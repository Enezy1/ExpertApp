# اختبارات المرحلة 1 (تقارير الخبراء): python -m unittest test_telecom -v
# أسماء الشركات هنا وهمية؛ الحقيقية تأتي من gemini_network.ini.
import os
import tempfile
import unittest

import telecom_config as tc
import telecom_reports as tr

CO = {'شركة الألف للاتصالات': ['الالف', 'Alef Telecom'], 'باء موبايل': ['باء']}


class MatchTests(unittest.TestCase):
    def test_normalization_variants(self):
        self.assertEqual(tc.match_company('شركه الالف للاتصالات ضد فلان', CO), 'شركة الألف للاتصالات')
        self.assertEqual(tc.match_company('إلى الألف', CO), 'شركة الألف للاتصالات')

    def test_alias_and_latin(self):
        self.assertEqual(tc.match_company('ALEF TELECOM v. X', CO), 'شركة الألف للاتصالات')
        self.assertEqual(tc.match_company('شركة باء ضد علي', CO), 'باء موبايل')

    def test_prefix_letters(self):
        self.assertEqual(tc.match_company('لباء ضد محمد', CO), 'باء موبايل')

    def test_no_false_positive_inside_word(self):
        self.assertIsNone(tc.match_company('محمد باءر الصباح', CO))
        self.assertIsNone(tc.match_company('شركة الجيم ضد محمد', CO))
        self.assertIsNone(tc.match_company('', CO))

    def test_tashkeel_and_spaces(self):
        self.assertEqual(tc.match_company('  الأَلْف   ', CO), 'شركة الألف للاتصالات')


class IniTests(unittest.TestCase):
    def test_roundtrip_keeps_other_sections(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x.ini')
            open(p, 'w', encoding='utf-8').write('[network]\nproxy_url = a\n\n[telecom_companies]\nقديمة = x\n\n[features]\napi = 1\n')
            tc.save_companies(CO, p)
            txt = open(p, encoding='utf-8').read()
            self.assertIn('proxy_url = a', txt)
            self.assertIn('api = 1', txt)
            self.assertNotIn('قديمة', txt)
            self.assertEqual(tc.load_companies(p), CO)

    def test_missing_file_and_section(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x.ini')
            open(p, 'w', encoding='utf-8').write('[network]\nproxy_url =\n')
            self.assertEqual(tc.load_companies(p), tc.DEFAULT_COMPANIES)
            tc.save_companies({'ج': []}, p)
            self.assertEqual(tc.load_companies(p), {'ج': []})

    def test_defaults_when_empty(self):
        self.assertEqual(tc.load_companies('/no/such/file.ini'), tc.DEFAULT_COMPANIES)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x.ini')
            open(p, 'w', encoding='utf-8').write('[telecom_companies]\n')
            self.assertEqual(tc.load_companies(p), tc.DEFAULT_COMPANIES)


class RealCompaniesTests(unittest.TestCase):
    D = tc.DEFAULT_COMPANIES

    def test_three_companies(self):
        m = lambda t: tc.match_company(t, self.D)
        self.assertEqual(m('الشركة الوطنية للاتصالات'), 'أوريدو')
        self.assertEqual(m('الوطنية للاتصالات المتنقلة'), 'أوريدو')
        self.assertEqual(m('شركة الاتصالات المتنقلة'), 'زين')
        self.assertEqual(m('MTC'), 'زين')
        self.assertEqual(m('شركة الاتصالات الكويتية - stc'), 'stc')
        self.assertIsNone(m('شركة الاتصالات العربية'))

    def test_longest_form_wins(self):
        c = {'قصير': ['الاتصالات المتنقلة'], 'طويل': ['الوطنية للاتصالات المتنقلة']}
        self.assertEqual(tc.match_company('الوطنية للاتصالات المتنقلة', c), 'طويل')
        self.assertEqual(tc.match_company('الاتصالات المتنقلة', c), 'قصير')

    def test_split_plaintiff(self):
        self.assertEqual(tc.split_plaintiff('الوطنية للاتصالات ضد حسام'), 'الوطنية للاتصالات')
        self.assertEqual(tc.split_plaintiff('ضد حسام'), '')
        self.assertEqual(tc.split_plaintiff('بلا فصل'), '')


PENDING = [
    {'caso_no': 'A1', 'title': 'الالف ضد س', 'received_date': '2026-03-02', 'autocase_no': '1'},
    {'caso_no': 'A2', 'title': 'ضد فلان', 'received_date': '2026-01-05', 'autocase_no': '2'},
    {'caso_no': 'A3', 'title': 'ضد علان', 'received_date': '2026-02-01', 'autocase_no': '3'},
    {'caso_no': 'A4', 'title': 'ضد زيد', 'received_date': '2026-04-01', 'autocase_no': '4'},
    {'caso_no': 'A5', 'title': 'ضد عمرو', 'received_date': '2026-05-01', 'autocase_no': '5'},
]
SYSTEM = {'A2': {'plaintiffs': ['باء موبايل ش.م.ك'], 'defendants': ['فلان']},
          'A3': {'plaintiffs': ['شخص عادي'], 'defendants': ['علان']},
          'A5': {'plaintiffs': [], 'defendants': []}}


class ReportsTests(unittest.TestCase):
    def run_it(self, saved=None, parse=None, pending=None):
        calls = []

        def parse_fn(n, ck):
            calls.append(n)
            if n == 'A4':
                raise RuntimeError('offline')
            return SYSTEM.get(n)
        return tr.get_my_telecom_cases(
            {}, CO, pending_fn=lambda ck: PENDING if pending is None else pending,
            parse_fn=parse or parse_fn, saved_fn=saved or (lambda n: [])), calls

    def test_title_then_system_sorted_by_date(self):
        res, calls = self.run_it()
        self.assertEqual([c['caso_no'] for c in res['cases']], ['A2', 'A1'])
        self.assertEqual(res['cases'][0]['source'], 'system')
        self.assertEqual(res['cases'][1]['source'], 'title')
        self.assertEqual(res['cases'][0]['defendants'], ['فلان'])
        self.assertNotIn('A1', calls)          # العنوان كفى — لا طلب إضافي
        self.assertEqual(res['unresolved'], 2)  # A4 فشل، A5 بلا أطراف
        self.assertEqual(res['total'], 5)

    def test_no_end_date_field(self):
        res, _ = self.run_it()
        for c in res['cases']:
            self.assertFalse([k for k in c if k in ('end_date', 'due_date', 'expiry_date') or 'انتهاء' in k])

    def test_saved_plaintiff_skips_system(self):
        res, calls = self.run_it(saved=lambda n: ['باء'] if n == 'A2' else ['خاص'] if n == 'A3' else [])
        self.assertNotIn('A2', calls)
        self.assertNotIn('A3', calls)
        self.assertEqual(res['cases'][0]['source'], 'saved')

    def test_not_configured(self):
        res = tr.get_my_telecom_cases({}, {}, pending_fn=lambda c: self.fail('no fetch'))
        self.assertFalse(res['configured'])
        self.assertEqual(res['cases'], [])

    def test_plaintiff_only_not_defendant(self):
        pend = [{'caso_no': 'B1', 'title': 'فلان ضد الالف', 'received_date': '2026-01-01'},
                {'caso_no': 'B2', 'title': 'الالف ضد فلان', 'received_date': '2026-01-02'}]
        res, calls = self.run_it(pending=pend)
        self.assertEqual([c['caso_no'] for c in res['cases']], ['B2'])
        self.assertEqual(calls, [])           # العنوان واضح — لا رجوع للنظام

    def test_all_mode(self):
        res = tr.get_my_telecom_cases(
            {}, CO, pending_fn=lambda ck: PENDING, parse_fn=lambda *a: self.fail('no fetch'),
            saved_fn=lambda n: self.fail('no db'), only_telecom=False)
        self.assertEqual(len(res['cases']), 5)
        self.assertEqual(res['cases'][0]['caso_no'], 'A2')
        comp = {c['caso_no']: c['company'] for c in res['cases']}
        self.assertEqual(comp['A1'], 'شركة الألف للاتصالات')
        self.assertEqual(comp['A3'], '')

    def test_empty_pending(self):
        res, _ = self.run_it(pending=[])
        self.assertEqual((res['total'], res['cases']), (0, []))


if __name__ == '__main__':
    unittest.main()
