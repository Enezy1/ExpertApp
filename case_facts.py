# ===== case_facts.py — نموذج الحقائق المنظَّم (schema صارم) للتقرير المركَّب بالكود (2026-10-20) =====
# الهدف: تقرير صحيح مهما كان النموذج ضعيفاً. الحقائق تأتي من مصدرين ويتحقق منهما الكود قبل أي استعمال:
#   (1) قارئ الكود للجداول والصفحات المنظَّمة (كشوف الفواتير، كشف الخطوط، صفحات الفواتير، نماذج طلب الخدمة، كشوف الأجهزة)؛
#       كل حقيقة منه مقتبسة من سطرها حرفياً.
#   (2) استخراج النموذج (جيميناي) بـJSON صارم؛ كل عنصر يُقبل فقط إن ورد اقتباسه حرفياً في مستنده وورد كل رقم/تاريخ فيه
#       في الاقتباس أو صفحته؛ وإلا يُحذف بملاحظة حمراء «حُذف لعدم التحقق».
# قواعد ثابتة: الخط أو رقم الطلب/الاشتراك ليس عقداً (يصير طلب خدمة تحت عقده)؛ إجماليات المدعية (statement_totals) لا تُعامل
# كفواتير أبداً ولا تدخل في أي جمع؛ الغرامة داخل فاتورة مكوّن منها (components) لا بند مستقل.
# الأطراف من بيانات القضية (الصفة، الاسم، الجنس النحوي: مذكر/مؤنث/جهة اعتبارية) بدليل نصي لا بتخمين من الاسم.
# الناتج: data['facts3'] + 03_حقائق/الحقائق.json. المحاور (mission_axes) يبنيها report_playbooks.
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation

import calc

SCHEMA = 3
REL = '_نظام/03_حقائق/الحقائق.json'
G_M, G_F, G_E = 'مذكر', 'مؤنث', 'جهة اعتبارية'
SRC_CODE, SRC_MODEL = 'code', 'model'
_DIG = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_AMT = re.compile(r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?')
MAX_PROMPT_CHARS = 400_000


def _now():
    return datetime.now().isoformat(timespec='seconds')


# ---------- أدوات النص والأرقام والتواريخ ----------

def norm_text(t):
    """للمطابقة الحرفية: أرقام لاتينية، بلا رموز markdown والتطويل والتشكيل، همزات/تاء/ياء موحّدة، مسافات مفردة."""
    t = str(t or '').translate(_DIG)
    t = re.sub(r'[*|#`>_]+', ' ', t)
    t = re.sub(r'[ً-ْـ]', '', t)
    t = t.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي')
    return ' '.join(t.split())


def contains(hay, needle):
    n = norm_text(needle)
    return bool(n) and n in norm_text(hay)


def dec(x):
    """Decimal من نص/عدد أو None (الفواصل والأرقام الهندية مقبولة)."""
    if x is None or x == '':
        return None
    if isinstance(x, Decimal):
        return x
    try:
        return calc.D(x)
    except (calc.CalcError, InvalidOperation, ValueError, TypeError):
        return None


def money(d):
    """المبلغ بثلاث خانات عشرية ثابتة وفواصل الآلاف: 59.400 / 1,155.770."""
    return calc.fmt(Decimal(d), money=True)


_MONTH_NO = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10,
           'nov': 11, 'dec': 12}
_MON = r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?'
_DMONY = re.compile(rf'(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s\-/]*{_MON}[\s\-/,]*(\d{{4}}|\d{{2}})(?!\d)', re.I)
_MONDY = re.compile(rf'(?<![a-z]){_MON}\s*(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(\d{{4}})(?!\d)', re.I)


def _month_date(s):
    """(يوم، شهر، سنة) من صيغ فواتير الشركات الإنجليزية: «01 Sep 23»، «30-Aug-2023»، «Sep 30, 2023»؛ وإلا None.
    السنة بخانتين = 20yy (الفواتير الحديثة)."""
    m = _DMONY.search(s)
    if m:
        d, mo, y = int(m.group(1)), _MONTH_NO[m.group(2).lower()[:3]], m.group(3)
    else:
        m = _MONDY.search(s)
        if not m:
            return None
        mo, d, y = _MONTH_NO[m.group(1).lower()[:3]], int(m.group(2)), m.group(3)
    y = int(y) + (2000 if len(y) == 2 else 0)
    return (d, mo, y) if 1 <= d <= 31 and 1990 <= y <= 2100 else None


def parse_date(s):
    """(يوم، شهر، سنة) من dd/mm/yyyy أو yyyy-mm-dd أو yyyy/mm/dd أو d/m/yyyy أو «01 Sep 23»؛ وإلا None."""
    s = str(s or '').translate(_DIG)
    m = re.search(r'(\d{1,4})\s*[/\-.\\]\s*(\d{1,2})\s*[/\-.\\]\s*(\d{1,4})', s)
    if not m:
        return _month_date(s)
    a, b, c = m.groups()
    if len(a) == 4:
        y, mo, d = int(a), int(b), int(c)
    elif len(c) == 4:
        d, mo, y = int(a), int(b), int(c)
    else:
        return None
    if not (1 <= mo <= 12 and 1 <= d <= 31 and 1990 <= y <= 2100):
        return None
    return d, mo, y


def fmt_date(s):
    p = parse_date(s) if not isinstance(s, tuple) else s
    return f'{p[0]:02d}/{p[1]:02d}/{p[2]}' if p else ''


def date_key(s):
    p = parse_date(s)
    return (p[2], p[1], p[0]) if p else (9999, 0, 0)


def date_in(text, s):
    """التاريخ s وارد في text بأي صيغة (يوم/شهر/سنة أو سنة-شهر-يوم، بأصفار أو بدونها)."""
    p = parse_date(s)
    if not p:
        return False
    d, mo, y = p
    t = str(text or '').translate(_DIG)
    sep = r'\s*[/\-.\\]\s*'
    pats = [rf'(?<!\d)0*{d}{sep}0*{mo}{sep}{y}(?!\d)', rf'(?<!\d){y}{sep}0*{mo}{sep}0*{d}(?!\d)']
    if any(re.search(p_, t) for p_ in pats):
        return True
    return any(_month_date(m.group(0)) == p for rx in (_DMONY, _MONDY) for m in rx.finditer(t))


def amount_in(text, value):
    v = dec(value)
    if v is None:
        return False
    want = calc.norm_num(abs(v))
    return want in {calc.norm_num(abs(Decimal(x))) for x in calc.numbers_in(text)}


def digits_in(text, number):
    """رقم مستند/خط/فاتورة وارد كما هو (مع أصفار بادئة مسموحة)."""
    n = re.sub(r'\D', '', str(number or '').translate(_DIG)).lstrip('0')
    if len(n) < 3:
        return False
    return bool(re.search(rf'(?<!\d)0*{n}(?!\d)', str(text or '').translate(_DIG)))


def clean_number(x):
    return re.sub(r'\D', '', str(x or '').translate(_DIG)).lstrip('0')


def _sha(obj):
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


# ---------- المستندات (المدونة) بمراجع الخبير ----------

_DOCNO = re.compile(r'^\s*#*\s*\(?\s*مستند\s*\)?\s*(?:رقم\s*)?\(?\s*(\d{1,3})\s*\)?\s*$', re.M)


def doc_numbers(pages):
    """{رقم الصفحة: رقم المستند داخل الحافظة} من عناوين «مستند (N)» (الصفحة ترث آخر عنوان قبلها)."""
    out, cur = {}, None
    for n, t in pages:
        m = list(_DOCNO.finditer(str(t).translate(_DIG)))
        if m:
            cur = int(m[-1].group(1))
        out[n] = cur
    return out


def face_side(text):
    """مقدّم الحافظة/المذكرة من وجهها: «من: … صفتها: مدعية» أو «مقدمة من … المدعية»."""
    t = norm_text(str(text or '')[:3000])
    m = re.search(r'صفت(?:ها|ه)\s*:?\s*(مدعي(?:ه)?\s*علي(?:ها|ه)|مدعي(?:ه)?)', t)
    if m:
        v = m.group(1).replace(' ', '')
        return 'المدعى عليه' if 'علي' in v else 'المدعية'
    i = t.find('مقدمه من')
    if i >= 0:                                   # أول صفة بعد «مقدمة من» (وجه المذكرة قد يأتي مبعثر الأسطر من OCR)
        seg = t[i:i + 400]
        hits = [(seg.find(k), v) for k, v in (('المدعيه', 'المدعية'), ('المدعي عليها', 'المدعى عليها'),
                                              ('المدعي عليه', 'المدعى عليه')) if seg.find(k) >= 0]
        if hits:
            return min(hits)[1]
    return ''


def corpus(base, data):
    """[{code, file, kind, side, date, memo, pages, docno}] لكل مستند محوَّل (حافظة/مذكرة/صحيفة/حكم).
    المقدّم من وجه المستند يتقدم على ما سجّله البرنامج للحافظة (قد يكون «الخبير» خطأً)، والتاريخ dd/mm/yyyy."""
    import research_pipeline as rp
    out = []
    for d in rp.documents(base, data):
        pages = tidy_pages(d['pages'])
        text = '\n'.join(t for _n, t in pages)
        side = face_side(text) or d.get('side') or ''
        if side == 'الخبير':
            side = ''
        out.append({'code': d['code'], 'file': d['file'], 'kind': d['kind'], 'side': side,
                    'date': fmt_date(d.get('date')) or d.get('date') or '', 'memo': d['memo'], 'multi': d.get('multi'),
                    'pages': pages, 'docno': doc_numbers(pages), 'merged': merged_ranges(text)})
    return out


_MERGED = re.compile(r'<!--\s*صفحات\s*(\d+)\s*[–\-]\s*(\d+)\s*مدموجة\s*-->')


def tidy_pages(pages):
    """الصفحات بأرقام فريدة: ما سبق أول علامة صفحة (تعليقات رأس الملف) أو تكرّر رقمه يُضم إلى صفحته —
    وإلا قرأ المدقّق صفحة «1» الفارغة (سطر التعليق) بدل نص الدفعة المدموجة فحذف كل الحقائق."""
    out = []
    for n, t in pages:
        if out and out[-1][0] == n:
            out[-1] = (n, out[-1][1].rstrip() + '\n' + (t or ''))
        else:
            out.append((n, t or ''))
    return out


def merged_ranges(text):
    """[(من، إلى)] دفعات صفحات دمجها التحويل (عدد صفحات الرد لا يطابق الملف) — أرقام صفحاتها غير موثوقة."""
    return [(int(a), int(b)) for a, b in _MERGED.findall(text or '')]


def apply_reread(docs, reread):
    """يضيف نص الصفحات المعاد قراءتها من PDF (reread: [{doc, page, text}]) إلى صفحاتها برقمها الأصلي، فيتحقق المدقّق
    من الاقتباس في أي من القراءتين. نص markdown القديم يبقى (لا يُحذف شيء)."""
    by = {}
    for r in reread or []:
        try:
            n = int(r.get('page'))
        except (TypeError, ValueError):
            continue
        if r.get('doc') and str(r.get('text') or '').strip():
            by.setdefault(r['doc'], {})[n] = str(r['text'])
    if not by:
        return docs
    out = []
    for d in docs:
        new = by.get(d['code'])
        if not new:
            out.append(d)
            continue
        old = dict(d['pages'])
        pages = [(n, (new[n] + '\n\n' + old[n]) if n in new and n in old else new.get(n, old.get(n, '')))
                 for n in sorted(set(old) | set(new))]
        out.append(dict(d, pages=pages, docno=doc_numbers(pages), reread=sorted(new)))
    return out


def cite(doc, page=None, docno=None):
    """المرجع بصيغة الخبير: «(مرفق بحافظة مستندات المدعية المؤرخة 18/10/2026 مستند 2)» — لا رقم صفحة أبداً،
    ولا مرجع للصحيفة/حكم الإحالة (لا يُستشهد بهما). docno: رقم المستند المتحقَّق للحقيقة (يتقدّم على خريطة الصفحات)."""
    if doc is None or doc['kind'] in ('صحيفة الدعوى', 'حكم الإحالة'):
        return ''
    side = doc.get('side') or ''
    date = doc.get('date') or ''
    if doc['memo']:
        return f"(مذكرة دفاع {side} المؤرخة {date})".replace('  ', ' ') if date else f"(مذكرة دفاع {side})".replace(' )', ')')
    in_merged = page is not None and any(a <= page <= b for a, b in doc.get('merged') or [])
    no = docno or ((doc.get('docno') or {}).get(page) if page is not None and not in_merged else None)
    s = 'مرفق بحافظة مستندات' + (f' {side}' if side else '') + (f' المؤرخة {date}' if date else '')
    return f"({s}{f' مستند {no}' if no else ''})"


def _doc(docs, code):
    return next((d for d in docs if d['code'] == code), None)


def find_in_doc(doc, quote, page=None):
    """رقم الصفحة التي ورد فيها الاقتباس حرفياً (بالتطبيع) أو None. الاقتباس ≥ 3 كلمات أو رقم ≥ 5 خانات."""
    q = norm_text(quote)
    if not q or (len(q.split()) < 3 and not re.search(r'\d{5,}', q)):
        return None
    order = sorted(doc['pages'], key=lambda pt: pt[0] != page)
    for n, t in order:
        if q in norm_text(t):
            return n
    return None


def page_text(doc, n):
    return '\n'.join(t for k, t in doc['pages'] if k == n)


# ---------- الأطراف والجنس النحوي ----------

def _count(pattern, texts):
    return sum(len(re.findall(pattern, norm_text(t))) for t in texts)


def gender_of(role, name, texts, company):
    """(الجنس، الدليل). الشركة/الجهة ← جهة اعتبارية؛ الفرد ← بعدّ «المدعى عليه/عليها» (أو «المدعي/المدعية») في المستندات."""
    if company:
        return G_E, 'اسم شركة/جهة'
    if role == 'plaintiff':
        f = _count(r'(?<!\S)المدعيه(?!\S)', texts)
        m = _count(r'(?<!\S)المدعي(?!\S)(?!\s+علي)', texts)
    else:
        f = _count(r'المدعي\s+عليها(?!\S)', texts) + _count(r'صفتها\s*:?\s*مدعي\s+عليها', texts)
        m = _count(r'المدعي\s+عليه(?!\S)', texts) + _count(r'المعلن\s+اليه(?!\S)', texts)
    if f > m:
        return G_F, f'ورد بالمؤنث {f} مرة مقابل {m}'
    if m > f:
        return G_M, f'ورد بالمذكر {m} مرة مقابل {f}'
    return G_M, 'لم يتضح من المستندات — الافتراضي المذكر (راجعه)'


_ORD_M = ('الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس')
_ORD_F = ('الأولى', 'الثانية', 'الثالثة', 'الرابعة', 'الخامسة', 'السادسة')


def parties(data, texts):
    """[{role, n, name, gender, evidence, label}] من بيانات القضية (الحضور في الإجراءات ثم بيانات القضية)."""
    import case_procedures as cp
    att = ((data.get('procedures') or {}).get('attendance') or {})
    rows = [(r['role'], r['name']) for r in att.get('result') or [] if r.get('name')]
    if not rows:
        import case_sort as cs
        rows += [('plaintiff', n) for n in cs.party_names(data, 'plaintiff')]
        rows += [('defendant', n) for n in cs.party_names(data, 'defendant')]
    out = []
    by_role = Counter(r for r, _n in rows)
    seen = Counter()
    for role, name in rows:
        role = 'plaintiff' if role == 'plaintiff' else 'defendant'
        seen[role] += 1
        comp = cp._is_company(name)
        import case_sort as cs
        known = cs.party_gender(data, role, seen[role])        # الجنس من بيانات الأطراف (الصحيفة) يتقدّم على العدّ
        if known and not comp:
            g, ev = (G_F if known == 'f' else G_M), 'صفته في صحيفة الدعوى'
        else:
            g, ev = gender_of(role, name, texts, comp)
        certain = comp or bool(known) or 'لم يتضح' not in ev
        fem = g in (G_F, G_E)
        if role == 'plaintiff':
            label = 'المدعية' if fem else 'المدعي'
        else:
            label = 'المدعى عليها' if fem else 'المدعى عليه'
        if by_role[role] > 1:
            label += ' ' + ((_ORD_F if fem else _ORD_M)[seen[role] - 1] if seen[role] <= 6 else str(seen[role]))
        out.append({'role': role, 'n': seen[role], 'name': ' '.join(str(name).split()), 'gender': g,
                    'evidence': ev, 'label': label, 'company': comp, 'certain': certain})
    return out


# ---------- قارئ الكود للجداول والصفحات المنظَّمة ----------

def _cells(line):
    s = line.strip()
    if not s.startswith('|'):
        return None
    parts = [c.strip().strip('*').strip() for c in s.strip('|').split('|')]
    return parts


def tables(text):
    """[(سطر ما قبل الجدول، [رؤوس]، [[خلايا], …], [نص السطر الخام…])] من جداول markdown."""
    out, lines = [], str(text or '').splitlines()
    i = 0
    while i < len(lines):
        c = _cells(lines[i])
        if c is None:
            i += 1
            continue
        prev = ''
        for j in range(i - 1, max(-1, i - 6), -1):
            if lines[j].strip():
                prev = lines[j].strip()
                break
        head, rows, raws = c, [], []
        i += 1
        while i < len(lines) and _cells(lines[i]) is not None:
            c2 = _cells(lines[i])
            if not all(re.fullmatch(r':?-{2,}:?', x) or not x for x in c2):
                rows.append(c2)
                raws.append(lines[i].strip())
            i += 1
        filled = [x for x in head if x]
        if rows and len(filled) == 1 and re.fullmatch(r'\d{7,9}', clean_number(filled[0]) or ''):
            prev, head, rows, raws = filled[0], rows[0], rows[1:], raws[1:]     # رقم الخط سطر رأس فوق الرؤوس
        out.append((prev, head, rows, raws))
    return out


def _col(head, *keys):
    for k in keys:
        for i, h in enumerate(head):
            if k in norm_text(h):
                return i
    return None


def _cell(row, i):
    return row[i] if i is not None and i < len(row) else ''


def _num_cell(s):
    m = _AMT.search(str(s or '').translate(_DIG).replace(' ', ''))
    return dec(m.group(0)) if m else None


def _line_before(prev):
    m = re.fullmatch(r'\D{0,20}(\d{7,9})\D{0,5}', str(prev or '').translate(_DIG).replace('*', '').strip())
    return m.group(1) if m else ''


_INV_NO = re.compile(r'رقم\s*الفاتور[ةه]\s*[:：|]?\s*0*(\d{6,})')
_PENALTY = re.compile(r'(Commitment\s+Penalty|غرام[ةه]\s+(?:ال)?التزام|غرام[ةه]\s+(?:انهاء|إنهاء|فسخ)|غرام[ةه])', re.I)
_CONTRACT_NO = re.compile(r'رقم\s*العقد\s*[:：]?[\s|*:]*?(\d{5,})')
_LINE_NO = re.compile(r'رقم\s*(?:الخط|الاشتراك)\s*[:：]?[\s|*:]*?(\d{7,9})(?!\d)')


def scan(docs):
    """حقائق قارئ الكود (لا نموذج): {'invoices','payments','statement_totals','service_orders','contracts'}.
    كل عنصر: src='code' + doc/page + quote (السطر حرفياً)."""
    inv, pays, tots, devices, lines_meta = {}, [], [], {}, {}
    contract_votes, line_set = Counter(), set()
    contract_pages = {}
    for d in docs:
        if d['memo'] or d['kind'] in ('صحيفة الدعوى', 'حكم الإحالة'):
            continue
        for n, t in d['pages']:
            for prev, head, rows, raws in tables(t):
                h = norm_text(' '.join(head))
                ci_no, ci_amt = _col(head, 'رقم الفاتوره'), _col(head, 'مبلغ الفاتوره')
                if ci_no is not None and ci_amt is not None:        # كشف مفردات فواتير خط
                    ci_line, ci_date = _col(head, 'رقم الخط'), _col(head, 'تاريخ الفاتوره', 'التاريخ')
                    ci_paid, ci_rem = _col(head, 'المدفوع', 'المسدد'), _col(head, 'المتبقي')
                    tline = _line_before(prev)
                    for row, raw in zip(rows, raws):
                        no = clean_number(_cell(row, ci_no))
                        line = clean_number(_cell(row, ci_line)) or tline
                        amt, paid, rem = (_num_cell(_cell(row, ci_amt)), _num_cell(_cell(row, ci_paid)),
                                          _num_cell(_cell(row, ci_rem)))
                        if len(no) >= 5 and amt is not None:
                            line_set.add(line)
                            rec = inv.setdefault(no, {'number': no, 'line': line, 'date': fmt_date(_cell(row, ci_date)),
                                                      'amount': amt, 'components': [], 'quote': raw, 'doc': d['code'],
                                                      'page': n, 'src': SRC_CODE})
                            if rem is not None:
                                rec['stated_remaining'] = rem
                            if paid:
                                pays.append({'amount': paid, 'invoice': no, 'line': line, 'date': '', 'note': '',
                                             'quote': raw, 'doc': d['code'], 'page': n, 'src': SRC_CODE})
                        elif not no and amt is not None:              # سطر الإجمالي: إجمالي المدعية لا فاتورة
                            tots.append({'scope': 'line', 'line': line, 'amount': rem if rem is not None else amt,
                                         'invoices_total': amt, 'paid_total': paid, 'label': 'إجمالي كشف مفردات الخط',
                                         'quote': raw, 'doc': d['code'], 'page': n, 'src': SRC_CODE})
                    continue
                if 'اجمالي المبلغ لكل خط' in h or ('رقم الخط' in h and 'حاله الخط' in h):   # كشف إجماليات الخطوط
                    for row, raw in zip(rows, raws):
                        nums = [clean_number(x) for x in row if re.fullmatch(r'\d{7,9}', clean_number(x) or '')]
                        amt = next((_num_cell(x) for x in reversed(row) if re.search(r'\d\.\d{3}', x)), None)
                        if nums and amt is not None:
                            status = next((x for x in row if re.search(r'disconnect|مفصول|active|فعال', x, re.I)), '')
                            lines_meta.setdefault(nums[0], {})['status'] = status
                            line_set.add(nums[0])
                            tots.append({'scope': 'line', 'line': nums[0], 'amount': amt, 'label': 'كشف الإجماليات',
                                         'quote': raw, 'doc': d['code'], 'page': n, 'src': SRC_CODE})
                    continue
                if 'نوع الجهاز' in h and 'مده الالتزام' in h:               # كشف الأجهزة المسحوبة على خط
                    line = _line_before(prev)
                    ci_dev, ci_val = _col(head, 'نوع الجهاز'), _col(head, 'قيمه الالتزام')
                    ci_mon, ci_start = _col(head, 'مده الالتزام'), _col(head, 'تاريخ بدء')
                    best = None
                    for row, raw in zip(rows, raws):
                        name = _cell(row, ci_dev)
                        if not name:
                            continue
                        val, mon = _num_cell(_cell(row, ci_val)), _num_cell(_cell(row, ci_mon))
                        val, mon = _fix_device_cols(row, val, mon)
                        aux = bool(re.search(r'warranty|service|ضمان|تأمين', name, re.I))
                        cand = (not aux, val or 0, name, val, mon, fmt_date(_cell(row, ci_start)), raw)
                        if best is None or cand[:2] > best[:2]:
                            best = cand
                    if line and best:
                        devices[line] = {'device': best[2], 'device_value': best[3], 'commitment_months':
                                         int(best[4]) if best[4] is not None else None, 'date': best[5],
                                         'quote': best[6], 'doc': d['code'], 'page': n}
            nt = str(t).translate(_DIG)
            for m in _CONTRACT_NO.finditer(nt):
                contract_votes[m.group(1)] += 1
                contract_pages.setdefault(m.group(1), (d['code'], n, m.group(0)))
            for m in _LINE_NO.finditer(nt):
                line_set.add(m.group(1))
            mt = re.search(r'اجمالي\s+المبلغ\s*:?\s*(\d[\d,]*\.\d{3})', norm_text(t))
            if mt and dec(mt.group(1)):
                tots.append({'scope': 'all', 'line': '', 'amount': dec(mt.group(1)), 'label': 'إجمالي كشف المدعية',
                             'quote': mt.group(0), 'doc': d['code'], 'page': n, 'src': SRC_CODE})
    _scan_invoice_pages(docs, inv, pays)
    contracts = []
    for num, votes in contract_votes.most_common():
        if num in line_set or num in inv:
            continue
        code, n, q = contract_pages[num]
        contracts.append({'number': num, 'date': '', 'kind': 'عقد اشتراك', 'scope': '', 'value': None, 'duration': '',
                          'payment': '', 'quote': q, 'doc': code, 'page': n, 'src': SRC_CODE, 'votes': votes})
    orders = []
    for line in sorted(l for l in line_set if l):
        so = {'line': line, 'contract': contracts[0]['number'] if len(contracts) == 1 else '', 'device': '',
              'device_value': None, 'commitment_months': None, 'monthly': None, 'date': '', 'status': '',
              'src': SRC_CODE}
        so.update({k: v for k, v in (devices.get(line) or {}).items() if v not in (None, '')})
        so['status'] = (lines_meta.get(line) or {}).get('status', '')
        orders.append(so)
    _scan_service_dates(docs, orders, contracts)
    seen_pay, uniq = set(), []              # الجدول نفسه قد يتكرر في الحافظة (أو يُقرأ معكوس الأعمدة) ← الدفعة مرة واحدة
    for p in pays:
        k = (p.get('invoice') or '', calc.norm_num(p.get('amount')) if p.get('amount') is not None else None,
             p.get('line') or '')
        if p.get('invoice') and k in seen_pay:
            continue
        seen_pay.add(k)
        uniq.append(p)
    pays = uniq
    return {'invoices': list(inv.values()), 'payments': pays, 'statement_totals': _dedupe_totals(tots),
            'service_orders': orders, 'contracts': contracts}


_MONTHS = (6, 12, 18, 24, 30, 36, 48, 60)


def _fix_device_cols(row, val, mon):
    """جدول الأجهزة قد يُقرأ برؤوس معكوسة الترتيب (480 | 36 | 32 تحت «المتبقي من المدة | المدة | القيمة»): مدة الالتزام
    عدد أشهر معتاد (12/24/36…)، وقيمة الجهاز لا تقل عن «المتبقي من قيمة الجهاز» (آخر خانة). غير المعقول يُصحَّح من الصف."""
    nums = [n for n in (_num_cell(x) for x in row if re.fullmatch(r'\s*[\d.,]+\s*', str(x or '')))
            if n is not None and n < 100000]     # خانات رقمية فقط: لا اسم جهاز ولا سيريال ولا رقم خط
    rest = nums[-1] if nums else None
    if mon is None or int(mon) not in _MONTHS:
        mon = next((n for n in nums if n == int(n) and int(n) in _MONTHS), mon)
    if val is not None and rest is not None and val < rest:
        bigger = [n for n in nums[:-1] if n >= rest]
        if bigger:
            val = max(bigger)
    return val, mon


def _dedupe_totals(tots):
    out, seen = [], set()
    for t in tots:
        k = (t['scope'], t.get('line') or '', calc.norm_num(t['amount']) if t.get('amount') is not None else '')
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def _scan_invoice_pages(docs, inv, pays):
    """صفحة الفاتورة (رقم الفاتورة …): الغرامة المتضمنة (Commitment Penalty) مكوّناً منها، وتاريخ الدفعة المقدّمة."""
    for d in docs:
        if d['memo']:
            continue
        pages = d['pages']
        for i, (n, t) in enumerate(pages):
            nt = str(t).translate(_DIG)
            m = _INV_NO.search(nt)
            if not m or m.group(1).lstrip('0') not in inv:
                continue
            no = m.group(1).lstrip('0')
            seg = nt
            if i + 1 < len(pages) and not _INV_NO.search(str(pages[i + 1][1]).translate(_DIG)):
                seg += '\n' + str(pages[i + 1][1]).translate(_DIG)         # تتمة الفاتورة في الصفحة التالية
            rec = inv[no]
            for ln in seg.splitlines():
                pm = _PENALTY.search(ln)
                if not pm:
                    continue
                am = re.findall(r'\d[\d,]*\.\d{3}', ln)
                if not am:
                    continue
                amt = dec(am[-1])
                if amt and amt <= rec['amount'] and not any(c['amount'] == amt for c in rec['components']):
                    rec['components'].append({'kind': 'غرامة التزام', 'amount': amt, 'quote': ln.strip(),
                                              'doc': d['code'], 'page': n, 'src': SRC_CODE})
            for p in pays:
                if p['invoice'] != no or p.get('date'):
                    continue
                pm = re.search(r'المدفوعات\s+حتى\s+تاريخ\s*(\d{1,2}/\d{1,2}/\d{4})[^\n]*?(\d[\d,]*\.\d{3})', seg)
                if pm and dec(pm.group(2)) == p['amount']:
                    p['date'] = fmt_date(pm.group(1))
                if re.search(r'المدفوعه\s+مقدما.{0,12}?' + re.escape(money(p['amount'])), norm_text(seg)):
                    p['note'] = 'مقدماً'


def _scan_service_dates(docs, orders, contracts):
    """تاريخ كل طلب خدمة وتاريخ العقد من «عقد خدمات»/«نموذج طلب الخدمة» (الصفحة التي تحمل رقم الخط)."""
    by_line = {o['line']: o for o in orders}
    dates = []
    for d in docs:
        if d['memo']:
            continue
        for n, t in d['pages']:
            nt = norm_text(t)
            if not ('طلب الخدمه' in nt or 'عقد خدمات' in nt or 'service contract' in nt.lower()):
                continue
            lines = [l for l in by_line if l in nt]
            m = (re.search(r'التاريخ\s*/?\s*(?:الوقت)?\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})', nt)
                 or re.search(r'تاريخ\s+بدايه\s+الخدمه\s*:?\s*(\d{4}/\d{1,2}/\d{1,2})', nt))
            if not m or len(lines) != 1:
                continue
            o = by_line[lines[0]]
            if not o.get('date'):
                o['date'] = fmt_date(m.group(1))
                o['date_quote'] = m.group(0)
                o.setdefault('doc', d['code'])
                o.setdefault('page', n)
            if 'post-paid' in t.lower() and '☑' in t or 'دفع اجل' in nt:
                o['payment'] = 'دفع آجل'
            dates.append((date_key(m.group(1)), fmt_date(m.group(1)), d['code'], n))
    if len(contracts) == 1 and dates and not contracts[0].get('date'):
        _k, dt, code, n = min(dates)
        contracts[0].update(date=dt, date_doc=code, date_page=n)
    for o in orders:
        if o.get('payment') and len(contracts) == 1 and not contracts[0].get('payment'):
            contracts[0]['payment'] = 'دفع آجل شهري'


# ---------- استخراج النموذج والتحقق منه ----------

EXTRACT_KEYS = ('contracts', 'service_orders', 'invoices', 'payments', 'statement_totals', 'defenses')


def extract_prompt(docs, plist, case_type=''):
    """طلب JSON صارم: كل عنصر باقتباس حرفي قصير من مستنده ورمزه وصفحته. لا حساب ولا استنتاج."""
    who = '؛ '.join(f"{p['label']}: {p['name']}" for p in plist)
    parts = [
        "أنت مستخرج حقائق لتقرير خبرة قضائي. اقرأ المستندات أدناه وأخرج JSON فقط بالمفاتيح المحددة، دون أي شرح.",
        "قواعد ملزمة:",
        "1) كل عنصر يحمل quote: اقتباساً حرفياً قصيراً (5–25 كلمة أو سطر الجدول كما هو) من المستند نفسه، و doc: رمز "
        "المستند (D1…) و page: رقم الصفحة. ما لا تجد له اقتباساً حرفياً لا تكتبه.",
        "2) انسخ الأرقام والتواريخ كما وردت. لا تحسب ولا تجمع ولا تقرّب ولا تستنتج.",
        "3) العقد هو العقد الحقيقي برقمه (رقم العقد/Contract No). رقم الخط/الاشتراك/الهاتف أو رقم الطلب ليس عقداً: "
        "ضعه في service_orders تحت عقده.",
        "4) الإجماليات (إجمالي الفاتورة التراكمي، إجمالي الكشف، إجمالي المبلغ لكل خط، إجمالي المطالبة) ليست فواتير: "
        "ضعها في statement_totals فقط.",
        "5) الغرامة الواردة داخل فاتورة (Commitment Penalty/Disconnection Penalty/Subsidy Termination/غرامة التزام/رسوم "
        "إلغاء) مكوّن من تلك الفاتورة في components لا فاتورة مستقلة. components للغرامات ورسوم الإلغاء وحدها — لا تضع فيها "
        "بنود الفاتورة العادية (الباقة، قسط الجهاز، الشريحة).",
        "6) defenses: ما ورد في مذكرات الدفاع فقط (by: plaintiff أو defendant، summary جملة قصيرة بلا أرقام).",
        "7) الجداول: اقرأ كل صف بخلاياه في أعمدتها كما هي (لا تنقل رقماً من عمود إلى آخر ولا تدمج صفين). المبلغ السالب "
        "(خصم/دفعة/Credit) يبقى بإشارته. اقتباس العنصر من جدول = سطر الجدول نفسه كما ورد. فواتير الشركات قد تكون "
        "بالإنجليزية: انسخ النص والتواريخ (مثل 01 Sep 23) كما وردت دون ترجمة.",
        "8) service_orders: سطر لكل خط برقمه، وفيه الجهاز وقسطه الشهري (monthly) وقيمته (device_value إن وردت) والباقة "
        "(plan) واشتراكها الشهري (plan_monthly) ومدة الالتزام بالأشهر وتاريخ التفعيل — ما ورد منها فقط.",
        "9) docno: رقم المستند داخل الحافظة حسب فهرس الحافظة (جدول «م / البيان» في صفحتها الأولى) أو عنوان «مستند (N)»؛ "
        "اتركه فارغاً إن لم يتضح. لا تكتب رقم الصفحة بدلاً منه.",
        "10) need_pdf: إن كان نص مستند مهم (العقد، الفواتير، الكشف) مشوّهاً أو ناقصاً أو أرقامه غير مقروءة أو صفحاته "
        "مدموجة بلا ترقيم صحيح، اطلب ملفه الأصلي: {\"doc\":\"D3\",\"pages\":\"12-20\",\"why\":\"سبب قصير\"} — سيُرسل لك "
        "PDF فتعيد استخراجه منه. لا تخمّن رقماً من نص مشوّه.",
        f"الأطراف: {who}",
        "الشكل:",
        '{"contracts":[{"number":"","date":"","kind":"","scope":"وصف قصير لمحل العقد","value":"","duration":"",'
        '"payment":"طريقة السداد","quote":"","doc":"D1","page":1,"docno":""}],'
        '"service_orders":[{"contract":"رقم العقد","line":"رقم الخط","device":"","monthly":"","device_value":"",'
        '"plan":"","plan_monthly":"","commitment_months":"","date":"","quote":"","doc":"","page":1,"docno":""}],'
        '"invoices":[{"number":"","date":"","amount":"","line":"","components":[{"kind":"","amount":"","quote":""}],'
        '"quote":"","doc":"","page":1,"docno":""}],'
        '"payments":[{"amount":"","date":"","invoice":"","line":"","note":"","quote":"","doc":"","page":1,"docno":""}],'
        '"statement_totals":[{"scope":"line|contract|all","line":"","amount":"","label":"","quote":"","doc":"","page":1}],'
        '"defenses":[{"by":"plaintiff|defendant","kind":"","summary":"","quote":"","doc":"","page":1}],'
        '"need_pdf":[]}',
        "## المستندات"]
    budget = MAX_PROMPT_CHARS
    for d in docs:
        head = (f"### {d['code']} — {d['kind']}" + (f" مقدمة من {d['side']}" if d['side'] else '')
                + (f" المؤرخة {d['date']}" if d.get('date') else ''))
        if d.get('merged'):
            head += ' ⚠ ' + '، '.join(f'الصفحات {a}–{b} مدموجة عند التحويل (ترقيمها داخلها غير دقيق)'
                                     for a, b in d['merged'])
        body = '\n'.join(f"<!-- صفحة {n} -->\n{t}" for n, t in d['pages'])
        body = body[:max(2000, budget)]
        budget -= len(body)
        parts.append(head + '\n' + body)
    return '\n\n'.join(parts)


def _parse_json(raw):
    m = re.search(r'\{.*\}', str(raw or ''), re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _locate(docs, item):
    """(doc، page) إن ورد اقتباس العنصر حرفياً في مستنده (أو في أي مستند إن أخطأ الرمز)."""
    q = item.get('quote') or ''
    d = _doc(docs, item.get('doc'))
    pg = item.get('page')
    try:
        pg = int(pg)
    except (TypeError, ValueError):
        pg = None
    for cand in ([d] if d else []) + [x for x in docs if x is not d]:
        n = find_in_doc(cand, q, pg)
        if n is not None:
            return cand, n
    if d is not None and pg is not None:             # اقتباس سطر جدول أعاد النموذج بناءه («عمود | قيمة») أو مختصر بـ«…»
        pg = next((a for a, b in d.get('merged') or [] if a <= pg <= b), pg)     # صفحة داخل دفعة مدموجة ← بدايتها
        for n in (pg, pg - 1, pg + 1):
            if any(k == n for k, _t in d['pages']) and tokens_in(_evidence(d, n, {}), q):
                return d, n
    return None, None


TOKENS_MIN = 5


def tokens_in(text, quote):
    """كل كلمات الاقتباس وأرقامه واردة في النص (≥ 5 كلمات، بلا ترتيب): لسطر جدول أعاد النموذج تركيبه بعناوين أعمدته أو
    اقتباس مختصر بنقاط حذف. يُستعمل في مستند العنصر وصفحته المذكورة (±1) فقط، والأرقام تُفحص بعده كالعادة."""
    words = [w for w in norm_text(re.sub(r'\.{2,}|…', ' ', str(quote or ''))).split() if w not in ('-', ':', '"')]
    words = [w.strip('"()،,:;') for w in words]
    words = [w for w in words if w]
    if len(words) < TOKENS_MIN:
        return False
    have = set(w.strip('"()،,:;') for w in norm_text(text).split())
    return all(w in have for w in words)


AMOUNT_FIELDS = ('amount', 'value', 'monthly', 'plan_monthly', 'device_value')
PENALTY_KIND = re.compile(r'penalt|terminat|disconnect|cancel|غرام|إلغاء|الغاء|فصل|جزاء', re.I)
# حقل ثانوي لم يرد في صفحة الاقتباس (أخذه النموذج من صفحة أخرى، مثل قيمة الجهاز من الفاتورة): يُترك فارغاً ولا يُحذف الخط
# كله برقمه وجهازه وقسطه المتحقَّقة (2026-10-25، A2263970: حُذف الخطان لأن «قيمة الجهاز 308.000» ليست في صفحة العقد).
SECONDARY_FIELDS = {'service_orders': ('date', 'device_value', 'plan_monthly')}
LINK_FIELDS = {'service_orders': ('contract',), 'payments': ('invoice',)}


def _docno(doc, page, given):
    """رقم المستند داخل الحافظة: عنوان «مستند (N)» في الصفحة يتقدّم، وإلا رقم النموذج من فهرس الحافظة (1–99)، وإلا None."""
    own = (doc.get('docno') or {}).get(page)
    if own and not any(a <= page <= b for a, b in doc.get('merged') or []):     # الدفعة المدموجة: آخر عنوان فيها لا يخص
        return own                                                              # كل صفحاتها ← رقم النموذج من الفهرس
    try:
        n = int(str(given).translate(_DIG).strip())
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 99 and not doc.get('memo') else None


def _evidence(doc, page, item):
    """الاقتباس + صفحته + الصفحتان المجاورتان: رقم الفاتورة وتاريخها في رأسها وبنودها في الصفحة التالية (فواتير الشركات)."""
    return '\n'.join([item.get('quote') or '', _prev_page(doc, page), page_text(doc, page), _next_page(doc, page)])


def verify_model(raw, docs):
    """(حقائق متحقَّقة بالشكل نفسه، [سبب كل حذف]). القبول: الاقتباس حرفياً + كل رقم/تاريخ في الاقتباس أو صفحته."""
    obj = _parse_json(raw)
    out = {k: [] for k in EXTRACT_KEYS}
    removed = []
    if obj is None:
        return out, (['ردّ الاستخراج ليس JSON صالحاً'] if raw else [])
    for key in EXTRACT_KEYS:
        for it in obj.get(key) or []:
            if not isinstance(it, dict):
                continue
            doc, page = _locate(docs, it)
            label = f"{key}: {str(it.get('number') or it.get('line') or it.get('amount') or it.get('quote') or '')[:40]}"
            if doc is None:
                removed.append((f'{label} — الاقتباس غير وارد حرفياً', key, it))
                continue
            ev = _evidence(doc, page, it)
            bad = []
            it = dict(it)
            for f in ('number', 'line', 'invoice', 'contract'):
                if it.get(f) and not digits_in(ev, it[f]):
                    if f in LINK_FIELDS.get(key, ()):     # رابط بعنصر آخر (رقم العقد في طلب الخدمة) لا حقيقة: يُترك فارغاً
                        it[f] = ''
                        continue
                    bad.append(f)
            for f in AMOUNT_FIELDS:
                if it.get(f) not in (None, '') and dec(it[f]) is not None and not amount_in(ev, it[f]):
                    if f in SECONDARY_FIELDS.get(key, ()):
                        it[f] = ''
                        continue
                    bad.append(f)
            if it.get('date') and not date_in(ev, it['date']):
                if 'date' in SECONDARY_FIELDS.get(key, ()):
                    it['date'] = ''
                else:
                    bad.append('date')
            if bad:
                removed.append((f"{label} — لم يرد في المستند: {'، '.join(bad)}", key, it))
                continue
            rec = dict(it, doc=doc['code'], page=page, src=SRC_MODEL)
            rec['docno'] = _docno(doc, page, it.get('docno'))
            for f in ('number', 'line', 'invoice', 'contract'):
                if rec.get(f):
                    rec[f] = clean_number(rec[f])
            for f in AMOUNT_FIELDS:
                if f in rec or f in ('amount', 'value', 'monthly'):
                    rec[f] = dec(rec.get(f))
            if rec.get('date'):
                rec['date'] = fmt_date(rec['date']) or rec['date']
            if key == 'invoices':
                comps = []
                for c in it.get('components') or []:
                    a = dec((c or {}).get('amount'))
                    if not PENALTY_KIND.search(str((c or {}).get('kind') or '') + ' ' + str((c or {}).get('quote') or '')):
                        continue                         # بند فاتورة عادي (قسط جهاز، باقة) ليس غرامة: لا يُحسب «منه غرامة»
                    if a is not None and amount_in(page_text(doc, page) + '\n' + _next_page(doc, page), a):
                        comps.append({'kind': c.get('kind') or 'غرامة', 'amount': a, 'quote': c.get('quote') or '',
                                      'doc': doc['code'], 'page': page, 'src': SRC_MODEL})
                    elif a is not None:
                        removed.append((f"مكوّن فاتورة {rec.get('number')}: {a} — غير وارد في صفحتها", 'components', c))
                rec['components'] = comps
                if not rec.get('number') or rec.get('amount') is None:
                    if rec.get('amount') is not None and re.search(r'اجمالي|total', norm_text(rec.get('quote')), re.I):
                        out['statement_totals'].append({'scope': 'line', 'line': rec.get('line') or '',
                                                        'amount': rec['amount'], 'label': 'إجمالي (صُحّح من فاتورة)',
                                                        'quote': rec['quote'], 'doc': rec['doc'], 'page': page,
                                                        'src': SRC_MODEL})
                    else:
                        removed.append((f'{label} — فاتورة بلا رقم أو مبلغ', key, it))
                    continue
            if key == 'defenses' and re.search(r'\d', str(rec.get('summary') or '').translate(_DIG)):
                rec['summary'] = ''
            out[key].append(rec)
    return out, removed


def _next_page(doc, page):
    pages = doc['pages']
    for i, (n, _t) in enumerate(pages):
        if n == page and i + 1 < len(pages):
            return pages[i + 1][1]
    return ''


def _prev_page(doc, page):
    pages = doc['pages']
    for i, (n, _t) in enumerate(pages):
        if n == page and i > 0:
            return pages[i - 1][1]
    return ''


# ---------- الدمج والتطبيع ----------

def merge(code, model, notes):
    """قارئ الكود هو المرجع لما يغطيه؛ ما يضيفه النموذج يدخل بعد التحقق، والتعارض ملاحظة حمراء."""
    f = {k: [dict(x) for x in code.get(k) or []] for k in ('contracts', 'service_orders', 'invoices', 'payments',
                                                         'statement_totals')}
    f['defenses'] = []
    inv = {i['number']: i for i in f['invoices']}
    for i in model.get('invoices') or []:
        cur = inv.get(i['number'])
        if cur is None:
            f['invoices'].append(i)
            inv[i['number']] = i
            continue
        if i.get('amount') is not None and i['amount'] != cur['amount']:
            notes.append(('قرار يحتاج مراجعة الخبير', f"الفاتورة {i['number']}: النموذج قرأ {money(i['amount'])} والجدول "
                          f"{money(cur['amount'])} — اعتُمد الجدول"))
        for c in i.get('components') or []:
            if not any(x['amount'] == c['amount'] for x in cur['components']) and c['amount'] <= cur['amount']:
                cur['components'].append(c)
        for k in ('date', 'line'):
            if not cur.get(k) and i.get(k):
                cur[k] = i[k]
    have_pay = {(p.get('invoice'), clean_number(p.get('line')), calc.norm_num(p['amount'])) for p in f['payments']
                if p.get('amount') is not None}
    for p in model.get('payments') or []:
        if p.get('amount') is None:
            continue
        k = (p.get('invoice'), clean_number(p.get('line')), calc.norm_num(p['amount']))     # المبلغ نفسه لخطين = دفعتان
        if k in have_pay or any(calc.norm_num(x['amount']) == k[2] and x.get('invoice') == p.get('invoice')
                                and (not k[1] or not x.get('line') or clean_number(x.get('line')) == k[1])
                                for x in f['payments']):
            for x in f['payments']:
                if x.get('invoice') == p.get('invoice') and calc.norm_num(x['amount']) == k[2]:
                    x['date'] = x.get('date') or p.get('date') or ''
                    x['note'] = x.get('note') or p.get('note') or ''
            continue
        if f['invoices'] and p.get('invoice') and p['invoice'] in inv and any(
                x.get('invoice') == p['invoice'] for x in f['payments']):
            notes.append(('قرار يحتاج مراجعة الخبير', f"دفعة {money(p['amount'])} على الفاتورة {p['invoice']} من النموذج "
                          "تخالف جدول الكشف — لم تُعتمد"))
            continue
        f['payments'].append(p)
        have_pay.add(k)
    have_tot = {(t['scope'], t.get('line') or '') for t in f['statement_totals']}      # إجماليات الكشف من الجدول مرجع:
    tots = f['statement_totals'] + [t for t in model.get('statement_totals') or [] if t.get('amount') is not None    # لا يُضاف
                                    and (t.get('scope'), clean_number(t.get('line'))) not in have_tot           # «إجمالي»
                                    and not (t.get('scope') == 'line' and any(k[0] == 'line' for k in have_tot))]  # آخر
    f['statement_totals'] = _dedupe_totals(tots)
    f['contracts'] += model.get('contracts') or []
    f['service_orders'] += model.get('service_orders') or []
    f['defenses'] = model.get('defenses') or []
    normalize_contracts(f, notes)
    return f


def normalize_contracts(f, notes):
    """عقد حقيقي فقط: رقم يساوي خطاً/اشتراكاً/فاتورة ← طلب خدمة تحت العقد الحقيقي؛ العقود برقم واحد تُدمج."""
    lines = {o['line'] for o in f['service_orders'] if o.get('line')} | {i.get('line') for i in f['invoices'] if i.get('line')}
    invs = {i['number'] for i in f['invoices']}
    real, demoted = [], []
    for c in f['contracts']:
        num = clean_number(c.get('number'))
        if num and (num in lines or num in invs):           # رقم خط/اشتراك/فاتورة ليس عقداً
            demoted.append(c)
            continue
        real.append(dict(c, number=num))
    merged = []
    for c in real:
        same = next((m for m in merged if (c['number'] and m['number'] == c['number']) or
                     (not c['number'] and not m['number'] and c.get('date') and m.get('date') == c.get('date'))), None)
        if same is None:
            merged.append(c)
            continue
        if c.get('date') and not same.get('date'):      # سجل العقد بتاريخه = صفحة العقد نفسه (لا رأس فاتورة): مرجعه يتقدّم
            for k in ('doc', 'page', 'docno', 'quote'):
                if c.get(k) not in (None, ''):
                    same[k] = c[k]
        for k, v in c.items():
            if v not in (None, '', []) and same.get(k) in (None, '', []):
                same[k] = v
    if not merged and demoted:
        nums = Counter(clean_number(o.get('contract')) for o in f['service_orders'] if o.get('contract'))
        if nums:
            merged.append({'number': nums.most_common(1)[0][0], 'date': '', 'kind': 'عقد اشتراك', 'src': SRC_MODEL})
    for c in demoted:
        notes.append(('حُذف لعدم التحقق', f"«{c.get('number')}» رقم خط/طلب لا عقد — صار طلب خدمة تحت عقده"))
        line = clean_number(c.get('number'))
        if line and not any(clean_number(o.get('line')) == line for o in f['service_orders']):
            f['service_orders'].append({'line': line, 'contract': merged[0]['number'] if len(merged) == 1 else '',
                                        'date': c.get('date') or '', 'src': c.get('src')})
    orders = {}
    for o in f['service_orders']:
        line = clean_number(o.get('line'))
        if not line:
            continue
        cur = orders.get(line)
        o = dict(o, line=line, contract=clean_number(o.get('contract')))
        if cur is None:
            orders[line] = o
            continue
        for k, v in o.items():
            if v not in (None, '', []) and cur.get(k) in (None, '', []):
                cur[k] = v
    for o in orders.values():
        if not o.get('contract') and len(merged) == 1:
            o['contract'] = merged[0]['number']
        if o.get('contract') and not any(m['number'] == o['contract'] for m in merged):
            o['contract'] = merged[0]['number'] if len(merged) == 1 else o['contract']
    for i, c in enumerate(merged, 1):
        c['id'] = f'C{i}'
    f['contracts'] = merged
    f['service_orders'] = sorted(orders.values(), key=lambda o: o['line'])
    for i, o in enumerate(f['service_orders'], 1):
        o['id'] = f'L{i}'
    for i, x in enumerate(sorted(f['invoices'], key=lambda x: (x.get('line') or '', date_key(x.get('date')))), 1):
        x['id'] = f'I{i}'
    f['invoices'].sort(key=lambda x: x['id'])
    for i, p in enumerate(f['payments'], 1):
        p['id'] = f'P{i}'
    for i, t in enumerate(f['statement_totals'], 1):
        t['id'] = f'T{i}'


# ---------- المطالبة والمحاضر والدفاع ----------

def claim(base, data, docs):
    """المبلغ المطالب به من صحيفة الدعوى (أكثر مبلغ بالدينار تكراراً فيها) + الاقتباس، أو None."""
    plaint = next((d for d in docs if d['kind'] == 'صحيفة الدعوى'), None)
    texts = ['\n'.join(t for _n, t in plaint['pages'])] if plaint else []
    if not texts:
        src = (data.get('sources') or {}).get('plaint') or {}
        if src.get('text'):
            texts = [src['text']]
    votes, quote = Counter(), {}
    for t in texts:
        for m in re.finditer(r'(?:مبلغ\s*(?:و?قدره)?|بمبلغ)\s*\(?\s*(\d[\d,]*\.\d{3})\s*(?:د\.?\s*ك|دينار)', t.translate(_DIG)):
            k = calc.norm_num(dec(m.group(1)))
            votes[k] += 1
            quote.setdefault(k, m.group(0))
    if not votes:
        return None
    k, _c = votes.most_common(1)[0]
    return {'amount': Decimal(k), 'quote': quote[k], 'source': 'صحيفة الدعوى'}


def minutes_facts(base, data, plist):
    """من المحاضر فقط: العدد، الحضور والتخلف، ثبوت الإعلان، المناقشة، بوابة الاكتمال (كلها من
    case_procedures.proven_facts — مصدر واحد للإجراءات)، وما قُدّم والطلبات وتاريخ الحجز."""
    import case_procedures as cp
    import research_pipeline as rp
    proc = data.get('procedures') or {}
    mins = rp.minutes(base, data)
    texts = [m['text'] for m in mins]
    out = cp.proven_facts(data, texts)
    joined = '\n'.join(texts)
    submitted = {}
    for m in re.finditer(r'قدم\s+(?:ال)?(?:حاضر|وكيل)\s+عن\s+(المدعي[ةه]|المدعى\s+علي(?:ه|ها))\s+([^،.\n]{0,80})', joined):
        who = 'plaintiff' if 'علي' not in m.group(1) else 'defendant'
        kinds = [k for k in ('مذكرة دفاع', 'حافظة مستندات') if k.split()[0] in m.group(2)]
        submitted.setdefault(who, [])
        submitted[who] += [k for k in kinds if k not in submitted[who]]
    requested = [m.group(0).strip() for m in re.finditer(r'(?:كلفت|طلبت|تكليف)\s+الخبر[ةه][^.\n]{0,160}', joined)]
    out.update(submitted=submitted, requested=requested,
               received=fmt_date((proc.get('received') or {}).get('date')),
               judgment=fmt_date((proc.get('judgment') or {}).get('date')),
               booked=fmt_date((proc.get('booked') or {}).get('date')))
    return out


def defenses(docs, model_def, mf):
    """المذكرات المقدّمة (المقدّم والتاريخ والمرجع) + ملخص النموذج المتحقَّق إن وجد. لا دفاع بلا مذكرة أو محضر."""
    out = []
    for d in docs:
        if not d['memo']:
            continue
        by = 'defendant' if 'عليه' in (d.get('side') or '') else 'plaintiff' if d.get('side') else ''
        summ = next((x.get('summary') for x in model_def if x.get('doc') == d['code'] and x.get('summary')), '')
        if by != 'defendant' or not _clean_summary(summ):        # ملخص النموذج: لدفاع المدعى عليه فقط وبعربية قصيرة بلا أرقام
            summ = ''
        else:
            summ = _clean_summary(summ)
        out.append({'by': by, 'side': d.get('side') or '', 'date': d.get('date') or '', 'doc': d['code'],
                    'cite': cite(d), 'summary': summ})
    return out


def _clean_summary(t):
    t = ' '.join(str(t or '').split()).strip(' .،')
    if not t or len(t.split()) > 25 or re.search(r'[A-Za-z0-9٠-٩]|\[|\]|حافظ|مستند|صفح', t):
        return ''
    return t


# ---------- البناء ----------

def corpus_key(docs, data):
    return _sha([[d['code'], d['side'], d['date'], d['pages']] for d in docs]
                + [(data.get('procedures') or {}).get('attendance'), (data.get('mission') or {}).get('raw')])


def build(base, data, ask=None, force=False, case_type='', reread=None):
    """يبني الحقائق ويحفظها (data['facts3'] + الحقائق.json). ask=None ← قارئ الكود وحده (مع ملاحظة).
    يرجع dict الحقائق. الاستخراج بالنموذج مخزّن ببصمة المستندات (لا يُعاد إلا بتغيّرها أو force).
    reread: نص صفحات أعاد النموذج قراءتها من PDF ([{doc, page, text}]) — يُحفظ مع الحقائق ويدخل التحقق."""
    docs = corpus(base, data)
    texts = ['\n'.join(t for _n, t in d['pages']) for d in docs]
    plist = parties(data, texts)
    key = corpus_key(docs, data)
    old = data.get('facts3') or {}
    notes = []
    code = scan(docs)
    model, removed = {k: [] for k in EXTRACT_KEYS}, []
    same = old.get('key') == key
    cached = old.get('model_raw') if same and not force else None
    if reread is None:
        reread = (old.get('reread') or []) if same else []
    vdocs = apply_reread(docs, reread)
    raw = cached
    if raw is None and ask is not None:
        import ai_call_log
        ai_call_log.detail('استخراج الحقائق من كل المستندات')
        raw = ask(extract_prompt(docs, plist, case_type))
    if raw:
        model, removed = verify_model(raw, vdocs)
        if raw is not cached:
            import ai_call_log
            ai_call_log.verdict(True, f'حُذف لعدم التحقق: {len(removed)}' if removed else 'كل العناصر تحققت')
    elif ask is None:
        notes.append(('ناقص', 'لم يُستعمل نموذج للاستخراج — الحقائق من قارئ الكود للجداول وحده'))
    f = merge(code, model, notes)
    merge_near_contracts(f, texts, notes)
    for r in removed:                                # ما غطّاه قارئ الكود بحقيقة متحقَّقة لا يُعلن حذفه (ضجيج)
        text, k, it = r if isinstance(r, tuple) else (r, '', {})
        if not covered(f, k, it):
            notes.append(('حُذف لعدم التحقق', text))
    for d in docs:
        if d.get('merged') and not any(r.get('doc') == d['code'] for r in reread):
            notes.append(('قرار يحتاج مراجعة الخبير', f"{d['code']} ({d['kind']} {d['date']}): "
                          + '، '.join(f'الصفحات {a}–{b}' for a, b in d['merged'])
                          + ' مدموجة عند التحويل — أرقام صفحاتها ومستنداتها غير موثوقة؛ أعد قراءة الملف'))
    f.update(schema=SCHEMA, key=key, at=_now(), model_raw=raw or '', parties=plist, reread=list(reread),
             removed=len(removed), need_pdf=need_pdf_of(raw),
             claim=claim(base, data, docs), minutes=minutes_facts(base, data, plist),
             defenses=defenses(docs, f.get('defenses') or [], None), notes=[list(n) for n in notes],
             docs=[{'code': d['code'], 'kind': d['kind'], 'side': d['side'], 'date': d['date'], 'memo': d['memo'],
                    'docno': {str(k): v for k, v in d['docno'].items()}, 'file': d['file'],
                    'merged': d.get('merged') or []} for d in vdocs])
    for p in plist:
        if 'الافتراضي' in p['evidence']:
            f['notes'].append(['قرار يحتاج مراجعة الخبير', f"الجنس النحوي لـ«{p['name']}»: {p['evidence']}"])
    f = json.loads(json.dumps(f, ensure_ascii=False, default=str))      # JSON آمن في case.json (المبالغ نصوص Decimal)
    data['facts3'] = f
    save(base, f)
    return f


def _one_digit_apart(a, b):
    """رقمان طويلان يختلفان بخانة واحدة محذوفة/مزيدة/مبدّلة (خطأ قراءة OCR) — 275854644 و2758545644."""
    if a == b or min(len(a), len(b)) < 7 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    s, t = (a, b) if len(a) < len(b) else (b, a)
    return any(t[:i] + t[i + 1:] == s for i in range(len(t)))


def merge_near_contracts(f, texts, notes):
    """عقدان برقمين متقاربين (خانة واحدة) = عقد واحد قُرئ رقمه خطأً: يبقى الأكثر وروداً في المستندات (ثم ما أكّده النموذج)،
    وتنتقل إليه طلبات الخدمة، مع ملاحظة للخبير. يمنع «عقدين» مكررين في البحث والنتيجة."""
    cs = f.get('contracts') or []
    if len(cs) < 2:
        return
    joined = '\n'.join(texts).translate(_DIG)

    def weight(c):
        n = c.get('number') or ''
        return (len(re.findall(rf'(?<!\d){n}(?!\d)', joined)) if n else 0, c.get('src') == SRC_MODEL, bool(c.get('date')))
    keep = []
    for c in sorted(cs, key=weight, reverse=True):
        twin = next((k for k in keep if c.get('number') and k.get('number')
                     and _one_digit_apart(c['number'], k['number'])), None)
        if twin is None:
            keep.append(c)
            continue
        for k, v in c.items():
            if v not in (None, '', []) and twin.get(k) in (None, '', []) and k not in ('number', 'id'):
                twin[k] = v
        for o in f.get('service_orders') or []:
            if o.get('contract') == c['number']:
                o['contract'] = twin['number']
        notes.append(('قرار يحتاج مراجعة الخبير', f"رقم العقد «{c['number']}» يختلف بخانة واحدة عن «{twin['number']}» — "
                      f"عُدّا عقداً واحداً برقم {twin['number']} (الأكثر وروداً في المستندات)؛ تحقّق من الرقم"))
    if len(keep) < len(cs):
        order = {id(c): i for i, c in enumerate(cs)}
        f['contracts'] = sorted(keep, key=lambda c: order[id(c)])
        for i, c in enumerate(f['contracts'], 1):
            c['id'] = f'C{i}'


def need_pdf_of(raw):
    """طلبات النموذج لإرسال PDF ([{doc, pages, why}]) من ردّه."""
    obj = _parse_json(raw) if raw else None
    out = []
    for r in (obj or {}).get('need_pdf') or []:
        if isinstance(r, dict) and re.fullmatch(r'D\d+', str(r.get('doc') or '').strip()):
            out.append({'doc': r['doc'].strip(), 'pages': str(r.get('pages') or '').strip(),
                        'why': str(r.get('why') or '').strip()[:120]})
    return out


def covered(f, key, it):
    """عنصر من النموذج رُفض لكن حقيقته موجودة أصلاً من قارئ الكود (الرقم نفسه) ← لا ملاحظة."""
    it = it or {}
    num = clean_number(it.get('number'))
    line = clean_number(it.get('line'))
    if key == 'invoices':
        return bool(num) and any(i['number'] == num for i in f.get('invoices') or [])
    if key == 'contracts':
        return bool(num) and any(c['number'] == num for c in f.get('contracts') or []) or             any(o['line'] == num for o in f.get('service_orders') or [])
    if key == 'service_orders':
        return bool(line) and any(o['line'] == line for o in f.get('service_orders') or [])
    if key == 'payments':
        inv = clean_number(it.get('invoice'))
        return any(p.get('invoice') == inv or (line and p.get('line') == line) for p in f.get('payments') or [])
    if key == 'statement_totals':
        return any(t.get('src') == SRC_CODE for t in f.get('statement_totals') or [])
    return False


def save(base, f):
    import case_documents as cd
    cd._write_md(base, REL, json.dumps(f, ensure_ascii=False, indent=1, default=str) + '\n')


def doc_of(f, code):
    """سجل مستند من الحقائق (للمراجع) بالشكل الذي يقبله cite()."""
    d = next((x for x in f.get('docs') or [] if x['code'] == code), None)
    if d is None:
        return None
    return dict(d, docno={int(k): v for k, v in (d.get('docno') or {}).items()},
                merged=[tuple(x) for x in d.get('merged') or []])
