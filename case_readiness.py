# ===== case_readiness.py — «فحص الجاهزية» قبل كتابة «البحث ورأي الخبرة» (2026-10-17) =====
# لكل نقطة من المأمورية المؤكَّدة (data['mission']['points'] — مقسّمة كما وردت في حكم الإحالة):
#   1) النموذج (ask) يستنتج «ما يلزم لإجابتها» ويقترح لكل متطلب موضعه في المستندات مع اقتباس حرفي قصير.
#   2) الكود يحكم بالدليل فقط: المتطلب «موجود» إن ورد الاقتباس حرفياً (بتطبيع case_subject_telecom.Plaint) في
#      نص مستند محوَّل، ويُسجَّل موضعه (الحافظة/المستند/الصفحة) كما وجده الكود لا كما ادّعاه النموذج. بلا موضع = «ناقص».
#   3) لكل ناقص «طلب موجّه للخصم» بصيغة رسمية موجزة في data['questions'] (مربوط بالنقطة، open/closed).
#   4) إعادة الفحص (تلقائياً عند تغيّر المستندات): الأسئلة التي سُدّت تُغلق، والباقية تبقى، والجديدة تُضاف.
#   5) جدول الوقائع 03_حقائق/جدول_الوقائع.md: كل رقم/مبلغ ورد في المستندات بموضعه؛ البحث لا يكتب رقماً خارجه.
# المصادر: case.json (المستندات ونصوصها في 02_markdown، وهي نفسها «سجل/نصوص المستندات» في ذاكرة_القضية.md).
import hashlib
import json
import os
import re
from datetime import datetime

import case_documents
import case_memory
import case_model as cm
import case_subject_telecom as st
import case_workspace as cw

FACTS_REL = os.path.join('_نظام', '03_حقائق', 'جدول_الوقائع.md')
MAX_DOC_CHARS = 120_000
READY, MISSING = 'ready', 'missing'
STATE_TEXT = {READY: 'جاهز', MISSING: 'ناقص'}
_PAGE_RE = re.compile(r'(?:<!--\s*صفحة\s*(\d+)\s*-->|-{2,}\s*صفحة\s*(\d+)\s*-{2,})')
_AMOUNT_RE = re.compile(r'(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{3,})(?![\w])')
PARTIES = ('المدعية', 'المدعي', 'المدعى عليه', 'المدعى عليها', 'المدعى عليهم')


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _norm_need(text):
    return ' '.join(n for n, _, _ in st._tokens(st._display(text)))


# ---------- فهرس المستندات (من case.json + 02_markdown) ----------

def doc_index(base, data):
    """[{'label','pid','uid','type','submitter','date','pages':[(رقم، نص)]}] للمستندات المحوَّلة بنجاح."""
    out = []
    for p, d in case_documents.content_docs(data):
        if (d.get('convert') or {}).get('state') != 'done' or d.get('needs_type'):
            continue
        raw, _ = case_memory._read_text(base, d.get('md'))
        if raw is None:
            continue
        text = case_memory._dec(raw)
        out.append({'label': f"{p['id']}-{d['no']}", 'pid': p['id'], 'uid': d['uid'],
                    'type': d.get('type') or d.get('doc_type') or 'مستند', 'submitter': p.get('submitter') or '',
                    'date': p.get('date') or '', 'pages': split_pages(text)})
    return out


def split_pages(text):
    """[(رقم الصفحة، نصها)] بعلامات «<!-- صفحة N -->» أو «--- صفحة N ---»؛ بلا علامات ← صفحة 1."""
    marks = list(_PAGE_RE.finditer(text or ''))
    if not marks:
        return [(1, text or '')]
    pages = []
    if text[:marks[0].start()].strip():
        pages.append((1, text[:marks[0].start()]))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        pages.append((int(m.group(1) or m.group(2)), text[m.end():end]))
    return pages


def docs_signature(data):
    """بصمة المستندات المحوَّلة (تتغيّر بإضافة مستند أو إعادة تحويله) — لإعادة الفحص تلقائياً."""
    parts = sorted(f"{d['uid']}:{d.get('sha1') or ''}:{(d.get('convert') or {}).get('state')}"
                   for _p, d in case_documents.all_docs(data))
    return hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()


def locate(index, quote, prefer=None):
    """موضع الاقتباس حرفياً: {'doc','pid','uid','type','submitter','page','quote'} أو None.
    يبدأ بالمستند المقترح ثم البقية. اقتباس أقل من 3 كلمات لا يُعتدّ به."""
    q = st._clean(quote)
    if not q or len(q.split()) < 3:
        return None
    order = sorted(index, key=lambda d: d['label'] != prefer)
    for d in order:
        for page, txt in d['pages']:
            found = st.Plaint(txt).find(q)
            if found:
                return {'doc': d['label'], 'pid': d['pid'], 'uid': d['uid'], 'type': d['type'],
                        'submitter': d['submitter'], 'page': page, 'quote': found}
    return None


def where_text(loc):
    """«حافظة P1 (المدعية) — مستند P1-2 «عقد» — صفحة 3»."""
    sub = f" ({loc['submitter']})" if loc.get('submitter') else ''
    return f"حافظة {loc['pid']}{sub} — مستند {loc['doc']} «{loc['type']}» — صفحة {loc['page']}"


# ---------- جدول الوقائع (الأرقام بمواضعها) ----------

def facts_table(index):
    """[{'value','doc','page','context'}] لكل رقم/مبلغ (3 أرقام فأكثر أو بكسور أو بفواصل آلاف) في المستندات."""
    rows = []
    for d in index:
        for page, txt in d['pages']:
            disp = st._display(txt)
            for m in _AMOUNT_RE.finditer(disp):
                a, b = max(0, m.start() - 40), min(len(disp), m.end() + 40)
                rows.append({'value': m.group(1), 'doc': d['label'], 'page': page,
                             'context': re.sub(r'\s+', ' ', disp[a:b]).strip()})
    return rows


def write_facts(base, rows):
    lines = ['# جدول الوقائع (الأرقام والمبالغ كما وردت في المستندات)', '',
             '| القيمة | المستند | الصفحة | السياق |', '|---|---|---|---|']
    lines += [f"| {r['value']} | {r['doc']} | {r['page']} | {r['context'].replace('|', '/')} |" for r in rows]
    case_documents._write_md(base, FACTS_REL.replace('\\', '/'), '\n'.join(lines) + '\n')


def fact_numbers(rows):
    return {format(st.Decimal(r['value'].replace(',', '')).normalize(), 'f') for r in rows}


def unverified_numbers(text, allowed):
    """الأرقام/المبالغ في نص النموذج غير الواردة في جدول الوقائع (إحالات [P1-2] مستثناة)."""
    disp = re.sub(r'\[[^\]]*\]', ' ', st._display(text))
    bad = []
    for m in _AMOUNT_RE.finditer(disp):
        v = format(st.Decimal(m.group(1).replace(',', '')).normalize(), 'f')
        if v not in allowed and m.group(1) not in bad:
            bad.append(m.group(1))
    return bad


def mark_unverified_numbers(text, allowed):
    """يستبدل كل رقم غير وارد في جدول الوقائع بـ«[رقم غير موثّق: X]» (القاعدة: لا رقم من النموذج بلا مصدر)."""
    for v in unverified_numbers(text, allowed):
        text = re.sub(rf'(?<![\w.,\[]){re.escape(v)}(?![\w])', f'[رقم غير موثّق: {v}]', text)
    return text


# ---------- الطلب والتحليل ----------

def build_prompt(data, point, index):
    docs = []
    budget = MAX_DOC_CHARS // max(1, len(index))
    for d in index:
        body = '\n'.join(f'<!-- صفحة {n} -->\n{t.strip()}' for n, t in d['pages'])
        if len(body) > budget:
            body = body[:budget] + '\n[… مقتطع]'
        docs.append(f"### [{d['label']}] {d['type']} — مقدَّم من: {d['submitter'] or 'غير محدد'} {d['date']}\n{body}")
    return (
        "أنت تساعد خبيراً قضائياً قبل كتابة «البحث ورأي الخبرة». للنقطة التالية من المأمورية، استنتج قائمة "
        "«ما يلزم لإجابتها» من مستندات (مثل: العقد المؤرخ كذا، كشف الحساب لفترة كذا، فواتير الأشهر، إشعار الإلغاء، "
        "مستندات المدعى عليه، مذكرة الدفاع المقدمة أمام المحكمة). ثم ابحث عن كل متطلب في المستندات أدناه.\n"
        "قاعدة صارمة: لا تعدّ متطلباً موجوداً إلا باقتباس حرفي (5 كلمات فأكثر) منسوخ كما هو من نص المستند، مع رمز "
        "المستند ورقم الصفحة. إن لم تجده فاجعل found = null. لا تخمّن ولا تكتب أرقاماً من عندك.\n"
        'أجب بـ JSON فقط بالشكل:\n'
        '{"requirements":[{"need":"وصف المستند/المعلومة اللازمة","from":"المدعية أو المدعى عليه",'
        '"why":"لماذا يلزم للنقطة","found":{"doc":"P1-2","page":1,"quote":"اقتباس حرفي"} أو null}]}\n'
        "- from: الطرف الذي يُطلب منه تقديمه إن كان ناقصاً.\n\n"
        f"## موضوع القضية\n{data.get('subject') or '—'}\n\n"
        f"## النقطة رقم {point['n']} من المأمورية\n{point['text']}\n\n"
        "## المستندات\n" + ('\n\n'.join(docs) if docs else '_لا مستندات محوَّلة._'))


def _party(v):
    v = st._clean(v)
    for p in PARTIES:
        if p in v:
            return 'المدعى عليه' if 'عليه' in p else 'المدعية'
    return 'أطراف الدعوى'


def question_text(to, need, point, why):
    """صياغة موجزة في سطر واحد بلا سبب ولا بند طويل (احتياطي حين لا يتوفر الذكاء؛ الأصل توليد case_questions)."""
    return f"تكليف {to} بتقديم {need}"


def check_point(data, point, index, ask):
    """فحص نقطة واحدة. يرجع سجلها: state/score/requirements/missing. ردّ غير JSON يرفع ValueError."""
    obj = st.parse_response(ask(build_prompt(data, point, index)))
    import ai_call_log
    ai_call_log.verdict(True, f"نقطة {point.get('n', '')}: {len(obj.get('requirements') or [])} متطلب مقترح (يُتحقق من اقتباساتها)")
    reqs = []
    for r in obj.get('requirements') or []:
        if not isinstance(r, dict) or not st._clean(r.get('need')):
            continue
        need = st._clean(r['need']).rstrip('.،')
        f = r.get('found') if isinstance(r.get('found'), dict) else {}
        loc = locate(index, f.get('quote'), st._clean(f.get('doc'))) if f else None
        reqs.append({'need': need, 'key': _norm_need(need), 'to': _party(r.get('from')), 'why': st._clean(r.get('why')),
                     'found': loc, 'where': where_text(loc) if loc else '',
                     'claimed': bool(f) and loc is None})          # النموذج ادّعى موضعاً لم يتحقق منه الكود
    if not reqs:
        raise ValueError('لم يُرجع النموذج أي متطلب للنقطة')
    have = sum(1 for r in reqs if r['found'])
    missing = [r for r in reqs if not r['found']]
    return {'id': point['id'], 'n': point['n'], 'point_text': point['text'],
            'state': READY if not missing else MISSING, 'score': round(100 * have / len(reqs)),
            'requirements': reqs, 'missing': [r['need'] for r in missing], 'at': _now()}


# ---------- الأسئلة المهمة ----------

def _qid(point_id, key):
    return f"r_{point_id}_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:8]}"


def normalize_questions(data):
    """data['questions']: النصوص القديمة (إضافة يدوية) تُحوَّل إلى سجلات {id,text,status,auto=False}."""
    out = []
    for i, q in enumerate(data.get('questions') or []):
        if isinstance(q, str):
            q = {'id': f'm{i + 1}', 'text': q, 'status': 'open', 'auto': False}
        out.append(q)
    data['questions'] = out
    return out


def sync_questions(data, results, points):
    """يضيف طلباً لكل ناقص، ويُغلق ما سُدّ، ويُبقي الباقي. يرجع (أُضيف، أُغلق) بالمعرّفات."""
    qs = normalize_questions(data)
    by_id = {q['id']: q for q in qs}
    pts = {p['id']: p for p in points}
    added, closed, live = [], [], set()
    for res in results:
        point = pts.get(res['id'])
        if point is None:
            continue
        for r in res['requirements']:
            qid = _qid(res['id'], r['key'])
            if r['found']:
                continue
            live.add(qid)
            q = by_id.get(qid)
            if q is None:
                q = {'id': qid, 'auto': True, 'point_id': res['id'], 'point_n': res['n'], 'to': r['to'],
                     'need': r['need'], 'why': r['why'], 'text': question_text(r['to'], r['need'], point, r['why']),
                     'status': 'open', 'at': _now()}
                qs.append(q)
                by_id[qid] = q
                added.append(qid)
            elif q.get('status') == 'closed':
                q.update(status='open', reopened_at=_now())
                added.append(qid)
            q['point_n'] = res['n']
    checked = {res['id'] for res in results}
    for q in qs:
        if q.get('auto') and q.get('status') == 'open' and q.get('point_id') in checked and q['id'] not in live:
            res = next(r for r in results if r['id'] == q['point_id'])
            loc = next((r['where'] for r in res['requirements'] if _qid(res['id'], r['key']) == q['id'] and r['found']), '')
            q.update(status='closed', closed_at=_now(), closed_by=loc or 'لم يعد مطلوباً في الفحص الأخير')
            closed.append(q['id'])
    return added, closed


def open_questions(data, point_id=None):
    return [q for q in normalize_questions(data) if q.get('status', 'open') == 'open'
            and (point_id is None or q.get('point_id') == point_id)]


def questions_html(data):
    """للطباعة: جدولا مهام الخبير وطلبات الخصوم (case_questions)."""
    import case_questions
    return case_questions.questions_html(data)


def _questions_html_old(data):
    """قائمة قديمة (للتوافق فقط)."""
    rows = []
    for i, q in enumerate(open_questions(data), 1):
        tag = f" <small>(البند {q['point_n']})</small>" if q.get('point_n') else ''
        rows.append(f"<li>{q['text']}{tag}</li>")
    return (f"<html dir='rtl'><body style='font-family:Tahoma; font-size:13pt'>"
            f"<h2>الأسئلة المهمة — القضية {data.get('caso_no', '')}</h2>"
            f"<ol>{''.join(rows) or '<li>لا أسئلة مفتوحة.</li>'}</ol></body></html>")


# ---------- التشغيل ----------

def is_stale(data):
    r = data.get('readiness') or {}
    pts = [[p['id'], p['text']] for p in (data.get('mission') or {}).get('points') or []]
    return bool(r) and (r.get('docs_sig') != docs_signature(data) or r.get('points') != pts)


def run_readiness(base, data, ask=None):
    """يفحص كل نقاط المأمورية المؤكَّدة. يرجع data['readiness']. يرفع cm.StepError إن لم تؤكَّد المأمورية.
    فشل نقطة (المزوّد/JSON) يُسجَّل لها state='error' ولا يوقف البقية، ولا يُغلق أسئلتها."""
    m = data.get('mission') or {}
    points = m.get('points') or []
    if not points:
        raise cm.StepError('لا توجد نقاط مأمورية بعد — تُقرأ من حكم الإحالة.')
    if cm.state(data, 'mission') != 'reviewed':      # المأمورية صحيحة ما لم يعدّلها الخبير
        import case_subject_mission as sm
        sm.confirm_mission(base, data)
    if ask is None:
        import case_research
        ask = case_research.default_ask
    index = doc_index(base, data)
    facts = facts_table(index)
    write_facts(base, facts)
    results, ok_results = [], []
    for p in points:
        try:
            res = check_point(data, p, index, ask)
            ok_results.append(res)
        except Exception as e:
            res = {'id': p['id'], 'n': p['n'], 'point_text': p['text'], 'state': 'error', 'score': 0,
                   'requirements': [], 'missing': [], 'error': str(e) or e.__class__.__name__, 'at': _now()}
        results.append(res)
    added, closed = sync_questions(data, ok_results, points)
    data['readiness'] = {'items': results, 'docs_sig': docs_signature(data), 'at': _now(),
                         'points': [[p['id'], p['text']] for p in points], 'facts': len(facts),
                         'added': added, 'closed': closed}
    cw.write_case_json(base, data)
    return data['readiness']


_NEED_RULES = (      # (كلمات النقطة، ما يلزمها، من يقدّمه، المفتاح) — المراحل الثلاث: بالكود من الملخص بلا طلب
    (r'عقد|علاق|التزام|إخلال|اخلال|طبيع', 'العقد بين طرفي الدعوى', 'المدعية', 'contract'),
    (r'مديوني|مبلغ|مستحق|فاتور|رصيد|حساب|تصفي|ذم[ةه]|سداد', 'كشف الحساب أو الفواتير المطالب بها', 'المدعية', 'amounts'),
)


def _have(base, data):
    """ما يثبت في الملخص (الفرز المتحقَّق): {'contract': موضع، 'amounts': موضع}."""
    import os
    import case_triage
    have = {}
    mc = data.get('main_contract') or {}
    if mc.get('found'):
        c = mc['contract']
        have['contract'] = {'where': os.path.splitext(os.path.basename(c.get('file') or ''))[0]}
    try:
        for rel, e, t in case_triage.entries(base):
            for p in t.get('parts') or []:
                if p.get('amounts') and 'amounts' not in have:
                    have['amounts'] = {'where': os.path.splitext(os.path.basename(rel))[0]}
                if (p.get('contract') or {}).get('found') and 'contract' not in have:
                    have['contract'] = {'where': os.path.splitext(os.path.basename(rel))[0]}
    except Exception:
        pass
    return have


def run_code(base, data):
    """فحص الجاهزية بالكود (بلا ذكاء): لكل نقطة ما يلزمها بحسب كلماتها، وهل ثبت في الملخص. الناقص طلب للخصم في
    «الأسئلة المهمة» (sync_questions). نقطة لا تحتاج مستنداً محدداً (الدفاع مثلاً) جاهزة. يرجع data['readiness']."""
    points = (data.get('mission') or {}).get('points') or []
    if not points:
        raise cm.StepError('لا توجد نقاط مأمورية بعد — تُقرأ من حكم الإحالة.')
    have = _have(base, data)
    sig = hashlib.sha1(json.dumps([[p['id'], p['text']] for p in points] + [sorted(have)],
                                  ensure_ascii=False).encode('utf-8')).hexdigest()
    old = data.get('readiness') or {}
    if old.get('source') == 'code' and old.get('code_sig') == sig:
        return old                                     # لا تغيير: لا كتابة
    results = []
    for p in points:
        reqs = []
        for rx, need, to, key in _NEED_RULES:
            if re.search(rx, p['text'] or ''):
                loc = have.get(key)
                reqs.append({'need': need, 'key': _norm_need(need), 'to': to, 'why': '',
                             'found': loc, 'where': (loc or {}).get('where', ''), 'claimed': False})
        have_n = sum(1 for r in reqs if r['found'])
        missing = [r for r in reqs if not r['found']]
        results.append({'id': p['id'], 'n': p['n'], 'point_text': p['text'],
                        'state': READY if not missing else MISSING,
                        'score': round(100 * have_n / len(reqs)) if reqs else 100,
                        'requirements': reqs, 'missing': [r['need'] for r in missing], 'at': _now()})
    added, closed = sync_questions(data, results, points)
    data['readiness'] = {'items': results, 'docs_sig': docs_signature(data), 'at': _now(), 'source': 'code',
                         'code_sig': sig,
                         'points': [[p['id'], p['text']] for p in points], 'added': added, 'closed': closed}
    cw.write_case_json(base, data)
    return data['readiness']


def item(data, point_id):
    return next((r for r in (data.get('readiness') or {}).get('items') or [] if r['id'] == point_id), None)


def ready_ids(data):
    return [r['id'] for r in (data.get('readiness') or {}).get('items') or [] if r['state'] == READY]


def sentence(data, res):
    """جملة واضحة للخبير عن نقطة واحدة."""
    if res['state'] == 'error':
        return f"البند {res['n']}: تعذّر الفحص — {res.get('error')}"
    if res['state'] == READY:
        return f"البند {res['n']} جاهز ({res['score']}%): كل ما يلزمه موجود في المستندات."
    qs = {q.get('need') for q in open_questions(data, res['id'])}
    parts = []
    for need in res['missing']:
        parts.append(f"لم يُرفق {need}" + ('، أُضيف طلب تقديمه للأسئلة المهمة' if need in qs else ''))
    return f"البند {res['n']} ناقص ({res['score']}%): " + '؛ '.join(parts) + '.'
