# ===== case_contracts.py — العقود أساس الموضوع: استخراج بالذكاء ثم تحقق الكود (2026-10-18) =====
# بعد تحويل المستندات إلى markdown تُرسل نصوصها (طلب واحد، مزوّد «استخراج» = جيميناي بحسب جدول المزوّدين)
# لاستخراج كل العقود: النوع (عقد رئيسي/عقد بين الطرفين/ملحق/أمر شراء/أمر تغيير)، التاريخ، الأطراف، نطاق الأعمال،
# القيمة، المدة، ومكانه (المستند والصفحة).
# الكود يتحقق: كل تاريخ وكل مبلغ يجب أن يرد حرفياً (بعد تطبيع الأرقام والفواصل) في markdown مستنده، وإلا يُعلَّم
# «غير متحقَّق» (أحمر في الواجهة) ولا يدخل سرد الموضوع. والنطاق بالكود: عقد أطرافه طرفا الدعوى ← «بين طرفي الدعوى»؛
# العقد الرئيسي (مع جهة ليست طرفاً) وغيره ← «خارج نطاق الدعوى» يُعرض منفصلاً ولا يدخل الموضوع إلا عند الحاجة.
# الحفظ: data['contracts'] + «العقود.md» في جذر مجلد القضية + جدول في فهرس_المستندات.md. مخزّن ببصمة النصوص.
import hashlib
import json
import os
import re
import tempfile

import case_folder as cf

CONTRACTS_NAME = '_نظام/العقود.md'
KINDS = ('عقد رئيسي', 'عقد بين الطرفين', 'ملحق', 'أمر شراء', 'أمر تغيير')
SCOPE_IN, SCOPE_MAIN, SCOPE_OUT = 'بين طرفي الدعوى', 'العقد الرئيسي', 'خارج نطاق الدعوى'
MAX_CHARS_PER_DOC = 12000
MAX_TOTAL_CHARS = 120000
SKIP_FOLDERS = (cf.MINUTES,)                    # المحاضر لا تحوي عقوداً (تُقرأ في الإجراءات)
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬', '01234567890123456789.,')
_PAGE = re.compile(r'<!--\s*صفحة\s*(\d+)\s*-->')


def _read(base, rel):
    try:
        with open(os.path.join(base, rel), encoding='utf-8') as f:
            import doc_header
            return doc_header.strip(f.read())             # الرأس لا يدخل التحقق الحرفي
    except OSError:
        return ''


def collect(base):
    """[{ref, name, file, md, text}] لكل مستند محوَّل (عدا المحاضر)، بعلامات الصفحات."""
    man = cf.load_manifest(base)['files']
    items, total = [], 0
    for rel, e in sorted(man.items()):
        if e.get('state') != 'done' or cf.kind_of(rel) in SKIP_FOLDERS:
            continue
        text = _read(base, e.get('md') or cf.md_rel(rel))
        if not text.strip():
            continue
        text = text[:MAX_CHARS_PER_DOC]
        if total + len(text) > MAX_TOTAL_CHARS:
            break
        total += len(text)
        items.append({'ref': f'D{len(items) + 1}', 'name': os.path.basename(rel), 'file': rel,
                      'md': e.get('md') or cf.md_rel(rel), 'text': text,
                      'plaint': cf.kind_of(rel) == cf.PLAINT})
    return items


PROMPT_VERSION = 3          # تغيّر الطلب (الطلبات + علاقة كل عقد بها) ← يُعاد الاستخراج مرة واحدة


def text_key(items, litigants):
    return hashlib.sha1(json.dumps([[i['file'], i['text']] for i in items] + [litigants, PROMPT_VERSION],
                                   ensure_ascii=False).encode('utf-8')).hexdigest()


def build_prompt(items, litigants):
    blocks = '\n\n'.join(f"[{it['ref']}] (الملف: {it['name']}{' — صحيفة الدعوى' if it.get('plaint') else ''})\n{it['text']}"
                         for it in items)
    return (
        "أنت مساعد خبير قضائي. أمامك نصوص مستندات قضية واحدة (بعلامات <!-- صفحة N -->). استخرج كل العقود الواردة فيها: "
        "العقد الرئيسي، والعقود المبرمة بين طرفي الدعوى، والملاحق، وأوامر الشراء، وأوامر التغيير. لا تستنتج ولا تخمّن؛ "
        "انسخ التاريخ والقيمة كما وردا حرفياً. أعد JSON فقط بهذا الشكل:\n"
        '{"contracts":[{"kind":"عقد رئيسي|عقد بين الطرفين|ملحق|أمر شراء|أمر تغيير","date":"كما ورد",'
        '"parties":["الطرف الأول","الطرف الثاني"],"scope":"نطاق الأعمال بإيجاز","value":"القيمة كما وردت مع العملة",'
        '"duration":"المدة كما وردت","summary":"ما تضمّنه العقد باختصار شديد (مثال: اشتراك شهري بقيمة 15 د.ك مع جهازين بقيمة 240 د.ك)",'
        '"doc":"D1","page":3,"between_litigants":true,'
        '"in_claim":true,"claim_reason":"لماذا يتصل (أو لا يتصل) بطلبات المدعية"}],'
        '"plaintiffs":["المدعي كما في الصحيفة"],"defendants":["المدعى عليه كما في الصحيفة"],'
        '"claim":"طلبات المدعية الختامية من الصحيفة اقتباساً حرفياً"}\n'
        f"طرفا الدعوى (من النظام، قد يكون فارغاً): {json.dumps(litigants, ensure_ascii=False)}\n"
        "خذ أطراف الدعوى وطلبات المدعية من المستند الموسوم «صحيفة الدعوى». between_litigants=true إن كان طرفا العقد هما "
        "المدعي والمدعى عليه. in_claim=true إن كانت المطالبة ناشئة عن هذا العقد أو مذكوراً في الصحيفة، مع السبب في claim_reason. "
        "ما لم يرد اكتب \"\".\n\n"
        f"المستندات:\n{blocks}")


def _parse(raw):
    if isinstance(raw, dict):
        return raw
    m = re.search(r'\{.*\}', (raw or '').strip(), re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}


def _digits(t):
    return (t or '').translate(_DIGITS)


def date_in_text(date, text):
    """التاريخ يرد حرفياً في النص (أي فاصل / - . وبأرقام عربية أو هندية، وبصفر بادئ أو بدونه)."""
    nums = re.findall(r'\d+', _digits(date))
    if len(nums) != 3:
        return False
    a, b, c = (n.lstrip('0') or '0' for n in nums)
    sep = r'\s*[/\-.\\]\s*'
    pat = rf'(?<!\d)0*{a}{sep}0*{b}{sep}0*{c}(?!\d)'
    if len(c) == 4:                    # «18/10/2026» يطابق «2026/10/18» (المذكرات تكتب السنة أولاً)
        pat += rf'|(?<!\d){c}{sep}0*{b}{sep}0*{a}(?!\d)'
    return bool(re.search(pat, _digits(text)))


def amount_in_text(value, text):
    """المبلغ (أرقامه) يرد حرفياً في النص: يُقارن بعد حذف الفواصل والمسافات بين الأرقام."""
    m = re.search(r'\d[\d,\s]*(?:\.\d+)?', _digits(value))
    if not m:
        return False
    want = re.sub(r'[,\s]', '', m.group(0)).rstrip('.')
    if len(want) < 2:
        return False
    w_int = want.split('.')[0]
    for got in re.findall(r'\d[\d,]*(?:\.\d+)?', _digits(text)):
        g = got.replace(',', '')
        if g == want or g.split('.')[0] == w_int and (g == w_int or want == w_int or g.split('.')[1:] == want.split('.')[1:]
                                                      or set(''.join(g.split('.')[1:]) + ''.join(want.split('.')[1:])) <= {'0'}):
            return True
    return False


def _page_text(text, page):
    parts = _PAGE.split(text)
    if len(parts) < 3:
        return text
    for i in range(1, len(parts) - 1, 2):
        if parts[i] == str(page):
            return parts[i + 1]
    return ''


def _norm(t):
    import case_procedures as cp
    return cp.norm_ar(t or '')


_LEGAL = re.compile(r'\b(?:ش\s*م\s*ك(?:\s*ع|\s*م)?|ذ\s*م\s*م|شركه|شركة|مؤسسه|مؤسسة|السيد|السيده)\b')


def _tokens(t):
    n = _LEGAL.sub(' ', _norm(re.sub(r'\([^)]*\)', ' ', t or '')))
    return [w for w in n.split() if len(w) > 1]


def _matches(name, people):
    """تطابق بالكلمات (لا الحرف): «شركة الاتصالات المتنقلة ش.م.ك.» = «شركة الاتصالات المتنقلة (زين)»."""
    a = _tokens(name)
    for p in people:
        b = _tokens(p)
        if not a or not b:
            continue
        common = len(set(a) & set(b))
        if common >= min(len(set(a)), len(set(b)), 3) or common / min(len(set(a)), len(set(b))) >= 0.6:
            return True
    return False


def decide_scope(c, plaintiffs, defendants):
    """(النطاق، السبب). «خارج نطاق الدعوى» لا يُعطى إلا بسبب صريح؛ عند غياب أطراف الدعوى يُؤخذ رأي النموذج."""
    parties = c.get('parties') or []
    known = bool(plaintiffs and defendants)
    has_p = any(_matches(x, plaintiffs) for x in parties)
    has_d = any(_matches(x, defendants) for x in parties)
    if (has_p and has_d) or (not known and c.get('between_litigants')):
        why = 'طرفاه هما طرفا الدعوى' if has_p and has_d else 'طرفاه هما طرفا الدعوى (بحسب قراءة المستندات)'
        return SCOPE_IN, why
    if not known:
        return SCOPE_OUT if parties else SCOPE_IN, ('أطراف الدعوى غير معروفة والعقد لا يبدو بين طرفيها' if parties
                                                    else 'لم تُذكر أطرافه')
    others = [x for x in parties if not _matches(x, plaintiffs) and not _matches(x, defendants)]
    why = ('طرفه ' + '، '.join(f'«{x}»' for x in others) + ' ليس طرفاً في الدعوى') if others else \
        'لا يجمع المدعي والمدعى عليه معاً'
    return (SCOPE_MAIN if c.get('kind') == 'عقد رئيسي' else SCOPE_OUT), why


def plaint_mention(c, plaint_text):
    """هل الصحيفة تذكر هذا العقد (بتاريخه أو قيمته أو رقم وارد فيه)؟ فحص بالكود."""
    if not plaint_text:
        return None
    if c.get('date') and date_in_text(c['date'], plaint_text):
        return True
    if c.get('value') and amount_in_text(c['value'], plaint_text):
        return True
    nums = re.findall(r'\d{5,}', _digits(' '.join([c.get('scope_of_work') or '', c.get('raw_ref') or ''])))
    return any(n in _digits(plaint_text) for n in nums)


def verify(raw, items, plaintiffs, defendants):
    """سجلات متحقَّق منها: لكل عقد checks {date, value} (None = لم يرد). يرجع (contracts, ملاحظات)."""
    by_ref = {it['ref']: it for it in items}
    out, notes = [], []
    for c in (_parse(raw).get('contracts') or []):
        if not isinstance(c, dict):
            continue
        it = by_ref.get(str(c.get('doc') or ''))
        if it is None:
            notes.append(f"عقد بمستند غير معروف «{c.get('doc')}» — أُهمل")
            continue
        kind = str(c.get('kind') or '').strip()
        kind = kind if kind in KINDS else ('عقد بين الطرفين' if 'عقد' in kind else kind or 'عقد بين الطرفين')
        try:
            page = int(str(c.get('page') or '').translate(_DIGITS))
        except ValueError:
            page = None
        rec = {'kind': kind, 'date': ' '.join(str(c.get('date') or '').split()),
               'parties': [' '.join(str(p).split()) for p in (c.get('parties') or []) if str(p).strip()][:4],
               'scope_of_work': ' '.join(str(c.get('scope') or '').split())[:300],
               'value': ' '.join(str(c.get('value') or '').split()), 'duration': ' '.join(str(c.get('duration') or '').split()),
               'summary': ' '.join(str(c.get('summary') or '').split())[:200],
               'doc': it['name'], 'file': it['file'], 'md': it['md'], 'page': page,
               'between_litigants': bool(c.get('between_litigants')),
               'in_claim': c.get('in_claim') if isinstance(c.get('in_claim'), bool) else None,
               'claim_reason': ' '.join(str(c.get('claim_reason') or '').split())[:300]}
        where = _page_text(it['text'], page) if page else it['text']
        where = where if where.strip() else it['text']
        rec['checks'] = {'date': (date_in_text(rec['date'], it['text']) if rec['date'] else None),
                         'value': (amount_in_text(rec['value'], it['text']) if rec['value'] else None),
                         'page': (bool(page) and bool(_page_text(it['text'], page).strip())) if page else None}
        rec['on_page'] = bool(rec['date']) and date_in_text(rec['date'], where)
        rec['scope'], rec['scope_reason'] = decide_scope(rec, plaintiffs, defendants)
        rec['verified'] = all(v is not False for v in (rec['checks']['date'], rec['checks']['value']))
        for k, lab in (('date', 'التاريخ'), ('value', 'القيمة')):
            if rec['checks'][k] is False:
                notes.append(f"{rec['kind']} في «{it['name']}»: {lab} «{rec[k]}» لا يرد حرفياً في المستند")
        out.append(rec)
    return out, notes


def litigants(data):
    """أطراف الدعوى من بيانات القضية بكل صيغها، ثم ما استُخرج من الصحيفة وتحقّق حرفياً (contracts['litigants'])."""
    case = data.get('case') or {}
    pl = [p for p in (case.get('plaintiffs') or []) if p] + [x for x in (case.get('plaintiff'), case.get('company')) if x]
    df = [d for d in (case.get('defendants') or []) if d]
    got = (data.get('contracts') or {}).get('litigants') or {}
    pl += [p for p in got.get('plaintiffs') or [] if p not in pl]
    df += [d for d in got.get('defendants') or [] if d not in df]
    return [' '.join(p.split()) for p in pl], [' '.join(d.split()) for d in df]


def _proven(quote, text):
    q = _norm(quote)
    return len(q.split()) >= 3 and q in _norm(text)


def read_claim(raw, items):
    """(أطراف الصحيفة، الطلبات) مما أعاده النموذج، مقبولة فقط إن وردت حرفياً في نص الصحيفة."""
    plaint = '\n'.join(it['text'] for it in items if it.get('plaint'))
    r = _parse(raw)
    names = lambda k: [' '.join(str(x).split()) for x in (r.get(k) or [])        # noqa: E731
                       if str(x).strip() and _norm(_LEGAL.sub(' ', _norm(str(x)))).strip()
                       and all(w in _norm(plaint) for w in _tokens(str(x))[:3])]
    claim = ' '.join(str(r.get('claim') or '').split())
    return ({'plaintiffs': names('plaintiffs'), 'defendants': names('defendants')},
            claim if claim and _proven(claim[:200], plaint) else '', plaint)


def extract(base, data, ask, force=False):
    """يشغّل الطلب (أو يعيد المخزّن ببصمة النصوص) ويحفظ data['contracts'] و«العقود.md». يرجع السجل أو None."""
    items = collect(base)
    pl, df = litigants(data)
    prev = data.get('contracts') or {}
    if not items:
        return prev or None
    key = text_key(items, [pl, df])
    if prev.get('key') == key and prev.get('items') is not None and not force:
        return prev
    if ask is None:
        return prev or None
    try:
        raw = ask(build_prompt(items, {'المدعون': pl, 'المدعى عليهم': df}))
    except Exception as e:
        data['contracts'] = dict(prev, error=f'تعذّر استخراج العقود بالذكاء الاصطناعي: {e}')
        return data['contracts']
    lit, claim, plaint = read_claim(raw, items)
    data['contracts'] = {'litigants': lit}
    pl, df = litigants(data)
    recs, notes = verify(raw, items, pl, df)
    import ai_call_log
    ai_call_log.verdict(True, f'{len(recs)} عقد متحقَّق' + (f'؛ أُهمل: {"؛ ".join(notes[:3])}' if notes else ''))
    for c in recs:
        c['in_plaint'] = plaint_mention(c, plaint)
    data['contracts'] = {'key': key, 'items': recs, 'notes': notes, 'docs': len(items), 'litigants': lit,
                         'claim': claim, 'has_plaint': bool(plaint)}
    try:
        attach_evidence(base, data)
    except Exception:
        pass
    write_file(base, data)
    return data['contracts']


def items(data, scope=None):
    """العقود مع إعادة حساب النطاق وسببه من الأطراف المعروفة الآن (فلا يبقى تصنيف قديم خاطئ مخزّناً)."""
    recs = (data.get('contracts') or {}).get('items') or []
    pl, df = litigants(data)
    out = []
    for c in recs:
        sc, why = decide_scope(c, pl, df) if (pl and df) or 'case' in data else (c['scope'], c.get('scope_reason', ''))
        out.append(dict(c, scope=sc, scope_reason=why))
    return [c for c in out if scope is None or c['scope'] == scope]


def render(data):
    esc = lambda s: (str(s) if s not in (None, '') else '—').replace('|', '\\|')       # noqa: E731
    mark = lambda c, k: '' if c['checks'].get(k) is not False else ' ⚠غير متحقَّق'      # noqa: E731
    out = ['# العقود', '',
           '> مستخرجة بالذكاء من نصوص المستندات، والتاريخ والقيمة متحقَّق منهما حرفياً في المستند (⚠ = لم يُتحقق).', '']
    for title, scope in (('العقود المبرمة بين طرفي الدعوى', SCOPE_IN), ('العقد الرئيسي', SCOPE_MAIN),
                         ('عقود خارج نطاق الدعوى', SCOPE_OUT)):
        rows = items(data, scope)
        out += [f'## {title}', '']
        if not rows:
            out += ['_لا شيء._', '']
            continue
        out += ['| م | النوع | التاريخ | الأطراف | نطاق الأعمال | القيمة | المدة | المستند | الصفحة |',
                '|---|---|---|---|---|---|---|---|---|']
        for i, c in enumerate(rows, 1):
            out.append(f"| {i} | {esc(c['kind'])} | {esc(c['date'])}{mark(c, 'date')} | {esc('، '.join(c['parties']))} "
                       f"| {esc(c['scope_of_work'])} | {esc(c['value'])}{mark(c, 'value')} | {esc(c['duration'])} "
                       f"| {esc(c['doc'])} | {esc(c['page'])} |")
        out.append('')
    return '\n'.join(out)


def contract_line(c):
    """سطر مختصر لعقد بين الطرفين: النوع، التاريخ، ما تضمّنه، القيمة (ما لم يتحقق حرفياً لا يُذكر رقمه)."""
    bits = [c.get('kind') or 'عقد']
    if c.get('date') and (c.get('checks') or {}).get('date') is not False:
        bits.append(f"مؤرخ {c['date']}")
    if c.get('summary'):
        bits.append(f"— {c['summary']}")
    elif c.get('scope_of_work'):
        bits.append(f"— {c['scope_of_work']}")
    if c.get('value') and (c.get('checks') or {}).get('value') is not False and c['value'] not in (c.get('summary') or ''):
        bits.append(f"بقيمة {c['value']}")
    if c.get('evidence'):
        bits.append(f"({c['evidence']})")
    return ' '.join(bits)


def not_in_plaint(data):
    """عقود بين الطرفين قُدّمت لكنها لم تُذكر في صحيفة الدعوى (للتنويه)."""
    return [c for c in items(data, SCOPE_IN) if c.get('in_plaint') is False]


def write_file(base, data):
    path = os.path.join(base, CONTRACTS_NAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.con.', suffix='.tmp', dir=os.path.dirname(path))
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write(render(data) + '\n')
    os.replace(tmp, path)
    try:                                       # جدول العقود في الفهرس أيضاً
        import case_index
        case_index.write_index(base, data)
    except Exception:
        pass
    return path


def subject_context(data, include_out=False):
    """نص العقود المتحقَّق منها لطلب «الموضوع» (بين طرفي الدعوى أولاً؛ الرئيسي/الخارجي فقط عند الطلب) + القيم المسموحة."""
    rows = [c for c in items(data) if c['verified'] and (c['scope'] == SCOPE_IN or include_out)]
    lines, allowed = [], []
    for c in rows:
        bits = [c['kind'], f"بتاريخ {c['date']}" if c['date'] else '', f"بين {' و'.join(c['parties'])}" if c['parties'] else '',
                f"نطاقه: {c['scope_of_work']}" if c['scope_of_work'] else '', f"بقيمة {c['value']}" if c['value'] else '',
                f"مدته {c['duration']}" if c['duration'] else '', f"({c['scope']})"]
        if c.get('evidence'):
            bits.append(f"— مكان الإثبات: {c['evidence']}")
        lines.append('- ' + ' '.join(b for b in bits if b))
        allowed += [v for v in (c['date'], c['value'], c['duration']) if v]
    return '\n'.join(lines), allowed


def main_contract_facts(data):
    """حقائق العقد الأساس للموضوع (أول عقد متحقَّق بين الطرفين): {contract_date, amount, duration, object}."""
    c = next((c for c in items(data, SCOPE_IN) if c['verified']), None)
    if c is None:
        return {}
    out = {'contract_date': c['date'] if c['checks']['date'] else '',
           'amount': c['value'] if c['checks']['value'] else '', 'duration': c['duration'], 'object': c['scope_of_work']}
    return {k: v for k, v in out.items() if v}


# ---------- وجه الحافظة = مكان الاستدلال على كل عقد (2026-10-19) ----------
# الصفحة الأولى للحافظة جدول «م | عدد | التاريخ | البيان»؛ كل عقد يُنسب لبنده فيها:
# «المستند رقم (n) بحافظة مستندات المدعية المؤرخة …» — يُكتب مكان الإثبات مع العقد في التقرير.
_ROW = re.compile(r'^\s*\|\s*\**\s*(\d{1,3})\s*\**\s*\|(.*)$')


def face_rows(md):
    """[(رقم البند، نصه)] من جدول وجه الحافظة (الصفحة الأولى)."""
    first = re.split(r'<!--\s*صفحة\s*2\s*-->', md or '', maxsplit=1)[0]
    out = []
    for line in first.splitlines():
        m = _ROW.match(line)
        if m:
            out.append((int(m.group(1)), re.sub(r'[*|]|<br>', ' ', m.group(2))))
    return out


def _iso_variants(d):
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', (d or '').strip())
    if not m:
        return []
    dd, mm, yy = int(m.group(1)), int(m.group(2)), m.group(3)
    return [f'{yy}-{mm:02d}-{dd:02d}', f'{dd:02d}/{mm:02d}/{yy}', f'{yy}/{mm:02d}/{dd:02d}']


def evidence_for(c, faces):
    """(وصف الحافظة، رقم البند) لأنسب بند في وجوه الحوافظ، أو None. faces: [(وصف، [(n, نص)])]."""
    nums = set(re.findall(r'\d{5,}', _digits(' '.join(str(c.get(k) or '') for k in ('scope_of_work', 'summary')))))
    dates = _iso_variants(c.get('date'))
    best = None
    for label, rows in faces:
        for n, text in rows:
            t = _digits(text)
            score = 2 * any(x in t for x in nums) + 2 * any(x in t for x in dates) + ('عقد' in t or 'اتفاق' in t)
            if score >= 2 and (best is None or score > best[0]):
                best = (score, label, n)
    return (best[1], best[2]) if best else None


def attach_evidence(base, data):
    """يكتب c['evidence'] لكل عقد من وجوه الحوافظ المحوَّلة. يرجع عدد العقود المنسوبة."""
    import case_documents
    import case_attachments
    faces = []
    for p in data.get('portfolios') or []:
        role = case_attachments._role_of(case_documents.clean_submitter(p.get('submitter')))
        for d in p['docs']:
            if 'حافظ' not in (d.get('doc_type') or '') or not d.get('md'):
                continue
            rows = face_rows(_read(base, d['md']))
            if not rows:
                continue
            side = case_attachments._side_label(data, role) if role else ''
            date = case_attachments._dmy(d.get('doc_date') or p.get('date') or '')
            label = 'حافظة مستندات' + (f' {side}' if side else '') + (f' المؤرخة {date}' if date else '')
            faces.append((label, rows))
    n = 0
    for c in (data.get('contracts') or {}).get('items') or []:
        ev = evidence_for(c, faces)
        c['evidence'] = f'المستند رقم ({ev[1]}) ب{ev[0]}' if ev else ''
        n += bool(ev)
    return n
