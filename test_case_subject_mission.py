# اختبارات المرحلة 2ح (الموضوع والمأمورية): python -m unittest test_case_subject_mission -v
import case_subject_mission as _sm_style
_sm_style.STYLE = 'formula'          # هذه الاختبارات للقوالب القديمة؛ الكتابة بالذكاء في test_subject_style.py
import json
import os
import tempfile
import unittest

import case_memory as mem
import case_model as cm
import case_subject_mission as sm
import test_case_subject_contract as tc
import case_workspace as cw

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)

MISSION_NUM = """ندبت المحكمة الخبير للقيام بالآتي:
1- بيان قيمة الفواتير المستحقة.
2- بيان ما تم سداده منها.
٣- بيان رصيد المدعية بعد السداد."""


class SplitTests(unittest.TestCase):
    def test_numbered_lines_with_preamble(self):
        self.assertEqual(sm.split_points(MISSION_NUM),
                         ['بيان قيمة الفواتير المستحقة', 'بيان ما تم سداده منها', 'بيان رصيد المدعية بعد السداد'])

    def test_inline_numbers(self):
        self.assertEqual(sm.split_points('1- بيان الفواتير 2- بيان السداد'), ['بيان الفواتير', 'بيان السداد'])

    def test_parenthesis_and_dot(self):
        self.assertEqual(sm.split_points('1) أ\n2) ب'), ['أ', 'ب'])
        self.assertEqual(sm.split_points('1. أ\n2. ب'), ['أ', 'ب'])

    def test_ordinals(self):
        t = 'أولاً: فحص العقد.\nثانياً: بيان المستحقات.\nثالثًا: تحديد التعويض.'
        self.assertEqual(sm.split_points(t), ['فحص العقد', 'بيان المستحقات', 'تحديد التعويض'])

    def test_dates_and_amounts_not_split(self):
        t = 'بيان المستحق عن عقد رقم 2026/1234 بقيمة 1.5 مليون وفق 12 - 5 فاتورة'
        self.assertEqual(sm.split_points(t), [t])

    def test_bullets(self):
        self.assertEqual(sm.split_points('- بيان أ\n- بيان ب'), ['بيان أ', 'بيان ب'])

    def test_single_and_empty(self):
        self.assertEqual(sm.split_points('بيان ما إذا كان العقد صحيحاً'), ['بيان ما إذا كان العقد صحيحاً'])
        self.assertEqual(sm.split_points('  '), [])
        self.assertEqual(sm.split_points('1- نقطة وحيدة'), ['نقطة وحيدة'])

    def test_run_must_start_at_one(self):
        self.assertEqual(len(sm.split_points('2- أ\n3- ب')), 1)

    def test_word_thalith_in_sentence_not_a_marker(self):
        t = 'بيان مسؤولية طرف ثالث عن التأخير وأول مرة'
        self.assertEqual(sm.split_points(t), [t])


class StepTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        self.row = {'case_summary': 'نزاع حول فواتير خدمات', 'mission_text': MISSION_NUM}
        self.get = lambda no: self.row
        self.plaint = tc.PLAINT

    def run_s(self, get=None, **kw):
        """الموضوع (غير الاتصالات) بصيغة العقد العام من الصحيفة — لا ملخص حر."""
        kw.setdefault('ask', tc.ask_with(tc.REPLY))
        kw.setdefault('claim_fn', lambda: self.plaint)
        kw.setdefault('companies', tc.COMPANIES)
        return sm.run_subject(self.base, self.data, get or self.get, **kw)

    def tearDown(self):
        self._tmp.cleanup()

    def disk(self):
        return cw.read_case_json(self.base)

    def test_subject_auto_done_and_persisted_with_memory(self):
        self.assertEqual(self.run_s(), 'done')
        d = self.disk()
        self.assertEqual(d['subject'], tc.EXPECTED)
        self.assertEqual(d['steps']['subject']['state'], 'done')
        with open(mem.memory_path(self.base), encoding='utf-8', newline='') as f:
            self.assertIn('فتم رفع الدعوى الماثلة', f.read())

    def test_subject_missing_needs_input_then_manual(self):
        self.row = {}
        self.assertEqual(sm.run_subject(self.base, self.data, self.get), 'needs_input')
        self.assertEqual(sm.set_subject(self.base, self.data, 'موضوع يدوي'), 'done')
        sm.review_subject(self.base, self.data)
        self.assertEqual(self.disk()['steps']['subject']['state'], 'reviewed')
        # تعديله بعد المراجعة يعيده «كُتبت»
        self.assertEqual(sm.set_subject(self.base, self.data, 'موضوع ثانٍ'), 'done')

    def test_subject_db_error_marks_failed_and_retry_works(self):
        def boom(_):
            raise RuntimeError('القاعدة مقفلة')
        self.assertEqual(sm.run_subject(self.base, self.data, boom), 'failed')
        self.assertIn('القاعدة مقفلة', self.disk()['steps']['subject']['message'])
        self.assertEqual(self.run_s(), 'done')

    def test_done_subject_untouched_without_force(self):
        self.run_s()
        self.plaint = 'صحيفة أخرى تماماً'
        self.run_s()
        self.assertEqual(self.data['subject'], tc.EXPECTED)

    def test_mission_flow_needs_input_then_confirm(self):
        self.assertEqual(sm.run_mission(self.base, self.data, self.get), 'needs_input')
        m = self.disk()['mission']
        self.assertEqual([p['n'] for p in m['points']], [1, 2, 3])
        self.assertEqual(len({p['id'] for p in m['points']}), 3)
        self.assertFalse(m['confirmed'])
        self.assertEqual(sm.confirm_mission(self.base, self.data), 'reviewed')
        d = self.disk()
        self.assertTrue(d['mission']['confirmed'])
        self.assertEqual(d['steps']['mission']['state'], 'reviewed')

    def test_mission_missing_text(self):
        self.row = {}
        self.assertEqual(sm.run_mission(self.base, self.data, self.get), 'needs_input')
        with self.assertRaises(cm.StepError):
            sm.confirm_mission(self.base, self.data)
        sm.set_mission(self.base, self.data, raw='1- أ 2- ب')
        self.assertEqual(sm.confirm_mission(self.base, self.data), 'reviewed')

    def test_edit_points_keeps_ids_of_unchanged_and_unconfirms(self):
        sm.run_mission(self.base, self.data, self.get)
        sm.confirm_mission(self.base, self.data)
        ids = {p['text']: p['id'] for p in self.data['mission']['points']}
        t = list(ids)
        sm.set_mission(self.base, self.data, points=[t[2], t[0], 'نقطة جديدة'])
        pts = self.data['mission']['points']
        self.assertEqual([p['n'] for p in pts], [1, 2, 3])
        self.assertEqual(pts[0]['id'], ids[t[2]])         # المعرّف يتبع النص لا الرقم
        self.assertEqual(pts[1]['id'], ids[t[0]])
        self.assertNotIn(pts[2]['id'], ids.values())
        self.assertFalse(self.data['mission']['confirmed'])
        self.assertEqual(cm.state(self.data, 'mission'), 'done')       # عُدِّلت بعد الاعتماد ← «كُتبت» لا «راجعها الخبير"

    def test_edit_after_review_marks_downstream_stale_not_regenerated(self):
        sm.run_mission(self.base, self.data, self.get)
        sm.confirm_mission(self.base, self.data)
        self.data['steps']['documents'] = dict(cm.new_step(), state='done')
        cm.set_step(self.data, 'research', 'running')
        cm.set_step(self.data, 'research', 'done')
        sm.set_mission(self.base, self.data, points=['واحدة'])
        self.assertTrue(self.disk()['steps']['research']['stale'])
        self.assertEqual(self.disk()['steps']['research']['state'], 'done')

    def test_research_blocked_until_mission_reviewed(self):
        sm.run_mission(self.base, self.data, self.get)
        cm.refresh_blocked(self.data)
        self.assertEqual(cm.state(self.data, 'research'), 'blocked')
        sm.confirm_mission(self.base, self.data)
        self.data['steps']['documents']['state'] = 'done'
        self.assertTrue(cm.can_start(self.data, 'research')[0])

    def test_memory_failure_does_not_fail_step(self):
        # مجلد باسم الذاكرة يجعل كتابتها تفشل؛ الخطوة تبقى done و case.json سليم
        os.makedirs(mem.memory_path(self.base))
        self.assertEqual(self.run_s(), 'done')
        self.assertEqual(self.disk()['steps']['subject']['state'], 'done')


if __name__ == '__main__':
    unittest.main()
