# اختبارات انحدار التقرير المركَّب بالكود (2026-10-20) — من أرقام القضية A2263973 (اتصالات، فواتير):
#   python -W ignore -m unittest test_report_v3 -v
# الخط 94939904: فواتير 626.670، المسدد 45.000 (مقدماً)، المتبقي 581.670. الخط 99817125: فواتير 609.100 (منها غرامة 471.500
# داخل فاتورة 480.900)، المسدد 35.000، المتبقي المحسوب 574.100 (وفي كشف المدعية 574.099 ← فرق فلس معلَّم). المجموع 1,155.770
# = المطالبة. عقد واحد 1460362 بخطين (لا ثلاثة عقود). المدعى عليه مذكر لم يحضر. نموذج «غبي» يُرفض ثم يُصحَّح. أقل من 900 كلمة.
import json
import os
import shutil
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

import amounts
import calc
import case_facts as cf
import case_workspace as cw
import report_audit as ra
import report_compose as rc
import report_playbooks as pb
import report_v3

HERE = os.path.dirname(os.path.abspath(__file__))
# نسخة مجمّدة (26/10/2026) من القضية الحقيقية بدون PDF/docx/سجلات — مستقلة عن المجلد الحيّ
REAL_CASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_data', 'A2263973')

MISSION = ("بيان طبيعة العلاقة بين طرفي التداعي، وبيان التزامات كلاً منهما اتجاه الآخر، وبيان عما إذا أخل أحدهما "
           "بالتزاماته تجاه الآخر من عدمه، وفي الحالة الأولى بيان الطرف المخل بالتزاماته، وكيفية ذلك الإخلال وسببه، وبيان "
           "طبيعة عقود الخدمات ونماذج طلب خدمة ومرفقاتها المبرمة بين طرفي التداعي، المرفق بمحافظة مستندات المدعية، وبيان "
           "قيمتها الإجمالية وطريقة سدادها، وبيان أصل مبلغ المديونية، وبيان قيمة الغرامات إن وجدت، وبيان عما إذا كانت ذمة "
           "المدعى عليه مشغولة بثمة مبالغ مالية لصالح المدعية من عدمه، وبيان المبالغ المالية المسددة من المدعى عليه، "
           "وبيان المبالغ المالية المتبقية بذمة المدعى عليه وسبب عدم سدادها، وبالإجمال بيان كل ما يفيد الدعوى ووصولاً لتصفية "
           "الحساب بين الطرفين، وبحث ما قد يثيره طرفي التداعي من أوجه دفاع وصولاً لوجه الحق في الدعوى.")

P_FACE = """### حافظة مستندات
| مــــــــن: | شركة الاتصالات المتنقلة (ش.م.ك) | صفتـــــــــها: | مدعية |
| ضـــــــــد: | عبد الرحمن فهد عبد الرحمن الخراز | صفتـــــــــه: | مدعى عليه |
"""
P_STATEMENT = """# مستند (1)
اسم العميل: عبد الرحمن فهد الخراز
رقم العقد: 1460362

| رقم الخط | حالة الخط | نوع الخط | إجمالي المبلغ لكل خط |
| :---: | :---: | :---: | :---: |
| 1 | 94939904 | Disconnected | 581.670 د.ك |
| 2 | 99817125 | Disconnected | Postpaid/MIXED | 574.099 د.ك |

**إجمالي المبلغ : 1155.769 د.ك**
"""
P_LINE1 = """# مستند (2)
94939904

| رقم الخط | رقم الفاتورة | تاريخ الفاتورة | مبلغ الفاتورة | المبلغ المدفوع | المتبقي |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 94939904 | 93409432 | 1/8/2025 | 464.07 | 0 | 464.07 |
| 94939904 | 92141354 | 1/7/2025 | 34.4 | 0 | 34.4 |
| 94939904 | 90844496 | 1/6/2025 | 34.4 | 0 | 34.4 |
| 94939904 | 89659568 | 1/5/2025 | 34.4 | 0 | 34.4 |
| 94939904 | 88274392 | 1/4/2025 | 59.4 | 45 | 14.4 |
| | | | 626.67 | 45 | 581.67 |
"""
P_INV1 = """رقم الفاتورة : 0093409432
رقم الخط: 94939904
رقم العقد: 1460362
المدفوعات حتى تاريخ 31/07/2025: 0.000 د.ك
**إجمالي الفاتورة: 581.670 د.ك**
| Commitment Penalty | | | 454.670 د.ك |
"""
P_INV1A = """رقم الفاتورة : 0088274392
رقم الخط: 94939904
رقم العقد: 1460362
| المدفوعات حتى تاريخ 31/03/2025 | 45.000- د.ك |
| المبالغ المدفوعة مقدما | 45.000- د.ك |
"""
P_DEV1 = """# مستند (3)
94939904

| تاريخ بدء العقد | تاريخ نهاية العقد | السيريال | نوع الجهاز | قيمة الالتزام | مدة الالتزام | المتبقي من مدة الالتزام | المتبقي من قيمة الجهاز |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1/3/2025 | 1/3/2026 | 352898270773584 | Zain Device Extended Warranty Service primary commitment | 42 | 12 | 8 | 28 |
| 1/3/2025 | 1/3/2028 | 352898270773584 | Samsung Galaxy Fold6 256GB Silver Shadow | 480 | 36 | 32 | 426.666667 |
"""
P_CONTRACT1 = """Zain Service Contract عقد خدمات
| التاريخ : 01/03/2025 | اشتراك دفع مسبق Pre-paid ☐ | اشتراك دفع آجل Post-paid ☑ | Date : 01/03/2025 |
| رقم العقد : | 1460362 | رقم الاشتراك : Contract No.: | 94939904 Subscription No.: |
"""
P_LINE2 = """# مستند (4)
99817125

| رقم الخط | رقم الفاتورة | تاريخ الفاتورة | مبلغ الفاتورة | المبلغ المدفوع | المتبقي |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 99817125 | 92141355 | 1/7/2025 | 480.9 | 0 | 480.9 |
| 99817125 | 90844497 | 1/6/2025 | 34.4 | 0 | 34.4 |
| 99817125 | 89659569 | 1/5/2025 | 34.4 | 0 | 34.4 |
| 99817125 | 88274393 | 1/4/2025 | 59.4 | 35 | 24.399 |
| | | | 609.1 | 35 | 574.099 |
"""
P_INV2 = """رقم الفاتورة : 0092141355
رقم الخط: 99817125
رقم العقد: 1460362
الاستخدام الشهري الرسوم الاضافية 471.500 د.ك
| Commitment Penalty | | | 471.500 د.ك |
"""
P_DEV2 = """# مستند (5)
| 99817125 | | | | | | | |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| تاريخ بدء العقد | تاريخ نهاية العقد | السيريال | نوع الجهاز | قيمة الالتزام | مدة الالتزام | المتبقي من مدة الالتزام | المتبقي من قيمة الجهاز |
| 1/3/2025 | 1/3/2028 | 352898270882096 | Samsung Galaxy Fold6 256GB Silver Shadow | 480 | 36 | 33 | 440 |
"""
P_ORDER2 = """### نموذج طلب الخدمة
| التاريخ / الوقت: | 01/03/2025 08:57 PM | | |
| اسم المشترك : | عبد الرحمن فهد عبد الرحمن الخراز | رقم العقد : | 1460362 |
| رقم الاشتراك : | 99817125 |
"""
PAGES = [(1, P_FACE), (4, P_STATEMENT), (6, P_LINE1), (7, P_INV1), (8, P_INV1A), (17, P_DEV1), (19, P_CONTRACT1),
         (28, P_LINE2), (30, P_INV2), (39, P_DEV2), (44, P_ORDER2)]
MEMO = [(1, "مذكرة دفاع\nمقدمة من:\nالسادة شركة الاتصالات المتنقلة ش.م.ك\nالمدعية\nالمدعى عليه\n"),
        (2, "تخصص المدعية دفاعها الماثل لبيان طبيعة العلاقة.")]
PLAINT = [(1, "بإلزام المعلن إليه بأن يؤدي إلى الطالبة مبلغ وقدره 1,155.770 د.ك (الف ومائة وخمسة وخمسون دينار) "
              "والمدعى عليه مدين لها بمبلغ وقدره 1,155.770 د.ك")]


def docs():
    out = [{'code': 'D1', 'file': 'm.pdf', 'kind': 'مذكرة دفاع', 'side': '', 'date': '18/10/2026', 'memo': True,
            'multi': False, 'pages': MEMO},
           {'code': 'D2', 'file': 'p.pdf', 'kind': 'حافظة مستندات', 'side': '', 'date': '18/10/2026', 'memo': False,
            'multi': False, 'pages': PAGES},
           {'code': 'D3', 'file': 's.pdf', 'kind': 'صحيفة الدعوى', 'side': '', 'date': '', 'memo': False, 'multi': False,
            'pages': PLAINT}]
    for d in out:
        d['side'] = cf.face_side('\n'.join(t for _n, t in d['pages'])) or d['side']
        d['docno'] = cf.doc_numbers(d['pages'])
    return out


def case_data():
    return {
        'caso_no': 'A2263973', 'subject_type': 'اتصالات',
        'case': {'caso_no': 'A2263973', 'plaintiff': 'شركة الاتصالات المتنقلة ش.م.ك.',
                 'defendants': ['عبدالرحمن فهد عبدالرحمن الخراز']},
        'mission': {'raw': MISSION, 'points': [{'id': 'q2', 'n': 1, 'text': MISSION}], 'confirmed': True},
        'procedures': {
            'received': {'date': '2026-10-06'}, 'booked': {'date': '2026-10-18'}, 'judgment': {'date': '20/09/2026'},
            'attendance': {
                'result': [{'present': True, 'certain': True, 'name': 'شركة الاتصالات المتنقلة ش.م.ك.', 'role': 'plaintiff'},
                           {'present': False, 'certain': True, 'name': 'عبدالرحمن فهد عبدالرحمن الخراز', 'role': 'defendant'}],
                'candidates': [{'label': 'المحضر 1', 'present': [], 'segment': 'لم يحضر أحد.'},
                               {'label': 'المحضر 3', 'present': [0],
                                'segment': 'وكيل المدعية/ احمد، ولم يحضر احد عن المدعى عليه على الرغم من صحه إعلانه.'}]}},
        'sessions': {'minutes': [{'no': 1, 'file': 'x1'}, {'no': 3, 'file': 'x2'}]},
    }


MINUTE_TEXT = {'x1': ['لم يحضر أحد.'], 'x2': ['قدم الحاضر عن المدعية مذكرة دفاع من 5 ورقات وحافظة مستندات، وأفاد الحاضر '
                                             'عن المدعية ان المدعى عليه لم يسدد أي مبلغ']}


def build_facts(data=None, model_raw=None):
    """build() بلا مجلد قضية: المدونة والمحاضر مستبدلة."""
    import research_pipeline as rp
    data = data or case_data()
    with mock.patch.object(cf, 'corpus', lambda base, d: docs()), \
            mock.patch.object(rp, 'MINUTE_TEXTS', lambda recs: {r['path']: MINUTE_TEXT.get(r['path'], []) for r in recs}), \
            mock.patch.object(cf, 'save', lambda base, f: None):
        ask = (lambda p: model_raw) if model_raw is not None else None
        f = cf.build('', data, ask=ask)
    return data, f


def ctx_of(model_raw=None, data=None):
    data, f = build_facts(data, model_raw)
    return rc.Ctx(data, f)


THREE_CONTRACTS = json.dumps({
    'contracts': [{'number': '94939904', 'quote': 'رقم الخط: 94939904', 'doc': 'D2', 'page': 7},
                  {'number': '99817125', 'quote': 'رقم الخط: 99817125', 'doc': 'D2', 'page': 30},
                  {'number': '1460362', 'quote': 'رقم العقد: 1460362', 'doc': 'D2', 'page': 4}],
    'invoices': [{'number': '', 'amount': '581.670', 'quote': 'إجمالي الفاتورة: 581.670 د.ك', 'doc': 'D2', 'page': 7}],
}, ensure_ascii=False)


class LedgerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.ctx = ctx_of()

    def test_line_totals_and_sum(self):
        g = {g['line']: g for g in self.ctx.L['groups']}
        self.assertEqual(g['94939904']['invoices'], Decimal('626.670'))
        self.assertEqual(g['94939904']['paid'], Decimal('45.000'))
        self.assertEqual(g['94939904']['remaining'], Decimal('581.670'))
        self.assertEqual(g['99817125']['invoices'], Decimal('609.100'))
        self.assertEqual(g['99817125']['paid'], Decimal('35.000'))
        self.assertEqual(g['99817125']['remaining'], Decimal('574.100'))
        self.assertEqual(self.ctx.L['total']['remaining'], Decimal('1155.770'))
        self.assertTrue(self.ctx.L['claim_match'])

    def test_fils_difference_flagged(self):
        texts = ' | '.join(c['text'] for c in self.ctx.L['checks'])
        self.assertIn('574.099', texts)
        self.assertIn('574.100', texts)
        self.assertIn('فرق 0.001', texts)
        self.assertIn('1,155.769', texts)

    def test_penalty_component_not_added_twice(self):
        g = {g['line']: g for g in self.ctx.L['groups']}['99817125']
        self.assertEqual(g['penalties'], Decimal('471.500'))
        self.assertEqual(g['invoices'], Decimal('609.100'))          # لا 1,080.600
        self.assertEqual(g['remaining_penalty'], Decimal('471.500'))

    def test_advance_payment_recorded(self):
        p = next(p for p in self.ctx.f['payments'] if p['invoice'] == '88274392')
        self.assertEqual(p['date'], '31/03/2025')
        self.assertEqual(p['note'], 'مقدماً')

    def test_statement_totals_never_invoices(self):
        nums = {i['number'] for i in self.ctx.f['invoices']}
        self.assertEqual(len(nums), 9)
        self.assertTrue(all(len(n) >= 8 for n in nums))
        self.assertTrue(any(t['scope'] == 'all' for t in self.ctx.f['statement_totals']))

    def test_formats(self):
        self.assertEqual(cf.money(Decimal('59.4')), '59.400')
        self.assertEqual(cf.money(Decimal('1155.77')), '1,155.770')
        self.assertEqual(cf.fmt_date('2025/03/01'), '01/03/2025')
        self.assertEqual(amounts.words_to_decimal(amounts.to_words(Decimal('1155.770'))), Decimal('1155.770'))


class ContractMatrixTests(unittest.TestCase):
    def test_one_contract_two_lines_not_three_contracts(self):
        ctx = ctx_of(THREE_CONTRACTS)
        self.assertEqual([c['number'] for c in ctx.contracts], ['1460362'])
        self.assertEqual([o['line'] for o in ctx.orders], ['94939904', '99817125'])
        self.assertTrue(all(o['contract'] == '1460362' for o in ctx.orders))
        rep = rc.compose(ctx, rc.draft_slots(ctx, None)[0])
        rel = next(a for a in rep['axes'] if a['kind'] == pb.AX_REL)['text']
        self.assertIn('بموجب عقد واحد', rel)
        self.assertNotIn('2-', rel.split('التزامات')[0])

    def test_model_total_as_invoice_moves_to_statement(self):
        ctx = ctx_of(THREE_CONTRACTS)
        self.assertEqual(ctx.L['total']['remaining'], Decimal('1155.770'))
        self.assertNotIn('', {i['number'] for i in ctx.f['invoices']})


def smart_slots(extra=None):
    s = {'rel.duty_p': 'تقديم خدمات الاتصالات المتنقلة والأجهزة المبينة بطلبات الخدمة',
         'rel.duty_d': 'سداد الفواتير الشهرية وأقساط الأجهزة في مواعيدها',
         'rel.scope.1': 'تقديم خدمات الاتصالات المتنقلة بنظام الدفع الآجل',
         'V1_relation.opinion': 'ترى الخبرة أن طرفي الدعوى يرتبطان بعقد اشتراك صحيح نافذ في حقهما.',
         'V2_breach.opinion': 'ترى الخبرة أن المدعى عليه أخل بالتزامه بالسداد.',
         'V5_debt.opinion': 'ترى الخبرة أن ذمة المدعى عليه مشغولة لصالح المدعية بمبلغ {{مبلغ:الإجمالي.متبقي}} د.ك '
                            '({{حروف:الإجمالي}}).'}
    s.update(extra or {})
    return json.dumps({'slots': s}, ensure_ascii=False)


DUMB = json.dumps({'slots': {
    'rel.duty_p': 'تقديم الخدمة بمبلغ 25 دينار شهرياً',                              # رقم خام
    'rel.duty_d': 'سداد الفواتير، والمدعى عليها ملتزمة بذلك',                          # جنس مخالف
    'V1_relation.opinion': 'مما سبق ترى الخبرة أن المديونية {{مبلغ:الإجمالي.متبقي}}',      # ممنوع + خانة من خارج المحور
    'V2_breach.opinion': 'ترى الخبرة أن المدعى عليه أخل بالتزامه بالسداد.',
    'V3_nature.opinion': 'ترى الخبرة أن المدعى عليه أخل بالتزامه بالسداد.',                # تكرار
    'V5_debt.opinion': 'ترى الخبرة أن ذمة المدعى عليه مشغولة بمبلغ 205.200 د.ك',         # الرقم الخاطئ من التقرير المعيب
}}, ensure_ascii=False)


class DumbModelTests(unittest.TestCase):
    def setUp(self):
        self.ctx = ctx_of()

    def test_dumb_rejected_and_fallback_correct(self):
        rep, errs, log = report_v3.produce(self.ctx, lambda p: DUMB)
        self.assertEqual(errs, [])
        for sid in ('rel.duty_p', 'rel.duty_d', 'V1_relation.opinion', 'V3_nature.opinion', 'V5_debt.opinion'):
            self.assertIn(sid, log['fallback'])
        full = rc.full_text(rep)
        self.assertNotIn('205.200', full)
        self.assertNotIn('25 دينار', full)
        self.assertNotIn('المدعى عليها', full)
        self.assertNotIn('مما سبق', full)
        self.assertIn('1,155.770', full)

    def test_dumb_then_corrected(self):
        replies = iter([DUMB, smart_slots()])
        rep, errs, log = report_v3.produce(self.ctx, lambda p: next(replies))
        self.assertEqual(errs, [])
        self.assertIn('rel.duty_p', log['model'])
        self.assertIn('V5_debt.opinion', log['model'])
        debt = next(a for a in rep['axes'] if a['kind'] == pb.AX_DEBT)['text']
        self.assertIn('ترى الخبرة أن ذمة المدعى عليه مشغولة لصالح المدعية بمبلغ 1,155.770 د.ك', debt)

    def test_raw_number_rejected_in_slot(self):
        _t, errs = rc.check_slot('rel.duty_d', 'سداد مبلغ 609.100 د.ك', self.ctx)
        self.assertTrue(any('رقم خام' in e for e in errs))

    def test_placeholder_outside_axis_rejected(self):
        _t, errs = rc.check_slot('V1_relation.opinion', 'ترى الخبرة أن المتبقي {{مبلغ:الإجمالي.متبقي}}', self.ctx)
        self.assertTrue(any('خارج حقائق هذا المحور' in e or 'غير مسموحة في هذه الخانة' in e for e in errs))

    def test_english_and_line_placeholders_rejected(self):
        _t, errs = rc.check_slot('rel.scope.1', 'تقديم خدمات للخط {{رقم:خط1.رقم}}', self.ctx)
        self.assertTrue(any('غير مسموحة' in e for e in errs))
        _t, errs = rc.check_slot('V6_defense.opinion', 'ترى الخبرة أن The defendant failed to pay.', self.ctx)
        self.assertTrue(any('غير عربي' in e for e in errs))

    def test_model_summary_never_english(self):
        self.assertEqual(cf._clean_summary('The defendant failed to pay the monthly invoices'), '')
        self.assertEqual(cf._clean_summary('دفع بسداد مبلغ 50 د.ك'), '')

    def test_audit_failure_retries_once_then_reports(self):
        calls = []

        def ask(p):
            calls.append(p)
            return smart_slots()
        with mock.patch.object(ra, 'audit', side_effect=[['(و) المحور أولاً: خطأ مصطنع'], ['(و) المحور أولاً: خطأ مصطنع'],
                                                          ['(و) المحور أولاً: خطأ مصطنع']]):
            rep, errs, log = report_v3.produce(self.ctx, ask)
        self.assertEqual(log['audit_attempts'], 2)
        self.assertTrue(errs)
        self.assertTrue(any('رُفضت صياغتك السابقة' in p for p in calls[1:]))


class AxisScopeTests(unittest.TestCase):
    """الجزء 8: كل محور يجيب عن سؤاله فقط."""

    def setUp(self):
        self.ctx = ctx_of()
        self.rep = rc.compose(self.ctx, rc.draft_slots(self.ctx, None)[0])

    def axis(self, kind):
        return next(a for a in self.rep['axes'] if a['kind'] == kind)['text']

    def test_relation_axis_has_no_invoice_or_debt(self):
        rel = self.axis(pb.AX_REL)
        for inv in self.ctx.f['invoices']:
            self.assertNotIn(inv['number'], rel)
        for v in ('581.670', '574.100', '1,155.770', '609.100', '626.670', '45.000', '35.000', '471.500'):
            self.assertNotIn(v, rel)

    def test_breach_axis_has_no_tables(self):
        self.assertNotIn('|', self.axis(pb.AX_BREACH))
        self.assertNotIn('|', self.axis(pb.AX_DEF))

    def test_invoices_only_in_debt_tables_once(self):
        full = rc.full_text(self.rep)
        for inv in self.ctx.f['invoices']:
            self.assertEqual(full.count(inv['number']), 1)
        debt = self.axis(pb.AX_DEBT)
        self.assertIn('| 92141355 |', debt)

    def test_audit_rejects_debt_amount_in_relation(self):
        bad = json.loads(json.dumps(self.rep, ensure_ascii=False))
        a = next(x for x in bad['axes'] if x['kind'] == pb.AX_REL)
        a['text'] += '\n\nوترصد مبلغ 581.670 د.ك عن الفاتورة 93409432.'
        errs = ra.audit(bad, self.ctx)
        self.assertTrue(any(e.startswith('(ك)') for e in errs))
        self.assertTrue(any(e.startswith('(ج)') for e in errs))


class ShapeTests(unittest.TestCase):
    def setUp(self):
        self.ctx = ctx_of()
        self.rep = rc.compose(self.ctx, rc.draft_slots(self.ctx, None)[0])

    def test_clean_report_passes_audit(self):
        self.assertEqual(ra.audit(self.rep, self.ctx), [])

    def test_word_count_under_900(self):
        self.assertLess(rc.word_count(self.rep), 900)

    def test_one_section_per_axis_and_conclusion_count(self):
        kinds = [a['kind'] for a in self.rep['axes']]
        self.assertEqual(kinds, [pb.AX_REL, pb.AX_BREACH, pb.AX_NATURE, pb.AX_VALUE, pb.AX_DEBT, pb.AX_DEF])
        self.assertEqual(len(self.rep['conclusion']), len(self.rep['axes']))
        for a in self.rep['axes']:
            self.assertLessEqual(len(a['title'].split()), 8)
            self.assertGreaterEqual(len(a['title'].split()), 3)
            self.assertEqual(a['text'].count('ترى الخبرة'), 1)
        for p, a in zip(self.rep['conclusion'], self.rep['axes']):
            self.assertTrue(p['text'].startswith('أن'))
            self.assertIn(f"كما هو موضح تفصيلياً في بند البحث ورأي الخبرة ({a['ordinal']})", p['text'])
            self.assertNotIn('مرفق', p['text'])

    def test_final_amount_matches_ledger(self):
        debt = next(p for p in self.rep['conclusion'] if p['axis'].endswith('debt'))
        self.assertIn('1,155.770', debt['text'])
        self.assertIn(amounts.to_words(Decimal('1155.770')), debt['text'])
        self.assertEqual(self.rep['final']['shown'], '1,155.770')

    def test_gender_masculine_defendant(self):
        full = rc.full_text(self.rep)
        self.assertNotIn('المدعى عليها', full)
        self.assertIn('المدعى عليه', full)

    def test_refs_first_mention_no_page_no_plaint(self):
        full = rc.full_text(self.rep)
        self.assertNotIn('(صحيفة الدعوى)', full)
        self.assertNotIn('(حكم الإحالة)', full)
        self.assertNotRegex(full, r'(?<!\S)(?:ص|صفحة)\s*\d')
        self.assertEqual(full.count('(مرفق بحافظة مستندات المدعية المؤرخة 18/10/2026 مستند 2)'), 1)
        self.assertNotIn('بادئ ذي بدء', full)
        self.assertNotIn('أمانة', full)

    def test_procedures_from_minutes(self):
        p = self.rep['procedures']
        self.assertIn('وحددنا عدة جلسات حضرتها الشركة المدعية', p)         # العدد لا يُكتب أبداً
        self.assertNotIn('جلستين', p)
        self.assertNotIn('مناقشة أطراف الدعوى', p)
        self.assertIn('وتخلف المدعى عليه عن الحضور رغم صحة إعلانه', p)
        self.assertIn('06/10/2026', p)
        self.assertIn('18/10/2026', p)

    def test_notified_only_if_proven(self):
        data = case_data()
        data['procedures']['attendance']['candidates'][1]['segment'] = 'ولم يحضر احد عن المدعى عليه.'
        with mock.patch.dict(MINUTE_TEXT, {'x2': ['ولم يحضر احد عن المدعى عليه.']}):
            ctx = ctx_of(data=data)
        p = rc.procedures_text(ctx)[0]
        self.assertIn('وتخلف المدعى عليه عن الحضور', p)
        self.assertNotIn('رغم صحة إعلانه', p)

    def test_subject_elements(self):
        s, miss = rc.subject_text(self.ctx)
        for v in ('(1460362)', '01/03/2025', '(94939904)', '(99817125)', 'Samsung Galaxy Fold6', '(36) شهراً', '1,155.770'):
            self.assertIn(v, s)
        self.assertEqual(miss, ['المبلغ الشهري'])

    def test_defense_axis_absent_defendant(self):
        d = next(a for a in self.rep['axes'] if a['kind'] == pb.AX_DEF)['text']
        self.assertIn('تخلف المدعى عليه عن حضور جلسات الخبرة رغم صحة إعلانه', d)
        self.assertNotIn('1,155.770', d)

    def test_feminine_defendant(self):
        data = case_data()
        data['procedures']['attendance']['result'][1]['name'] = 'شركة الخليج للتجارة'
        ctx = ctx_of(data=data)
        rep = rc.compose(ctx, rc.draft_slots(ctx, None)[0])
        full = rc.full_text(rep)
        self.assertIn('المدعى عليها', full)
        self.assertEqual(ra.audit(rep, ctx), [])


class AuditDetectionTests(unittest.TestCase):
    def setUp(self):
        self.ctx = ctx_of()
        self.rep = rc.compose(self.ctx, rc.draft_slots(self.ctx, None)[0])

    def mutate(self, kind, extra):
        bad = json.loads(json.dumps(self.rep, ensure_ascii=False))
        next(x for x in bad['axes'] if x['kind'] == kind)['text'] += '\n\n' + extra
        return ra.audit(bad, self.ctx)

    def test_unformatted_numbers(self):
        errs = self.mutate(pb.AX_DEBT, 'وبلغت الفاتورة 59.4 د.ك بتاريخ 2025/04/01.')
        self.assertTrue(any('ثلاث خانات' in e for e in errs))
        self.assertTrue(any('dd/mm/yyyy' in e for e in errs))

    def test_invented_number(self):
        self.assertTrue(any('غير موجود في الحقائق' in e for e in self.mutate(pb.AX_DEBT, 'وبمبلغ 205.200 د.ك.')))

    def test_similar_sentences(self):
        s = 'ثبت للخبرة صدور الفواتير الشهرية عن الخطين وامتنع المدعى عليه عن سدادها دون أي سبب مشروع ثابت.'
        self.assertTrue(any(e.startswith('(د)') for e in self.mutate(pb.AX_BREACH, s + '\n\n' + s)))

    def test_forbidden_refs_and_codes(self):
        errs = self.mutate(pb.AX_NATURE, 'كما ورد (صحيفة الدعوى) وفي [P1-2 ص6] وبادئ ذي بدء.')
        self.assertTrue(sum(1 for e in errs if e.startswith('(و)')) >= 3)

    def test_penalty_added_twice(self):
        self.assertTrue(any(e.startswith('(ح)') for e in
                            self.mutate(pb.AX_DEBT, 'والإجمالي = 609.100 + 471.500 = 1,080.600 د.ك.')))

    def test_conclusion_count(self):
        bad = json.loads(json.dumps(self.rep, ensure_ascii=False))
        bad['conclusion'] = bad['conclusion'][:-1]
        self.assertTrue(any(e.startswith('(ي)') for e in ra.audit(bad, self.ctx)))

    def test_long_heading(self):
        bad = json.loads(json.dumps(self.rep, ensure_ascii=False))
        bad['axes'][0]['heading'] = 'أولاً: ' + ' '.join(['بيان'] * 14) + ':'
        self.assertTrue(any(e.startswith('(هـ)') for e in ra.audit(bad, self.ctx)))


class MissionAxesTests(unittest.TestCase):
    def test_axes_from_case_mission(self):
        axes = pb.mission_axes(case_data())
        self.assertEqual([a['kind'] for a in axes],
                         [pb.AX_REL, pb.AX_BREACH, pb.AX_NATURE, pb.AX_VALUE, pb.AX_DEBT, pb.AX_DEF])
        self.assertTrue(all(3 <= len(a['title'].split()) <= 8 for a in axes))


class GeminiModelTests(unittest.TestCase):
    NAMES = ['gemini-2.5-pro', 'gemini-2.5-pro-preview-tts', 'gemini-pro-latest', 'gemini-3.1-pro-preview',
             'gemini-3.1-pro-preview-customtools', 'gemini-3-pro-image-preview', 'gemini-flash-latest', 'nano-banana-pro-preview']

    def test_pick_latest_pro(self):
        import gemini_config as gc
        self.assertEqual(gc.rank_pro(self.NAMES)[0], 'gemini-3.1-pro-preview')
        self.assertNotIn('gemini-3-pro-image-preview', gc.rank_pro(self.NAMES))
        self.assertNotIn('gemini-2.5-pro-preview-tts', gc.rank_pro(self.NAMES))

    def _caps(self, tmp):
        import gemini_config as gc
        return mock.patch.object(gc, '_caps_path', return_value=os.path.join(tmp, 'caps.json'))

    def test_candidates_follow_what_key_allows(self):
        import gemini_config as gc
        import tempfile

        class Ok:
            def generate_content(self, model, **k):
                return type('R', (), {'text': 'نعم'})()
        client = type('C', (), {'models': Ok()})()
        with tempfile.TemporaryDirectory() as tmp, self._caps(tmp),                 mock.patch.object(gc, 'pro_setting', return_value='auto'),                 mock.patch.object(gc, 'list_models', return_value=self.NAMES):
            c = gc.pro_candidates(client, 'KEY-PRO')
            self.assertEqual(c[0], 'gemini-3.1-pro-preview')               # المفتاح يتيح Pro
            self.assertTrue(gc.cached_key_model('KEY-PRO')['pro'])
        with mock.patch.object(gc, 'pro_setting', return_value='gemini-2.5-pro'):
            self.assertEqual(gc.pro_candidates(None, 'k')[0], 'gemini-2.5-pro')

    def test_free_key_without_pro_uses_latest_flash_and_is_remembered(self):
        import gemini_config as gc
        import tempfile
        names = self.NAMES + ['gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemma-4-31b-it']
        calls = []

        class Models:
            def generate_content(self, model, **k):
                calls.append(model)
                if 'pro' in model:
                    raise RuntimeError("429 RESOURCE_EXHAUSTED quota 'GenerateRequestsPerDayPerProjectPerModel-FreeTier' limit: 0")
                return type('R', (), {'text': 'ok'})()
        client = type('C', (), {'models': Models()})()
        with tempfile.TemporaryDirectory() as tmp, self._caps(tmp),                 mock.patch.object(gc, 'pro_setting', return_value='auto'),                 mock.patch.object(gc, 'list_models', return_value=names):
            c = gc.pro_candidates(client, 'FREE')
            self.assertEqual(c[0], 'gemini-3.6-flash')                      # أحدث Flash من قائمة الـAPI
            self.assertFalse(gc.cached_key_model('FREE')['pro'])
            n = len(calls)
            gc.pro_candidates(client, 'FREE')
            self.assertEqual(len(calls), n)                                 # لا تجربة Pro في كل طلب
            self.assertNotIn('gemma-4-31b-it', c)                           # Gemma خارج الخطة (2026-10-25)
            self.assertNotIn('gemini-flash-latest', c)                      # لا أسماء مستعارة
            gc._generate_on_client(client, models=c, contents=['x'])
            self.assertEqual(gc.describe_model(gc.last_model_used()[0]), 'gemini-3.6-flash')
            self.assertIn('نموذج احتياطي', gc.describe_model('gemini-3.6-flash', True))

    def test_daily_quota_model_is_skipped_until_reset(self):
        import gemini_config as gc
        import tempfile

        class Models:
            def generate_content(self, model, **k):
                if model == 'gemini-3.6-flash':
                    raise RuntimeError("429 RESOURCE_EXHAUSTED 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier' "
                                       "'retryDelay': '3600s'")
                return type('R', (), {'text': 'ok'})()
        client = type('C', (), {'models': Models()})()
        with tempfile.TemporaryDirectory() as tmp, self._caps(tmp):
            gc._KEY_CTX.kid = gc.key_id('Q')
            gc._generate_on_client(client, models=['gemini-3.6-flash', 'gemini-3.5-flash'], contents=['x'])
            self.assertEqual(gc.last_model_used()[0], 'gemini-3.5-flash')
            self.assertIn('gemini-3.6-flash', gc.exhausted_models('Q'))

    def test_research_never_small_model(self):
        import ai_providers as ap
        import case_research as cr
        seen = {}

        def fake_chain(task, spec=None):
            seen['spec'] = spec
            raise ap.ProviderMissing(task, spec, 'x')
        with mock.patch.object(ap, 'build_task_chain', fake_chain), \
                mock.patch.object(ap, 'get_task_specs', return_value={'research': 'gemini,openai'}):
            with self.assertRaises(ap.ProviderMissing):
                cr.default_ask('x', 'research')
        self.assertEqual(seen['spec'], 'gemini')


class OcrRedoTests(unittest.TestCase):
    """الجزء 7: زر 🔄 — قائمة بنمط صريح (لا صندوق أسود)، تقدّم الصفحات، والفشل حالة برسالة لا استثناء مبلوع."""

    def test_styled_menu(self):
        from PyQt6.QtWidgets import QApplication, QPushButton
        app = QApplication.instance() or QApplication([])
        import qt_context_menu as qc
        self.btn = QPushButton()
        m = qc.styled_menu(self.btn, 'أعد قراءة المستند بمحرّك:')
        self.assertIn('QMenu', m.styleSheet())
        self.assertFalse(m.actions()[0].isEnabled())
        del app

    def test_reconvert_progress_and_failure(self):
        import case_documents as cd
        import doc_router
        d = {'uid': 'd1', 'file': 'a.pdf', 'md': 'a.md', 'engine': doc_router.ENGINE_LOCAL,
             'convert': {'state': 'done', 'message': ''}}
        data = {'portfolios': [{'id': 'P1', 'docs': [d]}]}
        ups = []

        def conv_doc(base, doc, convert, engines=None):
            doc_router.page_progress(1, 2)
            raise RuntimeError('انقطع الاتصال')
        with mock.patch.object(cd, '_convert_doc', conv_doc), mock.patch.object(cd, '_save', lambda *a: None), \
                mock.patch.object(cd, '_memory', lambda *a: None), mock.patch.object(cd, '_sync_attachments', lambda *a: None), \
                mock.patch.object(cd, '_refresh_step', lambda *a: None), mock.patch.object(cd, 'find_doc', lambda dt, u: (None, d)), \
                mock.patch.object(cd.cm, 'state', return_value='running'):
            st = cd.reconvert('', data, 'd1', on_update=lambda u, c: ups.append(dict(c)))
        self.assertEqual(st, 'failed')
        self.assertIn('انقطع الاتصال', d['convert']['message'])
        self.assertTrue(any(c.get('progress') == 50 for c in ups))


class ProceduresGateTests(unittest.TestCase):
    """نص الإجراءات وفق نماذج_صياغة_الإجراءات.md وبوابة الاكتمال: الحضور والتخلف من المحاضر فقط، «رغم صحة إعلانه» عند ثبوته،
    ولا «تم مناقشة أطراف الدعوى» إن تخلف طرف، ولا تخلف/مناقشة/عدد جلسات مع نقص محضر."""

    def proc(self, data=None):
        return rc.procedures_text(ctx_of(data=data))

    def test_complete_absent_defendant_notified_and_partial_plaintiff(self):
        p, miss = self.proc()
        self.assertIn('وحددنا عدة جلسات حضرتها الشركة المدعية وتخلف المدعى عليه عن الحضور رغم صحة إعلانه', p)
        self.assertNotIn('إحداهما', p)
        self.assertNotIn('تم مناقشة أطراف الدعوى', p)

    def test_plaintiff_in_every_session_uses_pronoun_form(self):
        data = case_data()
        data['procedures']['attendance']['candidates'][0]['present'] = [0]
        p, _ = self.proc(data)
        self.assertIn('وحددنا عدة جلسات حضرتها الشركة المدعية وتخلف المدعى عليه عن الحضور رغم صحة إعلانه', p)
        self.assertNotIn('حضرتهما', p)
        self.assertIn('وتمت مناقشة الحاضر عن', p)            # لا «تم مناقشة أطراف الدعوى» وطرف متخلف
        self.assertNotIn('تم مناقشة أطراف الدعوى', p)

    def test_all_present_is_discussed_with_parties(self):
        data = case_data()
        data['procedures']['attendance']['result'][1]['present'] = True
        data['procedures']['attendance']['candidates'][0]['present'] = [0, 1]
        data['procedures']['attendance']['candidates'][1]['present'] = [0, 1]
        with mock.patch.dict(MINUTE_TEXT, {'x2': ['حضر الطرفان وتمت مناقشة الأطراف']}):
            p, _ = self.proc(data)
        self.assertIn('وتم مناقشة أطراف الدعوى', p)
        self.assertNotIn('تخلف', p)

    def test_missing_minute_withholds_absence_discussion_and_count(self):
        data = case_data()
        data['sessions']['missing_count'] = 1
        with mock.patch.dict(MINUTE_TEXT, {'x2': ['وأفاد الحاضر عن المدعية بمناقشة الموضوع']}):
            p, miss = self.proc(data)
        self.assertIn('عدة جلسات', p)
        self.assertNotIn('جلستين', p)
        self.assertNotIn('تخلف', p)
        self.assertNotIn('رغم صحة إعلانه', p)
        self.assertNotIn('مناقشة', p)
        self.assertTrue(any('ينقص محضر واحد' in m for m in miss), miss)

    def test_missing_minute_does_not_claim_defendant_attended_or_absent_elsewhere(self):
        data = case_data()
        data['sessions']['missing_count'] = 1
        ctx = ctx_of(data=data)
        mf = ctx.f['minutes']
        self.assertFalse(mf['complete'])
        self.assertNotIn('defendant', mf['attended'])
        self.assertFalse(mf['all_present'])
        defense = ' '.join(rc.axis_defense(ctx, {'kind': pb.AX_DEF}, None))
        self.assertNotIn('تخلف', defense)
        self.assertNotIn('حضر', defense)

    def test_complete_flag_default_true_without_shortfall(self):
        self.assertTrue(ctx_of().f['minutes']['complete'])


@unittest.skipUnless(os.path.isdir(REAL_CASE), 'مجلد القضية الحقيقية غير موجود على هذا الجهاز')
class RealCaseTests(unittest.TestCase):
    """تجربة على القضية A2263973 نفسها (نسخة مؤقتة؛ الأصل لا يُلمس): قارئ الكود + نموذج «غبي»."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='v3_')
        cls.base = os.path.join(cls.tmp, 'A2263973')
        shutil.copytree(REAL_CASE, cls.base)
        cls.data = cw.read_case_json(cls.base)
        cls.data.pop('facts3', None)

        def ask(p):
            return THREE_CONTRACTS if 'مستخرج حقائق' in p else DUMB
        import research_pipeline as rp
        cls.state = rp.run(cls.base, cls.data, ask=ask)
        cls.r = rp.state(cls.data)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_numbers(self):
        f = self.data['facts3']
        L = calc.ledger(f)
        g = {g['line']: g['remaining'] for g in L['groups']}
        self.assertEqual(g['94939904'], Decimal('581.670'))
        self.assertEqual(g['99817125'], Decimal('574.100'))
        self.assertEqual(L['total']['remaining'], Decimal('1155.770'))
        self.assertEqual([c['number'] for c in f['contracts']], ['1460362'])

    def test_audit_ok_and_notes(self):
        import research_pipeline as rp
        self.assertTrue(self.r['audit']['ok'], self.r['audit']['errors'])
        notes = ' | '.join(t for _k, t, _w in rp.notes_list(self.data))
        self.assertIn('574.099', notes)
        self.assertLess(self.r['v3']['words'], 900)
        # القضية الحقيقية مجلد حيّ يتغير (محاضر تُضاف/تنقص)، فلا نثبّت صياغة بعينها: الصياغة تتبع بوابة الاكتمال
        # (نماذج_صياغة_الإجراءات.md). التفاصيل الحتمية في ProceduresGateTests.
        proc = self.data['procedures']['text']
        if (self.data.get('sessions') or {}).get('missing_count'):
            self.assertIn('عدة جلسات', proc)
            self.assertNotIn('تخلف', proc)
            self.assertNotIn('مناقشة', proc)
        else:
            self.assertRegex(proc, r'حضر(?:ت)?(?:ها|هما)? (?:الشركة المدعية|وكيل المدعية)')
        self.assertNotIn('المدعى عليها', rp.research_text(self.base, self.data) + self.data['subject'])


class PdfRereadTests(unittest.TestCase):
    """(2026-10-25) مستند مهم نصه رديء ← طلب ثانٍ ومعه PDF الأصلي (need_pdf أو صفحات مدموجة بلا فواتير متحقَّقة)."""

    def setUp(self):
        from pypdf import PdfWriter
        self.base = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.base, 'حوافظ'))
        w = PdfWriter()
        for _ in range(5):
            w.add_blank_page(width=200, height=200)
        with open(os.path.join(self.base, 'حوافظ', 'h.pdf'), 'wb') as f:
            w.write(f)
        self.facts = {'docs': [{'code': 'D3', 'kind': 'حافظة مستندات', 'memo': False, 'file': 'حوافظ/h.pdf',
                                'merged': [[1, 3]]},
                               {'code': 'D9', 'kind': 'صحيفة الدعوى', 'memo': False, 'file': 'حوافظ/h.pdf', 'merged': []}],
                      'invoices': [], 'need_pdf': []}

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_auto_request_for_merged_bundle_without_invoices(self):
        reqs = report_v3.pdf_requests(self.base, self.facts)
        self.assertEqual([(c, a, b) for c, _p, a, b, _w in reqs], [('D3', 1, 3)])

    def test_no_auto_request_when_invoices_verified(self):
        self.facts['invoices'] = [{'number': '1'}]
        self.assertEqual(report_v3.pdf_requests(self.base, self.facts), [])

    def test_model_request_and_plaint_never_sent(self):
        self.facts['invoices'] = [{'number': '1'}]
        self.facts['need_pdf'] = [{'doc': 'D9', 'pages': '1', 'why': ''}, {'doc': 'D3', 'pages': '2-4', 'why': 'مشوّه'}]
        self.assertEqual([(c, a, b) for c, _p, a, b, _w in report_v3.pdf_requests(self.base, self.facts)],
                         [('D3', 2, 4)])

    def test_reread_sends_cut_pdf_and_returns_reply(self):
        seen = {}

        def fake(prompt, paths):
            from pypdf import PdfReader
            seen['pages'] = [len(PdfReader(p).pages) for p in paths]
            seen['prompt'] = prompt
            return json.dumps({'invoices': [], 'reread': [{'doc': 'D3', 'page': 2, 'text': 'نص'}]})
        with mock.patch.object(report_v3, 'PDF_ASK', fake):
            got = report_v3.reread_pdf(self.base, {}, [('D3', os.path.join(self.base, 'حوافظ', 'h.pdf'), 2, 4, 'x')],
                                       'الطلب')
        self.assertEqual(seen['pages'], [3])
        self.assertIn('المرفق 1 = D3، الصفحات 2–4', seen['prompt'])
        self.assertIn('"reread"', seen['prompt'])
        self.assertEqual(got[1]['reread'][0]['page'], 2)

    def test_tie_prefers_first_reply(self):
        """الانحدار (A2263970): الطلب الثاني بلا reread تعادل مع الأول (4 و4) فاعتُمد وضاعت فاتورتان متحقَّقتان."""
        first = {'invoices': [1, 2], 'payments': [1, 2]}
        second = {'service_orders': [1, 2], 'payments': [1, 2]}
        self.assertFalse(report_v3._n_facts(second) > report_v3._n_facts(first))
        self.assertFalse(report_v3._n_facts(first) > report_v3._n_facts(dict(first)))
        self.assertTrue(report_v3._n_facts({'invoices': [1, 2, 3]}) > report_v3._n_facts(first))

    def test_reread_failure_keeps_first_reply(self):
        def boom(prompt, paths):
            raise RuntimeError('network')
        with mock.patch.object(report_v3, 'PDF_ASK', boom):
            self.assertIsNone(report_v3.reread_pdf(self.base, {}, [('D3', os.path.join(self.base, 'حوافظ', 'h.pdf'),
                                                                    None, None, 'x')], 'الطلب'))


class FullReportTimeoutTests(unittest.TestCase):
    """الطلب الواحد لكتابة التقرير انقطع عند 180ث (السجل 25/10): يأخذ مهلة طويلة، وبقية طلبات البحث تبقى 180."""

    def test_long_request_only_inside_context(self):
        import case_research as cr
        self.assertEqual(cr.research_timeout(), cr.RESEARCH_TIMEOUT)
        with cr.long_request():
            self.assertEqual(cr.research_timeout(), cr.FULL_REPORT_TIMEOUT)
        self.assertEqual(cr.research_timeout(), cr.RESEARCH_TIMEOUT)
        self.assertGreater(cr.FULL_REPORT_TIMEOUT, cr.RESEARCH_TIMEOUT)

    def test_default_ask_uses_long_timeout_for_research(self):
        import ai_providers
        import case_research as cr
        seen = []

        def fake_chain(call, size, timeout, chain=None):
            seen.append(timeout)
            return mock.Mock(text='{}', provider='')
        with mock.patch.object(ai_providers, 'build_task_chain', return_value=[]),                 mock.patch.object(ai_providers, 'run_chain', side_effect=fake_chain):
            cr.default_ask('x', 'research', spec='gemini')
            with cr.long_request():
                cr.default_ask('x', 'research', spec='gemini')
        self.assertEqual(seen, [cr.RESEARCH_TIMEOUT, cr.FULL_REPORT_TIMEOUT])


if __name__ == '__main__':
    unittest.main()
