# ===== case_memory.py — ملف ذاكرة القضية 02_markdown/ذاكرة_القضية.md (المرحلة 2ز) =====
# case.json هو المصدر الوحيد للحقيقة؛ الذاكرة ناتج مشتق منه يمكن إعادة توليده كاملاً في أي وقت.
# كل قسم بين علامتين: <!-- BEGIN:id sha1=... --> ... <!-- END:id -->. التحديث يعيد توليد قسم واحد
# من case.json ثم يكتب الملف كاملاً ذرّياً (مؤقت ← fsync ← .bak ← استبدال).
# إن فُقدت العلامات أو تغيّر قسم يدوياً (البصمة لا تطابق) يُحفظ الملف باسم .corrupt-<وقت> ويُعاد توليده.
# نصوص المستندات تُقرأ من ملفات 02_markdown لحظة التوليد وتُتحقق ببصمة sha1 المسجّلة في case.json.
import hashlib
import os
import re
import tempfile
from datetime import datetime

import case_model as cm

MEMORY_REL = os.path.join('_نظام', '02_markdown', 'ذاكرة_القضية.md')
SECTION_IDS = ('status', 'case', 'mission', 'sessions', 'docs_table', 'docs_text', 'items', 'conclusion')
TITLES = {
    'status': 'حالة العمل',
    'case': 'بيانات القضية',
    'mission': 'المأمورية (حرفياً)',
    'sessions': 'الجلسات',
    'docs_table': 'سجل المستندات',
    'docs_text': 'نصوص المستندات',
    'items': 'البنود المكتوبة',
    'conclusion': 'النتيجة',
}
_SEC_RE = re.compile(r'<!-- BEGIN:(\w+) sha1=([0-9a-f]{40}) -->\n(.*?)\n<!-- END:\1 -->', re.S)
EMPTY = '_لا شيء بعد._'


def memory_path(base):
    return os.path.join(base, MEMORY_REL)


def _sha1(b):
    return hashlib.sha1(b).hexdigest()


def _read_text(base, rel):
    """(نص، None) أو (None، سبب). rel مسار نسبي لمجلد القضية."""
    if not rel:
        return None, 'لا مسار مسجّل'
    p = os.path.join(base, rel)
    try:
        with open(p, 'rb') as f:
            raw = f.read()
    except OSError:
        return None, 'الملف غير موجود'
    return raw, None


def _dec(raw):
    t = raw.decode('utf-8', errors='replace')
    return t.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10)).strip()


def _cell(v):
    return str(v if v not in (None, '') else '—').replace('|', '\\|').replace('\n', ' ')


# ---------- توليد الأقسام ----------

def _status(base, data):
    lines = [f"آخر تحديث: {data.get('updated_at') or '—'} — الجهاز: {data.get('updated_on') or '—'}", '']
    for k in cm.STEP_KEYS:
        rec = data['steps'].get(k, {})
        st = cm.STATE_TEXT.get(rec.get('state', 'pending'), rec.get('state'))
        extra = ' — تحتاج تحديثاً' if rec.get('stale') else ''
        msg = f" — {rec['message']}" if rec.get('message') else ''
        prog = rec.get('progress')
        pr = f" ({prog['done']}/{prog['total']})" if isinstance(prog, dict) and 'done' in prog else ''
        lines.append(f"- {cm.STEP_LABELS[k]}: {st}{pr}{extra}{msg}")
    return '\n'.join(lines)


def _case(base, data):
    c = data.get('case') or {}
    rows = [
        ('رقم الخبرة', data.get('caso_no')), ('الرقم الآلي', data.get('autocase_no')),
        ('رقم الدعوى', data.get('claim_no')), ('المدعية', c.get('plaintiff') or c.get('company')),
        ('الشركة', c.get('company')), ('المدعى عليه', '، '.join(c.get('defendants') or [])),
        ('تاريخ الاستلام', c.get('received_date')), ('عنوان القضية', c.get('title')),
    ]
    out = [f"- {k}: {v}" for k, v in rows if v]
    jp = data.get('judgment_pick') or {}
    if jp:
        out.append(f"- حكم الإحالة المعتمد: {jp.get('file')} ({jp.get('date') or '—'})"
                   + (f" — **{jp['note']}** — {jp.get('reason', '')}" if jp.get('note') else ''))
    for step, wb in sorted((data.get('written_by') or {}).items()):     # النموذج المستعمل فعلاً (Pro أو Flash الاحتياطي)
        if isinstance(wb, dict) and wb.get('provider'):
            out.append(f"- كُتب بواسطة ({step}): {wb['provider']}" + (f" / {wb['model'].split(' (احتياطي')[0]}" if wb.get('model') else ''))
    if data.get('subject'):
        out += ['', '**الموضوع:**', data['subject']]
    return '\n'.join(out) or EMPTY


def _mission(base, data):
    m = data.get('mission') or {}
    if not m.get('raw') and not m.get('points'):
        return EMPTY
    out = [m.get('raw') or '']
    if m.get('points'):
        out += ['', f"النقاط ({'مؤكدة' if m.get('confirmed') else 'غير مؤكدة'}):"]
        out += [f"{p['n']}. {p['text']}" for p in m['points']]
    return '\n'.join(out)


def _sessions(base, data):
    s = data.get('sessions') or {}
    mins = s.get('minutes') or []
    cnt = s.get('count_system')
    out = [f"عدد الجلسات في نظام الخبراء: {cnt if cnt is not None else '—'}",
           f"عدد المحاضر المقروءة: {len(mins)}"]
    for m in mins:
        out.append(f"- {m.get('date') or '—'} — {m.get('file') or '—'}")
    return '\n'.join(out)


def _all_docs(data):
    for p in data.get('portfolios') or []:
        for d in p.get('docs') or []:
            yield p, d


def _docs_table(base, data):
    rows = ['| الحافظة | المقدِّم | التاريخ | م | النوع | العقد | صفحات | الملف | التحويل |',
            '|---|---|---|---|---|---|---|---|---|']
    n = 0
    for p, d in _all_docs(data):
        n += 1
        conv = (d.get('convert') or {}).get('state') or '—'
        rows.append('| ' + ' | '.join(_cell(x) for x in (
            p.get('id'), p.get('submitter'), p.get('date'), d.get('no'), d.get('type'),
            d.get('contract'), d.get('pages'),
            d.get('file') if not d.get('ref_of') else f"مرجع: {d.get('ref_label')}", conv)) + ' |')
    return '\n'.join(rows) if n else EMPTY


def _docs_text(base, data):
    out = []
    for p, d in _all_docs(data):
        if d.get('ref_of'):                      # مرجع لمحتوى سبق إدراجه: لا يتكرر نصه في الملخص
            continue
        head = f"### {p.get('id')}-{d.get('no')}: {d.get('type') or 'مستند'}"
        raw, why = _read_text(base, d.get('md'))
        if raw is None:
            out.append(f"{head}\n\n⚠ لا يوجد نص ({why}).")
            continue
        warn = ''
        if d.get('sha1') and _sha1(raw) != d['sha1']:
            warn = '⚠ بصمة الملف لا تطابق المسجّلة في case.json (عُدِّل بعد التحويل؟).\n\n'
        out.append(f"{head}\n\n{warn}{_dec(raw)}")
    return '\n\n'.join(out) if out else EMPTY


def _items(base, data):
    out = []
    for it in data.get('research') or []:
        head = f"### البند {it.get('n')} — {cm.STATE_TEXT.get(it.get('state'), it.get('state'))}"
        raw, why = _read_text(base, it.get('file'))
        if raw is None:
            out.append(f"{head}\n\n⚠ لا يوجد نص ({why}).")
            continue
        warn = ''
        if it.get('sha1') and _sha1(raw) != it['sha1']:
            warn = '⚠ عُدِّل الملف يدوياً بعد كتابته.\n\n'
        out.append(f"{head}\n\n{warn}{_dec(raw)}")
    return '\n\n'.join(out) if out else EMPTY


def _conclusion(base, data):
    raw, _ = _read_text(base, (data.get('conclusion') or {}).get('file'))
    return _dec(raw) if raw else EMPTY


_RENDER = {'status': _status, 'case': _case, 'mission': _mission, 'sessions': _sessions,
           'docs_table': _docs_table, 'docs_text': _docs_text, 'items': _items, 'conclusion': _conclusion}


def render_section(base, data, sid):
    """النص الكامل للقسم: عنوان + جسم محاط بالعلامتين (مع بصمة الجسم)."""
    if sid not in _RENDER:
        raise KeyError(f'قسم غير معروف: {sid}')
    body = _RENDER[sid](base, data).strip('\n')
    return (f"## {TITLES[sid]}\n\n<!-- BEGIN:{sid} sha1={_sha1(body.encode('utf-8'))} -->\n"
            f"{body}\n<!-- END:{sid} -->")


def generate(base, data):
    title = f"# ذاكرة القضية {data.get('caso_no')}\n\n> ملف مولَّد من case.json — لا تعدّله يدوياً.\n"
    return title + '\n\n' + '\n\n'.join(render_section(base, data, s) for s in SECTION_IDS) + '\n'


# ---------- الكتابة والتحديث ----------

def _atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.mem.', suffix='.tmp', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            try:
                with open(path, 'rb') as src:
                    raw = src.read()
                with open(path + '.bak.tmp', 'wb') as b:
                    b.write(raw)
                os.replace(path + '.bak.tmp', path + '.bak')
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _parse(text):
    """{id: (sha_في_العلامة, جسم, بداية, نهاية)} إن كان الملف سليماً وبالترتيب، وإلا None."""
    found = list(_SEC_RE.finditer(text))
    if tuple(m.group(1) for m in found) != SECTION_IDS:
        return None
    for m in found:
        if _sha1(m.group(3).encode('utf-8')) != m.group(2):
            return None
    return found


def _quarantine(path):
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    dst = f"{path}.corrupt-{stamp}"
    i = 1
    while os.path.exists(dst):
        i += 1
        dst = f"{path}.corrupt-{stamp}-{i}"
    os.replace(path, dst)
    return dst


def regenerate(base, data):
    """يولّد الملف كاملاً من case.json (يستبدل الموجود ذرّياً مع .bak)."""
    _atomic_write(memory_path(base), generate(base, data))
    return memory_path(base)


def update_section(base, data, *sids):
    """يعيد توليد الأقسام المذكورة فقط ويترك غيرها حرفياً. يرجع 'updated' أو 'regenerated'.
    ملف مفقود ← توليد كامل؛ علامات مفقودة/مخلّة أو قسم عُدِّل يدوياً ← حجر الملف ثم توليد كامل."""
    for s in sids:
        if s not in _RENDER:
            raise KeyError(f'قسم غير معروف: {s}')
    path = memory_path(base)
    if not os.path.exists(path):
        regenerate(base, data)
        return 'regenerated'
    try:
        with open(path, encoding='utf-8', newline='') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        text = ''
    found = _parse(text)
    if found is None:
        _quarantine(path)
        regenerate(base, data)
        return 'regenerated'
    out, pos = [], 0
    for m in found:
        sid = m.group(1)
        out.append(text[pos:m.start()])
        if sid in sids:
            # render_section يضيف العنوان قبل العلامة؛ العنوان سبق المطابقة فنستبدل الجسم فقط
            body = _RENDER[sid](base, data).strip('\n')
            out.append(f"<!-- BEGIN:{sid} sha1={_sha1(body.encode('utf-8'))} -->\n{body}\n<!-- END:{sid} -->")
        else:
            out.append(m.group(0))
        pos = m.end()
    out.append(text[pos:])
    _atomic_write(path, ''.join(out))
    return 'updated'
