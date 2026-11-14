# -*- coding: utf-8 -*-
# اختبارات صفحة «القضايا المحالة» (Qt):
#   • زر «الملف الآلي» موجود في كل إحالة.
#   • الملفات تنحفظ **داخل مجلد القضية** في «تقارير الخبراء» (مو على سطح المكتب).
#   • بدون رقم آلي ⟵ رسالة واضحة (مو crash).
#   python -W ignore -m unittest test_qt_referred_page_v2 -v
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QPushButton

import qt_referred_page_v2 as qr

APP = QApplication.instance() or QApplication([])

CASE = {'caso_no': 'A2264212', 'plaintiff': 'شركة كذا', 'date': '10/11/2026',
        'from_dept': 'قسم فني', 'from_emp': 'رئيس القسم', 'notes': '',
        'autocase_no': '260668600', 'task_id': '123', 'req_no': '9',
        'to_dept': 'قسم هندسي', 'is_secondment': False}


class AutoFileButtonTests(unittest.TestCase):
    """زر «الملف الآلي» — يفتح حكم الإحالة وصحيفة الدعوى قبل الاستلام"""

    def setUp(self):
        self.card = qr.ReferredCaseCard(dict(CASE), {'s': '1'})

    def test_button_exists(self):
        labels = [b.text() for b in self.card.findChildren(QPushButton)]
        self.assertIn('الملف الآلي', labels)

    def test_click_without_auto_number_shows_message(self):
        """ما فيه رقم آلي ⟵ رسالة واضحة (ما يكسر ولا يNetwork)."""
        case = dict(CASE)
        case['autocase_no'] = ''
        card = qr.ReferredCaseCard(case, {'s': '1'})
        with mock.patch.object(qr.QMessageBox, 'information') as info:
            card._open_auto_file()
        self.assertTrue(info.called)


class FetchAutoFileTests(unittest.TestCase):
    """السحب — ينحفظ داخل مجلد القضية في «تقارير الخبراء»"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='ilann_referred_')
        self.addCleanup(_rmtree, self.tmp)

    def test_saves_into_case_folder_under_reports_root(self):
        """الملفات تنزل في `<تقارير الخبراء>\\<رقم الخبرة>\\مستندات_النظام`."""
        saved = {}

        def fake_bundle(cookies, autocase_no, user_id, out_dir):
            saved['out_dir'] = out_dir
            path = os.path.join(out_dir, 'حكم_الإحالة.pdf')
            with open(path, 'wb') as f:
                f.write(b'%PDF-1.4 test')
            return {'judgment': path, 'claim': None, 'report': None}

        import case_workspace
        import case_folder
        with mock.patch.object(case_workspace, 'ensure_workspace',
                               return_value=(self.tmp, {})), \
             mock.patch('documents.get_case_documents_bundle', side_effect=fake_bundle):
            res = qr.fetch_auto_file('A2264212', '260668600', {'s': '1'})

        self.assertTrue(res['ok'])
        self.assertEqual(res['folder'],
                         os.path.join(self.tmp, case_folder.SYSDOCS))
        self.assertTrue(res['open'].endswith('حكم_الإحالة.pdf'))

    def test_no_documents_returns_clear_message(self):
        import case_workspace
        with mock.patch.object(case_workspace, 'ensure_workspace',
                               return_value=(self.tmp, {})), \
             mock.patch('documents.get_case_documents_bundle',
                        return_value={'judgment': None, 'claim': None, 'report': None}):
            res = qr.fetch_auto_file('A2264212', '260668600', {'s': '1'})
        self.assertFalse(res['ok'])
        self.assertIn('ما فيه مستندات', res['message'])


def _rmtree(path):
    import shutil
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
