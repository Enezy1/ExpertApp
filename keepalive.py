# ===== keepalive.py — إبقاء اتصال الجلسة مع نظام الوزارة حيّاً (11/2026) =====
# المشكلة: الجلسة تنقطع إذا ترك الخبير البرنامج فترة بلا نشاط.
# الحل: نبضة خفيفة كل 10 دقائق بنفس كوكيز الدخول، بحد أقصى 3 ساعات من تشغيل البرنامج.
#
# ⚠️ تجربة قابلة للإزالة: لو تبيّن أن الجلسة تنقطع بكل الأحوال (حتى مع النشاط)،
#    احذف هذا الملف + استدعاءه في qt_shell_v2.ExpertAppQt (كلمة keepalive) — لا شي ثاني يعتمد عليه.
#    كل نبضة تُسجَّل في keepalive.log (مجلد app_paths) لقياس المدة الفعلية.
#
# النتيجة لكل نبضة:
#   'ok'    الجلسة حيّة (الصفحة فيها اسم المستخدم)
#   'lost'  السيرفر رجّع صفحة تسجيل الدخول ← انتهت الجلسة فعلاً
#   'error' تعذّر الوصول (إنترنت/مهلة) ← ما نحكم على الجلسة، نعيد المحاولة بالنبضة التالية
import threading
import time
from datetime import datetime

import requests

import app_paths
import net_timeouts
from config import BASE_URL

INTERVAL_SEC = 10 * 60          # نبضة كل 10 دقائق
MAX_DURATION_SEC = 3 * 60 * 60  # حد أقصى 3 ساعات من بدء التشغيل
PING_PATH = '/MyCalendar'       # نفس صفحة التحقق من الدخول بالبرنامج (فيها username-hide-on-mobile)
LOGGED_IN_MARKER = 'username-hide-on-mobile'
LOG_NAME = 'keepalive.log'


def _log(line):
    try:
        with open(app_paths.path(LOG_NAME), 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {line}\n")
    except Exception:
        pass


def ping(cookies, timeout=net_timeouts.MY_CALENDAR_TIMEOUT):
    """نبضة واحدة (تُشغَّل بخيط خلفي). ترجّع 'ok' أو 'lost' أو 'error' — لا ترمي استثناء."""
    try:
        r = requests.get(f"{BASE_URL}{PING_PATH}", cookies=cookies,
                         verify=False, timeout=timeout)
        if r.status_code >= 500:
            return 'error'
        return 'ok' if LOGGED_IN_MARKER in r.text else 'lost'
    except Exception:
        return 'error'


def should_continue(elapsed_sec, max_sec=MAX_DURATION_SEC):
    "هل ما زال البرنامج ضمن مدة النبضات المسموحة؟"
    return elapsed_sec < max_sec


class KeepAlive:
    """
    يشغّل النبضات بخيط خلفي واحد (بلا Qt — الواجهة تستقبل النتيجة عبر callback
    ويجب أن تحوّلها لخيطها بإشارة). يتوقف تلقائياً عند:
      - انتهاء الجلسة ('lost') — بعد إبلاغ الواجهة مرة واحدة
      - بلوغ الحد الأقصى (3 ساعات)
      - stop()
    """

    def __init__(self, cookies, on_state, interval=INTERVAL_SEC, max_duration=MAX_DURATION_SEC,
                 pinger=ping):
        self.cookies = cookies
        self.on_state = on_state            # on_state('ok'|'lost'|'error')
        self.interval = interval
        self.max_duration = max_duration
        self._pinger = pinger
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread or not self.cookies:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name='keepalive')
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        t0 = time.monotonic()
        _log(f"بدأ — نبضة كل {self.interval // 60} د، حد أقصى {self.max_duration // 3600} س")
        while not self._stop.wait(self.interval):
            elapsed = time.monotonic() - t0
            if not should_continue(elapsed, self.max_duration):
                _log(f"توقف — بلغ الحد الأقصى ({int(elapsed // 60)} د)")
                return
            state = self._pinger(self.cookies)
            _log(f"بعد {int(elapsed // 60)} د من التشغيل: {state}")
            try:
                self.on_state(state)
            except Exception:
                pass
            if state == 'lost':
                _log("انتهت الجلسة — توقفت النبضات")
                return
