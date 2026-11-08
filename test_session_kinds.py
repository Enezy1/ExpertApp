# -*- coding: utf-8 -*-
"""
test_session_kinds.py — أنواع الجلسات من سجل الحركة (مو من اللون)

المشكلة: نظام الوزارة يعطي «فتح محضر» (150004) و«جلسه محكمه» (150011)
**نفس اللون** `#27659a` — فاللون ما يفرّق بينهم. النتيجة: جلسة المحكمة
ما تنحسب ضمن الجلسات الفعلية → ترقام المحاضر تنقص 1، و«الجلسة القادمة»
بتتخطّى جلسة المحكمة.

الحل: سجل الحركة (ECS_CASE_FLOW) هو المرجع — يكتب اسم النوع بالحرف.
نختم كل جلسة بنوعها (_kind) عند جلبها، و«فتح محضر» ما ينحسب إلا لو
النوع فأكّده سجل الحركة.

  python -W ignore -m unittest test_session_kinds -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import api
import first_session

CASO = 'A2264064'
OPEN_COLOR = '#27659a'      # لون «فتح محضر» — ونفسه جلسة المحكمة بالنظام!


def session(start, color=OPEN_COLOR, title='  ' + CASO, sid='1'):
    """جلسة كما ترجع من load.php."""
    return {'start': start, 'end': start, 'title': title, 'id': sid,
            'backgroundColor': color, 'description': CASO}


def flow_html(rows):
    """يبني HTML سجل حركة من (نوع، تاريخ DD/MM/YYYY، وقت) صفوف."""
    cells = []
    for kind, d, t in rows:
        cells += [kind, d, t, 'لا يوجد', 'لا يوجد', 'محمد عبدالله فرحان العنزى']
    return '<table><tr>' + ''.join('<td>%s</td>' % c for c in cells) + '</tr></table>'


class KindsParsingTests(unittest.TestCase):
    """استخراج الأنواع من سجل الحركة."""

    def test_parses_open_record_and_court(self):
        cells = api._flow_cells(flow_html([
            ('فتح محضر', '18/10/2026', '02:52'),
            ('جلسه محكمه', '20/10/2026', '12:00'),
        ]))
        kinds = api._kinds_from_cells(cells)
        self.assertEqual(kinds.get(('2026/10/18', '02:52')), 'open_record')
        self.assertEqual(kinds.get(('2026/10/20', '12:00')), 'court')

    def test_ignores_other_labels(self):
        cells = api._flow_cells(flow_html([
            ('مباشرة القضية', '15/10/2026', '10:00'),
            ('توزيع للخبراء', '15/10/2026', '10:00'),
        ]))
        self.assertEqual(api._kinds_from_cells(cells), {})

    def test_ignores_rows_without_valid_date_time(self):
        cells = api._flow_cells('<table><tr><td>فتح محضر</td><td>--</td>'
                                '<td>--</td></tr></table>')
        self.assertEqual(api._kinds_from_cells(cells), {})

    def test_court_with_shifted_time_is_captured(self):
        """تعارض ضاع الوقت لـ12:01 — لازم ينقرأ صح."""
        cells = api._flow_cells(flow_html([('جلسه محكمه', '11/10/2026', '12:01')]))
        kinds = api._kinds_from_cells(cells)
        self.assertEqual(kinds.get(('2026/10/11', '12:01')), 'court')


class IsOpenRecordTests(unittest.TestCase):
    """«فتح محضر» vs «جلسة محكمة» — نفس اللون، يفرق بالنوع."""

    def test_court_session_is_counted(self):
        s = session('2026/10/20 12:00')
        s['_kind'] = 'court'
        self.assertFalse(api._is_open_record_session(s))

    def test_open_record_is_not_counted(self):
        s = session('2026/10/18 02:52')
        s['_kind'] = 'open_record'
        self.assertTrue(api._is_open_record_session(s))

    def test_without_kind_falls_back_to_color(self):
        """سجل الحركة تأخر → نرجع للسلوك القديم (اللون)."""
        s = session('2026/10/20 12:00')
        self.assertTrue(api._is_open_record_session(s))

    def test_normal_session_is_counted(self):
        s = session('2026/10/27 09:00', color='#0d95b8')
        self.assertFalse(api._is_open_record_session(s))


class StampTests(unittest.TestCase):
    """ختم الجلسات بنوعها عند الجلب."""

    def test_get_all_case_sessions_stamps_kind(self):
        sess = [session('2026/10/18 02:52'), session('2026/10/20 12:00'),
                session('2026/10/27 09:00', color='#0d95b8')]
        kinds = {('2026/10/18', '02:52'): 'open_record',
                 ('2026/10/20', '12:00'): 'court'}
        with mock.patch.object(api, 'get_sessions', return_value=sess), \
             mock.patch.object(api, 'get_case_session_kinds', return_value=kinds):
            out = api.get_all_case_sessions({}, CASO)
        self.assertEqual(out[0]['_kind'], 'open_record')
        self.assertEqual(out[1]['_kind'], 'court')
        self.assertEqual(out[2].get('_kind', ''), '')

    def test_other_cases_are_filtered_out(self):
        sess = [session('2026/10/20 12:00'),
                dict(session('2026/10/21 12:00'), description='OTHER_CASE')]
        with mock.patch.object(api, 'get_sessions', return_value=sess), \
             mock.patch.object(api, 'get_case_session_kinds', return_value={}):
            out = api.get_all_case_sessions({}, CASO)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['description'], CASO)


class SessionNumberTests(unittest.TestCase):
    """رقم المحضر —(sessioncourt تُحسب)"""

    def _sessions(self):
        return [session('2026/10/18 02:52'),      # فتح محضر
                session('2026/10/20 12:00'),      # جلسة محكمة
                session('2026/10/27 09:00', color='#0d95b8')]

    def _kinds(self):
        return {('2026/10/18', '02:52'): 'open_record',
                ('2026/10/20', '12:00'): 'court'}

    def test_court_session_is_included_in_the_count(self):
        with mock.patch.object(api, 'get_sessions', return_value=self._sessions()), \
             mock.patch.object(api, 'get_case_session_kinds', return_value=self._kinds()):
            num = api.compute_session_number({}, CASO, '2026/10/31')
        # فتح محضر (لا يُحسب) + جلسة محكمة + مناقشة = 2 → الرقم 3
        self.assertEqual(num, 3)

    def test_without_kinds_the_old_behaviour_is_kept(self):
        """سجل الحركة تأخر → السلوك القديم (رقم ناقص) — ما نكسر شي."""
        with mock.patch.object(api, 'get_sessions', return_value=self._sessions()), \
             mock.patch.object(api, 'get_case_session_kinds', return_value={}):
            num = api.compute_session_number({}, CASO, '2026/10/31')
        self.assertEqual(num, 2)


class UpcomingSessionTests(unittest.TestCase):
    """«الجلسة القادمة» — ما تتخطّى جلسة المحكمة، وتعرف نوعها."""

    def _sessions(self):
        return [session('2026/10/18 02:52'),
                session('2026/10/20 12:00'),
                session('2026/10/27 09:00', color='#0d95b8')]

    def _kinds(self):
        return {('2026/10/18', '02:52'): 'open_record',
                ('2026/10/20', '12:00'): 'court'}

    def test_next_session_is_the_court_session(self):
        with mock.patch.object(api, 'get_sessions', return_value=self._sessions()), \
             mock.patch.object(api, 'get_case_session_kinds', return_value=self._kinds()):
            up = first_session.get_upcoming_session({}, CASO, '2026-10-18')
        self.assertIsNotNone(up)
        self.assertEqual(up['date'], '2026/10/20')
        self.assertTrue(up['is_court_session'])

    def test_court_session_detected_at_shifted_time(self):
        """تعارض ضاع الوقت لـ12:01 — لازم تُعرف إنها جلسة محكمة."""
        sess = [session('2026/10/11 12:01')]
        kinds = {('2026/10/11', '12:01'): 'court'}
        with mock.patch.object(api, 'get_sessions', return_value=sess), \
             mock.patch.object(api, 'get_case_session_kinds', return_value=kinds):
            up = first_session.get_upcoming_session({}, CASO, '2026-10-06')
        self.assertIsNotNone(up)
        self.assertEqual(up['time'], '12:01')
        self.assertTrue(up['is_court_session'])

    def test_open_record_is_skipped(self):
        """«فتح محضر» لحاله ما يطلع كـ«جلسة قادمة»."""
        sess = [session('2026/10/18 02:52')]
        kinds = {('2026/10/18', '02:52'): 'open_record'}
        with mock.patch.object(api, 'get_sessions', return_value=sess), \
             mock.patch.object(api, 'get_case_session_kinds', return_value=kinds):
            up = first_session.get_upcoming_session({}, CASO, '2026-10-18')
        self.assertIsNone(up)


class CacheTests(unittest.TestCase):
    """كاش الأنواع — يمنع تكرار الطلب، ويمسح بعد الإضافة."""

    def setUp(self):
        api.invalidate_session_kinds()

    def tearDown(self):
        api.invalidate_session_kinds()

    def test_same_case_is_fetched_once_within_ttl(self):
        calls = []

        def fake_fetch(caso, cookies):
            calls.append(caso)
            return {('2026/10/20', '12:00'): 'court'}

        with mock.patch.object(api, '_fetch_session_kinds', side_effect=fake_fetch):
            api.get_case_session_kinds(CASO, {'a': '1'})
            api.get_case_session_kinds(CASO, {'a': '1'})
            api.get_case_session_kinds(CASO, {'a': '1'})
        self.assertEqual(len(calls), 1)

    def test_different_cookies_are_not_shared(self):
        calls = []

        def fake_fetch(caso, cookies):
            calls.append(caso)
            return {}

        with mock.patch.object(api, '_fetch_session_kinds', side_effect=fake_fetch):
            api.get_case_session_kinds(CASO, {'a': '1'})
            api.get_case_session_kinds(CASO, {'b': '2'})
        self.assertEqual(len(calls), 2)

    def test_insert_invalidates_the_cache(self):
        with mock.patch.object(api, '_fetch_session_kinds', return_value={}):
            api.get_case_session_kinds(CASO, {'a': '1'})
        self.assertTrue(api._KINDS_CACHE)
        with mock.patch.object(api, 'requests') as req:
            req.post.return_value.text = '1'
            api.insert_session({'a': '1'}, CASO, '2026/10/20', '12:00', '150011')
        self.assertFalse(api._KINDS_CACHE)


class NoExtraNetworkTests(unittest.TestCase):
    """parse_case_info يجيب سجل الحركة أصلاً — ما نضيف طلب زيادة."""

    def test_parse_case_info_returns_kinds_without_extra_request(self):
        html = flow_html([('فتح محضر', '18/10/2026', '02:52'),
                          ('جلسه محكمه', '20/10/2026', '12:00')])

        class R:
            def __init__(self, text):
                self.text = text

        def fake_post(url, data=None, cookies=None, verify=None, **kw):
            if 'ECS_CASE_FLOW' in url:
                return R(html)
            return R('<h4>المدعى : مدع</h4>')

        with mock.patch.object(api.requests, 'post', side_effect=fake_post):
            info = api.parse_case_info(CASO, {}, 'الخبير')
        self.assertEqual(info['session_kinds'].get(('2026/10/20', '12:00')), 'court')
        self.assertEqual(info['session_kinds'].get(('2026/10/18', '02:52')), 'open_record')


class RealWorldDataTests(unittest.TestCase):
    """
    بيانات حقيقية ملتقطة من نظام الخبراء (25/10/2026) — تثبت السلوك
    بالبيانات الحقيقية مو بس بالمحاكاة.

    المصدر: load.php (التقويم) + ECS_CASE_FLOW (سجل الحركة) لقضايا
    حقيقية من حساب الخبير. القيم منقولة حرفياً.
    """

    # (التاريخ بالتقويم، اللون، النوع بسجل الحركة)
    REAL = {
        'A2264064': {
            'sessions': [
                ('2026/10/18 02:52', '#27659a', 'open_record'),
                ('2026/10/20 12:00', '#27659a', 'court'),
                ('2026/10/27 09:00', '#0d95b8', ''),
            ],
            'old_number': 2, 'new_number': 3,
            'old_next': '2026/10/27', 'new_next': '2026/10/20',
        },
        'A2263981': {
            'sessions': [
                ('2026/10/05 10:49', '#27659a', 'open_record'),
                ('2026/10/11 12:00', '#27659a', 'court'),
                ('2026/10/18 10:00', '#0d95b8', ''),
                ('2026/10/26 10:00', '#0d95b8', ''),
            ],
            'old_number': 3, 'new_number': 4,
            'old_next': '2026/10/18', 'new_next': '2026/10/11',
        },
        'A2263973': {
            'sessions': [
                ('2026/10/06 01:51', '#27659a', 'open_record'),
                ('2026/10/11 12:01', '#27659a', 'court'),   # وقت مزحزح 12:01
                ('2026/10/18 09:30', '#0d95b8', ''),
                ('2026/10/18 10:30', '#132294', ''),
            ],
            'old_number': 3, 'new_number': 4,
            'old_next': '2026/10/18', 'new_next': '2026/10/11',
        },
    }

    def _run(self, caso, data):
        sess = []
        kinds = {}
        for start, color, kind in data['sessions']:
            s = session(start, color=color)
            s['description'] = caso
            sess.append(s)
            if kind:
                kinds[(start[:10], start[11:16])] = kind
        return sess, kinds

    def test_real_cases_court_session_is_counted(self):
        for caso, data in self.REAL.items():
            sess, kinds = self._run(caso, data)
            with mock.patch.object(api, 'get_sessions', return_value=sess), \
                 mock.patch.object(api, 'get_case_session_kinds', return_value=kinds):
                num = api.compute_session_number({}, caso, '2026/10/31')
            self.assertEqual(num, data['new_number'], '%s: رقم المحضر' % caso)

    def test_real_cases_next_session_is_the_court_one(self):
        for caso, data in self.REAL.items():
            sess, kinds = self._run(caso, data)
            with mock.patch.object(api, 'get_sessions', return_value=sess), \
                 mock.patch.object(api, 'get_case_session_kinds', return_value=kinds):
                up = first_session.get_upcoming_session({}, caso, '2026-10-01')
            self.assertIsNotNone(up, caso)
            self.assertEqual(up['date'], data['new_next'], caso)
            self.assertTrue(up['is_court_session'], caso)

    def test_real_cases_old_behaviour_was_off_by_one(self):
        """باللون بس (السلوك القديم) الرقم كان ناقص 1 — توثيق للرجوع."""
        for caso, data in self.REAL.items():
            sess, _ = self._run(caso, data)
            old_count = len([s for s in sess
                             if (s.get('backgroundColor') or '').lower() != '#27659a'])
            self.assertEqual(old_count + 1, data['old_number'], caso)


if __name__ == '__main__':
    unittest.main(verbosity=2)
