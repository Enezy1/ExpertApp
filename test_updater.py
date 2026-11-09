# ===== test_updater.py — اختبارات التحديث (مصدران: داخلي ثم أونلاين) =====
"""
المشكلة اللي يعالجها هذا الملف (9/11/2026):
  - السحابة كانت تنشر رابط GitHub بحقل «مسار مجلد التحديثات» — والكود القديم
    كان يتعامل مع المسار كأنه مجلد محلي (os.path.isdir) ⇒ فشل التحميل
    برسالة «ما قدرت أوصل لمجلد التحديث على الشبكة».
  - وكان يختار «أحدث .exe» بالزمن ⇒ ممكن يختار المثبّت ويحلّ محل البرنامج
    (والبرنامج بعدها ما يحمل).
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import updater as up


def _mk_exe(folder, name, size=1024):
    path = os.path.join(folder, name)
    with open(path, 'wb') as f:
        f.write(b'MZ' + b'\0' * (size - 2))
    return path


class SourceOrderTests(unittest.TestCase):
    """الترتيب: المصدر الداخلي أول، وبعده الأونلاين."""

    def test_internal_comes_before_online(self):
        with mock.patch.object(up, '_cloud_row', return_value={}), \
             mock.patch.object(up, '_cloud_version', return_value=''), \
             mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch('expert_settings.load_update_folder', return_value=r'\\srv\Updates'), \
                 mock.patch('expert_settings.load_update_online_url', return_value='https://example.com/x.exe'):
                sources = up._configured_sources()
        kinds = [s['kind'] for s in sources]
        self.assertIn('internal', kinds)
        self.assertIn('online', kinds)
        self.assertLess(kinds.index('internal'), kinds.index('online'))

    def test_url_stored_in_folder_field_is_treated_as_online(self):
        """الرابط المحفوظ بالمكان الغلط = مصدر أونلاين (مو مجلد)."""
        url = 'https://github.com/Enezy1/ExpertApp/releases/latest/download/ExpertApp-Setup-1.2.8.exe'
        with mock.patch.object(up, '_cloud_row', return_value={'folder_path': url}), \
             mock.patch('expert_settings.load_update_folder', return_value=''), \
             mock.patch('expert_settings.load_update_online_url', return_value=''):
            sources = up._configured_sources()
        match = [s for s in sources if s['loc'] == url]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]['kind'], 'online')

    def test_default_online_source_always_present(self):
        with mock.patch.object(up, '_cloud_row', return_value={}), \
             mock.patch('expert_settings.load_update_folder', return_value=''), \
             mock.patch('expert_settings.load_update_online_url', return_value=''):
            sources = up._configured_sources()
        self.assertTrue(any(s['kind'] == 'online' for s in sources))

    def test_provider_row_is_never_read(self):
        """⚠️ الصف 2 = مزوّدات الذكاء الاصطناعي (فيه مفاتيح) — ما نلمسه."""
        self.assertNotEqual(up.ONLINE_ROW_ID, 2)
        self.assertNotEqual(up.UPDATE_ROW_ID, 2)
        seen = []

        def fake_row(row_id, timeout=8):
            seen.append(row_id)
            if row_id == 2:
                return {'version': 'ai_providers',
                        'folder_path': '[{"name":"ocrspace","api_key":"K123"}]'}
            return {}

        with mock.patch.object(up, '_cloud_row', side_effect=fake_row), \
             mock.patch('expert_settings.load_update_folder', return_value=''), \
             mock.patch('expert_settings.load_update_online_url', return_value=''):
            sources = up._configured_sources()
        self.assertNotIn(2, seen)
        for s in sources:
            self.assertNotIn('ocrspace', s['loc'])

    def test_row_with_non_version_mark_is_ignored(self):
        """صف ما رقم نسخته مو 'a.b.c' (مثل ai_providers) → نتجاهله."""
        with mock.patch.object(up, '_cloud_row',
                               return_value={'version': 'ai_providers',
                                             'folder_path': 'x'}), \
             mock.patch('expert_settings.load_update_folder', return_value=''), \
             mock.patch('expert_settings.load_update_online_url', return_value=''):
            sources = up._configured_sources()
        self.assertFalse(any(s['loc'] == 'x' for s in sources))


class ProgramExePickTests(unittest.TestCase):
    """اختيار نسخة البرنامج من المجلد — **ما نختار المثبّت أبداً**."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='upd_test_')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_installer_is_never_picked(self):
        _mk_exe(self.dir, 'ExpertApp.exe')
        _mk_exe(self.dir, 'تثبيت_نظام_جلسات_الخبراء.exe')
        _mk_exe(self.dir, 'ExpertApp-Setup-1.2.9.exe')
        picked = up._pick_program_exe(self.dir)
        self.assertIsNotNone(picked)
        self.assertEqual(os.path.basename(picked), 'ExpertApp.exe')

    def test_program_preferred_even_if_older_than_installer(self):
        prog = _mk_exe(self.dir, 'ExpertApp.exe')
        old = os.path.getmtime(prog)
        inst = _mk_exe(self.dir, 'ExpertApp-Setup-9.9.9.exe')
        os.utime(inst, (old + 500, old + 500))
        picked = up._pick_program_exe(self.dir)
        self.assertEqual(os.path.basename(picked), 'ExpertApp.exe')

    def test_no_program_returns_none(self):
        _mk_exe(self.dir, 'ExpertApp-Setup-1.2.9.exe')
        self.assertIsNone(up._pick_program_exe(self.dir))

    def test_empty_folder_returns_none(self):
        self.assertIsNone(up._pick_program_exe(self.dir))


class OnlineAssetTests(unittest.TestCase):
    """اختيار أصل التحديث من آخر إصدار على GitHub."""

    def test_program_asset_preferred_over_installer(self):
        rel = {'version': '1.2.9', 'assets': [
            {'name': 'ExpertApp-Setup-1.2.9.exe', 'url': 'https://x/setup.exe'},
            {'name': 'ExpertApp.exe', 'url': 'https://x/app.exe'},
        ]}
        name, url, kind = up._pick_online_asset(rel)
        self.assertEqual(kind, 'program')
        self.assertEqual(name, 'ExpertApp.exe')

    def test_installer_used_when_no_program_asset(self):
        rel = {'version': '1.2.9', 'assets': [
            {'name': 'ExpertApp-Setup-1.2.9.exe', 'url': 'https://x/setup.exe'},
        ]}
        name, url, kind = up._pick_online_asset(rel)
        self.assertEqual(kind, 'installer')

    def test_no_exe_assets(self):
        rel = {'version': '1.2.9', 'assets': [{'name': 'notes.txt', 'url': 'https://x/n.txt'}]}
        self.assertEqual(up._pick_online_asset(rel), ('', '', ''))

    def test_installer_name_detection(self):
        self.assertTrue(up._is_installer_name('ExpertApp-Setup-1.2.9.exe'))
        self.assertTrue(up._is_installer_name('تثبيت_نظام_جلسات_الخبراء.exe'))
        self.assertFalse(up._is_installer_name('ExpertApp.exe'))


class DownloadFallbackTests(unittest.TestCase):
    """التنزيل: الداخلي أول، وإذا تعذّر → الأونلاين."""

    def _sources(self):
        return [
            {'kind': 'internal', 'loc': r'\\srv\Updates', 'version': ''},
            {'kind': 'online', 'loc': 'https://example.com/app.exe', 'version': ''},
        ]

    def test_internal_used_first(self):
        with mock.patch.object(up, '_copy_from_folder', return_value=r'C:\tmp\ExpertApp.exe') as cp, \
             mock.patch.object(up, '_download_online', return_value=('', '')) as dl:
            path, kind, src = up.download_update(self._sources())
        self.assertEqual(path, r'C:\tmp\ExpertApp.exe')
        self.assertEqual(kind, 'program')
        self.assertEqual(src['kind'], 'internal')
        self.assertTrue(cp.called)
        self.assertFalse(dl.called)

    def test_online_used_when_internal_unavailable(self):
        with mock.patch.object(up, '_copy_from_folder', return_value='') as cp, \
             mock.patch.object(up, '_download_online',
                               return_value=(r'C:\tmp\app.exe', 'program')) as dl:
            path, kind, src = up.download_update(self._sources())
        self.assertEqual(path, r'C:\tmp\app.exe')
        self.assertEqual(kind, 'program')
        self.assertEqual(src['kind'], 'online')
        self.assertTrue(cp.called)
        self.assertTrue(dl.called)

    def test_all_fail_returns_empty(self):
        with mock.patch.object(up, '_copy_from_folder', return_value=''), \
             mock.patch.object(up, '_download_online', return_value=('', '')):
            path, kind, src = up.download_update(self._sources())
        self.assertEqual(path, '')
        self.assertEqual(kind, '')
        self.assertIsNone(src)


class VersionTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(up._parse_version('1.2.8'), (1, 2, 8))
        self.assertIsNone(up._parse_version('1.2'))
        self.assertIsNone(up._parse_version('x'))

    def test_newer_version_detected(self):
        self.assertGreater(up._parse_version('1.2.9'), up._parse_version('1.2.8'))
        self.assertFalse(up._parse_version('1.2.8') > up._parse_version('1.2.8'))


if __name__ == '__main__':
    unittest.main()
