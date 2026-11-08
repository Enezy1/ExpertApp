# ===== calc.py — الحساب بالكود فقط لـ«البحث ورأي الخبرة» (2026-10-20) =====
# كل العمليات بـDecimal (الدينار 3 خانات، ROUND_HALF_UP عند التقريب إلى الفلس). النموذج لا يحسب أبداً: يأخذ من هنا
# الأرقام النهائية وسطور المعادلات جاهزة (Step.line) ويُفحص نصه بعد ذلك بأن كل رقم فيه وارد في قائمة الأرقام الجاهزة.
# المجاميع تُقارن بما ورد في مستندات المدعية؛ أي فرق ولو فلساً يُرجَع في diffs ليظهر في «قرارات تحتاج مراجعة».
import ast
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

FILS = Decimal('0.001')
KWD = 'د.ك'
MINUS, TIMES, DIVIDE = '−', '×', '/'
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬', '01234567890123456789.,')
_NUM = re.compile(r'-?\d[\d,]*(?:\.\d+)?')
CURRENCY_NAMES = {'KWD': 'د.ك', 'USD': 'دولار أمريكي', 'EUR': 'يورو', 'GBP': 'جنيه إسترليني', 'SAR': 'ريال سعودي',
                  'AED': 'درهم إماراتي'}
_CUR_WORDS = (('USD', ('دولار', 'usd', '$')), ('EUR', ('يورو', 'eur', '€')), ('GBP', ('استرليني', 'إسترليني', 'gbp', '£')),
              ('SAR', ('ريال سعودي', 'sar')), ('AED', ('درهم', 'aed')), ('KWD', ('د.ك', 'دينار', 'kwd', 'د ك')))


class CalcError(ValueError):
    pass


def D(x):
    """رقم من نص/عدد: الفواصل والأرقام الهندية مقبولة. نص بلا رقم ← CalcError."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, (int, float)):
        return Decimal(str(x))
    m = _NUM.search(str(x or '').translate(_DIGITS))
    if not m:
        raise CalcError(f'لا رقم في «{x}»')
    try:
        return Decimal(m.group(0).replace(',', ''))
    except InvalidOperation:
        raise CalcError(f'رقم غير صالح «{x}»')


def q3(d):
    return Decimal(d).quantize(FILS, rounding=ROUND_HALF_UP)


def currency_of(text):
    """'KWD' / 'USD' … من نص المبلغ أو العملة؛ الافتراضي الدينار."""
    t = str(text or '').lower()
    for code, words in _CUR_WORDS:
        if any(w in t for w in words):
            return code
    return 'KWD'


def fmt(d, money=True):
    """المال بالدينار: «1,155.770» (3 خانات دائماً). غير ذلك: بلا أصفار زائدة «250,000» / «0.30545»."""
    d = Decimal(d)
    if money:
        return f'{q3(d):,}'
    s = format(d.normalize(), 'f')
    if '.' in s:
        whole, frac = s.split('.')
        return f'{int(whole):,}.{frac}' if whole.lstrip('-').isdigit() else s
    return f'{int(s):,}'


def fmt_cur(d, cur='KWD'):
    """المبلغ بعملته: الدينار 3 خانات، والعملات الأخرى بلا أصفار زائدة."""
    return f"{fmt(d, money=(cur == 'KWD'))} {CURRENCY_NAMES.get(cur, cur)}"


class Step:
    """خطوة حساب: label = expr = value unit. line() هو السطر الجاهز الذي ينسخه النموذج حرفياً."""

    def __init__(self, label, expr, value, unit=KWD, money=True, kind=''):
        self.label, self.expr, self.value, self.unit, self.money, self.kind = label, expr, Decimal(value), unit, money, kind

    def shown(self):
        return fmt(self.value, self.money)

    def line(self):
        lab = f'{self.label} = ' if self.label else '= '
        return f'{lab}{self.expr} = {self.shown()} {self.unit}'.strip()

    def to_dict(self):
        return {'label': self.label, 'expr': self.expr, 'value': str(self.value), 'unit': self.unit,
                'money': self.money, 'kind': self.kind, 'line': self.line()}


def _join(values, op, money):
    return f' {op} '.join(fmt(v, money) for v in values)


def add_chain(label, values, unit=KWD, money=True, kind='sum'):
    vals = [D(v) for v in values]
    if not vals:
        raise CalcError('لا قيم للجمع')
    return Step(label, _join(vals, '+', money), sum(vals, Decimal(0)), unit, money, kind)


def subtract_chain(label, start, deductions, unit=KWD, money=True, kind='remaining'):
    """«750,000 − 45,000 − 19,089» ← 685,911."""
    s = D(start)
    ded = [D(v) for v in deductions]
    return Step(label, _join([s] + ded, MINUS, money), s - sum(ded, Decimal(0)), unit, money, kind)


def multiply(label, a, b, unit=KWD, money=True, kind='product'):
    a, b = D(a), D(b)
    v = a * b
    return Step(label, f'{fmt(a, False)} {TIMES} {fmt(b, False)}', q3(v) if money else v, unit, money, kind)


def ratio(label, a, b, c, unit='', money=False, kind='ratio'):
    """(أ × ب) / ج — مثل «كمية التربة = (50,000 × 500) / 100»."""
    a, b, c = D(a), D(b), D(c)
    if c == 0:
        raise CalcError('قسمة على صفر')
    v = (a * b) / c
    return Step(label, f'({fmt(a, False)} {TIMES} {fmt(b, False)}) {DIVIDE} {fmt(c, False)}',
                q3(v) if money else v.normalize(), unit, money, kind)


def percent(label, base, pct, unit=KWD, kind='percent'):
    base, pct = D(base), D(pct)
    return Step(label, f'{fmt(base)} {TIMES} {fmt(pct, False)}%', q3(base * pct / 100), unit, True, kind)


def convert(amount, rate, cur, date='', label='القيمة بالدينار الكويتي'):
    """تحويل العملة بسعر الخبير وتاريخه: «685,911 دولار أمريكي × 0.305450» ← بالدينار مقرَّباً إلى الفلس."""
    a, r = D(amount), D(rate)
    if r <= 0:
        raise CalcError('سعر الصرف يجب أن يكون موجباً')
    rate_txt = str(rate).strip().translate(_DIGITS) if isinstance(rate, str) else fmt(r, False)
    expr = f'{fmt(a, False)} {CURRENCY_NAMES.get(cur, cur)} {TIMES} {rate_txt}'
    return Step(label, expr, q3(a * r), KWD, True, 'fx')


# ---------- تقييم آمن لمعادلة يقترحها النموذج (الكود يحسب، النموذج يقترح البنية فقط) ----------
_ALLOWED_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}


def evaluate(expr):
    """(القيمة، [الأرقام المستعملة]) لمعادلة من أرقام و+ − × / وأقواس فقط. غير ذلك ← CalcError."""
    src = str(expr or '').translate(_DIGITS).replace('×', '*').replace('x', '*').replace('÷', '/').replace(MINUS, '-')
    src = re.sub(r'(?<=\d),(?=\d{3})', '', src)
    if not re.fullmatch(r'[\d.\s+\-*/()]+', src or ''):
        raise CalcError(f'معادلة غير مقبولة «{expr}»')
    try:
        tree = ast.parse(src, mode='eval')
    except SyntaxError:
        raise CalcError(f'معادلة غير صالحة «{expr}»')
    used = []

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            v = Decimal(str(src[n.col_offset:n.end_col_offset]))
            used.append(v)
            return v
        if isinstance(n, ast.BinOp) and type(n.op) in _ALLOWED_OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Div) and b == 0:
                raise CalcError('قسمة على صفر')
            return _ALLOWED_OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        raise CalcError(f'معادلة غير مقبولة «{expr}»')
    return ev(tree), used


def pretty_expr(expr):
    """المعادلة بالشكل المعروض: × و/ و− وفواصل الآلاف."""
    src = str(expr or '').translate(_DIGITS).replace('*', TIMES).replace('x', TIMES).replace('÷', DIVIDE)
    src = re.sub(r'(?<=\d),(?=\d{3})', '', src)
    src = re.sub(r'(?<![\d.])(\d+(?:\.\d+)?)', lambda m: fmt(Decimal(m.group(1)), False), src)
    src = re.sub(r'\s*([+×/])\s*', r' \1 ', src)
    src = re.sub(r'(?<=[\d)])\s*-\s*', f' {MINUS} ', src)
    return ' '.join(src.split())


def formula(label, expr, unit='', money=False, kind='formula'):
    v, used = evaluate(expr)
    return Step(label, pretty_expr(expr), q3(v) if money else v.normalize(), unit, money, kind), used


# ---------- جداول العقود والمطابقة ----------

def money_table(rows, head=('البيان', 'المبلغ (د.ك)')):
    """جدول markdown صغير: rows = [(البيان، قيمة|نص)]."""
    out = [f'| {head[0]} | {head[1]} |', '|---|---|']
    for lab, v in rows:
        out.append(f"| {lab} | {fmt(v) if isinstance(v, Decimal) else v} |")
    return '\n'.join(out)


def contract_account(title, totals, paid, fines=(), stated_remaining=None, claim=None, cur='KWD'):
    """حساب عقد/خط واحد: totals/paid/fines = [(البيان، قيمة)]. يرجع dict:
    total, paid, fine, remaining (Decimal)، steps [Step]، table (markdown)، diffs [نص] (فرق المحسوب عن المستند/المطالبة)."""
    money = cur == 'KWD'
    unit = CURRENCY_NAMES.get(cur, cur)
    tv = [D(v) for _, v in totals]
    pv = [D(v) for _, v in paid]
    fv = [D(v) for _, v in fines]
    steps = []
    if len(tv) > 1:
        steps.append(add_chain('إجمالي قيمة العقد', tv, unit, money, 'total'))
    total = sum(tv, Decimal(0))
    if len(pv) > 1:
        steps.append(add_chain('إجمالي المسدد', pv, unit, money, 'paid'))
    paid_sum = sum(pv, Decimal(0))
    fine_sum = sum(fv, Decimal(0))
    ded = ([paid_sum] if pv else []) + ([fine_sum] if fv else [])
    rem = subtract_chain('المتبقي' if ded else 'المستحق', total, ded, unit, money, 'remaining')
    steps.append(rem)
    rows = [('الإجمالي', fmt(total, money)), ('المسدد', fmt(paid_sum, money))]
    if fv:
        rows.append(('الغرامة', fmt(fine_sum, money)))
    rows.append(('المتبقي', fmt(rem.value, money)))
    table = money_table(rows, ('البيان', f'المبلغ ({unit})'))
    diffs = []
    if stated_remaining is not None and D(stated_remaining) != rem.value:
        diffs.append(f'{title}: المتبقي المحسوب {fmt(rem.value, money)} لا {fmt(D(stated_remaining), money)} الوارد في المستند '
                     f'(فرق {fmt(abs(rem.value - D(stated_remaining)), money)})')
    if claim is not None and D(claim) != rem.value:
        diffs.append(f'{title}: المتبقي المحسوب {fmt(rem.value, money)} لا يطابق مطالبة المدعية {fmt(D(claim), money)} '
                     f'(فرق {fmt(abs(rem.value - D(claim)), money)})')
    return {'title': title, 'total': total, 'paid': paid_sum, 'fine': fine_sum, 'remaining': rem.value, 'cur': cur,
            'steps': steps, 'table': table, 'diffs': diffs}


def sum_check(label, parts, stated=None, money=True):
    """مجموع بالكود ومطابقته لمجموع مذكور: (Step، فرق Decimal أو None، نص الفرق أو '')."""
    st = add_chain(label, parts, KWD if money else '', money, 'sum') if len(parts) > 1 else \
        Step(label, fmt(D(parts[0]), money), D(parts[0]), KWD if money else '', money, 'sum')
    if stated is None:
        return st, None, ''
    diff = st.value - D(stated)
    if diff == 0:
        return st, Decimal(0), ''
    return st, diff, (f'{label}: المجموع المحسوب {fmt(st.value, money)} لا {fmt(D(stated), money)} '
                      f'(فرق {fmt(abs(diff), money)})')


def line_item_check(label, qty, unit_price, stated_total):
    """الكمية × سعر الوحدة مقابل الإجمالي المذكور: (Step، نص الفرق أو '')."""
    s = multiply(label, qty, unit_price)
    if D(stated_total) != s.value:
        return s, f'{label}: {s.expr} = {s.shown()} لا {fmt(D(stated_total))} الوارد في المستند'
    return s, ''


def numbers_in(text):
    """كل رقم في نص كقيمة Decimal مطبَّعة (بلا فواصل وبلا أصفار زائدة)؛ أجزاء التاريخ أرقام مستقلة."""
    out = set()
    t = str(text or '').translate(_DIGITS)
    for m in re.finditer(r'\d[\d,]*(?:\.\d+)?', t):
        s = m.group(0).rstrip(',')
        for part in re.split(r'[/\\]', s):
            try:
                out.add(norm_num(part))
            except (InvalidOperation, ValueError):
                pass
    return out


def norm_num(s):
    v = Decimal(str(s).replace(',', ''))
    return format(v.normalize(), 'f') if v != v.to_integral() else str(int(v))


# ---------- دفتر المديونية للتقرير المركَّب (case_facts → report_compose) — 2026-10-20 ----------
# المتبقي = Σ الفواتير − Σ المدفوعات لكل خط/عقد. الغرامة المتضمنة في فاتورة مكوّن منها (تُعرض ولا تُجمع مرة ثانية).
# إجماليات المدعية (statement_totals) لا تدخل في أي جمع: تُقارن فقط، وأي فرق ولو فلساً ← «فرق أرقام» لا يُخفى.
DIFF_KIND = 'فرق أرقام'


def _dd(x):
    if x is None or x == '':
        return None
    return q3(D(x))


def _dkey(s):
    m = re.findall(r'\d+', str(s or '').translate(_DIGITS))
    if len(m) == 3:
        d, mo, y = (int(x) for x in m) if len(m[2]) == 4 else (int(m[2]), int(m[1]), int(m[0]))
        return (y, mo, d)
    return (9999, 0, 0)


def ledger(facts):
    """{'groups': [...], 'total': {...}, 'claim', 'claim_match', 'checks': [{'kind','text'}]} — القيم Decimal بثلاث خانات.
    المجموعة = طلب خدمة (خط) إن وُجدت خطوط، وإلا العقد، وإلا مجموعة واحدة للقضية."""
    invoices = list(facts.get('invoices') or [])
    payments = list(facts.get('payments') or [])
    orders = {o['line']: o for o in facts.get('service_orders') or [] if o.get('line')}
    checks = []

    def gkey(x):
        line = x.get('line') or ''
        if line:
            return line
        if not orders and x.get('contract'):
            return x['contract']
        return '_'
    groups, order = {}, []
    for o in facts.get('service_orders') or []:
        if o.get('line') and o['line'] not in groups:
            groups[o['line']] = {'key': o['line'], 'line': o['line'], 'contract': o.get('contract') or '', 'rows': []}
            order.append(o['line'])
    by_no = {}
    for inv in sorted(invoices, key=lambda i: (_dkey(i.get('date')), i.get('number') or '')):
        k = gkey(inv)
        if k not in groups:
            groups[k] = {'key': k, 'line': inv.get('line') or '', 'contract': inv.get('contract') or '', 'rows': []}
            order.append(k)
        amt = _dd(inv['amount'])
        pen = q3(sum((_dd(c['amount']) for c in inv.get('components') or []), Decimal(0)))
        if pen > amt:
            checks.append({'kind': DIFF_KIND, 'text': f"الفاتورة {inv.get('number')}: مكوّن الغرامة {fmt(pen)} أكبر من "
                                                       f"مبلغها {fmt(amt)} — لم تُعتمد الغرامة"})
            pen = Decimal('0.000')
        row = {'id': inv.get('id'), 'number': inv.get('number') or '', 'date': inv.get('date') or '', 'amount': amt,
               'penalty': pen, 'paid': Decimal('0.000'), 'stated_remaining': _dd(inv.get('stated_remaining'))}
        groups[k]['rows'].append(row)
        by_no[row['number']] = (k, row)
    loose = {}
    for p in payments:
        a = _dd(p.get('amount'))
        if a is None:
            continue
        hit = by_no.get(p.get('invoice') or '')
        if hit:
            hit[1]['paid'] = q3(hit[1]['paid'] + a)
            continue
        k = gkey(p) if p.get('line') else (order[0] if len(order) == 1 else '_')
        loose[k] = q3(loose.get(k, Decimal(0)) + a)
        if k not in groups:
            groups[k] = {'key': k, 'line': '', 'contract': '', 'rows': []}
            order.append(k)
    out_groups = []
    for k in order:
        g = groups[k]
        for r in g['rows']:
            r['remaining'] = q3(r['amount'] - r['paid'])
            r['paid_principal'] = q3(min(r['paid'], r['amount'] - r['penalty']))     # السداد للأصل أولاً ثم للغرامة
            r['paid_penalty'] = q3(r['paid'] - r['paid_principal'])
            if r['stated_remaining'] is not None and r['stated_remaining'] != r['remaining']:
                checks.append({'kind': DIFF_KIND, 'text': f"الفاتورة {r['number']}: المتبقي في كشف المدعية "
                               f"{fmt(r['stated_remaining'])} والمحسوب {fmt(r['amount'])} − {fmt(r['paid'])} = "
                               f"{fmt(r['remaining'])} (فرق {fmt(abs(r['stated_remaining'] - r['remaining']))})"})

        def s(f, g=g):
            return q3(sum((r[f] for r in g['rows']), Decimal(0)))
        g['invoices'], g['penalties'] = s('amount'), s('penalty')
        g['principal'] = q3(g['invoices'] - g['penalties'])
        g['unallocated_paid'] = loose.get(k, Decimal('0.000'))
        g['paid'] = q3(s('paid') + g['unallocated_paid'])
        g['paid_penalty'] = s('paid_penalty')
        g['paid_principal'] = q3(g['paid'] - g['paid_penalty'])
        g['remaining'] = q3(g['invoices'] - g['paid'])
        g['remaining_penalty'] = q3(g['penalties'] - g['paid_penalty'])
        g['remaining_principal'] = q3(g['remaining'] - g['remaining_penalty'])
        if g['rows'] or g['paid']:
            out_groups.append(g)
    tot = {f: q3(sum((g[f] for g in out_groups), Decimal(0))) for f in
           ('invoices', 'penalties', 'principal', 'paid', 'paid_penalty', 'paid_principal', 'remaining',
            'remaining_penalty', 'remaining_principal')}
    for t in facts.get('statement_totals') or []:
        a = _dd(t.get('amount'))
        if a is None:
            continue
        if t.get('scope') == 'line':
            g = next((g for g in out_groups if g['line'] == t.get('line')), None)
            if g is not None and a != g['remaining']:
                checks.append({'kind': DIFF_KIND, 'text': f"الخط {g['line']}: المتبقي في كشف المدعية {fmt(a)} والمحسوب "
                               f"{fmt(g['invoices'])} − {fmt(g['paid'])} = {fmt(g['remaining'])} (فرق "
                               f"{fmt(abs(a - g['remaining']))})"})
        elif t.get('scope') in ('all', 'contract') and a != tot['remaining']:
            checks.append({'kind': DIFF_KIND, 'text': f"إجمالي كشف المدعية {fmt(a)} والمحسوب {fmt(tot['remaining'])} "
                           f"(فرق {fmt(abs(a - tot['remaining']))})"})
    claim = _dd((facts.get('claim') or {}).get('amount'))
    if claim is not None and claim != tot['remaining']:
        checks.append({'kind': DIFF_KIND, 'text': f"المبلغ المطالب به {fmt(claim)} والمحسوب {fmt(tot['remaining'])} "
                       f"(فرق {fmt(abs(claim - tot['remaining']))})"})
    seen, uniq = set(), []
    for c in checks:
        if c['text'] not in seen:
            seen.add(c['text'])
            uniq.append(c)
    return {'groups': out_groups, 'total': tot, 'claim': claim,
            'claim_match': claim is not None and claim == tot['remaining'], 'checks': uniq}
