# ===== settings_page.py — صفحة الإعدادات (ربط Google Gemini API) =====
"""
صفحة بسيطة داخل البرنامج: حقل واحد يلصق فيه الخبير مفتاح Gemini API
(من aistudio.google.com/app/apikey)، وزر حفظ. المفتاح يُخزَّن محليًا
عبر gemini_config.py ولا يُعرض كاملاً بعد الحفظ (نسخة مموهة فقط).
"""
import customtkinter as ctk
from tkinter import messagebox
from gemini_config import save_api_key, load_api_key, mask_key
from expert_settings import save_specialty, load_specialty, save_location, load_location
from icloud_calendar import (
    save_credentials as save_icloud_credentials,
    load_credentials as load_icloud_credentials,
    test_connection as test_icloud_connection,
)

SIDEBAR  = "#1e2535"
SIDEBAR2 = "#252f42"
BG       = "#f5f6fa"
CARD     = "#ffffff"
CARD_BD  = "#e8ecf0"
ACCENT   = "#2ecc71"
ACCENT2  = "#27ae60"
BLUE     = "#3498db"
TEXT_D   = "#1e2535"
TEXT_M   = "#5a6a80"
TEXT_L   = "#94a3b8"
WHITE    = "#ffffff"
FONT     = "Arial"


def F(s, b=False):
    return (FONT, s, "bold") if b else (FONT, s)


def build_settings_page(parent):
    """يبني صفحة الإعدادات داخل parent — حاليًا فقط ربط مفتاح Gemini API"""
    top = ctk.CTkFrame(parent, fg_color=WHITE, corner_radius=0, height=56,
        border_width=1, border_color=CARD_BD)
    top.pack(fill='x'); top.pack_propagate(False)

    content = ctk.CTkScrollableFrame(parent, fg_color="transparent",
        scrollbar_button_color=CARD_BD, scrollbar_button_hover_color=TEXT_L)
    content.pack(fill='both', expand=True, padx=30, pady=22)

    ctk.CTkLabel(content, text="الإعدادات",
        font=F(24, True), text_color=TEXT_D).pack(anchor='e')
    ctk.CTkLabel(content, text="ربط الذكاء الاصطناعي (Google Gemini) لقراءة أحكام الإحالة",
        font=F(12), text_color=TEXT_L).pack(anchor='e', pady=(3, 20))

    card = ctk.CTkFrame(content, fg_color=CARD, corner_radius=12,
        border_width=1, border_color=CARD_BD)
    card.pack(fill='x', pady=4)

    inner = ctk.CTkFrame(card, fg_color="transparent")
    inner.pack(fill='x', padx=20, pady=18)

    ctk.CTkLabel(inner, text="مفتاح Google Gemini API",
        font=F(13, True), text_color=TEXT_D).pack(anchor='e')
    ctk.CTkLabel(inner, text="تحصل عليه من aistudio.google.com/app/apikey",
        font=F(10), text_color=TEXT_L).pack(anchor='e', pady=(2, 10))

    status_lbl = ctk.CTkLabel(inner, text="", font=F(11, True), text_color=ACCENT2)
    status_lbl.pack(anchor='e', pady=(0, 8))

    row = ctk.CTkFrame(inner, fg_color="transparent")
    row.pack(fill='x')

    entry = ctk.CTkEntry(row, font=F(13), justify='left', fg_color=WHITE,
        border_color=CARD_BD, text_color=TEXT_D,
        placeholder_text="AIzaSy...")
    entry.pack(side='right', fill='x', expand=True, padx=(0, 10))

    def refresh_status():
        existing = load_api_key()
        if existing:
            status_lbl.configure(text=f"✅ مفتاح محفوظ حاليًا: {mask_key(existing)}")
        else:
            status_lbl.configure(text="⚠️ لا يوجد مفتاح محفوظ بعد")

    def do_paste():
        try:
            clip = entry.clipboard_get()
        except Exception:
            messagebox.showwarning("تنبيه", "الحافظة فاضية — انسخ المفتاح أولاً، ثم اضغط لصق")
            return
        entry.delete(0, 'end')
        entry.insert(0, clip.strip())

    def do_save():
        key = entry.get().strip()
        if not key:
            messagebox.showwarning("تنبيه", "يرجى لصق المفتاح أولاً")
            return
        save_api_key(key)
        entry.delete(0, 'end')
        refresh_status()
        messagebox.showinfo("✅ تم", "تم حفظ مفتاح Gemini بنجاح")

    ctk.CTkButton(row, text="💾 حفظ", font=F(12, True), width=90, height=36,
        fg_color=ACCENT, hover_color=ACCENT2, text_color=WHITE,
        command=do_save).pack(side='left')

    ctk.CTkButton(row, text="📋 لصق", font=F(12, True), width=80, height=36,
        fg_color=BLUE, hover_color="#2980b9", text_color=WHITE,
        command=do_paste).pack(side='left', padx=(0, 8))

    def do_test():
        key = load_api_key()
        if not key:
            messagebox.showwarning("تنبيه", "لا يوجد مفتاح محفوظ — احفظ المفتاح أولاً")
            return
        try:
            from google import genai
        except ImportError:
            messagebox.showerror(
                "خطأ",
                "مكتبة google-genai غير مثبتة على جهازك.\n\n"
                "افتح cmd وشغّل:\npip install google-genai"
            )
            return

        status_lbl.configure(text="⏳ جاري الاختبار...")
        inner.update()
        try:
            from gemini_config import generate_content_with_fallback
            client = genai.Client(api_key=key)
            response = generate_content_with_fallback(
                client,
                contents='قل بالضبط هذي الجملة فقط: تم الربط بنجاح'
            )
            messagebox.showinfo("✅ الاتصال يعمل", f"رد Gemini:\n\n{response.text}")
        except Exception as e:
            messagebox.showerror("❌ فشل الاتصال", f"تعذر الاتصال بـ Gemini:\n\n{e}")
        refresh_status()

    ctk.CTkButton(inner, text="🧪 اختبار الاتصال بالذكاء الاصطناعي", font=F(12, True),
        height=38, fg_color="#9b59b6", hover_color="#8e44ad", text_color=WHITE,
        command=do_test).pack(anchor='e', pady=(14, 0))

    refresh_status()

    # ===== بطاقة ثانية: ربط تقويم iCloud (مزامنة مواعيد الجلسات تلقائيًا) =====
    card3 = ctk.CTkFrame(content, fg_color=CARD, corner_radius=12,
        border_width=1, border_color=CARD_BD)
    card3.pack(fill='x', pady=(16, 4))

    inner3 = ctk.CTkFrame(card3, fg_color="transparent")
    inner3.pack(fill='x', padx=20, pady=18)

    ctk.CTkLabel(inner3, text="ربط تقويم الآيفون (iCloud)",
        font=F(13, True), text_color=TEXT_D).pack(anchor='e')
    ctk.CTkLabel(inner3, text="مواعيد الجلسات الجديدة تُرسَل تلقائيًا لتقويمك الافتراضي بالآيفون",
        font=F(10), text_color=TEXT_L).pack(anchor='e', pady=(2, 10))

    apple_id_row = ctk.CTkFrame(inner3, fg_color="transparent")
    apple_id_row.pack(fill='x', pady=(0, 8))
    apple_id_entry = ctk.CTkEntry(apple_id_row, font=F(13), justify='left',
        fg_color=WHITE, border_color=CARD_BD, text_color=TEXT_D,
        placeholder_text="بريد Apple ID")
    existing_apple_id, existing_app_pw = load_icloud_credentials()
    if existing_apple_id:
        apple_id_entry.insert(0, existing_apple_id)
    apple_id_entry.pack(side='right', fill='x', expand=True, padx=(0, 8))

    def do_paste_apple_id():
        try:
            clip = apple_id_entry.clipboard_get()
        except Exception:
            messagebox.showwarning("تنبيه", "الحافظة فاضية — انسخ البريد أولاً، ثم اضغط لصق")
            return
        apple_id_entry.delete(0, 'end')
        apple_id_entry.insert(0, clip.strip())

    ctk.CTkButton(apple_id_row, text="📋 لصق", font=F(12, True), width=70, height=32,
        fg_color=BLUE, hover_color="#2980b9", text_color=WHITE,
        command=do_paste_apple_id).pack(side='left')

    app_pw_row = ctk.CTkFrame(inner3, fg_color="transparent")
    app_pw_row.pack(fill='x', pady=(0, 8))
    app_pw_entry = ctk.CTkEntry(app_pw_row, font=F(13), justify='left',
        fg_color=WHITE, border_color=CARD_BD, text_color=TEXT_D,
        placeholder_text="App-Specific Password (xxxx-xxxx-xxxx-xxxx)")
    if existing_app_pw:
        app_pw_entry.insert(0, existing_app_pw)
    app_pw_entry.pack(side='right', fill='x', expand=True, padx=(0, 8))

    def do_paste_app_pw():
        try:
            clip = app_pw_entry.clipboard_get()
        except Exception:
            messagebox.showwarning("تنبيه", "الحافظة فاضية — انسخ كلمة المرور أولاً، ثم اضغط لصق")
            return
        app_pw_entry.delete(0, 'end')
        app_pw_entry.insert(0, clip.strip())

    ctk.CTkButton(app_pw_row, text="📋 لصق", font=F(12, True), width=70, height=32,
        fg_color=BLUE, hover_color="#2980b9", text_color=WHITE,
        command=do_paste_app_pw).pack(side='left')

    ctk.CTkLabel(inner3,
        text="تحصل عليه من appleid.apple.com ← الأمان ← كلمات مرور خاصة بالتطبيق\n(مب كلمة مرور حسابك الأصلية)",
        font=F(10), text_color=TEXT_L, justify='right').pack(anchor='e', pady=(0, 10))

    cal_status_lbl = ctk.CTkLabel(inner3, text="", font=F(11, True),
        text_color=ACCENT2, justify='right')
    cal_status_lbl.pack(anchor='e', pady=(0, 8))

    def refresh_cal_status():
        aid, apw = load_icloud_credentials()
        if aid and apw:
            cal_status_lbl.configure(text=f"✅ مربوط بحساب: {aid}")
        else:
            cal_status_lbl.configure(text="⚠️ لا يوجد حساب مربوط بعد")

    def do_save_icloud():
        aid = apple_id_entry.get().strip()
        apw = app_pw_entry.get().strip()
        if not aid or not apw:
            messagebox.showwarning("تنبيه", "يرجى تعبية البريد وكلمة المرور أولاً")
            return
        save_icloud_credentials(aid, apw)
        refresh_cal_status()
        messagebox.showinfo("✅ تم", "تم حفظ بيانات تقويم iCloud بنجاح")

    def do_test_icloud():
        cal_status_lbl.configure(text="⏳ جاري الاختبار...")
        inner3.update()
        ok, info = test_icloud_connection()
        if ok:
            messagebox.showinfo("✅ الاتصال يعمل", f"تم الاتصال بنجاح بتقويم: {info}")
        else:
            messagebox.showerror("❌ فشل الاتصال", f"تعذر الاتصال بـ iCloud:\n\n{info}")
        refresh_cal_status()

    row3 = ctk.CTkFrame(inner3, fg_color="transparent")
    row3.pack(fill='x')
    ctk.CTkButton(row3, text="💾 حفظ", font=F(12, True), width=90, height=36,
        fg_color=ACCENT, hover_color=ACCENT2, text_color=WHITE,
        command=do_save_icloud).pack(side='right')
    ctk.CTkButton(row3, text="🧪 اختبار", font=F(12, True), width=90, height=36,
        fg_color="#9b59b6", hover_color="#8e44ad", text_color=WHITE,
        command=do_test_icloud).pack(side='left')

    refresh_cal_status()

    # ===== بطاقة ثالثة: بيانات الخبير (الشق التخصصي + مكان المكتب) =====
    # الشق التخصصي يُستخدم بمحاضر الاستعانة، والمقر/الدور/المكتب/الجناح
    # يُستخدم بإخطارات الحكومة — كلها خصائص ثابتة بالخبير تُضاف مرة
    # واحدة، فجُمعت ببطاقة واحدة وزر حفظ موحّد.
    card2 = ctk.CTkFrame(content, fg_color=CARD, corner_radius=12,
        border_width=1, border_color=CARD_BD)
    card2.pack(fill='x', pady=(16, 4))

    inner2 = ctk.CTkFrame(card2, fg_color="transparent")
    inner2.pack(fill='x', padx=20, pady=18)

    ctk.CTkLabel(inner2, text="بيانات الخبير",
        font=F(13, True), text_color=TEXT_D).pack(anchor='e')
    ctk.CTkLabel(inner2,
        text="تُضاف مرة واحدة. الشق التخصصي يُستخدم بمحاضر الاستعانة، والمقر/الدور/المكتب/الجناح بإخطارات الحكومة",
        font=F(10), text_color=TEXT_L, justify='right').pack(anchor='e', pady=(2, 12))

    existing_specialty = load_specialty()
    existing_loc = load_location()

    def expert_field(label_text, placeholder, value=''):
        ctk.CTkLabel(inner2, text=label_text, font=F(11, True),
            text_color=TEXT_M).pack(anchor='e', pady=(6, 2))
        e = ctk.CTkEntry(inner2, font=F(13), justify='right',
            fg_color=WHITE, border_color=CARD_BD, text_color=TEXT_D,
            placeholder_text=placeholder)
        if value:
            e.insert(0, value)
        e.pack(fill='x')
        return e

    specialty_entry = expert_field(
        "الشق التخصصي", "مثال: حاسب آلي", existing_specialty)
    maqar_entry = expert_field(
        "المقر", "مثال: مبنى الإدارة العامة للخبراء - الرقعي", existing_loc.get('maqar', ''))
    dor_entry = expert_field("الدور", "مثال: الثاني", existing_loc.get('dor', ''))
    maktab_entry = expert_field("المكتب", "مثال: 12", existing_loc.get('maktab', ''))
    janah_entry = expert_field("الجناح", "مثال: ب", existing_loc.get('janah', ''))

    def do_save_expert():
        specialty = specialty_entry.get().strip()
        if specialty:
            save_specialty(specialty)
        save_location(
            maqar=maqar_entry.get().strip(),
            dor=dor_entry.get().strip(),
            maktab=maktab_entry.get().strip(),
            janah=janah_entry.get().strip(),
        )
        messagebox.showinfo("✅ تم", "تم حفظ بيانات الخبير بنجاح")

    ctk.CTkButton(inner2, text="💾 حفظ", font=F(12, True), width=90, height=36,
        fg_color=ACCENT, hover_color=ACCENT2, text_color=WHITE,
        command=do_save_expert).pack(anchor='e', pady=(14, 0))