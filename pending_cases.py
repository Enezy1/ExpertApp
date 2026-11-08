# ===== pending_cases.py — القضايا المتداولة (محضر أول جلسة) =====
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import requests
import re
import os
import html as html_lib
from datetime import datetime, timedelta

from config import BASE_URL
import case_db

# نفس ألوان ui.py تماماً (يُحافظ على نفس الهوية البصرية)
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

# لون تمييز القضايا المحجوزة (أزرق فاتح متناسق مع الهوية البصرية)
RESERVED_BG = "#eaf4fc"   # أزرق فاتح جداً للخلفية
RESERVED_BD = "#bcdcf5"   # حدّ أزرق أفتح للتمييز

def F(s, b=False):
    return (FONT, s, "bold") if b else (FONT, s)


def get_title_fallback(cookies, caso_no):
    """
    يجلب اسم 'المدعى عليه' من basic_info_result.php كعنوان بديل
    عندما يكون عنوان القضية فاضياً في METMONTH (نفس مصدر بيانات المحضر).
    """
    try:
        r = requests.post(f"{BASE_URL}/includes/basic_info_result.php",
            data={'id': '1', 'title': caso_no, 'met_date': '', 'met_time': '', 'description': caso_no},
            cookies=cookies, verify=False, timeout=5)
        h4s = re.findall(r'<h4[^>]*>(.*?)</h4>', r.text)
        h4s = [re.sub(r'<[^>]+>', '', h).strip() for h in h4s]
        for h in h4s:
            if 'المدعى عليه' in h:
                return h.split(':', 1)[-1].strip()
    except Exception:
        pass
    return ''


def get_pending_cases(cookies):
    """
    يجيب كل القضايا المتداولة لدى الخبير حالياً من صفحة METMONTH
    (رصيد الخبير) — تشمل القضايا التي لم تُحدَّد لها جلسات بعد.

    ملاحظة مهمة عن آلية عمل الصفحة بالسيرفر: METMONTH.php يعتمد على
    متغيّر SESSION اسمه source_id لا يكون موجوداً تلقائياً عند الدخول
    المباشر للرابط — في الموقع الأصلي، يُضبط هذا المتغيّر عبر طلب AJAX
    منفصل (set_sourc.php) يُستدعى تلقائياً عند الضغط على بطاقة "رصيد
    الخبير" بالصفحة الرئيسية (الدالة set_sourc_type('motadawal')،
    والتي تُرسل POST لـ ./includes/set_sourc.php مع source_id=motadawal
    قبل الانتقال لصفحة METMONTH).

    نكرر هذا الإجراء بالضبط برمجياً: نرسل نفس طلب POST أولاً لضبط
    source_id بالجلسة، ثم نطلب METMONTH وتظهر بياناتها بشكل صحيح
    من أول محاولة، بدون أي حاجة لمتصفح حقيقي أو محاولات متكررة.

    يرجع قائمة dicts: {'caso_no', 'title', 'received_date', 'autocase_no'}
    مرتبة من الأقدم استلاماً إلى الأحدث.
    """
    try:
        # الخطوة الضرورية: ضبط source_id بالجلسة قبل طلب الجدول
        requests.post(f"{BASE_URL}/includes/set_sourc.php",
            data={'source_id': 'motadawal'}, cookies=cookies, verify=False, timeout=10)

        r = requests.get(f"{BASE_URL}/METMONTH", cookies=cookies, verify=False, timeout=10)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', r.text, re.DOTALL)
        tds = [re.sub(r'<[^>]+>', '', t).strip() for t in tds]

        # كل سجل يبدأ بـ '&nbsp' ثم 8 حقول، آخرها اسم القضية بعد رقم الخبرة
        # النمط المرصود:
        # &nbsp, رقم حركة, رقم آلي, قسم, اسم الخبير, قسم, تاريخ الاستلام(YYYY-MM-DD), رقم الخبرة, اسم القضية
        cases = []
        i = 0
        while i < len(tds):
            if tds[i] == '&nbsp':
                block = tds[i:i+9]
                if len(block) == 9:
                    autocase_no = block[2]
                    received_date = block[6]
                    caso_no = block[7]
                    title = block[8]
                    if caso_no:
                        cases.append({
                            'caso_no': caso_no,
                            'title': title,
                            'received_date': received_date,
                            'autocase_no': autocase_no,
                        })
                i += 9
            else:
                i += 1

        def parse_date(d):
            try:
                return datetime.strptime(d, '%Y-%m-%d')
            except:
                return datetime.max

        # عنوان بديل للقضايا التي يرجع عنوانها فاضياً من METMONTH
        for c in cases:
            if not c['title']:
                c['title'] = get_title_fallback(cookies, c['caso_no'])

        cases.sort(key=lambda c: parse_date(c['received_date']))
        return cases
    except Exception as e:
        print(f"get_pending_cases ERROR: {e}")
        return []


def build_referred_report_html(cases, date_from, date_to, expert_name):
    """
    يبني تقرير HTML قابل للطباعة (نفس أسلوب weekly_report.py) لكل
    القضايا المحالة/الموزّعة على الخبير ضمن فترة معيّنة، بالاعتماد
    على 'تاريخ المباشرة' (received_date) — نفس مصدر بيانات
    get_pending_cases (رصيد الخبير بصفحة METMONTH).

    ⚠️ ملاحظة مهمة عن حدود هذا التقرير: يشمل بس القضايا المتداولة
    حالياً (اللي لسه ما اتقفل تقريرها/انسلّمت). قضية اتوزعت بالفترة
    المطلوبة لكن خلصت وأُقفلت قبل تاريخ توليد التقرير تختفي من رصيد
    الخبير بالنظام أصلاً ولن تظهر هنا — النظام ما يوفر سجل تاريخي كامل
    لكل القضايا الموزّعة (منتهية أو لا) بمكان واحد حالياً.

    cases: قائمة القضايا (نفس صيغة get_pending_cases — تشمل عادةً
    المتداولة + المحجوزة مجمّعة). date_from/date_to: كائنات datetime.
    يرجع مسار ملف HTML المُنشأ.
    """
    sf = date_from.strftime('%Y-%m-%d')
    ef = date_to.strftime('%Y-%m-%d')

    rows = [c for c in (cases or []) if sf <= (c.get('received_date') or '') <= ef]
    rows.sort(key=lambda c: c.get('received_date', ''))

    def esc(t):
        return html_lib.escape(str(t or ''))

    body_rows = ''
    if not rows:
        body_rows = '<tr><td colspan="4" class="empty">لا توجد قضايا محالة ضمن هذه الفترة</td></tr>'
    else:
        for i, c in enumerate(rows, start=1):
            try:
                d = datetime.strptime(c.get('received_date', ''), '%Y-%m-%d')
                date_disp = d.strftime('%Y/%m/%d')
            except Exception:
                date_disp = c.get('received_date', '') or '—'
            body_rows += (
                '<tr>'
                f'<td class="c">{i}</td>'
                f'<td class="c">{esc(date_disp)}</td>'
                f'<td class="c"><b>{esc(c.get("caso_no", ""))}</b></td>'
                f'<td class="e">{esc(c.get("title", "")) or "—"}</td>'
                '</tr>'
            )

    period_disp = f"{date_from.strftime('%Y/%m/%d')} — {date_to.strftime('%Y/%m/%d')}"

    html_doc = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>إحصائية القضايا المحالة</title>
<style>
  @page {{ size: A4 portrait; margin: 14mm 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
    direction: rtl; color: #1e2535; margin: 0; padding: 0;
  }}
  .header {{ text-align: center; border-bottom: 4px solid #1e2535; padding-bottom: 12px; margin-bottom: 20px; }}
  .header h1 {{ font-size: 26px; margin: 0 0 8px; }}
  .header .sub {{ font-size: 15px; color: #5a6a80; }}
  .meta {{ display: flex; justify-content: space-between; font-size: 14px; margin-bottom: 16px; }}
  .meta b {{ color: #1e2535; }}
  table {{ width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 13px; border: 2.5px solid #1e2535; }}
  th {{ background: #1e2535; color: #fff; padding: 8px 6px; text-align: center; border: 2px solid #1e2535; font-size: 13px; }}
  td {{ border: 2px solid #1e2535; padding: 7px 6px; vertical-align: top; word-wrap: break-word; overflow-wrap: break-word; }}
  td.c {{ text-align: center; white-space: nowrap; }}
  td.e {{ text-align: right; white-space: normal; }}
  tr:nth-child(even) td {{ background: #f7f9fc; }}
  .empty {{ text-align: center; color: #94a3b8; padding: 30px; font-size: 13px; }}
  .footer {{ margin-top: 18px; font-size: 12px; color: #94a3b8; text-align: center; }}
  @media print {{ .no-print {{ display: none; }} }}
</style>
</head>
<body onload="window.print()">
  <div class="header">
    <h1>إحصائية القضايا المحالة</h1>
    <div class="sub">وزارة العدل — نظام جلسات الخبراء</div>
  </div>
  <div class="meta">
    <div>الخبير: <b>{esc(expert_name)}</b></div>
    <div>الفترة: <b>{esc(period_disp)}</b></div>
    <div>عدد القضايا: <b>{len(rows)}</b></div>
  </div>
  <table>
    <thead>
      <tr>
        <th style="width:6%">م</th>
        <th style="width:16%">تاريخ المباشرة</th>
        <th style="width:20%">رقم الخبرة</th>
        <th style="width:58%">القضية</th>
      </tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>
  <div class="footer">
    ⚠️ هذا التقرير يشمل القضايا المتداولة حالياً فقط ضمن الفترة —
    القضايا الموزّعة بالفترة واللي خلصت وأُقفلت قبل توليد هذا التقرير
    لا تظهر هنا.
  </div>
</body>
</html>"""

    out_dir = os.path.join(os.path.expanduser("~"), "Desktop", "إحصائية القضايا المحالة")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"القضايا_المحالة_{date_from.strftime('%Y-%m-%d')}_الى_{date_to.strftime('%Y-%m-%d')}.html"
    path = os.path.join(out_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    return path


def get_reservation_date(cookies, caso_no):
    """
    يستخرج تاريخ جلسة الحجز الفعلي للقضية من سجل الحركة (ECS_CASE_FLOW)
    نصياً — بدون الاعتماد على ألوان التقويم (اللي أثبتت أنها هشّة).

    في ECS_CASE_FLOW تظهر كل جلسة كاسم نوعها (قد يحوي مدّات إطالة مثل
    'حجز للتقرير' أو 'مناقشــــــة') متبوعاً مباشرة بتاريخها (DD/MM/YYYY).
    نلقى آخر سطر يحوي كلمة 'حجز' ونأخذ التاريخ الذي يليه مباشرة.

    يرجع التاريخ بصيغة 'YYYY-MM-DD' (مطبَّعة)، أو '' إذا لم توجد جلسة حجز.
    """
    try:
        r = requests.post(f"{BASE_URL}/ECS_CASE_FLOW",
            data={'P_CASES': caso_no}, cookies=cookies, verify=False, timeout=10)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', r.text, re.DOTALL)
        tds = [re.sub(r'<[^>]+>', ' ', t).strip() for t in tds]
        tds = [t for t in tds if t and t != '&nbsp']

        date_re = re.compile(r'^\d{2}/\d{2}/\d{4}$')
        last_reserve_date = ''

        for i, cell in enumerate(tds):
            # 'حجز' تغطي كل أنواع الحجز (للتقرير/للصلح/للإعادة)
            if 'حجز' in cell:
                # التاريخ يلي اسم النوع مباشرة (أو أقرب تاريخ بعده)
                for j in range(i + 1, min(i + 3, len(tds))):
                    if date_re.match(tds[j]):
                        last_reserve_date = tds[j]  # نستمر لآخر حجز
                        break

        if last_reserve_date:
            try:
                return datetime.strptime(last_reserve_date, '%d/%m/%Y').strftime('%Y-%m-%d')
            except Exception:
                return last_reserve_date
        return ''
    except Exception as e:
        print(f"get_reservation_date ERROR ({caso_no}): {e}")
        return ''


_AFTER_SHOW = re.compile(r"aftershowImg\(\s*'([A-Za-z]\d{5,})'\s*,\s*'?(\d{6,12})'?\s*\)")


def reserved_autocase_map(html):
    """{رقم الخبرة: الرقم الآلي} من زر «الملف الالى» في كل سطر (aftershowImg('A2263970',260517110))."""
    return dict(_AFTER_SHOW.findall(html or ''))


def get_reserved_cases(cookies):
    """
    يجيب القضايا 'المحجوزة ولم تنجز' من نفس صفحة METMONTH، لكن بعد ضبط
    source_id='BookedNoEdecision' (نفس ما تفعله البطاقة الخضراء في الصفحة
    الرئيسية عبر set_sourc_type('BookedNoEdecision')).

    تنسيق الجدول هنا يختلف عن المتداولة: كل سجل يبدأ بخليتين فارغتين ''
    (زرّا «الملف الالى» و«تفاصيل»)، ويتكوّن من 8 خلايا بالترتيب (مُتحقَّق منه حياً 2026-10-21):
      [0]='' , [1]='' , [2]=رقم الاجراء (ليس الرقم الآلي!) , [3]=تاريخ المباشرة (DD/MM/YYYY),
      [4]=جلسة الحجز (YYYY-MM-DD), [5]=الرقم الآلي, [6]=رقم الخبرة, [7]=المدعى (قد يكون فارغاً)
    الرقم الآلي يُؤخذ أولاً من زر «الملف الالى» في السطر (reserved_autocase_map) فلا يتأثر بترتيب الأعمدة.

    يرجع قائمة dicts:
      {'caso_no', 'title', 'received_date', 'reserved_date', 'autocase_no'}
    مرتبة من الأقدم مباشرةً إلى الأحدث.

    ملاحظة: received_date هنا يُخزَّن بصيغة YYYY-MM-DD (مطبَّعة) ليكون
    متوافقاً مع بقية النظام، بينما يبقى عرض تاريخ المباشرة كما ورد.
    """
    try:
        # ضبط المصدر للقضايا المحجوزة قبل طلب الجدول
        requests.post(f"{BASE_URL}/includes/set_sourc.php",
            data={'source_id': 'BookedNoEdecision'}, cookies=cookies, verify=False, timeout=10)

        r = requests.get(f"{BASE_URL}/METMONTH", cookies=cookies, verify=False, timeout=10)
        auto_map = reserved_autocase_map(r.text)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', r.text, re.DOTALL)
        tds = [re.sub(r'<[^>]+>', '', t).strip() for t in tds]

        # نتعرّف على رقم القضية بصيغته المميزة (حرف واحد + أرقام) لتثبيت المطابقة
        caso_re = re.compile(r'^[A-Za-z]\d{5,}$')

        cases = []
        i = 0
        n = len(tds)
        while i < n:
            # بداية سجل: خليتان فارغتان متتاليتان
            if tds[i] == '' and i + 1 < n and tds[i+1] == '':
                block = tds[i:i+8]
                if len(block) == 8 and caso_re.match(block[6] or ''):
                    caso_no        = block[6]
                    # الرقم الآلي من رابط السطر نفسه (aftershowImg) ثم عمود «الرقم الالى» [5]؛ [2] = «رقم الاجراء»
                    # (رقم من 7 خانات ليس الرقم الآلي — كان يُؤخذ خطأً فيفشل الملف الآلي والحكم والصحيفة)
                    autocase_no    = auto_map.get(caso_no) or (block[5] if re.fullmatch(r'\d{6,12}', block[5] or '') else '')
                    action_no      = block[2]
                    onset_display  = block[3]   # تاريخ المباشرة كما ورد DD/MM/YYYY
                    reserved_date  = block[4]   # تاريخ جلسة الحجز YYYY-MM-DD
                    title          = block[7]

                    # تطبيع تاريخ المباشرة إلى YYYY-MM-DD للتوافق مع بقية النظام
                    received_norm = onset_display
                    try:
                        received_norm = datetime.strptime(onset_display, '%d/%m/%Y').strftime('%Y-%m-%d')
                    except Exception:
                        pass

                    cases.append({
                        'caso_no': caso_no,
                        'title': title,
                        'received_date': received_norm,
                        'reserved_date': reserved_date,
                        'autocase_no': autocase_no,
                        'action_no': action_no,
                    })
                    i += 8
                    continue
            i += 1

        def parse_date(d):
            try:
                return datetime.strptime(d, '%Y-%m-%d')
            except:
                return datetime.max

        # عنوان بديل عند غياب اسم القضية + تصحيح تاريخ الحجز من سجل الحركة
        for c in cases:
            if not c['title']:
                c['title'] = get_title_fallback(cookies, c['caso_no'])

            # تاريخ الحجز الوارد من METMONTH غير موثوق (يطلع 1900-01-01
            # أحياناً)؛ نستخرج التاريخ الفعلي نصياً من ECS_CASE_FLOW.
            rd = c.get('reserved_date', '')
            if (not rd) or rd.startswith('1900'):
                real = get_reservation_date(cookies, c['caso_no'])
                if real:
                    c['reserved_date'] = real

        cases.sort(key=lambda c: parse_date(c['received_date']))
        return cases
    except Exception as e:
        print(f"get_reserved_cases ERROR: {e}")
        return []


def sync_case_statuses(cases, reserved_map, current_user):
    """
    يحدّث حالة كل قضية بقاعدة البيانات المحلية (متداولة/محجوزة) بعد كل
    تحميل لهذي الصفحة، ويكتشف القضايا التي 'أُنجزت' (كانت مسجّلة متداولة
    أو محجوزة سابقًا لنفس الخبير، واختفت الآن من القائمتين الحيتين
    القادمتين من الموقع). الكتابة الفعلية تصير فقط عند تغيّر حقيقي
    (case_db.update_status لا يكتب لو الحالة نفسها لم تتغيّر).
    """
    caso_nos_now = {c['caso_no'] for c in cases}

    for c in cases:
        status = 'محجوزة' if c['caso_no'] in reserved_map else 'متداولة'
        try:
            case_db.update_status(c['caso_no'], status)
        except Exception as e:
            print(f"sync_case_statuses (update) ERROR ({c['caso_no']}): {e}")

    try:
        previously_active = case_db.get_active_caso_nos(current_user)
        for caso_no in previously_active:
            if caso_no not in caso_nos_now:
                case_db.update_status(caso_no, 'منجزة')
    except Exception as e:
        print(f"sync_case_statuses (completed) ERROR: {e}")


def ensure_case_type_and_committee(cases, cookies, current_user):
    """
    يستكشف نوع القضية (أصالة/استعانة) ولجنة/فردي تلقائياً — لكن فقط
    لأول مرة تظهر فيها القضية (لو case_type فاضي بالقاعدة المحلية،
    يعني لسه ما استُكشفت). المرات الجاية ما يعيد الطلب لنفس القضية
    (case_type محفوظ صار موجود)، عشان ما يبطّئ تحميل الصفحة كل مرة.

    يستخدم نفس دوال ui.py (get_case_type / get_experts) بدون أي تكرار
    منطق — فقط يربطها هنا بصفحة القضايا المتداولة تلقائياً.
    """
    from ui import get_case_type, get_experts

    for c in cases:
        caso_no = c['caso_no']
        cached = case_db.get_case(caso_no)
        # نتحقق من is_committee تحديداً (مو case_type) — قضايا سُجّلت
        # قبل إضافة هذي الميزة قد يكون عندها case_type معبّى من مصدر
        # ثاني (شاشة معلومات القضية) بينما is_committee لسه ما استُكشف
        # إطلاقاً. is_committee يبقى '' فقط لو لسه ما فُحص، بينما '0'
        # تعني فُحص فعلاً ووُجد إنه ليس لجنة.
        if cached and cached.get('is_committee') not in (None, ''):
            continue  # سبق استُكشفت — لا داعي لطلب إضافي

        try:
            case_type = get_case_type(cookies, caso_no, current_user) or 'أصالة'
            experts = get_experts(caso_no, cookies, current_user)
            case_db.save_case(
                caso_no,
                autocase_no=c.get('autocase_no', ''),
                expert_name=current_user,
                title=c.get('title', ''),
                received_date=c.get('received_date', ''),
                case_type=case_type,
                is_committee='1' if len(experts) > 1 else '0',
                committee_members=[e['name'] for e in experts] if len(experts) > 1 else [],
            )
        except Exception as e:
            print(f"ensure_case_type_and_committee ERROR ({caso_no}): {e}")


def build_pending_cases_page(parent, cookies, current_user):
    """
    يبني صفحة 'القضايا المحجوزة' داخل parent (نفس مكان صفحة الجلسات).

    الفكرة: نعرض قائمة القضايا المتداولة كاملةً، ونميّز بصرياً (خلفية زرقاء
    فاتحة) القضايا التي تكون كذلك 'محجوزة ولم تنجز'. العنوان والعدّاد يعكسان
    عدد القضايا المحجوزة. المطابقة بين القائمتين تتم عبر رقم القضية caso_no.
    """
    state = {'cases': [], 'reserved_map': {}}

    # الهيدر (نفس ستايل صفحة الجلسات)
    top = ctk.CTkFrame(parent, fg_color=WHITE, corner_radius=0, height=56,
        border_width=1, border_color=CARD_BD)
    top.pack(fill='x'); top.pack_propagate(False)

    refresh_btn = ctk.CTkButton(top, text="↻  تحديث", font=F(11),
        fg_color="transparent", border_width=1, border_color=CARD_BD,
        text_color=TEXT_M, hover_color="#f0f4ff", width=100, height=36,
        command=lambda: load_cases())
    refresh_btn.pack(side='left', padx=15, pady=10)

    cnt_lbl = ctk.CTkLabel(top, text="", font=F(13, True), text_color=TEXT_D)
    cnt_lbl.pack(side='right', padx=20)

    # المحتوى
    content = ctk.CTkFrame(parent, fg_color="transparent")
    content.pack(fill='both', expand=True, padx=30, pady=22)

    ctk.CTkLabel(content, text="القضايا المتداولة",
        font=F(24, True), text_color=TEXT_D).pack(anchor='e')
    ctk.CTkLabel(content, text="ملاحظة: القضايا المحجوزة ولم تُنجز مميّزة باللون الأزرق",
        font=F(12), text_color=TEXT_L).pack(anchor='e', pady=(3, 16))

    scroll = ctk.CTkScrollableFrame(content, fg_color="transparent",
        scrollbar_button_color=CARD_BD, scrollbar_button_hover_color=TEXT_L)
    scroll.pack(fill='both', expand=True)

    def render(cases, reserved_map):
        for w in scroll.winfo_children():
            w.destroy()

        if not cases:
            ctk.CTkLabel(scroll, text="لا توجد قضايا حالياً",
                font=F(14), text_color=TEXT_L).pack(pady=60)
            return

        for case in cases:
            reserved_info = reserved_map.get(case['caso_no'])
            build_case_row(scroll, case, cookies, current_user, reserved_info)

    def load_cases():
        cnt_lbl.configure(text="جاري التحميل...")
        parent.update()

        cases = get_pending_cases(cookies)
        reserved = get_reserved_cases(cookies)
        reserved_map = {c['caso_no']: c for c in reserved}

        # نضمن ظهور أي قضية محجوزة غير موجودة ضمن المتداولة (احتياطاً)
        known = {c['caso_no'] for c in cases}
        for rc in reserved:
            if rc['caso_no'] not in known:
                cases.append(rc)

        state['cases'] = cases
        state['reserved_map'] = reserved_map
        ensure_case_type_and_committee(cases, cookies, current_user)
        sync_case_statuses(cases, reserved_map, current_user)
        render(cases, reserved_map)
        cnt_lbl.configure(text=f"عدد القضايا المحجوزة: {len(reserved)}")

    load_cases()


def build_case_row(scroll, case, cookies, current_user, reserved_info=None):
    """
    بطاقة قضية واحدة — نفس تنسيق بطاقات الجلسات.
    - قضايا الاستعانة: خلفية وردية فاتحة (كما هو معتاد).
    - القضايا المحجوزة ولم تنجز: خلفية زرقاء فاتحة + سطر بتاريخ جلسة الحجز.
    """
    SECONDMENT_BG = "#fdf2f6"  # وردي فاتح جدًا — يميّز قضايا الاستعانة بصريًا فقط
    case_type = ''
    try:
        cached = case_db.get_case(case['caso_no'])
        if cached:
            case_type = cached.get('case_type', '')
    except Exception:
        pass

    is_reserved = reserved_info is not None

    # أولوية اللون: المحجوزة (أزرق) ثم الاستعانة (وردي) ثم العادي (أبيض)
    if is_reserved:
        row_bg = RESERVED_BG
        base_bd = RESERVED_BD
    elif case_type == 'استعانة':
        row_bg = SECONDMENT_BG
        base_bd = CARD_BD
    else:
        row_bg = CARD
        base_bd = CARD_BD

    row = ctk.CTkFrame(scroll, fg_color=row_bg, corner_radius=12,
        border_width=1, border_color=base_bd, cursor='hand2')
    row.pack(fill='x', pady=5, padx=4)

    row.bind('<Enter>', lambda e: row.configure(border_color=ACCENT))
    row.bind('<Leave>', lambda e: row.configure(border_color=base_bd))

    def open_info(e=None):
        open_case_info(scroll, case, cookies, current_user)

    # صف 1: رقم القضية + العنوان (يمين) + تاريخ المباشرة (يسار)
    r1 = ctk.CTkFrame(row, fg_color="transparent", cursor='hand2')
    r1.pack(fill='x', padx=18, pady=(14, 0))

    title_lbl = ctk.CTkLabel(r1, text=f"{case['caso_no']}  ·  {case['title'][:45]}",
        font=F(15, True), text_color=TEXT_D, anchor='e', cursor='hand2')
    title_lbl.pack(side='right')

    # الضغط على الصف أو صف العنوان أو نص العنوان نفسه يفتح شاشة معلومات القضية
    for w in (row, r1, title_lbl):
        w.bind('<Button-1>', open_info)

    date_display = case['received_date']
    try:
        d = datetime.strptime(case['received_date'], '%Y-%m-%d')
        date_display = d.strftime('%Y/%m/%d')
    except:
        pass

    date_lbl = ctk.CTkLabel(r1, text=f"تاريخ المباشرة: {date_display}",
        font=F(12, True), text_color=TEXT_D)
    date_lbl.pack(side='left')

    # سطر إضافي للقضايا المحجوزة: تاريخ جلسة الحجز + وسم "محجوزة"
    reserved_lbl = None
    if is_reserved:
        res_display = reserved_info.get('reserved_date', '')
        try:
            rd = datetime.strptime(res_display, '%Y-%m-%d')
            res_display = rd.strftime('%Y/%m/%d')
        except:
            pass

        r_extra = ctk.CTkFrame(row, fg_color="transparent")
        r_extra.pack(fill='x', padx=18, pady=(8, 0))

        badge = ctk.CTkLabel(r_extra, text="●  محجوزة ولم تُنجز",
            font=F(11, True), text_color=BLUE)
        badge.pack(side='right')

        reserved_lbl = ctk.CTkLabel(r_extra,
            text=f"جلسة الحجز: {res_display}",
            font=F(11, True), text_color=BLUE)
        reserved_lbl.pack(side='left')

        # عدّاد المتبقي للإنجاز: 21 يوم من تاريخ الحجز الفعلي (نظام
        # الخبراء يفرض إنجاز التقرير خلال هذي المهلة). نحسب الأيام
        # المتبقية لآخر يوم بالمهلة بالنسبة لتاريخ اليوم الفعلي.
        remaining_lbl = None
        try:
            reserved_date_raw = reserved_info.get('reserved_date', '')
            r_date = datetime.strptime(reserved_date_raw, '%Y-%m-%d')
            deadline = r_date + timedelta(days=21)
            remaining_days = (deadline.date() - datetime.now().date()).days

            if remaining_days < 0:
                remaining_text = f"⚠️ تجاوز الموعد بـ {abs(remaining_days)} يوم"
                remaining_color = "#e74c3c"
            elif remaining_days <= 3:
                remaining_text = f"⏰ متبقي على الإنجاز: {remaining_days} يوم"
                remaining_color = "#e74c3c"
            elif remaining_days <= 7:
                remaining_text = f"متبقي على الإنجاز: {remaining_days} يوم"
                remaining_color = "#e67e22"
            else:
                remaining_text = f"متبقي على الإنجاز: {remaining_days} يوم"
                remaining_color = BLUE

            r_extra2 = ctk.CTkFrame(row, fg_color="transparent")
            r_extra2.pack(fill='x', padx=18, pady=(4, 0))

            remaining_lbl = ctk.CTkLabel(r_extra2, text=remaining_text,
                font=F(11, True), text_color=remaining_color)
            remaining_lbl.pack(side='right')

            r_extra2.bind('<Button-1>', open_info)
            remaining_lbl.bind('<Button-1>', open_info)
        except Exception:
            pass

        for w in (r_extra, badge, reserved_lbl):
            w.bind('<Button-1>', open_info)

    # صف 2: زر محضر أول جلسة (يسار) — بنفس ستايل زر طباعة المحضر في الجلسات
    r2 = ctk.CTkFrame(row, fg_color="transparent")
    r2.pack(fill='x', padx=18, pady=(10, 14))

    # نوسّع منطقة الضغط لتشمل كل الصف (التاريخ + صف الزر) — زر الطباعة
    # نفسه له command منفصل خاص به، فما يتأثر بهذا الربط الإضافي
    for w in (date_lbl, r2):
        w.bind('<Button-1>', open_info)

    ctk.CTkButton(r2, text="🖨  محضر أول جلسة", font=F(12, True),
        width=160, height=36, fg_color=BLUE, hover_color="#2980b9",
        text_color=WHITE, corner_radius=8,
        command=lambda c=case: print_first_session(scroll, c, cookies, current_user)
    ).pack(side='left')

    # زر ملخص القضية: يعرض المخزّن فقط (بدون أي استدعاء Gemini) — ستايل
    # ثانوي (نفس زر 'تحديث' بالهيدر) بنفس ارتفاع زر المحضر وبنفس الفاصل
    ctk.CTkButton(r2, text="📄  ملخص القضية", font=F(12, True),
        width=140, height=36, fg_color="transparent", border_width=1,
        border_color=CARD_BD, text_color=TEXT_M, hover_color="#f0f4ff",
        corner_radius=8,
        command=lambda c=case: show_case_summary(c)
    ).pack(side='left', padx=(10, 0))


def show_case_summary(case):
    """يعرض ملخص القضية المخزّن محلياً فقط، أو رسالة لو ما توفر بعد"""
    try:
        summary = (case_db.get_case(case['caso_no']) or {}).get('case_summary', '')
    except Exception:
        summary = ''
    messages = {
        'NO_AUTOCASE': "لا يوجد ملف آلي مرتبط بهذي القضية",
        'NO_CLAIM_DOC': "لم يتم العثور على صحيفة الدعوى ضمن مستندات القضية",
    }
    messagebox.showinfo(f"ملخص القضية {case['caso_no']}",
        messages.get(summary) or summary or "لم يتوفر ملخص بعد")


def open_case_info(parent, case, cookies, current_user):
    """يفتح شاشة معلومات القضية (عرض/تعديل/استخراج تلقائي) للقضية المحددة"""
    from case_info_window import open_case_info_window
    open_case_info_window(parent.winfo_toplevel(), cookies, current_user, case)


def print_first_session(parent, case, cookies, current_user):
    """
    يتأكد أول شي من بيانات القضية بالقاعدة (يجلبها تلقائيًا لو ناقصة —
    شاشة انتظار/إدخال يدوي حسب الحاجة)، وبعدها يفتح نافذة محضر أول
    جلسة (الحالة الافتراضية) مع تمرير البيانات الجاهزة لتعبيتها تلقائيًا.
    """
    from case_info_window import ensure_case_data
    from first_session import open_first_session_window

    toplevel = parent.winfo_toplevel()
    case_data = ensure_case_data(toplevel, cookies, current_user, case)
    open_first_session_window(
        toplevel, cookies, current_user,
        case['caso_no'], case['received_date'], case_data=case_data
    )