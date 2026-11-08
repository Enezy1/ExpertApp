# ===== qt_documents_panel.py — «إضافة مستندات القضية» داخل صفحة القضية (تصميم Stitch، 2026-10-18) =====
# لا نافذة جديدة: اللوحة تُعرض في خطوة «المستندات والعقود» نفسها وتتسع لحجم الشاشة (القائمة واللوحة الجانبية
# تتمرّران داخلياً فلا ينزل شيء تحت حافة الشاشة).
# المنطق كله من DocumentsDialog (نسخ ← تصنيف ← تحويل في Job خلفي، الإشارات، الأسئلة) — هنا الشكل فقط:
#   1 بيانات الحافظة (مقدّم بأزرار + تاريخ؛ يُقترحان ثم يُضبطان من الصفحة الأولى بمزوّد رخيص)
#   2 اختر المستندات (منطقة إفلات)   3 المستندات المختارة (صف لكل ملف: رقم، اسم، حجم، نوع، حالة بنسبة)
#   جانبياً «ما يفعله البرنامج الآن» (خط زمني: تم / جارٍ بشريط نسبة / بانتظار) + الشريط السفلي (المجموع/الجاهز).
import os
from datetime import datetime

from PyQt6.QtCore import Qt, QDate, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDateEdit, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import case_documents
import doc_router
import qt_documents_dialog as qd

F = "'IBM Plex Sans Arabic','Tajawal','Segoe UI'"
NAVY = '#0f1c2c'
INK = '#1e293b'
MUTED = '#64748b'
LINE = '#e2e8f0'
SOFT = '#f1f5f9'
BLUE = '#1e88c8'
BLUE_SOFT = '#e8f3fb'
BLUE_LINE = '#cfe3f4'
BLUE_INK = '#1d4f91'
GREEN = '#15803d'
GREEN_SOFT = '#ecfaf2'
GREEN_LINE = '#a7e3c3'
RED = '#b3261e'
RED_SOFT = '#fdecea'
AMBER = '#b45309'
AMBER_SOFT = '#fff7e6'
AMBER_LINE = '#f7d58f'
INK2 = '#334155'
SCROLL_QSS = ("QScrollArea{background:transparent; border:none;}"     # شريط تمرير نحيف بلا أسهم
              "QScrollBar:vertical{background:transparent; width:8px; margin:2px 0;}"
              "QScrollBar::handle:vertical{background:#cbd5e1; border-radius:4px; min-height:30px;}"
              "QScrollBar::handle:vertical:hover{background:#94a3b8;}"
              "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0; border:none; background:none;}"
              "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}")
SIDES = (('المدعية', '#f59e0b'), ('المدعى عليه', '#16a34a'), ('أخرى', None))   # الحافظة من الخصوم فقط — لا «الخبير»
FILTERS = ('الكل', 'المدعية', 'المدعى عليه', 'أخرى')
CORE_TYPES = (doc_router.T_JUDGMENT, doc_router.T_PLAINT, doc_router.T_MINUTES)     # حكم الإحالة، الصحيفة، المحاضر
_CORE_ORDER = {doc_router.T_JUDGMENT: 0, doc_router.T_PLAINT: 1, doc_router.T_MINUTES: 2}


def side_of(p, d):
    """فرز المستند: المدعية / المدعى عليه / أخرى (المحاضر وحكم الإحالة والصحيفة وكل ما ليس حافظة أو مذكرة)."""
    if d.get('doc_type') not in (doc_router.T_PORTFOLIO, doc_router.T_DEFENSE):
        return 'أخرى'
    who = case_documents.clean_submitter(p.get('submitter'))
    if any(k in who for k in ('عليه', 'عليها', 'عليهم', 'ضده', 'ضدها')):
        return 'المدعى عليه'
    if any(k in who for k in ('المدعي', 'مدعية', 'المدعون', 'المستأنف')):
        return 'المدعية'
    return 'أخرى'


def order_key(p, d):
    """الترتيب: حكم الإحالة ثم الصحيفة ثم المحاضر؛ ثم المدعية (حوافظ ثم مذكرات) ثم المدعى عليه (كذلك)؛ ثم البقية."""
    t = d.get('doc_type')
    if t in _CORE_ORDER:
        return (0, _CORE_ORDER[t], 0, p.get('date') or '', d.get('no') or 0)
    side = side_of(p, d)
    rank = {'المدعية': 1, 'المدعى عليه': 2}.get(side, 3)
    return (rank, 0 if t == doc_router.T_PORTFOLIO else 1, 0, p.get('date') or '', d.get('no') or 0)


def title_of(p, d):
    """عنوان المستند بمعناه (لا باسم الملف): «حافظة مستندات المدعية»، «مذكرة دفاع المدعى عليه»، «حكم»…"""
    t = d.get('doc_type') or d.get('kind') or 'مستند'
    who = case_documents.clean_submitter(p.get('submitter'))
    if t in (doc_router.T_PORTFOLIO, doc_router.T_DEFENSE) and who and 'لم يتضح' not in who:
        return f"{t} {who}" + (f" بتاريخ {p['date']}" if p.get('date') else '')
    return t


def _lbl(text, size=13, color=INK, bold=False, wrap=True):
    l = QLabel(text)
    l.setWordWrap(wrap)
    l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter)   # يمين فعلي في RTL
    l.setStyleSheet(f"font-family:{F}; font-size:{size}px; color:{color}; border:none; background:transparent;"
                    + ("font-weight:700;" if bold else ''))
    return l


def _pill(text, fg, bg, border=None, icon=None, dot=None):
    """شارة مستديرة الزوايا؛ icon أيقونة مرسومة قبل النص، dot نقطة ملوّنة (مثل مقدّم الحافظة)."""
    if not icon and not dot:
        l = QLabel(text)
        l.setStyleSheet(f"font-family:{F}; font-size:12px; font-weight:600; color:{fg}; background:{bg};"
                        f"border:1px solid {border or bg}; border-radius:7px; padding:3px 10px;")
        return l
    import qt_icons
    w = QFrame()
    w.setObjectName('pill')
    w.setStyleSheet(f"QFrame#pill{{background:{bg}; border:1px solid {border or bg}; border-radius:7px;}}")
    h = QHBoxLayout(w)
    h.setContentsMargins(9, 3, 10, 3)
    h.setSpacing(6)
    if icon:
        ic = QLabel()
        ic.setPixmap(qt_icons.pixmap(icon, fg, 13))
        ic.setStyleSheet("background:transparent; border:none;")
        h.addWidget(ic)
    if dot:
        d = QLabel()
        d.setFixedSize(7, 7)
        d.setStyleSheet(f"background:{dot}; border-radius:3px; border:none;")
        h.addWidget(d)
    t = QLabel(text)
    t.setStyleSheet(f"font-family:{F}; font-size:12px; font-weight:700; color:{fg}; background:transparent; border:none;")
    h.addWidget(t)
    w.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    w.text = t.text                                   # توافق: الشارة تُقرأ كنص في الاختبارات
    return w


def _btn(text, primary=False, icon=None):
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon:
        import qt_icons
        b.setIcon(qt_icons.icon(icon, NAVY, size=16))
    if primary:
        b.setStyleSheet(f"QPushButton{{background:{NAVY}; color:white; border:none; border-radius:10px; padding:9px 18px;"
                        f"font-family:{F}; font-size:13px; font-weight:700;}} QPushButton:disabled{{background:#9aa5b1;}}")
    else:
        b.setStyleSheet(f"QPushButton{{background:white; color:{NAVY}; border:1px solid #cbd5e1; border-radius:10px;"
                        f"padding:8px 18px; font-family:{F}; font-size:13px; font-weight:600;}}"
                        f"QPushButton:hover{{background:{SOFT}; border-color:#94a3b8;}}"
                        "QPushButton:disabled{color:#9aa5b1;}")
    return b


def _num(n, size=28):
    l = QLabel(str(n))
    l.setFixedSize(size, size)
    l.setAlignment(Qt.AlignmentFlag.AlignCenter)
    l.setStyleSheet(f"background:{NAVY}; color:white; border-radius:7px; font-family:{F}; font-size:13px; font-weight:700;")
    return l


COL_NO, COL_CAT, COL_STATE, COL_ACT, COL_GAP = 28, 118, 150, 62, 12     # أعمدة جدول المستندات (px): الإجراء = إعادة فرز + إعادة قراءة


def _cell(widget, width, below=None):
    """خلية ثابتة العرض: العنصر (وتحته عنصر اختياري) ملاصق لبداية الخلية، فتصطف الأعمدة بين الصفوف."""
    c = QWidget()
    c.setObjectName('cell')
    c.setStyleSheet("QWidget#cell{background:transparent;}")
    c.setFixedWidth(width)
    c.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)   # لا تتمدد الخلية رأسياً
    v = QVBoxLayout(c)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(3)
    for x in (widget, below):
        if x is not None:
            x.setMaximumWidth(width)
            v.addWidget(x, 0, Qt.AlignmentFlag.AlignLeading)
    return c


def _link(text):
    """زر نصي صغير (رابط) لإجراء ثانوي داخل خلية."""
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"QPushButton{{background:transparent; border:none; color:{BLUE}; font-family:{F};"
                    "font-size:11px; font-weight:600; padding:0; text-align:right;}"
                    f"QPushButton:hover{{color:{NAVY}; text-decoration:underline;}}")
    return b


def _section_head(n, title, sub):
    """رأس قسم: رقم في مربع كحلي ثم العنوان وتحته سطر خافت. يرجع (التخطيط، العنوان، السطر)."""
    h = QHBoxLayout()
    h.setSpacing(10)
    h.addWidget(_num(n, 22), 0, Qt.AlignmentFlag.AlignTop)
    v = QVBoxLayout()
    v.setSpacing(2)
    t = _lbl(title, 14, NAVY, True)                 # يلتف في النافذة الضيقة بدل أن يدفع العمود خارجها
    s = _lbl(sub, 11, MUTED)
    s.setVisible(bool(sub))                          # بلا سطر فرعي: العنوان وحده
    v.addWidget(t)
    v.addWidget(s)
    h.addLayout(v, 1)
    return h, t, s


def human_size(n):
    if n is None:
        return ''
    if n >= 1 << 20:
        return f'{n / (1 << 20):.1f} م.ب'
    return f'{max(1, n // 1024)} ك.ب'


def state_view(conv, is_original=False, weak=''):
    """(نص الحالة، لون، خلفية، نسبة أو None) لحالة تحويل مستند. دالة صرفة للاختبار."""
    st = conv.get('state')
    if st == 'done':
        if weak:
            return ('تم — قراءة ضعيفة', AMBER, AMBER_SOFT, None)
        return ('لا يحتاج تحويل' if is_original else 'تم التحويل ✓', GREEN, GREEN_SOFT, None)
    if st == 'running':
        p = int(conv.get('progress') or 0)
        return (f'جارٍ التحويل {p}%' if p else 'جارٍ التحويل…', BLUE, BLUE_SOFT, p)
    if st == 'failed':
        return ('فشل', RED, RED_SOFT, None)
    return ('بانتظار التحويل', MUTED, SOFT, None)


class DocumentsPanel(qd.DocumentsDialog):
    """لوحة مضمَّنة (QDialog بعلامة Widget) تعيد استعمال كل منطق DocumentsDialog."""

    PER_FILE_PORTFOLIO = True
    retry = pyqtSignal(str)          # ملف «تعذّر التحويل» (مسار نسبي) — يعالجه صاحب الصفحة
    answer = pyqtSignal(str)         # ملف ينتظر قرار الفرز
    reread = pyqtSignal(str, str)    # «إعادة القراءة» لملف (مسار نسبي، محرّك أو ''): التحويل والفرز من جديد — يعالجه صاحب الصفحة
    retriage = pyqtSignal(object)    # «إعادة فرز» من markdown بلا OCR: [مسار نسبي] لملف واحد، أو None = «إعادة فرز الكل»

    def __init__(self, base, data, parent=None, convert=None, on_changed=None, caso_no=''):
        qd.QDialog.__init__(self, parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setAcceptDrops(True)
        self.setStyleSheet("QDialog{background:transparent;}")
        self._batch, self._staged, self._rows = set(), [], {}
        self._times = {}                     # uid -> وقت الانتهاء (للخط الزمني)
        self._on_changed = on_changed
        self.base, self.data, self._convert = base, qd.live_data(base) or data, convert
        doc_router.ensure_defaults()
        if qd.active_job(base) is None and case_documents.recover_running(self.data):
            case_documents._save(base, self.data)
        br = qd.bridge()
        qd._OPEN.add(base)
        slots = [(br.log, self._on_log), (br.update, self._on_update), (br.finished, self._on_finished)]
        for sig, slot in slots:
            sig.connect(slot)
        self.destroyed.connect(lambda *_a, s=slots, b=base: _teardown(s, b))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)

        # ===== العمود الرئيسي (يمين في RTL) =====
        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(8)
        # مقدّم الحافظة وتاريخها يُستخرجان آلياً من صفحتها الأولى؛ عناصرها مخفية ويستعملها المنطق فقط
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._on_portfolio_changed)
        self.date = QDateEdit(QDate.currentDate())
        self.submitter = QLineEdit()
        for w in (self.combo, self.date, self.submitter):
            w.setVisible(False)
        self._filter = 'الكل'
        # المقدّم يُعرف آلياً من صفحة كل مستند (لا اختيار يدوي قبل الإضافة)؛ الفرز بالمقدّم تحت القائمة
        self._side_btns = {}
        # 1) اختر المستندات — منطقة إفلات بسطر واحد: أيقونة ونص يميناً، وزرّا الاختيار يساراً
        h, _t, _s = _section_head(1, "اختر المستندات", "")
        ml.addLayout(h)
        self.drop = QFrame()
        self.drop.setObjectName('drop')
        self.drop.setStyleSheet(f"QFrame#drop{{border:1px dashed #8fcbea; border-radius:10px; background:white;}}")
        dl = QHBoxLayout(self.drop)
        dl.setContentsMargins(18, 16, 18, 16)
        dl.setSpacing(14)
        import qt_icons
        icon = QLabel()
        icon.setFixedSize(46, 46)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(qt_icons.pixmap('upload', BLUE, 22))
        icon.setStyleSheet(f"background:{BLUE_SOFT}; border-radius:23px; border:none;")
        dl.addWidget(icon)
        tv = QVBoxLayout()
        tv.setSpacing(3)
        tv.addWidget(_lbl("اسحب وأفلت الملفات هنا، أو اضغط للاختيار من جهازك", 14, INK, True))
        tv.addWidget(_lbl("يدعم ملفات PDF، مستندات Word، وصور الحوافظ والمستندات الرسمية", 11, MUTED))
        dl.addLayout(tv, 1)
        self.files_btn = _btn("  اختيار ملفات", icon='file')
        self.files_btn.clicked.connect(self._pick_files)
        self.folder_btn = _btn("  اختيار مجلد كامل", icon='folder')
        self.folder_btn.clicked.connect(self._pick_folder)
        for b_ in (self.files_btn, self.folder_btn):
            b_.setStyleSheet(b_.styleSheet().replace("padding:8px 18px", "padding:8px 16px"))
            dl.addWidget(b_)
        self.add_btn = _btn("إضافة وتصنيف")          # المرحلتان اليدويتان (AUTO_RUN=False) فقط
        self.add_btn.clicked.connect(self._start)
        self.import_btn = _btn("استيراد وتحويل", True)
        self.import_btn.clicked.connect(self._convert_pending)
        for b_ in (self.add_btn, self.import_btn):
            b_.setVisible(not self.AUTO_RUN)
            dl.addWidget(b_)
        ml.addWidget(self.drop)
        ml.addSpacing(4)

        # 2) المستندات المدرجة + الفرز بالمقدّم في السطر نفسه (يساراً)
        h, self.list_title, self.list_sub = _section_head(2, "المستندات المدرجة في القضية", "")
        seg = QFrame()                              # فرز بالمقدّم (أزرار متجاورة؛ المختار كحلي)
        seg.setObjectName('seg')
        seg.setStyleSheet(f"QFrame#seg{{background:white; border:1px solid {LINE}; border-radius:10px;}}")
        fb = QHBoxLayout(seg)
        fb.setContentsMargins(4, 4, 4, 4)
        fb.setSpacing(2)
        self._filter_btns = {}
        dots = dict(SIDES)
        for name in FILTERS:
            b_ = QPushButton()
            b_.setCursor(Qt.CursorShape.PointingHandCursor)
            b_.setFixedHeight(30)
            bl = QHBoxLayout(b_)
            bl.setContentsMargins(12, 0, 12, 0)
            bl.setSpacing(6)
            d_ = QLabel()
            d_.setFixedSize(7, 7)
            d_.setVisible(bool(dots.get(name)))
            d_.setStyleSheet(f"background:{dots.get(name) or NAVY}; border-radius:3px; border:none;")
            t_ = QLabel(name)
            t_.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            d_.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            bl.addWidget(t_)
            bl.addWidget(d_)
            b_.setProperty('txt', t_)
            b_.setProperty('dot', dots.get(name) or NAVY)
            b_.clicked.connect(lambda _c=False, n=name: self._set_filter(n))
            fb.addWidget(b_)
            self._filter_btns[name] = b_
        h.addWidget(seg, 0, Qt.AlignmentFlag.AlignVCenter)
        ml.addLayout(h)
        self.port_tag = QLabel()
        self.port_tag.setVisible(False)
        self.list_box = QWidget()                   # حاوية شفافة: الجدول الأبيض بطول صفوفه، والفراغ تحته
        self.list_box.setObjectName('lstwrap')
        self.list_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.list_box.setStyleSheet("QWidget#lstwrap{background:transparent;}")
        wrap = QVBoxLayout(self.list_box)
        wrap.setContentsMargins(0, 0, 0, 0)
        table = QFrame()
        table.setObjectName('lst')
        table.setStyleSheet(f"QFrame#lst{{background:white; border:1px solid {LINE}; border-radius:10px;}}")
        self.list_lay = QVBoxLayout(table)
        self.list_lay.setContentsMargins(1, 1, 1, 1)
        self.list_lay.setSpacing(0)
        wrap.addWidget(table)
        wrap.addStretch(1)
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_scroll.setStyleSheet(SCROLL_QSS)
        self.list_scroll.setWidget(self.list_box)
        self.list_scroll.viewport().setAutoFillBackground(False)
        self.list_scroll.viewport().setStyleSheet("background:transparent;")
        self.list_scroll.setMinimumHeight(150)
        ml.addWidget(self.list_scroll, 1)

        # ===== اللوحة الجانبية «ما يفعله البرنامج الآن» (أول عنصر = يمين في RTL) =====
        side = QFrame()
        side.setObjectName('side')
        side.setStyleSheet(f"QFrame#side{{background:white; border:1px solid {LINE}; border-radius:14px;}}")
        side.setMinimumWidth(250)
        side.setMaximumWidth(330)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 12, 14, 10)
        sv.setSpacing(10)
        hd = QHBoxLayout()
        hd.setSpacing(8)
        self.live_dot = QFrame()                     # نقطة زرقاء حين يعمل البرنامج
        self.live_dot.setFixedSize(9, 9)
        self.live_dot.setStyleSheet(f"background:{MUTED}; border-radius:4px; border:none;")
        hd.addWidget(self.live_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        hd.addWidget(_lbl("ما يفعله البرنامج الآن", 13, NAVY, True, wrap=False))
        hd.addStretch(1)
        self.live_tag = _pill("مزامنة حية", MUTED, SOFT, LINE)
        self.live_tag.setVisible(False)
        hd.addWidget(self.live_tag)
        sv.addLayout(hd)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{LINE}; border:none;")
        sv.addWidget(sep)
        inner = QWidget()                            # الخطوات + أسئلة الفرز + تقدّم الدفعة، تتمرّر معاً
        inner.setObjectName('sideinner')
        inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        inner.setStyleSheet("QWidget#sideinner{background:transparent;}")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 4, 0)
        il.setSpacing(8)
        self.steps_box = QVBoxLayout()               # خطوات خط البداية التسع (case_startup) بحالة كل خطوة
        self.steps_box.setSpacing(4)
        il.addLayout(self.steps_box)
        self._spinners = []
        self.q_box = QVBoxLayout()                   # ملفات تنتظر قرارك (فرز لم يُحسم) بزر «تحديد»
        il.addLayout(self.q_box)
        self.total_lbl = _lbl("", 12, NAVY, True)
        il.addWidget(self.total_lbl)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(f"QProgressBar{{background:{LINE}; border:none; border-radius:3px;}}"
                               f"QProgressBar::chunk{{background:{BLUE}; border-radius:3px;}}")
        self.bar.setVisible(False)
        il.addWidget(self.bar)
        self.timeline = QWidget()
        self.tl_lay = QVBoxLayout(self.timeline)
        self.tl_lay.setContentsMargins(0, 0, 0, 0)
        self.tl_lay.setSpacing(6)
        il.addWidget(self.timeline)
        il.addStretch(1)
        tl_scroll = QScrollArea()
        tl_scroll.setWidgetResizable(True)
        tl_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tl_scroll.setStyleSheet(SCROLL_QSS)
        tl_scroll.viewport().setStyleSheet("background:transparent;")
        tl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tl_scroll.setWidget(inner)
        sv.addWidget(tl_scroll, 1)
        self.files_lbl = QLabel()                    # توافق مع منطق DocumentsDialog (غير ظاهر)
        self.files_lbl.setVisible(False)
        self.log = QPlainTextEdit()                  # سجل مفصّل مطويّ (الأخطاء بنص مفهوم)
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(70)
        self.log.setStyleSheet(f"QPlainTextEdit{{border:none; background:transparent; color:{MUTED};"
                               f"font-family:{F}; font-size:11px;}}")
        self.log.setVisible(False)                   # الأخطاء تظهر في كل بند؛ السجل الكامل في tooltip «ما يفعله…»
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background:{LINE}; border:none;")
        sv.addWidget(sep2)
        nl = QHBoxLayout()
        nl.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(qt_icons.pixmap('info', MUTED, 15))
        ic.setStyleSheet("background:transparent; border:none;")
        nl.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        note = _lbl("يتم تحديث المؤشرات تلقائياً فور إدراج مستندات جديدة.", 11, MUTED)
        note.setToolTip("يمكنك الانتقال إلى خطوة أخرى أو إغلاق النافذة؛ يستمر التحويل في الخلفية وتُحفظ النتائج تلقائياً.")
        nl.addWidget(note, 1)
        sv.addLayout(nl)
        body.addWidget(main, 3)                     # RTL: الرئيسي يميناً، و«ما يفعله البرنامج» يساراً
        body.addWidget(side, 1)

        # ===== الشريط السفلي =====
        foot = QHBoxLayout()
        self.status = _lbl("", 11, MUTED)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.sum_lbl = _lbl("", 12, MUTED, wrap=False)
        foot.addWidget(self.sum_lbl)
        foot.addWidget(self.status, 1)
        root.addLayout(foot)

        self.table = None                           # لا جدول هنا: _render/_set_state_cell مُعادة التعريف
        self._fill_combo()
        self._render()
        self._sync_buttons()
        self._prog_timer = QTimer(self)
        self._prog_timer.setInterval(400)
        self._prog_timer.timeout.connect(self._refresh_progress)
        self._prog_timer.start()
        if qd.active_job(base) is not None:
            self._batch |= {d['uid'] for _, d in case_documents.all_docs(self.data)
                            if d['convert']['state'] in ('pending', 'running')}
        self._refresh_progress()

    # ---------- مقدّم الحافظة ----------
    def _pick_side(self, name):
        """اختيار مقدّم الحافظة للدفعة القادمة؛ الضغط على المختار يعيده «تلقائي»."""
        if self._side == name:
            self._side = None
            self.submitter.clear()
            self.submitter.setVisible(False)
        elif name == 'أخرى':
            self._side = name
            self.submitter.clear()
            self.submitter.setVisible(True)
            self.submitter.setFocus()
        else:
            self._side = name
            self.submitter.setText(name)
            self.submitter.setVisible(False)
        self._sync_side()

    _side = None

    def _sync_side(self):
        for name, b in getattr(self, '_side_btns', {}).items():
            on = name == self._side
            b.setChecked(on)
            dot = b.property('dot')
            b.setStyleSheet(
                "QPushButton{border-radius:7px;"
                + (f"background:white; border:1px solid {dot if dot != MUTED else LINE};}}" if on
                   else "background:transparent; border:1px solid transparent;} QPushButton:hover{background:white;}"))
            b.property('txt').setStyleSheet(f"font-family:{F}; font-size:13px; background:transparent; border:none;"
                                            f"color:{(dot if dot != MUTED else NAVY) if on else INK};"
                                            + ("font-weight:700;" if on else ''))

    def _fill_combo(self):
        super()._fill_combo()
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(self.combo.findData(qd.NEW))     # كل إضافة تبدأ حافظة جديدة تُعرف من صفحتها
        self.combo.blockSignals(False)

    def _on_portfolio_changed(self):
        typed = self.submitter.text()
        super()._on_portfolio_changed()
        if self._side:                                # الأب يمسح الحقل عند «حافظة جديدة» ← نُبقي اختيار الخبير
            self.submitter.setText(typed if self._side == 'أخرى' else self._side)
        self._sync_side()
        if getattr(self, 'list_box', None) is not None:
            self._render()

    # ---------- العرض ----------
    def _sync_buttons(self):
        busy = self._busy()
        self.add_btn.setEnabled(bool(self._staged) and not busy)
        self.import_btn.setEnabled(bool(case_documents.pending_docs(self.data)) and not busy)
        self.files_btn.setEnabled(not busy)
        self.folder_btn.setEnabled(not busy)
        for w in self.list_box.findChildren(QPushButton):
            w.setEnabled(not busy)

    def _set_state_cell(self, row, conv, override=None):     # منطق الأب يستدعيها؛ هنا يكفي إعادة الرسم
        self._render_soon()

    def _on_update(self, base, uid, conv):
        if base != self.base:
            return
        if uid == '*':
            self._batch |= {d['uid'] for _, d in case_documents.all_docs(self.data)
                            if d['convert']['state'] in ('pending', 'running')}
        else:
            self._batch.add(uid)
            if (conv or {}).get('state') in ('done', 'failed'):
                self._times[uid] = datetime.now().strftime('%H:%M')
        self._render_soon()

    def _render_soon(self):
        if not getattr(self, '_pending_render', False):
            self._pending_render = True
            QTimer.singleShot(150, self._render_now)

    def _render_now(self):
        self._pending_render = False
        self._render()

    def _clear(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
            elif it.layout():
                self._clear(it.layout())

    def _row(self, i, p, d, last):
        """صف جدول: # | المستند (العنوان وتحته الملف والحجم) | النوع | الحالة | إعادة — أعمدة ثابتة العرض فتصطف الصفوف."""
        w = QFrame()
        w.setObjectName('row')
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)   # الصف بارتفاع محتواه؛ الفراغ أسفل الجدول
        w.setStyleSheet(f"QFrame#row{{border:none; border-bottom:{0 if last else 1}px solid {LINE}; background:white;}}"
                        f"QFrame#row:hover{{background:#f8fafc;}}")
        r = QHBoxLayout(w)
        r.setContentsMargins(12, 7, 12, 7)
        r.setSpacing(COL_GAP)
        n = QLabel(str(d.get('no') or i))
        n.setFixedSize(COL_NO, 24)
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        n.setStyleSheet(f"background:#eef2f7; border:none; border-radius:6px; color:#475569; font-family:{F};"
                        "font-size:11px; font-weight:700;")
        r.addWidget(n)
        nv = QVBoxLayout()
        nv.setSpacing(1)
        name = _lbl(title_of(p, d), 13, INK, True, wrap=False)
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        name.setToolTip(d['orig_name'])
        nv.addWidget(name)
        size = None
        try:
            size = os.path.getsize(os.path.join(self.base, d.get('file') or ''))
        except OSError:
            pass
        meta = '  ·  '.join(x for x in (d['orig_name'], human_size(size)) if x)
        fn = _lbl(meta, 11, '#94a3b8', wrap=False)
        fn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        nv.addWidget(fn)
        r.addLayout(nv, 1)
        # النوع: تصنيف واحد فقط — المدعية / المدعى عليه للحوافظ والمذكرات، وغيرها «أخرى» (نوعه في عنوانه)
        if d.get('needs_type') and d['convert']['state'] == 'pending':
            cat = QComboBox()
            cat.addItem(qd.PLACEHOLDER, None)
            for t in doc_router.KNOWN_TYPES:
                cat.addItem(t, t)
            cat.setStyleSheet(f"QComboBox{{background:{AMBER_SOFT}; color:{AMBER};}}"      # والقائمة المنبثقة بيضاء (لا سوداء)
                              "QComboBox QAbstractItemView{background:white; color:#0f1c2c;"
                              "selection-background-color:#e8f3fb; selection-color:#0f1c2c;}")
            cat.currentIndexChanged.connect(lambda _i, u=d['uid'], c=cat: self._on_type_chosen(u, c))
        elif d.get('doc_type') in (doc_router.T_PORTFOLIO, doc_router.T_DEFENSE):
            cat = self._side_chip(p)
        else:
            cat = _pill('أخرى', INK2, SOFT, LINE)
            kind = d.get('kind') or d.get('doc_type') or ''
            cat.setToolTip(f"{kind} — {d.get('type_reason', '')} — المحرّك: "
                           f"{doc_router.ENGINE_LABELS.get(d.get('engine'), '')}")
        r.addWidget(_cell(cat, COL_CAT))
        # الحالة: الشارة، وتحتها شريط التقدّم أو رابط الإجراء (إعادة المحاولة / محرك أقوى)
        st = d['convert'].get('state')
        text, fg, bg, pct = state_view(d['convert'], d.get('origin') == 'original', d.get('quality_warning') or '')
        ok = st == 'done' and fg == GREEN
        pill = _pill(text.replace(' ✓', ''), fg, bg, GREEN_LINE if ok else None, icon='check' if ok else None)
        if st == 'failed':
            pill.setToolTip(qd.friendly_error(d['convert'].get('message')))
        extra = None
        if st == 'running':                                   # شريط تقدّم حيّ (نسبة الصفحات، أو متحرك بلا نسبة)
            extra = QProgressBar()
            extra.setFixedSize(90, 5)
            extra.setTextVisible(False)
            extra.setRange(0, 100 if pct else 0)
            if pct:
                extra.setValue(pct)
            extra.setStyleSheet(f"QProgressBar{{background:{SOFT}; border:none; border-radius:2px;}}"
                                f"QProgressBar::chunk{{background:{BLUE}; border-radius:2px;}}")
        elif st == 'failed':
            extra = _link("إعادة المحاولة")
            extra.clicked.connect(lambda _=False, u=d['uid']: self._retry(u))
        elif d.get('quality_warning') and st == 'done':
            extra = _link("أعد القراءة بمحرك أقوى")
            extra.clicked.connect(lambda _=False, u=d['uid']: self._reread(u))
        r.addWidget(_cell(pill, COL_STATE, extra))
        redo = None
        if st in ('done', 'failed') and d.get('file') and d.get('engine') != doc_router.ENGINE_TEXT:
            redo = self._redo_btn(d)                          # «فشل» أيضاً: إعادة بمحرّك آخر تختاره
        r.addWidget(_cell(redo, COL_ACT))
        return w

    def _table_head(self):
        """رأس الجدول بعناوين الأعمدة (بنفس عروض الصفوف)."""
        w = QFrame()
        w.setObjectName('thead')
        w.setStyleSheet(f"QFrame#thead{{background:{SOFT}; border:none; border-bottom:1px solid {LINE};"
                        "border-top-left-radius:10px; border-top-right-radius:10px;}")
        r = QHBoxLayout(w)
        r.setContentsMargins(12, 5, 12, 5)
        r.setSpacing(COL_GAP)
        for text, width in (('#', COL_NO), ('المستند', None), ('المقدّم', COL_CAT), ('الحالة', COL_STATE)):
            l = _lbl(text, 11, MUTED, True, wrap=False)
            if width is None:
                r.addWidget(l, 1)
            else:
                if text == '#':
                    l.setAlignment(Qt.AlignmentFlag.AlignCenter)
                l.setFixedWidth(width)
                r.addWidget(l)
        r.addWidget(_cell(self._icon_btn('sort', "إعادة فرز الكل من markdown (بلا OCR) — يُطلب تأكيدك أولاً",
                                         lambda: self.retriage.emit(None), small=True), COL_ACT))
        return w

    def _icon_btn(self, kind, tip, fn, small=False):
        """زر أيقونة خفيف بنمط السهم الدائري نفسه."""
        import qt_icons
        b = QPushButton()
        b.setIcon(qt_icons.icon(kind, '#475569', active=NAVY, size=14 if small else 16))
        b.setFixedSize(24 if small else 28, 24 if small else 28)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(tip)
        b.setStyleSheet(f"QPushButton{{background:white; border:1px solid {LINE}; border-radius:8px;}}"
                        f"QPushButton:hover{{background:{SOFT}; border-color:#cbd5e1;}}")
        b.clicked.connect(lambda _=False: fn())
        return b


    def _redo_btn(self, d):
        """🔄 إعادة عمل OCR/markdown بمحرّك آخر يختاره الخبير (إن لم يكن الناتج مضبوطاً).
        القائمة بنمط صريح (qt_context_menu.styled_menu): بدونه يتسرّب «background:transparent» من الصفحة فتظهر صندوقاً
        أسود فارغاً ولا يمكن اختيار شيء (الخلل المبلَّغ 2026-10-20)."""
        import qt_context_menu
        import qt_icons
        b = QPushButton()
        b.setIcon(qt_icons.icon('refresh', '#475569', active=NAVY, size=16))
        b.setFixedSize(28, 28)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip("إعادة التحويل (قراءة المستند من جديد) بمحرّك تختاره")
        b.setStyleSheet(f"QPushButton{{background:white; border:1px solid {LINE}; border-radius:8px;}}"
                        f"QPushButton:hover{{background:{SOFT}; border-color:#cbd5e1;}} QPushButton::menu-indicator{{width:0;}}")
        menu = qt_context_menu.styled_menu(b, "أعد قراءة المستند بمحرّك:")
        cur = d.get('engine_used') or d.get('engine')
        for e in doc_router.ENGINES:
            act = menu.addAction(doc_router.ENGINE_LABELS[e] + ('  (الحالي)' if e == cur else ''))
            act.setData(e)
        menu.triggered.connect(lambda act, u=d['uid']: act.data() and self._redo(u, act.data()))
        b.setMenu(menu)
        return b

    def _side_chip(self, p):
        """مقدّم الحافظة في الصف: يُغيَّر بنقرة (المدعية/المدعى عليه/أخرى)؛ غير المعروف عنبري."""
        from PyQt6.QtWidgets import QInputDialog
        who = case_documents.clean_submitter(p.get('submitter'))
        known = who and 'لم يتضح' not in who
        dot = next((c for n, c in SIDES if c and known and who.startswith(n.split()[0]) and
                    (('عليه' in who) == ('عليه' in n))), MUTED)
        import qt_icons
        b = QPushButton(who if known else "حدّد المقدّم")
        if known:                                       # نقطة مرسومة بلون المقدّم (● لا يظهر في كل الخطوط)
            b.setIcon(qt_icons.icon('dot', dot, size=12))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip("مقدّم الحافظة — اضغط للتغيير")
        green = dot == SIDES[1][1]
        fg, bg, line = ((('#15803d', GREEN_SOFT, GREEN_LINE) if green else (AMBER, AMBER_SOFT, AMBER_LINE)) if known
                        else (AMBER, AMBER_SOFT, AMBER_SOFT))
        if known and dot == MUTED:
            fg, bg, line = INK2, SOFT, LINE
        b.setStyleSheet(f"QPushButton{{font-family:{F}; font-size:12px; font-weight:700; color:{fg}; background:{bg};"
                        f"border:1px solid {line}; border-radius:7px; padding:3px 10px;}}")
        import qt_context_menu
        menu = qt_context_menu.styled_menu(b)            # لا QMenu عارية هنا (تظهر سوداء — انظر _redo_btn)
        for n, _c in SIDES:
            menu.addAction(n)

        def chosen(act):
            n = act.text()
            if n == 'أخرى':
                n, ok = QInputDialog.getText(self, "مقدّم الحافظة", "صفة المقدّم:")
                if not ok or not n.strip():
                    return
            case_documents.update_portfolio(self.base, self.data, p['id'], submitter=n)
            self._render()
            if self._on_changed is not None:
                QTimer.singleShot(0, self._on_changed)
        menu.triggered.connect(chosen)
        b.setMenu(menu)
        b.setStyleSheet(b.styleSheet() + "QPushButton::menu-indicator{width:0;}")
        return b

    def _staged_row(self, path, sp):
        w = QFrame()
        w.setObjectName('row')
        w.setStyleSheet(f"QFrame#row{{border:none; border-bottom:1px solid {LINE}; background:#fbfdff;}}")
        r = QHBoxLayout(w)
        r.setContentsMargins(12, 8, 12, 8)
        r.addWidget(sp)
        r.addWidget(_lbl(os.path.basename(path), 13, INK, True, wrap=False), 1)
        r.addWidget(_pill('جديد', MUTED, SOFT))
        return w

    def _set_filter(self, name):
        self._filter = name
        self._render()

    # ---------- القائمة: الأصول في مجلد القضية (case_folder.doc_rows) — لا markdown ولا _نظام ولا الملخص ----------
    def folder_rows(self):
        import case_folder
        try:
            return case_folder.doc_rows(self.base, self.data)
        except Exception:
            return []

    @staticmethod
    def is_court_doc(r):
        """صحيفة الدعوى وحكم الإحالة والمحاضر: مستندات النظام — عمود «المقدّم» = «أخرى» في العرض والتصفية."""
        import case_folder
        kind = r.get('kind') or ''
        return (kind.startswith(('صحيفة', 'حكم', 'محضر')) and ' و' not in kind
                or case_folder.kind_of(r.get('rel') or '') in (case_folder.PLAINT, case_folder.JUDGMENT,
                                                                case_folder.MINUTES))

    @classmethod
    def row_side(cls, r):
        s = '' if cls.is_court_doc(r) else (r.get('side') or '')
        if any(k in s for k in ('عليه', 'عليها', 'عليهم', 'ضده', 'ضدها')):
            return 'المدعى عليه'
        if s.startswith('المدعي') or 'المستأنف' in s:
            return 'المدعية'
        return 'أخرى'

    def _render(self):
        if getattr(self, 'list_lay', None) is None:
            return
        self._clear(self.list_lay)
        rows = self.folder_rows()
        self._rows_sig = self._live_sig(rows)
        show = [r for r in rows if self._filter == 'الكل' or self.row_side(r) == self._filter]
        for name, b_ in self._filter_btns.items():
            n = len(rows) if name == 'الكل' else sum(1 for r in rows if self.row_side(r) == name)
            on = name == self._filter
            b_.property('txt').setText(f"{name} ({n})")
            b_.setMinimumWidth(b_.property('txt').sizeHint().width() + (37 if dict(SIDES).get(name) else 26))
            b_.setStyleSheet("QPushButton{border-radius:7px; border:none;"
                             + (f"background:{NAVY};}}" if on
                                else f"background:transparent;}} QPushButton:hover{{background:{SOFT};}}"))
            b_.property('txt').setStyleSheet(f"font-family:{F}; font-size:12px; background:transparent; border:none;"
                                             f"color:{'white' if on else INK2};" + ("font-weight:700;" if on else ''))
        if show or self._staged:
            self.list_lay.addWidget(self._table_head())
        for i, r in enumerate(show, 1):
            self.list_lay.addWidget(self._frow(i, r, i == len(show) and not self._staged))
        for path, sp in self._staged:
            self.list_lay.addWidget(self._staged_row(path, sp))
        if not show and not self._staged:
            e = _lbl("لا مستندات بعد — اسحب الملفات إلى المنطقة أعلاه أو اخترها." if not rows
                     else "لا مستندات من هذا المقدّم.", 12, MUTED)
            e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e.setStyleSheet(e.styleSheet() + "padding:18px;")
            self.list_lay.addWidget(e)
        total = len(rows) + len(self._staged)
        self.list_sub.setVisible(True)
        self.list_sub.setText(f"المستندات الأصلية في مجلد القضية: {total}")
        ready = sum(1 for r in rows if r['state'] == 'done')
        self.sum_lbl.setText(f"مجموع المستندات: {len(rows)}  •  مقروءة ومفروزة: {ready}")
        self._sync_buttons()

    @staticmethod
    def _live_sig(rows):
        return tuple((r['rel'], r['state'], (r.get('live') or {}).get('stage'), (r.get('live') or {}).get('pct'))
                     for r in rows)

    def row_texts(self):
        """[(الاسم، النوع، الحالة)] كما تُعرض (للاختبار)."""
        return [(r['name'], r['kind'], self._fstate(r)[0]) for r in self.folder_rows()]

    @staticmethod
    def _fstate(r):
        st = r['state']
        if st == 'running':
            live = r.get('live') or {}
            word = 'جارٍ الفرز' if live.get('stage') == 'sort' else 'جارٍ التحويل'
            return f"{word} {live.get('pct') or 0}%", BLUE, BLUE_SOFT
        if st == 'failed':
            return 'تعذّر', RED, RED_SOFT
        if st == 'pending':
            return 'بانتظار التحويل', MUTED, SOFT
        if r.get('question'):
            return 'يحتاج قرارك', AMBER, AMBER_SOFT
        if r.get('alert'):
            return 'تم — راجع الأرقام', AMBER, AMBER_SOFT
        return 'تم', GREEN, GREEN_SOFT

    def _frow(self, i, r, last):
        """صف: # | المستند (الاسم وتحته النوع والحجم والمحرّك) | المقدّم | الحالة (وشريط التقدم) | إعادة القراءة."""
        w = QFrame()
        w.setObjectName('row')
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        w.setStyleSheet(f"QFrame#row{{border:none; border-bottom:{0 if last else 1}px solid {LINE}; background:white;}}"
                        f"QFrame#row:hover{{background:#f8fafc;}}")
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 7, 12, 7)
        h.setSpacing(COL_GAP)
        n = QLabel(str(i))
        n.setFixedSize(COL_NO, 24)
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        n.setStyleSheet(f"background:#eef2f7; border:none; border-radius:6px; color:#475569; font-family:{F};"
                        "font-size:11px; font-weight:700;")
        h.addWidget(n)
        nv = QVBoxLayout()
        nv.setSpacing(1)
        name = _lbl(os.path.splitext(r['name'])[0], 13, INK, True, wrap=False)
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        name.setToolTip(r['rel'])
        nv.addWidget(name)
        eng = doc_router.ENGINE_LABELS.get(r['engine'], '') if r['engine'] not in ('', 'direct', 'text') else ''
        meta = '  ·  '.join(x for x in (r['kind'], f"{r['pages']} صفحة" if r.get('pages') else '',
                                        human_size(r.get('size')), eng) if x)
        fn = _lbl(meta, 11, '#94a3b8', wrap=False)
        fn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        nv.addWidget(fn)
        h.addLayout(nv, 1)
        side = '' if self.is_court_doc(r) else (r.get('side') or '')
        defendant = 'عليه' in side or 'عليها' in side or 'ضد' in side
        cat = _pill(side or 'أخرى', INK2 if not side else ('#15803d' if defendant else AMBER),
                    SOFT if not side else (GREEN_SOFT if defendant else AMBER_SOFT), LINE)
        h.addWidget(_cell(cat, COL_CAT))
        text, fg, bg = self._fstate(r)
        pill = _pill(text, fg, bg, GREEN_LINE if fg == GREEN else None, icon='check' if fg == GREEN else None)
        if r['state'] == 'failed':
            pill.setToolTip(qd.friendly_error(r.get('message')))
        extra = None
        if r['state'] == 'running':
            extra = QProgressBar()
            extra.setFixedSize(90, 5)
            extra.setTextVisible(False)
            extra.setRange(0, 100)
            extra.setValue(int((r.get('live') or {}).get('pct') or 0))
            extra.setStyleSheet(f"QProgressBar{{background:{SOFT}; border:none; border-radius:2px;}}"
                                f"QProgressBar::chunk{{background:{BLUE}; border-radius:2px;}}")
        elif r['state'] == 'failed':
            extra = _link("أعد القراءة")
            extra.clicked.connect(lambda _=False, rel=r['rel']: self.reread.emit(rel, ''))
        elif r.get('question'):
            extra = _link("حدّد")
            extra.setToolTip(r['question'])
            extra.clicked.connect(lambda _=False, rel=r['rel']: self.answer.emit(rel))
        h.addWidget(_cell(pill, COL_STATE, extra))
        acts = None
        if r['state'] in ('done', 'failed'):
            acts = QWidget()
            acts.setStyleSheet("background:transparent;")
            al = QHBoxLayout(acts)
            al.setContentsMargins(0, 0, 0, 0)
            al.setSpacing(4)
            al.addWidget(self._reread_btn(r))
            if r['state'] == 'done':
                al.addWidget(self._icon_btn('sort', "إعادة فرز هذا الملف من markdown (بلا OCR)",
                                            lambda rel=r['rel']: self.retriage.emit([rel])))
            al.addStretch()
        h.addWidget(_cell(acts, COL_ACT))
        return w

    def _reread_btn(self, r):
        """السهم الدائري: يعيد تحويل هذا الملف وفرزه من البداية (بشريط تقدّم في الصف)."""
        import qt_icons
        b = QPushButton()
        b.setIcon(qt_icons.icon('refresh', '#475569', active=NAVY, size=16))
        b.setFixedSize(28, 28)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip("إعادة القراءة: تحويل المستند وفرزه من جديد")
        b.setStyleSheet(f"QPushButton{{background:white; border:1px solid {LINE}; border-radius:8px;}}"
                        f"QPushButton:hover{{background:{SOFT}; border-color:#cbd5e1;}}")
        b.clicked.connect(lambda _=False, rel=r['rel']: self.reread.emit(rel, ''))
        return b

    def _refresh_steps(self):
        """خطوات خط البداية في «ما يفعله البرنامج الآن» + أسئلة الفرز المعلّقة."""
        import case_sort
        import case_startup as cs
        src = self.step_source() if getattr(self, 'step_source', None) else self.data
        live = cs.live(self.base)
        st = live or cs.state(src)
        rows = []
        for k, label in cs.STEPS:
            s = st.get(k) or {'state': cs.PENDING}
            rows.append((k, s.get('state') or cs.PENDING, label, cs.counter_text(s), s.get('message') or ''))
        sig = tuple(rows)
        self._startup_live = live is not None and any(r[1] == cs.RUNNING for r in rows)
        if sig != getattr(self, '_steps_sig', None):
            self._steps_sig = sig
            self._steps_text = '\n'.join(f"{label} {counter} {msg}".strip() for _k, _s, label, counter, msg in rows)
            self._clear(self.steps_box)
            self._spinners = []
            for _k, state, label, counter, msg in rows:
                self.steps_box.addWidget(self._step_row(state, label, counter, msg))
        qs = tuple(case_sort.questions(src))
        if qs != getattr(self, '_qs', None):
            self._qs = qs
            self._clear(self.q_box)
            for rel, q in qs:
                row = QHBoxLayout()
                row.addWidget(_lbl(f"{os.path.basename(rel)}: {q}", 11, RED, True), 1)
                b = _btn("تحديد")
                b.clicked.connect(lambda _=False, r_=rel: self.answer.emit(r_))
                row.addWidget(b)
                self.q_box.addLayout(row)

    def steps_text(self):
        """نص الخطوات التسع كما تُعرض (للاختبار)."""
        return getattr(self, '_steps_text', '')

    def _step_row(self, state, label, counter, msg):
        """سطر خطوة: العنوان وتحته الحالة يميناً، ودائرة الحالة يساراً؛ الجارية في بطاقة زرقاء فاتحة."""
        import case_startup as cs
        import qt_icons
        running = state == cs.RUNNING
        w = QFrame()
        w.setObjectName('strow')
        w.setStyleSheet(f"QFrame#strow{{background:{BLUE_SOFT if running else 'transparent'};"
                        f"border:{('1px solid ' + BLUE_LINE) if running else 'none'}; border-radius:10px;}}")
        h = QHBoxLayout(w)
        h.setContentsMargins(*((10, 7, 10, 7) if running else (2, 4, 2, 4)))
        h.setSpacing(10)
        v = QVBoxLayout()
        v.setSpacing(3)
        title_col = {cs.RUNNING: BLUE_INK, cs.PENDING: INK2, cs.SKIPPED: MUTED}.get(state, NAVY)
        t = _lbl(label, 12, title_col, state != cs.PENDING)
        v.addWidget(t)
        sub, sub_col = msg, MUTED
        if state == cs.DONE and counter and not msg:
            v.addWidget(_pill(f"اكتمل ({counter})", MUTED, SOFT, LINE), 0, Qt.AlignmentFlag.AlignLeading)
            sub = ''
        elif state == cs.RUNNING:
            sub, sub_col = (msg or 'جارٍ العمل…') + (f" ({counter})" if counter else ''), BLUE
        elif state in (cs.FAILED, cs.INPUT):
            sub, sub_col = msg or cs.STATE_TEXT.get(state, ''), RED
        elif state == cs.PENDING and not msg:
            sub, sub_col = 'بانتظار', '#94a3b8'
        elif state == cs.SKIPPED and not msg:
            sub = cs.STATE_TEXT[cs.SKIPPED]
        elif counter:
            sub = f"{msg} ({counter})" if msg else counter
        if sub:
            v.addWidget(_lbl(sub, 11, sub_col))
        h.addLayout(v, 1)
        kind, fg, bg = {cs.DONE: ('check', '#16a34a', '#dcfce7'), cs.FAILED: ('close', RED, RED_SOFT),
                        cs.INPUT: ('alert', AMBER, '#fef3c7'), cs.RUNNING: ('spinner:0', BLUE, 'white')
                        }.get(state, ('dot', '#94a3b8', SOFT))
        ic = QLabel()
        ic.setFixedSize(24, 24)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setPixmap(qt_icons.pixmap(kind, fg, 14 if kind != 'dot' else 12))
        ic.setStyleSheet(f"background:{bg}; border-radius:12px; border:none;")
        if running:
            self._spinners.append(ic)
        h.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        return w

    def _refresh_progress(self):
        busy = self._busy()
        try:
            self._refresh_steps()
        except Exception:
            pass
        try:                                           # إعادة قراءة جارية لملف: شريط التقدّم في صفّه يتحدّث
            import case_folder
            if case_folder._REREAD or getattr(self, '_had_reread', False):
                self._had_reread = bool(case_folder._REREAD)
                if self._live_sig(self.folder_rows()) != getattr(self, '_rows_sig', None):
                    self._render_soon()
        except Exception:
            pass
        live = busy or getattr(self, '_startup_live', False)
        self.live_dot.setStyleSheet(f"background:{BLUE if live else '#94a3b8'}; border-radius:4px; border:none;")
        self.live_tag.setVisible(live)
        if self._spinners:                           # دوران أيقونة الخطوة الجارية (كل 400ms)
            import qt_icons
            self._spin = (getattr(self, '_spin', 0) + 45) % 360
            for ic in self._spinners:
                try:
                    ic.setPixmap(qt_icons.pixmap(f'spinner:{self._spin}', BLUE, 14))
                except RuntimeError:
                    pass
        self._clear(self.tl_lay)
        if not self._batch:
            self.total_lbl.setText("")
            self.bar.setVisible(False)
            self.tl_lay.addStretch()
            return
        pm = self.progress_model()
        self.total_lbl.setText(f"تم {pm['done']} من {pm['total']}")
        self.bar.setVisible(True)
        self.bar.setValue(pm['percent'])
        docs = {d['orig_name']: d for _p, d in case_documents.all_docs(self.data) if d['uid'] in self._batch}
        files = pm['files']
        for i, (name, st, pct) in enumerate(files):
            self.tl_lay.addWidget(self._tl_item(name, st, pct, docs.get(name) or {}, i == len(files) - 1))
        self.tl_lay.addStretch()

    def _tl_item(self, name, st, pct, d, last=False):
        """بند الخط الزمني: دائرة الحالة وخط رأسي يصلها بالتالي؛ الجاري في بطاقة بيضاء بشريط تقدّم."""
        outer = QWidget()
        ol = QHBoxLayout(outer)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(10)
        rail = QVBoxLayout()
        rail.setSpacing(0)
        rail.setContentsMargins(0, 4, 0, 0)
        mark, col = {'done': ('✓', GREEN), 'failed': ('✕', RED), 'running': ('◌', BLUE)}.get(st, ('•', '#b8c1cb'))
        m = QLabel(mark)
        m.setFixedSize(26, 26)
        m.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bg = {'done': GREEN_SOFT, 'failed': RED_SOFT, 'running': BLUE_SOFT}.get(st, '#eef1f4')
        m.setStyleSheet(f"color:{col}; border:1px solid {col}; border-radius:13px; font-size:12px; font-weight:700;"
                        f"background:{bg};")
        rail.addWidget(m, 0, Qt.AlignmentFlag.AlignHCenter)
        line = QFrame()
        line.setFixedWidth(2)
        line.setStyleSheet(f"background:{'transparent' if last else '#dde3e9'}; border:none;")
        rail.addWidget(line, 1, Qt.AlignmentFlag.AlignHCenter)
        ol.addLayout(rail)
        w = QFrame()
        w.setObjectName('tl')
        running = st == 'running'
        w.setStyleSheet(f"QFrame#tl{{background:{'white' if running else 'transparent'};"
                        f"border:{'1px solid #c8d8f0' if running else 'none'}; border-radius:10px;}}")
        v = QVBoxLayout(w)
        v.setContentsMargins(10 if running else 0, 8 if running else 4, 10 if running else 0, 12)
        v.setSpacing(4)
        head = {'done': 'تمت قراءة', 'failed': 'تعذّرت قراءة', 'running': 'جارٍ تحويل'}.get(st, 'بانتظار تحويل')
        t = _lbl(f"{head}: {name}", 13, '#9aa5b1' if st == 'pending' else INK, st != 'pending')
        t.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        t.setToolTip(name)
        v.addWidget(t)
        if running:
            b = QProgressBar()
            b.setFixedHeight(6)
            b.setTextVisible(False)
            if pct:
                b.setRange(0, 100)
                b.setValue(pct)
            else:
                b.setRange(0, 0)                     # محرّك بعيد (Gemini/Vision) لا يبلّغ بالصفحات ← شريط متحرك
            b.setStyleSheet(f"QProgressBar{{background:#e3e8ed; border:none; border-radius:3px;}}"
                            f"QProgressBar::chunk{{background:{NAVY}; border-radius:3px;}}")
            v.addWidget(b)
            eng = doc_router.ENGINE_LABELS.get(d.get('engine'), '')
            v.addWidget(_lbl(f"الآن • {pct}%" if pct else f"الآن • {eng or 'قراءة النص'}", 11, BLUE))
        elif st == 'done':
            v.addWidget(_lbl(" • ".join(x for x in (self._times.get(d.get('uid'), ''),
                                                    f"{d.get('pages')} صفحة" if d.get('pages') else '',
                                                    'حُفظ في ملف القضية') if x), 11, MUTED))
        elif st == 'failed':
            v.addWidget(_lbl(qd.friendly_error((d.get('convert') or {}).get('message')), 11, RED))
        else:
            v.addWidget(_lbl("في قائمة الانتظار", 11, '#b0b9c3'))
        ol.addWidget(w, 1)
        return outer

    def _say(self, text):
        self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    def _on_finished(self, base, res):
        if base != self.base:
            return
        super()._on_finished(base, res)
        self._fill_combo()
        if self._on_changed is not None:
            QTimer.singleShot(0, self._on_changed)

    def done(self, r):           # لوحة مضمَّنة لا تُغلق؛ التنظيف عند إتلافها (_teardown)
        pass


def _teardown(slots, base):
    for sig, slot in slots:
        try:
            sig.disconnect(slot)
        except (TypeError, RuntimeError):
            pass
    qd._OPEN.discard(base)
