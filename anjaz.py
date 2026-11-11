"""
anjaz.py — وحدة «الأتعاب» (رسوم الخبرة) مع نظام الخبراء (expertapp.moj.gov.kw).

مهمتها:
  1) تقرأ نموذج الأتعاب من النظام (صفحة FEES_DONE) لاستخراج أسماء
     المصروفات وأكوادها.
  2) تحفظ أتعاب القضية عبر نفس آلية الموقع (includes/insert_fee.php).
  3) تطبع «رسوم الخبرة» كملف Word (باستخدام report_builder، بترويسة الوزارة).

⚠️ قواعد الأمان (مطلوبة):
  • حفظ الأتعاب = كتابة بالنظام الحقيقي. لذلك `save_fees()` الافتراضي
    dry_run=True (يبني الـ payload ويرجعه بدون ما يرسل شي). الإرسال الحقيقي
    يتطلب dry_run=False — ويكون بعد موافقة الخبير على القيم المعروضة.
  • ما في أي تعامل مع «الإنجاز» هنا إطلاقاً (قرار الخبير: لا تقرب منه —
    الخطأ فيه ما ينموي). وحدة القراءة فقط لسجل الإنجاز موجودة في
    سجل الحركة، وهذا الملف ما يكتب أي شي هناك.

مصدر المعلومات (كله مقيس على السيرفر الحقيقي 11/11/2026):
  • صفحة الأتعاب        : GET  {BASE_URL}/FEES_DONE
  • حفظ الأتعاب         : POST {BASE_URL}/includes/insert_fee.php
  • حقول كل نوع مصروف   : name_<code> · count_<code> · days_<code> · amount_<code>
  • أنواع المصروفات     : 170001..170009 + 1700010  (10 أنواع)
  • ردود الحفظ          : 1=تم الحفظ · 2=خطأ بيانات · 3=تم تعديل الأتعاب السابقة
                          4=لا يوجد جلسة حجز (لازم الحجز أول)
"""

import re

import requests

from config import BASE_URL

# ---------------------------------------------------------------------------
# ثابتات النظام
# ---------------------------------------------------------------------------

FEES_PAGE = '/FEES_DONE'
FEES_SAVE = '/includes/insert_fee.php'

#: أكواد أنواع المصروفات كما يقراها السيرفر (includes/insert_fee.php سطر 59-62)
FEE_CODES = ('170001', '170002', '170003', '170004', '170005',
             '170006', '170007', '170008', '170009', '1700010')

#: أسماء المصروفات كما تظهر في دليل الوزارة (دليل المستخدم 2021 صفحة 26).
#: ترتيبها يطابق ترتيب الأكواد. لو الصفحة زوّدتنا بالأسماء الحقيقية من
#: السيرفر (fetch_fee_form) بنستخدمها بدالها.
FEE_NAMES = {
    '170001': 'عمل داخل الادارة',
    '170002': 'عمل بمحل الشرايع وجهات العلاج',
    '170003': 'عمل لمكتبه التقرير',
    '170004': 'اعمال خبرة خارجية',
    '170005': 'اعمال الخبره المستحق بها',
    '170006': 'اعمال خبرة سابقه',
    '170007': 'مصروفات نقل',
    '170008': 'اعمال سببيه امنيه الالغاء',
    '170009': 'ايجار الغرف',
    '1700010': 'مصروفات اخري',
}

#: ردود حفظ الأتعاب (نفس رسائل SweetAlert في الموقع)
SAVE_RESULTS = {
    '1': 'تم حفظ الاتعاب بنجاح',
    '2': 'يوجد خطاء فى ادخال البيانات يرجى مراجعه البيانات',
    '3': 'تم تعديل الاتعاب السابقه بنجاح',
    '4': 'لا يوجد جلسه حجز للقضيه يجب ادخال الحجز اولا',
}


def fee_types():
    """قائمة أنواع المصروفات بالترتيب: [{'code','name'}, ...]"""
    return [{'code': c, 'name': FEE_NAMES.get(c, c)} for c in FEE_CODES]


# ---------------------------------------------------------------------------
# قراءة نموذج الأتعاب من السيرفر
# ---------------------------------------------------------------------------

def _clean(x):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', x)).replace('&nbsp;', ' ').strip()


def parse_fee_form(html):
    """يحلل HTML صفحة الأتعاب ويرجع صفوف المصروفات.

    يرجع قائمة [{'code','name','days','count','amount'}] أو [] إذا ما كان
    بالصفحة جدول (مثلاً الجلسة بدون قضية محدّدة).
    """
    rows = []
    for code in FEE_CODES:
        def val(prefix):
            m = re.search(
                r'(?is)<input\b[^>]*\bname\s*=\s*["\']%s_%s["\'][^>]*\bvalue\s*=\s*["\']([^"\']*)' % (prefix, code),
                html)
            if m:
                return m.group(1).strip()
            m = re.search(
                r'(?is)<input\b[^>]*\bvalue\s*=\s*["\']([^"\']*)["\'][^>]*\bname\s*=\s*["\']%s_%s["\']' % (prefix, code),
                html)
            return m.group(1).strip() if m else ''
        rows.append({
            'code': code,
            'name': val('name') or FEE_NAMES.get(code, code),
            'days': val('days'),
            'count': val('count'),
            'amount': val('amount'),
        })
    # إذا ما فيها أي input بالم الصفحة ⇒ ما فيه جدول
    has_table = bool(re.search(r'(?is)name\s*=\s*["\']name_170001["\']', html))
    return rows if has_table else []


def fetch_fee_form(cookies, caso_no=None):
    """يجيب نموذج الأتعاب من السيرفر.

    يعيد قاموس:
        {'rows': [...], 'live': bool, 'total': float}
    live=True يعني السيرفر رجّع الجدول فعلاً (نعتمد الأسماء الحقيقية).
    live=False يعني استعملنا الأسماء الافتراضية (نفس دليل الوزارة).
    """
    if caso_no:
        # نختار القضية بالجلسة أولاً (نفس آلية زر «تفاصيل» في الموقع)
        try:
            requests.post('%s/Exp_new_cases.php' % BASE_URL, data={'task_id': caso_no},
                          cookies=cookies, verify=False)
        except Exception:
            pass
    try:
        r = requests.get(BASE_URL + FEES_PAGE, cookies=cookies, verify=False)
        html = r.text or ''
    except Exception:
        html = ''
    rows = parse_fee_form(html)
    live = bool(rows)
    if not live:
        rows = [{'code': c, 'name': FEE_NAMES.get(c, c), 'days': '', 'count': '', 'amount': ''}
                for c in FEE_CODES]
    return {'rows': rows, 'live': live, 'total': fees_total(rows)}


# ---------------------------------------------------------------------------
# الحسابات
# ---------------------------------------------------------------------------

def _num(v):
    if v is None:
        return 0.0
    s = str(v).strip().replace(',', '')
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def fees_total(rows):
    """مجموع مبالغ الأتعاب."""
    return sum(_num(r.get('amount')) for r in rows or [])


def normalize_rows(rows):
    """يرجّع صفوفاً نظيفة (نص لكل الحقول) بنفس ترتيب الأكواد."""
    by_code = {}
    for r in rows or []:
        c = str(r.get('code') or '').strip()
        if c:
            by_code[c] = r
    out = []
    for c in FEE_CODES:
        r = by_code.get(c, {})
        out.append({
            'code': c,
            'name': (r.get('name') or FEE_NAMES.get(c, c)).strip(),
            'days': str(r.get('days') or '').strip(),
            'count': str(r.get('count') or '').strip(),
            'amount': str(r.get('amount') or '').strip(),
        })
    return out


def build_fee_payload(caso_no, rows):
    """يبني الـ payload بالضبط مثل جافاسكربت الموقع (insert_fee_F).

    الحقول:
        <code>        = <code>        ← عنصر FEE_TYPE (علم النوع)
        name_<code>   = اسم المصروف
        count_<code>  = عدد الخبراء
        days_<code>   = عدد الأيام
        amount_<code> = المبلغ
        ECS_IN_REGNO  = رقم الخبرة
    """
    payload = {'ECS_IN_REGNO': str(caso_no or '').strip()}
    for r in normalize_rows(rows):
        c = r['code']
        payload[c] = c
        payload['name_' + c] = r['name']
        payload['count_' + c] = r['count']
        payload['days_' + c] = r['days']
        payload['amount_' + c] = r['amount']
    return payload


# ---------------------------------------------------------------------------
# الحفظ
# ---------------------------------------------------------------------------

def save_fees(cookies, caso_no, rows, dry_run=True):
    """يحفظ أتعاب القضية.

    dry_run=True (الافتراضي): يبني الـ payload ويرجعه **بدون أي إرسال**.
    dry_run=False: يرسل للنظام فعلياً.

    يرجع قاموس:
        {'ok': bool, 'code': str, 'message': str, 'payload': dict, 'total': float}
    """
    clean = normalize_rows(rows)
    payload = build_fee_payload(caso_no, clean)
    total = fees_total(clean)
    if dry_run:
        return {'ok': False, 'code': 'dry_run', 'message': 'معاينة فقط — ما تم الإرسال',
                'payload': payload, 'total': total}
    if not payload['ECS_IN_REGNO']:
        return {'ok': False, 'code': 'x', 'message': 'رقم الخبرة مطلوب',
                'payload': payload, 'total': total}
    try:
        r = requests.post(BASE_URL + FEES_SAVE, data=payload, cookies=cookies, verify=False)
        code = (r.text or '').strip()
    except Exception as e:
        return {'ok': False, 'code': 'err', 'message': 'تعذر الاتصال بالنظام: %s' % e,
                'payload': payload, 'total': total}
    # السيرفر يرد بالرقم (وربما Notices قبله) — ناخذ آخر رقم في الرد
    m = re.findall(r'\b([1234])\b', (r.text or '').strip())
    code = m[-1] if m else (r.text or '').strip()[:40]
    return {'ok': code == '1' or code == '3', 'code': code,
            'message': SAVE_RESULTS.get(code, 'رد غير معروف من النظام'),
            'payload': payload, 'total': total}


# ---------------------------------------------------------------------------
# الطباعة — «رسوم الخبرة»
# ---------------------------------------------------------------------------

def fees_docx(path, caso_no, rows, case_info=None, expert_name='', header_line2='الإدارة العامة للخبراء'):
    """يولّد ملف Word لرسوم الخبرة.

    case_info: قاموس اختياري فيه مفاتيح مثل
        {'case_no': رقم القضية, 'auto_no': الرقم الالى, 'type': نوع القضية,
         'party': الطرف, 'referral_date': تاريخ الاحالة}
    يرجع مسار الملف.
    """
    import base64
    import os

    import report_builder as rb

    clean = normalize_rows(rows)
    info = case_info or {}
    total = fees_total(clean)

    # صور الترويسة (شعار الوزارة + الشعار) — نفس ملفات تقرير الخبرة
    assets = os.path.join(getattr(os.sys, '_MEIPASS', None) or
                          os.path.dirname(os.path.abspath(__file__)), 'report_assets')
    try:
        with open(os.path.join(assets, 'emblem.jpg'), 'rb') as f:
            emblem = base64.b64encode(f.read())
        with open(os.path.join(assets, 'badge.jpg'), 'rb') as f:
            badge = base64.b64encode(f.read())
        rb.load_images(emblem, badge)
    except Exception:
        pass  # بدون صور: التقرير يطلع بدون ترويسة صور (ما يطيّح)

    rep = rb.Report(header_line2=header_line2)
    rep.title('رسوم الخبرة')
    rep.text('رسوم الخبرة الخاصة بالقضية رقم الخبرة: %s' % caso_no, jc='center', b=True)

    hdr = ['المصروف', 'المبلغ', 'عدد الأيام', 'عدد الخبراء']
    body = []
    for r in clean:
        if not (r['amount'] or r['days'] or r['count']):
            continue
        body.append([r['name'], r['amount'] or '0', r['days'] or '-', r['count'] or '-'])
    body.append(['الإجمالي', ('%g' % total), '', ''])
    rep.data_table(hdr, body, [3900, 1900, 1900, 2036], bold_rows=(len(body) - 1,))

    facts = []
    if info.get('case_no'):
        facts.append('رقم القضية: %s' % info['case_no'])
    if info.get('auto_no'):
        facts.append('الرقم الالى: %s' % info['auto_no'])
    if info.get('type'):
        facts.append('نوع القضية: %s' % info['type'])
    if info.get('party'):
        facts.append('الطرف: %s' % info['party'])
    if info.get('referral_date'):
        facts.append('تاريخ الاحالة: %s' % info['referral_date'])
    if facts:
        rep.text(' • '.join(facts), jc='center')

    if expert_name:
        rep.text('الخبير: %s' % expert_name, jc='right')
    rep.blank()
    rep.signature([('الخبير', expert_name)] if expert_name else [])
    return rep.save(path)
