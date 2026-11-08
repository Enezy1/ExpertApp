# اختبارات المرحلة 2ي (المستندات): python -m unittest test_case_documents -v
import json
import os
import tempfile
import threading
import time
import unittest

import case_documents as cd
import case_memory as mem
import case_model as cm
import case_workspace as cw

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)


def fake_convert(path):
    name = os.path.basename(path)
    with open(path, 'rb') as f:
        raw = f.read()
    if raw == b'BAD':
        raise cd.ConvertError('الملف تالف')
    return f'<!-- صفحة 1 -->\nنص {name}', 1


def known_classifier(path):
    return {'type': 'محضر أعمال', 'confidence': 1.0, 'reason': 'اختبار', 'snippet': ''}


class Base(unittest.TestCase):
    def setUp(self):
        self._old_cls = cd.CLASSIFIER
        cd.CLASSIFIER = known_classifier
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, os.path.join(self._tmp.name, 'ws'))
        self.src_dir = os.path.join(self._tmp.name, 'src')
        os.makedirs(self.src_dir)

    def tearDown(self):
        cd.CLASSIFIER = self._old_cls
        self._tmp.cleanup()

    def src(self, name, content=None):
        p = os.path.join(self.src_dir, name)
        with open(p, 'wb') as f:
            f.write(name.encode() if content is None else content)
        return p

    def disk(self):
        return cw.read_case_json(self.base)

    def batch(self, names, contents=None, **kw):
        p = cd.add_portfolio(self.data, 'المدعية', '2026-09-01') if not self.data['portfolios'] else self.data['portfolios'][0]
        paths = [self.src(n, (contents or {}).get(n)) for n in names]
        items = cd.plan_batch(self.data, p['id'], paths)
        return p, cd.import_batch(self.base, self.data, p['id'], items, convert=kw.pop('convert', fake_convert), **kw)


class PortfolioTests(Base):
    def test_ids_and_numbering_continue(self):
        p1 = cd.add_portfolio(self.data, 'المدعية', '2026-09-01')
        p2 = cd.add_portfolio(self.data, 'المدعى عليها', '2026-09-10')
        self.assertEqual((p1['id'], p2['id']), ('P1', 'P2'))
        with self.assertRaises(cm.StepError):
            cd.add_portfolio(self.data, ' ', '')
        self.batch(['a.pdf', 'b.pdf'])
        more = cd.plan_batch(self.data, 'P1', ['x', 'y'])
        self.assertEqual([m['no'] for m in more], [3, 4])


class BatchTests(Base):
    def test_batch_with_corrupt_file_does_not_fail_others(self):
        p, res = self.batch(['a.pdf', 'b.pdf', 'c.pdf'], contents={'b.pdf': b'BAD'})
        self.assertEqual((res['total'], res['done'], res['failed']), (3, 2, 1))
        d = self.disk()
        docs = d['portfolios'][0]['docs']
        self.assertEqual([x['convert']['state'] for x in docs], ['done', 'failed', 'done'])
        self.assertIn('تالف', docs[1]['convert']['message'])
        self.assertEqual(d['steps']['documents']['state'], 'failed')
        self.assertTrue(os.path.exists(os.path.join(self.base, docs[0]['md'])))
        self.assertFalse(os.path.exists(os.path.join(self.base, docs[1]['md'])))
        self.assertEqual(docs[0]['file'], 'أخرى/a.pdf')                  # «أخرى» باسمه الأصلي حتى يفرزه case_sort
        self.assertEqual(docs[0]['md'], 'markdown/أخرى/a.md')
        self.assertEqual(docs[0]['orig_name'], 'a.pdf')
        self.assertEqual(len(docs[0]['sha1']), 40)

    def test_all_ok_marks_done_and_memory_has_text(self):
        self.batch(['a.pdf', 'b.pdf'])
        self.assertEqual(self.disk()['steps']['documents']['state'], 'done')
        with open(mem.memory_path(self.base), encoding='utf-8', newline='') as f:
            t = f.read()
        self.assertIn('نص a.pdf', t)
        self.assertIn('| P1 |', t)
        self.assertNotIn('بصمة الملف لا تطابق', t)

    def test_reconvert_one_file_fixes_step(self):
        self.batch(['a.pdf', 'b.pdf'], contents={'b.pdf': b'BAD'})
        uid = self.data['portfolios'][0]['docs'][1]['uid']
        with open(os.path.join(self.base, 'أخرى', 'b.pdf'), 'wb') as f:
            f.write(b'GOOD')
        self.assertEqual(cd.reconvert(self.base, self.data, uid, convert=fake_convert), 'done')
        d = self.disk()
        self.assertEqual(d['steps']['documents']['state'], 'done')
        self.assertEqual(d['portfolios'][0]['docs'][1]['convert']['state'], 'done')

    def test_second_batch_continues_numbers_and_seq(self):
        self.batch(['a.pdf'])
        self.batch(['b.pdf', 'c.pdf'])
        docs = self.disk()['portfolios'][0]['docs']
        self.assertEqual([d['no'] for d in docs], [1, 2, 3])
        self.assertEqual([d['file'] for d in docs], ['أخرى/a.pdf', 'أخرى/b.pdf', 'أخرى/c.pdf'])
        self.assertEqual(len({d['uid'] for d in docs}), 3)

    def test_duplicate_numbers_rejected_before_any_copy(self):
        p = cd.add_portfolio(self.data, 'م', '')
        with self.assertRaises(cm.StepError):
            cd.import_batch(self.base, self.data, p['id'],
                            [{'src': self.src('a.pdf'), 'no': 1}, {'src': self.src('b.pdf'), 'no': 1}],
                            convert=fake_convert)
        self.assertFalse(os.path.exists(os.path.join(self.base, '01_اصول', 'P1')))

    def test_missing_source_file_recorded_as_failed(self):
        p = cd.add_portfolio(self.data, 'م', '')
        res = cd.import_batch(self.base, self.data, p['id'],
                              [{'src': os.path.join(self.src_dir, 'ghost.pdf'), 'no': 1}], convert=fake_convert)
        self.assertEqual(res['failed'], 1)
        self.assertIn('تعذّر نسخ', self.disk()['portfolios'][0]['docs'][0]['convert']['message'])

    def test_converter_exception_is_contained(self):
        def boom(_):
            raise RuntimeError('انهيار')
        _, res = self.batch(['a.pdf'], convert=boom)
        self.assertEqual(res['failed'], 1)
        self.assertIn('انهيار', self.disk()['portfolios'][0]['docs'][0]['convert']['message'])

    def test_at_most_two_concurrent_conversions(self):
        active, peak, lock = [0], [0], threading.Lock()

        def slow(path):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.1)
            with lock:
                active[0] -= 1
            return 'نص', 1
        self.batch([f'{i}.pdf' for i in range(6)], convert=slow)
        self.assertLessEqual(peak[0], 2)
        self.assertGreaterEqual(peak[0], 2)

    def test_progress_callbacks(self):
        seen = []
        self.batch(['a.pdf'], on_update=lambda u, c: seen.append(c['state']))
        self.assertEqual(seen, ['running', 'done'])


class RenumberTests(Base):
    def test_renumber_swaps_without_touching_files_or_uids(self):
        self.batch(['a.pdf', 'b.pdf', 'c.pdf'])
        docs = self.data['portfolios'][0]['docs']
        u = [d['uid'] for d in docs]
        files = [d['file'] for d in docs]
        self.assertEqual(cd.renumber(self.base, self.data, 'P1', {u[0]: 3, u[2]: 1}), '')
        d = self.disk()['portfolios'][0]['docs']
        self.assertEqual([x['uid'] for x in d], [u[2], u[1], u[0]])
        self.assertEqual({x['uid']: x['file'] for x in d}, dict(zip(u, files)))
        self.assertEqual([x['no'] for x in d], [1, 2, 3])

    def test_duplicate_numbers_rejected(self):
        self.batch(['a.pdf', 'b.pdf'])
        u = [d['uid'] for d in self.data['portfolios'][0]['docs']]
        with self.assertRaises(cm.StepError):
            cd.renumber(self.base, self.data, 'P1', {u[0]: 2})

    def test_warns_when_research_exists_and_marks_stale(self):
        self.batch(['a.pdf', 'b.pdf'])
        for k in ('mission',):
            cm.set_step(self.data, k, 'running')
            cm.set_step(self.data, k, 'done')
            cm.set_step(self.data, k, 'reviewed')
        cm.set_step(self.data, 'research', 'running')
        cm.set_step(self.data, 'research', 'done')
        self.data['research'] = [{'n': 1, 'state': 'done'}]
        u = [d['uid'] for d in self.data['portfolios'][0]['docs']]
        warn = cd.renumber(self.base, self.data, 'P1', {u[0]: 2, u[1]: 1})
        self.assertIn('بنود', warn)
        self.assertTrue(self.disk()['steps']['research']['stale'])


class WaiveAndMetaTests(Base):
    def test_waive_unblocks_research_attachments_independent(self):
        self.batch(['a.pdf', 'b.pdf'], contents={'b.pdf': b'BAD'})
        for k in ('mission',):
            cm.set_step(self.data, k, 'running')
            cm.set_step(self.data, k, 'done')
            cm.set_step(self.data, k, 'reviewed')
        cm.refresh_blocked(self.data)
        self.assertEqual(cm.state(self.data, 'research'), 'blocked')
        cd.waive_documents(self.base, self.data)
        self.assertEqual(cm.state(self.data, 'research'), 'pending')
        self.assertEqual(cm.state(self.data, 'attachments'), 'done')      # المرفقات تُبنى آلياً بلا انتظار المستندات

    def test_guess_meta_and_set_meta(self):
        g = cd.guess_meta('عقد خدمات رقم C-2020/45 بين الطرفين')
        self.assertEqual(g['type'], 'عقد')
        self.assertEqual(g['contract'], 'C-2020/45')
        self.assertEqual(cd.guess_meta('نص عادي'), {'type': '', 'contract': ''})
        self.batch(['a.pdf'])
        uid = self.data['portfolios'][0]['docs'][0]['uid']
        cd.set_doc_meta(self.base, self.data, uid, type='فاتورة', contract='K1')
        d = self.disk()['portfolios'][0]['docs'][0]
        self.assertEqual((d['type'], d['contract']), ('فاتورة', 'K1'))


class RealConverterTests(Base):
    def test_embedded_text_pdf_and_corrupt_pdf(self):
        import fitz
        pdf = os.path.join(self.src_dir, 'real.pdf')
        doc = fitz.open()
        for i in range(2):
            pg = doc.new_page()
            pg.insert_text((72, 72), f'Invoice number {i + 1} total amount due for services rendered in March')
        doc.save(pdf)
        doc.close()
        text, pages = cd.ocr_to_markdown(pdf)
        self.assertEqual(pages, 2)
        self.assertIn('<!-- صفحة 1 -->', text)
        self.assertIn('<!-- صفحة 2 -->', text)
        self.assertIn('Invoice number 2', text)
        bad = self.src('bad.pdf', b'not a pdf at all')
        with self.assertRaises(cd.ConvertError):
            cd.ocr_to_markdown(bad)
        with self.assertRaises(cd.ConvertError):
            cd.ocr_to_markdown(self.src('x.xyz'))
        # دفعة حقيقية: ملف سليم وتالف
        p = cd.add_portfolio(self.data, 'م', '')
        res = cd.import_batch(self.base, self.data, p['id'],
                              [{'src': pdf, 'no': 1}, {'src': bad, 'no': 2}])
        self.assertEqual((res['done'], res['failed']), (1, 1))

class FingerprintAndPendingTests(Base):
    def test_same_file_twice_in_same_portfolio_converted_once(self):
        calls = []

        def counting(path):
            calls.append(path)
            return fake_convert(path)
        a = self.src('a.pdf')
        p, res = self.batch(['a.pdf'], convert=counting)
        res2 = cd.import_batch(self.base, self.data, p['id'], [{'src': a, 'no': 2}], convert=counting)
        self.assertEqual((res['done'], res2['total'], len(calls)), (1, 0, 1))
        self.assertEqual(len(p['docs']), 1)

    def test_same_bytes_in_other_portfolio_is_allowed(self):
        a = self.src('a.pdf')
        p1 = cd.add_portfolio(self.data, 'المدعية', '')
        p2 = cd.add_portfolio(self.data, 'المدعى عليها', '')
        cd.import_batch(self.base, self.data, p1['id'], [{'src': a, 'no': 1}], convert=fake_convert)
        r = cd.import_batch(self.base, self.data, p2['id'], [{'src': a, 'no': 1}], convert=fake_convert)
        self.assertEqual(r['done'], 1)

    def test_classify_files(self):
        a, b = self.src('a.pdf'), self.src('b.pdf', b'BAD')
        p, _ = self.batch(['a.pdf', 'b.pdf'], contents={'b.pdf': b'BAD'})
        c = self.src('c.pdf')
        got = {os.path.basename(x): st for x, st, _ in cd.classify_files(self.data, [a, b, c], p['id'])}
        self.assertEqual(got, {'a.pdf': 'done', 'b.pdf': 'failed', 'c.pdf': 'new'})

    def test_stop_leaves_pending_and_step_needs_input_then_resume(self):
        flag = {'stop': False}

        def conv_then_stop(path):
            flag['stop'] = True
            return fake_convert(path)
        p = cd.add_portfolio(self.data, 'المدعية', '')
        items = [{'src': self.src(f'{n}.pdf'), 'no': i} for i, n in enumerate('abc', 1)]
        r = cd.import_batch(self.base, self.data, p['id'], items, convert=conv_then_stop, workers=1,
                            stop=lambda: flag['stop'])
        self.assertEqual((r['done'], r['left']), (1, 2))
        self.assertEqual(cm.state(self.data, 'documents'), 'needs_input')
        res = cd.process_pending(self.base, self.data, fake_convert)
        self.assertEqual((res['done'], res['left']), (2, 0))
        self.assertEqual(cm.state(self.data, 'documents'), 'done')

    def test_running_after_crash_becomes_pending_again(self):
        p, _ = self.batch(['a.pdf'])
        p['docs'][0]['convert'] = {'state': 'running', 'message': ''}
        self.assertTrue(cd.recover_running(self.data))
        self.assertEqual(len(cd.pending_docs(self.data)), 1)

    def test_attachments_follow_documents_automatically(self):
        self.batch(['a.pdf'])
        self.assertEqual(cm.state(self.data, 'attachments'), 'done')
        self.assertTrue(any('حافظة مستندات المدعية' in a['title'] for a in self.data['attachments']))



if __name__ == '__main__':
    unittest.main()


class DuplicateTextTests(Base):
    """ملف md/txt بمحتوى مطابق (باسم أو حافظة مختلفة): يُعاد استعمال الناتج ويُسجَّل مرجع بلا تحويل ولا تكرار في الملخص."""

    TEXT = 'استلمنا المحضر الأول.\nالمبلغ المتفق عليه ألف دينار.\n'.encode('utf-8')

    def two_portfolios(self):
        p1 = cd.add_portfolio(self.data, 'المدعية', '2026-09-01')
        p2 = cd.add_portfolio(self.data, 'المدعى عليها', '2026-09-10')
        return p1, p2

    def add(self, pid, name, content):
        items = cd.plan_batch(self.data, pid, [self.src(name, content)])
        return cd.add_files(self.base, self.data, pid, items)

    def test_same_content_other_portfolio_other_name_is_reference_not_conversion(self):
        p1, p2 = self.two_portfolios()
        first = self.add(p1['id'], 'مذكرة.md', self.TEXT)[0]
        second = self.add(p2['id'], 'نسخة مختلفة.txt', self.TEXT.replace(b'\n', b'\r\n') + b'  ')[0]
        self.assertEqual(second.get('ref_of'), first['uid'])
        self.assertEqual(second['md'], first['md'])                       # لا ملف md جديد
        self.assertEqual(second['convert']['state'], 'done')
        self.assertIn('لم يُحوَّل ثانية', second['convert']['message'])
        mds = [m for _, _, fs in os.walk(os.path.join(self.base, 'markdown')) for m in fs if m.endswith('.md')]
        self.assertEqual(len(mds), 1)

    def test_reference_not_repeated_in_memory_text_or_research_inputs(self):
        import case_research as cr
        p1, p2 = self.two_portfolios()
        self.add(p1['id'], 'a.md', self.TEXT)
        self.add(p2['id'], 'b.md', self.TEXT)
        cd.process_pending(self.base, self.data)
        texts = cr._doc_texts(self.base, self.data)
        self.assertEqual(len(texts), 1)
        self.assertEqual(sum(1 for _ in cd.all_docs(self.data)), 2)        # المرجع باقٍ في الجدول
        self.assertEqual(len(list(cd.content_docs(self.data))), 1)
        table = mem._docs_table(self.base, self.data)
        self.assertIn('مرجع: P1-', table)
        self.assertEqual(mem._docs_text(self.base, self.data).count('المبلغ المتفق عليه'), 1)

    def test_same_content_same_portfolio_is_skipped(self):
        p1, _p2 = self.two_portfolios()
        self.add(p1['id'], 'a.md', self.TEXT)
        again = self.add(p1['id'], 'b.md', self.TEXT + b'\n')
        self.assertEqual(again, [])

    def test_different_content_not_deduped(self):
        p1, p2 = self.two_portfolios()
        self.add(p1['id'], 'a.md', self.TEXT)
        other = self.add(p2['id'], 'b.md', self.TEXT + 'سطر إضافي'.encode('utf-8'))
        self.assertFalse(other[0].get('ref_of'))
