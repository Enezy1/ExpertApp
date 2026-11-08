# ===== doc_router.py — تصنيف المستند عند إضافته وتوجيهه إلى محرّك التحويل (2026-10-17) =====
# 1) classify_file: OCR الصفحة الأولى فقط (المحرّك المحلي) ثم تصنيف بالقواعد من [doc_types] في gemini_network.ini
#    (كلمات مفتاحية مفصولة بـ | قابلة للتعديل). النتيجة: النوع + الثقة + السبب. دون الحد الأدنى للثقة = «غير معروف».
# 2) engine_for: النوع → محرّك من [doc_routing] (local | external_ocr | gemini). «غير معروف» لا محرّك له:
#    يختاره الخبير ولا يُحوَّل قبل ذلك.
# 3) حدود Gemini (صفحات/حجم) في [gemini_limits] مع تاريخ التحقق من التوثيق الرسمي؛ plan_chunks يقسّم PDF
#    متجاوزاً للحدود (pypdf) ويحفظ ترقيم الصفحات الأصلي عند الدمج.
# المحرّكات هنا تأخذ (path, doc) وترجع (markdown، صفحات، تحذير). المحرّك المحلي يُمرَّر من case_documents (تجنّباً للدوران).
import configparser
import json
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import date

import gemini_config as gc
import telecom_config

T_PORTFOLIO, T_DEFENSE, T_MINUTES, T_PLAINT, T_JUDGMENT, T_UNKNOWN = (
    'حافظة مستندات', 'مذكرة دفاع', 'محضر أعمال', 'صحيفة دعوى', 'حكم', 'غير معروف')
TYPES = (T_PORTFOLIO, T_DEFENSE, T_MINUTES, T_PLAINT, T_JUDGMENT, T_UNKNOWN)
KNOWN_TYPES = TYPES[:-1]
ENGINE_LOCAL, ENGINE_EXTERNAL, ENGINE_GEMINI = 'local', 'external_ocr', 'gemini'
ENGINE_VISION = 'cloud_vision'
ENGINES = (ENGINE_LOCAL, ENGINE_EXTERNAL, ENGINE_GEMINI, ENGINE_VISION)
# ملفات .md/.txt نص جاهز: لا OCR ولا ذكاء اصطناعي؛ تُنسخ كما هي. محرّكها 'text' خارج ENGINES (لا يختاره الخبير).
ENGINE_TEXT = 'text'
TEXT_EXTS = ('.md', '.txt')
ENGINE_LABELS = {ENGINE_LOCAL: 'OCR المحلي', ENGINE_EXTERNAL: 'OCR خارجي', ENGINE_GEMINI: 'Gemini',
                 ENGINE_VISION: 'Google Cloud Vision', 'text_layer': 'الطبقة النصية',
                 ENGINE_TEXT: 'نص جاهز'}
TEXT_HEAD_CHARS = 1500       # أول سطور النص المقروءة للتصنيف بدل OCR الصفحة الأولى

DEFAULT_KEYWORDS = {
    T_PORTFOLIO: 'حافظة مستندات | حافظة بمستندات | حافظة | مستندات مقدمة | بيان المستندات',
    T_DEFENSE: 'مذكرة بدفاع | مذكرة دفاع | مذكرة جوابية | مذكرة بالرد | مذكرة شارحة | دفاع المدعى عليه',
    T_MINUTES: 'محضر أعمال | محضر اعمال الخبير | محضر جلسة | محضر الخبرة | محضر مباشرة',
    T_PLAINT: 'صحيفة دعوى | صحيفة الدعوى | صحيفة افتتاح | صحيفة افتتاح دعوى',
    T_JUDGMENT: 'حكمت المحكمة | باسم حضرة صاحب السمو | منطوق الحكم | حكم تمهيدي | حكم صادر',
}
# "best" = أفضل محرّك مضبوط وقت التحويل (Gemini ثم الخارجي ثم المحلي): صحيفة الدعوى وحكم الإحالة قصيران ومفتاحان لكل
# التقرير فلا يُقرآن بالـOCR المحلي الضعيف. يبقى للخبير تغيير المحرّك يدوياً.
ENGINE_BEST = 'best'
DEFAULT_ROUTING = {T_DEFENSE: ENGINE_EXTERNAL, T_PORTFOLIO: ENGINE_GEMINI, T_MINUTES: ENGINE_LOCAL,
                   T_PLAINT: ENGINE_BEST, T_JUDGMENT: ENGINE_BEST}
KEY_TYPES = (T_PLAINT, T_JUDGMENT)       # مستندات مفتاحية: جودة قراءتها تُفحص
ROUTING_VERSION = 2                      # 2 = صحيفة الدعوى والحكم «best» بدل المحلي (يُرحَّل الملف القديم مرة واحدة)
# حدود Gemini لملفات PDF — تحقّقت منها من التوثيق الرسمي بتاريخ VERIFIED (ai.google.dev/gemini-api/docs/document-processing
# و /files): «PDF files up to 50MB or 1000 pages». chunk_pages إعداد خاص بالتطبيق (0 = معطّل) لا حدّ من Gemini.
DEFAULT_LIMITS = {'max_pages': '1000', 'max_mb': '50', 'chunk_pages': '0', 'batch_pages': '25', 'retries': '3',
                  'retry_wait': '30', 'verified': '2026-10-17',
                  'source': 'https://ai.google.dev/gemini-api/docs/document-processing'}
DEFAULT_MIN_CONFIDENCE = 0.5
SNIPPET_CHARS = 600

_SEC_TYPES, _SEC_ROUTE, _SEC_LIMITS, _SEC_CLASSIFY = 'doc_types', 'doc_routing', 'gemini_limits', 'doc_classify'


# ---------- الإعدادات ----------

def _ini_path():
    return os.path.join(gc._app_dir(), gc._NET_INI_NAME)


def _read():
    cp = configparser.RawConfigParser()
    cp.optionxform = str                 # لا تُصغَّر المفاتيح (أسماء عربية/إنجليزية كما كُتبت)
    try:
        cp.read(_ini_path(), encoding='utf-8')
    except Exception:
        pass
    return cp


def ensure_defaults():
    """يضيف الأقسام الناقصة فقط إلى gemini_network.ini (لا يمسّ ما كتبه المستخدم). يرجع هل كتب شيئاً."""
    path = _ini_path()
    cp = _read()
    blocks = []
    if not cp.has_section(_SEC_TYPES):
        blocks.append(f'[{_SEC_TYPES}]\n' + ''.join(f'{k} = {v}\n' for k, v in DEFAULT_KEYWORDS.items()))
    if not cp.has_section(_SEC_CLASSIFY):
        blocks.append(f'[{_SEC_CLASSIFY}]\nmin_confidence = {DEFAULT_MIN_CONFIDENCE}\n')
    if not cp.has_section(_SEC_ROUTE):
        blocks.append(f'[{_SEC_ROUTE}]\n' + ''.join(f'{k} = {v}\n' for k, v in DEFAULT_ROUTING.items())
                      + f'routing_version = {ROUTING_VERSION}\n')
    if not cp.has_section(_SEC_LIMITS):
        blocks.append(f'[{_SEC_LIMITS}]\n' + ''.join(f'{k} = {v}\n' for k, v in DEFAULT_LIMITS.items())
                      + f'batch_version = {BATCH_VERSION}\n')
    migrated = _migrate_routing(path, cp) if cp.has_section(_SEC_ROUTE) else False
    migrated = _migrate_batch(path, cp) or migrated
    if cp.has_section(_SEC_LIMITS):
        missing = [k for k in ('batch_pages', 'retries', 'retry_wait') if not cp.has_option(_SEC_LIMITS, k)]
        if missing:
            try:
                with open(path, encoding='utf-8') as f:
                    txt = f.read()
                add = ''.join(f'{k} = {DEFAULT_LIMITS[k]}\n' for k in missing)
                txt = re.sub(rf'(\[{_SEC_LIMITS}\]\s*\n)', lambda m: m.group(1) + add, txt, count=1)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(txt)
                migrated = True
            except OSError:
                pass
    if not blocks:
        return migrated
    try:
        old = ''
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                old = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(old.rstrip('\n') + ('\n\n' if old.strip() else '') + '\n'.join(blocks))
        return True
    except OSError:
        return False


BATCH_VERSION = 2                        # 2 = دفعة OCR الافتراضية 25 صفحة بدل 20 (طلبات أقل لنفس الملف)
BATCH_MIN, BATCH_MAX = 25, 30


def _migrate_batch(path, cp):
    """batch_pages = 20 (الافتراضي القديم) ← 25 مرة واحدة (علامة batch_version). قيمة اختارها الخبير غير 20 لا تُمسّ."""
    if not cp.has_section(_SEC_LIMITS):
        return False
    try:
        if int(cp.get(_SEC_LIMITS, 'batch_version', fallback='1')) >= BATCH_VERSION:
            return False
    except ValueError:
        pass
    try:
        with open(path, encoding='utf-8') as f:
            txt = f.read()
        if cp.get(_SEC_LIMITS, 'batch_pages', fallback='').strip() == '20':
            txt = re.sub(r'(?m)^(batch_pages\s*=\s*)20\s*$', r'\g<1>' + DEFAULT_LIMITS['batch_pages'], txt, count=1)
        txt = re.sub(rf'(\[{_SEC_LIMITS}\]\s*\n)', lambda m: m.group(1) + f'batch_version = {BATCH_VERSION}\n', txt, count=1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(txt)
        return True
    except OSError:
        return False


def _migrate_routing(path, cp):
    """ملف قديم كتب افتراضيَّ «local» لصحيفة الدعوى/الحكم ← «best» مرة واحدة (علامة routing_version).
    ما اختاره الخبير غير «local» لا يُمسّ. يرجع هل كتب شيئاً."""
    try:
        if int(cp.get(_SEC_ROUTE, 'routing_version', fallback='1')) >= ROUTING_VERSION:
            return False
    except ValueError:
        pass
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.read().split('\n')
        out, inside, done = [], False, False
        for ln in lines:
            st = ln.strip()
            if st.startswith('['):
                if inside and not done:
                    out.append(f'routing_version = {ROUTING_VERSION}')
                    done = True
                inside = st == f'[{_SEC_ROUTE}]'
            elif inside and '=' in st:
                k, v = (x.strip() for x in st.split('=', 1))
                if k in KEY_TYPES and v.lower() == ENGINE_LOCAL:
                    ln = f'{k} = {ENGINE_BEST}'
                elif k == 'routing_version':
                    continue
            out.append(ln)
        if inside and not done:
            while out and not out[-1].strip():
                out.pop()
            out += [f'routing_version = {ROUTING_VERSION}', '']
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(out))
        return True
    except OSError:
        return False


def keywords():
    """{نوع: [كلمات]} — من الملف إن وُجد القسم وإلا الافتراضي."""
    cp = _read()
    out = {}
    for t in KNOWN_TYPES:
        raw = cp.get(_SEC_TYPES, t, fallback=None) if cp.has_section(_SEC_TYPES) else None
        raw = DEFAULT_KEYWORDS[t] if raw is None else raw
        out[t] = [k.strip() for k in raw.split('|') if k.strip()]
    return out


def min_confidence():
    try:
        return float(_read().get(_SEC_CLASSIFY, 'min_confidence', fallback=DEFAULT_MIN_CONFIDENCE))
    except ValueError:
        return DEFAULT_MIN_CONFIDENCE


def routing():
    cp = _read()
    out = dict(DEFAULT_ROUTING)
    if cp.has_section(_SEC_ROUTE):
        for t in KNOWN_TYPES:
            v = cp.get(_SEC_ROUTE, t, fallback='').strip().lower()
            if v in ENGINES or v == ENGINE_BEST:
                out[t] = v
    return out


def best_engine_source():
    """مصدر مفتاح أقوى محرّك الآن: 'own' (مفتاحك) | 'shared' (مفتاح القسم) | '' (محلي). لا يتصل بالشبكة.
    المفتاح الشخصي للمزوّد يُستعمل وحده ويحجب مفتاح القسم لنفس المزوّد (ai_providers.build_chain)."""
    try:
        import ai_providers
        eng = best_engine()
        which = {ENGINE_GEMINI: 'gemini', ENGINE_VISION: 'vision', ENGINE_EXTERNAL: 'ocrspace'}.get(eng)
        src = ai_providers.key_source(which) if which else 'none'
        return '' if src == 'none' else src
    except Exception:
        return ''


def best_engine():
    """أقوى محرّك مضبوط الآن: Gemini (مفتاحك الشخصي، وإلا مفتاح القسم) ثم Vision (شخصي فقط) ثم OCR.space
    (شخصي ثم القسم) ثم المحلي. لا يتصل بالشبكة."""
    try:
        _gemini_provider()
        return ENGINE_GEMINI
    except Exception:
        pass
    try:
        import ocr_vision
        if ocr_vision.is_available():
            return ENGINE_VISION
    except Exception:
        pass
    try:
        import ocr_space
        if gc.feature_on('ocr_external') and ocr_space.is_available():
            return ENGINE_EXTERNAL
    except Exception:
        pass
    return ENGINE_LOCAL


def engine_for(doc_type):
    """محرّك النوع («best» يُحلّ إلى المحرّك الفعلي)، أو None لغير المعروف."""
    if doc_type not in KNOWN_TYPES:
        return None
    e = routing().get(doc_type)
    return best_engine() if e == ENGINE_BEST else e


def gemini_limits():
    """{'max_pages','max_bytes','chunk_pages','verified','source'} من [gemini_limits]."""
    cp = _read()
    g = lambda k: cp.get(_SEC_LIMITS, k, fallback=DEFAULT_LIMITS[k]).strip() or DEFAULT_LIMITS[k]
    def num(k, cast):
        try:
            return cast(g(k))
        except ValueError:
            return cast(DEFAULT_LIMITS[k])
    return {'max_pages': num('max_pages', int), 'max_bytes': int(num('max_mb', float) * 1024 * 1024),
            'chunk_pages': num('chunk_pages', int), 'batch_pages': num('batch_pages', int),
            'retries': num('retries', int), 'retry_wait': num('retry_wait', float),
            'verified': g('verified'), 'source': g('source')}


def limits_text(lim=None):
    lim = lim or gemini_limits()
    return (f"حدود Gemini للملف الواحد: {lim['max_pages']} صفحة و{lim['max_bytes'] // (1024 * 1024)}MB "
            f"(تحقّق منها بتاريخ {lim['verified']} — {lim['source']})")


# ---------- التصنيف ----------

def _score(text, kws):
    norm = telecom_config.normalize(text)
    scores, hits = {}, {}
    for t, words in kws.items():
        found = [w for w in words if telecom_config.normalize(w) and telecom_config.normalize(w) in norm]
        if found:
            scores[t], hits[t] = len(found), found
    return scores, hits


# افتتاحية محضر الخبرة الثابتة (محاضر Word التي يكتبها البرنامج والمحاضر الرسمية): حاسمة قبل عدّ الكلمات المفتاحية —
# المحضر يذكر «قدم الحاضر حافظة مستندات» فكان يُعدّ «حافظة مستندات» (2026-10-25، A2263970: «محضر الخبرة رقم 1» = حافظة 67%).
MINUTES_OPEN = ('فتح المحضر بتاريخه',)
MINUTES_CLOSE = ('أغلق المحضر', 'أقفل المحضر')
MINUTES_HEAD_CHARS = 400


def is_minutes_text(text):
    """نص يبدأ بافتتاحية محضر الخبرة (أول MINUTES_HEAD_CHARS حرفاً) أو ينتهي بخاتمته."""
    t = str(text or '')
    head = telecom_config.normalize(t[:MINUTES_HEAD_CHARS])
    tail = telecom_config.normalize(t[-MINUTES_HEAD_CHARS:])
    return (any(telecom_config.normalize(m) in head for m in MINUTES_OPEN)
            or any(telecom_config.normalize(m) in tail for m in MINUTES_CLOSE))


def classify_text(text, kws=None, threshold=None):
    """يصنّف نص الصفحة الأولى. يرجع {'type','confidence','reason'}.
    الثقة = (حصة النوع الفائز من كل التطابقات) × min(1، تطابقاته/2): تطابق وحيد يعطي 0.5 بالكثير.
    افتتاحية المحضر الثابتة (is_minutes_text) تحسم «محضر أعمال» بثقة 1 قبل العدّ."""
    if is_minutes_text(text):
        return {'type': T_MINUTES, 'confidence': 1.0, 'reason': 'افتتاحية محضر الخبرة («فتح المحضر بتاريخه»)'}
    kws = kws or keywords()
    threshold = min_confidence() if threshold is None else threshold
    scores, hits = _score(text or '', kws)
    if not scores:
        return {'type': T_UNKNOWN, 'confidence': 0.0, 'reason': 'لم تُطابق أي كلمة مفتاحية في الصفحة الأولى'}
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], KNOWN_TYPES.index(kv[0])))
    best, n = ranked[0]
    total = sum(scores.values())
    conf = round(n / total * min(1.0, n / 2), 2)
    tied = len(ranked) > 1 and ranked[1][1] == n
    why = f"تطابق {n}: «{'» «'.join(hits[best])}»"
    if len(ranked) > 1:
        why += ' | الأقرب بعده: ' + '، '.join(f"{t} ({s})" for t, s in ranked[1:3])
    if tied:
        return {'type': T_UNKNOWN, 'confidence': conf, 'reason': 'تعادل بين نوعين — ' + why}
    if conf < threshold:
        return {'type': T_UNKNOWN, 'confidence': conf,
                'reason': f'الثقة {conf} دون الحد الأدنى {threshold} — ' + why}
    return {'type': best, 'confidence': conf, 'reason': why}


_ARABIC = re.compile(r'[؀-ۿ]')


def read_text_file(path):
    """نص ملف .md/.txt: UTF-8 (مع BOM أو بدونه) وإلا windows-1256 العربي."""
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'cp1256'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def classify_text_file(path):
    """تصنيف ملف نصي بقراءة أول سطوره نفسها (بلا OCR): {'type','confidence','reason','snippet'}."""
    head = read_text_file(path).strip()[:TEXT_HEAD_CHARS]
    res = classify_text(head)
    res['snippet'] = head[:SNIPPET_CHARS]
    return res


def first_page_text(path, local_ocr_mod=None):
    """نص الصفحة الأولى فقط: Word ← أول فقرات؛ PDF/صورة ← نص مضمّن غير عربي، وإلا OCR المحلي؛ .md/.txt ← أول النص."""
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXTS:
        return read_text_file(path).strip()[:TEXT_HEAD_CHARS]
    if ext == '.docx':
        import case_documents
        return case_documents._docx_text(path)[:3000]
    import fitz
    doc = fitz.open(path)
    try:
        if doc.page_count == 0:
            return ''
        page = doc[0]
        emb = (page.get_text() or '').strip()
        if len(emb) >= 40 and not _ARABIC.search(emb):
            return emb
        lo = local_ocr_mod
        if lo is None:
            import local_ocr as lo
        if not lo.available():
            return emb
        return lo.read_page(page, 1).text
    finally:
        doc.close()


def classify_file(path):
    """التصنيف الكامل لملف: {'type','confidence','reason','snippet'}. أي خطأ ← غير معروف مع السبب."""
    try:
        text = first_page_text(path)
    except Exception as e:
        return {'type': T_UNKNOWN, 'confidence': 0.0, 'snippet': '',
                'reason': f'تعذّرت قراءة الصفحة الأولى ({e.__class__.__name__}: {e})'}
    res = classify_text(text)
    res['snippet'] = (text or '').strip()[:SNIPPET_CHARS]
    return res


# ---------- عدّ الصفحات والتقسيم ----------

def page_count(path):
    from pypdf import PdfReader
    return len(PdfReader(path).pages)


def _as_pdf(path, tmpdir):
    """PDF كما هو، أو صورة تُحوَّل إلى PDF من صفحة واحدة."""
    if os.path.splitext(path)[1].lower() == '.pdf':
        return path
    import fitz
    src = fitz.open(path)
    try:
        out = os.path.join(tmpdir, 'img.pdf')
        pdf = fitz.open('pdf', src.convert_to_pdf())
        pdf.save(out)
        pdf.close()
        return out
    finally:
        src.close()


def _write_range(reader, a, b, out):
    from pypdf import PdfWriter
    w = PdfWriter()
    for i in range(a, b):
        w.add_page(reader.pages[i])
    with open(out, 'wb') as f:
        w.write(f)
    return os.path.getsize(out)


def plan_chunks(pdf_path, tmpdir, max_pages, max_bytes, chunk_pages=0):
    """يرجع [(بداية 0-based، نهاية حصرية، مسار PDF)] — ملف واحد كما هو إن لم يتجاوز الحدود.
    التقسيم متوازن: يُنصَّف المقطع حتى يوافق الحدّين. صفحة واحدة تتجاوز الحجم ← ValueError."""
    from pypdf import PdfReader
    n = page_count(pdf_path)
    size = os.path.getsize(pdf_path)
    cap = max_pages if not chunk_pages else min(max_pages, chunk_pages)
    if n <= cap and size <= max_bytes:
        return [(0, n, pdf_path)]
    reader = PdfReader(pdf_path)
    out, k = [], [0]

    def split(a, b):
        path = os.path.join(tmpdir, f'part{k[0]}.pdf')
        k[0] += 1
        sz = _write_range(reader, a, b, path)
        if (b - a) <= cap and sz <= max_bytes:
            out.append((a, b, path))
        elif b - a == 1:
            raise ValueError(f'الصفحة {a + 1} وحدها ({sz // 1024}KB) تتجاوز حد الحجم')
        else:
            os.remove(path)
            mid = (a + b) // 2
            split(a, mid)
            split(mid, b)
    if chunk_pages:                     # دفعات متتالية بالحجم المضبوط: أول 20 صفحة ثم التالية (45 صفحة = 3 دفعات)
        for a in range(0, n, cap):
            split(a, min(a + cap, n))
    else:
        split(0, n)
    return out


def merge_chunks(results):
    """results: [(بداية 0-based، [(نص الصفحة)…])] ← نص واحد بعلامات <!-- صفحة N --> بالترقيم الأصلي."""
    parts = []
    for start, texts in results:
        for i, t in enumerate(texts):
            parts.append(f'<!-- صفحة {start + i + 1} -->\n{t.strip()}')
    return '\n\n'.join(parts)


# ---------- المحرّكات ----------
PAGE_SEP = '=====PAGE====='
_PAGE_NO = re.compile(r'^[ \t]*=====\s*PAGE\s*(\d+)\s*=====[ \t]*$', re.M)
# (2026-10-25) كان «حرفياً بالعربية» يدفع النموذج لترجمة فواتير الشركات الإنجليزية، ولا قواعد للجداول، والفاصل بلا رقم:
# صفحة واحدة ناقصة في الرد كانت تدمج الدفعة كلها (25 صفحة) فتضيع أرقام الصفحات والمستندات. الآن كل صفحة برقمها.
GEMINI_PROMPT = (
    "حوّل هذا المستند القضائي إلى نص Markdown دقيق. القواعد:\n"
    "1) انقل النص حرفياً بلغته الأصلية كما يظهر (العربي عربي والإنجليزي إنجليزي) دون ترجمة أو تلخيص أو إضافة أو تصحيح.\n"
    "2) الأرقام والتواريخ والمبالغ كما تظهر بالضبط: الفاصلة العشرية والإشارة السالبة والأرقام الهندية كما هي، "
    "ولا تحسب ولا تجمع شيئاً.\n"
    "3) كل جدول يُكتب جدول Markdown بعدد أعمدته الفعلي وبصف عناوينه، وكل صف في سطر: الخلية الفارغة تبقى فارغة (| |) "
    "ولا تنقل قيمة إلى عمود مجاور، والخلية ذات السطرين تبقى في خليتها مفصولة بـ<br>، ولا تدمج صفين ولا تحذف صف الإجمالي.\n"
    "4) حقول النماذج: اسم الحقل وقيمته في سطر واحد «الحقل: القيمة» (مثل Contract Number: 2758545644).\n"
    "5) ما لا يُقرأ اكتبه [غير مقروء] ولا تخمّنه؛ التوقيع [توقيع]، والختم [ختم].\n"
    "6) عدد صفحات الملف {n}. ابدأ كل صفحة، بما فيها الأولى، بسطر وحده نصه بالضبط =====PAGE k===== حيث k رقم الصفحة "
    "من 1 إلى {n} بالترتيب. الصفحة الفارغة: علامتها ثم [صفحة فارغة]. لا تتخطَّ صفحة ولا تدمج صفحتين.\n"
    "7) لا تكتب أي مقدمة أو شرح.")

# مصنع المزوّد (يُستبدل بالاختبارات بمزوّد وهمي): () -> كائن فيه generate(prompt, prep, route, timeout)
GEMINI_PROVIDER_FACTORY = None


STATUS_HOOK = None          # fn(نص) تضبطه الواجهة لتعرض خطوات المحرّكات (مثل التقسيم) في لوحة «ما يفعله البرنامج»


PAGE_HOOK = None            # fn(صفحات_منجزة، الإجمالي) يضبطها case_documents.process_pending لنسبة كل ملف


PROGRESS_LISTENERS = []    # حارس المهلة (case_folder.convert_guarded): أي تقدّم صفحات يجدّد وقته
_TLS = threading.local()


def set_batch_override(n):
    """إعادة التحويل بعد حلقة: دفعات صفحات أصغر لهذا الخيط فقط (0 = الإعداد العادي)."""
    _TLS.batch = int(n or 0)


def set_triage(parties, base=None):
    """الفرز مدمج في طلب التحويل (case_triage): نص أطراف القضية لهذا الخيط، أو None لإيقافه.
    base: مجلد القضية ← كل دفعة (تحويل + فرز) تُسجَّل في سجل طلبات القضية (ai_call_log)."""
    _TLS.triage = parties
    _TLS.triage_base = base
    _TLS.triage_blocks = []


def take_triage():
    """كتل الفرز [(a، b، obj)] من آخر تحويل جيميناي في هذا الخيط (وتُمسح)."""
    blocks = getattr(_TLS, 'triage_blocks', None) or []
    _TLS.triage_blocks = []
    return blocks


def batch_override():
    return getattr(_TLS, 'batch', 0)


class Stalled(Exception):
    """مهلة طويلة بلا تقدّم في التحويل (حارس case_folder.convert_guarded)."""


def start_watch(stall):
    _TLS.watch = [time.monotonic(), float(stall), 0.0]          # آخر تقدّم، الحد، أطول فجوة


def stop_watch():
    w = getattr(_TLS, 'watch', None)
    _TLS.watch = None
    if not w:
        return 0.0
    return max(w[2], time.monotonic() - w[0])


def _tick():
    w = getattr(_TLS, 'watch', None)
    if w:
        now = time.monotonic()
        w[2] = max(w[2], now - w[0])
        w[0] = now


def check_stall():
    """تستدعيها المحرّكات بين الدفعات: فجوة بلا تقدّم أطول من الحد ← Stalled (يُترك الطلب ويُعاد بدفعات أصغر)."""
    w = getattr(_TLS, 'watch', None)
    if w and time.monotonic() - w[0] > w[1]:
        raise Stalled(f'مهلة طويلة بلا تقدّم ({int(time.monotonic() - w[0])} ثانية)')


def set_progress_hook(fn):
    """مستمع تقدّم الصفحات لهذا الخيط فقط (إعادة قراءة ملف واحد ← شريط تقدّم في صفّه)."""
    _TLS.progress_hook = fn


def page_progress(done, total):
    _tick()
    tl = getattr(_TLS, 'progress_hook', None)
    if tl:
        try:
            tl(done, total)
        except Exception:
            pass
    for fn in list(PROGRESS_LISTENERS):
        try:
            fn(done, total)
        except Exception:
            pass
    if PAGE_HOOK:
        try:
            PAGE_HOOK(done, total)
        except Exception:
            pass


def _hook(text):
    if STATUS_HOOK:
        STATUS_HOOK(text)


class EngineUnavailable(Exception):
    """المحرّك غير مضبوط/غير متاح ← يُستعمل المحلي مع تنبيه."""


def _gemini_provider():
    if GEMINI_PROVIDER_FACTORY:
        return GEMINI_PROVIDER_FACTORY()
    import ai_providers
    for p in ai_providers.build_chain():
        if isinstance(p, ai_providers.GeminiProvider):
            return p
    raise EngineUnavailable('لا يوجد مفتاح Gemini مضبوط')


def _call_provider(provider, prompt, chunk_path, pages):
    prep = {'kind': 'pdf', 'path': chunk_path}
    timeout = gc.compute_timeout(pages)
    size = os.path.getsize(chunk_path)
    if GEMINI_PROVIDER_FACTORY:                          # مزوّد وهمي: بلا مسارات شبكة
        return provider.generate(prompt, prep, 'direct', timeout).text
    return gc._run_with_routes(lambda route: provider.generate(prompt, prep, route, timeout), size, timeout).text


SLEEP = None             # الاختبارات تستبدلها؛ الافتراضي time.sleep


def _rate_limited(e):
    m = str(e).lower()
    return '429' in m or 'resource_exhausted' in m or 'rate limit' in m or 'quota' in m


def _retry_after(e, default):
    m = re.search(r'retry(?:\s+in|delay)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*s', str(e), re.I)
    return float(m.group(1)) + 1 if m else default


def _call_provider_retry(provider, prompt, chunk_path, pages, lim):
    """دفعة صفحات واحدة — بلا إعادة هنا (2026-10-25): سياسة واحدة في gemini_config (محاولتان في المجموع، و429/503 ينقل
    الطلب فوراً للنموذج التالي في سلسلة المهمة). الطلب المرفوض يُحتسب من حصة اليوم فلا تُكرَّر الدفعة على النموذج نفسه.
    (retries/retry_wait في [gemini_limits] لم تعد تُستعمل.)"""
    return _call_provider(provider, prompt, chunk_path, pages)


def split_pages(text, expected):
    """يفصل ردّ Gemini على علامة الصفحة. يرجع (قائمة نصوص، تحذير أو '').
    العلامات المرقّمة (=====PAGE k=====): كل نص في صفحته برقمها، والصفحة الناقصة تبقى فارغة بتحذير — لا دمج للدفعة."""
    marks = list(_PAGE_NO.finditer(text or ''))
    if marks:
        by = {}
        for i, m in enumerate(marks):
            k = int(m.group(1))
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            if 1 <= k <= expected:
                by[k] = (by.get(k, '') + '\n\n' + text[m.end():end]).strip()
        missing = [k for k in range(1, expected + 1) if k not in by]
        if len(missing) < expected:
            pieces = [by.get(k, '') for k in range(1, expected + 1)]
            return pieces, (f"لم ترد في ردّ Gemini الصفحات ({'، '.join(map(str, missing))}) من {expected} — بقيت فارغة"
                            if missing else '')
    pieces = [p.strip() for p in (text or '').split(PAGE_SEP)]
    if len(pieces) == expected:
        return pieces, ''
    return [(text or '').replace(PAGE_SEP, '\n\n').strip()], (
        f'عدد الصفحات في ردّ Gemini ({len(pieces)}) لا يطابق الفعلي ({expected}) — النص مدموج لهذا الجزء')


def _log_triage(prompt, reply, t0, a, b, n):
    """دفعة «التحويل والفرز» في سجل طلبات القضية (الطلب بلا صور، والرد كاملاً). فشل التسجيل صامت."""
    base = getattr(_TLS, 'triage_base', None)
    if not base:
        return
    try:
        import ai_call_log
        ai_call_log._local.detail = f'الصفحات {a + 1}–{b} من {n}'
        ai_call_log._local.provider = 'Gemini'
        ai_call_log._local.model = getattr(getattr(_TLS, 'triage_provider', None), 'last_model', '') or ''
        ai_call_log._write_req(base, 'التحويل والفرز', prompt, reply, True, '', time.time() - t0, t0)
        ai_call_log._local.detail = ''
    except Exception:
        pass


def gemini_engine(local, limits=None, status=None):
    """محرّك Gemini: يعدّ الصفحات والحجم، يقسّم عند تجاوز الحدود، ويدمج بالترقيم الأصلي.
    بلا Gemini متاح ← المحلي مع تحذير."""
    say = status or _hook

    def run(path, doc):
        lim = limits or gemini_limits()
        try:
            provider = _gemini_provider()
        except EngineUnavailable as e:
            text, pages = local(path)
            return text, pages, f'Gemini غير متاح ({e}) — استُعمل OCR المحلي'
        # التحويل وحده (2026-10-23): Flash Lite ينسخ النص markdown فقط، والفرز طلب نصي مستقل لاحقاً (text_light —
        # case_triage.triage_file) فلا يُحمَّل طلب الصور بقوالب JSON ولا يُستعمل نموذج أقوى للنسخ.
        _TLS.triage_blocks = []
        if hasattr(provider, 'task'):
            provider.task = 'ocr'
        tmp = tempfile.mkdtemp(prefix='docroute_')
        try:
            pdf = _as_pdf(path, tmp)
            n, size = page_count(pdf), os.path.getsize(pdf)
            chunks = plan_chunks(pdf, tmp, lim['max_pages'], lim['max_bytes'],
                                 batch_override() or lim.get('batch_pages') or lim['chunk_pages'])
            if len(chunks) > 1:
                say(f"الملف {n} صفحة و{size // 1024}KB يتجاوز الحدود ({lim['max_pages']} صفحة / "
                    f"{lim['max_bytes'] // (1024 * 1024)}MB) — قُسّم إلى {len(chunks)} أجزاء")
            results, warns = [], []
            for idx, (a, b, cpath) in enumerate(chunks):
                check_stall()                      # مهلة بلا تقدّم ← يُترك ويُعاد بدفعات أصغر (case_folder)
                page_progress(a, n)
                prompt = GEMINI_PROMPT.format(n=b - a)
                try:
                    reply = _call_provider_retry(provider, prompt, cpath, b - a, lim)
                except gc.QuotaExhausted:
                    raise                          # حصة اليوم نفدت: ليست فشل مفتاح
                except Exception as e:
                    import ai_providers
                    if getattr(provider, 'key_type', '') == ai_providers.KEY_OWN and not GEMINI_PROVIDER_FACTORY:
                        raise ai_providers.personal_failure(provider, e) from e      # مفتاحك الشخصي: توقف واسأل
                    raise
                import loop_guard                 # حلقة في دفعة ← يتوقف فوراً (لا تُرسل بقية الدفعات ولا يُحفظ شيء)
                loop_guard.check(reply, b - a)
                texts, w = split_pages(reply, b - a)
                if w:
                    warns.append(f'الصفحات {a + 1}–{b}: {w}')
                if len(texts) != b - a:                    # فاصل بلا أرقام ولا يطابق العدد: الدفعة مدموجة
                    results.append((a, [f'<!-- صفحات {a + 1}–{b} مدموجة -->\n{texts[0]}']))
                else:
                    results.append((a, texts))
            md = merge_chunks(results)
            if not re.sub(r'<!--.*?-->|\s', '', md):
                raise RuntimeError('ردّ Gemini فارغ')
            return md, n, '؛ '.join(warns)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return run


def external_ocr_engine(local, status=None):
    """OCR خارجي = المزوّد المضبوط في ai_providers (ocrspace). غير مضبوط/فاشل ← المحلي مع تنبيه."""
    say = status or _hook

    vision = vision_engine(local, status)

    def run(path, doc):
        import ocr_space
        import ocr_vision
        if ocr_vision.is_available():                 # OCR رقم 1 = Google Cloud Vision (أدق في العربي والأرقام)
            text, pages, warn = vision(path, doc)
            if not warn:
                doc['engine_used'] = ENGINE_VISION
                return text, pages, ''
        if not (gc.feature_on('ocr_external') and ocr_space.is_available()):
            text, pages = local(path)
            return text, pages, 'OCR الخارجي غير مضبوط — استُعمل OCR المحلي'
        tmp = tempfile.mkdtemp(prefix='docroute_')
        try:
            pdf = _as_pdf(path, tmp)
            n = page_count(pdf)
            try:
                raw = gc._run_with_routes(lambda route: ocr_space.ocr_pages(pdf, list(range(n)), route),
                                          os.path.getsize(pdf), gc.compute_timeout(n))
            except Exception as e:
                text, pages = local(path)
                return text, pages, f'تعذّر OCR الخارجي ({e}) — استُعمل OCR المحلي'
            pieces = re.split(r'--- صفحة (\d+) ---\n', raw)
            md = '\n\n'.join(f'<!-- صفحة {pieces[i]} -->\n{pieces[i + 1].strip()}'
                             for i in range(1, len(pieces) - 1, 2))
            return md, n, ''
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return run


def vision_engine(local, status=None):
    """Google Cloud Vision (document text detection): غير مضبوط/فاشل ← المحلي مع تنبيه."""
    def run(path, doc):
        import ocr_vision
        if not ocr_vision.is_available():
            text, pages = local(path)
            return text, pages, 'مفتاح Google Cloud Vision غير مضبوط — استُعمل OCR المحلي'
        tmp = tempfile.mkdtemp(prefix='docroute_')
        try:
            pdf = _as_pdf(path, tmp)
            n = page_count(pdf)
            try:
                raw = gc._run_with_routes(lambda route: ocr_vision.ocr_pages(pdf, list(range(n)), route),
                                          os.path.getsize(pdf), gc.compute_timeout(n))
            except Exception as e:
                text, pages = local(path)
                return text, pages, f'تعذّر Google Cloud Vision ({e}) — استُعمل OCR المحلي'
            pieces = re.split(r'--- صفحة (\d+) ---\n', raw)
            md = '\n\n'.join(f'<!-- صفحة {pieces[i]} -->\n{pieces[i + 1].strip()}'
                             for i in range(1, len(pieces) - 1, 2))
            return md, n, ''
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return run


def local_engine(local):
    def run(path, doc):
        text, pages = local(path)
        return text, pages, ''
    return run


def build_engines(local, status=None):
    return {ENGINE_LOCAL: local_engine(local), ENGINE_EXTERNAL: external_ocr_engine(local, status),
            ENGINE_GEMINI: gemini_engine(local, status=status), ENGINE_VISION: vision_engine(local, status)}


# ---------- فحص جودة النص المقروء ----------
# بلا قاموس خارجي: (أ) حصة كلمات الربط الشائعة (في/من/على/أن…) في النثر العربي السليم تفوق ~20%؛ تهبط كثيراً مع نص
# مشوَّه. (ب) كلمات مريبة: خلط عربي/لاتيني/رقم في كلمة، رموز OCR شاذة، تكرار حرف 3+، «ال» مكررة،
# تاء مربوطة/ألف مقصورة وسط الكلمة. النص القصير جداً لا يُحكم عليه.
WEAK_MESSAGE = 'جودة قراءة الصحيفة ضعيفة، أعد قراءتها بمحرك أقوى'
MIN_QUALITY_TOKENS = 40
MAX_SUSPECT_RATIO = 0.12
MIN_FUNCTION_RATIO = 0.10
_FUNCTION_WORDS = frozenset(
    'في من على الي عن ان انه انها كان كانت هو هي هذا هذه ذلك التي الذي الذين ما لا لم لن قد ثم او كل بين عند '
    'بعد قبل حتي اذا اي غير مع منذ خلال له لها لهم به بها بهم عليه عليها عليهم منه منها فيه فيها كما حيث '
    'علي بان بما لما حول دون الا انما اذ اذن هل بل لكن لان'.split())
_NOISE = re.compile(r'[|~¬^_*=<>{}\[\]§¶•]')
_MIXED = re.compile(r'(?=.*[؀-ۿ])(?=.*[A-Za-z0-9])')
_DATEISH = re.compile(r'[؀-ۿ]*\d[\d/.,:-]*[؀-ۿ]*')
_WORD = re.compile(r'[^\s،؛:.!?؟()"«»\-–—/\\]+')
_STRIP = re.compile(r'[ً-ٰٟـ]')
_NORM = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي', 'ة': 'ه'})


def _suspect(tok):
    if _NOISE.search(tok):
        return True
    if _MIXED.search(tok) and not _DATEISH.fullmatch(tok):
        return True
    if re.search(r'(.)\1{2,}', tok) or re.search(r'(ال){2,}', tok):
        return True
    return bool(re.search(r'[ةى][؀-ۿ]{2,}$', tok) and not tok.startswith('ال'))


def _is_function(tok):
    t = _STRIP.sub('', tok).translate(_NORM)
    return t in _FUNCTION_WORDS or (len(t) > 2 and t[0] in 'وفبلك' and t[1:] in _FUNCTION_WORDS)


def text_quality(text):
    """{'ok','weak','tokens','suspect_ratio','function_ratio','reason'}. فارغ ← ضعيف؛ أقل من MIN_QUALITY_TOKENS كلمة ← سليم."""
    body = re.sub(r'<!--.*?-->', ' ', text or '')
    toks = [t for t in _WORD.findall(body) if _ARABIC.search(t) or _NOISE.search(t)]
    if not toks:
        return {'ok': False, 'weak': True, 'tokens': 0, 'suspect_ratio': 1.0, 'function_ratio': 0.0,
                'reason': 'لا نص عربي مقروء'}
    n = len(toks)
    sr = round(sum(1 for t in toks if _suspect(t)) / n, 3)
    fr = round(sum(1 for t in toks if _is_function(t)) / n, 3)
    res = {'ok': True, 'weak': False, 'tokens': n, 'suspect_ratio': sr, 'function_ratio': fr, 'reason': ''}
    if n < MIN_QUALITY_TOKENS:
        return res
    why = []
    if sr > MAX_SUSPECT_RATIO:
        why.append(f'نسبة الكلمات المريبة {sr:.0%}')
    if fr < MIN_FUNCTION_RATIO:
        why.append(f'كلمات الربط المألوفة {fr:.0%} فقط')
    if why:
        res.update(ok=False, weak=True, reason='؛ '.join(why))
    return res


def quality_warning(doc_type, text):
    """تنبيه جودة لمستند مفتاحي (صحيفة/حكم) أو '' إن كان سليماً أو غير مفتاحي."""
    if doc_type not in KEY_TYPES:
        return ''
    q = text_quality(text)
    return f'{WEAK_MESSAGE} ({q["reason"]})' if q['weak'] else ''


# ---------- مستندات الأرقام: Gemini أولاً ثم Vision ثم الخارجي ثم المحلي، مع إفصاح المحرّك ----------
LOCAL_FALLBACK_MARK = 'استُعمل OCR المحلي'
CRITICAL_LABELS = {T_PLAINT: 'الصحيفة', T_JUDGMENT: 'حكم الإحالة'}


def engine_alert(label, engine_used):
    """تنبيه أحمر إن قُرئ مستند حاسم بغير Gemini، وإلا ''."""
    if not engine_used or engine_used in (ENGINE_GEMINI, 'text_layer'):     # طبقة النص الأصلية لا خطأ قراءة فيها
        return ''
    name = ENGINE_LABELS.get(engine_used, engine_used)
    return (f'قُرئت {label} بمحرك {name}: احتمال وجود أخطاء، تحقق من الأرقام خاصة المبالغ والتواريخ')


def read_numbers_pdf(path, local, text_layer='', status=None):
    """يقرأ PDF مستند أرقام بأقوى محرّك متاح، دون أن يَسقط صامتاً إلى أضعف.
    يرجع dict: text، pages، engine (المحرّك الفعلي)، skipped [(محرّك، سبب)]. text_layer: نص الـPDF الأصلي إن وُجد
    (يُستعمل قبل OCR المحلي فقط). Gemini يُستعمل ولو وُجدت طبقة نصية."""
    skipped = []
    engines = build_engines(local, status)
    steps = []
    try:
        _gemini_provider()
        steps.append(ENGINE_GEMINI)
    except Exception as e:
        skipped.append((ENGINE_GEMINI, 'لا مفتاح Gemini مضبوط' if isinstance(e, EngineUnavailable) else f'Gemini غير متاح: {e}'))
    try:
        import ocr_vision
        if ocr_vision.is_available():
            steps.append(ENGINE_VISION)
        else:
            skipped.append((ENGINE_VISION, 'مفتاح Cloud Vision غير مضبوط'))
    except Exception as e:
        skipped.append((ENGINE_VISION, str(e)))
    try:
        import ocr_space
        if gc.feature_on('ocr_external') and ocr_space.is_available():
            steps.append(ENGINE_EXTERNAL)
        else:
            skipped.append((ENGINE_EXTERNAL, 'OCR الخارجي غير مفعّل'))
    except Exception as e:
        skipped.append((ENGINE_EXTERNAL, str(e)))
    for eng in steps:
        try:
            md, pages, warn = engines[eng](path, {})
        except Exception as e:
            import ai_providers
            if isinstance(e, ai_providers.PersonalKeyFailure):
                raise                                # لا ننتقل لمحرّك آخر بصمت بعد فشل مفتاح Gemini الشخصي
            skipped.append((eng, f'فشل: {gc.short_error(e) if hasattr(gc, "short_error") else e}'))
            continue
        if LOCAL_FALLBACK_MARK in (warn or ''):
            skipped.append((eng, warn))
            continue
        return {'text': md, 'pages': pages, 'engine': eng, 'skipped': skipped}
    if len((text_layer or '').strip()) >= 100:
        return {'text': text_layer, 'pages': 0, 'engine': 'text_layer', 'skipped': skipped}
    text, pages = local(path)
    return {'text': text, 'pages': pages, 'engine': ENGINE_LOCAL, 'skipped': skipped}


def step_alerts(data, step):
    """[(مستوى 'red'|'amber'، نص)] لخطوة: تنبيهات المحرّك الحاسم وتعارض/نقص التحقق من المبالغ."""
    out = []
    if step == 'subject':
        claim = (data.get('engines') or {}).get('claim') or {}
        msg = engine_alert('الصحيفة', claim.get('engine'))
        if msg:
            why = '؛ '.join(f'{e}: {w}' for e, w in claim.get('skipped') or [])
            out.append(('red', msg + (f' (سبب عدم استعمال الأقوى — {why})' if why else '')))
        out += [(lv, t) for lv, t in data.get('subject_alerts') or []]
        miss = data.get('subject_missing') or {}
        core_absent = 'المطالبة' in (miss.get('absent') or [])
        if miss.get('unverified') or miss.get('absent'):
            parts = []
            if miss.get('unverified'):
                parts.append('لم يُتحقق منه: ' + '، '.join(miss['unverified']))
            if miss.get('absent'):
                parts.append('لم يرد في الصحيفة: ' + '، '.join(miss['absent']))
            out.append(('amber', ' — '.join(parts) + ' (حُذفت من الجملة ولم تُخمَّن)'))
    elif step == 'mission':
        raw = (data.get('case') or {}).get('judgment_engine')
        if raw is None:
            try:
                import case_db
                raw = (case_db.get_case(data.get('caso_no') or '') or {}).get('judgment_engine')
            except Exception:
                raw = None
        try:
            info = json.loads(raw) if raw else {}
        except ValueError:
            info = {}
        msg = engine_alert('حكم الإحالة', info.get('engine'))
        if msg:
            why = '؛ '.join(f'{e}: {w}' for e, w in info.get('skipped') or [])
            out.append(('red', msg + (f' (سبب عدم استعمال الأقوى — {why})' if why else '')))
    # «documents»: تنبيه القراءة لكل مستند باسمه الحقيقي وزرّيه في صفحة القضية (case_folder.doc_rows)، لا هنا
    return out
