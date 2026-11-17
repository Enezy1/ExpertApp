# -*- coding: utf-8 -*-
"""
اختبارات `first_session.py` — محضر أول جلسة (Tk).

**بلا شبكة في الاختبارات** — كل مسارات iCloud مُموكَسة.

المغطى:
  • طلب iCloud **ما يجمّدش** الواجهة (كان يُنفَّذ مباشرة على خيط Tk).
  • فحص الحساب باقى محلي (قراءة ملف) — يعرض التنبيه فوراً.
  • منطق الجلسات (الجلسة القادمة / أنواع الجلسات) يظل شغّال.
"""
import os
import sys
import time
import inspect
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import first_session


class _Stub:
    """بديل نافذة Tk — نحتاج الدالة بس (self.caso_no/cookies/current_user)."""

    def __init__(self):
        self.caso_no = 'A2264321'
        self.cookies = {'sid': 'x'}
        self.current_user = 'expert'


class CalendarSyncBackgroundTests(unittest.TestCase):
    """⚠️ الاختبار الأصلي (مهمة㉓): `add_calendar_event` كان يُنفَّذ
    **مباشرة** على خيط الواجهة ⟵ مع مهلة 8 ث (أو 30 قبلها) كانت
    نافذة المحضر تتجمد. لازم يرجع فوراً."""

    def test_sync_returns_immediately(self):
        stub = _Stub()

        def slow_add(*a, **kw):
            time.sleep(1.2)
            return (True, None)

        with mock.patch('icloud_calendar.has_credentials', return_value=True), \
                mock.patch('icloud_calendar.add_calendar_event', side_effect=slow_add), \
                mock.patch('api.get_case_parties_summary', return_value=' parties '):
            started = time.time()
            first_session.FirstSessionWindow._sync_calendar_silent(
                stub, '2026/11/18', '08:00')
            elapsed = time.time() - started
        self.assertLess(elapsed, 0.4,
                        'المزامنة لازم تكون بالخلفية — رجعت بعد %.2f ث' % elapsed)

    def test_sync_uses_a_thread(self):
        """حارس انحدر: raw thread مع الصمت عند الفشل هو السلوك المقصود
        لواجهة Tk (ما فيه إطار إشعارات)."""
        src = inspect.getsource(first_session.FirstSessionWindow._sync_calendar_silent)
        self.assertIn('threading.Thread', src)
        self.assertNotIn('add_calendar_event(', src.split('def work()')[0])

    def test_no_direct_calendar_call_on_ui_thread(self):
        """
        ⚠️ الحارس الأهم: ما فيه أي استدعاء مباشر لـ`add_calendar_event`
        داخل دوال الواجهة (الطلب كله داخل `work()` بالخلفية).
        """
        src = inspect.getsource(first_session.FirstSessionWindow)
        # كل استدعاء لـadd_calendar_event لازم يكون داخل work() — نتحقق
        # إنه ما موجود إلا مرة واحدة (داخل الخيط)
        self.assertEqual(src.count('add_calendar_event('), 1)

    def test_has_credentials_check_stays_local(self):
        """
        فحص الحساب **محلي** (قراءة ملف) ⟵ يبقى بخيط الواجهة عشان
        التنبيه «ما فيه حساب iCloud» يظهر فوراً (لو راح للخلفية تأخر).
        والاستدعاء الوحيد لـ`add_calendar_event` هو **داخل `work()`**
        (يعني داخل الخيط).
        """
        src = inspect.getsource(first_session.FirstSessionWindow)
        self.assertIn('has_credentials', src)
        work_src = inspect.getsource(
            first_session.FirstSessionWindow._sync_calendar_silent)
        # الاستدعاء الوحيد موجود داخل work()
        self.assertEqual(work_src.count('add_calendar_event('), 1)
        self.assertIn('def work():', work_src)
        self.assertLess(work_src.index('def work():'),
                        work_src.index('add_calendar_event('))

    def test_sync_without_credentials_does_nothing(self):
        stub = _Stub()
        called = []
        with mock.patch('icloud_calendar.has_credentials', return_value=False), \
                mock.patch('icloud_calendar.add_calendar_event',
                           side_effect=lambda *a, **kw: called.append(1)):
            first_session.FirstSessionWindow._sync_calendar_silent(
                stub, '2026/11/18', '08:00')
            time.sleep(0.2)
        self.assertEqual(called, [])


if __name__ == '__main__':
    unittest.main()
