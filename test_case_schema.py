# -*- coding: utf-8 -*-
"""
test_case_schema.py — اختبارات عقد بيانات القضية (case_schema.py)

تثبت ست أشياء:
  1) الفحص يكتشف الخانة الغلط الشكل ويسمّيها (مفتاح + متوقّع + موجود).
  2) الإصلاح يحوّل «subject_missing» من قائمة إلى قاموس **مع حفظ المحتوى**.
  3) الإصلاح يضيف الناقص فقط — ما يحذف أي معلومة أبداً.
  4) **الاختبار المرجعي**: بعد الإصلاح، `doc_router.step_alerts` ما يرمي
     استثناء — هي المشكلة الفعلية (17 انهيار في crash_log.txt بين 21/10 و25/10).
  5) الرقعة (install) تفحص وتصلّح عند القراءة، و`uninstall` يرجّع الأصل.
  6) الفحص الشامل (scan) يلقى القضايا المعطوبة في مجلد مؤقت.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import case_schema


def _good():
    """دفتر قضية سليم — كما يكتبه البرنامج فعلياً."""
    return {
        'caso_no': 'A2263973',
        'autocase_no': 'A2263973',
        'claim_no': '12345',
        'created': '2026-10-20T14:09:00',
        'updated_at': '2026-10-26T01:06:56',
        'updated_on': 'PC',
        'schema': 2,
        'subject': 'موضوع القضية',
        'subject_prev': '',
        'subject_source': 'stage2',
        'subject_edited': False,
        'subject_missing': {'unverified': [], 'absent': ['المبلغ الشهري'], 'models': []},
        'subject_alerts': [['amber', 'لم يرد في الصحيفة: المبلغ الشهري']],
        'subject_facts': {'amount': 144},
        'steps': {'subject': {'state': 'done', 'message': '', 'at': '', 'attempts': 1}},
        'mission': {'raw': '', 'points': [], 'confirmed': False},
        'sessions': {'count_system': None, 'minutes': []},
        'research': [],
        'research2': {},
        'conclusion': {'state': 'pending'},
        'files': {},
        'portfolios': [],
        'attachments': [],
        'written_by': {'subject': {'provider': 'gemini', 'model': 'flash'}},
    }


class ValidateTests(unittest.TestCase):
    """الفحص — يشوف الخانة الغلط بلا ما يعدّل."""

    def test_clean_data_has_no_problems(self):
        self.assertEqual(case_schema.validate(_good()), [])

    def test_detects_subject_missing_written_as_list(self):
        """المشكلة الفعلية: report_v3 كتبها قائمة."""
        data = _good()
        data['subject_missing'] = ['المبلغ الشهري', 'مدة الالتزام']
        problems = case_schema.validate(data)
        self.assertEqual(len(problems), 1)
        p = problems[0]
        self.assertEqual(p.key, 'subject_missing')
        self.assertEqual(p.expected, 'قاموس')
        self.assertEqual(p.actual, 'قائمة')
        self.assertTrue(p.fixable)

    def test_detects_wrong_type_on_plain_key(self):
        data = _good()
        data['steps'] = ['a', 'b']
        problems = case_schema.validate(data)
        self.assertEqual([p.key for p in problems], ['steps'])

    def test_detects_string_step_value(self):
        data = _good()
        data['steps']['research'] = 'done'
        problems = case_schema.validate(data)
        self.assertEqual([p.key for p in problems], ['steps.research'])
        self.assertTrue(problems[0].fixable)

    def test_detects_malformed_alert_item(self):
        data = _good()
        data['subject_alerts'] = ['نص واحد']
        problems = case_schema.validate(data)
        self.assertEqual([p.key for p in problems], ['subject_alerts[0]'])

    def test_detects_written_by_value_not_dict(self):
        data = _good()
        data['written_by']['subject'] = 'gemini'
        problems = case_schema.validate(data)
        self.assertEqual([p.key for p in problems], ['written_by.subject'])

    def test_non_dict_file_is_reported(self):
        problems = case_schema.validate(['قائمة'])
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].key, '(case.json)')

    def test_unknown_keys_are_not_flagged(self):
        """مفتاح غير مذكور في العقد = غير مقيد (ما نرفضه)."""
        data = _good()
        data['شيء_جديد'] = {'أي': 'شكل'}
        self.assertEqual(case_schema.validate(data), [])


class RepairTests(unittest.TestCase):
    """الإصلاح — يصلّح الآمن فقط."""

    def test_subject_missing_list_becomes_dict_keeping_content(self):
        data = _good()
        data['subject_missing'] = ['المبلغ الشهري', 'مدة الالتزام']
        fixes = case_schema.repair(data)
        self.assertTrue(fixes)
        self.assertIsInstance(data['subject_missing'], dict)
        self.assertEqual(data['subject_missing']['absent'], ['المبلغ الشهري', 'مدة الالتزام'])
        self.assertEqual(data['subject_missing']['unverified'], [])
        self.assertEqual(data['subject_missing']['models'], [])

    def test_subject_missing_dict_gets_missing_subkeys(self):
        data = _good()
        data['subject_missing'] = {'absent': ['أ']}
        case_schema.repair(data)
        self.assertEqual(sorted(data['subject_missing']), ['absent', 'models', 'unverified'])
        self.assertEqual(data['subject_missing']['absent'], ['أ'])   # ما انمسح

    def test_string_step_value_becomes_dict(self):
        data = _good()
        data['steps']['research'] = 'done'
        case_schema.repair(data)
        self.assertEqual(data['steps']['research'], {'state': 'done'})

    def test_sessions_minutes_filled_not_removed(self):
        data = _good()
        data['sessions'] = {'count_system': 3}
        case_schema.repair(data)
        self.assertEqual(data['sessions']['minutes'], [])
        self.assertEqual(data['sessions']['count_system'], 3)

    def test_repair_never_deletes_unknown_data(self):
        data = _good()
        data['حقل_خاص'] = {'قيمة': 1}
        data['subject_missing'] = ['أ']
        case_schema.repair(data)
        self.assertEqual(data['حقل_خاص'], {'قيمة': 1})
        self.assertEqual(data['subject'], 'موضوع القضية')
        self.assertEqual(data['steps']['subject']['state'], 'done')

    def test_check_returns_problems_and_fixes(self):
        data = _good()
        data['subject_missing'] = ['أ']
        result = case_schema.check(data)
        self.assertFalse(result['ok'])
        self.assertTrue(result['fixes'])
        self.assertEqual(len(result['problems']), 1)


class RegressionStepAlertsTests(unittest.TestCase):
    """الاختبار المرجعي — المشكلة الفعلية 25/10."""

    def test_step_alerts_does_not_raise_after_repair(self):
        import doc_router
        data = _good()
        data['subject_missing'] = ['المبلغ الشهري', 'مدة الالتزام']
        # قبل الإصلاح: استثناء
        with self.assertRaises(AttributeError):
            doc_router.step_alerts(data, 'subject')
        # بعد الإصلاح: تنبيه عنبري بدل الانهيار
        case_schema.repair(data)
        out = doc_router.step_alerts(data, 'subject')
        self.assertTrue(out)
        self.assertEqual(out[0][0], 'amber')
        self.assertIn('المبلغ الشهري', out[0][1])

    def test_subject_missing_text_does_not_raise_after_repair(self):
        import qt_case_page
        data = _good()
        data['subject_missing'] = ['المبلغ الشهري']
        with self.assertRaises(AttributeError):
            qt_case_page.subject_missing_text(data)
        case_schema.repair(data)
        self.assertIsInstance(qt_case_page.subject_missing_text(data), str)


class InstallTests(unittest.TestCase):
    """الرقعة على القراءة."""

    def setUp(self):
        case_schema.uninstall()          # تنظيف: لو اختبار سابق ركّب الرقعة
        self.tmp = tempfile.mkdtemp(prefix='case_schema_test_')
        self.base = os.path.join(self.tmp, 'A2263973')
        os.makedirs(os.path.join(self.base, '_نظام'))
        with open(os.path.join(self.base, '_نظام', 'case.json'), 'w', encoding='utf-8') as f:
            json.dump({'caso_no': 'A2263973', 'subject_missing': ['المبلغ']}, f, ensure_ascii=False)
        self._installed = False

    def tearDown(self):
        case_schema.uninstall()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_install_is_noop_under_tests_without_force(self):
        self.assertFalse(case_schema.install())            # تحت الاختبار: ما يركّب
        self.assertTrue(case_schema.install(force=True))    # مع force يركّب
        self._installed = True

    def test_install_repairs_on_read(self):
        import case_workspace
        original = case_workspace._read
        self.assertTrue(case_schema.install(force=True))
        self._installed = True
        self.assertIsNot(case_workspace._read, original)
        data = case_workspace.read_case_json(self.base)
        self.assertIsInstance(data['subject_missing'], dict)
        self.assertEqual(data['subject_missing']['absent'], ['المبلغ'])

    def test_uninstall_restores_original_read(self):
        import case_workspace
        original = case_workspace._read
        case_schema.install(force=True)
        self._installed = True
        case_schema.uninstall()
        self._installed = False
        self.assertIs(case_workspace._read, original)

    def test_install_does_not_break_reading(self):
        import case_workspace
        case_schema.install(force=True)
        self._installed = True
        data = case_workspace.read_case_json(self.base)
        self.assertEqual(data['caso_no'], 'A2263973')
        self.assertIn('steps', data)          # الترحيل كمّل عادي


class ScanTests(unittest.TestCase):
    """الفحص الشامل."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='case_schema_scan_')
        for caso, payload in (('A1', {'caso_no': 'A1'}),):
            os.makedirs(os.path.join(self.tmp, caso, '_نظام'))
            with open(os.path.join(self.tmp, caso, '_نظام', 'case.json'), 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False)
        os.makedirs(os.path.join(self.tmp, 'A2', '_نظام'))
        with open(os.path.join(self.tmp, 'A2', '_نظام', 'case.json'), 'w', encoding='utf-8') as f:
            json.dump({'caso_no': 'A2', 'subject_missing': ['أ']}, f, ensure_ascii=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scan_finds_only_the_broken_case(self):
        rows = case_schema.scan(self.tmp)
        self.assertEqual(len(rows), 2)
        by_caso = {r['caso']: r for r in rows}
        self.assertEqual(by_caso['A1']['problems'], [])
        self.assertEqual(len(by_caso['A2']['problems']), 1)
        self.assertTrue(by_caso['A2']['fixes'])

    def test_main_runs_and_returns_zero(self):
        self.assertEqual(case_schema.main([self.tmp]), 0)

    def test_main_with_fix_writes_repaired_file(self):
        case_schema.main(['--fix', self.tmp])
        p = os.path.join(self.tmp, 'A2', '_نظام', 'case.json')
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        self.assertIsInstance(data['subject_missing'], dict)


if __name__ == '__main__':
    unittest.main()
