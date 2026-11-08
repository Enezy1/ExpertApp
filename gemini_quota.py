# ===== gemini_quota.py — عدّاد حصص Gemini المحلي لكل (مفتاح، نموذج) (2026-10-23، السقف الناعم 2026-10-25) =====
# السبب: الطلب الفاشل بـ429 يُحتسب من حصة اليوم (20 لـFlash)، والإعادات المتكررة كانت تستهلكها بلا فائدة. العدّاد يتنبأ
# فقط: يتخطى النموذج المنتهي «قبل» الإرسال، ويؤخّر الطلب حتى تسمح حدود الدقيقة. ردّ 429 الفعلي يبقى المرجع الأخير
# (gemini_config.mark_exhausted). المفتاح المدفوع (Pro متاح) لا تُفرض عليه الحدود المحلية.
# الحصص تتجدد منتصف الليل بتوقيت المحيط الهادئ (America/Los_Angeles). الملف: %LOCALAPPDATA%\ExpertApp\gemini_quota.json
# الحدود الافتراضية أدناه، وتُعدَّل من [model_limits] في gemini_network.ini (مثل lite_rpd = 500، lite_soft_rpd = 300).
# نوع العمل (mode) يحدد سقف اليوم لكل نموذج Lite:
#   ui          عمل الواجهة المباشر (زر يضغطه الخبير): حتى rpd (500).
#   background  الافتراضي — خط البداية والتحويل والفرز التلقائي: السقف الناعم lite_soft_rpd (300)؛ عند بلوغه لـ3.5 ينتقل
#               الطلب مباشرة إلى 3.1، ويبقى الباقي حتى 500 احتياطاً للواجهة.
#   queue       طابور الملخصات الخلفي: queue_share (70%) من السقف الناعم.
import configparser
import json
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

DEFAULT_LIMITS = {
    'flash': {'rpm': 5, 'tpm': 250_000, 'rpd': 20},
    'lite': {'rpm': 15, 'tpm': 250_000, 'rpd': 500},
    'gemma': {'rpm': 30, 'tpm': 16_000, 'rpd': 14_400},
}
SOFT_RPD = {'lite': 300}                # السقف الناعم لأعمال الخلفية لكل نموذج ([model_limits] lite_soft_rpd)
QUEUE_SHARE = 0.7                       # طابور الملخصات يتوقف عند 70% من السقف الناعم ([model_limits] queue_share)
BACKGROUND_SHARE = QUEUE_SHARE          # الاسم القديم (توافق)
QUEUE_CASES_PER_DAY = 40                # سقف طابور الملخصات اليومي بالقضايا ([model_limits] queue_cases_per_day)
MODES = ('ui', 'background', 'queue')
CHARS_PER_TOKEN = 2.5
SECTION = 'model_limits'
PATH_OVERRIDE = None                    # الاختبارات توجّه الملف إلى مجلد مؤقت
INI_OVERRIDE = None                     # الاختبارات: dict بدل قراءة gemini_network.ini

_lock = threading.Lock()
_minute = {}                            # (kid، نموذج) ← deque[(وقت، توكن)] لآخر 60 ثانية (في الذاكرة)
_tls = threading.local()


def family(model):
    """'lite' | 'gemma' | 'flash' | 'pro' | None من اسم النموذج."""
    n = str(model or '').split('/')[-1].lower()
    if n.startswith('gemma'):
        return 'gemma'
    if 'flash-lite' in n or 'flash_lite' in n:
        return 'lite'
    if 'flash' in n:
        return 'flash'
    if 'pro' in n:
        return 'pro'
    return None


def estimate_tokens(contents):
    """تقدير التوكن من النصوص فقط (حرف ÷ 2.5). الملفات المرفوعة لا تُقدَّر هنا."""
    if isinstance(contents, str):
        return int(len(contents) / CHARS_PER_TOKEN)
    total = 0
    for c in contents or []:
        if isinstance(c, str):
            total += len(c)
    return int(total / CHARS_PER_TOKEN)


def _pacific():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo('America/Los_Angeles')
    except Exception:                       # بلا قاعدة مناطق (tzdata): UTC-8 ثابت — أبكر بساعة صيفاً فلا يتجاوز الحد
        return timezone(timedelta(hours=-8))


def pacific_day(now=None):
    """يوم الحصة الحالي 'YYYY-MM-DD' بتوقيت المحيط الهادئ."""
    t = datetime.fromtimestamp(now if now is not None else time.time(), _pacific())
    return t.strftime('%Y-%m-%d')


def next_reset(now=None):
    """وقت (epoch) منتصف الليل القادم بتوقيت المحيط الهادئ — تجدد الحصة."""
    tz = _pacific()
    t = datetime.fromtimestamp(now if now is not None else time.time(), tz)
    nxt = (t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.timestamp()


def _ini():
    if INI_OVERRIDE is not None:
        return dict(INI_OVERRIDE)
    cp = configparser.RawConfigParser()
    try:
        import gemini_config as gc
        cp.read(os.path.join(gc._app_dir(), gc._NET_INI_NAME), encoding='utf-8')
    except Exception:
        return {}
    return {k.lower(): v for k, v in cp.items(SECTION)} if cp.has_section(SECTION) else {}


def limits(model):
    """{'rpm','tpm','rpd'} لعائلة النموذج (الافتراضي + [model_limits])، أو None لنموذج بلا حدود محلية (Pro/غيره)."""
    fam = family(model)
    if fam not in DEFAULT_LIMITS:
        return None
    out = dict(DEFAULT_LIMITS[fam])
    ini = _ini()
    for k in out:
        try:
            out[k] = int(float(ini.get(f'{fam}_{k}', out[k])))
        except (TypeError, ValueError):
            pass
    return out


def queue_share():
    """حصة طابور الملخصات من السقف الناعم (queue_share، والاسم القديم background_share)."""
    ini = _ini()
    try:
        v = float(ini.get('queue_share', ini.get('background_share', QUEUE_SHARE)))
        return min(1.0, max(0.0, v))
    except (TypeError, ValueError):
        return QUEUE_SHARE


background_share = queue_share


def queue_cases_per_day():
    try:
        return max(0, int(float(_ini().get('queue_cases_per_day', QUEUE_CASES_PER_DAY))))
    except (TypeError, ValueError):
        return QUEUE_CASES_PER_DAY


def queue_room(kid, models, now=None):
    """هل بقي لطابور الملخصات مكان في حصة اليوم؟ True إن كان أحد نماذج Lite المعطاة تحت 70% من سقفه الناعم."""
    lite = [m for m in models or [] if family(m) == 'lite']
    if not lite:
        return True
    with _lock:
        counts = _load()['counts'].get(kid, {})
    return any(int(counts.get(m, 0)) < day_cap(m, 'queue') for m in lite)


def soft_rpd(model):
    """السقف الناعم اليومي لأعمال الخلفية لعائلة النموذج (Lite: 300)، أو None إن لم يكن لها سقف ناعم."""
    fam = family(model)
    if fam not in SOFT_RPD:
        return None
    try:
        return int(float(_ini().get(f'{fam}_soft_rpd', SOFT_RPD[fam])))
    except (TypeError, ValueError):
        return SOFT_RPD[fam]


def day_cap(model, mode=None):
    """سقف اليوم لهذا النموذج بحسب نوع العمل: ui ← rpd، background ← السقف الناعم، queue ← queue_share منه."""
    lim = limits(model)
    if lim is None:
        return None
    mode = mode or current_mode()
    if mode == 'ui':
        return lim['rpd']
    soft = min(soft_rpd(model) or lim['rpd'], lim['rpd'])
    return soft if mode == 'background' else int(soft * queue_share())


def _path():
    if PATH_OVERRIDE:
        return PATH_OVERRIDE
    import app_paths
    return app_paths.path('gemini_quota.json')


def _load():
    try:
        with open(_path(), encoding='utf-8') as f:
            s = json.load(f)
        if isinstance(s, dict) and s.get('day') == pacific_day():
            s.setdefault('counts', {})
            return s
    except (OSError, ValueError):
        pass
    return {'day': pacific_day(), 'counts': {}}


def _save(s):
    try:
        os.makedirs(os.path.dirname(_path()), exist_ok=True)
        tmp = _path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _path())
    except OSError:
        pass                                # العدّاد مساعد: فشل حفظه لا يوقف العمل


def used_today(kid, model):
    with _lock:
        return int(_load()['counts'].get(kid, {}).get(model, 0))


def usage(kid):
    """{نموذج: عدد طلبات اليوم} لهذا المفتاح."""
    with _lock:
        return dict(_load()['counts'].get(kid, {}))


def _window(kid, model, now):
    q = _minute.setdefault((kid, model), deque())
    while q and now - q[0][0] >= 60:
        q.popleft()
    return q


def current_mode():
    """نوع عمل هذا الخيط: 'ui' | 'background' (الافتراضي) | 'queue'."""
    return getattr(_tls, 'mode', None) or 'background'


def set_mode(mode):
    _tls.mode = mode if mode in MODES else None


@contextmanager
def mode(name):
    """طلبات هذا الخيط من نوع name (ui للأزرار المباشرة، queue لطابور الملخصات)."""
    prev = getattr(_tls, 'mode', None)
    set_mode(name)
    try:
        yield
    finally:
        _tls.mode = prev


def background():
    """طابور الملخصات (الاسم القديم): mode('queue')."""
    return mode('queue')


def is_background():
    return current_mode() == 'queue'


def check(kid, model, tokens=0, background=None, enforce=True, now=None, mode=None):
    """(مسموح؟، السبب 'day'|'minute'|'too_big'|''، ثوانٍ للانتظار). لا يسجّل شيئاً.
    mode: نوع العمل (الافتراضي نوع هذا الخيط)؛ background=True للتوافق = 'queue'."""
    lim = limits(model)
    if not enforce or lim is None:
        return True, '', 0.0
    now = time.time() if now is None else now
    if mode is None and background is not None:
        mode = 'queue' if background else 'ui'
    if tokens and tokens > lim['tpm']:
        return False, 'too_big', 0.0
    cap = day_cap(model, mode)
    with _lock:
        if int(_load()['counts'].get(kid, {}).get(model, 0)) >= cap:
            return False, 'day', 0.0
        q = _window(kid, model, now)
        wait = 0.0
        if len(q) >= lim['rpm']:
            wait = 60 - (now - q[len(q) - lim['rpm']][0])
        if tokens and q and sum(t for _a, t in q) + tokens > lim['tpm']:
            room = lim['tpm'] - tokens
            acc = sum(t for _a, t in q)
            for at, t in q:                         # أقدم الطلبات يخرج أولاً حتى يتسع الطلب
                if acc <= room:
                    break
                acc -= t
                wait = max(wait, 60 - (now - at))
    if wait > 0:
        return False, 'minute', round(wait + 0.5, 1)
    return True, '', 0.0


def record(kid, model, tokens=0, now=None):
    """طلب أُرسل فعلاً (نجح أو رُفض بـ429 — كلاهما يُحتسب)."""
    if limits(model) is None:
        return
    now = time.time() if now is None else now
    with _lock:
        _window(kid, model, now).append((now, int(tokens or 0)))
        s = _load()
        k = s['counts'].setdefault(kid, {})
        k[model] = int(k.get(model, 0)) + 1
        _save(s)


def mark_full(kid, model):
    """429 يومي فعلي: النموذج منتهٍ لبقية اليوم مهما قال العدّاد."""
    lim = limits(model)
    if lim is None:
        return
    with _lock:
        s = _load()
        k = s['counts'].setdefault(kid, {})
        k[model] = max(int(k.get(model, 0)), lim['rpd'])
        _save(s)


def reset_memory():
    """للاختبارات: يفرّغ نوافذ الدقيقة."""
    with _lock:
        _minute.clear()
