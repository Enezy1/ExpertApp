# ===== ai_call_log.py — سجل استدعاءات مزوّد الذكاء الاصطناعي من خطوات التقرير =====
# كل استدعاء (الغرض، المزوّد، المدة، النجاح أو نص الخطأ) يُكتب في %LOCALAPPDATA%\ExpertApp\ai_calls.log
# ويُحفظ آخر 50 منها في الذاكرة لتعرضها صفحة القضية للخبير («آخر استدعاء: …»).
# wrap(ask, purpose, base=) يغلّف أي دالة ask(prompt) -> نص دون تغيير سلوكها (الاستثناء يمرّ كما هو بعد تسجيله).
# سجل الطلبات داخل القضية (2026-10-21): مع base يُحفظ كل طلب في <القضية>/_نظام/سجلات/طلبات_الذكاء/ كملف JSON واحد:
#   الوقت، الخطوة (purpose) وتفصيلها (detail)، المزوّد والنموذج وصاحب المفتاح، الطلب والرد كاملين، المدة، الأحجام،
#   وحكم التحقق (verdict) وهل أُعيد الطلب (retried). لا يُكتب أي مفتاح أو سر (scrub). السجل مساعد: فشله لا يوقف العمل.
# verdict(ok, reason) يستدعيها المتحقق بعد قراءة الرد؛ detail(text) تضع تفصيل الخطوة (اسم الملف/المحور/المحاولة) قبل الطلب.
import json
import os
import re
import threading
import time
from collections import deque
from datetime import datetime

_recent = deque(maxlen=50)
_lock = threading.Lock()
_local = threading.local()
PATH_OVERRIDE = None                    # الاختبارات توجّه السجل إلى مجلد مؤقت
REQ_DIR = ('_نظام', 'سجلات', 'طلبات_الذكاء')
_GSK = re.compile(r'\bgsk_[0-9A-Za-z]{16,}|\bsk-ant-[0-9A-Za-z_\-]{10,}')


def req_dir(base):
    return os.path.join(base, *REQ_DIR)


def scrub(text):
    """يخفي أي مفتاح محتمل (gemini_config.redact + مفاتيح Groq/Anthropic) من نص يُحفظ في السجل."""
    text = str(text if text is not None else '')
    try:
        import gemini_config as gc
        text = gc.redact(text)
    except Exception:
        pass
    return _GSK.sub('***', text)


def log_path():
    if PATH_OVERRIDE:
        return PATH_OVERRIDE
    import app_paths                        # الاختبارات: مجلد مؤقت (EXPERTAPP_LOG_DIR) لا السجل الحقيقي
    return app_paths.path('ai_calls.log')


def set_provider(name, model=''):
    """يستدعيها المزوّد الفعلي (case_research.default_ask) ليُعرف اسم/نموذج من أجاب في هذا الخيط."""
    _local.provider = name or ''
    _local.model = model or ''


def last_provider():
    return getattr(_local, 'provider', '')


def last_model():
    return getattr(_local, 'model', '')


def _write(rec):
    line = (f"{rec['at']} | {rec['purpose']} | {rec['provider'] or '—'} | "
            f"{'OK' if rec['ok'] else 'FAIL'} | {rec['secs']:.1f}s | {rec['detail']}\n")
    try:
        os.makedirs(os.path.dirname(log_path()), exist_ok=True)
        with open(log_path(), 'a', encoding='utf-8') as f:
            f.write(line)
    except OSError:
        pass                                # السجل مساعد: فشله لا يوقف العمل


def record(purpose, ok, provider='', secs=0.0, detail=''):
    detail = scrub(detail)                             # أي مفتاح في نص الخطأ يُخفى قبل السجل
    rec = {'at': datetime.now().isoformat(timespec='seconds'), 'purpose': purpose, 'ok': bool(ok),
           'provider': provider or '', 'secs': float(secs), 'detail': str(detail or '')[:300]}
    with _lock:
        _recent.append(rec)
    _write(rec)
    return rec


# ---------- سجل الطلبات داخل القضية ----------

def detail(text=''):
    """تفصيل الخطوة للطلب التالي في هذا الخيط (اسم الملف / «خانات التقرير — محاولة 2»…)؛ يُصفَّر بعد الطلب."""
    _local.detail = str(text or '')


def key_owner(label):
    """«مفتاحك» / «مفتاح القسم» / '' من اسم المزوّد كما يسجّله ai_providers.provider_label."""
    label = label or ''
    if 'مفتاح القسم' in label:
        return 'مفتاح القسم'
    return 'مفتاحك' if 'مفتاحك' in label else ''


def _save_req(path, rec):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({k: v for k, v in rec.items() if k != 'base'}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass


def _slug(text):
    return re.sub(r'[^\w\-]+', '_', text, flags=re.U).strip('_')[:30] or 'طلب'


def _write_req(base, purpose, prompt, response, ok, error, secs, started):
    """ملف واحد للطلب (اسمه: رقم_وقت_خطوة.json). فشل الكتابة صامت."""
    try:
        d = req_dir(base)
        os.makedirs(d, exist_ok=True)
        with _lock:
            seq = 1 + max([int(n[:4]) for n in os.listdir(d) if n[:4].isdigit() and n.endswith('.json')] or [0])
            prov = getattr(_local, 'provider', '')
            prev = getattr(_local, 'last_req', None)
            # إعادة = نفس الخطوة في نفس القضية بعد طلب سابق فشل أو رُفض في التحقق
            retry = bool(prev and prev[1].get('base') == base and prev[1].get('step') == purpose
                         and (not prev[1].get('ok') or (prev[1].get('verdict') or {}).get('ok') is False))
            if retry:
                prev[1]['retried'] = True
                _save_req(prev[0], prev[1])
            rec = {'id': seq, 'at': datetime.fromtimestamp(started).isoformat(timespec='seconds'), 'step': purpose,
                   'detail': getattr(_local, 'detail', ''), 'provider': prov, 'model': getattr(_local, 'model', ''),
                   'key_owner': key_owner(prov), 'prompt': scrub(prompt), 'response': scrub(response),
                   'secs': round(secs, 1), 'prompt_chars': len(prompt or ''), 'response_chars': len(response or ''),
                   'ok': bool(ok), 'error': scrub(error), 'verdict': None, 'is_retry': retry, 'retried': False}
            path = os.path.join(d, f"{seq:04d}_{datetime.fromtimestamp(started).strftime('%H%M%S')}_{_slug(purpose)}.json")
            _save_req(path, rec)
            rec['base'] = base
            _local.last_req = (path, rec)
    except Exception:
        pass


def verdict(ok, reason=''):
    """حكم التحقق على آخر طلب في هذا الخيط: ok=False ← «رُفض» مع السبب. يُحدَّث ملف الطلب. لا يرفع استثناء."""
    try:
        cur = getattr(_local, 'last_req', None)
        if not cur:
            return
        path, rec = cur
        rec['verdict'] = {'ok': bool(ok), 'reason': scrub(reason)[:500]}
        _save_req(path, rec)
    except Exception:
        pass


def wrap(ask, purpose, base=None):
    """ask مغلَّفة بالتسجيل. ask=None ← None. مع base يُحفظ كل طلب كاملاً في سجل القضية أيضاً."""
    if ask is None:
        return None

    def call(prompt):
        _local.provider = ''
        _local.model = ''
        t = time.time()
        try:
            out = ask(prompt)
        except BaseException as e:
            msg = str(e) or e.__class__.__name__
            record(purpose, False, getattr(_local, 'provider', ''), time.time() - t, msg)
            if base:
                _write_req(base, purpose, prompt, '', False, msg, time.time() - t, t)
            _local.detail = ''
            raise
        record(purpose, True, getattr(_local, 'provider', ''), time.time() - t,
               f'{len(out or "")} حرفاً' if (out or '').strip() else 'ردّ فارغ')
        if base:
            text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, default=str)
            _write_req(base, purpose, prompt, text, True, '', time.time() - t, t)
            if not (text or '').strip():
                verdict(False, 'ردّ فارغ')
        _local.detail = ''
        return out
    return call


def list_requests(base):
    """[سجل الطلب] الأقدم أولاً؛ التالف يُتخطّى. كل سجل فيه 'file' (مساره)."""
    out = []
    d = req_dir(base)
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith('.json'))
    except OSError:
        return out
    for n in names:
        try:
            with open(os.path.join(d, n), encoding='utf-8') as f:
                rec = json.load(f)
            rec['file'] = os.path.join(d, n)
            out.append(rec)
        except (OSError, ValueError):
            continue
    return out


def outcome(rec):
    """(✓/✗، نص) لنتيجة الطلب: فشل الاتصال، أو رفض التحقق، أو نجاح."""
    if not rec.get('ok'):
        return '✗', 'فشل الاتصال: ' + (rec.get('error') or '')
    v = rec.get('verdict')
    if v and v.get('ok') is False:
        return '✗', 'رُفض في التحقق: ' + (v.get('reason') or '')
    return '✓', ('تحقق: ' + v['reason']) if v and v.get('reason') else 'نجح'


def last(purpose=None, since=None):
    """آخر سجل (لغرض معيّن إن طُلب، وبعد الوقت since إن طُلب)، أو None."""
    with _lock:
        for rec in reversed(_recent):
            if (purpose is None or rec['purpose'] == purpose) and (since is None or rec['at'] >= since):
                return rec
    return None


def describe(rec):
    """سطر عربي للعرض."""
    if rec is None:
        return ''
    who = f"المزوّد: {rec['provider']}" if rec['provider'] else 'المزوّد: غير معروف'
    if rec['ok']:
        return f"آخر استدعاء للذكاء الاصطناعي نجح ({who}، {rec['secs']:.0f} ث، {rec['detail']})"
    return f"فشل استدعاء الذكاء الاصطناعي ({who}، {rec['secs']:.0f} ث): {rec['detail']}"
