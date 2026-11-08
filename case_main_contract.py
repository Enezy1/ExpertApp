# ===== case_main_contract.py — البحث عن العقد في الحوافظ من الأقدم (2026-10-21) =====
# (المراحل الثلاث، 2026-10-21) العقد يُقرأ من الفرز وحده (case_triage: كل ملف طلب واحد) — find(..., from_triage=True)
# بلا أي طلب ذكاء؛ الطلب المخصص لكل حافظة أدناه بقي للتوافق فقط ولا يُستدعى من خط البداية.
# مع سؤال الفرز للحوافظ يُسأل: هل تحتوي على عقد؟ رقمه وتاريخه وأطرافه ونطاقه وقيمته ومدته وملخص قصير ومكانه.
# هنا: تُرتَّب الحوافظ (حوافظ/ + أجزاء «حافظة» في الملفات المختلطة) بتاريخها من الأقدم؛ لكل حافظة: جواب الفرز إن ذكر
# عقداً، وإلا طلب مخصص بنص الحافظة كاملاً (بحد). التحقق بالكود: التاريخ والقيمة حرفياً في نص الحافظة (case_contracts).
# أول حافظة فيها عقد متحقَّق ← يتوقف البحث. النتيجة في data['main_contract'] وتُضاف إلى data['contracts']['items']
# (بين طرفي الدعوى، متحقَّق) فتستعملها كتابة الموضوع فوراً مع صحيفة الدعوى، ويسجّلها الملخص.md بمكانها.
import hashlib
import json
import os
import re
from datetime import datetime

import case_folder as cf

MAX_CHARS = 60000

PROMPT = """هذه حافظة مستندات من قضية أمام إدارة الخبراء. أعد JSON فقط بلا أي نص آخر.
هل تحتوي على عقد؟ إن وُجد: رقمه وتاريخه وأطرافه ونطاقه وقيمته ومدته، وملخص قصير، ومكانه (رقم المستند/الصفحة).
اكتب التاريخ والقيمة كما وردا حرفياً في النص. لا تخمّن: ما لا يرد اتركه فارغاً.
{{"found": false, "number": "", "date": "DD/MM/YYYY", "parties": [], "scope": "", "value": "", "duration": "",
  "summary": "", "doc_no": "", "page": null}}
نص الحافظة:
{text}"""


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _read(base, e, rel):
    try:
        with open(os.path.join(base, e.get('md') or cf.md_rel(rel)), encoding='utf-8') as f:
            import doc_header
            return doc_header.strip(f.read())             # الرأس لا يدخل التحقق الحرفي للعقد
    except OSError:
        return ''


def _date_key(dmy):
    m = re.fullmatch(r'(\d{2})-(\d{2})-(\d{4})', dmy or '')
    return f'{m.group(3)}{m.group(2)}{m.group(1)}' if m else '99999999'      # بلا تاريخ ← آخراً


def portfolios(base, man=None):
    """[{file, label, date, text, parts_pages, sort_contract}] للحوافظ مرتّبة بالتاريخ من الأقدم."""
    import case_sort
    man = man or cf.load_manifest(base)
    out = []
    for rel, e in man['files'].items():
        if e.get('state') != 'done' or not os.path.exists(os.path.join(base, rel)):
            continue
        parts = ((e.get('sort') or {}).get('parts') or (e.get('triage') or {}).get('parts') or [])
        md = None
        if cf.kind_of(rel) == cf.PORTFOLIO:
            m = re.search(r'(\d{2}-\d{2}-\d{4})', os.path.basename(rel))
            p0 = next((p for p in parts if p.get('type') == case_sort.T_PORTF), {})
            md = _read(base, e, rel)
            out.append({'file': rel, 'date': p0.get('date') or (m.group(1) if m else ''), 'label': p0.get('label', ''),
                        'text': md, 'sort_contract': p0.get('contract') or {}, 'pages': None})
        elif cf.kind_of(rel) == cf.OTHER:
            for p in parts:
                if p.get('type') == case_sort.T_PORTF:
                    md = md if md is not None else _read(base, e, rel)
                    out.append({'file': rel, 'date': p.get('date', ''), 'label': p.get('label', ''),
                                'text': case_sort.part_text(md, p.get('pages')), 'sort_contract': p.get('contract') or {},
                                'pages': p.get('pages')})
    out.sort(key=lambda x: (_date_key(x['date']), x['file']))
    return out


def _sig(items):
    h = hashlib.sha1()
    for it in items:
        h.update((it['file'] + '|' + it['date'] + '|' + str(len(it['text']))).encode('utf-8'))
        h.update(hashlib.sha1(it['text'].encode('utf-8')).digest())
        h.update(json.dumps(it.get('sort_contract') or {}, ensure_ascii=False, sort_keys=True).encode('utf-8'))
    return h.hexdigest()


def parse(raw):
    if isinstance(raw, dict):
        return raw
    s = re.sub(r'^```(?:json)?|```$', '', (raw or '').strip(), flags=re.M).strip()
    i, j = s.find('{'), s.rfind('}')
    return json.loads(s[i:j + 1]) if 0 <= i < j else {}


def verify(c, text):
    """العقد بعد التحقق الحرفي: checks {date, value} و verified (التاريخ متحقَّق، والقيمة متحقَّقة أو غير مذكورة)."""
    import case_contracts as cc
    c = {k: (' '.join(str(c.get(k) or '').split()) if k != 'parties' else
             [' '.join(str(p).split()) for p in c.get('parties') or [] if str(p).strip()][:4])
         for k in ('number', 'date', 'parties', 'scope', 'value', 'duration', 'payment', 'summary', 'doc_no')} | {
        'page': c.get('page')}
    checks = {'date': cc.date_in_text(c['date'], text) if c['date'] else None,
              'value': cc.amount_in_text(c['value'], text) if c['value'] else None}
    c['checks'] = checks
    c['verified'] = checks['date'] is True and checks['value'] is not False
    return c


def find(base, data, ask, force=False, from_triage=False):
    """يبحث من أقدم حافظة. يرجع {'found', 'contract', 'searched', 'message'} ويحفظ data['main_contract'].
    from_triage=True: من جواب الفرز وحده (بلا طلب)، ويُحكم بعدم الوجود بعد فحص كل الحوافظ."""
    if from_triage:
        ask = None
    items = portfolios(base)
    prev = data.get('main_contract') or {}
    sig = _sig(items)
    if not force and prev.get('sig') == sig and (prev.get('found') or prev.get('complete')):
        return prev
    if not items:
        rec = {'found': False, 'searched': False, 'sig': sig, 'complete': True, 'message': 'لا حوافظ بعد', 'at': _now()}
        data['main_contract'] = rec
        return rec
    checked, notes = [], []
    for it in items:
        cand = it['sort_contract'] if (it['sort_contract'] or {}).get('found') else None
        c = verify(cand, it['text']) if cand else None
        if (c is None or not c['verified']) and ask is not None:
            import ai_call_log
            ai_call_log.detail(os.path.basename(it['file']))
            try:
                reply = parse(ask(PROMPT.format(text=it['text'][:MAX_CHARS])))
            except ValueError as e:
                ai_call_log.verdict(False, f'ردّ ليس JSON: {e}')
                raise
            if reply.get('found'):
                c = verify(reply, it['text'])
                ai_call_log.verdict(c['verified'], 'العقد تحقق (التاريخ والقيمة حرفياً في النص)' if c['verified']
                                    else 'رُفض العقد: التاريخ أو القيمة لم يردا حرفياً في نص الحافظة')
            else:
                ai_call_log.verdict(True, 'لا عقد في هذه الحافظة')
        checked.append(it['file'])
        if c is not None and c['verified']:
            c.update(file=it['file'], portfolio_date=it['date'], portfolio_label=it['label'], at=_now())
            rec = {'found': True, 'contract': c, 'searched': True, 'sig': sig, 'checked': checked, 'at': _now(),
                   'complete': True, 'message': ''}
            data['main_contract'] = rec
            _publish(data, c)
            return rec
        if c is not None:
            notes.append(f"{os.path.basename(it['file'])}: عقد لم يُتحقق تاريخه/قيمته حرفياً")
        if ask is None and cand is None and not from_triage:
            break                                           # بلا مزوّد: لا يُحكم بعدم الوجود
    rec = {'found': False, 'searched': True, 'sig': sig, 'checked': checked, 'at': _now(),
           'complete': ask is not None or from_triage,
           'message': '؛ '.join(notes) or ('لم يُعثر على عقد في الحوافظ' if ask is not None or from_triage
                                         else 'لا مزوّد ذكاء متاح للبحث عن العقد')}
    data['main_contract'] = rec
    return rec


def _publish(data, c):
    """يضيف العقد إلى data['contracts']['items'] (بين طرفي الدعوى، متحقَّق) لتستعمله كتابة الموضوع فوراً."""
    import case_contracts as cc
    con = data.setdefault('contracts', {})
    its = [x for x in con.get('items') or [] if x.get('origin') != 'main_contract']
    rec = {'kind': 'عقد' + (f" رقم {c['number']}" if c.get('number') else ''), 'date': c['date'], 'parties': c['parties'],
           'scope_of_work': c['scope'], 'value': c['value'], 'duration': c['duration'], 'summary': c['summary'],
           'doc': os.path.basename(c['file']), 'file': c['file'], 'md': cf.md_rel(c['file']), 'page': c.get('page'),
           'between_litigants': True, 'in_claim': None, 'claim_reason': '', 'origin': 'main_contract',
           'checks': {'date': c['checks']['date'], 'value': c['checks']['value'], 'page': None},
           'on_page': True, 'scope': cc.SCOPE_IN, 'scope_reason': 'العقد من أقدم حافظة (البحث عن العقد)',
           'verified': True, 'evidence': where(c)}
    con['items'] = [rec] + its


def republish(data):
    """بعد case_contracts.extract (يستبدل القائمة): يعيد العقد المعتمد من أقدم حافظة إليها."""
    mc = data.get('main_contract') or {}
    if mc.get('found'):
        _publish(data, mc['contract'])


def where(c):
    bits = []
    if c.get('doc_no'):
        bits.append(f"المستند رقم ({c['doc_no']})")
    bits.append(f"بـ{os.path.splitext(os.path.basename(c.get('file') or ''))[0]}")
    if c.get('page'):
        bits.append(f"صفحة {c['page']}")
    return ' '.join(bits)


def short(c):
    bits = ['عقد' + (f" رقم {c['number']}" if c.get('number') else '')]
    if c.get('date'):
        bits.append(f"مؤرخ {c['date']}")
    if c.get('value'):
        bits.append(f"بقيمة {c['value']}")
    return ' '.join(bits) + f" — {where(c)}"
