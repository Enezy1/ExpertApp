# ===== qt_theme.py — نظام الألوان والمكوّنات المشتركة (تصميم Executive) =====
# مرجع: بريك داون إعادة تصميم نظام جلسات الخبراء — يُلزم كل الشاشات بنفس اللغة البصرية.
# القاعدة الثابتة: كل واجهة تُبنى باتجاه RTL كامل (نص + محاذاة + ترتيب عناصر).

import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase, QIcon

# ---------- الألوان (حسب لوحة الألوان المعتمدة بالمواصفات) ----------
BG          = "#FAFAF8"   # الخلفية الرئيسية — أبيض دافئ جداً
SURFACE     = "#FFFFFF"   # سطح البطاقات
BORDER      = "#EDEAE2"   # حدود رفيعة هادئة
BORDER_SOFT = "#F1EEE6"

TEXT_PRIMARY   = "#0F172A"
TEXT_SECONDARY = "#475569"
TEXT_MUTED     = "#94A3B8"

NAVY       = "#0F2747"   # اللون الرئيسي — كحلي مؤسساتي
NAVY_HOVER = "#153560"
NAVY_PRESSED = "#0A1C34"   # ضغط زر رئيسي — أغمق قليلًا من الكحلي
NAVY_SOFT  = "#F1F6F4"

SIDEBAR       = "#0F2747"
SIDEBAR_ITEM_ACTIVE = "rgba(255,255,255,0.08)"
SIDEBAR_TEXT_MUTED  = "#93A5C2"

EMERALD      = "#1D9E75"  # التأكيد الثانوي — أخضر داكن أنيق (زمردي)
EMERALD_BG   = "#E1F5EE"
EMERALD_TEXT = "#085041"

AMBER      = "#B45309"    # التحذير الزمني — ذهبي هادئ
AMBER_BG   = "#FAEEDA"
AMBER_TEXT = "#854F0B"

DANGER      = "#B42318"
DANGER_BG   = "#FBEAE9"
DANGER_TEXT = "#7A231C"

BLUE_INFO_BG   = "#EAF4FC"
BLUE_INFO_TEXT = "#0C447C"
INFO_BORDER    = "#CFE4F4"    # حدّ بطاقة القضية المحجوزة

# الاستعانة — لون مخصّص لها وحدها بكل الشاشات (قاعدة: الوردي = استعانة)
SECONDMENT_BG   = "#FDF2F6"
SECONDMENT_TEXT = "#C0392B"

# درجات مساعدة
EMERALD_HOVER    = "#178A63"   # مرور على زر زمردي
EMERALD_ON_NAVY  = "#3FC79A"   # نص زمردي صغير فوق الكحلي (7.0:1)
DANGER_ON_NAVY   = "#F4A39B"   # نص/نقطة «انقطع الاتصال» فوق الكحلي (7.5:1)
RULER_TRACK      = "#78859A"   # العلامات الفارغة بمسطرة المهلة (≥3.35:1 على كل خلفيات البطاقات)
BTN2_BORDER      = "#386380"   # حدّ الأزرار الثانوية (أغمق ليُرى على الأبيض)
BTN2_BG          = "#E6EEF4"   # خلفية الأزرار الثانوية الفاتحة
BTN2_HOVER       = "#D3E2EC"
NAVY_TINT        = "#E8EDF4"   # شارات كحلية هادئة (نوع الجلسة، «غدًا»)
RAIL_LINE        = "#C9D3E0"   # الخط الزمني بصفحة الجلسات
DISABLED_BG      = "#B9C2CE"   # زر رئيسي معطّل
SIDEBAR_DIVIDER  = "rgba(255,255,255,0.08)"   # فاصل رفيع فوق الكحلي
ON_NAVY_BORDER   = "rgba(255,255,255,0.3)"    # حدود زر ثانوي فوق خلفية كحلية

# شاشة الدخول (خلفية كحلية داكنة)
LOGIN_FIELD_BG        = "#0F1D30"
LOGIN_FIELD_BORDER    = "#24344C"
EMERALD_DISABLED_BG   = "#2E4A42"
EMERALD_DISABLED_TEXT = "#B7C3BF"

RADIUS_CARD = 16
RADIUS_BTN  = 10
RADIUS_PILL = 20

FONT_FAMILY = "Tajawal"

# ---------- سلّم الطباعة ----------
# Tajawal أوزانه المتوفرة: 400 / 500 / 700 / 800 فقط — الوزن 600 غير موجود
# ويُعرض 700 (عريض)، لذلك لا يُستخدم 600 بالتصميم.
FS_HERO, FS_DISPLAY, FS_HEADLINE, FS_TITLE = 28, 22, 20, 15
FS_BODY, FS_LABEL, FS_CAPTION = 13, 12, 11
W_REGULAR, W_MEDIUM, W_BOLD, W_HEAVY = 400, 500, 700, 800

_FONTS_LOADED = False


def _fonts_dir():
    # داخل EXE (PyInstaller) الملفات المضمّنة بـ sys._MEIPASS — ExpertApp.spec يضم مجلد fonts
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "fonts")


def load_window_icon():
    """
    أيقونة النافذة وشريط المهام: desk_icon (أيقونة «مكتب الخبير» الأصلية) ثم app_icon احتياطًا.
    تعمل من بايثون ومن EXE (الملفات المضمّنة بـ sys._MEIPASS). شعار الإدارة داخل الواجهة
    (الشريط الجانبي وشاشة الدخول) يبقى من load_app_icon كما هو.
    """
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    for name in ("desk_icon.ico", "desk_icon.png", "app_icon.ico", "app_icon.png"):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            return QIcon(path)
    return QIcon()


def load_fonts():
    """
    يسجّل خطوط Tajawal المضمّنة مع البرنامج (مجلد fonts) — تعمل من بايثون ومن EXE،
    فلا يحتاج الجهاز أن يكون الخط مثبّتًا عليه. يضبطه خطًا افتراضيًا للتطبيق كله
    (يشمل الرسائل والقوائم ومربعات الحوار). آمنة للاستدعاء أكثر من مرة.
    لو المجلد مفقود يرجع لخط النظام "Segoe UI" بدون أي خطأ.
    """
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return FONT_FAMILY if FONT_FAMILY in QFontDatabase.families() else "Segoe UI"
    fonts_dir = _fonts_dir()
    if os.path.isdir(fonts_dir):
        for f in sorted(os.listdir(fonts_dir)):
            if f.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(fonts_dir, f))
    _FONTS_LOADED = True
    if FONT_FAMILY not in QFontDatabase.families():
        return "Segoe UI"
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        default = QFont(FONT_FAMILY)
        default.setPixelSize(FS_BODY)
        app.setFont(default)
    return FONT_FAMILY


def app_font(size=13, weight=QFont.Weight.Normal):
    f = QFont(FONT_FAMILY, size)
    f.setWeight(weight)
    return f


def apply_rtl(widget):
    widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)


def ltr(text):
    """
    يعزل نص LTR (مسارات ملفات ويندوز، أرقام قضايا لاتينية...) داخل نص
    عربي RTL عشان ما ينعكس ترتيبه بصريًا (مشكلة bidi كلاسيكية —
    "C:\\Users\\...\\محاضر\\A123\\1.docx" كانت تطلع معكوسة داخل أي
    QMessageBox أو QLabel RTL). استخدمها لأي مسار/رابط/كود يُعرض وسط
    واجهة RTL.
    """
    return "⁦" + str(text) + "⁩"


# ملاحظة مهمة: بعد ما صار التطبيق كامل RTL (QApplication.setLayoutDirection)،
# Qt يبدّل تلقائيًا معنى AlignRight/AlignLeft ليطابق اتجاه القراءة المنطقي
# (AlignRight تصير تعني الحافة اليسرى فعليًا داخل ودجت RTL!). عشان نضمن
# محاذاة بصرية ثابتة ومتوقعة دائمًا (يمين = يمين فعليًا)، نستخدم هذين
# الثابتين بدل الأعلام الخام بكل الملفات.
ARIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute
ALEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute


GLOBAL_QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT_PRIMARY};
    font-family: "{FONT_FAMILY}", "Segoe UI";
}}
QLabel {{ background: transparent; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{
    background: {NAVY}; color: white; border: none;
    padding: 6px 10px; border-radius: 6px; font-size: 12px;
}}
QRadioButton {{ spacing: 8px; background: transparent; border: none; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border-radius: 9px;
    border: 1.5px solid {BORDER}; background: {SURFACE};
}}
QRadioButton::indicator:hover {{ border-color: {NAVY}; }}
QRadioButton::indicator:checked {{
    border: 5px solid {NAVY}; background: {SURFACE};
}}
QLineEdit, QComboBox {{ background: {SURFACE}; }}
"""


def card_style(bg=SURFACE, border=BORDER, radius=RADIUS_CARD):
    return f"""
        background: {bg};
        border: 1px solid {border};
        border-radius: {radius}px;
    """


def primary_button_style(radius=RADIUS_BTN):
    return f"""
        QPushButton {{
            background: {NAVY}; color: white; border: none;
            border-radius: {radius}px; padding: 10px 20px;
            font-size: {FS_BODY}px; font-weight: {W_BOLD};
        }}
        QPushButton:hover {{ background: {NAVY_HOVER}; }}
        QPushButton:pressed {{ background: {NAVY_PRESSED}; padding-top: 11px; padding-bottom: 9px; }}
        QPushButton:disabled {{ background: {DISABLED_BG}; color: #ffffff; }}
    """


def secondary_button_style(radius=RADIUS_BTN):
    return f"""
        QPushButton {{
            background: {BTN2_BG}; color: {NAVY};
            border: 1px solid {BTN2_BORDER}; border-radius: {radius}px;
            padding: 9px 16px; font-size: {FS_LABEL}px; font-weight: {W_MEDIUM};
        }}
        QPushButton:hover {{ background: {BTN2_HOVER}; border-color: {NAVY}; color: {NAVY}; }}
        QPushButton:pressed {{ background: {NAVY_TINT}; border-color: {NAVY}; color: {NAVY};
                               padding-top: 10px; padding-bottom: 8px; }}
        QPushButton:disabled {{ background: #F1F3F5; color: #8B97A3; border-color: #C5CED6; }}
    """


def badge_style(bg, text):
    return f"""
        background: {bg}; color: {text};
        border-radius: {RADIUS_PILL}px; padding: 4px 14px;
        font-size: {FS_CAPTION}px; font-weight: {W_BOLD};
    """
