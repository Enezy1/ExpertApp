# اختبارات تعديلات الخطة المجانية (2026-10-25): python -W ignore -m unittest test_free_plan -v
# رأس نوع المستند في markdown، إعادة الفرز المجمّعة من markdown (بلا OCR)، والقضايا القديمة لا يُعاد فرزها لتغيّر VERSION.
# لا طلب ذكاء حقيقي: كل «ask» هنا بديل محلي.
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication

import case_folder as cf
import case_sort as cs
import case_triage as ct
import case_workspace as cw
import doc_header
import test_qt_case_page as tp

CASE = tp.CASE
APP = QApplication.instance() or QApplication([])          # حيّ طوال الوحدة (حذفه مبكراً يُسقط Qt)


def _dispose(w):
    """حذف فوري للصفحة وأبنائها قبل نهاية العملية (الحذف المؤجَّل عند الخروج يُسقط Qt)."""
    from PyQt6 import sip
    APP.processEvents()
    sip.delete(w)
    APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    APP.processEvents()
MEMO = '<!-- صفحة 1 -->\nمذكرة بدفاع المدعى عليه بتاريخ 02/04/2026\nيدفع المدعى عليه بانقضاء العقد بالإلغاء'
PORTF = '<!-- صفحة 1 -->\nحافظة مستندات المدعية بتاريخ 15/10/2025\nمستند رقم (1) فاتورة بمبلغ 120.500 د.ك'
R_MEMO = {'parts': [{'type': 'مذكرة', 'pages': [1, 1], 'submitter_role': 'defendant', 'date': '02/04/2026',
                     'defenses': [{'summary': 'انقضاء العقد', 'quote': 'يدفع المدعى عليه بانقضاء العقد'}]}]}
R_PORTF = {'parts': [{'type': 'حافظة', 'pages': [1, 1], 'submitter_role': 'plaintiff', 'date': '15/10/2025'}]}


class Ask:
    def __init__(self, reply):
        self.calls, self.reply = [], reply

    def __call__(self, prompt):
        self.calls.append(prompt)
        return self.reply(prompt) if callable(self.reply) else self.reply


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def add(self, name, text):
        with open(os.path.join(self.base, cf.OTHER, name), 'w', encoding='utf-8') as f:
            f.write(text)

    def md_of(self, rel):
        e = cf.load_manifest(self.base)['files'][rel]
        with open(os.path.join(self.base, e['md']), encoding='utf-8') as f:
            return f.read()


class HeaderTests(Base):
    def test_render_parse_strip_roundtrip(self):
        info = {'type': 'حافظة مستندات', 'by': 'المدعية', 'date': '15-10-2025', 'minute': '', 'v': '4', 'sha1': 'abc'}
        text = doc_header.apply('<!-- صفحة 1 -->\nنص', info)
        self.assertTrue(text.startswith('<!-- ترويسة المستند | النوع: حافظة مستندات | المقدّم: المدعية'))
        self.assertEqual(doc_header.parse(text), info)
        self.assertEqual(doc_header.strip(text), '<!-- صفحة 1 -->\nنص')
        self.assertEqual(doc_header.apply(text, dict(info, by='المدعى عليه')).count('ترويسة المستند'), 1)
        self.assertEqual(doc_header.parse('نص بلا رأس'), {})

    def test_triage_writes_header_and_header_not_used_as_evidence(self):
        self.add('m.txt', MEMO)
        cf.sync_case_folder(self.base, self.data)
        cs.run(self.base, self.data, Ask(json.dumps(R_MEMO, ensure_ascii=False)))
        rel = f'{cf.MEMOS}/مذكرة دفاع المدعى عليه 02-04-2026.txt'
        h = doc_header.parse(self.md_of(rel))
        self.assertEqual((h['type'], h['by'], h['date'], h['v']), ('مذكرة دفاع', 'المدعى عليه', '02-04-2026', str(ct.VERSION)))
        self.assertEqual(h['sha1'], cf.load_manifest(self.base)['files'][rel]['sha1'])
        # تاريخ لا يرد إلا في الرأس لا «يتحقق» في الفرز التالي
        md = cs._read_md(self.base, cf.load_manifest(self.base)['files'][rel], rel)
        self.assertNotIn('ترويسة المستند', md)
        self.assertEqual(doc_header.read(self.base, cf.load_manifest(self.base)['files'][rel]['md'])['by'], 'المدعى عليه')

    def test_referral_mark_still_recognised_after_header(self):
        import referral_pick as rp
        text = doc_header.apply(cf.REFERRAL_MARK + '\n\nنص بلا صيغة ندب', {'type': 'حكم'})
        with mock.patch('case_subject_mission.extract_mission', return_value=['بند']):
            self.assertTrue(rp.is_referral(text))


class BatchRetriageTests(Base):
    def _two_files(self):
        self.add('m.txt', MEMO)
        self.add('p.txt', PORTF)
        cf.sync_case_folder(self.base, self.data)

    def _batch_reply(self, prompt):
        out = {}
        for fid in ('F1', 'F2', 'F3'):
            if f'=====ملف {fid}:' not in prompt:
                continue
            block = prompt.split(f'=====ملف {fid}:')[1].split(f'=====نهاية الملف {fid}=====')[0]
            out[fid] = R_MEMO if 'مذكرة بدفاع' in block else R_PORTF
        return json.dumps({'files': out}, ensure_ascii=False)

    def test_one_request_for_all_files_verified_per_file(self):
        self._two_files()
        ask = Ask(self._batch_reply)
        res = cs.retriage(self.base, self.data, ask)
        self.assertEqual((res['files'], res['requests'], len(ask.calls)), (2, 1, 1))     # دفعة واحدة لا طلب لكل ملف
        self.assertIn('=====ملف F1:', ask.calls[0])
        self.assertIn('=====ملف F2:', ask.calls[0])
        self.assertTrue(os.path.exists(os.path.join(self.base, cf.MEMOS, 'مذكرة دفاع المدعى عليه 02-04-2026.txt')))
        self.assertTrue(os.path.exists(os.path.join(self.base, cf.PORTF, 'حافظة مستندات المدعية 15-10-2025.txt')))
        e = cf.load_manifest(self.base)['files'][f'{cf.MEMOS}/مذكرة دفاع المدعى عليه 02-04-2026.txt']
        self.assertEqual(e['triage']['source'], 'batch')

    def test_cross_file_values_rejected_by_per_file_verification(self):
        self._two_files()
        # النموذج نقل تاريخ المذكرة إلى الحافظة: التحقق على نص الحافظة وحده يرفضه
        bad = {'parts': [{'type': 'حافظة', 'pages': [1, 1], 'submitter_role': 'plaintiff', 'date': '02/04/2026'}]}

        def reply(prompt):
            out = json.loads(self._batch_reply(prompt))
            for fid, v in out['files'].items():
                if v is R_PORTF or v == R_PORTF:
                    out['files'][fid] = bad
            return json.dumps(out, ensure_ascii=False)
        cs.retriage(self.base, self.data, Ask(reply))
        man = cf.load_manifest(self.base)['files']
        portf = next(e for rel, e in man.items() if 'p.txt' in rel or rel.startswith(cf.PORTF))
        self.assertEqual(portf['triage']['parts'][0]['date'], '')

    def test_batches_by_size_and_plan_counts(self):
        self._two_files()
        n, req = cs.retriage_plan(self.base, limit=10)                # حد صغير: كل ملف في دفعته
        self.assertEqual((n, req), (2, 2))
        self.assertEqual(cs.retriage_plan(self.base)[1], 1)
        ask = Ask(self._batch_reply)
        cs.retriage(self.base, self.data, ask, limit=10)
        self.assertEqual(len(ask.calls), 2)

    def test_single_file_retriage_no_conversion(self):
        self._two_files()
        conv = []
        cf.CONVERTER, old = (lambda *a: conv.append(a)), cf.CONVERTER
        try:
            ask = Ask(self._batch_reply)
            rel = f'{cf.OTHER}/m.txt'
            cs.retriage(self.base, self.data, ask, rels=[rel])
        finally:
            cf.CONVERTER = old
        self.assertEqual(conv, [])                                   # من markdown الموجود: بلا تحويل ولا OCR
        self.assertEqual(len(ask.calls), 1)
        self.assertNotIn('p.txt', ask.calls[0])

    def test_missing_file_in_reply_is_error_not_crash(self):
        self._two_files()
        res = cs.retriage(self.base, self.data, Ask('{"files": {}}'))
        self.assertEqual(len(res['errors']), 2)


class OldCaseTests(Base):
    def test_version_bump_does_not_retriage_written_case(self):
        self.add('m.txt', MEMO)
        cf.sync_case_folder(self.base, self.data)
        cs.run(self.base, self.data, Ask(json.dumps(R_MEMO, ensure_ascii=False)))
        self.data['subject'] = 'جاءت المدعية بصحيفة…'
        self.data.setdefault('stage2', {})['sig'] = 'old'
        man = cf.load_manifest(self.base)
        for e in man['files'].values():
            e['triage']['v'] = ct.VERSION - 1                         # فُرز بقواعد أقدم
        cf.save_manifest(self.base, man)
        ask = Ask(json.dumps(R_MEMO, ensure_ascii=False))
        cs.run(self.base, self.data, ask)
        self.assertEqual(ask.calls, [])                               # القضية المكتوبة: تبقى بنتائجها
        self.assertTrue(ct.entries(self.base))                        # ونتائجها القديمة باقية في الملخص
        fresh = {'caso_no': self.data['caso_no']}
        self.assertTrue(ct.pending(self.base, data=fresh))            # قضية لم يُكتب موضوعها: تُعاد

    def test_summary_signature_unchanged_by_version_bump(self):
        import case_stage2
        self.add('m.txt', MEMO)
        cf.sync_case_folder(self.base, self.data)
        cs.run(self.base, self.data, Ask(json.dumps(R_MEMO, ensure_ascii=False)))
        sig = case_stage2.signature(self.base, self.data)
        with mock.patch.object(ct, 'VERSION', ct.VERSION + 1):
            self.assertEqual(case_stage2.signature(self.base, self.data), sig)


def claim_pdf(path, text='صحيفة الدعوى المرفوعة من المدعية', stamp=''):
    """PDF بطبقة نص؛ stamp يغيّر بايتات الغلاف (معرّف الملف/التاريخ) دون المحتوى — كما يفعل النظام في كل تنزيل."""
    import fitz
    d = fitz.open()
    d.new_page().insert_text((72, 72), 'Claim ' + text.encode('ascii', 'ignore').decode() + ' body text 2025')
    d.set_metadata({'producer': 'moj ' + stamp, 'creationDate': stamp})
    d.save(path)
    d.close()


class ClaimTests(Base):
    def test_same_content_new_bytes_no_second_copy(self):
        import case_sources as src
        a, b = os.path.join(self._tmp.name, 'a.pdf'), os.path.join(self._tmp.name, 'b.pdf')
        claim_pdf(a, stamp='1')
        claim_pdf(b, stamp='2')
        self.assertNotEqual(src._sha1(a), src._sha1(b))                 # البايتات مختلفة
        self.assertEqual(src.content_key(a), src.content_key(b))         # والمحتوى نفسه
        rec, added = src.store_claim(self.base, self.data, a, doc_id='77')
        self.assertEqual(added, f'{cf.SYSDOCS}/صحيفة الدعوى.pdf')
        self.assertEqual(src.store_claim(self.base, self.data, b, doc_id='77')[1], '')    # رقم المستند نفسه
        self.assertEqual(src.store_claim(self.base, self.data, b, doc_id='78')[1], '')    # المحتوى نفسه
        self.assertEqual(src.claim_files(self.base), [f'{cf.SYSDOCS}/صحيفة الدعوى.pdf'])
        self.assertEqual(self.data['sources']['claim']['doc_ids'], ['77', '78'])

    def test_different_text_saved_as_amended(self):
        import case_sources as src
        a, b = os.path.join(self._tmp.name, 'a.pdf'), os.path.join(self._tmp.name, 'b.pdf')
        claim_pdf(a, 'first')
        claim_pdf(b, 'second amended')
        src.store_claim(self.base, self.data, a)
        rec, added = src.store_claim(self.base, self.data, b)
        self.assertEqual(added, f'{cf.SYSDOCS}/صحيفة الدعوى — معدّلة.pdf')
        self.assertEqual(rec['file'], f'{cf.SYSDOCS}/صحيفة الدعوى.pdf')    # الأصلية تبقى المصدر
        self.assertTrue(cs.is_canonical(added))                          # الفرز لا يعيد تسميتها «(2)»

    def test_existing_duplicates_moved_not_deleted(self):
        import case_sources as src
        sd = os.path.join(self.base, cf.SYSDOCS)
        for i, name in enumerate(('صحيفة الدعوى.pdf', 'صحيفة الدعوى (2).pdf', 'صحيفة الدعوى (3).pdf')):
            claim_pdf(os.path.join(sd, name), stamp=str(i))
        moved = src.dedupe_claims(self.base, self.data)
        self.assertEqual(len(moved), 2)
        self.assertEqual(sorted(os.listdir(sd)), ['صحيفة الدعوى.pdf'])
        self.assertEqual(sorted(os.listdir(os.path.join(self.base, src.DUP_DIR))),
                         ['صحيفة الدعوى (2).pdf', 'صحيفة الدعوى (3).pdf'])
        self.assertEqual(src.dedupe_claims(self.base, self.data), [])
        self.assertNotIn(src.DUP_DIR, cf.FOLDERS)                        # خارج المزامنة والعدّ

    def test_dedupe_on_open_does_not_resume_subject(self):
        import case_stage2
        import case_startup
        sd = os.path.join(self.base, cf.SYSDOCS)
        claim_pdf(os.path.join(sd, 'صحيفة الدعوى.pdf'), stamp='0')
        case_startup.run(self.base, self.data, ask=None, fetch=lambda k: [])     # فتح سابق للقضية
        claim_pdf(os.path.join(sd, 'صحيفة الدعوى (2).pdf'), stamp='1')          # تنزيل مكرر قديم
        cf.sync_case_folder(self.base, self.data)
        self.data['subject'] = 'جاءت المدعية بصحيفة…'
        self.data.setdefault('stage2', {})['sig'] = case_stage2.signature(self.base, self.data)
        case_startup.run(self.base, self.data, ask=None, fetch=lambda k: [])
        self.assertEqual(sorted(os.listdir(os.path.join(self.base, 'مكررات'))),
                         ['صحيفة الدعوى (2).md', 'صحيفة الدعوى (2).pdf'])           # الأصل ومشتقه، بلا حذف
        self.assertFalse(case_stage2.needs_run(self.base, self.data))   # لا يُستأنف الموضوع لنقل مكرر

    def test_queue_uses_saved_claim_without_download(self):
        import case_sources as src
        import summary_queue as sq
        claim_pdf(os.path.join(self.base, cf.SYSDOCS, 'صحيفة الدعوى.pdf'))
        cw.write_case_json(self.base, self.data)
        got = []
        with mock.patch('documents.get_claim_for_case', side_effect=lambda *a: got.append(a)), \
                mock.patch.object(cw, 'ensure_workspace', return_value=(self.base, self.data)), \
                mock.patch.object(sq, 'summarize_text', return_value='ملخص'), \
                mock.patch('case_db.save_case'):
            cf.CONVERTER, old = (lambda p, k: ('نص الصحيفة', 1, 'text_layer')), cf.CONVERTER
            try:
                self.assertEqual(sq.process({'caso_no': self.data['caso_no'], 'autocase_no': '1'}, None), 'ملخص')
            finally:
                cf.CONVERTER = old
        self.assertEqual(got, [])                                        # لا تنزيل جديد
        self.assertEqual(src.claim_files(self.base), [f'{cf.SYSDOCS}/صحيفة الدعوى.pdf'])

    def test_case_json_merge_keeps_claim_source(self):
        page = json.loads(json.dumps(self.data))                         # نسخة صفحة القضية في الذاكرة
        self.data.setdefault('sources', {})['claim'] = {'file': f'{cf.SYSDOCS}/صحيفة الدعوى.pdf',
                                                        'fetched_at': '2026-10-25 10:00:00', 'doc_ids': ['5']}
        cw.write_case_json(self.base, self.data)                         # الطابور الخلفي يكتب المصدر
        page['subject'] = 'نص عدّله الخبير'
        cw.write_case_json(self.base, page)                              # الصفحة تكتب نسختها القديمة
        disk = cw.read_case_json(self.base)
        self.assertEqual(disk['sources']['claim']['doc_ids'], ['5'])
        self.assertEqual(disk['subject'], 'نص عدّله الخبير')


class DedupTests(unittest.TestCase):
    S = 'ترى الخبرة أن المدعى عليه أخل بالتزامه بسداد الفواتير الشهرية في مواعيدها المحددة.'

    def test_duplicate_sentence_removed_by_code_and_noted(self):
        import report_audit as ra
        rep = {'procedures': '', 'conclusion': [],
               'axes': [{'key': 'A', 'ordinal': 'أولاً', 'text': self.S},
                        {'key': 'B', 'ordinal': 'ثانياً',
                         'text': self.S + ' وهذه جملة أخرى مختلفة تماماً عن السابقة في كل شيء.'}]}
        out, gone = ra.dedupe(rep)
        self.assertEqual(len(gone), 1)
        self.assertEqual(gone[0][0], 'المحور ثانياً')
        self.assertEqual(out['axes'][1]['text'], 'وهذه جملة أخرى مختلفة تماماً عن السابقة في كل شيء.')
        self.assertEqual(out['axes'][0]['text'], self.S)
        import difflib
        other = 'ترى الخبرة أن المدعى عليه لم يلتزم بسداد الفواتير الشهرية في المواعيد المتفق عليها.'
        r = difflib.SequenceMatcher(None, self.S, other).ratio()
        self.assertTrue(0.6 < r < ra.DEDUP_MIN, r)
        near = dict(rep, axes=[rep['axes'][0], {'key': 'B', 'ordinal': 'ثانياً', 'text': other}])
        self.assertEqual(len(ra.dedupe(near)[1]), 0)                   # تشابه أقل من 95%: يبقى (يفحصه التدقيق)

    def test_tables_untouched(self):
        import report_audit as ra
        row = '| 1 | 94939904 | 581.670 |'
        rep = {'procedures': '', 'axes': [{'key': 'A', 'ordinal': 'أولاً', 'text': row},
                                          {'key': 'B', 'ordinal': 'ثانياً', 'text': row}]}
        self.assertEqual(ra.dedupe(rep)[0]['axes'][1]['text'], row)


class V3AxisRewriteTests(unittest.TestCase):
    """«إعادة كتابة هذا البند»: محور واحد بطلب خانات صغير، وبقية المحاور المدموجة لا تُمسّ."""

    def setUp(self):
        import case_facts
        import research_pipeline as rp
        import test_report_v3 as tr
        self.tr = tr
        self._tmp = tempfile.TemporaryDirectory()
        d = tr.case_data()
        self.base, self.data = cw.ensure_workspace({'caso_no': d['caso_no'], 'autocase_no': '', 'title': ''},
                                                   self._tmp.name)
        self.data.update(d)
        self.data['steps']['mission']['state'] = 'reviewed'
        self.data['steps']['documents']['state'] = 'done'
        self.patches = [mock.patch.object(case_facts, 'corpus', lambda base, data: tr.docs()),
                        mock.patch.object(rp, 'MINUTE_TEXTS', lambda recs: {r['path']: tr.MINUTE_TEXT.get(r['path'], [])
                                                                             for r in recs})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self._tmp.cleanup()

    def test_only_target_axis_rewritten(self):
        import report_v3
        import research_pipeline as rp
        report_v3.write_full(self.base, self.data, full_reply=self.tr.smart_slots())
        axes = rp.state(self.data)['axes']
        before = {a['key']: rp.section_text(self.base, a['sections'][0]) for a in axes}
        self.assertTrue(all(a['sections'][0]['state'] == rp.S_MERGED for a in axes))
        target = next(a['key'] for a in axes if a['key'].startswith('V2'))
        calls = []

        def ask(p):
            calls.append(p)
            return json.dumps({'slots': {f'{target}.opinion': 'ترى الخبرة أن المدعى عليه أخل بالتزامه بسداد الفواتير '
                                                              'الشهرية المستحقة عليه.'}}, ensure_ascii=False)
        rp.rewrite_axis(self.base, self.data, target, ask=ask)
        self.assertEqual(len(calls), 1)                                 # طلب خانات صغير واحد
        self.assertIn(f'{target}.opinion', calls[0])
        self.assertNotIn('V5_debt.opinion', calls[0])
        after = {a['key']: rp.section_text(self.base, a['sections'][0]) for a in rp.state(self.data)['axes']}
        for k in before:
            if k != target:
                self.assertEqual(after[k], before[k])                    # المدموج غيره لا يُمسّ
        self.assertIn('الفواتير الشهرية المستحقة عليه', after[target])
        sec = next(a for a in rp.state(self.data)['axes'] if a['key'] == target)['sections'][0]
        self.assertEqual(sec['state'], rp.S_MERGED)


class ReportsLocalFilterTests(unittest.TestCase):
    PENDING = [{'caso_no': 'A1', 'title': 'الالف ضد س', 'received_date': '2026-03-02'},
               {'caso_no': 'A2', 'title': 'ضد فلان', 'received_date': '2026-01-05'},
               {'caso_no': 'A3', 'title': 'شخص ضد ص', 'received_date': '2026-02-01'}]
    CO = {'شركة الألف للاتصالات': ['الالف'], 'باء': ['باء موبايل']}

    def test_fetch_once_then_filter_locally(self):
        import telecom_reports as tr
        calls, ready, done = [], [], []

        def parse(n, ck):
            calls.append(n)
            return {'plaintiffs': ['باء موبايل ش.م.ك'], 'defendants': ['فلان']}
        res = tr.fetch_all({}, self.CO, pending_fn=lambda c: self.PENDING, parse_fn=parse, saved_fn=lambda n: [],
                           on_ready=lambda r: ready.append([c['caso_no'] for c in r['all'] if c['resolved']]),
                           on_case=done.append)
        self.assertEqual(ready, [['A1', 'A3']])                         # العنوان الواضح يظهر فوراً
        self.assertEqual([c['caso_no'] for c in done], ['A2'])          # الغامض فور تحديده
        self.assertEqual(calls, ['A2'])
        tele = tr.filter_cases(res, True)
        everyone = tr.filter_cases(res, False)
        self.assertEqual([c['caso_no'] for c in tele['cases']], ['A2', 'A1'])
        self.assertEqual(len(everyone['cases']), 3)
        self.assertEqual(calls, ['A2'])                                 # التبديل: لا طلب إضافي

    def test_page_toggle_does_not_refetch(self):
        app = APP
        import qt_expert_reports as er
        import telecom_reports as tr
        n = []
        real_fetch = tr.fetch_all

        def fake_fetch(cookies, on_ready=None, on_case=None, stop=None, **k):
            n.append(1)
            res = real_fetch(cookies, self.CO, pending_fn=lambda c: self.PENDING,
                               parse_fn=lambda *a: {'plaintiffs': ['باء موبايل'], 'defendants': []},
                               saved_fn=lambda x: [], on_ready=on_ready, on_case=on_case)
            return res
        with mock.patch.object(tr, 'fetch_all', side_effect=fake_fetch), \
                mock.patch.object(er.rlm, 'build_card', side_effect=lambda c: {'case': c, 'caso_no': c['caso_no'],
                                                                              'autocase_no': '', 'plaintiff': '',
                                                                              'defendant': '', 'other_party': '',
                                                                              'company': c['company'], 'base': '',
                                                                              'in_progress': False, 'needs_me': False}), \
                mock.patch.object(er.ExpertReportsPage, '_render_list', lambda self, *a: None), \
                mock.patch.object(er.ExpertReportsPage, '_render_header', lambda self, *a: None), \
                mock.patch.object(er, '_save_only_telecom'):
            page = er.ExpertReportsPage({'c': 1}, 'خبير')
            page.only_telecom = True
            page.reload()
            import time
            end = time.time() + 5
            while (page._all is None or any(not c['resolved'] for c in page._all['all'])) and time.time() < end:
                app.processEvents()
                time.sleep(0.01)
            page._apply_filter()
            self.assertEqual(len(page._cards), 2)
            page._set_mode(False)
            self.assertEqual(len(page._cards), 3)
            page._set_mode(True)
            self.assertEqual(len(page._cards), 2)
            self.assertEqual(len(n), 1)                                  # جلب واحد للجلسة
            _dispose(page)


class PendingFilterReuseTests(unittest.TestCase):
    def test_filter_shows_hides_without_rebuilding(self):
        import qt_pending_page_v2 as qp
        a = {'caso_no': 'A1', 'title': 'س ضد ص', 'received_date': '2026-10-06', 'autocase_no': '1'}
        b = {'caso_no': 'A2', 'title': 'دعوى', 'received_date': '2026-10-07', 'autocase_no': '2'}
        with mock.patch.object(qp, 'claim_summary_initial', return_value=('skip', '')), \
                mock.patch.object(qp.case_db, 'get_case', return_value=None), \
                mock.patch.object(qp.mo, '_MOTION', False):
            page = qp.PendingCasesPage({'s': '1'}, 'خبير')
            page._cases, page._reserved_map = [a, b], {'A2': b}
            page._render_cases()
            cards = {c: w for _t, _h, items in page._groups for c, w in items}
            with mock.patch.object(qp, 'PendingCaseCard', side_effect=AssertionError('أُعيد البناء')):
                page._set_filter('reserved')
                self.assertFalse(cards['A1'].isVisibleTo(page.scroll_content))
                self.assertTrue(cards['A2'].isVisibleTo(page.scroll_content))
                page._set_filter('all')
                self.assertTrue(cards['A1'].isVisibleTo(page.scroll_content))
            _dispose(page)


class CloudFileTests(Base):
    def test_ui_scan_never_reads_cloud_file_and_sync_hydrates(self):
        import cloud_files
        p = os.path.join(self.base, cf.OTHER, 'c.txt')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('نص')
        cloud_files.ATTRS = lambda path: cloud_files.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS if path == p else 0
        try:
            with mock.patch.object(cf, 'sha1', side_effect=AssertionError('قُرئ الملف السحابي من خيط الواجهة')):
                rows = cf.scan(self.base, {}, hydrate=False)
            self.assertTrue(rows[f'{cf.OTHER}/c.txt']['cloud'])
            read = []
            real = cloud_files.ensure_local
            with mock.patch.object(cloud_files, 'ensure_local', side_effect=lambda path, st=None: read.append(path) or real(path)):
                got = cf.scan(self.base, {})
            self.assertEqual(read, [p])
            self.assertTrue(got[f'{cf.OTHER}/c.txt']['sha1'])
        finally:
            cloud_files.ATTRS = None

    def test_download_message(self):
        import cloud_files
        p = os.path.join(self._tmp.name, 'x.bin')
        with open(p, 'wb') as f:
            f.write(b'0' * 10)
        seen = []
        cloud_files.ATTRS = lambda path: cloud_files.FILE_ATTRIBUTE_OFFLINE
        try:
            self.assertTrue(cloud_files.ensure_local(p, seen.append))
        finally:
            cloud_files.ATTRS = None
        self.assertEqual(seen, ['جاري تنزيل الملف من OneDrive: x.bin'])
        self.assertEqual(cloud_files.current(), '')


class QueueCapTests(unittest.TestCase):
    def setUp(self):
        import gemini_quota as gq
        import summary_queue as sq
        self.sq, self.gq = sq, gq
        self._tmp = tempfile.TemporaryDirectory()
        sq.PATH_OVERRIDE = os.path.join(self._tmp.name, 's.json')
        gq.INI_OVERRIDE = {'queue_cases_per_day': '2'}

    def tearDown(self):
        self.sq.PATH_OVERRIDE = self.sq.PROCESS = self.sq.ROOM = None
        self.gq.INI_OVERRIDE = None
        self._tmp.cleanup()

    def _drain(self, cases):
        import threading
        done, order, gate = threading.Event(), [], threading.Event()
        left = [len(cases)]

        def proc(case, cookies):
            gate.wait(5)
            order.append(case['caso_no'])
            return 'ملخص'

        def cb(_s):
            left[0] -= 1
            if left[0] <= 0:
                done.set()
        self.sq.PROCESS = proc
        hold = {'caso_no': 'HOLD', 'received_date': '2099-01-01'}         # يشغل العامل حتى تُضاف البقية
        self.sq.enqueue(hold, None, lambda s: None)
        for c in cases:
            self.sq.enqueue(c, None, cb)
        gate.set()
        self.assertTrue(done.wait(5))
        return order

    def test_newest_first_and_daily_cap(self):
        self.gq.INI_OVERRIDE = {'queue_cases_per_day': '3'}
        cases = [{'caso_no': f'Q{i}', 'received_date': d} for i, d in
                 enumerate(('2026-01-01', '2026-09-01', '2026-05-01'))]
        order = self._drain(cases)
        self.assertEqual(order, ['HOLD', 'Q1', 'Q2'])                    # الأحدث أولاً، ثم توقف عند 3 قضايا
        self.assertEqual(self.sq.daily_left(), 0)
        self.assertFalse(self.sq.enqueue({'caso_no': 'Q9'}, None))       # السقف اليومي: لا إضافة
        self.assertFalse(self.sq.recently_failed(cases[0]))              # الموقوف بالسقف ليس فاشلاً: يُعاد غداً

    def test_stops_at_lite_share(self):
        self.gq.INI_OVERRIDE = {'queue_cases_per_day': '40'}
        self.sq.ROOM = lambda: False
        sent = []
        self.sq.PROCESS = lambda case, ck: sent.append(case) or 'ملخص'
        import threading
        ev = threading.Event()
        self.sq.enqueue({'caso_no': 'R1'}, None, lambda s: ev.set())
        self.assertTrue(ev.wait(5))
        self.assertEqual(sent, [])


class LogIsolationTests(unittest.TestCase):
    def test_logs_go_to_temp_dir_under_tests(self):
        import ai_call_log
        import app_paths
        import gemini_config as gc
        import gemini_quota as gq
        d = os.environ.get(app_paths.ENV)
        self.assertTrue(d and os.path.isdir(d))
        real = os.path.join(os.environ.get('LOCALAPPDATA') or '', 'ExpertApp')
        with mock.patch.object(ai_call_log, 'PATH_OVERRIDE', None), mock.patch.object(gq, 'PATH_OVERRIDE', None):
            paths = (ai_call_log.log_path(), gq._path(), gc._caps_path(), gc._models_cache_path())
        for p in paths + (gc._LOG_PATH,):
            self.assertTrue(p.startswith(d), p)
            self.assertFalse(p.startswith(real + os.sep), p)


if __name__ == '__main__':
    unittest.main()
