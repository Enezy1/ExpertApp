# ===== local_ocr.py — قراءة الصفحات الممسوحة على الجهاز (بلا إنترنت) =====
"""الطبقة التي يستخدمها البرنامج فوق ocr_engine.py.

read_pages(pdf, idx) ← نص بنفس صيغة prepare_pdf ("--- صفحة N ---") + تقييم كل صفحة:
  - weak: قراءة ضعيفة (ضجيج في الكلمات أو ثقة منهارة) — لا يُعتمد عليها.
  - indic: أرقام الصفحة هندية (٠١٢٣…). المحرّك الداخلي يخطئ فيها كثيراً (قيس على 38 رقماً من أحكام حقيقية:
    11 صحيحة فقط، والخطأ "معقول" 2024/3290 بدل 2024/3295)، فالتواريخ والأرقام تُؤخذ من OCR أونلاين أو الذكاء.
    الأرقام الإنجليزية يقرؤها جيداً.
  - table: جدول بشبكة خطوط داخلية.
النص (الكلمات) دقيق ~97% بعد تقويم الميل، فيكفي للتلخيص حتى مع بعض الأخطاء.

أي فشل (مكتبة ناقصة، نموذج مفقود، صفحة تالفة) ← available()=False أو استثناء يلتقطه المستدعي ويكمل بالمسار القديم.
"""
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field

RENDER_DPI = 300          # النموذج العربي أدق كلما كبرت الحروف (200 تضيّع أرقاماً)
WEAK_NOISE = 0.10         # ≥10% من الكلمات ضجيج ⇒ قراءة ضعيفة (قيس على 107 صفحة: 11 ضعيفة، كلها فعلاً كذلك)
WEAK_MEAN_CONF = 0.55
MARGIN = 0.12

_lock = threading.Lock()
_engine = None
_engine_error = ''


def _root():
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'ocr')


def available():
    """المحرّك جاهز للاستخدام (المكتبات والنماذج موجودة ويُحمَّل بلا خطأ)."""
    try:
        _get_engine()
        return True
    except Exception:
        return False


def _get_engine():
    global _engine, _engine_error
    if _engine is not None:
        return _engine
    if _engine_error:
        raise RuntimeError(_engine_error)
    with _lock:
        if _engine is None:
            try:
                from ocr_engine import Engine
                _engine = Engine(_root())
            except Exception as e:
                _engine_error = f'{type(e).__name__}: {e}'
                raise RuntimeError(_engine_error)
    return _engine


# ------------------------------------------------------------ صورة الصفحة

def _page_png(page):
    """(PNG، معامل التكبير). صورة مسح واحدة مستقيمة بدقة أقل من 250 نقطة تُؤخذ كما هي ويكبّرها المحرّك تكبيراً
    ناعماً (أدق من إعادة رسمها)، وإلا تُرسم الصفحة بدقة RENDER_DPI."""
    import fitz
    try:
        infos = page.get_image_info(xrefs=True)
        if len(infos) == 1 and infos[0].get('xref'):
            info = infos[0]
            bbox = fitz.Rect(info['bbox'])
            t = info.get('transform') or (1, 0, 0, 1, 0, 0)
            straight = abs(t[1]) < 1e-3 and abs(t[2]) < 1e-3 and t[0] > 0 and t[3] > 0
            if straight and bbox.get_area() >= 0.9 * page.rect.get_area():
                pix = fitz.Pixmap(page.parent, info['xref'])
                dpi = pix.width / (bbox.width / 72)
                if dpi < 250:
                    if pix.alpha or pix.n not in (1, 3):
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    return pix.tobytes('png'), max(2, min(4, round(RENDER_DPI / max(dpi, 1))))
    except Exception:
        pass
    return page.get_pixmap(dpi=RENDER_DPI, alpha=False).tobytes('png'), 1


# ------------------------------------------------------------ ترتيب الأسطر

@dataclass
class Line:
    text: str
    conf: float
    box: tuple


def _order_lines(items):
    """أعلى←أسفل، وداخل السطر يمين←يسار. القطع المتداخلة رأسياً أكثر من النصف = سطر واحد."""
    segs = sorted((Line(str(i['text']).strip(), float(i.get('conf', 0)), tuple(i['box'])) for i in items
                   if str(i.get('text', '')).strip()), key=lambda s: (s.box[1] + s.box[3]) / 2)
    rows = []
    for s in segs:
        h = s.box[3] - s.box[1]
        for row in rows:
            r0, r1 = min(x.box[1] for x in row), max(x.box[3] for x in row)
            if min(r1, s.box[3]) - max(r0, s.box[1]) > 0.5 * min(h, r1 - r0):
                row.append(s)
                break
        else:
            rows.append([s])
    rows.sort(key=lambda r: min(x.box[1] for x in r))
    out = []
    for row in rows:
        row.sort(key=lambda x: -x.box[2])
        out.append(Line(' '.join(x.text for x in row), min(x.conf for x in row),
                        (min(x.box[0] for x in row), min(x.box[1] for x in row),
                         max(x.box[2] for x in row), max(x.box[3] for x in row))))
    return out


def _drop_margin_marks(lines, size):
    """سطر من حرف أو حرفين على حافة الصفحة (رقم صفحة، علامة تدبيس أو ختم) ليس من المتن."""
    if not size:
        return lines
    w, h = size
    out = []
    for ln in lines:
        visible = re.sub(r'[\s\-–—_.·•|()\[\]{}]', '', ln.text)
        x0, y0, x1, y1 = ln.box
        edge = x1 < w * MARGIN or x0 > w * (1 - MARGIN) or y1 < h * MARGIN or y0 > h * (1 - MARGIN)
        if not (len(visible) <= 2 and edge):
            out.append(ln)
    return out


# ------------------------------------------------------------ الأرقام والجودة

_INDIC_MAP = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬', '01234567890123456789.,')
_BIDI = re.compile('[‎‏‪-‮⁦-⁩]')


def to_latin_digits(s):
    return _BIDI.sub('', (s or '').translate(_INDIC_MAP))


def digits_kind(raw):
    """"indic" أو "latin" أو "" حسب الأغلب في نص الصفحة الخام (قبل التحويل)."""
    ind = len(re.findall('[٠-٩۰-۹]', raw or ''))
    lat = len(re.findall('[0-9]', raw or ''))
    if not ind and not lat:
        return ''
    return 'indic' if ind >= lat else 'latin'


_AR = 'ء-يً-ْـ'


def noise_ratio(text):
    """نسبة الكلمات التي ليست كلمة: كتابتان في كلمة واحدة، رموز فقط (= ~ *)، شظايا لاتينية من حرف أو حرفين.
    الكلمة الإنجليزية الكاملة (ترويسة "State Of Kuwait") والحرف العربي المفرد (ش.م.ك) ليسا ضجيجاً."""
    toks = (text or '').split()
    if not toks:
        return 1.0
    bad = 0
    for t in toks:
        core = t.strip('.,،:؛()[]/-–«»"\'')
        if not core:
            continue
        ar, lat = re.search(f'[{_AR}]', core), re.search('[A-Za-z]', core)
        if ar and lat:
            bad += 1
        elif not ar and not lat and not re.search(r'[\d٠-٩]', core):
            bad += 1
        elif lat and not ar and len(re.sub('[^A-Za-z]', '', core)) <= 2 and core.lower() not in ('of', 'no'):
            bad += 1
    return bad / len(toks)


def has_table(png):
    """جدول حقيقي: 4 خطوط أفقية طويلة على الأقل + خطّا أعمدة داخليان (بعيدان عن الحواف). خطوط الحواف وحدها
    إطار صفحة لا جدول (13 صفحة نصية من 99 كانت تُحسب جداول بدون هذا الشرط)."""
    try:
        import io
        import numpy as np
        from PIL import Image, ImageFilter
        g = Image.open(io.BytesIO(png)).convert('L')
        g.thumbnail((1000, 1000))
        a = np.array(g.filter(ImageFilter.MinFilter(3))) < 170

        def runs(mask, k):
            c = np.cumsum(np.pad(mask.astype(np.int32), ((0, 0), (1, 0))), axis=1)
            return ((c[:, k:] - c[:, :-k]) >= k * 0.92).any(axis=1)

        hr = runs(a, int(a.shape[1] * 0.4))
        h_lines = int(hr[0]) + int(np.count_nonzero(hr[1:] & ~hr[:-1]))
        cols = runs(a.T, int(a.shape[0] * 0.1))
        w = a.shape[1]
        starts = [x for x in np.flatnonzero(cols) if x == 0 or not cols[x - 1]]
        inner = [x for x in starts if 0.14 * w <= x <= 0.86 * w]
        return h_lines >= 4 and len(inner) >= 2
    except Exception:
        return False


@dataclass
class PageText:
    number: int              # رقم الصفحة (من 1)
    text: str                # النص بأرقام إنجليزية
    raw: str                 # النص كما خرج (أرقام هندية إن كانت)
    mean_conf: float
    noise: float
    digits: str              # indic | latin | ""
    table: bool
    skew: float = 0.0

    @property
    def weak(self):
        return not self.text.strip() or self.noise >= WEAK_NOISE or self.mean_conf < WEAK_MEAN_CONF


@dataclass
class LocalResult:
    pages: list = field(default_factory=list)
    seconds: float = 0.0
    stopped: bool = False     # توقف مبكراً بشرط stop (البقية لم تُقرأ)

    @property
    def text(self):
        return '\n\n'.join(f'--- صفحة {p.number} ---\n{p.text}' for p in self.pages)

    @property
    def weak(self):
        return [p.number for p in self.pages if p.weak]

    @property
    def indic(self):
        return any(p.digits == 'indic' for p in self.pages)

    @property
    def tables(self):
        return [p.number for p in self.pages if p.table]


def read_page(page, number):
    eng = _get_engine()
    png, scale = _page_png(page)
    try:   # صفحة ممسوحة مقلوبة/جانبية ⇒ تُقوَّم قبل القراءة
        import page_orient
        png, _rot = page_orient.fix_png(png)
    except Exception:
        pass
    with _lock:   # جلسات onnxruntime آمنة، لكن المحرّك يحفظ حالة الصفحة (last_size)
        items = eng.ocr(png, scale)
        size, skew = getattr(eng, 'last_size', None), getattr(eng, 'last_skew', 0.0)
    lines = _drop_margin_marks(_order_lines(items), size)
    raw = '\n'.join(re.sub(r'[ \t]{2,}', ' ', ln.text).strip() for ln in lines)
    text = to_latin_digits(raw)
    confs = [ln.conf for ln in lines]
    return PageText(number, text, raw, sum(confs) / len(confs) if confs else 0.0, noise_ratio(text),
                    digits_kind(raw), has_table(png), skew)


def read_pages(pdf_path, idx=None, stop=None):
    """idx: أرقام صفحات من 0 (None = كل الصفحات).
    stop(page) → True: يتوقف بعد هذه الصفحة (لا فائدة من البقية). يُعرف ذلك من res.stopped."""
    import fitz
    t0 = time.monotonic()
    res = LocalResult()
    doc = fitz.open(pdf_path)
    try:
        for i in (idx if idx is not None else range(doc.page_count)):
            res.pages.append(read_page(doc[i], i + 1))
            if stop is not None and stop(res.pages[-1]):
                res.stopped = True
                break
    finally:
        doc.close()
    res.seconds = time.monotonic() - t0
    return res
