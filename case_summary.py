# ===== case_summary.py — «الملخص.md» في جذر مجلد القضية: مرجع كل الخطوات (2026-10-21) =====
# يُكتب ذرّياً بعد كل تغيير (خط البداية، الفرز، الكتابة التلقائية، وكل حفظ لـcase.json): قائمة كل المستندات بأسمائها
# الجديدة ونوعها ومقدّمها وتاريخها وحالة تحويلها والمحرّك؛ تفاصيل الملفات المختلطة؛ العقد/العقود ومكانها وملخصها؛
# المحاضر وتواريخها؛ أسئلة الفرز المعلّقة؛ مصدر كل جزء من التقرير. يُبنى من manifest وcase.json فقط (بلا قراءة نصوص).
import os
import re
import tempfile
from datetime import datetime

import case_folder as cf
import case_layout as cl
import doc_header

ENGINE_TEXT = {'text_layer': 'طبقة النص', 'direct': 'مباشر (Word/نص)', 'gemini': 'Gemini', 'local': 'OCR المحلي',
               'external_ocr': 'OCR خارجي', 'cloud_vision': 'Google Vision', 'text': 'نص جاهز'}
STATE_TEXT = {'done': 'محوَّل', 'failed': 'تعذّر التحويل', 'missing': 'حُذف الأصل', 'pending': 'لم يُحوَّل بعد'}
SOURCE_TEXT = {'plaint': 'كُتب من صحيفة الدعوى', 'contract': 'كُتب من العقد وصحيفة الدعوى',
               'system': 'كُتبت من بيانات النظام', 'minutes': 'كُتبت من المحاضر',
               'stage2': 'كُتب من هذا الملخص بطلب واحد (المرحلة الثانية)'}


def _esc(v):
    return (str(v) if v not in (None, '') else '—').replace('|', '\\|').replace('\n', ' ')


def _date_of(rel, parts):
    if parts:
        d = next((p.get('date') for p in parts if p.get('date')), '')
        if d:
            return d
    m = re.search(r'(\d{2}-\d{2}-\d{4})', os.path.basename(rel))
    return m.group(1) if m else ''


def _engine(e):
    eng = e.get('engine') or ''
    return ENGINE_TEXT.get(eng, eng) + (f" (أُعيد {e['retries']} مرة)" if e.get('retries') else '')


def _state(e):
    if e.get('state') == 'failed' and e.get('loop'):
        return 'تعذّر التحويل (حلقة تكرار)'
    return STATE_TEXT.get(e.get('state'), e.get('state') or '—')


def documents(base, man):
    rows = []
    for rel, e in sorted(man['files'].items(), key=lambda kv: (cf.FOLDERS.index(kv[0].split('/')[0])
                                                              if kv[0].split('/')[0] in cf.FOLDERS else 9, kv[0])):
        s = e.get('sort') or {}
        parts = s.get('parts') or []
        kind = cf.KIND_LABELS.get(cf.kind_of(rel), '—')
        if s.get('state') == 'mixed':
            kind = 'ملف مختلط'
        labels = sorted({p.get('label') for p in parts if p.get('label')})
        date = _date_of(rel, parts)
        if (not labels or not date) and e.get('state') == 'done':      # رأس نوع المستند في markdown (بلا طلب)
            h = doc_header.read(base, e.get('md') or cf.md_rel(rel))
            if h.get('sha1') == e.get('sha1'):
                labels = labels or ([h['by']] if h.get('by') else [])
                date = date or h.get('date') or ''
        rows.append({'name': os.path.basename(rel), 'folder': rel.split('/')[0], 'kind': kind,
                     'by': '، '.join(labels), 'date': date, 'state': _state(e), 'engine': _engine(e),
                     'parts': parts if s.get('state') == 'mixed' else [], 'rel': rel})
    return rows


def render(base, data, man=None):
    import case_sort
    man = man or cf.load_manifest(base)
    docs = documents(base, man)
    out = [f"# ملخص القضية {data.get('caso_no', '')}", '',
           f"> يُحدَّث تلقائياً بعد كل تغيير — آخر تحديث {datetime.now().strftime('%Y-%m-%d %H:%M')}. لا تعدّله يدوياً.", '']
    c = data.get('case') or {}
    if c:
        out += ['## بيانات القضية', '', f"- رقم الخبرة: {data.get('caso_no', '')}",
                f"- رقم الدعوى: {data.get('claim_no') or '—'}",
                f"- المدعي: {c.get('plaintiff') or '، '.join(c.get('plaintiffs') or []) or '—'}",
                f"- المدعى عليه: {'، '.join(c.get('defendants') or []) or '—'}", '']
    out += ['## المستندات', '', '| # | الاسم | المجلد | النوع | المقدّم | التاريخ | التحويل | المحرّك |',
            '|---|---|---|---|---|---|---|---|']
    for i, r in enumerate(docs, 1):
        out.append(f"| {i} | {_esc(r['name'])} | {_esc(r['folder'])} | {_esc(r['kind'])} | {_esc(r['by'])} | "
                   f"{_esc(r['date'])} | {_esc(r['state'])} | {_esc(r['engine'])} |")
    if not docs:
        out.append('| — | لا مستندات بعد | | | | | | |')
    mixed = [r for r in docs if r['parts']]
    out += ['', '## الملفات المختلطة', '']
    if not mixed:
        out.append('_لا شيء._')
    for r in mixed:
        out.append(f"### {r['name']}")
        for p in r['parts']:
            pg = p.get('pages') or []
            rng = f"الصفحات {pg[0]}–{pg[1]}" if len(pg) == 2 else 'الصفحات —'
            out.append(f"- {p.get('type', '—')} — {p.get('label') or 'مقدّم غير معروف'} — "
                       f"{p.get('date') or 'بلا تاريخ'} — {rng}")
    qs = case_sort.questions(data)
    if qs:
        out += ['', '## تنتظر قرارك', '']
        out += [f"- 🔴 {os.path.basename(f)}: {q}" for f, q in qs]
    out += ['', '## العقد', '']
    mc = data.get('main_contract') or {}
    if mc.get('found'):
        k = mc['contract']
        out += [f"- العقد: {'رقم ' + k['number'] if k.get('number') else '—'}",
                f"- التاريخ: {k.get('date') or '—'}{' ✓ متحقَّق حرفياً' if k['checks'].get('date') else ''}",
                f"- الأطراف: {'، '.join(k.get('parties') or []) or '—'}",
                f"- النطاق: {k.get('scope') or '—'}",
                f"- القيمة: {k.get('value') or '—'}{' ✓ متحقَّقة حرفياً' if k['checks'].get('value') else ''}",
                f"- المدة: {k.get('duration') or '—'}",
                f"- الملخص: {k.get('summary') or '—'}",
                f"- مكانه: {_where(k)}"]
    else:
        out.append(f"_{mc.get('message') or 'لم يُبحث بعد'}._")
    found = triage_contracts(base, man)
    if found:
        out += ['', '### العقود من فرز المستندات (طلب واحد لكل ملف، متحقَّق حرفياً)', '']
        out += [f"- {name}: {line}" for name, line in found]
    others = [x for x in (data.get('contracts') or {}).get('items') or [] if x.get('origin') != 'main_contract']
    if others:
        out += ['', '### عقود أخرى مستخرجة', '']
        for x in others:
            out.append(f"- {x.get('kind', 'عقد')} {('بتاريخ ' + x['date']) if x.get('date') else ''} "
                       f"{('بقيمة ' + x['value']) if x.get('value') else ''} — {x.get('doc', '')}"
                       f"{'' if x.get('verified') else ' ⚠غير متحقَّق'}")
    out += ['', '## المحاضر', '']
    mins = [r for r in docs if cf.kind_of(r['rel']) == cf.MINUTES]
    dates = {}
    for m in (data.get('sessions') or {}).get('minutes') or []:
        if m.get('no') is not None:
            dates[m['no']] = m.get('date') or ''
    if not mins:
        out.append('_لا محاضر بعد._')
    for r in mins:
        mm = re.search(r'رقم (\d+)', r['name'])
        no = int(mm.group(1)) if mm else None
        out.append(f"- {r['name']} — التاريخ: {dates.get(no) or '—'} — {r['state']}")
    out += ['', '## محتوى المستندات', '',
            '_من الفرز (طلب ذكاء واحد لكل ملف)؛ لا يُكتب هنا إلا ما تحقق منه الكود حرفياً في نص الملف نفسه._', '']
    out += content(base, data, man) or ['_لم يُفرز أي مستند بعد._']
    out += ['', '## مصدر كل جزء من التقرير', '']
    out += [f"- {line}" for line in sources(data)]
    return '\n'.join(out) + '\n'


_TYPE_NAME = {'حافظة': 'حافظة مستندات', 'مذكرة': 'مذكرة دفاع', 'محضر': 'محضر خبرة', 'حكم': 'حكم',
              'صحيفة': 'صحيفة دعوى', 'تقرير': 'تقرير خبرة سابق', 'أخرى': 'غير مصنَّف'}


def _who(data, role, index, text=''):
    import case_sort
    return case_sort.role_label(data, role, index or 1, text) if role else ''


def _contract_line(c, md, pg):
    """سطر عقد من الفرز بعد التحقق الحرفي (case_main_contract.verify)، أو '' إن لم يوجد عقد."""
    import case_main_contract as mc
    import case_sort
    if not c.get('found'):
        return ''
    v = mc.verify(c, case_sort.part_text(md, pg) if md else '')
    bits = ['عقد' + (f" رقم {v['number']}" if v.get('number') else '')]
    bits.append(f"مؤرخ {v['date']}" if v['checks'].get('date') else
                ('التاريخ لم يتحقق حرفياً' if v.get('date') else ''))
    if v.get('parties'):
        bits.append('بين ' + ' و'.join(v['parties']))
    if v.get('scope'):
        bits.append(f"نطاقه: {v['scope']}")
    if v.get('value'):
        bits.append(f"قيمته {v['value']}" if v['checks'].get('value') else 'القيمة لم تتحقق حرفياً')
    for k, lab in (('duration', 'مدته'), ('payment', 'طريقة السداد')):
        if v.get(k):
            bits.append(f"{lab}: {v[k]}")
    where = ' '.join(x for x in ((f"المستند رقم ({v['doc_no']})" if v.get('doc_no') else ''),
                                (f"صفحة {v['page']}" if v.get('page') else '')) if x)
    if where:
        bits.append(f"مكانه: {where}")
    return '، '.join(b for b in bits if b)


def triage_contracts(base, man=None):
    """[(اسم الملف، سطر العقد)] لكل عقد وجده طلب الفرز (text_light) في ملفات القضية — لقسم «العقد» في الملخص."""
    import case_triage as ct
    out = []
    for rel, e, t in ct.entries(base, man):
        md = ''
        try:
            with open(os.path.join(base, e.get('md') or cf.md_rel(rel)), encoding='utf-8') as f:
                md = doc_header.strip(f.read())      # الرأس بيانات وصفية: لا يدخل التحقق الحرفي
        except OSError:
            pass
        for p in t.get('parts') or []:
            for c in [p.get('contract') or {}] + list(p.get('more_contracts') or []):
                line = _contract_line(c, md, p.get('pages') or [])
                if line:
                    out.append((os.path.basename(rel), line))
    return out


def content(base, data, man=None):
    """قسم لكل مستند مفروز: النوع والمقدّم والتاريخ ورقم المحضر، ثم المحتوى المتحقَّق (المستندات، العقد، المبالغ،
    الدفاع، الحضور والحجز). هذا ما تُرسله المرحلتان الثانية والثالثة بدل نصوص المستندات كلها."""
    import case_triage as ct
    out = []
    for rel, e, t in ct.entries(base, man):
        parts = t.get('parts') or []
        out.append(f"### {os.path.basename(rel)}")
        if t.get('error'):
            out.append(f"- تعذّر فرزه آلياً: {t['error']}")
        md = ''
        try:
            with open(os.path.join(base, e.get('md') or cf.md_rel(rel)), encoding='utf-8') as f:
                md = doc_header.strip(f.read())      # الرأس بيانات وصفية: لا يدخل التحقق الحرفي
        except OSError:
            pass
        for p in parts:
            import case_sort
            head = [_TYPE_NAME.get(p.get('type'), p.get('type') or '—')]
            if p.get('label'):
                head.append(f"المقدّم: {p['label']}")
            if p.get('date'):
                head.append(f"التاريخ: {p['date'].replace('-', '/')}")
            if p.get('minute_no') is not None:
                head.append(f"رقم المحضر: {p['minute_no']}")
            if p.get('referral'):
                head.append('حكم إحالة للخبرة')
            pg = p.get('pages') or []
            if len(parts) > 1 and len(pg) == 2:
                head.append(f"الصفحات {pg[0]}–{pg[1]}")
            out.append('- ' + ' — '.join(head))
            docs = p.get('documents') or []
            if docs:
                out.append('  - المستندات: ' + '؛ '.join(
                    (f"({d['no']}) " if d.get('no') else '') + (d.get('desc') or '') for d in docs))
            for c in [p.get('contract') or {}] + list(p.get('more_contracts') or []):
                line = _contract_line(c, md, pg)
                if line:
                    out.append('  - العقد: ' + line)
            for a in p.get('amounts') or []:
                out.append(f"  - مبلغ: {a.get('label') or 'مبلغ'}: {a['amount']}"
                           + (f" بتاريخ {a['date']}" if a.get('date') else '') + f" — «{a.get('quote', '')}»")
            for d in p.get('defenses') or []:
                out.append(f"  - وجه دفاع: {d['summary']} — «{d['quote']}»")
            att = p.get('attendance') or {}
            for key, lab in (('present', 'حضر'), ('absent', 'تخلف')):
                for x in att.get(key) or []:
                    out.append(f"  - {lab}: {_who(data, x['role'], x.get('index'), md) or x['role']} — «{x['quote']}»")
            if att.get('booking_date'):
                out.append(f"  - تاريخ حجز الدعوى للتقرير: {att['booking_date']}")
        out.append('')
    return out


def verified_text(base, data, inputs_only=False):
    """نص الملخص المتحقَّق (بلا سطر وقت التحديث): مرجع التحقق من أرقام وتواريخ المرحلتين الثانية والثالثة.
    inputs_only: بلا قسم «مصدر كل جزء» (يتغيّر بالكتابة نفسها) — لبصمة المدخلات."""
    text = '\n'.join(l for l in render(base, data).splitlines() if not l.startswith('> يُحدَّث'))
    if inputs_only:
        text = text.split('\n## مصدر كل جزء من التقرير')[0]
    return text


def _where(k):
    try:
        import case_main_contract as mc
        return mc.where(k)
    except Exception:
        return k.get('file', '—')


def sources(data):
    aw = data.get('autowrite') or {}
    sub = aw.get('subject') or {}
    proc = aw.get('procedures') or {}
    pick = (data.get('judgment_pick') or {}).get('file') or ''
    out = [f"الموضوع: {SOURCE_TEXT.get(sub.get('source'), 'لم يُكتب بعد')}"
           + (' (عدّله الخبير يدوياً)' if sub.get('manual') else ''),
           f"المأمورية: من {os.path.basename(pick) if pick else 'حكم الإحالة'}",
           f"الإجراءات: {SOURCE_TEXT.get(proc.get('source'), 'لم تُكتب بعد')}"
           + (' (عدّلها الخبير يدوياً)' if proc.get('manual') else ''),
           'المستندات والمرفقات: من الحوافظ والمذكرات ومستندات النظام أعلاه',
           'البحث والنتيجة: من الحقائق المتحقَّق منها في المستندات والعقد والمحاضر']
    return out


def write(base, data):
    """يكتب الملخص.md ذرّياً ويرجع مساره."""
    text = render(base, data)
    path = os.path.join(base, cl.SUMMARY)
    fd, tmp = tempfile.mkstemp(prefix='.sum.', suffix='.tmp', dir=base)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def write_quiet(base, data):
    """من write_case_json: لا يُفشل الحفظ أبداً، ولا يكتب قبل اكتمال البنية الجديدة."""
    try:
        if os.path.isdir(os.path.join(base, cl.SYS)) and data.get('caso_no'):
            write(base, data)
    except Exception:
        pass
