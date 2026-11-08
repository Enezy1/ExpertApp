# ===== provider_sync.py — توزيع مفاتيح المزودات على القسم عبر Supabase =====
"""
تخزين بسيط بدون جدول جديد: الصف id=2 في جدول app_version الموجود
(الصف id=1 يخص التحديث التلقائي ولا يُلمس). folder_path يحمل JSON بقائمة المزودات.

- الأدمن يحفظ/يفعّل مزودًا من صفحة الإعدادات → يُكتب في الصف مباشرة.
- كل نسخة عند التشغيل تجلب الصف (بنفس منطق البروكسي/المباشر) وتحفظ آخر نسخة
  ناجحة محليًا. تعذّر الاتصال → النسخة المحلية؛ لا توجد → ملف الإعدادات المحلي
  ومفتاح المستخدم بدون أي خطأ.
- المفاتيح لا تُكتب في السجل أو رسائل الخطأ.
"""
import json
import os
import threading

import gemini_config as gc
import secret_store
from config import SUPABASE_URL, SUPABASE_KEY

_URL = f'{SUPABASE_URL}/rest/v1/app_version'
_ROW_ID = 2
_MARK = 'ai_providers'
_CACHE_PATH = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'ai_providers_cache.json')
_HEADERS = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json'}

_lock = threading.Lock()
_state = {'rows': None, 'source': 'لم يُجلب بعد', 'loaded': False, 'last_error': ''}


def _request(method, **kw):
    """طلب Supabase بمنطق البروكسي/المباشر نفسه. يرجع requests.Response."""
    import requests

    def call(route):
        s = requests.Session()
        proxy = gc.get_proxy_url()
        if route == gc.ROUTE_DIRECT or proxy:
            s.trust_env = False
        if route == gc.ROUTE_PROXY and proxy:
            s.proxies = {'http': proxy, 'https': proxy}
        try:
            return s.request(method, _URL, headers=dict(_HEADERS, **kw.pop('headers', {})),
                             timeout=15, **kw)
        finally:
            s.close()
    gc.set_log_provider('Supabase', '-')
    return gc._run_with_routes(call, 0, 20)


def _save_cache(rows):
    """النسخة المحلية لمفاتيح القسم: كل api_key مشفّر بـDPAPI لمستخدم ويندوز («dpapi:…»).
    تعذّر التشفير ⇒ لا نكتب نصاً صريحاً أبداً (يبقى الملف السابق/لا ملف)."""
    try:
        secret_store.atomic_write_json(_CACHE_PATH, secret_store.protect_rows(rows))
    except Exception:
        pass


def _load_cache():
    """يقرأ النسخة المحلية ويفكّ التشفير. ملف قديم بمفاتيح صريحة يُرحَّل فوراً (يُعاد كتابته مشفّراً)."""
    try:
        with open(_CACHE_PATH, encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return None
    rows, legacy = secret_store.unprotect_rows(raw)
    if legacy:
        _save_cache(rows)
    return rows


def refresh():
    """يجلب الإعدادات من Supabase؛ يرجع للنسخة المحلية عند الفشل. يُسجَّل المصدر."""
    try:
        r = _request('GET', params={'id': f'eq.{_ROW_ID}', 'select': 'version,folder_path'})
        if r.status_code >= 400:
            raise RuntimeError(f'HTTP {r.status_code}: {r.text[:200]}')
        data = r.json()
        rows = json.loads(data[0]['folder_path'] or '[]') if data and data[0].get('version') == _MARK else []
        _save_cache(rows)
        with _lock:
            _state.update(rows=rows, source='Supabase', loaded=True, last_error='')
        gc._log(gc._net_state['route'], 'CONFIG-OK', note=f'Supabase | {len(rows)} مزود')
    except Exception as e:
        rows = _load_cache()
        src = 'نسخة محلية' if rows is not None else 'لا يوجد'
        with _lock:
            _state.update(rows=rows, source=src, loaded=True, last_error=gc.short_error(e))
        gc._log(gc._net_state['route'], 'CONFIG-FAIL', error=e, note=f'المصدر المستخدم: {src}')


def start_refresh():
    """جلب بالخلفية عند تشغيل البرنامج. (يُعاد الجلب أيضًا قبل كل طلب استخراج —
    gemini_config.generate_from_pdf — فالإيقاف من الأدمن يسري من الطلب التالي.)"""
    threading.Thread(target=lambda: (migrate_local_secrets(), refresh()), daemon=True).start()


def migrate_local_secrets():
    """ترحيل تلقائي لمرة واحدة: أي مفتاح محلي بنص صريح (نسخة القسم + مفاتيح الخبير الشخصية) يُعاد كتابته مشفّراً
    بـDPAPI ويُحذف النص الصريح. القراءة نفسها تُرحِّل، فنقرأ الكل مرة عند التشغيل."""
    for f in (_load_cache, gc.load_api_key, gc.load_ocr_key, gc.load_openai_key):
        try:
            f()
        except Exception:
            pass
    try:
        import ocr_vision
        ocr_vision.load_key()
    except Exception:
        pass


_SHARE = '_share'  # صف خاص: هل مفاتيح الأدمن متاحة للقسم


def _all_rows():
    with _lock:
        rows, loaded = _state['rows'], _state['loaded']
    if not loaded:
        rows = _load_cache()
    return [dict(r) for r in (rows or [])]


def is_shared():
    """مشاركة مفاتيح الأدمن مع القسم مفعّلة؟ (الافتراضي: نعم)"""
    row = next((r for r in _all_rows() if r.get('name') == _SHARE), None)
    return True if row is None else bool(row.get('enabled'))


def get_configs():
    """صفوف المزودات (dict لكل مزود). لو المشاركة موقوفة: لا شيء لغير الأدمن.
    لا شبكة هنا."""
    rows = [r for r in _all_rows() if r.get('name') != _SHARE]
    if not is_shared() and not gc.is_admin():
        return []
    return rows


def set_shared(enabled):
    """تفعيل/إيقاف استخدام القسم لمفاتيح الأدمن. يرجع (ok, رسالة)."""
    ok, msg = upsert(_SHARE, {'enabled': bool(enabled)})
    if ok:
        msg = 'تم تفعيل مفاتيحك للقسم' if enabled else 'تم إيقاف مفاتيحك عن القسم'
    return ok, msg


def status():
    return {'source': _state['source'], 'last_error': _state['last_error']}


def upsert(name, fields):
    """يحفظ مزودًا واحدًا (يدمجه مع الباقين) ويرفع القائمة كاملة. يرجع (ok, رسالة)."""
    if not gc.is_admin():
        return False, 'غير مخوّل'
    refresh()  # آخر نسخة قبل الدمج حتى لا نمسح تعديلًا من جهاز آخر
    if _state['source'] != 'Supabase':
        return False, 'تعذر الاتصال بـSupabase — لم يُحفظ شيء، حاول لاحقًا'
    rows = {r['name']: r for r in _all_rows()}
    row = dict(rows.get(name, {}), name=name)
    for k, v in fields.items():
        if k == 'options':
            row.update({ok: str(ov) for ok, ov in (v or {}).items()})
        elif v is not None:
            row[k] = v
    row.setdefault('api_key', '')
    rows[name] = row
    try:
        r = _request('POST', json={'id': _ROW_ID, 'version': _MARK,
                                   'folder_path': json.dumps(list(rows.values()), ensure_ascii=False)},
                     headers={'Prefer': 'resolution=merge-duplicates,return=minimal'})
        if r.status_code >= 400:
            return False, f'رفض Supabase الحفظ (HTTP {r.status_code})'
    except Exception as e:
        return False, f'تعذر الحفظ: {type(e).__name__}'
    refresh()
    return True, 'تم الحفظ والتفعيل للقسم'
