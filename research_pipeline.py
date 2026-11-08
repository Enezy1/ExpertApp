# ===== research_pipeline.py — «البحث ورأي الخبرة» بأسلوب الخبير: محوراً محوراً وعقداً عقداً (2026-10-20) =====
# (أ) المدخلات: بنود المأمورية حرفياً (mission.points)، فهرس العقود المصنَّف (case_contracts)، markdown المستندات،
#     وقائع المحاضر (ما طلبته الخبرة من الأطراف وما قدّموه)، مذكرات الدفاع.
# (ب) التقسيم: المحاور = البنود المتتالية من النوع نفسه (علاقة/إخلال/حساب/اعتراضات/عام) بعنوان «أولاً: …:» كما في تقارير
#     الخبير؛ داخل المحور قسم لكل عقد بين طرفي الدعوى يُرسل بمستندات ذلك العقد وحده (+العامة) فلا يختلط عقد بآخر.
#     العقد الرئيسي والعقود خارج نطاق الدعوى سياق فقط بوسم واضح. عقد واحد = قسم واحد.
# (ج) المرحلة 1: حقائق JSON (تاريخ، مبلغ، مصدر، صفحة، اقتباس حرفي) ← الكود يتحقق أن كل اقتباس وتاريخ ومبلغ وارد حرفياً
#     في markdown المصدر؛ ما لم يتحقق يُحذف ويُسجَّل ملاحظة حمراء.
# (د) الحساب بالكود فقط (calc.py، Decimal) والأرقام بالحروف (amounts.to_words)؛ كل مجموع يُقارن بما في مستندات المدعية
#     وأي فرق ولو فلساً ← «قرارات تحتاج مراجعة». تحويل العملة بسعر وتاريخ يحددهما الخبير (set_fx).
# (هـ) المرحلة 2: طلب صياغة لكل قسم بقواعد نماذج_صياغة_البحث.md والنماذج المطابقة والحقائق والأرقام الجاهزة؛ ثم يتحقق الكود
#     أن كل رقم في الناتج من الأرقام الجاهزة (رقم غريب ← رفض وإعادة مرة واحدة)، ويزيل الرموز الداخلية والعبارات الممنوعة.
# (و) لا يبدأ محور إلا إذا كانت بنوده «جاهزة» في case_readiness (أو «اكتب رغم النقص» صراحة)؛ لا أرقام ناقصة.
# (ز) الإخراج: 04_تقرير/بحث/*.md (مسودة كل قسم للمعاينة) ← «دمج» ← 04_تقرير/البحث.md، والملاحظات الحمراء منفصلة في
#     04_تقرير/ملاحظات_البحث.md وcase.json['research2']؛ report_docx يدمج النص المدموج فقط.
# التسليم: api (جيميناي افتراضياً عبر مهمة research) | file (prompt.md لنموذج الخبير ثم استيراد الرد) | copilot (مثله للصق).
import hashlib
import json
import os
import re
from datetime import datetime
from decimal import Decimal

import amounts
import calc
import case_model as cm
import case_workspace as cw

DIR_REL = '_نظام/04_تقرير/بحث'
TEXT_REL = '_نظام/04_تقرير/البحث.md'
NOTES_REL = '_نظام/04_تقرير/ملاحظات_البحث.md'
PROMPT_REL = 'التقرير/prompt.md'           # يفتحه الخبير (Copilot/ملف): خارج _نظام المخفي
ORDINALS = ('أولاً', 'ثانياً', 'ثالثاً', 'رابعاً', 'خامساً', 'سادساً', 'سابعاً', 'ثامناً', 'تاسعاً', 'عاشراً',
            'حادي عشر', 'ثاني عشر')
K_REL, K_BREACH, K_CALC, K_DEF, K_GEN = 'علاقة', 'إخلال', 'حساب', 'اعتراضات', 'عام'
S_PENDING, S_BLOCKED, S_FACTS, S_DRAFTED, S_MERGED, S_FAILED = 'pending', 'blocked', 'facts', 'drafted', 'merged', 'failed'
STATE_TEXT = {S_PENDING: 'لم يُكتب', S_BLOCKED: 'بانتظار مستند', S_FACTS: 'الحقائق جاهزة', S_DRAFTED: 'مسودة للمعاينة',
              S_MERGED: 'مدموج في البحث', S_FAILED: 'تعذّر'}
PROGRESS = {S_PENDING: 0, S_BLOCKED: 0, S_FAILED: 0, S_FACTS: 50, S_DRAFTED: 90, S_MERGED: 100}
N_MISSING, N_DECISION, N_DIFF, N_REMOVED = 'ناقص', 'قرار يحتاج مراجعة الخبير', 'فرق أرقام', 'حُذف لعدم التحقق'
N_DEDUP = 'حُذف تكرار'                    # جملة مكررة (تشابه ≥ 95%) حذفها الكود — report_audit.dedupe
DELIVERY = ('api', 'file', 'copilot')
MAX_SECTION_CHARS = 120_000
MARK = '===القسم {key}==='
CONCL_MARK = '===النتيجة==='
MINUTE_TEXTS = None                       # الاختبارات تستبدله: fn(minutes) -> {path: [فقرات]}
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _sha(obj):
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def _norm(t):
    return ' '.join(amounts.norm(str(t or '').translate(_DIGITS)).replace('ـ', '').split())


def state(data):
    return data.setdefault('research2', {'version': 1, 'axes': [], 'decisions': {}, 'delivery': 'api', 'minutes': {}})


# ---------- (ب) المحاور من بنود المأمورية ----------
_CALC_STRONG = ('تصفيه', 'حساب')
_DEF_KW = ('اعتراض', 'دفاع', 'دفوع')
_BREACH_KW = ('اخل', 'المخل', 'اوفي', 'التزم', 'تنفيذ', 'نفذ', 'كميات', 'كميه', 'استلام', 'النتايج', 'مطابق',
              'المواصفات', 'تاخير', 'تاخر', 'منجز', 'انجاز', 'عيوب', 'معاينه')
_CALC_KW = ('المبالغ', 'مبلغ', 'المستحق', 'مستحقات', 'سدد', 'ترصد', 'ذمه', 'اضرار', 'الاضرار', 'تعويض', 'غرام',
            'قيمه', 'مديونيه', 'الدفعات')


def classify_point(text):
    """نوع البند بالكلمات (بلا ذكاء): حساب ← اعتراضات ← علاقة ← إخلال ← حساب ضعيف ← عام."""
    n = _norm(text)
    if any(k in n for k in _CALC_STRONG):
        return K_CALC
    if any(k in n for k in _DEF_KW):
        return K_DEF
    if 'علاقه' in n or ('التزامات' in n and 'كل' in n) or 'حقوق' in n:
        return K_REL
    if any(k in n for k in _BREACH_KW):
        return K_BREACH
    if any(k in n for k in _CALC_KW):
        return K_CALC
    return K_GEN


_CLAUSE_SPLIT = re.compile(r'(?<=\S)\s+(?=و(?:بيان|تحديد|حساب|احتساب|معرفة|بحث|تصفية|تقدير|مطابقة|عما|عن|هل)\b)')


def mission_clauses(points):
    """بنود المأمورية كجمل مستقلة: البند الطويل الذي يضم عدة طلبات («… وبيان … وحساب …») يُقسَّم عند واو العطف قبل
    فعل الطلب، فلا يُكتب نص المأمورية كاملاً عنواناً لمحور واحد. المعرّف الأصلي يبقى للجاهزية."""
    out = []
    for p in points:
        text = ' '.join(str(p['text']).split())
        parts = [x for x in _CLAUSE_SPLIT.split(text) if x.strip()] if len(text) > 110 else [text]
        for k, part in enumerate(parts):
            out.append(dict(p, text=part, cid=p['id'] if len(parts) == 1 else f"{p['id']}.{k + 1}"))
    return out


def group_points(points):
    """[(نوع، [بنود])] — البنود المتتالية من النوع نفسه محور واحد، والترتيب كما في المأمورية."""
    out = []
    for p in points:
        k = classify_point(p['text'])
        if out and out[-1][0] == k and k != K_GEN:
            out[-1][1].append(p)
        else:
            out.append((k, [p]))
    return out


def axis_title(points):
    """عنوان المحور كما في تقارير الخبير: نص البنود متصلاً («لبيان … وبيان …»)."""
    parts = [re.sub(r'[\s،,.:؛]+$', '', ' '.join(p['text'].split())) for p in points]
    return '، '.join(x for x in parts if x)


def heading(axis):
    return f"{axis['ordinal']}: {axis['title']}:"


# ---------- الأطراف والعقود ----------

def party_labels(data):
    """{'plaintiff': 'المدعية', 'defendants': ['المدعى عليها الأولى', …]} بالصفات لا بالأسماء."""
    import case_attachments as ca
    import case_procedures as cp
    res = ((data.get('procedures') or {}).get('attendance') or {}).get('result') or []
    if res:
        labs = cp.party_labels(res, data)
        pl = next((l for r, (l, _f) in zip(res, labs) if r['role'] == 'plaintiff'), '')
        dfs = [l for r, (l, _f) in zip(res, labs) if r['role'] != 'plaintiff']
        strip = lambda s: s.replace('الشركة ', '', 1)            # noqa: E731
        if pl or dfs:
            return {'plaintiff': strip(pl) or ca._side_label(data, 'plaintiff'), 'defendants': [strip(x) for x in dfs]
                    or [ca._side_label(data, 'defendant')]}
    c = data.get('case') or {}
    defs = [d for d in c.get('defendants') or [] if d]
    if len(defs) > 1:
        out = []
        for i, name in enumerate(defs):
            f = cp._is_company(name)
            base = 'المدعى عليها' if f else 'المدعى عليه'
            o = cp._ORD_M[i] if i < len(cp._ORD_M) else str(i + 1)
            out.append(f"{base} {('الأولى' if i == 0 else o + 'ة') if f else o}")
        return {'plaintiff': ca._side_label(data, 'plaintiff'), 'defendants': out}
    return {'plaintiff': ca._side_label(data, 'plaintiff'), 'defendants': [ca._side_label(data, 'defendant')]}


def _party_label(name, data, labels):
    import case_contracts as cc
    pl, _df = cc.litigants(data)
    if cc._matches(name, pl):
        return labels['plaintiff']
    defs = [d for d in (data.get('case') or {}).get('defendants') or [] if d]
    for i, d in enumerate(defs):
        if cc._matches(name, [d]) and i < len(labels['defendants']):
            return labels['defendants'][i]
    if cc._matches(name, _df):
        return labels['defendants'][0]
    return ''


_KIND_LABEL = {'عقد رئيسي': 'العقد', 'عقد بين الطرفين': 'العقد', 'ملحق': 'ملحق العقد', 'أمر شراء': 'أمر الشراء',
               'أمر تغيير': 'الأمر التغييري'}
_REF_RE = re.compile(r'(?:عقد|العقد|الخط|خط|حساب|الحساب|اشتراك|الاشتراك|طلب|امر\s*شراء|أمر\s*شراء|رقم)\s*(?:رقم)?\s*[:(\[]?\s*'
                     r'([A-Za-z]{0,6}[\d][\dA-Za-z./\\-]{3,})')
_STOP = {'شركه', 'شركة', 'المدعيه', 'المدعي', 'عليه', 'عليها', 'المدعى', 'ذمم', 'لاعمال', 'للتجاره', 'العامه',
         'التجاريه', 'والمقاولات', 'المحدوده', 'الكويت', 'كويت', 'السيد', 'السيده'}


def contract_number(c, own_text=''):
    """رقم العقد/الخط إن ورد (من الملخص/النطاق ثم صفحة العقد نفسها)."""
    for src in (' '.join(str(c.get(k) or '') for k in ('summary', 'scope_of_work', 'raw_ref')), own_text):
        m = _REF_RE.search(str(src or '').translate(_DIGITS))
        if m and sum(ch.isdigit() for ch in m.group(1)) >= 4:
            return m.group(1).strip('./\\-')
    return ''


def contract_groups(data, docs_by_file=None):
    """العقود بين طرفي الدعوى مجمّعة: الملحق/الأمر التغييري مع عقده الأسبق، والبقية عقد مستقل.
    يرجع [{'key','title','main','members','files','ids'}] بالترتيب الزمني. والسياق (رئيسي/خارجي) منفصل."""
    import case_contracts as cc
    labels = party_labels(data)
    recs = cc.items(data, cc.SCOPE_IN)

    def dkey(c):
        m = re.findall(r'\d+', str(c.get('date') or '').translate(_DIGITS))
        if len(m) == 3:
            d, mo, y = (int(x) for x in m) if len(m[2]) == 4 else (int(m[2]), int(m[1]), int(m[0]))
            return (y, mo, d)
        return (9999, 0, 0)
    recs = sorted(recs, key=dkey)
    groups = []
    for c in recs:
        if c.get('kind') in ('ملحق', 'أمر تغيير') and groups:
            prev = [g for g in groups if dkey(g['main']) <= dkey(c)] or groups
            prev[-1]['members'].append(c)
            continue
        groups.append({'main': c, 'members': [c]})
    docs_by_file = docs_by_file or {}
    for g in groups:
        c = g['main']
        own = '\n'.join(t for _n, t in (docs_by_file.get(c.get('file')) or {}).get('pages') or [])
        num = contract_number(c, own)
        names = [x for x in (_party_label(p, data, labels) for p in c.get('parties') or []) if x]
        label = _KIND_LABEL.get(c.get('kind'), 'العقد')
        title = label + (f' رقم ({num})' if num else '') + (f" المؤرخ {c['date']}" if c.get('date') else '')
        if len(names) >= 2:
            title += f" بين {names[0]} و{names[1]}"
        g.update(key=hashlib.sha1(f"{c.get('kind')}|{c.get('date')}|{c.get('file')}|{c.get('page')}".encode('utf-8'))
                 .hexdigest()[:8], title=title, number=num,
                 files=sorted({m.get('file') for m in g['members'] if m.get('file')}))
    _assign_ids(groups)
    return groups


def _date_variants(d):
    m = re.findall(r'\d+', str(d or '').translate(_DIGITS))
    if len(m) != 3:
        return []
    a, b, c = (x.lstrip('0') or '0' for x in m)
    return [rf'(?<!\d)0*{a}\s*[/\-.\\]\s*0*{b}\s*[/\-.\\]\s*0*{c}(?!\d)', rf'(?<!\d)0*{c}\s*[/\-.\\]\s*0*{b}\s*[/\-.\\]\s*0*{a}(?!\d)']


def _assign_ids(groups):
    """معرّفات كل عقد للتعرّف على صفحاته: رقمه، كلمات أطرافه التي لا يشاركه فيها عقد آخر، وتاريخه إن تفرّد."""
    import case_contracts as cc
    toks = []
    for g in groups:
        ws = set()
        for m in g['members']:
            for p in m.get('parties') or []:
                ws |= {w for w in cc._tokens(p) if len(w) >= 3 and w not in _STOP}
        toks.append(ws)
    dates = [g['main'].get('date') for g in groups]
    for i, g in enumerate(groups):
        others = set().union(*(t for j, t in enumerate(toks) if j != i)) if len(groups) > 1 else set()
        ids = {'numbers': [], 'words': sorted(toks[i] - others) if len(groups) > 1 else [], 'dates': []}
        if g.get('number'):
            ids['numbers'].append(g['number'])
        for m in g['members']:
            ids['numbers'] += re.findall(r'\d{5,}', ' '.join(str(m.get(k) or '') for k in ('summary', 'scope_of_work'))
                                         .translate(_DIGITS))
        ids['numbers'] = sorted(set(ids['numbers']))
        if len(groups) > 1 and dates.count(g['main'].get('date')) == 1:
            ids['dates'] = _date_variants(g['main'].get('date'))
        g['ids'] = ids


def _hits(text, ids):
    t = str(text or '').translate(_DIGITS)
    if any(n and n in t for n in ids['numbers']):
        return True
    if any(re.search(p, t) for p in ids['dates']):
        return True
    nt = set(_norm(t).split())
    return bool(ids['words']) and any(w in nt for w in ids['words'])


# ---------- المستندات بمراجع الخبير ----------

def _dmy(d):
    m = re.findall(r'\d+', str(d or '').translate(_DIGITS))
    if len(m) != 3:
        return str(d or '').strip()
    if len(m[0]) == 4:
        m = [m[2], m[1], m[0]]
    return f'{int(m[0])}/{int(m[1])}/{m[2]}'


def _side_of(text, data):
    import case_attachments as ca
    import case_documents as cd
    who = cd.clean_submitter(text)
    n = _norm(who)
    if re.search(r'المدع(?:ي|ى)\s*علي', n) and re.search(r'الاول|الثاني|الثالث|الرابع', n):
        return re.sub(r'^(?:حافظ[ةه]\s+(?:ال)?مستندات\s+|مذكر[ةه]\s+(?:ال)?دفاع\s+)', '', who).strip()
    role = ca._role_of(who)
    return ca._side_label(data, role) if role else ''


def _read(base, rel):
    """نص ملف markdown بلا رأس نوع المستند (doc_header): الرأس لا يدخل نصوص المستندات ولا بصمتها."""
    import doc_header
    try:
        import case_memory
        raw, _ = case_memory._read_text(base, rel)
        return doc_header.strip(case_memory._dec(raw)) if raw is not None else ''
    except Exception:
        try:
            with open(os.path.join(base, rel), encoding='utf-8') as f:
                return doc_header.strip(f.read())
        except OSError:
            return ''


def is_minutes_doc(d, text):
    """محضر الخبرة وإن سُجّل خطأً حافظةً في قائمة المستندات (أُضيف من نافذة المستندات وصنّفته الكلمات المفتاحية): ملفه في
    مستندات_النظام باسم «محضر…»، أو نصه يبدأ بافتتاحية المحضر. المحاضر لا تدخل البحث مستنداً (لها خطوة الإجراءات)."""
    import case_folder as cf
    import doc_router
    return cf.kind_of(d.get('file') or '') == cf.MINUTES or doc_router.is_minutes_text(text)


def documents(base, data):
    """كل مستند محوَّل (عدا المحاضر) بمرجعه بصيغة الخبير. [{code, file, kind, side, date, cite, memo, pages, face}]."""
    import case_documents as cd
    import case_folder as cf
    import case_readiness as cr
    import case_contracts as cc
    out, seen = [], set()
    for p, d in cd.content_docs(data):
        if (d.get('convert') or {}).get('state') != 'done' or not d.get('md'):
            continue
        text = _read(base, d['md'])
        if not text.strip():
            continue
        dt = (d.get('doc_type') or d.get('type') or '')
        memo = 'مذكر' in dt
        if 'محضر' in dt or is_minutes_doc(d, text):
            seen.add(d.get('file'))              # لا يعود من قائمة المجلد «مستنداً» (A2263970: «أخرى/3 محضر.pdf»)
            continue
        side = _side_of(p.get('submitter') or '', data)
        date = _dmy(d.get('doc_date') or p.get('date') or '')
        multi = len(p.get('docs') or []) > 1
        if memo:
            cite = f"(مذكرة دفاع {side} المؤرخة {date})" if side else f"(مذكرة دفاع المؤرخة {date})"
            kind = 'مذكرة دفاع'
        else:
            kind = 'حافظة مستندات'
            cite = (f"مرفق بحافظة مستندات {side} المؤرخة {date}" if side else f"مرفق بحافظة المستندات المؤرخة {date}")
            suffix = f" مستند {d['no']}" if multi and d.get('no') else ''
            cite = f"({cite}{suffix})"
        seen.add(d.get('file'))
        out.append({'file': d.get('file') or d['md'], 'md': d['md'], 'kind': kind, 'side': side, 'date': date,
                    'cite': cite, 'memo': memo, 'multi': multi, 'pages': cr.split_pages(text),
                    'face': [] if memo or multi else cc.face_rows(text)})
    folder_kind = {cf.PLAINT: ('صحيفة الدعوى', '(صحيفة الدعوى)'), cf.JUDGMENT: ('حكم الإحالة', '(حكم الإحالة)'),
                   cf.PRIOR: ('تقرير خبرة سابق', '(تقرير الخبرة السابق)'),
                   cf.OTHER: ('مستند', '(مستند مقدم بملف الدعوى)'),
                   cf.PORTFOLIO: ('مستند', '(مستند مقدم بملف الدعوى)'),
                   cf.DEFENSE: ('مذكرة', '(مذكرة مقدمة بملف الدعوى)')}
    try:
        man = cf.load_manifest(base)['files']
    except Exception:
        man = {}
    for rel, e in sorted(man.items()):
        top = cf.kind_of(rel)
        if e.get('state') != 'done' or rel in seen or top == cf.MINUTES or top not in folder_kind:
            continue
        text = _read(base, e.get('md') or cf.md_rel(rel))
        if not text.strip():
            continue
        if is_minutes_doc({'file': rel}, text):
            continue
        kind, cite = folder_kind[top]
        import doc_header                        # المقدّم والتاريخ من رأس نوع المستند (بالكود، بلا طلب)
        h = doc_header.read(base, e.get('md') or cf.md_rel(rel))
        h = h if h.get('sha1') == e.get('sha1') else {}
        side, date = _side_of(h.get('by') or '', data) or (h.get('by') or ''), (h.get('date') or '').replace('-', '/')
        memo = False
        if top == cf.PORTFOLIO and not is_minutes_doc({'file': rel}, text):     # مجلد الحوافظ = حافظة مستندات (2026-10-25:
            kind = 'حافظة مستندات'                                              # كانت «مستند مقدم بملف الدعوى» بلا مقدّم
            cite = (f"(مرفق بحافظة مستندات {side} المؤرخة {date})" if side else   # ولا تاريخ ولا رقم مستند)
                    f"(مرفق بحافظة المستندات المؤرخة {date})")
        elif top == cf.DEFENSE:
            kind, memo = 'مذكرة دفاع', True
            cite = f"(مذكرة دفاع {side} المؤرخة {date})" if side else f"(مذكرة دفاع المؤرخة {date})"
        out.append({'file': rel, 'md': e.get('md') or cf.md_rel(rel), 'kind': kind, 'side': side,
                    'date': date, 'cite': cite,
                    'memo': memo, 'multi': False, 'pages': cr.split_pages(text), 'face': []})
    for i, d in enumerate(out, 1):
        d['code'] = f'D{i}'
    return out


def minutes(base, data):
    """[{ref, file, no, date, text, cite}] لمحاضر القضية المقروءة."""
    rows = (data.get('sessions') or {}).get('minutes') or []
    recs = [{'path': r.get('file') or r.get('path'), 'name': r.get('name') or ''} for r in rows if r.get('file') or r.get('path')]
    if not recs:
        return []
    fn = MINUTE_TEXTS
    if fn is None:
        import case_procedures as cp
        fn = cp.minute_texts
    texts = fn(recs)
    out = []
    for i, (r, rec) in enumerate(zip(rows, recs), 1):
        t = '\n'.join(texts.get(rec['path']) or [])
        if not t.strip():
            continue
        date = _dmy(r.get('date') or r.get('text_date') or '')
        cite = f"(محضر أعمال الخبرة المؤرخ {date})" if date else (f"(محضر الأعمال رقم {r['no']})" if r.get('no') else
                                                                    '(محاضر أعمال الخبرة)')
        out.append({'ref': f'M{i}', 'file': rec['path'], 'no': r.get('no'), 'date': date, 'text': t, 'cite': cite})
    return out


# ---------- توزيع الصفحات على العقود ----------

def assign_pages(docs, groups):
    """{group_key: [(doc, [(n, نص)])]}، general: [(doc, صفحات)]، memos: [(doc, صفحات)].
    صفحة فيها معرّف عقد ← لذلك العقد فقط؛ ملف العقد نفسه ← لعقده؛ صفحة بلا معرّف ← لعقد المستند الوحيد إن تفرّد، وإلا عامة."""
    by_g = {g['key']: [] for g in groups}
    general, memos = [], []
    own = {f: g['key'] for g in groups for f in g['files']}
    for d in docs:
        if d['memo']:
            memos.append((d, d['pages']))
            continue
        if d['file'] in own:
            by_g[own[d['file']]].append((d, d['pages']))
            continue
        if not groups:
            general.append((d, d['pages']))
            continue
        page_hits = [(n, t, {g['key'] for g in groups if _hits(t, g['ids'])}) for n, t in d['pages']]
        doc_hits = set().union(*(h for _n, _t, h in page_hits)) if page_hits else set()
        per = {k: [] for k in doc_hits}
        gen = []
        for n, t, h in page_hits:
            if h:
                for k in h:
                    per[k].append((n, t))
            elif len(doc_hits) == 1:
                per[next(iter(doc_hits))].append((n, t))
            else:
                gen.append((n, t))
        for k, pages in per.items():
            if pages:
                by_g[k].append((d, pages))
        if gen:
            general.append((d, gen))
    return by_g, general, memos


# ---------- الخطة ----------

def build_plan(base, data):
    """يبني/يحدّث المحاور والأقسام ويحفظ ما كُتب سابقاً للمفتاح نفسه. يرجع research2."""
    r = state(data)
    points = (data.get('mission') or {}).get('points') or []
    docs = documents(base, data)
    groups = contract_groups(data, {d['file']: d for d in docs})
    old = {s['key']: s for a in r.get('axes') or [] for s in a.get('sections') or []}
    has_memos = any(d['memo'] for d in docs)
    grouped = group_points(mission_clauses(points))
    has_def_axis = any(k == K_DEF for k, _ in grouped)
    axes = []
    for i, (kind, pts) in enumerate(grouped):
        akey = 'A' + '-'.join(str(p.get('cid') or p['id']) for p in pts)
        ordinal = ORDINALS[i] if i < len(ORDINALS) else f'{i + 1}'
        secs = []
        if kind == K_DEF:
            secs.append({'key': f'{akey}:def', 'title': '', 'kind': 'objections', 'contract': None})
        elif groups:
            for g in groups:
                secs.append({'key': f"{akey}:{g['key']}", 'title': g['title'] if len(groups) > 1 else '',
                             'contract_title': g['title'], 'kind': 'contract', 'contract': g['key']})
            if kind == K_CALC and len(groups) > 1:
                secs.append({'key': f'{akey}:total', 'title': 'تصفية الحساب الإجمالية', 'kind': 'total', 'contract': None})
        else:
            secs.append({'key': f'{akey}:all', 'title': '', 'kind': 'general', 'contract': None})
        if i == len(grouped) - 1 and has_memos and not has_def_axis:
            secs.append({'key': f'{akey}:obj', 'title': '', 'kind': 'objections', 'contract': None})
        for s in secs:
            prev = old.get(s['key'])
            if prev:
                prev.update({k: v for k, v in s.items() if k in ('title', 'contract_title', 'kind', 'contract')})
                s.clear()
                s.update(prev)
            else:
                s.update(state=S_PENDING, progress=0, message='', file='', notes=[], facts=None, calc=None,
                         allowed=[], edited=False)
        axes.append({'key': akey, 'ordinal': ordinal, 'kind': kind, 'title': axis_title(pts),
                     'point_ids': list(dict.fromkeys(p['id'] for p in pts)), 'sections': secs})
    r['axes'] = axes
    r['groups'] = [{'key': g['key'], 'title': g['title'], 'files': g['files'], 'ids': g['ids']} for g in groups]
    r['plan_at'] = _now()
    return r


def all_sections(data):
    return [(a, s) for a in state(data).get('axes') or [] for s in a['sections']]


def section(data, key):
    return next(((a, s) for a, s in all_sections(data) if s['key'] == key), (None, None))


def _note(sec, kind, text):
    if not any(n['type'] == kind and n['text'] == text for n in sec.setdefault('notes', [])):
        sec['notes'].append({'type': kind, 'text': text})


# ---------- (و) الجاهزية ----------

def axis_ready(data, axis):
    """(جاهز؟، [ما ينقص]) من case_readiness: كل بنود المحور «جاهزة»."""
    items = {r['id']: r for r in (data.get('readiness') or {}).get('items') or []}
    if not items:
        return False, ['لم يُفحص اكتمال المستندات بعد']
    miss = []
    for pid in axis['point_ids']:
        r = items.get(pid)
        if r is None:
            miss.append('لم يُفحص البند')
        elif r.get('state') != 'ready':
            miss += r.get('missing') or ['تعذّر فحص البند']
    return not miss, miss


# ---------- (ج) المرحلة 1: الحقائق ----------

def _section_inputs(base, data, axis, sec, cache=None):
    """(مستندات القسم [(doc, صفحات)]، المذكرات، سطور السياق، المحاضر)."""
    cache = cache if cache is not None else {}
    if 'docs' not in cache:
        cache['docs'] = documents(base, data)
        cache['groups'] = contract_groups(data, {d['file']: d for d in cache['docs']})
        cache['split'] = assign_pages(cache['docs'], cache['groups'])
        cache['minutes'] = minutes(base, data)
    by_g, general, memos = cache['split']
    if sec['kind'] == 'contract':
        docs = by_g.get(sec['contract'], []) + general
    elif sec['kind'] == 'objections':
        docs = [(d, p) for d, p in general] + [x for v in by_g.values() for x in v]
    else:
        docs = general + [x for v in by_g.values() for x in v]
    return _merge_docs(docs), (memos if sec['kind'] == 'objections' else []), context_lines(data), cache['minutes']


def _merge_docs(docs):
    """المستند الوارد أكثر من مرة (صفحة عقده + صفحته العامة) كتلة واحدة بصفحاته مرتبة، بترتيب المستندات الأصلي."""
    order, pages = [], {}
    for d, p in docs:
        if d['code'] not in pages:
            order.append(d)
            pages[d['code']] = {}
        pages[d['code']].update(dict(p))
    order.sort(key=lambda d: int(d['code'][1:]))
    return [(d, sorted(pages[d['code']].items())) for d in order]


def context_lines(data):
    """العقد الرئيسي والعقود خارج نطاق الدعوى: سياق فقط بوسم واضح (المتحقَّق منه فقط)."""
    import case_contracts as cc
    out = []
    for c in cc.items(data):
        if c['scope'] == cc.SCOPE_IN or not c.get('verified'):
            continue
        bits = [f"[سياق فقط — {c['scope']}]", c['kind'], f"مؤرخ {c['date']}" if c.get('date') else '',
                f"بين {' و'.join(c['parties'])}" if c.get('parties') else '', c.get('summary') or c.get('scope_of_work') or '',
                f"بقيمة {c['value']}" if c.get('value') and (c.get('checks') or {}).get('value') else '']
        out.append(' '.join(b for b in bits if b))
    return out


def _doc_block(d, pages, budget):
    body = '\n'.join(f'<!-- صفحة {n} -->\n{t.strip()}' for n, t in pages)
    if len(body) > budget:
        body = body[:budget] + '\n[… مقتطع لطول المستند]'
    who = d['cite'].strip('()')
    return f"### [{d['code']}] {d['kind']} — {who}\n{body}"


def facts_prompt(axis, sec, docs, memos, ctx, axes=None):
    """طلب المرحلة 1 لعقد واحد (أو لكل المستندات بلا عقود، أو للاعتراضات): الحقائق اللازمة لكل محاور البحث معاً،
    فتُستخرج مرة واحدة للعقد وتُشارك بين محاوره."""
    blocks = docs + memos
    budget = MAX_SECTION_CHARS // max(1, len(blocks))
    axes = axes or [axis]
    parts = [
        "أنت مساعد خبير قضائي. المطلوب «المرحلة 1: استخراج الحقائق» لقسم من «البحث ورأي الخبرة». لا تكتب نصاً "
        "للتقرير ولا تحسب شيئاً. استخرج من المستندات أدناه فقط ما يلزم للإجابة عن محاور البحث، بترتيب زمني، بلا استنتاج ولا "
        "تخمين. لكل واقعة أو مبلغ: رمز المستند (D1…) ورقم الصفحة واقتباساً حرفياً متصلاً (5–25 كلمة) منسوخاً كما هو من نص "
        "تلك الصفحة ويحتوي التاريخ/المبلغ نفسه. انسخ الأرقام والتواريخ كما وردت. ما لا يرد في المستندات لا تذكره.",
        "## محاور البحث\n" + '\n'.join(f"- المحور {a['ordinal']}: {a['title']}" for a in axes),
        f"## القسم: {sec.get('contract_title') or sec.get('title') or 'كل مستندات القضية'}"
        + ("\nهذا قسم عقد واحد: لا تستخرج وقائع أو مبالغ عقد آخر." if sec['kind'] == 'contract' else ''),
    ]
    if ctx:
        parts.append("## سياق فقط (لا تستخرج منه حقائق لهذا القسم)\n" + '\n'.join(f'- {c}' for c in ctx))
    parts.append(
        "## صيغة الرد (JSON فقط)\n"
        '{"facts":[{"date":"dd/mm/yyyy أو \\"\\"","text":"الواقعة بإيجاز","doc":"D1","page":1,"quote":"اقتباس حرفي","item":null,"key":false}],\n'
        ' "amounts":[{"label":"وصف المبلغ","value":"كما ورد","currency":"د.ك","kind":"total","doc":"D1","page":1,"quote":"اقتباس حرفي فيه المبلغ","item":null}],\n'
        ' "formulas":[{"label":"اسم الناتج","expr":"(50000 * 500) / 100","unit":"طن","role":"","basis":"النص التعاقدي","alternatives":["أساس بديل"]}],\n'
        ' "objections":[{"party":"المدعى عليها الأولى","text":"الاعتراض بإيجاز","doc":"D4","page":1,"quote":"اقتباس حرفي"}],\n'
        ' "debtor":"","creditor":""}\n'
        "- kind للمبالغ: total = قيمة العقد/الخط أو إجمالي المستحق، paid = مبلغ مسدد، fine = غرامة، remaining = متبقٍ كما ورد "
        "في المستند، claim = ما تطالب به المدعية عن هذا العقد/الخط، claim_total = إجمالي المطالبة، price = سعر وحدة، "
        "qty = كمية، rate = نسبة أو معدل، other = غير ذلك.\n"
        "- formulas: فقط إن نص العقد على أساس احتساب (مثل: كل X لتر يعالج Y طن، والمقابل Z عن كل طن)؛ اكتب المعادلة "
        "بالأرقام الواردة حرفياً و+ - * / وأقواس فقط، ولا تكتب ناتجها؛ role = total إن كان ناتجها إجمالي المستحق.\n"
        "- key: true فقط للواقعة التي تحتاج إثباتاً بمستند (العقد، المبلغ المطالب به، الدفعات، إقرار طرف، مستند الشحن أو التسليم، "
        "مستند يحسم نزاعاً)، وfalse للوقائع الثانوية.\n"
        "- item: رقم المستند في جدول وجه الحافظة (عمود م) إن تبيّن أن الصفحة تخصه، وإلا null.\n"
        "- debtor/creditor: الطرف المدين والدائن بالصفة (المدعية، المدعى عليها الأولى…) إن ظهر من المستندات، وإلا \"\"."
        + ("\n- objections: أوجه دفاع/اعتراضات كل طرف من مذكراته بإيجاز مع اقتباس حرفي من المذكرة." if memos else
           "\n- objections: اتركها [] في هذا القسم."))
    parts.append("## المستندات\n" + ('\n\n'.join(_doc_block(d, p, budget) for d, p in blocks) or '_لا مستندات._'))
    return '\n\n'.join(parts)


def _parse_json(raw):
    if isinstance(raw, dict):
        return raw
    m = re.search(r'\{.*\}', str(raw or ''), re.S)
    if not m:
        raise ValueError('ردّ المزوّد ليس JSON صالحاً')
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        raise ValueError('ردّ المزوّد ليس JSON صالحاً') from None
    if not isinstance(obj, dict):
        raise ValueError('ردّ المزوّد ليس JSON صالحاً')
    return obj


_PLAINT_CACHE = {}


def _plaint(text):
    import case_subject_telecom as st
    key = hashlib.sha1(text.encode('utf-8')).hexdigest()
    if key not in _PLAINT_CACHE:
        if len(_PLAINT_CACHE) > 2000:
            _PLAINT_CACHE.clear()
        _PLAINT_CACHE[key] = st.Plaint(text)
    return _PLAINT_CACHE[key]


def find_quote(pages, quote, page=None):
    """(رقم الصفحة، النص الموجود) إن ورد الاقتباس حرفياً (بتطبيع الأرقام والتشكيل) — الصفحة المذكورة أولاً."""
    import case_subject_telecom as st
    q = st._clean(quote)
    if not q or len(q.split()) < 3:
        return None
    order = sorted(pages, key=lambda pt: pt[0] != page)
    for n, t in order:
        got = _plaint(t).find(q)
        if got:
            return n, got
    want = [_loose(x) for x, _s, _e in st._tokens(st._display(q))]
    for n, t in order:                        # الكلمة نفسها مع/بلا «و»/«ف» في أولها (ويدفع = يدفع) — لا غير
        pl = _plaint(t)
        have = [_loose(x) for x, _s, _e in pl.toks]
        k = len(want)
        for i in range(len(have) - k + 1):
            if have[i:i + k] == want:
                return n, re.sub(r'\s+', ' ', pl.display[pl.toks[i][1]:pl.toks[i + k - 1][2]]).strip()
    return None


def _loose(tok):
    return tok[1:] if len(tok) > 3 and tok[0] in 'وف' else tok


def _amount_in(value, text):
    try:
        v = calc.norm_num(calc.D(value))
    except (calc.CalcError, ValueError):
        return False
    return v in calc.numbers_in(text)


def _face_item(d, item, quote):
    """«مستند N» من وجه الحافظة إن طابق البندُ الاقتباسَ (رقم ≥4 خانات أو تاريخ أو كلمتان)؛ وإلا None."""
    try:
        n = int(str(item).translate(_DIGITS))
    except (TypeError, ValueError):
        return None
    row = next((t for k, t in d.get('face') or [] if k == n), None)
    if row is None:
        return None
    rn, qn = calc.numbers_in(row), calc.numbers_in(quote)
    if any(len(x.replace('.', '')) >= 4 and x in qn for x in rn):
        return n
    rw = {w for w in _norm(row).split() if len(w) >= 4}
    return n if len(rw & set(_norm(quote).split())) >= 2 else None


def cite_of(d, item=None):
    if item and d['kind'] == 'حافظة مستندات' and not d.get('multi'):
        return d['cite'][:-1] + f' مستند {item})'
    return d['cite']


def verify_facts(raw, docs, memos=()):
    """يحوّل ردّ المرحلة 1 إلى حقائق متحقَّقة. يرجع (verified, removed[نصوص])."""
    import case_contracts as cc
    obj = _parse_json(raw)
    by_code = {d['code']: (d, pages) for d, pages in list(docs) + list(memos)}
    removed = []
    out = {'facts': [], 'amounts': [], 'formulas': [], 'objections': [], 'debtor': '', 'creditor': ''}

    def locate(rec, what):
        code = str(rec.get('doc') or '').strip('[] ')
        if code not in by_code:
            removed.append(f"{what}: مستند غير معروف «{code}»")
            return None
        d, pages = by_code[code]
        try:
            page = int(str(rec.get('page') or '').translate(_DIGITS))
        except ValueError:
            page = None
        hit = find_quote(pages, rec.get('quote'), page)
        if not hit:
            removed.append(f"{what}: الاقتباس «{str(rec.get('quote') or '')[:80]}» غير موجود حرفياً في {d['cite']}")
            return None
        return d, hit[0], hit[1]

    for f in obj.get('facts') or []:
        if not isinstance(f, dict):
            continue
        loc = locate(f, 'واقعة')
        if not loc:
            continue
        d, page, quote = loc
        date = ' '.join(str(f.get('date') or '').split())
        page_text = dict(by_code[d['code']][1]).get(page, '')
        if date and not (cc.date_in_text(date, quote) or cc.date_in_text(date, page_text)):
            removed.append(f"واقعة: التاريخ {date} لا يرد في {d['cite']}")
            continue
        item = _face_item(d, f.get('item'), quote)
        out['facts'].append({'date': date, 'text': ' '.join(str(f.get('text') or '').split())[:400], 'quote': quote,
                             'doc': d['code'], 'page': page, 'cite': cite_of(d, item), 'key': bool(f.get('key'))})
    for a in obj.get('amounts') or []:
        if not isinstance(a, dict):
            continue
        loc = locate(a, f"مبلغ «{a.get('value')}»")
        if not loc:
            continue
        d, page, quote = loc
        val = str(a.get('value') or '')
        page_text = dict(by_code[d['code']][1]).get(page, '')
        if not (_amount_in(val, quote) or _amount_in(val, page_text)):
            removed.append(f"مبلغ: «{val}» لا يرد حرفياً في {d['cite']}")
            continue
        try:
            dec = calc.D(val)
        except calc.CalcError:
            removed.append(f"مبلغ: «{val}» ليس رقماً")
            continue
        kind = str(a.get('kind') or 'other').strip()
        item = _face_item(d, a.get('item'), quote)
        out['amounts'].append({'label': ' '.join(str(a.get('label') or '').split())[:200], 'value': val, 'dec': str(dec),
                               'cur': calc.currency_of(f"{a.get('currency') or ''} {val}"), 'kind': kind,
                               'quote': quote, 'doc': d['code'], 'page': page, 'cite': cite_of(d, item)})
    known = set()
    for rec in out['amounts'] + out['facts']:
        known |= calc.numbers_in(rec['quote'])
    for f in obj.get('formulas') or []:
        if not isinstance(f, dict) or not f.get('expr'):
            continue
        try:
            step, used = calc.formula(' '.join(str(f.get('label') or 'الناتج').split()), f['expr'],
                                      ' '.join(str(f.get('unit') or '').split()))
        except calc.CalcError as e:
            removed.append(f"معادلة «{f.get('expr')}»: {e}")
            continue
        bad = [calc.fmt(u, False) for u in used if calc.norm_num(u) not in known]
        if bad:
            removed.append(f"معادلة «{f.get('expr')}»: أرقام غير واردة في المستندات ({'، '.join(bad)})")
            continue
        out['formulas'].append({'label': step.label, 'expr': f['expr'], 'unit': step.unit,
                                'role': str(f.get('role') or ''), 'basis': ' '.join(str(f.get('basis') or '').split())[:300],
                                'alternatives': [' '.join(str(x).split())[:200] for x in f.get('alternatives') or [] if str(x).strip()][:3],
                                'step': step.to_dict()})
    for o in obj.get('objections') or []:
        if not isinstance(o, dict):
            continue
        loc = locate(o, 'اعتراض')
        if not loc:
            continue
        d, page, quote = loc
        out['objections'].append({'party': ' '.join(str(o.get('party') or d.get('side') or '').split())[:80],
                                  'text': ' '.join(str(o.get('text') or '').split())[:500], 'quote': quote,
                                  'doc': d['code'], 'page': page, 'cite': d['cite']})
    for k in ('debtor', 'creditor'):
        out[k] = ' '.join(str(obj.get(k) or '').split())[:60]
    out['facts'].sort(key=lambda f: _date_key(f['date']))
    return out, removed


def _date_key(d):
    m = re.findall(r'\d+', str(d or '').translate(_DIGITS))
    if len(m) != 3:
        return (9999, 99, 99)
    if len(m[0]) == 4:
        return (int(m[0]), int(m[1]), int(m[2]))
    return (int(m[2]), int(m[1]), int(m[0]))


# ---------- طلبات الخبرة في المحاضر ----------

def requests_prompt(items, labels):
    parties = [labels['plaintiff']] + labels['defendants']
    blocks = '\n\n'.join(f"[{m['ref']}] {m['cite']}\n{m['text'][:6000]}" for m in items)
    return ("أنت مساعد خبير قضائي. أمامك نصوص محاضر أعمال الخبرة. استخرج ما طلبته الخبرة من كل طرف (مستند أو بيان) "
            "وهل قدّمه، بلا استنتاج. أعد JSON فقط:\n"
            '{"requests":[{"minute":"M1","to":"المدعى عليها الأولى","what":"تقديم …","evidence":"اقتباس حرفي من المحضر فيه الطلب",'
            '"delivered":false,"proof":"اقتباس حرفي يثبت عدم التقديم أو التقديم من أي محضر أو \\"\\""}]}\n'
            "- evidence وproof اقتباسات حرفية متصلة (5–20 كلمة) منسوخة كما هي.\n"
            "- delivered = true إن ثبت التقديم، false إن ثبت عدم التقديم أو تكرر الطلب في محضر لاحق، null إن لم يتبيّن.\n"
            f"- الأطراف بالصفات: {json.dumps(parties, ensure_ascii=False)}\n\nالمحاضر:\n{blocks}")


def verify_requests(raw, items):
    """طلبات ثابتة بدليل حرفي. «لم يقدم» لا تثبت إلا بطلب ثابت + (دليل عدم تقديم حرفي أو تكرار الطلب في محضرين)."""
    import case_minutes_ai as mai
    by_ref = {m['ref']: m for m in items}
    norms = {m['ref']: mai._norm(m['text']) for m in items}
    out, bad = [], []
    for r in (_parse_json(raw).get('requests') or []):
        if not isinstance(r, dict):
            continue
        m = by_ref.get(str(r.get('minute') or ''))
        ev = str(r.get('evidence') or '')
        if not m or not mai._proven(ev, norms[m['ref']]):
            bad.append(f"طلب «{str(r.get('what') or '')[:60]}» بلا دليل حرفي في المحضر")
            continue
        proof = str(r.get('proof') or '')
        proof_ok = bool(proof) and any(mai._proven(proof, n) for n in norms.values())
        out.append({'to': ' '.join(str(r.get('to') or '').split())[:80], 'what': ' '.join(str(r.get('what') or '').split())[:300],
                    'minute': m['ref'], 'date': m['date'], 'cite': m['cite'], 'evidence': ev,
                    'delivered': r.get('delivered') if isinstance(r.get('delivered'), bool) else None,
                    'proof': proof if proof_ok else ''})
    for r in out:                                    # تكرار الطلب نفسه للطرف نفسه في محضرين مختلفين
        same = [x for x in out if x is not r and _norm(x['to']) == _norm(r['to'])
                and len(set(_norm(x['what']).split()) & set(_norm(r['what']).split())) >= 2 and x['minute'] != r['minute']]
        r['not_delivered'] = r['delivered'] is False and bool(r['proof'] or same)
    return out, bad


def extract_requests(base, data, ask, cache=None):
    r = state(data)
    items = (cache or {}).get('minutes') if cache and 'minutes' in cache else minutes(base, data)
    key = _sha([[m['ref'], m['text']] for m in items])
    prev = r.get('minutes') or {}
    if prev.get('key') == key and prev.get('requests') is not None:
        return prev
    if not items or ask is None:
        r['minutes'] = {'key': key, 'requests': [], 'unverified': []} if not items else prev
        return r['minutes']
    try:
        raw = ask(requests_prompt(items, party_labels(data)))
        reqs, bad = verify_requests(raw, items)
        import ai_call_log
        ai_call_log.verdict(True, f'{len(reqs)} طلباً متحقَّقاً؛ لم يتحقق {len(bad)}')
    except Exception as e:
        r['minutes'] = dict(prev, error=f'تعذّر استخراج طلبات الخبرة من المحاضر: {e}')
        return r['minutes']
    r['minutes'] = {'key': key, 'requests': reqs, 'unverified': bad}
    return r['minutes']


def proven_requests(data):
    return [q for q in (state(data).get('minutes') or {}).get('requests') or [] if q.get('not_delivered')]


# ---------- (د) الحساب بالكود ----------

def set_fx(base, data, cur, rate, date, basis=''):
    """سعر الصرف الذي يحدده الخبير (وتاريخه وسبب اختياره). يُعيد حساب أقسام الحساب عند التشغيل التالي."""
    rate_d = calc.D(rate)
    if rate_d <= 0:
        raise cm.StepError('سعر الصرف يجب أن يكون موجباً.')
    fx = state(data).setdefault('decisions', {}).setdefault('fx', {})
    fx[calc.currency_of(cur) if len(cur) > 3 else cur.upper()] = {'rate': str(rate).strip(), 'date': _dmy(date),
                                                                   'basis': ' '.join(str(basis or '').split())}
    for _a, s in all_sections(data):
        if s.get('calc') and s['state'] in (S_DRAFTED, S_FACTS):
            s['calc'] = None
    cw.write_case_json(base, data)


def _amounts(ver, kind, cur=None):
    return [(a['label'] or a['kind'], calc.D(a['dec'])) for a in ver['amounts']
            if a['kind'] == kind and (cur is None or a['cur'] == cur)]


def compute(sec, ver, data, labels, axis_kind, multi=False):
    """أرقام القسم الجاهزة: الجداول وسطور المعادلات والمبلغ النهائي بالحروف. يرجع (calc dict، notes).
    multi: محور حساب بعدة عقود ← سطر ختام القسم «المتبقي على العقد …» والحكم المالي في القسم الإجمالي وحده."""
    notes = []
    steps, tables = [], []
    fx = (state(data).get('decisions') or {}).get('fx') or {}
    for f in ver['formulas']:
        st = f['step']
        steps.append(st['line'])
        if f.get('basis'):
            alt = ('؛ البدائل: ' + '، '.join(f['alternatives'])) if f.get('alternatives') else ''
            notes.append((N_DECISION, f"أساس الاحتساب «{st['label']}»: {f['basis']}{alt}"))
    out = {'steps': steps, 'tables': tables, 'final': None, 'remaining': None, 'cur': 'KWD', 'counts': []}
    if axis_kind != K_CALC or sec['kind'] not in ('contract', 'general'):
        return out, notes
    totals_f = [f for f in ver['formulas'] if f.get('role') == 'total']
    curs = [a['cur'] for a in ver['amounts'] if a['kind'] in ('total', 'paid')] or ['KWD']
    cur = max(set(curs), key=curs.count)
    totals = [(f['step']['label'], Decimal(f['step']['value'])) for f in totals_f] or _amounts(ver, 'total', cur)
    if not totals:
        notes.append((N_MISSING, 'لا يوجد في المستندات المتحقَّقة إجمالي مستحق لهذا القسم — لم يُحسب المتبقي'))
        return out, notes
    paid = _amounts(ver, 'paid', cur)
    fines = _amounts(ver, 'fine', cur)
    others = [a for a in ver['amounts'] if a['kind'] in ('total', 'paid', 'fine') and a['cur'] != cur]
    for a in others:
        notes.append((N_DECISION, f"مبلغ بعملة مختلفة لم يدخل الحساب: {a['value']} ({a['cite']})"))
    stated = [Decimal(a['dec']) for a in ver['amounts'] if a['kind'] == 'remaining' and a['cur'] == cur]
    claims = [Decimal(a['dec']) for a in ver['amounts'] if a['kind'] == 'claim' and a['cur'] == cur]
    title = sec.get('contract_title') or 'الحساب'
    acc = calc.contract_account(title, totals, paid, fines, stated[-1] if stated else None,
                                claims[-1] if claims else None, cur)
    tables.append(acc['table'])
    steps += [s.line() for s in acc['steps']]
    for dtxt in acc['diffs']:
        notes.append((N_DIFF, dtxt))
    out['counts'] = [len(paid), len(totals), len(fines)]
    remaining = acc['remaining']
    if cur != 'KWD':
        rate = fx.get(cur)
        if not rate:
            notes.append((N_MISSING, f"سعر صرف {calc.CURRENCY_NAMES.get(cur, cur)} وتاريخه غير محددين — حدّدهما من «سعر "
                                     f"الصرف» ثم أعد صياغة القسم؛ لم يُحوَّل المبلغ إلى الدينار"))
            out.update(remaining=str(remaining), cur=cur)
            return out, notes
        st = calc.convert(remaining, rate['rate'], cur, rate['date'])
        steps.append(st.line())
        notes.append((N_DECISION, f"سعر صرف {calc.CURRENCY_NAMES.get(cur, cur)}: {rate['rate']} د.ك بتاريخ {rate['date']}"
                                  + (f" ({rate['basis']})" if rate.get('basis') else '')
                                  + ' — البدائل: سعر تاريخ رفع الدعوى أو تاريخ الاستحقاق'))
        out['fx'] = dict(rate, cur=cur)
        remaining = st.value
    out.update(remaining=str(remaining), cur='KWD')
    out['final'] = final_info(remaining, ver, labels)
    if multi:
        f = out['final']
        f['line'] = (f"وعليه ترى الخبرة أن المتبقي على {title} مبلغ وقدره {f['shown']} د.ك ({f['words']})."
                     if remaining >= 0 else
                     f"وعليه ترى الخبرة أن رصيد {title} لصالح {f['creditor']} مبلغ وقدره {f['shown']} د.ك ({f['words']}).")
        f['partial'] = True
    return out, notes


def final_info(remaining, ver, labels):
    remaining = Decimal(remaining)
    known = [labels['plaintiff']] + labels['defendants']
    debtor = ver.get('debtor') if ver.get('debtor') in known else labels['defendants'][0]
    creditor = ver.get('creditor') if ver.get('creditor') in known else labels['plaintiff']
    if remaining < 0:
        debtor, creditor = creditor, debtor
    amt = abs(remaining)
    words = amounts.to_words(amt)
    return {'amount': str(calc.q3(amt)), 'shown': calc.fmt(amt), 'words': words, 'debtor': debtor, 'creditor': creditor,
            'line': (f"مما سبق ترى الخبرة أنه بعد تصفية الحساب بين الطرفين فإن ذمة {debtor} مشغولة لصالح {creditor} "
                     f"بمبلغ وقدره {calc.fmt(amt)} د.ك ({words})." if amt else
                     "مما سبق ترى الخبرة أنه بعد تصفية الحساب بين الطرفين لا تترصد مبالغ في ذمة أي منهما للآخر.")}


def total_section_text(axis, data, labels):
    """قسم «تصفية الحساب الإجمالية» لعدة عقود — يكتبه الكود وحده: جدول المتبقي لكل عقد ثم المجموع ومطابقته للمطالبة."""
    rows, vals, notes = [], [], []
    claim_total = None
    for s in axis['sections']:
        if s['kind'] != 'contract':
            continue
        c = s.get('calc') or {}
        if c.get('remaining') is None or c.get('cur') != 'KWD':
            notes.append((N_MISSING, f"لم يكتمل حساب {s.get('contract_title') or s['key']} — المجموع جزئي"))
            continue
        rows.append((s.get('contract_title') or '', Decimal(c['remaining'])))
        vals.append(Decimal(c['remaining']))
        for a in (s.get('facts') or {}).get('amounts') or []:
            if a['kind'] == 'claim_total' and a['cur'] == 'KWD':
                claim_total = Decimal(a['dec'])
    if not vals:
        return None, None, notes
    st, diff, dtxt = calc.sum_check('مجموع المتبقي على العقود', vals, claim_total)
    table = calc.money_table([(lab, calc.fmt(v)) for lab, v in rows] + [('المجموع', calc.fmt(st.value))],
                             ('العقد', 'المتبقي (د.ك)'))
    text = ["توضح الخبرة أن المتبقي على كل عقد من العقود المبينة أعلاه على النحو التالي:", table, st.line()]
    if claim_total is not None:
        text.append(f"وهو مطابق لمطالبة المدعية البالغة {calc.fmt(claim_total)} د.ك." if diff == 0 else
                    f"ويختلف عن مطالبة المدعية البالغة {calc.fmt(claim_total)} د.ك بفرق {calc.fmt(abs(diff))} د.ك.")
    if dtxt:
        notes.append((N_DIFF, dtxt))
    fin = final_info(st.value, {}, labels)
    text.append(fin['line'])
    return '\n\n'.join(text), fin, notes


# ---------- (هـ) المرحلة 2: الصياغة ----------

def case_type(data):
    t = (data.get('subject_type') or '')
    subj = _norm(data.get('subject') or '')
    if t == 'اتصالات':
        return 'اتصالات'
    if t == 'مقاول_باطن' or 'شراكه' in subj or 'باطن' in subj:
        return 'باطن_شراكة'
    return 'مقاولة_توريد'


def pick_models(models, ctype, tag, limit=3):
    """نموذجان من نوع القضية بوسم المقطع + المرجعي بالوسم نفسه."""
    same = [m for m in models if m['type'] == ctype and tag in m['tags']]
    ref = [m for m in models if m['type'] == 'مرجعي' and tag in m['tags']]
    gen = [m for m in models if m['type'] == 'عام' and tag in m['tags']]
    out = (same[:2] + ref[:1] + gen[:1])[:limit]
    return out or [m for m in models if tag in m['tags']][:limit]


def _library():
    import drafting_library as dl
    rules, models = dl.load(dl.RESEARCH_FILE)
    return rules, models, dl.load_section(dl.RESEARCH_FILE, 'قواعد النتيجة')


_TAG = {K_REL: 'علاقة', K_BREACH: 'إخلال', K_CALC: 'حساب', K_DEF: 'اعتراضات', K_GEN: 'إخلال'}


def _fact_line(f):
    shown = f['text'] if f.get('text') and calc.numbers_in(f['text']) <= (calc.numbers_in(f['quote'])
                                                                          | calc.numbers_in(f['date'])) else ''
    ref = (f"[للإثبات — مرجعها: {f['cite']}]" if f.get('key') else '[ثانوية — بلا مرجع]')
    return f"- {('[' + f['date'] + '] ') if f.get('date') else ''}{shown + ' — ' if shown else ''}«{f['quote']}» {ref}"


def numbers_block(sec):
    c = sec.get('calc') or {}
    out = []
    for t in c.get('tables') or []:
        out.append(t)
    for line in c.get('steps') or []:
        out.append(line)
    if c.get('final'):
        out.append('السطر الختامي (انسخه حرفياً): ' + c['final']['line'])
    if sec['kind'] == 'total' and sec.get('total_text'):
        out.append(sec['total_text'])
    return '\n'.join(out)


def section_material(data, axis, sec, first_in_axis):
    """نص «مادة القسم» المشترك بين طلب API وملف prompt.md."""
    ver = sec.get('facts') or {}
    reqs = proven_requests(data)
    parts = [f"## موضع القسم\nالمحور {axis['ordinal']}: «{axis['title']}» — عنوانه يكتبه البرنامج فلا تكرره ولا تكرر نص المأمورية."]
    if sec['kind'] == 'contract':
        parts[0] += f"\nهذا قسم {sec.get('contract_title')} وحده: لا تذكر وقائع أو أرقام عقد آخر."
    parts[0] += ("\nالمراجع: تُكتب بالصيغة المعطاة حرفياً بلا رقم صفحة، ولا تُكتب في كل جملة: عند أول ذكر للمستند في "
                 "الفقرة فقط، وللمواضع المعلّمة «للإثبات»؛ الوقائع الثانوية بلا مرجع؛ وحد أقصى مرجع واحد لكل مستند في الفقرة.")
    if sec['kind'] == 'objections':
        parts[0] += "\nهذا قسم اعتراضات الأطراف من مذكراتهم والرد عليها بأسباب مرقمة."
    if first_in_axis and sec['kind'] != 'objections':
        parts[0] += "\nهو أول قسم في المحور (يجوز البدء بـ«بادئ ذي بدء توضح الخبرة التالي:» عند الحاجة)."
    facts = ver.get('facts') or []
    amts = ver.get('amounts') or []
    parts.append("## الحقائق المتحقَّقة (بترتيب زمني، مع مرجع كل منها بصيغة الخبير)\n"
                 + ('\n'.join(_fact_line(f) for f in facts) or '- لا وقائع متحقَّقة')
                 + ('\n' + '\n'.join(f"- مبلغ: {a['label']}: {a['value']} «{a['quote']}» {a['cite']}" for a in amts) if amts else ''))
    nb = numbers_block(sec)
    parts.append("## الأرقام الجاهزة (محسوبة بالكود؛ انسخها كما هي ولا تحسب غيرها)\n" + (nb or '- لا حساب في هذا القسم'))
    if reqs:
        parts.append("## طلبات الخبرة الثابتة في المحاضر (وحدها تجيز «طلبت الخبرة من … تقديم … إلا أنه لم يقدم … رغم "
                     "منحه الفرصة الكافية»)\n" + '\n'.join(f"- {q['to']}: {q['what']} {q['cite']}" for q in reqs))
    else:
        parts.append("## طلبات الخبرة الثابتة في المحاضر\n- لا توجد: فلا تكتب أن طرفاً لم يقدم مستنداً رغم طلب الخبرة.")
    dec = [n['text'] for n in sec.get('notes') or [] if n['type'] == N_DECISION]
    if dec:
        parts.append("## اجتهادات الخبرة (تُصاغ صراحة: «أخذت الخبرة بالأساس …»)\n" + '\n'.join(f'- {d}' for d in dec))
    objs = ver.get('objections') or []
    if objs:
        parts.append("## أوجه دفاع الأطراف من المذكرات\n" + '\n'.join(
            f"- {o['party']}: {o['text']} «{o['quote']}» {o['cite']}" for o in objs))
    ctx = context_lines(data)
    if ctx:
        parts.append("## سياق فقط (لا يدخل الحساب)\n" + '\n'.join(f'- {c}' for c in ctx))
    return '\n\n'.join(parts)


def draft_prompt(data, axis, sec, first_in_axis, rules, models, bad=None):
    parts = ["أنت تكتب بأسلوب الخبير القضائي قسماً من «البحث ورأي الخبرة» في تقرير خبرة. "
             "التزم بالأرقام المعطاة حرفياً: لا تحسب ولا تقرّب ولا تكتب رقماً أو تاريخاً أو مبلغاً غير وارد أدناه.",
             "## قواعد الصياغة (ملزمة)\n" + rules]
    if models:
        parts.append("## نماذج من تقارير الخبير (للأسلوب فقط؛ لا تنقل منها وقائع ولا أرقاماً)\n"
                     + '\n\n'.join(f"### {m['title']}\n{m['text']}" for m in models))
    parts.append(section_material(data, axis, sec, first_in_axis))
    req = ("## المطلوب\nاكتب نص القسم نثراً متصلاً بفقرات قصيرة بترتيب الوقائع الزمني، بلا عناوين إلا «اعتراضات …» في قسم "
           "الاعتراضات، وبلا قوائم نقطية إلا الجداول المعطاة والأسباب المرقمة للرد على الاعتراضات، وبلا رموز المستندات "
           "(D1…) ولا أسماء ملفات. اختم بخلاصة «مما سبق ترى الخبرة …».")
    if (sec.get('calc') or {}).get('final'):
        req += " وانسخ السطر الختامي المعطى حرفياً في آخر القسم."
    parts.append(req)
    if bad:
        parts.append("تنبيه: رُفضت صياغتك السابقة لأنها تضمنت: " + '، '.join(bad) + ". أعد الكتابة دونها.")
    return '\n\n'.join(parts)


_CODE = r'[PDMR]\d+(?:-\d+)?'
_PG = (r'(?:ص|صص|صفحة|الصفحة|صفحات|الصفحات)\s*\.?\s*\d+(?:\s*(?:[-–—]|،|,|و|إلى|الى)\s*'
       r'(?:(?:ص|صفحة)\s*\.?\s*)?\d+)*')
_ELEM = rf'(?:{_CODE}|{_PG})'
_GROUP = re.compile(rf'[\[(]\s*{_ELEM}(?:[\s،,;؛/]*{_ELEM})*\s*[\])]')
_BARE_CODE = re.compile(rf'(?<![\w\u0600-\u06FF]){_CODE}(?:\s*{_PG})?(?![\w])')
_BARE_PG = re.compile(rf'(?:(?<![؀-ۿ])و?في\s+)?(?<![؀-ۿ]){_PG}')
_GLYPHS = '-*•▪◦·‣∙●○▫■□–—'
_LEAD_GLYPH = re.compile(rf'^[ \t]*(?:[{re.escape(_GLYPHS)}][ \t]*)+')
_REF_PAREN = re.compile(r'\(\s*[^()\n]{0,220}?(?:حافظ[ةه]|مذكر[ةه]|محضر|صحيف[ةه]|حكم الإحالة|تقرير الخبر[ةه] السابق)'
                        r'[^()\n]{0,220}\)')


def strip_internal(text):
    """يزيل رموز المستندات والصفحات من أي نص (بكل صيغها: [P1-2 ص6، ص15]، P1-2، ص15، صفحة 3، D3، M2)
    ويرتّب ما بقي من علامات. يمر عليه كل نص من أي مسار (API، prompt.md، Copilot، الاستيراد، المعاينة، Word)."""
    t = str(text or '')
    for _ in range(2):
        t = _GROUP.sub('', t)
        t = _BARE_CODE.sub('', t)
        t = _BARE_PG.sub('', t)
    t = re.sub(r'\(\s*[،,;؛]*\s*\)|\[\s*[،,;؛]*\s*\]', '', t)
    t = re.sub(r'\(\s*[،,;؛]+', '(', t)
    t = re.sub(r'[،,]\s*(?=[،,])', '', t)
    t = re.sub(r'[ \t]+([،.:؛)\]])', r'\1', t)
    t = re.sub(r'([(\[])[ \t]+', r'\1', t)
    t = re.sub(r'[ \t]{2,}', ' ', t)
    return t


def fix_glyphs(text):
    """علامة تعداد واحدة فقط في أول السطر (لا «· ·» ولا «- •»)."""
    out = []
    for ln in str(text or '').split('\n'):
        m = _LEAD_GLYPH.match(ln)
        if m and ln[m.end():].strip():
            ln = '- ' + ln[m.end():]
        out.append(ln)
    return '\n'.join(out)


def _ref_key(par):
    n = _norm(par)
    kind = next((k for k in ('حافظ', 'مذكر', 'محضر', 'صحيف', 'حكم', 'تقرير') if k in n), '')
    return (kind, tuple(sorted(calc.numbers_in(par))), 'عليه' in n or 'عليها' in n)


def limit_refs(text):
    """مرجع واحد على الأكثر لكل مستند في الفقرة: يبقى أول ذكر ويُحذف المكرر (الفقرة = السطر)."""
    out = []
    for ln in str(text or '').split('\n'):
        if ln.lstrip().startswith('|'):
            out.append(ln)
            continue
        seen = set()

        def one(m):
            k = _ref_key(m.group(0))
            if k in seen:
                return ''
            seen.add(k)
            return m.group(0)
        ln = _REF_PAREN.sub(one, ln)
        ln = re.sub(r'[ \t]+([،.:؛])', r'\1', ln)
        out.append(re.sub(r'[ \t]{2,}', ' ', ln))
    return '\n'.join(out)


def strip_refs(text):
    """يزيل كل مرجع مستند/مرفق (للنتيجة: لا إحالة لمستند أو مرفق)."""
    t = _REF_PAREN.sub('', strip_internal(text))
    t = re.sub(r'[ \t]+([،.:؛])', r'\1', t)
    return re.sub(r'[ \t]{2,}', ' ', t)


def clean_display(text):
    """المنظّف الموحّد قبل العرض والحفظ: بلا رموز/صفحات، علامة تعداد واحدة، مرجع واحد لكل مستند في الفقرة."""
    return limit_refs(fix_glyphs(strip_internal(text)))


_FILENAME = re.compile(r'[^\s()«»"]+\.(?:pdf|docx?|md|txt|xlsx?|jpe?g|png|tiff?|rtf|odt)\b', re.I)
_FORBIDDEN = ('[يُكتب]', '[يكتب]', '[ناقص', 'يتعذر على الخبرة', 'يتعذّر على الخبرة', 'تعذر على الخبرة', 'تعذّر على الخبرة',
              'ما ينقص المستندات', 'ما ينقص من المستندات', '[رقم غير موثّق')
_NOT_SUBMITTED = re.compile(r'لم\s+(?:ي|ت)قدم|لم\s+(?:ي|ت)قم\s+بتقديم|لم\s+(?:ي|ت)رد\s+على\s+(?:طلب|سؤال|استفسار)|'
                            r'رغم\s+منح|رغم\s+طلب\s+الخبر|'
                            r'على\s+الرغم\s+من\s+طلب\s+الخبر|رغم\s+(?:إمهال|امهال)')
_WORDS_AMT = re.compile(r'\(([^()]{6,220}?(?:فقط|لا\s+غير|كويتي)[^()]*)\)')
_BULLET = re.compile(r'^\s*(?:[' + re.escape(_GLYPHS) + r']\s*)+')


def _sentences(par):
    return [s for s in re.split(r'(?<=[.؟!])\s+', par) if s.strip()]


def mission_echo(text, mission_raw, n=6):
    """الجمل التي تشارك نص المأمورية في n كلمات متتالية فأكثر."""
    mw = _norm(mission_raw).split()
    grams = {' '.join(mw[i:i + n]) for i in range(len(mw) - n + 1)}
    if not grams:
        return []
    out = []
    for par in text.split('\n'):
        for s in _sentences(par):
            w = _norm(s).split()
            if any(' '.join(w[i:i + n]) in grams for i in range(len(w) - n + 1)):
                out.append(s)
    return out


def allowed_numbers(data, sec):
    """كل رقم مسموح في نص القسم: من الحقائق المتحقَّقة ومراجعها والأرقام الجاهزة والطلبات الثابتة والسياق."""
    nums = set()
    ver = sec.get('facts') or {}
    for f in ver.get('facts') or []:
        nums |= calc.numbers_in(f['quote']) | calc.numbers_in(f['date']) | calc.numbers_in(f['cite'])
    for a in ver.get('amounts') or []:
        nums |= calc.numbers_in(a['quote']) | calc.numbers_in(a['value']) | calc.numbers_in(a['cite'])
    for o in ver.get('objections') or []:
        nums |= calc.numbers_in(o['quote']) | calc.numbers_in(o['cite'])
    nums |= calc.numbers_in(numbers_block(sec))
    for n in (sec.get('calc') or {}).get('counts') or []:
        nums.add(str(n))
    for q in proven_requests(data):
        nums |= calc.numbers_in(q['cite']) | calc.numbers_in(q['evidence'])
    for n in sec.get('notes') or []:
        if n['type'] == N_DECISION:
            nums |= calc.numbers_in(n['text'])
    nums |= calc.numbers_in(' '.join(context_lines(data)))
    nums |= calc.numbers_in(sec.get('contract_title') or '')
    for i in range(1, 10):                       # ترقيم أسباب الرد على الاعتراضات (1، 2، 3)
        if sec['kind'] == 'objections':
            nums.add(str(i))
    return nums


def allowed_word_amounts(sec):
    vals = set()
    ver = sec.get('facts') or {}
    for a in ver.get('amounts') or []:
        try:
            vals.add(calc.q3(calc.D(a['dec'])))
        except calc.CalcError:
            pass
    fin = (sec.get('calc') or {}).get('final') or sec.get('total_final')
    if fin:
        vals.add(calc.q3(Decimal(fin['amount'])))
    for line in (sec.get('calc') or {}).get('steps') or []:
        for v in calc.numbers_in(line):
            vals.add(calc.q3(Decimal(v)))
    return vals


def check_text(text, data, sec, mission_raw=''):
    """(النص المنظَّف، مشكلات تمنع القبول [نصوص]، ملاحظات حمراء [(نوع، نص)]).
    تُزال الرموز الداخلية وأسماء الملفات وعلامات القوائم والعبارات الممنوعة وصدى المأمورية وعبارة «لم يقدم» بلا سند؛
    والرقم الغريب أو المبلغ بالحروف غير المطابق مشكلة تمنع القبول."""
    notes = []
    t = str(text or '').replace('\r', '').strip()
    t = re.sub(r'^```\w*\s*|\s*```$', '', t)
    t = strip_internal(t)
    t = _FILENAME.sub('', t)
    lines = []
    for ln in t.split('\n'):
        if ln.lstrip().startswith('|'):
            lines.append(ln)
            continue
        ln = _BULLET.sub('', ln).replace('**', '')
        if re.match(r'^\s*#{1,6}\s*', ln):
            ln = re.sub(r'^\s*#{1,6}\s*', '', ln)
        kept = []
        for s in _sentences(ln) if ln.strip() else ['']:
            if any(f in s for f in _FORBIDDEN):
                notes.append((N_MISSING, f"أُزيلت جملة تذكر نقصاً داخل النص: «{s.strip()[:120]}»"))
                continue
            if _NOT_SUBMITTED.search(s) and not _not_submitted_ok(s, data):
                notes.append((N_MISSING, "أُزيلت عبارة «لم يقدم رغم طلب الخبرة» لعدم ثبوت الطلب وعدم التقديم في المحاضر "
                                         f"المقروءة: «{s.strip()[:120]}»"))
                continue
            kept.append(s)
        lines.append(' '.join(kept))
    t = limit_refs('\n'.join(lines))
    for s in mission_echo(t, mission_raw):
        t = t.replace(s, '')
        notes.append((N_REMOVED, f"أُزيلت جملة تعيد نص المأمورية: «{s.strip()[:100]}»"))
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r' +([،.:؛])', r'\1', t)
    t = re.sub(r'\(\s*\)', '', t)
    t = re.sub(r'\n{3,}', '\n\n', t).strip()
    problems = []
    foreign = sorted(calc.numbers_in(t) - allowed_numbers(data, sec), key=lambda x: (len(x), x))
    if foreign:
        problems.append('أرقام غير واردة في الحقائق أو الأرقام الجاهزة: ' + '، '.join(foreign))
    okw = allowed_word_amounts(sec)
    for m in _WORDS_AMT.finditer(t):
        v = amounts.words_to_decimal(m.group(1))
        if v is not None and calc.q3(v) not in okw:
            problems.append(f"مبلغ بالحروف غير مطابق للأرقام الجاهزة: «{m.group(1)[:60]}»")
    fin = (sec.get('calc') or {}).get('final')
    if fin and not problems and fin['words'] not in t:
        t = t.rstrip() + '\n\n' + fin['line']             # المبلغ النهائي بالأرقام ثم بالحروف — يضمنه الكود
    if not t.strip():
        problems.append('النص فارغ بعد التنظيف')
    return t, problems, notes


def _not_submitted_ok(sentence, data):
    reqs = proven_requests(data)
    if not reqs:
        return False
    s = _norm(sentence)
    for q in reqs:
        to = [w for w in _norm(q['to']).split() if len(w) >= 3]
        if to and all(w in s for w in to[:3]):
            return True
    return False


# ---------- التشغيل ----------

def _apply_notes(sec, notes):
    for kind, text in notes:
        _note(sec, kind, text)


def _write_section(base, sec, text):
    import case_documents as cd
    rel = sec.get('file') or f"{DIR_REL}/{re.sub(r'[^A-Za-z0-9_-]+', '_', sec['key'])}.md"
    cd._write_md(base, rel, clean_display(text).rstrip() + '\n')
    with open(os.path.join(base, rel), 'rb') as f:
        sec['sha1'] = hashlib.sha1(f.read()).hexdigest()
    sec['file'] = rel


def section_text(base, sec):
    return clean_display(_read(base, sec['file'])).strip() if sec.get('file') else ''


def prepare_section(base, data, axis, sec, ask, cache, force=False):
    """المرحلة 1 + الحساب: حقائق متحقَّقة (مخزّنة ببصمة المدخلات) ثم الأرقام الجاهزة. يرجع True إن جهزت."""
    labels = party_labels(data)
    if sec['kind'] == 'total':
        text, fin, notes = total_section_text(axis, data, labels)
        sec['notes'] = [n for n in sec.get('notes') or [] if n['type'] != N_DIFF]
        _apply_notes(sec, notes)
        if text is None:
            return False
        sec['total_text'], sec['total_final'] = text, fin
        sec['facts'] = {'facts': [], 'amounts': [], 'formulas': [], 'objections': []}
        sec['calc'] = {'steps': [], 'tables': [], 'final': fin, 'remaining': fin['amount'], 'cur': 'KWD', 'counts': []}
        sec['allowed'] = sorted(allowed_numbers(data, sec))
        if sec['state'] in (S_PENDING, S_BLOCKED, S_FAILED):
            sec.update(state=S_FACTS, progress=PROGRESS[S_FACTS])
        return True
    docs, memos, ctx, _mins = _section_inputs(base, data, axis, sec, cache)
    axes = state(data)['axes']
    key = _sha([[d['code'], d['cite'], p] for d, p in docs] + [[d['code'], p] for d, p in memos]
               + [ctx, [a['title'] for a in axes]])
    group = sec.get('contract') or ('obj' if sec['kind'] == 'objections' else 'all')
    if sec.get('facts') is None or sec.get('docs_key') != key or force:
        shared = state(data).setdefault('facts_cache', {})
        hit = shared.get(group)
        if hit and hit.get('key') == key and (not force or cache.get(('fresh', group))):
            ver, removed = json.loads(json.dumps(hit['ver'], ensure_ascii=False)), list(hit.get('removed') or [])
        else:
            if ask is None:
                _note(sec, N_MISSING, 'لا مزوّد ذكاء اصطناعي لاستخراج الحقائق')
                return False
            raw = ask(facts_prompt(axis, sec, docs, memos, ctx, axes))
            ver, removed = verify_facts(raw, docs, memos)
            import ai_call_log
            ai_call_log.verdict(True, f'حُذف لعدم التحقق: {len(removed)}' if removed else 'كل العناصر تحققت')
            shared[group] = {'key': key, 'ver': ver, 'removed': removed}
            cache[('fresh', group)] = True
            ver = json.loads(json.dumps(ver, ensure_ascii=False))
        sec['facts'], sec['docs_key'], sec['calc'] = ver, key, None
        sec['notes'] = [n for n in sec.get('notes') or [] if n['type'] not in (N_REMOVED, N_DIFF, N_DECISION, N_MISSING)]
        for r in removed:
            _note(sec, N_REMOVED, r)
    if sec.get('calc') is None:
        multi = sum(1 for s in axis['sections'] if s['kind'] == 'contract') > 1
        c, notes = compute(sec, sec['facts'], data, labels, axis['kind'], multi)
        sec['notes'] = [n for n in sec.get('notes') or [] if n['type'] not in (N_DIFF, N_DECISION)
                        or n['text'].startswith('أُزيلت')]
        _apply_notes(sec, notes)
        sec['calc'] = c
    sec['allowed'] = sorted(allowed_numbers(data, sec))
    sec['progress'] = max(sec.get('progress') or 0, PROGRESS[S_FACTS])
    if sec['state'] in (S_PENDING, S_BLOCKED, S_FAILED):
        sec['state'] = S_FACTS
    return True


def draft_section(base, data, axis, sec, ask, first_in_axis, source='api'):
    """المرحلة 2: طلب الصياغة ثم فحص الكود؛ رقم غريب ← إعادة مرة واحدة ثم الرفض."""
    mission_raw = (data.get('mission') or {}).get('raw') or ''
    if sec['kind'] == 'total':
        text, problems, notes = check_text(sec['total_text'], data, sec, mission_raw)
    else:
        rules, models, _cr = _library()
        tag = 'اعتراضات' if sec['kind'] == 'objections' else _TAG.get(axis['kind'], 'إخلال')
        models = pick_models(models, case_type(data), tag)
        bad = None
        for _attempt in range(2):
            raw = ask(draft_prompt(data, axis, sec, first_in_axis, rules, models, bad))
            text, problems, notes = check_text(raw, data, sec, mission_raw)
            import ai_call_log
            ai_call_log.verdict(not problems, 'نص القسم سليم' if not problems else 'رُفض: ' + '؛ '.join(problems))
            if not problems:
                break
            bad = problems
    if problems:
        sec.update(state=S_FAILED, message='رُفض النص: ' + '؛ '.join(problems))
        _note(sec, N_REMOVED, 'رُفض نص القسم بعد إعادة الطلب مرة: ' + '؛ '.join(problems))
        return False
    _apply_notes(sec, notes)
    _write_section(base, sec, text)
    sec.update(state=S_DRAFTED, message='', progress=PROGRESS[S_DRAFTED], source=source, drafted_at=_now(), edited=False)
    return True


def _set_step(data, new, msg=''):
    """ينقل خطوة البحث بأقصر طريق مسموح (عبر «تحتاج مدخلاً» عند الحاجة)؛ «فشلت» بعد اكتمال سابق ← «تحتاج مدخلاً»."""
    cur = cm.state(data, 'research')
    if cur == new:
        data['steps']['research']['message'] = msg
        return
    if new in cm.ALLOWED[cur]:
        cm.set_step(data, 'research', new, msg)
        return
    if new == 'failed':
        new = 'needs_input'
    if cur != 'needs_input' and 'needs_input' in cm.ALLOWED[cur]:
        cm.set_step(data, 'research', 'needs_input', msg)
    if cm.state(data, 'research') != new and new in cm.ALLOWED[cm.state(data, 'research')]:
        cm.set_step(data, 'research', new, msg)


def finish_state(base, data):
    """حالة خطوة البحث من الأقسام + كتابة البحث.md والملاحظات."""
    secs = all_sections(data)
    if not secs:
        return cm.state(data, 'research')
    merged = sum(1 for _a, s in secs if s['state'] == S_MERGED)
    drafted = sum(1 for _a, s in secs if s['state'] == S_DRAFTED)
    blocked = [s for _a, s in secs if s['state'] == S_BLOCKED]
    failed = [s for _a, s in secs if s['state'] == S_FAILED]
    data['steps']['research']['progress'] = {'done': merged, 'total': len(secs)}
    assemble(base, data)
    if merged == len(secs):
        _set_step(data, 'done', f'{merged} قسماً مدموجاً في البحث')
    elif failed and not drafted and not merged:
        _set_step(data, 'failed', 'تعذّرت كتابة: ' + '، '.join(s.get('contract_title') or s['key'] for s in failed[:3]))
    else:
        bits = [f'{merged} من {len(secs)} قسماً مدموجاً']
        if drafted:
            bits.append(f'{drafted} مسودة تنتظر المعاينة والدمج')
        if blocked:
            bits.append(f'{len(blocked)} بانتظار مستند')
        if failed:
            bits.append(f'{len(failed)} تعذّر')
        _set_step(data, 'needs_input', ' — '.join(bits))
    return cm.state(data, 'research')


def run(base, data, ask=None, only_axes=None, despite_missing=False, on_progress=None, stop=None, force=False,
        draft=True, require_ready=True):
    """يكتب الأقسام الجاهزة: الحقائق ← الحساب ← الصياغة (draft=False: الحقائق والحساب فقط لملف prompt.md).
    only_axes: مفاتيح محاور بعينها. despite_missing: «اكتب رغم النقص». يرجع حالة الخطوة."""
    if not (data.get('mission') or {}).get('points'):
        raise cm.StepError('لا توجد بنود مأمورية للبحث فيها.')
    import report_v3
    if report_v3.ENABLED and draft:          # التقرير المركَّب بالكود (2026-10-20): النموذج يملأ خانات قصيرة فقط
        return report_v3.run(base, data, ask=ask, on_progress=on_progress, stop=stop, force=force)
    if ask is None:
        import case_research
        ask = lambda p: case_research.default_ask(p, 'research')          # noqa: E731
    cm.set_step(data, 'research', 'running')
    build_plan(base, data)
    cache = {}
    extract_requests(base, data, ask)
    cw.write_case_json(base, data)
    for axis in state(data)['axes']:
        if only_axes is not None and axis['key'] not in only_axes:
            continue
        ready, miss = axis_ready(data, axis)
        if require_ready and not ready and not despite_missing:
            for s in axis['sections']:
                if s['state'] in (S_PENDING, S_FAILED, S_BLOCKED, S_FACTS):
                    s.update(state=S_BLOCKED, message='بانتظار مستند: ' + '؛ '.join(miss[:4]))
            continue
        for i, sec in enumerate(axis['sections']):
            if stop and stop():
                finish_state(base, data)
                cw.write_case_json(base, data)
                return cm.state(data, 'research')
            if sec['state'] in (S_DRAFTED, S_MERGED) and not force and not sec.get('stale'):
                continue
            if not ready:
                for m in miss:
                    _note(sec, N_MISSING, f'كُتب رغم النقص: {m}')
            try:
                ok = prepare_section(base, data, axis, sec, ask, cache, force)
                if ok and draft:
                    draft_section(base, data, axis, sec, ask, i == 0)
                elif not ok:
                    sec.update(state=S_FAILED, message='لم تكتمل الحقائق أو الحساب')
            except Exception as e:
                sec.update(state=S_FAILED, message=str(e) or e.__class__.__name__)
            sec['stale'] = False
            cw.write_case_json(base, data)
            if on_progress:
                on_progress(axis, sec)
    st = finish_state(base, data)
    cw.write_case_json(base, data)
    return st


def rewrite_axis(base, data, axis_key, ask=None, despite_missing=False):
    """«أعد صياغة هذا المحور»: يعيد الحقائق والحساب والصياغة لأقسامه (المدموج يعود مسودة للمعاينة)."""
    axis = next((a for a in state(data).get('axes') or [] if a['key'] == axis_key), None)
    if axis is None:
        raise cm.StepError('المحور غير موجود.')
    import report_v3
    if report_v3.ENABLED and report_v3.is_v3(data):          # المسار المركَّب: هذا المحور وحده، والمدموج غيره لا يُمسّ
        return report_v3.rewrite_axis(base, data, axis_key, ask=ask)
    for s in axis['sections']:
        if s['state'] == S_MERGED:
            s['state'] = S_DRAFTED
    return run(base, data, ask, only_axes={axis_key}, despite_missing=despite_missing, force=True)


def merge_section(base, data, key):
    """«دمج في البحث»: المسودة المعاينة تدخل نص البحث المعتمد."""
    _a, sec = section(data, key)
    if sec is None or sec['state'] not in (S_DRAFTED, S_MERGED) or not section_text(base, sec):
        raise cm.StepError('لا مسودة لهذا القسم بعد.')
    sec.update(state=S_MERGED, progress=100, merged_at=_now())
    _mark_conclusion_stale(data)
    finish_state(base, data)
    cw.write_case_json(base, data)


def merge_all(base, data):
    n = 0
    for _a, s in all_sections(data):
        if s['state'] == S_DRAFTED and section_text(base, s):
            s.update(state=S_MERGED, progress=100, merged_at=_now())
            n += 1
    if n:
        _mark_conclusion_stale(data)
    finish_state(base, data)
    cw.write_case_json(base, data)
    return n


def set_section_text(base, data, key, text):
    """تعديل الخبير اليدوي لنص قسم: يُحفظ كما هو، والنتيجة «تحتاج إعادة توليد» بطلبه."""
    _a, sec = section(data, key)
    if sec is None:
        raise cm.StepError('القسم غير موجود.')
    if text.strip() == section_text(base, sec):
        return
    _write_section(base, sec, text)
    sec['edited'] = True
    if sec['state'] not in (S_DRAFTED, S_MERGED):
        sec['state'] = S_DRAFTED
    _mark_conclusion_stale(data)
    if cm.state(data, 'research') == 'reviewed':
        cm.set_step(data, 'research', 'done')
    finish_state(base, data)
    cw.write_case_json(base, data)


def _mark_conclusion_stale(data):
    c = (data.get('conclusion') or {}).get('v2')
    if c:
        c['stale'] = True


# ---------- (ز) الإخراج ----------

def merged_axes(base, data):
    """[(axis, [(sec, نص)])] للمحاور التي دُمجت كل أقسامها (المكتملة)، و[(axis, ما ينقص)] لغير المكتملة."""
    full, partial = [], []
    for a in state(data).get('axes') or []:
        texts = [(s, section_text(base, s)) for s in a['sections']]
        if a['sections'] and all(s['state'] == S_MERGED and t for s, t in texts):
            full.append((a, texts))
        else:
            left = [s.get('contract_title') or s.get('title') or STATE_TEXT.get(s['state'], '') for s, t in texts
                    if s['state'] != S_MERGED or not t]
            partial.append((a, left))
    return full, partial


def research_text(base, data, axes_only=None):
    """نص البحث المدموج (للنتيجة وWord): «أولاً: …:» ثم أقسامه (بعنوان العقد إن تعددت العقود)."""
    out = []
    full, _p = merged_axes(base, data)
    for a, texts in full:
        if axes_only is not None and a['key'] not in axes_only:
            continue
        out.append(heading(a))
        for s, t in texts:
            if s.get('title'):
                out.append(s['title'] + ':')
            out.append(t)
    return '\n\n'.join(out)


def notes_list(data):
    """كل الملاحظات الحمراء مجمّعة بالنوع: [(نوع، نص، موضع)]."""
    out = []
    for a, s in all_sections(data):
        where = f"{a['ordinal']}" + (f" — {s.get('contract_title') or s.get('title')}" if (s.get('contract_title') or
                                                                                         s.get('title')) else '')
        for n in s.get('notes') or []:
            out.append((n['type'], n['text'], where))
        if s['state'] == S_BLOCKED and s.get('message'):
            out.append((N_MISSING, s['message'], where))
        if s['state'] == S_FAILED and s.get('message'):
            out.append((N_MISSING, s['message'], where))
    for b in (state(data).get('minutes') or {}).get('unverified') or []:
        out.append((N_REMOVED, b, 'المحاضر'))
    merged, order = {}, []                    # الحقائق مشتركة بين محاور العقد ← الملاحظة نفسها مرة واحدة بمواضعها
    for kind, text, where in out:
        k = (kind, text)
        if k not in merged:
            merged[k] = []
            order.append(k)
        if where not in merged[k]:
            merged[k].append(where)
    return [(k[0], k[1], '، '.join(merged[k])) for k in order]


def assemble(base, data):
    """يكتب البحث.md (المدموج فقط) وملاحظات_البحث.md (الأحمر المنفصل)."""
    import case_documents as cd
    txt = research_text(base, data)
    cd._write_md(base, TEXT_REL, (txt or '') + '\n')
    r = state(data)
    r['text_sha'] = hashlib.sha1(txt.encode('utf-8')).hexdigest() if txt else ''
    lines = ['# ملاحظات البحث (للخبير — لا تدخل التقرير)', '']
    groups = {}
    for kind, text, where in notes_list(data):
        groups.setdefault(kind, []).append(f'- ({where}) {text}')
    for kind in ('فشل التدقيق', N_MISSING, N_DECISION, N_DIFF, N_REMOVED, N_DEDUP):
        if groups.get(kind):
            lines += [f'## {kind}', ''] + groups[kind] + ['']
    cd._write_md(base, NOTES_REL, '\n'.join(lines) + '\n')
    r['final'] = case_final(data)
    return txt


def case_final(data):
    """المبلغ النهائي للقضية من محور الحساب (القسم الإجمالي إن تعددت العقود)."""
    for a in state(data).get('axes') or []:
        if a['kind'] != K_CALC:
            continue
        tot = next((s for s in a['sections'] if s['kind'] == 'total'), None)
        if tot and tot.get('total_final'):
            return dict(tot['total_final'], axis=a['key'])
        fins = [s['calc']['final'] for s in a['sections'] if (s.get('calc') or {}).get('final')
                and not s['calc']['final'].get('partial')]
        if len(fins) == 1:
            return dict(fins[0], axis=a['key'])
    return None


# ---------- التسليم بملف (prompt.md) أو Copilot ----------

def export_prompt(base, data, ask=None, delivery='file'):
    """يجهّز الحقائق والأرقام للأقسام الجاهزة (المرحلة 1 بالمزوّد إن توفر) ثم يكتب prompt.md واحداً بكل الأقسام
    بالترتيب وتعليمات النتيجة. يرجع المسار."""
    import case_documents as cd
    import report_v3
    if report_v3.ENABLED:                    # المسار المركَّب: الملف = طلب الخانات القصيرة وحده (لا أرقام يكتبها النموذج)
        return report_v3.export_prompt(base, data, ask=ask, delivery=delivery)
    try:
        run(base, data, ask, draft=False)
    except Exception as e:                       # بلا مزوّد: يُكتب الملف بما تجهّز (والباقي ملاحظة حمراء)
        state(data)['export_error'] = str(e)
    rules, models, crules = _library()
    ctype = case_type(data)
    out = [f"# طلب كتابة «البحث ورأي الخبرة» و«النتيجة» — القضية {data.get('caso_no', '')}", '',
           "**التزم بالأرقام المعطاة حرفياً**: لا تحسب ولا تقرّب ولا تكتب أي رقم أو تاريخ أو مبلغ غير وارد في «الحقائق "
           "المتحقَّقة» أو «الأرقام الجاهزة» لكل قسم؛ أي رقم غريب يُرفض النص بسببه عند الاستيراد.", '',
           "## صيغة الرد", '',
           "- اكتب كل قسم تحت سطر علامته كما هو حرفياً (مثل " + MARK.format(key='A1:all') + ") ثم نص القسم.",
           f"- بعد آخر قسم اكتب السطر {CONCL_MARK} ثم فقرات النتيجة وفق «قواعد النتيجة»، فقرة لكل محور بالترتيب.",
           "- لا تكتب عناوين المحاور (يكتبها البرنامج)، ولا رموز المستندات ولا أسماء الملفات.", '',
           "## قواعد البحث", '', rules, '', "## قواعد النتيجة", '', crules, '']
    used = set()
    for axis in state(data)['axes']:
        for i, sec in enumerate(axis['sections']):
            if sec['state'] not in (S_FACTS, S_DRAFTED, S_MERGED):
                continue
            tag = 'اعتراضات' if sec['kind'] == 'objections' else _TAG.get(axis['kind'], 'إخلال')
            for m in pick_models(models, ctype, tag):
                used.add(m['title'])
            out += [MARK.format(key=sec['key']), f"### {heading(axis)}" + (f" — {sec['title']}" if sec.get('title') else ''),
                    '', section_material(data, axis, sec, i == 0), '']
    sample = [m for m in models if m['title'] in used]
    if sample:
        out += ['## نماذج من تقارير الخبير (للأسلوب فقط)', ''] + [f"### {m['title']}\n{m['text']}\n" for m in sample]
    fin = case_final(data)
    out += [CONCL_MARK, '### تعليمات النتيجة', '',
            'المحاور بالترتيب: ' + '، '.join(f"{a['ordinal']} ({a['title'][:60]})" for a in state(data)['axes']),
            (f"الحكم المالي (انسخه حرفياً في فقرة محور الحساب): ذمة {fin['debtor']} مشغولة لصالح {fin['creditor']} "
             f"بمبلغ وقدره {fin['shown']} د.ك ({fin['words']})" if fin else 'لا مبلغ نهائي محسوب بعد.')]
    blocked = [(a, s) for a, s in all_sections(data) if s['state'] not in (S_FACTS, S_DRAFTED, S_MERGED)]
    if blocked:
        out += ['', '> أقسام غير مشمولة (بانتظار مستند أو لم تكتمل حقائقها): '
                + '، '.join(f"{a['ordinal']}" + (f" — {s.get('contract_title')}" if s.get('contract_title') else '')
                           for a, s in blocked)]
    cd._write_md(base, PROMPT_REL, '\n'.join(out) + '\n')
    state(data).update(delivery=delivery, exported_at=_now())
    cw.write_case_json(base, data)
    return os.path.join(base, PROMPT_REL)


def split_reply(text):
    """{مفتاح القسم: نص} و نص النتيجة من ردّ النموذج الخارجي بالعلامات."""
    text = str(text or '').replace('\r', '')
    parts = re.split(r'(?m)^\s*(?:#+\s*)?===\s*(القسم\s+\S+?|النتيجة)\s*===\s*$', text)
    out, concl = {}, ''
    for i in range(1, len(parts) - 1, 2):
        tag, body = parts[i].strip(), parts[i + 1].strip()
        if tag == 'النتيجة':
            concl = body
        else:
            out[tag.split(None, 1)[1].strip()] = body
    return out, concl


def import_reply(base, data, text, source='file'):
    """يستورد ردّ نموذج الخبير/Copilot: كل قسم يمر بفحص الكود نفسه (الأرقام والرموز والعبارات) فيصير مسودة للمعاينة.
    يرجع {'accepted': [...], 'rejected': [(مفتاح، سبب)], 'conclusion': حالة أو ''}."""
    import report_v3
    if report_v3.ENABLED and report_v3.PROMPT_MARK in str(text or '') or (report_v3.ENABLED and '"slots"' in str(text or '')):
        return report_v3.import_reply(base, data, text, source)
    secs, concl = split_reply(text)
    if not secs and not concl:
        raise cm.StepError('لم أجد علامات الأقسام (===القسم …===) في الرد.')
    mission_raw = (data.get('mission') or {}).get('raw') or ''
    res = {'accepted': [], 'rejected': [], 'conclusion': ''}
    for key, body in secs.items():
        axis, sec = section(data, key)
        if sec is None:
            res['rejected'].append((key, 'قسم غير معروف'))
            continue
        if sec.get('facts') is None and sec['kind'] != 'total':
            res['rejected'].append((key, 'لم تُجهَّز حقائق هذا القسم'))
            continue
        clean, problems, notes = check_text(body, data, sec, mission_raw)
        if problems:
            res['rejected'].append((key, '؛ '.join(problems)))
            _note(sec, N_REMOVED, f'رُفض النص المستورد ({source}): ' + '؛ '.join(problems))
            continue
        _apply_notes(sec, notes)
        _write_section(base, sec, clean)
        sec.update(state=S_DRAFTED, progress=PROGRESS[S_DRAFTED], source=source, drafted_at=_now(), edited=False,
                   message='')
        res['accepted'].append(key)
    finish_state(base, data)
    if concl.strip():
        import conclusion_pipeline as cp2
        try:
            res['conclusion'] = cp2.accept_text(base, data, concl, source=source, include_drafted=True)
        except cm.StepError as e:
            res['conclusion'] = f'رُفضت: {e}'
    cw.write_case_json(base, data)
    return res
