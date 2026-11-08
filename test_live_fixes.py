# ===== test_live_fixes.py — إصلاحات اكتُشفت بتشغيل حقيقي على A2263973 (2026-10-22) =====
import os
import tempfile
import unittest

import case_contracts as cc
import case_sort as cs
import case_stage2
import case_triage as ct
import loop_guard
import report_audit as ra


class TriageVerifyTests(unittest.TestCase):
    def test_year_first_date_matches(self):
        self.assertTrue(cc.date_in_text('18/10/2026', 'المحدد لنظرها جلسة 2026/10/18'))
        self.assertFalse(cc.date_in_text('18/11/2026', 'جلسة 2026/10/18'))

    def test_scanned_quote_tolerates_ocr_typos(self):
        text = 'حتى بلغ مجموع المبالغ الستحقة والمترصدة بذمته مديونية وقدرها 1,155.769د. ك'
        self.assertTrue(ct.quote_in('مجموع المبالغ المستحقة والمترصدة بذمته مديونية وقدرها', text))
        self.assertFalse(ct.quote_in('عقد مقاولة لإنشاء مبنى مدرسة', text))

    def test_model_type_names_normalized(self):
        self.assertEqual(cs.norm_type('صحيفة دعوى'), 'صحيفة')
        self.assertEqual(cs.norm_type('حافظة مستندات'), 'حافظة')
        self.assertEqual(cs.norm_type('مذكرة دفاع'), 'مذكرة')
        self.assertEqual(cs.norm_type('شيء آخر'), 'أخرى')

    def test_portfolio_inner_documents_absorbed_and_amounts_verified_anywhere(self):
        md = '\n'.join(f'<!-- صفحة {i} -->\nحافظة مستندات المدعية {"480.000" if i == 44 else ""}' for i in range(1, 52))
        raw = {'parts': [{'type': 'حافظة', 'pages': [1, 1], 'submitter_role': 'unknown',
                          'amounts': [{'label': 'جهاز', 'amount': '480.000', 'page': 4, 'quote': 'x'}]},
                         {'type': 'أخرى', 'pages': [6, 17]}, {'type': 'أخرى', 'pages': [41, 51]}]}
        parts, notes = ct.verify({}, raw, md)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]['pages'], [1, 51])
        self.assertEqual([a['amount'] for a in parts[0]['amounts']], ['480.000'])

    def test_parties_and_gender_adopted_from_plaint(self):
        data = {'case': {'plaintiff': '', 'defendants': []}}
        md = 'بناءً على طلب السادة شركة الاتصالات المتنقلة ضد السيد/ عبد الرحمن فهد الخراز'
        parts = [{'type': 'صحيفة', 'parties': [
            {'role': 'plaintiff', 'name': 'شركة الاتصالات المتنقلة', 'gender': 'f'},
            {'role': 'defendant', 'name': 'عبد الرحمن فهد الخراز', 'gender': 'm'}]}]
        self.assertTrue(ct.adopt_parties(data, parts, md))
        self.assertEqual(cs.party_gender(data, 'defendant'), 'm')
        self.assertEqual(cs.role_label(data, 'defendant', 1, 'لم يحضر أحد عن المدعى عليها'), 'المدعى عليه')
        self.assertEqual(cs.role_label(data, 'plaintiff'), 'المدعية')

    def test_unknown_gender_does_not_fail_subject(self):
        data = {'case': {'plaintiffs': ['س'], 'defendants': ['ص']}}
        self.assertEqual(case_stage2._gender_errors(data, 'جاء المدعي … المدعى عليها'), [])


class MinutesTests(unittest.TestCase):
    def test_duplicate_minute_numbers_renumbered_by_date(self):
        import case_folder as cf
        import case_workspace as cw
        with tempfile.TemporaryDirectory() as tmp:
            base, data = cw.ensure_workspace({'caso_no': 'T0000001'}, tmp)
            man = {'files': {}}
            for name, date in (('محضر الخبرة رقم 1 (2).docx', '06-10-2026'), ('محضر الخبرة رقم 1.docx', '11-10-2026'),
                               ('محضر الخبرة رقم 3.docx', '18-10-2026')):
                p = os.path.join(base, cf.SYSDOCS, name)
                with open(p, 'wb') as f:
                    f.write(name.encode())
                man['files'][f'{cf.SYSDOCS}/{name}'] = {
                    'state': 'done', 'sha1': cf.sha1(p), 'md': cf.md_rel(f'{cf.SYSDOCS}/{name}'),
                    'triage': {'sha1': cf.sha1(p), 'v': ct.VERSION, 'parts': [
                        {'type': 'محضر', 'minute_no': int(name.split('رقم ')[1][0]), 'date': date}]}}
            cs.renumber_minutes(base, data, man)
            names = sorted(os.listdir(os.path.join(base, cf.SYSDOCS)))
            self.assertEqual(names, ['محضر الخبرة رقم 1.docx', 'محضر الخبرة رقم 2.docx', 'محضر الخبرة رقم 3.docx'])


class MiscTests(unittest.TestCase):
    def test_footer_on_every_page_is_not_a_loop(self):
        text = '\n'.join(f'فاتورة {i}\nFor more info, please call 107' for i in range(16))
        self.assertIsNone(loop_guard.detect(text, 51))
        self.assertIsNotNone(loop_guard.detect('\n'.join(['For more info, please call 107'] * 40), 2))

    def test_subject_empty_slot_and_misread_line_rejected(self):
        self.assertTrue(case_stage2._EMPTY_SLOT.search('مع مدة التزام وقدرها . وأفادت'))
        self.assertTrue(case_stage2._misread_numbers('الخطوط 94939904 و 9981725 و 99817125'))
        self.assertEqual(case_stage2._misread_numbers('الخطين 94939904 و99817125'), [])

    def test_audit_messages_are_plain_arabic(self):
        msg = ra.plain('(ز) المحور 1: كُتب «المدعى عليه» والمدعى عليها شركة/أنثى — الصواب «المدعى عليها»')
        self.assertFalse(msg.startswith('('))
        self.assertIn('ملاحظتان', ra.summary_line(['a', 'b']))

    def test_browser_opens_real_browser_maximized(self):
        import browser_write as bw
        got = []
        args = bw.open_site('https://copilot.microsoft.com/', launcher=got.append)
        if bw.browser_exe():
            self.assertIn('--start-maximized', args)
            self.assertEqual(args[-1], 'https://copilot.microsoft.com/')
        self.assertEqual(bw.COPILOT['url'], 'https://copilot.microsoft.com/')


if __name__ == '__main__':
    unittest.main()
