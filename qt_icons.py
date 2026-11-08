# ===== qt_icons.py — أيقونات خطية مرسومة بالكود (هوية «مكتب الخبير») =====
# بلا ملفات صور ولا مكتبات إضافية — QPainter فقط، فتعمل كما هي داخل EXE (PyInstaller).
# الأسلوب: شبكة 18×18، خط 1.6px، أطراف وزوايا دائرية، تُرسم بدقة مضاعفة لتبقى حادّة.
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QPixmap, QIcon, QPainterPath

import qt_theme as th


def _draw(p, kind, color):
    pen = QPen(QColor(color), 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    def dot(x, y, r):
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(color)))
        p.drawEllipse(QPointF(x, y), r, r)
        p.restore()

    def path(*pts, close=False):
        pa = QPainterPath()
        pa.moveTo(*pts[0])
        for pt in pts[1:]:
            pa.lineTo(*pt)
        if close:
            pa.closeSubpath()
        p.drawPath(pa)

    if kind == 'calendar':            # ورقة تقويم: حلقتان + سطر رأس + نقطة يوم
        p.drawRoundedRect(QRectF(2.5, 4.0, 13.0, 11.5), 2.2, 2.2)
        p.drawLine(QPointF(6.0, 2.4), QPointF(6.0, 5.6))
        p.drawLine(QPointF(12.0, 2.4), QPointF(12.0, 5.6))
        p.drawLine(QPointF(2.5, 7.8), QPointF(15.5, 7.8))
        dot(11.4, 11.6, 1.4)
    elif kind == 'gov':               # مبنى حكومي: سقف مثلث + ثلاثة أعمدة + قاعدة
        path((2.2, 6.6), (9.0, 2.4), (15.8, 6.6), close=True)
        for x in (4.8, 9.0, 13.2):
            p.drawLine(QPointF(x, 8.8), QPointF(x, 13.2))
        p.drawLine(QPointF(2.2, 15.6), QPointF(15.8, 15.6))
    elif kind in ('session', 'clock'):  # ساعة (+ علامة إضافة للجلسة القادمة)
        cx = 7.6 if kind == 'session' else 9.0
        p.drawEllipse(QPointF(cx, 10.0 if kind == 'session' else 9.0), 5.6 if kind == 'session' else 6.5, 5.6 if kind == 'session' else 6.5)
        cy = 10.0 if kind == 'session' else 9.0
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy - 3.1))
        p.drawLine(QPointF(cx, cy), QPointF(cx + 2.2, cy + 1.3))
        if kind == 'session':
            p.drawLine(QPointF(14.6, 1.9), QPointF(14.6, 6.3))
            p.drawLine(QPointF(12.4, 4.1), QPointF(16.8, 4.1))
    elif kind in ('folder', 'folder_plus'):   # ملف قضية (+ إضافة)
        path((2.5, 5.2), (2.5, 14.0), (15.5, 14.0), (15.5, 6.8), (9.2, 6.8), (7.6, 4.4), (3.3, 4.4), close=True)
        if kind == 'folder_plus':
            p.drawLine(QPointF(9.0, 8.4), QPointF(9.0, 12.4))
            p.drawLine(QPointF(7.0, 10.4), QPointF(11.0, 10.4))
    elif kind == 'inbox':             # صندوق وارد: سهم داخل + درج
        p.drawLine(QPointF(9.0, 1.8), QPointF(9.0, 8.6))
        path((6.6, 6.4), (9.0, 8.8), (11.4, 6.4))
        path((2.5, 10.6), (2.5, 15.2), (15.5, 15.2), (15.5, 10.6))
        path((2.5, 10.6), (5.8, 10.6), (6.8, 12.6), (11.2, 12.6), (12.2, 10.6), (15.5, 10.6))
    elif kind == 'gear':              # ترس الإعدادات
        p.drawEllipse(QPointF(9.0, 9.0), 4.6, 4.6)
        p.drawEllipse(QPointF(9.0, 9.0), 1.8, 1.8)
        import math
        for i in range(8):
            a = math.radians(i * 45)
            p.drawLine(QPointF(9 + 4.6 * math.cos(a), 9 + 4.6 * math.sin(a)),
                       QPointF(9 + 6.8 * math.cos(a), 9 + 6.8 * math.sin(a)))
    elif kind == 'search':            # عدسة البحث
        p.drawEllipse(QPointF(7.8, 7.8), 4.8, 4.8)
        p.drawLine(QPointF(11.4, 11.4), QPointF(15.6, 15.6))
    elif kind == 'refresh':           # تحديث: قوس مع رأس سهم
        p.drawArc(QRectF(3.2, 3.2, 11.6, 11.6), 70 * 16, 290 * 16)
        path((9.6, 1.6), (12.0, 3.4), (9.8, 5.6))
    elif kind == 'sort':              # إعادة فرز: ثلاثة أسطر متناقصة (نوع/مقدّم/تاريخ) + سهم صغير
        p.drawLine(QPointF(2.6, 4.6), QPointF(11.4, 4.6))
        p.drawLine(QPointF(2.6, 9.0), QPointF(9.0, 9.0))
        p.drawLine(QPointF(2.6, 13.4), QPointF(6.6, 13.4))
        p.drawLine(QPointF(14.2, 6.2), QPointF(14.2, 14.6))
        path((12.2, 12.6), (14.2, 14.6), (16.2, 12.6))
    elif kind == 'pen':               # إعادة كتابة: قلم مائل + سطر
        path((4.0, 14.0), (4.6, 11.0), (12.4, 3.2), (14.8, 5.6), (7.0, 13.4), close=True)
        p.drawLine(QPointF(10.8, 4.8), QPointF(13.2, 7.2))
        p.drawLine(QPointF(9.6, 15.6), QPointF(15.4, 15.6))
    elif kind == 'chart':             # إحصائية: ثلاثة أعمدة على خط أساس
        p.drawRoundedRect(QRectF(3.6, 9.4, 2.8, 5.6), 1.0, 1.0)
        p.drawRoundedRect(QRectF(7.6, 4.4, 2.8, 10.6), 1.0, 1.0)
        p.drawRoundedRect(QRectF(11.6, 7.2, 2.8, 7.8), 1.0, 1.0)
        p.drawLine(QPointF(2.2, 16.0), QPointF(15.8, 16.0))
    elif kind == 'print':             # طابعة: ورقة داخلة + جسم + ورقة خارجة
        p.drawRoundedRect(QRectF(5.2, 2.4, 7.6, 4.2), 0.8, 0.8)
        p.drawRoundedRect(QRectF(2.4, 6.6, 13.2, 6.6), 1.8, 1.8)
        p.drawRoundedRect(QRectF(5.2, 10.8, 7.6, 5.0), 0.8, 0.8)
        dot(13.0, 8.9, 0.8)
    elif kind == 'check':             # علامة صح
        path((3.6, 9.6), (7.3, 13.2), (14.6, 5.2))
    elif kind == 'return':            # إعادة: سهم منعطف نحو اليمين (RTL)
        pa = QPainterPath()
        pa.moveTo(14.4, 12.6)
        pa.lineTo(7.2, 12.6)
        pa.cubicTo(3.0, 12.6, 3.0, 5.8, 7.2, 5.8)
        pa.lineTo(13.4, 5.8)
        p.drawPath(pa)
        path((10.8, 3.2), (13.4, 5.8), (10.8, 8.4))
    elif kind == 'offline':           # لا اتصال: أقواس إشارة مع خط قطري
        p.drawArc(QRectF(2.0, 4.6, 14.0, 14.0), 50 * 16, 80 * 16)
        p.drawArc(QRectF(5.0, 7.6, 8.0, 8.0), 50 * 16, 80 * 16)
        dot(9.0, 13.6, 1.3)
        p.drawLine(QPointF(3.0, 2.8), QPointF(15.0, 15.6))
    elif kind == 'alert':             # تنبيه: مثلث + علامة تعجّب
        path((9.0, 2.6), (16.0, 15.0), (2.0, 15.0), close=True)
        p.drawLine(QPointF(9.0, 7.0), QPointF(9.0, 10.6))
        dot(9.0, 12.9, 1.0)
    elif kind == 'seal':              # ختم: دائرتان + علامة صح
        p.drawEllipse(QPointF(9.0, 9.0), 7.0, 7.0)
        p.save()
        p.setPen(QPen(QColor(color), 0.9))
        p.drawEllipse(QPointF(9.0, 9.0), 5.0, 5.0)
        p.restore()
        path((6.6, 9.2), (8.4, 10.9), (11.6, 7.4))
    elif kind == 'upload':            # رفع: سهم صاعد فوق صينية
        p.drawLine(QPointF(9.0, 2.8), QPointF(9.0, 11.4))
        path((5.6, 6.0), (9.0, 2.6), (12.4, 6.0))
        path((3.0, 11.0), (3.0, 15.0), (15.0, 15.0), (15.0, 11.0))
    elif kind == 'file':              # ملف: ورقة بزاوية مطوية وسطرين
        path((4.0, 2.4), (10.6, 2.4), (14.0, 5.8), (14.0, 15.6), (4.0, 15.6), close=True)
        path((10.4, 2.6), (10.4, 6.0), (13.8, 6.0))
        p.drawLine(QPointF(6.6, 9.4), QPointF(11.4, 9.4))
        p.drawLine(QPointF(6.6, 12.4), QPointF(11.4, 12.4))
    elif kind == 'folder':            # مجلد: لسان + جسم
        path((2.4, 5.0), (2.4, 14.6), (15.6, 14.6), (15.6, 6.4), (8.6, 6.4), (7.0, 4.0), (3.4, 4.0), close=True)
        p.drawLine(QPointF(2.6, 8.2), QPointF(15.4, 8.2))
    elif kind == 'scales':            # ميزان العدل: عمود + ذراع + كفّتان
        p.drawLine(QPointF(9.0, 2.6), QPointF(9.0, 15.0))
        p.drawLine(QPointF(5.6, 15.4), QPointF(12.4, 15.4))
        p.drawLine(QPointF(3.2, 5.0), QPointF(14.8, 5.0))
        path((3.2, 5.0), (1.4, 10.0), (5.0, 10.0), close=True)
        path((14.8, 5.0), (13.0, 10.0), (16.6, 10.0), close=True)
    elif kind == 'close':             # إغلاق: خطان متقاطعان
        p.drawLine(QPointF(4.4, 4.4), QPointF(13.6, 13.6))
        p.drawLine(QPointF(13.6, 4.4), QPointF(4.4, 13.6))
    elif kind == 'info':              # معلومة: دائرة + i
        p.drawEllipse(QPointF(9.0, 9.0), 6.8, 6.8)
        p.drawLine(QPointF(9.0, 8.4), QPointF(9.0, 12.6))
        dot(9.0, 5.8, 1.0)
    elif kind == 'dot':               # نقطة ممتلئة (مقدّم الحافظة، حالة الاتصال)
        dot(9.0, 9.0, 4.6)
    elif kind.startswith('spinner'):  # تحميل: قوس ثلاثة أرباع؛ spinner:<زاوية> يدوّره
        ang = int(kind.split(':')[1]) if ':' in kind else 0
        p.save()
        p.translate(9.0, 9.0)
        p.rotate(ang)
        p.translate(-9.0, -9.0)
        pen.setWidthF(2.0)
        p.setPen(pen)
        p.drawArc(QRectF(3.2, 3.2, 11.6, 11.6), 0, 270 * 16)
        p.restore()
    else:
        dot(9.0, 9.0, 2.0)


def _dpr():
    """دقة الشاشة الفعلية (2 كحد أدنى) — حتى تبقى الأيقونات حادّة على 4K بمقياس 250–300%"""
    import math
    from PyQt6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    scr = app.primaryScreen() if app is not None else None
    return max(2, math.ceil(scr.devicePixelRatio())) if scr is not None else 2


def pixmap(kind, color=th.NAVY, size=18):
    """أيقونة كصورة (لـ QLabel) — بدقة الشاشة"""
    r = _dpr()
    pm = QPixmap(size * r, size * r)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(size * r / 18.0, size * r / 18.0)
    _draw(p, kind, color)
    p.end()
    pm.setDevicePixelRatio(r)
    return pm


def icon(kind, color=th.NAVY, active=None, size=18):
    """أيقونة لزر أو عنصر قائمة: لون عادي، ولون مرور/تحديد اختياري"""
    ic = QIcon()
    ic.addPixmap(pixmap(kind, color, size), QIcon.Mode.Normal)
    act = active or color
    ic.addPixmap(pixmap(kind, act, size), QIcon.Mode.Active)
    ic.addPixmap(pixmap(kind, act, size), QIcon.Mode.Selected)
    ic.addPixmap(pixmap(kind, th.TEXT_MUTED, size), QIcon.Mode.Disabled)
    return ic
