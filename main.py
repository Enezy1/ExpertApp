# ===== main.py — نقطة التشغيل مع شاشة تسجيل الدخول =====
import subprocess, sys, os, traceback, datetime

# تسجيل أي خطأ غير متوقع بملف سجل بدل ما البرنامج يختفي بصمت بدون أي أثر
# (يحصل هذا لأن EXE النهائي بدون نافذة كونسول console=False — أي استثناء
# غير ملتقط بصمت يقفل البرنامج ولا يظهر أي رسالة). هذا لا يمنع الانهيار
# بحد ذاته، لكنه أول خطوة تشخيص فعلية: نفتح الملف بعد أول مرة تختفي فيها
# الشاشة ونشوف بالضبط وين وقف الخطأ.
def _crash_log_path():
    base = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'ExpertApp')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'crash_log.txt')

def _log_uncaught(exc_type, exc_value, exc_tb):
    try:
        with open(_crash_log_path(), 'a', encoding='utf-8') as f:
            f.write(f"\n===== {datetime.datetime.now().isoformat()} =====\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass
    # نطبعه أيضاً لو فيه كونسول (تشغيل عادي بـ python)
    traceback.print_exception(exc_type, exc_value, exc_tb)

sys.excepthook = _log_uncaught

# نفس الفكرة لكن للأخطاء اللي تصير داخل Thread ثانوي (مثل poll_loop في
# login_with_webview أو أي مزامنة خلفية) — sys.excepthook وحده لا يلتقطها.
def _log_uncaught_thread(args):
    _log_uncaught(args.exc_type, args.exc_value, args.exc_traceback)

import threading
threading.excepthook = _log_uncaught_thread


def install(pkg):
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# تثبيت المكتبات تلقائياً لو مو موجودة — فقط عند التشغيل العادي بـ python.
# عند التشغيل كـ EXE مبني بـ PyInstaller (sys.frozen=True)، كل المكتبات
# مجهّزة مسبقاً داخل الملف نفسه، ومحاولة استدعاء pip هنا فعليًا تحاول
# تشغّل ملف EXE نفسه بخيارات pip وهذا غير ممكن — نتجاهل الحلقة كلياً.
if not getattr(sys, 'frozen', False):
    for lib, pkg in [
        ('customtkinter', 'customtkinter'),
        ('browser_cookie3', 'browser-cookie3'),
        ('requests', 'requests'),
        ('webview', 'pywebview'),
        ('google.genai', 'google-genai'),
        ('caldav', 'caldav'),
        ('icalendar', 'icalendar'),
        ('PyQt6', 'PyQt6'),
        ('qfluentwidgets', 'PyQt6-Fluent-Widgets'),
        ('pyodbc', 'pyodbc'),
    ]:
        try:
            __import__(lib)
        except ImportError:
            print(f"جاري تثبيت {pkg}...")
            install(pkg)

# ===== مهلات طلبات الشبكة =====
# أي طلب لسيرفر الوزارة ما انكتب له timeout = طلب يعلق **للأبد** لو
# انقطعت الشبكة بالضبط وقت الطلب (ما تقدر تسكّر البرنامج، الزر يضل
# معطّل، والخيط ما يخلص). الرقعة تحط مهلة تلقائية لكل هالطلبات —
# بالمقاسات الفعلية لسيرفر الوزارة — بدون ما نلمس أي ملف مشترك.
# ملاحظة: مهلات الذكاء الاصطناعي (60..180 ث) مو بخانة — ما تنمس.
import net_timeouts
net_timeouts.install()

# ===== عقد بيانات القضية =====
# case.json يكتبه أكثر من وحدة (case_subject_mission · report_v3 · case_stage2 …)
# وما كان فيه عقد واحد بينها، فتصدق تعارض في الشكل: وحدة كتبت خانة قائمة
# وثانية قرأتها قاموساً ⇒ استثناء أثناء رسم البطاقة ⇒ البطاقة ما تنرسم.
# الرقعة تفحص كل دفتر قضية عند قراءته وتصلّح الأشكال الآمنة فقط (ما تحذف
# أي معلومة) — بدون ما نلمس أي ملف مشترك.
import case_schema
case_schema.install()

# ===== شاشة ترحيب سريعة =====
# تظهر فورًا قبل الاستيرادات الثقيلة (requests/api/Qt المتبقي) عشان المستخدم
# يعرف إن البرنامج يشتغل وما تعلّق، وتُغلق لما تظهر شاشة الدخول.
_SPLASH = None
_QAPP = None  # مرجع دائم لـQApplication (بدونه يُحذف عند خروج الدالة وتختفي النافذة)


def _show_splash():
    global _SPLASH, _QAPP
    try:
        from PyQt6.QtCore import Qt as _Qt
        from PyQt6.QtWidgets import (QApplication as _QApp, QWidget as _QW, QVBoxLayout as _QV,
                                     QLabel as _QL, QProgressBar as _QP, QFrame as _QF)
        import qt_theme as _th
        import qt_login_ui as _ui
        app = _QApp.instance() or _QApp(sys.argv)
        _QAPP = app
        try:
            _th.load_fonts()
        except Exception:
            pass
        w = _QW()
        w.setWindowFlags(_Qt.WindowType.SplashScreen | _Qt.WindowType.FramelessWindowHint
                         | _Qt.WindowType.WindowStaysOnTopHint)
        w.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground)
        w.setLayoutDirection(_Qt.LayoutDirection.RightToLeft)
        w.setFixedSize(460, 400)
        outer = _QV(w)
        outer.setContentsMargins(0, 0, 0, 0)
        card = _QF()
        card.setObjectName("splashCard")
        card.setStyleSheet(
            "QFrame#splashCard { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f" stop:0 {_ui.NAVY_MID}, stop:1 #050E1C); border-radius:24px;"
            f" border:1px solid {_ui.GOLD}; }}")
        outer.addWidget(card)
        lay = _QV(card)
        lay.setContentsMargins(50, 34, 50, 26)
        lay.setSpacing(0)

        def lbl(text, size, color):
            l = _QL(text)
            l.setAlignment(_Qt.AlignmentFlag.AlignCenter)
            l.setStyleSheet(f"color:{color}; font-family:'{_th.FONT_FAMILY}'; font-size:{size}px;"
                            " background:transparent; border:none;")
            return l

        logo = _QL()
        logo.setAlignment(_Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("background:transparent; border:none;")
        try:
            from PyQt6.QtGui import QIcon as _QIcon
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            pm = None
            for nm in ("app_icon.ico", "app_icon.png"):
                fp = os.path.join(base, nm)
                if os.path.isfile(fp):
                    pm = _QIcon(fp).pixmap(96, 96)
                    break
        except Exception:
            pm = None
        if pm and not pm.isNull():
            logo.setPixmap(pm)
        else:
            logo.setText("⚖")
            logo.setStyleSheet(f"color:{_ui.GOLD}; font-size:56px; background:transparent; border:none;")
        lay.addWidget(logo)
        lay.addSpacing(10)
        lay.addWidget(_ui.GradientLabel("نظام جلسات الخبراء", 26))
        lay.addWidget(lbl("الإدارة العامة للخبراء — وزارة العدل", 12, _ui.TEXT_SOFT))
        lay.addSpacing(14)
        div = _QW()
        div.setFixedSize(220, 2)
        div.setStyleSheet(f"background:{_ui.GOLD}; border-radius:1px;")
        lay.addWidget(div, 0, _Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(20)
        lay.addWidget(lbl("انتظر قليلاً... جاري تشغيل البرنامج", 14, "white"))
        lay.addSpacing(12)
        bar = _QP()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(5)
        bar.setStyleSheet("QProgressBar { background:#0A1830; border:none; border-radius:2px; }"
                          f" QProgressBar::chunk {{ background:{_ui.GOLD}; border-radius:2px; }}")
        lay.addWidget(bar)
        lay.addStretch()
        lay.addWidget(lbl("تصميم وتطوير: الخبير محمد عبدالله العنزي", 11, _ui.GOLD))
        scr = app.primaryScreen().availableGeometry()
        w.move(scr.center().x() - w.width() // 2, scr.center().y() - w.height() // 2)
        w.show()
        app.processEvents()
        _SPLASH = w
        # شاشة PyInstaller الأولى (EXE فقط) — نغلقها لأن نافذتنا ظهرت
        try:
            import pyi_splash
            pyi_splash.close()
        except Exception:
            pass
    except Exception:
        _SPLASH = None


def _close_splash():
    global _SPLASH
    try:
        if _SPLASH is not None:
            _SPLASH.close()
    except Exception:
        pass
    _SPLASH = None


_show_splash()

import requests, urllib3, webbrowser
from config import BASE_URL
from api import get_logged_in_name

urllib3.disable_warnings()


import json, os

CRED_PATH = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'credentials.json')

# ===== حسابات متعددة على نفس الجهاز =====
# جهاز واحد ممكن يستخدمه أكثر من خبير (كل خبير برقمه/كلمة مروره
# الخاصة). بدل ما نخزّن حساب واحد بس (وكل خبير يضطر يمسح ويكتب بيانات
# التاني عند كل دخول)، نخزّن كل حساب دخل من هذا الجهاز مرة على الأقل،
# ونعرض أزرار اختيار سريع بشاشة الدخول — ضغطة وحدة تعبّي الحقول
# وتحاول الدخول مباشرة، بدون كتابة يدوية كل مرة. آخر حساب استُخدم هو
# الافتراضي المعروض عند فتح البرنامج (نفس السلوك القديم للمستخدم
# الوحيد، ونضيف له باقي الحسابات كخيارات إضافية بس).
def _load_cred_file():
    try:
        if os.path.exists(CRED_PATH):
            with open(CRED_PATH, encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and 'accounts' in data:
                    # توافق مع صيغة وسطى (حساب = نص كلمة مرور مباشرة، بدون
                    # display_name) — نحوّلها لصيغة dict موحّدة بالذاكرة.
                    for u, v in list(data['accounts'].items()):
                        if not isinstance(v, dict):
                            data['accounts'][u] = {'password': v, 'display_name': ''}
                    return data
                # توافق مع الصيغة القديمة جدًا (حساب واحد فقط: username/password)
                if isinstance(data, dict) and data.get('username'):
                    return {
                        'accounts': {data['username']: {
                            'password': data.get('password', ''), 'display_name': ''}},
                        'last_used': data['username'],
                    }
    except Exception:
        pass
    return {'accounts': {}, 'last_used': ''}


def save_credentials(username, password, display_name=None):
    """يحفظ/يحدّث حساب معيّن بقائمة الحسابات المحفوظة على هذا الجهاز،
    ويجعله آخر حساب مستخدم (الافتراضي عند الفتح القادم) — بدون ما يمسح
    باقي الحسابات المحفوظة. display_name (اختياري): الاسم الفعلي
    المعروض بعد نجاح الدخول (من get_logged_in_name) — يُخزَّن عشان
    نتحقق منه لاحقًا عند إعادة استخدام جلسة فايرفوكس (انظر
    try_get_cookies)، بدون ما نعتمد على اسم المستخدم/الرقم المكتوب
    بحقل الدخول نفسه (غالبًا مختلف تمامًا عن الاسم المعروض)."""
    if not username:
        return
    data = _load_cred_file()
    existing = data['accounts'].get(username, {})
    data['accounts'][username] = {
        'password': password,
        'display_name': display_name if display_name else existing.get('display_name', ''),
    }
    data['last_used'] = username
    os.makedirs(os.path.dirname(CRED_PATH), exist_ok=True)
    with open(CRED_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def load_credentials():
    """يقرأ بيانات آخر حساب استُخدم (نفس الشكل القديم: username/password)
    — تعبئة تلقائية للحقول عند فتح شاشة الدخول."""
    data = _load_cred_file()
    last = data.get('last_used', '')
    if last and last in data['accounts']:
        return {'username': last, 'password': data['accounts'][last]['password']}
    return {}


def load_all_accounts():
    """يرجع قائمة [(username, password), ...] لكل الحسابات المحفوظة على
    هذا الجهاز، آخر حساب مستخدم أولاً — لعرض أزرار الاختيار السريع."""
    data = _load_cred_file()
    accounts = data.get('accounts', {})
    last = data.get('last_used', '')
    usernames = list(accounts.keys())
    if last in usernames:
        usernames.remove(last)
        usernames.insert(0, last)
    return [(u, accounts[u]['password']) for u in usernames]


def get_saved_display_name(username):
    """الاسم المعروض المحفوظ لحساب معيّن (من آخر دخول ناجح له)، أو نص
    فاضي لو حساب جديد لسه ما سجّل دخول ناجح من قبل."""
    data = _load_cred_file()
    return (data['accounts'].get(username) or {}).get('display_name', '')


def try_get_cookies(expected_display_name=None):
    """
    يجرب يحصل cookies من Firefox أولاً (جلسة سابقة لسه صالحة) — هذا
    المسار السريع (بدون فتح نافذة OTP) وأهم شي بالنسبة لأغلب المستخدمين
    (جهاز شخصي، حساب واحد بس)، فما نعطّله إلا لما نحتاج فعلاً.

    expected_display_name (اختياري): الاسم المعروض المحفوظ مسبقًا لهذا
    الحساب (من get_saved_display_name — مو اسم المستخدم/الرقم المكتوب
    بحقل الدخول، لأنه غالبًا شكل مختلف تمامًا عن الاسم المعروض بعد
    الدخول). لو مُمرَّر، نتحقق إن جلسة فايرفوكس فعلاً تخص نفس الاسم
    (يحمي أجهزة يشترك فيها أكثر من خبير من دخول بحساب غلط بصمت). لو
    ما فيه اسم محفوظ بعد (أول مرة لهذا الحساب على هذا الجهاز)، نتخطى
    التحقق ونثق بالجلسة — نفس السلوك السريع القديم.
    """
    import browser_cookie3
    try:
        cookies = browser_cookie3.firefox(domain_name='expertapp.moj.gov.kw')
        # MyCalendar أثقل صفحة عند الوزارة (2.1 ث وسط، 5.2 ث أعلى مرة شفناها)
        # — مهلة 5 ث كانت ترجّع فشل عشوائي وتطلّع المستخدم لشاشة الدخول
        # رغم إن جلسته سليمة. نعطيها مهلة measured.
        r = requests.get(f"{BASE_URL}/MyCalendar",
            cookies=cookies, verify=False, timeout=net_timeouts.MY_CALENDAR_TIMEOUT)
        if 'username-hide-on-mobile' in r.text:
            if expected_display_name:
                from api import short_name
                logged_in = get_logged_in_name(cookies) or ''
                if short_name(logged_in) != short_name(expected_display_name):
                    return None
            return cookies
    except: pass
    return None


LOGIN_WINDOW_TITLE = 'تسجيل الدخول — نظام الخبراء'


def _point_mouse_at_captcha(window, title=LOGIN_WINDOW_TITLE, wait_s=10):
    """يحرّك مؤشر الماوس بسلاسة لمنتصف مربع «أنا لست برنامج روبوت» — ولا يضغط أبدًا: الخبير يضغط بنفسه.
    (المسافة لا تكفي: المربع داخل إطار Google ولا يمكن إعطاؤه تركيز لوحة المفاتيح من الصفحة.)
    المكان = موضع إطار الكابتشا بالصفحة × devicePixelRatio + أصل منطقة محتوى النافذة على الشاشة.
    أي فشل (نافذة لم تُعثر، إطار لم يظهر، المستخدم حلّها) → لا شيء."""
    import ctypes
    import time
    from ctypes import wintypes

    def note(msg):   # تشخيص: كل خطوة بسطر في %LOCALAPPDATA%\ExpertApp\login_debug.log
        try:
            d = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ExpertApp')
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, 'login_debug.log'), 'a', encoding='utf-8') as fh:
                fh.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' | captcha-pointer | ' + msg + '\n')
        except Exception:
            pass

    js = """(function(){
        // الصفحة فيها نموذجان (كلمة المرور / الرسائل) لكل منهما كابتشا؛ إطار النموذج المخفي مقاسه صفر
        // (سجل الدخول الفعلي: not-visible:0,0,0) — نختار الظاهر، ونفضّل الذي داخل نموذج الرسائل
        var all = Array.prototype.slice.call(document.querySelectorAll(
            'iframe[src*="recaptcha"][src*="anchor"], iframe[title*="reCAPTCHA"], .g-recaptcha iframe'));
        if (!all.length) return 'no-iframe:' + document.querySelectorAll('iframe').length;
        var shown = all.filter(function(x){ var b = x.getBoundingClientRect(); return b.width > 50 && b.height > 30; });
        var otp = document.getElementById('log_f_otp');
        var f = shown.filter(function(x){ return otp && otp.contains(x); })[0] || shown[0];
        if (!f) return 'hidden-frames:' + all.length;
        try { if (window.grecaptcha && grecaptcha.getResponse().length > 0) return 'solved'; } catch(e) {}
        var r = f.getBoundingClientRect();
        if (r.width < 50 || r.bottom < 0 || r.top > window.innerHeight)
            return 'not-visible:' + [r.left, r.top, r.width, window.innerHeight].map(Math.round).join(',');
        // مربع الاختيار في إطار 304×78 على بعد ~27 من حافته ومنتصف الارتفاع. بالعربية (hl=ar أو صفحة rtl)
        // المربع على اليمين والشعار على اليسار — بالإنجليزية العكس (المؤشر وقف على الشعار قبل هذا التصحيح)
        var src = f.getAttribute('src') || '';
        var rtl = /[?&]hl=(ar|fa|he|ur)/.test(src) ||
                  (!/[?&]hl=/.test(src) && getComputedStyle(f.parentElement || f).direction === 'rtl');
        return [rtl ? r.right - 27 : r.left + 27, r.top + r.height / 2, window.devicePixelRatio || 1];
    })()"""
    try:
        end = time.monotonic() + wait_s
        pos = None
        time.sleep(0.9)   # بعد scrollIntoView (يبدأ بعد 400ms)
        note('start')
        while time.monotonic() < end:
            pos = window.evaluate_js(js)
            if isinstance(pos, list):
                break
            if pos == 'solved':
                note('already solved')
                return
            time.sleep(0.4)
        if not isinstance(pos, list):
            note(f'gave up: {pos}')
            return
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            note(f'window not found by title: {title}')
            return
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(origin))
        x, y, dpr = pos
        tx, ty = int(origin.x + x * dpr), int(origin.y + y * dpr)
        note(f'frame css=({x:.0f},{y:.0f}) dpr={dpr} client-origin=({origin.x},{origin.y}) -> target=({tx},{ty})')
        cur = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(cur))
        steps = 18   # حركة ناعمة ~0.3 ثانية بدل القفز
        for i in range(1, steps + 1):
            k = i / steps
            k = k * k * (3 - 2 * k)
            user32.SetCursorPos(int(cur.x + (tx - cur.x) * k), int(cur.y + (ty - cur.y) * k))
            time.sleep(0.016)
        after = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(after))
        note(f'cursor now=({after.x},{after.y})')

        # === إضافة النقر هنا ===
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004

        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        
        note('clicked successfully')
        # === 2. تحريك الماوس للأسفل قليلاً (5 سم / ~190 بكسل) ===
        time.sleep(0.3) # توقف بسيط بين النقر والحركة الثانية
        
        # الحصول على موقع الماوس الحالي (الذي يقف عليه الآن بعد النقر الأول)
        cur2 = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(cur2))
        
        # تحديد الإحداثيات الجديدة (النزول على محور Y بمقدار 190 بكسل)
        target_x = cur2.x
        target_y = cur2.y + 95

        # حركة ناعمة للمكان الجديد
        steps = 18
        for i in range(1, steps + 1):
            k = i / steps
            k = k * k * (3 - 2 * k)
            user32.SetCursorPos(int(cur2.x + (target_x - cur2.x) * k), int(cur2.y + (target_y - cur2.y) * k))
            time.sleep(0.016)

        # === 3. النقر الثاني في المكان الجديد ===
        time.sleep(1.0)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        
        note('second click executed after moving down')

    except Exception as e:
        note(f'error: {type(e).__name__}: {e}')


def login_with_webview(username='', password=''):
    """
    يفتح متصفح صغير مدمج بالبرنامج (pywebview) ويملأ بيانات الدخول
    تلقائياً. المستخدم يحل CAPTCHA و OTP بنفسه، وبمجرد نجاح الدخول
    (الخروج من صفحة /login) نقرأ الكوكيز ونغلق النافذة تلقائياً.

    ملاحظة: مشكلة "القضايا المتداولة" التي ظهرت سابقاً لم تكن متعلقة
    بمصدر الكوكيز (pywebview أو Firefox) بل بمتغير source_id ناقص في
    صفحة METMONTH بالسيرفر — تم حلها بشكل مستقل في pending_cases.py
    عبر طلب set_sourc.php قبل طلب الجدول. لذلك لا حاجة لفتح Firefox
    حقيقي هنا؛ النافذة الداخلية السريعة تكفي تماماً.
    """
    import webview, time, requests as req

    result = {'cookies': None, 'done': False}

    def check_cookies_now():
        """يحاول يقرأ الكوكيز الحقيقية ويتحقق منها في أي لحظة —
        مستقل عن حدث تحميل الصفحة (مهم لأن شاشة OTP غالباً تظهر
        بجافاسكربت بدون إعادة تحميل كاملة للصفحة، فحدث on_loaded ما
        يتكرر). أول ما الكوكيز تصير صالحة فعلياً عند السيرفر (حتى لو
        لسه بشاشة OTP — لأن OTP قد لا يكون شرط فعلي)، نسكّر فوراً."""
        if result['done']: return False
        try:
            raw_cookies = window.get_cookies()
            cd = {}
            for c in raw_cookies:
                try:
                    for k, morsel in c.items():
                        cd[k] = morsel.value
                except Exception:
                    continue
            if cd:
                r = req.get(f"{BASE_URL}/MyCalendar",
                    cookies=cd, verify=False, timeout=net_timeouts.MY_CALENDAR_TIMEOUT)
                if 'username-hide-on-mobile' in r.text:
                    result['cookies'] = cd
                    result['done'] = True
                    window.destroy()
                    return True
        except Exception:
            pass
        return False

    def poll_loop():
        while not result['done']:
            time.sleep(1)
            check_cookies_now()

    def on_loaded(window):
        if result['done']: return
        try:
            current_url = window.evaluate_js("window.location.href")
            if not current_url: return

            # الدخول التلقائي بالمسجات: نختار طريقة OTP، نعبّي البيانات
            # ونضغط دخول مرة وحدة فقط (لو البيانات غلط ما نعيد المحاولة
            # بحلقة). بعدها المستخدم يكتب رمز الـSMS بس.
            if username and password and not result.get('auto_submitted'):
                import json as _json
                ok = window.evaluate_js(f"""
                    (function() {{
                        var f = document.getElementById('log_f_otp');
                        var u = document.getElementById('inp_username_otp');
                        var p = document.getElementById('inp_password_otp');
                        if (!f || !u || !p) return false;
                        var step2 = document.getElementById('form_otp_step2');
                        if (step2 && step2.offsetParent !== null) return false;
                        if (typeof switchMethod === 'function') switchMethod('otp');
                        u.value = {_json.dumps(username)};
                        p.value = {_json.dumps(password)};
                        [u, p].forEach(function(el) {{
                            el.dispatchEvent(new Event('input', {{bubbles:true}}));
                            el.dispatchEvent(new Event('change', {{bubbles:true}}));
                        }});
                        var btn = f.querySelector('button[type=submit]');
                        // ننزل لمربع "أنا لست برنامج روبوت" عشان يكون قدام المستخدم
                        setTimeout(function() {{
                            var cap = f.querySelector('.g-recaptcha, iframe[src*="recaptcha"]') || btn;
                            if (cap) cap.scrollIntoView({{block: 'center'}});
                        }}, 400);
                        // الـreCAPTCHA يحلها المستخدم بنفسه؛ أول ما تنحل
                        // نضغط "إرسال رمز OTP" تلقائياً
                        var t = setInterval(function() {{
                            var solved = true;
                            if (window.grecaptcha && f.querySelector('.g-recaptcha, iframe[src*="recaptcha"]')) {{
                                try {{ solved = grecaptcha.getResponse().length > 0; }}
                                catch (e) {{ solved = false; }}
                            }}
                            if (!solved) return;
                            clearInterval(t);
                            if (btn) btn.click();
                            else if (f.requestSubmit) f.requestSubmit();
                            else f.submit();
                        }}, 500);
                        return true;
                    }})();
                """)
                if not ok:
                    try:   # لماذا لم يبدأ التعبئة التلقائية (ومعها تحريك المؤشر)
                        _d = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'login_debug.log')
                        with open(_d, 'a', encoding='utf-8') as fh:
                            fh.write(time.strftime('%Y-%m-%d %H:%M:%S') + f' | auto-fill skipped | ok={ok!r} url={current_url}\n')
                    except Exception:
                        pass
                if ok:
                    result['auto_submitted'] = True
                    # المؤشر يذهب لمربع «أنا لست برنامج روبوت» — الضغط على الخبير
                    import threading as _th
                    _th.Thread(target=_point_mouse_at_captcha, args=(window,), daemon=True).start()
                    return

            # بعد طلب الرمز: نركّز على خانة الـOTP
            try:
                window.evaluate_js("var o=document.getElementById('inp_otp'); if(o && o.offsetParent!==null) o.focus();")
            except Exception:
                pass

            # نملأ البيانات في أي صفحة فيها حقول دخول
            if username and password:
                window.evaluate_js(f"""
                    (function() {{
                        var inputs = document.querySelectorAll('input');
                        inputs.forEach(function(inp) {{
                            if (inp.id == 'inp_otp' || inp.name == 'otp_code') return;
                            var t = (inp.type||'').toLowerCase();
                            var n = (inp.name||inp.id||inp.placeholder||'').toLowerCase();
                            if(t=='text' || n.includes('user') || n.includes('اسم')) {{
                                inp.value = '{username}';
                                inp.dispatchEvent(new Event('input', {{bubbles:true}}));
                                inp.dispatchEvent(new Event('change', {{bubbles:true}}));
                            }}
                            if(t=='password' || n.includes('pass') || n.includes('مرور') || n.includes('كلمة')) {{
                                inp.value = '{password}';
                                inp.dispatchEvent(new Event('input', {{bubbles:true}}));
                                inp.dispatchEvent(new Event('change', {{bubbles:true}}));
                            }}
                        }});
                    }})();
                """)

            # محاولة سريعة وآمنة عبر document.cookie
            js_c = window.evaluate_js("document.cookie")
            if js_c and ('PHPSESSID' in js_c or 'BNES' in js_c):
                cd = {}
                for item in js_c.split(';'):
                    if '=' in item:
                        k, v = item.strip().split('=', 1)
                        cd[k.strip()] = v.strip()
                if cd:
                    r = req.get(f"{BASE_URL}/MyCalendar",
                        cookies=cd, verify=False, timeout=net_timeouts.MY_CALENDAR_TIMEOUT)
                    if 'username-hide-on-mobile' in r.text:
                        result['cookies'] = cd
                        result['done'] = True
                        window.destroy()
                        return

            # لو خرجنا من صفحة login لكن الكوكيز المهمة محمية بـ HttpOnly
            # (لا تظهر بـ document.cookie)، نقرأ الكوكيز الحقيقية
            # فوراً من هنا عبر get_cookies() (تعمل بأمان أثناء تشغيل
            # الحلقة، النافذة لسه حية وما احتجنا ننتظر إغلاقها) — ثم
            # نسكّر مباشرة. هذا يمنع بقاء النافذة عالقة على الصفحة
            # الرئيسية بانتظار شرط document.cookie اللي ممكن ما يتحقق
            # أبداً لأن الكوكيز المهمة HttpOnly.
            if 'login' not in current_url:
                try:
                    raw_cookies = window.get_cookies()
                    cd = {}
                    for c in raw_cookies:
                        try:
                            # كل عنصر SimpleCookie (قاموس فيه مفتاح
                            # واحد = اسم الكوكي، وقيمته Morsel فيه
                            # .value الحقيقية)
                            for k, morsel in c.items():
                                cd[k] = morsel.value
                        except Exception:
                            continue
                    # وصولنا لصفحة غير /login جوه النافذة نفسها هو
                    # أقوى دليل نجاح ممكن — ما نخلي نجاح الدخول
                    # مرهون بتحقق ثانوي هش عبر requests من برا
                    # المتصفح (فرق User-Agent، كوكيز إضافية ما
                    # تنجمع، توقيت كتابة الكوكيز...). نقبل أي كوكيز
                    # غير فارغة كنجاح مباشرة.
                    if cd:
                        result['cookies'] = cd
                except Exception:
                    pass

                result['done'] = True
                window.destroy()
        except: pass

    window = webview.create_window(
        LOGIN_WINDOW_TITLE,
        f"{BASE_URL}/login",
        width=580, height=680,
        resizable=False,
        on_top=True,
    )
    window.events.loaded += lambda: on_loaded(window)

    import threading
    threading.Thread(target=poll_loop, daemon=True).start()

    webview.start()

    return result['cookies']


from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QApplication,
    QPushButton, QMessageBox
)
import qt_theme as th
from qt_widgets import PrimaryButton


class _UpdateBridge(QObject):
    "ينقل نتائج خيوط الفحص والتنزيل للخيط الرئيسي (الواجهة لا تُلمس إلا من هناك)"
    ready = pyqtSignal(str, object)     # (النسخة الجديدة، قائمة المصادر) — فيه تحديث
    progress = pyqtSignal(int, int)     # (المنزَّل، المجموع)
    downloaded = pyqtSignal(str, str)   # (مسار الملف، نوعه) — نجح التنزيل ('' = فشل)


_update_bridge = None
_update_state = {'ver': '', 'sources': None, 'path': '', 'kind': '', 'busy': False}


def _start_update_check():
    """فحص مرة وحدة عند الإقلاع (بخيط خلفي). لو فيه تحديث يظهر زر «تحديث متوفر»
    بالشريط الجانبي فقط — بلا نوافذ تقاطع الشغل."""
    global _update_bridge
    import threading
    _update_bridge = _UpdateBridge()
    _update_bridge.ready.connect(_on_update_available)
    _update_bridge.progress.connect(_on_update_progress)
    _update_bridge.downloaded.connect(_on_update_downloaded)

    def worker():
        try:
            import updater
            available, new_ver, sources = updater.check_for_update()
            if available:
                _update_bridge.ready.emit(new_ver, sources)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def _update_sidebar():
    "شريط النافذة الرئيسية (None لو لسه ما انبنت)"
    win = getattr(LoginScreenQt, '_main_window_ref', None)
    return getattr(win, 'sidebar', None) if win else None


def _on_update_available(new_ver, sources, _tries=0):
    sb = _update_sidebar()
    if sb is None:
        # الفحص قد يخلص قبل ما تنبني النافذة الرئيسية — نعيد المحاولة بهدوء
        if _tries < 40:
            QTimer.singleShot(500, lambda: _on_update_available(new_ver, sources, _tries + 1))
        return
    _update_state.update(ver=new_ver, sources=sources, path='', kind='')
    sb.show_update(new_ver)
    try:
        sb.update_btn.clicked.disconnect()
    except Exception:
        pass
    sb.update_btn.clicked.connect(_on_update_button)


def _on_update_button():
    "ضغطة الزر: لو التنزيل جاهز ← نطبّق ونعيد التشغيل؛ وإلا نبدأ التنزيل بالخلفية"
    if _update_state['busy']:
        return
    if _update_state['path']:
        import updater
        if not updater.apply_update(_update_state['path'], _update_state['kind']):
            QMessageBox.information(getattr(LoginScreenQt, '_main_window_ref', None), "التحديث",
                                    "التحديث التلقائي يعمل من نسخة EXE فقط.")
        return
    import threading
    import updater
    sb = _update_sidebar()
    _update_state['busy'] = True
    if sb:
        sb.set_update_progress(-1)

    def worker():
        path = kind = ''
        try:
            # داخلي أول، وإذا ما قدر يتصل داخلياً ينزّل من الخارج (download_update)
            path, kind, _src = updater.download_update(
                _update_state['sources'], _update_state['ver'],
                lambda done, total: _update_bridge.progress.emit(done, total))
        except Exception:
            pass
        _update_bridge.downloaded.emit(path or '', kind or '')

    threading.Thread(target=worker, daemon=True).start()


def _on_update_progress(done, total):
    sb = _update_sidebar()
    if sb:
        sb.set_update_progress(done * 100 // total if total else -1)


def _on_update_downloaded(path, kind):
    _update_state['busy'] = False
    sb = _update_sidebar()
    if path:
        _update_state['path'], _update_state['kind'] = path, kind
        if sb:
            sb.set_update_ready()
    elif sb:
        sb.set_update_failed(_update_state['ver'])


class LoginScreenQt(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("نظام جلسات الخبراء")
        self.setFixedSize(520, 830)
        # بدون إطار ويندوز الأبيض — شريط العنوان مرسوم داخل qt_login_ui.TitleBar
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        try:
            icon = th.load_window_icon()
            if not icon.isNull():
                self.setWindowIcon(icon)
        except Exception:
            pass

        self._spinner_chars = ['◐', '◓', '◑', '◒']
        self._spinner_idx = 0
        self._running = True
        self._build()

        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._spin)
        self._spin_timer.start(200)

        QTimer.singleShot(500, self._try_connect)

    def _field_style(self):
        return f"""
            QLineEdit {{
                background: {th.LOGIN_FIELD_BG}; border: 1px solid {th.LOGIN_FIELD_BORDER}; border-radius: 12px;
                padding: 11px 14px; font-size: 13px; color: white;
            }}
            QLineEdit:focus {{ border: 1px solid {th.EMERALD}; }}
        """

    def paintEvent(self, event):
        from qt_login_ui import paint_login_background
        paint_login_background(self, event)

    def _build(self):
        from qt_login_ui import build_login_ui
        creds = load_credentials()
        other_accounts = [u for u, p in load_all_accounts() if u != creds.get('username')]
        build_login_ui(self, creds, other_accounts)

    def _switch_account(self, username):
        """يعبّي الحقول بحساب محفوظ ثاني ويحاول الدخول مباشرة — ضغطة
        وحدة بدل كتابة يدوية كل مرة يبدّل فيها خبير ثاني نفس الجهاز."""
        accounts = dict(load_all_accounts())
        password = accounts.get(username, '')
        self.username_entry.setText(username)
        self.password_entry.setText(password)
        self._try_connect()

    def _spin(self):
        if not self._running:
            return
        self._spinner_idx = (self._spinner_idx + 1) % 4
        self.spinner.setText(self._spinner_chars[self._spinner_idx])

    def _try_connect(self):
        username = self.username_entry.text().strip()
        password = self.password_entry.text().strip()

        if not username or not password:
            self.status_lbl.setText("يرجى إدخال اسم المستخدم وكلمة المرور")
            return

        self.status_lbl.setText("جاري الاتصال...")
        self.retry_btn.setEnabled(False)
        self.retry_btn.setText("جاري...")
        QApplication.processEvents()

        # نجرب Firefox أولاً (لو الجلسة لا تزال صالحة من قبل) — المسار
        # السريع، بدون فتح نافذة OTP. نتحقق من هوية الجلسة بس لو عندنا
        # اسم معروض محفوظ سابقًا لنفس هذا الحساب (get_saved_display_name)
        # — مو اسم/رقم المستخدم المكتوب بحقل الدخول نفسه (شكل مختلف
        # كليًا عن الاسم المعروض)، وإلا التحقق يفشل دايمًا بالغلط ويعطّل
        # هذا المسار السريع للجميع بدل ما يحمي بس الأجهزة المشتركة فعلاً.
        expected_name = get_saved_display_name(username)
        cookies = try_get_cookies(expected_display_name=expected_name)
        if cookies:
            user = get_logged_in_name(cookies)
            save_credentials(username, password, display_name=user)
            self._open_app(cookies, user, account_no=username)
            return

        # نفتح نافذة تسجيل دخول داخلية صغيرة
        self.status_lbl.setText("أدخل OTP في النافذة...")
        QApplication.processEvents()
        self.hide()
        cookies = login_with_webview(username, password)
        self.show()

        if cookies:
            user = get_logged_in_name(cookies)
            save_credentials(username, password, display_name=user)
            self._open_app(cookies, user, account_no=username)
        else:
            self.status_lbl.setText("فشل تسجيل الدخول — حاول مرة ثانية")
            self.retry_btn.setEnabled(True)
            self.retry_btn.setText("🔐  تسجيل الدخول")

    def _open_app(self, cookies, user, account_no=None):
        # لا نسكّر شاشة الدخول فوراً — فيه شوية شغل يصير هنا (مزامنة
        # سحابية، تحميل خطوط، بناء كل صفحات الواجهة الرئيسية وأول جلب
        # بيانات لها) وكله يشتغل على نفس الـthread قبل ما تطلع الشاشة
        # الرئيسية. لو سكّرنا شاشة الدخول فوراً هنا، المستخدم يشوف ولا
        # شي (لا شاشة دخول ولا رئيسية) لثواني، ويظن البرنامج تعلّق أو
        # اتخرب. نخلي شاشة الدخول ظاهرة (بالسبينر ورسالة واضحة) طول
        # فترة التجهيز، ونسكّرها بس بعد ما الشاشة الرئيسية جاهزة وتطلع
        # فعلياً — انتقال متواصل بدون أي فراغ بصري.
        self.status_lbl.setText("جاري تجهيز البرنامج...")
        self.retry_btn.hide()
        QApplication.processEvents()

        import current_expert
        current_expert.set_current_user(user)
        # فحص طريق الاتصال بـGemini (بروكسي/مباشر) بالخلفية — لا يعطّل الفتح
        try:
            from gemini_config import start_connection_check
            start_connection_check()
            # مفاتيح المزودات المفعّلة للقسم (Supabase → نسخة محلية مشفرة)
            from provider_sync import start_refresh
            start_refresh()
        except Exception:
            pass
        # رقم الحساب (اسم المستخدم بشاشة الدخول، مثل 309) — معلومة إضافية فقط،
        # غير موثوق للتخويل (النظام يعلق على رقم أول مستخدم دخل الجهاز). التخويل
        # صار بالاسم المعروض الموثوق (main1_access.py).
        current_expert.set_current_account(account_no)

        # تسجيل اسم الخبير الحالي بسجل الخبراء الموحّد أونلاين (Supabase) — مرجع
        # موحّد لأسماء الخبراء يحل محل الاعتماد على قاعدة Access المحلية (المتوفرة
        # فقط على شبكة الدوام). best-effort صامت: أي فشل (لا إنترنت، السحابة
        # واقعة) لا يوقف تشغيل البرنامج ولا يزعج المستخدم.
        #
        # ⚠️ بالخلفية: الطلب الشبكي يوقف خيط الواجهة لو تم على خيطها، ومهلته
        # 6 ثوانٍ — فكان البرنامج يقف وقت الفتح. النية أصلاً «خلفية بحتة»
        # (شوف التعليق تحت)، بس التنفيذ كان على خيط الواجهة.
        def _register_in_background():
            try:
                import experts_registry
                experts_registry.register_expert(user, account_no=account_no or "")
            except Exception:
                pass
        threading.Thread(target=_register_in_background, daemon=True).start()

        # فحص خفيف واحد فقط عند بدء البرنامج: هل هذا الخبير مفعّل
        # للمزامنة من طرف رئيس القسم؟ لو نعم، يرفع القضايا المعلّقة
        # (needs_sync='1') تلقائياً بصمت تام. أي فشل (لا إنترنت،
        # السيرفر واقع...) لا يوقف تشغيل البرنامج إطلاقاً — المزامنة
        # خلفية بحتة.
        #
        # ⚠️ بالخلفية لنفس السبب أعلاه (مهلة 5 ثوانٍ + 15 للرفع الفعلي).
        def _sync_in_background():
            try:
                import cloud_sync
                cloud_sync.try_sync_on_startup(user)
            except Exception:
                pass
        threading.Thread(target=_sync_in_background, daemon=True).start()

        # فحص صلاحية «رئيس القسم» مبكراً بالخلفية — النتيجة تُستعمل وقت
        # بناء الشريط الجانبي (بننتظرها ثانيتين بالحد — resolve_authorization).
        # للمالك الجواب فوري بدون أي طلب شبكة.
        try:
            import main1_access
            main1_access.start_auth_check(user)
        except Exception:
            pass

        # فحص التحديث مرة وحدة فقط عند بدء التشغيل، بخيط منفصل لا يعطّل الواجهة.
        # لو فيه تحديث ونجح تنزيله من مجلد الشبكة، يظهر سؤال التأكيد؛ غير ذلك
        # (لا تحديث / لا اتصال / الشبكة غير متاحة) يكمل البرنامج بصمت تام.
        try:
            _start_update_check()
        except Exception:
            pass

        QApplication.processEvents()

        th.load_fonts()
        QApplication.instance().setStyleSheet(th.GLOBAL_QSS)
        from qt_shell_v2 import ExpertAppQt
        self._main_window = ExpertAppQt(cookies, user)
        LoginScreenQt._main_window_ref = self._main_window
        self._main_window.show()
        import window_guard
        window_guard.install(QApplication.instance(), self._main_window)   # الرئيسية لا تختفي عند إغلاق حوار

        self._running = False
        self._spin_timer.stop()
        self.close()


if __name__ == "__main__":
    try:
        # ويندوز يجمّع النوافذ تحت python.exe (فيظهر شعار بايثون بشريط المهام) ما لم يكن للعملية
        # معرّف تطبيق خاص — يُعيَّن قبل إنشاء أي نافذة. بلا أثر على غير ويندوز.
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ExpertDesk.ExpertApp")
            except Exception:
                pass
        qt_app = QApplication.instance() or QApplication(sys.argv)
        qt_app.setWindowIcon(th.load_window_icon())
        # قاعدة ثابتة: كل الواجهة RTL بالكامل — نضبطها على مستوى التطبيق نفسه
        qt_app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        # خط Tajawal المضمّن مع البرنامج — من أول شاشة (الدخول)، حتى لو مو مثبّت بالجهاز
        th.load_fonts()
        import qt_context_menu
        import qt_report_card
        qt_report_card.load_plex()           # IBM Plex Sans Arabic لقائمة السياق من أول شاشة
        try:
            import ai_providers
            ai_providers.ensure_task_defaults()      # قسم [task_providers] الافتراضي في gemini_network.ini
            ai_providers.ensure_model_defaults()     # [gemini_routing] و[model_limits] (توجيه النماذج والحصص)
        except Exception:
            pass
        qt_context_menu.install(qt_app)     # قائمة سياق عربية فاتحة موحّدة لكل حقول النص
        screen = LoginScreenQt()
        screen.show()
        _close_splash()
        qt_app.exec()
    except Exception:
        # أي فشل حتى قبل ظهور شاشة الدخول (مثل تعذّر تحميل مكتبة Qt أو
        # ملف مفقود) يُسجَّل بدل ما يختفي البرنامج بصمت تام.
        _log_uncaught(*sys.exc_info())
        raise