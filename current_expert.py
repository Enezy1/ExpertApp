# ===== current_expert.py — تحديد الخبير الحالي لفصل إعداداته عن غيره =====
"""
البرنامج ممكن يُستخدم على جهاز واحد من أكثر من خبير (كل واحد يسجّل
دخول بحسابه الخاص بالنظام، بنفس الجهاز). هذا الملف يحدد اسم الخبير
الحالي **مرة واحدة عند تسجيل الدخول** (main.py يستدعي set_current_user
بعد التأكد من الاسم)، وتستخدمه باقي ملفات الإعدادات الشخصية
(gemini_config.py، icloud_calendar.py، expert_settings.py) لتخزين كل
إعداد بمجلد خاص بكل خبير على حدة، بدل مجلد عام واحد يتشاركه الكل
بالغلط.

ملاحظة: قاعدة بيانات القضايا (case_db.py) تبقى مشتركة عمدًا — بيانات
القضية نفسها (رقم القضية، المدعي، تاريخ الحكم...) حقيقة عن القضية
لا تخص خبيرًا بعينه، فمشاركتها بين خبراء الجهاز نفسه غير ضارة. اللي
يخص الخبير شخصيًا فقط هو: مفتاح الذكاء الاصطناعي، حساب iCloud،
والشق التخصصي — هذولا الثلاثة هم المفصولين هنا.

رقم الحساب (account no):
يُضبط كذلك مرة واحدة عند الدخول. رقم الحساب هو اسم المستخدم الذي يكتبه
الخبير بشاشة الدخول (مثل 309). يُحفظ كمعلومة إضافية فقط — ⚠️ غير موثوق
للتخويل لأن النظام الحكومي يعلق على رقم أول مستخدم دخل الجهاز حتى لو
غيّره الخبير يدويًا. التخويل الفعلي صار بالاسم المعروض الموثوق
(get_logged_in_name) — انظر main1_access.py.
"""
import os
import re

_current_user = None
_current_account = None


def set_current_user(name):
    "تُستدعى مرة واحدة من main.py فور تأكيد اسم الخبير المسجّل دخوله"
    global _current_user
    _current_user = (name or '').strip()


def get_current_user():
    return _current_user or 'default'


def set_current_account(account_no):
    "تُستدعى مرة واحدة من main.py — رقم الحساب (معلومة إضافية فقط، غير موثوق للتخويل)"
    global _current_account
    _current_account = (str(account_no).strip() if account_no else None)


def get_current_account():
    "يرجع رقم حساب الخبير الحالي (نص)، أو نص فاضي لو غير معروف"
    return _current_account or ''


def safe_folder_name(name):
    "يحوّل اسم الخبير لاسم مجلد صالح (يحذف رموز ممنوعة بأسماء الملفات/المجلدات بويندوز)"
    cleaned = re.sub(r'[\\/:*?"<>|]', '_', name.strip())
    return cleaned or 'default'


def expert_data_dir():
    "يرجع مجلد بيانات الخبير الحالي (ينشئه لو غير موجود)"
    base = os.path.join(
        os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'experts',
        safe_folder_name(get_current_user())
    )
    os.makedirs(base, exist_ok=True)
    return base
