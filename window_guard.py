# ===== window_guard.py — النافذة الرئيسية لا تختفي ولا يخرج البرنامج عند إغلاق نافذة فرعية (2026-10-17) =====
# العَرَض: عند X/Esc/«إغلاق» لأي نافذة فرعية (صفحة القضية، الإجراءات، المراجعة، المستندات، الأسئلة المهمة…) تختفي الصفحة
# الخلفية أو يتصرف التطبيق كأنه خرج. الأسباب المحتملة التي يعالجها هذا الحارس معاً (لم يُمكن استنساخ سبب واحد offscreen):
#   (1) quitOnLastWindowClosed: إغلاق آخر نافذة مرئية (ولو مؤقتاً) ينهي الحلقة ← يُعطَّل ويكون الخروج صريحاً بإغلاق الرئيسية فقط.
#   (2) ويندوز يمنح التركيز لنافذة تطبيق آخر عند إخفاء الحوار فتنزل الرئيسية خلف النوافذ ← بعد كل إخفاء/إغلاق حوار:
#       show() ثم raise_() ثم activateWindow() بتأخير QTimer.singleShot(0) (بعد انتهاء حدث الإغلاق).
#   (3) حوارات بلا أب ← أُدقِّقت: كل الحوارات الحالية آباؤها الصفحة/الرئيسية؛ ويحمي الحارس أي حوار مستقبلي بلا أب.
# النافذة المصغَّرة بقرار المستخدم تبقى مصغَّرة. لا يعالج إلا النافذة الرئيسية المسجَّلة (لا شاشة الدخول المخفية عمداً).
from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QApplication, QDialog

_guard = None


def restore(win):
    """يعيد النافذة الرئيسية إلى الواجهة (إن لم يصغّرها المستخدم)."""
    try:
        if win is None or win.isMinimized():
            return
        if not win.isVisible():
            win.show()
        win.raise_()
        win.activateWindow()
    except RuntimeError:                 # النافذة أُتلفت
        pass


class WindowGuard(QObject):
    def __init__(self, app, main_window):
        super().__init__(app)
        self.app, self.main = app, main_window
        app.setQuitOnLastWindowClosed(False)
        app.installEventFilter(self)
        self._main_filter = _MainCloseFilter(app, main_window)

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Hide, QEvent.Type.Close) and isinstance(obj, QDialog) and obj.isWindow():
            QTimer.singleShot(0, lambda: restore(self.main))
        return False


class _MainCloseFilter(QObject):
    """إغلاق الرئيسية من الخبير = خروج صريح من البرنامج."""

    def __init__(self, app, main_window):
        super().__init__(main_window)
        self.app = app
        main_window.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Close:
            # الإغلاق قد يُرفض في closeEvent: نتحقق بعد انتهاء الحدث أن الرئيسية اختفت فعلاً
            QTimer.singleShot(0, lambda: None if obj.isVisible() else self.app.quit())
        return False


def install(app, main_window):
    global _guard
    _guard = WindowGuard(app, main_window)
    return _guard
