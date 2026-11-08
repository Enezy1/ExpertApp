# ===== qt_report_card.py — شكل شاشة «تقارير الخبراء»: الألوان + بطاقة المؤشر + بطاقة القضية =====
# شكل فقط: كل البيانات تأتي جاهزة من reports_list_model. القيم مأخوذة من إعداد tailwind
# داخل design/code.html (secondary/primary-container/error/surface-container...).
# لتعديل الشكل غيّر الثوابت أدناه فقط.
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSizePolicy,
)

import reports_list_model as rlm

import qt_icons

# ---- ألوان التصميم (من tailwind-config في code.html) ----
SURFACE = '#f7fafd'
CARD = '#ffffff'
CONTAINER = '#ebeef1'
CONTAINER_HIGH = '#e5e8eb'
INK = '#181c1e'
INK_SOFT = '#44474c'
SECONDARY = '#386380'
SECONDARY_SOFT = '#c9e6ff'
PRIMARY_DARK = '#0f1c2c'
ERROR = '#ba1a1a'
ERROR_SOFT = '#ffdad6'
AMBER = '#b54708'
AMBER_SOFT = '#fef0c7'
IDLE = '#c4c6cc'
OUTLINE = '#c4c6cc'
GRAY_TEXT = '#74777d'

R_LG, R_XL = 8, 12                       # borderRadius lg / xl
FONT = "'IBM Plex Sans Arabic','Segoe UI',Tahoma"
FONT_DIR_NAME = 'fonts'


def load_plex():
    """يسجّل IBM Plex Sans Arabic من assets/fonts إن وُجدت (بلا إنترنت). يرجع True إن نجح."""
    import os
    import sys
    from PyQt6.QtGui import QFontDatabase
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, 'assets', FONT_DIR_NAME)
    ok = False
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.lower().endswith('.ttf') and QFontDatabase.addApplicationFont(os.path.join(d, f)) >= 0:
                ok = True
    return ok


def base_qss():
    return f"font-family:{FONT};"


def card_frame_qss(name, bg=CARD, border=OUTLINE, radius=R_XL):
    return f"QFrame#{name}{{background:{bg}; border:1px solid {border}; border-radius:{radius}px;}}"


def _label(text, size, color, bold=False):
    l = QLabel(text)
    l.setStyleSheet(f"font-family:{FONT}; font-size:{size}px; color:{color}; border:none;"
                    f"font-weight:{700 if bold else 400}; background:transparent;")
    l.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter)
    return l


def _pill(text, bg, fg, size=11):
    l = _label(text, size, fg, True)
    l.setAlignment(Qt.AlignmentFlag.AlignCenter)
    l.setStyleSheet(l.styleSheet() + f"background:{bg}; border-radius:10px; padding:2px 10px;")
    return l


class StatCard(QFrame):
    """بطاقة مؤشر: عنوان + رقم كبير + شريط رفيع (عنبري عند alert)."""

    def __init__(self, title, value, alert=False, parent=None):
        super().__init__(parent)
        self.setObjectName('stat')
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet(card_frame_qss('stat'))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)
        lay.addWidget(_label(title, 12, INK_SOFT))
        self.num = _label(str(value), 32, AMBER if alert else INK, True)
        lay.addWidget(self.num)
        self.bar = QFrame()
        self.bar.setFixedHeight(4)
        self.bar.setStyleSheet(f"background:{AMBER if alert else SECONDARY}; border-radius:2px;")
        lay.addWidget(self.bar)


# لون الشريط الجانبي والنص حسب حالة البطاقة (لا علاقة بقرب الجلسة)
ACCENT_COLOR = {rlm.ACCENT_NORMAL: SECONDARY, rlm.ACCENT_INPUT: AMBER, rlm.ACCENT_FAILED: ERROR}
# (لون التعبئة، لون الإطار، رمز داخل النقطة)
DOT_STYLE = {
    rlm.ST_DONE: (SECONDARY, SECONDARY, '✓'),
    rlm.ST_CURRENT: ('white', SECONDARY, ''),   # حلقة سميكة بوسط أبيض (رمز ● غير موجود في الخط)
    rlm.ST_INPUT: (AMBER, AMBER, '!'),
    rlm.ST_FAILED: (ERROR, ERROR, '×'),
    rlm.ST_IDLE: (CONTAINER, IDLE, ''),
}
DOT = 20


def step_dot(name, status):
    """نقطة خطوة واحدة؛ المؤشر عليها يُظهر «الاسم — الحالة»."""
    fill, ring, glyph = DOT_STYLE[status]
    fg = SECONDARY if status == rlm.ST_CURRENT else 'white'
    d = QLabel(glyph)
    d.setFixedSize(DOT, DOT)
    d.setAlignment(Qt.AlignmentFlag.AlignCenter)
    d.setToolTip(f"{name} — {rlm.ST_TEXT[status]}")
    d.setStyleSheet(f"font-family:{FONT}; font-size:11px; font-weight:700; color:{fg};"
                    f"background:{fill}; border:{5 if status == rlm.ST_CURRENT else 2}px solid {ring};"
                    f"border-radius:{DOT // 2}px;")
    return d


def steps_strip(steps):
    """سبع نقاط مرتبة يمين←يسار (RTL) يصل بينها خط رفيع."""
    w = QWidget()
    w.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    for i, (_k, name, status, _m) in enumerate(steps):
        if i:
            line = QFrame()
            line.setFixedSize(16, 2)
            line.setStyleSheet(f"background:{OUTLINE}; border:none;")
            lay.addWidget(line)
        lay.addWidget(step_dot(name, status))
    lay.addStretch()
    return w


def _party_line(role, names, color):
    if names:
        txt = f"<span style='color:{SECONDARY}'>{role}:</span> <b>{names}</b>"
    else:
        txt = f"<span style='color:{SECONDARY}'>{role}:</span> <span style='color:{GRAY_TEXT}'>غير محدد</span>"
    l = _label(txt, 14, color)
    l.setTextFormat(Qt.TextFormat.RichText)
    l.setWordWrap(True)
    return l


class ReportCaseCard(QFrame):
    open_track = pyqtSignal(object)        # يحمل بيانات البطاقة (dict من build_card)
    open_documents = pyqtSignal(object)

    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self.vm = vm
        self.setObjectName('rcard')
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet(card_frame_qss('rcard'))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        accent = ACCENT_COLOR[vm['accent']]

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 18, 14)
        root.setSpacing(14)

        side = QFrame()                     # العمود الجانبي الملوّن (يمين البطاقة في RTL)
        side.setFixedWidth(5)
        side.setStyleSheet(f"background:{accent}; border:none; border-radius:2px;")
        root.addWidget(side)

        main = QVBoxLayout()
        main.setSpacing(8)
        root.addLayout(main, 1)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(_label(vm['caso_no'], 18, INK, True))
        if vm['company']:
            top.addWidget(_pill(vm['company'], SECONDARY_SOFT, '#001e2f'))
        if vm['court']:
            top.addWidget(_pill(vm['court'], CONTAINER_HIGH, INK))
        top.addStretch()
        main.addLayout(top)

        if vm['plaintiff'] or vm['defendant'] or not vm['other_party']:
            main.addWidget(_party_line('المدعي', vm['plaintiff'], INK))
            main.addWidget(_party_line('المدعى عليه', vm['defendant'], INK))
        else:                               # العنوان اسم واحد لا يُعرف دوره: لا نخمّن
            main.addWidget(_party_line('الأطراف', vm['other_party'], INK))

        main.addWidget(steps_strip(vm['steps']))
        hint_color = {rlm.ACCENT_NORMAL: INK_SOFT if vm['started'] else GRAY_TEXT}.get(vm['accent'], accent)
        hint = _label(vm['hint'], 12, hint_color, vm['accent'] != rlm.ACCENT_NORMAL)
        hint.setWordWrap(True)
        main.addWidget(hint)

        acts = QVBoxLayout()
        acts.setSpacing(8)
        acts.addStretch()
        go = QPushButton("فتح مسار التقرير")
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.setStyleSheet(f"QPushButton{{font-family:{FONT}; background:{PRIMARY_DARK}; color:white;"
                         f"border:none; border-radius:{R_LG}px; padding:9px 22px; font-size:13px; font-weight:700;}}"
                         f"QPushButton:hover{{background:{SECONDARY};}}")
        go.clicked.connect(lambda: self.open_track.emit(self.vm))
        acts.addWidget(go)
        if vm['has_workspace']:             # أزرار صغيرة: فقط ما وظيفته متاحة من القائمة
            small = QHBoxLayout()
            small.addStretch()
            docs = QPushButton()
            docs.setToolTip("فتح مجلد القضية")
            docs.setIcon(qt_icons.icon('folder', INK))
            docs.setFixedSize(34, 34)
            docs.setCursor(Qt.CursorShape.PointingHandCursor)
            docs.setStyleSheet(f"QPushButton{{background:{CONTAINER}; border:none; border-radius:{R_LG}px;}}"
                               f"QPushButton:hover{{background:{CONTAINER_HIGH};}}")
            docs.clicked.connect(lambda: self.open_documents.emit(self.vm))
            small.addWidget(docs)
            acts.addLayout(small)
        acts.addStretch()
        root.addLayout(acts)

