# ===== qt_extraction.py — استخراج بيانات القضية بالخلفية (نسخة PyQt6) =====
"""
بديل الدائرة اللي كانت تعلّق البرنامج وقت طلب بيانات القضية من الذكاء
الاصطناعي (تفاصيل القضية / محضر أول جلسة / محضر).

- السحب من الملف الآلي + Gemini يشتغلون بـthread منفصل. الـthread ما
  يلمس أي عنصر واجهة: يرسل signals لـQObject يعيش بالـmain thread (Qt
  يحوّلها تلقائيًا لـqueued connection = آمنة بين الـthreads).
- الحفظ بالقاعدة (case_db.save_case) والرسائل تتم بالـmain thread فقط،
  بنفس منطق _finalize_fetch الموجود بـcase_info_window.py.
- نافذة تقدم داكنة بالمراحل الخمس + حركة بسيطة مرسومة بـQPainter.
- زر "تصغير" يخلي العملية تكمل بالخلفية، وأكثر من قضية بنفس الوقت
  (dict مفتاحه رقم القضية). أول ما تخلص يطلع Toast بزاوية الشاشة.
"""
import math
import time
import threading
import traceback

from PyQt6.QtCore import (Qt, QObject, QEvent, QTimer, QPropertyAnimation, QEasingCurve, QRectF, QPointF,
                          QPoint, pyqtSignal)
from PyQt6.QtGui import QPainter, QColor, QPen, QPolygonF, QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGraphicsDropShadowEffect
)

import qt_theme as th
import qt_motion as mo

from extraction_tasks import STAGES, PENDING, IN_PROGRESS, DONE, ERROR, SKIPPED, Cancelled


FRAME_MS = 16


# ============================================================
# المهمة + المدير
# ============================================================

from ai_providers import UserCancelled as _UserCancelled, set_cancel_event


class _Bridge(QObject):
    """يعيش بالـmain thread — الـworker يبعث عليه signals بس"""
    stage = pyqtSignal(int, str, str)
    finished = pyqtSignal(object, object)
    cancelled = pyqtSignal()


class QtExtractionTask(QObject):
    stage_changed = pyqtSignal()
    done = pyqtSignal()          # يُبعث بعد finalize (بالـmain thread)

    def __init__(self, key, caso_no, worker, finalize):
        super().__init__()
        self.key = key
        self.caso_no = caso_no
        self._worker = worker
        self._finalize = finalize
        self.cancel_event = threading.Event()
        self.stages = [PENDING] * len(STAGES)
        self.notes = [""] * len(STAGES)
        self.state = "running"
        self.result = None
        self.error = None
        self.summary = ""
        self.success = False
        self.minimized = False
        self.window = None
        self.on_toast_open = None    # callable() — زر "فتح القضية" بالـToast

        self._bridge = _Bridge()
        self._bridge.stage.connect(self._on_stage)
        self._bridge.finished.connect(self._on_finished)
        self._bridge.cancelled.connect(self._on_cancelled)

    # ---------- داخل الـworker thread ----------
    def progress(self, index, state, note=""):
        if self.cancel_event.is_set():
            raise Cancelled()
        self._bridge.stage.emit(index, state, note or "")

    def _run(self):
        set_cancel_event(self.cancel_event)   # مزود المتصفح يتوقف بإلغاء هذه المهمة فقط
        try:
            result, error = self._worker(self.progress)
            if not self.cancel_event.is_set():
                self._bridge.finished.emit(result, error)
        except (Cancelled, _UserCancelled):
            self._bridge.cancelled.emit()
        except Exception as e:
            traceback.print_exc()
            self._bridge.finished.emit(None, str(e))

    def start(self):
        threading.Thread(target=self._run, daemon=True,
                         name=f"extract-{self.caso_no}").start()

    # ---------- main thread ----------
    def cancel(self):
        if self.state == "running":
            self.cancel_event.set()
            self.state = "cancelled"
            _MANAGER._remove(self)

    def _set(self, i, st, note=""):
        self.stages[i] = st
        self.notes[i] = note
        self.stage_changed.emit()

    def _on_stage(self, i, st, note):
        if self.state == "running":
            self._set(i, st, note)

    def _on_cancelled(self):
        if self.state == "running":
            self.state = "cancelled"
            _MANAGER._remove(self)

    def _on_finished(self, result, error):
        if self.state != "running":
            return  # ملغاة — النتيجة تنتجاهل
        self.result, self.error = result, error
        for i, st in enumerate(self.stages[:-1]):
            if st == IN_PROGRESS:
                self._set(i, ERROR if error else DONE, self.notes[i])
            elif st == PENDING:
                self._set(i, SKIPPED)
        self._set(4, IN_PROGRESS)
        final = DONE
        try:
            self._finalize(self)
        except Exception as e:
            traceback.print_exc()
            self.error = self.error or str(e)
            self.summary = f"❌ {e}"
            self.success = False
            final = ERROR
        self._set(4, final, self.summary)
        self.state = "finished"
        _MANAGER._remove(self)
        self.done.emit()
        if self.minimized:
            show_task_toast(self)


class _QtTaskManager:
    def __init__(self):
        self.tasks = {}

    def start(self, key, caso_no, worker, finalize):
        t = self.tasks.get(key)
        if t and t.state == "running":
            return t, False
        t = QtExtractionTask(key, caso_no, worker, finalize)
        self.tasks[key] = t
        t.start()
        return t, True

    def _remove(self, task):
        if self.tasks.get(task.key) is task:
            del self.tasks[task.key]
        # نخلي مرجع للمهمة لين تخلص الـToast (ما تنحذف من الذاكرة قبل)
        _FINISHED.append(task)
        del _FINISHED[:-20]


_MANAGER = _QtTaskManager()
_FINISHED = []


def task_manager():
    return _MANAGER


# ============================================================
# «مكتب الخبير» — نافذة الاستخراج كورقة حكم على المكتب
# ============================================================
# الفكرة: حكم الإحالة ورقة بيضاء على ورق المكتب الدافئ. سطورها تنكتب
# بالحبر مع كل مرحلة تخلص، ومسطرة قراءة كحلية تمشي عليها وقت الشغل.
# المراحل دفتر يومية: خط زمني كحلي، وكل مرحلة تخلص ينختم عليها ختم
# زمردي. لحظة الحركة الوحيدة المقصودة: ختم «تم» ينطبع على الورقة.
# كل الألوان من qt_theme — الزمردي/الكهرماني/القرمزي للحالة فقط.

def _font(size, weight=th.W_REGULAR):
    f = QFont(th.FONT_FAMILY)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    return f


def _q(hex_or_rgba, alpha=None):
    c = QColor(hex_or_rgba)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def _ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _seconds_ar(n):
    """قاعدة العدّ العربي بنظام التصميم: ثانية واحدة / ثانيتان / 3–10 ثوانٍ / 11+ ثانية"""
    if n <= 1:
        return "ثانية واحدة"
    if n == 2:
        return "ثانيتان"
    if n <= 10:
        return f"{n} ثوانٍ"
    if n < 60:
        return f"{n} ثانية"
    m = n // 60
    return "دقيقة واحدة" if m == 1 else ("دقيقتان" if m == 2 else f"{m} دقائق")


SLOW_AFTER_S = 20


def _has_arabic(text):
    return any('؀' <= ch <= 'ۿ' for ch in text)


def _bidi_tail(text):
    """«سبب عربي: رسالة خطأ لاتينية» — يعزل الذيل اللاتيني عشان ما ينعكس ترتيبه"""
    if ': ' in text:
        head, tail = text.split(': ', 1)
        if not _has_arabic(tail):
            return f"{head}: ⁦{tail}⁩"
    return text


def _count_ar(n, one, two, few, many):
    if n == 1:
        return one
    if n == 2:
        return two
    if 3 <= n <= 10:
        return f"{n} {few}"
    return f"{n} {many}"


def case_facts(result):
    """خلاصة قصيرة من البيانات المستخرجة فعليًا — بدون أي رقم مخترع"""
    if not isinstance(result, dict):
        return ""
    parts = []
    num = (result.get('court_case_number') or '').strip()
    if num:
        parts.append(f"رقم الدعوى ⁨{num}⁩")   # FSI: الرقم ممكن يخلط عربي ولاتيني
    pl = len(result.get('plaintiffs') or [])
    df = len(result.get('defendants') or [])
    if pl:
        parts.append(_count_ar(pl, "مدعٍ واحد", "مدعيان", "مدعين", "مدعيًا"))
    if df:
        parts.append(_count_ar(df, "مدعى عليه واحد", "مدعى عليهما", "مدعى عليهم", "مدعى عليهم"))
    hd = (result.get('hearing_date') or '').strip()
    if hd:
        parts.append(f"حضور الخصوم {th.ltr(hd)}")
    return "  ·  ".join(parts)   # بعدها نقول بصراحة إن الشبكة بطيئة ونقترح المتابعة بالخلفية


class _JudgmentSheet(QWidget):
    """
    سطح المكتب (لوح كحلي باهت) وفوقه ورقة حكم الإحالة لهذي القضية بالذات:
    ترويستها تحمل رقم القضية، سطورها تنكتب بالحبر مع كل مرحلة، ومسطرة
    القراءة الكحلية تمشي على السطر الجاري. في النهاية ينطبع الختم: ضغطة
    على الورقة + حلقة حبر تنتشر وتتلاشى — لحظة الحركة الوحيدة المقصودة.
    """
    LINES = 10
    W, H = 264, 452

    def __init__(self, caso_no=""):
        super().__init__()
        self.setFixedSize(self.W, self.H)
        self.caso_no = caso_no
        self.inked = 0.0
        self.target = 0.0
        self.reading = True
        self.t = 0.0
        self.seal = None
        self.seal_age = -1.0      # ثواني منذ بدء انطباع الختم
        self.motion = mo.motion_enabled()
        self.caption = ""

    def stamp(self, text, color):
        self.seal = (text, color)
        self.seal_age = 0.0 if self.motion else 2.0

    def step(self, dt):
        self.t += dt
        if self.motion:
            self.inked += (self.target - self.inked) * min(1.0, dt * 4.0)
        else:
            self.inked = self.target
        if self.seal is not None and self.seal_age < 2.0:
            self.seal_age += dt
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # سطح المكتب: كحلي المحكمة كامل — نفس عمود الشريط الجانبي بالبرنامج،
        # على طول حافة النافذة. الورقة البيضاء فوقه هي البؤرة الوحيدة.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_q(th.NAVY))
        p.drawRect(QRectF(0, 0, self.W, self.H))

        # ضغطة الختم: الورقة تنزل 2px لحظة الانطباع وترجع
        press = 0.0
        if self.seal is not None and self.motion and 0.18 < self.seal_age < 0.42:
            press = math.sin((self.seal_age - 0.18) / 0.24 * math.pi) * 2.0
        sw, sh = 196, 272
        sheet = QRectF((self.W - sw) / 2, (self.H - sh) / 2 - 16 + press, sw, sh)

        for i, a in enumerate((6, 5, 4, 3, 2)):
            g = 2 + i * 3
            p.setBrush(_q(th.NAVY_PRESSED, a * 14))
            p.drawRoundedRect(sheet.adjusted(-g / 2, 7 - g / 3 - press, g / 2, 7 + g / 2 - press),
                              6 + g / 2, 6 + g / 2)
        p.setBrush(_q(th.SURFACE))
        p.setPen(QPen(_q(th.BORDER), 1))
        p.drawRoundedRect(sheet, 6, 6)

        # الترويسة: «حكم إحالة» بالكحلي يمينًا، ورقم القضية بالحبر يسارًا
        x0, x1 = sheet.left() + 16, sheet.right() - 16
        p.setPen(_q(th.NAVY))
        p.setFont(_font(th.FS_CAPTION, th.W_BOLD))
        p.drawText(QRectF(x0, sheet.top() + 14, x1 - x0, 16), th.ARIGHT | Qt.AlignmentFlag.AlignVCenter, "حكم إحالة")
        p.setPen(_q(th.TEXT_SECONDARY))
        p.setFont(_font(10, th.W_MEDIUM))
        p.drawText(QRectF(x0, sheet.top() + 14, x1 - x0, 16), th.ALEFT | Qt.AlignmentFlag.AlignVCenter, self.caso_no)
        p.setPen(QPen(_q(th.NAVY), 2))
        p.drawLine(QPointF(x0, sheet.top() + 38), QPointF(x1, sheet.top() + 38))
        p.setPen(QPen(_q(th.BORDER), 1))
        p.drawLine(QPointF(x0, sheet.top() + 41), QPointF(x1, sheet.top() + 41))

        # السطور: شبح ورقي، وحبر يزحف من اليمين لليسار (اتجاه الكتابة العربية)
        p.setPen(Qt.PenStyle.NoPen)
        top = sheet.top() + 56
        gap = 15.5
        widths = (1.0, 0.9, 1.0, 0.74, 1.0, 0.95, 0.58, 1.0, 0.86, 0.5)
        full_w = x1 - x0
        for k in range(self.LINES):
            y = top + k * gap
            w = full_w * widths[k]
            p.setBrush(_q(th.BORDER_SOFT))
            p.drawRoundedRect(QRectF(x1 - w, y, w, 3.6), 1.8, 1.8)
            ink = max(0.0, min(1.0, self.inked - k))
            if ink > 0:
                p.setBrush(_q(th.TEXT_SECONDARY, 170))
                p.drawRoundedRect(QRectF(x1 - w * ink, y, w * ink, 3.6), 1.8, 1.8)

        # مسطرة القراءة
        if self.reading and self.seal is None:
            cur = min(self.LINES - 1, int(self.inked))
            wob = (math.sin(self.t * 2.2) + 1) / 2 if self.motion else 0
            y = top + cur * gap - 5 + wob * 1.5
            p.setBrush(_q(th.NAVY, 20))
            p.drawRoundedRect(QRectF(sheet.left() + 7, y, sheet.width() - 14, 13), 3, 3)
            p.setBrush(_q(th.NAVY))
            p.drawRoundedRect(QRectF(sheet.left() + 7, y + 13, sheet.width() - 14, 2), 1, 1)

        # الختم
        if self.seal is not None:
            text, col = self.seal
            a = self.seal_age
            e = _ease_out(a / 0.32)
            cx, cy = sheet.left() + 50, sheet.bottom() - 46
            # حلقة الحبر: تنتشر من نقطة الانطباع وتتلاشى
            if self.motion and 0.2 < a < 1.1:
                k = (a - 0.2) / 0.9
                r = 34 + k * 30
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(_q(col, int(90 * (1 - k))), 2))
                p.drawEllipse(QPointF(cx, cy), r, r)
            p.save()
            p.translate(cx, cy)
            p.rotate(-12)
            s = 1.0 + (1 - e) * 0.5
            p.scale(s, s)
            p.setOpacity(min(1.0, e * 1.2))
            p.setBrush(_q(th.SURFACE, 225))
            p.setPen(QPen(_q(col), 2.6))
            p.drawEllipse(QPointF(0, 0), 33, 33)
            p.setPen(QPen(_q(col), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0, 0), 27.5, 27.5)
            p.setPen(_q(col))
            p.setFont(_font(18 if len(text) <= 2 else 14, th.W_HEAVY))
            p.drawText(QRectF(-30, -14, 60, 28), Qt.AlignmentFlag.AlignCenter, text)
            p.restore()

        # تحت الورقة: سطر صغير يقول وين وصلنا — بألوان النص على الكحلي
        col_cap = th.SIDEBAR_TEXT_MUTED
        if self.seal is not None:
            col_cap = {"تم": th.EMERALD_ON_NAVY, "تعذّر": th.DANGER_ON_NAVY}.get(self.seal[0], "#FFFFFF")
        p.setPen(_q(col_cap))
        p.setFont(_font(th.FS_CAPTION, th.W_MEDIUM))
        if self.seal is None:
            cap = self.caption
        else:
            cap = {"تم": "خُتم — البيانات محفوظة", "ناقص": "خُتم مع ملاحظة",
                   "تعذّر": "لم يُختم — راجع السبب"}.get(self.seal[0], "")
        p.drawText(QRectF(0, sheet.bottom() + 22, self.W, 22), Qt.AlignmentFlag.AlignCenter, cap)
        p.end()


class _Ledger(QWidget):
    """دفتر المراحل: خط زمني كحلي على حافة القراءة (اليمين)، وعقدة لكل مرحلة"""
    ROW = 46
    RAIL_X_FROM_RIGHT = 14

    def __init__(self, task):
        super().__init__()
        self.task = task
        self.started = {}         # رقم المرحلة -> وقت البدء
        self.stamped = {}         # رقم المرحلة -> وقت الختم (لحركة ظهور العلامة)
        self.t = 0.0
        self.now = 0.0
        self.motion = mo.motion_enabled()
        self.setFixedHeight(self.ROW * len(STAGES))
        self.setMinimumWidth(250)

    def sync(self, now):
        for i, st in enumerate(self.task.stages):
            if st == IN_PROGRESS and i not in self.started:
                self.started[i] = now
            if st in (DONE, ERROR, SKIPPED) and i not in self.stamped:
                self.stamped[i] = now

    def step(self, dt, now):
        self.t += dt
        self.now = now
        self.sync(now)
        self.update()

    def _caption(self, i, st):
        note = (self.task.notes[i] or "").lstrip("✅❌⚠️ ").strip()
        if i == len(STAGES) - 1:
            return "", None   # نتيجة العرض النهائي تظهر بسطر التذييل، ما نكررها
        if st == IN_PROGRESS:
            el = int(self.now - self.started.get(i, self.now))
            # الخطوة الفعلية (مثل "OCR.space يقرأ الصفحات 1 و6 و7") إن وُجدت، مع الوقت
            if note:
                return f"{note} · {_seconds_ar(el)}", (th.AMBER_TEXT if i < 2 and el >= SLOW_AFTER_S
                                                       else th.TEXT_SECONDARY)
            if i < 2 and el >= SLOW_AFTER_S:
                return f"الشبكة بطيئة الآن — مضت {_seconds_ar(el)}", th.AMBER_TEXT
            return (f"جارٍ منذ {_seconds_ar(el)}" if el >= 1 else "بدأت للتو"), th.TEXT_SECONDARY
        if st == ERROR:
            return (note or "تعذّرت هذه المرحلة"), th.DANGER_TEXT
        if st == SKIPPED:
            if note:
                return note, th.TEXT_SECONDARY
            if ERROR in self.task.stages:
                return "لم تُنفَّذ بسبب تعذّر المرحلة السابقة", th.TEXT_SECONDARY
            return "تم التخطي — لا حاجة لها", th.TEXT_SECONDARY
        if st == DONE and note:
            return note, th.TEXT_SECONDARY
        return "", None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W = self.width()
        rx = W - self.RAIL_X_FROM_RIGHT
        stages = self.task.stages
        n = len(stages)

        # الخط الزمني: زمردي بين المراحل المختومة، رمادي-كحلي لباقي الطريق
        for i in range(n - 1):
            y0 = i * self.ROW + 14 + 11
            y1 = (i + 1) * self.ROW + 14 - 11
            done_seg = stages[i] == DONE and stages[i + 1] in (DONE, IN_PROGRESS)
            p.setPen(QPen(_q(th.EMERALD if done_seg else th.RAIL_LINE), 2))
            p.drawLine(QPointF(rx, y0), QPointF(rx, y1))

        text_right = W - 40
        for i, st in enumerate(stages):
            if st == IN_PROGRESS:
                cy = i * self.ROW + 14
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_q(th.NAVY_SOFT))
                p.drawRoundedRect(QRectF(0, cy - 15, W - 30, 42 if self._caption(i, st)[0] else 30),
                                  th.RADIUS_BTN, th.RADIUS_BTN)
        for i, (name, st) in enumerate(zip(STAGES, stages)):
            cy = i * self.ROW + 14
            c = QPointF(rx, cy)
            age = self.now - self.stamped.get(i, -10)
            pop = _ease_out(age / 0.24) if self.motion else 1.0

            if st == DONE:
                r = 9 + (1 - pop) * 3
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(_q(th.EMERALD)); p.drawEllipse(c, r, r)
                pen = QPen(_q(th.SURFACE), 2.2)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                p.drawPolyline(QPolygonF([QPointF(rx - 4, cy + 0.3), QPointF(rx - 1.2, cy + 3),
                                          QPointF(rx + 4.2, cy - 3)]))
            elif st == ERROR:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(_q(th.DANGER)); p.drawEllipse(c, 9, 9)
                pen = QPen(_q(th.SURFACE), 2.2); pen.setCapStyle(Qt.PenCapStyle.RoundCap); p.setPen(pen)
                p.drawLine(QPointF(rx - 3.2, cy - 3.2), QPointF(rx + 3.2, cy + 3.2))
                p.drawLine(QPointF(rx + 3.2, cy - 3.2), QPointF(rx - 3.2, cy + 3.2))
            elif st == SKIPPED:
                p.setPen(QPen(_q(th.RAIL_LINE), 2)); p.setBrush(_q(th.BG)); p.drawEllipse(c, 8, 8)
                p.setPen(QPen(_q(th.RULER_TRACK), 2))
                p.drawLine(QPointF(rx - 3.5, cy), QPointF(rx + 3.5, cy))
            elif st == IN_PROGRESS:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(_q(th.NAVY_TINT)); p.drawEllipse(c, 11, 11)
                p.setBrush(_q(th.SURFACE)); p.drawEllipse(c, 8, 8)
                pen = QPen(_q(th.NAVY), 2.4); pen.setCapStyle(Qt.PenCapStyle.RoundCap); p.setPen(pen)
                ang = (self.t * 300) % 360 if self.motion else 90
                p.drawArc(QRectF(rx - 8, cy - 8, 16, 16), int(-ang * 16), 110 * 16)
            else:
                p.setPen(QPen(_q(th.RAIL_LINE), 2)); p.setBrush(_q(th.BG)); p.drawEllipse(c, 8, 8)

            # النص: اسم المرحلة + سطر حالة صغير
            if st == IN_PROGRESS:
                p.setFont(_font(th.FS_BODY + 1, th.W_BOLD)); color = th.TEXT_PRIMARY
            elif st == DONE:
                p.setFont(_font(th.FS_BODY, th.W_MEDIUM)); color = th.TEXT_PRIMARY
            elif st == ERROR:
                p.setFont(_font(th.FS_BODY, th.W_MEDIUM)); color = th.DANGER_TEXT
            else:
                p.setFont(_font(th.FS_BODY)); color = th.TEXT_SECONDARY
            p.setPen(_q(color))
            p.drawText(QRectF(0, cy - 11, text_right, 22),
                       th.ARIGHT | Qt.AlignmentFlag.AlignVCenter, name)
            cap, ccol = self._caption(i, st)
            if cap:
                p.setFont(_font(th.FS_CAPTION, th.W_MEDIUM))
                p.setPen(_q(ccol))
                fm = p.fontMetrics()
                cap = fm.elidedText(cap, Qt.TextElideMode.ElideRight, int(text_right))   # يقص نهاية الجملة لا بدايتها
                if not _has_arabic(cap):
                    cap = "⁦" + cap + "⁩"   # رسالة خطأ لاتينية: تُعرض يسار-ليمين كاملة الترتيب
                p.drawText(QRectF(0, cy + 9, text_right, 18),
                           th.ARIGHT | Qt.AlignmentFlag.AlignVCenter, cap)
        p.end()


def _secondary_css():
    return f"""
        QPushButton {{ background:{th.BTN2_BG}; color:{th.NAVY}; border:1px solid {th.BTN2_BORDER};
            border-radius:{th.RADIUS_BTN}px; padding:9px 18px; font-size:{th.FS_LABEL + 1}px;
            font-weight:{th.W_MEDIUM}; }}
        QPushButton:hover {{ background:{th.DANGER_BG}; color:{th.DANGER_TEXT}; border-color:{th.DANGER_BG}; }}
        QPushButton:pressed {{ padding-top:10px; padding-bottom:8px; }}
        QPushButton:focus {{ border-color:{th.NAVY}; }}
        QPushButton:disabled {{ color:{th.TEXT_MUTED}; border-color:{th.BORDER_SOFT}; }}
    """


class ExtractionProgressDialog(QDialog):
    def __init__(self, parent, task, allow_minimize=True, auto_close_ms=1100):
        # القابلة للتصغير نافذة مستقلة (بلا أب) حتى تبقى ظاهرة خلف البرنامج ولا تُغطّي عليه
        super().__init__(None if allow_minimize else parent)
        if allow_minimize:
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowTitleHint
                                | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
            if parent is not None:
                parent.destroyed.connect(lambda *_: self._finish())
        self.task = task
        self.allow_minimize = allow_minimize
        self.auto_close_ms = auto_close_ms
        self._closing = False
        self._finished_shown = False

        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("استخراج بيانات القضية")
        self.setFixedSize(700, 452)
        # قابلة للتصغير = غير حاجبة: الخبير يضغط بأي مكان بالبرنامج ويكمل
        # شغله، والنافذة تتنحى للخلفية بروحها (بدون زر). مسار المحضر حاجب.
        self.setModal(not allow_minimize)
        self._armed = False
        if allow_minimize:
            QTimer.singleShot(400, lambda: setattr(self, '_armed', True))
        self.setStyleSheet(f"QDialog {{ background:{th.BG}; }} QLabel {{ background:transparent; }}")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(32, 28, 30, 22)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setSpacing(0)
        col = QVBoxLayout()
        col.setSpacing(0)

        self.title = QLabel("جاري استخراج بيانات القضية")
        self.title.setFont(_font(th.FS_HEADLINE, th.W_BOLD))
        self.title.setStyleSheet(f"color:{th.TEXT_PRIMARY};")
        self.title.setAlignment(th.ARIGHT)
        uploaded = isinstance(task.key, tuple) and task.key[0] == 'upload'
        source = "ملف مرفوع يدويًا" if uploaded else "حكم الإحالة من الملف الآلي"
        self._source = source
        self.sub = QLabel(f"القضية {th.ltr(task.caso_no)}  ·  {source}")
        self.sub.setFont(_font(th.FS_LABEL))
        self.sub.setStyleSheet(f"color:{th.TEXT_SECONDARY};")
        self.sub.setAlignment(th.ARIGHT)
        col.addWidget(self.title)
        col.addSpacing(4)
        col.addWidget(self.sub)
        col.addSpacing(22)
        self.ledger = _Ledger(task)
        col.addWidget(self.ledger)
        col.addStretch()

        self.sheet = _JudgmentSheet(task.caso_no)
        body.addLayout(col, 1)
        root.addLayout(body, 1)
        outer.addWidget(content, 1)               # RTL: أول عنصر = يمين
        outer.addWidget(self.sheet)               # العمود الكحلي على الحافة اليسرى

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background:{th.BORDER};")
        root.addWidget(rule)
        root.addSpacing(16)

        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.hint = QLabel("اضغط بأي مكان وكمّل شغلك — نبلغك أول ما يخلص" if allow_minimize
                           else "تكمل الطباعة تلقائيًا بعد الاستخراج")
        self.hint.setFont(_font(th.FS_CAPTION, th.W_MEDIUM))
        self.hint.setStyleSheet(f"color:{th.TEXT_SECONDARY};")
        self.cancel_btn = QPushButton("إلغاء")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(_secondary_css())
        self.cancel_btn.clicked.connect(self.cancel)
        self.hint.setWordWrap(True)
        self.hint.setAlignment(th.ARIGHT | Qt.AlignmentFlag.AlignVCenter)
        foot.addWidget(self.hint, 1)              # RTL: الخلاصة يمينًا، تلتف لو طالت
        foot.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(foot)
        self.title.setFont(_font(th.FS_HEADLINE + 2, th.W_BOLD))

        task.window = self
        task.minimized = False
        task.stage_changed.connect(self._refresh)
        task.done.connect(self._on_done)

        self._clock = time.monotonic()
        self._t0 = self._clock
        self._refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._frame)
        self._timer.start(FRAME_MS)

    def _refresh(self):
        done = sum(1 for s in self.task.stages[:4] if s in (DONE, SKIPPED, ERROR))
        # كل مرحلة مكتملة تكتب ~سطرين من الحكم؛ المرحلة الجارية تكتب نص سطر
        running = any(s == IN_PROGRESS for s in self.task.stages[:4])
        self.sheet.target = min(_JudgmentSheet.LINES, done * 2.4 + (0.7 if running else 0))
        cur = next((i for i, s in enumerate(self.task.stages) if s == IN_PROGRESS), None)
        if cur is not None:
            self.sheet.caption = f"المرحلة {cur + 1} من {len(STAGES)}"
        elif not any(s != PENDING for s in self.task.stages):
            self.sheet.caption = "بانتظار الملف الآلي…"
        self.ledger.sync(time.monotonic() - self._t0)

    def _frame(self):
        now = time.monotonic()
        dt, self._clock = now - self._clock, now
        self.sheet.step(dt)
        self.ledger.step(dt, now - self._t0)

    def _on_done(self):
        t = self.task
        self.sheet.target = _JudgmentSheet.LINES
        self.sheet.reading = False
        summary = t.summary or ""
        if t.success:
            self.sheet.stamp("تم", th.EMERALD)
            self.title.setText("اكتمل الاستخراج")
        elif summary.startswith("❌"):
            self.sheet.stamp("تعذّر", th.DANGER)
            self.title.setText("تعذّر الاستخراج")
        else:
            self.sheet.stamp("ناقص", th.AMBER)
            self.title.setText("اكتمل مع ملاحظة")
        took = int(time.monotonic() - self._t0)
        self.sub.setText(f"القضية {th.ltr(t.caso_no)}  ·  {self._source}  ·  خلال {_seconds_ar(max(1, took))}")
        clean = summary.lstrip("✅❌⚠️ ").strip()
        if clean and not t.success:
            self.hint.setText(_bidi_tail(clean))
            self.hint.setStyleSheet(f"color:{th.DANGER_TEXT if summary.startswith('❌') else th.AMBER_TEXT};")
        # الأزرار ما عاد لها معنى — نخفيها بدل ما تبقى رمادية معطّلة
        self.cancel_btn.hide()
        facts = case_facts(t.result) if t.success else ""
        if t.success:
            self.hint.setText(facts or "البيانات محفوظة بالقاعدة")
            self.hint.setFont(_font(th.FS_LABEL, th.W_BOLD))
            self.hint.setStyleSheet(f"color:{th.EMERALD_TEXT};")
        # وقت كافي يشوف فيه الختم ينطبع قبل ما تنقفل
        # وقت يكفي يشوف الختم ينطبع ويقرا الخلاصة قبل ما تنقفل
        QTimer.singleShot(self.auto_close_ms + (900 if facts else 0) if t.success
                          else self.auto_close_ms + 1600, self._finish)

    def cancel(self):
        self.task.cancel()
        self._finish()

    def minimize(self):
        self.task.minimized = True
        self._finish()

    def changeEvent(self, e):
        # فقدت التركيز (ضغط على البرنامج أو برنامج ثاني) = كمّل بالخلفية
        # (سابقاً: تُغلق عند فقدان التركيز. الآن تبقى ظاهرة خلف البرنامج حتى انتهاء المهمة)
        super().changeEvent(e)

    def reject(self):
        if self._closing:
            return super().reject()
        self.minimize() if self.allow_minimize else self.cancel()

    def _finish(self):
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        try:
            self.task.stage_changed.disconnect(self._refresh)
            self.task.done.disconnect(self._on_done)
        except (TypeError, RuntimeError):
            pass
        if self.task.window is self:
            self.task.window = None
        self.done(QDialog.DialogCode.Accepted)
        self.deleteLater()


def show_progress(parent, task, allow_minimize=True):
    """يعرض نافذة التقدم بدون حجب (للمسارات اللي تكمل بعد الانتهاء عبر task.done)"""
    old = task.window
    if old is not None:
        try:
            if old.allow_minimize == allow_minimize:
                old.raise_(); old.activateWindow()
                return old
            old._finish()
        except RuntimeError:
            pass
    dlg = ExtractionProgressDialog(parent, task, allow_minimize=allow_minimize)
    dlg.show()
    return dlg


# ============================================================
# الإشعار — بطاقة صغيرة على زاوية الشاشة
# ============================================================

_TOASTS = []
_SHADOW = 18     # هامش شفاف حول البطاقة عشان ظل المكتب


class _StatusSeal(QWidget):
    """ختم الحالة الصغير على يمين الإشعار — نفس لغة أختام الدفتر"""
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.setFixedSize(30, 30)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg, fg = {"success": (th.EMERALD_BG, th.EMERALD),
                  "warning": (th.AMBER_BG, th.AMBER),
                  "error": (th.DANGER_BG, th.DANGER)}[self.kind]
        c = QPointF(15, 15)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(_q(bg)); p.drawEllipse(c, 15, 15)
        pen = QPen(_q(fg), 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if self.kind == "success":
            p.drawPolyline(QPolygonF([QPointF(9.5, 15.3), QPointF(13.3, 19), QPointF(20.5, 11.5)]))
        elif self.kind == "error":
            p.drawLine(QPointF(11, 11), QPointF(19, 19)); p.drawLine(QPointF(19, 11), QPointF(11, 19))
        else:
            p.drawLine(QPointF(15, 9.5), QPointF(15, 16.5))
            p.setBrush(_q(fg)); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QPointF(15, 20.3), 1.4, 1.4)
        p.end()


class _CloseGlyph(QPushButton):
    def __init__(self):
        super().__init__()
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("إغلاق")
        self.setStyleSheet(f"QPushButton {{ background:transparent; border:none; border-radius:6px; }}"
                           f"QPushButton:hover {{ background:{th.NAVY_SOFT}; }}")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(_q(th.NAVY if self.underMouse() else th.TEXT_SECONDARY), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(8.5, 8.5), QPointF(15.5, 15.5)); p.drawLine(QPointF(15.5, 8.5), QPointF(8.5, 15.5))
        p.end()


class Toast(QWidget):
    def __init__(self, title, message, kind="success", action_text=None, action=None, duration_ms=6000):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setFixedWidth(380 + 2 * _SHADOW)
        kind = kind if kind in ("success", "warning", "error") else "success"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_SHADOW, _SHADOW - 6, _SHADOW, _SHADOW + 6)
        card = QFrame()
        card.setObjectName("toast")
        card.setStyleSheet(f"#toast {{ background:{th.SURFACE}; border:1px solid {th.BORDER}; border-radius:12px; }}"
                           "QLabel { background:transparent; border:none; }")
        eff = QGraphicsDropShadowEffect(card)
        eff.setBlurRadius(26); eff.setOffset(0, 8); eff.setColor(_q(th.TEXT_PRIMARY, 34))
        card.setGraphicsEffect(eff)
        outer.addWidget(card)

        row = QHBoxLayout(card)
        row.setContentsMargins(16, 14, 12, 14)
        row.setSpacing(12)
        row.addWidget(_StatusSeal(kind), 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(3)
        t = QLabel(title)
        t.setFont(_font(th.FS_BODY + 1, th.W_BOLD))
        t.setStyleSheet(f"color:{th.TEXT_PRIMARY};")
        t.setAlignment(th.ARIGHT)
        m = QLabel(message)
        m.setWordWrap(True)
        m.setFont(_font(th.FS_LABEL))
        m.setStyleSheet(f"color:{th.TEXT_SECONDARY};")
        m.setAlignment(th.ARIGHT)
        text.addWidget(t)
        text.addWidget(m)
        if action_text and action:
            b = QPushButton(action_text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"QPushButton {{ background:{th.NAVY}; color:white; border:none; border-radius:8px;"
                            f" padding:6px 14px; font-size:{th.FS_LABEL}px; font-weight:{th.W_BOLD}; }}"
                            f"QPushButton:hover {{ background:{th.NAVY_HOVER}; }}")

            def _go():
                self.fade_out()
                action()
            b.clicked.connect(_go)
            br = QHBoxLayout(); br.addWidget(b); br.addStretch()
            text.addSpacing(8); text.addLayout(br)
        row.addLayout(text, 1)
        x = _CloseGlyph()
        x.clicked.connect(self.fade_out)
        row.addWidget(x, 0, Qt.AlignmentFlag.AlignTop)

        self.adjustSize()
        self._remaining = duration_ms
        self._hover = False
        self._closing = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)

        _TOASTS.append(self)
        Toast._restack(animate=False)
        self.setWindowOpacity(0.0)
        self.show()
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(200 if mo.motion_enabled() else 80)
        self._anim.setStartValue(0.0); self._anim.setEndValue(1.0)
        self._anim.start()
        if mo.motion_enabled():
            end = self.pos()
            self.move(end.x(), end.y() + 14)
            self._slide = QPropertyAnimation(self, b"pos", self)
            self._slide.setDuration(260); self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._slide.setStartValue(self.pos()); self._slide.setEndValue(end)
            self._slide.start()

    @staticmethod
    def _restack(animate=True):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        y = screen.bottom() - 6
        for t in _TOASTS:
            y -= t.height() - _SHADOW
            target = QPoint(screen.right() - t.width() + 2, y - _SHADOW + 4)
            if animate and mo.motion_enabled() and t.isVisible():
                a = QPropertyAnimation(t, b"pos", t)
                a.setDuration(220); a.setEasingCurve(QEasingCurve.Type.OutCubic)
                a.setEndValue(target); a.start()
                t._restack_anim = a
            else:
                t.move(target)
            y -= 2

    def enterEvent(self, e):
        self._hover = True
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        super().leaveEvent(e)

    def _tick(self):
        if not self._hover:
            self._remaining -= 100
        if self._remaining <= 0:
            self.fade_out()

    def fade_out(self):
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(180); self._anim.setStartValue(self.windowOpacity()); self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._gone)
        self._anim.start()

    def _gone(self):
        if self in _TOASTS:
            _TOASTS.remove(self)
        self.close()
        Toast._restack()


def show_toast(title, message, kind="success", action_text=None, action=None, duration_ms=6000):
    return Toast(title, message, kind, action_text, action, duration_ms)


def show_task_toast(task):
    action = task.on_toast_open
    case = th.ltr(task.caso_no)
    if task.success:
        facts = case_facts(task.result)
        show_toast("اكتمل استخراج بيانات القضية",
                   f"القضية {case} جاهزة" + (f"\n{facts}" if facts else " — بياناتها محفوظة."),
                   "success", "فتح القضية" if action else None, action, duration_ms=7000)
    else:
        summary = (task.summary or "انتهت العملية").lstrip("✅❌⚠️ ").strip()
        kind = "error" if (task.summary or "").startswith("❌") else "warning"
        title = "تعذّر الاستخراج" if kind == "error" else "اكتمل الاستخراج مع ملاحظة"
        show_toast(title, f"القضية {case}: {summary}", kind,
                   "فتح القضية" if action else None, action, duration_ms=10000)


# ============================================================
# مساعد عام: تشغيل أي دالة شبكة بـthread، والنتيجة ترجع للـmain thread
# ============================================================

class _BgBridge(QObject):
    ok = pyqtSignal(object)
    fail = pyqtSignal(str)


_BG_JOBS = set()   # نحتفظ بالمراجع لين ترجع النتيجة


def run_in_background(fn, on_ok, on_fail):
    """
    fn() تشتغل بـthread منفصل (ممنوع تلمس الواجهة). on_ok(نتيجة) أو
    on_fail(نص_الخطأ) تُستدعى بالـmain thread — آمنة لتحديث الواجهة.
    """
    bridge = _BgBridge()
    _BG_JOBS.add(bridge)

    def _ok(r):
        _BG_JOBS.discard(bridge)
        on_ok(r)

    def _fail(msg):
        _BG_JOBS.discard(bridge)
        on_fail(msg)

    bridge.ok.connect(_ok)
    bridge.fail.connect(_fail)

    def _run():
        try:
            r = fn()
        except Exception as e:
            traceback.print_exc()
            bridge.fail.emit(str(e))
            return
        bridge.ok.emit(r)

    threading.Thread(target=_run, daemon=True, name="bg-job").start()
