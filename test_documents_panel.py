# اختبارات لوحة «إضافة مستندات القضية» المضمَّنة (2026-10-18): python -W ignore -m unittest test_documents_panel -v
import json
import os
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QDialog

import case_documents as cd
import case_workspace as cw
import qt_documents_dialog as qd
import qt_documents_panel as qp

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)
APP = QApplication.instance() or QApplication([])
FIRST = 'حافظة مستندات مقدمة من المدعى عليه بجلسة 05/10/2026 أمام الخبير'


def conv(path):
    return f'<!-- صفحة 1 -->\n{FIRST}\n<!-- صفحة 2 -->\nنص آخر 01/01/2020', 2


def classifier(path):
    return {'type': 'حافظة مستندات', 'confidence': 1.0, 'reason': 'اختبار', 'snippet': ''}


def spin(cond, secs=10):
    end = time.time() + secs
    while not cond() and time.time() < end:
        APP.processEvents()
        time.sleep(0.02)
    APP.processEvents()
    assert cond(), 'انتهت المهلة'


class PureTests(unittest.TestCase):
    def test_sorting_and_sides(self):
        P = lambda who: {'submitter': who, 'date': ''}                      # noqa: E731
        D = lambda t, no=1: {'doc_type': t, 'no': no}                       # noqa: E731
        rows = [(P('المدعى عليه'), D('مذكرة دفاع')), (P('المدعية'), D('مذكرة دفاع')), (P('—'), D('محضر أعمال')),
                (P('المدعى عليه'), D('حافظة مستندات')), (P('—'), D('حكم')), (P('المدعية'), D('حافظة مستندات')),
                (P('—'), D('صحيفة دعوى'))]
        rows.sort(key=lambda pd: qp.order_key(*pd))
        self.assertEqual([(qp.side_of(p, d), d['doc_type']) for p, d in rows],
                         [('أخرى', 'حكم'), ('أخرى', 'صحيفة دعوى'), ('أخرى', 'محضر أعمال'),
                          ('المدعية', 'حافظة مستندات'), ('المدعية', 'مذكرة دفاع'),
                          ('المدعى عليه', 'حافظة مستندات'), ('المدعى عليه', 'مذكرة دفاع')])
        self.assertEqual(qp.title_of({'submitter': 'المدعية', 'date': ''}, {'doc_type': 'مذكرة دفاع'}),
                         'مذكرة دفاع المدعية')

    def test_state_view(self):
        self.assertEqual(qp.state_view({'state': 'running', 'progress': 65})[0], 'جارٍ التحويل 65%')
        self.assertEqual(qp.state_view({'state': 'running'})[3], 0)          # بعيد بلا نسبة ← شريط متحرك
        self.assertIn('تم التحويل', qp.state_view({'state': 'done'})[0])
        self.assertEqual(qp.state_view({'state': 'failed'})[0], 'فشل')
        self.assertEqual(qp.human_size(2_516_582), '2.4 م.ب')

    def test_verify_portfolio_meta_requires_text(self):
        self.assertEqual(cd.verify_portfolio_meta('{"submitter":"المدعى عليه","date":"05/10/2026"}', FIRST),
                         ('المدعى عليه', '2026-10-05'))
        self.assertEqual(cd.verify_portfolio_meta('{"submitter":"شركة لا ترد","date":"09/09/2026"}', FIRST), ('', ''))


class PanelTests(unittest.TestCase):
    def setUp(self):
        self._old = (cd.CLASSIFIER, qd.DocumentsDialog.AUTO_RUN, qd.DocumentsDialog.PORTFOLIO_ASK)
        cd.CLASSIFIER = classifier
        qd.DocumentsDialog.AUTO_RUN = True
        self.asked = []
        qd.DocumentsDialog.PORTFOLIO_ASK = staticmethod(
            lambda p: self.asked.append(p) or '{"submitter":"المدعى عليه","date":"05/10/2026"}')
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, os.path.join(self._tmp.name, 'ws'))
        self.src = os.path.join(self._tmp.name, 'src')
        os.makedirs(self.src)

    def tearDown(self):
        spin(lambda: qd.active_job(self.base) is None)
        cd.CLASSIFIER, qd.DocumentsDialog.AUTO_RUN, qd.DocumentsDialog.PORTFOLIO_ASK = self._old
        self._tmp.cleanup()

    def file(self, name):
        p = os.path.join(self.src, name)
        with open(p, 'wb') as f:
            f.write(b'%PDF ' + name.encode())
        return p

    def test_embedded_widget_auto_converts_and_refines_portfolio_from_first_page(self):
        done = []
        from PyQt6.QtWidgets import QWidget
        host = QWidget()
        panel = qp.DocumentsPanel(self.base, self.data, host, convert=conv, on_changed=lambda: done.append(1))
        self.assertFalse(panel.isWindow())                     # مضمَّنة لا نافذة
        panel.add_paths([self.file('a.pdf'), self.file('b.pdf')])
        spin(lambda: qd.active_job(self.base) is None and done)
        self.assertEqual(len(self.data['portfolios']), 2)        # كل ملف حافظة مستقلة
        for p in self.data['portfolios']:
            self.assertEqual((p['submitter'], p['date'], p['auto_meta']), ('المدعى عليه', '2026-10-05', 'ai'))
        self.assertEqual(len(self.asked), 2)                     # صفحة أولى لكل حافظة (مزوّد رخيص)
        self.assertIn(FIRST, self.asked[0])
        self.assertNotIn('نص آخر', self.asked[0])                # الصفحة الأولى فقط
        APP.processEvents()
        panel._render()
        # القائمة من الأصول في مجلد القضية (لا markdown ولا _نظام)؛ المقدّم يأتي من الفرز (case_sort) لا من هنا
        self.assertIn('مجموع المستندات: 2', panel.sum_lbl.text())
        self.assertIn('المستندات الأصلية في مجلد القضية: 2', panel.list_sub.text())
        self.assertEqual(sorted(n for n, _k, _s in panel.row_texts()), ['a.pdf', 'b.pdf'])
        host.deleteLater()

    def test_user_edited_portfolio_not_overwritten(self):
        p = cd.add_portfolio(self.data, 'المدعية', '2026-10-01')
        p['auto_meta'] = True
        cd.update_portfolio(self.base, self.data, p['id'], 'الخبير', None)
        self.assertIsNone(cd.refine_portfolio(self.base, self.data, p['id'], ask=lambda _p: self.fail('لا طلب')))

    def test_case_page_hosts_panel_and_button_opens_step(self):
        import qt_case_page as qcp
        saved = (qcp.CasePageDialog.AUTO_SYNC, qcp.CasePageDialog.AUTO_PROCEDURES, qcp.CasePageDialog.AUTO_ASK_TYPE)
        qcp.CasePageDialog.AUTO_SYNC = qcp.CasePageDialog.AUTO_PROCEDURES = qcp.CasePageDialog.AUTO_ASK_TYPE = False
        try:
            opened = []
            orig = QDialog.exec
            QDialog.exec = lambda self_: opened.append(type(self_).__name__) or 0
            try:
                dlg = qcp.CasePageDialog(self.base, cw.read_case_json(self.base))
                dlg.open_step('documents')
                self.assertEqual(dlg._open, 'documents')
                self.assertIsInstance(dlg.docs_panel, qp.DocumentsPanel)
                self.assertEqual(opened, [])                    # لا نافذة جديدة
            finally:
                QDialog.exec = orig
            dlg.deleteLater()
        finally:
            qcp.CasePageDialog.AUTO_SYNC, qcp.CasePageDialog.AUTO_PROCEDURES, qcp.CasePageDialog.AUTO_ASK_TYPE = saved


if __name__ == '__main__':
    unittest.main()


class FolderListTests(unittest.TestCase):
    """القائمة: الأصول فقط (لا .md ولا markdown/ ولا _نظام ولا الملخص.md)، وزر إعادة القراءة يرسل المسار."""
    def setUp(self):
        import case_workspace as cw
        import case_folder as cf
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace({'caso_no': 'T0000009'}, self._tmp.name)
        for rel, body in (('أخرى/a.pdf', b'%PDF a'), ('أخرى/ملاحظات.md', b'# x'), ('markdown/أخرى/a.md', b'x'),
                          ('الملخص.md', b'x')):
            p = os.path.join(self.base, *rel.split('/'))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as f:
                f.write(body)
        self._old = cf.CONVERTER
        cf.CONVERTER = lambda path, kind: ('<!-- صفحة 1 -->' + chr(10) + 'نص', 1)
        cf.sync_case_folder(self.base, self.data)

    def tearDown(self):
        import case_folder as cf
        cf.CONVERTER = self._old
        self._tmp.cleanup()

    def test_only_originals_listed_and_reread_emits_path(self):
        import case_folder as cf
        rows = cf.doc_rows(self.base, self.data)
        self.assertEqual([r['rel'] for r in rows], ['أخرى/a.pdf'])
        self.assertNotIn('أخرى/ملاحظات.md', cf.load_manifest(self.base)['files'])
        from PyQt6.QtWidgets import QWidget, QPushButton
        host = QWidget()
        panel = qp.DocumentsPanel(self.base, self.data, host)
        got = []
        panel.reread.connect(lambda rel, eng: got.append((rel, eng)))
        btn = next(b for b in panel.list_box.findChildren(QPushButton) if 'إعادة القراءة' in b.toolTip())
        btn.click()
        self.assertEqual(got, [('أخرى/a.pdf', '')])
        host.deleteLater()

    def test_reread_file_converts_and_sorts_with_progress(self):
        import case_folder as cf
        seen = []
        cf.CONVERTER = lambda path, kind: (seen.append(cf.reread_state(self.base, 'أخرى/a.pdf')) or
                                           ('<!-- صفحة 1 -->' + chr(10) + 'نص جديد', 1))
        asked = []
        new = cf.reread_file(self.base, self.data, 'أخرى/a.pdf',
                             ask=lambda p: asked.append(p) or '{"parts": [{"type": "أخرى", "pages": [1, 1]}]}')
        self.assertEqual(seen[0]['stage'], 'convert')
        self.assertEqual(len(asked), 1)                       # طلب فرز واحد للملف وحده
        self.assertEqual(new, 'أخرى/a.pdf')
        self.assertEqual(cf.reread_state(self.base, 'أخرى/a.pdf'), {})
        with open(os.path.join(self.base, 'markdown', 'أخرى', 'a.md'), encoding='utf-8') as f:
            self.assertIn('نص جديد', f.read())
