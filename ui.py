# ===== ui.py — واجهة نظام جلسات الخبراء =====
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import requests, re, os
from datetime import datetime, timedelta

from config import SESSION_TYPES, BASE_URL, GOV_KEYWORDS
from api import get_day_name, get_sessions, get_all_case_sessions, parse_case_info, get_logged_in_name, compute_session_number
from mahdar import fill_mahdar
from gov_notice import fill_gov_notice
from weekly_report import build_weekly_report_html, _week_bounds, suggest_default_period
import case_db

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

# ===== الألوان — مطابقة للصورة =====
SIDEBAR  = "#1e2535"
SIDEBAR2 = "#252f42"
BG       = "#f5f6fa"
CARD     = "#ffffff"
CARD_BD  = "#e8ecf0"
ACCENT   = "#2ecc71"   # أخضر
ACCENT2  = "#27ae60"
BLUE     = "#3498db"
TEXT_D   = "#1e2535"
TEXT_M   = "#5a6a80"
TEXT_L   = "#94a3b8"
WHITE    = "#ffffff"
FONT     = "Arial"

# لون تمييز القضايا "بدون جلسة قادمة" (أحمر فاتح جداً — يلفت الانتباه
# بدون ما يكسر الهوية البصرية الحالية)
NO_UPCOMING_BG  = "#fdecea"
NO_UPCOMING_BD  = "#f5c6c6"
NO_UPCOMING_TXT = "#c0392b"

# حجم "وحدة" التمرير بالبكسل لكل نقرة عجلة ماوس — الافتراضي بـCTk
# صغير جدًا (يحتاج نقرات كثيرة لينزل شوي). نكبّره لتسريع التمرير.
SCROLL_PIXELS_PER_UNIT = 45

def F(s, b=False): return (FONT, s, "bold") if b else (FONT, s)
def short_name(n):
    p = [x for x in n.strip().split() if x]
    return f"{p[0]} {p[-1]}" if len(p) >= 2 else n.strip()

def clean_spaces(n):
    """يوحّد كل المسافات المتعددة بين كلمات الاسم إلى مسافة واحدة فقط"""
    return ' '.join(n.split())

def enable_universal_copy_paste(root):
    """
    يحل عطل شائع: النسخ/اللصق (Ctrl+C/V/X) ما يشتغل لو لوحة المفاتيح
    على وضع العربي. السبب: Tkinter يربط اختصارات النسخ الافتراضية
    بحرف keysym اللاتيني (c/v/x) — ولو تخطيط لوحة المفاتيح عربي، نفس
    المفتاح الفيزيائي ينتج keysym عربي مختلف تمامًا، فيفشل الربط
    الافتراضي بصمت (بدون أي رسالة خطأ).

    الحل: نراقب event.keycode (كود المفتاح الفيزيائي الخام من نظام
    ويندوز، ثابت دائمًا بكل تخطيطات اللوحة أيًا كانت اللغة) بدل
    keysym، ونطلق حدث Tk الافتراضي (<<Copy>>/<<Paste>>/<<Cut>>/
    <<SelectAll>>) يدويًا على العنصر اللي فيه التركيز حاليًا. هذي
    الأحداث الافتراضية موجودة أصلاً ببرمجة Entry/Textbox (تنسخ/تلصق
    صح لو انطلقت) — المشكلة كانت فقط بالمُطلِق (trigger) مو بالتنفيذ.

    يُستدعى مرة وحدة على النافذة الرئيسية (ExpertApp) — bind_all يغطي
    كل التطبيق تلقائيًا (كل الحقول بكل الشاشات والنوافذ الفرعية).
    """
    VK_COPY, VK_PASTE, VK_CUT, VK_SELECT_ALL = 67, 86, 88, 65  # C, V, X, A

    def _on_ctrl_key(event):
        if event.keycode == VK_COPY:
            seq = "<<Copy>>"
        elif event.keycode == VK_PASTE:
            seq = "<<Paste>>"
        elif event.keycode == VK_CUT:
            seq = "<<Cut>>"
        elif event.keycode == VK_SELECT_ALL:
            seq = "<<SelectAll>>"
        else:
            return None

        widget = root.focus_get()
        if widget is None:
            return None
        try:
            widget.event_generate(seq)
        except Exception:
            pass
        return "break"

    root.bind_all("<Control-KeyPress>", _on_ctrl_key)

def speed_up_scroll(scrollable_frame, pixels_per_unit=SCROLL_PIXELS_PER_UNIT):
    """
    يسرّع التمرير بعجلة الماوس داخل CTkScrollableFrame — بدون أي ربط
    أحداث إضافي (المحاولة الأولى بـbind_all كانت تتعارض مع ربط CTk
    الداخلي على نفس الحدث فيصير ازدواج/تذبذب بالتمرير — أسوأ من قبل).

    الطريقة الصحيحة والآمنة: CTk أصلاً يستخدم
    canvas.yview_scroll(n, "units") لكل نقرة عجلة — وحجم "الوحدة"
    محكوم بخاصية yscrollincrement بالقماشة نفسها (صغيرة جدًا افتراضيًا).
    نكبّر هذي الخاصية فقط، فتصير كل نقرة تحرّك مسافة أكبر تلقائيًا،
    بدون لمس أي ربط أحداث موجود أصلاً.
    """
    canvas = getattr(scrollable_frame, '_parent_canvas', None)
    if canvas is None:
        return
    canvas.configure(yscrollincrement=pixels_per_unit)

def detect_gov_parties(plaintiffs, defendants):
    """
    يكتشف كل الأطراف الحكومية بين أطراف الدعوى (مدعين + مدعى عليهم)،
    لأن الإخطار قد يُرسل لأكثر من جهة حكومية بنفس القضية. نرجّع
    قائمة بكل جهة تحتوي إحدى كلمات GOV_KEYWORDS المفتاحية، بعد
    تنظيف المسافات وإزالة 'بصفته/بصفتها/بصفتهم' وما بعدها من السطر
    (النموذج يريد اسم الجهة فقط بدون 'بصفته').

    لو ما فيه أي طرف حكومي، نرجّع قائمة فاضية — ويُترك حقل الجهة
    فاضيًا ليكتبه الخبير يدويًا. لو فيه أكثر من جهة، تُدرَج كلها
    ويمسح الخبير ما لا يريده.
    """
    gov = []
    for p in list(plaintiffs) + list(defendants):
        name = clean_spaces(p)
        if not name:
            continue
        if any(kw in name for kw in GOV_KEYWORDS):
            cut = name
            for marker in ['بصفته', 'بصفتها', 'بصفتهم', 'بصفتهما']:
                if marker in cut:
                    cut = cut.split(marker)[0].strip()
            # تنظيف أي أقواس/رموز/فواصل معلّقة في النهاية بعد القطع
            # (مثل '... والماء (' لما يكون الأصل '... والماء (بصفته)')
            cut = cut.strip(' \t([{«"\'-،,؛;:/\\')
            cut = clean_spaces(cut)
            if cut and cut not in gov:
                gov.append(cut)
    return gov

def get_experts(caso_no, cookies, current_user=''):
    """
    يجلب أعضاء اللجنة/الخبير المسؤول عن القضية حالياً من سجل الحركة.

    المنطق (مُصحَّح على بيانات حقيقية من جدول 'الإجراءات'): كل صف
    إجراء بالنظام مكوّن من 7 خلايا ثابتة الترتيب:
    [رقم الإجراء, تاريخ الإجراء, نوع الإجراء, من قسم, من موظف, إلى قسم,
    إلى موظف]. عمود 'إلى موظف' (إزاحة i+4 من خلية 'نوع الإجراء') هو
    العضو المُسنَد إليه فعليًا لكل 'توزيع للخبراء' — بغض النظر مين
    المحوِّل ('من موظف'). هذا نفس الإزاحة الموثوقة المستخدمة أصلاً
    بدالة get_case_type بهذا الملف.

    ⚠️ الطريقة القديمة (تجميع كل الأسماء بالكتلة وتخطي أول اسم بافتراض
    إنه المحوِّل) تنكسر لو المحوِّل أسند القضية لنفسه كعضو أول ضمن
    اللجنة (نفس الاسم بخانتي 'من موظف' و'إلى موظف' بنفس الصف) — يصير
    عندنا اسم مكرر يُحذف تلقائياً، فيختفي هذا العضو من نتيجة اللجنة.
    الاعتماد المباشر على 'إلى موظف' يتفادى هذي الحالة تمامًا لأننا ما
    نلمس عمود 'من موظف' إطلاقًا.

    نجمّع 'توزيع للخبراء' المتتالية بنفس تاريخ التوزيع في لجنة واحدة
    (كل عضو له صف/إجراء منفصل بنفس اليوم). الاستعانة تبقى بكتل مستقلة
    بدون تجميع لحد ما نراجعها لاحقًا.
    """
    try:
        import urllib3; urllib3.disable_warnings()
        r = requests.post(f"{BASE_URL}/ECS_CASE_FLOW",
            data={'P_CASES': caso_no}, cookies=cookies, verify=False)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', r.text, re.DOTALL)
        tds = [re.sub(r'<[^>]+>', '', t).strip() for t in tds]
        tds = [t for t in tds if t.strip()]

        skip = ['قسم', 'مراقبه', 'مراقبة', 'إدارة', 'مكتب', 'لا يوجد', '&nbsp']
        NORMAL_DIST     = 'توزيع للخبراء'
        SECONDMENT_DIST = 'توزيع استعانه بخبير على الخبراء'

        # نجمع (تاريخ، نوع، العضو المُسنَد فعليًا='إلى موظف') من كل صف
        entries = []
        for i, td in enumerate(tds):
            is_normal     = td.strip() == NORMAL_DIST
            is_secondment = td.strip() == SECONDMENT_DIST
            if not (is_normal or is_secondment) or i + 4 >= len(tds):
                continue

            date = tds[i - 1].strip() if i - 1 >= 0 else ''
            recipient = tds[i + 4].strip()
            if not recipient or len(recipient) <= 5:
                continue
            if any(x in recipient for x in skip) or recipient[0:1].isdigit():
                continue

            entries.append({
                'type': 'secondment' if is_secondment else 'normal',
                'name': recipient, 'date': date,
            })

        if not entries:
            return []

        # تجميع 'توزيع للخبراء' المتتالية بنفس التاريخ في لجنة واحدة
        clusters = []
        for e in entries:
            prev = clusters[-1] if clusters else None
            can_merge = (
                e['type'] == 'normal' and prev is not None
                and prev['type'] == 'normal'
                and e['date'] == prev['date']
            )
            if can_merge:
                if e['name'] not in prev['members']:
                    prev['members'].append(e['name'])
            else:
                clusters.append({
                    'type': e['type'], 'members': [e['name']], 'date': e['date'],
                })

        if not clusters:
            return []

        # نلقى آخر كتلة (لجنة) تحتوي اسم المستخدم الحالي
        target = None
        if current_user:
            cur_short = short_name(current_user)
            for c in reversed(clusters):
                if any(short_name(n) == cur_short for n in c['members']):
                    target = c
                    break

        # احتياطي: آخر كتلة بشكل عام
        if target is None:
            target = clusters[-1]

        result = []
        for i, n in enumerate(target['members']):
            sn = short_name(n)
            result.append({'name': sn, 'role': 'رئيس لجنة' if i == 0 else 'عضو لجنة'})
        return result
    except:
        return []


def get_case_type(cookies, caso_no, current_user=''):
    """
    يحدد نوع القضية للخبير الحالي تلقائيًا: 'استعانة' لو كان آخر
    توزيع له بسجل الحركة عبر 'توزيع استعانه بخبير على الخبراء'،
    أو 'أصالة' لو كان عبر 'توزيع للخبراء' العادي. نفس مصدر البيانات
    ومنطق get_experts بالضبط (إزاحة i+4 للاسم، ترتيب بالتاريخ
    الفعلي)، بس هنا نحتاج فقط نوع آخر توزيع مطابق للمستخدم الحالي،
    لا أعضاء اللجنة كاملة.

    يرجع نص فاضي '' لو تعذر التحديد (القضية جديدة بدون أي توزيع
    بعد، أو خطأ بالاتصال) — يُعامَل كـ'أصالة' افتراضيًا بالمستدعي.
    """
    try:
        r = requests.post(f"{BASE_URL}/ECS_CASE_FLOW",
            data={'P_CASES': caso_no}, cookies=cookies, verify=False)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', r.text, re.DOTALL)
        tds = [re.sub(r'<[^>]+>', '', t).strip() for t in tds]
        tds = [t for t in tds if t.strip()]
        skip = ['قسم','مراقبه','إدارة','مكتب','لا يوجد','&nbsp']

        cur_short = short_name(current_user) if current_user else ''
        entries = []  # (date, type, expert_name)
        for i, td in enumerate(tds):
            is_normal = td.strip() == 'توزيع للخبراء'
            is_secondment = td.strip() == 'توزيع استعانه بخبير على الخبراء'
            if (is_normal or is_secondment) and i >= 1 and i + 4 < len(tds):
                date = tds[i - 1]
                exp = tds[i + 4].strip()
                if len(exp) > 5 and not any(x in exp for x in skip) and not exp[0].isdigit():
                    entries.append((date, 'استعانة' if is_secondment else 'أصالة', exp))

        if not entries:
            return ''

        def pd(d):
            try:
                p = d.split('/')
                return (int(p[2]), int(p[1]), int(p[0]))
            except:
                return (0, 0, 0)

        entries.sort(key=lambda e: pd(e[0]))

        if cur_short:
            matching = [e for e in entries if short_name(e[2]) == cur_short]
            if matching:
                return matching[-1][1]
            return ''
        return entries[-1][1]
    except Exception:
        return ''


class SmartDateEntry(ctk.CTkFrame):
    def __init__(self, parent, border_color=None, text_color=None, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        self.var = tk.StringVar()
        self._pending = None
        self._after_id = None
        self.entry = ctk.CTkEntry(self, textvariable=self.var, font=F(13),
            width=170, justify="right", fg_color=WHITE,
            border_color=border_color or CARD_BD, text_color=text_color or TEXT_D,
            placeholder_text="التاريخ")
        self.entry.pack()
        self.entry.bind('<KeyRelease>', self._on_key)
        self.entry.bind('<Tab>', self._on_tab)
        self.entry.bind('<Return>', self._on_tab)
        self.entry.bind('<FocusIn>', lambda e: self.entry.select_range(0,'end'))
        self.entry.bind('<FocusOut>', self._focusout)

    def _parse(self, raw):
        raw = raw.strip()
        today = datetime.now(); y, m = today.year, today.month

        # أولوية أولى: لو فيه فاصل صريح (/ أو -) بين جزئين أو أكثر، نتعامل
        # معه كـ DD/MM[/YYYY] مباشرة — هذا يحل حالة كتابة تاريخ كامل بفاصل
        # (مثل '10/7' أو '10/7/2026') كان يفشل بصمت بالمنطق القديم (تجريد
        # الفواصل قبل الفحص كان يولّد عدد خانات غير متوقع، 6 أو 7 خانات،
        # ما تطابق أي حالة معالَجة بالأسفل).
        if '/' in raw or '-' in raw:
            parts = [p for p in re.split(r'[/\-]', raw) if p != '']
            if len(parts) >= 2 and all(p.isdigit() for p in parts):
                try:
                    day = int(parts[0])
                    mon = int(parts[1])
                    if not (1 <= day <= 31 and 1 <= mon <= 12):
                        return None
                    if len(parts) >= 3 and parts[2]:
                        yr = int(parts[2])
                        if yr < 100:
                            yr += 2000
                    else:
                        yr = y if (mon > m or (mon == m and day >= today.day)) else y + 1
                    datetime(yr, mon, day)  # تحقق من صلاحية التاريخ
                    return f"{yr}/{mon:02d}/{day:02d}"
                except Exception:
                    return None
            return None

        # بدون أي فاصل — رقم خام، نستخدم منطق الإكمال التلقائي بالأرقام
        d = raw
        if not d.isdigit(): return None
        try:
            if len(d)==1: return None
            elif len(d)==2:
                day=int(d)
                if not 1<=day<=31: return None
                if day>=today.day: return datetime(y,m,day).strftime('%Y/%m/%d')
                nm=m+1 if m<12 else 1; ny=y if m<12 else y+1
                return datetime(ny,nm,day).strftime('%Y/%m/%d')
            elif len(d)==3:
                day,mon=int(d[:2]),int(d[2])
                if not(1<=day<=31 and 1<=mon<=9): return None
                yr=y if(mon>m or(mon==m and day>=today.day)) else y+1
                return f"{yr}/{mon:02d}/{day:02d}"
            elif len(d)==4:
                day,mon=int(d[:2]),int(d[2:])
                if not(1<=day<=31 and 1<=mon<=12): return None
                yr=y if(mon>m or(mon==m and day>=today.day)) else y+1
                return f"{yr}/{mon:02d}/{day:02d}"
            elif len(d)==8:
                y2,m2,d2=int(d[:4]),int(d[4:6]),int(d[6:])
                datetime(y2,m2,d2); return f"{y2}/{m2:02d}/{d2:02d}"
        except: return None

    def _on_key(self, e):
        if e.keysym in('Tab','Return','BackSpace','Delete','Left','Right'): return
        self._pending = self._parse(self.var.get())
        if self._after_id:
            try: self.entry.after_cancel(self._after_id)
            except: pass
        if self._pending:
            self._after_id = self.entry.after(2000, self._apply)

    def _apply(self):
        if self._pending: self.var.set(self._pending); self._pending = None

    def _on_tab(self, e):
        d = self.var.get().strip().replace('/','')
        if d.isdigit() and len(d)==1: self._pending = self._parse('0'+d)
        if not self._pending: self._pending = self._parse(self.var.get())
        self._apply(); return 'break'

    def _focusout(self, e):
        raw = self.var.get().strip()
        if not raw: return
        s = self._parse(raw)
        if s: self.var.set(s)
        else:
            try:
                p=raw.split('/'); datetime(int(p[0]),int(p[1]),int(p[2]))
            except: self.var.set('')

    def get(self): return self.var.get()
    def set(self, v): self.var.set(v)
    def focus(self): self.entry.focus()


class SmartTimeEntry(ctk.CTkFrame):
    def __init__(self, parent, border_color=None, text_color=None, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        self.sfx = tk.StringVar(value='ص')
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack()
        self.sfx_btn = ctk.CTkButton(row, textvariable=self.sfx,
            width=38, height=36, font=F(12,True),
            fg_color=ACCENT, hover_color=ACCENT2,
            text_color=WHITE, command=self._toggle)
        self.sfx_btn.pack(side='left', padx=(0,5))
        self.var = tk.StringVar()
        self.entry = ctk.CTkEntry(row, textvariable=self.var,
            font=F(13), width=90, justify="right",
            fg_color=WHITE, border_color=border_color or CARD_BD,
            text_color=text_color or TEXT_D)
        self.entry.pack(side='left')
        self.entry.bind('<FocusOut>', self._fmt)
        self.entry.bind('<FocusIn>', lambda e: self.entry.select_range(0,'end'))

    def _toggle(self):
        self.sfx.set('م' if self.sfx.get()=='ص' else 'ص')

    def _fmt(self, e=None):
        val = self.var.get().replace(':','').strip()
        if not val.isdigit(): return
        try:
            if len(val)<=2: h,mn=int(val),0
            elif len(val)==3: h,mn=int(val[0]),int(val[1:])
            else: h,mn=int(val[:2]),int(val[2:4])
            if mn>=60: mn=0
            if 7<=h<=11: self.sfx.set('ص')
            elif 1<=h<=3: self.sfx.set('م')
            h24=h+12 if self.sfx.get()=='م' and h<12 else h
            if h24>15: h,mn=3,0; self.sfx.set('م')
            self.var.set(f"{h:02d}:{mn:02d}")
        except: pass

    def get(self):
        self._fmt()
        val = self.var.get().replace(':','').strip()
        try:
            if len(val)<=2: h,mn=int(val),0
            elif len(val)==3: h,mn=int(val[0]),int(val[1:])
            else: h,mn=int(val[:2]),int(val[2:4])
            if self.sfx.get()=='م' and h<12: h+=12
            if h>15: h=15
            return f"{h:02d}:{mn:02d}"
        except: return "10:00"

    def set(self, v):
        try:
            p=v.split(':'); h,mn=int(p[0]),int(p[1]) if len(p)>1 else 0
            self.sfx.set("ص" if h<12 else "م")
            dh=h if h<=12 else h-12; self.var.set(f"{dh:02d}:{mn:02d}")
        except: self.var.set(v)

    def focus(self): self.entry.focus()


class AddSessionWindow(ctk.CTkToplevel):
    def __init__(self, parent, cookies, caso_no, case_name, last_time, last_type, on_success):
        super().__init__(parent)
        self.cookies = cookies
        self.on_success = on_success
        self._caso = caso_no
        self._case_name = case_name
        self.title("إضافة جلسة")
        self.geometry("460x390")
        self.configure(fg_color=BG)
        self.grab_set()
        self.resizable(False, False)

        # هيدر
        hdr = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0, height=56)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="إضافة جلسة قادمة",
            font=F(15,True), text_color=WHITE).place(relx=0.97, rely=0.5, anchor='e')
        ctk.CTkButton(hdr, text="✕", width=32, height=32,
            fg_color="transparent", hover_color=SIDEBAR2,
            text_color=TEXT_L, command=self.destroy).place(relx=0.03, rely=0.5, anchor='w')

        # بانر
        ref = ctk.CTkFrame(self, fg_color="#eaf4ff", corner_radius=8)
        ref.pack(fill='x', padx=20, pady=12)
        ctk.CTkLabel(ref, text=caso_no, font=F(11,True), text_color=BLUE).pack(side='right', padx=12, pady=8)
        ctk.CTkLabel(ref, text=case_name[:38], font=F(10), text_color=TEXT_M).pack(side='right', pady=8)

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill='x', padx=20)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        def lbl(t, r, c, cs=1):
            ctk.CTkLabel(form, text=t, font=F(10), text_color=TEXT_M, anchor='e'
                ).grid(row=r*2, column=c, columnspan=cs, sticky='e', pady=(10,2), padx=5)

        lbl("التاريخ", 0, 1); self.de = SmartDateEntry(form)
        self.de.grid(row=1, column=1, sticky='ew', padx=5, pady=2)
        lbl("التوقيت", 0, 0); self.te = SmartTimeEntry(form)
        self.te.set(last_time or "10:30")
        self.te.grid(row=1, column=0, sticky='ew', padx=5, pady=2)
        lbl("نوع الجلسة", 1, 0, 2)
        self.tv = tk.StringVar(value=last_type if last_type in SESSION_TYPES else "مناقشة")
        self.tc = ctk.CTkComboBox(form, variable=self.tv,
            values=list(SESSION_TYPES.keys()), font=F(12),
            dropdown_font=F(12), fg_color=WHITE,
            border_color=CARD_BD, button_color=ACCENT,
            button_hover_color=ACCENT2, text_color=TEXT_D,
            width=400, justify='right')
        self.tc.grid(row=3, column=0, columnspan=2, sticky='ew', padx=5, pady=2)

        def de_tab(e):
            # لو رقم واحد نضيف صفر قبله
            val = self.de.var.get().strip()
            if val.isdigit() and len(val) == 1:
                self.de._pending = self.de._parse('0' + val)
            self.de._apply()
            self.te.entry._entry.focus_set()
            return 'break'
        def te_tab(e):
            self.te._fmt()
            self.tc._entry.focus_set()
            return 'break'
        # نربط على الـ widget الداخلي مباشرة
        self.de.entry._entry.bind('<Tab>', de_tab)
        self.de.entry._entry.bind('<Return>', de_tab)
        self.te.entry._entry.bind('<Tab>', te_tab)
        self.te.entry._entry.bind('<Return>', te_tab)
        self.tc._entry.bind('<Return>', lambda e: self._submit())

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(fill='x', padx=20, pady=15, side='bottom')
        ctk.CTkButton(bf, text="إلغاء", font=F(11),
            fg_color="transparent", border_width=1, border_color=CARD_BD,
            text_color=TEXT_M, hover_color="#eef0f5",
            command=self.destroy).pack(side='left')
        ctk.CTkButton(bf, text="💾  حفظ الجلسة", font=F(11,True),
            fg_color=ACCENT, hover_color=ACCENT2, text_color=WHITE,
            command=self._submit).pack(side='right')
        self.de.focus()

    def _submit(self):
        dv, tv, typev = self.de.get().strip(), self.te.get().strip(), self.tv.get().strip()
        if not dv: messagebox.showwarning("تنبيه","يرجى إدخال التاريخ"); return
        if not tv: messagebox.showwarning("تنبيه","يرجى إدخال التوقيت"); return
        if typev not in SESSION_TYPES: messagebox.showwarning("تنبيه","يرجى اختيار نوع الجلسة"); return
        try:
            import urllib3; urllib3.disable_warnings()
            r = requests.post(f"{BASE_URL}/includes/insert.php",
                data={'ECS_IN_REGNO':self._caso,'EMET_MEET_DTE':dv,
                      'EMET_MEET_TIME':tv,'EMET_TYPE':SESSION_TYPES[typev]},
                cookies=self.cookies, verify=False)
            msgs={'1':('✅ تم الحفظ','info'),'2':('❌ خطأ','error'),
                  '3':('⚠️ تعارض توقيت','warning'),'4':('⚠️ جلسة حجز','warning'),
                  '5':('⚠️ إجازة','warning'),'6':('❌ أقل من 7 أيام','error')}
            msg,mt=msgs.get(r.text.strip(),(f'نتيجة: {r.text}','error'))
            if mt=='info':
                self._sync_to_calendar(dv, tv)
                try:
                    case_db.upsert_session(self._caso, dv, tv, typev, self._case_name)
                except Exception:
                    pass
                try:
                    from db_writer import insert_event_record
                    insert_event_record(self._caso, dv, tv, typev)
                except Exception:
                    pass
                messagebox.showinfo("✅",msg); self.destroy(); self.on_success()
            elif mt=='warning': messagebox.showwarning("تنبيه",msg)
            else: messagebox.showerror("خطأ",msg)
        except Exception as e: messagebox.showerror("خطأ",str(e))

    def _sync_to_calendar(self, dv, tv):
        """يدفع الموعد تلقائيًا لتقويم iCloud لو الخبير مربوط حسابه — فشل المزامنة الفعلي (شبكة مثلاً) لا يوقف أي شي، بس عدم الربط من الأساس يستحق تنبيهًا واضحًا"""
        try:
            from icloud_calendar import has_credentials, add_calendar_event
            if not has_credentials():
                messagebox.showwarning(
                    "⚠️ تنبيه",
                    "لم تُضَف الجلسة لتقويم آيفونك — لا يوجد حساب iCloud "
                    "مربوط.\n\nاربط حسابك من صفحة الإعدادات لتفعيل المزامنة "
                    "التلقائية."
                )
                return
            from api import get_case_parties_summary
            summary = get_case_parties_summary(self._caso, self.cookies, '')
            start_dt = datetime.strptime(f"{dv} {tv}", "%Y/%m/%d %H:%M")
            add_calendar_event(
                f"{summary} - {self._caso}", start_dt,
                description=self._case_name or ''
            )
        except Exception:
            pass


class SessionCard(ctk.CTkFrame):
    SECONDMENT_BG = "#fdf2f6"  # وردي فاتح جدًا — يميّز جلسات الاستعانة بصريًا فقط

    def __init__(self, parent, sdata, cookies, user, on_refresh, title_fallback_fn=None):
        caso = sdata.get('description','')

        case_type = ''
        try:
            cached = case_db.get_case(caso)
            if cached:
                case_type = cached.get('case_type', '')
        except Exception:
            pass
        card_bg = self.SECONDMENT_BG if case_type == 'استعانة' else CARD

        super().__init__(parent, fg_color=card_bg, corner_radius=12,
            border_width=1, border_color=CARD_BD)
        self.cookies=cookies; self.user=user; self.on_refresh=on_refresh

        title = sdata.get('title','').strip().replace(caso,'').strip()
        if not title and title_fallback_fn:
            title = title_fallback_fn(caso)
        self.case_title = title
        parts = sdata.get('start','').split(' ')
        date = parts[0] if parts else ''
        time = parts[1] if len(parts)>1 else ''
        try:
            h,mn=int(time.split(':')[0]),int(time.split(':')[1])
            sfx="ص" if h<12 else "م"; dh=h if h<=12 else h-12
            tdis=f"{dh:02d}:{mn:02d} {sfx}"
        except: tdis=time

        # hover
        self.bind('<Enter>', lambda e: self.configure(border_color=ACCENT))
        self.bind('<Leave>', lambda e: self.configure(border_color=CARD_BD))

        # صف 1: نوع الجلسة يمين + وقت + ثلاث نقاط
        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(fill='x', padx=18, pady=(14,0))

        mbtn = ctk.CTkLabel(r1, text="⋮", font=F(18), text_color=TEXT_L, cursor='hand2', width=24)
        mbtn.pack(side='left')

        ctk.CTkLabel(r1, text=tdis, font=F(18,True), text_color=TEXT_D).pack(side='left', padx=(10,0))

        # تاج نوع الجلسة
        ctk.CTkLabel(r1, text="  مناقشة  ", font=F(12),
            fg_color="#e8f8f0", text_color="#27ae60",
            corner_radius=20).pack(side='right')

        # صف 2: رقم الخبرة يمين + زر طباعة يسار
        r2 = ctk.CTkFrame(self, fg_color="transparent")
        r2.pack(fill='x', padx=18, pady=(10,0))

        ctk.CTkButton(r2, text="🖨  طباعة المحضر", font=F(12,True),
            width=155, height=36, fg_color=BLUE, hover_color="#2980b9",
            text_color=WHITE, corner_radius=8,
            command=lambda cn=caso,d=date,t=time: self._print(cn,d,t)
        ).pack(side='left')

        ctk.CTkButton(r2, text="📅", font=F(14,True),
            width=40, height=36, fg_color="#9b59b6", hover_color="#8e44ad",
            text_color=WHITE, corner_radius=8,
            command=lambda cn=caso,d=date,t=time: self._add_to_calendar(cn,d,t)
        ).pack(side='left', padx=(6,0))

        ctk.CTkButton(r2, text="📢", font=F(14,True),
            width=40, height=36, fg_color="#e67e22", hover_color="#d35400",
            text_color=WHITE, corner_radius=8,
            command=lambda cn=caso,d=date,t=time: self._print_gov_notice(cn,d,t)
        ).pack(side='left', padx=(6,0))

        ctk.CTkLabel(r2, text=f"{caso}  ·  {title[:38]}",
            font=F(17,True), text_color=TEXT_D, anchor='e').pack(side='right')

        # فاصل
        ctk.CTkFrame(self, fg_color=CARD_BD, height=1).pack(fill='x', padx=18, pady=(12,0))

        # صف 3: زر إضافة جلسة
        r3 = ctk.CTkFrame(self, fg_color="transparent")
        r3.pack(fill='x', padx=18, pady=(8,14))

        ctk.CTkButton(r3,
            text="➕   إضافة جلسة قادمة",
            font=F(12, True),
            fg_color=ACCENT, hover_color=ACCENT2,
            text_color=WHITE, corner_radius=20,
            height=36,
            command=lambda cn=caso,t=title,ti=time:
                AddSessionWindow(self.winfo_toplevel(),
                    self.cookies, cn, t, ti, "مناقشة", self.on_refresh)
        ).pack(side='right')

        for w in [self, r1, r2, mbtn]:
            w.bind('<Enter>', lambda e: self.configure(border_color=ACCENT))
            w.bind('<Leave>', lambda e: self.configure(border_color=CARD_BD))

    def _print(self, caso, date, time):
        try:
            from case_info_window import ensure_case_data
            case_dict = {'caso_no': caso, 'title': self.case_title,
                         'received_date': '', 'autocase_no': ''}
            case_data = ensure_case_data(self.winfo_toplevel(), self.cookies, self.user, case_dict)

            self.winfo_toplevel().configure(cursor='wait'); self.winfo_toplevel().update()
            info = parse_case_info(caso, self.cookies, self.user)
            exps = get_experts(caso, self.cookies, self.user)
            if exps:
                chairs=[x for x in exps if x['role']=='رئيس لجنة']
                members=[x for x in exps if x['role']!='رئيس لجنة']
                if len(exps)==1: es=exps[0]['name']
                elif len(exps)>=3 and chairs:
                    es=f"{members[0]['name']}  ،  {chairs[0]['name']}  ،  {members[1]['name'] if len(members)>1 else ''}"
                else: es='  ،  '.join([x['name'] for x in exps])
            else: es=self.user

            # بيانات القاعدة (مستخرجة من حكم الإحالة فعليًا) تُفضَّل دايمًا؛
            # كشط الموقع (parse_case_info) يبقى احتياطي فقط لو القاعدة فاضية
            plaintiffs = case_data.get('plaintiffs') or info.get('plaintiffs', [])
            defendants = case_data.get('defendants') or info.get('defendants', [])
            court_case_number = case_data.get('court_case_number') or info.get('case_num', '')

            pl=[clean_spaces(p) for p in plaintiffs]
            pl_s=pl[0] if len(pl)==1 else '\n'.join([f"{i+1}- {p}" for i,p in enumerate(pl)])
            df=[clean_spaces(d) for d in defendants]
            df_s=df[0] if len(df)==1 else '\n'.join([f"{i+1}- {d}" for i,d in enumerate(df)])

            num=compute_session_number(self.cookies, caso, date)
            out=os.path.join(os.path.expanduser("~"),"Desktop","محاضر",caso)
            os.makedirs(out, exist_ok=True)
            path=os.path.join(out,f"{num}.docx")

            fill_mahdar(path, {
                'رقم_المحضر':str(num),'اليوم':get_day_name(date),
                'التاريخ':date,'رقم_الخبرة':caso,'الساعة':time,
                'رقم_الدعوى':court_case_number,
                'الواردة_من':info.get('source',''),
                'المرفوعة_من':pl_s,'المرفوعة_ضد':df_s,
                'الخبير':es,'المحافظة':info.get('governorate',''),
                'القسم':info.get('department',''),
            })
            self.winfo_toplevel().configure(cursor='')
            messagebox.showinfo("✅ تم", f"تم إنشاء المحضر!\n\n{path}")
            os.startfile(path)
        except Exception as e:
            self.winfo_toplevel().configure(cursor='')
            messagebox.showerror("خطأ", str(e))

    def _print_gov_notice(self, caso, date, time):
        """
        يولّد 'إخطار لحضور جلسة خبرة' موجّه للجهة/الجهات الحكومية
        الطرف بالدعوى. نفس مصدر بيانات المحضر (parse_case_info +
        القاعدة) لرقم الدعوى/الأطراف/الخبير/المحافظة/القسم، مع بيانات
        الجلسة القادمة (التاريخ/اليوم/الساعة من الكرت نفسه) ومكان
        الخبير من الإعدادات (المقر/الدور/المكتب/الجناح). الجهة
        الحكومية تُكتشف تلقائيًا من الأطراف (كلها، ليمسح الخبير ما لا
        يريده). المخرج: Desktop/محاضر/{caso}/اخطار_حكومة.docx
        """
        try:
            from case_info_window import ensure_case_data
            case_dict = {'caso_no': caso, 'title': self.case_title,
                         'received_date': '', 'autocase_no': ''}
            case_data = ensure_case_data(self.winfo_toplevel(), self.cookies, self.user, case_dict)

            self.winfo_toplevel().configure(cursor='wait'); self.winfo_toplevel().update()
            info = parse_case_info(caso, self.cookies, self.user)
            exps = get_experts(caso, self.cookies, self.user)
            if exps:
                chairs = [x for x in exps if x['role'] == 'رئيس لجنة']
                members = [x for x in exps if x['role'] != 'رئيس لجنة']
                if len(exps) == 1: es = exps[0]['name']
                elif len(exps) >= 3 and chairs:
                    es = f"{members[0]['name']}  ،  {chairs[0]['name']}  ،  {members[1]['name'] if len(members) > 1 else ''}"
                else: es = '  ،  '.join([x['name'] for x in exps])
            else: es = self.user

            plaintiffs = case_data.get('plaintiffs') or info.get('plaintiffs', [])
            defendants = case_data.get('defendants') or info.get('defendants', [])
            court_case_number = case_data.get('court_case_number') or info.get('case_num', '')

            pl = [clean_spaces(p) for p in plaintiffs]
            pl_s = pl[0] if len(pl) == 1 else '\n'.join([f"{i+1}- {p}" for i, p in enumerate(pl)])
            df = [clean_spaces(d) for d in defendants]
            df_s = df[0] if len(df) == 1 else '\n'.join([f"{i+1}- {d}" for i, d in enumerate(df)])

            # كشف الأطراف الحكومية (كلها) — تُدرج بسطر 'السيد الفاضل /'
            gov_parties = detect_gov_parties(plaintiffs, defendants)
            gov_text = '  ،  '.join(gov_parties)

            # مكان الخبير من الإعدادات
            from expert_settings import load_location
            loc = load_location()

            out = os.path.join(os.path.expanduser("~"), "Desktop", "محاضر", caso)
            os.makedirs(out, exist_ok=True)
            path = os.path.join(out, "اخطار_حكومة.docx")

            fill_gov_notice(path, {
                'رقم_الدعوى': court_case_number,
                'الواردة_من': info.get('source', ''),
                'رقم_الخبرة': caso,
                'المرفوعة_من': pl_s,
                'المرفوعة_ضد': df_s,
                'الخبير': es,
                'المحافظة': info.get('governorate', ''),
                'القسم': info.get('department', ''),
                'التاريخ': date,
                'اليوم': get_day_name(date),
                'الساعة': time,
                'المقر': loc.get('maqar', ''),
                'الدور': loc.get('dor', ''),
                'المكتب': loc.get('maktab', ''),
                'الجناح': loc.get('janah', ''),
                'الجهة': gov_text,
            })
            self.winfo_toplevel().configure(cursor='')
            if not gov_parties:
                messagebox.showinfo(
                    "✅ تم", f"تم إنشاء الإخطار!\n\nملاحظة: لم يتم التعرّف "
                    f"تلقائيًا على جهة حكومية بين الأطراف — اكتب الجهة "
                    f"يدويًا بخانة 'السيد الفاضل'.\n\n{path}")
            else:
                messagebox.showinfo("✅ تم", f"تم إنشاء الإخطار!\n\n{path}")
            os.startfile(path)
        except Exception as e:
            self.winfo_toplevel().configure(cursor='')
            messagebox.showerror("خطأ", str(e))

    def _add_to_calendar(self, caso, date, time):
        """يضيف هذي الجلسة يدويًا لتقويم iCloud — يفيد للجلسات القديمة أو أي جلسة موجودة فعلاً بالنظام قبل بناء هذي الميزة"""
        try:
            from icloud_calendar import has_credentials, add_calendar_event
            if not has_credentials():
                messagebox.showwarning("تنبيه", "لا يوجد حساب iCloud مربوط — اربطه من صفحة الإعدادات أولاً")
                return
            from api import get_case_parties_summary
            summary = get_case_parties_summary(caso, self.cookies, self.user)
            time_clean = time[:5]  # احتياطي لو الوقت بصيغة HH:MM:SS
            start_dt = datetime.strptime(f"{date} {time_clean}", "%Y/%m/%d %H:%M")
            ok, err = add_calendar_event(f"{summary} - {caso}", start_dt)
            if ok:
                messagebox.showinfo("✅ تم", "تمت إضافة الجلسة لتقويمك بنجاح")
            else:
                messagebox.showerror("❌ فشل", f"تعذرت الإضافة:\n\n{err}")
        except Exception as e:
            messagebox.showerror("❌ فشل", f"تعذرت الإضافة:\n\n{e}")


class WeeklyReportDialog(ctk.CTkToplevel):
    """
    نافذة اختيار فترة "كشف الجلسات" قبل الطباعة. حسب طلب المستخدم:
    - لو اليوم خميس/جمعة/سبت: نرشّح "الأسبوع القادم" افتراضيًا
      (أسبوع العمل الحالي خلص/راح ينخلص).
    - لو اليوم أحد: نرشّح "هذا الأسبوع" (للتو بدأ).
    - لو اثنين/ثلاثاء/أربعاء: نرشّح "الأسبوع القادم".
    بكل الأحوال المستخدم يقدر يغيّر الاختيار، أو يحدد فترة تاريخ
    مخصّصة يدويًا (SmartDateEntry لبداية ونهاية الفترة).
    """
    def __init__(self, parent, cookies, expert_name):
        super().__init__(parent)
        self.cookies = cookies
        self.expert_name = expert_name
        self.title("طباعة كشف الجلسات")
        self.geometry("420x430")
        self.configure(fg_color=BG)
        self.grab_set()
        self.resizable(False, False)

        hdr = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0, height=56)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🖨️  طباعة كشف الجلسات الأسبوعي",
            font=F(14,True), text_color=WHITE).place(relx=0.97, rely=0.5, anchor='e')
        ctk.CTkButton(hdr, text="✕", width=32, height=32,
            fg_color="transparent", hover_color=SIDEBAR2,
            text_color=TEXT_L, command=self.destroy).place(relx=0.03, rely=0.5, anchor='w')

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill='both', expand=True, padx=20, pady=16)

        default = suggest_default_period()
        self.choice = tk.StringVar(value=default)

        this_s, this_e = _week_bounds(offset_weeks=0)
        next_s, next_e = _week_bounds(offset_weeks=1)

        ctk.CTkRadioButton(body,
            text=f"هذا الأسبوع  ({this_s.strftime('%Y/%m/%d')} — {this_e.strftime('%Y/%m/%d')})",
            variable=self.choice, value='this', font=F(12),
            text_color=TEXT_D, text_color_disabled=TEXT_L,
            fg_color=ACCENT, hover_color=ACCENT2,
            command=self._on_choice_change
        ).pack(anchor='e', pady=(4,8), fill='x')

        ctk.CTkRadioButton(body,
            text=f"الأسبوع القادم  ({next_s.strftime('%Y/%m/%d')} — {next_e.strftime('%Y/%m/%d')})",
            variable=self.choice, value='next', font=F(12),
            text_color=TEXT_D, text_color_disabled=TEXT_L,
            fg_color=ACCENT, hover_color=ACCENT2,
            command=self._on_choice_change
        ).pack(anchor='e', pady=(0,8), fill='x')

        ctk.CTkRadioButton(body, text="تحديد فترة مخصّصة",
            variable=self.choice, value='custom', font=F(12),
            text_color=TEXT_D, text_color_disabled=TEXT_L,
            fg_color=ACCENT, hover_color=ACCENT2,
            command=self._on_choice_change
        ).pack(anchor='e', pady=(0,4), fill='x')

        self.custom_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.custom_frame.pack(fill='x', pady=(4,0))
        self.custom_frame.columnconfigure(0, weight=1)
        self.custom_frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(self.custom_frame, text="من", font=F(10), text_color=TEXT_M
            ).grid(row=0, column=1, sticky='e', padx=5)
        ctk.CTkLabel(self.custom_frame, text="إلى", font=F(10), text_color=TEXT_M
            ).grid(row=0, column=0, sticky='e', padx=5)
        self.de_from = SmartDateEntry(self.custom_frame)
        self.de_from.grid(row=1, column=1, sticky='ew', padx=5, pady=2)
        self.de_to = SmartDateEntry(self.custom_frame)
        self.de_to.grid(row=1, column=0, sticky='ew', padx=5, pady=2)

        self._on_choice_change()

        # اتجاه الورقة — بالعرض (landscape) افتراضيًا لأنه أنسب لجدول
        # الكشف (أعمدة عريضة)، مع خيار التحويل للطول لمن يفضّله
        ori_row = ctk.CTkFrame(body, fg_color="transparent")
        ori_row.pack(fill='x', pady=(14,0))
        ctk.CTkLabel(ori_row, text="اتجاه الورقة:", font=F(11),
            text_color=TEXT_M).pack(side='right', padx=(0,8))
        self.orientation = tk.StringVar(value='landscape')
        ctk.CTkRadioButton(ori_row, text="بالعرض", variable=self.orientation,
            value='landscape', font=F(11), text_color=TEXT_D,
            fg_color=ACCENT, hover_color=ACCENT2).pack(side='right', padx=(0,12))
        ctk.CTkRadioButton(ori_row, text="بالطول", variable=self.orientation,
            value='portrait', font=F(11), text_color=TEXT_D,
            fg_color=ACCENT, hover_color=ACCENT2).pack(side='right')

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(fill='x', padx=20, pady=15, side='bottom')
        ctk.CTkButton(bf, text="إلغاء", font=F(11),
            fg_color="transparent", border_width=1, border_color=CARD_BD,
            text_color=TEXT_M, hover_color="#eef0f5",
            command=self.destroy).pack(side='left')
        ctk.CTkButton(bf, text="🖨️  طباعة", font=F(11,True),
            fg_color=ACCENT, hover_color=ACCENT2, text_color=WHITE,
            command=self._generate).pack(side='right')

    def _on_choice_change(self):
        state = 'normal' if self.choice.get() == 'custom' else 'disabled'
        for child in self.custom_frame.winfo_children():
            try: child.configure(state=state)
            except Exception: pass

    def _generate(self):
        c = self.choice.get()
        if c == 'this':
            start, end = _week_bounds(offset_weeks=0)
        elif c == 'next':
            start, end = _week_bounds(offset_weeks=1)
        else:
            try:
                start = datetime.strptime(self.de_from.get().strip(), '%Y/%m/%d')
                end = datetime.strptime(self.de_to.get().strip(), '%Y/%m/%d')
            except Exception:
                messagebox.showwarning("تنبيه", "يرجى إدخال تاريخين صحيحين")
                return
            if end < start:
                messagebox.showwarning("تنبيه", "تاريخ النهاية قبل تاريخ البداية")
                return

        try:
            self.configure(cursor='wait'); self.update()
            all_s = get_sessions(self.cookies,
                start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
            path = build_weekly_report_html(all_s, start, end, self.expert_name,
                orientation=self.orientation.get())
            self.configure(cursor='')
            os.startfile(path)
            self.destroy()
        except Exception as e:
            self.configure(cursor='')
            messagebox.showerror("خطأ", str(e))


class ExpertApp(ctk.CTk):
    def __init__(self, cookies, current_user):
        super().__init__()
        case_db.init_db()
        self.title("نظام جلسات الخبراء — وزارة العدل")
        self._fit_window_to_screen()
        self.configure(fg_color=BG)
        self.cookies=cookies; self.sessions_data=[]; self.current_user=current_user; self.week_offset=0
        self._build()
        enable_universal_copy_paste(self)
        self.after(200, lambda: self._connect(cookies, current_user))



    def _fit_window_to_screen(self):
        """
        كانت النافذة بحجم ثابت 1200x750 دائمًا، بغض النظر عن حجم شاشة
        المستخدم الفعلي. على الشاشات الأصغر (لابتوبات بدقة 1366x768 أو
        أقل، خصوصًا مع شريط المهام) كان هذا يخلي جزء من الواجهة ينزل
        تحت حدود الشاشة المرئية فيبين "ناقص" أو غير متناسق.

        الحل: نحسب حجم النافذة بناءً على دقة شاشة المستخدم الفعلية
        (winfo_screenwidth/height) — نستخدم نسبة من الشاشة (لا تتجاوز
        الحجم الأصلي 1200x750 كحد أقصى حتى ما يصير التصميم كبير زيادة
        على الشاشات العملاقة)، مع حد أدنى معقول (minsize) حتى ما تنكسر
        الواجهة لو المستخدم صغّر النافذة يدويًا، ثم نوسّط النافذة على
        الشاشة. النافذة تبقى قابلة للتحجيم (resizable) بشكل طبيعي.
        """
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        # نسبة من الشاشة مع هامش بسيط، وبحد أقصى الحجم الأصلي 1200x750
        target_w = min(1200, int(screen_w * 0.92))
        target_h = min(750, int(screen_h * 0.88))

        # حد أدنى حتى تبقى كل العناصر ظاهرة وما تتزاحم
        min_w, min_h = 1000, 620
        target_w = max(target_w, min(min_w, screen_w))
        target_h = max(target_h, min(min_h, screen_h))

        x = max(0, (screen_w - target_w) // 2)
        y = max(0, (screen_h - target_h) // 2)

        self.geometry(f"{target_w}x{target_h}+{x}+{y}")
        self.minsize(min_w, min_h)

    def _build(self):
        # الشريط الجانبي
        sb = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0, width=260)
        sb.pack(side='right', fill='y'); sb.pack_propagate(False)

        # الشعار
        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.pack(fill='x', padx=20, pady=28)
        ctk.CTkLabel(logo, text="⚖", font=F(28), text_color=ACCENT).pack(side='right')
        lf = ctk.CTkFrame(logo, fg_color="transparent")
        lf.pack(side='right', padx=(0,10))
        ctk.CTkLabel(lf, text="نظام الخبراء", font=F(17,True), text_color=WHITE).pack(anchor='e')
        self.stat = ctk.CTkLabel(lf, text="● جاري الاتصال...", font=F(10), text_color=TEXT_L)
        self.stat.pack(anchor='e')

        # خط فاصل
        ctk.CTkFrame(sb, fg_color="#2a3a50", height=1).pack(fill='x', padx=20, pady=8)

        # قائمة التنقل
        self.nav_sessions = ctk.CTkFrame(sb, fg_color=SIDEBAR2, corner_radius=10, cursor='hand2')
        self.nav_sessions.pack(fill='x', padx=12, pady=8)
        self.nav_sessions_lbl = ctk.CTkLabel(self.nav_sessions, text="🗓   الجلسات",
            font=F(11, True), text_color=WHITE)
        self.nav_sessions_lbl.pack(side='right', padx=16, pady=14)
        self.nav_sessions_bar = ctk.CTkFrame(self.nav_sessions, fg_color=ACCENT, width=4, corner_radius=2)
        self.nav_sessions_bar.pack(side='right', fill='y')
        for w in (self.nav_sessions, self.nav_sessions_lbl):
            w.bind('<Button-1>', lambda e: self._show_sessions_page())

        # بند: محضر أول جلسة (القضايا المتداولة)
        self.nav_pending = ctk.CTkFrame(sb, fg_color="transparent", corner_radius=10, cursor='hand2')
        self.nav_pending.pack(fill='x', padx=12, pady=2)
        self.nav_pending_lbl = ctk.CTkLabel(self.nav_pending, text="📋   القضايا المتداولة",
            font=F(11), text_color=TEXT_L)
        self.nav_pending_lbl.pack(side='right', padx=16, pady=14)
        self.nav_pending_bar = ctk.CTkFrame(self.nav_pending, fg_color=ACCENT, width=4, corner_radius=2)
        # الشريط الأخضر يُعرض فقط وقت التفعيل (نضيفه عند التفعيل لاحقاً)
        for w in (self.nav_pending, self.nav_pending_lbl):
            w.bind('<Button-1>', lambda e: self._show_pending_page())

        # بند: القضايا المحالة (مباشرة / إعادة)
        self.nav_referred = ctk.CTkFrame(sb, fg_color="transparent", corner_radius=10, cursor='hand2')
        self.nav_referred.pack(fill='x', padx=12, pady=2)
        self.nav_referred_lbl = ctk.CTkLabel(self.nav_referred, text="📨   القضايا المحالة",
            font=F(11), text_color=TEXT_L)
        self.nav_referred_lbl.pack(side='right', padx=16, pady=14)
        self.nav_referred_bar = ctk.CTkFrame(self.nav_referred, fg_color=ACCENT, width=4, corner_radius=2)
        for w in (self.nav_referred, self.nav_referred_lbl):
            w.bind('<Button-1>', lambda e: self._show_referred_page())

        # بند: الإعدادات (ربط Google Gemini API)
        self.nav_settings = ctk.CTkFrame(sb, fg_color="transparent", corner_radius=10, cursor='hand2')
        self.nav_settings.pack(fill='x', padx=12, pady=2)
        self.nav_settings_lbl = ctk.CTkLabel(self.nav_settings, text="⚙️   الإعدادات",
            font=F(11), text_color=TEXT_L)
        self.nav_settings_lbl.pack(side='right', padx=16, pady=14)
        self.nav_settings_bar = ctk.CTkFrame(self.nav_settings, fg_color=ACCENT, width=4, corner_radius=2)
        for w in (self.nav_settings, self.nav_settings_lbl):
            w.bind('<Button-1>', lambda e: self._show_settings_page())

        # اسم المستخدم
        ctk.CTkLabel(sb, text="المستخدم الحالي", font=F(9), text_color=TEXT_L
            ).pack(side='bottom', anchor='e', padx=20, pady=(0,4))
        self.user_lbl = ctk.CTkLabel(sb, text="", font=F(14,True),
            text_color=ACCENT, wraplength=220, justify='right')
        self.user_lbl.pack(side='bottom', anchor='e', padx=20, pady=(0,8))

        # المنطقة الرئيسية
        self.main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.main.pack(side='right', fill='both', expand=True)

        # حاوية الصفحة الحالية (إطاران ثابتان يُبدَّل بينهما بـ pack/pack_forget — كاش طبيعي)
        self.page_container = ctk.CTkFrame(self.main, fg_color=BG, corner_radius=0)
        self.page_container.pack(fill='both', expand=True)

        self.sessions_frame = ctk.CTkFrame(self.page_container, fg_color=BG, corner_radius=0)
        self.pending_frame = ctk.CTkFrame(self.page_container, fg_color=BG, corner_radius=0)
        self.referred_frame = ctk.CTkFrame(self.page_container, fg_color=BG, corner_radius=0)
        self.settings_frame = ctk.CTkFrame(self.page_container, fg_color=BG, corner_radius=0)

        self.current_page = None
        self._build_sessions_page(self.sessions_frame)
        self._show_sessions_page()

    def _clear_page(self):
        for w in self.page_container.winfo_children():
            w.destroy()

    def _set_active_nav(self, active):
        """يلوّن بند القائمة النشط بالأخضر ويطفئ البقية — يدعم أي عدد من البنود"""
        navs = {
            'sessions': (self.nav_sessions, self.nav_sessions_lbl, self.nav_sessions_bar),
            'pending': (self.nav_pending, self.nav_pending_lbl, self.nav_pending_bar),
            'referred': (self.nav_referred, self.nav_referred_lbl, self.nav_referred_bar),
            'settings': (self.nav_settings, self.nav_settings_lbl, self.nav_settings_bar),
        }
        for key, (frame, lbl, bar) in navs.items():
            if key == active:
                frame.configure(fg_color=SIDEBAR2)
                lbl.configure(text_color=WHITE, font=F(11, True))
                bar.pack(side='right', fill='y')
            else:
                frame.configure(fg_color="transparent")
                lbl.configure(text_color=TEXT_L, font=F(11))
                bar.pack_forget()

    def _show_sessions_page(self):
        self._set_active_nav('sessions')
        if self.current_page == 'sessions':
            return
        self.current_page = 'sessions'
        self.pending_frame.pack_forget()
        self.referred_frame.pack_forget()
        self.settings_frame.pack_forget()
        self.sessions_frame.pack(fill='both', expand=True)

    def _show_pending_page(self):
        self._set_active_nav('pending')
        if self.current_page == 'pending':
            return
        self.current_page = 'pending'
        self.sessions_frame.pack_forget()
        self.referred_frame.pack_forget()
        self.settings_frame.pack_forget()
        if not getattr(self, '_pending_built', False):
            from pending_cases import build_pending_cases_page
            build_pending_cases_page(self.pending_frame, self.cookies, self.current_user)
            self._pending_built = True
        self.pending_frame.pack(fill='both', expand=True)

    def _show_referred_page(self):
        self._set_active_nav('referred')
        if self.current_page == 'referred':
            return
        self.current_page = 'referred'
        self.sessions_frame.pack_forget()
        self.pending_frame.pack_forget()
        self.settings_frame.pack_forget()
        if not getattr(self, '_referred_built', False):
            from referred_cases import build_referred_cases_page
            build_referred_cases_page(self.referred_frame, self.cookies, self.current_user)
            self._referred_built = True
        self.referred_frame.pack(fill='both', expand=True)

    def _show_settings_page(self):
        self._set_active_nav('settings')
        if self.current_page == 'settings':
            return
        self.current_page = 'settings'
        self.sessions_frame.pack_forget()
        self.pending_frame.pack_forget()
        self.referred_frame.pack_forget()
        if not getattr(self, '_settings_built', False):
            from settings_page import build_settings_page
            build_settings_page(self.settings_frame)
            self._settings_built = True
        self.settings_frame.pack(fill='both', expand=True)

    def _build_sessions_page(self, parent):
        # الهيدر
        top = ctk.CTkFrame(parent, fg_color=WHITE, corner_radius=0, height=56,
            border_width=1, border_color=CARD_BD)
        top.pack(fill='x'); top.pack_propagate(False)
        ctk.CTkButton(top, text="↻  تحديث", font=F(11),
            fg_color="transparent", border_width=1, border_color=CARD_BD,
            text_color=TEXT_M, hover_color="#f0f4ff", width=100, height=36,
            command=self.load_sessions).pack(side='left', padx=15, pady=10)
        ctk.CTkButton(top, text="🖨️  كشف الجلسات", font=F(11),
            fg_color="transparent", border_width=1, border_color=CARD_BD,
            text_color=TEXT_M, hover_color="#f0f4ff", width=130, height=36,
            command=self._open_weekly_report_dialog).pack(side='left', padx=(0,10), pady=10)
        self.cnt = ctk.CTkLabel(top, text="", font=F(13,True), text_color=TEXT_D)
        self.cnt.pack(side='right', padx=20)

        # المحتوى
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill='both', expand=True, padx=30, pady=22)

        ctk.CTkLabel(content, text="جدول الجلسات الأسبوعية",
            font=F(24,True), text_color=TEXT_D).pack(anchor='e')
        self.date_range_lbl = ctk.CTkLabel(content, text="",
            font=F(12), text_color=TEXT_L)
        self.date_range_lbl.pack(anchor='e', pady=(3,16))

        self.scroll = ctk.CTkScrollableFrame(content, fg_color="transparent",
            scrollbar_button_color=CARD_BD, scrollbar_button_hover_color=TEXT_L)
        self.scroll.pack(fill='both', expand=True)
        speed_up_scroll(self.scroll)

    def _open_weekly_report_dialog(self):
        WeeklyReportDialog(self, self.cookies, self.current_user)

    def _connect(self, cookies, user):
        """يستقبل cookies ويحدّث حالة الاتصال"""
        self.cookies = cookies
        self.current_user = user
        self.stat.configure(text="● متصل", text_color=ACCENT)
        self.user_lbl.configure(text=self.current_user)
        if self.current_page == 'sessions':
            self.load_sessions()

    def _dedupe_same_day(self, sessions_list):
        """
        يمنع ظهور أكثر من جلسة/بطاقة لنفس (رقم الخبرة + اليوم) —
        ثبت من قضايا لجنة حقيقية إن أكثر من عضو (أو الخبير نفسه
        بالغلط) قد يضيف جلسة لنفس اليوم لنفس القضية (أحياناً بفارق
        دقيقة، أو بنوع مختلف زي 'للاعلان' اللي هو إجراء إداري لنفس
        الجلسة لا جلسة ثانية فعلية). النظام لا يسمح أصلاً بجلستين
        حقيقيتين بنفس اليوم لنفس القضية، فأي تكرار بهذا المستوى نعتبره
        نفس الجلسة ونعرض واحدة فقط (الأسبق بالترتيب).
        """
        seen = set()
        result = []
        for s in sessions_list:
            caso = s.get('description', '')
            date = s.get('start', '')[:10]
            key = (caso, date)
            if key in seen:
                continue
            seen.add(key)
            result.append(s)
        return result

    def load_sessions(self):
        try:
            today=datetime.now()
            # نبدأ من أمس عشان نضمن ظهور جلسات اليوم الحالي
            start=(today-timedelta(days=1)).strftime('%Y-%m-%d')
            end=(today+timedelta(days=30)).strftime('%Y-%m-%d')
            sf=today.strftime('%Y/%m/%d'); ef=end.replace('-','/')
            all_s=get_sessions(self.cookies,start,end)
            # نسجّل كل جلسة (حتى الماضية) محليًا — أساس ميزة "قضايا بدون
            # جلسة قادمة" (case_db.get_no_upcoming_cases)
            self._record_sessions_locally(all_s)
            filtered=sorted([s for s in all_s if sf<=s.get('start','')[:10]<=ef],
                key=lambda x:x.get('start',''))
            # إزالة تكرار نفس القضية بنفس اليوم (قضايا اللجان بالذات)
            self.sessions_data=self._dedupe_same_day(filtered)
            self._ensure_title_fallback_map()
            self.week_offset=0; self._render()
            self.cnt.configure(text=f"{len(self.sessions_data)} جلسة قادمة")
        except Exception as e: messagebox.showerror("خطأ",str(e))

    def _record_sessions_locally(self, sessions_list):
        """
        يسجّل كل جلسة (حتى الماضية) بجدول sessions المحلي (case_db).
        هذا يضمن أنه لو قضية طاحت برّا نطاق الجلب الحي (أمس→+30 يوم)
        بدون أي جلسة قادمة، يبقى عندنا 'آخر جلسة معروفة' لها محفوظة
        محليًا — فتظهر تلقائيًا ببطاقة تنبيه بدل ما تختفي بصمت.
        """
        for s in sessions_list or []:
            caso = s.get('description', '')
            if not caso:
                continue
            parts = s.get('start', '').split(' ')
            date = parts[0] if parts else ''
            time = parts[1] if len(parts) > 1 else ''
            title = s.get('title', '').strip().replace(caso, '').strip()
            try:
                case_db.upsert_session(caso, date, time, '', title)
            except Exception:
                pass

    def _ensure_title_fallback_map(self):
        """
        خريطة (رقم الخبرة -> اسم بديل) تُملأ lazily فقط للقضايا
        التي يرجع عنوانها فاضياً من load.php و METMONTH معاً.
        نستخدم basic_info_result.php (نفس مصدر بيانات المحضر) لجلب
        اسم المدعى عليه كعنوان بديل عند الحاجة فقط.
        """
        if getattr(self, '_title_map', None) is None:
            self._title_map = {}

    def _get_title_fallback(self, caso_no):
        """يجلب عنوان بديل لقضية واحدة فقط عند الحاجة (lazy, مع تخزين مؤقت)"""
        if caso_no in self._title_map:
            return self._title_map[caso_no]
        try:
            r = requests.post(f"{BASE_URL}/includes/basic_info_result.php",
                data={'id':'1','title':caso_no,'met_date':'','met_time':'','description':caso_no},
                cookies=self.cookies, verify=False, timeout=5)
            h4s = re.findall(r'<h4[^>]*>(.*?)</h4>', r.text)
            h4s = [re.sub(r'<[^>]+>','',h).strip() for h in h4s]
            defendant = ''
            for h in h4s:
                if 'المدعى عليه' in h:
                    defendant = h.split(':',1)[-1].strip()
                    break
            self._title_map[caso_no] = defendant
            return defendant
        except Exception:
            self._title_map[caso_no] = ''
            return ''

    def load_next_week(self):
        self.week_offset+=7
        try:
            today=datetime.now()
            start=(today+timedelta(days=self.week_offset)).strftime('%Y-%m-%d')
            end=(today+timedelta(days=self.week_offset+7)).strftime('%Y-%m-%d')
            sf,ef=start.replace('-','/'),end.replace('-','/')
            all_s=get_sessions(self.cookies,start,end)
            self._record_sessions_locally(all_s)
            new_s=sorted([s for s in all_s if sf<=s.get('start','')[:10]<=ef],
                key=lambda x:x.get('start',''))
            # ندمج مع القائمة الحالية ثم نزيل التكرار على المجموعة كاملة —
            # يضمن عدم تكرار قضية ظهرت أسبوع سابق بنفس اليوم مرة ثانية هنا
            self.sessions_data=self._dedupe_same_day(self.sessions_data + new_s)
            self._render()
            self.cnt.configure(text=f"{len(self.sessions_data)} جلسة")
        except Exception as e: messagebox.showerror("خطأ",str(e))

    def _render_no_upcoming(self):
        """
        يعرض بأعلى قائمة الجلسات بطاقات القضايا اللي 'بدون جلسة قادمة'
        فعليًا — يقتصر على القضايا 'المتداولة' فقط لهذا الخبير تحديداً
        (case_db.get_no_upcoming_cases(current_user)، اللي بدورها
        تستبعد المحجوزة/المنجزة/أي قضية غير متابَعة). بخلفية حمراء
        فاتحة تميّزها بوضوح، مع آخر جلسة معروفة وزر إضافة جلسة مباشر.
        القضية تختفي تلقائياً من هذا القسم بمجرد إضافة جلسة قادمة لها
        (تُسجَّل فورًا عبر AddSessionWindow._submit، فتظهر بالتحميل
        الجاي ضمن القائمة العادية لا هنا).
        """
        try:
            no_upcoming = case_db.get_no_upcoming_cases(self.current_user)
        except Exception:
            no_upcoming = []
        if not no_upcoming:
            return

        known_upcoming = {s.get('description', '') for s in self.sessions_data}
        no_upcoming = [c for c in no_upcoming if c['caso_no'] not in known_upcoming]
        if not no_upcoming:
            return

        hdr = ctk.CTkFrame(self.scroll, fg_color="transparent")
        hdr.pack(fill='x', pady=(0, 6))
        ctk.CTkLabel(hdr, text=f"⚠  قضايا متداولة بدون جلسة قادمة ({len(no_upcoming)})",
            font=F(13, True), text_color=NO_UPCOMING_TXT).pack(anchor='e')

        for c in no_upcoming:
            self._build_no_upcoming_card(c)

        ctk.CTkFrame(self.scroll, fg_color=CARD_BD, height=1).pack(fill='x', pady=(10, 4))

    def _build_no_upcoming_card(self, info):
        caso = info.get('caso_no', '')

        title = ''
        try:
            cached = case_db.get_case(caso)
            if cached:
                title = cached.get('title', '') or ''
        except Exception:
            pass
        if not title:
            title = info.get('title', '') or ''
        if not title:
            title = self._get_title_fallback(caso)

        last_date_disp = info.get('session_date', '')
        try:
            d = datetime.strptime(last_date_disp, '%Y-%m-%d')
            last_date_disp = d.strftime('%Y/%m/%d')
        except Exception:
            pass

        row = ctk.CTkFrame(self.scroll, fg_color=NO_UPCOMING_BG, corner_radius=12,
            border_width=1, border_color=NO_UPCOMING_BD)
        row.pack(fill='x', pady=5, padx=4)
        row.bind('<Enter>', lambda e: row.configure(border_color=NO_UPCOMING_TXT))
        row.bind('<Leave>', lambda e: row.configure(border_color=NO_UPCOMING_BD))

        r1 = ctk.CTkFrame(row, fg_color="transparent")
        r1.pack(fill='x', padx=18, pady=(14, 0))
        ctk.CTkLabel(r1, text=f"{caso}  ·  {title[:45]}",
            font=F(15, True), text_color=TEXT_D, anchor='e').pack(side='right')
        ctk.CTkLabel(r1, text="⚠  بدون جلسة قادمة", font=F(11, True),
            text_color=NO_UPCOMING_TXT).pack(side='left')

        r2 = ctk.CTkFrame(row, fg_color="transparent")
        r2.pack(fill='x', padx=18, pady=(6, 14))
        ctk.CTkLabel(r2,
            text=f"آخر جلسة معروفة: {last_date_disp}" + (f"  ({info.get('session_type')})" if info.get('session_type') else ''),
            font=F(11), text_color=TEXT_M).pack(side='right')

        ctk.CTkButton(r2, text="➕  إضافة جلسة قادمة", font=F(12, True),
            fg_color=ACCENT, hover_color=ACCENT2, text_color=WHITE, corner_radius=20,
            height=36,
            command=lambda cn=caso, t=title:
                AddSessionWindow(self.winfo_toplevel(), self.cookies, cn, t,
                    "10:30", "مناقشة", self.load_sessions)
        ).pack(side='left')

    def _render(self):
        for w in self.scroll.winfo_children(): w.destroy()

        # قسم "قضايا متداولة بدون جلسة قادمة" — يظهر دايمًا أولًا لو فيه
        # قضايا مؤهلة، حتى لو قائمة الجلسات القادمة العادية فاضية
        self._render_no_upcoming()

        # تحديث نطاق التواريخ
        if self.sessions_data:
            dates = [s.get('start','')[:10] for s in self.sessions_data if s.get('start','')]
            if dates:
                first = min(dates); last = max(dates)
                def fmt(d):
                    try:
                        p=d.split('/')
                        # لو format YYYY/MM/DD نعكسه
                        if len(p[0])==4: return f"{p[2]}/{p[1]}/{p[0]}"
                        # لو format DD/MM/YYYY نتركه
                        return d
                    except: return d
                self.date_range_lbl.configure(text=f"({fmt(first)}  —  {fmt(last)})")
        else:
            self.date_range_lbl.configure(text="")

        if not self.sessions_data:
            ctk.CTkLabel(self.scroll, text="لا توجد جلسات قادمة",
                font=F(15), text_color=TEXT_L).pack(pady=60)
        else:
            cur=None
            for s in self.sessions_data:
                p=s.get('start','').split(' '); date=p[0] if p else ''; day=get_day_name(date)
                if date!=cur:
                    cur=date
                    df=ctk.CTkFrame(self.scroll, fg_color="transparent")
                    df.pack(fill='x', pady=(18,6))
                    ctk.CTkFrame(df, fg_color=CARD_BD, height=1).pack(side='left',fill='x',expand=True,pady=7)
                    ctk.CTkLabel(df, text=f"  {day}  ·  {date}  ",
                        font=F(13,True), text_color=WHITE, fg_color=SIDEBAR,
                        corner_radius=14).pack(side='left', padx=4)
                    ctk.CTkFrame(df, fg_color=CARD_BD, height=1).pack(side='left',fill='x',expand=True,pady=7)

                SessionCard(self.scroll, s, self.cookies, self.current_user,
                    self.load_sessions, title_fallback_fn=self._get_title_fallback
                    ).pack(fill='x', pady=5, padx=4)

        ctk.CTkButton(self.scroll, text="∨   تحميل جلسات الأسبوع القادم",
            font=F(12), fg_color="transparent", border_width=1,
            border_color=CARD_BD, text_color=TEXT_M,
            hover_color=WHITE, command=self.load_next_week,
            height=44, corner_radius=10).pack(fill='x', pady=(15,5), padx=4)
