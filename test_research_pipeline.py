# اختبارات «البحث ورأي الخبرة» و«النتيجة» بأسلوب الخبير (2026-10-20):
#   python -W ignore -m unittest test_research_pipeline -v
# عقدان في قضية واحدة لا يختلطان؛ مجموع مخالف يُعلَّم؛ اقتباس غير موجود يُحذف؛ رقم غريب يُرفض ويُعاد مرة؛ تحويل العملة
# بسعر الخبير؛ لا رموز P1/D1 ولا أسماء ملفات؛ «لم يقدم رغم طلب الخبرة» بسند المحاضر فقط؛ النتيجة بلا نص المأمورية ولا
# «[يُكتب]» وأرقامها من البحث؛ عدد الفقرات = عدد المحاور والإحالات مطابقة؛ المبلغ بالحروف بالكود؛ ملف prompt.md والاستيراد.
import json
import os
import re
import tempfile
import unittest
from decimal import Decimal

import amounts
import calc
import case_conclusion as cc
import case_documents as cd
import case_model as cm
import case_workspace as cw
import conclusion_pipeline as cp2
import report_docx as rd
import research_pipeline as rp
import report_v3


def setUpModule():
    # هذه الاختبارات للمسار القديم (صياغة النموذج للأقسام كاملة) الباقي في الكود؛ المسار المركَّب له test_report_v3
    report_v3._prev_enabled = report_v3.ENABLED
    report_v3.ENABLED = False


def tearDownModule():
    report_v3.ENABLED = report_v3._prev_enabled

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = dict(json.load(_f), plaintiff='شركة الاتصالات المتنقلة', company='شركة الاتصالات المتنقلة',
                defendants=['خالد سعد المطيري'])

MISSION = ('لبيان طبيعة العلاقة بين طرفي الدعوى والتزامات كل منهما قبل الآخر، وبيان الطرف المخل بالتزاماته، '
           'وبيان المبالغ المسددة والمتبقية وعلى وجه العموم تصفية الحساب بين الطرفين')
POINTS = ['لبيان طبيعة العلاقة بين طرفي الدعوى والتزامات كل منهما قبل الآخر', 'وبيان الطرف المخل بالتزاماته',
          'وبيان المبالغ المسددة والمتبقية وعلى وجه العموم تصفية الحساب بين الطرفين']
TEXTS = {
    'a.pdf': '<!-- صفحة 1 -->\nنموذج طلب خدمة للخط رقم 96662240 المؤرخ 15/5/2021 اشترك بموجبه المدعى عليه مع المدعية '
             'بقيمة 29 د.ك تدفع شهرياً لمدة سنتين.',
    'b.pdf': '<!-- صفحة 1 -->\nنموذج طلب خدمة للخط رقم 90030422 المؤرخ 3/6/2022 اشترك بموجبه المدعى عليه مع المدعية '
             'بقيمة 15 د.ك تدفع شهرياً.',
    's.pdf': ('<!-- صفحة 1 -->\nكشف حساب الخط رقم 96662240 إجمالي المستحق على الخط 609.100 د.ك والمسدد منه 35.000 د.ك '
              'والمتبقي 574.099 د.ك.\n<!-- صفحة 2 -->\nكشف حساب الخط رقم 90030422 إجمالي المستحق على الخط 600.670 د.ك '
              'والمسدد منه 19.000 د.ك والمتبقي 581.670 د.ك.\n<!-- صفحة 3 -->\nوعليه فإن إجمالي المطالبة عن الخطين '
              'مبلغ 1,155.769 د.ك فقط.'),
    'm.pdf': '<!-- صفحة 1 -->\nيعترض المدعى عليه على المطالبة ويدفع بأنه قام بإلغاء الخط الثاني بتاريخ 1/1/2023 ولم '
             'يستعمله بعد ذلك.',
}
FINAL_WORDS = amounts.to_words(Decimal('1155.770'))


def blocks(prompt):
    """{رمز المستند: نصه} من طلب المرحلة 1."""
    out = {}
    for m in re.finditer(r'### \[(D\d+)\][^\n]*\n(.*?)(?=\n### \[D|\Z)', prompt, re.S):
        out[m.group(1)] = m.group(2)
    return out


def code_of(prompt, snippet):
    return next(c for c, t in blocks(prompt).items() if snippet in t)


class FakeAsk:
    """مزوّد وهمي يميّز الطلب بنصه: المرحلة 1 / الصياغة / النتيجة / طلبات المحاضر."""

    def __init__(self, bad_draft_once=False, bad_draft_always=False, concl_bad=False, requests=None):
        self.prompts, self.bad_once, self.bad_always, self.concl_bad = [], bad_draft_once, bad_draft_always, concl_bad
        self.requests = requests

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if 'المرحلة 1' in prompt:
            return json.dumps(self.facts(prompt), ensure_ascii=False)
        if 'اكتب «النتيجة»' in prompt:
            return json.dumps(self.conclusion(prompt), ensure_ascii=False)
        if 'استخرج ما طلبته الخبرة' in prompt:
            return json.dumps({'requests': self.requests or []}, ensure_ascii=False)
        if 'أنت تكتب بأسلوب الخبير' in prompt:
            return self.draft(prompt)
        raise AssertionError('طلب غير متوقع')

    @staticmethod
    def which(prompt):
        head = prompt.split('## القسم:', 1)[1].split('\n', 1)[0] if '## القسم:' in prompt else \
            prompt.split('## موضع القسم', 1)[1].split('## الحقائق', 1)[0]
        if '96662240' in head:
            return 'A'
        if '90030422' in head:
            return 'B'
        return 'OBJ' if 'اعتراضات' in head or 'كل مستندات' in head else 'X'

    def facts(self, prompt):
        w = self.which(prompt)
        if w == 'A':
            ca, cs = code_of(prompt, 'رقم 96662240 المؤرخ'), code_of(prompt, 'كشف حساب الخط رقم 96662240')
            return {'facts': [{'date': '15/5/2021', 'text': 'اشترك المدعى عليه بخدمة الخط', 'doc': ca, 'page': 1,
                               'quote': 'نموذج طلب خدمة للخط رقم 96662240 المؤرخ 15/5/2021'},
                              {'date': '', 'text': 'واقعة مختلقة', 'doc': ca, 'page': 1,
                               'quote': 'هذا اقتباس مختلق لا يرد في أي مستند إطلاقاً'}],
                    'amounts': [{'label': 'إجمالي المستحق', 'value': '609.100', 'kind': 'total', 'doc': cs, 'page': 1,
                                 'quote': 'إجمالي المستحق على الخط 609.100 د.ك'},
                                {'label': 'المسدد', 'value': '35.000', 'kind': 'paid', 'doc': cs, 'page': 1,
                                 'quote': 'والمسدد منه 35.000 د.ك'},
                                {'label': 'المتبقي كما في الكشف', 'value': '574.099', 'kind': 'remaining', 'doc': cs,
                                 'page': 1, 'quote': 'والمتبقي 574.099 د.ك'},
                                {'label': 'إجمالي المطالبة', 'value': '1,155.769', 'kind': 'claim_total', 'doc': cs,
                                 'page': 3, 'quote': 'إجمالي المطالبة عن الخطين مبلغ 1,155.769'}],
                    'formulas': [], 'objections': [], 'debtor': 'المدعى عليه', 'creditor': 'المدعية'}
        if w == 'B':
            cb, cs = code_of(prompt, 'رقم 90030422 المؤرخ'), code_of(prompt, 'كشف حساب الخط رقم 90030422')
            return {'facts': [{'date': '3/6/2022', 'text': 'اشتراك الخط الثاني', 'doc': cb, 'page': 1,
                               'quote': 'نموذج طلب خدمة للخط رقم 90030422 المؤرخ 3/6/2022'}],
                    'amounts': [{'label': 'إجمالي المستحق', 'value': '600.670', 'kind': 'total', 'doc': cs, 'page': 2,
                                 'quote': 'إجمالي المستحق على الخط 600.670 د.ك'},
                                {'label': 'المسدد', 'value': '19.000', 'kind': 'paid', 'doc': cs, 'page': 2,
                                 'quote': 'والمسدد منه 19.000 د.ك'}],
                    'formulas': [], 'objections': [], 'debtor': '', 'creditor': ''}
        cm_ = code_of(prompt, 'يعترض المدعى عليه')
        return {'facts': [], 'amounts': [], 'formulas': [],
                'objections': [{'party': 'المدعى عليه', 'text': 'إلغاء الخط الثاني', 'doc': cm_, 'page': 1,
                                'quote': 'يدفع بأنه قام بإلغاء الخط الثاني بتاريخ 1/1/2023'}]}

    def draft(self, prompt):
        w = self.which(prompt)
        axis = re.search(r'المحور (\S+): «', prompt).group(1)
        if w == 'A' and axis == 'أولاً':
            return ('ترى الخبرة أن العلاقة بين طرفي الدعوى علاقة تعاقدية بموجب نموذج طلب خدمة للخط رقم 96662240 المؤرخ '
                    '15/5/2021 [P1-1] (مرفق بحافظة مستندات المدعية المؤرخة 15/2/2026 مستند 1) والمرفق a.pdf.')
        if w == 'B' and axis == 'أولاً':
            return ('ترى الخبرة أن الخط رقم 90030422 المؤرخ 3/6/2022 علاقة تعاقدية مستقلة D2 '
                    '(مرفق بحافظة مستندات المدعية المؤرخة 15/2/2026 مستند 2).')
        if axis == 'ثانياً':
            return ('ثبت للخبرة أن المدعى عليه لم يسدد كامل المستحق على الخط رقم 96662240. '
                    'طلبت الخبرة من المدعى عليه تقديم ما يفيد السداد إلا أنه لم يقدم رغم منحه الفرصة الكافية.'
                    if w == 'A' else 'ثبت للخبرة أن المدعى عليه لم يسدد كامل المستحق على الخط رقم 90030422.')
        if w == 'OBJ':
            return ('اعتراضات المدعى عليه:\nأفاد المدعى عليه أنه قام بإلغاء الخط الثاني بتاريخ 1/1/2023 '
                    '(مذكرة دفاع المدعى عليه المؤرخة 1/3/2026).\nتوضح الخبرة أن هذا الدفاع مردود وذلك لعدة أسباب وهي كالتالي:\n'
                    '1. ثبت للخبرة من كشف الحساب استمرار المستحق على الخط.\n2. لم يرد في المستندات ما يثبت الإلغاء.')
        if w == 'A':
            if self.bad_always or self.bad_once:
                self.bad_once = False
                return 'ثبت للخبرة أن إجمالي المستحق 609.100 د.ك وتبلغ الفوائد 77.5 د.ك.'
            return ('ثبت للخبرة أن إجمالي المستحق على الخط 609.100 د.ك والمسدد منه 35.000 د.ك.\n\n'
                    '= 609.100 − 35.000 = 574.100 د.ك')
        return 'ثبت للخبرة أن إجمالي المستحق على الخط 600.670 د.ك والمسدد منه 19.000 د.ك.'

    def conclusion(self, prompt):
        if self.concl_bad:
            return {'paragraphs': [{'axis': 'أولاً', 'text': 'أن العلاقة تعاقدية منذ 2019'},
                                   {'axis': 'ثانياً', 'text': 'أن المدعى عليه أخل'},
                                   {'axis': 'ثالثاً', 'text': 'أنه بعد تصفية الحساب الذمة مشغولة بمبلغ 999 د.ك'}]}
        return {'paragraphs': [
            {'axis': 'أولاً', 'text': 'أن العلاقة بين طرفي الدعوى علاقة تعاقدية بموجب نموذجي طلب الخدمة للخطين رقم '
                                     '96662240 ورقم 90030422، كما هو موضح تفصيلياً في بند البحث ورأي الخبرة (ثانياً).'},
            {'axis': 'ثانياً', 'text': 'أن المدعى عليه أخل بالتزاماته التعاقدية بعدم سداد كامل المستحق على الخطين'},
            {'axis': 'ثالثاً', 'text': f'أنه وبعد تصفية الحساب بين الطرفين فإن ذمة المدعى عليه مشغولة لصالح المدعية '
                                      f'بمبلغ وقدره 1,155.770 د.ك ({FINAL_WORDS})'}]}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        d = self.data
        d['subject'] = 'مطالبة شركة اتصالات بمديونية خطين'
        d['subject_type'] = 'اتصالات'
        d['mission'] = {'raw': MISSION, 'confirmed': True, 'next_id': 4,
                        'points': [{'id': f'q{i}', 'n': i, 'text': t} for i, t in enumerate(POINTS, 1)]}
        src = {}
        for name in TEXTS:
            src[name] = os.path.join(self._tmp.name, name)
            open(src[name], 'wb').write(name.encode('utf-8'))
        conv = lambda path: (TEXTS[os.path.basename(path)], TEXTS[os.path.basename(path)].count('صفحة'))   # noqa: E731
        p1 = cd.add_portfolio(d, 'المدعية', '2026-02-15')
        cd.import_batch(self.base, d, p1['id'], [{'src': src['a.pdf'], 'no': 1}, {'src': src['b.pdf'], 'no': 2},
                                                 {'src': src['s.pdf'], 'no': 3}], convert=conv,
                        classify=lambda path: {'type': 'حافظة مستندات', 'confidence': 1.0, 'reason': 'اختبار'})
        p2 = cd.add_portfolio(d, 'المدعى عليه', '2026-03-01')
        cd.import_batch(self.base, d, p2['id'], [{'src': src['m.pdf'], 'no': 1}], convert=conv,
                        classify=lambda path: {'type': 'مذكرة دفاع', 'confidence': 1.0, 'reason': 'اختبار'})
        files = {os.path.basename(x['file']): x for x in d['portfolios'][0]['docs']}
        pa = ['شركة الاتصالات المتنقلة', 'خالد سعد المطيري']

        def con(fname, date, value, line):
            f = files[fname]
            return {'kind': 'عقد بين الطرفين', 'date': date, 'parties': pa, 'scope_of_work': f'خدمة اتصالات للخط {line}',
                    'value': value, 'duration': '', 'summary': f'اشتراك شهري للخط رقم {line}', 'doc': fname,
                    'file': f['file'], 'md': f['md'], 'page': 1, 'checks': {'date': True, 'value': True, 'page': True},
                    'verified': True, 'scope': 'بين طرفي الدعوى', 'between_litigants': True}
        d['contracts'] = {'items': [con('a.pdf', '15/5/2021', '29 د.ك', '96662240'),
                                    con('b.pdf', '3/6/2022', '15 د.ك', '90030422')], 'litigants': {}, 'claim': ''}
        d['readiness'] = {'items': [{'id': f'q{i}', 'n': i, 'point_text': POINTS[i - 1], 'state': 'ready', 'score': 100,
                                     'requirements': [], 'missing': []} for i in (1, 2, 3)]}
        for k in ('running', 'done', 'reviewed'):
            cm.set_step(d, 'mission', k)
        d['steps']['documents']['waived'] = True
        cm.refresh_blocked(d)
        cw.write_case_json(self.base, d)
        rp.MINUTE_TEXTS = lambda recs: {}

    def tearDown(self):
        rp.MINUTE_TEXTS = None
        self._tmp.cleanup()

    def run_all(self, ask=None):
        ask = ask or FakeAsk()
        st = rp.run(self.base, self.data, ask)
        return ask, st

    def sec(self, axis_ord, line=None, kind=None):
        for a in rp.state(self.data)['axes']:
            if a['ordinal'] != axis_ord:
                continue
            for s in a['sections']:
                if kind and s['kind'] == kind:
                    return s
                if line and line in (s.get('contract_title') or ''):
                    return s
        raise AssertionError('القسم غير موجود')


class PlanTests(Base):
    def test_axes_from_mission_points_with_expert_headings(self):
        r = rp.build_plan(self.base, self.data)
        self.assertEqual([a['ordinal'] for a in r['axes']], ['أولاً', 'ثانياً', 'ثالثاً'])
        self.assertEqual([a['kind'] for a in r['axes']], [rp.K_REL, rp.K_BREACH, rp.K_CALC])
        self.assertEqual(rp.heading(r['axes'][0]), f'أولاً: {POINTS[0]}:')
        kinds = [[s['kind'] for s in a['sections']] for a in r['axes']]
        self.assertEqual(kinds, [['contract', 'contract'], ['contract', 'contract'],
                                 ['contract', 'contract', 'total', 'objections']])
        titles = [s['contract_title'] for s in r['axes'][0]['sections']]
        self.assertEqual(titles, ['العقد رقم (96662240) المؤرخ 15/5/2021 بين المدعية والمدعى عليه',
                                  'العقد رقم (90030422) المؤرخ 3/6/2022 بين المدعية والمدعى عليه'])

    def test_single_contract_is_one_section_without_artificial_split(self):
        self.data['contracts']['items'] = self.data['contracts']['items'][:1]
        r = rp.build_plan(self.base, self.data)
        self.assertEqual([len(a['sections']) for a in r['axes']], [1, 1, 2])          # + الاعتراضات في آخر محور
        self.assertEqual(r['axes'][0]['sections'][0]['title'], '')                   # بلا عنوان عقد

    def test_classify_point_examples_from_reports(self):
        self.assertEqual(rp.classify_point('لبيان طبيعة العلاقة بين أطراف الدعوى والعقد المبرم بينهم'), rp.K_REL)
        self.assertEqual(rp.classify_point('وتحديد كميات البكتيريا التي تم استلامها من المدعية وقيمتها'), rp.K_BREACH)
        self.assertEqual(rp.classify_point('وحساب المبالغ المستحقة للمدعية طبقاً لشروط العقد'), rp.K_CALC)
        self.assertEqual(rp.classify_point('وبيان الأضرار إن وجدت'), rp.K_CALC)
        self.assertEqual(rp.classify_point('وبالجملة بحث وتحقيق أوجه دفاع الخصوم'), rp.K_DEF)


class TwoContractsTests(Base):
    def test_contracts_never_mix_in_prompts(self):
        ask, _st = self.run_all()
        facts = [p for p in ask.prompts if 'المرحلة 1' in p]
        a = [p for p in facts if FakeAsk.which(p) == 'A']
        b = [p for p in facts if FakeAsk.which(p) == 'B']
        self.assertTrue(a and b)
        for p in a:
            docs = '\n'.join(blocks(p).values())
            self.assertIn('609.100', docs)
            self.assertNotIn('90030422', docs)
            self.assertNotIn('600.670', docs)
            self.assertIn('1,155.769', docs)                       # الصفحة العامة (بلا معرّف عقد) مشتركة
        for p in b:
            docs = '\n'.join(blocks(p).values())
            self.assertIn('600.670', docs)
            self.assertNotIn('96662240', docs)
            self.assertNotIn('609.100', docs)
        drafts = [p for p in ask.prompts if 'أنت تكتب بأسلوب الخبير' in p and FakeAsk.which(p) == 'A']
        self.assertTrue(all('600.670' not in p for p in drafts))

    def test_fabricated_quote_removed_and_marked_red(self):
        self.run_all()
        s = self.sec('أولاً', '96662240')
        self.assertEqual(len(s['facts']['facts']), 1)
        self.assertNotIn('مختلق', json.dumps(s['facts'], ensure_ascii=False))
        self.assertTrue(any(n['type'] == rp.N_REMOVED and 'غير موجود حرفياً' in n['text'] for n in s['notes']))

    def test_code_computes_and_flags_every_fils(self):
        self.run_all()
        s = self.sec('ثالثاً', '96662240')
        self.assertIn('المتبقي = 609.100 − 35.000 = 574.100 د.ك', s['calc']['steps'])
        self.assertTrue(any(n['type'] == rp.N_DIFF and '574.100 لا 574.099' in n['text'] for n in s['notes']))
        tot = self.sec('ثالثاً', kind='total')
        self.assertIn('= 574.100 + 581.670 = 1,155.770 د.ك', tot['total_text'])
        self.assertTrue(any(n['type'] == rp.N_DIFF and '1,155.770 لا 1,155.769' in n['text'] for n in tot['notes']))
        fin = rp.case_final(self.data)
        self.assertEqual((fin['amount'], fin['debtor'], fin['creditor']), ('1155.770', 'المدعى عليه', 'المدعية'))
        self.assertEqual(fin['words'], FINAL_WORDS)
        self.assertEqual(amounts.words_to_decimal(fin['words']), Decimal('1155.770'))

    def test_no_internal_codes_or_filenames_in_output(self):
        self.run_all()
        rp.merge_all(self.base, self.data)
        txt = rp.research_text(self.base, self.data)
        self.assertNotRegex(txt, r'P\d+-\d+|\bD\d+\b|\.pdf')
        self.assertIn('(مرفق بحافظة مستندات المدعية المؤرخة 15/2/2026 مستند 1)', txt)

    def test_not_submitted_phrase_removed_without_minutes_proof(self):
        self.run_all()
        s = self.sec('ثانياً', '96662240')
        txt = rp.section_text(self.base, s)
        self.assertNotIn('لم يقدم', txt)
        self.assertIn('لم يسدد كامل المستحق', txt)
        self.assertTrue(any(n['type'] == rp.N_MISSING and 'لم يقدم' in n['text'] for n in s['notes']))

    def test_foreign_number_rejected_then_retried_once(self):
        ask, _ = self.run_all(FakeAsk(bad_draft_once=True))
        s = self.sec('ثالثاً', '96662240')
        self.assertEqual(s['state'], rp.S_DRAFTED)
        txt = rp.section_text(self.base, s)
        self.assertNotIn('77.5', txt)
        retry = [p for p in ask.prompts if 'رُفضت صياغتك السابقة' in p]
        self.assertEqual(len(retry), 1)
        self.assertIn('77.5', retry[0])
        self.assertIn('المتبقي على العقد رقم (96662240)', txt)        # سطر الختام بالأرقام والحروف يضمنه الكود
        self.assertIn(amounts.to_words(Decimal('574.100')), txt)

    def test_foreign_number_twice_is_refused_not_written(self):
        self.run_all(FakeAsk(bad_draft_always=True))
        s = self.sec('ثالثاً', '96662240')
        self.assertEqual(s['state'], rp.S_FAILED)
        self.assertFalse(s.get('file'))
        self.assertIn('77.5', s['message'])

    def test_objections_section_with_numbered_reasons(self):
        self.run_all()
        s = self.sec('ثالثاً', kind='objections')
        txt = rp.section_text(self.base, s)
        self.assertIn('اعتراضات المدعى عليه:', txt)
        self.assertIn('1. ثبت للخبرة', txt)
        self.assertIn('(مذكرة دفاع المدعى عليه المؤرخة 1/3/2026)', txt)

    def test_preview_then_merge_and_step_states(self):
        _ask, st = self.run_all()
        self.assertEqual(st, 'needs_input')                       # مسودات تنتظر المعاينة والدمج
        self.assertEqual(rp.research_text(self.base, self.data), '')
        n = rp.merge_all(self.base, self.data)
        self.assertEqual(n, 8)                                     # 2 + 2 + (2 + الإجمالي + الاعتراضات)
        self.assertEqual(cm.state(self.data, 'research'), 'done')
        txt = rp.research_text(self.base, self.data)
        self.assertTrue(txt.startswith(f'أولاً: {POINTS[0]}:'))
        self.assertIn('العقد رقم (90030422) المؤرخ 3/6/2022 بين المدعية والمدعى عليه:', txt)
        with open(os.path.join(self.base, rp.TEXT_REL), encoding='utf-8') as f:
            self.assertEqual(f.read().strip(), txt)
        with open(os.path.join(self.base, rp.NOTES_REL), encoding='utf-8') as f:
            notes = f.read()
        self.assertIn('## فرق أرقام', notes)
        self.assertNotIn('فرق أرقام', txt)                        # الملاحظات الحمراء منفصلة عن النص

    def test_blocked_axis_not_written_without_ready_documents(self):
        self.data['readiness']['items'][2] = {'id': 'q3', 'n': 3, 'point_text': POINTS[2], 'state': 'missing', 'score': 0,
                                              'requirements': [], 'missing': ['كشف حساب الخطين']}
        ask, _ = self.run_all()
        s = self.sec('ثالثاً', '96662240')
        self.assertEqual(s['state'], rp.S_BLOCKED)
        self.assertIn('كشف حساب الخطين', s['message'])
        self.assertFalse(any('أنت تكتب بأسلوب الخبير' in p and 'المحور ثالثاً: «' in p for p in ask.prompts))
        self.assertEqual(sum('المرحلة 1' in p for p in ask.prompts), 2)      # حقائق كل عقد مرة واحدة لكل محاوره
        self.assertIsNone(rp.case_final(self.data))

    def test_rewrite_axis_returns_merged_to_preview(self):
        self.run_all()
        rp.merge_all(self.base, self.data)
        key = rp.state(self.data)['axes'][0]['key']
        rp.rewrite_axis(self.base, self.data, key, ask=FakeAsk())
        self.assertEqual({s['state'] for s in rp.state(self.data)['axes'][0]['sections']}, {rp.S_DRAFTED})
        self.assertEqual({s['state'] for s in rp.state(self.data)['axes'][1]['sections']}, {rp.S_MERGED})


class MinutesProofTests(Base):
    MINUTE = ('محضر أعمال الخبرة رقم 2 بتاريخ 10/4/2026 حضر وكيل المدعية ووكيل المدعى عليه وطلبت الخبرة من المدعى عليه '
              'تقديم ما يفيد سداد المستحق على الخط وأجلت للجلسة القادمة لتقديم ذلك.')
    MINUTE2 = ('محضر أعمال الخبرة رقم 3 بتاريخ 24/4/2026 حضر وكيل المدعية وتخلف المدعى عليه ولم يقدم المدعى عليه ما يفيد '
               'السداد رغم طلب الخبرة.')

    def setUp(self):
        super().setUp()
        self.data['sessions']['minutes'] = [{'file': 'm2.docx', 'name': '2', 'no': 2, 'date': '10/04/2026'},
                                            {'file': 'm3.docx', 'name': '3', 'no': 3, 'date': '24/04/2026'}]
        rp.MINUTE_TEXTS = lambda recs: {'m2.docx': [self.MINUTE], 'm3.docx': [self.MINUTE2]}

    def test_not_submitted_phrase_kept_with_minutes_proof(self):
        reqs = [{'minute': 'M1', 'to': 'المدعى عليه', 'what': 'تقديم ما يفيد سداد المستحق على الخط',
                 'evidence': 'وطلبت الخبرة من المدعى عليه تقديم ما يفيد سداد المستحق على الخط', 'delivered': False,
                 'proof': 'ولم يقدم المدعى عليه ما يفيد السداد رغم طلب الخبرة'}]
        ask, _ = self.run_all(FakeAsk(requests=reqs))
        self.assertTrue(rp.proven_requests(self.data))
        txt = rp.section_text(self.base, self.sec('ثانياً', '96662240'))
        self.assertIn('إلا أنه لم يقدم رغم منحه الفرصة الكافية', txt)
        draft = next(p for p in ask.prompts if 'أنت تكتب بأسلوب الخبير' in p)
        self.assertIn('(محضر أعمال الخبرة المؤرخ 10/4/2026)', draft)

    def test_request_without_literal_evidence_is_not_proof(self):
        reqs = [{'minute': 'M1', 'to': 'المدعى عليه', 'what': 'تقديم كشف', 'evidence': 'طلبت الخبرة كشفاً مختلقاً لا يرد',
                 'delivered': False, 'proof': ''}]
        self.run_all(FakeAsk(requests=reqs))
        self.assertFalse(rp.proven_requests(self.data))
        self.assertNotIn('لم يقدم', rp.section_text(self.base, self.sec('ثانياً', '96662240')))


class ConclusionTests(Base):
    def setUp(self):
        super().setUp()
        self.run_all()
        rp.merge_all(self.base, self.data)

    def test_paragraph_per_axis_with_matching_references(self):
        st = cc.run_conclusion(self.base, self.data, ask=FakeAsk())
        self.assertEqual(st, 'done')
        rec = self.data['conclusion']['v2']
        self.assertEqual(len(rec['paragraphs']), len(rp.state(self.data)['axes']))
        self.assertTrue(cc.verify_counts(self.data))
        for p, a in zip(rec['paragraphs'], rp.state(self.data)['axes']):
            self.assertTrue(p['text'].startswith('أن'))
            self.assertTrue(p['text'].endswith(f"كما هو موضح تفصيلياً في بند البحث ورأي الخبرة ({a['ordinal']})."))
            self.assertEqual(p['text'].count('كما هو موضح'), 1)        # الإحالة الخاطئة «(ثانياً)» صُحّحت
        self.assertIn('ذمة المدعى عليه مشغولة لصالح المدعية بمبلغ وقدره 1,155.770 د.ك', rec['paragraphs'][2]['text'])
        with open(os.path.join(self.base, cp2.REL), encoding='utf-8') as f:
            md = f.read()
        self.assertIn(cp2.OPENING, md)
        self.assertIn(cp2.CLOSING, md)

    def test_conclusion_has_no_mission_text_or_todo(self):
        cc.run_conclusion(self.base, self.data, ask=FakeAsk())
        text = cp2.text_of(self.data['conclusion']['v2'])
        self.assertNotIn('[يُكتب]', text)
        for p in POINTS:
            self.assertNotIn(p, text)
        path, _w = rd.build_report(self.base, self.data, {})
        from docx import Document
        doc = '\n'.join(par.text for par in Document(path).paragraphs)
        concl = doc.split('النتيجة:', 1)[1].split('المرفقات:', 1)[0]
        self.assertNotIn('[يُكتب]', concl)
        self.assertNotIn(POINTS[2], concl)
        self.assertIn('1,155.770', concl)

    def test_conclusion_numbers_must_match_research(self):
        with self.assertRaises(cm.StepError) as e:
            cc.run_conclusion(self.base, self.data, ask=FakeAsk(concl_bad=True))
        self.assertIn('2019', str(e.exception))                 # رقم غريب في فقرة غير مالية
        self.assertNotIn('999', str(e.exception))               # الفقرة المالية الخاطئة استُبدلت بجملة الكود
        self.assertIsNone((self.data.get('conclusion') or {}).get('v2'))

    def test_financial_paragraph_forced_from_code(self):
        class Wrong(FakeAsk):
            def conclusion(self, prompt):
                d = super().conclusion(prompt)
                d['paragraphs'][2]['text'] = 'أن الذمة مشغولة لصالح المدعية'
                return d
        cc.run_conclusion(self.base, self.data, ask=Wrong())
        p = self.data['conclusion']['v2']['paragraphs'][2]
        self.assertIn(f'1,155.770 د.ك ({FINAL_WORDS})', p['text'])
        self.assertTrue(p.get('financial_by_code'))

    def test_incomplete_research_writes_complete_axes_only(self):
        a3 = rp.state(self.data)['axes'][2]
        a3['sections'][0]['state'] = rp.S_DRAFTED                 # لم يُدمج بعد
        rp.finish_state(self.base, self.data)

        class Two(FakeAsk):
            def conclusion(self, prompt):
                d = super().conclusion(prompt)
                d['paragraphs'] = d['paragraphs'][:2]
                return d
        cc.run_conclusion(self.base, self.data, ask=Two(), force=True)
        rec = self.data['conclusion']['v2']
        self.assertEqual(len(rec['paragraphs']), 2)
        self.assertTrue(any('ثالثاً' in n for n in cp2.notes(self.base, self.data)))

    def test_manual_research_edit_marks_conclusion_stale(self):
        cc.run_conclusion(self.base, self.data, ask=FakeAsk())
        s = rp.state(self.data)['axes'][1]['sections'][0]
        rp.set_section_text(self.base, self.data, s['key'], rp.section_text(self.base, s) + ' وثبت ذلك للخبرة.')
        self.assertTrue(self.data['conclusion']['v2']['stale'])
        self.assertTrue(any('ستُحدَّث تلقائياً' in n for n in cp2.notes(self.base, self.data)))   # غير معدَّلة ← تلقائية
        self.assertTrue(cp2.needs_regen(self.base, self.data))


class CurrencyAndCalcTests(unittest.TestCase):
    def test_fx_conversion_at_expert_rate(self):
        data = {'research2': {'decisions': {'fx': {'USD': {'rate': '0.305450', 'date': '31/10/2025',
                                                           'basis': 'تاريخ انتهاء العقد بين المدعى عليهما'}}}}}
        ver = {'facts': [], 'formulas': [], 'objections': [], 'debtor': '', 'creditor': '',
               'amounts': [{'label': 'المبالغ المستحقة', 'dec': '750000', 'value': '750,000', 'cur': 'USD', 'kind': 'total',
                            'quote': '', 'cite': ''},
                           {'label': 'دفعة', 'dec': '45000', 'value': '45,000', 'cur': 'USD', 'kind': 'paid', 'quote': '', 'cite': ''},
                           {'label': 'دفعة', 'dec': '19089', 'value': '19,089', 'cur': 'USD', 'kind': 'paid', 'quote': '', 'cite': ''}]}
        labels = {'plaintiff': 'المدعية', 'defendants': ['المدعى عليها الأولى', 'المدعى عليها الثانية']}
        c, notes = rp.compute({'kind': 'contract', 'contract_title': 'عقد الشراكة'}, ver, data, labels, rp.K_CALC)
        self.assertIn('القيمة بالدينار الكويتي = 685,911 دولار أمريكي × 0.305450 = 209,511.515 د.ك', c['steps'])
        self.assertEqual(c['final']['amount'], '209511.515')
        self.assertIn('مائتان وتسعة آلاف وخمسمائة وأحد عشر ديناراً وخمسمائة وخمسة عشر فلساً كويتي فقط لا غير',
                      c['final']['line'])
        self.assertTrue(any(k == rp.N_DECISION and '0.305450' in t and '31/10/2025' in t for k, t in notes))

    def test_missing_fx_is_a_red_note_not_a_number(self):
        ver = {'facts': [], 'formulas': [], 'objections': [],
               'amounts': [{'label': 'المستحق', 'dec': '1000', 'value': '1,000', 'cur': 'USD', 'kind': 'total', 'quote': '', 'cite': ''}]}
        c, notes = rp.compute({'kind': 'contract'}, ver, {'research2': {}}, {'plaintiff': 'المدعية',
                                                                          'defendants': ['المدعى عليه']}, rp.K_CALC)
        self.assertIsNone(c['final'])
        self.assertTrue(any(k == rp.N_MISSING and 'سعر صرف' in t for k, t in notes))

    def test_formula_computed_by_code_from_verified_numbers(self):
        docs = [({'code': 'D1', 'cite': '(العقد)', 'kind': 'حافظة مستندات', 'face': [], 'multi': False},
                 [(1, 'نصت المادة 3 على أن كل 100 لتر تعالج 50,000 طن من التربة وتم توريد 500 لتر')])]
        raw = {'facts': [{'date': '', 'text': '', 'doc': 'D1', 'page': 1,
                          'quote': 'كل 100 لتر تعالج 50,000 طن من التربة وتم توريد 500 لتر'}],
               'amounts': [], 'formulas': [{'label': 'كمية التربة المعالجة', 'expr': '(50000 * 500) / 100', 'unit': 'طن',
                                            'basis': 'المادة (3) من العقد'},
                                           {'label': 'مختلقة', 'expr': '(50000 * 700) / 100', 'unit': 'طن'}]}
        ver, removed = rp.verify_facts(json.dumps(raw, ensure_ascii=False), docs)
        self.assertEqual(len(ver['formulas']), 1)
        self.assertEqual(ver['formulas'][0]['step']['line'], 'كمية التربة المعالجة = (50,000 × 500) / 100 = 250,000 طن')
        self.assertTrue(any('700' in r for r in removed))

    def test_amount_and_date_must_be_literal(self):
        docs = [({'code': 'D1', 'cite': '(كشف)', 'kind': 'حافظة مستندات', 'face': [], 'multi': False},
                 [(1, 'سدد المدعى عليه بتاريخ 4/12/2024 مبلغ 45,000 دولار أمريكي')])]
        raw = {'facts': [{'date': '5/12/2024', 'text': '', 'doc': 'D1', 'page': 1,
                          'quote': 'سدد المدعى عليه بتاريخ 4/12/2024 مبلغ'}],
               'amounts': [{'value': '46,000', 'kind': 'paid', 'doc': 'D1', 'page': 1,
                            'quote': 'سدد المدعى عليه بتاريخ 4/12/2024 مبلغ 45,000 دولار'},
                           {'value': '45,000', 'currency': 'دولار', 'kind': 'paid', 'doc': 'D1', 'page': 1,
                            'quote': 'مبلغ 45,000 دولار أمريكي'}]}
        ver, removed = rp.verify_facts(json.dumps(raw, ensure_ascii=False), docs)
        self.assertEqual(ver['facts'], [])
        self.assertEqual([a['value'] for a in ver['amounts']], ['45,000'])
        self.assertEqual(ver['amounts'][0]['cur'], 'USD')
        self.assertEqual(len(removed), 2)

    def test_words_roundtrip_and_examples(self):
        self.assertEqual(amounts.to_words(Decimal('75600')), 'خمسة وسبعون ألف وستمائة دينار كويتي فقط لا غير')
        self.assertEqual(amounts.to_words(Decimal('4679')), 'أربعة آلاف وستمائة وتسعة وسبعون ديناراً كويتي فقط لا غير')
        for v in ('0.001', '1', '2', '13.045', '200000', '1155.770', '1470127.400', '209511.515'):
            self.assertEqual(amounts.words_to_decimal(amounts.to_words(Decimal(v))), Decimal(v), v)

    def test_calc_examples_from_request(self):
        self.assertEqual(calc.subtract_chain('', '609.100', ['35.000']).line(), '= 609.100 − 35.000 = 574.100 د.ك')
        st, diff, txt = calc.sum_check('المجموع', ['574.100', '581.670'], '1,155.769')
        self.assertEqual((calc.fmt(st.value), diff), ('1,155.770', Decimal('0.001')))
        self.assertIn('1,155.770 لا 1,155.769', txt)
        with self.assertRaises(calc.CalcError):
            calc.evaluate('__import__("os")')

    def test_check_text_strips_codes_and_forbidden_phrases(self):
        data = {'research2': {}, 'mission': {'raw': MISSION}}
        sec = {'kind': 'general', 'facts': {'facts': [{'quote': 'بتاريخ 1/2/2024', 'date': '1/2/2024', 'cite': '(مستند)'}]},
               'calc': None, 'notes': []}
        t, problems, notes = rp.check_text('- ثبت للخبرة بتاريخ 1/2/2024 [P1-2] D3 الملف عقد.pdf.\n'
                                           'يتعذر على الخبرة بيان الباقي.\n[يُكتب]', data, sec, MISSION)
        self.assertEqual(problems, [])
        self.assertEqual(t, 'ثبت للخبرة بتاريخ 1/2/2024 الملف.')
        self.assertEqual(len([n for n in notes if n[0] == rp.N_MISSING]), 2)


class DeliveryTests(Base):
    def test_prompt_file_then_import_reply(self):
        ask = FakeAsk()
        path = rp.export_prompt(self.base, self.data, ask=ask)
        with open(path, encoding='utf-8') as f:
            md = f.read()
        self.assertIn('التزم بالأرقام المعطاة حرفياً', md)
        self.assertIn('## قواعد النتيجة', md)
        self.assertIn('= 574.100 + 581.670 = 1,155.770 د.ك', md)
        self.assertEqual(md.count('===القسم '), 9)                 # 8 أقسام + مثال الصيغة
        self.assertFalse(any('أنت تكتب بأسلوب الخبير' in p for p in ask.prompts))      # لا صياغة بالمزوّد في وضع الملف
        keys = [s['key'] for _a, s in rp.all_sections(self.data)]
        a_calc = self.sec('ثالثاً', '96662240')['key']
        reply = '\n'.join(f"{rp.MARK.format(key=k)}\nثبت للخبرة ما يلي وفق المستندات." for k in keys if k != a_calc)
        reply += f"\n{rp.MARK.format(key=a_calc)}\nثبت للخبرة أن المستحق 609.100 د.ك والفائدة 12.5 د.ك.\n"
        res = rp.import_reply(self.base, self.data, reply, source='file')
        self.assertEqual(len(res['accepted']), 7)
        self.assertEqual([k for k, _w in res['rejected']], [a_calc])
        self.assertIn('12.5', res['rejected'][0][1])
        self.assertEqual(self.sec('ثالثاً', '96662240')['state'], rp.S_FACTS)

    def test_split_reply_markers(self):
        secs, concl = rp.split_reply('===القسم A1:x===\nنص أ\n\n=== القسم A2:y ===\nنص ب\n===النتيجة===\nأن …')
        self.assertEqual(secs, {'A1:x': 'نص أ', 'A2:y': 'نص ب'})
        self.assertEqual(concl, 'أن …')


class PageTests(Base):
    """صفحة «كتابة البحث ورأي الخبرة»: الخيارات الثلاثة، شريط تقدم لكل محور/عقد، المعاينة والدمج، إعادة صياغة النتيجة."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        import qt_case_page as qp
        self.qp = qp
        self._flags = {k: getattr(qp.CasePageDialog, k) for k in
                       ('AUTO_SYNC', 'AUTO_ASK_TYPE', 'AUTO_PROCEDURES', 'AUTO_READINESS', 'AUTO_RESUME',
                        'OPEN_EXTERNAL', 'AUTO_CONCLUSION')}
        for k in self._flags:
            setattr(qp.CasePageDialog, k, False)

    def tearDown(self):
        for dlg in getattr(self, '_dlgs', []):     # عمل خلفي متأخر (النتيجة التلقائية) لا يصل لمجلد حُذف
            self.wait(dlg)
            dlg._done.disconnect()
            dlg.deleteLater()
        for k, v in self._flags.items():
            setattr(self.qp.CasePageDialog, k, v)
        super().tearDown()

    def page(self, ask=None):
        dlg = self.qp.CasePageDialog(self.base, cw.read_case_json(self.base), ask=ask or FakeAsk())
        dlg.open_step('research')
        self._dlgs = getattr(self, '_dlgs', []) + [dlg]
        return dlg

    def wait(self, dlg):
        import time
        for _ in range(500):
            self.app.processEvents()
            if not dlg._busy:
                break
            time.sleep(0.02)
        for _ in range(5):
            self.app.processEvents()

    def buttons(self, dlg):
        from PyQt6.QtWidgets import QPushButton
        return {b.text(): b for b in dlg.card.findChildren(QPushButton)}

    def test_one_button_writes_merges_and_concludes(self):
        """زر واحد «اكتب البحث» (ثم «إعادة الكتابة»): البحث كاملاً ثم الدمج التلقائي ثم النتيجة؛ لا أزرار دمج/معاينة/اعتماد."""
        from PyQt6.QtWidgets import QRadioButton
        dlg = self.page()
        radios = [r.text() for r in dlg.card.findChildren(QRadioButton)]
        self.assertEqual(radios, ['جيميناي', 'عبر المتصفح'])
        btns = self.buttons(dlg)
        for t in ('أعد صياغة هذا المحور', 'معاينة', 'دمج في البحث', 'دمج الكل', 'أعد صياغة النتيجة', 'اعتماد رأيي',
                  'كتابة البحث ورأي الخبرة', 'اكتب رغم النقص', 'إنشاء prompt.md'):
            self.assertNotIn(t, btns)
        btns['اكتب البحث'].click()
        self.wait(dlg)
        self.assertEqual({s['state'] for _a, s in rp.all_sections(dlg.data)}, {rp.S_MERGED})    # دُمج تلقائياً
        labels = ' '.join(__import__('qt_bidi').strip_isolates(l.text()) for l in dlg.card.findChildren(self.qp.QLabel))
        self.assertIn('أولاً: لبيان طبيعة العلاقة', labels)
        self.assertNotIn('كل مستندات المحور', labels)
        self.assertIn('فرق أرقام', labels)
        self.assertIn('ترى الخبرة أن العلاقة', dlg.editor.toPlainText())
        self.assertIn('إعادة الكتابة', self.buttons(dlg))

    def test_rewrite_redoes_whole_research_then_conclusion(self):
        from unittest import mock
        import report_v3
        dlg = self.page()
        with mock.patch.object(report_v3, 'run', return_value='done') as run,                 mock.patch.object(rp, 'merge_all', return_value=0) as merge,                 mock.patch.object(report_v3, 'store_conclusion') as concl,                 mock.patch.object(report_v3, 'ENABLED', True):
            report_v3.write_full(dlg.base, dlg.data, ask=FakeAsk())
        self.assertTrue(run.call_args.kwargs['force'])          # البحث كله من جديد، لا النتيجة وحدها
        merge.assert_called_once()
        self.assertTrue(concl.call_args.kwargs['force'])

    def test_rewrite_conclusion_asks_before_replacing_manual_text(self):
        from unittest import mock
        from PyQt6.QtWidgets import QMessageBox
        dlg = self.page()
        dlg._write_ready()
        self.wait(dlg)
        self.wait(dlg)                                   # والنتيجة التلقائية بعده (AutoConclusionTests)
        cc.run_conclusion(dlg.base, dlg.data, ask=FakeAsk())
        cp2.set_text(dlg.base, dlg.data, cp2.text_of(dlg.data['conclusion']['v2']) + '\nأن فقرة كتبها الخبير بيده')
        self.assertTrue(dlg.data['conclusion']['v2']['edited'])
        with mock.patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as q, \
                mock.patch('case_conclusion.run_conclusion') as run:
            dlg._rewrite('conclusion')
        q.assert_called_once()
        run.assert_not_called()
        self.assertIn('فقرة كتبها الخبير', cp2.text_of(dlg.data['conclusion']['v2']))

    def test_browser_mode_buttons(self):
        dlg = self.page()
        dlg._set_delivery('file')                           # «ملف prompt.md» أُزيل ← جيميناي
        self.app.processEvents()
        self.assertNotIn('إنشاء prompt.md', self.buttons(dlg))
        dlg._set_delivery('browser')
        self.app.processEvents()
        btns = self.buttons(dlg)
        self.assertIn('اكتب عبر المتصفح', btns)
        self.assertIn('لصق الرد', btns)
        self.app.processEvents()
        live = [b.text() for b in dlg.card.findChildren(self.qp.QPushButton) if not b.isHidden()
                and b.parent() is not None and b.text() == 'أعد الكتابة' and b.isVisibleTo(dlg.card)]
        self.assertEqual(live, [])                          # الطريقة تُختار أعلاه؛ لا زر مكرر


class CleanerTests(unittest.TestCase):
    """الرموز الداخلية والصفحات بكل صيغها لا تصل لأي ناتج، من أي مسار."""
    FORMS = ['ثبت العقد [P1-2 ص6، ص15] وسدد.', 'ثبت العقد [P1-2 ص6] وسدد.', 'ثبت العقد [P1-2] وسدد.',
             'ثبت العقد (P1-2 ص6، ص15) وسدد.', 'ثبت العقد P1-2 وسدد.', 'ثبت العقد [P1-2; P2-1 ص3] وسدد.',
             'ثبت العقد [D3 ص2] وسدد.', 'ثبت العقد [M2] وسدد.', 'ثبت العقد ص15 وسدد.', 'ثبت العقد ص 6-8 وسدد.',
             'ثبت العقد (ص 6) وسدد.', 'ثبت العقد في الصفحة 3 وسدد.', 'ثبت العقد [P1-2 ص6، ص15، P1-3] وسدد.']

    def test_all_forms_removed(self):
        for t in self.FORMS:
            out = rp.clean_display(t)
            self.assertEqual(out, 'ثبت العقد وسدد.', (t, out))
            self.assertNotRegex(out, r'P\d|ص\s*\d|\bD\d|\bM\d|صفحة')

    def test_check_text_and_import_and_legacy_paths_use_same_cleaner(self):
        sec = {'kind': 'general', 'facts': {'facts': []}, 'calc': None, 'notes': []}
        for t in self.FORMS:
            out, problems, _n = rp.check_text(t, {'research2': {}}, sec, '')
            self.assertEqual((out, problems), ('ثبت العقد وسدد.', []))
        import case_research
        body = case_research.split_response('نص البند [P1-2 ص6، ص15] مدعوم.\n' + case_research.SUMMARY_MARK + '\nخلاصة ص15')
        self.assertNotRegex(rp.clean_display(body[0]) + rp.strip_internal(body[1]), r'P1|ص\s*\d')

    def test_legacy_item_text_cleaned_when_written(self):
        import case_research
        raw = case_research.split_response('نص [P1-2 ص6، ص15] بند.\n' + case_research.SUMMARY_MARK + '\nخ')[0]
        self.assertEqual(rp.clean_display(raw), 'نص بند.')

    def test_duplicate_bullet_glyphs_collapsed(self):
        self.assertEqual(rp.fix_glyphs('· · بند\n- • آخر\n·· ثالث'), '- بند\n- آخر\n- ثالث')
        import report_docx as rdx
        self.assertEqual(rdx.md_blocks('- · بند أول\n• · ثاني'), [('bullets', ['بند أول', 'ثاني'])])

    def test_check_text_flattens_bullets(self):
        sec = {'kind': 'general', 'facts': {'facts': []}, 'calc': None, 'notes': []}
        out, _p, _n = rp.check_text('· · أولاً ثبت كذا.\n  - • فرع ثبت كذا.', {'research2': {}}, sec, '')
        self.assertNotIn('·', out)
        self.assertNotIn('•', out)
        self.assertFalse(any(l.lstrip().startswith('-') for l in out.split('\n')))


class ReferenceTests(unittest.TestCase):
    R1 = '(مرفق بحافظة مستندات المدعية المؤرخة 15/10/2025 مستند 1)'
    R2 = '(مرفق بحافظة مستندات المدعية المؤرخة 15/10/2025 مستند 2)'

    def test_one_reference_per_document_per_paragraph(self):
        t = (f'ثبت العقد {self.R1} وتاريخه كذا {self.R1} وسدد {self.R2} ثم كذا {self.R1} وانتهى.\n'
             f'فقرة ثانية {self.R1} تعيد ذكره.')
        out = rp.limit_refs(t)
        first, second = out.split('\n')
        self.assertEqual((first.count(self.R1), first.count(self.R2)), (1, 1))
        self.assertEqual(second.count(self.R1), 1)                # الفقرة الجديدة تبدأ من جديد
        self.assertNotIn(' ،', out)

    def test_reference_never_has_page_number(self):
        out = rp.clean_display('ثبت العقد (مرفق بحافظة مستندات المدعية المؤرخة 15/10/2025 مستند 1 ص6) وسدد.')
        self.assertNotIn('ص6', out)

    def test_secondary_facts_have_no_reference_in_material(self):
        f_key = {'date': '', 'text': '', 'quote': 'عقد مؤرخ 1/1/2020 قيمته', 'cite': self.R1, 'key': True}
        f_sec = {'date': '', 'text': '', 'quote': 'واقعة ثانوية بسيطة جداً هنا', 'cite': self.R2, 'key': False}
        self.assertIn(self.R1, rp._fact_line(f_key))
        self.assertNotIn(self.R2, rp._fact_line(f_sec))
        self.assertIn('بلا مرجع', rp._fact_line(f_sec))

    def test_draft_output_has_one_ref_per_doc_and_no_pages(self):
        raw = (f'ترى الخبرة أن الخط رقم 96662240 المؤرخ 15/5/2021 {self.R1} ثابت {self.R1} '
               f'[P1-2 ص6، ص15] وأيضاً {self.R1}.')
        sec = {'kind': 'general', 'facts': {'facts': [{'quote': '96662240 15/5/2021', 'date': '15/5/2021',
                                                        'cite': self.R1}]}, 'calc': None, 'notes': []}
        out, problems, _n = rp.check_text(raw, {'research2': {}}, sec, '')
        self.assertEqual(problems, [])
        self.assertEqual(out.count(self.R1), 1)
        self.assertNotRegex(out, r'P1|ص\d')


class MissionTests(Base):
    LONG = ('لبيان طبيعة العلاقة بين طرفي الدعوى والتزامات كل منهما قبل الآخر وبيان الطرف المخل بالتزاماته وبيان المبالغ '
            'المسددة والمتبقية وعلى وجه العموم تصفية الحساب بين الطرفين')

    def test_single_long_point_is_split_not_echoed_as_one_heading(self):
        self.data['mission']['points'] = [{'id': 'q1', 'n': 1, 'text': self.LONG}]
        r = rp.build_plan(self.base, self.data)
        self.assertGreaterEqual(len(r['axes']), 3)
        for a in r['axes']:
            self.assertLess(len(a['title']), len(self.LONG) * 0.6)
            self.assertEqual(a['point_ids'], ['q1'])

    def test_research_text_does_not_start_with_whole_mission(self):
        self.run_all()
        rp.merge_all(self.base, self.data)
        txt = rp.research_text(self.base, self.data)
        self.assertTrue(txt.startswith('أولاً: '))
        self.assertNotIn(MISSION, txt)

    def test_mission_echo_sentence_removed_from_draft(self):
        sec = {'kind': 'general', 'facts': {'facts': []}, 'calc': None, 'notes': []}
        out, _p, notes = rp.check_text('لبيان طبيعة العلاقة بين طرفي الدعوى والتزامات كل منهما قبل الآخر. ثبت للخبرة كذا.',
                                       {'research2': {}}, sec, MISSION)
        self.assertEqual(out, 'ثبت للخبرة كذا.')
        self.assertTrue(any(k == rp.N_REMOVED for k, _t in notes))


class AutoConclusionTests(PageTests):
    """النتيجة تلقائية بعد دمج البحث، وتتحدّث بتغيّر نصه، ولا تتجاوز نصاً عدّله الخبير."""

    def setUp(self):
        super().setUp()
        self.qp.CasePageDialog.AUTO_CONCLUSION = True

    def test_conclusion_generated_automatically_after_merge(self):
        dlg = self.page()
        self.buttons(dlg)['اكتب البحث'].click()               # يُدمج تلقائياً ثم تُكتب النتيجة
        self.wait(dlg)
        self.wait(dlg)
        rec = cp2.record(dlg.data)
        self.assertIsNotNone(rec)                              # بلا ضغط «اكتب»
        self.assertEqual(len(rec['paragraphs']), 3)

    def test_updates_when_research_changes_unless_edited(self):
        dlg = self.page()
        self.buttons(dlg)['اكتب البحث'].click()
        self.wait(dlg)
        self.wait(dlg)
        s = rp.state(dlg.data)['axes'][1]['sections'][0]
        old_sha = cp2.record(dlg.data)['source_sha']
        rp.set_section_text(dlg.base, dlg.data, s['key'], rp.section_text(dlg.base, s) + ' وثبت ذلك للخبرة أيضاً.')
        dlg.reload()
        self.wait(dlg)
        self.assertNotEqual(cp2.record(dlg.data)['source_sha'], old_sha)       # حُدّثت تلقائياً
        cp2.set_text(dlg.base, dlg.data, cp2.text_of(cp2.record(dlg.data)) + '\nأن فقرة بخط الخبير')
        kept = cp2.text_of(cp2.record(dlg.data))
        rp.set_section_text(dlg.base, dlg.data, s['key'], rp.section_text(dlg.base, s) + ' وتفصيل آخر.')
        dlg.reload()
        self.wait(dlg)
        self.assertEqual(cp2.text_of(cp2.record(dlg.data)), kept)              # لم تُستبدل
        self.assertFalse(cp2.needs_regen(dlg.base, dlg.data))
        self.assertIn('البحث تغيّر بعد تعديلك للنتيجة — «إعادة الكتابة» تكتب البحث والنتيجة من جديد', cp2.notes(dlg.base, dlg.data))
        self.assertIn('إعادة الكتابة', self.buttons(dlg))
        self.assertEqual(cc.run_conclusion(dlg.base, dlg.data, ask=FakeAsk()), 'done')    # بلا force لا تُستبدل
        self.assertEqual(cp2.text_of(cp2.record(dlg.data)), kept)


class ConclusionShapeTests(Base):
    def test_no_references_and_short_in_conclusion(self):
        self.run_all()
        rp.merge_all(self.base, self.data)

        class Refs(FakeAsk):
            def conclusion(self, prompt):
                d = super().conclusion(prompt)
                d['paragraphs'][0]['text'] = ('أن العلاقة تعاقدية بموجب الخطين 96662240 و90030422 ' + ReferenceTests.R1 +
                                              ' [P1-2 ص6، ص15] (مذكرة دفاع المدعية المؤرخة 1/3/2026)')
                return d
        cc.run_conclusion(self.base, self.data, ask=Refs())
        rec = self.data['conclusion']['v2']
        for p in rec['paragraphs']:
            self.assertNotRegex(p['text'], r'مرفق|حافظة|مذكرة دفاع|P\d|ص\s*\d|مستند')
        self.assertTrue(rec['paragraphs'][0]['text'].endswith('(أولاً).'))
        self.assertEqual(len(rec['paragraphs']), len(rp.state(self.data)['axes']))
        text = cp2.text_of(rec)
        self.assertTrue(text.startswith(cp2.OPENING))
        self.assertTrue(text.endswith(cp2.CLOSING))
        self.assertEqual(rec['paragraphs'][2]['text'].count('1,155.770 د.ك'), 1)

    def test_long_paragraph_gets_red_note_not_rejection(self):
        self.run_all()
        rp.merge_all(self.base, self.data)

        class Long(FakeAsk):
            def conclusion(self, prompt):
                d = super().conclusion(prompt)
                d['paragraphs'][1]['text'] = 'أن المدعى عليه أخل بالتزاماته ' + 'وهذا ثابت من الأوراق ' * 40
                return d
        cc.run_conclusion(self.base, self.data, ask=Long())
        self.assertTrue(any('أطول من حكم مباشر' in n for n in cp2.notes(self.base, self.data)))


if __name__ == '__main__':
    unittest.main()


class MinutesNotDocumentsTests(unittest.TestCase):
    """(2026-10-25، A2263970) محضرا Word أُضيفا من نافذة المستندات بنوع «حافظة مستندات» فدخلا البحث D1 وD2."""

    def test_minutes_doc_detected_by_folder_or_text(self):
        self.assertTrue(rp.is_minutes_doc({'file': 'مستندات_النظام/محضر الخبرة رقم 1 (2).docx'}, ''))
        self.assertTrue(rp.is_minutes_doc({'file': 'أخرى/1.docx'}, 'فتح المحضر بتاريخه في تمام الساعة 10:00'))
        self.assertFalse(rp.is_minutes_doc({'file': 'حوافظ/حافظة مستندات المدعية.pdf'}, 'حافظة مستندات مقدمة من المدعية'))


class BundleFolderTests(unittest.TestCase):
    """(2026-10-25، A2263970) حافظة أعيدت قراءتها فصارت في قائمة المجلد وحدها ← «مستند مقدم بملف الدعوى» بلا مقدّم ولا تاريخ؛
    ومحضر مسجّل في قائمة المستندات عاد من قائمة المجلد «مستنداً»."""

    def docs(self, files, content=()):
        from unittest import mock
        import case_folder as cfo
        import doc_header
        texts = {'markdown/حوافظ/ح.md': 'حافظة مستندات مقدمة من المدعية',
                 'markdown/أخرى/3 محضر.md': 'محضر', 'markdown/مذكرات/م.md': 'مذكرة دفاع'}
        man = {'files': {rel: {'state': 'done', 'md': md, 'sha1': 's'} for rel, md in files}}
        with mock.patch.object(cd, 'content_docs', lambda data: list(content)), \
                mock.patch.object(cfo, 'load_manifest', lambda base: man), \
                mock.patch.object(rp, '_read', lambda base, rel: texts.get(rel, '')), \
                mock.patch.object(rp, '_side_of', lambda t, data: 'المدعية' if t else ''), \
                mock.patch.object(doc_header, 'read', lambda base, md: {'sha1': 's', 'by': 'المدعية', 'date': '11-10-2026'}):
            return rp.documents('', {})

    def test_bundles_folder_is_bundle_with_date(self):
        d = self.docs([('حوافظ/ح.pdf', 'markdown/حوافظ/ح.md')])[0]
        self.assertEqual((d['kind'], d['side'], d['date'], d['memo']), ('حافظة مستندات', 'المدعية', '11/10/2026', False))
        self.assertEqual(d['cite'], '(مرفق بحافظة مستندات المدعية المؤرخة 11/10/2026)')

    def test_memos_folder_is_memo(self):
        d = self.docs([('مذكرات/م.pdf', 'markdown/مذكرات/م.md')])[0]
        self.assertEqual((d['kind'], d['memo']), ('مذكرة دفاع', True))

    def test_registered_minutes_not_back_from_folder(self):
        p = {'submitter': 'المدعية', 'docs': []}
        doc = {'file': 'أخرى/3 محضر.pdf', 'md': 'markdown/أخرى/3 محضر.md', 'doc_type': 'محضر أعمال',
               'convert': {'state': 'done'}}
        out = self.docs([('أخرى/3 محضر.pdf', 'markdown/أخرى/3 محضر.md')], content=[(p, doc)])
        self.assertEqual(out, [])
