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
