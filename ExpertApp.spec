# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import re as _re

# رقم النسخة يُدمج بخصائص ملف EXE (يقرأه updater.py من مجلد التحديثات بلا تشغيله)
_ver = _re.search(r'APP_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"', open('config.py', encoding='utf-8').read())
_v = tuple(int(x) for x in _ver.groups()) if _ver else (0, 0, 0)
_vs = '.'.join(map(str, _v)) + '.0'
with open('version_info.txt', 'w', encoding='utf-8') as _f:
    _f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={_v + (0,)}, prodvers={_v + (0,)}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', 'ExpertApp'),
      StringStruct('FileVersion', '{_vs}'),
      StringStruct('ProductName', 'ExpertApp'),
      StringStruct('ProductVersion', '{_vs}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")

datas = [
    ('ma7dar_template.dotx', '.'),
    ('اخطار_حكومه.dotx', '.'),
    ('نماذج_صياغة_الموضوع.md', '.'),
    ('نماذج_صياغة_الإجراءات.md', '.'),
    ('نماذج_صياغة_البحث.md', '.'),
    ('app_icon.ico', '.'),
    ('app_icon.png', '.'),
    ('desk_icon.ico', '.'),     # أيقونة «مكتب الخبير» — النافذة وشريط المهام
    ('desk_icon.png', '.'),
]
binaries = []
hiddenimports = []

# PyQt6 بلا collect_all: هوك PyInstaller يضم الوحدات المستوردة فعلًا (QtCore/QtGui/QtWidgets) وإضافاتها.
# collect_all كان يضم Qt كاملة (Quick/QML/3D/Pdf/Multimedia/Designer…) ~78MB لا يستخدمها البرنامج.
for pkg in [
    'pyodbc',
    'customtkinter',
    'webview',
    'browser_cookie3',
    'google.genai',
    'pydantic',
    'caldav',
    'icalendar',
]:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

import os
if os.path.isdir('fonts'):
    datas += [('fonts', 'fonts')]
# نموذجا OCR الداخلي (كشف + تعرّف عربي، ~13MB). بدونهما يرجع البرنامج للمسار القديم تلقائيًا
if os.path.isdir('assets/fonts'):
    datas += [('assets/fonts', 'assets/fonts')]

datas += [('ocr/models', 'ocr/models')]
# شعارا ترويسة تقرير الخبرة (report_docx.py / report_builder.py)
datas += [('report_assets', 'report_assets')]
# مكتبات تشغيل onnxruntime فقط. collect_all('onnxruntime') يسحب أدواتها (transformers/tools) ومعها torch وscipy
# وpandas وsympy — رفعت EXE تجريبي إلى 347MB بدل 114MB، والبرنامج لا يستخدم أياً منها
from PyInstaller.utils.hooks import collect_dynamic_libs
binaries += collect_dynamic_libs('onnxruntime')
hiddenimports += ['onnxruntime', 'onnxruntime.capi._pybind_state', 'local_ocr', 'ocr_engine', 'local_extract', 'page_orient',
                  'cv2', 'pyclipper', 'numpy']
# معاينة الملف الآلي داخل التطبيق (qt_case_lookup.show_pdf_preview) — استيرادها داخل دالة فنُصرّح بها صراحة
hiddenimports += ['PyQt6.QtPdf', 'PyQt6.QtPdfWidgets']
# مجلد القضية (المرحلة 2أ) — يُستورد داخل دالة في qt_settings_page
hiddenimports += ['case_workspace', 'report_pipeline', 'secret_store']
# التقرير المركَّب بالكود (2026-10-20) — يُستورد داخل دوال research_pipeline/conclusion_pipeline
hiddenimports += ['case_facts', 'report_playbooks', 'report_compose', 'report_audit', 'report_v3']
OCR_EXCLUDES = ['torch', 'scipy', 'pandas', 'sympy', 'onnx', 'onnxruntime.transformers', 'onnxruntime.tools',
                'onnxruntime.quantization',
                # استيرادات اختيارية لمكتبات أخرى (PIL/fsspec/sentry…) — البرنامج لا يستخدمها
                'pyarrow', 'grpc', 'hf_xet', 'huggingface_hub']

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=OCR_EXCLUDES,
    noarchive=False,
    optimize=0,
)
# cv2 يُستخدم لمعالجة صور OCR فقط: مكتبة تشغيل الفيديو (ffmpeg، ~13MB) لا حاجة لها
a.binaries = [b for b in a.binaries if 'opencv_videoio_ffmpeg' not in b[0]]

# ---- تحصين: لا أسرار ولا إعدادات محلية داخل EXE ----
# gemini_network.ini فيه مفاتيح Groq/OCR.space، وai_providers_cache.json وملفات المفاتيح تعيش في %LOCALAPPDATA% لا في المشروع.
# نستبعد: أي .ini من مجلد المشروع (مكتبات الطرف الثالث لا تُمسّ)، وأسماء الأسرار أينما وُجدت. ثم نفشل البناء إن بقي أثر.
import os as _os
_SPEC_DIR = _os.path.normcase(_os.path.abspath(SPECPATH))
_SECRET_NAMES = {'gemini_network.ini', 'ai_providers_cache.json', 'credentials.json', 'gemini_key.json',
                 'ocr_key.json', 'vision_key.json', 'openai_key.json', 'expert_settings.json', 'ocr_quota.json'}


def _is_secret_data(entry):
    dest = entry[0].replace(chr(92), '/').lower()
    name = dest.rsplit('/', 1)[-1]
    src = _os.path.normcase(_os.path.abspath(entry[1]))
    in_project = src.startswith(_SPEC_DIR + _os.sep)
    return name in _SECRET_NAMES or (in_project and name.endswith('.ini'))


a.datas = [d for d in a.datas if not _is_secret_data(d)]
_leaked = [d[0] for d in a.datas if _is_secret_data(d)]
assert not _leaked, f'ملفات أسرار داخل EXE: {_leaked}'

pyz = PYZ(a.pure)

# شاشة انتظار تظهر فور تشغيل الـEXE (أثناء فك الملفات، قبل أن يبدأ كود بايثون).
# تُغلق من main.py عبر pyi_splash.close() لما تظهر نافذة الانتظار الرئيسية.
splash = Splash(
    'splash_boot.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    always_on_top=True,
)

# onefile: EXE واحد مستقل (مطلوب لنظام التحديث التلقائي updater.py — يُنسخ ملف واحد ويُستبدل)
exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    [],
    name='ExpertApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon='desk_icon.ico',          # أيقونة ملف EXE (يولّدها make_desk_icon.py)
)
