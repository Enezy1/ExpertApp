# ===== ocr_space.py — قراءة الصفحات الممسوحة عبر OCR.space (ضمن شروط الخطة المجانية) =====
"""
شروط الخطة المجانية التي يلتزم بها هذا الملف:
  - حجم الملف ≤ 1MB      → كل صفحة تُرسل كصورة JPEG رمادية مستقلة، تُصغَّر حتى تقل عن الحد.
  - 3 صفحات لكل PDF     → لا نرسل PDF أصلًا، صفحة واحدة لكل طلب.
  - 500 طلب/يوم لكل IP  → عداد يومي.
  - 25,000 طلب/شهر       → عداد شهري (المحرك 2 يدخل ضمنه).
  - المحرك 3: 1,000/شهر   → عداد مستقل؛ عند نفاده نستخدم المحرك 2 مباشرة.
المحرك 1 لا يدعم العربي. المحرك 3 يرجع أحيانًا نصًا فاضيًا بلا خطأ → نعيد الصفحة بالمحرك 2.
الحدود والمفتاح في gemini_network.ini قسم [provider:ocrspace].
"""
import base64
import configparser
import json
import os
import re
from datetime import datetime

import gemini_config as gc

_QUOTA_PATH = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'ocr_quota.json')
_DEFAULTS = {
    'base_url': 'https://api.ocr.space/parse/image', 'api_key': '', 'enabled': '1',
    'daily_limit': '500', 'monthly_limit': '25000', 'engine3_monthly_limit': '1000',
    'safety_margin': '0.95', 'dpi': '200', 'jpeg_quality': '75', 'max_kb': '950',
    'min_arabic_chars': '20', 'timeout': '60',
}
_ARABIC = re.compile(r'[؀-ۿ]')
_LETTER = re.compile(r'[^\W\d_]')


class OCRFailed(Exception):
    pass


def get_settings():
    cfg = dict(_DEFAULTS)
    try:
        cp = configparser.ConfigParser()
        cp.read(os.path.join(gc._app_dir(), gc._NET_INI_NAME), encoding='utf-8')
        if cp.has_section('provider:ocrspace'):
            cfg.update({k: v.strip() for k, v in cp.items('provider:ocrspace')})
    except Exception:
        pass
    cfg['key_type'] = 'افتراضي'
    try:  # إعدادات القسم (Supabase) تتقدم على الملف المحلي
        import provider_sync
        row = next((r for r in provider_sync.get_configs() if r['name'] == 'ocrspace'), None)
        if row:
            cfg.update({k: str(v) for k, v in row.items() if v not in (None, '')})
            cfg['enabled'] = '1' if row.get('enabled') else '0'
    except Exception:
        pass
    own = gc.load_ocr_key()
    if own:  # مفتاح الخبير الخاص يُستخدم دائمًا بدل مفتاح القسم
        cfg.update(api_key=own, enabled='1', key_type='خاص')
    return cfg


def _quota_path():
    """عداد مستقل للمفتاح الخاص (حدوده تخص حساب الخبير نفسه)."""
    if gc.load_ocr_key():
        return os.path.join(gc.expert_data_dir(), 'ocr_quota.json')
    return _QUOTA_PATH


def is_available():
    c = get_settings()
    return bool(c['api_key']) and c['enabled'].lower() not in ('0', 'false', 'no')


# ===== العدادات =====
def _load_quota():
    now = datetime.now()
    q = {'month': now.strftime('%Y-%m'), 'day': now.strftime('%Y-%m-%d'),
         'month_total': 0, 'month_e3': 0, 'day_total': 0}
    try:
        with open(_quota_path(), encoding='utf-8') as f:
            old = json.load(f)
        if old.get('month') == q['month']:
            q['month_total'], q['month_e3'] = old.get('month_total', 0), old.get('month_e3', 0)
            if old.get('day') == q['day']:
                q['day_total'] = old.get('day_total', 0)
    except Exception:
        pass
    return q


def _count(engine):
    q = _load_quota()
    q['month_total'] += 1
    q['day_total'] += 1
    if engine == 3:
        q['month_e3'] += 1
    try:
        os.makedirs(os.path.dirname(_quota_path()), exist_ok=True)
        with open(_quota_path(), 'w', encoding='utf-8') as f:
            json.dump(q, f)
    except Exception:
        pass


def quota_status():
    return _load_quota()


def _allowed(engine, pages_needed):
    """هل يسمح الحد بـpages_needed طلبًا إضافيًا (مع هامش أمان)؟"""
    c, q = get_settings(), _load_quota()
    m = float(c['safety_margin'])
    if q['day_total'] + pages_needed > int(c['daily_limit']) * m:
        return False
    if q['month_total'] + pages_needed > int(c['monthly_limit']) * m:
        return False
    if engine == 3 and q['month_e3'] + pages_needed > int(c['engine3_monthly_limit']) * m:
        return False
    return True


# ===== القراءة =====
def _page_jpeg(page, c):
    import fitz
    dpi, max_b = int(c['dpi']), int(c['max_kb']) * 1024
    while True:
        jpg = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY).tobytes(
            'jpeg', jpg_quality=int(c['jpeg_quality']))
        # base64 يكبّر الحجم بالثلث — الحد 1MB على الطلب
        if len(jpg) * 4 / 3 < max_b or dpi <= 100:
            return jpg
        dpi -= 25


def _post(jpg, engine, route, c):
    import requests
    s = requests.Session()
    proxy = gc.get_proxy_url()
    if route == gc.ROUTE_DIRECT or proxy:
        s.trust_env = False
    if route == gc.ROUTE_PROXY and proxy:
        s.proxies = {'http': proxy, 'https': proxy}
    try:
        r = s.post(c['base_url'], headers={'apikey': c['api_key']}, timeout=int(c['timeout']), data={
            'language': 'ara' if engine == 3 else 'auto', 'OCREngine': engine,
            'scale': 'true', 'detectOrientation': 'true',
            'base64Image': 'data:image/jpeg;base64,' + base64.b64encode(jpg).decode()})
    finally:
        s.close()
    _count(engine)
    if r.status_code >= 400:
        raise OCRFailed(f'OCR.space HTTP {r.status_code}: {r.text[:300]}')
    j = r.json()
    if j.get('IsErroredOnProcessing'):
        raise OCRFailed(f"OCR.space engine {engine}: {j.get('ErrorMessage')}")
    return '\n'.join(p.get('ParsedText', '') for p in j.get('ParsedResults') or []).strip()


def _looks_valid(text, c):
    """صفحة مقلوبة/مشوشة تعطي نصًا قليلًا أو حروفًا غير عربية."""
    ar = len(_ARABIC.findall(text))
    letters = len(_LETTER.findall(text)) or 1
    return ar >= int(c['min_arabic_chars']) and ar / letters >= 0.5


def ocr_pages(pdf_path, idx, route):
    """يقرأ الصفحات idx (من 0) ويرجع نصًا واحدًا بالترتيب، أو يرفع OCRFailed."""
    import fitz
    c = get_settings()
    if not is_available():
        raise OCRFailed('OCR.space غير مفعّل أو بدون مفتاح')
    if not _allowed(2, len(idx)):
        raise OCRFailed('تم بلوغ حد الاستخدام اليومي/الشهري لـOCR.space')
    use_e3 = _allowed(3, len(idx))
    gc.set_log_provider('OCR.space', c['key_type'])  # يعمل بخيط المهلة — السياق لا ينتقل تلقائيًا
    doc = fitz.open(pdf_path)
    out = []
    try:
        for i in idx:
            jpg = _page_jpeg(doc[i], c)
            text, engine = '', 3 if use_e3 else 2
            if use_e3:
                try:
                    text = _post(jpg, 3, route, c)
                except OCRFailed as e:
                    # حد المحرك 3 أو خطأ منه → المحرك 2 لباقي الصفحات
                    gc._log(route, 'OCR-E3-FAIL', error=e, note='→ المحرك 2')
                    use_e3 = False
            if not _looks_valid(text, c):
                engine = 2
                text = _post(jpg, 2, route, c)
            if not _looks_valid(text, c):
                raise OCRFailed(f'صفحة {i + 1}: نص غير مقروء ({len(text)} حرف) — ربما مقلوبة أو غير واضحة')
            gc._log(route, 'OCR-PAGE', len(jpg), note=f'صفحة {i + 1} | محرك {engine} | {len(text)} حرف')
            out.append(f'--- صفحة {i + 1} ---\n{text}')
    except Exception as e:
        if c['key_type'] == 'خاص':                       # مفتاحك الشخصي فشل: يُبلَّغ الخبير ولا يُستعمل مفتاح القسم
            gc.note_personal_failure('OCR.space', e)
        raise
    finally:
        doc.close()
    return '\n\n'.join(out)
