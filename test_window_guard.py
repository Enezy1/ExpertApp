# حارس النافذة الرئيسية (offscreen): python -W ignore -m unittest test_window_guard -v
import os
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow, QMessageBox, QWidget

import window_guard as wg

APP = QApplication.instance() or QApplication([])


def pump():
    for _ in range(4):
        QCoreApplication.processEvents()


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.main = QMainWindow()
        self.main.show()
        self.guard = wg.install(APP, self.main)

    def tearDown(self):
        self.main.removeEventFilter(self.guard._main_filter)
        APP.removeEventFilter(self.guard)
        APP.setQuitOnLastWindowClosed(True)
        self.main.close()

    def test_app_does_not_quit_on_last_window_closed(self):
        self.assertFalse(APP.quitOnLastWindowClosed())

    def test_main_restored_after_child_dialog_closes(self):
        dlg = QDialog(self.main)
        dlg.show()
        pump()
        self.main.hide()                                  # العَرَض: الصفحة الخلفية اختفت أثناء الحوار
        with mock.patch.object(self.main, 'raise_') as r, mock.patch.object(self.main, 'activateWindow') as a:
            dlg.close()
            pump()
        self.assertTrue(self.main.isVisible())
        r.assert_called()
        a.assert_called()

    def test_esc_rejects_and_main_comes_back(self):
        dlg = QDialog(self.main)
        dlg.show()
        self.main.hide()
        dlg.reject()                                      # ما يفعله Esc
        pump()
        self.assertTrue(self.main.isVisible())

    def test_minimized_by_user_stays_minimized(self):
        dlg = QDialog(self.main)
        dlg.show()
        self.main.showMinimized()
        dlg.close()
        pump()
        self.assertTrue(self.main.isMinimized())

    def test_closing_main_quits_explicitly(self):
        with mock.patch.object(APP, 'quit') as q:
            self.main.close()
            pump()
        q.assert_called()

    def test_guard_ignores_non_dialog_widgets(self):
        w = QWidget(self.main)
        w.show()
        self.main.hide()
        w.hide()
        pump()
        self.assertFalse(self.main.isVisible())


if __name__ == '__main__':
    unittest.main()
