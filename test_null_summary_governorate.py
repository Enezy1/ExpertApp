"""انحدار 12/11/2026: (١) قضايا قديمة case_summary=NULL كانت تُسقط بطاقة المتداولة/المحالة
فتطلع الصفحة فاضية والأرقام ظاهرة. (٢) محافظة الأحمدي ما كانت تُطابَق من اسم القسم."""
import os
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import config
import referred_cases


class NullSummaryTests(unittest.TestCase):
    def test_shared_function_handles_null_summary(self):
        # الجذر مُصلَح (12/11 بإذن العنزي): NULL لا يكسر claim_summary_initial
        with mock.patch.object(referred_cases.case_db, 'get_case',
                               return_value={'case_summary': None}):
            self.assertEqual(referred_cases.claim_summary_initial(
                {'caso_no': 'A1', 'autocase_no': '5'}), ('load', None))

    def test_get_case_normalizes_null_columns(self):
        import sqlite3
        import case_db
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE cases (caso_no TEXT, case_summary TEXT, plaintiffs TEXT,"
                     " defendants TEXT, committee_members TEXT)")
        conn.execute("INSERT INTO cases VALUES ('A1', NULL, NULL, NULL, NULL)")
        with mock.patch.object(case_db, '_connect', return_value=conn):
            row = case_db.get_case('A1')
        self.assertEqual(row['case_summary'], '')
        self.assertEqual(row['plaintiffs'], [])

    def _check(self, module):
        with mock.patch.object(referred_cases.case_db, 'get_case',
                               return_value={'case_summary': None}):
            self.assertEqual(module._summary_state({'caso_no': 'A1', 'autocase_no': '5'}), ('load', None))
            self.assertEqual(module._summary_state({'caso_no': 'A1', 'autocase_no': ''}), ('skip', None))

    def test_pending_page_survives_null_summary(self):
        import qt_pending_page_v2
        self._check(qt_pending_page_v2)

    def test_referred_page_survives_null_summary(self):
        import qt_referred_page_v2
        self._check(qt_referred_page_v2)


class GovernorateTests(unittest.TestCase):
    @staticmethod
    def _gov(dept):
        for key, val in config.GOVERNORATES.items():     # نفس حلقة api.parse_case_info
            if key in dept:
                return val
        return ''

    def test_ahmadi_all_spellings(self):
        for dept in ('قسم قضايا الكهرباء والكمبيوتر الاحمدي', 'قسم قضايا الكهرباء والكمبيوتر الاحمدى',
                     'قسم قضايا الكهرباء والكمبيوتر الأحمدي', 'قسم قضايا الكهرباء والكمبيوتر الأحمدى'):
            self.assertEqual(self._gov(dept), 'الأحمدي', dept)

    def test_existing_governorates_unchanged(self):
        self.assertEqual(self._gov('قسم قضايا الكهرباء والكمبيوتر العاصمه'), 'العاصمة')
        self.assertEqual(self._gov('قسم قضايا X الفروانيه'), 'الفروانية')
        self.assertEqual(self._gov('قسم قضايا X حوله'), 'حولي')
        self.assertEqual(self._gov('قسم قضايا X مبارك الكبير'), 'مبارك الكبير')
        self.assertEqual(self._gov('قسم قضايا X الجهراء'), 'الجهراء')


if __name__ == '__main__':
    unittest.main()
