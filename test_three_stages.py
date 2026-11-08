# اختبارات «المراحل الثلاث» (2026-10-21): python -W ignore -m unittest test_three_stages -v
# (1) الفرز: كل ملف = طلب ذكاء واحد (مدمج في تحويل الممسوح)، وإعادة الفتح بلا تغيير = صفر طلبات.
# (2) الموضوع والإجراءات والمرفقات بطلب واحد، ولا كتابة بلا صحيفة، والفشل يظهر سبباً وأزراراً.
# (3) البحث بطلب واحد وإعادة واحدة فقط للمرفوض. (4) مسار المتصفح يمر على نفس التحقق.
import json
import os
import re
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import ai_call_log
import case_folder as cf
import case_sort as cs
import case_stage2
import case_startup as st
import case_triage as ct
import case_workspace as cw
import doc_router as dr
import test_qt_case_page as tp

CASE = tp.CASE
PAGE_N = re.compile(r'عدد صفحات الملف (\d+)')
LIMITS = {'max_pages': 1000, 'max_bytes': 50 * 1024 * 1024, 'chunk_pages': 0, 'batch_pages': 20, 'retries': 0,
          'retry_wait': 0}


def make_pdf(path, n):
    import fitz
    doc = fitz.open()
    for i in range(n):
        doc.new_page().insert_text((72, 72), f'page {i + 1}')
    doc.save(path)
    doc.close()


def page_text(i, mixed):
    if i == 1:
        return ('حافظة مستندات المدعية بتاريخ 15/10/2025\nمستند رقم (1) عقد اشتراك مؤرخ 01/02/2024 بقيمة 1,200.000 د.ك')
    if mixed and i == 41:
        return 'مذكرة بدفاع المدعى عليه بتاريخ 02/04/2026\nيدفع المدعى عليه بانقضاء العقد بالإلغاء قبل المطالبة'
    return f'الصفحة {i} من كشف الحساب: رصيد مستحق {i}.500 د.ك عن الفترة رقم {i}'


class FakeGemini:
    """جيميناي وهمي للتحويل وحده (2026-10-23): نص صفحات الدفعة بعلامة الفصل، بلا أي كتلة فرز."""
    task = ''

    def __init__(self, mixed=False):
        self.calls, self.mixed, self.done = [], mixed, 0

    def generate(self, prompt, prep, route, timeout):
        self.calls.append(prompt)
        n = int(PAGE_N.search(prompt).group(1))
        a, b = self.done + 1, self.done + n
        self.done = b
        return type('R', (), {'text': dr.PAGE_SEP.join(page_text(i, self.mixed) for i in range(a, b + 1))})()


class Counter:
    def __init__(self, reply='{"parts": []}'):
        self.calls, self.reply = [], reply

    def __call__(self, prompt):
        self.calls.append(prompt)
        return self.reply(prompt) if callable(self.reply) else self.reply


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        self._conv, self._fac = cf.CONVERTER, dr.GEMINI_PROVIDER_FACTORY

    def tearDown(self):
        cf.CONVERTER, dr.GEMINI_PROVIDER_FACTORY = self._conv, self._fac
        self._tmp.cleanup()

    def scanned(self, n=45, **kw):
        """ملف ممسوح في «أخرى» يُحوَّل بمحرّك جيميناي الحقيقي (الدفعات والفصل والحارس) ومزوّد وهمي."""
        self.fake = FakeGemini(**kw)
        dr.GEMINI_PROVIDER_FACTORY = lambda: self.fake
        engine = dr.gemini_engine(lambda path: ('محلي', 1), limits=dict(LIMITS))
        cf.CONVERTER = lambda path, kind: engine(path, {})[:2] + ('gemini',)
        make_pdf(os.path.join(self.base, cf.OTHER, 'scan.pdf'), n)


# ---------- (1) المرحلة الأولى ----------

class StageOneTests(Base):
    FULL = {'parts': [{'type': 'حافظة', 'pages': [1, 45], 'submitter_role': 'plaintiff', 'submitter_index': 1,
                       'date': '15/10/2025',
                       'documents': [{'no': '1', 'desc': 'عقد اشتراك', 'quote': 'مستند رقم (1) عقد اشتراك'}],
                       'contract': {'found': True, 'date': '01/02/2024', 'value': '1,200.000',
                                    'quote': 'عقد اشتراك مؤرخ 01/02/2024'}}]}

    def test_scanned_45_pages_converted_in_batches_then_one_triage_request(self):
        self.scanned(45)
        cf.sync_case_folder(self.base, self.data)
        self.assertEqual(len(self.fake.calls), 3)                     # 20 + 20 + 5
        self.assertNotIn('"parts"', ''.join(self.fake.calls))         # التحويل وحده: لا قالب فرز في طلب الصور
        md = open(os.path.join(self.base, 'markdown', cf.OTHER, 'scan.md'), encoding='utf-8').read()
        self.assertNotIn('```', md)
        self.assertEqual(md.count('<!-- صفحة '), 45)
        ask = Counter(json.dumps(self.FULL, ensure_ascii=False))
        cs.run(self.base, self.data, ask)
        self.assertEqual(len(ask.calls), 1)                           # طلب فرز نصي واحد للملف كله (text_light)
        self.assertIn('نص الملف', ask.calls[0])
        self.assertIn('الصفحة 45 من كشف الحساب', ask.calls[0])
        self.assertEqual(os.listdir(os.path.join(self.base, cf.PORTF)), ['حافظة مستندات المدعية 15-10-2025.pdf'])
        e = cf.load_manifest(self.base)['files']['حوافظ/حافظة مستندات المدعية 15-10-2025.pdf']
        self.assertEqual(e['triage']['source'], 'request')
        self.assertEqual(e['triage']['parts'][0]['documents'], [{'no': '1', 'desc': 'عقد اشتراك'}])
        ask.calls.clear()
        cs.run(self.base, self.data, ask)
        self.assertEqual(ask.calls, [])                               # البصمة نفسها: لا طلب ثانٍ

    def test_mixed_file_detected_by_triage_request(self):
        self.scanned(45, mixed=True)
        cf.sync_case_folder(self.base, self.data)
        reply = {'parts': [{'type': 'حافظة', 'pages': [1, 40], 'submitter_role': 'plaintiff', 'date': '15/10/2025'},
                           {'type': 'مذكرة', 'pages': [41, 45], 'submitter_role': 'defendant', 'submitter_index': 1,
                            'date': '02/04/2026'}]}
        cs.run(self.base, self.data, Counter(json.dumps(reply, ensure_ascii=False)))
        rel = 'أخرى/1 حافظة و1 مذكرة.pdf'
        f = self.data['sort']['files'][rel]
        self.assertEqual(f['state'], 'mixed')
        self.assertEqual([(p['type'], p['pages']) for p in f['parts']], [('حافظة', [1, 40]), ('مذكرة', [41, 45])])
        self.assertEqual(f['parts'][1]['label'], 'المدعى عليه')

    def test_adding_text_file_is_one_request_and_reopen_is_zero(self):
        tp_memo = '<!-- صفحة 1 -->\nمذكرة بدفاع المدعى عليه بتاريخ 02/04/2026\nيدفع المدعى عليه بانقضاء العقد'
        with open(os.path.join(self.base, cf.OTHER, 'm.txt'), 'w', encoding='utf-8') as f:
            f.write(tp_memo)
        reply = {'parts': [{'type': 'مذكرة', 'pages': [1, 1], 'submitter_role': 'defendant', 'date': '02/04/2026',
                            'defenses': [{'summary': 'انقضاء العقد بالإلغاء', 'quote': 'يدفع المدعى عليه بانقضاء العقد'}]}]}
        ask = Counter(json.dumps(reply, ensure_ascii=False))
        st.run(self.base, self.data, ask=ask, fetch=lambda k: [])
        self.assertEqual(len(ask.calls), 1)                           # ملف نصي = طلب فرز واحد
        self.assertTrue(os.path.exists(os.path.join(self.base, cf.MEMOS, 'مذكرة دفاع المدعى عليه 02-04-2026.txt')))
        summary = open(os.path.join(self.base, 'الملخص.md'), encoding='utf-8').read()
        self.assertIn('## محتوى المستندات', summary)
        self.assertIn('وجه دفاع: انقضاء العقد بالإلغاء', summary)
        ask.calls.clear()
        st.run(self.base, self.data, ask=ask, fetch=lambda k: [])
        self.assertEqual(ask.calls, [])                               # إعادة الفتح بلا تغيير = 0 طلبات

    def test_unverified_quotes_are_dropped(self):
        md = '<!-- صفحة 1 -->\nحافظة مستندات المدعية بتاريخ 15/10/2025\nمستند (1) فاتورة بمبلغ 20.000 د.ك'
        raw = {'parts': [{'type': 'حافظة', 'pages': [1, 1], 'submitter_role': 'plaintiff', 'date': '15/10/2025',
                          'amounts': [{'amount': '20.000', 'quote': 'فاتورة بمبلغ 20.000 د.ك'},
                                      {'amount': '99.000', 'quote': 'مبلغ 99.000 د.ك مختلق'}],
                          'attendance': {'present': [{'role': 'plaintiff', 'quote': 'حضر وكيل المدعية'}]}}]}
        parts, notes = ct.verify(self.data, raw, md)
        self.assertEqual([a['amount'] for a in parts[0]['amounts']], ['20.000'])
        self.assertEqual(parts[0]['attendance']['present'], [])
        self.assertTrue(any('99.000' in n for n in notes))


# ---------- (2) المرحلة الثانية ----------

class StageTwoTests(Base):
    def reply(self, **kw):
        r = dict(tp.STAGE2_REPLY, **kw)
        return Counter(json.dumps(r, ensure_ascii=False))

    def test_one_request_returns_subject_procedures_attachments(self):
        tp.stage1(self.base)
        data = cw.read_case_json(self.base)
        ask = self.reply(attachments=['مذكرة دفاع المدعى عليه المؤرخة 15/03/2024.'])
        case_stage2.run(self.base, data, ask)
        self.assertEqual(len(ask.calls), 1)
        p = ask.calls[0]
        for part in ('## ملخص القضية المتحقَّق', '## نماذج وقواعد صياغة الموضوع', '## قالب الإجراءات', '## بيانات النظام',
                     '"attachments"'):
            self.assertIn(part, p)
        self.assertEqual(data['subject'], tp.STAGE2_REPLY['subject'])
        self.assertEqual(data['procedures']['source'], 'stage2')
        self.assertTrue(data['procedures']['text'])
        self.assertEqual(data['attachments_ai']['items'], ['مذكرة دفاع المدعى عليه المؤرخة 15/03/2024.'])
        ask.calls.clear()
        case_stage2.run(self.base, data, ask)                         # إعادة الفتح بلا تغيير
        self.assertEqual(ask.calls, [])

    def test_bad_attachments_retried_once_then_built_by_code(self):
        tp.stage1(self.base)
        data = cw.read_case_json(self.base)
        ask = self.reply(attachments=['مذكرة غير معروفة التاريخ المؤرخة 01/01/2020.'])
        case_stage2.run(self.base, data, ask)
        self.assertEqual(len(ask.calls), 2)                           # إعادة واحدة للمرفوض وحده
        self.assertIn('أعد فقط المرفقات', ask.calls[1])
        self.assertIn('المرفقات: رُفضت', ' '.join(data['stage2']['notes']))  # بقي مرفوضاً ← بالكود

    def test_no_plaint_no_request_and_missing_list(self):
        ask = self.reply()
        s = case_stage2.run(self.base, self.data, ask)
        self.assertEqual(ask.calls, [])
        self.assertEqual(s['missing'], ['صحيفة الدعوى', 'حكم الإحالة', 'محاضر الخبرة'])
        text, red = case_stage2.status_line(self.base, self.data)
        self.assertTrue(red)
        self.assertIn('صحيفة الدعوى', text)

    def test_rejected_subject_retried_once_then_red_not_empty(self):
        tp.stage1(self.base)
        data = cw.read_case_json(self.base)
        bad = tp.STAGE2_REPLY['subject'].replace('15/03/2024', '16/03/2024')
        ask = self.reply(subject=bad)
        case_stage2.run(self.base, data, ask)
        self.assertEqual(len(ask.calls), 2)                           # الأول + إعادة واحدة فقط
        self.assertIn('رُفضت كتابتك السابقة', ask.calls[1])
        self.assertEqual(data['subject'], bad)                        # لا يُستبدل بنص فارغ
        self.assertIn('16/3/2024', ' '.join(data['subject_check']['errors']))
        self.assertEqual(data['steps']['subject']['state'], 'needs_input')

    def test_rerun_when_summary_changes_unless_manual(self):
        tp.stage1(self.base)
        data = cw.read_case_json(self.base)
        ask = self.reply()
        case_stage2.run(self.base, data, ask)
        with open(os.path.join(self.base, cf.OTHER, 'م.txt'), 'w', encoding='utf-8') as f:
            f.write('<!-- صفحة 1 -->\nمذكرة بدفاع المدعى عليه بتاريخ 02/04/2026')
        cf.sync_case_folder(self.base, data)
        cs.run(self.base, data, lambda p: json.dumps({'parts': [{'type': 'مذكرة', 'pages': [1, 1],
                                                               'submitter_role': 'defendant', 'date': '02/04/2026'}]}))
        self.assertTrue(case_stage2.needs_run(self.base, data))
        ask.calls.clear()
        case_stage2.run(self.base, data, ask)
        self.assertEqual(len(ask.calls), 1)                           # الملخص تغيّر ← طلب واحد تلقائياً
        data['subject_edited'] = True                                 # عدّل الخبير النص
        with open(os.path.join(self.base, cf.OTHER, 'ن.txt'), 'w', encoding='utf-8') as f:
            f.write('<!-- صفحة 1 -->\nحافظة مستندات المدعية بتاريخ 15/10/2025')
        cf.sync_case_folder(self.base, data)
        cs.run(self.base, data, lambda p: json.dumps({'parts': [{'type': 'حافظة', 'pages': [1, 1],
                                                               'submitter_role': 'plaintiff', 'date': '15/10/2025'}]}))
        ask.calls.clear()
        case_stage2.run(self.base, data, ask)
        self.assertEqual(ask.calls, [])                               # نص الخبير لا يُمسّ

    def test_procedures_gate_rejects_unproven_absence(self):
        tp.stage1(self.base)
        data = cw.read_case_json(self.base)
        _t, errs = case_stage2.check_procedures(self.base, data, 'استلمنا ملف الدعوى، وحددنا 3 جلسات وتخلف المدعى '
                                                                 'عليه عن الحضور رغم صحة إعلانه.')
        joined = ' '.join(errs)
        self.assertIn('عدة جلسات', joined)
        self.assertIn('التخلف لم يثبت', joined)
        self.assertIn('ذكرت عدد الجلسات', joined)


class SubjectFailureUiTests(Base):
    def setUp(self):
        super().setUp()
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        self.data['steps']['documents']['state'] = 'done'
        cw.write_case_json(self.base, self.data)
        tp.stage1(self.base)
        import qt_case_page as qp
        self.qp = qp
        self.saved = (qp.CasePageDialog.AUTO_SYNC, qp.CasePageDialog.OPEN_EXTERNAL, qp.CasePageDialog.AUTO_BROWSER)
        qp.CasePageDialog.AUTO_SYNC = qp.CasePageDialog.OPEN_EXTERNAL = qp.CasePageDialog.AUTO_BROWSER = False

    def tearDown(self):
        (self.qp.CasePageDialog.AUTO_SYNC, self.qp.CasePageDialog.OPEN_EXTERNAL,
         self.qp.CasePageDialog.AUTO_BROWSER) = self.saved
        super().tearDown()

    def labels(self, dlg):
        import qt_bidi
        return ' '.join(qt_bidi.strip_isolates(l.text()) for l in dlg.card.findChildren(self.qp.QLabel))

    def buttons(self, dlg):
        import qt_bidi
        from PyQt6.QtWidgets import QPushButton
        return {qt_bidi.strip_isolates(b.text()): b for b in dlg.card.findChildren(QPushButton)}

    def test_failure_shows_reason_and_buttons_then_browser_paste_is_verified(self):
        def boom(prompt):
            raise RuntimeError('انتهت الحصة اليومية')
        dlg = self.qp.CasePageDialog(self.base, cw.read_case_json(self.base), ask=boom)
        dlg.open_step('subject')
        dlg._rewrite('subject')
        tp.wait(dlg)
        self.assertIn('انتهت الحصة اليومية', self.labels(dlg))     # السبب بوضوح، لا خانة فارغة بصمت
        btns = self.buttons(dlg)
        self.assertIn('أعد الكتابة', btns)
        self.assertIn('جيميناي (API)', btns)
        btns['جيميناي (API)'].click()                                  # التبديل إلى «عبر المتصفح»
        btns = self.buttons(dlg)
        self.assertIn('اكتب عبر المتصفح', btns)
        self.assertIn('لصق الرد', btns)
        self.assertIn('عبر المتصفح', btns)
        btns['اكتب عبر المتصفح'].click()                               # يجهّز الطلب نفسه وينسخه للحافظة
        tp.wait(dlg)
        from PyQt6.QtGui import QGuiApplication
        self.assertIn('## ملخص القضية المتحقَّق', QGuiApplication.clipboard().text())
        bad = dict(tp.STAGE2_REPLY, subject=tp.STAGE2_REPLY['subject'].replace('436.750', '999.000'))
        dlg._browser_paste('stage2', json.dumps(bad, ensure_ascii=False))
        text, red = dlg._notice
        self.assertTrue(red)
        self.assertIn('999', text)                                    # نفس التحقق بالكود
        dlg._browser_paste('stage2', json.dumps(tp.STAGE2_REPLY, ensure_ascii=False))
        d = cw.read_case_json(self.base)
        self.assertEqual(d['subject'], tp.STAGE2_REPLY['subject'])
        self.assertEqual(d['written_by']['subject']['provider'], 'عبر المتصفح (Copilot)')
        self.assertEqual(d['ai_mode']['stage2'], 'browser')


# ---------- (3) المرحلة الثالثة ----------

class StageThreeTests(unittest.TestCase):
    def setUp(self):
        import test_report_v3 as tv3
        import research_pipeline as rp
        import case_facts as cfx
        self.tv3 = tv3
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(dict(CASE, caso_no='A2263973'), self._tmp.name)
        self.data.update({k: v for k, v in tv3.case_data().items() if k != 'caso_no'})
        import case_model as cm
        for k, seq in (('documents', ('running', 'done')), ('mission', ('running', 'done', 'reviewed'))):
            for x in seq:
                cm.set_step(self.data, k, x)
        self.patches = [mock.patch.object(cfx, 'corpus', lambda base, d: tv3.docs()),
                        mock.patch.object(rp, 'MINUTE_TEXTS', lambda recs: {r['path']: tv3.MINUTE_TEXT.get(r['path'], [])
                                                                            for r in recs})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self._tmp.cleanup()

    def full(self, slots_json):
        return json.dumps(dict(json.loads(slots_json), invoices=[]), ensure_ascii=False)

    EXTRA = {'nature': 'ترى الخبرة أن العقد عقد خدمات اتصالات متنقلة بنظام الدفع الآجل الشهري.',
             'value': 'ترى الخبرة أن قيمة العقد تتحدد بالفواتير الشهرية الصادرة عن كل خط.',
             'defense': 'ترى الخبرة أنه لم يُبدَ من المدعى عليه دفاع ينال مما انتهت إليه.',
             'general': 'ترى الخبرة أن الأوراق لا تتضمن ما يغير ما سبق بيانه.'}

    def all_slots(self, prompt):
        """ردّ ذكي لكل خانة مطلوبة في الطلب (smart_slots + جملة مختلفة لكل محور آخر)."""
        got = json.loads(self.tv3.smart_slots())['slots']
        for sid in re.findall(r'^- (\S+) \(محور', prompt, re.M):
            if sid not in got:
                key = next((k for k in self.EXTRA if k in sid), 'general')
                got[sid] = self.EXTRA[key]
        return json.dumps({'slots': got, 'invoices': []}, ensure_ascii=False)

    def test_one_request_with_summary_and_critical_docs(self):
        import report_v3
        ask = Counter(self.all_slots)
        report_v3.run(self.base, self.data, ask=ask)
        self.assertEqual(len(ask.calls), 1)
        p = ask.calls[0]
        self.assertIn('## ملخص القضية المتحقَّق', p)
        self.assertIn('Commitment Penalty', p)                        # صفحات الكشف/الفواتير
        self.assertIn('تخصص المدعية دفاعها', p)                      # مذكرة الدفاع كاملة
        self.assertIn('بإلزام المعلن إليه', p)                        # 2026-10-23: كل المستندات كاملة ما دامت ضمن الميزانية
        self.assertIn('## مستندات القضية كاملة', p)
        with mock.patch.object(report_v3, 'FULL_DOCS_TOKENS', 10):  # فوق الميزانية ← الحاسمة فقط (الصحيفة لا تُرسل)
            p2 = report_v3.full_prompt(self.base, self.data)
            self.assertNotIn('بإلزام المعلن إليه', p2)
            self.assertIn('## المستندات الحاسمة', p2)
            self.assertIn('Commitment Penalty', p2)
        self.assertIn('"slots"', p)
        import research_pipeline as rp
        r = rp.state(self.data)
        self.assertTrue(r['audit']['ok'], r['audit']['errors'])

    def test_rejected_slots_retried_once_only(self):
        import report_v3
        ask = Counter(lambda prompt: self.full(self.tv3.DUMB))
        report_v3.run(self.base, self.data, ask=ask)
        self.assertEqual(len(ask.calls), 2)                           # الطلب + إعادة واحدة للمرفوض فقط
        self.assertIn('رُفضت صياغتك السابقة', ask.calls[1])
        import research_pipeline as rp
        self.assertTrue(rp.state(self.data)['v3']['fallback'])        # ما بقي ← جمل الكود

    def test_browser_reply_same_checks_no_request(self):
        import report_v3
        res = report_v3.import_full_reply(self.base, self.data, self.full(self.tv3.DUMB), source='browser:Copilot')
        self.assertTrue(res['rejected'])                              # نفس الفحص: الأرقام الخام مرفوضة
        self.assertEqual(self.data['written_by']['research']['provider'], 'عبر المتصفح (Copilot)')
        import research_pipeline as rp
        self.assertNotIn('205.200', json.dumps(rp.state(self.data)['v3']['slots'], ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
