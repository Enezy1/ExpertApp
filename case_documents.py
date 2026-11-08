# ===== case_documents.py — خطوة «المستندات»: الحوافظ ودفعات الاستيراد (المرحلة 2ي) =====
# الحافظة (المقدِّم والتاريخ) تُسأل مرة، ثم تُختار ملفات فتُرقَّم بالتسلسل داخلها (والرقم قابل للتعديل).
# كل ملف يُنسخ إلى مجلد نوعه في القضية (case_folder: حكم_الإحالة/صحيفة_الدعوى/محاضر/مستندات_أخرى) باسمه الأصلي
# ويُحوَّل إلى markdown/<المسار نفسه>.md (القديم 01_اصول/02_markdown يبقى مقروءاً). يُستدعى import_batch من خيط خلفي؛ التحويل بحدّ أقصى عاملين معاً (OCR ثقيل).
# فشل ملف لا يُفشل الدفعة؛ لكل ملف حالته convert، والخطوة تصير failed إن بقي ملف فاشل
# (يستطيع الخبير المتابعة بـ waive_documents). الأرقام الظاهرة للعرض فقط؛ الإحالة بالمعرّف uid.
# المحوّل: CONVERTER دالة path -> (نص markdown بعلامات <!-- صفحة N -->، عدد الصفحات).
# الحالي مبني على OCR البرنامج (local_ocr) وسيُستبدل لاحقاً بمحوّل Markdown مخصص دون تغيير هذه الوحدة.
import hashlib
import os
import re
import shutil
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree

import case_folder
import case_memory
import case_model as cm
import case_workspace as cw
import doc_router

TEXT_EXTS = doc_router.TEXT_EXTS
SUPPORTED = ('.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.docx') + TEXT_EXTS
MIN_EMBEDDED_CHARS = 40
# نص PDF الرقمي العربي قد يخرج بترتيب بصري معكوس؛ فصفحاته تمرّ على OCR ما لم يُسمح صراحةً.
TRUST_EMBEDDED_ARABIC = False
MAX_WORKERS = 2
_TLS = threading.local()                   # المستند الجاري في كل خيط تحويل (لتقدّم الصفحات)
_ARABIC = re.compile(r'[؀-ۿ]')


class ConvertError(Exception):
    """فشل تحويل ملف (رسالة عربية)."""


# ---------- المحوّل الحالي (OCR داخل البرنامج) ----------

def _docx_text(path):
    try:
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read('word/document.xml'))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError) as e:
        raise ConvertError(f'ملف Word تالف أو غير مقروء ({e.__class__.__name__})')
    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    paras = []
    for p in root.iter(ns + 'p'):
        t = ''.join(x.text or '' for x in p.iter(ns + 't')).strip()
        if t:
            paras.append(t)
    return '\n'.join(paras)


_PAGE_MARK = re.compile(r'<!--\s*صفحة\s*\d+')
_PAGE_LINE = re.compile(r'^[ \t]*-{3,}[ \t]*صفحة[ \t]*(\d+)[ \t]*-{3,}[ \t]*$', re.M)


def text_to_markdown(path):
    """ملف .md/.txt كما هو (لا OCR ولا ذكاء اصطناعي). يرجع (markdown، عدد الصفحات).
    علامات الصفحات الموجودة تبقى؛ وإلا يُحوَّل سطر «--- صفحة N ---» أو فاصل الصفحة \\f؛ وإلا صفحة واحدة."""
    text = doc_router.read_text_file(path).replace('\r\n', '\n').replace('\r', '\n')
    if not text.strip():
        raise ConvertError('الملف فارغ — لا نص فيه')
    marks = _PAGE_MARK.findall(text)
    if marks:
        return text, len(marks)
    if _PAGE_LINE.search(text):
        text = _PAGE_LINE.sub(lambda m: f'<!-- صفحة {m.group(1)} -->', text)
        return text, len(_PAGE_MARK.findall(text))
    pages = [t.strip('\n') for t in text.split('\f')]
    pages = [t for t in pages if t.strip()]
    return '\n\n'.join(f'<!-- صفحة {i} -->\n{t}' for i, t in enumerate(pages, 1)), len(pages)


def ocr_to_markdown(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXTS:
        return text_to_markdown(path)
    if ext not in SUPPORTED:
        raise ConvertError(f'صيغة غير مدعومة ({ext or "بلا امتداد"})')
    if ext == '.docx':
        text = _docx_text(path)
        if not text.strip():
            raise ConvertError('لم يُستخرج نص من الملف')
        return f'<!-- صفحة 1 -->\n{text}', 1
    import fitz
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise ConvertError(f'الملف تالف أو لا يُفتح ({e.__class__.__name__})')
    parts = []
    try:
        if doc.page_count == 0:
            raise ConvertError('الملف بلا صفحات')
        for i in range(doc.page_count):
            page, n = doc[i], i + 1
            emb = (page.get_text() or '').strip()
            if len(emb) >= MIN_EMBEDDED_CHARS and (TRUST_EMBEDDED_ARABIC or not _ARABIC.search(emb)):
                parts.append(f'<!-- صفحة {n} -->\n{emb}')
                continue
            import local_ocr
            if not local_ocr.available():
                raise ConvertError(f'الصفحة {n} تحتاج OCR ومحرّك القراءة غير متاح')
            try:
                pt = local_ocr.read_page(page, n)
            except Exception as e:
                raise ConvertError(f'تعذّرت قراءة الصفحة {n} ({e.__class__.__name__}: {e})')
            marks = ''
            if pt.weak:
                marks += '<!-- ⚠ قراءة ضعيفة: راجع الأصل -->\n'
            if pt.digits == 'indic':
                marks += '<!-- ⚠ أرقام هندية: تحقق من الأرقام والتواريخ -->\n'
            parts.append(f'<!-- صفحة {n} -->\n{marks}{pt.text}')
            doc_router.page_progress(n, doc.page_count)
        pages = doc.page_count
    finally:
        doc.close()
    text = '\n\n'.join(parts)
    if not re.sub(r'<!--.*?-->|\s', '', text):
        raise ConvertError('لم يُستخرج نص من الملف')
    return text, pages


CONVERTER = ocr_to_markdown
# المصنِّف (path -> {'type','confidence','reason','snippet'}) تستبدله الاختبارات.
# المحرّكات: اسم -> fn(path, doc) -> (markdown، صفحات، تحذير).
CLASSIFIER = doc_router.classify_file
ENGINES = doc_router.build_engines(ocr_to_markdown)

# ---------- تخمين النوع والعقد (اقتراح فقط، يؤكده الخبير) ----------
_TYPES = (('عقد', 'عقد'), ('فاتورة', 'فاتورة'), ('إشعار', 'إشعار'), ('اشعار', 'إشعار'),
          ('خطاب', 'خطاب'), ('كشف حساب', 'كشف حساب'), ('مذكرة', 'مذكرة'))
_CONTRACT_RE = re.compile(r'(?:رقم\s*(?:ال)?عقد|عقد[^\n]{0,30}?رقم|عقد\s*:)\s*[:：]?\s*([A-Za-z0-9][\w\-/]{2,})')


def guess_meta(text):
    head = (text or '')[:2000]
    typ = next((label for key, label in _TYPES if key in head), '')
    m = _CONTRACT_RE.search(head)
    return {'type': typ, 'contract': m.group(1) if m else ''}


# ---------- بنية الحافظات ----------

def _sha1_file(path):
    with open(path, 'rb') as f:
        return hashlib.sha1(f.read()).hexdigest()


def _portfolio(data, pid):
    for p in data['portfolios']:
        if p['id'] == pid:
            return p
    raise cm.StepError(f'الحافظة غير موجودة: {pid}')


def all_docs(data):
    for p in data['portfolios']:
        for d in p['docs']:
            yield p, d


def find_doc(data, uid):
    for p, d in all_docs(data):
        if d['uid'] == uid:
            return p, d
    raise cm.StepError(f'المستند غير موجود: {uid}')


def add_portfolio(data, submitter, date):
    submitter = (submitter or '').strip()
    if not submitter:
        raise cm.StepError('اسم مقدِّم الحافظة مطلوب.')
    nums = [int(p['id'][1:]) for p in data['portfolios'] if re.fullmatch(r'P\d+', p['id'])]
    p = {'id': f'P{max(nums, default=0) + 1}', 'submitter': submitter, 'date': (date or '').strip(),
         'seq': 0, 'docs': []}
    data['portfolios'].append(p)
    return p


def plan_batch(data, pid, paths):
    """ترقيم مقترح للملفات المختارة: يتابع بعد أكبر رقم في الحافظة. قابل للتعديل قبل الاستيراد."""
    p = _portfolio(data, pid)
    start = max((d['no'] for d in p['docs']), default=0) + 1
    return [{'src': s, 'no': start + i} for i, s in enumerate(paths)]


# ---------- الاستيراد والتحويل ----------

def _write_md(base, rel, text):
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.md.', suffix='.tmp', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


_CONTENT_KINDS = ((re.compile(r'مذكر[ةه]\s+(?:ب|ال)?دفاع|مذكر[ةه]\s+(?:ختامية|شارحة|بالرد)'), 'مذكرة دفاع'),
                  (re.compile(r'حافظ[ةه]\s+(?:ال)?مستندات'), 'حافظة مستندات'))
_CONTENT_DATE = re.compile(r'(?:بجلسة|جلسة|بتاريخ|المؤرخ[ةه]?)[\s:：|*]*'
                           r'([\d٠-٩]{1,4}\s*[/\-.]\s*[\d٠-٩]{1,2}\s*[/\-.]\s*[\d٠-٩]{1,4})')


def _role_from_head(head):
    """صفة المقدِّم من رأس الصفحة: «مـن: … | صفتها: مدعية» أو «مذكرة بدفاع المدعية». التباس (الصفتان معاً
    بلا ربط) ← '' فلا تخمين؛ ويُضبط المقدّم بعدها من الحافظة/الذكاء أو يحدّده الخبير."""
    import case_procedures as cp
    n = cp.norm_ar(head.replace('ـ', ''))
    m = re.search(r'من\s+[^|]{0,80}?\s+صفت\w*\s+(مدعي\s*علي|مدعي)', n)
    if m:
        return 'defendant' if 'علي' in m.group(1) else 'plaintiff'
    m = re.search(r'مذكره\s+(?:ب)?دفاع\s+(?:الشركه\s+)?(?:ال)?(مدعي\s*علي|مدعي)', n)
    if m:
        return 'defendant' if 'علي' in m.group(1) else 'plaintiff'
    pl = bool(re.search(r'المدعي(?:ه)?(?!\s*علي)', n))
    df = bool(re.search(r'المدعي\s*علي', n))
    return 'plaintiff' if pl and not df else 'defendant' if df and not pl else ''


def detect_contents(text):
    """[{'kind','role','date'}] لكل مذكرة/حافظة تبدأ في رأس صفحة من الملف (أول 600 حرف من الصفحة)."""
    import case_attachments
    import case_procedures as cp
    out = []
    for pg in re.split(r'<!--\s*صفحة\s*\d+\s*-->', text or ''):
        head = re.sub(r'<!--.*?-->', ' ', pg, flags=re.S).replace('ـ', '')[:900]
        for rx, kind in _CONTENT_KINDS:
            m = rx.search(head)
            if not m:
                continue
            ctx = head[m.start():]
            dm = _CONTENT_DATE.search(ctx)
            rec = {'kind': kind, 'role': _role_from_head(head),
                   'date': (cp.minute_date([dm.group(1)]) if dm else '') or ''}
            if rec not in out:
                out.append(rec)
            break
    return out


def contents_header(contents):
    names = {'plaintiff': 'المدعية', 'defendant': 'المدعى عليه'}
    parts = []
    for c in contents:
        d = c['date']
        dmy = f'{d[8:10]}/{d[5:7]}/{d[:4]}' if re.fullmatch(r'\d{4}-\d{2}-\d{2}', d or '') else d
        parts.append(' '.join(x for x in (c['kind'], names.get(c['role'], ''), f'المؤرخة {dmy}' if dmy else '') if x))
    return '<!-- يحتوي هذا المستند على: ' + '؛ '.join(parts) + ' -->\n'


def _convert_doc(base, doc, convert, engines=None):
    """يحوّل مستنداً واحداً ويرجع (convert_dict، حقول إضافية). لا يرفع استثناءً.
    convert صريح (توافق قديم) يُستعمل لكل الملفات؛ وإلا يُختار المحرّك من doc['engine'] (الافتراضي: المحلي)."""
    if not doc.get('file'):
        return {'state': 'failed', 'message': doc['convert'].get('message') or 'لا يوجد ملف'}, {}
    try:
        path = os.path.join(base, doc['file'])
        if doc.get('engine') == doc_router.ENGINE_TEXT:      # نص جاهز: نسخ فقط، حتى لو مُرِّر convert
            text, pages = text_to_markdown(path)
            warning = ''
        elif convert is not None:
            text, pages = convert(path)
            warning = ''
        else:
            fn = (engines or ENGINES).get(doc.get('engine') or doc_router.ENGINE_LOCAL)
            if fn is None:
                raise ConvertError(f"محرّك غير معروف: {doc.get('engine')}")
            text, pages, warning = fn(path, doc)
        if warning:
            text = f'<!-- ⚠ {warning} -->\n{text}'
        contents = detect_contents(text)
        if contents and doc.get('engine') != doc_router.ENGINE_TEXT:     # رأس واضح: ما يحتويه الملف (قد يضم أكثر من مذكرة/حافظة في PDF واحد)
            text = contents_header(contents) + text
        _write_md(base, doc['md'], text)
        try:
            if doc['file'].split('/', 1)[0] in case_folder.FOLDERS:
                case_folder.record_converted(base, doc['file'], doc['md'])     # المزامنة لا تعيد تحويله
        except OSError:
            pass
        used = (doc_router.ENGINE_LOCAL if doc_router.LOCAL_FALLBACK_MARK in (warning or '')
                else doc.get('engine') or doc_router.ENGINE_LOCAL)
        extra = {'contents': contents, 'engine_used': used, 'pages': pages, 'sha1': _sha1_file(os.path.join(base, doc['md'])), 'warning': warning,
                 'quality_warning': doc_router.quality_warning(doc.get('doc_type'), text),
                 'origin': 'original' if doc.get('engine') == doc_router.ENGINE_TEXT else 'converted'}
        g = guess_meta(text)
        crit = doc_router.CRITICAL_LABELS.get(doc.get('doc_type')) or (
            'العقد' if (g['type'] or doc.get('type')) == 'عقد' else 'الفاتورة' if (g['type'] or doc.get('type')) == 'فاتورة'
            else '')
        extra['engine_alert'] = (doc_router.engine_alert(crit, used)
                                 if crit and used != doc_router.ENGINE_TEXT else '')
        if not doc.get('kind_known') and not doc.get('kind_asked'):     # المحتوى الكامل أوضح من مقتطف التصنيف
            m = content_meta(re.sub(r'<!--.*?-->', '', text)[:3000])
            if m['known'] or 'kind' not in doc:
                extra.update(kind=m['kind'], doc_date=doc.get('doc_date') or m['date'],
                             parties=doc.get('parties') or m['parties'], kind_known=m['known'])
        if not doc.get('type') and g['type']:
            extra['type'] = g['type']
        if not doc.get('contract') and g['contract']:
            extra['contract'] = g['contract']
        return {'state': 'done', 'message': ''}, extra
    except ConvertError as e:
        return {'state': 'failed', 'message': str(e)}, {}
    except Exception as e:
        return {'state': 'failed', 'message': f'{e.__class__.__name__}: {e}'}, {}


def _refresh_step(data):
    docs = [d for _, d in all_docs(data)]
    if any(d['convert']['state'] == 'running' for d in docs):
        return
    held = [d for d in docs if d['convert']['state'] == 'pending' and d.get('needs_type')]
    if held:
        cm.set_step(data, 'documents', 'needs_input', f'{len(held)} مستنداً بانتظار اختيار نوعه قبل التحويل')
        return
    left = [d for d in docs if d['convert']['state'] == 'pending']
    if left:
        cm.set_step(data, 'documents', 'needs_input', f'{len(left)} مستنداً لم يُحوَّل بعد — يُستأنف تلقائياً')
        return
    failed = [d for d in docs if d['convert']['state'] == 'failed']
    if failed:
        cm.set_step(data, 'documents', 'failed',
                    f'فشل تحويل {len(failed)} من {len(docs)} مستنداً — أعد المحاولة أو تابع بموافقتك')
    else:
        cm.set_step(data, 'documents', 'done', f'{len(docs)} مستنداً محوَّلاً')


def _save(base, data):
    cw.write_case_json(base, data)


def _memory(base, data):
    try:
        case_memory.update_section(base, data, 'status', 'docs_table', 'docs_text')
    except Exception:
        pass       # الذاكرة مشتقة: فشلها لا يُفشل الاستيراد


def find_by_fingerprint(data, sha1, pid=None):
    """(حافظة، مستند) سبق استيراد ملف بالبصمة نفسها داخل الحافظة pid (كل الحوافظ إن None) ما لم يفشل تحويله."""
    if not sha1:
        return None
    for p, d in all_docs(data):
        if pid and p['id'] != pid:
            continue
        if d.get('src_sha1') == sha1 and (d.get('convert') or {}).get('state') != 'failed':
            return p, d
    return None


def text_fingerprint(path):
    """بصمة محتوى ملف md/txt مستقلة عن الاسم والمجلد: توحيد النهايات والمسافات الطرفية والـBOM. '' عند التعذّر."""
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError:
        return ''
    t = raw.decode('utf-8-sig', errors='replace').replace('\r\n', '\n').replace('\r', '\n')
    t = '\n'.join(line.rstrip() for line in t.split('\n')).strip()
    return hashlib.sha1(t.encode('utf-8')).hexdigest() if t else ''


def find_text_original(data, tsha):
    """(حافظة، مستند) أصل نصي محوَّل بالمحتوى نفسه في أي حافظة (المراجع لا تُحسب أصولاً)."""
    if not tsha:
        return None
    for p, d in all_docs(data):
        if d.get('text_sha') == tsha and not d.get('ref_of') and (d.get('convert') or {}).get('state') == 'done':
            return p, d
    return None


def content_docs(data):
    """(حافظة، مستند) بلا المراجع المكررة: لكل محتوى نسخة واحدة في الملخص/البحث (المرجع يبقى في جدول المستندات والمرفقات)."""
    for p, d in all_docs(data):
        if not d.get('ref_of'):
            yield p, d


def classify_files(data, paths, pid=None):
    """حالة كل ملف مختار قبل الاستيراد: [(مسار، 'new'|'done'|'failed'|'pending', مستند أو None)].
    'done' = سبق تحويله (لا يُحوَّل ثانية)؛ 'failed' = سبق فشله (زر إعادة المحاولة يخصّه)."""
    out = []
    for path in paths:
        try:
            sha = _sha1_file(path)
        except OSError:
            out.append((path, 'new', None))
            continue
        hit = next(((p, d) for p, d in all_docs(data)
                    if d.get('src_sha1') == sha and (not pid or p['id'] == pid)), None)
        if hit is None:
            out.append((path, 'new', None))
        else:
            st = hit[1]['convert']['state']
            out.append((path, st if st in ('done', 'failed') else 'pending', hit[1]))
    return out


def add_files(base, data, pid, items, classify=None):
    """ينسخ الملفات إلى 01_اصول ويسجّلها بحالة pending (لا تحويل هنا). الملف الذي سبق استيراده (بالبصمة)
    يُتخطّى. كل ملف جديد يُصنَّف (OCR الصفحة الأولى + قواعد) ويُعيَّن محرّكه؛ «غير معروف» يُحجز حتى يختار الخبير.
    يرجع قائمة المستندات الجديدة. items: [{'src','no'}]."""
    classify = classify or CLASSIFIER
    p = _portfolio(data, pid)
    nos = [it['no'] for it in items]
    taken = {d['no'] for d in p['docs']}
    if len(set(nos)) != len(nos) or taken & set(nos) or any(int(n) < 1 for n in nos):
        raise cm.StepError('أرقام المستندات مكرّرة أو غير صالحة داخل الحافظة.')
    new_docs = []
    uid_n = data.get('next_doc_uid', 1)
    for it in items:
        src = it['src']
        try:
            sha = _sha1_file(src)
        except OSError:
            sha = ''
        if find_by_fingerprint(data, sha, pid):
            continue                                   # سبق استيراده: لا نسخة ثانية ولا تحويل
        is_text = os.path.splitext(src)[1].lower() in TEXT_EXTS
        tsha = text_fingerprint(src) if is_text else ''
        orig = find_text_original(data, tsha) if tsha else None
        if orig is not None:                           # المحتوى نفسه (باسم أو حافظة مختلفة): مرجع جديد بلا تحويل ولا تكرار
            op, od = orig
            if op['id'] == pid:
                continue
            p['seq'] += 1
            doc = {'uid': f'd{uid_n}', 'no': int(it['no']), 'seq': p['seq'], 'file': od['file'], 'md': od['md'],
                   'orig_name': os.path.basename(src), 'type': od.get('type', ''), 'contract': od.get('contract', ''),
                   'pages': od.get('pages', 0), 'sha1': od.get('sha1', ''), 'src_sha1': sha, 'text_sha': tsha,
                   'origin': 'original', 'engine': doc_router.ENGINE_TEXT, 'ref_of': od['uid'],
                   'ref_label': f"{op['id']}-{od['no']}", 'doc_type': od.get('doc_type', ''), 'needs_type': False,
                   'convert': {'state': 'done', 'message': f"مرجع للمستند {op['id']}-{od['no']} (محتوى مطابق — لم يُحوَّل ثانية)"}}
            uid_n += 1
            p['docs'].append(doc)
            new_docs.append(doc)
            continue
        p['seq'] += 1
        seq, uid = p['seq'], f'd{uid_n}'
        uid_n += 1
        ext = os.path.splitext(src)[1].lower()
        doc = {'uid': uid, 'no': int(it['no']), 'seq': seq, 'file': '', 'md': '',
               'orig_name': os.path.basename(src),
               'type': '', 'contract': '', 'pages': 0, 'sha1': '', 'src_sha1': sha,
               'origin': 'converted',
               'convert': {'state': 'pending', 'message': ''}}
        # مجلد القضية هو الأصل: يُصنَّف الملف أولاً ثم يُنسخ إلى مجلد نوعه (غير المعروف ← مستندات_أخرى)
        if ext not in TEXT_EXTS:
            _apply_classification(doc, classify, src)
            apply_content_meta(doc, doc.get('first_text') or '')
        else:
            try:
                with open(src, encoding='utf-8', errors='replace') as fh:
                    apply_content_meta(doc, fh.read(3000))
            except OSError:
                pass
        try:
            ctype = doc.get('doc_type') if ext not in TEXT_EXTS else doc_router.classify_text_file(src).get('type')
        except Exception:
            ctype = None
        try:
            rel = case_folder.add_original(base, src, case_folder.OTHER)     # يُفرز ويُسمّى بعد تحويله (case_sort)
        except OSError as e:
            doc.update(convert={'state': 'failed', 'message': f'تعذّر نسخ الملف: {e}'})
        else:
            doc.update(file=rel, md=case_folder.md_rel(rel))
            if ext in TEXT_EXTS:
                doc['text_sha'] = tsha
                _import_text(base, doc)
        p['docs'].append(doc)
        new_docs.append(doc)
    data['next_doc_uid'] = uid_n
    p['docs'].sort(key=lambda d: d['no'])
    if any(d.get('engine') == doc_router.ENGINE_TEXT for d in new_docs):
        _settle_step(base, data)
    _save(base, data)
    return new_docs


def _import_text(base, doc):
    """ملف .md/.txt: يُصنَّف بقراءة أول نصه (بلا OCR) ويُنسخ فوراً إلى 02_markdown دون أي محرّك تحويل.
    الفارغ يفشل برسالة تنبيه (لا يُحسب محوَّلاً)."""
    try:
        res = doc_router.classify_text_file(os.path.join(base, doc['file']))
    except Exception as e:
        res = {'type': doc_router.T_UNKNOWN, 'confidence': 0.0, 'snippet': '',
               'reason': f'تعذّر التصنيف ({e.__class__.__name__}: {e})'}
    doc.update(doc_type=res['type'], type_conf=float(res.get('confidence') or 0), type_reason=res.get('reason', ''),
               first_text=res.get('snippet', ''), engine=doc_router.ENGINE_TEXT, manual=False, needs_type=False,
               origin='original')
    conv, extra = _convert_doc(base, doc, None)
    doc['convert'] = conv
    doc.update(extra)


def _settle_step(base, data):
    """بعد إضافة نصوص جاهزة (تُنجَز فوراً): حدّث حالة الخطوة والذاكرة والمرفقات كما بعد أي تحويل."""
    try:
        if cm.state(data, 'documents') != 'running':
            cm.set_step(data, 'documents', 'running')
        _refresh_step(data)
    except cm.StepError:
        pass
    _memory(base, data)
    _sync_attachments(base, data)


def _apply_classification(doc, classify, path):
    try:
        res = classify(path)
    except Exception as e:
        res = {'type': doc_router.T_UNKNOWN, 'confidence': 0.0,
               'reason': f'تعذّر التصنيف ({e.__class__.__name__}: {e})'}
    t = res.get('type') if res.get('type') in doc_router.TYPES else doc_router.T_UNKNOWN
    engine = doc_router.engine_for(t)
    doc.update(doc_type=t, type_conf=float(res.get('confidence') or 0), type_reason=res.get('reason', ''),
               first_text=res.get('snippet', ''), engine=engine or '', manual=False, needs_type=engine is None)


def _editable(d):
    if d.get('engine') == doc_router.ENGINE_TEXT:
        raise cm.StepError('ملف نصي جاهز: لا يحتاج تحويلاً ولا يُرسل لأي محرّك.')
    if d['convert']['state'] not in ('pending', 'failed'):
        raise cm.StepError('لا يمكن تغيير النوع/المحرّك بعد بدء التحويل أو اكتماله.')


def set_doc_type(base, data, uid, doc_type, engine=None):
    """اختيار/تغيير نوع المستند يدوياً قبل التحويل (pending أو failed). المحرّك من التوجيه ما لم يُمرَّر engine."""
    _, d = find_doc(data, uid)
    if doc_type not in doc_router.KNOWN_TYPES:
        raise cm.StepError(f'نوع غير صالح: {doc_type}')
    _editable(d)
    d['doc_type'] = doc_type
    d['engine'] = engine if engine in doc_router.ENGINES else doc_router.engine_for(doc_type)
    _relocate(base, d)
    d.update(manual=True, needs_type=False, type_reason=f'اختيار الخبير: {doc_type}')
    _refresh_step(data)
    _save(base, data)


def _relocate(base, d):
    """منذ البنية المختصرة (2026-10-21) النقل والتسمية للفرز الآلي وحده (case_sort، بالمحتوى ومقدّمه وتاريخه)."""
    return
    f = d.get('file') or ''
    want = case_folder.folder_for_type(d.get('doc_type')) or case_folder.OTHER
    if not f or f.split('/', 1)[0] not in case_folder.FOLDERS or f.split('/', 1)[0] == want:
        return
    src = os.path.join(base, f)
    if not os.path.isfile(src):
        return
    os.makedirs(os.path.join(base, want), exist_ok=True)
    dst = case_folder._unique(os.path.join(base, want), os.path.basename(f))
    os.replace(src, dst)
    d['file'] = os.path.relpath(dst, base).replace('\\', '/')
    d['md'] = case_folder.md_rel(d['file'])


def set_doc_engine(base, data, uid, engine):
    _, d = find_doc(data, uid)
    if engine not in doc_router.ENGINES:
        raise cm.StepError(f'محرّك غير صالح: {engine}')
    _editable(d)
    if d.get('needs_type'):
        raise cm.StepError('اختر نوع المستند أولاً.')
    d['engine'] = engine
    d['manual'] = True
    _save(base, data)


def recover_running(data):
    """مستند بقي running (أُغلق البرنامج أثناءه) ← pending ليُحوَّل مع الجديد. يرجع هل تغيّر شيء."""
    changed = False
    for _, d in all_docs(data):
        if d['convert']['state'] == 'running':
            d['convert'] = {'state': 'pending', 'message': ''}
            changed = True
    return changed


def pending_docs(data):
    return [d for _, d in all_docs(data)
            if d['convert']['state'] == 'pending' and d.get('file') and not d.get('needs_type')]


def process_pending(base, data, convert=None, on_update=None, workers=MAX_WORKERS, stop=None, uids=None,
                    engines=None):
    """يحوّل المستندات pending فقط (الجديد). stop() → True يوقف قبل بدء الملف التالي (يبقى pending).
    يرجع {'total','done','failed','left','uids'}. آمن للاستدعاء من خيط خلفي."""
    on_update = on_update or (lambda uid, conv: None)
    stop = stop or (lambda: False)
    lock = threading.Lock()
    todo = [d for d in pending_docs(data) if uids is None or d['uid'] in uids]
    if not todo:
        return {'total': 0, 'done': 0, 'failed': 0, 'left': 0, 'uids': []}
    if cm.state(data, 'documents') != 'running':
        cm.set_step(data, 'documents', 'running')
    _save(base, data)

    def page_hook(done, total):                # تقدّم الصفحات للملف الجاري في هذا الخيط ← نسبة الملف حيّة
        doc = getattr(_TLS, 'doc', None)
        if doc is None or not total:
            return
        with lock:
            doc['convert']['progress'] = max(0, min(99, int(done * 100 / total)))
        on_update(doc['uid'], dict(doc['convert']))

    def work(doc):
        if stop():
            return
        with lock:
            doc['convert'] = {'state': 'running', 'message': '', 'progress': 0}
        on_update(doc['uid'], dict(doc['convert']))
        _TLS.doc = doc
        try:
            conv, extra = _convert_doc(base, doc, convert, engines)
        finally:
            _TLS.doc = None
        with lock:
            doc['convert'] = conv
            doc.update(extra)
            _save(base, data)
        on_update(doc['uid'], dict(conv))

    prev_hook, doc_router.PAGE_HOOK = doc_router.PAGE_HOOK, page_hook
    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            list(ex.map(work, todo))
    finally:
        doc_router.PAGE_HOOK = prev_hook
    with lock:
        _refresh_step(data)
        _save(base, data)
    _memory(base, data)
    _sync_attachments(base, data)
    states = [d['convert']['state'] for d in todo]
    return {'total': len(todo), 'done': states.count('done'), 'failed': states.count('failed'),
            'left': states.count('pending'), 'uids': [d['uid'] for d in todo]}


def _sync_attachments(base, data):
    try:
        import case_attachments
        case_attachments.sync_attachments(base, data)
    except Exception:
        pass       # المرفقات مشتقة وتتجدد في أي وقت


def import_batch(base, data, pid, items, convert=None, on_update=None, workers=MAX_WORKERS, stop=None,
                 classify=None, engines=None):
    """نسخ + تحويل في استدعاء واحد (للاختبارات والتوافق). الواجهة تستعمل add_files ثم process_pending."""
    new_docs = add_files(base, data, pid, items, classify)
    uids = {d['uid'] for d in new_docs}
    process_pending(base, data, convert, on_update, workers, stop, uids=uids, engines=engines)
    if new_docs and not pending_docs(data):             # كل الجديد فشل نسخه: حدّث حالة الخطوة
        if cm.state(data, 'documents') != 'running':
            cm.set_step(data, 'documents', 'running')
        _refresh_step(data)
        _save(base, data)
    states = [d['convert']['state'] for d in new_docs]
    return {'total': len(new_docs), 'done': states.count('done'), 'failed': states.count('failed'),
            'left': states.count('pending'), 'uids': [d['uid'] for d in new_docs]}


def reconvert(base, data, uid, convert=None, on_update=None, engines=None):
    """إعادة تحويل مستند واحد فاشل (زر «إعادة المحاولة»). يرجع حالة التحويل."""
    p, doc = find_doc(data, uid)
    if cm.state(data, 'documents') != 'running':
        cm.set_step(data, 'documents', 'running')
    doc['convert'] = {'state': 'running', 'message': '', 'progress': 0}
    _save(base, data)
    if on_update:
        on_update(uid, dict(doc['convert']))

    def page_hook(done, total):                  # تقدّم الصفحات حيّاً (زر 🔄 / إعادة المحاولة) كما في التحويل الجماعي
        if total:
            doc['convert']['progress'] = max(0, min(99, int(done * 100 / total)))
            if on_update:
                on_update(uid, dict(doc['convert']))
    prev_hook, doc_router.PAGE_HOOK = doc_router.PAGE_HOOK, page_hook
    try:
        conv, extra = _convert_doc(base, doc, convert, engines)
    except Exception as e:                       # لا استثناء مبلوع: الفشل حالة ظاهرة برسالة
        conv, extra = {'state': 'failed', 'message': str(e) or e.__class__.__name__}, {}
    finally:
        doc_router.PAGE_HOOK = prev_hook
    doc['convert'] = conv
    doc.update(extra)
    _refresh_step(data)
    _save(base, data)
    if on_update:
        on_update(uid, dict(conv))
    _memory(base, data)
    _sync_attachments(base, data)
    return conv['state']


_ENGINE_RANK = {doc_router.ENGINE_LOCAL: 0, doc_router.ENGINE_EXTERNAL: 1, doc_router.ENGINE_VISION: 2,
                doc_router.ENGINE_GEMINI: 3}


def stronger_engine(doc):
    """أقوى محرّك مضبوط إن كان أقوى من محرّك المستند الحالي، وإلا None."""
    best = doc_router.best_engine()
    cur = doc.get('engine') or doc_router.ENGINE_LOCAL
    return best if _ENGINE_RANK.get(best, 0) > _ENGINE_RANK.get(cur, 0) else None


def reread_stronger(base, data, uid, convert=None, on_update=None, engines=None):
    """زر «أعد قراءتها بمحرك أقوى»: يبدّل محرّك المستند إلى أقوى مضبوط ويعيد التحويل. يرجع (حالة، المحرّك الجديد)."""
    _p, doc = find_doc(data, uid)
    if doc.get('engine') == doc_router.ENGINE_TEXT:
        raise cm.StepError('ملف نصي جاهز: لا يُقرأ بمحرّك.')
    target = stronger_engine(doc)
    if target is None:
        raise cm.StepError('لا يوجد محرّك أقوى مضبوط — اضبط مفتاح Gemini أو OCR الخارجي من الإعدادات.')
    doc['engine'] = target
    doc['manual'] = True
    return reconvert(base, data, uid, convert, on_update, engines), target


def reconvert_with(base, data, uid, engine, convert=None, on_update=None, engines=None):
    """إعادة عمل markdown لمستند مكتمل بمحرّك يختاره الخبير (زر 🔄). يرجع حالة التحويل."""
    _p, doc = find_doc(data, uid)
    if doc.get('engine') == doc_router.ENGINE_TEXT:
        raise cm.StepError('ملف نصي جاهز: لا يُقرأ بمحرّك.')
    if engine not in doc_router.ENGINES:
        raise cm.StepError(f'محرّك غير صالح: {engine}')
    doc['engine'] = engine
    doc['manual'] = True
    return reconvert(base, data, uid, convert, on_update, engines)


def renumber(base, data, pid, new_numbers):
    """new_numbers: {uid: رقم}. الأرقام للعرض فقط (الملفات والمعرّفات لا تتغيّر). يرجع نص تحذير أو ''.
    تغيير الأرقام يجعل المرفقات والبحث «تحتاج تحديثاً»؛ وإن وُجدت بنود مكتوبة يُحذَّر."""
    p = _portfolio(data, pid)
    cur = {d['uid']: d['no'] for d in p['docs']}
    unknown = set(new_numbers) - set(cur)
    if unknown:
        raise cm.StepError(f'مستندات غير موجودة في الحافظة: {sorted(unknown)}')
    final = dict(cur, **{u: int(n) for u, n in new_numbers.items()})
    vals = list(final.values())
    if len(set(vals)) != len(vals) or any(n < 1 for n in vals):
        raise cm.StepError('الأرقام مكرّرة أو غير صالحة داخل الحافظة.')
    if final == cur:
        return ''
    for d in p['docs']:
        d['no'] = final[d['uid']]
    p['docs'].sort(key=lambda d: d['no'])
    cm.mark_modified(data, 'documents')
    _save(base, data)
    _memory(base, data)
    return ('تنبيه: توجد بنود بحث مكتوبة قد تُحيل إلى أرقام المستندات القديمة — راجعها.'
            if data.get('research') else '')


def set_doc_meta(base, data, uid, type=None, contract=None):
    _, d = find_doc(data, uid)
    if type is not None:
        d['type'] = type.strip()
    if contract is not None:
        d['contract'] = contract.strip()
    _save(base, data)
    _memory(base, data)


def waive_documents(base, data, waived=True):
    """متابعة الخبير رغم نقص المستندات (يفكّ حجب البحث)؛ لا يسري على المرفقات."""
    data['steps']['documents']['waived'] = bool(waived)
    cm.refresh_blocked(data)
    _save(base, data)


# ---------- قراءة المحتوى (الصفحة الأولى) لا الاسم — 2026-10-18 ----------
# نوع المستند بحسب محتواه: يُبحث بالترتيب (الأخص أولاً) في أول 1500 حرف من الصفحة الأولى.
CONTENT_KINDS = (('أمر تغيير', 'أمر تغيير'), ('أمر التغيير', 'أمر تغيير'), ('أمر شراء', 'أمر شراء'),
                 ('أمر الشراء', 'أمر شراء'), ('ملحق', 'ملحق'), ('حافظة مستندات', 'حافظة'),
                 ('صحيفة', 'صحيفة دعوى'), ('محضر', 'محضر'), ('مذكرة', 'مذكرة'), ('حكمت المحكمة', 'حكم'),
                 ('باسم صاحب السمو', 'حكم'), ('حكم', 'حكم'), ('اتفاقية', 'عقد'), ('عقد', 'عقد'),
                 ('فاتورة', 'فاتورة'), ('كشف حساب', 'كشف حساب'), ('إنذار', 'إنذار'), ('كتاب', 'كتاب'))
CONTENT_KIND_LABELS = ('عقد', 'ملحق', 'أمر شراء', 'أمر تغيير', 'حافظة', 'مذكرة', 'محضر', 'حكم', 'صحيفة دعوى',
                       'فاتورة', 'كشف حساب', 'إنذار', 'كتاب', 'أخرى')
_PARTY_RES = (re.compile(r'(?:الطرف\s+الأول|الطرف الاول)\s*[:：]?\s*([^\n:،,]{3,60})'),
              re.compile(r'(?:الطرف\s+الثاني)\s*[:：]?\s*([^\n:،,]{3,60})'),
              re.compile(r'(?:بين|أبرم بين)\s*[:：]?\s*([^\n،,]{3,60}?)\s+و\s*(?:بين\s+)?([^\n،,]{3,60})'),
              re.compile(r'(?:المدعي(?:ة)?|المدعى عليه(?:ا)?)\s*[:：/]\s*([^\n:،,]{3,60})'))
_SUBMIT_RE = re.compile(r'(?:مقدمة|المقدمة|مقدّمة|المقدّمة|مقدم|المقدم)\s+من\s*[:：]?\s*(?:قبل\s+)?([^\n،,]{3,60})')
_SIDE_RE = re.compile(r'(?:من\s+)?(?:ال)?(المدعى عليه(?:ا|م)?|المدعي(?:ة)?|المتدخل(?:ة)?)')


def _clean_name(s):
    s = re.sub(r'\s+', ' ', (s or '').strip(' .:-–—\t'))
    return re.split(r'\s(?:بتاريخ|بجلسة|في|المؤرخ)\s', s)[0].strip()[:60]


def content_meta(text):
    """{'kind','date','parties','known'} من نص الصفحة الأولى (قواعد، بلا ذكاء). known=False ← يُسأل الخبير مرة."""
    import case_procedures as cp
    head = (text or '')[:1500]
    kind = next((label for key, label in CONTENT_KINDS if key in head), '')
    d = cp.date_from_text(head) if head.strip() else ''
    parties = []
    for rx in _PARTY_RES:
        for m in rx.finditer(head):
            for g in m.groups():
                n = _clean_name(g)
                if n and n not in parties:
                    parties.append(n)
    return {'kind': kind or 'أخرى', 'date': d, 'parties': parties[:4], 'known': bool(kind)}


def suggest_portfolio(text):
    """اقتراح مقدِّم الحافظة وتاريخها من الصفحة الأولى: (المقدِّم، التاريخ yyyy-mm-dd) — فارغ لما لم يتضح."""
    import case_procedures as cp
    head = (text or '')[:2000]
    who = ''
    m = _SUBMIT_RE.search(head)
    if m:
        who = _clean_name(m.group(1))
    if not who:
        m = _SIDE_RE.search(head)
        who = m.group(1) if m else ''
    d = ''
    m = re.search(r'(?:بجلسة|بتاريخ|جلسة)\s*[:：]?\s*', head)
    if m:
        d = cp.minute_date([head[m.end():m.end() + 20]]) or ''
    return clean_submitter(who), d or (cp.date_from_text(head) if head.strip() else '')


def apply_content_meta(doc, text):
    meta = content_meta(text)
    doc.update(kind=meta['kind'], doc_date=meta['date'], parties=meta['parties'], kind_known=meta['known'])
    return meta


def unknown_kind_docs(data):
    """المستندات التي لم يتضح نوعها من محتواها ولم يُسأل عنها بعد (يُسأل الخبير مرة واحدة)."""
    return [d for _, d in all_docs(data) if d.get('kind_known') is False and not d.get('kind_asked')]


def set_kinds(base, data, chosen):
    """chosen: {uid: نوع}. كل مستند سُئل عنه يُعلَّم فلا يُسأل ثانية ولو تُرك فارغاً."""
    for _, d in all_docs(data):
        if d.get('kind_known') is False and not d.get('kind_asked'):
            d['kind_asked'] = True
            k = chosen.get(d['uid'])
            if k:
                d.update(kind=k, kind_known=True, kind_manual=True)
    _save(base, data)


def update_portfolio(base, data, pid, submitter=None, date=None):
    p = _portfolio(data, pid)
    changed = False
    if submitter is not None and submitter.strip() and submitter.strip() != p['submitter']:
        p['submitter'], changed = submitter.strip(), True
    if date is not None and date.strip() != p.get('date', ''):
        p['date'], changed = date.strip(), True
    if changed:
        p['auto_meta'] = False                  # عدّله الخبير بيده ← لا يُضبط آلياً بعد ذلك
    _save(base, data)
    return p


def batch_progress(data, uids=None):
    """التقدّم الإجمالي: {'done','total','percent','files':[(اسم، حالة، نسبة)]} — المنتهي = تم/فشل."""
    docs = [d for _, d in all_docs(data) if uids is None or d['uid'] in uids]
    files, fin, acc = [], 0, 0
    for d in docs:
        st = d['convert']['state']
        pct = 100 if st in ('done', 'failed') else int(d['convert'].get('progress') or 0) if st == 'running' else 0
        fin += st in ('done', 'failed')
        acc += pct
        files.append((d['orig_name'], st, pct))
    total = len(docs)
    return {'done': fin, 'total': total, 'percent': int(acc / total) if total else 0, 'files': files}


def resumable(data):
    """عملية توقفت (أُغلق البرنامج أثناءها): مستندات running/pending جاهزة للتحويل."""
    return any(d['convert']['state'] in ('running', 'pending') and d.get('file') and not d.get('needs_type')
               for _, d in all_docs(data))


# ---------- بيانات الحافظة من صفحتها الأولى بعد التحويل (2026-10-18) ----------
# طلب استخراج قصير لا يحتاج صياغة ← مزوّد رخيص (Groq ثم أي متوافق مع OpenAI) لا جيميناي، لتقليل استهلاكه.
# الكود يتحقق: المقدِّم صفة معروفة أو نص وارد حرفياً في الصفحة، والتاريخ وارد فيها؛ وإلا يبقى الاقتراح بالقواعد.
# لا يُلمس ما عدّله الخبير بيده (portfolio['auto_meta'] False).
CHEAP_SPEC = 'groq,openai'
_SIDES = ('المدعية', 'المدعي', 'المدعون', 'المدعى عليه', 'المدعى عليها', 'المدعى عليهم', 'المدعى عليه الأول',
          'المدعى عليه الثاني', 'المدعى عليه الثالث', 'المستأنف', 'المستأنفة', 'المستأنف ضده', 'المستأنف ضدها',
          'الخصم المدخل')


def clean_submitter(who):
    """الحوافظ تُقدَّم من الخصوم فقط (المدعي/المدعى عليه/خصم مدخل) — لا «حافظة الخبير» ولا «المكتب»."""
    who = ' '.join(str(who or '').split())
    if not who or any(w in who for w in ('الخبير', 'المكتب', 'الخبراء')):
        return ''
    return who


def portfolio_prompt(text):
    return ("هذه الصفحة الأولى من حافظة مستندات قُدّمت في دعوى أمام إدارة الخبراء. من قدّمها؟ وما تاريخ تقديمها؟\n"
            'أعد JSON فقط: {"submitter": "صفة المقدِّم (المدعية/المدعى عليه/المدعى عليها/المدعى عليه الثاني…) — الحافظة لا يقدّمها الخبير أبداً", '
            '"date": "dd/mm/yyyy", "evidence": "اقتباس حرفي من الصفحة يثبت ذلك"}. ما لم يرد اتركه فارغاً.\n\n'
            + (text or '')[:3500])


def _first_page(base, d):
    try:
        with open(os.path.join(base, d.get('md') or ''), encoding='utf-8') as f:
            t = f.read()
    except OSError:
        return ''
    parts = re.split(r'<!--\s*صفحة\s*2\s*-->', t, maxsplit=1)
    return re.sub(r'<!--.*?-->', ' ', parts[0], flags=re.S)


def verify_portfolio_meta(raw, text):
    """(المقدِّم، التاريخ yyyy-mm-dd) بعد التحقق من نص الصفحة، أو ('','')."""
    import json as _json
    import case_procedures as cp
    m = re.search(r'\{.*\}', raw or '', re.S)
    try:
        got = _json.loads(m.group(0)) if m else {}
    except ValueError:
        got = {}
    who = clean_submitter(got.get('submitter'))
    norm = cp.norm_ar(text)
    if who and not (who in _SIDES or (len(who) >= 3 and cp.norm_ar(who) in norm)):
        who = ''
    d = cp.minute_date([str(got.get('date') or '')])
    if d and not any(cp.minute_date([s]) == d for s in
                     re.findall(r'\d{1,4}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{1,4}', (text or '').translate(cp._DIGITS))):
        d = ''
    return who, d


def _cheap_ask(prompt):
    import case_research
    return case_research.default_ask(prompt, 'extract', spec=CHEAP_SPEC, timeout=60)


def refine_portfolio(base, data, pid, ask=None):
    """بعد تحويل أول مستند في حافظة اقتُرح مقدّمها/تاريخها آلياً: يقرأ صفحته الأولى بمزوّد رخيص ويضبطهما.
    يرجع (المقدِّم، التاريخ، رسالة). أي فشل (لا مزوّد/لا اتصال) ← يبقى الاقتراح بالقواعد بصمت."""
    p = _portfolio(data, pid)
    if not p.get('auto_meta'):
        return None
    first = next((d for d in sorted(p['docs'], key=lambda d: d['no'])
                  if (d.get('convert') or {}).get('state') == 'done' and d.get('md')), None)
    if first is None:
        return None
    text = _first_page(base, first)
    if not text.strip():
        return None
    try:
        raw = (ask or _cheap_ask)(portfolio_prompt(text))
    except Exception as e:
        return (p['submitter'], p.get('date', ''), f'تعذّر ضبط بيانات الحافظة بالذكاء ({e}) — بقي الاقتراح الأولي')
    who, d = verify_portfolio_meta(raw, text)
    if not who and not d:
        return (p['submitter'], p.get('date', ''), 'لم يتضح من الصفحة الأولى مقدّم الحافظة ولا تاريخها')
    if who:
        p['submitter'] = who
    if d:
        p['date'] = d
    p['auto_meta'] = 'ai'
    _save(base, data)
    return (p['submitter'], p.get('date', ''), f"ضُبطت الحافظة من صفحتها الأولى: {p['submitter']} بتاريخ {p.get('date') or '—'}")
