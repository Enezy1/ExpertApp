# ===== extraction_tasks.py — مدير عمليات الاستخراج بالخلفية (threading + queue) =====
"""
كل عملية استخراج (سحب حكم الإحالة + Gemini) تشتغل بـthread منفصل.
القاعدة الذهبية: الـworker thread ما يلمس أي عنصر CTk أبدًا — كل اللي
يسويه إنه يحط رسائل بـqueue.Queue، والـmain thread يفحص الـqueue كل
POLL_MS عبر after() ويحدّث الواجهة بأمان.

يدعم أكثر من عملية بنفس الوقت (لقضايا مختلفة): المهام مخزنة بـdict
مفتاحه رقم القضية. طلب عملية لقضية عندها عملية شغالة أصلاً يرجع نفس
المهمة (بدون تكرار سحب/تكلفة API).
"""
import queue
import threading
import traceback

POLL_MS = 100

STAGES = [
    "سحب حكم الإحالة من الملف الآلي",
    "قراءة وتحليل حكم الإحالة",   # الخطوة الفعلية (OCR داخلي/OCR.space/أي مزود) تظهر بملاحظة المرحلة
    "تجهيز ملخص الخبير الأولي",
    "مراجعة الطلبات والخصوم",
    "العرض النهائي",
]

PENDING, IN_PROGRESS, DONE, ERROR, SKIPPED = "pending", "in_progress", "done", "error", "skipped"


from ai_providers import UserCancelled as _UserCancelled, set_cancel_event


class Cancelled(BaseException):
    """BaseException عمدًا — عشان ما تبلعها كتل 'except Exception: pass' الموجودة بمنطق الجلب"""


class ExtractionTask:
    def __init__(self, key, caso_no, worker, finalize):
        self.key = key
        self.caso_no = caso_no
        self._worker = worker          # worker(progress) -> (result, error) — يشتغل بالـthread
        self._finalize = finalize      # finalize(task) — يشتغل بالـmain thread بعد الانتهاء
        self.queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.stages = [PENDING] * len(STAGES)
        self.notes = [""] * len(STAGES)
        self.state = "running"         # running / finished / cancelled
        self.result = None
        self.error = None
        self.summary = ""              # نص الحالة النهائي (يُعبّى بـfinalize)
        self.success = False
        self.minimized = False
        self.window = None             # نافذة التقدم المرتبطة حاليًا (إن وجدت)
        self.listeners = []            # callables(task) تُستدعى بالـmain thread عند الانتهاء
        self.on_stage = []             # callables(task) تُستدعى بالـmain thread عند تغيّر أي مرحلة
        self.toast_factory = None      # callable(task) يعرض Toast لو المهمة كانت مصغّرة

    # ---------- داخل الـworker thread ----------
    def progress(self, index, state, note=""):
        """يُستدعى من الـworker فقط — يحط رسالة بالـqueue، ويوقف العملية لو انلغت"""
        if self.cancel_event.is_set():
            raise Cancelled()
        self.queue.put(("stage", index, state, note))

    def _run(self):
        set_cancel_event(self.cancel_event)   # مزود المتصفح يتوقف بإلغاء هذه المهمة فقط
        try:
            result, error = self._worker(self.progress)
            self.queue.put(("finish", result, error))
        except (Cancelled, _UserCancelled):
            self.queue.put(("cancelled",))
        except Exception as e:
            traceback.print_exc()
            self.queue.put(("finish", None, str(e)))

    def start(self):
        threading.Thread(target=self._run, daemon=True,
                         name=f"extract-{self.caso_no}").start()

    # ---------- main thread ----------
    def cancel(self):
        """الـthread ما ينقتل بالقوة (طلب الشبكة ما يقبل مقاطعة) — نعلّمه
        بالإلغاء، ويتوقف بأول نقطة فحص، وأي نتيجة توصل بعدها تنتجاهل."""
        if self.state == "running":
            self.cancel_event.set()
            self.state = "cancelled"
            _MANAGER._remove(self)

    def set_stage(self, index, state, note=""):
        self.stages[index] = state
        self.notes[index] = note
        for cb in list(self.on_stage):
            try:
                cb(self)
            except Exception:
                traceback.print_exc()

    def _handle(self, msg):
        kind = msg[0]
        if self.state != "running":
            return  # ملغاة — نتجاهل أي شي يوصل متأخر
        if kind == "stage":
            _, i, st, note = msg
            self.set_stage(i, st, note)
        elif kind == "cancelled":
            self.state = "cancelled"
            _MANAGER._remove(self)
        elif kind == "finish":
            _, self.result, self.error = msg
            # أي مرحلة ظلت "جارية" بدون ما تنقفل = هي اللي فشلت
            # وأي مرحلة ما وصلها الدور أصلاً = اتخطّت (مثلاً ما فيه حكم إحالة)
            for i, st in enumerate(self.stages[:-1]):
                if st == IN_PROGRESS:
                    self.set_stage(i, ERROR if self.error else DONE, self.notes[i])
                elif st == PENDING:
                    self.set_stage(i, SKIPPED)
            self.set_stage(4, IN_PROGRESS)
            final_state = DONE
            try:
                self._finalize(self)
            except Exception as e:
                traceback.print_exc()
                self.error = self.error or str(e)
                self.summary = f"❌ {e}"
                self.success = False
                final_state = ERROR
            self.set_stage(4, final_state, self.summary)
            self.state = "finished"
            _MANAGER._remove(self)
            for cb in list(self.listeners):
                try:
                    cb(self)
                except Exception:
                    traceback.print_exc()
            if self.minimized and self.toast_factory:
                try:
                    self.toast_factory(self)
                except Exception:
                    traceback.print_exc()


class _TaskManager:
    def __init__(self):
        self.tasks = {}          # key -> ExtractionTask
        self._root = None
        self._polling = False

    def get(self, key):
        return self.tasks.get(key)

    def running(self):
        return list(self.tasks.values())

    def start(self, root_widget, key, caso_no, worker, finalize):
        """يرجع (task, is_new). لو فيه مهمة شغالة لنفس المفتاح، يرجعها بدل ما يبدأ وحدة ثانية."""
        existing = self.tasks.get(key)
        if existing and existing.state == "running":
            return existing, False
        self._root = root_widget.winfo_toplevel()._root()
        task = ExtractionTask(key, caso_no, worker, finalize)
        self.tasks[key] = task
        task.start()
        self._ensure_polling()
        return task, True

    def _remove(self, task):
        if self.tasks.get(task.key) is task:
            del self.tasks[task.key]

    def _ensure_polling(self):
        if not self._polling:
            self._polling = True
            self._root.after(POLL_MS, self._poll)

    def _poll(self):
        # نحتفظ بنسخة لأن المهام تنحذف من الـdict أثناء المعالجة
        for task in list(self.tasks.values()):
            try:
                while True:
                    task._handle(task.queue.get_nowait())
            except queue.Empty:
                pass
        if self.tasks:
            try:
                self._root.after(POLL_MS, self._poll)
                return
            except Exception:
                pass  # النافذة الجذرية انقفلت
        self._polling = False


_MANAGER = _TaskManager()


def manager():
    return _MANAGER
