# ===== page_orient.py — كشف اتجاه الصفحة الممسوحة وتصحيحه (0/90/180/270) على الجهاز =====
"""أحكام تُمسح أحياناً مقلوبة (180°) أو جانبية (90°/270°). القراءة والذكاء يفشلان معها.

الطريقة (بنفس محرّك OCR الداخلي، بلا نماذج إضافية):
  1) اتجاه الأسطر: كاشف الأسطر على الصفحة كما هي وعلى نسخة مدوّرة 90° — الأسطر الأفقية صناديقها عريضة.
  2) مقلوبة أم لا: قراءة عيّنة من الأسطر كما هي ومقلوبة 180° — الاتجاه الصحيح تكون ثقة القراءة فيه أعلى.
أي فشل أو شك ⇒ 0 (لا تدوير). التدوير الخاطئ أسوأ من تركها.
"""
MAX_SIDE = 1200      # تصغير الصفحة للكشف (يكفي لاتجاه الأسطر)
SAMPLE = 8           # عدد الأسطر المقروءة لاختبار القلب
WIDE = 1.5           # صندوق عرضه ≥ 1.5 ارتفاعه = سطر أفقي
HORIZ_OK = 0.6       # نسبة الأسطر الأفقية التي نعدّ بها الصفحة مستقيمة الأسطر
FLIP_MARGIN = 0.04   # لا نقلب إلا إذا زادت ثقة المقلوبة بهذا الفارق


def _engine():
    import local_ocr
    return local_ocr._get_engine()


def _wide_boxes(eng, img):
    np = eng.np
    boxes = eng.detect(img)
    wide = []
    for b in boxes:
        w = max(np.linalg.norm(b[0] - b[1]), np.linalg.norm(b[2] - b[3]))
        h = max(np.linalg.norm(b[0] - b[3]), np.linalg.norm(b[1] - b[2]))
        if w >= WIDE * h:
            wide.append((w, b))
    return len(boxes), wide


def _conf(eng, crops):
    cs = [c for chars in eng._run_rec(crops) for _x, ch, c in chars if ch.strip()]   # قراءة خام أسرع من recognize
    return sum(cs) / len(cs) if cs else 0.0


def rotation_needed(png: bytes) -> int:
    """الدرجات (باتجاه عقارب الساعة) اللازمة لتصير الصفحة مستقيمة: 0 أو 90 أو 180 أو 270."""
    try:
        eng = _engine()
        cv2, np = eng.cv2, eng.np
        img = cv2.imdecode(np.frombuffer(png, 'uint8'), cv2.IMREAD_COLOR)
        if img is None:
            return 0
        f = min(1.0, MAX_SIDE / max(img.shape[:2]))
        if f < 1.0:
            img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        n0, wide0 = _wide_boxes(eng, img)
        base, angle, wide = img, 0, wide0
        if n0 < 3 or len(wide0) < HORIZ_OK * n0:
            img90 = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
            n90, wide90 = _wide_boxes(eng, img90)
            if n90 >= 3 and len(wide90) / n90 > len(wide0) / max(n0, 1) + 0.2:
                base, angle, wide = img90, 90, wide90
        if len(wide) < 3:
            return 0 if angle == 0 else angle      # جانبية واضحة لكن لا أسطر كافية لاختبار القلب
        wide.sort(key=lambda t: -t[0])
        crops = [eng.crop(base, b) for _w, b in wide[:SAMPLE]]
        flipped = [cv2.rotate(c, cv2.ROTATE_180) for c in crops]
        if _conf(eng, flipped) > _conf(eng, crops) + FLIP_MARGIN:
            angle += 180
        return angle % 360
    except Exception:
        return 0


def fix_png(png: bytes):
    """(PNG مستقيمة، الدرجات المطبّقة)."""
    rot = rotation_needed(png)
    if not rot:
        return png, 0
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(png, 'uint8'), cv2.IMREAD_COLOR)
        code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rot]
        ok, buf = cv2.imencode('.png', cv2.rotate(img, code))
        return (buf.tobytes(), rot) if ok else (png, 0)
    except Exception:
        return png, 0
