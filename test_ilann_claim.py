# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# اختبارات «سحب العنوان من صحيفة الدعوى» (ilann_claim):
#   • مطابقة المحافظة والمنطقة (أسماء مختلفة لنفس الشي) + مطابقة اسم الطرف.
#   • قراءة رد الذكاء (JSON نظيف أو داخل ```json أو مع نص زايد).
#   • **الاستخراج يردّ الطرفين معاً** (المدعي + المدعى عليه) والمطابقة محلياً
#     **بالصفة أولاً ثم بالاسم** — المدعى عليه ما ياخذ عنوان المدعي.
#   • القاعدة الأساسية: مع محامٍ ⟵ «مندوب» + اسم/هاتف/فاكس المحامي في خانات الاتصال،
#     وبدون محامٍ ⟵ العنوان «مثل ما هو مكتوب» ووسيلة الإعلان ما تتغيّر.
#   • **مسار التجهيز**: المجلد ⟵ الـPDF بجذر مجلد رقم الخبرة؟ لا ⟵ ننزّله ·
#     المارك داون موجودة؟ ⟵ وقف · لا ⟵ نحوّلها ونحفظها **بالجذر** (بلا مجلدات فرعية).
#   • **الاستخراج من نص المارك داون** (أول صفحتين) + المحاولة موجّهة + Gemini أولاً.
#   • الرسالة بالعربي وتقول «شنو مالقيت».
#   python -W ignore -m unittest test_ilann_claim -v
import json
import os
import tempfile
import unittest
from unittest import mock

import ilann
import ilann_claim as ic


ADDRESS_WITH_LAWYER = {
    'found': True,
    'address': {
        'city': 'محافظه العاصمه',
        'area': 'حطين',
        'street': 'أحمد الجابر',
        'jadda': None,
        'block': '5',
        'building': None,
        'floor': '10',
        'unit': '23',
        'unit_type': 'شقة',
        'description': 'منطقة حطين قطعة 5 شارع أحمد الجابر دوار 10 شقة 23',
    },
    'has_lawyer': True,
    'lawyer': {
        'name': 'عبدالله المحامي',
        'phone': '09650000',
        'fax': '22222222',
        'address': {'description': 'مكتب المحامي في العليا'},
    },
}

ADDRESS_NO_LAWYER = {
    'found': True,
    'address': {
        'city': 'حولي',
        'area': 'السالمية',
        'street': 'شارع محمد',
        'block': None,
        'description': 'منطقة السالمية شارع محمد',
    },
    'has_lawyer': False,
    'lawyer': {'name': None, 'phone': None, 'fax': None, 'address': {}},
}


def _case_folders():
    """مجلد قضية مؤقت ببنية البرنامج (مستندات النظام + markdown)."""
    base = tempfile.mkdtemp()
    sysdocs = os.path.join(base, 'مستندات_النظام')
    os.makedirs(sysdocs, exist_ok=True)
    os.makedirs(os.path.join(base, 'markdown', 'مستندات_النظام'), exist_ok=True)
    return base, sysdocs, os.path.join(base, 'markdown', 'مستندات_النظام')


class NormalizeTests(unittest.TestCase):
    """تطبيع النص — «محافظه العاصمه» = «العاصمة»"""

    def test_same_governorate_spelling(self):
        self.assertEqual(ic.normalize('محافظه العاصمه'), ic.normalize('العاصمة'))

    def test_alef_ya_ta_marbuta(self):
        self.assertEqual(ic.normalize('الفروانية'), ic.normalize('الفروانيه'))

    def test_spaces_removed(self):
        self.assertEqual(ic.normalize('منطقة  حطين'), 'منطقهحطين')

    def test_words_keeps_words(self):
        self.assertEqual(ic.normalize_words('ش.م.ك'), 'ش م ك')

    def test_name_score_same_company_different_spelling(self):
        """«شركه الاتصالات المتنقله ش م ك» ≈ «شركة الاتصالات المتنقله ش.م.ك»."""
        score = ic.name_score('شركه الاتصالات المتنقله ش م ك',
                              'شركة الاتصالات المتنقله ش.م.ك')
        self.assertGreaterEqual(score, ic.NAME_MATCH_MIN)

    def test_name_score_different_party(self):
        self.assertLess(ic.name_score('شركه الاتصالات المتنقله ش م ك',
                                      'عبد الهادي محمد علي'), 0.4)


class MatchTests(unittest.TestCase):
    """مطابقة المحافظة والمنطقة والأطراف مع قوائم النظام"""

    def test_governorate_by_name(self):
        self.assertEqual(ic.match_governorate('العاصمه'), '1')
        self.assertEqual(ic.match_governorate('محافظة حولى'), '2')
        self.assertEqual(ic.match_governorate('الفروانية'), '5')
        self.assertEqual(ic.match_governorate('مبارك الكبير'), '6')

    def test_governorate_unknown(self):
        self.assertEqual(ic.match_governorate('خارج الكويت'), '')

    def test_zone_by_name(self):
        zones = [('101', 'الدسمة'), ('102', 'حطين')]
        self.assertEqual(ic.match_zone('حطين', zones), '102')

    def test_zone_partial_text(self):
        zones = [('101', 'الدسمة'), ('102', 'حطين')]
        self.assertEqual(ic.match_zone('منطقة حطين قطعة 5', zones), '102')

    def test_zone_no_match(self):
        self.assertEqual(ic.match_zone('البرمال', [('101', 'الدسمة')]), '')

    def test_match_party_picks_the_right_row(self):
        rows = [{'party': 'شركه الاتصالات المتنقله ش م ك', 'address': {'street': 'أ'}},
                {'party': 'عبد الهادي محمد علي', 'address': {'street': 'ب'}}]
        got = ic.match_party(rows, 'شركة الاتصالات المتنقله ش.م.ك')
        self.assertEqual(got['address']['street'], 'أ')

    def test_match_party_none_when_no_similar(self):
        rows = [{'party': 'شركه الاتصالات المتنقله ش م ك', 'address': {}}]
        self.assertIsNone(ic.match_party(rows, 'شركه البترول_END'))


class RoleTests(unittest.TestCase):
    """دور الطرف من صفة النظام («مدعى» / «مدعي عليه»)"""

    def test_plaintiff_role(self):
        self.assertEqual(ic.party_role('مدعى'), ic.ROLE_PLAINTIFF)
        self.assertEqual(ic.party_role('مدعي'), ic.ROLE_PLAINTIFF)
        self.assertEqual(ic.party_role('المدعي'), ic.ROLE_PLAINTIFF)
        self.assertEqual(ic.party_role('مدعيه'), ic.ROLE_PLAINTIFF)

    def test_defendant_role(self):
        self.assertEqual(ic.party_role('مدعي عليه'), ic.ROLE_DEFENDANT)
        self.assertEqual(ic.party_role('مدعى عليه'), ic.ROLE_DEFENDANT)
        self.assertEqual(ic.party_role('المدعى عليه'), ic.ROLE_DEFENDANT)

    def test_defendant_checked_before_plaintiff(self):
        """«مدعي عليه» فيها كلمة «مدعي» — لازم تكون مدعى عليه."""
        self.assertEqual(ic.party_role('مدعي عليه'), ic.ROLE_DEFENDANT)

    def test_ai_role_words(self):
        """رد الذكاء: «المدعي» / «المدعى عليه»."""
        self.assertEqual(ic.party_role('المدعي'), ic.ROLE_PLAINTIFF)
        self.assertEqual(ic.party_role('المدعى عليه'), ic.ROLE_DEFENDANT)

    def test_unknown_role(self):
        self.assertEqual(ic.party_role('وكيل'), '')
        self.assertEqual(ic.party_role(''), '')


class SelectPartyTests(unittest.TestCase):
    """اختيار الطرف من أطراف صحيفة الدعوى — بالصفة أولاً ثم بالاسم

    (ملاحظة العنزي 14/11/2026: «نفس المعلومات الخاصة بالمدعي ظهرت للمدعى عليه»).
    """

    ROWS = [
        {'role': 'المدعي', 'party': 'شركه الاتصالات المتنقله ش م ك',
         'address': {'description': 'العاصمة الشويخ'},
         'lawyer': {'name': 'عمر محمد العمر', 'phone': '1807807', 'fax': None}},
        {'role': 'المدعى عليه', 'party': 'عبد الهادي محمد علي المري',
         'address': {'description': 'حطين قطعة 5'},
         'lawyer': {'name': None, 'phone': None, 'fax': None}},
    ]

    def test_defendant_does_not_get_plaintiff_address(self):
        """المدعى عليه ما ياخذ عنوان المدعي."""
        row = ic.select_party(self.ROWS, 'عبد الهادي محمد علي المري', 'مدعي عليه')
        self.assertIsNotNone(row)
        self.assertEqual(row['address']['description'], 'حطين قطعة 5')

    def test_plaintiff_gets_its_own_row(self):
        row = ic.select_party(self.ROWS, 'شركه الاتصالات المتنقله ش م ك', 'مدعى')
        self.assertIsNotNone(row)
        self.assertEqual(row['address']['description'], 'العاصمة الشويخ')

    def test_role_decides_when_name_differs(self):
        """الاسم بالسمية يختلف قليلاً («ش.م.ك» ≈ «ش م ك») — الصفة تحسم."""
        rows = [{'role': 'المدعى عليه', 'party': 'عبد الهادي محمد علي', 'address': {}}]
        row = ic.select_party(rows, 'عبد الهادي محمد علي المرى', 'مدعي عليه')
        self.assertIsNotNone(row)

    def test_two_same_role_needs_name(self):
        """طرفان بنفس الصفة ⟵ لازم الاسم يطابق."""
        rows = [{'role': 'المدعى عليه', 'party': 'سالم', 'address': {}},
                {'role': 'المدعى عليه', 'party': 'ناصر', 'address': {}}]
        self.assertIsNone(ic.select_party(rows, 'خالد', 'مدعي عليه'))
        self.assertEqual(ic.select_party(rows, 'ناصر', 'مدعي عليه')['party'], 'ناصر')

    def test_fallback_to_name_when_no_role(self):
        rows = [{'party': 'شركه الاتصالات المتنقله ش م ك', 'address': {'street': 'أ'}}]
        got = ic.select_party(rows, 'شركة الاتصالات المتنقله ش.م.ك', '')
        self.assertIsNotNone(got)

    def test_no_match_at_all(self):
        self.assertIsNone(ic.select_party(self.ROWS, 'طرف ثالث', 'مدعي عليه'))

    def test_row_to_data_shape(self):
        data = ic.party_row_to_data(self.ROWS[0])
        self.assertTrue(data['found'])
        self.assertTrue(data['has_lawyer'])
        self.assertEqual(data['lawyer']['name'], 'عمر محمد العمر')
        self.assertEqual(data['address']['description'], 'العاصمة الشويخ')


class ParseTests(unittest.TestCase):
    """قراءة رد الذكاء"""

    def test_plain_json(self):
        self.assertEqual(ic.parse_json('{"found": true}'), {'found': True})

    def test_fenced_json(self):
        raw = '```json\n{"found": true, "address": {}}\n```'
        self.assertTrue(ic.parse_json(raw)['found'])

    def test_json_with_extra_text(self):
        raw = 'هذا هو الرد:\n{"found": false}\nوهذا نهاية.'
        self.assertFalse(ic.parse_json(raw)['found'])

    def test_invalid_returns_none(self):
        self.assertIsNone(ic.parse_json('ما فيه JSON هنا'))
        self.assertIsNone(ic.parse_json(''))

    def test_arabic_digits_to_latin(self):
        self.assertEqual(ic.latin_digits('٠٩٦٥٠٠٠٠'), '09650000')
        self.assertEqual(ic.latin_digits('۱۲۳'), '123')


class BuildValuesTests(unittest.TestCase):
    """القاعدة الأساسية — تعبئة النموذج من رد الذكاء"""

    def test_no_lawyer_address_as_written(self):
        """بدون محامٍ ⟵ العنوان مثل ما هو مكتوب، ووسيلة الإعلان ما تتغيّر."""
        v = ic.build_values(ADDRESS_NO_LAWYER)
        self.assertEqual(v['fields']['ADRS_STREET'], 'شارع محمد')
        self.assertEqual(v['fields']['ADRS_DESCR'], 'منطقة السالمية شارع محمد')
        self.assertEqual(v['city_code'], '2')
        self.assertEqual(v['method'], '')
        self.assertFalse(v['has_lawyer'])
        self.assertNotIn('ADDRNO', v['fields'])
        self.assertNotIn('EIF_NOTE', v['fields'])

    def test_lawyer_sets_representative(self):
        """مع محامٍ ⟵ وسيلة الإعلان «مندوب» (10001)."""
        v = ic.build_values(ADDRESS_WITH_LAWYER)
        self.assertEqual(v['method'], '10001')
        self.assertTrue(v['has_lawyer'])

    def test_lawyer_contact_fields(self):
        """اسم المحامي ورقمه وفاكسه في خانات الاتصال تحت."""
        v = ic.build_values(ADDRESS_WITH_LAWYER)
        self.assertEqual(v['fields']['ADDRNO'], '09650000')
        self.assertEqual(v['fields']['MAIN_CNTD_TYPE_DESC'], 'المحامي: عبدالله المحامي')
        note = v['fields']['EIF_NOTE']
        self.assertIn('عبدالله المحامي', note)
        self.assertIn('09650000', note)
        self.assertIn('22222222', note)

    def test_lawyer_fax_used_when_no_phone(self):
        data = {'found': True, 'address': {}, 'has_lawyer': True,
                'lawyer': {'name': 'محامي', 'phone': None, 'fax': '55555555'}}
        v = ic.build_values(data)
        self.assertEqual(v['fields']['ADDRNO'], '55555555')

    def test_lawyer_without_any_contact(self):
        """محامٍ بلا أرقام ⟵ ما نخترع رقم تواصل."""
        data = {'found': True, 'address': {}, 'has_lawyer': True,
                'lawyer': {'name': 'محامي', 'phone': None, 'fax': None}}
        v = ic.build_values(data)
        self.assertNotIn('ADDRNO', v['fields'])
        self.assertEqual(v['fields']['MAIN_CNTD_TYPE_DESC'], 'المحامي: محامي')

    def test_null_values_ignored(self):
        """«null» من الذكاء ⟵ ما تتعبّى خانة (زي قيم النظام الفارغة)."""
        data = {'found': True,
                'address': {'city': None, 'street': 'null', 'block': None,
                            'description': 'شارع محمد'},
                'has_lawyer': False, 'lawyer': {}}
        v = ic.build_values(data)
        self.assertNotIn('ADRS_STREET', v['fields'])
        self.assertNotIn('ADRS_BLOCK', v['fields'])
        self.assertEqual(v['fields']['ADRS_DESCR'], 'شارع محمد')
        self.assertEqual(v['city_code'], '')

    def test_description_built_from_parts(self):
        """لو ما في وصف كامل ⟵ نركّبه من الأجزاء (العنوان مثل ما هو مكتوب)."""
        data = {'found': True,
                'address': {'street': 'أحمد الجابر', 'block': '5', 'unit': '23'},
                'has_lawyer': False, 'lawyer': {}}
        v = ic.build_values(data)
        self.assertIn('أحمد الجابر', v['fields']['ADRS_DESCR'])
        self.assertIn('23', v['fields']['ADRS_DESCR'])

    def test_contact_number_max_length(self):
        """رقم الاتصال محدود بـ12 حرف (حدّ النموذج)."""
        data = {'found': True, 'address': {}, 'has_lawyer': True,
                'lawyer': {'name': 'محامي', 'phone': '123456789012345678'}}
        v = ic.build_values(data)
        self.assertEqual(len(v['fields']['ADDRNO']), 12)

    def test_zone_matched_from_zones_list(self):
        v = ic.build_values(ADDRESS_WITH_LAWYER, zones=[('102', 'حطين')])
        self.assertEqual(v['zone_code'], '102')

    def test_summary_mentions_representative(self):
        v = ic.build_values(ADDRESS_WITH_LAWYER)
        self.assertIn('مندوب', ic.summary_of(v))

    def test_summary_without_lawyer(self):
        v = ic.build_values(ADDRESS_NO_LAWYER)
        self.assertNotIn('مندوب', ic.summary_of(v))


class NotFoundMessageTests(unittest.TestCase):
    """الرسالة بالعربي وتقول «شنو مالقيت»"""

    def test_message_uses_party_type(self):
        msg = ic.not_found_message('مدعى عليه', 'شركه الاتصالات')
        self.assertIn('لم نجد أي عنوان', msg)
        self.assertIn('المدعى عليه', msg)

    def test_message_lists_found_parties(self):
        msg = ic.not_found_message('مدعى عليه', 'طرف ثاني',
                                   ['شركه الاتصالات المتنقله ش م ك', 'عبد الهادي محمد علي'])
        self.assertIn('الموجود بالصحيفة', msg)
        self.assertIn('عبد الهادي', msg)

    def test_message_without_any_party(self):
        msg = ic.not_found_message('مدعى', 'طرف', [])
        self.assertIn('لم نجد أي عنوان', msg)
        self.assertNotIn('الموجود بالصحيفة', msg)


class EnsureClaimMarkdownTests(unittest.TestCase):
    """مسار التجهيز: المجلد ← الـPDF بجذر مجلد رقم الخبرة ← المارك داون بجذره"""

    def test_markdown_exists_skips_conversion(self):
        """المارك داون موجودة ← وقف: ما تحويل ولا تنزيل (والـPDF موجودة)."""
        base, sysdocs, md_dir = _case_folders()
        with open(os.path.join(base, ic.CLAIM_ROOT_PDF), 'wb') as f:
            f.write(b'%PDF-1.4 test')
        with open(os.path.join(base, ic.CLAIM_ROOT_MD), 'w', encoding='utf-8') as f:
            f.write('نص صحيفة الدعوى')
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, {})), \
             mock.patch.object(ic, 'fetch_newest_claim') as fetch, \
             mock.patch.object(ic, 'convert_to_markdown') as conv:
            out = ic.ensure_claim_markdown({}, 'A1', '260668600')
        self.assertTrue(out['ok'])
        self.assertIn('نص صحيفة الدعوى', out['text'])
        fetch.assert_not_called()
        conv.assert_not_called()

    def test_pdf_exists_gets_converted(self):
        """الـPDF موجودة بدون مارك داون ← نحوّلها (ما ننزّل)."""
        base, sysdocs, md_dir = _case_folders()
        with open(os.path.join(base, ic.CLAIM_ROOT_PDF), 'wb') as f:
            f.write(b'%PDF-1.4 test')
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, {})), \
             mock.patch.object(ic, 'fetch_newest_claim') as fetch, \
             mock.patch.object(ic, 'convert_to_markdown',
                               return_value=('نص مضمون', 3, 'test')):
            out = ic.ensure_claim_markdown({}, 'A1', '260668600')
        fetch.assert_not_called()
        self.assertTrue(out['ok'])
        self.assertEqual(out['text'], 'نص مضمون')
        self.assertTrue(os.path.exists(os.path.join(base, ic.CLAIM_ROOT_MD)))

    def test_missing_file_downloads_then_converts(self):
        """ولا ملف ← ننزّله من الملف الآلي ونحوّله — **بجذر المجلد**."""
        base, sysdocs, md_dir = _case_folders()

        def fake_fetch(cookies, auto, out_path, user_id='309'):
            with open(out_path, 'wb') as f:
                f.write(b'%PDF-1.4 test')
            return out_path, 'OK'

        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, {})), \
             mock.patch.object(ic, 'fetch_newest_claim', side_effect=fake_fetch) as fetch, \
             mock.patch.object(ic, 'convert_to_markdown',
                               return_value=('نص جديد', 2, 'test')):
            out = ic.ensure_claim_markdown({}, 'A1', '260668600')
        fetch.assert_called_once()
        self.assertTrue(out['ok'])
        self.assertTrue(os.path.exists(os.path.join(base, ic.CLAIM_ROOT_PDF)))
        self.assertTrue(os.path.exists(os.path.join(base, ic.CLAIM_ROOT_MD)))

    def test_no_auto_number_gives_message(self):
        base, _sysdocs, _md = _case_folders()
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, {})):
            out = ic.ensure_claim_markdown({}, 'A1', '')
        self.assertFalse(out['ok'])
        self.assertIn('ما فيه رقم آلي', out['message'])

    def test_progress_messages_are_arabic(self):
        base, _sysdocs, _md = _case_folders()
        seen = []
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, {})):
            ic.ensure_claim_markdown({}, 'A1', '', progress=seen.append)
        self.assertTrue(all(isinstance(x, str) and x for x in seen))

    def test_legacy_markdown_copied_to_root(self):
        """مارك داون بالمسار القديم ← تننسخ لجذر المجلد (ما نحوّل من جديد)."""
        base, _sysdocs, md_dir = _case_folders()
        with open(os.path.join(md_dir, 'صحيفة_الدعوى.md'), 'w', encoding='utf-8') as f:
            f.write('نص قديم')
        with open(os.path.join(base, ic.CLAIM_ROOT_PDF), 'wb') as f:
            f.write(b'%PDF-1.4 test')
        os.utime(os.path.join(base, ic.CLAIM_ROOT_PDF), (1000, 1000))
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, {})), \
             mock.patch.object(ic, 'convert_to_markdown') as conv:
            out = ic.ensure_claim_markdown({}, 'A1', '')
        conv.assert_not_called()
        self.assertTrue(out['ok'])
        self.assertIn('نص قديم', out['text'])
        self.assertTrue(os.path.exists(os.path.join(base, ic.CLAIM_ROOT_MD)))

    def test_legacy_markdown_current_name_copied_to_root(self):
        """المارك داون بالاسم الحالي («صحيفة الدعوى.md») ← تننسخ لجذر المجلد."""
        base, _sysdocs, md_dir = _case_folders()
        with open(os.path.join(md_dir, 'صحيفة الدعوى.md'), 'w', encoding='utf-8') as f:
            f.write('نص الحالي')
        with open(os.path.join(base, ic.CLAIM_ROOT_PDF), 'wb') as f:
            f.write(b'%PDF-1.4 test')
        os.utime(os.path.join(base, ic.CLAIM_ROOT_PDF), (1000, 1000))
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, {})), \
             mock.patch.object(ic, 'convert_to_markdown') as conv:
            out = ic.ensure_claim_markdown({}, 'A1', '')
        conv.assert_not_called()
        self.assertTrue(out['ok'])
        self.assertIn('نص الحالي', out['text'])

    def test_legacy_pdf_copied_to_root(self):
        """الـPDF بالمسار القديم ← تننسخ لجذر المجلد (ما ننزّل من جديد)."""
        base, sysdocs, _md = _case_folders()
        with open(os.path.join(sysdocs, ic.CLAIM_FILE_NAME), 'wb') as f:
            f.write(b'%PDF-1.4 test')
        with open(os.path.join(base, ic.CLAIM_ROOT_MD), 'w', encoding='utf-8') as f:
            f.write('نص')
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, {})), \
             mock.patch.object(ic, 'fetch_newest_claim') as fetch:
            out = ic.ensure_claim_markdown({}, 'A1', '')
        fetch.assert_not_called()
        self.assertTrue(out['ok'])
        self.assertTrue(os.path.exists(os.path.join(base, ic.CLAIM_ROOT_PDF)))

    def test_source_registered_with_root_path(self):
        """السجل (case.json) يشير للملف بالجذر — عشان باقي البرنامج يلاقيه."""
        base, _sysdocs, _md = _case_folders()
        data = {}
        with open(os.path.join(base, ic.CLAIM_ROOT_PDF), 'wb') as f:
            f.write(b'%PDF-1.4 test')
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, data)):
            ic.ensure_claim_markdown({}, 'A1', '')
        rec = (data.get('sources') or {}).get('claim') or {}
        self.assertEqual(rec.get('file'), ic.CLAIM_ROOT_PDF)

    def test_text_registered_for_report_pipeline(self):
        """النص المحفوظ يُسجَّل في sources ⟵ برنامج التقارير ما يعيد تحويل الصحيفة."""
        base, _sysdocs, _md = _case_folders()
        data = {}
        with open(os.path.join(base, ic.CLAIM_ROOT_PDF), 'wb') as f:
            f.write(b'%PDF-1.4' + b'0' * 400)
        with open(os.path.join(base, ic.CLAIM_ROOT_MD), 'w', encoding='utf-8') as f:
            f.write('نص صحيفة الدعوى')
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, data)):
            out = ic.ensure_claim_markdown({}, 'A1', '')
        self.assertTrue(out['ok'])
        rec = (data.get('sources') or {}).get('claim') or {}
        self.assertTrue(rec.get('text_file'))
        self.assertTrue(os.path.exists(os.path.join(base, rec['text_file'])))


class ClaimPathsTests(unittest.TestCase):
    """مسار صحيفة الدعوى: بجذر مجلد رقم الخبرة (بلا مجلدات فرعية)"""

    def test_rel_paths_at_case_root(self):
        rel, md_rel = ic.claim_rel_paths()
        self.assertEqual(rel, 'صحيفة الدعوى.pdf')
        self.assertEqual(md_rel, 'صحيفة الدعوى.md')
        self.assertNotIn('/', rel)
        self.assertNotIn('/', md_rel)

    def test_find_local_claim_prefers_root(self):
        base = tempfile.mkdtemp()
        with open(os.path.join(base, ic.CLAIM_ROOT_PDF), 'wb') as f:
            f.write(b'%PDF-1.4 test')
        with mock.patch.object(ic, '_case_base', return_value=base):
            got = ic.find_local_claim('A1')
        self.assertEqual(got, os.path.join(base, ic.CLAIM_ROOT_PDF))

    def test_find_local_claim_falls_back_to_old_folder(self):
        base = tempfile.mkdtemp()
        sysdocs = os.path.join(base, 'مستندات_النظام')
        os.makedirs(sysdocs, exist_ok=True)
        with open(os.path.join(sysdocs, ic.CLAIM_FILE_NAME), 'wb') as f:
            f.write(b'%PDF-1.4 test')
        with mock.patch.object(ic, '_case_base', return_value=base), \
             mock.patch.object(ic, 'sysdocs_dir', return_value=sysdocs):
            got = ic.find_local_claim('A1')
        self.assertEqual(got, os.path.join(sysdocs, ic.CLAIM_FILE_NAME))

    def test_find_local_claim_returns_empty_when_missing(self):
        base = tempfile.mkdtemp()
        with mock.patch.object(ic, '_case_base', return_value=base), \
             mock.patch.object(ic, 'sysdocs_dir', return_value=''):
            self.assertEqual(ic.find_local_claim('A1'), '')


class FirstPagesTests(unittest.TestCase):
    """أول صفحتين من نص المارك داون"""

    def test_takes_first_two_pages(self):
        text = '<!-- صفحة 1 -->\nأ\n<!-- صفحة 2 -->\nب\n<!-- صفحة 3 -->\nج'
        self.assertEqual(ic.first_pages(text, 2), 'أ\nب')

    def test_fallback_without_page_markers(self):
        self.assertEqual(len(ic.first_pages('x' * 20000, 2)), 8000)

    def test_empty_text(self):
        self.assertEqual(ic.first_pages('', 2), '')


class ExtractFromTextTests(unittest.TestCase):
    """الاستخراج من نص المارك داون (أول صفحتين)"""

    #: رد الذكاء بالطرفين (المدعي + المدعى عليه) — مثال حقيقي من قضية A2264212
    BOTH_REPLY = json.dumps({'parties': [
        {'role': 'المدعي', 'party': 'شركه الاتصالات المتنقله ش م ك',
         'address': {'city': 'العاصمة', 'area': 'الشويخ',
                     'description': 'الكائن مقرها العاصمة الشويخ'},
         'has_lawyer': True,
         'lawyer': {'name': 'عمر محمد العمر', 'phone': '1807807', 'fax': None}},
        {'role': 'المدعى عليه', 'party': 'عبد الهادي محمد علي المري',
         'address': {'city': 'حولي', 'area': 'حطين',
                     'description': 'حطين قطعة 5'},
         'has_lawyer': False, 'lawyer': {}},
    ]}, ensure_ascii=False)

    def test_asks_with_first_two_pages(self):
        seen = {}

        def fake_ask(prompt, task=None, spec=None, timeout=None):
            seen['prompt'] = prompt
            seen['task'] = task
            return '{"found": true, "address": {"street": "شارع محمد"}}'

        text = '<!-- صفحة 1 -->\nأول\n<!-- صفحة 2 -->\nثاني\n<!-- صفحة 3 -->\nثالث'
        with mock.patch('case_research.default_ask', fake_ask):
            data, err = ic.extract_party_address_from_text(text, 'طرف', 'مدعى')
        self.assertIsNone(err)
        self.assertEqual(data['address']['street'], 'شارع محمد')
        self.assertEqual(seen['task'], 'extract')
        self.assertIn('أول', seen['prompt'])
        # النص كله يروح للذكاء (مو صفحتين) — العنوان ممكن بأي صفحة
        self.assertIn('ثالث', seen['prompt'])

    def test_both_parties_in_one_request(self):
        """طلب واحد ⟵ الطرفين (المدعي + المدعى عليه)، وبعدها المطابقة محلياً."""
        seen = {}

        def fake(prompt, task=None, spec=None, timeout=None):
            seen['prompt'] = prompt
            seen['task'] = task
            seen['spec'] = spec
            return self.BOTH_REPLY

        with mock.patch('case_research.default_ask', fake):
            data, err = ic.extract_party_address_from_text('نص', 'عبد الهادي محمد علي المري',
                                                           'مدعي عليه')
        self.assertIsNone(err)
        # المدعى عليه أخذ عنوانه هو — مو عنوان المدعي
        self.assertEqual(data['address']['description'], 'حطين قطعة 5')
        self.assertIn('المدعى عليه', seen['prompt'])
        self.assertEqual(seen['spec'], 'gemini,openai')

    def test_plaintiff_row_with_its_lawyer(self):
        with mock.patch('case_research.default_ask', return_value=self.BOTH_REPLY):
            data, err = ic.extract_party_address_from_text('نص', 'شركه الاتصالات المتنقله ش م ك',
                                                           'مدعى')
        self.assertIsNone(err)
        self.assertEqual(data['lawyer']['name'], 'عمر محمد العمر')
        self.assertTrue(data['has_lawyer'])

    def test_unlabeled_reply_falls_back_to_targeted_request(self):
        """رد بلا هوية ⟵ طلب موجّه للطرف (اسم + صفة)."""
        seen = []

        def fake(prompt, task=None, spec=None, timeout=None):
            seen.append(prompt)
            return '{"found": true, "address": {"street": "شارع محمد"}}'

        with mock.patch('case_research.default_ask', fake):
            data, err = ic.extract_party_address_from_text('نص', 'طرف', 'مدعى')
        self.assertIsNone(err)
        self.assertEqual(data['address']['street'], 'شارع محمد')
        self.assertEqual(len(seen), 2)          # طلب الطرفين ← ثم طلب موجّه
        self.assertIn('مدعى', seen[1])          # الطلب الثاني موجّه بالصفة

    def test_second_pass_matches_different_spelling(self):
        """الاسم بالسمية مختلف قليلاً («ش.م.ك» ≈ «ش م ك») ⟵ يطابق."""
        reply = json.dumps({'parties': [
            {'role': 'المدعي', 'party': 'شركة الاتصالات المتنقله ش.م.ك',
             'address': {'street': 'شارع محمد'}}]}, ensure_ascii=False)
        with mock.patch('case_research.default_ask', return_value=reply):
            data, err = ic.extract_party_address_from_text('نص', 'شركه الاتصالات المتنقله ش م ك',
                                                           'مدعى')
        self.assertIsNone(err)
        self.assertEqual(data['address']['street'], 'شارع محمد')

    def test_not_found_message_in_arabic(self):
        replies = ['{"found": false}',
                   json.dumps({'parties': [{'party': 'عبد الهادي محمد علي', 'address': {}}]})]
        with mock.patch('case_research.default_ask', side_effect=replies):
            data, err = ic.extract_party_address_from_text('نص', 'طرف ثاني', 'مدعى عليه')
        self.assertIn('لم نجد أي عنوان', err)
        self.assertIn('عبد الهادي', err)


class ExtractPdfTests(unittest.TestCase):
    """الاستخراج من الملف مباشرة (Gemini بصور عالية الجودة)"""

    class _Resp:
        def __init__(self, text):
            self.text = text

    def test_extract_parses_gemini_reply(self):
        with mock.patch('gemini_config.generate_from_pdf',
                        return_value=self._Resp('{"found": true, "address": {}}')):
            data, err = ic.extract_party_address('x.pdf', 'شركه الاتصالات', 'مدعى')
        self.assertIsNone(err)
        self.assertTrue(data['found'])

    def test_gemini_first_with_critical(self):
        """critical=True ⟵ Gemini بصور عالية الجودة (الخدمة أوّلاً)."""
        seen = {}

        def fake(prompt, pdf_path, **kw):
            seen.update(kw)
            return self._Resp('{"found": true}')

        with mock.patch('gemini_config.generate_from_pdf', fake):
            ic.extract_party_address('x.pdf', 'طرف', 'مدعى')
        self.assertTrue(seen.get('critical'))
        self.assertEqual(seen.get('task'), 'text_light')

    def test_extract_bad_reply_gives_error(self):
        with mock.patch('gemini_config.generate_from_pdf',
                        return_value=self._Resp('ما فهمت شي')):
            data, err = ic.extract_party_address('x.pdf', 'شركه الاتصالات', 'مدعى')
        self.assertIsNone(data)
        self.assertIn('ما قدرنا نفهم', err)

    def test_not_found_message_is_arabic_and_specific(self):
        with mock.patch('gemini_config.generate_from_pdf',
                        return_value=self._Resp('{"found": false}')):
            data, err = ic.extract_party_address('x.pdf', 'شركه الاتصالات', 'مدعى عليه')
        self.assertIsNone(data)
        self.assertIn('لم نجد أي عنوان', err)
        self.assertIn('المدعى عليه', err)


class FetchNewestClaimTests(unittest.TestCase):
    """اختيار أحدث صحيفة دعوى (نفس منطق زر «الملف الآلي»)"""

    def test_picks_newest_claim_by_date(self):
        rows = [
            {'doc_type': 'صحيفة دعوى', 'doc_date': '01/02/2024 10:00:00 AM', 'doc_id': 'old'},
            {'doc_type': 'صحيفه دعوى', 'doc_date': '05/11/2026 09:00:00 AM', 'doc_id': 'new'},
            {'doc_type': 'حكم احالة', 'doc_date': '09/11/2026 09:00:00 AM', 'doc_id': 'judg'},
        ]

        def classify(row):
            if 'صحيف' in row['doc_type']:
                return 'claim'
            return 'judgment' if 'حكم' in row['doc_type'] else None

        with mock.patch('documents.get_documents_page', return_value='<html>x</html>'), \
             mock.patch('documents.parse_sections', return_value={'قسم': rows}), \
             mock.patch('documents.classify_document', side_effect=classify), \
             mock.patch('documents.download_judgment_pdf') as dl:
            path, status = ic.fetch_newest_claim({}, '260668600', 'x.pdf')
        self.assertEqual(status, 'OK')
        dl.assert_called_once_with({}, 'new', 'x.pdf')


class FetchAndExtractTests(unittest.TestCase):
    """الجلب + التحويل + الاستخراج"""

    def test_uses_markdown_text_first(self):
        prep = {'ok': True, 'text': 'نص', 'pdf': '', 'message': 'موجود مسبقاً'}
        with mock.patch.object(ic, 'ensure_claim_markdown', return_value=prep), \
             mock.patch.object(ic, 'extract_party_address_from_text',
                               return_value=({'found': True}, None)) as ex:
            data, err, msg = ic.fetch_and_extract({}, '260668600', 'طرف', 'مدعى',
                                                  caso_no='A1')
        ex.assert_called_once()
        self.assertTrue(data['found'])
        self.assertIn('تم استخراج العنوان', msg)

    def test_falls_back_to_pdf_when_text_fails(self):
        base, sysdocs, _md = _case_folders()
        pdf = os.path.join(sysdocs, 'صحيفة_الدعوى.pdf')
        with open(pdf, 'wb') as f:
            f.write(b'%PDF')
        prep = {'ok': True, 'text': 'نص', 'pdf': pdf, 'message': 'تم'}
        with mock.patch.object(ic, 'ensure_claim_markdown', return_value=prep), \
             mock.patch.object(ic, 'extract_party_address_from_text',
                               return_value=(None, 'ما لقينا عنوان')), \
             mock.patch.object(ic, 'extract_party_address',
                               return_value=({'found': True}, None)) as pdf_ex:
            data, err, msg = ic.fetch_and_extract({}, '260668600', 'طرف', 'مدعى',
                                                  caso_no='A1')
        pdf_ex.assert_called_once()
        self.assertTrue(data['found'])

    def test_no_claim_document_message(self):
        prep = {'ok': False, 'text': '', 'pdf': '', 'message': 'ما فيه صحيفة دعوى متاحة.'}
        with mock.patch.object(ic, 'ensure_claim_markdown', return_value=prep):
            data, err, msg = ic.fetch_and_extract({}, '260668600', 'طرف', 'مدعى',
                                                  caso_no='A1')
        self.assertIsNone(data)
        self.assertIn('ما فيه صحيفة دعوى', msg)

    def test_error_message_is_arabic(self):
        prep = {'ok': True, 'text': 'نص', 'pdf': '', 'message': 'تم'}
        with mock.patch.object(ic, 'ensure_claim_markdown', return_value=prep), \
             mock.patch.object(ic, 'extract_party_address_from_text',
                               return_value=(None, 'لم نجد أي عنوان للمدعى عليه')):
            data, err, msg = ic.fetch_and_extract({}, '260668600', 'طرف', 'مدعى',
                                                  caso_no='A1')
        self.assertIsNone(data)
        self.assertIn('لم نجد أي عنوان', err)


#: نص صحيفة دعوى حقيقي (مقتطف من قضية A2264212) — لاختبار الاستخراج المحلي
CLAIM_TEXT_REAL = """<!-- صفحة 1 -->
المركز القانوني
عمر محمد العمر وشركاؤه
صحيفة دعوى
بناء على طلب: شركة الاتصالات المتنقلة (ش م ك).
الكائن مقرها: العاصمة الشويخ - ق (6) - ش المطار - م (80002)
ومحلها المختختار مكتب / عمر محمد العمر المحامي الكائن في
الشرق - شارع أحمد الجابر - بالقرب من دروازة العبدالرزاق -
الخصم: عبد الهادي محمد علي المري
ويعلن في : الفنطاس - قطعة (2) - شارع (13) - قسيمة (4503) منزل (1)
"""


class LocalAddressTests(unittest.TestCase):
    """الاستخراج المحلي (بلا ذكاء) — احتياط مضمون لو الذكاء ما لقى"""

    def test_finds_defendant_address(self):
        got = ic.local_address(CLAIM_TEXT_REAL, 'عبد الهادي محمد علي المري', 'مدعي عليه')
        self.assertIsNotNone(got)
        self.assertIn('الفنطاس', got['address']['description'])

    def test_finds_plaintiff_address(self):
        got = ic.local_address(CLAIM_TEXT_REAL, 'شركه الاتصالات المتنقله ش م ك', 'مدعى')
        self.assertIsNotNone(got)
        self.assertIn('الشويخ', got['address']['description'])

    def test_does_not_take_the_other_party_address(self):
        """المدعى عليه ما ياخذ عنوان المدعي (ولا العكس)."""
        got = ic.local_address(CLAIM_TEXT_REAL, 'عبد الهادي محمد علي المري', 'مدعي عليه')
        self.assertNotIn('الشويخ', got['address']['description'])
        got2 = ic.local_address(CLAIM_TEXT_REAL, 'شركه الاتصالات المتنقله ش م ك', 'مدعى')
        self.assertNotIn('الفنطاس', got2['address']['description'])

    def test_parses_address_fields(self):
        got = ic.local_address(CLAIM_TEXT_REAL, 'عبد الهادي محمد علي المري', 'مدعي عليه')
        self.assertEqual(got['address']['block'], '(2)')
        self.assertIn('13', got['address']['street'])

    def test_strips_the_label_prefix(self):
        got = ic.local_address(CLAIM_TEXT_REAL, 'شركه الاتصالات المتنقله ش م ك', 'مدعى')
        self.assertFalse(got['address']['description'].startswith('الكائن'))

    def test_finds_lawyer_name(self):
        got = ic.local_address(CLAIM_TEXT_REAL, 'عبد الهادي محمد علي المري', 'مدعي عليه')
        self.assertEqual(got['lawyer']['name'], 'عمر محمد العمر')

    def test_unknown_name_returns_none(self):
        self.assertIsNone(ic.local_address(CLAIM_TEXT_REAL, 'شركة ما لها علاقة', 'مدعى'))

    def test_address_hint_needs_word_boundary(self):
        """«حي» ما تطابق «صيحة»/«صحيفة» (كانت خطأ يختار سطر غلط)."""
        self.assertFalse(ic._has_address_hint('صحيفة دعوى'))
        self.assertTrue(ic._has_address_hint('الفنطاس - قطعة (2) - شارع (13)'))


class ExtractionFallbackTests(unittest.TestCase):
    """الترتيب: ذكاء (موثّق) ← محلي ← طلب موجّه"""

    def test_local_used_when_ai_has_no_address(self):
        reply = json.dumps({'parties': [
            {'role': 'المدعى عليه', 'party': 'عبد الهادي محمد علي المري',
             'address': {'description': ''}}]}, ensure_ascii=False)
        with mock.patch('case_research.default_ask', return_value=reply):
            data, err = ic.extract_party_address_from_text(
                CLAIM_TEXT_REAL, 'عبد الهادي محمد علي المري', 'مدعي عليه')
        self.assertIsNone(err)
        self.assertIn('الفنطاس', data['address']['description'])

    def test_fake_quote_is_rejected(self):
        """اقتباس مو موجود بالنص ⟵ الرد مو موثوق ⟵ نرجع للمحلي."""
        reply = json.dumps({'parties': [
            {'role': 'المدعى عليه', 'party': 'عبد الهادي محمد علي المري',
             'quote': 'عنوان ما وجود له بالصحيفة',
             'address': {'description': 'عنوان مفبرك'}}]}, ensure_ascii=False)
        with mock.patch('case_research.default_ask', return_value=reply):
            data, err = ic.extract_party_address_from_text(
                CLAIM_TEXT_REAL, 'عبد الهادي محمد علي المري', 'مدعي عليه')
        self.assertIsNone(err)
        self.assertIn('الفنطاس', data['address']['description'])

    def test_real_quote_is_accepted(self):
        reply = json.dumps({'parties': [
            {'role': 'المدعى عليه', 'party': 'عبد الهادي محمد علي المري',
             'quote': 'ويعلن في : الفنطاس - قطعة (2)',
             'address': {'description': 'الفنطاس - قطعة (2)'}}]}, ensure_ascii=False)
        with mock.patch('case_research.default_ask', return_value=reply):
            data, err = ic.extract_party_address_from_text(
                CLAIM_TEXT_REAL, 'عبد الهادي محمد علي المري', 'مدعي عليه')
        self.assertIsNone(err)
        self.assertEqual(data['address']['description'], 'الفنطاس - قطعة (2)')

    def test_quote_must_exist_in_text(self):
        self.assertTrue(ic.quote_in_text('الفنطاس - قطعة (2)', CLAIM_TEXT_REAL))
        self.assertFalse(ic.quote_in_text('عنوان ما وجود له', CLAIM_TEXT_REAL))

    def test_whole_text_is_sent(self):
        """نرسل نص صحيفة الدعوى كله — مو صفحتين."""
        seen = {}

        def fake(prompt, task=None, spec=None, timeout=None):
            seen['prompt'] = prompt
            return '{"found": false}'

        text = '<!-- صفحة 1 -->\nأ\n<!-- صفحة 2 -->\nب\n<!-- صفحة 3 -->\nج'
        with mock.patch('case_research.default_ask', fake):
            ic.extract_party_address_from_text(text, 'طرف', 'مدعى')
        self.assertIn('ج', seen['prompt'])
        self.assertNotIn('صفحتين', seen['prompt'])


class ReuseExistingClaimTests(unittest.TestCase):
    """استعمال صحيفة الدعوى الموجودة — بدون تنزيل ولا تحويل (طلب العنزي 15/11/2026)."""

    def _at(self, path, when):
        """تعديل وقت الملف (لاختبار «الأحدث»)."""
        os.utime(path, (when, when))

    def test_newest_copy_wins_over_older_root(self):
        """نسخة قديمة بالجذر + أحدث بمجلد فرعي ⟵ نستعمل الأحدث (ما ننزّل ولا نحوّل)."""
        base, sysdocs, md_dir = _case_folders()
        root_pdf = os.path.join(base, ic.CLAIM_ROOT_PDF)
        with open(root_pdf, 'wb') as f:
            f.write(b'%PDF-1.4 old')
        with open(os.path.join(base, ic.CLAIM_ROOT_MD), 'w', encoding='utf-8') as f:
            f.write('نص قديم')
        new_pdf = os.path.join(sysdocs, ic.CLAIM_FILE_NAME)
        with open(new_pdf, 'wb') as f:
            f.write(b'%PDF-1.4 new')
        new_md = os.path.join(md_dir, 'صحيفة_الدعوى.md')
        with open(new_md, 'w', encoding='utf-8') as f:
            f.write('نص جديد')
        self._at(root_pdf, 1000)
        self._at(os.path.join(base, ic.CLAIM_ROOT_MD), 1100)
        self._at(new_pdf, 2000)
        self._at(new_md, 2100)
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, {})), \
             mock.patch.object(ic, 'fetch_newest_claim') as fetch, \
             mock.patch.object(ic, 'convert_to_markdown') as conv:
            out = ic.ensure_claim_markdown({}, 'A1', '')
        fetch.assert_not_called()
        conv.assert_not_called()
        self.assertTrue(out['ok'])
        self.assertIn('نص جديد', out['text'])
        with open(root_pdf, 'rb') as f:
            self.assertIn(b'new', f.read())

    def test_second_press_reuses_without_download_or_convert(self):
        """ضغط الزر مرة ثانية ⟵ نفس الملف، بلا تنزيل ولا تحويل."""
        base, _sysdocs, _md = _case_folders()
        with open(os.path.join(base, ic.CLAIM_ROOT_PDF), 'wb') as f:
            f.write(b'%PDF-1.4 test')
        with open(os.path.join(base, ic.CLAIM_ROOT_MD), 'w', encoding='utf-8') as f:
            f.write('نص صحيفة الدعوى')
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, {})), \
             mock.patch.object(ic, 'fetch_newest_claim') as fetch, \
             mock.patch.object(ic, 'convert_to_markdown') as conv:
            first = ic.ensure_claim_markdown({}, 'A1', '260668600')
            second = ic.ensure_claim_markdown({}, 'A1', '260668600')
        fetch.assert_not_called()
        conv.assert_not_called()
        self.assertTrue(first['ok'] and second['ok'])
        self.assertEqual(first['text'], second['text'])

    def test_older_markdown_is_converted_again(self):
        """مارك داون أقدم من الـPDF ⟵ نصها لنسخة أقدم ⟵ نحوّل من جديد."""
        base, _sysdocs, _md = _case_folders()
        pdf = os.path.join(base, ic.CLAIM_ROOT_PDF)
        with open(pdf, 'wb') as f:
            f.write(b'%PDF-1.4 test')
        with open(os.path.join(base, ic.CLAIM_ROOT_MD), 'w', encoding='utf-8') as f:
            f.write('نص قديم')
        self._at(os.path.join(base, ic.CLAIM_ROOT_MD), 1000)
        self._at(pdf, 2000)
        with mock.patch.object(ic, 'ensure_case_dir', return_value=(base, {})), \
             mock.patch.object(ic, 'fetch_newest_claim') as fetch, \
             mock.patch.object(ic, 'convert_to_markdown',
                               return_value=('نص مضمون', 2, 'test')) as conv:
            out = ic.ensure_claim_markdown({}, 'A1', '260668600')
        fetch.assert_not_called()
        conv.assert_called_once()
        self.assertTrue(out['ok'])
        self.assertEqual(out['text'], 'نص مضمون')

    def test_find_local_claim_returns_newest_copy(self):
        """«find_local_claim» ترجّع الأحدث — مو أي نسخة."""
        base, sysdocs, _md = _case_folders()
        root_pdf = os.path.join(base, ic.CLAIM_ROOT_PDF)
        with open(root_pdf, 'wb') as f:
            f.write(b'%PDF-1.4 old')
        new_pdf = os.path.join(sysdocs, ic.CLAIM_FILE_NAME)
        with open(new_pdf, 'wb') as f:
            f.write(b'%PDF-1.4 new')
        self._at(root_pdf, 1000)
        self._at(new_pdf, 2000)
        with mock.patch.object(ic, '_case_base', return_value=base):
            got = ic.find_local_claim('A1')
        self.assertEqual(got, new_pdf)


if __name__ == '__main__':
    unittest.main()
