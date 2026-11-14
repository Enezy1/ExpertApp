import unittest
from unittest import mock

import qt_sessions_page as sp


class CourtBadgeTests(unittest.TestCase):
    def test_court_kind_shows_court_badge(self):
        s = {'backgroundColor': '#27659a', '_kind': 'court'}
        self.assertEqual(sp._session_kind(s), 'جلسة محكمة')

    def test_open_record_keeps_colour_badge(self):
        self.assertEqual(sp._session_kind({'backgroundColor': '#27659a'}), 'فتح محضر')

    def test_stamp_uses_flow_kinds_only_for_ambiguous_colour(self):
        sess = [
            {'backgroundColor': '#27659a', 'description': 'A1', 'start': '2026-12-09T12:00:00'},
            {'backgroundColor': '#27659a', 'description': 'A1', 'start': '2026-12-01T10:00:00'},
        ]
        kinds = {('2026-12-09', '12:00'): 'court', ('2026-12-01', '10:00'): 'open_record'}
        with mock.patch('api.get_case_session_kinds', return_value=kinds) as m:
            sp._stamp_ambiguous_kinds(sess, {})
        self.assertEqual(m.call_count, 1)
        self.assertEqual(sess[0]['_kind'], 'court')
        self.assertEqual(sess[1]['_kind'], 'open_record')
        self.assertEqual(sp._session_kind(sess[0]), 'جلسة محكمة')
        self.assertEqual(sp._session_kind(sess[1]), 'فتح محضر')


if __name__ == '__main__':
    unittest.main()
