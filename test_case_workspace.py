# اختبارات المرحلة 2أ/2ب (مجلد القضية + منفّذ المراحل): python -m unittest test_case_workspace -v
# بيانات القضية وهمية: test_data/dummy_case.json. المراحل التجريبية تنام أو تفشل عمداً.
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

import case_workspace as cw
import report_pipeline as rp

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)


def sleeper(sec=2):
    def run(_):
        time.sleep(sec)
        return f'نامت {sec} ث'
    return run


def boom(_):
    raise RuntimeError('فشل متعمَّد للاختبار')


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_structure_and_json(self):
        base, data = cw.ensure_workspace(CASE, self.root)
        self.assertEqual(os.path.basename(base), 'A9990001')
        for d in cw.SUBDIRS:
            self.assertTrue(os.path.isdir(os.path.join(base, d)), d)
        on_disk = cw.read_case_json(base)
        self.assertEqual(on_disk['autocase_no'], '999000111')
        self.assertEqual(on_disk['claim_no'], CASE['claim_no'])

    def test_recreates_missing_dir_without_touching_files(self):
        base, _ = cw.ensure_workspace(CASE, self.root)
        mine = os.path.join(base, '_نظام', '04_تقرير', 'تعديلي.docx')
        open(mine, 'wb').write(b'manual')
        os.rmdir(os.path.join(base, '_نظام', '03_حقائق'))
        before = open(os.path.join(base, '_نظام', 'case.json'), 'rb').read()
        cw.ensure_workspace(CASE, self.root)
        self.assertTrue(os.path.isdir(os.path.join(base, '_نظام', '03_حقائق')))
        self.assertEqual(open(mine, 'rb').read(), b'manual')
        self.assertEqual(open(os.path.join(base, '_نظام', 'case.json'), 'rb').read(), before)

    def test_bak_and_corrupt_recovery(self):
        base, data = cw.ensure_workspace(CASE, self.root)
        data['steps']['subject'] = {'state': 'done'}
        cw.write_case_json(base, data)
        self.assertTrue(os.path.exists(os.path.join(base, '_نظام', 'case.json.bak')))
        data['steps']['mission'] = {'state': 'done'}
        cw.write_case_json(base, data)
        open(os.path.join(base, '_نظام', 'case.json'), 'w', encoding='utf-8').write('{نصف ملف')
        rec = cw.read_case_json(base)
        self.assertEqual(rec['steps']['subject']['state'], 'done')
        # الـ .bak السليم لا يُستبدل بنسخة تالفة عند الكتابة التالية
        cw.write_case_json(base, rec)
        self.assertIsNotNone(json.load(open(os.path.join(base, '_نظام', 'case.json.bak'), encoding='utf-8')))
        self.assertFalse([n for n in os.listdir(os.path.join(base, '_نظام')) if n.endswith('.tmp')])

    def test_long_path_rejected(self):
        deep = os.path.join(self.root, 'x' * 200)
        with self.assertRaises(cw.WorkspaceError):
            cw.ensure_workspace(CASE, deep)
        self.assertFalse(os.path.exists(deep))

    def test_bad_caso_no(self):
        for bad in ('', '  ', 'A1/2', '..', 'a:b'):
            with self.assertRaises(cw.WorkspaceError):
                cw.case_dir(bad, self.root)

    def test_foreign_case_json_untouched(self):
        base, data = cw.ensure_workspace(CASE, self.root)
        data['caso_no'] = 'A0000000'
        cw.write_case_json(base, data)
        with self.assertRaises(cw.WorkspaceError):
            cw.ensure_workspace(CASE, self.root)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_failure_does_not_stop_independent_stages(self):
        calls = []
        stages = [
            rp.Stage('fetch', 'جلب', boom),
            rp.Stage('convert', 'تحويل', lambda c: calls.append('convert'), depends=('fetch',)),
            rp.Stage('read', 'قراءة', lambda c: calls.append('read') or 'ok'),
            rp.Stage('write', 'كتابة'),
        ]
        res = rp.Pipeline(self.base, self.data, stages).run()
        self.assertEqual(res, {'fetch': 'failed', 'convert': 'blocked', 'read': 'done', 'write': 'unavailable'})
        self.assertEqual(calls, ['read'])
        saved = cw.read_case_json(self.base)['steps']
        self.assertIn('فشل متعمَّد', saved['fetch']['message'])
        self.assertIn('جلب', saved['convert']['message'])

    def test_resume_skips_done_and_retries_failed(self):
        n = {'fetch': 0, 'convert': 0}
        fail = {'on': True}

        def fetch(_):
            n['fetch'] += 1

        def convert(_):
            n['convert'] += 1
            if fail['on']:
                raise RuntimeError('x')
        stages = [rp.Stage('fetch', 'جلب', fetch), rp.Stage('convert', 'تحويل', convert, ('fetch',))]
        rp.Pipeline(self.base, self.data, stages).run()
        fail['on'] = False
        data2 = cw.read_case_json(self.base)       # «إعادة فتح البرنامج»
        res = rp.Pipeline(self.base, data2, stages).run()
        self.assertEqual(res, {'fetch': 'done', 'convert': 'done'})
        self.assertEqual(n, {'fetch': 1, 'convert': 2})

    def test_default_stages_seven_steps(self):
        res = rp.Pipeline(self.base, self.data, rp.default_stages()).run()
        self.assertEqual(len(res), 7)
        self.assertEqual(res['subject'], 'unavailable')
        self.assertEqual(res['research'], 'blocked')

    def test_progress_callbacks_in_order(self):
        seen = []
        stages = [rp.Stage('fetch', 'جلب', sleeper(0.1))]
        rp.Pipeline(self.base, self.data, stages, on_update=lambda k, r: seen.append(r['state'])).run()
        self.assertEqual(seen, ['running', 'done'])


CHILD = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
import case_workspace as cw, report_pipeline as rp
base = sys.argv[2]
data = cw.read_case_json(base)
def slow(_):
    open(sys.argv[3], 'w').close()   # إشارة: بدأت المرحلة
    time.sleep(30)
rp.Pipeline(base, data, [rp.Stage('fetch', 'جلب', slow)]).run()
'''


class KillResumeTest(unittest.TestCase):
    """يقتل عملية حقيقية أثناء مرحلة تنام، ثم يتأكد أن الاستئناف يعيدها ويكملها."""

    def test_kill_mid_stage_then_resume(self):
        with tempfile.TemporaryDirectory() as root:
            base, data = cw.ensure_workspace(CASE, root)
            flag = os.path.join(root, 'started')
            script = os.path.join(root, 'child.py')
            open(script, 'w', encoding='utf-8').write(CHILD)
            p = subprocess.Popen([sys.executable, script, HERE, base, flag])
            try:
                for _ in range(200):
                    if os.path.exists(flag):
                        break
                    time.sleep(0.05)
                self.assertTrue(os.path.exists(flag), 'العملية الفرعية لم تبدأ المرحلة')
            finally:
                p.kill()
                p.wait()
            data = cw.read_case_json(base)
            self.assertEqual(data['steps']['fetch']['state'], 'running')
            pipe = rp.Pipeline(base, data, [rp.Stage('fetch', 'جلب', sleeper(2))])
            self.assertEqual(pipe.state('fetch'), 'pending')
            t = time.time()
            self.assertEqual(pipe.run(), {'fetch': 'done'})
            self.assertGreaterEqual(time.time() - t, 2)


if __name__ == '__main__':
    unittest.main()
