# ===== report_audit.py — المدقّق النهائي قبل عرض التقرير (2026-10-20) =====
# يعمل على التقرير المركَّب (report_compose.compose) والسياق (الحقائق والدفتر). أي خطأ ← يفشل الإنتاج: يعيد report_v3
# الصياغة تلقائياً مرة واحدة بقائمة الأخطاء، فإن بقي خطأ يُعرض بخط أحمر «فشل التدقيق» مع الأسباب ولا يُعرض النص كأنه سليم.
# الفحوص:
#  (أ) كل رقم/تاريخ في النص موجود في الحقائق المحسوبة بالصيغة نفسها (المال 3 خانات عشرية، التاريخ dd/mm/yyyy).
#  (ب) المجموع النهائي = مجموع المتبقي لكل الخطوط/العقود = رقم النتيجة، ومقارنته بالمطالبة (الفرق ملاحظة لا يُخفى).
#  (ج) لا فاتورة/دفعة تُسرد في موضع سردي (الجداول فقط، ومرة واحدة).
#  (د) لا جملتان بتشابه أعلى من 85%.   (هـ) العناوين ≤ 12 كلمة.   (و) لا رموز داخلية ولا مراجع محظورة.
#  (ز) توافق الجنس النحوي.   (ح) لا غرامة تُجمع مرتين.   (ط) كل محور من المأمورية مجاب مرة واحدة.
#  (ي) عدد فقرات النتيجة = عدد المحاور.   (ك) الجزء 8: لا رقم/مبلغ في محور من خارج أنواع حقائقه المسموحة.
import difflib
import re
from decimal import Decimal

import calc
import case_facts as cf
import report_playbooks as pb

SIM_MAX = 0.85
HEAD_MAX_WORDS = 12
_DATE = re.compile(r'(?<![\d/])\d{1,4}[/\-]\d{1,2}[/\-]\d{1,4}(?![\d/])')
_MONEY = re.compile(r'(?<![\d.,])\d{1,3}(?:,\d{3})*\.\d+(?![\d.])')
_INT = re.compile(r'(?<![\d.,/\-])\d+(?![\d.,/\-]|\s*-\s)')
FORBIDDEN = (('[يُكتب]', 'علامة «[يُكتب]»'), ('[يكتب]', 'علامة «[يكتب]»'), ('{{', 'عبارة مرجعية لم تُستبدل'),
             ('(صحيفة الدعوى)', 'مرجع محظور «(صحيفة الدعوى)»'), ('(حكم الإحالة)', 'مرجع محظور «(حكم الإحالة)»'),
             ('بادئ ذي بدء', 'عبارة «بادئ ذي بدء»'), ('مما سبق', 'عبارة «مما سبق»'), ('أمانة', 'ذكر أمانة الخبير'),
             ('None', 'قيمة فارغة None'), ('null', 'قيمة فارغة null'))
_CODES = re.compile(r'\[\s*[PDMR]\d+(?:-\d+)?[^\]]*\]|(?<![\w])[PDM]\d+-\d+(?![\w])|\b(?:ص|صفحة)\s*\d+\b|'
                    r'[^\s()«»"]+\.(?:pdf|docx?|md|txt|xlsx?)\b', re.I)


def _table_line(ln):
    return ln.strip().startswith('|')


def _prose(text):
    return '\n'.join(l for l in str(text or '').splitlines() if not _table_line(l))


def sentences(text):
    out = []
    for par in _prose(text).split('\n'):
        if re.match(r'^\s*\d{1,2}\s*-\s', par) or par.rstrip().endswith(':'):
            continue                  # بنود القوائم وعناوين الجداول بنية متكررة عمداً (سطر لكل عقد/خط)، لا تكرار سردي
        for s in re.split(r'(?<=[.؟!])\s+', par):
            s = ' '.join(s.split())
            if len(s.split()) >= 6:
                out.append(s)
    return out


DEDUP_MIN = 0.95                  # جملة تشابه سابقتها بهذه النسبة فأكثر = تكرار يُحذف بالكود (لا يُفشل المحور)


def dedupe(rep, ratio=DEDUP_MIN):
    """يحذف بالكود الجملة المكررة (تشابه ≥ ratio مع جملة سابقة) من الموضوع والإجراءات والمحاور — بدل إفشال المحور بـ(د).
    الجداول وبنود القوائم وعناوينها لا تُمسّ. يرجع (التقرير، [(الموضع، الجملة المحذوفة)])."""
    seen, removed = [], []

    def clean(where, text):
        lines = []
        for line in str(text or '').split('\n'):
            if _table_line(line) or re.match(r'^\s*\d{1,2}\s*-\s', line) or line.rstrip().endswith(':'):
                lines.append(line)
                continue
            keep = []
            for s in re.split(r'(?<=[.؟!])\s+', line):
                n = ' '.join(s.split())
                if len(n.split()) >= 6:
                    if any(difflib.SequenceMatcher(None, n, k).ratio() >= ratio for k in seen):
                        removed.append((where, n))
                        continue
                    seen.append(n)
                keep.append(s)
            lines.append(' '.join(keep))
        return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()
    out = dict(rep)
    if rep.get('subject'):
        out['subject'] = clean('الموضوع', rep['subject'])
    out['procedures'] = clean('الإجراءات', rep.get('procedures') or '')
    out['axes'] = [dict(a, text=clean(f"المحور {a['ordinal']}", a['text'])) for a in rep.get('axes') or []]
    out['dedup'] = removed
    return out, removed


class Allowed:
    """قيم الحقائق المحسوبة بصيغ العرض، مجمّعة بنوع الحقيقة (للفحص (أ) و(ك))."""

    def __init__(self, ctx):
        self.by_type = {}
        f, L = ctx.f, ctx.L
        add = self.add
        for c in ctx.contracts:
            add(pb.F_CONTRACT, c.get('number'), c.get('date'))
            if c.get('value') is not None:
                add(pb.F_CONTRACT, cf.money(c['value']))
        for o in ctx.orders:
            add(pb.F_ORDER, o.get('line'), o.get('date'))
            if o.get('device'):
                for n in re.findall(r'\d+', o['device']):
                    add(pb.F_ORDER, n)
            if o.get('device_value') is not None:
                add(pb.F_ORDER_VALUE, cf.money(o['device_value']))
            if o.get('commitment_months'):
                add(pb.F_ORDER_VALUE, str(int(o['commitment_months'])))
            if o.get('monthly') is not None:
                add(pb.F_ORDER_VALUE, cf.money(o['monthly']))
            if cf.dec(o.get('plan_monthly')) is not None:
                add(pb.F_ORDER_VALUE, cf.money(cf.dec(o['plan_monthly'])))
            for n in re.findall(r'\d+', str(o.get('plan') or '')):      # اسم الباقة بأرقامه («Always ON 15»)
                add(pb.F_ORDER, n)
        for g in L['groups']:
            add(pb.F_ORDER, g.get('line'))
            for r in g['rows']:
                add(pb.F_INVOICE, r['number'], r['date'], cf.money(r['amount']), cf.money(r['remaining']))
                if r['penalty']:
                    add(pb.F_INVOICE, cf.money(r['penalty']))
                add(pb.F_PAYMENT, cf.money(r['paid']))
            for k in ('invoices', 'penalties', 'principal', 'paid', 'paid_principal', 'paid_penalty', 'remaining',
                      'remaining_principal', 'remaining_penalty'):
                add(pb.F_DEBT, cf.money(g[k]))
        for k, v in L['total'].items():
            add(pb.F_DEBT, cf.money(v))
        if L.get('claim') is not None:
            add(pb.F_CLAIM, cf.money(L['claim']))
            add(pb.F_DEBT, cf.money(abs(L['claim'] - L['total']['remaining'])))
        for t in f.get('statement_totals') or []:
            if t.get('amount') is not None:
                add(pb.F_STATEMENT, cf.money(t['amount']))
        mf = f.get('minutes') or {}
        add(pb.F_MINUTES, mf.get('received'), mf.get('judgment'), mf.get('booked'))
        if mf.get('count'):
            add(pb.F_MINUTES, str(mf['count']))
        for d in f.get('defenses') or []:
            add(pb.F_DEFENSE, d.get('date'))
        for d in f.get('docs') or []:
            add('ref', d.get('date'), *[str(v) for v in (d.get('docno') or {}).values() if v])

    def add(self, typ, *vals):
        s = self.by_type.setdefault(typ, set())
        for v in vals:
            if v not in (None, ''):
                s.add(str(v))

    def any(self, types=None):
        out = set()
        for t, vals in self.by_type.items():
            if types is None or t in types or t == 'ref':
                out |= vals
        return out


def numbers_of(text):
    """(تواريخ، مبالغ، أعداد صحيحة) كما كُتبت في النص (الأعداد خارج التواريخ والمبالغ؛ أرقام القوائم «1-» تُهمل)."""
    t = str(text or '').translate(cf._DIG)
    dates = _DATE.findall(t)
    t2 = _DATE.sub(' ', t)
    moneys = _MONEY.findall(t2)
    t3 = _MONEY.sub(' ', t2)
    t3 = re.sub(r'(?m)^\s*\d{1,2}\s*-\s', ' ', t3)
    ints = _INT.findall(t3)
    return dates, moneys, ints


def check_numbers(where, text, allowed_vals, errs, strict_types_msg=''):
    dates, moneys, ints = numbers_of(text)
    for d in dates:
        if not re.fullmatch(r'\d{2}/\d{2}/\d{4}', d):
            errs.append(f'(أ) {where}: تاريخ بغير صيغة dd/mm/yyyy «{d}»')
        elif d not in allowed_vals:
            errs.append(f'(أ) {where}: تاريخ غير موجود في الحقائق{strict_types_msg} «{d}»')
    for m in moneys:
        if not re.fullmatch(r'\d{1,3}(?:,\d{3})*\.\d{3}', m):
            errs.append(f'(أ) {where}: مبلغ بغير ثلاث خانات عشرية «{m}»')
        elif m not in allowed_vals:
            errs.append(f'(أ) {where}: مبلغ غير موجود في الحقائق{strict_types_msg} «{m}»')
    for n in ints:
        if n not in allowed_vals:
            errs.append(f'(أ) {where}: رقم غير موجود في الحقائق{strict_types_msg} «{n}»')


def check_axis(a, every, own, errs):
    """(أ) لكل رقم في المحور ثم (ك): رقم موجود في الحقائق لكنه من نوع غير مسموح لهذا المحور (الجزء 8)."""
    where = f"المحور {a['ordinal']}"
    before = len(errs)
    check_numbers(where, a['text'], every, errs)
    bad = {e.split('«')[-1] for e in errs[before:]}
    dates, moneys, ints = numbers_of(a['text'])
    for v in dates + moneys + ints:
        if v in every and v not in own and v + '»' not in bad:
            errs.append(f"(ك) {where} ({a['title']}): «{v}» من حقائق خارج نوع هذا المحور")


def audit(rep, ctx):
    """[أخطاء] — قائمة فارغة = سليم."""
    errs = []
    A = Allowed(ctx)
    every = A.any()
    # (أ) + (ك)
    if rep.get('subject'):
        check_numbers('الموضوع', rep['subject'], every, errs)
    check_numbers('الإجراءات', rep['procedures'], every, errs)
    has_debt = any(x['kind'] == pb.AX_DEBT for x in rep['axes'])
    for a in rep['axes']:
        kinds = set(pb.ALLOWED.get(a['kind'], pb.ALLOWED[pb.AX_GEN]))
        if a['kind'] == pb.AX_BREACH and not has_debt:           # لا محور حساب: جداول الإخلال مسموحة فيه
            kinds |= pb.ALLOWED[pb.AX_DEBT]
        check_axis(a, every, A.any(kinds), errs)
        if a['kind'] != pb.AX_DEBT and not (a['kind'] == pb.AX_BREACH and not has_debt):
            for r in ctx.f.get('invoices') or []:
                if cf.digits_in(a['text'], r['number']):
                    errs.append(f"(ك) المحور {a['ordinal']} ({a['title']}) يذكر رقم الفاتورة {r['number']} من خارج نوعه")
    for p in rep['conclusion']:
        check_numbers(f"النتيجة ({p['ordinal']})", p['text'], every, errs)
    # (ب)
    T = ctx.L['total']
    s = sum((g['remaining'] for g in ctx.L['groups']), Decimal(0))
    if calc.q3(s) != T['remaining']:
        errs.append(f"(ب) مجموع المتبقي للخطوط {cf.money(s)} ≠ الإجمالي {cf.money(T['remaining'])}")
    debt = next((p for p in rep['conclusion'] if next((a for a in rep['axes'] if a['key'] == p['axis']), {}).get('kind')
                 == pb.AX_DEBT), None)
    no_inv = getattr(ctx, 'no_inv', False)       # لا فاتورة متحقَّقة: لا مبلغ محسوب يُطالَب به (الفقرة تقول «لم تتمكن»)
    if debt is not None and not no_inv and T['remaining'] > 0 and cf.money(T['remaining']) not in debt['text']:
        errs.append(f"(ب) فقرة المديونية في النتيجة لا تحمل المبلغ المحسوب {cf.money(T['remaining'])}")
    if debt is not None:
        others = [m for m in numbers_of(debt['text'])[1] if m not in A.any({pb.F_DEBT, pb.F_CLAIM})]
        if others:
            errs.append(f"(ب) فقرة المديونية في النتيجة تحمل مبالغ غير محسوبة: {'، '.join(others)}")
    dax = next((a for a in rep['axes'] if a['kind'] == pb.AX_DEBT), None)
    if dax is not None and not no_inv and T['remaining'] > 0 and cf.money(T['remaining']) not in dax['text']:
        errs.append('(ب) محور المديونية لا يحمل المجموع النهائي المحسوب')
    if ctx.L.get('claim') is not None and not ctx.L['claim_match']:
        if not any('المطالب به' in c['text'] for c in ctx.L['checks']):
            errs.append('(ب) فرق المطالبة غير مسجّل في «قرارات تحتاج مراجعة»')
    # (ج)
    alltext = [('الموضوع', rep.get('subject') or ''), ('الإجراءات', rep['procedures'])] + \
              [(f"المحور {a['ordinal']}", a['text']) for a in rep['axes']] + \
              [(f"النتيجة ({p['ordinal']})", p['text']) for p in rep['conclusion']]
    for r in ctx.f.get('invoices') or []:
        prose_hits = [w for w, t in alltext if cf.digits_in(_prose(t), r['number'])]
        table_hits = sum(len(re.findall(rf'(?<!\d)0*{r["number"]}(?!\d)', '\n'.join(
            l for l in t.splitlines() if _table_line(l)))) for _w, t in alltext)
        if prose_hits:
            errs.append(f"(ج) الفاتورة {r['number']} مسرودة في نص سردي ({'، '.join(prose_hits)}) — الجداول فقط")
        if table_hits > 1:
            errs.append(f"(ج) الفاتورة {r['number']} مكررة في الجداول ({table_hits} مرات)")
    # (د)
    sents = []
    for w, t in alltext:
        if w.startswith('النتيجة'):
            continue
        sents += [(w, s) for s in sentences(t)]
    for i in range(len(sents)):
        for j in range(i + 1, len(sents)):
            r = difflib.SequenceMatcher(None, sents[i][1], sents[j][1]).ratio()
            if r > SIM_MAX:
                errs.append(f"(د) جملتان متشابهتان {int(r * 100)}% ({sents[i][0]} / {sents[j][0]}): «{sents[i][1][:60]}…»")
    concl = [p['text'] for p in rep['conclusion']]
    for i in range(len(concl)):
        for j in range(i + 1, len(concl)):
            if difflib.SequenceMatcher(None, concl[i], concl[j]).ratio() > SIM_MAX:
                errs.append(f'(د) فقرتان متشابهتان في النتيجة ({i + 1} و{j + 1})')
    # (هـ)
    for a in rep['axes']:
        if len(a['heading'].replace(':', ' ').split()) > HEAD_MAX_WORDS:
            errs.append(f"(هـ) عنوان المحور {a['ordinal']} أطول من {HEAD_MAX_WORDS} كلمة")
    # (و)
    for w, t in alltext:
        for pat, why in FORBIDDEN:
            if pat in t:
                errs.append(f'(و) {w}: {why}')
        m = _CODES.search(t)
        if m:
            errs.append(f'(و) {w}: رمز داخلي أو مرجع محظور «{m.group(0)}»')
    # (ز)
    for w, t in alltext:              # الجنس يُفحص فقط إن تحدد من بيانات الأطراف (الاسم/الصفة في الصحيفة)
        if ctx.Dd.certain and not ctx.Dd.fem and not ctx.Dd.many and re.search(r'المدع[ىي]\s+عليها(?![\w])', t):
            errs.append(f'(ز) {w}: كُتب «المدعى عليها» والمدعى عليه رجل — الصواب «المدعى عليه»')
        if ctx.Dd.certain and ctx.Dd.fem and re.search(r'المدع[ىي]\s+عليه(?![\w])', t):
            errs.append(f'(ز) {w}: كُتب «المدعى عليه» والمدعى عليها شركة/أنثى — الصواب «المدعى عليها»')
        if ctx.P.certain and ctx.P.fem and re.search(r'(?<![\w])المدعي(?![\w])(?!\s+علي)', t):
            errs.append(f'(ز) {w}: كُتب «المدعي» والمدعية شركة/أنثى — الصواب «المدعية»')
    # (ح)
    want = calc.q3(sum((calc.D(i['amount']) for i in ctx.f.get('invoices') or []), Decimal(0))
                   - sum((calc.D(p['amount']) for p in ctx.f.get('payments') or [] if p.get('amount') is not None), Decimal(0)))
    if ctx.L['groups'] and want != T['remaining']:
        errs.append(f"(ح) المتبقي {cf.money(T['remaining'])} ≠ Σالفواتير − Σالمدفوعات {cf.money(want)} (غرامة أو إجمالي جُمع مرتين؟)")
    for g in ctx.L['groups']:
        for r in g['rows']:
            if r['penalty'] and dax is not None and re.search(rf"\+\s*{re.escape(cf.money(r['penalty']))}", dax['text']):
                errs.append(f"(ح) الغرامة {cf.money(r['penalty'])} مضافة في معادلة رغم أنها ضمن فاتورتها")
    # (ط)
    kinds = [a['kind'] for a in rep['axes'] if a['kind'] != pb.AX_GEN]
    if len(kinds) != len(set(kinds)):
        errs.append('(ط) محور من المأمورية مجاب أكثر من مرة')
    if len(rep['axes']) != len(ctx.axes):
        errs.append(f"(ط) عدد المحاور {len(rep['axes'])} ≠ محاور المأمورية {len(ctx.axes)}")
    heads = [a['heading'] for a in rep['axes']]
    if len(heads) != len(set(heads)):
        errs.append('(ط) عنوان محور مكرر')
    # (ي)
    if len(rep['conclusion']) != len(rep['axes']):
        errs.append(f"(ي) فقرات النتيجة {len(rep['conclusion'])} ≠ المحاور {len(rep['axes'])}")
    for p, a in zip(rep['conclusion'], rep['axes']):
        if f"({a['ordinal']})" not in p['text'] or not p['text'].startswith(('أن', 'أنه')):
            errs.append(f"(ي) فقرة النتيجة للمحور {a['ordinal']} لا تبدأ بـ«أن» أو لا تحيل إليه")
    return list(dict.fromkeys(errs))          # الرموز (أ)…(ك) داخلية؛ العرض للخبير بـplain()


_CODE = re.compile(r'^\((?:أ|ب|ج|د|هـ|و|ز|ح|ط|ي|ك)\)\s*')
_WHAT = {'ب': 'المجموع', 'ج': 'سرد الفواتير', 'د': 'التكرار', 'هـ': 'العناوين', 'و': 'الرموز والعبارات المحظورة',
         'ز': 'الجنس النحوي', 'ح': 'الجمع المكرر', 'ط': 'المحاور', 'ي': 'النتيجة', 'أ': 'الأرقام', 'ك': 'الأرقام'}


def plain(e):
    """رسالة التدقيق بجملة عربية مفهومة بلا رموز الفحص «(ز)» ولا «≠»."""
    m = _CODE.match(e)
    out = e[m.end():] if m else e
    return out.replace(' ≠ ', ' لا يساوي ').replace('≠', 'لا يساوي').replace('Σ', 'مجموع ')


def summary_line(errs):
    """سطر واحد يُفتح للتفاصيل: «التدقيق: 3 ملاحظات (الأرقام، الجنس النحوي)»."""
    if not errs:
        return ''
    n = len(errs)
    word = 'ملاحظة واحدة' if n == 1 else 'ملاحظتان' if n == 2 else f'{n} ملاحظات' if n <= 10 else f'{n} ملاحظة'
    return f'لم يجتز البحث التدقيق بالكود: {word} — اضغط للتفاصيل'


def axes_of_errors(errs, rep):
    """مفاتيح المحاور التي تخصها الأخطاء (لإعادة صياغة خاناتها فقط)."""
    out = set()
    for e in errs:
        for a in rep['axes']:
            if f"المحور {a['ordinal']}" in e:
                out.add(a['key'])
    return out
