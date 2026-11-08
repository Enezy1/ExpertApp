# ===== qt_review_dialogs.py — نوافذ المراجعة الفعلية (إصلاحات 2026-10-17) =====
# SubjectReviewDialog: نص الموضوع كاملاً مع تعديل مباشر وزر «اعتماد» (لا تتحول الحالة إلى «راجعها الخبير» بغيره).
# MinutesEditDialog: «تعديل» خطوة الإجراءات — المحاضر المأخوذة تلقائياً (استبعاد/إعادة/إضافة) وحضور كل طرف
#                    (تلقائي/حضر/لم يحضر). لا تأكيد منفصل: الاستخراج آلي وهذه للتعديل فقط. المنطق في case_procedures.py.
# show_saved_toast: رسالة صغيرة «تم الحفظ» تختفي وحدها.
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QMessageBox, QComboBox, QCheckBox, QWidget,
    QFileDialog, QScrollArea, QFrame,
)

import qt_theme as th
from qt_bidi import BidiPlainTextEdit
from qt_widgets import PrimaryButton, SecondaryButton

import case_model
import case_procedures as cp
import case_subject_mission as sm
from case_subject_telecom import TODO


def show_saved_toast(parent, text="تم الحفظ ✓", msec=2200):
    """رسالة صغيرة أعلى النافذة الأم تختفي وحدها (لا تعترض الإغلاق)."""
    lbl = QLabel(text, None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
    lbl.setStyleSheet(f"background:{th.NAVY}; color:white; padding:8px 18px; border-radius:8px; font-size:13px;")
    lbl.adjustSize()
    if parent is not None and parent.isVisible():
        g = parent.frameGeometry()
        lbl.move(g.center().x() - lbl.width() // 2, g.top() + 40)
    else:
        from PyQt6.QtGui import QGuiApplication
        g = QGuiApplication.primaryScreen().availableGeometry()
        lbl.move(g.center().x() - lbl.width() // 2, g.top() + 60)
    lbl.show()
    _TOASTS.append(lbl)
    QTimer.singleShot(msec, lambda: (lbl.close(), _TOASTS.remove(lbl) if lbl in _TOASTS else None))


_TOASTS = []


class SubjectReviewDialog(QDialog):
    """يعرض الموضوع كاملاً قابلاً للتعديل. «حفظ» لا يغيّر الاعتماد؛ «اعتماد» وحده يجعلها «راجعها الخبير»."""

    def __init__(self, base, data, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("مراجعة الموضوع")
        self.setMinimumSize(620, 420)
        self.base, self.data = base, data
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("اقرأ نص الموضوع كاملاً، عدّله مباشرة إن لزم، ثم اضغط «اعتماد»:"))
        self.text = BidiPlainTextEdit(data.get('subject') or '')
        lay.addWidget(self.text, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{th.AMBER_TEXT}; font-size:12px; border:none;")
        if TODO in (data.get('subject') or ''):
            self.note.setText(f"في النص «{TODO}» (لم يرد في الصحيفة أو لم يُتحقق منه) — أكمله ثم اعتمد.")
        lay.addWidget(self.note)
        self.reread_requested = False
        qw = data.get('subject_quality_warning')
        if qw:
            self.quality = QLabel(f"⚠ جودة قراءة الصحيفة ضعيفة، أعد قراءتها بمحرك أقوى — {qw}")
            self.quality.setWordWrap(True)
            self.quality.setStyleSheet(f"color:{th.DANGER}; font-size:12px; border:none;")
            lay.addWidget(self.quality)
            rb = SecondaryButton("أعد القراءة بمحرك أقوى")
            rb.clicked.connect(self._reread)
            lay.addWidget(rb)
        row = QHBoxLayout()
        ok = PrimaryButton("اعتماد")
        ok.clicked.connect(lambda: self._save(True))
        save = SecondaryButton("حفظ دون اعتماد")
        save.clicked.connect(lambda: self._save(False))
        close = SecondaryButton("إغلاق")
        close.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(save)
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)

    def _reread(self):
        self.reread_requested = True
        self.reject()

    def _save(self, approve):
        txt = self.text.toPlainText().strip()
        try:
            changed = txt != (self.data.get('subject') or '').strip()
            if changed or case_model.state(self.data, 'subject') not in case_model.OK_STATES:
                sm.set_subject(self.base, self.data, txt)
            if approve:
                sm.review_subject(self.base, self.data)
        except case_model.StepError as e:
            QMessageBox.warning(self, "الموضوع", str(e))
            return
        stale = case_model.stale_labels(self.data, 'subject')
        if changed and stale and not approve:
            self.note.setText("عُدِّل الموضوع: " + "، ".join(stale) + " تحتاج تحديثاً.")
        show_saved_toast(self)
        if approve:
            self.accept()


class MinutesEditDialog(QDialog):
    """«تعديل» الإجراءات: كل تغيير يُحفظ فوراً ويعيد الحساب (case_procedures.exclude_minute/add_minute/set_attendance)."""
    AUTO, YES, NO = 0, 1, 2

    def __init__(self, base, data, parent=None, ask=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("الإجراءات — تعديل")
        self.setMinimumSize(560, 460)
        self.base, self.data, self._ask = base, data, ask
        lay = QVBoxLayout(self)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setAlignment(th.ARIGHT)
        self.summary.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:13px; border:none;")
        lay.addWidget(self.summary)
        lay.addWidget(QLabel("<b>المحاضر التي أُخذت</b> (أزل العلامة لاستبعاد ملف أُخذ بالخطأ):"))
        self.files_host = QWidget()
        self.files = QVBoxLayout(self.files_host)
        self.files.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.files_host)
        scroll.setMinimumHeight(120)
        lay.addWidget(scroll, 1)
        lay.addWidget(QLabel("<b>الحضور</b> (حضوره في محضر واحد يكفي ليُكتب «حضر»):"))
        self.att_host = QWidget()
        self.att = QVBoxLayout(self.att_host)
        self.att.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.att_host)
        row = QHBoxLayout()
        add = SecondaryButton("إضافة محضر آخر")
        add.clicked.connect(self._add)
        close = PrimaryButton("تم")
        close.clicked.connect(self.accept)
        row.addWidget(add)
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        self._boxes, self._combos = [], []
        self._reload()

    def _clear(self, lay):
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _reload(self):
        self.summary.setText(cp.checks_text(self.data).replace('\n', '<br>'))
        self._clear(self.files)
        self._boxes = []
        cands = cp.all_candidates(self.data, base=self.base)
        if not cands:
            self.files.addWidget(QLabel("لم يُعثر على محاضر — «إضافة محضر آخر»."))
        for path, name, excluded in cands:
            cb = QCheckBox(name)
            cb.setToolTip(path)
            cb.setChecked(not excluded)
            cb.toggled.connect(lambda on, p=path: self._toggle(p, on))
            self.files.addWidget(cb)
            self._boxes.append(cb)
        self.files.addStretch()
        self._clear(self.att)
        self._combos = []
        att = (self.data.get('procedures') or {}).get('attendance') or {}
        result = att.get('result') or []
        ov = att.get('overrides') or {}
        for i, ((label, _f), r) in enumerate(zip(cp.party_labels(result), result)):
            host = QWidget()
            h = QHBoxLayout(host)
            h.setContentsMargins(0, 0, 0, 0)
            name = QLabel(f"{label}: {r['name']}")
            name.setWordWrap(True)
            combo = QComboBox()
            auto = 'لم يتأكد' if not r['certain'] or str(i) in ov else ('حضر' if r['present'] else 'لم يحضر')
            if str(i) in ov:
                auto = 'من المحاضر'
            combo.addItems([f"تلقائي ({auto})", "حضر", "لم يحضر"])
            combo.setCurrentIndex(self.AUTO if str(i) not in ov else self.YES if ov[str(i)] else self.NO)
            combo.currentIndexChanged.connect(lambda v, i=i: self._set(i, v))
            h.addWidget(name, 1)
            h.addWidget(combo)
            self.att.addWidget(host)
            self._combos.append(combo)
        if not result:
            self.att.addWidget(QLabel("لم تُعرف الأطراف بعد (لا محاضر مقروءة ولا بيانات أطراف)."))

    def _apply(self, fn):
        try:
            fn()
        except case_model.StepError as e:
            QMessageBox.warning(self, "الإجراءات", str(e))
        QTimer.singleShot(0, self._reload)          # لا نحذف عناصر الواجهة داخل إشارتها

    def _toggle(self, path, on):
        self._apply(lambda: cp.exclude_minute(self.base, self.data, path, excluded=not on, ask=self._ask))

    def _set(self, index, choice):
        val = None if choice == self.AUTO else choice == self.YES
        self._apply(lambda: cp.set_attendance(self.base, self.data, index, val, ask=self._ask))

    def _add(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختر المحضر", "", cp.FILE_FILTER)
        if path:
            self._apply(lambda: cp.add_minute(self.base, self.data, path, ask=self._ask))
