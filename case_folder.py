# ===== case_folder.py — «مجلد القضية» هو الأصل الوحيد للمستندات (2026-10-18، البنية المختصرة 2026-10-21) =====
# البنية (case_layout): مستندات_النظام/ حوافظ/ مذكرات/ أخرى/ ← الأصول؛ markdown/ ← نسخة مشتقة بنفس البنية والأسماء
# (.md، لا تُعدَّل يدوياً)؛ _نظام/ (مخفي) فيه manifest.json وcase.json والسجلات.
# نوع المستند (kind_of) من مجلده واسمه: في مستندات_النظام «حكم…»/«صحيفة…»/«محضر…»/«تقرير…»؛ حوافظ ← حافظة؛ مذكرات ← مذكرة.
# قواعد الأمان: لا حذف ولا استبدال لأي أصل (الاسم المكرر يأخذ « (2)»)، manifest يُكتب ذرّياً، الملفات المؤقتة تُتجاهل.
# sync_case_folder: يقارن (المسار النسبي + الحجم + sha1) مع manifest، يحوّل الجديد/المتغيّر فقط (مع حارس الحلقة
# loop_guard: إعادة بدفعات أصغر مرتين ثم «تعذّر التحويل»)، ويبلّغ عن الأصل المحذوف دون حذف مشتقه.
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime

import case_convert
import case_layout as cl
import doc_router

SYSDOCS, PORTF, MEMOS, OTHER = cl.SYSDOCS, cl.PORTF, cl.MEMOS, cl.OTHER
FOLDERS = cl.ORIG_FOLDERS
FOLDER_LABELS = {SYSDOCS: 'مستندات النظام', PORTF: 'الحوافظ', MEMOS: 'المذكرات', OTHER: 'أخرى'}
# أنواع المستندات (معرّفات ثابتة؛ قيمها أسماء المجلدات القديمة للتوافق مع ما حُفظ سابقاً)
MINUTES, JUDGMENT, PLAINT, PRIOR = cl.OLD_MINUTES, cl.OLD_JUDGMENT, cl.OLD_PLAINT, cl.OLD_PRIOR
PORTFOLIO, DEFENSE = 'حافظة', 'مذكرة'
KIND_LABELS = {MINUTES: 'محضر خبرة', JUDGMENT: 'حكم', PLAINT: 'صحيفة دعوى', PRIOR: 'تقرير خبرة سابق',
               PORTFOLIO: 'حافظة مستندات', DEFENSE: 'مذكرة دفاع', OTHER: 'غير مصنَّف'}
MD_DIR = cl.MD_DIR
LOG_REL = cl.MIGRATION_LOG
SUPPORTED = case_convert.SUPPORTED
_TEMP_SUFFIX = ('.tmp', '.part', '.crdownload', '.partial', '.bak')
_TEMP_NAMES = {'thumbs.db', 'desktop.ini', '.ds_store'}

TYPE_FOLDER = {doc_router.T_MINUTES: SYSDOCS, doc_router.T_JUDGMENT: SYSDOCS, doc_router.T_PLAINT: SYSDOCS,
               doc_router.T_PORTFOLIO: PORTF, doc_router.T_DEFENSE: MEMOS}
FOLDER_TYPE = {MINUTES: doc_router.T_MINUTES, JUDGMENT: doc_router.T_JUDGMENT, PLAINT: doc_router.T_PLAINT,
               PORTFOLIO: doc_router.T_PORTFOLIO, DEFENSE: doc_router.T_DEFENSE}
KIND_OF_TYPE = {doc_router.T_MINUTES: MINUTES, doc_router.T_JUDGMENT: JUDGMENT, doc_router.T_PLAINT: PLAINT,
                doc_router.T_PORTFOLIO: PORTFOLIO, doc_router.T_DEFENSE: DEFENSE}

# المحوّل: fn(path, kind) -> (markdown, صفحات[, محرّك])؛ تستبدله الاختبارات. المصنِّف: fn(path) -> {'type',...}.
CONVERTER = None
CLASSIFIER = None


def kind_of(rel):
    """نوع الأصل من مساره النسبي: MINUTES/JUDGMENT/PLAINT/PRIOR/PORTFOLIO/DEFENSE/OTHER (والقديم بمجلده)."""
    parts = (rel or '').replace('\\', '/').split('/')
    top, name = parts[0], parts[-1]
    if top in (MINUTES, JUDGMENT, PLAINT, PRIOR):                     # بنية 2026-10-18 (قبل الترحيل)
        return top
    if top == PORTF:
        return PORTFOLIO
    if top == MEMOS:
        return DEFENSE
    if top == SYSDOCS:
        for word, k in (('محضر', MINUTES), ('صحيفة', PLAINT), ('صحيفه', PLAINT), ('حكم', JUDGMENT), ('تقرير', PRIOR)):
            if name.startswith(word):
                return k
    return OTHER


EXPERT_JUDGMENT = 'حكم خبير'           # حكم الإحالة المسحوب كاملاً من «تفاصيل القضية» (case_sources.referral_markdown)
REFERRAL_MARK = 'حكم خبير (حكم الإحالة)'   # أول سطر في markdown هذا الحكم: يتعرف عليه الفرز بالكود (referral_pick) بلا ذكاء


def is_referral_name(rel):
    return os.path.splitext(os.path.basename(rel or ''))[0].split(' (')[0] in ('حكم الإحالة', EXPERT_JUDGMENT)


SYSTEM_NAMES = {JUDGMENT: 'حكم الإحالة', PLAINT: 'صحيفة الدعوى'}


def minute_name(no):
    return f'محضر الخبرة رقم {int(no)}'


def safe_name(text):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text or '').strip().rstrip('.') or 'مستند'


def _now():
    return datetime.now().isoformat(timespec='seconds')


def folder_for_type(doc_type):
    return TYPE_FOLDER.get(doc_type)


# ---------- البنية ----------

def ensure_structure(base):
    cl.ensure(base)


class NeedsFolder(Exception):
    """نوع الملف غير معروف: الواجهة تسأل الخبير عن المجلد."""


def is_ignored(name):
    """ملف مؤقت/نظامي لا يُعدّ أصلاً (لا يدخل العدّ)."""
    n = name.lower()
    # ملفات markdown مشتقة دائماً (markdown/ والملخص.md وذاكرة القضية): لا تُعدّ أصلاً ولا تُعرض ولا تُفرز ولا تُزامَن
    return (n.startswith('~$') or n.startswith('.') or n in _TEMP_NAMES or n.endswith(_TEMP_SUFFIX)
            or n.endswith('.md'))


def is_temp(name):
    """لا يُحوَّل: مؤقت أو بصيغة غير مدعومة (غير المدعوم يظهر في فحص العدد بسببه)."""
    return is_ignored(name) or os.path.splitext(name.lower())[1] not in SUPPORTED


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def md_rel(rel):
    """المشتق لأصل: markdown/<نفس المسار>.md (الأصل .md يبقى بالاسم نفسه)."""
    return f"{MD_DIR}/{os.path.splitext(rel)[0]}.md"


MAX_PATH = 250          # حد Windows (260) مع هامش « (N)» والمشتق .md داخل markdown/


def _fit(folder, name):
    """يقصّر الاسم الطويل (العربي غالباً) حتى يبقى المسار والمشتق تحت حد Windows."""
    stem, ext = os.path.splitext(name)
    room = MAX_PATH - len(os.path.join(folder, '')) - len(ext) - len(MD_DIR) - 8
    return (stem[:max(8, room)].rstrip() + ext) if len(stem) > room else name


def _unique(folder, name):
    name = _fit(folder, name)
    dst = os.path.join(folder, name)
    stem, ext = os.path.splitext(name)
    i = 2
    while os.path.exists(dst):
        dst = os.path.join(folder, f'{stem} ({i}){ext}')
        i += 1
    return dst


def _same_in(folder, sha):
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for n in names:
        p = os.path.join(folder, n)
        if os.path.isfile(p) and not is_temp(n):
            try:
                if sha1(p) == sha:
                    return p
            except OSError:
                continue
    return None


def classify(path):
    """المجلد المقترح لملف بحسب نوعه (doc_router)، أو None إن لم يُعرف."""
    fn = CLASSIFIER
    try:
        if fn is None:
            ext = os.path.splitext(path)[1].lower()
            fn = doc_router.classify_text_file if ext in doc_router.TEXT_EXTS else doc_router.classify_file
        return folder_for_type((fn(path) or {}).get('type'))
    except Exception:
        return None


def _kind_target(folder, src, name):
    """يقبل نوعاً بدل المجلد (JUDGMENT/PLAINT/MINUTES/PRIOR/PORTFOLIO/DEFENSE): المجلد + الاسم المعتمد للنوع."""
    ext = os.path.splitext(src)[1]
    stem = os.path.splitext(name or os.path.basename(src))[0]
    if folder in SYSTEM_NAMES:
        return SYSDOCS, name if name and kind_of(f'{SYSDOCS}/{name}') == folder else SYSTEM_NAMES[folder] + ext
    if folder == MINUTES:
        return SYSDOCS, name if name and kind_of(f'{SYSDOCS}/{name}') == MINUTES else minute_file_name(src, stem)
    if folder == PRIOR:
        return SYSDOCS, name if name and name.startswith('تقرير') else f'تقرير خبرة سابق - {stem}{ext}'
    if folder == PORTFOLIO:
        return PORTF, name
    if folder == DEFENSE:
        return MEMOS, name
    return folder, name


def add_original(base, src, folder=None, name=None):
    """ينسخ ملفاً إلى مجلده في القضية ويرجع المسار النسبي. لا يستبدل شيئاً: المطابق بالبصمة في المجلد نفسه
    يُعاد مساره، والاسم المكرر يأخذ « (2)». folder=None ← «أخرى» (الفرز الآلي case_sort يسمّيه وينقله بعد تحويله)."""
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    folder, name = _kind_target(folder or OTHER, src, name)
    if folder not in FOLDERS:
        raise NeedsFolder(os.path.basename(src))
    ensure_structure(base)
    target = os.path.join(base, folder)
    sha = sha1(src)
    hit = _same_in(target, sha)
    if hit is None:
        if os.path.normcase(os.path.abspath(os.path.dirname(src))) == os.path.normcase(os.path.abspath(target)):
            hit = src
        else:
            hit = _unique(target, name or os.path.basename(src))
            tmp = hit + '.part'
            shutil.copy(src, tmp)          # وقت التعديل = وقت الإضافة (الأحدث يُعرف به)
            os.replace(tmp, hit)
    return os.path.relpath(hit, base).replace('\\', '/')


# ---------- manifest ----------

def manifest_path(base):
    return cl.sys_path(base, cl.MANIFEST)


def load_manifest(base):
    try:
        with open(manifest_path(base), encoding='utf-8') as f:
            m = json.load(f)
        if isinstance(m, dict) and isinstance(m.get('files'), dict):
            return m
    except (OSError, ValueError):
        pass
    return {'version': 1, 'files': {}}


def save_manifest(base, m):
    path = manifest_path(base)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    m['updated_at'] = _now()
    fd, tmp = tempfile.mkstemp(prefix='manifest.', suffix='.tmp', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def record_converted(base, rel, md, origin='converted'):
    """تسجيل تحويل تم خارج sync (case_documents مثلاً) فلا يُعاد تحويله."""
    m = load_manifest(base)
    p = os.path.join(base, rel)
    st = os.stat(p)
    m['files'][rel] = {'size': st.st_size, 'mtime': int(st.st_mtime), 'sha1': sha1(p), 'md': md,
                       'state': 'done', 'message': '', 'origin': origin, 'at': _now()}
    save_manifest(base, m)


def scan(base, old=None, hydrate=True):
    """{المسار النسبي: {size, mtime, sha1}} لكل الأصول. يعيد استعمال sha1 من old إن طابق الحجم والوقت.
    ملف OneDrive غير منزَّل (cloud_files): hydrate=True (الخيط الخلفي) ← يُنزَّل أولاً برسالة؛ hydrate=False (خيط الواجهة)
    ← لا يُقرأ أبداً: بصمته السابقة إن وُجدت وإلا '' مع cloud=True (يظهر «بانتظار» حتى تنزّله المزامنة)."""
    import cloud_files
    old = old or {}
    out = {}
    for folder in FOLDERS:
        root = os.path.join(base, folder)
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for n in files:
                if is_temp(n):
                    continue
                p = os.path.join(dirpath, n)
                rel = os.path.relpath(p, base).replace('\\', '/')
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                prev = old.get(rel) or {}
                if prev.get('size') == st.st_size and prev.get('mtime') == int(st.st_mtime) and prev.get('sha1'):
                    h = prev['sha1']
                elif cloud_files.is_cloud(p) and not hydrate:
                    out[rel] = {'size': st.st_size, 'mtime': int(st.st_mtime), 'sha1': prev.get('sha1') or '',
                                'cloud': True}
                    continue
                else:
                    if not cloud_files.ensure_local(p, doc_router._hook if doc_router.STATUS_HOOK else None):
                        continue                      # تعذّر تنزيله من OneDrive: يُتخطى هذه المرة بلا تعليق
                    try:
                        h = sha1(p)
                    except OSError:
                        continue
                out[rel] = {'size': st.st_size, 'mtime': int(st.st_mtime), 'sha1': h}
    return out


# ---------- التحويل ----------

def unsupported(base):
    """[(المسار النسبي، السبب)] لملفات الأصول بصيغة لا يحوّلها البرنامج (تدخل العدّ ولا تُحوَّل)."""
    out = []
    for folder in FOLDERS:
        for dirpath, dirs, files in os.walk(os.path.join(base, folder)):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for n in files:
                if not is_ignored(n) and os.path.splitext(n.lower())[1] not in SUPPORTED:
                    rel = os.path.relpath(os.path.join(dirpath, n), base).replace('\\', '/')
                    out.append((rel, f'صيغة غير مدعومة ({os.path.splitext(n)[1] or "بلا امتداد"})'))
    return sorted(out)


def legacy_convert(path, folder):
    """المسار القائم للممسوح والصور: محرّك نوع المجلد (جيميناي/OCR خارجي/محلي) مع إفصاح المحرّك والتحذير."""
    import case_documents as cd
    doc = {'doc_type': FOLDER_TYPE.get(folder, doc_router.T_PORTFOLIO)}
    engine = doc_router.engine_for(doc['doc_type']) or doc_router.ENGINE_LOCAL
    if engine == getattr(doc_router, 'ENGINE_BEST', None):
        engine = doc_router.best_engine()
    fn = cd.ENGINES.get(engine) or cd.ENGINES.get(doc_router.ENGINE_LOCAL)
    text, pages, warning = fn(path, doc)
    used = doc.get('engine_used') or engine
    return (f'<!-- ⚠ {warning} -->\n{text}' if warning else text), pages, used


def _default_convert(path, folder):
    """docx/doc/rtf/odt/xlsx/csv/txt/md مباشرة، وPDF بطبقة نصه السليمة، وإلا legacy_convert (case_convert)."""
    return case_convert.convert(path, folder)


RETRY_BATCHES = (5, 2)        # بعد الحلقة: إعادة من البداية بدفعات صفحات أصغر — محاولتان فقط
STALL_SECONDS = 600           # مهلة بلا أي تقدّم (صفحات) ← يُترك الطلب ويُعدّ محاولة فاشلة
LOOP_FAIL = 'تعذّر التحويل'


class ConversionLoop(Exception):
    """فشل التحويل بعد المحاولات: حلقة تكرار أو مهلة بلا تقدّم. الناتج لا يُحفظ."""


def _with_watchdog(fn, batch, stall):
    """يشغّل fn في الخيط نفسه (سياق الإلغاء والسجل والمستند الجاري thread-local) ويراقب التقدّم: المحرّكات تفحص المهلة
    بين الدفعات (doc_router.check_stall)، وفجوة بلا تقدّم أطول من stall عند الانتهاء ← ConversionLoop (النتيجة تُهمل)."""
    import time
    import loop_guard
    doc_router.start_watch(stall)
    doc_router.set_batch_override(batch)
    try:
        out = fn()
    except doc_router.Stalled as e:
        raise ConversionLoop(str(e))
    finally:
        gap = doc_router.stop_watch()
        doc_router.set_batch_override(0)
    if gap > stall:
        raise ConversionLoop(f'مهلة طويلة بلا تقدّم ({int(gap)} ثانية)')
    return out


def is_key_failure(e):
    """فشل المفتاح الشخصي (ai_providers.PersonalKeyFailure): يوقف المهمة ويعرض الخيارات — لا إعادة ولا «فاشل»."""
    try:
        import ai_providers
        return isinstance(e, ai_providers.PersonalKeyFailure)
    except Exception:
        return False


def convert_guarded(convert, path, kind, stall=None, on_retry=None):
    """التحويل مع حارس الحلقة: يُفحص الناتج (loop_guard)؛ عند الحلقة أو المهلة يُعاد من البداية بدفعات أصغر
    (RETRY_BATCHES، محاولتان) ثم ConversionLoop «تعذّر التحويل». يرجع (نص، صفحات، محرّك، عدد_الإعادات)."""
    import loop_guard
    why = ''
    for attempt, batch in enumerate((0,) + tuple(RETRY_BATCHES)):
        if attempt and on_retry:
            on_retry(attempt, why)
        try:
            got = _with_watchdog(lambda: convert(path, kind), batch, stall or STALL_SECONDS)
        except (loop_guard.LoopDetected, ConversionLoop) as e:
            why = str(e)
            continue
        text, pages = got[0], got[1]
        found = loop_guard.detect(text, pages)
        if not found:
            return text, pages, (got[2] if len(got) > 2 else ''), attempt
        why = found
    raise ConversionLoop(f'{LOOP_FAIL}: {why} — أُعيد التحويل {len(RETRY_BATCHES)} مرتين بدفعات أصغر دون جدوى')


def _write_md(base, rel, text):
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.md.', suffix='.tmp', dir=os.path.dirname(path))
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    os.replace(tmp, path)


def _stale(base, entry, f):
    """يحتاج تحويلاً: جديد، أو تغيّرت بصمته، أو لم ينجح تحويله، أو غاب مشتقه."""
    if not entry or entry.get('sha1') != f['sha1'] or entry.get('state') != 'done':
        return True
    return not os.path.exists(os.path.join(base, entry.get('md') or ''))


_MD_PAGE = re.compile(r'<!--\s*صفحة\s*(\d+)\s*-->')
_MD_COMMENT = re.compile(r'<!--.*?-->', re.S)
_MD_BAD_WARN = ('لا يطابق الفعلي', 'بقيت فارغة', 'النص مدموج')     # تحذيرات التحويل الجزئي (doc_router.split_pages)
MIN_CHARS_PER_PAGE = 20             # نسخة بلا علامات صفحات (برنامج آخر): أقل من هذا لكل صفحة PDF = ناقصة
MAX_EMPTY_PAGES_RATIO = 0.25        # صفحات فارغة أكثر من الربع = قراءة ناقصة (الصفحة الفاصلة البيضاء مقبولة)


def md_complete(base, rel, md):
    """(مكتملة؟، السبب). فحص بالكود بلا أي طلب: نص غير فارغ، لا تحذير تحويل جزئي، لا حلقة تكرار، ولأصل PDF: كل
    صفحاته لها علامة <!-- صفحة N --> وأغلبها فيه نص (أو طول معقول لنسخة بلا علامات)."""
    try:
        with open(os.path.join(base, md), encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return False, 'لا توجد نسخة markdown'
    if not _MD_COMMENT.sub('', text).strip():
        return False, 'نسخة markdown فارغة'
    for c in _MD_COMMENT.findall(text):
        if '⚠' in c and any(w in c for w in _MD_BAD_WARN):
            return False, 'النسخة فيها صفحات ناقصة أو مدموجة'
    n = 0
    if rel.lower().endswith('.pdf'):
        try:
            n = doc_router.page_count(os.path.join(base, rel))
        except Exception:
            n = 0                                    # تعذّر عدّ صفحات الأصل: يكفي بقية الفحص
    try:
        import loop_guard
        loop = loop_guard.detect(text, n)
    except Exception:
        loop = None
    if loop:
        return False, f'النسخة فيها تكرار ({loop})'
    if not n:
        return True, ''
    marks = list(_MD_PAGE.finditer(text))
    if not marks:
        if len(_MD_COMMENT.sub('', text).strip()) < MIN_CHARS_PER_PAGE * n:
            return False, f'النص قصير جداً لـ{n} صفحة'
        return True, ''
    pages = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        k = int(m.group(1))
        pages[k] = pages.get(k, '') + _MD_COMMENT.sub('', text[m.end():end]).strip()
    missing = [k for k in range(1, n + 1) if k not in pages]
    if missing:
        return False, f'ناقصة {len(missing)} من {n} صفحة'
    empty = sum(1 for k in range(1, n + 1) if not pages[k])
    if empty > max(1, int(n * MAX_EMPTY_PAGES_RATIO)):
        return False, f'{empty} من {n} صفحة بلا نص'
    return True, ''


def adopt_existing(base, known, files, busy=(), rejected=None):
    """نسخة markdown/<الأصل>.md موجودة ومكتملة (md_complete) ولا سجل نافذاً لها (مُسح manifest/الكاش، أو حُوِّلت
    ببرنامج آخر) ← تُعتمد كما هي بلا تحويل؛ الناقصة تبقى للتحويل (وتُضاف إلى rejected إن أُعطيت: [(rel, السبب)]).
    الأصل الذي تغيّرت بصمته عن سجله يبقى للتحويل (نسخته قديمة). يرجع المعتمَدة."""
    out = []
    for rel, f in files.items():
        entry = known.get(rel)
        if rel in busy or f.get('cloud') or not _stale(base, entry, f):
            continue
        if entry and entry.get('sha1') and entry['sha1'] != f['sha1']:
            continue
        md = md_rel(rel)
        if not os.path.exists(os.path.join(base, md)):
            continue
        ok, why = md_complete(base, rel, md)
        if ok:
            known[rel] = dict(f, md=md, state='done', message='', origin='existing_md', at=_now())
            out.append(rel)
        elif rejected is not None:
            rejected.append((rel, why))
    return out


def sync_case_folder(base, data=None, convert=None, stop=None, on_file=None):
    """يزامن markdown مع الأصول. يرجع {converted, failed:[(rel,سبب)], missing, total, message}.
    data (اختياري): يُسجَّل فيه data['folder_sync'] (المستدعي يحفظ case.json)."""
    ensure_structure(base)
    convert = convert or CONVERTER or _default_convert
    man = load_manifest(base)
    known = man['files']
    for rel in [r for r in known if r.lower().endswith('.md')]:     # سُجّل قديماً أصلاً؛ markdown ليس أصلاً
        known.pop(rel)
    files = scan(base, known)
    busy ={d.get('file') for p in (data or {}).get('portfolios') or [] for d in p.get('docs') or []
            if (d.get('convert') or {}).get('state') in ('pending', 'running')}     # خط المستندات يحوّلها هو
    adopted = adopt_existing(base, known, files, busy)        # المحوَّل سابقاً (markdown موجود) لا يُعاد تحويله
    todo = [rel for rel, f in sorted(files.items())
            if rel not in busy and _stale(base, known.get(rel), f)]
    converted, failed = [], []
    for rel in todo:
        if stop and stop():
            break
        f, md = files[rel], md_rel(rel)
        entry = dict(f, md=md, at=_now(), origin='converted')
        if on_file:
            on_file(rel, len(converted) + len(failed), len(todo))
        try:
            import case_triage
            doc_router.set_triage(case_triage.parties_text(data), base)     # الفرز مدمج في طلب تحويل جيميناي
            try:
                text, pages, engine, retries = convert_guarded(convert, os.path.join(base, rel), kind_of(rel))
                blocks = doc_router.take_triage()
            finally:
                doc_router.set_triage(None)
            if not (text or '').strip():
                raise ValueError('لم يُستخرج نص')
            _write_md(base, md, text)
            entry.update(state='done', message='', pages=pages, engine=engine, retries=retries)
            case_triage.stash_conversion(entry, blocks, pages)
            converted.append(rel)
        except ConversionLoop as e:                 # لا يُحفظ ناتج فيه حلقة؛ أحمر «تعذّر التحويل» + زر إعادة
            entry.update(state='failed', loop=True, message=str(e))
            failed.append((rel, entry['message']))
        except Exception as e:
            if is_key_failure(e):                   # مفتاحك الشخصي فشل: تتوقف المهمة كلها (لا يُعلَّم الملف فاشلاً)
                if todo or not os.path.exists(manifest_path(base)):
                    save_manifest(base, man)
                raise
            entry.update(state='failed', message=str(e) or e.__class__.__name__)
            failed.append((rel, entry['message']))
        known[rel] = entry
    missing = sorted(rel for rel in known if rel not in files)
    for rel in missing:
        known[rel]['state'] = 'missing'
    if todo or missing or adopted or not os.path.exists(manifest_path(base)):
        save_manifest(base, man)
    res = {'converted': converted, 'failed': failed, 'missing': missing, 'total': len(files),
           'message': summary_line(converted, failed, missing), 'at': _now(),
           'count': count_check(base, files, known, busy)}
    try:                                       # الفهرس مشتق: فشله لا يُفشل المزامنة
        import case_index
        case_index.write_index(base, data)
    except Exception as e:
        res['message'] += f' — تعذّر بناء فهرس المستندات: {e}'
    if data is not None:
        data['folder_sync'] = {k: res[k] for k in ('message', 'at', 'total', 'count')} | {
            'converted': len(converted), 'failed': [list(x) for x in failed], 'missing': missing}
        documents_step(data, res['count'])
    return res


def documents_step(data, count):
    """مسار المجلد (بلا حوافظ النافذة القديمة): خطوة «المستندات» تتبع عدّ التحويل — كل الأصول محوَّلة ← مكتملة، وإلا
    «بانتظار». قبلها لم يكن شيء يكملها في هذا المسار فيُحجب «البحث ورأي الخبرة» رغم أن الملفات كلها محوَّلة (A2263970)."""
    import case_model as cm
    if data.get('portfolios'):
        return                                       # النافذة القديمة تدير الخطوة (case_documents._refresh_step)
    st = cm.state(data, 'documents')
    if st == 'running':
        return
    n = count.get('originals') or 0
    if count.get('ok') and n:
        if st not in cm.OK_STATES:
            if st != 'needs_input':
                cm.set_step(data, 'documents', 'needs_input')
            cm.set_step(data, 'documents', 'done', f'{n} مستنداً محوَّلاً')
    else:
        left = len(count.get('unconverted') or [])
        msg = f'{left} من {n} لم يُحوَّل بعد' if n else 'لا مستندات في مجلد القضية'
        if st != 'needs_input' or cm._step(data, 'documents').get('message') != msg:
            cm.set_step(data, 'documents', 'needs_input', msg)


# ---------- قائمة المستندات في صفحة القضية: الأصول فقط ----------

_TYPE_TITLE = {'حافظة': 'حافظة مستندات', 'مذكرة': 'مذكرة دفاع', 'محضر': 'محضر خبرة', 'حكم': 'حكم',
               'صحيفة': 'صحيفة دعوى', 'تقرير': 'تقرير خبرة سابق', 'أخرى': 'غير مصنَّف'}
WEAK_ENGINES = ('external_ocr', 'local', 'cloud_vision')     # قراءة OCR قد تخطئ في الأرقام ← تنبيه للخبير


def doc_rows(base, data=None):
    """صف لكل أصل في المجلدات الأربعة (لا markdown ولا _نظام ولا الملخص.md): {rel, name, folder, kind, side, date,
    state (done|failed|pending|running), message, engine, pages, size, alert, question}. الترتيب: مستندات النظام ثم
    الحوافظ والمذكرات بتاريخها ثم أخرى."""
    man = load_manifest(base)['files']
    files = scan(base, man, hydrate=False)              # تُعرض من خيط الواجهة: لا قراءة لملف OneDrive غير منزَّل
    qs = dict(__import__('case_sort').questions(data or {}))
    reviewed = set(((data or {}).get('ocr_reviewed') or {}).keys())
    legacy = {d.get('file'): (d.get('engine_used') or d.get('engine') or '')
              for p in (data or {}).get('portfolios') or [] for d in p.get('docs') or [] if d.get('file')}
    rows = []
    for rel in sorted(files):
        e = man.get(rel) or {}
        t = e.get('triage') if (e.get('triage') or {}).get('sha1') == files[rel]['sha1'] else {}
        parts = [p for p in (t or {}).get('parts') or [] if p.get('type') != 'أخرى'] or (t or {}).get('parts') or []
        p0 = parts[0] if parts else {}
        kind = (' و'.join(dict.fromkeys(_TYPE_TITLE.get(p['type'], p['type']) for p in parts)) if len(parts) > 1
                else _TYPE_TITLE.get(p0.get('type'), '') or KIND_LABELS.get(kind_of(rel), ''))
        live = reread_state(base, rel)
        state = ('running' if live else 'done' if e.get('state') == 'done' and e.get('sha1') == files[rel]['sha1']
                 else 'failed' if e.get('state') == 'failed' else 'pending')
        eng = e.get('engine') or legacy.get(rel) or ''      # تحويل قديم (نافذة المستندات) يحفظ محرّكه في الحافظة
        alert = ''
        if state == 'done' and eng in WEAK_ENGINES and rel not in reviewed:
            alert = (f'قُرئ «{os.path.splitext(os.path.basename(rel))[0]}» بمحرّك {doc_router.ENGINE_LABELS.get(eng, eng)} وقد تكون فيه أخطاء '
                     'في الأرقام والتواريخ: قارن المبالغ والتواريخ في نصّه بالمستند الأصلي، أو أعد قراءته بجيميناي.')
        rows.append({'rel': rel, 'name': os.path.basename(rel), 'folder': rel.split('/', 1)[0], 'kind': kind,
                     'side': p0.get('label') or '', 'date': p0.get('date') or '', 'state': state,
                     'message': e.get('message') or '', 'engine': eng, 'pages': e.get('pages'),
                     'size': files[rel]['size'], 'alert': alert, 'question': qs.get(rel, ''),
                     'live': live})
    order = {SYSDOCS: 0, PORTF: 1, MEMOS: 2, OTHER: 3}
    rows.sort(key=lambda r: (order.get(r['folder'], 4), r['date'][6:] + r['date'][3:5] + r['date'][:2], r['name']))
    return rows


def mark_reviewed(base, data, rel):
    """«راجعته»: يُخفى تنبيه القراءة لهذا المستند (ببصمته — نسخة جديدة منه تُنبَّه من جديد)."""
    data.setdefault('ocr_reviewed', {})[rel] = source_sha(base, rel)


# ---------- إعادة قراءة ملف واحد (زر السهم الدائري بجانب كل مستند) ----------

_REREAD = {}                  # (base, rel) ← {'stage': 'convert'|'sort', 'pct': 0..100, 'at'} — تقرؤه القائمة كل 400ms


def reread_state(base, rel):
    return dict(_REREAD.get((os.path.normcase(os.path.abspath(base)), rel)) or {})


def _reread_set(base, rel, **kw):
    k = (os.path.normcase(os.path.abspath(base)), rel)
    if kw.get('stage') is None:
        _REREAD.pop(k, None)
    else:
        _REREAD[k] = dict(_REREAD.get(k) or {}, **kw)


def engine_convert(engine):
    """محوّل بمحرّك بعينه (doc_router.ENGINE_*)؛ None ← المحوّل المعتاد (طبقة النص إن سلمت وإلا محرّك نوع المجلد)."""
    if not engine:
        return CONVERTER or _default_convert

    def run(path, kind):
        import case_documents as cd
        doc = {'doc_type': FOLDER_TYPE.get(kind, doc_router.T_PORTFOLIO)}
        fn = cd.ENGINES.get(engine) or cd.ENGINES.get(doc_router.ENGINE_LOCAL)
        text, pages, warning = fn(path, doc)
        used = doc.get('engine_used') or engine
        return (f'<!-- ⚠ {warning} -->\n{text}' if warning else text), pages, used
    return run


def reread_file(base, data, rel, ask=None, engine=None, convert=None):
    """يعيد قراءة ملف واحد من البداية: التحويل إلى markdown (بمحرّك engine إن اختير) ثم الفرز والتسمية والنقل.
    يرجع المسار النسبي الجديد (قد يتغير بالفرز). التقدّم الحي في reread_state (القائمة تعرضه شريطاً)."""
    import case_triage
    import case_sort
    man = load_manifest(base)
    path = os.path.join(base, rel)
    if not os.path.isfile(path):
        raise FileNotFoundError(rel)
    f = scan(base, {}).get(rel) or {'size': os.path.getsize(path), 'mtime': int(os.path.getmtime(path)), 'sha1': sha1(path)}
    entry = dict(f, md=md_rel(rel), at=_now(), origin='converted')
    _reread_set(base, rel, stage='convert', pct=5, at=_now())
    doc_router.set_progress_hook(lambda done, n: _reread_set(base, rel, stage='convert',
                                                             pct=5 + int(70 * done / max(1, n))))
    try:
        doc_router.set_triage(case_triage.parties_text(data), base)
        try:
            text, pages, used, retries = convert_guarded(convert or engine_convert(engine), path, kind_of(rel))
            blocks = doc_router.take_triage()
        finally:
            doc_router.set_triage(None)
            doc_router.set_progress_hook(None)
        if not (text or '').strip():
            raise ValueError('لم يُستخرج نص')
        _write_md(base, entry['md'], text)
        entry.update(state='done', message='', pages=pages, engine=used, retries=retries)
        case_triage.stash_conversion(entry, blocks, pages)
        old = man['files'].get(rel) or {}
        if (old.get('sort') or {}).get('state') == 'manual':
            entry['sort'] = old['sort']
        man['files'][rel] = entry                    # فرز قديم يُمسح: يُعاد من النص الجديد
        save_manifest(base, man)
        _reread_set(base, rel, stage='sort', pct=80)
        out = case_sort.run(base, data, ask, only=[rel])
        rec = (out.get('sorted') or [{}])[0]
        if out.get('errors'):
            raise ValueError(out['errors'][0][1])
        try:
            data['triage_docs'] = case_triage.attachment_items(base)
            import case_summary
            case_summary.write(base, data)
        except Exception:
            pass
        return rec.get('file') or rel
    except Exception as e:
        if is_key_failure(e):
            raise
        man = load_manifest(base)
        e_ = man['files'].setdefault(rel, entry)
        if e_.get('state') != 'done':
            e_.update(state='failed', message=str(e) or e.__class__.__name__)
            save_manifest(base, man)
        raise
    finally:
        _reread_set(base, rel, stage=None)


def count_check(base, files=None, known=None, busy=()):
    """بعد كل مزامنة: عدد الأصول = عدد ملفات markdown؟ يرجع {originals, markdown, ok, unconverted:[(اسم، سبب)], line}.
    line = السطر الأحمر بأسماء غير المحوَّل وسبب كل منها (فارغ عند التطابق)."""
    known = known if known is not None else load_manifest(base)['files']
    files = files if files is not None else scan(base, known)
    bad = list(unsupported(base))
    md_n = 0
    for rel in sorted(files):
        e = known.get(rel) or {}
        if e.get('state') == 'done' and e.get('sha1') == files[rel]['sha1']                 and os.path.exists(os.path.join(base, e.get('md') or '')):
            md_n += 1
        elif rel in busy:
            bad.append((rel, 'قيد التحويل في نافذة المستندات'))
        else:
            bad.append((rel, e.get('message') or ('لم يُحوَّل بعد' if e.get('state') != 'failed' else 'فشل التحويل')))
    total = len(files) + len(unsupported(base))
    line = ''
    if bad:
        line = (f'الأصول {total} وملفات markdown {md_n} — لم يُحوَّل: '
                + '؛ '.join(f'{os.path.basename(r)} ({why})' for r, why in bad))
    return {'originals': total, 'markdown': md_n, 'ok': not bad, 'unconverted': [list(x) for x in bad], 'line': line}


def has_pending(base):
    """True إن في المجلد أصل جديد/متغيّر لم يُحوَّل بعد (فتُعاد القراءة والمزامنة قبل إعادة الكتابة)."""
    known = load_manifest(base)['files']
    return any(_stale(base, known.get(rel), f) and (known.get(rel) or {}).get('state') != 'failed'
               for rel, f in scan(base, known).items())


def summary_line(converted, failed, missing):
    parts = []
    if converted:
        parts.append(f'حوّلتُ {len(converted)} ملفاً جديداً')
    if failed:
        parts.append('تعذّر تحويل ' + '، '.join(f'{os.path.basename(r)} ({why})' for r, why in failed[:3])
                     + (f' و{len(failed) - 3} غيرها' if len(failed) > 3 else ''))
    if missing:
        parts.append(f'{len(missing)} أصلاً حُذف من المجلد (بقيت نسخته في markdown): '
                     + '، '.join(os.path.basename(r) for r in missing[:3]))
    return ' — '.join(parts) or 'جاهز'


def files_word(n):
    """«ملف واحد» / «ملفين» / «3 ملفات» / «11 ملفاً»."""
    if n == 1:
        return 'ملف واحد'
    if n == 2:
        return 'ملفين'
    return f'{n} ملفات' if 3 <= n <= 10 else f'{n} ملفاً'


def brief_status(fs):
    """سطر حالة مختصر لصفحة القضية بدل سيل الأخطاء: {'line', 'details': [(اسم، سبب)], 'bad'}.
    fs = data['folder_sync'] أو نتيجة sync_case_folder. التفاصيل (سبب كل ملف) تُعرض بزر «التفاصيل» فقط."""
    fs = fs or {}
    seen, details = set(), []
    for rel, why in list((fs.get('count') or {}).get('unconverted') or []) + list(
            fs.get('failed') if isinstance(fs.get('failed'), list) else []):
        name = os.path.basename(rel)
        if name not in seen:
            seen.add(name)
            details.append((name, why or 'سبب غير معروف'))
    conv = fs.get('converted')
    conv = len(conv) if isinstance(conv, list) else (conv or 0)
    parts = [f'حوّلتُ {files_word(conv)} جديداً' if conv else '']
    if details:
        parts.append(f'تعذّر تحويل {files_word(len(details))}')
    line = ' — '.join(p for p in parts if p) or 'جاهز'
    return {'line': line, 'details': details, 'bad': bool(details)}


def details_text(details):
    return '\n'.join(f'• {n}: {why}' for n, why in details)


# ---------- القراءة ----------

def latest_md(base, kind):
    """(المسار النسبي للأصل، نص markdown) لأحدث أصل محوَّل من نوع kind (kind_of)، أو (None, '').
    «حكم الإحالة»/«صحيفة الدعوى» بالاسم المعتمد تتقدّم على غيرها من نوعها."""
    man = load_manifest(base)['files']
    best = None
    for rel, e in man.items():
        if kind_of(rel) != kind or e.get('state') != 'done':
            continue
        p = os.path.join(base, rel)
        if not os.path.exists(p):
            continue
        canon = os.path.splitext(os.path.basename(rel))[0].split(' (')[0] == SYSTEM_NAMES.get(kind)
        t = (1 if canon else 0, os.path.getmtime(p))
        if best is None or t > best[0]:
            best = (t, rel, e)
    if best is None:
        return None, ''
    try:
        with open(os.path.join(base, best[2]['md']), encoding='utf-8') as f:
            return best[1], f.read()
    except OSError:
        return None, ''


def source_sha(base, rel):
    return (load_manifest(base)['files'].get(rel) or {}).get('sha1', '') if rel else ''


# ---------- الترحيل الآمن ----------

def _log(base, lines):
    if not lines:
        return
    p = os.path.join(base, LOG_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'a', encoding='utf-8') as f:
        f.write(f'# {_now()}\n' + '\n'.join(lines) + '\n')


def migrate_legacy(base, data):
    """ينسخ (لا ينقل ولا يحذف) أصول البنية الأقدم (_نظام/01_اصول) إلى البنية الحالية ومشتقاتها إلى markdown فلا
    يُعاد تحويلها: الحكم والصحيفة ← مستندات_النظام بالاسم المعتمد، المحاضر ← «محضر الخبرة رقم N»، الحوافظ ← أخرى
    (يفرزها case_sort). يسجّل ما نُسخ في _نظام/سجلات وdata['folder_migration']. يرجع قائمة (من، إلى)."""
    ensure_structure(base)
    moves = []
    legacy = cl.LEGACY_ASSETS + '/'

    def take(src_rel, folder, name=None, md_src=None):
        src = os.path.join(base, src_rel)
        if not os.path.isfile(src) or is_temp(os.path.basename(src)):
            return None
        try:
            rel = add_original(base, src, folder, name)
        except OSError:
            return None
        moves.append((src_rel.replace('\\', '/'), rel))
        if md_src and os.path.isfile(os.path.join(base, md_src)):
            md = md_rel(rel)
            if not os.path.exists(os.path.join(base, md)):
                os.makedirs(os.path.dirname(os.path.join(base, md)), exist_ok=True)
                shutil.copy2(os.path.join(base, md_src), os.path.join(base, md))
            record_converted(base, rel, md, origin='migrated')
        return rel

    for kind in ('judgment', 'claim'):
        rec = (data.get('sources') or {}).get(kind) or {}
        if rec.get('file', '').startswith(legacy):
            ext = os.path.splitext(rec['file'])[1] or '.pdf'
            new = take(rec['file'], SYSDOCS, SYSTEM_NAMES[JUDGMENT if kind == 'judgment' else PLAINT] + ext)
            if new:
                rec['legacy_file'], rec['file'] = rec['file'], new
    old_min = os.path.join(base, cl.LEGACY_ASSETS, 'محاضر')
    if os.path.isdir(old_min):
        for n in sorted(os.listdir(old_min)):
            p = os.path.join(old_min, n)
            take(f'{legacy}محاضر/{n}', SYSDOCS, minute_file_name(p))
    for p in data.get('portfolios') or []:
        for d in p.get('docs') or []:
            f = d.get('file') or ''
            if not f.startswith(legacy) or d.get('ref_of'):
                continue
            md_src = d.get('md') if (d.get('convert') or {}).get('state') == 'done' else None
            new = take(f, OTHER, d.get('orig_name') or None, md_src)
            if new:
                d['legacy_file'], d['file'] = f, new
                if md_src:
                    d['legacy_md'], d['md'] = d['md'], md_rel(new)
    if moves:
        _log(base, [f'نُسخ: {a}  ←  {b}' for a, b in moves])
    data['folder_migration'] = {'at': _now(), 'version': 2, 'copied': [list(x) for x in moves]}
    return moves


def migrate_root(caso_no, new_root, old_root):
    """قضية موجودة في الجذر القديم (سطح المكتب) فقط ← تُنسخ كلها إلى الجديد (يبقى القديم كما هو). يرجع True إن نسخ."""
    if not old_root or os.path.normcase(os.path.abspath(old_root)) == os.path.normcase(os.path.abspath(new_root)):
        return False
    src, dst = os.path.join(old_root, caso_no), os.path.join(new_root, caso_no)
    if not os.path.isdir(src) or os.path.exists(dst):
        return False
    os.makedirs(new_root, exist_ok=True)
    shutil.copytree(src, dst)
    _log(dst, [f'نُسخ مجلد القضية كاملاً من {src} إلى {dst} (القديم لم يُحذف)'])
    return True


# ---------- الجلب من النظام والمحاضر المحلية ----------

def minute_file_name(path, fallback=''):
    """«محضر الخبرة رقم N.ext» والرقم من نص المحضر نفسه (لا ترتيب التحميل)، ثم من اسم ملف البرنامج «N.docx»."""
    ext = os.path.splitext(path)[1]
    try:
        import case_procedures as cp
        no = cp.minute_meta(path).get('no')
        if no is None:
            no = cp._number(os.path.basename(path))
    except Exception:
        no = None
    if no is not None:
        return minute_name(no) + ext
    return f"محضر الخبرة - {safe_name(fallback or os.path.splitext(os.path.basename(path))[0])}{ext}"


def collect_local_minutes(base, caso_no, minutes_root=None):
    """محاضر Word التي يكتبها البرنامج ({جذر المحاضر}\\{رقم الخبرة}\\N.docx) تُنسخ إلى مستندات_النظام باسم
    «محضر الخبرة رقم N». المطابق بالبصمة لا يُنسخ ثانية."""
    try:
        import case_procedures as cp
        folder = cp.minutes_dir(caso_no, minutes_root)
        names = sorted(os.listdir(folder))
    except Exception:
        return []
    out = []
    for n in names:
        p = os.path.join(folder, n)
        if os.path.isfile(p) and not is_temp(n) and not cp._is_notice(n) and cp._number(n) is not None:
            out.append(add_original(base, p, SYSDOCS, minute_file_name(p)))
    return out


def system_kind(row):
    """نوع مستند من صفحة الملف الآلي، أو None."""
    t = row.get('doc_type') or ''
    if 'محضر' in t:
        return MINUTES
    if 'تقرير' in t:
        return PRIOR
    if 'حكم' in t:
        return JUDGMENT
    if any(k in t for k in ('صحيفة', 'صحيفه', 'لائحة دعوى')):
        return PLAINT
    return None


def has_kind(base, kind):
    """هل في مستندات_النظام أصل من هذا النوع (حكم الإحالة/صحيفة الدعوى بالاسم المعتمد)؟"""
    want = SYSTEM_NAMES.get(kind)
    try:
        names = os.listdir(os.path.join(base, SYSDOCS))
    except OSError:
        return False
    for n in names:
        if is_temp(n):
            continue
        stem = os.path.splitext(n)[0].split(' (')[0]
        if (stem == want) if want else kind_of(f'{SYSDOCS}/{n}') == kind:
            return True
    return False


def fetch_from_system(base, data, cookies, user_id='309', list_rows=None, download=None, kinds=None):
    """يجلب من الملف الآلي إلى مستندات_النظام: أحدث حكم («حكم الإحالة») وأحدث صحيفة («صحيفة الدعوى»)، وكل المحاضر
    («محضر الخبرة رقم N» من نصه) والتقارير السابقة. kinds: الأنواع المطلوبة فقط (None = الكل).
    ما نُزِّل سابقاً (doc_id في data['folder_fetch']) لا يُنزَّل ثانية. يرجع قائمة المسارات النسبية الجديدة."""
    import documents as dm
    if list_rows is None:
        def list_rows():
            secs = dm.parse_sections(dm.get_documents_page(cookies, data.get('autocase_no') or '', user_id))
            return [r for rows in secs.values() for r in rows]
    download = download or (lambda doc_id, path: dm.download_judgment_pdf(cookies, doc_id, path))
    seen = data.setdefault('folder_fetch', {}).setdefault('doc_ids', [])
    groups = {}
    for r in list_rows():
        k = system_kind(r)
        if k and (kinds is None or k in kinds):
            groups.setdefault(k, []).append(r)
    picked = []
    for k, rows in groups.items():
        rows.sort(key=lambda r: dm._parse_doc_date(r.get('doc_date')), reverse=True)
        picked += [(k, r) for r in (rows[:1] if k in (JUDGMENT, PLAINT) else rows)]
    new = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (k, r) in enumerate(picked):
            if str(r['doc_id']) in seen:
                continue
            date = (r.get('doc_date') or '').split(' ')[0].replace('/', '-')
            p = os.path.join(tmp, f'{i}.pdf')
            download(r['doc_id'], p)
            if not (os.path.isfile(p) and os.path.getsize(p) > 0):
                continue
            if k == PLAINT:                       # الصحيفة: المسار الواحد بالمحتوى (لا «صحيفة الدعوى (2)» لكل تنزيل)
                import case_sources
                _rec, added = case_sources.store_claim(base, data, p, doc_id=r['doc_id'])
                if added:
                    new.append(added)
                continue
            if k in SYSTEM_NAMES:
                fname = SYSTEM_NAMES[k] + '.pdf'
            elif k == MINUTES:
                fname = minute_file_name(p, f"{(r.get('doc_type') or '').strip()} {date}".strip())
            else:
                fname = f"تقرير خبرة سابق {date}.pdf" if date else 'تقرير خبرة سابق.pdf'
            new.append(add_original(base, p, SYSDOCS, fname))
            seen.append(str(r['doc_id']))
    data['folder_fetch']['at'] = _now()
    return new


def open_case(base, data, cookies=None, user_id='309', convert=None, fetch=True, stop=None, ask=None):
    """ما يجري عند فتح قضية: البنية ← ترحيل لمرة واحدة ← المحاضر المحلية ← الجلب من النظام ← المزامنة.
    لا يرفع استثناء من الجلب (الشبكة)؛ السبب يُضاف إلى السطر. يرجع نتيجة sync."""
    ensure_structure(base)
    if not data.get('folder_migration'):
        migrate_legacy(base, data)
    notes = []
    try:
        collect_local_minutes(base, data['caso_no'])
    except Exception as e:
        notes.append(f'تعذّر نسخ المحاضر المحلية: {e}')
    if fetch and cookies:
        try:
            fetch_from_system(base, data, cookies, user_id)
        except Exception as e:
            notes.append(f'تعذّر الجلب من النظام: {e}')
    res = sync_case_folder(base, data, convert, stop)
    try:                                       # حكم الإحالة: أحدث حكم يحيل للخبرة (referral_pick)
        import referral_pick
        referral_pick.pick(base, data, ask)
    except Exception as e:
        notes.append(f'تعذّر تحديد حكم الإحالة: {e}')
    if notes:
        res['message'] = ' — '.join([res['message']] + notes)
        data['folder_sync']['message'] = res['message']
    return res


def adopt_manual_judgment(case, pdf_path):
    """حكم إحالة رُفع يدوياً (معلومات القضية): يُنسخ فوراً إلى حكم_الإحالة/ في مجلد القضية ويُسجَّل مصدراً،
    فتقرؤه خطوة المأمورية من المجلد. يرجع المسار النسبي أو '' عند التعذّر (لا يُفشل الرفع)."""
    try:
        import case_sources
        import case_workspace as cw
        base, data = cw.ensure_workspace(case)
        rec = case_sources.store(base, data, 'judgment', pdf_path, None, origin='manual')
        cw.write_case_json(base, data)
        return rec['file']
    except Exception:
        return ''
