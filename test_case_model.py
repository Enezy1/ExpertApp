# اختبارات المرحلة 2هـ (نموذج الحالات): python -m unittest test_case_model -v
import json
import os
import tempfile
import unittest

import case_model as cm
import case_workspace as cw

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)


def fresh():
    return cm.new_case_data(CASE)


def finish(d, key, final='done'):
    cm.set_step(d, key, 'running')
    cm.set_step(d, key, 'done')
    if final == 'reviewed':
        cm.set_step(d, key, 'reviewed')


class MigrationTests(unittest.TestCase):
    V1 = {'schema': 1, 'caso_no': 'A9990001', 'autocase_no': '1', 'claim_no': '2', 'case': {},
          'created': 'c', 'updated': 'u', 'stages': {'fetch': {'state': 'done'}}, 'files': {'x': 1}}

    def test_v1_to_v2(self):
        d, changed = cm.migrate(json.loads(json.dumps(self.V1)))
        self.assertTrue(changed)
        self.assertEqual(d['schema'], 2)
        self.assertEqual(set(d['steps']), set(cm.STEP_KEYS))
        self.assertNotIn('stages', d)
        self.assertEqual(d['legacy_stages']['fetch']['state'], 'done')
        self.assertEqual(d['updated_at'], 'u')
        self.assertEqual(d['files'], {'x': 1})
        self.assertEqual(d['mission'], {'raw': '', 'points': [], 'confirmed': False})

    def test_idempotent(self):
        d, _ = cm.migrate(json.loads(json.dumps(self.V1)))
        d2, changed = cm.migrate(json.loads(json.dumps(d)))
        self.assertFalse(changed)
        self.assertEqual(d, d2)

    def test_future_schema_not_downgraded(self):
        d, _ = cm.migrate({'schema': 3, 'caso_no': 'x'})
        self.assertEqual(d['schema'], 3)

    def test_workspace_migrates_on_disk_and_keeps_bak(self):
        with tempfile.TemporaryDirectory() as root:
            base = cw.case_dir(CASE['caso_no'], root)
            os.makedirs(base)
            v1 = dict(self.V1, caso_no=CASE['caso_no'])
            with open(os.path.join(base, 'case.json'), 'w', encoding='utf-8') as f:
                json.dump(v1, f)
            _, data = cw.ensure_workspace(CASE, root)
            self.assertEqual(data['schema'], 2)
            with open(os.path.join(base, '_نظام', 'case.json'), encoding='utf-8') as f:      # رُحِّل إلى _نظام
                self.assertEqual(json.load(f)['schema'], 2)
            with open(os.path.join(base, '_نظام', 'case.json.bak'), encoding='utf-8') as f:
                self.assertEqual(json.load(f)['schema'], 1)


class TransitionTests(unittest.TestCase):
    def test_allowed_and_forbidden(self):
        d = fresh()
        cm.set_step(d, 'subject', 'running')
        cm.set_step(d, 'subject', 'done', 'تم')
        cm.set_step(d, 'subject', 'reviewed')
        self.assertEqual(d['steps']['subject']['attempts'], 1)
        with self.assertRaises(cm.StepError):
            cm.set_step(d, 'procedures', 'done')        # pending ← done ممنوع
        with self.assertRaises(cm.StepError):
            cm.set_step(d, 'procedures', 'reviewed')
        with self.assertRaises(cm.StepError):
            cm.set_step(d, 'procedures', 'bogus')

    def test_running_to_needs_input_to_reviewed(self):
        d = fresh()
        cm.set_step(d, 'mission', 'running')
        cm.set_step(d, 'mission', 'needs_input')
        cm.set_step(d, 'mission', 'reviewed')
        self.assertEqual(cm.state(d, 'mission'), 'reviewed')


class DependencyTests(unittest.TestCase):
    def test_research_needs_reviewed_mission_and_documents(self):
        d = fresh()
        self.assertFalse(cm.can_start(d, 'research')[0])
        finish(d, 'mission', 'done')                      # كُتبت فقط، لم تُراجَع
        finish(d, 'documents')
        self.assertFalse(cm.can_start(d, 'research')[0])
        cm.set_step(d, 'mission', 'reviewed')
        self.assertTrue(cm.can_start(d, 'research')[0])

    def test_running_refused_when_unmet(self):
        d = fresh()
        with self.assertRaises(cm.StepError):
            cm.set_step(d, 'conclusion', 'running')

    def test_documents_waiver_lets_research_proceed(self):
        d = fresh()
        finish(d, 'mission', 'reviewed')
        self.assertFalse(cm.can_start(d, 'research')[0])
        d['steps']['documents']['waived'] = True
        self.assertTrue(cm.can_start(d, 'research')[0])
        d['steps']['procedures']['state'] = 'done'
        self.assertTrue(cm.can_start(d, 'attachments')[0])     # المرفقات لا تعتمد على غيرها (تُبنى آلياً)

    def test_failure_blocks_dependents_only(self):
        d = fresh()
        finish(d, 'mission', 'reviewed')
        cm.set_step(d, 'documents', 'running')
        cm.set_step(d, 'documents', 'failed', 'ملف تالف')
        cm.refresh_blocked(d)
        self.assertEqual(cm.state(d, 'research'), 'blocked')
        self.assertEqual(cm.state(d, 'attachments'), 'pending')   # لا اعتماد للمرفقات على المستندات
        self.assertEqual(cm.state(d, 'procedures'), 'pending')   # مستقلة
        self.assertIn('المستندات', d['steps']['research']['message'])
        # الإصلاح يفكّ الحجب
        finish(d, 'documents')
        self.assertEqual(cm.state(d, 'research'), 'pending')

    def test_blocked_not_run_but_next_actionable_skips_it(self):
        d = fresh()
        cm.refresh_blocked(d)
        self.assertEqual(cm.next_actionable(d), 'subject')
        finish(d, 'subject')
        self.assertEqual(cm.next_actionable(d), 'mission')


class StaleTests(unittest.TestCase):
    def build(self):
        d = fresh()
        for k in ('mission', 'procedures', 'documents'):
            finish(d, k, 'reviewed')
        finish(d, 'attachments')
        finish(d, 'research')
        finish(d, 'conclusion')
        return d

    def test_rerun_marks_dependents_stale_not_regenerated(self):
        d = self.build()
        cm.set_step(d, 'mission', 'running')
        self.assertTrue(d['steps']['research'].get('stale'))
        self.assertTrue(d['steps']['conclusion'].get('stale'))        # متعدٍّ
        self.assertFalse(d['steps'].get('attachments', {}).get('stale'))
        self.assertEqual(cm.state(d, 'research'), 'done')             # لم يُعد توليده
        self.assertNotEqual(cm.next_actionable(d), 'research')

    def test_documents_change_stales_research_and_conclusion(self):
        d = self.build()
        cm.mark_modified(d, 'documents')
        self.assertTrue(d['steps']['research']['stale'])
        self.assertTrue(d['steps']['conclusion']['stale'])

    def test_stale_cleared_on_regeneration(self):
        d = self.build()
        cm.mark_modified(d, 'mission')
        finish(d, 'research')
        self.assertFalse(d['steps']['research']['stale'])


class ResumeTests(unittest.TestCase):
    def test_interrupted_running_returns_to_pending_via_disk(self):
        with tempfile.TemporaryDirectory() as root:
            base, d = cw.ensure_workspace(CASE, root)
            cm.set_step(d, 'subject', 'running')
            cw.write_case_json(base, d)
            d2 = cw.read_case_json(base)
            self.assertTrue(cm.recover_interrupted(d2))
            self.assertEqual(cm.state(d2, 'subject'), 'pending')
            self.assertEqual(cm.next_actionable(d2), 'subject')

class EditAfterApprovalTests(unittest.TestCase):
    def test_reviewed_can_return_to_done(self):
        d = fresh()
        finish(d, 'subject', 'reviewed')
        cm.set_step(d, 'subject', 'done', 'عُدِّل بعد الاعتماد')
        self.assertEqual(cm.state(d, 'subject'), 'done')

    def test_subject_edit_stales_research_and_conclusion(self):
        d = fresh()
        for k in ('mission',):
            finish(d, k, 'reviewed')
        finish(d, 'documents')
        finish(d, 'research')
        finish(d, 'conclusion')
        cm.mark_modified(d, 'subject')
        self.assertEqual(sorted(cm.stale_labels(d, 'subject')), sorted(['البحث ورأي الخبرة', 'النتيجة']))



if __name__ == '__main__':
    unittest.main()
