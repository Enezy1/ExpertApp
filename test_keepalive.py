"""اختبارات إبقاء الجلسة حيّة (keepalive.py) وزر التحديث بالشريط الجانبي."""
import os
import threading
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import keepalive


class _Resp:
    def __init__(self, text='', status=200):
        self.text, self.status_code = text, status


class PingTests(unittest.TestCase):
    def test_ok_when_logged_in_marker_present(self):
        with mock.patch('keepalive.requests.get', return_value=_Resp('x username-hide-on-mobile y')):
            self.assertEqual(keepalive.ping({'a': '1'}), 'ok')

    def test_lost_when_login_page_returned(self):
        with mock.patch('keepalive.requests.get', return_value=_Resp('<form>تسجيل الدخول</form>')):
            self.assertEqual(keepalive.ping({'a': '1'}), 'lost')

    def test_error_on_network_failure_is_not_lost(self):
        with mock.patch('keepalive.requests.get', side_effect=OSError('down')):
            self.assertEqual(keepalive.ping({'a': '1'}), 'error')

    def test_error_on_server_5xx_is_not_lost(self):
        with mock.patch('keepalive.requests.get', return_value=_Resp('', 503)):
            self.assertEqual(keepalive.ping({'a': '1'}), 'error')


class LimitsTests(unittest.TestCase):
    def test_defaults_are_10_minutes_and_3_hours(self):
        self.assertEqual(keepalive.INTERVAL_SEC, 600)
        self.assertEqual(keepalive.MAX_DURATION_SEC, 3 * 3600)

    def test_should_continue_boundary(self):
        self.assertTrue(keepalive.should_continue(3 * 3600 - 1))
        self.assertFalse(keepalive.should_continue(3 * 3600))


class LoopTests(unittest.TestCase):
    def _run(self, states, max_duration=60):
        got, done = [], threading.Event()
        it = iter(states)

        def pinger(_c):
            return next(it)

        def on_state(s):
            got.append(s)
            if len(got) == len(states):
                done.set()

        ka = keepalive.KeepAlive({'a': '1'}, on_state, interval=0.01,
                                 max_duration=max_duration, pinger=pinger)
        ka.start()
        done.wait(2)
        ka.stop()
        return got, ka

    def test_reports_each_ping(self):
        got, _ = self._run(['ok', 'error', 'ok'])
        self.assertEqual(got, ['ok', 'error', 'ok'])

    def test_stops_after_lost(self):
        got, ka = self._run(['ok', 'lost'])
        ka._thread.join(2)
        self.assertEqual(got, ['ok', 'lost'])
        self.assertFalse(ka._thread.is_alive())

    def test_stops_at_max_duration_without_pinging(self):
        calls = []
        ka = keepalive.KeepAlive({'a': '1'}, lambda s: None, interval=0.01,
                                 max_duration=0.0, pinger=lambda c: calls.append(1) or 'ok')
        ka.start()
        ka._thread.join(2)
        self.assertEqual(calls, [])
        self.assertFalse(ka._thread.is_alive())

    def test_no_cookies_means_no_thread(self):
        ka = keepalive.KeepAlive(None, lambda s: None)
        ka.start()
        self.assertIsNone(ka._thread)


class SidebarUpdateButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import qt_shell_v2
        self.sb = qt_shell_v2.Sidebar(lambda k: None, 'tester', main1_authorized=False)

    def test_hidden_until_update_found(self):
        self.assertTrue(self.sb.update_btn.isHidden())

    def test_show_progress_ready_failed(self):
        self.sb.show_update('1.3.0')
        self.assertFalse(self.sb.update_btn.isHidden())
        self.assertIn('1.3.0', self.sb.update_btn.text())
        self.assertTrue(self.sb.update_btn.isEnabled())
        self.sb.set_update_progress(40)
        self.assertIn('40%', self.sb.update_btn.text())
        self.assertFalse(self.sb.update_btn.isEnabled())
        self.sb.set_update_ready()
        self.assertTrue(self.sb.update_btn.isEnabled())
        self.sb.set_update_failed('1.3.0')
        self.assertTrue(self.sb.update_btn.isEnabled())


if __name__ == '__main__':
    unittest.main()
