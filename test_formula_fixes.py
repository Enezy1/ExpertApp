# اختبارات 2026-10-19: صيغة موضوع الاتصالات حرفياً + «إعادة الكتابة» للإجراءات بلا تأليف + العقود المختصرة.
# python -W ignore -m unittest test_formula_fixes -v
import json
import os
import tempfile
import unittest

import case_contracts
import case_procedures as cp
import case_rewrite
import case_subject_ai as sa
import case_workspace as cw

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)


class TelecomFormula(unittest.TestCase):
    def test_exact_wording_and_nothing_after(self):
        t = sa.compose_telecom({'contract_date': '19/04/2018', 'claim': 'إلزام المدعى عليه بأن يؤدي مبلغ 1,155.770 د.ك'})
        self.assertTrue(t.startswith('جاءت المدعية بصحيفة مفادها أنه بموجب عقد اشتراك مؤرخ 19/04/2018 مبرم بينها وبين المدعى عليه'))
        self.assertIn('إلا أن الأخير لم يلتزم بالسداد مما ترصد في ذمته مبلغ (1,155.770 د.ك)', t)
        self.assertTrue(t.endswith('فتم رفع الدعوى الماثلة.'))
        self.assertNotIn('بحكم مشمول', t)

    def test_missing_parts_dropped_silently_and_gender(self):
        t = sa.compose_telecom({}, 'f')
        self.assertNotIn('مؤرخ', t)
        self.assertNotIn('[يُكتب]', t)
        self.assertIn('الأخيرة لم تلتزم بالسداد، فتم رفع', t)


class ProceduresRewrite(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_rewrite_uses_template_never_ai_prose(self):
        prompts = []
        self.data['procedures'] = {'text': 'نص ألّفه الذكاء عن الجلسة الأولى', 'edited': True, 'edited_by': 'rewrite'}
        case_rewrite.rewrite_procedures(self.base, self.data, ask=lambda p: prompts.append(p) or '{}')
        self.assertEqual(self.data['procedures']['text'], cp.compose_text(self.data))
        self.assertTrue(self.data['procedures']['text'].startswith('استلمنا ملف الدعوى'))
        self.assertFalse(any('أعد صياغة' in p for p in prompts))

    def test_old_ai_text_replaced_on_reevaluate(self):
        self.data['procedures'] = {'text': 'وفي الجلسة الأولى وجهت الخبرة طلبات…', 'edited': True, 'edited_by': 'rewrite'}
        cp.re_evaluate(self.base, self.data)
        self.assertNotIn('الجلسة الأولى', self.data['procedures']['text'])


class ContractLines(unittest.TestCase):
    def test_short_line_and_note(self):
        c = {'kind': 'عقد بين الطرفين', 'date': '01/02/2020', 'summary': 'اشتراك شهري بقيمة 15 د.ك مع جهازين بقيمة 240 د.ك',
             'value': '15 د.ك', 'checks': {'date': True, 'value': True}}
        self.assertEqual(case_contracts.contract_line(c),
                         'عقد بين الطرفين مؤرخ 01/02/2020 — اشتراك شهري بقيمة 15 د.ك مع جهازين بقيمة 240 د.ك')


if __name__ == '__main__':
    unittest.main()
