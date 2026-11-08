# ===== case_autowrite.py — التحديث التلقائي للموضوع والإجراءات حين يتوفر مصدر أحدث (2026-10-21) =====
# الموضوع: يُكتب أولاً من صحيفة الدعوى («كُتب من صحيفة الدعوى»)، فإذا وُجد العقد (case_main_contract) يُعاد كتابته
#   تلقائياً من العقد والصحيفة («كُتب من العقد وصحيفة الدعوى»).
# الإجراءات: تُكتب أولاً من بيانات النظام («كُتبت من بيانات النظام»)، وعند توفر المحاضر تُعاد كتابتها منها
#   («كُتبت من المحاضر»).
# إن كان الخبير عدّل النص يدوياً فلا يُستبدل أبداً: تُسجَّل «توفر مصدر أحدث، أعد الكتابة؟» ويظهر زر (accept_newer).
# الحالة في data['autowrite'][key] = {source, note, manual, newer, notice, at, error}.
from datetime import datetime

import case_folder as cf

NOTES = {'plaint': 'كُتب من صحيفة الدعوى', 'contract': 'كُتب من العقد وصحيفة الدعوى',
         'system': 'كُتبت من بيانات النظام', 'minutes': 'كُتبت من المحاضر'}
NEWER = 'توفر مصدر أحدث، أعد الكتابة؟'
RANK = {'plaint': 0, 'contract': 1, 'system': 0, 'minutes': 1}


def _now():
    return datetime.now().isoformat(timespec='seconds')


def subject_source(data):
    return 'contract' if (data.get('main_contract') or {}).get('found') else 'plaint'


def procedures_source(data, base=None):
    if (data.get('sessions') or {}).get('minutes'):
        return 'minutes'
    if base:
        try:
            if any(cf.kind_of(rel) == cf.MINUTES and e.get('state') == 'done'
                   for rel, e in cf.load_manifest(base)['files'].items()):
                return 'minutes'
        except Exception:
            pass
    return 'system'


def _has_text(data, key):
    if key == 'subject':
        return bool((data.get('subject') or '').strip())
    return bool(((data.get('procedures') or {}).get('text') or '').strip())


def is_manual(data, key):
    if key == 'subject':
        return bool(data.get('subject_edited'))
    return bool((data.get('procedures') or {}).get('edited'))


def _text_source_now(data, key):
    """مصدر النص الموجود (لقضية بلا سجل سابق): الإجراءات من المحاضر إن قُرئت؛ الموضوع من الصحيفة."""
    if key == 'procedures':
        return 'minutes' if (data.get('sessions') or {}).get('minutes') else 'system'
    return 'plaint'


def run(base, data, write_subject=None, write_procedures=None):
    """يعيد الكتابة حيث توفر مصدر أحدث. write_*: دوال بلا وسائط تكتب النص (تُستدعى في الخيط الخلفي).
    يرجع قائمة الخطوات التي أُعيدت كتابتها."""
    aw = data.setdefault('autowrite', {})
    did = []
    for key, want, fn in (('subject', subject_source(data), write_subject),
                          ('procedures', procedures_source(data, base), write_procedures)):
        rec = aw.setdefault(key, {})
        has = _has_text(data, key)
        rec['manual'] = is_manual(data, key) and has
        if not rec.get('source') and has and _text_source_now(data, key) == want:
            rec.update(source=want, note=NOTES[want], newer='', notice='', at=_now())      # قضية قديمة: يُسجَّل فقط
            continue
        if rec.get('source') == want and has:
            if not rec['manual']:
                rec.update(newer='', notice='')
            continue
        if has and rec.get('source') and RANK[want] < RANK[rec['source']]:
            continue                                           # لا رجوع إلى مصدر أضعف (العقد حُذف مثلاً)
        if rec['manual']:
            rec.update(newer=want, notice=NEWER)               # نص الخبير لا يُمسّ
            continue
        if fn is None:
            continue
        try:
            fn()
        except Exception as e:
            rec['error'] = str(e) or e.__class__.__name__
            continue
        if _has_text(data, key):
            rec.update(source=want, note=NOTES[want], newer='', notice='', error='', at=_now(), manual=False)
            did.append(key)
    return did


def accept_newer(base, data, key, write_fn):
    """زر «أعد الكتابة»: الخبير قبل المصدر الأحدث ← يُكتب النص منه ويُستبدل تعديله اليدوي."""
    rec = data.setdefault('autowrite', {}).setdefault(key, {})
    want = rec.get('newer') or (subject_source(data) if key == 'subject' else procedures_source(data, base))
    if key == 'subject':
        data['subject_edited'] = False
    else:
        proc = data.setdefault('procedures', {})
        proc['edited'] = False
        proc['text'] = ''
    write_fn()
    rec.update(source=want, note=NOTES[want], newer='', notice='', manual=False, at=_now(), error='')
    return rec


def line(data, key):
    """(ملاحظة المصدر، سؤال «توفر مصدر أحدث» أو '')."""
    rec = (data.get('autowrite') or {}).get(key) or {}
    return rec.get('note', ''), (rec.get('notice') or '') if rec.get('newer') else ''
