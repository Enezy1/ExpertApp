# ===== report_docx.py — إصدار تقرير الخبرة Word من case.json (المرحلة 2ج) =====
# يبني التقرير بالشكل المعتمد عبر report_builder.py (الترويسة والخط والهوامش كما هي، لا تُعدَّل) من:
#   الموضوع ← subject، المأمورية ← mission.raw حرفياً، الإجراءات ← محاضر الجلسات (sessions.minutes)،
#   البحث ← نصوص البنود، النتيجة ← ردود النقاط، المرفقات ← attachments.
# لا استنتاج: أي بيان غير متوافر (الواردة من، القسم، اسم الخبير…) يُكتب «..........» ويُذكر في warnings
# ليكمله الخبير في Word. لا يكتب فوق ملف موجود (قد يكون الخبير عدّله): يُنشأ «التقرير (2).docx» وهكذا.
# يعمل في أي مرحلة (2026-10-17): يولّد ما هو متوفر، والناقص يُكتب «[يُكتب]» ليكمله الخبير في Word.
# كل إصدار ملف جديد: التقرير_v1.docx ثم _v2 … والسابق يبقى كما هو. المعاينة/سماع الشهود تُترك للخبير.
import base64
import hashlib
import os
import re
import sys
from datetime import datetime

import case_conclusion
import case_model as cm
import case_workspace as cw

BLANK = '..........'
TODO = '[يُكتب]'
OUT_REL = 'التقرير/التقرير.docx'          # مخرجات التقرير في التقرير/ (البنية المختصرة 2026-10-21)


def assets_dir():
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'report_assets')


def _b64(name):
    with open(os.path.join(assets_dir(), name), 'rb') as f:
        return base64.b64encode(f.read())


# ---------- Markdown → كتل ----------
_HTML_COMMENT = re.compile(r'<!--.*?-->', re.S)
_BULLET = re.compile(r'^\s*(?:[-*•·▪◦‣∙●○–—]\s*)+(.*\S.*)')
_NUMBERED = re.compile(r'^\s*\d{1,2}[.)\-]\s+(.*)')
_HEADING = re.compile(r'^\s*#{1,6}\s+(.*)')


def _inline(s):
    return s.replace('`', '').replace('\\|', '|').strip()


def md_blocks(text):
    """كتل: ('p', نص) ('sub', نص) ('bullets', [..]) ('numbered', [..]) ('table', [[..]]). بلا تعليقات HTML."""
    text = _HTML_COMMENT.sub('', text or '')
    blocks, para, lines = [], [], text.splitlines()

    def flush():
        if para:
            blocks.append(('p', _inline(' '.join(para))))
            para.clear()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            flush()
        elif _HEADING.match(ln):
            flush()
            blocks.append(('sub', _inline(_HEADING.match(ln).group(1))))
        elif ln.lstrip().startswith('|'):
            flush()
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith('|'):
                cells = [_inline(c) for c in re.split(r'(?<!\\)\|', lines[i].strip().strip('|'))]
                if not all(re.fullmatch(r':?-{2,}:?', c) for c in cells if c):
                    rows.append(cells)
                i += 1
            blocks.append(('table', rows))
            continue
        elif _BULLET.match(ln) or _NUMBERED.match(ln):
            flush()
            rx = _BULLET if _BULLET.match(ln) else _NUMBERED
            items = []
            while i < len(lines) and rx.match(lines[i]):
                items.append(_inline(rx.match(lines[i]).group(1)))
                i += 1
            blocks.append(('bullets' if rx is _BULLET else 'numbered', items))
            continue
        else:
            para.append(ln.strip())
        i += 1
    flush()
    return [b for b in blocks if b[1]]


def _emit(r, blocks):
    for kind, val in blocks:
        if kind == 'p':
            r.text(val)
        elif kind == 'sub':
            r.subheading(val if val.endswith(':') else val + ':')
        elif kind == 'bullets':
            r.bullets(val)
        elif kind == 'numbered':
            r.numbered(val)
        elif kind == 'table' and val:
            n = max(len(row) for row in val)
            rows = [row + [''] * (n - len(row)) for row in val]
            w = 9736 // n
            r.data_table(rows[0], rows[1:], [w] * n)


# ---------- التجميع ----------

def gather_info(data, cookies=None, current_user=''):
    """بيانات الجدول الأول بنفس مصدر المحضر (case_header): الأطراف ورقم الدعوى من بيانات القضية المحفوظة ثم النظام،
    والخبراء من سجل الحركة (get_experts) — لا اسم المستخدم الداخل. لا يرفع استثناءً."""
    try:
        import case_header
        import current_expert
        user = current_user or current_expert.get_current_user()
        if user == 'default':
            user = ''
        h = case_header.fetch_header(cookies, user, data['caso_no'])
        info = dict(h['info'])
        info.update(plaintiffs=h['plaintiffs'], defendants=h['defendants'],
                    court_case_number=h['court_case_number'], experts=[('الخبير', n) for n in h['names']])
        return info
    except Exception:
        return {}


def resolve_header(info, data, settings=None):
    """(kwargs لترويسة التقرير، تحذيرات): المحافظة والقسم بالأولوية: نظام الخبراء (info) ← بيانات القضية المحفوظة
    ← إعدادات الخبير. لا إدخال يدوي في التقرير؛ وإن لم يتوفر شيء تبقى القيمة المعتمدة مع تحذير."""
    if settings is None:
        try:
            import expert_settings
            settings = expert_settings.load_report_header()
        except Exception:
            settings = {}
    c = (data or {}).get('case') or {}
    kw, warns = {}, []
    for key, label, default in (('governorate', 'المحافظة', 'العاصمة'), ('department', 'القسم', None)):
        val = (info.get(key) or c.get(key) or settings.get(key) or '').strip()
        if val:
            kw[key] = val
        else:
            warns.append(f'{label}: استُخدمت القيمة المعتمدة' + (f' «{default}»' if default else '')
                         + ' — تحقق منها أو اضبطها من الإعدادات.')
    return kw, warns


def remember_header(info):
    """يحفظ المحافظة/القسم القادمين من النظام في إعدادات الخبير إن كانت فارغة (لا يكتب فوق ما ضبطه الخبير)."""
    try:
        import expert_settings
        cur = expert_settings.load_report_header()
        new = {k: cur.get(k) or (info.get(k) or '').strip() for k in ('governorate', 'department')}
        if new != cur:
            expert_settings.save_report_header(**new)
            return True
    except Exception:
        pass
    return False


def _unique_path(base, rel):
    """التقرير_v1.docx ثم _v2 … لا يكتب فوق شيء. يرجع (المسار، رقم النسخة)."""
    root, ext = os.path.splitext(os.path.join(base, rel))
    n = 1
    while os.path.exists(f'{root}_v{n}{ext}'):
        n += 1
    return f'{root}_v{n}{ext}', n


def check_ready(data):
    """لم يعد شرطاً للإصدار؛ تبقى للتوافق وترجع نصاً بما ينقص ('' إن اكتملت النتيجة)."""
    if cm.state(data, 'conclusion') not in cm.OK_STATES:
        return 'النتيجة لم تُكتب بعد.'
    if not case_conclusion.verify_counts(data):
        return 'عدد ردود النتيجة لا يطابق نقاط المأمورية.'
    return ''


def build_report(base, data, info=None, today=None):
    """يرجع (المسار، warnings). info: بيانات الجدول الأول (انظر gather_info) وقد تحوي experts=[(لقب، اسم)]."""
    import report_builder as rb
    info = info or {}
    warns = []
    c = data.get('case') or {}

    def need(val, what, mark=BLANK):
        val = (val or '').strip() if isinstance(val, str) else val
        if not val:
            warns.append(f'لم يتوفر «{what}» — تُرك فارغاً ليكمله الخبير.')
            return mark
        return val

    plaintiffs = info.get('plaintiffs') or [p for p in [c.get('plaintiff') or c.get('company')] if p]
    defendants = info.get('defendants') or c.get('defendants') or []
    experts = info.get('experts')
    if not experts:
        name = (info.get('expert_name') or '').strip()
        experts = [('الخبير', name or BLANK)]
        warns.append('لقب الخبير واسمه: تحقق منهما في التوقيع والجدول الأول.' if name
                     else 'لم يتوفر اسم الخبير — تُرك فارغاً ليكمله الخبير.')
    kw, hwarns = resolve_header(info, data)
    warns += hwarns
    court_no = info.get('court_case_number') or info.get('case_num') or ''      # كالمحضر: بيانات القضية ثم النظام
    if not court_no:
        import referral_pick                 # احتياط: من نص حكم الإحالة
        court_no = referral_pick.case_number(base, data) or c.get('court_case_number') or ''

    rb.load_images(_b64('emblem.jpg'), _b64('badge.jpg'))
    r = rb.Report()
    date = today or datetime.now().strftime('%d/%m/%Y')
    r.info_table(date, data['caso_no'],
                 need(court_no or info.get('court_case_number') or info.get('case_num') or data.get('claim_no'), 'رقم الدعوى'),
                 need(info.get('source'), 'الواردة من'),
                 plaintiffs or [BLANK], defendants or [BLANK], [e[1] for e in experts], **kw)
    r.title()
    r.heading('الموضوع:')
    r.text(need(data.get('subject'), 'الموضوع', TODO))
    r.heading('المأمورية:')
    r.text(need((data.get('mission') or {}).get('raw'), 'المأمورية', TODO))
    minutes = sorted((data.get('sessions') or {}).get('minutes') or [], key=lambda m: (m.get('no') is None, m.get('no') or 0))
    proc_text = ((data.get('procedures') or {}).get('text') or '').strip()
    r.heading('الإجراءات:')
    if proc_text:                       # نص الخطوة (قالب تقرير النموذج أو تعديل الخبير)
        r.text(proc_text)
        if TODO in proc_text:
            warns.append('الإجراءات: بقي «[يُكتب]» في النص — أكمله في Word.')
    elif minutes:
        r.text('باشرت الخبرة المأمورية وعقدت الجلسات التالية:')
        r.bullets([f"الجلسة رقم {m['no']}" + (f" بتاريخ {m['date']}" if m.get('date') else '') for m in minutes])
    else:
        r.text(TODO)
        warns.append('لا محاضر مسجّلة: قسم الإجراءات يحمل «[يُكتب]».')
    r.heading('البحث ورأي الخبرة:')
    if case_conclusion.is_v2(data):
        _emit_research_v2(r, base, data, warns)
    else:
        items = data.get('research') or []
        if not items:
            r.text(TODO)
            warns.append('لم يُكتب أي بند بحث: القسم يحمل «[يُكتب]».')
        for it in items:
            if it['state'] not in cm.OK_STATES:
                warns.append(f"البند {it['n']} غير مكتوب — وُضعت علامة «[يُكتب]» مكانه.")
                r.subheading(f"{it['n']}) {it.get('point_text') or ''}:")
                r.text(TODO)
                continue
            r.subheading(f"{it['n']}) {it.get('point_text') or ''}:")
            raw, _ = _read(base, it.get('file'))
            _emit(r, md_blocks(_clean(raw)))
    r.heading('النتيجة:', page_break_before=True)
    _emit_conclusion(r, base, data, warns)
    r.heading('المرفقات:')
    atts = data.get('attachments') or []
    if atts:
        r.numbered([a['title'] for a in atts if not a.get('note')])
        warns += [f"المرفقات: {a['title']}" for a in atts if a.get('note')]     # الملاحظة للخبير لا في التقرير
    else:
        r.text(TODO)
        warns.append('لا مرفقات مبنية: القسم يحمل «[يُكتب]».')
    r.closing()
    r.signature(experts)

    for k in cm.STEP_KEYS:
        rec = data['steps'][k]
        if rec['state'] != 'reviewed' and not (k in ('research', 'conclusion') and rec['state'] == 'done'):
            # البحث والنتيجة يُعدَّلان في التقرير مباشرة (أُزيل «اعتماد رأيي»): «كُتبت» لا تحتاج تحذيراً
            warns.append(f"الخطوة «{cm.STEP_LABELS[k]}» لم يراجعها الخبير ({cm.STATE_TEXT[rec['state']]}).")
        elif rec.get('stale'):
            warns.append(f"الخطوة «{cm.STEP_LABELS[k]}» تحتاج تحديثاً.")
    miss = case_conclusion.missing_points(data)
    if miss:
        warns.append('نقاط بلا بند بحث: ' + '، '.join(str(p['n']) for p in miss))

    path, ver = _unique_path(base, OUT_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r.save(path)
    rel = os.path.relpath(path, base).replace('\\', '/')
    with open(path, 'rb') as f:
        data.setdefault('files', {})[rel] = {'sha256': hashlib.sha256(f.read()).hexdigest(), 'by': 'app'}
    data['report'] = {'file': rel, 'version': ver, 'at': cw._now(), 'warnings': warns}
    cw.write_case_json(base, data)
    return path, warns


def _clean(text):
    import research_pipeline as rp
    return rp.clean_display(text)


def _emit_research_v2(r, base, data, warns):
    """البحث الجديد: «أولاً: …:» ثم أقسامه المدموجة فقط؛ غير المدموج لا يُكتب (لا «[يُكتب]») ويُذكر في الملاحظات."""
    import research_pipeline as rp
    full, partial = rp.merged_axes(base, data)
    done = {a['key'] for a, _t in full}
    for a in rp.state(data).get('axes') or []:
        if a['key'] not in done:
            left = next((l for x, l in partial if x['key'] == a['key']), [])
            warns.append(f"البحث — المحور {a['ordinal']} لم يُدمج بعد" + (f": {'، '.join(x for x in left if x)}" if left else '')
                         + ' — لم يُكتب في التقرير.')
            continue
        r.subheading(rp.heading(a))
        for s, t in next(texts for x, texts in full if x['key'] == a['key']):
            if s.get('title'):
                r.subheading(s['title'] + ':')
            _emit(r, md_blocks(_clean(t)))
    for kind, text, where in rp.notes_list(data):
        warns.append(f'البحث ({kind}) — {where}: {text}')


def _emit_conclusion(r, base, data, warns):
    """النتيجة: الافتتاحية + فقرة لكل محور (البحث الجديد)، أو ردود النقاط القديمة بلا نص المأمورية.
    لا يُنسخ نص المأمورية تحت «النتيجة» ولا «[يُكتب]» أبداً (2026-10-20)؛ «والله ولي التوفيق» من r.closing()."""
    import conclusion_pipeline as cp2
    c = data.get('conclusion') or {}
    rec = c.get('v2')
    if case_conclusion.is_v2(data) and rec and rec.get('paragraphs'):
        r.text(cp2.OPENING)
        r.numbered([_clean(p['text']) for p in rec['paragraphs']])
        warns += [f'النتيجة: {n}' for n in cp2.notes(base, data)]
        return
    answers = [a for a in c.get('answers') or [] if (a.get('text') or '').strip() and not a.get('missing')]
    if answers:
        r.text(cp2.OPENING)
        r.numbered([a['text'] for a in answers])
        return
    warns.append('النتيجة لم تُولَّد بعد — القسم فارغ ليكمله الخبير.')


def _read(base, rel):
    import case_memory
    raw, why = case_memory._read_text(base, rel)
    return (case_memory._dec(raw) if raw is not None else ''), why
