# اختبارات نوافذ المراجعة (2026-10-17): python -m unittest test_qt_review_dialogs -v
import case_subject_mission as _sm_style
_sm_style.STYLE = 'formula'          # هذه الاختبارات للقوالب القديمة؛ الكتابة بالذكاء في test_subject_style.py
import json
import os
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication

import case_model as cm
import case_procedures as cp
import case_subject_mission as sm
import case_workspace as cw
import qt_review_dialogs as rd
from test_case_procedures import DEFS, PLAINTIFF, write_minute

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)
APP = QApplication.instance() or QApplication([])


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def disk(self):
        return cw.read_case_json(self.base)


class SubjectReviewTests(Base):
    def setUp(self):
        super().setUp()
        sm.set_subject(self.base, self.data, 'موضوع أول')         # كُتب (done) ولم يُراجَع

    def test_save_without_approve_keeps_done(self):
        dlg = rd.SubjectReviewDialog(self.base, self.data)
        dlg.text.setPlainText('موضوع معدّل')
        dlg._save(False)
        d = self.disk()
        self.assertEqual((d['subject'], d['steps']['subject']['state']), ('موضوع معدّل', 'done'))

    def test_dialog_warns_when_text_still_has_todo_marker(self):
        self.assertEqual(rd.SubjectReviewDialog(self.base, self.data).note.text(), '')
        sm.set_subject(self.base, self.data, 'وطلبت [يُكتب].')
        self.assertIn('[يُكتب]', rd.SubjectReviewDialog(self.base, self.data).note.text())

    def test_approve_button_is_the_only_way_to_reviewed(self):
        dlg = rd.SubjectReviewDialog(self.base, self.data)
        self.assertEqual(dlg.text.toPlainText(), 'موضوع أول')        # النص كاملاً
        self.assertEqual(self.disk()['steps']['subject']['state'], 'done')
        dlg._save(True)
        self.assertEqual(self.disk()['steps']['subject']['state'], 'reviewed')

    def test_edit_after_approval_returns_to_written_and_warns_dependents(self):
        for k in ('mission',):
            cm.set_step(self.data, k, 'running')
            cm.set_step(self.data, k, 'done')
            cm.set_step(self.data, k, 'reviewed')
        for k in ('documents', 'research'):
            cm.set_step(self.data, k, 'running')
            cm.set_step(self.data, k, 'done')
        sm.review_subject(self.base, self.data)
        dlg = rd.SubjectReviewDialog(self.base, self.data)
        dlg.text.setPlainText('موضوع بعد الاعتماد')
        dlg._save(False)
        d = self.disk()
        self.assertEqual(d['steps']['subject']['state'], 'done')
        self.assertTrue(d['steps']['research']['stale'])
        self.assertIn('البحث ورأي الخبرة', dlg.note.text())


class MinutesEditDialogTests(Base):
    """«تعديل» الإجراءات: لا تأكيد منفصل للحضور — استبعاد/إعادة محضر وتعديل حضور طرف فقط."""

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self._tmp.name, 'm')
        os.makedirs(os.path.join(self.root, CASE['caso_no']))
        full = f'{PLAINTIFF} و{DEFS[0]} و{DEFS[1]}'
        write_minute(os.path.join(self.root, CASE['caso_no'], '1.docx'), 'لم يحضر أحد.')
        write_minute(os.path.join(self.root, CASE['caso_no'], '2.docx'), full)
        cp.run_procedures(self.base, self.data, lambda: [{'date': '2026-09-01', 'open_record': True},
                                                         {'date': '2026-09-15', 'open_record': False}],
                          root=self.root, today='2026-10-10', get_case=lambda c: {},
                          flow=lambda: {'sessions': [], 'received': '2026-08-20', 'booked': '2026-10-05'})

    def settle(self):
        for _ in range(5):
            APP.processEvents()
            time.sleep(0.01)

    def test_lists_taken_minutes_and_attendance_without_confirm_button(self):
        self.assertEqual(self.disk()['steps']['procedures']['state'], 'reviewed')      # اعتُمدت وحدها
        dlg = rd.MinutesEditDialog(self.base, self.data)
        self.assertEqual([b.text() for b in dlg._boxes], ['1.docx', '2.docx'])
        self.assertTrue(all(b.isChecked() for b in dlg._boxes))
        self.assertEqual(len(dlg._combos), 3)
        self.assertIn('في النظام جلستان، تم الاطلاع على محضرين', dlg.summary.text())
        self.assertFalse(hasattr(dlg, 'confirm_btn'))

    def test_excluding_a_minute_reevaluates_truthfully(self):
        dlg = rd.MinutesEditDialog(self.base, self.data)
        dlg._boxes[1].setChecked(False)
        self.settle()
        d = self.disk()
        self.assertEqual([m['name'] for m in d['sessions']['minutes']], ['1.docx'])
        self.assertEqual(d['sessions']['missing_count'], 1)                    # النقص ملاحظة لا يحجب

    def test_setting_attendance_changes_text(self):
        dlg = rd.MinutesEditDialog(self.base, self.data)
        dlg._combos[2].setCurrentIndex(rd.MinutesEditDialog.NO)
        self.settle()
        d = self.disk()
        self.assertEqual(d['procedures']['attendance']['overrides'], {'2': False})
        self.assertIn('تخلف', d['procedures']['text'])           # تأكيد الخبير نفسه يُكتب رغم نقص المحاضر
        self.assertNotIn('رغم صحة إعلانه', d['procedures']['text'])   # والإعلان لم يثبت في المحاضر


if __name__ == '__main__':
    unittest.main()
