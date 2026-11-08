# ===== first_session.py — محضر أول جلسة (أصالة + استعانة) =====
"""
يبني محضر أول جلسة للقضايا المتداولة — يفرّع تلقائيًا حسب نوع القضية
(case_data['case_type'])، اللي يُحدَّد تلقائيًا بـcase_info_window.py:

  - أصالة: تاريخ صدور الحكم والتاريخ المحدد لحضور الخصوم يُعبَّيان من
    قاعدة البيانات (مستخرجة من حكم الإحالة بالذكاء الاصطناعي).
  - استعانة: لا حكم إحالة من الأساس — اسم ونوع الخبير المستعين
    يُعبَّيان تلقائيًا (من سجل الحركة)، والشق التخصصي من إعدادات
    البرنامج الثابتة، ونص المأمورية يدوي دايمًا (لا AI حاليًا).

فلسفة "الزر الواحد" (تنطبق فقط على أصالة — الاستعانة فيها حقل يدوي
دائم وهو نص المأمورية، فما فيها مسار صامت بالكامل): لو كل البيانات
المطلوبة متوفرة تلقائيًا، يُصدَر المحضر مباشرة بدون عرض أي نافذة.

ثلاث حالات حسب الجلسة القادمة المضافة بالنظام لهذي القضية (تنطبق
على الحالتين أصالة واستعانة):
  - لا توجد جلسة قادمة: حقول الجلسة الجديدة فاضية يدوية بالكامل
    (وتُسجَّل فعليًا بالنظام عند الإصدار — نفس آلية "➕ إضافة جلسة").
  - جلسة قادمة عادية: نملأ يوم/تاريخ/ساعة الجلسة تلقائياً.
  - جلسة قادمة من نوع 'جلسة محكمة' (أو ساعتها 12:00): صيغة مختلفة
    تفترض ساعة حضور ثابتة 12:00م بدل ذكر يوم/تاريخ الجلسة الجديدة.
"""
import os
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime, timedelta

from config import SESSION_TYPES
from api import get_day_name, get_all_case_sessions, parse_case_info, insert_session, get_original_experts, session_exists
from mahdar import fill_mahdar
from dates import normalize_date
from ui import SmartDateEntry, SmartTimeEntry, get_experts
from expert_settings import load_specialty

SIDEBAR  = "#1e2535"
SIDEBAR2 = "#252f42"
BG       = "#f5f6fa"
CARD     = "#ffffff"
CARD_BD  = "#e8ecf0"
ACCENT   = "#2ecc71"
ACCENT2  = "#27ae60"
BLUE     = "#3498db"
RED      = "#c0392b"
TEXT_D   = "#1e2535"
TEXT_M   = "#5a6a80"
TEXT_L   = "#94a3b8"
WHITE    = "#ffffff"
FONT     = "Arial"

COURT_SESSION_CODE = SESSION_TYPES.get('جلسة محكمة', '150011')


def F(s, b=False):
    return (FONT, s, "bold") if b else (FONT, s)


def get_upcoming_session(cookies, caso_no, received_date=None):
    """
    يرجع أول جلسة بتاريخها بسجل هذي القضية بعد تاريخ الاستلام الحالي
    (received_date)، أو None إن لم توجد. يرجع dict: {'date': 'YYYY-MM-DD',
    'time': 'HH:MM', 'is_court_session': bool}

    ملاحظة مهمة: هذي الدالة لا تقارن بتاريخ اليوم إطلاقاً — محضر أول
    جلسة قد يُطبع متأخراً وبحلول وقت الطباعة قد تكون توجد عدة جلسات
    لاحقة بسجل القضية. "الجلسة القادمة" بسياق محضر أول جلسة تعني
    أول جلسة تاريخياً بالسجل (بعد الاستلام)، حتى لو تاريخها فعلياً بالماضي.

    استبعاد الإحالات القديمة: قد تحتوي القضية على جلسات من إحالة سابقة
    (اتحوّلت للخبير ثم رجعت). تلك الجلسات تسبق تاريخ الاستلام الحالي،
    فنستبعد أي جلسة تاريخها قبل received_date حتى لا تُلتقط كجلسة قادمة.
    لو ما توفّر received_date نرجع للسلوك القديم (أقدم جلسة مطلقاً).

    تُستبعد جلسات "فتح محضر" (الكود 150004) كليًا — تُضاف تلقائيًا
    بالنظام ولا يجب احتسابها جلسة فعلية.
    """
    OPEN_RECORD_CODE = SESSION_TYPES.get('فتح محضر', '150004')
    from config import IGNORED_SESSION_COLORS

    def parse_start_date(raw):
        try:
            return datetime.strptime(raw[:10], '%Y/%m/%d').date()
        except Exception:
            return None

    # عتبة الاستلام: نتجاهل الجلسات التي تسبقها (إحالة قديمة)
    recv_threshold = None
    if received_date:
        try:
            recv_threshold = datetime.strptime(received_date[:10], '%Y-%m-%d').date()
        except Exception:
            recv_threshold = None

    def is_open_record(s):
        """يتعرف على جلسة فتح محضر — اللون أثبت طريقة، النص والكود احتياطيان

        ⚠️ استثناء فوق اللون: جلسة المحكمة («جلسه محكمه» بسجل الحركة) هي
        **جلسة حقيقية تُحسب** — لأن نظام الوزارة يعطي «فتح محضر» و«جلسه
        محكمه» نفس اللون (#27659a)، فاللون لحاله ما يفرّق بينهم. النوع
        (_kind) جاي من سجل الحركة وهو المرجع.
        """
        if (s.get('_kind') or '') == 'court':
            return False
        color = (s.get('backgroundColor') or '').strip().lower()
        if color in {c.lower() for c in IGNORED_SESSION_COLORS}:
            return True
        title = (s.get('title', '') or '').strip()
        sid = str(s.get('id', ''))
        return 'فتح محضر' in title or OPEN_RECORD_CODE in sid

    try:
        sessions = get_all_case_sessions(cookies, caso_no)
        all_dated = []
        for s in sessions:
            if is_open_record(s):
                continue  # تجاهل كليًا
            d = parse_start_date(s.get('start', ''))
            if d is None:
                continue
            # استبعاد جلسات الإحالة القديمة (قبل تاريخ الاستلام الحالي)
            if recv_threshold is not None and d < recv_threshold:
                continue
            all_dated.append((d, s))

        if not all_dated:
            return None
        all_dated.sort(key=lambda pair: pair[0])
        earliest = all_dated[0][1]
        start = earliest.get('start', '')
        date_part = start[:10]
        time_part = start[11:16] if len(start) >= 16 else ''

        is_court = False
        if time_part.startswith('12:'):
            is_court = True
        # سجل الحركة هو المرجع: «جلسه محكمه» → جلسة محكمة (حتى لو وقتها
        # اتزحزح لـ12:01 بسبب تعارض، أو 10:30 لو المحكمة حجزتوقت ثاني).
        if (earliest.get('_kind') or '') == 'court':
            is_court = True
        title = earliest.get('title', '') or ''
        if 'جلسة محكمة' in title or COURT_SESSION_CODE in str(earliest.get('id', '')):
            is_court = True

        return {'date': date_part, 'time': time_part, 'is_court_session': is_court}
    except Exception:
        return None


def find_open_record_session(cookies, caso_no, received_date=None):
    """
    يبحث عن جلسة 'فتح محضر' مباشرة من سجل الحركة (ECS_CASE_FLOW) —
    مو من لون الجلسة بتقويم load.php. ثبت إن الاعتماد على اللون غير
    موثوق (نفس اللون ممكن يظهر على 'جلسة محكمة' أيضاً)، بينما النص
    الصريح بسجل الحركة ('فتح محضر' حرفياً) موثوق 100%.

    يرجع {'date': 'YYYY/MM/DD', 'time': 'HH:MM'} لأقدم جلسة فتح محضر
    مسجّلة (لو فيه أكثر من عضو لجنة كل واحد له سطر منفصل، ناخذ
    الأقدم تاريخياً — كلهم بنفس التاريخ والوقت أصلاً بالحالات
    الطبيعية)، أو None لو ما فيه فتح محضر مسجّل أصلاً.
    """
    import re
    import requests
    from config import BASE_URL
    try:
        r = requests.post(f"{BASE_URL}/ECS_CASE_FLOW",
            data={'P_CASES': caso_no}, cookies=cookies, verify=False)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', r.text, re.DOTALL)
        tds = [re.sub(r'<[^>]+>', '', t).strip() for t in tds]
        tds = [t for t in tds if t.strip()]

        found = []
        for i, td in enumerate(tds):
            if td.strip() != 'فتح محضر':
                continue
            if i + 2 >= len(tds):
                continue
            date_raw = tds[i + 1].strip()
            time_raw = tds[i + 2].strip()
            if not re.match(r'^\d{2}/\d{2}/\d{4}$', date_raw):
                continue
            if not re.match(r'^\d{2}:\d{2}$', time_raw):
                continue
            found.append((date_raw, time_raw))

        if not found:
            return None

        def pd(d):
            try:
                p = d.split('/')
                return (int(p[2]), int(p[1]), int(p[0]))
            except Exception:
                return (9999, 12, 31)

        # قد تحتوي القضية على أكثر من جلسة 'فتح محضر' (إحالات/إعادات
        # سابقة). المباشرة الصحيحة هي فتح المحضر الأقرب لتاريخ الاستلام
        # الحالي (received_date)، مب الأقدم مطلقاً. لو ما توفّر تاريخ
        # الاستلام نرجع للأقدم (السلوك القديم) كخط دفاع.
        chosen = None
        if received_date:
            try:
                # received_date يأتي بصيغة YYYY-MM-DD
                ry, rm, rd = [int(x) for x in received_date.split('-')]
                r_ord = datetime(ry, rm, rd).toordinal()

                def dist(item):
                    y, m, d = pd(item[0])
                    try:
                        return abs(datetime(y, m, d).toordinal() - r_ord)
                    except Exception:
                        return 10 ** 9
                chosen = min(found, key=dist)
            except Exception:
                chosen = None

        if chosen is None:
            found.sort(key=lambda x: pd(x[0]))
            chosen = found[0]

        d, t = chosen
        dd, mm, yyyy = d.split('/')
        return {'date': f"{yyyy}/{mm}/{dd}", 'time': t}
    except Exception:
        return None


def compute_closing_time(opening_time_str):
    """يحسب ساعة إقفال المحضر = ساعة الفتح + 10 دقائق، نفس صيغة HH:MM"""
    try:
        t = datetime.strptime(opening_time_str.strip(), '%H:%M')
        closing = t + timedelta(minutes=10)
        return closing.strftime('%H:%M')
    except Exception:
        return ''


def format_date_display(date_str):
    """يعرض التاريخ بصيغة DD/MM/YYYY مهما كانت صيغته الأصلية"""
    return normalize_date(date_str)


def _time_period(time_str):
    """يحدد صباحاً/مساءً من وقت بصيغة HH:MM (24 ساعة)"""
    try:
        h = int(time_str.split(':')[0])
        return 'صباحاً' if h < 12 else 'مساءً'
    except Exception:
        return ''


def build_mission_text(judgment_date, hearing_date, opening_time,
                        received_date=None, new_date_raw=None, new_time=None):
    """
    يبني نص 'وبوشرت المهمة المطلوبة' بإحدى صيغتين:

    1. تاريخ المحكمة لاحق لتاريخ الاستلام (أو received_date غير محدد):
       → "وحيث لم تحدد المحكمة ساعة حضور... 12:00م"
       (المحكمة حددت تاريخاً مستقبلياً بدون ساعة)

    2. تاريخ المحكمة سابق لتاريخ الاستلام:
       → "وحيث أن التاريخ المذكور سابق... جلسة أخرى"
       (وصل الملف بعد التاريخ المحدد، الخبرة تحدد موعداً جديداً)
    """
    if not judgment_date or not hearing_date:
        return None

    closing_time = compute_closing_time(opening_time)
    closing_period = _time_period(closing_time)
    intro = (
        f"استلمنا ملف الدعوى بتاريخه وساعته واطلعنا على ما جاء به من أوراق ومستندات "
        f"وذلك لتنفيذ المأمورية الواردة بالحكم الصادر بجلسة {judgment_date} "
        f"والذي حددت به هيئة المحكمة جلسة {hearing_date} لحضور الطرفين أمام الخبرة"
    )

    # نقارن تاريخ المحكمة بتاريخ الاستلام لتحديد الحالة
    hearing_is_past = False
    if received_date:
        try:
            h = datetime.strptime(hearing_date.strip(), '%d/%m/%Y').date()
            r = datetime.strptime(received_date.strip(), '%d/%m/%Y').date()
            hearing_is_past = h < r
        except Exception:
            pass

    if not hearing_is_past:
        # الحالة 1: التاريخ لاحق — المحكمة لم تحدد ساعة
        return (
            f"{intro}، "
            f"وحيث لم تحدد المحكمة ساعة حضور الطرفين أمام الخبرة، فقد قررت الخبرة أن تكون "
            f"ساعة الحضور هي 12:00م، وأقفل المحضر بتاريخه بتمام الساعة "
            f"{closing_time} {closing_period}."
        )

    # الحالة 2: التاريخ سابق — نحدد جلسة جديدة
    if not new_date_raw or not new_time:
        return None
    new_day = get_day_name(new_date_raw)
    new_date_display = normalize_date(new_date_raw)
    return (
        f"{intro} "
        f"وحيث أن التاريخ المذكور سابق لتاريخ استلامنا لملف الدعوى فقد قررت الخبرة "
        f"تحديد جلسة أخرى لحضورهم وذلك في يوم {new_day} الموافق {new_date_display} الساعة {new_time} "
        f"وستقوم الخبرة بإخطارهم بالموعد الجديد وأقفل المحضر بتاريخه بتمام الساعة "
        f"{closing_time} {closing_period}."
    )


def build_secondment_mission_text(original_names, original_type, specialty, mission_text,
                                   opening_time, date_specified, session_date_raw,
                                   session_time=None):
    """
    يبني نص مهمة محضر الاستعانة.

    original_names: قائمة أسماء الخبير/اللجنة الأصلية (صاحبة القضية،
    اللي استعانت بنا) — مستخرجة من get_original_experts.
    original_type: نوع الخبير الأصيل (الهندسي/الحسابي).

    الصياغة:
    - خبير واحد: 'السيد الخبير (الهندسي) / اسمه'
    - لجنة: 'السادة الخبراء الهندسيين: اسم1، اسم2، اسم3'
    """
    if not original_names or not session_date_raw or not session_time:
        return None

    closing_time = compute_closing_time(opening_time)
    closing_period = _time_period(closing_time)
    mission_display = mission_text.strip() if mission_text else ""

    # بناء صيغة الخبير الأصيل
    type_label = original_type or ''
    if len(original_names) == 1:
        expert_ref = f"السيد الخبير ({type_label}) / {original_names[0]}"
    else:
        names_str = '،  '.join(original_names)
        # الهندسي → الهندسيين، الحسابي → الحسابيين
        type_plural = type_label.replace('الهندسي', 'الهندسيين').replace('الحسابي', 'الحسابيين')
        expert_ref = f"السادة الخبراء {type_plural}: {names_str}"

    intro = (
        f"استلمنا بتاريخ اليوم ملف طلب الاستعانة الوارد إلينا من {expert_ref}، "
        f"وذلك لتنفيذ الشق ({specialty}) "
        f"من المأمورية، والتي نصها: ({mission_display})."
    )

    session_day = get_day_name(session_date_raw)
    session_date_display = normalize_date(session_date_raw)

    if date_specified:
        body_text = (
            f"وبعد الاطلاع على ملف الاستعانة ومرفقاته، تقرر مباشرة أعمال المأمورية "
            f"في حدود الشق الفني المطلوب، وقد حدد الخبير المستعان بنا جلسة يوم "
            f"{session_day} الموافق {session_date_display} الساعة {session_time} موعداً "
            f"لحضور أطراف النزاع أمامنا، مع تكليفهم بتقديم ما لديهم من مستندات "
            f"أو بيانات أو مذكرات يرون الاستناد إليها بما يخدم تنفيذ المأمورية، "
            f"وأقفل المحضر بتاريخه في تمام الساعة {closing_time} {closing_period}."
        )
    else:
        body_text = (
            f"وتقرر مباشرة أعمال المأمورية في حدود الشق الفني المطلوب، وحيث لم "
            f"يحدد الخبير المستعان بنا أي جلسة، فقد قررت الخبرة تحديد جلسة يوم "
            f"{session_day} الموافق {session_date_display} الساعة {session_time} "
            f"موعداً لحضور أطراف النزاع أمامنا، مع تكليفهم بتقديم ما لديهم من "
            f"مستندات أو بيانات أو مذكرات يرون الاستناد إليها بما يخدم تنفيذ "
            f"المأمورية، وأقفل المحضر بتاريخه في تمام الساعة "
            f"{closing_time} {closing_period}."
        )

    return f"{intro}\n{body_text}"


def insert_session_no_conflict(cookies, caso_no, date_raw, time_str, type_code,
                                on_conflict_note=None):
    """
    يسجّل جلسة بالنظام مع تفادي تعارض التوقيت تلقائيًا: لو رجّع النظام
    كود تعارض ('3') أو تداخل حجز ('4') يزيد دقيقة ويعيد المحاولة (حتى 60
    محاولة). يرجع (result_code, final_time) — result_code '1' يعني نجح.

    on_conflict_note: دالة اختيارية تُستدعى مرة واحدة عند أول تعارض
    (لعرض تنبيه للمستخدم بوجود جلسة بنفس الوقت).
    """
    try_time = time_str
    noted = False
    result = None
    for _ in range(60):
        try:
            result = insert_session(cookies, caso_no, date_raw, try_time, type_code)
        except Exception:
            result = None
        if result == '1':
            return '1', try_time
        if result in ('3', '4'):
            if not noted and on_conflict_note:
                try:
                    on_conflict_note()
                except Exception:
                    pass
                noted = True
            t = datetime.strptime(try_time, '%H:%M') + timedelta(minutes=1)
            try_time = t.strftime('%H:%M')
            continue
        break  # خطأ آخر (عام/إجازة/أقل من 7 أيام) — نتوقف
    return result, try_time


class NextSessionDialog(ctk.CTkToplevel):
    """
    نافذة مختصرة لإدخال الجلسة القادمة (تاريخ + وقت)، مع خيار اختياري
    'محددة من الخبير الأصلي' لقضايا الاستعانة. تُستخدم قبل فتح المحضر
    عندما لا توجد جلسة قادمة مضافة بالنظام. تُعيد النتيجة عبر callback
    on_submit(date_raw, time_str, by_original) أو تُقفل بلا شيء عند الإلغاء.
    """
    def __init__(self, parent, caso_no, case_name, is_secondment,
                 on_submit, default_time="10:30"):
        super().__init__(parent)
        self.on_submit = on_submit
        self._submitted = False
        self.title("إضافة الجلسة القادمة")
        self.geometry("460x330" if is_secondment else "460x290")
        self.configure(fg_color=BG)
        self.grab_set()
        self.resizable(False, False)

        hdr = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0, height=56)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="إضافة الجلسة القادمة",
            font=F(15, True), text_color=WHITE).place(relx=0.97, rely=0.5, anchor='e')
        ctk.CTkButton(hdr, text="✕", width=32, height=32,
            fg_color="transparent", hover_color=SIDEBAR2,
            text_color=TEXT_L, command=self.destroy).place(relx=0.03, rely=0.5, anchor='w')

        ref = ctk.CTkFrame(self, fg_color="#eaf4ff", corner_radius=8)
        ref.pack(fill='x', padx=20, pady=12)
        ctk.CTkLabel(ref, text=caso_no, font=F(11, True), text_color=BLUE).pack(side='right', padx=12, pady=8)
        ctk.CTkLabel(ref, text=(case_name or '')[:38], font=F(10), text_color=TEXT_M).pack(side='right', pady=8)

        note = ("حدد تاريخ ووقت الجلسة القادمة — ستُسجَّل بالنظام كجلسة "
                "مناقشة ثم يُفتح المحضر.")
        ctk.CTkLabel(self, text=note, font=F(10), text_color=TEXT_L,
            justify='right', wraplength=410).pack(anchor='e', padx=20, pady=(0, 6))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill='x', padx=20)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="التاريخ", font=F(10), text_color=TEXT_M, anchor='e'
            ).grid(row=0, column=1, sticky='e', pady=(6, 2), padx=5)
        self.de = SmartDateEntry(form)
        self.de.grid(row=1, column=1, sticky='ew', padx=5, pady=2)

        ctk.CTkLabel(form, text="التوقيت", font=F(10), text_color=TEXT_M, anchor='e'
            ).grid(row=0, column=0, sticky='e', pady=(6, 2), padx=5)
        self.te = SmartTimeEntry(form)
        self.te.set(default_time)
        self.te.grid(row=1, column=0, sticky='ew', padx=5, pady=2)

        self.by_original_var = None
        if is_secondment:
            self.by_original_var = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(self, text="محددة من الخبير الأصلي",
                variable=self.by_original_var, font=F(12),
                text_color=TEXT_D, fg_color=ACCENT, hover_color=ACCENT2,
                checkbox_width=22, checkbox_height=22
            ).pack(anchor='e', padx=22, pady=(12, 0))

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(fill='x', padx=20, pady=16, side='bottom')
        ctk.CTkButton(bf, text="إلغاء", font=F(11),
            fg_color="transparent", border_width=1, border_color=CARD_BD,
            text_color=TEXT_M, hover_color="#eef0f5",
            command=self.destroy).pack(side='left')
        ctk.CTkButton(bf, text="💾  إضافة وفتح المحضر", font=F(11, True),
            fg_color=ACCENT, hover_color=ACCENT2, text_color=WHITE,
            command=self._submit).pack(side='right')
        self.de.focus()

    def _submit(self):
        dv = self.de.get().strip()
        tv = self.te.get().strip()
        if not dv:
            messagebox.showwarning("تنبيه", "يرجى إدخال التاريخ"); return
        if not tv:
            messagebox.showwarning("تنبيه", "يرجى إدخال التوقيت"); return
        by_original = bool(self.by_original_var.get()) if self.by_original_var else False
        self._submitted = True
        self.destroy()
        self.on_submit(dv, tv, by_original)


class FirstSessionWindow(ctk.CTkToplevel):
    """نافذة محضر أول جلسة — تظهر فقط لو ناقص شي يحتاج إدخال يدوي"""

    def __init__(self, parent, cookies, current_user, caso_no, received_date,
                 opening_time='10:00', case_data=None):
        super().__init__(parent)
        self.withdraw()  # نخفيها فورًا — نقرر لاحقًا هل نعرضها أو لا

        self.cookies = cookies
        self.current_user = current_user
        self.caso_no = caso_no
        self.received_date = received_date
        self.opening_time = opening_time
        self.case_data = case_data or {}

        self.title("محضر أول جلسة")
        self.geometry("560x680")
        self.configure(fg_color=BG)

        self.open_record = find_open_record_session(
            self.cookies, self.caso_no, self.received_date)
        self.upcoming = get_upcoming_session(
            self.cookies, self.caso_no, self.received_date)
        self.is_secondment = self.case_data.get('case_type') == 'استعانة'
        # علم للاستعانة: هل الجلسة القادمة محددة من الخبير الأصلي؟
        # (يُضبط من نافذة الجلسة القادمة، ويُستخدم في اختيار صيغة النص)
        self.secondment_by_original = None

        # ── ضمان وجود جلسة قادمة (رقم 2) قبل التوليد ──
        # لو ما فيه جلسة قادمة مضافة بالنظام، نضيفها حسب الحالة:
        #   • استعانة → نافذة إدخال [تاريخ/وقت + محددة من الأصلي] → مناقشة
        #   • أصالة + تاريخ المحكمة بعد المباشرة → جلسة محكمة 12:00 بصمت
        #   • أصالة + تاريخ المحكمة قبل المباشرة (متأخرة) → نافذة [تاريخ/وقت] → مناقشة
        # لو فيه جلسة قادمة أصلاً، لا نضيف شيئًا (حارس ضد التكرار).
        if self.upcoming is None:
            handled = self._ensure_next_session()
            if handled == 'pending':
                # فُتحت نافذة إدخال — بقية المسار يكمل داخل الـcallback
                return

        self._route_after_upcoming()

    def _route_after_upcoming(self):
        """
        يقرر المسار بعد أن أصبحت self.upcoming محسومة (موجودة أو لا):
        مسار صامت لو كل بيانات الأصالة متوفرة، وإلا نافذة الإدخال الكاملة.
        """
        if self.is_secondment:
            can_auto = False
            judgment_date = hearing_date = ''
        else:
            judgment_date = self.case_data.get('judgment_date', '')
            hearing_date = self.case_data.get('hearing_date', '')
            can_auto = bool(judgment_date and hearing_date and self.upcoming)

        if can_auto:
            received_display = datetime.strptime(
                self.received_date, '%Y-%m-%d').strftime('%d/%m/%Y')
            new_date_raw = self.upcoming['date']
            new_time = self.upcoming['time']
            mission_text = build_mission_text(
                judgment_date, hearing_date, self.opening_time,
                received_date=received_display,
                new_date_raw=new_date_raw, new_time=new_time
            )
            self.after(50, lambda: self._finalize(mission_text, new_date_raw, new_time))
        else:
            self.deiconify()
            self.grab_set()
            self._build()

    def _hearing_is_past(self):
        """
        هل التاريخ المحدد من المحكمة سابق لتاريخ المباشرة (القضية وصلت
        متأخرة)؟ يُقارَن hearing_date بـ received_date. عند نقص أي منهما
        أو تعذّر التحويل يرجع None (حالة غير محسومة).
        """
        hearing_date = (self.case_data.get('hearing_date') or '').strip()
        if not hearing_date:
            return None
        try:
            h = datetime.strptime(hearing_date, '%d/%m/%Y').date()
            r = datetime.strptime(self.received_date, '%Y-%m-%d').date()
            return h < r
        except Exception:
            return None

    def _ensure_next_session(self):
        """
        يضمن وجود جلسة قادمة بالنظام قبل التوليد (تُستدعى فقط حين
        self.upcoming is None). يرجع:
          • 'court'   : أُضيفت جلسة محكمة 12:00 تلقائيًا (بصمت) — نكمل مباشرة
          • 'pending' : فُتحت نافذة إدخال — المتابعة داخل الـcallback
          • 'skip'    : تعذّر الحسم (بيانات ناقصة) — نكمل بالمسار اليدوي القديم
        """
        case_name = self.case_data.get('case_name') or self.caso_no

        # ── الاستعانة: دائمًا نافذة إدخال [تاريخ/وقت + محددة من الأصلي] ──
        if self.is_secondment:
            NextSessionDialog(
                self, self.caso_no, case_name, is_secondment=True,
                on_submit=self._on_next_session_submitted)
            return 'pending'

        # ── الأصالة: نحتاج تحديد الحالة بمقارنة التواريخ ──
        past = self._hearing_is_past()
        if past is None:
            # بيانات ناقصة — نرجع للنافذة الكاملة القديمة (خط دفاع أخير)
            return 'skip'

        if past:
            # وصلت متأخرة → الخبير يحدد الجلسة القادمة (مناقشة)
            NextSessionDialog(
                self, self.caso_no, case_name, is_secondment=False,
                on_submit=self._on_next_session_submitted)
            return 'pending'

        # وصلت قبل الموعد → جلسة محكمة 12:00 بصمت بتاريخ المحكمة
        hearing_date = self.case_data.get('hearing_date', '').strip()
        try:
            court_date_raw = datetime.strptime(hearing_date, '%d/%m/%Y').strftime('%Y/%m/%d')
        except Exception:
            return 'skip'

        # خط دفاع: لو الجلسة هذي مضافة أصلاً بالنظام (إعادة فتح/طباعة
        # محضر أول جلسة لنفس القضية)، ما نعيد إضافتها.
        if session_exists(self.cookies, self.caso_no, court_date_raw, '12:00'):
            self.upcoming = {'date': court_date_raw, 'time': '12:00', 'is_court_session': True}
            return 'court'

        result, final_time = insert_session_no_conflict(
            self.cookies, self.caso_no, court_date_raw, '12:00', COURT_SESSION_CODE)
        # نحدّث upcoming محليًا حتى لو رجع تحذير (المهم تُبنى صيغة النص)
        self.upcoming = {'date': court_date_raw, 'time': final_time,
                         'is_court_session': True}
        if result == '1':
            self._sync_calendar_silent(court_date_raw, final_time)
            self._sync_event_db_silent(court_date_raw, final_time, 'جلسة محكمة')
        return 'court'

    def _on_next_session_submitted(self, date_raw, time_str, by_original):
        """
        callback نافذة الجلسة القادمة: يسجّل الجلسة (مناقشة) مع تفادي
        التعارض، يعرض رسالة نجاح، ثم يكمل مسار التوليد.
        """
        discussion_code = SESSION_TYPES.get('مناقشة', next(iter(SESSION_TYPES.values())))

        # خط دفاع: نفس الفكرة — لو الجلسة هذي مضافة أصلاً بالنظام.
        if session_exists(self.cookies, self.caso_no, date_raw, time_str):
            self.upcoming = {'date': date_raw, 'time': time_str, 'is_court_session': False}
            self.secondment_by_original = by_original
            self._sync_calendar_silent(date_raw, time_str)
            self._sync_event_db_silent(date_raw, time_str, 'مناقشة')
            messagebox.showinfo("تم", "هذي الجلسة مضافة فعلاً بالنظام مسبقاً — ما راح نكررها.")
            return

        conflict_flag = {'hit': False}

        def note():
            conflict_flag['hit'] = True

        result, final_time = insert_session_no_conflict(
            self.cookies, self.caso_no, date_raw, time_str,
            discussion_code, on_conflict_note=note)

        if result == '1':
            self.upcoming = {'date': date_raw, 'time': final_time,
                             'is_court_session': False}
            self.secondment_by_original = by_original
            self._sync_calendar_silent(date_raw, final_time)
            self._sync_event_db_silent(date_raw, final_time, 'مناقشة')
            extra = ""
            if conflict_flag['hit']:
                extra = (f"\n\n⚠️ كانت هناك جلسة بنفس الوقت، فتم ضبط الوقت "
                         f"إلى {final_time} تلقائيًا.")
            messagebox.showinfo("✅ تم", f"تمت إضافة الجلسة القادمة بالنظام.{extra}")
        else:
            warnings = {
                '2': 'تعذر تسجيل الجلسة (خطأ عام).',
                '5': 'هذا اليوم إجازة بالنظام.',
                '6': 'يجب أن يكون التاريخ بعد 7 أيام على الأقل حسب قواعد النظام.',
            }
            msg = warnings.get(result, f'نتيجة غير متوقعة من النظام: {result}')
            messagebox.showwarning(
                "⚠️ تنبيه",
                f"{msg}\n\nسيُفتح المحضر، لكن راجع جدولة الجلسة يدويًا لو لزم.")
            # حتى مع التحذير، نضبط upcoming محليًا لبناء النص
            self.upcoming = {'date': date_raw, 'time': time_str,
                             'is_court_session': False}
            self.secondment_by_original = by_original

        self._route_after_upcoming()

    def _sync_calendar_silent(self, date_raw, time_str):
        """يضيف موعد الجلسة لتقويم iCloud لو الحساب مربوط (بصمت عند الفشل)"""
        try:
            from icloud_calendar import has_credentials, add_calendar_event
            if has_credentials():
                from api import get_case_parties_summary
                summary = get_case_parties_summary(self.caso_no, self.cookies, self.current_user)
                start_dt = datetime.strptime(f"{date_raw} {time_str}", "%Y/%m/%d %H:%M")
                add_calendar_event(f"{summary} - {self.caso_no}", start_dt)
        except Exception:
            pass

    def _sync_event_db_silent(self, date_raw, time_str, type_label):
        """يضيف الجلسة القادمة بجدول الاحداث بقاعدة ExpretDB.MDB (بصمت عند أي فشل)"""
        try:
            from db_writer import insert_event_record
            insert_event_record(self.caso_no, date_raw, time_str, type_label)
        except Exception:
            pass

    def _build(self):
        top = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0, height=60)
        top.pack(fill='x'); top.pack_propagate(False)
        ctk.CTkButton(top, text="✕", width=32, height=32,
            fg_color="transparent", hover_color=SIDEBAR2,
            text_color=TEXT_L, command=self.destroy
        ).place(relx=0.03, rely=0.5, anchor='w')
        ctk.CTkLabel(top, text=f"محضر أول جلسة — {self.caso_no}",
            font=F(15, True), text_color=WHITE
        ).place(relx=0.97, rely=0.5, anchor='e')

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill='both', expand=True, padx=20, pady=15)

        if self.is_secondment:
            self._build_secondment_fields(body)
        else:
            self._build_asala_fields(body)

        ctk.CTkFrame(body, fg_color=CARD_BD, height=1).pack(fill='x', pady=18)

        if self.upcoming:
            kind = "جلسة محكمة" if self.upcoming['is_court_session'] else "جلسة عادية"
            info_txt = (f"الجلسة القادمة المضافة بالنظام: {kind}\n"
                        f"{format_date_display(self.upcoming['date'])} "
                        f"الساعة {self.upcoming['time']}")
        else:
            info_txt = "⚠️ لا توجد جلسة قادمة مضافة بالنظام — يرجى وضع الجلسة القادمة بالنظام أولاً، أو تعبية حقولها يدويًا بالأسفل"

        ctk.CTkLabel(body, text=info_txt, font=F(11, True), text_color=RED,
            justify='right').pack(anchor='e', pady=(0, 14))

        # حقول الجلسة الجديدة تظهر دائماً — الحالة (سابق/لاحق) تُحدَّد
        # وقت الإصدار فعلياً بمقارنة تاريخ المحكمة بتاريخ الاستلام
        self.new_date_entry = None
        self.new_time_entry = None

        if not self.is_secondment:
            ctk.CTkLabel(body, text="تاريخ الجلسة الجديدة",
                font=F(12, True), text_color=TEXT_D).pack(anchor='e', pady=(4, 3))
            self.new_date_entry = SmartDateEntry(body,
                border_color=RED if self.upcoming else None,
                text_color=RED if self.upcoming else None)
            if self.upcoming:
                self.new_date_entry.set(self.upcoming['date'])
            self.new_date_entry.pack(anchor='e')

            ctk.CTkLabel(body, text="ساعة الجلسة الجديدة",
                font=F(12, True), text_color=TEXT_D).pack(anchor='e', pady=(10, 3))
            self.new_time_entry = SmartTimeEntry(body,
                border_color=RED if self.upcoming else None,
                text_color=RED if self.upcoming else None)
            if self.upcoming:
                self.new_time_entry.set(self.upcoming['time'])
            self.new_time_entry.pack(anchor='e')

        ctk.CTkButton(body, text="🖨  إصدار المحضر", font=F(13, True),
            fg_color=ACCENT, hover_color=ACCENT2, text_color=WHITE,
            width=220, height=42, corner_radius=10,
            command=self._generate_manual
        ).pack(anchor='e', pady=(24, 10))

    def _build_asala_fields(self, body):
        """حقول محضر أول جلسة لقضية أصالة (تاريخ الحكم + تاريخ حضور الخصوم)"""
        ctk.CTkLabel(body, text="تاريخ صدور الحكم (DD/MM/YYYY)",
            font=F(12, True), text_color=TEXT_D).pack(anchor='e', pady=(8, 3))
        self.judgment_date_entry = ctk.CTkEntry(body, font=F(13), width=220,
            justify='right', fg_color=WHITE, border_color=CARD_BD,
            text_color=TEXT_D, placeholder_text="مثال: 20/05/2025")
        if self.case_data.get('judgment_date'):
            self.judgment_date_entry.insert(0, self.case_data['judgment_date'])
        self.judgment_date_entry.pack(anchor='e')
        self.judgment_date_entry.bind('<FocusOut>', self._normalize_judgment_date)

        is_court_preview = self.upcoming and self.upcoming['is_court_session']
        hearing_label_text = "التاريخ المحدد من المحكمة لحضور الطرفين أمام الخبرة"
        if is_court_preview:
            hearing_label_text += "  (تلقائي = تاريخ الجلسة القادمة)"

        ctk.CTkLabel(body, text=hearing_label_text,
            font=F(12, True), text_color=TEXT_D).pack(anchor='e', pady=(14, 3))
        self.hearing_date_entry = ctk.CTkEntry(body, font=F(13), width=220,
            justify='right', fg_color=WHITE,
            border_color=RED if is_court_preview else CARD_BD,
            text_color=RED if is_court_preview else TEXT_D,
            placeholder_text="مثال: 17/06/2025")
        if is_court_preview:
            self.hearing_date_entry.insert(0, format_date_display(self.upcoming['date']))
            self.hearing_date_entry.configure(state='disabled')
        elif self.case_data.get('hearing_date'):
            self.hearing_date_entry.insert(0, self.case_data['hearing_date'])
        self.hearing_date_entry.pack(anchor='e')

    def _build_secondment_fields(self, body):
        """حقول محضر استعانة (اسم/نوع الخبير المستعين، الشق، نص المأمورية)"""
        ctk.CTkLabel(body, text="نوع الخبير المستعين (هندسي/حسابي)",
            font=F(12, True), text_color=TEXT_D).pack(anchor='e', pady=(8, 3))
        self.requesting_type_entry = ctk.CTkEntry(body, font=F(13), width=220,
            justify='right', fg_color=WHITE, border_color=RED, text_color=RED,
            placeholder_text="مثال: الحسابي")
        if self.case_data.get('requesting_expert_type'):
            self.requesting_type_entry.insert(0, self.case_data['requesting_expert_type'])
        self.requesting_type_entry.pack(anchor='e')

        ctk.CTkLabel(body, text="اسم الخبير المستعين (مُستخرج من سجل الحركة، عدّله لو غير دقيق)",
            font=F(12, True), text_color=TEXT_D).pack(anchor='e', pady=(10, 3))
        self.requesting_name_entry = ctk.CTkEntry(body, font=F(13), width=220,
            justify='right', fg_color=WHITE, border_color=RED, text_color=RED,
            placeholder_text="اسم الخبير")
        if self.case_data.get('requesting_expert_name'):
            self.requesting_name_entry.insert(0, self.case_data['requesting_expert_name'])
        self.requesting_name_entry.pack(anchor='e')

        ctk.CTkLabel(body, text="الشق التخصصي",
            font=F(12, True), text_color=TEXT_D).pack(anchor='e', pady=(10, 3))
        self.specialty_entry = ctk.CTkEntry(body, font=F(13), width=220,
            justify='right', fg_color=WHITE, border_color=CARD_BD, text_color=TEXT_D,
            placeholder_text="مثال: حاسب آلي")
        saved_specialty = load_specialty()
        if saved_specialty:
            self.specialty_entry.insert(0, saved_specialty)
        self.specialty_entry.pack(anchor='e')

        ctk.CTkLabel(body, text="نص المأمورية (يدوي — لا يوجد استخراج تلقائي حاليًا)",
            font=F(12, True), text_color=TEXT_D).pack(anchor='e', pady=(14, 3))
        self.mission_box = ctk.CTkTextbox(body, font=F(12), height=100,
            fg_color=WHITE, border_color=CARD_BD, border_width=1,
            text_color=TEXT_D, wrap='word')
        if self.case_data.get('mission_text'):
            self.mission_box.insert('1.0', self.case_data['mission_text'])
        self.mission_box.pack(fill='x')

    def _normalize_judgment_date(self, event=None):
        raw = self.judgment_date_entry.get()
        normalized = normalize_date(raw)
        if normalized != raw:
            self.judgment_date_entry.delete(0, 'end')
            self.judgment_date_entry.insert(0, normalized)

    def _generate_manual(self):
        """مسار الزر اليدوي — يقرأ من الحقول حسب النوع، يبني النص المناسب، ثم يُصدر"""
        new_date_raw = new_time = None
        if not self.is_secondment:
            new_date_raw = self.new_date_entry.get().strip()
            new_time = self.new_time_entry.get().strip()
            if not new_date_raw or not new_time:
                messagebox.showwarning("تنبيه", "يرجى إدخال تاريخ وساعة الجلسة الجديدة")
                return
        elif self.upcoming:
            # الاستعانة: تاريخ/وقت الجلسة القادمة من الجلسة المسجّلة بالنظام
            # (سواء كانت موجودة أصلاً أو أضفناها عبر نافذة الجلسة القادمة)
            new_date_raw = self.upcoming['date']
            new_time = self.upcoming['time']

        if self.is_secondment:
            requesting_type = self.requesting_type_entry.get().strip()
            specialty = self.specialty_entry.get().strip()
            mission_raw = self.mission_box.get('1.0', 'end').strip()

            orig = get_original_experts(self.cookies, self.caso_no)
            original_names = orig.get('names', [])
            original_type = requesting_type or orig.get('type_label', '')

            if not original_names:
                manual_name = self.requesting_name_entry.get().strip()
                if not manual_name:
                    messagebox.showwarning("تنبيه", "تعذر تحديد الخبير المستعين — يرجى إدخاله يدويًا")
                    return
                original_names = [manual_name]

            # صيغة النص: "حدد الخبير المستعان بنا" مقابل "قررت الخبرة".
            # لو مررنا عبر نافذة الجلسة القادمة نحترم اختيار الـcheckbox؛
            # وإلا نرجع للسلوك القديم (وجود جلسة قادمة = حددها الأصلي).
            if self.secondment_by_original is not None:
                date_specified = self.secondment_by_original
            else:
                date_specified = bool(self.upcoming)
            mission_text = build_secondment_mission_text(
                original_names, original_type, specialty, mission_raw,
                self.opening_time, date_specified, new_date_raw, new_time
            )
        else:
            judgment_date = self.judgment_date_entry.get().strip()
            hearing_date = self.hearing_date_entry.get().strip()
            if not judgment_date or not hearing_date:
                messagebox.showwarning("تنبيه", "يرجى إدخال تاريخ صدور الحكم والتاريخ المحدد من المحكمة")
                return
            received_display = datetime.strptime(
                self.received_date, '%Y-%m-%d').strftime('%d/%m/%Y')
            mission_text = build_mission_text(
                judgment_date, hearing_date, self.opening_time,
                received_date=received_display,
                new_date_raw=new_date_raw, new_time=new_time
            )

        if not mission_text:
            messagebox.showerror("خطأ", "تعذر بناء نص المهمة — تحقق من الحقول")
            return

        self._finalize(mission_text, new_date_raw, new_time)

    def _finalize(self, mission_text, new_date_raw=None, new_time=None):
        """
        يسجّل الجلسة بالنظام لو احتاج، يكتب الملف، يفتحه، ويقفل النافذة.
        يستقبل نص المهمة جاهزًا (بناه المستدعي عبر build_mission_text أو
        build_secondment_mission_text حسب النوع) — مشترك بين المسار
        التلقائي (بدون نافذة ظاهرة) والمسار اليدوي (بعد ضغط زر الإصدار).
        """
        if not mission_text:
            if self.state() == 'withdrawn':
                self.deiconify()
                self.grab_set()
                self._build()
            else:
                messagebox.showerror("خطأ", "تعذر بناء نص المهمة — تحقق من الحقول")
            return

        try:
            if not self.upcoming:
                # مسار احتياطي نادر: يُصل إليه فقط حين تعذّر حسم الجلسة
                # القادمة مسبقًا (بيانات ناقصة رجعتنا للنافذة الكاملة القديمة).
                # الحالات العادية تُضاف فيها الجلسة قبل الوصول هنا عبر
                # _ensure_next_session، فتكون self.upcoming مضبوطة دائمًا.
                type_code = SESSION_TYPES.get('مناقشة', next(iter(SESSION_TYPES.values())))
                if session_exists(self.cookies, self.caso_no, new_date_raw, new_time):
                    # مضافة أصلاً بالنظام — لا نكرر الإضافة
                    result = '1'
                else:
                    try:
                        result = insert_session(self.cookies, self.caso_no, new_date_raw, new_time, type_code)
                    except Exception:
                        result = None

                warnings = {
                    '2': 'تعذر تسجيل الجلسة الجديدة بالنظام (خطأ عام).',
                    '3': 'تعارض بالتوقيت مع جلسة أخرى بالنظام.',
                    '4': 'يوجد جلسة حجز بنفس الفترة بالنظام.',
                    '5': 'هذا اليوم إجازة بالنظام.',
                    '6': 'يجب أن يكون التاريخ بعد 7 أيام على الأقل من اليوم حسب قواعد النظام.',
                }
                if result in warnings:
                    messagebox.showwarning(
                        "⚠️ تنبيه بجدولة الجلسة",
                        f"{warnings[result]}\n\nسيُصدَر المحضر رغم ذلك، لكن يرجى "
                        f"إضافة الجلسة يدويًا من صفحة الجلسات لو لم تُسجَّل."
                    )
                elif result == '1':
                    # نجح التسجيل بالنظام — ندفع الموعد لتقويم iCloud لو
                    # الخبير مربوط حسابه. عدم الربط من الأساس يستحق
                    # تنبيهًا واضحًا (مب فشل شبكة عابر يُتجاهل بصمت)
                    try:
                        from icloud_calendar import has_credentials, add_calendar_event
                        if has_credentials():
                            from api import get_case_parties_summary
                            summary = get_case_parties_summary(self.caso_no, self.cookies, self.current_user)
                            start_dt = datetime.strptime(f"{new_date_raw} {new_time}", "%Y/%m/%d %H:%M")
                            add_calendar_event(f"{summary} - {self.caso_no}", start_dt)
                        else:
                            messagebox.showwarning(
                                "⚠️ تنبيه",
                                "لم تُضَف الجلسة لتقويم آيفونك — لا يوجد حساب "
                                "iCloud مربوط.\n\nاربط حسابك من صفحة الإعدادات "
                                "لتفعيل المزامنة التلقائية."
                            )
                    except Exception:
                        pass
                    self._sync_event_db_silent(new_date_raw, new_time, 'مناقشة')

            if self.winfo_exists():
                self.configure(cursor='wait')
                self.update()

            info = parse_case_info(self.caso_no, self.cookies, self.current_user)

            exps = get_experts(self.caso_no, self.cookies, self.current_user)
            if exps:
                chairs = [x for x in exps if x['role'] == 'رئيس لجنة']
                members = [x for x in exps if x['role'] != 'رئيس لجنة']
                if len(exps) == 1:
                    es = exps[0]['name']
                elif len(exps) >= 3 and chairs:
                    es = f"{members[0]['name']}  ،  {chairs[0]['name']}  ،  {members[1]['name'] if len(members) > 1 else ''}"
                else:
                    es = '  ،  '.join([x['name'] for x in exps])
            else:
                es = self.current_user

            def clean_spaces(n):
                return ' '.join(n.split())

            plaintiffs = self.case_data.get('plaintiffs') or info.get('plaintiffs', [])
            defendants = self.case_data.get('defendants') or info.get('defendants', [])
            court_case_number = self.case_data.get('court_case_number') or info.get('case_num', '')

            pl = [clean_spaces(p) for p in plaintiffs]
            pl_s = pl[0] if len(pl) == 1 else '\n'.join([f"{i+1}- {p}" for i, p in enumerate(pl)])
            df = [clean_spaces(d) for d in defendants]
            df_s = df[0] if len(df) == 1 else '\n'.join([f"{i+1}- {d}" for i, d in enumerate(df)])

            # تاريخ ووقت الجلسة الأولى الفعلي: من فتح المحضر المسجّل
            # بالنظام لو موجود مسبقاً، وإلا تاريخ الاستلام (ونسجّل
            # فتح محضر جديد بالنظام تلقائياً بعد شوي)
            if self.open_record and self.open_record.get('date'):
                session1_date_raw = self.open_record['date']
                session1_time = self.open_record['time'] or self.opening_time
                need_insert_open_record = False
            else:
                received_dt = datetime.strptime(self.received_date, '%Y-%m-%d')
                session1_date_raw = received_dt.strftime('%Y/%m/%d')
                session1_time = self.opening_time
                need_insert_open_record = True
                # خط دفاع أخير: find_open_record_session تبحث بسجل
                # الحركة وممكن تتأخر بالتحديث — نتأكد كمان من تقويم
                # الجلسات مباشرة قبل ما نضيف فتح محضر مكرر.
                if session_exists(self.cookies, self.caso_no, session1_date_raw, session1_time):
                    need_insert_open_record = False

            if need_insert_open_record:
                open_code = SESSION_TYPES.get('فتح محضر', '150004')
                try_time = session1_time
                for _ in range(60):
                    try:
                        res = insert_session(self.cookies, self.caso_no, session1_date_raw, try_time, open_code)
                    except Exception:
                        res = None
                    if res == '1':
                        session1_time = try_time
                        break
                    if res in ('3', '4'):
                        t = datetime.strptime(try_time, '%H:%M') + timedelta(minutes=1)
                        try_time = t.strftime('%H:%M')
                        continue
                    break  # خطأ ثاني (عام/إجازة/أقل من 7 أيام) — نتوقف بصمت ونكمل بنفس الموعد

            day_name = get_day_name(session1_date_raw)
            date_str = datetime.strptime(session1_date_raw, '%Y/%m/%d').strftime('%d/%m/%Y')

            data = {
                'رقم_المحضر': '1',
                'اليوم': day_name,
                'التاريخ': date_str,
                'رقم_الخبرة': self.caso_no,
                'الساعة': session1_time,
                'المحافظة': info.get('governorate', 'العاصمة'),
                'القسم': info.get('department', ''),
                'رقم_الدعوى': court_case_number,
                'الواردة_من': info.get('source', ''),
                'المرفوعة_من': pl_s,
                'المرفوعة_ضد': df_s,
                'الخبير': es,
                'نص_الحضور': 'لم يحضر أحد.',
                'نص_المهمة': mission_text,
            }

            from expert_settings import minute_path
            out_path = minute_path(self.caso_no, 1)          # «مستندات_النظام\محضر الخبرة رقم 1.docx»
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            fill_mahdar(out_path, data)

            if self.winfo_exists():
                self.configure(cursor='')
            os.startfile(out_path)
            self.destroy()

        except PermissionError:
            was_auto = self.state() == 'withdrawn'
            if self.winfo_exists():
                self.configure(cursor='')
            messagebox.showerror(
                "الملف مفتوح",
                "هذا الملف مفتوح حاليًا ببرنامج آخر (Word غالبًا).\n\n"
                "أغلق الملف أولاً، ثم حاول إصدار المحضر مرة ثانية."
            )
            if was_auto:
                self.destroy()  # نافذة المسار التلقائي بلا محتوى — نقفلها بدل تركها فاضية
        except Exception as e:
            was_auto = self.state() == 'withdrawn'
            if self.winfo_exists():
                self.configure(cursor='')
            messagebox.showerror("خطأ", f"تعذر إصدار المحضر:\n{e}")
            if was_auto:
                self.destroy()  # نافذة المسار التلقائي بلا محتوى — نقفلها بدل تركها فاضية


def open_first_session_window(parent, cookies, current_user, caso_no, received_date, case_data=None):
    """نقطة الدخول المستخدمة من pending_cases.py"""
    FirstSessionWindow(parent, cookies, current_user, caso_no, received_date, case_data=case_data)