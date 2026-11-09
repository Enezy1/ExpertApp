# اختبارات صفحة «إضافة قضية جديدة» (Qt) — مهمة⑰ (9/11/2026)
#   1) عجلة الفأرة ما تغيّر قيمة القوائم (وتمرّر الصفحة بدالها)
#   2) ترتيب عربي: التسمية يمين والحقل يسار
#   3) 3 خبراء مسجّلون ⇐ «لجنة ثلاثية» تلقائياً
#   4) التخصص يُختار تلقائياً حسب تخصص الخبير المسجّل بقاعدة القسم
#   5) زر المعاينة 👁: صحيفة الدعوى فوق وحكم الإحالة تحت — بنفس الملف
#   python -W ignore -m unittest test_qt_main1 -v
import os
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QPushButton,
)

import qt_main1 as m1

APP = QApplication.instance() or QApplication([])

EXPECTED_BUTTONS = [
    '✅ إضافة للقاعدة',
    '🔄 إعادة الاستخراج',
    '📎 رفع حكم إحالة يدويًا',
    '🖨️ طباعة ملصق نصف ورقة',
    '👁',
]


def _wheel():
    """حدث عجلة فأرة (لفوق 120 درجة)."""
    return QWheelEvent(
        QPointF(5, 5),          # position
        QPointF(5, 5),          # globalPosition
        QPoint(0, 0),           # pixelDelta
        QPoint(0, 120),         # angleDelta
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,                  # inverted
    )


def _make_page():
    """صفحة «إضافة قضية» نظيفة + نموذج مراجعة مبني (بدون شبكة ولا قاعدة)."""
    with mock.patch.object(m1, 'get_expert_names', return_value=[]):
        page = m1.Main1Page(None, {}, 'خبير تجريبي')
    page.extracted = {'caso_no': 'A2264164', 'autocase_no': '262208250'}
    with mock.patch.object(m1, 'get_expert_names', return_value=[]):
        page._render_review_form()
    return page


class WheelOnComboTests(unittest.TestCase):
    """عجلة الفأرة كانت تغيّر قيمة القوائم تلقائياً (الخبير/النوع/التخصص)."""

    def setUp(self):
        self.page = _make_page()

    def test_wheel_event_is_swallowed_by_combo(self):
        combo = self.page.entries.get('comm')
        self.assertIsInstance(combo, QComboBox)
        self.assertTrue(self.page.eventFilter(combo, _wheel()),
                        'مرشّح الأحداث لازم يبتلع عجلة الفأرة على القوائم')

    def test_wheel_does_not_change_combo_value(self):
        for key in ('comm', 'type', 'spe'):
            combo = self.page.entries.get(key)
            if not isinstance(combo, QComboBox):
                continue
            before = combo.currentText()
            index_before = combo.currentIndex()
            APP.sendEvent(combo, _wheel())
            self.assertEqual(combo.currentText(), before,
                             f'عجلة الفأرة غيّرت قيمة القائمة «{key}»')
            self.assertEqual(combo.currentIndex(), index_before)

    def test_wheel_passes_through_for_other_widgets(self):
        """العجلة لازم توصل لغير القوائم — عشان الصفحة تتمرّر."""
        self.assertFalse(self.page.eventFilter(self.page.ref_entry, _wheel()),
                         'العجلة لازم تُمرّر لغير القوائم (تمرير الصفحة)')

    def test_every_combo_is_protected(self):
        combos = [w for w in self.page.entries.values()
                  if isinstance(w, QComboBox)]
        self.assertTrue(combos, 'ما فيه قوائم بالنموذج؟')
        for combo in combos:
            self.assertTrue(self.page.eventFilter(combo, _wheel()))


class ArabicOrderTests(unittest.TestCase):
    """ترتيب عربي: التسمية يمين والحقل يسار."""

    def setUp(self):
        self.page = _make_page()

    def _row_of(self, widget):
        """سطر الحقل = تخطيط البطاقة (Card) اللي فيها الحقل."""
        parent = widget.parentWidget()
        lay = parent.layout() if parent is not None else None
        if not isinstance(lay, QHBoxLayout):
            return None, -1
        for j in range(lay.count()):
            if lay.itemAt(j).widget() is widget:
                return lay, j
        return None, -1

    def test_page_is_right_to_left(self):
        self.assertEqual(self.page.layoutDirection(),
                         Qt.LayoutDirection.RightToLeft)

    def test_label_comes_before_field(self):
        for key in ('ref', 'name_c', 'name_p', 'reg_date_r', 'boss_est'):
            widget = self.page.entries.get(key)
            self.assertIsNotNone(widget, f'الحقل «{key}» مفقود')
            lay, idx = self._row_of(widget)
            self.assertIsNotNone(lay, f'ما لقيت سطر الحقل «{key}»')
            first = lay.itemAt(0).widget()
            self.assertIsInstance(first, QLabel,
                                  f'الحقل «{key}» لازم يكون بعد التسمية')
            self.assertIsNot(first, widget)
            self.assertGreater(idx, 0)

    def test_label_comes_before_combo(self):
        for key in ('comm', 'type', 'spe'):
            combo = self.page.entries.get(key)
            if not isinstance(combo, QComboBox):
                continue
            lay, idx = self._row_of(combo)
            self.assertIsNotNone(lay, f'ما لقيت سطر القائمة «{key}»')
            self.assertIsInstance(lay.itemAt(0).widget(), QLabel,
                                  f'القائمة «{key}» لازم تكون يسار التسمية')
            self.assertGreater(idx, 0)


class CommitteeAutoTests(unittest.TestCase):
    """3 خبراء مسجّلون على القضية ⇐ «لجنة ثلاثية» تلقائياً."""

    def _lookup(self, n_experts):
        page = _make_page()
        exps = [{'name': f'خبير {i}'} for i in range(1, n_experts + 1)]
        with mock.patch.object(m1.case_db, 'get_case', return_value=None), \
                mock.patch.object(m1, '_get_autocase_no', return_value='262208250'), \
                mock.patch.object(m1, 'parse_case_info',
                                  return_value={'plaintiffs': [], 'defendants': []}), \
                mock.patch.object(m1, 'get_case_type', return_value=''), \
                mock.patch.object(m1, 'get_experts', return_value=exps), \
                mock.patch.object(m1.Main1Page, '_extract_via_ai',
                                  return_value=({}, False)), \
                mock.patch('db_writer.get_expert_specialty', return_value=''), \
                mock.patch('expert_settings.load_specialty', return_value=''):
            result, _, _ = page._lookup_case('A2264164', {})
        return result

    def test_three_experts_committee(self):
        result = self._lookup(3)
        self.assertEqual(result.get('comm'), 'لجنة ثلاثية')

    def test_five_experts_committee(self):
        result = self._lookup(5)
        self.assertEqual(result.get('comm'), 'لجنة ثلاثية')

    def test_two_experts_not_committee(self):
        result = self._lookup(2)
        self.assertNotEqual(result.get('comm'), 'لجنة ثلاثية')

    def test_expert_names_still_filled(self):
        result = self._lookup(3)
        self.assertEqual(result.get('expr_name1'), 'خبير 1')
        self.assertEqual(result.get('expr_name3'), 'خبير 3')


class SpecialtyAutoTests(unittest.TestCase):
    """التخصص يُختار حسب تخصص الخبير المسجّل (مو 'كهرباء 15' دائماً)."""

    def setUp(self):
        self.page = _make_page()

    def _apply(self, db_value, settings_value):
        result = {'expr_name1': 'أحمد الغانم'}
        with mock.patch('db_writer.get_expert_specialty', return_value=db_value), \
                mock.patch('expert_settings.load_specialty',
                           return_value=settings_value):
            self.page._apply_specialty_auto(result)
        return result

    def test_specialty_from_section_db(self):
        result = self._apply('كمبيوتر 24', '')
        self.assertEqual(result.get('spe'), 'كمبيوتر 24')

    def test_specialty_electric_from_db(self):
        result = self._apply('كهرباء 15', '')
        self.assertEqual(result.get('spe'), 'كهرباء 15')

    def test_fallback_to_current_expert_specialty(self):
        result = self._apply('', 'حاسب آلي')
        self.assertEqual(result.get('spe'), 'كمبيوتر 24')

    def test_fallback_electric_from_settings(self):
        result = self._apply('', 'كهرباء')
        self.assertEqual(result.get('spe'), 'كهرباء 15')

    def test_nothing_known_keeps_default(self):
        result = self._apply('', '')
        self.assertNotIn('spe', result)

    def test_db_helper_empty_name_returns_empty(self):
        import db_writer
        self.assertEqual(db_writer.get_expert_specialty(''), '')
        self.assertEqual(db_writer.get_expert_specialty(None), '')


class PreviewMergedTests(unittest.TestCase):
    """
    زر المعاينة 👁 (10/11/2026): يفتح نافذة المعاينة الأصلية (مع زر طباعة)
    على **ملف واحد**: صحيفة الدعوى فوق وحكم الإحالة تحتها.
    """

    def setUp(self):
        self.page = _make_page()

    def _button_texts(self):
        return [b.text() for b in self.page.findChildren(QPushButton)]

    def test_eye_button_exists(self):
        self.assertIn('👁', self._button_texts())

    def test_no_separate_print_buttons(self):
        """زري الطباعة المغلوطة — اتشالوا (طلب العنزي 10/11)."""
        texts = self._button_texts()
        self.assertNotIn('🖨️ طباعة حكم الإحالة', texts)
        self.assertNotIn('🖨️ طباعة صحيفة الدعوى', texts)

    def test_all_five_buttons_present(self):
        texts = self._button_texts()
        for expected in EXPECTED_BUTTONS:
            self.assertIn(expected, texts, f'الزر «{expected}» مفقود')

    def test_merge_keeps_order(self):
        """الملف المدمج: صفحة صحيفة الدعوى أول، ثم حكم الإحالة."""
        import fitz
        import os
        import tempfile
        d = tempfile.mkdtemp()
        claim = os.path.join(d, 'claim.pdf')
        judgment = os.path.join(d, 'judgment.pdf')
        merged = os.path.join(d, 'merged.pdf')
        for path, text in ((claim, 'CLAIM'), (judgment, 'JUDGMENT')):
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), text)
            doc.save(path)
            doc.close()
        m1._merge_pdfs([claim, judgment], merged)
        with fitz.open(merged) as doc:
            self.assertEqual(doc.page_count, 2)
            self.assertIn('CLAIM', doc[0].get_text())
            self.assertIn('JUDGMENT', doc[1].get_text())

    def test_preview_opens_one_merged_file(self):
        import fitz
        import os
        import tempfile
        d = tempfile.mkdtemp()
        claim = os.path.join(d, 'claim.pdf')
        judgment = os.path.join(d, 'judgment.pdf')
        for path, text in ((claim, 'CLAIM'), (judgment, 'JUDGMENT')):
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), text)
            doc.save(path)
            doc.close()
        self.page.extracted['caso_no'] = 'A2264164'
        self.page.extracted['autocase_no'] = '262208250'
        self.page.extracted['judgment_path'] = judgment
        with mock.patch.object(m1.Main1Page, '_print_dir', return_value=d), \
                mock.patch('documents.get_claim_for_case',
                           return_value=(None, claim, 'OK')), \
                mock.patch('qt_case_lookup.show_pdf_preview') as preview:
            self.page._on_preview_merged_clicked()
        preview.assert_called_once()
        merged = preview.call_args[0][1]
        self.assertTrue(os.path.exists(merged))
        with fitz.open(merged) as doc:
            self.assertEqual(doc.page_count, 2)
            self.assertIn('CLAIM', doc[0].get_text())
            self.assertIn('JUDGMENT', doc[1].get_text())

    def test_preview_without_extraction_warns(self):
        self.page.extracted = {}
        with mock.patch.object(m1.QMessageBox, 'warning') as warn:
            self.page._on_preview_merged_clicked()
        self.assertEqual(warn.call_count, 1)

    def test_print_dir_is_judgments_folder(self):
        d = self.page._print_dir()
        self.assertTrue(d.endswith('judgments'), d)
        self.assertTrue(os.path.isdir(d))


if __name__ == '__main__':
    unittest.main()
