# ===== qt_ilann_page.py — «طلب إعلان» (نظام الخبراء) =====
# نافذة «طلب إعلان» — تُفتح من بطاقة الجلسة: «إجراءات أخرى» ← «طلب إعلان».
#
# الشكل (مبني على التصميم المرجعي):
#   • شريط علوي كحلي: اسم الشاشة + رقم الخبرة.
#   • صف بطاقات هوية (رقم الخبرة · رقم القضية · الرقم الآلي · تاريخ/وقت الجلسة).
#   • بطاقة «الأطراف»: كل طرف صف قابل للاختيار — نقطة حالة + الاسم + شارة الصفة
#     + زر «إعلان»؛ الصف المختار يظل بحد كحلي وشارة «الطرف المختار».
#   • بطاقة النموذج (للطرف المختار): العنوان + سطر هوية + شبكة حقول 4 أعمدة
#     (التسمية فوق الحقل) — عنوان ثم «وسيلة الإعلان».
#   • «نتيجة الإعلان»: جدول منفصل تحت (أعمدة نظام الوزارة كما هي).
#   • شريط إجراءات سفلي ثابت: حالة الاتصال + «إغلاق/تحديث/طباعة/إرسال الإعلان».
#
# ⚠️ وضع «عرض الحالة» (read_only) — الجلسة مضى وقتها (نفس اليوم بعد وقتها):
#   نافذة نفسها بلا زر «إعلان» لكل طرف وبلا زر «إرسال»، مع شريط تنبيه يشرح السبب.
#   السبب: نظام الخبراء يرفض إعلاناً لجلسة سابقة (رد «4»).
#   الغرض: الخبير يقدر يشوف «شنو صار بالإعلان» بدل ما الشاشة تختفي عليه.
#
# ⚠️ Enter ما يرسل أبداً — التأكيد نافذة داخلية وزر «تراجع» هو الافتراضي.
# ⚠️ الإرسال ما يصير إلا بعد موافقة الخبير، والمكتبة (ilann.py) ترسل بـ dry_run=True افتراضياً.
import os
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QDialog, QComboBox, QFileDialog, QFrame,
    QScrollArea, QGridLayout, QSizePolicy, QAbstractItemView,
)

import qt_theme as th
import qt_icons as ic
import qt_fit
from qt_widgets import Card, PrimaryButton, SecondaryButton, _field_qss

import ilann
import ilann_claim


# ---------------------------------------------------------------------------
# أنماط مشتركة
# ---------------------------------------------------------------------------

#: house-style الجداول (نفس نمط qt_case_lookup.py / qt_case_page.py)
TABLE_QSS = f"""
QTableWidget {{
    background: {th.SURFACE}; alternate-background-color: {th.BG};
    border: 1px solid {th.BORDER}; border-radius: 10px;
    font-size: 13px; gridline-color: {th.BORDER};
}}
QHeaderView::section {{
    background: {th.NAVY_TINT}; padding: 8px; border: none;
    border-bottom: 1px solid {th.BORDER}; font-weight: 700;
}}
QTableWidget::item {{ padding: 6px 8px; }}
"""

#: القوائم المنسدلة — نفس رموز الحقول (radius 10 + حدّ هادئ)
COMBO_QSS = f"""
QComboBox {{
    background: {th.SURFACE}; border: 1px solid {th.BORDER}; border-radius: 10px;
    padding: 8px 12px; font-size: 13px; color: {th.TEXT_PRIMARY};
}}
QComboBox:focus {{ border: 1px solid {th.NAVY}; }}
QComboBox QAbstractItemView {{
    background: {th.SURFACE}; border: 1px solid {th.BORDER}; border-radius: 10px;
    padding: 4px; outline: none;
    selection-background-color: {th.NAVY}; selection-color: {th.SURFACE};
}}
"""

#: ردود النظام — نعرض رسالة مفهومة بدل نص الاستثناء الخام
SEND_MESSAGES = {
    '3': 'يوجد إعلان سابق لنفس الطرف في نفس الجلسة',
    '4': 'لا يجوز إدخال إعلان لجلسة سابقة',
    'err': 'ما نقدر نأكد إذا وصل الإعلان — حدّث النتائج قبل إعادة الإرسال.',
    'unknown': 'تعذّر إرسال الإعلان — لم يتم الإرسال.',
    'too_long': 'حقل أطول من المسموح بالنظام — قصّره وأعد الإرسال.',
}

#: شارات بطاقات الهوية — أيقونة دائرية: أخضر للجلسة (وقت/تاريخ) · كحلي لمعلومات القضية
FACT_ICONS = {
    'caso': ('file', th.NAVY, th.NAVY_TINT),
    'case': ('scales', th.NAVY, th.NAVY_TINT),
    'auto': ('gear', th.NAVY, th.NAVY_TINT),
    'date': ('calendar', th.EMERALD, th.EMERALD_BG),
    'time': ('clock', th.EMERALD, th.EMERALD_BG),
}


def _fact_icon(key):
    """خيارات الشارة الدائرية لبطاقة هوية (أيقونة + لون + خلفية)."""
    kind, color, bg = FACT_ICONS[key]
    return {'icon_kind': kind, 'badge_color': color, 'badge_bg': bg}


# ---------------------------------------------------------------------------
# أدوات واجهة صغيرة
# ---------------------------------------------------------------------------

def _lbl(text, color=None, bold=False, size=None, align=None, selectable=True):
    """نص عادي: خلفية شفافة، بلا حدّ، محاذاة يمين مطلقة (Absolute Right Rule)."""
    l = QLabel(text or '')
    l.setStyleSheet(
        "color:%s; font-size:%spx; font-weight:%s; background:transparent; border:none;"
        % (color or th.TEXT_PRIMARY, size or th.FS_BODY, th.W_BOLD if bold else th.W_REGULAR))
    l.setAlignment(align or th.ARIGHT)
    if selectable:
        l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return l


def _pill(text, bg, fg):
    """شارة صغيرة بجانب الاسم (نمط qt_sessions_page._pill)."""
    lbl = QLabel(text)
    lbl.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:9px; padding:2px 10px;"
                      f" font-size:11px; font-weight:700; border:none;")
    lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return lbl


def _icon(kind, color, size=18):
    """أيقونة خطية مرسومة بالكود (qt_icons) — بدون إيموجي."""
    lbl = QLabel()
    lbl.setPixmap(ic.pixmap(kind, color, size))
    lbl.setFixedSize(size, size)
    lbl.setStyleSheet("background:transparent; border:none;")
    return lbl


def _dot(color, size=10):
    """نقطة ممتلئة — إشارة حالة (Design المرجعي)."""
    dot = QFrame()
    dot.setFixedSize(size, size)
    dot.setStyleSheet(f"background:{color}; border:none; border-radius:{size // 2}px;")
    return dot


def _fmt_date(value):
    """'2026/11/10' → '10/11/2026' (للعرض فقط)"""
    v = (value or '').strip()
    for f in ('%Y/%m/%d', '%Y-%m-%d'):
        try:
            from datetime import datetime
            return datetime.strptime(v[:10], f).strftime('%d/%m/%Y')
        except Exception:
            continue
    return v or '—'


def _icon_badge(kind, color, bg, size=34):
    """شارة أيقونة دائرية (حلقة ملوّنة) — بدل النقطة الصغيرة."""
    badge = QFrame()
    badge.setObjectName('icon_badge')
    badge.setFixedSize(size, size)
    badge.setStyleSheet(f"background:{bg}; border:none; border-radius:{size // 2}px;")
    lay = QHBoxLayout(badge)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(_icon(kind, color, 20))
    return badge


def _fact(label, value, latin=False, icon_kind=None, badge_color=None, badge_bg=None):
    """بطاقة هوية: شارة أيقونة دائرية + تسمية + قيمة كبيرة."""
    box = QFrame()
    box.setObjectName('fact')
    box.setStyleSheet(f"QFrame#fact {{ background:{th.SURFACE}; border:1px solid {th.BORDER};"
                      f" border-radius:16px; }}")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(6)

    top = QHBoxLayout()
    top.setSpacing(8)
    top.addStretch()
    top.addWidget(_lbl(label, color=th.TEXT_SECONDARY, size=th.FS_CAPTION, selectable=False))
    if icon_kind:
        top.addWidget(_icon_badge(icon_kind, badge_color or th.NAVY,
                                   badge_bg or th.NAVY_TINT))
    lay.addLayout(top)

    val = _lbl(th.ltr(value) if latin else (value or '—'),
               bold=True, size=th.FS_TITLE)
    lay.addWidget(val)
    box.value_lbl = val
    return box


def _section(title, icon_kind=None):
    """عنوان قسم: أيقونة + نص عريض (نمط «بيانات العنوان المسجل للإعلان»)."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    if icon_kind:
        lay.addWidget(_icon(icon_kind, th.TEXT_SECONDARY, 16))
    lay.addWidget(_lbl(title, bold=True, size=th.FS_BODY, selectable=False))
    lay.addStretch()
    return w


def _grid_field(label_text, widget):
    """خلية شبكة: التسمية فوق الحقل (نمط التصميم المرجعي)."""
    cell = QWidget()
    lay = QVBoxLayout(cell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lbl = _lbl(label_text, color=th.TEXT_SECONDARY, size=th.FS_CAPTION, selectable=False)
    # التسمية مرتبطة بالحقل — قارئ الشاشة ينطق الاسم مع الحقل
    lbl.setBuddy(widget)
    lay.addWidget(lbl)
    lay.addWidget(widget)
    return cell


def _state(kind, title, sub='', retry_cb=None):
    """حالة داخل النافذة (فراغ / خطأ / تحميل) — نفس نمط qt_sessions_page._state_view."""
    from qt_sessions_page import _state_view
    return _state_view(kind, title, sub, retry_cb)


def _status_color(text):
    """لون حالة الإعلان (Three Signals Rule): تم ← زمردي، فشل ← عنابي."""
    t = (text or '').strip()
    if 'تم' in t:
        return th.EMERALD_TEXT
    if ('فشل' in t) or ('تعذر' in t) or ('تعذّر' in t):
        return th.DANGER_TEXT
    return th.TEXT_PRIMARY


class _ElidedLabel(QLabel):
    """اسم طويل ما يخرّب التخطيط — يُقصّ بثلاث نقاط والاسم كامل بالتلميح."""

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self._full = ''
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setAlignment(th.ARIGHT)
        self.setFullText(text)

    def setFullText(self, text):
        self._full = text or ''
        self.setToolTip(self._full)
        self._render()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._render()

    def _render(self):
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full, Qt.TextElideMode.ElideRight,
                                           max(40, self.width())))


# ---------------------------------------------------------------------------
# نافذة مشاهدة صحيفة الدعوى — على **يسار الشاشة** (مشاهدة مباشرة)
# ---------------------------------------------------------------------------

def _print_pdf(path):
    """طباعة مباشرة على الطابعة الافتراضية."""
    try:
        os.startfile(path, 'print')
    except OSError:
        pass


def _screen_of(widget):
    """شاشة العنصر (أو الشاشة الأساسية) — لأجل الوضع على يسار الشاشة."""
    try:
        from PyQt6.QtGui import QGuiApplication
    except Exception:
        return None
    screen = None
    try:
        screen = widget.screen() if widget is not None else None
    except Exception:
        screen = None
    if screen is None:
        try:
            screen = QGuiApplication.primaryScreen()
        except Exception:
            screen = None
    return screen


def _place_on_left(dlg, parent=None):
    """يحطّ النافذة على **يسار الشاشة** وينزاح النافذة الأم لليمين.

    عشان الخبير يشوف صحيفة الدعوى والنموذج بنفس الوقت.
    """
    screen = _screen_of(parent)
    if screen is None:
        dlg.resize(760, 900)
        return
    geo = screen.availableGeometry()
    keep = 640
    if parent is not None:
        try:
            keep = max(640, parent.minimumWidth())
        except Exception:
            keep = 640
    # عرض صحيفة الدعوى: 42% من الشاشة — وعلى الشاشة الضيّقة ما ناخذ
    # أكثر عشان يبقى مكان كافي لشريط الإجراءات (الأزرار) في النافذة أم.
    width = max(360, int(geo.width() * 0.42))
    avail = geo.width() - width - 12
    width = min(width, max(360, avail))
    dlg.setGeometry(geo.left(), geo.top(), width, geo.height())
    if parent is not None and hasattr(parent, 'setGeometry'):
        try:
            # ⚠️ ما نقرّر عرض النافذة أم عن حدّه الأدنى: شريط الإجراءات
            #    (وزر «إرسال الإعلان») هو الأهم — لو ضغطناها انقصّ الزر.
            pw = min(parent.width(), max(keep, avail))
            pw = min(pw, geo.width())
            x = geo.left() + geo.width() - pw
            if x < geo.left() + width + 12:
                x = geo.left() + width + 12
            parent.setGeometry(x, geo.top(), pw, min(parent.height(), geo.height()))
        except Exception:
            pass


def open_claim_viewer(parent, path, title='صحيفة الدعوى'):
    """نافذة **مستقلة** لمشاهدة صحيفة الدعوى — تنفتح على **يسار الشاشة**.

    النافذة أم (طلب إعلان) تنزاح لليمين — والخبير يشوف الاثنين بنفس الوقت.
    النافذة ما تنغلق مع النافذة أم (والمرجع محفوظ عندها عشان ما تنحذف).
    """
    from PyQt6.QtPdf import QPdfDocument
    from PyQt6.QtPdfWidgets import QPdfView

    saved = None
    try:
        saved = parent.geometry() if parent is not None else None
    except Exception:
        saved = None

    dlg = QDialog(parent, Qt.WindowType.Window)
    dlg.setModal(False)
    dlg.setWindowModality(Qt.WindowModality.NonModal)
    dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    dlg.setWindowTitle(title)

    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    head = QHBoxLayout()
    head.setContentsMargins(10, 6, 10, 6)
    head.setSpacing(8)
    head.addWidget(_icon('file', th.TEXT_SECONDARY, 16))
    head.addWidget(_lbl('صحيفة الدعوى', bold=True, size=th.FS_BODY, selectable=False))
    head.addStretch()
    lay.addLayout(head)

    doc = QPdfDocument(dlg)
    doc.load(path)
    view = QPdfView(dlg)
    view.setDocument(doc)
    view.setPageMode(QPdfView.PageMode.MultiPage)
    view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
    lay.addWidget(view, 1)

    row = QHBoxLayout()
    row.setContentsMargins(10, 6, 10, 8)
    row.setSpacing(8)
    pbtn = SecondaryButton('طباعة')
    pbtn.setIcon(ic.icon('print', th.TEXT_SECONDARY, size=15))
    pbtn.setAccessibleName('طباعة صحيفة الدعوى')
    pbtn.clicked.connect(lambda: _print_pdf(path))
    cbtn = SecondaryButton('إغلاق')
    cbtn.setAccessibleName('إغلاق مشاهدة صحيفة الدعوى')
    cbtn.clicked.connect(dlg.close)
    row.addWidget(pbtn)
    row.addStretch()
    row.addWidget(cbtn)
    lay.addLayout(row)

    _place_on_left(dlg, parent)
    if saved is not None:
        # لما تنغلق المعاينة ⟵ النافذة أم ترجع لمكانها
        def restore():
            try:
                parent.setGeometry(saved)
            except Exception:
                pass
        dlg.finished.connect(lambda _code: restore())
    dlg.show()
    dlg.raise_()
    return dlg


# ---------------------------------------------------------------------------
# نافذة التأكيد — داخلية بهوية التطبيق (Enter ما يرسل أبداً)
# ---------------------------------------------------------------------------

class _ConfirmSend(QDialog):
    """تأكيد إرسال الإعلان.

    ⚠️ Enter ما يرسل: زر «تراجع» هو الافتراضي (default + focus) وزر «إرسال إعلان»
    setAutoDefault(False) — فالضغط بالغلط على Enter يطلع من النافذة بدون إرسال.
    """

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle('تأكيد إرسال إعلان')
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        # ⚠️ الحدّ الأدنى يتعدّل على حجم الشاشة (زوم/شاشة صغيرة) — وإلا
        #    طلعت النافذة أعرض من الشاشة وانقصّت أزرارها.
        geo = qt_fit.available_geometry(self)
        self.setMinimumWidth(max(360, min(600, geo.width() - 32)))

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        root.addWidget(_lbl('سيُرسل إعلان فعلي في نظام الخبراء', bold=True, size=th.FS_TITLE))

        grid = QGridLayout()
        grid.setSpacing(10)
        for i, item in enumerate(rows):
            label, value = item[0], item[1]
            latin = item[2] if len(item) > 2 else False
            grid.addWidget(_fact(label, value, latin), i // 2, i % 2)
        root.addLayout(grid)

        warn = QHBoxLayout()
        warn.setSpacing(6)
        warn.addWidget(_icon('alert', th.AMBER_TEXT))
        warn.addWidget(_lbl('لا يمكن التراجع بعد الإرسال.', color=th.AMBER_TEXT,
                            size=th.FS_LABEL))
        warn.addStretch()
        root.addLayout(warn)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.btn_send = PrimaryButton('إرسال إعلان')
        self.btn_send.setFixedHeight(38)
        self.btn_send.setAutoDefault(False)
        self.btn_send.setAccessibleName('إرسال إعلان — كتابة في نظام الخبراء')
        self.btn_send.clicked.connect(self.accept)
        self.btn_cancel = SecondaryButton('تراجع')
        self.btn_cancel.setFixedHeight(38)
        self.btn_cancel.setDefault(True)
        self.btn_cancel.setAccessibleName('تراجع — لا إرسال')
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_send)
        btns.addWidget(self.btn_cancel)
        btns.addStretch()
        root.addLayout(btns)

        self.btn_cancel.setFocus(Qt.FocusReason.OtherFocusReason)
        # المقاس على المحتوى — ومقصوص لو ما fit على الشاشة
        qt_fit.clamp_to_screen(self)


# ---------------------------------------------------------------------------
# نموذج العنوان/الاتصال — يظهر تحت قائمة الأطراف داخل نفس النافذة
# ---------------------------------------------------------------------------

class PartyForm(QWidget):
    """نموذج عنوان/اتصال طرف (يبدأ من بيانات النظام ويكملها الخبير)."""

    #: يطلع بعد موافقة الخبير على نافذة التأكيد
    submitted = pyqtSignal(dict)

    #: نتيجة «سحب العنوان من صحيفة الدعوى» (تعبئة الحقول + رسالة الشريط السفلي)
    claim_done = pyqtSignal(dict)

    _zones_ready = pyqtSignal(list)
    _claim_ready = pyqtSignal(dict)
    _claim_progress = pyqtSignal(str)
    _claim_file_ready = pyqtSignal(dict)

    def __init__(self, cookies, caso_no='', session_date='', session_time='',
                 auto_no='', parent=None):
        super().__init__(parent)
        self.cookies = cookies
        self.caso_no = caso_no or ''
        self.session_date = session_date or ''
        self.session_time = session_time or ''
        self.auto_no = auto_no or ''
        self._claim_busy = False
        self._view_busy = False
        self._claim_data = None
        self.form = {}
        self.party = {}
        self.edits = {}
        self.cb_method = None
        self.cb_city = None
        self.cb_zone = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.card = Card()
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(14)

        # ---- الرأس: اسم الطرف + الصفة + سطر الهوية ----
        head = QHBoxLayout()
        head.setSpacing(10)
        self.name_lbl = _lbl('', bold=True, size=th.FS_TITLE)
        self.type_pill = _pill('', th.NAVY_TINT, th.NAVY)
        head.addWidget(self.name_lbl)
        head.addWidget(self.type_pill)
        head.addStretch()
        self.identity_lbl = _lbl('', color=th.TEXT_SECONDARY, size=th.FS_LABEL)
        self.identity_lbl.setAlignment(th.ALEFT)
        head.addWidget(self.identity_lbl)
        cl.addLayout(head)

        self.note_lbl = _lbl('', color=th.AMBER_TEXT, size=th.FS_LABEL)
        self.note_lbl.hide()
        cl.addWidget(self.note_lbl)

        # ---- العنوان ----
        addr_head = QWidget()
        ah = QHBoxLayout(addr_head)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(6)
        ah.addWidget(_icon('dot', th.TEXT_SECONDARY, 16))
        ah.addWidget(_lbl('بيانات العنوان المسجل للإعلان', bold=True, size=th.FS_BODY,
                          selectable=False))
        # سطر الحالة **بجانب الزر** — الجواب يجي مكان «جاري السحب» مو بعيد عنه
        self.claim_lbl = _ElidedLabel('')
        self.claim_lbl.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Preferred)
        self.claim_lbl.setMaximumWidth(460)
        self.claim_lbl.setVisible(False)
        ah.addWidget(self.claim_lbl, 1)
        # زر «عرض صحيفة الدعوى» — يفتحها على **يسار الشاشة** (مشاهدة مباشرة)
        self.btn_view_claim = SecondaryButton('عرض صحيفة الدعوى')
        self.btn_view_claim.setFixedHeight(34)
        self.btn_view_claim.setIcon(ic.icon('file', th.TEXT_SECONDARY, size=15))
        self.btn_view_claim.setAccessibleName('عرض صحيفة الدعوى')
        self.btn_view_claim.setToolTip('يفتح صحيفة الدعوى على يسار الشاشة — مشاهدة مباشرة '
                                       'للتأكد من المعلومات')
        self.btn_view_claim.clicked.connect(self._on_view_claim)
        ah.addWidget(self.btn_view_claim)
        self.btn_claim = SecondaryButton('سحب العنوان من صحيفة الدعوى')
        self.btn_claim.setFixedHeight(34)
        self.btn_claim.setIcon(ic.icon('search', th.TEXT_SECONDARY, size=15))
        self.btn_claim.setAccessibleName('سحب العنوان من صحيفة الدعوى')
        self.btn_claim.setToolTip('يستخدم صحيفة الدعوى المحفوظة بالجهاز، أو ينزّلها من الملف الآلي، '
                                  'ويستخرج عنوان هذا الطرف')
        self.btn_claim.clicked.connect(self._on_claim)
        ah.addWidget(self.btn_claim)
        cl.addWidget(addr_head)

        # سطر التفاصيل (تحت): شنو لقينا بالضبط
        self.claim_detail = _lbl('', color=th.TEXT_SECONDARY, size=th.FS_LABEL)
        self.claim_detail.setWordWrap(True)
        self.claim_detail.hide()
        cl.addWidget(self.claim_detail)

        self.fields_box = QWidget()
        self.fields_layout = QVBoxLayout(self.fields_box)
        self.fields_layout.setContentsMargins(0, 0, 0, 0)
        self.fields_layout.setSpacing(10)
        cl.addWidget(self.fields_box)

        # ---- وسيلة الإعلان ----
        cl.addWidget(_section('وسيلة الإعلان', 'upload'))
        self.contact_box = QWidget()
        self.contact_layout = QGridLayout(self.contact_box)
        self.contact_layout.setContentsMargins(0, 0, 0, 0)
        self.contact_layout.setHorizontalSpacing(10)
        self.contact_layout.setVerticalSpacing(10)
        cl.addWidget(self.contact_box)

        root.addWidget(self.card)

        self._zones_ready.connect(self._set_zones)
        self._claim_ready.connect(self._on_claim_result)
        self._claim_progress.connect(self._on_claim_progress)
        self._claim_file_ready.connect(self._on_claim_file_ready)
        self._zones = []

    # ---- تحميل بيانات طرف ----
    def load(self, form, party):
        """يحمّل بيانات الطرف (من النظام) ويبني حقوله."""
        self.form = form or {}
        self.party = party or {}
        self._build_fields()
        self._fill_header()

    def _fill_header(self):
        name = self.party.get('name', '')
        ptype = self.party.get('type', '')
        self.name_lbl.setText(name)
        self.type_pill.setText(ptype)
        self.type_pill.setVisible(bool(ptype))
        bits = []
        if self.caso_no:
            bits.append('رقم الخبرة: %s' % th.ltr(self.caso_no))
        if self.session_date:
            bits.append('تاريخ الجلسة: %s' % th.ltr(_fmt_date(self.session_date)))
        if self.session_time:
            bits.append('الوقت: %s' % th.ltr(self.session_time))
        self.identity_lbl.setText('  •  '.join(bits))
        if not ilann.form_has_address(self.form):
            self.note_lbl.setText('لا يوجد عنوان مسجّل لهذا الطرف في النظام — '
                                  'عبي البيانات بنفسك قبل الإرسال.')
            self.note_lbl.show()
        else:
            self.note_lbl.hide()

    # ---- بناء الحقول ----
    def _build_fields(self):
        """العنوان: شبكة 4 أعمدة (تسمية فوق الحقل) — ثم الاتصال."""
        while self.fields_layout.count():
            item = self.fields_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.edits = {}
        fields = self.form.get('fields') or {}

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.fields_layout.addLayout(grid)

        # --- الموقع: المحافظة والمنطقة ---
        self.cb_city = QComboBox()
        for code, label in (self.form.get('cities') or list(ilann.GOVERNORATES)):
            self.cb_city.addItem(label, code)
        cidx = self.cb_city.findData(fields.get('ADRS_CITY', ''))
        if cidx >= 0:
            self.cb_city.setCurrentIndex(cidx)
        self.cb_city.setStyleSheet(COMBO_QSS)
        self.cb_city.setAccessibleName('المحافظة')
        self.cb_city.setMinimumHeight(38)
        grid.addWidget(_grid_field('المحافظة', self.cb_city), 0, 0)

        self.cb_zone = QComboBox()
        self.cb_zone.setStyleSheet(COMBO_QSS)
        self.cb_zone.setAccessibleName('المنطقة')
        self.cb_zone.setMinimumHeight(38)
        grid.addWidget(_grid_field('المنطقة', self.cb_zone), 0, 1)

        # --- حقول العنوان (نفس تسلسل النموذج المرجعي) ---
        addr_fields = (
            ('ADRS_BLOCK', 'القطعة'),
            ('ADRS_STREET', 'الشارع'),
            ('ADRS_KASIMA', 'الجادة'),
            ('ADRS_BUILDING_NO', 'المبنى / المسيمة'),
            ('ADRS_FLOOR', 'الدور'),
            ('ADRS_UNIT_NO', 'رقم الوحدة / المكتب'),
            ('ADRS_UNIT_TYPE', 'نوع الوحدة'),
            ('ADRS_DESCR', 'الوصف'),
            ('MAIN_CNTD_TYPE_DESC', 'عنوان آخر'),
        )
        limits = self.form.get('limits') or {}
        col = 2
        row = 0
        for name, label in addr_fields:
            # ⚠️ حدّ الحقل من نموذج النظام (`maxlength`) — الموقع يقصّها في المتصفح،
            #    ولو أرسلنا قيمة أطول رفضها السيرفر بـORA-12899 (15/11/2026).
            lim = ilann.field_limit(name, limits)
            val = ilann.truncate_field(name, fields.get(name, ''), limits)
            e = QLineEdit(val)
            if lim:
                e.setMaxLength(lim)
            e.setStyleSheet(_field_qss())
            e.setAlignment(th.ARIGHT)
            e.setAccessibleName(label)
            e.setMinimumHeight(38)
            self.edits[name] = e
            grid.addWidget(_grid_field(label, e), row, col)
            col += 1
            if col > 3:
                col = 0
                row += 1

        # --- وسيلة الاتصال + الرقم + الملاحظات ---
        while self.contact_layout.count():
            item = self.contact_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self.cb_method = QComboBox()
        for code, label in (self.form.get('methods') or list(ilann.CONTACT_METHODS.items())):
            self.cb_method.addItem(label, code)
        midx = self.cb_method.findData(fields.get('MAIN_CNTD_CODE_NEW', ''))
        if midx >= 0:
            self.cb_method.setCurrentIndex(midx)
        self.cb_method.setStyleSheet(COMBO_QSS)
        self.cb_method.setAccessibleName('وسيلة الاتصال')
        self.cb_method.setMinimumHeight(38)
        self.contact_layout.addWidget(_grid_field('وسيلة الإعلان', self.cb_method), 0, 0)

        e_no = QLineEdit(ilann.clean_value(fields.get('ADDRNO', '')))
        e_no.setStyleSheet(_field_qss())
        e_no.setAlignment(th.ARIGHT)
        e_no.setMaxLength(12)
        e_no.setAccessibleName('رقم الاتصال')
        e_no.setMinimumHeight(38)
        self.edits['ADDRNO'] = e_no
        self.contact_layout.addWidget(_grid_field('رقم الاتصال', e_no), 0, 1)

        e_note = QLineEdit(ilann.clean_value(fields.get('EIF_NOTE', '')))
        e_note.setStyleSheet(_field_qss())
        e_note.setAlignment(th.ARIGHT)
        e_note.setMaxLength(150)
        e_note.setAccessibleName('الملاحظات')
        e_note.setMinimumHeight(38)
        self.edits['EIF_NOTE'] = e_note
        self.contact_layout.addWidget(_grid_field('الملاحظات', e_note), 0, 2, 1, 2)

        # --- المناطق تُجلب من النظام حسب المحافظة ---
        self.cb_city.currentIndexChanged.connect(
            lambda _i: self._load_zones(self.cb_city.currentData()))
        self._fill_zones(self.form.get('zones') or [], fields.get('ADRS_ZONE', ''))
        self._load_zones(self.cb_city.currentData())

    # ---- المناطق ----
    def _load_zones(self, gov_id):
        if not gov_id:
            return
        cookies = self.cookies

        def work():
            try:
                zones = ilann.fetch_zones(cookies, gov_id)
            except Exception:
                zones = []
            try:
                self._zones_ready.emit(zones)
            except RuntimeError:
                pass    # النموذج انحذف (بدّلنا الطرف) — الخيط يخلص بهدوء

        threading.Thread(target=work, daemon=True).start()

    def _set_zones(self, zones):
        if not zones:
            return
        self._zones = zones
        current = (self.form.get('fields') or {}).get('ADRS_ZONE', '')
        self._fill_zones(zones, current)
        # المناطق وصلت بعد ما سحبنا العنوان ⟵ نطابق اسم المنطقة الآن
        if self._claim_data:
            self._apply_claim_data(self._claim_data)

    def _fill_zones(self, zones, current=''):
        if self.cb_zone is None:
            return
        self.cb_zone.blockSignals(True)
        self.cb_zone.clear()
        for code, label in zones:
            self.cb_zone.addItem(label, code)
        idx = self.cb_zone.findData(current)
        if idx >= 0:
            self.cb_zone.setCurrentIndex(idx)
        self.cb_zone.blockSignals(False)

    # ---- سحب العنوان من صحيفة الدعوى ----
    def _on_claim(self):
        """زر «سحب العنوان من صحيفة الدعوى» — جلب وتحليل بالذكاء (بخيط خلفي)."""
        if self._claim_busy:
            return
        if not self.auto_no and not ilann_claim.find_local_claim(self.caso_no):
            self._set_claim_status('ما فيه رقم آلي للقضية — تعذّر جلب صحيفة الدعوى.',
                                   th.AMBER_TEXT)
            return
        self._claim_busy = True
        self.btn_claim.setEnabled(False)
        self._set_claim_status('جاري سحب المعلومات من صحيفة الدعوى…', th.AMBER_TEXT)
        cookies = self.cookies
        auto_no = self.auto_no
        caso_no = self.caso_no
        name = self.party.get('name', '')
        ptype = self.party.get('type', '')

        def work():
            def progress(msg):
                try:
                    self._claim_progress.emit(msg)
                except RuntimeError:
                    pass
            try:
                data, err, msg = ilann_claim.fetch_and_extract(cookies, auto_no,
                                                               name, ptype,
                                                               caso_no=caso_no,
                                                               progress=progress)
            except Exception as e:
                data, err, msg = None, None, 'تعذّر سحب العنوان: %s' % e
            payload = {'ok': bool(data), 'error': err or '', 'message': msg or '',
                       'data': data}
            try:
                self._claim_ready.emit(payload)
            except RuntimeError:
                pass    # النموذج انحذف — الخيط يخلص بهدوء

        threading.Thread(target=work, daemon=True).start()

    def _on_claim_progress(self, text):
        """تحديثات الخطوات (تأكّد/تنزيل/تحويل/إرسال) — بنفس سطر الحالة."""
        self._set_claim_status(text, th.AMBER_TEXT)

    # ---- عرض صحيفة الدعوى (يسار الشاشة) ----
    def _on_view_claim(self):
        """زر «عرض صحيفة الدعوى» — يفتحها على **يسار الشاشة** (مشاهدة مباشرة).

        لو ما عندنا نسخة محفوظة ⟵ نجيبها من الملف الآلي (بدون ذكاء) ثم نفتحها.
        """
        path = ilann_claim.find_local_claim(self.caso_no)
        if path:
            self._open_claim_window(path)
            return
        if self._view_busy:
            return
        if not self.auto_no:
            self._set_claim_status('ما فيه رقم آلي للقضية — تعذّر جلب صحيفة الدعوى.',
                                   th.AMBER_TEXT)
            return
        self._view_busy = True
        self.btn_view_claim.setEnabled(False)
        self._set_claim_status('جاري جلب صحيفة الدعوى…', th.AMBER_TEXT)
        cookies = self.cookies
        auto_no = self.auto_no
        caso_no = self.caso_no

        def work():
            def progress(msg):
                try:
                    self._claim_progress.emit(msg)
                except RuntimeError:
                    pass
            try:
                prep = ilann_claim.ensure_claim_markdown(cookies, caso_no, auto_no,
                                                           progress=progress)
            except Exception as e:
                prep = {'ok': False, 'pdf': '', 'message': 'تعذّر جلب صحيفة الدعوى: %s' % e}
            try:
                self._claim_file_ready.emit({'ok': bool(prep.get('ok')),
                                             'pdf': prep.get('pdf') or '',
                                             'message': prep.get('message') or ''})
            except RuntimeError:
                pass    # النموذج انحذف — الخيط يخلص بهدوء

        threading.Thread(target=work, daemon=True).start()

    def _on_claim_file_ready(self, payload):
        """نتيجة جلب صحيفة الدعوى (على خيط الواجهة) — نفتحها."""
        self._view_busy = False
        if getattr(self, 'btn_view_claim', None) is not None:
            self.btn_view_claim.setEnabled(True)
        pdf = payload.get('pdf') or ''
        if payload.get('ok') and pdf and os.path.exists(pdf):
            self._set_claim_status('صحيفة الدعوى جاهزة للمشاهدة', th.EMERALD_TEXT)
            self._open_claim_window(pdf)
            return
        msg = payload.get('message') or 'ما قدرنا نجلب صحيفة الدعوى.'
        self._set_claim_status(msg.split(' — ')[0], th.DANGER_TEXT, detail=msg)
        self.claim_done.emit({'ok': False, 'message': msg, 'color': th.DANGER_TEXT})

    def _open_claim_window(self, path):
        """يفتح نافذة المشاهدة (يسار الشاشة) — المرجع محفوظ بالنافذة أم."""
        host = self.window()
        prev = getattr(host, '_claim_viewer', None)
        if prev is not None:
            try:
                if prev.isVisible():        # مفتوحة ⟵ نرفعها بدل ما نفتح ثانية
                    prev.raise_()
                    prev.activateWindow()
                    return
            except RuntimeError:
                pass
        try:
            win = open_claim_viewer(host, path,
                                     'صحيفة الدعوى — %s' % (self.caso_no or ''))
        except Exception as e:
            self._set_claim_status('تعذّر فتح صحيفة الدعوى: %s' % e, th.DANGER_TEXT)
            return
        try:
            host._claim_viewer = win      # عشان ما تنحذف النافذة مع المرجع
        except Exception:
            pass

    def _on_claim_result(self, payload):
        """نتيجة السحب (على خيط الواجهة) — ملء الحقول."""
        self._claim_busy = False
        if getattr(self, 'btn_claim', None) is not None:
            self.btn_claim.setEnabled(True)
        data = payload.get('data')
        if not data:
            msg = (payload.get('error') or payload.get('message')
                   or 'ما قدرنا نستخرج العنوان.')
            # الجواب قصير جنب الزر، والتفصيل (شنو مالقيت) تحته
            short = msg.split(' — ')[0]
            self._set_claim_status(short, th.DANGER_TEXT, detail=msg)
            self.claim_done.emit({'ok': False, 'message': msg, 'color': th.DANGER_TEXT})
            return
        values = self._apply_claim_data(data)
        if values.get('fields'):
            msg = ilann_claim.summary_of(values)
            color = th.EMERALD_TEXT
            short = 'تم استخراج العنوان'
        else:
            msg = 'ما لقينا تفاصيل عنوان بالصحيفة — راجع الحقول بنفسك.'
            color = th.AMBER_TEXT
            short = 'ما لقينا تفاصيل عنوان'
        self._set_claim_status(short, color, detail=msg)
        self.claim_done.emit({'ok': True, 'message': msg, 'color': color})

    def _apply_claim_data(self, data):
        """يحوّل رد الذكاء إلى قيم الحقول ويملؤها.

        ينادى مرة ثانية عند وصول المناطق ⟵ نطابق اسم المنطقة مع قائمة المناطق.
        """
        self._claim_data = data
        cities = [(self.cb_city.itemData(i), self.cb_city.itemText(i))
                  for i in range(self.cb_city.count())]
        zones = [(self.cb_zone.itemData(i), self.cb_zone.itemText(i))
                 for i in range(self.cb_zone.count())]
        values = ilann_claim.build_values(data, cities=cities, zones=zones)
        # المحافظة
        if values.get('city_code'):
            idx = self.cb_city.findData(values['city_code'])
            if idx >= 0:
                self.cb_city.setCurrentIndex(idx)
        # المنطقة
        if values.get('zone_code'):
            idx = self.cb_zone.findData(values['zone_code'])
            if idx >= 0:
                self.cb_zone.setCurrentIndex(idx)
        # وسيلة الإعلان (مندوب لو فيه محامٍ)
        if values.get('method'):
            idx = self.cb_method.findData(values['method'])
            if idx >= 0:
                self.cb_method.setCurrentIndex(idx)
        # خانات العنوان والاتصال
        for name, value in (values.get('fields') or {}).items():
            edit = self.edits.get(name)
            if edit is not None and value:
                edit.setText(value)
        return values

    def _set_claim_status(self, text, color=None, detail=''):
        """سطر الحالة **جنب الزر** + سطر التفاصيل تحت.

        الجواب (نجاح/فشل) يطلع مكان «جاري السحب» بالضبط — مو في مكان ثاني.
        """
        self.claim_lbl.setFullText(text or '')
        self.claim_lbl.setStyleSheet(
            "color:%s; font-size:%spx; font-weight:%s; background:transparent; border:none;"
            % (color or th.TEXT_SECONDARY, th.FS_LABEL, th.W_BOLD))
        self.claim_lbl.setVisible(bool(text))
        self.claim_detail.setText(detail or '')
        self.claim_detail.setStyleSheet(
            "color:%s; font-size:%spx; font-weight:%s; background:transparent; border:none;"
            % (color or th.TEXT_SECONDARY, th.FS_LABEL, th.W_REGULAR))
        self.claim_detail.setVisible(bool(detail))

    # ---- القيم والإرسال ----
    def focus_first_field(self):
        """التركيز على أول حقل قابل للتحرير — بداية سريعة وقارئ شاشة يعرف وين."""
        target = None
        for edit in self.edits.values():
            if edit.text().strip():
                target = edit
                break
        if target is None and self.edits:
            target = next(iter(self.edits.values()))
        if target is not None:
            target.setFocus(Qt.FocusReason.OtherFocusReason)
            # بدون تحديد النص (الوضع العادي للتركيز بالماوس)
            target.setCursorPosition(len(target.text()))
            target.deselect()

    def values(self):
        """القيم الحالية من النموذج (بأسماء حقول النظام)."""
        v = dict(self.form.get('fields') or {})
        v['MAIN_CNTD_CODE_NEW'] = self.cb_method.currentData() or ''
        v['ADRS_CITY'] = self.cb_city.currentData() or ''
        v['ADRS_ZONE'] = self.cb_zone.currentData() or ''
        for name, edit in self.edits.items():
            v[name] = edit.text()
        return v

    def _on_send(self):
        vals = self.values()
        street = vals.get('ADRS_STREET', '')
        descr = vals.get('ADRS_DESCR', '')
        address = ' '.join(x for x in (street, descr) if x).strip()
        rows = [
            ('رقم الخبرة', self.caso_no or '—', True),
            ('تاريخ الجلسة', _fmt_date(self.session_date), True),
            ('وقت الجلسة', self.session_time or '—', True),
            ('الطرف', self.party.get('name', '')),
            ('الصفة', self.party.get('type', '')),
            ('وسيلة الإعلان', self.cb_method.currentText()),
            ('رقم الاتصال', vals.get('ADDRNO', '') or '—', True),
            ('العنوان', address or '—'),
        ]
        dlg = _ConfirmSend(rows, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.submitted.emit(vals)


# ---------------------------------------------------------------------------
# النافذة
# ---------------------------------------------------------------------------

class IlannDialog(QDialog):
    """«طلب إعلان» — جلسة قادمة معروفة (من بطاقة الجلسة).

    ما في خطوة «جلب قضية»: رقم الخبرة والجلسة والعنوان جايين من بطاقة الجلسة،
    والأطراف تُجلب من النظام مباشرة.
    """

    _loaded = pyqtSignal(dict)
    _failed = pyqtSignal(str)
    _form_ready = pyqtSignal(dict)
    _form_failed = pyqtSignal(dict)
    _sent = pyqtSignal(dict)

    def __init__(self, cookies, caso_no, data=None, auto_no='', session_date='',
                 session_time='', case_title='', current_user='', read_only=False,
                 parent=None):
        super().__init__(parent)
        self.cookies = cookies
        # ⚠️ read_only = «عرض الحالة فقط» — الجلسة مضى وقتها (نفس اليوم بعد وقت
        #    الجلسة). نظام الخبراء يرفض إعلاناً لجلسة سابقة (رد «4»)، فنعرض
        #    «نتيجة الإعلان» و«حالة كل طرف» بدون زر إرسال. (18/11/2026)
        self.read_only = bool(read_only)
        self.current_user = current_user or ''
        self.caso_no = caso_no or ''
        self.auto_no = auto_no or ''
        self.session_date = session_date or ''
        self.session_time = session_time or ''
        self.case_title = case_title or ''
        self.data = {'ok': False, 'case': {}, 'parties': [], 'results': [], 'message': ''}
        self._party_form = None
        self._selected = None
        self._empty_note = 'ما فيه إعلان بعد لهذه الجلسة.'
        #: 'busy' = رسالة لحظية (تختفي) · 'outcome' = نتيجة مهمة (تبقى)
        self._state_kind = ''
        self._connected = None      # None = ما انقيس · True · False

        self.setWindowTitle('%s — %s' % ('حالة الإعلان' if self.read_only else 'طلب إعلان',
                                         self.caso_no or ''))
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._build_titlebar()

        # ---- المحتوى (كله داخل منطقة تمرير — ما ينقص على شاشة 660px) ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # تمرير أفقي عند الحاجة (ما نخسر أي عمود على شاشة ضيّقة)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # ⚠️Ignored: ما نسمح لعرض المحتوى (الصور/الجدول) أن يفرض عرضاً
        #    أكبر من الشاشة على النافذة — التخطيط يمرّر أفقياً بدل ما يقصّ.
        scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        content = QWidget()
        content.setStyleSheet("background:transparent;")
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(16, 14, 16, 14)
        self.content_layout.setSpacing(14)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self._build_facts()
        self._build_readonly_banner()
        self._build_parties()
        self._build_form_holder()
        self._build_results()

        self._build_actionbar()

        # ⚠️ المقاس يُحسب على الشاشة الفعلية (بعد زوم ويندوز): شاشة 1366×768
        #    بـ150% تصير 911×512 منطقية — لو ثبّتنا 1120×780 لفتحت النافذة
        #    أكبر من الشاشة وطلع زر «إرسال الإعلان» (Far يسار) براها.
        #    ⚠️ لازم يكون **بعد** بناء التخطيط: قبلها ما في تخطيط نرخي
        #    قيده (وهو اللي كان يفرض عرض 2000+ بكسل ويقصّ الأزرار).
        qt_fit.apply_fit(self, prefer=(1120, 780), minimum=(840, 560))

        self._loaded.connect(self._on_loaded)
        self._failed.connect(self._on_failed)
        self._form_ready.connect(self._on_form_ready)
        self._form_failed.connect(self._on_form_failed)
        self._sent.connect(self._on_sent)

        if data:
            self._apply_data(data)
        else:
            self.refresh()

    def showEvent(self, e):
        """لو تغيّر زوم الشاشة بين الإنشاء والفتح — نرجّع النافذة جوّا الشاشة
        (ما يبقى شريط الإجراءات — ولا حتى زر الإرسال — برا الشاشة)."""
        super().showEvent(e)
        qt_fit.keep_on_screen(self)

    # ------------------------------------------------------------------
    # بناء الأقسام
    # ------------------------------------------------------------------
    def _build_titlebar(self):
        """شريط علوي كحلي: اسم الشاشة + رقم الخبرة (نمط التصميم المرجعي)."""
        bar = QFrame()
        bar.setObjectName('titlebar')
        bar.setStyleSheet(f"QFrame#titlebar {{ background:{th.NAVY}; border:none; }}")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(10)

        title = QLabel('حالة الإعلان' if self.read_only else 'طلب إعلان')
        title.setStyleSheet(f"color:{th.SURFACE}; font-size:18px; font-weight:700;"
                            f" background:transparent; border:none;")
        lay.addWidget(title)
        if self.caso_no:
            num = QLabel(th.ltr(self.caso_no))
            num.setStyleSheet(f"color:{th.EMERALD_ON_NAVY}; font-size:18px; font-weight:700;"
                              f" background:transparent; border:none;")
            lay.addWidget(num)
        lay.addStretch()
        brand = QLabel('نظام الخبراء — وزارة العدل')
        brand.setStyleSheet(f"color:{th.SIDEBAR_TEXT_MUTED}; font-size:12px;"
                            f" background:transparent; border:none;")
        lay.addWidget(brand)
        self.titlebar = bar
        root = self.layout()
        root.insertWidget(0, bar)

    def _build_facts(self):
        """صف بطاقات الهوية (رقم الخبرة · القضية · الآلي · التاريخ · الوقت) — بعرض الصفحة."""
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        # ⚠️ التسمية تتبع الحالة: جلسة قادمة ⟵ «القادمة» · جلسة مضى وقتها ⟵ «الجلسة»
        #    (sessions_page يمرّر read_only للجلسة المنقضية).
        date_label = 'تاريخ الجلسة' if self.read_only else 'تاريخ الجلسة القادمة'
        time_label = 'وقت الجلسة' if self.read_only else 'وقت الجلسة القادمة'

        row.addWidget(_fact('رقم ملف الخبرة', self.caso_no or '—', latin=True,
                            **_fact_icon('caso')), 1)
        self.fact_case_no = _fact('رقم القضية', '—', latin=True, **_fact_icon('case'))
        self.fact_auto_no = _fact('الرقم الآلي للقضية', self.auto_no or '—', latin=True,
                                  **_fact_icon('auto'))
        row.addWidget(self.fact_case_no, 1)
        row.addWidget(self.fact_auto_no, 1)
        row.addWidget(_fact(date_label, _fmt_date(self.session_date),
                            **_fact_icon('date')), 1)
        row.addWidget(_fact(time_label, self.session_time or '—', latin=True,
                            **_fact_icon('time')), 1)
        self.content_layout.addWidget(wrap)

    def _build_readonly_banner(self):
        """شريط تنبيه «عرض الحالة فقط» — يظهر للجلسة اللي مضى وقتها.

        السبب: نظام الخبراء يرفض إعلاناً لجلسة سابقة (رد «4»)، فبدل ما نخفي
        الشاشة بالكامل (الخبير يحتاج يشوف شنو صار بالإعلان) نعرض الحالة فقط.
        """
        if not self.read_only:
            self.readonly_banner = None
            return
        box = QFrame()
        box.setObjectName('readonly_banner')
        box.setStyleSheet(
            f"QFrame#readonly_banner {{ background:{th.AMBER_BG}; border:1px solid {th.AMBER};"
            f" border-radius:12px; }}")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)
        lay.addWidget(_icon('info', th.AMBER, 18))
        txt = _lbl('جلسة مضى وقتها — نعرض حالة الإعلان فقط. '
                   'الإرسال متوقف لأن نظام الخبراء ما يقبل إعلاناً لجلسة سابقة.',
                   color=th.AMBER_TEXT, size=th.FS_BODY)
        txt.setWordWrap(True)
        lay.addWidget(txt, 1)
        self.readonly_banner = box
        self.content_layout.addWidget(box)

    def _build_parties(self):
        card = Card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(10)

        cap = QHBoxLayout()
        cap.setSpacing(10)
        cap.addWidget(_lbl('أطراف الدعوى والخصوم', bold=True, size=th.FS_TITLE))
        self.parties_count = _pill('0 طرف', th.NAVY_TINT, th.NAVY)
        cap.addWidget(self.parties_count)
        cap.addStretch()
        # ⚠️ في وضع «عرض الحالة» ما فيه إعلان ⟵ نعرض حالة كل طرف بدل الدعوة للإعلان
        cap.addWidget(_icon('info', th.AMBER if not self.read_only else th.NAVY, 16))
        cap.addWidget(_lbl(
            'حالة إعلان كل طرف — «تم» أو «فشل» مع السبب' if self.read_only
            else 'اضغط «إعلان» بجانب الطرف المطلوب لإعلانه',
            color=th.TEXT_SECONDARY, size=th.FS_LABEL))
        cl.addLayout(cap)

        self.parties_box = QWidget()
        self.parties_layout = QVBoxLayout(self.parties_box)
        self.parties_layout.setContentsMargins(0, 0, 0, 0)
        self.parties_layout.setSpacing(10)
        cl.addWidget(self.parties_box)

        self.content_layout.addWidget(card)

    def _build_form_holder(self):
        """مكان النموذج — يظهر تحت قائمة الأطراف بعد الضغط «إعلان»."""
        self.form_holder = QWidget()
        self.form_layout = QVBoxLayout(self.form_holder)
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_layout.setSpacing(0)
        self.content_layout.addWidget(self.form_holder)

    def _build_results(self):
        card = Card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(10)

        cap = QHBoxLayout()
        cap.setSpacing(10)
        cap.addWidget(_lbl('نتيجة الإعلان', bold=True, size=th.FS_TITLE))
        # ⚠️ لو القراءة جت على مستوى القضية (الجلسة المنقضية) ⟵ نقول للخبير
        #    إن النتائج مو مربوطة بجلسة واحدة (عنده عمود «تاريخ الجلسة»).
        self.results_note = _lbl('', color=th.AMBER_TEXT, size=th.FS_LABEL)
        self.results_note.setWordWrap(True)
        self.results_note.hide()
        cap.addWidget(self.results_note, 1)
        cap.addStretch()
        cl.addLayout(cap)

        self.tbl_results = QTableWidget(0, 6)
        self.tbl_results.setHorizontalHeaderLabels(
            ['الاسم', 'وسيلة الإعلان', 'تاريخ الإعلان', 'تاريخ الجلسة',
             'حالة الإعلان', 'سبب التعذر'])
        self.tbl_results.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.tbl_results.verticalHeader().setVisible(False)
        self.tbl_results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_results.setWordWrap(True)
        self.tbl_results.setAlternatingRowColors(True)
        self.tbl_results.setStyleSheet(TABLE_QSS)
        self.tbl_results.verticalHeader().setDefaultSectionSize(34)
        # الجدول يأخذ ارتفاع صفوفه فقط — ما يتمدّد بفراغ تحت المحتوى
        self.tbl_results.setSizePolicy(QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Maximum)
        hdr = self.tbl_results.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        cl.addWidget(self.tbl_results)

        # حالة «ما فيه إعلان بعد» — بدل جدول فاضي (Honest Figures Rule)
        self.results_empty = QWidget()
        el = QHBoxLayout(self.results_empty)
        el.setContentsMargins(0, 18, 0, 18)
        el.setSpacing(6)
        el.addWidget(_icon('seal', th.TEXT_MUTED, 18))
        self.results_empty_lbl = _lbl(self._empty_note, color=th.TEXT_SECONDARY,
                                      size=th.FS_LABEL)
        el.addWidget(self.results_empty_lbl)
        el.addStretch()
        self.results_empty.hide()
        cl.addWidget(self.results_empty)

        self.content_layout.addWidget(card)
        # الفراغ الزايد ينزل تحت — مو بين الأقسام (ما تتشرب المسافات)
        self.content_layout.addStretch()

    def _build_actionbar(self):
        """شريط الإجراءات السفلي الثابت (نمط التصميم المرجعي)."""
        bar = QFrame()
        bar.setObjectName('actionbar')
        bar.setStyleSheet(f"QFrame#actionbar {{ background:{th.SURFACE};"
                          f" border-top:1px solid {th.BORDER}; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        # ---- حالة الاتصال (يمين) ----
        self.conn_dot = _dot(th.TEXT_MUTED, 10)
        lay.addWidget(self.conn_dot)
        self.conn_lbl = _lbl('جاري الاتصال…', color=th.TEXT_SECONDARY, size=th.FS_LABEL)
        self.conn_lbl.setStyleSheet(
            f"color:{th.TEXT_SECONDARY}; font-size:{th.FS_LABEL}px; font-weight:700;"
            f" background:{th.EMERALD_BG}; border-radius:12px; padding:4px 12px;"
            f" border:1px solid {th.EMERALD_BG};")
        # الشارة نصّها قصير («متصل») — النص الكامل بالتلميح؛ كذا ما تفرض
        # الشارة عرضاً كبيراً على الشريط (شاشة ضيّقة/زوم).
        self.conn_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.conn_lbl.setToolTip('حالة الاتصال بنظام الخبراء')
        lay.addWidget(self.conn_lbl)

        self.lbl_state = _lbl('', color=th.TEXT_SECONDARY, size=th.FS_LABEL)
        self.lbl_state.setWordWrap(True)
        # ⚠️ نص الحالة هو العنصر المطّاطي الوحيد — لازم ينكمش (مو يفرض
        #    حدّاً أدنى على العرض) وإلا انزاحت الأزرار (وزر الإرسال) برا
        #    الشاشة على الأجهزة اللي فيها زوم.
        self.lbl_state.setMinimumWidth(0)
        self.lbl_state.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # قارئ الشاشة يقرأ النتيجة لو وصله التركيز (FocusReason)
        self.lbl_state.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.lbl_state.setAccessibleName('حالة طلب الإعلان')
        lay.addWidget(self.lbl_state, 1)

        lay.addStretch()

        # ---- الأزرار (يسار) ----
        btn_close = SecondaryButton('إغلاق')
        btn_close.setFixedHeight(38)
        btn_close.setAccessibleName('إغلاق نافذة طلب إعلان')
        btn_close.clicked.connect(self.accept)
        lay.addWidget(btn_close)

        btn_refresh = SecondaryButton('تحديث')
        btn_refresh.setFixedHeight(38)
        btn_refresh.setIcon(ic.icon('refresh', th.TEXT_SECONDARY, size=16))
        btn_refresh.setAccessibleName('تحديث بيانات القضية')
        btn_refresh.clicked.connect(self.refresh)
        lay.addWidget(btn_refresh)

        self.btn_print = SecondaryButton('طباعة إشعار الإعلان')
        self.btn_print.setFixedHeight(38)
        self.btn_print.setIcon(ic.icon('print', th.TEXT_SECONDARY, size=16))
        self.btn_print.setAccessibleName('طباعة إشعار الإعلان')
        self.btn_print.clicked.connect(self._on_print)
        lay.addWidget(self.btn_print)

        self.btn_send = PrimaryButton('إرسال الإعلان')
        self.btn_send.setFixedHeight(38)
        self.btn_send.setMinimumWidth(150)
        # بدون أيقونة: زر الإرسال ما له علاقة برفع ملفات (طلب العنزي 15/11/2026)
        self.btn_send.setAccessibleName('إرسال الإعلان — كتابة في نظام الخبراء')
        self.btn_send.clicked.connect(self._send_selected)
        self.btn_send.setEnabled(False)
        lay.addWidget(self.btn_send)

        # ⚠️ وضع «عرض الحالة» (الجلسة مضى وقتها): ما فيه إرسال ⟵ نخفي الزر
        #    ونقول بالخطر شنو صاير بدل ما الخبير يضغط وما يصير شي.
        if self.read_only:
            self.btn_send.hide()
            self._set_state('عرض الحالة فقط — الإرسال متوقف (الجلسة مضى وقتها).',
                            color=th.AMBER_TEXT)

        self.actionbar = bar
        self.layout().addWidget(bar)

    # ------------------------------------------------------------------
    # البيانات
    # ------------------------------------------------------------------
    def _apply_data(self, data):
        self.data = data or {'ok': False, 'case': {}, 'parties': [], 'results': [],
                             'message': ''}
        case = self.data.get('case') or {}
        self.fact_case_no.value_lbl.setText(
            th.ltr(ilann.case_field(case, 'case_no', '—') or '—'))
        auto = ilann.case_field(case, 'auto_no', self.auto_no or '—') or '—'
        # نثبّت الرقم الآلي المحلول (نحتاجه لجلب صحيفة الدعوى)
        resolved = ilann.case_field(case, 'auto_no', self.auto_no or '')
        if resolved:
            self.auto_no = resolved
        self.fact_auto_no.value_lbl.setText(th.ltr(auto))

        if not self.data.get('ok'):
            reason = self.data.get('reason')
            title = ('تعذّر الاتصال بنظام الخبراء' if reason == 'connection'
                     else (self.data.get('message') or 'لا توجد بيانات'))
            self._clear_parties()
            self.parties_layout.addWidget(_state(
                'offline' if reason == 'connection' else 'gov', title,
                'جرّب «تحديث» بعد ما تتأكد من الاتصال.',
                retry_cb=self.refresh))
            offline = (reason == 'connection')
            self._fill_results([], note=('ما قدرنا نجيب نتيجة الإعلان — تعذّر الاتصال بنظام الخبراء.'
                                         if offline else 'ما في نتيجة إعلان — النظام ما رجّع بيانات لهذه القضية.'))
            self.btn_print.setEnabled(False)
            self._set_connection(not offline)   # «لا توجد بيانات» ≠ انقطاع اتصال
            return

        self._fill_parties(self.data.get('parties') or [])
        self._fill_results(self.data.get('results') or [])
        # الطباعة بإعلان فعلي فقط (ما نطبع إشعار فاضي)
        self.btn_print.setEnabled(bool(self.data.get('results')))
        self._set_connection(True)
        # ⚠️ النتائج على مستوى القضية (ما قدرنا نحدد الجلسة) ⟵ نوضّح للخبير
        if getattr(self, 'results_note', None) is not None:
            if self.data.get('case_level'):
                self.results_note.setText(
                    'النتائج على مستوى القضية (ما قدرنا نحدد الجلسة) — '
                    'راجع عمود «تاريخ الجلسة».')
                self.results_note.show()
            else:
                self.results_note.hide()

    def _set_connection(self, ok):
        """حالة الاتصال بالشريط السفلي (نقطة + شارة)."""
        self._connected = ok
        if ok:
            self.conn_dot.setStyleSheet(
                f"background:{th.EMERALD}; border:none; border-radius:5px;")
            self.conn_lbl.setText('متصل')
            self.conn_lbl.setToolTip('متصل بنظام إدارة الإعلانات — وزارة العدل')
            self.conn_lbl.setStyleSheet(
                f"color:{th.EMERALD_TEXT}; font-size:{th.FS_LABEL}px; font-weight:700;"
                f" background:{th.EMERALD_BG}; border-radius:12px; padding:4px 12px;"
                f" border:1px solid {th.EMERALD_BG};")
        else:
            self.conn_dot.setStyleSheet(
                f"background:{th.DANGER}; border:none; border-radius:5px;")
            self.conn_lbl.setText('تعذّر الاتصال')
            self.conn_lbl.setToolTip('تعذّر الاتصال بنظام الخبراء')
            self.conn_lbl.setStyleSheet(
                f"color:{th.DANGER_TEXT}; font-size:{th.FS_LABEL}px; font-weight:700;"
                f" background:{th.DANGER_BG}; border-radius:12px; padding:4px 12px;"
                f" border:1px solid {th.DANGER_BG};")

    def _clear_parties(self):
        while self.parties_layout.count():
            item = self.parties_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _fill_parties(self, parties):
        self._clear_parties()
        if not parties:
            self.parties_count.setText('0 طرف')
            self.parties_layout.addWidget(_state(
                'gov', 'لا يوجد أطراف في هذه القضية',
                'ما ظهر طرف واحد من نظام الخبراء — تأكد من رقم الخبرة.'))
            return
        self.parties_count.setText('%d طرف' % len(parties))
        for party in parties:
            self.parties_layout.addWidget(self._party_row(party))

    def _party_status(self, name):
        """حالة إعلان الطرف من جدول النتائج (تم/فشل/ما انعلن)."""
        target = (name or '').strip()
        for row in (self.data.get('results') or []):
            if (row.get('name') or '').strip() != target:
                continue
            status = (row.get('status') or '').strip()
            if 'تم' in status:
                return 'done'
            if ('فشل' in status) or ('تعذر' in status) or ('تعذّر' in status):
                return 'failed'
            return 'other'
        return None

    def _party_row(self, party):
        row = QFrame()
        row.setObjectName('party')
        selected = (self._selected is not None
                    and self._selected.get('part_id') == party.get('part_id'))
        if selected:
            row.setStyleSheet(f"QFrame#party {{ background:{th.NAVY_TINT};"
                              f" border:2px solid {th.NAVY}; border-radius:12px; }}")
        else:
            row.setStyleSheet(f"QFrame#party {{ background:{th.SURFACE};"
                              f" border:1px solid {th.BORDER}; border-radius:12px; }}")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # ---- الطرف (يمين) ----
        status = self._party_status(party.get('name', ''))
        dot_color = th.EMERALD if status == 'done' else (
            th.DANGER if status == 'failed' else th.TEXT_MUTED)
        if selected:
            dot_color = th.NAVY       # المختار ⟵ نقطته كحلية (مو رمادية)
        lay.addWidget(_dot(dot_color, 10))

        name = _ElidedLabel(party.get('name', ''))
        name.setStyleSheet(f"color:{th.NAVY if selected else th.TEXT_PRIMARY};"
                           f" font-size:{th.FS_TITLE}px;"
                           f" font-weight:{th.W_MEDIUM}; background:transparent; border:none;")
        lay.addWidget(name, 1)

        ptype = party.get('type', '')
        if ptype:
            lay.addWidget(_pill(ptype, th.NAVY_TINT, th.NAVY))
        if selected:
            lay.addWidget(_pill('محدد', th.NAVY, th.SURFACE))
        if status == 'done':
            lay.addWidget(_pill('تم', th.EMERALD_BG, th.EMERALD_TEXT))
        elif status == 'failed':
            lay.addWidget(_pill('فشل', th.DANGER_BG, th.DANGER_TEXT))

        lay.addStretch()

        # ---- الزر (يسار) — نفس التسمية دائماً: «إعلان» ----
        # ⚠️ وضع «عرض الحالة»: ما فيه زر «إعلان» — الجلسة مضى وقتها والنظام
        #    ما يقبل إعلاناً لجلسة سابقة (رد «4»). يظهر بدله شارة الحالة
        #    («تم» / «فشل») على يمين الصف.
        if not self.read_only:
            btn = PrimaryButton('إعلان')
            btn.setFixedHeight(38)
            btn.clicked.connect(lambda _=False, p=party: self._open_party(p))
            btn.setAccessibleName('طلب إعلان — %s' % (party.get('name', '') or 'الطرف'))
            btn.setMinimumWidth(110)
            lay.addWidget(btn)
        return row

    def _fill_results(self, rows, note=None):
        """note: نص حالة «ما فيه إعلان» — يختلف لو فشل الاتصال (ما نقول «ما فيه» وأنا ما جبت)."""
        self._empty_note = note or (
            'ما فيه إعلان مسجّل لهذه الجلسة.' if self.read_only
            else 'ما فيه إعلان بعد لهذه الجلسة.')
        if getattr(self, 'results_empty_lbl', None) is not None:
            self.results_empty_lbl.setText(self._empty_note)
        self.tbl_results.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(('name', 'means', 'date', 'session_date',
                                     'status', 'reason')):
                val = ilann.clean_value(row.get(key, ''))
                it = QTableWidgetItem(val or '—')
                it.setTextAlignment(th.ARIGHT | Qt.AlignmentFlag.AlignVCenter)
                if not val:
                    it.setForeground(QColor(th.TEXT_SECONDARY))
                elif key == 'status':
                    it.setForeground(QColor(_status_color(val)))
                self.tbl_results.setItem(r, c, it)
        self.tbl_results.resizeRowsToContents()
        # بلا نتائج ⟵ رسالة قصيرة بدل جدول فاضي
        if not rows:
            self.tbl_results.hide()
            self.results_empty.show()
            return
        self.tbl_results.show()
        self.results_empty.hide()
        # ارتفاع الجدول = صفوفه فقط (ما يتمدّد بفراغ تحت المحتوى)
        head_h = self.tbl_results.horizontalHeader().height()
        rows_h = sum(self.tbl_results.rowHeight(i) for i in range(self.tbl_results.rowCount()))
        self.tbl_results.setMaximumHeight(max(60, head_h + rows_h + 6))

    # ------------------------------------------------------------------
    # نموذج الطرف
    # ------------------------------------------------------------------
    def _open_party(self, party):
        # ⚠️ وضع «عرض الحالة»: ما نفتح نموذج ولا نسمح بإرسال (18/11/2026)
        if self.read_only:
            return
        part_id = party.get('part_id', '')
        if not part_id:
            self._set_state('ما فيه معرّف طرف لهذا السطر — تعذّر فتح نموذج الإعلان.',
                            color=th.AMBER_TEXT)
            return
        self._selected = party
        self._refresh_party_rows()
        self._clear_form()
        self.form_layout.addWidget(_state('clock', 'جاري جلب بيانات الطرف…'))
        cookies = self.cookies

        def work():
            try:
                form = ilann.fetch_party_form(cookies, part_id)
            except Exception:
                self._emit(self._form_failed, {'party': party})
                return
            self._emit(self._form_ready, {'party': party, 'form': form})

        threading.Thread(target=work, daemon=True).start()

    def _deselect(self, party):
        """إلغاء اختيار الطرف ⟵ ينمسح النموذج وتنعاد صفوف الأطراف."""
        self._selected = None
        self._clear_form()
        self._refresh_party_rows()

    def _refresh_party_rows(self):
        """إعادة بناء صفوف الأطراف (لتحديث الحدود والشارات)."""
        parties = self.data.get('parties') or []
        current = self.parties_layout.count()
        # نحتفظ بالصف الأول لو كان حالة (فراغ/خطأ) — نعيد البناء من الصفر
        if current:
            self._clear_parties()
        if parties:
            for party in parties:
                self.parties_layout.addWidget(self._party_row(party))
        self.btn_send.setEnabled(self._party_form is not None)

    @staticmethod
    def _emit(signal, payload):
        """إرسال نتيجة الخيط بأمان — لو النافذة انغلقت ما يطلع استثناء."""
        try:
            signal.emit(payload)
        except RuntimeError:
            pass

    def _clear_form(self):
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._party_form = None
        if getattr(self, 'btn_send', None) is not None:
            self.btn_send.setEnabled(False)

    def _on_form_ready(self, payload):
        party = payload.get('party') or {}
        form = payload.get('form') or {}
        self._clear_form()
        self._party_form = PartyForm(self.cookies, self.caso_no,
                                     self.session_date, self.session_time,
                                     auto_no=self.auto_no)
        self._party_form.submitted.connect(self._on_submit)
        self._party_form.claim_done.connect(self._on_claim_status)
        self._party_form.load(form, party)
        self.form_layout.addWidget(self._party_form)
        # التركيز على أول حقل — الخبير يكمل من مكان ما انتهى (وقارئ الشاشة يعرف وين)
        self._party_form.focus_first_field()
        self.btn_send.setEnabled(True)

    def _on_form_failed(self, payload):
        party = payload.get('party') or {}
        self._clear_form()
        name = party.get('name', '') or 'الطرف'
        self.form_layout.addWidget(_state(
            'offline', 'تعذّر الاتصال بالنظام',
            'ما قدرنا نجيب بيانات %s من نظام الخبراء.' % name,
            retry_cb=lambda: self._open_party(party)))

    def _on_claim_status(self, payload):
        """نتيجة «سحب العنوان من صحيفة الدعوى» ⟵ الشريط السفلي."""
        self._set_state(payload.get('message') or '', color=payload.get('color'))

    # ------------------------------------------------------------------
    # الإرسال
    # ------------------------------------------------------------------
    def _send_selected(self):
        """زر «إرسال الإعلان» في الشريط السفلي ⟵ يستدعي نموذج الطرف المختار."""
        if self.read_only:
            self._set_state('الإرسال متوقف — الجلسة مضى وقتها (نظام الخبراء ما يقبلها).',
                            color=th.AMBER_TEXT)
            return
        if self._party_form is None:
            self._set_state('اختر طرفاً أولاً (اضغط «إعلان» بجوار الاسم).',
                            color=th.AMBER_TEXT)
            return
        self._party_form._on_send()

    def _on_submit(self, values):
        form = self._party_form.form if self._party_form else {}
        payload = ilann.build_payload(form, values)
        cookies = self.cookies
        # ⚠️ التاريخ والوقت مطلوبين: السيرفر يقرأهما من **جلسته** (ECS_MET_DATE /
        #    ECS_MET_TIME) ويرد «4» (جلسة سابقة) بدونهما — انظر ilann.set_meeting_context.
        caso, auto = self.caso_no, self.auto_no
        sdate, stime = self.session_date, self.session_time

        def work():
            res = ilann.send_inform(cookies, payload, dry_run=False, caso_no=caso,
                                    auto_no=auto, session_date=sdate, session_time=stime)
            self._emit(self._sent, res)

        threading.Thread(target=work, daemon=True).start()

    def _on_sent(self, res):
        if res.get('ok'):
            # الإعلان تم ⟵ نسكّر النموذج: ما يبقى زر إرسال فعّال (ضمان ما يتكرر الإعلان)
            self._clear_form()
            self._selected = None
            self._refresh_party_rows()
            self._set_state('تم إرسال الإعلان بنجاح.', color=th.EMERALD_TEXT)
            self.refresh(keep_outcome=True)
            return
        code = str(res.get('code', ''))
        if code == 'err':
            # ما نعرف إذا وصل الطلب للنظام ⟵ ما نقول «فشل» (قد يكون وصل والنهار ذهب)
            self._set_state(SEND_MESSAGES['err'], color=th.AMBER_TEXT)
            self.refresh(keep_outcome=True)
            return
        msg = SEND_MESSAGES.get(code) or 'تعذّر إرسال الإعلان — لم يتم الإرسال.'
        if code in ('too_long', 'ora') and res.get('message'):
            msg = res['message']  # رسالة السيرفر تحدّد الحقل والطول والحدّ
        self._set_state(msg, color=th.DANGER_TEXT)

    # ------------------------------------------------------------------
    # تحديث + حالة
    # ------------------------------------------------------------------
    def refresh(self, keep_outcome=False):
        """يُعيد جلب صفحة الطلب (يُستدعى بعد إرسال ناجح)."""
        cookies = self.cookies
        caso, auto = self.caso_no, self.auto_no
        # ما نطمس نتيجة مهمة (مثل «تم إرسال الإعلان») برسالة لحظية
        if not (keep_outcome and self._state_kind == 'outcome'):
            self._set_state('جاري التحديث…', color=th.TEXT_SECONDARY, kind='busy')

        def work():
            try:
                data = ilann.fetch_page(cookies, caso, auto,
                                        session_date=self.session_date,
                                        session_time=self.session_time,
                                        case_fallback=self.read_only)
            except Exception:
                self._emit(self._failed, 'تعذّر الاتصال بنظام الخبراء')
                return
            self._emit(self._loaded, data)

        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, data):
        self._apply_data(data)
        if data.get('ok') and self._state_kind == 'busy':
            self._set_state('')

    def _on_failed(self, msg):
        self._set_state(str(msg), color=th.DANGER_TEXT)
        self._set_connection(False)

    def _set_state(self, text, color=None, kind='outcome'):
        self._state_kind = kind if text else ''
        self.lbl_state.setText(text or '')
        self.lbl_state.setStyleSheet(
            "color:%s; font-size:%spx; font-weight:%s; background:transparent; border:none;"
            % (color or th.TEXT_SECONDARY, th.FS_LABEL, th.W_REGULAR))
        if text:
            # النتيجة أهم جزء قانونياً ⟵ نوصّلها للتركيز (قارئ الشاشة + لوحة المفاتيح)
            self.lbl_state.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------------------------------------------
    # طباعة إشعار الإعلان
    # ------------------------------------------------------------------
    def _on_print(self):
        parties = self.data.get('parties') or []
        if not parties:
            self._set_state('جلب بيانات القضية أول (عندها أطراف وإعلان).',
                            color=th.AMBER_TEXT)
            return
        default = 'إشعار_إعلان_%s.docx' % (self.caso_no or 'قضية')
        path, _ = QFileDialog.getSaveFileName(self, 'حفظ إشعار الإعلان', default,
                                              'Word (*.docx)')
        if not path:
            return
        case = self.data.get('case') or {}
        party = parties[0]
        try:
            ilann.notice_docx(
                path, self.caso_no,
                party={'name': party.get('name', ''), 'type': party.get('type', '')},
                results=self.data.get('results') or [],
                case_info={'auto_no': ilann.case_field(case, 'auto_no', self.auto_no),
                           'case_no': ilann.case_field(case, 'case_no'),
                           'type': ilann.case_field(case, 'type'),
                           'in_date': ilann.case_field(case, 'in_date')},
                expert_name=self.current_user)
        except Exception:
            self._set_state('تعذّر إنشاء الملف.', color=th.DANGER_TEXT)
            return
        self._set_state('تم حفظ الملف: %s' % path, color=th.EMERALD_TEXT)
