# اختبارات إحصائية سجل الحركة (case_stats):
#   قضية لها تاريخ إنجاز وما عندها تاريخ إحالة ما تنسقط من التقرير بصمت.
#   python -W ignore -m unittest test_case_stats -v
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import case_stats as cs


def event(label, actor, to_name, date_str):
    """صف إجراء ببلوك 7 خانات: تسمية، قسم1، اسم1(الفاعل)، قسم2، اسم2(المستلم)، رقم، تاريخ"""
    return [label, 'قسم فني', actor, 'قسم فني', to_name, '12345', date_str]


ME = 'محمد العنزي'                      # الاسم المختصر (زي ما يجي من get_my_name)
ME_FULL = 'محمد عبدالله العنزي'          # الاسم الكامل بالتدفق
OTHER = 'سالم عبدالله الخالدي'


class AnalyzeCaseFlowTests(unittest.TestCase):
    """إصلاح الجذر: تاريخ إحالة احتياطي من أول «مباشرة القضية»"""

    def analyze(self, cells):
        with mock.patch.object(cs, '_parse_flow', return_value=cells):
            return cs.analyze_case_flow({}, 'A1', ME)

    def test_no_referral_date_falls_back_to_mubashara_date(self):
        """باشر وأنجز، بس ما طلع اسمه بأي كتلة توزيع → لازم ينال تاريخ إحالة"""
        cells = []
        cells += event('مباشرة القضية', ME_FULL, ME_FULL, '05/10/2026')
        cells += event('انجاز القضية', ME_FULL, ME_FULL, '20/10/2026')

        r = self.analyze(cells)
        self.assertTrue(r['referred'])
        self.assertTrue(r['completed'])
        self.assertEqual(r['referral_date'], datetime(2026, 10, 5))
        self.assertEqual(r['completion_date'], datetime(2026, 10, 20))

    def test_normal_case_keeps_the_distribution_date(self):
        """لو فيه كتلة توزيع فيها اسمه → تاريخ الإحالة يبقى تاريخ التوزيع (ما تغيّر)"""
        cells = []
        cells += event(cs.NORMAL_DIST_LABEL, 'رئيس القسم', ME_FULL, '01/10/2026')
        cells += event('مباشرة القضية', ME_FULL, ME_FULL, '05/10/2026')
        cells += event('انجاز القضية', ME_FULL, ME_FULL, '20/10/2026')

        r = self.analyze(cells)
        self.assertEqual(r['referral_date'], datetime(2026, 10, 1))
        self.assertEqual(r['completion_date'], datetime(2026, 10, 20))

    def test_case_without_mubashara_is_not_mine(self):
        """لو ما باشر أصلاً → مو قضيته (ما نتغيّر هذا السلوك)"""
        cells = event(cs.NORMAL_DIST_LABEL, 'رئيس القسم', ME_FULL, '01/10/2026')
        r = self.analyze(cells)
        self.assertFalse(r['referred'])
        self.assertIsNone(r['referral_date'])

    def test_redistribution_also_gets_fallback_date(self):
        """إعادة التوزيع: لازم تاخذ تاريخ إحالة احتياطي كمان (ما تختفي من المستبعدات)"""
        cells = []
        cells += event('مباشرة القضية', ME_FULL, ME_FULL, '05/10/2026')
        cells += event('اعادة توزيع القضية', ME_FULL, ME_FULL, '12/10/2026')

        r = self.analyze(cells)
        self.assertTrue(r['is_redistributed'])
        self.assertEqual(r['referral_date'], datetime(2026, 10, 5))


def row(caso, rd='', cd='', redist=''):
    return {'caso_no': caso, 'title': 'قضية ' + caso,
            'referral_date_actual': rd, 'completion_date_actual': cd,
            'is_redistributed': redist}


class BuildReportDataTests(unittest.TestCase):
    """حزام الأمان: ما فيه قضية تنسقط من التقرير بصمت"""

    def build(self, rows, frm='2026-01-01', to='2026-12-31'):
        with mock.patch.object(cs.case_db, 'get_all_checked_stats', return_value=rows):
            return cs.build_report_data(datetime.fromisoformat(frm),
                                        datetime.fromisoformat(to),
                                        cookies=None, current_user=ME)

    def test_completed_case_without_referral_date_is_kept(self):
        """القضية المنجزة بلا تاريخ إحالة — لسه بتطلع (كانت بتختفي!)"""
        referred, completed, excluded = self.build([row('A1', rd='', cd='2026-05-10')])
        self.assertEqual([c['caso_no'] for c in referred], ['A1'])
        self.assertEqual([c['caso_no'] for c in completed], ['A1'])
        self.assertEqual(excluded, [])
        self.assertTrue(referred[0]['referral_date_inferred'])

    def test_referral_date_has_priority_over_completion_date(self):
        """لو فيه إحالة — هي المرجع حتى لو الإنجاز بالفترة"""
        referred, completed, excluded = self.build([row('A2', rd='2025-06-01', cd='2026-05-10')])
        self.assertEqual(referred, [])
        self.assertEqual(completed, [])

    def test_case_without_any_date_is_excluded(self):
        """ما عندها أي تاريخ → ما تنحط بأي فترة (صح)"""
        referred, completed, excluded = self.build([row('A3', rd='', cd='')])
        self.assertEqual(referred, [])
        self.assertEqual(completed, [])

    def test_normal_case_unchanged(self):
        """الحالة العادية ما تتغيّر"""
        referred, completed, excluded = self.build([row('A4', rd='2026-03-01', cd='2026-05-10')])
        self.assertEqual([c['caso_no'] for c in referred], ['A4'])
        self.assertEqual([c['caso_no'] for c in completed], ['A4'])
        self.assertFalse(referred[0]['referral_date_inferred'])

    def test_redistributed_case_still_listed(self):
        """المستبعدة (أُعيد توزيعها) تفتح كمان"""
        referred, completed, excluded = self.build([row('A5', rd='2026-03-01', cd='', redist='1')])
        self.assertEqual(referred, [])
        self.assertEqual([c['caso_no'] for c in excluded], ['A5'])


class ReportHtmlTests(unittest.TestCase):
    """التقرير: التاريخ المستنتج يُعلَّم بعلامة * مع حاشية توضيح"""

    def render(self, referred, completed, excluded):
        tmp = tempfile.mkdtemp(prefix='ea_stats_test_')
        with mock.patch.object(cs.os.path, 'expanduser', return_value=tmp):
            path = cs.build_full_stats_report_html(
                referred, completed, excluded,
                datetime(2026, 1, 1), datetime(2026, 12, 31), ME)
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_inferred_date_is_marked_and_explained(self):
        html = self.render(
            [{'caso_no': 'A1', 'title': 'قضية', 'referral_date': '',
              'completion_date': '2026-05-10', 'referral_date_inferred': True}],
            [], [])
        self.assertIn('*', html)
        self.assertIn('تاريخ الإحالة غير مسجّل', html)

    def test_no_footnote_when_all_dates_known(self):
        html = self.render(
            [{'caso_no': 'A1', 'title': 'قضية', 'referral_date': '2026-03-01',
              'completion_date': '2026-05-10', 'referral_date_inferred': False}],
            [], [])
        self.assertNotIn('تاريخ الإحالة غير مسجّل', html)


class ScanErrorTests(unittest.TestCase):
    """أخطاء الفحص ما تنبتلع — توصل للواجهة"""

    def test_scan_error_is_reported_through_error_cb(self):
        errors = []
        with mock.patch.object(cs, 'get_my_name', return_value=ME), \
                mock.patch.object(cs, 'get_candidate_cases', return_value=['A1']), \
                mock.patch.object(cs.case_db, 'get_case_stats', return_value=None), \
                mock.patch.object(cs, 'analyze_case_flow', side_effect=OSError('network down')):
            cs.run_full_scan({}, ME, error_cb=lambda caso, err: errors.append((caso, err)))
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][0], 'A1')
        self.assertIsInstance(errors[0][1], OSError)

    def test_scan_without_error_cb_still_works(self):
        with mock.patch.object(cs, 'get_my_name', return_value=ME), \
                mock.patch.object(cs, 'get_candidate_cases', return_value=[]):
            self.assertEqual(cs.run_full_scan({}, ME), [])


if __name__ == '__main__':
    unittest.main()
