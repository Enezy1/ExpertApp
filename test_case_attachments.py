# اختبارات المرفقات (2ك، أُعيدت 2026-10-17): python -m unittest test_case_attachments -v
# تُبنى فوراً من المحاضر («عدد ( N ) محضر أعمال.») ثم تُضاف الحوافظ بعبارة الإحالة المعتمدة، بلا انتظار أي خطوة.
import json
import os
import tempfile
import unittest

import case_attachments as ca
import case_model as cm
import case_workspace as cw

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)

CONV = {'state': 'done', 'message': ''}


def add_minutes(data, n):
    data['sessions']['minutes'] = [{'no': i, 'date': '', 'file': f'C:/m/{i}.docx', 'md': ''} for i in range(1, n + 1)]


def add_portfolios(data):
    data['portfolios'] = [
        {'id': 'P2', 'submitter': 'المدعى عليها', 'date': '2026-10-01', 'seq': 1, 'docs': [
            {'uid': 'd9', 'no': 1, 'file': '01_اصول/P2/001.pdf', 'type': '', 'contract': '', 'convert': CONV}]},
        {'id': 'P1', 'submitter': 'المدعية', 'date': '2021-11-08', 'seq': 3, 'docs': [
            {'uid': 'd1', 'no': 1, 'file': '01_اصول/P1/001.pdf', 'type': 'صور توكيل', 'contract': '', 'convert': CONV},
            {'uid': 'd2', 'no': 2, 'file': '01_اصول/P1/002.pdf', 'type': 'صور توكيل', 'contract': '', 'convert': CONV},
            {'uid': 'd3', 'no': 3, 'file': '', 'type': 'خطاب', 'contract': '',
             'convert': {'state': 'failed', 'message': 'تعذّر نسخ'}}]},
    ]


class BuildTests(unittest.TestCase):
    def test_minutes_only_is_enough(self):
        d = cm.new_case_data(CASE)
        add_minutes(d, 7)
        self.assertEqual([(a['kind'], a['title']) for a in ca.build_attachments(d)],
                         [('minutes', 'عدد ( 7 ) محضر أعمال.')])

    def test_portfolios_use_agreed_wording_in_creation_order(self):
        d = cm.new_case_data(CASE)
        add_minutes(d, 7)
        add_portfolios(d)
        got = [a['title'] for a in ca.build_attachments(d)]
        self.assertEqual(got[:3], ['عدد ( 7 ) محضر أعمال.',             # المدعية ثم المدعى عليه، تاريخياً
                                   'حافظة مستندات المدعية المؤرخة 08/11/2021.',
                                   'حافظة مستندات المدعى عليها المؤرخة 01/10/2026.'])
        self.assertIn('لم تُقرأ المرفقات من المحاضر', got[3])          # من المستندات لا المحاضر ← ملاحظة
        self.assertEqual([a['no'] for a in ca.build_attachments(d)], [1, 2, 3, None])

    def test_empty(self):
        d = cm.new_case_data(CASE)
        self.assertEqual(ca.build_attachments(d), [])
        self.assertIn('لا مرفقات', ca.render_md([]))

    def test_failed_copy_is_not_attached(self):
        d = cm.new_case_data(CASE)
        d['portfolios'] = [{'id': 'P1', 'submitter': 'المدعية', 'date': '', 'seq': 1, 'docs': [
            {'uid': 'd1', 'no': 1, 'file': '', 'type': '', 'contract': '', 'convert': {'state': 'failed'}}]}]
        self.assertEqual(ca.build_attachments(d), [])


class SyncTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_builds_immediately_without_other_steps(self):
        add_minutes(self.data, 3)
        self.assertTrue(ca.sync_attachments(self.base, self.data))
        d = cw.read_case_json(self.base)
        self.assertEqual(cm.state(d, 'attachments'), 'done')
        self.assertEqual([a['title'] for a in d['attachments']], ['عدد ( 3 ) محضر أعمال.'])
        with open(os.path.join(self.base, ca.REL), encoding='utf-8') as f:
            self.assertIn('1. عدد ( 3 ) محضر أعمال.', f.read())

    def test_nothing_yet_waits_quietly(self):
        self.assertTrue(ca.sync_attachments(self.base, self.data))
        self.assertEqual(cm.state(self.data, 'attachments'), 'needs_input')
        self.assertFalse(ca.sync_attachments(self.base, self.data))        # لا كتابة متكررة بلا تغيير

    def test_grows_automatically_when_portfolio_added(self):
        add_minutes(self.data, 2)
        ca.sync_attachments(self.base, self.data)
        self.assertFalse(ca.sync_attachments(self.base, self.data))        # لا تغيير ← لا كتابة
        add_portfolios(self.data)
        self.assertTrue(ca.sync_attachments(self.base, self.data))
        self.assertEqual(len(self.data['attachments']), 4)
        self.assertEqual(cm.state(self.data, 'attachments'), 'done')

    def test_edit_after_review_returns_to_done(self):
        add_minutes(self.data, 2)
        ca.sync_attachments(self.base, self.data)
        cm.set_step(self.data, 'attachments', 'reviewed')
        add_minutes(self.data, 3)
        ca.sync_attachments(self.base, self.data)
        self.assertEqual(cm.state(self.data, 'attachments'), 'done')

    def test_run_attachments_force(self):
        add_minutes(self.data, 2)
        self.assertEqual(ca.run_attachments(self.base, self.data, force=True), 'done')

    def test_old_v2_case_gains_attachments_key(self):
        d = cm.new_case_data(CASE)
        del d['attachments']
        d2, changed = cm.migrate(d)
        self.assertTrue(changed)
        self.assertEqual(d2['attachments'], [])


if __name__ == '__main__':
    unittest.main()
