# اختبارات نافذة المستندات الجديدة (2ي، 2026-10-17): python -m unittest test_qt_documents_dialog -v
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QPushButton

import case_documents as cd
import case_workspace as cw
import qt_documents_dialog as qd
qd.DocumentsDialog.AUTO_RUN = False          # هذه الاختبارات للمرحلتين اليدويتين؛ التلقائي في test_five_parts

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)
APP = QApplication.instance() or QApplication([])


def conv(path):
    with open(path, 'rb') as f:
        if f.read() == b'BAD':
            raise cd.ConvertError('الملف تالف')
    return '<!-- صفحة 1 -->\nنص', 1


def spin_until(cond, secs=10):
    end = time.time() + secs
    while not cond() and time.time() < end:
        APP.processEvents()
        time.sleep(0.02)
    APP.processEvents()
    assert cond(), 'انتهت المهلة'


def start(dlg):
    """مرحلتا الواجهة: إضافة وتصنيف (إن كانت هناك ملفات مختارة) ثم تحويل الجاهز."""
    if dlg._staged:
        dlg._start()
        spin_until(lambda: not dlg._busy())
    dlg._convert_pending()


def known_classifier(path):
    return {'type': 'محضر أعمال', 'confidence': 1.0, 'reason': 'اختبار', 'snippet': ''}


class Base(unittest.TestCase):
    def setUp(self):
        self._old_cls = cd.CLASSIFIER
        cd.CLASSIFIER = known_classifier
        self._tmp = tempfile.TemporaryDirectory()
        t = self._tmp.name
        self.base, self.data = cw.ensure_workspace(CASE, os.path.join(t, 'ws'))
        self.src = os.path.join(t, 'src')
        os.makedirs(self.src)

    def tearDown(self):
        cd.CLASSIFIER = self._old_cls
        spin_until(lambda: qd.active_job(self.base) is None)
        self._tmp.cleanup()

    def f(self, name, content=None):
        p = os.path.join(self.src, name)
        with open(p, 'wb') as fh:
            fh.write(name.encode() if content is None else content)
        return p

    def dialog(self, convert=conv):
        return qd.DocumentsDialog(self.base, self.data, convert=convert)


class PureTests(unittest.TestCase):
    def test_portfolio_colors_distinct(self):
        pl = qd.portfolio_colors('المدعية', 0)
        df = qd.portfolio_colors('المدعى عليها', 1)
        self.assertNotEqual(pl, df)
        self.assertEqual(pl[0], qd.th.AMBER_BG)
        self.assertEqual(df, qd._TEAL)

    def test_friendly_error(self):
        self.assertEqual(qd.friendly_error('الملف تالف'), 'الملف تالف')
        self.assertIn('خطأ تقني', qd.friendly_error('KeyError: x'))
        self.assertTrue(qd.friendly_error(''))


class DialogTests(Base):
    def test_no_removed_buttons_and_help_text(self):
        dlg = self.dialog()
        texts = {b.text() for b in dlg.findChildren(QPushButton)}
        self.assertNotIn('إعادة تحويل المحدَّد', texts)
        self.assertNotIn('المتابعة رغم النقص', texts)
        self.assertTrue({'اختيار ملفات', 'اختيار مجلد', 'استيراد وتحويل'} <= texts)
        self.assertIn('الحافظة', qd.PORTFOLIO_HELP)

    def test_pick_folder_lists_all_supported_files_as_new(self):
        for n in ('a.pdf', 'b.pdf', 'c.xyz'):
            self.f(n)
        os.makedirs(os.path.join(self.src, 'sub'))
        open(os.path.join(self.src, 'sub', 'd.docx'), 'wb').write(b'd')
        dlg = self.dialog()
        with mock.patch.object(qd.QFileDialog, 'getExistingDirectory', return_value=self.src):
            dlg._pick_folder()
        self.assertEqual(len(dlg._staged), 3)                        # c.xyz غير مدعوم (.txt/.md صارا مدعومين)
        self.assertEqual({dlg.table.item(r, 7).text() for r in range(3)}, {'جديد'})

    def test_import_converts_new_only_and_state_per_file(self):
        a, b = self.f('a.pdf'), self.f('b.pdf', b'BAD')
        dlg = self.dialog()
        dlg.submitter.setText('المدعية')
        dlg._stage([a, b])
        start(dlg)
        self.assertTrue(dlg._busy())
        self.assertFalse(dlg.import_btn.isEnabled())
        spin_until(lambda: not dlg._busy())
        spin_until(lambda: 'اكتمل' in dlg.status.text())
        states = {dlg.table.item(r, 2).text(): dlg.table.item(r, 7).text() for r in range(dlg.table.rowCount())}
        self.assertEqual(states['a.pdf'], 'تم التحويل')
        self.assertTrue(states['b.pdf'].startswith('فشل'))
        self.assertIn('الملف تالف', states['b.pdf'])
        # زر إعادة المحاولة بجانب الفاشل فقط
        buttons = [dlg.table.cellWidget(r, 8) for r in range(2)]
        self.assertEqual(sorted(bool(w) for w in buttons), [False, True])
        # اللوحة الجانبية سجّلت الخطوات والخطأ بنص مفهوم
        log = dlg.log.toPlainText()
        for s in ('بدأ قراءة «a.pdf»', 'اكتمل «a.pdf»', 'فشل «b.pdf»: الملف تالف'):
            self.assertIn(s, log)

    def test_already_converted_file_is_skipped_by_fingerprint(self):
        a = self.f('a.pdf')
        calls = []

        def counting(path):
            calls.append(path)
            return conv(path)
        dlg = self.dialog(counting)
        dlg.submitter.setText('المدعية')
        dlg._stage([a])
        start(dlg)
        spin_until(lambda: not dlg._busy())
        self.assertEqual(len(calls), 1)
        dlg = self.dialog(counting)
        dlg.combo.setCurrentIndex(0)                                # نفس الحافظة P1
        dlg._stage([a])                                             # نفس الملف ثانية
        self.assertEqual(dlg._staged, [])
        self.assertIn('موجود سابقاً', dlg.log.toPlainText())
        self.assertEqual(len(calls), 1)

    def test_retry_only_failed_runs_in_background_without_blocking(self):
        gate = threading.Event()
        state = {'n': 0}

        def flaky(path):
            state['n'] += 1
            if state['n'] == 1:
                raise cd.ConvertError('الملف تالف')
            gate.wait(5)
            return conv(path)
        dlg = self.dialog(flaky)
        dlg.submitter.setText('المدعية')
        dlg._stage([self.f('a.pdf')])
        start(dlg)
        spin_until(lambda: not dlg._busy())
        btn = dlg.table.cellWidget(0, 8)
        self.assertIsNotNone(btn)
        btn.click()                                                 # الخيط الخلفي ينتظر البوابة…
        self.assertTrue(dlg._busy())
        t0 = time.time()
        for _ in range(20):                                         # …والواجهة ما زالت تستجيب
            APP.processEvents()
            time.sleep(0.01)
        self.assertLess(time.time() - t0, 2)
        self.assertIn('جارٍ التحويل', dlg.table.item(0, 7).text())
        self.assertIsNone(dlg.table.cellWidget(0, 8))               # لا «إعادة محاولة» أثناء التحويل
        gate.set()
        spin_until(lambda: not dlg._busy())
        self.assertEqual(dlg.table.item(0, 7).text(), 'تم التحويل')
        self.assertIsNone(dlg.table.cellWidget(0, 8))

    def test_close_while_running_background_keeps_job_and_state(self):
        gate = threading.Event()

        def slow(path):
            gate.wait(5)
            return conv(path)
        dlg = self.dialog(slow)
        dlg.submitter.setText('المدعية')
        dlg._stage([self.f('a.pdf')])
        start(dlg)
        spin_until(lambda: dlg.table.rowCount() == 1 and 'جارٍ' in dlg.table.item(0, 7).text())

        class FakeBox:
            ButtonRole = qd.QMessageBox.ButtonRole

            def __init__(self, *a):
                self.buttons = {}

            def setWindowTitle(self, *a): pass

            def setText(self, *a): pass

            def addButton(self, text, role):
                self.buttons[text] = object()
                return self.buttons[text]

            def exec(self): pass

            def clickedButton(self):
                return self.buttons['متابعته في الخلفية']
        with mock.patch.object(qd, 'QMessageBox', FakeBox):
            dlg.done(0)
        self.assertIsNotNone(qd.active_job(self.base))              # العمل لم يُقطع
        self.assertIs(qd.live_data(self.base), self.data)
        gate.set()
        spin_until(lambda: qd.active_job(self.base) is None)
        d = cw.read_case_json(self.base)
        self.assertEqual(d['portfolios'][0]['docs'][0]['convert']['state'], 'done')

    def test_stop_leaves_rest_new_and_resumable(self):
        stop_after_first = {'n': 0}
        dlg_holder = {}

        def conv_stop(path):
            stop_after_first['n'] += 1
            qd._JOBS[self.base].stop_flag = True
            return conv(path)
        dlg = self.dialog(conv_stop)
        dlg.submitter.setText('المدعية')
        dlg._stage([self.f('a.pdf'), self.f('b.pdf'), self.f('c.pdf')])
        start(dlg)
        spin_until(lambda: not dlg._busy())
        d = cw.read_case_json(self.base)
        states = [x['convert']['state'] for x in d['portfolios'][0]['docs']]
        self.assertIn('pending', states)
        self.assertEqual(d['steps']['documents']['state'], 'needs_input')
        # استئناف: «استيراد وتحويل» يحوّل الجديد فقط
        dlg2 = self.dialog(conv)
        self.assertTrue(dlg2.import_btn.isEnabled())
        start(dlg2)
        spin_until(lambda: not dlg2._busy())
        d = cw.read_case_json(self.base)
        self.assertEqual({x['convert']['state'] for x in d['portfolios'][0]['docs']}, {'done'})
        self.assertEqual(d['steps']['documents']['state'], 'done')


import doc_router as dr
from PyQt6.QtWidgets import QComboBox


def typed(mapping):
    """مصنِّف وهمي بحسب محتوى الملف (اسمه): {اسم: نوع}"""
    def f(path):
        t = mapping[open(path, 'rb').read().decode()]
        return {'type': t, 'confidence': 0.0 if t == dr.T_UNKNOWN else 0.8, 'reason': f'سبب {t}', 'snippet': 'نص أول'}
    return f


class RoutingDialogTests(Base):
    def setUp(self):
        super().setUp()
        self.engines_log = []
        self._old_engines = cd.ENGINES
        log = self.engines_log

        def mk(name):
            def run(path, doc):
                log.append((name, doc['orig_name']))
                return '<!-- صفحة 1 -->\nنص', 1, ''
            return run
        cd.ENGINES = {e: mk(e) for e in dr.ENGINES}

    def tearDown(self):
        cd.ENGINES = self._old_engines
        super().tearDown()

    def stage_and_classify(self, mapping):
        cd.CLASSIFIER = typed(mapping)
        dlg = self.dialog(None)
        dlg.submitter.setText('المدعية')
        dlg._stage([self.f(n) for n in mapping])
        dlg._start()
        spin_until(lambda: not dlg._busy())
        return dlg

    def row(self, dlg, name):
        for r in range(dlg.table.rowCount()):
            if dlg.table.item(r, 2).text() == name:
                return r
        raise AssertionError(name)

    def test_classify_phase_shows_type_and_engine_and_does_not_convert(self):
        dlg = self.stage_and_classify({'a.pdf': dr.T_PORTFOLIO, 'b.pdf': dr.T_DEFENSE, 'c.pdf': dr.T_MINUTES})
        self.assertEqual(self.engines_log, [])                            # لا تحويل قبل المراجعة
        for name, t, e in (('a.pdf', dr.T_PORTFOLIO, 'gemini'), ('b.pdf', dr.T_DEFENSE, 'external_ocr'),
                           ('c.pdf', dr.T_MINUTES, 'local')):
            r = self.row(dlg, name)
            tc, ec = dlg.table.cellWidget(r, 3), dlg.table.cellWidget(r, 4)
            self.assertEqual((tc.currentData(), ec.currentData()), (t, e))
            self.assertIn('سبب', tc.toolTip())
        self.assertIn('راجع النوع والمحرّك', dlg.status.text())
        self.assertTrue(dlg.import_btn.isEnabled())
        self.assertIn('1000', doc_router_text())

    def test_manual_change_of_type_and_engine_then_convert_uses_choice(self):
        dlg = self.stage_and_classify({'a.pdf': dr.T_PORTFOLIO})
        r = self.row(dlg, 'a.pdf')
        tc = dlg.table.cellWidget(r, 3)
        tc.setCurrentIndex(tc.findData(dr.T_DEFENSE))                     # يغيّر النوع ← المحرّك يتبع التوجيه
        r = self.row(dlg, 'a.pdf')
        ec = dlg.table.cellWidget(r, 4)
        self.assertEqual(ec.currentData(), 'external_ocr')
        ec.setCurrentIndex(ec.findData('local'))                          # ثم يغيّر المحرّك وحده
        d = next(x for _, x in cd.all_docs(self.data))
        self.assertEqual((d['doc_type'], d['engine'], d['manual']), (dr.T_DEFENSE, 'local', True))
        dlg._convert_pending()
        spin_until(lambda: not dlg._busy())
        self.assertEqual(self.engines_log, [('local', 'a.pdf')])
        r = self.row(dlg, 'a.pdf')
        self.assertEqual(dlg.table.item(r, 3).text(), dr.T_DEFENSE)       # بعد التحويل: نص لا قائمة
        self.assertIsNone(dlg.table.cellWidget(r, 3))

    def test_unknown_is_held_shows_placeholder_and_first_page_choice(self):
        dlg = self.stage_and_classify({'a.pdf': dr.T_MINUTES, 'u.pdf': dr.T_UNKNOWN})
        r = self.row(dlg, 'u.pdf')
        tc = dlg.table.cellWidget(r, 3)
        self.assertEqual(tc.currentText(), qd.PLACEHOLDER)
        self.assertFalse(dlg.table.cellWidget(r, 4).isEnabled())
        self.assertIsNotNone(dlg.table.cellWidget(r, 8))                  # زر «الصفحة الأولى…»
        self.assertIn('نوعه غير معروف', dlg.status.text())
        dlg._convert_pending()
        spin_until(lambda: not dlg._busy())
        self.assertEqual([n for _, n in self.engines_log], ['a.pdf'])     # غير المعروف لم يُحوَّل
        # الصفحة الأولى + القائمة
        d = next(x for _, x in cd.all_docs(self.data) if x['orig_name'] == 'u.pdf')
        fp = qd.FirstPageDialog(self.base, d)
        self.assertEqual(fp.combo.count(), 5)
        fp.combo.setCurrentIndex(fp.combo.findData(dr.T_PORTFOLIO))
        fp._accept()
        self.assertEqual(fp.chosen, dr.T_PORTFOLIO)
        with mock.patch.object(qd.FirstPageDialog, 'exec',
                               new=lambda self: (setattr(self, 'chosen', dr.T_PORTFOLIO), 1)[1]):
            dlg._show_first_page(d['uid'])
        self.assertEqual((d['doc_type'], d['engine'], d['needs_type']), (dr.T_PORTFOLIO, 'gemini', False))
        dlg._convert_pending()
        spin_until(lambda: not dlg._busy())
        self.assertEqual(self.engines_log[-1], ('gemini', 'u.pdf'))

    def test_edit_widgets_disabled_while_busy(self):
        dlg = self.stage_and_classify({'a.pdf': dr.T_MINUTES})
        gate = threading.Event()
        cd.ENGINES = {e: (lambda path, doc: (gate.wait(5), ('<!-- صفحة 1 -->\nx', 1, ''))[1]) for e in dr.ENGINES}
        dlg._convert_pending()
        r = self.row(dlg, 'a.pdf')
        self.assertFalse(dlg.table.cellWidget(r, 3).isEnabled())          # العمل جارٍ ← لا تعديل
        self.assertFalse(dlg.table.cellWidget(r, 4).isEnabled())
        gate.set()
        spin_until(lambda: not dlg._busy())


def doc_router_text():
    return dr.limits_text()


if __name__ == '__main__':
    unittest.main()
