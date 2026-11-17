# ===== test_icloud_calendar.py — اختبارات مزامنة تقويم iCloud =====
"""
اختبارات وحدة `icloud_calendar.py` (المهمة㉓ — تجاوز البورت **تلقائي وصامت**).

⚠️ **ما فيه أي طلب شبكة حقيقي**: كل مسارات الشبكة (CalDAV + الوسيط)
مُموكَسة على مستوى الموديول. الحسابات تُكتب بمجلد مؤقت (ما نلمس
بيانات الخبير الحقيقية).

المغطى:
  • المهلات القصيرة (8 ث) لكل محاولة.
  • **سلسلة المحاولات التلقائية**: مباشر ⟵ وسيط ⟵ مباشر ⟵ رسالة.
  • **حارس «ما فيه واجهة»**: لا إعدادات شبكة ولا تصدير .ics ولا زر.
  • تشفير RSA-OAEP (SHA-256) — المطابقة للخاص (دورة كاملة).
  • فحص الاتصال بنفس السلسلة (مع حذف الموعد التجريبي).
"""
import os
import sys
import json
import base64
import datetime
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import icloud_calendar as icc

_DT = datetime.datetime(2026, 11, 18, 8, 0)


# ---------------------------------------------------------------------------
# أدوات مساعدة
# ---------------------------------------------------------------------------

class _FakeEvent:
    """موعد وهمي (يحاكي caldav Event)."""

    def __init__(self, summary=''):
        self.summary = summary
        self.deleted = False
        self.loaded = False

    def load(self):
        self.loaded = True

    def delete(self):
        self.deleted = True

    @property
    def icalendar_component(self):
        return {'summary': self.summary}


class _FakeCalendar:
    """تقويم وهمي — date_search يرجع مواعيد، save_event يرجع موعد."""

    def __init__(self, name='تقويم', existing=None, fail_save=False):
        self.name = name
        self._existing = list(existing or [])
        self._fail_save = fail_save
        self.saved = []

    def date_search(self, start, end):
        return list(self._existing)

    def save_event(self, ics):
        if self._fail_save:
            raise RuntimeError('تعذرت الكتابة على هذا التقويم')
        self.saved.append(ics)
        return _FakeEvent()


class _NetworkError(Exception):
    """خطأ شبكة نموذجي (نفس شكل طلب ministry المحجوب)."""
    def __str__(self):
        return ('HTTPSConnectionPool(host=\'caldav.icloud.com\', port=443): '
                'Read timed out. (read timeout=8)')


class _AuthError(Exception):
    def __str__(self):
        return '401 Unauthorized'


class ICloudCalendarBase(unittest.TestCase):
    """أساس: يوجّه ملفات الإعدادات لمجلد مؤقت (ما نلمس بيانات الخبير)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = self._tmp.name
        self._cfg = os.path.join(self._dir, 'icloud_calendar.json')

        self._patches = [
            mock.patch.object(icc, '_config_path', lambda: self._cfg),
            mock.patch.object(icc, '_OLD_CONFIG_PATH',
                              os.path.join(self._dir, '__no_old__.json')),
        ]
        for p in self._patches:
            p.start()

        # بيانات حساب موجودة (كل الاختبارات تفترض حساب مربوط)
        with open(self._cfg, 'w', encoding='utf-8') as f:
            json.dump({'apple_id': 'expert@test.com',
                       'app_password': 'abcd-efgh-ijkl-mnop'}, f)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# 1) المهلات القصيرة
# ---------------------------------------------------------------------------

class TimeoutTests(ICloudCalendarBase):

    def test_direct_timeout_is_short_not_thirty(self):
        """المهلة 8 ث — مو 30 (الـ30 كانت تعلّق المستخدم نص دقيقة)"""
        self.assertLessEqual(icc.CALDAV_TIMEOUT, 10)
        self.assertGreater(icc.CALDAV_TIMEOUT, 0)

    def test_relay_timeout_is_twelve(self):
        """
        ⚠️ مهلة الوسيط **12 ث** (مو 8): أول نداء بعد خمول الدالة قيس
        بـ5–6.2 ث ⟵ بمهلة 8 ث ممكن تفشل قبل ما الخادم يكمّل الكتابة.
        ومو 30 أبداً (الـ30 كانت تعلّق المستخدم نص دقيقة).
        """
        self.assertEqual(icc.RELAY_TIMEOUT, 12)
        self.assertLess(icc.RELAY_TIMEOUT, 30)
        self.assertGreater(icc.RELAY_TIMEOUT, 0)

    def test_dav_client_passes_timeout(self):
        """المهلة تُمرَّر لـcaldav — بدونها الـdefault 30 ثانية"""
        captured = {}

        def fake_client(**kw):
            captured.update(kw)
            return object()

        with mock.patch('caldav.DAVClient', side_effect=fake_client):
            icc._dav_client()
        self.assertEqual(captured.get('timeout'), icc.CALDAV_TIMEOUT)
        self.assertEqual(captured.get('url'), 'https://caldav.icloud.com/')

    def test_dav_client_has_no_proxy_key(self):
        """ما في بروكسي anymore — لا تمرير مفتاح proxy للعميل"""
        captured = {}

        def fake_client(**kw):
            captured.update(kw)
            return object()

        with mock.patch('caldav.DAVClient', side_effect=fake_client):
            icc._dav_client()
        self.assertNotIn('proxy', captured)

    def test_dav_client_without_credentials_raises(self):
        with open(self._cfg, 'w', encoding='utf-8') as f:
            json.dump({'apple_id': '', 'app_password': ''}, f)
        with self.assertRaises(ValueError):
            icc._dav_client()


# ---------------------------------------------------------------------------
# 2) حارس «ما فيه واجهة» — ⚠️ أهم ما في الملف
# ---------------------------------------------------------------------------

class InvisibleFeatureTests(ICloudCalendarBase):
    """
    ⚠️ **حارس انحدار**: ميزة تجاوز البورت لازم تكون **غير مرئية تماماً**.
    أي واجهة إعدادات (بروكسي/checkbox) أو تصدير .ics ⟵ رجوع للوضع القديم.
    """

    def test_no_network_settings_api(self):
        for name in ('load_net_settings', 'save_net_settings',
                     '_mark_direct_failure', '_direct_recently_failed'):
            self.assertFalse(hasattr(icc, name),
                             '%s رجعت — تجاوز البورت لازم يكون صامت' % name)

    def test_no_ics_export_api(self):
        """خيار تصدير ملف .ics المحلي — محذوف نهائياً"""
        for name in ('export_ics', 'open_ics'):
            self.assertFalse(hasattr(icc, name),
                             '%s رجعت — ما فيه تحويل لملفات' % name)

    def test_no_settings_file_is_written(self):
        """المزامنة ما تكتب أي ملف إعدادات (ما فيه إعدادات أصلاً)"""
        cal = _FakeCalendar('تقويم شخصي')
        with mock.patch.object(icc, '_get_calendars', return_value=[cal]):
            ok, err = icc.add_calendar_event('موعد', _DT)
        self.assertTrue(ok, err)
        leftovers = [f for f in os.listdir(self._dir)
                     if f not in ('icloud_calendar.json',)]
        self.assertEqual(leftovers, [],
                         'المزامنة كتبت ملفات إعدادات: %s' % leftovers)

    def test_module_has_no_visible_settings_widgets(self):
        """ما فيه أي استيراد لوحدات واجهة الإعدادات"""
        src = open(icc.__file__, encoding='utf-8').read()
        for bad in ('PyQt', 'tkinter', 'QCheckBox', 'QDialog'):
            self.assertNotIn(bad, src,
                             '%s داخل وحدة المزامنة — لازم تكون منطق بس' % bad)


# ---------------------------------------------------------------------------
# 3) سلسلة المحاولات التلقائية — الترتيب
# ---------------------------------------------------------------------------

class ChainOrderTests(ICloudCalendarBase):

    def test_no_credentials_returns_error(self):
        with open(self._cfg, 'w', encoding='utf-8') as f:
            json.dump({'apple_id': '', 'app_password': ''}, f)
        ok, err = icc.add_calendar_event('موعد', _DT)
        self.assertFalse(ok)
        self.assertIn('iCloud', err)

    def test_direct_success_stops_chain(self):
        """مباشر نجح ⟵ ما نكمّل (ما فيه طلب زيادة)"""
        cal = _FakeCalendar('تقويم شخصي')
        with mock.patch.object(icc, '_get_calendars', return_value=[cal]), \
                mock.patch.object(icc, 'add_calendar_event_via_relay') as relay:
            ok, err = icc.add_calendar_event('موعد', _DT)
        self.assertTrue(ok, err)
        relay.assert_not_called()
        self.assertEqual(len(cal.saved), 1)

    def test_order_is_direct_then_relay_then_direct(self):
        """
        ⚠️ الترتيب المطلوب: **مباشر ⟵ وسيط ⟵ مباشر** — وبعدها رسالة وحدة.
        """
        calls = []

        def fake_direct(*a, **kw):
            calls.append('direct')
            return (False, 'انتهت مهلة الاتصال', 'network')

        def fake_relay(*a, **kw):
            calls.append('relay')
            return (False, 'الوسيط ما رد (404)')

        with mock.patch.object(icc, '_write_direct', side_effect=fake_direct), \
                mock.patch.object(icc, 'add_calendar_event_via_relay',
                                  side_effect=fake_relay):
            ok, err = icc.add_calendar_event('موعد', _DT)

        self.assertFalse(ok)
        self.assertEqual(calls, ['direct', 'relay', 'direct'])
        self.assertEqual(err, icc.BLOCKED_MESSAGE)

    def test_relay_used_after_direct_failure(self):
        """سيناريو الوزارة: مباشر معلّق ⟵ الوسيط يشتغل"""
        with mock.patch.object(icc, '_get_calendars', side_effect=_NetworkError()), \
                mock.patch.object(icc, 'add_calendar_event_via_relay',
                                  return_value=(True, None)) as relay:
            ok, err = icc.add_calendar_event('موعد', _DT)
        self.assertTrue(ok, err)
        relay.assert_called_once()

    def test_second_direct_attempt_succeeds(self):
        """الوسيط فشل ⟵ المحاولة المباشرة الثانية تنجح"""
        state = {'n': 0}

        def fake_direct(*a, **kw):
            state['n'] += 1
            if state['n'] == 1:
                return (False, 'انتهت مهلة الاتصال', 'network')
            return (True, None, None)

        with mock.patch.object(icc, '_write_direct', side_effect=fake_direct), \
                mock.patch.object(icc, 'add_calendar_event_via_relay',
                                  return_value=(False, 'الوسيط ما رد (404)')):
            ok, err = icc.add_calendar_event('موعد', _DT)
        self.assertTrue(ok, err)
        self.assertEqual(state['n'], 2)

    def test_auth_failure_ends_with_auth_message(self):
        """بيانات الحساب غلط ⟵ رسالة البيانات (مو رسالة البورت)"""
        with mock.patch.object(icc, '_write_direct',
                               return_value=(False, '401 Unauthorized', 'auth')), \
                mock.patch.object(icc, 'add_calendar_event_via_relay',
                                  return_value=(False, 'الوسيط ما رد (404)')):
            ok, err = icc.add_calendar_event('موعد', _DT)
        self.assertFalse(ok)
        self.assertEqual(err, icc.AUTH_MESSAGE)

    def test_write_failure_on_first_calendar_tries_second(self):
        bad = _FakeCalendar('تقويم نظام', fail_save=True)
        good = _FakeCalendar('تقويم شخصي')
        with mock.patch.object(icc, '_get_calendars', return_value=[bad, good]), \
                mock.patch.object(icc, 'add_calendar_event_via_relay') as relay:
            ok, err = icc.add_calendar_event('موعد', _DT)
        self.assertTrue(ok, err)
        self.assertEqual(len(good.saved), 1)
        relay.assert_not_called()

    def test_existing_same_summary_is_replaced(self):
        """تجديد بدل تكرار: الموعد القديم بنفس العنوان يُحذف أولاً"""
        old = _FakeEvent('جلسة - A123')
        cal = _FakeCalendar('تقويم', existing=[old])
        with mock.patch.object(icc, '_get_calendars', return_value=[cal]):
            ok, err = icc.add_calendar_event('جلسة - A123', _DT)
        self.assertTrue(ok, err)
        self.assertTrue(old.deleted)
        self.assertEqual(len(cal.saved), 1)

    def test_direct_network_failure_is_treated_as_network(self):
        """خطأ الشبكة ⟵ تصنيف 'network' (يعني المحاولة التالية تنفع)"""
        with mock.patch.object(icc, '_get_calendars', side_effect=_NetworkError()):
            ok, err, kind = icc._write_direct('موعد', _DT)
        self.assertFalse(ok)
        self.assertEqual(kind, 'network')


# ---------------------------------------------------------------------------
# 4) الوسيط — التشفير والمسار
# ---------------------------------------------------------------------------

class RelayTests(ICloudCalendarBase):

    def _make_keypair(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo).decode('utf-8')
        return key, pem

    def test_password_is_encrypted_with_rsa_oaep_sha256(self):
        """
        ⚠️ كلمة المرور **ما تنرسل أبداً كنص** — تنرسل مشفّرة بمفتاح
        عام، والخاص عند الخادم بس. والدورة الكاملة (تشفير ← فك) هي
        الدليل إن التشفير متوافق مع الطرف الآخر.
        """
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        private_key, public_pem = self._make_keypair()
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured['url'] = url
            captured['json'] = json
            captured['headers'] = headers
            captured['timeout'] = timeout

            class R:
                status_code = 200

                def json(self):
                    return {'ok': True}
            return R()

        with mock.patch.object(icc, 'RELAY_PUBLIC_KEY_PEM', public_pem), \
                mock.patch('requests.post', side_effect=fake_post):
            ok, err = icc.add_calendar_event_via_relay('جلسة - A1', _DT)
        self.assertTrue(ok, err)

        body = captured['json']
        self.assertNotIn('abcd-efgh-ijkl-mnop', json.dumps(body))
        self.assertIn('password_b64', body)
        self.assertEqual(body['apple_id'], 'expert@test.com')

        enc = base64.b64decode(body['password_b64'])
        plain = private_key.decrypt(
            enc,
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                         algorithm=hashes.SHA256(), label=None))
        self.assertEqual(plain.decode('utf-8'), 'abcd-efgh-ijkl-mnop')

    def test_relay_sends_token_header(self):
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured['headers'] = headers

            class R:
                status_code = 200

                def json(self):
                    return {'ok': True}
            return R()

        with mock.patch('requests.post', side_effect=fake_post):
            icc.add_calendar_event_via_relay('موعد', _DT)
        self.assertEqual(captured['headers'].get('x-relay-token'), icc.RELAY_TOKEN)

    def test_relay_uses_short_timeout(self):
        """مهلة الطلب = 8 ث (ما نبقي المستخدم منتظر)"""
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured['timeout'] = timeout

            class R:
                status_code = 200

                def json(self):
                    return {'ok': True}
            return R()

        with mock.patch('requests.post', side_effect=fake_post):
            icc.add_calendar_event_via_relay('موعد', _DT)
        self.assertEqual(captured.get('timeout'), icc.RELAY_TIMEOUT)

    def test_delete_after_flag_is_sent(self):
        """فحص الاتصال ⟵ الخادم يحذف الموعد التجريبي فور كتابته"""
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured['json'] = json

            class R:
                status_code = 200

                def json(self):
                    return {'ok': True}
            return R()

        with mock.patch('requests.post', side_effect=fake_post):
            icc.add_calendar_event_via_relay('موعد', _DT, delete_after=True)
        self.assertTrue(captured['json'].get('delete_after'))

    def test_relay_non_200_gives_clear_message(self):
        def fake_post(*a, **kw):
            class R:
                status_code = 404
            return R()

        with mock.patch('requests.post', side_effect=fake_post):
            ok, err = icc.add_calendar_event_via_relay('موعد', _DT)
        self.assertFalse(ok)
        self.assertIn('404', err)

    def test_relay_error_body_is_propagated(self):
        def fake_post(*a, **kw):
            class R:
                status_code = 200

                def json(self):
                    return {'ok': False, 'error': 'بيانات غير صحيحة'}
            return R()

        with mock.patch('requests.post', side_effect=fake_post):
            ok, err = icc.add_calendar_event_via_relay('موعد', _DT)
        self.assertFalse(ok)
        self.assertIn('بيانات غير صحيحة', err)

    def test_relay_without_credentials_fails_fast(self):
        with open(self._cfg, 'w', encoding='utf-8') as f:
            json.dump({'apple_id': '', 'app_password': ''}, f)
        ok, err = icc.add_calendar_event_via_relay('موعد', _DT)
        self.assertFalse(ok)
        self.assertIn('iCloud', err)


# ---------------------------------------------------------------------------
# 5) فحص الاتصال — بنفس السلسلة التلقائية
# ---------------------------------------------------------------------------

class TestConnectionTests(ICloudCalendarBase):

    def test_direct_success_returns_calendar_name(self):
        """الوسيط ما نجح ⟵ نكمّل للمباشر ونرجّع اسم التقويم"""
        cal = _FakeCalendar('تقويم شخصي')
        with mock.patch.object(icc, 'add_calendar_event_via_relay',
                               return_value=(False, 'تعذّر')), \
                mock.patch.object(icc, '_get_calendars', return_value=[cal]):
            ok, msg = icc.test_connection()
        self.assertTrue(ok, msg)
        self.assertIn('تقويم شخصي', msg)
        self.assertEqual(len(cal.saved), 1)
        self.assertIn('ConnectionTest', cal.saved[0])

    def test_relay_used_first(self):
        """
        ⚠️ زر «اختبار» لازم يكون **سريع** بشبكة الدوام:
        الوسيط أولاً (‏~3 ث) بدل انتظار 8 ث على المباشر المحجوب.
        """
        with mock.patch.object(icc, 'add_calendar_event_via_relay',
                               return_value=(True, None)) as relay, \
                mock.patch.object(icc, '_get_calendars') as direct:
            ok, msg = icc.test_connection()
        self.assertTrue(ok, msg)
        relay.assert_called_once()
        direct.assert_not_called()
        self.assertIn('وسيط', msg)

    def test_direct_used_when_relay_fails(self):
        """الوسيط فشل ⟵ نجرّب المباشر (فحص كامل للحساب)"""
        cal = _FakeCalendar('تقويم شخصي')
        with mock.patch.object(icc, 'add_calendar_event_via_relay',
                               return_value=(False, 'الوسيط ما رد (404)')), \
                mock.patch.object(icc, '_get_calendars', return_value=[cal]):
            ok, msg = icc.test_connection()
        self.assertTrue(ok, msg)
        self.assertIn('تقويم شخصي', msg)

    def test_relay_test_event_is_deleted_after_write(self):
        """⚠️ فحص الاتصال عبر الوسيط ⟵ الموعد التجريبي لازم ينحذف"""
        captured = {}

        def fake_relay(summary, start, duration_minutes=60, description='',
                       delete_after=False):
            captured['delete_after'] = delete_after
            captured['summary'] = summary
            return (True, None)

        with mock.patch.object(icc, '_get_calendars', side_effect=_NetworkError()), \
                mock.patch.object(icc, 'add_calendar_event_via_relay',
                                  side_effect=fake_relay):
            ok, msg = icc.test_connection()
        self.assertTrue(ok, msg)
        self.assertTrue(captured.get('delete_after'))
        self.assertIn('connection_test', captured.get('summary', '').lower())

    def test_all_failures_report_blocked_message(self):
        with mock.patch.object(icc, '_get_calendars', side_effect=_NetworkError()), \
                mock.patch.object(icc, 'add_calendar_event_via_relay',
                                  return_value=(False, 'الوسيط ما رد (404)')):
            ok, msg = icc.test_connection()
        self.assertFalse(ok)
        self.assertEqual(msg, icc.BLOCKED_MESSAGE)

# ---------------------------------------------------------------------------
# 6) الرسائل والتصنيف
# ---------------------------------------------------------------------------

class MessageTests(ICloudCalendarBase):

    def test_timeout_is_network_error(self):
        self.assertTrue(icc.is_network_error(_NetworkError()))

    def test_auth_error_is_not_network_error(self):
        self.assertFalse(icc.is_network_error(_AuthError()))

    def test_classify_auth(self):
        self.assertEqual(icc.classify_error(_AuthError()), 'auth')

    def test_classify_network(self):
        self.assertEqual(icc.classify_error(_NetworkError()), 'network')

    def test_friendly_error_mentions_timeout_in_arabic(self):
        msg = icc.friendly_error(_NetworkError())
        self.assertIn('مهلة', msg)

    def test_friendly_error_for_credentials(self):
        msg = icc.friendly_error(_AuthError())
        self.assertIn('iCloud', msg)

    def test_blocked_message_mentions_port(self):
        self.assertIn('البورت', icc.BLOCKED_MESSAGE)

    def test_messages_have_no_action_buttons(self):
        """الرسالة نصية فقط — ما فيها دعوة لزر أو ملف"""
        for msg in (icc.BLOCKED_MESSAGE, icc.AUTH_MESSAGE):
            self.assertNotIn('.ics', msg)
            self.assertNotIn('إعادة المحاولة', msg)


# ---------------------------------------------------------------------------
# 7) الثوابت (حارس accidental writes)
# ---------------------------------------------------------------------------

class ConstantsTests(unittest.TestCase):

    def test_relay_url_points_to_supabase_function(self):
        self.assertTrue(icc.RELAY_URL.startswith('https://'))
        self.assertIn('/functions/v1/calendar-relay', icc.RELAY_URL)

    def test_relay_token_present(self):
        self.assertTrue(icc.RELAY_TOKEN)
        self.assertGreaterEqual(len(icc.RELAY_TOKEN), 32)

    def test_public_key_is_pem_public_key(self):
        self.assertIn('BEGIN PUBLIC KEY', icc.RELAY_PUBLIC_KEY_PEM)
        self.assertNotIn('PRIVATE KEY', icc.RELAY_PUBLIC_KEY_PEM)

    def test_public_key_loads_and_encrypts(self):
        """المفتاح العام لازم يكون RSA 2048 صالح"""
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        key = serialization.load_pem_public_key(
            icc.RELAY_PUBLIC_KEY_PEM.encode('utf-8'))
        enc = key.encrypt(b'secret', padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(), label=None))
        self.assertEqual(len(enc), 256)   # 2048 بت

    def test_no_private_key_in_source(self):
        """⚠️ المفتاح الخاص ما ينكتب بالبرنامج أبداً"""
        src = open(icc.__file__, encoding='utf-8').read()
        self.assertNotIn('PRIVATE KEY', src)
        self.assertNotIn('BEGIN RSA PRIVATE', src)


if __name__ == '__main__':
    unittest.main()
