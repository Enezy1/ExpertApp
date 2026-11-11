# -*- coding: utf-8 -*-
"""
test_anjaz.py — اختبارات وحدة الأتعاب (anjaz.py).

كل الاختبارات بدون شبكة (offline): نتحقق من بناء الـ payload، والحسابات،
وتحليل صفحة الأتعاب، وتوليد ملف Word.

⚠️ ما في أي اختبار يرسل بيانات للنظام الحقيقي.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import anjaz


# صفحة الأتعاب كما يرسمها السيرفر (نموذج مبني على أسماء الحقول الحقيقية)
SAMPLE_FORM_HTML = """
<table>
 <tr><th>المصروف</th><th>المبلغ</th><th>عدد الايام</th><th>عدد الخبراء</th></tr>
 <tr>
   <td><input type="text" class="FEE_NAME" name="name_170001" id="name_170001" value="عمل داخل الادارة"></td>
   <td><input type="text" class="FEE_AMOUNT" name="amount_170001" id="amount_170001" value="20"></td>
   <td><input type="text" class="FEE_DAYS" name="days_170001" id="days_170001" value=""></td>
   <td><input type="text" class="FEE_COUNT" name="count_170001" id="count_170001" value=""></td>
 </tr>
 <tr>
   <td><input type="text" class="FEE_NAME" name="name_170007" id="name_170007" value="مصروفات نقل"></td>
   <td><input type="text" class="FEE_AMOUNT" name="amount_170007" id="amount_170007" value="15"></td>
   <td><input type="text" class="FEE_DAYS" name="days_170007" id="days_170007" value="1"></td>
   <td><input type="text" class="FEE_COUNT" name="count_170007" id="count_170007" value="2"></td>
 </tr>
</table>
"""


class FeeCodesTests(unittest.TestCase):
    def test_ten_codes(self):
        self.assertEqual(len(anjaz.FEE_CODES), 10)
        self.assertEqual(anjaz.FEE_CODES[0], '170001')
        self.assertEqual(anjaz.FEE_CODES[-1], '1700010')

    def test_codes_are_unique(self):
        self.assertEqual(len(set(anjaz.FEE_CODES)), len(anjaz.FEE_CODES))

    def test_every_code_has_a_name(self):
        for c in anjaz.FEE_CODES:
            self.assertTrue(anjaz.FEE_NAMES.get(c), 'بدون اسم للأكواد %s' % c)

    def test_fee_types_order(self):
        rows = anjaz.fee_types()
        self.assertEqual([r['code'] for r in rows], list(anjaz.FEE_CODES))


class ParseFormTests(unittest.TestCase):
    def test_parse_rows(self):
        rows = anjaz.parse_fee_form(SAMPLE_FORM_HTML)
        self.assertEqual(len(rows), 10)
        by = {r['code']: r for r in rows}
        self.assertEqual(by['170001']['name'], 'عمل داخل الادارة')
        self.assertEqual(by['170001']['amount'], '20')
        self.assertEqual(by['170007']['amount'], '15')
        self.assertEqual(by['170007']['days'], '1')
        self.assertEqual(by['170007']['count'], '2')

    def test_parse_empty_page_returns_empty(self):
        self.assertEqual(anjaz.parse_fee_form('<html><body>لا يوجد</body></html>'), [])

    def test_total(self):
        rows = anjaz.parse_fee_form(SAMPLE_FORM_HTML)
        self.assertEqual(anjaz.fees_total(rows), 35.0)


class NormalizeTests(unittest.TestCase):
    def test_missing_rows_get_defaults(self):
        rows = anjaz.normalize_rows([{'code': '170001', 'amount': '5'}])
        self.assertEqual(len(rows), 10)
        first = rows[0]
        self.assertEqual(first['name'], anjaz.FEE_NAMES['170001'])
        self.assertEqual(first['amount'], '5')
        self.assertEqual(first['days'], '')

    def test_values_become_strings(self):
        rows = anjaz.normalize_rows([{'code': '170007', 'amount': 15, 'days': 1, 'count': 2}])
        r = [x for x in rows if x['code'] == '170007'][0]
        self.assertEqual(r['amount'], '15')
        self.assertEqual(r['days'], '1')
        self.assertEqual(r['count'], '2')

    def test_unknown_codes_are_dropped(self):
        rows = anjaz.normalize_rows([{'code': '999999', 'amount': '1'}])
        self.assertEqual(len(rows), 10)
        self.assertNotIn('999999', [r['code'] for r in rows])

    def test_total_ignores_non_numeric(self):
        rows = anjaz.normalize_rows([{'code': '170001', 'amount': 'شيك'},
                                      {'code': '170002', 'amount': '10'}])
        self.assertEqual(anjaz.fees_total(rows), 10.0)


class PayloadTests(unittest.TestCase):
    def test_payload_has_all_fields(self):
        p = anjaz.build_fee_payload('A2262424', [{'code': '170001', 'amount': '20'}])
        self.assertEqual(p['ECS_IN_REGNO'], 'A2262424')
        self.assertEqual(p['amount_170001'], '20')
        self.assertEqual(p['name_170001'], anjaz.FEE_NAMES['170001'])
        self.assertEqual(p['count_170001'], '')
        self.assertEqual(p['days_170001'], '')
        # عنصر FEE_TYPE: الاسم = القيمة = الكود
        self.assertEqual(p['170001'], '170001')
        # كل الأكواد العشرة لازم تكون موجودة (السيرفر يتوقعها كلها)
        for c in anjaz.FEE_CODES:
            self.assertIn('amount_' + c, p)
            self.assertIn('count_' + c, p)
            self.assertIn('days_' + c, p)
            self.assertIn('name_' + c, p)

    def test_payload_requires_case_number(self):
        p = anjaz.build_fee_payload('', [])
        self.assertEqual(p['ECS_IN_REGNO'], '')


class SaveSafetyTests(unittest.TestCase):
    """مهم: الحفظ لازم يكون dry_run بالافتراضي (ما يرسل شي بدون إذن)."""

    def test_dry_run_does_not_post(self):
        posted = {}

        def fake_post(url, data=None, cookies=None, verify=None, **kw):
            posted['url'] = url
            posted['data'] = data
            raise AssertionError('ما ينفع يرسل/network وقت dry_run')

        import requests as _rq
        old = _rq.post
        _rq.post = fake_post
        try:
            res = anjaz.save_fees({}, 'A2262424', [{'code': '170001', 'amount': '20'}])
        finally:
            _rq.post = old
        self.assertFalse(posted)
        self.assertEqual(res['code'], 'dry_run')
        self.assertFalse(res['ok'])
        self.assertEqual(res['payload']['ECS_IN_REGNO'], 'A2262424')
        self.assertEqual(res['total'], 20.0)

    def test_missing_case_number_blocks_save(self):
        res = anjaz.save_fees({}, '', [], dry_run=False)
        self.assertFalse(res['ok'])
        self.assertEqual(res['code'], 'x')


class DocxTests(unittest.TestCase):
    def test_generates_word_file(self):
        rows = anjaz.normalize_rows([
            {'code': '170001', 'name': 'عمل داخل الادارة', 'amount': '20'},
            {'code': '170007', 'name': 'مصروفات نقل', 'amount': '15',
             'days': '1', 'count': '2'},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'رسوم_الخبرة.docx')
            anjaz.fees_docx(out, 'A2262424', rows,
                            case_info={'case_no': '16004885', 'type': 'جنح'},
                            expert_name='محمد عبدالله فرحان العنزى')
            self.assertTrue(os.path.exists(out))
            self.assertGreater(os.path.getsize(out), 5000)


if __name__ == '__main__':
    unittest.main()
