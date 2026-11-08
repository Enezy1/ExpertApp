# ===== qt_startup_panel.py — أول ما يراه الخبير في «مسار التقرير»: قائمة المستندات + لوحة خطوات حيّة (2026-10-21) =====
# يمين (RTL): لوحة الخطوات التسع (case_startup) بحالة كل خطوة وعدادها، تُقرأ كل ثانية من الحالة الحية أثناء العمل.
# يسار: كل مستندات المجلد بأسمائها الجديدة (case_summary.documents) ونوعها ومقدّمها وتاريخها وحالة تحويلها والمحرّك.
# الأحمر: ملف «تعذّر التحويل» (حلقة/مهلة) بزر «إعادة»، وملف لم يُحسم فرزه بسؤال واحد وزر «تحديد».
import os

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
                             QLabel, QLineEdit, QPushButton, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

import case_folder as cf
import case_sort
import case_startup as cs
import case_summary
import qt_report_card as rc

F = rc.FONT
ICON = {cs.PENDING: ('•', '#8B97A3'), cs.RUNNING: ('⏳', rc.PRIMARY_DARK), cs.DONE: ('✓', rc.SECONDARY),
        cs.SKIPPED: ('–', '#8B97A3'), cs.FAILED: ('✗', rc.ERROR), cs.INPUT: ('!', rc.ERROR)}
COLUMNS = ('الاسم', 'المجلد', 'النوع', 'المقدّم', 'التاريخ', 'التحويل', 'المحرّك', '')


def _lbl(text, size=12, color=rc.INK, bold=False, wrap=True):
    l = QLabel(text)
    l.setWordWrap(wrap)
    l.setStyleSheet(f"font-family:{F}; font-size:{size}px; color:{color}; font-weight:{700 if bold else 400};"
                    "border:none; background:transparent;")
    return l


def step_rows(data, live=None):
    """[(مفتاح، أيقونة، لون، النص، العداد، الرسالة)] — دالة صرفة للاختبار."""
    st = live or cs.state(data)
    out = []
    for k, label in cs.STEPS:
        s = st.get(k) or {'state': cs.PENDING}
        icon, color = ICON.get(s.get('state'), ICON[cs.PENDING])
        out.append((k, icon, color, label, cs.counter_text(s), s.get('message') or ''))
    return out


def doc_rows(base, data):
    """صفوف قائمة المستندات: من manifest (مع الفرز) + ما في المجلد ولم يُسجَّل بعد. كل صف: dict + action/red."""
    man = cf.load_manifest(base)
    rows = case_summary.documents(base, man)
    known = {r['rel'] for r in rows}
    for rel in cs.originals(base):
        if rel not in known:
            rows.append({'name': os.path.basename(rel), 'folder': rel.split('/')[0], 'kind': '—', 'by': '',
                         'date': '', 'state': 'لم يُحوَّل بعد', 'engine': '', 'parts': [], 'rel': rel})
    qs = dict(case_sort.questions(data))
    for r in rows:
        e = man['files'].get(r['rel']) or {}
        r['action'], r['red'], r['question'] = '', False, qs.get(r['rel'], '')
        if e.get('state') == 'failed':
            r['red'], r['action'] = True, 'retry'
        elif r['question']:
            r['red'], r['action'] = True, 'answer'
    return rows


class StartupPanel(QWidget):
    retry = pyqtSignal(str)          # المسار النسبي لملف «تعذّر التحويل»
    answer = pyqtSignal(str)         # المسار النسبي لملف ينتظر قرار الفرز

    def __init__(self, base, data, parent=None):
        super().__init__(parent)
        self.base, self.data = base, data
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        # لوحة الخطوات (أول عنصر = يمين في RTL)
        self.steps_box = QFrame()
        self.steps_box.setObjectName('steps')
        self.steps_box.setStyleSheet("QFrame#steps{background:#F7F9FB; border:1px solid #e1e6eb; border-radius:10px;}")
        self.steps_box.setFixedWidth(300)
        sl = QVBoxLayout(self.steps_box)
        sl.setContentsMargins(12, 10, 12, 10)
        sl.setSpacing(6)
        sl.addWidget(_lbl('ما يفعله البرنامج الآن', 13, rc.PRIMARY_DARK, True))
        self.step_labels = {}
        for k, _ in cs.STEPS:
            l = _lbl('', 12)
            l.setTextFormat(Qt.TextFormat.RichText)
            self.step_labels[k] = l
            sl.addWidget(l)
        sl.addStretch()
        root.addWidget(self.steps_box)
        # قائمة المستندات
        left = QVBoxLayout()
        self.title = _lbl('مستندات القضية', 14, rc.PRIMARY_DARK, True)
        left.addWidget(self.title)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(COLUMNS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet(f"QTableWidget{{font-family:{F}; font-size:12px; border:1px solid #e1e6eb;"
                                 "border-radius:8px; background:white;}")
        left.addWidget(self.table, 1)
        self.questions = QVBoxLayout()
        left.addLayout(self.questions)
        root.addLayout(left, 1)
        self._sig = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def set_data(self, data):
        self.data = data
        self._sig = None
        self.refresh()

    def refresh(self):
        live = cs.live(self.base)
        for k, icon, color, label, counter, msg in step_rows(self.data, live):
            extra = f" <span style='color:#5b6670'>({counter})</span>" if counter else ''
            note = f"<br><span style='color:{color if color == rc.ERROR else '#5b6670'}; font-size:11px'>{msg}</span>" if msg else ''
            self.step_labels[k].setText(f"<span style='color:{color}; font-weight:700'>{icon}</span> {label}{extra}{note}")
        try:
            rows = doc_rows(self.base, self.data)
        except Exception:
            rows = []
        sig = tuple((r['rel'], r['state'], r['by'], r['date'], r['action']) for r in rows)
        if sig == self._sig:
            return
        self._sig = sig
        self.title.setText(f'مستندات القضية ({len(rows)})')
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate((r['name'], r['folder'], r['kind'], r['by'], r['date'], r['state'], r['engine'])):
                it = QTableWidgetItem(v or '—')
                if r['red']:
                    it.setForeground(Qt.GlobalColor.red)
                self.table.setItem(i, j, it)
            self.table.setCellWidget(i, len(COLUMNS) - 1, self._action_btn(r))
        while self.questions.count():
            w = self.questions.takeAt(0).widget()
            if w:
                w.deleteLater()
        for r in rows:
            if r['action'] == 'answer':
                self.questions.addWidget(_lbl(f"🔴 {r['name']}: {r['question']}", 12, rc.ERROR, True))

    def _action_btn(self, r):
        if not r['action']:
            return None
        b = QPushButton('إعادة' if r['action'] == 'retry' else 'تحديد')
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"QPushButton{{font-family:{F}; font-size:11px; color:{rc.ERROR}; border:1px solid {rc.ERROR};"
                        "border-radius:6px; background:transparent; padding:2px 10px;}")
        rel = r['rel']
        b.clicked.connect(lambda: (self.retry if r['action'] == 'retry' else self.answer).emit(rel))
        return b


class SortAnswerDialog(QDialog):
    """سؤال الفرز الواحد: نوع الملف ومقدّمه وتاريخه (ورقم المحضر)."""
    TYPES = (case_sort.T_PORTF, case_sort.T_MEMO, case_sort.T_MIN, case_sort.T_JUDG, case_sort.T_PLAINT,
             case_sort.T_PRIOR)
    ROLES = (('plaintiff', 'المدعي/المدعية'), ('defendant', 'المدعى عليه/عليها'), ('appellant', 'المستأنف'),
             ('appellee', 'المستأنف ضده'))

    def __init__(self, name, question, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle('تحديد المستند')
        lay = QVBoxLayout(self)
        lay.addWidget(_lbl(f"{name}\n{question}", 12, rc.ERROR, True))
        form = QFormLayout()
        self.type = QComboBox()
        self.type.addItems(self.TYPES)
        self.role = QComboBox()
        for k, t in self.ROLES:
            self.role.addItem(t, k)
        self.index = QSpinBox()
        self.index.setRange(1, 10)
        self.date = QLineEdit()
        self.date.setPlaceholderText('DD/MM/YYYY')
        self.no = QSpinBox()
        self.no.setRange(0, 99)
        form.addRow('النوع', self.type)
        form.addRow('المقدّم', self.role)
        form.addRow('ترتيبه بين أطراف دوره', self.index)
        form.addRow('التاريخ', self.date)
        form.addRow('رقم المحضر (للمحضر)', self.no)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        return {'type_': self.type.currentText(), 'role': self.role.currentData(), 'index': self.index.value(),
                'date': self.date.text().strip(), 'minute_no': self.no.value() or None}
