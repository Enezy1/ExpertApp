"""انحدار 16/11/2026 — بطء ظهور الجلسات + مسح `session_type`.

السبب الجذري (مقاس على النظام الحقيقي):
`load.php` **يتجاهل** نطاق التاريخ ويرجّع كل جلسات الخبير (نحو 2266 سجل
من 2012 لين اليوم) في كل تشغيل. والكتابة كانت **صف‑بصف** — اتصال
SQLite + commit مستقل لكل جلسة — أي ≈13 ثانية قبل ما تظهر أول بطاقة.
وأسوأ: إعادة الكتابة كانت تمسح `session_type` الحقيقي المحفوظ من
`AddSessionDialog` (يكتبه 'فتح محضر'…) لأنها كانت تكتب `session_type=''`.

الحل: `case_db.upsert_sessions_bulk` — دفعة واحدة، اتصال واحد،
transaction واحدة، commit واحد، و**INSERT للجديد فقط**؛ الموجود ما
يتلمس (لا session_type ولا title ولا updated_at).

⚠️ كل الاختبارات على قاعدة مؤقتة — القاعدة الحقيقية ما تتلمس.
"""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import case_db


# نفس بنية جدول sessions بال production (case_db.py:136-142)
SESSIONS_SCHEMA = """
CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caso_no TEXT NOT NULL,
            session_date TEXT NOT NULL,
            session_time TEXT,
            session_type TEXT,
            title TEXT,
            updated_at TEXT,
            UNIQUE(caso_no, session_date, session_time)
        )
"""


class _CountingConn:
    """غلاف يحسب عدد الـcommits على اتصال واحد."""

    def __init__(self, real):
        self._real = real
        self.commits = 0

    def commit(self):
        self.commits += 1
        return self._real.commit()

    def __getattr__(self, name):
        return getattr(self._real, name)


class BulkUpsertTests(unittest.TestCase):

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        conn = sqlite3.connect(self.path)
        conn.execute(SESSIONS_SCHEMA)
        conn.commit()
        conn.close()
        # القاعدة-ready مسبقاً (كما في البرنامج بعد أول استخدام) — عشان
        # الـcommit اللي تعمله تهيئة الجدول ما يتحسب على عملية التخزين
        self._was_ready = case_db._schema_ready
        case_db._schema_ready = True
        self.addCleanup(self._restore)

    def _restore(self):
        case_db._schema_ready = self._was_ready
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _rows(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT caso_no, session_date, session_time, session_type, title, updated_at"
            " FROM sessions ORDER BY caso_no, session_date, session_time")]
        conn.close()
        return rows

    def _insert_raw(self, caso, date, time, stype, title, updated):
        conn = sqlite3.connect(self.path)
        conn.execute(
            "INSERT INTO sessions (caso_no, session_date, session_time,"
            " session_type, title, updated_at) VALUES (?,?,?,?,?,?)",
            (caso, date, time, stype, title, updated))
        conn.commit()
        conn.close()

    # ---------- ١) الجديد يدخل ----------
    def test_new_session_is_inserted(self):
        with mock.patch.object(case_db, 'DB_PATH', self.path):
            n = case_db.upsert_sessions_bulk(
                [('A2263973', '2026-11-20', '10:00', 'شركه الاختبار')])
        self.assertEqual(n, 1)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['caso_no'], 'A2263973')
        self.assertEqual(rows[0]['session_date'], '2026-11-20')
        self.assertEqual(rows[0]['session_time'], '10:00')
        self.assertEqual(rows[0]['title'], 'شركه الاختبار')
        self.assertTrue(rows[0]['updated_at'])

    def test_new_rows_enter_table(self):
        rows_in = [('A1', '2026-11-20', '10:00', 'ع1'),
                   ('A2', '2026-11-21', '11:00', 'ع2'),
                   ('A3', '2026-11-22', '12:00', 'ع3')]
        with mock.patch.object(case_db, 'DB_PATH', self.path):
            case_db.upsert_sessions_bulk(rows_in)
        self.assertEqual(len(self._rows()), 3)

    # ---------- ٢) الموجود ما يتغير ----------
    def test_existing_row_is_untouched(self):
        self._insert_raw('A2263973', '2026-11-20', '10:00', 'فتح محضر',
                         'عنوان قديم', '2026-01-01 00:00:00')
        before = self._rows()
        with mock.patch.object(case_db, 'DB_PATH', self.path):
            case_db.upsert_sessions_bulk(
                [('A2263973', '2026-11-20', '10:00', 'عنوان جديد')])
        after = self._rows()
        self.assertEqual(len(after), 1, 'ما تتكرر الصفوف')
        self.assertEqual(after[0]['session_type'], 'فتح محضر')
        self.assertEqual(after[0]['title'], 'عنوان قديم')
        self.assertEqual(after[0]['updated_at'], '2026-01-01 00:00:00')
        self.assertEqual(before[0]['updated_at'], after[0]['updated_at'])

    def test_manual_session_type_survives_bulk_pass(self):
        """سيناريو المستخدم: أضاف جلسة يدوياً بنوع «فتح محضر» ← شغّل
        تحميل صفحة الجلسات ← لازم النوع يبقى زي ما هو."""
        with mock.patch.object(case_db, 'DB_PATH', self.path):
            case_db.upsert_session('A2263973', '2026/11/20', '10:00',
                                    'فتح محضر', 'شركه الاختبار')
            self.assertEqual(self._rows()[0]['session_type'], 'فتح محضر')
            # الآن simulates صفحة الجلسات — نفس المفتاح قادم من load.php
            case_db.upsert_sessions_bulk(
                [('A2263973', '2026-11-20', '10:00', 'شركه الاختبار')])
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['session_type'], 'فتح محضر',
                         'session_type اتمسح — خطأ')

    def test_empty_value_does_not_overwrite_existing(self):
        self._insert_raw('A1', '2026-11-20', '10:00', 'جلسه محكمه',
                         'عنوان', '2026-01-01 00:00:00')
        with mock.patch.object(case_db, 'DB_PATH', self.path):
            case_db.upsert_sessions_bulk([('A1', '2026-11-20', '10:00', '')])
        row = self._rows()[0]
        self.assertEqual(row['session_type'], 'جلسه محكمه')
        self.assertEqual(row['title'], 'عنوان')

    # ---------- ٣) التطبيع مطابق لـupsert_session ----------
    def test_normalization_matches_upsert_session(self):
        """'a123' + '2026/11/20' لازم يوصل نفس المفتاح — وإلا تكرّرت الصفوف."""
        self._insert_raw('A123', '2026-11-20', '10:00', 'فتح محضر',
                         'ع', '2026-01-01 00:00:00')
        with mock.patch.object(case_db, 'DB_PATH', self.path):
            case_db.upsert_sessions_bulk([(' a123 ', '2026/11/20', '10:00', 'ع')])
        rows = self._rows()
        self.assertEqual(len(rows), 1, 'التطبيع خاطئ — تكرّرت الصف')
        self.assertEqual(rows[0]['session_type'], 'فتح محضر')

    def test_invalid_rows_are_skipped(self):
        with mock.patch.object(case_db, 'DB_PATH', self.path):
            n = case_db.upsert_sessions_bulk([
                ('', '2026-11-20', '10:00', 'بلا رقم'),
                ('A1', '', '10:00', 'بلا تاريخ'),
                ('A2', '2026-11-21', '10:00', 'صالح'),
            ])
        self.assertEqual(n, 1)
        self.assertEqual([r['caso_no'] for r in self._rows()], ['A2'])

    def test_empty_batch_is_noop(self):
        with mock.patch.object(case_db, 'DB_PATH', self.path):
            self.assertEqual(case_db.upsert_sessions_bulk([]), 0)
            self.assertEqual(case_db.upsert_sessions_bulk(None), 0)
        self.assertEqual(self._rows(), [])

    # ---------- ٤) اتصال واحد + commit واحد ----------
    def test_single_connection_and_single_commit(self):
        conns = []
        real_connect = sqlite3.connect

        def counting_connect(*a, **kw):
            proxy = _CountingConn(real_connect(*a, **kw))
            conns.append(proxy)
            return proxy

        rows_in = [('A%d' % i, '2026-11-%02d' % (i % 28 + 1), '10:00', 'ع')
                   for i in range(2266)]
        with mock.patch.object(case_db, 'DB_PATH', self.path), \
                mock.patch('sqlite3.connect', side_effect=counting_connect):
            n = case_db.upsert_sessions_bulk(rows_in)
        self.assertEqual(n, 2266)
        self.assertEqual(len(conns), 1, 'اتصال واحد فقط')
        self.assertEqual(conns[0].commits, 1, 'commit واحد فقط')
        self.assertEqual(len(self._rows()), 2266)

    # ---------- ٥) المسار اليدوي ما يتأثر ----------
    def test_upsert_session_still_updates_when_called_directly(self):
        """upsert_session (مسار AddSessionDialog) ما يتغيّر — لسه يحدّث."""
        with mock.patch.object(case_db, 'DB_PATH', self.path):
            case_db.upsert_session('A1', '2026-11-20', '10:00', 'فتح محضر', 'ع1')
            case_db.upsert_session('A1', '2026-11-20', '10:00', 'جلسه محكمه', 'ع2')
        row = self._rows()[0]
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(row['session_type'], 'جلسه محكمه')
        self.assertEqual(row['title'], 'ع2')

    # ---------- ٦) قارئو الدرج والاحتياطي ما يتأثرون ----------
    def test_get_no_upcoming_cases_still_works(self):
        """درج «قضايا بدون جلسة قادمة» يعتمد على آخر جلسة معروفة."""
        with mock.patch.object(case_db, 'DB_PATH', self.path):
            case_db.upsert_session('A1', '2026-01-10', '10:00', 'فتح محضر', 'ع1')
            case_db.upsert_session('A2', '2099-01-10', '10:00', '', 'ع2')
            conn = sqlite3.connect(self.path)
            conn.execute("CREATE TABLE cases (caso_no TEXT PRIMARY KEY, expert_name TEXT,"
                         " status TEXT)")
            conn.executemany("INSERT INTO cases VALUES (?,?,?)",
                             [('A1', 'خبير', 'متداولة'), ('A2', 'خبير', 'متداولة')])
            conn.commit()
            conn.close()
            out = case_db.get_no_upcoming_cases('خبير')
        self.assertEqual([r['caso_no'] for r in out], ['A1'])
        self.assertEqual(out[0]['session_date'], '2026-01-10')
        self.assertEqual(out[0]['session_type'], 'فتح محضر')

    def test_get_case_sessions_still_works(self):
        """الاحتياطي المحلي في «تتبّع القضية» يعتمد على get_case_sessions."""
        with mock.patch.object(case_db, 'DB_PATH', self.path):
            case_db.upsert_session('A1', '2026-11-20', '10:00', 'فتح محضر', 'ع1')
            case_db.upsert_session('A1', '2026-11-25', '11:00', '', 'ع1')
            out = case_db.get_case_sessions('A1')
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]['session_date'], '2026-11-20')
        self.assertEqual(out[0]['session_type'], 'فتح محضر')
        self.assertEqual(out[1]['session_date'], '2026-11-25')


class SessionsPageBulkTests(unittest.TestCase):
    """`_record_sessions_locally` لازم ينادي الدالة الجماعية مرة واحدة."""

    def test_record_uses_bulk_once(self):
        import qt_sessions_page as sp
        sessions = [
            {'description': 'A1', 'start': '2026-11-20 10:00', 'title': '  A1'},
            {'description': 'A2', 'start': '2026/11/21 11:00', 'title': '  A2'},
            {'description': '', 'start': '2026-11-22 12:00', 'title': ''},
        ]
        with mock.patch.object(case_db, 'upsert_sessions_bulk') as m:
            sp.SessionsPage._record_sessions_locally(None, sessions)
        self.assertEqual(m.call_count, 1, 'لازم استدعاء واحد')
        rows = m.call_args[0][0]
        self.assertEqual(len(rows), 2, 'الصف الفارغ ينتخطى')
        self.assertEqual(rows[0][0], 'A1')
        self.assertEqual(rows[0][1], '2026-11-20')
        self.assertEqual(rows[0][2], '10:00')
        self.assertEqual(rows[1][1], '2026/11/21')
        self.assertEqual(rows[1][2], '11:00')

    def test_record_does_not_use_per_row_upsert(self):
        """المسار القديم (اتصال+commit لكل صف) ما يرجع."""
        import qt_sessions_page as sp
        sessions = [{'description': 'A%d' % i, 'start': '2026-11-20 10:00',
                     'title': ''} for i in range(50)]
        with mock.patch.object(case_db, 'upsert_session') as old, \
                mock.patch.object(case_db, 'upsert_sessions_bulk') as new:
            sp.SessionsPage._record_sessions_locally(None, sessions)
        self.assertEqual(old.call_count, 0, 'لسه يستخدم المسار الصف‑بصف')
        self.assertEqual(new.call_count, 1)


if __name__ == '__main__':
    unittest.main()
