# ===== case_convert.py — تحويل أي أصل في مجلد القضية إلى markdown (2026-10-18) =====
# المبدأ: ما له نص رقمي يُقرأ مباشرة بلا OCR ولا ذكاء اصطناعي:
#   docx (فقرات + جداول + رأس الصفحة) · doc (Word عبر COM ثم LibreOffice) · rtf (محلل داخلي) · odt (content.xml)
#   txt/md (نسخ) · xlsx/xlsm (openpyxl) · csv (جداول markdown).
# PDF: طبقة النص تُستخرج مباشرة إن كانت «سليمة» في كل الصفحات (عربي بترتيب منطقي لا بصري معكوس، لا ضجيج)،
#   وإلا فالمسار القائم (جيميناي/OCR بحسب نوع المجلد) كما هو مع إفصاح المحرّك.
# convert(path, folder) -> (markdown، عدد الصفحات، المحرّك). الفشل يرفع ConvertError برسالة عربية.
import csv
import io
import os
import re
import zipfile
from xml.etree import ElementTree

import doc_router

WORD_EXTS = ('.docx', '.doc', '.rtf', '.odt')
SHEET_EXTS = ('.xlsx', '.xlsm', '.csv')
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp')
SUPPORTED = ('.pdf',) + IMAGE_EXTS + WORD_EXTS + SHEET_EXTS + doc_router.TEXT_EXTS

ENGINE_DIRECT = 'direct'            # نص رقمي مباشر (Word/جداول/نص)
ENGINE_TEXT_LAYER = 'text_layer'    # طبقة نص PDF
ENGINE_LABELS = {ENGINE_DIRECT: 'تحويل مباشر', ENGINE_TEXT_LAYER: 'طبقة النص في PDF'}

MIN_PAGE_CHARS = 40
_ARABIC = re.compile(r'[؀-ۿ]')
_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class ConvertError(Exception):
    """فشل تحويل ملف (رسالة عربية)."""


# ---------- جداول markdown ----------

def _cell(v):
    s = '' if v is None else str(v)
    return ' '.join(s.replace('|', '\\|').split())


def md_table(rows):
    rows = [[_cell(c) for c in r] for r in rows if any(_cell(c) for c in r)]
    if not rows:
        return ''
    n = max(len(r) for r in rows)
    rows = [r + [''] * (n - len(r)) for r in rows]
    out = ['| ' + ' | '.join(rows[0]) + ' |', '|' + '---|' * n]
    out += ['| ' + ' | '.join(r) + ' |' for r in rows[1:]]
    return '\n'.join(out)


# ---------- Word (docx) ----------

def _p_text(p):
    return ''.join(t.text or '' for t in p.iter(_W + 't')).strip()


def _tbl_rows(tbl):
    rows = []
    for tr in tbl.findall(_W + 'tr'):
        rows.append([' '.join(_p_text(p) for p in tc.iter(_W + 'p') if _p_text(p)) for tc in tr.findall(_W + 'tc')])
    return rows


def _body_blocks(root):
    """الفقرات والجداول بترتيبها في المستند (الجداول المتداخلة تُسطَّح داخل خلاياها)."""
    body = root.find(_W + 'body')
    if body is None:
        body = root
    out = []
    for el in body:
        if el.tag == _W + 'p':
            t = _p_text(el)
            if t:
                out.append(t)
        elif el.tag == _W + 'tbl':
            t = md_table(_tbl_rows(el))
            if t:
                out.append(t)
        elif el.tag == _W + 'sdt':
            out += _body_blocks(el.find(_W + 'sdtContent') if el.find(_W + 'sdtContent') is not None else el)
    return out


def docx_to_markdown(path):
    try:
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read('word/document.xml'))
            headers = [ElementTree.fromstring(z.read(n)) for n in sorted(z.namelist())
                       if re.fullmatch(r'word/header\d*\.xml', n)]
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError) as e:
        raise ConvertError(f'ملف Word تالف أو غير مقروء ({e.__class__.__name__})')
    head, seen = [], set()
    for h in headers:                       # رأس الصفحة فيه رقم المحضر وتاريخه في محاضر البرنامج
        for b in _body_blocks(h):
            if b not in seen:
                seen.add(b)
                head.append(b)
    blocks = _body_blocks(root)
    if not blocks and not head:
        raise ConvertError('لم يُستخرج نص من ملف Word')
    parts = (['<!-- رأس الصفحة -->'] + head + ['<!-- /رأس الصفحة -->'] if head else []) + blocks
    return '<!-- صفحة 1 -->\n' + '\n\n'.join(parts), 1


# ---------- odt ----------

_O = {'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
      'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0'}


def _o_text(el):
    return ' '.join(''.join(el.itertext()).split())


def odt_to_markdown(path):
    try:
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read('content.xml'))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError) as e:
        raise ConvertError(f'ملف ODT تالف أو غير مقروء ({e.__class__.__name__})')
    out = []
    P, H, T = (f"{{{_O['text']}}}p", f"{{{_O['text']}}}h", f"{{{_O['table']}}}table")

    def walk(el):
        for ch in el:
            if ch.tag in (P, H):
                t = _o_text(ch)
                if t:
                    out.append(t)
            elif ch.tag == T:
                rows = [[_o_text(c) for c in r.findall(f"{{{_O['table']}}}table-cell")]
                        for r in ch.iter(f"{{{_O['table']}}}table-row")]
                t = md_table(rows)
                if t:
                    out.append(t)
            else:
                walk(ch)
    walk(root)
    if not out:
        raise ConvertError('لم يُستخرج نص من ملف ODT')
    return '<!-- صفحة 1 -->\n' + '\n\n'.join(out), 1


# ---------- rtf ----------

_RTF_SKIP = {'fonttbl', 'colortbl', 'stylesheet', 'info', 'pict', 'object', 'header', 'footer', 'themedata',
             'datastore', 'latentstyles', 'listtable', 'listoverridetable', 'rsidtbl', 'generator', 'xmlnstbl',
             'mmathPr', 'colorschememapping', 'fldinst'}
_RTF_TOKEN = re.compile(r'\\([a-zA-Z]+)(-?\d+)? ?|\\\'([0-9a-fA-F]{2})|\\(.)|([{}])|[\r\n]+|([^\\{}\r\n]+)')


def rtf_to_text(raw):
    """محلل RTF مبسّط: \\uN و\\'hh بترميز \\ansicpg (العربي cp1256)، يتخطى الجداول الوصفية، \\par/\\cell أسطر."""
    m = re.search(r'\\ansicpg(\d+)', raw)
    enc = f'cp{m.group(1)}' if m else 'cp1256'
    try:
        b''.decode(enc)
    except LookupError:
        enc = 'cp1256'
    stack, skip, uc, pending = [], False, 1, 0
    out, buf = [], bytearray()

    def flush():
        if buf:
            out.append(buf.decode(enc, errors='replace'))
            buf.clear()
    for tok in _RTF_TOKEN.finditer(raw):
        word, arg, hexb, sym, brace, text = tok.groups()
        if brace == '{':
            stack.append((skip, uc))
            continue
        if brace == '}':
            flush()
            if stack:
                skip, uc = stack.pop()
            continue
        if skip:
            continue
        if word:
            if word in _RTF_SKIP:
                skip = True
                continue
            flush()
            if word == 'uc':
                uc = int(arg or 1)
            elif word == 'u':
                n = int(arg)
                out.append(chr(n + 65536 if n < 0 else n))
                pending = uc
            elif word in ('par', 'line', 'row', 'sect', 'page'):
                out.append('\n')
            elif word == 'cell':
                out.append(' | ')
            elif word == 'tab':
                out.append('\t')
            continue
        if hexb:
            if pending:
                pending -= 1
                continue
            buf.append(int(hexb, 16))
            continue
        if sym:
            if sym == '*':
                skip = True
            elif sym in '\\{}':
                flush()
                out.append(sym)
            continue
        if text:
            if pending:
                drop = min(pending, len(text))
                text, pending = text[drop:], pending - drop
            flush()
            out.append(text)
    flush()
    lines = [' '.join(l.split()) for l in ''.join(out).split('\n')]
    return '\n'.join(l for l in lines if l.strip(' |'))


def rtf_to_markdown(path):
    try:
        with open(path, 'rb') as f:
            raw = f.read().decode('latin-1')
    except OSError as e:
        raise ConvertError(f'تعذّرت قراءة ملف RTF ({e.__class__.__name__})')
    if not raw.lstrip().startswith('{\\rtf'):
        raise ConvertError('الملف ليس بصيغة RTF سليمة')
    text = rtf_to_text(raw)
    if not text.strip():
        raise ConvertError('لم يُستخرج نص من ملف RTF')
    return '<!-- صفحة 1 -->\n' + text, 1


# ---------- doc (Word القديم) ----------

def _doc_via_word(path, out_docx):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx('Word.Application')
        word.Visible = False
        word.DisplayAlerts = 0
        d = word.Documents.Open(os.path.abspath(path), ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False)
        d.SaveAs2(os.path.abspath(out_docx), FileFormat=16)
        d.Close(False)
    finally:
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()


def _doc_via_soffice(path, outdir):
    import shutil
    import subprocess
    exe = shutil.which('soffice') or next((p for p in (r'C:\Program Files\LibreOffice\program\soffice.exe',
                                                       r'C:\Program Files (x86)\LibreOffice\program\soffice.exe')
                                           if os.path.exists(p)), None)
    if not exe:
        raise ConvertError('لا Word ولا LibreOffice')
    subprocess.run([exe, '--headless', '--convert-to', 'docx', '--outdir', outdir, path],
                   check=True, timeout=120, capture_output=True)


DOC_CONVERTERS = (_doc_via_word, _doc_via_soffice)     # الاختبارات تستبدلها


def doc_to_markdown(path):
    import tempfile
    reasons = []
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, os.path.splitext(os.path.basename(path))[0] + '.docx')
        for fn in DOC_CONVERTERS:
            try:
                fn(path, out if fn is not _doc_via_soffice else tmp)
                if os.path.exists(out):
                    return docx_to_markdown(out)
            except ConvertError as e:
                reasons.append(str(e))
            except Exception as e:
                reasons.append(f'{fn.__name__.replace("_doc_via_", "")}: {e.__class__.__name__}')
    raise ConvertError('ملف .doc القديم يحتاج Microsoft Word أو LibreOffice على الجهاز (' + '؛ '.join(reasons) + ')')


# ---------- الجداول ----------

def xlsx_to_markdown(path):
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        raise ConvertError(f'ملف Excel تالف أو غير مقروء ({e.__class__.__name__})')
    parts = []
    try:
        for i, ws in enumerate(wb.worksheets, 1):
            t = md_table(list(ws.iter_rows(values_only=True)))
            if t:
                parts.append(f'<!-- صفحة {i} -->\n## {ws.title}\n\n{t}')
    finally:
        wb.close()
    if not parts:
        raise ConvertError('ملف Excel بلا بيانات')
    return '\n\n'.join(parts), len(parts)


def _decode(raw):
    for enc in ('utf-8-sig', 'cp1256'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def csv_to_markdown(path):
    try:
        with open(path, 'rb') as f:
            text = _decode(f.read())
    except OSError as e:
        raise ConvertError(f'تعذّرت قراءة CSV ({e.__class__.__name__})')
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    t = md_table(list(csv.reader(io.StringIO(text), dialect)))
    if not t:
        raise ConvertError('ملف CSV فارغ')
    return '<!-- صفحة 1 -->\n' + t, 1


# ---------- PDF: طبقة النص ----------

def _norm_word(w):
    return doc_router._STRIP.sub('', w).translate(doc_router._NORM)


def arabic_order_ok(text):
    """True إن كان العربي بترتيب منطقي. النص البصري المعكوس (حروف الكلمة مقلوبة) يُكشف بأن كلمات الربط
    الشائعة (في/من/على/التي…) تظهر مقلوبةً أكثر مما تظهر سليمة."""
    words = [w for w in re.findall(r'[؀-ۿ]+', text or '') if len(w) >= 2]
    if len(words) < 8:
        return True
    fw = doc_router._FUNCTION_WORDS
    fwd = sum(1 for w in words if _norm_word(w) in fw)
    rev = sum(1 for w in words if _norm_word(w[::-1]) in fw)
    return fwd >= rev


def page_sound(text):
    """(سليمة؟، السبب) لطبقة نص صفحة واحدة."""
    t = (text or '').strip()
    if len(t) < MIN_PAGE_CHARS:
        return False, 'الصفحة بلا طبقة نص كافية (ممسوحة)'
    if '\ufffd' in t or len(re.findall(r'[\ue000-\uf8ff]', t)) > 3:
        return False, 'رموز خطوط غير قابلة للقراءة'
    if _ARABIC.search(t):
        if not arabic_order_ok(t):
            return False, 'العربي بترتيب بصري معكوس'
        q = doc_router.text_quality(t)
        if not q['ok']:
            return False, q['reason']
    return True, ''


def pdf_text_layer(path):
    """(markdown، صفحات) إن كانت طبقة النص سليمة في كل الصفحات، وإلا (None، السبب)."""
    import fitz
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise ConvertError(f'الملف تالف أو لا يُفتح ({e.__class__.__name__})')
    try:
        if doc.page_count == 0:
            raise ConvertError('الملف بلا صفحات')
        parts = []
        for i in range(doc.page_count):
            t = (doc[i].get_text() or '').strip()
            ok, why = page_sound(t)
            if not ok:
                return None, f'الصفحة {i + 1}: {why}'
            parts.append(f'<!-- صفحة {i + 1} -->\n{t}')
        return '\n\n'.join(parts), doc.page_count
    finally:
        doc.close()


# ---------- نقطة الدخول ----------

def _fallback(path, folder):
    """المسار القائم (جيميناي/OCR بحسب نوع المجلد) مع إفصاح المحرّك."""
    import case_folder as cf
    return cf.legacy_convert(path, folder)


FALLBACK = None          # تستبدله الاختبارات: fn(path, folder) -> (md، صفحات، محرّك)


def convert(path, folder=''):
    ext = os.path.splitext(path)[1].lower()
    if ext in doc_router.TEXT_EXTS:
        import case_documents as cd
        text, pages = cd.text_to_markdown(path)
        return text, pages, ENGINE_DIRECT
    direct = {'.docx': docx_to_markdown, '.doc': doc_to_markdown, '.rtf': rtf_to_markdown, '.odt': odt_to_markdown,
              '.xlsx': xlsx_to_markdown, '.xlsm': xlsx_to_markdown, '.csv': csv_to_markdown}.get(ext)
    if direct:
        text, pages = direct(path)
        return text, pages, ENGINE_DIRECT
    if ext == '.pdf':
        text, pages = pdf_text_layer(path)
        if text:
            return text, pages, ENGINE_TEXT_LAYER
        why = pages
        text, pages, engine = (FALLBACK or _fallback)(path, folder)
        return f'<!-- طبقة النص غير سليمة ({why}) — قُرئ بمحرك: {engine} -->\n{text}', pages, engine
    if ext in IMAGE_EXTS:
        return (FALLBACK or _fallback)(path, folder)
    raise ConvertError(f'صيغة غير مدعومة ({ext or "بلا امتداد"})')
