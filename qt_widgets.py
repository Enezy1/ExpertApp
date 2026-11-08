# ===== qt_widgets.py — مكوّنات مشتركة (design system) للتصميم الجديد =====
from datetime import datetime
import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QFrame,
    QGraphicsDropShadowEffect, QSizePolicy, QLineEdit
)
from PyQt6.QtGui import QColor, QCursor

import qt_theme as th


def soft_shadow(widget, blur=22, y=6, alpha=18):
    """ظل ناعم جداً وخفيف — فصل طبقي بسيط بدون shadow ثقيل"""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, y)
    eff.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(eff)


class Card(QFrame):
    """بطاقة أساسية: زوايا 16px، حدود رفيعة هادئة، ظل ناعم جداً"""
    clicked = pyqtSignal()

    def __init__(self, bg=th.SURFACE, border=th.BORDER, radius=th.RADIUS_CARD, clickable=False, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame#card {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
        """)
        self.setObjectName("card")
        # لازم لضمان رسم الخلفية المحددة بالـ QSS فعليًا (وإلا بعض الأنماط
        # على ويندوز تعرض ما وراء الودجت بدل الخلفية البيضاء المطلوبة)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        soft_shadow(self)
        if clickable:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, e):
        self.clicked.emit()
        super().mousePressEvent(e)


class Badge(QLabel):
    def __init__(self, text, bg, color, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(th.badge_style(bg, color))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class _HoverFade:
    """
    انتقال ناعم (120ms) للون خلفية الزر عند دخول/خروج الماوس — عرض فقط.
    يعمل فقط والزر بتنسيقه الافتراضي: أي زر خُصّص تنسيقه لاحقًا (مثل زر الإعادة
    الأحمر) يبقى كما هو بالتبدّل الفوري المعتاد، فلا يُكسر أي تنسيق خاص.
    """
    def _hf_setup(self, base_qss, normal, hover):
        self._hf_base = base_qss
        self._hf_from = QColor(normal)
        self._hf_to = QColor(hover)
        self._hf_anim = None

    def _hf_run(self, forward):
        import qt_motion as mo
        if not self.isEnabled() or not mo.motion_enabled():
            return
        animating = self._hf_anim is not None and self._hf_anim.state() == self._hf_anim.State.Running
        if not animating and self.styleSheet() != self._hf_base:
            return                                   # زر مخصّص — لا نتدخّل
        from PyQt6.QtCore import QVariantAnimation, QEasingCurve
        start = self._hf_anim.currentValue() if animating else (0.0 if forward else 1.0)
        if animating:
            self._hf_anim.stop()
        a = QVariantAnimation(self)
        a.setStartValue(float(start))
        a.setEndValue(1.0 if forward else 0.0)
        a.setDuration(120)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(self._hf_tick)
        a.finished.connect(lambda: self.setStyleSheet(self._hf_base))
        self._hf_anim = a
        a.start()

    def _hf_tick(self, t):
        t = float(t)
        c0, c1 = self._hf_from, self._hf_to
        r = round(c0.red() + (c1.red() - c0.red()) * t)
        g = round(c0.green() + (c1.green() - c0.green()) * t)
        b = round(c0.blue() + (c1.blue() - c0.blue()) * t)
        a = round(c0.alpha() + (c1.alpha() - c0.alpha()) * t)
        css = f"rgba({r},{g},{b},{a})"
        self.setStyleSheet(self._hf_base + f"QPushButton, QPushButton:hover {{ background: {css}; }}")

    def _hf_stop(self):
        if self._hf_anim is not None:
            self._hf_anim.stop()
            self._hf_anim = None
            self.setStyleSheet(self._hf_base)

    def enterEvent(self, e):
        self._hf_run(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hf_run(False)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._hf_stop()                              # حالة الضغط تظهر فورًا كما هي
        super().mousePressEvent(e)


class PrimaryButton(_HoverFade, QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(th.primary_button_style())
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(th.app_font(13))
        self._hf_setup(th.primary_button_style(), th.NAVY, th.NAVY_HOVER)


class SecondaryButton(_HoverFade, QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(th.secondary_button_style())
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(th.app_font(12))
        self._hf_setup(th.secondary_button_style(), th.BTN2_BG, th.BTN2_HOVER)


class KPICard(Card):
    def __init__(self, label, value, value_color=th.TEXT_PRIMARY, parent=None):
        super().__init__(parent=parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(6)
        lay.setDirection(QVBoxLayout.Direction.TopToBottom)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none;")
        lbl.setAlignment(th.ARIGHT)

        val = QLabel(value)
        val.setStyleSheet(f"color:{value_color}; font-size:{th.FS_DISPLAY}px; font-weight:{th.W_BOLD}; border:none;")
        val.setAlignment(th.ARIGHT)
        self.value_label = val

        lay.addWidget(lbl)
        lay.addWidget(val)


class SidebarItem(QFrame):
    clicked = pyqtSignal()

    def __init__(self, icon_text, label_text, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._active = False
        self.setFixedHeight(46)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 0, 14, 0)
        root.setSpacing(10)

        self.indicator = QFrame()
        self.indicator.setFixedWidth(3)
        self.indicator.setStyleSheet(f"background:{th.EMERALD}; border-radius:2px;")
        self.indicator.setVisible(False)

        self.lbl = QLabel(f"{label_text}")
        self.lbl.setStyleSheet(f"color:{th.SIDEBAR_TEXT_MUTED}; font-size:14px; background:transparent; border:none;")

        icon = QLabel(icon_text)
        icon.setStyleSheet("font-size:15px; background:transparent; border:none;")
        icon.setFixedWidth(20)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        root.addWidget(self.indicator)
        root.addWidget(self.lbl)
        root.addStretch()
        root.addWidget(icon)
        self._apply()

    def set_active(self, active):
        self._active = active
        self._apply()

    def _apply(self):
        if self._active:
            self.setStyleSheet(f"""
                QFrame {{ background: {th.SIDEBAR_ITEM_ACTIVE}; border-radius: 10px; border: none; }}
            """)
            self.lbl.setStyleSheet(f"color:white; font-size:14px; font-weight:{th.W_BOLD}; background:transparent; border:none;")
            self.indicator.setVisible(True)
        else:
            self.setStyleSheet("QFrame { background: transparent; border-radius: 10px; border: none; }")
            self.lbl.setStyleSheet(f"color:{th.SIDEBAR_TEXT_MUTED}; font-size:14px; background:transparent; border:none;")
            self.indicator.setVisible(False)

    def mousePressEvent(self, e):
        self.clicked.emit()
        super().mousePressEvent(e)


class PageHeader(QWidget):
    """عنوان الصفحة الرئيسي + سطر وصفي ثانوي أنيق"""
    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        t = QLabel(title)
        t.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:{th.FS_HEADLINE}px; font-weight:{th.W_BOLD}; border:none;")
        t.setAlignment(th.ARIGHT)
        lay.addWidget(t)

        self.subtitle_label = None
        if subtitle:
            s = QLabel(subtitle)
            s.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:13px; border:none;")
            s.setAlignment(th.ARIGHT)
            lay.addWidget(s)
            self.subtitle_label = s


def _field_qss(border=None):
    border = border or th.BORDER
    return f"""
        QLineEdit {{
            background: white; border: 1px solid {border}; border-radius: 10px;
            padding: 9px 12px; font-size: 13px; color: {th.TEXT_PRIMARY};
        }}
        QLineEdit:focus {{ border: 1px solid {th.NAVY}; }}
    """


class SmartDateEdit(QLineEdit):
    """
    حقل تاريخ ذكي — نفس منطق SmartDateEntry الأصلي بالضبط (يقبل أرقام
    خام بدون فواصل زي '17' أو '1706' ويكمل السنة تلقائيًا، أو تاريخ
    كامل DD/MM/YYYY)، لكن كـ QLineEdit بسيط بدل ودجت مركّبة. القيمة
    النهائية بصيغة 'YYYY/MM/DD' متوافقة مع كل دوال api.py.
    """
    def __init__(self, initial="", danger=False, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("DD/MM/YYYY")
        self.setStyleSheet(_field_qss(th.DANGER if danger else None))
        self.setAlignment(th.ARIGHT)
        if initial:
            self.setText(initial)

    def _parse(self, raw):
        raw = (raw or "").strip()
        today = datetime.now()
        y, m = today.year, today.month

        if '/' in raw or '-' in raw:
            parts = [p for p in re.split(r'[/\-]', raw) if p != '']
            if len(parts) >= 2 and all(p.isdigit() for p in parts):
                try:
                    day = int(parts[0])
                    mon = int(parts[1])
                    if not (1 <= day <= 31 and 1 <= mon <= 12):
                        return None
                    if len(parts) >= 3 and parts[2]:
                        yr = int(parts[2])
                        if yr < 100:
                            yr += 2000
                    else:
                        yr = y if (mon > m or (mon == m and day >= today.day)) else y + 1
                    datetime(yr, mon, day)
                    return f"{yr}/{mon:02d}/{day:02d}"
                except Exception:
                    return None
            return None

        d = raw
        if not d.isdigit():
            return None
        try:
            if len(d) == 1:
                return None
            elif len(d) == 2:
                day = int(d)
                if not 1 <= day <= 31:
                    return None
                if day >= today.day:
                    return datetime(y, m, day).strftime('%Y/%m/%d')
                nm = m + 1 if m < 12 else 1
                ny = y if m < 12 else y + 1
                return datetime(ny, nm, day).strftime('%Y/%m/%d')
            elif len(d) == 3:
                day, mon = int(d[:2]), int(d[2])
                if not (1 <= day <= 31 and 1 <= mon <= 9):
                    return None
                yr = y if (mon > m or (mon == m and day >= today.day)) else y + 1
                return f"{yr}/{mon:02d}/{day:02d}"
            elif len(d) == 4:
                day, mon = int(d[:2]), int(d[2:])
                if not (1 <= day <= 31 and 1 <= mon <= 12):
                    return None
                yr = y if (mon > m or (mon == m and day >= today.day)) else y + 1
                return f"{yr}/{mon:02d}/{day:02d}"
            elif len(d) == 8:
                y2, m2, d2 = int(d[:4]), int(d[4:6]), int(d[6:])
                datetime(y2, m2, d2)
                return f"{y2}/{m2:02d}/{d2:02d}"
        except Exception:
            return None
        return None

    def focusOutEvent(self, e):
        raw = self.text().strip()
        if raw:
            parsed = self._parse(raw)
            if parsed:
                self.setText(parsed)
        super().focusOutEvent(e)

    def get_value(self):
        raw = self.text().strip()
        parsed = self._parse(raw)
        if parsed:
            self.setText(parsed)
            return parsed
        return raw


class SmartTimeEdit(QWidget):
    """حقل وقت ذكي — نفس منطق SmartTimeEntry الأصلي (زر تبديل ص/م + نص رقمي)"""
    def __init__(self, initial="10:00", danger=False, parent=None):
        super().__init__(parent)
        self._suffix = "ص"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.entry = QLineEdit()
        self.entry.setStyleSheet(_field_qss(th.DANGER if danger else None))
        self.entry.setFixedWidth(90)
        self.entry.setAlignment(th.ARIGHT)

        self.sfx_btn = QPushButton("ص")
        self.sfx_btn.setFixedSize(40, 38)
        self.sfx_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.sfx_btn.setStyleSheet(f"""
            QPushButton {{ background:{th.EMERALD}; color:white; border:none;
                border-radius:9px; font-weight:700; font-size:12px; }}
            QPushButton:hover {{ background:{th.EMERALD_HOVER}; }}
        """)
        self.sfx_btn.clicked.connect(self._toggle)

        lay.addWidget(self.sfx_btn)
        lay.addWidget(self.entry)

        self.set_value(initial)

    def _toggle(self):
        self._suffix = 'م' if self._suffix == 'ص' else 'ص'
        self.sfx_btn.setText(self._suffix)

    def _fmt(self):
        val = self.entry.text().replace(':', '').strip()
        if not val.isdigit():
            return
        try:
            if len(val) <= 2:
                h, mn = int(val), 0
            elif len(val) == 3:
                h, mn = int(val[0]), int(val[1:])
            else:
                h, mn = int(val[:2]), int(val[2:4])
            if mn >= 60:
                mn = 0
            if 7 <= h <= 11:
                self._suffix = 'ص'
            elif 1 <= h <= 3:
                self._suffix = 'م'
            self.sfx_btn.setText(self._suffix)
            h24 = h + 12 if self._suffix == 'م' and h < 12 else h
            if h24 > 15:
                h, mn = 3, 0
                self._suffix = 'م'
                self.sfx_btn.setText(self._suffix)
            self.entry.setText(f"{h:02d}:{mn:02d}")
        except Exception:
            pass

    def get_value(self):
        """يرجع الوقت بصيغة 24 ساعة 'HH:MM' — نفس ما تتوقعه دوال api.py"""
        self._fmt()
        val = self.entry.text().replace(':', '').strip()
        try:
            if len(val) <= 2:
                h, mn = int(val), 0
            elif len(val) == 3:
                h, mn = int(val[0]), int(val[1:])
            else:
                h, mn = int(val[:2]), int(val[2:4])
            if self._suffix == 'م' and h < 12:
                h += 12
            if h > 15:
                h = 15
            return f"{h:02d}:{mn:02d}"
        except Exception:
            return "10:00"

    def set_value(self, v):
        try:
            p = v.split(':')
            h, mn = int(p[0]), int(p[1]) if len(p) > 1 else 0
            self._suffix = "ص" if h < 12 else "م"
            self.sfx_btn.setText(self._suffix)
            dh = h if h <= 12 else h - 12
            self.entry.setText(f"{dh:02d}:{mn:02d}")
        except Exception:
            self.entry.setText(v)


class SummaryLine(QLabel):
    """سطر «ملخص الدعوى» بالبطاقات: شريط زمردي رفيع على جهة البداية (يمين) +
    وسم صغير «ملخص الدعوى» — يميّزه عن بقية الحقول بدون ما يغيّر مقاسات البطاقة"""
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(th.ARIGHT)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setStyleSheet(
            f"color:{th.TEXT_PRIMARY}; font-size:{th.FS_LABEL}px; background:transparent; "
            f"border:none; border-right:2px solid {th.EMERALD}; padding-top:1px; padding-bottom:1px;")
        self.setContentsMargins(0, 0, 0, 0)
        self.setIndent(10)
        self.set_summary(text) if text else self.set_loading()

    def _render(self, body, muted=False):
        from html import escape
        color = th.TEXT_MUTED if muted else th.TEXT_PRIMARY
        self.setText(f'<span style="color:{th.EMERALD_TEXT}; font-weight:{th.W_MEDIUM};">ملخص الدعوى</span>'
                     f'<span style="color:{th.TEXT_MUTED};">  ·  </span>'
                     f'<span style="color:{color};">{escape(body)}</span>')

    def set_summary(self, text):
        self._render(text)

    def set_loading(self):
        self._render("⏳ جاري التحميل...", muted=True)
