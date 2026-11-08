# ===== referred_cases.py — القضايا المحالة للخبير (مباشرة / إعادة) =====
"""
صفحة القضايا المحالة: تعرض القضايا التي أحالها رئيس القسم للخبير عبر
'توزيع القضايا على الخبراء' (عادية) أو 'توزيع استعانة بخبير' (استعانة).
الخبير يختار قضية ثم:
  - 'مباشرة'  → يستلمها  (الإجراء 130004 — نفسه بالنوعين)
  - 'إعادة'   → يرفض استلامها فترجع لرئيس القسم:
                130006 للقضايا العادية، 140032 لقضايا الاستعانة

آلية الصفحة بالسيرفر (مستخرجة من exp_new_cases + mubashara_table_2.php):
  1. جلب الجدول: POST لـ /mubashara_table_2.php بـ {type_id}
     → يرجّع HTML جدول القضايا المحالة (12 عمود ثابت).
     type_id=130003 → القضايا العادية، type_id=130049 → قضايا الاستعانة
     (نوعان منفصلان تماماً، كل واحد يُطلب بطلب مستقل ويُدمَج بعدين).
  2. تنفيذ الإجراء: POST لـ /includes/insert_mubashara.php بـ:
       req_seq_array = JSON list لأرقام الإجراء (task_id) المختارة
       next_rqs_type = 130004 (مباشرة) أو 130006/140032 (إعادة، حسب النوع)
     الرد: نص '1' = نجح، غير ذلك = خطأ.

⚠️ المباشرة/الإعادة كتابة فعلية على السيرفر بالنيابة عن الخبير —
   كل عملية تمرّ بنافذة تأكيد صريحة تبيّن القضية + الإجراء قبل الإرسال.

✅ بنية الصف (12 عمود، مؤكدة من رد حقيقي لقضية عادية): السيرفر يرجّع
   خلايا <td> داخل <tbody> بدون وسم <tr> مفتوح فعلياً (HTML غير سليم
   يصلحه المتصفح تلقائياً) — لذلك نقسّم كل خلايا tbody لمجموعات كل
   وحدة 12 خلية بدل الاعتماد على <tr>. task_id يُلتقط من id الـ
   checkbox بالعمود الأول (من الـ JS: add_to_arr(task_id)).

⚠️ نقطة لسه غير مؤكدة: بنية صف قضية استعانة فعلية (لم تصل بعد —
   tbody النوع 130049 كان فاضياً وقت آخر فحص). نفترض نفس الـ 12 عمود
   لأن الـ thead مطابق تماماً للنوع العادي، لكن يُفضّل التحقق عند وصول
   أول قضية استعانة حقيقية.
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import requests
import re
import json
import os
import tempfile
import threading

from config import BASE_URL
import case_db
from documents import get_claim_for_case, claim_log, is_login_page, LoginPageError
from summarizer import summarize_claim_pdf, LOCAL_MARK
from toast_notification import show_toast

# رقم المستخدم (الخبير) — نفس الرقم المستخدم بكل روابط نظام الملف الآلي
USER_ID = "309"

# قيم نهائية تُخزَّن بـcase_summary بدل الملخص (لا تُعرض هنا؛ زر المتداولة يترجمها)
CLAIM_SENTINELS = ('NO_AUTOCASE', 'NO_CLAIM_DOC')

# نفس ألوان ui.py تماماً (نفس الهوية البصرية)
SIDEBAR  = "#1e2535"
SIDEBAR2 = "#252f42"
BG       = "#f5f6fa"
CARD     = "#ffffff"
CARD_BD  = "#e8ecf0"
ACCENT   = "#2ecc71"
ACCENT2  = "#27ae60"
BLUE     = "#3498db"
RED      = "#e74c3c"
RED2     = "#c0392b"
TEXT_D   = "#1e2535"
TEXT_M   = "#5a6a80"
TEXT_L   = "#94a3b8"
WHITE    = "#ffffff"
FONT     = "Arial"

# أكواد الإجراءات (من dropdown ALL_REP في الموقع)
REFERRED_LIST_TYPE          = "130003"   # توزيع القضايا على الخبراء (عادية)
SECONDMENT_LIST_TYPE        = "130049"   # توزيع استعانة بخبير (نوع منفصل)
ACTION_MUBASHARA            = "130004"   # مباشرة القضية (استلام — نفسه بالنوعين)
ACTION_RETURN               = "130006"   # اعادة لرئيس القسم — القضايا العادية
ACTION_RETURN_SECONDMENT    = "140032"   # اعادة استعانة بخبير لرئيس القسم

def F(s, b=False):
    return (FONT, s, "bold") if b else (FONT, s)


def get_referred_cases(cookies, type_id=REFERRED_LIST_TYPE, raise_errors=False):
    """
    يجيب القضايا المحالة للخبير عبر POST لـ mubashara_table_2.php.

    يرجع قائمة dicts، كل واحد يمثل صف قضية:
      {'task_id', 'caso_no', 'plaintiff', 'date', 'from_dept',
       'to_dept', 'from_emp', 'notes', 'autocase_no', 'req_no', 'raw'}

    الأعمدة الثابتة في الجدول (12 عمود بالترتيب):
      [0] مباشرة القضية (checkbox — منه نلتقط task_id)
      [1] الملف الآلي
      [2] تفاصيل
      [3] ملاحظات
      [4] إلى قسم
      [5] من موظف
      [6] من قسم
      [7] التاريخ
      [8] رقم الإجراء
      [9] الرقم الآلي
      [10] رقم الخبرة
      [11] المدعى

    raise_errors=True (يستخدمه فحص الكاش بالخلفية): أي فشل شبكة أو صفحة
    تسجيل دخول يرفع استثناء بدل ما يرجّع [] — عشان ما نفسّر "فشل الطلب"
    على إنه "كل القضايا اختفت" ونمسح الكاش بالغلط.
    """
    try:
        r = requests.post(f"{BASE_URL}/mubashara_table_2.php",
            data={'type_id': type_id}, cookies=cookies, verify=False, timeout=15)
        if raise_errors:
            r.raise_for_status()
            if is_login_page(r.text) and '<tbody' not in r.text:
                raise LoginPageError("جلسة منتهية — صفحة تسجيل دخول")

        # نعزل محتوى tbody فقط (تجنّب صفوف thead)
        body_match = re.search(r'<tbody[^>]*>(.*?)</tbody>', r.text, re.DOTALL)
        body_html = body_match.group(1) if body_match else r.text

        # ملاحظة مهمة: السيرفر يرجّع صفوف tbody بدون وسم <tr> مفتوح
        # فعلياً (HTML غير سليم — المتصفح يصلحه تلقائياً بعرضه، لكن
        # ما ينفع نعتمد على <tr> بالـ regex لأنه غير موجود بالخام).
        # الحل: نستخرج كل خلايا <td> مباشرة من tbody بدون المرور
        # بالصف، وبما إن الأعمدة ثابتة 12 (مؤكدة من رد حقيقي)، نقسّم
        # القائمة الكاملة لمجموعات كل وحدة منها 12 خلية بالترتيب.
        cells_raw_all = re.findall(r'<td[^>]*>(.*?)</td>', body_html, re.DOTALL)

        cases = []
        for i in range(0, len(cells_raw_all) - 11, 12):
            chunk_raw = cells_raw_all[i:i+12]
            cells = [re.sub(r'<[^>]+>', ' ', c) for c in chunk_raw]
            cells = [re.sub(r'\s+', ' ', c).replace('&nbsp;', ' ').strip() for c in cells]

            # task_id = id الـ checkbox بالخلية الأولى الخام (قبل تنظيفها)
            chk = re.search(r'<input[^>]*type=["\']?checkbox["\']?[^>]*>', chunk_raw[0], re.IGNORECASE)
            task_id = ''
            if chk:
                id_m = re.search(r'id=["\']?([^"\'\s>]+)', chk.group(0))
                if id_m:
                    task_id = id_m.group(1)
            # احتياطي: لو ما لقينا id بالـ checkbox، نستخدم رقم الإجراء (عمود 8)
            if not task_id:
                task_id = cells[8]

            # لو الصف كله فاضي (thead تسرّب أو صف زخرفي)، نتجاهله
            if not (cells[8] or cells[9] or cells[10]):
                continue

            cases.append({
                'task_id':     task_id,
                # cells[1] عمود زر 'الملف الآلي' (فاضي نصياً) — الرقم الآلي الفعلي بعمود [9]
                'autocase_no': cells[9] or cells[1],
                'notes':       cells[3],
                'to_dept':     cells[4],
                'from_emp':    cells[5],
                'from_dept':   cells[6],
                'date':        cells[7],
                'req_no':      cells[8],
                'caso_no':     cells[10],
                'plaintiff':   cells[11],
                'is_secondment': (type_id == SECONDMENT_LIST_TYPE),
                'raw':         cells,   # نحتفظ به للتشخيص عند أول قضية
            })

        return cases
    except Exception as e:
        print(f"get_referred_cases ERROR: {e}")
        if raise_errors:
            raise
        return []


def submit_action(cookies, task_ids, action_type):
    """
    يرسل المباشرة أو الإعادة للسيرفر (كتابة فعلية).

    task_ids: قائمة أرقام الإجراء (task_id) المختارة.
    action_type: ACTION_MUBASHARA أو ACTION_RETURN.

    يرجع (ok, message).
    """
    try:
        req_seq_array = json.dumps(task_ids)
        r = requests.post(f"{BASE_URL}/includes/insert_mubashara.php",
            data={'req_seq_array': req_seq_array, 'next_rqs_type': action_type},
            cookies=cookies, verify=False, timeout=15)
        body = (r.text or '').strip()
        if body == '1':
            return True, 'تم بنجاح'
        return False, f'رد السيرفر غير متوقع: {body[:200]}'
    except Exception as e:
        return False, str(e)


def build_referred_cases_page(parent, cookies, current_user):
    """
    يبني صفحة 'القضايا المحالة' داخل parent (نفس مكان بقية الصفحات).
    نفس الستايل البصري لصفحة الجلسات والمتداولة.
    """
    # الهيدر
    top = ctk.CTkFrame(parent, fg_color=WHITE, corner_radius=0, height=56,
        border_width=1, border_color=CARD_BD)
    top.pack(fill='x'); top.pack_propagate(False)

    ctk.CTkButton(top, text="↻  تحديث", font=F(11),
        fg_color="transparent", border_width=1, border_color=CARD_BD,
        text_color=TEXT_M, hover_color="#f0f4ff", width=100, height=36,
        command=lambda: load_cases()).pack(side='left', padx=15, pady=10)

    cnt_lbl = ctk.CTkLabel(top, text="", font=F(13, True), text_color=TEXT_D)
    cnt_lbl.pack(side='right', padx=20)

    # المحتوى
    content = ctk.CTkFrame(parent, fg_color="transparent")
    content.pack(fill='both', expand=True, padx=30, pady=22)

    ctk.CTkLabel(content, text="القضايا المحالة",
        font=F(24, True), text_color=TEXT_D).pack(anchor='e')
    ctk.CTkLabel(content, text="القضايا التي أحالها رئيس القسم — اختر مباشرة للاستلام أو إعادة للرفض",
        font=F(12), text_color=TEXT_L).pack(anchor='e', pady=(3, 16))

    scroll = ctk.CTkScrollableFrame(content, fg_color="transparent",
        scrollbar_button_color=CARD_BD, scrollbar_button_hover_color=TEXT_L)
    scroll.pack(fill='both', expand=True)

    # آخر قائمة معروضة فعليًا — مرجع المقارنة لفحص الخلفية
    shown = {'cases': None}

    def render(cases):
        shown['cases'] = cases
        for w in scroll.winfo_children():
            w.destroy()

        cnt_lbl.configure(text=f"عدد القضايا المحالة: {len(cases)}")
        if not cases:
            ctk.CTkLabel(scroll, text="لا توجد قضايا محالة حالياً",
                font=F(14), text_color=TEXT_L).pack(pady=60)
            return

        for case in cases:
            build_case_row(scroll, case, cookies, on_done=load_cases)

    def load_cases():
        """زر '↻ تحديث' اليدوي (وبعد مباشرة/إعادة) — force refresh يتجاوز الكاش
        تمامًا، نفس السلوك السابق بالضبط، ويحدّث الكاش بالنتيجة."""
        cnt_lbl.configure(text="جاري التحميل...")
        parent.update()
        try:
            regular = get_referred_cases(cookies, REFERRED_LIST_TYPE, raise_errors=True)
            secondment = get_referred_cases(cookies, SECONDMENT_LIST_TYPE, raise_errors=True)
        except Exception:
            # فشل شبكة/جلسة — نبقي العرض والكاش كما هم بدل ما نعرض قائمة فاضية
            cnt_lbl.configure(text="⚠️ تعذّر التحديث — تحقق من الاتصال")
            return
        save_referred_cache(current_user, regular, secondment)
        render(regular + secondment)

    def check_in_background():
        """
        فحص صامت بالخلفية (thread منفصل — الواجهة ما تتجمد): يجلب القائمة
        الفعلية ويقارنها بالمعروضة بمفتاح (task_id, caso_no). لو ما فيه
        تغيير: ما نلمس الواجهة إطلاقًا. لو فيه: نعيد العرض + Toast بسيط.
        أي فشل (شبكة/جلسة منتهية) يُتجاهل بصمت — الكاش يبقى كما هو.
        """
        def work():
            try:
                regular = get_referred_cases(cookies, REFERRED_LIST_TYPE, raise_errors=True)
                secondment = get_referred_cases(cookies, SECONDMENT_LIST_TYPE, raise_errors=True)
            except Exception:
                return
            fresh = regular + secondment

            def apply():
                try:
                    if not scroll.winfo_exists():
                        return
                except Exception:
                    return
                old = shown['cases'] or []
                save_referred_cache(current_user, regular, secondment)
                if cases_signature(fresh) == cases_signature(old) and shown['cases'] is not None:
                    return  # ما فيه أي تغيير — صفر لمس للواجهة
                render(fresh)
                added = cases_signature(fresh) - cases_signature(old)
                if added and shown_had_cache['v']:
                    try:
                        show_toast(parent.winfo_toplevel(), "تحديث القضايا المحالة",
                                   f"قضية جديدة محالة ({len(added)})" if len(added) > 1
                                   else "تحديث: قضية جديدة محالة", kind="success")
                    except Exception:
                        pass
            try:
                parent.after(0, apply)
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    # عند الفتح: الكاش فورًا (بدون أي انتظار شبكة)، ثم الفحص بالخلفية
    cached = load_referred_cache(current_user)
    shown_had_cache = {'v': cached is not None}
    if cached is not None:
        render(cached)
    else:
        # أول فتح على هذا الجهاز (ما فيه كاش) — رسالة انتظار بدون تجميد
        cnt_lbl.configure(text="جاري التحميل...")
    check_in_background()


def cases_signature(cases):
    """مفتاح مقارنة القائمة: مجموعة (task_id, caso_no) — مو مقارنة نصية
    كاملة للـdict (فيه حقل raw ونصوص قد تتغير شكليًا بدون تغيير فعلي)."""
    return {(c.get('task_id', ''), c.get('caso_no', '')) for c in (cases or [])}


def load_referred_cache(current_user):
    """يرجّع القائمة المدمجة (عادية + استعانة) من الكاش، أو None لو ما فيه
    كاش لأي من النوعين بعد."""
    try:
        regular = case_db.get_referred_cache(current_user, REFERRED_LIST_TYPE)
        secondment = case_db.get_referred_cache(current_user, SECONDMENT_LIST_TYPE)
    except Exception:
        return None
    if regular is None and secondment is None:
        return None
    return (regular or []) + (secondment or [])


def save_referred_cache(current_user, regular, secondment):
    try:
        case_db.save_referred_cache(current_user, REFERRED_LIST_TYPE, regular)
        case_db.save_referred_cache(current_user, SECONDMENT_LIST_TYPE, secondment)
    except Exception:
        pass


def build_case_row(scroll, case, cookies, on_done=None):
    """بطاقة قضية محالة واحدة + زرّي مباشرة/إعادة (كلاهما بتأكيد صريح).
    قضايا الاستعانة (is_secondment=True) تُميَّز بخلفية وردية فاتحة —
    نفس الهوية البصرية المستخدمة بصفحة القضايا المتداولة."""
    SECONDMENT_BG = "#fdf2f6"  # وردي فاتح جداً — يميّز الاستعانة فقط
    is_secondment = case.get('is_secondment', False)
    row_bg = SECONDMENT_BG if is_secondment else CARD

    row = ctk.CTkFrame(scroll, fg_color=row_bg, corner_radius=12,
        border_width=1, border_color=CARD_BD)
    row.pack(fill='x', pady=5, padx=4)

    # صف 1: رقم القضية + المدعى (يمين) + التاريخ (يسار)
    r1 = ctk.CTkFrame(row, fg_color="transparent")
    r1.pack(fill='x', padx=18, pady=(14, 0))

    title = case['caso_no']
    if case['plaintiff']:
        title += f"  ·  {case['plaintiff'][:45]}"
    if is_secondment:
        title += "  ·  🔷 استعانة"
    ctk.CTkLabel(r1, text=title, font=F(15, True),
        text_color=TEXT_D, anchor='e').pack(side='right')

    if case['date']:
        ctk.CTkLabel(r1, text=f"تاريخ الإحالة: {case['date']}",
            font=F(12, True), text_color=TEXT_D).pack(side='left')

    # صف 2: تفاصيل الإحالة (من قسم / من موظف / ملاحظات)
    meta_bits = []
    if case['from_dept']:
        meta_bits.append(f"من قسم: {case['from_dept']}")
    if case['from_emp']:
        meta_bits.append(f"من موظف: {case['from_emp']}")
    if case['notes']:
        meta_bits.append(f"ملاحظات: {case['notes']}")
    if meta_bits:
        ctk.CTkLabel(row, text="   |   ".join(meta_bits),
            font=F(11), text_color=TEXT_M, anchor='e', justify='right'
            ).pack(fill='x', padx=18, pady=(6, 0))

    # صف ملخص الدعوى (ميزة إضافية): سطر ثانوي تحت سطر التفاصيل مباشرة،
    # بنفس ستايله وإزاحته. يُبنى بعد باقي الصف ولا يوقف الأزرار أبداً.
    add_claim_summary_line(row, case, cookies)

    # صف 3: زرّا الإجراء — كود الإعادة يختلف حسب نوع القضية
    return_action = ACTION_RETURN_SECONDMENT if is_secondment else ACTION_RETURN
    return_label = "إعادة استعانة لرئيس القسم" if is_secondment else "إعادة لرئيس القسم"

    r3 = ctk.CTkFrame(row, fg_color="transparent")
    r3.pack(fill='x', padx=18, pady=(10, 14))

    ctk.CTkButton(r3, text="✔  مباشرة (استلام)", font=F(12, True),
        width=160, height=36, fg_color=ACCENT, hover_color=ACCENT2,
        text_color=WHITE, corner_radius=8,
        command=lambda: confirm_and_submit(
            scroll, case, cookies, ACTION_MUBASHARA, "مباشرة", on_done)
    ).pack(side='left')

    ctk.CTkButton(r3, text=f"↩  {return_label}", font=F(12, True),
        width=190, height=36, fg_color=RED, hover_color=RED2,
        text_color=WHITE, corner_radius=8,
        command=lambda: confirm_and_submit(
            scroll, case, cookies, return_action, return_label, on_done)
    ).pack(side='left', padx=(10, 0))


def claim_summary_initial(case):
    """
    الحالة الأولية لسطر الملخص (بدون شبكة): يرجع (حالة, نص)
      ('show', ملخص) — محفوظ مسبقاً، اعرضه فوراً
      ('skip', None) — نتيجة نهائية سابقة أو ما فيه autocase_no (يُحفظ NO_AUTOCASE)
      ('load', None) — يحتاج جلب بالخلفية (ينفَّذ fetch_claim_summary)
    """
    caso_no = case['caso_no']
    try:
        cached = (case_db.get_case(caso_no) or {}).get('case_summary', '')
    except Exception:
        cached = ''
    if cached in CLAIM_SENTINELS:
        return 'skip', None
    if cached.startswith(LOCAL_MARK):
        return 'load', cached   # ملخص محلي مؤقت: نعرضه ونعيد المحاولة بالذكاء بالخلفية
    if cached:
        return 'show', cached
    if not case.get('autocase_no', ''):
        try:
            case_db.save_case(caso_no, case_summary='NO_AUTOCASE')
        except Exception:
            pass
        return 'skip', None
    return 'load', None


def fetch_claim_summary(cookies, case):
    """
    (blocking — يُستدعى من خيط خلفي فقط) يجلب صحيفة الدعوى ويلخّصها ويحفظ.
    يرجع نص الملخص، أو None لو لازم يُخفى السطر. يحفظ NO_AUTOCASE /
    NO_CLAIM_DOC نهائياً، وأي فشل مؤقت (شبكة/صفحة دخول/Gemini) لا يحفظ شي.
    """
    caso_no = case['caso_no']
    autocase_no = case.get('autocase_no', '')
    path = None
    try:
        fd, path = tempfile.mkstemp(suffix='.pdf', prefix='claim_')
        os.close(fd)
        claim, saved, status = get_claim_for_case(cookies, autocase_no, USER_ID, path)
        if status in CLAIM_SENTINELS:
            case_db.save_case(caso_no, autocase_no=autocase_no, case_summary=status)
            return None
        summary, error = summarize_claim_pdf(saved)
        if error or not summary:
            claim_log(f"{caso_no}: فشل التلخيص — {error}")
            return None
        if not summary.startswith(LOCAL_MARK):   # المحلي لا يُحفظ ليُعاد لاحقاً بالذكاء
            try:
                case_db.save_case(caso_no, autocase_no=autocase_no, case_summary=summary)
            except Exception:
                pass
        return summary
    except Exception as e:
        claim_log(f"{caso_no} autocase={autocase_no}: فشل مؤقت — {type(e).__name__}: {e}")
        return None
    finally:
        if path:
            try:
                os.remove(path)
            except Exception:
                pass


def add_claim_summary_line(row, case, cookies):
    """سطر 'ملخص الدعوى' (نسخة customtkinter القديمة) — نفس المنطق المشترك أعلاه"""
    state, text = claim_summary_initial(case)
    if state == 'skip':
        return
    lbl = ctk.CTkLabel(row, text=(f"📄 {text}" if text else "⏳ جاري تحميل ملخص الدعوى..."),
        font=F(11), text_color=TEXT_M, anchor='e', justify='right')
    lbl.pack(fill='x', padx=18, pady=(4, 0))
    if state == 'show':
        return

    def work():
        summary = fetch_claim_summary(cookies, case)
        def apply():
            try:
                if summary:
                    lbl.configure(text=f"📄 {summary}")
                else:
                    lbl.destroy()
            except Exception:
                pass
        try:
            row.after(0, apply)
        except Exception:
            pass

    threading.Thread(target=work, daemon=True).start()


def confirm_and_submit(scroll, case, cookies, action_type, action_label, on_done):
    """
    نافذة تأكيد صريحة قبل أي كتابة على السيرفر — تبيّن القضية والإجراء.
    لا يُرسل أي POST إلا بعد ضغط المستخدم 'تأكيد'.
    """
    msg = (
        f"سيتم تنفيذ الإجراء التالي على نظام الخبراء:\n\n"
        f"القضية: {case['caso_no']}\n"
        f"المدعى: {case['plaintiff'] or '—'}\n"
        f"الإجراء: {action_label}\n\n"
    )
    if action_type in (ACTION_RETURN, ACTION_RETURN_SECONDMENT):
        msg += "⚠️ الإعادة ترفض استلام القضية وترجعها لرئيس القسم.\n\n"
    msg += "هل تريد المتابعة؟"

    if not messagebox.askyesno("تأكيد الإجراء", msg, icon='warning'):
        return

    try:
        scroll.winfo_toplevel().configure(cursor='watch')
        scroll.update()
    except Exception:
        pass

    ok, message = submit_action(cookies, [case['task_id']], action_type)

    try:
        scroll.winfo_toplevel().configure(cursor='')
    except Exception:
        pass

    if ok:
        messagebox.showinfo("✅ تم", f"تمت {action_label} للقضية {case['caso_no']} بنجاح")
        if on_done:
            on_done()  # نعيد تحميل القائمة (القضية اختفت من المحالة)
    else:
        messagebox.showerror("❌ فشل", f"تعذّر تنفيذ الإجراء:\n\n{message}")