# ===== conclusion_pipeline.py — «النتيجة» من نص البحث المعتمد وأرقامه فقط (2026-10-20) =====
# تُولَّد بعد دمج/اعتماد نص البحث (research_pipeline)، وبعد أي تعديل يدوي عليه تُعلَّم «تحتاج إعادة توليد» ولا تُعاد إلا
# بطلب الخبير. البنية (قواعد النتيجة في نماذج_صياغة_البحث.md):
#   «بعد الاطلاع على ملف الدعوى … خلصت الخبرة إلى التالي:» (الكود)
#   فقرة واحدة لكل محور مكتمل تبدأ بـ«أن…» وتنتهي بـ«، كما هو موضح تفصيلياً في بند البحث ورأي الخبرة (أولاً).» (الكود يضبطها)
#   فقرة محور الحساب تحمل الحكم المالي «أنه وبعد تصفية الحساب … بمبلغ وقدره X د.ك (بالحروف)» من حساب الكود حرفياً
#   «والله ولي التوفيق» (الكود؛ وفي Word يكتبها report_builder.closing)
# تحقق الكود: كل رقم/تاريخ/مبلغ (والمبالغ بالحروف) وارد في نص البحث، عدد الفقرات = عدد المحاور المكتملة، الإحالات
# تطابق ترتيب المحاور، لا نص مأمورية ولا «[يُكتب]». المحور غير المكتمل لا فقرة له وتظهر ملاحظة حمراء بما ينقص.
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal

import amounts
import calc
import case_model as cm
import case_workspace as cw

REL = '_نظام/04_تقرير/النتيجة.md'
OPENING = 'بعد الاطلاع على ملف الدعوى وما قدم من دفاع ومستندات وبعد المناقشة خلصت الخبرة إلى التالي:'
CLOSING = 'والله ولي التوفيق'
REF_TPL = 'كما هو موضح تفصيلياً في بند البحث ورأي الخبرة ({ordinal})'
_REF_RE = re.compile(r'[،,]?\s*(?:و)?كما\s+هو\s+(?:موضح|مبين)\s*(?:تفصيلياً|تفصيلاً|تفصيليا|تفصيلا)?\s*في\s+بند\s+'
                     r'البحث\s+ورأي\s+الخبر[ةه]\s*\(?\s*([^)\n]*?)\s*\)?\s*[.،]?\s*$')
_FORBIDDEN = ('[يُكتب]', '[يكتب]', '[ناقص', 'يتعذر على الخبرة', 'تعذر على الخبرة')


def _now():
    return datetime.now().isoformat(timespec='seconds')


def record(data):
    return (data.get('conclusion') or {}).get('v2')


def _rp():
    import research_pipeline
    return research_pipeline


MAX_BODY = 420          # حكم مباشر قصير: حروف الفقرة دون الإحالة والجملة المالية


def current_sha(base, data):
    """بصمة نص البحث المدموج الحالي (أساس «البحث تغيّر»)."""
    return hashlib.sha1(_rp().research_text(base, data).encode('utf-8')).hexdigest()


def needs_regen(base, data):
    """True إن وجب توليد النتيجة آلياً: محور مكتمل واحد على الأقل، ولا نتيجة أو تغيّر نص البحث، ولم يعدّلها الخبير.
    نتيجة عدّلها الخبير لا تُستبدل أبداً هنا (تظهر ملاحظة وزر «أعد صياغة النتيجة»)."""
    if not complete_axes(base, data):
        return False
    rec = record(data)
    if rec is None:
        return True
    if rec.get('edited'):
        return False
    return bool(rec.get('stale') or rec.get('source_sha') != current_sha(base, data)
                or rec.get('axes') != [a['key'] for a, _t in complete_axes(base, data)])


def complete_axes(base, data, include_drafted=False):
    """[(axis, نص المحور)] للمحاور المكتملة (كل أقسامها مدموجة؛ أو مسودة مع include_drafted للاستيراد)."""
    rp = _rp()
    out = []
    for a in rp.state(data).get('axes') or []:
        texts = [(s, rp.section_text(base, s)) for s in a['sections']]
        ok = (rp.S_MERGED, rp.S_DRAFTED) if include_drafted else (rp.S_MERGED,)
        if a['sections'] and all(s['state'] in ok and t for s, t in texts):
            body = [rp.heading(a)] + [(f"{s['title']}:\n" if s.get('title') else '') + t for s, t in texts]
            out.append((a, '\n\n'.join(body)))
    return out


def incomplete_axes(base, data, include_drafted=False):
    done = {a['key'] for a, _t in complete_axes(base, data, include_drafted)}
    return [a for a in _rp().state(data).get('axes') or [] if a['key'] not in done]


def financial_sentence(final):
    return (f"أنه وبعد تصفية الحساب بين الطرفين فإن ذمة {final['debtor']} مشغولة لصالح {final['creditor']} "
            f"بمبلغ وقدره {final['shown']} د.ك ({final['words']})")


def build_prompt(rules, models, axes, final, bad=None):
    parts = ["اكتب «النتيجة» لتقرير خبرة قضائي من نص «البحث ورأي الخبرة» المعتمد أدناه فقط. التزم بالأرقام والتواريخ "
             "والمبالغ الواردة فيه حرفياً، ولا تضف معلومة غير واردة فيه، ولا تنسخ نص المأمورية. كل نقطة حكم مباشر قصير "
             "(جملة أو جملتان) لا إعادة للبحث، بلا أي إحالة لمستند أو حافظة أو مرفق ولا أرقام صفحات.",
             "## قواعد النتيجة (ملزمة)\n" + rules]
    if models:
        parts.append("## نماذج من تقارير الخبير (للأسلوب فقط)\n" + '\n\n'.join(m['text'] for m in models))
    parts.append("## نص البحث المعتمد (محوراً محوراً)\n" + '\n\n'.join(t for _a, t in axes))
    if final:
        fax = next((a for a, _t in axes if a['key'] == final.get('axis')), None)
        if fax:
            parts.append(f"## الحكم المالي (ضعه حرفياً في فقرة المحور {fax['ordinal']})\n{financial_sentence(final)}")
    parts.append("## صيغة الرد (JSON فقط)\n"
                 '{"paragraphs":[{"axis":"أولاً","text":"أن …"}]}\n'
                 f"- فقرة واحدة لكل محور بالترتيب ({'، '.join(a['ordinal'] for a, _t in axes)})، تبدأ بـ«أن» أو «أنه»، "
                 "وتجيب عن المحور بحكم مباشر من خلاصته. لا تكتب الإحالة «كما هو موضح…» ولا الافتتاحية ولا الختام "
                 "(يضيفها البرنامج).")
    if bad:
        parts.append("تنبيه: رُفضت صياغتك السابقة لأنها تضمنت: " + '؛ '.join(bad) + ". أعدها دون ذلك.")
    return '\n\n'.join(parts)


def fix_paragraph(text, ordinal):
    """يحذف أي إحالة كتبها النموذج ويضيف الإحالة الصحيحة برقم المحور؛ ويبدأ الفقرة بـ«أن»."""
    import research_pipeline as _rp2
    t = ' '.join(_rp2.strip_refs(str(text or '').replace('**', '')).split())   # لا إحالة لمستند أو مرفق
    t = re.sub(r'^\s*(?:\d+[.)\-]\s*|[-•]\s*)', '', t)
    for _ in range(2):
        t = _REF_RE.sub('', t).strip()
    t = t.rstrip(' .،,؛')
    if not re.match(r'^(?:أن|ان|أنه|انه|أنها)\b', t):
        t = 'أن ' + t
    return f'{t}، {REF_TPL.format(ordinal=ordinal)}.'


def ref_of(paragraph):
    m = _REF_RE.search(paragraph or '')
    return m.group(1).strip() if m else ''


def _word_amounts(text):
    out = []
    for m in re.finditer(r'\(([^()]{6,220}?)\)', text or ''):
        v = amounts.words_to_decimal(m.group(1))
        if v is not None:
            out.append((m.group(1), calc.q3(v)))
    return out


def check(paragraphs, axes, research_text, mission_raw=''):
    """مشكلات تمنع القبول: العدد، الإحالات، أرقام/مبالغ غير واردة في البحث، نص المأمورية، «[يُكتب]»."""
    rp = _rp()
    problems = []
    if len(paragraphs) != len(axes):
        problems.append(f'عدد فقرات النتيجة ({len(paragraphs)}) لا يساوي عدد محاور البحث المكتملة ({len(axes)})')
    for p, (a, _t) in zip(paragraphs, axes):
        if ref_of(p['text']) != a['ordinal']:
            problems.append(f"إحالة الفقرة لا تطابق المحور {a['ordinal']}")
    allowed = calc.numbers_in(research_text)
    allowed_amt = {calc.q3(Decimal(x)) for x in allowed} | {v for _w, v in _word_amounts(research_text)}
    body = '\n'.join(_REF_RE.sub('', p['text']) for p in paragraphs)
    foreign = sorted(calc.numbers_in(body) - allowed, key=lambda x: (len(x), x))
    if foreign:
        problems.append('أرقام/تواريخ غير واردة في البحث: ' + '، '.join(foreign))
    for w, v in _word_amounts(body):
        if v not in allowed_amt:
            problems.append(f'مبلغ بالحروف غير وارد في البحث: «{w[:60]}»')
    if any(f in body for f in _FORBIDDEN):
        problems.append('في النتيجة علامة نقص («[يُكتب]» أو ما يشبهها)')
    echo = rp.mission_echo(body, mission_raw)
    if echo:
        problems.append('النتيجة تنسخ نص المأمورية')
    return problems


def parse_paragraphs(raw, axes):
    """فقرات من JSON النموذج، أو من نص حر (كل فقرة تبدأ بـ«أن»)؛ تُربط بالمحاور بالترتيب."""
    paras = []
    try:
        obj = json.loads(re.search(r'\{.*\}', str(raw or ''), re.S).group(0))
        for p in obj.get('paragraphs') or []:
            if isinstance(p, dict) and str(p.get('text') or '').strip():
                paras.append(str(p['text']).strip())
    except (AttributeError, ValueError, TypeError):
        lines = [l.strip() for l in str(raw or '').replace('\r', '').split('\n') if l.strip()]
        lines = [re.sub(r'^\s*(?:\d+[.)\-]\s*|[-•]\s*)', '', l) for l in lines]
        paras = [l for l in lines if re.match(r'^(?:أن|ان|أنه|انه|أنها)\b', l)]
    return [{'axis': a['key'], 'ordinal': a['ordinal'], 'text': fix_paragraph(t, a['ordinal'])}
            for t, (a, _x) in zip(paras, axes)] + [{'axis': '', 'ordinal': '', 'text': t} for t in paras[len(axes):]]


def _enforce_financial(paras, axes, final):
    """فقرة محور الحساب يجب أن تحمل المبلغ النهائي وحروفه كما حسبهما الكود؛ وإلا تُستبدل بجملة الكود."""
    if not final:
        return
    for p in paras:
        if p['axis'] == final.get('axis'):
            if final['shown'] not in p['text'] or final['words'] not in p['text']:
                p['text'] = fix_paragraph(financial_sentence(final), p['ordinal'])
                p['financial_by_code'] = True


def long_paragraphs(paras, axes):
    """ملاحظة حمراء (لا رفض) للفقرة الأطول من حكم مباشر قصير."""
    out = []
    for p, (a, _t) in zip(paras, axes):
        body = _REF_RE.sub('', p['text'])
        body = body.split('وبعد تصفية الحساب')[0] if 'وبعد تصفية الحساب' in body else body
        if len(body) > MAX_BODY:
            out.append(f"فقرة المحور {a['ordinal']} أطول من حكم مباشر قصير — اختصرها إن شئت")
    return out


def render_md(rec):
    out = ['# النتيجة', '', OPENING, '']
    out += [f"{i}. {p['text']}" for i, p in enumerate(rec.get('paragraphs') or [], 1)]
    out += ['', CLOSING]
    return '\n'.join(out) + '\n'


def text_of(rec):
    """النص الكامل للمعاينة/التعديل: الافتتاحية + الفقرات + الختام."""
    return '\n'.join([OPENING] + [p['text'] for p in rec.get('paragraphs') or []] + [CLOSING])


def _store(base, data, paras, axes, source, notes, research_sha):
    import case_documents as cd
    c = data.setdefault('conclusion', {'state': 'pending', 'file': REL})
    rec = {'paragraphs': paras, 'axes': [a['key'] for a, _t in axes], 'source': source, 'at': _now(),
           'source_sha': research_sha, 'notes': notes, 'edited': False, 'stale': False, 'state': 'done'}
    c['v2'] = rec
    c['file'] = REL
    c['state'] = 'done'
    cd._write_md(base, REL, render_md(rec))
    st = cm.state(data, 'conclusion')
    if st != 'done':
        if 'needs_input' in cm.ALLOWED[st] and st != 'needs_input':
            cm.set_step(data, 'conclusion', 'needs_input')
        cm.set_step(data, 'conclusion', 'done', f'{len(paras)} فقرة لـ{len(axes)} محوراً مكتملاً'
                    + (f' — {len(notes)} ملاحظة' if notes else ''))
    else:
        data['steps']['conclusion']['message'] = f'{len(paras)} فقرة لـ{len(axes)} محوراً مكتملاً'
    data['steps']['conclusion']['stale'] = False
    cw.write_case_json(base, data)
    return rec


def _missing_notes(base, data, include_drafted=False):
    return [f"لم يكتمل المحور {a['ordinal']} ({a['title'][:60]}) — لا فقرة له في النتيجة"
            for a in incomplete_axes(base, data, include_drafted)]


def generate(base, data, ask=None, force=False):
    """يولّد النتيجة من المحاور المكتملة. يرجع حالة الخطوة. لا محور مكتمل ← StepError."""
    rp = _rp()
    import report_v3
    if report_v3.is_v3(data):                 # التقرير المركَّب: النتيجة من الحقائق والأرقام المحسوبة نفسها (لا من النموذج)
        return report_v3.store_conclusion(base, data, force=force)
    axes = complete_axes(base, data)
    if not axes:
        raise cm.StepError('لا محور مكتمل في البحث بعد — ادمج أقسام محور واحد على الأقل.')
    old = record(data)
    if old and not force and (old.get('edited') or (not old.get('stale') and old.get('axes') == [a['key'] for a, _t in axes]
                                                   and old.get('source_sha') == current_sha(base, data))):
        return cm.state(data, 'conclusion')      # المعدَّلة يدوياً لا تُستبدل إلا بطلب الخبير (force)
    if ask is None:
        import case_research
        ask = lambda p: case_research.default_ask(p, 'research')          # noqa: E731
    _rules, models, crules = rp._library()
    models = rp.pick_models(models, rp.case_type(data), 'نتيجة', limit=2)
    research = '\n\n'.join(t for _a, t in axes)
    final = rp.case_final(data)
    mission_raw = (data.get('mission') or {}).get('raw') or ''
    bad = None
    for _attempt in range(2):
        paras = parse_paragraphs(ask(build_prompt(crules, models, axes, final, bad)), axes)
        _enforce_financial(paras, axes, final)
        problems = check(paras, axes, research, mission_raw)
        import ai_call_log
        ai_call_log.verdict(not problems, 'فقرات النتيجة سليمة' if not problems else 'رُفضت: ' + '؛ '.join(problems))
        if not problems:
            break
        bad = problems
    long_notes = [] if problems else long_paragraphs(paras, axes)
    if problems:
        data.setdefault('conclusion', {})['v2_error'] = '؛ '.join(problems)
        if old:
            old['notes'] = list(dict.fromkeys((old.get('notes') or []) + ['تعذّر إعادة التوليد: ' + '؛ '.join(problems)]))
        cw.write_case_json(base, data)
        raise cm.StepError('رُفضت النتيجة المولّدة بعد إعادة الطلب: ' + '؛ '.join(problems))
    if not rp.state(data).get('axes') or cm.state(data, 'research') not in cm.OK_STATES:
        data['steps']['research']['waived'] = True          # الخبير طلب النتيجة للمحاور المكتملة فقط
    notes = _missing_notes(base, data) + long_notes
    data.get('conclusion', {}).pop('v2_error', None)
    _store(base, data, paras, axes, 'api', notes, current_sha(base, data))
    return cm.state(data, 'conclusion')


def accept_text(base, data, text, source='file', include_drafted=False):
    """نتيجة كتبها نموذج الخبير/Copilot (من ردّ prompt.md): تمر بالضبط والتحقق نفسيهما. يرجع وصفاً قصيراً."""
    rp = _rp()
    axes = complete_axes(base, data, include_drafted)
    if not axes:
        raise cm.StepError('لا محور مكتمل لربط فقرات النتيجة به.')
    lines = [l for l in rp.strip_internal(text).split('\n') if l.strip() and OPENING[:20] not in l and 'ولي التوفيق' not in l]
    paras = parse_paragraphs('\n'.join(lines), axes)
    _enforce_financial(paras, axes, rp.case_final(data))
    problems = check(paras, axes, '\n\n'.join(t for _a, t in axes), (data.get('mission') or {}).get('raw') or '')
    if problems:
        raise cm.StepError('؛ '.join(problems))
    _store(base, data, paras, axes, source, _missing_notes(base, data, include_drafted), current_sha(base, data))
    return f'قُبلت ({len(paras)} فقرة)'


def set_text(base, data, text):
    """تعديل الخبير اليدوي لنص النتيجة: الفقرات كما كتبها (بلا الافتتاحية والختام)، وتُعلَّم «عدّلها الخبير»."""
    import case_documents as cd
    rec = record(data)
    if rec is None:
        raise cm.StepError('لم تُولَّد النتيجة بعد.')
    lines = [l.strip() for l in _rp().strip_internal(text).split('\n') if l.strip()]
    lines = [l for l in lines if OPENING[:20] not in l and 'ولي التوفيق' not in l]
    lines = [re.sub(r'^\s*\d+[.)\-]\s*', '', l) for l in lines]
    if [p['text'] for p in rec['paragraphs']] == lines:
        return
    old = rec['paragraphs']
    rec['paragraphs'] = [{'axis': old[i]['axis'] if i < len(old) else '', 'ordinal': old[i]['ordinal'] if i < len(old) else '',
                          'text': l} for i, l in enumerate(lines)]
    rec['edited'] = True
    cd._write_md(base, REL, render_md(rec))
    if cm.state(data, 'conclusion') == 'reviewed':
        cm.set_step(data, 'conclusion', 'done')
    cw.write_case_json(base, data)


def notes(base, data):
    """ملاحظات حمراء للنتيجة: المحاور الناقصة، تعديل البحث بعد التوليد، خطأ آخر توليد."""
    rec = record(data) or {}
    out = list(rec.get('notes') or [])
    if rec and (rec.get('stale') or (rec.get('source_sha') and rec.get('source_sha') != current_sha(base, data))):
        out.append('البحث تغيّر بعد تعديلك للنتيجة — «إعادة الكتابة» تكتب البحث والنتيجة من جديد' if rec.get('edited') else 'عُدّل نص البحث بعد توليد النتيجة — ستُحدَّث تلقائياً')
    err = (data.get('conclusion') or {}).get('v2_error')
    if err:
        out.append(f'آخر محاولة توليد رُفضت: {err}')
    return out


def research_sha(text):
    return hashlib.sha1((text or '').encode('utf-8')).hexdigest()
