# اختبارات تصنيف المستندات وتوجيهها (2026-10-17): python -W ignore -m unittest test_doc_router -v
# كلها بلا اتصال حيّ: مزوّد Gemini وهمي، وOCR خارجي مُحاكى، وملف إعدادات مؤقت.
import json
import os
import tempfile
import unittest
from unittest import mock

import case_documents as cd
import case_model as cm
import case_workspace as cw
import doc_router as dr

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)

SAMPLES = {
    dr.T_PORTFOLIO: 'حافظة مستندات مقدمة من المدعية في الدعوى رقم 5 لسنة 2026',
    dr.T_DEFENSE: 'مذكرة بدفاع المدعى عليها في الدعوى رقم 5 لسنة 2026',
    dr.T_MINUTES: 'محضر أعمال الخبير المنتدب في الدعوى رقم 5 لسنة 2026',
    dr.T_PLAINT: 'صحيفة دعوى مقدمة إلى محكمة الكويت الكلية',
    dr.T_JUDGMENT: 'باسم حضرة صاحب السمو أمير البلاد حكمت المحكمة حضورياً',
}


def make_pdf(path, pages, label='PAGE', first_text=None):
    import fitz
    doc = fitz.open()
    for i in range(pages):
        pg = doc.new_page()
        txt = first_text if (i == 0 and first_text) else f'{label} {i + 1}'
        pg.insert_text((72, 100), txt, fontsize=14)
    doc.save(path)
    doc.close()


class IniCase(unittest.TestCase):
    """ملف gemini_network.ini مؤقت لكل اختبار."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ini = os.path.join(self._tmp.name, 'gemini_network.ini')
        open(self.ini, 'w', encoding='utf-8').write('[network]\nproxy_url = \n')
        self._p = mock.patch.object(dr, '_ini_path', return_value=self.ini)
        self._p.start()
        self.addCleanup(self._p.stop)
        self._best = mock.patch.object(dr, 'best_engine', return_value=dr.ENGINE_GEMINI)   # لا نقرأ إعدادات الجهاز
        self._best.start()
        self.addCleanup(self._best.stop)
        self.addCleanup(self._tmp.cleanup)


class ClassifyTests(IniCase):
    def test_each_type_is_detected_with_reason(self):
        for t, text in SAMPLES.items():
            r = dr.classify_text(text)
            self.assertEqual(r['type'], t, (t, r))
            self.assertGreater(r['confidence'], 0)
            self.assertIn('تطابق', r['reason'])

    def test_unknown_when_nothing_matches(self):
        r = dr.classify_text('نص عشوائي لا علاقة له بأي نوع')
        self.assertEqual((r['type'], r['confidence']), (dr.T_UNKNOWN, 0.0))
        self.assertTrue(r['reason'])

    def test_tie_is_unknown(self):
        r = dr.classify_text('مذكرة بدفاع وصحيفة دعوى')
        self.assertEqual(r['type'], dr.T_UNKNOWN)
        self.assertIn('تعادل', r['reason'])

    def test_low_confidence_is_unknown_and_threshold_is_configurable(self):
        text = 'مذكرة دفاع'                         # تطابق وحيد ← ثقة 0.5
        self.assertEqual(dr.classify_text(text)['confidence'], 0.5)
        self.assertEqual(dr.classify_text(text)['type'], dr.T_DEFENSE)
        open(self.ini, 'a', encoding='utf-8').write('\n[doc_classify]\nmin_confidence = 0.9\n')
        self.assertEqual(dr.classify_text(text)['type'], dr.T_UNKNOWN)

    def test_keywords_editable_in_ini(self):
        open(self.ini, 'a', encoding='utf-8').write('\n[doc_types]\nحكم = ZZTOP | كلمتي\n')
        self.assertEqual(dr.classify_text('هذه كلمتي وZZTOP')['type'], dr.T_JUDGMENT)
        self.assertEqual(dr.classify_text(SAMPLES[dr.T_JUDGMENT])['type'], dr.T_UNKNOWN)   # القائمة استُبدلت
        self.assertEqual(dr.classify_text(SAMPLES[dr.T_DEFENSE])['type'], dr.T_DEFENSE)   # الأنواع الأخرى افتراضية

    def test_normalisation_variants(self):
        self.assertEqual(dr.classify_text('محضر اعمال الخبير')['type'], dr.T_MINUTES)   # أ/ا
        self.assertEqual(dr.classify_text('صحيفة دعوي')['type'], dr.T_PLAINT)           # ى/ي
        self.assertEqual(dr.classify_text('صحيفة دعوى')['type'], dr.T_PLAINT)

    def test_classify_file_reads_first_page_only(self):
        open(self.ini, 'a', encoding='utf-8').write('\n[doc_types]\nمذكرة دفاع = DEFENSE MEMO | MEMO OF DEFENSE\n')
        p = os.path.join(self._tmp.name, 'a.pdf')
        make_pdf(p, 3, first_text='DEFENSE MEMO of the defendant in case number 5 of 2026')
        r = dr.classify_file(p)
        self.assertEqual(r['type'], dr.T_DEFENSE)
        self.assertIn('DEFENSE MEMO', r['snippet'])

    def test_classify_file_on_bad_file_is_unknown_with_reason(self):
        p = os.path.join(self._tmp.name, 'bad.pdf')
        open(p, 'wb').write(b'BAD')
        r = dr.classify_file(p)
        self.assertEqual(r['type'], dr.T_UNKNOWN)
        self.assertIn('تعذّرت قراءة', r['reason'])


class RoutingAndLimitsTests(IniCase):
    def test_default_routing(self):
        self.assertEqual(dr.engine_for(dr.T_DEFENSE), dr.ENGINE_EXTERNAL)
        self.assertEqual(dr.engine_for(dr.T_PORTFOLIO), dr.ENGINE_GEMINI)
        self.assertEqual(dr.engine_for(dr.T_MINUTES), dr.ENGINE_LOCAL)
        self.assertIsNone(dr.engine_for(dr.T_UNKNOWN))

    def test_routing_is_configurable_and_bad_value_ignored(self):
        open(self.ini, 'a', encoding='utf-8').write('\n[doc_routing]\nمحضر أعمال = gemini\nحكم = nonsense\n')
        self.assertEqual(dr.engine_for(dr.T_MINUTES), dr.ENGINE_GEMINI)
        self.assertEqual(dr.engine_for(dr.T_JUDGMENT), dr.ENGINE_GEMINI)       # قيمة غير صالحة ← الافتراضي «best»

    def test_ensure_defaults_writes_missing_sections_only(self):
        self.assertTrue(dr.ensure_defaults())
        txt = open(self.ini, encoding='utf-8').read()
        for sec in ('[doc_types]', '[doc_routing]', '[gemini_limits]', '[doc_classify]', '[network]'):
            self.assertIn(sec, txt)
        lim = dr.gemini_limits()
        self.assertEqual((lim['max_pages'], lim['max_bytes'], lim['verified']), (1000, 50 * 1024 * 1024, '2026-10-17'))
        self.assertIn('ai.google.dev', lim['source'])
        self.assertFalse(dr.ensure_defaults())                                   # لا تكرار
        self.assertEqual(txt, open(self.ini, encoding='utf-8').read())

    def test_plaint_and_judgment_default_to_best_engine(self):
        self.assertEqual(dr.routing()[dr.T_PLAINT], dr.ENGINE_BEST)
        self.assertEqual(dr.routing()[dr.T_JUDGMENT], dr.ENGINE_BEST)
        for best in (dr.ENGINE_GEMINI, dr.ENGINE_EXTERNAL, dr.ENGINE_LOCAL):
            with mock.patch.object(dr, 'best_engine', return_value=best):
                self.assertEqual(dr.engine_for(dr.T_PLAINT), best)
                self.assertEqual(dr.engine_for(dr.T_JUDGMENT), best)
                self.assertEqual(dr.engine_for(dr.T_MINUTES), dr.ENGINE_LOCAL)      # غيرهما لا يتأثر

    def test_manual_choice_overrides_best(self):
        open(self.ini, 'a', encoding='utf-8').write('\n[doc_routing]\nصحيفة دعوى = local\nroutingversion = 2\nrouting_version = 2\n')
        self.assertEqual(dr.engine_for(dr.T_PLAINT), dr.ENGINE_LOCAL)

    def test_old_ini_with_local_default_is_migrated_once(self):
        open(self.ini, 'a', encoding='utf-8').write(
            '\n[doc_routing]\nمذكرة دفاع = external_ocr\nصحيفة دعوى = local\nحكم = local\nمحضر أعمال = gemini\n')
        self.assertTrue(dr.ensure_defaults())
        self.assertEqual(dr.routing()[dr.T_PLAINT], dr.ENGINE_BEST)
        self.assertEqual(dr.routing()[dr.T_JUDGMENT], dr.ENGINE_BEST)
        self.assertEqual(dr.routing()[dr.T_MINUTES], dr.ENGINE_GEMINI)               # اختيار الخبير لا يُمسّ
        # بعد الترحيل: اختيار «local» اليدوي اللاحق يبقى
        txt = open(self.ini, encoding='utf-8').read().replace('صحيفة دعوى = best', 'صحيفة دعوى = local')
        open(self.ini, 'w', encoding='utf-8').write(txt)
        dr.ensure_defaults()
        self.assertEqual(dr.routing()[dr.T_PLAINT], dr.ENGINE_LOCAL)

    def test_ensure_defaults_keeps_user_edits(self):
        open(self.ini, 'a', encoding='utf-8').write('\n[doc_routing]\nحكم = gemini\n')
        dr.ensure_defaults()
        self.assertEqual(dr.engine_for(dr.T_JUDGMENT), dr.ENGINE_GEMINI)
        self.assertEqual(txt_count(self.ini, '[doc_routing]'), 1)

    def test_limits_text_mentions_verification_date(self):
        dr.ensure_defaults()
        t = dr.limits_text()
        self.assertIn('1000', t)
        self.assertIn('50MB', t)
        self.assertIn('2026-10-17', t)


def txt_count(path, needle):
    return open(path, encoding='utf-8').read().count(needle)


class FakeGemini:
    """مزوّد وهمي: يردّ بنص كل صفحة من الجزء المرسل (مستخرجاً بـpypdf) مفصولاً بعلامة الصفحة."""
    def __init__(self, wrong_count=False, empty=False):
        self.calls, self.wrong_count, self.empty = [], wrong_count, empty

    def generate(self, prompt, prep, route, timeout):
        from pypdf import PdfReader
        pages = [pg.extract_text().strip() or 'IMG' for pg in PdfReader(prep['path']).pages]
        self.calls.append(pages)
        if self.empty:
            return mock.Mock(text='')
        if self.wrong_count:
            return mock.Mock(text=' '.join(pages))
        return mock.Mock(text=dr.PAGE_SEP.join(pages))


class SplitTests(IniCase):
    def setUp(self):
        super().setUp()
        self.tmp2 = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp2, ignore_errors=True))

    def pdf(self, pages, name='big.pdf'):
        p = os.path.join(self._tmp.name, name)
        make_pdf(p, pages)
        return p

    def test_no_split_within_limits(self):
        p = self.pdf(5)
        self.assertEqual(dr.plan_chunks(p, self.tmp2, 10, 10_000_000), [(0, 5, p)])

    def test_split_by_pages_covers_everything_in_order(self):
        p = self.pdf(25)
        chunks = dr.plan_chunks(p, self.tmp2, 10, 10_000_000)
        self.assertGreater(len(chunks), 2)
        self.assertEqual(chunks[0][0], 0)
        self.assertEqual(chunks[-1][1], 25)
        for (a, b, _), (a2, _b2, _) in zip(chunks, chunks[1:]):
            self.assertEqual(b, a2)
        self.assertTrue(all(b - a <= 10 for a, b, _ in chunks))
        self.assertEqual(sum(dr.page_count(c) for _, _, c in chunks), 25)

    def test_split_by_size(self):
        p = self.pdf(12)
        size = os.path.getsize(p)
        chunks = dr.plan_chunks(p, self.tmp2, 1000, size // 3)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(os.path.getsize(c) <= size // 3 for _, _, c in chunks))

    def test_single_page_over_size_raises(self):
        p = self.pdf(2)
        with self.assertRaises(ValueError):
            dr.plan_chunks(p, self.tmp2, 1000, 100)

    def test_chunk_pages_app_setting_splits_even_under_gemini_limits(self):
        p = self.pdf(9)
        self.assertEqual(len(dr.plan_chunks(p, self.tmp2, 1000, 10_000_000, chunk_pages=4)), 3)

    def test_gemini_engine_splits_and_keeps_original_numbering(self):
        fake = FakeGemini()
        msgs = []
        p = self.pdf(25)
        with mock.patch.object(dr, 'GEMINI_PROVIDER_FACTORY', lambda: fake):
            eng = dr.gemini_engine(lambda path: ('LOCAL', 1),
                                   limits={'max_pages': 10, 'max_bytes': 10_000_000, 'chunk_pages': 0},
                                   status=msgs.append)
            md, pages, warn = eng(p, {})
        self.assertEqual((pages, warn), (25, ''))
        self.assertGreater(len(fake.calls), 2)
        for n in (1, 10, 11, 25):                    # ترقيم أصلي لا ترقيم الجزء
            self.assertIn(f'<!-- صفحة {n} -->\nPAGE {n}', md)
        order = [md.index(f'<!-- صفحة {n} -->') for n in range(1, 26)]
        self.assertEqual(order, sorted(order))
        self.assertTrue(any('قُسّم إلى' in m for m in msgs))

    def test_no_split_when_within_limits_single_call(self):
        fake = FakeGemini()
        p = self.pdf(4)
        with mock.patch.object(dr, 'GEMINI_PROVIDER_FACTORY', lambda: fake):
            md, pages, warn = dr.gemini_engine(lambda path: ('L', 1), limits=dr.gemini_limits())(p, {})
        self.assertEqual((len(fake.calls), pages, warn), (1, 4, ''))

    def test_image_input_is_converted_and_sent(self):
        import fitz
        pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
        pm.clear_with(255)
        img = os.path.join(self._tmp.name, 'a.png')
        pm.save(img)
        fake = FakeGemini()
        with mock.patch.object(dr, 'GEMINI_PROVIDER_FACTORY', lambda: fake):
            md, pages, _ = dr.gemini_engine(lambda path: ('L', 1), limits=dr.gemini_limits())(img, {})
        self.assertEqual((pages, len(fake.calls)), (1, 1))

    def test_page_count_mismatch_warns_and_still_keeps_text(self):
        fake = FakeGemini(wrong_count=True)
        p = self.pdf(3)
        with mock.patch.object(dr, 'GEMINI_PROVIDER_FACTORY', lambda: fake):
            md, pages, warn = dr.gemini_engine(lambda path: ('L', 1), limits=dr.gemini_limits())(p, {})
        self.assertIn('لا يطابق', warn)
        self.assertIn('PAGE 1', md)
        self.assertIn('صفحات 1–3', md)

    def test_empty_gemini_reply_raises(self):
        fake = FakeGemini(empty=True)
        p = self.pdf(2)
        with mock.patch.object(dr, 'GEMINI_PROVIDER_FACTORY', lambda: fake):
            with self.assertRaises(RuntimeError):
                dr.gemini_engine(lambda path: ('L', 1), limits=dr.gemini_limits())(p, {})

    def test_no_gemini_falls_back_to_local_with_warning(self):
        def none():
            raise dr.EngineUnavailable('لا يوجد مفتاح Gemini مضبوط')
        p = self.pdf(2)
        with mock.patch.object(dr, 'GEMINI_PROVIDER_FACTORY', none):
            md, pages, warn = dr.gemini_engine(lambda path: ('LOCALTEXT', 2), limits=dr.gemini_limits())(p, {})
        self.assertEqual((md, pages), ('LOCALTEXT', 2))
        self.assertIn('استُعمل OCR المحلي', warn)


class ExternalOcrTests(IniCase):
    def test_not_configured_falls_back_to_local_with_warning(self):
        import ocr_space
        p = os.path.join(self._tmp.name, 'a.pdf')
        make_pdf(p, 2)
        with mock.patch.object(ocr_space, 'is_available', return_value=False):
            md, pages, warn = dr.external_ocr_engine(lambda path: ('LOCAL', 2))(p, {})
        self.assertEqual((md, pages), ('LOCAL', 2))
        self.assertIn('غير مضبوط', warn)

    def test_configured_uses_external_and_numbers_pages(self):
        import gemini_config as gc
        import ocr_space
        p = os.path.join(self._tmp.name, 'a.pdf')
        make_pdf(p, 2)
        raw = '--- صفحة 1 ---\nالنص الأول\n\n--- صفحة 2 ---\nالنص الثاني'
        with mock.patch.object(ocr_space, 'is_available', return_value=True), \
                mock.patch.object(ocr_space, 'ocr_pages', return_value=raw) as op, \
                mock.patch.object(gc, '_run_with_routes', side_effect=lambda fn, size, t: fn('direct')), \
                mock.patch.object(gc, 'feature_on', return_value=True):
            md, pages, warn = dr.external_ocr_engine(lambda path: ('LOCAL', 2))(p, {})
        self.assertEqual((pages, warn), (2, ''))
        self.assertEqual(op.call_args[0][1], [0, 1])
        self.assertIn('<!-- صفحة 2 -->\nالنص الثاني', md)

    def test_external_failure_falls_back_with_reason(self):
        import gemini_config as gc
        import ocr_space
        p = os.path.join(self._tmp.name, 'a.pdf')
        make_pdf(p, 1)
        with mock.patch.object(ocr_space, 'is_available', return_value=True), \
                mock.patch.object(gc, '_run_with_routes', side_effect=RuntimeError('حد الاستخدام')), \
                mock.patch.object(gc, 'feature_on', return_value=True):
            md, pages, warn = dr.external_ocr_engine(lambda path: ('LOCAL', 1))(p, {})
        self.assertEqual(md, 'LOCAL')
        self.assertIn('حد الاستخدام', warn)


# ---------- التكامل مع case_documents / case.json ----------

def record_engines(log):
    def mk(name):
        def run(path, doc):
            log.append((name, doc['orig_name']))
            return f'<!-- صفحة 1 -->\nمن {name}', 1, ''
        return run
    return {e: mk(e) for e in dr.ENGINES}


class IntegrationTests(IniCase):
    def setUp(self):
        super().setUp()
        self.base, self.data = cw.ensure_workspace(CASE, os.path.join(self._tmp.name, 'ws'))
        self.src = os.path.join(self._tmp.name, 'src')
        os.makedirs(self.src)
        self.portfolio = cd.add_portfolio(self.data, 'المدعية', '2026-09-01')

    def add(self, specs, classify):
        """specs: {اسم: نوع يرجعه المصنِّف}"""
        paths = []
        for n in specs:
            p = os.path.join(self.src, n)
            open(p, 'wb').write(n.encode())
            paths.append(p)
        items = cd.plan_batch(self.data, self.portfolio['id'], paths)
        return cd.add_files(self.base, self.data, self.portfolio['id'], items, classify=self._cls(specs))

    def _cls(self, specs):
        # المسار المنسوخ داخل 01_اصول لا يحمل الاسم الأصلي؛ نطابق بمحتوى الملف (اسمه)
        def f(path):
            name = open(path, 'rb').read().decode()
            t = specs[name]
            return {'type': t, 'confidence': 0.0 if t == dr.T_UNKNOWN else 0.9, 'reason': f'اختبار {t}',
                    'snippet': 'نص الصفحة الأولى'}
        return f

    def test_every_type_is_recorded_in_case_json_and_routed(self):
        specs = {'a.pdf': dr.T_PORTFOLIO, 'b.pdf': dr.T_DEFENSE, 'c.pdf': dr.T_MINUTES,
                 'd.pdf': dr.T_PLAINT, 'e.pdf': dr.T_JUDGMENT}
        docs = self.add(specs, None)
        disk = {d['orig_name']: d for _, d in cd.all_docs(cw.read_case_json(self.base))}
        expected = {'a.pdf': 'gemini', 'b.pdf': 'external_ocr', 'c.pdf': 'local', 'd.pdf': 'gemini', 'e.pdf': 'gemini'}
        for n, t in specs.items():
            self.assertEqual(disk[n]['doc_type'], t)
            self.assertEqual(disk[n]['engine'], expected[n])
            self.assertEqual(disk[n]['type_conf'], 0.9)
            self.assertEqual(disk[n]['type_reason'], f'اختبار {t}')
            self.assertFalse(disk[n]['needs_type'])
        log = []
        res = cd.process_pending(self.base, self.data, engines=record_engines(log))
        self.assertEqual((res['done'], res['failed']), (5, 0))
        self.assertEqual(dict((n, e) for e, n in log), {n: expected[n] for n in specs})

    def test_unknown_is_held_until_expert_chooses(self):
        self.add({'a.pdf': dr.T_MINUTES, 'u.pdf': dr.T_UNKNOWN}, None)
        d = {x['orig_name']: x for _, x in cd.all_docs(self.data)}
        self.assertTrue(d['u.pdf']['needs_type'])
        self.assertEqual(d['u.pdf']['engine'], '')
        self.assertEqual([x['orig_name'] for x in cd.pending_docs(self.data)], ['a.pdf'])
        log = []
        res = cd.process_pending(self.base, self.data, engines=record_engines(log))
        self.assertEqual(res['total'], 1)
        self.assertEqual([n for _, n in log], ['a.pdf'])                     # لم يُحوَّل غير المعروف
        self.assertEqual(d['u.pdf']['convert']['state'], 'pending')
        step = self.data['steps']['documents']
        self.assertEqual(step['state'], 'needs_input')
        self.assertIn('بانتظار اختيار نوعه', step['message'])
        # الخبير يختار ← يصير جاهزاً بمحرّك نوعه ويُحوَّل
        cd.set_doc_type(self.base, self.data, d['u.pdf']['uid'], dr.T_DEFENSE)
        self.assertEqual((d['u.pdf']['engine'], d['u.pdf']['manual'], d['u.pdf']['needs_type']),
                         ('external_ocr', True, False))
        res = cd.process_pending(self.base, self.data, engines=record_engines(log))
        self.assertEqual(res['done'], 1)
        self.assertEqual(log[-1], ('external_ocr', 'u.pdf'))
        self.assertEqual(cm.state(self.data, 'documents'), 'done')

    def test_manual_type_and_engine_change_before_conversion(self):
        self.add({'a.pdf': dr.T_MINUTES}, None)
        d = next(x for _, x in cd.all_docs(self.data))
        cd.set_doc_type(self.base, self.data, d['uid'], dr.T_PORTFOLIO)
        self.assertEqual(d['engine'], 'gemini')
        cd.set_doc_engine(self.base, self.data, d['uid'], 'local')
        disk = next(x for _, x in cd.all_docs(cw.read_case_json(self.base)))
        self.assertEqual((disk['doc_type'], disk['engine'], disk['manual']), (dr.T_PORTFOLIO, 'local', True))
        log = []
        cd.process_pending(self.base, self.data, engines=record_engines(log))
        self.assertEqual(log, [('local', 'a.pdf')])                           # المحرّك اليدوي هو المستعمل

    def test_change_rejected_after_conversion_and_for_invalid_values(self):
        self.add({'a.pdf': dr.T_MINUTES}, None)
        d = next(x for _, x in cd.all_docs(self.data))
        with self.assertRaises(cm.StepError):
            cd.set_doc_type(self.base, self.data, d['uid'], 'نوع وهمي')
        with self.assertRaises(cm.StepError):
            cd.set_doc_engine(self.base, self.data, d['uid'], 'nope')
        cd.process_pending(self.base, self.data, engines=record_engines([]))
        with self.assertRaises(cm.StepError):
            cd.set_doc_type(self.base, self.data, d['uid'], dr.T_DEFENSE)
        with self.assertRaises(cm.StepError):
            cd.set_doc_engine(self.base, self.data, d['uid'], 'gemini')

    def test_engine_choice_on_unknown_requires_type_first(self):
        self.add({'u.pdf': dr.T_UNKNOWN}, None)
        d = next(x for _, x in cd.all_docs(self.data))
        with self.assertRaises(cm.StepError):
            cd.set_doc_engine(self.base, self.data, d['uid'], 'local')

    def test_failed_doc_can_switch_engine_then_retry(self):
        self.add({'a.pdf': dr.T_PORTFOLIO}, None)
        d = next(x for _, x in cd.all_docs(self.data))
        eng = record_engines([])
        eng['gemini'] = lambda path, doc: (_ for _ in ()).throw(cd.ConvertError('تجاوز الحد'))
        cd.process_pending(self.base, self.data, engines=eng)
        self.assertEqual(d['convert']['state'], 'failed')
        cd.set_doc_engine(self.base, self.data, d['uid'], 'local')
        self.assertEqual(cd.reconvert(self.base, self.data, d['uid'], engines=eng), 'done')

    def test_over_limit_with_fake_provider_end_to_end(self):
        fake = FakeGemini()
        src = os.path.join(self.src, 'big.pdf')
        make_pdf(src, 23)
        specs_cls = lambda path: {'type': dr.T_PORTFOLIO, 'confidence': 0.9, 'reason': 'x', 'snippet': ''}
        items = cd.plan_batch(self.data, self.portfolio['id'], [src])
        cd.add_files(self.base, self.data, self.portfolio['id'], items, classify=specs_cls)
        engines = dr.build_engines(lambda path: ('LOCAL', 1))
        engines['gemini'] = dr.gemini_engine(lambda path: ('LOCAL', 1),
                                             limits={'max_pages': 8, 'max_bytes': 10_000_000, 'chunk_pages': 0})
        with mock.patch.object(dr, 'GEMINI_PROVIDER_FACTORY', lambda: fake):
            res = cd.process_pending(self.base, self.data, engines=engines)
        self.assertEqual((res['done'], res['failed']), (1, 0))
        d = next(x for _, x in cd.all_docs(self.data))
        self.assertEqual(d['pages'], 23)
        md = open(os.path.join(self.base, d['md']), encoding='utf-8').read()
        self.assertGreater(len(fake.calls), 2)
        for n in range(1, 24):
            self.assertIn(f'<!-- صفحة {n} -->\nPAGE {n}', md)

    def test_warning_is_recorded_and_embedded_in_markdown(self):
        self.add({'a.pdf': dr.T_PORTFOLIO}, None)
        eng = record_engines([])
        eng['gemini'] = lambda path, doc: ('<!-- صفحة 1 -->\nx', 1, 'Gemini غير متاح — استُعمل OCR المحلي')
        cd.process_pending(self.base, self.data, engines=eng)
        d = next(x for _, x in cd.all_docs(cw.read_case_json(self.base)))
        self.assertIn('استُعمل OCR المحلي', d['warning'])
        md = open(os.path.join(self.base, d['md']), encoding='utf-8').read()
        self.assertTrue(md.startswith('<!-- ⚠ Gemini غير متاح'))

    def test_classifier_exception_makes_unknown(self):
        p = os.path.join(self.src, 'a.pdf')
        open(p, 'wb').write(b'a')
        items = cd.plan_batch(self.data, self.portfolio['id'], [p])

        def boom(path):
            raise OSError('x')
        cd.add_files(self.base, self.data, self.portfolio['id'], items, classify=boom)
        d = next(x for _, x in cd.all_docs(self.data))
        self.assertEqual((d['doc_type'], d['needs_type']), (dr.T_UNKNOWN, True))
        self.assertIn('تعذّر التصنيف', d['type_reason'])

    def test_real_classifier_end_to_end_with_latin_keywords(self):
        open(self.ini, 'a', encoding='utf-8').write(
            '\n[doc_types]\nمذكرة دفاع = DEFENSE MEMO\nحافظة مستندات = FOLDER LIST\n')
        a, u = os.path.join(self.src, 'a.pdf'), os.path.join(self.src, 'u.pdf')
        make_pdf(a, 2, first_text='DEFENSE MEMO of the defendant in case number 5 of 2026')
        make_pdf(u, 2, first_text='Nothing relevant here at all in this long first page text')
        items = cd.plan_batch(self.data, self.portfolio['id'], [a, u])
        cd.add_files(self.base, self.data, self.portfolio['id'], items, classify=dr.classify_file)
        d = {x['orig_name']: x for _, x in cd.all_docs(self.data)}
        self.assertEqual((d['a.pdf']['doc_type'], d['a.pdf']['engine']), (dr.T_DEFENSE, 'external_ocr'))
        self.assertEqual((d['u.pdf']['doc_type'], d['u.pdf']['needs_type']), (dr.T_UNKNOWN, True))
        self.assertIn('Nothing relevant here', d['u.pdf']['first_text'])


if __name__ == '__main__':
    unittest.main()


class QualityTests(unittest.TestCase):
    GOOD = ('المدعى عليه أخل في سداد قيمة الأعمال التي نفذتها المدعية على الرغم من إنذاره عدة مرات وقد طلبت الحكم '
            'بإلزامه بالمبلغ وذلك بموجب عقد مؤرخ في عام ألفين وخمسة وعشرين وأن المحكمة قد قضت بإحالة الدعوى إلى '
            'الخبير لبيان ما إذا كان العقد قد نفذ أم لا وما هي المبالغ التي استحقت للمدعية عن هذه الأعمال')
    BAD = 'ا1ل|مدءى عليهة ااالل ببببب فيي ممنن ءلى 5لدعوى ' * 12

    def test_clean_text_is_ok(self):
        q = dr.text_quality(self.GOOD)
        self.assertTrue(q['ok'])
        self.assertEqual(dr.quality_warning(dr.T_PLAINT, self.GOOD), '')

    def test_garbled_text_is_weak_with_message(self):
        q = dr.text_quality(self.BAD)
        self.assertTrue(q['weak'])
        w = dr.quality_warning(dr.T_PLAINT, self.BAD)
        self.assertIn('جودة قراءة الصحيفة ضعيفة، أعد قراءتها بمحرك أقوى', w)
        self.assertTrue(dr.quality_warning(dr.T_JUDGMENT, self.BAD))

    def test_only_key_documents_are_checked_and_empty_is_weak(self):
        self.assertEqual(dr.quality_warning(dr.T_MINUTES, self.BAD), '')
        self.assertTrue(dr.text_quality('   ')['weak'])

    def test_short_text_not_judged(self):
        self.assertFalse(dr.text_quality('حكمت المحكمة')['weak'])


class RereadStrongerTests(unittest.TestCase):
    def test_stronger_engine_ranking(self):
        import case_documents as cdoc
        with mock.patch.object(dr, 'best_engine', return_value=dr.ENGINE_GEMINI):
            self.assertEqual(cdoc.stronger_engine({'engine': 'local'}), 'gemini')
            self.assertEqual(cdoc.stronger_engine({'engine': 'external_ocr'}), 'gemini')
            self.assertIsNone(cdoc.stronger_engine({'engine': 'gemini'}))
        with mock.patch.object(dr, 'best_engine', return_value=dr.ENGINE_LOCAL):
            self.assertIsNone(cdoc.stronger_engine({'engine': 'local'}))


class BatchAndRetryTests(SplitTests):
    """دفعات صفحات بدل طلب لكل صفحة، وإعادة المحاولة عند حدّ الطلبات."""

    def test_batch_pages_sends_many_pages_per_request_in_order(self):
        fake = FakeGemini()
        p = self.pdf(45)
        lim = {'max_pages': 1000, 'max_bytes': 10_000_000, 'chunk_pages': 0, 'batch_pages': 20}
        with mock.patch.object(dr, 'GEMINI_PROVIDER_FACTORY', lambda: fake):
            md, pages, warn = dr.gemini_engine(lambda path: ('L', 1), limits=lim)(p, {})
        self.assertEqual([len(c) for c in fake.calls], [20, 20, 5])     # 3 دفعات متتالية: أول 20 صفحة ثم التالية
        self.assertEqual(pages, 45)
        self.assertIn('<!-- صفحة 45 -->\nPAGE 45', md)

    def test_default_batch_is_configured_in_ini_not_one_per_page(self):
        self.assertGreater(dr.gemini_limits()['batch_pages'], 1)

    def test_rate_limit_not_retried_on_same_batch(self):
        """2026-10-25: لا إعادة للدفعة هنا — الطلب المرفوض يستهلك الحصة؛ النموذج التالي تتولاه سياسة gemini_config."""
        calls, waits = [], []

        class Flaky:
            def generate(self_, prompt, prep, route, timeout):
                calls.append(1)
                raise RuntimeError('429 RESOURCE_EXHAUSTED. Please retry in 7.2s')
        p = self.pdf(2)
        with mock.patch.object(dr, 'SLEEP', waits.append):
            with self.assertRaises(RuntimeError):
                dr._call_provider_retry(Flaky(), 'pr', p, 2, {'retries': 3, 'retry_wait': 30})
        self.assertEqual(len(calls), 1)
        self.assertEqual(waits, [])

    def test_other_errors_not_retried_and_retries_bounded(self):
        class Bad:
            n = 0

            def generate(self_, *a):
                Bad.n += 1
                raise RuntimeError('400 INVALID_ARGUMENT')
        p = self.pdf(2)
        with mock.patch.object(dr, 'SLEEP', lambda s: None):
            with self.assertRaises(RuntimeError):
                dr._call_provider_retry(Bad(), 'pr', p, 2, {'retries': 3})
        self.assertEqual(Bad.n, 1)

        class Limited:
            n = 0

            def generate(self_, *a):
                Limited.n += 1
                raise RuntimeError('429 quota')
        with mock.patch.object(dr, 'SLEEP', lambda s: None):
            with self.assertRaises(RuntimeError):
                dr._call_provider_retry(Limited(), 'pr', p, 2, {'retries': 2, 'retry_wait': 1})
        self.assertEqual(Limited.n, 1)


class NumberedPagesTests(unittest.TestCase):
    """(2026-10-25) صفحة ناقصة في ردّ التحويل كانت تدمج الدفعة كلها فتضيع أرقام الصفحات والمستندات."""

    def test_missing_page_stays_empty_not_merged(self):
        texts, w = dr.split_pages('=====PAGE 1=====\nأ\n=====PAGE 3=====\nج', 3)
        self.assertEqual(texts, ['أ', '', 'ج'])
        self.assertIn('(2)', w)

    def test_numbered_all_pages(self):
        self.assertEqual(dr.split_pages('=====PAGE 1=====\nأ\n=====PAGE 2=====\nب', 2), (['أ', 'ب'], ''))

    def test_old_separator_still_works(self):
        self.assertEqual(dr.split_pages(dr.PAGE_SEP.join(['أ', 'ب']), 2), (['أ', 'ب'], ''))

    def test_prompt_keeps_language_and_tables(self):
        p = dr.GEMINI_PROMPT.format(n=4)
        for w in ('بلغته الأصلية', 'دون ترجمة', 'جدول Markdown بعدد أعمدته', '[غير مقروء]', '=====PAGE k=====', '1 إلى 4'):
            self.assertIn(w, p)
        self.assertNotIn('حرفياً بالعربية', p)


class MinutesClassifyTests(unittest.TestCase):
    """(2026-10-25) محضر الخبرة يذكر «قدم الحاضر حافظة مستندات» فصنّفته الكلمات المفتاحية «حافظة مستندات» (67%)."""
    MINUTE = ('فتح المحضر بتاريخه في تمام السـاعة\n12:02\nبمقــر\nإدارة شئون خبراء العاصمة\nرقـم الدعـوى\n'
              'وقدم الحاضر عن المدعية حافظة مستندات طويت على مستندات مقدمة')

    def test_minutes_opening_wins(self):
        r = dr.classify_text(self.MINUTE)
        self.assertEqual((r['type'], r['confidence']), (dr.T_MINUTES, 1.0))

    def test_bundle_still_bundle(self):
        r = dr.classify_text('حافظة مستندات مقدمة من المدعية\nبيان المستندات\n1- صورة من محضر التسليم')
        self.assertEqual(r['type'], dr.T_PORTFOLIO)
