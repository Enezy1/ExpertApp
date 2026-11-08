# اختبارات دفعة «أسلوب الموضوع»: التواريخ، حفظ الصحيفة والحكم، الكتابة بالذكاء، الأسئلة المهمة، ✓ الصادقة، إصدار Word
# python -W ignore -m unittest test_subject_style -v
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

import case_model as cm
import case_questions as cq
import case_sources as src
import case_subject_ai as sa
import case_subject_mission as sm
import case_subject_telecom as st
import case_workspace as cw
import reports_list_model as rlm
import qt_case_page as qp
qp.CasePageDialog.AUTO_SYNC = False            # المزامنة عند الفتح تُختبر في test_folder_minutes_referral
qp.CasePageDialog.AUTO_ASK_TYPE = False

HERE = os.path.dirname(os.path.abspath(__file__))
APP = QApplication.instance() or QApplication([])
B = chr(92)            # المائلة العكسية
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)

WORDS = 'خمسة آلاف وثمانمائة وستة وسبعون ديناراً وخمسمائة وأربعون فلساً'
PLAINT = ('تقدمت الشركة المدعية بصحيفة دعوى وقالت إنه بموجب العقد المؤرخ 19' + B + '4' + B + '2018 تعهدت المدعية بصفتها '
          'مقاول من الباطن للمدعى عليها الأولى بصفتها مقاول رئيسي بتركيب معدات المختبرات العلمية مقابل مبلغ 5,876.540 د.ك '
          f'({WORDS}) لمدة 24 شهراً. وقامت المدعية بالتوريد وتم اعتماد الأجهزة إلا أن المدعى عليها أخلّت بعدم سداد '
          'المستحقات المالية. لذلك تطلب الحكم بإلزام المدعى عليها بأن تؤدي لها مبلغ 5,876.540 د.ك مع الفوائد.')
FACTS = {'plaintiff_capacity': 'بصفتها مقاول من الباطن', 'defendant_capacity': 'بصفتها مقاول رئيسي',
         'contract_date': '19/4/2018', 'contract_number': None,
         'object': 'بتركيب معدات المختبرات العلمية', 'amount': '5,876.540 د.ك (' + WORDS + ')',
         'duration': '24 شهراً', 'performed': 'وقامت المدعية بالتوريد وتم اعتماد الأجهزة',
         'breach': 'أخلّت بعدم سداد المستحقات المالية',
         'claim': 'الحكم بإلزام المدعى عليها بأن تؤدي لها مبلغ 5,876.540 د.ك مع الفوائد'}
GOOD_TEXT = ('جاءت المدعية بصحيفة مفادها أنه بموجب العقد المؤرخ 19/04/2018 تعهدت المدعية بصفتها مقاول من الباطن '
             'بتركيب معدات المختبرات العلمية مقابل مبلغ 5,876.540 د.ك لمدة 24 شهراً. وأفادت المدعية على حسب دعواها أنها '
             'قامت بالتوريد، إلا أن المدعى عليها أخلّت بعدم سداد المستحقات المالية.')


def fake_ask(facts=None, text=GOOD_TEXT, prompts=None):
    facts = FACTS if facts is None else facts

    def ask(prompt):
        if prompts is not None:
            prompts.append(prompt)
        if 'نص الصحيفة:' in prompt:
            return json.dumps(facts, ensure_ascii=False)
        return text
    return ask


class StyleEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        sa.STYLE_PATH = os.path.join(self.tmp.name, 'styles.md')
        self.addCleanup(lambda: setattr(sa, 'STYLE_PATH', None))
        old = sm.STYLE
        sm.STYLE = 'ai'
        self.addCleanup(lambda: setattr(sm, 'STYLE', old))


class DateTests(unittest.TestCase):
    def test_formats_normalized_to_dd_mm_yyyy(self):
        for v in ('19/4/2018', '19' + B + '4' + B + '2018', '2018/4/19', '19-4-2018', '19.4.2018', '١٩/٤/٢٠١٨',
                  '٢٠١٨' + B + '٤' + B + '١٩'):
            self.assertEqual(st.fmt_date(st.parse_date(v)), '19/04/2018', v)

    def test_ocr_reversed_blob_is_date_only_after_date_cue(self):
        with_cue = st.Plaint('بموجب العقد المؤرخ 201814119 اتفق الطرفان')
        no_cue = st.Plaint('عقد رقم 201814119 اتفق الطرفان')
        self.assertEqual(st.verify('date', '19/4/2018', with_cue), ('19/04/2018', ''))
        self.assertIsNone(st.verify('date', '19/4/2018', no_cue)[0])
        self.assertIsNone(st.verify('date', '201814119', no_cue)[0])          # رقم عقد لا تاريخ

    def test_logic_checks(self):
        p = st.Plaint('مؤرخ 31/02/2018 و 5/5/1985 و 12/13/2018 و 7/7/2031')
        for v in ('31/02/2018', '5/5/1985', '12/13/2018', '7/7/2031'):
            self.assertIsNone(st.verify('date', v, p)[0], v)

    def test_date_not_in_plaint_is_dropped_not_guessed(self):
        p = st.Plaint('بموجب العقد المؤرخ 19/4/2018')
        val, why = st.verify('date', '20/4/2018', p)
        self.assertIsNone(val)
        self.assertIn('غير وارد', why)

    def test_contract_number_with_backslashes_is_a_number(self):
        num = '013' + B + '2017' + B + '66001' + B + 'CTP' + B + 'SCA' + B + 'V'
        p = st.Plaint('عقد رقم ' + num + ' مؤرخ 19/4/2018')
        self.assertEqual(st.verify('number', num, p), (num, ''))
        self.assertIsNone(st.find_date(num))


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base, self.data = cw.ensure_workspace(CASE, os.path.join(self.tmp.name, 'ws'))
        self.judg = os.path.join(self.tmp.name, 'judgments')
        os.makedirs(self.judg)
        old = src.JUDGMENTS_DIR
        src.JUDGMENTS_DIR = self.judg
        self.addCleanup(lambda: setattr(src, 'JUDGMENTS_DIR', old))
        self.pdf = os.path.join(self.tmp.name, 'in.pdf')
        with open(self.pdf, 'wb') as f:
            f.write(b'%PDF-1.4\n' + b'x' * 400)

    def test_claim_saved_with_date_and_engine_then_reused_without_network(self):
        calls = []

        def fake_get(cookies, autocase, uid, path):
            calls.append(1)
            with open(path, 'wb') as f:
                f.write(open(self.pdf, 'rb').read())
            return {}, path, 'OK'

        def fake_pdf_text(path, stronger=False):
            st._tls.info = {'engine': 'gemini', 'label': 'Gemini', 'skipped': []}
            return 'نص الصحيفة المقروء'
        with mock.patch('documents.get_claim_for_case', fake_get), mock.patch.object(st, 'pdf_text', fake_pdf_text):
            t1 = st.fetch_claim_text({'k': 1}, 'AC1', False, self.base, self.data)
            rec = self.data['sources']['claim']
            self.assertTrue(os.path.exists(os.path.join(self.base, rec['file'])))
            self.assertTrue(rec['fetched_at'])
            self.assertEqual(rec['engine'], 'gemini')
            t2 = st.fetch_claim_text(None, 'AC1', False, self.base, self.data)         # بلا اتصال: من المحلي
        self.assertEqual((t1, t2), ('نص الصحيفة المقروء', 'نص الصحيفة المقروء'))
        self.assertEqual(len(calls), 1)
        self.assertTrue(os.path.exists(os.path.join(self.judg, f"{self.data['caso_no']}_claim.pdf")))

    def test_refresh_goes_back_to_system(self):
        calls = []

        def fake_get(cookies, autocase, uid, path):
            calls.append(1)
            with open(path, 'wb') as f:
                f.write(b'%PDF-1.4\n' + b'y' * (300 + len(calls)))
            return {}, path, 'OK'
        with mock.patch('documents.get_claim_for_case', fake_get), \
                mock.patch.object(st, 'pdf_text', lambda p, s=False: 'نص'):
            st.fetch_claim_text({'k': 1}, 'AC1', False, self.base, self.data)
            st.fetch_claim_text({'k': 1}, 'AC1', False, self.base, self.data)
            st.fetch_claim_text({'k': 1}, 'AC1', False, self.base, self.data, True)
        self.assertEqual(len(calls), 2)

    def test_no_connection_and_nothing_local_raises(self):
        with self.assertRaises(RuntimeError):
            st.fetch_claim_text(None, 'AC1', False, self.base, self.data)

    def test_tampered_local_file_is_not_trusted(self):
        src.store(self.base, self.data, 'claim', self.pdf, {'engine': 'gemini'})
        src.save_text(self.base, self.data, 'claim', 'نص')
        self.assertIsNotNone(src.load_text(self.base, self.data, 'claim'))
        with open(os.path.join(self.base, self.data['sources']['claim']['file']), 'ab') as f:
            f.write(b'tamper')
        self.assertIsNone(src.load_text(self.base, self.data, 'claim'))

    def test_old_judgment_in_desktop_folder_is_adopted_into_case_folder(self):
        # حالة A2260637: الحكم كان في judgments فقط دون ربطه بالقضية
        dst = os.path.join(self.judg, f"{self.data['caso_no']}.pdf")
        with open(dst, 'wb') as f:
            f.write(open(self.pdf, 'rb').read())
        self.assertTrue(src.adopt_judgment(self.base, self.data))
        rec = self.data['sources']['judgment']
        self.assertTrue(os.path.exists(os.path.join(self.base, rec['file'])))
        self.assertEqual(rec['origin'], 'adopted')
        self.assertFalse(src.adopt_judgment(self.base, self.data))                    # مرة واحدة
        self.assertIn('sources', cw.read_case_json(self.base))                        # مسجَّل في case.json


class AiSubjectTests(StyleEnv):
    def build(self, ask, plaint=PLAINT, defendants=('شركة المقاول',)):
        return sa.build_subject(plaint, list(defendants), ask)

    def test_models_file_created_with_the_two_approved_models_verbatim(self):
        sa.ensure_style_file()
        md = open(sa.style_path(), encoding='utf-8').read()
        self.assertIn(sa.MODEL1, md)
        self.assertIn(sa.MODEL2, md)
        self.assertLess(md.index(sa.MODEL1), md.index(sa.MODEL2))
        self.assertTrue(sa.MODEL1.startswith('جاءت المدعية بصحيفة مفادها أنه بموجب العقد المؤرخ 19/4/2018'))
        self.assertIn('(تاريخ العقد)', sa.MODEL2)

    def test_models_are_sent_few_shot_and_closest_is_picked(self):
        prompts = []
        self.build(fake_ask(prompts=prompts))
        gen = [p for p in prompts if 'النماذج المعتمدة' in p][0]
        self.assertIn(sa.MODEL1, gen)                       # مقاولة من الباطن الأقرب
        self.assertIn('لا تكرر عبارة «عقد مؤرخ»', gen)
        self.assertIn('لا تخترع', gen)
        telecom = sa.pick_models(sa.load_models(), 'اشتراك خدمات الاتصال', 'اتصالات')
        self.assertEqual(telecom[0]['title'], 'نموذج 2 — اتصالات')
        self.assertTrue(sa.pick_models(sa.load_models(), 'قضية إيجار شقة'))            # لا قريب ← الأقرب لغةً

    def test_added_model_is_persisted_and_used(self):
        sa.add_model('نموذج إيجار', ['إيجار', 'مؤجر'], 'جاءت المدعية بصحيفة مفادها أنها أجّرت العين للمدعى عليه.')
        titles = [m['title'] for m in sa.load_models()]
        self.assertEqual(titles[-1], 'نموذج إيجار')
        top = sa.pick_models(sa.load_models(), 'دعوى إيجار ومؤجر وأجرة متأخرة')[0]
        self.assertEqual(top['title'], 'نموذج إيجار')

    def test_full_facts_write_clean_text_without_placeholders(self):
        b = self.build(fake_ask())
        self.assertEqual(b['text'], GOOD_TEXT)
        self.assertNotIn('[يُكتب]', b['text'])
        self.assertEqual(b['unverified'], [])
        self.assertNotIn('عقد مؤرخ', b['text'])

    def test_without_contract_or_date_text_is_still_sound_and_missing_line_lists_them(self):
        facts = dict(FACTS, contract_date=None, object=None, amount=None, duration=None)
        text = ('جاءت المدعية بصحيفة مفادها أنها بصفتها مقاول من الباطن قامت بالتوريد، إلا أن المدعى عليها أخلّت '
                'بعدم سداد المستحقات المالية.')
        b = self.build(fake_ask(facts, text))
        self.assertEqual(b['text'], text)
        for label in ('تاريخ العقد', 'قيمة العقد', 'مدة العقد', 'محل العقد'):
            self.assertIn(label, b['absent'])
        self.assertNotIn('المطالبة', b['absent'])
        self.assertNotIn('[', b['text'])

    def test_unverified_date_is_dropped_and_reported_not_guessed(self):
        facts = dict(FACTS, contract_date='20/4/2018')                      # غير وارد في الصحيفة
        text = 'جاءت المدعية بصحيفة مفادها أنها قامت بالتوريد إلا أن المدعى عليها لم تسدد.'
        b = self.build(fake_ask(facts, text))
        self.assertIn('تاريخ العقد', b['unverified'])
        self.assertNotIn('20/04/2018', b['text'])
        self.assertNotIn('2018', b['text'])

    def test_no_unverified_number_in_output_falls_back_to_deterministic(self):
        bad = 'بموجب العقد المؤرخ 20/04/2018 مقابل مبلغ 9,999.000 د.ك لمدة 36 شهراً.'
        calls = []

        def ask(prompt):
            if 'نص الصحيفة:' in prompt:
                return json.dumps(FACTS, ensure_ascii=False)
            calls.append(prompt)
            return bad
        b = self.build(ask)
        self.assertEqual(len(calls), 2)                                      # المحاولة الثانية بطلب أشد
        self.assertIn('أرقاماً غير موجودة', calls[1])
        for n in ('9,999', '36', '20/04'):
            self.assertNotIn(n, b['text'])
        self.assertEqual(sa.unverified_numbers(b['text'], b['facts']), [])
        self.assertIn('19/04/2018', b['text'])

    def test_amount_mismatch_writes_neither_and_alerts_red(self):
        plaint = PLAINT.replace('5,876.540 د.ك (', '58760540 د.ك (', 1)
        facts = dict(FACTS, amount='58760540 د.ك (' + WORDS + ')')
        b = self.build(fake_ask(facts), plaint)
        self.assertIn('قيمة العقد', b['unverified'])
        self.assertTrue(any(a[0] == 'red' and '5,876.540' in a[1] for a in b['alerts']))
        self.assertNotIn('58760540', b['text'])

    def test_step_state_and_alert_line(self):
        base, data = cw.ensure_workspace(CASE, self.tmp.name)
        facts = dict(FACTS, contract_date='20/4/2018')
        text = 'جاءت المدعية بصحيفة مفادها أنها قامت بالتوريد إلا أن المدعى عليها لم تسدد.'
        row = {'defendants': ['فلان'], 'plaintiffs': ['شركة']}
        with mock.patch('case_subject_mission._default_get_case', lambda no: row):
            state = sm.run_subject(base, data, ask=fake_ask(facts, text), claim_fn=lambda: PLAINT)
        self.assertEqual(state, 'done')                 # ما كتبه البرنامج يُعدّ صحيحاً
        import doc_router
        alerts = doc_router.step_alerts(data, 'subject')
        self.assertTrue(any(lv == 'amber' and 'لم يُتحقق منه: تاريخ العقد' in t for lv, t in alerts))
        # لا «[يُكتب]» داخل النص
        self.assertNotIn(sm.st.TODO, data['subject'])
        # تعديل الخبير ينهي سطر النواقص
        sm.set_subject(base, data, text.replace('لم تسدد', 'لم تسدد المستحقات'))
        self.assertNotIn('subject_missing', data)

    def test_optional_absence_still_done(self):
        base, data = cw.ensure_workspace(CASE, self.tmp.name)
        facts = dict(FACTS, contract_date=None, contract_number=None, amount=None, duration=None, object=None)
        text = 'جاءت المدعية بصحيفة مفادها أنها قامت بالتوريد إلا أن المدعى عليها لم تسدد.'
        with mock.patch('case_subject_mission._default_get_case', lambda no: {'defendants': ['س']}):
            state = sm.run_subject(base, data, ask=fake_ask(facts, text), claim_fn=lambda: PLAINT)
        self.assertEqual(state, 'done')
        import doc_router
        lv = [x for x in doc_router.step_alerts(data, 'subject') if 'لم يرد' in x[1]]
        self.assertEqual(lv[0][0], 'amber')


class FastPathTests(StyleEnv):
    """طلب واحد (حقائق + نص) حين تتحقق كل الحقائق؛ وطلب ثانٍ عند أي رفض؛ ومهل قصيرة للنصوص."""

    def combined(self, facts, text, calls):
        def ask(prompt):
            calls.append(prompt)
            if 'نص الصحيفة:' in prompt:
                return json.dumps(dict(facts, text=text), ensure_ascii=False)
            return text
        return ask

    def test_single_call_when_everything_verified(self):
        calls = []
        b = sa.build_subject(PLAINT, ['شركة'], self.combined(FACTS, GOOD_TEXT, calls))
        self.assertEqual(len(calls), 1)
        self.assertTrue(b.get('fast'))
        self.assertEqual(b['text'], GOOD_TEXT)

    def test_second_call_when_a_fact_was_rejected(self):
        calls = []
        facts = dict(FACTS, contract_date='20/4/2018')
        safe = 'جاءت المدعية بصحيفة مفادها أنها قامت بالتوريد إلا أن المدعى عليها لم تسدد.'
        b = sa.build_subject(PLAINT, ['شركة'], self.combined(facts, 'بموجب العقد المؤرخ 20/04/2018 ' + safe, calls))
        self.assertGreaterEqual(len(calls), 2)
        self.assertNotIn('20/04/2018', b['text'])
        self.assertIn('تاريخ العقد', b['unverified'])

    def test_second_call_when_fast_text_has_unverified_number(self):
        calls = []
        b = sa.build_subject(PLAINT, ['شركة'], self.combined(FACTS, 'مقابل مبلغ 9,999.000 د.ك لمدة 36 شهراً', calls))
        self.assertGreaterEqual(len(calls), 2)
        self.assertNotIn('9,999', b['text'])

    def test_short_timeouts_and_status_text(self):
        import case_research as cr
        self.assertEqual(cr.SHORT_TIMEOUTS['الموضوع'], 60)
        self.assertLess(cr.SHORT_TIMEOUTS['الموضوع'], cr.TIMEOUT)
        captured = {}

        def fake_chain(call, size, timeout, **kw):
            captured['t'] = timeout
            return mock.Mock(text='x', provider='p')
        with mock.patch('ai_providers.run_chain', fake_chain),                 mock.patch('ai_providers.build_task_chain', lambda *a, **k: []):
            cr.default_ask('p', 'write', timeout=cr.SHORT_TIMEOUTS['الموضوع'])
            self.assertEqual(captured['t'], 60)
            cr.default_ask('p', 'research')
            self.assertEqual(captured['t'], cr.TIMEOUT)
        track = open(os.path.join(HERE, 'qt_case_track.py'), encoding='utf-8').read()
        self.assertIn('"جارٍ كتابة الموضوع', track)


class QuestionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base, self.data = cw.ensure_workspace(CASE, self.tmp.name)
        self.data['subject'] = 'جاءت المدعية بصحيفة مفادها كذا'
        self.data['mission'] = {'raw': 'x', 'confirmed': True, 'next_id': 3, 'points': [
            {'id': 'q1', 'n': 1, 'text': 'طلب العقد المبرم بين الطرفين لبيان طبيعة العلاقة'},
            {'id': 'q2', 'n': 2, 'text': 'بيان المبلغ المستحق'}]}
        self.reply = {
            'expert_tasks': [{'text': 'مطالعة ملف الدعوى', 'point': 1}, {'text': 'الانتقال لمعاينة موقع المشروع', 'point': 2}],
            'party_requests': [
                {'to': 'المدعية', 'text': 'تكليف المدعية بتقديم العقد المبرم بين الطرفين، وذلك لبيان طبيعة العلاقة بينهما', 'point': 1},
                {'to': 'المدعية', 'text': 'كشف الحساب وإيصالات السداد وبيان كيفية احتساب المبلغ المطالب به', 'point': 2},
                {'to': 'المدعى عليه', 'text': 'تكليف المدعى عليه بتقديم ملف الدعوى الأصلي', 'point': 1},
                {'to': 'المدعى عليه', 'text': 'تقديم أوراق الدعوى كاملة', 'point': 1}]}

    def gen(self):
        return cq.generate(self.base, self.data, lambda p: json.dumps(self.reply, ensure_ascii=False))

    def test_two_lists_concise_and_no_case_file_requested(self):
        self.gen()
        experts, parties = cq.split(self.data)
        self.assertEqual([q['text'] for q in experts], ['مطالعة ملف الدعوى', 'الانتقال لمعاينة موقع المشروع'])
        self.assertEqual([q['to'] for q in experts], ['الخبير', 'الخبير'])
        texts = [q['text'] for q in parties]
        self.assertEqual(texts[0], 'تكليف المدعية بتقديم العقد المبرم بين الطرفين')        # بلا تعليل
        self.assertEqual(texts[1], 'تكليف المدعية بتقديم كشف الحساب وإيصالات السداد وبيان كيفية احتساب المبلغ المطالب به')
        self.assertEqual(len(parties), 2)                                                  # ملف الدعوى لم يُطلب من الخصوم
        self.assertFalse(any('ملف' in t and 'الدعوى' in t for t in texts))
        self.assertEqual([q['point_n'] for q in parties], [1, 2])
        self.assertTrue(all(q['status'] == 'open' for q in experts + parties))

    def test_prompt_starts_from_mission_points_and_readiness_needs(self):
        self.data['readiness'] = {'items': [{'id': 'q2', 'n': 2, 'requirements': [
            {'key': 'k_stmt', 'need': 'كشف الحساب', 'to': 'المدعية', 'found': None}]}]}
        p = cq.build_prompt(self.data, cq.open_needs(self.data))
        self.assertIn('طلب العقد المبرم بين الطرفين لبيان طبيعة العلاقة', p)
        self.assertIn('key=k_stmt', p)
        self.assertIn('ممنوع أن تطلب من الخصوم ملف الدعوى', p)

    def test_key_links_to_readiness_so_it_closes_when_satisfied(self):
        import case_readiness as cr
        self.data['readiness'] = {'items': [{'id': 'q2', 'n': 2, 'requirements': [
            {'key': 'k_stmt', 'need': 'كشف الحساب', 'to': 'المدعية', 'found': None}]}]}
        self.reply['party_requests'][1]['key'] = 'k_stmt'
        self.gen()
        qid = cr._qid('q2', 'k_stmt')
        q = next(x for x in self.data['questions'] if x['id'] == qid)
        self.assertEqual(q['need'], 'كشف الحساب')
        # سُدّ المتطلب ← sync يغلقه
        res = [{'id': 'q2', 'n': 2, 'requirements': [{'key': 'k_stmt', 'need': 'كشف الحساب', 'to': 'المدعية',
                                                      'why': '', 'found': {'x': 1}, 'where': 'P1-1'}]}]
        cr.sync_questions(self.data, res, self.data['mission']['points'])
        self.assertEqual(q['status'], 'closed')

    def test_regenerate_keeps_manual_and_closed_and_drops_stale_open(self):
        self.gen()
        qs = self.data['questions']
        qs.append({'id': 'm9', 'text': 'سؤال يدوي', 'status': 'open', 'auto': False})
        closed = next(q for q in qs if q['kind'] == 'party')
        closed['status'] = 'closed'
        self.reply = {'expert_tasks': [{'text': 'مطالعة ملف الدعوى', 'point': 1}], 'party_requests': []}
        self.gen()
        ids = {q['id'] for q in self.data['questions']}
        self.assertIn('m9', ids)
        self.assertIn(closed['id'], ids)
        self.assertEqual(len([q for q in self.data['questions'] if q.get('ai') and q['status'] == 'open']), 1)

    def test_written_by_recorded_and_no_mission_error(self):
        import ai_call_log
        def inner(prompt):
            ai_call_log.set_provider('Gemini', 'gemini-x')            # كما يفعل case_research.default_ask
            return json.dumps(self.reply, ensure_ascii=False)
        ask = ai_call_log.wrap(inner, 'الأسئلة المهمة')
        cq.generate(self.base, self.data, ask)
        self.assertEqual(self.data['written_by']['questions']['provider'], 'Gemini')
        empty = dict(self.data, mission={})
        with self.assertRaises(cm.StepError):
            cq.generate(self.base, empty, ask)

    def test_dialog_has_two_wrapping_tables_with_five_columns_no_horizontal_scroll(self):
        self.gen()
        d = qp.QuestionsDialog(self.base, self.data, None)
        d.resize(760, 560)
        d.show()
        APP.processEvents()
        self.assertEqual(d.table_expert.columnCount(), 5)
        self.assertEqual([d.table_party.horizontalHeaderItem(i).text() for i in range(5)],
                         ['م', 'الموجَّه إليه', 'المطلوب', 'البند', 'الحالة'])
        self.assertEqual(d.table_party.rowCount(), 2)
        self.assertEqual(d.table_party.item(0, 1).text(), 'المدعية')
        self.assertTrue(d.table_party.wordWrap())
        from PyQt6.QtCore import Qt
        self.assertEqual(d.table_party.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertFalse(d.table_party.horizontalScrollBar().isVisible())
        long_row = d.table_party.rowHeight(1)
        self.assertGreater(long_row, d.table_party.rowHeight(0) - 1)                      # السطر الطويل يلتف فيعلو الصف
        html = cq.questions_html(self.data)
        self.assertIn('مهام الخبير', html)
        self.assertIn('طلبات للخصوم', html)
        self.assertIn('تكليف المدعية بتقديم العقد المبرم بين الطرفين', html)
        d.close()

    def test_empty_lists_show_clear_message(self):
        d = qp.QuestionsDialog(self.base, self.data, None)
        self.assertIn('لا طلبات للخصوم', d.empty_party.text())
        self.assertIn('لا مهام للخبير', d.empty_expert.text())

    def test_manual_add_to_either_list(self):
        d = qp.QuestionsDialog(self.base, self.data, None)
        d.edit.setText('سؤال يدوي')
        d.kind_box.setCurrentIndex(1)
        d._add()
        self.assertEqual(d.table_expert.rowCount(), 1)
        self.assertEqual(d.table_expert.item(0, 1).text(), 'الخبير')

    def test_dialog_generates_with_ask_in_background(self):
        import time
        ask = lambda p: json.dumps(self.reply, ensure_ascii=False)              # noqa: E731
        d = qp.QuestionsDialog(self.base, self.data, None, ask=ask)
        for _ in range(100):
            APP.processEvents()
            if d.table_party.rowCount():
                break
            time.sleep(0.05)
        self.assertEqual(d.table_party.rowCount(), 2)
        self.assertEqual(d.table_expert.rowCount(), 2)


class HonestCheckAndReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base, self.data = cw.ensure_workspace(CASE, self.tmp.name)

    def disp(self, data, key):
        return {k: s for k, _n, s, _m in rlm.step_states(data)[0]}[key]

    def test_check_hidden_when_gaps_exist(self):
        d = self.data
        for k in ('subject', 'procedures'):
            d['steps'][k]['state'] = 'reviewed'
        d['subject'] = 'موضوع سليم'
        d['procedures'] = {'text': 'استلمنا الملف وحددنا عدة جلسات [ناقص: الحضور — ينقص محضر]'}
        self.assertEqual(self.disp(d, 'subject'), rlm.ST_DONE)
        self.assertEqual(self.disp(d, 'procedures'), rlm.ST_INPUT)               # علامة [ناقص] ← لا ✓
        d['subject'] = 'موضوع [يُكتب]'
        self.assertEqual(self.disp(d, 'subject'), rlm.ST_INPUT)
        d['subject'] = 'موضوع سليم'
        d['engines'] = {'claim': {'engine': 'local', 'skipped': []}}              # تنبيه أحمر للمحرك
        self.assertEqual(self.disp(d, 'subject'), rlm.ST_INPUT)
        d['engines'] = {}
        d['subject_missing'] = {'unverified': ['تاريخ العقد'], 'absent': []}   # تنبيه بسيط لا يحجب
        self.assertEqual(self.disp(d, 'subject'), rlm.ST_DONE)

    def test_attachments_not_complete_until_minutes_and_portfolios_complete(self):
        d = self.data
        d['steps']['attachments']['state'] = 'done'
        self.assertEqual(self.disp(d, 'attachments'), rlm.ST_INPUT)
        d['steps']['procedures']['state'] = 'reviewed'
        d['steps']['documents']['state'] = 'reviewed'
        d['sessions'] = {'source': 'live', 'expected_minutes': 2, 'minutes': [{'no': 1}], 'missing_count': 1}
        self.assertEqual(self.disp(d, 'attachments'), rlm.ST_DONE)                # نقص محضر ملاحظة فقط
        d['sessions'] = {'source': 'live', 'expected_minutes': 1, 'minutes': [{'no': 1}], 'missing_count': 0}
        self.assertEqual(self.disp(d, 'attachments'), rlm.ST_DONE)
        d['steps']['documents']['state'] = 'failed'
        self.assertEqual(self.disp(d, 'attachments'), rlm.ST_INPUT)

    def test_report_button_never_changes_any_state(self):
        qp.CasePageDialog.AUTO_PROCEDURES = False
        dlg = qp.CasePageDialog(self.base, cw.read_case_json(self.base))
        dlg.data['subject'] = 'موضوع كامل'
        dlg.data['steps']['subject']['state'] = 'done'                            # كان سيُعتمد تلقائياً عند أي reload
        cw.write_case_json(self.base, dlg.data)
        before = json.dumps({k: v['state'] for k, v in dlg.data['steps'].items()})
        with mock.patch('report_docx.gather_info', lambda d, c: {}), \
                mock.patch('qt_case_track.QMessageBox.information'), mock.patch('os.startfile', create=True):
            dlg._do_report()
            import time
            for _ in range(200):
                APP.processEvents()
                if not dlg._busy:
                    break
                time.sleep(0.05)
        after = json.dumps({k: v['state'] for k, v in cw.read_case_json(self.base)['steps'].items()})
        self.assertEqual(before, after)
        self.assertEqual(cw.read_case_json(self.base)['steps']['subject']['state'], 'done')


class UiStyleTests(unittest.TestCase):
    def test_title_and_buttons(self):
        import qt_theme as th
        import qt_expert_reports as er
        src_text = open(os.path.join(HERE, 'qt_expert_reports.py'), encoding='utf-8').read()
        self.assertIn('منصة إنشاء التقارير', src_text)
        self.assertNotIn('تقارير الخبراء القضائيين', src_text)
        qss = th.secondary_button_style()
        self.assertIn('#386380', qss)
        self.assertIn(th.NAVY, qss)
        self.assertNotIn('background: transparent', qss.split('QPushButton:hover')[0])
        b = qp._btn('ثانوي')
        self.assertIn('#386380', b.styleSheet())
        self.assertIn(th.BTN2_BG, b.styleSheet())
        p = qp._btn('رئيسي', True)
        self.assertIn(f'background:{qp.NAVY}', p.styleSheet())
        self.assertTrue(hasattr(er, 'ExpertReportsPage'))


if __name__ == '__main__':
    unittest.main()
