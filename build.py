# ===== build.py — يرفع رقم النسخة تلقائيًا ثم يبني EXE بـPyInstaller =====
"""
الاستخدام:
    python build.py            # يزيد patch:  1.0.3 → 1.0.4
    python build.py --minor    # يزيد minor:  1.2.5 → 1.3.0
    python build.py --major    # يزيد major:  1.2.5 → 2.0.0
بعد النجاح، انسخ الـEXE من dist لمجلد التحديثات بالشبكة يدويًا، ثم من
إعدادات البرنامج (حساب الأدمن) احفظ مسار المجلد لنشر النسخة الجديدة.
"""
import os
import re
import sys
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, 'config.py')
_VERSION_RE = re.compile(r'^(APP_VERSION\s*=\s*")(\d+)\.(\d+)\.(\d+)(")', re.MULTILINE)


def read_version(text):
    m = _VERSION_RE.search(text)
    if not m:
        raise SystemExit("❌ ما لقيت APP_VERSION بصيغة major.minor.patch بملف config.py")
    return tuple(int(m.group(i)) for i in (2, 3, 4))


def bump(version, args):
    major, minor, patch = version
    if '--major' in args:
        return (major + 1, 0, 0)
    if '--minor' in args:
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def main():
    # كونسول ويندوز (cp1252/cp1256) قد لا يدعم الإيموجي — لا نسمح له بإيقاف البناء
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    args = sys.argv[1:]
    with open(CONFIG_PATH, encoding='utf-8') as f:
        text = f.read()

    old = read_version(text)
    new = bump(old, args)
    new_str = '.'.join(map(str, new))

    text = _VERSION_RE.sub(lambda m: f'{m.group(1)}{new_str}{m.group(5)}', text, count=1)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f"🔨 بناء نسخة {new_str}  (السابقة: {'.'.join(map(str, old))})")
    result = subprocess.run(["pyinstaller", "ExpertApp.spec", "--noconfirm"], cwd=ROOT)
    if result.returncode != 0:
        print(f"❌ فشل البناء (رمز {result.returncode}). رقم النسخة بقي {new_str} بملف config.py.")
        sys.exit(result.returncode)

    exe_path = os.path.join(ROOT, 'dist', 'ExpertApp.exe')
    print(f"\n✅ تم البناء بنجاح — نسخة {new_str}")
    print(f"📦 الملف: {exe_path}")
    print("⚠️ لا تنسى: انسخ ExpertApp.exe يدويًا لمجلد التحديثات على الشبكة،"
          " ثم احفظ المسار من الإعدادات (حساب الأدمن) لنشر النسخة.")


if __name__ == '__main__':
    main()
