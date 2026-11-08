# ===== case_triage.py — المرحلة الأولى: فرز كل ملف وتلخيص محتواه بطلب ذكاء واحد (2026-10-21) =====
# طريقة الخبير: يقرأ الملف كاملاً مرة واحدة ثم يكتب. لكل ملف يدخل مجلد القضية طلب ذكاء واحد فقط:
#   • الممسوح الذي يحوّله جيميناي: الفرز مدمج في طلب التحويل نفسه — الرد markdown الصفحات ثم كتلة ```json``` واحدة في آخره.
#     الدفعة الأولى (أول 20 صفحة) تعيد الفرز الكامل (FULL)، وكل دفعة تالية تعيد فقط: هل بدأ جزء جديد ومن أي صفحة ومن قدّمه
#     وتاريخه، وأي عقد أو مبالغ جديدة (CONT). الكود يفصل النص عن JSON (split_reply) ويطبّق loop_guard على النص وحده.
#   • الملف النصي (docx، PDF بطبقة نص، txt، md، xlsx): التحويل بالكود بلا ذكاء، ثم طلب فرز واحد بنفس القالب (text_prompt).
#   • غابت كتلة JSON من دفعة أو فشلت قراءتها ← طلب فرز منفصل واحد على النص المحوَّل (احتياط فقط).
# كل قيمة تعود مع اقتباس حرفي، والكود يتحقق منها في النص المحوَّل نفسه (verify): النوع والتاريخ والصفة ورقم المحضر كما في
# case_sort.verify_part، والمستندات والمبالغ وأوجه الدفاع والحضور وتاريخ الحجز باقتباسها؛ العقد بتاريخه وقيمته حرفياً
# (case_main_contract.verify عند الاستعمال). النتيجة في manifest (e['triage'] ببصمة الملف) فلا يُعاد طلب ملف لم تتغير بصمته.
import json
import re
from datetime import datetime

TRIAGE_PURPOSE = 'الفرز'
MAX_TEXT_CHARS = 300_000          # الملف النصي يُرسل كاملاً حتى هذا الحد (طلب واحد)
_FENCE = re.compile(r'```(?:json)?\s*(\{.*\})\s*```\s*$', re.S)
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_MARKS = re.compile(r'[ً-ْٰـ]')
_LETTERS = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي', 'ة': 'ه', 'ؤ': 'و', 'ئ': 'ي'})

PARTIES = ('"parties": [{"role": "plaintiff|defendant", "name": "الاسم كما ورد", "gender": "f|m|", '
           '"quote": ""}]')
_CONTRACT = ('{"found": false, "number": "", "date": "DD/MM/YYYY", "parties": [], "scope": "", "value": "", '
             '"duration": "", "payment": "", "summary": "", "doc_no": "", "page": null, "quote": ""}')
SCHEMA_FULL = (
    '{"parts": [{"type": "حافظة|مذكرة|محضر|حكم|صحيفة|تقرير|أخرى", "pages": [1, 3],\n'
    '  "submitter_role": "plaintiff|defendant|appellant|appellee|unknown", "submitter_index": 1,\n'
    '  "submitter_as_written": "الصفة أو الاسم كما ورد حرفياً", "date": "DD/MM/YYYY", "date_as_written": "",\n'
    '  "minute_no": null, "referral": false,\n'
    f'  {PARTIES},\n'
    '  "documents":[{"no": "1", "desc": "وصف المستند", "quote": ""}],\n'
    f'  "contract": {_CONTRACT},\n'
    '  "amounts": [{"label": "فاتورة/كشف/إجمالي/مطالبة…", "amount": "", "date": "", "page": 1, "quote": ""}],\n'
    '  "defenses": [{"summary": "وجه دفاع في جملة قصيرة", "quote": ""}],\n'
    '  "attendance": {"present": [{"role": "plaintiff", "index": 1, "quote": ""}],\n'
    '                 "absent": [{"role": "defendant", "index": 1, "quote": ""}],\n'
    '                 "booking_date": "", "booking_quote": ""}}]}')
SCHEMA_CONT = (
    '{"new_parts": [{"type": "حافظة|مذكرة|محضر|حكم|صحيفة|تقرير|أخرى", "start_page": 21,\n'
    '  "submitter_role": "plaintiff|defendant|appellant|appellee|unknown", "submitter_index": 1,\n'
    '  "submitter_as_written": "", "date": "DD/MM/YYYY", "minute_no": null, "referral": false}],\n'
    f' "contracts": [{_CONTRACT}],\n'
    ' "amounts": [{"label": "", "amount": "", "date": "", "page": 21, "quote": ""}]}')
RULES = ('قواعد: كل قيمة معها quote: اقتباس حرفي قصير (3–25 كلمة) منسوخ من النص كما هو. لا تخمّن: ما لا يرد في النص '
         'اتركه فارغاً أو unknown. referral=true للحكم الذي يندب الخبرة. الأطراف من قائمة أطراف القضية بأرقامها. '
         'الحافظة جزء واحد من غلافها حتى آخر مستند فيها: مستنداتها الداخلية (مستند رقم 1، 2… فواتير، كشوف، عقود، بطاقات) '
         'تُذكر في documents ولا تُعدّ أجزاء مستقلة؛ الجزء الجديد فقط مذكرة/حافظة/محضر/حكم/صحيفة لها غلاف أو بداية مستقلة. '
         'التاريخ بصيغة DD/MM/YYYY حتى لو كُتب في النص بالسنة أولاً. لصحيفة الدعوى: parties = كل طرف باسمه كما ورد وصفته '
         '(plaintiff/defendant) وجنسه النحوي كما تكتبه الصحيفة (f لـ«المدعية/المدعى عليها»، m لـ«المدعي/المدعى عليه»، '
         'و"" إن لم يتضح).')
ASK_FULL = ('حدّد نوع كل جزء (حافظة مستندات/مذكرة دفاع/حكم/صحيفة دعوى/محضر خبرة/تقرير خبرة سابق/أخرى) — والملف المختلط '
            'يُذكر كل جزء منه وحده بنطاق صفحاته —، ومقدّمه بصفته من أطراف القضية، وتاريخه، ورقم المحضر، ثم ملخص محتواه: '
            'للحافظة قائمة مستنداتها (رقم المستند ووصفه) والعقد إن وُجد (رقمه، تاريخه، أطرافه، نطاقه، قيمته، مدته، طريقة '
            'السداد، مكانه) والفواتير والكشوف والمبالغ الرئيسية؛ للمذكرة أوجه الدفاع؛ للمحضر من حضر ومن تخلف وتاريخ حجز '
            'الدعوى للتقرير إن ورد.')


def _now():
    return datetime.now().isoformat(timespec='seconds')


def parties_text(data):
    import case_sort as cs
    ps = cs.parties_list(data or {})
    return '\n'.join(f'- {r} #{i} ({cs._ROLE_AR[r]}): {n}' for r, i, n in ps) or '- (لا أطراف مسجّلة؛ استعمل الصفة كما وردت)'


# ---------- القوالب ----------

def convert_suffix(parties, first, a, b, n):
    """ما يُلحق بطلب تحويل دفعة الصفحات [a+1..b] من n (جيميناي): كتلة ```json``` واحدة في آخر الرد."""
    head = (f'\n\nبعد نص آخر صفحة من هذه الدفعة (الصفحات {a + 1}–{b} من أصل {n}، وأرقام الصفحات في JSON بهذا الترقيم) '
            'أضف في آخر الرد كتلة واحدة فقط ```json … ``` دون علامة صفحة قبلها، فيها:\n')
    if first:
        return (head + ASK_FULL + '\n' + RULES + '\nأطراف القضية:\n' + parties + '\nالصيغة:\n' + SCHEMA_FULL)
    return (head + 'فقط ما جدّ في هذه الدفعة: هل بدأ فيها جزء جديد (مذكرة/حافظة/محضر/حكم…) ومن أي صفحة ومن قدّمه وتاريخه '
            '(new_parts فارغة إن كانت تكملة للجزء السابق)، وأي عقد أو مبالغ رئيسية جديدة وردت فيها.\n' + RULES
            + '\nأطراف القضية:\n' + parties + '\nالصيغة:\n' + SCHEMA_CONT)


def text_prompt(data, md):
    """طلب الفرز الواحد للملف النصي (وللاحتياط): النص كاملاً حتى MAX_TEXT_CHARS."""
    text = md if len(md) <= MAX_TEXT_CHARS else md[:MAX_TEXT_CHARS] + '\n… (بقية النص لم تُرسل لطوله)'
    return ('أنت خبير قضائي تقرأ ملفاً من مستندات قضية أمام إدارة الخبراء بوزارة العدل الكويتية لتفرزه وتلخّصه. '
            'اقرأ الملف كاملاً أولاً، ثم أعد JSON فقط بلا أي نص آخر.\n' + ASK_FULL + '\n' + RULES
            + '\nأطراف القضية:\n' + parties_text(data) + '\n\nالصيغة المطلوبة:\n' + SCHEMA_FULL
            + '\n\nنص الملف (بعلامات صفحاته):\n' + text)


def batch_prompt(data, items):
    """طلب فرز واحد لعدة ملفات (إعادة الفرز المجمّعة من markdown بلا OCR): items = [(معرّف، الاسم، النص)]. كل ملف يُعلَّم
    بمعرّفه، والرد {"files": {"F1": {"parts": [...]}, ...}} — والتحقق الحرفي بعده لكل ملف على نصه وحده."""
    blocks = []
    for fid, name, md in items:
        text = md if len(md) <= MAX_TEXT_CHARS else md[:MAX_TEXT_CHARS] + '\n… (بقية النص لم تُرسل لطوله)'
        blocks.append(f'=====ملف {fid}: {name}=====\n{text}\n=====نهاية الملف {fid}=====')
    ids = '، '.join(fid for fid, _n, _t in items)
    return ('أنت خبير قضائي تقرأ ملفات من مستندات قضية أمام إدارة الخبراء بوزارة العدل الكويتية لتفرزها وتلخّصها. '
            f'أمامك {len(items)} ملفاً منفصلاً ({ids})، كل ملف بين علامتيه بمعرّفه. افرز كل ملف وحده كأنه الملف الوحيد: '
            'أرقام الصفحات في كل ملف بعلامات صفحاته هو، ولا تنقل قيمة أو اقتباساً من ملف إلى آخر. اقرأ الملفات كاملة أولاً، '
            'ثم أعد JSON فقط بلا أي نص آخر.\n' + ASK_FULL + '\n' + RULES
            + '\nأطراف القضية:\n' + parties_text(data)
            + '\n\nالصيغة المطلوبة: {"files": {"<المعرّف>": ' + SCHEMA_FULL.replace('\n', ' ') + '}} — مفتاح لكل ملف بمعرّفه.'
            + '\n\nالملفات:\n' + '\n\n'.join(blocks))


def split_batch(raw, ids):
    """{معرّف: فرز الملف} من رد الطلب المجمّع؛ الملف الغائب من الرد لا يُذكر."""
    obj = parse_json(raw) or {}
    files = obj.get('files') if isinstance(obj.get('files'), dict) else obj
    out = {}
    for fid in ids:
        v = files.get(fid) if isinstance(files, dict) else None
        if isinstance(v, dict) and isinstance(v.get('parts'), list):
            out[fid] = v
    return out


def plan_batches(items, limit):
    """[[عناصر]] بدفعات حسب الحجم: كل دفعة حتى limit حرفاً تقريباً (ملف أكبر من الحد وحده في دفعته)."""
    batches, cur, size = [], [], 0
    for it in items:
        n = min(len(it[-1]), MAX_TEXT_CHARS)
        if cur and size + n > limit:
            batches.append(cur)
            cur, size = [], 0
        cur.append(it)
        size += n
    if cur:
        batches.append(cur)
    return batches


# ---------- فصل النص عن JSON ----------

def split_reply(reply):
    """(النص بلا كتلة JSON، الكائن أو None). الكتلة في آخر الرد ```json {…} ```؛ بلا سياج تُقبل {…} في آخر سطر."""
    s = (reply or '').rstrip()
    m = _FENCE.search(s)
    if m is None:
        i = s.rfind('\n{')
        if i >= 0 and s.endswith('}'):
            try:
                return s[:i].rstrip(), json.loads(s[i + 1:])
            except ValueError:
                return s, None
        return s, None
    try:
        obj = json.loads(m.group(1))
    except ValueError:
        obj = None
    return s[:m.start()].rstrip(), obj if isinstance(obj, dict) else None


def parse_json(raw):
    if isinstance(raw, dict):
        return raw
    s = re.sub(r'^```(?:json)?|```$', '', (raw or '').strip(), flags=re.M).strip()
    i, j = s.find('{'), s.rfind('}')
    if i < 0 or j < i:
        return None
    try:
        obj = json.loads(s[i:j + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


# ---------- تجميع دفعات التحويل ----------

def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def assemble(blocks, n):
    """blocks: [(a 0-based، b، obj)] بالترتيب ← {'parts': [...]} بنطاقات صفحات عامة، أو None إن غابت أي كتلة (احتياط)."""
    if not blocks or any(obj is None for _a, _b, obj in blocks):
        return None
    first = blocks[0][2]
    if not isinstance(first.get('parts'), list):
        return None
    parts = [dict(p) for p in first['parts'] if isinstance(p, dict)]
    for p in parts:
        pg = p.get('pages') or []
        if not (isinstance(pg, list) and len(pg) == 2 and _int(pg[0]) and _int(pg[1])):
            p['pages'] = [1, blocks[0][1]]

    def owner(page):
        cands = [p for p in parts if _int((p.get('pages') or [0])[0], 0) <= page]
        return max(cands, key=lambda p: _int(p['pages'][0], 0)) if cands else (parts[0] if parts else None)
    for a, b, obj in blocks[1:]:
        for np_ in obj.get('new_parts') or []:
            if not isinstance(np_, dict):
                continue
            sp = min(max(_int(np_.get('start_page'), a + 1) or a + 1, a + 1), b)
            p = {k: np_.get(k) for k in ('type', 'submitter_role', 'submitter_index', 'submitter_as_written', 'date',
                                         'date_as_written', 'minute_no', 'referral')}
            p['pages'] = [sp, b]
            parts.append(p)
            parts.sort(key=lambda x: _int(x['pages'][0], 0))
        for c in obj.get('contracts') or []:
            if isinstance(c, dict) and (c.get('found') or c.get('date') or c.get('number')):
                own = owner(_int(c.get('page'), a + 1) or a + 1)
                if own is not None:
                    if not (own.get('contract') or {}).get('found'):
                        own['contract'] = dict(c, found=True)
                    else:
                        own.setdefault('more_contracts', []).append(dict(c, found=True))
        for am in obj.get('amounts') or []:
            if isinstance(am, dict):
                own = owner(_int(am.get('page'), a + 1) or a + 1)
                if own is not None:
                    own.setdefault('amounts', []).append(am)
    parts.sort(key=lambda x: _int(x['pages'][0], 0))
    for i, p in enumerate(parts):                         # كل جزء ينتهي قبل بداية التالي، والأخير عند آخر صفحة
        start = _int(p['pages'][0], 1)
        end = (_int(parts[i + 1]['pages'][0], start) - 1) if i + 1 < len(parts) else n
        p['pages'] = [start, max(start, end)]
    return {'parts': parts}


# ---------- التحقق الحرفي ----------

def norm(t):
    t = str(t or '').translate(_DIGITS)
    t = _MARKS.sub('', t).translate(_LETTERS)
    t = re.sub(r'[|*#>`]', ' ', t)
    return ' '.join(t.split())


QUOTE_RATIO = 0.6       # الاقتباس من نص ممسوح: النموذج يصحّح أخطاء القراءة («الستحقة» ← «المستحقة») فلا يطابق حرفياً


def quote_in(quote, text, ratio=QUOTE_RATIO):
    """الاقتباس وارد في النص: حرفياً بعد التطبيع، أو أغلب كلماته (ratio) واردة فيه — للنص الممسوح بأخطاء قراءته."""
    q = norm(quote)
    if len(q) < 6:
        return False
    t = norm(text)
    if q in t:
        return True
    words = [w for w in q.split() if len(w) >= 2]
    if len(words) < 3:
        return False
    tw = set(t.split())
    return sum(1 for w in words if w in tw) / len(words) >= ratio


def _verify_extras(p, text, full=''):
    """المستندات والمبالغ والدفاع والحضور والحجز: يبقى ما ورد في نص الجزء (أو في نص الملف كله full: أرقام صفحات الدفعات
    اللاحقة قد تأتي نسبية للدفعة). يرجع (القيم، ملاحظات)."""
    import case_contracts as cc
    notes = []
    text = text if not full or full == text else text + chr(10) + full
    docs = []
    for d in p.get('documents') or []:
        if isinstance(d, dict) and (quote_in(d.get('quote'), text) or quote_in(d.get('desc'), text)):
            docs.append({'no': str(d.get('no') or '').strip(), 'desc': ' '.join(str(d.get('desc') or '').split())})
        elif isinstance(d, dict) and (d.get('desc') or d.get('quote')):
            notes.append(f"مستند «{str(d.get('desc') or '')[:30]}» بلا اقتباس حرفي")
    amounts = []
    for a in p.get('amounts') or []:
        if not isinstance(a, dict) or not str(a.get('amount') or '').strip():
            continue
        q = a.get('quote') or ''
        if cc.amount_in_text(a['amount'], text):          # المبلغ نفسه وارد في نص الجزء (الاقتباس سياق فقط)
            date = a.get('date') if a.get('date') and cc.date_in_text(a['date'], text) else ''
            amounts.append({'label': ' '.join(str(a.get('label') or '').split()), 'amount': str(a['amount']).strip(),
                            'date': date, 'page': _int(a.get('page')), 'quote': ' '.join(q.split())})
        else:
            notes.append(f"مبلغ {a.get('amount')} لم يرد حرفياً")
    defenses = []
    for d in p.get('defenses') or []:
        if isinstance(d, dict) and quote_in(d.get('quote'), text):
            s = ' '.join(str(d.get('summary') or '').split())
            defenses.append({'summary': ' '.join(s.split()[:30]), 'quote': ' '.join(str(d['quote']).split())})
        elif isinstance(d, dict) and d.get('summary'):
            notes.append('وجه دفاع بلا اقتباس حرفي')
    att = p.get('attendance') if isinstance(p.get('attendance'), dict) else {}
    out_att = {'present': [], 'absent': [], 'booking_date': '', 'booking_quote': ''}
    for key in ('present', 'absent'):
        for x in att.get(key) or []:
            if isinstance(x, dict) and x.get('role') in ('plaintiff', 'defendant', 'appellant', 'appellee') \
                    and quote_in(x.get('quote'), text):
                out_att[key].append({'role': x['role'], 'index': _int(x.get('index'), 1) or 1,
                                     'quote': ' '.join(str(x['quote']).split())})
            elif isinstance(x, dict) and x.get('role'):
                notes.append(f"{'حضور' if key == 'present' else 'تخلف'} بلا اقتباس حرفي")
    bd = str(att.get('booking_date') or '').strip()
    if bd:
        if cc.date_in_text(bd, text) and ('حجز' in norm(text)):
            out_att['booking_date'] = bd
            out_att['booking_quote'] = ' '.join(str(att.get('booking_quote') or '').split())
        else:
            notes.append(f'تاريخ الحجز {bd} لم يرد حرفياً')
    contract = p.get('contract') if isinstance(p.get('contract'), dict) else {}
    if contract.get('found'):
        contract = dict(contract, quote_ok=quote_in(contract.get('quote'), text))
    return {'documents': docs, 'amounts': amounts, 'defenses': defenses, 'attendance': out_att,
            'contract': contract, 'more_contracts': [c for c in p.get('more_contracts') or [] if isinstance(c, dict)]}, notes


def verify(data, raw, md):
    """الأجزاء بعد التحقق: case_sort.verify_part (النوع/التاريخ/الصفة/رقم المحضر) + المحتوى باقتباسه. يرجع (أجزاء، ملاحظات)."""
    import case_sort as cs
    parts, notes = [], []
    raw_parts = []
    for p in (raw or {}).get('parts') or []:
        if isinstance(p, dict):
            q = dict(p, type=cs.norm_type(p.get('type')))
            pg = q.get('pages') or []
            if not (isinstance(pg, list) and len(pg) == 2 and _int(pg[0]) and _int(pg[1])):
                q.pop('pages', None)
            raw_parts.append(q)
    if all(q.get('pages') for q in raw_parts):
        raw_parts = absorb(raw_parts)          # مستندات الحافظة الداخلية تُضم قبل التحقق: نطاق الجزء = الحافظة كلها
    for p in raw_parts:
        v = cs.verify_part(data, p, md)
        extras, n2 = _verify_extras(p, cs.part_text(md, p.get('pages')), md)
        v.update(extras)
        v['notes'] = list(v.get('notes') or []) + n2
        v['parties'] = [x for x in p.get('parties') or [] if isinstance(x, dict)] if v['type'] == 'صحيفة' else []
        notes += v['notes']
        parts.append(v)
    return absorb(parts), notes


def absorb(parts):
    """مستندات الحافظة الداخلية ليست أجزاء: كل جزء «أخرى» يُضم إلى الجزء الحقيقي قبله (أو بعده إن كان أولاً)، بنطاق صفحاته
    ومستنداته ومبالغه — فلا تصير حافظة واحدة «ملفاً مختلطاً» من عشرة أجزاء. بلا أي جزء حقيقي تبقى كما هي."""
    real = [p for p in parts if p.get('type') != 'أخرى']
    if not real or len(real) == len(parts):
        return parts
    out = []
    pending = []
    for p in sorted(parts, key=lambda x: _int((x.get('pages') or [0])[0], 0)):
        if p.get('type') == 'أخرى':
            if out:
                _merge(out[-1], p)
            else:
                pending.append(p)
            continue
        for q in pending:
            _merge(p, q)
        pending = []
        out.append(p)
    return out


def _merge(into, p):
    pg, qg = into.get('pages') or [], p.get('pages') or []
    if len(pg) == 2 and len(qg) == 2:
        into['pages'] = [min(_int(pg[0], 1), _int(qg[0], 1)), max(_int(pg[1], 1), _int(qg[1], 1))]
    for k in ('documents', 'amounts', 'defenses'):
        into[k] = list(into.get(k) or []) + list(p.get(k) or [])
    c = p.get('contract') or {}
    if c.get('found'):
        if (into.get('contract') or {}).get('found'):
            into.setdefault('more_contracts', []).append(c)
        else:
            into['contract'] = c
    into['more_contracts'] = list(into.get('more_contracts') or []) + list(p.get('more_contracts') or [])
    into['notes'] = list(into.get('notes') or []) + list(p.get('notes') or [])


def adopt_parties(data, parts, md=''):
    """أطراف القضية من صحيفة الدعوى المفروزة (حين لا يعيدها النظام): الأسماء والجنس النحوي كما تكتبه الصحيفة.
    الاسم يُعتمد فقط إن ورد في نص الصحيفة. لا يمسّ أطرافاً مسجّلة. يرجع True إن أضاف شيئاً."""
    case = data.setdefault('case', {})
    got = {'plaintiff': [], 'defendant': []}
    gen = {'plaintiff': [], 'defendant': []}
    for p in parts or []:
        for x in p.get('parties') or []:
            role, name = x.get('role'), ' '.join(str(x.get('name') or '').split())
            if role in got and name and (not md or quote_in(name, md, 0.75)) and name not in got[role]:
                got[role].append(name)
                g = x.get('gender') if x.get('gender') in ('f', 'm') else ''
                gen[role].append(g)
    changed = False
    if got['plaintiff'] and not (case.get('plaintiff') or case.get('plaintiffs')):
        case['plaintiffs'], case['plaintiff'] = got['plaintiff'], '، '.join(got['plaintiff'])
        changed = True
    if got['defendant'] and not case.get('defendants'):
        case['defendants'] = got['defendant']
        changed = True
    if changed:
        case['genders'] = {r: gen[r] for r in gen if got[r]}
        case['parties_source'] = 'صحيفة الدعوى (الفرز)'
    return changed


# ---------- التخزين والطلب ----------

def stash_conversion(entry, blocks, n):
    """يُستدعى من مزامنة المجلد بعد تحويل جيميناي: يحفظ كتل الفرز الخام ببصمة الملف (تُتحقق عند الفرز)."""
    if blocks:
        entry['triage_raw'] = {'sha1': entry.get('sha1'), 'pages': n, 'blocks': [[a, b, obj] for a, b, obj in blocks],
                               'at': _now()}
    else:
        entry.pop('triage_raw', None)


VERSION = 4     # 2026-10-22: تحقق التاريخ بالسنة أولاً، الاقتباس التقريبي للممسوح، الحافظة جزء واحد، أطراف الصحيفة — يُعاد الفرز مرة


def done(e):
    """للملف نتيجة فرز لنسخته الحالية (بصمة sha1) — بأي نسخة من قواعد الفرز. (القضية القديمة تبقى بنتائجها: 2026-10-25)"""
    t = e.get('triage') or {}
    return bool(t) and t.get('sha1') == e.get('sha1')


def current(e):
    """فُرز بنسخة القواعد الحالية (VERSION)."""
    return done(e) and (e.get('triage') or {}).get('v') == VERSION


def locked(data):
    """قضية أُنجز موضوعها سابقاً: تغيّر VERSION لا يعيد فرزها تلقائياً — تبقى بنتائجها حتى يضغط الخبير «إعادة فرز»."""
    d = data or {}
    return bool((d.get('stage2') or {}).get('sig') or (d.get('subject') or '').strip())


def pending(base, man=None, data=None):
    """الأصول المحوَّلة التي تحتاج فرزاً: بلا نتيجة لنسختها الحالية (بصمة sha1)، أو بنسخة قواعد أقدم في قضية لم يُكتب
    موضوعها بعد (data؛ بلا data ← نتيجة أي نسخة تكفي). المعتمد اسمها أيضاً (يُلخَّص ولا يُنقل)."""
    import os
    import case_folder as cf
    man = man or cf.load_manifest(base)
    redo_old = data is not None and not locked(data)
    out = []
    for rel, e in sorted(man['files'].items()):
        if e.get('state') != 'done' or not os.path.exists(os.path.join(base, rel)):
            continue
        if current(e) or (done(e) and not redo_old):
            continue
        s = e.get('sort') or {}
        if s.get('state') == 'manual' and s.get('sha1') == e.get('sha1'):
            continue
        out.append(rel)
    return out


def triage_file(base, data, rel, ask, man, md):
    """فرز ملف واحد: كتل التحويل إن وُجدت (بلا طلب)، وإلا طلب فرز واحد على النص (نصي أو احتياط).
    يرجع (raw dict أو None، المصدر convert|request|fallback، ملاحظة) ولا يحفظ."""
    import ai_call_log
    e = man['files'][rel]
    old = e.get('triage') or {}
    if old.get('raw') and old.get('sha1') == e.get('sha1') and old.get('source') != 'convert':
        return old['raw'], old.get('source') or 'request', ''      # رد محفوظ: تحقق جديد بلا طلب (تغيّر قواعد التحقق)
    tr = e.get('triage_raw') or {}
    if tr.get('sha1') == e.get('sha1') and tr.get('blocks'):
        got = assemble([tuple(b) for b in tr['blocks']], tr.get('pages') or 1)
        if got is not None:
            return got, 'convert', ''
        why = 'ردّ التحويل بلا كتلة فرز صالحة في إحدى الدفعات'
        source = 'fallback'
    else:
        why, source = '', 'request'
    if ask is None:
        return None, source, why or 'لا مزوّد ذكاء متاح للفرز'
    import os
    ai_call_log.detail(os.path.basename(rel) + (' (احتياط: ' + why + ')' if why else ''))
    raw = parse_json(ask(text_prompt(data, md)))
    if raw is None:
        ai_call_log.verdict(False, 'ردّ الفرز ليس JSON')
        raise ValueError('ردّ الفرز ليس JSON')
    return raw, source, why


def store(e, parts, notes, source, raw=None):
    e['triage'] = {'sha1': e.get('sha1'), 'source': source, 'parts': parts, 'notes': notes[:20], 'at': _now(),
                   'v': VERSION}
    if raw is not None and source != 'convert':          # رد النموذج يُحفظ: تغيّر قواعد التحقق لا يكلّف طلباً جديداً
        e['triage']['raw'] = raw
    return e['triage']


# ---------- القراءة من الملخص (للخطوات التالية بالكود) ----------

def entries(base, man=None):
    """[(rel, entry, triage)] لكل أصل مفروز بنسخته الحالية."""
    import case_folder as cf
    man = man or cf.load_manifest(base)
    return [(rel, e, e['triage']) for rel, e in sorted(man['files'].items()) if done(e) and e.get('state') == 'done']


def minute_records(base, man=None):
    """لكل محضر مفروز: {'rel','no','present':[(role,index)],'absent':[...],'booking':iso,'name'} — للإجراءات بلا طلب."""
    import os
    import case_folder as cf
    import case_procedures as cp
    out = []
    for rel, e, t in entries(base, man):
        for p in t.get('parts') or []:
            if p.get('type') != 'محضر' and cf.kind_of(rel) != cf.MINUTES:
                continue
            att = p.get('attendance') or {}
            bk = cp.minute_date([att.get('booking_date')]) if att.get('booking_date') else ''
            no = p.get('minute_no')
            if no is None:                                    # «محضر الخبرة رقم N» — الرقم من الاسم المعتمد
                m = re.search(r'رقم (\d+)', os.path.basename(rel))
                no = int(m.group(1)) if m else None
            out.append({'rel': rel, 'path': os.path.join(base, rel), 'no': no, 'sha1': e.get('sha1'),
                        'name': os.path.basename(rel), 'booking': bk,
                        'present': [(x['role'], x.get('index') or 1) for x in att.get('present') or []],
                        'absent': [(x['role'], x.get('index') or 1) for x in att.get('absent') or []]})
            break
    return out


def signature(base, man=None, kinds=None):
    """بصمة ما فُرز (لإعادة المرحلة الثانية عند تغيّر الملخص: عقد جديد، محضر جديد…)."""
    import hashlib
    h = hashlib.sha1()
    for rel, e, t in entries(base, man):
        h.update((rel + '|' + str(e.get('sha1'))).encode('utf-8'))
    return h.hexdigest()


def attachment_items(base, man=None):
    """[{'role','kind','date'}] لكل حافظة/مذكرة مفروزة (للمرفقات بالكود حين تُرفض قائمة النموذج)."""
    out = []
    for rel, e, t in entries(base, man):
        for p in t.get('parts') or []:
            kind = {'حافظة': 'حافظة مستندات', 'مذكرة': 'مذكرة دفاع'}.get(p.get('type'))
            if not kind:
                continue
            m = re.fullmatch(r'(\d{2})-(\d{2})-(\d{4})', p.get('date') or '')
            out.append({'role': p.get('role') or '', 'side': p.get('label') or '', 'kind': kind,
                        'date': f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else ''})
    return out
