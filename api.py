# ===== api.py — التواصل مع نظام الخبراء =====
import requests
import json
import urllib3
import re
import threading
import time
from datetime import datetime
from config import BASE_URL, DAYS_AR, GOVERNORATES, SESSION_TYPES, IGNORED_SESSION_COLORS

urllib3.disable_warnings()


def get_day_name(date_str):
    """يرجع اسم اليوم بالعربي"""
    try:
        d = datetime.strptime(date_str[:10].replace('/', '-'), '%Y-%m-%d')
        return DAYS_AR[d.weekday()]
    except:
        return ""


def short_name(full_name):
    """الاسم الأول والأخير فقط"""
    parts = [p for p in full_name.strip().split() if p]
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1]}"
    return full_name.strip()


def build_case_number(raw_num, case_type):
    """يبني رقم الدعوى: 628/2025/إداري/"""
    try:
        raw = str(raw_num).strip()
        if len(raw) >= 6:
            year = "20" + raw[:2]
            number = str(int(raw[2:]))
            ct = case_type.strip() if case_type else ""
            return f"{number}/{year}/{ct}/"
        return raw
    except:
        return str(raw_num)


def get_logged_in_name(cookies):
    """يسحب اسم المستخدم الحالي من الهيدر"""
    try:
        r = requests.get(f"{BASE_URL}/MyCalendar", cookies=cookies, verify=False)
        names = re.findall(r'username-hide-on-mobile[^>]*>\s*([^<]+?)\s*<', r.text)
        if names:
            return short_name(names[-1].strip())
    except:
        pass
    return ""


def fetch_user_profile_raw(cookies):
    """
    يجلب صفحة /user_profile الخام (نفس آلية جلب أي صفحة أخرى بالنظام —
    كوكيز الجلسة الحالية). ما تُستخدم هذي الدالة مباشرة عادة — استخدم
    get_expert_profile_fields() اللي تحاول تستخرج الحقول المعروفة منها.
    ترجع نص HTML الخام، أو نص فاضي لو فشل الطلب أو رجّع صفحة تسجيل دخول
    (يعني الكوكيز منتهية/غير صالحة لهذا المسار).
    """
    try:
        r = requests.get(f"{BASE_URL}/user_profile", cookies=cookies, verify=False)
        if 'login.php' in (r.url or '') or 'شاشة الدخول' in r.text:
            return ""
        return r.text or ""
    except Exception:
        return ""


# تأكدنا فعليًا (بفحص صفحة /user_profile الحقيقية — "بيانات الخبير" ←
# "تغيير عنوان الخبير") من أسماء الحقول الدقيقة بالنموذج:
#   EXP_BULD    = المبنى (select — القيمة بنص الـoption المحدد "selected")
#   EXP_FLOOR   = الدور (select — نفس الشي)
#   EXP_SECTION = الجناح (select — نفس الشي، مثلاً "D")
#   EXP_ROOM    = الغرفه/المكتب (input رقمي عادي، القيمة بـvalue="...")
# لا يوجد أي حقل "الشق التخصصي" بهذي الصفحة إطلاقًا — يبقى إدخال يدوي.
_PROFILE_SELECT_FIELDS = {
    'EXP_BULD': 'maqar',
    'EXP_FLOOR': 'dor',
    'EXP_SECTION': 'janah',
}


def _strip_html(html):
    text = re.sub(r'<script.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '\n', text)
    text = re.sub(r'&nbsp;?', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    lines = [ln.strip() for ln in text.split('\n')]
    return [ln for ln in lines if ln]


def get_expert_profile_fields(cookies):
    """
    يستخرج (maqar, dor, maktab, janah) من صفحة /user_profile فعليًا —
    القيم مبنية على فحص حقيقي لهيكل الصفحة (مو تخمين). لا يوجد حقل
    specialty بهذي الصفحة إطلاقًا، فيبقى يُدخَل يدويًا كما كان.

    ترجع (dict_بالحقول_المكتشفة, raw_lines) — راجع أعلى الملف لتوضيح
    أسماء الحقول بالنموذج الأصلي.
    """
    html = fetch_user_profile_raw(cookies)
    if not html:
        return {}, []

    found = {}

    for select_name, key in _PROFILE_SELECT_FIELDS.items():
        m = re.search(rf'<select[^>]*name="{select_name}"[^>]*>(.*?)</select>', html, re.DOTALL)
        if not m:
            continue
        body = m.group(1)
        sel = re.search(r'<option\b[^>]*\bselected\b[^>]*>([^<]*)</option>', body)
        if sel:
            text = sel.group(1).strip()
            if text:
                found[key] = text

    room_match = re.search(r'<input[^>]*name="EXP_ROOM"[^>]*\bvalue=["\']?(\d+)', html)
    if room_match:
        found['maktab'] = room_match.group(1)

    return found, _strip_html(html)[:60]


def get_sessions(cookies, start, end):
    """يسحب الجلسات من النظام"""
    r = requests.get(
        f"{BASE_URL}/includes/load.php?start={start}&end={end}",
        cookies=cookies, verify=False
    )
    return json.loads(r.text)


# ===== أنواع الجلسات — سجل الحركة هو المرجع، مو اللون =====
#
# ⚠️ ليش مو اللون: نظام الوزارة يعطي «فتح محضر» (150004) و«جلسه محكمه»
# (150011) **نفس اللون بالضبط** `#27659a` — فاللون ما يفرّق بينهم أبداً.
# (مقيس على بيانات حقيقية 25/10/2026: 24 جلسة محكمة + 32 فتح محضر — كلهم
#  نفس اللون.) النتيجة كانت: جلسة المحكمة ما تنحسب ضمن الجلسات الفعلية،
#  فترقام المحاضر تنقص 1، و«الجلسة القادمة» تتخطّى جلسة المحكمة.
#
# المرجع الوحيد الدقيق هو **سجل الحركة** (ECS_CASE_FLOW) لأنه يكتب اسم
# النوع بالحرف مع تاريخ الجلسة ووقتها.

_OPEN_RECORD_LABEL = 'فتح محضر'
_COURT_LABELS = ('جلسه محكمه', 'جلسة محكمة')

_KINDS_CACHE = {}          # (case, بصمة الكوكيز) -> (وقت, خريطة الأنواع)
_KINDS_TTL = 30            # ثانية — يمنع تكرار الطلب لنفس القضية
_kinds_lock = threading.Lock()


def _cookies_fingerprint(cookies):
    """بصمة الكوكيز — عشان الكاش ما ينلخبط بين جلستين مختلفتين."""
    try:
        items = sorted((k, str(v)) for k, v in dict(cookies).items())
    except Exception:
        items = []
    return hash(tuple(items))


def _flow_cells(html):
    """خلايا سجل الحركة (نص نظيف، بدون ووم)."""
    out = []
    for raw in re.findall(r'<td[^>]*>(.*?)</td>', html, re.DOTALL):
        t = re.sub(r'<[^>]+>', '', raw).replace('&nbsp', ' ').strip()
        if t:
            out.append(t)
    return out


def _kinds_from_cells(cells):
    """يستخرج {(التاريخ, الوقت): النوع} من خلايا سجل الحركة."""
    kinds = {}
    for i, cell in enumerate(cells):
        if cell != _OPEN_RECORD_LABEL and cell not in _COURT_LABELS:
            continue
        if i + 2 >= len(cells):
            continue
        d, t = cells[i + 1].strip(), cells[i + 2].strip()
        m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', d)
        if not m or not re.match(r'^\d{2}:\d{2}$', t):
            continue
        dd, mm, yyyy = m.groups()
        kind = 'open_record' if cell == _OPEN_RECORD_LABEL else 'court'
        kinds[('%s/%s/%s' % (yyyy, mm, dd), t)] = kind
    return kinds


def _fetch_session_kinds(caso_no, cookies):
    """يرجّع {(التاريخ 'YYYY/MM/DD', الوقت 'HH:MM'): النوع} من سجل الحركة."""
    try:
        r = requests.post(f"{BASE_URL}/ECS_CASE_FLOW",
            data={'P_CASES': caso_no}, cookies=cookies, verify=False)
    except Exception:
        return {}
    return _kinds_from_cells(_flow_cells(r.text))


def _store_session_kinds(caso_no, cookies, kinds):
    """يحفظ الخريطة بالكاش."""
    key = (caso_no, _cookies_fingerprint(cookies))
    with _kinds_lock:
        _KINDS_CACHE[key] = (time.time(), kinds)


def get_case_session_kinds(caso_no, cookies, max_age=None):
    """
    أنواع جلسات القضية من سجل الحركة:
        'open_record' → «فتح محضر» (لا تُحسب ضمن الجلسات الفعلية)
        'court'       → «جلسه محكمه» (تُحسب — جلسة حقيقية)
    الجلسات الأخرى (مناقشة، معاينة، حجز...) ما ترجع من سجل الحركة — بسجل
    الحركة ما يسجّل إلا جلسات الخبير الخاصة.

    الكاش 30 ثانية عشان ما نضرب السيرفر بكل استدعاء.
    """
    if not caso_no:
        return {}
    ttl = _KINDS_TTL if max_age is None else max_age
    key = (caso_no, _cookies_fingerprint(cookies))
    now = time.time()
    with _kinds_lock:
        hit = _KINDS_CACHE.get(key)
        if hit and (now - hit[0]) < ttl:
            return hit[1]
    kinds = _fetch_session_kinds(caso_no, cookies)
    _store_session_kinds(caso_no, cookies, kinds)
    return kinds


def invalidate_session_kinds(caso_no=None):
    """يمسح كاش الأنواع — يُستدعى بعد إضافة جلسة جديدة (سجل الحركة يتغير)."""
    with _kinds_lock:
        if caso_no:
            for key in [k for k in _KINDS_CACHE if k[0] == caso_no]:
                _KINDS_CACHE.pop(key, None)
        else:
            _KINDS_CACHE.clear()


def _stamp_session_kinds(sessions, caso_no, cookies):
    """يختم كل جلسة بنوعها ('open_record' / 'court') — من سجل الحركة."""
    if not sessions:
        return
    kinds = get_case_session_kinds(caso_no, cookies)
    if not kinds:
        return
    for s in sessions:
        start = s.get('start') or ''
        s['_kind'] = kinds.get((start[:10], start[11:16]), '')


def get_all_case_sessions(cookies, caso_no):
    """يسحب كل جلسات قضية معينة"""
    all_s = get_sessions(cookies, "2010-01-01", "2035-01-01")
    sessions = [s for s in all_s if s.get('description') == caso_no]
    _stamp_session_kinds(sessions, caso_no, cookies)
    return sessions


def session_exists(cookies, caso_no, date_raw, time_str):
    """
    يتحقق هل فيه جلسة مسجّلة فعلاً بنظام الخبراء بنفس تاريخ ووقت
    القضية المحدَّدين — خط دفاع إضافي قبل أي استدعاء لـinsert_session
    عشان ما تنضاف جلسة مكررة لو الجلسة مضافة أصلاً (حتى لو upcoming/
    open_record ما التقطاها بالفحص الأول لأي سبب، مثل إعادة فتح/طباعة
    محضر أول جلسة لقضية سبق وأُضيفت لها الجلسة).

    date_raw بصيغة 'YYYY/MM/DD'، time_str بصيغة 'HH:MM'. يرجع False
    بصمت لو تعذر الاتصال — أفضل نحاول الإضافة العادية بدل ما نوقف
    الطباعة على فحص إضافي فشل.
    """
    try:
        for s in get_all_case_sessions(cookies, caso_no):
            start = s.get('start', '')
            if start[:10] == date_raw and start[11:16] == time_str:
                return True
        return False
    except Exception:
        return False


def _is_open_record_session(s):
    """يتعرف على جلسة فتح محضر — اللون أثبت طريقة، النص والكود احتياطيان
    (نفس منطق first_session.py، هنا موحّد للاستخدام بمحضر عادي)

    ⚠️ استثناء واحد فوق اللون: لو سجل الحركة says الجلسة «جلسه محكمه»
    فهي **جلسة حقيقية تُحسب** — لأن نظام الوزارة يعطي «فتح محضر» و«جلسه
    محكمه» نفس اللون (#27659a)، فاللون لحاله ما يفرّق بينهم. النوع
    المؤختم على الجلسة (_kind) جاي من سجل الحركة وهو المرجع.
    """
    # ← السطر الإضافي: جلسة المحكمة تُحسب (اللون لحالة ما يفرّق)
    if (s.get('_kind') or '') == 'court':
        return False
    OPEN_RECORD_CODE = SESSION_TYPES.get('فتح محضر', '150004')
    color = (s.get('backgroundColor') or '').strip().lower()
    if color in {c.lower() for c in IGNORED_SESSION_COLORS}:
        return True
    title = (s.get('title', '') or '').strip()
    sid = str(s.get('id', ''))
    return 'فتح محضر' in title or OPEN_RECORD_CODE in sid


def compute_session_number(cookies, caso_no, date):
    """
    يحسب رقم المحضر العادي (مو أول جلسة) لتاريخ معيّن.

    القاعدة: مباشرة الدعوى تُحسب دايماً كجلسة أولى ضمنية (الـ +1 بالأسفل).
    لو فيه جلسة 'فتح محضر' بسجل القضية، فهي تمثّل نفس حدث المباشرة
    (خبير حط جلسة فتح محضر يدوياً بدل ما يفهم إنها تلقائية) — لذا تُستبعد
    من العدّ عشان ما تُحسب جلسة إضافية فوق المباشرة الضمنية. باقي أنواع
    الجلسات (مناقشة، معاينة، ...) تُحسب عادي.
    """
    all_s = get_all_case_sessions(cookies, caso_no)
    real_sessions = [s for s in all_s if not _is_open_record_session(s)]
    return len([s for s in real_sessions if s.get('start', '')[:10] <= date]) + 1


def parse_case_info(caso_no, cookies, current_user=""):
    """يسحب بيانات القضية كاملة"""
    result = {
        'plaintiffs': [], 'defendants': [],
        'case_num': '', 'source': '',
        'case_type': '', 'expert_name': current_user,
        'governorate': '', 'department': '',
    }
    try:
        # الأطراف
        r2 = requests.post(
            f"{BASE_URL}/includes/basic_info_result.php",
            data={'id': '1', 'title': caso_no, 'met_date': '', 'met_time': '', 'description': caso_no},
            cookies=cookies, verify=False
        )
        h4s = re.findall(r'<h4[^>]*>(.*?)</h4>', r2.text, re.DOTALL)
        h4s = [re.sub(r'<[^>]+>', '', h).strip() for h in h4s]
        for h in h4s:
            if 'المدعى   :' in h or 'المدعى:' in h:
                name = h.split(':', 1)[-1].strip()
                if name: result['plaintiffs'].append(name)
            elif 'المدعى عليه' in h:
                name = h.split(':', 1)[-1].strip()
                if name: result['defendants'].append(name)

        # تفاصيل القضية
        r3 = requests.post(
            f"{BASE_URL}/ECS_CASE_FLOW",
            data={'P_CASES': caso_no}, cookies=cookies, verify=False
        )
        html = r3.text

        # أنواع جلسات القضية من نفس الرد (سجل الحركة) — **بدون طلب إضافي**:
        # 'open_record' = فتح محضر (لا يُحسب)، 'court' = جلسة محكمة (تُحسب).
        # اللون بالنظام ما يفرّق بينهم (#27659a للاثنين) — هذا هو المرجع.
        _kinds = _kinds_from_cells(_flow_cells(html))
        result['session_kinds'] = _kinds
        _store_session_kinds(caso_no, cookies, _kinds)

        # الحقول
        fields = re.findall(
            r'<label[^>]*>\s*(.*?)\s*</label>.*?[Vv]alue=["\'\s]*([^"\'>\s][^"\'>\n]*?)["\'\s]*>',
            html, re.DOTALL
        )
        for label, value in fields:
            label = label.strip()
            value = value.strip()
            if 'رقم القضيه' in label or 'رقم القضية' in label:
                result['case_num'] = value
            elif ('الجهه' in label or 'الجهة' in label) and not re.match(r'\d+/\d+/\d+', value):
                result['source'] = value
            elif label == 'النوع':
                result['case_type'] = value

        # بناء رقم الدعوى
        if result['case_num']:
            result['case_num'] = build_case_number(result['case_num'], result['case_type'])

        # من سجل الحركة
        tds = re.findall(r'<td[^>]*>(.*?)</td>', html, re.DOTALL)
        tds = [re.sub(r'<[^>]+>', '', t).strip() for t in tds]
        tds = [t for t in tds if t and t != '&nbsp' and len(t) > 1]

        # الأطراف لو ما طلعوا
        if not result['plaintiffs'] or not result['defendants']:
            for i, td in enumerate(tds):
                if td == 'مدعى' and i > 0:
                    result['plaintiffs'].append(tds[i - 1])
                elif td == 'مدعي عليه' and i > 0:
                    result['defendants'].append(tds[i - 1])

        # القسم والمحافظة
        for i, td in enumerate(tds):
            if ('توزيع للخبراء' in td or 'مباشرة القضية' in td) and i + 1 < len(tds):
                dept = tds[i + 1]
                if 'قسم' in dept:
                    result['department'] = dept
                    for key, val in GOVERNORATES.items():
                        if key in dept:
                            result['governorate'] = val
                            break

    except Exception:
        pass

    return result


def get_requesting_expert(cookies, caso_no):
    """
    يحدد اسم ونوع الخبير (أو اللجنة) الذي قدّم طلب الاستعانة.

    المنطق النهائي (مبني على بيانات حقيقية):
      - نلقى آخر كتلة 'توزيع استعانة بخبير على الخبراء' فقط.
      - نتخطى الاسم الأول فيها (المحوِّل/رئيس القسم الذي أسند القضية).
      - نأخذ الأسماء الباقية (الخبراء الفعليون المستعان بهم).
      - النوع (هندسي/حسابي) من أقرب مراقبة سابقة لطلب الاستعانة.
    """
    result = {'name': '', 'type': ''}
    try:
        r = requests.post(f"{BASE_URL}/ECS_CASE_FLOW",
            data={'P_CASES': caso_no}, cookies=cookies, verify=False)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', r.text, re.DOTALL)
        tds = [re.sub(r'<[^>]+>', '', t).strip() for t in tds]
        tds = [t for t in tds if t and t != '&nbsp']

        skip = ['قسم', 'مراقبه', 'مراقبة', 'إدارة', 'مكتب', 'لا يوجد']
        DIST_LABELS = ('توزيع استعانه بخبير على الخبراء',
                       'توزيع استعانة بخبير على الخبراء')
        REQUEST_LABELS = ('طلب استعانة بخبير', 'طلب استعانه بخبير')

        # نوع الخبير من أقرب مراقبة قبل آخر طلب استعانة
        request_idx = None
        for i, td in enumerate(tds):
            if td.strip() in REQUEST_LABELS:
                request_idx = i
        if request_idx is not None:
            for k in range(request_idx - 1, -1, -1):
                if 'حسابيه' in tds[k] or 'حسابية' in tds[k]:
                    result['type'] = 'الحسابي'; break
                if 'هندسيه' in tds[k] or 'هندسية' in tds[k]:
                    result['type'] = 'الهندسي'; break

        # آخر كتلة توزيع استعانة على الخبراء
        last_dist_idx = None
        for i, td in enumerate(tds):
            if td.strip() in DIST_LABELS:
                last_dist_idx = i

        if last_dist_idx is None:
            # احتياطي: اسم أول بعد طلب الاستعانة
            if request_idx is not None:
                for j in range(request_idx + 1, min(request_idx + 4, len(tds))):
                    c = tds[j].strip()
                    if c and not any(x in c for x in skip) and not c[0:1].isdigit() and len(c) > 5:
                        result['name'] = short_name(c); break
            return result

        # نجمع الأسماء من آخر كتلة فقط (حتى رقم إجراء)
        all_names = []
        for j in range(last_dist_idx + 1, min(last_dist_idx + 14, len(tds))):
            c = tds[j].strip()
            if c[0:1].isdigit() and len(c) > 6:
                break  # رقم إجراء = نهاية الكتلة
            if c and len(c) > 5 and not any(x in c for x in skip) and not c[0:1].isdigit():
                sn = short_name(c)
                if sn not in all_names:
                    all_names.append(sn)

        # تخطي الاسم الأول (المحوِّل) — الخبراء الفعليون من الثاني فصاعداً
        experts = all_names[1:] if len(all_names) > 1 else all_names
        if experts:
            result['name'] = '  ،  '.join(experts)

    except Exception:
        pass

    return result


_LEADING_GENERIC = {
    'شركة', 'الشركة', 'شركه', 'الشركه',
    'مؤسسة', 'المؤسسة', 'مؤسسه', 'المؤسسه',
    'وكيل', 'وكيلة', 'وزارة', 'الوزارة', 'وزاره', 'الوزاره',
}
_STOP_WORDS = {'بصفته', 'بصفتها', 'بصفتهم', 'بصفتهما'}


def _shorten_party_name(full_name, max_words=4):
    """
    يختصر اسم طرف (مدعي/مدعى عليه) لجوهره: يحذف الكلمات العامة
    بالبداية (شركة/وكيل/وزارة)، ويتوقف عند أول وصف عام بحرف 'ل' يجي
    بعد أول كلمة محددة فعلاً (مثل 'لمشاريع'، 'للتكنولوجيا')، أو عند
    كلمة 'بصفته' وما شابه. مثال: 'الشركة الوطنية لمشاريع التكنولوجيا'
    → 'الوطنية'، 'وكيل وزارة التربية بصفته' → 'التربية'.
    """
    words = [w.strip('،.()[]/') for w in (full_name or '').strip().split() if w.strip('،.()[]/')]
    result = []
    for w in words:
        if not result and w in _LEADING_GENERIC:
            continue
        if w in _STOP_WORDS:
            break
        if result and w.startswith('ل') and len(w) > 2:
            break
        result.append(w)
        if len(result) >= max_words:
            break
    return ' '.join(result) if result else (full_name or '').strip()


def insert_session(cookies, caso_no, date, time, type_code):
    """
    يضيف جلسة جديدة فعليًا بنظام الخبراء (نفس آلية '➕ إضافة جلسة
    قادمة'). يرجع كود النتيجة الخام: '1'=نجح، '2'=خطأ، '3'=تعارض،
    '4'=حجز، '5'=إجازة، '6'=أقل من 7 أيام.
    """
    r = requests.post(
        f"{BASE_URL}/includes/insert.php",
        data={
            'ECS_IN_REGNO': caso_no,
            'EMET_MEET_DTE': date,
            'EMET_MEET_TIME': time,
            'EMET_TYPE': type_code,
        },
        cookies=cookies, verify=False,
    )
    # الجلسة الجديدة تدخل سجل الحركة — نسخّ كاش الأنواع عشان الفحص الجديد
    # يشوفها فوراً (وإلا انحسبت «فتح محضر» لأن اللون مو مميّز).
    invalidate_session_kinds(caso_no)
    return r.text.strip()


def get_case_parties_summary(caso_no, cookies, current_user=''):
    """
    يرجع ملخص أطراف القضية مختصر بصيغة 'مدعي ضد مدعى عليه' (كل طرف
    مختصر لجوهره فقط — انظر _shorten_party_name) — يُستخدم بعنوان
    موعد التقويم عشان يكون واضح بنظرة واحدة بالآيفون.

    يفضّل القاعدة المحلية (case_db، مستخرجة بالذكاء الاصطناعي من حكم
    الإحالة، أدق) لو متوفرة، وإلا يرجع لكشط الموقع (parse_case_info)
    كاحتياط. يرجع رقم الخبرة نفسه لو تعذر إيجاد أي طرف بأي مصدر.
    """
    plaintiffs, defendants = [], []
    try:
        import case_db
        cached = case_db.get_case(caso_no)
        if cached:
            plaintiffs = cached.get('plaintiffs') or []
            defendants = cached.get('defendants') or []
    except Exception:
        pass

    if not plaintiffs and not defendants:
        try:
            info = parse_case_info(caso_no, cookies, current_user)
            plaintiffs = info.get('plaintiffs', [])
            defendants = info.get('defendants', [])
        except Exception:
            pass

    p = _shorten_party_name(plaintiffs[0]) if plaintiffs else ''
    d = _shorten_party_name(defendants[0]) if defendants else ''

    if p and d:
        return f"{p} ضد {d}"
    return p or d or caso_no


def get_original_experts(cookies, caso_no):
    """
    يستخرج الخبير/اللجنة الأصلية صاحبة القضية (اللي استعانت بنا) —
    وهم من ظهروا في أول 'توزيع للخبراء' بسجل الحركة (قبل أي استعانة).
    يرجع dict: {'names': [...], 'label': 'السيد الخبير'|'السادة الخبراء'}
    """
    result = {'names': [], 'label': ''}
    try:
        r = requests.post(f"{BASE_URL}/ECS_CASE_FLOW",
            data={'P_CASES': caso_no}, cookies=cookies, verify=False)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', r.text, re.DOTALL)
        tds = [re.sub(r'<[^>]+>', '', t).strip() for t in tds]
        tds = [t for t in tds if t and t != '&nbsp']
        skip = ['قسم', 'مراقبه', 'مراقبة', 'إدارة', 'مكتب', 'لا يوجد']

        # نلقى أول 'توزيع للخبراء' (الأصلي، قبل أي استعانة)
        first_dist_idx = None
        for i, td in enumerate(tds):
            if td.strip() == 'توزيع للخبراء':
                first_dist_idx = i
                break  # أول ظهور فقط

        if first_dist_idx is None:
            return result

        # نجمع كل الأسماء من هذي الكتلة
        names = []
        for j in range(first_dist_idx + 1, min(first_dist_idx + 14, len(tds))):
            c = tds[j].strip()
            if c[0:1].isdigit() and len(c) > 6:
                break
            if c and len(c) > 5 and not any(x in c for x in skip) and not c[0:1].isdigit():
                sn = short_name(c)
                if sn not in names:
                    names.append(sn)

        if not names:
            return result

        # نتخطى الاسم الأول بالكتلة (رئيس القسم/المحوِّل اللي وزّع
        # القضية) — نفس المنطق المستخدم بالضبط بـget_requesting_expert
        # (سطر 336) وبـget_experts في ui.py. كان مفقوداً هنا، فكان اسم
        # رئيس القسم يظهر بالخطأ كـ"الخبير الأصلي" بمحضر أول جلسة
        # للاستعانة.
        names = names[1:] if len(names) > 1 else names
        if not names:
            return result

        result['names'] = names
        result['label'] = 'السادة الخبراء' if len(names) > 1 else 'السيد الخبير'
    except Exception:
        pass
    return result