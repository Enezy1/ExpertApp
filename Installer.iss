; ===== Installer.iss — سكربت تثبيت نظام جلسات الخبراء =====
; يُجمَّع بواسطة Inno Setup Compiler (مجاني) لإنتاج ملف Setup.exe
; واحد يثبت البرنامج تلقائيًا (اختصار سطح المكتب + قائمة ابدأ +
; برنامج إلغاء تثبيت رسمي بلوحة تحكم ويندوز).
;
; المتطلب قبل التجميع: ملف dist\ExpertApp.exe لازم يكون موجود وجاهز
; (يعني نفّذت أمر: pyinstaller ExpertApp.spec  قبل هذا).
;
; ===== متطلبات إضافية (سبب شائع لاختفاء البرنامج بصمت على جهاز جديد) =====
; PyQt6 وpywebview يحتاجان مكتبات نظام غير مضمّنة تلقائيًا داخل أي EXE
; مبني بـ PyInstaller:
;   1) Visual C++ Redistributable 2015-2022 (x64) — بدونه PyQt6 ينهار
;      فوراً بدون أي رسالة خطأ (crash صامت على مستوى نظام التشغيل، لا
;      يصل حتى لكود بايثون ليُسجَّل بملف crash_log.txt).
;   2) Microsoft Edge WebView2 Runtime — تحتاجه نافذة تسجيل الدخول
;      الداخلية (pywebview). موجود افتراضيًا على أغلب أجهزة ويندوز 11
;      وأغلب ويندوز 10 المحدَّثة، لكن غير مضمون على كل الأجهزة.
;
; قبل تجميع هذا السكربت، نزّل الملفين التاليين مرة واحدة وضعهما بجانب
; هذا الملف (Installer.iss) بنفس المجلد:
;   - vc_redist.x64.exe
;     من: https://aka.ms/vs/17/release/vc_redist.x64.exe
;   - MicrosoftEdgeWebView2RuntimeInstaller.exe
;     من: https://go.microsoft.com/fwlink/p/?LinkId=2124703
; الاثنان صغار (الأول ~25 ميجا، الثاني ~2 ميجا) ويُثبَّتان مرة واحدة
; فقط بصمت (silent) — السكربت يتحقق تلقائياً إذا كانا مثبَّتين مسبقاً
; ويتخطاهما في هذي الحالة.

#define MyAppName "نظام جلسات الخبراء"
#define MyAppVersion "1.2.10"
#define MyAppPublisher "وزارة العدل - الكويت"
#define MyAppExeName "ExpertApp.exe"

[Setup]
AppId={{B6E6C1B2-4B7B-4B36-9E7B-6C2E1E6E9A11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=تثبيت_نظام_جلسات_الخبراء
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "إنشاء اختصار على سطح المكتب"; GroupDescription: "اختصارات إضافية:"

[Files]
Source: "dist\ExpertApp.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not VCRedistInstalled
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not WebView2Installed

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\إلغاء تثبيت {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; يُثبَّتان بصمت وقبل تشغيل البرنامج نفسه — يُتخطَّيان تلقائياً لو
; مثبَّتان مسبقاً (شرط Check أعلاه في [Files] يمنع حتى نسخهما لو غير
; محتاجين).
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "جاري تثبيت مكوّنات ويندوز الأساسية (مرة واحدة)..."; Check: not VCRedistInstalled; Flags: waituntilterminated
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "جاري تثبيت WebView2 Runtime (مرة واحدة)..."; Check: not WebView2Installed; Flags: waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "تشغيل {#MyAppName} الآن"; Flags: nowait postinstall skipifsilent

[Code]
// يتحقق من وجود Visual C++ Redistributable 2015-2022 (x64) عبر مفتاح
// الريجستري الرسمي اللي يكتبه مثبِّت مايكروسوفت نفسه.
function VCRedistInstalled: Boolean;
var
  installed: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64', 'Installed', installed)
    and (installed = 1);
end;

// يتحقق من وجود WebView2 Runtime عبر مفتاح الريجستري اللي يكتبه مثبت
// Edge/WebView2 (نفس المفتاح لنسخة الجهاز الكامل ونسخة per-user).
function WebView2Installed: Boolean;
var
  ver: String;
begin
  Result := RegQueryStringValue(HKLM64, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', ver)
    or RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', ver)
    or RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', ver);
end;
