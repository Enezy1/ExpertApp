# ===== qt_shell_v2.py — النافذة الرئيسية والشريط الجانبي بأيقونات مرسومة =====
# نفس كلاسات qt_shell.py العامة (Sidebar, ExpertAppQt) وبنفس التواقيع — بديل مباشر.
# يستورد صفحات _v2 (المتداولة والمحالة) — للتجربة غيّر في main.py:
#     from qt_shell import ExpertAppQt   →   from qt_shell_v2 import ExpertAppQt
# منطق الصلاحيات والتنقّل منسوخ حرفيًا؛ الذي تغيّر الشريط الجانبي فقط:
# أيقونات خطية مرسومة بدل الإيموجي، مجموعتان (عملي / رئيس القسم)، الإعدادات أسفل الشريط.
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QPoint, QRect, QTimer, QObject, QEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QStackedWidget,
    QFrame, QMessageBox, QPushButton
)
from PyQt6.QtWidgets import QApplication, QToolTip
from PyQt6.QtGui import QIcon, QCursor, QPainter, QColor, QBrush, QKeySequence, QShortcut
import os

import qt_theme as th
import qt_icons as ic
import qt_motion as mo
from qt_sessions_page import SessionsPage
from qt_pending_page_v2 import PendingCasesPage
from qt_referred_page_v2 import ReferredCasesPage
from qt_settings_page import SettingsPage

# فحص خفيف بدون استيراد qt_main1 (اللي يستورد pyodbc) — تفادياً لأي
# مشكلة تثبيت مكتبة عند خبراء ثانيين ما تظهر لهم هذي الميزة أصلاً.
# الصلاحية تُدار أونلاين بالاسم عبر Supabase (main1_access.py) بدل قائمة الأسماء
# الثابتة القديمة — المالك مخوّل دائمًا، وغيره يُمنح بالاسم من نافذة الإعدادات.
import main1_access
from current_expert import get_current_account


def _is_authorized_for_main1(current_user):
    return main1_access.is_authorized_for_main1(current_user, get_current_account())


def _app_dir():
    return os.path.dirname(os.path.abspath(__file__))


def load_app_icon():
    """
    يحمّل أيقونة التطبيق من app_icon.ico (أولوية — أوضح بشريط مهام ويندوز)
    أو app_icon.png كبديل. يكفي استبدال هذا الملف بشعار الإدارة العامة
    للخبراء الحقيقي لاحقًا — لا حاجة لأي تعديل بالكود.
    """
    for name in ("app_icon.ico", "app_icon.png"):
        path = os.path.join(_app_dir(), name)
        if os.path.isfile(path):
            return QIcon(path)
    return QIcon()


class _StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.color = th.SIDEBAR_TEXT_MUTED
        self.setFixedSize(8, 8)

    def set_color(self, c):
        self.color = c
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(self.color)))
        p.drawEllipse(QPointF(4, 4), 3.5, 3.5)
        p.end()


class NavItem(QFrame):
    """عنصر تنقّل: أيقونة مرسومة + نص؛ النشط: غسلة بيضاء خفيفة + علامة زمردية"""
    clicked = pyqtSignal()

    def __init__(self, kind, label_text, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._active = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedHeight(44)
        self.setObjectName("nav")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 12, 0)
        root.setSpacing(12)

        self.indicator = QFrame()
        self.indicator.setFixedSize(3, 22)
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl = QLabel(label_text)

        root.addWidget(self.indicator)
        root.addWidget(self.icon)
        root.addWidget(self.lbl)
        # عدّاد تنبيه (مثلاً عدد القضايا المحالة) — مخفي لحد ما يُضبط رقم > 0
        self.badge = QLabel("")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setMinimumWidth(22)
        self.badge.setFixedHeight(20)
        self.badge.setStyleSheet(f"background:{th.DANGER}; color:white; border-radius:10px; border:none;"
                                 f" font-size:{th.FS_CAPTION}px; font-weight:{th.W_BOLD}; padding:0 6px;")
        self.badge.hide()
        root.addWidget(self.badge)
        root.addStretch()
        self._wash = 0.0            # شدّة غسلة المرور 0..1 (تتلاشى بدل الظهور المفاجئ)
        self._wash_anim = None
        self._apply(hover=False)

    def set_active(self, active):
        self._active = active
        self._apply(hover=False)

    def set_badge(self, n):
        """يعرض الرقم بجانب الاسم، ويخفيه لو صفر"""
        n = int(n or 0)
        self.badge.setText(str(n))
        self.badge.setVisible(n > 0)

    def _fade_wash(self, to):
        if not mo.motion_enabled():
            self._wash = to
            self._apply(hover=to > 0)
            return
        from PyQt6.QtCore import QVariantAnimation, QEasingCurve
        if self._wash_anim is not None:
            self._wash_anim.stop()
        a = QVariantAnimation(self)
        a.setStartValue(float(self._wash))
        a.setEndValue(float(to))
        a.setDuration(120)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(lambda v: (setattr(self, "_wash", float(v)), self._apply(hover=to > 0)))
        self._wash_anim = a
        a.start()

    def enterEvent(self, e):
        self._fade_wash(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._fade_wash(0.0)
        super().leaveEvent(e)

    def _apply(self, hover):
        if self._active:
            bg, fg, weight, ind = th.SIDEBAR_ITEM_ACTIVE, "white", th.W_BOLD, "transparent"   # العلامة يرسمها ختم الشريط المنزلق
        elif hover or self._wash > 0.01:
            bg, fg, weight, ind = f"rgba(255,255,255,{0.04 * max(self._wash, 0.0):.3f})", ("white" if hover else th.SIDEBAR_TEXT_MUTED), th.W_MEDIUM, "transparent"
        else:
            bg, fg, weight, ind = "transparent", th.SIDEBAR_TEXT_MUTED, th.W_MEDIUM, "transparent"
        self.setStyleSheet(f"QFrame#nav {{ background:{bg}; border-radius:10px; border:none; }}")
        self.indicator.setStyleSheet(f"background:{ind}; border-radius:1px; border:none;")
        self.icon.setPixmap(ic.pixmap(self.kind, fg, 18))
        self.icon.setStyleSheet("background:transparent; border:none;")
        self.lbl.setStyleSheet(f"color:{fg}; font-size:14px; font-weight:{weight}; background:transparent; border:none;")

    def mousePressEvent(self, e):
        self.clicked.emit()
        super().mousePressEvent(e)


def _group_caption(text):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{th.SIDEBAR_TEXT_MUTED}; font-size:{th.FS_CAPTION}px; font-weight:{th.W_BOLD};"
                      f" background:transparent; border:none; padding:14px 14px 6px 0;")
    lbl.setAlignment(th.ARIGHT)
    return lbl


def _initials(name):
    """حرفا الاسم الأول والأخير (بدون «ال» التعريف)، مفصولان بمسافة دقيقة حتى لا يتّصلا ككلمة"""
    parts = [p for p in (name or '').split() if p]
    if not parts:
        return ""
    first = parts[0][0]
    if len(parts) == 1:
        return first
    last = parts[-1][2:] if parts[-1].startswith("ال") and len(parts[-1]) > 2 else parts[-1]
    return f"{first} {last[0]}"


class Sidebar(QFrame):
    def __init__(self, on_nav, current_user=None, main1_authorized=None, parent=None):
        super().__init__(parent)
        self.on_nav = on_nav
        self.setFixedWidth(240)
        self.setStyleSheet(f"background:{th.SIDEBAR}; border:none;")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 24, 14, 18)
        root.setSpacing(2)

        # ---- الهوية: الشعار + الاسم + حالة الاتصال ----
        logo_row = QHBoxLayout()
        logo_row.setSpacing(10)
        logo_icon = QLabel()
        icon = load_app_icon()
        pm = icon.pixmap(36, 36) if not icon.isNull() else None
        if pm and not pm.isNull():
            logo_icon.setPixmap(pm)
            logo_icon.setFixedSize(36, 36)
            logo_icon.setStyleSheet("background:transparent; border:none;")
        else:
            logo_icon.setPixmap(ic.pixmap('gov', 'white', 20))
            logo_icon.setFixedSize(36, 36)
            logo_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_icon.setStyleSheet(f"background:{th.EMERALD}; border-radius:10px;")
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        t1 = QLabel("نظام الخبراء")
        t1.setStyleSheet(f"color:white; font-size:15px; font-weight:{th.W_BOLD}; border:none; background:transparent;")
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_dot = _StatusDot()
        self.status_lbl = QLabel("جاري الاتصال...")
        self.status_lbl.setStyleSheet(f"color:{th.SIDEBAR_TEXT_MUTED}; font-size:{th.FS_CAPTION}px; border:none; background:transparent;")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_lbl)
        status_row.addStretch()
        title_box.addWidget(t1)
        title_box.addLayout(status_row)
        logo_row.addWidget(logo_icon)
        logo_row.addLayout(title_box)
        logo_row.addStretch()
        root.addLayout(logo_row)
        root.addSpacing(18)

        # ---- التنقّل ----
        self.items = {}
        self._active_key = None

        def add(key, kind, label):
            item = NavItem(kind, label)
            item.clicked.connect(lambda k=key: self.on_nav(k))
            root.addWidget(item)
            self.items[key] = item

        root.addWidget(_group_caption("عملي"))
        add('sessions', 'calendar', 'الجلسات')
        add('pending', 'folder', 'القضايا المتداولة')
        add('referred', 'inbox', 'القضايا المحالة')
        add('myfiles', 'folder', 'الملف الآلي')
        add('expert_reports', 'seal', 'تقارير الخبراء')
        # اختصارات لمن يكتشفها — تستدعي نفس on_nav (لا منطق جديد)
        for n, key in enumerate(('sessions', 'pending', 'referred'), start=1):
            self.items[key].setToolTip(f"Ctrl+{n}")
            sc = QShortcut(QKeySequence(f"Ctrl+{n}"), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(lambda k=key: self.on_nav(k))
        # صلاحية «رئيس القسم»: تُمرَّر من الخارج (نتيجة وحدة تُحسب مرة
        # واحدة وتُشارك بين الشريط الجانبي والصفحات). لو ما انمرّرت —
        # نفحصها هنا (للتوافق مع أي نداء قديم).
        if main1_authorized is None:
            main1_authorized = _is_authorized_for_main1(current_user)
        if main1_authorized:
            root.addWidget(_group_caption("رئيس القسم"))
            add('main1', 'folder_plus', 'إضافة قضية جديدة')
            add('case_lookup', 'search', 'بحث قضية')
            add('labels', 'print', 'طباعة ملصق')

        root.addStretch()
        add('settings', 'gear', 'الإعدادات')
        root.addSpacing(10)

        # زر التحديث — مخفي إلا لما يوجد تحديث (يتحكم فيه main.py عبر show_update…)
        self.update_btn = QPushButton("")
        self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_btn.setMinimumHeight(38)
        self.update_btn.hide()
        root.addWidget(self.update_btn)
        root.addSpacing(8)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{th.SIDEBAR_DIVIDER}; border:none;")
        root.addWidget(sep)
        root.addSpacing(12)

        # ---- المستخدم ----
        user_row = QHBoxLayout()
        user_row.setSpacing(10)
        self.avatar = QLabel("")
        self.avatar.setFixedSize(34, 34)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setStyleSheet(f"background:{th.SIDEBAR_ITEM_ACTIVE}; color:white; border-radius:17px;"
                                  f" font-size:{th.FS_LABEL}px; font-weight:{th.W_BOLD}; border:none;")
        user_box = QVBoxLayout()
        user_box.setSpacing(0)
        self.user_lbl = QLabel("")
        self.user_lbl.setStyleSheet(f"color:white; font-size:{th.FS_BODY}px; font-weight:{th.W_BOLD}; border:none; background:transparent;")
        self.user_lbl.setAlignment(th.ARIGHT)
        logout_lbl = QLabel("تسجيل الخروج")
        logout_lbl.setStyleSheet(f"color:{th.SIDEBAR_TEXT_MUTED}; font-size:{th.FS_CAPTION}px; border:none; background:transparent;")
        logout_lbl.setAlignment(th.ARIGHT)
        user_box.addWidget(self.user_lbl)
        user_box.addWidget(logout_lbl)
        user_row.addWidget(self.avatar)
        user_row.addLayout(user_box)
        user_row.addStretch()
        root.addLayout(user_row)

    # ---- زر التحديث (عرض فقط — المنطق في main.py) ----
    def _style_update_btn(self, bg, enabled=True):
        self.update_btn.setEnabled(enabled)
        self.update_btn.setStyleSheet(
            f"QPushButton {{ background:{bg}; color:white; border:none; border-radius:10px;"
            f" font-size:{th.FS_LABEL}px; font-weight:{th.W_BOLD}; padding:6px 10px; }}"
            f"QPushButton:disabled {{ background:{bg}; color:white; }}")

    def show_update(self, new_ver):
        self.update_btn.setText(f"🔄 تحديث متوفر ({new_ver})")
        self._style_update_btn(th.EMERALD)
        self.update_btn.show()

    def set_update_progress(self, percent):
        self.update_btn.setText(f"⬇️ جاري التحميل… {percent}%" if percent >= 0 else "⬇️ جاري التحميل…")
        self._style_update_btn(th.SIDEBAR_ITEM_ACTIVE, enabled=False)

    def set_update_ready(self):
        self.update_btn.setText("✅ جاهز — اضغط لإعادة التشغيل")
        self._style_update_btn(th.EMERALD)

    def set_update_failed(self, new_ver):
        self.update_btn.setText(f"⚠️ تعذّر التحميل — أعد المحاولة ({new_ver})")
        self._style_update_btn("#B3261E")

    def set_active(self, key):
        for k, item in self.items.items():
            item.set_active(k == key)
        self._active_key = key
        self._place_seal(animate=True)

    # ---- «الختم الزمردي»: علامة واحدة تنزلق بين عناصر التنقّل (عرض فقط) ----
    def _seal(self):
        if getattr(self, "_seal_w", None) is None:
            self._seal_w = QFrame(self)
            self._seal_w.setStyleSheet(f"background:{th.EMERALD}; border-radius:1px; border:none;")
            self._seal_w.hide()
        return self._seal_w

    def _place_seal(self, animate):
        if getattr(self, "_opening", False):
            return                      # افتتاح المكتب جارٍ — الختم ينزل بنفسه
        item = self.items.get(self._active_key)
        seal = self._seal()
        if item is None or not item.isVisible():
            return
        top_left = item.indicator.mapTo(self, QPoint(0, 0))
        rect = QRect(top_left, item.indicator.size())
        seal.raise_()
        if animate and seal.isVisible():
            mo.glide(seal, rect, 240)
        else:
            seal.setGeometry(rect)
            seal.show()

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_opened", False) and mo.motion_enabled():
            # «افتتاح المكتب»: مرة واحدة عند كل تشغيل — الختم ينزل من أعلى الشريط إلى الصفحة الحالية
            self._opened = True
            self._opening = True
            QTimer.singleShot(140, self._open_desk)
            return
        self._opened = True
        self._place_seal(animate=False)

    def _open_desk(self):
        item = self.items.get(self._active_key)
        seal = self._seal()
        if item is None:
            self._opening = False
            return
        top_left = item.indicator.mapTo(self, QPoint(0, 0))
        target = QRect(top_left, item.indicator.size())
        start = QRect(target.x(), 64, target.width(), target.height())
        seal.setGeometry(start)
        seal.raise_()
        seal.show()
        mo.glide(seal, target, 420)
        def done():
            self._opening = False
            self._place_seal(animate=False)
        QTimer.singleShot(460, done)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_seal(animate=False)

    def set_connected(self, user):
        self.set_status('ok')
        self.user_lbl.setText(user)
        self.avatar.setText(_initials(user))

    def set_status(self, state):
        """عرض فقط: حالة الاتصال الصادقة — 'ok' متصل / 'lost' انقطع / 'none' غير متصل"""
        text, fg, dot = {
            'ok':   ("متصل", th.EMERALD_ON_NAVY, th.EMERALD),
            'lost': ("انقطع الاتصال", th.DANGER_ON_NAVY, th.DANGER_ON_NAVY),
            'none': ("غير متصل", th.SIDEBAR_TEXT_MUTED, th.SIDEBAR_TEXT_MUTED),
        }.get(state, ("جاري الاتصال...", th.SIDEBAR_TEXT_MUTED, th.SIDEBAR_TEXT_MUTED))
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color:{fg}; font-size:{th.FS_CAPTION}px; border:none; background:transparent;")
        self.status_dot.set_color(dot)


class _ToolTipRelay(QObject):
    """
    وسيط التلميحات (عرض فقط): Qt يعطي التلميح تنسيق الويدجت الذي يطلبه، فأي تنسيق
    «بلا محدِّد» على الويدجت أو بطاقته (مثل background:transparent) يُفسد ألوانه.
    الوسيط يعرض نفس النص بسياق النافذة العليا (تنسيقها محصور بـ QMainWindow/QDialog)،
    فيأخذ التلميح دائمًا نمط QToolTip العام: كحلي + أبيض. ويُخفى عند مغادرة الويدجت كالمعتاد.
    """
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.ToolTip and isinstance(obj, QWidget):
            text = obj.toolTip()
            if not text:
                return False
            win = obj.window()
            QToolTip.showText(ev.globalPos(), text, win, QRect(obj.mapTo(win, QPoint(0, 0)), obj.size()))
            return True
        return False


def _install_tooltip_relay():
    app = QApplication.instance()
    if app is not None and getattr(app, "_tooltip_relay", None) is None:
        app._tooltip_relay = _ToolTipRelay(app)
        app.installEventFilter(app._tooltip_relay)


class FadingStack(QStackedWidget):
    """مكدّس صفحات يُظهر الصفحة الجديدة بتلاشٍ ناعم (180ms) — نفس واجهة QStackedWidget.
    F5 يحدّث الصفحة الظاهرة بنفس دالة زر «تحديث» الموجودة فيها."""
    def __init__(self, parent=None):
        super().__init__(parent)
        _install_tooltip_relay()          # مرة واحدة للتطبيق كله (النافذة الرئيسية + كل النوافذ المنبثقة)
        sc = QShortcut(QKeySequence("F5"), self)
        sc.setContext(Qt.ShortcutContext.WindowShortcut)
        sc.activated.connect(self._refresh_current)

    def addWidget(self, w):
        """يمرّر إشارة حالة الاتصال من الصفحات (إن وُجدت) إلى الشريط الجانبي — عرض فقط"""
        i = super().addWidget(w)
        sig = getattr(w, "connection_state", None)
        if sig is not None:
            sig.connect(self._relay_status)
            st = getattr(w, "_conn_state", None)
            if st:
                QTimer.singleShot(0, lambda s=st: self._relay_status(s))
        return i

    def _relay_status(self, state):
        win = self.window()
        sb = win.findChild(Sidebar) if win is not None else None
        if sb is not None:
            sb.set_status(state)

    def _refresh_current(self):
        page = self.currentWidget()
        for name in ('_refresh_clicked', '_refresh_connection_and_sessions'):
            fn = getattr(page, name, None)
            if callable(fn):
                fn()
                return

    def setCurrentWidget(self, w):
        changed = w is not self.currentWidget()
        super().setCurrentWidget(w)
        if changed:
            mo.fade_in(w, 180)


class ExpertAppQt(QMainWindow):
    # عدد القضايا المحالة — يُرسَل من خيط الجلب الخلفي للواجهة
    _referred_count = pyqtSignal(int)
    _keepalive_state = pyqtSignal(str)      # نتيجة نبضة الإبقاء من الخيط الخلفي

    def __init__(self, cookies, current_user):
        super().__init__()
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("نظام جلسات الخبراء — وزارة العدل")
        app_icon = th.load_window_icon()        # أيقونة «مكتب الخبير» لشريط المهام — شعار الشريط الجانبي يبقى من load_app_icon
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
            if QApplication.instance():
                QApplication.instance().setWindowIcon(app_icon)
        self.cookies = cookies
        self.current_user = current_user
        self.setStyleSheet(f"QMainWindow {{ background:{th.BG}; }}")   # محصور في النافذة — لا يسري على التلميحات

        # ===== صلاحية «رئيس القسم» — تُحسب مرة واحدة وتُشارك =====
        # كان الفحص ينادى مرتين (هنا بالشريط الجانبي، وتحت بالصفحات) =
        # طلبان شبكيان كل واحد بمهلة 6 ثوانٍ، على خيط الواجهة = تجميد
        # وقت الإقلاع. الحين: نتيجة واحدة، وتنتظر الفحص المسبق (الخلفية)
        # ثانيتين بالحد — ولو ما وصلت، نرجع للنسخة المحفوظة على الجهاز.
        self._main1_authorized = main1_access.resolve_authorization(current_user, wait=2.0)

        self._fit_window_to_screen()

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(self.navigate, current_user,
                               main1_authorized=self._main1_authorized)
        root.addWidget(self.sidebar)

        self.stack = FadingStack()
        root.addWidget(self.stack, 1)

        self.sessions_page = SessionsPage(cookies, current_user)
        self.pending_page = PendingCasesPage(cookies, current_user)
        self.referred_page = ReferredCasesPage(cookies, current_user)
        self.settings_page = SettingsPage(cookies, current_user)
        from qt_my_files import MyFilesPage
        self.my_files_page = MyFilesPage(cookies, current_user)
        from qt_expert_reports import ExpertReportsPage
        self.expert_reports_page = ExpertReportsPage(cookies, current_user)

        self.pages = {
            'myfiles': self.my_files_page,
            'expert_reports': self.expert_reports_page,
            'sessions': self.sessions_page,
            'pending': self.pending_page,
            'referred': self.referred_page,
            'settings': self.settings_page,
        }

        if self._main1_authorized:
            from qt_case_lookup import CaseLookupPage
            self.case_lookup_page = CaseLookupPage(cookies, current_user)
            self.pages['case_lookup'] = self.case_lookup_page

            # 'إضافة قضية جديدة' كانت تفتح نافذة منبثقة (QDialog.exec())
            # فوق النافذة الرئيسية — الآن صفحة مدمجة بنفس النافذة زي
            # باقي الأقسام، تحتاج مكتبة pyodbc فقط عند الاستيراد الفعلي
            # (لذلك الاستيراد هنا داخل نفس شرط التخويل، مو بأعلى الملف).
            try:
                from qt_main1 import Main1Page
                self.main1_page = Main1Page(self, cookies, current_user)
                self.pages['main1'] = self.main1_page
                # صفحة 'طباعة ملصق' تعتمد على Main1Page لجلب بيانات القضايا
                from qt_main1 import LabelsPage
                self.pages['labels'] = LabelsPage(self.main1_page)
            except ImportError as e:
                self.main1_page = None
                self._main1_import_error = e

        for p in self.pages.values():
            self.stack.addWidget(p)

        self.navigate('sessions')

        # شارة عدد القضايا المحالة بالشريط الجانبي: تُجلب عند الدخول ثم كل 5 دقائق،
        # وتتحدث فوراً كلما حمّلت صفحة المحالة قائمتها (استلام/إعادة/تحديث)
        self._referred_count.connect(self.sidebar.items['referred'].set_badge)
        self.referred_page.countChanged.connect(self.sidebar.items['referred'].set_badge)
        if cookies:
            self._refresh_referred_badge()
            self._badge_timer = QTimer(self)
            self._badge_timer.timeout.connect(self._refresh_referred_badge)
            self._badge_timer.start(5 * 60 * 1000)

        if cookies:
            self.sidebar.set_connected(current_user)
            self.sessions_page.set_connected(current_user)

        # إبقاء الجلسة حيّة: نبضة كل 10 د، حد أقصى 3 س (تجربة قابلة للإزالة — keepalive.py)
        self._keepalive_state.connect(self._on_keepalive_state)
        self._keepalive = None
        if cookies:
            try:
                import keepalive
                self._keepalive = keepalive.KeepAlive(
                    cookies, lambda s: self._keepalive_state.emit(s))
                self._keepalive.start()
            except Exception:
                pass

    def _on_keepalive_state(self, state):
        "على خيط الواجهة: ok ← متصل · lost ← انتهت الجلسة (رسالة مرة وحدة) · error ← نتجاهل"
        if state == 'ok':
            self.sidebar.set_status('ok')
        elif state == 'lost':
            self.sidebar.set_status('lost')
            QMessageBox.warning(
                self, "انقطع الاتصال",
                "انقطع الاتصال بنظام الخبراء (انتهت الجلسة).\n"
                "أغلق البرنامج وافتحه من جديد لتسجيل الدخول.")

    def _refresh_referred_badge(self):
        """جلب خفيف بالخلفية لعدد القضايا المحالة (عادية + استعانة) — أي فشل يترك الشارة كما هي"""
        import threading
        from referred_cases import get_referred_cases, REFERRED_LIST_TYPE, SECONDMENT_LIST_TYPE

        def work():
            try:
                a = get_referred_cases(self.cookies, REFERRED_LIST_TYPE)
                b = get_referred_cases(self.cookies, SECONDMENT_LIST_TYPE)
                self._referred_count.emit(len(a) + len(b))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _placeholder_page(self, title):
        w = QWidget()
        lay = QVBoxLayout(w)
        lbl = QLabel(f"{title} — قيد النقل للتصميم الجديد، ستتوفر بالمرحلة القادمة")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:14px; border:none;")
        lay.addStretch()
        lay.addWidget(lbl)
        lay.addStretch()
        return w

    def navigate(self, key):
        if key in ('main1', 'labels') and self.pages.get(key) is None:
            QMessageBox.critical(self, "خطأ",
                f"تعذر فتح الشاشة — مكتبة مطلوبة غير مثبتة:\n{getattr(self, '_main1_import_error', '')}\n\n"
                "افتح cmd وشغّل:\npip install pyodbc")
            return
        self.sidebar.set_active(key)
        self.stack.setCurrentWidget(self.pages[key])

    def _fit_window_to_screen(self):
        screen = self.screen() or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        target_w = min(1280, int(geo.width() * 0.92))
        target_h = min(800, int(geo.height() * 0.88))
        min_w, min_h = 1080, 660
        target_w = max(target_w, min(min_w, geo.width()))
        target_h = max(target_h, min(min_h, geo.height()))
        x = geo.x() + max(0, (geo.width() - target_w) // 2)
        y = geo.y() + max(0, (geo.height() - target_h) // 2)
        self.setGeometry(x, y, target_w, target_h)
        self.setMinimumSize(min_w, min_h)

