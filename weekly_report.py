# ===== weekly_report.py — كشف الجلسات الأسبوعي (للطباعة) =====
"""
يبني كشف جلسات لفترة معيّنة (هذا الأسبوع / الأسبوع القادم / فترة
مخصّصة) بصيغة HTML جاهزة للطباعة على ورقة A4 — يفتح بالمتصفح
الافتراضي مباشرة مع نافذة طباعة تلقائية، بدون أي حاجة لمكتبات
خارجية إضافية (نفس فلسفة بقية المشروع بتفادي أي dependency جديدة).

اخترنا HTML بدل قالب Word لأن هذا كشف بعدد صفوف متغيّر (قد يكون
صفر جلسات أو عشرات) — التنسيق بالمتصفح مع CSS طباعة (@page) أبسط
وأثبت من محاولة حقن صفوف جدول ديناميكيًا داخل XML ملف .dotx.
"""
import os
import html as html_lib
from datetime import datetime, timedelta

from config import DAYS_AR
import case_db


def _week_bounds(reference=None, offset_weeks=0):
    """
    يرجع (بداية الأسبوع = الأحد، نهاية الأسبوع = الخميس) بصيغة
    datetime، بناءً على أسبوع العمل بالكويت (الأحد → الخميس).
    """
    d = reference or datetime.now()
    # Python: الاثنين=0 ... الأحد=6. نحسب فرق الأيام عن أقرب أحد سابق (أو نفسه لو هو أحد)
    days_since_sunday = (d.weekday() + 1) % 7
    sunday = d - timedelta(days=days_since_sunday)
    sunday = sunday.replace(hour=0, minute=0, second=0, microsecond=0)
    sunday += timedelta(weeks=offset_weeks)
    thursday = sunday + timedelta(days=4)
    return sunday, thursday


def suggest_default_period():
    """
    اقتراح افتراضي ذكي حسب يوم الأسبوع الحالي:
    - خميس/جمعة/سبت (آخر يوم دوام أو عطلة): الافتراضي "الأسبوع القادم"
      لأن أسبوع العمل الحالي خلص أو راح ينخلص.
    - أحد (أول يوم بالأسبوع): الافتراضي "هذا الأسبوع" — الأسبوع للتو بدأ.
    - اثنين/ثلاثاء/أربعاء: الافتراضي "الأسبوع القادم".
    يرجع 'this' أو 'next'.
    """
    wd = datetime.now().weekday()  # الاثنين=0 ... الأحد=6
    if wd == 6:  # الأحد
        return 'this'
    if wd in (3, 4, 5):  # الخميس، الجمعة، السبت
        return 'next'
    return 'next'  # الاثنين/الثلاثاء/الأربعاء


def _day_name_ar(d):
    return DAYS_AR.get(d.weekday(), '')


def _parties_lookup(caso, cookies, current_user, _cache={}):
    """
    يرجع (المدعي، المدعى عليه) كنص جاهز للعرض. يفضّل القاعدة المحلية
    (case_db — مستخرجة بالذكاء الاصطناعي من حكم الإحالة، أدق) لو
    متوفرة وكاملة، لكن لو القضية غير موجودة بالقاعدة، أو موجودة بدون
    أطراف (لم يُسحب حكم الإحالة بعد، أو لا يوجد ملف من الأساس)، يرجع
    تلقائيًا لجلب البيانات حيًا من النظام الأساسي (parse_case_info)
    بدل ما يرجع فراغ بصمت — بنفس فلسفة get_case_parties_summary
    بـapi.py. لا يُحفَظ الناتج الحي بالقاعدة المحلية (تجنّبًا لتخزين
    سجل جزئي قد يمنع لاحقًا استخراج الحكم الكامل من شاشة تفاصيل
    القضية)، فقط يُستخدم لعرض الكشف الحالي.
    """
    if caso in _cache:
        return _cache[caso]

    pl, df = [], []
    try:
        cached = case_db.get_case(caso)
        if cached:
            pl = cached.get('plaintiffs') or []
            df = cached.get('defendants') or []
    except Exception:
        pass

    if not pl and not df and cookies:
        try:
            from api import parse_case_info  # استيراد مؤجَّل لتفادي دورة استيراد
            info = parse_case_info(caso, cookies, current_user)
            pl = info.get('plaintiffs', [])
            df = info.get('defendants', [])
        except Exception:
            pass

    result = ('، '.join(pl) if pl else '', '، '.join(df) if df else '')
    _cache[caso] = result
    return result


def _experts_names_label(caso, cookies, expert_name, _cache={}):
    """
    يرجع اسم الخبير (أو أسماء أعضاء اللجنة مفصولين بفاصلة لو أكثر من
    خبير) — يجلبها حيًا من سجل الحركة (get_experts) في كل مرة طالما
    فيه اتصال، بدل الاعتماد على قيمة مخزّنة قد تكون قديمة. لو تعذّر
    الجلب الحي (لا يوجد كوكيز أو فشل الطلب)، يرجع اسم الخبير الحالي
    (expert_name) كخط دفاع أخير بدل ما يرجع فراغ. _cache قاموس داخلي
    لتفادي تكرار نفس الطلب الشبكي أكثر من مرة لنفس القضية خلال نفس
    عملية بناء الكشف الواحدة.
    """
    if caso in _cache:
        return _cache[caso]

    names = []
    if cookies:
        try:
            from ui import get_experts  # استيراد مؤجَّل لتفادي دورة استيراد مع ui.py
            experts = get_experts(caso, cookies, '')
            names = [e['name'] for e in experts if e.get('name')]
            try:
                case_db.save_case(caso, is_committee='1' if len(names) > 1 else '0')
            except Exception:
                pass
        except Exception:
            names = []

    label = '، '.join(names) if names else (expert_name or '—')
    _cache[caso] = label
    return label


def build_weekly_report_html(sessions, start_date, end_date, expert_name,
                              orientation='landscape', cookies=None):
    """
    sessions: قائمة dict فيها 'description' (رقم القضية)، 'start'
    ('YYYY-MM-DD HH:MM')، 'title' (قد يحوي رقم القضية بالبداية).
    start_date / end_date: كائنات datetime (حدود الفترة المطلوبة شاملة).
    orientation: 'landscape' (افتراضي — بالعرض) أو 'portrait' (بالطول).
    cookies: تُستخدم لتحديد نوع الجلسة (الخبير/اللجنة) حيًا من سجل
    الحركة، وكذلك كخط دفاع أخير لجلب أطراف القضية (المدعي/المدعى عليه)
    لو غير محفوظة بالقاعدة المحلية — اختيارية، لو ما مرّرت يرجع '—'
    لنوع الجلسة وفراغ للأطراف غير المتوفرة محليًا.
    يرجع مسار ملف الـ HTML المُنشأ.
    """
    sf = start_date.strftime('%Y-%m-%d')
    ef = end_date.strftime('%Y-%m-%d')

    rows = []
    for s in sessions or []:
        parts = (s.get('start') or '').split(' ')
        raw_date = parts[0] if parts else ''
        # نظام الوزارة يرجّع التاريخ أحيانًا بفاصل '/' (مثل بقية النظام:
        # SmartDateEntry وinsert.php) وأحيانًا '-' — نوحّدها لـ '-' حتى
        # تصير المقارنة النصية بين sf/ef والتاريخ صحيحة دائمًا (كانت
        # المقارنة تفشل بصمت لو التنسيقات غير متطابقة، فيطلع الكشف فاضي
        # حتى لو فيه جلسات فعلية بهذه الفترة).
        date = raw_date.replace('/', '-')
        time = parts[1] if len(parts) > 1 else ''
        if not (sf <= date <= ef):
            continue
        caso = s.get('description', '')
        try:
            dd = datetime.strptime(date, '%Y-%m-%d')
            day_name = _day_name_ar(dd)
            date_disp = dd.strftime('%Y/%m/%d')
        except Exception:
            day_name, date_disp = '', date
        try:
            h, mn = int(time.split(':')[0]), int(time.split(':')[1])
            sfx = 'ص' if h < 12 else 'م'
            dh = h if h <= 12 else h - 12
            time_disp = f"{dh:02d}:{mn:02d} {sfx}"
        except Exception:
            time_disp = time
        plaintiff, defendant = _parties_lookup(caso, cookies, expert_name)
        experts_names = _experts_names_label(caso, cookies, expert_name)
        rows.append({
            'date': date, 'day': day_name, 'date_disp': date_disp,
            'time_disp': time_disp, 'caso': caso,
            'plaintiff': plaintiff, 'defendant': defendant,
            'experts_names': experts_names,
        })

    rows.sort(key=lambda r: (r['date'], r['time_disp']))

    # نفس منطق إزالة التكرار المستخدم بشاشة الجلسات (_dedupe_same_day):
    # نفس رقم القضية + نفس اليوم = نفس الجلسة الفعلية (يصير تكرارها من
    # النظام نفسه لو أكثر من عضو لجنة أضاف جلسته بنفس اليوم). نبقي أول
    # ظهور (الأسبق بالوقت بعد الترتيب فوق) ونشيل الباقي.
    seen = set()
    deduped = []
    for r in rows:
        key = (r['caso'], r['date'])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    rows = deduped

    def esc(t):
        return html_lib.escape(str(t or ''))

    body_rows = ''
    if not rows:
        body_rows = (
            '<tr><td colspan="7" class="empty">لا توجد جلسات ضمن هذه '
            'الفترة</td></tr>'
        )
    else:
        for i, r in enumerate(rows, start=1):
            body_rows += (
                '<tr>'
                f'<td class="c">{i}</td>'
                f'<td class="c">{esc(r["day"])}<br><span class="dt">{esc(r["date_disp"])}</span></td>'
                f'<td class="c">{esc(r["time_disp"])}</td>'
                f'<td class="c"><b>{esc(r["caso"])}</b></td>'
                f'<td class="x">{esc(r["experts_names"])}</td>'
                f'<td class="e">{esc(r["plaintiff"]) or "—"}</td>'
                f'<td class="e">{esc(r["defendant"]) or "—"}</td>'
                '</tr>'
            )

    period_disp = f"{start_date.strftime('%Y/%m/%d')} — {end_date.strftime('%Y/%m/%d')}"
    page_orient = 'landscape' if orientation == 'landscape' else 'portrait'

    # تحجيم تلقائي حسب عدد الصفوف — عشان الجدول يضل بصفحة وحدة دايمًا
    # مهما كان عدد الجلسات، بحد أقصى 15 جلسة بالصفحة الواحدة (بعدها
    # طبيعي يفيض لصفحة ثانية — 15 هو أقصى ما يقدر يتحمّله A4 بخط
    # مقروء). درجات أدق من قبل (كانت 7 جلسات تفيض بالخط الكبير)، وكل
    # عنصر بالصفحة يصغر مع الرأس والهوامش، مو بس الجدول، عشان المساحة
    # المتوفرة للجدول تكبر فعليًا مع زيادة عدد الصفوف.
    row_count = len(rows)
    if row_count <= 5:
        f_body, f_th, f_meta, td_pad = "16px", "16px", "15px", "10px 8px"
        h1_size, sub_size, hdr_pad, hdr_mb = "24px", "14px", "10px", "16px"
    elif row_count <= 8:
        f_body, f_th, f_meta, td_pad = "13px", "13px", "13px", "7px 6px"
        h1_size, sub_size, hdr_pad, hdr_mb = "20px", "12px", "8px", "12px"
    elif row_count <= 11:
        f_body, f_th, f_meta, td_pad = "11px", "11px", "11px", "5px 5px"
        h1_size, sub_size, hdr_pad, hdr_mb = "17px", "11px", "6px", "9px"
    elif row_count <= 15:
        f_body, f_th, f_meta, td_pad = "9.5px", "9.5px", "10px", "3px 4px"
        h1_size, sub_size, hdr_pad, hdr_mb = "15px", "10px", "5px", "7px"
    else:
        f_body, f_th, f_meta, td_pad = "9px", "9px", "9px", "2px 3px"
        h1_size, sub_size, hdr_pad, hdr_mb = "14px", "9px", "4px", "6px"

    html_doc = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>كشف الجلسات الأسبوعي</title>
<style>
  @page {{ size: A4 {page_orient}; margin: {"14mm 12mm" if row_count <= 5 else "9mm 10mm"}; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
    direction: rtl; color: #1e2535; margin: 0; padding: 0;
  }}
  .header {{ text-align: center; border-bottom: 3px solid #1e2535; padding-bottom: {hdr_pad}; margin-bottom: {hdr_mb}; }}
  .header h1 {{ font-size: {h1_size}; margin: 0 0 4px; }}
  .header .sub {{ font-size: {sub_size}; color: #5a6a80; }}
  .meta {{ display: flex; justify-content: space-between; font-size: {f_meta}; margin-bottom: {hdr_mb}; }}
  .meta b {{ color: #1e2535; }}
  table {{ width: 100%; table-layout: fixed; border-collapse: collapse; font-size: {f_body}; border: 2.5px solid #1e2535; }}
  th {{ background: #1e2535; color: #fff; padding: {td_pad}; text-align: center; border: 2px solid #1e2535; font-size: {f_th}; }}
  td {{ border: 2px solid #1e2535; padding: {td_pad}; vertical-align: top; word-wrap: break-word; overflow-wrap: break-word; }}
  td.c {{ text-align: center; white-space: nowrap; }}
  td.x {{ text-align: center; white-space: normal; }}
  td.e {{ text-align: right; white-space: normal; }}
  tr:nth-child(even) td {{ background: #f7f9fc; }}
  .dt {{ color: #5a6a80; font-size: 0.85em; }}
  .ttl {{ color: #5a6a80; font-size: 0.9em; }}
  .empty {{ text-align: center; color: #94a3b8; padding: 30px; font-size: {f_body}; }}
  .footer {{ margin-top: 22px; font-size: 12.5px; color: #94a3b8; text-align: center; }}
  @media print {{
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body onload="window.print()">
  <div class="header">
    <h1>كشف الجلسات الأسبوعي</h1>
    <div class="sub">وزارة العدل — نظام جلسات الخبراء</div>
  </div>
  <div class="meta">
    <div>الخبير: <b>{esc(expert_name)}</b></div>
    <div>الفترة: <b>{esc(period_disp)}</b></div>
  </div>
  <table>
    <thead>
      <tr>
        <th style="width:4%">م</th>
        <th style="width:11%">اليوم / التاريخ</th>
        <th style="width:7%">الوقت</th>
        <th style="width:13%">رقم الخبرة</th>
        <th style="width:13%">اسم الخبير</th>
        <th style="width:25%">المدعي</th>
        <th style="width:27%">المدعى عليه</th>
      </tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>
</body>
</html>"""

    out_dir = os.path.join(os.path.expanduser("~"), "Desktop", "كشوفات الجلسات")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"كشف_جلسات_{start_date.strftime('%Y-%m-%d')}_الى_{end_date.strftime('%Y-%m-%d')}.html"
    path = os.path.join(out_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    return path
