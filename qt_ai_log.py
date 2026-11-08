# ===== qt_ai_log.py — نافذة «سجل الذكاء الاصطناعي» لقضية (2026-10-21) =====
# قائمة طلبات القضية بالترتيب (الوقت، الخطوة، النموذج، المدة، النتيجة ✓/✗)؛ الضغط على طلب يعرض الطلب والرد كاملين
# كنصّين قابلين للنسخ، وسبب الرفض إن رُفض. «فتح المجلد» يفتح _نظام/سجلات/طلبات_الذكاء. القراءة من ملفات ai_call_log فقط.
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QPlainTextEdit,
                             QAbstractItemView, QHeaderView, QSplitter, QWidget)

import ai_call_log
import qt_theme as th
from qt_widgets import PrimaryButton, SecondaryButton

COLS = ('الوقت', 'الخطوة', 'النموذج', 'المدة', 'النتيجة')


def _time(rec):
    return (rec.get('at') or '').replace('T', ' ')[-8:]


def _step(rec):
    s = rec.get('step') or ''
    return f"{s} — {rec['detail']}" if rec.get('detail') else s


def _model(rec):
    who = ' · '.join(x for x in (rec.get('provider'), rec.get('model')) if x)
    return who or '—'


class AiLogDialog(QDialog):
    def __init__(self, base, parent=None):
        super().__init__(parent)
        self.base = base
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle('سجل الذكاء الاصطناعي')
        self.resize(900, 640)
        lay = QVBoxLayout(self)
        self.head = QLabel('')
        self.head.setAlignment(th.ARIGHT)
        self.head.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none;")
        lay.addWidget(self.head)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._select)
        self.note = QLabel('')
        self.note.setWordWrap(True)
        self.note.setAlignment(th.ARIGHT)
        self.note.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none;")
        self.prompt, self.reply = QPlainTextEdit(), QPlainTextEdit()
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(self._pane('الطلب', self.prompt))
        split.addWidget(self._pane('الرد', self.reply))
        split.setSizes([200, 220, 220])
        lay.addWidget(split, 1)
        lay.addWidget(self.note)
        btns = QHBoxLayout()
        refresh = SecondaryButton('↻  تحديث')
        refresh.clicked.connect(self.reload)
        folder = SecondaryButton('فتح المجلد')
        folder.clicked.connect(self.open_folder)
        close = PrimaryButton('إغلاق')
        close.clicked.connect(self.accept)
        for b in (refresh, folder):
            btns.addWidget(b)
        btns.addStretch()
        btns.addWidget(close)
        lay.addLayout(btns)
        self.recs = []
        self.reload()

    def _pane(self, title, edit):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        lab = QLabel(title)
        lab.setStyleSheet("font-weight:600; border:none;")
        cp = SecondaryButton('نسخ')
        cp.clicked.connect(lambda: QGuiApplication.clipboard().setText(edit.toPlainText()))
        row.addWidget(lab)
        row.addStretch()
        row.addWidget(cp)
        v.addLayout(row)
        edit.setReadOnly(True)
        edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        v.addWidget(edit)
        return box

    def reload(self):
        self.recs = ai_call_log.list_requests(self.base)
        self.table.setRowCount(len(self.recs))
        bad = 0
        for r, rec in enumerate(self.recs):
            mark, why = ai_call_log.outcome(rec)
            bad += mark == '✗'
            word = 'مقبول' if mark == '✓' else ('فشل' if why.startswith('فشل') else 'مرفوض')   # كلمة لا رمز (✗ لا يظهر في كل الخطوط)
            vals = (_time(rec), _step(rec), _model(rec), f"{rec.get('secs', 0):.0f} ث", word)
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setToolTip(why)
                if c == 4:
                    it.setForeground(Qt.GlobalColor.darkGreen if mark == '✓' else Qt.GlobalColor.red)
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, it)
        self.head.setText(f"{len(self.recs)} طلباً" + (f" — {bad} مرفوض أو فاشل" if bad else '')
                          if self.recs else 'لا طلبات ذكاء اصطناعي مسجَّلة لهذه القضية بعد.')
        if self.recs:
            self.table.setCurrentCell(len(self.recs) - 1, 0)
        else:
            self.prompt.setPlainText('')
            self.reply.setPlainText('')
            self.note.setText('')

    def _select(self):
        items = self.table.selectedItems()
        row = items[0].row() if items else self.table.currentRow()
        if not 0 <= row < len(self.recs):
            return
        rec = self.recs[row]
        self.prompt.setPlainText(rec.get('prompt') or '')
        self.reply.setPlainText(rec.get('response') or rec.get('error') or '')
        mark, why = ai_call_log.outcome(rec)
        bits = [f"{mark} {why}", f"الطلب {rec.get('prompt_chars', 0):,} حرفاً والرد {rec.get('response_chars', 0):,} حرفاً"]
        if rec.get('key_owner'):
            bits.append(f"المفتاح: {rec['key_owner']}")
        if rec.get('is_retry'):
            bits.append('إعادة لطلب سابق رُفض')
        if rec.get('retried'):
            bits.append('أُعيد بعده طلب آخر')
        self.note.setText(' — '.join(bits))

    def open_folder(self):
        d = ai_call_log.req_dir(self.base)
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)
        except OSError:
            pass
