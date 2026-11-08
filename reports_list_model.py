# ===== reports_list_model.py — نموذج عرض قائمة «تقارير الخبراء» (منطق صرف، بلا واجهة) =====
# يحوّل قضية من telecom_reports إلى بيانات جاهزة للبطاقة: الأطراف (المدعي/المدعى عليه)،
# حالات خطوات التقرير السبع من case.json (قراءة فقط — لا ينشئ مجلداً)، المؤشرات، والبحث.
# الواجهة (qt_report_card / qt_expert_reports) تعرض فقط ما يرجع من هنا.
import re

import case_model
import case_workspace

# ترتيب العرض (ليس ترتيب التنفيذ في case_model.STEP_KEYS) + الاسم القصير للنقطة
DISPLAY_STEPS = (
    ('documents', 'المستندات'),       # المستندات أولاً: كل ما بعدها يُبنى منها
    ('subject', 'الموضوع'),
    ('mission', 'المأمورية'),
    ('procedures', 'الإجراءات'),
    ('research', 'البحث'),            # النتيجة جزء من «البحث ورأي الخبرة» (لا خطوة مستقلة)
    ('attachments', 'المرفقات'),
)
# حالة النقطة المعروضة
ST_DONE, ST_CURRENT, ST_INPUT, ST_FAILED, ST_IDLE = 'done', 'current', 'input', 'failed', 'idle'
ST_TEXT = {ST_DONE: 'منتهية', ST_CURRENT: 'الخطوة الحالية', ST_INPUT: 'تحتاج مدخلاً منك',
           ST_FAILED: 'تعذّر', ST_IDLE: 'لم تبدأ'}
NOT_STARTED = 'لم يبدأ التقرير بعد'
ACCENT_NORMAL, ACCENT_INPUT, ACCENT_FAILED = 'normal', 'input', 'failed'

_DIDD = re.compile(r'(?<!\w)ضد(?!\w)')


def _clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def _names(v):
    if isinstance(v, str):
        v = [v]
    out = []
    for x in v or []:
        x = _clean(x)
        if x and x not in out:
            out.append(x)
    return out


def _saved_parties(caso_no):
    try:
        import case_db
        c = case_db.get_case(caso_no) or {}
        return _names(c.get('plaintiffs')), _names(c.get('defendants'))
    except Exception:
        return [], []


def resolve_parties(case, saved=None):
    """(مدّعون[], مدّعى عليهم[], طرف_غير_محدد) — طرف_غير_محدد = عنوان لا يُعرف دوره.
    الأولوية: ما جلبه النظام للقضية (defendants) ← المحفوظ في case_db ← العنوان «س ضد ص».
    العنوان وحده بلا «ضد» (METMONTH يعيد اسماً واحداً) لا يُنسب لأي دور ويُرجَع كطرف غير محدد."""
    sp, sd = saved if saved else ([], [])
    pl, df = _names(case.get('plaintiff')), _names(case.get('defendants'))
    if df:                                   # جاء من النظام مباشرة
        return (pl or _names(sp)), df, ''
    if sp or sd:                             # محفوظ سابقاً
        return (_names(sp) or pl), _names(sd), ''
    title = _clean(case.get('title'))
    parts = _DIDD.split(title, maxsplit=1)
    if len(parts) == 2 and (parts[0].strip() or parts[1].strip()):
        return (pl or _names(parts[0])), _names(parts[1]), ''
    if pl:
        return pl, [], ''
    return [], [], title


_MARKS = ('[ناقص', '[يُكتب]', '[رقم غير موثّق')


def has_gaps(data, key):
    """نقص ظاهر في الخطوة المنتهية: علامة «[ناقص…]»/«[يُكتب]» في رسالتها أو نصها، أو تنبيه أحمر لها."""
    data = data or {}
    texts = [(data.get('steps') or {}).get(key, {}).get('message') or '']
    if key == 'subject':
        texts.append(data.get('subject') or '')
    elif key == 'procedures':
        texts.append((data.get('procedures') or {}).get('text') or '')
    elif key == 'conclusion':
        texts += [a.get('text') or '' for a in (data.get('conclusion') or {}).get('answers') or []]
    if any(m in t for t in texts for m in _MARKS):
        return True
    try:
        import doc_router
        return any(lv == 'red' for lv, _t in doc_router.step_alerts(data, key))
    except Exception:
        return False


def attachments_complete(data):
    """المرفقات تُبنى من المحاضر والحوافظ: لا تكتمل إلا باكتمالهما (المحاضر = الجلسات، والمستندات محوَّلة بلا فشل)."""
    d = data or {}
    steps = d.get('steps') or {}
    if (steps.get('procedures') or {}).get('state') not in case_model.OK_STATES:
        return False
    if (steps.get('documents') or {}).get('state') not in case_model.OK_STATES:
        return False
    return True                      # نقص محضر ملاحظة فقط لا يجعل المرفقات ناقصة


def step_states(data):
    """قائمة [(key, اسم قصير, حالة معروضة, رسالة)] بترتيب العرض. data=None → كلها idle."""
    steps = (data or {}).get('steps') or {}
    raw = {k: (steps.get(k) or {}) for k, _ in DISPLAY_STEPS}
    out = []
    for k, name in DISPLAY_STEPS:
        st = raw[k].get('state', 'pending')
        disp = (ST_DONE if st in case_model.OK_STATES else ST_INPUT if st == 'needs_input'
                else ST_FAILED if st == 'failed' else ST_CURRENT if st == 'running' else ST_IDLE)
        if disp == ST_DONE and data is not None:        # ✓ صادقة: لا نقص ولا تنبيه أحمر، والمرفقات تتبع ما تُبنى منه
            if has_gaps(data, k) or (k == 'attachments' and not attachments_complete(data)):
                disp = ST_INPUT
        msg = _clean(raw[k].get('message')) or ('قيد التنفيذ' if st == 'running' else '')
        if (k == 'subject' and data is not None and 'subject' in data and disp in (ST_DONE, ST_INPUT)
                and not (data.get('subject') or '').strip()):
            # ممنوع «منتهية» بموضوع فارغ: لم يُكتب نص ← «تعذّر» بالسبب (وزر «أعد الكتابة» في بطاقة الموضوع)
            why = ((data.get('stage2') or {}).get('error') or (data.get('stage2') or {}).get('blocked') or '').strip()
            disp, msg = ST_FAILED, 'تعذّر: لم يُكتب نص الموضوع' + (f' — {why}' if why else '')
        out.append([k, name, disp, msg])
    started = any(raw[k].get('state', 'pending') not in ('pending', 'blocked') for k, _ in DISPLAY_STEPS)
    if started and not any(s[2] in (ST_INPUT, ST_FAILED, ST_CURRENT) for s in out):
        for s in out:                        # لا شيء ينتظرني: التالي للبدء هو «الحالية»
            if s[2] == ST_IDLE:
                s[2] = ST_CURRENT
                break
    return [tuple(s) for s in out], started


def step_hint(steps, started):
    """سطر «ما ينتظرني»: فاشلة ← تحتاج مدخلاً ← الحالية ← اكتمال."""
    if not started:
        return NOT_STARTED
    for want, default in ((ST_FAILED, 'فشلت'), (ST_INPUT, 'تحتاج مدخلاً منك')):
        for _k, name, st, msg in steps:
            if st == want:
                return f'{name}: {msg or default}'
    for _k, name, st, msg in steps:
        if st == ST_CURRENT:
            return f'{name}: {msg or "الخطوة التالية"}'
    return 'اكتملت كل الخطوات'


def read_workspace(caso_no):
    """قراءة case.json إن وُجد (دون إنشاء شيء). يرجع (base, data) أو (None, None)."""
    try:
        base = case_workspace.case_dir(caso_no)
        return base, case_workspace.read_case_json(base)
    except Exception:
        return None, None


def build_card(case, ws_reader=read_workspace, saved_fn=_saved_parties):
    """بيانات بطاقة واحدة (saved_fn/ws_reader قابلان للاستبدال في الاختبار)."""
    base, data = ws_reader(case['caso_no'])
    pl, df, other = resolve_parties(case, saved_fn(case['caso_no']))
    steps, started = step_states(data)
    states = [s[2] for s in steps]
    accent = (ACCENT_FAILED if ST_FAILED in states else ACCENT_INPUT if ST_INPUT in states
              else ACCENT_NORMAL)
    return {
        'case': case,
        'caso_no': case['caso_no'],
        'autocase_no': case.get('autocase_no') or '',
        'company': case.get('company') or '',
        'court': case.get('court') or '',
        'plaintiff': '، '.join(pl),
        'defendant': '، '.join(df),
        'other_party': other,
        'steps': steps,
        'started': started,
        'hint': step_hint(steps, started),
        'accent': accent,
        'needs_me': accent != ACCENT_NORMAL,
        'in_progress': started and any(s != ST_DONE for s in states),
        'has_workspace': data is not None,
        'base': base,
        'data': data,
    }


def kpis(cards):
    return {
        'active': len(cards),
        'preparing': sum(1 for c in cards if c['in_progress']),
        'needs_me': sum(1 for c in cards if c['needs_me']),
    }


def search(cards, query):
    q = (query or '').strip().lower()
    if not q:
        return cards
    return [c for c in cards if q in ' '.join((c['caso_no'], c['autocase_no'], c['plaintiff'],
                                               c['defendant'], c['other_party'], c['company'])).lower()]
