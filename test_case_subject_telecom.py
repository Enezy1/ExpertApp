# اختبارات صيغة «الموضوع» لقضايا الاتصالات: python -W ignore -m unittest test_case_subject_telecom -v
# صحائف وأسماء وأرقام وهمية كلها. ask دالة مزيّفة تعيد JSON كما يفعل النموذج (وأحياناً تهلوس عمداً).
import case_subject_mission as _sm_style
_sm_style.STYLE = 'formula'          # هذه الاختبارات للقوالب القديمة؛ الكتابة بالذكاء في test_subject_style.py
import json
import os
import tempfile
import unittest

import case_model as cm
import case_subject_mission as sm
import case_subject_telecom as st
import case_workspace as cw
import report_docx
import telecom_config

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)
TELECOM = dict(CASE, plaintiff='شركة الاتصالات المتنقلة', company='زين', defendants=['فلان الاختباري الوهمي'])
COMPANIES = telecom_config.DEFAULT_COMPANIES

PLAINT = """بسم الله الرحمن الرحيم
صحيفة دعوى
المدعية: شركة الاتصالات المتنقلة (زين) ش.م.ك.ع
المدعى عليه: فلان الاختباري الوهمي
أولاً: الوقائع
بموجب عقد اشتراك مؤرخ 15/03/2024 اشترك المدعى عليه لدى المدعية في خدمة الاتصال للخط رقم 99990000
مقابل اشتراك شهري قدره 18.500 د.ك لمدة التزام قدرها 24 شهراً، وقد توقف المدعى عليه عن السداد
وتراكمت عليه مديونية.
ثانياً: الطلبات
ليسمع المدعى عليه الحكم بإلزامه بأن يؤدي للمدعية مبلغ 436.750 د.ك مع الفوائد القانونية
بواقع 7% من تاريخ الاستحقاق وحتى تمام السداد وبالرسوم والمصروفات ومقابل أتعاب المحاماة.
"""
CLAIM = ('الحكم بإلزامه بأن يؤدي للمدعية مبلغ 436.750 د.ك مع الفوائد القانونية بواقع 7% من تاريخ الاستحقاق '
         'وحتى تمام السداد وبالرسوم والمصروفات ومقابل أتعاب المحاماة')
GOOD = {'date': '15/03/2024', 'monthly': '18.500 د.ك', 'duration': '24 شهراً'}

# نفس الصحيفة بلا ذكر لمدة الالتزام (والباقي كما هو)
PLAINT_NO_DURATION = PLAINT.replace(' لمدة التزام قدرها 24 شهراً،', '،')


def fake_ask(contracts, claim, seen=None):
    def ask(prompt):
        if seen is not None:
            seen.append(prompt)
        return 'تفضل:\n' + json.dumps({'contracts': contracts, 'claim': claim}, ensure_ascii=False)
    return ask


def expected(date='15/03/2024', monthly='18.500 د.ك', duration='24 شهراً', claim=CLAIM, who='المدعى عليه',
             last='الأخير', neg='لم يلتزم'):
    to_who = 'ل' + who[1:]
    return (f'جاءت المدعية بصحيفة مفادها أنها بموجب عقد اشتراك مؤرخ {date} قامت المدعية بتقديم خدمات الاتصال '
            f'لصالح {who}، وذلك مقابل اشتراك شهري {monthly} مع مدة التزام وقدرها {duration}. '
            f'وأفادت المدعية على حسب دعواها أنها قدّمت الخدمة {to_who} إلا أن {last} {neg} بالسداد، '
            f'فتم رفع الدعوى الماثلة، وطلبت {claim}.')


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(TELECOM, self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_step(self, plaint=PLAINT, ask=None, case_row=None, **kw):
        row = case_row or {}
        return sm.run_subject(self.base, self.data, lambda no: row, ask=ask,
                              claim_fn=(lambda: plaint) if plaint is not None else None, companies=COMPANIES, **kw)

    def disk(self):
        return cw.read_case_json(self.base)


class FullPlaintTests(Base):
    def test_template_filled_exactly_from_plaint(self):
        seen = []
        self.assertEqual(self.run_step(ask=fake_ask([GOOD], CLAIM, seen)), 'done')
        d = self.disk()
        self.assertEqual(d['subject'], expected())               # الصيغة كما هي بقيم الصحيفة حرفياً
        self.assertNotIn(st.TODO, d['subject'])
        self.assertEqual(d['steps']['subject']['state'], 'done')  # كُتبت لا «راجعها»: الاعتماد بنافذة المراجعة
        self.assertIn('فلان الاختباري', seen[0])                  # نص الصحيفة ذهب للنموذج

    def test_complete_text_then_review_dialog_approval_path(self):
        self.run_step(ask=fake_ask([GOOD], CLAIM))
        sm.review_subject(self.base, self.data)
        self.assertEqual(self.disk()['steps']['subject']['state'], 'reviewed')

    def test_values_come_from_plaint_not_from_model_spelling(self):
        # النموذج كتب 18.5 و«شهراً» والصحيفة 18.500 و«شهر»: التحقق بقيمة Decimal، والمكتوب نص الصحيفة
        plaint = PLAINT.replace('24 شهراً', '24 شهر')
        self.run_step(plaint=plaint, ask=fake_ask([dict(GOOD, monthly='18.5 د.ك')], CLAIM))
        self.assertEqual(self.disk()['subject'], expected(duration='24 شهر'))

    def test_indic_digits_plaint_displayed_with_latin_digits(self):
        plaint = (PLAINT.replace('15/03/2024', '١٥/٠٣/٢٠٢٤').replace('18.500', '١٨٫٥٠٠')
                  .replace('24 شهراً', '٢٤ شهراً'))
        self.run_step(plaint=plaint, ask=fake_ask([GOOD], CLAIM))
        self.assertEqual(self.disk()['subject'], expected())

    def test_two_contracts_listed_in_order_in_the_same_sentence(self):
        plaint = PLAINT.replace('بموجب عقد اشتراك مؤرخ 15/03/2024 اشترك',
                                'بموجب عقد اشتراك مؤرخ 01/02/2023 بقيمة 12 د.ك لمدة 12 شهراً وعقد آخر مؤرخ 15/03/2024 اشترك')
        c1 = {'date': '01/02/2023', 'monthly': '12 د.ك', 'duration': '12 شهراً'}
        self.run_step(plaint=plaint, ask=fake_ask([c1, GOOD], CLAIM))
        s = self.disk()['subject']
        self.assertIn('عقد اشتراك مؤرخ 01/02/2023 وعقد آخر مؤرخ 15/03/2024 قامت المدعية', s)
        self.assertIn('اشتراك شهري 12.000 د.ك للعقد الأول و18.500 د.ك للعقد الثاني', s)
        self.assertIn('مدة التزام وقدرها 12 شهراً للعقد الأول و24 شهراً للعقد الثاني', s)
        self.assertEqual(self.disk()['steps']['subject']['state'], 'done')

    def test_duplicate_contract_from_model_is_dropped(self):
        self.run_step(ask=fake_ask([GOOD, dict(GOOD)], CLAIM))
        self.assertEqual(self.disk()['subject'], expected())


class MissingValuesTests(Base):
    def test_plaint_without_duration_leaves_todo_not_a_guess(self):
        # الصحيفة بلا مدة والنموذج أعاد null: «[يُكتب]» والباقي يُملأ
        st_ = self.run_step(plaint=PLAINT_NO_DURATION, ask=fake_ask([dict(GOOD, duration=None)], CLAIM))
        self.assertEqual(st_, 'needs_input')
        d = self.disk()
        self.assertEqual(d['subject'], expected(duration=st.TODO))
        self.assertIn('مدة التزام وقدرها [يُكتب].', d['subject'])
        self.assertIn('مدة الالتزام', d['steps']['subject']['message'])
        self.assertNotIn('تاريخ العقد', d['steps']['subject']['message'])

    def test_model_guess_not_in_plaint_is_rejected_by_code(self):
        # النموذج هلوس مدة؛ الكود يردّها: 36 غير واردة، و«7 شهراً» رقمها وارد (7%) لكن العبارة لم ترد متصلة
        for guess in ('36 شهراً', '7 شهراً', '24 يوماً', 'سنتان'):
            with self.subTest(guess=guess):
                self.data['steps']['subject'] = cm.new_step()
                self.run_step(plaint=PLAINT_NO_DURATION, ask=fake_ask([dict(GOOD, duration=guess)], CLAIM), force=True)
                self.assertEqual(self.disk()['subject'], expected(duration=st.TODO))

    def test_rejections_are_reported_with_reason(self):
        built = st.build_subject(PLAINT_NO_DURATION, ['فلان'], fake_ask([dict(GOOD, duration='36 شهراً')], CLAIM))
        self.assertEqual([lbl for lbl, _ in built['rejected']], ['مدة الالتزام (1)'])
        self.assertIn('غير وارد', built['rejected'][0][1])
        self.assertEqual(built['missing'], ['مدة الالتزام'])

    def test_amount_not_in_plaint_rejected(self):
        self.run_step(ask=fake_ask([dict(GOOD, monthly='19.500 د.ك')], CLAIM))
        self.assertEqual(self.disk()['subject'], expected(monthly=st.TODO))

    def test_zero_or_missing_number_rejected(self):
        plaint = PLAINT.replace('18.500', '0')
        self.run_step(plaint=plaint, ask=fake_ask([dict(GOOD, monthly='0 د.ك')], CLAIM))
        self.assertIn('اشتراك شهري [يُكتب] مع', self.disk()['subject'])
        self.assertEqual(st.verify('amount', 'د.ك فقط', st.Plaint(PLAINT))[0], None)

    def test_date_without_digits_rejected(self):
        self.assertIsNone(st.verify('date', 'مارس', st.Plaint(PLAINT.replace('15/03/2024', 'مارس')))[0])

    def test_paraphrased_claim_is_not_accepted(self):
        self.run_step(ask=fake_ask([GOOD], 'إلزام المدعى عليه بسداد مبلغ 436.750 د.ك'))
        d = self.disk()
        self.assertTrue(d['subject'].endswith('وطلبت [يُكتب].'))
        self.assertIn('المطالبة', d['steps']['subject']['message'])

    def test_claim_with_wrong_amount_is_rejected(self):
        self.run_step(ask=fake_ask([GOOD], CLAIM.replace('436.750', '463.750')))
        self.assertTrue(self.disk()['subject'].endswith('وطلبت [يُكتب].'))

    def test_contract_with_nothing_verified_is_not_counted(self):
        ghost = {'date': '01/01/1999', 'monthly': '5 د.ك', 'duration': '3 شهراً'}
        self.run_step(ask=fake_ask([GOOD, ghost], CLAIM))
        self.assertEqual(self.disk()['subject'], expected())

    def test_nothing_extracted_gives_full_template_of_todos(self):
        self.run_step(ask=fake_ask([], None))
        s = self.disk()['subject']
        self.assertEqual(s.count(st.TODO), 4)                      # تاريخ، اشتراك، مدة، مطالبة
        self.assertEqual(self.disk()['steps']['subject']['state'], 'needs_input')

    def test_report_marker_is_the_same_todo(self):
        self.assertEqual(st.TODO, report_docx.TODO)


class SourceProblemTests(Base):
    def test_no_connection_for_claim_keeps_template_with_todos(self):
        self.assertEqual(self.run_step(plaint=None, ask=lambda p: self.fail('لا يجوز استدعاء الذكاء بلا صحيفة')),
                         'needs_input')
        d = self.disk()
        self.assertEqual(d['subject'], expected(date=st.TODO, monthly=st.TODO, duration=st.TODO, claim=st.TODO))
        self.assertIn('لا يتوفر اتصال', d['steps']['subject']['message'])

    def test_claim_not_found_or_unreadable(self):
        self.assertEqual(self.run_step(plaint='  ', ask=lambda p: self.fail('x')), 'needs_input')
        self.assertIn('لم تُوجد صحيفة', self.disk()['steps']['subject']['message'])

    def test_claim_fetch_error_fails_and_retry_works(self):
        def boom():
            raise RuntimeError('جلسة منتهية')
        self.assertEqual(sm.run_subject(self.base, self.data, lambda no: {}, claim_fn=boom, companies=COMPANIES),
                         'failed')
        self.assertIn('جلسة منتهية', self.disk()['steps']['subject']['message'])
        self.assertEqual(self.run_step(ask=fake_ask([GOOD], CLAIM)), 'done')

    def test_ai_errors_fail_with_message(self):
        for bad in (lambda p: 'لا json هنا', lambda p: '[1, 2]'):
            with self.subTest(bad=bad('')):
                self.data['steps']['subject'] = cm.new_step()
                self.assertEqual(self.run_step(ask=bad), 'failed')
        self.assertIn('تعذّر استخراج', self.disk()['steps']['subject']['message'])

        def down(prompt):
            raise ConnectionError('لا مزود')
        self.data['steps']['subject'] = cm.new_step()
        self.assertEqual(self.run_step(ask=down), 'failed')
        self.assertIn('لا مزود', self.disk()['steps']['subject']['message'])


class DetectionTests(Base):
    def test_other_plaintiffs_use_the_general_contract_form(self):
        import test_case_subject_contract as tc
        with tempfile.TemporaryDirectory() as other:
            base, data = cw.ensure_workspace(CASE, other)               # المدعية «شركة وهمية للاتصالات»
            row = {'case_summary': 'نزاع حول فواتير'}
            res = sm.run_subject(base, data, lambda no: row, ask=tc.ask_with(tc.REPLY),
                                 claim_fn=lambda: tc.PLAINT, companies=COMPANIES)
            self.assertEqual((res, data['subject']), ('done', tc.EXPECTED))
            self.assertNotIn('نزاع حول فواتير', data['subject'])          # لا ملخص حر

    def test_detected_from_case_db_plaintiffs_and_title(self):
        self.assertEqual(st.telecom_company({'plaintiffs': ['شركة أوريدو الكويت']}, {}, COMPANIES), 'أوريدو')
        self.assertEqual(st.telecom_company({}, {'title': 'stc ضد فلان'}, COMPANIES), 'stc')
        self.assertIsNone(st.telecom_company({'plaintiffs': ['شركة وهمية']}, {'title': 'فلان ضد زين'}, COMPANIES))

    def test_companies_come_from_the_telecom_section(self):
        custom = {'اتصالات_وهمية': ['وهمية للاتصالات']}
        self.assertEqual(st.telecom_company({}, {'plaintiff': 'شركة وهمية للاتصالات'}, custom), 'اتصالات_وهمية')


class DefendantFormTests(Base):
    def go(self, defendants, plaint=PLAINT):
        self.data['case']['defendants'] = defendants
        self.data['steps']['subject'] = cm.new_step()
        self.run_step(plaint=plaint, ask=fake_ask([GOOD], CLAIM), force=True)
        return self.disk()['subject']

    def test_male_single(self):
        self.assertEqual(self.go(['فلان الاختباري']), expected())

    def test_female_single_by_plaint_wording(self):
        plaint = PLAINT.replace('المدعى عليه', 'المدعى عليها')
        self.assertEqual(self.go(['فلانة الاختبارية'], plaint),
                         expected(who='المدعى عليها', last='الأخيرة', neg='لم تلتزم'))

    def test_company_defendant_is_feminine(self):
        self.assertEqual(self.go(['شركة الأفق الوهمية للتجارة']),
                         expected(who='المدعى عليها', last='الأخيرة', neg='لم تلتزم'))

    def test_several_defendants_plural(self):
        self.assertEqual(self.go(['فلان الاختباري', 'علان الاختباري']),
                         expected(who='المدعى عليهم', last='الأخيرين', neg='لم يلتزموا'))

    def test_unknown_gender_defaults_to_masculine_with_note(self):
        plaint = PLAINT.replace('المدعى عليه', 'الطرف الآخر')
        self.go(['فلان الاختباري'], plaint)
        self.assertIn('جنس المدعى عليه غير محسوم', self.disk()['steps']['subject']['message'])
        self.assertIn('لصالح المدعى عليه،', self.disk()['subject'])

    def test_wording_does_not_confuse_feminine_with_masculine(self):
        self.assertEqual(st.Plaint('المدعى عليها الأولى والمدعى عليها الثانية').wording(), (0, 2, 0))
        self.assertEqual(st.Plaint('المدعى عليه والمدعى عليهم').wording(), (1, 0, 1))

    def test_defendants_unknown_use_plaint_wording(self):
        self.assertEqual(st.defendant_kind([], st.Plaint('المدعى عليها')), ('f', ''))
        self.assertEqual(st.defendant_kind([], st.Plaint('المدعى عليه والمدعى عليها'))[0], 'p')
        self.assertEqual(st.defendant_kind([], None)[0], 'm')


class MatchingTests(unittest.TestCase):
    def test_numbers_compared_by_decimal_value(self):
        p = st.Plaint('مبلغ 1,250.500 د.ك و ١٠٠ و 7.0')
        self.assertEqual(p.find('1250.5 د.ك'), '1,250.500 د.ك')
        self.assertEqual(p.find('100'), '100')
        self.assertIn(st.Decimal('7'), p.numbers)
        self.assertIsNone(p.find('1250.6 د.ك'))

    def test_phrase_must_be_contiguous_and_whole_tokens(self):
        p = st.Plaint('2 24 شهراً')
        self.assertIsNone(p.find('224'))
        self.assertIsNone(p.find('2 شهراً'))
        self.assertEqual(p.find('24 شهر'), '24 شهراً')

    def test_tashkeel_and_hamza_ignored(self):
        self.assertEqual(st.Plaint('مدّة الالتزام أربعة وعشرون شهرًا').find('مده الإلتزام'), 'مدّة الالتزام')
        self.assertEqual(st.Plaint('مُدَّةُ الالتزام').find('مدة الالتزام'), 'مُدَّةُ الالتزام')
        self.assertIsNone(st.Plaint('مدة الالتزام').find('مدة الالتزامات'))


if __name__ == '__main__':
    unittest.main()
