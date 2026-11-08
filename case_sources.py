# ===== case_sources.py — حفظ صحيفة الدعوى وحكم الإحالة محلياً وإعادة استعمالهما (2026-10-17) =====
# السبب (A2260637): الحكم كان يُحفظ في Desktop\judgments فقط ولا يُسجَّل في القضية، والصحيفة كانت تُجلب إلى ملف مؤقت يُحذف
# بعد القراءة فتُجلب وتُقرأ بالـOCR من جديد في كل مرة. الآن: كلاهما يُنسخ إلى مجلده في القضية (حكم_الإحالة\ أو صحيفة_الدعوى\ — case_folder)، ويُسجَّل في
# case.json['sources'][kind] = {file, text_file, fetched_at, engine, label, skipped, sha1, origin}. الاستعمال اللاحق يبحث
# محلياً أولاً ولا يطلب من النظام إلا إن غاب الملف أو طلب الخبير «تحديث من النظام» (refresh=True).
# نص الصحيفة المقروء يُحفظ بجانبها (.txt) فلا يُعاد OCR/Gemini ما دامت البصمة نفسها.
import hashlib
import json
import os
import shutil
from datetime import datetime

import case_workspace as cw

import case_layout as cl

SUB = cl.SOURCES_DIR                          # نصوص القراءة فقط (.txt)؛ الأصول في مستندات_النظام (case_folder)
FOLDERS = {'claim': cl.SYSDOCS, 'judgment': cl.SYSDOCS}
NAMES = {'claim': 'صحيفة الدعوى', 'judgment': 'حكم الإحالة'}
TEXT_NAMES = {'claim': 'صحيفة_الدعوى', 'judgment': 'حكم_الإحالة'}
LABELS = {'claim': 'صحيفة الدعوى', 'judgment': 'حكم الإحالة'}
JUDGMENTS_DIR = None            # الاختبارات تستبدله؛ الافتراضي Desktop\judgments


def judgments_dir():
    return JUDGMENTS_DIR or os.path.join(os.path.expanduser('~'), 'Desktop', 'judgments')


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def is_pdf(path):
    try:
        with open(path, 'rb') as f:
            return f.read(5) == b'%PDF-' and os.path.getsize(path) > 200
    except OSError:
        return False


def record(data, kind):
    return (data.get('sources') or {}).get(kind) or {}


def local_file(base, data, kind):
    """مسار الملف المحفوظ في مجلد القضية إن كان سليماً وبصمته مطابقة للمسجّلة، وإلا None."""
    rec = record(data, kind)
    if not rec.get('file'):
        return None
    path = os.path.join(base, rec['file'])
    if not is_pdf(path):
        return None
    if rec.get('sha1') and _sha1(path) != rec['sha1']:
        return None
    return path


def has_local(base, data, kind):
    return local_file(base, data, kind) is not None


def store(base, data, kind, src_path, info=None, origin='system', copy_to_judgments=None, caso_no=None, name=None):
    """ينسخ الملف إلى مجلد نوعه في القضية (حكم_الإحالة/صحيفة_الدعوى — case_folder) ويسجّله (تاريخ الجلب + المحرك).
    لا يستبدل أصلاً: المطابق بالبصمة يُعاد استعماله والاسم المكرر يأخذ « (2)». info: {'engine','label','skipped'}.
    copy_to_judgments: اسم الملف داخل Desktop\judgments (إن كان المجلد موجوداً)؛ لا يُنشأ المجلد. يرجع المسجّل."""
    import case_folder
    rel = case_folder.add_original(base, src_path, FOLDERS[kind], f"{name or NAMES[kind]}.pdf")
    dst = os.path.join(base, rel)
    rec = {'file': rel, 'fetched_at': _now(), 'sha1': _sha1(dst), 'origin': origin,
           'engine': (info or {}).get('engine', ''), 'label': (info or {}).get('label', ''),
           'skipped': (info or {}).get('skipped', []), 'text_file': ''}
    data.setdefault('sources', {})[kind] = rec
    if copy_to_judgments and os.path.isdir(judgments_dir()):
        try:
            target = os.path.join(judgments_dir(), copy_to_judgments)
            if os.path.abspath(target) != os.path.abspath(src_path):
                shutil.copy2(src_path, target)
        except OSError:
            pass
    return rec


# ---------- صحيفة الدعوى: مسار حفظ واحد بالمحتوى (2026-10-25) ----------
# النظام يولّد ملف PDF مختلف البايتات في كل تنزيل، فبصمة الملف (sha1) لا تكفي: كان كل تنزيل (الطابور الخلفي، مزامنة المجلد،
# الموضوع) يضيف «صحيفة الدعوى (2)» و«(3)». الآن الاعتبار برقم المستند في النظام (doc_id) ثم ببصمة المحتوى (نص الطبقة
# وصور الصفحات كما هي داخل الملف — content_key) لا بايتات الملف. نسخة ثانية تُحفظ فقط إن اختلف المحتوى فعلاً وتُسمّى
# «صحيفة الدعوى — معدّلة». النسخ الزائدة القديمة تُنقل إلى «مكررات» داخل القضية (لا تُحذف) — dedupe_claims.
CLAIM_NAME = 'صحيفة الدعوى'
AMENDED_NAME = 'صحيفة الدعوى — معدّلة'
DUP_DIR = 'مكررات'


def content_key(path):
    """بصمة محتوى PDF مستقلة عن بايتات الغلاف: نص كل صفحة (بلا مسافات زائدة) + بصمة بيانات كل صورة مضمَّنة كما هي.
    ملف بلا نص ولا صور (أو تعذّرت قراءته) ← بصمة الملف نفسه."""
    h = hashlib.sha1()
    n = 0
    try:
        import fitz
        with fitz.open(path) as d:
            for page in d:
                t = ' '.join((page.get_text() or '').split())
                h.update(t.encode('utf-8') + b'\x00')
                n += len(t)
                for img in page.get_images(full=True):
                    try:
                        raw = d.extract_image(img[0]).get('image') or b''
                    except Exception:
                        continue
                    h.update(hashlib.sha1(raw).digest())
                    n += 1
    except Exception:
        n = 0
    return h.hexdigest() if n else _sha1(path)


def claim_files(base):
    """[المسار النسبي] لكل صحيفة دعوى PDF في مستندات_النظام («صحيفة الدعوى»، «… (N)»، «… — معدّلة»)، الأصلية أولاً."""
    folder = os.path.join(base, FOLDERS['claim'])
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    out = [n for n in names if n.lower().endswith('.pdf') and os.path.splitext(n)[0].split(' (')[0].startswith(CLAIM_NAME)
           and is_pdf(os.path.join(folder, n))]
    out.sort(key=lambda n: (os.path.splitext(n)[0] != CLAIM_NAME, AMENDED_NAME in n, n))
    return [f'{FOLDERS["claim"]}/{n}' for n in out]


def _keys(base, rec):
    """{مسار نسبي: بصمة المحتوى} للصحف المحفوظة (مخزّنة في السجل فلا تُحسب كل مرة)."""
    cache = rec.setdefault('content_keys', {}) if rec is not None else {}
    out = {}
    for rel in claim_files(base):
        p = os.path.join(base, rel)
        tag = f'{os.path.getsize(p)}:{int(os.path.getmtime(p))}'
        hit = cache.get(rel)
        if not (isinstance(hit, list) and hit[0] == tag):
            hit = [tag, content_key(p)]
            cache[rel] = hit
        out[rel] = hit[1]
    return out


def find_claim(base, data):
    """مسار الصحيفة المحفوظة في القضية (المسجّلة، أو «صحيفة الدعوى» الموجودة في المجلد فتُسجَّل)، أو None — بلا أي تنزيل."""
    rec = record(data, 'claim')
    if rec.get('file') and is_pdf(os.path.join(base, rec['file'])):
        p = os.path.join(base, rec['file'])
        if rec.get('sha1') and _sha1(p) != rec['sha1']:          # استُبدل الملف في المجلد: نصه المحفوظ لم يعد له
            rec.update(sha1=_sha1(p), text_file='')
        return p
    files = claim_files(base)
    if not files:
        return None
    rel = files[0]
    p = os.path.join(base, rel)
    old = dict(rec)
    data.setdefault('sources', {})['claim'] = dict(old, file=rel, sha1=_sha1(p), origin=old.get('origin') or 'folder',
                                                   fetched_at=old.get('fetched_at') or _now(), text_file='')
    return p


def store_claim(base, data, src_path, doc_id='', origin='system', info=None):
    """المسار الواحد لحفظ صحيفة نُزّلت من النظام. يرجع (السجل، المسار النسبي الجديد أو '' إن لم يُحفظ شيء جديد).
    رقم المستند نفسه أو المحتوى نفسه ← لا نسخة جديدة؛ محتوى مختلف فعلاً ← «صحيفة الدعوى — معدّلة» (والأصلية تبقى المصدر)."""
    import case_folder
    doc_id = str(doc_id or '')
    rec = dict(record(data, 'claim'))
    ids = list(rec.get('doc_ids') or [])
    keys = _keys(base, rec)
    if doc_id and doc_id in ids and keys:
        return rec, ''
    key = content_key(src_path)
    same = next((rel for rel, k in keys.items() if k == key), None)
    if same is None and keys:
        name = AMENDED_NAME
    elif same is None:
        name = CLAIM_NAME
    else:
        name = None
    added = ''
    if name:
        added = case_folder.add_original(base, src_path, FOLDERS['claim'], f'{name}.pdf')
        p = os.path.join(base, added)
        rec.setdefault('content_keys', {})[added] = [f'{os.path.getsize(p)}:{int(os.path.getmtime(p))}', key]
        if name == CLAIM_NAME or not rec.get('file'):
            rec.update(file=added, fetched_at=_now(), sha1=_sha1(p), origin=origin, text_file='',
                       engine=(info or {}).get('engine', ''), label=(info or {}).get('label', ''),
                       skipped=(info or {}).get('skipped', []))
        else:
            rec.setdefault('amended', [])
            if added not in rec['amended']:
                rec['amended'].append(added)
    elif not rec.get('file'):
        p = os.path.join(base, same)
        rec.update(file=same, fetched_at=_now(), sha1=_sha1(p), origin=origin, text_file='')
    if doc_id and doc_id not in ids:
        ids.append(doc_id)
    rec['doc_ids'] = ids
    data.setdefault('sources', {})['claim'] = rec
    if doc_id:
        seen = data.setdefault('folder_fetch', {}).setdefault('doc_ids', [])
        if doc_id not in seen:
            seen.append(doc_id)
    return rec, added


SAME_TEXT_RATIO = 0.9


def _md_body(base, man, rel):
    import re
    import case_folder as cf
    import doc_header
    e = man['files'].get(rel) or {}
    if e.get('state') != 'done':
        return ''
    try:
        with open(os.path.join(base, e.get('md') or cf.md_rel(rel)), encoding='utf-8') as f:
            text = doc_header.strip(f.read())
    except OSError:
        return ''
    return ' '.join(re.sub(r'<!--.*?-->', ' ', text, flags=re.S).split())


def _same_text(base, man, a, b):
    """بصمة النص المحوَّل: نصّا markdown للملفين متطابقان تقريباً (قراءة النسخة نفسها مرتين) ← النسخة نفسها."""
    import difflib
    ta, tb = _md_body(base, man, a), _md_body(base, man, b)
    if not ta or not tb:
        return False
    return ta == tb or difflib.SequenceMatcher(None, ta[:8000], tb[:8000]).ratio() >= SAME_TEXT_RATIO


def dedupe_claims(base, data):
    """«صحيفة الدعوى (2)» و«(3)»… بمحتوى الأصلية نفسه ← تُنقل إلى «مكررات» داخل القضية (لا حذف) مع مشتقها في markdown،
    وتُرفع من manifest. ما اختلف محتواه فعلاً يبقى (يُسمّى «— معدّلة» إن لم توجد). يرجع [(من، إلى)]."""
    import case_folder as cf
    import case_layout as cl
    files = claim_files(base)
    if len(files) < 2:
        return []
    rec = data.setdefault('sources', {}).setdefault('claim', {})
    keys = _keys(base, rec)
    man = cf.load_manifest(base)
    main = files[0]
    moved, seen = [], {keys.get(main): main}
    for rel in files[1:]:
        k = keys.get(rel)
        stem = os.path.splitext(os.path.basename(rel))[0]
        twin = next((r for r in seen.values() if _same_text(base, man, r, rel)), None)
        if k not in seen and twin:
            k = next(kk for kk, r in seen.items() if r == twin)          # نص محوَّل نفسه (بايتات الصور اختلفت)
        if k in seen:
            dst_dir = os.path.join(base, DUP_DIR)
            os.makedirs(dst_dir, exist_ok=True)
            got = cl.safe_move(os.path.join(base, rel), os.path.join(dst_dir, os.path.basename(rel)))
            e = man['files'].pop(rel, None)
            md = (e or {}).get('md') or cf.md_rel(rel)
            if os.path.isfile(os.path.join(base, md)):
                cl.safe_move(os.path.join(base, md), os.path.join(dst_dir, os.path.basename(md)))
            to = os.path.relpath(got, base).replace('\\', '/')
            moved.append((rel, to))
            (rec.get('content_keys') or {}).pop(rel, None)
            if rec.get('file') == rel:
                rec['file'] = seen[k]
        elif ' (' in stem and AMENDED_NAME not in stem and not any(AMENDED_NAME in f for f in files):
            new = cl.relocate(base, data, rel, f"{FOLDERS['claim']}/{AMENDED_NAME}.pdf", man)
            rec = data.setdefault('sources', {}).setdefault('claim', {})     # relocate يعيد بناء data بالمسارات الجديدة
            moved.append((rel, new))
            seen[k] = new
        else:
            seen[k] = rel
    if moved:
        cf.save_manifest(base, man)
        rec['deduped_at'] = _now()
    return moved


def save_text(base, data, kind, text, info=None):
    """يحفظ نص القراءة بجانب الملف ويحدّث محرّكه في السجل."""
    rec = record(data, kind)
    if not rec:
        return
    rel = f"{SUB}/{TEXT_NAMES[kind]}.txt".replace('\\', '/')
    os.makedirs(os.path.join(base, SUB), exist_ok=True)
    with open(os.path.join(base, rel), 'w', encoding='utf-8') as f:
        f.write(text or '')
    rec['text_file'] = rel
    rec['text_sha1'] = rec.get('sha1', '')
    if info:
        rec.update(engine=info.get('engine', ''), label=info.get('label', ''), skipped=info.get('skipped', []))


def load_text(base, data, kind):
    """(نص، info) محفوظان لنسخة الملف الحالية، أو None."""
    rec = record(data, kind)
    if not rec.get('text_file') or not local_file(base, data, kind):
        return None
    if rec.get('text_sha1') != rec.get('sha1'):
        return None
    try:
        with open(os.path.join(base, rec['text_file']), encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return None
    if not text.strip():
        return None
    return text, {'engine': rec.get('engine', ''), 'label': rec.get('label', ''), 'skipped': rec.get('skipped', [])}


def adopt_judgment(base, data):
    """يتبنّى حكماً محفوظاً مسبقاً في Desktop\\judgments (كان يُحفظ هناك دون ربطه بالقضية). يرجع True إن سجّل شيئاً."""
    if local_file(base, data, 'judgment'):
        return False
    caso = (data.get('caso_no') or '').strip().upper()
    for name in (f'{caso}.pdf', f'{caso}_MAIN1.pdf'):
        path = os.path.join(judgments_dir(), name)
        if is_pdf(path):
            engine = {}
            try:
                import case_db
                raw = (case_db.get_case(caso) or {}).get('judgment_engine')
                engine = json.loads(raw) if raw else {}
            except Exception:
                engine = {}
            rec = store(base, data, 'judgment', path, engine, origin='adopted')
            rec['fetched_at'] = datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M:%S')
            cw.write_case_json(base, data)
            return True
    return False


def refresh_judgment(base, data, cookies, user_id='309'):
    """«تحديث من النظام»: يجلب الحكم من جديد (تجاهل المحلي) ويسجّله. يرفع استثناء عند فشل الشبكة. يرجع المسار أو None."""
    from documents import get_referral_judgment_for_case
    import tempfile
    tmp = tempfile.mkdtemp(prefix='judg_')
    save = os.path.join(tmp, f"{data['caso_no']}.pdf")
    row, path = get_referral_judgment_for_case(cookies, data.get('autocase_no') or '', user_id, save, use_local=False)
    if not path:
        return None
    rec = store(base, data, 'judgment', path, None, origin='system')
    shutil.rmtree(tmp, ignore_errors=True)
    cw.write_case_json(base, data)
    return os.path.join(base, rec['file'])


def referral_markdown(case, pdf_path, convert=None):
    """«تفاصيل القضية» (2026-10-23): حكم الإحالة كاملاً (بلا حد الصفحات) ← markdown مرة واحدة ← يُحفظ في مجلد القضية باسم
    «حكم خبير» وأول سطر فيه REFERRAL_MARK (يتعرف عليه referral_pick بالكود)، ويُسجَّل في manifest وcase_sources فلا يعيد
    تحويلَه فتحُ القضية ولا كتابة التقرير. التحويل: طبقة النص إن سلمت وإلا المحرّك «best» (Gemini بمهمة ocr: Flash Lite).
    يرجع (النص، المحرّك) أو ('', '') عند التعذّر (بلا مجلد قضية)."""
    import case_folder as cf
    try:
        base, data = cw.ensure_workspace(case)
    except Exception:
        return '', ''
    rec = store(base, data, 'judgment', pdf_path, origin='system', name=cf.EXPERT_JUDGMENT)
    got = load_text(base, data, 'judgment')
    import doc_header
    if got and doc_header.strip(got[0]).lstrip().startswith(cf.REFERRAL_MARK):
        return got[0], got[1].get('engine', '')
    rel = rec['file']
    convert = convert or cf.CONVERTER or cf._default_convert
    text, _pages, engine = convert(os.path.join(base, rel), cf.JUDGMENT)[:3]
    if not (text or '').strip():
        return '', ''
    md = f'{cf.REFERRAL_MARK}\n\n{text}'
    cf._write_md(base, cf.md_rel(rel), md)
    cf.record_converted(base, rel, cf.md_rel(rel))
    save_text(base, data, 'judgment', md, {'engine': engine, 'label': engine, 'skipped': []})
    cw.write_case_json(base, data)
    return md, engine
