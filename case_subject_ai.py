# ===== case_subject_ai.py — كتابة «الموضوع» بالذكاء الاصطناعي بأسلوب نماذج الخبير (لكل القضايا) (2026-10-17) =====
# بدل قالب فراغات: (1) يستخرج النموذج حقائق منظّمة JSON من نص الصحيفة (المقروء بصرياً بـGemini أولاً)، (2) الكود يتحقق من كل
# تاريخ (case_subject_telecom.verify: بقيمته في الصحيفة بأي صيغة) ومبلغ (amounts.py: رقم=حروف) ورقم مدة/عقد وعبارة (ورودها
# حرفياً)، (3) يُرسل لمزوّد «صياغة التقرير» الحقائق المتحقَّق منها فقط + أقرب النماذج من «نماذج_صياغة_الموضوع.md» (few-shot)
# ليكتب كما في النماذج، (4) فحص: لا رقم ولا تاريخ في الناتج خارج الحقائق المتحقَّق منها؛ مخالفة ← إعادة بطلب أشد ثم تركيب
# احتياطي حتمي من الحقائق. ما لم يتحقق يُحذف من الجملة (لا «[يُكتب]» داخل النص) ويُعرض في سطر منفصل فوق المحرر.
# ملف النماذج يضيف إليه الخبير بنفسه (زر «احفظ هذا النص كنموذج»): يُنشأ أول مرة بنموذجين معتمدين.
import json
import os
import re

import case_subject_telecom as st
import drafting_library as dl

STYLE_FILE = dl.SUBJECT_FILE      # في مجلد البرنامج، ويُحمَّل عند كل توليد (drafting_library)
STYLE_PATH = None                # الاختبارات تستبدله

MODEL1 = ('جاءت المدعية بصحيفة مفادها أنه بموجب العقد المؤرخ 19/4/2018 تعهدت المدعية بصفتها مقاول من الباطن للمدعى عليها '
          'الأولى بصفتها مقاول رئيسي بتركيب وتشغيل وتسليم وصيانة كافة معدات المختبرات العلمية، وذلك لصالح المدعى عليها '
          'الثانية عن العقد الرئيسي المختص بإنشاء وإنجاز وتأثيث مبنى الإدارة العامة للمعلومات الجنائية. وأفادت المدعية '
          'على حسب دعواها أنها قامت بالتوريد وتم اعتماد الأجهزة من قبل مالك المشروع، إلا أن المدعى عليها الأولى أخلّت '
          'بالتزاماتها التعاقدية وذلك في عدم سداد مستحقاتها المالية.')
MODEL2 = ('جاءت المدعية بصحيفة مفادها أنها بموجب عقد اشتراك مؤرخ (تاريخ العقد) قامت المدعية بتقديم خدمات الاتصال لصالح '
          'المدعى عليه، وذلك مقابل اشتراك شهري (القيمة) مع مدة التزام وقدرها (المدة). وأفادت المدعية على حسب دعواها أنها '
          'قدّمت الخدمة للمدعى عليه إلا أن الأخير لم يلتزم بالسداد، فتم رفع الدعوى الماثلة، وطلبت (المطالبة).')
# احتياطي إن فُقد ملف المكتبة (الأصل: نماذج_صياغة_الموضوع.md)
DEFAULT_MODELS = [
    {'title': 'نموذج 1 — مقاولة من الباطن', 'type': 'مقاول_باطن',
     'tags': ['مقاولة', 'مقاول', 'باطن', 'توريد', 'تركيب', 'مشروع', 'أعمال'], 'text': MODEL1},
    {'title': 'نموذج 2 — اتصالات', 'type': 'اتصالات',
     'tags': ['اتصالات', 'اشتراك', 'خدمات الاتصال', 'هاتف', 'إنترنت', 'خط', 'باقة'], 'text': MODEL2},
]
DEFAULT_RULES = ('الموضوع من الصحيفة فقط ولا يُذكر دفاع المدعى عليه؛ الصفة من الصحيفة؛ الأرقام والتواريخ من الصحيفة بعد '
                 'تحقق الكود؛ ما لم يُتحقق منه يُحذف دون فراغات؛ الخبير مذكّر.')
CASE_TYPES = {'عقد_مقاولة': 'عقد مقاولة/توريد', 'مقاول_باطن': 'مقاول من الباطن', 'عقد_ملحق': 'عقد وعقود ملحقة',
              'سداد_واخلال': 'عقد مع سداد المدعي', 'بلا_عقد': 'دعوى بلا عقد', 'اتصالات': 'اشتراك اتصالات',
              'استئناف': 'استئناف', 'استعانة': 'استعانة', 'شكوى_جزائية': 'شكوى جزائية / إثبات حالة'}
HEADER = ('# نماذج صياغة الموضوع'+chr(10)*2+
          'أمثلة معتمدة يُرسل أقربها إلى الذكاء الاصطناعي مع كل طلب ليكتب «الموضوع» بأسلوبها. أضف نماذجك بنفس الصيغة '
          '(أو من زر «احفظ هذا النص كنموذج» في محرر الموضوع):'+chr(10)+
          '`## عنوان النموذج` ثم سطرا `النوع: مفتاح` و`الكلمات: كلمة، كلمة` ثم نص النموذج. الأقواس (…) في النموذج تعني قيمة تُملأ من الصحيفة.'+chr(10)*2)


def style_path():
    return STYLE_PATH or dl.program_path(STYLE_FILE)


def ensure_style_file():
    """ملف المكتبة موجود في مجلد البرنامج؛ إن فُقد (أو كان مسار الاختبار) يُنشأ بالنموذجين الاحتياطيين."""
    path = style_path()
    if not os.path.exists(path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(HEADER + dl.MODELS_HEAD + chr(10)*2 + chr(10).join(dl.render(m) for m in DEFAULT_MODELS))
        except OSError:
            pass
    return path


def load_library():
    """(القواعد، النماذج) من الملف عند كل توليد."""
    ensure_style_file()
    rules, models = dl.load(STYLE_FILE, STYLE_PATH)
    return rules or DEFAULT_RULES, models or [dict(m) for m in DEFAULT_MODELS]


def load_models():
    return load_library()[1]


def add_model(title, tags, text, kind=''):
    """يضيف النص المعتمد نموذجاً جديداً إلى الملف تحت النوع المناسب (يرجع المسار)."""
    ensure_style_file()
    return dl.append_model(STYLE_FILE, {'title': title.strip() or 'نموذج جديد', 'type': kind, 'tags': list(tags),
                                        'text': text}, STYLE_PATH)


_TYPE_CUES = (
    ('استعانة', ('طلب الاستعانة', 'ملف الاستعانة')),
    ('شكوى_جزائية', ('الشاكي', 'المشكو بحقه', 'المشكو بحقها', 'لدى نيابة', 'إثبات حالة', 'اثبات حالة')),
    ('استئناف', ('المستأنف', 'المستأنفة', 'الطاعن', 'استأنف', 'صحيفة الاستئناف', 'صحيفة استئنافه')),
    ('مقاول_باطن', ('من الباطن', 'مقاول رئيسي', 'المقاول الرئيسي')),
    ('عقد_ملحق', ('عقد ملحق', 'ملحق للعقد', 'ملحق العقد', 'عقد آخر', 'أمر تغييري', 'أمر تعديل', 'ملحق رقم')),
)
_CONTRACT_WORDS = ('عقد', 'العقد', 'مناقصة', 'أمر شراء', 'اتفاقية', 'اتفاق', 'تعهد', 'بموجب')


def detect_type(plaint_text, hint=''):
    """(مفتاح النوع، واضح؟). hint='اتصالات' من بيانات القضية. غير واضح ← (أقرب نوع، False) ويسأل الخبير.
    الترتيب: الأقوى دلالة أولاً (استعانة، شكوى، استئناف، باطن، ملحق) ثم سداد المدعي وإخلال، ثم عقد عام، وإلا بلا عقد."""
    if hint == 'اتصالات':
        return 'اتصالات', True
    t = st._display(plaint_text or '')
    if not t.strip():
        return 'عقد_مقاولة', False
    for kind, cues in _TYPE_CUES:
        if any(c in t for c in cues):
            return kind, True
    has_contract = any(w in t for w in _CONTRACT_WORDS)
    if has_contract and re.search(r'(سداد|سدد|دفع)\w*\s+(كامل|كافة|جميع)', t):
        return 'سداد_واخلال', True
    if re.search(r'اشتراك|خدمات الاتصال|خط هاتف', t):
        return 'اتصالات', True
    if has_contract and re.search(r'عقد|مناقصة|أمر شراء', t):
        return 'عقد_مقاولة', True
    if not re.search(r'عقد|مناقصة|اتفاق', t):
        return 'بلا_عقد', True
    return 'عقد_مقاولة', False


def pick_models(models, plaint_text, hint='', k=2, kind=''):
    """النموذج المطابق للنوع أولاً، ثم أقرب النماذج بتقاطع الكلمات المفتاحية مع الصحيفة (hint: 'اتصالات').
    لا تقاطع ← الأول (أقرب لغةً)."""
    t = st._display(plaint_text or '') + ' ' + hint
    scored = []
    for i, m in enumerate(models):
        s = sum(1 for tag in m['tags'] if tag and tag in t)
        if hint and hint in m['tags']:
            s += 3
        scored.append((-s, i, m))
    scored.sort(key=lambda x: (x[0], x[1]))
    typed = [m for m in models if kind and m.get('type') == kind][-1:]            # الأحدث إضافةً لذلك النوع
    best = typed + [m for s, _i, m in scored if s < 0 and m not in typed]
    return best[:k] or [scored[0][2]]


# ---------- الحقائق ----------
FACT_LABELS = {'contract_date': 'تاريخ العقد', 'contract_number': 'رقم العقد', 'object': 'محل العقد',
               'amount': 'قيمة العقد', 'duration': 'مدة العقد', 'plaintiff_capacity': 'صفة المدعية',
               'defendant_capacity': 'صفة المدعى عليهم', 'breach': 'إخلال المدعى عليه',
               'claim': 'المطالبة'}
CORE = ('claim',)                 # غيابها أو عدم التحقق منها يوقف الاعتماد التلقائي؛ الباقي اختياري (العقد ليس شرطاً)


def build_facts_prompt(plaint_text):
    return (
        "أنت تستخرج وقائع من صحيفة دعوى. انسخ كل قيمة حرفياً كما وردت في نص الصحيفة أدناه دون تعديل أو ترجمة أو تحويل أرقام "
        "أو اختصار أو تصحيح. إن لم تذكر الصحيفة القيمة صراحةً فاكتب null — لا تخمّن ولا تحسب ولا تستنتج.\n"
        'أجب بـ JSON فقط بالشكل:\n'
        '{"plaintiff_capacity":"صفة المدعية كما وردت (مقاول من الباطن، مؤجر، شركة اتصالات…)",'
        '"defendant_capacity":"صفة المدعى عليهم كما وردت (مقاول رئيسي، مستأجر، مشترك…)",'
        '"contract_date":"تاريخ العقد (يوم/شهر/سنة فقط)","contract_number":"رقم العقد إن ذُكر",'
        '"object":"محل العقد والتزامات الطرفين كما وردت","amount":"قيمة العقد أو الاشتراك مع عملتها",'
        '"duration":"مدة العقد أو الالتزام مع وحدتها",'
        '"breach":"ما أخلّ به المدعى عليه كما ورد",'
        '"claim":"طلب المدعية الختامي (من «الحكم بـ…» أو «بإلزام…» دون «ليسمع») متضمناً المبلغ"}\n\n'
        "نص الصحيفة:\n" + (plaint_text or '')[:st.MAX_PROMPT_CHARS])


def verify_facts(raw, plaint, alerts, rejected):
    """{مفتاح: قيمة متحقَّق منها}، ويملأ rejected [(تسمية، سبب)] لما أعاده النموذج ولم يتحقق، وalerts للمبالغ."""
    kinds = {'contract_date': 'date', 'contract_number': 'number', 'amount': 'amount', 'duration': 'duration',
             'object': 'excerpt', 'plaintiff_capacity': 'excerpt', 'defendant_capacity': 'excerpt',
             'breach': 'excerpt', 'claim': 'claim'}
    ok = {}
    for key, kind in kinds.items():
        val, why = st.verify(kind, raw.get(key), plaint, alerts, FACT_LABELS[key])
        if val:
            ok[key] = val
        elif st._clean(raw.get(key)):
            rejected.append((FACT_LABELS[key], why))
    if 'contract_date' not in ok and 'contract_number' not in ok and st._clean(raw.get('contract_date')):
        num, _w = st.verify('number', raw.get('contract_date'), plaint)        # رقم عقد وُضع في خانة التاريخ
        if num and not st.find_date(num):
            ok['contract_number'] = num
    return ok


def allowed_numbers(facts):
    nums = set()
    for v in facts.values():
        nums |= {format(d.normalize(), 'f') for d in st._decimals(v)}
    return nums


def unverified_numbers(text, facts):
    """أرقام الناتج غير الموجودة في الحقائق المتحقَّق منها."""
    allowed = allowed_numbers(facts)
    bad = []
    for n, _s, _e in st._tokens(st._display(text)):
        if st._is_num(n) and n not in allowed:
            bad.append(n)
    return bad


def build_combined_prompt(plaint_text, models, parties, rules=''):
    """طلب واحد: الحقائق JSON + حقل text بالصياغة بأسلوب النماذج (المسار السريع). يُقبل text فقط إن تحقّقت كل الحقائق
    المُعادة ولم يخالف قاعدة الأرقام؛ وإلا يُعاد التوليد بالطلب المنفصل من الحقائق المتحقَّق منها."""
    ex = '\n\n'.join(f"[{m['title']}]\n{m['text']}" for m in models)
    return (build_facts_prompt(plaint_text).split('\n\nنص الصحيفة:')[0]
            + '\n\nأضف إلى JSON حقلاً أخيراً "text": فقرة «الموضوع» مكتوبة بأسلوب النماذج المعتمدة أدناه (لغة قضائية سليمة يفهم '
              'منها القاضي من أول قراءة؛ لا تخترع؛ لا فراغات ولا أقواس؛ لا تكرر عبارة «عقد مؤرخ»؛ الأرقام والتواريخ كما في الصحيفة '
              'حرفياً؛ الأسماء لا تُذكر بل الصفات؛ ما لم يرد اتركه بصمت؛ النماذج للأسلوب فقط).\n'
              f"قواعد الصياغة (من مكتبة الخبير):\n{rules}\n\nالنماذج المعتمدة:\n{ex}\n\nالأطراف: {json.dumps(parties, ensure_ascii=False)}\n\n"
              "نص الصحيفة:\n" + (plaint_text or '')[:st.MAX_PROMPT_CHARS])


def build_generation_prompt(facts, models, parties, strict_bad=None, rules=''):
    ex = '\n\n'.join(f"[{m['title']}]\n{m['text']}" for m in models)
    p = ("أنت خبير قضائي تكتب فقرة «الموضوع» في تقرير الخبرة. اكتب كما في النماذج المعتمدة أدناه، بلغة قضائية سليمة، "
         "بحيث يفهم منها القاضي من أول قراءة: من المدعية وصفتها، ومن المدعى عليهم وصفاتهم، وما العقد وتاريخه ومحله وقيمته "
         "ومدته إن وردت، وما أخلّ به المدعى عليه، وما طلبته.\n"
         "القواعد: (1) استعمل فقط ما في «الوقائع المتحقَّق منها» ولا تخترع معلومة غير واردة؛ ما لم يرد فيها اتركه بصمت دون "
         "فراغات أو أقواس أو عبارة «يُكتب». (2) انقل الأرقام والتواريخ والمبالغ حرفياً كما هي ولا تضف رقماً أو تاريخاً غيرها. "
         "(3) لا تكرر عبارة «عقد مؤرخ». (4) الأسماء لا تُذكر؛ يُشار إلى الأطراف بصفاتهم (المدعية، المدعى عليه…) مع مراعاة "
         "الجنس والعدد من «الأطراف». (5) النماذج للأسلوب فقط: لا تنقل منها وقائع.\n\n"
         f"قواعد الصياغة (من مكتبة الخبير):\n{rules}\n\nالنماذج المعتمدة:\n{ex}\n\nالأطراف: {json.dumps(parties, ensure_ascii=False)}\n"
         f"الوقائع المتحقَّق منها:\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n\n")
    if strict_bad:
        p += ("تنبيه: الصياغة السابقة ذكرت أرقاماً غير موجودة في الوقائع: " + '، '.join(strict_bad) +
              ". أعد الكتابة دون أي رقم غير وارد حرفياً في الوقائع.\n")
    return p + "أعد الفقرة فقط، نصاً عادياً بلا ترقيم ولا تنسيق."


def compose_fallback(facts, parties):
    """تركيب حتمي من الحقائق المتحقَّق منها فقط (بلا فراغات)، عند فشل النموذج أو مخالفته."""
    pl = f"بصفتها {facts['plaintiff_capacity']}" if facts.get('plaintiff_capacity') else ''
    df = parties.get('defendant_word', 'المدعى عليه')
    rel = 'بموجب العقد' + (f" المؤرخ {facts['contract_date']}" if facts.get('contract_date') else '')
    if facts.get('contract_number'):
        rel += f" رقم {facts['contract_number']}"
    body = ''
    if facts.get('object'):
        body = f" {facts['object']}"
    if facts.get('amount'):
        body += f"، وذلك مقابل مبلغ {facts['amount']}"
    if facts.get('duration'):
        body += f" لمدة {facts['duration']}"
    first = f"جاءت المدعية بصحيفة مفادها أنه {rel}{(' ' + pl) if pl else ''}{body}."
    second = ''
    if facts.get('performed') or facts.get('breach'):
        second = ' وأفادت المدعية على حسب دعواها'
        if facts.get('performed'):
            second += f" {facts['performed']}"
        if facts.get('breach'):
            second += f"{'، إلا أن' if facts.get('performed') else ' أن'} {df} {facts['breach']}"
        second += '.'
    third = f" وطلبت {facts['claim']}." if facts.get('claim') else ''
    return re.sub(r'\s+', ' ', first + second + third).strip()


CONTRACTS_HEAD = ("\n\nالعقود المستخرجة من مستندات القضية (المرجع لبيانات العقد: نوعه وتاريخه وأطرافه ونطاقه وقيمته؛ "
                  "متحقَّق منها حرفياً؛ ما وُسم «خارج نطاق الدعوى» أو «العقد الرئيسي» لا يُذكر إلا إن لزم لفهم العلاقة):\n")


def with_contracts(prompt, contracts_text):
    """يُلحق كتلة العقود (من case_contracts) بالطلب قبل نص الصحيفة/التعليمات الختامية."""
    return prompt + CONTRACTS_HEAD + contracts_text if contracts_text else prompt


def compose_telecom(facts, kind='m'):
    """صيغة الاتصالات المعتمدة من الخبير حرفياً (2026-10-19)، من الحقائق المتحقَّق منها فقط؛ لا شيء بعد
    «فتم رفع الدعوى الماثلة». الناقص يُحذف بصمت (لا «[يُكتب]»)."""
    import amounts
    who, last, neg = st._FORMS[kind]
    pron = {'m': 'ه', 'f': 'ها', 'p': 'هم'}[kind]
    date = f" مؤرخ {facts['contract_date']}" if facts.get('contract_date') else ''
    monthly = f" قيمته {facts['amount']}" if facts.get('amount') else ''
    owed = amounts.digits_to_decimal(facts.get('claim') or '')
    tail = (f" مما ترصد في ذمت{pron} مبلغ ({amounts.fmt_kwd(owed)})" if owed is not None else '')
    return (f"جاءت المدعية بصحيفة مفادها أنه بموجب عقد اشتراك{date} مبرم بينها وبين {who}، تعهدت المدعية بتقديم "
            f"خدمات هاتفية لخطوط الهواتف المتنقلة ملحق بها عدد من الخدمات والأجهزة لصالح {who}، وذلك مقابل اشتراك "
            f"شهري{monthly}، وأفادت المدعية على حسب دعواها أنها قدمت الخدمة لل{who[2:]} إلا أن {last} {neg} "
            f"بالسداد{tail}، فتم رفع الدعوى الماثلة.")


def build_subject(plaint_text, defendants, ask, plaintiffs=None, hint='', case_type='', contracts=None):
    """يرجع dict: text، missing (أسماء ما لم يرد أو لم يتحقق)، absent، unverified، rejected، alerts، kind، note، ocr_fixes،
    models. plaint_text فارغ أو ask=None ← نص فارغ وقائمة نواقص. ما يرفعه ask يمرّ كما هو."""
    plaint_text, ocr_fixes = st.fix_ocr(plaint_text)
    plaint = st.Plaint(plaint_text) if (plaint_text or '').strip() else None
    kind, note = st.defendant_kind(defendants, plaint)
    alerts, rejected, facts = [], [], {}
    out = {'text': '', 'rejected': rejected, 'alerts': alerts, 'kind': kind, 'note': note, 'ocr_fixes': ocr_fixes,
           'models': []}
    if plaint is None or ask is None:
        out.update(missing=[FACT_LABELS[k] for k in FACT_LABELS], absent=list(FACT_LABELS.values()), unverified=[])
        return out
    rules, library = load_library()
    ctype, clear = (case_type, True) if case_type in CASE_TYPES else detect_type(plaint_text, hint)
    out.update(type=ctype, type_unclear=not clear)
    models = pick_models(library, plaint_text, hint, kind=ctype)
    out['models'] = [m['title'] for m in models]
    word = st._FORMS[kind][0]
    parties = {'plaintiffs': [p for p in (plaintiffs or []) if p][:2], 'defendants_count': len(defendants or []),
               'defendant_word': word, 'defendant_names_for_gender_only': [d for d in (defendants or []) if d][:3]}
    import case_contracts
    con_text, con_allowed = case_contracts.subject_context(contracts or {})
    raw = st.parse_response(ask(with_contracts(build_combined_prompt(plaint_text, models, parties, rules), con_text)))
    facts = verify_facts(raw, plaint, alerts, rejected)
    import ai_call_log
    ai_call_log.verdict(bool(facts), (f'{len(facts)} حقيقة متحقَّقة' if facts else 'لم تتحقق أي حقيقة')
                        + (f'؛ رُفض: {"؛ ".join(l for l, _w in rejected[:4])}' if rejected else ''))
    for k, v in case_contracts.main_contract_facts(contracts or {}).items():      # العقد من المستندات لا من حقول يدوية
        facts.setdefault(k, v)
    if con_allowed:
        facts['contracts_from_documents'] = ' ؛ '.join(con_allowed)
    out['contracts_used'] = bool(con_text)
    text = ''
    fast = ' '.join(str(raw.get('text') or '').split())
    if facts and fast and not rejected and not unverified_numbers(fast, facts) and st.TODO not in fast:
        text = fast                                    # كل الحقائق تحقّقت والرقم سليم: لا حاجة لطلب ثانٍ
        out['fast'] = True
    if facts and not text:
        bad = None
        for _attempt in range(2):
            ai_call_log.detail('صياغة الموضوع من الحقائق' + (' (إعادة بعد رفض أرقام)' if bad else ''))
            text = ' '.join((ask(with_contracts(build_generation_prompt(facts, models, parties, bad, rules), con_text))
                             or '').split())
            bad = unverified_numbers(text, facts)
            if text and not bad and st.TODO not in text:
                ai_call_log.verdict(True, 'صياغة سليمة: كل أرقامها واردة في الحقائق')
                break
            ai_call_log.verdict(False, ('أرقام غير واردة في الحقائق: ' + '، '.join(bad)) if bad else 'نص فارغ أو فيه علامة «يُكتب»')
            text = ''
        if not text:
            text = compose_fallback(facts, parties)
    if ctype == 'اتصالات' and facts:               # صيغة ثابتة للاتصالات: الذكاء يستخرج الحقائق فقط
        text = compose_telecom(facts, kind)
        out['fast'] = False
    unverified = [label for label, _why in rejected]
    rejected_labels = set(unverified)
    absent = [FACT_LABELS[k] for k in FACT_LABELS if k not in facts and FACT_LABELS[k] not in rejected_labels]
    facts.pop('contracts_from_documents', None)
    out.update(text=text, absent=absent, unverified=unverified, facts=facts,
               missing=unverified + absent)
    return out
