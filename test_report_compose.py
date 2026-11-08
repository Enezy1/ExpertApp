# ===== test_report_compose.py — انحدار تركيب «طبيعة العلاقة» والمديونية (2026-10-25، القضية A2263970) =====
# كان محور العلاقة: «عقد الاشتراك رقم (…)، حيث تلتزم المدعية بتقديم خدمات الاشتراك، مقابل اشتراك شهري» بلا أطراف بأسمائهم
# ولا خطوط ولا أجهزة ولا أقساط ولا مدة؛ وحين لم تتحقق الفواتير كتب البرنامج للنموذج «لم تثبت مديونية» فخرجت النتيجة
# «ذمة المدعى عليها غير مشغولة» والمطالبة 937.561 د.ك.
import copy
import unittest
from decimal import Decimal

import report_audit as ra
import report_compose as rc
import report_playbooks as pb
import test_report_v3 as t3


def _rel(ctx, S=None):
    a = next(x for x in ctx.axes if x['kind'] == pb.AX_REL)
    S = S or {sid: rc.fallback(ctx, sid) for sid, *_r in rc.slot_specs(ctx)}
    return '\n'.join(rc.axis_relation(ctx, a, S))


class RelationTests(unittest.TestCase):
    def setUp(self):
        self.ctx = t3.ctx_of()

    def test_parties_by_name_and_role(self):
        t = _rel(self.ctx)
        self.assertIn('بين الشركة المدعية (شركة الاتصالات المتنقلة ش.م.ك.) بصفتها مقدّمة الخدمة', t)
        self.assertIn('والمدعى عليه (عبدالرحمن فهد عبدالرحمن الخراز) بصفته المشترك', t)

    def test_contract_with_date_and_lines(self):
        t = _rel(self.ctx)
        self.assertIn('عقد الاشتراك رقم (1460362) المؤرخ 01/03/2025', t)
        self.assertIn('عن الخطين رقمي (94939904) و(99817125)', t)

    def test_lines_table_with_device_and_installment(self):
        ctx = self.ctx
        for o, m in zip(ctx.orders, ('13.333', '13.334')):
            o['monthly'], o['plan'], o['plan_monthly'] = Decimal(m), 'Always ON 15', '15.000'
        t = _rel(ctx)
        self.assertIn('| رقم الخط | الجهاز | قسط الجهاز الشهري (د.ك) |', t)
        self.assertIn('| (94939904) |', t)
        self.assertIn('13.333', t)
        self.assertIn('Always ON 15', t)
        self.assertIn('مقابل اشتراك شهري وأقساط شهرية للأجهزة مبينة بالجدول التالي', t)

    def test_relation_passes_audit(self):
        ctx = self.ctx
        rep = rc.compose(ctx, {sid: rc.fallback(ctx, sid) for sid, *_r in rc.slot_specs(ctx)})
        self.assertFalse([e for e in ra.audit(rep, ctx) if 'المحور أولاً' in e or 'النتيجة (أولاً)' in e])

    def test_nature_does_not_repeat_lines_table(self):
        ctx = self.ctx
        a = next(x for x in ctx.axes if x['kind'] == pb.AX_NATURE)
        t = '\n'.join(rc.axis_nature(ctx, a, {}))
        self.assertIn('بجدول البند (أولاً)', t)
        self.assertNotIn('1- الخط رقم', t)

    def test_conclusion_names_parties_and_installments(self):
        ctx = self.ctx
        for o in ctx.orders:
            o['monthly'] = Decimal('13.333')
        p = next(x for x in rc.conclusion_paragraphs(ctx) if x['ordinal'] == 'أولاً')['text']
        self.assertIn('علاقة تعاقدية بين الشركة المدعية والمدعى عليه بموجب عقد الاشتراك رقم (1460362)', p)
        self.assertIn('وأقساط الأجهزة الشهرية (13.333) د.ك للخط (94939904)', p)


class NoInvoicesTests(unittest.TestCase):
    """لا فاتورة متحقَّقة: لا يُحكم بثبوت المديونية ولا بنفيها."""

    def setUp(self):
        data, f = t3.build_facts()
        f = copy.deepcopy(f)
        f['invoices'], f['payments'] = [], []
        self.ctx = rc.Ctx(data, f)

    def test_prompt_does_not_say_no_debt(self):
        p = rc.slots_prompt(self.ctx, rc.slot_specs(self.ctx))
        self.assertNotIn('لم تثبت مديونية', p)
        self.assertIn('لا تحكم بثبوت مديونية', p)

    def test_conclusion_says_could_not_settle(self):
        texts = {p['ordinal']: p['text'] for p in rc.conclusion_paragraphs(self.ctx)}
        debt = next(a['ordinal'] for a in self.ctx.axes if a['kind'] == pb.AX_DEBT)
        self.assertIn('لم تتمكن من تصفية الحساب', texts[debt])
        self.assertNotIn('غير مشغولة', texts[debt])

    def test_fallback_opinion(self):
        key = next(a['key'] for a in self.ctx.axes if a['kind'] == pb.AX_DEBT)
        self.assertIn('ترى الخبرة أنها لم تتمكن من تصفية الحساب', rc.fallback(self.ctx, f'{key}.opinion'))

    def test_no_invoices_report_passes_audit(self):
        """الانحدار (A2263970): «فقرة المديونية لا تحمل المبلغ المحسوب 6.000» و«فقرتان متشابهتان (2 و5)» أفشلتا المحاور
        الستة كلها حين لم تتحقق أي فاتورة."""
        ctx = self.ctx
        rep = rc.compose(ctx, {sid: rc.fallback(ctx, sid) for sid, *_r in rc.slot_specs(ctx)})
        errs = ra.audit(rep, ctx)
        self.assertFalse([e for e in errs if e.startswith(('(ب)', '(د)'))], errs)


class DebtOpinionGuardTests(unittest.TestCase):
    def test_opinion_negating_computed_debt_rejected(self):
        ctx = t3.ctx_of()
        key = next(a['key'] for a in ctx.axes if a['kind'] == pb.AX_DEBT)
        _t, errs = rc.check_slot(f'{key}.opinion', 'ترى الخبرة أنه لم تثبت مديونية متبقية بذمة المدعى عليه.', ctx)
        self.assertTrue(any('ينفيها' in e for e in errs), errs)
        _t, ok = rc.check_slot(f'{key}.opinion', 'ترى الخبرة أن ذمة المدعى عليه مشغولة بمبلغ '
                               '{{مبلغ:الإجمالي.متبقي}} د.ك.', ctx)
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
