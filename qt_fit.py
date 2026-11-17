# ===== qt_fit.py — ضبط مقاسات النوافذ على حجم الشاشة (مع زوم ويندوز) =====
"""
المشكلة (المبلَّغ 17/11/2026): شاشة «طلب إعلان» كانت بحجم ثابت (1120×780)
وحدّ أدنى 840×560. على جهاز فيه **زوم ويندوز** (125%/150%/175%) المقاس
**المنطقي** للشاشة يصغر — مثلاً 1366×768 تصير 911×512 بـ150% — فتصير النافذة
أكبر من الشاشة، ويطلع زر «إرسال الإعلان» (Far يسار الشريط السفلي) **برا
الشاشة**.

سبب أعمق (مقاس): حتى لو نادينا resize()، التخطيط (QLayout) يفرض **حدّه
الأدنى** على النافذة — والنافذة تصير 2422px عرضاً (أكبر من أي شاشة) وتطلع
الأزرار براها. الحل: نرخي قيد التخطيط (SetNoConstraint) ونحدّد مقاس النافذة
على الشاشة، ونخلي العناصر المطاطية (نص الحالة) تنكمش.

هنا وحدة واحدة تستعملها كل النوافذ:
  • available_geometry() — منطقة الشاشة المتاحة (بعد الزوم، من غير شريط المهام)
  • fit_size()          — المقاس الملائم للشاشة (مقرّب)
  • apply_fit()         — يطبّق المقاس + الحدّ الأدنى + التوسيط + يرخّي التخطيط
  • clamp_to_screen()   — نافذة على محتواها ثم مقصوصة على الشاشة (حوارات قصيرة)
  • keep_on_screen()    — لو النافذة خرجت برا الشاشة (تغيّر الزوم أثناء التشغيل)

⚠️ كل المقاسات **منطقية** (Qt بيقيسها بعد الزوم) — ما نضرب أرقام الشاشة
   متسلسلة. المقاسات الثابتة بالتصميم (1120×780) تبقى كما هي على الشاشة
   الكبيرة، وتتصغّر تلقائياً على الصغيرة.
"""
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QLayout

#: هامش بين حافة النافذة وحافة الشاشة (بالبكسل المنطقي)
MARGIN = 16
#: أقل مقاس نعطيه لنافذة (ما نخليها بلا فايدة)
MIN_W = 320
MIN_H = 240
#: مقاس احتياطي لو ما لقينا شاشة (بيئة بلا واجهة)
FALLBACK = QRect(0, 0, 1920, 1080)


def available_geometry(widget=None):
    """
    منطقة الشاشة المتاحة (من غير شريط المهام) — بمقاس **منطقي** بعد الزوم.

    يختار شاشة النافذة نفسها (شاشات متعددة)، وإلا الشاشة الأساسية.
    """
    screen = None
    try:
        if widget is not None:
            screen = widget.screen()
    except Exception:
        screen = None
    if screen is None:
        try:
            screen = QGuiApplication.primaryScreen()
        except Exception:
            screen = None
    if screen is None:
        return QRect(FALLBACK)
    try:
        geo = screen.availableGeometry()
    except Exception:
        return QRect(FALLBACK)
    if geo is None or geo.width() <= 0 or geo.height() <= 0:
        return QRect(FALLBACK)
    return geo


def fit_size(widget=None, prefer=(1024, 768), minimum=(0, 0), margin=MARGIN):
    """
    يرجّع (العرض, الارتفاع) الملائمين للشاشة.

    - prefer  : المقاس المطلوب (يتقصّ إذا ما fit على الشاشة)
    - minimum : الحدّ الأدنى المطلوب (يتقصّ هو بعد — ما نخلي النافذة
                تتجاوز الشاشة أبداً)
    """
    geo = available_geometry(widget)
    avail_w = max(MIN_W, geo.width() - 2 * int(margin))
    avail_h = max(MIN_H, geo.height() - 2 * int(margin))
    try:
        pw, ph = int(prefer[0]), int(prefer[1])
    except Exception:
        pw, ph = avail_w, avail_h
    try:
        mw, mh = int(minimum[0]), int(minimum[1])
    except Exception:
        mw, mh = 0, 0
    w = min(pw if pw > 0 else avail_w, avail_w)
    h = min(ph if ph > 0 else avail_h, avail_h)
    w = max(w, min(mw, avail_w))
    h = max(h, min(mh, avail_h))
    return w, h


def apply_fit(widget, prefer=(1024, 768), minimum=(0, 0), margin=MARGIN,
              center=True, ratio=None, relax_layout=True):
    """
    يضبط النافذة على الشاشة: المقاس + الحدّ الأدنى + الموضع (توسيط).

    relax_layout=True ⟵ يرخّي قيد التخطيط (SetNoConstraint) عشان النافذة
    **تتنصّف** مع الشاشة بدل ما يفرض التخطيط حدّه الأدنى (وهو سبب خروج
    الأزرار برا الشاشة). المحتوى القابل للتمرير يبقى داخل QScrollArea.

    ratio=(0.92, 0.88) ⟵ يحدّ المقاس بنسبة من حجم الشاشة (للنافذة الكبيرة).
    يرجّع QRect الهندسة النهائية.
    """
    geo = available_geometry(widget)
    try:
        pw, ph = int(prefer[0]), int(prefer[1])
    except Exception:
        pw, ph = geo.width(), geo.height()
    if ratio:
        try:
            pw = min(pw, int(geo.width() * float(ratio[0])))
            ph = min(ph, int(geo.height() * float(ratio[1])))
        except Exception:
            pass
    w, h = fit_size(widget, (pw, ph), minimum, margin)

    # الحدّ الأدنى: ما يتجاوز الشاشة أبداً (وإلا انزاحت النافذة براها)
    try:
        mw, mh = int(minimum[0]), int(minimum[1])
    except Exception:
        mw, mh = 0, 0
    min_w = max(0, min(mw, geo.width()))
    min_h = max(0, min(mh, geo.height()))

    if relax_layout:
        try:
            lay = widget.layout()
            if lay is not None:
                lay.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        except Exception:
            pass

    try:
        widget.setMinimumSize(min_w, min_h)
    except Exception:
        pass

    if center:
        x = geo.x() + max(0, (geo.width() - w) // 2)
        y = geo.y() + max(0, (geo.height() - h) // 2)
        try:
            widget.setGeometry(x, y, w, h)
        except Exception:
            try:
                widget.resize(w, h)
            except Exception:
                pass
    else:
        try:
            widget.resize(w, h)
        except Exception:
            pass
    try:
        return widget.geometry()
    except Exception:
        return QRect(0, 0, w, h)


def keep_on_screen(widget, margin=8):
    """
    لو النافذة خرجت برا الشاشة (تغيّر الزوم، أو انفصلت الشاشة) — ترجعها
    جوّا الشاشة المتاحة. ما يغيّر المقاس.
    """
    geo = available_geometry(widget)
    try:
        r = widget.geometry()
    except Exception:
        return
    x = min(max(r.x(), geo.x() + margin),
            geo.x() + max(0, geo.width() - r.width() - margin))
    y = min(max(r.y(), geo.y() + margin),
            geo.y() + max(0, geo.height() - r.height() - margin))
    if (x, y) != (r.x(), r.y()):
        try:
            widget.move(x, y)
        except Exception:
            pass


def clamp_to_screen(widget, margin=MARGIN, center=True, relax_layout=True):
    """
    يضبط النافذة على **محتواها** (adjustSize) ثم يقصّ المقاس لو ما fit على
    الشاشة — ويرجّع QRect.

    للاستخدام بالحوارات القصيرة (تأكيد الإرسال): ما نفرض مقاساً ولا نخلي
    النافذة تطلع برا الشاشة.

    relax_layout=True ⟵ يرخّي قيد التخطيط (زي apply_fit) — وإلا فرض حدّه
    الأدنى على النافذة ورجّعها أعرض من الشاشة.
    """
    geo = available_geometry(widget)
    if relax_layout:
        try:
            lay = widget.layout()
            if lay is not None:
                lay.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        except Exception:
            pass
    try:
        widget.adjustSize()
    except Exception:
        pass
    try:
        w = widget.width()
        h = widget.height()
    except Exception:
        return QRect(0, 0, 0, 0)
    avail_w = max(MIN_W, geo.width() - 2 * int(margin))
    avail_h = max(MIN_H, geo.height() - 2 * int(margin))
    w = min(w, avail_w)
    h = min(h, avail_h)
    if center:
        x = geo.x() + max(0, (geo.width() - w) // 2)
        y = geo.y() + max(0, (geo.height() - h) // 2)
    else:
        x, y = widget.x(), widget.y()
    try:
        widget.setGeometry(x, y, w, h)
    except Exception:
        try:
            widget.resize(w, h)
        except Exception:
            pass
    try:
        return widget.geometry()
    except Exception:
        return QRect(x, y, w, h)
