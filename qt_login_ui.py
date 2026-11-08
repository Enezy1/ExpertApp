# ===== qt_login_ui.py — تصميم شاشة الدخول (كحلي + ذهبي، بطاقة زجاجية) =====
# طبقة عرض فقط: main.LoginScreenQt يستدعي build_login_ui ويحتفظ بكل منطق الدخول.
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (QColor, QLinearGradient, QRadialGradient, QPainter, QPen, QBrush,
                         QPolygonF, QFont)
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFrame,
                             QPushButton)

import qt_theme as th

GOLD = "#C9A24B"
GOLD_LIGHT = "#E8CB7E"
GOLD_DARK = "#9C7A2E"
NAVY_DEEP = "#071426"
NAVY_MID = "#0C2140"
TEXT_SOFT = "#A9B8CF"


_BUILDING_CACHE = {}


def _building_pixmap(w, h):
    """مدخل محكمة كلاسيكي (أعمدة + عتبة + درج) يظهر على اليسار ويتلاشى ناحية اليمين."""
    from PyQt6.QtGui import QPixmap
    key = (w, h)
    if key in _BUILDING_CACHE:
        return _BUILDING_CACHE[key]
    bw = int(w * 0.50)
    pm = QPixmap(bw, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    top = 96                      # أعلى العتبة (entablature)
    bottom = int(h * 0.80)        # أرضية الأعمدة
    col_w, gap = 44, 30
    x0 = -14
    xs = [x0 + i * (col_w + gap) for i in range(5)]

    def stone(x, wid, alpha):
        g = QLinearGradient(x, 0, x + wid, 0)
        g.setColorAt(0.0, QColor(185, 210, 245, alpha))
        g.setColorAt(0.45, QColor(110, 145, 200, int(alpha * 0.8)))
        g.setColorAt(1.0, QColor(35, 60, 105, int(alpha * 0.6)))
        return g

    # العتبة العلوية + الجملون
    p.fillRect(QRectF(-10, top, bw + 20, 26), QBrush(stone(-10, bw, 120)))
    p.fillRect(QRectF(-10, top + 26, bw + 20, 10), QColor(60, 90, 140, 90))
    p.setPen(Qt.PenStyle.NoPen)

    # الأعمدة
    for x in xs:
        shaft_top, shaft_bot = top + 36, bottom - 26
        # تاج العمود
        p.fillRect(QRectF(x - 6, shaft_top, col_w + 12, 14), QBrush(stone(x - 6, col_w + 12, 130)))
        # الجذع
        p.fillRect(QRectF(x, shaft_top + 14, col_w, shaft_bot - shaft_top - 14), QBrush(stone(x, col_w, 115)))
        # تخاديد
        p.setPen(QPen(QColor(10, 25, 55, 90), 1.2))
        for k in range(1, 5):
            fx = x + k * col_w / 5
            p.drawLine(QPointF(fx, shaft_top + 18), QPointF(fx, shaft_bot - 2))
        p.setPen(Qt.PenStyle.NoPen)
        # قاعدة العمود
        p.fillRect(QRectF(x - 6, shaft_bot, col_w + 12, 12), QBrush(stone(x - 6, col_w + 12, 130)))
        p.fillRect(QRectF(x - 10, shaft_bot + 12, col_w + 20, 14), QBrush(stone(x - 10, col_w + 20, 120)))

    # الدرج
    for i in range(4):
        y = bottom + i * 12
        p.fillRect(QRectF(-10, y, bw + 20 - i * 0, 12), QBrush(stone(-10, bw, 95 - i * 14)))
        p.setPen(QPen(QColor(200, 220, 255, 40), 1))
        p.drawLine(QPointF(-10, y), QPointF(bw + 10, y))
        p.setPen(Qt.PenStyle.NoPen)

    # قناع التلاشي: ظاهر على اليسار ويختفي يمينًا وأسفلًا
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    mask = QLinearGradient(0, 0, bw, 0)
    mask.setColorAt(0.0, QColor(0, 0, 0, 255))
    mask.setColorAt(0.55, QColor(0, 0, 0, 170))
    mask.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(0, 0, bw, h, mask)
    vmask = QLinearGradient(0, bottom - 20, 0, bottom + 90)
    vmask.setColorAt(0.0, QColor(0, 0, 0, 255))
    vmask.setColorAt(1.0, QColor(0, 0, 0, 40))
    p.fillRect(0, int(bottom - 20), bw, h, vmask)
    p.end()
    _BUILDING_CACHE[key] = pm
    return pm


def _gold_path(w, h):
    from PyQt6.QtGui import QPainterPath
    path = QPainterPath(QPointF(w * 0.68, 66))
    path.lineTo(QPointF(w - 5, h * 0.19))
    path.lineTo(QPointF(w - 5, h * 0.43))
    return path


def paint_login_background(widget, event=None):
    """خلفية كحلية + مدخل محكمة على اليسار + خطوط ذهبية لامعة (مع وميض متحرك)."""
    p = QPainter(widget)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = widget.width(), widget.height()

    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0.0, QColor(NAVY_MID))
    g.setColorAt(0.55, QColor(NAVY_DEEP))
    g.setColorAt(1.0, QColor("#050E1C"))
    p.fillRect(0, 0, w, h, g)

    glow = QRadialGradient(QPointF(w / 2, h * 0.2), w * 0.6)
    glow.setColorAt(0.0, QColor(40, 90, 170, 90))
    glow.setColorAt(1.0, QColor(40, 90, 170, 0))
    p.fillRect(0, 0, w, h, glow)
    glow2 = QRadialGradient(QPointF(w * 0.2, h * 0.95), w * 0.7)
    glow2.setColorAt(0.0, QColor(201, 162, 75, 38))
    glow2.setColorAt(1.0, QColor(201, 162, 75, 0))
    p.fillRect(0, 0, w, h, glow2)

    # مدخل المحكمة
    p.setOpacity(0.62)
    p.drawPixmap(0, 0, _building_pixmap(w, h))
    p.setOpacity(1.0)

    # الخط الذهبي اللامع
    path = _gold_path(w, h)
    # توهج خارجي
    for width, alpha in ((14, 18), (8, 34), (4, 60)):
        p.setPen(QPen(QColor(232, 203, 126, alpha), width, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
    # الخط الأساسي بتدرج ذهبي
    lg = QLinearGradient(w * 0.68, 66, w, h * 0.43)
    lg.setColorAt(0.0, QColor(GOLD_DARK))
    lg.setColorAt(0.35, QColor("#FFE9A8"))
    lg.setColorAt(0.65, QColor(GOLD))
    lg.setColorAt(1.0, QColor("#F6DC93"))
    p.setPen(QPen(QBrush(lg), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)
    # خط ثانٍ رفيع موازٍ
    p.setPen(QPen(QColor(232, 203, 126, 90), 1.0))
    p.drawLine(QPointF(w * 0.72, 66), QPointF(w - 15, h * 0.185))

    # وميض يمشي على الخط
    phase = getattr(widget, '_shine_phase', 0.0)
    pt = path.pointAtPercent(phase)
    sg = QRadialGradient(pt, 34)
    sg.setColorAt(0.0, QColor(255, 244, 205, 235))
    sg.setColorAt(0.25, QColor(255, 226, 150, 130))
    sg.setColorAt(1.0, QColor(255, 226, 150, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(sg))
    p.drawEllipse(pt, 34, 34)
    p.setBrush(QColor(255, 250, 230))
    p.drawEllipse(pt, 2.6, 2.6)
    # إطار ذهبي رفيع حول النافذة (بدل إطار ويندوز)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(201, 162, 75, 120), 1.2))
    p.drawRect(QRectF(0.6, 0.6, w - 1.2, h - 1.2))
    p.setPen(Qt.PenStyle.NoPen)
    # بريق ثابت عند الزاوية
    corner = QPointF(w - 5, h * 0.19)
    cg = QRadialGradient(corner, 16)
    cg.setColorAt(0.0, QColor(255, 235, 175, 200))
    cg.setColorAt(1.0, QColor(255, 235, 175, 0))
    p.setBrush(QBrush(cg))
    p.drawEllipse(corner, 16, 16)
    p.end()


def start_shine(widget):
    """يحرّك الوميض على الخط الذهبي (يعيد رسم زاوية الشاشة فقط)."""
    from PyQt6.QtCore import QTimer, QRect
    widget._shine_phase = 0.0
    t = QTimer(widget)

    def tick():
        widget._shine_phase = (widget._shine_phase + 0.012) % 1.0
        w, h = widget.width(), widget.height()
        widget.update(QRect(int(w * 0.62), 20, int(w * 0.38) + 2, int(h * 0.46)))
    t.timeout.connect(tick)
    t.start(40)
    widget._shine_timer = t


class TitleBar(QWidget):
    """شريط عنوان كحلي/ذهبي بدل شريط ويندوز: عنوان + تصغير + إغلاق، وسحب النافذة."""
    HEIGHT = 46

    def __init__(self, screen, title):
        super().__init__(screen)
        self._screen = screen
        self.setFixedHeight(self.HEIGHT)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(8)

        icon = QLabel()
        try:
            ic = screen.windowIcon()
            if not ic.isNull():
                icon.setPixmap(ic.pixmap(22, 22))
        except Exception:
            pass
        icon.setStyleSheet("background:transparent; border:none;")
        lay.addWidget(icon)
        t = QLabel(title)
        t.setStyleSheet(f"color:{GOLD_LIGHT}; font-size:13px; font-weight:700;"
                        " background:transparent; border:none;")
        lay.addWidget(t)
        lay.addStretch()

        def mk(text, hover_bg, hover_fg="white"):
            b = QPushButton(text)
            b.setFixedSize(40, 32)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{ background:transparent; color:{TEXT_SOFT}; border:none;
                    border-radius:8px; font-size:15px; }}
                QPushButton:hover {{ background:{hover_bg}; color:{hover_fg}; }}
            """)
            return b
        mini = mk("—", "rgba(201,162,75,0.22)", GOLD_LIGHT)
        close = mk("✕", "#C0392B")
        mini.clicked.connect(screen.showMinimized)
        close.clicked.connect(screen.close)
        lay.addWidget(mini)
        lay.addWidget(close)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            h = self._screen.windowHandle()
            if h is not None:
                h.startSystemMove()
        super().mousePressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QPen(QColor(201, 162, 75, 55), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()



class GradientLabel(QLabel):
    """نص بتدرج ذهبي (العنوان)."""
    def __init__(self, text, size=30, parent=None):
        super().__init__(text, parent)
        self._size = size
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(int(size * 1.9))
        self.setStyleSheet("background:transparent; border:none;")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(th.FONT_FAMILY)
        f.setPixelSize(self._size)
        f.setBold(True)
        p.setFont(f)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, QColor(GOLD_LIGHT))
        g.setColorAt(1.0, QColor(GOLD))
        p.setPen(QPen(QBrush(g), 1))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


class _Field(QFrame):
    """حقل إدخال بأيقونة، يتوهج بالذهبي عند التركيز."""
    def __init__(self, icon_text, placeholder, password=False, parent=None):
        super().__init__(parent)
        self.setObjectName("loginField")
        self.setFixedHeight(54)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(10)

        icon = QLabel(icon_text)
        icon.setStyleSheet(f"color:{TEXT_SOFT}; font-size:17px; background:transparent; border:none;")
        icon.setFixedWidth(26)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        if password:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit.setStyleSheet(f"""
            QLineEdit {{ background:transparent; border:none; color:white;
                font-size:15px; selection-background-color:{GOLD_DARK}; }}
            QLineEdit::placeholder {{ color:{TEXT_SOFT}; }}
        """)
        self.edit.installEventFilter(self)
        lay.addWidget(icon)
        lay.addWidget(self.edit, 1)
        self._set_focus_style(False)

    def _set_focus_style(self, on):
        border = GOLD if on else "rgba(201,162,75,0.35)"
        self.setStyleSheet(f"""
            QFrame#loginField {{ background:rgba(4,12,26,0.65); border:1px solid {border};
                border-radius:14px; }}
        """)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self.edit:
            if event.type() == QEvent.Type.FocusIn:
                self._set_focus_style(True)
            elif event.type() == QEvent.Type.FocusOut:
                self._set_focus_style(False)
        return super().eventFilter(obj, event)


def _lbl(text, size, color, bold=False, align=Qt.AlignmentFlag.AlignCenter):
    l = QLabel(text)
    l.setAlignment(align)
    l.setStyleSheet(f"color:{color}; font-size:{size}px; font-weight:{700 if bold else 400};"
                    " background:transparent; border:none;")
    return l


def build_login_ui(screen, creds, other_accounts):
    """يبني عناصر الشاشة على الكائن screen ويضبط أسماء الحقول التي يعتمد عليها منطق الدخول:
    username_entry / password_entry / status_lbl / spinner / retry_btn / _switch_account."""
    start_shine(screen)
    screen._title_bar = TitleBar(screen, screen.windowTitle())
    screen._title_bar.setGeometry(0, 0, screen.width(), TitleBar.HEIGHT)
    screen._title_bar.raise_()
    outer = QVBoxLayout(screen)
    outer.setContentsMargins(40, TitleBar.HEIGHT + 22, 40, 22)
    outer.setSpacing(0)

    # --- الشعار ---
    logo = QLabel()
    pm = None
    try:
        from qt_shell_v2 import load_app_icon
        icon = load_app_icon()
        pm = icon.pixmap(96, 96) if not icon.isNull() else None
    except Exception:
        pm = None
    if pm and not pm.isNull():
        logo.setPixmap(pm)
    else:
        logo.setText("⚖")
        logo.setStyleSheet(f"color:{GOLD}; font-size:60px; background:transparent; border:none;")
    logo.setFixedSize(96, 96)
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if pm:
        logo.setStyleSheet("background:transparent; border:none;")
    outer.addWidget(logo, 0, Qt.AlignmentFlag.AlignCenter)
    outer.addSpacing(12)

    outer.addWidget(GradientLabel("نظام جلسات الخبراء", 32))
    outer.addWidget(_lbl("الإدارة العامة للخبراء — وزارة العدل", 14, TEXT_SOFT))
    outer.addSpacing(10)

    # فاصل بالمعين الذهبي
    div = QHBoxLayout()
    div.setSpacing(8)
    for i in range(3):
        if i == 1:
            d = QLabel("◆")
            d.setStyleSheet(f"color:{GOLD}; font-size:10px; background:transparent; border:none;")
            div.addWidget(d)
        else:
            line = QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet(f"background:{GOLD_DARK}; border:none;")
            div.addWidget(line, 1)
    outer.addLayout(div)
    outer.addSpacing(8)
    outer.addWidget(_lbl("خبرة .. للعدالة منصة", 15, "#7F93B0"))
    outer.addSpacing(18)

    # --- البطاقة الزجاجية ---
    card = QFrame()
    card.setObjectName("loginCard")
    card.setStyleSheet(f"""
        QFrame#loginCard {{ background:rgba(255,255,255,0.045);
            border:1px solid rgba(201,162,75,0.55); border-radius:26px; }}
    """)
    c = QVBoxLayout(card)
    c.setContentsMargins(30, 24, 30, 24)
    c.setSpacing(0)

    if other_accounts:
        c.addWidget(_lbl("تبديل سريع لحساب محفوظ:", 12, TEXT_SOFT, align=Qt.AlignmentFlag.AlignRight))
        c.addSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        for uname in other_accounts[:4]:
            btn = QPushButton(uname)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{ background:rgba(4,12,26,0.65); color:{GOLD_LIGHT};
                    border:1px solid rgba(201,162,75,0.5); border-radius:15px;
                    padding:6px 16px; font-size:12px; }}
                QPushButton:hover {{ border:1px solid {GOLD}; color:white; }}
            """)
            btn.clicked.connect(lambda checked=False, u=uname: screen._switch_account(u))
            row.addWidget(btn)
        c.addLayout(row)
        c.addSpacing(16)

    c.addWidget(_lbl("اسم المستخدم", 13, TEXT_SOFT, align=Qt.AlignmentFlag.AlignRight))
    c.addSpacing(6)
    uf = _Field("👤", "أدخل اسم المستخدم")
    screen.username_entry = uf.edit
    if creds.get('username'):
        uf.edit.setText(creds['username'])
    c.addWidget(uf)
    c.addSpacing(14)

    c.addWidget(_lbl("كلمة المرور", 13, TEXT_SOFT, align=Qt.AlignmentFlag.AlignRight))
    c.addSpacing(6)
    pf = _Field("🔒", "أدخل كلمة المرور", password=True)
    screen.password_entry = pf.edit
    if creds.get('password'):
        pf.edit.setText(creds['password'])
    pf.edit.returnPressed.connect(screen._try_connect)
    c.addWidget(pf)
    c.addSpacing(14)

    screen.status_lbl = _lbl("", 12, TEXT_SOFT)
    c.addWidget(screen.status_lbl)
    screen.spinner = _lbl("◐", 22, GOLD)
    c.addWidget(screen.spinner)
    c.addSpacing(8)

    btn = QPushButton("🔐  تسجيل الدخول")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedHeight(54)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {GOLD_LIGHT}, stop:1 {GOLD});
            color:#1B1305; border:none; border-radius:14px; font-size:16px; font-weight:700; }}
        QPushButton:hover {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #F3DA94, stop:1 {GOLD_LIGHT}); }}
        QPushButton:pressed {{ background:{GOLD_DARK}; }}
        QPushButton:disabled {{ background:#4A4331; color:#9A927C; }}
    """)
    btn.clicked.connect(screen._try_connect)
    screen.retry_btn = btn
    c.addWidget(btn)

    card_row = QHBoxLayout()
    card_row.addStretch()
    card.setFixedWidth(430)
    card_row.addWidget(card)
    card_row.addStretch()
    outer.addLayout(card_row)
    outer.addStretch()

    # --- التذييل ---
    foot = QHBoxLayout()
    safe = _lbl("🛡  بيئة آمنة ومحمية", 12, TEXT_SOFT, align=Qt.AlignmentFlag.AlignLeft)
    moj = _lbl("وزارة العدل", 13, TEXT_SOFT, align=Qt.AlignmentFlag.AlignRight)
    foot.addWidget(moj)
    foot.addStretch()
    foot.addWidget(safe)
    outer.addLayout(foot)
