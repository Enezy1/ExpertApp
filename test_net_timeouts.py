# -*- coding: utf-8 -*-
"""
test_net_timeouts.py — اختبارات مهلات طلبات الشبكة

تثبت ثلاث أشياء مهمة:
  1) أي طلب لسيرفر الوزارة ما انكتب له timeout تنحط له مهلة تلقائية
     (يعني ما يعلق للأبد لو انقطعت الشبكة).
  2) أي طلب له timeout أصلاً (ذكاء اصطناعي / Supabase / Ministry)
     ما ينمس أبداً.
  3) مهلات الذكاء الاصطناعي (60..180 ث) باقية كما هي — صفر تغيير.
"""
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

import net_timeouts


class _CaptureAdapter(requests.adapters.HTTPAdapter):
    """يلتقط الـ timeout اللي وصل فعلاً لطبقة الشبكة."""

    def __init__(self):
        super().__init__()
        self.captured = {}

    def send(self, request, **kwargs):
        self.captured = dict(kwargs)
        resp = requests.Response()
        resp.status_code = 200
        resp._content = b'ok'
        resp.url = request.url
        resp.request = request
        return resp


def _probe(url, **kwargs):
    """ينفّذ طلب حقيقي (بلا شبكة) ويرجّع الـ timeout اللي وصل للشبكة."""
    s = requests.Session()
    adapter = _CaptureAdapter()
    s.mount('https://', adapter)
    s.mount('http://', adapter)
    try:
        s.get(url, **kwargs)
    finally:
        s.close()
    return adapter.captured.get('timeout', '<absent>')


class TimeoutTableTests(unittest.TestCase):
    """جدول المهلات نفسه."""

    def test_mistry_urls_get_a_timeout(self):
        t = net_timeouts.timeout_for('https://expertapp.moj.gov.kw/ECS_CASE_FLOW')
        self.assertIsNotNone(t)
        self.assertEqual(len(t), 2)

    def test_non_ministry_urls_get_nothing(self):
        for url in (
            'https://generativelanguage.googleapis.com/v1beta/models',
            'https://xzgwlqfsdwbjoxdewffy.supabase.co/rest/v1/app_version',
            'https://ocr.space/ocrapi',
            'https://www.google.com',
            '',
        ):
            self.assertIsNone(net_timeouts.timeout_for(url), url)

    def test_my_calendar_gets_the_longest_read_timeout(self):
        """MyCalendar أثقل صفحة (2.1ث وسط / 5.2ث أعلى مرة)."""
        t = net_timeouts.timeout_for('https://expertapp.moj.gov.kw/MyCalendar')
        self.assertEqual(t, net_timeouts.MY_CALENDAR_TIMEOUT)
        self.assertGreater(t[1], net_timeouts.DEFAULT_MINISTRY_TIMEOUT[1])

    def test_load_php_gets_its_own_timeout(self):
        t = net_timeouts.timeout_for(
            'https://expertapp.moj.gov.kw/includes/load.php?start=2010-01-01&end=2035-01-01')
        self.assertEqual(t, net_timeouts.SESSIONS_LOAD_TIMEOUT)

    def test_write_endpoints_get_write_timeout(self):
        for path in ('/includes/insert.php', '/includes/set_sourc.php',
                     '/includes/insert_mubashara.php'):
            t = net_timeouts.timeout_for('https://expertapp.moj.gov.kw' + path)
            self.assertEqual(t, net_timeouts.WRITE_TIMEOUT, path)

    def test_query_string_does_not_break_path_match(self):
        t = net_timeouts.timeout_for(
            'https://expertapp.moj.gov.kw/MyCalendar?x=1')
        self.assertEqual(t, net_timeouts.MY_CALENDAR_TIMEOUT)

    def test_connect_timeout_is_short(self):
        """فشل الشبكة لازم ينكشف بسرعة مو بعد شوي."""
        self.assertLessEqual(net_timeouts.CONNECT_TIMEOUT, 5)
        self.assertEqual(net_timeouts.DEFAULT_MINISTRY_TIMEOUT[0],
                         net_timeouts.CONNECT_TIMEOUT)


class PatchBehaviourTests(unittest.TestCase):
    """الرقعة نفسها — السلوك وقت الطلب."""

    def setUp(self):
        self._was_installed = net_timeouts.is_installed()
        net_timeouts.install()

    def tearDown(self):
        if not self._was_installed:
            net_timeouts.uninstall()

    def test_ministry_request_without_timeout_gets_default(self):
        t = _probe('https://expertapp.moj.gov.kw/ECS_CASE_FLOW')
        self.assertEqual(t, net_timeouts.DEFAULT_MINISTRY_TIMEOUT)

    def test_ministry_request_keeps_its_own_timeout(self):
        t = _probe('https://expertapp.moj.gov.kw/ECS_CASE_FLOW', timeout=7)
        self.assertEqual(t, 7)

    def test_ai_request_is_untouched(self):
        """طلب الذكاء الاصطناعي — لو ما انكتب له timeout ما نضيف له شي."""
        t = _probe('https://generativelanguage.googleapis.com/v1beta/models:generate')
        self.assertIsNone(t)

    def test_ai_request_keeps_its_own_timeout(self):
        t = _probe('https://generativelanguage.googleapis.com/v1beta/models',
                   timeout=180)
        self.assertEqual(t, 180)

    def test_supabase_request_is_untouched(self):
        t = _probe('https://xzgwlqfsdwbjoxdewffy.supabase.co/rest/v1/app_version')
        self.assertIsNone(t)

    def test_install_is_idempotent(self):
        self.assertFalse(net_timeouts.install())      # نداء ثانٍ = ما سوّي شي

    def test_uninstall_restores_original(self):
        pristine = getattr(net_timeouts, '_original_request', None) or requests.Session.request
        net_timeouts.uninstall()
        try:
            self.assertIs(requests.Session.request, pristine)
        finally:
            net_timeouts.install()


class AiTimeoutsUntouchedTests(unittest.TestCase):
    """
    أهم اختبار بالمجموعة: يثبت إن مهلات الذكاء الاصطناعي ما تغيّرت.
    لو أحد عدّل وحدة المهلات وأمسّ Gemini بالغلط — هذا يسقط.
    """

    def test_case_research_timeouts_unchanged(self):
        import case_research
        self.assertEqual(case_research.TIMEOUT, 180)
        self.assertEqual(case_research.RESEARCH_TIMEOUT, 180)
        self.assertEqual(case_research.SHORT_TIMEOUTS, {
            'الموضوع': 60, 'الحضور': 60, 'الأسئلة المهمة': 90,
            'فحص الجاهزية': 120,
        })

    def test_ai_layers_keep_their_own_timeout_values(self):
        import ocr_vision
        import gemini_config
        self.assertEqual(ocr_vision.URL.startswith('https://'), True)
        self.assertTrue(hasattr(gemini_config, '_make_client'))

    def test_ai_timeout_is_much_larger_than_ministry(self):
        import case_research
        self.assertGreater(case_research.TIMEOUT,
                           net_timeouts.MY_CALENDAR_TIMEOUT[1] * 5)

    def test_net_timeouts_never_touches_ai_layer(self):
        """
        الوحدة ما تستورد ولا تشير لأي وحدة ذكاء اصطناعي بالكود
        (الفحص بالـAST — الكلام بالشرح/comments ما يُحسب).
        """
        import ast
        tree = ast.parse(open(net_timeouts.__file__, encoding='utf-8').read())
        banned = {'case_research', 'ai_providers', 'gemini_config',
                  'ocr_vision', 'ocr_space', 'ai_call_log'}
        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    seen.add(a.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    seen.add(node.module.split('.')[0])
            elif isinstance(node, ast.Name):
                seen.add(node.id)
            elif isinstance(node, ast.Attribute):
                seen.add(node.attr)
        self.assertEqual(seen & banned, set(),
                         'الوحدة تشير لوحدة ذكاء اصطناعي: %s' % (seen & banned))


class MainEntryTests(unittest.TestCase):
    """نقطة التشغيل: الرقعة مثبّتة + مهلة MyCalendar صحيحة."""

    def setUp(self):
        here = os.path.dirname(os.path.abspath(__file__))
        self.main_py = os.path.join(here, 'main.py')
        self.src = open(self.main_py, encoding='utf-8').read()

    def test_patch_installed_at_startup(self):
        self.assertIn('net_timeouts.install()', self.src)

    def test_my_calendar_uses_measured_timeout(self):
        """كان timeout=5 بينما الصفحة تاخذ 2.1..5.2 ث → فشل عشوائي."""
        calls = re.findall(r'\{BASE_URL\}/MyCalendar",?\s*\n?\s*cookies=[^\n]*\n?[^\n]*',
                           self.src)
        self.assertTrue(calls, 'ما لقيت مواضع طلب MyCalendar')
        for c in calls:
            self.assertIn('net_timeouts.MY_CALENDAR_TIMEOUT', c)
            self.assertNotIn('timeout=5)', c)

    def test_no_my_calendar_call_keeps_the_old_five_seconds(self):
        for m in re.finditer(r'MyCalendar', self.src):
            seg = self.src[m.start():m.start() + 200]
            self.assertNotIn('timeout=5)', seg, seg[:120])


class CoverageTests(unittest.TestCase):
    """
    كل طلب ministry بالمشروع الحيّ — لازم الرقعة تغطّيه (يرجّع له مهلة)
    سواء كان فيه timeout صريح أو لا. ما فيه طلب يطلع بلا حد أعلى.
    """

    def setUp(self):
        self.root = os.path.dirname(os.path.abspath(__file__))
        self.skip_dirs = {'قديم', 'محذوفه', '__pycache__', 'build', 'dist',
                          'installer_output', '.claude', 'assets', 'fonts',
                          'ocr', 'report_assets', 'samples', 'test_data',
                          'tools', 'shots_style', 'stitch', 'design', 'تجارب'}

    def _py_files(self):
        out = []
        for dp, dn, fns in os.walk(self.root):
            dn[:] = [d for d in dn if d not in self.skip_dirs]
            for f in fns:
                if f.endswith('.py'):
                    out.append(os.path.join(dp, f))
        return out

    def _ministry_sites(self):
        """كل مواضع الاستدعاءات لسيرفر الوزارة (رابط BASE_URL أو مسار ministry)."""
        pattern = re.compile(
            r'requests\.(get|post|put|delete|patch)\(\s*'
            r'(f?)["\']([^"\']+)["\']', re.IGNORECASE)
        sites = []
        for path in self._py_files():
            src = open(path, encoding='utf-8', errors='replace').read()
            for m in pattern.finditer(src):
                url = m.group(3)
                # SUPABASE_URL فيها كلمة BASE_URL كجزء من الاسم — مو ministry
                if 'SUPABASE' in url:
                    continue
                if 'BASE_URL' not in url and 'moj.gov.kw' not in url:
                    continue
                line = src.count('\n', 0, m.start()) + 1
                if '{BASE_URL}' in url:
                    url = url.replace('{BASE_URL}', 'https://expertapp.moj.gov.kw')
                sites.append((os.path.relpath(path, self.root), line, url))
        return sites

    def test_every_ministry_call_site_is_covered_by_the_patch(self):
        """أي طلب ministry — الرقعة ترجّع له مهلة (ما يعلق للأبد)."""
        sites = self._ministry_sites()
        self.assertGreater(len(sites), 0, 'ما لقيت أي طلب ministry — الفحص مو صالح')
        uncovered = []
        for rel, line, url in sites:
            if net_timeouts.timeout_for(url) is None:
                uncovered.append('%s:%d  %s' % (rel, line, url))
        self.assertEqual(uncovered, [],
                         'مواضع ministry ما تغطّيها الرقعة:\n' + '\n'.join(uncovered))

    def test_ministry_call_sites_are_enough_to_be_worth_covering(self):
        """رقم يوثّق حجم التغطية (مرجع للمقارنة بعد أي تعديل)."""
        sites = self._ministry_sites()
        self.assertGreaterEqual(len(sites), 15)

    def test_patch_covers_the_known_no_timeout_files(self):
        """الملفات اللي كانت فيها طلبات بلا مهلة — صارت مغطّاة بالرقعة."""
        sites = self._ministry_sites()
        files = {rel for rel, _, _ in sites}
        for expected in ('api.py', 'ui.py', 'first_session.py', 'qt_sessions_page.py'):
            self.assertIn(expected, files)

    def test_runtime_built_ministry_url_is_covered(self):
        """
        documents.py يبني الرابط وقت التشغيل (BASE_URL + ShowImg.php)
        — ما يظهر بالفحص الساكن، فلازم نغطّيه صراحةً.
        """
        import documents
        url = documents.build_doc_link('123/2026', 42)
        self.assertTrue(url.startswith('https://expertapp.moj.gov.kw'))
        self.assertIsNotNone(net_timeouts.timeout_for(url))
        self.assertEqual(net_timeouts.timeout_for(url),
                         net_timeouts.DOCUMENTS_TIMEOUT)


if __name__ == '__main__':
    unittest.main(verbosity=2)
