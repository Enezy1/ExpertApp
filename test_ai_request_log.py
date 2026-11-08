# اختبارات سجل طلبات الذكاء الاصطناعي داخل القضية: python -W ignore -m unittest test_ai_request_log -v
import json
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication

import ai_call_log
import case_workspace as cw
import case_procedures as cp
import qt_ai_log
import qt_case_page as qp

qp.CasePageDialog.AUTO_SYNC = False
qp.CasePageDialog.AUTO_ASK_TYPE = False
qp.CasePageDialog.STARTUP_VIEW = False
qp.CasePageDialog.AUTO_PROCEDURES = False
ai_call_log.PATH_OVERRIDE = os.path.join(tempfile.gettempdir(), 'expertapp_test_ai_calls.log')

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)
APP = QApplication.instance() or QApplication([])

SECRETS = ('AIzaSyA1234567890abcdefghijklmnop', 'sk-proj-abcdefghijklmnop1234', 'gsk_abcdefghijklmnopqrstuvwx')


def provider_ask(reply, label='Gemini (مفتاحك)', model='gemini-test'):
    def ask(prompt):
        ai_call_log.set_provider(label, model)
        return reply
    return ask


class LogFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_one_file_per_request_with_full_prompt_and_reply(self):
        ask = ai_call_log.wrap(provider_ask('{"ok": 1}'), 'الفرز', base=self.base)
        ai_call_log.detail('حافظة 1.pdf')
        ask('نص الطلب الكامل')
        ask('طلب ثانٍ')
        files = sorted(os.listdir(ai_call_log.req_dir(self.base)))
        self.assertEqual(len(files), 2)
        self.assertTrue(files[0].startswith('0001_') and files[1].startswith('0002_'))
        r = ai_call_log.list_requests(self.base)[0]
        self.assertEqual((r['step'], r['detail'], r['prompt'], r['response']), ('الفرز', 'حافظة 1.pdf', 'نص الطلب الكامل', '{"ok": 1}'))
        self.assertEqual((r['provider'], r['model'], r['key_owner']), ('Gemini (مفتاحك)', 'gemini-test', 'مفتاحك'))
        self.assertEqual((r['prompt_chars'], r['response_chars'], r['ok']), (len('نص الطلب الكامل'), 9, True))
        self.assertIn('secs', r)
        self.assertIsNone(ai_call_log.list_requests(self.base)[1]['detail'] or None)       # التفصيل يُصفَّر بعد الطلب

    def test_section_key_owner(self):
        ai_call_log.wrap(provider_ask('x', 'Gemini (مفتاح القسم)'), 'العقد', base=self.base)('p')
        self.assertEqual(ai_call_log.list_requests(self.base)[0]['key_owner'], 'مفتاح القسم')

    def test_no_secret_saved_anywhere(self):
        ask = ai_call_log.wrap(provider_ask(f'رد فيه {SECRETS[1]}'), 'الموضوع', base=self.base)
        ask(f'طلب فيه key={SECRETS[0]} و {SECRETS[2]}')

        def boom(p):
            raise RuntimeError(f'HTTP 401 ?key={SECRETS[0]}')
        try:
            ai_call_log.wrap(boom, 'الموضوع', base=self.base)('p')
        except RuntimeError:
            pass
        blob = ''
        for n in os.listdir(ai_call_log.req_dir(self.base)):
            with open(os.path.join(ai_call_log.req_dir(self.base), n), encoding='utf-8') as f:
                blob += f.read()
        for s in SECRETS:
            self.assertNotIn(s, blob)
        self.assertIn('***', blob)

    def test_failure_logged_with_error_and_exception_still_raised(self):
        def boom(p):
            raise RuntimeError('انقطع الاتصال')
        with self.assertRaises(RuntimeError):
            ai_call_log.wrap(boom, 'البحث', base=self.base)('طلب')
        r = ai_call_log.list_requests(self.base)[0]
        self.assertFalse(r['ok'])
        self.assertEqual(ai_call_log.outcome(r)[0], '✗')
        self.assertIn('انقطع الاتصال', r['error'])

    def test_verdict_rejection_and_retry_flags(self):
        ask = ai_call_log.wrap(provider_ask('رد1'), 'الموضوع', base=self.base)
        ask('أولى')
        ai_call_log.verdict(False, 'أرقام غير واردة: 99')
        ask('ثانية')
        ai_call_log.verdict(True, 'سليم')
        a, b = ai_call_log.list_requests(self.base)
        self.assertEqual(ai_call_log.outcome(a), ('✗', 'رُفض في التحقق: أرقام غير واردة: 99'))
        self.assertTrue(a['retried'])
        self.assertTrue(b['is_retry'])
        self.assertEqual(ai_call_log.outcome(b)[0], '✓')
        ask('ثالثة')                                     # بعد طلب ناجح لا تُعدّ إعادة
        self.assertFalse(ai_call_log.list_requests(self.base)[2]['is_retry'])

    def test_empty_reply_is_rejected(self):
        ai_call_log.wrap(provider_ask('  '), 'العقد', base=self.base)('p')
        self.assertEqual(ai_call_log.outcome(ai_call_log.list_requests(self.base)[0])[0], '✗')

    def test_without_base_nothing_written_in_case(self):
        ai_call_log.wrap(provider_ask('x'), 'العقد')('p')
        self.assertEqual(ai_call_log.list_requests(self.base), [])

    def test_real_validator_marks_request(self):
        ask = ai_call_log.wrap(provider_ask('{"present": [1]}'), 'الحضور', base=self.base)
        got = cp.ai_attendance('حضر الخبير', ['شركة أ', 'شركة ب'], ask)
        self.assertEqual(got, [0])
        r = ai_call_log.list_requests(self.base)[0]
        self.assertEqual(ai_call_log.outcome(r)[0], '✓')
        self.assertIn('الحاضرون', r['verdict']['reason'])
        cp.ai_attendance('x', ['أ'], ai_call_log.wrap(provider_ask('ليس json'), 'الحضور', base=self.base))
        self.assertEqual(ai_call_log.outcome(ai_call_log.list_requests(self.base)[1])[0], '✗')


class DialogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        self.data['steps']['documents']['state'] = 'done'
        cw.write_case_json(self.base, self.data)
        ai_call_log.wrap(provider_ask('رد الفرز'), 'الفرز', base=self.base)('طلب الفرز الكامل')
        ai_call_log.verdict(True, 'جزء واحد')
        ai_call_log.wrap(provider_ask(f'رد {SECRETS[1]}', 'ChatGPT (مفتاح القسم)', 'gpt-x'), 'الموضوع', base=self.base)(
            f'طلب {SECRETS[0]}')
        ai_call_log.verdict(False, 'رقم غير وارد')

    def tearDown(self):
        self._tmp.cleanup()

    def test_dialog_lists_requests_and_shows_texts(self):
        dlg = qt_ai_log.AiLogDialog(self.base)
        t = dlg.table
        self.assertEqual(t.rowCount(), 2)
        self.assertEqual([t.horizontalHeaderItem(i).text() for i in range(5)], ['الوقت', 'الخطوة', 'النموذج', 'المدة', 'النتيجة'])
        self.assertEqual((t.item(0, 1).text(), t.item(0, 4).text()), ('الفرز', 'مقبول'))
        self.assertEqual((t.item(1, 1).text(), t.item(1, 4).text()), ('الموضوع', 'مرفوض'))
        self.assertIn('gpt-x', t.item(1, 2).text())
        t.setCurrentCell(0, 0)
        self.assertEqual((dlg.prompt.toPlainText(), dlg.reply.toPlainText()), ('طلب الفرز الكامل', 'رد الفرز'))
        t.setCurrentCell(1, 0)
        self.assertIn('رقم غير وارد', dlg.note.text())
        self.assertIn('مفتاح القسم', dlg.note.text())
        self.assertTrue(dlg.prompt.isReadOnly())
        for s in SECRETS:
            self.assertNotIn(s, dlg.prompt.toPlainText() + dlg.reply.toPlainText())

    def test_empty_case_shows_message(self):
        with tempfile.TemporaryDirectory() as t:
            dlg = qt_ai_log.AiLogDialog(t)
            self.assertEqual(dlg.table.rowCount(), 0)
            self.assertIn('لا طلبات', dlg.head.text())

    def test_case_page_has_small_button_that_opens_dialog(self):
        opened = []
        dlg = qp.CasePageDialog(self.base, cw.read_case_json(self.base))
        self.assertEqual(dlg.ai_log_btn.text(), 'سجل الذكاء الاصطناعي')
        orig = qt_ai_log.AiLogDialog.exec
        qt_ai_log.AiLogDialog.exec = lambda self_: opened.append(self_.table.rowCount())
        try:
            dlg.ai_log_btn.click()
        finally:
            qt_ai_log.AiLogDialog.exec = orig
        self.assertEqual(opened, [2])


if __name__ == '__main__':
    unittest.main()
