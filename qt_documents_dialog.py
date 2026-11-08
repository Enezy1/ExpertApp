# ===== qt_documents_dialog.py — نافذة مستندات القضية (المرحلة 2ي، أُعيد تصميمها 2026-10-17) =====
# الحافظة = مجموعة مستندات قدّمها أحد الخصوم بتاريخ واحد؛ تُسأل مرة (المقدِّم والتاريخ) ثم تُختار الملفات
# (ملفات أو مجلد كامل) فتظهر في قائمة واحدة بحالة لكل ملف: جديد / جارٍ التحويل / تم التحويل / فشل.
# «استيراد وتحويل» ينسخ ويحوّل الجديد فقط (بصمة الملف تمنع إعادة تحويل ما تحوّل). زر «إعادة المحاولة» بجانب الفاشل فقط.
# كل العمل في خيط خلفي (Job) تتابعه الواجهة بإشارات؛ لوحة اليسار «ما يفعله البرنامج الآن» تعرض الخطوات والأخطاء.
# الإغلاق لا يضيّع شيئاً (case.json يُحفظ بعد كل ملف): إن كان تحويل جارياً يُسأل الخبير: إيقاف أم متابعة بالخلفية.
# مرحلتان (2026-10-17): «إضافة وتصنيف» ينسخ ويصنّف كل ملف (OCR الصفحة الأولى + قواعد) ويعيّن محرّكه؛ ثم يعدّل الخبير
# النوع/المحرّك من قائمة بكل صف («غير معروف» لا يُحوَّل قبل اختياره) ثم «استيراد وتحويل» يحوّل الجاهز فقط.
# المنطق في case_documents.py وdoc_router.py؛ هنا عرض وإشارات فقط.
# 2026-10-18 «إضافة مستندات القضية» (تصميم Stitch): المكان الوحيد لإضافة المستندات. السحب/الاختيار يبدأ العملية فوراً
# (نسخ ← تصنيف بالمحتوى ← تحويل) بلا زر؛ مقدّم الحافظة وتاريخها يُقترحان من الصفحة الأولى؛ ما لم يتضح نوعه يُسأل
# عنه مرة واحدة؛ اللوحة الجانبية تعرض «N من M» ونسبة كل ملف؛ الإغلاق لا يوقف العمل (يتابع بالخلفية).
import os
import threading
from datetime import datetime

from PyQt6.QtCore import Qt, QDate, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit, QDateEdit, QTableWidget,
    QTableWidgetItem, QSpinBox, QFileDialog, QMessageBox, QHeaderView, QAbstractItemView, QPlainTextEdit,
    QPushButton, QFrame, QProgressBar,
)

import qt_theme as th
from qt_widgets import PrimaryButton, SecondaryButton

import case_documents
import case_model
import doc_router

NEW = '__new__'
C_PORT, C_NO, C_FILE, C_TYPE, C_ENGINE, C_GUESS, C_CONTRACT, C_STATE, C_ACTION = range(9)
PLACEHOLDER = '— اختر النوع —'
STATE_ORIGINAL = 'لا يحتاج تحويل'
STATE_TEXT = {'staged': 'جديد', 'pending': 'جديد', 'running': 'جارٍ التحويل…', 'done': 'تم التحويل', 'failed': 'فشل'}
PORTFOLIO_HELP = ("الحافظة: مجموعة مستندات قدّمها أحد الخصوم (المدعية مثلاً) بتاريخ واحد. "
                  "نسجّل مقدِّمها وتاريخها مرة، ثم نضيف مستنداتها فتُرقَّم داخلها، "
                  "وتُذكر في التقرير: «حافظة مستندات … بتاريخ …».")

# لون خاص بكل حافظة: (خلفية، نص) — المدعية عنبري، المدعى عليه تيل، وبقية الحوافظ ألوان هادئة متمايزة
_TEAL = ('#DDF1EF', '#0B5F5A')
_PALETTE = [_TEAL, (th.AMBER_BG, th.AMBER_TEXT), (th.BLUE_INFO_BG, th.BLUE_INFO_TEXT), ('#EDE7F6', '#4A2F8A'),
            ('#F1F5E4', '#4B6A12')]


def portfolio_colors(submitter, index=0):
    s = submitter or ''
    if 'عليه' in s or 'عليها' in s or 'عليهم' in s:
        return _TEAL
    if 'مدعي' in s or 'المدعية' in s or 'مدعى' in s:
        return (th.AMBER_BG, th.AMBER_TEXT)
    return _PALETTE[(index + 2) % len(_PALETTE)]


def friendly_error(msg):
    """رسالة فشل مفهومة: الأخطاء العربية كما هي، والتقنية (اسم_استثناء: …) تُغلَّف بعبارة بسيطة."""
    msg = (msg or '').strip()
    if not msg:
        return 'تعذّر التحويل لسبب غير معروف'
    head = msg.split(':', 1)[0]
    if head.isascii() and head.replace('_', '').isalnum() and ':' in msg:
        return f'خطأ تقني أثناء القراءة ({msg}) — جرّب «إعادة المحاولة» أو راسل الدعم بهذا النص'
    return msg


# ---------- عمل خلفي مشترك (يبقى حياً لو أُغلقت النافذة) ----------

class _Bridge(QObject):
    log = pyqtSignal(str, str)              # (base, سطر)
    update = pyqtSignal(str, str, object)   # (base, uid، حالة التحويل) — uid '*' = أعد رسم القائمة
    finished = pyqtSignal(str, object)      # (base, ملخص | Exception)


_BRIDGE = None
_JOBS = {}                                  # base -> Job


_OPEN = set()                               # قواعد القضايا التي نافذة مستنداتها مفتوحة


def _global_finished(base, res):
    """تحويل أنهى عمله بعد إغلاق نافذته: رسالة صغيرة بدل الصمت."""
    if base not in _OPEN and not isinstance(res, Exception):
        from qt_review_dialogs import show_saved_toast
        show_saved_toast(None, "اكتمل تحويل المستندات بالخلفية ✓", 3500)


def bridge():
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = _Bridge()
        _BRIDGE.finished.connect(_global_finished)
    return _BRIDGE


class Job:
    def __init__(self, base, data):
        self.base, self.data = base, data
        self.stop_flag = False
        self.thread = None


def active_job(base):
    return _JOBS.get(base)


def live_data(base):
    """case.json الحيّ في الذاكرة إن كان تحويل يعمل بالخلفية (لئلا تكتب نافذة أخرى فوق تقدّمه)."""
    j = _JOBS.get(base)
    return j.data if j else None


def start_job(base, data, fn):
    """fn(job, br) في خيط واحد لكل قضية. يرجع Job أو None إن كان هناك عمل جارٍ."""
    if base in _JOBS:
        return None
    br = bridge()
    job = Job(base, data)
    _JOBS[base] = job

    def run():
        try:
            res = fn(job, br)
        except Exception as e:
            res = e
        finally:
            _JOBS.pop(base, None)
        br.finished.emit(base, res)
    job.thread = threading.Thread(target=run, daemon=True)
    job.thread.start()
    return job


def convert_work(base, data, convert=None):
    """دالة العمل الخلفي لتحويل الجاهز (pending) — تستعملها النافذة والاستئناف التلقائي عند فتح القضية."""
    def work(job, br):
        pend = case_documents.pending_docs(data)
        held = sum(1 for _, d in case_documents.all_docs(data)
                   if d.get('needs_type') and d['convert']['state'] == 'pending')
        br.log.emit(base, f"سيتم تحويل {len(pend)} مستنداً (ما سبق تحويله يُتخطّى)."
                          + (f" و{held} بانتظار اختيار نوعه فلن يُحوَّل." if held else ""))
        return _run_pending(job, br, base, data, convert)
    return work


def _run_pending(job, br, base, data, convert):
    def on_update(uid, conv):
        br.update.emit(base, uid, conv)
        _p, d = case_documents.find_doc(data, uid)
        name = d['orig_name']
        if conv['state'] == 'running' and not conv.get('progress'):
            eng = doc_router.ENGINE_LABELS.get(d.get('engine'), '')
            br.log.emit(base, f"بدأ قراءة «{name}» وتحويلها إلى نص" + (f" ({eng})…" if eng else "…"))
        elif conv['state'] == 'done':
            br.log.emit(base, f"اكتمل «{name}» ({d.get('pages') or '؟'} صفحة).")
            if d.get('warning'):
                br.log.emit(base, f"⚠ «{name}»: {d['warning']}")
        elif conv['state'] == 'failed':
            br.log.emit(base, f"فشل «{name}»: {friendly_error(conv['message'])}")
    doc_router.STATUS_HOOK = lambda t: br.log.emit(base, t)
    try:
        return case_documents.process_pending(base, data, convert, on_update, stop=lambda: job.stop_flag)
    finally:
        doc_router.STATUS_HOOK = None


def resume_documents(base, data, convert=None):
    """عند فتح القضية: عملية توقفت (أُغلق البرنامج أثناءها) تُستأنف تلقائياً بالخلفية. يرجع Job أو None."""
    if active_job(base) is not None or not case_documents.pending_docs(data):
        return None
    return start_job(base, data, convert_work(base, data, convert))


class UnknownKindsDialog(QDialog):
    """سؤال واحد لكل ما لم يتضح نوعه من محتواه: قائمة بكل الملفات معاً (لا نافذة لكل ملف)."""
    def __init__(self, docs, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("مستندات لم يتضح نوعها")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("قرأتُ الصفحة الأولى ولم يتضح نوع هذه المستندات — اختره مرة واحدة (أو اتركه):"))
        self.table = QTableWidget(len(docs), 3)
        self.table.setHorizontalHeaderLabels(["الملف", "نوعه", "توجيه القراءة"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._docs = docs
        for r, d in enumerate(docs):
            self.table.setItem(r, 0, QTableWidgetItem(d['orig_name']))
            k = QComboBox()
            k.addItem('— اتركه —', None)
            for lab in case_documents.CONTENT_KIND_LABELS:
                k.addItem(lab, lab)
            self.table.setCellWidget(r, 1, k)
            if d.get('needs_type'):
                t = QComboBox()
                t.addItem(PLACEHOLDER, None)
                for lab in doc_router.KNOWN_TYPES:
                    t.addItem(lab, lab)
                self.table.setCellWidget(r, 2, t)
        lay.addWidget(self.table, 1)
        ok = PrimaryButton("اعتماد")
        ok.clicked.connect(self.accept)
        lay.addWidget(ok)

    def result_maps(self):
        kinds, types = {}, {}
        for r, d in enumerate(self._docs):
            k = self.table.cellWidget(r, 1).currentData()
            if k:
                kinds[d['uid']] = k
            t = self.table.cellWidget(r, 2)
            if t is not None and t.currentData():
                types[d['uid']] = t.currentData()
        return kinds, types


# ---------- النافذة ----------

class FirstPageDialog(QDialog):
    """نوع غير معروف: الصفحة الأولى (صورة أو النص المقروء) وقائمة الأنواع ليختار الخبير. chosen = النوع بعد الاعتماد."""
    def __init__(self, base, doc, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("اختيار نوع المستند")
        self.setMinimumSize(560, 520)
        self.chosen = None
        lay = QVBoxLayout(self)
        why = QLabel(f"{doc['orig_name']} — {doc.get('type_reason', '')}")
        why.setWordWrap(True)
        why.setAlignment(th.ARIGHT)
        lay.addWidget(why)
        img = QLabel()
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = self._render_first(os.path.join(base, doc.get('file') or ''))
        if pm is not None:
            img.setPixmap(pm)
        else:
            img.setText(doc.get('first_text') or "(تعذّر عرض الصفحة الأولى)")
            img.setWordWrap(True)
        lay.addWidget(img, 1)
        self.combo = QComboBox()
        for t in doc_router.KNOWN_TYPES:
            self.combo.addItem(t, t)
        lay.addWidget(self.combo)
        row = QHBoxLayout()
        ok = PrimaryButton("اعتماد النوع")
        ok.clicked.connect(self._accept)
        cancel = SecondaryButton("إلغاء")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        row.addStretch()
        lay.addLayout(row)

    @staticmethod
    def _render_first(path):
        try:
            import fitz
            from PyQt6.QtGui import QPixmap
            doc = fitz.open(path)
            try:
                pix = doc[0].get_pixmap(dpi=70)
                pm = QPixmap()
                pm.loadFromData(pix.tobytes('png'))
                return pm
            finally:
                doc.close()
        except Exception:
            return None

    def _accept(self):
        self.chosen = self.combo.currentData()
        self.accept()


class DocumentsDialog(QDialog):
    AUTO_RUN = True          # الاختيار/السحب يبدأ النسخ والتصنيف والتحويل فوراً (اختبارات المرحلتين القديمة تطفئه)
    ASK_UNKNOWN = None       # fn(docs) -> (kinds, types) بدل نافذة السؤال (للاختبارات)
    PER_FILE_PORTFOLIO = False   # True في اللوحة المضمَّنة: كل ملف حافظة مستقلة
    PORTFOLIO_ASK = None     # مزوّد ضبط بيانات الحافظة؛ None = رخيص (Groq/OpenAI) لا جيميناي

    def __init__(self, base, data, parent=None, convert=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("إضافة مستندات القضية")
        self.setAcceptDrops(True)
        self._batch = set()                 # معرّفات مستندات هذه الجلسة (للعداد «N من M»)
        self.setMinimumSize(1180, 560)
        self.base, self.data, self._convert = base, live_data(base) or data, convert
        doc_router.ensure_defaults()            # أقسام [doc_types]/[doc_routing]/[gemini_limits] إن كانت ناقصة
        self._staged = []                   # [(مسار، QSpinBox)] ملفات مختارة لم تُستورد بعد
        self._rows = {}                     # uid -> صف الجدول
        if active_job(base) is None and case_documents.recover_running(self.data):
            case_documents._save(base, self.data)
        br = bridge()
        _OPEN.add(base)
        br.log.connect(self._on_log)
        br.update.connect(self._on_update)
        br.finished.connect(self._on_finished)

        lay = QVBoxLayout(self)
        help_lbl = QLabel("ⓘ " + PORTFOLIO_HELP)
        help_lbl.setWordWrap(True)
        help_lbl.setAlignment(th.ARIGHT)
        help_lbl.setStyleSheet(f"background:{th.BLUE_INFO_BG}; color:{th.BLUE_INFO_TEXT}; padding:8px 12px; "
                               f"border-radius:8px; font-size:12px;")
        lay.addWidget(help_lbl)

        sec = QLabel("بيانات الحافظة")
        sec.setStyleSheet(f"font-weight:bold; color:{th.NAVY}; font-size:13px;")
        sec.setAlignment(th.ARIGHT)
        lay.addWidget(sec)
        top = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._on_portfolio_changed)
        self.submitter = QLineEdit()
        self.submitter.setPlaceholderText("مقدِّم الحافظة — يُقترح تلقائياً من الصفحة الأولى ويمكن تعديله")
        self.submitter.editingFinished.connect(self._portfolio_edited)
        self.date = QDateEdit(QDate.currentDate())
        self.date.dateChanged.connect(lambda _d: self._portfolio_edited())
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setCalendarPopup(True)
        top.addWidget(QLabel("الحافظة:"))
        top.addWidget(self.combo)
        top.addWidget(self.submitter, 1)
        top.addWidget(self.date)
        lay.addLayout(top)

        sec2 = QLabel("اختر المستندات")
        sec2.setStyleSheet(f"font-weight:bold; color:{th.NAVY}; font-size:13px;")
        sec2.setAlignment(th.ARIGHT)
        lay.addWidget(sec2)
        self.drop = QFrame()
        self.drop.setStyleSheet(f"QFrame {{ border:2px dashed {th.BORDER}; border-radius:10px; background:{th.SURFACE}; }}")
        row = QHBoxLayout(self.drop)
        hint = QLabel("اسحب الملفات أو المجلد وأفلتها هنا — يبدأ النسخ والتحويل والتصنيف تلقائياً، أو")
        hint.setStyleSheet("border:none;")
        row.addWidget(hint)
        self.files_btn = SecondaryButton("اختيار ملفات")
        self.files_btn.clicked.connect(self._pick_files)
        self.folder_btn = SecondaryButton("اختيار مجلد")
        self.folder_btn.clicked.connect(self._pick_folder)
        self.add_btn = SecondaryButton("إضافة وتصنيف")
        self.add_btn.clicked.connect(self._start)
        self.import_btn = PrimaryButton("استيراد وتحويل")
        self.import_btn.clicked.connect(self._convert_pending)
        row.addWidget(self.files_btn)
        row.addWidget(self.folder_btn)
        row.addWidget(self.add_btn)
        row.addWidget(self.import_btn)
        row.addStretch()
        lay.addWidget(self.drop)
        self.add_btn.setVisible(not self.AUTO_RUN)
        self.import_btn.setVisible(not self.AUTO_RUN)
        sec3 = QLabel("المستندات المختارة")
        sec3.setStyleSheet(f"font-weight:bold; color:{th.NAVY}; font-size:13px;")
        sec3.setAlignment(th.ARIGHT)
        lay.addWidget(sec3)

        body = QHBoxLayout()
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["الحافظة", "م", "الملف", "توجيه القراءة", "المحرّك", "النوع (من المحتوى)",
                                              "التاريخ / الأطراف", "الحالة", ""])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(C_FILE, QHeaderView.ResizeMode.Stretch)
        for c in (C_TYPE, C_ENGINE, C_STATE):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        body.addWidget(self.table, 3)
        side = QFrame()
        side.setStyleSheet(f"QFrame {{ background:{th.SURFACE}; border:1px solid {th.BORDER}; border-radius:10px; }}")
        sl = QVBoxLayout(side)
        t = QLabel("ما يفعله البرنامج الآن")
        t.setStyleSheet(f"font-weight:bold; color:{th.NAVY}; border:none; font-size:13px;")
        t.setAlignment(th.ARIGHT)
        sl.addWidget(t)
        self.total_lbl = QLabel("")
        self.total_lbl.setStyleSheet(f"border:none; font-weight:bold; color:{th.NAVY}; font-size:13px;")
        self.total_lbl.setAlignment(th.ARIGHT)
        sl.addWidget(self.total_lbl)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(True)
        self.bar.setVisible(False)
        sl.addWidget(self.bar)
        self.files_lbl = QLabel("")
        self.files_lbl.setWordWrap(True)
        self.files_lbl.setAlignment(th.ARIGHT)
        self.files_lbl.setStyleSheet("border:none; font-size:12px;")
        sl.addWidget(self.files_lbl)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("ستظهر هنا خطوات النسخ والتحويل وأي خطأ بنص مفهوم.")
        self.log.setStyleSheet("border:none; font-size:12px;")
        sl.addWidget(self.log, 1)
        side.setMinimumWidth(280)
        body.addWidget(side, 1)           # آخر عنصر في تخطيط RTL = أقصى اليسار
        lay.addLayout(body, 1)

        lim = QLabel("ⓘ " + doc_router.limits_text())
        lim.setWordWrap(True)
        lim.setAlignment(th.ARIGHT)
        lim.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:11px; border:none;")
        lay.addWidget(lim)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none;")
        lay.addWidget(self.status)
        bot = QHBoxLayout()
        bot.addStretch()
        close = SecondaryButton("إغلاق")
        close.clicked.connect(self.accept)
        bot.addWidget(close)
        lay.addLayout(bot)
        self._fill_combo()
        self._render()
        self._sync_buttons()
        self._prog_timer = QTimer(self)
        self._prog_timer.setInterval(400)
        self._prog_timer.timeout.connect(self._refresh_progress)
        self._prog_timer.start()
        if active_job(base) is not None:
            self._batch |= {d['uid'] for _, d in case_documents.all_docs(self.data)
                            if d['convert']['state'] in ('pending', 'running')}
        self._refresh_progress()

    # ---------- السحب والإفلات ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()

    def add_paths(self, paths):
        """ملفات و/أو مجلدات (سحب أو اختيار) ← القائمة ثم البدء التلقائي."""
        out = []
        for p in paths:
            if os.path.isdir(p):
                out += self._walk(p)
            elif os.path.isfile(p):
                out.append(p)
        self._stage(out)

    @staticmethod
    def _walk(folder):
        paths = []
        for root, _dirs, names in os.walk(folder):
            for n in sorted(names):
                if os.path.splitext(n)[1].lower() in case_documents.SUPPORTED and not n.startswith('~$'):
                    paths.append(os.path.join(root, n))
        return paths

    # ---------- العداد الحي ----------
    def progress_model(self):
        return case_documents.batch_progress(self.data, self._batch)

    def _refresh_progress(self):
        if not self._batch:
            self.total_lbl.setText("")
            self.bar.setVisible(False)
            self.files_lbl.setText("")
            return
        pm = self.progress_model()
        self.total_lbl.setText(f"{pm['done']} من {pm['total']}")
        self.bar.setVisible(True)
        self.bar.setValue(pm['percent'])
        lines = []
        for name, st, pct in pm['files']:
            mark = {'done': '✓', 'failed': '✗', 'running': '◐'}.get(st, '○')
            lines.append(f"{mark} {name} — " + (f"{pct}%" if st == 'running' else STATE_TEXT.get(st, st)))
        self.files_lbl.setText('\n'.join(lines[-12:]))

    # ---------- الحافظة ----------
    def _fill_combo(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        for p in self.data['portfolios']:
            self.combo.addItem(f"{p['id']} — {p['submitter']}", p['id'])
        self.combo.addItem("حافظة جديدة…", NEW)
        self.combo.setCurrentIndex(self.combo.count() - 1 if not self.data['portfolios'] else 0)
        self.combo.blockSignals(False)
        self._on_portfolio_changed()

    def _on_portfolio_changed(self):
        pid = self.combo.currentData()
        p = next((x for x in self.data['portfolios'] if x['id'] == pid), None)
        for w in (self.submitter, self.date):
            w.blockSignals(True)
        if p is not None:                       # الحافظة القائمة: مقدّمها وتاريخها قابلان للتعديل
            self.submitter.setText(p['submitter'])
            d = QDate.fromString(p.get('date') or '', "yyyy-MM-dd")
            if d.isValid():
                self.date.setDate(d)
        else:
            self.submitter.clear()
        for w in (self.submitter, self.date):
            w.blockSignals(False)
        self._renumber_staged()

    def _portfolio_edited(self):
        pid = self.combo.currentData()
        if pid == NEW or not pid or not self.submitter.text().strip():
            return
        try:
            case_documents.update_portfolio(self.base, self.data, pid, self.submitter.text(),
                                            self.date.date().toString("yyyy-MM-dd"))
        except case_model.StepError:
            return
        self.combo.setItemText(self.combo.currentIndex(), f"{pid} — {self.submitter.text().strip()}")

    # ---------- اختيار الملفات ----------
    def _pick_files(self):
        exts = ' '.join('*' + e for e in case_documents.SUPPORTED)
        paths, _ = QFileDialog.getOpenFileNames(self, "اختر مستندات الحافظة", "", f"مستندات ({exts});;كل الملفات (*)")
        self._stage(paths)

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "اختر مجلد المستندات")
        if not folder:
            return
        paths = self._walk(folder)
        if not paths:
            self.status.setText("لا توجد في المجلد مستندات مدعومة (PDF/صور/Word/نص).")
            return
        self._stage(paths)

    def _stage(self, paths):
        """يضيف الجديد إلى القائمة؛ ما سبق تحويله لا يُضاف ويُذكر في اللوحة."""
        if not paths:
            return
        staged_paths = {p for p, _ in self._staged}
        skipped = 0
        for path, st, _doc in case_documents.classify_files(
                self.data, paths, self.combo.currentData() if self.combo.currentData() != NEW else None):
            if path in staged_paths:
                continue
            if st in ('done', 'failed', 'pending'):
                skipped += 1
                self._say(f"«{os.path.basename(path)}» موجود سابقاً ({STATE_TEXT.get(st, st)}) — لن يُضاف مرة ثانية.")
                continue
            sp = QSpinBox()
            sp.setRange(1, 9999)
            self._staged.append((path, sp))
        self._renumber_staged()
        self._render()
        self._sync_buttons()
        if skipped:
            self.status.setText(f"تم تخطي {skipped} ملفاً سبق استيراده.")
        if self.AUTO_RUN and self._staged and not self._busy():
            self._start()

    def _renumber_staged(self):
        pid = self.combo.currentData()
        start = 1
        if pid != NEW:
            p = next((x for x in self.data['portfolios'] if x['id'] == pid), None)
            start = max((d['no'] for d in p['docs']), default=0) + 1 if p else 1
        for i, (_, sp) in enumerate(self._staged):
            sp.setValue(start + i)

    # ---------- التشغيل ----------
    def _busy(self):
        return active_job(self.base) is not None

    def _sync_buttons(self):
        busy = self._busy()
        self.add_btn.setEnabled(bool(self._staged) and not busy)
        self.import_btn.setEnabled(bool(case_documents.pending_docs(self.data)) and not busy)
        self.files_btn.setEnabled(not busy)
        self.folder_btn.setEnabled(not busy)
        for r in range(self.table.rowCount()):
            for c in (C_TYPE, C_ENGINE, C_ACTION):
                w = self.table.cellWidget(r, c)
                if w is not None and not isinstance(w, QSpinBox):
                    w.setEnabled(not busy and not w.property('locked'))

    def _start(self):
        """المرحلة 1: نسخ الملفات المختارة وتصنيفها (OCR الصفحة الأولى + قواعد). لا تحويل هنا."""
        if self._busy() or not self._staged:
            return
        if self.combo.currentData() == NEW and not self.submitter.text().strip() and not self.AUTO_RUN:
            QMessageBox.warning(self, "الحافظة", "اكتب اسم مقدِّم الحافظة.")
            return
        nos = [sp.value() for _, sp in self._staged]
        if len(set(nos)) != len(nos):
            QMessageBox.warning(self, "الأرقام", "أرقام المستندات مكرّرة داخل الدفعة.")
            return
        pid = self.combo.currentData()
        typed_who = self.submitter.text().strip()
        typed_date = self.date.date().toString("yyyy-MM-dd")
        items = [{'src': p, 'no': sp.value()} for p, sp in self._staged]
        base, data, convert, auto = self.base, self.data, self._convert, self.AUTO_RUN
        portfolio_ask = self.PORTFOLIO_ASK
        per_file = self.PER_FILE_PORTFOLIO

        def work(job, br):
            br.log.emit(base, f"نسخ {len(items)} ملفاً وتصنيفها بقراءة الصفحة الأولى (المحتوى لا الاسم)…")
            cache = {}

            def classify(path):
                if path not in cache:
                    cache[path] = case_documents.CLASSIFIER(path)
                return cache[path]
            # لوحة الصفحة: كل ملف حافظة مستقلة يُعرف مقدّمها وتاريخها من صفحته الأولى (لا يرث حافظة غيره)
            groups = [[it] for it in items] if (per_file and pid == NEW and not typed_who) else [items]
            targets, added = [], []
            for grp in groups:
                target = pid
                if target == NEW:
                    who, when = typed_who, typed_date
                    if not who:                  # اقتراح المقدّم والتاريخ من الصفحة الأولى لأول مستند
                        first = next((it['src'] for it in grp
                                      if os.path.splitext(it['src'])[1].lower() not in case_documents.TEXT_EXTS), None)
                        snippet = (classify(first).get('snippet') or '') if first else ''
                        s_who, s_date = case_documents.suggest_portfolio(snippet)
                        who = s_who or 'لم يتضح من الصفحة الأولى'
                        when = s_date or when
                        br.log.emit(base, f"اقترحتُ مقدّم الحافظة «{who}» وتاريخها {when} من الصفحة الأولى.")
                    newp = case_documents.add_portfolio(data, who, when)
                    newp['auto_meta'] = not typed_who      # اقتراح آلي ← يُضبط من الصفحة الأولى بعد التحويل
                    target = newp['id']
                targets.append(target)
                added += case_documents.add_files(base, data, target, grp, classify)
            target = targets[-1]
            for d in added:
                if d['convert']['state'] == 'failed':
                    br.log.emit(base, f"«{d['orig_name']}»: {friendly_error(d['convert']['message'])}")
                elif d.get('engine') == doc_router.ENGINE_TEXT:
                    br.log.emit(base, f"«{d['orig_name']}» ملف نصي ← {d['doc_type']} — لا يحتاج تحويل (نُسخ كما هو).")
                else:
                    br.log.emit(base, f"«{d['orig_name']}» ← {d['doc_type']} (ثقة {d['type_conf']:.0%}) — "
                                      f"{d['type_reason']}")
                br.log.emit(base, f"«{d['orig_name']}»: {d.get('kind', '')}"
                                  + (f" بتاريخ {d['doc_date']}" if d.get('doc_date') else '')
                                  + (f" — الأطراف: {'، '.join(d['parties'])}" if d.get('parties') else ''))
            br.update.emit(base, '*', None)
            held = sum(1 for d in added if d.get('needs_type'))
            res = {'total': len(added), 'phase': 'classify', 'held': held, 'pid': target}
            if auto:                              # بلا زر: التحويل يتبع التصنيف مباشرة
                res = dict(_run_pending(job, br, base, data, convert), phase='auto', held=held, pid=target)
                for t in targets:
                    got = case_documents.refine_portfolio(base, data, t, portfolio_ask)
                    if got:
                        br.log.emit(base, got[2])
                        res['refined'] = True
            return res
        self._staged = []
        if start_job(base, data, work) is None:
            return
        self.status.setText("⏳ جارٍ النسخ والتصنيف والتحويل في الخلفية — تابع اللوحة الجانبية."
                            if self.AUTO_RUN else "⏳ جارٍ التصنيف في الخلفية…")
        self._render()
        self._sync_buttons()

    def _convert_pending(self):
        """المرحلة 2: تحويل الجاهز فقط (الأنواع المعروفة) بالمحرّك المعيَّن لكل ملف."""
        if self._busy():
            return
        self._batch |= {d['uid'] for d in case_documents.pending_docs(self.data)}
        if start_job(self.base, self.data, convert_work(self.base, self.data, self._convert)) is None:
            return
        self.status.setText("⏳ جارٍ التحويل في الخلفية — يمكنك متابعة اللوحة الجانبية.")
        self._render()
        self._sync_buttons()

    def _ask_unknown_once(self):
        """ما لم يتضح نوعه من محتواه يُسأل عنه مرة واحدة (نافذة واحدة لكل الملفات). يرجع هل صار شيء جاهزاً للتحويل."""
        docs = case_documents.unknown_kind_docs(self.data)
        ids = {d['uid'] for d in docs}
        docs += [d for _, d in case_documents.all_docs(self.data)
                 if d.get('needs_type') and d['convert']['state'] == 'pending' and d['uid'] not in ids
                 and not d.get('kind_asked')]
        if not docs:
            return False
        if self.ASK_UNKNOWN is not None:
            kinds, types = self.ASK_UNKNOWN(docs)
        else:
            dlg = UnknownKindsDialog(docs, self)
            dlg.exec()
            kinds, types = dlg.result_maps()
        case_documents.set_kinds(self.base, self.data, kinds)
        for d in docs:
            d['kind_asked'] = True
        ready = False
        for uid, t in types.items():
            try:
                case_documents.set_doc_type(self.base, self.data, uid, t)
                ready = True
            except case_model.StepError as e:
                self._say(str(e))
        case_documents._save(self.base, self.data)
        self._render()
        self._sync_buttons()
        return ready

    # ---------- تغيير النوع/المحرّك يدوياً (قبل التحويل) ----------
    def _on_type_chosen(self, uid, combo):
        t = combo.currentData()
        if not t:
            return
        try:
            case_documents.set_doc_type(self.base, self.data, uid, t)
        except case_model.StepError as e:
            self.status.setText(str(e))
        else:
            self._say(f"اختار الخبير نوع «{t}» ← المحرّك: {doc_router.ENGINE_LABELS.get(doc_router.engine_for(t), '')}")
        self._render()
        self._sync_buttons()

    def _on_engine_chosen(self, uid, combo):
        try:
            case_documents.set_doc_engine(self.base, self.data, uid, combo.currentData())
        except case_model.StepError as e:
            self.status.setText(str(e))
        else:
            self._say(f"غيّر الخبير المحرّك إلى «{combo.currentText()}».")

    def _show_first_page(self, uid):
        _p, d = case_documents.find_doc(self.data, uid)
        dlg = FirstPageDialog(self.base, d, self)
        if dlg.exec() and dlg.chosen:
            try:
                case_documents.set_doc_type(self.base, self.data, uid, dlg.chosen)
            except case_model.StepError as e:
                self.status.setText(str(e))
            self._render()
            self._sync_buttons()

    def _retry(self, uid):
        if self._busy():
            return
        base, data, convert = self.base, self.data, self._convert
        _p, d = case_documents.find_doc(data, uid)
        name = d['orig_name']

        def work(job, br):
            br.log.emit(base, f"إعادة محاولة «{name}»…")

            def on_update(u, conv):
                br.update.emit(base, u, conv)
                if conv['state'] == 'done':
                    br.log.emit(base, f"اكتمل «{name}».")
                elif conv['state'] == 'failed':
                    br.log.emit(base, f"فشل «{name}» مرة أخرى: {friendly_error(conv['message'])}")
            case_documents.reconvert(base, data, uid, convert, on_update)
            return {'total': 1}
        if start_job(base, data, work) is not None:
            self._render()
            self._sync_buttons()

    def _reread(self, uid):
        """إعادة قراءة صحيفة/حكم ضعيف الجودة بأقوى محرّك مضبوط."""
        if self._busy():
            return
        base, data, convert = self.base, self.data, self._convert
        _p, d = case_documents.find_doc(data, uid)
        name = d['orig_name']
        if case_documents.stronger_engine(d) is None:
            self.status.setText("لا يوجد محرّك أقوى مضبوط — اضبط مفتاح Gemini أو OCR الخارجي من الإعدادات.")
            return

        def work(job, br):
            br.log.emit(base, f"إعادة قراءة «{name}» بمحرّك أقوى…")

            def on_update(u, conv):
                br.update.emit(base, u, conv)
                if conv['state'] == 'done':
                    br.log.emit(base, f"اكتملت إعادة قراءة «{name}».")
                elif conv['state'] == 'failed':
                    br.log.emit(base, f"فشلت إعادة قراءة «{name}»: {friendly_error(conv['message'])}")
            case_documents.reread_stronger(base, data, uid, convert, on_update)
            return {'total': 1}
        if start_job(base, data, work) is not None:
            self._render()
            self._sync_buttons()

    def _redo(self, uid, engine):
        """🔄 إعادة عمل OCR/markdown بمحرّك يختاره الخبير. لا خروج صامت: عمل جارٍ ← رسالة؛ الفشل ← رسالة عربية."""
        if self._busy():
            self._alert("إعادة القراءة", "يجري الآن عمل آخر على مستندات هذه القضية — انتظر حتى ينتهي ثم أعد المحاولة.")
            return
        base, data, convert = self.base, self.data, self._convert
        _p, d = case_documents.find_doc(data, uid)
        name, label = d['orig_name'], doc_router.ENGINE_LABELS.get(engine, engine)
        self._redo_watch = (uid, name, label)

        def work(job, br):
            br.log.emit(base, f"إعادة عمل markdown لـ«{name}» بمحرّك {label}…")

            def on_update(u, conv):
                br.update.emit(base, u, conv)
                if conv['state'] == 'done':
                    br.log.emit(base, f"اكتملت إعادة «{name}» بمحرّك {label}.")
                elif conv['state'] == 'failed':
                    br.log.emit(base, f"فشلت إعادة «{name}» بمحرّك {label}: {friendly_error(conv['message'])}")
            case_documents.reconvert_with(base, data, uid, engine, convert, on_update)
            return {'total': 1}
        if start_job(base, data, work) is not None:
            self.status.setText(f"⏳ جارٍ إعادة قراءة «{name}» بمحرّك {label}…")
            self._render()
            self._sync_buttons()
        else:
            self._redo_watch = None
            self._alert("إعادة القراءة", "تعذّر بدء إعادة القراءة: يجري عمل آخر على مستندات هذه القضية.")

    def _alert(self, title, text, bad=False):
        """رسالة بنمط فاتح صريح ومن النافذة العليا (النمط الشفاف للّوحة المضمَّنة يجعل الحوارات الفرعية سوداء)."""
        box = QMessageBox(QMessageBox.Icon.Warning if bad else QMessageBox.Icon.Information, title, text,
                          QMessageBox.StandardButton.Ok, self.window() if self.window() is not self else self)
        box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        box.setStyleSheet("QMessageBox{background:#ffffff;} QLabel{color:#1b2a3a; background:transparent; font-size:13px;}"
                          "QPushButton{background:#ffffff; color:#1b2a3a; border:1px solid #c9d3dc; border-radius:6px;"
                          "padding:4px 16px;}")
        if self.ALERTS:
            box.exec()
        self.last_alert = (title, text)
        return box

    def _redo_finished(self, res):
        """بعد 🔄: نجاح ← سطر الحالة؛ فشل (حالة المستند أو استثناء العمل) ← رسالة عربية واضحة."""
        watch, self._redo_watch = getattr(self, '_redo_watch', None), None
        if not watch:
            return
        uid, name, label = watch
        try:
            _p, d = case_documents.find_doc(self.data, uid)
            conv = d['convert']
        except Exception:
            conv = {}
        if isinstance(res, Exception) or conv.get('state') == 'failed':
            why = friendly_error(str(res) if isinstance(res, Exception) else conv.get('message') or '')
            self.status.setText(f"تعذّرت إعادة قراءة «{name}»: {why}")
            self._alert("تعذّرت إعادة القراءة", f"تعذّرت إعادة قراءة «{name}» بمحرّك {label}.\n\nالسبب: {why}\n\n"
                        "جرّب محرّكاً آخر من زر 🔄، أو تأكد من ضبط مفتاح المحرّك في الإعدادات.", bad=True)
        elif conv.get('state') == 'done':
            warn = d.get('warning') or ''
            msg = f"اكتملت إعادة قراءة «{name}» بمحرّك {label} ✓" + (f" — {warn}" if warn else '')
            self.status.setText(msg)
            QTimer.singleShot(0, lambda: self.status.setText(msg))      # بعد الرسالة العامة «اكتمل.»

    # ---------- الإشارات (خيط الواجهة) ----------
    def _say(self, text):
        self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    def _on_log(self, base, text):
        if base == self.base:
            self._say(text)

    def _on_update(self, base, uid, conv):
        if base != self.base:
            return
        if uid == '*':
            self._batch |= {d['uid'] for _, d in case_documents.all_docs(self.data)
                            if d['convert']['state'] in ('pending', 'running')}
        else:
            self._batch.add(uid)
        r = self._rows.get(uid)
        if uid == '*' or r is None:
            self._render()
        else:
            self._set_state_cell(r, self._state_of(uid), conv)

    ALERTS = True                 # الاختبارات تطفئ النوافذ المنبثقة (تبقى last_alert)

    def _on_finished(self, base, res):
        if base != self.base:
            return
        self._render()
        self._sync_buttons()
        if getattr(self, '_redo_watch', None):
            self._redo_finished(res)
            if isinstance(res, Exception):
                return
        if isinstance(res, Exception):
            self.status.setText(f"تعذّر التنفيذ: {friendly_error(str(res) or res.__class__.__name__)}")
            self._say(f"توقّف العمل: {friendly_error(str(res) or res.__class__.__name__)}")
            return
        if res.get('pid') and (self.combo.currentData() == NEW or res.get('refined')):      # الحافظة الجديدة باقتراحها ← قابلة للتعديل
            self._fill_combo()
            i = self.combo.findData(res['pid'])
            if i >= 0:
                self.combo.setCurrentIndex(i)
        self._refresh_progress()
        if res.get('phase') == 'auto':
            msg = (f"اكتمل: {res.get('done', 0)} محوَّل، {res.get('failed', 0)} فاشل من {res.get('total', 0)}."
                   if res.get('total') else "تمت الإضافة.")
            self.status.setText(msg)
            self._say(msg)
            if self._ask_unknown_once():
                self._convert_pending()
            return
        if res.get('phase') == 'classify':
            msg = (f"تمت إضافة {res['total']} مستنداً وتصنيفها — راجع النوع والمحرّك ثم اضغط «استيراد وتحويل»."
                   + (f" {res['held']} نوعه غير معروف: اختره أولاً." if res.get('held') else ''))
        elif res.get('total', 0) > 1 or res.get('done') or res.get('failed'):
            msg = f"اكتمل: {res.get('done', 0)} محوَّل، {res.get('failed', 0)} فاشل" + (
                f"، {res['left']} بقي للمرة القادمة" if res.get('left') else '') + f" من {res['total']}."
        else:
            msg = "اكتمل."
        self.status.setText(msg)
        self._say(msg)

    # ---------- العرض ----------
    def _state_of(self, uid):
        try:
            return case_documents.find_doc(self.data, uid)[1]['convert']
        except case_model.StepError:
            return {'state': 'pending', 'message': ''}

    def _is_original(self, uid):
        try:
            return case_documents.find_doc(self.data, uid)[1].get('origin') == 'original'
        except case_model.StepError:
            return False

    def _set_state_cell(self, row, conv, override=None):
        conv = override or conv
        st = conv['state']
        text = STATE_TEXT.get(st, st)
        if st == 'running' and conv.get('progress'):
            text = f"جارٍ التحويل {conv['progress']}%"
        uid_item = self.table.item(row, C_PORT)
        if st == 'done' and uid_item is not None and self._is_original(uid_item.data(Qt.ItemDataRole.UserRole)):
            text = STATE_ORIGINAL
        if st == 'failed' and conv.get('message'):
            text += f" — {friendly_error(conv['message'])}"
        it = QTableWidgetItem(text)
        if st == 'failed':
            it.setForeground(QColor(th.DANGER))
        elif st == 'done':
            it.setForeground(QColor(th.EMERALD_TEXT))
        self.table.setItem(row, C_STATE, it)
        self.table.removeCellWidget(row, C_ACTION)
        uid0 = self.table.item(row, C_PORT).data(Qt.ItemDataRole.UserRole)
        _p0, d0 = case_documents.find_doc(self.data, uid0)
        qw = d0.get('quality_warning') if st == 'done' else ''
        if qw:
            it.setForeground(QColor(th.DANGER))
            it.setText(f"{text} — ⚠ {doc_router.WEAK_MESSAGE}")
            it.setToolTip(qw)
            b = QPushButton("أعد القراءة بمحرك أقوى")
            b.clicked.connect(lambda _=False, u=uid0: self._reread(u))
            b.setEnabled(not self._busy())
            self.table.setCellWidget(row, C_ACTION, b)
        elif st == 'failed':
            b = QPushButton("إعادة المحاولة")
            uid = self.table.item(row, C_PORT).data(Qt.ItemDataRole.UserRole)
            b.clicked.connect(lambda _=False, u=uid: self._retry(u))
            b.setEnabled(not self._busy())
            self.table.setCellWidget(row, C_ACTION, b)

    def _type_engine_cells(self, r, d):
        """عمودا «نوع المستند» و«المحرّك»: قائمتان قبل التحويل، ونص بعده. غير المعروف بلون تنبيه وزر الصفحة الأولى."""
        state = d['convert']['state']
        editable = (state in ('pending', 'failed') and bool(d.get('file'))
                    and d.get('engine') != doc_router.ENGINE_TEXT)
        dtype, engine = d.get('doc_type') or '', d.get('engine') or ''
        if not dtype:                                # مستند قديم قبل ميزة التصنيف
            self.table.setItem(r, C_TYPE, QTableWidgetItem('—'))
            self.table.setItem(r, C_ENGINE, QTableWidgetItem(doc_router.ENGINE_LABELS[doc_router.ENGINE_LOCAL]))
            return
        tip = f"{d.get('type_reason', '')} (ثقة {d.get('type_conf', 0):.0%})" + (" — اختيار يدوي" if d.get('manual') else "")
        if not editable:
            it = QTableWidgetItem(dtype)
            it.setToolTip(tip)
            self.table.setItem(r, C_TYPE, it)
            self.table.setItem(r, C_ENGINE, QTableWidgetItem(doc_router.ENGINE_LABELS.get(engine, '')))
            return
        tc = QComboBox()
        if d.get('needs_type'):
            tc.addItem(PLACEHOLDER, None)
            tc.setStyleSheet(f"background:{th.AMBER_BG}; color:{th.AMBER_TEXT};")
        for t in doc_router.KNOWN_TYPES:
            tc.addItem(t, t)
        tc.setCurrentIndex(0 if d.get('needs_type') else tc.findData(dtype))
        tc.setToolTip(tip)
        tc.currentIndexChanged.connect(lambda _i, u=d['uid'], c=tc: self._on_type_chosen(u, c))
        self.table.setCellWidget(r, C_TYPE, tc)
        ec = QComboBox()
        for e in doc_router.ENGINES:
            ec.addItem(doc_router.ENGINE_LABELS[e], e)
        ec.setCurrentIndex(max(0, ec.findData(engine)))
        ec.setProperty('locked', bool(d.get('needs_type')))     # يُفتح باختيار النوع أولاً
        ec.setEnabled(not d.get('needs_type'))
        ec.currentIndexChanged.connect(lambda _i, u=d['uid'], c=ec: self._on_engine_chosen(u, c))
        self.table.setCellWidget(r, C_ENGINE, ec)
        if d.get('needs_type') and state == 'pending':
            b = QPushButton("الصفحة الأولى…")
            b.clicked.connect(lambda _=False, u=d['uid']: self._show_first_page(u))
            self.table.setCellWidget(r, C_ACTION, b)

    def _render(self):
        self._rows = {}
        docs = list(case_documents.all_docs(self.data))
        order = {p['id']: i for i, p in enumerate(self.data['portfolios'])}
        self.table.setRowCount(len(docs) + len(self._staged))
        self.table.clearContents()
        for r, (p, d) in enumerate(docs):
            bg, fg = portfolio_colors(p['submitter'], order[p['id']])
            meta = ' — '.join(x for x in (d.get('doc_date') or '', '، '.join(d.get('parties') or [])) if x)
            for c, v in ((C_PORT, f"{p['id']} — {p['submitter']}"), (C_NO, d['no']), (C_FILE, d['orig_name']),
                         (C_GUESS, d.get('kind') or d['type']), (C_CONTRACT, meta or d['contract'])):
                it = QTableWidgetItem(str(v))
                it.setBackground(QColor(bg))
                it.setForeground(QColor(fg))
                self.table.setItem(r, c, it)
            self.table.item(r, C_PORT).setData(Qt.ItemDataRole.UserRole, d['uid'])
            self._set_state_cell(r, d['convert'])
            self._type_engine_cells(r, d)
            self._rows[d['uid']] = r
        pid = self.combo.currentData()
        who = next((p['submitter'] for p in self.data['portfolios'] if p['id'] == pid), self.submitter.text())
        bg, fg = portfolio_colors(who, order.get(pid, len(order)))
        for k, (path, sp) in enumerate(self._staged):
            r = len(docs) + k
            lbl = f"{pid} — {who}" if pid != NEW else (who or "حافظة جديدة")
            for c, v in ((C_PORT, lbl), (C_FILE, os.path.basename(path))):
                it = QTableWidgetItem(v)
                it.setBackground(QColor(bg))
                it.setForeground(QColor(fg))
                it.setToolTip(path)
                self.table.setItem(r, c, it)
            self.table.setCellWidget(r, C_NO, sp)
            self.table.setItem(r, C_STATE, QTableWidgetItem(STATE_TEXT['staged']))

    # ---------- الإغلاق ----------
    def done(self, r):
        job = active_job(self.base)     # الإغلاق لا يوقف العمل: يتابع بالخلفية (ويُستأنف عند فتح القضية إن أُغلق البرنامج)
        self._prog_timer.stop()
        if job is None and self._staged:
            self._say("لم تُستورد الملفات المختارة بعد.")
        for sig, slot in ((bridge().log, self._on_log), (bridge().update, self._on_update),
                          (bridge().finished, self._on_finished)):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass
        _OPEN.discard(self.base)
        from qt_review_dialogs import show_saved_toast
        show_saved_toast(self.parent() or self, "تم الحفظ ✓" if job is None else "تم الحفظ — التحويل يتابع بالخلفية")
        super().done(r)
