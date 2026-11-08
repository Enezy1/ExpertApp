# ===== case_model.py — نموذج حالات قضية تقرير الخبرة (المرحلة 2هـ، case.json النسخة 2) =====
# منطق صرف بلا واجهة ولا I/O: بنية البيانات، الترحيل من النسخة 1، الانتقالات المسموحة،
# حجب الخطوات المعتمدة على خطوة فاشلة/ناقصة، وعلامة «تحتاج تحديثاً» (stale).
# الكتابة على القرص دائماً عبر case_workspace.write_case_json.
import copy
import os
import socket

SCHEMA_VERSION = 2

STEP_KEYS = ('subject', 'mission', 'procedures', 'documents', 'attachments', 'research', 'conclusion')
STEP_LABELS = {
    'subject': 'الموضوع',
    'mission': 'المأمورية',
    'procedures': 'الإجراءات',
    'documents': 'المستندات',
    'attachments': 'المرفقات',
    'research': 'البحث ورأي الخبرة',
    'conclusion': 'النتيجة',
}

STATES = ('pending', 'needs_input', 'running', 'done', 'reviewed', 'failed', 'blocked')
STATE_TEXT = {
    'pending': 'لم تبدأ',
    'needs_input': 'تحتاج مدخلاً منه',
    'running': 'قيد التنفيذ',
    'done': 'كُتبت',
    'reviewed': 'راجعها الخبير',
    'failed': 'فشلت',
    'blocked': 'معلّقة',
}
OK_STATES = ('done', 'reviewed')

# اعتماد الخطوة على غيرها: key -> {dep: الحالة المطلوبة} ('ok' = done أو reviewed)
DEPENDS = {
    'research': {'mission': 'reviewed', 'documents': 'ok'},
    'conclusion': {'research': 'ok'},
}
# ما تغذّيه الخطوة دون أن يحجب بدءها: تعديلها بعد اكتمالها يجعل هذه «تحتاج تحديثاً» (تنبيه لا حجب).
# المرفقات تُبنى آلياً من المحاضر والحوافظ وتتجدد وحدها، فلا اعتماد لها على غيرها.
FEEDS = {'subject': ('research', 'conclusion'), 'procedures': ('research',)}
# تنازل الخبير عن الشرط: الخطوة المعتمَد عليها -> مفتاح التنازل في سجلّها
# (المستندات ناقصة والبحث يتابع؛ بنود البحث ناقصة والنتيجة تتابع). لا يسري على المرفقات.
WAIVABLE = {('research', 'documents'), ('conclusion', 'research')}

ALLOWED = {
    'pending': {'running', 'needs_input', 'blocked'},
    'needs_input': {'running', 'done', 'reviewed', 'pending'},
    'running': {'done', 'failed', 'needs_input', 'pending'},
    'done': {'reviewed', 'running', 'needs_input', 'pending'},
    'reviewed': {'running', 'needs_input', 'pending', 'done'},   # done: عُدِّلت بعد الاعتماد ← «كُتبت»
    'failed': {'running', 'pending', 'needs_input'},
    'blocked': {'pending', 'running', 'needs_input'},
}


class StepError(Exception):
    """انتقال حالة غير مسموح أو خطوة غير موجودة (رسالة عربية)."""


def _now():
    from datetime import datetime
    return datetime.now().isoformat(timespec='seconds')


def machine_name():
    return os.environ.get('COMPUTERNAME') or socket.gethostname() or ''


def new_step():
    return {'state': 'pending', 'message': '', 'at': '', 'attempts': 0}


def _fill_v2(data):
    """يضمن وجود كل مفاتيح النسخة 2 دون مسّ الموجود (idempotent)."""
    steps = data.setdefault('steps', {})
    for k in STEP_KEYS:
        steps.setdefault(k, new_step())
    data.setdefault('subject', '')
    data.setdefault('mission', {'raw': '', 'points': [], 'confirmed': False})
    data.setdefault('sessions', {'count_system': None, 'minutes': []})
    data.setdefault('portfolios', [])
    data.setdefault('research', [])
    data.setdefault('attachments', [])
    data.setdefault('conclusion', {'state': 'pending', 'file': '_نظام/04_تقرير/النتيجة.md'})
    data.setdefault('files', {})
    data.setdefault('updated_at', '')
    data.setdefault('updated_on', '')
    return data


def new_case_data(case):
    data = {
        'schema': SCHEMA_VERSION,
        'caso_no': case['caso_no'],
        'autocase_no': case.get('autocase_no') or '',
        'claim_no': case.get('claim_no') or '',
        'case': {k: v for k, v in case.items() if isinstance(v, (str, int, float, list, type(None)))},
        'created': _now(),
    }
    return _fill_v2(data)


def migrate(data):
    """يرجع (data، تغيّر؟). النسخة 1 → 2؛ الأحدث من 2 تبقى كما هي (لا تخفيض)."""
    ver = data.get('schema') or 1
    if ver >= SCHEMA_VERSION:
        before = copy.deepcopy(data)
        _fill_v2(data)
        return data, data != before
    old_stages = data.pop('stages', {})
    data['legacy_stages'] = old_stages        # مراحل 2أ القديمة (جلب/تحويل/قراءة/كتابة) للتتبع فقط
    data['updated_at'] = data.pop('updated', '')
    data['updated_on'] = ''
    data['schema'] = SCHEMA_VERSION
    _fill_v2(data)
    return data, True


# ---------- الاعتماد والحجب ----------

def _step(data, key):
    if key not in STEP_KEYS:
        raise StepError(f'خطوة غير معروفة: {key}')
    return data['steps'].setdefault(key, new_step())


def state(data, key):
    return _step(data, key)['state']


def _need_met(data, owner, dep, need):
    rec = _step(data, dep)
    if rec.get('waived') and (owner, dep) in WAIVABLE:
        return True
    st = rec['state']
    if rec.get('stale') and st in OK_STATES and need != 'reviewed':
        return True           # «تحتاج تحديثاً» لا تحجب التالية، يقرّر الخبير
    return st == 'reviewed' if need == 'reviewed' else st in OK_STATES


def unmet(data, key):
    """قائمة نصوص عربية بما ينقص الخطوة قبل أن تبدأ (فارغة = جاهزة)."""
    out = []
    for dep, need in DEPENDS.get(key, {}).items():
        if not _need_met(data, key, dep, need):
            want = 'مراجعة الخبير لها' if need == 'reviewed' else 'اكتمالها'
            out.append(f'تحتاج {want}: {STEP_LABELS[dep]}')
    return out


def can_start(data, key):
    reasons = unmet(data, key)
    return (not reasons, '؛ '.join(reasons))


def refresh_blocked(data):
    """pending ↔ blocked حسب الاعتماد. لا يمسّ running/done/reviewed/failed/needs_input."""
    changed = False
    for k in STEP_KEYS:
        rec = _step(data, k)
        if rec['state'] not in ('pending', 'blocked'):
            continue
        reasons = unmet(data, k)
        if reasons and rec['state'] == 'pending':
            rec.update(state='blocked', message='؛ '.join(reasons), at=_now())
            changed = True
        elif not reasons and rec['state'] == 'blocked':
            rec.update(state='pending', message='', at=_now())
            changed = True
        elif reasons and rec['message'] != '؛ '.join(reasons):
            rec['message'] = '؛ '.join(reasons)
            changed = True
    return changed


# ---------- الانتقالات ----------

def _dependents(key):
    """كل ما يتأثر بتغيّر الخطوة (متعدٍّ): الاعتماد المباشر + المستندات تغذّي البحث."""
    direct = {}
    for owner, deps in DEPENDS.items():
        for dep in deps:
            direct.setdefault(dep, set()).add(owner)
    for dep, owners in FEEDS.items():
        direct.setdefault(dep, set()).update(owners)
    seen, todo = set(), [key]
    while todo:
        for o in direct.get(todo.pop(), ()):
            if o not in seen:
                seen.add(o)
                todo.append(o)
    return [k for k in STEP_KEYS if k in seen]


def mark_modified(data, key):
    """عُدّلت خطوة اكتملت/روجعت: المعتمدة عليها (المكتملة) تصبح stale ولا تُعاد تلقائياً."""
    _step(data, key)['stale'] = False
    marked = []
    for k in _dependents(key):
        rec = _step(data, k)
        if rec['state'] in OK_STATES:
            rec['stale'] = True
            marked.append(k)
    return marked


def set_step(data, key, new_state, message='', **extra):
    """ينقل خطوة إلى حالة جديدة بعد التحقق. يرفع StepError عند الممنوع. يرجع سجل الخطوة."""
    if new_state not in STATES:
        raise StepError(f'حالة غير معروفة: {new_state}')
    rec = _step(data, key)
    old = rec['state']
    if new_state != old and new_state not in ALLOWED[old]:
        raise StepError(f'انتقال غير مسموح للخطوة «{STEP_LABELS[key]}»: '
                        f'{STATE_TEXT[old]} ← {STATE_TEXT[new_state]}')
    if new_state == 'running':
        ok, why = can_start(data, key)
        if not ok:
            raise StepError(f'لا يمكن بدء «{STEP_LABELS[key]}» — {why}')
        rec['attempts'] = rec.get('attempts', 0) + 1
        if old in OK_STATES:
            mark_modified(data, key)       # إعادة توليد خطوة مكتملة تُقدِّم قِدَم ما بعدها
    if new_state in OK_STATES + ('running',):
        rec['stale'] = False
    rec.update(state=new_state, message=message, at=_now(), **extra)
    if new_state in ('failed', 'pending', 'needs_input', 'running', 'done', 'reviewed'):
        refresh_blocked(data)
    return rec


def recover_interrupted(data):
    """خطوة running بقيت (أُغلق البرنامج أثناءها) ← pending. يرجع هل تغيّر شيء."""
    changed = False
    for rec in data['steps'].values():
        if rec.get('state') == 'running':
            rec.update(state='pending', message='يُستأنف تلقائياً', at=_now())
            changed = True
    if changed:
        refresh_blocked(data)
    return changed


def next_actionable(data):
    """أول خطوة جاهزة للاستئناف: pending/failed وشروطها متحققة. الـstale لا تُقترح (قرار الخبير)."""
    for k in STEP_KEYS:
        if _step(data, k)['state'] in ('pending', 'failed'):
            if can_start(data, k)[0]:
                return k
    return None


def stale_labels(data, key):
    """أسماء الخطوات المكتملة التي صارت «تحتاج تحديثاً» بسبب تعديل الخطوة key (للتنبيه بعد التعديل)."""
    return [STEP_LABELS[k] for k in _dependents(key) if _step(data, k).get('stale')]
