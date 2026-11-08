# ===== secret_store.py — تشفير مفاتيح API بـDPAPI لمستخدم ويندوز (2026-10-21) =====
# CryptProtectData بنطاق المستخدم الحالي: لا يُفكّ التشفير إلا من نفس حساب ويندوز على نفس الجهاز.
# القيمة المشفّرة تُخزَّن كنص «dpapi:<base64>». أي قيمة بلا هذه البادئة تُعدّ نصاً صريحاً قديماً وتُرحَّل تلقائياً
# عند أول قراءة (يُكتب الملف مشفّراً بدل النص الصريح، ويُتحقَّق من فك التشفير قبل الاستبدال).
# لا يُطبع أي مفتاح هنا، ولا يُفحص شكله ببادئته.
import base64
import ctypes
import json
import os
import tempfile
from ctypes import wintypes

PREFIX = 'dpapi:'
_ENTROPY = b'ExpertApp.keys.v1'
AVAILABLE = os.name == 'nt'


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _crypt(data, protect):
    inb, _keep = _blob(data)
    ent, _keep2 = _blob(_ENTROPY)
    out = _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(inb), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError('DPAPI failed')
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def is_protected(value):
    return isinstance(value, str) and value.startswith(PREFIX)


def protect(text):
    """نص → «dpapi:…». فارغ يبقى فارغاً. إن تعذّر DPAPI (غير ويندوز) يرفع OSError ولا يكتب نصاً صريحاً بصمت."""
    text = (text or '').strip()
    if not text or is_protected(text):
        return text
    if not AVAILABLE:
        raise OSError('DPAPI غير متاح على هذا النظام')
    return PREFIX + base64.b64encode(_crypt(text.encode('utf-8'), True)).decode('ascii')


def unprotect(value):
    """«dpapi:…» → النص. قيمة بلا بادئة (قديمة صريحة) تُرجَع كما هي. تعذّر الفك (مستخدم آخر/تالف) → ''."""
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if not is_protected(value):
        return value
    try:
        return _crypt(base64.b64decode(value[len(PREFIX):]), False).decode('utf-8').strip()
    except Exception:
        return ''


def atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_key(path, field, value):
    """يحفظ مفتاحاً شخصياً مشفّراً في ملف JSON صغير {field: 'dpapi:…'}. فارغ = حذف المفتاح."""
    atomic_write_json(path, {field: protect(value)})


def read_key(path, field):
    """يقرأ المفتاح (نصاً). إن وُجد نص صريح قديم: يُرحَّل للتشفير ويُستبدل في الملف نفسه، فلا يبقى نص صريح."""
    try:
        with open(path, encoding='utf-8') as f:
            raw = (json.load(f).get(field) or '').strip()
    except Exception:
        return ''
    if raw and not is_protected(raw):
        try:
            enc = protect(raw)
            if unprotect(enc) == raw:                    # لا نستبدل الأصل إلا بعد التحقق من الرجوع
                atomic_write_json(path, {field: enc})
        except Exception:
            pass                                          # تعذّر الترحيل: يبقى الملف كما هو والمفتاح يعمل
        return raw
    return unprotect(raw)


def protect_rows(rows):
    """نسخة من صفوف المزودات بحقل api_key مشفّر (للنسخة المحلية)."""
    out = []
    for r in rows or []:
        r = dict(r)
        if r.get('api_key'):
            r['api_key'] = protect(r['api_key'])
        out.append(r)
    return out


def unprotect_rows(rows):
    """(صفوف بمفاتيح مفكوكة، هل وُجد نص صريح يلزم ترحيله؟)"""
    out, legacy = [], False
    for r in rows or []:
        r = dict(r)
        k = r.get('api_key')
        if k and not is_protected(k):
            legacy = True
        if k:
            r['api_key'] = unprotect(k)
        out.append(r)
    return out, legacy
