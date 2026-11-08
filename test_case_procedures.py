# اختبارات الإجراءات (2ط، أُعيدت 2026-10-17 — الخطوة تلقائية): python -W ignore -m unittest test_case_procedures -v
# المحاضر تُؤخذ وحدها من مكان الحفظ، والحضور يُستخرج آلياً (حضور في محضر واحد يكفي)، والنص من قالب تقرير النموذج،
# و«منتهية» فقط بالأربعة: الاستلام + الحجز + الحضور مستخرج + عدد المحاضر = عدد الجلسات.
import json
import os
import tempfile
import unittest
import zipfile

import case_model as cm
import case_procedures as cp
import case_workspace as cw

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)

TODAY = '2026-10-10'
# مباشرة ضمنية (فتح محضر) + جلستان فعليتان منعقدتان + جلسة مستقبلية ⇒ المتوقع 3 محاضر
SESSIONS = [
    {'date': '2026-09-01', 'open_record': True},
    {'date': '2026-09-15', 'open_record': False},
    {'date': '2026-10-05', 'open_record': False},
    {'date': '2026-12-01', 'open_record': False},
]
FLOW = {'sessions': [], 'received': '2026-08-20', 'booked': '2026-10-05'}
PLAINTIFF = 'شركة بدر سلطان واخوانه (ذ.م.م)'
DEFS = ['شركة الدار للهندسة والانشاءات', 'وكيل وزارة الاشغال العامة بصفته']
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
JUDGMENT = {'judgment_date': '07/06/2026'}


def write_minute(path, attend='', header=True, plaintiff=PLAINTIFF, defs=DEFS, date=''):
    """محضر docx مبسَّط: (تاريخ) + ترويسة الأطراف + قسم الحضور."""
    paras = [f'التاريخ: {date}'] if date else []
    if header:
        paras += ['المرفوعة من', plaintiff, 'المرفوعة ضد', '\n'.join(f'{i}- {d}' for i, d in enumerate(defs, 1)),
                  'بحضور الخبير', 'محمد المطوع']
    paras += [f'وقد حضر في الموعد المحدد كل من: {attend}'.rstrip(), 'وبوشرت المهمة المطلوبة كما يلي: ...']
    body = ''.join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paras)
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W[1:-1]}"><w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', xml)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, 'محاضر')
        self.base, self.data = cw.ensure_workspace(CASE, os.path.join(self._tmp.name, 'ws'))
        self.fetch = lambda: SESSIONS
        self.flow = lambda: dict(FLOW)

    def tearDown(self):
        self._tmp.cleanup()

    def minute(self, name, attend=None, root=None, **kw):
        d = cp.minutes_dir(CASE['caso_no'], root or self.root)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        if attend is None:
            open(p, 'wb').close()
        else:
            write_minute(p, attend, **kw)
        return p

    def run_it(self, **kw):
        kw.setdefault('flow', self.flow)
        kw.setdefault('get_case', lambda c: JUDGMENT)
        return cp.run_procedures(self.base, self.data, self.fetch, root=self.root, today=TODAY, **kw)

    def disk(self):
        return cw.read_case_json(self.base)

    def msg(self):
        return self.disk()['steps']['procedures']['message']

    def check(self, key):
        return next(c for c in cp.build_checks(self.data) if c['key'] == key)


class SummaryTests(unittest.TestCase):
    def test_expected_counts_future_and_open_record_excluded(self):
        s = cp.summarize_sessions(SESSIONS, TODAY)
        self.assertEqual((s['count_system'], s['real_held'], s['expected_minutes'], s['future']), (4, 2, 3, 1))
        self.assertEqual(s['dates'], {1: '2026-09-01', 2: '2026-09-15', 3: '2026-10-05'})

    def test_no_sessions_means_one_minute(self):
        self.assertEqual(cp.summarize_sessions([], TODAY)['expected_minutes'], 1)

    def test_count_words(self):
        self.assertEqual([cp.count_word(n) for n in (1, 2, 8, 20)], ['محضر واحد', 'محضرين', '8 محاضر', '20 محضراً'])


class FindTests(Base):
    """إرفاق تلقائي من مجلد المحاضر بلا نافذة: كل الأنواع، والإخطار والمؤقت لا يُحسبان."""

    def test_takes_all_types_from_case_folder(self):
        for n in ('1.docx', '2.pdf', '3.png', 'محضر 4.md', 'اخطار_حكومة.docx', 'إخطار.pdf', '~$1.docx', 'x.docx',
                  'ملاحظات.xlsx'):
            self.minute(n)
        names = [m['name'] for m in cp.find_minutes(CASE['caso_no'], self.root)]
        self.assertEqual(names, ['1.docx', '2.pdf', '3.png', 'محضر 4.md'])
        self.assertEqual([m['no'] for m in cp.find_minutes(CASE['caso_no'], self.root)], [1, 2, 3, 4])

    def test_files_named_with_case_number_anywhere_in_root(self):
        os.makedirs(self.root)
        open(os.path.join(self.root, f"{CASE['caso_no']} محضر الجلسة.pdf"), 'wb').close()
        open(os.path.join(self.root, 'A0000000.docx'), 'wb').close()           # قضية أخرى
        other = os.path.join(self.root, f"محاضر {CASE['caso_no']} القديمة")
        os.makedirs(other)
        open(os.path.join(other, 'ج1.docx'), 'wb').close()
        names = sorted(m['name'] for m in cp.find_minutes(CASE['caso_no'], self.root))
        self.assertEqual(names, sorted([f"{CASE['caso_no']} محضر الجلسة.pdf", 'ج1.docx']))

    def test_same_number_docx_and_pdf_is_one_minute(self):
        self.minute('3.pdf')
        self.minute('3.docx')
        found = cp.find_minutes(CASE['caso_no'], self.root)
        self.assertEqual([(m['no'], m['name']) for m in found], [(3, '3.docx')])

    def test_missing_folder_not_created(self):
        self.assertEqual(cp.find_minutes(CASE['caso_no'], self.root), [])
        self.assertFalse(os.path.exists(self.root))

    def test_scan_minutes_numbered_only(self):
        for n in ('1.docx', '2.pdf', 'اخطار_حكومة.docx', '~$3.docx', 'x.docx'):
            self.minute(n)
        self.assertEqual(sorted(cp.scan_minutes(CASE['caso_no'], self.root)), [1, 2])

    def test_run_takes_minutes_without_asking(self):
        self.minute('1.docx', 'لم يحضر أحد.')
        self.minute('2.docx', 'لم يحضر أحد.')
        self.run_it()
        self.assertEqual(len(self.disk()['sessions']['minutes']), 2)
        self.assertIn('تم الاطلاع على محضرين', self.msg())


class CountTests(Base):
    """عدد المحاضر مقابل جلسات النظام."""

    def test_equal_counts_line(self):
        for n in (1, 2, 3):
            self.minute(f'{n}.docx', 'لم يحضر أحد.')
        self.run_it()
        self.assertEqual(self.check('compare'),
                         {'key': 'compare', 'ok': True, 'text': 'في النظام 3 جلسات (+1 قادمة)، تم الاطلاع على 3 محاضر'})

    def test_missing_minutes_with_session_dates(self):
        self.minute('1.docx', 'لم يحضر أحد.')
        self.minute('3.docx', 'لم يحضر أحد.')
        self.assertEqual(self.run_it(), 'reviewed')           # النقص ملاحظة لا يحجب (2026-10-19)
        c = self.check('compare')
        self.assertIsNone(c['ok'])
        self.assertIn('المتبقي: الجلسة رقم (2)', c['text'])
        self.assertEqual(self.disk()['sessions']['missing'], [2])

    def test_unnumbered_minute_matched_by_its_date(self):
        self.minute('1.docx', 'لم يحضر أحد.')
        self.minute('محضر الجلسة الثانية.docx', 'لم يحضر أحد.', date='15/09/2026')
        self.run_it()
        self.assertEqual(self.disk()['sessions']['missing'], [3])
        self.assertIn('الجلسة رقم (3)', self.check('compare')['text'])

    def test_empty_sessions_everywhere_is_not_success(self):
        self.minute('1.docx', 'لم يحضر أحد.')
        self.fetch = lambda: []
        self.run_it(flow=lambda: {})
        self.assertIn('تعذّر التحقق', self.check('compare')['text'])

    def test_live_failure_uses_fallback_then_stored(self):
        def boom():
            raise RuntimeError('لا اتصال')
        self.minute('1.docx', 'لم يحضر أحد.')
        cp.run_procedures(self.base, self.data, boom, fallbacks=(lambda: SESSIONS,), root=self.root,
                          today=TODAY, flow=self.flow, get_case=lambda c: {})
        self.assertEqual(self.data['sessions']['source'], 'local')
        cp.run_procedures(self.base, self.data, boom, root=self.root, today=TODAY, force=True, get_case=lambda c: {})
        self.assertEqual(self.data['sessions']['source'], 'stored')
        self.assertIn('من آخر جلب محفوظ', self.check('compare')['text'])

    def test_no_stored_and_all_fail_reports_reason(self):
        def boom():
            raise RuntimeError('لا اتصال')
        self.assertEqual(cp.run_procedures(self.base, self.data, boom, root=self.root, get_case=lambda c: {}),
                         'needs_input')
        self.assertIn('لا اتصال', self.msg())


class RulesTests(unittest.TestCase):
    def test_party_present_by_name_tokens(self):
        self.assertTrue(cp.party_present('وكيل وزارة الاشغال العامة بصفته', 'حضر ممثل وزارة الأشغال العامة'))
        self.assertFalse(cp.party_present('وكيل وزارة الداخلية بصفته', 'حضر ممثل وزارة الأشغال العامة'))

    def test_header_parties_split_numbered_defendants(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, '1.docx')
            write_minute(p)
            pl, defs = cp.minute_parties(cp.read_minute_paragraphs(p))
        self.assertEqual(pl, PLAINTIFF)
        self.assertEqual(defs, DEFS)

    def test_attendance_variants(self):
        parties = [PLAINTIFF] + DEFS
        with tempfile.TemporaryDirectory() as t:
            def res(attend):
                p = os.path.join(t, 'm.docx')
                write_minute(p, attend)
                return cp.rules_attendance(cp.read_minute_paragraphs(p), parties)
            self.assertEqual(res('لم يحضر أحد.'), [])
            self.assertEqual(res(''), [])
            self.assertEqual(res('حضر الطرفان'), [0, 1, 2])
            self.assertEqual(res('ممثل شركة بدر سلطان واخوانه وممثل وزارة الاشغال العامة'), [0, 2])

    def test_no_attendance_section_is_none(self):
        self.assertIsNone(cp.rules_attendance(['نص آخر'], ['أ']))

    def test_ai_json_parsing_and_failure(self):
        self.assertEqual(cp.ai_attendance('نص', ['أ', 'ب', 'ج'], lambda p: 'الرد: {"present":[1,3]}'), [0, 2])
        self.assertEqual(cp.ai_attendance('نص', ['أ'], lambda p: '{"present":[5]}'), [])
        self.assertIsNone(cp.ai_attendance('نص', ['أ'], lambda p: 'ليس json'))

        def boom(p):
            raise RuntimeError('x')
        self.assertIsNone(cp.ai_attendance('نص', ['أ'], boom))

    def test_minute_date(self):
        self.assertEqual(cp.minute_date(['محضر', 'التاريخ: ١٥/٠٩/٢٠٢٦']), '2026-09-15')
        self.assertEqual(cp.minute_date(['بلا تاريخ']), '')

    def test_md_and_txt_minutes_are_read(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, '1.md')
            with open(p, 'w', encoding='utf-8') as f:
                f.write('المرفوعة من\nأ\nوقد حضر في الموعد المحدد كل من: أ\nوبوشرت')
            self.assertEqual(cp.attendance_segment(cp.read_minute_text(p)), 'أ')


class FlowTests(unittest.TestCase):
    def test_parse_flow_actions(self):
        acts = [
            {'date': '01/08/2026', 'action': 'توزيع للخبراء', 'to_name': 'محمد عبدالله المطوع'},
            {'date': '20/08/2026', 'action': 'توزيع للخبراء', 'to_name': 'خبير آخر تماما'},
            {'date': '05/09/2026', 'time': '10:00', 'action': 'جلسة «فتح محضر»'},
            {'date': '05/10/2026', 'time': '09:00', 'action': 'جلسة «حجز للتقرير»'},
        ]
        r = cp.parse_flow_actions(acts, 'محمد المطوع')
        self.assertEqual((r['received'], r['booked']), ('2026-08-01', '2026-10-05'))
        self.assertEqual([s['open_record'] for s in r['sessions']], [True, False])
        self.assertEqual(cp.parse_flow_actions(acts)['received'], '2026-08-20')

    def test_merge_sessions_dedupes_by_date_and_time(self):
        cal = [{'date': '2026-09-15', 'time': '10:00'}]
        flow = [{'date': '2026-09-15', 'time': '10:00'}, {'date': '2026-10-05', 'time': '09:00'}]
        self.assertEqual(len(cp.merge_sessions(cal, flow)), 2)


class AttendanceTests(Base):
    """الحضور: حضر / لم يحضر رغم صحة إعلانه / حضوره في محضر واحد يكفي — بلا خطوة تأكيد."""
    ZAIN, PERSON = 'شركة زين للاتصالات', 'حسام محمد النعمه'

    def two_party(self, attends):
        for i, a in enumerate(attends, 1):
            self.minute(f'{i}.docx', a, plaintiff=self.ZAIN, defs=[self.PERSON])

    def result(self):
        return [(r['present'], r['certain']) for r in self.data['procedures']['attendance']['result']]

    def test_present_in_one_minute_is_enough(self):
        self.two_party(['لم يحضر أحد.', f'ممثل {self.ZAIN} و{self.PERSON}', 'لم يحضر أحد.'])
        self.assertEqual(self.run_it(), 'reviewed')                        # اكتملت ← معتمدة تلقائياً
        self.assertEqual(self.result(), [(True, True), (True, True)])
        t = self.data['procedures']['text']                               # حضرا في محضر واحد ← يُكتبان حاضرين: «حضرتها …»
        self.assertIn('وحددنا عدة جلسات حضرتها الشركة المدعية والمدعى عليه،', t)
        self.assertNotIn('منها', t)

    def test_absent_everywhere_written_as_not_attended_despite_notice(self):
        self.two_party(['لم يحضر أحد.', f'ممثل {self.ZAIN}', f'ممثل {self.ZAIN}'])
        calls = []

        def ask(prompt):
            calls.append(prompt)
            return '{"present":[1]}'
        self.assertEqual(self.run_it(ask=ask), 'reviewed')
        att_calls = lambda: [c for c in calls if 'المحاضر:' not in c]       # noqa: E731 (طلب الجلسات منفصل)
        self.assertEqual(len(att_calls()), 1)                               # طلب واحد لكل نصوص الحضور
        t = self.data['procedures']['text']
        self.assertIn('وحددنا عدة جلسات حضرتها الشركة المدعية وتخلف المدعى عليه عن الحضور،', t)
        self.assertNotIn('رغم صحة إعلانه', t)                                # الإعلان لم يرد في المحاضر ← لا يُكتب
        n = len(calls)
        self.run_it(ask=ask, force=True)
        self.assertEqual(len(calls), n)                                     # لا يكرّر أي طلب لنصوص لم تتغيّر

    def test_without_ai_absence_is_not_guessed(self):
        self.two_party(['لم يحضر أحد.', f'ممثل {self.ZAIN}', 'لم يحضر أحد.'])
        self.run_it()
        self.assertEqual(self.result(), [(True, True), (False, False)])
        self.assertIn(cp.TODO, self.data['procedures']['text'])
        self.assertIn('لم يتأكد', self.check('attendance')['text'])

    def test_plaintiff_absence_is_never_written_automatically(self):
        self.two_party(['لم يحضر أحد.', 'لم يحضر أحد.', ''])
        self.assertEqual(self.run_it(), 'reviewed')               # يُكتب مما في المحاضر (2026-10-19)
        t = self.data['procedures']['text']
        self.assertIn('تخلفت الشركة المدعية', t)
        self.assertNotIn('وتم مناقشة أطراف الدعوى', t)            # لم يثبت حضور أحد

    def test_blank_attendance_box_is_not_absence(self):
        self.two_party(['', '', ''])
        self.run_it()
        self.assertEqual(self.result(), [(False, False), (False, False)])
        self.assertNotIn('تخلف', self.data['procedures']['text'])

    def test_discussed_only_when_written_in_minutes_and_for_who_attended(self):
        self.two_party(['لم يحضر أحد.', f'ممثل {self.ZAIN}', 'لم يحضر أحد.'])
        self.run_it(ask=lambda p: '{"present":[1]}')
        self.assertNotIn('مناقشة', self.data['procedures']['text'])           # حضور وحده لا يثبت المناقشة
        self.two_party(['لم يحضر أحد.', f'ممثل {self.ZAIN} وتمت مناقشة الحاضر', 'لم يحضر أحد.'])
        self.run_it(ask=lambda p: '{"present":[1]}', force=True)
        t = self.data['procedures']['text']
        self.assertIn('وتمت مناقشة الحاضر عن الشركة المدعية', t)                # متخلف ← لا «تم مناقشة أطراف الدعوى»
        self.assertNotIn('تم مناقشة أطراف الدعوى', t)

    def test_notice_written_only_when_in_minutes(self):
        self.two_party(['لم يحضر أحد.', f'ممثل {self.ZAIN}', 'ولم يحضر أحد عن المدعى عليه على الرغم من صحة إعلانه'])
        self.run_it(ask=lambda p: '{"present":[1]}')
        self.assertIn('وتخلف المدعى عليه عن الحضور رغم صحة إعلانه', self.data['procedures']['text'])

    def test_all_present_and_discussed_uses_parties_phrase(self):
        self.two_party([f'ممثل {self.ZAIN} و{self.PERSON} وتمت مناقشة الأطراف'] * 3)
        self.run_it()
        t = self.data['procedures']['text']
        self.assertIn('وحددنا عدة جلسات حضرتها الشركة المدعية والمدعى عليه', t)
        self.assertIn('وتم مناقشة أطراف الدعوى', t)

    def test_incomplete_minutes_give_neutral_phrase_without_ruling(self):
        self.minute('1.docx', f'ممثل {self.ZAIN}', plaintiff=self.ZAIN, defs=[self.PERSON])       # 3 متوقعة، محضر واحد
        self.run_it()
        t = self.data['procedures']['text']
        self.assertNotIn('[ناقص: الحضور', t)                       # يُكتب مما توفّر؛ النقص ملاحظة فقط

    def test_expert_override_then_auto_again(self):
        self.two_party(['لم يحضر أحد.', f'ممثل {self.ZAIN}', 'لم يحضر أحد.'])
        self.run_it()
        self.assertEqual(cp.set_attendance(self.base, self.data, 1, False), 'reviewed')
        self.assertIn('بتعديل الخبير', self.check('attendance')['text'])
        cp.set_attendance(self.base, self.data, 1, None)

    def test_no_attendance_section_needs_input(self):
        d = cp.minutes_dir(CASE['caso_no'], self.root)
        os.makedirs(d)
        with open(os.path.join(d, '1.md'), 'w', encoding='utf-8') as f:
            f.write('محضر بلا قسم حضور')
        self.run_it()
        self.assertFalse(self.check('attendance')['ok'])


class StateTests(Base):
    """الحالة الصادقة: «منتهية» فقط بالأربعة، وإلا needs_input بسطر يذكر الناقص."""
    FULL = f'{PLAINTIFF} و{DEFS[0]} و{DEFS[1]}'

    def full(self):
        for n in (1, 2, 3):
            self.minute(f'{n}.docx', self.FULL if n == 2 else 'لم يحضر أحد.')

    def test_all_four_gives_reviewed_automatically(self):
        self.full()
        self.assertEqual(self.run_it(), 'reviewed')
        self.assertTrue(self.disk()['steps']['procedures'].get('auto'))
        self.assertIn('اعتُمدت تلقائياً', self.msg())

    def test_missing_booking_date(self):
        self.full()
        self.run_it(flow=lambda: {'sessions': [], 'received': '2026-08-20', 'booked': ''})
        self.assertIn('تاريخ الحجز: لم يُعثر', self.check('booked')['text'])

    def test_missing_received_date(self):
        self.full()
        self.data['case']['received_date'] = ''
        self.run_it(flow=lambda: {'sessions': [], 'received': '', 'booked': '2026-10-05'})
        self.assertIn('تاريخ الاستلام: غير متوفر', self.check('received')['text'])

    def test_missing_minute_is_only_a_note(self):
        self.minute('1.docx', self.FULL)
        self.minute('2.docx', 'لم يحضر أحد.')
        self.assertEqual(self.run_it(), 'reviewed')
        self.assertIn('المتبقي: الجلسة رقم', self.check('compare')['text'])

    def test_booking_session_in_calendar_counts(self):
        self.full()
        self.fetch = lambda: SESSIONS + [{'date': '2026-10-06', 'open_record': False, 'booking': True}]
        self.run_it(flow=lambda: {'sessions': [], 'received': '', 'booked': ''})
        self.assertEqual(self.data['procedures']['booked']['date'], '2026-10-06')

    def test_received_comes_from_case_then_flow(self):
        self.full()
        self.run_it()
        self.assertEqual(self.data['procedures']['received']['date'], CASE['received_date'])
        self.data['case']['received_date'] = ''
        self.run_it(force=True)
        self.assertEqual(self.data['procedures']['received']['date'], '2026-08-20')

    def test_done_not_rerun_without_force(self):
        self.full()
        self.run_it()
        self.fetch = lambda: (_ for _ in ()).throw(RuntimeError('لا يجب الاستدعاء'))
        self.assertEqual(self.run_it(), 'reviewed')

    def test_rerun_without_change_does_not_mark_next_steps_stale(self):
        self.full()
        self.run_it()
        self.data['steps']['research'].update(state='done', stale=False)
        self.run_it(force=True)
        self.assertFalse(self.data['steps']['research'].get('stale'))

    def test_edit_after_approval_keeps_approval_and_flags_research(self):
        self.full()
        self.run_it()
        self.data['steps']['research'].update(state='done', stale=False)
        self.assertEqual(cp.set_procedures_text(self.base, self.data, 'نص عدّله الخبير'), 'reviewed')
        self.assertTrue(self.data['steps']['research']['stale'])
        self.run_it(force=True)
        self.assertEqual(self.disk()['procedures']['text'], 'نص عدّله الخبير')    # التحديث الآلي لا يمسح تعديله

    def test_attachments_do_not_depend_on_procedures(self):
        self.assertEqual(cm.unmet(self.data, 'attachments'), [])


class TemplateTests(Base):
    """صيغة الإجراءات من تقرير النموذج H2212338 حرفياً مع الفراغات المتغيرة."""

    def test_full_text(self):
        for i, a in enumerate(['لم يحضر أحد.', 'ممثل شركة زين للاتصالات', 'لم يحضر أحد.'], 1):
            self.minute(f'{i}.docx', a, plaintiff='شركة زين للاتصالات', defs=['حسام محمد النعمه'])
        self.run_it(ask=lambda p: '{"present":[1]}')
        self.assertEqual(self.data['procedures']['text'],
                         'استلمنا ملف الدعوى بتاريخ 01/10/2026، وذلك لتنفيذ المأمورية السابق بيانها والواردة في '
                         'الحكم التمهيدي الصادر بجلسة 07/06/2026، وحددنا عدة جلسات حضرتها الشركة المدعية '
                         'وتخلف المدعى عليه عن الحضور، واطلعنا على ما به من أوراق ومستندات، وتم حجز الدعوى للتقرير '
                         'بتاريخ 05/10/2026.')

    def test_full_text_with_notice_and_discussion_proven(self):
        for i, a in enumerate(['لم يحضر أحد.', 'ممثل شركة زين للاتصالات وتمت مناقشة الحاضر',
                               'ولم يحضر أحد عن المدعى عليه على الرغم من صحة إعلانه'], 1):
            self.minute(f'{i}.docx', a, plaintiff='شركة زين للاتصالات', defs=['حسام محمد النعمه'])
        self.run_it(ask=lambda p: '{"present":[1]}')
        t = self.data['procedures']['text']
        self.assertIn('وحددنا عدة جلسات حضرتها الشركة المدعية وتخلف المدعى عليه عن الحضور رغم صحة إعلانه، '
                      'واطلعنا على ما به من أوراق ومستندات، وتمت مناقشة الحاضر عن الشركة المدعية، وتم حجز', t)

    def test_unknown_values_are_todo(self):
        self.minute('1.docx', 'لم يحضر أحد.')
        self.data['case']['received_date'] = ''
        self.run_it(get_case=lambda c: {}, flow=lambda: {'sessions': [], 'received': '', 'booked': ''})
        t = self.data['procedures']['text']
        self.assertEqual(t.count(cp.TODO), 3)                     # الاستلام والحكم والحجز
        self.assertTrue(t.startswith('استلمنا ملف الدعوى بتاريخ [يُكتب]، وذلك لتنفيذ المأمورية'))

    def test_multiple_defendants_labels(self):
        res = [{'name': 'شركة زين', 'role': 'plaintiff', 'present': True, 'certain': True},
               {'name': 'س', 'role': 'defendant', 'present': False, 'certain': True},
               {'name': 'ص', 'role': 'defendant', 'present': False, 'certain': True}]
        self.assertEqual(cp.attendance_clause(res, notified={'defendant': True}), 'حضرتها الشركة المدعية وتخلف المدعى عليه الأول والمدعى عليه '
                                                    'الثاني عن الحضور رغم صحة إعلانهما')


class UnifiedGateTests(Base):
    """مسار كتابة واحد (case_procedures.compose) ببوابة الاكتمال: النقص ← «عدة جلسات» بلا حضور/تخلف/مناقشة، وملاحظة «ينقص محضر N»،
    وإعادة الكتابة تلقائياً مع محضر جديد ما لم يعدّل الخبير النص."""
    ZAIN, PERSON = 'شركة زين للاتصالات', 'حسام محمد النعمه'

    def one(self, i, attend):
        self.minute(f'{i}.docx', attend, plaintiff=self.ZAIN, defs=[self.PERSON])

    def test_missing_minutes_gate_text_and_note(self):
        self.one(1, f'ممثل {self.ZAIN} وتمت مناقشة الحاضر، ولم يحضر أحد عن المدعى عليه على الرغم من صحة إعلانه')
        self.assertEqual(self.run_it(), 'reviewed')                  # يُكتب مما توفّر ويُعتمد؛ النقص ملاحظة
        t = self.data['procedures']['text']
        self.assertIn('وحددنا عدة جلسات،', t)
        for banned in ('تخلف', 'مناقشة', 'رغم صحة', 'حضر', '(1)', 'جلستين'):
            self.assertNotIn(banned, t.replace('الحكم التمهيدي', ''), banned)
        self.assertEqual(self.data['procedures']['gate_note'], 'ينقص المحاضر 2، 3')
        self.assertIn('ينقص المحاضر 2، 3', self.msg())

    def test_only_receiving_minute_missing_keeps_attendance_but_not_count(self):
        data = {'sessions': {'minutes': [{'no': 2}, {'no': 3}], 'missing_count': 1, 'missing': [1]},
                'procedures': {'received': {'date': '2026-10-01'}, 'booked': {'date': '2026-10-05'},
                               'judgment': {'date': '07/06/2026'}, 'evidence': {'notified': True, 'discussed': True},
                               'attendance': {'candidates': [{'present': [0]}, {'present': [0]}],
                                              'result': [{'present': True, 'certain': True, 'role': 'plaintiff',
                                                          'name': 'شركة زين'},
                                                         {'present': False, 'certain': True, 'role': 'defendant',
                                                          'name': 'س'}]}}}
        t, notes = cp.compose(data)
        self.assertIn('وحددنا عدة جلسات حضرتها الشركة المدعية وتخلف المدعى عليه عن الحضور رغم صحة إعلانه', t)
        self.assertIn('وتمت مناقشة الحاضر عن الشركة المدعية', t)
        self.assertEqual(notes, ['ينقص محضر 1'])

    def test_note_wording_for_one_missing_minute(self):
        g = cp.minutes_gate({'sessions': {'missing_count': 1, 'missing': [2]}})
        self.assertEqual((g['complete'], g['attendance_ok'], g['note']), (False, False, 'ينقص محضر 2'))
        self.assertTrue(cp.minutes_gate({'sessions': {}})['complete'])
        g = cp.minutes_gate({'sessions': {'missing_count': 1, 'missing': [2]},
                             'procedures': {'attendance': {'overrides': {'1': False}}}})
        self.assertEqual((g['complete'], g['attendance_ok']), (False, True))       # تأكيد الخبير بنفسه يُكتب رغم النقص
        self.assertEqual(cp.minutes_gate({'sessions': {'missing_count': 2}})['note'], 'ينقص محضرين')

    def test_new_minutes_rewrite_automatically_unless_edited(self):
        self.one(1, 'لم يحضر أحد.')
        self.run_it()
        self.assertIn('عدة جلسات', self.data['procedures']['text'])
        self.one(2, f'ممثل {self.ZAIN}')
        self.one(3, f'ممثل {self.ZAIN}')
        self.run_it(force=True, ask=lambda p: '{"present":[1]}')
        t = self.data['procedures']['text']
        self.assertIn('وحددنا عدة جلسات حضرتها الشركة المدعية', t)   # اكتملت المحاضر ← الحضور يظهر، والعدد لا يُكتب أبداً
        self.assertNotRegex(t, r'جلستين|عدد \(\d+\) جلس')
        cp.set_procedures_text(self.base, self.data, 'نص عدّله الخبير')
        self.minute('4.docx', f'ممثل {self.ZAIN}', plaintiff=self.ZAIN, defs=[self.PERSON])
        self.run_it(force=True, ask=lambda p: '{"present":[1]}')
        self.assertEqual(self.data['procedures']['text'], 'نص عدّله الخبير')       # تعديل الخبير لا يُمسّ

    def test_single_path_report_and_step_share_one_composer(self):
        import case_facts
        import report_compose
        self.assertFalse(hasattr(case_facts, '_NOTIFIED'))
        for dead in ('minutes_complete', 'incomplete_reason', 'proven_present'):
            self.assertFalse(hasattr(cp, dead), dead)
        import inspect
        self.assertIn('cp.compose(', inspect.getsource(report_compose.procedures_text))
        self.assertIn('proven_facts', inspect.getsource(case_facts.minutes_facts))
        self.one(1, 'لم يحضر أحد.')
        self.run_it()
        self.assertEqual(self.data['procedures']['text'], cp.compose_text(self.data))


class AddExcludeTests(Base):
    def test_add_any_type_copies_into_case_workspace(self):
        self.minute('1.docx', 'لم يحضر أحد.')
        self.run_it()
        src = os.path.join(self._tmp.name, 'محضر مصوّر.md')
        with open(src, 'w', encoding='utf-8') as f:
            f.write('محضر')
        cp.add_minute(self.base, self.data, src, root=self.root)
        self.assertTrue(os.path.exists(os.path.join(self.base, cp.EXTRA_DIR, 'محضر الخبرة - محضر مصوّر.md')))
        self.assertEqual(len(self.disk()['sessions']['minutes']), 2)
        self.assertFalse(os.path.exists(os.path.join(cp.minutes_dir(CASE['caso_no'], self.root), 'محضر مصوّر.md')))

    def test_add_refuses_bad_type_and_missing_file(self):
        src = os.path.join(self._tmp.name, 'a.exe')
        open(src, 'wb').close()
        with self.assertRaises(cm.StepError):
            cp.add_minute(self.base, self.data, src, root=self.root)
        with self.assertRaises(cm.StepError):
            cp.add_minute(self.base, self.data, os.path.join(self._tmp.name, 'none.docx'), root=self.root)

    def test_exclude_wrong_file(self):
        self.minute('1.docx', 'لم يحضر أحد.')
        p = self.minute('2.docx', 'لم يحضر أحد.')
        self.run_it()
        cp.exclude_minute(self.base, self.data, p)
        self.assertEqual([m['name'] for m in self.disk()['sessions']['minutes']], ['1.docx'])
        self.assertTrue(os.path.exists(p))                        # لا يُحذف من القرص
        self.assertIn((p, '2.docx', True), cp.all_candidates(self.data, base=self.base))
        cp.exclude_minute(self.base, self.data, p, excluded=False)
        self.assertEqual(len(self.disk()['sessions']['minutes']), 2)


if __name__ == '__main__':
    unittest.main()


class DefendantGenderTests(unittest.TestCase):
    """(2026-10-25، A2263970) مدعى عليها أنثى ثابتة من صحيفة الدعوى كانت تُكتب «وتخلف المدعى عليه … رغم صحة إعلانه»."""
    RES = [{'name': 'شركة الاتصالات الكويتية ش.م.ك.', 'role': 'plaintiff', 'present': True, 'certain': True},
           {'name': 'أبرار نواف عبدالله الربيع', 'role': 'defendant', 'present': False, 'certain': True}]

    def data(self, g):
        return {'case': {'plaintiff': 'شركة الاتصالات الكويتية ش.م.ك.', 'defendants': ['أبرار نواف عبدالله الربيع'],
                         'genders': {'defendant': [g]}}}

    def test_female_defendant_from_plaint(self):
        self.assertEqual(cp.attendance_clause(self.RES, notified={'defendant': True}, data=self.data('f')),
                         'حضرتها الشركة المدعية وتخلفت المدعى عليها عن الحضور رغم صحة إعلانها')

    def test_male_or_unknown_unchanged(self):
        want = 'حضرتها الشركة المدعية وتخلف المدعى عليه عن الحضور رغم صحة إعلانه'
        self.assertEqual(cp.attendance_clause(self.RES, notified={'defendant': True}, data=self.data('m')), want)
        self.assertEqual(cp.attendance_clause(self.RES, notified={'defendant': True}), want)      # بلا بيانات: كما كان

    def test_two_female_defendants_ordinals(self):
        res = self.RES[:1] + [dict(self.RES[1], name='س'), dict(self.RES[1], name='ص')]
        data = {'case': {'defendants': ['س', 'ص'], 'genders': {'defendant': ['f', 'f']}}}
        self.assertEqual([l for l, _f in cp.party_labels(res, data)][1:], ['المدعى عليها الأولى', 'المدعى عليها الثانية'])
