# فشل المفتاح الشخصي لا ينتقل لمزوّد آخر بصمت: توقف المهمة + رسالة بالسبب + خيارات بأزرار + Groq خارج كل السلاسل
# python -W ignore -m unittest test_key_failure -v
import os
import types
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import ai_call_log
import ai_providers as ap
import doc_router
import gemini_config as gc

OWN_G = 'AQ.OwnGeminiKey_abcdefghijklmnopqrstuvwxyz'
OWN_O = 'sk-proj-OwnOpenAIKey_abcdefghijklmnop'
SEC_G, SEC_O = 'AIzaSECTIONgemini_abcdefghijklmnop', 'sk-SECTIONopenai_abcdefghijklmnop'


def rows(section_gemini=True, section_openai=True):
    out = [{'name': 'zai', 'kind': 'openai', 'api_key': 'zai-SECTION-key-abcdefghij', 'enabled': 1, 'priority': 10,
            'base_url': 'https://api.z.ai/api/paas/v4', 'model': 'm'},
           {'name': 'groq', 'kind': 'openai', 'api_key': 'gsk_SECTIONgroup_abcdefghij', 'enabled': 1, 'priority': 20,
            'base_url': 'https://api.groq.com/openai/v1', 'model': 'm'}]
    if section_gemini:
        out.append({'name': 'Gemini', 'kind': 'gemini', 'api_key': SEC_G, 'enabled': 1, 'priority': 1, 'model': ''})
    if section_openai:
        out.append({'name': 'chatgpt', 'kind': 'openai', 'api_key': SEC_O, 'enabled': 1, 'priority': 5,
                    'base_url': 'https://api.openai.com/v1', 'model': 'gpt-4o-mini'})
    return out


class Base(unittest.TestCase):
    g, o, section_gemini, section_openai = OWN_G, OWN_O, True, True

    def setUp(self):
        ap.reset_key_state()
        self.addCleanup(ap.reset_key_state)
        gc.pop_personal_failures()
        for target, value in (
                (ap, ('get_provider_configs', lambda: rows(self.section_gemini, self.section_openai))),
                (gc, ('feature_on', lambda k: True)),
                (gc, ('load_api_key', lambda: self.g)),
                (gc, ('load_openai_key', lambda: self.o)),
                (gc, ('_run_with_routes', lambda fn, s, t: fn('direct'))),
                (gc, ('_log', lambda *a, **k: None)),
                (ap.BrowserProvider, ('bot_dir', classmethod(lambda cls: None)))):
            p = mock.patch.object(target, *value)
            p.start()
            self.addCleanup(p.stop)

    def run_chain(self, call, chain=None):
        return ap.run_chain(call, 10, 10, chain=chain)


class StopOnPersonalFailureTests(Base):
    def calls_failing(self, msg, kind=ap.GeminiProvider):
        used = []

        def call(p, route):
            used.append((p.name, p.key_type, p.api_key))
            if p.key_type == ap.KEY_OWN and isinstance(p, kind):
                raise RuntimeError(msg)
            return ap.AIResponse('ok', p.name)
        return used, call

    def test_gemini_personal_failure_stops_and_calls_nobody_else(self):
        used, call = self.calls_failing('HTTP 400 API key not valid. Please pass a valid API key.')
        with self.assertRaises(ap.PersonalKeyFailure) as cm:
            self.run_chain(call)                                    # السلسلة الكاملة: Gemini + ChatGPT + z.ai + أقسام
        self.assertEqual(used, [('Gemini', ap.KEY_OWN, OWN_G)])     # لا ChatGPT ولا z.ai ولا Groq ولا مفتاح القسم
        f = cm.exception
        self.assertEqual((f.kind, f.cause, f.label), ('gemini', 'invalid', 'Gemini'))
        self.assertEqual(f.alt, 'openai')
        self.assertTrue(f.section)
        self.assertIn('المفتاح غير صالح', str(f))
        self.assertIn('لم ينتقل إلى أي مزوّد آخر', str(f))

    def test_each_cause_has_arabic_reason(self):
        cases = {'HTTP 401 invalid api key': ('invalid', 'المفتاح غير صالح'),
                 'HTTP 429 insufficient_quota': ('quota', 'نفد الرصيد'),
                 'HTTP 429 rate limit reached for requests': ('rate', 'تجاوزت الحد'),
                 gc.USER_FAIL_MSG: ('network', 'انقطع الاتصال'),
                 'شيء غريب': ('other', 'خطأ من المزوّد')}
        for msg, (cause, text) in cases.items():
            ap.reset_key_state()
            used, call = self.calls_failing(msg)
            with self.assertRaises(ap.PersonalKeyFailure) as cm:
                self.run_chain(call)
            self.assertEqual(cm.exception.cause, cause, msg)
            self.assertIn(text, str(cm.exception), msg)
            self.assertEqual(len(used), 1, msg)

    def test_openai_personal_failure_offers_gemini_and_stops(self):
        used, call = self.calls_failing('HTTP 429 insufficient_quota', kind=ap.OpenAICompatProvider)
        chain = ap.build_chain()
        # Gemini الشخصي ينجح فنقدّم ChatGPT وحده ليفشل: السلسلة ChatGPT أولاً
        chain = [p for p in chain if isinstance(p, ap.OpenAIOwnProvider)] + [p for p in chain if not isinstance(p, ap.OpenAIOwnProvider)]
        with self.assertRaises(ap.PersonalKeyFailure) as cm:
            self.run_chain(call, chain)
        self.assertEqual(cm.exception.kind, 'openai')
        self.assertEqual(cm.exception.alt, 'gemini')
        self.assertEqual([u[1] for u in used], [ap.KEY_OWN])

    def test_options_reflect_what_exists(self):
        self.o, self.section_gemini = '', False                     # لا مفتاح ChatGPT شخصي ولا مفتاح قسم لـGemini
        used, call = self.calls_failing('HTTP 401 invalid api key')
        with self.assertRaises(ap.PersonalKeyFailure) as cm:
            self.run_chain(call)
        self.assertIsNone(cm.exception.alt)
        self.assertFalse(cm.exception.section)

    def test_shared_key_failures_still_fall_through_but_never_to_groq(self):
        self.g = self.o = ''                                        # لا مفاتيح شخصية: السلوك القديم للقسم
        used = []

        def call(p, route):
            used.append(p.name)
            if p.name in ('Gemini', 'chatgpt'):
                raise RuntimeError('HTTP 500')
            return ap.AIResponse('ok', p.name)
        resp = self.run_chain(call)
        self.assertEqual(resp.provider, 'zai')
        self.assertNotIn('groq', used)

    def test_blocked_in_same_job_thread_until_decision(self):
        import threading
        out = {}

        def job():
            used, call = self.calls_failing('HTTP 401 invalid api key')
            for i in range(3):                                      # خطوات متتالية لنفس المهمة (محاور البحث مثلاً)
                try:
                    self.run_chain(call)
                except ap.PersonalKeyFailure:
                    pass
            out['n'] = len(used)
        t = threading.Thread(target=job)
        t.start()
        t.join()
        self.assertEqual(out['n'], 1)                               # الخطوتان التاليتان فشلتا فوراً بلا شبكة

    def test_pop_key_failure_once_and_cleared_by_personal_success(self):
        used, call = self.calls_failing('HTTP 401 invalid api key')
        with self.assertRaises(ap.PersonalKeyFailure):
            self.run_chain(call)
        self.assertIsNotNone(ap.pop_key_failure())
        self.assertIsNone(ap.pop_key_failure())

    def test_cancel_is_not_a_key_failure(self):
        def call(p, route):
            raise ap.UserCancelled()
        with self.assertRaises(ap.UserCancelled):
            self.run_chain(call)
        self.assertIsNone(ap.pop_key_failure())


class ChoiceTests(Base):
    def fail_once(self):
        def call(p, route):
            raise RuntimeError('HTTP 401 invalid api key')
        with self.assertRaises(ap.PersonalKeyFailure) as cm:
            self.run_chain(call)
        return cm.exception

    def test_alt_chatgpt_continues_with_chatgpt_personal_only(self):
        f = self.fail_once()
        ap.set_key_choice('alt', f)
        chain = ap.build_chain()
        self.assertFalse(any(isinstance(p, ap.GeminiProvider) for p in chain))     # ولا Gemini القسم
        self.assertIsInstance(chain[0], ap.OpenAIOwnProvider)
        used = []

        def call(p, route):
            used.append((p.name, p.key_type, p.api_key))
            return ap.AIResponse('تم', p.name)
        resp = self.run_chain(call, chain)
        self.assertEqual(used, [('chatgpt', ap.KEY_OWN, OWN_O)])
        self.assertEqual(resp.provider, 'chatgpt')
        label = ap.provider_label(chain[0])
        self.assertIn('ChatGPT (مفتاحك)', label)
        self.assertIn('بدلاً من Gemini', label)                     # يُذكر في «كُتب بواسطة»

    def test_alt_replaces_task_spec_even_for_gemini_only_research(self):
        f = self.fail_once()
        ap.set_key_choice('alt', f)
        with mock.patch.object(ap, 'get_task_specs', lambda: {'research': 'gemini', 'write': 'gemini,openai'}):
            for task in ('research', 'write'):
                chain = ap.build_task_chain(task, 'gemini' if task == 'research' else None)
                self.assertEqual([p.name for p in chain], ['chatgpt'], task)

    def test_alt_failure_also_stops_no_section_fallback(self):
        f = self.fail_once()
        ap.set_key_choice('alt', f)
        used = []

        def call(p, route):
            used.append(p.api_key)
            raise RuntimeError('HTTP 429 insufficient_quota')
        with self.assertRaises(ap.PersonalKeyFailure) as cm:
            self.run_chain(call, ap.build_chain())
        self.assertEqual(used, [OWN_O])
        self.assertEqual(cm.exception.kind, 'openai')

    def test_section_key_only_after_explicit_choice(self):
        f = self.fail_once()
        # بلا قرار: مفتاح القسم لا يظهر في السلسلة
        self.assertNotIn(SEC_G, [p.api_key for p in ap.build_chain()])
        ap.set_key_choice('section', f)
        chain = ap.build_chain()
        gem = [p for p in chain if isinstance(p, ap.GeminiProvider)]
        self.assertEqual([(p.key_type, p.api_key) for p in gem], [(ap.KEY_DEFAULT, SEC_G)])
        self.assertNotIn(OWN_G, [p.api_key for p in chain])
        self.assertIn('(مفتاح القسم)', ap.provider_label(gem[0]))
        self.assertIn('باختيارك', ap.provider_label(gem[0]))

    def test_section_choice_does_not_unlock_other_provider_section_key(self):
        f = self.fail_once()
        ap.set_key_choice('section', f)
        chain = ap.build_chain()
        self.assertEqual([p.api_key for p in chain if p.name == 'chatgpt'], [OWN_O])   # ChatGPT بقي شخصياً

    def test_retry_keeps_personal_key_and_labels_it(self):
        f = self.fail_once()
        ap.set_key_choice('retry', f)
        chain = ap.build_chain()
        self.assertEqual(chain[0].api_key, OWN_G)
        self.assertEqual(self.run_chain(lambda p, r: ap.AIResponse('ok', p.name), chain).provider, 'Gemini')
        self.assertIn('بعد إعادة المحاولة', ap.provider_label(chain[0]))

    def test_written_by_line_after_choice(self):
        import case_research
        f = self.fail_once()
        ap.set_key_choice('alt', f)
        with mock.patch.object(ap, 'get_task_specs', lambda: {'research': 'gemini'}):
            with mock.patch.object(ap.OpenAIOwnProvider, 'generate_text',
                                   lambda self, contents, route, timeout: ap.AIResponse('نص', self.name)):
                case_research.default_ask('سؤال', 'research')
        self.assertIn('ChatGPT (مفتاحك)', ai_call_log.last_provider())
        self.assertIn('بدلاً من Gemini', ai_call_log.last_provider())

    def test_clear_returns_to_normal(self):
        f = self.fail_once()
        ap.set_key_choice('alt', f)
        ap.clear_key_choice()
        self.assertTrue(any(isinstance(p, ap.GeminiProvider) and p.api_key == OWN_G for p in ap.build_chain()))


class GroqNeverTests(Base):
    def test_groq_absent_from_every_chain_and_task(self):
        self.g = self.o = ''
        for chain in (ap.build_chain(), ap.build_text_chain(), ap.build_image_chain()):
            self.assertNotIn('groq', [p.name.lower() for p in chain])
        with mock.patch.object(ap, 'get_task_specs', lambda: dict(ap.TASK_DEFAULTS)):
            for task in ap.TASKS:
                try:
                    chain = ap.build_task_chain(task)
                except ap.ProviderMissing:
                    continue
                self.assertNotIn('groq', [p.name.lower() for p in chain], task)

    def test_explicit_groq_spec_gives_nothing(self):
        with self.assertRaises(ap.ProviderMissing):
            ap.build_task_chain('write', 'groq')

    def test_run_chain_filters_a_groq_provider_even_if_passed_in(self):
        g = ap.OpenAICompatProvider('groq', 'k', ap.KEY_DEFAULT, 'm', 'https://api.groq.com/openai/v1')
        z = ap.OpenAICompatProvider('zai', 'k', ap.KEY_DEFAULT, 'm', 'https://api.z.ai/api/paas/v4')
        used = []

        def call(p, route):
            used.append(p.name)
            if p.name == 'zai':
                raise RuntimeError('HTTP 500')
            return ap.AIResponse('ok', p.name)
        with self.assertRaises(RuntimeError):
            self.run_chain(call, [g, z])
        self.assertEqual(used, ['zai'])

    def test_task_combo_has_no_groq_option(self):
        import inspect
        import qt_settings_page as sp
        self.assertIn('_is_groq', inspect.getsource(sp.SettingsPage._build_task_providers_card))


class ReadingAndExtractionTests(Base):
    def test_gemini_reading_engine_stops_on_personal_key_failure(self):
        prov = ap.GeminiProvider('Gemini', OWN_G, ap.KEY_OWN)
        with mock.patch.object(doc_router, '_gemini_provider', lambda: prov), \
                mock.patch.object(doc_router, '_as_pdf', lambda path, tmp: path), \
                mock.patch.object(doc_router, 'page_count', lambda p: 2), \
                mock.patch.object(doc_router.os.path, 'getsize', lambda p: 100), \
                mock.patch.object(doc_router, 'plan_chunks', lambda *a, **k: [(0, 2, 'x.pdf')]), \
                mock.patch.object(doc_router, '_call_provider_retry', side_effect=RuntimeError('HTTP 429 insufficient_quota')):
            run = doc_router.gemini_engine(lambda path: ('محلي', 1))
            with self.assertRaises(ap.PersonalKeyFailure) as cm:
                run('a.pdf', {})
        self.assertEqual(cm.exception.cause, 'quota')

    def test_read_numbers_does_not_fall_back_to_ocr_after_personal_failure(self):
        called = []
        failure = ap.PersonalKeyFailure('gemini', 'invalid', 'x')

        def gem(path, doc):
            raise failure

        def vision(path, doc):
            called.append('vision')
            return 'نص', 1, ''
        with mock.patch.object(doc_router, '_gemini_provider', lambda: object()), \
                mock.patch.object(doc_router, 'build_engines',
                                  lambda local, status=None: {doc_router.ENGINE_GEMINI: gem, doc_router.ENGINE_VISION: vision,
                                                              doc_router.ENGINE_EXTERNAL: vision, doc_router.ENGINE_LOCAL: vision}), \
                mock.patch('ocr_vision.is_available', lambda: True):
            with self.assertRaises(ap.PersonalKeyFailure):
                doc_router.read_numbers_pdf('a.pdf', lambda p: ('محلي', 1))
        self.assertEqual(called, [])

    def test_extraction_critical_path_reraises_instead_of_falling_to_standard(self):
        failure = ap.PersonalKeyFailure('gemini', 'invalid', 'x')
        prov = ap.GeminiProvider('Gemini', OWN_G, ap.KEY_OWN)
        std = mock.Mock()
        with mock.patch('provider_sync.refresh', lambda: None), \
                mock.patch.object(gc, 'cleanup_temp_pdfs', lambda: None), \
                mock.patch.object(ap, 'build_chain', lambda: [prov]), \
                mock.patch.object(gc, 'prepare_pdf', lambda *a, **k: {'kind': 'pdf', 'path': 'x', 'size_after': 1}), \
                mock.patch.object(ap, 'run_chain', side_effect=failure), \
                mock.patch.object(gc, '_generate_standard', std):
            with self.assertRaises(ap.PersonalKeyFailure):
                gc.generate_from_pdf('p', 'x.pdf', critical=True)
        std.assert_not_called()


class FakeBox:
    """بديل QMessageBox: يسجّل الأزرار ويضغط الزر المطلوب باسمه."""
    from PyQt6.QtWidgets import QMessageBox as _Q
    Icon, ButtonRole, StandardButton = _Q.Icon, _Q.ButtonRole, _Q.StandardButton
    choose = None
    confirm = True
    last = None

    def __init__(self, *a):
        self.buttons, self.clicked, FakeBox.last = [], None, self
        self.text = ''

    def setIcon(self, *a): pass
    def setWindowTitle(self, *a): pass
    def setDetailedText(self, *a): pass
    def setText(self, t): self.text = t

    def addButton(self, text, role):
        b = types.SimpleNamespace(text=text)
        self.buttons.append(b)
        return b

    def exec(self):
        self.clicked = next((b for b in self.buttons if b.text == FakeBox.choose), None)

    def clickedButton(self):
        return self.clicked

    @staticmethod
    def question(*a, **k):
        return FakeBox.StandardButton.Yes if FakeBox.confirm else FakeBox.StandardButton.No


class DialogTests(Base):
    def setUp(self):
        super().setUp()
        import qt_case_track as qt
        self.qt = qt
        p = mock.patch.object(qt, 'QMessageBox', FakeBox)
        p.start()
        self.addCleanup(p.stop)
        FakeBox.choose, FakeBox.confirm, FakeBox.last = None, True, None
        self.me = types.SimpleNamespace(status=mock.Mock(), _run_bg=mock.Mock(), _last_job=(lambda: None, 'نص', None),
                                        _after=None, _choice_active=False)

    def failure(self, alt='openai', section=True, kind='gemini'):
        return ap.PersonalKeyFailure(kind, 'quota', 'HTTP 429', alt=alt, section=section)

    def ask(self, f, choose):
        FakeBox.choose = choose
        self.qt.CaseTrackDialog._ask_key_failure(self.me, f)

    def test_buttons_with_all_options(self):
        self.ask(self.failure(), 'إلغاء')
        self.assertEqual([b.text for b in FakeBox.last.buttons],
                         ['أعد المحاولة', 'استعمل ChatGPT (مفتاحك)', 'استعمل مفتاح القسم', 'إلغاء'])
        self.assertIn('نفد الرصيد', FakeBox.last.text)
        self.assertIn('لم ينتقل إلى أي مزوّد آخر', FakeBox.last.text)

    def test_buttons_hide_unavailable_options(self):
        self.ask(self.failure(alt=None, section=False), 'إلغاء')
        self.assertEqual([b.text for b in FakeBox.last.buttons], ['أعد المحاولة', 'إلغاء'])
        self.ask(self.failure(alt='gemini', section=False, kind='openai'), 'إلغاء')
        self.assertEqual([b.text for b in FakeBox.last.buttons], ['أعد المحاولة', 'استعمل Gemini (مفتاحك)', 'إلغاء'])

    def test_cancel_runs_nothing_and_sets_no_choice(self):
        self.ask(self.failure(), 'إلغاء')
        self.me._run_bg.assert_not_called()
        self.assertIsNone(ap.get_key_choice())

    def test_retry_reruns_same_job(self):
        self.ask(self.failure(), 'أعد المحاولة')
        self.assertEqual(ap.get_key_choice()['use'], 'retry')
        self.me._run_bg.assert_called_once_with(self.me._last_job[0], 'نص')
        self.assertTrue(self.me._choice_active)

    def test_chatgpt_choice_reruns_with_alt(self):
        self.ask(self.failure(), 'استعمل ChatGPT (مفتاحك)')
        c = ap.get_key_choice()
        self.assertEqual((c['use'], c['kind'], c['alt']), ('alt', 'gemini', 'openai'))
        self.me._run_bg.assert_called_once()

    def test_section_needs_explicit_confirmation(self):
        FakeBox.confirm = False
        self.ask(self.failure(), 'استعمل مفتاح القسم')
        self.me._run_bg.assert_not_called()
        self.assertIsNone(ap.get_key_choice())                     # لم يوافق ← لا مفتاح قسم
        FakeBox.confirm = True
        self.ask(self.failure(), 'استعمل مفتاح القسم')
        self.assertEqual(ap.get_key_choice()['use'], 'section')
        self.me._run_bg.assert_called_once()

    def test_offer_provider_choice_shows_dialog_when_failure_pending(self):
        f = self.failure()
        me = types.SimpleNamespace(_ask_key_failure=mock.Mock())
        with mock.patch.object(ap, 'pop_key_failure', lambda max_age=600: f):
            self.qt.CaseTrackDialog._offer_provider_choice(me)
        me._ask_key_failure.assert_called_once_with(f)

    def test_completed_task_does_not_open_dialog_for_side_failure(self):
        """25/10: طلب جانبي انقطع (180ث) والتقرير انطبع ← لا نافذة خيارات، سطر في الحالة فقط."""
        f = self.failure()
        me = types.SimpleNamespace(_ask_key_failure=mock.Mock(), status=mock.Mock())
        with mock.patch.object(ap, 'pop_key_failure', lambda max_age=600: f), \
                mock.patch.object(ap, 'pop_personal_failures', lambda: []), \
                mock.patch.object(ap, 'pop_missing', lambda: None):
            self.qt.CaseTrackDialog._offer_provider_choice(me, stopped=False)
        me._ask_key_failure.assert_not_called()
        self.assertIn('أكمل البرنامج المهمة', me.status.setText.call_args[0][0])

    def test_on_done_passes_stopped_only_for_key_failure(self):
        def run(err):
            me = types.SimpleNamespace(
                _choice_active=False, _timer=mock.Mock(), _busy=True, stop_btn=mock.Mock(), track=mock.Mock(),
                status=mock.Mock(), _after=None, reload=mock.Mock(), _report_running=True,
                _offer_provider_choice=mock.Mock())
            with mock.patch.object(self.qt.QMessageBox, 'critical', create=True):
                self.qt.CaseTrackDialog._on_done(me, err)
            return me._offer_provider_choice.call_args.kwargs['stopped']
        self.assertFalse(run(None))                                # المهمة نجحت
        self.assertTrue(run(ap.PersonalKeyFailure('gemini', 'timeout')))

    def test_on_done_clears_choice_after_rerun_and_skips_double_error_box(self):
        ap.set_key_choice('alt', self.failure())
        me = types.SimpleNamespace(
            _choice_active=True, _timer=mock.Mock(), _busy=True, stop_btn=mock.Mock(), track=mock.Mock(), status=mock.Mock(),
            _after=None, reload=mock.Mock(), _report_running=True, _offer_provider_choice=mock.Mock())
        with mock.patch.object(self.qt.QMessageBox, 'critical', create=True) as crit:
            self.qt.CaseTrackDialog._on_done(me, ap.PersonalKeyFailure('gemini', 'invalid'))
        self.assertIsNone(ap.get_key_choice())
        self.assertFalse(me._choice_active)
        crit.assert_not_called()                                   # النافذة الوحيدة هي نافذة الخيارات


if __name__ == '__main__':
    unittest.main()
