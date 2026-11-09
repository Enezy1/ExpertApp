# اختبارات صفحة «الإعدادات» (Qt) — مهمة⑱ (9/11/2026)
#   1) ضغط الواجهة: بطاقتا المفاتيح جنب بعض، وكل مزوّد بسطر مضغوط
#   2) بيانات الخبير بعمودين جنب بعض
#   3) المحافظة/القسم تجي تلقائياً من سجل الحركة (والحقول الفاضية فقط)
#   4) أولوية المحافظة/القسم: النظام ← إعدادات الخبير
#   python -W ignore -m unittest test_qt_settings_page -v
import os
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import (
    QApplication, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)

import qt_settings_page as sp
import expert_settings

APP = QApplication.instance() or QApplication([])

EXPERT = 'محمد عبدالله فرحان العنزى'


def _make_page():
    """صفحة إعدادات نظيفة — بلا شبكة ولا Supabase."""
    with mock.patch.object(sp.main1_access, 'is_owner', return_value=False), \
            mock.patch('gemini_config.is_admin', return_value=False), \
            mock.patch('ai_providers.get_provider_configs', return_value=[]), \
            mock.patch('provider_sync.is_shared', return_value=False):
        return sp.SettingsPage(cookies={}, current_user=EXPERT)


def _card_with_title(page, title_text):
    """بطاقة (Card) اللي عنوانها بالسطر المعطى."""
    for w in page.findChildren(QLabel):
        if w.text() != title_text:
            continue
        node = w
        while node is not None:
            parent = node.parentWidget()
            if parent is not None and parent.__class__.__name__ == 'Card':
                return parent
            node = parent
    return None


class SettingsLayoutTests(unittest.TestCase):
    """ضغط الواجهة — أقل تمرير وأقل مساحات."""

    def setUp(self):
        self.page = _make_page()

    def test_ai_section_before_ocr(self):
        """الذكاء الاصطناعي فوق قراءة المستندات (OCR)."""
        import inspect
        src = inspect.getsource(sp.SettingsPage._build)
        self.assertLess(src.index('مفاتيح الذكاء الاصطناعي'),
                        src.index('قراءة المستندات (OCR)'))

    def test_keys_sections_stacked_not_side_by_side(self):
        """القسمان تحت بعض (بطاقتين منفصلتين) مو جنب بعض."""
        import inspect
        src = inspect.getsource(sp.SettingsPage._build)
        ai = src.index("('gemini', 'openai')")
        ocr = src.index("('vision', 'ocrspace')")
        self.assertLess(ai, ocr, 'الذكاء الاصطناعي لازم يكون قبل OCR')
        block = src[ai:ocr]
        self.assertNotIn('QHBoxLayout', block,
                         'ما في صف جنب بعض — كل قسم تحت بعض')

    def test_section_titles_look_like_list_headers(self):
        """عنوان كل قسم: عنوان عريض + سطر شرح (ستايل قوائم قوقل)."""
        for title in ('🔑 مفاتيح الذكاء الاصطناعي', '📄 قراءة المستندات (OCR)'):
            labels = [w for w in self.page.findChildren(QLabel) if w.text() == title]
            self.assertTrue(labels, f'العنوان «{title}» مفقود')
            lbl = labels[0]
            self.assertIn('font-weight:800', lbl.styleSheet())

    def test_no_section_chips(self):
        """«القسم الأول»/«القسم الثاني» اتشالوا — مالها معنى (طلب العنزي 10/11)."""
        texts = [w.text() for w in self.page.findChildren(QLabel)]
        self.assertNotIn('القسم الأول', texts)
        self.assertNotIn('القسم الثاني', texts)

    def test_no_model_badge(self):
        """«مفتاحك يتيح: <النموذج>» اتشال — مالها معنى (طلب العنزي 10/11)."""
        texts = [w.text() for w in self.page.findChildren(QLabel)]
        self.assertFalse([t for t in texts if 'مفتاحك يتيح' in t])
        self.assertFalse(hasattr(sp.SettingsPage, 'caps_text'))

    def test_openai_note_removed(self):
        """«اشتراك ChatGPT Plus لا يكفي…» اتشال."""
        texts = [w.text() for w in self.page.findChildren(QLabel)]
        self.assertFalse([t for t in texts if 'ChatGPT Plus' in t])

    def test_link_is_last_on_the_left(self):
        """الرابط آخر يسار في كل الصفوف (زي Gemini)."""
        for which in ('vision', 'ocrspace', 'gemini', 'openai'):
            link = self.page._key_widgets[which]['link']
            row = link.parentWidget()
            lay = row.layout().itemAt(1).layout()   # سطر 2
            self.assertIs(lay.itemAt(lay.count() - 1).widget(), link,
                          f'رابط {which} لازم يكون آخر يسار')

    def test_each_provider_is_one_compact_row(self):
        """كل مزوّد: خانة مفتاح + ٤ أزرار (لصق/حفظ/اختبار/حذف)."""
        for which in ('vision', 'ocrspace', 'gemini', 'openai'):
            w = self.page._key_widgets.get(which)
            self.assertIsNotNone(w, f'مزوّد {which} مفقود')
            self.assertIsInstance(w['entry'], QLineEdit)
        row = self.page._key_widgets['vision']['entry'].parentWidget()
        texts = [b.text() for b in row.findChildren(QPushButton)]
        for expected in ('📋 لصق', '💾 حفظ', '🧪 اختبار', '🗑 حذف'):
            self.assertIn(expected, texts, f'زر «{expected}» مفقود بصف المزوّد')

    def test_provider_rows_have_status_and_link(self):
        for which in ('vision', 'ocrspace', 'gemini', 'openai'):
            w = self.page._key_widgets[which]
            self.assertTrue(hasattr(w['status'], 'setText'))
            self.assertTrue(hasattr(w['link'], 'setText'))

    def test_expert_fields_one_row_each(self):
        """كل حقل سطر واحد: التسمية يمين والحقل يسار — والحقول تحت بعض."""
        for attr in ('specialty_entry', 'maqar_entry', 'dor_entry', 'maktab_entry',
                     'janah_entry', 'gov_entry', 'dept_entry'):
            entry = getattr(self.page, attr)
            row = entry.parentWidget()
            lay = row.layout()
            self.assertIsInstance(lay, QHBoxLayout, f'{attr}: لازم سطر واحد')
            first = lay.itemAt(0).widget()
            self.assertIsInstance(first, QLabel, f'{attr}: التسمية أول (يمين)')
            self.assertIs(lay.itemAt(1).widget(), entry)

    def test_no_two_column_grid(self):
        """رجّعنا الحقول لعمود واحد (10/11) — ما في شبكة عمودين."""
        for w in self.page.findChildren(QGridLayout):
            self.fail('في شبكة عمودين — المفروض عمود واحد')

    def test_expert_fields_present(self):
        for attr in ('specialty_entry', 'maqar_entry', 'dor_entry', 'maktab_entry',
                     'janah_entry', 'gov_entry', 'dept_entry'):
            self.assertIsInstance(getattr(self.page, attr), QLineEdit, attr)

    def test_gov_placeholder_mentions_autofill(self):
        self.assertIn('تلقائي', self.page.gov_entry.placeholderText())
        self.assertIn('تلقائي', self.page.dept_entry.placeholderText())


class AutoHeaderTests(unittest.TestCase):
    """المحافظة/القسم: من سجل الحركة، وتعبّي الحقول الفاضية فقط."""

    def setUp(self):
        self.page = _make_page()

    def test_fetch_section_from_system(self):
        import case_db
        with mock.patch.object(case_db, 'get_active_cases', return_value={'A2264146'}), \
                mock.patch.object(case_db, 'get_case', return_value={
                    'caso_no': 'A2264146', 'expert_name': EXPERT,
                    'updated_at': '2026-11-09 08:52'}), \
                mock.patch('api.parse_case_info', return_value={
                    'governorate': 'العاصمة',
                    'department': 'قسم قضايا الكهرباء والكمبيوتر العاصمه'}):
            out = self.page._fetch_section_fields()
        self.assertEqual(out.get('governorate'), 'العاصمة')
        self.assertEqual(out.get('department'), 'قسم قضايا الكهرباء والكمبيوتر العاصمه')

    def test_fetch_section_returns_empty_on_failure(self):
        import case_db
        with mock.patch.object(case_db, 'get_active_cases', return_value=set()), \
                mock.patch.object(case_db, 'get_all_caso_nos', return_value=set()), \
                mock.patch('api.parse_case_info', side_effect=RuntimeError('offline')):
            self.assertEqual(self.page._fetch_section_fields(), {})

    def test_apply_profile_fills_empty_fields_only(self):
        self.page.gov_entry.setText('العاصمة')      # موجود مسبقاً — ما ينكتب فوقه
        self.page.dept_entry.setText('')             # فاضي — ينعبّى
        with mock.patch.object(sp, 'save_specialty'), \
                mock.patch.object(sp, 'save_location'), \
                mock.patch('expert_settings.save_report_header'):
            self.page._apply_profile({'governorate': 'حولي',
                                      'department': 'قسم قضايا الكهرباء حوليه'})
        self.assertEqual(self.page.gov_entry.text(), 'العاصمة')
        self.assertEqual(self.page.dept_entry.text(), 'قسم قضايا الكهرباء حوليه')

    def test_apply_profile_does_not_touch_manual_values(self):
        self.page.gov_entry.setText('حولي')
        self.page.dept_entry.setText('قسم حدودي')
        with mock.patch.object(sp, 'save_specialty'), \
                mock.patch.object(sp, 'save_location'), \
                mock.patch('expert_settings.save_report_header'):
            self.page._apply_profile({'governorate': 'العاصمة',
                                      'department': 'قسم قضايا الكهرباء العاصمه'})
        self.assertEqual(self.page.gov_entry.text(), 'حولي')
        self.assertEqual(self.page.dept_entry.text(), 'قسم حدودي')


class ResolveHeaderTests(unittest.TestCase):
    """أولوية المحافظة/القسم: النظام ← إعدادات الخبير."""

    def test_system_wins(self):
        with mock.patch.object(expert_settings, 'load_report_header',
                               return_value={'governorate': 'حولي', 'department': 'قسم حدودي'}):
            gov, dep = expert_settings.resolve_report_header(
                {'governorate': 'العاصمة', 'department': 'قسم الكهرباء العاصمه'})
        self.assertEqual(gov, 'العاصمة')
        self.assertEqual(dep, 'قسم الكهرباء العاصمه')

    def test_settings_used_when_system_empty(self):
        with mock.patch.object(expert_settings, 'load_report_header',
                               return_value={'governorate': 'حولي', 'department': 'قسم حدودي'}):
            gov, dep = expert_settings.resolve_report_header(
                {'governorate': '', 'department': ''})
        self.assertEqual(gov, 'حولي')
        self.assertEqual(dep, 'قسم حدودي')

    def test_both_empty_returns_empty(self):
        with mock.patch.object(expert_settings, 'load_report_header',
                               return_value={'governorate': '', 'department': ''}):
            gov, dep = expert_settings.resolve_report_header({})
        self.assertEqual(gov, '')
        self.assertEqual(dep, '')


if __name__ == '__main__':
    unittest.main()
