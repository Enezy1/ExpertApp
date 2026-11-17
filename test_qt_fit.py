# -*- coding: utf-8 -*-
# ===== test_qt_fit.py — ضبط مقاسات النوافذ على الشاشة (مع زوم ويندوز) =====
"""
المشكلة اللي يعالجها هذا الملف (المبلَّغ 17/11/2026):
  شاشة «طلب إعلان» بحجم ثابت (1120×780) وحدّ أدنى 840×560. على جهاز فيه
  زوم ويندوز (125%/150%/175%) المقاس **المنطقي** للشاشة يصغر — 1366×768
  تصير 911×512 بـ150% — فتصير النافذة أكبر من الشاشة، ويطلع زر
  «إرسال الإعلان» (Far يسار الشريط السفلي) **برا الشاشة**.

  والسبب الأعمق (مقاس): التخطيط (QLayout) يفرض حدّه الأدنى على النافذة
  (2422px عرضاً!) — فمهما نادينا resize() النافذة تطلع أعرض من الشاشة.

الحل: qt_fit.apply_fit — يحدّد المقاس على الشاشة + يرخّي قيد التخطيط.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QRect, QPoint, Qt
from PyQt6.QtWidgets import (QApplication, QLabel, QVBoxLayout, QWidget, QSizePolicy,
                             QScrollArea)

import qt_fit

APP = QApplication.instance() or QApplication([])

#: شاشة لابتوب 1366×768 **بزوم 150%** ⟵ 911×512 منطقية
ZOOMED = QRect(0, 0, 911, 512)
#: شاشة عادية 1920×1080
NORMAL = QRect(0, 0, 1920, 1040)


class AvailableGeometryTests(unittest.TestCase):
    def test_returns_valid_rect(self):
        geo = qt_fit.available_geometry()
        self.assertGreater(geo.width(), 0)
        self.assertGreater(geo.height(), 0)

    def test_uses_widget_screen_when_available(self):
        w = QWidget()
        geo = qt_fit.available_geometry(w)
        self.assertGreater(geo.width(), 0)


class FitSizeTests(unittest.TestCase):
    """المقاس المطلوب يتقصّ لو ما fit على الشاشة."""

    def test_preferred_size_kept_on_big_screen(self):
        with mock.patch.object(qt_fit, 'available_geometry', return_value=NORMAL):
            w, h = qt_fit.fit_size(None, prefer=(1120, 780), minimum=(840, 560))
        self.assertEqual((w, h), (1120, 780))

    def test_clamped_on_zoomed_screen(self):
        with mock.patch.object(qt_fit, 'available_geometry', return_value=ZOOMED):
            w, h = qt_fit.fit_size(None, prefer=(1120, 780), minimum=(840, 560))
        self.assertLessEqual(w, ZOOMED.width())
        self.assertLessEqual(h, ZOOMED.height())

    def test_minimum_never_exceeds_screen(self):
        """الحدّ الأدنى المطلوب ما يخلّي النافذة تتجاوز الشاشة."""
        with mock.patch.object(qt_fit, 'available_geometry', return_value=ZOOMED):
            w, h = qt_fit.fit_size(None, prefer=(1120, 780), minimum=(1080, 660))
        self.assertLessEqual(w, ZOOMED.width())
        self.assertLessEqual(h, ZOOMED.height())


class ApplyFitTests(unittest.TestCase):
    """تطبيق المقاس: الحجم داخل الشاشة + التخطيط ما يفرض حدّه الأدنى."""

    def _widget(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel('نص طويل جداً ' * 60))   # يفرض عرضاً كبيراً
        return w

    def test_size_within_screen(self):
        w = self._widget()
        with mock.patch.object(qt_fit, 'available_geometry', return_value=ZOOMED):
            geo = qt_fit.apply_fit(w, prefer=(1120, 780), minimum=(840, 560))
        self.assertLessEqual(geo.width(), ZOOMED.width())
        self.assertLessEqual(geo.height(), ZOOMED.height())

    def test_layout_constraint_relaxed(self):
        """⚠️ بدون SetNoConstraint التخطيط يفرض 2422px ⟵ الزر يطلع برا."""
        from PyQt6.QtWidgets import QLayout
        w = self._widget()
        with mock.patch.object(qt_fit, 'available_geometry', return_value=ZOOMED):
            qt_fit.apply_fit(w, prefer=(1120, 780), minimum=(840, 560))
        self.assertEqual(w.layout().sizeConstraint(),
                         QLayout.SizeConstraint.SetNoConstraint)
        w.show()
        APP.processEvents()
        self.assertLessEqual(w.width(), ZOOMED.width())

    def test_minimum_size_not_bigger_than_screen(self):
        w = self._widget()
        with mock.patch.object(qt_fit, 'available_geometry', return_value=ZOOMED):
            qt_fit.apply_fit(w, prefer=(1120, 780), minimum=(1080, 660))
        self.assertLessEqual(w.minimumWidth(), ZOOMED.width())
        self.assertLessEqual(w.minimumHeight(), ZOOMED.height())


class KeepOnScreenTests(unittest.TestCase):
    def test_window_pulled_back_inside(self):
        w = QWidget()
        w.setGeometry(5000, 4000, 300, 200)
        with mock.patch.object(qt_fit, 'available_geometry', return_value=NORMAL):
            qt_fit.keep_on_screen(w)
        geo = NORMAL
        self.assertGreaterEqual(w.x(), geo.x())
        self.assertGreaterEqual(w.y(), geo.y())
        self.assertLessEqual(w.x() + w.width(), geo.x() + geo.width())
        self.assertLessEqual(w.y() + w.height(), geo.y() + geo.height())

    def test_window_inside_stays(self):
        w = QWidget()
        w.setGeometry(100, 100, 300, 200)
        with mock.patch.object(qt_fit, 'available_geometry', return_value=NORMAL):
            qt_fit.keep_on_screen(w)
        self.assertEqual((w.x(), w.y()), (100, 100))


class ClampToScreenTests(unittest.TestCase):
    def test_clamped_to_screen(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel('نص طويل جداً ' * 60))
        with mock.patch.object(qt_fit, 'available_geometry', return_value=ZOOMED):
            geo = qt_fit.clamp_to_screen(w)
        self.assertLessEqual(geo.width(), ZOOMED.width())
        self.assertLessEqual(geo.height(), ZOOMED.height())


class IlannScreenFitTests(unittest.TestCase):
    """
    الاختبار المرجعي: شاشة «طلب إعلان» على شاشة **مزومة** (911×512).

    المطلوب: النافذة ما تتجاوز الشاشة، وزر «إرسال الإعلان» **داخل**
    النافذة (مو برا الشاشة).
    """

    def setUp(self):
        self.dlg = self._build()

    def tearDown(self):
        # ⚠️ النافذة لازم تنحذف **بشكل صريح**: لو خلّيناها للـGC يحذفها
        # متى ما اتفق (جوه اختبارات ثانية) — وقد ينهار البرنامج.
        dlg = getattr(self, 'dlg', None)
        if dlg is not None:
            try:
                dlg.close()
                dlg.deleteLater()
                APP.processEvents()
            except Exception:
                pass
            self.dlg = None

    def _build(self):
        import qt_ilann_page as qi
        data = {'ok': True, 'auto_no': '260668600',
                'case': {'رقم الخبرة': 'A2264212', 'الرقم الالى': '260668600',
                         'رقم القضيه': '26001611', 'الجهه': 'الأحمدى',
                         'النوع': 'تجارىومدنى جزئي', 'تاريخ الوارد': '02/11/2026',
                         'امانه الخبير': '50'},
                'parties': [{'part_id': '160801', 'name': 'شركه الاتصالات',
                             'type': 'مدعى'}],
                'results': []}
        with mock.patch.object(qt_fit, 'available_geometry', return_value=ZOOMED):
            dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=data,
                                 auto_no='260668600', session_date='2026/11/10',
                                 session_time='01:30', case_title='تجريبي',
                                 current_user='خبير')
        dlg.show()
        APP.processEvents()
        return dlg

    def _dialog(self):
        return self.dlg

    def test_window_fits_zoomed_screen(self):
        dlg = self._dialog()
        self.assertLessEqual(dlg.width(), ZOOMED.width())
        self.assertLessEqual(dlg.height(), ZOOMED.height())

    def test_send_button_inside_window(self):
        """⚠️ الاختبار الأصلي للخلل: زر الإرسال ما يطلع برا النافذة."""
        dlg = self._dialog()
        pos = dlg.btn_send.mapTo(dlg, QPoint(0, 0))
        self.assertGreaterEqual(pos.x(), 0)
        self.assertLessEqual(pos.x() + dlg.btn_send.width(), dlg.width())
        self.assertGreaterEqual(pos.y(), 0)
        self.assertLessEqual(pos.y() + dlg.btn_send.height(), dlg.height())

    def test_action_bar_inside_window(self):
        """الشريط السفلي (زر الإرسال فيه) جوّا النافذة."""
        dlg = self._dialog()
        pos = dlg.actionbar.mapTo(dlg, QPoint(0, 0))
        self.assertGreaterEqual(pos.y(), 0)
        self.assertLessEqual(pos.y() + dlg.actionbar.height(), dlg.height())

    def test_status_label_can_shrink(self):
        """نص الحالة لازم ينكمش — وإلا انزاحت الأزرار (زر الإرسال) براها."""
        dlg = self._dialog()
        self.assertEqual(dlg.lbl_state.minimumWidth(), 0)

    def test_layout_constraint_relaxed(self):
        """
        ⚠️ الاختبار الحاسم: التخطيط ما يفرض حدّه الأدنى على النافذة.

        بدون SetNoConstraint يفرض التخطيط عرضه الأدنى (2000+ بكسل على
        البيانات الحقيقية) ⟵ النافذة تطلع أعرض من الشاشة ويطلع زر
        «إرسال الإعلان» براها.
        """
        from PyQt6.QtWidgets import QLayout
        dlg = self._dialog()
        self.assertEqual(dlg.layout().sizeConstraint(),
                         QLayout.SizeConstraint.SetNoConstraint)

    def test_scroll_area_does_not_force_width(self):
        """منطقة التمرير ما تفرض عرض المحتوى على النافذة (تمرير أفقي بدل قصّ)."""
        from PyQt6.QtWidgets import QScrollArea
        dlg = self._dialog()
        scrolls = dlg.findChildren(QScrollArea)
        self.assertTrue(scrolls)
        for s in scrolls:
            self.assertEqual(s.sizePolicy().horizontalPolicy(),
                             QSizePolicy.Policy.Ignored)
            self.assertEqual(s.horizontalScrollBarPolicy(),
                             Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def test_wide_content_does_not_push_window_off_screen(self):
        """
        محتوى عريض (اسم طويل/جدول كبير) ⟵ النافذة **ما تتجاوز الشاشة**
        (قبل الإصلاح كانت تطلع بعرض 2000+ بكسل ويطلع الزر براها).
        """
        from PyQt6.QtWidgets import QLabel
        dlg = self._dialog()
        wide = QLabel('س' * 1200)
        wide.setFixedWidth(2000)
        dlg.content_layout.addWidget(wide)
        with mock.patch.object(qt_fit, 'available_geometry', return_value=ZOOMED):
            qt_fit.apply_fit(dlg, prefer=(1120, 780), minimum=(840, 560))
        dlg.show()
        APP.processEvents()
        self.assertLessEqual(dlg.width(), ZOOMED.width())
        self.assertLessEqual(dlg.height(), ZOOMED.height())
        pos = dlg.btn_send.mapTo(dlg, QPoint(0, 0))
        self.assertGreaterEqual(pos.x(), 0)
        self.assertLessEqual(pos.x() + dlg.btn_send.width(), dlg.width())

    def test_send_button_on_screen_with_claim_viewer(self):
        """
        نافذة «صحيفة الدعوى» مفتوحة يسار الشاشة ⟵ زر «إرسال الإعلان» لازم
        يبقى **ظاهر على الشاشة** (Far يسار النافذة أم).
        """
        import qt_ilann_page as qi
        dlg = self._dialog()
        viewer = QWidget()
        qi._place_on_left(viewer, dlg)
        pos = dlg.btn_send.mapTo(dlg, QPoint(0, 0))
        on_screen = dlg.x() + pos.x()
        self.assertGreaterEqual(on_screen, 0)
        self.assertLessEqual(on_screen + dlg.btn_send.width(), ZOOMED.width())


class LoginScreenFitTests(unittest.TestCase):
    """
    شاشة الدخول: على شاشة قصيرة (زوم) لازم تكون **قابلة للتمرير** —
    زر «تسجيل الدخول» يوصل دائماً (ما يطلع برا الشاشة).
    """

    def _login(self, w=520, h=480):
        import qt_login_ui
        from PyQt6.QtWidgets import QWidget

        class _Fake(QWidget):
            def _try_connect(self):
                pass

            def _switch_account(self, u):
                pass

        s = _Fake()
        s.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        s.setFixedSize(w, h)
        qt_login_ui.build_login_ui(s, {}, [])
        s.show()
        APP.processEvents()
        return s

    def test_login_has_scroll_area(self):
        s = self._login()
        self.assertIsNotNone(s.findChild(QScrollArea))

    def test_login_button_reachable_by_scrolling(self):
        s = self._login()
        scroll = s.findChild(QScrollArea)
        btn = s.retry_btn
        bottom = btn.mapTo(s, QPoint(0, 0)).y() + btn.height()
        # المحتوى أطول من النافذة ⟵ والتمرير يوصّلنا للزر
        self.assertGreater(bottom, s.height())
        self.assertGreaterEqual(scroll.verticalScrollBar().maximum(),
                                bottom - s.height())

    def test_login_button_visible_on_tall_screen(self):
        """على شاشة عادية: الزر ظاهر بدون تمرير."""
        s = self._login(w=520, h=830)
        btn = s.retry_btn
        top = btn.mapTo(s, QPoint(0, 0)).y()
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(top + btn.height(), s.height())


if __name__ == '__main__':
    unittest.main()
