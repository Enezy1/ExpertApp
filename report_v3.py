# ===== report_v3.py — تشغيل التقرير المركَّب بالكود: الحقائق ← الخانات ← التركيب ← التدقيق ← الحفظ (2026-10-20) =====
# 1) case_facts.build (قارئ الكود + استخراج النموذج المتحقَّق حرفياً)  2) calc.ledger (Decimal)
# 3) report_compose.draft_slots (النموذج يملأ خانات قصيرة بعبارات مرجعية؛ المرفوض يُعاد مرة ثم احتياطي الكود)
# 4) report_compose.compose (البحث محوراً محوراً + الموضوع + الإجراءات + النتيجة من الحقائق)
# 5) report_audit.audit — فشل ← إعادة الصياغة تلقائياً مرة واحدة بقائمة الأخطاء (خانات المحاور المعنية)، ثم احتياطي الكود
#    لتلك المحاور؛ إن بقي خطأ ← الأقسام «فشل التدقيق» بخط أحمر مع الأسباب (لا تُدمج ولا تُعرض كأنها سليمة).
# 6) الحفظ بالشكل القائم: research2 (محور = قسم واحد «:v3»)، النتيجة في research2['v3']['conclusion'] ثم conclusion.v2 عند الدمج،
#    الموضوع (إن لم يعدّله الخبير)، نص الإجراءات (إن لم يعدّله)، الملاحظات الحمراء، «كُتب بواسطة»، ذاكرة_القضية.md.
import json
import re

import case_facts as cf
import case_model as cm
import case_workspace as cw
import report_audit as ra
import report_compose as rc
import report_playbooks as pb

ENABLED = True                      # المسار الجديد افتراضي لكل القضايا؛ الاختبارات القديمة تطفئه
N_AUDIT = 'فشل التدقيق'
PROMPT_MARK = '===الخانات==='
WORD_LIMIT = 900                    # تقرير فواتير بخطين أقل من 900 كلمة (الجداول ضمن العدّ)


def _rp():
    import research_pipeline
    return research_pipeline


def is_v3(data):
    return (_rp().state(data).get('engine') == rc.ENGINE)


_RP_KIND = {pb.AX_REL: 'علاقة', pb.AX_BREACH: 'إخلال', pb.AX_DEBT: 'حساب', pb.AX_DEF: 'اعتراضات'}


def _slots_of_axes(ctx, keys):
    out = set()
    for sid, kind, _d, _m in rc.slot_specs(ctx):
        if any(sid.startswith(k + '.') for k in keys) or (sid.startswith('rel.') and any(
                a['kind'] == pb.AX_REL and a['key'] in keys for a in ctx.axes)):
            out.add(sid)
    return out


def _compose(ctx, S):
    """التركيب بالكود ثم حذف الجملة المكررة (تشابه ≥ 95%) بالكود (report_audit.dedupe) — يُسجَّل «حُذف تكرار» في
    ملاحظات البحث بدل إفشال المحور بفحص التكرار."""
    rep, _gone = ra.dedupe(rc.compose(ctx, S))
    return rep


def produce(ctx, ask, slots=None, single=False):
    """(التقرير، الأخطاء، السجل). slots جاهزة (من ملف/Copilot) تُستعمل بدل طلب النموذج.
    single=True (المرحلة الثالثة): الخانات جاءت مع الطلب الواحد؛ المرفوض منها وما فشل في التدقيق يُعاد معاً
    بطلب واحد فقط (إن وُجد ask)، ثم ما بقي ← جمل الكود الاحتياطية."""
    if slots is None:
        S, log = rc.draft_slots(ctx, ask)
    else:
        S, log = imported_slots(ctx, slots)
    rep = _compose(ctx, S)
    errs = ra.audit(rep, ctx)
    log['audit_attempts'] = 1
    _audit_verdict(errs, slots if not single else None)
    if single:
        redo = set(log.get('rejected') or {})
        if errs:
            redo |= _slots_of_axes(ctx, ra.axes_of_errors(errs, rep) or {a['key'] for a in ctx.axes})
        if redo and ask is not None:
            by_slot = {sid: list((log.get('rejected') or {}).get(sid) or []) + [
                e for e in errs if any(e.find(f"المحور {a['ordinal']}") >= 0 for a in ctx.axes
                                       if sid.startswith(a['key']))] for sid in redo}
            S2, log2 = rc.draft_slots(ctx, ask, errors_by_slot=by_slot, only=redo, prev=S, attempts=1)
            rep2 = _compose(ctx, S2)
            errs2 = ra.audit(rep2, ctx)
            _audit_verdict(errs2, None)
            if errs2:
                keys2 = ra.axes_of_errors(errs2, rep2) or {a['key'] for a in ctx.axes}
                S3 = dict(S2, **{sid: rc.fallback(ctx, sid) for sid in _slots_of_axes(ctx, keys2)})
                rep3 = _compose(ctx, S3)
                errs3 = ra.audit(rep3, ctx)
                if len(errs3) <= len(errs2):
                    rep2, errs2, S2 = rep3, errs3, S3
            log.update(redraft=log2, first_errors=errs, audit_attempts=2)
            rep, errs, S = rep2, errs2, S2
        elif errs:                                   # بلا إعادة (المتصفح): ما فشل ← جمل الكود
            keys = ra.axes_of_errors(errs, rep) or {a['key'] for a in ctx.axes}
            S3 = dict(S, **{sid: rc.fallback(ctx, sid) for sid in _slots_of_axes(ctx, keys)})
            rep3 = _compose(ctx, S3)
            errs3 = ra.audit(rep3, ctx)
            if len(errs3) <= len(errs):
                log['first_errors'] = errs
                rep, errs, S = rep3, errs3, S3
    elif errs:                                       # إعادة الصياغة تلقائياً مرة واحدة بقائمة الأخطاء
        keys = ra.axes_of_errors(errs, rep) or {a['key'] for a in ctx.axes}
        only = _slots_of_axes(ctx, keys)
        by_slot = {sid: [e for e in errs if any(e.find(f"المحور {a['ordinal']}") >= 0 for a in ctx.axes
                                                if sid.startswith(a['key']))] or errs[:6] for sid in only}
        S2, log2 = rc.draft_slots(ctx, ask, errors_by_slot=by_slot, only=only, prev=S)
        rep2 = _compose(ctx, S2)
        errs2 = ra.audit(rep2, ctx)
        _audit_verdict(errs2, slots)
        if errs2:                                    # ما بقي في تلك المحاور ← جمل الكود الاحتياطية
            keys2 = ra.axes_of_errors(errs2, rep2) or keys
            S3 = dict(S2, **{sid: rc.fallback(ctx, sid) for sid in _slots_of_axes(ctx, keys2)})
            rep3 = _compose(ctx, S3)
            errs3 = ra.audit(rep3, ctx)
            if len(errs3) <= len(errs2):
                rep2, errs2, S2 = rep3, errs3, S3
                log2['fallback'] = sorted(set(log2.get('fallback', [])) | _slots_of_axes(ctx, keys2))
        log.update(redraft=log2, first_errors=errs, audit_attempts=2)
        rep, errs, S = rep2, errs2, S2
    if not errs and rc.word_count(rep) >= WORD_LIMIT:      # تقرير موجز: أطول خانات النموذج ← جملة الكود حتى يقل عن الحد
        for sid in sorted((k for k in S if k in (log.get('model') or [])), key=lambda k: -len(S[k].split())):
            S = dict(S, **{sid: rc.fallback(ctx, sid)})
            cand = _compose(ctx, S)
            if not ra.audit(cand, ctx):
                rep = cand
                log.setdefault('shortened', []).append(sid)
            if rc.word_count(rep) < WORD_LIMIT:
                break
    log['slots'] = S
    return rep, errs, log


def _audit_verdict(errs, slots):
    """مدقّق التقرير النهائي حكم على آخر طلب خانات (إن وُجد طلب في هذا الخيط): الرفض هنا يعني أن التقرير المركَّب فشل التدقيق."""
    if slots is not None:
        return
    import ai_call_log
    ai_call_log.verdict(not errs, 'اجتاز التقرير المركَّب التدقيق النهائي' if not errs
                        else 'فشل التدقيق النهائي: ' + '؛ '.join(errs[:3]))


def imported_slots(ctx, slots):
    """خانات من ردّ ملف/Copilot: تمر بفحص الخانة نفسه، والمرفوض ← احتياطي الكود."""
    S, log = {}, {'attempts': 1, 'rejected': {}, 'fallback': [], 'model': []}
    for sid, *_r in rc.slot_specs(ctx):
        text, errs = rc.check_slot(sid, slots.get(sid), ctx, list(S.values()))
        if errs:
            S[sid] = rc.fallback(ctx, sid)
            log['rejected'][sid] = errs
            log['fallback'].append(sid)
        else:
            S[sid] = text
            log['model'].append(sid)
    return S, log


def run(base, data, ask=None, extract_ask=None, on_progress=None, stop=None, force=False, slots=None,
        full_reply=None, source='api'):
    """يكتب البحث كله بالمسار المركَّب. يرجع حالة خطوة البحث.
    المرحلة الثالثة (slots=None): طلب واحد (full_prompt) يعيد الحقائق المالية باقتباساتها والخانات القصيرة معاً؛
    full_reply: ردّ جاهز لهذا الطلب (عبر المتصفح) يمر على التحقق نفسه بلا أي طلب."""
    import case_facts as cf
    rp = _rp()
    if not (data.get('mission') or {}).get('points'):
        raise cm.StepError('لا توجد بنود مأمورية للبحث فيها.')
    cm.set_step(data, 'research', 'running')
    ctype = pb.case_type(data)
    if slots is not None:                            # ردّ خانات وحدها (ملف/Copilot القديم)
        try:
            facts = cf.build(base, data, ask=extract_ask or ask, force=force, case_type=ctype)
        except Exception as e:                       # تعذّر الاستخراج ← قارئ الكود وحده (مع ملاحظة) بدل الفشل
            facts = cf.build(base, data, ask=None, case_type=ctype)
            facts['notes'].append(['ناقص', f'تعذّر استخراج النموذج ({str(e) or e.__class__.__name__}) — قارئ الكود وحده'])
        ctx = rc.Ctx(data, facts, ctype)
        rep, errs, log = produce(ctx, ask, slots)
    else:
        import ai_call_log
        if full_reply is None:
            if ask is None:
                ask = default_ask
            pre = cf.build(base, data, ask=None, case_type=ctype)         # قارئ الكود: مفاتيح الخانات قبل الطلب
            ai_call_log.detail('البحث ورأي الخبرة — طلب واحد (الحقائق المالية + الخانات)')
            import case_research
            try:
                with case_research.long_request():                  # كتابة التقرير بطلب واحد تحتاج وقتاً
                    full_reply = ask(full_prompt(base, data, rc.Ctx(data, pre, ctype)))
            except Exception as e:
                import case_folder
                if case_folder.is_key_failure(e):
                    raise
                cm.set_step(data, 'research', 'failed', f'تعذّر طلب البحث: {str(e) or e.__class__.__name__}')
                cw.write_case_json(base, data)
                raise
            retry_ask = ask
        else:
            retry_ask = None                         # ردّ المتصفح: نفس التحقق، والمرفوض ← جمل الكود
        obj = cf._parse_json(full_reply) or {}
        facts = cf.build(base, data, ask=lambda _p: full_reply, force=True, case_type=ctype)
        reqs = pdf_requests(base, facts)
        if reqs and retry_ask is not None:           # مستند مهم نصه رديء ← طلب ثانٍ ومعه PDF الأصلي
            with case_research.long_request():
                got2 = reread_pdf(base, data, reqs, full_prompt(base, data, rc.Ctx(data, facts, ctype)))
            if got2 is not None:
                reply2, obj2 = got2
                facts2 = cf.build(base, data, ask=lambda _p: reply2, force=True, case_type=ctype,
                                  reread=obj2.get('reread') if isinstance(obj2.get('reread'), list) else [])
                if _n_facts(facts2) > _n_facts(facts):     # التعادل ← الأولى (A2263970: الثانية بلا reread أضاعت فاتورتين)
                    full_reply, obj, facts = reply2, obj2, facts2
                else:                                # القراءة الثانية أضعف ← الأولى كما كانت
                    facts = cf.build(base, data, ask=lambda _p: full_reply, force=True, case_type=ctype)
                    facts['notes'].append(['قرار يحتاج مراجعة الخبير', 'إعادة القراءة من PDF لم تزد الفواتير '
                                           'والحقائق المتحقَّقة على الأولى — اعتُمدت القراءة الأولى'])
        elif reqs:                                   # ردّ المتصفح: لا إرسال ملفات من هنا
            facts['notes'].append(['قرار يحتاج مراجعة الخبير', 'طلب النموذج قراءة PDF لـ'
                                   + '، '.join(f'{c} ({why})' for c, _p, _a, _b, why in reqs)
                                   + ' — أعد كتابة البحث عبر API ليُرسل له الملف'])
        if not obj:
            facts['notes'].append(['ناقص', 'ردّ البحث ليس JSON صالحاً — الحقائق من قارئ الكود وحده'])
        if on_progress:
            on_progress({'ordinal': '', 'key': ''}, {'key': '', 'progress': 40, 'contract_title': 'الحقائق جاهزة'})
        ctx = rc.Ctx(data, facts, ctype)
        got = obj.get('slots') if isinstance(obj.get('slots'), dict) else {}
        if retry_ask is not None:
            ai_call_log.verdict(bool(obj), ('حقائق متحقَّقة وخانات' if obj else 'ردّ ليس JSON صالحاً'))
        rep, errs, log = produce(ctx, retry_ask, got, single=True)
        log['source'] = source
    store(base, data, ctx, rep, errs, log)
    if on_progress:
        for a, s in rp.all_sections(data):
            on_progress(a, s)
    return cm.state(data, 'research')


# ---------- إعادة قراءة مستند من PDF (2026-10-25) ----------
# النموذج يطلب ملف مستند مهم نصه رديء (need_pdf)، أو يطلبه البرنامج تلقائياً حين تكون صفحات حافظة مدموجة عند التحويل ولم
# تتحقق الفواتير. طلب ثانٍ واحد فقط: الطلب نفسه + PDF الأصلي (صفحاته المطلوبة) + «reread» نص كل صفحة استند إليها من الملف،
# فيتحقق المدقّق من الاقتباس في نص PDF الجديد أو markdown القديم. لا يُعدَّل ملف markdown.

PDF_ASK = None                         # الاختبارات: fn(prompt, paths) بدل الطلب الحقيقي
MAX_PDF_DOCS = 2
MAX_PDF_PAGES = 40
AUTO_REREAD_REMOVED = 3                # عناصر حُذفت لعدم التحقق ← قراءة الحافظة المدموجة تلقائياً
_NO_CITE = ('صحيفة الدعوى', 'حكم الإحالة')


def _n_facts(f):
    """(الفواتير المتحقَّقة، كل الحقائق) — الفواتير أولاً: هي ما يُحسب منه المتبقي."""
    return (len(f.get('invoices') or []),
            sum(len(f.get(k) or []) for k in ('contracts', 'service_orders', 'invoices', 'payments')))


def _range(pages):
    nums = [int(x) for x in re.findall(r'\d+', str(pages or '').translate(cf._DIG))]
    return (min(nums), max(nums)) if nums else (None, None)


def pdf_requests(base, facts):
    """[(رمز، مسار PDF، من، إلى، السبب)] — طلبات النموذج أولاً، ثم التلقائي (حافظة مدموجة الصفحات وتحقق ضعيف)."""
    import os
    docs = {d['code']: d for d in facts.get('docs') or []}
    out = []

    def add(code, a, b, why):
        d = docs.get(code)
        if d is None or d['kind'] in _NO_CITE or any(o[0] == code for o in out) or len(out) >= MAX_PDF_DOCS:
            return
        path = os.path.join(base, d.get('file') or '')
        if path.lower().endswith('.pdf') and os.path.isfile(path):
            out.append((code, path, a, b, why))
    for r in facts.get('need_pdf') or []:
        a, b = _range(r.get('pages'))
        add(r['doc'], a, b, r.get('why') or 'طلبه النموذج')
    if not (facts.get('invoices') or []) or (facts.get('removed') or 0) >= AUTO_REREAD_REMOVED:
        for d in facts.get('docs') or []:
            if d.get('merged') and not d.get('memo'):
                add(d['code'], min(a for a, _b in d['merged']), max(b for _a, b in d['merged']),
                    'صفحات مدموجة عند التحويل')
    return out


def cut_pdf(path, a, b, tmpdir):
    """(مسار الجزء، من، إلى) — صفحات a..b (1-based، حتى MAX_PDF_PAGES) من الملف الأصلي."""
    import os
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(path)
    n = len(r.pages)
    a = max(1, a or 1)
    b = min(n, b or n, a + MAX_PDF_PAGES - 1)
    w = PdfWriter()
    for i in range(a - 1, b):
        w.add_page(r.pages[i])
    out = os.path.join(tmpdir, f'part{len(os.listdir(tmpdir)) + 1}.pdf')
    with open(out, 'wb') as f:
        w.write(f)
    return out, a, b


def reread_prompt(prompt, parts):
    lines = ['## إعادة القراءة من ملفات PDF المرفقة',
             'أرفقنا الملفات الأصلية للمستندات التالية لأن نصها المحوَّل أعلاه رديء أو صفحاته مدموجة:']
    for i, (code, _p, a, b, why) in enumerate(parts, 1):
        lines.append(f'- المرفق {i} = {code}، الصفحات {a}–{b} من الملف (صفحته الأولى = الصفحة {a}) — {why}')
    lines += ['اقرأ هذه الصفحات من PDF مباشرة، وأعد JSON كاملاً بالشكل نفسه أعلاه (الحقائق والخانات معاً)، واقتباساتك '
              'من نص PDF، و page = رقم الصفحة الأصلي في الملف.',
              'وأضف مفتاح "reread": [{"doc": "D3", "page": 12, "text": "نص الصفحة حرفياً كما في PDF، الجداول كجداول '
              'Markdown بأعمدتها، دون ترجمة"}] لكل صفحة استندت إليها من PDF.',
              'لا تطلب need_pdf مرة أخرى.']
    return prompt + _NL * 2 + _NL.join(lines)


def reread_pdf(base, data, reqs, prompt):
    """(الرد، obj) من الطلب الثاني بالملفات، أو None إن تعذّر (يبقى الرد الأول). يُسجَّل في سجل طلبات القضية."""
    import shutil
    import tempfile
    import ai_call_log
    tmp = tempfile.mkdtemp(prefix='reread_')
    try:
        parts, paths = [], []
        for code, path, a, b, why in reqs:
            try:
                out, a2, b2 = cut_pdf(path, a, b, tmp)
            except Exception:
                continue
            parts.append((code, path, a2, b2, why))
            paths.append(out)
        if not paths:
            return None
        p2 = reread_prompt(prompt, parts)
        if PDF_ASK is not None:
            fn = PDF_ASK
        else:
            import case_research
            fn = ai_call_log.wrap(lambda pr: case_research.ask_with_files(pr, paths), 'البحث — إعادة قراءة PDF', base)
        ai_call_log.detail('إعادة قراءة PDF: ' + '، '.join(f'{c} ص{a}–{b}' for c, _p, a, b, _w in parts))
        try:
            reply = fn(p2) if PDF_ASK is None else fn(p2, paths)
        except Exception as e:
            import case_folder
            if case_folder.is_key_failure(e):
                raise
            return None
        obj = cf._parse_json(reply)
        ai_call_log.verdict(bool(obj), 'ردّ إعادة القراءة JSON' if obj else 'ردّ إعادة القراءة ليس JSON صالحاً')
        return (reply, obj) if obj else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- المرحلة الثالثة: طلب واحد (الحقائق المالية + الخانات) ----------

_CRITICAL = re.compile(r'فاتور|كشف|رصيد|عقد|اتفاقي|إجمالي|اجمالي|مستحق|سداد|مديوني|غرام|Invoice|Statement|Total|'
                       r'Contract|Balance|\|', re.I)
MAX_CRITICAL_CHARS = 200_000
_NL = chr(10)


def critical_docs(docs):
    """المستندات الحاسمة فقط: مذكرات الدفاع كاملة، ومن غيرها (الحوافظ…) صفحات العقد والكشوف والفواتير وحدها.
    الصحيفة والحكم والمحاضر لا تُرسل نصوصها (ملخصها في الملخص.md)."""
    out, budget = [], MAX_CRITICAL_CHARS
    for d in docs:
        kind = d.get('kind') or ''
        if any(w in kind for w in ('صحيف', 'حكم', 'محضر')):
            continue
        pages = d['pages'] if d.get('memo') else [(n, t) for n, t in d['pages'] if _CRITICAL.search(t or '')]
        if not pages:
            continue
        size = sum(len(t or '') for _n, t in pages)
        if size > budget:
            keep, room = [], budget
            for n, t in pages:
                if len(t or '') > room:
                    break
                keep.append((n, t))
                room -= len(t or '')
            pages = keep
        if pages:
            out.append(dict(d, pages=pages))
            budget -= sum(len(t or '') for _n, t in pages)
        if budget <= 0:
            break
    return out


FULL_DOCS_TOKENS = 150_000             # ميزانية تقديرية لنصوص كل المستندات في طلب البحث (حرف ÷ 2.5)؛ فوقها ← الحاسمة فقط
CHARS_PER_TOKEN = 2.5


def research_docs(docs, budget_tokens=None):
    """(المستندات، كاملة؟): نص كل مستندات القضية markdown كاملاً إن وسعته الميزانية، وإلا اختيار الحاسمة (critical_docs)."""
    budget = FULL_DOCS_TOKENS if budget_tokens is None else budget_tokens
    chars = sum(len(t or '') for d in docs for _n, t in d['pages'])
    if docs and chars / CHARS_PER_TOKEN <= budget:
        return docs, True
    return critical_docs(docs), False


def full_prompt(base, data, ctx0=None):
    """الطلب الواحد للبحث: الملخص.md كاملاً + نصوص المستندات الحاسمة + المأمورية + قواعد مكتبة البحث + شكل JSON
    (الحقائق المالية باقتباساتها + خانات المحاور القصيرة بالعبارات المرجعية). يُستعمل نفسه عبر المتصفح."""
    import case_facts as cf
    import case_summary
    import drafting_library as dl
    ctype = pb.case_type(data)
    if ctx0 is None:
        ctx0 = rc.Ctx(data, cf.build(base, data, ask=None, case_type=ctype), ctype)
    docs = cf.corpus(base, data)
    crit, whole = research_docs(docs)
    plist = cf.parties(data, [_NL.join(t for _n, t in d['pages']) for d in docs])
    ext = cf.extract_prompt(crit, plist, ctype)
    head_rules, _sep, docs_txt = ext.partition(_NL * 2 + '## المستندات')
    head_rules = head_rules.split(_NL * 2, 1)[1] if _NL * 2 in head_rules else head_rules
    slot_lines = [l for l in rc.slots_prompt(ctx0, rc.slot_specs(ctx0)).splitlines()[1:]
                  if not l.startswith('أجب بـJSON')]
    mission = _NL.join(f"{p.get('n', i)}) {p['text']}" for i, p in enumerate(data['mission'].get('points') or [], 1))
    try:
        lib_rules = dl.parse(dl._read(dl.program_path(dl.RESEARCH_FILE)))[0].strip()
    except Exception:
        lib_rules = ''
    return (_NL * 2).join(x for x in [
        'أنت خبير قضائي تكتب «البحث ورأي الخبرة» في تقرير خبرة كويتي. قرأتَ ملخص القضية المتحقَّق و'
        + ('نصوص كل مستندات القضية' if whole else 'المستندات الحاسمة') + ' أدناه. '
        'في طلب واحد: (أ) استخرج الحقائق المالية باقتباساتها، (ب) واكتب الخانات القصيرة لكل محور بالعبارات المرجعية. '
        'البرنامج يحسب كل الأرقام ويركّب المحاور والجداول والنتيجة ويدقّقها بنفسه.',
        '## (أ) الحقائق المالية', head_rules,
        '## (ب) الخانات القصيرة', _NL.join(slot_lines),
        'أجب بـJSON واحد فقط يجمع مفاتيح الحقائق أعلاه ومفتاح "slots": {"معرّف الخانة": "النص"}، بلا أي نص آخر.',
        '## المأمورية', mission,
        ('## قواعد مكتبة البحث' + _NL + lib_rules) if lib_rules else '',
        '## ملخص القضية المتحقَّق (الملخص.md)', case_summary.verified_text(base, data).strip(),
        ('## مستندات القضية كاملة' if whole else '## المستندات الحاسمة (العقد، الكشوف والفواتير، مذكرات الدفاع)')
        + docs_txt] if x)


def browser_prompt(base, data):
    """ملف الطلب عبر المتصفح (prompt.md): التعليمات وقواعد الأسلوب ونماذج البحث كاملة + الملخص.md كاملاً + المأمورية بمحاورها
    + نصوص المستندات الحاسمة (كلها من full_prompt نفسه) + الأرقام المحسوبة بالكود + شكل الرد: البحث بمحاوره ثم النتيجة.
    الرد JSON نفسه فيمر على التحقق ذاته (import_full_reply)."""
    import case_facts as cf
    import drafting_library as dl
    ctype = pb.case_type(data)
    ctx0 = rc.Ctx(data, cf.build(base, data, ask=None, case_type=ctype), ctype)
    base_text = full_prompt(base, data, ctx0)
    L = ctx0.L
    nums = []
    for g in L.get('groups') or []:
        rows = g.get('rows') or []
        if not rows:
            continue
        amt = sum((r['amount'] for r in rows), calc_zero())
        paid = sum((r['paid'] for r in rows), calc_zero())
        nums.append(f"- الخط/العقد {g.get('line') or g.get('contract') or g['key']}: {len(rows)} فاتورة، مجموعها "
                    f"{cf.money(amt)} د.ك، المسدد {cf.money(paid)} د.ك، المتبقي {cf.money(amt - paid)} د.ك")
    T = L.get('total') or {}
    if T:
        nums.append(f"- إجمالي المتبقي المحسوب: {cf.money(T.get('remaining'))} د.ك")
    if L.get('claim') is not None:
        nums.append(f"- المبلغ المطالب به: {cf.money(L['claim'])} د.ك")
    if not nums:
        nums.append('- لم يستخرج قارئ الكود فواتير من الجداول بعد — استخرجها أنت في invoices باقتباساتها.')
    axes = []
    specs = rc.slot_specs(ctx0)
    for a in ctx0.axes:
        ids = [sid for sid, kind, _d, _m in specs if kind == a['kind']]
        axes.append(f"{a['ordinal']}) {a['title']} — خاناته: " + ('، '.join(ids) if ids else 'يكتبه البرنامج من الحقائق'))
    try:
        lib = dl._read(dl.program_path(dl.RESEARCH_FILE)).strip()
    except Exception:
        lib = ''
    return (_NL * 2).join(x for x in [
        base_text,
        '## الأرقام المحسوبة بالكود (للاطلاع — لا تكتب أرقاماً من عندك)', _NL.join(nums),
        ('## نماذج وقواعد أسلوب البحث (مكتبة الخبير كاملة)' + _NL + lib) if lib else '',
        '## شكل الرد المطلوب',
        'البحث بمحاوره بالترتيب ثم النتيجة: لكل محور اكتب خاناته القصيرة في "slots" بأسلوب النماذج أعلاه، والحقائق المالية '
        'في مفاتيحها باقتباساتها. البرنامج يركّب من ردك نص كل محور بجداوله وأرقامه المحسوبة، ثم فقرة النتيجة لكل محور، '
        'ويدقّق كل رقم. المحاور:', _NL.join(axes),
        'أجب بـJSON واحد فقط (داخل ```json``` إن شئت)، بلا أي شرح قبله أو بعده.'] if x)


def calc_zero():
    from decimal import Decimal
    return Decimal('0.000')


def write_full(base, data, ask=None, on_progress=None, stop=None, full_reply=None, source='api'):
    """«اكتب البحث» / «إعادة الكتابة»: البحث كاملاً من جديد (الحقائق والحساب والخانات والتركيب والتدقيق)، ثم الدمج في
    التقرير تلقائياً، ثم النتيجة من الكود — لا أزرار دمج ولا «أعد صياغة النتيجة». يرجع حالة خطوة البحث."""
    rp = _rp()
    if ENABLED or full_reply is not None:
        st = run(base, data, ask=ask, on_progress=on_progress, stop=stop, force=True, full_reply=full_reply, source=source)
    else:                                            # المسار القديم (الاختبارات القديمة تطفئ المركَّب)
        st = rp.run(base, data, ask=ask, on_progress=on_progress, stop=stop, force=True)
    rp.merge_all(base, data)
    try:
        store_conclusion(base, data, force=True)
    except cm.StepError:
        pass
    data['research_written'] = True
    cw.write_case_json(base, data)
    return st


def import_full_reply(base, data, text, source='browser'):
    """ردّ الطلب الواحد من المتصفح ← نفس التحقق (الحقائق حرفياً + الخانات + التدقيق) بلا أي طلب، ثم الدمج والنتيجة."""
    st = write_full(base, data, ask=None, full_reply=str(text or ''), source=source)
    r = _rp().state(data)
    return {'accepted': r['v3'].get('model') or [], 'rejected': list((r['v3'].get('rejected') or {}).items()),
            'conclusion': 'من الكود', 'state': st, 'audit': r.get('audit') or {}}


def rewrite_axis(base, data, axis_key, ask=None):
    """«إعادة كتابة هذا البند» (2026-10-25): خانات محور واحد فقط بطلب خانات صغير واحد — الحقائق من المخزّن (بصمة
    المستندات، بلا طلب) — ثم التركيب والتدقيق بالكود، ويُستبدل قسم هذا المحور وحده ويُدمج؛ بقية المحاور المدموجة لا تُمسّ.
    (في المسار المركَّب لكل محور قسم واحد، فـ«البند» = المحور.) يرجع حالة خطوة البحث."""
    import ai_call_log
    import case_facts as cf
    rp = _rp()
    r = rp.state(data)
    v3 = r.get('v3') or {}
    old_axis = next((a for a in r.get('axes') or [] if a['key'] == axis_key), None)
    if old_axis is None:
        raise cm.StepError('المحور غير موجود.')
    ctype = v3.get('ctype') or pb.case_type(data)
    facts = cf.build(base, data, ask=None, case_type=ctype)
    ctx = rc.Ctx(data, facts, ctype)
    if axis_key not in {a['key'] for a in ctx.axes}:
        raise cm.StepError('تغيّرت محاور المأمورية — أعد كتابة البحث كاملاً.')
    only = _slots_of_axes(ctx, {axis_key})
    ai_call_log.detail(f"إعادة كتابة المحور {old_axis['ordinal']} وحده")
    S, log = rc.draft_slots(ctx, ask or default_ask, only=only, prev=dict(v3.get('slots') or {}), attempts=1)
    rep = _compose(ctx, S)
    mine = [e for e in ra.audit(rep, ctx) if f"المحور {old_axis['ordinal']}" in e]
    if mine:                                         # ما فشل في هذا المحور ← جمل الكود الاحتياطية له وحده
        S2 = dict(S, **{sid: rc.fallback(ctx, sid) for sid in only})
        rep2 = _compose(ctx, S2)
        mine2 = [e for e in ra.audit(rep2, ctx) if f"المحور {old_axis['ordinal']}" in e]
        if len(mine2) <= len(mine):
            rep, mine, S = rep2, mine2, S2
            log['fallback'] = sorted(set(log.get('fallback') or []) | only)
    a = next(x for x in rep['axes'] if x['key'] == axis_key)
    sec = dict(old_axis['sections'][0]) if old_axis.get('sections') else {
        'key': f'{axis_key}:v3', 'title': '', 'contract_title': '', 'kind': 'v3', 'contract': None, 'facts': {},
        'allowed': [], 'file': '', 'calc': {}}
    sec['notes'] = [n for n in sec.get('notes') or [] if n['type'] not in (N_AUDIT, rp.N_DEDUP)]
    rp._write_section(base, sec, a['text'])
    sec.update(edited=False, source='v3', drafted_at=rc._now(), stale=False, written_by=None)
    if mine:
        sec.update(state=rp.S_FAILED, progress=0, message='لم يجتز التدقيق: ' + '؛ '.join(ra.plain(e) for e in mine[:2]))
        _note(sec, N_AUDIT, ra.summary_line(mine) + _NL + _NL.join('• ' + ra.plain(e) for e in mine))
    else:
        sec.update(state=rp.S_MERGED, progress=100, message='', merged_at=rc._now())
    old_axis['sections'] = [sec]
    _dedup_notes([old_axis], rep, only={axis_key})
    v3['slots'] = dict(v3.get('slots') or {}, **{sid: S[sid] for sid in only if sid in S})
    concl = {p['axis']: p for p in v3.get('conclusion') or []}
    for p in rep['conclusion']:
        if p['axis'] == axis_key:
            concl[axis_key] = p
    v3['conclusion'] = [concl[x['key']] for x in r['axes'] if x['key'] in concl]
    v3['rejected'] = dict({k: v for k, v in (v3.get('rejected') or {}).items() if k not in only},
                          **(log.get('rejected') or {}))
    r['v3'] = v3
    audit = r.get('audit') or {}
    others = [e for e in audit.get('errors') or [] if f"المحور {old_axis['ordinal']}" not in e]
    r['audit'] = dict(audit, ok=not (others or mine), errors=others + mine, at=rc._now())
    prov, model = ai_call_log.last_provider(), ai_call_log.last_model()
    if prov:
        sec['written_by'] = {'provider': prov, 'model': model}
        data.setdefault('written_by', {})['research'] = {'provider': prov, 'model': model, 'purpose': 'البحث'}
    rp._mark_conclusion_stale(data)
    rp.finish_state(base, data)
    try:
        store_conclusion(base, data)
    except cm.StepError:
        pass
    cw.write_case_json(base, data)
    return cm.state(data, 'research')


def default_ask(prompt):
    import case_research
    return case_research.default_ask(prompt, 'research')


def _note(sec, kind, text):
    if not any(n['type'] == kind and n['text'] == text for n in sec['notes']):
        sec['notes'].append({'type': kind, 'text': text})


def store(base, data, ctx, rep, errs, log):
    import ai_call_log
    rp = _rp()
    r = rp.state(data)
    old = {s['key']: s for a in r.get('axes') or [] for s in a.get('sections') or []}
    failed = bool(errs)
    axes = []
    for a in rep['axes']:
        key = f"{a['key']}:v3"
        prev = old.get(key) or {}
        sec = {'key': key, 'title': '', 'contract_title': '', 'kind': 'v3', 'contract': None, 'notes': [],
               'facts': {'facts': [], 'amounts': [], 'formulas': [], 'objections': []}, 'allowed': [],
               'file': prev.get('file') or '', 'edited': False}
        if a['kind'] == pb.AX_DEBT:
            sec['calc'] = {'steps': [], 'tables': [], 'final': dict(rep['final'], partial=False),
                           'remaining': rep['final']['amount'], 'cur': 'KWD', 'counts': []}
        else:
            sec['calc'] = {'steps': [], 'tables': [], 'final': None, 'remaining': None, 'cur': 'KWD', 'counts': []}
        if prev.get('edited') and prev.get('file') and rp.section_text(base, prev):
            sec.update(state=prev.get('state', rp.S_DRAFTED), edited=True, progress=prev.get('progress', 90),
                       message='عدّله الخبير — لم يُستبدل')
            _note(sec, rp.N_DECISION, 'نص المحور معدَّل يدوياً فلم يُستبدل بالتركيب الجديد — راجعه')
        else:
            rp._write_section(base, sec, a['text'])
            if failed:
                mine = [e for e in errs if f"المحور {a['ordinal']}" in e] or ([] if ra.axes_of_errors(errs, rep) else errs)
                sec.update(state=rp.S_FAILED if mine else rp.S_DRAFTED, progress=0 if mine else rp.PROGRESS[rp.S_DRAFTED],
                           message=('لم يجتز التدقيق: ' + '؛ '.join(ra.plain(e) for e in mine[:2])) if mine else '')
                if mine:                             # سطر واحد يُفتح للتفاصيل
                    _note(sec, N_AUDIT, ra.summary_line(mine) + _NL + _NL.join('• ' + ra.plain(e) for e in mine))
            else:
                sec.update(state=rp.S_DRAFTED, progress=rp.PROGRESS[rp.S_DRAFTED], message='')
        sec.update(source='v3', drafted_at=rc._now(), stale=False)
        axes.append({'key': a['key'], 'ordinal': a['ordinal'], 'kind': _RP_KIND.get(a['kind'], 'عام'), 'v3kind': a['kind'],
                     'title': a['title'], 'point_ids': list(a['point_ids']), 'sections': [sec]})
    if axes:
        tgt = axes[0]['sections'][0]
        for kind, text in (ctx.f.get('notes') or []):
            _note(tgt, kind, text)
        dsec = next((x['sections'][0] for x in axes if x['v3kind'] == pb.AX_DEBT), tgt)
        if not (ctx.f.get('invoices') or []):          # المحسوب صفر لأن الفواتير لم تُستخرج — ليس «فرق أرقام»
            _note(dsec, rp.N_MISSING, 'لم تُستخرج الفواتير من المستندات — راجع قراءة الحوافظ (أعد قراءة الحافظة) '
                                      'ثم أعد كتابة البحث؛ لم يُحسب المتبقي')
        else:
            for c in ctx.L['checks']:                # أي فرق ولو فلساً: «قرارات تحتاج مراجعة» حمراء لا تُخفى
                _note(dsec, rp.N_DECISION, 'فرق أرقام — ' + c['text'])
        for kind, text in ctx.notes:
            _note(tgt, kind, text)
        _dedup_notes(axes, rep)
        for m in ([] if _by_stage2(data, 'subject') else rep.get('subject_missing') or []):
            _note(tgt, rp.N_MISSING, f'الموضوع: لم يرد «{m}» في المستندات المتحقَّقة — حُذف من الجملة')
        for m in rep.get('procedures_missing') or []:
            _note(tgt, rp.N_MISSING, f'الإجراءات: لم يتوفر «{m}» من المحاضر')
        if failed:                                   # سطر واحد يُفتح للتفاصيل بدل ملاحظات كثيرة
            _note(tgt, N_AUDIT, ra.summary_line(errs) + _NL + _NL.join('• ' + ra.plain(e) for e in errs))
    r['axes'] = axes
    r['engine'] = rc.ENGINE
    r['groups'] = []
    r['plan_at'] = rc._now()
    r['audit'] = {'ok': not failed, 'errors': errs, 'attempts': log.get('audit_attempts', 1), 'at': rc._now(),
                  'first_errors': log.get('first_errors') or []}
    prov, model = ai_call_log.last_provider(), ai_call_log.last_model()
    src = log.get('source') or 'api'
    if src.startswith('browser'):                    # «كُتب بواسطة»: عبر المتصفح (الموقع)
        site = src.split(':', 1)[1] if ':' in src else ''
        prov, model = (f'عبر المتصفح ({site})' if site else 'عبر المتصفح'), ''
    r['v3'] = {'ctype': ctx.ctype, 'conclusion': rep['conclusion'], 'final': rep['final'],
               'subject': rep.get('subject') or '', 'procedures': rep['procedures'], 'words': rc.word_count(rep),
               'slots': log.get('slots') or {}, 'fallback': log.get('fallback') or [],
               'rejected': log.get('rejected') or {}, 'model': (log.get('model') or []), 'source': src,
               'written_by': {'provider': prov, 'model': model} if prov else None}
    r['final'] = dict(rep['final'], axis=next((x['key'] for x in axes if x['v3kind'] == pb.AX_DEBT), None))
    _apply_subject(data, rep)
    _apply_procedures(data, rep)
    if prov:
        data.setdefault('written_by', {})['research'] = {'provider': prov, 'model': model, 'purpose': 'البحث'}
        ctx.f['model'] = {'provider': prov, 'model': model}
    rp.finish_state(base, data)
    if failed:
        data['steps']['research']['message'] = f'{N_AUDIT}: ' + '؛ '.join(ra.plain(e) for e in errs[:3])
    cw.write_case_json(base, data)
    try:
        import case_memory
        case_memory.update_section(base, data, 'case', 'status')
    except Exception:
        pass


def _dedup_notes(axes, rep, only=None):
    """«حُذف تكرار» لكل جملة حذفها الكود (rep['dedup']) في قسم محورها (أو أول محور للموضوع/الإجراءات)."""
    rp = _rp()
    for where, sent in rep.get('dedup') or []:
        tgt = next((x for x in axes if f"المحور {x['ordinal']}" == where), None)
        if tgt is None and only is None:
            tgt = axes[0] if axes else None
        if tgt is not None and (only is None or tgt['key'] in only):
            _note(tgt['sections'][0], rp.N_DEDUP, f'حُذف تكرار ({where}): «{sent[:90]}{"…" if len(sent) > 90 else ""}»')


def _by_stage2(data, key):
    """النص كتبته المرحلة الثانية (طلب الموضوع والإجراءات) ← البحث لا يستبدله بتركيب الكود."""
    return ((data.get('autowrite') or {}).get(key) or {}).get('source') == 'stage2' and bool((data.get('stage2') or {}).get('at'))


def _apply_subject(data, rep):
    if not rep.get('subject') or data.get('subject_edited') or _by_stage2(data, 'subject'):
        return
    if (data.get('subject') or '').strip() != rep['subject']:
        data['subject_prev'] = data.get('subject') or ''
        data['subject'] = rep['subject']
        data['subject_source'] = 'v3'
    data['subject_missing'] = list(rep.get('subject_missing') or [])


def _apply_procedures(data, rep):
    proc = data.setdefault('procedures', {})
    if proc.get('edited') or not rep.get('procedures') or proc.get('source') in ('stage2', 'code') and             (data.get('stage2') or {}).get('at'):
        return
    if (proc.get('text') or '').strip() != rep['procedures']:
        proc['text_prev'] = proc.get('text') or ''
        proc['text'] = rep['procedures']
        proc['auto_text'] = rep['procedures']
        proc['source'] = 'v3'


# ---------- النتيجة (من الكود عند الدمج) ----------

def store_conclusion(base, data, force=False):
    """فقرات النتيجة المبنية بالكود للمحاور المكتملة (المدموجة) — بديل توليد النموذج. يرجع حالة الخطوة."""
    import conclusion_pipeline as cp2
    rp = _rp()
    axes = cp2.complete_axes(base, data)
    if not axes:
        raise cm.StepError('لا محور مكتمل في البحث بعد — ادمج أقسام محور واحد على الأقل.')
    old = cp2.record(data)
    if old and old.get('edited') and not force:
        return cm.state(data, 'conclusion')
    paras = {p['axis']: p for p in (rp.state(data).get('v3') or {}).get('conclusion') or []}
    done = [(a, t) for a, t in axes if a['key'] in paras]
    out = [{'axis': a['key'], 'ordinal': a['ordinal'], 'text': paras[a['key']]['text']} for a, _t in done]
    notes = cp2._missing_notes(base, data)
    cp2._store(base, data, out, done, 'code', notes, cp2.current_sha(base, data))
    return cm.state(data, 'conclusion')


# ---------- التسليم بملف/Copilot: طلب الخانات وحده ----------

def export_prompt(base, data, ask=None, delivery='file'):
    """prompt.md: طلب الخانات القصيرة (لا أرقام) لنموذج الخبير؛ الرد JSON يُستورد بـimport_reply."""
    import case_documents as cd
    import case_facts as cf
    ctype = pb.case_type(data)
    try:
        facts = cf.build(base, data, ask=ask, case_type=ctype)
    except Exception:
        facts = cf.build(base, data, ask=None, case_type=ctype)
    ctx = rc.Ctx(data, facts, ctype)
    text = (f"# طلب خانات «البحث ورأي الخبرة» — القضية {data.get('caso_no', '')}\n\n"
            f"انسخ ردّك كاملاً (JSON) تحت السطر {PROMPT_MARK} عند الاستيراد، أو الصقه كما هو.\n\n"
            + rc.slots_prompt(ctx, rc.slot_specs(ctx)) + '\n')
    cd._write_md(base, _rp().PROMPT_REL, text)
    _rp().state(data).update(delivery=delivery, exported_at=rc._now())
    cw.write_case_json(base, data)
    import os
    return os.path.join(base, _rp().PROMPT_REL)


def import_reply(base, data, text, source='file'):
    """ردّ JSON للخانات من ملف/Copilot ← الفحص نفسه ← التركيب ← التدقيق ← الحفظ."""
    import case_facts as cf
    raw = str(text or '').split(PROMPT_MARK)[-1]
    obj = cf._parse_json(raw)
    if not obj:
        raise cm.StepError('لم أجد JSON للخانات في الرد ({"slots": {...}}).')
    slots = obj.get('slots') if isinstance(obj.get('slots'), dict) else obj
    st = run(base, data, ask=None, slots=slots)
    r = _rp().state(data)
    r['v3']['source'] = source
    cw.write_case_json(base, data)
    return {'accepted': r['v3'].get('model') or [], 'rejected': list((r['v3'].get('rejected') or {}).items()),
            'conclusion': 'من الكود', 'state': st}


def audit_line(data):
    """سطر أحمر للواجهة إن فشل التدقيق، وإلا ''."""
    a = _rp().state(data).get('audit') or {}
    if not is_v3(data) or a.get('ok', True):
        return ''
    return f"{N_AUDIT} — لا يُعتمد هذا النص قبل معالجة الأسباب:\n" + '\n'.join(f"• {ra.plain(e)}" for e in a.get('errors') or [])
