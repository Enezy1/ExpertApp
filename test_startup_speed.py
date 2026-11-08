# اختبارات إقلاع سريع (المهمة④):
#   فحص صلاحية «رئيس القسم» ما يوقف برنامج الإقلاع.
#   python -W ignore -m unittest test_startup_speed -v
import os
import re
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication

import main1_access
import qt_shell_v2 as qs

APP = QApplication.instance() or QApplication([])

HERE = os.path.dirname(os.path.abspath(__file__))
OWNER = 'محمد العنزي'
COLLEAGUE = 'سالم عبدالله الخالدي'


def reset_state():
    """صفّر حالة الفحص العامة بين الاختبارات"""
    main1_access._auth_value = None
    main1_access._auth_user = None
    main1_access._auth_event.clear()


class ResolveAuthorizationTests(unittest.TestCase):
    """resolve_authorization: ينتظر بالحد، وي fallback للكاش"""

    def setUp(self):
        reset_state()

    def tearDown(self):
        reset_state()

    def test_owner_is_instant_without_any_network_call(self):
        """المالك (أنت) — الجواب فوري، صفر طلب شبكة"""
        with mock.patch.object(main1_access, 'is_authorized_for_main1') as m:
            m.side_effect = lambda *a, **k: main1_access.is_owner(OWNER)
            start = time.time()
            got = main1_access.resolve_authorization(OWNER, wait=2.0)
            elapsed = time.time() - start
        self.assertTrue(got)
        self.assertLess(elapsed, 0.2)

    def test_waits_at_most_the_given_limit(self):
        """الفحص بطيء (شبكة ضعيفة) — ما ننتظر أكثر من الحد المحدد"""
        def slow(*_a, **_k):
            time.sleep(5)
            return True

        with mock.patch.object(main1_access, 'is_authorized_for_main1', side_effect=slow):
            start = time.time()
            got = main1_access.resolve_authorization(COLLEAGUE, wait=1.0)
            elapsed = time.time() - start
        self.assertLess(elapsed, 2.0, 'انتظرنا أكثر من الحد: %.2f ثانية' % elapsed)
        # ما وصلتنا نتيجة → رجعنا للكاش (فاضي هنا = غير مخوّل)
        self.assertFalse(got)

    def test_returns_background_result_when_ready(self):
        """لو الفحص المسبق خلص — النتيجة ترجع فوراً بلا انتظار"""
        with mock.patch.object(main1_access, 'is_authorized_for_main1', return_value=True):
            main1_access.start_auth_check(COLLEAGUE)
            time.sleep(0.15)
            start = time.time()
            got = main1_access.resolve_authorization(COLLEAGUE, wait=2.0)
            elapsed = time.time() - start
        self.assertTrue(got)
        self.assertLess(elapsed, 0.2)

    def test_falls_back_to_local_cache_when_network_fails(self):
        """السيرفر واقع → نرجع للنسخة المحفوظة على الجهاز (فورية)"""
        with mock.patch.object(main1_access, 'is_authorized_for_main1', return_value=True), \
                mock.patch.object(main1_access, '_load_cache', return_value=[COLLEAGUE]), \
                mock.patch.object(main1_access, '_save_cache'):
            main1_access.start_auth_check(COLLEAGUE)
            time.sleep(0.15)
            # ن simulate أن النتيجة ما وصلت: نوقف الفحص ونستخدم الكاش مباشرة
            reset_state()
            with mock.patch.object(main1_access, '_load_cache', return_value=[COLLEAGUE]):
                got = main1_access._cached_authorization(COLLEAGUE)
        self.assertTrue(got)

    def test_cache_fallback_recognizes_owner_without_network(self):
        """المالك مخوّل دائماً من الكاش — حتى بدون إنترنت"""
        with mock.patch.object(main1_access, '_load_cache', return_value=[]):
            self.assertTrue(main1_access._cached_authorization(OWNER))

    def test_check_is_not_repeated_for_same_user(self):
        """نفس الخبير — ما نعيد الفحص لو خلص"""
        with mock.patch.object(main1_access, 'is_authorized_for_main1', return_value=True) as m:
            main1_access.start_auth_check(COLLEAGUE)
            time.sleep(0.15)
            main1_access.start_auth_check(COLLEAGUE)
            time.sleep(0.1)
        self.assertEqual(m.call_count, 1, 'الفحص تكرر — صار أكثر من طلب شبكة')


class SidebarAuthorizationTests(unittest.TestCase):
    """الشريط الجانبي: النتيجة تُمرَّر من فوق — ما يعيد الفحص"""

    def test_sidebar_does_not_recheck_when_flag_is_given(self):
        with mock.patch.object(qs, '_is_authorized_for_main1') as m:
            sb = qs.Sidebar(lambda k: None, OWNER, main1_authorized=True)
            m.assert_not_called()
        self.assertIn('main1', sb.items)
        self.assertIn('case_lookup', sb.items)
        self.assertIn('labels', sb.items)

    def test_sidebar_hides_section_when_not_authorized(self):
        sb = qs.Sidebar(lambda k: None, OWNER, main1_authorized=False)
        self.assertNotIn('main1', sb.items)
        self.assertNotIn('case_lookup', sb.items)

    def test_sidebar_falls_back_to_live_check_when_flag_missing(self):
        """نداء قديم بدون تمرير النتيجة → يفحص بنفسه (للتوافق)"""
        with mock.patch.object(qs, '_is_authorized_for_main1', return_value=True) as m:
            sb = qs.Sidebar(lambda k: None, OWNER)
            m.assert_called_once()
        self.assertIn('main1', sb.items)


class StartupThreadingTests(unittest.TestCase):
    """عمليات الإقلاع الشبكية لازم تكون بالخلفية"""

    def test_main_registers_expert_in_background_thread(self):
        src = open(os.path.join(HERE, 'main.py'), encoding='utf-8').read()
        self.assertIn('threading.Thread(target=_register_in_background, daemon=True).start()', src,
                      'تسجيل اسم الخبير رجع ينفّذ على خيط الواجهة')
        self.assertIn('threading.Thread(target=_sync_in_background, daemon=True).start()', src,
                      'المزامنة السحابية رجعت تنفّذ على خيط الواجهة')

    def test_main_starts_auth_check_early(self):
        src = open(os.path.join(HERE, 'main.py'), encoding='utf-8').read()
        self.assertIn('main1_access.start_auth_check(user)', src,
                      'فحص الصلاحية ما انطلق مبكراً')

    def test_shell_resolves_authorization_once(self):
        """النافذة تحسب الصلاحية مرة واحدة — مو مرتين"""
        src = open(os.path.join(HERE, 'qt_shell_v2.py'), encoding='utf-8').read()
        # نعدّ الاستدعاءات فقط (مو سطر التعريف def)
        live_calls = len(re.findall(r'(?<!def )\b_is_authorized_for_main1\(current_user\)', src))
        self.assertLessEqual(live_calls, 1,
                             'الفحص المباشر صار %d مرة (المفروض مرة وحدة fallback)' % live_calls)
        self.assertIn('self._main1_authorized = main1_access.resolve_authorization(',
                      src, 'النافذة ما تستخدم النتيجة المشتركة')


if __name__ == '__main__':
    unittest.main()
