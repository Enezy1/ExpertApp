# ===== department_report.py — كشف جلسات القسم (كل الخبراء أو خبير معيّن) =====
"""
مصدر بيانات مختلف تمامًا عن weekly_report.py: ذاك يجيب جلسات الخبير
الحالي حيًا من نظام الخبراء (load.php) — هنا نجيب من قاعدة القسم
المحلية (ExpretDB.MDB، جدول [الاحداث] مربوط بـ[main]) لأنها المصدر
الوحيد المتوفر لجلسات أي خبير ثاني غير الخبير المسجّل دخوله حالياً
(نظام الخبراء أونلاين ما يعرض إلا "جلساتي أنا").

نفس تصميم/تحجيم جدول 'كشف الجلسات الأسبوعي' بالضبط (weekly_report.py):
نفس الأعمدة، نفس درجات تصغير الخط حسب عدد الصفوف (تضمن بقاء جلسات كل
خبير بصفحة وحدة). الفرق هنا: كل خبير يحصل على صفحته المستقلة الخاصة
داخل نفس الملف (فاصل صفحة تلقائي بين كل خبير والتالي)، بدل جدول واحد
مجمّع للكل.
"""
import os
import html as html_lib
from datetime import datetime

from config import DAYS_AR
from db_writer import get_department_week_sessions


def _day_name_ar(d):
    return DAYS_AR.get(d.weekday(), '')


def _size_tiers(row_count):
    """نفس الدرجات المستخدمة بالضبط بـweekly_report.py — تضمن بقاء
    جدول أي خبير بصفحة A4 وحدة مهما زاد عدد جلساته (حتى 15 جلسة)."""
    if row_count <= 5:
        return dict(f_body="16px", f_th="16px", f_meta="15px", td_pad="10px 8px",
                     h1_size="22px", sub_size="13px", hdr_pad="8px", hdr_mb="14px")
    if row_count <= 8:
        return dict(f_body="13px", f_th="13px", f_meta="13px", td_pad="7px 6px",
                     h1_size="19px", sub_size="12px", hdr_pad="6px", hdr_mb="10px")
    if row_count <= 11:
        return dict(f_body="11px", f_th="11px", f_meta="11px", td_pad="5px 5px",
                     h1_size="16px", sub_size="11px", hdr_pad="5px", hdr_mb="8px")
    if row_count <= 15:
        return dict(f_body="9.5px", f_th="9.5px", f_meta="10px", td_pad="3px 4px",
                     h1_size="14px", sub_size="10px", hdr_pad="4px", hdr_mb="6px")
    return dict(f_body="9px", f_th="9px", f_meta="9px", td_pad="2px 3px",
                h1_size="13px", sub_size="9px", hdr_pad="3px", hdr_mb="5px")


def _build_page(expert_name, rows, period_disp, is_last):
    """يبني صفحة واحدة (لخبير واحد) — نفس هيكل جدول weekly_report.py
    بالضبط لكن بستايلات inline (مو selectors عامة) عشان كل صفحة تقدر
    تاخذ حجم خط مختلف حسب عدد جلساتها هي."""
    def esc(t):
        return html_lib.escape(str(t or ''))

    t = _size_tiers(len(rows))

    body_rows = ''
    if not rows:
        body_rows = (
            f'<tr><td colspan="7" style="text-align:center;color:#94a3b8;'
            f'padding:30px;font-size:{t["f_body"]};border:2px solid #1e2535;">'
            'لا توجد جلسات ضمن هذه الفترة</td></tr>'
        )
    else:
        for i, r in enumerate(rows, start=1):
            td_style = f'border:2px solid #1e2535; padding:{t["td_pad"]}; vertical-align:top; word-wrap:break-word;'
            body_rows += (
                '<tr>'
                f'<td style="{td_style} text-align:center; white-space:nowrap;">{i}</td>'
                f'<td style="{td_style} text-align:center; white-space:nowrap;">{esc(r["day"])}<br>'
                f'<span style="color:#5a6a80; font-size:0.85em;">{esc(r["date_disp"])}</span></td>'
                f'<td style="{td_style} text-align:center; white-space:nowrap;">{esc(r["time_disp"])}</td>'
                f'<td style="{td_style} text-align:center; white-space:nowrap;"><b>{esc(r["ref"])}</b></td>'
                f'<td style="{td_style} text-align:center; white-space:normal;">{esc(r["type"])}</td>'
                f'<td style="{td_style} text-align:right; white-space:normal;">{esc(r["name_c"]) or "—"}</td>'
                f'<td style="{td_style} text-align:right; white-space:normal;">{esc(r["name_p"]) or "—"}</td>'
                '</tr>'
            )

    page_break = '' if is_last else 'page-break-after: always;'

    return f"""
<div style="{page_break} padding: 6mm 4mm;">
  <div style="text-align:center; border-bottom:3px solid #1e2535; padding-bottom:{t['hdr_pad']}; margin-bottom:{t['hdr_mb']};">
    <h1 style="font-size:{t['h1_size']}; margin:0 0 4px;">كشف جلسات الخبير — {esc(expert_name)}</h1>
    <div style="font-size:{t['sub_size']}; color:#5a6a80;">وزارة العدل — الإدارة العامة للخبراء</div>
  </div>
  <div style="display:flex; justify-content:space-between; font-size:{t['f_meta']}; margin-bottom:{t['hdr_mb']};">
    <div>الخبير: <b>{esc(expert_name)}</b></div>
    <div>الفترة: <b>{esc(period_disp)}</b></div>
  </div>
  <table style="width:100%; table-layout:fixed; border-collapse:collapse; font-size:{t['f_body']}; border:2.5px solid #1e2535;">
    <thead>
      <tr>
        <th style="width:4%; background:#1e2535; color:#fff; padding:{t['td_pad']}; text-align:center; border:2px solid #1e2535; font-size:{t['f_th']};">م</th>
        <th style="width:11%; background:#1e2535; color:#fff; padding:{t['td_pad']}; text-align:center; border:2px solid #1e2535; font-size:{t['f_th']};">اليوم/التاريخ</th>
        <th style="width:7%; background:#1e2535; color:#fff; padding:{t['td_pad']}; text-align:center; border:2px solid #1e2535; font-size:{t['f_th']};">الوقت</th>
        <th style="width:12%; background:#1e2535; color:#fff; padding:{t['td_pad']}; text-align:center; border:2px solid #1e2535; font-size:{t['f_th']};">رقم الخبرة</th>
        <th style="width:14%; background:#1e2535; color:#fff; padding:{t['td_pad']}; text-align:center; border:2px solid #1e2535; font-size:{t['f_th']};">نوع الجلسة</th>
        <th style="width:26%; background:#1e2535; color:#fff; padding:{t['td_pad']}; text-align:center; border:2px solid #1e2535; font-size:{t['f_th']};">المدعي</th>
        <th style="width:26%; background:#1e2535; color:#fff; padding:{t['td_pad']}; text-align:center; border:2px solid #1e2535; font-size:{t['f_th']};">المدعى عليه</th>
      </tr>
    </thead>
    <tbody>{body_rows}</tbody>
  </table>
</div>"""


def build_department_week_report_html(date_from, date_to, expert_filter=None):
    """
    date_from/date_to: كائنات datetime.date أو datetime (حدود الفترة
    شاملة). expert_filter: اسم خبير محدد (صفحة وحدة له فقط) أو None
    (صفحة مستقلة لكل خبير له جلسة بهذي الفترة، بنفس تصميم كشف الجلسات
    الأسبوعي بالضبط). يرجع مسار ملف الـHTML المُنشأ.
    """
    rows = get_department_week_sessions(date_from, date_to)
    period_disp = f"{date_from.strftime('%Y/%m/%d')} — {date_to.strftime('%Y/%m/%d')}"

    def fmt(r):
        try:
            day_name = _day_name_ar(r['date'])
            date_disp = r['date'].strftime('%Y/%m/%d')
        except Exception:
            day_name, date_disp = '', str(r['date'])
        try:
            time_disp = r['time'].strftime('%H:%M')
        except Exception:
            time_disp = str(r['time'] or '')
        return {
            'day': day_name, 'date_disp': date_disp, 'time_disp': time_disp,
            'type': r['type'], 'ref': r['ref'],
            'name_c': r['name_c'], 'name_p': r['name_p'],
        }

    # نبني قاموس خبير -> صفوفه (كل جلسة تُنسَب لكل خبير مسند لها —
    # قضية لجنة تظهر بنفس الجلسة بصفحة كل عضو من أعضائها).
    by_expert = {}
    for r in rows:
        experts = r['experts'] or []
        if expert_filter:
            experts = [e for e in experts if e.strip() == expert_filter.strip()]
        for e in experts:
            by_expert.setdefault(e, []).append(fmt(r))

    expert_names = sorted(by_expert.keys(), key=lambda n: n)
    if expert_filter and expert_filter not in by_expert:
        expert_names = [expert_filter]
        by_expert[expert_filter] = []

    for name in expert_names:
        by_expert[name].sort(key=lambda r: (r['date_disp'], r['time_disp']))

    if not expert_names:
        expert_names = ["—"]
        by_expert["—"] = []

    pages = [
        _build_page(name, by_expert[name], period_disp, is_last=(idx == len(expert_names) - 1))
        for idx, name in enumerate(expert_names)
    ]

    html_doc = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>كشف جلسات القسم</title>
<style>
  @page {{ size: A4 landscape; margin: 8mm 6mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family:'Segoe UI', Tahoma, Arial, sans-serif; direction:rtl; color:#1e2535; margin:0; padding:0; }}
  tr:nth-child(even) td {{ background:#f7f9fc; }}
</style>
</head>
<body onload="window.print()">
{''.join(pages)}
</body>
</html>"""

    out_dir = os.path.join(os.path.expanduser("~"), "Desktop", "كشوفات الجلسات")
    os.makedirs(out_dir, exist_ok=True)
    suffix = expert_filter.replace(' ', '_') if expert_filter else 'كل_الخبراء'
    fname = f"كشف_جلسات_القسم_{date_from.strftime('%Y-%m-%d')}_الى_{date_to.strftime('%Y-%m-%d')}_{suffix}.html"
    path = os.path.join(out_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    return path
