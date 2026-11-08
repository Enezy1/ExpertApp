# ===== case_procedures.py — خطوة «الإجراءات» (المرحلة 2ط، أُعيد تنظيمها 2026-10-17: تلقائية بالكامل) =====
# عند فتح الخطوة يجري كل شيء وحده، والخبير لا يضغط إلا ليعدّل:
#   1) المحاضر: تُؤخذ كلها من مكان حفظ المحاضر المضبوط في الإعدادات (expert_settings.load_minutes_root،
#      افتراضياً Desktop\محاضر): مجلد القضية {رقم الخبرة}\ + أي ملف/مجلد في الجذر يحمل رقم الخبرة +
#      ما أضافه الخبير يدوياً (يُنسخ إلى 01_اصول\محاضر داخل مجلد القضية). الأنواع: docx/pdf/صور/md/txt.
#   2) الجلسات حيّة من الموقع (التقويم + سجل الحركة ECS_CASE_FLOW)، ثم المصادر البديلة، ثم المحفوظ.
#      قاعدة الترقيم (كما في api.compute_session_number): المباشرة جلسة أولى ضمنية، و«فتح محضر» تمثّلها
#      ⇒ المحاضر المتوقعة = الجلسات الفعلية المنعقدة + 1. قائمة فارغة ليست نجاحاً.
#   3) الحضور لكل طرف: حضوره في محضر واحد يكفي ← «حضر»؛ لم يرد في أي محضر ← «لم يحضر رغم صحة إعلانه».
#      قواعد أولاً، ثم طلب واحد للذكاء الاصطناعي بكل نصوص الحضور لمن لم تجده القواعد. الغياب «مؤكد» فقط
#      إن قرأه الذكاء أو كانت نصوص الحضور فارغة/«لم يحضر أحد»؛ وإلا يبقى غير مؤكد (لا تخمين).
#   4) نص الإجراءات من قالب تقرير النموذج samples\…H2212338.docx حرفياً، والناقص «[يُكتب]».
#   5) الحالة صادقة: «منتهية» (معتمدة تلقائياً reviewed) فقط إن توفّر تاريخ الاستلام + تاريخ الحجز + الحضور
#      مستخرج لكل الأطراف + عدد المحاضر = عدد الجلسات؛ وإلا needs_input مع سطر بما ينقص بالتحديد.
#      تعديل الخبير للنص بعد الاعتماد يبقيها معتمدة وينبّه الخطوات التالية (case_model.mark_modified).
import hashlib
import json
import os
import re
import shutil
import zipfile
from xml.etree import ElementTree
from datetime import date as _date

import case_memory
import case_model as cm
import case_workspace as cw
import drafting_library as dl

TODO = '[يُكتب]'
MINUTE_EXTS = ('.docx', '.pdf', '.md', '.txt', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp')
FILE_FILTER = 'المحاضر (*.docx *.pdf *.md *.txt *.png *.jpg *.jpeg *.tif *.tiff *.bmp);;كل الملفات (*.*)'
EXTRA_DIR = 'مستندات_النظام'                           # مجلد القضية هو الأصل: «محضر الخبرة رقم N.ext» (case_folder)
LEGACY_EXTRA_DIR = os.path.join('_نظام', '01_اصول', 'محاضر')    # يُقرأ للقضايا القديمة جداً
_NUM_NAME = re.compile(r'(\d+)')


def default_root():
    try:
        import expert_settings
        return expert_settings.load_minutes_root()
    except Exception:
        return os.path.join(os.path.expanduser('~'), 'Desktop', 'محاضر')


def minutes_dir(caso_no, root=None):
    return os.path.join(root or default_root(), caso_no or '')


def _is_notice(name):
    n = name.replace('إ', 'ا')
    return 'اخطار' in n


def _ext_ok(name):
    return os.path.splitext(name)[1].lower() in MINUTE_EXTS and not name.startswith('~$')


def _number(name):
    """رقم المحضر من اسم مثل 3.docx أو «محضر 3.pdf»، وإلا None."""
    stem = os.path.splitext(name)[0]
    if stem.isdigit():
        return int(stem)
    stem = re.sub(r'\s*\(\d+\)\s*$', '', stem) if stem.startswith('محضر الخبرة') else stem     # « (2)» للتكرار
    m = re.fullmatch(r'\s*محضر\s*(?:الخبرة|أعمال|اعمال)?\s*(?:رقم)?\s*\(?\s*(\d+)\s*\)?\s*', stem)
    return int(m.group(1)) if m else None


def scan_minutes(caso_no, root=None):
    """{رقم المحضر: المسار} للملفات المرقّمة في مجلد القضية (كل الأنواع المقبولة). لا تنشئ مجلداً."""
    try:
        names = os.listdir(minutes_dir(caso_no, root))
    except OSError:
        return {}
    out = {}
    for n in sorted(names, key=lambda x: (os.path.splitext(x)[1].lower() != '.docx', x)):
        no = _number(n) if _ext_ok(n) and not _is_notice(n) else None
        if no is not None and no not in out:                 # 3.docx يتقدّم على 3.pdf
            out[no] = os.path.join(minutes_dir(caso_no, root), n)
    return out


def _files_in(folder):
    try:
        return [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                if os.path.isfile(os.path.join(folder, n))]
    except OSError:
        return []


def _extra_roots(root):
    """مع الجذر الافتراضي (Desktop\\محاضر) يُبحث أيضاً في سطح المكتب نفسه عن ملفات تحمل رقم الخبرة."""
    desk = os.path.join(os.path.expanduser('~'), 'Desktop')
    if os.path.normcase(os.path.abspath(root)) == os.path.normcase(os.path.join(desk, 'محاضر')):
        return [desk]
    return []


def find_minutes(caso_no, root=None, base=None, excluded=()):
    """كل محاضر القضية دون سؤال: [{'path','name','no','source'}] (no = رقم المحضر من الاسم أو None).
    مجلد القضية: الملفات المرقّمة أو التي فيها «محضر»/رقم الخبرة. الجذر: الملفات والمجلدات التي تحمل رقم الخبرة.
    ما أضافه الخبير: base\\01_اصول\\محاضر. الإخطار وملفات Word المؤقتة لا تُحسب. لا ينشئ شيئاً."""
    root = root or default_root()
    key = (caso_no or '').lower()
    case_dir = minutes_dir(caso_no, root)
    cands = []
    for p in _files_in(case_dir):
        n = os.path.basename(p)
        if _number(n) is not None or 'محضر' in n or (key and key in n.lower()):
            cands.append((p, 'folder'))
    if key:
        for p in _files_in(root):
            if key in os.path.basename(p).lower():
                cands.append((p, 'root'))
        try:
            subs = [os.path.join(root, d) for d in sorted(os.listdir(root))
                    if key in d.lower() and os.path.isdir(os.path.join(root, d))]
        except OSError:
            subs = []
        for d in subs:
            if os.path.normcase(d) != os.path.normcase(case_dir):
                cands += [(p, 'root') for p in _files_in(d)]
        for extra in _extra_roots(root):                     # محاضر محفوظة مباشرة على سطح المكتب
            cands += [(p, 'root') for p in _files_in(extra) if key in os.path.basename(p).lower()]
    if base:
        cands += [(p, 'added') for p in _files_in(os.path.join(base, EXTRA_DIR))
                  if os.path.basename(p).startswith('محضر')]
        cands += [(p, 'added') for p in _files_in(os.path.join(base, LEGACY_EXTRA_DIR))]
    skip = {os.path.normcase(os.path.abspath(x)) for x in excluded or ()}
    tri_no = {}                     # رقم المحضر بعد فرزه (case_sort.renumber_minutes يصحّح الرقم المكرر في نص المحضر)
    if base:
        try:
            import case_triage
            tri_no = {r['sha1']: r['no'] for r in case_triage.minute_records(base) if r.get('sha1') and r.get('no')}
        except Exception:
            tri_no = {}
    out, seen, nums = [], set(), {}
    for p, src in cands:
        n = os.path.basename(p)
        k = os.path.normcase(os.path.abspath(p))
        if k in seen or not _ext_ok(n) or _is_notice(n):
            continue
        seen.add(k)
        if k in skip:
            continue
        meta = minute_meta(p)
        no_file = _number(n)
        no = meta['no'] if meta['no'] is not None else no_file     # رقم المحضر من نصه أولاً، لا من اسم الملف
        if tri_no:
            fixed = tri_no.get(_sha1(p))
            if fixed and fixed != no:
                meta = dict(meta, no=fixed)
                no = fixed
        rec = {'path': p, 'name': n, 'no': no, 'source': src, 'no_file': no_file,
               'no_source': 'text' if meta['no'] is not None else ('name' if no_file is not None else ''),
               'date': meta['date']}
        if meta['no'] is not None and no_file is not None and meta['no'] != no_file:
            rec['no_conflict'] = no_file
        if no is not None and no in nums:                    # 3.docx و3.pdf = محضر واحد
            if n.lower().endswith('.docx') and not nums[no]['name'].lower().endswith('.docx'):
                nums[no].update(rec)
            continue
        if no is not None:
            nums[no] = rec
        out.append(rec)
    out.sort(key=minute_order_key)
    return out


# ---------- رقم المحضر وتاريخه من المحضر نفسه (2026-10-18) ----------
# السبب الجذري لـ«فُتح محضر رقم 1 والصحيح 2»: الرقم كان يُؤخذ من اسم الملف (N.docx) فقط، بينما محضر البرنامج
# يكتب «رقم المحضر» و«التاريخ» في رأس الصفحة (word/header*.xml) الذي لم يكن يُقرأ أصلاً (read_minute_paragraphs
# تقرأ document.xml وحده)؛ فأي ملف سُمّي بغير رقمه (أول جلسة تُحفظ دائماً 1.docx، نسخة منقولة، محضر من النظام
# باسم «محضر أعمال 2026-…») يأخذ رقماً خاطئاً أو ترتيباً من التحميل. الآن: الرقم من نص المحضر/رأسه، ثم الاسم احتياطاً.

_HDR_NO = re.compile(r'رقم\s*المحضر\s*[:：\-]?\s*\(?\s*(\d{1,3})(?!\d)')
_TXT_NO = re.compile(r'محضر\s+(?:[أا]عمال\s+)?(?:ال)?(?:خبرة\s+)?رقم\s*[:：\-]?\s*\(?\s*(\d{1,3})(?!\d)'
                     r'|(?:ال)?جلسة\s+رقم\s*[:：\-]?\s*\(?\s*(\d{1,3})(?!\d)')
_HDR_DATE = re.compile(r'التاريخ\s*[:：]?\s*')
_META_CACHE = {}


def _docx_header_paras(path):
    try:
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist() if re.fullmatch(r'word/header\d*\.xml', n))
            roots = [ElementTree.fromstring(z.read(n)) for n in names]
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError):
        return []
    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    out = []
    for r in roots:
        out += [''.join(x.text or '' for x in p.iter(ns + 't')).strip() for p in r.iter(ns + 'p')]
    return [p for p in out if p]


def number_from_text(text):
    """رقم المحضر من نص رأسه/متنه («رقم المحضر 2»، «محضر أعمال رقم (2)»، «الجلسة رقم 2») أو None."""
    t = (text or '').translate(_DIGITS).replace('ـ', '')
    m = _HDR_NO.search(t)
    if m:
        return int(m.group(1))
    m = _TXT_NO.search(t)
    return int(m.group(1) or m.group(2)) if m else None


def date_from_text(text):
    """تاريخ المحضر (ISO): بعد كلمة «التاريخ» إن وُجدت، وإلا أول تاريخ في أعلى النص."""
    t = (text or '').translate(_DIGITS).replace('ـ', '')
    m = _HDR_DATE.search(t)
    if m:
        d = minute_date([t[m.end():m.end() + 20]])
        if d:
            return d
    return minute_date(t.splitlines()[:25] or [t])


def minute_meta(path):
    """{'no','date'} من المحضر نفسه دون OCR: رأس Word ومتنه، أو طبقة نص PDF، أو md/txt. ذاكرة بالحجم والوقت."""
    try:
        st = os.stat(path)
        key = (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns)
    except OSError:
        return {'no': None, 'date': ''}
    if key in _META_CACHE:
        return _META_CACHE[key]
    ext = os.path.splitext(path)[1].lower()
    head = ''
    try:
        if ext == '.docx':
            head = ' '.join(_docx_header_paras(path)) + '\n' + '\n'.join(read_minute_paragraphs(path)[:25])
        elif ext in ('.md', '.txt'):
            with open(path, 'rb') as f:
                head = '\n'.join(f.read().decode('utf-8', errors='replace').splitlines()[:40])
        elif ext == '.pdf':
            import fitz
            with fitz.open(path) as d:
                head = d[0].get_text() if d.page_count else ''
    except Exception:
        head = ''
    hdr = head.split('\n', 1)[0] if ext == '.docx' else head
    out = {'no': number_from_text(head), 'date': date_from_text(hdr) or date_from_text(head)}
    _META_CACHE[key] = out
    return out


def minute_order_key(r):
    """الترتيب: بالتاريخ ثم بالرقم (بلا تاريخ ← بعد المؤرَّخ بحسب رقمه)."""
    return (r.get('date') or '9999-99-99', r.get('no') is None, r.get('no') or 0, r.get('name') or '')


def order_warnings(minutes):
    """تنبيهات: رقم نص المحضر يخالف اسم ملفه، أو الرقم يخالف ترتيب التواريخ. دالة صرفة."""
    out = []
    for m in minutes:
        if m.get('no_conflict') is not None:
            out.append(f"الملف «{m['name']}» يوحي بالمحضر {m['no_conflict']} لكن نصه «رقم المحضر {m['no']}» — اعتُمد رقم النص")
    dated = sorted((m for m in minutes if m.get('date') and m.get('no') is not None), key=lambda m: (m['date'], m['no']))
    for a, b in zip(dated, dated[1:]):
        if b['no'] <= a['no']:
            out.append(f"المحضر {b['no']} ({_dmy(b['date'])}) بعد المحضر {a['no']} ({_dmy(a['date'])}) تاريخاً "
                       "والرقم لا يتبع الترتيب — تحقّق من الرقم")
    return out


# ---------- قراءة نص المحضر (كل الأنواع) ----------

def read_minute_paragraphs(path):
    try:
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read('word/document.xml'))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError):
        return []
    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    paras = [''.join(x.text or '' for x in p.iter(ns + 't')).strip() for p in root.iter(ns + 'p')]
    return [p for p in paras if p]


def _lines(text):
    return [l.strip() for l in (text or '').splitlines() if l.strip()]


def _ocr_pdf(path, pages=6):
    import fitz
    import local_ocr
    with fitz.open(path) as d:
        n = min(d.page_count, pages)
    return '\n'.join(p.text for p in local_ocr.read_pages(path, list(range(n))).pages)


def read_minute_text(path):
    """فقرات المحضر: docx من XML، md/txt كما هي، pdf بطبقته النصية ثم OCR الداخلي، والصور بالـOCR الداخلي.
    لا يرفع استثناءً: تعذّر القراءة ← []."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == '.docx':
            return read_minute_paragraphs(path)
        if ext in ('.md', '.txt'):
            with open(path, 'rb') as f:
                return _lines(f.read().decode('utf-8', errors='replace'))
        if ext == '.pdf':
            import fitz
            with fitz.open(path) as d:
                text = '\n'.join(p.get_text() for p in d)
            return _lines(text if len(text.strip()) >= 50 else _ocr_pdf(path))
        import fitz                                          # صورة ← PDF مؤقت ← OCR
        import tempfile
        with fitz.open(path) as img:
            pdf = img.convert_to_pdf()
        fd, tmp = tempfile.mkstemp(suffix='.pdf')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(pdf)
            return _lines(_ocr_pdf(tmp, 1))
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    except Exception:
        return []


TEXT_READER = read_minute_text          # قابل للاستبدال في الاختبارات
_TEXT_CACHE = {}


def minute_texts(minutes):
    """{المسار: الفقرات} مع ذاكرة مؤقتة بالحجم ووقت التعديل (لا يُعاد OCR ملف لم يتغيّر)."""
    out = {}
    for m in minutes:
        p = m['path']
        try:
            st = os.stat(p)
            key = (os.path.normcase(os.path.abspath(p)), st.st_size, st.st_mtime_ns, TEXT_READER)
        except OSError:
            out[p] = []
            continue
        if key not in _TEXT_CACHE:
            _TEXT_CACHE[key] = TEXT_READER(p)
        out[p] = _TEXT_CACHE[key]
    return out

_DATE_RE = re.compile(r'(?<!\d)(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})(?!\d)')
_DATE_YMD = re.compile(r'(?<!\d)(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?!\d)')
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def minute_date(paras):
    """أول تاريخ في أعلى المحضر (ISO) أو ''. يُستخدم لربط المحضر غير المرقّم بجلسته."""
    for p in paras[:25]:
        t = p.translate(_DIGITS)
        m = _DATE_RE.search(t)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = _DATE_YMD.search(t)
            if not m:
                continue
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            return f'{y:04d}-{mo:02d}-{d:02d}'
    return ''


# ---------- جلب الجلسات (مصادر قابلة للحقن) ----------
# الصيغة الموحَّدة: قائمة {'date': 'YYYY-MM-DD', 'open_record': bool}

def live_fetcher(cookies, caso_no):
    """من نظام الخبراء مباشرة (api.get_all_case_sessions)."""
    def fetch():
        import api
        return [{'date': (s.get('start') or '')[:10], 'time': (s.get('start') or '')[11:16],
                 'open_record': bool(api._is_open_record_session(s)),
                 'booking': 'حجز' in (s.get('title') or '')}
                for s in api.get_all_case_sessions(cookies, caso_no)]
    return fetch


def local_fetcher(caso_no):
    """من القاعدة المحلية case_db.sessions (احتياطي عند انقطاع الاتصال)."""
    def fetch():
        import case_db
        return [{'date': (r.get('session_date') or '')[:10],
                 'open_record': 'فتح محضر' in ((r.get('session_type') or '') + (r.get('title') or ''))}
                for r in case_db.get_case_sessions(caso_no)]
    return fetch


def summarize_sessions(sessions, today=None):
    """يحسب: عدد الكل، الفعلية المنعقدة (≤ اليوم)، القادمة، المحاضر المتوقعة، تواريخ كل رقم محضر."""
    today = today or _date.today().isoformat()
    real = sorted(s['date'] for s in sessions if not s.get('open_record') and s.get('date'))
    held = [d for d in real if d <= today]
    opened = sorted(s['date'] for s in sessions if s.get('open_record') and s.get('date'))
    dates = {1: opened[0] if opened else ''}
    for i, d in enumerate(held, 2):
        dates[i] = d
    return {'count_system': len(sessions), 'real_held': len(held), 'future': len(real) - len(held),
            'expected_minutes': len(held) + 1, 'dates': dates}


# ---------- سجل الحركة ECS_CASE_FLOW: الجلسات + تاريخا الاستلام والحجز ----------

def _iso(d):
    """YYYY-MM-DD ← DD/MM/YYYY (وإلا '')."""
    m = re.fullmatch(r'(\d{2})/(\d{2})/(\d{4})', (d or '').strip())
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else ''


def _name_matches(mine, full):
    parts = (mine or '').split()
    if not parts or not full:
        return False
    return parts[0] in full and parts[-1] in full


def parse_flow_actions(actions, my_name=''):
    """من قائمة case_stats.get_case_actions ← {'sessions','received','booked'} (تواريخ ISO).
    الاستلام: آخر «توزيع للخبراء» لي (أو آخر توزيع إن لم يُعرف اسمي). الحجز: آخر جلسة نوعها يبدأ بـ«حجز»."""
    sessions, received, booked = [], '', ''
    for a in actions or []:
        act, date = a.get('action') or '', _iso(a.get('date'))
        if act.startswith('جلسة «'):
            typ = act[len('جلسة «'):].rstrip('»')
            sessions.append({'date': date, 'time': (a.get('time') or '')[:5], 'open_record': typ.startswith('فتح محضر'),
                             'booking': typ.startswith('حجز')})
            if typ.startswith('حجز') and date:
                booked = max(booked, date)
        elif act == 'توزيع للخبراء' and date:
            if not my_name or _name_matches(my_name, a.get('to_name') or ''):
                received = max(received, date)
    return {'sessions': sessions, 'received': received, 'booked': booked}


def flow_fetcher(cookies, caso_no, my_name=''):
    def fetch():
        import case_stats
        return parse_flow_actions(case_stats.get_case_actions(cookies, caso_no), my_name)
    return fetch


def merge_sessions(calendar, flow):
    """يدمج جلسات التقويم وسجل الحركة بلا تكرار (التاريخ + الوقت إن توفّرا)."""
    out = list(calendar or [])

    def same(a, b):
        return a.get('date') == b.get('date') and (not a.get('time') or not b.get('time') or a['time'] == b['time'])
    for f in flow or []:
        if not any(same(f, c) for c in out):
            out.append(f)
    return out


# ---------- الحضور: قواعد ثم ذكاء اصطناعي ----------
_DIAC = re.compile(r'[ً-ْـ]')
_AR_MAP = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي', 'ة': 'ه', 'ؤ': 'و', 'ئ': 'ي'})
_STOP = {'بصفته', 'بصفتها', 'وكيل', 'ممثل', 'شركه', 'مساهمه', 'مقفله', 'عامه', 'ذ', 'م', 'ش', 'السيد', 'السيده'}
_ATTEND_ALL = ('حضر الطرفان', 'حضر جميع الاطراف', 'حضر كافه الاطراف', 'حضر الاطراف جميعا', 'حضر الخصوم')
_NONE = ('لم يحضر احد', 'لم يحضر اي')


def norm_ar(t):
    t = _DIAC.sub('', t or '').translate(_AR_MAP)
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', t)).strip()


def _tokens(t):
    out = []
    for w in norm_ar(t).split():
        w2 = w[2:] if w.startswith('ال') and len(w) > 4 else w
        if w2 not in _STOP and w not in _STOP and len(w2) > 1 and not w2.isdigit():
            out.append(w2)
    return out


def party_present(party, segment):
    """القاعدة: ≥ 60% من الكلمات المميِّزة لاسم الطرف ترد في نص الحضور."""
    toks = _tokens(party)
    if not toks:
        return False
    seg = set(_tokens(segment))
    return sum(1 for t in toks if t in seg) / len(toks) >= 0.6


def minute_parties(paras):
    """(المدعية، [المدعى عليهم]) من ترويسة المحضر: بعد «المرفوعة من» و«المرفوعة ضد»."""
    plaintiff, defs = '', []
    for i, p in enumerate(paras):
        n = norm_ar(p)
        if n.startswith('المرفوعه من') and i + 1 < len(paras):
            plaintiff = paras[i + 1]
        elif n.startswith('المرفوعه ضد'):
            for q in paras[i + 1:]:
                if 'بحضور الخبير' in q:
                    break
                defs.extend(re.sub(r'^\s*\d+\s*[-.)]\s*', '', line).strip() for line in q.splitlines())
    return plaintiff, [d for d in defs if d]


def attendance_segment(paras):
    """نص ما بين «وقد حضر في الموعد المحدد كل من:» و«وبوشرت…». '' إن لم توجد العبارة."""
    seg, on = [], False
    for p in paras:
        if not on and 'وقد حضر' in p:
            on = True
            seg.append(p.split(':', 1)[1] if ':' in p else '')
            continue
        if on:
            if p.startswith('وبوشرت'):
                break
            seg.append(p)
    return ' '.join(s for s in seg if s).strip()


_REP = r'(?:وكيل|وكيله|ممثل|ممثله|محامي|مندوب|حضر\s+عن|عن)'
_PL_RE = re.compile(_REP + r'\s+(?:ال)?(?:شركه\s+)?المدعي(?:ه|ين|ون)?(?!\s*علي)')
_DF_RE = re.compile(_REP + r'\s+(?:ال)?(?:شركه\s+)?المدعي\s*علي(?:ه|ها|هم)?')


def role_present(seg, role):
    """حضور بالصفة: «وكيل المدعية/ …» يكفي ولو لم يُذكر اسم الطرف؛ «لم يحضر أحد عن …» لا يُعدّ حضوراً."""
    n = norm_ar(seg)
    rx = _PL_RE if role == 'plaintiff' else _DF_RE
    for m in rx.finditer(n):
        before = n[max(0, m.start() - 20):m.start()]
        if 'لم يحضر' in before or 'لم يحضر' in n[m.start():m.start() + 12]:
            continue
        return True
    return False


def rules_attendance(paras, parties, roles=None):
    """[فهارس الأطراف الحاضرة] أو None إن لم يوجد قسم الحضور أصلاً. فارغ = لم يحضر أحد/لا شيء مكتوب."""
    if not any('وقد حضر' in p for p in paras):
        return None
    seg = attendance_segment(paras)
    n = norm_ar(seg)
    if not n:
        return []
    if any(k in n for k in _ATTEND_ALL):
        return list(range(len(parties)))
    roles = roles or []
    return [i for i, p in enumerate(parties) if party_present(p, seg)
            or (i < len(roles) and role_present(seg, roles[i]))]


def _empty_segment(seg):
    n = norm_ar(seg)
    return not n or any(k in n for k in _NONE)


def ai_attendance(segment, parties, ask):
    """يطلب JSON {"present":[أرقام الأطراف من 1]} ويرجع فهارس (من 0) أو None عند الفشل. لا يرفع استثناء.
    segment نص حضور محضر واحد أو نصوص عدة محاضر معاً (الحضور في أي منها يكفي)."""
    prompt = ('من نصوص الحضور التالية في محاضر خبرة، حدّد أيّ الأطراف المرقّمة حضر فعلاً في محضر واحد على الأقل. '
              'أجب بـ JSON فقط بالشكل {"present":[1,2]} (أرقام الأطراف الحاضرة؛ فارغة إن لم يحضر أحد). '
              'لا تخمّن: إن لم يُذكر الطرف أو من يمثله صراحةً فهو غير حاضر.\n\nالأطراف:\n'
              + '\n'.join(f'{i}) {p}' for i, p in enumerate(parties, 1))
              + f'\n\nنص الحضور:\n{segment}')
    try:
        txt = ask(prompt)
        m = re.search(r'\{.*\}', txt or '', re.S)
        nums = json.loads(m.group(0)).get('present', [])
        got = sorted({int(n) - 1 for n in nums if 1 <= int(n) <= len(parties)})
        import ai_call_log
        ai_call_log.verdict(True, f'الحاضرون: {len(got)} من {len(parties)}')
        return got
    except Exception as e:
        try:
            import ai_call_log
            ai_call_log.verdict(False, f'ردّ غير مفهوم: {e}')
        except Exception:
            pass
        return None


def _sha1(path):
    try:
        with open(path, 'rb') as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return ''


def _label(m):
    return f"المحضر {m['no']}" if m.get('no') is not None else m.get('name') or 'محضر'


def triage_minutes(base, minutes):
    """سجلات الفرز (case_triage) لمحاضر القائمة، مربوطة بالمسار أو برقم المحضر. complete = كل محضر له سجل."""
    if not base:
        return None
    try:
        import case_triage
        recs = case_triage.minute_records(base)
    except Exception:
        return None
    if not recs:
        return None
    by_path = {os.path.normcase(os.path.abspath(r['path'])): r for r in recs}
    by_sha = {r['sha1']: r for r in recs if r.get('sha1')}
    by_no = {r['no']: r for r in recs if r.get('no') is not None}
    got = []
    for m in minutes:                                   # المسار، ثم بصمة المحتوى (نسخة مجلد المحاضر)، ثم رقم المحضر
        r = (by_path.get(os.path.normcase(os.path.abspath(m['path']))) or by_sha.get(_sha1(m['path']))
             or by_no.get(m.get('no')))
        if r is not None:
            got.append(r)
    return {'records': got, 'complete': bool(minutes) and len(got) == len(minutes)}


def _triage_present(parties, roles, tri):
    """الحاضرون من الفرز: (الدور، الترتيب) ← فهرس الطرف في قائمة الأطراف. None إن لم تُفرز كل المحاضر."""
    if not tri or not tri.get('complete'):
        return None
    present = set()
    for r in tri['records']:
        for role, idx in r.get('present') or []:
            same = [i for i, x in enumerate(roles) if x == role]
            if same:
                present.add(same[min(max(int(idx or 1), 1), len(same)) - 1])
    return {'key': 'triage', 'present': sorted(present), 'how': 'الفرز'}


def analyze_attendance(data, minutes, ask=None, texts=None, triage=None):
    """يحلّل كل المحاضر ويحفظ النتيجة لكل طرف في data['procedures']['attendance']:
    candidates (لكل محضر: نص الحضور وما وجدته القواعد) و result (لكل طرف: حضر؟ مؤكد؟ أين؟ كيف؟).
    الذكاء الاصطناعي: طلب واحد بكل نصوص الحضور لمن لم تجده القواعد، ويُحفظ ببصمة النصوص فلا يتكرر.
    تعديل الخبير (overrides) يتقدّم على الكل ويبقى ما دام الطرف نفسه موجوداً."""
    att = data.setdefault('procedures', {}).setdefault('attendance', {})
    texts = texts if texts is not None else minute_texts(minutes)
    parties, roles = [], []
    for m in minutes:
        pl, defs = minute_parties(texts.get(m['path']) or [])
        if pl or defs:
            parties = ([pl] if pl else []) + defs
            roles = (['plaintiff'] if pl else []) + ['defendant'] * len(defs)
            break
    if not parties:
        c = data.get('case') or {}
        pl = [x for x in [c.get('plaintiff') or c.get('company')] if x]
        defs = [d for d in c.get('defendants') or [] if d]
        parties, roles = pl + defs, ['plaintiff'] * len(pl) + ['defendant'] * len(defs)
    old_parties = att.get('parties') or []
    overrides = {}
    for k, v in (att.get('overrides') or {}).items():          # تعديل الخبير مربوط باسم الطرف
        try:
            name = old_parties[int(k)]
        except (ValueError, IndexError):
            continue
        if name in parties:
            overrides[str(parties.index(name))] = bool(v)
    cands = []
    for m in minutes:
        paras = texts.get(m['path']) or []
        seg = attendance_segment(paras)
        res = rules_attendance(paras, parties, roles) if parties else None
        cands.append({'no': m.get('no'), 'name': m['name'], 'label': _label(m), 'segment': seg,
                      'has_section': res is not None, 'present': res or [], 'sha1': _sha1(m['path'])})
    found = {}
    for c in cands:
        for i in c['present']:
            found.setdefault(i, c['label'])
    sections = [c for c in cands if c['has_section']]
    need = [i for i in range(len(parties)) if i not in found and str(i) not in overrides]
    written = [c for c in sections if not _empty_segment(c['segment'])]
    explicit_none = any(any(k in norm_ar(c['segment']) for k in _NONE) for c in sections)
    ai_prev, ai = att.get('ai') or {}, None
    ai_error = ''
    if need and ask is None and _triage_present(parties, roles, triage) is not None:
        ai = _triage_present(parties, roles, triage)              # المرحلة الأولى: الحضور من فرز كل محضر (بلا طلب)
    elif need and written:
        joined = '\n'.join(f"[{c['label']}] {c['segment']}" for c in written)
        key = hashlib.sha1(json.dumps([parties, joined], ensure_ascii=False).encode('utf-8')).hexdigest()
        if ai_prev.get('key') == key and ai_prev.get('present') is not None:
            ai = ai_prev                                          # لا نكرّر الطلب لنصوص لم تتغيّر
        elif ask:
            got = ai_attendance(joined, parties, ask)
            if got is None:
                ai_error = 'تعذّر استخراج الحضور بالذكاء الاصطناعي'
            else:
                ai = {'key': key, 'present': got}
        else:
            ai_error = 'لا يتوفر مزوّد ذكاء اصطناعي لقراءة نصوص الحضور'
    result = []
    for i, name in enumerate(parties):
        if str(i) in overrides:
            r = {'present': overrides[str(i)], 'certain': True, 'where': '', 'how': 'الخبير'}
        elif i in found:
            r = {'present': True, 'certain': True, 'where': found[i], 'how': 'قواعد'}
        elif ai is not None and i in ai['present']:
            r = {'present': True, 'certain': True, 'where': '', 'how': ai.get('how') or 'ذكاء اصطناعي'}
        elif ai is not None or (sections and not written and explicit_none):
            # الغياب لا يثبت بخانة فارغة أو غير مقروءة: إما رأي النموذج على نص حضور مكتوب، أو عبارة «لم يحضر أحد» صريحة
            r = {'present': False, 'certain': True, 'where': '',
                 'how': (ai.get('how') or 'ذكاء اصطناعي') if ai is not None else 'قواعد'}
        else:
            r = {'present': False, 'certain': False, 'where': '', 'how': ''}
        r.update(name=name, role=roles[i] if i < len(roles) else 'defendant')
        result.append(r)
    att.clear()
    att.update({'parties': parties, 'roles': roles, 'candidates': cands, 'result': result,
                'overrides': overrides, 'extracted': bool(parties) and all(r['certain'] for r in result)})
    if ai is not None and ai.get('key') != 'triage':
        att['ai'] = ai
    if ai_error:
        att['ai_error'] = ai_error
    return att


def set_attendance(base, data, index, present, ask=None):
    """تعديل الخبير لحضور طرف (present: True/False، أو None لإلغاء التعديل والعودة للاستخراج)."""
    att = data.setdefault('procedures', {}).setdefault('attendance', {})
    if not 0 <= int(index) < len(att.get('parties') or []):
        raise cm.StepError('الطرف غير موجود بين أطراف المحاضر.')
    ov = att.setdefault('overrides', {})
    if present is None:
        ov.pop(str(int(index)), None)
    else:
        ov[str(int(index))] = bool(present)
    return evaluate(base, data, ask)


def confirm_attendance(base, data, minute_no, present):
    """(توافق مع الشاشة القديمة) تأكيد الخبير حضور أطراف في محضر ← تعديل «حضر» لكل منهم."""
    att = data.setdefault('procedures', {}).setdefault('attendance', {})
    if not any(c.get('no') == int(minute_no) for c in att.get('candidates') or []):
        raise cm.StepError('المحضر غير موجود بين المحاضر المحلَّلة.')
    ov = att.setdefault('overrides', {})
    for i in present:
        ov[str(int(i))] = True
    return evaluate(base, data)


# ---------- نص الإجراءات: قالب تقرير النموذج (samples\…H2212338.docx) ----------
# النص في النموذج حرفياً:
#   «استلمنا ملف الدعوى بتاريخ 16/8/2021، وذلك لتنفيذ المأمورية السابق بيانها والواردة في الحكم التمهيدي الصادر
#    بجلسة 7/6/2021، وحددنا عدة جلسات حضرتها الشركة المدعى عليها وتخلف المدعى عليه عن الحضور رغم صحة اعلانه عن
#    طريق النيابة، واطلعنا على ما به من أوراق ومستندات، وتم مناقشة أطراف الدعوى، وتم حجز الدعوى للتقرير بتاريخ 8/11/2021.»
# المتغيّر: التواريخ الثلاثة + جملة الحضور. «عن طريق النيابة» لا تُكتب (طريقة الإعلان غير معروفة من البيانات).
PROCEDURES_TEMPLATE = ('استلمنا ملف الدعوى بتاريخ {received}، وذلك لتنفيذ المأمورية السابق بيانها والواردة في '
                       '{ruling}، وحددنا عدة جلسات {attendance}، واطلعنا على ما به '
                       'من أوراق ومستندات{discussed}{extras}، وتم حجز الدعوى للتقرير بتاريخ {booked}.')
# مكتبة الصياغة: نماذج_صياغة_الإجراءات.md في مجلد البرنامج تُقرأ عند كل توليد (drafting_library)؛ هذه احتياطية إن فُقد الملف.
STYLE_PATH = None                # الاختبارات تستبدله
DEFAULT_TEMPLATES = {
    'الأساسي': PROCEDURES_TEMPLATE,
    'الأحدث': ('استلمنا ملف الدعوى بتاريخ {received}، واطلعنا على ما جاء به من أوراق ومستندات وذلك لتنفيذ المأمورية '
               'الواردة بـ{ruling}، وبعد الاطلاع على الملف وأوراقه حددنا لمباشرة الدعوى عدة جلسات {attendance}{extras}، '
               'وتبين محاضر أعمالنا ما قمنا به من إجراءات وتم حجز الدعوى للتقرير بتاريخ {booked}.'),
    'إعادة_التوزيع': 'استلمنا ملف الدعوى بحالته بعد إعادة توزيعه بتاريخ {received}',
    'الانتقال': 'بجلسة الخبرة المؤرخة {date}، قامت الخبرة بالانتقال{who}، وتبين للخبرة التالي:',
    'الشهود': 'أقامت الخبرة جلسة استماع شهود بتاريخ {date}{who}، وتمت الجلسة على النحو التالي:',
    'إضافة_الانتقال': 'وبتاريخ {date} تم الانتقال والمعاينة{who}',
    'إضافة_الشهود': 'وبتاريخ {date} تم عقد جلسة لسماع الشهود{who}',
}


def load_templates():
    """({النوع: النص}, الصيغة المعتمدة) من ملف المكتبة؛ الناقص يُكمَّل من الاحتياطي."""
    rules, models = dl.load(dl.PROCEDURES_FILE, STYLE_PATH)
    tpl = dict(DEFAULT_TEMPLATES)
    for m in models:
        if m.get('type') in DEFAULT_TEMPLATES and '{' in m['text']:
            tpl[m['type']] = m['text']
    for k, v in tpl.items():                      # {sessions} قديم ← «عدة جلسات»: العدد لا يُكتب أبداً
        tpl[k] = v.replace('{sessions} ', 'عدة جلسات ').replace('{sessions}', 'عدة جلسات')
    mm = re.search(r'الصيغة المعتمدة\s*:\s*(\S+)', rules or '')
    choice = mm.group(1) if mm and mm.group(1) in tpl else 'الأساسي'
    return tpl, choice


DISCUSSED = '، وتم مناقشة أطراف الدعوى'          # لا تُكتب إلا عند ثبوت حضور طرف في محضر
_ORD_M = ('الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس', 'السابع', 'الثامن', 'التاسع', 'العاشر')


def _dmy(iso):
    """DD/MM/YYYY ← ISO أو DD/MM/YYYY؛ وإلا «[يُكتب]»."""
    v = (iso or '').strip()[:10]
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', v)
    if m:
        return f'{m.group(3)}/{m.group(2)}/{m.group(1)}'
    if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}', v):
        return v
    return TODO


def _is_company(name):
    try:
        import case_subject_telecom as st
        return st._is_company(name or '')
    except Exception:
        return False


def party_labels(result, data=None):
    """[(وصف الطرف في النص، مؤنث؟)] بترتيب result: «الشركة المدعية»، «المدعى عليه الثاني»…
    الجنس: الشركة مؤنث؛ وغيرها من صفته في صحيفة الدعوى (data['case']['genders'] — case_sort.party_gender) إن مُرّرت
    data، وإلا مذكّر افتراضياً (لا تخمين من الاسم؛ يعدّله الخبير). (2026-10-25: كانت «المدعى عليه … إعلانه» لمدعى عليها.)"""
    by_role = {}
    for r in result:
        by_role.setdefault(r['role'], []).append(r)
    out = []
    for r in result:
        same = by_role[r['role']]
        k = same.index(r)
        f = _is_company(r['name'])
        fem = f
        if not f and data is not None:
            import case_sort as cs
            fem = cs.party_gender(data, r['role'], k + 1) == 'f'
        base = 'المدعية' if r['role'] == 'plaintiff' and fem else 'المدعي' if r['role'] == 'plaintiff' else (
            'المدعى عليها' if fem else 'المدعى عليه')
        if len(same) > 1:
            base += ' ' + (_ORD_M[k] if not fem else _ORD_M[k] + 'ة' if k else 'الأولى').replace('الأولة', 'الأولى')
        out.append((('الشركة ' + base) if f else base, fem))
    return out


def _pron(group):
    if len(group) >= 3:
        return 'هم'
    if len(group) == 2:
        return 'هما'
    return 'ها' if group[0][1] else 'ه'


_NOTIFIED = re.compile(r'(?:رغم|الرغم\s+من)\s+صح[ةه]\s+(?:إ|ا)?علان(?:ه|ها|هم|هما)')
_DISCUSSED_RE = re.compile(r'مناقش[ةه]|افاد\s+الحاضر|أفاد\s+الحاضر')
def minutes_gate(data):
    """بوابة الاكتمال (نماذج_صياغة_الإجراءات.md): عدد المحاضر = الجلسات المنعقدة + 1.
    complete: لا نقص معروف. attendance_ok: الحضور/التخلف/المناقشة تُكتب؛ تتعطل مع نقص محضر
    (قد يكون الطرف حضره)، إلا إن كان الناقص محضر الاستلام (رقم 1) وحده فلا حضور فيه ولا يؤثر على الحضور، أو أكّد الخبير الحضور
    بنفسه (تعديل الحضور يدوياً) فيُكتب بتأكيده.
    الجلسات المجهولة (لم تُجلب بعد) تُعدّ بلا نقص معروف. note: «ينقص محضر N» أو ''."""
    s = data.get('sessions') or {}
    miss = int(s.get('missing_count') or 0)
    nums = [int(x) for x in s.get('missing') or [] if str(x).isdigit()]
    if not miss:
        return {'complete': True, 'attendance_ok': True, 'missing': 0, 'nums': [], 'note': ''}
    if nums:
        note = f"ينقص محضر {nums[0]}" if len(nums) == 1 else 'ينقص المحاضر ' + '، '.join(str(n) for n in nums)
    else:
        note = f'ينقص {count_word(miss)}'
    overridden = bool(((data.get('procedures') or {}).get('attendance') or {}).get('overrides'))
    return {'complete': False, 'attendance_ok': nums == [1] or overridden, 'missing': miss, 'nums': nums, 'note': note}


def evidence(texts_list):
    """ما يُثبته نص المحاضر المقروءة نفسه: هل ورد صحة الإعلان، وهل وردت مناقشة (يُحفظ في procedures.evidence)."""
    joined = chr(10).join(texts_list or [])
    return {'notified': bool(_NOTIFIED.search(joined)), 'discussed': bool(_DISCUSSED_RE.search(joined))}


def proven_facts(data, texts=None):
    """حقائق الإجراءات المثبتة من المحاضر المقروءة فقط (مصدر واحد للإجراءات وللتقرير v3):
    attended {role: bool} للأدوار المؤكدة، notified {role: bool} للمتخلفين، discussed، count، complete/note، all_present.
    texts: نصوص المحاضر (قائمة) لاستخراج الإعلان والمناقشة منها، وإلا يُستعمل ما حُفظ في procedures.evidence."""
    proc = data.get('procedures') or {}
    att = proc.get('attendance') or {}
    res = att.get('result') or []
    roles = [r['role'] for r in res]
    per = []
    for c in att.get('candidates') or []:
        present = sorted({roles[i] for i in c.get('present') or [] if i < len(roles)})
        per.append({'label': c.get('label'), 'present': present, 'text': c.get('segment') or ''})
    attended = {r['role']: bool(r.get('present')) for r in res if r.get('certain')}
    if not attended and per:
        for role in dict.fromkeys(att.get('roles') or roles):
            attended[role] = any(role in x['present'] for x in per)
    if texts is not None:
        joined = chr(10).join(texts)
        ev = {'notified': bool(_NOTIFIED.search(chr(10).join(x['text'] for x in per) + chr(10) + joined)),
              'discussed': bool(_DISCUSSED_RE.search(joined))}
    else:
        ev = proc.get('evidence') or {}
    gate = minutes_gate(data)
    notified = {role: bool(ev.get('notified')) for role, v in attended.items() if v is False}
    discussed = bool(ev.get('discussed'))
    if not gate['attendance_ok']:
        attended = {k: v for k, v in attended.items() if v}         # الغياب غير مثبت مع نقص محضر؛ الحضور المثبت يبقى
        notified, discussed = {}, False
    rows = (data.get('sessions') or {}).get('minutes') or []
    return {'count': len(rows) or len(texts or []) or len(per), 'sessions': per, 'attended': attended,
            'notified': notified, 'discussed': discussed, 'complete': gate['complete'],
            'attendance_ok': gate['attendance_ok'], 'missing_count': gate['missing'], 'gate_note': gate['note'],
            'all_present': gate['attendance_ok'] and bool(attended) and all(attended.values())
            and len(attended) == len(set(roles) or attended)}


def attendance_clause(result, complete=True, reason='', notified=None, data=None):
    """جملة الحضور بعد «وحددنا عدة جلسات»: «حضرها X» أو «حضرها X وتخلف Y عن الحضور رغم صحة إعلانه» (عدد الجلسات لا يُكتب).
    X من حضر في أي محضر مقروء. complete=False (محضر ناقص) ← '' (لا حضور ولا تخلف). غير مؤكد ← «[يُكتب]».
    notified: {role:bool} أو None (لم يثبت الإعلان ← بلا «رغم صحة إعلانه»). المدعية لا يُكتب تخلفها إلا بما ثبت ويقدّره الخبير."""
    if not complete:
        return ''
    if not result or not all(r['certain'] for r in result):
        return TODO
    labels = party_labels(result, data)
    notified = notified or {}
    join = lambda g: ' و'.join(x[0] for x in g)
    present = [labels[i] for i, r in enumerate(result) if r['present']]
    absent_n = [labels[i] for i, r in enumerate(result) if not r['present'] and notified.get(r['role'])]
    absent_u = [labels[i] for i, r in enumerate(result) if not r['present'] and not notified.get(r['role'])]
    parts = []
    if present:
        parts.append(f"{'حضرتها' if present[0][1] else 'حضرها'} {join(present)}")
    for grp, why in ((absent_n, True), (absent_u, False)):
        if grp:
            where = 'عن الحضور' if parts else 'عن حضورها'
            parts.append(f"{'تخلفت' if grp[0][1] else 'تخلف'} {join(grp)} {where}" + (f' رغم صحة إعلان{_pron(grp)}' if why else ''))
    return ' و'.join(parts)


_APPEAL_SUBJECT = re.compile(r'^\s*جاء(?:ت)?\s+(?:ال)?(?:مستأنف|طاعن)')
_EXTRA_KEYS = {
    'transfer': tuple(norm_ar(k) for k in ('الانتقال', 'انتقلت الخبرة', 'انتقلنا', 'معاينة')),
    'witness': tuple(norm_ar(k) for k in ('سماع شهود', 'استماع شهود', 'سماع الشهود', 'استماع الشهود')),
    'redistribution': tuple(norm_ar(k) for k in ('إعادة توزيع', 'اعادة توزيع')),
}


def is_appeal(data):
    mission = data.get('mission') or {}
    return (data.get('subject_type') == 'استئناف' or bool(_APPEAL_SUBJECT.match(data.get('subject') or ''))
            or 'حكم الاستئناف' in (mission.get('raw') or ''))


def detect_extras(minutes, texts, att):
    """الإضافات الاختيارية التي تثبت من نصوص المحاضر المقروءة: {'transfer':[{'date','present'}], 'witness':[…],
    'redistribution': bool}. present = فهارس الأطراف الحاضرين في ذلك المحضر (من قسم حضوره إن وُجد)."""
    out = {'transfer': [], 'witness': [], 'redistribution': False}
    by_name = {c.get('name'): c for c in (att or {}).get('candidates') or []}
    for m in minutes:
        paras = texts.get(m['path']) or []
        body = norm_ar(chr(10).join(paras[:80]))
        d = minute_date(paras)
        cand = by_name.get(m['name']) or {}
        for key in ('transfer', 'witness'):
            if d and any(k in body for k in _EXTRA_KEYS[key]):
                out[key].append({'date': d, 'present': list(cand.get('present') or []) if cand.get('has_section') else None})
        if any(k in body for k in _EXTRA_KEYS['redistribution']):
            out['redistribution'] = True
    return out


def _who(item, result, complete, data=None):
    """« بحضور X وتخلف Y عن الحضور على الرغم من صحة إعلانه»: الحاضرون من محضر ذلك اليوم، والتخلف فقط إن اكتملت المحاضر
    وثبت غياب الطرف في كل المحاضر وليس مدعياً (تقدير غياب المدعي للخبير)."""
    present = item.get('present')
    if not present or not result:
        return ''
    labels = party_labels(result, data)
    pres = [labels[i][0] for i in present if i < len(labels)]
    abs_ = [labels[i] for i, r in enumerate(result)
            if i not in present and complete and r['certain'] and not r['present'] and r['role'] != 'plaintiff']
    out = f" بحضور {' و'.join(pres)}" if pres else ''
    if abs_ and pres:
        out += f" وتخلف{'ت' if abs_[0][1] else ''} {' و'.join(x[0] for x in abs_)} عن الحضور على الرغم من صحة إعلان{_pron(abs_)}"
    return out


def _extras(data, tpl, result, complete):
    """(جمل داخل الفقرة، أقسام فرعية بعد الفقرة)."""
    ex = (data.get('procedures') or {}).get('extras') or {}
    inline, subs = [], []
    for key, add_key, head, sub_key in (('transfer', 'إضافة_الانتقال', 'الانتقال:', 'الانتقال'),
                                        ('witness', 'إضافة_الشهود', 'جلسة استماع شهود:', 'الشهود')):
        for it in ex.get(key) or []:
            who = _who(it, result, complete, data)
            inline.append(tpl[add_key].format(date=_dmy(it['date']), who=who))
            subs.append(head + chr(10) + tpl[sub_key].format(date=_dmy(it['date']), who=who))
    return ('، ' + '، '.join(inline)) if inline else '', subs


def _discussed_clause(result, facts, data=None):
    """«وتم مناقشة أطراف الدعوى» إن حضر الكل وثبتت المناقشة؛ «وتمت مناقشة الحاضر عن X» إن تخلف طرف؛ وإلا ''."""
    if not facts.get('discussed') or not facts.get('attendance_ok', True) or not result or not all(r['certain'] for r in result):
        return ''
    pres = [lab[0] for lab, r in zip(party_labels(result, data), result) if r['present']]
    if not pres:
        return ''
    if len(pres) == len(result):
        return DISCUSSED
    return '، وتمت مناقشة الحاضر عن ' + ' و'.join(pres) if len(pres) == 1 else '، وتمت مناقشة الحاضرين عن ' + ' و'.join(pres)


def compose(data, facts=None):
    """نص الإجراءات وملاحظاته — المسار الوحيد للكتابة (خطوة الإجراءات والتقرير v3). من الصيغة المعتمدة حرفياً:
    «وحددنا عدة جلسات» دائماً (العدد لا يُكتب أبداً)، ولا حضور ولا تخلف ولا مناقشة إلا بما يثبت في المحاضر المقروءة؛
    عند نقص محضر لا حضور ولا تخلف ولا مناقشة وتُضاف ملاحظة «ينقص محضر N».
    facts: ناتج proven_facts (للتقرير v3 يمرّره بنصوص المحاضر). يرجع (النص، [ملاحظات: ما ينقص]).
    تُكتب مما هو متاح، وتُعاد الكتابة تلقائياً مع كل قراءة جديدة ما لم يعدّل الخبير النص (re_evaluate)."""
    facts = facts or proven_facts(data)
    proc = data.get('procedures') or {}
    att = proc.get('attendance') or {}
    ok = facts.get('attendance_ok', True)
    tpl, choice = load_templates()
    result = att.get('result') or []
    extras, subs = _extras(data, tpl, result, ok)
    kind = 'حكم الاستئناف' if is_appeal(data) else 'الحكم التمهيدي'
    n = facts.get('count') or 0
    received, booked, judgment = (_dmy((proc.get('received') or {}).get('date')),
                                  _dmy((proc.get('booked') or {}).get('date')), _dmy(judgment_date(data)))
    text = tpl[choice].format(
        received=received, ruling=f"{kind} الصادر بجلسة {judgment}",
        attendance=attendance_clause(result, ok, '', facts.get('notified'), data),
        discussed=_discussed_clause(result, facts, data), extras=extras, booked=booked)
    text = re.sub(r' +([،.])', r'\1', text)               # «عدة جلسات ،» عند غياب جملة الحضور
    if (proc.get('extras') or {}).get('redistribution'):
        head = tpl['إعادة_التوزيع'].format(received=received)
        text = re.sub(r'^استلمنا ملف الدعوى بتاريخ ' + re.escape(received), lambda _m: head, text, count=1)
    notes = [name for name, v in (('تاريخ الاستلام', received), ('تاريخ الحكم التمهيدي', judgment), ('تاريخ الحجز', booked))
             if v == TODO]
    if not n:
        notes.append('محاضر الجلسات')
    if facts.get('gate_note'):
        notes.append(facts['gate_note'])
    return (chr(10) * 2).join([text] + subs), notes


def compose_text(data):
    return compose(data)[0]


def set_procedures_text(base, data, text):
    """تعديل الخبير لنص الإجراءات (حفظ تلقائي). بعد الاعتماد تبقى معتمدة وتُنبَّه الخطوات التالية."""
    text = (text or '').strip()
    proc = data.setdefault('procedures', {})
    if text == (proc.get('text') or '').strip():
        return cm.state(data, 'procedures')
    proc['text'] = text
    proc['edited'] = bool(text) and text != (proc.get('auto_text') or '').strip()
    proc.pop('changed_notice', None)
    if cm.state(data, 'procedures') in cm.OK_STATES:
        cm.mark_modified(data, 'procedures')
    _save(base, data)
    return cm.state(data, 'procedures')


# ---------- عدد المحاضر مقابل الجلسات ----------

def count_word(n):
    """«محضر واحد»، «محضرين»، «3 محاضر»، «20 محضراً»."""
    if n == 1:
        return 'محضر واحد'
    if n == 2:
        return 'محضرين'
    return f'{n} محاضر' if 3 <= n <= 10 else f'{n} محضراً'


def _sessions_word(n):
    return 'جلسة واحدة' if n == 1 else 'جلستان' if n == 2 else f'{n} جلسات' if 3 <= n <= 10 else f'{n} جلسة'


def compare_minutes(minutes, summary, texts=None):
    """يربط كل محضر برقم جلسته (من اسمه، وإلا بتاريخه داخل النص) ويحسب الناقص.
    يرجع dict: minutes (مع no/date)، missing (أرقام)، missing_count، missing_dates (ISO)، exact (الربط دقيق؟)."""
    expected = summary.get('expected_minutes') or 0
    dates = summary.get('dates') or {}
    covered, rows, loose = {}, [], []
    for m in minutes:
        paras = (texts or {}).get(m['path']) or []
        row = {'no': m.get('no'), 'date': '', 'file': m['path'], 'name': m['name'], 'source': m.get('source', ''),
               'md': '', 'text_date': m.get('date') or minute_date(paras), 'no_source': m.get('no_source', '')}
        rows.append(row)
        if row['no'] is not None and row['no'] not in covered:
            covered[row['no']] = row
            row['date'] = dates.get(row['no'], '')
        else:
            loose.append(row)
    for row in list(loose):
        k = next((n for n in sorted(dates) if dates[n] and dates[n] == row['text_date'] and n not in covered), None)
        if k is not None:
            covered[k] = row
            row['date'] = dates[k]
            loose.remove(row)
    for row in loose:
        row['date'] = row['date'] or row['text_date']
    missing = [n for n in range(1, expected + 1) if n not in covered]
    exact = not loose
    return {'minutes': rows, 'missing': missing if exact else [], 'missing_count': max(0, expected - len(rows)),
            'missing_dates': [dates.get(n, '') for n in missing if dates.get(n)] if exact else [], 'exact': exact}


# ---------- التحقق والحالة ----------

def judgment_date(data):
    """تاريخ الحكم التمهيدي: المحفوظ، وإلا تاريخ حكم الإحالة المعتمد نفسه (لا يلزم المحضر)."""
    jd = ((data.get('procedures') or {}).get('judgment') or {}).get('date')
    return jd or ((data.get('judgment_pick') or {}).get('date') or '')


def build_checks(data):
    """[{'key','ok','text'}]: الاستلام، الحجز، الحضور، المحاضر مقابل الجلسات (+ سطر معلومة للحكم). دالة صرفة."""
    proc = data.get('procedures') or {}
    s = data.get('sessions') or {}
    rec, bk = proc.get('received') or {}, proc.get('booked') or {}
    att = proc.get('attendance') or {}
    checks = [
        {'key': 'received', 'ok': bool(rec.get('date')),
         'text': f"تاريخ الاستلام: {_dmy(rec['date'])}" if rec.get('date') else 'تاريخ الاستلام: غير متوفر من النظام'},
        {'key': 'booked', 'ok': bool(bk.get('date')),
         'text': (f"تاريخ الحجز: {_dmy(bk['date'])}" + (f" ({bk['note']})" if bk.get('note') else ''))
         if bk.get('date') else 'تاريخ الحجز: لم يُعثر عليه في النظام ولا في المحاضر'},
    ]
    result = att.get('result') or []
    if not s.get('minutes'):
        ok, text = False, 'الحضور: لا محاضر لاستخراجه منها'
    elif not result:
        ok, text = False, 'الحضور: لم تُعرف أطراف الدعوى من المحاضر ولا من بيانات القضية'
    else:
        parts = []
        for (label, _f), r in zip(party_labels(result, data), result):
            if not r['certain']:
                parts.append(f'{label}: لم يتأكد')
            else:
                parts.append(f"{label}: {'حضر' if r['present'] else 'لم يحضر'}"
                             + (f" ({r['where']})" if r.get('where') else '')
                             + (' — بتعديل الخبير' if r['how'] == 'الخبير' else ''))
        ok = bool(att.get('extracted'))
        text = 'الحضور: ' + '، '.join(parts)
        if not ok:
            why = att.get('ai_error') or ('لا يوجد قسم حضور مقروء في المحاضر'
                                          if not any(c['has_section'] for c in att.get('candidates') or []) else '')
            text += (f' — {why}' if why else '') + ' (حدّده من «تعديل»)'
    checks.append({'key': 'attendance', 'ok': ok, 'text': text})
    n_min = len(s.get('minutes') or [])
    expected = s.get('expected_minutes')
    if s.get('source') in (None, '') and not expected:
        ok, text = False, (f"المحاضر: {_seen(n_min)} — "
                           f"{proc.get('fetch_error') or 'تعذّر التحقق: لم تُجلب جلسات النظام'}")
    else:
        fut = s.get('future') or 0
        head = (f"في النظام {_sessions_word(expected)}" + (f' (+{fut} قادمة)' if fut else '')
                + f"، {_seen(n_min)}")
        miss = s.get('missing_count') or 0
        if miss:                                     # ملاحظة لا نقص: الإجراءات تُكتب مما قُدّم
            nums = s.get('missing') or []
            rest = (f" — المتبقي: الجلسة رقم ({'، '.join(str(n) for n in nums)})" if nums
                    else f" — ينقص {count_word(miss)}")
            if nums == [1]:
                rest += ' وهي جلسة الاستلام (لا حضور فيها، وتاريخها من النظام) — لا تؤثر'
            ok, text = None, head + rest
        else:
            ok, text = True, head
        if s.get('source') == 'stored':
            text += ' — من آخر جلب محفوظ'
    checks.append({'key': 'compare', 'ok': ok, 'text': text})
    for w in s.get('minute_warnings') or []:
        checks.append({'key': 'order', 'ok': None, 'text': '⚠ ' + w})
    jd = judgment_date(data)
    checks.append({'key': 'judgment', 'ok': None,
                   'text': f'تاريخ الحكم التمهيدي: {_dmy(jd)}' if jd else 'تاريخ الحكم التمهيدي: غير محفوظ — «[يُكتب]» في النص'})
    return checks


def checks_text(data):
    return '\n'.join(('✓ ' if c['ok'] else '× ' if c['ok'] is False else '• ') + c['text']
                     for c in build_checks(data))


def missing_line(data):
    """سطر واحد بما ينقص بالتحديد (فارغ = اكتملت)."""
    out = []
    for c in build_checks(data):
        if c['ok'] is False:
            out.append(c['text'])
    return '؛ '.join(out)


def summary_line(data):
    """«تم الاطلاع على N محضر» لرأس الخطوة."""
    return _seen(len((data.get('sessions') or {}).get('minutes') or []))


def _seen(n):
    return f'تم الاطلاع على {count_word(n)}' if n else 'لم يُعثر على أي محضر'


def _save(base, data):
    cw.write_case_json(base, data)
    try:
        case_memory.update_section(base, data, 'status', 'sessions')
    except Exception:
        pass       # الذاكرة مشتقة: فشلها لا يُفشل الخطوة


def re_evaluate(base, data):
    """يعيد حساب النص والحالة من البيانات المخزَّنة. اكتملت ← معتمدة تلقائياً (reviewed)؛ وإلا needs_input."""
    proc = data.setdefault('procedures', {})
    if proc.get('edited_by') == 'rewrite':      # نص ألّفه الذكاء سابقاً (ليس تعديل الخبير) ← يُستبدل بالصيغة المعتمدة
        proc.pop('edited_by', None)
        proc['edited'] = False
    auto = compose_text(data)
    was_ok = cm.state(data, 'procedures') in cm.OK_STATES
    changed = auto != proc.get('auto_text')
    proc['auto_text'] = auto
    keep_stage2 = (proc.get('source') == 'stage2' and proc.get('stage2_auto') == auto       # نص المرحلة الثانية المتحقَّق
                   and (proc.get('text') or '').strip() and not proc.get('edited'))      # يبقى ما دامت الحقائق نفسها
    if keep_stage2:
        pass
    elif not proc.get('edited') or not (proc.get('text') or '').strip():
        if changed and was_ok and (proc.get('text') or '').strip() and auto != proc.get('text'):
            proc['changed_notice'] = 'تغيّرت الإجراءات بعد قراءة المحاضر من جديد (محضر جديد أو معطيات تغيّرت)'
        proc['text'], proc['edited'] = auto, False
    elif changed and (proc.get('text') or '').strip() != auto:
        # نص عدّله الخبير بيده لا يُستبدل تلقائياً أبداً؛ يُعلَم فقط أن المعطيات تغيّرت
        proc['changed_notice'] = ('تغيّرت الإجراءات المستخرجة من المحاضر بعد تعديلك للنص — نصك لم يُمسّ؛ '
                                  'اضغط «إعادة الكتابة» إن أردت تحديثه')
    gate_note = minutes_gate(data)['note']
    proc['gate_note'] = gate_note
    miss = missing_line(data)
    cur = cm.state(data, 'procedures')
    if (data.get('sessions') or {}).get('minutes') and (proc.get('text') or '').strip():
        miss = ''                                    # ما ينقص ملاحظة في البطاقة لا يمنع الاعتماد ولا الإصدار
    if not miss:
        msg = summary_line(data) + (f' — {gate_note}' if gate_note else '') + ' — اكتملت المعلومات واعتُمدت تلقائياً'
        if proc.get('edited') and changed:
            msg += ' (تغيّرت المعطيات بعد تعديلك للنص — راجعه)'
        if cur not in ('needs_input', 'done', 'reviewed'):
            cm.set_step(data, 'procedures', 'needs_input')
        if cur != 'done' and cur != 'reviewed':
            cm.set_step(data, 'procedures', 'done', msg)
        cm.set_step(data, 'procedures', 'reviewed', msg, auto=True)
        if was_ok and changed and not proc.get('edited'):
            cm.mark_modified(data, 'procedures')         # النص تغيّر ← ينبّه البحث
    else:
        cm.set_step(data, 'procedures', 'needs_input', f'{summary_line(data)} — ينقص: {miss}')
    _save(base, data)
    return cm.state(data, 'procedures')


def _call(fn):
    try:
        return fn(), ''
    except Exception as e:
        return None, str(e) or e.__class__.__name__


def _default_get_case(caso_no):
    import case_db
    return case_db.get_case(caso_no)


def evaluate(base, data, ask=None, root=None):
    """يجمع المحاضر ويقارنها بالجلسات المحفوظة ويستخرج الحضور ثم يعيد الحساب (بلا شبكة)."""
    proc = data.setdefault('procedures', {})
    minutes = find_minutes(data['caso_no'], root or proc.get('root'), base, proc.get('excluded') or ())
    texts = minute_texts(minutes)
    s = data['sessions']
    summary = {'expected_minutes': s.get('expected_minutes') or 0,
               'dates': {int(k): v for k, v in (s.get('dates') or {}).items()}}
    cmp_ = compare_minutes(minutes, summary, texts)
    s.update(minutes=cmp_['minutes'], missing=cmp_['missing'], missing_count=cmp_['missing_count'],
             missing_dates=cmp_['missing_dates'])
    if not s.get('expected_minutes'):
        s['missing_count'] = 0
    s['minute_warnings'] = order_warnings(minutes)
    tri = triage_minutes(base, minutes)                # المرحلة الأولى: حضور كل محضر وتاريخ حجزه من فرزه (بلا طلب)
    att = analyze_attendance(data, minutes, ask, texts, triage=tri)
    proc['extras'] = detect_extras(minutes, texts, att)
    proc['evidence'] = evidence([chr(10).join(texts.get(m['path']) or []) for m in minutes])
    try:                                       # الجلسات من المحاضر بالذكاء، ولا يُقبل إلا ما له دليل حرفي
        import case_minutes_ai as mai
        ai = mai.extract(proc, minutes, texts, att.get('parties') or [], ask)
        if ai:
            mai.merge_attendance(att, ai)
            mai.merge_extras(proc['extras'], ai)
            s['details'] = [{k: r.get(k) for k in ('name', 'number', 'date', 'events', 'visit', 'inspection', 'witnesses')}
                            | {'present': [p['index'] for p in r['present']], 'absent': [p['index'] for p in r['absent']]}
                            for r in ai['records']]
    except Exception as e:
        proc['minutes_ai_error'] = f'تعذّر استخراج الجلسات من المحاضر: {e}'
        ai = None
    bk = proc.get('booked') or {}
    if not bk.get('date') or bk.get('source') == 'المحضر':     # تاريخ الحجز: النظام أولاً، وإلا من المحاضر
        try:
            import case_minutes_ai as mai
            if ai is None and tri:                         # تاريخ الحجز المتحقَّق في فرز المحضر (بلا طلب)
                ai = {'records': [{'booking': r['booking'], 'number': r.get('no'), 'name': r['name']}
                                  for r in tri['records'] if r.get('booking')]}
            got = mai.booking_from_minutes(minutes, texts, ai)
        except Exception:
            got = {}
        if got:
            proc['booked'] = {'date': got['date'], 'source': 'المحضر', 'minute': got['minute'],
                              'minute_name': got['name'], 'method': got['method'], 'note': got['note']}
        elif bk.get('source') == 'المحضر':
            proc['booked'] = {'date': '', 'source': ''}
    st = re_evaluate(base, data)
    try:                                       # المرفقات تُقرأ من المحاضر ← تتجدد معها
        import case_attachments
        case_attachments.sync_attachments(base, data)
    except Exception:
        pass
    return st


def run_procedures(base, data, fetch, fallbacks=(), root=None, today=None, force=False,
                   flow=None, ask=None, get_case=None):
    """fetch: الجلسات الحيّة (تقويم النظام). flow: دالة ترجع {'sessions','received','booked'} من سجل الحركة.
    fallbacks: مصادر بديلة للجلسات. ask: ذكاء اصطناعي لاستكمال الحضور. get_case: صف case_db (تاريخ الحكم).
    خطوة مكتملة لا تُعاد إلا مع force. لا تنقل خطوة معتمدة إلى «قيد التنفيذ» (حتى لا تُنبَّه التالية بلا تغيير)."""
    if cm.state(data, 'procedures') in cm.OK_STATES and not force:
        return cm.state(data, 'procedures')
    if cm.state(data, 'procedures') not in cm.OK_STATES:
        cm.set_step(data, 'procedures', 'running')
    proc = data.setdefault('procedures', {})
    if root:
        proc['root'] = root
    errors, cal, source = [], None, ''
    for name, fn in (('live', fetch),) + tuple((getattr(f, '__name__', 'fallback'), f) for f in fallbacks):
        if fn is None:
            continue
        res, err = _call(fn)
        if err:
            errors.append(err)
        elif res:                                   # قائمة فارغة ليست نجاحاً: جرّب المصدر التالي
            cal, source = res, 'live' if name == 'live' else 'local'
            break
    fl, ferr = _call(flow) if flow else (None, '')
    if ferr:
        errors.append('سجل الحركة: ' + ferr)
    fl = fl or {}
    sessions = merge_sessions(cal, fl.get('sessions'))
    if fl.get('sessions'):
        source = (source + '+flow') if source else 'flow'
    s = data['sessions']
    if sessions:
        summary = summarize_sessions(sessions, today)
        s.update(count_system=summary['count_system'], expected_minutes=summary['expected_minutes'],
                 future=summary['future'], dates={str(k): v for k, v in summary['dates'].items()}, source=source)
        proc.pop('fetch_error', None)
    elif s.get('expected_minutes'):
        s['source'] = 'stored'
        proc.pop('fetch_error', None)
    else:
        proc['fetch_error'] = 'تعذّر التحقق: ' + (errors[0] if errors else 'لم يُرجع النظام أي جلسة لهذه القضية')
        s.update(source='', expected_minutes=0)
    case_recv = ((data.get('case') or {}).get('received_date') or '')[:10]
    recv = case_recv or fl.get('received') or (proc.get('received') or {}).get('date', '')
    booked = (fl.get('booked')
              or next((x['date'] for x in sorted(sessions, key=lambda x: x['date'], reverse=True)
                       if x.get('booking') and x.get('date')), '')
              or (proc.get('booked') or {}).get('date', ''))
    proc['received'] = {'date': recv, 'source': 'القضية' if case_recv else 'سجل الحركة' if fl.get('received') else 'محفوظ'}
    old_bk = proc.get('booked') or {}
    if booked and old_bk.get('source') == 'المحضر' and booked == old_bk.get('date') and not (
            fl.get('booked') or any(x.get('booking') and x.get('date') for x in sessions)):
        pass                                        # المحفوظ من المحضر يبقى بعلامته
    else:
        proc['booked'] = {'date': booked, 'source': 'سجل الحركة/التقويم' if booked else ''}
    try:
        row = (get_case or _default_get_case)(data['caso_no']) or {}
    except Exception:
        row = {}
    jd = row.get('judgment_date') or (data.get('case') or {}).get('judgment_date') or (proc.get('judgment') or {}).get('date', '')
    proc['judgment'] = {'date': jd}
    return evaluate(base, data, ask, root)


def add_minute(base, data, src_path, number=None, root=None, ask=None):
    """«إضافة محضر آخر»: ينسخ الملف (docx/pdf/صورة/md/txt) إلى 01_اصول\\محاضر داخل مجلد القضية (لا يكتب فوق
    موجود ولا يمسّ مجلد المحاضر الأصلي)، ثم يعيد المقارنة والحضور. number: يسمّيه N.ext ليُربط بالجلسة N."""
    if not os.path.isfile(src_path):
        raise cm.StepError('الملف غير موجود.')
    name = os.path.basename(src_path)
    ext = os.path.splitext(name)[1].lower()
    if ext not in MINUTE_EXTS:
        raise cm.StepError('نوع الملف غير مقبول — المقبول: Word وPDF والصور وmd/txt.')
    folder = os.path.join(base, EXTRA_DIR)
    os.makedirs(folder, exist_ok=True)
    if number is not None:
        dst_name = f'محضر الخبرة رقم {int(number)}{ext}'
    else:
        import case_folder
        dst_name = case_folder.minute_file_name(src_path)        # الرقم من نص المحضر لا ترتيب التحميل
    dst = os.path.join(folder, dst_name)
    if os.path.exists(dst):
        if number is not None:
            raise cm.StepError(f'المحضر رقم {number} مضاف أصلاً ولن يُستبدل.')
        stem = os.path.splitext(dst_name)[0]
        i = 2
        while os.path.exists(dst):
            dst = os.path.join(folder, f'{stem} ({i}){ext}')
            i += 1
    shutil.copy2(src_path, dst)
    proc = data.setdefault('procedures', {})
    proc['excluded'] = [x for x in proc.get('excluded') or [] if os.path.normcase(x) != os.path.normcase(dst)]
    return evaluate(base, data, ask, root)


def exclude_minute(base, data, path, excluded=True, ask=None):
    """«تعديل»: استبعاد ملف أُخذ بالخطأ (أو إعادته). لا يحذف شيئاً من القرص."""
    proc = data.setdefault('procedures', {})
    cur = [x for x in proc.get('excluded') or [] if os.path.normcase(x) != os.path.normcase(path)]
    if excluded:
        cur.append(path)
    proc['excluded'] = cur
    return evaluate(base, data, ask)


def all_candidates(data, root=None, base=None):
    """للشاشة «تعديل»: [(المسار، الاسم، مستبعد؟)] لكل ما وُجد، بما فيه المستبعد."""
    proc = data.get('procedures') or {}
    found = find_minutes(data['caso_no'], root or proc.get('root'), base, ())
    ex = {os.path.normcase(os.path.abspath(x)) for x in proc.get('excluded') or []}
    return [(m['path'], m['name'], os.path.normcase(os.path.abspath(m['path'])) in ex) for m in found]
