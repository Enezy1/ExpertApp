# اختبارات ملفات .md/.txt (2026-10-17): نص جاهز لا يُحوَّل ولا يُرسل لأي OCR/ذكاء اصطناعي.
# python -m unittest test_text_input -v
import json
import os
import tempfile
import unittest
from unittest import mock

import case_documents as cd
import case_model as cm
import case_workspace as cw
import doc_router

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)

PORTFOLIO_MD = '# حافظة مستندات\nمقدمة من المدعية\nحافظة بمستندات مقدمة للخبير\nعقد رقم: C-7788\n'


def boom(*a, **k):
    raise AssertionError('لا يجوز استدعاء OCR/ذكاء اصطناعي لملف نصي')


class TextInputBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, os.path.join(self._tmp.name, 'ws'))
        self.src_dir = os.path.join(self._tmp.name, 'src')
        os.makedirs(self.src_dir)
        # أي محاولة تصنيف/تحويل/Gemini/OCR تُفشل الاختبار
        self._patches = [
            mock.patch.object(cd, 'CLASSIFIER', boom),
            mock.patch.object(cd, 'ocr_to_markdown', boom),
            mock.patch.object(doc_router, 'GEMINI_PROVIDER_FACTORY', boom),
            mock.patch.dict(cd.ENGINES, {k: boom for k in cd.ENGINES}),
        ]
        for p in self._patches:
            p.start()
        self.p = cd.add_portfolio(self.data, 'المدعية', '2026-09-01')

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def src(self, name, content):
        path = os.path.join(self.src_dir, name)
        with open(path, 'wb') as f:
            f.write(content if isinstance(content, bytes) else content.encode('utf-8'))
        return path

    def add(self, *paths):
        items = cd.plan_batch(self.data, self.p['id'], list(paths))
        return cd.import_batch(self.base, self.data, self.p['id'], items, convert=boom)

    def md_text(self, doc):
        with open(os.path.join(self.base, doc['md']), encoding='utf-8') as f:
            return f.read()


class TestTextInput(TextInputBase):
    def test_md_portfolio_copied_without_conversion(self):
        r = self.add(self.src('حافظة.md', PORTFOLIO_MD))
        self.assertEqual((r['total'], r['done'], r['failed'], r['left']), (1, 1, 0, 0))
        d = self.p['docs'][0]
        self.assertEqual(d['engine'], doc_router.ENGINE_TEXT)
        self.assertEqual(d['origin'], 'original')
        self.assertEqual(d['doc_type'], doc_router.T_PORTFOLIO)       # صُنِّف من أول سطور النص
        self.assertFalse(d['needs_type'])
        self.assertEqual(d['convert']['state'], 'done')
        self.assertEqual(d['pages'], 1)
        self.assertEqual(d['contract'], 'C-7788')
        self.assertTrue(os.path.exists(os.path.join(self.base, d['md'])))
        self.assertTrue(self.md_text(d).startswith('<!-- صفحة 1 -->\n# حافظة مستندات'))
        self.assertIn('مقدمة من المدعية', self.md_text(d))
        self.assertEqual(cm.state(self.data, 'documents'), 'done')
        disk = cw.read_case_json(self.base)
        self.assertEqual(disk['portfolios'][0]['docs'][0]['origin'], 'original')

    def test_txt_and_existing_page_markers_kept(self):
        text = '<!-- صفحة 1 -->\nأ\n\n<!-- صفحة 2 -->\nب\n'
        self.add(self.src('م.txt', text))
        d = self.p['docs'][0]
        self.assertEqual(self.md_text(d), text)                        # كما هو
        self.assertEqual(d['pages'], 2)

    def test_formfeed_and_page_lines_become_markers(self):
        self.add(self.src('a.txt', 'الأولى\fالثانية'), self.src('b.md', 'x\n--- صفحة 1 ---\ny\n--- صفحة 2 ---\nz'))
        da, db = self.p['docs']
        self.assertEqual(da['pages'], 2)
        self.assertIn('<!-- صفحة 2 -->\nالثانية', self.md_text(da))
        self.assertEqual(db['pages'], 2)
        self.assertIn('<!-- صفحة 2 -->', self.md_text(db))

    def test_cp1256_text_is_decoded(self):
        self.add(self.src('w.txt', 'محضر أعمال الخبير\nمحضر مباشرة'.encode('cp1256')))
        d = self.p['docs'][0]
        self.assertEqual(d['doc_type'], doc_router.T_MINUTES)
        self.assertIn('محضر', self.md_text(d))

    def test_minutes_and_defense_classified_from_text(self):
        self.add(self.src('m.md', 'محضر أعمال الخبير\nمحضر جلسة'), self.src('d.md', 'مذكرة بدفاع\nمذكرة دفاع المدعى عليه'))
        self.assertEqual([d['doc_type'] for d in self.p['docs']], [doc_router.T_MINUTES, doc_router.T_DEFENSE])

    def test_unknown_text_is_not_held(self):
        self.add(self.src('u.md', 'نص عادي لا يدل على نوع'))
        d = self.p['docs'][0]
        self.assertEqual(d['doc_type'], doc_router.T_UNKNOWN)
        self.assertFalse(d['needs_type'])
        self.assertEqual(d['convert']['state'], 'done')
        self.assertEqual(cd.pending_docs(self.data), [])

    def test_readding_same_file_is_skipped(self):
        path = self.src('حافظة.md', PORTFOLIO_MD)
        self.add(path)
        copy = self.src('نسخة.md', PORTFOLIO_MD)                       # اسم مختلف، المحتوى نفسه
        self.assertEqual(cd.classify_files(self.data, [path, copy], self.p['id'])[1][1], 'done')
        r = self.add(copy)
        self.assertEqual(r['total'], 0)
        self.assertEqual(len(self.p['docs']), 1)
        self.assertEqual(len(os.listdir(os.path.join(self.base, 'markdown', 'أخرى'))) >= 1, True)

    def test_empty_md_is_flagged(self):
        r = self.add(self.src('فارغ.md', '  \n\n'))
        self.assertEqual((r['done'], r['failed']), (0, 1))
        d = self.p['docs'][0]
        self.assertEqual(d['convert']['state'], 'failed')
        self.assertIn('فارغ', d['convert']['message'])
        self.assertEqual(cm.state(self.data, 'documents'), 'failed')
        self.assertFalse(os.path.exists(os.path.join(self.base, d['md'])))

    def test_text_doc_type_and_engine_not_editable(self):
        self.add(self.src('فارغ.md', ''))
        uid = self.p['docs'][0]['uid']
        with self.assertRaises(cm.StepError):
            cd.set_doc_type(self.base, self.data, uid, doc_router.T_PORTFOLIO)
        with self.assertRaises(cm.StepError):
            cd.set_doc_engine(self.base, self.data, uid, doc_router.ENGINE_GEMINI)

    def test_text_never_reconverted_by_process_pending(self):
        self.add(self.src('حافظة.md', PORTFOLIO_MD))
        before = self.md_text(self.p['docs'][0])
        res = cd.process_pending(self.base, self.data, convert=boom)
        self.assertEqual(res['total'], 0)
        self.assertEqual(self.md_text(self.p['docs'][0]), before)

    def test_mixed_with_pdf_pending_keeps_step_open(self):
        with mock.patch.object(cd, 'CLASSIFIER', lambda p: {'type': 'محضر أعمال', 'confidence': 1, 'reason': ''}):
            items = cd.plan_batch(self.data, self.p['id'], [self.src('x.pdf', b'%PDF')])
            cd.add_files(self.base, self.data, self.p['id'], items)
        self.add(self.src('حافظة.md', PORTFOLIO_MD))
        self.assertEqual(cm.state(self.data, 'documents'), 'needs_input')
        self.assertEqual(len(cd.pending_docs(self.data)), 1)

    def test_supported_includes_text(self):
        self.assertIn('.md', cd.SUPPORTED)
        self.assertIn('.txt', cd.SUPPORTED)

    def test_classify_file_reads_text_without_ocr(self):
        res = doc_router.classify_file(self.src('h.md', PORTFOLIO_MD))
        self.assertEqual(res['type'], doc_router.T_PORTFOLIO)
        self.assertIn('حافظة', res['snippet'])


if __name__ == '__main__':
    unittest.main()
