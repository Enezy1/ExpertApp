# -*- coding: utf-8 -*-
"""
اختبارات مسار مزامنة التقويم بالواجهة (Qt) — المهمة㉓.

**بلا شبكة في الاختبارات** — كل مسارات iCloud مُموكَسة.

المغطى:
  • «إضافة الجلسة للتقويم» ما تجمّدش الواجهة (تشتغل بالخلفية).
  • مسار تسجيل الجلسة likewise بخلفية — مو طلب شبكة على خيط الواجهة.
  • ⚠️ **حارس الان invisibility**: ما فيه أي زر ولا نافذة إعدادات مزامنة
    ولا خيار .ics — الرسالة النهائية **نصية فقط**.
"""
import os
import time
import inspect
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication

import icloud_calendar
import qt_first_session as qfs
import qt_sessions_page as qsp

APP = QApplication.instance() or QApplication([])
ROOT = os.path.dirname(os.path.abspath(__file__))


class _Stub:
    """مش-CalDAV event وهمي — يكفي لتجربة مسار المزامنة."""

    def __init__(self):
        self.caso_no = 'A2264321'
        self.cookies = {'sid': 'x'}
        self.current_user = 'expert'
        self.failures = []

    def _calendar_sync_failed(self, err):
        self.failures.append(err)


# ---------------------------------------------------------------------------
# 1) مسار تسجيل الجلسة (qt_first_session) — لازم يكون بالخلفية
# ---------------------------------------------------------------------------

class FirstSessionBackgroundTests(unittest.TestCase):

    def test_sync_calendar_silent_returns_immediately(self):
        """
        ⚠️ الاختبار الأصلي: `add_calendar_event` كان ينادى **مباشرة** على
        خيط الواجهة ⟵ مع مهلة 8 ث (أو 30 قبلها) كانت نافذة تسجيل الجلسة
        تتجمد. الآن لازم يرجع فوراً.
        """
        stub = _Stub()

        def slow_add(*a, **kw):
            time.sleep(1.2)
            return (True, None)

        started = time.time()
        with mock.patch.object(icloud_calendar, 'has_credentials', return_value=True), \
                mock.patch.object(icloud_calendar, 'add_calendar_event', side_effect=slow_add), \
                mock.patch.object(qfs, 'get_case_parties_summary', return_value=' parties '):
            qfs.FirstSessionControllerQt._sync_calendar_silent(stub, '2026/11/18', '08:00')
        elapsed = time.time() - started
        self.assertLess(elapsed, 0.4,
                        'المزامنة لازم تكون بالخلفية — رجعت بعد %.2f ث' % elapsed)

    def test_sync_calendar_silent_reports_failure(self):
        """الفشل يوصل للمستخدم (تنبيه) — مو يختفي بصمت"""
        stub = _Stub()
        seen = {}

        def fake_bg(fn, on_ok, on_fail):
            on_ok((False, 'انتهت مهلة الاتصال'))

        with mock.patch.object(icloud_calendar, 'has_credentials', return_value=True), \
                mock.patch.object(icloud_calendar, 'add_calendar_event',
                                  return_value=(False, 'انتهت مهلة الاتصال')), \
                mock.patch.object(qfs, 'get_case_parties_summary', return_value='p'), \
                mock.patch('qt_extraction.run_in_background', side_effect=fake_bg):
            qfs.FirstSessionControllerQt._sync_calendar_silent(stub, '2026/11/18', '08:00')
        self.assertTrue(stub.failures)
        self.assertIn('مهلة', stub.failures[0])

    def test_sync_calendar_silent_uses_signal_bridge_not_raw_thread(self):
        """
        حارس انحدار: `run_in_background` (جسر إشارات) هو الآمن — raw thread
        ما يقدر يسلّم النتيجة لخيط الواجهة بأمان.
        """
        src = inspect.getsource(qfs.FirstSessionControllerQt._sync_calendar_silent)
        self.assertIn('run_in_background', src)
        self.assertNotIn('threading.Thread', src)

    def test_finalize_has_no_direct_calendar_call(self):
        """
        ⚠️ `_finalize` كان يستدعي `add_calendar_event` مباشرة على خيط
        الواجهة ⟵ تجمّد. لازم يمرّ بالمسار الخلفي بس.
        """
        src = inspect.getsource(qfs.FirstSessionControllerQt._finalize)
        self.assertNotIn('add_calendar_event(', src)
        self.assertIn('_sync_calendar_silent(', src)


# ---------------------------------------------------------------------------
# 2) صفحة الجلسات (qt_sessions_page)
# ---------------------------------------------------------------------------

class SessionsPageCalendarTests(unittest.TestCase):

    def test_add_to_calendar_runs_in_background(self):
        src = inspect.getsource(qsp.SessionCardQt._add_to_calendar)
        self.assertIn('_run_job(', src)
        self.assertNotIn('threading.Thread', src)

    def test_calendar_failure_is_text_only(self):
        """
        ⚠️ **الرسالة النهائية نصية فقط**: بلا زر «إعادة المحاولة» وبلا
        «ملف تقويم» وبلا «إعدادات المزامنة» — ولا تحويل لملفات.
        """
        src = inspect.getsource(qsp.SessionCardQt._calendar_failed)
        self.assertNotIn('addButton', src)
        self.assertNotIn('إعادة المحاولة', src)
        self.assertNotIn('ملف تقويم', src)
        self.assertNotIn('إعدادات المزامنة', src)
        self.assertNotIn('clickedButton', src)
        self.assertIn('QMessageBox', src)

    def test_no_ics_export_helper(self):
        """خيار تصدير .ics — محذوف"""
        self.assertFalse(hasattr(qsp.SessionCardQt, '_export_calendar_ics'))

    def test_no_calendar_settings_helper(self):
        """نافذة إعدادات المزامنة — محذوفة"""
        self.assertFalse(hasattr(qsp.SessionCardQt, '_open_calendar_settings'))

    def test_calendar_settings_entry_removed_from_menu(self):
        """ما فيه بند «إعدادات مزامنة التقويم» بقائمة إجراءات الجلسة"""
        src = inspect.getsource(qsp.SessionCardQt)
        self.assertNotIn('إعدادات مزامنة التقويم', src)
        self.assertNotIn('_open_calendar_settings', src)

    def test_add_to_calendar_menu_item_still_exists(self):
        """⚠️ زر «إضافة للتقويم» (الأساسي) يبقى — هو مو ميزة التجاوز"""
        src = inspect.getsource(qsp.SessionCardQt._show_more_actions)
        self.assertIn('إضافة للتقويم', src)


# ---------------------------------------------------------------------------
# 2ب) ⚠️ انحدار «إضافة للتقويم» — خطأ تقني خام للمستخدم (18/11/2026)
# ---------------------------------------------------------------------------

class AddToCalendarRegressionTests(unittest.TestCase):
    """
    ⚠️ **الخلل**: «إضافة للتقويم» كان يرمي

        AttributeError: 'SessionCardQt' object has no attribute 'case_name'

    ⟵ خطأ تقني خام (مو رسالة مفهومة) يظهر للمستخدم **مباشرة** عند
    الضغط على البند — والسبب: بطاقة الجلسة فيها `case_title` مو `case_name`.

    الاختبار هنا **يشغّل** مسار العمل فعلياً (مو بس يقرأ الكود) ⟵ لو
    رجع الخطأ يبيّن نفسه.
    """

    class _Card:
        """بديل بطاقة الجلسة — نفس الصفات اللي يقرأها المسار."""

        caso = 'A2263973'
        cookies = {'sid': 'x'}
        user = 'خبير'
        date = '2026/11/25'
        time = '08:30'
        case_title = 'شركة الاختبار ضد شركة الاختبار'

        def _run_job(self, work, on_done):
            self.work = work
            self.on_done = on_done

        def _calendar_done(self, result):
            self.result = result

    def _run(self):
        card = self._Card()
        captured = {}

        def fake_add(summary, start_dt, description='', **kwargs):
            captured['summary'] = summary
            captured['description'] = description
            captured['start'] = start_dt
            return (True, None)

        with mock.patch.object(icloud_calendar, 'has_credentials', return_value=True), \
             mock.patch.object(icloud_calendar, 'add_calendar_event', side_effect=fake_add), \
             mock.patch.object(qsp, 'get_case_parties_summary', return_value='مدع ضد مدعى'):
            qsp.SessionCardQt._add_to_calendar(card)
            result = card.work()
        return card, captured, result

    def test_worker_succeeds_without_attribute_error(self):
        """قبل الإصلاح: AttributeError ⟵ ما في نتيجة ولا رسالة مفهومة."""
        _card, _captured, result = self._run()
        ok = result[0] if isinstance(result, (tuple, list)) else False
        self.assertTrue(ok, 'مسار «إضافة للتقويم» فشل: %r' % (result,))

    def test_description_uses_case_title(self):
        """وصف الموعد = عنوان القضية (case_title) — مو case_name."""
        _card, captured, _result = self._run()
        self.assertEqual(captured.get('description'), 'شركة الاختبار ضد شركة الاختبار')

    def test_source_has_no_case_name_attribute(self):
        """حارس: مسار الإضافة ما يقرأ `self.case_name` (ما موجودة بالكارت)."""
        src = inspect.getsource(qsp.SessionCardQt._add_to_calendar)
        self.assertNotIn('self.case_name', src)

    def test_card_defines_case_title(self):
        """الكارت نفسه يعرّف `case_title` (وهو اللي ينقرأ)."""
        src = inspect.getsource(qsp.SessionCardQt.__init__)
        self.assertIn('self.case_title', src)


# ---------------------------------------------------------------------------
# 3) ⚠️ حارس الاختفاء — ما فيه أي واجهة لتجاوز البورت
# ---------------------------------------------------------------------------

class InvisibleUiTests(unittest.TestCase):

    def test_calendar_net_module_deleted(self):
        """ملف النافذة نفسه محذوف"""
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'qt_calendar_net.py')))

    def test_no_module_imports_calendar_net(self):
        for name in ('qt_sessions_page.py', 'qt_first_session.py',
                     'qt_settings_page.py', 'icloud_calendar.py'):
            path = os.path.join(ROOT, name)
            src = open(path, encoding='utf-8').read()
            self.assertNotIn('qt_calendar_net', src,
                             '%s لسه يستورد نافذة إعدادات المزامنة' % name)

    def test_toast_has_no_action_button(self):
        """⚠️ التنبيه بعد تسجيل الجلسة ⟵ نصي فقط (بلا زر إعدادات)"""
        src = inspect.getsource(qfs.FirstSessionControllerQt._calendar_sync_failed)
        self.assertNotIn('action_text', src)
        self.assertNotIn('action=', src)
        self.assertNotIn('CalendarNetDialog', src)

    def test_no_ics_button_in_ui(self):
        for name in ('qt_sessions_page.py', 'qt_first_session.py'):
            src = open(os.path.join(ROOT, name), encoding='utf-8').read()
            self.assertNotIn('export_ics', src)
            self.assertNotIn('open_ics', src)


if __name__ == '__main__':
    unittest.main()
