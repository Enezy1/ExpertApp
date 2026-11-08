# ===== case_schema.py — عقد بيانات القضية: نوع كل مفتاح في case.json + فحص وإصلاح =====
"""
ليش هذا الملف موجود:
    case.json هو المصدر الوحيد لكل شي في القضية، ويكتبه **أكثر من وحدة**:
        case_subject_mission · report_v3 · case_stage2 · case_research · report_docx …
    وما كان فيه **عقد واحد** بين الوحدات، فتصدق تعارض في الشكل: وحدة كتبت
    «subject_missing» **قائمة** وثانية قرأتها **قاموساً** ⇒ استثناء أثناء رسم
    بطاقة الموضوع ⇒ **البطاقة ما تنرسم أصلاً** (17 مرة بين 21/10 و25/10 —
    crash_log.txt).

شنو يسوي هذا الملف:
    1. `FIELD_TYPES` — العقد: نوع كل مفتاح معروف (مستخرَج من مواضع الكتابة
       في الكود + القيم الحقيقية في دفاتر القضايا).
    2. `validate(data)` — يفحص ويبلّغ عن كل خانة غلط الشكل.
    3. `repair(data)` — يصلّح **الأشكال الآمنة فقط** (ما يحذف أي معلومة أبداً).
    4. `install()` — رقعة على **قراءة** case.json: كل دفتر يُفحص ويُصلَّح قبل ما
       Uses الكود محتواه. نفس نمط رقعة `net_timeouts` — بلا لمس أي ملف مشترك.
    5. `scan()` + سطر الأوامر: تقرير عن كل القضايا (وفحص شامل بضغطة).

الاستعمال:
    من main.py:   case_schema.install()
    يدوي:         python case_schema.py            ← تقرير
                  python case_schema.py --fix      ← تقرير + حفظ الإصلاحات
"""
import datetime
import json
import os
import sys
from collections import namedtuple

# ===== العقد: نوع كل مفتاح في case.json =====
# مستخرَج (26/10/2026) من كل موضع كتابة في المشروع + كل قيمة حقيقية في دفاتر
# القضايا الست. مفتاح غير مذكور هنا = غير مقيد (يُقبل أي شكل) — يُضاف لل العقد
# عند ما يتّضح شكله.
FIELD_TYPES = {
    # هوية القضية
    'caso_no': str, 'autocase_no': str, 'claim_no': str, 'created': str,
    'updated_at': str, 'updated_on': str, 'questions_generated_at': str,
    'schema': int, 'next_doc_uid': int,
    # الموضوع
    'subject': str, 'subject_prev': str, 'subject_source': str, 'subject_type': str,
    'subject_quality_warning': str, 'subject_edited': bool, 'subject_type_unclear': bool,
    'subject_missing': dict, 'subject_alerts': list, 'subject_facts': dict,
    'subject_check': dict,
    # باقي الخطوات
    'steps': dict, 'mission': dict, 'procedures': dict, 'case': dict,
    'conclusion': dict, 'research': list, 'research2': dict, 'research_written': bool,
    'readiness': dict, 'questions': list, 'contracts': dict, 'main_contract': dict,
    'judgment_pick': dict, 'attachments': list, 'attachments_ai': dict,
    'portfolios': list, 'triage_docs': list, 'doc_index': list, 'files': dict,
    'engines': dict, 'written_by': dict, 'sessions': dict, 'ai_mode': dict,
    'autowrite': dict, 'stage2': dict, 'sources': dict, 'sort': dict,
    'startup': dict, 'layout': dict, 'folder_fetch': dict, 'folder_migration': dict,
    'folder_sync': dict, 'facts3': dict, 'report': dict,
}

TYPE_NAMES = {str: 'نص', dict: 'قاموس', list: 'قائمة', bool: 'منطقي', int: 'رقم'}

# خانة فيها خلل: (المفتاح، المتوقع، الموجود، قابل للإصلاح؟، تفصيل)
Problem = namedtuple('Problem', 'key expected actual fixable detail')

MAX_LOG_FIXES = 200        # أقصى عدد إصلاحات محفوظة للعرض في التشخيص
LAST_FIXES = []            # آخر إصلاحات (لتبويب التشخيص)


def _tname_of(t):
    return TYPE_NAMES.get(t, getattr(t, '__name__', str(t)))


def _tname_of_value(v):
    t = type(v)
    if t is bool:
        return 'منطقي'
    return TYPE_NAMES.get(t, t.__name__)


def _type_ok(value, expected):
    """bool subclasses int —hence the separate branches."""
    if expected is bool:
        return isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


# ===== الفحص =====
def validate(data):
    """يرجع قائمة مشاكل الشكل في دفتر القضية (ما يعدّل شيئاً)."""
    problems = []
    if not isinstance(data, dict):
        return [Problem('(case.json)', 'قاموس', _tname_of_value(data), False,
                        'الملف مو قاموس — يقرأه الكود كخريطة')]
    for key, expected in FIELD_TYPES.items():
        if key not in data:
            continue
        value = data[key]
        if _type_ok(value, expected):
            continue
        problems.append(Problem(key, _tname_of(expected), _tname_of_value(value),
                                _fixable(key, value), ''))
    problems.extend(_validate_nested(data))
    return problems


def _validate_nested(data):
    """شكل المفاتيح داخل الخانات القابلة للتوسّع (الخطوات، التنبيهات، …)."""
    out = []
    steps = data.get('steps')
    if isinstance(steps, dict):
        for name, value in steps.items():
            if isinstance(value, str):
                out.append(Problem('steps.' + name, 'قاموس', 'نص', True,
                                   'قيمة الخطوة نص («%s») — الكود يتوقّع قاموساً' % value[:40]))
            elif not isinstance(value, dict):
                out.append(Problem('steps.' + name, 'قاموس', _tname_of_value(value),
                                   False, 'قيمة الخطوة مو قاموس'))
    alerts = data.get('subject_alerts')
    if isinstance(alerts, list):
        for i, item in enumerate(alerts):
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                out.append(Problem('subject_alerts[%d]' % i, 'زوج (مستوى، نص)',
                                   _tname_of_value(item), False, 'شكل التنبيه غير متوقّع'))
    wb = data.get('written_by')
    if isinstance(wb, dict):
        for name, value in wb.items():
            if not isinstance(value, dict):
                out.append(Problem('written_by.' + name, 'قاموس',
                                   _tname_of_value(value), False, ''))
    return out


def _fixable(key, value):
    """هل بالإصلاح الآمن تصحيح هذا الخلل؟ (لا نحذف أي معلومة أبداً)"""
    if key == 'subject_missing':
        return isinstance(value, (list, dict))
    return False


# ===== الإصلاح (أشكال آمنة فقط) =====
def repair(data):
    """يصلّح الأشكال الآمنة داخل data (بالمكان نفسه) ويرجع قائمة بما صُحّح."""
    fixes = []
    if not isinstance(data, dict):
        return fixes

    # 1) subject_missing: القائمة ← القاموس (المشكلة الفعلية 25/10)
    sm = data.get('subject_missing')
    if isinstance(sm, list):
        data['subject_missing'] = {'unverified': [], 'absent': list(sm), 'models': []}
        fixes.append('subject_missing: قائمة ← قاموس (%d عنصر في absent)' % len(sm))
    elif isinstance(sm, dict):
        for sub in ('unverified', 'absent', 'models'):
            if sub not in sm:
                sm[sub] = []
                fixes.append('subject_missing: أُضيف المفتاح %s' % sub)
            elif not isinstance(sm[sub], list):
                sm[sub] = list(sm[sub]) if isinstance(sm[sub], (tuple, set)) else []
                fixes.append('subject_missing.%s: حُوّل لقائمة' % sub)

    # 2) steps: قيمة الخطوة نص ← قاموس فيه state (الكود يقرأ .get('state'))
    steps = data.get('steps')
    if isinstance(steps, dict):
        for name, value in list(steps.items()):
            if isinstance(value, str):
                steps[name] = {'state': value}
                fixes.append('steps.%s: نص ← قاموس' % name)

    # 3) sessions: القوائم الناقصة تُملأ (لا تُحذف)
    sessions = data.get('sessions')
    if isinstance(sessions, dict):
        if not isinstance(sessions.get('minutes'), list):
            sessions['minutes'] = []
            fixes.append('sessions.minutes: قائمة فارغة')
        if 'count_system' not in sessions:
            sessions['count_system'] = None
            fixes.append('sessions.count_system: أُضيف')
    return fixes


def check(data):
    """يفحص ويصلّح دفعة واحدة: {'problems': [...], 'fixes': [...], 'ok': bool}"""
    problems = validate(data)
    fixes = repair(data)
    return {'problems': problems, 'fixes': fixes, 'ok': not problems}


# ===== الرقعة على القراءة =====
_INSTALLED = False


def _log_path():
    try:
        import app_paths
        base = app_paths.data_dir()
    except Exception:
        base = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'ExpertApp')
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return None
    return os.path.join(base, 'case_schema.log')


def _log_fixes(caso, fixes):
    global LAST_FIXES
    LAST_FIXES.append((caso, list(fixes)))
    del LAST_FIXES[:-MAX_LOG_FIXES]
    path = _log_path()
    if not path:
        return
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write('%s  %s  %s\n' % (datetime.datetime.now().isoformat(timespec='seconds'),
                                      caso, ' | '.join(fixes)))
    except OSError:
        pass


def install(force=False):
    """رقعة على قراءة case.json: يفحص ويصلّح قبل ما يقرأ الكود الملف.

    Returns True if the patch was installed. Under tests it does nothing unless
    force=True (so the test suite stays unaffected by the global patch)."""
    global _INSTALLED
    if _INSTALLED:
        return False
    if not force:
        try:
            import app_paths
            if app_paths.under_tests():
                return False
        except Exception:
            pass
    try:
        import case_workspace
    except Exception:
        return False
    orig = getattr(case_workspace, '_read', None)
    if orig is None or getattr(orig, '_case_schema_wrapped', False):
        _INSTALLED = True
        return False

    def _read(base):
        got = orig(base)
        try:
            data = got[0] if isinstance(got, tuple) else got
            if isinstance(data, dict):
                fixes = repair(data)
                if fixes:
                    _log_fixes(data.get('caso_no') or os.path.basename(str(base)), fixes)
        except Exception:
            pass
        return got

    _read._case_schema_wrapped = True
    _read._orig_read = orig
    case_workspace._read = _read
    _INSTALLED = True
    return True


def uninstall():
    """يرفع الرقعة (للاختبارات فقط)."""
    global _INSTALLED
    try:
        import case_workspace
        cur = getattr(case_workspace, '_read', None)
        orig = getattr(cur, '_orig_read', None)
        if orig is not None:
            case_workspace._read = orig
    except Exception:
        pass
    _INSTALLED = False
    return True


# ===== الفحص الشامل =====
def _case_count(root):
    try:
        return sum(1 for n in os.listdir(root)
                   if os.path.isdir(os.path.join(root, n, '_نظام')))
    except OSError:
        return 0


def _reports_root():
    """جذر مجلدات القضايا: الجذر المُعدّ في إعدادات الخبير (الأكثر قضايا) —
    الجذر الافتراضي الفاضي (مجلد المستندات) ما ينفع."""
    configured = []
    try:
        base = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'experts')
        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name, 'expert_settings.json')
            if not os.path.isfile(p):
                continue
            with open(p, encoding='utf-8') as f:
                r = (json.load(f) or {}).get('reports_root')
            if r and r not in configured:
                configured.append(r)
    except Exception:
        pass
    default = ''
    try:
        import case_workspace
        default = case_workspace.reports_root() or ''
    except Exception:
        pass

    best, best_n = '', 0
    for r in configured:
        n = _case_count(r)
        if n > best_n:
            best, best_n = r, n
    if best:
        return best
    if default and _case_count(default):
        return default
    if configured:
        return configured[0]
    return default


def scan(root=None):
    """يفحص كل القضايا في الجذر: [{caso, path, problems, fixes}]."""
    root = root or _reports_root()
    out = []
    if not root or not os.path.isdir(root):
        return out
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for caso in names:
        base = os.path.join(root, caso)
        path = os.path.join(base, '_نظام', 'case.json')
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (ValueError, OSError) as e:
            out.append({'caso': caso, 'path': path, 'fixes': [],
                        'problems': [Problem('(case.json)', 'JSON صالح', type(e).__name__,
                                              False, str(e)[:140])]})
            continue
        problems = validate(data)
        fixes = repair(data)
        out.append({'caso': caso, 'path': path, 'problems': problems, 'fixes': fixes})
    return out


def apply_fixes(row, write=True):
    """يحفظ إصلاحات القضية في ملفها (بصيغة المشروع نفسها)."""
    if not row.get('fixes') or not write:
        return False
    try:
        import case_workspace
        base = os.path.dirname(os.path.dirname(row['path']))
        with open(row['path'], encoding='utf-8') as f:
            data = json.load(f)
        repair(data)
        case_workspace.write_case_json(base, data)
        return True
    except Exception:
        return False


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    do_fix = '--fix' in argv
    root = next((a for a in argv if not a.startswith('-')), None)
    rows = scan(root)
    if not rows:
        print('ما لقيت قضايا (الجذر: %s)' % (root or _reports_root() or 'غير محدد'))
        return 0
    bad = [r for r in rows if r['problems'] or r['fixes']]
    print('فُحصت %d قضية — %d فيها ملاحظة' % (len(rows), len(bad)))
    for r in rows:
        if not (r['problems'] or r['fixes']):
            continue
        print('\n■ %s' % r['caso'])
        for p in r['problems']:
            print('   ✖ %-26s المتوقع: %-8s الموجود: %-8s%s'
                  % (p.key, p.expected, p.actual,
                     '  (قابل للإصلاح)' if p.fixable else ''))
            if p.detail:
                print('       %s' % p.detail)
        for fx in r['fixes']:
            print('   ✔ %s' % fx)
    if do_fix:
        n = sum(1 for r in rows if apply_fixes(r))
        print('\nحُفظت الإصلاحات في %d قضية.' % n)
    elif bad:
        print('\n(لحفظ الإصلاحات: python case_schema.py --fix)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
