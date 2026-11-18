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
import sys
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


# ---------------------------------------------------------------------------
# التحديث «بمكانه» — ما نسخة ثانية أبداً (المبلَّغ 17/11/2026)
# ---------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.abspath(__file__))


class ApplyUpdateTests(unittest.TestCase):
    """
    ⚠️ المشكلة: التحديث كان **ينصّب نسخة ثانية** بمكان ثاني (المثبّت يشتغل
    بدون تحديد مجلد) فيبقى البرنامج القديم شغّالاً والنسخة ما تتغيّر.

    المطلوب: الاستبدال **دائماً** بمكان النسخة الحالية + إعادة التشغيل من
    نفس المسار (اختصارات المستخدم تبقى على النسخة الجديدة).
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='upd_apply_')
        self.exe = os.path.join(self.tmp, 'ExpertApp.exe')
        with open(self.exe, 'wb') as f:
            f.write(b'MZ' + b'\0' * 100)
        self.new_dir = os.path.join(self.tmp, 'downloaded')
        os.makedirs(self.new_dir, exist_ok=True)
        self.new = os.path.join(self.new_dir, 'ExpertApp.exe')
        with open(self.new, 'wb') as f:
            f.write(b'MZ' + b'\1' * 200)
        self.bat = os.path.join(tempfile.gettempdir(), 'expertapp_update.bat')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        import glob
        for d in glob.glob(os.path.join(tempfile.gettempdir(), 'ExpertAppUpdate_Bak_*')):
            shutil.rmtree(d, ignore_errors=True)

    def _apply(self, kind='program'):
        if os.path.exists(self.bat):
            os.remove(self.bat)
        with mock.patch.object(sys, 'frozen', True, create=True), \
             mock.patch.object(sys, 'executable', self.exe), \
             mock.patch.object(up.subprocess, 'Popen') as popen, \
             mock.patch.object(up.os, '_exit') as exit_:
            up.apply_update(self.new, kind)
        script = ''
        if os.path.exists(self.bat):
            with open(self.bat, encoding='ascii', errors='replace') as f:
                script = f.read()
        # البرنامج يخرج فوراً (os._exit) — نسجّل إنه اشتغل فعلاً
        self.assertTrue(exit_.called, 'البرنامج ما خرج — سكربت التحديث ما اشتغل')
        self.assertTrue(popen.called)
        # متغيرات البيئة اللي اتمرّرناها للـbatch (المسارات كلها فيها)
        env = popen.call_args.kwargs.get('env') or {}
        return script, env

    def test_program_replaces_same_file(self):
        script, _env = self._apply('program')
        self.assertIn('copy /Y "%EXPERTAPP_NEW%" "%EXPERTAPP_OLD%"', script)

    def test_restarts_same_path(self):
        """⟵ الاختصارات وقائمة ابدأ تبقى على النسخة الجديدة."""
        script, _env = self._apply('program')
        self.assertIn('start "" "%EXPERTAPP_OLD%"', script)

    def test_no_backup_next_to_program(self):
        """
        ⚠️ النسخة الاحتياطية كانت تنحفظ **جنب البرنامج** (ExpertApp.exe.bak)
        وتبقى للأبد ⟵ كانت هي «النسخة الثانية». الآن: التسمية (.old) المؤقتة
        + تنظيف عند الإقلاع.
        """
        self._apply('program')
        self.assertFalse(os.path.exists(self.exe + '.bak'))

    def test_old_backup_is_cleaned(self):
        """نسخة احتياطية قديمة (من نسخ سابقة) تنحذف بعد التحديث."""
        script, _env = self._apply('program')
        self.assertIn('del /F /Q "%EXPERTAPP_OLD%.bak"', script)

    def test_installer_installs_in_same_folder(self):
        """
        ⚠️ الأساس: المثبّت ينصّب **بنفس مجلد البرنامج** (/DIR) ⟵ يستبدل
        النسخة القديمة بدل ما ينصّب نسخة ثانية بمكان ثاني.
        """
        script, env = self._apply('installer')
        self.assertIn('/DIR="%EXPERTAPP_DIR%"', script)
        self.assertIn('/VERYSILENT', script)
        self.assertEqual(env.get('EXPERTAPP_DIR'), os.path.dirname(self.exe))

    def test_installer_restarts_same_path(self):
        script, _env = self._apply('installer')
        self.assertIn('start "" "%EXPERTAPP_OLD%"', script)

    def test_installer_applied_silently_in_place(self):
        """
        ⚠️ **تثبيت المثبّت من المصدر الداخلي** = نفس سلوك GitHub بالضبط:
        نسخ المثبّت لـ%TEMP% ← تشغيله **بصمت** بنفس المجلد ← إغلاق قسري
        لكل النسخ ← تنظيف النسخة القديمة.
        """
        script, env = self._apply('installer')
        self.assertIn('/VERYSILENT', script)
        self.assertIn('/SUPPRESSMSGBOXES', script)
        self.assertIn('/NORESTART', script)
        self.assertIn('/DIR="%EXPERTAPP_DIR%"', script)
        self.assertIn('taskkill /F /IM "%EXPERTAPP_IMG%"', script)
        self.assertIn('del /F /Q "%EXPERTAPP_OLDBak%"', script)
        self.assertEqual(env.get('EXPERTAPP_INSTALLER'), self.new)

    def test_not_frozen_returns_false(self):
        with mock.patch.object(sys, 'frozen', False, create=True):
            self.assertFalse(up.apply_update(self.new, 'program'))

    def test_empty_path_returns_false(self):
        with mock.patch.object(sys, 'frozen', True, create=True):
            self.assertFalse(up.apply_update('', 'program'))


# ---------------------------------------------------------------------------
# ⚠️ انحدار 18/11/2026 — التحديث ما كان يشتغل أبداً على أي جهاز
# ---------------------------------------------------------------------------

class ArabicPathBatchTests(unittest.TestCase):
    """
    ⚠️ **السبب الأول لفشل التحديث (مقاس)**: سكربت الـbatch كان يُكتب
    بترميز mbcs (cp1252) ⟵ كل حرف عربي في مسار التثبيت صار «؟»:

        C:\\...\\نظام جلسات الخبراء\\ExpertApp.exe
        ⟵ C:\\...\\???? ????? ???????\\ExpertApp.exe   (المسار ما موجود!)

    ⟵ التحديث يفشل 100% على كل جهاز (مجلد التثبيت عربي دائماً).

    الحل: **السكربت ASCII صِرف** والمسارات كلها **بمتغيرات بيئة**
    (Unicode ⟵ cmd يسلّمها سليمة).
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='upd_arabic_')
        self.exe = os.path.join(self.tmp, 'نظام جلسات الخبراء', 'ExpertApp.exe')
        os.makedirs(os.path.dirname(self.exe), exist_ok=True)
        with open(self.exe, 'wb') as f:
            f.write(b'MZ' + b'\0' * 100)
        self.new = os.path.join(self.tmp, 'ExpertApp.exe')
        with open(self.new, 'wb') as f:
            f.write(b'MZ' + b'\1' * 100)
        self.bat = os.path.join(tempfile.gettempdir(), 'expertapp_update.bat')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        if os.path.exists(self.bat):
            os.remove(self.bat)

    def _apply(self):
        with mock.patch.object(sys, 'frozen', True, create=True), \
             mock.patch.object(sys, 'executable', self.exe), \
             mock.patch.object(up.subprocess, 'Popen') as popen, \
             mock.patch.object(up.os, '_exit'):
            up.apply_update(self.new, 'program')
        with open(self.bat, encoding='ascii', errors='replace') as f:
            script = f.read()
        return script, (popen.call_args.kwargs.get('env') or {})

    def test_batch_file_is_pure_ascii(self):
        """السكربت ما يحوي أي حرف عربي/غير-ASCII (ما فيه «؟» بعد الكتابة)."""
        script, _env = self._apply()
        script.encode('ascii')   # يرمي UnicodeEncodeError لو فيه حرف غير ASCII
        self.assertNotIn('?', script)

    def test_arabic_path_passed_through_environment(self):
        """المسار العربي يوصل كامل بمتغير البيئة (Unicode) — مو بالسكربت."""
        script, env = self._apply()
        self.assertEqual(env.get('EXPERTAPP_OLD'), self.exe)
        self.assertIn('نظام جلسات الخبراء', env.get('EXPERTAPP_OLD'))
        self.assertNotIn('نظام جلسات الخبراء', script)

    def test_new_file_passed_through_environment(self):
        _script, env = self._apply()
        self.assertEqual(env.get('EXPERTAPP_NEW'), self.new)

    def test_result_file_written(self):
        """الـbatch يكتب النتيجة ⟵ البرنامج يخبر الخبير إن التحديث نجح/فشل."""
        script, env = self._apply()
        self.assertIn('> "%EXPERTAPP_RES%" echo ok', script)
        self.assertIn('> "%EXPERTAPP_RES%" echo failed', script)
        self.assertTrue(env.get('EXPERTAPP_RES'))


class RunningExeLockTests(unittest.TestCase):
    """
    ⚠️ **السبب الثاني (مقاس)**: ويندوز يرفض الكتابة فوق EXE شغّال:

        «The process cannot access the file ... because it is being
         used by another process»  ⟵ «البرنامج يعمل»

    ونسخة onefile (PyInstaller) فيها عملية أب تحتجز الملف بعد ما يخرج
    البرنامج ⟵ محاولات النسخ كلها تفشل.

    الحل: **التسمية أولاً** (ويندوز يسمح بتسمية ملف شغّال) ⟵ يفكّ القفل
    وبعدها ننسخ الجديدة بالمكان.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='upd_lock_')
        self.exe = os.path.join(self.tmp, 'ExpertApp.exe')
        with open(self.exe, 'wb') as f:
            f.write(b'MZ' + b'\0' * 100)
        self.new = os.path.join(self.tmp, 'downloaded', 'ExpertApp.exe')
        os.makedirs(os.path.dirname(self.new), exist_ok=True)
        with open(self.new, 'wb') as f:
            f.write(b'MZ' + b'\1' * 100)
        self.bat = os.path.join(tempfile.gettempdir(), 'expertapp_update.bat')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        if os.path.exists(self.bat):
            os.remove(self.bat)

    def _apply(self):
        with mock.patch.object(sys, 'frozen', True, create=True), \
             mock.patch.object(sys, 'executable', self.exe), \
             mock.patch.object(up.subprocess, 'Popen') as popen, \
             mock.patch.object(up.os, '_exit'):
            up.apply_update(self.new, 'program')
        with open(self.bat, encoding='ascii', errors='replace') as f:
            script = f.read()
        return script, (popen.call_args.kwargs.get('env') or {})

    def test_rename_happens_before_copy(self):
        """التسمية تسبق النسخ (هي اللي تفكّ قفل الملف)."""
        script, _env = self._apply()
        self.assertIn('move /Y "%EXPERTAPP_OLD%" "%EXPERTAPP_OLDBak%"', script)
        self.assertLess(script.index('move /Y "%EXPERTAPP_OLD%"'),
                        script.index('copy /Y "%EXPERTAPP_NEW%"'))

    def test_old_file_removed_after_success(self):
        """النسخة القديمة (.old) تنحذف بعد ما يخرج البرنامج القديم."""
        script, _env = self._apply()
        self.assertIn('del /F /Q "%EXPERTAPP_OLDBak%"', script)

    def test_fallback_restores_old_file(self):
        """لو فشل النسخ ⟵ ترجع النسخة القديمة لمكانها."""
        script, _env = self._apply()
        self.assertIn('move /Y "%EXPERTAPP_OLDBak%" "%EXPERTAPP_OLD%"', script)

    def test_all_instances_force_closed_before_replace(self):
        """
        ⚠️ **إغلاق قسري لكل النسخ** قبل الاستبدال:
          - نسخة PyInstaller (onefile) فيها عملية أب (bootstrap) تحتجز ملف EXE
            بعد ما يخرج البرنامج ⟵ وتخلي الاستبدال يفشل.
          - وأي نسخة ثانية مفتوحة (المستخدم فتح البرنامج مرتين) كمان تحتجزه.
        ⟵ السكربت يسكّر كل النسخ (taskkill) قبل التسمية.
        """
        script, env = self._apply()
        self.assertIn('taskkill /F /IM "%EXPERTAPP_IMG%"', script)
        self.assertEqual(env.get('EXPERTAPP_IMG'), 'ExpertApp.exe')
        self.assertLess(script.index('taskkill'),
                        script.index('move /Y "%EXPERTAPP_OLD%"'))


class InternalSourceTests(unittest.TestCase):
    """
    ⚠️ **المصدر الداخلي (مجلد الشبكة) — يستخدم المثبّت** (طلب العنزي 18/11/2026):
      - الأجهزة تسحب من مجلد الأدمن على **شبكة الدوام** مباشرة (أسرع،
        وما تستهلك إنترنت الدوام ولا GitHub).
      - الملف = **المثبّت** (`*Setup*.exe` / `*تثبيت*.exe`) — **ما نتجاهله** anymore.
      - رقم النسخة من `FileVersion`/`ProductVersion` أو من **اسم الملف**.
      - التثبيت = نسخ المثبّت لـ%TEMP% + تشغيله بصمت — **نفس** مسار GitHub.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='upd_int_')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_installer_preferred_over_portable_program(self):
        """المثبّت له الأولوية على النسخة المحمولة."""
        _mk_exe(self.dir, 'ExpertApp.exe')
        setup = _mk_exe(self.dir, 'ExpertApp-Setup-1.2.15.exe')
        picked = up._pick_source_exe(self.dir)
        self.assertEqual(picked, setup)

    def test_arabic_installer_name_is_picked(self):
        """`تثبيت_نظام_جلسات_الخبراء.exe` — مثبّت معروف (بدون رقم بالاسم)."""
        _mk_exe(self.dir, 'ExpertApp.exe')
        setup = _mk_exe(self.dir, 'تثبيت_نظام_جلسات_الخبراء.exe')
        picked = up._pick_source_exe(self.dir)
        self.assertEqual(picked, setup)
        self.assertEqual(up._source_kind(picked), 'installer')

    def test_newest_installer_wins(self):
        """الأحدث زمنياً = الأحدث إصداراً."""
        old = _mk_exe(self.dir, 'ExpertApp-Setup-1.2.14.exe')
        os.utime(old, (1000000, 1000000))
        new = _mk_exe(self.dir, 'ExpertApp-Setup-1.2.15.exe')
        os.utime(new, (2000000, 2000000))
        self.assertEqual(up._pick_source_exe(self.dir), new)

    def test_falls_back_to_portable_program(self):
        """لو ما فيه مثبّت ⟵ النسخة المحمولة (احتياط)."""
        prog = _mk_exe(self.dir, 'ExpertApp.exe')
        self.assertEqual(up._pick_source_exe(self.dir), prog)
        self.assertEqual(up._source_kind(prog), 'program')

    def test_version_read_from_file_name(self):
        """لو الملف ما عنده خصائص ⟵ الرقم من اسمه."""
        f = _mk_exe(self.dir, 'ExpertApp-Setup-1.2.15.exe')
        self.assertEqual(up._exe_version_or_name(f), '1.2.15')

    def test_version_from_properties_wins_over_name(self):
        """لو فيه خصائص ⟵ هي الأصح (الاسم ممكن يكون قديم)."""
        f = _mk_exe(self.dir, 'ExpertApp-Setup-9.9.9.exe')
        with mock.patch.object(up, '_exe_file_version', return_value='1.2.15'):
            self.assertEqual(up._exe_version_or_name(f), '1.2.15')

    def test_zero_version_is_not_taken(self):
        """`0.0.0` (حالة المثبّت Inno) ⟵ ما ينحسب نسخة ⟵ ننزل للاسم/المنتج."""
        f = _mk_exe(self.dir, 'ExpertApp-Setup-1.2.15.exe')
        with mock.patch.object(up, '_exe_file_version', return_value='0.0.0'), \
             mock.patch.object(up, '_exe_string_version', return_value=''):
            self.assertEqual(up._exe_version_or_name(f), '1.2.15')

    def test_source_version_uses_installer(self):
        """`_source_version` للمصدر الداخلي يقرأ من المثبّت."""
        _mk_exe(self.dir, 'ExpertApp-Setup-1.2.16.exe')
        src = {'kind': 'internal', 'loc': self.dir, 'version': ''}
        with mock.patch.object(up, '_path_reachable', return_value=True):
            self.assertEqual(up._source_version(src), '1.2.16')

    def test_detect_version_prefers_installer(self):
        """رقم النسخة المنشور (من الإعدادات) يقرأ من المثبّت."""
        _mk_exe(self.dir, 'ExpertApp-Setup-1.2.17.exe')
        with mock.patch.object(up, '_path_reachable', return_value=True):
            self.assertEqual(up.detect_version(self.dir), '1.2.17')

    def test_internal_download_returns_installer_kind(self):
        """التنزيل من المصدر الداخلي ⟵ النوع 'installer' (مش 'program')."""
        with mock.patch.object(up, '_copy_from_folder',
                               return_value=r'C:\tmp\ExpertApp-Setup-1.2.15.exe'):
            path, kind, src = up.download_update(
                [{'kind': 'internal', 'loc': r'\\srv\Updates', 'version': ''}])
        self.assertEqual(kind, 'installer')

    def test_internal_download_program_kind_when_no_installer(self):
        """لو كان الملف المحمول ⟵ النوع 'program'."""
        with mock.patch.object(up, '_copy_from_folder',
                               return_value=r'C:\tmp\ExpertApp.exe'):
            path, kind, src = up.download_update(
                [{'kind': 'internal', 'loc': r'\\srv\Updates', 'version': ''}])
        self.assertEqual(kind, 'program')


class UpdateResultTests(unittest.TestCase):
    """نتيجة آخر تحديث — يقرأها البرنامج عند الإقلاع (مرة وحدة)."""

    def setUp(self):
        self.path = up.update_result_file()

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_reads_and_clears(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('failed\n')
        self.assertEqual(up.read_update_result(), 'failed')
        self.assertFalse(os.path.exists(self.path), 'الملف ما انحذف — بيطلع تنبيه كل إقلاع')

    def test_missing_file_returns_empty(self):
        self.assertEqual(up.read_update_result(), '')

    def test_cleanup_removes_stale_copies(self):
        """بقايا النسخ القديمة (نسخة ثانية) تنحذف عند الإقلاع."""
        tmp = tempfile.mkdtemp(prefix='upd_stale_')
        try:
            exe = os.path.join(tmp, 'ExpertApp.exe')
            with open(exe, 'wb') as f:
                f.write(b'MZ')
            for name in ('ExpertApp.exe' + up.OLD_SUFFIX, 'ExpertApp.exe.bak'):
                with open(os.path.join(tmp, name), 'wb') as f:
                    f.write(b'x')
            with mock.patch.object(sys, 'frozen', True, create=True), \
                 mock.patch.object(sys, 'executable', exe):
                up.cleanup_stale_update_files()
            self.assertFalse(os.path.exists(os.path.join(tmp, 'ExpertApp.exe' + up.OLD_SUFFIX)))
            self.assertFalse(os.path.exists(os.path.join(tmp, 'ExpertApp.exe.bak')))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class DetectVersionTests(unittest.TestCase):
    """رقم النسخة يُقرأ **تلقائياً** من ملف النسخة بالمجلد."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='upd_ver_')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_reads_version_from_exe(self):
        _mk_exe(self.dir, 'ExpertApp.exe')
        with mock.patch.object(up, '_exe_file_version', return_value='1.2.13'):
            self.assertEqual(up.detect_version(self.dir), '1.2.13')

    def test_empty_without_exe(self):
        self.assertEqual(up.detect_version(self.dir), '')

    def test_empty_for_unreachable_folder(self):
        with mock.patch.object(up, '_path_reachable', return_value=False):
            self.assertEqual(up.detect_version(r'\\srv\Updates'), '')


class PublishVersionTests(unittest.TestCase):
    """رقم النسخة المنشور = المقروء تلقائياً (اليدوي احتياط فقط)."""

    def _post_body(self, **kwargs):
        with mock.patch.object(up, 'detect_version', **kwargs), \
             mock.patch.object(up.requests, 'post') as post:
            post.return_value.status_code = 200
            post.return_value.text = ''
            ok, err = up.publish_app_version(r'\\srv\Updates', '1.0.0')
        self.assertTrue(ok, err)
        return post.call_args_list[0].kwargs['json']

    def test_detected_version_wins(self):
        body = self._post_body(return_value='1.2.13')
        self.assertEqual(body['version'], '1.2.13')

    def test_manual_used_when_detection_fails(self):
        body = self._post_body(return_value='')
        self.assertEqual(body['version'], '1.0.0')


class OneClickUpdateFlowTests(unittest.TestCase):
    """ضغطة وحدة: تحميل صامت ⟵ استبدال ⟵ إعادة تشغيل."""

    def test_download_triggers_apply_immediately(self):
        with open(os.path.join(ROOT, 'main.py'), encoding='utf-8') as f:
            src = f.read()
        start = src.index('def _on_update_downloaded')
        block = src[start:start + 1500]
        end = block.find('\ndef ')
        if end > 0:
            block = block[:end]
        self.assertIn('apply_update', block)
        self.assertIn('set_update_installing', block)


class DownloadIntegrityTests(unittest.TestCase):
    """
    ⚠️ ملف ناقص = نسخة مكسورة — ما يستبدل بها البرنامج الحالي (التحديث صامت).
    """

    class _Resp:
        def __init__(self, total, chunks):
            self.headers = {'Content-Length': str(total)}
            self._chunks = chunks

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=1):
            for c in self._chunks:
                yield c

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def test_truncated_download_fails(self):
        resp = self._Resp(1000, [b'x' * 100])
        with mock.patch.object(up.requests, 'get', return_value=resp):
            path = up._download_file('https://x/app.exe')
        self.assertEqual(path, '')

    def test_complete_download_kept(self):
        resp = self._Resp(10, [b'x' * 10])
        with mock.patch.object(up.requests, 'get', return_value=resp):
            path = up._download_file('https://x/app.exe')
        self.assertTrue(path)
        self.assertEqual(os.path.getsize(path), 10)


if __name__ == '__main__':
    unittest.main()
