# أولوية المفتاح الشخصي على مفتاح القسم + تشفير DPAPI + عدم تسرّب المفاتيح + بطاقات المفاتيح وروابطها
# python -W ignore -m unittest test_key_priority -v
import base64
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import ai_providers as ap
import gemini_config as gc
import ocr_space
import ocr_vision
import provider_sync
import secret_audit
import secret_store

OWN_G = 'AQ.OwnGeminiKey_abcdefghijklmnopqrstuvwxyz'          # بادئة غير AIza عمداً: لا نتحقق من الشكل
OWN_O = 'sk-proj-OwnOpenAIKey_abcdefghijklmnop'
OWN_V = 'AQ.OwnVisionKey_abcdefghijklmnopqrstuv'
OWN_R = 'K8OwnOcrSpaceKey'
SEC_G, SEC_O, SEC_R = 'AIzaSECTIONgemini_abcdefghijklmnop', 'sk-SECTIONopenai_abcdefghijklmnop', 'K8SECTIONocr'


def section_rows():
    return [
        {'name': 'Gemini', 'kind': 'gemini', 'api_key': SEC_G, 'enabled': 1, 'priority': 1, 'model': ''},
        {'name': 'chatgpt', 'kind': 'openai', 'api_key': SEC_O, 'enabled': 1, 'priority': 5,
         'base_url': 'https://api.openai.com/v1', 'model': 'gpt-4o-mini'},
        {'name': 'groq', 'kind': 'openai', 'api_key': 'gsk_SECTIONgroup_abcdefghij', 'enabled': 1, 'priority': 20,
         'base_url': 'https://api.groq.com/openai/v1', 'model': 'm'},
        {'name': 'ocrspace', 'kind': 'ocr', 'api_key': SEC_R, 'enabled': 1, 'priority': 1},
    ]


class TmpExpertDir(unittest.TestCase):
    """مجلد خبير مؤقت لكل المحمّلات (gemini_config / ocr_vision)، وسجل مؤقت بدل سجل الجهاز."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name
        for mod in (gc, ocr_vision):
            p = mock.patch.object(mod, 'expert_data_dir', lambda: self.d)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(gc, '_LOG_PATH', os.path.join(self.d, 'gemini_log.txt'))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(gc, '_OLD_KEY_PATH', os.path.join(self.d, 'old', 'gemini_key.json'))
        p.start()
        self.addCleanup(p.stop)
        gc.pop_personal_failures()
        self.addCleanup(gc.pop_personal_failures)
        ap.reset_key_state()
        self.addCleanup(ap.reset_key_state)

    def raw(self, name):
        with open(os.path.join(self.d, name), encoding='utf-8') as f:
            return f.read()


class SecretStoreTests(unittest.TestCase):
    def test_roundtrip_and_ciphertext_differs(self):
        enc = secret_store.protect(OWN_G)
        self.assertTrue(enc.startswith('dpapi:'))
        self.assertNotIn(OWN_G, enc)
        self.assertEqual(secret_store.unprotect(enc), OWN_G)

    def test_empty_and_tampered(self):
        self.assertEqual(secret_store.protect(''), '')
        self.assertEqual(secret_store.unprotect('dpapi:' + base64.b64encode(b'garbage-not-dpapi').decode()), '')
        self.assertEqual(secret_store.unprotect('dpapi:!!!notbase64'), '')

    def test_legacy_plaintext_passthrough(self):
        self.assertEqual(secret_store.unprotect('  plain-old-key  '), 'plain-old-key')


class MigrationTests(TmpExpertDir):
    def _legacy(self, name, field, value):
        with open(os.path.join(self.d, name), 'w', encoding='utf-8') as f:
            json.dump({field: value}, f)

    def test_each_personal_key_file_migrates_and_plaintext_removed(self):
        cases = [('gemini_key.json', 'gemini_api_key', OWN_G, gc.load_api_key),
                 ('ocr_key.json', 'ocr_api_key', OWN_R, gc.load_ocr_key),
                 ('vision_key.json', 'vision_api_key', OWN_V, ocr_vision.load_key),
                 ('openai_key.json', 'openai_api_key', OWN_O, gc.load_openai_key)]
        for name, field, val, loader in cases:
            self._legacy(name, field, val)
            self.assertEqual(loader(), val, name)                    # المفتاح يعمل فور القراءة
            text = self.raw(name)
            self.assertNotIn(val, text, name)                        # النص الصريح اختفى من الملف
            self.assertTrue(json.loads(text)[field].startswith('dpapi:'), name)
            self.assertEqual(loader(), val, name)                    # والقراءة التالية من المشفّر

    def test_save_writes_encrypted_and_delete_clears(self):
        gc.save_openai_key(OWN_O)
        self.assertNotIn(OWN_O, self.raw('openai_key.json'))
        self.assertEqual(gc.load_openai_key(), OWN_O)
        gc.save_openai_key('')
        self.assertEqual(gc.load_openai_key(), '')

    def test_migrate_local_secrets_runs_all(self):
        self._legacy('gemini_key.json', 'gemini_api_key', OWN_G)
        self._legacy('vision_key.json', 'vision_api_key', OWN_V)
        with mock.patch.object(provider_sync, '_CACHE_PATH', os.path.join(self.d, 'cache.json')):
            provider_sync.migrate_local_secrets()
        self.assertNotIn(OWN_G, self.raw('gemini_key.json'))
        self.assertNotIn(OWN_V, self.raw('vision_key.json'))

    def test_failed_encryption_never_destroys_key(self):
        self._legacy('gemini_key.json', 'gemini_api_key', OWN_G)
        with mock.patch.object(secret_store, 'protect', side_effect=OSError('no dpapi')):
            self.assertEqual(gc.load_api_key(), OWN_G)               # يعمل، ويبقى الملف كما هو
        self.assertIn(OWN_G, self.raw('gemini_key.json'))


class ProviderCacheTests(TmpExpertDir):
    def setUp(self):
        super().setUp()
        self.cache = os.path.join(self.d, 'ai_providers_cache.json')
        p = mock.patch.object(provider_sync, '_CACHE_PATH', self.cache)
        p.start()
        self.addCleanup(p.stop)

    def test_save_cache_is_really_encrypted(self):
        provider_sync._save_cache(section_rows())
        text = open(self.cache, encoding='utf-8').read()
        for k in (SEC_G, SEC_O, SEC_R):
            self.assertNotIn(k, text)
        self.assertIn('dpapi:', text)
        got = {r['name']: r['api_key'] for r in provider_sync._load_cache()}
        self.assertEqual(got['Gemini'], SEC_G)
        self.assertEqual(got['chatgpt'], SEC_O)

    def test_legacy_plaintext_cache_migrated_on_load(self):
        with open(self.cache, 'w', encoding='utf-8') as f:
            json.dump(section_rows(), f)
        rows = provider_sync._load_cache()
        self.assertEqual({r['name']: r['api_key'] for r in rows}['Gemini'], SEC_G)
        self.assertNotIn(SEC_G, open(self.cache, encoding='utf-8').read())

    def test_audit_sees_cache_clean_after_migration_and_dirty_before(self):
        with open(self.cache, 'w', encoding='utf-8') as f:
            json.dump(section_rows(), f)
        with mock.patch.object(secret_audit, 'expert_data_dir', lambda: self.d), \
                mock.patch.object(gc, '_app_dir', lambda: self.d):
            before = {os.path.basename(p) for p, _ in secret_audit.find_plaintext_keys()}
            provider_sync._load_cache()
            after = {os.path.basename(p) for p, _ in secret_audit.find_plaintext_keys()}
        self.assertIn('ai_providers_cache.json', before)
        self.assertNotIn('ai_providers_cache.json', after)

    def test_audit_covers_openai_key_file(self):
        with open(os.path.join(self.d, 'openai_key.json'), 'w', encoding='utf-8') as f:
            json.dump({'openai_api_key': OWN_O}, f)
        with mock.patch.object(secret_audit, 'expert_data_dir', lambda: self.d), \
                mock.patch.object(gc, '_app_dir', lambda: self.d):
            self.assertIn('openai_key.json', {os.path.basename(p) for p, _ in secret_audit.find_plaintext_keys()})
            gc.load_openai_key()
            self.assertNotIn('openai_key.json', {os.path.basename(p) for p, _ in secret_audit.find_plaintext_keys()})


class PriorityChainTests(TmpExpertDir):
    """الشخصي يحجب مفتاح القسم لنفس المزوّد؛ وبلا شخصي يُستعمل مفتاح القسم."""

    def chain(self, g='', o=''):
        with mock.patch.object(ap, 'get_provider_configs', section_rows), \
                mock.patch.object(gc, 'feature_on', lambda k: True), \
                mock.patch.object(gc, 'load_api_key', lambda: g), \
                mock.patch.object(gc, 'load_openai_key', lambda: o), \
                mock.patch.object(ap.BrowserProvider, 'bot_dir', classmethod(lambda cls: None)):
            return ap.build_chain()

    def keys(self, chain):
        return [(p.name, p.key_type, p.api_key) for p in chain]

    def test_gemini_personal_replaces_section(self):
        c = self.chain(g=OWN_G)
        gem = [p for p in c if isinstance(p, ap.GeminiProvider)]
        self.assertEqual([(p.key_type, p.api_key) for p in gem], [(ap.KEY_OWN, OWN_G)])
        self.assertNotIn(SEC_G, [p.api_key for p in c])

    def test_gemini_absent_personal_uses_section(self):
        gem = [p for p in self.chain() if isinstance(p, ap.GeminiProvider)]
        self.assertEqual([(p.key_type, p.api_key) for p in gem], [(ap.KEY_DEFAULT, SEC_G)])

    def test_openai_personal_replaces_section_chatgpt(self):
        c = self.chain(o=OWN_O)
        oa = [p for p in c if p.name == 'chatgpt']
        self.assertEqual([(type(p).__name__, p.key_type, p.api_key) for p in oa],
                         [('OpenAIOwnProvider', ap.KEY_OWN, OWN_O)])
        self.assertNotIn(SEC_O, [p.api_key for p in c])
        self.assertNotIn('groq', [p.name for p in c])               # Groq مستبعد دائماً (سياسة 2026-10-21)

    def test_openai_absent_personal_uses_section(self):
        oa = [p for p in self.chain() if p.name == 'chatgpt']
        self.assertEqual([(type(p).__name__, p.key_type, p.api_key) for p in oa],
                         [('OpenAICompatProvider', ap.KEY_DEFAULT, SEC_O)])

    def test_order_gemini_then_own_openai_before_fallbacks(self):
        names = [p.name for p in self.chain(g=OWN_G, o=OWN_O)]
        self.assertEqual(names[:2], ['Gemini', 'chatgpt'])

    def test_personal_gemini_ignored_when_api_feature_off(self):
        with mock.patch.object(ap, 'get_provider_configs', section_rows), \
                mock.patch.object(gc, 'feature_on', lambda k: k != 'api'), \
                mock.patch.object(gc, 'load_api_key', lambda: OWN_G), \
                mock.patch.object(ap.BrowserProvider, 'bot_dir', classmethod(lambda cls: None)):
            self.assertEqual(ap.build_chain(), [])

    def test_key_source_and_texts(self):
        with mock.patch.object(ap, 'get_provider_configs', section_rows):
            with mock.patch.object(gc, 'load_api_key', lambda: OWN_G), \
                    mock.patch.object(gc, 'load_openai_key', lambda: ''), \
                    mock.patch.object(gc, 'load_ocr_key', lambda: ''), \
                    mock.patch.object(ocr_vision, 'load_key', lambda: ''):
                self.assertEqual(ap.key_source('gemini'), 'own')
                self.assertEqual(ap.key_source('openai'), 'shared')
                self.assertEqual(ap.key_source('ocrspace'), 'shared')
                self.assertEqual(ap.key_source('vision'), 'none')       # Vision شخصي فقط
        with mock.patch.object(ap, 'get_provider_configs', lambda: []), \
                mock.patch.object(gc, 'load_api_key', lambda: ''):
            self.assertEqual(ap.key_source('gemini'), 'none')
        self.assertEqual(ap.KEY_SOURCE_TEXT['own'], 'يُستعمل مفتاحك')
        self.assertEqual(ap.KEY_SOURCE_TEXT['shared'], 'لا يوجد مفتاح شخصي، يُستعمل مفتاح القسم')
        self.assertEqual(ap.KEY_SOURCE_TEXT['none'], 'لا يوجد مفتاح')

    def test_provider_label_marks_key_owner(self):
        own = ap.GeminiProvider('Gemini', 'k', ap.KEY_OWN)
        shared = ap.GeminiProvider('Gemini', 'k', ap.KEY_DEFAULT)
        self.assertEqual(ap.provider_label(own), 'Gemini (مفتاحك)')
        self.assertEqual(ap.provider_label(shared), 'Gemini (مفتاح القسم)')

    def test_written_by_line_carries_key_owner(self):
        import ai_call_log
        import case_research
        own = ap.GeminiProvider('Gemini', OWN_G, ap.KEY_OWN)
        own.generate_text = lambda contents, route, timeout: ap.AIResponse('نص', 'Gemini')
        with mock.patch.object(ap, 'build_text_chain', lambda: [own]), \
                mock.patch.object(gc, '_run_with_routes', lambda fn, s, t: fn('direct')), \
                mock.patch.object(gc, '_log', lambda *a, **k: None):
            case_research.default_ask('سؤال')
        self.assertEqual(ai_call_log.last_provider(), 'Gemini (مفتاحك)')

    def test_best_engine_source(self):
        import doc_router
        with mock.patch.object(doc_router, 'best_engine', lambda: doc_router.ENGINE_GEMINI), \
                mock.patch.object(ap, 'key_source', lambda w: 'own' if w == 'gemini' else 'none'):
            self.assertEqual(doc_router.best_engine_source(), 'own')
        with mock.patch.object(doc_router, 'best_engine', lambda: doc_router.ENGINE_LOCAL):
            self.assertEqual(doc_router.best_engine_source(), '')
        with mock.patch.object(doc_router, 'best_engine', lambda: doc_router.ENGINE_EXTERNAL), \
                mock.patch.object(ap, 'key_source', lambda w: 'shared' if w == 'ocrspace' else 'none'):
            self.assertEqual(doc_router.best_engine_source(), 'shared')


class OcrSpaceSourceTests(TmpExpertDir):
    def settings(self, own):
        row = {'name': 'ocrspace', 'api_key': SEC_R, 'enabled': 1}
        with mock.patch.object(gc, '_app_dir', lambda: self.d), \
                mock.patch.object(provider_sync, 'get_configs', lambda: [row]), \
                mock.patch.object(gc, 'load_ocr_key', lambda: own):
            return ocr_space.get_settings()

    def test_personal_wins(self):
        c = self.settings(OWN_R)
        self.assertEqual((c['api_key'], c['key_type']), (OWN_R, 'خاص'))

    def test_section_when_no_personal(self):
        c = self.settings('')
        self.assertEqual((c['api_key'], c['key_type']), (SEC_R, 'افتراضي'))


class PersonalFailureTests(TmpExpertDir):
    """فشل المفتاح الشخصي يُبلَّغ به ولا ينتقل لمفتاح القسم بصمت."""

    def run_chain(self, chain, call):
        with mock.patch.object(gc, '_run_with_routes', lambda fn, s, t: fn('direct')), \
                mock.patch.object(gc, '_log', lambda *a, **k: None):
            return ap.run_chain(call, 10, 10, chain=chain)

    def test_expired_personal_gemini_reports_and_never_tries_section_key(self):
        c = TestChain.make(self, g=OWN_G)                          # سلسلة بمفتاح شخصي: لا مفتاح قسم لـGemini فيها
        used = []

        def call(p, route):
            used.append((p.name, p.key_type, p.api_key))
            raise RuntimeError('HTTP 400 API key not valid. Please pass a valid API key.')
        with self.assertRaises(RuntimeError) as cm:
            self.run_chain([p for p in c if isinstance(p, ap.GeminiProvider)], call)
        self.assertEqual([u[2] for u in used], [OWN_G])
        self.assertNotIn(SEC_G, [u[2] for u in used])
        self.assertIn('مفتاحك الشخصي لـGemini', str(cm.exception))
        self.assertIn('غير صالح', str(cm.exception))
        self.assertIsInstance(cm.exception, ap.PersonalKeyFailure)

    def test_personal_openai_out_of_credit_stops_and_never_tries_section_or_others(self):
        c = TestChain.make(self, o=OWN_O)
        used = []

        def call(p, route):
            used.append(p.api_key)
            if p.key_type == ap.KEY_OWN:
                raise ap.ProviderHTTPError('chatgpt HTTP 429: {"error":{"code":"insufficient_quota"}}')
            return ap.AIResponse('ok', p.name)
        with self.assertRaises(ap.PersonalKeyFailure) as cm:
            self.run_chain([p for p in c if not isinstance(p, ap.GeminiProvider)], call)
        self.assertEqual(used, [OWN_O])                            # لا مفتاح القسم ولا أي مزوّد آخر
        self.assertEqual(cm.exception.cause, 'quota')
        self.assertIn('نفد الرصيد', str(cm.exception))

    def test_network_error_is_not_blamed_on_key(self):
        c = TestChain.make(self, g=OWN_G)

        def call(p, route):
            raise RuntimeError('تعذر الاتصال بخدمة الذكاء الاصطناعي، حاول لاحقاً')
        with self.assertRaises(RuntimeError):
            self.run_chain([p for p in c if isinstance(p, ap.GeminiProvider)], call)
        self.assertEqual(ap.pop_personal_failures(), [])

    def test_shared_key_failure_is_not_reported_as_personal(self):
        c = TestChain.make(self)

        def call(p, route):
            raise RuntimeError('HTTP 401 invalid api key')
        with self.assertRaises(RuntimeError):
            self.run_chain([p for p in c if isinstance(p, ap.GeminiProvider)], call)
        self.assertEqual(ap.pop_personal_failures(), [])

    def test_vision_and_ocrspace_personal_failure_noted(self):
        with mock.patch.object(ocr_vision, 'load_key', lambda: OWN_V), \
                mock.patch.object(ocr_vision, '_post', side_effect=ocr_vision.VisionFailed('Cloud Vision HTTP 403: API key expired')), \
                mock.patch('fitz.open') as fo:
            doc = mock.MagicMock()
            doc.__enter__.return_value = doc
            doc.__getitem__.return_value.get_pixmap.return_value.tobytes.return_value = b'x'
            fo.return_value = doc
            with self.assertRaises(ocr_vision.VisionFailed):
                ocr_vision.ocr_pages('x.pdf', [0], 'direct')
        self.assertTrue(any('Google Cloud Vision' in m for m in gc.pop_personal_failures()))


class TestChain:
    @staticmethod
    def make(tc, g='', o=''):
        with mock.patch.object(ap, 'get_provider_configs', section_rows), \
                mock.patch.object(gc, 'feature_on', lambda k: True), \
                mock.patch.object(gc, 'load_api_key', lambda: g), \
                mock.patch.object(gc, 'load_openai_key', lambda: o), \
                mock.patch.object(ap.BrowserProvider, 'bot_dir', classmethod(lambda cls: None)):
            return ap.build_chain()


class OpenAIModelPickTests(TmpExpertDir):
    def test_rank_strongest_first_without_fixed_name(self):
        ids = ['gpt-4o', 'gpt-4o-mini', 'gpt-5', 'gpt-5-mini', 'gpt-5-2025-08-07', 'gpt-5.1', 'gpt-5.1-codex',
               'gpt-5-pro', 'text-embedding-3-large', 'gpt-4.1', 'gpt-image-1', 'o3', 'gpt-4o-audio-preview',
               'gpt-5.1-2025-11-13', 'whisper-1', 'gpt-4o-realtime-preview']
        self.assertEqual(ap.rank_openai_models(ids, 4), ['gpt-5.1', 'gpt-5', 'gpt-5-mini', 'gpt-4.1'])
        self.assertEqual(ap.rank_openai_models(ids + ['gpt-9'])[0], 'gpt-9')      # نموذج مستقبلي يُلتقط بلا تعديل كود
        self.assertEqual(ap.rank_openai_models(['gpt-5-2025-08-07']), ['gpt-5-2025-08-07'])   # لقطة بلا اسم مستعار
        self.assertEqual(ap.rank_openai_models(['whisper-1', 'tts-1']), [])

    def _provider(self, ids, post_side):
        p = ap.OpenAIOwnProvider('chatgpt', OWN_O, ap.KEY_OWN, '', ap.OPENAI_BASE, max_tokens=100)
        ap._openai_models_cache.clear()
        self.addCleanup(ap._openai_models_cache.clear)
        sess = mock.MagicMock()
        sess.get.return_value = mock.Mock(status_code=200, json=lambda: {'data': [{'id': i} for i in ids]})

        def post(url, headers=None, json=None, **kw):
            return post_side(json['model'])
        sess.post.side_effect = post
        patcher = mock.patch('requests.Session', return_value=sess)
        patcher.start()
        self.addCleanup(patcher.stop)
        return p, sess

    def test_uses_best_model_and_records_it(self):
        ok = lambda model: mock.Mock(status_code=200, text='', json=lambda: {'choices': [{'message': {'content': 'تم'}}]})
        p, sess = self._provider(['gpt-4o', 'gpt-5', 'gpt-5-mini'], ok)
        with mock.patch.object(gc, 'get_proxy_url', return_value=''):
            out = p.generate_text(['hi'], 'direct', 10)
        self.assertEqual(out.text, 'تم')
        self.assertEqual(p.last_model, 'gpt-5')

    def test_falls_to_next_model_when_key_has_no_access(self):
        def post(model):
            if model == 'gpt-5':
                return mock.Mock(status_code=404, text='The model `gpt-5` does not exist or you do not have access')
            return mock.Mock(status_code=200, text='', json=lambda: {'choices': [{'message': {'content': 'x'}}]})
        p, _ = self._provider(['gpt-5', 'gpt-5-mini'], post)
        with mock.patch.object(gc, 'get_proxy_url', return_value=''):
            p.generate_text(['hi'], 'direct', 10)
        self.assertEqual(p.last_model, 'gpt-5-mini')

    def test_bad_key_error_propagates_and_is_explained(self):
        p = ap.OpenAIOwnProvider('chatgpt', OWN_O, ap.KEY_OWN, '', ap.OPENAI_BASE)
        ap._openai_models_cache.clear()
        sess = mock.MagicMock()
        sess.get.return_value = mock.Mock(status_code=401, text='{"error":{"message":"Incorrect API key provided: sk-proj-***"}}')
        with mock.patch('requests.Session', return_value=sess), mock.patch.object(gc, 'get_proxy_url', return_value=''):
            with self.assertRaises(ap.ProviderHTTPError) as cm:
                p.generate_text(['hi'], 'direct', 10)
        self.assertIn('غير صالح', gc.explain_key_failure(cm.exception))

    def test_reasoning_model_uses_max_completion_tokens(self):
        p = ap.OpenAIOwnProvider('chatgpt', OWN_O, ap.KEY_OWN, 'gpt-5', ap.OPENAI_BASE, max_tokens=100)
        body = p._body([{'role': 'user', 'content': 'x'}])
        self.assertNotIn('max_tokens', body)
        self.assertNotIn('temperature', body)
        self.assertEqual(body['max_completion_tokens'], 400)
        p.model = 'gpt-4.1'
        self.assertEqual(p._body([])['max_tokens'], 100)


class NoLeakTests(TmpExpertDir):
    def test_redact_patterns(self):
        for raw in ('https://x/v1?key=' + OWN_V, 'Bearer ' + OWN_O, 'api_key: ' + OWN_G, 'k ' + 'AIza' + 'A' * 30,
                    'sk-' + 'b' * 30, 'dpapi:' + 'QUJD' * 12):
            self.assertNotRegex(gc.redact(raw), r'AQ\.Own|sk-proj|sk-bbbb|AIzaAAAA|QUJDQUJD|OwnGemini|OwnVision')

    def test_short_error_and_log_never_contain_key(self):
        e = RuntimeError(f'HTTPSConnectionPool: Max retries /v1/images:annotate?key={OWN_V} (Caused by ...)')
        self.assertNotIn(OWN_V, gc.short_error(e))
        gc._log('direct', 'FAIL', error=e, note=f'x {OWN_O}')
        gc._log('direct', 'FAIL', error=RuntimeError('Bearer ' + OWN_O))
        text = self.raw('gemini_log.txt')
        self.assertNotIn(OWN_V, text)
        self.assertNotIn('Bearer ' + OWN_O, text)

    def test_ai_call_log_redacts_detail(self):
        import ai_call_log
        with tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, 'ai_calls.log')
            with mock.patch.object(ai_call_log, 'PATH_OVERRIDE', path):
                ai_call_log.record('x', False, 'p', 1, f'key={OWN_G} failed')
                self.assertNotIn(OWN_G, open(path, encoding='utf-8').read())
                self.assertNotIn(OWN_G, ai_call_log.last()['detail'])

    def test_vision_key_sent_in_header_not_url(self):
        sess = mock.MagicMock()
        sess.post.return_value = mock.Mock(status_code=200, json=lambda: {'responses': [{'fullTextAnnotation': {'text': 'نص'}}]})
        with mock.patch('requests.Session', return_value=sess), mock.patch.object(gc, 'get_proxy_url', return_value=''):
            ocr_vision._post(b'x', 'direct', OWN_V)
        args, kw = sess.post.call_args
        self.assertNotIn('params', kw)
        self.assertNotIn(OWN_V, args[0])
        self.assertEqual(kw['headers']['X-Goog-Api-Key'], OWN_V)

    def test_mask_never_shows_full_key(self):
        for k in (OWN_G, OWN_O, OWN_V, 'x' * 10, 'y' * 12):
            self.assertNotEqual(gc.mask_key(k), k)
            self.assertLess(len(gc.mask_key(k)), len(k) + 1)
        self.assertNotIn(OWN_G[4:-4], gc.mask_key(OWN_G))

    def test_log_audit_detects_leaks(self):
        with open(gc._LOG_PATH, 'w', encoding='utf-8') as f:
            f.write(f'line ok\nline key={OWN_V}\nclean key=***\n')
        with mock.patch.object(secret_audit, '_log_paths', lambda: [gc._LOG_PATH]):
            self.assertEqual([n for _, n in secret_audit.find_key_leaks_in_logs()], [1])
        gc._log('direct', 'FAIL', error=RuntimeError('url?key=' + OWN_V))
        with mock.patch.object(secret_audit, '_log_paths', lambda: [gc._LOG_PATH]):
            self.assertEqual(len(secret_audit.find_key_leaks_in_logs()), 1)    # الأسطر القديمة فقط، السطر الجديد نظيف
        with open(gc._LOG_PATH, 'w', encoding='utf-8') as f:
            pass
        gc._log('direct', 'FAIL', error=RuntimeError('url?key=' + OWN_V))
        with mock.patch.object(secret_audit, '_log_paths', lambda: [gc._LOG_PATH]):
            self.assertEqual(secret_audit.find_key_leaks_in_logs(), [])


class SettingsCardsTests(TmpExpertDir):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def page(self):
        import qt_settings_page as sp
        from PyQt6.QtWidgets import QWidget
        page = sp.SettingsPage.__new__(sp.SettingsPage)
        QWidget.__init__(page)
        page._cards = []
        orig = page._build_key_card
        page._build_key_card = lambda which: page._cards.append(orig(which)) or page._cards[-1]
        return sp, page

    def test_sections_and_urls(self):
        sp, page = self.page()
        want = {'vision': 'https://console.cloud.google.com/apis/credentials',
                'ocrspace': 'https://ocr.space/ocrapi/freekey',
                'gemini': 'https://aistudio.google.com/app/apikey',
                'openai': 'https://platform.openai.com/api-keys'}
        self.assertEqual({k: v['url'] for k, v in sp.SettingsPage.KEY_CARDS.items()}, want)
        for which, url in want.items():
            page._build_key_card(which)
            with mock.patch.object(sp.QDesktopServices, 'openUrl') as op:
                page._key_widgets[which]['link'].click()
            op.assert_called_once()
            self.assertEqual(op.call_args[0][0].toString(), url)

    def test_helper_texts(self):
        sp, page = self.page()
        cards = sp.SettingsPage.KEY_CARDS
        self.assertIn('فعّل Cloud Vision API', cards['vision']['note'])
        self.assertEqual(cards['openai']['note'], 'اشتراك ChatGPT Plus لا يكفي، تحتاج مفتاح API برصيد.')

    def test_status_line_three_states(self):
        sp, page = self.page()
        page._build_key_card('gemini')
        for src, text in (('own', 'يُستعمل مفتاحك'), ('shared', 'لا يوجد مفتاح شخصي، يُستعمل مفتاح القسم'),
                          ('none', 'لا يوجد مفتاح')):
            with mock.patch.object(ap, 'key_source', lambda w, s=src: s), \
                    mock.patch.object(gc, 'load_api_key', lambda: OWN_G):
                page._refresh_key_status('gemini')
            shown = page._key_widgets['gemini']['status'].text()
            self.assertIn(text, shown)
            self.assertNotIn(OWN_G, shown)                         # لا يظهر المفتاح كاملاً

    def test_save_accepts_any_prefix_and_clears_entry(self):
        sp, page = self.page()
        saved = []
        for which in ('gemini', 'openai', 'vision', 'ocrspace'):
            page._build_key_card(which)
        for key in ('AQ.weird-prefix_123456789', 'AIzaSyOldStyle1234567890', 'not-a-standard-key', 'sk-abc'):
            page._key_widgets['gemini']['entry'].setText(key)
            with mock.patch.object(page, '_key_io', lambda w: (lambda: '', saved.append)), \
                    mock.patch.object(sp.QMessageBox, 'information'), mock.patch.object(sp.QMessageBox, 'warning') as warn:
                page._save_key('gemini')
            warn.assert_not_called()
            self.assertEqual(page._key_widgets['gemini']['entry'].text(), '')
        self.assertEqual(saved, ['AQ.weird-prefix_123456789', 'AIzaSyOldStyle1234567890', 'not-a-standard-key', 'sk-abc'])

    def test_test_button_reports_arabic_reason_without_key(self):
        sp, page = self.page()
        page._build_key_card('openai')
        err = f'ProviderHTTPError: chatgpt HTTP 401: Incorrect API key provided: {OWN_O}'
        with mock.patch.object(page, '_key_io', lambda w: (lambda: OWN_O, None)), \
                mock.patch.object(page, '_run_key_test', lambda w: (False, err)), \
                mock.patch.object(sp.QMessageBox, 'critical') as crit:
            page._test_key('openai')
        shown = ' '.join(str(a) for a in crit.call_args[0])
        self.assertIn('المفتاح غير صالح', shown)
        self.assertNotIn(OWN_O, shown)

    def test_test_button_success(self):
        sp, page = self.page()
        page._build_key_card('vision')
        with mock.patch.object(page, '_key_io', lambda w: (lambda: OWN_V, None)), \
                mock.patch.object(page, '_run_key_test', lambda w: (True, 'حكمت المحكمة')), \
                mock.patch.object(sp.QMessageBox, 'information') as info:
            page._test_key('vision')
        self.assertIn('حكمت المحكمة', ' '.join(str(a) for a in info.call_args[0]))

    def test_test_without_personal_key_does_not_hit_network(self):
        sp, page = self.page()
        page._build_key_card('ocrspace')
        with mock.patch.object(page, '_key_io', lambda w: (lambda: '', None)), \
                mock.patch.object(page, '_run_key_test') as run, \
                mock.patch.object(sp.QMessageBox, 'warning') as warn:
            page._test_key('ocrspace')
        run.assert_not_called()
        warn.assert_called_once()

    def test_two_sections_order_in_general_settings(self):
        sp, page = self.page()
        import inspect
        src = inspect.getsource(sp.SettingsPage._build)
        i = [src.index(s) for s in ("قراءة المستندات (OCR)", "_build_key_card('vision')", "_build_key_card('ocrspace')",
                                    "مفاتيح الذكاء الاصطناعي", "_build_key_card('gemini')", "_build_key_card('openai')")]
        self.assertEqual(i, sorted(i))


if __name__ == '__main__':
    unittest.main()
