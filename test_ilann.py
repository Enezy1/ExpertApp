# -*- coding: utf-8 -*-
"""
test_ilann.py — اختبارات وحدة «طلب الإعلان» (ilann.py).

كل الاختبارات بدون شبكة (offline): نتحقق من تحليل صفحة الطلب ونموذج الطرف،
وبناء الـ payload، وحماية «ما يرسل إلا بإذن»، وتوليد ملف Word.

الملفات المجمّدة (test_data/ilann/) لقطة حقيقية من نظام الخبراء 12/11/2026 —
ما فيه أي اختبار يرسل بيانات للنظام الحقيقي.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ilann

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_data', 'ilann')


def _read(name):
    with open(os.path.join(DATA, name), encoding='utf-8', errors='ignore') as f:
        return f.read()


class FixtureTests(unittest.TestCase):
    """الملفات المجمّدة موجودة وتقرأ بنجاح"""

    def test_fixtures_exist(self):
        for n in ('meeting_inform.html', 'party_form.html', 'meeting_inform_empty.html'):
            self.assertTrue(os.path.exists(os.path.join(DATA, n)), n)
            self.assertGreater(len(_read(n)), 500, n)


class CaseInfoTests(unittest.TestCase):
    def test_parses_case_fields(self):
        info = ilann.parse_case_info(_read('meeting_inform.html'))
        self.assertEqual(info.get('الرقم الالى'), '260668600')
        self.assertEqual(info.get('رقم القضيه'), '26001611')
        self.assertEqual(info.get('رقم الخبرة'), 'A2264212')
        self.assertEqual(info.get('الجهه'), 'الأحمدى')
        self.assertEqual(info.get('امانه الخبير'), '50')

    def test_case_field_helper(self):
        info = ilann.parse_case_info(_read('meeting_inform.html'))
        self.assertEqual(ilann.case_field(info, 'auto_no'), '260668600')
        self.assertEqual(ilann.case_field(info, 'expert_no'), 'A2264212')
        self.assertEqual(ilann.case_field(info, 'expert_trust'), '50')
        self.assertEqual(ilann.case_field(info, 'nope', '-'), '-')


class PartiesTests(unittest.TestCase):
    def setUp(self):
        self.parties = ilann.parse_parties(_read('meeting_inform.html'))

    def test_two_parties(self):
        self.assertEqual(len(self.parties), 2)

    def test_party_fields_and_part_id(self):
        p = self.parties[0]
        self.assertEqual(p['part_id'], '160801')
        self.assertIn('شركه الاتصالات', p['name'])
        self.assertEqual(p['type'], 'مدعى')
        self.assertEqual(self.parties[1]['part_id'], '380068')
        self.assertEqual(self.parties[1]['type'], 'مدعي عليه')


class PartiesDuplicateTests(unittest.TestCase):
    """تكرار الأطراف بعد إرسال إعلان (15/11/2026).

    صفحة الطلب فيها **جدولين**: «الاطراف» و«نتيجه الاعلان» — وصفوف الثاني
    تبدأ باسم الطرف وبعمود «وسيله الاعلان» (مندوب/رسائل/هاتف…). فلو قُرئت
    مع جدول الأطراف ⟵ يتكرّر نفس الشخص مرتين: سطر «مدعى عليه» وسطر «مندوب».
    """

    HTML = """
    <table class="table table-striped table-bordered table-hover">
      <thead class="thead-dark"><tr>
        <th>الاسم</th><th>نوع الطرف</th><th>العنوان</th>
      </tr></thead>
      <tbody>
        <tr onclick="showadd('160801')"><td>شركه الاتصالات المتنقله ش م ك</td>
            <td>مدعى</td>
            <td><button type="button" onclick="showadd('160801')">&#9660;</button></td></tr>
        <tr onclick="showadd('380068')"><td>عبد الهادى محمد على المرى</td>
            <td>مدعي عليه</td>
            <td><button type="button" onclick="showadd('380068')">&#9660;</button></td></tr>
      </tbody>
    </table>
    <table class="table table-striped table-bordered table-hover">
      <thead class="thead-dark"><tr>
        <th>الاسم</th><th>وسيله الاعلان</th><th>تاريخ الاعلان</th>
        <th>تاريخ الجلسه</th><th>حاله الاعلان</th><th>سبب التعذر</th>
      </tr></thead>
      <tbody>
        <tr><td>عبد الهادى محمد على المرى</td><td>مندوب</td><td>15/11/2026</td>
            <td>09/12/2026</td><td>تم</td><td>-</td></tr>
      </tbody>
    </table>"""

    def test_result_row_is_not_a_party(self):
        parties = ilann.parse_parties(self.HTML)
        self.assertEqual(len(parties), 2)
        self.assertEqual([p['type'] for p in parties], ['مدعى', 'مدعي عليه'])

    def test_no_duplicated_party_name(self):
        names = [p['name'] for p in ilann.parse_parties(self.HTML)]
        self.assertEqual(len(names), len(set(names)), names)

    def test_parties_keep_part_id(self):
        parties = ilann.parse_parties(self.HTML)
        self.assertEqual(parties[0]['part_id'], '160801')
        self.assertEqual(parties[1]['part_id'], '380068')

    def test_results_table_still_parsed(self):
        rows = ilann.parse_results(self.HTML)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['means'], 'مندوب')
        self.assertEqual(rows[0]['status'], 'تم')
        self.assertEqual(rows[0]['name'], 'عبد الهادى محمد على المرى')

    def test_frozen_page_still_two_parties(self):
        self.assertEqual(len(ilann.parse_parties(_read('meeting_inform.html'))), 2)

    def test_page_with_only_results_gives_no_parties(self):
        only_results = self.HTML.split('</table>')[1] + '</table>'
        self.assertEqual(ilann.parse_parties(only_results), [])

    def test_fallback_when_header_text_changed(self):
        """لو غيّر الموقع نص الرأس — نرجع لزرّ الطرف (showadd) بدل ما نفقد الأطراف."""
        html = self.HTML.replace('<th>نوع الطرف</th>', '<th>صفة الخصم</th>')
        parties = ilann.parse_parties(html)
        self.assertEqual(len(parties), 2)
        self.assertEqual(parties[0]['part_id'], '160801')


class ResultsTests(unittest.TestCase):
    def test_empty_table_gives_no_rows(self):
        self.assertEqual(ilann.parse_results(_read('meeting_inform.html')), [])

    def test_reads_rows(self):
        html = """
        <table><thead><tr><th>الاسم</th><th>وسيله الاعلان</th><th>تاريخ الاعلان</th>
        <th>تاريخ الجلسه</th><th>حاله الاعلان</th><th>سبب التعذر</th></tr></thead>
        <tbody>
          <tr><td>شركه الاتصالات</td><td>رسائل</td><td>20/10/2020</td>
              <td>28/10/2020</td><td>تم</td><td>-</td></tr>
          <tr><td>عبد الهادى</td><td>هاتف</td><td>20/10/2020</td>
              <td>28/10/2020</td><td>تعذر</td><td>لا يوجد هاتف</td></tr>
        </tbody></table>"""
        rows = ilann.parse_results(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['means'], 'رسائل')
        self.assertEqual(rows[0]['status'], 'تم')
        self.assertEqual(rows[1]['reason'], 'لا يوجد هاتف')


class PartyFormTests(unittest.TestCase):
    def setUp(self):
        self.form = ilann.parse_party_form(_read('party_form.html'))

    def test_hidden_ids(self):
        self.assertEqual(self.form['part_id'], '160801')
        self.assertEqual(self.form['cnt_seq'], '160799')

    def test_contact_method(self):
        self.assertEqual(self.form['contact_code'], '10001')
        self.assertEqual(self.form['contact_label'], 'مندوب')

    def test_address_values(self):
        f = self.form['fields']
        self.assertEqual(f.get('ADRS_BLOCK'), '5')
        self.assertEqual(f.get('ADRS_STREET'), 'احمد الجابر')
        self.assertEqual(f.get('ADRS_UNIT_TYPE'), 'دور')
        self.assertEqual(f.get('ADRS_FLOOR'), '10')
        self.assertEqual(f.get('ADRS_UNIT_NO'), '23')
        self.assertEqual(f.get('ADRS_CITY'), '1')
        self.assertEqual(f.get('ADRS_ZONE'), '102')

    def test_options_lists(self):
        self.assertGreaterEqual(len(self.form['methods']), 6)
        self.assertGreaterEqual(len(self.form['cities']), 6)
        self.assertGreater(len(self.form['zones']), 50)
        self.assertEqual(self.form['cities'][0], ('1', 'محافظه العاصمه'))


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.form = ilann.parse_party_form(_read('party_form.html'))

    def test_all_fields_present(self):
        p = ilann.build_payload(self.form, {})
        for k in ('MAIN_CNTD_CODE_NEW', 'MAIN_CNTD_TYPE_DESC', 'ADRS_CITY', 'ADRS_ZONE',
                  'ADRS_KASIMA', 'ADRS_BLOCK', 'ADRS_STREET', 'ADRS_UNIT_TYPE',
                  'ADRS_DESCR', 'ADRS_BUILDING_NO', 'ADRS_FLOOR', 'ADRS_UNIT_NO',
                  'ADDRNO', 'EIF_NOTE', 'part_id', 'CNT_SEQ'):
            self.assertIn(k, p)
        self.assertEqual(p['part_id'], '160801')
        self.assertEqual(p['CNT_SEQ'], '160799')

    def test_keeps_form_values_when_not_overridden(self):
        p = ilann.build_payload(self.form, {})
        self.assertEqual(p['ADRS_STREET'], 'احمد الجابر')
        self.assertEqual(p['ADRS_CITY'], '1')

    def test_overrides_win(self):
        p = ilann.build_payload(self.form, {'ADRS_STREET': 'شارع جديد', 'ADDRNO': '9655555'})
        self.assertEqual(p['ADRS_STREET'], 'شارع جديد')
        self.assertEqual(p['ADDRNO'], '9655555')

    def test_contact_label_follows_code(self):
        p = ilann.build_payload(self.form, {'MAIN_CNTD_CODE_NEW': '10003'})
        self.assertEqual(p['MAIN_CNTD_CODE'], 'بريد مسجل')
        self.assertEqual(p['MAIN_CNTD_CODE_NEW'], '10003')


class SendTests(unittest.TestCase):
    """حماية: ما يرسل شي إلا بعد إذن صريح (dry_run=False)"""

    def setUp(self):
        self.form = ilann.parse_party_form(_read('party_form.html'))
        self.payload = ilann.build_payload(self.form, {})
        # سجل التشخيص يروح لمجلد مؤقت — ما نلوّث سجل المستخدم
        self._old_local = os.environ.get('LOCALAPPDATA')
        os.environ['LOCALAPPDATA'] = tempfile.mkdtemp(prefix='ilann-test-')
        self.addCleanup(self._restore_local)

    def _restore_local(self):
        if self._old_local is None:
            os.environ.pop('LOCALAPPDATA', None)
        else:
            os.environ['LOCALAPPDATA'] = self._old_local

    def test_dry_run_does_not_post(self):
        posted = []

        def fake_post(url, data=None, cookies=None, **kw):
            posted.append((url, data))
            raise AssertionError('ما ينفع يرسل وقت dry_run')

        import requests as _rq
        old = _rq.post
        _rq.post = fake_post
        try:
            res = ilann.send_inform({}, self.payload)
        finally:
            _rq.post = old
        self.assertFalse(posted)
        self.assertEqual(res['code'], 'dry_run')
        self.assertFalse(res['ok'])
        self.assertEqual(res['payload']['part_id'], '160801')

    def test_missing_part_id_blocks_send(self):
        res = ilann.send_inform({}, {'part_id': ''}, dry_run=False)
        self.assertFalse(res['ok'])
        self.assertEqual(res['code'], 'x')

    def test_real_send_posts_to_right_endpoint(self):
        calls = {}

        class Resp:
            text = '1'

        def fake_post(url, data=None, cookies=None, **kw):
            calls['url'] = url
            calls['data'] = data
            return Resp()

        import requests as _rq
        old = _rq.post
        _rq.post = fake_post
        try:
            res = ilann.send_inform({}, self.payload, dry_run=False)
        finally:
            _rq.post = old
        self.assertTrue(calls['url'].endswith('/includes/insert_inform_detail.php'))
        self.assertEqual(calls['data']['part_id'], '160801')
        self.assertTrue(res['ok'])
        self.assertEqual(res['message'], 'تم حفظ الاعلان بنجاح')

    def test_reply_codes_mapped(self):
        for code, ok, msg in (('1', True, 'تم حفظ الاعلان بنجاح'),
                              ('3', False, 'يوجد اعلان سابق لنفس الطرف فى نفس الجلسه'),
                              ('4', False, 'لا يجوز ادخال اعلان لجلسه سابقه')):
            class Resp:
                text = code

            def fake_post(url, data=None, cookies=None, **kw):
                return Resp()

            import requests as _rq
            old = _rq.post
            _rq.post = fake_post
            try:
                res = ilann.send_inform({}, self.payload, dry_run=False)
            finally:
                _rq.post = old
            self.assertEqual(res['code'], code)
            self.assertEqual(res['ok'], ok)
            self.assertEqual(res['message'], msg)


class FieldLimitsTests(unittest.TestCase):
    """حدود الحقول — SIRVER يرفض القيمة الطويلة بـORA-12899 (15/11/2026).

    الموقع يقصّ الحقل في المتصفح (`maxlength`) — ونحاكي نفس السلوك.
    """

    def setUp(self):
        self.form = ilann.parse_party_form(_read('party_form.html'))

    def test_limits_read_from_the_form(self):
        limits = self.form.get('limits') or {}
        self.assertEqual(limits.get('ADRS_BUILDING_NO'), 5)
        self.assertEqual(limits.get('ADRS_KASIMA'), 10)
        self.assertEqual(limits.get('ADRS_BLOCK'), 4)
        self.assertEqual(limits.get('ADDRNO'), 12)
        self.assertEqual(limits.get('EIF_NOTE'), 150)

    def test_payload_truncates_long_values(self):
        values = {'ADRS_BUILDING_NO': 'برج برايم الطويل',   # 16 حرف
                  'ADRS_KASIMA': 'طريق طويل جداً جداً',          # 18 حرف
                  'ADDRNO': '999999999999999'}                  # 15 حرف
        p = ilann.build_payload(self.form, values)
        self.assertEqual(len(p['ADRS_BUILDING_NO']), 5)
        self.assertEqual(len(p['ADRS_KASIMA']), 10)
        self.assertEqual(len(p['ADDRNO']), 12)

    def test_short_values_untouched(self):
        p = ilann.build_payload(self.form, {'ADRS_BUILDING_NO': '36'})
        self.assertEqual(p['ADRS_BUILDING_NO'], '36')

    def test_truncate_helper(self):
        self.assertEqual(ilann.truncate_field('ADRS_BUILDING_NO', 'abcdefgh'),
                         'abcde')
        self.assertEqual(ilann.truncate_field('ADRS_BUILDING_NO', 'abc'), 'abc')
        self.assertEqual(ilann.truncate_field('ADRS_DESCR', 'x' * 90), 'x' * 90)

    def test_limit_helper(self):
        self.assertEqual(ilann.field_limit('ADRS_BUILDING_NO',
                                           self.form.get('limits')), 5)
        self.assertEqual(ilann.field_limit('ADRS_FLOOR', {}), 5)
        self.assertIsNone(ilann.field_limit('ADRS_DESCR', {}))


class OraTooLongTests(unittest.TestCase):
    """رد ORA-12899 ⟵ رسالة واضحة: أي حقل وكم حرف وكم يسمح."""

    ORA = ('<br /> <b>Warning</b>:  oci_execute(): ORA-12899: value too large for '
           'column &quot;EXPRT&quot;.&quot;CONTACTS_ADRS&quot;.&quot;ADRS_BUILDING_NO&quot; '
           '(actual: 9, maximum: 5) in '
           '<b>C:\\Apache24\\htdocs\\includes\\insert_inform_detail.php</b> on line '
           '<b>126</b><br /> 21')

    def test_detect_column_and_lengths(self):
        got = ilann._too_long_field(self.ORA)
        self.assertIsNotNone(got)
        self.assertEqual(got[0], 'ADRS_BUILDING_NO')
        self.assertEqual(got[1], '9')
        self.assertEqual(got[2], '5')

    def test_generic_ora_detection(self):
        got = ilann._ora_error(
            'ORA-01400: ORA-01400: cannot insert NULL into ("EXPRT"."CONTACTS_ADRS"."ADDRNO")')
        self.assertIsNotNone(got)
        self.assertEqual(got[0], 'ORA-01400')
        self.assertIn('فاضي', got[1])

    def test_no_ora_means_none(self):
        self.assertIsNone(ilann._ora_error('1'))
        self.assertIsNone(ilann._ora_error(''))

    def test_send_reports_too_long(self):
        class Resp:
            text = OraTooLongTests.ORA
            status_code = 200

        def fake_post(url, data=None, cookies=None, **kw):
            return Resp()

        import requests as _rq
        old = _rq.post
        _rq.post = fake_post
        logged = []
        old_log = ilann._log_send
        ilann._log_send = lambda e: logged.append(e)
        try:
            form = ilann.parse_party_form(_read('party_form.html'))
            payload = ilann.build_payload(form, {})
            res = ilann.send_inform({}, payload, dry_run=False, caso_no='A2264206',
                                    session_date='2026/11/19', session_time='10:30')
        finally:
            _rq.post = old
            ilann._log_send = old_log
        self.assertFalse(res['ok'])
        self.assertEqual(res['code'], 'too_long')
        self.assertIn('المبنى', res['message'])
        self.assertIn('5', res['message'])
        self.assertTrue(logged)


class MeetingDateFormatTests(unittest.TestCase):
    """صيغة تاريخ الجلسة — يyyy/mm/dd فقط هي اللي يقبلها السيرفر (15/11/2026)."""

    def test_calendar_format_is_kept(self):
        self.assertEqual(ilann.normalize_meeting_date('2026/11/17'), '2026/11/17')

    def test_iso_is_converted(self):
        self.assertEqual(ilann.normalize_meeting_date('2026-11-17'), '2026/11/17')

    def test_day_first_is_converted(self):
        self.assertEqual(ilann.normalize_meeting_date('17/11/2026'), '2026/11/17')

    def test_oracle_is_converted(self):
        self.assertEqual(ilann.normalize_meeting_date('17-NOV-26'), '2026/11/17')

    def test_with_time_part(self):
        self.assertEqual(ilann.normalize_meeting_date('2026/11/17 10:00'), '2026/11/17')

    def test_empty(self):
        self.assertEqual(ilann.normalize_meeting_date(''), '')
        self.assertEqual(ilann.normalize_meeting_date(None), '')

    def test_time_normalization(self):
        self.assertEqual(ilann.normalize_meeting_time('10:00'), '10:00')
        self.assertEqual(ilann.normalize_meeting_time('9:05'), '09:05')
        self.assertEqual(ilann.normalize_meeting_time('10:00:00'), '10:00')
        self.assertEqual(ilann.normalize_meeting_time(''), '')


class MeetingContextTests(unittest.TestCase):
    """سياق الجلسة — سبب فشل «طلب إعلان» الحقيقي (15/11/2026).

    السبب الجذري (مقاس على السيرفر الحقيقي — رسائل PHP):
      • `insert_inform_detail.php` يقرأ من **جلسة السيرفر**:
        ECS_IN_REGNO_INFO (سطر 51) · ECS_MET_DATE (سطر 134) · ECS_MET_TIME (سطر 138)
      • `basic_info_result.php` (سطر 21-22) هو اللي يكتب التاريخ والوقت في الجلسة
        من `met_date` / `met_time`.
      • البرنامج كان يرسل `met_date=''` `met_time=''` ⟵ الجلسة بلا تاريخ جلسة
        ⟵ السيرفر يرد «4» (لا يجوز ادخال اعلان لجلسه سابقه) — حتى لو الجلسة قادمة.
    """

    def _capture(self, reply='1'):
        calls = []

        class Resp:
            text = reply

        def fake_post(url, data=None, cookies=None, **kw):
            calls.append((url, data or {}))
            return Resp()

        import requests as _rq
        old = _rq.post
        _rq.post = fake_post
        self.addCleanup(lambda: setattr(_rq, 'post', old))
        return calls

    def test_context_is_set_before_the_send(self):
        calls = self._capture()
        form = ilann.parse_party_form(_read('party_form.html'))
        payload = ilann.build_payload(form, {})
        res = ilann.send_inform({}, payload, dry_run=False, caso_no='A2264185',
                                auto_no='262461650', session_date='2026/11/20',
                                session_time='10:30')
        self.assertTrue(res['ok'])
        # أول طلب = ضبط سياق الجلسة (رقم الخبرة + تاريخ الجلسة + وقتها)
        self.assertTrue(calls[0][0].endswith('/includes/basic_info_result.php'))
        self.assertEqual(calls[0][1]['met_date'], '2026/11/20')
        self.assertEqual(calls[0][1]['met_time'], '10:30')
        self.assertEqual(calls[0][1]['description'], 'A2264185')
        self.assertEqual(calls[0][1]['title'], 'A2264185')
        # ثاني طلب = إعادة تحديد القضية (نفس «الملف الآلي» بالموقع)
        self.assertTrue(calls[1][0].endswith('/includes/insert_showimg.php'))
        self.assertEqual(calls[1][1]['task_id'], 'A2264185')
        # آخر طلب = نقطة الإرسال
        self.assertTrue(calls[-1][0].endswith('/includes/insert_inform_detail.php'))

    def test_context_is_set_even_without_a_case_number(self):
        """حتى بلا رقم خبرة نرسل التاريخ (لو موجود) — الجلسة هي المرجع."""
        calls = self._capture()
        form = ilann.parse_party_form(_read('party_form.html'))
        payload = ilann.build_payload(form, {})
        ilann.send_inform({}, payload, dry_run=False, session_date='2026/11/20',
                          session_time='10:30')
        self.assertTrue(calls[0][0].endswith('/includes/basic_info_result.php'))
        self.assertEqual(calls[0][1]['met_date'], '2026/11/20')

    def test_no_context_call_without_session_date(self):
        """بدون تاريخ جلسة: ما نرسلش طلب ضبط السياق (ما عندنا قيمة نرسلها)."""
        calls = self._capture()
        form = ilann.parse_party_form(_read('party_form.html'))
        payload = ilann.build_payload(form, {})
        ilann.send_inform({}, payload, dry_run=False, caso_no='A2264185')
        self.assertFalse(any('basic_info_result' in u for u, _ in calls))

    def test_parse_reply_with_php_notices(self):
        """رد فيه تحذيرات PHP قبل الكود ⟵ الكود هو آخر سطر."""
        raw = ('Notice: Undefined index: ECS_MET_DATE in insert_inform_detail.php '
               'on line 134\n\nNotice: Undefined index: ECS_MET_TIME on line 138\n4')
        code, out = ilann._parse_send_response(raw)
        self.assertEqual(code, '4')
        self.assertEqual(out, raw)

    def test_parse_reply_plain_and_html(self):
        self.assertEqual(ilann._parse_send_response('1')[0], '1')
        self.assertEqual(ilann._parse_send_response('<b>1</b>')[0], '1')
        self.assertEqual(ilann._parse_send_response('')[0], '')
        self.assertEqual(ilann._parse_send_response(' boom ')[0], '')

    def test_unknown_reply_is_reported_as_unknown(self):
        calls = self._capture(reply='<b>Warning</b>: something went wrong')
        form = ilann.parse_party_form(_read('party_form.html'))
        payload = ilann.build_payload(form, {})
        res = ilann.send_inform({}, payload, dry_run=False, caso_no='A2264185',
                                session_date='2026/11/20')
        self.assertFalse(res['ok'])
        self.assertEqual(res['code'], 'unknown')
        self.assertTrue(res['raw'])

    def test_send_failure_is_logged(self):
        calls = self._capture(reply='4')
        form = ilann.parse_party_form(_read('party_form.html'))
        payload = ilann.build_payload(form, {})
        logged = []
        old_log = ilann._log_send
        ilann._log_send = lambda entry: logged.append(entry)
        try:
            ilann.send_inform({}, payload, dry_run=False, caso_no='A2264185',
                              session_date='2026/11/20', session_time='10:30')
        finally:
            ilann._log_send = old_log
        self.assertTrue(logged)
        self.assertIn('A2264185', logged[0])
        self.assertIn('2026/11/20', logged[0])


class FetchTests(unittest.TestCase):
    """الشبكة: نتأكد من النقاط المستخدمة ومن الرسائل (بـ patch بدون شبكة)"""

    def _patch(self, post_text='', get_text=''):
        import requests as _rq
        state = {}

        class Resp:
            def __init__(self, text):
                self.text = text

        def fake_post(url, data=None, cookies=None, **kw):
            state['post_url'] = url
            state['post_data'] = data
            return Resp(post_text)

        def fake_get(url, cookies=None, **kw):
            state['get_url'] = url
            return Resp(get_text)

        _rq.post, _rq.get = fake_post, fake_get
        return state

    def _restore(self):
        import requests as _rq
        _rq.post = _rq.Session.post if hasattr(_rq, 'Session') else _rq.post
        # استرجاع الأصليين عبر requests.api
        import requests.api as _api
        _rq.post = _api.request  # placeholder — يُصلح أدناه

    def test_fetch_page_reports_empty(self):
        import requests as _rq
        import requests.api as api
        oldp, oldg = _rq.post, _rq.get
        state = self._patch(post_text='1', get_text=_read('meeting_inform_empty.html'))
        try:
            out = ilann.fetch_page({}, 'A2264212', '260668600')
        finally:
            _rq.post, _rq.get = oldp, oldg
        self.assertFalse(out['ok'])
        self.assertIn('لا توجد بيانات', out['message'])
        self.assertTrue(state['post_url'].endswith('/includes/insert_showimg.php'))
        self.assertEqual(state['post_data']['task_id'], 'A2264212')
        self.assertEqual(state['post_data']['caseid'], '260668600')

    def test_fetch_page_parses_filled(self):
        import requests as _rq
        oldp, oldg = _rq.post, _rq.get
        self._patch(post_text='1', get_text=_read('meeting_inform.html'))
        try:
            out = ilann.fetch_page({}, 'A2264212', '260668600')
        finally:
            _rq.post, _rq.get = oldp, oldg
        self.assertTrue(out['ok'])
        self.assertEqual(len(out['parties']), 2)
        self.assertEqual(out['case'].get('رقم الخبرة'), 'A2264212')

    def test_fetch_party_form_uses_endpoint(self):
        import requests as _rq
        oldp = _rq.post
        state = self._patch(post_text=_read('party_form.html'))
        try:
            form = ilann.fetch_party_form({}, '160801')
        finally:
            _rq.post = oldp
        self.assertTrue(state['post_url'].endswith('/includes/load_add.php'))
        self.assertEqual(state['post_data']['part_id'], '160801')
        self.assertEqual(form['part_id'], '160801')

    def test_fetch_zones(self):
        import requests as _rq
        oldp = _rq.post
        html = '<select name="ADRS_ZONE"><option value="204">حولى</option>' \
               '<option value="205">الشعب</option></select>'
        state = self._patch(post_text=html)
        try:
            zones = ilann.fetch_zones({}, '2')
        finally:
            _rq.post = oldp
        self.assertTrue(state['post_url'].endswith('/includes/load_gov.php'))
        self.assertEqual(state['post_data']['gov_id'], '2')
        self.assertEqual(zones, [('204', 'حولى'), ('205', 'الشعب')])


class NullCleaningTests(unittest.TestCase):
    """تنظيف قيم النظام الفارغة ('null'/'None'/'undefined') — إلزامي:

    النظام يكتب القيمة الفارغة كنص حرفي، فكانت تطلع بالواجهة كأنها قيمة
    (رقم هاتف «null»!) وتُرسَل للنظام بحالها.
    """

    def test_clean_value_removes_null_like(self):
        for bad in ('null', 'NULL', 'Null', 'None', 'none', 'undefined',
                    'undefined ', ' null', '', '   ', '-', None):
            self.assertEqual(ilann.clean_value(bad), '', repr(bad))

    def test_clean_value_keeps_real_values(self):
        self.assertEqual(ilann.clean_value('9655555'), '9655555')
        self.assertEqual(ilann.clean_value('احمد الجابر'), 'احمد الجابر')
        self.assertEqual(ilann.clean_value('  10  '), '10')

    def test_party_form_cleans_null_fields(self):
        """نموذج الطرف المجمّد فيه ADDRNO=null — لازم يطلع فراغ."""
        form = ilann.parse_party_form(_read('party_form.html'))
        self.assertEqual(form['fields'].get('ADDRNO'), '')

    def test_payload_never_carries_null(self):
        form = ilann.parse_party_form(_read('party_form.html'))
        payload = ilann.build_payload(form, {})
        self.assertEqual(payload['ADDRNO'], '')
        for k, v in payload.items():
            self.assertNotEqual(str(v).strip().lower(), 'null', k)

    def test_payload_cleans_user_typed_null(self):
        form = ilann.parse_party_form(_read('party_form.html'))
        payload = ilann.build_payload(form, {'ADDRNO': 'null', 'ADRS_STREET': '  '})
        self.assertEqual(payload['ADDRNO'], '')
        self.assertEqual(payload['ADRS_STREET'], '')

    def test_results_clean_null_cells(self):
        html = """
        <table><thead><tr><th>الاسم</th><th>وسيله الاعلان</th><th>تاريخ الاعلان</th>
        <th>تاريخ الجلسه</th><th>حاله الاعلان</th><th>سبب التعذر</th></tr></thead>
        <tbody>
          <tr><td>شركه الاتصالات</td><td>null</td><td>20/10/2020</td>
              <td>28/10/2020</td><td>تم</td><td>null</td></tr>
        </tbody></table>"""
        rows = ilann.parse_results(html)
        self.assertEqual(rows[0]['means'], '')
        self.assertEqual(rows[0]['reason'], '')


class FormAddressTests(unittest.TestCase):
    """فروق «ما فيه عنوان مسجّل» عن «تعذّر الاتصال»."""

    def test_form_has_address_true(self):
        form = ilann.parse_party_form(_read('party_form.html'))
        self.assertTrue(ilann.form_has_address(form))

    def test_form_has_address_false_when_empty(self):
        form = ilann.parse_party_form(_read('party_form.html'))
        form['fields'] = {'part_id': '160801', 'CNT_SEQ': '160799'}
        self.assertFalse(ilann.form_has_address(form))

    def test_form_has_address_ignores_null_only(self):
        form = ilann.parse_party_form(_read('party_form.html'))
        form['fields'] = {'ADDRNO': 'null', 'ADRS_STREET': 'null'}
        self.assertFalse(ilann.form_has_address(form))


class NetworkErrorTests(unittest.TestCase):
    """فشل الشبكة لازم يطلع كخطأ صريح — مو نتيجة فاضية."""

    def test_fetch_party_form_raises_on_network_error(self):
        import requests as _rq
        oldp = _rq.post

        def boom(*a, **kw):
            raise OSError('network down')

        _rq.post = boom
        try:
            with self.assertRaises(Exception):
                ilann.fetch_party_form({}, '160801')
        finally:
            _rq.post = oldp

    def test_fetch_page_reports_connection_reason(self):
        import requests as _rq
        oldp = _rq.post

        def boom(*a, **kw):
            raise OSError('network down')

        _rq.post = boom
        try:
            out = ilann.fetch_page({}, 'A2264212', '260668600')
        finally:
            _rq.post = oldp
        self.assertFalse(out['ok'])
        self.assertEqual(out['reason'], 'connection')
        self.assertNotIn('network down', out['message'])

    def test_fetch_page_reports_no_data_reason(self):
        import requests as _rq
        oldp, oldg = _rq.post, _rq.get

        class Resp:
            text = '0'

        _rq.post = lambda *a, **kw: Resp()
        _rq.get = lambda *a, **kw: Resp()
        try:
            out = ilann.fetch_page({}, 'A9999999', '')
        finally:
            _rq.post, _rq.get = oldp, oldg
        self.assertFalse(out['ok'])
        self.assertEqual(out['reason'], 'no_data')


class DocxTests(unittest.TestCase):
    def test_generates_word_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'إشعار_إعلان.docx')
            ilann.notice_docx(
                out, 'A2264212',
                party={'name': 'شركه الاتصالات المتنقله ش م ك', 'type': 'مدعى',
                       'contact': 'مندوب', 'address': 'شارع احمد الجابر', 'phone': '9655555'},
                results=[{'name': 'شركه الاتصالات', 'means': 'رسائل', 'date': '20/10/2020',
                          'session_date': '28/10/2020', 'status': 'تم', 'reason': '-'}],
                case_info={'auto_no': '260668600', 'case_no': '26001611',
                           'type': 'تجارىومدنى جزئي'},
                expert_name='محمد عبدالله فرحان العنزى')
            self.assertTrue(os.path.exists(out))
            self.assertGreater(os.path.getsize(out), 5000)


if __name__ == '__main__':
    unittest.main()
