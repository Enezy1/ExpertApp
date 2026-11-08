# ===== case_research.py — خطوة «البحث ورأي الخبرة» (المرحلة 2ل) =====
# حلقة بالتتابع على نقاط المأمورية المؤكَّدة. كل بند يستلم: نصوص المستندات (Markdown) + سجل المستندات
# + ملخصات البنود السابقة. يُحفظ كل بند فور انتهائه في 04_تقرير/بنود/NN.md وفي case.json
# (case.json['research']، والمفتاح الثابت هو معرّف نقطة المأمورية id لا رقمها). الاستئناف يبدأ من أول بند
# غير مكتمل. فشل بند يوقف الحلقة (لأن ما بعده يعتمد على ملخصه) والخطوة failed؛ المكتمل محفوظ.
# إعادة كتابة بند تجعل اللاحق المكتمل «تحتاج تحديثاً» (stale) دون إعادة كتابته تلقائياً.
# المزوّد: ask(prompt) -> نص. الافتراضي سلسلة ai_providers.build_text_chain (مع المزوّد البديل).
# فحص الجاهزية (case_readiness): run_research(only=…) يكتب البنود الجاهزة فقط؛ «اكتب رغم النقص» = rewrite_item(missing=…)
# فيضع النموذج «[ناقص: …]» في موضع المعلومة (ويضمنها الكود). أي رقم/مبلغ في النص غير وارد في جدول الوقائع
# (03_حقائق/جدول_الوقائع.md) يُستبدل بـ«[رقم غير موثّق: X]».
import contextlib
import hashlib
import os
import re
import threading

import case_memory
import case_model as cm
import case_documents
import case_workspace as cw

ITEMS_DIR = os.path.join('_نظام', '04_تقرير', 'بنود')
SUMMARY_MARK = '===ملخص==='
MAX_PROMPT_CHARS = 150_000          # ميزانية نصوص المستندات؛ فوقها يُقتطع كل مستند بالتناسب
SUMMARY_FALLBACK_CHARS = 400
TIMEOUT = 180
RESEARCH_TIMEOUT = 180              # مهلة طلب تقرير البحث (research) — 3.8 بطيء أحياناً
# مهل أقصر للطلبات النصية القصيرة (الموضوع/الحضور/الأسئلة): الطلب العالق يُعاد بسرعة بدل انتظار 180ث (السجل: 207ث لموضوع واحد)
SHORT_TIMEOUTS = {'الموضوع': 60, 'الحضور': 60, 'الأسئلة المهمة': 90, 'فحص الجاهزية': 120}
# الطلب الواحد لكتابة التقرير (البحث كاملاً + إعادة قراءة PDF): أطول بكثير من بقية الطلبات — 180ث لم تكفِ (السجل 25/10)
FULL_REPORT_TIMEOUT = 480
_long = threading.local()


@contextlib.contextmanager
def long_request(seconds=FULL_REPORT_TIMEOUT):
    """طلبات «research» داخل هذا السياق (في الخيط نفسه) تأخذ المهلة الطويلة بدل RESEARCH_TIMEOUT."""
    prev = getattr(_long, 'seconds', None)
    _long.seconds = seconds
    try:
        yield
    finally:
        _long.seconds = prev


def research_timeout():
    return getattr(_long, 'seconds', None) or RESEARCH_TIMEOUT


def default_ask(prompt, task=None, spec=None, timeout=None):
    """task: استخراج/تلخيص/صياغة/بحث (ai_providers.TASKS) ← سلسلة مزوّد المهمة؛ بلا task ← السلسلة التلقائية القديمة.
    غياب مزوّد المهمة يرفع ai_providers.ProviderMissing (لا انتقال صامت إلى أضعف)."""
    import ai_providers
    import ai_call_log
    if task == 'research' and spec is None:          # البحث والنتيجة: Gemini وحده (لا Groq ولا نموذج صغير) ما لم يختر الخبير
        cur = ai_providers.get_task_specs().get('research', 'auto')     # مزوّداً بعينه صراحةً من الإعدادات
        spec = 'gemini' if cur in ('auto', 'gemini,openai', 'gemini') else cur
    chain = ai_providers.build_task_chain(task, spec) if task else ai_providers.build_text_chain()
    if task == 'research':
        timeout = research_timeout()
    resp = ai_providers.run_chain(lambda p, route: p.generate_text([prompt], route, timeout or TIMEOUT),
                                  len(prompt.encode('utf-8')), timeout or TIMEOUT, chain=chain)
    name = getattr(resp, 'provider', '')
    prov = next((p for p in chain if p.name == name), None)
    ai_call_log.set_provider(ai_providers.provider_label(prov) if prov else name,           # «Gemini (مفتاحك)» / «… (مفتاح القسم)»
                             (getattr(prov, 'last_model', '') or getattr(prov, 'model', '')) if prov else '')
    return resp.text


def ask_with_files(prompt, paths, task='research', spec=None):
    """مثل default_ask ومعه ملفات PDF مرفقة (إعادة قراءة مستند طلبه نموذج البحث). نفس سلسلة مزوّد المهمة."""
    import ai_providers
    import ai_call_log
    if task == 'research' and spec is None:
        cur = ai_providers.get_task_specs().get('research', 'auto')
        spec = 'gemini' if cur in ('auto', 'gemini,openai', 'gemini') else cur
    chain = ai_providers.build_task_chain(task, spec)
    size = len(prompt.encode('utf-8')) + sum(os.path.getsize(p) for p in paths)
    timeout = research_timeout()
    resp = ai_providers.run_chain(lambda p, route: p.generate_files(prompt, list(paths), route, timeout),
                                  size, timeout, chain=chain)
    name = getattr(resp, 'provider', '')
    prov = next((p for p in chain if p.name == name), None)
    ai_call_log.set_provider(ai_providers.provider_label(prov) if prov else name,
                             (getattr(prov, 'last_model', '') or getattr(prov, 'model', '')) if prov else '')
    return resp.text


# ---------- بناء الطلب ----------

def doc_label(p, d):
    return f"{p['id']}-{d['no']}"


def _doc_texts(base, data, budget=MAX_PROMPT_CHARS):
    """[(label, text)] للمستندات المحوَّلة بنجاح، مقتطعة بالتناسب إن تجاوزت الميزانية."""
    docs = []
    for p, d in case_documents.content_docs(data):
        if (d.get('convert') or {}).get('state') != 'done':
            continue
        raw, _ = case_memory._read_text(base, d.get('md'))
        if raw is not None:
            docs.append((doc_label(p, d), case_memory._dec(raw)))
    total = sum(len(t) for _, t in docs)
    if total > budget and docs:
        per = max(500, budget // len(docs))
        docs = [(l, t if len(t) <= per else t[:per] + '\n[… مقتطع لطول المستند]') for l, t in docs]
    return docs


def build_prompt(base, data, point, prev_summaries, missing=None, facts=None):
    m = data['mission']
    parts = [
        "أنت تساعد خبيراً قضائياً في كتابة قسم «البحث ورأي الخبرة» من تقرير خبرة. "
        "اعتمد على المستندات المرفقة فقط، ولا تخترع وقائع أو أرقاماً، وأحِل إلى المستند بين قوسين مربعين "
        "بذكر نوع المستند وتاريخه بلا رموز داخلية ولا أرقام صفحات. اكتب بلغة عربية قضائية رصينة. "
        "إن لم تكفِ المستندات للإجابة فاذكر ذلك صراحةً وحدّد الناقص.",
        f"## موضوع القضية\n{data.get('subject') or '—'}",
        f"## المأمورية كاملة\n{m.get('raw') or '—'}",
        f"## البند المطلوب الآن (رقم {point['n']})\n{point['text']}",
    ]
    if prev_summaries:
        parts.append('## ملخص البنود السابقة\n' + '\n'.join(f"- البند {n}: {s}" for n, s in prev_summaries))
    parts.append('## سجل المستندات\n' + case_memory._docs_table(base, data))
    if facts:
        parts.append('## جدول الوقائع (لا تكتب أي رقم أو مبلغ غير وارد فيه)\n'
                     + '\n'.join(f"- {r['value']}: {r['context']}" for r in facts[:400]))
    if missing:
        parts.append('## معلومات ناقصة (لم تُرفق بعد)\n' + '\n'.join(f'- {x}' for x in missing)
                     + '\nاكتب البند بما هو متاح، وضع في موضع كل معلومة ناقصة العلامة «[ناقص: وصفها]» حرفياً، '
                       'ولا تفترض مضمونها.')
    docs = _doc_texts(base, data)
    parts.append('## نصوص المستندات\n' + ('\n\n'.join(f"### [{l}]\n{t}" for l, t in docs) if docs else '_لا نصوص._'))
    parts.append(f"## صيغة الرد\nاكتب نص البند كاملاً، ثم سطراً منفرداً يحوي {SUMMARY_MARK} ثم ملخصاً من سطرين "
                 "لما انتهيت إليه في هذا البند (يُستعمل في البنود التالية).")
    return '\n\n'.join(parts)


def split_response(text):
    """(نص البند، ملخص). بلا علامة ← ملخص من بداية النص."""
    text = (text or '').strip()
    if SUMMARY_MARK in text:
        body, _, summ = text.partition(SUMMARY_MARK)
        body, summ = body.strip(), re.sub(r'\s+', ' ', summ).strip()
        if body and summ:
            return body, summ
        text = body or summ
    flat = re.sub(r'\s+', ' ', text)
    return text, flat[:SUMMARY_FALLBACK_CHARS] + ('…' if len(flat) > SUMMARY_FALLBACK_CHARS else '')


# ---------- الحالة ----------

def _item(data, pid):
    return next((i for i in data['research'] if i['id'] == pid), None)


def sync_items(data):
    """يوفّق قائمة البنود مع نقاط المأمورية بمعرّفاتها: جديد ← pending، تغيّر نص النقطة ← stale،
    نقطة محذوفة ← يُسقط بندها (ملفه يبقى على القرص). يرجع قائمة معرّفات أُسقطت."""
    points = data['mission'].get('points') or []
    by_id = {p['id']: p for p in points}
    dropped = [i['id'] for i in data['research'] if i['id'] not in by_id]
    old = {i['id']: i for i in data['research']}
    items = []
    for p in points:
        it = old.get(p['id']) or {'id': p['id'], 'state': 'pending', 'file': '', 'summary': '', 'sha1': '',
                                  'point_text': p['text']}
        if it['state'] in cm.OK_STATES and it.get('point_text') != p['text']:
            it['stale'] = True
        it['n'] = p['n']
        items.append(it)
    data['research'] = items
    return dropped


def _progress(data):
    items = data['research']
    done = sum(1 for i in items if i['state'] in cm.OK_STATES)
    data['steps']['research']['progress'] = {'done': done, 'total': len(items)}
    return done, len(items)


def _save(base, data, *sids):
    cw.write_case_json(base, data)
    try:
        case_memory.update_section(base, data, 'status', *sids)
    except Exception:
        pass       # الذاكرة مشتقة: فشلها لا يُفشل الخطوة


def _write_item(base, data, point, it, ask, missing=None):
    import case_readiness as cr
    prev = [(i['n'], i['summary']) for i in data['research']
            if i['n'] < it['n'] and i['state'] in cm.OK_STATES and i.get('summary')]
    facts = cr.facts_table(cr.doc_index(base, data))
    text = ask(build_prompt(base, data, point, prev, missing, facts))
    body, summary = split_response(text)
    import research_pipeline as _rp
    body, summary = _rp.clean_display(body).strip(), _rp.strip_internal(summary).strip()   # بلا رموز/صفحات من أي مسار
    if not body:
        raise RuntimeError('ردّ المزوّد فارغ')
    body = cr.mark_unverified_numbers(body, cr.fact_numbers(facts))
    if missing:
        absent = [x for x in missing if f'[ناقص: {x}]' not in body]
        if absent and '[ناقص:' not in body:
            body = ''.join(f'[ناقص: {x}]\n' for x in absent) + body
        it['written_with_missing'] = list(missing)
    else:
        it.pop('written_with_missing', None)
    rel = it.get('file') or os.path.join(ITEMS_DIR, f"{point['n']:02d}.md").replace('\\', '/')
    case_documents._write_md(base, rel, body)
    with open(os.path.join(base, rel), 'rb') as f:
        sha = hashlib.sha1(f.read()).hexdigest()
    it.update(file=rel, summary=summary, sha1=sha, state='done', message='', point_text=point['text'])
    it['stale'] = False


def _mark_later_stale(data, it):
    for o in data['research']:
        if o['n'] > it['n'] and o['state'] in cm.OK_STATES:
            o['stale'] = True


def run_research(base, data, ask=None, on_item=None, stop=None, include_stale=False, force=False, only=None):
    """يكتب البنود غير المكتملة بالتتابع (pending/failed، وstale إن include_stale). يرجع حالة الخطوة.
    يرفع cm.StepError إن لم تُراجَع المأمورية أو لم تكتمل المستندات (أو يتنازل الخبير عنها)."""
    ask = ask or default_ask
    rec = data['steps']['research']
    if rec['state'] in cm.OK_STATES and not rec.get('stale') and not force and not include_stale:
        return rec['state']
    if not data['mission'].get('points'):
        raise cm.StepError('لا توجد نقاط مأمورية للبحث فيها.')
    cm.set_step(data, 'research', 'running')
    for it in data['research']:
        if it['state'] == 'running':          # بقي من تشغيل انقطع
            it['state'] = 'pending'
    dropped = sync_items(data)
    _progress(data)
    _save(base, data, 'items')
    points = {p['id']: p for p in data['mission']['points']}
    for it in data['research']:
        todo = it['state'] not in cm.OK_STATES or (include_stale and it.get('stale'))
        if not todo or (only is not None and it['id'] not in only):   # فحص الجاهزية: الجاهزة فقط
            continue
        if stop and stop():
            cm.set_step(data, 'research', 'pending', f'أُوقف بعد {_progress(data)[0]} من {len(data["research"])} بنداً')
            _save(base, data, 'items')
            return 'pending'
        it['state'] = 'running'
        try:
            _write_item(base, data, points[it['id']], it, ask)
        except Exception as e:
            it.update(state='failed', message=str(e) or e.__class__.__name__)
            _progress(data)
            cm.set_step(data, 'research', 'failed', f"فشل البند {it['n']}: {it['message']}")
            _save(base, data, 'items')
            return 'failed'
        _mark_later_stale(data, it)
        _progress(data)
        _save(base, data, 'items')
        if on_item:
            on_item(it)
    done, total = _progress(data)
    note = f' (أُسقط {len(dropped)} بنداً لنقاط محذوفة)' if dropped else ''
    if done < total:                                   # بنود بانتظار مستند لم تُكتب بعد
        cm.set_step(data, 'research', 'needs_input', f'{done} من {total} بنداً مكتوباً — الباقي بانتظار مستند{note}')
        _save(base, data, 'items')
        return 'needs_input'
    cm.set_step(data, 'research', 'done', f'{done} بنداً مكتوباً{note}')
    _save(base, data, 'items')
    return 'done'


def rewrite_item(base, data, point_id, ask=None, missing=None):
    """إعادة كتابة بند واحد؛ اللاحق المكتمل يصير stale دون إعادة كتابته. يرجع حالة البند."""
    ask = ask or default_ask
    it = _item(data, point_id)
    point = next((p for p in data['mission']['points'] if p['id'] == point_id), None)
    if it is None or point is None:
        raise cm.StepError('البند غير موجود.')
    ok, why = cm.can_start(data, 'research')
    if not ok:
        raise cm.StepError(why)
    try:
        _write_item(base, data, point, it, ask, missing)
    except Exception as e:
        it.update(state='failed', message=str(e) or e.__class__.__name__)
        _progress(data)
        _save(base, data, 'items')
        return 'failed'
    _mark_later_stale(data, it)
    done, total = _progress(data)
    if done == total and cm.state(data, 'research') in ('needs_input', 'pending', 'failed'):
        if cm.state(data, 'research') != 'needs_input':
            cm.set_step(data, 'research', 'needs_input')
        cm.set_step(data, 'research', 'done', f'{done} بنداً مكتوباً')
    _save(base, data, 'items')
    return it['state']


def review_item(base, data, point_id):
    it = _item(data, point_id)
    if it is None or it['state'] not in cm.OK_STATES:
        raise cm.StepError('لا يمكن مراجعة بند لم يُكتب بعد.')
    it['state'] = 'reviewed'
    _save(base, data, 'items')
