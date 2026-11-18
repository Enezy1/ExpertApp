# ===== updater.py — التحديث التلقائي للبرنامج (مصدران: داخلي ثم أونلاين) =====
"""
آلية العمل (بعد إصلاح 9/11/2026):
  1. عند بدء البرنامج (مرة وحدة فقط) يفحص check_for_update() هل فيه نسخة
     أحدث من config.APP_VERSION — بمصدرين بالترتيب:
       (أ) داخلي: مجلد على شبكة الدوام (ينسخ فيه الأدمن ملف EXE الجديد)
       (ب) أونلاين: آخر إصدار منشور على GitHub (لو الشبكة الداخلية مو متاحة)
  2. بعد موافقة المستخدم، download_update() ينزّل النسخة بالترتيب نفسه:
       - من المجلد الداخلي: ينسخ **نسخة البرنامج المحمولة** (لا المثبّت)
       - من الأونلاين: ينزّل أصل الإصدار — نسخة البرنامج أول، وإلا المثبّت
  3. apply_update():
       - 'program'   → يستبدل EXE الحالي (مع نسخة احتياطية .bak) ويعيد التشغيل
       - 'installer' → يشغّل المثبّت ويتركه يحدّث (ما يستبدل البرنامج بمثبّت!)

⚠️ سبب هذا الإصلاح: الكود القديم كان يتعامل مع مسار المصدر كأنه **مجلد
محلي** (os.path.isdir) — فلما حُفظ رابط GitHub بالمكان ذاك فشل التحميل
برسالة «ما قدرت أوصل لمجلد التحديث على الشبكة». وكان يختار «أحدث .exe»
بالزمن — فممكن يختار **المثبّت** ويحلّ محل البرنامج (والبرنامج بعدها ما
يحمل). واليوم: المصدر الداخلي يُجرّب أول، وبعده الأونلاين.

أي فشل (لا إنترنت، لا شبكة، مجلد فاضي...) يُعامَل بصمت — لا يوقف البرنامج.
"""
import os
import sys
import glob
import shutil
import tempfile
import threading
import subprocess
import re
from datetime import datetime, timezone

import requests

import config
from config import SUPABASE_URL, SUPABASE_KEY

# اسم جدول التحديث بالسحابة — من config لو معرّف (لتوافق أي نسخة ثانية)،
# وإلا الاسم الافتراضي (نفسه الذي كان مستخدم قبل).
_APP_VERSION_TABLE = getattr(config, 'APP_VERSION_TABLE', 'app_version')

_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}

# ---------- مصادر التحديث ----------
# 1) الأونلاين: مستودع GitHub — آخر إصدار (يتحلّ لملفات الإصدار عبر API).
GITHUB_REPO = 'Enezy1/ExpertApp'
GITHUB_LATEST_API = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'
GITHUB_RELEASES_PAGE = f'https://github.com/{GITHUB_REPO}/releases/latest'
# 2) اسم ثابت لنسخة البرنامج المحمولة (ينشره مهارة الإصدار مع كل نسخة).
ONLINE_PROGRAM_ASSET = 'ExpertApp.exe'
ONLINE_PROGRAM_URL = f'https://github.com/{GITHUB_REPO}/releases/latest/download/{ONLINE_PROGRAM_ASSET}'

# اسم نسخة البرنامج المحمولة (اللي بينسخه الأدمن لمجلد الشبكة).
PROGRAM_EXE_NAMES = ('expertapp.exe',)
# أي اسم فيه هذه الكلمات = مثبّت (Setup/Installer/تثبيت) — ما يستبدل به البرنامج.
INSTALLER_HINTS = ('setup', 'install', 'installer', 'تثبيت')


def _parse_version(text):
    "'1.2.3' → (1, 2, 3)؛ أي صيغة غير صالحة ترجع None"
    try:
        parts = tuple(int(p) for p in str(text).strip().split('.'))
        return parts if len(parts) == 3 else None
    except Exception:
        return None


def _is_url(path):
    return str(path or '').strip().lower().startswith(('http://', 'https://'))


def _looks_like_version(value):
    """هل القيمة رقم نسخة (أو فاضية)؟ — يحمي من صفوق جدول app_version
    المستعملة لشيء ثاني (مثل 'ai_providers')."""
    v = str(value or '').strip()
    if not v:
        return True
    return _parse_version(v) is not None


def _is_installer_name(name):
    """اسم الملف يدل على مثبّت؟ (Setup / Installer / تثبيت)"""
    low = str(name or '').lower()
    return any(h in low for h in INSTALLER_HINTS)


def _filename_from_url(url, fallback='ExpertApp.exe'):
    """اسم الملف من آخر جزء بالرابط (بدون استعلامات)."""
    try:
        part = str(url or '').split('?')[0].rstrip('/').split('/')[-1]
        return part or fallback
    except Exception:
        return fallback


# ---------- السحابة (Supabase) ----------
#
# ⚠️ جدول app_version **مشترك** بين أكثر من ميزة — انتبه للصفوف:
#   - id=1 → هذا التحديث (رقم النسخة + مسار المصدر الداخلي)
#   - id=2 → مزوّدات الذكاء الاصطناعي (provider_sync.py) — **ما نلمسه أبداً**
#   - id=3 → رابط التحديث الأونلاين (هذا الملف)
UPDATE_ROW_ID = 1
ONLINE_ROW_ID = 3


def publish_app_version(folder_path, version=None, online_url=None, timeout=10):
    """
    ينشر مصدرَي التحديث لكل الأجهزة:
      - الصف 1 (id=1): مسار المجلد الداخلي على الشبكة (أو رابط، للقبول).
      - الصف 3 (id=3): رابط التحديث الأونلاين.
    رقم النسخة (version) يُرفع بالصف 1 (وبالصف 3 لو موجود).

    ⚠️ رقم النسخة **تلقائي**: يُقرأ من ملف النسخة نفسه بمجلد التحديثات
    (خصائص EXE) — هذا هو الرقم الصح. الرقم اليدوي (لو انكتب) يُستعمل بس
    إذا تعذّرت القراءة التلقائية.
    ⚠️ الصف 2 مخصّص لمزوّدات الذكاء الاصطناعي (provider_sync) — ما نكتب فيه.
    يستدعيها الأدمن فقط من صفحة الإعدادات. يرجّع (نجح: bool, نص خطأ أو None).
    """
    folder_path = (folder_path or '').strip()
    online_url = (online_url or '').strip()
    manual = (version or '').strip()
    detected = detect_version(folder_path)
    version = detected or manual or config.APP_VERSION
    try:
        # الصف 1 — المصدر الداخلي + رقم النسخة
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/{_APP_VERSION_TABLE}",
            headers={**_HEADERS, 'Prefer': 'resolution=merge-duplicates'},
            json={
                'id': UPDATE_ROW_ID,
                'version': version,
                'folder_path': folder_path,
                'released_at': datetime.now(timezone.utc).isoformat(),
            },
            timeout=timeout,
        )
        if r.status_code not in (200, 201, 204):
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        # الصف 3 — المصدر الأونلاين (اختياري)
        if online_url:
            r2 = requests.post(
                f"{SUPABASE_URL}/rest/v1/{_APP_VERSION_TABLE}",
                headers={**_HEADERS, 'Prefer': 'resolution=merge-duplicates'},
                json={
                    'id': ONLINE_ROW_ID,
                    'version': version,
                    'folder_path': online_url,
                    'released_at': datetime.now(timezone.utc).isoformat(),
                },
                timeout=timeout,
            )
            if r2.status_code not in (200, 201, 204):
                return False, f"HTTP {r2.status_code}: {r2.text[:200]}"
        return True, None
    except Exception as e:
        return False, str(e)


def _cloud_row(row_id, timeout=8):
    """صف واحد من جدول app_version ('' لو ما وصل أو ما فيه)."""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{_APP_VERSION_TABLE}",
            headers=_HEADERS,
            params={'id': f'eq.{row_id}', 'select': 'version,folder_path'},
            timeout=timeout,
        )
        if r.status_code == 200 and r.json():
            return r.json()[0] or {}
    except Exception as e:
        print(f"_cloud_row({row_id}) ERROR: {e}")
    return {}


def _cloud_version(timeout=8):
    """رقم النسخة المنشور في السحابة (الصف 1) — '' لو ما وصل."""
    row = _cloud_row(UPDATE_ROW_ID, timeout)
    return (row.get('version') or '').strip()


# ---------- تحديد المصادر ----------

def _configured_sources():
    """
    قائمة المصادر بالترتيب المفضل: **داخلي (مجلد الشبكة) أول، وبعده أونلاين**.

    - داخلي: مجلد على شبكة الدوام — من السحابة (الصف 1) أو من إعدادات جهاز
      الأدمن. (لو المسار رابط، يُعامل كمصدر أونلاين — صار شغلاً قديماً.)
    - أونلاين: رابط الأدمن (السحابة الصف 3 / الإعدادات المحلية) ← بعده
      آخر إصدار على GitHub (يتحلّ لملفات الإصدار عبر API) ← بعده رابط
      نسخة البرنامج بالاسم الثابت ← وأخيراً أي رابط قديم محفوظ.
    - الأونلاين الافتراضي (GitHub) موجود دائماً — حتى لو ما نشر الأدمن شي.
    """
    internal, online, legacy_online = [], [], []

    def push(bucket, loc):
        loc = (loc or '').strip()
        if loc and loc not in bucket:
            bucket.append(loc)

    # السحابة — الصف 1 (الداخلي) والصف 3 (الأونلاين)
    # ⚠️ ما نقرأ الصف 2 (مزوّدات الذكاء الاصطناعي) أبداً.
    # وحارس إضافي: صف ما رقم نسخته مو شكل نسخة (مثل 'ai_providers') → نتجاهله.
    row1 = _cloud_row(UPDATE_ROW_ID)
    if _looks_like_version(row1.get('version')):
        loc = (row1.get('folder_path') or '').strip()
        if _is_url(loc):
            push(legacy_online, loc)      # رابط محفوظ بحقل المجلد (خطأ قديم)
        else:
            push(internal, loc)
    row3 = _cloud_row(ONLINE_ROW_ID)
    if _looks_like_version(row3.get('version')):
        push(online, row3.get('folder_path'))

    # الإعدادات المحلية (جهاز الأدمن)
    try:
        from expert_settings import load_update_folder, load_update_online_url
        local_folder = (load_update_folder() or '').strip()
        if _is_url(local_folder):
            push(legacy_online, local_folder)
        else:
            push(internal, local_folder)
        push(online, load_update_online_url())
    except Exception:
        pass

    # الأونلاين: رابط الأدمن ← آخر إصدار (API) ← نسخة البرنامج بالاسم الثابت
    ordered_online = list(online)
    for loc in (GITHUB_RELEASES_PAGE, ONLINE_PROGRAM_URL):
        if loc not in ordered_online:
            ordered_online.append(loc)
    for loc in legacy_online:
        if loc not in ordered_online:
            ordered_online.append(loc)

    sources = [{'kind': 'internal', 'loc': loc, 'version': ''} for loc in internal]
    sources += [{'kind': 'online', 'loc': loc, 'version': ''} for loc in ordered_online]
    return sources


# ---------- قراءة الأرقام من الملفات ----------

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


def _pick_program_exe(folder_path):
    """
    يختار **نسخة البرنامج المحمولة** من مجلد الشبكة.
    ⚠️ ما يختار المثبّتات (Setup/Installer/تثبيت) أبداً — لأن استبدال
    البرنامج بمثبّت يجعله ما يحمل.
    الأفضلية لاسم البرنامج بالضبط (ExpertApp.exe)، وإلا الأحدث زمنياً
    من الباقي (بعد استبعاد المثبّتات).
    """
    try:
        exes = glob.glob(os.path.join(folder_path, '*.exe'))
    except Exception:
        return None
    if not exes:
        return None
    programs = [e for e in exes if not _is_installer_name(os.path.basename(e))]
    if not programs:
        return None
    exact = [e for e in programs
             if os.path.basename(e).lower() in PROGRAM_EXE_NAMES]
    pool = exact or programs
    try:
        return max(pool, key=os.path.getmtime)
    except Exception:
        return pool[0]


def _latest_exe(folder_path):
    """أحدث .exe بالمجلد (للتوافق مع الكود القديم) — يفضّل نسخة البرنامج."""
    return _pick_program_exe(folder_path)


def detect_version(folder_path, timeout=4):
    """
    رقم نسخة البرنامج الموجود بمجلد التحديثات — **تلقائي** (من خصائص ملف
    EXE، بدون تشغيله). يرجع '' لو ما قدرنا نعرفه.

    ⚠️ ليش مهم: رقم النسخة كان **يُكتب يدوياً** من الأدمن ⟵ أي خطأ (أو
    نسى) يخلّي الأجهزة ما تعرف إن فيه نسخة جديدة. الحين الرقم يقرأ من
    ملف النسخة نفسه — تلقائي ومطابق دائماً.
    ⚠️ timeout: مهلة فحص الوصول للمجلد (شبكة الدوام ممكن تتأخر) — خلّها
    قصيرة لما يناديها من الواجهة.
    """
    try:
        if not folder_path or not _path_reachable(folder_path, timeout):
            return ''
        exe = _pick_program_exe(folder_path)
        if not exe:
            return ''
        return _exe_file_version(exe) or ''
    except Exception as e:
        print(f"detect_version ERROR: {e}")
        return ''


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


# ---------- الأونلاين (GitHub) ----------

def _github_latest_release(timeout=8):
    """
    آخر إصدار منشور على GitHub: {version, assets:[{name,url}], page}.
    يرجع None لو ما وصل (إنترنت مقطوع / حدّ المعدّل).
    """
    try:
        r = requests.get(
            GITHUB_LATEST_API,
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'ExpertApp-Updater'},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        data = r.json() or {}
        assets = []
        for a in (data.get('assets') or []):
            url = a.get('browser_download_url') or ''
            if not url:
                continue
            assets.append({'name': a.get('name') or _filename_from_url(url), 'url': url})
        return {
            'version': (data.get('tag_name') or '').lstrip('v').strip(),
            'assets': assets,
            'page': data.get('html_url') or GITHUB_RELEASES_PAGE,
        }
    except Exception as e:
        print(f"_github_latest_release ERROR: {e}")
        return None


def _pick_online_asset(release):
    """
    يختار ملف التحديث من آخر إصدار: **نسخة البرنامج أول**، وإلا المثبّت.
    يرجّع (اسم, رابط, نوع) — النوع 'program' أو 'installer' أو ''.
    """
    assets = (release or {}).get('assets') or []
    exes = [a for a in assets if str(a.get('name') or '').lower().endswith('.exe')]
    programs = [a for a in exes if not _is_installer_name(a.get('name'))]
    installers = [a for a in exes if _is_installer_name(a.get('name'))]
    if programs:
        a = programs[0]
        return a.get('name'), a.get('url'), 'program'
    if installers:
        a = installers[0]
        return a.get('name'), a.get('url'), 'installer'
    return '', '', ''


# ---------- الفحص ----------

def _source_version(src, timeout=8):
    """أحدث رقم نسخة معروف عند المصدر ('' لو ما قدرنا نعرف)."""
    try:
        if src['kind'] == 'internal':
            if not _path_reachable(src['loc']):
                return ''
            exe = _pick_program_exe(src['loc'])
            if not exe:
                return ''
            return _exe_file_version(exe) or ''
        # أونلاين
        loc = src['loc']
        if GITHUB_REPO in loc and '/releases' in loc and 'download' not in loc:
            rel = _github_latest_release(timeout)
            return (rel or {}).get('version') or ''
        m = re.search(r'(\d+)\.(\d+)\.(\d+)', loc)
        return m.group(0) if m else ''
    except Exception as e:
        print(f"_source_version ERROR: {e}")
        return ''


def check_for_update(timeout=8):
    """
    فحص خفيف: هل فيه نسخة أحدث من النسخة الحالية؟

    المصادر بالترتيب: **داخلي (مجلد الشبكة) أول، وبعده أونلاين (GitHub)**.
    رقم النسخة لكل مصدر: من خصائص ملف EXE (داخلي) أو من وسم الإصدار
    (أونلاين) — وإلا من رقم النسخة المنشور في السحابة.

    يرجّع (متوفر: bool, النسخة_الجديدة, المصادر) — المصادر قائمة مصادر
    بالترتيب وجاهزة للتنزيل. أي خطأ → (False, '', []).
    """
    try:
        sources = _configured_sources()
        best_ver = _cloud_version(timeout)
        best_t = _parse_version(best_ver)
        for src in sources:
            v = _source_version(src, timeout)
            if not v:
                continue
            src['version'] = v
            vt = _parse_version(v)
            if vt and (best_t is None or vt > best_t):
                best_t, best_ver = vt, v
        cur_t = _parse_version(config.APP_VERSION)
        if not best_t or not cur_t or best_t <= cur_t:
            return False, best_ver, sources
        return True, best_ver, sources
    except Exception as e:
        print(f"check_for_update ERROR: {e}")
        return False, '', []


# ---------- التنزيل ----------

def _copy_from_folder(folder_path):
    """ينسخ نسخة البرنامج من مجلد الشبكة لمجلد مؤقت — ويرجّع المسار أو ''."""
    try:
        if not folder_path or not _path_reachable(folder_path):
            return ''
        exe = _pick_program_exe(folder_path)
        if not exe:
            return ''
        tmp_dir = tempfile.mkdtemp(prefix='ExpertAppUpdate_')
        local = os.path.join(tmp_dir, os.path.basename(exe))
        shutil.copy2(exe, local)
        # تأكد إن الملف انسخ كامل (نسخ الشبكة sometimes ينقطع)
        try:
            if os.path.getsize(local) != os.path.getsize(exe):
                return ''
        except OSError:
            return ''
        return local
    except Exception as e:
        print(f"_copy_from_folder ERROR: {e}")
        return ''


def _download_file(url, name=None, progress=None, timeout=120):
    """
    ينزّل ملف من رابط (مع متابعة الحجم لو progress وُجد).
    يرجّع المسار المحلي أو ''.
    """
    tmp_dir = tempfile.mkdtemp(prefix='ExpertAppUpdate_')
    local = os.path.join(tmp_dir, name or _filename_from_url(url))
    try:
        with requests.get(url, stream=True, timeout=timeout, allow_redirects=True,
                          headers={'User-Agent': 'ExpertApp-Updater'}) as r:
            r.raise_for_status()
            total = int(r.headers.get('Content-Length') or 0)
            done = 0
            with open(local, 'wb') as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        try:
                            if progress(done, total) is False:   # المستخدم ألغى
                                raise InterruptedError('cancelled')
                        except InterruptedError:
                            raise
                        except Exception:
                            pass
            # ⚠️ ملف ناقص = نسخة مكسورة ⟵ ما نستبدل بها البرنامج الحالي.
            if total and done != total:
                raise IOError(f'الملف النازل ناقص ({done} من {total} بايت)')
        return local
    except Exception as e:
        print(f"_download_file ERROR: {e}")
        try:
            shutil.rmtree(os.path.dirname(local), ignore_errors=True)
        except Exception:
            pass
        return ''


def _download_online(src, progress=None, timeout=120):
    """
    ينزّل من مصدر أونلاين.
    يرجّع (المسار المحلي, النوع) — النوع 'program' أو 'installer'.
    """
    loc = src.get('loc') or ''
    try:
        # رابط مستودع/إصدار → نحلّه عبر API ونختار الأصل المناسب
        if GITHUB_REPO in loc and '/releases' in loc and 'download' not in loc:
            rel = _github_latest_release(timeout=10)
            if not rel:
                return '', ''
            name, url, kind = _pick_online_asset(rel)
            if not url:
                return '', ''
            path = _download_file(url, name, progress, timeout)
            return path, kind
        # رابط ملف مباشر
        name = _filename_from_url(loc)
        kind = 'installer' if _is_installer_name(name) else 'program'
        path = _download_file(loc, name, progress, timeout)
        return path, kind
    except Exception as e:
        print(f"_download_online ERROR: {e}")
        return '', ''


def download_update(sources, target_version='', progress=None):
    """
    ينزّل التحديث بالترتيب: **داخلي (مجلد الشبكة) أول، وبعده أونلاين**.

    يرجّع (المسار المحلي, نوع الملف, المصدر):
      - نوع الملف 'program'   = نسخة البرنامج (تُستبدل مكان EXE الحالي)
      - نوع الملف 'installer' = مثبّت (يُشغَّل بدل الاستبدال)
    أو ('', '', None) عند الفشل.
    """
    for src in (sources or []):
        try:
            # مصدر أقدم من النسخة المطلوبة (مثل رابط مثبّت مثبّت على رقم قديم)
            # → نتخطّاه، حتى ما ننزّل نسخة أقدم.
            if target_version and src.get('version'):
                vt = _parse_version(src['version'])
                tt = _parse_version(target_version)
                if vt and tt and vt < tt:
                    continue
            if src.get('kind') == 'internal':
                local = _copy_from_folder(src.get('loc'))
                if local:
                    return local, 'program', src
                continue
            local, kind = _download_online(src, progress)
            if local:
                return local, kind, src
        except Exception as e:
            print(f"download_update ERROR ({src.get('loc')}): {e}")
    return '', '', None


def try_download_update(folder_path):
    """
    (للتوافق مع الكود القديم) ينسخ أحدث نسخة من مجلد واحد — ويرجع المسار
    المحلي أو None (نفس السلوك السابق).
    يفضّل نسخة البرنامج على المثبّت.
    """
    return _copy_from_folder(folder_path) or None


# ---------- التطبيق ----------

#: لاحقة الملف القديم بعد التسمية (مؤقتة — تنحذف بعد نجاح التحديث)
OLD_SUFFIX = '.old'


def exe_path():
    """مسار البرنامج المشغّل (EXE) — نص فاضي لو مشغّل من الكود المصدري."""
    if not getattr(sys, 'frozen', False):
        return ''
    try:
        return os.path.abspath(sys.executable)
    except Exception:
        return ''


def update_result_file():
    """
    ملف نتيجة آخر محاولة تحديث — يكتبه سكربت الـbatch بعد ما يخلّص،
    ويقرؤه البرنامج عند إقلاعه (مرة وحدة) ليخبر الخبير: نجح التحديث
    ولا فشل (وإلا رجع البرنامج القديم بصمت وما عرف ليش).
    """
    base = os.environ.get('LOCALAPPDATA', '') or tempfile.gettempdir()
    return os.path.join(base, 'ExpertApp', 'update_result.txt')


def read_update_result():
    """
    نتيجة آخر تحديث: 'ok' / 'failed' / '' (لو ما فيه).
    الملف ينحذف بعد القراءة ⟵ الرسالة تظهر مرة وحدة بس.
    """
    path = update_result_file()
    try:
        if not os.path.exists(path):
            return ''
        with open(path, encoding='utf-8', errors='replace') as f:
            val = (f.read() or '').strip().lower()
        os.remove(path)
        return val
    except Exception:
        return ''


def cleanup_stale_update_files():
    """
    يحذف بقايا النسخ السابقة جنب البرنامج (ExpertApp.exe.old / .bak) —
    كانت «نسخة ثانية» يلقاها الخبير بمجلد البرنامج. بينادى عند الإقلاع.
    """
    current = exe_path()
    if not current:
        return
    folder = os.path.dirname(current)
    base = os.path.basename(current)
    for name in (base + OLD_SUFFIX, base + '.bak'):
        try:
            p = os.path.join(folder, name)
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def _backup_current_exe(current_exe):
    """
    نسخة احتياطية من EXE الحالي — **بمجلد مؤقت** (مو بمجلد البرنامج!).

    ⚠️ ما عاد مستعمل بالتحديث الجديد: التسمية (move) نفسها هي الاحتياط —
    البرنامج القديم يبقى موجوداً باسم .old حتى لو فشل النسخ (نرجّعه).
    ⚠️ سبب التغيير الأصلي: النسخة الاحتياطية كانت تنحفظ جنب البرنامج
    (ExpertApp.exe.bak) وتبقى للأبد ⟵ كانت هي «النسخة الثانية» اللي
    يشوفها الخبير بمجلد البرنامج.
    """
    try:
        bak_dir = tempfile.mkdtemp(prefix='ExpertAppUpdate_Bak_')
        bak = os.path.join(bak_dir, os.path.basename(current_exe) + '.bak')
        shutil.copy2(current_exe, bak)
        return bak
    except Exception:
        return ''


def apply_update(new_exe_path, kind='program'):
    """
    يطبّق التحديث **بمكانه** — ما ينسخ نسخة ثانية أبداً:

      - 'program':   يستبدل EXE المشغّل بالجديد (القديم يبقى مؤقتاً باسم
                     .old ويُحذف بعد نجاح الاستبدال)، ثم يعيد تشغيل
                     **نفس المسار** ⟵ اختصارات المستخدم وقائمة ابدأ تبقى
                     على النسخة الجديدة.
      - 'installer': يشغّل المثبّت **بنفس مجلد البرنامج** (/DIR=...) ⟵
                     Inno Setup ينصّب فوق النسخة القديمة (يحذفها ويزرع
                     الجديدة بنفس المكان) بدل ما ينصّب نسخة ثانية بمكان
                     ثاني، وبعدها يعيد تشغيل **نفس المسار**.

    ⚠️ سبب هذا الإصلاح (المبلَّغ 18/11/2026): التحديث ما كان يشتغل أبداً
    على أي جهاز —سببين حقيقيين (كلاهما مُقاس):

      1) **المسار العربي كان يضيع**: سكربت الـbatch كان يُكتب بترميز
         mbcs (cp1252 على الأجهزة الإنجليزية) ⟵ كل حرف عربي صار «؟» ⟵
         المسار الفعلي «C:\\...\\نظام جلسات الخبراء\\ExpertApp.exe» صار
         «C:\\...\\???? ????? ???????\\ExpertApp.exe» ⟵ النسخة ما تقدر
         تنسخ لمكانها (المسار ما موجود). الحل: **السكربت ASCII صِرف**
         والمسارات تجي **بمتغيرات بيئة** (Unicode) ⟵ cmd يسلّمها للـAPI
         سليمة. (مقاس: الترجمة نجحت مع مسار عربي عبر متغيرات بيئة.)

      2) **«البرنامج يعمل» ⟵ قفل الملف**: ويندوز يرفض الكتابة فوق EXE
         شغّال («The process cannot access the file ... because it is being
         used by another process»). نسخة onefile (PyInstaller) فيها عملية
         أب (bootstrap) تحتجز الملف حتى بعد خروج البرنامج ⟵ فالمحاولات
         (15 × ~1.5 ث ≈ 20 ث) كلها تفشل. لكن **التسمية مسموحة** لملف
         شغّال ⟵ نسمّيها .old (يفكّ القفل) وبعدها ننسخ الجديدة بالمكان
         والشغّال يكمّل على النسخة المسمّاة.

    ⚠️ الآن المستخدم **يعرف** إن التحديث فشل: الـbatch يكتب النتيجة
    بملفResult، والبرنامج يخبره عند الإقلاع (مرة وحدة).

    يعمل فقط من نسخة EXE المبنية (sys.frozen) — من الكود المصدري لا يفعل شي.
    """
    if not getattr(sys, 'frozen', False) or not new_exe_path:
        return False
    current_exe = exe_path()
    if not current_exe:
        return False
    bat_path = os.path.join(tempfile.gettempdir(), 'expertapp_update.bat')
    tmp_dir = os.path.dirname(new_exe_path)
    app_dir = os.path.dirname(current_exe)
    old_exe = current_exe + OLD_SUFFIX
    result_file = update_result_file()
    try:
        os.makedirs(os.path.dirname(result_file), exist_ok=True)
    except Exception:
        pass

    # ⚠️ السكربت ASCII صِرف — **أي** مسار يمر بمتغير بيئة (Unicode).
    #    (كتابة مسار عربي داخل السكربت = نفس البوكس القديم.)
    head = (
        '@echo off\r\n'
        'ping -n 3 127.0.0.1 >nul\r\n'
    )
    if kind == 'installer':
        body = (
            # سمِّ البرنامج الجاري تشغيله (يفكّ قفل الملف) ثم المثبّت ينصّب
            # فوق النسخة الجديدة بنفس المجلد.
            'move /Y "%EXPERTAPP_OLD%" "%EXPERTAPP_OLDBak%" >nul 2>&1\r\n'
            'call "%EXPERTAPP_INSTALLER%" /VERYSILENT /SUPPRESSMSGBOXES '
            '/NORESTART /CLOSEAPPLICATIONS /SP- /DIR="%EXPERTAPP_DIR%"\r\n'
            'if exist "%EXPERTAPP_OLD%" goto :installed\r\n'
            'move /Y "%EXPERTAPP_OLDBak%" "%EXPERTAPP_OLD%" >nul 2>&1\r\n'
            'goto :failed\r\n'
        )
    else:
        body = (
            # (1) سمِّ الملف الجاري تشغيله — ويندوز يسمح بذلك
            'move /Y "%EXPERTAPP_OLD%" "%EXPERTAPP_OLDBak%" >nul 2>&1\r\n'
            'if exist "%EXPERTAPP_OLDBak%" goto :renamed\r\n'
            'goto :direct\r\n'
            ':renamed\r\n'
            'set tries=0\r\n'
            ':copy_retry\r\n'
            'copy /Y "%EXPERTAPP_NEW%" "%EXPERTAPP_OLD%" >nul 2>&1\r\n'
            'if not errorlevel 1 goto :installed\r\n'
            'set /a tries+=1\r\n'
            'if %tries% LSS 15 (\r\n'
            '  ping -n 2 127.0.0.1 >nul\r\n'
            '  goto copy_retry\r\n'
            ')\r\n'
            # فشل نهائي ⟵ رجّع النسخة القديمة (هي .old) لمكانها
            'move /Y "%EXPERTAPP_OLDBak%" "%EXPERTAPP_OLD%" >nul 2>&1\r\n'
            'goto :failed\r\n'
            # مسار بديل: نسخ مباشر (لو التسمية ما نجحت — نادر)
            ':direct\r\n'
            'set tries=0\r\n'
            ':retry\r\n'
            'copy /Y "%EXPERTAPP_NEW%" "%EXPERTAPP_OLD%" >nul 2>&1\r\n'
            'if not errorlevel 1 goto :installed\r\n'
            'set /a tries+=1\r\n'
            'if %tries% LSS 15 (\r\n'
            '  ping -n 2 127.0.0.1 >nul\r\n'
            '  goto retry\r\n'
            ')\r\n'
            'goto :failed\r\n'
        )
    tail = (
        ':installed\r\n'
        '> "%EXPERTAPP_RES%" echo ok\r\n'
        'start "" "%EXPERTAPP_OLD%"\r\n'
        # النسخة القديمة ما تنحذف إلا بعد ما يخرج البرنامج القديم (العملية
        # تحتجزها) ⟵ محاولات + تنظيف عند الإقلاع القادم احتياطاً.
        'set tries=0\r\n'
        ':del_old\r\n'
        'del /F /Q "%EXPERTAPP_OLDBak%" >nul 2>&1\r\n'
        'if not exist "%EXPERTAPP_OLDBak%" goto :cleanup\r\n'
        'set /a tries+=1\r\n'
        'if %tries% LSS 20 (\r\n'
        '  ping -n 2 127.0.0.1 >nul\r\n'
        '  goto del_old\r\n'
        ')\r\n'
        'goto :cleanup\r\n'
        ':failed\r\n'
        '> "%EXPERTAPP_RES%" echo failed\r\n'
        'start "" "%EXPERTAPP_OLD%"\r\n'
        ':cleanup\r\n'
        'del /F /Q "%EXPERTAPP_OLD%.bak" >nul 2>&1\r\n'
        'rmdir /S /Q "%EXPERTAPP_TMP%" >nul 2>&1\r\n'
        '(goto) 2>nul & del "%~f0"\r\n'
    )
    script = head + body + tail

    env = dict(os.environ)
    env.update({
        'EXPERTAPP_OLD': current_exe,
        'EXPERTAPP_OLDBak': old_exe,
        'EXPERTAPP_NEW': new_exe_path,
        'EXPERTAPP_INSTALLER': new_exe_path,
        'EXPERTAPP_DIR': app_dir,
        'EXPERTAPP_RES': result_file,
        'EXPERTAPP_TMP': tmp_dir,
    })
    with open(bat_path, 'w', encoding='ascii', errors='replace') as f:
        f.write(script)
    subprocess.Popen(
        ['cmd', '/c', bat_path],
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )
    #سكربت الـbatch اشتغل ⟵ نخرج من البرنامج، وهو يكمل شغله:
    #نسخ النسخة الجديدة + إعادة تشغيل المسار نفسه.
    os._exit(0)
