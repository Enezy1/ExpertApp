# ===== ocr_vision.py — Google Cloud Vision (DOCUMENT_TEXT_DETECTION) محرّك OCR اختياري بمفتاح API (2026-10-17) =====
# يُستعمل بعد Gemini وقبل OCR الخارجي/المحلي. المفتاح خاص بالخبير الحالي (vision_key.json) ولا يوجد افتراضي.
# كل صفحة صورة JPEG بجودتها الأصلية (dpi قابل للضبط) في طلب REST واحد. لا يُضمَّن أي مفتاح في الكود.
import base64
import os

import gemini_config as gc
import secret_store
from current_expert import expert_data_dir

URL = 'https://vision.googleapis.com/v1/images:annotate'
LABEL = 'Google Cloud Vision'
DPI = 200


class VisionFailed(Exception):
    pass


def _key_path():
    return os.path.join(expert_data_dir(), 'vision_key.json')


def save_key(key):
    secret_store.write_key(_key_path(), 'vision_api_key', key)      # مشفّر بـDPAPI


def load_key():
    return secret_store.read_key(_key_path(), 'vision_api_key')     # نص صريح قديم ← يُرحَّل ويُستبدل


def is_available():
    return bool(load_key())


def _post(jpg, route, key):
    import requests
    s = requests.Session()
    proxy = gc.get_proxy_url()
    if route == gc.ROUTE_DIRECT or proxy:
        s.trust_env = False
    if route == gc.ROUTE_PROXY and proxy:
        s.proxies = {'http': proxy, 'https': proxy}
    body = {'requests': [{'image': {'content': base64.b64encode(jpg).decode()},
                          'features': [{'type': 'DOCUMENT_TEXT_DETECTION'}],
                          'imageContext': {'languageHints': ['ar', 'en']}}]}
    try:
        # المفتاح في ترويسة لا في الرابط، فلا يظهر في رسائل أخطاء الشبكة ولا السجل
        r = s.post(URL, headers={'X-Goog-Api-Key': key}, json=body, timeout=60)
    finally:
        s.close()
    if r.status_code >= 400:
        raise VisionFailed(f'Cloud Vision HTTP {r.status_code}: {r.text[:300]}')
    resp = (r.json().get('responses') or [{}])[0]
    if resp.get('error'):
        raise VisionFailed(f"Cloud Vision: {resp['error'].get('message')}")
    return ((resp.get('fullTextAnnotation') or {}).get('text') or '').strip()


def ocr_pages(pdf_path, idx, route):
    """يقرأ الصفحات idx (من 0) ويرجع نصاً بعلامة «--- صفحة N ---» لكل صفحة، أو يرفع VisionFailed."""
    import fitz
    key = load_key()
    if not key:
        raise VisionFailed('لا يوجد مفتاح Google Cloud Vision')
    out = []
    with fitz.open(pdf_path) as doc:
        for i in idx:
            jpg = doc[i].get_pixmap(dpi=DPI).tobytes('jpeg', jpg_quality=90)
            try:
                text = _post(jpg, route, key)
            except Exception as e:
                gc.note_personal_failure(LABEL, e)           # مفتاح الخبير الشخصي فقط (لا مفتاح قسم لـVision)
                raise
            if not text:
                raise VisionFailed(f'صفحة {i + 1}: لم يُستخرج نص')
            out.append(f'--- صفحة {i + 1} ---\n{text}')
    return '\n'.join(out)


def test():
    """(ok، رسالة): صفحة صغيرة فيها نص عربي."""
    import tempfile
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=420, height=160)
    page.insert_htmlbox(page.rect + (20, 20, -20, -20),
                        '<p dir="rtl" style="font-size:24px">حكمت المحكمة بندب خبير من إدارة الخبراء</p>')
    fd, tmp = tempfile.mkstemp(suffix='.pdf', prefix='vision_')
    os.close(fd)
    doc.save(tmp)
    doc.close()
    try:
        text = gc._run_with_routes(lambda route: ocr_pages(tmp, [0], route), 0, 60)
        return True, ' '.join(text.splitlines()[1:])
    except Exception as e:
        return False, gc.short_error(e)
    finally:
        os.remove(tmp)
