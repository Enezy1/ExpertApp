# ===== case_subject_mission.py — خطوتا «الموضوع» و«المأمورية» (المرحلة 2ح) =====
# منطق صرف بلا واجهة. المأمورية من حكم الإحالة في مجلد القضية (case_folder/markdown)، وcase_db.mission_text احتياطي.
# الموضوع: من صحيفة الدعوى حرفياً بقالب ثابت — قضايا الاتصالات (المدعية من [telecom_companies]) بصيغتها
# (case_subject_telecom) وغيرها بصيغة العقد العام (case_subject_contract). لا ملخص حر: ما لم يتحقق «[يُكتب]».
# المأمورية: تُعرض للتأكيد (needs_input)
# مقسّمة إلى نقاط يعدّلها الخبير، ثم confirm_mission ← reviewed. نقاط المأمورية بمعرّف ثابت id
# (الرقم n للعرض فقط) حتى لا تنكسر إحالات البنود عند إعادة الترقيم.
import re

import case_memory
import case_model as cm
import case_subject_contract as sc
import case_subject_ai as sa
import case_subject_telecom as st
import case_workspace as cw

_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_ORDINAL_STEMS = ('أول', 'ثاني', 'ثالث', 'رابع', 'خامس', 'سادس', 'سابع', 'ثامن', 'تاسع', 'عاشر')
_TAIL = r'[اًىٌٍَُِّ]{0,3}'
_NUM_RE = re.compile(r'(?<![\w/.,:])(\d{1,2})[ \t]*[-–—.)][ \t]+(?=\S)')
_ORD_RE = [
    re.compile(r'(?<![\w])' + ('[أإا]ول' if s == 'أول' else s) + _TAIL + r'(?:[ \t]*[:\-–—.)،][ \t]*|[ \t]*(?=\n))')
    for s in _ORDINAL_STEMS
]
_BULLET_RE = re.compile(r'(?m)^[ \t]*[-•*▪●][ \t]+(?=\S)')


def _norm(text):
    return (text or '').translate(_AR_DIGITS).replace('\r\n', '\n').replace('\r', '\n').strip()


def _run_from_one(markers):
    """أطول تسلسل متتالٍ 1،2،3… من قائمة (بداية، نهاية، رقم)؛ فارغ إن لم يبدأ بـ 1."""
    run, want = [], 1
    for m in markers:
        if m[2] == want:
            run.append(m)
            want += 1
    return run


def _split_by(text, markers):
    out = []
    for i, (_, end, _n) in enumerate(markers):
        stop = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        out.append(text[end:stop])
    return out


def _clean_point(s):
    return re.sub(r'\s+', ' ', s).strip(' \t\n؛;,،.-–—')


def split_points(raw):
    """يقسّم نص المأمورية إلى نقاط: أرقام (1- / 1. / 1) ثم أولاً/ثانياً ثم نقاط القوائم؛
    وإلا نقطة واحدة. النص قبل أول علامة (مقدمة) لا يُعدّ نقطة. يرجع قائمة نصوص."""
    text = _norm(raw)
    if not text:
        return []
    nums = _run_from_one([(m.start(), m.end(), int(m.group(1))) for m in _NUM_RE.finditer(text)])
    ords = []
    for i, rx in enumerate(_ORD_RE, 1):
        m = rx.search(text)
        if m:
            ords.append((m.start(), m.end(), i))
    ords.sort()
    ords = _run_from_one(ords)
    for markers in (nums, ords):
        if len(markers) >= 2 or (markers and not text[:markers[0][0]].strip()):
            pts = [_clean_point(p) for p in _split_by(text, markers)]
            return [p for p in pts if p]
    bullets = [(m.start(), m.end(), 0) for m in _BULLET_RE.finditer(text)]
    if len(bullets) >= 2:
        pts = [_clean_point(p) for p in _split_by(text, bullets)]
        return [p for p in pts if p]
    return [_clean_point(text)]


# ---------- الحفظ ----------

def _save(base, data, *sids):
    """case.json أولاً (المصدر)، ثم تحديث الذاكرة. فشل الذاكرة لا يُفشل الخطوة: يرجع تحذيراً أو ''."""
    cw.write_case_json(base, data)
    try:
        case_memory.update_section(base, data, 'status', *sids)
        return ''
    except Exception as e:
        return f'تعذّر تحديث ملف الذاكرة: {e}'


def _default_get_case(caso_no):
    import case_db
    return case_db.get_case(caso_no)


def _row(data, get_case):
    return (get_case or _default_get_case)(data['caso_no']) or {}


# ---------- الخطوة 1: الموضوع ----------

STYLE = 'ai'          # 'ai' = كتابة بالذكاء بأسلوب نماذج الخبير؛ 'formula' = القوالب القديمة (للاختبارات القديمة فقط)
FORMULAS = {
    'ai': (None, 'صياغة بأسلوب النماذج'),
    'telecom': (st.build_subject, 'صيغة الاتصالات'),
    'contract': (sc.build_subject, 'صيغة العقد العام'),
}


def _run_subject_formula(base, data, row, ask, claim_fn, formula, hint=''):
    """القالب الثابت من صحيفة الدعوى حرفياً، والناقص «[يُكتب]» (formula: telecom | contract).
    ناقص أو بلا صحيفة ← needs_input والنص محفوظ لتكمله في نافذة المراجعة؛ فشل الجلب/الذكاء ← failed (إعادة محاولة)."""
    build, label = FORMULAS[formula]
    if formula == 'ai':
        build = lambda plaint, defendants, ask_: sa.build_subject(          # noqa: E731
            plaint, defendants, ask_, plaintiffs=row.get('plaintiffs') or (data.get('case') or {}).get('plaintiffs'),
            hint=hint, case_type=data.get('subject_type') if data.get('subject_type_chosen') else '', contracts=data)
    defendants = row.get('defendants') or (data.get('case') or {}).get('defendants') or []
    plaint = None
    st._tls.info = None
    if claim_fn is not None:
        try:
            plaint = claim_fn()
        except Exception as e:
            cm.set_step(data, 'subject', 'failed', f'تعذّر جلب صحيفة الدعوى: {e}')
            _save(base, data)
            return 'failed'
    if not (plaint or '').strip():
        built = build('', defendants, None)
        if formula == 'ai':
            built['text'] = ''
        why = ('لا يتوفر اتصال لجلب صحيفة الدعوى' if claim_fn is None
               else 'لم تُوجد صحيفة الدعوى أو لم يُقرأ نصها')
        data['subject'] = built['text']
        cm.set_step(data, 'subject', 'needs_input', f'{why} — أكمل الموضوع ({label})')
        _save(base, data, 'case')
        return 'needs_input'
    if ask is None:
        import case_research
        ask = case_research.default_ask
    import doc_router
    info = st.last_read()
    if info:                                      # محرّك قراءة الصحيفة يُسجَّل في case.json ويُفصح عنه إن لم يكن Gemini
        data.setdefault('engines', {})['claim'] = {
            'engine': info['engine'], 'label': info['label'], 'skipped': [list(x) for x in info['skipped']]}
    qw = doc_router.quality_warning(doc_router.T_PLAINT, plaint)
    if qw:
        data['subject_quality_warning'] = qw
    else:
        data.pop('subject_quality_warning', None)
    try:
        built = build(plaint, defendants, ask)
    except Exception as e:
        cm.set_step(data, 'subject', 'failed', f'تعذّر استخراج بيانات الصحيفة: {e}')
        _save(base, data)
        return 'failed'
    data['subject'] = built['text']
    data['subject_alerts'] = [list(a) for a in built.get('alerts') or []]
    if formula == 'ai':
        return _finish_ai_subject(base, data, built, label, qw)
    notes = f' — {built["note"]}' if built['note'] else ''
    fixes = built.get('ocr_fixes') or []
    if fixes:                                      # يُسجَّل أن التصحيح تم (ما صُحّح وكم مرة)
        data['subject_ocr_fixes'] = [[b, g, n] for b, g, n in fixes]
        notes += ' — صُحِّحت أخطاء OCR واضحة في الصحيفة قبل الاقتباس: ' + '، '.join(
            f'«{b}»←«{g}» ({n})' for b, g, n in fixes)
    else:
        data.pop('subject_ocr_fixes', None)
    if qw:
        notes += f' — ⚠ {doc_router.WEAK_MESSAGE}'
    if any(a[0] == 'red' for a in data['subject_alerts']):
        notes += ' — ⚠ تعارض في مبلغ: راجع التنبيه الأحمر'
    if built['missing']:
        cm.set_step(data, 'subject', 'needs_input',
                    f'{label} — لم يرد في الصحيفة أو لم يُتحقق منه: {"، ".join(built["missing"])}'
                    f' (تُرك «{st.TODO}»){notes}')
    elif qw:
        cm.set_step(data, 'subject', 'needs_input', f'{label} من صحيفة الدعوى{notes}')
    else:
        cm.set_step(data, 'subject', 'done', f'{label} من صحيفة الدعوى{notes}')
    _save(base, data, 'case')
    return cm.state(data, 'subject')


def _finish_ai_subject(base, data, built, label, qw):
    """حالة الخطوة بعد الكتابة بالذكاء: ما لم يتحقق/تعارض مبلغ/غياب المطالبة ← تحتاج مدخلاً؛ غياب اختياري (عقد/تاريخ…) ← تُكتب."""
    miss = {'unverified': built.get('unverified') or [], 'absent': built.get('absent') or [],
            'models': built.get('models') or []}
    if built.get('type'):
        data['subject_type'] = built['type']                       # يحدّد صيغة الإجراءات أيضاً (استئناف…)
        data['subject_type_unclear'] = bool(built.get('type_unclear'))
    data['subject_missing'] = miss
    data['subject_facts'] = built.get('facts') or {}          # لإعادة الصياغة لاحقاً من الحقائق نفسها
    data['subject_edited'] = False
    core = {sa.FACT_LABELS[k] for k in sa.CORE}
    # ما كتبه البرنامج يُعدّ صحيحاً؛ ما لم يرد/لم يُتحقق تنبيه بسيط لا يحجب (والخطأ يُصلح بإعادة الكتابة)
    blocked = not built['text']
    note = ''
    fixes = built.get('ocr_fixes') or []
    if fixes:
        data['subject_ocr_fixes'] = [[b, g, n] for b, g, n in fixes]
        note += ' — صُحِّحت أخطاء OCR واضحة: ' + '، '.join(f'«{b}»←«{g}» ({n})' for b, g, n in fixes)
    else:
        data.pop('subject_ocr_fixes', None)
    if qw:
        note += f' — ⚠ {doc_router_weak()}'
    if built.get('type_unclear'):
        why_t = f"نوع القضية غير واضح من الصحيفة والعقد (اخترنا «{sa.CASE_TYPES.get(built.get('type'), '')}») — حدّده من «نوع القضية»"
        cm.set_step(data, 'subject', 'needs_input', f'{label} — {why_t}{note}')
    elif blocked:
        why = '؛ '.join(x for x in (
            ('لم يُتحقق منه: ' + '، '.join(miss['unverified'])) if miss['unverified'] else '',
            ('لم يرد: ' + '، '.join(miss['absent'])) if miss['absent'] else '') if x)
        cm.set_step(data, 'subject', 'needs_input', f'{label} — {why or "لا نص"}{note}')
    else:
        cm.set_step(data, 'subject', 'done', f'{label} من صحيفة الدعوى{note}')
    _save(base, data, 'case')
    return cm.state(data, 'subject')


def set_subject_type(base, data, case_type, **kw):
    """الخبير يحدّد نوع القضية (مفتاح من sa.CASE_TYPES) ← يُعاد توليد الموضوع بنموذج ذلك النوع."""
    if case_type not in sa.CASE_TYPES:
        raise cm.StepError('نوع القضية غير معروف.')
    data['subject_type'], data['subject_type_chosen'] = case_type, True
    data.pop('subject_type_unclear', None)
    return run_subject(base, data, force=True, **kw)


def doc_router_weak():
    import doc_router
    return doc_router.WEAK_MESSAGE


def _run_subject_telecom(base, data, row, ask, claim_fn):
    return _run_subject_formula(base, data, row, ask, claim_fn, 'telecom')


def run_subject(base, data, get_case=None, force=False, ask=None, claim_fn=None, companies=None):
    """يملأ الموضوع من صحيفة الدعوى بالقالب: صيغة الاتصالات إن كانت المدعية من [telecom_companies]، وإلا صيغة
    العقد العام (ask: مزوّد الذكاء، claim_fn: دالة تجلب نص الصحيفة). يرجع حالة الخطوة.
    لا يمسّ خطوة مكتملة إلا مع force («إعادة الكتابة» تمرّر force=True)."""
    if cm.state(data, 'subject') in cm.OK_STATES and not force:
        return cm.state(data, 'subject')
    cm.set_step(data, 'subject', 'running')
    try:
        row = _row(data, get_case)
        is_telecom = bool(st.telecom_company(row, data.get('case') or {}, companies))
    except Exception as e:
        cm.set_step(data, 'subject', 'failed', f'تعذّرت قراءة بيانات القضية: {e}')
        _save(base, data)
        return 'failed'
    if STYLE == 'ai':
        return _run_subject_formula(base, data, row, ask, claim_fn, 'ai', 'اتصالات' if is_telecom else '')
    return _run_subject_formula(base, data, row, ask, claim_fn, 'telecom' if is_telecom else 'contract')


def set_subject(base, data, text):
    """إدخال/تعديل الموضوع يدوياً من الخبير. بعد الاعتماد يعيد الحالة إلى «كُتبت» ويُقدِّم قِدَم المعتمدة عليه
    (cm.stale_labels(data, 'subject') لأسمائها). الاعتماد بزر منفصل (review_subject) فقط."""
    text = (text or '').strip()
    if not text:
        raise cm.StepError('الموضوع فارغ.')
    changed = text != (data.get('subject') or '')
    data['subject'] = text
    if changed:                              # الخبير تولّى النص: ينتهي سطر النواقص وتنبيهات المبالغ السابقة
        data['subject_edited'] = True        # لا يُستبدل تلقائياً أبداً (إلا بزر «إعادة الكتابة» مع تأكيد)
        data.pop('subject_missing', None)
        data['subject_alerts'] = []
    st = cm.state(data, 'subject')
    if st in cm.OK_STATES:
        if changed:
            cm.mark_modified(data, 'subject')
        if st == 'reviewed' and changed:
            cm.set_step(data, 'subject', 'done', 'عُدِّل بعد الاعتماد — اعتمده من جديد')
    else:                                   # pending/failed/blocked/needs_input ← عبر needs_input
        if st != 'needs_input':
            cm.set_step(data, 'subject', 'needs_input')
        cm.set_step(data, 'subject', 'done', 'أدخله الخبير')
    _save(base, data, 'case')
    return cm.state(data, 'subject')


def review_subject(base, data):
    cm.set_step(data, 'subject', 'reviewed')
    _save(base, data)


# ---------- الخطوة 2: المأمورية ----------

def _make_points(texts, mission):
    """يبني نقاطاً بمعرّفات ثابتة: يعيد استخدام id النقطة إن بقي نصها كما هو بنفس الترتيب النسبي."""
    old = {p['text']: p['id'] for p in mission.get('points') or []}
    nid = mission.get('next_id', 1)
    pts, used = [], set()
    for i, t in enumerate(texts, 1):
        pid = old.get(t)
        if pid is None or pid in used:
            pid = f'q{nid}'
            nid += 1
        used.add(pid)
        pts.append({'id': pid, 'n': i, 'text': t})
    mission['points'] = pts
    mission['next_id'] = max(nid, mission.get('next_id', 1))


# ---------- مصدر المأمورية: حكم الإحالة في مجلد القضية (2026-10-18) ----------
# السبب: المأمورية كانت تُقرأ من case_db.mission_text وحده، فحكم الإحالة المرفوع يدوياً إلى المستندات لا يصل إليها.
# الآن: نص حكم الإحالة من markdown المجلد (case_folder) ← المقطع بعد «تكون مهمته/مأموريته» حتى «وصرحت/وحددت/وأبقت…»،
# وcase_db احتياطي فقط. بصمة الملف المصدر في mission['source'] فيُعاد الاستخراج متى تغيّر الملف.

_M_START = re.compile(r'(?:و?ل?تكون|وتتمثل)\s+(?:مهمت|مأموريت|ماموريت)(?:ه|ها)\s*(?:في|هي)?\s*[:：\-–]?\s*'
                      r'|(?:المأمورية|الماموريه|المأموريه|المأمورية)\s+(?:التالية|الآتية|الاتية)\s*[:：\-–]?\s*')
_M_FALLBACK = re.compile(r'(?:و?قبل\s+الفصل\s+في\s+الموضوع\s+)?بندب\s+(?:إدارة|ادارة)\s+الخبراء')
_M_END = re.compile(r'(?:\s|^)(?:و?صرحت\s+(?:له|للخبير|لها)|و?حددت\s+(?:جلسة|لنظر)|و?[أا]بقت\s+الفصل|و?[أا]رجأت'
                    r'|و?قدرت\s+(?:للخبير\s+|لها\s+)?[أا]مانة|و?[أا]لزمت\s+(?:المدعي|المدعية)\s+[أا]مانة)')
MAX_MISSION_CHARS = 6000


def extract_mission(text):
    """نص المأمورية من نص حكم الإحالة (markdown)، أو '' إن لم يُعثر على بدايتها."""
    t = re.sub(r'<!--.*?-->', ' ', text or '', flags=re.S)
    t = re.sub(r'[ \t]+', ' ', t)
    starts = list(_M_START.finditer(t))
    if starts:
        i = starts[-1].end()                     # المنطوق في آخر الحكم
    else:
        fb = list(_M_FALLBACK.finditer(t))
        if not fb:
            return ''
        i = fb[-1].start()
    end = _M_END.search(t, i)
    out = t[i:end.start() if end else i + MAX_MISSION_CHARS].strip(' \n،,.-')
    return out[:MAX_MISSION_CHARS].strip()


def judgment_source(base, data):
    """(مسار الأصل النسبي، sha1، نص markdown) لحكم الإحالة من مجلد القضية، أو (None, '', '')."""
    import os
    import case_folder as cf
    cands = []
    jp = data.get('judgment_pick') or {}
    if jp.get('file'):                           # المحدَّد بـreferral_pick (أحدث حكم يحيل للخبرة) أولاً
        cands.append(jp['file'])
    rec = (data.get('sources') or {}).get('judgment') or {}
    if rec.get('file'):
        cands.append(rec['file'])
    rel, _ = cf.latest_md(base, cf.JUDGMENT)
    if rel:
        cands.append(rel)
    for p in data.get('portfolios') or []:
        for d in p.get('docs') or []:
            if d.get('doc_type') == 'حكم' and (d.get('convert') or {}).get('state') == 'done' and d.get('file'):
                cands.append(d['file'])
    man = cf.load_manifest(base)['files']
    for rel in cands:
        e = man.get(rel) or {}
        md = e.get('md') or cf.md_rel(rel)
        if e.get('state') not in (None, 'done'):
            continue
        for path in (os.path.join(base, md),):
            try:
                with open(path, encoding='utf-8') as f:
                    text = f.read()
            except OSError:
                continue
            if text.strip():
                return rel, e.get('sha1') or '', text
    # حوافظ قديمة: md خارج manifest
    for p in data.get('portfolios') or []:
        for d in p.get('docs') or []:
            if d.get('doc_type') == 'حكم' and d.get('md') and os.path.exists(os.path.join(base, d['md'])):
                with open(os.path.join(base, d['md']), encoding='utf-8') as f:
                    return d['file'], d.get('src_sha1', ''), f.read()
    return None, '', ''


def mission_source_changed(base, data):
    """True إن وُجد حكم إحالة في المجلد بصمته غير المسجّلة لآخر استخراج."""
    rel, sha, text = judgment_source(base, data)
    if not rel:
        return False
    src = (data.get('mission') or {}).get('source') or {}
    return (src.get('file'), src.get('sha1')) != (rel, sha)


def run_mission(base, data, get_case=None, force=False):
    """يقرأ المأمورية من حكم الإحالة في مجلد القضية (وإلا من case_db) ويقسّمها نقاطاً للتأكيد (needs_input)."""
    if cm.state(data, 'mission') in cm.OK_STATES and not force:
        return cm.state(data, 'mission')
    cm.set_step(data, 'mission', 'running')
    raw, source = '', {}
    try:
        rel, sha, text = judgment_source(base, data)
        if rel:
            source = {'file': rel, 'sha1': sha, 'from': 'folder'}
            raw = extract_mission(text)
    except Exception:
        rel = None
    if not raw:
        try:
            raw = (_row(data, get_case).get('mission_text') or '').strip()
            if raw:
                source = dict(source, from_='case_db') if source else {'from': 'case_db'}
        except Exception as e:
            if not source:
                cm.set_step(data, 'mission', 'failed', f'تعذّرت قراءة بيانات القضية: {e}')
                _save(base, data)
                return 'failed'
    m = data['mission']
    m['confirmed'] = False
    m['source'] = source
    m.pop('source_changed', None)
    m.pop('literal_missing', None)
    m.pop('edited', None)
    if not raw:
        cm.set_step(data, 'mission', 'needs_input',
                    'لم أجد المأمورية في حكم الإحالة بمجلد القضية — أضف الحكم أو الصق المأمورية هنا'
                    if source else 'لا يوجد حكم إحالة في مجلد القضية ولا مأمورية محفوظة — أضف الحكم أو الصقها هنا')
    else:
        m['raw'] = raw
        _make_points(split_points(raw), m)
        m['literal_missing'] = literal_check(m['points'], text if source.get('from') == 'folder' else raw)
        warn = (f" — ⚠ {len(m['literal_missing'])} نقطة لا ترد حرفياً في الحكم" if m['literal_missing'] else '')
        cm.set_step(data, 'mission', 'needs_input', f'{len(m["points"])} نقطة — راجعها وأكّدها{warn}')
    _save(base, data, 'mission')
    return cm.state(data, 'mission')


def _lit(t):
    t = re.sub(r'<!--.*?-->', ' ', t or '', flags=re.S)
    t = re.sub(r'[ً-ْـ]', '', t).translate(str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي', 'ة': 'ه'}))
    return ' '.join(re.sub(r'[^\w\s]', ' ', t).split())


def literal_check(points, judgment_text):
    """أرقام النقاط التي لا يرد نصها حرفياً (بعد تطبيع الهمزات والترقيم والمسافات) في نص الحكم."""
    body = _lit(judgment_text)
    return [p['n'] for p in points if _lit(p['text']) and _lit(p['text']) not in body]


def refresh_mission_if_changed(base, data, get_case=None):
    """بعد المزامنة: حكم الإحالة تغيّر (أو أُضيف) ← يُعاد الاستخراج إن لم يعتمد الخبير المأمورية؛
    وإن اعتمدها لا تُلمس نقاطه ويُعلَّم source_changed للتنبيه. يرجع 'rerun' | 'flagged' | ''."""
    if not mission_source_changed(base, data):
        return ''
    m = data.get('mission') or {}
    if (cm.state(data, 'mission') in cm.OK_STATES or m.get('edited')) and m.get('points'):
        data['mission']['source_changed'] = True
        cw.write_case_json(base, data)
        return 'flagged'
    run_mission(base, data, get_case, force=True)
    return 'rerun'


def set_mission(base, data, raw=None, points=None):
    """تعديل الخبير: raw (نص حرفي جديد يُعاد تقسيمه) و/أو points (قائمة نصوص بترتيبها).
    أي تعديل يلغي التأكيد، ويجعل المعتمدة عليها «تحتاج تحديثاً»."""
    m = data['mission']
    if raw is not None:
        m['raw'] = raw.strip()
        if points is None:
            points = split_points(m['raw'])
    if points is not None:
        _make_points([_clean_point(p) for p in points if _clean_point(p)], m)
    m['edited'] = True                       # تعديل الخبير لا يُستبدل تلقائياً (إلا بزر «أعد القراءة من الحكم»)
    was_ok = cm.state(data, 'mission') in cm.OK_STATES
    m['confirmed'] = False
    if was_ok:
        cm.mark_modified(data, 'mission')
        cm.set_step(data, 'mission', 'done', 'عُدِّلت بعد الاعتماد — اعتمدها من جديد')
    elif cm.state(data, 'mission') in ('pending', 'failed', 'blocked'):
        cm.set_step(data, 'mission', 'needs_input', 'أدخلها الخبير — أكّدها')
    _save(base, data, 'mission')
    return cm.state(data, 'mission')


def confirm_mission(base, data):
    """تأكيد الخبير للنقاط ← reviewed. يرفض إن لم توجد نقاط."""
    m = data['mission']
    if not m.get('points'):
        raise cm.StepError('لا توجد نقاط مأمورية لتأكيدها.')
    m['confirmed'] = True
    if cm.state(data, 'mission') != 'reviewed':
        cm.set_step(data, 'mission', 'reviewed', f'{len(m["points"])} نقطة مؤكَّدة')
    cm.refresh_blocked(data)      # تأكيد المأمورية يفكّ حجب البحث إن اكتفى بها
    _save(base, data, 'mission')
    return cm.state(data, 'mission')
