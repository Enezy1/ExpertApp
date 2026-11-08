# ===== case_questions.py — «الأسئلة المهمة» بالذكاء الاصطناعي (2026-10-17) =====
# تبدأ من نقاط المأمورية في حكم الإحالة (مثلاً: طلب العقد المبرم بين الطرفين لبيان طبيعة العلاقة) ثم ما ينقص بحسب فحص
# الجاهزية، وتنقسم إلى قائمتين: «مهام الخبير» (مطالعة ملف الدعوى، الانتقال، معاينة…) و«طلبات للخصوم» (من يُكلَّف + المطلوب).
# الصياغة سطر موجز: «تكليف المدعية بتقديم …» بلا سبب ولا بند طويل. لا يُطلب من الخصوم ملف الدعوى الأصلي ولا ما يطالعه
# الخبير بنفسه (يُرشَّح بالكود أيضاً). السجلات في case.json['questions'] (kind: expert|party، auto/ai، status open/closed)،
# وما ربطه النموذج بمتطلب من فحص الجاهزية يأخذ معرّفه فيُغلق آلياً حين يُسدّ بمستند (case_readiness.sync_questions).
# الإضافة اليدوية تبقى؛ والأصل التوليد التلقائي. المزوّد: مهمة «صياغة التقرير» ويُسجَّل «كُتب بواسطة».
import hashlib
import re
from datetime import datetime

import case_readiness as cr
import case_subject_telecom as st

EXPERT, PARTY = 'expert', 'party'
# ما لا يُطلب من الخصوم: ملف الدعوى الأصلي وما يطالعه الخبير بنفسه
FORBIDDEN_FOR_PARTIES = re.compile(r'ملف\s+(?:ال)?دعوى|أوراق\s+(?:ال)?دعوى|ملف\s+القضية|الدعوى\s+الأصلي|الأصل\s+ملف|'
                                   r'صحيفة\s+(?:ال)?دعوى|الحكم\s+التمهيدي|حكم\s+الإحالة|مطالعة|الاطلاع\s+على\s+(?:ال)?ملف')
_CUT = re.compile(r'\s*(?:[،؛,;]\s*)?(?:وذلك|إذ|لأن|حيث إن|بسبب)\b.*$')
_TO = ('المدعية', 'المدعى عليه', 'المدعى عليها', 'المدعى عليهم', 'الطرفين', 'الطرفان', 'الخصوم')


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def concise(text):
    """سطر موجز: يحذف التعليل («وذلك…/إذ…») ويبقي المطلوب وحده، بحد أقصى ~160 حرفاً."""
    t = re.sub(r'\s+', ' ', st._clean(text)).strip().rstrip('.،؛ ')
    t = _CUT.sub('', t).strip()
    if len(t) > 160:
        t = t[:160].rsplit(' ', 1)[0]
    return t


def build_prompt(data, needs):
    """needs: [{'key','need','to','point_id','n'}] المتطلبات الناقصة من فحص الجاهزية (قد تكون فارغة)."""
    m = data.get('mission') or {}
    pts = '\n'.join(f"{p['n']}) {p['text']}" for p in m.get('points') or []) or (m.get('raw') or '—')
    docs = []
    for p in data.get('portfolios') or []:
        for d in p.get('docs') or []:
            docs.append(f"- {p['id']}-{d['no']}: {d.get('type') or d.get('doc_type') or 'مستند'} — مقدَّم من {p.get('submitter') or '؟'}")
    parties = {'المدعية': (data.get('case') or {}).get('plaintiff') or (data.get('case') or {}).get('company') or '',
               'المدعى عليهم': (data.get('case') or {}).get('defendants') or []}
    return (
        "أنت خبير قضائي تُعدّ «الأسئلة المهمة» قبل كتابة البحث ورأي الخبرة. ابدأ من نقاط المأمورية الواردة في حكم الإحالة "
        "(مثلاً: طلب العقد المبرم بين الطرفين لبيان طبيعة العلاقة)، ثم أضف ما ينقص بحسب فحص الجاهزية. قسّمها قائمتين:\n"
        "1) expert_tasks: مهام الخبير نفسه (مطالعة ملف الدعوى، الانتقال، المعاينة، الاستعانة بمحاسب…).\n"
        "2) party_requests: طلبات للخصوم، لكل طلب: to (المدعية أو المدعى عليه أو المدعى عليهم أو الطرفين) وtext.\n"
        "الصياغة: سطر موجز واحد للطلب مثل «تكليف المدعية بتقديم العقد المبرم بين الطرفين» دون ذكر سبب أو بند طويل. "
        "لكشف الحساب: «تكليف المدعية بتقديم كشف الحساب وإيصالات السداد وبيان كيفية احتساب المبلغ المطالب به». "
        "ممنوع أن تطلب من الخصوم ملف الدعوى الأصلي أو أوراقها أو ما يطالعه الخبير بنفسه (يدخل في مهام الخبير). "
        "لا تطلب مستنداً موجوداً أصلاً في «المستندات المرفقة». لا تكرر.\n"
        'أجب بـ JSON فقط: {"expert_tasks":[{"text":"","point":1}],"party_requests":[{"to":"","text":"","point":1,"key":""}]}\n'
        "point رقم النقطة المرتبطة إن وُجدت؛ key يُنسخ من «النواقص» أدناه إن كان الطلب يسدّ أحدها وإلا اتركه فارغاً.\n\n"
        f"## موضوع القضية\n{data.get('subject') or '—'}\n\n## نقاط المأمورية\n{pts}\n\n"
        "## المستندات المرفقة\n" + ('\n'.join(docs) or '— لا شيء') + "\n\n## الأطراف\n"
        f"{parties}\n\n## النواقص من فحص الجاهزية\n"
        + ('\n'.join(f"- key={n['key']} | نقطة {n['n']} | من {n['to']}: {n['need']}" for n in needs) or '— لا يوجد فحص بعد'))


def open_needs(data):
    """المتطلبات الناقصة من آخر فحص جاهزية."""
    out = []
    for res in (data.get('readiness') or {}).get('items') or []:
        for r in res.get('requirements') or []:
            if not r.get('found'):
                out.append({'key': r['key'], 'need': r['need'], 'to': r['to'], 'point_id': res['id'], 'n': res['n']})
    return out


def _qid_ai(kind, to, text):
    return 'q_' + hashlib.sha1(f'{kind}|{to}|{text}'.encode('utf-8')).hexdigest()[:10]


def parse(data, obj, needs):
    """سجلات الأسئلة من ردّ النموذج بعد التنظيف: إيجاز، ترشيح الممنوع، ربط النقاط والمتطلبات."""
    pid_by_n = {p['n']: p['id'] for p in (data.get('mission') or {}).get('points') or []}
    by_key = {n['key']: n for n in needs}
    out, seen = [], set()

    def point(v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None, None
        return pid_by_n.get(n), n
    for t in obj.get('expert_tasks') or []:
        text = concise(t.get('text') if isinstance(t, dict) else t)
        if not text or ('E', text) in seen:
            continue
        seen.add(('E', text))
        pid, n = point(t.get('point') if isinstance(t, dict) else None)
        out.append({'id': _qid_ai(EXPERT, '', text), 'kind': EXPERT, 'to': 'الخبير', 'text': text, 'point_id': pid,
                    'point_n': n, 'status': 'open', 'auto': True, 'ai': True, 'at': _now()})
    for r in obj.get('party_requests') or []:
        if not isinstance(r, dict):
            continue
        text = concise(r.get('text'))
        to = st._clean(r.get('to')) or 'الطرفين'
        to = next((x for x in _TO if x in to), 'الطرفين')
        if not text or FORBIDDEN_FOR_PARTIES.search(text) or ('P', to, text) in seen:
            continue
        seen.add(('P', to, text))
        if not text.startswith('تكليف'):
            text = f'تكليف {to} بتقديم {text}'
        need = by_key.get(st._clean(r.get('key')))
        if need:
            qid, pid, n = cr._qid(need['point_id'], need['key']), need['point_id'], need['n']
        else:
            pid, n = point(r.get('point'))
            qid = _qid_ai(PARTY, to, text)
        rec = {'id': qid, 'kind': PARTY, 'to': to, 'text': text, 'point_id': pid, 'point_n': n,
               'status': 'open', 'auto': True, 'ai': True, 'at': _now()}
        if need:
            rec.update(need=need['need'], why='')
        out.append(rec)
    return out


def merge(data, new):
    """يدمج المولَّد: المُغلق يبقى، والمفتوح المولَّد سابقاً ولم يعد مقترحاً يُحذف، واليدوي لا يُمسّ.
    يرجع (أُضيف، أُزيل) بالمعرّفات."""
    qs = cr.normalize_questions(data)
    by_id = {q['id']: q for q in qs}
    added, removed = [], []
    new_ids = {q['id'] for q in new}
    keep = []
    for q in qs:
        if q.get('ai') and q.get('status') == 'open' and q['id'] not in new_ids:
            removed.append(q['id'])
            continue
        keep.append(q)
    qs[:] = keep
    by_id = {q['id']: q for q in qs}
    for q in new:
        old = by_id.get(q['id'])
        if old is None:
            qs.append(q)
            added.append(q['id'])
        else:
            old.update(kind=q['kind'], to=q['to'], text=q['text'], ai=True)      # نص موجز محدَّث؛ الحالة تبقى
            if q.get('point_n'):
                old['point_n'] = q['point_n']
    return added, removed


def generate(base, data, ask):
    """يستدعي الذكاء ويدمج الأسئلة ويحفظ case.json ويسجّل «كُتب بواسطة». يرفع الخطأ كما هو (المزوّد/JSON)."""
    import ai_call_log
    import case_workspace as cw
    if not (data.get('mission') or {}).get('points') and not (data.get('mission') or {}).get('raw'):
        raise cr.cm.StepError('لا نقاط مأمورية بعد — اقرأ حكم الإحالة أولاً.')
    needs = open_needs(data)
    obj = st.parse_response(ask(build_prompt(data, needs)))
    new = parse(data, obj, needs)
    ai_call_log.verdict(True, f'{len(new)} سؤالاً بعد التحقق')
    added, removed = merge(data, new)
    prov = ai_call_log.last_provider()
    if prov:
        data.setdefault('written_by', {})['questions'] = {'provider': prov, 'model': ai_call_log.last_model(),
                                                          'purpose': 'الأسئلة المهمة'}
    data['questions_generated_at'] = _now()
    cw.write_case_json(base, data)
    return {'added': added, 'removed': removed, 'total': len(new)}


def split(data):
    """(مهام الخبير، طلبات الخصوم): كل قائمة مرتبة؛ اليدوي بلا kind يُعدّ طلباً للخصوم."""
    qs = cr.normalize_questions(data)
    return ([q for q in qs if q.get('kind') == EXPERT],
            [q for q in qs if q.get('kind') != EXPERT])


def status_text(q):
    return 'مغلق ✓' if q.get('status') == 'closed' else 'مفتوح'


def table_html(title, rows, empty):
    head = ("<tr><th>م</th><th>الموجَّه إليه</th><th>المطلوب</th><th>البند</th><th>الحالة</th></tr>")
    body = ''.join(
        f"<tr><td>{i}</td><td>{q.get('to') or '—'}</td><td>{q['text']}</td><td>{q.get('point_n') or '—'}</td>"
        f"<td>{status_text(q)}</td></tr>" for i, q in enumerate(rows, 1))
    if not rows:
        body = f"<tr><td colspan='5'>{empty}</td></tr>"
    return (f"<h3>{title}</h3><table border='1' cellspacing='0' cellpadding='5' width='100%' "
            f"style='border-collapse:collapse'>{head}{body}</table>")


def questions_html(data):
    """للطباعة: الجدولان نفسهما (المفتوح والمغلق) بالأعمدة نفسها."""
    experts, parties = split(data)
    return (f"<html dir='rtl'><body style='font-family:Tahoma; font-size:12pt'>"
            f"<h2>الأسئلة المهمة — القضية {data.get('caso_no', '')}</h2>"
            + table_html('مهام الخبير', experts, 'لا مهام للخبير.')
            + table_html('طلبات للخصوم', parties, 'لا طلبات للخصوم.') + "</body></html>")
