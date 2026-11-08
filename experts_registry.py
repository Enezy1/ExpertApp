# ===== experts_registry.py — سجل أسماء الخبراء أونلاين (Supabase) =====
"""
مرجع موحّد لأسماء الخبراء، أونلاين بالكامل — يحل محل الاعتماد على قاعدة Access
المحلية (ExpretDB.MDB) التي لا تتوفر إلا على شبكة الدوام.

الفكرة:
- أي خبير يفتح البرنامج، اسمه المعروض (get_logged_in_name — الموثوق 100%) يُسجَّل
  تلقائيًا في جدول experts بالسحابة (upsert بالاسم، مع تحديث آخر ظهور).
- نافذة إدارة الصلاحيات (وأي مكان يحتاج قائمة الخبراء) تسحب الأسماء من هنا بدل
  Access — فتشتغل من أي مكان (بيت أو دوام) وتتراكم تلقائيًا كل ما يدخل خبير جديد.

التسجيل best-effort صامت تمامًا: أي فشل (لا إنترنت، السحابة واقعة) لا يوقف تشغيل
البرنامج ولا يزعج المستخدم — فقط يُتجاهل، ويعاد المحاولة تلقائيًا في الدخول التالي.

الجدول المطلوب بالسحابة (شغّل supabase_experts.sql مرة واحدة):
    experts(expert_name TEXT PK, account_no TEXT, first_seen TIMESTAMPTZ, last_seen TIMESTAMPTZ)
"""
import os
import json
import datetime

import requests

from config import SUPABASE_URL, SUPABASE_KEY

_TABLE = "experts"

# كاش محلي لأسماء الخبراء — يُستخدم فقط لو تعذّر الوصول للسحابة وقت العرض
_CACHE_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "ExpertApp", "experts_cache.json"
)

_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def _norm(name):
    return " ".join((name or "").split())


# ---------- الكاش المحلي ----------
def _load_cache():
    try:
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH, encoding="utf-8") as f:
                data = json.load(f)
                return [_norm(n) for n in data.get("names", []) if _norm(n)]
    except Exception:
        pass
    return []


def _save_cache(names):
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"names": sorted(set(names))}, f, ensure_ascii=False)
    except Exception:
        pass


# ---------- التسجيل التلقائي عند الدخول ----------
def register_expert(expert_name, account_no="", timeout=6):
    """
    يسجّل/يحدّث اسم الخبير الحالي بجدول experts (upsert بالاسم). يُستدعى مرة واحدة
    عند بدء البرنامج بعد تأكيد الاسم. best-effort صامت: يرجّع True عند النجاح،
    وFalse بصمت عند أي فشل (بدون رمي استثناء) — لا يجب أن يوقف تشغيل البرنامج.
    """
    name = _norm(expert_name)
    if not name:
        return False
    try:
        now = datetime.datetime.utcnow().isoformat()
        # نرسل last_seen دائمًا (يُحدَّث عند كل دخول). first_seen لا نرسله عمدًا:
        # عند أول إدراج يأخذ قيمته الافتراضية now() من السيرفر، وعند التحديث
        # (merge-duplicates) يبقى كما هو لأننا لم نرسله.
        payload = {
            "expert_name": name,
            "account_no": _norm(account_no),
            "last_seen": now,
        }
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/{_TABLE}",
            headers={**_HEADERS, "Prefer": "resolution=merge-duplicates"},
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=timeout,
        )
        if r.status_code in (200, 201, 204):
            # نحدّث الكاش المحلي بالاسم الجديد أيضًا
            cache = _load_cache()
            if name not in cache:
                cache.append(name)
                _save_cache(cache)
            return True
    except Exception:
        pass
    return False


# ---------- قراءة قائمة الخبراء ----------
def list_experts(timeout=6):
    """
    يرجع قائمة أسماء كل الخبراء المسجّلين (مرتبة أبجديًا) من السحابة، ويحدّث الكاش
    المحلي. لو تعذّر الاتصال يرجع آخر كاش معروف بصمت (قد يكون فاضيًا أول مرة).
    """
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{_TABLE}",
            headers=_HEADERS,
            params={"select": "expert_name", "order": "expert_name.asc"},
            timeout=timeout,
        )
        if r.status_code == 200:
            names = [_norm(row["expert_name"]) for row in r.json() if row.get("expert_name")]
            names = sorted(set(n for n in names if n))
            _save_cache(names)
            return names
    except Exception:
        pass
    return sorted(set(_load_cache()))
