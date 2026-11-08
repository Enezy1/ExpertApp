# ===== case_sort.py — الفرز الآلي لمستندات القضية: النوع والمقدّم والتاريخ ثم التسمية والنقل (2026-10-21) =====
# كل ملف جديد (اسمه غير معروف/غير معتمد) يُحوَّل أولاً إلى markdown، ثم يُرسل نصه (الصفحة الأولى + بداية كل صفحة لكشف
# الأجزاء) إلى أقوى Gemini متاح (مزوّد مهمة «الفرز» من جدول المزوّدين) بطلب يعيد JSON فقط: الأجزاء (حافظة/مذكرة/محضر
# ورقمه/حكم/صحيفة/تقرير)، ومن قدّمها (من قائمة أطراف القضية)، وتاريخها، ونطاق صفحاتها، والعقد إن وُجد في حافظة.
# الكود يتحقق: التاريخ حرفياً في نص الجزء، والصفة (أو اسم مقدّمها) حرفياً فيه، ورقم المحضر من نص المحضر نفسه.
# ثم يُنقل الملف (ومشتقه في markdown) إلى مجلده ويُسمّى:
#   «حكم الإحالة» «صحيفة الدعوى» «محضر الخبرة رقم N» «تقرير خبرة سابق DD-MM-YYYY» (مستندات_النظام)
#   «حافظة مستندات المدعية 15-10-2025» (حوافظ) «مذكرة دفاع المدعى عليه 02-04-2026» (مذكرات)
# الصفة بالجنس الصحيح من أطراف القضية (الشركة مؤنث؛ وإلا بصيغة النص نفسه؛ وإلا المذكر)، والتكرار « (2)».
# الملف المختلط (أكثر من جزء) يبقى في «أخرى» باسم يصف محتواه («2 مذكرة و1 حافظة - المدعية 15-10-2025») وتفاصيل أجزائه
# في manifest وdata['sort'] (ويعرضها الملخص). ما لم يُحسم يبقى في «أخرى» مع سؤال واحد للخبير (سطر أحمر).
import json
import os
import re
from datetime import datetime

import case_folder as cf
import case_layout as cl

T_PORTF, T_MEMO, T_MIN, T_JUDG, T_PLAINT, T_PRIOR, T_OTHER = 'حافظة', 'مذكرة', 'محضر', 'حكم', 'صحيفة', 'تقرير', 'أخرى'
TYPES = (T_PORTF, T_MEMO, T_MIN, T_JUDG, T_PLAINT, T_PRIOR, T_OTHER)
TYPE_WORDS = {T_PORTF: ('حافظة', 'حافظه'), T_MEMO: ('مذكرة', 'مذكره'), T_MIN: ('محضر',),
              T_JUDG: ('حكم', 'المحكمة', 'المحكمه'), T_PLAINT: ('صحيفة', 'صحيفه', 'لائحة', 'لائحه'),
              T_PRIOR: ('تقرير',)}
ROLES = ('plaintiff', 'defendant', 'appellant', 'appellee')
ROLE_WORDS = {'plaintiff': ('المدعي', 'المدعية'), 'defendant': ('المدعى عليه', 'المدعى عليها'),
              'appellant': ('المستأنف', 'المستأنفة'), 'appellee': ('المستأنف ضده', 'المستأنف ضدها')}
_ORD_M = ('الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس', 'السابع', 'الثامن', 'التاسع', 'العاشر')
_ORD_F = ('الأولى', 'الثانية', 'الثالثة', 'الرابعة', 'الخامسة', 'السادسة', 'السابعة', 'الثامنة', 'التاسعة', 'العاشرة')
PAGE_HEAD_CHARS = 350          # بداية كل صفحة (لكشف أجزاء الملف المختلط)
FIRST_PAGE_CHARS = 2500
MAX_PROMPT_CHARS = 30000
_PAGE = re.compile(r'<!--\s*صفحة\s*(\d+)\s*-->|^-{3}\s*صفحة\s*(\d+)\s*-{3}\s*$', re.M)
_CANON = {
    cf.SYSDOCS: re.compile(r'^(?:حكم الإحالة|حكم خبير|صحيفة الدعوى(?: — معدّلة)?|محضر الخبرة رقم \d+|حكم \d{2}-\d{2}-\d{4}|حكم|'
                           r'تقرير خبرة سابق(?: \d{2}-\d{2}-\d{4})?)(?: \(\d+\))?$'),
    cf.PORTF: re.compile(r'^حافظة مستندات .+ \d{2}-\d{2}-\d{4}(?: \(\d+\))?$'),
    cf.MEMOS: re.compile(r'^مذكرة دفاع .+ \d{2}-\d{2}-\d{4}(?: \(\d+\))?$'),
}


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _norm(t):
    import case_procedures as cp
    return cp.norm_ar(t or '')


# ---------- الأطراف والصفة ----------

def _names(v):
    if isinstance(v, str):
        return [x.strip() for x in re.split(r'[،,\n]|\s+و\s*(?=شركة)', v) if x.strip()]
    return [x.strip() for x in v or [] if isinstance(x, str) and x.strip()]


def party_names(data, role):
    c = data.get('case') or {}
    if role == 'plaintiff':
        return _names(c.get('plaintiffs')) or _names(c.get('plaintiff'))
    if role == 'defendant':
        return _names(c.get('defendants'))
    return _names(c.get(role + 's')) or _names(c.get(role))


def parties_list(data):
    """[(role, index, name)] لكل طرف معروف — تُعطى للنموذج ليختار منها."""
    out = []
    for role in ROLES:
        for i, n in enumerate(party_names(data, role), 1):
            out.append((role, i, n))
    return out


def _is_company(name):
    try:
        import case_subject_telecom as st
        return st._is_company(name or '')
    except Exception:
        return False


def _wording(role, text):
    """('f'|'m'|'') بحسب صيغة النص نفسه للدور (المدعية/المدعي، المدعى عليها/عليه…)."""
    m, f = (_norm(x) for x in ROLE_WORDS[role])
    t = _norm(text)
    has_f = bool(re.search(re.escape(f) + r'(?![ء-ي])', t))
    has_m = bool(re.search(re.escape(m) + r'(?![ء-ي])', t))
    if has_f and not has_m:
        return 'f'
    if has_m and not has_f:
        return 'm'
    return ''


def role_label(data, role, index=1, text='', as_written=''):
    """الصفة بالجنس الصحيح: «المدعية»، «المدعى عليه»، «المدعى عليها الأولى»، «المستأنف ضدها»…
    الجنس: جنس الطرف من بيانات الأطراف (party_gender: الاسم شركة/الصفة في الصحيفة) ← وإلا الصفة كما كُتبت في الجزء
    (as_written: «السادة شركة … المدعية») ← وإلا صيغة النص؛ وإلا المذكر. الترتيب إن تعدد أطراف الدور."""
    if role not in ROLE_WORDS:
        return ''
    names = party_names(data, role)
    name = names[index - 1] if 0 < (index or 0) <= len(names) else (names[0] if len(names) == 1 else '')
    g = party_gender(data, role, index)
    if g:
        fem = g == 'f'
    elif as_written and (_is_company(as_written) or _wording(role, as_written)):
        fem = _is_company(as_written) or _wording(role, as_written) == 'f'
    else:
        fem = _wording(role, text) == 'f'
    word = ROLE_WORDS[role][1 if fem else 0]
    if len(names) > 1 and 0 < (index or 0) <= len(names):
        word += ' ' + (_ORD_F if fem else _ORD_M)[min(index, 10) - 1]
    return word


def party_gender(data, role, index=1):
    """'f' | 'm' | '' — جنس الطرف من بيانات الأطراف: الاسم شركة/مؤسسة ← مؤنث؛ أو ما ثبت من الصحيفة
    (data['case']['genders'][role][index-1] يكتبه الفرز من صفة الطرف في صحيفة الدعوى). '' = لم يتحدد."""
    names = party_names(data, role)
    name = names[index - 1] if 0 < (index or 0) <= len(names) else (names[0] if len(names) == 1 else '')
    if name and _is_company(name):
        return 'f'
    gs = ((data.get('case') or {}).get('genders') or {}).get(role) or []
    i = (index or 1) - 1
    if 0 <= i < len(gs) and gs[i] in ('f', 'm'):
        return gs[i]
    return ''


def role_in_text(role, text, as_written='', name=''):
    """الصفة واردة حرفياً في نص الجزء: كلمة الدور (أي جنس) أو ما نقله النموذج حرفياً أو اسم الطرف."""
    t = _norm(text)
    cands = [ROLE_WORDS[role][0]] + ([as_written] if as_written else []) + ([name] if name else [])
    if role == 'appellee':
        cands += ['المستأنف عليه', 'المستأنف ضده']
    return any(c and _norm(c) in t for c in cands)


# ---------- النص والصفحات ----------

def split_pages(md):
    """[(رقم الصفحة، نصها)] من علامات <!-- صفحة N --> أو --- صفحة N ---؛ بلا علامات ← صفحة واحدة."""
    marks = list(_PAGE.finditer(md or ''))
    if not marks:
        return [(1, md or '')]
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        out.append((int(m.group(1) or m.group(2)), md[m.end():end].strip()))
    return out


def excerpt(md):
    """الصفحة الأولى + بداية كل صفحة تالية (لكشف الأجزاء)."""
    pages = split_pages(md)
    parts, total = [], 0
    for i, (n, t) in enumerate(pages):
        piece = t[:FIRST_PAGE_CHARS] if i == 0 else t[:PAGE_HEAD_CHARS]
        line = f'--- صفحة {n} ---\n{piece}'
        if total + len(line) > MAX_PROMPT_CHARS:
            parts.append(f'… (بقية الصفحات حتى {pages[-1][0]} لم تُرسل)')
            break
        parts.append(line)
        total += len(line)
    return '\n'.join(parts), len(pages)


def part_text(md, pages):
    """نص صفحات الجزء [من، إلى] (أو كل النص إن لم يُحدَّد)."""
    try:
        a, b = int(pages[0]), int(pages[1])
    except (TypeError, ValueError, IndexError):
        return md
    got = [t for n, t in split_pages(md) if a <= n <= b]
    return '\n'.join(got) or md


# ---------- الطلب ----------

PROMPT = """أنت تفرز مستندات قضية أمام إدارة الخبراء بوزارة العدل الكويتية. أعد JSON فقط بلا أي نص آخر.
السؤال: هل يحتوي هذا الملف على حافظة مستندات؟ مذكرة دفاع؟ محضر خبرة (ورقمه)؟ حكم؟ صحيفة دعوى؟ تقرير خبرة سابق؟
ومن قدّمه: المدعية أم المدعى عليه/عليها أم المستأنف أم المستأنف ضده (من قائمة الأطراف المعطاة)؟ وما تاريخه؟
وإن احتوى أكثر من مذكرة أو حافظة فاذكر كل جزء منفصلاً: نوعه ومقدّمه وتاريخه ونطاق صفحاته.
{contract_q}
أطراف القضية:
{parties}

الصيغة المطلوبة:
{{"parts": [{{"type": "حافظة|مذكرة|محضر|حكم|صحيفة|تقرير|أخرى",
  "submitter_role": "plaintiff|defendant|appellant|appellee|unknown", "submitter_index": 1,
  "submitter_as_written": "الصفة أو الاسم كما ورد حرفياً في النص",
  "date": "DD/MM/YYYY", "date_as_written": "التاريخ كما ورد حرفياً",
  "minute_no": null, "referral": false, "pages": [1, 3],
  "contract": {{"found": false, "number": "", "date": "", "parties": [], "scope": "", "value": "", "duration": "",
               "summary": "", "doc_no": "", "page": null}}}}]}}
قواعد: لا تخمّن؛ ما لا يرد في النص اتركه فارغاً أو unknown. referral=true للحكم الذي يندب الخبرة.
النص (الصفحة الأولى ثم بداية كل صفحة):
{text}"""

CONTRACT_Q = ('ولكل حافظة: هل تحتوي على عقد؟ إن وُجد: رقمه وتاريخه وأطرافه ونطاقه وقيمته ومدته، وملخص قصير، '
              'ومكانه (رقم المستند/الصفحة) في الحقل contract.')

_ROLE_AR = {'plaintiff': 'المدعي/المدعية', 'defendant': 'المدعى عليه/عليها', 'appellant': 'المستأنف/المستأنفة',
            'appellee': 'المستأنف ضده/ضدها'}


def build_prompt(data, md, with_contract=True):
    text, _ = excerpt(md)
    ps = parties_list(data)
    plines = '\n'.join(f'- {r} #{i} ({_ROLE_AR[r]}): {n}' for r, i, n in ps) or '- (لا أطراف مسجّلة؛ استعمل الصفة كما وردت)'
    return PROMPT.format(contract_q=CONTRACT_Q if with_contract else '', parties=plines, text=text)


def parse_reply(raw):
    if isinstance(raw, dict):
        return raw
    s = (raw or '').strip()
    s = re.sub(r'^```(?:json)?|```$', '', s, flags=re.M).strip()
    i, j = s.find('{'), s.rfind('}')
    if i < 0 or j < i:
        raise ValueError('ردّ الفرز ليس JSON')
    return json.loads(s[i:j + 1])


# ---------- التحقق ----------

def _type_in_text(t, text):
    nt = _norm(text)
    return t in TYPE_WORDS and any(_norm(w) in nt for w in TYPE_WORDS[t])


def _dmy(date):
    m = re.fullmatch(r'\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})\s*', date or '')
    return f'{int(m.group(1)):02d}-{int(m.group(2)):02d}-{m.group(3)}' if m else ''


def norm_type(raw):
    """النوع كما أعاده النموذج («صحيفة دعوى»، «حافظة مستندات»، «مذكرة دفاع»، «محضر خبرة»، «حكم تمهيدي»…) ← نوع معروف."""
    t = ' '.join(str(raw or '').split())
    if t in TYPES:
        return t
    for word, typ in (('صحيف', T_PLAINT), ('لائح', T_PLAINT), ('حافظ', T_PORTF), ('مذكر', T_MEMO), ('محضر', T_MIN),
                      ('تقرير', T_PRIOR), ('حكم', T_JUDG)):
        if t.startswith(word) or t.startswith('ال' + word):
            return typ
    return T_OTHER


def verify_part(data, p, md):
    """يرجع الجزء بعد التحقق: {type, role, index, label, date (DD-MM-YYYY أو ''), minute_no, pages, notes[], ok}."""
    import case_contracts as cc
    import case_procedures as cp
    text = part_text(md, p.get('pages'))
    notes = []
    t = norm_type(p.get('type'))
    if t != T_OTHER and not _type_in_text(t, text):
        notes.append(f'النوع «{t}» لم يرد حرفياً في النص')
        t = T_OTHER
    date = ''
    if p.get('date') and cc.date_in_text(p['date'], text):
        date = _dmy(p['date'])
    elif p.get('date'):
        notes.append(f'التاريخ {p["date"]} لم يرد حرفياً في النص')
    role = p.get('submitter_role') if p.get('submitter_role') in ROLES else ''
    idx = p.get('submitter_index') or 1
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        idx = 1
    names = party_names(data, role) if role else []
    name = names[idx - 1] if role and 0 < idx <= len(names) else ''
    if role and not role_in_text(role, text, p.get('submitter_as_written') or '', name):
        notes.append('الصفة لم ترد حرفياً في النص')
        role = ''
    label = role_label(data, role, idx, text, p.get('submitter_as_written') or '') if role else ''
    no = None
    if t == T_MIN:
        no = cp.number_from_text(text)                         # الرقم من نص المحضر نفسه، لا من النموذج
        if no is None and p.get('minute_no') not in (None, ''):
            try:
                cand = int(p['minute_no'])
                if re.search(rf'(?<!\d){cand}(?!\d)', cp.norm_ar(text)) and 'محضر' in cp.norm_ar(text):
                    no = cand
            except (TypeError, ValueError):
                pass
    return {'type': t, 'role': role, 'index': idx, 'label': label, 'date': date, 'minute_no': no,
            'referral': bool(p.get('referral')), 'pages': p.get('pages') or [], 'notes': notes,
            'contract': p.get('contract') if isinstance(p.get('contract'), dict) else {},
            'as_written': p.get('submitter_as_written') or ''}


# ---------- القرار والتسمية ----------

def is_canonical(rel):
    """الاسم معتمد في مجلده (لا يُعاد فرزه)."""
    folder = rel.split('/', 1)[0]
    stem = os.path.splitext(os.path.basename(rel))[0]
    pat = _CANON.get(folder)
    return bool(pat and pat.match(stem))


def _count_word(n, t):
    return f'{n} {t}'


def decide(parts, ext, has_referral=False):
    """(المجلد، الاسم، الحالة sorted|mixed|unresolved، سؤال). parts بعد التحقق."""
    real = [p for p in parts if p['type'] != T_OTHER]
    if len(real) > 1 or (len(parts) > 1 and real):
        order, counts = [], {}
        for p in real:
            counts[p['type']] = counts.get(p['type'], 0) + 1
            if p['type'] not in order:
                order.append(p['type'])
        name = ' و'.join(_count_word(counts[t], t) for t in order)
        labels = {p['label'] for p in real}
        dates = {p['date'] for p in real}
        tail = ' '.join(x for x in ((labels.pop() if len(labels) == 1 else ''),
                                    (dates.pop() if len(dates) == 1 else '')) if x)
        return cf.OTHER, cf.safe_name(name + (f' - {tail}' if tail else '')) + ext, 'mixed', ''
    if not real:
        return cf.OTHER, None, 'unresolved', 'لم يُعرف نوع هذا الملف: حدّد نوعه ومقدّمه وتاريخه'
    p = real[0]
    t = p['type']
    if t == T_MIN:
        if p['minute_no'] is None:
            return cf.OTHER, None, 'unresolved', 'محضر خبرة لم يُعرف رقمه من نصه: ما رقم المحضر؟'
        return cf.SYSDOCS, cf.minute_name(p['minute_no']) + ext, 'sorted', ''
    if t == T_PLAINT:
        return cf.SYSDOCS, 'صحيفة الدعوى' + ext, 'sorted', ''
    if t == T_JUDG:
        if p['referral'] and not has_referral:
            return cf.SYSDOCS, 'حكم الإحالة' + ext, 'sorted', ''
        return cf.SYSDOCS, (f"حكم {p['date']}" if p['date'] else 'حكم') + ext, 'sorted', ''
    if t == T_PRIOR:
        return cf.SYSDOCS, (f"تقرير خبرة سابق {p['date']}" if p['date'] else 'تقرير خبرة سابق') + ext, 'sorted', ''
    word, folder = ('حافظة مستندات', cf.PORTF) if t == T_PORTF else ('مذكرة دفاع', cf.MEMOS)
    missing = [x for x, ok in (('مقدّمها', p['label']), ('تاريخها', p['date'])) if not ok]
    if missing:
        return cf.OTHER, None, 'unresolved', f'{word}: لم يُعرف {" ولا ".join(missing)} من النص — حدّده'
    return folder, cf.safe_name(f"{word} {p['label']} {p['date']}") + ext, 'sorted', ''


def _has_referral(base, exclude=''):
    try:
        names = os.listdir(os.path.join(base, cf.SYSDOCS))
    except OSError:
        return False
    skip = os.path.basename(exclude or '')
    return any(cf.is_referral_name(n) and n != skip for n in names)


# ---------- التشغيل ----------

def pending(base, man=None):
    """الأصول المحوَّلة التي تحتاج فرزاً: اسمها غير معتمد في مجلدها، ولم تُفرز بنسختها الحالية (بصمة)."""
    man = man or cf.load_manifest(base)
    out = []
    for rel, e in sorted(man['files'].items()):
        if e.get('state') != 'done' or not os.path.exists(os.path.join(base, rel)):
            continue
        if is_canonical(rel):
            continue
        s = e.get('sort') or {}
        if s.get('sha1') == e.get('sha1') and s.get('state') in ('mixed', 'unresolved', 'sorted', 'manual'):
            continue
        out.append(rel)
    return out


def _read_md(base, e, rel):
    """نص markdown للأصل بلا رأس نوع المستند (الرأس لا يدخل التحقق الحرفي)."""
    import doc_header
    try:
        with open(os.path.join(base, e.get('md') or cf.md_rel(rel)), encoding='utf-8') as f:
            return doc_header.strip(f.read())
    except OSError:
        return ''


def write_header(base, man, rel):
    """رأس نوع المستند في أول markdown الأصل من نتيجة فرزه (تقرؤه الخطوات التالية بالكود). فشله صامت."""
    import doc_header
    e = man['files'].get(rel) or {}
    s = e.get('sort') or {}
    if e.get('state') != 'done':
        return False
    if s.get('state') == 'manual' and s.get('parts'):                 # قرار الخبير يتقدّم على الفرز الآلي
        t = dict(e.get('triage') or {}, parts=s['parts'])
    elif e.get('triage'):
        t = e['triage']
    else:
        return False
    return doc_header.write(base, e.get('md') or cf.md_rel(rel), doc_header.info_from_triage(t, e.get('sha1') or ''))


def sort_file(base, data, rel, ask, man):
    """يفرز ملفاً واحداً بالمرحلة الأولى (case_triage): كتلة الفرز من طلب التحويل نفسه إن وُجدت (بلا طلب)، وإلا طلب
    فرز واحد على النص المحوَّل. يُحفظ المحتوى المتحقَّق في manifest (e['triage']) ثم يُسمّى الملف ويُنقل — إلا إن كان
    اسمه معتمداً في مجلده (يُلخَّص ولا يُنقل). يرجع سجل الفرز، أو None (بلا نص، أو بلا مزوّد ولا كتلة تحويل)."""
    import case_triage as ct
    e = man['files'][rel]
    md = _read_md(base, e, rel)
    if not md.strip():
        return None
    raw, source, why = ct.triage_file(base, data, rel, ask, man, md)
    if raw is None:
        return None
    parts, notes = ct.verify(data, raw, md)
    if source != 'convert':
        import ai_call_log
        if not parts:
            ai_call_log.verdict(False, 'لم يُعد النموذج أي جزء')
        else:
            ai_call_log.verdict(True, f'{len(parts)} جزء' + (f'؛ حُذف ما لم يتحقق: {"؛ ".join(notes[:3])}' if notes else ''))
    ct.store(e, parts, notes + ([why] if why else []), source, raw)
    return _place(base, data, rel, parts, man, md)


def _place(base, data, rel, parts, man, md):
    """بعد حفظ الفرز: أطراف الصحيفة، ثم التسمية والنقل (أو الإبقاء)، ثم رأس نوع المستند في markdown."""
    import case_triage as ct
    e = man['files'][rel]
    if any(p.get('type') == T_PLAINT for p in parts):     # أطراف القضية وجنسهم من الصحيفة (إن لم يُعِدها النظام)
        ct.adopt_parties(data, parts, md)
    if (e.get('sort') or {}).get('state') == 'manual' and (e.get('sort') or {}).get('sha1') == e.get('sha1'):
        rec = dict(e['triage'], file=rel, state='kept')
    elif is_canonical(rel) and name_fits(base, rel, parts):
        rec = dict(e['triage'], file=rel, state='kept')
    else:
        rec = apply(base, data, rel, parts, man, source='ai')
    write_header(base, man, rec['file'])
    return rec


def _stem(rel):
    return re.sub(r' \(\d+\)$', '', os.path.splitext(os.path.basename(rel))[0])


def name_fits(base, rel, parts):
    """الاسم المعتمد الحالي يطابق ما فُرز (النوع ورقم المحضر والمقدّم والتاريخ) — وإلا يُعاد تسميته ونقله."""
    folder, name, state, _q = decide(parts, os.path.splitext(rel)[1], _has_referral(base, exclude=rel))
    if state != 'sorted' or not name:
        return True                                 # لم يُحسم: لا يُنقل ملف اسمه معتمد إلى «أخرى»
    if folder != rel.split('/', 1)[0]:
        return False
    want, have = _stem(name), _stem(rel)
    if want == have:
        return True
    return want in ('صحيفة الدعوى', 'حكم') and have.startswith(want)   # «صحيفة الدعوى 9-28-2026» صحيفة معدّلة: يبقى


def apply(base, data, rel, parts, man, source='ai'):
    ext = os.path.splitext(rel)[1]
    folder, name, state, question = decide(parts, ext, _has_referral(base, exclude=rel))
    new_rel = rel
    if name:
        new_rel = cl.relocate(base, data, rel, f'{folder}/{name}', man)
    e = man['files'][new_rel]
    rec = {'sha1': e.get('sha1'), 'state': state, 'question': question, 'parts': parts, 'from': rel,
           'at': _now(), 'source': source}
    e['sort'] = rec
    log = data.setdefault('sort', {})
    log.setdefault('files', {}).pop(rel, None)
    log['files'][new_rel] = {k: rec[k] for k in ('state', 'question', 'from', 'at', 'source')} | {
        'parts': [{k: p.get(k) for k in ('type', 'label', 'date', 'minute_no', 'pages')} for p in parts]}
    return dict(rec, file=new_rel)


def run(base, data, ask, stop=None, on_file=None, only=None):
    """يفرز كل ما يحتاج فرزاً (المرحلة الأولى: ملف لم تتغير بصمته لا يُعاد). بلا مزوّد (ask=None) ← ما حمل فرزه من طلب
    التحويل يُفرز، والباقي يبقى في «أخرى» بلا سؤال حتى يتوفر. يرجع ملخصاً."""
    import case_triage as ct
    man = cf.load_manifest(base)
    # الصحيفة أولاً (أطراف القضية وجنسهم لبقية الملفات)، ثم الحكم، ثم الباقي
    first = {cf.PLAINT: 0, cf.JUDGMENT: 1}
    todo = sorted(ct.pending(base, man, data), key=lambda r: (first.get(cf.kind_of(r), 2), r))
    if only is not None:                              # إعادة قراءة ملف بعينه
        todo = [r for r in todo if r in only]
    done, errors = [], []
    if ask is None:
        todo = [r for r in todo if (man['files'][r].get('triage_raw') or {}).get('sha1') == man['files'][r].get('sha1')]
        if not todo:
            return {'todo': len(ct.pending(base, man, data)), 'sorted': [], 'errors': [],
                    'skipped': 'لا مزوّد ذكاء متاح للفرز'}
    for i, rel in enumerate(todo):
        if stop and stop():
            break
        if on_file:
            on_file(rel, i, len(todo))
        try:
            rec = sort_file(base, data, rel, ask, man)
            if rec:
                done.append(rec)
        except Exception as e:
            if cf.is_key_failure(e):               # مفتاحك الشخصي فشل: يتوقف الفرز (لا خطأ لكل ملف)
                cf.save_manifest(base, man)
                raise
            errors.append((rel, str(e) or e.__class__.__name__))
            data.setdefault('sort', {}).setdefault('errors', {})[rel] = str(e)
            ent = man['files'].get(rel) or {}             # يُسجَّل ببصمته: لا يُعاد الطلب عند كل فتح (يُحدَّد يدوياً)
            ent['triage'] = {'sha1': ent.get('sha1'), 'source': 'request', 'parts': [], 'error': str(e), 'at': _now(),
                             'v': ct.VERSION}
            write_header(base, man, rel)
            if not is_canonical(rel):
                data['sort'].setdefault('files', {})[rel] = {
                    'state': 'unresolved', 'from': rel, 'at': _now(), 'source': 'ai', 'parts': [],
                    'question': f'تعذّر فرزه آلياً ({str(e) or e.__class__.__name__}): حدّد نوعه ومقدّمه وتاريخه'}
        cf.save_manifest(base, man)
    try:
        if renumber_minutes(base, data, man):
            todo = todo or ['*']
    except Exception as e:                            # الترقيم تحسين؛ فشله لا يوقف الفرز
        data.setdefault('sort', {}).setdefault('errors', {})['ترقيم المحاضر'] = str(e)
    if todo:
        cf.save_manifest(base, man)
    data.setdefault('sort', {})['at'] = _now()
    return {'todo': len(todo), 'sorted': done, 'errors': errors}


# ---------- إعادة الفرز من markdown (بلا OCR) بطلبات مجمّعة (2026-10-25) ----------

def retriage_items(base, man=None, rels=None):
    """[(rel، النص)] للأصول المحوَّلة القابلة لإعادة الفرز من markdown الموجود (ما حدّده الخبير يدوياً لا يُمسّ)."""
    man = man or cf.load_manifest(base)
    out = []
    for rel, e in sorted(man['files'].items()):
        if rels is not None and rel not in rels:
            continue
        if e.get('state') != 'done' or not os.path.exists(os.path.join(base, rel)):
            continue
        s = e.get('sort') or {}
        if s.get('state') == 'manual' and s.get('sha1') == e.get('sha1'):
            continue
        md = _read_md(base, e, rel)
        if md.strip():
            out.append((rel, md))
    return out


def retriage_plan(base, rels=None, limit=None):
    """(عدد الملفات، عدد الطلبات المتوقع) لإعادة الفرز — لرسالة التأكيد قبل «إعادة فرز الكل»."""
    import ai_providers
    import case_triage as ct
    items = retriage_items(base, rels=rels)
    limit = limit or ai_providers.triage_batch_chars()
    return len(items), len(ct.plan_batches([(r, r, t) for r, t in items], limit))


def retriage(base, data, ask, rels=None, limit=None, stop=None, on_batch=None):
    """يعيد فرز الأصول من markdown الموجود (بلا تحويل ولا OCR): الملفات تُجمع في طلب واحد لكل ~limit حرفاً (Lite/Flash —
    مهمة الفرز)، وكل ملف يُعلَّم بمعرّف في الطلب؛ التحقق الحرفي (case_triage.verify) بالكود على نص كل ملف على حدة، ثم التسمية
    والنقل والرأس كما في الفرز العادي. يرجع {'files','requests','sorted','errors'}."""
    import ai_call_log
    import ai_providers
    import case_triage as ct
    if ask is None:
        raise ValueError('لا مزوّد ذكاء متاح للفرز')
    man = cf.load_manifest(base)
    first = {cf.PLAINT: 0, cf.JUDGMENT: 1}
    items = sorted(retriage_items(base, man, rels), key=lambda x: (first.get(cf.kind_of(x[0]), 2), x[0]))
    named = [(f'F{i}', rel, md) for i, (rel, md) in enumerate(items, 1)]
    batches = ct.plan_batches(named, limit or ai_providers.triage_batch_chars())
    done, errors = [], []
    for bi, batch in enumerate(batches):
        if stop and stop():
            break
        if on_batch:
            on_batch(bi, len(batches), [rel for _f, rel, _t in batch])
        ai_call_log.detail(f'إعادة فرز مجمّعة — الدفعة {bi + 1} من {len(batches)} ({len(batch)} ملف): '
                           + '، '.join(os.path.basename(rel) for _f, rel, _t in batch)[:200])
        try:
            got = ct.split_batch(ask(ct.batch_prompt(data, [(f, os.path.basename(rel), t) for f, rel, t in batch])),
                                 [f for f, _r, _t in batch])
        except Exception as e:
            if cf.is_key_failure(e):
                cf.save_manifest(base, man)
                raise
            ai_call_log.verdict(False, str(e) or e.__class__.__name__)
            errors += [(rel, str(e) or e.__class__.__name__) for _f, rel, _t in batch]
            continue
        kept = 0
        for fid, rel, md in batch:
            raw = got.get(fid)
            if raw is None:
                errors.append((rel, 'لم يُذكر الملف في ردّ الفرز المجمّع'))
                continue
            e = man['files'][rel]
            parts, notes = ct.verify(data, raw, md)          # التحقق الحرفي على نص هذا الملف وحده
            ct.store(e, parts, notes, 'batch', raw)
            done.append(_place(base, data, rel, parts, man, md))
            kept += 1
        ai_call_log.verdict(kept == len(batch), f'{kept} من {len(batch)} ملفاً فُرز وتحقق' if kept else 'لا ملف في الرد')
        cf.save_manifest(base, man)
    try:
        renumber_minutes(base, data, man)
    except Exception as e:
        data.setdefault('sort', {}).setdefault('errors', {})['ترقيم المحاضر'] = str(e)
    cf.save_manifest(base, man)
    data.setdefault('sort', {})['at'] = _now()
    return {'files': len(items), 'requests': len(batches), 'sorted': done, 'errors': errors}


def renumber_minutes(base, data, man):
    """محضران بالرقم نفسه في نصّيهما (خطأ في المحضر نفسه): الأقدم تاريخاً يبقى برقمه، والتالي يأخذ أول رقم شاغر بعد
    سابقه — فتصير المحاضر 1 و2 و3 بترتيب تواريخها. ثم «محضر الخبرة رقم N (2)» يأخذ «رقم N» إن صار شاغراً.
    يرجع [(من، إلى)]. يُسجَّل الرقم الأصلي في الجزء (renumbered_from)."""
    import case_triage as ct
    recs = []
    for rel, e in man['files'].items():
        if not rel.startswith(cf.SYSDOCS + '/') or e.get('state') != 'done' or not ct.done(e):
            continue
        p = next((x for x in (e['triage'].get('parts') or []) if x.get('type') == T_MIN), None)
        if p is None or p.get('minute_no') is None:
            continue
        d = re.fullmatch(r'(\d{2})-(\d{2})-(\d{4})', p.get('date') or '')
        recs.append(((d.group(3) + d.group(2) + d.group(1)) if d else '99999999', int(p['minute_no']), rel, p))
    moves = []
    nums = [r[1] for r in recs]
    if len(nums) != len(set(nums)):
        declared, used, prev = set(nums), set(), 0
        for _d, n, rel, p in sorted(recs):
            want = n
            if n in used or n <= prev:
                want = prev + 1
                while want in used or (want in declared and want != n):
                    want += 1
            used.add(want)
            prev = want
            if want != n:
                p['renumbered_from'], p['minute_no'] = n, want
    cur = {id(p): rel for _d, _n, rel, p in recs}
    for _round in range(3):                       # جولتان تكفيان: «رقم 1» يُخلي مكانه ثم تأخذه «رقم 1 (2)»
        moved = False
        for _d, n, _rel, p in sorted(recs):
            rel = cur[id(p)]
            want = cf.minute_name(p['minute_no']) + os.path.splitext(rel)[1]
            if os.path.basename(rel) != want and not os.path.exists(os.path.join(base, cf.SYSDOCS, want)):
                new = cl.relocate(base, data, rel, f'{cf.SYSDOCS}/{want}', man)
                moves.append((rel, new))
                cur[id(p)] = new
                moved = True
        if not moved:
            break
    return moves


def questions(data):
    """[(الملف، السؤال)] لما لم يُحسم — سطر أحمر لكل ملف بسؤال واحد."""
    return [(rel, f['question']) for rel, f in sorted(((data.get('sort') or {}).get('files') or {}).items())
            if f.get('state') == 'unresolved' and f.get('question')]


def answer(base, data, rel, type_, role='', index=1, date='', minute_no=None):
    """جواب الخبير عن سؤال الفرز: يُطبَّق القرار نفسه (مصدره «الخبير»)."""
    man = cf.load_manifest(base)
    part = {'type': type_ if type_ in TYPES else T_OTHER, 'role': role if role in ROLES else '', 'index': index,
            'label': role_label(data, role, index, _read_md(base, man['files'].get(rel) or {}, rel)) if role in ROLES else '',
            'date': _dmy(date) or date, 'minute_no': minute_no, 'referral': False, 'pages': [], 'notes': [],
            'contract': {}, 'as_written': ''}
    rec = apply(base, data, rel, [part], man, source='manual')
    if rec['state'] == 'sorted':
        man['files'][rec['file']]['sort']['state'] = 'manual'
        data['sort']['files'][rec['file']]['state'] = 'manual'
    write_header(base, man, rec['file'])
    cf.save_manifest(base, man)
    return rec
