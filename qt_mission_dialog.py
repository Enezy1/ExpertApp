# ===== qt_mission_dialog.py — مراجعة المأمورية وتأكيدها (المرحلة 2ح، واجهة) =====
# يعرض النص الحرفي ونقاطه (نقطة بكل سطر) ليعدّلها الخبير ثم يحفظ أو يؤكّد. المنطق في case_subject_mission.py.
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QMessageBox

import qt_theme as th
from qt_bidi import BidiPlainTextEdit
from qt_widgets import PrimaryButton, SecondaryButton

import case_model
import case_subject_mission as sm


class MissionDialog(QDialog):
    def __init__(self, base, data, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("مأمورية القضية")
        self.setMinimumSize(620, 520)
        self.base, self.data = base, data
        m = data['mission']
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("نص المأمورية الحرفي:"))
        self.raw = BidiPlainTextEdit(m.get('raw') or '')
        self.raw.setMaximumHeight(150)
        lay.addWidget(self.raw)
        row = QHBoxLayout()
        row.addWidget(QLabel("النقاط (نقطة بكل سطر — الترقيم تلقائي):"))
        resplit = SecondaryButton("إعادة التقسيم من النص")
        resplit.clicked.connect(self._resplit)
        row.addStretch()
        row.addWidget(resplit)
        lay.addLayout(row)
        self.points = BidiPlainTextEdit('\n'.join(p['text'] for p in m.get('points') or []))
        lay.addWidget(self.points, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none;")
        lay.addWidget(self.note)
        btns = QHBoxLayout()
        save = SecondaryButton("حفظ دون اعتماد")
        save.clicked.connect(lambda: self._save(False))
        ok = PrimaryButton("اعتماد")
        ok.clicked.connect(lambda: self._save(True))
        cancel = SecondaryButton("إغلاق")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(save)
        btns.addStretch()
        btns.addWidget(cancel)
        lay.addLayout(btns)

    def _resplit(self):
        self.points.setPlainText('\n'.join(sm.split_points(self.raw.toPlainText())))

    def _lines(self):
        return [l.strip() for l in self.points.toPlainText().splitlines() if l.strip()]

    def _save(self, confirm):
        pts = self._lines()
        if confirm and not pts:
            QMessageBox.warning(self, "المأمورية", "لا توجد نقاط لتأكيدها.")
            return
        try:
            old = self.data['mission']
            raw_changed = self.raw.toPlainText().strip() != (old.get('raw') or '')
            pts_changed = pts != [p['text'] for p in old.get('points') or []]
            if raw_changed or pts_changed:
                sm.set_mission(self.base, self.data, raw=self.raw.toPlainText(), points=pts)
            if confirm:
                sm.confirm_mission(self.base, self.data)
        except case_model.StepError as e:
            QMessageBox.warning(self, "المأمورية", str(e))
            return
        from qt_review_dialogs import show_saved_toast
        stale = case_model.stale_labels(self.data, 'mission')
        if stale and not confirm:
            self.note.setText("عُدِّلت المأمورية: " + "، ".join(stale) + " تحتاج تحديثاً. الحالة الآن «كُتبت» حتى تعتمدها.")
        show_saved_toast(self)
        if confirm:
            self.accept()
