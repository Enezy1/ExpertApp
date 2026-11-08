# ===== case_conclusion.py — خطوة «النتيجة» (المرحلة 2م) =====
# ردّ مباشر على كل نقطة من نقاط المأمورية، مأخوذ من نص البند المكتوب لها في خطوة البحث (طلب لكل نقطة).
# لا تبدأ قبل اكتمال كل البنود، أو قبل تنازل الخبير صراحةً عن الناقص منها (waive_research)؛
# والنقطة التي لا بند لها تأخذ ردّاً ثابتاً «لم يُبحث» بلا استدعاء للمزوّد.
# الإجابات مفتاحها معرّف النقطة؛ كل إجابة تحمل بصمة نص البند الذي أُخذت منه، فإذا تغيّر البند أو نص النقطة
# أُعيدت كتابتها وحدها عند التشغيل التالي (والباقي يُترك). الخرج: case.json['conclusion']['answers'] و04_تقرير/النتيجة.md
# والثابت: عدد الإجابات = عدد النقاط بالمعرّفات نفسها وبالترتيب (verify_counts).
import hashlib
import os

import case_documents
import case_memory
import case_model as cm
import case_research
import case_workspace as cw

REL = os.path.join('_نظام', '04_تقرير', 'النتيجة.md').replace('\\', '/')
MISSING_TEXT = 'لم يُبحث هذا البند — تعذّر الجزم فيه.'


def missing_points(data):
    """نقاط المأمورية التي لا بند مكتوباً (done/reviewed) لها."""
    ok = {i['id'] for i in data['research'] if i['state'] in cm.OK_STATES}
    return [p for p in data['mission'].get('points') or [] if p['id'] not in ok]


def is_v2(data):
    """قضية بالبحث الجديد (محاور × عقود، research_pipeline) ← النتيجة من conclusion_pipeline."""
    return bool((data.get('research2') or {}).get('axes'))


def verify_counts(data):
    """True إن تطابقت الإجابات مع النقاط عدداً ومعرّفاً وترتيباً (وفي البحث الجديد: فقرة لكل محور مكتمل)."""
    rec = (data.get('conclusion') or {}).get('v2')
    if is_v2(data) and rec:
        return len(rec.get('paragraphs') or []) == len(rec.get('axes') or [])
    pts = [p['id'] for p in data['mission'].get('points') or []]
    ans = [a['id'] for a in (data.get('conclusion') or {}).get('answers') or []]
    return pts == ans


def waive_research(base, data, waived=True):
    """متابعة الخبير إلى النتيجة رغم نقص بنود البحث."""
    data['steps']['research']['waived'] = bool(waived)
    cm.refresh_blocked(data)
    cw.write_case_json(base, data)


def render_md(data):
    pts = data['mission'].get('points') or []
    by_id = {a['id']: a for a in data['conclusion'].get('answers') or []}
    out = ['# النتيجة', '']
    for p in pts:
        a = by_id.get(p['id'])
        out += [f"## النقطة {p['n']}: {p['text']}", '', (a['text'] if a else '_لم تُكتب بعد._'), '']
    return '\n'.join(out).rstrip('\n') + '\n' if pts else '# النتيجة\n\n_لا نقاط مأمورية._\n'


def _item_text(base, data, pid):
    it = next((i for i in data['research'] if i['id'] == pid and i['state'] in cm.OK_STATES), None)
    if it is None:
        return None, ''
    raw, _ = case_memory._read_text(base, it.get('file'))
    if raw is None:
        return None, ''
    return case_memory._dec(raw), hashlib.sha1(raw).hexdigest()


def _prompt(data, point, text):
    return ("اكتب «النتيجة» لتقرير خبرة قضائي: ردّاً مباشراً ومحدداً على النقطة التالية من المأمورية، "
            "في فقرة أو فقرتين بصيغة الجزم المهني (ما انتهت إليه الخبرة)، دون إعادة سرد الأسباب. "
            "اعتمد على نص البند فقط ولا تضف معلومة غير واردة فيه، وأبقِ إحالات المستندات كما وردت.\n\n"
            f"## موضوع القضية\n{data.get('subject') or '—'}\n\n"
            f"## النقطة (رقم {point['n']})\n{point['text']}\n\n"
            f"## نص البند المكتوب لها\n{text}")


def _save(base, data):
    c = data['conclusion']
    c['file'] = REL
    case_documents._write_md(base, REL, render_md(data))
    cw.write_case_json(base, data)
    try:
        case_memory.update_section(base, data, 'status', 'conclusion')
    except Exception:
        pass       # الذاكرة مشتقة: فشلها لا يُفشل الخطوة


def run_conclusion(base, data, ask=None, force=False):
    """يكتب إجابات النقاط الناقصة/القديمة. يرجع حالة الخطوة.
    يرفع cm.StepError إن لم يكتمل البحث (أو لم يتنازل الخبير) أو لم توجد نقاط."""
    if is_v2(data):                                   # البحث الجديد: فقرة لكل محور من نص البحث المدموج وأرقامه فقط
        import conclusion_pipeline
        return conclusion_pipeline.generate(base, data, ask=ask, force=force)
    ask = ask or case_research.default_ask
    rec = data['steps']['conclusion']
    if rec['state'] in cm.OK_STATES and not rec.get('stale') and not force:
        return rec['state']
    pts = data['mission'].get('points') or []
    if not pts:
        raise cm.StepError('لا توجد نقاط مأمورية.')
    miss = missing_points(data)
    if miss and not data['steps']['research'].get('waived'):
        raise cm.StepError('بنود البحث غير مكتملة: ' + '، '.join(str(p['n']) for p in miss)
                           + ' — أكملها أو تابع بموافقتك (waive_research).')
    cm.set_step(data, 'conclusion', 'running')
    c = data['conclusion']
    old = {a['id']: a for a in c.get('answers') or []}
    answers, failed = [], []
    for idx, p in enumerate(pts):
        text, sha = _item_text(base, data, p['id'])
        prev = old.get(p['id'])
        if text is None:                                      # لا بند ← ردّ ثابت
            answers.append({'id': p['id'], 'n': p['n'], 'point_text': p['text'], 'text': MISSING_TEXT,
                            'source_sha1': '', 'missing': True})
            continue
        if (prev and not prev.get('missing') and prev.get('source_sha1') == sha
                and prev.get('point_text') == p['text'] and not force):
            answers.append(dict(prev, n=p['n']))
            continue
        try:
            import research_pipeline as _rp
            reply = _rp.strip_internal(ask(_prompt(data, p, text)) or '').strip()
            if not reply:
                raise RuntimeError('ردّ المزوّد فارغ')
        except Exception as e:
            failed.append((p['n'], str(e) or e.__class__.__name__))
            if prev:                                          # القديم يبقى بدل الفراغ
                answers.append(dict(prev, n=p['n'], stale=True))
            continue
        answers.append({'id': p['id'], 'n': p['n'], 'point_text': p['text'], 'text': reply,
                        'source_sha1': sha, 'missing': False})
        c['answers'] = answers + [old[q['id']] for q in pts[idx + 1:] if q['id'] in old]
        _save(base, data)                                    # تقدّم محفوظ بعد كل ردّ
    c['answers'] = answers
    if failed:
        # الإجابات الفاشلة ناقصة من القائمة؛ التطابق يُستعاد بعد إعادة المحاولة
        cm.set_step(data, 'conclusion', 'failed',
                    'فشلت النقاط: ' + '؛ '.join(f'{n} ({m})' for n, m in failed))
        c['state'] = 'failed'
        _save(base, data)
        return 'failed'
    if not verify_counts(data):
        cm.set_step(data, 'conclusion', 'failed', 'عدد الإجابات لا يطابق عدد النقاط')
        c['state'] = 'failed'
        _save(base, data)
        return 'failed'
    n_missing = sum(1 for a in answers if a.get('missing'))
    note = f' ({n_missing} نقطة بلا بند)' if n_missing else ''
    cm.set_step(data, 'conclusion', 'done', f'{len(answers)} ردّاً على {len(pts)} نقطة{note}')
    c['state'] = 'done'
    _save(base, data)
    return 'done'


def review_conclusion(base, data):
    if is_v2(data) and (data.get('conclusion') or {}).get('v2'):
        if cm.state(data, 'conclusion') != 'done':
            raise cm.StepError('لا يمكن مراجعة نتيجة غير مكتملة.')
        cm.set_step(data, 'conclusion', 'reviewed')
        data['conclusion']['state'] = 'reviewed'
        cw.write_case_json(base, data)
        return
    if cm.state(data, 'conclusion') != 'done' or not verify_counts(data):
        raise cm.StepError('لا يمكن مراجعة نتيجة غير مكتملة.')
    cm.set_step(data, 'conclusion', 'reviewed')
    data['conclusion']['state'] = 'reviewed'
    cw.write_case_json(base, data)
