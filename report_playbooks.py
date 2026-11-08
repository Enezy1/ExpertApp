# ===== report_playbooks.py — القوالب حسب نوع القضية + محاور المأمورية + الحقائق المسموحة لكل محور (2026-10-20) =====
# المحور = سؤال القاضي كما هو: قسم واحد لكل نوع سؤال من المأمورية (بعنوان قصير 3–8 كلمات لا نسخ نص المأمورية).
# كل محور يجيب عن سؤاله فقط (الجزء 8): العلاقة لا فواتير ولا مديونية؛ الإخلال الإخلال وسببه بلا جداول حساب؛ الفواتير
# والجداول والحساب في المديونية/تصفية الحساب فقط؛ الدفاع في محوره. ALLOWED = أنواع الحقائق المسموح ذكرها في كل محور،
# ويرفض report_audit أي رقم/مبلغ في محور من خارج نوعه.
import re

AX_REL, AX_BREACH, AX_NATURE, AX_VALUE, AX_DEBT, AX_DEF, AX_GEN = (
    'relation', 'breach', 'nature', 'value', 'debt', 'defense', 'general')
AXIS_ORDER = (AX_REL, AX_BREACH, AX_NATURE, AX_VALUE, AX_DEBT, AX_DEF, AX_GEN)

# أنواع الحقائق (لخانات العبارات المرجعية وللمدقّق)
F_PARTY, F_CONTRACT, F_ORDER, F_ORDER_VALUE = 'party', 'contract', 'order', 'order_value'
F_INVOICE, F_PAYMENT, F_DEBT, F_CLAIM, F_STATEMENT = 'invoice', 'payment', 'debt', 'claim', 'statement'
F_MINUTES, F_DEFENSE = 'minutes', 'defense'

ALLOWED = {
    AX_REL: {F_PARTY, F_CONTRACT, F_ORDER, F_ORDER_VALUE},
    AX_BREACH: {F_PARTY, F_CONTRACT, F_ORDER, F_MINUTES},
    AX_NATURE: {F_PARTY, F_CONTRACT, F_ORDER, F_ORDER_VALUE},
    AX_VALUE: {F_PARTY, F_CONTRACT, F_ORDER, F_ORDER_VALUE},
    AX_DEBT: {F_PARTY, F_CONTRACT, F_ORDER, F_INVOICE, F_PAYMENT, F_DEBT, F_CLAIM, F_STATEMENT},
    AX_DEF: {F_PARTY, F_CONTRACT, F_MINUTES, F_DEFENSE},
    AX_GEN: {F_PARTY, F_CONTRACT, F_ORDER, F_MINUTES},
}

CT_TELECOM, CT_CONTRACTING, CT_PARTNERSHIP, CT_GENERAL = 'اتصالات', 'مقاولة_توريد', 'شراكة', 'عام'

PLAYBOOKS = {
    CT_TELECOM: {
        'titles': {AX_REL: 'طبيعة العلاقة والتزامات الطرفين', AX_BREACH: 'الإخلال بالالتزامات وسببه',
                   AX_NATURE: 'طبيعة عقود الخدمات وطلباتها', AX_VALUE: 'القيمة الإجمالية وطريقة السداد',
                   AX_DEBT: 'المديونية والغرامات والمسدد والمتبقي', AX_DEF: 'أوجه دفاع طرفي الدعوى'},
        'contract_word': 'عقد الاشتراك',
        'order_word': 'طلب خدمة الخط',
        'scope': 'تقديم خدمات الاتصالات المتنقلة',
        'plaintiff_duty': 'تقديم خدمات الاتصالات والأجهزة محل طلبات الخدمة',
        'defendant_duty': 'سداد الفواتير الشهرية وأقساط الأجهزة في مواعيدها والوفاء بمدة الالتزام',
        'breach': 'الامتناع عن سداد الفواتير الشهرية المستحقة',
        'consideration': 'اشتراك شهري',
        'p_short': 'بتقديم خدمات الاتصالات والأجهزة', 'd_short': 'بسداد الفواتير الشهرية',
    },
    CT_CONTRACTING: {
        'titles': {AX_REL: 'طبيعة العلاقة والتزامات الطرفين', AX_BREACH: 'الإخلال بالالتزامات وسببه',
                   AX_NATURE: 'طبيعة العقود وملحقاتها', AX_VALUE: 'قيمة العقود وطريقة السداد',
                   AX_DEBT: 'تصفية الحساب بين الطرفين', AX_DEF: 'أوجه دفاع طرفي الدعوى'},
        'contract_word': 'العقد', 'order_word': 'أمر العمل',
        'scope': 'تنفيذ الأعمال والتوريدات المتفق عليها',
        'plaintiff_duty': 'تنفيذ ما التزم به من أعمال أو توريدات وفق شروط العقد ومواصفاته',
        'defendant_duty': 'سداد قيمة الأعمال والتوريدات المنفذة وفق شروط الدفع المتفق عليها',
        'breach': 'عدم سداد المستحقات في مواعيدها',
        'consideration': 'قيمة العقد',
        'p_short': 'بتنفيذ الأعمال المتفق عليها', 'd_short': 'بسداد قيمتها',
    },
    CT_PARTNERSHIP: {
        'titles': {AX_REL: 'طبيعة العلاقة والتزامات الطرفين', AX_BREACH: 'الإخلال بالالتزامات وسببه',
                   AX_NATURE: 'طبيعة عقد الشراكة', AX_VALUE: 'رأس المال وطريقة السداد',
                   AX_DEBT: 'تصفية الحساب بين الشريكين', AX_DEF: 'أوجه دفاع طرفي الدعوى'},
        'contract_word': 'عقد الشراكة', 'order_word': 'الملحق',
        'scope': 'المشاركة في النشاط المتفق عليه',
        'plaintiff_duty': 'المساهمة بحصته والمشاركة في الإدارة وفق عقد الشراكة',
        'defendant_duty': 'المساهمة بحصته وتوزيع الأرباح وتحمل الخسائر وفق عقد الشراكة',
        'breach': 'عدم الوفاء بالحصة أو بنصيب الشريك',
        'consideration': 'الحصص',
        'p_short': 'بالمساهمة بحصته', 'd_short': 'بالمساهمة بحصته وتوزيع الأرباح',
    },
    CT_GENERAL: {
        'titles': {AX_REL: 'طبيعة العلاقة والتزامات الطرفين', AX_BREACH: 'الإخلال بالالتزامات وسببه',
                   AX_NATURE: 'طبيعة العقود المبرمة', AX_VALUE: 'القيمة وطريقة السداد',
                   AX_DEBT: 'تصفية الحساب بين الطرفين', AX_DEF: 'أوجه دفاع طرفي الدعوى'},
        'contract_word': 'العقد', 'order_word': 'الملحق',
        'scope': 'الالتزامات المتبادلة الواردة به',
        'plaintiff_duty': 'الوفاء بما رتبه العقد عليه من التزامات في مواعيدها',
        'defendant_duty': 'الوفاء بما رتبه العقد عليه من التزامات وسداد المستحق في مواعيده',
        'breach': 'عدم الوفاء بالالتزامات التعاقدية',
        'consideration': 'المقابل المتفق عليه',
        'p_short': 'بالوفاء بالتزاماته', 'd_short': 'بسداد المستحق',
    },
}


def case_type(data):
    """نوع القضية للقالب: اتصالات (شركة اتصالات مدعية/فواتير) | مقاولة_توريد | شراكة | عام."""
    import research_pipeline as rp
    t = data.get('subject_type') or ''
    if t == 'اتصالات':
        return CT_TELECOM
    try:
        import telecom_config
        c = data.get('case') or {}
        names = ' '.join([c.get('plaintiff') or '', c.get('company') or '', c.get('title') or ''] +
                         [r.get('name') or '' for r in ((data.get('procedures') or {}).get('attendance') or {})
                          .get('result') or [] if r.get('role') == 'plaintiff'])
        if telecom_config.match_company(names):
            return CT_TELECOM
    except Exception:
        pass
    old = rp.case_type(data)
    if old == 'باطن_شراكة' and 'شراك' in rp._norm(data.get('subject') or ''):
        return CT_PARTNERSHIP
    return CT_CONTRACTING if old == 'مقاولة_توريد' and (data.get('subject') or '') else CT_GENERAL


def playbook(ctype):
    return PLAYBOOKS.get(ctype) or PLAYBOOKS[CT_GENERAL]


# ---------- محاور المأمورية ----------

def _n(t):
    import research_pipeline as rp
    return rp._norm(t)


def classify(text):
    """نوع سؤال البند بالكلمات (بلا ذكاء)."""
    n = _n(text)
    if re.search(r'دفاع|دفوع|اعتراض', n):
        return AX_DEF
    if re.search(r'مديونيه|غرامات|الغرامه|ذمه|المسدده|المتبقيه|المترصده|تصفيه|حساب|المبالغ|المستحق', n):
        return AX_DEBT
    if re.search(r'(?:^|\s)(?:اخل|المخل|الاخلال|بالاخلال)', n):
        return AX_BREACH
    if re.search(r'قيمتها|طريقه\s*سداد|القيمه\s+الاجماليه', n):
        return AX_VALUE
    if 'طبيعه' in n and re.search(r'عقود|نماذج|طلب', n) and 'علاقه' not in n:
        return AX_NATURE
    if re.search(r'علاقه|التزامات|حقوق', n):
        return AX_REL
    return AX_GEN


def _short(text, limit=8):
    """عنوان عام قصير (≤ 8 كلمات) من نص البند: بلا «بيان/وبيان» الافتتاحية والفواصل."""
    t = re.sub(r'^\s*و?(?:بيان|تحديد|بحث)\s+(?:عما\s+إذا|ما\s+إذا|ما)?\s*', '', ' '.join(str(text).split()))
    words = re.sub(r'[،,.:؛()]', ' ', t).split()
    return ' '.join(words[:limit]) or 'ما يفيد الدعوى'


def mission_axes(data, ctype=None):
    """[{key, kind, title, ordinal, point_ids, clauses}] — محور واحد لكل نوع سؤال بترتيب أول ظهوره (العام يبقى منفرداً)."""
    import research_pipeline as rp
    ctype = ctype or case_type(data)
    pb = playbook(ctype)
    points = (data.get('mission') or {}).get('points') or []
    clauses = rp.mission_clauses(points)
    axes, by_kind = [], {}
    for c in clauses:
        k = classify(c['text'])
        if k != AX_GEN and k in by_kind:
            by_kind[k]['clauses'].append(c['text'])
            if c['id'] not in by_kind[k]['point_ids']:
                by_kind[k]['point_ids'].append(c['id'])
            continue
        ax = {'kind': k, 'clauses': [c['text']], 'point_ids': [c['id']]}
        axes.append(ax)
        if k != AX_GEN:
            by_kind[k] = ax
    for i, a in enumerate(axes):
        a['ordinal'] = rp.ORDINALS[i] if i < len(rp.ORDINALS) else str(i + 1)
        a['title'] = pb['titles'].get(a['kind']) or _short(a['clauses'][0])
        a['key'] = f"V{i + 1}_{a['kind']}"
    return axes
