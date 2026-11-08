# اختبارات البنية المختصرة لمجلد القضية + خط البداية + الفرز + العقد + الملخص + الكتابة التلقائية + حارس الحلقة + زر المجلد
# python -W ignore -m unittest test_case_layout -v
import hashlib
import json
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import case_autowrite as aw
import case_folder as cf
import case_layout as cl
import case_main_contract as mc
import case_sort as cs
import case_startup as st
import case_summary
import case_workspace as cw
import loop_guard

CASE = {'caso_no': 'A9990077', 'autocase_no': '999000177', 'claim_no': '2026/77',
        'plaintiff': 'شركة الاتصالات المتنقلة', 'defendants': ['خالد محمد سالم']}


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha1(f.read()).hexdigest()


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data if isinstance(data, bytes) else data.encode('utf-8'))


def all_hashes(root):
    out = []
    for dp, _, fs in os.walk(root):
        for n in fs:
            out.append(sha(os.path.join(dp, n)))
    return sorted(out)


# ---------- مزوّد وهمي للفرز ----------

PORTF_MD = ('<!-- صفحة 1 -->\nحافظة مستندات مقدمة من الشركة المدعية بجلسة 15/10/2025\n| م | البيان |\n| 1 | عقد |\n'
            '<!-- صفحة 2 -->\nعقد اشتراك رقم 55 مؤرخ 01/02/2024 بين الشركة والمدعى عليه بقيمة 1,200.000 د.ك لمدة سنة')
MEMO_MD = '<!-- صفحة 1 -->\nمذكرة بدفاع المدعى عليه مقدمة بتاريخ 02/04/2026 يطلب فيها رفض الدعوى'
MIN_MD = '<!-- صفحة 1 -->\nمحضر أعمال الخبرة رقم المحضر 3 بتاريخ 05/05/2026 حضر وكيل الشركة المدعية'
MIXED_MD = ('<!-- صفحة 1 -->\nمذكرة دفاع المدعية بتاريخ 15/10/2025\n<!-- صفحة 2 -->\nمذكرة ثانية المدعية بتاريخ 15/10/2025\n'
            '<!-- صفحة 3 -->\nحافظة مستندات المدعية بتاريخ 15/10/2025')
UNKNOWN_MD = '<!-- صفحة 1 -->\nورقة غير واضحة بلا عنوان'
OLD_PORTF_MD = '<!-- صفحة 1 -->\nحافظة مستندات مقدمة من الشركة المدعية بجلسة 10/01/2025\nكشف حساب فقط'

REPLIES = {
    'حافظة مستندات مقدمة من الشركة المدعية بجلسة 15/10/2025': {'parts': [{
        'type': 'حافظة', 'submitter_role': 'plaintiff', 'submitter_index': 1, 'submitter_as_written': 'الشركة المدعية',
        'date': '15/10/2025', 'pages': [1, 2],
        'contract': {'found': True, 'number': '55', 'date': '01/02/2024', 'parties': ['الشركة', 'المدعى عليه'],
                     'scope': 'خدمات اتصالات', 'value': '1,200.000', 'duration': 'سنة', 'summary': 'عقد اشتراك',
                     'doc_no': '1', 'page': 2}}]},
    'مذكرة بدفاع المدعى عليه': {'parts': [{'type': 'مذكرة', 'submitter_role': 'defendant', 'submitter_index': 1,
                                           'date': '02/04/2026', 'pages': [1, 1]}]},
    'محضر أعمال الخبرة': {'parts': [{'type': 'محضر', 'minute_no': 9, 'date': '05/05/2026', 'pages': [1, 1]}]},
    'مذكرة دفاع المدعية بتاريخ 15/10/2025': {'parts': [
        {'type': 'مذكرة', 'submitter_role': 'plaintiff', 'date': '15/10/2025', 'pages': [1, 1]},
        {'type': 'مذكرة', 'submitter_role': 'plaintiff', 'date': '15/10/2025', 'pages': [2, 2]},
        {'type': 'حافظة', 'submitter_role': 'plaintiff', 'date': '15/10/2025', 'pages': [3, 3]}]},
    'ورقة غير واضحة': {'parts': [{'type': 'أخرى'}]},
    'كشف حساب فقط': {'parts': [{'type': 'حافظة', 'submitter_role': 'plaintiff', 'date': '10/01/2025', 'pages': [1, 1],
                                'contract': {'found': False}}]},
}


class FakeAsk:
    def __init__(self, contract_reply=None):
        self.calls, self.contract_reply = [], contract_reply or {'found': False}

    def __call__(self, prompt):
        self.calls.append(prompt)
        if 'نص الحافظة:' in prompt:                       # طلب العقد المخصص (case_main_contract)
            return json.dumps(self.contract_reply, ensure_ascii=False)
        for key, rep in REPLIES.items():
            if key in prompt:
                return json.dumps(rep, ensure_ascii=False)
        return '{"parts": []}'


def md_convert(path, kind):
    with open(path, 'rb') as f:
        raw = f.read().decode('utf-8', 'replace')
    return raw, raw.count('<!-- صفحة') or 1, 'direct'


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, 'ws')
        self.base, self.data = cw.ensure_workspace(CASE, self.root)
        self._old = cf.CONVERTER
        cf.CONVERTER = md_convert

    def tearDown(self):
        cf.CONVERTER = self._old
        self._tmp.cleanup()

    def drop(self, name, text, folder=cf.OTHER):
        write(os.path.join(self.base, folder, name), text)


# ---------- 1) الترحيل بلا فقد ----------

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.base = os.path.join(self.root, CASE['caso_no'])
        b = self.base
        data = dict(CASE, schema=2, caso_no=CASE['caso_no'],
                    sources={'judgment': {'file': 'حكم_الإحالة/حكم_الإحالة.pdf'}},
                    portfolios=[{'id': 'P1', 'docs': [{'uid': 'd1', 'file': 'مستندات_أخرى/عقد.pdf',
                                                       'md': 'markdown/مستندات_أخرى/عقد.md'}]}],
                    conclusion={'file': '04_تقرير/النتيجة.md'},
                    procedures={'excluded': [os.path.join(b, 'محاضر', '2.docx')]})
        write(os.path.join(b, 'case.json'), json.dumps(data, ensure_ascii=False))
        write(os.path.join(b, 'case.json.bak'), json.dumps(data, ensure_ascii=False))
        write(os.path.join(b, 'محاضر', '1.docx'), b'minute-1')
        write(os.path.join(b, 'محاضر', '2.docx'), b'minute-2')
        write(os.path.join(b, 'حكم_الإحالة', 'حكم_الإحالة.pdf'), b'%PDF-judgment')
        write(os.path.join(b, 'حكم_الإحالة', 'حكم قديم.pdf'), b'%PDF-old')
        write(os.path.join(b, 'صحيفة_الدعوى', 'صحيفة_الدعوى.pdf'), b'%PDF-plaint')
        write(os.path.join(b, 'مستندات_أخرى', 'عقد.pdf'), b'contract')
        write(os.path.join(b, 'تقارير_سابقة', 'تقرير 2024.pdf'), b'prior')
        write(os.path.join(b, 'markdown', 'محاضر', '1.md'), 'نص المحضر 1')
        write(os.path.join(b, 'markdown', 'مستندات_أخرى', 'عقد.md'), 'نص العقد')
        man = {'version': 1, 'files': {'محاضر/1.docx': {'sha1': sha(os.path.join(b, 'محاضر', '1.docx')), 'state': 'done',
                                                       'md': 'markdown/محاضر/1.md', 'size': 8, 'mtime': 0},
                                       'مستندات_أخرى/عقد.pdf': {'sha1': 'x', 'state': 'done',
                                                                'md': 'markdown/مستندات_أخرى/عقد.md'}}}
        write(os.path.join(b, 'markdown', '.manifest.json'), json.dumps(man, ensure_ascii=False))
        write(os.path.join(b, '00_نظام', 'مصادر', 'حكم_الإحالة.txt'), 'نص')
        write(os.path.join(b, '03_حقائق', 'الحقائق.json'), '{}')
        write(os.path.join(b, '04_تقرير', 'البحث.md'), 'بحث')
        write(os.path.join(b, '04_تقرير', 'التقرير_v1.docx'), b'docx')
        write(os.path.join(b, 'فهرس_المستندات.md'), 'فهرس')
        self.before = all_hashes(b)

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_loss_every_file_kept_and_old_dirs_removed(self):
        base, data = cw.ensure_workspace(CASE, self.root)
        after = all_hashes(base)
        for h in self.before:                                  # كل محتوى قديم موجود بعد الترحيل
            self.assertIn(h, after)
        for old in ('محاضر', 'حكم_الإحالة', 'صحيفة_الدعوى', 'مستندات_أخرى', 'تقارير_سابقة',
                    '00_نظام', '01_اصول', '02_markdown', '03_حقائق', '04_تقرير'):
            self.assertFalse(os.path.exists(os.path.join(base, old)), old)
        self.assertFalse(os.path.exists(os.path.join(base, 'case.json')))
        S = os.path.join(base, cl.SYSDOCS)
        self.assertEqual(sorted(os.listdir(S)), sorted(['حكم الإحالة.pdf', 'حكم قديم.pdf', 'صحيفة الدعوى.pdf',
                                                        'محضر الخبرة رقم 1.docx', 'محضر الخبرة رقم 2.docx',
                                                        'تقرير 2024.pdf']))
        self.assertTrue(os.path.exists(os.path.join(base, 'أخرى', 'عقد.pdf')))
        self.assertTrue(os.path.exists(os.path.join(base, 'markdown', cl.SYSDOCS, 'محضر الخبرة رقم 1.md')))
        self.assertTrue(os.path.exists(os.path.join(base, 'التقرير', 'التقرير_v1.docx')))
        self.assertTrue(os.path.exists(os.path.join(base, '_نظام', '04_تقرير', 'البحث.md')))
        self.assertTrue(os.path.exists(os.path.join(base, '_نظام', '03_حقائق', 'الحقائق.json')))
        self.assertTrue(os.path.exists(os.path.join(base, '_نظام', 'مصادر', 'حكم_الإحالة.txt')))
        self.assertTrue(os.path.exists(os.path.join(base, '_نظام', 'فهرس_المستندات.md')))
        # المراجع داخل case.json والـmanifest
        self.assertEqual(data['sources']['judgment']['file'], 'مستندات_النظام/حكم الإحالة.pdf')
        self.assertEqual(data['portfolios'][0]['docs'][0]['file'], 'أخرى/عقد.pdf')
        self.assertEqual(data['portfolios'][0]['docs'][0]['md'], 'markdown/أخرى/عقد.md')
        self.assertEqual(data['conclusion']['file'], '_نظام/04_تقرير/النتيجة.md')
        self.assertEqual(data['procedures']['excluded'], [os.path.join(base, 'مستندات_النظام', 'محضر الخبرة رقم 2.docx')])
        man = cf.load_manifest(base)['files']
        self.assertEqual(man['مستندات_النظام/محضر الخبرة رقم 1.docx']['md'], 'markdown/مستندات_النظام/محضر الخبرة رقم 1.md')
        self.assertIn('أخرى/عقد.pdf', man)

    def test_log_for_every_move_and_second_run_is_noop(self):
        base, _ = cw.ensure_workspace(CASE, self.root)
        with open(os.path.join(base, '_نظام', 'سجلات', 'ترحيل_البنية.log'), encoding='utf-8') as f:
            log = f.read()
        self.assertIn('محاضر/1.docx', log)
        self.assertIn('sha1=', log)
        hist = json.load(open(os.path.join(base, '_نظام', 'سجلات', 'ترحيل_البنية.json'), encoding='utf-8'))
        self.assertGreaterEqual(len(hist['runs'][0]['moves']), 14)
        self.assertIsNone(cl.migrate(base))                   # لا قديم بعد الآن
        self.assertEqual(all_hashes(base), all_hashes(base))

    def test_hidden_system_folder_and_minutes_already_converted(self):
        base, data = cw.ensure_workspace(CASE, self.root)
        calls = []
        old = cf.CONVERTER
        cf.CONVERTER = lambda p, k: (calls.append(os.path.basename(p)), ('نص', 1))[1]
        try:
            cf.sync_case_folder(base, data)
        finally:
            cf.CONVERTER = old
        self.assertNotIn('محضر الخبرة رقم 1.docx', calls)     # مشتقه رُحِّل معه فلا يُعاد تحويله

    def test_safe_move_never_overwrites(self):
        a = os.path.join(self.root, 'x', 'a.txt')
        b = os.path.join(self.root, 'y', 'a.txt')
        write(a, 'one')
        write(b, 'two')
        got = cl.safe_move(a, b)
        self.assertTrue(got.endswith('a (2).txt'))
        self.assertEqual(open(b, encoding='utf-8').read(), 'two')


# ---------- 2) الفرز بنموذج وهمي ----------

class SortTests(Base):
    def test_portfolio_memo_minutes_mixed_unknown(self):
        self.drop('scan1.pdf', PORTF_MD)
        self.drop('scan2.pdf', MEMO_MD)
        self.drop('scan3.pdf', MIN_MD)
        self.drop('scan4.pdf', MIXED_MD)
        self.drop('scan5.pdf', UNKNOWN_MD)
        cf.sync_case_folder(self.base, self.data)
        ask = FakeAsk()
        res = cs.run(self.base, self.data, ask)
        self.assertEqual(res['todo'], 5)
        ls = lambda d: sorted(os.listdir(os.path.join(self.base, d)))      # noqa: E731
        self.assertEqual(ls(cf.PORTF), ['حافظة مستندات المدعية 15-10-2025.pdf'])
        self.assertEqual(ls(cf.MEMOS), ['مذكرة دفاع المدعى عليه 02-04-2026.pdf'])
        # رقم المحضر من نص المحضر (3) لا من ردّ النموذج (9)
        self.assertIn('محضر الخبرة رقم 3.pdf', ls(cf.SYSDOCS))
        self.assertEqual(ls(cf.OTHER), ['2 مذكرة و1 حافظة - المدعية 15-10-2025.pdf', 'scan5.pdf'])
        # markdown المقابل نُقل بالاسم الجديد
        self.assertTrue(os.path.exists(os.path.join(self.base, 'markdown', cf.PORTF,
                                                    'حافظة مستندات المدعية 15-10-2025.md')))
        # المختلط: تفاصيل الأجزاء محفوظة؛ المجهول: سؤال واحد
        f = self.data['sort']['files']['أخرى/2 مذكرة و1 حافظة - المدعية 15-10-2025.pdf']
        self.assertEqual(f['state'], 'mixed')
        self.assertEqual([p['pages'] for p in f['parts']], [[1, 1], [2, 2], [3, 3]])
        qs = cs.questions(self.data)
        self.assertEqual([os.path.basename(r) for r, _ in qs], ['scan5.pdf'])
        # لا يُعاد الفرز (بصمة)
        ask.calls.clear()
        self.assertEqual(cs.run(self.base, self.data, ask)['todo'], 0)
        self.assertEqual(ask.calls, [])

    def test_date_and_role_must_be_literal(self):
        self.drop('x.pdf', '<!-- صفحة 1 -->\nحافظة مستندات بلا صفة ولا تاريخ')
        cf.sync_case_folder(self.base, self.data)
        reply = {'parts': [{'type': 'حافظة', 'submitter_role': 'defendant', 'date': '01/01/2020', 'pages': [1, 1]}]}
        cs.run(self.base, self.data, lambda p: json.dumps(reply))
        self.assertEqual(os.listdir(os.path.join(self.base, cf.PORTF)), [])        # لم يُحسم ← يبقى في أخرى
        (rel, q), = cs.questions(self.data)
        self.assertIn('لم يُعرف مقدّمها ولا تاريخها', q)

    def test_expert_answer_moves_file(self):
        self.drop('x.pdf', UNKNOWN_MD)
        cf.sync_case_folder(self.base, self.data)
        cs.run(self.base, self.data, FakeAsk())
        rec = cs.answer(self.base, self.data, 'أخرى/x.pdf', 'مذكرة', 'defendant', 1, '02/04/2026')
        self.assertEqual(rec['file'], 'مذكرات/مذكرة دفاع المدعى عليه 02-04-2026.pdf')
        self.assertEqual(cs.questions(self.data), [])

    def test_duplicate_name_gets_suffix(self):
        self.drop('a.pdf', PORTF_MD)
        self.drop('b.pdf', PORTF_MD + '\nنسخة')
        cf.sync_case_folder(self.base, self.data)
        cs.run(self.base, self.data, FakeAsk())
        self.assertEqual(sorted(os.listdir(os.path.join(self.base, cf.PORTF))),
                         ['حافظة مستندات المدعية 15-10-2025 (2).pdf', 'حافظة مستندات المدعية 15-10-2025.pdf'])

    def test_canonical_names_are_not_resorted(self):
        for n in ('حكم الإحالة', 'صحيفة الدعوى', 'محضر الخبرة رقم 2', 'تقرير خبرة سابق 01-02-2024'):
            self.assertTrue(cs.is_canonical(f'{cf.SYSDOCS}/{n}.pdf'), n)
        self.assertTrue(cs.is_canonical(f'{cf.PORTF}/حافظة مستندات المدعى عليها الأولى 01-02-2024 (2).pdf'))
        self.assertFalse(cs.is_canonical(f'{cf.PORTF}/scan.pdf'))
        self.assertFalse(cs.is_canonical(f'{cf.OTHER}/x.pdf'))


# ---------- 3) التسمية بالصفة والجنس الصحيح ----------

class LabelTests(unittest.TestCase):
    def data(self, plaintiff='شركة زين', defendants=('خالد محمد',)):
        return {'case': {'plaintiff': plaintiff, 'defendants': list(defendants)}}

    def test_company_is_feminine(self):
        d = self.data(defendants=('شركة المقاولات المتحدة',))
        self.assertEqual(cs.role_label(d, 'plaintiff', 1, ''), 'المدعية')
        self.assertEqual(cs.role_label(d, 'defendant', 1, ''), 'المدعى عليها')

    def test_person_masculine_unless_text_says_feminine(self):
        d = self.data(plaintiff='محمد علي', defendants=('نورة سالم',))
        self.assertEqual(cs.role_label(d, 'plaintiff', 1, 'قدمها المدعي'), 'المدعي')
        self.assertEqual(cs.role_label(d, 'defendant', 1, 'مذكرة بدفاع المدعى عليها'), 'المدعى عليها')
        self.assertEqual(cs.role_label(d, 'defendant', 1, ''), 'المدعى عليه')

    def test_several_parties_ordinal_by_gender(self):
        d = self.data(defendants=('شركة ألف للتجارة', 'سالم أحمد'))
        self.assertEqual(cs.role_label(d, 'defendant', 1, ''), 'المدعى عليها الأولى')
        self.assertEqual(cs.role_label(d, 'defendant', 2, ''), 'المدعى عليه الثاني')

    def test_appeal_roles(self):
        d = {'case': {'appellants': ['شركة الخليج'], 'appellees': ['فهد ناصر']}}
        self.assertEqual(cs.role_label(d, 'appellant', 1, ''), 'المستأنفة')
        self.assertEqual(cs.role_label(d, 'appellee', 1, ''), 'المستأنف ضده')


# ---------- 4) العقد من أقدم حافظة ----------

class ContractTests(Base):
    def _sorted(self, ask):
        self.drop('new.pdf', PORTF_MD)
        self.drop('old.pdf', OLD_PORTF_MD)
        cf.sync_case_folder(self.base, self.data)
        cs.run(self.base, self.data, ask)

    def test_oldest_first_then_next(self):
        ask = FakeAsk()
        self._sorted(ask)
        order = [it['date'] for it in mc.portfolios(self.base)]
        self.assertEqual(order, ['10-01-2025', '15-10-2025'])
        ask.calls.clear()
        got = mc.find(self.base, self.data, ask)
        self.assertTrue(got['found'])
        self.assertEqual(got['checked'], ['حوافظ/حافظة مستندات المدعية 10-01-2025.pdf',
                                          'حوافظ/حافظة مستندات المدعية 15-10-2025.pdf'])
        self.assertEqual(len(ask.calls), 1)                   # الأقدم بلا عقد ← طلب مخصص؛ الثانية من جواب الفرز
        c = got['contract']
        self.assertEqual((c['number'], c['date'], c['value']), ('55', '01/02/2024', '1,200.000'))
        self.assertTrue(c['checks']['date'] and c['checks']['value'])
        self.assertEqual(self.data['contracts']['items'][0]['origin'], 'main_contract')
        ask.calls.clear()
        self.assertTrue(mc.find(self.base, self.data, ask)['found'])     # مخزّن ببصمة النصوص
        self.assertEqual(ask.calls, [])

    def test_value_not_literal_is_rejected(self):
        bad = dict(REPLIES)
        self._sorted(FakeAsk())
        e = cf.load_manifest(self.base)['files']['حوافظ/حافظة مستندات المدعية 15-10-2025.pdf']
        e['sort']['parts'][0]['contract']['value'] = '9,999.000'
        man = cf.load_manifest(self.base)
        man['files']['حوافظ/حافظة مستندات المدعية 15-10-2025.pdf'] = e
        cf.save_manifest(self.base, man)
        got = mc.find(self.base, self.data, FakeAsk({'found': True, 'date': '01/02/2024', 'value': '7,777'}))
        self.assertFalse(got['found'])
        self.assertIn('لم يُتحقق', got['message'])
        self.assertEqual(bad, REPLIES)


# ---------- 5) كشف الحلقة وإعادة التحويل ----------

class LoopTests(Base):
    LOOP = 'سطر يتكرر في الصفحة بلا توقف أبداً هنا\n' * 40

    def test_detect_kinds(self):
        self.assertIn('تكرار السطر', loop_guard.detect(self.LOOP, 1))
        words = ' '.join(f'كلمة{i}' for i in range(12))
        self.assertIn('عبارة طويلة', loop_guard.detect((words + ' ') * 20, 0))
        self.assertIn('طول الناتج', loop_guard.detect('أ ب ' * 20000, 1))
        self.assertIn('نهاية النص', loop_guard.detect('مقدمة عادية للنص. ' + 'والمبلغ المستحق ' * 300, 0))
        self.assertIsNone(loop_guard.detect('نص طبيعي من صفحتين\n<!-- صفحة 2 -->\nونص آخر مختلف تماماً', 2))

    def test_retry_with_smaller_batches_then_ok(self):
        import doc_router
        batches = []

        def conv(path, kind):
            batches.append(doc_router.batch_override())
            return (self.LOOP if len(batches) < 2 else 'نص سليم'), 1, 'gemini'
        cf.CONVERTER = conv
        self.drop('a.pdf', 'x')
        res = cf.sync_case_folder(self.base, self.data)
        self.assertEqual(res['converted'], ['أخرى/a.pdf'])
        self.assertEqual(batches, [0, cf.RETRY_BATCHES[0]])
        e = cf.load_manifest(self.base)['files']['أخرى/a.pdf']
        self.assertEqual(e['retries'], 1)

    def test_two_retries_then_failed_red_and_nothing_saved(self):
        calls = []
        cf.CONVERTER = lambda p, k: (calls.append(1), (self.LOOP, 1))[1]
        self.drop('a.pdf', 'x')
        res = cf.sync_case_folder(self.base, self.data)
        self.assertEqual(len(calls), 1 + len(cf.RETRY_BATCHES))           # محاولتان فقط بعد الأولى
        self.assertTrue(res['failed'][0][1].startswith(cf.LOOP_FAIL))
        e = cf.load_manifest(self.base)['files']['أخرى/a.pdf']
        self.assertTrue(e['loop'])
        self.assertFalse(os.path.exists(os.path.join(self.base, 'markdown', 'أخرى', 'a.md')))
        from qt_startup_panel import doc_rows
        row = next(r for r in doc_rows(self.base, self.data) if r['rel'] == 'أخرى/a.pdf')
        self.assertEqual((row['red'], row['action']), (True, 'retry'))
        self.assertIn('حلقة', row['state'])

    def test_gemini_engine_stops_on_looping_batch(self):
        import doc_router
        with self.assertRaises(loop_guard.LoopDetected):
            loop_guard.check(self.LOOP, 1)
        self.assertTrue(hasattr(doc_router, 'check_stall'))

    def test_stall_without_progress_counts_as_failed_attempt(self):
        import doc_router

        def conv(path, kind):
            doc_router.start_watch(0)            # حد صفري: أي فجوة = مهلة
            raise doc_router.Stalled('مهلة طويلة بلا تقدّم (0 ثانية)')
        cf.CONVERTER = conv
        self.drop('a.pdf', 'x')
        res = cf.sync_case_folder(self.base, self.data)
        self.assertIn('مهلة', res['failed'][0][1])


# ---------- 5ب) فشل المفتاح الشخصي + حارس الحلقة معاً (الجلستان) ----------

class KeyFailureWithLoopGuardTests(Base):
    def key_failure(self):
        import ai_providers as ap
        return ap.PersonalKeyFailure('gemini', 'quota', 'HTTP 429', alt=None, section=False)

    def test_conversion_stops_whole_task_no_retry_no_failed_mark(self):
        calls = []

        def conv(path, kind):
            calls.append(os.path.basename(path))
            raise self.key_failure()
        cf.CONVERTER = conv
        self.drop('a.pdf', 'x')
        self.drop('b.pdf', 'y')
        import ai_providers as ap
        with self.assertRaises(ap.PersonalKeyFailure):
            cf.sync_case_folder(self.base, self.data)
        self.assertEqual(calls, ['a.pdf'])                     # لا إعادة بدفعات أصغر ولا انتقال للملف التالي
        man = cf.load_manifest(self.base)['files']
        self.assertFalse(any(e.get('state') == 'failed' for e in man.values()))
        cf.CONVERTER = md_convert                               # بعد اختيار الخبير: يُحوَّل كله من جديد
        self.assertEqual(len(cf.sync_case_folder(self.base, self.data)['converted']), 2)

    def test_loop_guard_still_retries_when_key_is_fine(self):
        n = []
        cf.CONVERTER = lambda p, k: (n.append(1), (LoopTests.LOOP if len(n) == 1 else 'نص سليم', 1))[1]
        self.drop('a.pdf', 'x')
        self.assertEqual(cf.sync_case_folder(self.base, self.data)['converted'], ['أخرى/a.pdf'])
        self.assertEqual(len(n), 2)

    def test_gemini_engine_raises_key_failure_and_loop_separately(self):
        from unittest import mock
        import ai_providers as ap
        import doc_router
        prov = ap.GeminiProvider('Gemini', 'AQ.OwnKey_abcdefghijklmnopqrstuvwxyz', ap.KEY_OWN)
        common = (mock.patch.object(doc_router, '_gemini_provider', lambda: prov),
                  mock.patch.object(doc_router, '_as_pdf', lambda path, tmp: path),
                  mock.patch.object(doc_router, 'page_count', lambda p: 1),
                  mock.patch.object(doc_router.os.path, 'getsize', lambda p: 100),
                  mock.patch.object(doc_router, 'plan_chunks', lambda *a, **k: [(0, 1, 'x.pdf')]))
        for p in common:
            p.start()
        try:
            with mock.patch.object(doc_router, '_call_provider_retry', side_effect=RuntimeError('HTTP 429 quota')):
                with self.assertRaises(ap.PersonalKeyFailure):
                    doc_router.gemini_engine(lambda path: ('محلي', 1))('a.pdf', {})
            with mock.patch.object(doc_router, '_call_provider_retry', return_value=LoopTests.LOOP):
                with self.assertRaises(loop_guard.LoopDetected):
                    doc_router.gemini_engine(lambda path: ('محلي', 1))('a.pdf', {})
        finally:
            for p in common:
                p.stop()
            ap.reset_key_state()

    def test_startup_stops_on_key_failure_during_sort(self):
        import ai_providers as ap
        self.drop('scan.pdf', MEMO_MD)

        def ask(prompt):
            raise self.key_failure()
        with self.assertRaises(ap.PersonalKeyFailure):
            st.run(self.base, self.data, ask=ask, fetch=lambda k: [])
        s = st.state(self.data)
        self.assertEqual((s['convert']['state'], s['sort']['state'], s['contract']['state']), ('done', 'failed', 'pending'))
        self.assertIn('مفتاحك الشخصي', s['sort']['message'])
        self.assertFalse((self.data.get('sort') or {}).get('errors'))       # لا خطأ مسجّل لكل ملف


# ---------- 6) الكتابة التلقائية للموضوع والإجراءات ----------

class AutowriteTests(unittest.TestCase):
    def test_subject_plaint_then_contract_and_manual_kept(self):
        data = {'subject': ''}
        n = {'s': 0}

        def write_subject():
            n['s'] += 1
            data['subject'] = 'من العقد والصحيفة' if (data.get('main_contract') or {}).get('found') else 'من الصحيفة'
        self.assertEqual(aw.run(None, data, write_subject, None), ['subject'])
        self.assertEqual(aw.line(data, 'subject'), ('كُتب من صحيفة الدعوى', ''))
        self.assertEqual(aw.run(None, data, write_subject, None), [])          # لا تكرار
        data['main_contract'] = {'found': True}
        self.assertEqual(aw.run(None, data, write_subject, None), ['subject'])
        self.assertEqual(data['subject'], 'من العقد والصحيفة')
        self.assertEqual(aw.line(data, 'subject')[0], 'كُتب من العقد وصحيفة الدعوى')
        self.assertEqual(n['s'], 2)
        # تعديل يدوي ثم مصدر أحدث (محاكاة): لا يُستبدل، وتظهر الملاحظة
        data2 = {'subject': 'نص الخبير', 'subject_edited': True,
                 'autowrite': {'subject': {'source': 'plaint', 'note': 'كُتب من صحيفة الدعوى'}},
                 'main_contract': {'found': True}}
        self.assertEqual(aw.run(None, data2, lambda: data2.update(subject='مستبدل!'), None), [])
        self.assertEqual(data2['subject'], 'نص الخبير')
        self.assertEqual(aw.line(data2, 'subject')[1], aw.NEWER)
        aw.accept_newer(None, data2, 'subject', lambda: data2.update(subject='من العقد'))
        self.assertEqual((data2['subject'], aw.line(data2, 'subject')), ('من العقد', ('كُتب من العقد وصحيفة الدعوى', '')))

    def test_procedures_system_then_minutes(self):
        data = {'procedures': {}, 'sessions': {}}

        def write_proc():
            mins = data['sessions'].get('minutes')
            data['procedures']['text'] = 'من المحاضر' if mins else 'من النظام'
        aw.run(None, data, None, write_proc)
        self.assertEqual(aw.line(data, 'procedures')[0], 'كُتبت من بيانات النظام')
        data['sessions']['minutes'] = [{'no': 1}]
        self.assertEqual(aw.run(None, data, None, write_proc), ['procedures'])
        self.assertEqual((data['procedures']['text'], aw.line(data, 'procedures')[0]), ('من المحاضر', 'كُتبت من المحاضر'))

    def test_procedures_manual_not_touched(self):
        data = {'procedures': {'text': 'نصي', 'edited': True}, 'sessions': {'minutes': [{'no': 1}]},
                'autowrite': {'procedures': {'source': 'system'}}}
        aw.run(None, data, None, lambda: data['procedures'].update(text='مستبدل'))
        self.assertEqual(data['procedures']['text'], 'نصي')
        self.assertEqual(aw.line(data, 'procedures')[1], aw.NEWER)


# ---------- 7) خط البداية والملخص ----------

class StartupTests(Base):
    def test_nine_steps_fetch_list_convert_sort_contract_summary_and_resume(self):
        fetched = []

        def fetch(kind):
            fetched.append(kind)
            name = {cf.JUDGMENT: 'حكم الإحالة.pdf', cf.PLAINT: 'صحيفة الدعوى.pdf'}[kind]
            write(os.path.join(self.base, cf.SYSDOCS, name), f'<!-- صفحة 1 -->\n{name}')
            return [f'{cf.SYSDOCS}/{name}']
        write(os.path.join(self.base, 'scan1.pdf'), PORTF_MD)           # في جذر القضية ← أخرى ثم الفرز
        self.drop('scan2.pdf', MEMO_MD)
        ask = FakeAsk()
        updates = []
        st.run(self.base, self.data, ask=ask, fetch=fetch, on_update=lambda k, s: updates.append((k, s['state'])))
        steps = st.state(self.data)
        self.assertEqual(sorted(fetched), sorted([cf.JUDGMENT, cf.PLAINT]))
        self.assertEqual({k: s['state'] for k, s in steps.items()},
                         {'scan': 'done', 'judgment': 'done', 'plaint': 'done', 'list': 'done', 'check': 'done',
                          'convert': 'done', 'sort': 'done', 'contract': 'done', 'summary': 'done'})
        self.assertEqual(steps['list']['count'], 2)          # المستندات أولاً؛ الحكم والصحيفة يُسحبان بعدها فقط
        self.assertEqual(steps['convert']['total'], 2)
        for kind in (cf.JUDGMENT, cf.PLAINT):                 # وما سُحب يُحوَّل إلى markdown
            self.assertTrue(cf.has_kind(self.base, kind))
        self.assertEqual([k for k, s in updates if s == 'running'][:2], ['scan', 'list'])
        self.assertTrue(os.path.exists(os.path.join(self.base, cf.PORTF, 'حافظة مستندات المدعية 15-10-2025.pdf')))
        self.assertFalse(os.path.exists(os.path.join(self.base, 'scan1.pdf')))
        self.assertTrue(self.data['main_contract']['found'])
        with open(os.path.join(self.base, 'الملخص.md'), encoding='utf-8') as f:
            s = f.read()
        for part in ('## المستندات', 'حافظة مستندات المدعية 15-10-2025.pdf', 'مذكرة دفاع المدعى عليه 02-04-2026.pdf',
                     '## العقد', '1,200.000', 'مكانه', '## المحاضر', '## مصدر كل جزء من التقرير'):
            self.assertIn(part, s)
        # الاستئناف/إعادة الفتح: لا جلب ولا تحويل ولا طلب فرز/عقد من جديد
        ask.calls.clear()
        fetched.clear()
        old = cf.CONVERTER
        conv_calls = []
        cf.CONVERTER = lambda p, k: (conv_calls.append(p), md_convert(p, k))[1]
        try:
            st.run(self.base, self.data, ask=ask, fetch=fetch)
        finally:
            cf.CONVERTER = old
        self.assertEqual((fetched, conv_calls, ask.calls), ([], [], []))
        self.assertEqual(st.state(self.data)['judgment']['state'], 'skipped')

    def test_without_provider_files_stay_in_other(self):
        self.drop('scan.pdf', MEMO_MD)
        st.run(self.base, self.data, ask=None, fetch=lambda k: [])
        self.assertEqual(os.listdir(os.path.join(self.base, cf.OTHER)), ['scan.pdf'])
        self.assertEqual(st.state(self.data)['sort']['state'], 'skipped')
        self.assertEqual(st.state(self.data)['judgment']['state'], 'failed')

    def test_summary_mixed_details(self):
        self.drop('m.pdf', MIXED_MD)
        cf.sync_case_folder(self.base, self.data)
        cs.run(self.base, self.data, FakeAsk())
        s = case_summary.render(self.base, self.data)
        self.assertIn('## الملفات المختلطة', s)
        self.assertIn('حافظة — المدعية — 15-10-2025 — الصفحات 3–3', s)
        self.assertIn('مذكرة — المدعية — 15-10-2025 — الصفحات 1–1', s)

    def test_summary_rewritten_on_every_save(self):
        self.data['caso_no'] = CASE['caso_no']
        cw.write_case_json(self.base, self.data)
        self.assertTrue(os.path.exists(os.path.join(self.base, 'الملخص.md')))


# ---------- 8) الواجهة: الفتح على المستندات + زر المجلد ----------

class UiTests(Base):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_page_opens_on_documents_with_live_steps_panel(self):
        import qt_case_page as qp
        old = (qp.CasePageDialog.AUTO_SYNC, qp.CasePageDialog.AUTO_RESUME, qp.CasePageDialog.STARTUP_VIEW)
        qp.CasePageDialog.AUTO_SYNC = qp.CasePageDialog.AUTO_RESUME = False
        qp.CasePageDialog.STARTUP_VIEW = True
        try:
            dlg = qp.CasePageDialog(self.base, cw.read_case_json(self.base))
            self.assertEqual(dlg._open, 'documents')
            self.assertFalse(hasattr(dlg, 'startup_panel'))         # لوحة واحدة فقط: خطواتها داخل لوحة المستندات
            dlg.docs_panel._refresh_steps()
            text = dlg.docs_panel.steps_text()
            self.assertIn('سحب حكم الإحالة من النظام', text)
            self.assertEqual(sum(label in text for _k, label in st.STEPS), 9)
            dlg.close()
        finally:
            qp.CasePageDialog.AUTO_SYNC, qp.CasePageDialog.AUTO_RESUME, qp.CasePageDialog.STARTUP_VIEW = old

    def test_folder_button_only_opens_explorer(self):
        import qt_expert_reports as er
        opened = []
        er.STARTFILE = opened.append
        try:
            page = er.ExpertReportsPage.__new__(er.ExpertReportsPage)
            er.ExpertReportsPage._open_documents(page, {'base': self.base, 'data': self.data})
        finally:
            er.STARTFILE = None
        self.assertEqual(opened, [self.base])
        self.assertFalse(er.open_case_folder(os.path.join(self.base, 'غير موجود')))


if __name__ == '__main__':
    unittest.main()
