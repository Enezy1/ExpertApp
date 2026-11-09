---
name: release
description: إصدار نسخة جديدة من ExpertApp — رفع الرقم، بناء EXE، مثبّت Inno Setup، ضغط RAR، نسخ إلى OneDrive - mojq8، وتحقق. استخدمه عند قول "/release" أو "سو نسخة جديدة".
---

# إصدار نسخة ExpertApp

المجلد: `C:\Users\Dell\Desktop\ExpertApp`. لا تسأل المستخدم؛ نفّذ كل الخطوات بالترتيب، وأوقف وبلّغ عند أول فشل.
الوسيط (اختياري): `--minor` أو `--major` يُمرَّر لـ build.py، وإلا يزيد patch.

1. **البناء** (يرفع `APP_VERSION` في config.py تلقائيًا ثم PyInstaller، ~7 دقائق — شغّله في الخلفية):
   `PYTHONIOENCODING=utf-8 python build.py [--minor|--major]`
   ثم اقرأ `APP_VERSION` الجديد من config.py (اسمه X.Y.Z) وتأكد من وجود `dist\ExpertApp.exe` بوقت حديث.
2. **المثبّت:** غيّر `#define MyAppVersion` في `Installer.iss` إلى نفس X.Y.Z، ثم:
   `"/c/Program Files (x86)/Inno Setup 6/ISCC.exe" Installer.iss`
   الناتج: `installer_output\تثبيت_نظام_جلسات_الخبراء.exe`
3. **الضغط:** من داخل `installer_output`:
   `"/c/Program Files/WinRAR/Rar.exe" a -ep -m5 "نظام_جلسات_الخبراء_X.Y.Z.rar" "تثبيت_نظام_جلسات_الخبراء.exe"`
4. **النسخ:** `cp` الـ rar إلى `C:\Users\Dell\OneDrive - mojq8\` (جذر المجلد، بجانب النسخ السابقة).
5. **التحقق:** قارن الحجم بين الملفين، ونفّذ `UnRAR.exe t` على نسخة OneDrive (يجب "All OK").
6. **السجل:** أضف سطرًا في Changelog بـ `PROJECT_MEMORY.md` (التاريخ، رقم النسخة، ما تغيّر منذ آخر نسخة).
7. **التقرير:** اذكر الرقم والحجم ومسار الملف، وأن حالة رفع OneDrive للسحابة تُرى من أيقونتها (لا يمكن التحقق منها من هنا).

## ⚠️ خطوة لازمة للتحديث التلقائي — «نسخة البرنامج» بالاسم الثابت

التحديث التلقائي (updater.py) يجرّب مصدرين بالترتيب: **مجلد الشبكة الداخلي** ← **أونلاين (GitHub)**.
لكل مصدرين لازم يكون فيه **نسخة البرنامج المحمولة** (`dist\ExpertApp.exe`) — **مو المثبّت**:
استبدال البرنامج بملف `Setup.exe` يجعله ما يحمل بعد التحديث.

- **الداخلي:** الأدمن ينسخ `dist\ExpertApp.exe` (وليس ملف التثبيت) لمجلد التحديثات على الشبكة.
- **الأونلاين:** ارفع نسخة البرنامج كأصل في إصدار GitHub **بالاسم الثابت `ExpertApp.exe`**:
  ```powershell
  gh release upload vX.Y.Z dist\ExpertApp.exe
  ```
  (الاسم لازم يبقى `ExpertApp.exe` بالضبط — البرنامج يبحث عن هذا الاسم أول شي، وإذا ما لقيه ينزّل المثبّت).
  الرابط الثابت: `https://github.com/Enezy1/ExpertApp/releases/latest/download/ExpertApp.exe`

⚠️ **كل إصدار جديد لازم ينشر الأصل هذا** — بدونه التحديث الأونلاين يشتغل بس يفتح المثبّت بدل ما يحدّث البرنامج مباشرة.

لا تنشر لمجلد التحديثات بالشبكة ولا تحفظ مساره من الإعدادات — هذا يدوي بيد المستخدم.
