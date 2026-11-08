# ===== cloud_files.py — ملفات OneDrive غير المنزَّلة (2026-10-25) =====
# مجلد القضايا قد يكون داخل OneDrive: الملف «عند الطلب» يظهر في المجلد بحجمه لكنه غير محلي، وأول قراءة له تنزّله من
# السحابة وتعلّق من يقرأ حتى ينتهي التنزيل. لذلك قبل قراءة أي أصل يُفحص أنه محلي بسمات Windows:
#   FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS (0x400000) و FILE_ATTRIBUTE_OFFLINE (0x1000) (و RECALL_ON_OPEN 0x40000).
# خيط الواجهة لا يقرأ ملفاً سحابياً أبداً (case_folder.scan(hydrate=False))؛ التنزيل يجري في الخيط الخلفي (المزامنة) مع
# رسالة «جاري تنزيل الملف من OneDrive» تعرضها صفحة القضية (current()).
import os
import threading

FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_MASK = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
ATTRS = None                       # الاختبارات تستبدلها: fn(path) -> سمات الملف

_lock = threading.Lock()
_current = {}                      # المسار ← اسم الملف الجاري تنزيله


def attributes(path):
    if ATTRS is not None:
        return ATTRS(path)
    try:
        return getattr(os.stat(path), 'st_file_attributes', 0) or 0
    except OSError:
        return 0


def is_cloud(path):
    """الملف غير محلي (OneDrive عند الطلب): قراءته تنزّله من السحابة."""
    return bool(attributes(path) & CLOUD_MASK)


def current():
    """رسالة التنزيل الجاري للواجهة، أو ''."""
    with _lock:
        names = list(_current.values())
    if not names:
        return ''
    return f"جاري تنزيل الملف من OneDrive: {names[0]}" + (f" (+{len(names) - 1})" if len(names) > 1 else '')


def ensure_local(path, status=None):
    """في خيط خلفي فقط: يقرأ الملف السحابي كاملاً فينزّله OneDrive (مع رسالة)، ثم يرجع True إن صار محلياً.
    ملف محلي أصلاً ← True فوراً بلا قراءة. فشل التنزيل ← False (المستدعي يتخطاه بلا تعليق)."""
    if not is_cloud(path):
        return True
    name = os.path.basename(path)
    with _lock:
        _current[path] = name
    if status:
        try:
            status(f'جاري تنزيل الملف من OneDrive: {name}')
        except Exception:
            pass
    try:
        with open(path, 'rb') as f:
            while f.read(1 << 20):
                pass
        return True
    except OSError:
        return False
    finally:
        with _lock:
            _current.pop(path, None)
