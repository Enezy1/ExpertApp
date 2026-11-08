# ===== case_stage2.py — المرحلة الثانية: الموضوع والإجراءات والمرفقات بطلب ذكاء واحد (2026-10-21) =====
# طريقة الخبير: قرأ كل المستندات في المرحلة الأولى (الملخص.md)، ثم يكتب هنا دفعة واحدة:
#   • لا يُرسل الطلب بلا صحيفة الدعوى؛ ونقص حكم الإحالة أو المحاضر يظهر للخبير قائمةً (missing_inputs).
#   • الطلب: الملخص.md كاملاً + قواعد ونماذج الموضوع (نماذج_صياغة_الموضوع.md) + قالب الإجراءات (نماذج_صياغة_الإجراءات.md)
#     + بيانات النظام (تاريخ الاستلام، الحكم وجلسته، الحجز) + حقائق الإجراءات المثبتة بالكود. الرد JSON:
#     {"subject": "...", "procedures": "...", "attachments": ["..."]}.
#   • التحقق بالكود (check): كل تاريخ/رقم/مبلغ في النص موجود في الملخص المتحقَّق أو بيانات النظام، الجنس النحوي للأطراف،
#     وبوابة الإجراءات (حضور/تخلف/إعلان/مناقشة/تواريخ مطابقة لما ثبت في المحاضر، «عدة جلسات» بلا عدد)، والمرفقات بتواريخ
#     المستندات وعدد المحاضر. المرفوض يُعاد طلبه مرة واحدة بقائمة أخطائه؛ إن بقي: الموضوع يُعلَّم أحمر (لا يُستبدل بنص فارغ)،
#     والإجراءات والمرفقات تُكتب بالكود من الصيغة المعتمدة مع ملاحظة.
#   • فشل الطلب أو التحقق يظهر سببه للخبير مع زرّي «أعد الكتابة» و«اكتب عبر المتصفح» (browser_write).
#   • يُعاد تلقائياً عند تغيّر الملخص (عقد جديد، محضر جديد…) ما لم يعدّل الخبير النص يدوياً (needs_run / auto).
import hashlib
import json
import os
import re
from datetime import datetime

import case_model as cm
import case_workspace as cw

PURPOSE = 'الموضوع والإجراءات'
KEYS = ('subject', 'procedures', 'attachments')
LABELS = {'subject': 'الموضوع', 'procedures': 'الإجراءات', 'attachments': 'المرفقات'}
SCHEMA = '{"subject": "فقرة الموضوع", "procedures": "فقرة الإجراءات", "attachments": ["بند", "بند"]}'
_DATE = re.compile(r'(?<!\d)(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})(?!\d)')
_EMPTY_SLOT = re.compile(r'(وقدرها|وقدره|وطلبت|وطلب|بمبلغ|قيمة|مدة|بتاريخ|مؤرخ|رقم)\s*(?:[.،,؛]|$)')
_PLACEHOLDER = re.compile(r'\((?:تاريخ|القيمة|المدة|المطالبة|اسم|الشق|المبلغ)[^)]{0,20}\)|\[يُكتب\]|\{[^}]*\}')


def _register_task():
    """مزوّد المرحلة الثانية: مهمة «الصياغة» في جدول المزوّدين (جيميناي أولاً)."""
    try:
        import ai_providers
        ai_providers.PURPOSE_TASK.setdefault(PURPOSE, 'write')
    except Exception:
        pass


_register_task()


def _now():
    return datetime.now().isoformat(timespec='seconds')


def state(data):
    return data.setdefault('stage2', {})


# ---------- المدخلات ----------

def _has_type(base, kind_word, cf_kind):
    import case_folder as cf
    import case_triage as ct
    if cf.has_kind(base, cf_kind):
        return True
    for rel, e, t in ct.entries(base):
        if any(p.get('type') == kind_word for p in t.get('parts') or []):
            return True
    return False


def missing_inputs(base, data):
    """[اسم ما ينقص] من الملفات الأساسية: صحيفة الدعوى (شرط للإرسال)، حكم الإحالة، محاضر الخبرة."""
    import case_folder as cf
    import case_triage as ct
    out = []
    if not _has_type(base, 'صحيفة', cf.PLAINT):
        out.append('صحيفة الدعوى')
    if not (_has_type(base, 'حكم', cf.JUDGMENT) or (data.get('judgment_pick') or {}).get('file')):
        out.append('حكم الإحالة')
    has_min = bool((data.get('sessions') or {}).get('minutes'))
    if not has_min:
        has_min = any(cf.kind_of(rel) == cf.MINUTES or any(p.get('type') == 'محضر' for p in t.get('parts') or [])
                      for rel, e, t in ct.entries(base))
    if not has_min:
        out.append('محاضر الخبرة')
    return out


def _dmy(iso):
    import case_procedures as cp
    return cp._dmy(iso) if iso else ''


def system_block(data):
    """بيانات النظام وحقائق الإجراءات المثبتة بالكود (المرجع الوحيد للحضور والتواريخ)."""
    import case_procedures as cp
    import case_sort as cs
    proc = data.get('procedures') or {}
    facts = cp.proven_facts(data)
    lines = [f"- رقم الخبرة: {data.get('caso_no', '')}"]
    rec = (proc.get('received') or {}).get('date')
    if rec:
        lines.append(f"- تاريخ استلام ملف الدعوى: {_dmy(rec)}")
    jd = cp.judgment_date(data)
    kind = 'حكم الاستئناف' if cp.is_appeal(data) else 'الحكم التمهيدي'
    if jd:
        lines.append(f"- {kind} الصادر بجلسة {_dmy(jd)}")
    bk = (proc.get('booked') or {}).get('date')
    if bk:
        lines.append(f"- تاريخ حجز الدعوى للتقرير: {_dmy(bk)}")
    for role, word in (('plaintiff', 'المدعي/المدعية'), ('defendant', 'المدعى عليه/عليها')):
        for i, name in enumerate(cs.party_names(data, role), 1):
            lines.append(f"- {word} #{i}: {name} — الصفة في النص: «{cs.role_label(data, role, i)}»")
    res = (proc.get('attendance') or {}).get('result') or []
    if res and all(r.get('certain') for r in res) and facts.get('attendance_ok', True):
        for lab, r in zip(cp.party_labels(res, data), res):
            fem = bool(re.search(r'المدعية|عليها|الشركة', lab[0]))
            lines.append(f"- في المحاضر: {lab[0]} " + (('حضرت' if fem else 'حضر') if r['present']
                                                        else ('لم تحضر' if fem else 'لم يحضر'))
                         + (' (ثبت في المحاضر صحة إعلانه)' if not r['present'] and (facts.get('notified') or {}).get(r['role'])
                            else ''))
    elif not facts.get('attendance_ok', True):
        lines.append(f"- {facts.get('gate_note') or 'ينقص محضر'}: لا يُكتب حضور ولا تخلف ولا مناقشة")
    else:
        lines.append('- الحضور غير مؤكد من المحاضر: لا يُكتب حضور ولا تخلف')
    if facts.get('discussed'):
        lines.append('- وردت المناقشة في المحاضر')
    lines.append(f"- عدد محاضر الخبرة المقروءة: {len((data.get('sessions') or {}).get('minutes') or [])}")
    return '\n'.join(lines)


def _read(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def library_texts():
    """(نماذج الموضوع، قالب الإجراءات) كما في ملفَي مكتبة الخبير."""
    import case_procedures as cp
    import case_subject_ai as sa
    import drafting_library as dl
    sa.ensure_style_file()
    return (_read(sa.style_path()), _read(cp.STYLE_PATH or dl.program_path(dl.PROCEDURES_FILE)))


def build_prompt(base, data, errors=None, only=None):
    """الطلب الواحد (يُعاد نفسه عبر المتصفح). errors: {مفتاح: [أخطاء]} للإعادة، only: المفاتيح المطلوبة فقط."""
    import case_subject_telecom as st
    import case_summary
    summary = case_summary.verified_text(base, data)
    subj_lib, proc_lib = library_texts()
    want = [k for k in KEYS if not only or k in only]
    telecom = ''
    try:
        if st.telecom_company({}, data.get('case') or {}):
            telecom = ('\nالقضية اتصالات: اذكر في الموضوع تاريخ عقد الاشتراك وأرقام الخطوط والجهاز والمبلغ الشهري ومدة الالتزام '
                       'والمبلغ المطالب به — كلها من الملخص فقط.')
    except Exception:
        pass
    parts = [
        'أنت خبير قضائي في إدارة الخبراء بوزارة العدل الكويتية. قرأتَ كل مستندات القضية، وملخصها المتحقَّق أدناه. '
        'اكتب الآن دفعة واحدة: «الموضوع» و«الإجراءات» و«المرفقات» لتقرير الخبرة. أعد JSON فقط بلا أي نص آخر بالشكل:',
        SCHEMA if not only else json.dumps({k: ('[…]' if k == 'attachments' else '…') for k in want}, ensure_ascii=False),
        'قواعد ملزمة:',
        '1) الموضوع من صحيفة الدعوى والعقد كما في الملخص، بأسلوب النماذج المعتمدة أدناه حرفاً بحرف في البناء: «جاءت المدعية '
        'بصحيفة مفادها أنه بموجب عقد مؤرخ … تعهدت فيه … وذلك مقابل قيمة وقدرها … وفي مدة وقدرها …، وأفادت المدعية على حسب '
        'دعواها … إلا أن المدعى عليه … فتم رفع الدعوى الماثلة». الأطراف بصفاتهم (لا أسماء) وبالجنس الصحيح كما في «بيانات '
        'النظام». لا تذكر دفاع المدعى عليه في الموضوع.' + telecom,
        '2) لا تكتب أي تاريخ أو رقم أو مبلغ غير وارد في الملخص أو بيانات النظام. ما لم يرد اتركه بصمت: لا فراغات ولا أقواس '
        'ولا «[يُكتب]».',
        '3) الإجراءات بالقالب المعتمد («الصيغة المعتمدة» في ملف الإجراءات) بتواريخ بيانات النظام فقط، و«وحددنا عدة جلسات» '
        'دون أي عدد، والحضور والتخلف و«رغم صحة إعلانه» والمناقشة فقط بما ثبت في «بيانات النظام» من المحاضر.',
        '4) المرفقات بنود قصيرة بترتيب تقارير الخبير: «عدد ( N ) محضر أعمال.» (N عدد المحاضر المقروءة) ثم «صور توكيلات.» '
        'إن وردت، ثم مستندات المدعية (المذكرة قبل الحافظة) بالتاريخ ثم مستندات المدعى عليه، كل بند «حافظة مستندات المدعية '
        'المؤرخة DD/MM/YYYY.» أو «مذكرة دفاع المدعى عليه المؤرخة DD/MM/YYYY.» بمقدّمها وتاريخها كما في الملخص.',
        '## بيانات النظام', system_block(data),
        '## نماذج وقواعد صياغة الموضوع (من مكتبة الخبير)', subj_lib.strip(),
        '## قالب الإجراءات (من مكتبة الخبير)', proc_lib.strip(),
        '## ملخص القضية المتحقَّق (الملخص.md)', summary.strip()]
    if errors:
        parts.append('## رُفضت كتابتك السابقة لهذه الأسباب — أعد فقط ' + '، '.join(LABELS[k] for k in want) + ' دونها:')
        parts += [f'- {LABELS[k]}: {e}' for k in want for e in errors.get(k) or []]
    return '\n\n'.join(parts)


def parse(raw):
    import case_triage
    obj = case_triage.parse_json(raw)
    if obj is None:
        raise ValueError('ردّ المرحلة الثانية ليس JSON')
    return obj


# ---------- التحقق ----------

def _dates(text):
    out = set()
    import case_subject_telecom as st
    for m in _DATE.finditer(st._display(text)):
        try:
            out.add((int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    return out


def _numbers(text):
    import case_subject_telecom as st
    return {n for n, _s, _e in st._tokens(st._display(text)) if st._is_num(n)}


def allowed(base, data):
    import case_summary
    ref = case_summary.verified_text(base, data) + '\n' + system_block(data)
    return ref, _numbers(ref), _dates(ref)


def _gender_errors(data, text):
    """تعارض الجنس النحوي فقط حين يتحدد جنس الطرف من بيانات الأطراف (الاسم شركة، أو صفته في الصحيفة — party_gender).
    لم يتحدد ← لا خطأ (لا يُرفض النص بسبب جنس مجهول)."""
    import case_sort as cs
    errs = []
    pl, df = cs.party_names(data, 'plaintiff'), cs.party_names(data, 'defendant')
    if len(df) == 1:
        g = cs.party_gender(data, 'defendant', 1)
        if g == 'm' and re.search(r'المدع[ىي]\s+عليها', text):
            errs.append('كُتب «المدعى عليها» والمدعى عليه رجل — الصواب «المدعى عليه»')
        if g == 'f' and re.search(r'المدع[ىي]\s+عليه(?![اام])', text):
            errs.append('كُتب «المدعى عليه» والمدعى عليها شركة/أنثى — الصواب «المدعى عليها»')
    if len(pl) == 1:
        g = cs.party_gender(data, 'plaintiff', 1)
        if g == 'f' and re.search(r'(?<!\S)المدعي(?![ةهني])(?!\s+علي)', text):
            errs.append('كُتب «المدعي» والمدعية شركة/أنثى — الصواب «المدعية»')
        if g == 'm' and re.search(r'المدعية', text):
            errs.append('كُتب «المدعية» والمدعي رجل — الصواب «المدعي»')
    return errs


def _unknown_values(text, nums, dates):
    errs = []
    bad_d = sorted(d for d in _dates(text) if d not in dates)
    if bad_d:
        errs.append('تواريخ غير واردة في الملخص المتحقَّق: ' + '، '.join(f'{a}/{b}/{c}' for a, b, c in bad_d[:4]))
    import case_subject_telecom as st
    clean = _DATE.sub(' ', st._display(text))
    bad_n = sorted(n for n in _numbers(clean) if n not in nums)
    if bad_n:
        errs.append('أرقام/مبالغ غير واردة في الملخص المتحقَّق: ' + '، '.join(bad_n[:6]))
    return errs


def check_subject(base, data, text, ref=None):
    text = ' '.join(str(text or '').split())
    if not text:
        return text, ['الموضوع فارغ']
    _r, nums, dates = ref or allowed(base, data)
    errs = []
    if not re.match(r'^\s*جاء', text):
        errs.append('لا يبدأ بأسلوب النماذج («جاءت المدعية بصحيفة مفادها…»)')
    if _PLACEHOLDER.search(text):
        errs.append('فيه فراغ أو قوس خانة لم يُملأ')
    m = _EMPTY_SLOT.search(text)
    if m:
        errs.append(f'خانة فارغة بعد «{m.group(1)}» (لم يُكتب ما بعدها) — احذف العبارة كلها أو أكملها من الملخص')
    errs += _unknown_values(text, nums, dates)
    errs += _gender_errors(data, text)
    errs += _misread_numbers(text)
    return text, errs


def _misread_numbers(text):
    """رقم خط/عقد يطابق رقماً آخر في الفقرة نفسها بحذف خانة واحدة (9981725 و99817125) = خطأ قراءة في مستند، لا خط ثالث."""
    nums = sorted(set(re.findall(r'(?<![\d.,])\d{6,12}(?![\d.,])', text)), key=len)
    errs = []
    for n in nums:
        for m in nums:
            if len(m) == len(n) + 1 and any(m[:i] + m[i + 1:] == n for i in range(len(m))):
                errs.append(f'الرقم {n} يبدو خطأ قراءة للرقم {m} (خانة ناقصة) — اذكر الرقم الصحيح مرة واحدة')
    return errs


_SESS_N = re.compile(r'جلستين|جلستان|عدد\s*\(?\s*\d+\s*\)?\s*جلس|\d+\s*جلس')


def check_procedures(base, data, text):
    """بوابة الاكتمال القائمة: النص يطابق ما يثبت في المحاضر (كما في نص الكود cp.compose)."""
    import case_procedures as cp
    text = ' '.join(str(text or '').split())
    if not text:
        return text, ['الإجراءات فارغة']
    code, _notes = cp.compose(data)
    errs = []
    if 'عدة جلسات' not in text:
        errs.append('لا تتضمن «وحددنا عدة جلسات»')
    if _SESS_N.search(text):
        errs.append('ذكرت عدد الجلسات (العدد لا يُكتب أبداً)')
    for word, lab in (('تخلف', 'التخلف'), ('رغم صحة إعلان', '«رغم صحة إعلانه»'), ('مناقشة', 'المناقشة'),
                      ('حضر', 'الحضور')):
        has_t, has_c = word in text, word in code
        if has_t and not has_c:
            errs.append(f'{lab} لم يثبت في المحاضر')
        elif has_c and not has_t:
            errs.append(f'{lab} ثابت في المحاضر ولم يُذكر')
    bad = sorted(d for d in _dates(text) if d not in _dates(code))
    if bad:
        errs.append('تواريخ غير بيانات النظام: ' + '، '.join(f'{a}/{b}/{c}' for a, b, c in bad[:4]))
    return text, errs


def check_attachments(base, data, items):
    """كل بند بنوع معروف وتاريخ وارد في الملخص، وعدد المحاضر صحيح. يرجع ([بنود]، أخطاء)."""
    if not isinstance(items, list):
        return [], ['المرفقات ليست قائمة']
    _r, _nums, dates = allowed(base, data)
    n_min = len((data.get('sessions') or {}).get('minutes') or [])
    out, errs = [], []
    for it in items:
        t = ' '.join(str(it or '').split()).strip(' -•')
        if not t:
            continue
        if not re.search(r'حافظ|مذكر|محضر|توكيل|صور|تقرير|حكم', t):
            errs.append(f'بند غير معروف النوع: «{t[:40]}»')
            continue
        bad = [d for d in _dates(t) if d not in dates]
        if bad:
            errs.append(f'بند بتاريخ غير وارد في الملخص: «{t[:50]}»')
            continue
        m = re.search(r'عدد\s*\(\s*(\d+)\s*\)\s*محضر', t)
        if m and int(m.group(1)) != n_min:
            errs.append(f'عدد المحاضر في المرفقات ({m.group(1)}) لا يطابق المقروءة ({n_min})')
            continue
        out.append(t if t.endswith('.') else t + '.')
    if not out and items:
        errs.append('لا بند صالح')
    return out, errs


def check(base, data, obj, only=None):
    """{مفتاح: (القيمة، [أخطاء])} للأجزاء المطلوبة."""
    ref = allowed(base, data)
    out = {}
    want = [k for k in KEYS if not only or k in only]
    if 'subject' in want:
        out['subject'] = check_subject(base, data, obj.get('subject'), ref)
    if 'procedures' in want:
        out['procedures'] = check_procedures(base, data, obj.get('procedures'))
    if 'attachments' in want:
        out['attachments'] = check_attachments(base, data, obj.get('attachments'))
    return out


# ---------- التشغيل ----------

def signature(base, data):
    """بصمة المدخلات: الملخص المتحقَّق + بيانات النظام. تغيّرها (عقد/محضر جديد) ← إعادة تلقائية."""
    import case_summary
    h = hashlib.sha1()
    h.update(case_summary.verified_text(base, data, inputs_only=True).encode('utf-8'))
    h.update(system_block(data).encode('utf-8'))
    return h.hexdigest()


def is_manual(data, key):
    if key == 'subject':
        return bool(data.get('subject_edited')) and bool((data.get('subject') or '').strip())
    if key == 'procedures':
        p = data.get('procedures') or {}
        return bool(p.get('edited')) and bool((p.get('text') or '').strip())
    return False


def needs_run(base, data):
    """يلزم طلب جديد: تغيّرت بصمة الملخص منذ آخر كتابة ناجحة، ولم يعدّل الخبير الموضوع يدوياً."""
    s = state(data)
    if is_manual(data, 'subject'):
        return False
    try:
        sig = signature(base, data)
    except Exception:
        return False
    return s.get('sig') != sig


def _store(base, data, res, provider_line, source, errs_final, sig):
    """يحفظ ما قُبل؛ المرفوض بعد الإعادة: الموضوع أحمر (يبقى نصه)، والإجراءات/المرفقات من الكود مع ملاحظة."""
    import case_attachments
    import case_procedures as cp
    s = state(data)
    notes = []
    if 'subject' in res:
        text, errs = res['subject']
        if not is_manual(data, 'subject') and text:
            if (data.get('subject') or '').strip() != text:
                data['subject_prev'] = data.get('subject') or ''
            data['subject'] = text
            data['subject_edited'] = False
        data['subject_check'] = {'ok': not errs, 'errors': errs, 'at': _now()}
        if not text:
            cm.set_step(data, 'subject', 'failed', 'لم يُكتب الموضوع: ' + '؛ '.join(errs or ['ردّ فارغ']))
        elif errs:
            cm.set_step(data, 'subject', 'needs_input', 'الموضوع لم يجتز التحقق — راجع الأحمر: ' + '؛ '.join(errs[:3]))
        else:
            if cm.state(data, 'subject') not in cm.OK_STATES:
                if cm.state(data, 'subject') != 'needs_input':
                    cm.set_step(data, 'subject', 'needs_input')
                cm.set_step(data, 'subject', 'done', 'كُتب من الملخص (المرحلة الثانية)')
            else:
                cm.mark_modified(data, 'subject')
        data.setdefault('written_by', {})['subject'] = provider_line
        data.setdefault('autowrite', {})['subject'] = {'source': 'stage2', 'note': 'كُتب من الملخص (طلب واحد)',
                                                       'newer': '', 'notice': '', 'manual': False, 'at': _now()}
    if 'procedures' in res:
        text, errs = res['procedures']
        proc = data.setdefault('procedures', {})
        if not proc.get('edited'):
            auto = cp.compose_text(data)
            if errs or not text:
                text = auto
                notes.append('الإجراءات: رُفض نص النموذج (' + '؛ '.join(errs[:2]) + ') — كُتبت بالكود من الصيغة المعتمدة')
                proc['source'] = 'code'
            else:
                proc['source'] = 'stage2'
            proc['text'], proc['edited'], proc['stage2_auto'] = text, False, auto
        proc['stage2_check'] = {'ok': not errs, 'errors': errs, 'at': _now()}
        data.setdefault('written_by', {})['procedures'] = provider_line
        if proc.get('source') == 'stage2':
            data.setdefault('autowrite', {})['procedures'] = {'source': 'stage2', 'note': 'كُتبت من الملخص (طلب واحد)',
                                                              'newer': '', 'notice': '', 'manual': False, 'at': _now()}
    if 'attachments' in res:
        items, errs = res['attachments']
        if errs or not items:
            data['attachments_ai'] = {'items': [], 'errors': errs, 'at': _now(), 'stale': False}
            if errs:
                notes.append('المرفقات: رُفضت قائمة النموذج (' + '؛ '.join(errs[:2]) + ') — بُنيت بالكود')
        else:
            data['attachments_ai'] = {'items': items, 'errors': [], 'at': _now(), 'stale': False}
        try:
            case_attachments.sync_attachments(base, data)
        except Exception:
            pass
    s.update(sig=sig, at=_now(), source=source, error='', notes=notes, errors=errs_final, missing=missing_inputs(base, data))
    cw.write_case_json(base, data)
    return s


def _provider_line(source):
    import ai_call_log
    if source.startswith('browser'):
        site = source.split(':', 1)[1] if ':' in source else ''
        return {'provider': f'عبر المتصفح ({site})' if site else 'عبر المتصفح', 'model': '', 'purpose': PURPOSE}
    prov = ai_call_log.last_provider()
    return {'provider': prov or 'جيميناي (API)', 'model': ai_call_log.last_model(), 'purpose': PURPOSE}


def run(base, data, ask, force=False, replace_manual=False):
    """الطلب الواحد + التحقق + إعادة واحدة للمرفوض. يرجع حالة المرحلة (dict). بلا صحيفة ← لا طلب.
    replace_manual: «أعد الكتابة» بعد تأكيد الخبير ← يُستبدل موضوعه اليدوي (التشغيل التلقائي لا يمسّه أبداً)."""
    import ai_call_log
    s = state(data)
    if replace_manual:
        data['subject_edited'] = False
    miss = missing_inputs(base, data)
    s['missing'] = miss
    if 'صحيفة الدعوى' in miss:
        s.update(error='', blocked='صحيفة الدعوى غير موجودة — لا يُكتب الموضوع قبلها', at=_now())
        if not (data.get('subject') or '').strip():              # موضوع أدخله الخبير بيده لا تُخفَّض حالته
            cm.set_step(data, 'subject', 'needs_input', 'ينقص: ' + '، '.join(miss) + ' — لا يُكتب الموضوع قبل صحيفة الدعوى')
        cw.write_case_json(base, data)
        return s
    s.pop('blocked', None)
    if not force and not needs_run(base, data):
        return s
    if ask is None:
        s.update(error='لا مزوّد ذكاء متاح للكتابة — استعمل «اكتب عبر المتصفح»', at=_now())
        cm.set_step(data, 'subject', 'failed', s['error'])
        cw.write_case_json(base, data)
        return s
    sig = signature(base, data)
    if data.get('attachments_ai'):
        data['attachments_ai']['stale'] = True
    cm.set_step(data, 'subject', 'running')
    try:
        ai_call_log.detail('الموضوع والإجراءات والمرفقات (طلب واحد)')
        obj = parse(ask(build_prompt(base, data)))
    except Exception as e:
        import case_folder as cf
        if cf.is_key_failure(e):
            cm.set_step(data, 'subject', 'failed', f'تعذّرت كتابة الموضوع: {e}')
            cw.write_case_json(base, data)
            raise
        ai_call_log.verdict(False, str(e) or e.__class__.__name__)
        s.update(error=f'تعذّرت كتابة الموضوع: {str(e) or e.__class__.__name__}', at=_now())
        cm.set_step(data, 'subject', 'failed', s['error'])
        cw.write_case_json(base, data)
        return s
    res = check(base, data, obj)
    bad = {k: v[1] for k, v in res.items() if v[1]}
    ai_call_log.verdict(not bad, 'قُبل الموضوع والإجراءات والمرفقات' if not bad else
                        'رُفض: ' + '؛ '.join(f'{LABELS[k]}: {v[0]}' for k, v in bad.items()))
    if bad:                                              # إعادة واحدة فقط بقائمة الأخطاء للمرفوض وحده
        try:
            ai_call_log.detail('إعادة المرفوض بقائمة الأخطاء: ' + '، '.join(LABELS[k] for k in bad))
            obj2 = parse(ask(build_prompt(base, data, errors=bad, only=set(bad))))
            res2 = check(base, data, obj2, only=set(bad))
            for k, v in res2.items():
                if not v[1] or len(v[1]) < len(res[k][1]):
                    res[k] = v
            still = {k: res[k][1] for k in bad if res[k][1]}
            ai_call_log.verdict(not still, 'صُحِّح المرفوض' if not still else
                                'بقي مرفوضاً: ' + '؛ '.join(f'{LABELS[k]}: {v[0]}' for k, v in still.items()))
        except Exception as e:
            import case_folder as cf
            if cf.is_key_failure(e):
                raise
            ai_call_log.verdict(False, str(e) or e.__class__.__name__)
    final = {k: v[1] for k, v in res.items() if v[1]}
    return _store(base, data, res, _provider_line('api'), 'api', final, sig)


def apply_reply(base, data, text, source='browser'):
    """ردّ لُصق من المتصفح ← نفس التحقق ونفس الحفظ (بلا إعادة تلقائية: الأخطاء تظهر للخبير ليعيد اللصق)."""
    s = state(data)
    obj = parse(text)
    res = check(base, data, obj)
    final = {k: v[1] for k, v in res.items() if v[1]}
    return _store(base, data, res, _provider_line(source), source, final, signature(base, data)) | {'rejected': final}


def status_line(base, data):
    """(نص، أحمر؟) لبطاقة الموضوع: ما ينقص، أو سبب الفشل، أو أخطاء التحقق."""
    s = data.get('stage2') or {}
    if s.get('blocked'):
        return 'ينقص: ' + '، '.join(s.get('missing') or ['صحيفة الدعوى']) + ' — لا يُكتب الموضوع قبل صحيفة الدعوى', True
    if s.get('error'):
        return s['error'], True
    chk = data.get('subject_check') or {}
    if chk.get('errors'):
        return 'الموضوع لم يجتز التحقق بالكود (أحمر): ' + '؛ '.join(chk['errors']), True
    miss = [m for m in s.get('missing') or [] if m != 'صحيفة الدعوى']
    notes = list(s.get('notes') or [])
    if miss:
        notes.insert(0, 'ينقص من الملفات الأساسية: ' + '، '.join(miss))
    return ' — '.join(notes), bool(miss)
