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
"""

import html as _html
import re

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

#: قيم النظام الفارغة — تجي كنص حرفي («null»/«None»/«undefined») وتطلع بالواجهة
#: كأنها قيمة حقيقية، بل وتُرسَل للنظام كرقم هاتف مثلاً. ننظّفها بمكان واحد.
NULL_VALUES = frozenset({'null', 'none', 'undefined', 'n/a', 'na', 'nil', '-'})

#: حقول العنوان/الاتصال (للتحقق: هل في عنوان مسجّل للطرف أصلاً؟)
ADDRESS_FIELDS = ('MAIN_CNTD_TYPE_DESC', 'ADRS_KASIMA', 'ADRS_BLOCK', 'ADRS_STREET',
                  'ADRS_UNIT_TYPE', 'ADRS_DESCR', 'ADRS_BUILDING_NO', 'ADRS_FLOOR',
                  'ADRS_UNIT_NO', 'ADDRNO', 'EIF_NOTE')

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


def parse_parties(html):
    """أطراف القضية من جدول «الاطراف»: [{'part_id','name','type'}].

    كل صف عنده ‎onclick="showadd('part_id')‎ — وهو مفتاح جلب نموذج العنوان.
    """
    out = []
    html = _strip_comments(html)
    for m in re.finditer(r'(?is)<tr\b([^>]*)>(.*?)</tr>', html or ''):
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
    for m in re.finditer(r'(?is)<input\b([^>]*)>', html):
        tag = '<input' + m.group(1) + '>'
        name = _attr(tag, 'name')
        if not name:
            continue
        fields[name] = clean_value(_attr(tag, 'value'))
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
        'methods': methods or list(CONTACT_METHODS.items()),
        'cities': cities or list(GOVERNORATES),
        'zones': zones,
    }


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


def fetch_page(cookies, caso_no, auto_no):
    """يقرأ صفحة «طلب اعلان» كاملة.

    يرجّع:
        {'ok': bool, 'case': {...}, 'parties': [...], 'results': [...],
         'message': str, 'reason': 'connection'|'no_data'|''}
    """
    out = {'ok': False, 'case': {}, 'parties': [], 'results': [], 'message': '', 'reason': ''}
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

    def val(name):
        v = values.get(name)
        if v is None:
            v = fields.get(name, '')
        return clean_value(v)

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


def send_inform(cookies, payload, dry_run=True):
    """يرسل طلب الإعلان للنظام.

    dry_run=True (الافتراضي): يبني الـ payload ويرجعه **بدون إرسال**.
    dry_run=False: يرسل فعلياً لـ insert_inform_detail.php.

    يرجع: {'ok','code','message','payload'}
    """
    payload = dict(payload or {})
    if dry_run:
        return {'ok': False, 'code': 'dry_run', 'message': 'معاينة فقط — ما تم الإرسال',
                'payload': payload}
    if not payload.get('part_id'):
        return {'ok': False, 'code': 'x', 'message': 'معرف الطرف مطلوب', 'payload': payload}
    try:
        r = _post(BASE_URL + SEND_INFORM, cookies, data=payload)
        code = (r.text or '').strip()
    except Exception as e:
        return {'ok': False, 'code': 'err', 'message': 'تعذر الاتصال بالنظام: %s' % e,
                'payload': payload}
    m = re.findall(r'\b([134])\b', code)
    code = m[-1] if m else code[:40]
    return {'ok': code == '1', 'code': code,
            'message': SEND_RESULTS.get(code, 'رد غير معروف من النظام'), 'payload': payload}


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
