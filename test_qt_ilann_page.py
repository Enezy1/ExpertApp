# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# اختبارات واجهة «طلب إعلان» (Qt):
#   • النافذة تبني وترسم: رأس القضية/الجلسة + قائمة الأطراف + نتيجة الإعلان.
#   • الضغط «إعلان» يفتح النموذج **تحت القائمة بنفس النافذة** (مو نافذة ثانية).
#   • Enter ما يرسل أبداً — زر «تراجع» هو الافتراضي في نافذة التأكيد.
#   • الإرسال ما يصير إلا بعد موافقة، والقيم الفارغة («null») ما تطلع ولا ترسل.
#   • «طلب إعلان» بقائمة «إجراءات أخرى» — ولما الجلسة تنقضي يصير «حالة الإعلان»
#     (عرض النتيجة بدون إرسال؛ البند ما يختفي بنفس اليوم — 18/11/2026).
#   python -W ignore -m unittest test_qt_ilann_page -v
import os
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QPushButton, QLabel, QFrame

import ilann
import qt_ilann_page as qi

APP = QApplication.instance() or QApplication([])

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_data', 'ilann')

PARTIES = [{'part_id': '160801', 'name': 'شركه الاتصالات المتنقله ش م ك', 'type': 'مدعى'},
           {'part_id': '380068', 'name': 'عبد الهادى محمد على المرى', 'type': 'مدعي عليه'}]

RESULTS = [{'name': 'شركه الاتصالات المتنقله ش م ك', 'means': 'مندوب', 'date': '10/11/2026',
            'session_date': '10/11/2026', 'status': 'تم', 'reason': ''},
           {'name': 'عبد الهادى محمد على المرى', 'means': 'فاكس', 'date': '10/11/2026',
            'session_date': '10/11/2026', 'status': 'فشل', 'reason': 'الرقم مشغول'}]

PAGE_DATA = {'ok': True, 'auto_no': '260668600',
             'case': {'رقم الخبرة': 'A2264212', 'الرقم الالى': '260668600',
                      'رقم القضيه': '26001611', 'الجهه': 'الأحمدى',
                      'النوع': 'تجارىومدنى جزئي', 'تاريخ الوارد': '02/11/2026',
                      'امانه الخبير': '50'},
             'parties': PARTIES, 'results': RESULTS}


def _read(name):
    with open(os.path.join(DATA, name), encoding='utf-8', errors='ignore') as f:
        return f.read()


# ⚠️ **بلا شبكة في الاختبارات**: `PartyForm.load()` تشغّل خيطاً لجلب
#    المناطق (`ilann.fetch_zones`) — لو ما انموكست، الخيط يطلب سيرفر
#    الوزارة فعلياً، ولما ينتهي يطلّع على نموذج انحذف ⟵ انهيار متقطّع
#    (RuntimeError/Access Violation) حسب توقيت الـGC.
_ZONES_PATCH = None


def setUpModule():
    global _ZONES_PATCH
    _ZONES_PATCH = mock.patch.object(qi.ilann, 'fetch_zones', return_value=[])
    _ZONES_PATCH.start()


def tearDownModule():
    global _ZONES_PATCH
    if _ZONES_PATCH is not None:
        try:
            _ZONES_PATCH.stop()
        except Exception:
            pass
        _ZONES_PATCH = None


def pump(predicate, secs=10):
    end = time.time() + secs
    while time.time() < end:
        APP.processEvents()
        if predicate():
            APP.processEvents()
            return True
        time.sleep(0.01)
    APP.processEvents()
    return False


def _buttons(widget):
    """أول زر لكل تسمية (الأزرار المكرّرة: «إعلان» لكل طرف)."""
    out = {}
    for b in widget.findChildren(QPushButton):
        out.setdefault(b.text(), b)
    return out


class DialogBuildTests(unittest.TestCase):
    """النافذة تبني وترسم صح"""

    def setUp(self):
        self.dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA,
                                   auto_no='260668600', session_date='2026/11/10',
                                   session_time='01:30',
                                   case_title='شركه الاتصالات المتنقله ضد المرى',
                                   current_user='خبير تجريبي')

    def test_builds(self):
        self.assertIsNotNone(self.dlg)
        self.assertEqual(self.dlg.caso_no, 'A2264212')
        self.assertEqual(self.dlg.tbl_results.columnCount(), 6)

    def test_header_shows_case_and_session(self):
        texts = [w.text() for w in self.dlg.findChildren(type(self.dlg.lbl_state))]
        joined = ' | '.join(texts)
        self.assertIn('A2264212', joined)
        self.assertIn('10/11/2026', joined)

    def test_parties_listed_with_announcement_button(self):
        btns = _buttons(self.dlg)
        self.assertIn('إعلان', btns)
        names = [p['name'] for p in PARTIES]
        shown = [w.toolTip() for w in self.dlg.findChildren(type(self.dlg.lbl_state))]
        self.assertTrue(any(n in ' | '.join(shown) for n in names))

    def test_print_button_exists(self):
        self.assertIn('طباعة إشعار الإعلان', _buttons(self.dlg))

    def test_close_is_secondary_not_primary(self):
        """الإجراء الأساسي هو «إرسال إعلان» — «إغلاق» ثانوي."""
        from qt_widgets import PrimaryButton
        close = _buttons(self.dlg)['إغلاق']
        self.assertNotIsInstance(close, PrimaryButton)

    def test_identity_cards_have_icon_badges(self):
        """شكل البطاقة: شارة أيقونة دائرية لكل بطاقة — أخضر للجلسة · كحلي لمعلومات القضية."""
        badges = self.dlg.findChildren(QFrame, 'icon_badge')
        self.assertEqual(len(badges), 5)
        styles = [b.styleSheet() for b in badges]
        self.assertEqual(sum(qi.th.EMERALD_BG in s for s in styles), 2)
        self.assertEqual(sum(qi.th.NAVY_TINT in s for s in styles), 3)

    def test_identity_card_labels_unchanged(self):
        """أسماء البطاقات ما تتغيّر — نفس التسميات الأصلية."""
        texts = [w.text() for w in self.dlg.findChildren(QLabel)]
        for label in ('رقم ملف الخبرة', 'رقم القضية', 'الرقم الآلي للقضية',
                      'تاريخ الجلسة القادمة', 'وقت الجلسة القادمة'):
            self.assertIn(label, texts)
        self.assertNotIn('التقويم المقترح', texts)

    def test_send_button_has_no_icon(self):
        """زر «إرسال الإعلان» بدون أيقونة — الأيقونة ما لها علاقة بالإرسال (طلب العنزي 15/11/2026)."""
        self.assertTrue(self.dlg.btn_send.icon().isNull())

    def test_results_table_filled(self):
        self.assertEqual(self.dlg.tbl_results.rowCount(), 2)
        self.assertEqual(self.dlg.tbl_results.item(0, 4).text(), 'تم')
        self.assertEqual(self.dlg.tbl_results.item(1, 5).text(), 'الرقم مشغول')

    def test_empty_cell_shows_dash(self):
        """Honest Figures Rule — «—» بدل خلية فاضية."""
        self.assertEqual(self.dlg.tbl_results.item(0, 5).text(), '—')

    def test_empty_results_message_is_honest(self):
        """بلا نتائج ⟵ «ما فيه إعلان بعد» (مو فراغ صامت)."""
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212',
                             data={'ok': True, 'case': {}, 'parties': PARTIES,
                                   'results': []},
                             auto_no='260668600', session_date='2026/11/10')
        texts = ' | '.join(w.text() for w in dlg.findChildren(QLabel))
        self.assertIn('ما فيه إعلان بعد', texts)

    def test_connection_failure_does_not_claim_no_announcement(self):
        """فشل الاتصال ⟵ ما نقول «ما فيه إعلان» (أمانة الأرقام: ما جبنا الداتا)."""
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212',
                             data={'ok': False, 'reason': 'connection',
                                   'case': {}, 'parties': [], 'results': [],
                                   'message': ''},
                             auto_no='260668600', session_date='2026/11/10')
        texts = ' | '.join(w.text() for w in dlg.findChildren(QLabel))
        self.assertNotIn('ما فيه إعلان بعد', texts)
        self.assertIn('ما قدرنا نجيب نتيجة الإعلان', texts)


class PartyExpandTests(unittest.TestCase):
    """الضغط «إعلان» يفتح النموذج تحت القائمة داخل نفس النافذة"""

    def setUp(self):
        self.dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA,
                                   auto_no='260668600', session_date='2026/11/10',
                                   session_time='01:30')
        self.form = ilann.parse_party_form(_read('party_form.html'))

    def test_form_appears_inline_below(self):
        with mock.patch.object(qi.ilann, 'fetch_party_form', return_value=self.form):
            _buttons(self.dlg)['إعلان'].click()
            ok = pump(lambda: self.dlg._party_form is not None)
        self.assertTrue(ok, 'النموذج ما ظهر')
        self.assertIsNotNone(self.dlg.form_layout.itemAt(0).widget())

    def test_form_prefilled_from_system(self):
        with mock.patch.object(qi.ilann, 'fetch_party_form', return_value=self.form):
            _buttons(self.dlg)['إعلان'].click()
            ok = pump(lambda: self.dlg._party_form is not None)
        self.assertTrue(ok)
        form = self.dlg._party_form
        self.assertEqual(form.name_lbl.text(), 'شركه الاتصالات المتنقله ش م ك')
        self.assertEqual(form.edits['ADRS_STREET'].text(), 'احمد الجابر')
        self.assertEqual(form.edits['ADRS_BLOCK'].text(), '5')

    def test_null_value_not_shown(self):
        """ADDRNO='null' بالنظام ⟵ الحقل يطلع فاضي (مو 'null')."""
        with mock.patch.object(qi.ilann, 'fetch_party_form', return_value=self.form):
            _buttons(self.dlg)['إعلان'].click()
            ok = pump(lambda: self.dlg._party_form is not None)
        self.assertTrue(ok)
        self.assertEqual(self.dlg._party_form.edits['ADDRNO'].text(), '')

    def test_connection_error_shows_retry_state(self):
        """فشل الشبكة ⟵ «تعذّر الاتصال بالنظام» + إعادة محاولة، مو نص استثناء."""
        with mock.patch.object(qi.ilann, 'fetch_party_form',
                               side_effect=OSError('boom')):
            _buttons(self.dlg)['إعلان'].click()
            ok = pump(lambda: self.dlg._party_form is None
                      and self.dlg.form_layout.count() > 0)
        self.assertTrue(ok)
        widget = self.dlg.form_layout.itemAt(0).widget()
        texts = ' '.join(w.text() for w in widget.findChildren(type(self.dlg.lbl_state)))
        self.assertIn('تعذّر الاتصال', texts)
        self.assertNotIn('boom', texts)

    def test_switching_party_replaces_form(self):
        with mock.patch.object(qi.ilann, 'fetch_party_form', return_value=self.form):
            btns = _buttons(self.dlg)
            btns['إعلان'].click()
            ok = pump(lambda: self.dlg._party_form is not None)
            self.assertTrue(ok)
            first = self.dlg._party_form
            self.dlg._open_party(PARTIES[1])
            ok2 = pump(lambda: self.dlg._party_form is not None
                       and self.dlg._party_form is not first)
        self.assertTrue(ok2)


class ConfirmDialogTests(unittest.TestCase):
    """Enter ما يرسل أبداً — والتأكيد يعرض هوية القضية"""

    def test_send_is_not_default(self):
        dlg = qi._ConfirmSend([('رقم الخبرة', 'A2264212', True),
                               ('الطرف', 'شركه الاتصالات')])
        self.assertFalse(dlg.btn_send.autoDefault())
        self.assertTrue(dlg.btn_cancel.isDefault())

    def test_shows_case_and_party(self):
        dlg = qi._ConfirmSend([('رقم الخبرة', 'A2264212', True),
                               ('الطرف', 'شركه الاتصالات'),
                               ('تاريخ الجلسة', '10/11/2026', True)])
        texts = ' | '.join(w.text() for w in dlg.findChildren(QLabel))
        self.assertIn('A2264212', texts)
        self.assertIn('شركه الاتصالات', texts)

    def test_no_submit_without_confirmation(self):
        form = qi.PartyForm({'s': '1'}, 'A2264212', '2026/11/10', '01:30')
        form.load(ilann.parse_party_form(_read('party_form.html')), PARTIES[0])
        seen = []
        form.submitted.connect(lambda v: seen.append(v))

        class _Rejected:
            def __init__(self, *a, **kw):
                pass

            def exec(self):
                return qi.QDialog.DialogCode.Rejected

        with mock.patch.object(qi, '_ConfirmSend', _Rejected):
            form._on_send()
        self.assertEqual(seen, [])

    def test_submit_after_confirmation(self):
        form = qi.PartyForm({'s': '1'}, 'A2264212', '2026/11/10', '01:30')
        form.load(ilann.parse_party_form(_read('party_form.html')), PARTIES[0])
        seen = []
        form.submitted.connect(lambda v: seen.append(v))

        class _Accepted:
            def __init__(self, *a, **kw):
                pass

            def exec(self):
                return qi.QDialog.DialogCode.Accepted

        with mock.patch.object(qi, '_ConfirmSend', _Accepted):
            form._on_send()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]['ADRS_STREET'], 'احمد الجابر')


class SendFlowTests(unittest.TestCase):
    """الإرسال: يبني الـ payload صح ويحدّث النتيجة"""

    def setUp(self):
        self.dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA,
                                   auto_no='260668600', session_date='2026/11/10')
        self.form = ilann.parse_party_form(_read('party_form.html'))

    def test_payload_built_from_form(self):
        with mock.patch.object(qi.ilann, 'fetch_party_form', return_value=self.form):
            _buttons(self.dlg)['إعلان'].click()
            ok = pump(lambda: self.dlg._party_form is not None)
        self.assertTrue(ok)
        payload = ilann.build_payload(self.dlg._party_form.form, self.dlg._party_form.values())
        self.assertEqual(payload['part_id'], '160801')
        self.assertEqual(payload['ADRS_STREET'], 'احمد الجابر')
        self.assertEqual(payload['ADDRNO'], '')

    def test_send_uses_dry_run_false(self):
        """القاعدة: الإرسال الحقيقي يصير بعد موافقة الخبير فقط."""
        with mock.patch.object(qi.ilann, 'fetch_party_form', return_value=self.form), \
             mock.patch.object(qi.ilann, 'fetch_page', return_value=PAGE_DATA), \
             mock.patch.object(qi.ilann, 'send_inform',
                               return_value={'ok': True, 'code': '1',
                                             'message': 'تم حفظ الاعلان بنجاح'}) as send:
            _buttons(self.dlg)['إعلان'].click()
            ok = pump(lambda: self.dlg._party_form is not None)
            self.assertTrue(ok)
            self.dlg._on_submit(self.dlg._party_form.values())
            ok2 = pump(lambda: send.called)
        self.assertTrue(ok2)
        self.assertFalse(send.call_args[1]['dry_run'])

    def test_failed_send_shows_friendly_message(self):
        self.dlg._on_sent({'ok': False, 'code': '3', 'message': 'يوجد اعلان سابق'})
        self.assertIn('إعلان سابق', self.dlg.lbl_state.text())

    def test_connection_error_not_raw_exception(self):
        """فشل الشبكة ⟵ رسالة مفهومة، مو نص الاستثناء الخام (ومو «فشل» تأكيد)."""
        self.dlg._on_sent({'ok': False, 'code': 'err',
                           'message': 'تعذر الاتصال بالنظام: boom 1.2.3.4'})
        self.assertIn('ما نقدر نأكد', self.dlg.lbl_state.text())
        self.assertNotIn('1.2.3.4', self.dlg.lbl_state.text())

    def test_success_clears_the_form(self):
        """بعد نجاح الإعلان ⟵ النموذج ينمسح (ما يبقى زر إرسال فعّال)."""
        with mock.patch.object(qi.ilann, 'fetch_party_form', return_value=self.form), \
             mock.patch.object(qi.ilann, 'fetch_page', return_value=PAGE_DATA):
            _buttons(self.dlg)['إعلان'].click()
            ok = pump(lambda: self.dlg._party_form is not None)
            self.assertTrue(ok)
            self.dlg._on_sent({'ok': True, 'code': '1', 'message': 'تم'})
            pump(lambda: self.dlg._party_form is None)
        self.assertIsNone(self.dlg._party_form)

    def test_success_message_not_wiped_by_refresh(self):
        """«تم إرسال الإعلان» ما تنمسح برسالة «جاري التحديث»."""
        with mock.patch.object(qi.ilann, 'fetch_page', return_value=PAGE_DATA):
            self.dlg._on_sent({'ok': True, 'code': '1', 'message': 'تم'})
            pump(lambda: False, secs=0.3)
        self.assertIn('تم إرسال الإعلان', self.dlg.lbl_state.text())


class PrintTests(unittest.TestCase):
    """زر الطباعة — ما يطبع إشعار فاضي"""

    def test_print_disabled_without_results(self):
        data = {'ok': True, 'case': {}, 'parties': PARTIES, 'results': []}
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=data)
        self.assertFalse(dlg.btn_print.isEnabled())

    def test_print_enabled_with_results(self):
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA)
        self.assertTrue(dlg.btn_print.isEnabled())


class LabelTests(unittest.TestCase):
    """تسمية واحدة = معنى واحد (رقم الاتصال ≠ الرقم الآلي للقضية)"""

    def test_contact_number_label_is_distinct(self):
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA,
                             auto_no='260668600')
        labels = ' | '.join(w.text() for w in dlg.findChildren(QLabel))
        self.assertIn('الرقم الآلي للقضية', labels)
        self.assertNotIn('الرقم الآلي |', labels)

    def test_form_uses_contact_number_label(self):
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA)
        form = qi.PartyForm({'s': '1'}, 'A2264212', '2026/11/10', '01:30')
        form.load(ilann.parse_party_form(_read('party_form.html')), PARTIES[0])
        labels = ' | '.join(w.text() for w in form.findChildren(QLabel))
        self.assertIn('رقم الاتصال', labels)


class SelectionTests(unittest.TestCase):
    """اختيار الطرف: صف محدد + شارة + نموذج تحت القائمة + زر الإرسال"""

    def setUp(self):
        self.dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA,
                                   auto_no='260668600', session_date='2026/11/10')
        self.form = ilann.parse_party_form(_read('party_form.html'))

    def test_send_button_disabled_until_party_chosen(self):
        self.assertFalse(self.dlg.btn_send.isEnabled())

    def test_choosing_party_enables_send_and_marks_row(self):
        """الاختيار: النموذج ينزل + زر الإرسال يتفعّل — والتسمية ما تتغيّر."""
        with mock.patch.object(qi.ilann, 'fetch_party_form', return_value=self.form):
            _buttons(self.dlg)['إعلان'].click()
            ok = pump(lambda: self.dlg._party_form is not None)
        self.assertTrue(ok)
        self.assertTrue(self.dlg.btn_send.isEnabled())
        # التحديد يبان بالحد الكحلي على الصف — مو بشارة «الطرف المختار»
        texts = ' | '.join(w.text() for w in self.dlg.findChildren(QLabel))
        self.assertNotIn('الطرف المختار', texts)
        # والزر يبقى «إعلان» (ما يتغير لـ«فحدد للإعلان»)
        self.assertIn('إعلان', _buttons(self.dlg))
        self.assertNotIn('فحدد للإعلان', _buttons(self.dlg))

    def test_party_status_pill_reflects_results(self):
        """الطرف اللي صفّه «تم» ⟵ شارة «تم» أمامه (مو بس في الجدول)."""
        texts = ' | '.join(w.text() for w in self.dlg.findChildren(QLabel))
        self.assertIn('تم', texts)
        self.assertIn('فشل', texts)

    def test_connection_chip_shows_connected(self):
        self.assertIn('متصل', self.dlg.conn_lbl.text())

    def test_connection_chip_shows_disconnected(self):
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212',
                             data={'ok': False, 'reason': 'connection',
                                   'case': {}, 'parties': [], 'results': [],
                                   'message': ''})
        self.assertIn('تعذّر الاتصال', dlg.conn_lbl.text())

    def test_deselect_clears_form(self):
        with mock.patch.object(qi.ilann, 'fetch_party_form', return_value=self.form):
            _buttons(self.dlg)['إعلان'].click()
            ok = pump(lambda: self.dlg._party_form is not None)
        self.assertTrue(ok)
        self.dlg._deselect(PARTIES[0])
        self.assertIsNone(self.dlg._party_form)
        self.assertFalse(self.dlg.btn_send.isEnabled())

    def test_titlebar_shows_case_number(self):
        texts = ' | '.join(w.text() for w in self.dlg.findChildren(QLabel))
        self.assertIn('طلب إعلان', texts)
        self.assertIn('A2264212', texts)


class StateTests(unittest.TestCase):
    """حالات الفراغ والخطأ"""

    def test_no_parties_shows_state(self):
        data = {'ok': True, 'case': {}, 'parties': [], 'results': []}
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=data)
        widget = dlg.parties_layout.itemAt(0).widget()
        texts = ' '.join(w.text() for w in widget.findChildren(QLabel))
        self.assertIn('أطراف', texts)

    def test_connection_error_shows_state(self):
        data = {'ok': False, 'reason': 'connection',
                'message': 'تعذّر الاتصال بنظام الخبراء',
                'case': {}, 'parties': [], 'results': []}
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=data)
        widget = dlg.parties_layout.itemAt(0).widget()
        texts = ' '.join(w.text() for w in widget.findChildren(QLabel))
        self.assertIn('تعذّر الاتصال', texts)


class SessionsMenuTests(unittest.TestCase):
    """«طلب إعلان» بقائمة «إجراءات أخرى» — والبند **ما يختفي** بنفس اليوم"""

    def _card(self):
        import qt_sessions_page as qs
        sdata = {'description': 'A2264212', 'start': '2099/11/10 01:30',
                 'title': 'A2264212 اختبار'}
        return qs.SessionCardQt(sdata, {'s': '1'}, 'خبير تجريبي', lambda: None)

    def _menu_labels(self, card):
        import qt_sessions_page as qs
        fake = _FakeMenu()
        with mock.patch.object(qs, '_desk_menu', return_value=fake):
            card._show_more_actions()
        return [a.text for a in fake.actions]

    def test_menu_contains_announcement_for_upcoming(self):
        card = self._card()
        card.set_past(False)
        self.assertIn('طلب إعلان', self._menu_labels(card))

    def test_menu_shows_status_for_past_session(self):
        """⚠️ انحدار (18/11/2026): البند **ما ينحذف** لما الجلسة تنقضي.

        السبب: الخبير يحتاج يشوف «شنو صار بالإعلان» — قبل كانت ميزة الإعلان
        تختفي بنفس اليوم (بعد وقت الجلسة) وما يقدر يطّلع على النتيجة.
        ⟵ بند «حالة الإعلان» (عرض فقط) بدل «طلب إعلان» (إرسال).
        """
        card = self._card()
        card.set_past(True)
        labels = self._menu_labels(card)
        self.assertIn('حالة الإعلان', labels)
        self.assertNotIn('طلب إعلان', labels)

    def test_past_session_does_not_send_but_reads(self):
        """الجلسة المنقضية ⟵ نافذة بوضع «عرض الحالة» (ما فيها إرسال)."""
        card = self._card()
        card.set_past(True)
        seen = {}

        def fake_run_job(work, on_done):
            seen['read_only'] = card._past

        with mock.patch.object(card, '_ensure_case_data', return_value={'autocase_no': '260668600'}), \
             mock.patch.object(card, '_run_job', side_effect=fake_run_job), \
             mock.patch.object(qi.ilann, 'fetch_page', return_value={'ok': True,
                                                                   'parties': PARTIES,
                                                                   'results': []}):
            card._request_inform()
        self.assertTrue(seen.get('read_only'))

    def test_request_inform_uses_known_case(self):
        card = self._card()
        seen = {}

        def fake_run_job(work, on_done):
            seen['result'] = work()

        with mock.patch.object(card, '_ensure_case_data', return_value={'autocase_no': '260668600'}), \
             mock.patch.object(card, '_run_job', side_effect=fake_run_job), \
             mock.patch.object(qi.ilann, 'fetch_page',
                               return_value={'ok': True, 'parties': PARTIES,
                                             'results': []}) as fp:
            card._request_inform()
        self.assertTrue(fp.called)
        self.assertEqual(fp.call_args[0][1], 'A2264212')
        self.assertEqual(fp.call_args[0][2], '260668600')


class ReadOnlyDialogTests(unittest.TestCase):
    """وضع «عرض الحالة» — الجلسة مضى وقتها (نفس اليوم بعد وقتها).

    الهدف: الخبير يفتح الشاشة ويشوف «شنو صار بالإعلان» — بدون ما يقدر يرسل
    (نظام الخبراء يرفض إعلاناً لجلسة سابقة — رد «4»).
    """

    def setUp(self):
        self.dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA,
                                   auto_no='260668600', session_date='2026/11/10',
                                   session_time='01:30',
                                   case_title='شركه الاتصالات المتنقله ضد المرى',
                                   current_user='خبير تجريبي', read_only=True)

    def test_send_button_hidden(self):
        """ما فيه زر إرسال — ما ينفع (النظام ما يقبل إعلاناً لجلسة سابقة)."""
        self.assertTrue(self.dlg.btn_send.isHidden())

    def test_no_announce_button_per_party(self):
        """ما فيه زر «إعلان» لكل طرف — بس حالة كل طرف."""
        self.assertNotIn('إعلان', _buttons(self.dlg))

    def test_banner_explains_why(self):
        """شريط التنبيه يشرح السبب — الخبير يعرف ليش ما فيه إرسال."""
        texts = ' | '.join(w.text() for w in self.dlg.findChildren(QLabel))
        self.assertIn('مضى وقتها', texts)
        self.assertIn('حالة الإعلان', texts)

    def test_results_table_still_shown(self):
        """الجدول موجود — هذا هو المقصود من «حالة الإعلان»."""
        self.assertEqual(self.dlg.tbl_results.rowCount(), 2)
        self.assertEqual(self.dlg.tbl_results.item(0, 4).text(), 'تم')

    def test_title_is_status_not_request(self):
        self.assertIn('حالة الإعلان', self.dlg.windowTitle())

    def test_session_labels_not_upcoming(self):
        """التسمية تتبع الحالة — ما نقول «الجلسة القادمة» لجلسة منقضية."""
        texts = [w.text() for w in self.dlg.findChildren(QLabel)]
        self.assertNotIn('تاريخ الجلسة القادمة', texts)
        self.assertIn('تاريخ الجلسة', texts)

    def test_open_party_does_nothing(self):
        """ما نفتح نموذج ولا نسمح بإرسال."""
        self.dlg._open_party(PARTIES[0])
        self.assertIsNone(self.dlg._party_form)
        self.assertEqual(self.dlg.form_layout.count(), 0)

    def test_send_selected_is_blocked(self):
        """حتى لو اتصلنا بالزر برمجياً ⟵ ما يصير إرسال."""
        self.dlg._send_selected()
        self.assertIsNone(self.dlg._party_form)

    def test_empty_message_read_only(self):
        """بلا نتائج ⟵ رسالة صادقة «ما فيه إعلان مسجّل»."""
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212',
                             data={'ok': True, 'case': {}, 'parties': PARTIES,
                                   'results': []},
                             auto_no='260668600', session_date='2026/11/10',
                             read_only=True)
        texts = ' | '.join(w.text() for w in dlg.findChildren(QLabel))
        self.assertIn('ما فيه إعلان مسجّل', texts)

    def test_case_level_note_shown(self):
        """لو النتائج جت على مستوى القضية ⟵ نوضّح للخبير (أمانة الأرقام)."""
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212',
                             data={'ok': True, 'case': {}, 'parties': PARTIES,
                                   'results': RESULTS, 'case_level': True},
                             auto_no='260668600', session_date='2026/11/10',
                             read_only=True)
        texts = ' | '.join(w.text() for w in dlg.findChildren(QLabel))
        self.assertIn('على مستوى القضية', texts)

    def test_case_level_note_hidden_for_normal_session(self):
        """الجلسة القادمة ⟵ ما في تنبيه «مستوى القضية»."""
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA,
                             auto_no='260668600', session_date='2026/11/10')
        texts = ' | '.join(w.text() for w in dlg.findChildren(QLabel))
        self.assertNotIn('على مستوى القضية', texts)


class ShellTests(unittest.TestCase):
    """«طلب إعلان» ما عاد في الشريط الجانبي — بفتحه من بطاقة الجلسة"""

    def test_sidebar_has_no_announcement_entry(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'qt_shell_v2.py')
        src = open(path, encoding='utf-8').read()
        self.assertNotIn("add('ilann'", src)
        self.assertNotIn("'ilann':", src)


class _FakeAction:
    def __init__(self, text):
        self.text = text


class _FakeMenu:
    def __init__(self):
        self.actions = []

    def addAction(self, icon, text):
        a = _FakeAction(text)
        self.actions.append(a)
        return a

    def addSeparator(self):
        pass

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(200, 100)

    def exec(self, pos):
        return None


class ClaimAddressTests(unittest.TestCase):
    """زر «سحب العنوان من صحيفة الدعوى» — يجيب العنوان من صحيفة الدعوى"""

    DATA_WITH_LAWYER = {
        'found': True,
        'address': {'city': 'محافظه العاصمه', 'area': 'حطين',
                    'street': 'أحمد الجابر', 'block': '5', 'floor': '10',
                    'unit': '23', 'unit_type': 'شقة',
                    'description': 'منطقة حطين قطعة 5 شارع أحمد الجابر شقة 23'},
        'has_lawyer': True,
        'lawyer': {'name': 'عبدالله المحامي', 'phone': '09650000',
                   'fax': '22222222', 'address': {'description': 'مكتب في العليا'}},
    }

    DATA_NO_LAWYER = {
        'found': True,
        'address': {'city': 'حولي', 'area': 'السالمية', 'street': 'شارع محمد',
                    'description': 'منطقة السالمية شارع محمد'},
        'has_lawyer': False,
        'lawyer': {'name': None, 'phone': None, 'fax': None, 'address': {}},
    }

    def setUp(self):
        self.form_data = ilann.parse_party_form(_read('party_form.html'))
        self.form = qi.PartyForm({'s': '1'}, 'A2264212', '2026/11/10', '01:30',
                                 auto_no='260668600')
        self.form.load(self.form_data, PARTIES[0])

    def _run_claim(self, data=None, error=None, message=None):
        """يضغط الزر وينتظر النتيجة (الخيط يشتغل بالخلفية)."""
        with mock.patch.object(qi.ilann_claim, 'fetch_and_extract',
                               return_value=(data, error, message)) as fetch:
            self.form._on_claim()
            self.assertTrue(pump(lambda: bool(self.form.claim_lbl.text())),
                            'ما وصلت نتيجة السحب')
        return fetch

    def test_claim_button_exists(self):
        self.assertIn('سحب العنوان من صحيفة الدعوى', _buttons(self.form))

    def test_claim_fills_address_as_written_without_lawyer(self):
        """بدون محامٍ ⟵ العنوان «مثل ما هو مكتوب» ووسيلة الإعلان ما تتغيّر."""
        # نخليها «فاكس» قبل السحب ⟵ لازم تفضل فاكس (ما يصير مندوب تلقائياً)
        self.form.cb_method.setCurrentIndex(self.form.cb_method.findData('10002'))
        method_before = self.form.cb_method.currentData()
        self._run_claim(data=self.DATA_NO_LAWYER)
        self.assertEqual(self.form.edits['ADRS_STREET'].text(), 'شارع محمد')
        self.assertEqual(self.form.edits['ADRS_DESCR'].text(),
                         'منطقة السالمية شارع محمد')
        self.assertEqual(self.form.cb_city.currentData(), '2')
        self.assertEqual(self.form.cb_method.currentData(), method_before)
        self.assertNotEqual(self.form.cb_method.currentData(), '10001')

    def test_claim_with_lawyer_sets_representative_and_contact(self):
        """مع محامٍ ⟵ «مندوب» + اسم المحامي وهاتفه وفاكسه في خانات الاتصال تحت."""
        self._run_claim(data=self.DATA_WITH_LAWYER)
        self.assertEqual(self.form.cb_method.currentData(), '10001')
        self.assertEqual(self.form.cb_method.currentText(), 'مندوب')
        self.assertEqual(self.form.edits['ADDRNO'].text(), '09650000')
        self.assertEqual(self.form.edits['MAIN_CNTD_TYPE_DESC'].text(),
                         'المحامي: عبدالله المحامي')
        note = self.form.edits['EIF_NOTE'].text()
        self.assertIn('09650000', note)
        self.assertIn('22222222', note)
        self.assertEqual(self.form.cb_city.currentData(), '1')

    def test_claim_sets_zone_when_matched(self):
        self._run_claim(data=self.DATA_WITH_LAWYER)
        self.assertEqual(self.form.cb_zone.currentData(), '235')  # حطين

    def test_claim_failure_shows_error_and_reenables_button(self):
        self._run_claim(data=None, error='صحيفة الدعوى ما تحتوي على عنوان المدعى عليه '
                                         '— الموجود بالصحيفة: شركه الاتصالات')
        # الجواب قصير جنب الزر…
        self.assertIn('ما تحتوي على عنوان', self.form.claim_lbl.text())
        # …والتفصيل (شنو مالقيت) تحته
        self.assertIn('الموجود بالصحيفة', self.form.claim_detail.text())
        self.assertTrue(self.form.btn_claim.isEnabled())

    def test_claim_status_sits_next_to_the_button(self):
        """سطر الحالة بنفس صف الزر — الجواب يطلع مكان «جاري السحب»."""
        head = self.form.btn_claim.parentWidget()
        self.assertIs(self.form.claim_lbl.parentWidget(), head)
        self.assertEqual(self.form.claim_lbl.geometry().y(),
                         self.form.btn_claim.geometry().y())

    def test_claim_detail_line_exists_below(self):
        self.assertIsNotNone(self.form.claim_detail)

    def test_progress_updates_the_same_line(self):
        """تحديثات الخطوات (تأكّد/تنزيل/تحويل) تطلع بنفس سطر الحالة."""
        seen = []
        self.form._claim_progress.connect(seen.append)

        prep = {'ok': True, 'text': 'نص', 'pdf': '', 'message': 'تم'}
        with mock.patch.object(qi.ilann_claim, 'ensure_claim_markdown',
                               return_value=prep), \
             mock.patch.object(qi.ilann_claim, 'extract_party_address_from_text',
                               return_value=({'found': True, 'address': {'street': 'ش'}}, None)):
            self.form._on_claim()
            self.assertTrue(pump(lambda: bool(self.form.claim_lbl.text())))
            self.assertTrue(seen)
            self.assertIn('جاري سحب المعلومات', ' '.join(seen))

    def test_claim_without_auto_number_does_not_fetch(self):
        """ما فيه رقم آلي ⟵ ما نحاول نجيب صحيفة الدعوى."""
        form = qi.PartyForm({'s': '1'}, 'A2264212')
        form.load(self.form_data, PARTIES[0])
        with mock.patch.object(qi.ilann_claim, 'find_local_claim', return_value=''), \
             mock.patch.object(qi.ilann_claim, 'fetch_and_extract') as fetch:
            form._on_claim()
        fetch.assert_not_called()
        self.assertIn('ما فيه رقم آلي', form.claim_lbl.text())

    def test_local_claim_works_without_auto_number(self):
        """فيه صحيفة محفوظة بالجهاز ⟵ نستخدمها حتى بدون رقم آلي (ما ننزّل من النظام)."""
        form = qi.PartyForm({'s': '1'}, 'A2264212')
        form.load(self.form_data, PARTIES[0])
        with mock.patch.object(qi.ilann_claim, 'find_local_claim',
                               return_value='C:/tmp/claim.pdf'), \
             mock.patch.object(qi.ilann_claim, 'fetch_and_extract',
                               return_value=(self.DATA_WITH_LAWYER, None, 'تم')) as fetch:
            form._on_claim()
            self.assertTrue(pump(lambda: bool(form.claim_lbl.text())))
        fetch.assert_called()

    def test_status_reaches_bottom_bar(self):
        """النتيجة توصل الشريط السفلي (مو مختفية جوه النموذج)."""
        dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA,
                             auto_no='260668600', session_date='2026/11/10')
        dlg._on_form_ready({'party': PARTIES[0], 'form': self.form_data})
        self.assertEqual(dlg._party_form.auto_no, '260668600')
        with mock.patch.object(qi.ilann_claim, 'fetch_and_extract',
                               return_value=(self.DATA_WITH_LAWYER, None, 'تم')):
            dlg._party_form._on_claim()
            self.assertTrue(pump(lambda: bool(dlg.lbl_state.text())))
        self.assertIn('مندوب', dlg.lbl_state.text())


class ClaimViewTests(unittest.TestCase):
    """زر «عرض صحيفة الدعوى» — يفتحها على **يسار الشاشة** (مشاهدة مباشرة)"""

    def setUp(self):
        self.dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA,
                                   auto_no='260668600', session_date='2026/11/10',
                                   session_time='01:30')
        self.form = ilann.parse_party_form(_read('party_form.html'))

    def _open_form(self):
        with mock.patch.object(qi.ilann, 'fetch_party_form', return_value=self.form):
            _buttons(self.dlg)['إعلان'].click()
            ok = pump(lambda: self.dlg._party_form is not None)
        self.assertTrue(ok, 'النموذج ما ظهر')
        return self.dlg._party_form

    @staticmethod
    def _fake_pdf():
        """ملف PDF حقيقي (صفحة وحدة) — عشان QPdfDocument يفتحه."""
        import tempfile
        import fitz
        path = os.path.join(tempfile.mkdtemp(), 'صحيفة الدعوى.pdf')
        doc = fitz.open()
        doc.new_page()
        doc.save(path)
        doc.close()
        return path

    def test_view_button_exists(self):
        form = self._open_form()
        self.assertIn('عرض صحيفة الدعوى', _buttons(form))

    def test_view_opens_window_for_saved_claim(self):
        """الصحيفة محفوظة ⟵ تفتح مباشرة (بدون تنزيل)."""
        form = self._open_form()
        path = self._fake_pdf()
        with mock.patch.object(qi.ilann_claim, 'find_local_claim', return_value=path), \
             mock.patch.object(qi, 'open_claim_viewer') as viewer:
            form._on_view_claim()
        viewer.assert_called_once()
        self.assertEqual(viewer.call_args[0][1], path)

    def test_view_downloads_when_missing(self):
        """ما فيه ملف ⟵ نجيبه من الملف الآلي (بدون ذكاء) ثم نفتحه."""
        form = self._open_form()
        path = self._fake_pdf()
        prep = {'ok': True, 'pdf': path, 'message': 'تم'}
        with mock.patch.object(qi.ilann_claim, 'find_local_claim', return_value=''), \
             mock.patch.object(qi.ilann_claim, 'ensure_claim_markdown',
                               return_value=prep) as ensure, \
             mock.patch.object(qi, 'open_claim_viewer') as viewer:
            form._on_view_claim()
            ok = pump(lambda: viewer.called)
        self.assertTrue(ok, 'النافذة ما فتحت')
        ensure.assert_called_once()

    def test_viewer_window_placed_on_the_left(self):
        """النافذة تنفتح على **يسار الشاشة**."""
        from PyQt6.QtWidgets import QDialog
        host = QDialog()
        host.resize(1120, 780)
        win = qi.open_claim_viewer(host, self._fake_pdf())
        geo = qi._screen_of(host).availableGeometry()
        self.assertEqual(win.x(), geo.left())
        self.assertLessEqual(win.width(), geo.width())
        self.assertTrue(win.isVisible())
        win.close()

    def test_viewer_is_not_modal(self):
        """نافذة مستقلة (مو ؟) — الخبير يقدر يكمل بالنموذج بنفس الوقت."""
        from PyQt6.QtWidgets import QDialog
        host = QDialog()
        win = qi.open_claim_viewer(host, self._fake_pdf())
        self.assertFalse(win.isModal())
        win.close()

    def test_viewer_keeps_reference_on_parent(self):
        """مرجع النافذة محفوظ بالنافذة أم — ما تنحذف وتختفي."""
        from PyQt6.QtWidgets import QDialog
        host = QDialog()
        form = qi.PartyForm({'s': '1'}, 'A2264212')
        form.load(self.form, PARTIES[0])
        form.setParent(host)
        with mock.patch.object(qi.ilann_claim, 'find_local_claim',
                               return_value=self._fake_pdf()):
            form._open_claim_window(self._fake_pdf())
        self.assertIsNotNone(getattr(host, '_claim_viewer', None))
        getattr(host, '_claim_viewer').close()


class SelectedPartyTests(unittest.TestCase):
    """الطرف المختار ⟵ لونه يتغيّر (نقطة كحلية + خلفية + شارة «محدد»)"""

    def setUp(self):
        self.dlg = qi.IlannDialog({'s': '1'}, 'A2264212', data=PAGE_DATA,
                                   auto_no='260668600', session_date='2026/11/10')

    def _row_of(self, party):
        for w in self.dlg.parties_box.findChildren(type(self.dlg.lbl_state).__mro__[0]):
            pass
        return self.dlg._party_row(party)

    def test_selected_row_is_marked(self):
        self.dlg._selected = PARTIES[1]
        row = self.dlg._party_row(PARTIES[1])
        texts = ' '.join(w.text() for w in row.findChildren(QLabel))
        self.assertIn('\u0645\u062d\u062f\u062f', texts)          # «محدد»
        self.assertIn(qi.th.NAVY, row.styleSheet())

    def test_unselected_row_is_not_marked(self):
        self.dlg._selected = PARTIES[0]
        row = self.dlg._party_row(PARTIES[1])
        texts = ' '.join(w.text() for w in row.findChildren(QLabel))
        self.assertNotIn('\u0645\u062d\u062f\u062f', texts)

    def test_selected_dot_is_navy(self):
        """نقطة الطرف المختار كحلية (مو رمادية)."""
        self.dlg._selected = PARTIES[1]
        row = self.dlg._party_row(PARTIES[1])
        dots = [w for w in row.findChildren(QFrame)
                if w.width() == 10 and w.height() == 10]
        self.assertTrue(dots)
        self.assertIn(qi.th.NAVY, dots[0].styleSheet())


if __name__ == '__main__':
    unittest.main()
