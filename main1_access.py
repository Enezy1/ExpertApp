# ===== main1_access.py — إدارة صلاحية "إضافة قضية جديدة" بأسماء الخبراء (Supabase) =====
"""
صلاحية ميزة "إضافة قضية جديدة" تُدار أونلاين من قاعدة Supabase، وتنعكس على كل
الأجهزة فورًا بدون توزيع نسخة جديدة من البرنامج.

⚠️ لماذا بالاسم لا برقم الحساب؟
رقم الحساب غير موثوق: النظام الحكومي يسجّل رقم أول مستخدم دخل الجهاز تلقائيًا،
وحتى لو غيّر الخبير الرقم يدويًا بشاشة الدخول، قد يبقى الرقم الأول عالقًا —
فيختلط تحديد الهوية. بالمقابل، الاسم المعروض (get_logged_in_name) يُقرأ من هيدر
النظام *بعد* اكتمال الدخول الفعلي، وهو موثوق 100%. لذلك الصلاحية تُخزَّن وتُطابَق
بالاسم، لا بالرقم.

آلية العمل:
- المالك (محمد العنزي) مخوّل *دائمًا* بالاسم — حتى بدون إنترنت (خط دفاع لا ينكسر).
- أي خبير آخر مخوّل *فقط* لو اسمه مسجّل بجدول main1_authorized_users بالسحابة.
- المالك وحده يمنح/يسحب الصلاحية، ويختار الاسم من قائمة أسماء الخبراء المسجّلين
  أونلاين (experts_registry.list_experts) — لا كتابة يدوية حرة.

المطابقة: تتم بالاسم الأول + الأخير (نفس منطق باقي النظام)، لأن الاسم المعروض
مختصر (أول + أخير) بينما قائمة الأسماء قد تكون كاملة (بأسماء الأب/الجد).

الجدول المطلوب بالسحابة (شغّل supabase_main1_access.sql مرة واحدة):
    main1_authorized_users(expert_name TEXT PK, granted_by TEXT, granted_at TIMESTAMPTZ)
"""
import os
import json
import threading
import requests

from config import SUPABASE_URL, SUPABASE_KEY

# ===== المالك الأساسي (super-admin) — يُعرَّف بالاسم =====
OWNER_NAMES = {"محمد العنزي", "محمد العنزى"}

_TABLE = "main1_authorized_users"

_CACHE_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "ExpertApp", "main1_access_cache.json"
)

_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


# ---------- مطابقة الأسماء ----------
def _norm(name):
    return " ".join((name or "").split())


def _name_matches(stored, current):
    """يطابق اسمين تسامحًا مع اختلاف مختصر (أول+أخير) مقابل كامل (بأسماء الأب/الجد)."""
    s, c = _norm(stored), _norm(current)
    if not s or not c:
        return False
    if s == c:
        return True
    sp, cp = s.split(), c.split()
    if len(sp) >= 2 and len(cp) >= 2:
        return sp[0] == cp[0] and sp[-1] == cp[-1]
    return sp[0] in cp or cp[0] in sp


def is_owner(current_user=None, account_no=None):
    "هل المستخدم الحالي هو المالك الأساسي (بالاسم). account_no يُتجاهل — أُبقي للتوافق."
    cu = _norm(current_user)
    for owner in OWNER_NAMES:
        if _name_matches(owner, cu):
            return True
    return False


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


# ---------- القراءة من السحابة ----------
def list_authorized(timeout=6):
    """يرجع قائمة أسماء الخبراء المخوّلين من السحابة (ويحدّث الكاش). عند الفشل يرجع الكاش."""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{_TABLE}",
            headers=_HEADERS,
            params={"select": "expert_name"},
            timeout=timeout,
        )
        if r.status_code == 200:
            names = [_norm(row["expert_name"]) for row in r.json() if row.get("expert_name")]
            _save_cache(names)
            return sorted(set(names))
    except Exception:
        pass
    return sorted(set(_load_cache()))


def is_authorized_for_main1(current_user=None, account_no=None):
    """
    نقطة الفحص الموحّدة. المالك مخوّل دائمًا؛ غيره مخوّل فقط لو اسمه ضمن القائمة
    السحابية (أو الكاش). account_no يُتجاهل — أُبقي بالتوقيع للتوافق مع النداءات القديمة.
    """
    if is_owner(current_user):
        return True
    cu = _norm(current_user)
    if not cu:
        return False
    return any(_name_matches(stored, cu) for stored in list_authorized())


# ---------- الكتابة (المالك فقط) ----------
def grant_access(expert_name, granted_by="", timeout=10):
    "يمنح خبيرًا (بالاسم) صلاحية إضافة القضايا (upsert بالسحابة + تحديث الكاش). يرجع (ok, msg)."
    name = _norm(expert_name)
    if not name:
        return False, "الاسم فارغ"
    if is_owner(name):
        return True, "هذا اسم المالك — مخوّل أساسًا ولا يحتاج إضافة"
    try:
        payload = {"expert_name": name, "granted_by": _norm(granted_by)}
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/{_TABLE}",
            headers={**_HEADERS, "Prefer": "resolution=merge-duplicates"},
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=timeout,
        )
        if r.status_code in (200, 201, 204):
            cache = _load_cache()
            cache.append(name)
            _save_cache(cache)
            return True, "تمت الإضافة بنجاح"
        return False, f"رد غير متوقع من السحابة: {r.status_code} — {r.text[:200]}"
    except Exception as e:
        return False, f"تعذّر الاتصال بالسحابة: {e}"


def revoke_access(expert_name, timeout=10):
    "يسحب صلاحية خبير (بالاسم) — حذف من السحابة + تحديث الكاش. يرجع (ok, msg)."
    name = _norm(expert_name)
    if not name:
        return False, "الاسم فارغ"
    if is_owner(name):
        return False, "لا يمكن سحب صلاحية المالك"
    try:
        r = requests.delete(
            f"{SUPABASE_URL}/rest/v1/{_TABLE}",
            headers=_HEADERS,
            params={"expert_name": f"eq.{name}"},
            timeout=timeout,
        )
        if r.status_code in (200, 204):
            cache = [n for n in _load_cache() if n != name]
            _save_cache(cache)
            return True, "تم سحب الصلاحية"
        return False, f"رد غير متوقع من السحابة: {r.status_code} — {r.text[:200]}"
    except Exception as e:
        return False, f"تعذّر الاتصال بالسحابة: {e}"


# ==========================================================================
#  فحص الصلاحية السريع: خلفية + انتظار محدود
# ==========================================================================
# السبب: فحص الصلاحية يحتاج طلب شبكة (مهلته 6 ثوانٍ). لو صارت قبل بناء
# الواجهة على خيط الواجهة، يقف البرنامج 6-12 ثانية عند الإقلاع (كان
# والفحص ينادى مرتين). الحل: نفحص بالخلفية مبكراً عند الإقلاع
# (start_auth_check — يناديها main.py)، وبعدين وقت بناء الواجهة ننتظر
# النتيجة ثانيتين بالحد (resolve_authorization). لو ما وصلت — نرجع
# للنسخة المحفوظة على الجهاز (فورية، بدون شبكة).

_auth_lock = threading.Lock()
_auth_event = threading.Event()
_auth_value = None      # None = ما وصلت النتيجة بعد
_auth_user = None       # اسم الخبير اللي الفحص جارٍ له


def _cached_authorization(current_user):
    """الصلاحية من النسخة المحفوظة على الجهاز — فورية وبدون شبكة.
    المالك مخوّل دائماً (خط دفاع لا ينكسر حتى بدون إنترنت)."""
    if is_owner(current_user):
        return True
    cu = _norm(current_user)
    if not cu:
        return False
    return any(_name_matches(stored, cu) for stored in _load_cache())


def start_auth_check(current_user, timeout=4):
    """يبدأ فحص الصلاحية بالخلفية.

    يُنادى مبكراً عند الإقلاع (main.py) عشان تكون النتيجة جاهزة وقت
    بناء الواجهة. للمالك الجواب فوري بدون أي طلب شبكة.
    """
    global _auth_value, _auth_user
    with _auth_lock:
        if _auth_event.is_set() and _auth_user == current_user:
            return          # الفحص خلص أصلاً — ما نكرّره
        _auth_value = None
        _auth_user = current_user
        _auth_event.clear()

    def work():
        global _auth_value
        try:
            _auth_value = is_authorized_for_main1(current_user)
        except Exception:
            _auth_value = _cached_authorization(current_user)
        finally:
            _auth_event.set()

    threading.Thread(target=work, daemon=True).start()


def resolve_authorization(current_user, wait=2.0):
    """هل الخبير مخوّل لصلاحية «رئيس القسم»؟

    ينتظر نتيجة الفحص المسبق (الخلفية) حتى `wait` ثانية **بالحد**،
    ويرجع فوراً لو وصلت. لو ما وصلت — النسخة المحفوظة على الجهاز.
    """
    if not _auth_event.is_set():
        start_auth_check(current_user)
    _auth_event.wait(wait)
    with _auth_lock:
        val = _auth_value
    if val is not None:
        return val
    return _cached_authorization(current_user)
