# اختبارات المسار (2و + التوصيل): python -m unittest test_qt_case_track -v
import case_subject_mission as _sm_style
_sm_style.STYLE = 'formula'          # هذه الاختبارات للقوالب القديمة؛ الكتابة بالذكاء في test_subject_style.py
import json
import os
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication

import ai_call_log
import case_model as cm
import case_research as cr
import case_workspace as cw
import qt_case_track as qt
import test_case_subject_contract as tc

ai_call_log.PATH_OVERRIDE = os.path.join(tempfile.gettempdir(), 'expertapp_test_ai_calls.log')

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)
APP = QApplication.instance() or QApplication([])


def finish(d, k, final='done'):
    if k == 'subject' and not (d.get('subject') or '').strip():
        d['subject'] = 'جاءت المدعية بصحيفة مفادها…'     # «منتهية» لا تكون بموضوع فارغ (reports_list_model)
    cm.set_step(d, k, 'running')
    cm.set_step(d, k, 'done')
    if final == 'reviewed':
        cm.set_step(d, k, 'reviewed')


def wait(dlg, secs=10):
    end = time.time() + secs
    while dlg._busy and time.time() < end:
        APP.processEvents()
        time.sleep(0.02)
    APP.processEvents()
    assert not dlg._busy, 'انتهت المهلة والعمل ما زال جارياً'


class RowModelTests(unittest.TestCase):
    def test_symbols_per_state(self):
        d = cm.new_case_data(CASE)
        got = {}
        for state in cm.STATES:
            d['steps']['subject'] = dict(cm.new_step(), state=state)
            got[state] = qt.row_model(d, 'subject')
        self.assertEqual({s: m['symbol'] for s, m in got.items()},
                         {'pending': '○', 'running': '◐', 'needs_input': '⚠', 'done': '✎',
                          'reviewed': '✓', 'failed': '✗', 'blocked': '⊘'})

    def test_actions_per_state_and_step(self):
        d = cm.new_case_data(CASE)
        A = lambda k: [a for a, _ in qt.actions_for(d, k)]
        self.assertEqual(A('subject'), ['run'])
        self.assertEqual(A('documents'), ['add'])
        self.assertEqual(A('research'), [])                      # pending لكن شروطه غير متحققة
        d['steps']['procedures'].update(state='needs_input')
        self.assertEqual(A('procedures'), ['add', 'attend'])          # تلقائية: «إضافة محضر آخر» و«تعديل» فقط
        d['steps']['documents'].update(state='failed')
        self.assertEqual(A('documents'), ['retry', 'waive'])
        d['steps']['subject'].update(state='done')
        self.assertEqual(A('subject'), ['review'])
        d['steps']['mission'].update(state='reviewed')
        self.assertEqual(A('mission'), ['add'])
        d['steps']['attachments'].update(state='done', stale=True)
        self.assertEqual(A('attachments'), ['review'])             # تُبنى آلياً: لا زر «حدّث»
        d['steps']['procedures'].update(state='running')
        self.assertEqual(A('procedures'), [])

    def test_progress_stale_message(self):
        d = cm.new_case_data(CASE)
        d['steps']['research'].update(state='done', stale=True, message='ملاحظة', progress={'done': 2, 'total': 5})
        t = qt.row_model(d, 'research')['text']
        for s in ('(2/5)', 'تحتاج تحديثاً', 'ملاحظة'):
            self.assertIn(s, t)


class WidgetTests(unittest.TestCase):
    def test_buttons_emit_action_and_hide_when_none(self):
        d = cm.new_case_data(CASE)
        d['steps']['documents'].update(state='failed', message='ملف تالف')
        d['steps']['procedures'].update(state='needs_input')
        w = qt.CaseTrackWidget(d)
        got = []
        w.action.connect(lambda k, a: got.append((k, a)))
        w._rows['documents'][2][0].click()
        w._rows['documents'][2][1].click()
        w._rows['procedures'][2][1].click()
        self.assertEqual(got, [('documents', 'retry'), ('documents', 'waive'), ('procedures', 'attend')])
        self.assertTrue(w._rows['mission'][2][1].isHidden())
        self.assertIn('ملف تالف', w._rows['documents'][1].text())

    def test_changing_states_updates_rows(self):
        d = cm.new_case_data(CASE)
        w = qt.CaseTrackWidget(d)
        self.assertEqual(w._rows['subject'][0].text(), '○')
        finish(d, 'subject', 'reviewed')
        w.set_data(d)
        self.assertEqual(w._rows['subject'][0].text(), '✓')
        self.assertEqual(w._rows['subject'][2][0].property('action'), 'review')   # زر «عدّل» بعد الاعتماد


class DialogBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class ReloadTests(DialogBase):
    def test_reload_reads_disk_recovers_and_blocks(self):
        cm.set_step(self.data, 'subject', 'running')              # كأن البرنامج أُغلق أثناءها
        cw.write_case_json(self.base, self.data)
        dlg = qt.CaseTrackDialog(self.base, cw.read_case_json(self.base))
        self.assertEqual(dlg.track._rows['subject'][0].text(), '○')
        self.assertEqual(cw.read_case_json(self.base)['steps']['subject']['state'], 'pending')
        self.assertEqual(dlg.track._rows['research'][0].text(), '⊘')
        data = cw.read_case_json(self.base)
        data['steps']['procedures'] = dict(cm.new_step(), state='needs_input')
        cw.write_case_json(self.base, data)
        dlg.reload()
        self.assertEqual(dlg.track._rows['procedures'][0].text(), '⚠')


class WiringTests(DialogBase):
    """يضغط «الأزرار» عبر dlg.do ويتأكد أن المنطق الحقيقي نُفِّذ في خيط خلفي وحُفظ."""

    def make(self, **kw):
        return qt.CaseTrackDialog(self.base, cw.read_case_json(self.base), **kw)

    def subject_env(self):
        """اتصال وهمي: صحيفة الدعوى من test_case_subject_contract ومزوّد يعيد JSON حرفياً منها."""
        return mock.patch('case_subject_telecom.fetch_claim_text', lambda c, a, *r, **k: tc.PLAINT)

    def make_subject(self, **kw):
        """المرحلة الثانية: الصحيفة مفروزة في المجلد، والمزوّد يعيد الموضوع والإجراءات والمرفقات في JSON واحد."""
        import test_qt_case_page as tp
        tp.stage1(self.base)
        self.calls = []
        return self.make(cookies={'s': '1'}, ask=lambda p: (self.calls.append(p),
                                                          json.dumps(tp.STAGE2_REPLY, ensure_ascii=False))[1], **kw)

    def test_subject_run_from_case_db_stub_and_manual_and_review(self):
        row = {'case_summary': 'موضوع من الصحيفة', 'mission_text': '1- أ 2- ب'}
        with mock.patch('case_subject_mission._default_get_case', lambda no: row), self.subject_env():
            dlg = self.make_subject()
            dlg.do('subject', 'run')
            wait(dlg)
            self.assertEqual(cw.read_case_json(self.base)['steps']['subject']['state'], 'reviewed')
            import test_qt_case_page as tp
            self.assertEqual(cw.read_case_json(self.base)['subject'], tp.STAGE2_REPLY['subject'])
            self.assertEqual(len(self.calls), 1)                 # طلب واحد للموضوع والإجراءات والمرفقات
            self.assertEqual(dlg.track._rows['subject'][0].text(), '✓')
            with mock.patch.object(qt.SubjectReviewDialog, 'exec', lambda self: (self._save(True), 1)[1]):
                dlg.do('subject', 'review')
            self.assertEqual(cw.read_case_json(self.base)['steps']['subject']['state'], 'reviewed')
            dlg.do('mission', 'run')
            wait(dlg)
            self.assertEqual(cw.read_case_json(self.base)['steps']['mission']['state'], 'reviewed')
        with mock.patch('qt_case_track.QInputDialog.getMultiLineText', return_value=('موضوع يدوي', True)):
            dlg.do('subject', 'add')
        self.assertEqual(cw.read_case_json(self.base)['subject'], 'موضوع يدوي')

    def test_subject_without_plaint_sends_nothing_and_lists_missing(self):
        """لا يُرسل طلب الموضوع بلا صحيفة الدعوى؛ تظهر قائمة ما ينقص بدل الكتابة."""
        calls = []
        dlg = self.make(cookies={'k': 'v'}, ask=lambda p: calls.append(p) or '{}')
        dlg.do('subject', 'run')
        wait(dlg)
        d = cw.read_case_json(self.base)
        self.assertEqual(calls, [])
        self.assertEqual(d['steps']['subject']['state'], 'needs_input')
        self.assertIn('صحيفة الدعوى', d['steps']['subject']['message'])
        for need in ('صحيفة الدعوى', 'حكم الإحالة', 'محاضر الخبرة'):
            self.assertIn(need, d['stage2']['missing'])

    def test_subject_with_plaint_written_and_other_missing_listed(self):
        dlg = self.make_subject()
        dlg.do('subject', 'run')
        wait(dlg)
        d = cw.read_case_json(self.base)
        import case_stage2
        text, red = case_stage2.status_line(self.base, d)
        self.assertTrue(d['subject'].startswith('جاءت المدعية'))
        self.assertIn('حكم الإحالة', text)                      # ما ينقص يظهر للخبير
        self.assertTrue(red)

    def test_mission_confirm_via_review_button(self):
        row = {'mission_text': '1- أ 2- ب'}
        with mock.patch('case_subject_mission._default_get_case', lambda no: row):
            dlg = self.make()
            dlg.do('mission', 'run')
            wait(dlg)
        self.assertEqual(cw.read_case_json(self.base)['steps']['mission']['state'], 'reviewed')   # المأمورية صحيحة ما لم يعدّلها الخبير
        from qt_mission_dialog import MissionDialog
        with mock.patch.object(MissionDialog, 'exec', lambda self: (self._save(True), 1)[1]):
            dlg.do('mission', 'review')
        d = cw.read_case_json(self.base)
        self.assertEqual(d['steps']['mission']['state'], 'reviewed')
        self.assertTrue(d['mission']['confirmed'])

    def test_procedures_run_with_injected_fetch(self):
        with tempfile.TemporaryDirectory() as mroot:
            fetch = lambda: [{'date': '2026-09-01', 'open_record': True}]
            with mock.patch('case_procedures.minutes_dir', lambda c, root=None: os.path.join(mroot, c)):
                dlg = self.make(fetch=fetch)
                dlg.do('procedures', 'run')
                wait(dlg)
        d = cw.read_case_json(self.base)
        self.assertEqual(d['steps']['procedures']['state'], 'needs_input')
        self.assertEqual(d['sessions']['missing'], [1])
        self.assertEqual(dlg.track._rows['procedures'][0].text(), '⚠')

    def test_attachments_are_automatic_and_need_no_button(self):
        dlg = self.make()
        self.assertEqual(qt.actions_for(dlg.data, 'attachments'), [])
        self.data['sessions']['minutes'] = [{'no': 1, 'date': '', 'file': 'x', 'md': ''}]
        cw.write_case_json(self.base, self.data)
        dlg.reload()                                             # يُبنى فوراً من المحاضر بلا انتظار غيره
        d = cw.read_case_json(self.base)
        self.assertEqual(d['steps']['attachments']['state'], 'reviewed')
        self.assertEqual(dlg.track._rows['attachments'][0].text(), '✓')

    def test_review_is_automatic_for_complete_subject(self):
        row = {'case_summary': 'موضوع من الصحيفة'}
        with mock.patch('case_subject_mission._default_get_case', lambda no: row), self.subject_env():
            dlg = self.make_subject()
            dlg.do('subject', 'run')
            wait(dlg)
        self.assertEqual(cw.read_case_json(self.base)['steps']['subject']['state'], 'reviewed')   # تُعتمد وحدها متى اكتملت

    def test_research_then_conclusion_with_fake_ask(self):
        d = self.data
        d['subject'] = 'ن'
        d['mission'] = {'raw': 'x', 'confirmed': True, 'next_id': 3,
                        'points': [{'id': 'q1', 'n': 1, 'text': 'أ'}, {'id': 'q2', 'n': 2, 'text': 'ب'}]}
        finish(d, 'mission', 'reviewed')
        d['steps']['documents']['waived'] = True
        cw.write_case_json(self.base, d)

        def ask(prompt):
            if '## النقطة (رقم' in prompt:
                return 'ردّ نتيجة'
            return f'نص بند\n{cr.SUMMARY_MARK}\nخلاصة'
        dlg = self.make(ask=ask)
        dlg.do('research', 'run')
        wait(dlg)
        d = cw.read_case_json(self.base)
        self.assertEqual(d['steps']['research']['state'], 'done')
        self.assertEqual(d['steps']['research']['progress'], {'done': 2, 'total': 2})
        self.assertEqual(dlg.track._rows['research'][0].text(), '✎')
        dlg.do('conclusion', 'run')
        wait(dlg)
        d = cw.read_case_json(self.base)
        self.assertEqual(d['steps']['conclusion']['state'], 'done')
        self.assertEqual(len(d['conclusion']['answers']), 2)
        dlg.do('research', 'review')
        d = cw.read_case_json(self.base)
        self.assertEqual(d['steps']['research']['state'], 'reviewed')
        self.assertEqual({i['state'] for i in d['research']}, {'reviewed'})

    def test_report_button_builds_docx_in_background(self):
        d = self.data
        d['subject'] = 'ن'
        d['mission'] = {'raw': 'x', 'confirmed': True, 'next_id': 2,
                        'points': [{'id': 'q1', 'n': 1, 'text': 'أ'}]}
        finish(d, 'mission', 'reviewed')
        d['steps']['documents']['waived'] = True
        cw.write_case_json(self.base, d)
        ask = lambda p: 'ردّ' if '## النقطة (رقم' in p else f'نص\n{cr.SUMMARY_MARK}\nخلاصة'
        dlg = self.make(ask=ask)
        self.assertTrue(dlg.report_btn.isEnabled())               # يعمل في أي مرحلة
        dlg.do('research', 'run')
        wait(dlg)
        dlg.do('conclusion', 'run')
        wait(dlg)
        self.assertTrue(dlg.report_btn.isEnabled())
        with mock.patch('qt_case_track.report_docx.gather_info', return_value={}), \
                mock.patch('qt_case_track.QMessageBox.information') as info, \
                mock.patch('qt_case_track.os.startfile') as sf:
            dlg._do_report()
            wait(dlg)
        self.assertTrue(info.called)
        self.assertIn('التقرير_v1.docx', info.call_args[0][2])
        self.assertIn('ملاحظات', info.call_args[0][2])
        self.assertTrue(sf.called)
        self.assertTrue(os.path.exists(os.path.join(self.base, 'التقرير', 'التقرير_v1.docx')))
        self.assertIn('التقرير/التقرير_v1.docx', cw.read_case_json(self.base)['files'])

    def test_report_button_works_on_fresh_case_with_placeholders(self):
        dlg = self.make()
        with mock.patch('qt_case_track.report_docx.gather_info', return_value={}),                 mock.patch('qt_case_track.QMessageBox.information') as info,                 mock.patch('qt_case_track.os.startfile'):
            dlg._do_report()
            wait(dlg)
            dlg._do_report()
            wait(dlg)
        self.assertEqual(info.call_count, 2)
        self.assertTrue(os.path.exists(os.path.join(self.base, 'التقرير', 'التقرير_v1.docx')))
        self.assertTrue(os.path.exists(os.path.join(self.base, 'التقرير', 'التقرير_v2.docx')))

    def test_research_stop_button_pauses_and_provider_error_shows_failed(self):
        d = self.data
        d['mission'] = {'raw': 'x', 'confirmed': True, 'next_id': 3,
                        'points': [{'id': 'q1', 'n': 1, 'text': 'أ'}]}
        finish(d, 'mission', 'reviewed')
        d['steps']['documents']['waived'] = True
        cw.write_case_json(self.base, d)

        def bad(prompt):
            raise RuntimeError('المزوّد معطّل')
        dlg = self.make(ask=bad)
        dlg.do('research', 'run')
        wait(dlg)
        self.assertEqual(dlg.track._rows['research'][0].text(), '✗')
        self.assertEqual([a for a, _ in qt.actions_for(dlg.data, 'research')], ['retry', 'waive'])
        dlg.do('research', 'waive')
        self.assertTrue(cw.read_case_json(self.base)['steps']['research']['waived'])

    def test_buttons_disabled_while_busy_and_second_action_ignored(self):
        import threading
        gate = threading.Event()
        d = self.data
        row = {'case_summary': 'م'}

        def slow(no):
            gate.wait(5)
            return row
        with mock.patch('case_subject_mission._default_get_case', slow), self.subject_env():
            dlg = self.make_subject()
            dlg.do('subject', 'run')
            self.assertTrue(dlg._busy)
            before = dict(dlg.data['steps']['mission'])
            dlg.do('mission', 'run')                       # يُتجاهل: مشغول
            self.assertEqual(dict(dlg.data['steps']['mission']), before)
            gate.set()
            wait(dlg)
        self.assertEqual(cw.read_case_json(self.base)['steps']['subject']['state'], 'reviewed')


if __name__ == '__main__':
    unittest.main()
