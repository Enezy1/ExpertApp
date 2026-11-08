# اختبارات جودة الصحيفة وصيغة الموضوع وقائمة السياق: python -W ignore -m unittest test_claim_quality -v
import case_subject_mission as _sm_style
_sm_style.STYLE = 'formula'          # هذه الاختبارات للقوالب القديمة؛ الكتابة بالذكاء في test_subject_style.py
import json
import os
import re
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit

import case_subject_contract as sc
import case_subject_telecom as st
import qt_context_menu as cmenu

APP = QApplication.instance() or QApplication([])
P = ('بموجب عقد رقم 201814119 مؤرخ 10/01/2025 اتفقت مع المدعى غليه على توريد أجهزة، مقابل مبلغ 12,500 د.ك لمدة 6 أشهر، '
     'وأنها نفذت التزاماتها إلا أن المدعى عليه لم يسدد قيمة الأعمال.')


def ask(**over):
    r = {'contracts': [{'number': '201814119', 'date': '201814119', 'object': 'اتفقت مع المدعى عليه على توريد أجهزة',
                        'amount': '12,500 د.ك', 'duration': '6 أشهر'}],
         'performed': 'نفذت التزاماتها', 'breach': 'لم يسدد قيمة الأعمال'}
    r.update(over)
    return lambda prompt: json.dumps(r, ensure_ascii=False)


class MenuTests(unittest.TestCase):
    def test_arabic_labels_no_unicode_control(self):
        for cls in (QLineEdit, QTextEdit, QPlainTextEdit):
            w = cls()
            texts = ' '.join(a.text() for a in cmenu.build_menu(w).actions())
            for lab in ('تراجع', 'إعادة', 'قص', 'نسخ', 'لصق', 'حذف', 'تحديد الكل'):
                self.assertIn(lab, texts)
            self.assertNotIn('Unicode', texts)
            self.assertNotIn('Undo', texts)

    def test_readonly_hides_edit_actions(self):
        w = QLineEdit()
        w.setReadOnly(True)
        texts = ' '.join(a.text() for a in cmenu.build_menu(w).actions())
        self.assertNotIn('قص', texts)
        self.assertIn('نسخ', texts)

    def test_light_style_and_font(self):
        self.assertIn('#FFFFFF', cmenu.MENU_QSS)
        self.assertIn('IBM Plex Sans Arabic', cmenu.MENU_QSS)


class SubjectTests(unittest.TestCase):
    def test_number_is_not_a_date(self):
        for mod in (sc,):
            b = mod.build_subject(P, ['فلان'], ask())
            self.assertIn('رقم 201814119 مؤرخ [يُكتب]', b['text'])
        self.assertIsNone(st.find_date('201814119'))
        self.assertEqual(st.find_date('10/01/2025'), '10/01/2025')
        self.assertIsNone(st.find_date('31/02/2025'))

    def test_defendant_forms(self):
        self.assertIn('المدعى عليه أخلّ', sc.build_subject(P, ['فلان'], ask())['text'])
        self.assertIn('المدعى عليهم أخلّوا', sc.build_subject(P, ['أ', 'ب'], ask())['text'])
        self.assertIn('المدعى عليها أخلّت', sc.build_subject(P, ['شركة الأمل'], ask())['text'])

    def test_links(self):
        self.assertEqual(sc.link_for('لم يسدد')[0], 'بأن')
        self.assertEqual(sc.link_for('عدم سداد')[1], 'بعدم سداد')
        self.assertEqual(sc.link_for('أنه امتنع')[0], 'إذ')
        self.assertEqual(sc.link_for('سداد القيمة')[0], 'في')

    def test_missing_fields_replace_whole_segment(self):
        for over in ({'performed': None}, {'breach': None}, {'performed': None, 'breach': None}):
            t = sc.build_subject(P, ['فلان'], ask(**over))['text']
            self.assertNotRegex(t, r'أنها \[يُكتب\]')
            self.assertNotRegex(t, r'(?:أخلّ|أخلّت|أخلّوا) (?:في|بأن|إذ) \[يُكتب\]')

    def test_ocr_fix_recorded_numbers_untouched(self):
        b = sc.build_subject(P, ['فلان'], ask())
        self.assertEqual([f[:2] for f in b['ocr_fixes']], [('غليه', 'عليه')])
        self.assertIn('12,500', b['text'])
        self.assertIn('201814119', b['text'])


class QualityTests(unittest.TestCase):
    def test_weak_plaint_warns(self):
        import doc_router as dr
        bad = 'ا1ل|مدءى عليهة ااالل ببببب فيي ممنن ءلى 5لدعوى ' * 12
        self.assertIn(dr.WEAK_MESSAGE, dr.quality_warning(dr.T_PLAINT, bad))
        self.assertEqual(dr.quality_warning(dr.T_MINUTES, bad), '')


if __name__ == '__main__':
    unittest.main()
