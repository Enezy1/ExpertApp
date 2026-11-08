# اختبارات «صفحة القضية»: python -W ignore -m unittest test_qt_case_page -v
import case_subject_mission as _sm_style
_sm_style.STYLE = 'formula'          # هذه الاختبارات للقوالب القديمة؛ الكتابة بالذكاء في test_subject_style.py
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton, QFileDialog

import ai_call_log
import case_model as cm
import case_procedures as cp
import case_workspace as cw
import reports_list_model as rlm
import qt_case_page as qp
qp.CasePageDialog.AUTO_SYNC = False            # المزامنة عند الفتح تُختبر في test_folder_minutes_referral
qp.CasePageDialog.AUTO_ASK_TYPE = False
import test_case_subject_contract as tc
from test_case_procedures import write_minute
from test_qt_case_track import finish, wait

ai_call_log.PATH_OVERRIDE = os.path.join(tempfile.gettempdir(), 'expertapp_test_ai_calls.log')
qp.CasePageDialog.STARTUP_VIEW = False             # الفتح على المستندات يُختبر في test_case_layout
qp.CasePageDialog.AUTO_PROCEDURES = False          # يُشغَّل صراحةً في اختبارات الإجراءات التلقائية

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)
APP = QApplication.instance() or QApplication([])


class PureTests(unittest.TestCase):
    def test_seven_steps_in_order_with_long_labels(self):
        d = cm.new_case_data(CASE)
        names = [n for _k, n, _s, _m in qp.step_list(d)]
        self.assertEqual(names, ['المستندات', 'الموضوع', 'المأمورية', 'الإجراءات',
                                 'البحث ورأي الخبرة', 'المرفقات'])

    def test_current_step_priorities(self):
        d = cm.new_case_data(CASE)
        self.assertEqual(qp.current_step(d), 'documents')       # المستندات أولاً
        finish(d, 'documents', 'reviewed')
        self.assertEqual(qp.current_step(d), 'subject')
        finish(d, 'subject', 'reviewed')
        self.assertEqual(qp.current_step(d), 'mission')
        d['steps']['documents'].update(state='failed')
        self.assertEqual(qp.current_step(d), 'documents')

    def test_states_mapping(self):
        d = cm.new_case_data(CASE)
        finish(d, 'subject')
        d['steps']['mission'].update(state='needs_input')
        d['steps']['procedures'].update(state='failed')
        st = {k: s for k, _n, s, _m in qp.step_list(d)}
        self.assertEqual((st['subject'], st['mission'], st['procedures'], st['research']),
                         (rlm.ST_DONE, rlm.ST_INPUT, rlm.ST_FAILED, rlm.ST_IDLE))

    def test_neighbour(self):
        self.assertIsNone(qp.neighbour('documents', -1))
        self.assertEqual(qp.neighbour('documents', 1), 'subject')
        self.assertEqual(qp.neighbour('subject', 1), 'mission')
        self.assertIsNone(qp.neighbour('attachments', 1))

    def test_tag_colors(self):
        self.assertEqual(qp.tag_colors('المدعية'), qp.AMBER_TAG)
        self.assertEqual(qp.tag_colors('المدعى عليها'), qp.TEAL)

    def test_contracts_and_split(self):
        d = cm.new_case_data(CASE)
        d['portfolios'] = [{'id': 'P1', 'submitter': 'المدعية', 'date': '', 'seq': 2, 'docs': [
            {'uid': 'd1', 'no': 1, 'file': 'a.pdf', 'md': 'x.md', 'type': 'عقد', 'contract': 'C-77',
             'convert': {'state': 'done', 'message': ''}},
            {'uid': 'd2', 'no': 2, 'file': 'b.pdf', 'md': 'y.md', 'type': 'فاتورة', 'contract': '',
             'convert': {'state': 'failed', 'message': 'ملف تالف'}}]}]
        self.assertEqual([c['contract'] for c in qp.contracts(d)], ['C-77'])
        have, miss = qp.docs_split(d)
        self.assertEqual((len(have), len(miss), miss[0]['why']), (1, 1, 'ملف تالف'))


class PageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        self.data['steps']['documents']['state'] = 'done'     # المستندات أولاً: تُنجَز قبل الموضوع
        cw.write_case_json(self.base, self.data)

    def tearDown(self):
        self._tmp.cleanup()

    def make(self):
        return qp.CasePageDialog(self.base, cw.read_case_json(self.base))

    def test_opens_current_step_and_click_switches(self):
        dlg = self.make()
        self.assertEqual(dlg._open, 'subject')
        dlg.track._items['procedures'][0].click()
        self.assertEqual(dlg._open, 'procedures')
        self.assertTrue(dlg.report_btn.isEnabled())
        self.assertTrue(dlg.prev_btn.isEnabled())

    def test_autosave_then_approve_and_next(self):
        dlg = self.make()
        dlg.editor.setPlainText('موضوع مكتوب يدوياً')
        dlg.autosave()
        disk = cw.read_case_json(self.base)
        self.assertEqual(disk['subject'], 'موضوع مكتوب يدوياً')
        self.assertEqual(dlg.saved.text(), 'تم الحفظ تلقائياً')
        dlg.approve_and_next()
        self.assertEqual(cw.read_case_json(self.base)['steps']['subject']['state'], 'reviewed')
        self.assertEqual(dlg._open, 'mission')

    def test_approve_incomplete_step_warns_and_stays(self):
        dlg = self.make()
        dlg.open_step('procedures')
        with mock.patch.object(QMessageBox, 'warning') as w:
            dlg.approve_and_next()
        w.assert_called_once()
        self.assertEqual(dlg._open, 'procedures')

    def test_mission_edit_and_confirm(self):
        dlg = self.make()
        dlg.open_step('mission')
        dlg.editor.setPlainText('النقطة الأولى\nالنقطة الثانية')
        dlg.approve_current()
        m = cw.read_case_json(self.base)
        self.assertEqual([p['text'] for p in m['mission']['points']], ['النقطة الأولى', 'النقطة الثانية'])
        self.assertEqual(m['steps']['mission']['state'], 'reviewed')

    def test_every_step_renders(self):
        dlg = self.make()
        for k, _ in rlm.DISPLAY_STEPS:
            dlg.open_step(k)
            self.assertEqual(dlg._open, k)

    def test_report_always_builds(self):
        dlg = self.make()
        with mock.patch('report_docx.gather_info', lambda d, c: {}), \
                mock.patch('qt_case_track.QMessageBox.information'), mock.patch('os.startfile', create=True):
            dlg._do_report()
            wait(dlg, 30)
        self.assertTrue(os.path.exists(cw.read_case_json(self.base)['report']['file'])
                        or os.path.exists(os.path.join(self.base, cw.read_case_json(self.base)['report']['file'])))

    def test_questions_dialog_adds(self):
        dlg = self.make()
        q = qp.QuestionsDialog(self.base, dlg.data, dlg)
        q.edit.setText('هل العقد موقّع؟')
        q._add()
        self.assertEqual([(x['text'], x['status'], x['auto']) for x in cw.read_case_json(self.base)['questions']],
                         [('هل العقد موقّع؟', 'open', False)])
        self.assertEqual(q.table_party.rowCount(), 1)


SESSIONS = [{'date': '2026-09-01', 'open_record': True},
            {'date': '2026-09-15', 'open_record': False, 'booking': True}]      # جلسة الحجز تعطي تاريخ الحجز
FLOW = {'sessions': [], 'received': '2026-08-20', 'booked': '2026-10-05'}


class AutoProceduresTests(unittest.TestCase):
    """الإجراءات تلقائية: تُؤخذ المحاضر بلا نافذة، والأزرار الزائدة اختفت، والنافذة تظهر فقط إن لم يوجد شيء."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, 'محاضر')
        self.base, self.data = cw.ensure_workspace(CASE, os.path.join(self._tmp.name, 'ws'))
        self.patches = [mock.patch('case_procedures.default_root', lambda: self.root),
                        mock.patch('case_procedures._default_get_case', lambda c: {'judgment_date': '07/06/2026'}),
                        mock.patch('case_procedures.flow_fetcher', lambda *a: (lambda: dict(FLOW))),
                        mock.patch.object(qp.CasePageDialog, 'AUTO_PROCEDURES', True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self._tmp.cleanup()

    def minute(self, n, attend):
        d = cp.minutes_dir(CASE['caso_no'], self.root)
        os.makedirs(d, exist_ok=True)
        write_minute(os.path.join(d, f'{n}.docx'), attend, plaintiff='شركة زين للاتصالات', defs=['حسام محمد'])

    def triage(self):
        """المرحلة الأولى: المحاضر تُنسخ للقضية وتُفرز (الحضور باقتباس حرفي) — بدل طلب الحضور المنفصل."""
        import json as _j
        import case_folder as cf
        import case_sort as cs
        data = cw.read_case_json(self.base)
        cf.collect_local_minutes(self.base, CASE['caso_no'], self.root)
        cf.sync_case_folder(self.base, data)

        def ask(prompt):
            body = prompt.split('نص الملف')[-1]
            att = ({'present': [{'role': 'plaintiff', 'index': 1, 'quote': 'ممثل شركة زين للاتصالات'}]}
                   if 'ممثل شركة زين للاتصالات' in body else {})
            return _j.dumps({'parts': [{'type': 'محضر', 'pages': [1, 1], 'attendance': att}]}, ensure_ascii=False)
        cs.run(self.base, data, ask)
        cw.write_case_json(self.base, data)

    def open_procedures(self, picker):
        with mock.patch.object(QFileDialog, 'getOpenFileName', picker):
            dlg = qp.CasePageDialog(self.base, cw.read_case_json(self.base), cookies={'s': '1'},
                                    ask=lambda p: '{"present":[1]}', fetch=lambda: SESSIONS)
            dlg.open_step('procedures')
            wait(dlg)
            for _ in range(5):
                APP.processEvents()
        return dlg

    def test_takes_minutes_from_folder_without_dialog_and_approves(self):
        self.minute(1, 'لم يحضر أحد.')
        self.minute(2, 'ممثل شركة زين للاتصالات')
        self.triage()                                         # الحضور من فرز كل محضر (لا طلب حضور منفصل)
        dlg = self.open_procedures(lambda *a, **k: self.fail('لا يجب أن تظهر نافذة اختيار ملف'))
        d = cw.read_case_json(self.base)
        self.assertEqual(d['steps']['procedures']['state'], 'reviewed')
        texts = [l.text() for l in dlg.card.findChildren(qp.QLabel)]
        self.assertTrue(any('تم الاطلاع على محضرين' in t for t in texts))
        self.assertTrue(any('في النظام جلستان، تم الاطلاع على محضرين' in t for t in texts))
        buttons = [b.text() for b in dlg.card.findChildren(QPushButton) if b.isVisibleTo(dlg)]
        self.assertEqual(buttons, ['إعادة الكتابة', 'إضافة محضر آخر', 'تعديل'])
        for gone in ('التحقق والحضور', 'تحقق من النظام', 'اعتماد', 'إرفاق محضر'):
            self.assertNotIn(gone, buttons)
        shown = dlg.editor.toPlainText()
        self.assertIn('وتخلف المدعى عليه عن الحضور', shown)
        self.assertNotIn('رغم صحة إعلانه', shown)                 # الإعلان لم يرد في نص المحاضر ← لا يُكتب

    def test_file_dialog_only_when_nothing_found_and_any_type(self):
        calls = []

        def picker(parent, title, folder, flt):
            calls.append(flt)
            return '', ''
        self.open_procedures(picker)
        self.assertEqual(len(calls), 1)
        for ext in ('*.docx', '*.pdf', '*.png', '*.md', '*.txt'):
            self.assertIn(ext, calls[0])
        self.assertFalse(calls[0].startswith('Word'))

    def test_expert_edit_of_text_is_autosaved_and_keeps_approval(self):
        self.minute(1, 'لم يحضر أحد.')
        self.minute(2, 'ممثل شركة زين للاتصالات')
        dlg = self.open_procedures(lambda *a, **k: ('', ''))
        dlg.editor.setPlainText('نص الإجراءات بعد تعديل الخبير')
        dlg.autosave()
        d = cw.read_case_json(self.base)
        self.assertEqual((d['procedures']['text'], d['steps']['procedures']['state']),
                         ('نص الإجراءات بعد تعديل الخبير', 'reviewed'))


STAGE2_REPLY = {
    'subject': ('جاءت المدعية بصحيفة مفادها أنه بموجب عقد اشتراك مؤرخ 15/03/2024 تعهدت المدعية بتقديم خدمات الاتصال '
                'للمدعى عليه، وذلك مقابل اشتراك شهري قدره 18.500 د.ك لمدة التزام قدرها 24 شهراً، وأفادت المدعية على حسب '
                'دعواها أنها قدمت الخدمة إلا أن المدعى عليه توقف عن السداد بمبلغ 436.750 د.ك، فتم رفع الدعوى الماثلة.'),
    'procedures': 'استلمنا ملف الدعوى، وحددنا عدة جلسات، واطلعنا على ما به من أوراق ومستندات.',
    'attachments': []}


STAGE2_PLAINT = ('<!-- صفحة 1 -->\nصحيفة دعوى\nبموجب عقد اشتراك مؤرخ 15/03/2024 اشترك المدعى عليه لدى المدعية في خدمة '
                 'الاتصال مقابل اشتراك شهري قدره 18.500 د.ك لمدة التزام قدرها 24 شهراً، وقد توقف المدعى عليه عن السداد.\n'
                 'ليسمع المدعى عليه الحكم بإلزامه بأن يؤدي للمدعية مبلغ 436.750 د.ك.')


def stage1(base):
    """صحيفة الدعوى في مستندات_النظام ومفروزة بعقدها ومبلغها (اقتباسات حرفية) — مدخل المرحلة الثانية."""
    import json as _j
    import case_folder as cf
    import case_sort as cs
    data = cw.read_case_json(base)
    with open(os.path.join(base, cf.SYSDOCS, 'صحيفة الدعوى.txt'), 'w', encoding='utf-8') as f:
        f.write(STAGE2_PLAINT)
    cf.sync_case_folder(base, data)
    reply = {'parts': [{'type': 'صحيفة', 'pages': [1, 1],
                        'contract': {'found': True, 'date': '15/03/2024', 'value': '18.500 د.ك', 'duration': '24 شهراً',
                                     'quote': 'بموجب عقد اشتراك مؤرخ 15/03/2024'},
                        'amounts': [{'label': 'المطالبة', 'amount': '436.750', 'quote': 'مبلغ 436.750 د.ك'}]}]}
    cs.run(base, data, lambda p: _j.dumps(reply, ensure_ascii=False))
    cw.write_case_json(base, data)


class RewriteTests(unittest.TestCase):
    """«إعادة الكتابة» بمزوّد وهمي: كانت لا تعمل لأنها تُستدعى بلا force؛ الآن «جارٍ…» ثم النتيجة أو الخطأ."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        self.data['steps']['documents']['state'] = 'done'     # المستندات أولاً: تُنجَز قبل الموضوع
        cw.write_case_json(self.base, self.data)
        self.calls = []
        self.patch = mock.patch('case_subject_telecom.fetch_claim_text', lambda c, a, *r, **k: tc.PLAINT)
        self.patch.start()
        stage1(self.base)                                     # المرحلة الأولى: الصحيفة في المجلد ومفروزة

    def tearDown(self):
        self.patch.stop()
        self._tmp.cleanup()

    def fake(self, reply=None, error=None):
        def ask(prompt):
            ai_call_log.set_provider('مزوّد وهمي')
            self.calls.append(prompt)
            if error:
                raise RuntimeError(error)
            return reply
        return ask

    def page(self, ask):
        return qp.CasePageDialog(self.base, cw.read_case_json(self.base), cookies={'s': '1'}, ask=ask)

    def test_rewrite_runs_even_after_approval_and_reports_provider(self):
        import json as _j
        dlg = self.page(self.fake(_j.dumps(STAGE2_REPLY, ensure_ascii=False)))
        dlg.editor.setPlainText('موضوع قديم')
        dlg.approve_current()
        self.assertEqual(cw.read_case_json(self.base)['steps']['subject']['state'], 'reviewed')
        asked = []
        with mock.patch.object(QMessageBox, 'question',          # نص عدّله الخبير بيده ← تأكيد قبل الاستبدال
                               lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.Yes):
            dlg._rewrite('subject')
        self.assertEqual(len(asked), 1)
        self.assertTrue(dlg._busy)
        self.assertTrue(any('جارٍ' in l.text() for l in dlg.card.findChildren(qp.QLabel)))
        wait(dlg)
        self.assertEqual(len(self.calls), 1)                  # المرحلة الثانية: طلب واحد للموضوع والإجراءات والمرفقات
        self.assertEqual(cw.read_case_json(self.base)['subject'], STAGE2_REPLY['subject'])
        text, bad = dlg._notice
        self.assertFalse(bad)
        self.assertIn('تمت إعادة الكتابة', text)
        self.assertIn('مزوّد وهمي', text)
        self.assertEqual(dlg.editor.toPlainText(), STAGE2_REPLY['subject'])

    def test_provider_error_is_shown_in_clear_text(self):
        dlg = self.page(self.fake(error='انتهت الحصة اليومية'))
        dlg._rewrite('subject')
        wait(dlg)
        text, bad = dlg._notice
        self.assertTrue(bad)
        self.assertIn('تعذّرت إعادة الكتابة', text)
        self.assertIn('انتهت الحصة اليومية', text)
        self.assertTrue(any('انتهت الحصة اليومية' in l.text() for l in dlg.card.findChildren(qp.QLabel)))
        import case_stage2
        rec = ai_call_log.last(case_stage2.PURPOSE)
        self.assertEqual((rec['ok'], rec['provider']), (False, 'مزوّد وهمي'))
        with open(ai_call_log.log_path(), encoding='utf-8') as f:
            self.assertIn('انتهت الحصة اليومية', f.read())

    def test_conclusion_rewrite_forces(self):
        d = cw.read_case_json(self.base)
        d['mission'] = {'raw': 'x', 'confirmed': True, 'next_id': 2, 'points': [{'id': 'q1', 'n': 1, 'text': 'أ'}]}
        d['research'] = []
        d['steps']['research'].update(state='done', waived=True)
        d['conclusion'] = {'state': 'done', 'file': '04_تقرير/النتيجة.md',
                           'answers': [{'id': 'q1', 'n': 1, 'point_text': 'أ', 'text': 'قديم', 'source_sha1': 'x',
                                        'missing': False}]}
        d['steps']['conclusion'].update(state='done')
        cw.write_case_json(self.base, d)
        with mock.patch('case_conclusion.run_conclusion', side_effect=lambda b, dd, ask=None, force=False:
                        self.calls.append(force) or 'done'):
            dlg = self.page(self.fake('x'))
            dlg.AUTO_READINESS = False                   # فحص الجاهزية الآلي لا يتدخل في هذا الاختبار
            dlg.open_step('research')
            dlg._rewrite('conclusion')
            wait(dlg)
        self.assertEqual(self.calls, [True])


class LayoutTests(unittest.TestCase):
    """الصفحة لا تُقص: العنوان والأطراف و«السابق» داخل النافذة بعرض صغير، والخطوط بلا مستطيلات رمادية."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        self.data['steps']['documents']['state'] = 'done'     # المستندات أولاً: تُنجَز قبل الموضوع
        cw.write_case_json(self.base, self.data)

    def tearDown(self):
        self._tmp.cleanup()

    def inside(self, dlg, w):
        r = QRect(w.mapTo(dlg, QPoint(0, 0)), w.size())
        return dlg.rect().contains(r)

    def test_small_window_nothing_cut(self):
        dlg = qp.CasePageDialog(self.base, cw.read_case_json(self.base))
        for width, height in ((dlg.minimumWidth(), dlg.minimumHeight()), (900, 600), (1180, 800)):
            dlg.resize(width, height)
            dlg.show()
            APP.processEvents()
            for w in (dlg.parties, dlg.prev_btn, dlg.next_btn, dlg.report_btn, dlg.q_btn):
                self.assertTrue(self.inside(dlg, w), (width, w.text()))
            self.assertGreaterEqual(dlg.prev_btn.width(), dlg.prev_btn.sizeHint().width())
            # RTL: «السابق» أقصى اليمين و«اعتماد والانتقال» أقصى اليسار
            self.assertGreater(dlg.prev_btn.mapTo(dlg, QPoint(0, 0)).x(), dlg.next_btn.mapTo(dlg, QPoint(0, 0)).x())
        dlg.close()

    def test_window_fits_a_small_screen(self):
        dlg = qp.CasePageDialog(self.base, cw.read_case_json(self.base))
        av = APP.primaryScreen().availableGeometry()
        self.assertLessEqual(dlg.width(), av.width())
        self.assertLessEqual(dlg.height(), av.height())

    def test_step_connectors_are_thin_lines_without_background(self):
        dlg = qp.CasePageDialog(self.base, cw.read_case_json(self.base))
        cons = dlg.track.findChildren(qp._Connector)
        self.assertEqual(len(cons), 5)
        self.assertFalse(any(type(w) is qp.QWidget for w in dlg.track.findChildren(qp.QWidget)))
        self.assertTrue(all(c.testAttribute(qp.Qt.WidgetAttribute.WA_TranslucentBackground) for c in cons))


class BidiTitleTests(unittest.TestCase):
    def test_report_button_has_no_latin_word(self):
        import re
        src = open(os.path.join(HERE, 'qt_case_page.py'), encoding='utf-8').read()
        self.assertIn('إصدار التقرير بصيغة وورد', src)
        for m in re.finditer(r"""(?:_btn|setToolTip)[(](?P<q>["'])(?P<t>.*?)(?P=q)[)]""", src):
            text = m.group('t')
            if re.search(r'[؀-ۿ]', text):
                self.assertIsNone(re.search(r'[A-Za-z]{2,}', re.sub(r'\{[^}]*\}', '', text)), text)


if __name__ == '__main__':
    unittest.main()


class NoApproveButtonTests(unittest.TestCase):
    """لا زر «اعتماد» في الخطوات الآلية؛ «اعتماد رأيي» في البحث والنتيجة فقط؛ والتالي بلا تحذير."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        self.data['steps']['documents']['state'] = 'done'     # المستندات أولاً: تُنجَز قبل الموضوع
        cw.write_case_json(self.base, self.data)

    def tearDown(self):
        self._tmp.cleanup()

    def make(self):
        return qp.CasePageDialog(self.base, cw.read_case_json(self.base))

    def buttons(self, dlg):
        return [b.text() for b in dlg.card.findChildren(QPushButton)]

    def test_automatic_steps_have_no_approve_button(self):
        dlg = self.make()
        for k in ('subject', 'mission', 'procedures', 'documents', 'attachments'):
            dlg.open_step(k)
            self.assertNotIn('اعتماد', self.buttons(dlg), k)
            self.assertNotIn('اعتماد رأيي', self.buttons(dlg), k)

    def test_bottom_bar_is_next_and_never_blocks(self):
        dlg = self.make()
        self.assertEqual(dlg.next_btn.text(), 'التالي')
        dlg.open_step('procedures')                      # ناقصة، ومع ذلك ينتقل بلا تحذير
        with mock.patch.object(QMessageBox, 'warning') as w, mock.patch.object(QMessageBox, 'question') as q:
            dlg.next_btn.click()
        w.assert_not_called()
        q.assert_not_called()
        self.assertEqual(dlg._open, 'research')

    def test_complete_subject_is_auto_reviewed_on_reload(self):
        dlg = self.make()
        dlg.editor.setPlainText('موضوع مكتمل')
        dlg.autosave()
        dlg.reload()
        self.assertEqual(cw.read_case_json(self.base)['steps']['subject']['state'], 'reviewed')

    def test_subject_with_todo_stays_needs_input(self):
        dlg = self.make()
        dlg.editor.setPlainText('موضوع [يُكتب] ناقص')
        dlg.autosave()
        dlg.reload()
        self.assertNotEqual(cw.read_case_json(self.base)['steps']['subject']['state'], 'reviewed')

    def test_research_and_conclusion_keep_explicit_review_button(self):
        dlg = self.make()
        d = dlg.data
        d['conclusion'] = {'answers': [{'id': 'q1', 'n': 1, 'point_text': 'ن', 'text': 'ج'}], 'state': 'done'}
        finish(d, 'mission', 'reviewed')
        finish(d, 'documents')
        finish(d, 'research')
        finish(d, 'conclusion')
        cw.write_case_json(self.base, d)
        dlg.reload()
        dlg.open_step('research')                    # النتيجة ضمن البحث
        self.assertIn('اعتماد رأيي', self.buttons(dlg))
