# ===== qt_main1.py — إضافة قضية جديدة (رئيس القسم) — تصميم Executive الجديد =====
# نسخة Qt من MAIN1.py الأصلية — نفس منطق الاستخراج والكتابة بقاعدة
# ExpretDB.MDB بدون أي تعديل (db_writer.py / main1_config.py كما هي
# تمامًا)، فقط طبقة العرض جديدة بالكامل ومدمجة داخل التطبيق الرئيسي
# (بدل برنامج منفصل) — تفتح من صفحة الإعدادات، وتظهر فقط للخبير
# المخوَّل (رئيس القسم).
import os
import re
import sys
import html as html_lib

from PyQt6.QtCore import Qt, QRegularExpression, QEvent
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QMessageBox, QScrollArea, QApplication, QFileDialog, QFormLayout,
    QRadioButton, QListWidget,
)

import qt_theme as th
from qt_widgets import Card, PrimaryButton, SecondaryButton, SmartDateEdit

import requests
from datetime import datetime, timedelta
from config import BASE_URL, DAYS_AR
from api import parse_case_info
from documents import get_referral_judgment_for_case
from case_info_window import extract_from_pdf, autocorrect_hearing_date
from gemini_config import has_api_key, save_api_key, load_api_key, mask_key

from db_writer import (
    parse_expertise_number, parse_court_case_number,
    build_experts_dash_string, today_ddmmyyyy, insert_case_record, get_expert_names,
)
from department_report import build_department_week_report_html
from main1_config import load_db_path, save_db_path
import case_db

# دوال منطقية بحتة (لا تعتمد على tkinter) — نعيد استخدامها من ui.py كما هي
# (نفس أسلوب qt_sessions_page.py): get_case_type يكشف أصالة/استعانة من
# سجل الحركة، get_experts يجيب آخر خبير/لجنة انسندت لهم القضية.
from ui import get_case_type, get_experts

SPECIALTY_OPTIONS = ["كهرباء 15", "كمبيوتر 24"]
COMM_OPTIONS = ["الخبير لوحده", "لجنة ثلاثية"]

SECONDMENT_BG = th.SECONDMENT_BG  # وردي/أحمر فاتح جداً — نفس اللون المستخدم بباقي شاشات النظام لتمييز الاستعانة


def _detect_type_option(raw_court_no, case_type):
    """
    يحدد أحد الخيارات الأربعة بـTYPE_OPTIONS تلقائياً:
    - موضوعي/مستعجل: من وجود كلمة 'مستعجل' بنص رقم الدعوى الخام
      (أي صيغة، مثال: 'مستعجل العاصمة').
    - أصالة/استعانة: من case_type (نتيجة get_case_type).
    """
    urgent = 'مستعجل' in (raw_court_no or '')
    base = 'مستعجل' if urgent else 'موضوعي'
    if case_type == 'استعانة':
        return f'استعانة {base}'
    return base


def _day_name_ddmmyyyy(date_str):
    """
    يرجع اسم اليوم بالعربي لتاريخ بصيغة DD/MM/YYYY — نفس صيغة تواريخ
    الحكم/الجلسة المستخرجة بهذا الملف (api.get_day_name يتوقع صيغة
    YYYY/MM/DD المستخدمة بشاشات الجلسات، فما تصلح هنا مباشرة).
    """
    try:
        d = datetime.strptime((date_str or '').strip()[:10], '%d/%m/%Y')
        return DAYS_AR[d.weekday()]
    except Exception:
        return ''


def _bdi(text, direction):
    """
    يبني <bdi> (Bidirectional Isolate) يفرض اتجاه معيّن (ltr/rtl) على
    جزء نص لحاله بدون ما يخليه يتأثر بالنص المجاور أو ينعكس بصريًا —
    نستخدمها بالملصق عشان الأرقام (رقم الدعوى، التواريخ) تبقى بترتيبها
    الصحيح داخل سطر عربي (RTL)، بدل ما تنعكس بسبب خوارزمية الاتجاه
    ثنائي الاتجاه لما يختلط رقم إنجليزي مع نص/سياق عربي.
    """
    t = html_lib.escape(str(text or '').strip())
    return f'<bdi dir="{direction}">{t}</bdi>' if t else ''


TYPE_OPTIONS = ["موضوعي", "مستعجل", "استعانة موضوعي", "استعانة مستعجل"]

# أسماء الخبير المخوَّل الوحيد لهذي الميزة حاليًا — نتحمّل صياغتين
# محتملتين لحرف الألف المقصورة/الياء الأخيرة ("العنزي"/"العنزى")
# لأن النظام الحكومي نفسه غير ثابت بهذا الخصوص بمكان لمكان.
# الصلاحية تُدار أونلاين بالاسم عبر Supabase (main1_access.py) بدل قائمة الأسماء
# الثابتة القديمة — المالك مخوّل دائمًا، وغيره يُمنح بالاسم من نافذة الإعدادات.
import main1_access
from current_expert import get_current_account


def is_authorized_for_main1(current_user):
    """يحدد هل الخبير الحالي مخوَّل يشوف/يستخدم ميزة إضافة قضية جديدة لرئيس القسم"""
    return main1_access.is_authorized_for_main1(current_user, get_current_account())


def open_main1_dialog(parent, cookies, current_user):
    """تحتفظ بنفس الاسم القديم للتوافق، لكن لم تعد تفتح نافذة منفصلة —
    Main1Page الآن صفحة مدمجة بنفس نافذة البرنامج الرئيسية (يستخدمها
    qt_shell.py مباشرة بدل هذي الدالة). أُبقيها فقط لأي استدعاء قديم
    متبقٍّ، بديل احتياطي يفتحها نافذة مستقلة لو استُدعيت فعليًا."""
    page = Main1Page(parent, cookies, current_user)
    page.setWindowTitle("إضافة قضية جديدة — رئيس القسم")
    page.resize(680, 720)
    page.show()


def _strip_numbering(name):
    """يحذف أي ترقيم بادئ من اسم الطرف، مثل '1- ' أو '2)' أو 'ثانياً: '"""
    return re.sub(
        r'^\s*(\d+[\-\.\)]\s*|أولاً?[:\-]\s*|ثانياً?[:\-]\s*|ثالثاً?[:\-]\s*)',
        '', (name or '').strip()
    ).strip()


def _enumerate_parties(names):
    """يرقّم قائمة أطراف بصيغة موحّدة دائمًا: '1- الاسم - 2- الاسم - ...'"""
    clean = [_strip_numbering(n) for n in names if n and _strip_numbering(n)]
    if not clean:
        return ''
    if len(clean) == 1:
        return clean[0]
    return ' - '.join(f"{i+1}- {name}" for i, name in enumerate(clean))


def _get_autocase_no(caso_no, cookies):
    """يجيب الرقم الآلي (autocase_no) مباشرة من basic_info_result.php"""
    try:
        r = requests.post(
            f"{BASE_URL}/includes/basic_info_result.php",
            data={'id': '1', 'title': caso_no, 'met_date': '', 'met_time': '', 'description': caso_no},
            cookies=cookies, verify=False, timeout=10
        )
        numbers = re.findall(r'\b\d{6,9}\b', r.text)
        return numbers[0] if numbers else ''
    except Exception:
        return ''


def _merge_pdfs(paths, out_path):
    """
    يدمج ملفات PDF بالترتيب المعطى في **ملف واحد** (الصفحات كما هي):
   heds صحيفة الدعوى أول ثم حكم الإحالة تحتها — للمعاينة والطباعة معاً.

    fitz (MuPDF) أول لأنه أقوى مع الملفات الممسوحة، وpypdf احتياط.
    """
    paths = [p for p in (paths or []) if p and os.path.exists(p)]
    if not paths:
        raise FileNotFoundError('ما فيه ملفات للدمج')
    try:
        import fitz
        out = fitz.open()
        try:
            for p in paths:
                with fitz.open(p) as src:
                    out.insert_pdf(src)
            out.save(out_path)
        finally:
            out.close()
        return out_path
    except Exception:
        pass
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for p in paths:
        for page in PdfReader(p).pages:
            writer.add_page(page)
    with open(out_path, 'wb') as f:
        writer.write(f)
    return out_path


# تنسيق بطاقة الملصق (العنوان + الصفوف) — مشترك بين الملصق الفردي والصفحة
# المدمجة عشان شكل كل ملصق يبقى متطابق بالحالتين.
_LABEL_CARD_CSS = """  .title {
    text-align: center; font-size: 15px; font-weight: 700;
    margin-bottom: 8mm; color: #1e2535;
  }
  .card {
    width: 100%; border: 1.5px solid #1e2535; border-radius: 6px; overflow: hidden;
  }
  .row {
    padding: 4mm 4mm; border-bottom: 1px solid #e8ecf0;
  }
  .row:last-child { border-bottom: none; }
  .row.emph { background: #f5f6fa; }
  .row .lbl {
    display: block; font-size: 10.5px; font-weight: 700; color: #5a6a80;
    margin-bottom: 1.5mm;
  }
  .row .val {
    display: block; font-size: 13.5px; font-weight: 700; color: #1e2535;
    /* الاتجاه الطبيعي الموروث من dir="rtl" بالـhtml هو الصحيح هنا —
       أول جزء بترتيب الكتابة (DOM) يطلع أقصى اليمين، بالضبط زي أي
       جملة عربية فيها كلمة إنجليزية مضمّنة. الأرقام/التواريخ المعزولة
       بـ<bdi> (انظر _bdi) تحافظ على ترتيبها الداخلي الصحيح بدون ما
       تنعكس. (ملاحظة: unicode-bidi:plaintext كانت تسبب المشكلة العكسية
       تمامًا — لما كل المحتوى داخل <bdi> ما تلقى القيمة أي حرف عربي
       "ظاهر" لها فتفترض LTR كاتجاه افتراضي، فينعكس كل شي). */
    text-align: right;
  }
  .row.emph .val { font-size: 15px; }
"""


def _label_rows_html(fields):
    """يبني صفوف بطاقة الملصق (HTML) — مشتركة بين الملصق الفردي والصفحة المدمجة
    عشان يبقى محتوى/تنسيق كل ملصق متطابق تمامًا بالحالتين."""
    def esc(t):
        return html_lib.escape(str(t or '') or '—')

    # حقول أطراف الدعوى (اسم المدعي/المدعى عليها) مُنسَّقة بصيغة
    # "1- فلان - 2- علان - ..." (نفس صيغة _enumerate_parties) لو أكثر
    # من شخص — بالملصق نبيها كل واحد بسطر لسهولة القراءة بدل سطر واحد
    # طويل، فنفكّها على '<br>' بدل الفاصل ' - ' اللي يسبق كل رقم.
    NAME_LABELS = {"اسم المدعي", "اسم المدعى عليها"}

    def esc_value(label, t):
        t = str(t or '').strip()
        if not t:
            return '—'
        # قيم مبنية مسبقًا بـ<bdi> (من _bdi، لتصحيح اتجاه الأرقام/
        # التواريخ) تُمرَّر كما هي بدون إعادة تهريب — لو هُرِّبت ثانية
        # كانت رح تنكتب علامات <bdi> بالصفحة كنص حرفي بدل ما تشتغل.
        if t.startswith('<bdi'):
            return t
        if label in NAME_LABELS:
            parts = re.split(r'\s*-\s*(?=\d+-)', t)
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) > 1:
                return '<br>'.join(html_lib.escape(p) for p in parts)
        return html_lib.escape(t)

    # الحقول المهمة (رقم الخبرة/رقم الدعوى/اسم الخبير) تُبرَز بخط أكبر
    # وأثقل من الباقي — تمييز بصري بسيط بدل أن يكون كل السطر بنفس الوزن.
    EMPHASIZE = {"رقم الخبرة", "اسم الخبير", "نوع القضية"}

    rows_html = ''.join(
        f'<div class="row{" emph" if label in EMPHASIZE else ""}">'
        f'<span class="lbl">{esc(label)}</span>'
        f'<span class="val">{esc_value(label, value)}</span>'
        f'</div>'
        for label, value in fields
    )
    return rows_html


def _build_label_html(fields):
    """
    يبني ويحفظ ملف HTML لملصق نصف ورقة A4 طولي (نصف علوي فقط — الحجم
    الفعلي للطباعة نصف صفحة A4 طولية: 210×148.5مم) عشان يُطبع على ورق
    لاصق ويُلصق فوق ملف القضية. الطباعة تلقائية عند فتح الملف
    (window.print())، بنفس نمط بقية مستندات النظام.
    fields: قائمة أزواج (label, value) بنفس الترتيب المطلوب بالطباعة.
    """
    rows_html = _label_rows_html(fields)

    html_doc = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>ملصق القضية</title>
<style>
  @page {{ size: A4 portrait; margin: 0; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
    direction: rtl; color: #1e2535; margin: 0; padding: 0;
  }}
  /* الورقة كاملة A4 طولية، لكن المحتوى محصور بالنصف الأيمن من العرض
     فقط (105مم من أصل 210مم) — الطول مفتوح بدون تحديد، العرض هو
     المُقيَّد. خط متقطع يفصل النصفين عمودياً. */
  /* من دون ارتفاع مفروض على الورقة — يخليها تاخذ فقط ارتفاع المحتوى
     الفعلي بدل ما تُجبَر على ملء 297مم كاملة (وهذا كان يسبب طباعة
     صفحة ثانية فاضية بسبب فرق تقريب بسيط بين المتصفح والطابعة). */
  .sheet {{ width: 210mm; position: relative; }}
  .label {{
    width: 105mm;
    margin-right: 0; margin-left: auto;
    border-left: 1px dashed #94a3b8;
    padding: 10mm 8mm 6mm;
    display: flex; flex-direction: column; align-items: center;
  }}
{_LABEL_CARD_CSS}</style>
</head>
<body onload="window.print()">
  <div class="sheet">
    <div class="label">
      <div class="title">بيانات القضية<br>الإدارة العامة للخبراء</div>
      <div class="card">{rows_html}</div>
    </div>
  </div>
</body>
</html>"""

    # اسم الملف: رقم الخبرة (أول حقل) بعد تنظيفه من أي HTML (زي <bdi>
    # اللي نبنيها لعزل الاتجاه) ومن أي حرف ممنوع بأسماء ملفات ويندوز.
    raw_ref = re.sub(r'<[^>]+>', '', str(fields[0][1] or '')).strip()
    safe_ref = re.sub(r'[\\/:*?"<>|]', '', raw_ref) or 'قضية'

    out_dir = os.path.join(os.path.expanduser("~"), "Desktop", "ملصقات القضايا")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"ملصق_{today_ddmmyyyy().replace('/', '-')}_{safe_ref}.html".replace(' ', '_')
    path = os.path.join(out_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    return path


def _label_fields_from_values(values, caso_no):
    """يبني قائمة حقول الملصق (label, value) من قيم نموذج المراجعة (أو من
    نتيجة _lookup_case لقضية إضافية بنافذة الدمج — نفس المفاتيح)."""
    names = [values.get(f'expr_name{i}', '') for i in range(1, 6)]
    ex_name = build_experts_dash_string(names)

    case_type_raw = values.get('type', '') or ''
    case_type = 'استعانة' if 'استعانة' in case_type_raw else 'أصالة'

    # نص عادي بدون أي عزل اتجاه يدوي (bdi) — نسيب المتصفح يطبّق
    # خوارزمية الاتجاه ثنائي الاتجاه القياسية تلقائيًا (نفس اللي
    # يسويه الوورد بالضبط لأي فقرة عربية فيها أرقام/كلمات إنجليزية
    # مضمّنة) عن طريق الاتجاه الموروث من dir="rtl" بالصفحة. التجارب
    # اليدوية بـ<bdi> جربناها وطلعت أسوأ (تعكس ترتيب الأجزاء)، فرجعنا
    # لأبسط حل وأصحه.
    c_no = values.get('c_no', '')
    c_year = values.get('c_year', '')
    c_lett = values.get('c_lett', '')
    c_last_no = values.get('c_last_no', '')
    if c_no or c_year or c_lett or c_last_no:
        court_no_disp = f"{c_no}/ {c_year} {c_lett}/ {c_last_no}".strip()
    else:
        court_no_disp = values.get('raw_court_no', '')

    session_date = values.get('expert_session_date', '')
    session_day = _day_name_ddmmyyyy(session_date)
    session_disp = f"{session_day} {session_date}".strip() if session_day else session_date

    return [
        ("رقم الخبرة", caso_no),
        ("رقم الدعوى في المحكمة", court_no_disp),
        ("تاريخ الحكم", values.get('courtdate', '')),
        ("الجلسة المحددة للخبير", session_disp),
        ("اسم المدعي", values.get('name_c', '')),
        ("اسم المدعى عليها", values.get('name_p', '')),
        ("اسم الخبير", ex_name),
        ("نوع القضية", case_type),
    ]


def _split_label_pages(n):
    """يوزّع n ملصق على صفحات A4 (كل صفحة تتسع لـ3 كحد أقصى) بأقل عدد صفحات
    وبتوزيع متقارب، الصفحات الأولى تاخذ الزيادة:
    1→[1]، 2→[2]، 3→[3]، 4→[2,2]، 5→[3,2]، 6→[3,3]، 7→[3,2,2]..."""
    pages = -(-n // 3)
    base, extra = divmod(n, pages)
    return [base + (1 if i < extra else 0) for i in range(pages)]


def _build_merged_labels_html(fields_list):
    """
    يبني ويحفظ ملف HTML فيه كل الملصقات المختارة على صفحات A4 طولية (كل
    ملصق بنفس محتوى/تنسيق الملصق الفردي بالضبط — نفس _label_rows_html
    و_LABEL_CARD_CSS). تخطيط كل صفحة حسب عدد ملصقاتها:
      • 1 → يمين (نفس مكان الملصق الفردي).
      • 2 → يمين ويسار (105مم × طول الصفحة لكل واحد).
      • 3 → يمين ويسار بالنصف العلوي، والثالث بالعرض (مُدار 90°) تحت.
    التوزيع على الصفحات من _split_label_pages. خطوط قص متقطعة بين
    الملصقات، وأي ملصق أطول من خانته يُصغَّر تلقائيًا (JS قبل window.print).
    """
    cut = '1px dashed #94a3b8'
    layouts = {
        1: [(f'top:0; right:0; width:105mm; height:296mm; border-left:{cut};', False)],
        2: [
            (f'top:0; right:0; width:105mm; height:296mm; border-left:{cut};', False),
            ('top:0; left:0; width:105mm; height:296mm;', False),
        ],
        3: [
            (f'top:0; right:0; width:105mm; height:148.5mm; border-left:{cut}; border-bottom:{cut};', False),
            (f'top:0; left:0; width:105mm; height:148.5mm; border-bottom:{cut};', False),
            ('top:148.5mm; left:0; width:210mm; height:147.5mm;', True),
        ],
    }

    def cell_html(style, rot, fields):
        return (
            f'<div class="cell" style="{style}">'
            f'<div class="label{" rot" if rot else ""}">'
            f'<div class="title">بيانات القضية<br>الإدارة العامة للخبراء</div>'
            f'<div class="card">{_label_rows_html(fields)}</div>'
            f'</div></div>'
        )

    sheets = []
    pos = 0
    for count in _split_label_pages(len(fields_list)):
        page_fields = fields_list[pos:pos + count]
        pos += count
        cells = ''.join(cell_html(style, rot, f)
                        for (style, rot), f in zip(layouts[count], page_fields))
        sheets.append(f'<div class="sheet">{cells}</div>')

    html_doc = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>ملصقات القضايا</title>
<style>
  @page {{ size: A4 portrait; margin: 0; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
    direction: rtl; color: #1e2535; margin: 0; padding: 0;
  }}
  /* 296مم بدل 297 عشان فرق التقريب بين المتصفح والطابعة ما يطلّع صفحة فاضية */
  .sheet {{ width: 210mm; height: 296mm; position: relative; overflow: hidden;
            page-break-after: always; break-after: page; }}
  .sheet:last-child {{ page-break-after: auto; break-after: auto; }}
  .cell {{ position: absolute; overflow: hidden; }}
  .label {{
    position: absolute; left: 50%; top: 0;
    width: 105mm;
    padding: 10mm 8mm 6mm;
    display: flex; flex-direction: column; align-items: center;
    transform-origin: top center;
    transform: translateX(-50%);
  }}
  .label.rot {{ top: 50%; transform-origin: center; transform: translate(-50%, -50%) rotate(-90deg); }}
{_LABEL_CARD_CSS}</style>
<script>
  function fitLabels() {{
    document.querySelectorAll('.cell').forEach(function (cell) {{
      var lab = cell.querySelector('.label');
      var rot = lab.classList.contains('rot');
      var cw = cell.clientWidth, ch = cell.clientHeight;
      var lw = lab.offsetWidth, lh = lab.offsetHeight;
      var s = rot ? Math.min(1, ch / lw, cw / lh) : Math.min(1, cw / lw, ch / lh);
      lab.style.transform = rot
        ? 'translate(-50%, -50%) rotate(-90deg) scale(' + s + ')'
        : 'translateX(-50%) scale(' + s + ')';
    }});
  }}
  window.onload = function () {{ fitLabels(); window.print(); }};
</script>
</head>
<body>
  {''.join(sheets)}
</body>
</html>"""

    refs = []
    for fields in fields_list:
        raw_ref = re.sub(r'<[^>]+>', '', str(fields[0][1] or '')).strip()
        refs.append(re.sub(r'[\\/:*?"<>|]', '', raw_ref) or 'قضية')

    out_dir = os.path.join(os.path.expanduser("~"), "Desktop", "ملصقات القضايا")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"ملصقات_{today_ddmmyyyy().replace('/', '-')}_{'_'.join(refs[:6])}.html".replace(' ', '_')
    path = os.path.join(out_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    return path


class LabelsPage(QWidget):
    """صفحة 'طباعة ملصق' (قائمة رئيس القسم): تضيف أي عدد من القضايا برقم
    الخبرة وتطبعها كلها بملف وحد (التخطيط من _build_merged_labels_html).
    جلب بيانات كل قضية بنفس منطق زر الاستخراج بصفحة إضافة قضية
    (Main1Page._lookup_case) — لذلك تاخذ مرجع للصفحة هذي."""

    def __init__(self, main1_page):
        super().__init__()
        self.main1_page = main1_page
        self.cases = []  # [(caso_no, fields)]

        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet(f"background:{th.BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(f"background:{th.NAVY};")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(18, 0, 18, 0)
        h_title = QLabel("🏷 طباعة ملصق")
        h_title.setStyleSheet("color:white; font-size:14px; font-weight:700; border:none;")
        h_lay.addWidget(h_title)
        h_lay.addStretch()
        root.addWidget(header)

        body = QWidget()
        b_lay = QVBoxLayout(body)
        b_lay.setContentsMargins(18, 16, 18, 18)
        b_lay.setSpacing(10)

        card = Card()
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(18, 16, 18, 16)
        lbl = QLabel("رقم الخبرة (مثال: A2261234)")
        lbl.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:13px; font-weight:700; border:none;")
        lbl.setAlignment(th.ARIGHT)
        c_lay.addWidget(lbl)

        row = QHBoxLayout()
        self.ref_input = QLineEdit()
        self.ref_input.setStyleSheet(_field_qss())
        self.ref_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ref_input.setValidator(
            QRegularExpressionValidator(QRegularExpression(r'^[A-Za-z0-9]*$'))
        )
        self.ref_input.textChanged.connect(
            lambda t: t != t.upper() and self.ref_input.setText(t.upper()))
        self.ref_input.returnPressed.connect(self._add_case)
        self.add_btn = PrimaryButton("➕ إضافة قضية")
        self.add_btn.clicked.connect(self._add_case)
        row.addWidget(self.add_btn)
        row.addWidget(self.ref_input, 1)
        c_lay.addLayout(row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        self.status.setAlignment(th.ARIGHT)
        c_lay.addWidget(self.status)
        b_lay.addWidget(card)

        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget {{ background:white; border:1px solid {th.BORDER}; border-radius:10px;"
            f" font-size:13px; color:{th.TEXT_PRIMARY}; padding:6px; }}")
        b_lay.addWidget(self.list, 1)

        self.layout_lbl = QLabel("")
        self.layout_lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none;")
        self.layout_lbl.setAlignment(th.ARIGHT)
        b_lay.addWidget(self.layout_lbl)

        btns = QHBoxLayout()
        print_btn = PrimaryButton("🖨️ طباعة")
        print_btn.clicked.connect(self._print)
        rm_btn = SecondaryButton("🗑 حذف المحددة")
        rm_btn.clicked.connect(self._remove_selected)
        clear_btn = SecondaryButton("✖ مسح الكل")
        clear_btn.clicked.connect(self._clear)
        btns.addWidget(print_btn)
        btns.addWidget(rm_btn)
        btns.addWidget(clear_btn)
        btns.addStretch()
        b_lay.addLayout(btns)

        root.addWidget(body, 1)
        self._refresh()

    def _refresh(self):
        self.list.clear()
        for i, (caso_no, _) in enumerate(self.cases, start=1):
            self.list.addItem(f"{i}) {caso_no}")
        n = len(self.cases)
        if n:
            pages = _split_label_pages(n)
            self.layout_lbl.setText(
                f"العدد: {n} — الصفحات: {len(pages)} ("
                + " + ".join(str(p) for p in pages) + ")")
        else:
            self.layout_lbl.setText("أضف قضية أو أكثر ثم اضغط طباعة")

    def _add_case(self):
        raw = self.ref_input.text().strip()
        if not raw:
            return
        try:
            parsed = parse_expertise_number(raw)
        except ValueError as e:
            QMessageBox.critical(self, "خطأ بصيغة الرقم", str(e))
            return
        caso_no = raw.upper()
        if caso_no in {c for c, _ in self.cases}:
            QMessageBox.warning(self, "تنبيه", "هذي القضية مضافة مسبقًا")
            return

        self.status.setText("⏳ جاري البحث عن القضية بالنظام...")
        self.add_btn.setEnabled(False)
        QApplication.processEvents()
        try:
            result, _, _ = self.main1_page._lookup_case(caso_no, parsed)
        except Exception as e:
            self.status.setText("")
            QMessageBox.critical(self, "خطأ", f"تعذّر جلب القضية:\n{th.ltr(e)}")
            return
        finally:
            self.add_btn.setEnabled(True)
        self.cases.append((caso_no, _label_fields_from_values(result, caso_no)))
        self.status.setText(f"✅ أُضيفت {caso_no}")
        self.ref_input.clear()
        self._refresh()

    def _remove_selected(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.cases):
            del self.cases[row]
            self._refresh()

    def _clear(self):
        self.cases = []
        self.status.setText("")
        self._refresh()

    def _print(self):
        if not self.cases:
            QMessageBox.warning(self, "تنبيه", "أضف قضية واحدة على الأقل")
            return
        try:
            path = _build_merged_labels_html([f for _, f in self.cases])
            os.startfile(path)
        except Exception as e:
            QMessageBox.critical(self, "خطأ", f"تعذّرت طباعة الملصقات:\n{th.ltr(e)}")


def _field_qss():
    return f"""
        QLineEdit, QComboBox {{
            background: white; border: 1px solid {th.BORDER}; border-radius: 10px;
            padding: 8px 10px; font-size: 12.5px; color: {th.TEXT_PRIMARY};
        }}
        QLineEdit:focus, QComboBox:focus {{ border: 1px solid {th.NAVY}; }}
    """


class _SmallSettingsDialog(QDialog):
    """نافذة صغيرة عامة: تسمية + حقل + زر حفظ — تُستخدم لمسار القاعدة ومفتاح Gemini"""
    def __init__(self, parent, title, label_text, initial_value, on_save, secret=False):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(title)
        self.setFixedWidth(460)
        self.setStyleSheet(f"background:{th.BG};")
        self.on_save = on_save

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        lbl = QLabel(label_text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:12.5px; font-weight:700; border:none;")
        lbl.setAlignment(th.ARIGHT)
        root.addWidget(lbl)

        self.entry = QLineEdit()
        self.entry.setStyleSheet(_field_qss())
        self.entry.setAlignment(th.ALEFT)
        if secret:
            self.entry.setEchoMode(QLineEdit.EchoMode.Password)
        if initial_value:
            self.entry.setText(initial_value)
        root.addWidget(self.entry)

        btns = QHBoxLayout()
        cancel = SecondaryButton("إلغاء")
        cancel.clicked.connect(self.reject)
        save = PrimaryButton("💾 حفظ")
        save.clicked.connect(self._save)
        btns.addWidget(save)
        btns.addStretch()
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _save(self):
        val = self.entry.text().strip()
        if not val:
            QMessageBox.warning(self, "تنبيه", "أدخل قيمة أولاً")
            return
        try:
            self.on_save(val)
        except Exception as e:
            QMessageBox.critical(
                self, "فشل الحفظ",
                f"تعذر حفظ القيمة (تأكد من الاتصال بالإنترنت):\n\n{e}"
            )
            return
        self.accept()


class DepartmentReportDialog(QDialog):
    """كشف جلسات القسم — كل خبير أو خبير معيّن، ضمن فترة محدَّدة، من
    قاعدة القسم المحلية (ExpretDB.MDB) مباشرة. بديل عملي لعدم توفر
    الميزة بنظام الخبراء الأونلاين نفسه (اللي يعرض جلسات الخبير الحالي
    بس، ونظام أوراكل أبكس الإداري منفصل تمامًا وغير متاح للتكامل)."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("كشف جلسات القسم")
        self.setFixedWidth(420)
        self.setStyleSheet(f"background:{th.BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        title = QLabel("📅 كشف جلسات القسم")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:15px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        root.addWidget(title)

        note = QLabel(
            "يجيب الجلسات من جدول [الاحداث] بقاعدة القسم — نفس الجلسات "
            "المُضافة وقت إضافة القضية أو من صفحة الجلسات لأي خبير. "
            "اختر خبير معيّن أو كل الخبراء، وفترة، ويولّد كشف واحد "
            "قابل للطباعة."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        note.setAlignment(th.ARIGHT)
        root.addWidget(note)

        form = QFormLayout()
        form.setLabelAlignment(th.ARIGHT)
        form.setSpacing(10)

        self.expert_combo = QComboBox()
        self.expert_combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.expert_combo.addItem("كل الخبراء")
        try:
            self.expert_combo.addItems(get_expert_names())
        except Exception:
            pass
        form.addRow("الخبير", self.expert_combo)

        today = datetime.now()
        next_sunday = today + timedelta(days=(6 - today.weekday()) % 7 or 7)
        next_thursday = next_sunday + timedelta(days=4)
        self.date_from = SmartDateEdit(initial=next_sunday.strftime("%d/%m/%Y"))
        self.date_to = SmartDateEdit(initial=next_thursday.strftime("%d/%m/%Y"))
        form.addRow("من تاريخ", self.date_from)
        form.addRow("إلى تاريخ", self.date_to)
        root.addLayout(form)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        self.status_lbl.setAlignment(th.ARIGHT)
        self.status_lbl.setWordWrap(True)
        root.addWidget(self.status_lbl)

        btns = QHBoxLayout()
        cancel = SecondaryButton("إلغاء")
        cancel.clicked.connect(self.reject)
        gen_btn = PrimaryButton("🖨️ توليد وطباعة")
        gen_btn.clicked.connect(self._generate)
        btns.addWidget(gen_btn)
        btns.addStretch()
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _generate(self):
        try:
            date_from = datetime.strptime(self.date_from.get_value(), "%Y/%m/%d")
            date_to = datetime.strptime(self.date_to.get_value(), "%Y/%m/%d")
        except Exception:
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال تاريخين صحيحين")
            return
        if date_from > date_to:
            QMessageBox.warning(self, "تنبيه", "تاريخ البداية بعد تاريخ النهاية")
            return

        expert = self.expert_combo.currentText()
        expert_filter = None if expert == "كل الخبراء" else expert

        self.status_lbl.setText("⏳ جاري التوليد...")
        QApplication.processEvents()
        try:
            path = build_department_week_report_html(date_from, date_to, expert_filter)
        except Exception as e:
            self.status_lbl.setText("")
            QMessageBox.critical(self, "خطأ", f"تعذر توليد الكشف:\n{th.ltr(e)}")
            return

        self.status_lbl.setText("")
        os.startfile(path)
        self.accept()


class Main1Page(QWidget):
    """صفحة 'إضافة قضية جديدة' — مدمجة بنفس نافذة البرنامج الرئيسية
    (زي باقي الصفحات: الجلسات، المتداولة، إلخ) بدل نافذة منبثقة
    منفصلة. كانت QDialog تُفتح بـ.exec() فوق النافذة الرئيسية؛ الآن
    QWidget عادي يُضاف لنفس الـQStackedWidget بقسم rئيس القسم."""
    def __init__(self, parent, cookies, current_user):
        super().__init__(parent)
        self.cookies = cookies
        self.current_user = current_user
        self.extracted = {}
        self.entries = {}

        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet(f"background:{th.BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------- الهيدر ----------
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(f"background:{th.NAVY};")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(18, 0, 18, 0)
        h_title = QLabel("📋 إضافة قضية جديدة — رئيس القسم")
        h_title.setStyleSheet("color:white; font-size:14px; font-weight:700; border:none;")
        db_btn = SecondaryButton("⚙️ مسار القاعدة")
        db_btn.setStyleSheet(db_btn.styleSheet() + f"QPushButton{{background:transparent; color:white; border-color:{th.ON_NAVY_BORDER};}}")
        db_btn.clicked.connect(self._show_db_settings)
        db_btn.setAutoDefault(False)
        db_btn.setDefault(False)
        gemini_btn = SecondaryButton("🔑 مفتاح Gemini")
        gemini_btn.setStyleSheet(gemini_btn.styleSheet() + f"QPushButton{{background:transparent; color:white; border-color:{th.ON_NAVY_BORDER};}}")
        gemini_btn.clicked.connect(self._show_gemini_settings)
        gemini_btn.setAutoDefault(False)
        gemini_btn.setDefault(False)
        report_btn = SecondaryButton("📅 كشف جلسات القسم")
        report_btn.setStyleSheet(report_btn.styleSheet() + f"QPushButton{{background:transparent; color:white; border-color:{th.ON_NAVY_BORDER};}}")
        report_btn.clicked.connect(self._show_department_report)
        report_btn.setAutoDefault(False)
        report_btn.setDefault(False)
        h_lay.addWidget(h_title)
        h_lay.addStretch()
        h_lay.addWidget(report_btn)
        h_lay.addWidget(gemini_btn)
        h_lay.addWidget(db_btn)
        root.addWidget(header)

        # ---------- منطقة الإدخال (رقم الخبرة) ----------
        entry_card = Card()
        ec_lay = QVBoxLayout(entry_card)
        ec_lay.setContentsMargins(18, 16, 18, 16)
        ref_lbl = QLabel("رقم الخبرة (مثال: A2261234)")
        ref_lbl.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:13px; font-weight:700; border:none;")
        ref_lbl.setAlignment(th.ARIGHT)
        ec_lay.addWidget(ref_lbl)
        ec_lay.addSpacing(6)

        ref_row = QHBoxLayout()
        self.ref_entry = QLineEdit()
        self.ref_entry.setStyleSheet(_field_qss())
        self.ref_entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # يقبل بس حروف/أرقام إنجليزية (يرفض العربي كليًا مهما كانت لغة
        # الكيبورد وقت الكتابة)، ويحوّل تلقائيًا للحروف الكبيرة (Capital) —
        # عشان رقم الخبرة يوصل دايمًا بصيغة صحيحة (مثال: A2261234).
        self.ref_entry.setValidator(
            QRegularExpressionValidator(QRegularExpression(r'^[A-Za-z0-9]*$'))
        )
        self.ref_entry.textChanged.connect(self._force_upper_ref)
        self.ref_entry.returnPressed.connect(self._on_fetch_clicked)
        # لما تدخل على الحقل، نبدّل لغة كيبورد ويندوز نفسها للإنجليزي
        # تلقائياً — فلو كنت كاتب بالعربي، أول حرف تضغطه يطلع إنجليزي
        # مباشرة (مو مرفوض بصمت زي قبل)، بغض النظر عن اللغة اللي كانت
        # شغالة قبل ما تدخل الحقل.
        self.ref_entry.installEventFilter(self)
        self.fetch_btn = PrimaryButton("🔎 استخراج المعلومات")
        self.fetch_btn.clicked.connect(self._on_fetch_clicked)
        self.fetch_btn.setAutoDefault(True)
        self.fetch_btn.setDefault(True)
        ref_row.addWidget(self.fetch_btn)
        ref_row.addWidget(self.ref_entry, 1)
        ec_lay.addLayout(ref_row)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        self.status_lbl.setAlignment(th.ARIGHT)
        ec_lay.addSpacing(8)
        ec_lay.addWidget(self.status_lbl)

        # ---------- منطقة المراجعة (تُبنى ديناميكيًا بعد الاستخراج) ----------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.review_content = QWidget()
        self.review_lay = QVBoxLayout(self.review_content)
        self.review_lay.setContentsMargins(18, 10, 18, 18)
        self.review_lay.setSpacing(8)
        self.review_lay.addWidget(entry_card)
        self.review_lay.addStretch()
        scroll.setWidget(self.review_content)
        root.addWidget(scroll, 1)

    def eventFilter(self, obj, event):
        if obj is self.ref_entry and event.type() == QEvent.Type.FocusIn:
            self._force_english_keyboard()
        # ⚠️ القوائم ما تاخذ عجلة الفأرة: كانت تغيّر قيمتها تلقائياً
        # (الخبير مثلاً) والصفحة توقّفت عن التمرير. نخلّي العجلة تمرّر
        # الصفحة بدالها، وتغيير القيمة من القائمة نفسها.
        if event.type() == QEvent.Type.Wheel and isinstance(obj, QComboBox):
            event.ignore()
            return True
        return super().eventFilter(obj, event)

    def _force_english_keyboard(self):
        """
        يبدّل لغة كيبورد ويندوز الحالية للإنجليزية (US) تلقائياً —
        يُستدعى وقت الدخول على حقل رقم الخبرة. هذا حل مستوى نظام
        التشغيل (مو مجرد رفض الحروف العربية)، فيخلي أي حرف تكتبه
        يترجم إنجليزي مباشرة من لوحة المفاتيح نفسها، بدل ما يُرفض
        بصمت لو كانت لغتك شغالة عربي وقتها. يعمل بويندوز فقط — على
        أي نظام تشغيل ثاني (أو لو فشل الاستدعاء لأي سبب) نتجاهله
        بصمت والفلترة الموجودة أصلاً (رفض العربي + تحويل كابيتال)
        تبقى خط الدفاع الاحتياطي.
        """
        if sys.platform != 'win32':
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            KLF_ACTIVATE = 0x00000001
            ENGLISH_US_KLID = "00000409"
            hkl = user32.LoadKeyboardLayoutW(ENGLISH_US_KLID, KLF_ACTIVATE)
            if hkl:
                user32.ActivateKeyboardLayout(hkl, KLF_ACTIVATE)
        except Exception:
            pass

    def _force_upper_ref(self, text):
        """يحوّل رقم الخبرة تلقائيًا لحروف كبيرة أثناء الكتابة"""
        upper = text.upper()
        if upper != text:
            pos = self.ref_entry.cursorPosition()
            self.ref_entry.blockSignals(True)
            self.ref_entry.setText(upper)
            self.ref_entry.setCursorPosition(pos)
            self.ref_entry.blockSignals(False)

    # ---------- إعدادات فرعية ----------
    def _show_db_settings(self):
        dlg = _SmallSettingsDialog(
            self, "مسار قاعدة البيانات",
            "مسار ملف ExpretDB.MDB — هذا الحقل مشترك: أي تعديل هنا "
            "ينعكس فورًا على كل الأجهزة (مو بس جهازك).",
            load_db_path(), save_db_path
        )
        if dlg.exec():
            QMessageBox.information(
                self, "تم", "تم حفظ المسار الجديد وانتشر لكل الأجهزة.")

    def _show_gemini_settings(self):
        current = load_api_key()
        status = f"الحالي: {mask_key(current)}" if current else "لا يوجد مفتاح محفوظ حاليًا"
        dlg = _SmallSettingsDialog(
            self, "مفتاح Google Gemini API",
            f"مفتاح Google Gemini API\n{status}\nتحصل عليه من aistudio.google.com/app/apikey",
            "", save_api_key, secret=True
        )
        if dlg.exec():
            QMessageBox.information(self, "تم", "تم حفظ المفتاح بنجاح")

    def _show_department_report(self):
        dlg = DepartmentReportDialog(self)
        dlg.exec()

    # ---------- الاستخراج ----------
    def _extract_via_ai(self, caso_no, autocase_no, force_ai=False):
        """
        يجيب حكم الإحالة من نظام الخبراء ويستخرج بياناته بالذكاء
        الاصطناعي (اسم المدعي/المدعى عليه، تاريخ الحكم، رقم الدعوى،
        الجلسة المحددة للخبير). يرجع (updates: dict, judgment_found: bool).
        best-effort بالكامل — أي فشل (شبكة، توكن الذكاء الاصطناعي منتهي،
        ملف الحكم غير متوفر...) يرجع updates فاضي بصمت بدل ما يوقف الواجهة.
        force_ai: كل صفحات الحكم صورًا للذكاء مباشرة (خيار «قراءة كاملة بالذكاء»).
        """
        updates = {}
        judgment_found = False

        def say(text):   # الخطوة الفعلية (قراءة داخلية/OCR.space/أي مزود) بسطر الحالة
            self.status_lbl.setText(f"⏳ {text}")
            QApplication.processEvents()
        try:
            save_dir = os.path.join(os.path.expanduser("~"), "Desktop", "judgments")
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, f"{caso_no}_MAIN1.pdf")
            judgment, path = get_referral_judgment_for_case(
                self.cookies, autocase_no, "309", save_path
            )
            if judgment and path:
                judgment_found = True
                updates['judgment_path'] = path      # زر المعاينة 👁 يفتحه مع صحيفة الدعوى
                # allow_local: بلا اتصال/مزود تُستخرج على الجهاز — الخبير يراجعها بالنموذج قبل الحفظ
                data, error = extract_from_pdf(path, allow_local=True, force_ai=force_ai, status=say)
                if not error and data:
                    updates = self._updates_from_pdf_data(data)
                    self._local_warning = data.get('_warning') if data.get('_local') else None
        except Exception:
            pass
        return updates, judgment_found

    def _updates_from_pdf_data(self, data):
        """نفس منطق تعبئة الحقول المستخدم بـ_extract_via_ai، لكن من نتيجة
        extract_from_pdf جاهزة (مصدرها ملف مرفوع يدويًا أو جلب تلقائي) —
        دالة مشتركة لتفادي تكرار نفس التعيينات مرتين."""
        updates = {}
        plaintiffs = data.get('المدعون') or []
        defendants = data.get('المدعى_عليهم') or []
        updates['name_c'] = _enumerate_parties(plaintiffs)
        updates['name_p'] = _enumerate_parties(defendants)
        updates['courtdate'] = data.get('تاريخ_الحكم', '')
        raw_court_no = data.get('رقم_القضية', '')
        updates['raw_court_no'] = raw_court_no
        updates.update(parse_court_case_number(raw_court_no))
        raw_hearing = data.get('تاريخ_حضور_الخصوم', '')
        if raw_hearing:
            corrected, _ = autocorrect_hearing_date(
                updates.get('courtdate', ''), raw_hearing
            )
            updates['expert_session_date'] = corrected or raw_hearing
        return updates

    def _on_upload_manual_clicked(self):
        """رفع حكم إحالة يدويًا (PDF) واستخراج بياناته بالذكاء الاصطناعي —
        بديل لما الجلب التلقائي من النظام يفشل أو ما يلقى الملف (حتى لو
        القضية موجودة فعليًا بالنظام لأي سبب: تأخر أرشفة، اختلاف مسار
        البحث، إلخ). لا يحتاج رقم آلي (autocase_no) ولا اتصال بالنظام
        إطلاقًا — بس الملف نفسه."""
        if not self.extracted:
            QMessageBox.warning(self, "تنبيه", "أدخل رقم الخبرة واضغط 'استخراج المعلومات' أولاً")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "اختر ملف حكم الإحالة (PDF)", "", "PDF files (*.pdf)")
        if not path:
            return

        self.status_lbl.setText("⏳ جاري قراءة الملف المرفوع بالذكاء الاصطناعي...")
        QApplication.processEvents()

        # نحدّث الحقول من واجهة المراجعة أولاً (حفظ أي تعديل يدوي سابق)
        for k in self.entries:
            self.extracted[k] = self._entry_value(k)

        data, error = extract_from_pdf(path, allow_local=True)
        if error:
            self.status_lbl.setText(f"❌ فشل الاستخراج بالذكاء الاصطناعي: {th.ltr(error)}")
            self._render_review_form()
            return

        self.extracted.update(self._updates_from_pdf_data(data))
        self.status_lbl.setText(data['_warning'] if data.get('_local') else
                                "✅ تم الاستخراج من الملف المرفوع بنجاح — راجع البيانات بالأسفل")
        self._render_review_form()

    def _on_force_ai_clicked(self):
        """
        زر إعادة استخراج إجباري — يتجاوز أي كاش محلي ويعيد جلب الحكم
        واستخراجه بالذكاء الاصطناعي من جديد. يُستخدم لما البيانات تطلع
        ناقصة (مثلاً لأن توكن الذكاء الاصطناعي كان منتهي وقت أول محاولة
        فانحفظت بالكاش بيانات ناقصة).
        """
        if not self.extracted:
            QMessageBox.warning(self, "تنبيه", "اجلب رقم الخبرة أولاً")
            return
        caso_no = self.extracted.get('caso_no', '')
        autocase_no = self.extracted.get('autocase_no', '')
        if not autocase_no:
            QMessageBox.warning(self, "تنبيه", "ما فيه رقم آلي لهذي القضية — تعذر جلب الحكم")
            return

        # الخيار: المسار الطبيعي (قراءة داخلية/OCR.space ثم نص للذكاء، أول صفحة وآخر صفحتين)
        # أو كل صفحات الحكم صورًا للذكاء مباشرة — للحالات اللي فيها خطأ بالنتيجة
        box = QMessageBox(self)
        box.setWindowTitle("إعادة الاستخراج")
        box.setText("كيف تريد إعادة استخراج بيانات الحكم؟")
        box.setInformativeText(
            "• الوضع الطبيعي: القراءة الداخلية أو OCR.space، ثم النص للذكاء (أسرع).\n"
            "• قراءة كاملة بالذكاء: كل صفحات الحكم صورًا للذكاء مباشرة (أبطأ وأدق).")
        normal_btn = box.addButton("🔄 الوضع الطبيعي", QMessageBox.ButtonRole.AcceptRole)
        full_btn = box.addButton("🤖 قراءة كاملة بالذكاء", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("إلغاء", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(normal_btn)
        box.exec()
        if box.clickedButton() not in (normal_btn, full_btn):
            return
        force_ai = box.clickedButton() is full_btn

        self.status_lbl.setText("⏳ قراءة كاملة بالذكاء: كل صفحات الحكم صورًا..." if force_ai
                                else "⏳ جاري إعادة الاستخراج (الوضع الطبيعي)...")
        QApplication.processEvents()

        # نحدّث الحقول من واجهة المراجعة أولاً (حفظ أي تعديل يدوي سابق)
        for k in self.entries:
            self.extracted[k] = self._entry_value(k)

        self._local_warning = None
        updates, judgment_found = self._extract_via_ai(caso_no, autocase_no, force_ai=force_ai)
        if updates:
            self.extracted.update(updates)
            self.status_lbl.setText(self._local_warning or (
                "✅ تمت القراءة الكاملة بالذكاء — راجع البيانات بالأسفل" if force_ai else
                "✅ تم إعادة الاستخراج — راجع البيانات بالأسفل"))
        elif judgment_found:
            self.status_lbl.setText("⚠️ لُقي ملف الحكم لكن تعذر استخراج بياناته (تحقق من مفتاح/توكن الذكاء الاصطناعي)")
        else:
            self.status_lbl.setText("⚠️ تعذر جلب ملف الحكم من النظام")

        self._render_review_form()

    def _on_fetch_clicked(self):
        raw = self.ref_entry.text().strip()
        if not raw:
            QMessageBox.warning(self, "تنبيه", "أدخل رقم الخبرة أولًا")
            return

        try:
            parsed = parse_expertise_number(raw)
        except ValueError as e:
            QMessageBox.critical(self, "خطأ بصيغة الرقم", str(e))
            return

        self.status_lbl.setText("⏳ جاري البحث عن القضية بالنظام...")
        self.fetch_btn.setEnabled(False)
        QApplication.processEvents()

        caso_no = raw.upper()
        result, used_local, judgment_found = self._lookup_case(caso_no, parsed)

        if used_local:
            self.status_lbl.setText("💾 تم الجلب من القاعدة المحلية — راجع البيانات بالأسفل")
        elif not judgment_found:
            self.status_lbl.setText(
                "⚠️ لا يوجد ملف إحالة آلي لهذا الرقم بعد — "
                "أكمل رقم المحكمة والمعلومات يدويًا بالأسفل"
            )
        else:
            self.status_lbl.setText(getattr(self, '_local_warning', None) or
                                    "✅ تم الاستخراج التلقائي (ذكاء اصطناعي) — راجع البيانات بالأسفل")

        result['reg_date_r'] = today_ddmmyyyy()
        self.extracted = result
        self.fetch_btn.setEnabled(True)
        self._render_review_form()

    def _lookup_case(self, caso_no, parsed):
        """منطق جلب بيانات قضية بـcaso_no (قاعدة محلية ← ذكاء اصطناعي ←
        parse_case_info ← نوع القضية والخبراء) — مفصول عن _on_fetch_clicked
        عشان يُعاد استخدامه بنافذة دمج الملصقات بدون أي تكرار.
        يرجع (result, used_local, judgment_found)."""
        # أول شي: نتأكد من القاعدة المحلية (case_db) قبل أي استدعاء
        # شبكي أو استخراج بالذكاء الاصطناعي — لو القضية موجودة فيها
        # ببيانات فعلية (مدعي/مدعى عليه أو حكم/رقم دعوى) نستخدمها
        # مباشرة ونوفر وقت الاستخراج، ولو ناقصة أو غير موجودة نكمل
        # بالطريقة المعتادة (الذكاء الاصطناعي ثم parse_case_info).
        cached = None
        try:
            cached = case_db.get_case(caso_no)
        except Exception:
            cached = None

        result = dict(parsed)
        autocase_no = (cached or {}).get('autocase_no') or ''
        if not autocase_no:
            autocase_no = _get_autocase_no(caso_no, self.cookies)
        result.update({'caso_no': caso_no, 'autocase_no': autocase_no})

        used_local = False
        if cached and (cached.get('plaintiffs') or cached.get('defendants')):
            result['name_c'] = _enumerate_parties(cached.get('plaintiffs') or [])
            result['name_p'] = _enumerate_parties(cached.get('defendants') or [])
            if cached.get('judgment_date'):
                result['courtdate'] = cached['judgment_date']
            if cached.get('court_case_number'):
                result['raw_court_no'] = cached['court_case_number']
                try:
                    result.update(parse_court_case_number(cached['court_case_number']))
                except Exception:
                    pass
            if cached.get('hearing_date'):
                result['expert_session_date'] = cached['hearing_date']
            used_local = True

        judgment_found = bool(used_local and (result.get('courtdate') or result.get('raw_court_no')))

        self._local_warning = None
        if not used_local and autocase_no:
            updates, found = self._extract_via_ai(caso_no, autocase_no)
            if found:
                judgment_found = True
            result.update(updates)

        if not result.get('name_c'):
            try:
                info = parse_case_info(caso_no, self.cookies, self.current_user)
                plaintiffs = info.get('plaintiffs', [])
                defendants = info.get('defendants', [])
                result['name_c'] = _enumerate_parties(plaintiffs)
                result['name_p'] = _enumerate_parties(defendants)
            except Exception:
                pass

        # كشف أصالة/استعانة تلقائياً من سجل الحركة، ثم دمجه مع موضوعي/
        # مستعجل (من رقم الدعوى الخام) لاختيار أحد الخيارات الأربعة.
        case_type = ''
        try:
            case_type = get_case_type(self.cookies, caso_no, self.current_user) or ''
        except Exception:
            case_type = ''
        result['is_secondment'] = (case_type == 'استعانة')
        result['type'] = _detect_type_option(result.get('raw_court_no', ''), case_type)

        # المدة المحددة من رئيس القسم: 60 يوم لو القضية مستعجلة، 120
        # لو موضوعي — تبقى قابلة للتعديل يدوياً بالنموذج لو احتجت تغيّرها.
        result['boss_est'] = '60' if 'مستعجل' in result['type'] else '120'

        # اسم الخبير (أو اللجنة) اللي انسندت له القضية أخيراً — عادة
        # بنفس يوم سحب القضية لو التوزيع صار توّه.
        try:
            exps = get_experts(caso_no, self.cookies, self.current_user)
        except Exception:
            exps = []
        for i, e in enumerate(exps[:5], start=1):
            result[f'expr_name{i}'] = e.get('name', '')

        # 3 خبراء مسجّلين على القضية ⇐ لجنة ثلاثية تلقائياً.
        if len(exps) >= 3:
            result['comm'] = 'لجنة ثلاثية'

        # التخصص: من آخر تخصص مسجّل للخبير المسند له بقاعدة القسم، وإلا من
        # تخصص الخبير الحالي المحفوظ بالإعدادات — بدل 'كهرباء 15' دائماً.
        self._apply_specialty_auto(result)

        return result, used_local, judgment_found

    def _apply_specialty_auto(self, result):
        """
        يختار 'رمز التخصص' تلقائياً حسب الخبير المسند له القضية:
          1) آخر تخصص مسجّل له بقاعدة القسم (جدول main، عمود spe).
          2) وإلا تخصص الخبير الحالي المحفوظ بالإعدادات ('حاسب آلي' ⇐ كمبيوتر).
        ما يغيّر شي لو ما لقى إجابة — يبقى الاختيار الافتراضي.
        """
        try:
            from db_writer import get_expert_specialty
            expert_name = ''
            for i in range(1, 6):
                name = (result.get(f'expr_name{i}') or '').strip()
                if name:
                    expert_name = name
                    break
            spe = get_expert_specialty(expert_name) if expert_name else ''
        except Exception:
            spe = ''
        if spe in SPECIALTY_OPTIONS:
            result['spe'] = spe
            return
        try:
            from expert_settings import load_specialty
            current = (load_specialty() or '')
        except Exception:
            current = ''
        if 'كمبيوتر' in current or 'حاسب' in current:
            result['spe'] = 'كمبيوتر 24'
        elif 'كهرباء' in current:
            result['spe'] = 'كهرباء 15'

    # ---------- نموذج المراجعة ----------
    def _clear_review_extras(self):
        # نبقي أول عنصر بس (بطاقة رقم الخبرة) ونشيل كل شي بعده
        while self.review_lay.count() > 2:  # آخر عنصر هو الـstretch
            item = self.review_lay.takeAt(1)
            w = item.widget()
            if w:
                w.deleteLater()

    def _label(self, text, parent_lay):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:11px; font-weight:700; border:none;")
        lbl.setAlignment(th.ARIGHT)
        parent_lay.addWidget(lbl)

    def _field(self, label_text, key, default=''):
        row = Card()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 8, 12, 8)
        lbl = QLabel(label_text)
        lbl.setFixedWidth(190)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:11px; border:none;")
        lbl.setAlignment(th.ARIGHT)
        entry = QLineEdit()
        entry.setStyleSheet(_field_qss())
        entry.setAlignment(th.ARIGHT)
        entry.setText(self.extracted.get(key, default) or '')
        # ترتيب عربي: التسمية أول يمين، والحقل بعدها يسار
        lay.addWidget(lbl)
        lay.addWidget(entry, 1)
        self.entries[key] = entry
        self.review_lay.insertWidget(self.review_lay.count() - 1, row)

    def _dropdown(self, label_text, key, options, default=''):
        row = Card()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 8, 12, 8)
        lbl = QLabel(label_text)
        lbl.setFixedWidth(190)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:11px; border:none;")
        lbl.setAlignment(th.ARIGHT)
        combo = QComboBox()
        combo.setEditable(False)
        combo.addItems(options)
        combo.setStyleSheet(_field_qss())
        combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        combo.installEventFilter(self)      # العجلة تمرّر الصفحة (ما تغيّر القيمة)
        current = self.extracted.get(key, default) or (options[0] if options else '')
        idx = combo.findText(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        lay.addWidget(lbl)
        lay.addWidget(combo, 1)
        self.entries[key] = combo
        self.review_lay.insertWidget(self.review_lay.count() - 1, row)

    def _combo_editable(self, label_text, key, options):
        row = Card()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 8, 12, 8)
        lbl = QLabel(label_text)
        lbl.setFixedWidth(190)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:11px; border:none;")
        lbl.setAlignment(th.ARIGHT)
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems([''] + options)
        combo.setStyleSheet(_field_qss())
        combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        combo.installEventFilter(self)      # العجلة تمرّر الصفحة (ما تغيّر القيمة)
        current = (self.extracted.get(key, '') or '').strip()
        if current:
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setEditText(current)
        lay.addWidget(lbl)
        lay.addWidget(combo, 1)
        self.entries[key] = combo
        self.review_lay.insertWidget(self.review_lay.count() - 1, row)

    def _entry_value(self, key):
        w = self.entries.get(key)
        if w is None:
            return ''
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        return w.text().strip()

    def _render_review_form(self):
        self._clear_review_extras()
        self.entries = {}
        d = self.extracted

        # تمييز بصري: خلفية حمراء فاتحة جداً لو القضية استعانة (نفس
        # لون التمييز المستخدم بباقي شاشات النظام) — لو تبين تغييرها
        # يدوياً بعدين، غيّر خيار 'نوع القضية' وتختفي تلقائياً بأي
        # إعادة استخراج، أو خليها كما هي.
        self.review_content.setStyleSheet(
            f"background:{SECONDMENT_BG};" if d.get('is_secondment') else ""
        )


        auto_title = QLabel("📌 بيانات مستخرجة تلقائيًا (قابلة للتعديل)")
        auto_title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:13px; font-weight:700; border:none;")
        auto_title.setAlignment(th.ARIGHT)
        self.review_lay.insertWidget(self.review_lay.count() - 1, auto_title)

        self._field("مرجع (ref)", 'ref')
        self._field("اسم المدعي", 'name_c')
        self._field("اسم المدعى عليه", 'name_p')
        self._field("تاريخ إحالة رئيس القسم", 'reg_date_r')
        self._field("تاريخ صدور الحكم", 'courtdate')
        self._field("رقم الدعوى الخام (كما وصل من الذكاء الاصطناعي)", 'raw_court_no')
        self._field("رقم الدائرة (c_no)", 'c_no')
        self._field("سنة الدعوى (c_year)", 'c_year')
        self._field("حرف/نوع الدعوى (c_lett)", 'c_lett')
        self._field("رقم المحكمة الفرعي (c_last_no)", 'c_last_no')

        manual_title = QLabel("✏️ حقول تدخلها يدويًا")
        manual_title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:13px; font-weight:700; border:none;")
        manual_title.setAlignment(th.ARIGHT)
        self.review_lay.insertWidget(self.review_lay.count() - 1, manual_title)

        self._field("اسم المحكمة (الكلية/استئناف/تمييز)", 'c_name', 'الكلية')
        self._dropdown("الخبير لوحده أو لجنة", 'comm', COMM_OPTIONS)
        self._dropdown("نوع القضية", 'type', TYPE_OPTIONS)
        # لو غيّرت النوع يدوياً (استعانة ⇄ أصالة)، تتحدث خلفية التمييز فوراً
        type_combo = self.entries.get('type')
        if type_combo is not None:
            type_combo.currentTextChanged.connect(self._on_type_changed)
        self._dropdown("رمز التخصص", 'spe', SPECIALTY_OPTIONS)

        try:
            expert_names = get_expert_names()
        except Exception:
            expert_names = []

        if expert_names:
            self._combo_editable("اسم الخبير الأول", 'expr_name1', expert_names)
            self._combo_editable("اسم الخبير الثاني", 'expr_name2', expert_names)
            self._combo_editable("اسم الخبير الثالث", 'expr_name3', expert_names)
        else:
            self._field("اسم الخبير الأول", 'expr_name1')
            self._field("اسم الخبير الثاني", 'expr_name2')
            self._field("اسم الخبير الثالث", 'expr_name3')

        self._field("المدة المحددة من رئيس القسم (بالأيام)", 'boss_est')
        self._field("الجلسة المحددة للخبير", 'expert_session_date')

        btns_row = QHBoxLayout()
        print_btn = SecondaryButton("🖨️ طباعة ملصق نصف ورقة")
        print_btn.clicked.connect(self._on_print_label_clicked)
        # 👁 معاينة: صحيفة الدعوى فوق وحكم الإحالة تحت — بنفس الملف، ونافذة
        # المعاينة الأصلية (مع زر طباعة) — 2026-11-10 (طلب العنزي).
        eye_btn = SecondaryButton("👁")
        eye_btn.setToolTip("معاينة صحيفة الدعوى + حكم الإحالة (ملف واحد) — والطباعة منها")
        eye_btn.clicked.connect(self._on_preview_merged_clicked)
        force_ai_btn = SecondaryButton("🔄 إعادة الاستخراج")
        force_ai_btn.clicked.connect(self._on_force_ai_clicked)
        upload_btn = SecondaryButton("📎 رفع حكم إحالة يدويًا")
        upload_btn.clicked.connect(self._on_upload_manual_clicked)
        save_btn = PrimaryButton("✅ إضافة للقاعدة")
        save_btn.clicked.connect(self._on_save_clicked)
        btns_row.addWidget(save_btn)
        btns_row.addWidget(force_ai_btn)
        btns_row.addWidget(upload_btn)
        btns_row.addWidget(print_btn)
        btns_row.addWidget(eye_btn)
        self.review_lay.insertLayout(self.review_lay.count() - 1, btns_row)

    def _on_type_changed(self, text):
        """تحديث خلفية التمييز فوراً لو غيّرت 'نوع القضية' يدوياً"""
        is_secondment = text.strip().startswith('استعانة')
        self.extracted['is_secondment'] = is_secondment
        self.review_content.setStyleSheet(
            f"background:{SECONDMENT_BG};" if is_secondment else ""
        )

    def _on_print_label_clicked(self):
        """يطبع ملصق نصف ورقة (طولي) بالحقول الأساسية عشان يُلصق فوق ملف
        القضية بدل كتابتها يدويًا — لا يحفظ أي شي بقاعدة البيانات، طباعة فقط."""
        values = {k: self._entry_value(k) for k in self.entries}
        fields = _label_fields_from_values(
            values, self.extracted.get('caso_no', '') or values.get('ref', ''))
        try:
            path = _build_label_html(fields)
            os.startfile(path)
        except Exception as e:
            QMessageBox.critical(self, "خطأ", f"تعذّرت طباعة الملصق:\n{th.ltr(e)}")

    # ---------- 👁 معاينة الملف: صحيفة الدعوى + حكم الإحالة (ملف واحد) ----------
    def _print_dir(self):
        """مجلد حفظ الملفات المنزَّلة (نفس مجلد الاستخراج)."""
        d = os.path.join(os.path.expanduser("~"), "Desktop", "judgments")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d

    # ---------- 👁 معاينة الملف: صحيفة الدعوى فوق وحكم الإحالة تحت (ملف واحد) ----------
    def _on_preview_merged_clicked(self):
        """
        يفتح نافذة المعاينة الأصلية (مع زر طباعة) على **ملف واحد** فيه:
        صحيفة الدعوى أول، ثم حكم الإحالة تحتها.
        ينزّل أي ملف ناقص من الملف الآلي قبل الدمج.
        """
        caso_no = (self.extracted.get('caso_no') or '').strip()
        autocase_no = (self.extracted.get('autocase_no') or '').strip()
        if not caso_no:
            QMessageBox.warning(self, "تنبيه", "استخرج بيانات القضية أولاً")
            return
        if not autocase_no:
            QMessageBox.warning(self, "غير متوفر",
                                "ما أعرف الرقم الآلي للقضية — استخرج البيانات أولاً.")
            return
        out_dir = self._print_dir()

        # 1) حكم الإحالة (موجود من الاستخراج غالباً)
        judgment_path = (self.extracted.get('judgment_path') or '').strip()
        if not (judgment_path and os.path.exists(judgment_path)
                and os.path.getsize(judgment_path) > 0):
            save_path = os.path.join(out_dir, f"{caso_no}_MAIN1.pdf")
            self.status_lbl.setText("⏳ جاري تحميل حكم الإحالة من الملف الآلي…")
            QApplication.processEvents()
            try:
                from documents import get_referral_judgment_for_case
                _judgment, path = get_referral_judgment_for_case(
                    self.cookies, autocase_no, "309", save_path)
            except Exception as e:
                self.status_lbl.setText("")
                QMessageBox.critical(self, "خطأ", f"تعذّر تحميل حكم الإحالة:\n{th.ltr(e)}")
                return
            self.status_lbl.setText("")
            if not path or not os.path.exists(path):
                QMessageBox.warning(self, "غير متوفر",
                                    "ما لقيت حكم إحالة في الملف الآلي لهذه القضية.")
                return
            judgment_path = path
            self.extracted['judgment_path'] = path

        # 2) صحيفة الدعوى
        claim_path = os.path.join(out_dir, f"{caso_no}_CLAIM.pdf")
        if not (os.path.exists(claim_path) and os.path.getsize(claim_path) > 0):
            self.status_lbl.setText("⏳ جاري تحميل صحيفة الدعوى من الملف الآلي…")
            QApplication.processEvents()
            try:
                from documents import get_claim_for_case
                _row, path, status = get_claim_for_case(
                    self.cookies, autocase_no, "309", claim_path)
            except Exception as e:
                self.status_lbl.setText("")
                QMessageBox.critical(self, "خطأ", f"تعذّر تحميل صحيفة الدعوى:\n{th.ltr(e)}")
                return
            self.status_lbl.setText("")
            if status != 'OK' or not path or not os.path.exists(path):
                QMessageBox.information(
                    self, "غير متوفر",
                    "ما لقيت صحيفة دعوى في الملف الآلي — بتعرض حكم الإحالة بس.")
                claim_path = None
            else:
                claim_path = path

        # 3) دمج: صحيفة الدعوى فوق وحكم الإحالة تحت — نفس الملف
        parts = [p for p in (claim_path, judgment_path) if p]
        merged = os.path.join(out_dir, f"{caso_no}_PREVIEW.pdf")
        try:
            _merge_pdfs(parts, merged)
        except Exception as e:
            QMessageBox.critical(self, "خطأ", f"تعذّر تجهيز ملف المعاينة:\n{th.ltr(e)}")
            return
        from qt_case_lookup import show_pdf_preview
        show_pdf_preview(self, merged, f"صحيفة الدعوى + حكم الإحالة — {caso_no}")

    def _on_save_clicked(self):
        values = {k: self._entry_value(k) for k in self.entries}

        values['no1'] = self.extracted.get('no1', '')
        values['no2'] = self.extracted.get('no2', '')
        values['no3'] = self.extracted.get('no3', '')

        names = [values.get(f'expr_name{i}', '') for i in range(1, 6)]
        values['ex_name'] = build_experts_dash_string(names)

        summary = (
            f"المرجع: {values.get('ref', '')}\n"
            f"المدعي: {values.get('name_c', '')}\n"
            f"المدعى عليه: {values.get('name_p', '')}\n"
            f"رقم المحكمة: {values.get('c_year','')}/{values.get('c_no','')}/{values.get('c_lett','')}/{values.get('c_last_no','')}\n"
            f"اسم الخبير: {values.get('ex_name', '')}\n"
            f"المدة المحددة: {values.get('boss_est', '')} يوم"
        )
        confirm = QMessageBox.question(
            self, "تأكيد الإضافة",
            f"هل تريد إضافة هذه القضية فعليًا لقاعدة البيانات؟\n\n{summary}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            ok, error = insert_case_record(values)
        except Exception as e:
            ok, error = False, str(e)

        if ok:
            QMessageBox.information(self, "تم", "تمت إضافة القضية بنجاح ✅")
            self.ref_entry.clear()
            self._clear_review_extras()
            self.status_lbl.setText("")
        else:
            QMessageBox.critical(self, "فشلت الإضافة", f"خطأ:\n{th.ltr(error)}")
