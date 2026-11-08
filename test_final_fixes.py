# جودة تحضير الحاسم، حكم الإحالة، التلخيص، تحصين التغليف، تحذير المفاتيح: python -W ignore -m unittest test_final_fixes -v
import json
import os
import re
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QLabel   # قبل fitz (تعارض DLL)

import fitz

import ai_providers as ap
import doc_router
import gemini_config as gc

HERE = os.path.dirname(os.path.abspath(__file__))
APP = QApplication.instance() or QApplication([])      # يبقى مرجعاً حياً (إتلافه = qFatal عند أول ودجت)


def scanned_pdf(path, pages=1):
    """PDF بصفحات صورة فقط (بلا طبقة نصية)."""
    src = fitz.open()
    pg = src.new_page(width=595, height=842)
    pg.insert_htmlbox(pg.rect + (30, 30, -30, -30), '<p dir="rtl" style="font-size:28px">المبلغ 5,876.540 دينار كويتي</p>')
    pix = pg.get_pixmap(dpi=100)
    out = fitz.open()
    for _ in range(pages):
        p = out.new_page(width=595, height=842)
        p.insert_image(p.rect, stream=pix.tobytes('png'))
    out.save(path)


def text_pdf(path):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((50, 100), 'plain latin text layer ' * 20)
    d.save(path)


def image_info(pdf_path):
    with fitz.open(pdf_path) as d:
        xref = d[0].get_images()[0][0]
        info = d.extract_image(xref)
        return info['width'], info['colorspace']


class PrepareQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = os.path.join(self.tmp.name, 's.pdf')
        scanned_pdf(self.pdf)
        self.addCleanup(self.tmp.cleanup)

    def prep(self, **kw):
        prep = gc.prepare_pdf(self.pdf, **kw)
        if prep.get('temp'):
            self.addCleanup(lambda: os.path.exists(prep['path']) and os.remove(prep['path']))
        return prep

    def test_critical_is_300dpi_vs_noncritical_150dpi(self):
        normal, crit = self.prep(), self.prep(critical=True)
        self.assertEqual(round(image_info(crit['path'])[0] / 595 * 72), 300)
        self.assertEqual(round(image_info(normal['path'])[0] / 595 * 72), 150)

    def test_critical_color_is_configurable_gray_or_rgb(self):
        with mock.patch.object(gc, 'get_critical_color', lambda: 'gray'):
            self.assertEqual(image_info(self.prep(critical=True)['path'])[1], 1)
        with mock.patch.object(gc, 'get_critical_color', lambda: 'rgb'):
            self.assertEqual(image_info(self.prep(critical=True)['path'])[1], 3)

    def test_dpi_and_quality_configurable(self):
        cfg = dict(gc.get_pdf_settings(), critical_dpi=200, critical_jpeg_quality=80)
        with mock.patch.object(gc, 'get_pdf_settings', lambda: cfg):
            self.assertEqual(round(image_info(self.prep(critical=True)['path'])[0] / 595 * 72), 200)

    def test_size_cap_lowers_dpi_but_terminates(self):
        base = self.prep(critical=True)
        size_300 = os.path.getsize(base['path'])
        cfg = dict(gc.get_pdf_settings(), critical_max_mb=size_300 / 1024 / 1024 * 0.4)    # سقف أصغر من حجم 300dpi
        with mock.patch.object(gc, 'get_pdf_settings', lambda: cfg):
            capped = self.prep(critical=True)
        self.assertLess(image_info(capped['path'])[0], image_info(base['path'])[0])
        self.assertGreaterEqual(round(image_info(capped['path'])[0] / 595 * 72), 150)

    def test_defaults_present_and_under_gemini_limit(self):
        c = gc.get_pdf_settings()
        self.assertEqual((c['critical_dpi'], c['critical_jpeg_quality'], c['critical_max_mb']), (300, 90, 30))
        self.assertLess(c['critical_max_mb'], 50)

    def test_text_layer_pdf_critical_sent_as_images_noncritical_as_text(self):
        p = os.path.join(self.tmp.name, 't.pdf')
        text_pdf(p)
        self.assertEqual(gc.prepare_pdf(p)['kind'], 'text')
        crit = gc.prepare_pdf(p, critical=True)
        self.addCleanup(lambda: os.path.exists(crit['path']) and os.remove(crit['path']))
        self.assertEqual(crit['kind'], 'pdf')


class FakeGemini(ap.GeminiProvider):
    def __init__(self):
        super().__init__('Gemini', 'k', ap.KEY_DEFAULT, 'm')
        self.seen = []

    def generate(self, prompt, prep, route, timeout):
        self.seen.append(prep)
        return ap.AIResponse('{"ok": 1}', self.name)


class CriticalReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = os.path.join(self.tmp.name, 's.pdf')
        scanned_pdf(self.pdf)
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch('provider_sync.refresh', lambda: None)
        p.start()
        self.addCleanup(p.stop)

    def test_gemini_first_with_high_quality_and_recorded(self):
        fake = FakeGemini()
        with mock.patch.object(ap, 'build_chain', lambda: [fake]):
            r = gc.generate_from_pdf('p', self.pdf, trim=True, critical=True)
        self.assertEqual(r.text, '{"ok": 1}')
        self.assertEqual(gc.last_read()['engine'], 'gemini')
        self.assertEqual(fake.seen[0]['kind'], 'pdf')

    def test_without_gemini_reason_is_recorded_and_standard_path_runs(self):
        seen = {}

        def std(*a):
            seen['skipped'] = a[7]
            gc._set_read('external_ocr', a[7], True)
            return ap.AIResponse('x', 'groq')
        with mock.patch.object(ap, 'build_chain', lambda: []), mock.patch.object(gc, '_generate_standard', std):
            gc.generate_from_pdf('p', self.pdf, critical=True)
        self.assertEqual(seen['skipped'][0][0], 'gemini')
        self.assertIn('لا مفتاح Gemini', seen['skipped'][0][1])
        info = gc.last_read()
        self.assertEqual(info['engine'], 'external_ocr')
        self.assertTrue(info['critical'])

    def test_judgment_extraction_requests_critical(self):
        import case_info_window as ci
        with mock.patch.object(ci, 'has_any_provider', lambda: True), \
                mock.patch('gemini_config.generate_from_pdf', return_value=mock.Mock(text='{"رقم_القضية": "1"}')) as g:
            data, err = ci.extract_from_pdf('x.pdf')
        self.assertIsNone(err)
        self.assertTrue(g.call_args.kwargs['critical'])

    def test_judgment_engine_json_and_red_alert_for_non_gemini(self):
        import case_info_window as ci
        gc._set_read('local', [('gemini', 'لا مفتاح Gemini مضبوط')], True)
        info = json.loads(ci.judgment_engine_json())
        self.assertEqual(info['engine'], 'local')
        data = {'caso_no': 'A1', 'case': {'judgment_engine': ci.judgment_engine_json()}}
        out = doc_router.step_alerts(data, 'mission')
        self.assertEqual(out[0][0], 'red')
        self.assertIn('قُرئت حكم الإحالة بمحرك', out[0][1])
        self.assertIn('لا مفتاح Gemini', out[0][1])
        gc._set_read('gemini', [], True)
        data['case']['judgment_engine'] = ci.judgment_engine_json()
        self.assertEqual(doc_router.step_alerts(data, 'mission'), [])

class MissionCardAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_mission_card_shows_judgment_alert(self):
        import case_workspace as cw
        import qt_case_page as qp
        qp.CasePageDialog.AUTO_SYNC = qp.CasePageDialog.AUTO_ASK_TYPE = False
        with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as f:
            case = json.load(f)
        case['judgment_engine'] = json.dumps({'engine': 'local', 'skipped': []})
        base, _ = cw.ensure_workspace(case, self.tmp.name)
        dlg = qp.CasePageDialog(base, cw.read_case_json(base))
        dlg.open_step('mission')
        text = ' '.join(l.text() for l in dlg.card.findChildren(QLabel))
        self.assertIn('حكم الإحالة', text)
        self.assertIn('OCR', text)


class SummarizerTaskTests(unittest.TestCase):
    def test_summarizer_uses_summarize_task(self):
        import summarizer
        with mock.patch.object(summarizer, 'has_any_provider', lambda: True), \
                mock.patch('gemini_config.generate_from_pdf', return_value=mock.Mock(text='قضية تعاقدية')) as g:
            text, err = summarizer.summarize_claim_pdf('x.pdf')
        self.assertEqual((text, err), ('قضية تعاقدية', None))
        self.assertEqual(g.call_args.kwargs['task'], 'summarize')

    def test_task_chain_is_used_for_text_path(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pdf = os.path.join(tmp.name, 't.pdf')
        text_pdf(pdf)

        class P(ap.Provider):
            def generate(self_, prompt, prep, route, timeout):
                return ap.AIResponse('ملخص', 'MyProv')
        chain = [P('MyProv', 'k')]
        with mock.patch('provider_sync.refresh', lambda: None), \
                mock.patch.object(ap, 'build_task_chain', return_value=chain) as bt:
            r = gc.generate_from_pdf('p', pdf, purpose='summary', task='summarize')
        self.assertEqual(r.text, 'ملخص')
        bt.assert_called_with('summarize')

    def test_missing_task_provider_surfaces_in_summary_error(self):
        import summarizer
        with mock.patch.object(summarizer, 'has_any_provider', lambda: True), \
                mock.patch('gemini_config.generate_from_pdf',
                           side_effect=ap.ProviderMissing('summarize', 'gemini', 'لا مزوّد')), \
                mock.patch.object(summarizer, '_local_summary', lambda p, e: (None, e)):
            text, err = summarizer.summarize_claim_pdf('x.pdf')
        self.assertIsNone(text)
        self.assertIn('لا مزوّد', err)


class PackagingTests(unittest.TestCase):
    def spec_ns(self):
        src = open(os.path.join(HERE, 'ExpertApp.spec'), encoding='utf-8').read()
        a = src.index('# ---- تحصين')
        b = src.index('a.datas = [d for d in a.datas if not _is_secret_data(d)]')
        ns = {'SPECPATH': HERE}
        exec(src[a:b], ns)
        return ns

    def test_spec_filters_ini_and_secret_names(self):
        f = self.spec_ns()['_is_secret_data']
        self.assertTrue(f(('gemini_network.ini', os.path.join(HERE, 'gemini_network.ini'), 'DATA')))
        self.assertTrue(f(('sub/other.ini', os.path.join(HERE, 'x', 'other.ini'), 'DATA')))
        self.assertTrue(f(('ai_providers_cache.json', 'C:/anywhere/ai_providers_cache.json', 'DATA')))
        self.assertTrue(f(('ocr_key.json', 'C:/anywhere/ocr_key.json', 'DATA')))
        self.assertFalse(f(('pkg/config.ini', 'C:/Python/Lib/site-packages/pkg/config.ini', 'DATA')))
        self.assertFalse(f(('ocr/models/dict.json', os.path.join(HERE, 'ocr', 'models', 'dict.json'), 'DATA')))

    def test_spec_filters_before_pyz_and_fails_build_if_secret_left(self):
        src = open(os.path.join(HERE, 'ExpertApp.spec'), encoding='utf-8').read()
        self.assertIn('assert not _leaked', src)
        self.assertLess(src.index('a.datas = [d for d in a.datas if not _is_secret_data(d)]'),
                        src.index('splash = Splash('))
        compile(src, 'ExpertApp.spec', 'exec')

    def test_installer_files_section_has_no_ini_or_cache(self):
        iss = open(os.path.join(HERE, 'Installer.iss'), encoding='utf-8').read()
        files = re.split(r'\n\[', iss.split('[Files]', 1)[1], 1)[0]
        srcs = re.findall(r'Source:\s*"([^"]+)"', files)
        self.assertTrue(srcs)
        for s in srcs:
            self.assertFalse(re.search(r'\.ini$|\.json$|cache|credentials|_key', s, re.I), s)
            self.assertNotIn('*', s)

    def test_provider_cache_lives_in_localappdata_not_project(self):
        import provider_sync
        path = os.path.normcase(os.path.abspath(provider_sync._CACHE_PATH))
        self.assertFalse(path.startswith(os.path.normcase(HERE) + os.sep))
        self.assertIn('expertapp', path.lower())


class SecretAuditTests(unittest.TestCase):
    def test_warns_on_plaintext_and_hides_values(self):
        import secret_audit
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ini = os.path.join(tmp.name, 'gemini_network.ini')
        with open(ini, 'w', encoding='utf-8') as f:
            f.write('[provider:groq]\napi_key = gsk_SECRETVALUE\n\n[provider:zai]\napi_key =\n')
        cache = os.path.join(tmp.name, 'cache.json')
        with open(cache, 'w') as f:
            json.dump({'providers': [{'name': 'a', 'api_key': 'sk-abc'}, {'name': 'b', 'api_key': ''}]}, f)
        with mock.patch.object(gc, '_app_dir', lambda: tmp.name), \
                mock.patch('provider_sync._CACHE_PATH', cache), \
                mock.patch.object(secret_audit, 'expert_data_dir', lambda: tmp.name):
            found = {os.path.basename(p): n for p, n in secret_audit.find_plaintext_keys()}
            text = secret_audit.warning_text()
        self.assertEqual(found, {'gemini_network.ini': 1, 'cache.json': 1})
        self.assertIn('DPAPI', text)       # الاقتراح القديم (Credential Manager) استُبدل بتشفير DPAPI المطبَّق (2026-10-21)
        self.assertNotIn('SECRETVALUE', text)
        self.assertNotIn('sk-abc', text)

    def test_no_warning_when_clean(self):
        import secret_audit
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(gc, '_app_dir', lambda: tmp.name), \
                mock.patch('provider_sync._CACHE_PATH', os.path.join(tmp.name, 'none.json')), \
                mock.patch.object(secret_audit, 'expert_data_dir', lambda: tmp.name):
            self.assertEqual(secret_audit.warning_text(), '')

    def test_settings_page_shows_warning_card_only_when_needed(self):
        import qt_settings_page as sp
        page = sp.SettingsPage.__new__(sp.SettingsPage)
        with mock.patch('secret_audit.warning_text', lambda: '⚠ مفاتيح API نص صريح'):
            card = sp.SettingsPage._build_secrets_warning(page)
        self.assertIsNotNone(card)
        self.assertIn('نص صريح', ' '.join(l.text() for l in card.findChildren(QLabel)))
        with mock.patch('secret_audit.warning_text', lambda: ''):
            self.assertIsNone(sp.SettingsPage._build_secrets_warning(page))


if __name__ == '__main__':
    unittest.main()
