# اختبارات المرحلة 2م (النتيجة): python -m unittest test_case_conclusion -v
import json
import os
import tempfile
import unittest

import case_conclusion as cc
import case_model as cm
import case_research as cr
import case_workspace as cw

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)


def research_ask(prompt):
    n = int(prompt.split('## البند المطلوب الآن (رقم ', 1)[1].split(')', 1)[0])
    return f'تفصيل البند {n}\n{cr.SUMMARY_MARK}\nخلاصة {n}'


class ConcAsk:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, prompt):
        n = int(prompt.split('## النقطة (رقم ', 1)[1].split(')', 1)[0])
        self.calls.append((n, prompt))
        if n == self.fail_on:
            raise RuntimeError(f'فشل {n}')
        return f'ردّ مباشر على النقطة {n}'


class Base(unittest.TestCase):
    N = 4

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        d = self.data
        d['subject'] = 'نزاع فواتير'
        d['mission'] = {'raw': 'x', 'confirmed': True, 'next_id': self.N + 1,
                        'points': [{'id': f'q{i}', 'n': i, 'text': f'نقطة {i}'} for i in range(1, self.N + 1)]}
        for k in ('mission',):
            cm.set_step(d, k, 'running')
            cm.set_step(d, k, 'done')
            cm.set_step(d, k, 'reviewed')
        d['steps']['documents']['waived'] = True
        cr.run_research(self.base, d, ask=research_ask)
        cw.write_case_json(self.base, d)

    def tearDown(self):
        self._tmp.cleanup()

    def disk(self):
        return cw.read_case_json(self.base)


class RunTests(Base):
    def test_answers_match_points_count_and_ids(self):
        ask = ConcAsk()
        self.assertEqual(cc.run_conclusion(self.base, self.data, ask=ask), 'done')
        d = self.disk()
        self.assertEqual(len(d['conclusion']['answers']), len(d['mission']['points']))
        self.assertTrue(cc.verify_counts(d))
        self.assertEqual([a['id'] for a in d['conclusion']['answers']], ['q1', 'q2', 'q3', 'q4'])
        with open(os.path.join(self.base, cc.REL), encoding='utf-8') as f:
            t = f.read()
        for i in range(1, 5):
            self.assertIn(f'## النقطة {i}: نقطة {i}', t)
            self.assertIn(f'ردّ مباشر على النقطة {i}', t)
        self.assertEqual(d['steps']['conclusion']['state'], 'done')
        self.assertEqual(d['conclusion']['state'], 'done')

    def test_prompt_uses_item_text_of_that_point_only(self):
        ask = ConcAsk()
        cc.run_conclusion(self.base, self.data, ask=ask)
        p2 = ask.calls[1][1]
        self.assertIn('تفصيل البند 2', p2)
        self.assertNotIn('تفصيل البند 3', p2)

    def test_not_started_before_research_complete(self):
        self.data['steps']['research']['waived'] = False
        self.data['research'][2]['state'] = 'failed'
        self.data['steps']['research']['state'] = 'failed'
        with self.assertRaises(cm.StepError):
            cc.run_conclusion(self.base, self.data, ask=ConcAsk())

    def test_explicit_waive_allows_with_fixed_reply_for_missing(self):
        self.data['research'][2]['state'] = 'failed'
        self.data['steps']['research']['state'] = 'failed'
        with self.assertRaises(cm.StepError):
            cc.run_conclusion(self.base, self.data, ask=ConcAsk())
        cc.waive_research(self.base, self.data)
        ask = ConcAsk()
        self.assertEqual(cc.run_conclusion(self.base, self.data, ask=ask), 'done')
        self.assertEqual([n for n, _ in ask.calls], [1, 2, 4])           # النقطة 3 بلا استدعاء
        a3 = self.disk()['conclusion']['answers'][2]
        self.assertTrue(a3['missing'])
        self.assertEqual(a3['text'], cc.MISSING_TEXT)
        self.assertTrue(cc.verify_counts(self.disk()))

    def test_failure_on_one_point_continues_and_retry_only_missing(self):
        ask = ConcAsk(fail_on=2)
        self.assertEqual(cc.run_conclusion(self.base, self.data, ask=ask), 'failed')
        self.assertEqual([n for n, _ in ask.calls], [1, 2, 3, 4])
        self.assertIn('2', self.disk()['steps']['conclusion']['message'])
        self.assertFalse(cc.verify_counts(self.disk()))
        ask2 = ConcAsk()
        self.assertEqual(cc.run_conclusion(self.base, self.data, ask=ask2), 'done')
        self.assertEqual([n for n, _ in ask2.calls], [2])
        self.assertTrue(cc.verify_counts(self.disk()))

    def test_resume_from_partial_disk_state(self):
        class Crash(BaseException):
            pass

        def crash_on_3(prompt):
            if '## النقطة (رقم 3)' in prompt:
                raise Crash()
            return ConcAsk()(prompt)
        with self.assertRaises(Crash):
            cc.run_conclusion(self.base, self.data, ask=crash_on_3)
        d2 = self.disk()
        self.assertEqual([a['id'] for a in d2['conclusion']['answers']], ['q1', 'q2'])
        cm.recover_interrupted(d2)
        ask = ConcAsk()
        self.assertEqual(cc.run_conclusion(self.base, d2, ask=ask), 'done')
        self.assertEqual([n for n, _ in ask.calls], [3, 4])

    def test_done_not_rerun(self):
        cc.run_conclusion(self.base, self.data, ask=ConcAsk())
        ask = ConcAsk()
        self.assertEqual(cc.run_conclusion(self.base, self.data, ask=ask), 'done')
        self.assertEqual(ask.calls, [])


class ChangeTests(Base):
    def test_changed_item_regenerates_only_its_answer(self):
        cc.run_conclusion(self.base, self.data, ask=ConcAsk())
        cr.rewrite_item(self.base, self.data, 'q2', ask=lambda p: 'نص بند ٢ معدّل\n' + cr.SUMMARY_MARK + '\nخلاصة')
        cm.mark_modified(self.data, 'research')
        ask = ConcAsk()
        self.assertEqual(cc.run_conclusion(self.base, self.data, ask=ask), 'done')
        self.assertEqual([n for n, _ in ask.calls], [2])
        self.assertIn('نص بند ٢ معدّل', ask.calls[0][1])

    def test_new_point_and_removed_point_keep_counts_equal(self):
        cc.run_conclusion(self.base, self.data, ask=ConcAsk())
        pts = self.data['mission']['points']
        pts.pop(0)
        for i, p in enumerate(pts, 1):
            p['n'] = i
        pts.append({'id': 'q9', 'n': 4, 'text': 'جديدة'})
        cm.mark_modified(self.data, 'mission')
        cr.run_research(self.base, self.data, ask=research_ask)
        ask = ConcAsk()
        cc.run_conclusion(self.base, self.data, ask=ask)
        d = self.disk()
        self.assertTrue(cc.verify_counts(d))
        self.assertEqual([a['id'] for a in d['conclusion']['answers']], ['q2', 'q3', 'q4', 'q9'])
        self.assertEqual([n for n, _ in ask.calls], [4])                   # الجديدة فقط (أُعيد ترقيم الباقي)

    def test_review(self):
        cc.run_conclusion(self.base, self.data, ask=ConcAsk())
        cc.review_conclusion(self.base, self.data)
        self.assertEqual(self.disk()['steps']['conclusion']['state'], 'reviewed')


if __name__ == '__main__':
    unittest.main()
