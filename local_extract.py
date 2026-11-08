# ===== local_extract.py — استخراج بيانات حكم الإحالة بلا ذكاء ولا إنترنت =====
"""احتياط فقط: يُستخدم حين لا يوجد أي مزود ذكاء أو فشل الاتصال، وفي شاشة فيها مراجعة قبل الحفظ (إضافة قضية).
يرجع نفس مفاتيح EXTRACTION_PROMPT + "_local": True + "_warning" (نص التنبيه للخبير).

القواعد مبنية على صيغة أحكام الإحالة الكويتية: "بالجلسة المنعقدة … يوم/بتاريخ"، "في القضية رقم"، "المرفوعة من"،
"ضد"، "حكمت المحكمة …"، "… لحضور الخصوم". الأرقام الهندية من OCR الداخلي غير موثوقة (11 من 38 صحيحة)، فالتنبيه يذكرها.
"""
import re

_DATE = re.compile(r'(\d{1,4})\s*[/\-]\s*(\d{1,2})\s*[/\-]\s*(\d{1,4})')


def _clean(s):
    s = re.sub(r'\[؟\]', '', s or '')
    s = re.sub(r'^[\s:/\-–.|]+|[\s:/\-–.|]+$', '', s)
    return ' '.join(s.split())


def _dates(s):
    """التواريخ الصالحة في النص بصيغة DD/MM/YYYY بترتيب ظهورها."""
    out = []
    for m in _DATE.finditer(s or ''):
        a, b, c = m.groups()
        if len(a) == 4:
            y, mo, d = int(a), int(b), int(c)
        elif len(c) == 4:
            d, mo, y = int(a), int(b), int(c)
        else:
            continue
        if 1 <= d <= 31 and 1 <= mo <= 12 and 2000 <= y <= 2100:
            out.append(f'{d:02d}/{mo:02d}/{y}')
    return out


def _after(lines, pattern):
    """(رقم السطر، ما بعد العبارة) لأول سطر يطابق."""
    rx = re.compile(pattern)
    for i, ln in enumerate(lines):
        m = rx.search(ln)
        if m:
            return i, _clean(ln[m.end():])
    return -1, ''


def _split_parties(s):
    parts = re.split(r'\s+(?:و\s*)?(?:\d+\s*[-–)]\s*)|\s*،\s*(?=\d)|\s+\d+\s*[-–]\s*', ' ' + s)
    # ترقيم أو بقايا ختم في أول الاسم ("1 : شركة …")
    parts = [re.sub(r'^(?:\d+\s*[:.\-–)]?\s*)+', '', _clean(x)) for x in parts]
    return [p for p in (_clean(x) for x in parts) if len(p) >= 3]


def extract(text, indic_digits=True):
    """text: نص الحكم (أرقام إنجليزية، "--- صفحة N ---" بين الصفحات)."""
    lines = [ln.strip() for ln in re.sub(r'--- صفحة \d+ ---', '', text or '').splitlines() if ln.strip()]
    flat = ' '.join(lines)
    data = {'رقم_القضية': '', 'المدعون': [], 'المدعى_عليهم': [], 'تاريخ_الحكم': '',
            'تاريخ_حضور_الخصوم': '', 'المأمورية': ''}

    # تاريخ الحكم: أول تاريخ في سطر "الجلسة المنعقدة"
    for ln in lines:
        if re.search(r'المنعقدة|بالجلسة', ln):
            d = _dates(ln)
            if d:
                data['تاريخ_الحكم'] = d[0]
                break

    # رقم القضية: بعد "في القضية/الدعوى رقم" (أو "الاستئناف/الاستئنافين … برقم")
    _i, rest = _after(lines, r'(?:القضي\w*|الدعو\w*|الاستئناف\w*|الطعن)\s+(?:\S+\s+)?(?:رق\w*|برق\w*)\s*[:/]?')
    data['رقم_القضية'] = rest[:80]

    # المدعون: "المرفوعة من" (OCR يشوّهها أحياناً: "المرفةمـن")
    i, rest = _after(lines, r'المرف\w*\s*(?:مـ*ن)?\s*[:/]?')
    if rest:
        data['المدعون'] = _split_parties(re.sub(r'^مـ*ن\s*[:/]?\s*', '', rest)) or [rest]
    # المدعى عليهم: "ضد" (في سطرها أو السطر التالي للمدعين)
    j, rest = _after(lines, r'^(?:ضـ*د|ض\s*ـ+\s*د)\s*[:/]?|\sضد\s')
    if not rest and i >= 0 and i + 1 < len(lines):
        rest = _clean(re.sub(r'^(?:ض|د|ضد)\s', '', lines[i + 1]))
    if rest:
        data['المدعى_عليهم'] = _split_parties(rest) or [rest]

    # تاريخ حضور الخصوم: أقرب تاريخ لعبارة "لحضور الخصوم"
    m = re.search(r'لحضور\s+(?:ال)?خصوم', flat)
    if m:
        before = _dates(flat[max(0, m.start() - 60):m.start()])
        after = _dates(flat[m.end():m.end() + 60])
        data['تاريخ_حضور_الخصوم'] = (before[-1] if before else after[0] if after else '')

    # المأمورية: من "حكمت المحكمة" إلى أول صلاحية عامة/أمانة
    m = re.search(r'حكمت\s+المحكمة', flat)
    if m:
        body = flat[m.end():]
        end = re.search(r'وصرحت|وقررت|وأبقت|وابقت|وحددت|وكلفت|وأمرت', body)
        data['المأمورية'] = _clean(body[:end.start()] if end else body[:700])[:900]

    data['_local'] = True
    data['_warning'] = ('⚠ استُخرجت البيانات على الجهاز بلا ذكاء اصطناعي (لا يوجد اتصال أو مزود) — '
                        + ('الأرقام والتواريخ بالحكم هندية وقراءتها المحلية غير موثوقة: ' if indic_digits else '')
                        + 'راجع كل الحقول مع الحكم قبل الحفظ')
    return data
