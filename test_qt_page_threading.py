# اختبارات عدم تجميد صفحتَي «القضايا المحالة» و«الجلسات» (المهمة⑥):
#   الجلب يتم في خيط خلفي — لا يجوز أن تجمّد الواجهة.
#   python -W ignore -m unittest test_qt_page_threading -v
import os
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

import qt_referred_page_v2 as qr
import qt_sessions_page as qss

APP = QApplication.instance() or QApplication([])

CASE = {'caso_no': 'A2263973', 'title': 'شركة كذا ضد كذا',
        'received_date': '2026-10-06', 'autocase_no': '261932780',
        'description': 'A2263973', 'start': '2026-10-20 09:00', 'title_': '',
        # مفاتيح بطاقة «القضايا المحالة»
        'plaintiff': 'شركة كذا', 'date': '2026-10-20', 'from_dept': 'قسم فني',
        'from_emp': 'رئيس القسم', 'notes': '', 'is_secondment': False}

# جلسة بتاريخ داخل نافذة العرض (اليوم → +30 يوم) — عشان ما تترشّح.
# العنوان في نظام الوزارة يبدأ برقم القضية — فبعد شيله يصير فاضي
# (وهذا بالضبط الحالة اللي بتجلب العنوان الاحتياطي).
SESSION = dict(CASE)
SESSION['start'] = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d') + ' 09:00'
SESSION['title'] = 'A2263973'


def pump(predicate, secs=15):
    end = time.time() + secs
    while time.time() < end:
        APP.processEvents()
        if predicate():
            APP.processEvents()
            return True
        time.sleep(0.01)
    APP.processEvents()
    return False


class ReferredPageThreadingTests(unittest.TestCase):
    """صفحة القضايا المحالة"""

    def setUp(self):
        self.page = qr.ReferredCasesPage({'s': '1'}, 'خبير تجريبي')
        self._patches = [
            mock.patch.object(qr, 'get_referred_cases', return_value=[dict(CASE)]),
            mock.patch.object(qr, 'claim_summary_initial', return_value=('skip', '')),
            mock.patch.object(qr.mo, '_MOTION', False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        end = time.time() + 5
        while self.page._loading and time.time() < end:
            APP.processEvents()
            time.sleep(0.02)
        time.sleep(0.15)
        APP.processEvents()
        for p in self._patches:
            p.stop()
        self.page.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def test_load_does_not_block_the_ui_thread(self):
        """طلبان شبكيان بمهلة 15 ثانية — لازم load_cases ترجع فوراً"""
        def slow(*_a, **_k):
            time.sleep(1.0)
            return [dict(SESSION)]

        with mock.patch.object(qr, 'get_referred_cases', side_effect=slow):
            start = time.time()
            self.page.load_cases()
            elapsed = time.time() - start
        self.assertLess(elapsed, 0.3,
                        'load_cases تجمّدت خيط الواجهة — رجعنا بعد %.2f ثانية' % elapsed)
        APP.processEvents()
        self.assertTrue(self.page.isEnabled())

    def test_results_applied_on_ui_thread(self):
        self.page.load_cases()
        self.assertTrue(pump(lambda: self.page._loading is False),
                        'ما وصلت النتائج للواجهة')
        self.assertEqual(self.page.kpi_total.value_label.text(), '2')
        self.assertEqual(self.page.kpi_secondment.value_label.text(), '1')

    def test_refresh_while_loading_does_not_start_second_fetch(self):
        calls = []

        def slow(*_a, **_k):
            calls.append(1)
            time.sleep(0.6)
            return [dict(SESSION)]

        with mock.patch.object(qr, 'get_referred_cases', side_effect=slow):
            self.page.load_cases()
            self.page.load_cases()
            self.page.load_cases()
            self.assertEqual(len(calls), 1, 'تكرر الجلب — أكثر من خيط واحد')
            self.assertTrue(pump(lambda: self.page._loading is False))

    def test_error_handled_on_ui_thread(self):
        with mock.patch.object(qr, 'get_referred_cases', side_effect=OSError('network down')):
            self.page.load_cases()
            self.assertTrue(pump(lambda: self.page._loading is False))
            self.assertEqual(self.page.kpi_total.value_label.text(), '—')

    def test_stale_result_is_ignored(self):
        self.page._load_token = 99
        self.page._apply_data({'token': 1, 'cases': [dict(CASE)], 'secondment_count': 0})
        self.assertEqual(self.page.kpi_total.value_label.text(), '0',
                         'نتيجة قديمة طبقت نفسها على الواجهة')


class SessionsPageThreadingTests(unittest.TestCase):
    """صفحة الجلسات"""

    def setUp(self):
        self.page = qss.SessionsPage({'s': '1'}, 'خبير تجريبي')
        self._patches = [
            mock.patch.object(qss, 'get_sessions', return_value=[dict(SESSION)]),
            mock.patch.object(qss, 'case_db', mock.MagicMock()),
            mock.patch.object(qss.mo, '_MOTION', False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        end = time.time() + 5
        while self.page._loading and time.time() < end:
            APP.processEvents()
            time.sleep(0.02)
        time.sleep(0.15)
        APP.processEvents()
        for p in self._patches:
            p.stop()
        self.page.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def test_load_sessions_does_not_block_the_ui_thread(self):
        def slow(*_a, **_k):
            time.sleep(1.0)
            return [dict(SESSION)]

        with mock.patch.object(qss, 'get_sessions', side_effect=slow):
            start = time.time()
            self.page.load_sessions()
            elapsed = time.time() - start
        self.assertLess(elapsed, 0.3,
                        'load_sessions تجمّدت خيط الواجهة — %.2f ثانية' % elapsed)
        APP.processEvents()
        self.assertTrue(self.page.isEnabled())

    def test_sessions_applied_on_ui_thread(self):
        self.page.load_sessions()
        self.assertTrue(pump(lambda: self.page._loading is False))
        self.assertEqual(len(self.page.sessions_data), 1)

    def test_title_fallback_is_prefetched_off_the_ui_thread(self):
        """العنوان الناقص لازم يُجلب قبل العرض — مو وقت إنشاء البطاقة"""
        calls = []

        def fake_fallback(caso_no):
            calls.append(caso_no)
            return 'عنوان'

        with mock.patch.object(qss, 'get_sessions', return_value=[dict(SESSION)]), \
                mock.patch.object(self.page, '_get_title_fallback', side_effect=fake_fallback):
            self.page.load_sessions()
            self.assertTrue(pump(lambda: self.page._loading is False))
            self.assertIn('A2263973', calls, 'ما جلبنا العنوان مسبقاً')

    def test_no_network_call_during_render(self):
        """وقت العرض (بناء البطاقات) ما يصير فيه طلب شبكة"""
        with mock.patch.object(qss, 'get_sessions', return_value=[dict(SESSION)]), \
                mock.patch.object(self.page, '_get_title_fallback', return_value='عنوان'):
            self.page.load_sessions()
            self.assertTrue(pump(lambda: self.page._loading is False))
            with mock.patch.object(qss, 'requests') as r:
                self.page._render()
                r.post.assert_not_called()
                r.get.assert_not_called()

    def test_refresh_while_loading_does_not_start_second_fetch(self):
        calls = []

        def slow(*_a, **_k):
            calls.append(1)
            time.sleep(0.6)
            return [dict(SESSION)]

        with mock.patch.object(qss, 'get_sessions', side_effect=slow):
            self.page.load_sessions()
            self.page.load_sessions()
            self.assertEqual(len(calls), 1, 'تكرر الجلب — أكثر من خيط واحد')
            self.assertTrue(pump(lambda: self.page._loading is False))

    def test_error_handled_on_ui_thread(self):
        with mock.patch.object(qss, 'get_sessions', side_effect=OSError('network down')):
            self.page.load_sessions()
            self.assertTrue(pump(lambda: self.page._loading is False))

    def test_session_with_dash_date_is_not_dropped(self):
        """نظام الوزارة يرجّع التاريخ أحيانًا بـ'-' — ما تنفلتر الجلسة"""
        d = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
        sess = dict(SESSION)
        sess['start'] = d + ' 09:00'
        with mock.patch.object(qss, 'get_sessions', return_value=[sess]):
            self.page.load_sessions()
            self.assertTrue(pump(lambda: self.page._loading is False))
        self.assertEqual(len(self.page.sessions_data), 1,
                         "الجلسة بتاريخ '-' انفلترت — الخطأ القديم لسه موجود")

    def test_session_with_slash_date_is_not_dropped(self):
        """ونفس الشيء لو التاريخ رجع بـ'/'"""
        d = (datetime.now() + timedelta(days=3)).strftime('%Y/%m/%d')
        sess = dict(SESSION)
        sess['start'] = d + ' 09:00'
        with mock.patch.object(qss, 'get_sessions', return_value=[sess]):
            self.page.load_sessions()
            self.assertTrue(pump(lambda: self.page._loading is False))
        self.assertEqual(len(self.page.sessions_data), 1,
                         "الجلسة بتاريخ '/' انفلترت")


if __name__ == '__main__':
    unittest.main()
