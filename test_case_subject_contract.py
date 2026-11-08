# اختبارات «الموضوع» بصيغة العقد العام (غير الاتصالات): python -W ignore -m unittest test_case_subject_contract -v
# لا ملخص حر: القالب ثابت وقيمه من صحيفة الدعوى حرفياً، وما لم يتحقق «[يُكتب]».
import case_subject_mission as _sm_style
_sm_style.STYLE = 'formula'          # هذه الاختبارات للقوالب القديمة؛ الكتابة بالذكاء في test_subject_style.py
import json
import os
import tempfile
import unittest

import case_subject_contract as sc
import case_subject_mission as sm
import case_workspace as cw

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)
COMPANIES = {'زين': ['زين']}            # المدعية في الحالة التجريبية «شركة وهمية للاتصالات» ليست منها

PLAINT = ('تقدمت الشركة المدعية بصحيفة دعواها وقالت إنها بموجب عقد مؤرخ 10/01/2025 اتفقت مع المدعى عليه على '
          'توريد وتركيب أجهزة تكييف بالمبنى، مقابل مبلغ 12,500 د.ك لمدة 6 أشهر، وأنها نفذت كافة التزاماتها '
          'التعاقدية إلا أن المدعى عليه أخل في سداد قيمة الأعمال المنفذة، لذلك تطلب الحكم بإلزامه بالمبلغ.')
REPLY = {'contracts': [{'date': '10/01/2025', 'object': 'اتفقت مع المدعى عليه على توريد وتركيب أجهزة تكييف بالمبنى',
                        'amount': 'مبلغ 12,500 د.ك', 'duration': '6 أشهر'}],
         'performed': 'نفذت كافة التزاماتها التعاقدية', 'breach': 'سداد قيمة الأعمال المنفذة'}
EXPECTED = ('جاءت المدعية بصحيفة مفادها أنها بموجب عقد مؤرخ 10/01/2025 اتفقت مع المدعى عليه على توريد وتركيب '
            'أجهزة تكييف بالمبنى، وذلك مقابل مبلغ 12,500.000 د.ك لمدة 6 أشهر. وأفادت المدعية – على حسب دعواها – '
            'أنها نفذت كافة التزاماتها التعاقدية إلا أن المدعى عليه أخلّ في سداد قيمة الأعمال المنفذة، '
            'فتم رفع الدعوى الماثلة.')


def ask_with(reply):
    return lambda prompt: 'الرد:\n' + json.dumps(reply, ensure_ascii=False)


class BuildTests(unittest.TestCase):
    def test_full_formula_verbatim_from_plaint(self):
        b = sc.build_subject(PLAINT, ['مدعى عليه تجريبي'], ask_with(REPLY))
        self.assertEqual(b['text'], EXPECTED)
        self.assertEqual(b['missing'], [])

    def test_model_paraphrase_is_rejected_not_written(self):
        bad = dict(REPLY, performed='قامت بتنفيذ العقد على أكمل وجه', contracts=[dict(REPLY['contracts'][0], amount='13000 د.ك')])
        b = sc.build_subject(PLAINT, ['مدعى عليه تجريبي'], ask_with(bad))
        self.assertNotIn('أكمل وجه', b['text'])
        self.assertNotIn('13000', b['text'])
        self.assertIn('مبلغ العقد', b['missing'])
        self.assertEqual(b['text'].count(sc.TODO), 1)

    def test_no_plaint_gives_template_with_todo_only(self):
        b = sc.build_subject('', ['س'], None)
        self.assertTrue(b['text'].startswith('جاءت المدعية بصحيفة مفادها أنها بموجب عقد مؤرخ [يُكتب]'))
        self.assertTrue(b['text'].endswith('فتم رفع الدعوى الماثلة.'))
        self.assertEqual(len(b['missing']), 5)

    def test_company_defendant_is_feminine(self):
        b = sc.build_subject(PLAINT, ['شركة الخليج للمقاولات'], ask_with(REPLY))
        self.assertIn('إلا أن المدعى عليها أخلّت في', b['text'])

    def test_no_contract_in_plaint_is_noted(self):
        b = sc.build_subject(PLAINT, ['س'], ask_with({'contracts': [], 'performed': None, 'breach': None}))
        self.assertIn('لم تذكر الصحيفة عقداً', b['note'])


class StepTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_non_telecom_uses_contract_formula_not_summary(self):
        row = {'case_summary': 'قضية تعاقدية — ملخص حر لا يُستخدم'}
        res = sm.run_subject(self.base, self.data, lambda no: row, ask=ask_with(REPLY), claim_fn=lambda: PLAINT,
                             companies=COMPANIES)
        self.assertEqual((res, self.data['subject']), ('done', EXPECTED))
        self.assertIn('صيغة العقد العام', self.data['steps']['subject']['message'])

    def test_without_connection_needs_input_with_todo_not_summary(self):
        row = {'case_summary': 'قضية تعاقدية — ملخص'}
        res = sm.run_subject(self.base, self.data, lambda no: row, companies=COMPANIES)
        self.assertEqual(res, 'needs_input')
        self.assertNotIn('ملخص', self.data['subject'])
        self.assertIn(sc.TODO, self.data['subject'])

    def test_rewrite_with_force_reruns_done_subject(self):
        sm.run_subject(self.base, self.data, lambda no: {}, ask=ask_with(REPLY), claim_fn=lambda: PLAINT,
                       companies=COMPANIES)
        calls = []
        sm.run_subject(self.base, self.data, lambda no: {}, ask=lambda p: calls.append(p) or '{}',
                       claim_fn=lambda: PLAINT, companies=COMPANIES)
        self.assertEqual(calls, [])                          # بلا force: لا عمل
        sm.run_subject(self.base, self.data, lambda no: {}, ask=lambda p: calls.append(p) or '{}',
                       claim_fn=lambda: PLAINT, companies=COMPANIES, force=True)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
