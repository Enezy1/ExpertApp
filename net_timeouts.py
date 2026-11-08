# ===== net_timeouts.py — مهلات طلبات الشبكة (جدول واحد مركزي) =====
"""
لماذا هذا الملف موجود:
طلب الشبكة بدون مهلة = طلب يعلق **للأبد** لو السيرفر طاح أو الشبكة انقطعت
بالضبط وقت الطلب. عندها ما تقدر تسكّر البرنامج، والزر يضل معطّل، والخيط
ما يخلص. بـrequests الطلب بلا `timeout` ما عنده حد أعلى أبداً.

ليه مهل مو timeout واحد للجميع:
الأرقام هنا **مقيسة فعلياً** من سيرفر الوزارة (25/10/2026 — دخول حقيقي
بحساب الخبير «محمد عبدالله فرحان العنزى»)، مو مخمّنة:

    /includes/basic_info_result.php .... 0.06 ث (أعلى 0.08)
    /ECS_CASE_FLOW ..................... 0.08 ث (أعلى 0.12)
    /METMONTH .......................... 0.09 ث (أعلى 0.19)
    /user_profile ....................... 0.09 ث (أعلى 0.12)
    /mubashara_table_2.php ............. 0.28 ث (أعلى 0.33)
    /includes/load.php ................. 1.10 ث (أعلى 1.51)
    /MyCalendar ........................ 2.10 ث (أعلى 5.20)  ← الأثقل

⚠️ فصل قاطع — طلبات الذكاء الاصطناعي (Gemini / OCR / المزوّدات) **ما لها
علاقة ب)this الملف**:
    - نظام الوزارة: 0.06 .. 2.1 ث  → مهلة بالثواني
    - الذكاء الاصطناعي: قد تاخذ دقيقة  → مهلة 60..180 ث (case_research.TIMEOUT)
هذي الوحدة تعني **نظام الوزارة فقط**. أي timeout يمرره الكود لنفسه (Gemini
مثلاً) يبقى زي ما هو بدون أي تعديل.

كيف يشتغل:
`install()` يرقّع `requests.Session.request` مرة وحدة — في أي طلب لنظام
الوزارة **ما انكتب له مهلة أصلاً**، تنحط له مهلة الجدول تلقائياً.
الطلبات اللي عندها مهلة أصلاً (أو موministry) ما تنمس.

ليش الرقعة بدل ما نعدّل كل ملف؟ لأن أغلب الملفات اللي فيها طلبات بلا
مهلة هي ملفات مشتركة/تابعة للجهة الثانية — الرقعة تخلّي كل طلب مضمون
من غير ما نلمس ملف واحد منها.
"""
import threading

# ===== جدول المهلات =====
# كل قيمة = (مهلة الاتصال, مهلة القراءة) بالثواني.
# مهلة الاتصال قصيرة عمداً: لو الشبكة/السيرفر طاح نبي نعرف بسرعة
# بدل ما ننتظر. مهلة القراءة هي الحد الأعلى لاستجابة السيرفر.

CONNECT_TIMEOUT = 3          # failover سريع

#: افتراضي لصفحات الوزارة الخفيفة (0.06..0.33 ث مقيسة)
DEFAULT_MINISTRY_TIMEOUT = (CONNECT_TIMEOUT, 8)

#: التقويم الشهري — أثقل صفحة (2.1 ث وسط، 5.2 ث أعلى مرة شفناها)
MY_CALENDAR_TIMEOUT = (CONNECT_TIMEOUT, 15)

#: تقويم الجلسات الكامل (1.1 ث وسط، 1.5 ث أعلى مرة)
SESSIONS_LOAD_TIMEOUT = (CONNECT_TIMEOUT, 12)

#: عمليات الكتابة (إدراج جلسة / تحديد مصدر / إرسال مباشرة) — نتسامح أكثر
WRITE_TIMEOUT = (CONNECT_TIMEOUT, 15)

#: صفحة المستندات (ShowImg.php) — ترسم الأقسام كلها، ثقيلة مثل التقويم
DOCUMENTS_TIMEOUT = (CONNECT_TIMEOUT, 15)

#: مسار ← مهلة. المفتاح '*' هو الافتراضي.
MINISTRY_TIMEOUTS = {
    '/MyCalendar': MY_CALENDAR_TIMEOUT,
    '/includes/load.php': SESSIONS_LOAD_TIMEOUT,
    '/includes/insert.php': WRITE_TIMEOUT,
    '/includes/set_sourc.php': WRITE_TIMEOUT,
    '/includes/insert_mubashara.php': WRITE_TIMEOUT,
    '/ShowImg.php': DOCUMENTS_TIMEOUT,
}

#: كل المهلات بالثواني للعرض/التوثيق
TIMEOUT_SECONDS = {
    'connect': CONNECT_TIMEOUT,
    'default_read': DEFAULT_MINISTRY_TIMEOUT[1],
    'my_calendar_read': MY_CALENDAR_TIMEOUT[1],
    'sessions_load_read': SESSIONS_LOAD_TIMEOUT[1],
    'documents_read': DOCUMENTS_TIMEOUT[1],
    'write_read': WRITE_TIMEOUT[1],
}

_MINISTRY_HOST = 'expertapp.moj.gov.kw'

_installed = False
_lock = threading.Lock()
_original_request = None


def is_ministry_url(url):
    """هل الرابط لسيرفر الوزارة؟"""
    if not url:
        return False
    try:
        return _MINISTRY_HOST in str(url)
    except Exception:
        return False


def _path_of(url):
    """المسار من الرابط (بدون المضيف/الاستعلام) — للمطابقة مع الجدول."""
    try:
        s = str(url)
        i = s.find('://')
        if i >= 0:
            s = s[i + 3:]
        slash = s.find('/')
        if slash < 0:
            return '/'
        s = s[slash:]
        q = s.find('?')
        if q >= 0:
            s = s[:q]
        return s
    except Exception:
        return '/'


def timeout_for(url):
    """
    يرجع مهلة الطلب لسيرفر الوزارة بالشكل (connect, read)، أو None
    لو الرابط مو لسيرفر الوزارة (ذكاء اصطناعي / Supabase / غيره).
    """
    if not is_ministry_url(url):
        return None
    path = _path_of(url)
    for prefix, value in MINISTRY_TIMEOUTS.items():
        if prefix != '*' and path.startswith(prefix):
            return value
    return DEFAULT_MINISTRY_TIMEOUT


def install():
    """
    يرقّع requests.Session.request مرة واحدة — يضيف مهلة افتراضية
    لأي طلب ministry ما انكتب له timeout. Requests اللي عندها مهلة
    أصلاً (أو مو ministry) ما تنمس إطلاقاً.
    idempotent: نداءه مرة ثانية ما يسوي شي.
    """
    global _installed, _original_request
    with _lock:
        if _installed:
            return False
        try:
            import requests
        except Exception:
            return False
        if getattr(requests.Session.request, '_ministry_patched', False):
            _installed = True
            return False

        _original_request = requests.Session.request

        def _patched(self, method, url, *args, **kwargs):
            # ترتيب معاملات Session.request بعد method/url:
            # params, data, headers, cookies, files, auth, timeout
            explicit = args[6] if len(args) >= 7 else kwargs.get('timeout')
            if explicit is None:
                t = timeout_for(url)
                if t is not None:
                    kwargs['timeout'] = t
            return _original_request(self, method, url, *args, **kwargs)

        _patched._ministry_patched = True
        _patched._ministry_original = _original_request
        requests.Session.request = _patched
        _installed = True
        return True


def uninstall():
    """يرجّع الرقعة (للاختبارات فقط)."""
    global _installed, _original_request
    with _lock:
        if not _installed:
            return False
        try:
            import requests
            if _original_request is not None:
                requests.Session.request = _original_request
        except Exception:
            pass
        _installed = False
        _original_request = None
        return True


def is_installed():
    return _installed


def describe():
    """وصف مختصر للجدول — للتوثيق/التشخيص."""
    lines = ['مهلات نظام الوزارة (ثانية):']
    for prefix, (conn, read) in sorted(MINISTRY_TIMEOUTS.items()):
        lines.append('  %-32s اتصال=%s  قراءة=%s' % (prefix, conn, read))
    lines.append('  %-32s اتصال=%s  قراءة=%s' % ('(الافتراضي)', *DEFAULT_MINISTRY_TIMEOUT))
    lines.append('  ملاحظة: مهلات الذكاء الاصطناعي (60..180 ث) مو بخانة — ما تنمس.')
    return '\n'.join(lines)
