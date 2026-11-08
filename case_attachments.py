# ===== case_attachments.py — خطوة «المرفقات» (المرحلة 2ك، أُعيد بناؤها 2026-10-17) =====
# تُبنى آلياً من case.json بلا ذكاء اصطناعي ودون انتظار اكتمال أي خطوة: أول ما توجد محاضر يظهر بند
# «عدد ( N ) محضر أعمال.»، ثم تُضاف حافظة لكل حافظة مستندات بعبارة الإحالة المعتمدة في التقارير النموذجية:
#   «حافظة مستندات {مقدِّمها} بتاريخ {DD/MM/YYYY}» (وتحتها «عدد ( n ) {نوع}» لكل نوع مستند محدَّد).
# تتجدد وحدها (sync_attachments) كلما تغيّر عدد المحاضر أو أُضيفت حافظة/مستند. الخرج: case.json['attachments']
# + 04_تقرير/المرفقات.md. الترقيم المتسلسل للعرض فقط؛ ref ثابت لكل بند (minutes / معرّف الحافظة / نوع).
import os
import re

import case_documents
import case_memory
import case_model as cm
import case_workspace as cw

REL = os.path.join('_نظام', '04_تقرير', 'المرفقات.md')
MINUTES_TEXT = 'عدد ( {n} ) محضر أعمال.'
PORTFOLIO_TEXT = 'حافظة مستندات {who}'
DOC_GROUP_TEXT = 'عدد ( {n} ) {type}.'


def _pnum(p):
    m = re.fullmatch(r'P(\d+)', p['id'])
    return int(m.group(1)) if m else 10 ** 6


def _dmy(iso):
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', (iso or '').strip())
    return f'{m.group(3)}/{m.group(2)}/{m.group(1)}' if m else (iso or '').strip()


POA_TEXT = 'صور توكيلات.'
ITEM_TEXT = '{kind} {side} المؤرخة {date}.'
NOTE_FROM_DOCS = ('لم تُقرأ المرفقات من المحاضر بل من المستندات المرفقة بملف القضية — تأكد منها '
                  '(والمستند الذي لم يُضَف مسؤولية الخبير).')
_SUBMIT = re.compile(r'(?:قدم|قدّم|قدمت|أرفق|ارفق|أودع|اودع)')
_KINDS = ((re.compile(r'مذكر[ةه]\s*(?:بدفاع|دفاع|ختامية|شارحة)?'), 'مذكرة دفاع'),
          (re.compile(r'حافظ[ةه]\s*(?:ال)?مستندات|حافظ[ةه]'), 'حافظة مستندات'))


def _side_label(data, role):
    """«المدعية/المدعي» و«المدعى عليها/المدعى عليه» بحسب الأطراف (الشركة مؤنث)."""
    import case_procedures as cp
    res = ((data.get('procedures') or {}).get('attendance') or {}).get('result') or []
    fem = next((cp._is_company(r['name']) for r in res if r.get('role') == role), None)
    if fem is None:
        c = data.get('case') or {}
        name = (c.get('plaintiff') or c.get('company') or '') if role == 'plaintiff' else ((c.get('defendants') or [''])[0])
        fem = cp._is_company(name) if name else role == 'plaintiff'
    if role == 'plaintiff':
        return 'المدعية' if fem else 'المدعي'
    return 'المدعى عليها' if fem else 'المدعى عليه'


def _role_of(text):
    import case_procedures as cp
    n = cp.norm_ar(text)
    if re.search(r'المدعي\s*علي', n):
        return 'defendant'
    if 'المدعي' in n:
        return 'plaintiff'
    return ''


_TEXT_CACHE = {}


def _minutes_texts(data):
    import case_procedures as cp
    rows = (data.get('sessions') or {}).get('minutes') or []
    out = []
    for r in sorted(rows, key=lambda r: (r.get('date') or '9999', r.get('no') or 0)):
        path = r.get('file') or ''
        if not path or not os.path.exists(path):
            continue
        try:
            st = os.stat(path)
            key = (path, st.st_mtime, st.st_size)
            if key not in _TEXT_CACHE:              # المزامنة تتكرر كثيراً ← لا تُعاد قراءة (أو OCR) محضر لم يتغيّر
                _TEXT_CACHE[key] = cp.read_minute_text(path)
            t = _TEXT_CACHE[key]
        except Exception:
            continue
        out.append((r, ' '.join(t) if isinstance(t, list) else (t or '')))
    return out


def from_minutes(data):
    """(توكيلات؟، [{'role','kind','date'}]) مما ورد في المحاضر من «قدم الحاضر عن … مذكرة … وحافظة مستندات»."""
    poa, items = False, []
    for r, text in _minutes_texts(data):
        if 'توكيل' in text and re.search(r'ارفاق|إرفاق|ارفق|أرفق', text):
            poa = True
        for sent in re.split(r'[.\n]|،\s*و(?=أفاد|قرر|عليه)', text):
            if not _SUBMIT.search(sent):
                continue
            role = _role_of(sent[:_SUBMIT.search(sent).end() + 60])
            if not role:
                continue
            found = []
            for rx, kind in _KINDS:
                for m in rx.finditer(sent):
                    found.append((m.start(), kind))
            seen = set()
            for _pos, kind in sorted(found):
                if _pos in seen:
                    continue
                seen.add(_pos)
                items.append({'role': role, 'kind': kind, 'date': r.get('date') or r.get('text_date') or ''})
    return poa, items


def from_documents(data):
    """[{'role','kind','date'}] من المستندات المضافة: محتوى كل ملف إن ذُكر فيه أكثر من مستند، وإلا المذكرة بنفسها
    وبقية مستندات الحافظة حافظةً واحدة بتاريخها."""
    items = []
    for p in data.get('portfolios') or []:
        who = case_documents.clean_submitter(p.get('submitter'))
        role = _role_of(who) if who else ''
        side = who if re.fullmatch(r'ال(?:مدعي|مدعية|مدعى عليه|مدعى عليها|مدعى عليهم)(?: \S+)?', who or '') else ''
        docs = [d for d in p['docs'] if d.get('file')]
        rest = []
        for d in docs:
            if d.get('contents'):
                items += [dict(c, role=c.get('role') or role) for c in d['contents']]
            elif 'مذكر' in (d.get('doc_type') or ''):
                items.append({'role': role, 'side': side, 'kind': 'مذكرة دفاع',
                              'date': d.get('doc_date') or p.get('date') or ''})
            else:
                rest.append(d)
        if rest:
            items.append({'role': role, 'side': side, 'kind': 'حافظة مستندات',
                          'date': p.get('date') or next((d.get('doc_date') for d in rest if d.get('doc_date')), '')})
    return items


def from_triage(data):
    """[{'role','kind','date'}] للحوافظ والمذكرات من الفرز (data['triage_docs'] يكتبه خط البداية) — حين لا حوافظ قديمة."""
    return [dict(x) for x in data.get('triage_docs') or [] if x.get('kind')]


def build_attachments(data):
    """المرفقات (دالة صرفة على البيانات والمحاضر): عدد المحاضر، ثم «صور توكيلات»، ثم مستندات المدعية
    (المذكرة قبل الحافظة) مرتبة تاريخياً، ثم مستندات المدعى عليه بالنظام نفسه. المصدر المحاضر؛ وإن لم تذكر شيئاً
    فالمستندات المرفقة مع ملاحظة للتأكد. [{'no','kind','ref','title'}]"""
    ai = data.get('attachments_ai') or {}
    if ai.get('items') and not ai.get('stale'):          # المرحلة الثانية: قائمة النموذج بعد تحققها بالكود
        out = [{'kind': 'minutes' if 'محضر أعمال' in t else 'doc', 'ref': f'stage2:{i}', 'title': t}
               for i, t in enumerate(ai['items'])]
        for n, a in enumerate(out, 1):
            a['no'] = n
        return out
    out = []
    n_min = len((data.get('sessions') or {}).get('minutes') or [])
    if n_min:
        out.append({'kind': 'minutes', 'ref': 'minutes', 'title': MINUTES_TEXT.format(n=n_min)})
    poa, items = from_minutes(data)
    source = 'minutes'
    if not items:
        items, source = from_documents(data) or from_triage(data), 'documents'
    if poa:
        out.append({'kind': 'poa', 'ref': 'poa', 'title': POA_TEXT})
    rank = {'plaintiff': 0, 'defendant': 1}
    items.sort(key=lambda it: (rank.get(it['role'], 2), it.get('date') or '9999', it['kind'] != 'مذكرة دفاع'))
    for i, it in enumerate(items):
        side = it.get('side') or (_side_label(data, it['role']) if it['role'] else '(لم يتحدد مقدّمها)')
        title = (ITEM_TEXT.format(kind=it['kind'], side=side, date=_dmy(it['date'])) if it.get('date')
                 else f"{it['kind']} {side}.")
        out.append({'kind': 'doc', 'ref': f"{source}:{i}", 'title': title})
    if items and source == 'documents':
        out.append({'kind': 'note', 'ref': 'note', 'title': NOTE_FROM_DOCS, 'note': True})
    n = 0
    for a in out:
        if not a.get('note'):
            n += 1
            a['no'] = n
        else:
            a['no'] = None
    return out


def render_md(items):
    if not items:
        return '# المرفقات\n\n_لا مرفقات._\n'
    return '# المرفقات\n\n' + '\n'.join(f"{a['no']}. {a['title']}" for a in items) + '\n'


def _summary(items):
    n_p = sum(1 for a in items if a['kind'] in ('portfolio', 'doc'))
    has_min = any(a['kind'] == 'minutes' for a in items)
    return f"{'المحاضر' if has_min else 'بلا محاضر'} + {n_p} مستند" if items else 'لا مرفقات بعد'


def sync_attachments(base, data):
    """يبني المرفقات من الحالة الراهنة ويكتبها إن تغيّرت. بلا شروط على غيرها من الخطوات. يرجع هل تغيّر شيء.
    لا يرفع استثناءً: فشل الكتابة يُسجَّل failed برسالة."""
    items = build_attachments(data)
    old = [(a['ref'], a['title']) for a in data.get('attachments') or []]
    if old == [(a['ref'], a['title']) for a in items] and cm.state(data, 'attachments') in cm.OK_STATES:
        return False
    st = cm.state(data, 'attachments')
    if not items and st == 'needs_input':
        return False
    try:
        if st == 'running':
            return False
        cm.set_step(data, 'attachments', 'running')
        case_documents._write_md(base, REL, render_md(items))
        data['attachments'] = items
        cm.set_step(data, 'attachments', 'done' if items else 'needs_input',
                    _summary(items) if items else 'ستظهر هنا المحاضر والحوافظ تلقائياً')
    except Exception as e:
        try:
            cm.set_step(data, 'attachments', 'failed', f'{e.__class__.__name__}: {e}')
        except cm.StepError:
            pass
    cw.write_case_json(base, data)
    try:
        case_memory.update_section(base, data, 'status')
    except Exception:
        pass
    return True


def run_attachments(base, data, force=False):
    """للتوافق مع الواجهة: force يعيد البناء حتى لو لم يتغيّر شيء. يرجع حالة الخطوة."""
    if force:
        data['attachments'] = []
        if cm.state(data, 'attachments') in cm.OK_STATES:
            cm.set_step(data, 'attachments', 'needs_input')
    sync_attachments(base, data)
    return cm.state(data, 'attachments')
