# ===== case_layout.py — بنية مجلد القضية المختصرة + ترحيل القضايا القديمة إليها (2026-10-21) =====
# <رقم الخبرة>/
#   مستندات_النظام/  حكم الإحالة، صحيفة الدعوى، محاضر الخبرة، تقارير الخبراء السابقة
#   حوافظ/  مذكرات/  أخرى/ (ما لم يُعرف أو ملف مختلط)
#   markdown/         نسخة مطابقة لكل ما سبق بنفس الأسماء (.md)
#   الملخص.md         مرجع كل الخطوات (case_summary)
#   التقرير/           مخرجات التقرير (Word)
#   _نظام/ (مخفي)      case.json(.bak) وmanifest والحقائق والسجلات والفهرس والعقود ومسودات التقرير
# الترحيل: نقل داخل مجلد القضية نفسه (os.replace) بعد التحقق من sha1 قبل/بعد، وسجل لكل نقل في
# _نظام/سجلات/ترحيل_البنية.log، ولا حذف لأي محتوى (الاسم المكرر يأخذ « (2)»)؛ تُحذف المجلدات القديمة الفارغة فقط.
# المراجع داخل case.json (المسارات النسبية والمطلقة) تُحدَّث للمسارات الجديدة.
import hashlib
import json
import os
import re
from datetime import datetime

SYS = '_نظام'
SYSDOCS, PORTF, MEMOS, OTHER = 'مستندات_النظام', 'حوافظ', 'مذكرات', 'أخرى'
ORIG_FOLDERS = (SYSDOCS, PORTF, MEMOS, OTHER)
MD_DIR = 'markdown'
REPORT_DIR = 'التقرير'
SUMMARY = 'الملخص.md'

CASE_FILE = f'{SYS}/case.json'
MANIFEST = f'{SYS}/manifest.json'
FACTS_DIR = f'{SYS}/03_حقائق'
WORK_DIR = f'{SYS}/04_تقرير'          # مسودات التقرير (md)؛ ملف Word النهائي في التقرير/
SOURCES_DIR = f'{SYS}/مصادر'
LOGS_DIR = f'{SYS}/سجلات'
LEGACY_ASSETS = f'{SYS}/01_اصول'      # أصول القضايا القديمة جداً (قبل 2026-10-18)؛ تُقرأ فقط
LEGACY_MD = f'{SYS}/02_markdown'
INDEX = f'{SYS}/فهرس_المستندات.md'
CONTRACTS = f'{SYS}/العقود.md'
MIGRATION_LOG = f'{LOGS_DIR}/ترحيل_البنية.log'
MIGRATION_JSON = f'{LOGS_DIR}/ترحيل_البنية.json'
LAYOUT_VERSION = 3

# البنية السابقة: مجلدات الأصول (2026-10-18) ومجلدات النظام المرقّمة
OLD_MINUTES, OLD_JUDGMENT, OLD_PLAINT, OLD_OTHER, OLD_PRIOR = (
    'محاضر', 'حكم_الإحالة', 'صحيفة_الدعوى', 'مستندات_أخرى', 'تقارير_سابقة')
OLD_ORIG = (OLD_MINUTES, OLD_JUDGMENT, OLD_PLAINT, OLD_OTHER, OLD_PRIOR)
# (القديم، الجديد) — الترتيب مهم: الأطول أولاً
SYS_PREFIXES = (('00_نظام/', f'{SYS}/'), ('01_اصول/', f'{LEGACY_ASSETS}/'), ('02_markdown/', f'{LEGACY_MD}/'),
                ('03_حقائق/', f'{FACTS_DIR}/'), ('04_تقرير/', f'{WORK_DIR}/'))
ROOT_SYS_FILES = {'case.json': CASE_FILE, 'case.json.bak': CASE_FILE + '.bak',
                  'فهرس_المستندات.md': INDEX, 'العقود.md': CONTRACTS}


def _now():
    return datetime.now().isoformat(timespec='seconds')


def sys_path(base, rel=''):
    return os.path.join(base, *rel.split('/')) if rel else base


def hide(path):
    """FILE_ATTRIBUTE_HIDDEN على ويندوز (لا شيء في غيره)."""
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs != -1 and not attrs & 0x2:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs | 0x2)
    except Exception:
        pass


def ensure(base):
    """ينشئ البنية الجديدة الناقصة فقط (لا يكتب فوق شيء) ويخفي _نظام."""
    for d in ORIG_FOLDERS:
        os.makedirs(os.path.join(base, d), exist_ok=True)
        os.makedirs(os.path.join(base, MD_DIR, d), exist_ok=True)
    for d in (SYS, FACTS_DIR, WORK_DIR, SOURCES_DIR, LOGS_DIR):
        os.makedirs(sys_path(base, d), exist_ok=True)
    os.makedirs(os.path.join(base, REPORT_DIR), exist_ok=True)
    hide(os.path.join(base, SYS))


# ---------- الكشف ----------

def needs_migration(base):
    if not os.path.isdir(base):
        return False
    if os.path.isfile(os.path.join(base, 'case.json')) or os.path.isfile(os.path.join(base, MD_DIR, '.manifest.json')):
        return True
    return any(os.path.isdir(os.path.join(base, d)) for d in OLD_ORIG + tuple(p[:-1] for p, _ in SYS_PREFIXES))


# ---------- النقل الآمن ----------

def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def unique(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f'{stem} ({i}){ext}'):
        i += 1
    return f'{stem} ({i}){ext}'


class MoveError(Exception):
    pass


def safe_move(src, dst, log=None):
    """ينقل ملفاً (إعادة تسمية) بعد حساب البصمة، ويتحقق منها بعد النقل. لا يكتب فوق موجود: الاسم المكرر « (2)».
    المطابق بالبصمة في الوجهة نفسها لا يُنقل فوقه ولا يُحذف الأصل (يأخذ اسماً جديداً). يرجع المسار الفعلي."""
    before = sha1(src)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    dst = unique(dst)
    os.replace(src, dst)
    after = sha1(dst)
    if after != before:                                  # لا يحدث مع إعادة التسمية؛ احتياط صريح
        raise MoveError(f'اختلفت البصمة بعد النقل: {src} → {dst}')
    if log is not None:
        log.append({'from': src, 'to': dst, 'sha1': before, 'at': _now()})
    return dst


def _rel(base, p):
    return os.path.relpath(p, base).replace('\\', '/')


def _remove_empty_dirs(base, roots):
    """يحذف المجلدات الفارغة فقط (من الأعمق)، ولا يمسّ أي ملف."""
    removed = []
    for r in roots:
        top = os.path.join(base, r)
        if not os.path.isdir(top):
            continue
        for dirpath, dirs, files in os.walk(top, topdown=False):
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
                    removed.append(_rel(base, dirpath))
            except OSError:
                pass
    return removed


# ---------- تسمية مستندات النظام عند الترحيل ----------

def _minute_name(path, fallback_stem):
    try:
        import case_procedures as cp
        no = cp.minute_meta(path).get('no')
    except Exception:
        no = None
    if no is None:
        try:
            import case_procedures as cp
            no = cp._number(os.path.basename(path))
        except Exception:
            no = None
    return f'محضر الخبرة رقم {no}' if no is not None else f'محضر الخبرة - {fallback_stem}'


def _system_target(base, old_top, path, referral_rel, plaint_rel):
    name = os.path.basename(path)
    stem, ext = os.path.splitext(name)
    rel = _rel(base, path)
    if old_top == OLD_MINUTES:
        new = _minute_name(path, stem)
    elif old_top == OLD_JUDGMENT:
        new = 'حكم الإحالة' if rel == referral_rel else (stem if stem.startswith('حكم') else f'حكم - {stem}')
    elif old_top == OLD_PLAINT:
        new = 'صحيفة الدعوى' if rel == plaint_rel else (stem if stem.startswith('صحيفة') else f'صحيفة الدعوى - {stem}')
    else:
        new = stem if stem.startswith('تقرير') else f'تقرير خبرة سابق - {stem}'
    return os.path.join(base, SYSDOCS, new + ext)


def _newest(base, folder):
    best = None
    for dp, _, fs in os.walk(os.path.join(base, folder)):
        for n in fs:
            p = os.path.join(dp, n)
            if n.startswith(('~$', '.')):
                continue
            t = os.path.getmtime(p)
            if best is None or t > best[0]:
                best = (t, _rel(base, p))
    return best[1] if best else None


# ---------- إعادة كتابة المراجع ----------

def rewrite_refs(obj, mapping, base=None):
    """يستبدل كل مسار قديم في case.json بالجديد: القيمة المطابقة تماماً، أو التي تبدأ ببادئة مجلد نظام قديمة،
    أو مساراً مطلقاً داخل مجلد القضية. يشمل مفاتيح القواميس. mapping: {قديم_نسبي: جديد_نسبي}."""
    abs_map = {}
    if base:
        for a, b in mapping.items():
            for sep in ('\\', '/'):
                abs_map[os.path.join(base, a).replace('/', sep).replace('\\', sep)] = \
                    os.path.join(base, b).replace('/', sep).replace('\\', sep)

    def fix(s):
        if not isinstance(s, str) or not s:
            return s
        if s in mapping:
            return mapping[s]
        if s in abs_map:
            return abs_map[s]
        for old, new in SYS_PREFIXES:
            if s.startswith(old):
                return new + s[len(old):]
            if base and (s.startswith(os.path.join(base, old[:-1])) or s.startswith(base.replace('\\', '/') + '/' + old)):
                return s.replace(old[:-1], new[:-1], 1)
        return s

    if isinstance(obj, dict):
        return {fix(k): rewrite_refs(v, mapping, base) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rewrite_refs(v, mapping, base) for v in obj]
    return fix(obj)


# ---------- الترحيل ----------

def migrate(base):
    """يرحّل قضية من البنية القديمة إلى الجديدة. آمن للتكرار (لا يفعل شيئاً إن لم يجد قديماً).
    يرجع {'moved': [(من، إلى)], 'removed_dirs': [...], 'errors': [...]} أو None إن لم يلزم شيء."""
    if not needs_migration(base):
        ensure(base)
        return None
    ensure(base)
    log, errors, mapping = [], [], {}

    def move(src_rel, dst_rel):
        src = os.path.join(base, *src_rel.split('/'))
        if not os.path.isfile(src):
            return None
        try:
            got = safe_move(src, os.path.join(base, *dst_rel.split('/')), log)
        except (OSError, MoveError) as e:
            errors.append(f'{src_rel}: {e}')
            return None
        new_rel = _rel(base, got)
        mapping[src_rel] = new_rel
        return new_rel

    # 1) ملفات نظام الجذر ← _نظام
    for old, new in ROOT_SYS_FILES.items():
        if os.path.isfile(os.path.join(base, old)):
            move(old, new)
    # 2) مجلدات النظام المرقّمة ← _نظام/...  (04_تقرير: ملفات Word ← التقرير/)
    for old, new in SYS_PREFIXES:
        top = os.path.join(base, old[:-1])
        if not os.path.isdir(top):
            continue
        for dp, _, fs in os.walk(top):
            for n in fs:
                rel = _rel(base, os.path.join(dp, n))
                if old == '04_تقرير/' and n.lower().endswith('.docx') and '/' not in rel[len(old):]:
                    move(rel, f'{REPORT_DIR}/{n}')
                else:
                    move(rel, new + rel[len(old):])
    # 3) case.json القديم (بعد نقله) يُقرأ لمعرفة حكم الإحالة والصحيفة المعتمدَين
    data = _load_json(sys_path(base, CASE_FILE)) or {}
    src = data.get('sources') or {}
    referral_rel = ((data.get('judgment_pick') or {}).get('file') or (src.get('judgment') or {}).get('file')
                    or _newest(base, OLD_JUDGMENT))
    plaint_rel = (src.get('claim') or {}).get('file') or _newest(base, OLD_PLAINT)
    # 4) الأصول ← المجلدات الأربعة، ومشتقاتها في markdown تتبعها بنفس الاسم
    old_man = _load_json(os.path.join(base, MD_DIR, '.manifest.json')) or {}
    if old_man and os.path.isfile(os.path.join(base, MD_DIR, '.manifest.json')):
        move(f'{MD_DIR}/.manifest.json', MANIFEST)
    man_files = (old_man.get('files') if isinstance(old_man.get('files'), dict) else {}) or {}
    for top in OLD_ORIG:
        root = os.path.join(base, top)
        if not os.path.isdir(root):
            continue
        for dp, _, fs in os.walk(root):
            for n in sorted(fs):
                p = os.path.join(dp, n)
                rel = _rel(base, p)
                if top == OLD_OTHER:
                    dst = os.path.join(base, OTHER, *rel.split('/')[1:])
                else:
                    dst = _system_target(base, top, p, referral_rel, plaint_rel)
                new_rel = move(rel, _rel(base, dst))
                if not new_rel:
                    continue
                old_md = (man_files.get(rel) or {}).get('md') or f"{MD_DIR}/{os.path.splitext(rel)[0]}.md"
                new_md = f"{MD_DIR}/{os.path.splitext(new_rel)[0]}.md"
                if os.path.isfile(os.path.join(base, *old_md.split('/'))):
                    got = move(old_md, new_md)
                    new_md = got or new_md
                if rel in man_files:
                    e = dict(man_files.pop(rel))
                    e['md'] = new_md
                    man_files[new_rel] = e
    # 5) أي ملف بقي في markdown/<مجلد قديم> (مشتق بلا أصل) ← markdown/أخرى (لا يُحذف)
    for top in OLD_ORIG:
        root = os.path.join(base, MD_DIR, top)
        for dp, _, fs in os.walk(root) if os.path.isdir(root) else ():
            for n in fs:
                rel = _rel(base, os.path.join(dp, n))
                move(rel, f'{MD_DIR}/{OTHER}/' + rel[len(f'{MD_DIR}/{top}/'):])
    # 6) نسخة كما هي من case.json وmanifest قبل إعادة كتابة مراجعهما (لا فقد لأي محتوى)
    keep = sys_path(base, f'{LOGS_DIR}/قبل_الترحيل')
    for src_rel, name in ((CASE_FILE, 'case.json'), (CASE_FILE + '.bak', 'case.json.bak'), (MANIFEST, 'manifest.json')):
        src_p = sys_path(base, src_rel)
        if os.path.isfile(src_p):
            os.makedirs(keep, exist_ok=True)
            dst_p = unique(os.path.join(keep, name))
            with open(src_p, 'rb') as a, open(dst_p, 'wb') as b:
                b.write(a.read())
    # 7) manifest الجديد بالمفاتيح الجديدة
    if old_man:
        old_man['files'] = man_files
        old_man['layout'] = LAYOUT_VERSION
        _write_json(sys_path(base, MANIFEST), old_man)
    # 8) المراجع في case.json
    if data:
        data = rewrite_refs(data, mapping, base)
        data['layout'] = {'version': LAYOUT_VERSION, 'migrated_at': _now()}
        _write_json(sys_path(base, CASE_FILE), data)
    removed = _remove_empty_dirs(base, OLD_ORIG + tuple(p[:-1] for p, _ in SYS_PREFIXES)
                                 + tuple(f'{MD_DIR}/{t}' for t in OLD_ORIG))
    _append_log(base, log, errors, removed)
    ensure(base)
    return {'moved': [(_rel(base, x['from']), _rel(base, x['to'])) for x in log],
            'removed_dirs': removed, 'errors': errors}


def _load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _append_log(base, log, errors, removed):
    if not (log or errors or removed):
        return
    p = sys_path(base, MIGRATION_LOG)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'a', encoding='utf-8') as f:
        f.write(f'# {_now()} — ترحيل إلى البنية المختصرة (الإصدار {LAYOUT_VERSION})\n')
        for x in log:
            f.write(f"نُقل: {_rel(base, x['from'])}  ←→  {_rel(base, x['to'])}  sha1={x['sha1']}\n")
        for e in errors:
            f.write(f'خطأ: {e}\n')
        for d in removed:
            f.write(f'حُذف مجلد فارغ: {d}\n')
    hist = _load_json(sys_path(base, MIGRATION_JSON)) or {'runs': []}
    hist['runs'].append({'at': _now(), 'version': LAYOUT_VERSION, 'errors': errors, 'removed_dirs': removed,
                         'moves': [{'from': _rel(base, x['from']), 'to': _rel(base, x['to']), 'sha1': x['sha1']}
                                   for x in log]})
    _write_json(sys_path(base, MIGRATION_JSON), hist)


# ---------- نقل ملف أثناء العمل (الفرز) مع تحديث كل المراجع ----------

def relocate(base, data, old_rel, new_rel, man=None):
    """ينقل أصلاً ومشتقه في markdown إلى مسار جديد (بعد التحقق من البصمة)، ويحدّث manifest وcase.json. يرجع المسار
    النسبي الفعلي (قد يأخذ « (2)»). man: manifest محمَّل (يُعدَّل في مكانه؛ المستدعي يحفظه) أو None ← يُحمَّل ويُحفظ."""
    import case_folder as cf
    if os.path.normcase(old_rel) == os.path.normcase(new_rel):
        return old_rel
    own = man is None
    man = man if man is not None else cf.load_manifest(base)
    log = []
    got = safe_move(os.path.join(base, *old_rel.split('/')), os.path.join(base, *new_rel.split('/')), log)
    real = _rel(base, got)
    mapping = {old_rel: real}
    e = man['files'].pop(old_rel, None)
    old_md = (e or {}).get('md') or cf.md_rel(old_rel)
    new_md = cf.md_rel(real)
    if os.path.isfile(os.path.join(base, *old_md.split('/'))):
        new_md = _rel(base, safe_move(os.path.join(base, *old_md.split('/')), os.path.join(base, *new_md.split('/')), log))
        mapping[old_md] = new_md
    if e is not None:
        e['md'] = new_md
        man['files'][real] = e
    if own:
        cf.save_manifest(base, man)
    if data is not None:
        fixed = rewrite_refs(data, mapping, base)
        data.clear()
        data.update(fixed)
    _append_log(base, log, [], [])
    return real
