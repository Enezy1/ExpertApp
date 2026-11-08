# ===== case_workspace.py — مجلد قضية تقرير الخبرة + case.json (2أ، ونموذج النسخة 2 في case_model.py) =====
# الهيكل (2026-10-21، case_layout): {الجذر}\{رقم الخبرة}\ مستندات_النظام/ حوافظ/ مذكرات/ أخرى/ markdown/ الملخص.md
# التقرير/ و_نظام/ (مخفي: case.json وmanifest والحقائق والسجلات والفهرس والعقود). القضايا القديمة تُرحَّل عند الفتح.
# لا تحذف ولا تكتب فوق أي ملف موجود — تنشئ الناقص فقط.
# case.json يُكتب ذرّياً (ملف مؤقت ثم os.replace) مع نسخة .bak من الإصدار السابق.
import os
import re
import json
import tempfile
import threading
from datetime import datetime

import case_layout as cl
import case_model

SCHEMA_VERSION = case_model.SCHEMA_VERSION
SUBDIRS = (cl.SYS, cl.FACTS_DIR, cl.WORK_DIR, cl.SOURCES_DIR, cl.LOGS_DIR, cl.REPORT_DIR)
CASE_FILE = cl.CASE_FILE          # _نظام/case.json
MAX_PATH = 260
# هامش لأسماء الملفات التي ستُنشأ داخل المجلدات لاحقاً (مستندات مجلوبة، نسخ تقرير...)
PATH_HEADROOM = 80

STAGE_STATES = case_model.STATES + ('unavailable',)


class WorkspaceError(Exception):
    """خطأ برسالة عربية جاهزة للعرض على الخبير."""


def documents_dir():
    """مجلد «المستندات» الفعلي (قد يكون محوَّلاً إلى OneDrive) عبر Windows، وإلا ~/Documents."""
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:   # CSIDL_PERSONAL
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser('~'), 'Documents')


def legacy_root():
    """الجذر الافتراضي القديم (قبل 2026-10-18): القضايا فيه تُنسخ إلى الجديد عند فتحها ولا تُحذف."""
    return os.path.join(os.path.expanduser('~'), 'Desktop', 'تقارير الخبراء')


def default_root():
    return os.path.join(documents_dir(), 'تقارير الخبراء')


def reports_root():
    try:
        from expert_settings import load_reports_root
        r = load_reports_root()
    except Exception:
        r = ''
    return r or default_root()


def _safe_name(caso_no):
    n = (caso_no or '').strip()
    if not n or re.search(r'[<>:"/\\|?*\x00-\x1f]', n) or n in ('.', '..'):
        raise WorkspaceError(f"رقم الخبرة غير صالح كاسم مجلد: «{caso_no}»")
    return n


def case_file(base):
    return cl.sys_path(base, CASE_FILE)


def case_dir(caso_no, root=None):
    return os.path.join(root or reports_root(), _safe_name(caso_no))


def check_path_lengths(base):
    """يرفع WorkspaceError إن كان أطول مسار متوقع يتجاوز حد Windows."""
    longest = max(len(os.path.join(base, d)) for d in SUBDIRS + (CASE_FILE + '.bak', 'markdown/مستندات_النظام'))
    if longest + PATH_HEADROOM > MAX_PATH:
        raise WorkspaceError(
            f"مسار مجلد القضية طويل جداً ({longest} حرفاً، والحد {MAX_PATH} مع هامش "
            f"{PATH_HEADROOM} لأسماء الملفات). اختر جذراً أقصر من الإعدادات:\n{base}")


def _now():
    return datetime.now().isoformat(timespec='seconds')


def new_case_data(case):
    return case_model.new_case_data(case)


_WRITE_LOCK = threading.RLock()


def merge_shared(data, disk):
    """مفاتيح يكتبها عاملان (الطابور الخلفي وصفحة القضية) كلٌّ من نسخته في الذاكرة: يُدمج ما في الملف قبل الكتابة فلا تمسح
    كتابةُ أحدهما ما سجّله الآخر — مصادر المستندات (sources: الأحدث جلباً لكل نوع) وأرقام المستندات المسحوبة (folder_fetch)."""
    if not isinstance(disk, dict) or disk.get('caso_no') != data.get('caso_no'):
        return False
    changed = False
    src_disk = disk.get('sources') if isinstance(disk.get('sources'), dict) else {}
    if src_disk:
        mine = data.setdefault('sources', {})
        for kind, rec in src_disk.items():
            cur = mine.get(kind)
            if isinstance(rec, dict) and rec.get('file') and (not isinstance(cur, dict) or not cur.get('file')
                                                             or str(rec.get('fetched_at') or '') > str(cur.get('fetched_at') or '')):
                merged = dict(rec)
                if isinstance(cur, dict):
                    merged['doc_ids'] = list(dict.fromkeys(list(rec.get('doc_ids') or []) + list(cur.get('doc_ids') or [])))
                mine[kind] = merged
                changed = True
    ids = ((disk.get('folder_fetch') or {}).get('doc_ids') or []) if isinstance(disk.get('folder_fetch'), dict) else []
    if ids:
        ff = data.setdefault('folder_fetch', {})
        have = ff.setdefault('doc_ids', [])
        for i in ids:
            if i not in have:
                have.append(i)
                changed = True
    return changed


def write_case_json(base, data):
    """كتابة ذرّية: ملف مؤقت بنفس المجلد → fsync → نسخ القديم إلى .bak → os.replace. قفل واحد للعملية، ودمج المفاتيح المشتركة
    من الملف الحالي قبل الكتابة (merge_shared) — لا يُمسح مصدر الصحيفة الذي سجّله الطابور الخلفي."""
    with _WRITE_LOCK:
        _write_case_json(base, data)


def _write_case_json(base, data):
    path = cl.sys_path(base, CASE_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, encoding='utf-8') as f:
            merge_shared(data, json.load(f))
    except (OSError, ValueError):
        pass
    data['updated_at'] = _now()
    data['updated_on'] = case_model.machine_name()
    fd, tmp = tempfile.mkstemp(prefix='.case.', suffix='.tmp', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            bak = path + '.bak'
            try:
                with open(path, 'rb') as src:
                    raw = src.read()
                json.loads(raw.decode('utf-8'))   # لا نحفظ نسخة .bak تالفة فوق سليمة
                with open(bak + '.tmp', 'wb') as b:
                    b.write(raw)
                os.replace(bak + '.tmp', bak)
            except (ValueError, OSError):
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    import case_summary
    case_summary.write_quiet(base, data)          # «الملخص.md» يُحدَّث بعد كل تغيير (لا يُفشل الحفظ)


def _read(base):
    """يقرأ case.json؛ إن كان تالفاً يرجع لـ .bak. يرجع None إن لم يوجد أيٌّ منهما سليماً.
    القراءة لحظة استبدال الملف (os.replace من خيط آخر) قد تفشل على ويندوز ← إعادة قصيرة قبل اعتباره تالفاً."""
    import time
    for _try in range(6):
        got = _read_once(base)
        if got[0] is not None or not os.path.exists(cl.sys_path(base, CASE_FILE)):
            return got
        time.sleep(0.05)
    return got


def _read_once(base):
    for name in (CASE_FILE, CASE_FILE + '.bak', 'case.json', 'case.json.bak'):     # الأخيران: قبل الترحيل
        p = cl.sys_path(base, name)
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get('caso_no'):
                return case_model.migrate(data)
        except (ValueError, OSError):
            continue
    return None, False


def read_case_json(base):
    return _read(base)[0]


def ensure_workspace(case, root=None):
    """
    ينشئ مجلد القضية والمجلدات الفرعية الناقصة و case.json إن لم يوجد.
    يرجع (base, data). لا يمسّ أي ملف موجود.
    """
    base = case_dir(case['caso_no'], root)
    check_path_lengths(base)
    if root is None and not os.path.exists(base):
        try:                                   # قضية في الجذر القديم (سطح المكتب) ← نسخة كاملة، والقديم يبقى
            import case_folder
            case_folder.migrate_root(case['caso_no'], os.path.dirname(base), legacy_root())
        except Exception:
            pass
    try:
        os.makedirs(base, exist_ok=True)
        cl.migrate(base)                         # البنية القديمة ← المختصرة (نقل بعد التحقق من البصمة، بلا حذف)
        cl.ensure(base)
    except OSError as e:
        raise WorkspaceError(f"تعذّر إنشاء مجلد القضية:\n{base}\n{e}")
    data, migrated = _read(base)
    if data is None:
        data = new_case_data(case)
        write_case_json(base, data)
    elif data.get('caso_no') != case['caso_no']:
        raise WorkspaceError(
            f"case.json في المجلد يخص قضية أخرى ({data.get('caso_no')}) — لن يُعدَّل:\n{base}")
    elif migrated:
        write_case_json(base, data)       # ترحيل 1 → 2؛ تبقى النسخة القديمة في .bak
    return base, data
