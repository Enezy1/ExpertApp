# اختبارات دفعة الأجزاء الخمسة (2026-10-18): python -W ignore -m unittest test_five_parts -v
import json
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication

import case_folder
import case_workspace as cw
import qt_case_page as qp
qp.CasePageDialog.AUTO_SYNC = False
qp.CasePageDialog.AUTO_ASK_TYPE = False
qp.CasePageDialog.AUTO_PROCEDURES = False

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)
APP = QApplication.instance() or QApplication([])


# ---------- الجزء 1: رسائل الحالة ----------

class BriefStatusTests(unittest.TestCase):
    def test_short_line_and_details(self):
        fs = {'converted': 0, 'failed': [['محاضر/a.pdf', 'الملف تالف']],
              'count': {'unconverted': [['محاضر/a.pdf', 'الملف تالف'], ['مستندات_أخرى/b.doc', 'يحتاج Word']]}}
        b = case_folder.brief_status(fs)
        self.assertEqual(b['line'], 'تعذّر تحويل ملفين')
        self.assertTrue(b['bad'])
        self.assertEqual(b['details'], [('a.pdf', 'الملف تالف'), ('b.doc', 'يحتاج Word')])
        self.assertNotIn('تالف', b['line'])

    def test_ready_and_plural(self):
        self.assertEqual(case_folder.brief_status({})['line'], 'جاهز')
        self.assertEqual(case_folder.files_word(3), '3 ملفات')
        self.assertEqual(case_folder.files_word(12), '12 ملفاً')
        b = case_folder.brief_status({'converted': ['x', 'y', 'z']})
        self.assertEqual(b['line'], 'حوّلتُ 3 ملفات جديداً')
        self.assertFalse(b['bad'])


class FolderRowUiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, _ = cw.ensure_workspace(CASE, self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_one_line_with_details_and_retry(self):
        dlg = qp.CasePageDialog(self.base, cw.read_case_json(self.base))
        self.assertFalse(dlg.details_btn.isVisibleTo(dlg))
        dlg._brief = case_folder.brief_status({'count': {'unconverted': [[f'x/{i}.pdf', 'سبب طويل جداً'] for i in range(5)]}})
        dlg._folder_msg = dlg._brief['line']
        dlg._show_folder_line()
        self.assertEqual(dlg.folder_line.text(), 'حالة الملفات: تعذّر تحويل 5 ملفات')
        self.assertTrue(dlg.details_btn.isVisibleTo(dlg) and dlg.retry_btn.isVisibleTo(dlg))
        self.assertIn('• 0.pdf: سبب طويل جداً', dlg.folder_details_text())
        calls = []
        dlg.sync_folder = lambda *a, **k: calls.append(1)
        dlg.retry_btn.click()
        self.assertEqual(calls, [1])
        dlg.done(0)


# ---------- الجزء 2: إضافة مستندات القضية ----------
import threading
import time

import case_documents as cd
import doc_router
import qt_documents_dialog as qd
qd.DocumentsDialog.PORTFOLIO_ASK = staticmethod(lambda p: "{}")      # لا شبكة في الاختبارات

FIRST = ("حافظة مستندات مقدمة من الشركة المدعية بجلسة 12/05/2026\n"
         "عقد توريد وتركيب أبرم بين شركة الأفق للمقاولات و شركة النور للتجارة بتاريخ 03/02/2025")


def spin(cond, secs=10):
    end = time.time() + secs
    while not cond() and time.time() < end:
        APP.processEvents()
        time.sleep(0.02)
    APP.processEvents()
    assert cond(), 'انتهت المهلة'


class ContentMetaTests(unittest.TestCase):
    def test_kind_date_parties_from_content_not_name(self):
        m = cd.content_meta("ملحق رقم 2 للعقد\nالطرف الأول: وزارة الأشغال\nالطرف الثاني: شركة الخليج\n"
                            "حرر بتاريخ 15/03/2024")
        self.assertEqual(m['kind'], 'ملحق')
        self.assertEqual(m['date'], '2024-03-15')
        self.assertIn('وزارة الأشغال', m['parties'])
        self.assertIn('شركة الخليج', m['parties'])
        self.assertFalse(cd.content_meta("نص لا يدل على شيء")['known'])

    def test_suggest_portfolio(self):
        who, when = cd.suggest_portfolio(FIRST)
        self.assertEqual(who, 'الشركة المدعية')
        self.assertEqual(when, '2026-05-12')

    def test_batch_progress(self):
        data = {'portfolios': [{'id': 'P1', 'docs': [
            {'uid': 'a', 'orig_name': 'a.pdf', 'convert': {'state': 'done'}},
            {'uid': 'b', 'orig_name': 'b.pdf', 'convert': {'state': 'running', 'progress': 50}},
            {'uid': 'c', 'orig_name': 'c.pdf', 'convert': {'state': 'pending'}}]}]}
        pm = cd.batch_progress(data)
        self.assertEqual((pm['done'], pm['total'], pm['percent']), (1, 3, 50))
        self.assertEqual(pm['files'][1], ('b.pdf', 'running', 50))


class AutoDialogTests(unittest.TestCase):
    def setUp(self):
        self._old, self._auto = cd.CLASSIFIER, qd.DocumentsDialog.AUTO_RUN
        qd.DocumentsDialog.AUTO_RUN = True
        cd.CLASSIFIER = lambda p: {'type': 'حافظة مستندات', 'confidence': 1.0, 'reason': 'اختبار',
                                   'snippet': FIRST if os.path.basename(p).startswith('a') else 'سطر غامض'}
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, os.path.join(self._tmp.name, 'ws'))
        self.src = os.path.join(self._tmp.name, 'src')
        os.makedirs(self.src)

    def tearDown(self):
        cd.CLASSIFIER, qd.DocumentsDialog.AUTO_RUN = self._old, self._auto
        spin(lambda: qd.active_job(self.base) is None)
        self._tmp.cleanup()

    def f(self, name):
        p = os.path.join(self.src, name)
        with open(p, 'wb') as fh:
            fh.write(name.encode())
        return p

    def test_pick_starts_everything_and_asks_once(self):
        def conv(path):
            doc_router.page_progress(1, 2)
            return '<!-- صفحة 1 -->\nنص', 1
        asked = []
        dlg = qd.DocumentsDialog(self.base, self.data, convert=conv)
        self.assertEqual(dlg.windowTitle(), 'إضافة مستندات القضية')
        self.assertFalse(dlg.import_btn.isVisibleTo(dlg))
        dlg.ASK_UNKNOWN = lambda docs: (asked.append([d['orig_name'] for d in docs]) or ({docs[0]['uid']: 'كتاب'}, {}))
        dlg.add_paths([self.f('a.pdf'), self.f('z.pdf')])           # بلا أي زر
        spin(lambda: qd.active_job(self.base) is None and bool(asked))
        self.assertEqual(dlg.total_lbl.text(), '2 من 2')
        p = self.data['portfolios'][0]
        self.assertEqual((p['submitter'], p['date']), ('الشركة المدعية', '2026-05-12'))   # مقترحان من الصفحة الأولى
        self.assertEqual(dlg.submitter.text(), 'الشركة المدعية')
        docs = {d['orig_name']: d for d in p['docs']}
        self.assertEqual(docs['a.pdf']['convert']['state'], 'done')
        self.assertEqual(docs['a.pdf']['kind'], 'حافظة')
        self.assertEqual(asked, [['z.pdf']])                        # سؤال واحد لما لم يتضح
        self.assertEqual(docs['z.pdf']['kind'], 'كتاب')
        self.assertFalse(dlg._ask_unknown_once())                   # لا يُسأل ثانية
        self.assertEqual(len(asked), 1)
        dlg.submitter.setText('المدعى عليها')                     # التعديل يُحفظ
        dlg._portfolio_edited()
        self.assertEqual(cw.read_case_json(self.base)['portfolios'][0]['submitter'], 'المدعى عليها')
        dlg.done(0)

    def test_close_keeps_running_and_page_progress(self):
        gate = threading.Event()

        def slow(path):
            doc_router.page_progress(1, 4)
            gate.wait(5)
            return '<!-- صفحة 1 -->\nنص', 1
        dlg = qd.DocumentsDialog(self.base, self.data, convert=slow)
        dlg.ASK_UNKNOWN = lambda docs: ({}, {})
        self.f('a.pdf')
        dlg.add_paths([self.src])                                    # مجلد كامل بالسحب

        def state_text():
            it = dlg.table.item(0, qd.C_STATE)
            return it.text() if it else ''
        spin(lambda: 'جارٍ التحويل 25%' in state_text())
        spin(lambda: '25%' in dlg.files_lbl.text())
        dlg.done(0)                                                  # لا سؤال
        self.assertIsNotNone(qd.active_job(self.base))
        gate.set()
        spin(lambda: qd.active_job(self.base) is None)
        self.assertEqual(cw.read_case_json(self.base)['portfolios'][0]['docs'][0]['convert']['state'], 'done')


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)

    def tearDown(self):
        spin(lambda: qd.active_job(self.base) is None)
        self._tmp.cleanup()

    def test_interrupted_resumes_on_open_without_message(self):
        p = cd.add_portfolio(self.data, 'المدعية', '2026-01-01')
        src = os.path.join(self._tmp.name, 'x.md')
        with open(src, 'w', encoding='utf-8') as fh:
            fh.write('نص')
        rel = case_folder.add_original(self.base, src, case_folder.OTHER)
        p['docs'].append({'uid': 'd1', 'no': 1, 'seq': 1, 'file': rel, 'md': case_folder.md_rel(rel),
                          'orig_name': 'x.md', 'type': '', 'contract': '', 'pages': 0, 'sha1': '', 'src_sha1': '',
                          'origin': 'converted', 'engine': doc_router.ENGINE_TEXT,
                          'convert': {'state': 'running', 'message': ''}})
        self.data['steps']['documents']['state'] = 'running'
        cw.write_case_json(self.base, self.data)
        dlg = qp.CasePageDialog(self.base, cw.read_case_json(self.base))
        self.assertIsNone(dlg.add_docs_btn)                  # لا زر في الرأس: الإضافة من خطوة المستندات
        self.assertNotIn('انقطعت', json.dumps(dlg.data, ensure_ascii=False))
        spin(lambda: qd.active_job(self.base) is None and
             cw.read_case_json(self.base)['portfolios'][0]['docs'][0]['convert']['state'] == 'done')
        self.assertFalse(dlg.resume_failed)
        dlg.done(0)


# ---------- الجزء 3: العقود ----------
import case_contracts as cc
import case_subject_ai as sa

CONTRACT_MD = ("<!-- صفحة 1 -->\nعقد مقاولة من الباطن\nأبرم هذا العقد بتاريخ 19/4/2018 بين شركة الأفق للمقاولات "
               "و شركة النور للتجارة\nبقيمة 1,250,000 د.ك ومدته 18 شهراً\n"
               "<!-- صفحة 2 -->\nالعقد الرئيسي مع وزارة الأشغال العامة المؤرخ 01/01/2017 بقيمة 9,000,000 د.ك")
REPLY = {'contracts': [
    {'kind': 'عقد بين الطرفين', 'date': '19/04/2018', 'parties': ['شركة الأفق للمقاولات', 'شركة النور للتجارة'],
     'scope': 'أعمال التأثيث', 'value': '1250000 د.ك', 'duration': '18 شهراً', 'doc': 'D1', 'page': 1,
     'between_litigants': True},
    {'kind': 'عقد رئيسي', 'date': '01/01/2017', 'parties': ['وزارة الأشغال العامة', 'شركة النور للتجارة'],
     'scope': 'إنشاء مبنى', 'value': '9,000,000 د.ك', 'doc': 'D1', 'page': 2},
    {'kind': 'ملحق', 'date': '05/05/2019', 'parties': ['شركة الأفق للمقاولات', 'شركة النور للتجارة'],
     'value': '77,000', 'doc': 'D1', 'page': 1}]}


class ContractsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        self.data['case'] = dict(self.data.get('case') or {}, plaintiffs=['شركة الأفق للمقاولات'],
                                 defendants=['شركة النور للتجارة'])
        src = os.path.join(self._tmp.name, 'عقد.txt')
        with open(src, 'w', encoding='utf-8') as fh:
            fh.write(CONTRACT_MD)
        case_folder.add_original(self.base, src, case_folder.OTHER)
        case_folder.sync_case_folder(self.base, self.data)
        self.calls = []

    def tearDown(self):
        self._tmp.cleanup()

    def ask(self, prompt):
        self.calls.append(prompt)
        return json.dumps(REPLY, ensure_ascii=False)

    def test_literal_checks(self):
        self.assertTrue(cc.date_in_text('19/04/2018', 'بتاريخ ١٩/٤/٢٠١٨ م'))
        self.assertFalse(cc.date_in_text('19/05/2018', 'بتاريخ 19/4/2018'))
        self.assertTrue(cc.amount_in_text('1250000 د.ك', 'بقيمة 1,250,000 د.ك'))
        self.assertFalse(cc.amount_in_text('77,000', 'بقيمة 1,250,000'))

    def test_extract_scope_verify_store(self):
        res = cc.extract(self.base, self.data, self.ask)
        self.assertEqual(len(self.calls), 1)
        self.assertIn('شركة الأفق', self.calls[0])
        by = {c['kind']: c for c in res['items']}
        self.assertEqual(by['عقد بين الطرفين']['scope'], cc.SCOPE_IN)
        self.assertTrue(by['عقد بين الطرفين']['verified'])
        self.assertEqual(by['عقد رئيسي']['scope'], cc.SCOPE_MAIN)
        self.assertEqual(by['ملحق']['checks'], {'date': False, 'value': False, 'page': True})   # يُعلَّم أحمر
        self.assertFalse(by['ملحق']['verified'])
        md = open(os.path.join(self.base, cc.CONTRACTS_NAME), encoding='utf-8').read()
        self.assertIn('العقود المبرمة بين طرفي الدعوى', md)
        self.assertIn('⚠غير متحقَّق', md)
        idx = open(os.path.join(self.base, '_نظام', 'فهرس_المستندات.md'), encoding='utf-8').read()
        self.assertIn('مستخرجة ومتحقَّق منها', idx)
        cc.extract(self.base, self.data, self.ask)                   # النص لم يتغيّر: لا طلب ثانٍ
        self.assertEqual(len(self.calls), 1)

    def test_subject_reads_contracts_only_verified_in_scope(self):
        cc.extract(self.base, self.data, self.ask)
        text, allowed = cc.subject_context(self.data)
        self.assertIn('19/04/2018', text)
        self.assertNotIn('9,000,000', text)                          # الرئيسي لا يدخل السرد
        self.assertNotIn('05/05/2019', text)                         # غير المتحقَّق لا يدخل
        prompts = []

        def ask(p):
            prompts.append(p)
            return json.dumps({'claim': 'الحكم بإلزام المدعى عليها بأن تؤدي مبلغ 5000 د.ك', 'text': ''})
        plaint = 'تطلب المدعية الحكم بإلزام المدعى عليها بأن تؤدي مبلغ 5000 د.ك'
        out = sa.build_subject(plaint, ['شركة النور للتجارة'], ask, plaintiffs=['شركة الأفق للمقاولات'],
                               contracts=self.data)
        self.assertIn('العقود المستخرجة من مستندات القضية', prompts[0])
        self.assertTrue(out['contracts_used'])
        self.assertEqual(out['facts'].get('contract_date'), '19/04/2018')

    def test_case_without_parties_trusts_plaint_and_gives_reason(self):
        """قضية A2263973: بيانات القضية بلا أطراف ← لا يُحكم «خارج النطاق» على عقود بين الطرفين."""
        self.data['case'] = {'plaintiff': '', 'defendants': [], 'company': ''}
        plaint = os.path.join(self._tmp.name, 'صحيفة.txt')
        with open(plaint, 'w', encoding='utf-8') as fh:
            fh.write('<!-- صفحة 1 -->\nالمدعية شركة الاتصالات المتنقلة (زين) ضد عبد الرحمن فهد الخراز\n'
                     'وتطلب المدعية الحكم بإلزام المدعى عليه بأن يؤدي مبلغ 1,155.770 د.ك عن التعاقد رقم 94939904')
        case_folder.add_original(self.base, plaint, case_folder.PLAINT)
        case_folder.sync_case_folder(self.base, self.data)
        reply = {'plaintiffs': ['شركة الاتصالات المتنقلة (زين)'], 'defendants': ['عبد الرحمن فهد الخراز'],
                 'claim': 'الحكم بإلزام المدعى عليه بأن يؤدي مبلغ 1,155.770 د.ك',
                 'contracts': [{'kind': 'عقد بين الطرفين', 'date': '19/04/2018',
                                'parties': ['شركة الاتصالات المتنقلة ش.م.ك.', 'عبد الرحمن فهد عبد الرحمن الخراز'],
                                'scope': 'خط رقم 94939904', 'doc': 'D1', 'between_litigants': True, 'in_claim': True},
                               {'kind': 'عقد رئيسي', 'date': '01/01/2017',
                                'parties': ['وزارة الأشغال العامة', 'شركة الاتصالات المتنقلة ش.م.ك.'], 'doc': 'D1'}]}
        res = cc.extract(self.base, self.data, lambda p: json.dumps(reply, ensure_ascii=False))
        self.assertEqual(res['claim'], reply['claim'])                      # طلبات المدعية من الصحيفة حرفياً
        a, b = cc.items(self.data)
        self.assertEqual((a['scope'], a['in_plaint']), (cc.SCOPE_IN, True))
        self.assertEqual(b['scope'], cc.SCOPE_MAIN)
        self.assertIn('وزارة الأشغال العامة', b['scope_reason'])           # لا تصنيف خارجي بلا سبب
        txt, _ = qp.CasePageDialog.contract_text(b)
        self.assertIn('السبب:', txt)
        idx = open(os.path.join(self.base, '_نظام', 'فهرس_المستندات.md'), encoding='utf-8').read()
        self.assertEqual(cc.items(self.data)[0]['scope'], cc.SCOPE_IN)      # الفهرس لا يفسد التصنيف

    def test_docs_split_by_content(self):
        d = {'portfolios': [{'id': 'P1', 'submitter': 'المدعية', 'docs': [
            {'uid': 'a', 'no': 1, 'orig_name': 'scan001.pdf', 'file': 'x', 'md': '', 'kind': 'ملحق',
             'doc_date': '2019-05-05', 'parties': ['شركة الأفق'], 'convert': {'state': 'done'}},
            {'uid': 'b', 'no': 2, 'orig_name': 'scan002.pdf', 'file': 'y', 'md': '', 'convert': {'state': 'failed'}}]}]}
        have, miss = qp.docs_split(d)
        self.assertEqual(have[0]['title'], 'ملحق بتاريخ 2019-05-05 — شركة الأفق')
        self.assertNotIn('scan', miss[0]['title'])

    def test_unverified_contract_red_on_card(self):
        cc.extract(self.base, self.data, self.ask)
        c = next(c for c in qp.contracts(self.data) if c['kind'] == 'ملحق')
        _text, bad = qp.CasePageDialog.contract_text(c)
        self.assertIn('لم يُتحقق من التاريخ والقيمة', bad)


# ---------- الجزء 4: تاريخ الحجز من المحاضر ----------
import case_minutes_ai as mai
import case_procedures as cp


class BookingTests(unittest.TestCase):
    M = [{'path': 'p2', 'name': '2.docx', 'no': 2}, {'path': 'p3', 'name': '3.docx', 'no': 3}]

    def test_rules_take_latest_minute(self):
        texts = {'p2': ['محضر رقم 2 بتاريخ 01/03/2026', 'تأجيل لجلسة لاحقة'],
                 'p3': ['محضر رقم 3', 'وعليه تم حجز الدعوى للتقرير بتاريخ ١٥/٠٣/٢٠٢٦']}
        got = mai.booking_from_minutes(self.M, texts)
        self.assertEqual(got['date'], '2026-03-15')
        self.assertEqual(got['note'], 'مأخوذ من المحضر رقم 3')
        self.assertEqual(got['method'], 'rules')

    def test_ai_only_with_literal_evidence(self):
        items = [{'ref': 'M1', 'name': '3.docx', 'path': 'p3',
                  'text': 'قررنا حجز الأوراق لإعداد التقرير وذلك في 20/04/2026 بحضور الطرفين'}]
        good = {'minutes': [{'ref': 'M1', 'number': 3, 'booking': {
            'date': '20/04/2026', 'evidence': 'قررنا حجز الأوراق لإعداد التقرير'}}]}
        recs, _bad = mai.verify(good, items, [])
        self.assertEqual(recs[0]['booking'], '2026-04-20')
        fake = {'minutes': [{'ref': 'M1', 'number': 3, 'booking': {'date': '21/04/2026', 'evidence': 'قررنا حجز الأوراق لإعداد التقرير'}}]}
        recs, bad = mai.verify(fake, items, [])
        self.assertEqual(recs[0]['booking'], '')                       # التاريخ لا يرد في المحضر
        self.assertTrue(any('الحجز' in b for b in bad))
        got = mai.booking_from_minutes([{'path': 'p3', 'name': '3.docx', 'no': 3}],
                                       {'p3': [items[0]['text']]}, {'records': [dict(recs[0], booking='2026-04-20')]})
        self.assertEqual((got['date'], got['method']), ('2026-04-20', 'ai'))

    def test_check_line_shows_source(self):
        d = {'procedures': {'booked': {'date': '2026-03-15', 'source': 'المحضر', 'note': 'مأخوذ من المحضر رقم 3'}},
             'sessions': {}}
        line = next(c for c in cp.build_checks(d) if c['key'] == 'booked')
        self.assertTrue(line['ok'])
        self.assertIn('مأخوذ من المحضر رقم 3', line['text'])


# ---------- الجزء 5: الإعدادات ----------
from unittest import mock

import expert_settings as es


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, 'cases')
        self.old = os.path.join(self._tmp.name, 'old_minutes')
        self.p = [mock.patch('expert_settings.load_reports_root', lambda: self.root),
                  mock.patch('expert_settings.load_minutes_root', lambda: self.old)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()
        self._tmp.cleanup()

    def test_minutes_inside_case_folder_old_read_only(self):
        self.assertEqual(es.case_minutes_dir('A1'), os.path.join(self.root, 'A1', 'مستندات_النظام'))
        self.assertEqual(es.minutes_read_dirs('A1'), [os.path.join(self.root, 'A1', 'مستندات_النظام'),
                                                      os.path.join(self.root, 'A1', 'محاضر'), os.path.join(self.old, 'A1')])

    def test_sessions_page_reads_both(self):
        import qt_sessions_page as sp
        for d, n in ((es.case_minutes_dir('A1'), '2.docx'), (os.path.join(self.old, 'A1'), '1.docx')):
            os.makedirs(d)
            open(os.path.join(d, n), 'wb').close()
        self.assertEqual(sorted(sp._mahdar_files('A1')), ['1.docx', '2.docx'])

    def test_path_field_opens_folder_dialog(self):
        import qt_settings_page as qs
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest
        e = qs._path_edit('ph', '', 'اختر')
        with mock.patch.object(qs.QFileDialog, 'getExistingDirectory', return_value=self.root) as m:
            QTest.mouseClick(e, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
        m.assert_called_once()
        self.assertEqual(e.text(), os.path.normpath(self.root))

    def test_single_setting_card(self):
        import qt_settings_page as qs
        src = open(qs.__file__, encoding='utf-8').read()
        self.assertIn('مجلد حفظ مستندات القضايا', src)
        self.assertNotIn('c_lay.addWidget(self._build_minutes_root_card())', src)
        self.assertIn('self.update_folder_entry = _path_edit(', src)


if __name__ == '__main__':
    unittest.main()
