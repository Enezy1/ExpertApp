"""
ilann.py — وحدة «طلب الإعلان» مع نظام الخبراء (expertapp.moj.gov.kw).

مهمتها: تسوي شغل صفحة «طلب اعلان» اللي بالنظام — من داخل برنامج ExpertApp:
  1) تختار القضية (رقم الخبرة) وتقرأ صفحة الطلب.
  2) تشوف أطراف القضية، وتعبّي/تعدّل بيانات العنوان ووسيلة الاتصال لكل طرف.
  3) ترسل الإعلان بالنظام الحقيقي (حفظ وإرسال) — «طلب اعلان» زي ما يسويه الخبير بنفسه.
  4) تقرأ «نتيجه الاعلان» (حالة الإعلان لكل طرف).
  5) تطبع «إشعار الإعلان» ملف Word.

⚠️ قواعد الأمان:
  • `send_inform()` الافتراضي dry_run=True ⟵ يبني الـ payload بس ولا يرسل شي.
    الإرسال الحقيقي يحتاج dry_run=False بعد ما الخبير يوافق على القيم المعروضة.
  • ما في أي تعامل مع «الإنجاز» ولا «الأتعاب» هنا (ملفاتها: anjaz.py).
  • ما في أي كتابة على النظام إلا في step 3 (عند موافقة صريحة).

مصدر المعلومات (كله مقيس على السيرفر الحقيقي 12/11/2026):
  • اختيار القضية : POST {BASE_URL}/includes/insert_showimg.php
                     {task_id: رقم الخبرة, caseid: الرقم الآلي}  → '1'
                     ⚠️ لازم قبل أي صفحة تبع الجلسة (نفسه اللي يسويه زر ⬇ «الملف الآلي»).
  • صفحة الطلب   : GET  {BASE_URL}/MEETING_INFORM.php
  • نموذج الطرف  : POST {BASE_URL}/includes/load_add.php   {part_id: معرف الطرف}
  • المناطق       : POST {BASE_URL}/includes/load_gov.php   {gov_id: رقم المحافظة}
  • إرسال الإعلان : POST {BASE_URL}/includes/insert_inform_detail.php
  • ردود الإرسال  : 1=تم حفظ الاعلان بنجاح · 3=يوجد اعلان سابق لنفس الطرف فى نفس الجلسه
                    4=لا يجوز ادخال اعلان لجلسه سابقه

⚠️ سياق الجلسة (اكتشاف حي 15/11/2026 — رسائل PHP من السيرفر نفسه):
  نقطة `insert_inform_detail.php` تقرأ من **جلسة السيرفر**:
    ECS_IN_REGNO_INFO (سطر 51) · ECS_MET_DATE (سطر 134) · ECS_MET_TIME (سطر 138)
  و نقطة `basic_info_result.php` (سطر 21-22) هي اللي **تكتب** التاريخ والوقت في الجلسة
  من `met_date`/`met_time`.
  ⟵ البرنامج كان يرسل `met_date=''` و`met_time=''` ⟵ الجلسة بلا تاريخ جلسة
  ⟵ السيرفر يرد «4» (لا يجوز ادخال اعلان لجلسه سابقه) حتى لو الجلسة قادمة!
  ⟵ الحل: نرسل تاريخ الجلسة ووقتها الحقيقيين (set_meeting_context) قبل الإرسال،
    ونعيد ضبطها لحظة الإرسال (مضمونة) — انظر set_meeting_context.
"""

import html as _html
import os
import re
import time

import requests

from config import BASE_URL

# ---------------------------------------------------------------------------
# نقاط النظام
# ---------------------------------------------------------------------------

INFORM_PAGE = '/MEETING_INFORM.php'
SELECT_CASE = '/includes/insert_showimg.php'
LOAD_PARTY = '/includes/load_add.php'
LOAD_ZONES = '/includes/load_gov.php'
SEND_INFORM = '/includes/insert_inform_detail.php'

#: وسيلة الاتصال (MAIN_CNTD_CODE_NEW) — أكوادها من نموذج النظام نفسه
CONTACT_METHODS = {
    '10001': 'مندوب',
    '10002': 'فاكس',
    '10003': 'بريد مسجل',
    '10004': 'إرشاد',
    '10005': 'النيابة العامة',
    '10006': 'مندوب(عنوان اخر)',
}

#: المحافظات (ADRS_CITY) — من نموذج النظام. لو تعذّر الجلب من السيرفر نستخدم هذي.
GOVERNORATES = [
    ('1', 'محافظه العاصمه'),
    ('2', 'محافظه حولى'),
    ('3', 'محافظه الجهراء'),
    ('4', 'محافظه الاحمدى'),
    ('5', 'الفروانيه'),
    ('6', 'مبارك الكبير'),
]

#: ردود حفظ/إرسال الإعلان (نفس رسائل SweetAlert في الموقع)
SEND_RESULTS = {
    '1': 'تم حفظ الاعلان بنجاح',
    '3': 'يوجد اعلان سابق لنفس الطرف فى نفس الجلسه',
    '4': 'لا يجوز ادخال اعلان لجلسه سابقه',
}

#: حقول العنوان/الاتصال: (اسم الحقل، العنوان، أقصى طول)
PARTY_FIELDS = (
    ('MAIN_CNTD_TYPE_DESC', 'عنوان اخر', ''),
    ('ADRS_KASIMA', 'جاده', 10),
    ('ADRS_BLOCK', 'القطعه', 4),
    ('ADRS_STREET', 'الشارع', ''),
    ('ADRS_UNIT_TYPE', 'نوع الوحده', ''),
    ('ADRS_DESCR', 'الوصف', ''),
    ('ADRS_BUILDING_NO', 'المبنى', 5),
    ('ADRS_FLOOR', 'الدور', 5),
    ('ADRS_UNIT_NO', 'رقم الوحده', 5),
    ('ADDRNO', 'الرقم الالى', 12),
    ('EIF_NOTE', 'الملاحظات', 150),
)

#: أعمدة جدول «نتيجه الاعلان»
RESULT_COLUMNS = ('الاسم', 'وسيله الاعلان', 'تاريخ الاعلان', 'تاريخ الجلسه',
                  'حاله الاعلان', 'سبب التعذر')

#: أعمدة جدول «الاطراف» — رأسه يميّزه عن جدول «نتيجه الاعلان»
PARTY_COLUMNS = ('الاسم', 'نوع الطرف', 'العنوان')

#: كلمات تميّز جدول «نتيجه الاعلان» (جدول مخرجات — مو جدول أطراف)
RESULT_TABLE_MARKERS = ('وسيله الاعلان', 'حاله الاعلان', 'سبب التعذر', 'تاريخ الاعلان')

#: كلمات تميّز جدول «الاطراف» (فيه زرّ «إعلان» لكل طرف)
PARTY_TABLE_MARKERS = ('نوع الطرف', 'الاطراف')

#: قيم النظام الفارغة — تجي كنص حرفي («null»/«None»/«undefined») وتطلع بالواجهة
#: كأنها قيمة حقيقية، بل وتُرسَل للنظام كرقم هاتف مثلاً. ننظّفها بمكان واحد.
NULL_VALUES = frozenset({'null', 'none', 'undefined', 'n/a', 'na', 'nil', '-'})

#: حقول العنوان/الاتصال (للتحقق: هل في عنوان مسجّل للطرف أصلاً؟)
ADDRESS_FIELDS = ('MAIN_CNTD_TYPE_DESC', 'ADRS_KASIMA', 'ADRS_BLOCK', 'ADRS_STREET',
                  'ADRS_UNIT_TYPE', 'ADRS_DESCR', 'ADRS_BUILDING_NO', 'ADRS_FLOOR',
                  'ADRS_UNIT_NO', 'ADDRNO', 'EIF_NOTE')

#: حدود الحقول في قاعدة الوزارة (نفس `maxlength` حقول نموذج الموقع).
#: ⚠️ ليش مهمّة (15/11/2026): السيرفر يرفض أي قيمة أطول بـORA-12899:
#:   «value too large for column "EXPRT"."CONTACTS_ADRS"."ADRS_BUILDING_NO"
#:    (actual: 9, maximum: 5)» ⟵ والموقع يقصّ الحقل في المتصفح تلقائياً
#:    (السطر `maxlength="5"`) — فالخبر عندنا يرسل القيمة الخام فيرفضها.
FIELD_LIMITS = {
    'ADRS_KASIMA': 10, 'ADRS_BLOCK': 4, 'ADRS_BUILDING_NO': 5,
    'ADRS_FLOOR': 5, 'ADRS_UNIT_NO': 5, 'ADDRNO': 12, 'EIF_NOTE': 150,
}

#: أسماء الحقول بالعربي (للرسالة وقت يرفض السيرفر قيمة طويلة)
FIELD_LABELS = {
    'ADRS_KASIMA': 'الجادة', 'ADRS_BLOCK': 'القطعة', 'ADRS_BUILDING_NO': 'المبنى',
    'ADRS_FLOOR': 'الدور', 'ADRS_UNIT_NO': 'رقم الوحدة', 'ADDRNO': 'رقم الاتصال',
    'EIF_NOTE': 'الملاحظات', 'ADRS_STREET': 'الشارع', 'ADRS_UNIT_TYPE': 'نوع الوحدة',
    'ADRS_DESCR': 'الوصف', 'MAIN_CNTD_TYPE_DESC': 'عنوان آخر',
    'MAIN_CNTD_CODE_NEW': 'وسيلة الإعلان', 'ADRS_CITY': 'المحافظة', 'ADRS_ZONE': 'المنطقة',
}

#: حقول بيانات القضية: (مفتاحنا، عناوين possibl متعددة كما يكتبها السيرفر)
CASE_FIELDS = {
    'auto_no': ('الرقم الالى', 'الرقم الآلى'),
    'case_no': ('رقم القضيه',),
    'expert_no': ('رقم الخبرة',),
    'entity': ('الجهه',),
    'type': ('النوع',),
    'category': ('تصنيف القضيه',),
    'in_date': ('تاريخ الوارد',),
    'out_date': ('تاريخ الصادر',),
    'expert_trust': ('امانه الخبير', 'امانة الخبير'),
    'expert_kind': ('صفه الخبير', 'صفة الخبير'),
}


# ---------------------------------------------------------------------------
# أدوات تحليل HTML
# ---------------------------------------------------------------------------

def _clean(x):
    """نص نظيف من HTML."""
    x = re.sub(r'<[^>]+>', '', x or '')
    x = _html.unescape(x).replace('\xa0', ' ').replace('&nbsp;', ' ')
    return re.sub(r'\s+', ' ', x).strip()


def clean_value(value):
    """يحوّل قيمة النظام الفارغة إلى فراغ حقيقي.

    نظام الوزارة يكتب القيمة الفارغة كنص حرفي («null» أو «None» أو «undefined»)،
    فلو تمرّرت زي ما هي تطلع بالواجهة كأنها قيمة (رقم هاتف «null»!) وتُرسَل
    للنظام بحالها. الدالة едиّة: تُطبَّق عند الجلب وقبل الإرسال.
    """
    if value is None:
        return ''
    s = str(value).strip()
    if s.lower() in NULL_VALUES:
        return ''
    return s


def _strip_comments(html):
    """يشيل تعليقات HTML — النظام يحط كود قديم داخل <!-- --> وبالpars يطلع خطأ."""
    return re.sub(r'(?s)<!--.*?-->', '', html or '')


def _attr(tag, name):
    """قيمة خاصية داخل وسم HTML — يتعامل مع Value= بدون علامات اقتباس
    (نظام الوزارة يكتب كثير من الحقول هالشكل: Value=احمد الجابر)."""
    m = re.search(r'(?is)\b%s\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^>]+))' % re.escape(name), tag)
    if not m:
        return ''
    val = (m.group(1) or m.group(2) or m.group(3) or '').strip()
    if m.group(3):  # قيمة بدون اقتباس: نقص عند أول خاصية بعدها (selected/disabled/...)
        cut = re.search(r'(?is)\s+[A-Za-z_:][-\w:.]*\s*=|\s+(selected|disabled|checked|readonly|required|multiple)\b',
                        val)
        if cut:
            val = val[:cut.start()]
    val = _html.unescape(val)
    return val.replace('\xa0', ' ').strip().strip('/').strip()


def _label_value_pairs(html):
    """يرجّع [(عنوان الحقل, القيمة)] من بورتlets النموذج: كل <label> يليه <input>."""
    out = []
    html = _strip_comments(html)
    for m in re.finditer(r'(?is)<label[^>]*>(.*?)</label>(.{0,600}?)<input\b([^>]*)>', html):
        label = _clean(m.group(1))
        value = _attr(m.group(3), 'value')
        if label:
            out.append((label, value))
    return out


def _options(html):
    """خيارات <select>: [(القيمة, النص)] — يتعامل مع value بدون اقتباس."""
    out = []
    for o in re.finditer(r'(?is)<option\b([^>]*)>(.*?)</option>', html):
        val = _attr('<option' + o.group(1) + '>', 'value')
        txt = _clean(o.group(2))
        out.append((val, txt))
    return out


def _selected(html, name):
    """القيمة المختارة داخل select محدد بالاسم."""
    m = re.search(r'(?is)<select\b[^>]*name="%s"[^>]*>(.*?)</select>' % re.escape(name), html)
    if not m:
        return ''
    body = m.group(1)
    for o in re.finditer(r'(?is)<option\b([^>]*)>(.*?)</option>', body):
        if 'selected' in (o.group(1) or '').lower():
            return _attr('<option' + o.group(1) + '>', 'value')
    return ''


# ---------------------------------------------------------------------------
# صفحة «طلب اعلان»
# ---------------------------------------------------------------------------

def parse_case_info(html):
    """بيانات القضية من صفحة الطلب: {label: value}."""
    info = {}
    html = _strip_comments(html)
    for label, value in _label_value_pairs(html or ''):
        if label and label not in info:
            info[label] = value
    # رقم الخبرة متاح بمعرّف الحقل أحيانًا
    m = re.search(r'(?is)<input\b[^>]*id="ECS_IN_REGNO"[^>]*>', html or '')
    if m:
        info.setdefault('رقم الخبرة', _attr(m.group(0), 'value'))
    return info


def case_field(info, key, default=''):
    """يرجّع قيمة من بيانات القضية بمفتاح ثابت (يتحمل اختلاف كتابة السيرفر)."""
    info = info or {}
    for label in CASE_FIELDS.get(key, ()):
        if label in info and info[label] != '':
            return info[label]
    return default


def _table_head_text(table):
    """نص رأس الجدول (خلايا th) — لتمييز جدول الأطراف عن جدول النتائج."""
    head = table.split('</thead>')[0] if '</thead>' in table else ''
    if not head:
        # بلا thead: ناخذ أول صف كرأس
        m = re.search(r'(?is)<tr\b[^>]*>(.*?)</tr>', table)
        head = m.group(1) if m else ''
    cells = re.findall(r'(?is)<t[hd]\b[^>]*>(.*?)</t[hd]>', head)
    return ' '.join(_clean(c) for c in cells)


def _is_results_table(table):
    """جدول «نتيجه الاعلان» — مخرجات الإعلان، مو أطراف القضية."""
    head = _table_head_text(table)
    return any(k in head for k in RESULT_TABLE_MARKERS)


def _is_party_table(table):
    """جدول «الاطراف» — أطراف القضية (فيه زرّ «إعلان» لكل طرف)."""
    head = _table_head_text(table)
    return any(k in head for k in PARTY_TABLE_MARKERS)


def parse_parties(html):
    """أطراف القضية من جدول «الاطراف»: [{'part_id','name','type'}].

    كل صف عنده ‎onclick="showadd('part_id')‎ — وهو مفتاح جلب نموذج العنوان.

    ⚠️ (15/11/2026) ليش ما نمرّ على كل صفوف الصفحة:
      صفحة الطلب فيها **جدولين** — «الاطراف» و«نتيجه الاعلان» — وصفوف الثاني
      تبدأ باسم الطرف وبعمود «وسيله الاعلان» (مندوب/رسائل/هاتف…). فلو مرّرنا
      على كل ‎<tr>‎ ⟵ بعد إرسال إعلان يتكرّر نفس الشخص مرتين: سطر «مدعى عليه»
      وسطر «مندوب» (و«مندوب» وسيلة الإعلان مو صفة طرف، وهذا الصف ما فيه زرّ
      إعلان أصلاً).
      الحل: نقرأ **جدول الأطراف فقط** — نميّزه برأسه («نوع الطرف»)،
      وبالاحتياط بوجود زرّ الطرف (showadd) في صفوفه.
    """
    out = []
    html = _strip_comments(html or '')
    tables = re.findall(r'(?is)<table.*?</table>', html)
    if not tables:
        return out
    party_tables = [t for t in tables if _is_party_table(t) and not _is_results_table(t)]
    if party_tables:
        source = party_tables
    else:
        # احتياط: لو تغيّر نص الرأس — الجداول اللي صفوفها فيها زرّ الطرف
        source = [t for t in tables
                  if not _is_results_table(t) and "showadd('" in t]
        if not source:
            # احتياط أخير: أي جدول غير جدول النتائج (السلوك القديم)
            source = [t for t in tables if not _is_results_table(t)]
    for table in source:
        for m in re.finditer(r'(?is)<tr\b([^>]*)>(.*?)</tr>', table):
            attrs, row = m.group(1), m.group(2)
            cells = [_clean(c) for c in re.findall(r'(?is)<td\b[^>]*>(.*?)</td>', row)]
            if len(cells) < 2:
                continue
            pid = ''
            pm = re.search(r"showadd\('([^']*)'\)", attrs + row)
            if pm:
                pid = pm.group(1)
            out.append({'part_id': pid, 'name': cells[0], 'type': cells[1] if len(cells) > 1 else ''})
    return out


def parse_results(html):
    """صفوف جدول «نتيجه الاعلان»: [{'name','means','date','session_date','status','reason'}]."""
    rows = []
    html = _strip_comments(html)
    for m in re.finditer(r'(?is)<table.*?</table>', html or ''):
        table = m.group(0)
        if 'حاله الاعلان' not in table and 'وسيله الاعلان' not in table:
            continue
        body = re.search(r'(?is)<tbody\b[^>]*>(.*?)</tbody>', table)
        if not body:
            continue
        for r in re.finditer(r'(?is)<tr\b[^>]*>(.*?)</tr>', body.group(1)):
            cells = [_clean(c) for c in re.findall(r'(?is)<td\b[^>]*>(.*?)</td>', r.group(1))]
            if not cells:
                continue
            cells += [''] * (6 - len(cells))
            rows.append({
                'name': clean_value(cells[0]), 'means': clean_value(cells[1]),
                'date': clean_value(cells[2]), 'session_date': clean_value(cells[3]),
                'status': clean_value(cells[4]), 'reason': clean_value(cells[5]),
            })
        break
    return rows


def parse_party_form(html):
    """نموذج عنوان/اتصال الطرف.

    يرجّع قاموس:
        {'part_id','cnt_seq','contact_code','contact_label',
         'fields': {اسم الحقل: القيمة},
         'methods': [(كود, اسم)], 'cities': [(كود, اسم)], 'zones': [(كود, اسم)]}
    """
    html = _strip_comments(html)
    fields = {}
    limits = {}
    for m in re.finditer(r'(?is)<input\b([^>]*)>', html):
        tag = '<input' + m.group(1) + '>'
        name = _attr(tag, 'name')
        if not name:
            continue
        fields[name] = clean_value(_attr(tag, 'value'))
        # حدّ الحقل حسب نموذج النظام (`maxlength`) — حماية من ORA-12899
        ml = re.search(r'(?is)\bmaxlength\s*=\s*"?(\d+)"?', tag)
        if ml:
            limits[name] = int(ml.group(1))
    m = re.search(r'(?is)<select\b[^>]*name="MAIN_CNTD_CODE_NEW"[^>]*>(.*?)</select>', html)
    methods = _options(m.group(1)) if m else []
    m = re.search(r'(?is)<select\b[^>]*name="ADRS_CITY"[^>]*>(.*?)</select>', html)
    cities = _options(m.group(1)) if m else []
    m = re.search(r'(?is)<select\b[^>]*name="ADRS_ZONE"[^>]*>(.*?)</select>', html)
    zones = _options(m.group(1)) if m else []
    # القيم المختارة في القوائم المنسدلة (المحافظة/المنطقة/وسيلة الاتصال)
    for name in ('ADRS_CITY', 'ADRS_ZONE', 'MAIN_CNTD_CODE_NEW'):
        picked = _selected(html, name)
        if picked:
            fields[name] = clean_value(picked)
    return {
        'part_id': fields.get('part_id', ''),
        'cnt_seq': fields.get('CNT_SEQ', ''),
        'contact_code': _selected(html, 'MAIN_CNTD_CODE_NEW'),
        'contact_label': clean_value(fields.get('MAIN_CNTD_CODE', '')),
        'fields': fields,
        'limits': limits,
        'methods': methods or list(CONTACT_METHODS.items()),
        'cities': cities or list(GOVERNORATES),
        'zones': zones,
    }


def truncate_field(name, value, limits=None):
    """يقصّ القيمة لحدّ النظام (نفس `maxlength` بالموقع).

    ⚠️ بدون هالقصّ يرفض السيرفر الإSaving بـORA-12899 («value too large for
    column …») — والموقع يقصّها في المتصفح تلقائياً، فنحاكي نفس السلوك.
    """
    v = clean_value(value)
    lim = (limits or {}).get(name) or FIELD_LIMITS.get(name)
    if lim and len(v) > lim:
        return v[:lim]
    return v


def field_limit(name, limits=None):
    """حدّ الحقل (من نموذج النظام أو من الجدول الافتراضي)."""
    return (limits or {}).get(name) or FIELD_LIMITS.get(name)


def form_has_address(form):
    """هل في عنوان/اتصال مسجّل للطرف أصلاً؟

    يفرق بين حالتين يخلطهم الكود سابقاً:
      • «ما فيه عنوان مسجّل لهذا الطرف»  ⟵ النموذج رجع فاضي فعلاً
      • «تعذّر الاتصال بالنظام»          ⟵ الطلب ما وصل (استثناء) — ما يمرّ هنا
    """
    fields = (form or {}).get('fields') or {}
    return any(clean_value(fields.get(name)) for name in ADDRESS_FIELDS)



# ---------------------------------------------------------------------------
# الشبكة
# ---------------------------------------------------------------------------

def _get(url, cookies, **kw):
    kw.setdefault('verify', False)
    kw.setdefault('timeout', 25)
    return requests.get(url, cookies=cookies, **kw)


def _post(url, cookies, data=None, **kw):
    kw.setdefault('verify', False)
    kw.setdefault('timeout', 25)
    return requests.post(url, data=data or {}, cookies=cookies, **kw)


def select_case(cookies, caso_no, auto_no):
    """يختار القضية بالجلسة (نفس خطوة زر ⬇ «الملف الآلي» بالموقع).

    ⚠️ لازم هالخطوة قبل صفحة الطلب — بدونها ترجع «لا توجد بيانات».
    ⚠️ يرفع استثناء الشبكة (ما يبتلعه) عشان الواجهة تفرّق «تعذّر الاتصال»
    عن «لا توجد بيانات» — الاسم القديم كان يرجع False للاثنين.
    """
    if not caso_no:
        return False
    r = _post(BASE_URL + SELECT_CASE, cookies,
              data={'task_id': str(caso_no).strip(), 'caseid': str(auto_no or '').strip()})
    return '1' in (r.text or '')


_MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
           'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')


def normalize_meeting_date(value):
    """تاريخ الجلسة بصيغة نظام الخبراء: **yyyy/mm/dd** (مثل تقويم الموقع).

    ⚠️ الصيغة مهمّة جداً — مقيسة حيّاً 15/11/2026:
      `basic_info_result.php` (نقطة ضبط سياق الجلسة) تقارن التاريخ بتاريخ الجلسة،
      و«yyyy/mm/dd» هي الوحيدة اللي قبلها السيرفر:
        yyyy/mm/dd → الرد «2» (فحص التاريخ نجح ✅)
        dd/mm/yyyy · yyyy-mm-dd · DD-MON-YY → الرد «4» (لا يجوز ادخال اعلان
        لجلسه سابقه) — أي «الجلسة السابقة» حتى لو الجلسة قادمة!
    """
    s = str(value or '').strip()
    if not s:
        return ''
    s = s.split(' ')[0].strip()
    m = re.fullmatch(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', s)
    if m:
        return '%s/%02d/%02d' % (m.group(1), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', s)
    if m:
        return '%s/%02d/%02d' % (m.group(3), int(m.group(2)), int(m.group(1)))
    m = re.fullmatch(r'(\d{1,2})-([A-Za-z]{3})-(\d{2,4})', s)
    if m and m.group(2).upper() in _MONTHS:
        year = m.group(3)
        if len(year) == 2:
            year = '20' + year
        return '%s/%02d/%02d' % (year, _MONTHS.index(m.group(2).upper()) + 1,
                                 int(m.group(1)))
    return s


def normalize_meeting_time(value):
    """وقت الجلسة بصيغة hh:mm (مثل تقويم الموقع: '10:00')."""
    s = str(value or '').strip()
    if not s:
        return ''
    m = re.match(r'(\d{1,2}):(\d{2})', s)
    if m:
        return '%02d:%s' % (int(m.group(1)), m.group(2))
    return s


def set_meeting_context(cookies, caso_no, met_date='', met_time=''):
    """يضبط **سياق الجلسة** عند الوزارة: رقم الخبرة + تاريخ الجلسة + وقتها.

    ⚠️ الأهم في وحدة «طلب إعلان» — بدونها الإرسال ما ينجح:

    نقطة `insert_inform_detail.php` تقرأ من جلسة السيرفر (مش من الطلب):
        ECS_IN_REGNO_INFO (سطر 51) · ECS_MET_DATE (سطر 134) · ECS_MET_TIME (سطر 138)
    ونقطة `basic_info_result.php` (سطر 21-22) هي اللي تكتبها من `met_date`/`met_time`.

    ⟵ لو أرسلنا التاريخ والوقت فاضيين (زي ما كان) ⟵ الجلسة بلا تاريخ جلسة
    ⟵ السيرفر يرد «4» = «لا يجوز ادخال اعلان لجلسه سابقه» — حتى لو الجلسة **قادمة**.
    (هذا بالضبط ما صار 15/11/2026: الردود كانت 4 و«تعذّر الإرسال» لكل القضايا.)

    ⚠️ تاريخ الجلسة لازم يكون بصيغة **yyyy/mm/dd** — انظر normalize_meeting_date.
    ⚠️ ترتيب مهم: أي طلب لـ`basic_info_result.php` بـ`met_date` فاضي **يمسح** الجلسة —
    لذلك نضبط السياق **بعد** resolve_auto_no، ونعيد ضبطه **لحظة الإرسال**.
    """
    data = {'id': '1', 'title': str(caso_no or '').strip(),
            'description': str(caso_no or '').strip(),
            'met_date': normalize_meeting_date(met_date),
            'met_time': normalize_meeting_time(met_time)}
    try:
        r = _post(BASE_URL + '/includes/basic_info_result.php', cookies, data=data)
        return bool(r is not None)
    except Exception:
        return False


def resolve_auto_no(caso_no, cookies, fallback=''):
    """الرقم الآلي: من النظام (basic_info) أولاً، وإلا `fallback` (المحلي)."""
    try:
        import case_stats
        info = case_stats.get_case_basic_info(caso_no, cookies) or {}
        if info.get('autocase_no'):
            return str(info['autocase_no']).strip()
    except Exception:
        pass
    return str(fallback or '').strip()


def fetch_page(cookies, caso_no, auto_no, session_date='', session_time=''):
    """يقرأ صفحة «طلب اعلان» كاملة.

    يرجّع:
        {'ok': bool, 'case': {...}, 'parties': [...], 'results': [...],
         'message': str, 'reason': 'connection'|'no_data'|''}
    """
    out = {'ok': False, 'case': {}, 'parties': [], 'results': [], 'message': '', 'reason': ''}
    # الرقم الآلي من النظام أولاً (مصدر موثوق)؛ المحلي من القاعدة قد يكون قديم/غلط
    # ⟵ يختار قضية غلط فترجع «لا توجد بيانات». (هذا اللي انكسر لما شلنا الجلب.)
    auto_no = resolve_auto_no(caso_no, cookies, auto_no)
    # ⚠️ بعد resolve_auto_no بالضبط: هو يطلب basic_info_result.php بـ met_date فاضي
    #    ⟵ يمسح سياق الجلسة. فنضبط تاريخ الجلسة ووقتها الحقيقيين هنا.
    if session_date:
        set_meeting_context(cookies, caso_no, session_date, session_time)
    try:
        selected = select_case(cookies, caso_no, auto_no)
    except Exception:
        out['message'] = 'تعذّر الاتصال بنظام الخبراء'
        out['reason'] = 'connection'
        return out
    if not selected:
        out['message'] = 'لا توجد بيانات لهذا الرقم في نظام الخبراء'
        out['reason'] = 'no_data'
        return out
    try:
        r = _get(BASE_URL + INFORM_PAGE, cookies)
        html = r.text or ''
    except Exception:
        out['message'] = 'تعذّر الاتصال بنظام الخبراء'
        out['reason'] = 'connection'
        return out
    if 'لا توجد بيانات' in html:
        out['message'] = 'لا توجد بيانات لهذه القضية في صفحة «طلب اعلان»'
        out['reason'] = 'no_data'
        return out
    out['ok'] = True
    out['case'] = parse_case_info(html)
    out['parties'] = parse_parties(html)
    out['results'] = parse_results(html)
    return out


def fetch_party_form(cookies, part_id):
    """يجيب نموذج العنوان/الاتصال لطرف معيّن.

    ⚠️ ما يبتلع الاستثناء: أي فشل شبكة يطلع للواجهة عشان تعرض «تعذّر الاتصال
    بالنظام» مع زر «إعادة المحاولة» — مو نموذج فاضي يوهم الخبير إن العنوان
    مو مسجّل أصلاً (previously كان يبتلع الاستثناء ويرجع نموذج فاضي).
    """
    out = {'part_id': str(part_id or ''), 'cnt_seq': '', 'contact_code': '',
           'contact_label': '', 'fields': {}, 'methods': list(CONTACT_METHODS.items()),
           'cities': list(GOVERNORATES), 'zones': []}
    if not part_id:
        return out
    r = _post(BASE_URL + LOAD_PARTY, cookies, data={'part_id': str(part_id)})
    html = r.text or ''
    parsed = parse_party_form(html)
    parsed['part_id'] = parsed.get('part_id') or str(part_id)
    return parsed


def fetch_zones(cookies, gov_id):
    """مناطق المحافظة: [(كود, اسم)] — فاضي لو ما ضبط."""
    try:
        r = _post(BASE_URL + LOAD_ZONES, cookies, data={'gov_id': str(gov_id or '')})
        return _options(r.text or '')
    except Exception:
        return []


# ---------------------------------------------------------------------------
# الإرسال
# ---------------------------------------------------------------------------

def build_payload(form, values):
    """يبني الـ payload بالضبط مثل insert_inform_detail() بالموقع.

    form: ناتج fetch_party_form/parse_party_form.
    values: القيم اللي عدّلها الخبير (نفس أسماء الحقول).
    """
    values = values or {}
    fields = (form or {}).get('fields') or {}
    limits = (form or {}).get('limits') or {}

    def val(name):
        v = values.get(name)
        if v is None:
            v = fields.get(name, '')
        # ⚠️ قصّ حسب حدّ النظام — وإلا رفض الإرسال بـORA-12899
        return truncate_field(name, v, limits)

    method_code = str(values.get('MAIN_CNTD_CODE_NEW') or
                      (form or {}).get('contact_code') or '').strip()
    method_label = ''
    for code, label in (form or {}).get('methods') or CONTACT_METHODS.items():
        if str(code) == method_code:
            method_label = label
            break
    if not method_label:
        method_label = CONTACT_METHODS.get(method_code, '')

    payload = {
        'MAIN_CNTD_CODE_NEW': method_code,
        'MAIN_CNTD_TYPE_DESC': val('MAIN_CNTD_TYPE_DESC'),
        'ADRS_CITY': val('ADRS_CITY'),
        'ADRS_ZONE': val('ADRS_ZONE'),
        'ADRS_KASIMA': val('ADRS_KASIMA'),
        'ADRS_BLOCK': val('ADRS_BLOCK'),
        'ADRS_STREET': val('ADRS_STREET'),
        'ADRS_UNIT_TYPE': val('ADRS_UNIT_TYPE'),
        'ADRS_DESCR': val('ADRS_DESCR'),
        'ADRS_BUILDING_NO': val('ADRS_BUILDING_NO'),
        'ADRS_FLOOR': val('ADRS_FLOOR'),
        'ADRS_UNIT_NO': val('ADRS_UNIT_NO'),
        'ADDRNO': val('ADDRNO'),
        'EIF_NOTE': val('EIF_NOTE'),
        'part_id': clean_value(values.get('part_id') or fields.get('part_id')),
        'CNT_SEQ': clean_value(values.get('CNT_SEQ') or fields.get('CNT_SEQ')),
    }
    # MAIN_CNTD_CODE = النص العربي لوسيلة الاتصال (حقل مخفي بالنظام)
    payload['MAIN_CNTD_CODE'] = method_label
    return payload


_ORA_TOO_LONG = re.compile(
    r'ORA-12899.*?(?:"|&quot;|\')(?:[A-Z_]+"\."){0,3}(?:"|&quot;|\')?'
    r'([A-Z_]+)(?:"|&quot;|\')\s*\(\s*actual\s*:\s*(\d+)\s*,'
    r'\s*maximum\s*:\s*(\d+)\s*\)', re.S)


def _too_long_field(text):
    """لو السيرفر رفض قيمة طويلة (ORA-12899) ⟵ (اسم الحقل، الطول، الحد)."""
    m = _ORA_TOO_LONG.search(text or '')
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


#: أخطاء Oracle المتوقعة عند الحفظ — مترجمة لرسالة يفهمها الخبير
ORA_MESSAGES = {
    'ORA-12899': 'حقل أطول من المسموح بالنظام',
    'ORA-01400': 'حقل مطلوب فاضي بالنظام',
    'ORA-02291': 'الطرف غير موجود بالنظام (أعد جلب النموذج)',
    'ORA-00001': 'فيه سجل مكرر (إعلان سابق لنفس الطرف)',
    'ORA-01722': 'رقم تسلسلي مكرر (أعد المحاولة)',
}


def _ora_error(text):
    """لو رد السيرفر فيه خطأ Oracle ⟵ (الكود، الشرح، التفصيل)."""
    m = re.search(r'(ORA-\d{5})', text or '')
    if not m:
        return None
    code = m.group(1)
    detail = ''
    too_long = _too_long_field(text)
    if too_long:
        detail = ' (الحقل %s فيه %s حرف والحدّ %s)' % (too_long[0], too_long[1], too_long[2])
    return code, ORA_MESSAGES.get(code, 'خطأ في قاعدة بيانات الوزارة'), detail


def _parse_send_response(text):
    """يحلل رد نقطة الإرسال ⟵ (code, raw).

    الرد الطبيعي رقم لحاله ('1' تم · '3' إعلان سابق · '4' جلسة سابقة).
    لكن السيرفر مفعّل display_errors ⟵ الرد ممكن يكون تحذيرات PHP قبل الكود،
    فالكود هو **آخر سطر** فيه رقم لحاله.
    """
    raw = (text or '').strip()
    plain = re.sub(r'<[^>]+>', '\n', raw)
    lines = [l.strip() for l in plain.splitlines() if l.strip()]
    if lines and lines[-1] in ('1', '3', '4'):
        return lines[-1], raw
    m = re.findall(r'(?<![\w.])([134])(?![\w.])', plain)
    return (m[-1] if m else ''), raw


def _log_send(entry):
    """سجل تشخيص الإرسال — سبب الفشل الحقيقي مكتوب محلياً.

    الملف: %LOCALAPPDATA%\\ExpertApp\\ilann_send.log
    """
    try:
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        path = os.path.join(base, 'ExpertApp', 'ilann_send.log')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' | ' + entry + '\n')
    except Exception:
        pass


def send_inform(cookies, payload, dry_run=True, caso_no='', auto_no='',
                session_date='', session_time=''):
    """يرسل طلب الإعلان للنظام.

    dry_run=True (الافتراضي): يبني الـ payload ويرجعه **بدون إرسال**.
    dry_run=False: يرسل فعلياً لـ insert_inform_detail.php.

    ⚠️ قبل الإرسال نعيد ضبط سياق الجلسة (رقم الخبرة + تاريخ الجلسة + وقتها)
    — انظر set_meeting_context — لأن أي طلب آخر لـ basic_info_result.php
    بـ met_date فاضي يمسحه، والسيرفر بدونه يرد «4» (جلسة سابقة) بلا سبب.

    يرجع: {'ok','code','message','payload','raw','status'}
    """
    payload = dict(payload or {})
    if dry_run:
        return {'ok': False, 'code': 'dry_run', 'message': 'معاينة فقط — ما تم الإرسال',
                'payload': payload}
    if not payload.get('part_id'):
        return {'ok': False, 'code': 'x', 'message': 'معرف الطرف مطلوب', 'payload': payload}

    # ---- 1) سياق الجلسة: رقم الخبرة + تاريخ الجلسة + وقتها ----
    if session_date:
        set_meeting_context(cookies, caso_no, session_date, session_time)
    if caso_no:
        # إعادة تحديد القضية (نفس خطوة «الملف الآلي» بالموقع) — السيرفر يعتمد عليها
        try:
            select_case(cookies, caso_no, auto_no)
        except Exception:
            pass

    # ---- 2) الإرسال ----
    try:
        r = _post(BASE_URL + SEND_INFORM, cookies, data=payload)
        body = r.text or ''
        status = getattr(r, 'status_code', '')
    except Exception as e:
        _log_send('caso=%s part=%s EXC %s' % (caso_no, payload.get('part_id'), e))
        return {'ok': False, 'code': 'err', 'message': 'تعذر الاتصال بالنظام: %s' % e,
                'payload': payload}
    code, raw = _parse_send_response(body)
    too_long = _too_long_field(body)
    if too_long:
        fname, actual, maximum = too_long
        label = FIELD_LABELS.get(fname, fname)
        code = 'too_long'
        msg = ('حقل «%s» فيه %s حرف والنظام يسمح بـ%s — قصّره وأعد الإرسال.'
               % (label, actual, maximum))
        _log_send('caso=%s part=%s met=%s %s | status=%s | code=too_long(%s %s>%s) | %s'
                  % (caso_no, payload.get('part_id'), session_date, session_time,
                     status, fname, actual, maximum, msg))
        return {'ok': False, 'code': 'too_long', 'message': msg, 'payload': payload,
                'raw': raw, 'status': status}
    ora = _ora_error(body)
    if ora:
        ora_code, why, detail = ora
        code = 'ora'
        msg = '%s%s' % (why, detail)
        _log_send('caso=%s part=%s met=%s %s | status=%s | code=%s (%s) | %s'
                  % (caso_no, payload.get('part_id'), session_date, session_time,
                     status, ora_code, msg, raw[:300].replace('\n', ' ')))
        return {'ok': False, 'code': 'ora', 'message': msg, 'payload': payload,
                'raw': raw, 'status': status}
    _log_send('caso=%s part=%s met=%s %s | status=%s | code=%s | raw=%s'
              % (caso_no, payload.get('part_id'), session_date, session_time,
                 status, code or '-', raw[:400].replace('\n', ' ')))
    return {'ok': code == '1', 'code': code or 'unknown',
            'message': SEND_RESULTS.get(code, 'رد غير معروف من النظام'),
            'payload': payload, 'raw': raw, 'status': status}


# ---------------------------------------------------------------------------
# الطباعة — «إشعار الإعلان»
# ---------------------------------------------------------------------------

def notice_docx(path, caso_no, party=None, results=None, case_info=None,
                expert_name='', header_line2='الإدارة العامة للخبراء'):
    """يولّد ملف Word لـ«إشعار الإعلان» (بيانات party's + نتيجة الإعلان).

    party: {'name','type','contact','address','phone'} — اختياري.
    results: صفوف «نتيجه الاعلان» (نفس ناتج parse_results).
    case_info: {'auto_no','case_no','type','in_date','expert_no'}
    """
    import base64
    import os

    import report_builder as rb

    info = case_info or {}
    party = party or {}
    results = results or []

    assets = os.path.join(getattr(os.sys, '_MEIPASS', None) or
                          os.path.dirname(os.path.abspath(__file__)), 'report_assets')
    try:
        with open(os.path.join(assets, 'emblem.jpg'), 'rb') as f:
            emblem = base64.b64encode(f.read())
        with open(os.path.join(assets, 'badge.jpg'), 'rb') as f:
            badge = base64.b64encode(f.read())
        rb.load_images(emblem, badge)
    except Exception:
        pass

    rep = rb.Report(header_line2=header_line2)
    rep.title('إشعار إعلان')
    rep.text('إشعار إعلان خاص بالقضية رقم الخبرة: %s' % caso_no, jc='center', b=True)

    facts = []
    if info.get('auto_no'):
        facts.append('الرقم الالى: %s' % info['auto_no'])
    if info.get('case_no'):
        facts.append('رقم القضيه: %s' % info['case_no'])
    if info.get('type'):
        facts.append('نوع القضيه: %s' % info['type'])
    if info.get('in_date'):
        facts.append('تاريخ الوارد: %s' % info['in_date'])
    if facts:
        rep.text(' • '.join(facts), jc='center')

    if party:
        rep.blank()
        rep.subheading('بيانات الطرف')
        rows = [
            ['الاسم', party.get('name', '')],
            ['نوع الطرف', party.get('type', '')],
            ['وسيلة الاتصال', party.get('contact', '')],
            ['العنوان', party.get('address', '')],
            ['الرقم الالى', party.get('phone', '')],
        ]
        rep.data_table(['البيان', 'القيمة'], rows, [2600, 7136])

    if results:
        rep.blank()
        rep.subheading('نتيجة الإعلان')
        hdr = ['الاسم', 'وسيله الاعلان', 'تاريخ الاعلان', 'تاريخ الجلسه', 'حاله الاعلان']
        body = [[r.get('name', ''), r.get('means', ''), r.get('date', ''),
                 r.get('session_date', ''), r.get('status', '')] for r in results]
        rep.data_table(hdr, body, [2600, 1700, 1500, 1500, 1436])

    if expert_name:
        rep.text('الخبير: %s' % expert_name, jc='right')
    rep.blank()
    rep.signature([('الخبير', expert_name)] if expert_name else [])
    return rep.save(path)
