# ===== test_case_facts.py — انحدار التحقق من الحقائق (2026-10-25، القضية A2263970) =====
# جيميناي استخرج العقد والخطين والأجهزة و10 فواتير والمسدد، والمدقّق حذفها كلها: صفحة «1» مكررة (تعليقات رأس الملف) بدل
# نص الدفعة المدموجة، وتواريخ الفواتير الإنجليزية «01 Sep 23» غير مفهومة، واقتباس سطر جدول أعاد النموذج بناءه، ورقم العقد
# مقروء بخانة ناقصة في حافظة، وبنود الفاتورة العادية عُدّت غرامات، ودفعتان بالمبلغ نفسه لخطين عُدّتا دفعة واحدة.
import json
import unittest

import case_facts as cf

HEAD = ('<!-- يحتوي هذا المستند على: حافظة مستندات المؤرخة 11/10/2026 -->\n'
        '<!-- ⚠ الصفحات 1–3: عدد الصفحات في ردّ Gemini (2) لا يطابق الفعلي (3) — النص مدموج لهذا الجزء -->\n')
MERGED = """<!-- صفحات 1–3 مدموجة -->
| م | عدد الأوراق | التاريخ | البيان |
| :-: | :-: | :-: | :-- |
| 1 | 2 | 2023/08/30 | صورة ضوئية من عقد طلب الاشتراك |

(مستند) رقم (1)
Subscription Form
Contract Number: 2758545644
| Action | تفاصيل الخدمة Service Details | السعر Price | فترة الالتزام Commitment Period |
| :-- | :-- | :-- | :-- |
| Add | iPhone 14 Plus 256GB | 10 | 24 |

(مستند) رقم (2)
Mobile Number: 58885103
Contract Number: 275854644
Invoice Number: 1206218052
Bill Date: 01 Jan 24
| Description | Period الفترة | Amount القيمة |
| :-- | :-- | :-- |
| December 2023 Bill | | 324.167 |
| SUBSIDY TERMINATION-I007 | 01 Dec 23 till 31 Dec 23 | 190.000 |
| Always ON 15 | 01 Dec 23 till 31 Dec 23 | 15.000 |
| Paid Amounts | 30 Aug 23 till 31 Aug 23 | -3.000 |
"""


def merged_doc():
    """حافظة دمج التحويل صفحاتها: علامة «صفحة 1» بعد تعليقات الرأس ← صفحتان برقم 1 قبل التنظيف."""
    import case_readiness as cr
    text = HEAD + '<!-- صفحة 1 -->\n' + MERGED
    pages = cf.tidy_pages(cr.split_pages(text))
    return {'code': 'D3', 'file': 'x.pdf', 'kind': 'حافظة مستندات', 'side': 'المدعية', 'date': '11/10/2026',
            'memo': False, 'multi': False, 'pages': pages, 'docno': cf.doc_numbers(pages),
            'merged': cf.merged_ranges(text)}


def second_doc():
    pages = [(3, 'Mobile Number: 58885104\nContract Number: 2758545644\nInvoice Number: 1201064903\nBill Date: 01 Sep 23\n'
                 '| August 2023 Bill | | 10.259 |\n| Paid Amounts | 30 Aug 23 till 31 Aug 23 | -3.000 |\n'),
             (4, 'Contract Number: 2758545644\nContract Number: 2758545644\n')]
    return {'code': 'D4', 'file': 'y.pdf', 'kind': 'حافظة مستندات', 'side': 'المدعية', 'date': '19/10/2026',
            'memo': False, 'multi': False, 'pages': pages, 'docno': cf.doc_numbers(pages), 'merged': []}


class PagesTests(unittest.TestCase):
    def test_header_comments_join_first_page(self):
        d = merged_doc()
        self.assertEqual([n for n, _t in d['pages']], [1])
        self.assertIn('Invoice Number: 1206218052', cf.page_text(d, 1))
        self.assertEqual(d['merged'], [(1, 3)])

    def test_page_text_joins_duplicate_numbers(self):
        d = {'pages': [(1, 'أ'), (1, 'ب')]}
        self.assertEqual(cf.page_text(d, 1), 'أ\nب')


class DateTests(unittest.TestCase):
    def test_english_bill_dates(self):
        self.assertEqual(cf.parse_date('01 Sep 23'), (1, 9, 2023))
        self.assertEqual(cf.parse_date('30-Aug-2023'), (30, 8, 2023))
        self.assertEqual(cf.parse_date('Sep 30, 2023'), (30, 9, 2023))
        self.assertEqual(cf.fmt_date('01 Jan 24'), '01/01/2024')

    def test_date_in_matches_across_formats(self):
        self.assertTrue(cf.date_in('Bill Date: 01 Sep 23', '01/09/2023'))
        self.assertTrue(cf.date_in('التاريخ 2023/09/01', '01 Sep 23'))
        self.assertFalse(cf.date_in('Bill Date: 01 Oct 23', '01/09/2023'))

    def test_numeric_dates_unchanged(self):
        self.assertEqual(cf.parse_date('15/02/2026'), (15, 2, 2026))
        self.assertIsNone(cf.parse_date('بلا تاريخ'))


def reply(**kw):
    base = {'contracts': [], 'service_orders': [], 'invoices': [], 'payments': [], 'statement_totals': [], 'defenses': []}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


INVOICE = {'number': '1206218052', 'date': '01 Jan 24', 'amount': '324.167', 'line': '58885103',
           'quote': 'December 2023 Bill | | 324.167', 'doc': 'D3', 'page': 22,
           'components': [{'kind': 'SUBSIDY TERMINATION', 'amount': '190.000', 'quote': 'SUBSIDY TERMINATION-I007'},
                          {'kind': 'Always ON 15', 'amount': '15.000', 'quote': 'Always ON 15'}]}


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.docs = [merged_doc(), second_doc()]

    def test_invoice_in_merged_batch_verified(self):
        """الانحدار: كانت الفواتير العشر كلها «لم يرد في المستند: number، line، date»."""
        out, removed = cf.verify_model(reply(invoices=[INVOICE]), self.docs)
        self.assertEqual(len(out['invoices']), 1, removed)
        inv = out['invoices'][0]
        self.assertEqual((inv['doc'], inv['page'], inv['date']), ('D3', 1, '01/01/2024'))

    def test_only_penalties_kept_as_components(self):
        out, _r = cf.verify_model(reply(invoices=[INVOICE]), self.docs)
        self.assertEqual([str(c['amount']) for c in out['invoices'][0]['components']], ['190.000'])

    def test_rebuilt_table_row_quote_on_cited_page(self):
        o = {'contract': '2758545644', 'line': '58885103', 'device': 'iPhone 14 Plus 256GB', 'monthly': '10',
             'commitment_months': '24', 'date': '05/09/2023', 'doc': 'D3', 'page': 3,
             'quote': 'Action Add | تفاصيل الخدمة iPhone 14 Plus 256GB | السعر 10 | فترة الالتزام 24'}
        out, removed = cf.verify_model(reply(service_orders=[o]), self.docs)
        self.assertEqual(len(out['service_orders']), 1, removed)
        self.assertEqual(out['service_orders'][0]['date'], '')       # تاريخ التفعيل لم يرد: يُترك فارغاً لا يُحذف الخط

    def test_token_quote_needs_every_word(self):
        o = {'line': '58885103', 'doc': 'D3', 'page': 1, 'quote': 'Action Add iPhone 14 Plus 256GB Samsung'}
        out, removed = cf.verify_model(reply(service_orders=[o]), self.docs)
        self.assertFalse(out['service_orders'])
        self.assertIn('غير وارد حرفياً', removed[0][0])

    def test_misread_contract_link_cleared_not_dropped(self):
        o = {'contract': '2758545644', 'line': '58885104', 'doc': 'D4', 'page': 3,
             'quote': 'Mobile Number: 58885104 Contract Number: 2758545644'}
        out, _r = cf.verify_model(reply(service_orders=[dict(o, contract='9999999999')]), self.docs)
        self.assertEqual(out['service_orders'][0]['contract'], '')

    def test_wrong_amount_still_rejected(self):
        bad = dict(INVOICE, amount='999.000')
        out, removed = cf.verify_model(reply(invoices=[bad]), self.docs)
        self.assertFalse(out['invoices'])
        self.assertIn('amount', removed[0][0])

    def test_reread_text_verifies_quote(self):
        """قراءة PDF الجديدة تكفي للتحقق حين يكون نص markdown مشوّهاً."""
        docs = [dict(second_doc(), pages=[(3, 'نص مشوّه ###')])]
        inv = {'number': '1201064903', 'date': '01 Sep 23', 'amount': '10.259', 'line': '58885104',
               'quote': 'August 2023 Bill | | 10.259', 'doc': 'D4', 'page': 3}
        out, _r = cf.verify_model(reply(invoices=[inv]), docs)
        self.assertFalse(out['invoices'])
        re_docs = cf.apply_reread(docs, [{'doc': 'D4', 'page': 3, 'text': second_doc()['pages'][0][1]}])
        out2, removed = cf.verify_model(reply(invoices=[inv]), re_docs)
        self.assertEqual(len(out2['invoices']), 1, removed)
        self.assertIn('نص مشوّه', cf.page_text(re_docs[0], 3))          # نص markdown القديم لا يُحذف


class MergeTests(unittest.TestCase):
    def test_same_amount_on_two_lines_is_two_payments(self):
        f = cf.merge({}, {'payments': [{'amount': cf.dec('3.000'), 'line': '58885103', 'invoice': ''},
                                       {'amount': cf.dec('3.000'), 'line': '58885104', 'invoice': ''}]}, [])
        self.assertEqual(len(f['payments']), 2)

    def test_one_digit_apart_contracts_merged(self):
        texts = ['Contract Number: 2758545644 ' * 3, 'Contract Number: 275854644']
        f = {'contracts': [{'number': '275854644', 'src': 'code', 'id': 'C1'},
                           {'number': '2758545644', 'src': 'code', 'id': 'C2', 'date': '30/08/2023'}],
             'service_orders': [{'line': '58885103', 'contract': '275854644'}]}
        notes = []
        cf.merge_near_contracts(f, texts, notes)
        self.assertEqual([c['number'] for c in f['contracts']], ['2758545644'])
        self.assertEqual(f['service_orders'][0]['contract'], '2758545644')
        self.assertIn('275854644', notes[0][1])

    def test_different_contracts_kept(self):
        f = {'contracts': [{'number': '1460362'}, {'number': '2758545644'}], 'service_orders': []}
        cf.merge_near_contracts(f, [''], [])
        self.assertEqual(len(f['contracts']), 2)

    def test_dated_record_gives_contract_citation(self):
        """رقم العقد في رأس فاتورة (قارئ الكود) وفي صفحة العقد بتاريخه (النموذج): المرجع لصفحة العقد."""
        f = {'contracts': [{'number': '2758545644', 'doc': 'D4', 'page': 3, 'src': 'code'},
                           {'number': '2758545644', 'doc': 'D3', 'page': 1, 'date': '30/08/2023', 'docno': 1,
                            'src': 'model'}],
             'service_orders': [], 'invoices': [], 'payments': [], 'statement_totals': []}
        cf.normalize_contracts(f, [])
        c = f['contracts'][0]
        self.assertEqual((c['doc'], c['page'], c['docno'], c['date']), ('D3', 1, 1, '30/08/2023'))


class CitationTests(unittest.TestCase):
    def test_docno_heading_variants(self):
        for s in ('(مستند) رقم (1)', 'مستند (2)', '## مستند رقم 3'):
            self.assertTrue(cf._DOCNO.search(s), s)

    def test_cite_with_fact_docno(self):
        d = second_doc()
        self.assertEqual(cf.cite(d, 3, 2), '(مرفق بحافظة مستندات المدعية المؤرخة 19/10/2026 مستند 2)')

    def test_merged_page_no_guessed_docno(self):
        """صفحة الدفعة المدموجة: آخر عنوان فيها («مستند 2») لا يُنسب لكل ما فيها."""
        d = merged_doc()
        self.assertEqual(cf.cite(d, 1), '(مرفق بحافظة مستندات المدعية المؤرخة 11/10/2026)')
        self.assertIsNone(cf._docno(d, 1, ''))
        self.assertEqual(cf._docno(d, 1, '1'), 1)


class PromptTests(unittest.TestCase):
    def test_extract_prompt_rules(self):
        p = cf.extract_prompt([merged_doc()], [{'label': 'المدعية', 'name': 'شركة'}])
        self.assertIn('### D3 — حافظة مستندات مقدمة من المدعية المؤرخة 11/10/2026', p)
        self.assertIn('الصفحات 1–3 مدموجة', p)
        for w in ('need_pdf', 'docno', 'دون ترجمة', 'بإشارته', 'components للغرامات'):
            self.assertIn(w, p)

    def test_need_pdf_parsed(self):
        raw = json.dumps({'need_pdf': [{'doc': 'D3', 'pages': '12-20', 'why': 'الفواتير مشوّهة'}, {'doc': 'x'}]})
        self.assertEqual(cf.need_pdf_of(raw), [{'doc': 'D3', 'pages': '12-20', 'why': 'الفواتير مشوّهة'}])
        self.assertEqual(cf.need_pdf_of(''), [])


if __name__ == '__main__':
    unittest.main()


class SecondaryFieldsTests(unittest.TestCase):
    """(2026-10-25، A2263970) «قيمة الجهاز 308.000» من صفحة الفاتورة لا صفحة العقد ← حُذف الخطان بأجهزتهما وأقساطهما."""

    def test_device_value_cleared_line_kept(self):
        o = {'line': '58885104', 'device': 'iPhone', 'monthly': '', 'device_value': '370.000', 'plan_monthly': '35',
             'doc': 'D4', 'page': 3, 'quote': 'Mobile Number: 58885104 Contract Number: 2758545644'}
        out, removed = cf.verify_model(reply(service_orders=[o]), [second_doc()])
        self.assertEqual(len(out['service_orders']), 1, removed)
        rec = out['service_orders'][0]
        self.assertIsNone(rec['device_value'])
        self.assertIsNone(rec['plan_monthly'])

    def test_invoice_amount_still_primary(self):
        self.assertNotIn('amount', cf.SECONDARY_FIELDS.get('invoices', ()))
