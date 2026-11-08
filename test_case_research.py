# اختبارات المرحلة 2ل (البحث ورأي الخبرة): python -m unittest test_case_research -v
import json
import os
import tempfile
import unittest

import case_documents as cd
import case_memory as mem
import case_model as cm
import case_research as cr
import case_workspace as cw

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)


class Crash(BaseException):
    """يحاكي قتل العملية (لا يلتقطه except Exception)."""


class FakeAsk:
    def __init__(self, fail_on=None, crash_on=None):
        self.calls, self.fail_on, self.crash_on = [], fail_on, crash_on

    def __call__(self, prompt):
        m = prompt.split('## البند المطلوب الآن (رقم ', 1)[1]
        n = int(m.split(')', 1)[0])
        self.calls.append((n, prompt))
        if n == self.crash_on:
            raise Crash()
        if n == self.fail_on:
            raise RuntimeError(f'انقطع المزوّد عند {n}')
        return f'نص البند {n} [P1-1]\n{cr.SUMMARY_MARK}\nخلاصة {n}'


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        d = self.data
        d['subject'] = 'نزاع فواتير'
        d['mission'] = {'raw': '1- أ 2- ب 3- ج 4- د 5- ه', 'confirmed': True, 'next_id': 6,
                        'points': [{'id': f'q{i}', 'n': i, 'text': t} for i, t in enumerate(['أ', 'ب', 'ج', 'د', 'ه'], 1)]}
        src = os.path.join(self._tmp.name, 'a.pdf')
        open(src, 'wb').write(b'x')
        p = cd.add_portfolio(d, 'المدعية', '2026-09-01')
        cd.import_batch(self.base, d, p['id'], [{'src': src, 'no': 1}],
                        convert=lambda path: ('<!-- صفحة 1 -->\nنص العقد الأصلي', 1),
                        classify=lambda path: {'type': 'محضر أعمال', 'confidence': 1.0, 'reason': 'اختبار'})
        for k in ('mission',):
            cm.set_step(d, k, 'running')
            cm.set_step(d, k, 'done')
            cm.set_step(d, k, 'reviewed')
        cw.write_case_json(self.base, d)

    def tearDown(self):
        self._tmp.cleanup()

    def disk(self):
        return cw.read_case_json(self.base)

    def item_file(self, n):
        return os.path.join(self.base, '_نظام', '04_تقرير', 'بنود', f'{n:02d}.md')


class PromptTests(Base):
    def test_prompt_contains_docs_registry_and_previous_summaries_only(self):
        ask = FakeAsk()
        self.assertEqual(cr.run_research(self.base, self.data, ask=ask), 'done')
        p1, p2, p3 = ask.calls[0][1], ask.calls[1][1], ask.calls[2][1]
        for p in (p1, p2):
            self.assertIn('نص العقد الأصلي', p)
            self.assertIn('| P1 |', p)
            self.assertIn('نزاع فواتير', p)
        self.assertNotIn('ملخص البنود السابقة', p1)
        self.assertIn('خلاصة 1', p2)
        self.assertNotIn('خلاصة 2', p2)
        self.assertIn('خلاصة 1', p3)
        self.assertIn('خلاصة 2', p3)

    def test_large_docs_are_truncated_by_budget(self):
        _, d = self.data['portfolios'][0], self.data['portfolios'][0]['docs'][0]
        with open(os.path.join(self.base, d['md']), 'w', encoding='utf-8') as f:
            f.write('ك' * 5000)
        old = cr.MAX_PROMPT_CHARS
        cr.MAX_PROMPT_CHARS = 100
        try:
            texts = cr._doc_texts(self.base, self.data, budget=100)
        finally:
            cr.MAX_PROMPT_CHARS = old
        self.assertLess(len(texts[0][1]), 800)
        self.assertIn('مقتطع', texts[0][1])

    def test_split_response(self):
        self.assertEqual(cr.split_response(f'نص\n{cr.SUMMARY_MARK}\nملخص  قصير'), ('نص', 'ملخص قصير'))
        body, summ = cr.split_response('نص بلا علامة')
        self.assertEqual((body, summ), ('نص بلا علامة', 'نص بلا علامة'))


class LoopTests(Base):
    def test_full_run_writes_files_json_and_progress(self):
        seen = []
        self.assertEqual(cr.run_research(self.base, self.data, ask=FakeAsk(), on_item=lambda i: seen.append(i['n'])), 'done')
        self.assertEqual(seen, [1, 2, 3, 4, 5])
        d = self.disk()
        self.assertEqual([i['state'] for i in d['research']], ['done'] * 5)
        self.assertEqual(d['steps']['research']['progress'], {'done': 5, 'total': 5})
        for n in range(1, 6):
            self.assertTrue(os.path.exists(self.item_file(n)))
        self.assertEqual(d['research'][0]['id'], 'q1')
        self.assertEqual(len(d['research'][0]['sha1']), 40)
        with open(mem.memory_path(self.base), encoding='utf-8', newline='') as f:
            t = f.read()
        self.assertIn('نص البند 3', t)
        self.assertNotIn('بصمة', t.split('البنود المكتوبة')[1])

    def test_each_item_saved_immediately(self):
        ask = FakeAsk(crash_on=3)
        with self.assertRaises(Crash):
            cr.run_research(self.base, self.data, ask=ask)
        d = self.disk()                                   # ما على القرص لحظة «الانقطاع»
        self.assertEqual([i['state'] for i in d['research']][:2], ['done', 'done'])
        self.assertTrue(os.path.exists(self.item_file(2)))
        self.assertFalse(os.path.exists(self.item_file(3)))
        self.assertEqual(d['steps']['research']['progress']['done'], 2)

    def test_resume_after_cut_after_item_2(self):
        with self.assertRaises(Crash):
            cr.run_research(self.base, self.data, ask=FakeAsk(crash_on=3))
        data2 = cw.read_case_json(self.base)              # «إعادة فتح البرنامج»
        self.assertTrue(cm.recover_interrupted(data2))
        self.assertEqual(cm.state(data2, 'research'), 'pending')
        ask = FakeAsk()
        self.assertEqual(cr.run_research(self.base, data2, ask=ask), 'done')
        self.assertEqual([n for n, _ in ask.calls], [3, 4, 5])
        self.assertIn('خلاصة 2', ask.calls[0][1])
        self.assertEqual(cw.read_case_json(self.base)['steps']['research']['progress'], {'done': 5, 'total': 5})

    def test_failure_stops_loop_keeps_done_and_retry_continues(self):
        ask = FakeAsk(fail_on=3)
        self.assertEqual(cr.run_research(self.base, self.data, ask=ask), 'failed')
        d = self.disk()
        self.assertEqual([i['state'] for i in d['research']], ['done', 'done', 'failed', 'pending', 'pending'])
        self.assertIn('البند 3', d['steps']['research']['message'])
        self.assertEqual([n for n, _ in ask.calls], [1, 2, 3])
        ask2 = FakeAsk()
        self.assertEqual(cr.run_research(self.base, self.data, ask=ask2), 'done')
        self.assertEqual([n for n, _ in ask2.calls], [3, 4, 5])

    def test_empty_response_is_failure(self):
        self.assertEqual(cr.run_research(self.base, self.data, ask=lambda p: '  '), 'failed')
        self.assertIn('فارغ', self.disk()['research'][0]['message'])

    def test_stop_between_items(self):
        n = {'v': 0}
        ask = FakeAsk()

        def stop():
            n['v'] += 1
            return n['v'] > 2                              # يُسمح ببندين ثم يتوقف
        self.assertEqual(cr.run_research(self.base, self.data, ask=ask, stop=stop), 'pending')
        self.assertEqual([k for k, _ in ask.calls], [1, 2])
        self.assertEqual(cm.state(self.data, 'research'), 'pending')

    def test_requires_reviewed_mission_and_documents(self):
        d = self.data
        d['steps']['mission']['state'] = 'done'
        with self.assertRaises(cm.StepError):
            cr.run_research(self.base, d, ask=FakeAsk())
        d['steps']['mission']['state'] = 'reviewed'
        d['steps']['documents']['state'] = 'failed'
        with self.assertRaises(cm.StepError):
            cr.run_research(self.base, d, ask=FakeAsk())
        cd.waive_documents(self.base, d)
        self.assertEqual(cr.run_research(self.base, d, ask=FakeAsk()), 'done')

    def test_done_not_rerun(self):
        cr.run_research(self.base, self.data, ask=FakeAsk())
        ask = FakeAsk()
        self.assertEqual(cr.run_research(self.base, self.data, ask=ask), 'done')
        self.assertEqual(ask.calls, [])


class StaleAndEditTests(Base):
    def test_rewrite_item_marks_later_stale_not_regenerated(self):
        cr.run_research(self.base, self.data, ask=FakeAsk())
        ask = FakeAsk()
        self.assertEqual(cr.rewrite_item(self.base, self.data, 'q2', ask=ask), 'done')
        self.assertEqual([n for n, _ in ask.calls], [2])
        st = {i['n']: i.get('stale', False) for i in self.disk()['research']}
        self.assertEqual(st, {1: False, 2: False, 3: True, 4: True, 5: True})

    def test_mission_point_text_change_marks_item_stale_and_new_point_added(self):
        cr.run_research(self.base, self.data, ask=FakeAsk())
        pts = self.data['mission']['points']
        pts[1]['text'] = 'ب معدّلة'
        pts.append({'id': 'q6', 'n': 6, 'text': 'و'})
        cm.mark_modified(self.data, 'mission')            # كما يفعل set_mission
        ask = FakeAsk()
        self.assertEqual(cr.run_research(self.base, self.data, ask=ask), 'done')
        self.assertEqual([n for n, _ in ask.calls], [6])   # الجديد فقط؛ المعدّل ينتظر قرار الخبير
        st = {i['n']: i.get('stale', False) for i in self.disk()['research']}
        self.assertTrue(st[2])
        ask = FakeAsk()
        cr.run_research(self.base, self.data, ask=ask, include_stale=True)
        # إعادة كتابة 2 تُقدِّم قِدَم ما بعده (سلسلة الملخصات) فيُحدَّث معه عند طلب include_stale
        self.assertEqual([n for n, _ in ask.calls], [2, 3, 4, 5, 6])

    def test_removed_point_drops_item_keeps_file_ids_stable_after_reorder(self):
        cr.run_research(self.base, self.data, ask=FakeAsk())
        pts = self.data['mission']['points']
        removed = pts.pop(0)
        for i, p in enumerate(pts, 1):
            p['n'] = i
        cm.mark_modified(self.data, 'mission')
        cr.run_research(self.base, self.data, ask=FakeAsk())
        ids = [i['id'] for i in self.disk()['research']]
        self.assertNotIn(removed['id'], ids)
        self.assertEqual(ids, ['q2', 'q3', 'q4', 'q5'])
        self.assertTrue(os.path.exists(self.item_file(1)))  # الملف القديم لم يُحذف

    def test_review_item(self):
        cr.run_research(self.base, self.data, ask=FakeAsk())
        cr.review_item(self.base, self.data, 'q1')
        self.assertEqual(self.disk()['research'][0]['state'], 'reviewed')
        with self.assertRaises(cm.StepError):
            cr.review_item(self.base, self.data, 'nope')


if __name__ == '__main__':
    unittest.main()
