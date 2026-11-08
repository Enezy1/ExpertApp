# ===== updater.py — التحديث التلقائي للبرنامج عبر مجلد مشترك على الشبكة =====
"""
آلية العمل:
  1. الأدمن يبني نسخة جديدة (build.py) وينسخ ملف EXE يدويًا لمجلد التحديثات
     على الشبكة، ثم من صفحة الإعدادات يحفظ مسار المجلد → يُرفع مع رقم النسخة
     لجدول app_version بـSupabase (publish_app_version).
  2. عند بدء البرنامج (مرة وحدة فقط) يفحص check_for_update() هل النسخة
     المنشورة أحدث من config.APP_VERSION.
  3. لو نعم، try_download_update() ينسخ أحدث EXE من المجلد لمجلد مؤقت —
     ويرجع None بصمت لو المسار غير قابل للوصول (الحالة الطبيعية لجهاز
     بالبيت خارج شبكة الدوام).
  4. apply_update() يستبدل EXE الحالي بالجديد عبر سكربت batch ويعيد التشغيل.

أي فشل (لا إنترنت، لا شبكة، مجلد فاضي...) يُعامَل بصمت — لا يوقف البرنامج.
"""
import os
import sys
import glob
import shutil
import tempfile
import threading
import subprocess
from datetime import datetime, timezone

import requests

import config
from config import SUPABASE_URL, SUPABASE_KEY

_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}


def _parse_version(text):
    "'1.2.3' → (1, 2, 3)؛ أي صيغة غير صالحة ترجع None"
    try:
        parts = tuple(int(p) for p in str(text).strip().split('.'))
        return parts if len(parts) == 3 else None
    except Exception:
        return None


def publish_app_version(folder_path, version=None, timeout=10):
    """
    يرفع مسار مجلد التحديثات + رقم النسخة (version، وإلا APP_VERSION الحالي) للسحابة (upsert على id=1).
    يستدعيها الأدمن فقط من صفحة الإعدادات. يرجّع (نجح: bool, نص خطأ أو None).
    """
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/app_version",
            headers={**_HEADERS, 'Prefer': 'resolution=merge-duplicates'},
            json={
                'id': 1,
                'version': version or config.APP_VERSION,
                'folder_path': folder_path,
                'released_at': datetime.now(timezone.utc).isoformat(),
            },
            timeout=timeout,
        )
        if r.status_code in (200, 201, 204):
            return True, None
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


def _exe_file_version(path):
    """يقرأ رقم النسخة المدمج بخصائص ملف EXE (نافذة Details) دون تشغيله.
    يرجع 'a.b.c' أو None لو الملف بلا معلومات نسخة (EXE قديم)."""
    try:
        import ctypes
        from ctypes import wintypes
        ver = ctypes.windll.version
        ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        ver.GetFileVersionInfoW.restype = wintypes.BOOL
        ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                       ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        ver.VerQueryValueW.restype = wintypes.BOOL
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return None
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
            return None
        info = (wintypes.DWORD * 13).from_address(ptr.value)
        ms, ls = info[4], info[5]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}"
    except Exception:
        return None


def _latest_exe(folder_path):
    exes = glob.glob(os.path.join(folder_path, '*.exe'))
    return max(exes, key=os.path.getmtime) if exes else None


def check_for_update(timeout=5):
    """
    فحص خفيف واحد: هل النسخة الموجودة بمجلد التحديثات أحدث من النسخة الحالية؟
    المسار من السحابة (الأدمن ينشره) وإلا من الإعداد المحلي. رقم النسخة يُقرأ
    من خصائص ملف EXE نفسه — فلا حاجة لتحديث رقم يدويًا. لو EXE قديم بلا رقم
    مدمج، نرجع لرقم السحابة. يرجّع (متوفر: bool, النسخة_الجديدة, folder_path).
    أي خطأ → (False, '', '') بصمت.
    """
    try:
        cloud_ver, folder = '', ''
        try:
            r = requests.get(
                f"{SUPABASE_URL}/rest/v1/app_version",
                headers=_HEADERS,
                params={'id': 'eq.1', 'select': 'version,folder_path'},
                timeout=timeout,
            )
            if r.status_code == 200 and r.json():
                row = r.json()[0]
                cloud_ver = row.get('version') or ''
                folder = row.get('folder_path') or ''
        except Exception as e:
            print(f"check_for_update cloud ERROR: {e}")
        if not folder:
            try:
                from expert_settings import load_update_folder
                folder = load_update_folder() or ''
            except Exception:
                folder = ''
        if not folder:
            return False, '', ''

        new_ver = ''
        if _path_reachable(folder):
            exe = _latest_exe(folder)
            if exe:
                new_ver = _exe_file_version(exe) or ''
        if not new_ver:
            new_ver = cloud_ver
        new_t, cur_t = _parse_version(new_ver), _parse_version(config.APP_VERSION)
        if not new_t or not cur_t:
            return False, '', ''
        return (new_t > cur_t), new_ver, folder
    except Exception as e:
        print(f"check_for_update ERROR: {e}")
        return False, '', ''


def _path_reachable(path, timeout=4):
    "os.path.isdir بمهلة قصيرة — مسارات الشبكة غير المتاحة قد تعلّق عشرات الثواني"
    result = {'ok': False}

    def probe():
        try:
            result['ok'] = os.path.isdir(path)
        except Exception:
            pass

    t = threading.Thread(target=probe, daemon=True)
    t.start()
    t.join(timeout)
    return result['ok'] and not t.is_alive()


def try_download_update(folder_path):
    """
    لو مجلد التحديثات قابل للوصول، ينسخ أحدث ملف .exe فيه لمجلد مؤقت ويرجّع
    مساره المحلي. غير ذلك (لا شبكة / مجلد فاضي / فشل نسخ) → None بصمت.
    """
    try:
        if not folder_path or not _path_reachable(folder_path):
            return None
        exes = glob.glob(os.path.join(folder_path, '*.exe'))
        if not exes:
            return None
        latest = max(exes, key=os.path.getmtime)
        tmp_dir = tempfile.mkdtemp(prefix='ExpertAppUpdate_')
        local = os.path.join(tmp_dir, os.path.basename(latest))
        shutil.copy2(latest, local)
        return local
    except Exception as e:
        print(f"try_download_update ERROR: {e}")
        return None


def apply_update(new_exe_path):
    """
    يكتب سكربت batch مؤقت: ينتظر إغلاق البرنامج، يستبدل EXE الأصلي بالجديد،
    يعيد تشغيله، ثم يحذف نفسه. يشغّله منفصلًا ويُنهي البرنامج الحالي فورًا.
    يعمل فقط من نسخة EXE المبنية (sys.frozen) — من الكود المصدري لا يفعل شي.
    """
    if not getattr(sys, 'frozen', False) or not new_exe_path:
        return False
    current_exe = sys.executable
    bat_path = os.path.join(tempfile.gettempdir(), 'expertapp_update.bat')
    # copy بمحاولات متكررة: EXE الأصلي يظل مقفولًا لحظات بعد إغلاق البرنامج
    script = (
        '@echo off\r\n'
        'ping -n 3 127.0.0.1 >nul\r\n'
        'set tries=0\r\n'
        ':retry\r\n'
        f'copy /Y "{new_exe_path}" "{current_exe}" >nul 2>&1\r\n'
        'if errorlevel 1 (\r\n'
        '  set /a tries+=1\r\n'
        '  if %tries% LSS 15 (\r\n'
        '    ping -n 2 127.0.0.1 >nul\r\n'
        '    goto retry\r\n'
        '  )\r\n'
        ')\r\n'
        f'start "" "{current_exe}"\r\n'
        f'rmdir /S /Q "{os.path.dirname(new_exe_path)}" >nul 2>&1\r\n'
        '(goto) 2>nul & del "%~f0"\r\n'
    )
    with open(bat_path, 'w', encoding='mbcs', errors='replace') as f:
        f.write(script)
    subprocess.Popen(
        ['cmd', '/c', bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )
    os._exit(0)
