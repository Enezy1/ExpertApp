# اختبارات صفحة «القضايا المتداولة» (Qt):
#   الجلب ينفَّذ في خيط خلفي — لا يجوز أن تجمّد الواجهة.
#   python -W ignore -m unittest test_qt_pending_page -v
import os
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

import qt_pending_page_v2 as qp

APP = QApplication.instance() or QApplication([])

CASE_A = {'caso_no': 'A2263973', 'title': 'شركة كذا ضد شركة أخرى',
          'received_date': '2026-10-06', 'autocase_no': '261932780'}
CASE_B = {'caso_no': 'A2263970', 'title': 'دعوى مدنية',
          'received_date': '2026-10-07', 'autocase_no': '260517110'}
RESERVED = {'caso_no': 'A2263970', 'title': 'دعوى مدنية',
            'received_date': '2026-10-07', 'autocase_no': '260517110'}


def pump(predicate, secs=10):
    """يدوّر حلقة أحداث Qt لين تتحقق الحالة (أو تنتهي المهلة)"""
    end = time.time() + secs
    while time.time() < end:
        APP.processEvents()
        if predicate():
            APP.processEvents()
            return True
        time.sleep(0.01)
    APP.processEvents()
    return False


class PendingPageThreadingTests(unittest.TestCase):
    def setUp(self):
        self.page = qp.PendingCasesPage({'s': '1'}, 'خبير تجريبي')

        # نعطّل كل ما يمس الشبكة أو قاعدة البيانات الحقيقية
        self._patches = [
            mock.patch.object(qp, 'get_pending_cases', return_value=[dict(CASE_A)]),
            mock.patch.object(qp, 'get_reserved_cases', return_value=[dict(RESERVED)]),
            mock.patch.object(qp, 'ensure_case_type_and_committee'),
            mock.patch.object(qp, 'sync_case_statuses'),
            mock.patch.object(qp, 'claim_summary_initial', return_value=('skip', '')),
            mock.patch.object(qp.case_db, 'get_case', return_value=None),
            # نطفئ الحركة في الاختبار: Deterministic وما فيه مؤثرات معلّقة على widgets
            mock.patch.object(qp.mo, '_MOTION', False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        # ننتظر انتهاء خيط الجلب قبل حذف الصفحة — خيط شغّال يبعث إشارة على
        # widget محذوف يسبّب انهيار Qt (Access Violation) مو فشل اختبار عادي
        end = time.time() + 5
        while self.page._loading and time.time() < end:
            APP.processEvents()
            time.sleep(0.02)
        time.sleep(0.15)
        APP.processEvents()
        for p in self._patches:
            p.stop()
        self.page.deleteLater()
        # الحذف المؤجَّل لـQt ما ينفَّذ بـprocessEvents وحده — ننفّذه هنا بالترتيب
        # عشان ما يتعطّل الحذف لاختبار لاحق وينهار Qt
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    # ---------- الاختبار الأساسي: الواجهة ما تتجمّد ----------

    def test_load_does_not_block_the_ui_thread(self):
        """الجلب بطيء (يحاكاة شبكة الوزارة) — لازم load_cases ترجع فوراً"""
        def slow_pending(_cookies):
            time.sleep(1.0)
            return [dict(CASE_A)]

        with mock.patch.object(qp, 'get_pending_cases', side_effect=slow_pending):
            start = time.time()
            self.page.load_cases()
            elapsed = time.time() - start

        self.assertLess(elapsed, 0.3,
                        'load_cases تجمّدت خيط الواجهة — رجعنا بعد %.2f ثانية' % elapsed)
        # وخلال الجلب تكون الواجهة حيّة (نقدر نكوّر الصفحة ونعالج الأحداث)
        APP.processEvents()
        self.assertTrue(self.page.isEnabled())

    def test_results_are_applied_on_the_ui_thread(self):
        self.page.load_cases()
        self.assertTrue(pump(lambda: len(self.page._cases) == 2),
                        'ما وصلت النتائج للواجهة')

        # العدّادات مطابقة تماماً للسلوك الأصلي
        self.assertEqual(self.page.kpi_total.value_label.text(), '2')
        self.assertEqual(self.page.kpi_reserved.value_label.text(), '1')
        self.assertEqual(len(self.page._reserved_map), 1)

    def test_refresh_while_loading_does_not_start_a_second_fetch(self):
        """ضغطة تحديث أثناء جلب جارٍ ما تبدأ طلبات ثانية (ولا تضاعف الضغط على الشبكة)"""
        calls = []

        def slow_pending(_cookies):
            calls.append(1)
            time.sleep(0.6)
            return [dict(CASE_A)]

        with mock.patch.object(qp, 'get_pending_cases', side_effect=slow_pending):
            self.page.load_cases()
            self.page.load_cases()          # ضغطة ثانية
            self.page.load_cases()
            self.assertEqual(len(calls), 1, 'تكرر الجلب — صار أكثر من خيط واحد')
            self.assertTrue(pump(lambda: len(self.page._cases) == 2))

    def test_error_is_handled_on_the_ui_thread(self):
        """فشل الشبكة لازم يطلع كحالة خطأ بالواجهة (مو استثناء طائر)"""
        with mock.patch.object(qp, 'get_pending_cases', side_effect=OSError('network down')):
            self.page.load_cases()
            self.assertTrue(pump(lambda: self.page._loading is False))
            self.assertEqual(self.page._cases, [])
            # زر التحديث يرجع متاح بعد الخطأ
            self.assertTrue(self.page.refresh_btn.isEnabled())

    def test_stale_result_is_ignored(self):
        """نتيجة جلب قديمة (.token مختلف) ما تلمس الواجهة"""
        self.page._cases = []
        self.page._load_token = 99
        self.page._apply_data({'token': 1, 'cases': [dict(CASE_A)],
                               'reserved': [], 'reserved_map': {}})
        self.assertEqual(self.page._cases, [], 'نتيجة قديمة طبقت نفسها على الواجهة')

    def test_button_reenabled_after_success(self):
        self.page.load_cases()
        self.assertTrue(pump(lambda: len(self.page._cases) == 2))
        self.assertTrue(self.page.refresh_btn.isEnabled())


if __name__ == '__main__':
    unittest.main()
