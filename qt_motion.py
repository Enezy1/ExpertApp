# ===== qt_motion.py — حركة هادئة ومقتصدة لواجهة «مكتب الخبير» =====
# الحركة هنا للتوضيح والاستجابة فقط: 120–280ms، لا حلقات دائمة، لا انتظار.
# تحترم إعداد ويندوز «إظهار الحركات» (إمكانية الوصول): عند إطفائه تُلغى الحركة
# المكانية (الانزلاق والتتابع) ويبقى تلاشٍ قصير جدًا يوضّح تغيّر الحالة.
# بلا مكتبات إضافية: PyQt6 + ctypes (مكتبة بايثون القياسية).
import sys

import re

from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QTimer, QRect, QObject, QEvent
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QGraphicsDropShadowEffect

_MOTION = None


def motion_enabled():
    """هل الحركة مفعّلة بالنظام؟ (SPI_GETCLIENTAREAANIMATION) — تُقرأ مرة واحدة"""
    global _MOTION
    if _MOTION is None:
        _MOTION = True
        if sys.platform == 'win32':
            try:
                import ctypes
                val = ctypes.c_int(1)
                if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(val), 0):
                    _MOTION = bool(val.value)
            except Exception:
                pass
    return _MOTION


def fade_in(widget, duration=200, delay=0):
    """
    يُظهر العنصر بتلاشٍ ناعم. Qt يسمح بمؤثر رسومي واحد لكل عنصر — لو العنصر
    عليه ظل (البطاقات)، يُحفظ ويُعاد كما كان بعد انتهاء الحركة، فلا يبقى أي
    مؤثر إضافي يستهلك الأداء.
    """
    if widget is None:
        return
    if not motion_enabled():
        duration, delay = min(duration, 90), 0

    prev = widget.graphicsEffect()
    shadow = None
    if isinstance(prev, QGraphicsDropShadowEffect):
        shadow = (prev.blurRadius(), prev.offset(), prev.color())
    elif prev is not None:
        return                      # مؤثر آخر قائم (حركة سابقة جارية) — لا نتدخّل

    eff = QGraphicsOpacityEffect(widget)
    eff.setOpacity(0.0)
    widget.setGraphicsEffect(eff)

    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def done():
        if shadow:
            s = QGraphicsDropShadowEffect(widget)
            s.setBlurRadius(shadow[0])
            s.setOffset(shadow[1])
            s.setColor(shadow[2])
            widget.setGraphicsEffect(s)
        else:
            widget.setGraphicsEffect(None)

    anim.finished.connect(done)
    if delay:
        t = QTimer(widget)          # مربوط بالعنصر — يُحذف معه لو حُذف قبل الموعد
        t.setSingleShot(True)
        t.timeout.connect(anim.start)
        t.start(delay)
    else:
        anim.start()


def stagger(widgets, step=25, cap=8, duration=200):
    """تتابع ظهور قائمة: أول `cap` عناصر بفاصل `step`، والباقي يظهر فورًا (لا انتظار طويل)"""
    widgets = [w for w in widgets if w is not None]
    spatial = motion_enabled()
    for i, w in enumerate(widgets[:cap]):
        fade_in(w, duration, i * step if spatial else 0)


_EDGE_RE = re.compile(r"(border:\s*1px solid )(#[0-9A-Fa-f]{6})")


class _HoverEdge(QObject):
    """يلوّن حدّ البطاقة (1px) عند مرور الماوس ويعيده عند الخروج — بلا ظل إضافي (قاعدة الظل الواحد)"""
    def __init__(self, widget, color):
        super().__init__(widget)
        self.color = color

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.Enter:
            s = obj.styleSheet()
            m = _EDGE_RE.search(s)
            if m and m.group(2).lower() != self.color.lower():
                obj._edge_prev = m.group(2)
                obj.setStyleSheet(_EDGE_RE.sub(r"\g<1>" + self.color, s, count=1))
        elif t == QEvent.Type.Leave:
            prev = getattr(obj, "_edge_prev", None)
            if prev:
                obj.setStyleSheet(_EDGE_RE.sub(r"\g<1>" + prev, obj.styleSheet(), count=1))
                obj._edge_prev = None
        return False


def hover_edge(widget, color):
    """تفاعل مرور هادئ للبطاقات: الحدّ يتلوّن بلون كحلي خفيف"""
    f = _HoverEdge(widget, color)
    widget.installEventFilter(f)
    widget._hover_edge = f


def fade_window(win, duration=120):
    """تلاشٍ قصير لنافذة منبثقة (القوائم) — لا شيء لو الحركة مطفأة"""
    if not motion_enabled():
        return
    win.setWindowOpacity(0.0)
    a = QPropertyAnimation(win, b"windowOpacity", win)
    a.setDuration(duration)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.Type.OutCubic)
    a.start()
    win._fade_anim = a


def glide(widget, rect, duration=240):
    """ينقل عنصرًا لموضع جديد بانزلاق يتباطأ عند الوصول (أو فورًا لو الحركة مطفأة)"""
    rect = QRect(rect)
    if not motion_enabled() or not widget.isVisible() or widget.geometry().isEmpty():
        widget.setGeometry(rect)
        return
    anim = getattr(widget, "_glide_anim", None)
    if anim is None:
        anim = QPropertyAnimation(widget, b"geometry", widget)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        widget._glide_anim = anim
    anim.stop()
    anim.setDuration(duration)
    anim.setStartValue(widget.geometry())
    anim.setEndValue(rect)
    anim.start()
