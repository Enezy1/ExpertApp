# ===== report_compose.py — التقرير يُركَّب في الكود من الحقائق المتحقَّقة (2026-10-20) =====
# النموذج لا يكتب رقماً ولا تاريخاً أبداً: يملأ خانات قصيرة (التزامات كل طرف، محل العقد، رأي الخبرة في ختام المحور) بعبارات
# مرجعية مثل {{مبلغ:الإجمالي.متبقي}} و{{تاريخ:عقد1}}، والكود يستبدلها من الحقائق ويرفض أي رقم خام أو خانة من خارج المحور
# أو جنس نحوي مخالف أو عبارة ممنوعة، ويعيد الطلب مرة ثم يكتب الجملة الاحتياطية من الكود. كل ما عدا الخانات (القوائم والجداول
# والأرقام والمراجع والموضوع والإجراءات والنتيجة) يبنيه الكود. ثم يدقّق report_audit كل التقرير قبل عرضه.
# الإخراج متوافق مع المسار القائم: research2 (محور = قسم واحد) + conclusion.v2 + subject + procedures.text.
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal

import amounts
import calc
import case_facts as cf
import report_playbooks as pb

ENGINE = 'v3'
REF_TPL = 'كما هو موضح تفصيلياً في بند البحث ورأي الخبرة ({ordinal})'
_PH = re.compile(r'\{\{\s*(?:(مبلغ|تاريخ|رقم|نص|عدد|حروف)\s*:\s*)?([^{}]+?)\s*\}\}')
FORBIDDEN_MODEL = ('بادئ ذي بدء', 'مما سبق', 'صحيفة الدعوى', 'حكم الإحالة', 'أمانة', 'حافظة', 'مستند', 'مرفق',
                   '[', ']', 'ص.', 'صفحة', '«', 'كما هو موضح')
SLOT_MAX_WORDS = {'opinion': 28, 'duty_p': 16, 'duty_d': 16, 'scope': 12}


def _now():
    return datetime.now().isoformat(timespec='seconds')


def money(d):
    return cf.money(d)


def _join_ar(items):
    items = [x for x in items if x]
    if len(items) <= 1:
        return ''.join(items)
    return '، '.join(items[:-1]) + ' و' + items[-1]


# ---------- الأطراف والجنس النحوي ----------

class Party:
    def __init__(self, rec, many=False):
        self.rec = rec or {'label': 'المدعى عليه', 'gender': cf.G_M, 'company': False, 'role': 'defendant'}
        self.fem = self.rec.get('gender') in (cf.G_F, cf.G_E)
        self.certain = bool(rec) and self.rec.get('certain', True)     # الجنس ثابت من بيانات الأطراف/الاسم؟
        self.many = many
        self.label = 'المدعى عليهم' if many else self.rec['label']
        self.company = bool(self.rec.get('company'))

    @property
    def pron(self):                 # ه / ها / هم
        return 'هم' if self.many else 'ها' if self.fem else 'ه'

    def v(self, masc, fem, plural=None):
        return (plural or masc) if self.many else fem if self.fem else masc

    @property
    def full(self):                 # «الشركة المدعية» عند الشركة
        return ('الشركة ' + self.label) if self.company and self.rec.get('role') == 'plaintiff' else self.label


# ---------- السياق: الحقائق + الدفتر + القيم ----------

class Ctx:
    def __init__(self, data, facts, ctype=None):
        self.data, self.f = data, facts
        self.ctype = ctype or pb.case_type(data)
        self.pb = pb.playbook(self.ctype)
        self.L = calc.ledger(facts)
        ps = facts.get('parties') or []
        pl = [p for p in ps if p['role'] == 'plaintiff']
        df = [p for p in ps if p['role'] == 'defendant']
        self.P = Party(pl[0] if pl else {'label': 'المدعية', 'gender': cf.G_E, 'company': True, 'role': 'plaintiff'})
        self.Dd = Party(df[0] if df else None, many=len(df) > 1)
        self.contracts = facts.get('contracts') or []
        self.orders = facts.get('service_orders') or []
        self.axes = pb.mission_axes(data, self.ctype)
        self.values, self.vtype, self.desc = {}, {}, {}
        self.used_refs = set()
        self.notes = []
        self.no_inv = not (facts.get('invoices') or [])      # لم تتحقق أي فاتورة: لا يُحكم بثبوت المديونية ولا بنفيها
        self._build_values()

    # -- قيم الخانات: مفتاح ← (نص العرض، نوع الحقيقة، وصف للنموذج)
    def _put(self, key, text, ftype, desc):
        if text in (None, ''):
            return
        self.values[key], self.vtype[key], self.desc[key] = str(text), ftype, desc

    def _build_values(self):
        P, F = pb, self
        F._put('المدعية', self.P.full, P.F_PARTY, 'صفة المدعية')
        F._put('المدعى_عليه', self.Dd.label, P.F_PARTY, 'صفة المدعى عليه')
        for i, c in enumerate(self.contracts, 1):
            F._put(f'عقد{i}.رقم', f"({c['number']})" if c.get('number') else '', P.F_CONTRACT, f'رقم العقد {i}')
            F._put(f'عقد{i}.تاريخ', c.get('date'), P.F_CONTRACT, f'تاريخ العقد {i}')
        for i, o in enumerate(self.orders, 1):
            F._put(f'خط{i}.رقم', f"({o['line']})", P.F_ORDER, f'رقم الخط {i}')
            F._put(f'خط{i}.تاريخ', o.get('date'), P.F_ORDER, f'تاريخ طلب خدمة الخط {i}')
            F._put(f'خط{i}.جهاز', f"({o['device']})" if o.get('device') else '', P.F_ORDER, f'جهاز الخط {i}')
            if o.get('device_value') is not None:
                F._put(f'خط{i}.قيمة_الجهاز', money(o['device_value']), P.F_ORDER_VALUE, f'قيمة جهاز الخط {i} بالدينار')
            if o.get('commitment_months'):
                F._put(f'خط{i}.مدة', f"({int(o['commitment_months'])}) شهراً", P.F_ORDER_VALUE, f'مدة التزام الخط {i}')
            if o.get('monthly') is not None:
                F._put(f'خط{i}.شهري', money(o['monthly']), P.F_ORDER_VALUE, f'الاشتراك الشهري للخط {i}')
        for i, g in enumerate(self.L['groups'], 1):
            for k, f, d in (('فواتير', 'invoices', 'إجمالي فواتير'), ('غرامات', 'penalties', 'غرامات'),
                            ('مسدد', 'paid', 'المسدد'), ('متبقي', 'remaining', 'المتبقي'),
                            ('متبقي_أصل', 'remaining_principal', 'المتبقي من أصل المديونية'),
                            ('متبقي_غرامات', 'remaining_penalty', 'المتبقي من الغرامات')):
                F._put(f'خط{i}.{k}', money(g[f]), P.F_DEBT, f'{d} الخط {i} بالدينار')
        T = self.L['total']
        for k, f, d in (('فواتير', 'invoices', 'إجمالي الفواتير'), ('غرامات', 'penalties', 'إجمالي الغرامات'),
                        ('مسدد', 'paid', 'إجمالي المسدد'), ('متبقي', 'remaining', 'إجمالي المتبقي بذمة المدعى عليه'),
                        ('متبقي_أصل', 'remaining_principal', 'المتبقي من أصل المديونية'),
                        ('متبقي_غرامات', 'remaining_penalty', 'المتبقي من الغرامات')):
            F._put(f'الإجمالي.{k}', money(T[f]), P.F_DEBT, d + ' بالدينار')
        F._put('الإجمالي.حروف', amounts.to_words(T['remaining']), P.F_DEBT, 'إجمالي المتبقي بالحروف')
        if self.L.get('claim') is not None:
            F._put('المطالبة', money(self.L['claim']), P.F_CLAIM, 'المبلغ المطالب به بالدينار')

    # -- المراجع: أول ذكر للمستند فقط (والمواضع الحاسمة بمستند مختلف الرقم)
    def ref(self, code, page=None, force=False, docno=None):
        doc = cf.doc_of(self.f, code)
        if doc is None:
            return ''
        c = cf.cite(doc, page, docno)
        if not c or (c in self.used_refs and not force):
            return ''
        self.used_refs.add(c)
        return ' ' + c

    def lines_phrase(self, wrap=True):
        nums = [f"({o['line']})" for o in self.orders]
        if not nums:
            return ''
        if len(nums) == 1:
            return f'الخط رقم {nums[0]}'
        if len(nums) == 2:
            return f'الخطين رقمي {nums[0]} و{nums[1]}'
        return f'الخطوط أرقام {_join_ar(nums)}'

    def contract_phrase(self, c, with_date=True):
        w = self.pb['contract_word']
        s = w + (f" رقم ({c['number']})" if c.get('number') else '')
        if with_date and c.get('date'):
            s += f" المؤرخ {c['date']}"
        return s

    def commitment(self):
        ms = {o.get('commitment_months') for o in self.orders if o.get('commitment_months')}
        return int(ms.pop()) if len(ms) == 1 else None

    def same_device(self):
        ds = {o.get('device') for o in self.orders}
        return next(iter(ds)) if len(ds) == 1 and None not in ds and '' not in ds else ''

    def debtor_creditor(self):
        return self.Dd, self.P

    def allowed_types(self, kind):
        return pb.ALLOWED.get(kind, pb.ALLOWED[pb.AX_GEN])


# ---------- الخانات (ما يكتبه النموذج) ----------

def slot_specs(ctx):
    """[(slot_id, axis_kind, وصف، أقصى كلمات)] — خانات قصيرة فقط."""
    specs = []
    kinds = {a['kind'] for a in ctx.axes}
    if pb.AX_REL in kinds:
        specs.append(('rel.duty_p', pb.AX_REL, f"التزام {ctx.P.label} في سطر واحد: عبارة مصدرية تبدأ بمصدر "
                      "(مثل «تقديم …») دون ذكر الطرف", SLOT_MAX_WORDS['duty_p']))
        specs.append(('rel.duty_d', pb.AX_REL, f"التزام {ctx.Dd.label} في سطر واحد: عبارة مصدرية تبدأ بمصدر "
                      "(مثل «سداد …») دون ذكر الطرف", SLOT_MAX_WORDS['duty_d']))
        for i, _c in enumerate(ctx.contracts, 1):
            specs.append((f'rel.scope.{i}', pb.AX_REL, f"محل العقد {i} عبارة مصدرية قصيرة (مثل «تقديم خدمات …»)",
                          SLOT_MAX_WORDS['scope']))
    for a in ctx.axes:
        specs.append((f"{a['key']}.opinion", a['kind'], f"رأي الخبرة في ختام محور «{a['title']}»: جملة تبدأ بـ«ترى الخبرة "
                      "أن» تجيب عن سؤال المحور وحده", SLOT_MAX_WORDS['opinion']))
    return specs


def _axis_of_slot(ctx, sid):
    if sid.startswith('rel.'):
        return pb.AX_REL
    key = sid.rsplit('.', 1)[0]
    return next((a['kind'] for a in ctx.axes if a['key'] == key), pb.AX_GEN)


def slots_prompt(ctx, specs, errors=None):
    lines = ["أنت تكتب خانات قصيرة لتقرير خبرة قضائي كويتي بالعربية الفصحى. البرنامج يكتب الأرقام والتواريخ والجداول والمراجع "
             "بنفسه؛ أنت تكتب جملاً قصيرة فقط.",
             "قواعد ملزمة:",
             "1) لا تكتب أي رقم أو تاريخ أو مبلغ بنفسك أبداً. إن احتجت قيمة فاكتب عبارتها المرجعية حرفياً من الجدول أدناه "
             "مثل {{مبلغ:الإجمالي.متبقي}} أو {{تاريخ:عقد1.تاريخ}} أو {{رقم:عقد1.رقم}}.",
             "2) استعمل في كل خانة العبارات المرجعية المسموحة لمحورها فقط.",
             "3) لا مراجع ولا ذكر لحافظة أو مستند أو صحيفة أو حكم، ولا «بادئ ذي بدء» ولا «مما سبق».",
             f"4) الأطراف بصفاتهم: {ctx.P.full}، {ctx.Dd.label} (التزم بالتذكير/التأنيث كما هو).",
             "5) لا تكرر جملة كتبتها في خانة أخرى.",
             "أجب بـJSON فقط: {\"slots\": {\"معرّف الخانة\": \"النص\"}}",
             "## الحقائق المتاحة (للفهم فقط — لا تنسخ أرقامها)"]
    for c in ctx.contracts:
        lines.append(f"- {ctx.contract_phrase(c, False)} بين {ctx.P.label} و{ctx.Dd.label}"
                     + (f"، طريقة السداد: {c['payment']}" if c.get('payment') else ''))
    for o in ctx.orders:
        lines.append(f"- طلب خدمة: خط{'، جهاز ' + o['device'] if o.get('device') else ''}"
                     + (f"، حالة الخط: {o['status']}" if o.get('status') else ''))
    mf = ctx.f.get('minutes') or {}
    if mf.get('attended', {}).get('defendant') is False:
        lines.append(f"- {ctx.Dd.label} لم يحضر جلسات الخبرة" + (' رغم صحة إعلانه' if mf.get('notified', {}).get('defendant') else ''))
    if ctx.no_inv:
        lines.append(f"- لم تُستخرج الفواتير من المستندات بعد: لا تحكم بثبوت مديونية {ctx.Dd.label} ولا بنفيها")
    else:
        lines.append(f"- {'ثبتت' if ctx.L['total']['remaining'] > 0 else 'لم تثبت'} مديونية متبقية بذمة {ctx.Dd.label}")
    lines.append("## الخانات المطلوبة (ولكل خانة عباراتها المرجعية المسموحة وحدها)")
    for sid, kind, desc, mx in specs:
        keys = slot_keys(ctx, sid)
        lines.append(f"- {sid} (محور {kind}، حتى {mx} كلمة): {desc}"
                     + ('؛ العبارات: ' + '، '.join(f"{{{{{k}}}}} = {ctx.desc[k]}" for k in keys) if keys else ''))
    if errors:
        lines.append("## رُفضت صياغتك السابقة لهذه الأسباب — أعدها دونها:")
        lines += [f"- {e}" for e in errors]
    return '\n'.join(lines)


def slot_keys(ctx, sid):
    """العبارات المرجعية المسموحة لكل خانة: الالتزامات ومحل العقد بلا قيم (صفات الطرفين فقط)؛ رأي المحور برقم العقد
    وتاريخه؛ ورأي المديونية وحده بالمجاميع المحسوبة والحروف. لا أرقام خطوط ولا أجهزة ولا أعداد في نص النموذج."""
    base = ['المدعية', 'المدعى_عليه']
    if sid.startswith('rel.'):
        return [k for k in base if k in ctx.values]
    keys = base + [k for k in ctx.values if k.startswith('عقد') and (k.endswith('.رقم') or k.endswith('.تاريخ'))]
    if _axis_of_slot(ctx, sid) == pb.AX_DEBT:
        keys += [k for k in ('الإجمالي.متبقي', 'الإجمالي.حروف', 'الإجمالي.متبقي_أصل', 'الإجمالي.متبقي_غرامات',
                             'الإجمالي.مسدد', 'المطالبة')]
    return [k for k in keys if k in ctx.values]


def fill(text, ctx, kind, keys=None):
    """(النص بعد استبدال الخانات، [أخطاء]). يرفض: خانة غير معروفة، خانة من خارج المحور، أي رقم خام في نص النموذج."""
    errs = []
    raw = str(text or '')
    outside = _PH.sub(' ', raw).translate(cf._DIG)
    if re.search(r'\d', outside):
        errs.append('رقم خام في نص النموذج (يُمنع كتابة أي رقم إلا بعبارة مرجعية)')
    allowed = ctx.allowed_types(kind)

    def rep(m):
        typ, key = m.group(1), m.group(2).strip()
        if key not in ctx.values and typ:
            alias = {'تاريخ': '.تاريخ', 'رقم': '.رقم'}.get(typ)
            if alias and key + alias in ctx.values:
                key = key + alias
            elif typ == 'حروف' and key + '.حروف' in ctx.values:
                key = key + '.حروف'
        if key not in ctx.values:
            errs.append(f'عبارة مرجعية غير معروفة {{{{{m.group(2).strip()}}}}}')
            return ''
        if keys is not None and key not in keys:
            errs.append(f'عبارة {{{{{key}}}}} غير مسموحة في هذه الخانة')
            return ''
        if ctx.vtype[key] not in allowed:
            errs.append(f'عبارة {{{{{key}}}}} من خارج حقائق هذا المحور')
            return ''
        return ctx.values[key]
    out = _PH.sub(rep, raw)
    return ' '.join(out.split()), errs


def check_slot(sid, text, ctx, others=()):
    """(النص النهائي، [أخطاء]) لخانة واحدة من النموذج."""
    kind = _axis_of_slot(ctx, sid)
    t = ' '.join(str(text or '').replace('**', '').split()).strip(' -•')
    errs = []
    if not t:
        return '', ['خانة فارغة']
    filled, e = fill(t, ctx, kind, slot_keys(ctx, sid))
    if re.search(r'[A-Za-z]{3,}', _PH.sub(' ', t)):
        errs.append('نص غير عربي في الخانة')
    errs += e
    mx = SLOT_MAX_WORDS.get(sid.rsplit('.', 1)[-1] if not sid.startswith('rel.scope') else 'scope', 45)
    if len(filled.split()) > mx:
        errs.append(f'الخانة {sid} أطول من {mx} كلمة')
    for w in FORBIDDEN_MODEL:
        if w in t:
            errs.append(f'عبارة ممنوعة «{w}»')
            break
    if not ctx.Dd.fem and re.search(r'المدع[ىي]\s+عليها', filled):
        errs.append('تعارض الجنس النحوي: «المدعى عليها» والمدعى عليه مذكر')
    if ctx.Dd.fem and re.search(r'المدع[ىي]\s+عليه(?![اامم])', filled):
        errs.append('تعارض الجنس النحوي: «المدعى عليه» والمدعى عليها مؤنث')
    if sid.endswith('.opinion') and kind == pb.AX_DEBT and not ctx.no_inv:     # رأي يناقض الحساب بالكود يُرفض
        owes = ctx.L['total']['remaining'] > 0
        if owes and re.search(r'لم\s+(?:ت|ي)ثبت|غير\s+مشغولة|لا\s+(?:ت|ي)وجد\s+مديوني', filled):
            errs.append('رأي المديونية ينفيها والحساب أثبت متبقياً بذمة ' + ctx.Dd.label)
        if not owes and re.search(r'(?<!غير )مشغولة|ثبتت\s+مديوني', filled):
            errs.append('رأي المديونية يثبتها والحساب لم يُثبت متبقياً')
    if sid.endswith('.opinion'):
        filled = re.sub(r'^(?:و?مما\s+سبق\s+)?', '', filled)
        if not filled.startswith('ترى الخبرة'):
            filled = 'ترى الخبرة ' + (filled if re.match(r'^(?:أن|أنه|أنها)\b', filled) else 'أن ' + filled)
    import difflib
    for o in others:
        if o and difflib.SequenceMatcher(None, o, filled).ratio() > 0.85:
            errs.append(f'الخانة {sid} تكرار لخانة أخرى')
            break
    if not filled.endswith(('.', '؟')):
        filled = filled.rstrip('،,؛ ') + '.'
    return filled, errs


def draft_slots(ctx, ask, errors_by_slot=None, only=None, prev=None, attempts=2):
    """{slot_id: نص} من النموذج بعد التحقق (طلب، ثم إعادة مرة للمرفوض)، والباقي احتياطي الكود. + السجل.
    attempts=1: طلب واحد فقط (إعادة المرفوض في مسار المراحل الثلاث)."""
    specs = [s for s in slot_specs(ctx) if only is None or s[0] in only]
    out = dict(prev or {})
    log = {'attempts': 0, 'rejected': {}, 'fallback': [], 'model': []}
    if ask is None or not specs:
        for sid, *_r in specs:
            out[sid] = fallback(ctx, sid)
            log['fallback'].append(sid)
        return out, log
    todo = specs
    errs_prev = [f'{k}: {e}' for k, v in (errors_by_slot or {}).items() for e in v]
    for attempt in range(attempts):
        log['attempts'] += 1
        try:
            import ai_call_log
            ai_call_log.detail(f"خانات التقرير القصيرة — محاولة {attempt + 1} ({len(todo)} خانة)"
                               + (' [إعادة بعد تدقيق/رفض]' if errs_prev else ''))
            raw = ask(slots_prompt(ctx, todo, errs_prev or None))
        except Exception as e:                     # تعذّر المزوّد ← الاحتياطي (يُسجَّل)
            log['error'] = str(e) or e.__class__.__name__
            break
        obj = cf._parse_json(raw) or {}
        got = obj.get('slots') if isinstance(obj.get('slots'), dict) else obj
        bad, errs_prev = [], []
        for spec in todo:
            sid = spec[0]
            others = [v for k, v in out.items() if k != sid]
            text, errs = check_slot(sid, (got or {}).get(sid), ctx, others)
            if errs:
                bad.append(spec)
                log['rejected'].setdefault(sid, []).extend(errs)
                errs_prev += [f'{sid}: {e}' for e in errs]
            else:
                out[sid] = text
                if sid not in log['model']:
                    log['model'].append(sid)
        todo = bad
        ai_call_log.verdict(not todo, 'كل الخانات تحققت' if not todo else
                            f'رُفضت {len(todo)} خانة: ' + '؛ '.join(f'{s[0]}: {(log["rejected"].get(s[0]) or [""])[-1]}' for s in todo[:4]))
        if not todo:
            break
    for sid, *_r in todo:
        out[sid] = fallback(ctx, sid)
        log['fallback'].append(sid)
    return out, log


# ---------- الجمل الاحتياطية (الكود) ----------

def fallback(ctx, sid):
    P, Dd, T = ctx.P, ctx.Dd, ctx.L['total']
    if sid == 'rel.duty_p':
        return ctx.pb['plaintiff_duty'] + '.'
    if sid == 'rel.duty_d':
        return ctx.pb['defendant_duty'] + '.'
    if sid.startswith('rel.scope'):
        return ctx.pb['scope']
    key = sid.rsplit('.', 1)[0]
    kind = next((a['kind'] for a in ctx.axes if a['key'] == key), pb.AX_GEN)
    c = ctx.contracts[0] if len(ctx.contracts) == 1 else None
    cword = ctx.contract_phrase(c, False) if c else ('العقود المبينة' if ctx.contracts else 'التعامل القائم')
    owes = T['remaining'] > 0
    if kind == pb.AX_REL:
        return "ترى الخبرة أن العلاقة بين الطرفين تعاقدية تحكمها بنود العقد وشروطه العامة."
    if kind in (pb.AX_BREACH, pb.AX_DEBT) and ctx.no_inv:
        return _noinv_opinion(ctx, kind)
    if kind == pb.AX_BREACH:
        if owes:
            return (f"ترى الخبرة أن {Dd.label} {Dd.v('هو', 'هي', 'هم')} الطرف المخل بالتزاماته التعاقدية، "
                    f"وتمثل إخلال{Dd.pron} في {ctx.pb['breach']}.")
        return "ترى الخبرة عدم ثبوت إخلال أي من الطرفين بالتزاماته التعاقدية."
    if kind == pb.AX_NATURE:
        if ctx.orders:
            return "ترى الخبرة أن طلبات الخدمة المبينة جزء من العقد وتخضع لبنوده وشروطه العامة."
        return f"ترى الخبرة أن {cword} {'عقد خدمات اتصالات متنقلة' if ctx.ctype == pb.CT_TELECOM else 'عقد ملزم للجانبين'}."
    if kind == pb.AX_VALUE:
        return ("ترى الخبرة أن قيمة العقد تتحدد بما يصدر من فواتير شهرية لكل خط، "
                "وتُسدد بنظام الدفع الآجل الشهري." if ctx.ctype == pb.CT_TELECOM else
                "ترى الخبرة أن قيمة العقد وطريقة سدادها على النحو المبين أعلاه.")
    if kind == pb.AX_DEBT:
        if owes:
            return (f"ترى الخبرة أن ذمة {Dd.label} مشغولة لصالح {P.label} بمبلغ وقدره {money(T['remaining'])} د.ك "
                    f"({amounts.to_words(T['remaining'])}).")
        return f"ترى الخبرة أن ذمة {Dd.label} غير مشغولة بأي مبلغ لصالح {P.label}."
    if kind == pb.AX_DEF:
        mf = ctx.f.get('minutes') or {}
        if not any(d['by'] == 'defendant' for d in ctx.f.get('defenses') or []):
            return f"ترى الخبرة أنه لم يُبدَ من {Dd.label} أي دفع أو دفاع ينال مما انتهت إليه في المحاور السابقة."
        return "ترى الخبرة أن ما أثير من دفاع قد بُحث على النحو المبين أعلاه."
    return "ترى الخبرة أن الأوراق المقدمة لا تتضمن ما يغير مما سبق بيانه في المحاور السابقة."


# ---------- تركيب المحاور ----------

def _table(head, rows):
    out = ['| ' + ' | '.join(head) + ' |', '| ' + ' | '.join(':---:' for _ in head) + ' |']
    out += ['| ' + ' | '.join(str(c) for c in r) + ' |' for r in rows]
    return '\n'.join(out)


def parties_phrase(ctx):
    """«الشركة المدعية (شركة الاتصالات الكويتية) بصفتها مقدّمة الخدمة، والمدعى عليها (فلانة) بصفتها المشتركة» —
    من بيانات الأطراف المتحقَّقة؛ الصفة التعاقدية للاتصالات فقط."""
    P, Dd = ctx.P, ctx.Dd
    pn, dn = P.rec.get('name') or '', '' if Dd.many else (Dd.rec.get('name') or '')
    tele = ctx.ctype == pb.CT_TELECOM
    s = P.full + (f" ({pn})" if pn else '') + (f" بصفت{P.pron} مقدّم{'ة' if P.fem else ''} الخدمة" if tele else '')
    s += f"، و{Dd.label}" + (f" ({dn})" if dn else '')
    if tele:
        s += f" بصفت{Dd.pron} " + Dd.v('المشترك', 'المشتركة', 'المشتركين')
    return s


def lines_table(ctx, orders):
    """جدول الخطوط تحت العقد: الرقم، الجهاز وقسطه وقيمته، الباقة واشتراكها، مدة الالتزام — الأعمدة الواردة فقط
    (ومدة الالتزام الواحدة لكل الخطوط تُذكر في الجملة لا في الجدول)."""
    cols = [('رقم الخط', lambda o: f"({o['line']})"),
            ('الجهاز', lambda o: o.get('device') or ''),
            ('قسط الجهاز الشهري (د.ك)', lambda o: money(o['monthly']) if o.get('monthly') is not None else ''),
            ('قيمة الجهاز (د.ك)', lambda o: money(o['device_value']) if o.get('device_value') is not None else ''),
            ('الباقة', lambda o: o.get('plan') or ''),
            ('الاشتراك الشهري للباقة (د.ك)', lambda o: money(cf.dec(o['plan_monthly']))
             if cf.dec(o.get('plan_monthly')) is not None else ''),
            ('مدة الالتزام', lambda o: f"({int(o['commitment_months'])}) شهراً" if o.get('commitment_months') else '')]
    one_mon = len({o.get('commitment_months') for o in orders}) == 1
    cols = [c for c in cols if c[0] == 'رقم الخط' or (any(c[1](o) for o in orders)
                                                     and not (c[0] == 'مدة الالتزام' and one_mon))]
    if len(cols) < 2:
        return ''
    return _table([h for h, _f in cols], [[f(o) or '—' for _h, f in cols] for o in orders])


def axis_relation(ctx, a, S):
    out = []
    cs = ctx.contracts
    n = len(cs)
    P, Dd = ctx.P, ctx.Dd
    if n:
        out.append(f"العلاقة بين طرفي الدعوى علاقة تعاقدية بين {parties_phrase(ctx)}، بموجب "
                   + ('عقد واحد وهو' if n == 1 else 'عدة عقود وهي') + ' كالتالي:')
        for i, c in enumerate(cs, 1):
            page = c.get('date_page') or c.get('page')
            code = c.get('date_doc') or c.get('doc')
            scope = S.get(f'rel.scope.{i}') or ctx.pb['scope']
            scope = re.sub(r'^(?:ب|ل)(?=ت)', '', scope.rstrip('.،'))
            mine = [o for o in ctx.orders if o.get('contract') in ('', c['number'])]
            lines = ctx.lines_phrase() if mine and len(mine) == len(ctx.orders) else ''
            mon = {int(o['commitment_months']) for o in mine if o.get('commitment_months')}
            tele = ctx.ctype == pb.CT_TELECOM
            cons = ctx.pb['consideration'] + (' وأقساط شهرية للأجهزة' if tele and any(o.get('device') for o in mine) else '')
            if c.get('value') is not None:
                cons = f"مبلغ ({money(c['value'])}) د.ك"
            elif tele and mine and any(o.get('monthly') is not None or cf.dec(o.get('plan_monthly')) is not None
                                       for o in mine):
                cons += ' مبينة بالجدول التالي'
            s = (f"{i}- {ctx.contract_phrase(c)}{ctx.ref(code, page, docno=c.get('docno'))}، "
                 f"{'تلتزم' if P.fem else 'يلتزم'} بموجبه {P.label} ب{scope}" + (f" عن {lines}" if lines else ''))
            s += f"، مقابل {cons}"
            if len(mon) == 1:
                s += f"، لمدة التزام ({mon.pop()}) شهراً"
            if c.get('payment'):
                s += f"، وطريقة السداد: {c['payment'].strip(' .')}"
            out.append(s + '.')
            tbl = lines_table(ctx, mine)
            if tbl:
                out.append(tbl)
            missing = [w for w, ok in (('تاريخ العقد', c.get('date')), ('أرقام الخطوط', mine),
                                       ('الأجهزة وأقساطها', any(o.get('device') for o in mine)),
                                       ('مدة الالتزام', any(o.get('commitment_months') for o in mine))) if not ok]
            if tele and missing:
                ctx.notes.append(('ناقص', f"محور العلاقة ({ctx.contract_phrase(c, False)}): لم يُتحقَّق من "
                                  + '، '.join(missing) + ' — راجع قراءة العقد أو أعد قراءته من PDF'))
    else:
        out.append(f"لم يثبت للخبرة عقد مكتوب بين الطرفين، والعلاقة بين {parties_phrase(ctx)} على النحو الوارد بالأوراق.")
        ctx.notes.append(('ناقص', 'محور العلاقة: لم يُستخرج عقد متحقَّق'))
    out.append(f"التزامات {P.label}: {S['rel.duty_p']}")
    out.append(f"التزامات {Dd.label}: {S['rel.duty_d']}")
    return out


def axis_breach(ctx, a, S):
    T, Dd = ctx.L['total'], ctx.Dd
    out = []
    lines = ctx.lines_phrase()
    if T['remaining'] > 0:
        partial = T['paid'] > 0
        disc = ctx.orders and all(re.search(r'disconnect|مفصول', o.get('status') or '', re.I) for o in ctx.orders)
        pen = T['penalties'] > 0
        s = (f"ثبت للخبرة صدور الفواتير الشهرية" + (f" عن {lines}" if lines else '') + "، "
             f"وأن {Dd.label} {Dd.v('أخل', 'أخلت', 'أخلوا')} بالتزام{Dd.pron} بسدادها")
        if partial:
            s += ' فلم ' + Dd.v('يسدد', 'تسدد', 'يسددوا') + ' منها إلا مبالغ جزئية'
        if disc:
            s += '، حتى فُصلت الخدمة' + (' واحتُسبت غرامة التزام الأجهزة وفق شروط الاشتراك' if pen else '')
        out.append(s + '.')
        mf = ctx.f.get('minutes') or {}
        own_def = any(d['by'] == 'defendant' for d in ctx.f.get('defenses') or [])
        if not own_def:
            out.append("وسبب الإخلال الامتناع عن السداد دون سبب مشروع ثابت بالأوراق.")
    elif ctx.no_inv:
        out.append("لم تُستخرج الفواتير من المستندات المقروءة، فتعذّر على الخبرة بيان ما استحق وما سُدد منه.")
    else:
        out.append("لم يثبت للخبرة من الأوراق وجود مبالغ مستحقة غير مسددة، فلا إخلال ثابت بالتزام السداد.")
    return out


def axis_nature(ctx, a, S):
    out = []
    for i, c in enumerate(ctx.contracts, 1):
        pay = c.get('payment') or ''
        kind = 'عقد خدمات اتصالات متنقلة' if ctx.ctype == pb.CT_TELECOM else 'عقد'
        mine = [o for o in ctx.orders if o.get('contract') in ('', c['number'])]
        s = f"{ctx.contract_phrase(c, False)} {kind}" + (f" بنظام {pay.replace('شهري', '').strip()}" if pay else '')
        dev = ctx.same_device() if len(mine) > 1 else ''
        rel = next((x for x in ctx.axes if x['kind'] == pb.AX_REL), None)
        if mine and rel is not None and lines_table(ctx, mine):          # تفاصيل الخطوط في جدول محور العلاقة: لا تُكرَّر
            n = len(mine)
            out.append(s + f"، وتندرج تحته طلبات الخدمة {'للخط المبين' if n == 1 else 'للخطوط المبينة'} بجدول البند "
                       f"({rel['ordinal']})، {'وهو' if n == 1 else 'وكل منها'} خدمات اتصال"
                       + (' وجهاز بالتقسيط' if any(o.get('device') for o in mine) else '') + '.')
            continue
        out.append(s + (f"، وتندرج تحته طلبات الخدمة التالية" + (f"، لكل منها جهاز ({dev}) بالتقسيط" if dev else '') + ':'
                        if mine else '.'))
        for j, o in enumerate(mine, 1):
            t = f"{j}- الخط رقم ({o['line']})" + (f" المؤرخ {o['date']}" if o.get('date') else '') + ': '
            bits = [('خدمات اتصال وجهاز' if dev else f"جهاز ({o['device']}) بالتقسيط") if o.get('device') else 'خدمات اتصال']
            if o.get('commitment_months'):
                bits.append(f"والتزام ({int(o['commitment_months'])}) شهراً")
            out.append(t + ' '.join(bits) + '.')
    if ctx.ctype == pb.CT_TELECOM and ctx.contracts:
        out.append(f"ويخضع العقد للشروط العامة للاشتراك بخدمات {ctx.P.label}.")
    if not ctx.contracts:
        out.append("لم تتضمن الأوراق عقوداً أو طلبات خدمة متحقَّقة بين الطرفين.")
    return out


def axis_value(ctx, a, S):
    out = []
    for i, c in enumerate(ctx.contracts, 1):
        mine = [o for o in ctx.orders if o.get('contract') in ('', c['number'])]
        pay = c.get('payment') or ('دفع آجل شهري' if ctx.ctype == pb.CT_TELECOM else '')
        s = f"{i}- {ctx.contract_phrase(c, False)}: " + (f"{pay} بفاتورة شهرية لكل خط" if pay else 'لم تُبيَّن طريقة سداده')
        vals = {o.get('device_value') for o in mine if o.get('device_value') is not None}
        mon = ctx.commitment()
        if mine and len(vals) == 1 and all(o.get('device_value') is not None for o in mine):
            v = vals.pop()
            s += (f"، وقيمة جهاز {'كل خط' if len(mine) > 1 else 'الخط'} ({money(v)}) د.ك تُقسط"
                  + (f" على مدة الالتزام ({mon}) شهراً" if mon else ''))
        else:
            for o in mine:
                if o.get('device_value') is not None:
                    s += f"، وقيمة جهاز الخط رقم ({o['line']}) ({money(o['device_value'])}) د.ك"
        if c.get('value') is not None:
            s += f"، وقيمته الإجمالية ({money(c['value'])}) د.ك"
        out.append(s + '.')
    return out


def axis_debt(ctx, a, S):
    out = []
    L, T = ctx.L, ctx.L['total']
    groups = L['groups']
    if not groups:
        out.append("لم يتضمن ملف الدعوى فواتير أو مطالبات متحقَّقة يمكن تصفية الحساب على أساسها.")
        ctx.notes.append(('ناقص', 'محور المديونية: لا فواتير متحقَّقة'))
        return out
    inv_docs = {i['number']: i for i in ctx.f.get('invoices') or []}
    out.append("تفصيل الفواتير الصادرة والمسدد منها والمتبقي كالتالي:")
    for g in groups:
        first = next((inv_docs.get(r['number']) for r in g['rows'] if inv_docs.get(r['number'])), None)
        ref = ctx.ref(first['doc'], first.get('page'), docno=first.get('docno')) if first else ''
        out.append((f"الخط رقم ({g['line']})" if g['line'] else 'الفواتير') + f"{ref}:")
        rows = [[r['number'], r['date'], money(r['amount']), money(r['penalty']) if r['penalty'] else '—',
                 money(r['paid']), money(r['remaining'])] for r in g['rows']]
        rows.append(['الإجمالي', '', money(g['invoices']), money(g['penalties']) if g['penalties'] else '—',
                     money(g['paid']), money(g['remaining'])])
        out.append(_table(['رقم الفاتورة', 'التاريخ', 'المبلغ (د.ك)', 'منه غرامة التزام', 'المسدد', 'المتبقي'], rows))
    if T['penalties'] > 0:
        out.append("والغرامة الواردة في الجدول جزء من مبلغ فاتورتها، فلا تُجمع مرة ثانية.")
    if len(groups) > 1:
        out.append("والملخص لكل خط كالتالي:")
        rows = [[f"({g['line']})" if g['line'] else '—', money(g['principal']), money(g['penalties']), money(g['invoices']),
                 money(g['paid']), money(g['remaining'])] for g in groups]
        rows.append(['الإجمالي', money(T['principal']), money(T['penalties']), money(T['invoices']), money(T['paid']),
                     money(T['remaining'])])
        out.append(_table(['الخط', 'أصل المديونية', 'الغرامات', 'الإجمالي', 'المسدد', 'المتبقي'], rows))
    if T['penalties'] > 0:
        out.append(f"والمسدد كله من أصل المديونية، والمتبقي منه ({money(T['remaining_principal'])}) د.ك ومن الغرامات "
                   f"({money(T['remaining_penalty'])}) د.ك." if T['paid_penalty'] == 0 else
                   f"والمسدد من أصل المديونية ({money(T['paid_principal'])}) د.ك ومن الغرامات ({money(T['paid_penalty'])}) د.ك، "
                   f"والمتبقي من أصل المديونية ({money(T['remaining_principal'])}) د.ك ومن الغرامات "
                   f"({money(T['remaining_penalty'])}) د.ك.")
    expr = ' + '.join(money(g['remaining']) for g in groups)
    s = (f"وإجمالي المتبقي بذمة {ctx.Dd.label} = {expr} = {money(T['remaining'])} د.ك" if len(groups) > 1 else
         f"وإجمالي المتبقي بذمة {ctx.Dd.label} = {money(T['invoices'])} − {money(T['paid'])} = {money(T['remaining'])} د.ك")
    if L.get('claim') is not None:
        s += ('، وهو مطابق للمبلغ المطالب به' if L['claim_match'] else
              f"، بينما المبلغ المطالب به ({money(L['claim'])}) د.ك بفارق ({money(abs(L['claim'] - T['remaining']))}) د.ك")
    out.append(s + '.')
    if any('سبب عدم سداد' in c for c in a['clauses']) and T['remaining'] > 0:
        own_def = any(d['by'] == 'defendant' for d in ctx.f.get('defenses') or [])
        mf = ctx.f.get('minutes') or {}
        if not own_def and mf.get('attended', {}).get('defendant') is False:
            out.append(f"ولم يتبين سبب لعدم السداد لتخلف {ctx.Dd.label} عن الحضور.")
        elif not own_def:
            out.append(f"ولم يتبين للخبرة سبب لعدم السداد، إذ لم {ctx.Dd.v('يقدم', 'تقدم', 'يقدموا')} {ctx.Dd.label} ما يبرره.")
    return out


def axis_defense(ctx, a, S):
    out = []
    mf = ctx.f.get('minutes') or {}
    Dd = ctx.Dd
    defs = ctx.f.get('defenses') or []
    mine = [d for d in defs if d['by'] == 'defendant']
    n = mf.get('count') or 0
    sess = 'جلسات الخبرة'                                   # عدد الجلسات لا يُكتب أبداً
    absent = mf.get('attended', {}).get('defendant') is False
    if absent and not mine:
        s = (f"تبين من محاضر أعمال الخبرة تخلف {Dd.label} عن حضور {sess}"
             + (f" رغم صحة إعلان{Dd.pron}" if mf.get('notified', {}).get('defendant') else '')
             + f"، ولم {Dd.v('يقدم', 'تقدم', 'يقدموا')} مذكرة دفاع أو مستندات.")
        out.append(s)
    elif not mine and mf.get('attended', {}).get('defendant') is True:
        out.append(f"حضر {Dd.label} أمام الخبرة ولم {Dd.v('يقدم', 'تقدم', 'يقدموا')} مذكرة دفاع أو دفوعاً مكتوبة.")
    for d in mine:
        out.append(f"وقدم {Dd.label} مذكرة دفاع{ctx.ref(d['doc'])}" + (f" {d['summary'].rstrip('.')}" if d.get('summary') else '') + '.')
    for d in [d for d in defs if d['by'] == 'plaintiff']:
        kinds = (mf.get('submitted') or {}).get('plaintiff') or []
        extra = ' وحافظة مستندات' if 'حافظة مستندات' in kinds else ''
        out.append(f"وقدمت {ctx.P.label} مذكرة دفاعها" + (f" المؤرخة {d['date']}" if d.get('date') else '') + extra
                   + (f" {d['summary'].rstrip('.')}" if d.get('summary') else '') + '.')
    return out


AXIS_FN = {pb.AX_REL: axis_relation, pb.AX_BREACH: axis_breach, pb.AX_NATURE: axis_nature, pb.AX_VALUE: axis_value,
           pb.AX_DEBT: axis_debt, pb.AX_DEF: axis_defense}


def axis_general(ctx, a, S):
    return [f"بالاطلاع على الأوراق والمستندات المقدمة في شأن «{a['title']}» لم يتبين للخبرة ما يستوجب بياناً مستقلاً "
            "غير ما ورد في المحاور الأخرى."]


def compose_axes(ctx, S):
    """[{key, kind, ordinal, title, heading, text}] — قسم واحد لكل محور، ورأي الخبرة مرة واحدة في ختامه."""
    ctx.used_refs = set()
    out = []
    for a in ctx.axes:
        body = AXIS_FN.get(a['kind'], axis_general)(ctx, a, S)
        body.append(S.get(f"{a['key']}.opinion") or fallback(ctx, f"{a['key']}.opinion"))
        import research_pipeline as rp
        text = rp.clean_display('\n\n'.join(x for x in body if x)).strip()    # المنظّف نفسه قبل الحفظ (التدقيق على المعروض)
        out.append(dict(a, heading=f"{a['ordinal']}: {a['title']}:", text=text))
    return out


# ---------- الموضوع والإجراءات والنتيجة ----------

def subject_text(ctx):
    """الموضوع (اتصالات): تاريخ عقد الاشتراك ورقمه، الخطوط، الخدمة/الجهاز، المبلغ الشهري، مدة الالتزام، المطالبة — الناقص
    يُحذف من الجملة ويُسجَّل ملاحظة حمراء. (لغير الاتصالات: صيغة العقد العام القائمة لا تُستبدل.)"""
    miss = []
    c = ctx.contracts[0] if ctx.contracts else {}
    Dd = ctx.Dd
    ref = 'عقد اشتراك'
    if c.get('number'):
        ref += f" رقم ({c['number']})"
    else:
        miss.append('رقم عقد الاشتراك')
    if c.get('date'):
        ref += f" مؤرخ {c['date']}"
    else:
        miss.append('تاريخ عقد الاشتراك')
    lines = ctx.lines_phrase()
    if lines:
        ref += f" عن {lines}"
    else:
        miss.append('أرقام الخطوط')
    dev = ctx.same_device()
    svc = 'خدمات الاتصال' + (f" وجهاز {'' if len(ctx.orders) < 2 else ''}({dev}){' لكل خط' if len(ctx.orders) > 1 else ''}"
                             if dev else '')
    if not dev:
        miss.append('الجهاز')
    monthly = {o.get('monthly') for o in ctx.orders if o.get('monthly') is not None}
    cons = 'اشتراك شهري' + (f" قدره ({money(monthly.pop())}) د.ك" if len(monthly) == 1 else '')
    if not monthly and not any(o.get('monthly') is not None for o in ctx.orders):
        miss.append('المبلغ الشهري')
    mon = ctx.commitment()
    if not mon:
        miss.append('مدة الالتزام')
    claim = ctx.L.get('claim')
    if claim is None:
        miss.append('المبلغ المطالب به')
    to_who = 'ل' + Dd.label[1:] if Dd.label.startswith('ال') else Dd.label
    t = (f"جاءت المدعية بصحيفة مفادها أنها بموجب {ref} قامت بتقديم {svc} لصالح {Dd.label}، وذلك مقابل {cons}"
         + (f" مع مدة التزام وقدرها ({mon}) شهراً" if mon else '') + ". "
         f"وأفادت المدعية على حسب دعواها أنها قدّمت الخدمة {to_who} إلا أن {Dd.v('الأخير', 'الأخيرة', 'الأخيرين')} "
         f"لم {Dd.v('يلتزم', 'تلتزم', 'يلتزموا')} بالسداد، فتم رفع الدعوى الماثلة"
         + (f"، وطلبت الحكم بإلزام{Dd.pron} بأن {Dd.v('يؤدي', 'تؤدي', 'يؤدوا')} لها مبلغ ({money(claim)}) د.ك" if claim is not None else '')
         + '.')
    return t, miss


def procedures_text(ctx):
    """الإجراءات: المسار الوحيد case_procedures.compose (الصيغة المعتمدة + بوابة الاكتمال) بحقائق المحاضر المقروءة.
    يرجع (النص، [ما ينقص])."""
    import case_procedures as cp
    return cp.compose(ctx.data, ctx.f.get('minutes') or None)


# لا فاتورة متحقَّقة (2026-10-25): صياغتان مختلفتان للإخلال والمديونية — المتشابهتان كانتا تُفشلان التدقيق (د)
NOINV_BREACH = "أنه لم يتسنَّ بيان الإخلال بالتزام السداد، إذ لم تثبت في المستندات المقروءة فواتير مستحقة يُقاس عليها"
NOINV_DEBT = ("أن الخبرة لم تتمكن من تصفية الحساب ولا من احتساب المتبقي بذمة {who}، لعدم استخراج الفواتير الصادرة "
              "من حوافظ المدعية؛ ويلزم إعادة قراءتها")


def _noinv_opinion(ctx, kind):
    """رأي ختام المحور بلا فواتير متحقَّقة: الصياغة نفسها التي في النتيجة مسبوقة بـ«ترى الخبرة»."""
    if kind == pb.AX_BREACH:
        return 'ترى الخبرة ' + NOINV_BREACH + '.'
    return 'ترى الخبرة أنها' + NOINV_DEBT.format(who=ctx.Dd.label)[len('أن الخبرة'):] + '.'


def _installments(ctx):
    """«وأقساط الأجهزة الشهرية (10.000) د.ك للخط (58885103) و(6.000) د.ك للخط (58885104) طوال مدة الالتزام (24) شهراً»
    — للنتيجة، من طلبات الخدمة المتحقَّقة فقط؛ وإلا ''."""
    rows = [o for o in ctx.orders if o.get('monthly') is not None]
    bits = [f"({money(o['monthly'])}) د.ك للخط ({o['line']})" for o in rows]
    s = (' وأقساط الأجهزة الشهرية ' + _join_ar(bits)) if bits and len(rows) == len(ctx.orders) else ''
    mon = ctx.commitment()
    if mon:
        s += f" طوال مدة الالتزام ({mon}) شهراً"
    return s


def conclusion_paragraphs(ctx):
    """[{axis, ordinal, text}] فقرة «أن…» لكل محور من الحقائق والأرقام المحسوبة نفسها (لا من نص النموذج)."""
    T, Dd, P = ctx.L['total'], ctx.Dd, ctx.P
    c = ctx.contracts[0] if len(ctx.contracts) == 1 else None
    lines = ctx.lines_phrase()
    out = []
    for a in ctx.axes:
        k = a['kind']
        if k == pb.AX_REL:
            if ctx.contracts:
                base = ctx.contract_phrase(c) if c else 'العقود المبينة بالبحث'
                t = (f"أن العلاقة بين طرفي الدعوى علاقة تعاقدية بين {P.full} و{Dd.label} بموجب {base}"
                     + (f" عن {lines}" if lines and c else '')
                     + f"، {'تلتزم' if P.fem else 'يلتزم'} بموجبها {P.label} {ctx.pb['p_short']}، "
                     f"{Dd.v('ويلتزم', 'وتلتزم', 'ويلتزم')} {Dd.label} {ctx.pb['d_short']}")
                t += _installments(ctx)
            else:
                t = "أنه لم يثبت للخبرة عقد مكتوب بين الطرفين"
        elif k in (pb.AX_BREACH, pb.AX_DEBT) and ctx.no_inv:
            t = NOINV_BREACH if k == pb.AX_BREACH else NOINV_DEBT.format(who=Dd.label)
        elif k == pb.AX_BREACH:
            t = (f"أن {Dd.label} {Dd.v('هو', 'هي', 'هم')} الطرف المخل بالتزاماته، لامتناع{Dd.pron} عن سداد الفواتير "
                 "المستحقة دون سبب ثابت بالأوراق" if T['remaining'] > 0 else "أنه لم يثبت إخلال أي من الطرفين بالتزاماته")
        elif k == pb.AX_NATURE:
            t = (f"أن {ctx.contract_phrase(c, False) if c else 'العقود'} "
                 + ('عقد خدمات اتصالات متنقلة' if ctx.ctype == pb.CT_TELECOM else 'عقد ملزم للجانبين')
                 + (f" تندرج تحته طلبات خدمة {lines}" if lines else ''))
        elif k == pb.AX_VALUE:
            vals = {o.get('device_value') for o in ctx.orders if o.get('device_value') is not None}
            t = ("أن العقد بنظام الدفع الآجل الشهري بفاتورة لكل خط" if ctx.ctype == pb.CT_TELECOM else
                 "أن قيمة العقد وطريقة سدادها على النحو المبين بالبحث")
            if len(vals) == 1 and ctx.ctype == pb.CT_TELECOM:
                t += f"، وقيمة جهاز {'كل خط' if len(ctx.orders) > 1 else 'الخط'} ({money(vals.pop())}) د.ك تُقسط على مدة الالتزام"
        elif k == pb.AX_DEBT:
            if T['remaining'] > 0:
                t = (f"أن ذمة {Dd.label} مشغولة لصالح {P.label} بمبلغ وقدره {money(T['remaining'])} د.ك "
                     f"({amounts.to_words(T['remaining'])})")
                if T['penalties'] > 0:
                    t += (f"، منه أصل مديونية ({money(T['remaining_principal'])}) د.ك وغرامات التزام "
                          f"({money(T['remaining_penalty'])}) د.ك")
                if T['paid'] > 0:
                    t += f"، وذلك بعد خصم المسدد البالغ ({money(T['paid'])}) د.ك"
            else:
                t = f"أن ذمة {Dd.label} غير مشغولة بأي مبلغ لصالح {P.label}"
        elif k == pb.AX_DEF:
            mf = ctx.f.get('minutes') or {}
            if mf.get('attended', {}).get('defendant') is False and not any(
                    d['by'] == 'defendant' for d in ctx.f.get('defenses') or []):
                t = (f"أن {Dd.label} لم {Dd.v('يحضر', 'تحضر', 'يحضروا')} أمام الخبرة"
                     + (f" رغم صحة إعلان{Dd.pron}" if mf.get('notified', {}).get('defendant') else '')
                     + f" ولم {Dd.v('يقدم', 'تقدم', 'يقدموا')} أي دفاع")
            else:
                t = "أن ما أثير من دفاع قد بُحث ولم يغير مما انتهت إليه الخبرة"
        else:
            t = f"أن الأوراق لم تتضمن ما يستوجب بياناً مستقلاً في شأن {a['title']}"
        out.append({'axis': a['key'], 'ordinal': a['ordinal'], 'text': f"{t}، {REF_TPL.format(ordinal=a['ordinal'])}."})
    return out


# ---------- التقرير الكامل ----------

def compose(ctx, S):
    """{'subject','subject_missing','procedures','procedures_missing','axes','conclusion','final'}."""
    subj, smiss = subject_text(ctx) if ctx.ctype == pb.CT_TELECOM else ('', [])
    proc, pmiss = procedures_text(ctx)
    axes = compose_axes(ctx, S)
    concl = conclusion_paragraphs(ctx)
    T = ctx.L['total']
    final = {'amount': str(T['remaining']), 'shown': money(T['remaining']), 'words': amounts.to_words(T['remaining']),
             'debtor': ctx.Dd.label, 'creditor': ctx.P.label,
             'axis': next((a['key'] for a in axes if a['kind'] == pb.AX_DEBT), None)}
    return {'subject': subj, 'subject_missing': smiss, 'procedures': proc, 'procedures_missing': pmiss, 'axes': axes,
            'conclusion': concl, 'final': final}


def full_text(rep):
    parts = []
    if rep.get('subject'):
        parts += ['الموضوع:', rep['subject']]
    parts += ['الإجراءات:', rep['procedures'], 'البحث ورأي الخبرة:']
    for a in rep['axes']:
        parts += [a['heading'], a['text']]
    parts += ['النتيجة:'] + [p['text'] for p in rep['conclusion']]
    return '\n\n'.join(parts)


def word_count(rep):
    return len(re.findall(r'[\w؀-ۿ][\w؀-ۿ.,/()-]*', full_text(rep)))
