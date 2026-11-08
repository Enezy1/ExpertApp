# ===== case_minutes_ai.py — استخراج الجلسات من نصوص المحاضر بالذكاء الاصطناعي ثم تحقق الكود (2026-10-18) =====
# طلب واحد بنصوص كل المحاضر (markdown/الفقرات المقروءة) إلى مزوّد «استخراج» (جيميناي بحسب جدول المزوّدين):
#   لكل محضر: رقمه، تاريخ الجلسة، الحاضرون والمتخلفون، الانتقال/المعاينة/الشهود فقط (لا سرد لما جرى؛ النص من الصيغة).
# الكود لا يقبل إلا ما يثبت من النص: كل حضور/غياب/انتقال/شهود يلزمه «دليل» = اقتباس يرد حرفياً (بعد التطبيع) في نص
# ذلك المحضر، والتاريخ يجب أن يرد في نصه. ما لم يثبت يُهمل ويُذكر في unverified (لا تخمين).
# النتيجة مخزّنة ببصمة النصوص فلا يتكرر الطلب لنصوص لم تتغيّر.
import hashlib
import json
import re

MAX_CHARS_PER_MINUTE = 6000
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def _norm(t):
    import case_procedures as cp
    return ' '.join(cp.norm_ar((t or '').translate(_DIGITS)).replace('ـ', '').split())


def text_key(items):
    return hashlib.sha1(json.dumps(items, ensure_ascii=False).encode('utf-8')).hexdigest()


def build_prompt(items, parties):
    blocks = '\n\n'.join(f"[{it['ref']}] (الملف: {it['name']})\n{it['text'][:MAX_CHARS_PER_MINUTE]}" for it in items)
    return (
        "أنت مساعد خبير قضائي. أمامك نصوص محاضر أعمال الخبرة لقضية واحدة. استخرج من كل محضر ما ورد فيه فقط، "
        "بلا استنتاج ولا تخمين. أعد JSON فقط بهذا الشكل:\n"
        '{"minutes":[{"ref":"M1","number":2,"date":"06/07/2026",'
        '"present":[{"party":"اسم الطرف كما في القائمة","evidence":"اقتباس حرفي من المحضر"}],'
        '"absent":[{"party":"…","evidence":"اقتباس حرفي"}],'
        '"visit":{"yes":false,"evidence":""},"inspection":{"yes":false,"evidence":""},'
        '"witnesses":{"yes":false,"evidence":""},'
        '"booking":{"date":"","evidence":""}}]}\n'
        "القواعد: (1) evidence اقتباس حرفي متصل من نص ذلك المحضر نفسه (5–15 كلمة)، وإلا لا تذكر البند. "
        "(2) الغياب فقط إن نصّ المحضر على عدم حضور الطرف («لم يحضر»، «تخلف»…)، والخانة الفارغة ليست غياباً. "
        "(3) التاريخ كما في المحضر dd/mm/yyyy، ولا تكتب تاريخاً غير وارد فيه. "
        "booking: إن نصّ المحضر على حجز الدعوى للتقرير فاكتب تاريخ الحجز كما ورد واقتباس الجملة، وإلا اتركه فارغاً. "
        "(4) الأطراف من هذه القائمة فقط: "
        f"{json.dumps(parties, ensure_ascii=False)}\n\nالمحاضر:\n{blocks}")


def _parse(raw):
    if isinstance(raw, dict):
        return raw
    t = (raw or '').strip()
    m = re.search(r'\{.*\}', t, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}


def _proven(evidence, norm_text):
    ev = _norm(evidence)
    return len(ev.split()) >= 3 and ev in norm_text


def verify(raw, items, parties):
    """يحوّل ردّ النموذج إلى سجلات متحقَّق منها. يرجع (records, unverified[نصوص])."""
    import case_procedures as cp
    by_ref = {it['ref']: it for it in items}
    norm_parties = [cp.norm_ar(p) for p in parties]
    recs, bad = [], []
    for m in (_parse(raw).get('minutes') or []):
        it = by_ref.get(str(m.get('ref') or ''))
        if not it:
            continue
        nt = _norm(it['text'])
        rec = {'ref': it['ref'], 'name': it['name'], 'path': it['path'], 'number': None, 'date': '', 'booking': '',
               'present': [], 'absent': [], 'events': '',          # لا نطلب «ما جرى»: الإجراءات من الصيغة لا من سرد
               'visit': None, 'inspection': None, 'witnesses': None}
        try:
            n = int(str(m.get('number') or '').translate(_DIGITS))
            if re.search(rf'(?<!\d){n}(?!\d)', nt):
                rec['number'] = n
        except ValueError:
            pass
        d = cp.minute_date([str(m.get('date') or '')])
        if d:
            y, mo, dd = d.split('-')
            if any(cp.minute_date([s]) == d for s in re.findall(r'\d{1,4}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{1,4}', it['text'].translate(_DIGITS))):
                rec['date'] = d
            else:
                bad.append(f"{it['name']}: التاريخ {m.get('date')} لا يرد في المحضر")
        for key in ('present', 'absent'):
            for p in m.get(key) or []:
                name, ev = str((p or {}).get('party') or ''), str((p or {}).get('evidence') or '')
                idx = next((i for i, np_ in enumerate(norm_parties) if np_ and (np_ in cp.norm_ar(name) or cp.norm_ar(name) in np_)), None)
                if idx is None:
                    bad.append(f"{it['name']}: طرف غير معروف «{name}»")
                elif not _proven(ev, nt):
                    bad.append(f"{it['name']}: {('حضور' if key == 'present' else 'غياب')} {name} بلا دليل حرفي")
                else:
                    rec[key].append({'index': idx, 'evidence': ev})
        bk = m.get('booking') or {}
        if isinstance(bk, dict) and bk.get('date'):
            bd = cp.minute_date([str(bk.get('date'))])
            ev = str(bk.get('evidence') or '')
            if bd and 'حجز' in _norm(ev) and _proven(ev, nt) and booking_date_in(it['text'], bd):
                rec['booking'] = bd
            else:
                bad.append(f"{it['name']}: تاريخ الحجز {bk.get('date')} بلا دليل حرفي")
        for key in ('visit', 'inspection', 'witnesses'):
            v = m.get(key) or {}
            if isinstance(v, dict) and v.get('yes'):
                if _proven(v.get('evidence') or '', nt):
                    rec[key] = v.get('evidence')
                else:
                    bad.append(f"{it['name']}: {key} بلا دليل حرفي")
        recs.append(rec)
    return recs, bad


def booking_date_in(text, iso):
    """التاريخ iso يرد حرفياً في نص المحضر (بأي صيغة يقرؤها minute_date)."""
    import case_procedures as cp
    t = (text or '').translate(_DIGITS)
    return any(cp.minute_date([s]) == iso for s in re.findall(r'\d{1,4}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{1,4}', t))


_BOOK_RX = re.compile(r'حجز\w*\s+(?:ال)?(?:دعوى|قضية|الدعوي|الدعوة)?\s*(?:لل|ل)?\s*تقرير[^\n.]{0,60}?'
                      r'(\d{1,4}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{1,4})|'
                      r'(\d{1,4}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{1,4})[^\n.]{0,40}?حجز\w*\s+[^\n.]{0,30}?تقرير')


def booking_by_rules(text):
    """تاريخ الحجز من جملة «حجز الدعوى للتقرير … بتاريخ …» في المحضر (ISO) أو ''."""
    import case_procedures as cp
    t = ' '.join((text or '').translate(_DIGITS).replace('ـ', '').split())
    for m in _BOOK_RX.finditer(t):
        d = cp.minute_date([m.group(1) or m.group(2)])
        if d:
            return d
    return ''


def booking_from_minutes(minutes, texts, ai=None):
    """تاريخ الحجز من المحاضر عند غيابه في النظام: القواعد أولاً ثم الذكاء (كلاهما متحقَّق حرفياً).
    يرجع {'date','minute','name','method','note'} من أحدث محضر ينص على الحجز، أو {}."""
    found = []
    for m in minutes:
        t = '\n'.join(texts.get(m['path']) or [])
        d = booking_by_rules(t)
        if d:
            found.append((d, m.get('no'), m['name'], 'rules'))
    if not found and ai:
        for r in ai.get('records') or []:
            if r.get('booking'):
                found.append((r['booking'], r.get('number'), r['name'], 'ai'))
    if not found:
        return {}
    d, no, name, how = max(found, key=lambda x: (x[0], x[1] or 0))
    label = f'رقم {no}' if no else f'«{name}»'
    return {'date': d, 'minute': no, 'name': name, 'method': how, 'note': f'مأخوذ من المحضر {label}'}


def extract(proc, minutes, texts, parties, ask):
    """يشغّل الطلب (أو يعيد المخزَّن ببصمة النصوص) ويحفظ proc['minutes_ai']. يرجع السجل أو None."""
    items = []
    for i, m in enumerate(minutes, 1):
        t = '\n'.join(texts.get(m['path']) or [])
        if t.strip():
            items.append({'ref': f'M{i}', 'name': m['name'], 'path': m['path'], 'text': t})
    if not items or not parties:
        return None
    key = text_key([[it['name'], it['text']] for it in items] + [parties])
    prev = proc.get('minutes_ai') or {}
    if prev.get('key') == key and prev.get('records') is not None:
        return prev
    if ask is None:
        return prev or None
    try:
        raw = ask(build_prompt(items, parties))
    except Exception as e:
        proc['minutes_ai_error'] = f'تعذّر استخراج الجلسات من المحاضر بالذكاء الاصطناعي: {e}'
        return prev or None
    recs, bad = verify(raw, items, parties)
    import ai_call_log
    ai_call_log.verdict(True, f'{len(recs)} محضراً مقروءاً' + (f'؛ لم يتحقق: {len(bad)}' if bad else ''))
    proc.pop('minutes_ai_error', None)
    proc['minutes_ai'] = {'key': key, 'records': recs, 'unverified': bad}
    return proc['minutes_ai']


def merge_attendance(att, ai):
    """يكمل نتيجة الحضور بما ثبت بدليل حرفي فقط، لمن لم يتأكد بالقواعد/الخبير. يرجع عدد ما أُكمل."""
    if not ai or not att.get('result'):
        return 0
    n = 0
    for i, r in enumerate(att['result']):
        if r.get('certain'):
            continue
        hit = next(((rec, p) for rec in ai['records'] for p in rec['present'] if p['index'] == i), None)
        if hit:
            r.update(present=True, certain=True, where=hit[0]['name'], how='ذكاء اصطناعي (بدليل من المحضر)')
            n += 1
            continue
        miss = [rec for rec in ai['records'] if any(p['index'] == i for p in rec['absent'])]
        if miss and len(miss) == len(ai['records']):          # غياب منصوص عليه في كل المحاضر المقروءة
            r.update(present=False, certain=True, where='', how='ذكاء اصطناعي (بدليل من المحضر)')
            n += 1
    att['extracted'] = bool(att.get('parties')) and all(r['certain'] for r in att['result'])
    return n


def merge_extras(extras, ai):
    """الانتقال/المعاينة/الشهود الثابتة بدليل وتاريخ تُضاف إلى extras إن لم تكن فيه بتاريخها."""
    if not ai:
        return extras
    for rec in ai['records']:
        if not rec['date']:
            continue
        present = [p['index'] for p in rec['present']] or None
        for key, src in (('transfer', 'visit'), ('transfer', 'inspection'), ('witness', 'witnesses')):
            if rec[src] and not any(x.get('date') == rec['date'] for x in extras.get(key) or []):
                extras.setdefault(key, []).append({'date': rec['date'], 'present': present, 'how': 'ai'})
    return extras
