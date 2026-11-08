# ===== case_index.py — «فهرس_المستندات.md» داخل مجلد القضية (2026-10-18) =====
# يُبنى بعد كل مزامنة من ملفات markdown المحوَّلة (لا من الأصول مباشرة)، ليكون مرجع أي خطوة:
#   لكل مستند: الاسم، النوع، التاريخ، الأطراف، الصفحات/المسار.
#   ولكل عقد (أو ملحق/أمر شراء/أمر تغيير…) داخل أي مستند: نوعه بوضوح، تاريخه، أطرافه، قيمته، ورقم الصفحة.
# قواعد نصية فقط (لا ذكاء اصطناعي): ما لم يُعثر عليه يُكتب «—» ولا يُخمَّن.
import os
import re
import tempfile
from datetime import datetime

import case_folder as cf

INDEX_NAME = '_نظام/فهرس_المستندات.md'
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_PAGE = re.compile(r'<!--\s*صفحة\s*(\d+)\s*-->')
_COMMENT = re.compile(r'<!--.*?-->', re.S)

# نوع العقد: الأدق أولاً (أمر التغيير قبل الأمر، والملحق قبل العقد)
CONTRACT_KINDS = (
    ('أمر تغيير', re.compile(r'[أا]مر\s+(?:ال)?تغيير|[أا]وامر\s+(?:ال)?تغيير|change\s+order', re.I)),
    ('أمر شراء', re.compile(r'[أا]مر\s+(?:ال)?شراء|purchase\s+order', re.I)),
    ('أمر عمل', re.compile(r'[أا]مر\s+(?:ال)?عمل\b|work\s+order', re.I)),
    ('ملحق عقد', re.compile(r'ملحق\s+(?:رقم\s*\S+\s+)?(?:لل)?عقد|ملحق\s+رقم|addendum', re.I)),
    ('عقد من الباطن', re.compile(r'عقد\s+(?:مقاولة\s+)?(?:من\s+)?الباطن')),
    ('اتفاقية', re.compile(r'^\s*(?:اتفاقية|اتفاق)\b', re.M)),
    ('عقد', re.compile(r'^\s*عقد\s+\S+|(?:تم|حرر)\s+(?:الاتفاق|هذا\s+العقد)|^\s*العقد\b', re.M)),
)
FOLDER_TYPES = {cf.MINUTES: 'محضر أعمال', cf.JUDGMENT: 'حكم', cf.PLAINT: 'صحيفة دعوى', cf.PRIOR: 'تقرير سابق'}
_OTHER_TYPES = (('مذكرة دفاع', ('مذكرة بدفاع', 'مذكره بدفاع', 'مذكرة دفاع', 'مذكرة بأقوال')),
                ('حافظة مستندات', ('حافظة مستندات', 'حافظه مستندات')),
                ('فاتورة', ('فاتورة', 'فاتوره', 'invoice')), ('كشف حساب', ('كشف حساب',)),
                ('خطاب', ('خطاب', 'كتاب رقم')), ('حكم', ('حكمت المحكمة', 'باسم صاحب السمو')))

_DATE = re.compile(r'(?<!\d)(\d{1,2})\s*[/\-.\\]\s*(\d{1,2})\s*[/\-.\\]\s*(\d{4})(?!\d)|(?<!\d)(\d{4})\s*[/\-.\\]\s*(\d{1,2})\s*[/\-.\\]\s*(\d{1,2})(?!\d)')
_DATE_CUE = re.compile(r'(?:بتاريخ|المؤرخ(?:ة)?|مؤرخ(?:ة)?|تاريخ\s*[:：]?|حرر\s+في|بجلسة|الموافق)\s*[:：]?\s*$')
_AMOUNT = re.compile(r'(?:بمبلغ|مبلغ|بقيمة|قيمة(?:\s+العقد)?|القيمة(?:\s+الإجمالية)?|الإجمالي|إجمالي)\s*[:：]?\s*(?:وقدره\s*)?'
                     r'(\d{1,3}(?:[,٬]\d{3})+(?:[.٫]\d+)?|\d+(?:[.٫]\d+)?)\s*(د\.?\s?ك|دينار|KD|KWD)?', re.I)
_PARTY_LINES = (
    re.compile(r'(?:الطرف\s+الأول|الطرف\s+الاول|الفريق\s+الأول)\s*[:：\-–]?\s*(?:و?هو|و?هي)?\s*[:：]?\s*([^\n،.]{3,80})'),
    re.compile(r'(?:الطرف\s+الثاني|الفريق\s+الثاني)\s*[:：\-–]?\s*(?:و?هو|و?هي)?\s*[:：]?\s*([^\n،.]{3,80})'),
)
_PLAINT_PARTIES = (re.compile(r'(?:المدعي|المدعية|المدعون|المستأنف|المستأنفة)\s*[:：]\s*([^\n]{3,80})'),
                   re.compile(r'(?:المدعى\s+عليه(?:ا|م)?|المدعى\s+عليها|المستأنف\s+ضده|المستأنف\s+ضدها)\s*[:：]\s*([^\n]{3,80})'))
_BETWEEN = re.compile(r'(?:بين|المرفوعة\s+من)\s*[:：]?\s*([^\n]{3,80}?)\s+(?:و\s*بين|ضد)\s+([^\n]{3,80})')


def _clean(s):
    return ' '.join((s or '').replace('|', ' ').split()).strip(' :：-–،')


def find_date(text):
    """أول تاريخ في النص يسبقه «بتاريخ/المؤرخ/حرر في…» وإلا أول تاريخ صالح؛ dd/mm/yyyy أو ''."""
    t = (text or '').translate(_DIGITS)
    first = ''
    for m in _DATE.finditer(t):
        if m.group(1):
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            y, mo, d = int(m.group(4)), int(m.group(5)), int(m.group(6))
        if not (1 <= d <= 31 and 1 <= mo <= 12 and 1950 <= y <= 2100):
            continue
        val = f'{d:02d}/{mo:02d}/{y:04d}'
        if _DATE_CUE.search(t[max(0, m.start() - 25):m.start()]):
            return val
        first = first or val
    return first


def find_amount(text):
    m = _AMOUNT.search((text or '').translate(_DIGITS))
    if not m:
        return ''
    return m.group(1).replace('٬', ',').replace('٫', '.') + (' د.ك' if m.group(2) else '')


def find_parties(text):
    t = text or ''
    out = []
    for rx in _PARTY_LINES + _PLAINT_PARTIES:
        m = rx.search(t)
        if m and _clean(m.group(1)):
            out.append(_clean(m.group(1)))
    if not out:
        m = _BETWEEN.search(t)
        if m:
            out = [_clean(m.group(1)), _clean(m.group(2))]
    seen, res = set(), []
    for p in out:
        if p and p not in seen:
            seen.add(p)
            res.append(p)
    return res


def contract_kind(text):
    head = '\n'.join((text or '').splitlines()[:12])
    for kind, rx in CONTRACT_KINDS:
        if rx.search(head):
            return kind
    return ''


def doc_type(folder, text, name=''):
    if folder in FOLDER_TYPES:
        return FOLDER_TYPES[folder]
    head = (name + '\n' + '\n'.join((text or '').splitlines()[:15])).lower()
    k = contract_kind(text) or contract_kind(name)
    if k:
        return k
    for label, cues in _OTHER_TYPES:
        if any(c in head for c in cues):
            return label
    return 'مستند'


def split_pages(md):
    """[(رقم الصفحة، نص)] من علامات <!-- صفحة N -->؛ بلا علامات ← صفحة واحدة."""
    marks = list(_PAGE.finditer(md or ''))
    if not marks:
        return [(1, _COMMENT.sub('', md or ''))]
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        out.append((int(m.group(1)), _COMMENT.sub('', md[m.end():end])))
    return out


def contracts_in(md):
    """العقود داخل مستند (حافظة فيها عدة عقود/ملاحق): صفحة تبدأ بعنوان عقد ← سجل جديد."""
    out = []
    for n, text in split_pages(md):
        kind = contract_kind(text)
        if not kind:
            continue
        out.append({'kind': kind, 'page': n, 'date': find_date(text), 'parties': find_parties(text),
                    'value': find_amount(text)})
    return out


def _read(base, rel):
    try:
        with open(os.path.join(base, rel), encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def build(base):
    """[{name, file, md, folder, type, date, parties, pages, contracts:[…]}] لكل أصل محوَّل، مرتّبة بالمجلد ثم التاريخ."""
    man = cf.load_manifest(base)['files']
    rows = []
    for rel, e in sorted(man.items()):
        if e.get('state') != 'done' or not os.path.exists(os.path.join(base, rel)):
            continue
        md = _read(base, e.get('md') or cf.md_rel(rel))
        if not md.strip():
            continue
        folder = cf.kind_of(rel)
        name = os.path.basename(rel)
        body = _COMMENT.sub('', md)
        kind = doc_type(folder, body, name)
        cons = contracts_in(md)
        if kind in [k for k, _ in CONTRACT_KINDS] and not cons:
            cons = [{'kind': kind, 'page': 1, 'date': find_date(body), 'parties': find_parties(body),
                     'value': find_amount(body)}]
        rows.append({'name': name, 'file': rel, 'md': e.get('md') or cf.md_rel(rel), 'folder': folder, 'type': kind,
                     'date': find_date(body) or find_date(name.replace('-', '/')), 'parties': find_parties(body),
                     'pages': e.get('pages') or len(split_pages(md)), 'engine': e.get('engine', ''),
                     'contracts': cons})
    return rows


def _iso(dmy):
    try:
        return datetime.strptime(dmy, '%d/%m/%Y').strftime('%Y-%m-%d')
    except (TypeError, ValueError):
        return '9999'


def render(rows, caso_no='', ai=None):
    esc = lambda s: (s or '—').replace('|', '\\|')       # noqa: E731
    out = [f'# فهرس المستندات {caso_no}'.rstrip(), '',
           f'> مولَّد تلقائياً من ملفات markdown بعد كل مزامنة ({datetime.now():%Y-%m-%d %H:%M}) — لا تعدّله يدوياً.', '',
           '| م | المستند | النوع | التاريخ | الأطراف | الصفحات | المسار |', '|---|---|---|---|---|---|---|']
    for i, r in enumerate(rows, 1):
        out.append(f"| {i} | {esc(r['name'])} | {esc(r['type'])} | {esc(r['date'])} | {esc('، '.join(r['parties']))} "
                   f"| {r['pages']} | {esc(r['file'])} |")
    cons = [(r, c) for r in rows for c in r['contracts']]
    out += ['', '## العقود وملحقاتها', '']
    if not cons:
        out.append('_لم يُتعرَّف على عقد في المستندات المحوَّلة._')
    else:
        out += ['| م | النوع | التاريخ | الأطراف | القيمة | المستند | الصفحة |', '|---|---|---|---|---|---|---|']
        cons.sort(key=lambda rc: _iso(rc[1]['date']))
        for i, (r, c) in enumerate(cons, 1):
            out.append(f"| {i} | {esc(c['kind'])} | {esc(c['date'])} | {esc('، '.join(c['parties']))} | {esc(c['value'])} "
                       f"| {esc(r['file'])} | {c['page']} |")
    if ai:                                     # العقود المستخرجة بالذكاء والمتحقَّق منها (case_contracts)
        import case_contracts
        out += ['', '## العقود (من محتوى المستندات — مستخرجة ومتحقَّق منها)', '',
                case_contracts.render(ai if 'contracts' in ai else {'contracts': ai}).split('\n', 3)[-1]]
    return '\n'.join(out) + '\n'


def write_index(base, data=None):
    """يكتب فهرس_المستندات.md ذرّياً ويرجع المسار؛ data (اختياري) ← data['doc_index'] (موجز) للخطوات."""
    rows = build(base)
    text = render(rows, (data or {}).get('caso_no', ''), data if (data or {}).get('contracts') else None)
    path = os.path.join(base, INDEX_NAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.idx.', suffix='.tmp', dir=os.path.dirname(path))
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    os.replace(tmp, path)
    if data is not None:
        data['doc_index'] = [{k: r[k] for k in ('name', 'file', 'type', 'date', 'parties', 'pages', 'contracts')}
                             for r in rows]
    return path
