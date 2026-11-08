# ===== referral_pick.py — تحديد حكم الإحالة للخبرة بدقة (2026-10-18) =====
# المعتمد دائماً: أحدث حكم يحيل الدعوى للخبرة (قد تُستأنف القضية ثم تُحال من الاستئناف، أو العكس) —
# فإن وُجد حكم إحالة من الاستئناف لا يُعتمد حكم الكلية الأقدم.
# الترتيب:
#   1) حكم الإحالة الذي جلبه النظام (حكم_الإحالة/) إن احتوى مأمورية ← «system».
#   2) وإلا: كل مستندات القضية المحوَّلة مرتبة تاريخياً، ويؤخذ أحدثها مما يحيل للخبراء (نصه فيه ندب/إحالة للخبراء
#      ومأمورية تُستخرج) ← «auto» (حُدِّد تلقائياً، تأكد منه).
#   3) وإلا: قائمة الأسماء والتواريخ إلى الذكاء الاصطناعي يسأله أيها حكم الخبرة الأخير، ثم يتحقق الكود أن المختار
#      موجود فعلاً ويحتوي مأمورية ← «ai» (حُدِّد تلقائياً، تأكد منه).
# النتيجة في data['judgment_pick'] وتُكتب في ذاكرة_القضية.md (قسم بيانات القضية).
import json
import os
import re
from datetime import datetime

import case_folder as cf

AUTO_NOTE = 'حُدِّد تلقائياً، تأكد منه'
_REFER = re.compile(r'(?:بندب|ندب|بإحالة|باحالة|إحالة|احالة)\s+(?:الدعوى\s+(?:إلى|الى)\s+)?(?:إدارة|ادارة)\s+الخبراء'
                    r'|(?:إدارة|ادارة)\s+الخبراء\s+(?:لتندب|لندب|ليندب)')
_APPEAL = re.compile(r'محكمة\s+الاستئناف|الاستئناف\s+رقم|استئناف(?:ية)?\b|المستأنف')
_TAMYEEZ = re.compile(r'محكمة\s+التمييز|الطعن\s+بالتمييز')
_DATE_IN_NAME = re.compile(r'(\d{1,4})[-_/.](\d{1,2})[-_/.](\d{1,4})')
_JUDG_DATE = re.compile(r'(?:بجلسة|صدر\s+(?:هذا\s+)?الحكم\s+(?:علناً\s+)?(?:بجلسة|في)|بتاريخ)\s*[:：]?\s*'
                        r'(?:\S+\s+){0,3}?(\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{4}|\d{4}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{1,2})')
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def _iso(text):
    import case_procedures as cp
    return cp.minute_date([text or ''])


def doc_date(rel, md):
    """تاريخ المستند: من اسمه (… 2026-03-01.pdf كما يسمّيه الجلب من النظام) وإلا من «صدر بجلسة/بتاريخ» في نصه."""
    m = _DATE_IN_NAME.search(os.path.basename(rel))
    if m:
        d = _iso(m.group(0).replace('_', '-'))
        if d:
            return d
    t = (md or '').translate(_DIGITS)
    hits = [_iso(x) for x in _JUDG_DATE.findall(t)]
    hits = [h for h in hits if h]
    if hits:
        return max(hits)                  # تاريخ صدور الحكم آخر ما يُذكر غالباً
    return _iso('\n'.join(t.splitlines()[:30]))


def court_level(md):
    """3 تمييز، 2 استئناف، 1 كلية — لترجيح المتساويين تاريخاً."""
    head = (md or '')[:3000]
    if _TAMYEEZ.search(head):
        return 3
    if _APPEAL.search(head):
        return 2
    return 1


def is_referral(md):
    """حكم يحيل للخبرة: علامة «حكم خبير (حكم الإحالة)» في أول سطر (المسحوب من تفاصيل القضية) أو صيغة الندب، مع مأمورية."""
    import case_subject_mission as sm
    import doc_header
    md = doc_header.strip(md or '')                      # رأس نوع المستند قبل العلامة لا يخفيها
    marked = md.lstrip().startswith(cf.REFERRAL_MARK)
    return bool(marked or _REFER.search(md or '')) and bool(sm.extract_mission(md))


def _read(base, rel):
    try:
        with open(os.path.join(base, rel), encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def documents(base):
    """[{file, md_text, date, level, referral}] لكل أصل محوَّل، مرتبة تاريخياً (الأقدم أولاً)."""
    out = []
    for rel, e in cf.load_manifest(base)['files'].items():
        if e.get('state') != 'done' or not os.path.exists(os.path.join(base, rel)):
            continue
        md = _read(base, e.get('md') or cf.md_rel(rel))
        if not md.strip():
            continue
        out.append({'file': rel, 'text': md, 'date': doc_date(rel, md), 'level': court_level(md),
                    'referral': is_referral(md), 'sha1': e.get('sha1', '')})
    out.sort(key=lambda d: (d['date'] or '0000', d['level'], d['file']))
    return out


def latest_referral(docs):
    """أحدث حكم يحيل للخبرة؛ تساوي التاريخ ← الأعلى درجة (الاستئناف قبل الكلية)."""
    refs = [d for d in docs if d['referral']]
    return max(refs, key=lambda d: (d['date'] or '0000', d['level'])) if refs else None


def ask_prompt(docs):
    lines = '\n'.join(f"{i}. {os.path.basename(d['file'])} — التاريخ: {d['date'] or 'غير معروف'} — "
                      f"{' '.join(re.sub(r'<!--.*?-->', ' ', d['text']).split())[:160]}" for i, d in enumerate(docs, 1))
    return ("هذه قائمة مستندات قضية (الاسم، التاريخ، أول النص). أيها حكم الإحالة الأخير إلى إدارة الخبراء (الحكم الذي ندب "
            "الخبير وحدد مأموريته)؟ إن وُجد حكم استئناف يحيل للخبرة فهو المعتمد لا حكم الكلية الأقدم. "
            'أعد JSON فقط: {"index": رقم المستند، "reason": "سبب موجز"} أو {"index": null} إن لم يوجد.\n\n' + lines)


def _parse_index(raw):
    m = re.search(r'\{.*\}', raw if isinstance(raw, str) else json.dumps(raw or {}), re.S)
    try:
        v = json.loads(m.group(0)).get('index') if m else None
        return int(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _now():
    return datetime.now().isoformat(timespec='seconds')


def pick(base, data, ask=None):
    """يحدد حكم الإحالة ويسجّله في data['judgment_pick'] = {file, sha1, date, method, note, verified, reason}.
    يرجع السجل أو None. لا يلمس اختياراً أكّده الخبير (confirmed)."""
    prev = data.get('judgment_pick') or {}
    if prev.get('confirmed') and os.path.exists(os.path.join(base, prev.get('file') or '')):
        return prev
    docs = documents(base)
    rec = None
    sys_docs = [d for d in docs if cf.kind_of(d['file']) == cf.JUDGMENT]
    from_system = [d for d in sys_docs if d['referral']]
    best = latest_referral(docs)
    if from_system:
        top = latest_referral(from_system)
        if best is None or (best['date'] or '') <= (top['date'] or '') or best['file'] == top['file']:
            rec = {'file': top['file'], 'method': 'system', 'note': '', 'reason': 'حكم الإحالة من النظام'}
    if rec is None and best is not None:
        why = 'أحدث مستند يحيل للخبرة بعد ترتيب مستندات القضية تاريخياً'
        if from_system:
            why += ' (أحدث من حكم الإحالة المجلوب من النظام)'
        rec = {'file': best['file'], 'method': 'auto', 'note': AUTO_NOTE, 'reason': why}
    if rec is None and sys_docs:                # حكم في مجلد حكم_الإحالة لم تُعرف صيغة مأموريته ← يُعتمد كما هو بصمت
        top = max(sys_docs, key=lambda d: (d['date'] or '0000', d['level']))
        rec = {'file': top['file'], 'method': 'system', 'note': '', 'reason': 'حكم الإحالة من النظام'}
    if rec is None and docs and ask is not None:
        try:
            idx = _parse_index(ask(ask_prompt(docs)))
        except Exception as e:
            idx, data['judgment_pick_error'] = None, f'تعذّر سؤال الذكاء الاصطناعي: {e}'
        import ai_call_log
        if idx is None or not 1 <= idx <= len(docs):
            ai_call_log.verdict(idx is None, 'لا حكم إحالة بين المستندات' if idx is None else 'رقم مستند خارج القائمة')
        if idx is not None and 1 <= idx <= len(docs):
            import case_subject_mission as sm
            d = docs[idx - 1]
            has_mission = os.path.exists(os.path.join(base, d['file'])) and sm.extract_mission(d['text'])
            ai_call_log.verdict(bool(has_mission), 'المستند المختار يحتوي مأمورية' if has_mission
                                else 'المستند المختار لا يحتوي مأمورية')
            if has_mission:
                rec = {'file': d['file'], 'method': 'ai', 'note': AUTO_NOTE,
                       'reason': 'اختاره الذكاء الاصطناعي من قائمة المستندات وتحقق البرنامج أنه يحتوي مأمورية'}
            else:
                data['judgment_pick_error'] = (f"اختار الذكاء الاصطناعي «{os.path.basename(d['file'])}» لكنه لا يحتوي "
                                               'مأمورية — لم يُعتمد')
    if rec is None:
        if prev and not os.path.exists(os.path.join(base, prev.get('file') or '')):
            data.pop('judgment_pick', None)
        return None
    d = next(x for x in docs if x['file'] == rec['file'])
    rec.update(sha1=d['sha1'], date=d['date'], level=d['level'], verified=True, at=_now())
    if (prev.get('file'), prev.get('sha1')) != (rec['file'], rec['sha1']):
        data['judgment_pick'] = rec
        data.pop('judgment_pick_error', None)
        try:
            import case_memory
            case_memory.update_section(base, data, 'case')
        except Exception:
            pass
    return data.get('judgment_pick')


def confirm(base, data):
    """الخبير تأكد من الحكم المحدَّد تلقائياً ← يزول الخط الأحمر."""
    rec = data.get('judgment_pick') or {}
    if rec:
        rec.update(confirmed=True, note='')


def line(data):
    """(نص، أحمر؟) لعرض بيانات القضية، أو ('', False)."""
    rec = data.get('judgment_pick') or {}
    if not rec:
        return ('', False)                       # أخطاء الاختيار لا تُعرض للخبير (تبقى في case.json للتشخيص)
    name = os.path.basename(rec['file'])
    when = f" ({rec['date'][8:10]}/{rec['date'][5:7]}/{rec['date'][:4]})" if rec.get('date') else ''
    if rec.get('note'):
        return (f"حكم الإحالة: {name}{when} — اختاره البرنامج، والتأكيد للخبير", False)   # تنبيه لا أحمر
    return (f'حكم الإحالة: {name}{when}', False)


# رقم الدعوى في التقرير يؤخذ من حكم الإحالة نفسه (كما في المحضر) لا من نظام الخبراء.
_CASE_NO = re.compile(r'(?:في\s+)?(?:الدعوى|القضية|الاستئناف|الطعن)\s+(?:رقم|بالرقم)\s*[:：]?\s*'
                      r'(\d{1,6}\s*/\s*\d{4}(?:\s*[؀-ۿ]+){0,3}(?:\s*/\s*\d{1,3})?)')


def case_number_from_text(md):
    """«1234 / 2025 تجاري كلي / 7» من نص الحكم، أو ''."""
    text = re.sub(r'<!--.*?-->', ' ', md or '', flags=re.S).translate(_DIGITS)
    m = _CASE_NO.search(text[:6000])
    if not m:
        return ''
    num = ' '.join(m.group(1).split())
    num = re.sub(r'\s+(?:والمقام[ةه]?|المقام[ةه]?|المرفوع[ةه]?|من|ضد|بين|بتاريخ|بجلسة)(?:\s.*)?$', '', num)
    return num.strip()


def case_number(base, data):
    """رقم الدعوى بالأولوية: نص حكم الإحالة المعتمد ← المحفوظ محلياً من الحكم (case_db) ← ''."""
    rec = (data or {}).get('judgment_pick') or {}
    if base and rec.get('file'):
        e = cf.load_manifest(base)['files'].get(rec['file']) or {}
        n = case_number_from_text(_read(base, e.get('md') or cf.md_rel(rec['file'])))
        if n:
            return n
    try:
        import case_db
        row = case_db.get_case((data or {}).get('caso_no') or '') or {}
        return (row.get('court_case_number') or '').strip()
    except Exception:
        return ''
