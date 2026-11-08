# ===== test_gemini_routing.py — توجيه نماذج Gemini حسب المهمة + العدّاد المحلي + الدفعات + الطابور (2026-10-23) =====
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

import ai_providers as ap
import gemini_config as gc
import gemini_quota as gq

NAMES = ['gemini-3.8-flash', 'gemini-3.6-flash', 'gemini-2.5-flash', 'gemini-flash-latest',
         'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-flash-lite-latest',
         'gemma-4-31b-it', 'gemma-4-26b-a4b-it', 'gemini-3.1-pro-preview', 'gemini-2.5-flash-preview-tts']


def route(task, **kw):
    return ap.route_models(task, NAMES, routes=dict(ap.MODEL_ROUTES), gemma_max=10_000, **kw)


NAMES2 = NAMES + ['gemini-3-flash-preview', 'gemini-2.5-flash-lite', 'gemini-3.6-flash-preview-09-2026']


class RankTests(unittest.TestCase):
    """تقسيم الإصدارات في دالة rank واحدة: الأسماء الفعلية فقط (لا مستعارة)، بالإصدار ثم المستقر قبل preview."""

    def test_family_and_version(self):
        self.assertEqual(gc.model_family('gemini-3.5-flash-lite'), ('lite', '3.5', False))
        self.assertEqual(gc.model_family('models/gemini-3-flash-preview'), ('flash', '3', True))
        self.assertEqual(gc.model_family('gemini-3.1-pro-preview'), ('pro', '3.1', True))
        self.assertEqual(gc.model_family('gemini-flash-lite-latest')[0], '')          # مستعار ← خارج التوجيه
        self.assertEqual(gc.model_family('gemini-2.5-flash-preview-tts')[0], '')

    def test_rank_versions_and_aliases(self):
        self.assertEqual(gc.rank(NAMES2, 'lite', ('3.5', '3.1')), ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite'])
        self.assertEqual(gc.rank(NAMES2, 'flash'), ['gemini-3.8-flash', 'gemini-3.6-flash',
                                                    'gemini-3.6-flash-preview-09-2026', 'gemini-3-flash-preview',
                                                    'gemini-2.5-flash'])
        self.assertEqual(gc.rank(NAMES2, 'flash', ('3',)), ['gemini-3-flash-preview'])
        self.assertNotIn('gemini-flash-latest', gc.rank_flash(NAMES2))
        self.assertNotIn('gemini-flash-lite-latest', gc.rank_lite(NAMES2))


class RoutingTableTests(unittest.TestCase):
    def test_ocr_and_text_light_lite_35_then_31_only(self):
        for task in ('ocr', 'text_light'):
            r = route(task, media=task == 'ocr', tokens=2_000)
            self.assertEqual(r, ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite'])      # بلا Gemma ولا Flash ولا مستعار

    def test_write_flash_36_then_last_resort(self):
        r = ap.route_models('write', NAMES2, routes=dict(ap.MODEL_ROUTES, **{f'{k}_fallback': v for k, v in
                                                                              ap.FALLBACK_ROUTES.items()}))
        self.assertEqual(r[:2], ['gemini-3.6-flash', 'gemini-3.6-flash-preview-09-2026'])
        self.assertEqual(r[2:], ['gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-3.5-flash-lite',
                                 'gemini-3.1-flash-lite'])                             # Lite آخر حل للكتابة
        self.assertNotIn('gemini-3.8-flash', r)                                         # 3.8 محجوز للتقرير
        prim = ap.route_models('write', NAMES2, routes=dict(ap.MODEL_ROUTES), fallback=False)
        self.assertEqual(prim, ['gemini-3.6-flash', 'gemini-3.6-flash-preview-09-2026'])

    def test_research_top_then_flash_never_lite(self):
        self.assertEqual(route('research', fallback=False), ['gemini-3.8-flash'])
        self.assertEqual(route('research'), ['gemini-3.8-flash', 'gemini-2.5-flash'])
        r = ap.route_models('research', NAMES2, routes=dict(ap.MODEL_ROUTES))
        self.assertFalse([m for m in r if 'lite' in m or 'gemma' in m])                  # لا يهبط البحث إلى Lite
        self.assertEqual(route('research', pro_ok=True)[:2], ['gemini-3.1-pro-preview', 'gemini-3.8-flash'])
        self.assertNotIn('gemini-3.1-pro-preview', route('write', pro_ok=True))       # Pro للبحث فقط
        self.assertNotIn('gemini-3.1-pro-preview', route('text_light', pro_ok=True))

    def test_reserved_models_even_if_ini_asks(self):
        r = ap.route_models('write', NAMES, routes=dict(ap.MODEL_ROUTES, write='flash'), fallback=False)
        self.assertNotIn('gemini-3.8-flash', r)
        alt = ap.route_models('write', NAMES, routes=dict(ap.MODEL_ROUTES, write='text_light'), fallback=False)
        self.assertEqual(alt[0], 'gemini-3.5-flash-lite')
        gem = ap.route_models('text_light', NAMES, routes=dict(ap.MODEL_ROUTES, text_light='gemma,lite'),
                              gemma_max=10_000, tokens=10_001)
        self.assertEqual(gem[0], 'gemini-3.5-flash-lite')                              # بوابة حجم Gemma باقية لمن يذكره

    def test_old_ini_defaults_ignored_and_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini = os.path.join(tmp, 'gemini_network.ini')
            with open(ini, 'w', encoding='utf-8') as f:
                f.write('[gemini_routing]\nocr = lite,flash\ntext_light = gemma,lite,flash\nwrite = flash:3\n'
                        'research = top\ngemma_max_tokens = 10000\n\n[model_limits]\nlite_rpd = 500\n')
            with mock.patch.object(gc, '_app_dir', return_value=tmp):
                r = ap.get_model_routes()
                self.assertEqual(r['text_light'], ap.MODEL_ROUTES['text_light'])        # الافتراضي القديم لا يبقى
                self.assertEqual(r['write'], 'flash:3')                                  # ما غيّره الأدمن يبقى
                self.assertTrue(ap.ensure_model_defaults())
                with open(ini, encoding='utf-8') as f:
                    txt = f.read()
                self.assertIn('routes_version = 2', txt)
                self.assertIn('write = flash:3', txt)
                self.assertIn('lite_soft_rpd = 300', txt)
                self.assertNotIn('gemma,lite', txt)
                self.assertFalse(ap.ensure_model_defaults())                             # مرة واحدة

    def test_task_chain_sets_model_task(self):
        ap.reset_key_state()
        with mock.patch.object(ap, 'build_chain', lambda: [ap.GeminiProvider('Gemini', 'k')]):
            self.assertEqual(ap.build_task_chain('extract', 'gemini')[0].task, 'text_light')
            self.assertEqual(ap.build_task_chain('summarize', 'gemini')[0].task, 'text_light')
            self.assertEqual(ap.build_task_chain('write', 'gemini')[0].task, 'write')
            self.assertEqual(ap.build_task_chain('research', 'gemini')[0].task, 'research')
        self.assertEqual(ap.PURPOSE_TASK.get('حكم الإحالة'), 'extract')
        import case_startup  # noqa: F401 — يسجّل «الفرز» و«العقد»
        self.assertEqual(ap.PURPOSE_TASK.get('الفرز'), 'extract')

    def test_no_thinking_config_in_any_request(self):
        seen = []

        class Models:
            def generate_content(self, model, **k):
                seen.append(k)
                return type('R', (), {'text': 'ok'})()
        p = ap.GeminiProvider('Gemini', 'k')
        p.task = 'ocr'
        with mock.patch.object(gc, '_make_client', return_value=type('C', (), {'models': Models()})()), \
                mock.patch.object(p, '_models', return_value=['gemini-3.5-flash-lite']):
            p.generate_text(['x'], 'direct', 5)
        self.assertEqual(seen, [{'contents': ['x']}])
        self.assertFalse(hasattr(ap, '_NO_THINK_CFG'))


class FallbackLabelTests(unittest.TestCase):
    def test_fallback_model_marked_in_written_by(self):
        class Models:
            def generate_content(self, model, **k):
                if model == 'gemini-3.6-flash':
                    raise RuntimeError('503 UNAVAILABLE high demand')
                return type('R', (), {'text': 'ok'})()
        p = ap.GeminiProvider('Gemini', 'k')
        p.task = 'write'

        def models(client, contents=None, media=False):
            gc._KEY_CTX.primary = {'gemini-3.6-flash'}
            return ['gemini-3.6-flash', 'gemini-3-flash']
        with mock.patch.object(gc, '_make_client', return_value=type('C', (), {'models': Models()})()), \
                mock.patch.object(p, '_models', side_effect=models):
            p.generate_text(['x'], 'direct', 5)
        self.assertEqual(p.last_model, 'gemini-3-flash (نموذج احتياطي — أعد الكتابة لاحقاً)')
        self.assertTrue(p.fallback)

    def test_lite_31_is_not_a_fallback_for_triage(self):
        p = ap.GeminiProvider('Gemini', 'k')
        p.task = 'text_light'

        class Models:
            def generate_content(self, model, **k):
                return type('R', (), {'text': 'ok'})()

        def models(client, contents=None, media=False):
            gc._KEY_CTX.primary = {'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite'}
            return ['gemini-3.1-flash-lite']
        with mock.patch.object(gc, '_make_client', return_value=type('C', (), {'models': Models()})()), \
                mock.patch.object(p, '_models', side_effect=models):
            p.generate_text(['x'], 'direct', 5)
        self.assertEqual(p.last_model, 'gemini-3.1-flash-lite')


class RetryPolicyTests(unittest.TestCase):
    """سياسة واحدة: 500/503/504/429 ← النموذج التالي فوراً؛ محاولتان في المجموع للطلب عبر كل الطبقات."""

    def setUp(self):
        gc.SLEEP = lambda s: None
        gc._KEY_CTX.quota = False

    def tearDown(self):
        gc.SLEEP = None

    def _client(self, errors):
        sent = []

        class Models:
            def generate_content(self, model, **k):
                sent.append(model)
                err = errors.get(model)
                if err:
                    raise RuntimeError(err)
                return type('R', (), {'text': 'ok'})()
        return type('C', (), {'models': Models()})(), sent

    def test_503_moves_to_next_model_immediately(self):
        client, sent = self._client({'a': '503 UNAVAILABLE'})
        gc._generate_on_client(client, models=['a', 'b', 'c'], contents=['x'])
        self.assertEqual(sent, ['a', 'b'])

    def test_two_attempts_in_total(self):
        client, sent = self._client({'a': '500 INTERNAL', 'b': '429 RESOURCE_EXHAUSTED', 'c': '504 DEADLINE_EXCEEDED'})
        with self.assertRaises(RuntimeError):
            gc._generate_on_client(client, models=['a', 'b', 'c'], contents=['x'])
        self.assertEqual(sent, ['a', 'b'])

    def test_single_model_repeated_once_only(self):
        client, sent = self._client({'a': '503 UNAVAILABLE'})
        with self.assertRaises(RuntimeError):
            gc._generate_on_client(client, models=['a'], contents=['x'])
        self.assertEqual(sent, ['a', 'a'])

    def test_404_not_counted(self):
        client, sent = self._client({'a': '404 NOT_FOUND', 'b': '503 UNAVAILABLE'})
        gc._generate_on_client(client, models=['a', 'b', 'c'], contents=['x'])
        self.assertEqual(sent, ['a', 'b', 'c'])

    def test_route_layer_shares_budget_and_skips_hung_model(self):
        client, sent = self._client({})
        calls = []

        def fn(route):
            calls.append(route)
            if len(calls) == 1:                  # المحاولة الأولى ترسل للنموذج a ثم تعلق (مهلة)
                gc._quota_send(client, 'a', {'contents': ['x']})
                raise TimeoutError('انتهت مهلة الطلب (5s) timeout')
            return gc._generate_on_client(client, models=['a', 'b'], contents=['x'])
        with mock.patch.object(gc, '_log'), mock.patch.object(gc, '_adopt_route'):
            gc._run_with_routes(fn, 0, 5)
        self.assertEqual(sent, ['a', 'b'])                                           # بعد المهلة: التالي لا a
        calls.clear()
        sent.clear()

        def always_timeout(route):
            calls.append(route)
            gc._quota_send(client, 'a', {'contents': ['x']})
            raise TimeoutError('timed out')
        with mock.patch.object(gc, '_log'), mock.patch.object(gc, '_adopt_route'):
            with self.assertRaises(RuntimeError):
                gc._run_with_routes(always_timeout, 0, 5)
        self.assertEqual(len(sent), 2)                                               # لا محاولة ثالثة

    def test_doc_router_batch_not_retried(self):
        import doc_router as dr
        n = []

        class Limited:
            def generate(self_, *a):
                n.append(1)
                raise RuntimeError('429 quota')
        with tempfile.TemporaryDirectory() as tmp:
            import fitz
            pdf = os.path.join(tmp, 'a.pdf')
            d = fitz.open()
            d.new_page()
            d.save(pdf)
            d.close()
            old = dr.GEMINI_PROVIDER_FACTORY
            dr.GEMINI_PROVIDER_FACTORY = lambda: Limited()
            try:
                with self.assertRaises(RuntimeError):
                    dr._call_provider_retry(Limited(), 'p', pdf, 1, {'retries': 3, 'retry_wait': 1})
            finally:
                dr.GEMINI_PROVIDER_FACTORY = old
        self.assertEqual(len(n), 1)

class QuotaCounterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        gq.PATH_OVERRIDE = os.path.join(self._tmp.name, 'q.json')
        gq.INI_OVERRIDE = {}
        gq.reset_memory()

    def tearDown(self):
        gq.PATH_OVERRIDE = gq.INI_OVERRIDE = None
        gq.reset_memory()
        self._tmp.cleanup()

    def test_families(self):
        self.assertEqual([gq.family(m) for m in ('gemini-3.5-flash-lite', 'gemma-4-31b-it', 'gemini-3.8-flash',
                                                 'gemini-3.1-pro-preview')], ['lite', 'gemma', 'flash', 'pro'])

    def test_daily_limit_skips_before_sending(self):
        now = 1_000_000.0
        for i in range(20):
            self.assertTrue(gq.check('K', 'gemini-3.8-flash', now=now + i * 61)[0])
            gq.record('K', 'gemini-3.8-flash', now=now + i * 61)
        ok, why, _w = gq.check('K', 'gemini-3.8-flash', now=now + 99 * 61)
        self.assertEqual((ok, why), (False, 'day'))
        self.assertTrue(gq.check('K', 'gemini-3.6-flash')[0])          # لكل نموذج حصته المستقلة
        self.assertTrue(gq.check('OTHER', 'gemini-3.8-flash')[0])        # ولكل مفتاح

    def test_minute_limit_waits(self):
        now = 2_000_000.0
        for i in range(5):
            gq.record('K', 'gemini-3.8-flash', now=now + i)
        ok, why, wait = gq.check('K', 'gemini-3.8-flash', now=now + 10)
        self.assertEqual((ok, why), (False, 'minute'))
        self.assertGreater(wait, 49)
        self.assertTrue(gq.check('K', 'gemini-3.8-flash', now=now + 61)[0])

    def test_gemma_token_minute_limit(self):
        self.assertEqual(gq.check('K', 'gemma-4-31b-it', tokens=17_000)[1], 'too_big')
        gq.record('K', 'gemma-4-31b-it', tokens=9_000, now=100.0)
        self.assertEqual(gq.check('K', 'gemma-4-31b-it', tokens=9_000, now=110.0)[1], 'minute')

    def test_soft_cap_300_for_background_rest_for_ui(self):
        self.assertEqual(gq.day_cap('gemini-3.5-flash-lite', 'background'), 300)
        self.assertEqual(gq.day_cap('gemini-3.5-flash-lite', 'ui'), 500)
        self.assertEqual(gq.day_cap('gemini-3.5-flash-lite', 'queue'), 210)            # الطابور: 70% من الناعم
        self.assertEqual(gq.day_cap('gemini-3.6-flash', 'background'), 20)
        gq.INI_OVERRIDE = {'lite_rpd': '10', 'lite_soft_rpd': '6'}
        for i in range(6):
            gq.record('K', 'gemini-3.5-flash-lite', now=float(i * 61))
        self.assertEqual(gq.check('K', 'gemini-3.5-flash-lite')[:2], (False, 'day'))     # الخلفية (الافتراضي) عند الناعم
        self.assertTrue(gq.check('K', 'gemini-3.1-flash-lite')[0])                     # ← 3.1 مباشرة (حصة مستقلة)
        with gq.mode('ui'):
            self.assertTrue(gq.check('K', 'gemini-3.5-flash-lite')[0])                 # والباقي حتى 10 للواجهة
        self.assertFalse(gq.check('K', 'gemini-3.5-flash-lite', background=True)[0])
        self.assertFalse(gq.queue_room('K', ['gemini-3.5-flash-lite']))
        self.assertTrue(gq.queue_room('K', ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite']))

    def test_mode_crosses_timeout_thread(self):
        seen = []
        with gq.mode('ui'):
            gc._call_with_timeout(lambda: seen.append(gq.current_mode()), 5)
        gc._call_with_timeout(lambda: seen.append(gq.current_mode()), 5)
        self.assertEqual(seen, ['ui', 'background'])

    def test_background_skips_35_to_31_without_request(self):
        sent = []

        class Models:
            def generate_content(self, model, **k):
                sent.append(model)
                return type('R', (), {'text': 'ok'})()
        client = type('C', (), {'models': Models()})()
        kid = gc.key_id('SOFT')
        gq.INI_OVERRIDE = {'lite_soft_rpd': '2'}
        gq.record(kid, 'gemini-3.5-flash-lite', now=1.0)
        gq.record(kid, 'gemini-3.5-flash-lite', now=100.0)
        gc._KEY_CTX.kid, gc._KEY_CTX.quota, gc._KEY_CTX.tokens = kid, True, 0
        try:
            gc._generate_on_client(client, models=['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite'], contents=['x'])
        finally:
            gc._KEY_CTX.quota = False
        self.assertEqual(sent, ['gemini-3.1-flash-lite'])

    def test_paid_key_not_enforced_and_ini_overrides(self):
        gq.mark_full('K', 'gemini-3.8-flash')
        self.assertFalse(gq.check('K', 'gemini-3.8-flash')[0])
        self.assertTrue(gq.check('K', 'gemini-3.8-flash', enforce=False)[0])
        gq.INI_OVERRIDE = {'flash_rpd': '50'}
        self.assertEqual(gq.limits('gemini-3.8-flash')['rpd'], 50)

    def test_pacific_day_boundary(self):
        # 2026-10-23 06:59 UTC = 23:59 PDT (22 أكتوبر) ← يوم الحصة لم يتجدد بعد
        self.assertEqual(gq.pacific_day(1792738740), '2026-10-22')
        self.assertEqual(gq.pacific_day(1792738740 + 120), '2026-10-23')

    def test_generate_skips_full_model_without_request(self):
        sent = []

        class Models:
            def generate_content(self, model, **k):
                sent.append(model)
                return type('R', (), {'text': 'ok'})()
        client = type('C', (), {'models': Models()})()
        kid = gc.key_id('Z')
        gq.mark_full(kid, 'gemini-3.8-flash')
        gc._KEY_CTX.kid, gc._KEY_CTX.quota, gc._KEY_CTX.tokens = kid, True, 0
        try:
            gc._generate_on_client(client, models=['gemini-3.8-flash', 'gemini-3.5-flash-lite'], contents=['x'])
            self.assertEqual(sent, ['gemini-3.5-flash-lite'])            # المنتهي لم يُرسل له شيء
            self.assertEqual(gq.used_today(kid, 'gemini-3.5-flash-lite'), 1)
            gq.mark_full(kid, 'gemini-3.5-flash-lite')
            with self.assertRaises(gc.QuotaExhausted):
                gc._generate_on_client(client, models=['gemini-3.8-flash', 'gemini-3.5-flash-lite'], contents=['x'])
        finally:
            gc._KEY_CTX.quota = False

    def test_research_falls_back_to_flash_only_then_stops(self):
        kid = gc.key_id('FREE2')
        gq.mark_full(kid, 'gemini-3.8-flash')
        with mock.patch.object(gc, 'list_models', return_value=NAMES), \
                mock.patch.object(gc, 'key_model', return_value={'model': 'gemini-3.8-flash', 'pro': False}), \
                mock.patch.object(gc, 'exhausted_models', return_value={}), \
                mock.patch.object(gc, 'pro_setting', return_value='auto'), \
                mock.patch.object(ap, 'get_model_routes', return_value=dict(ap.MODEL_ROUTES)):
            self.assertEqual(gc.task_candidates(None, 'FREE2', 'research'), ['gemini-2.5-flash'])   # الملاذ الأخير
            self.assertTrue(gc.is_fallback('gemini-2.5-flash'))
            gq.mark_full(kid, 'gemini-2.5-flash')
            with self.assertRaises(gc.QuotaExhausted) as cm:
                gc.task_candidates(None, 'FREE2', 'research')                                # لا Lite أبداً
            self.assertIn('البحث والنتيجة', str(cm.exception))
            self.assertIn('لم يُستعمل نموذج أضعف', str(cm.exception))
            self.assertEqual(gc.task_candidates(None, 'FREE2', 'write')[0], 'gemini-3.6-flash')
        gc._KEY_CTX.quota = False


class BatchTests(unittest.TestCase):
    def test_default_batch_is_25_and_45_pages_two_requests(self):
        import doc_router as dr
        self.assertGreaterEqual(int(dr.DEFAULT_LIMITS['batch_pages']), 25)
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            pdf = os.path.join(tmp, 'a.pdf')
            d = fitz.open()
            for _ in range(45):
                d.new_page()
            d.save(pdf)
            d.close()
            chunks = dr.plan_chunks(pdf, tmp, 1000, 50 * 1024 * 1024, 25)
            self.assertEqual([(a, b) for a, b, _p in chunks], [(0, 25), (25, 45)])

    def test_old_default_20_migrates_once(self):
        import doc_router as dr
        with tempfile.TemporaryDirectory() as tmp:
            ini = os.path.join(tmp, 'gemini_network.ini')
            with open(ini, 'w', encoding='utf-8') as f:
                f.write('[gemini_limits]\nbatch_pages = 20\nretries = 3\nretry_wait = 30\n')
            with mock.patch.object(gc, '_app_dir', return_value=tmp):
                dr.ensure_defaults()
                self.assertEqual(dr.gemini_limits()['batch_pages'], 25)
                with open(ini, 'w', encoding='utf-8') as f:
                    f.write('[gemini_limits]\nbatch_version = 2\nbatch_pages = 20\nretries = 3\nretry_wait = 30\n')
                dr.ensure_defaults()
                self.assertEqual(dr.gemini_limits()['batch_pages'], 20)   # اختيار الخبير بعد الترحيل يبقى

    def test_ocr_request_has_no_triage_and_uses_ocr_task(self):
        import doc_router as dr
        seen = []

        class Fake:
            task = ''

            def generate(self, prompt, prep, route, timeout):
                seen.append((self.task, prompt))
                return type('R', (), {'text': 'نص'})()
        import fitz
        old = dr.GEMINI_PROVIDER_FACTORY
        fake = Fake()
        dr.GEMINI_PROVIDER_FACTORY = lambda: fake
        try:
            with tempfile.TemporaryDirectory() as tmp:
                pdf = os.path.join(tmp, 'a.pdf')
                d = fitz.open()
                d.new_page()
                d.save(pdf)
                d.close()
                dr.set_triage('- أطراف', None)
                dr.gemini_engine(lambda p: ('', 0), limits=dict(dr.gemini_limits(), retries=0))(pdf, {})
                dr.set_triage(None)
        finally:
            dr.GEMINI_PROVIDER_FACTORY = old
        self.assertEqual(seen[0][0], 'ocr')
        self.assertNotIn('json', seen[0][1])


class SummaryQueueTests(unittest.TestCase):
    def setUp(self):
        import summary_queue as sq
        self.sq = sq
        self._tmp = tempfile.TemporaryDirectory()
        sq.PATH_OVERRIDE = os.path.join(self._tmp.name, 's.json')

    def tearDown(self):
        self.sq.PATH_OVERRIDE = self.sq.PROCESS = None
        self._tmp.cleanup()

    def test_one_worker_dedupes_and_remembers_failures(self):
        sq = self.sq
        calls, gate, done = [], threading.Event(), threading.Event()
        active = []

        def proc(case, cookies):
            active.append(threading.current_thread().name)
            calls.append(case['caso_no'])
            gate.wait(5)
            if case['caso_no'] == 'B':
                raise RuntimeError('فشل')
            return 'ملخص'
        sq.PROCESS = proc
        got = []
        a = {'caso_no': 'A', 'autocase_no': '1'}
        b = {'caso_no': 'B', 'autocase_no': '2'}
        self.assertTrue(sq.enqueue(a, None, got.append))
        self.assertTrue(sq.enqueue(a, None, got.append))                 # مكرر: لا يُضاف مرة ثانية
        self.assertTrue(sq.enqueue(b, None, lambda s: done.set()))
        gate.set()
        self.assertTrue(done.wait(5))
        self.assertEqual(calls, ['A', 'B'])                               # بالتتابع، كل قضية مرة
        self.assertEqual(got, ['ملخص', 'ملخص'])
        self.assertEqual(set(active), {'summary-queue'})                  # خيط عامل واحد
        self.assertFalse(sq.enqueue(b, None))                             # فشلت مؤخراً: لا عاصفة إعادات
        self.assertTrue(sq.recently_failed(b))
        self.assertFalse(sq.recently_failed(b, now=time.time() + sq.FAIL_RETRY_SECONDS + 1))


class ReferralMarkerTests(unittest.TestCase):
    def test_expert_judgment_name_and_marker_recognised_by_code(self):
        import case_folder as cf
        import case_sort as cs
        import referral_pick as rp
        self.assertTrue(cf.is_referral_name(f'{cf.SYSDOCS}/حكم خبير.pdf'))
        self.assertTrue(cs.is_canonical(f'{cf.SYSDOCS}/حكم خبير.pdf'))
        self.assertEqual(cf.kind_of(f'{cf.SYSDOCS}/حكم خبير.pdf'), cf.JUDGMENT)
        with mock.patch('case_subject_mission.extract_mission', return_value=['بند']):
            self.assertTrue(rp.is_referral(cf.REFERRAL_MARK + '\n\nنص بلا صيغة ندب'))
            self.assertFalse(rp.is_referral('نص بلا صيغة ندب'))


if __name__ == '__main__':
    unittest.main()
