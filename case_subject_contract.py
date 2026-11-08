# ===== case_subject_contract.py — صيغة «الموضوع» للقضايا غير الاتصالات (صيغة العقد العام) =====
# الصيغة كما أعطاها الخبير (سكيل كتابة التقرير): «جاءت المدعية بصحيفة مفادها أنها بموجب عقد مؤرخ … (العلاقة
# من العقد: تاريخه، الالتزامات، المبلغ، المدة) … وأفادت المدعية – على حسب دعواها – أنها … إلا أن المدعى عليها
# أخلّت في … فتم رفع الدعوى الماثلة». لا ملخص حر: كل فراغ يُملأ بنص الصحيفة حرفياً بمنهج case_subject_telecom
# (النموذج يستخرج JSON فقط، والكود يتحقق من ورود القيمة متصلةً في الصحيفة ويكتب نص الصحيفة)، وما لم يتحقق «[يُكتب]».
import re

import case_subject_telecom as st

TODO = st.TODO
_FORMS = {'m': ('المدعى عليه', 'أخلّ'), 'f': ('المدعى عليها', 'أخلّت'), 'p': ('المدعى عليهم', 'أخلّوا')}
_LEAD_AMOUNT = ('مبلغا وقدره', 'مبلغاً وقدره', 'مبلغ وقدره', 'مبلغاً', 'مبلغا', 'مبلغ', 'وقدره', 'قدره')
_LEAD_DURATION = ('لمدة', 'ومدته', 'مدته', 'مدة')
FIELDS = (('date', 'date', 'تاريخ العقد'), ('object', 'excerpt', 'محل العقد والالتزامات'),
          ('amount', 'amount', 'مبلغ العقد'), ('duration', 'duration', 'مدة العقد'))


def _strip_lead(text, words):
    """يحذف كلمة افتتاحية تتكرر مع القالب («مبلغ»، «لمدة»…) — الباقي جزء متصل من نص الصحيفة كما هو."""
    t = (text or '').strip()
    for w in words:
        if t.startswith(w + ' '):
            return t[len(w):].strip()
    return t


_NEG_START = ('لم', 'لا', 'لن', 'ولم', 'فلم', 'ولا')
_MASDAR = ('سداد', 'دفع', 'تسليم', 'تنفيذ', 'وفاء', 'رد', 'اعادة', 'تقديم', 'استلام', 'صرف', 'تسديد', 'اداء')
_THAT_START = ('ان', 'انه', 'انها', 'انهم', 'ان')


def _first_norm(text):
    first = (text or '').split()[:1]
    return st._norm_token(st._display(first[0])) if first else ''


def link_for(breach):
    """رابط الإخلال بحسب أول كلمة في الجملة المقتبسة: لم/لا/لن ← «بأن»؛ عدم… ← «ب» ملصقة (بعدم)؛ أن… ← «إذ»؛
    مصدر معروف (سداد/دفع…) ← «في» (كما اعتمد الخبير: أخلّ في سداد…)؛ غير ذلك (جملة فعلية كاملة) ← «إذ». يرجع (الرابط، النص بعد الرابط)."""
    t = (breach or '').strip()
    w = _first_norm(t)
    bare = w[2:] if w.startswith('ال') else w
    if w in _NEG_START:
        return 'بأن', t
    if w == 'عدم':
        return '', 'ب' + t
    if w in _THAT_START:
        return 'إذ', t
    if bare in _MASDAR:
        return 'في', t
    return 'إذ', t


def _strip_that(text):
    return re.sub(r'^(?:أنها|أنه|أنهم|أن|انها|انه|ان)\s+', '', (text or '').strip())


def compose(contracts, performed, breach, kind):
    """كل مقطع ناقص يُستبدل كاملاً بـ«[يُكتب]»: «أنها {ما قامت به}» و«إلا أن {المدعى عليه} أخلّ {رابط} {الإخلال}»."""
    who, verb = _FORMS[kind]
    refs = ' وعقد آخر '.join(st.contract_ref(c) for c in contracts)
    performed = _strip_that(performed)
    perf = f'أنها {performed}' if performed else ''          # اختياري: غيابه لا يترك «[يُكتب]»
    if breach:
        link, text = link_for(breach)
        brc = f"إلا أن {who} {verb} {link} {text}".replace('  ', ' ')
    else:
        brc = TODO
    tail = brc if not perf else f'{perf} {brc}' if brc != TODO else perf
    if not perf and brc != TODO:
        tail = 'أن ' + brc[len('إلا أن '):]
    return (f"جاءت المدعية بصحيفة مفادها أنها بموجب عقد {refs} "
            f"{st._per_contract([c['object'] for c in contracts])}، "
            f"وذلك مقابل مبلغ {st._per_contract([c['amount'] for c in contracts])} "
            f"لمدة {st._per_contract([c['duration'] for c in contracts])}. "
            f"وأفادت المدعية – على حسب دعواها – {tail}، فتم رفع الدعوى الماثلة.")


def build_prompt(plaint_text):
    return (
        "أنت تستخرج بيانات من صحيفة دعوى تعاقدية. انسخ كل قيمة حرفياً كما وردت في نص الصحيفة أدناه، دون تعديل أو "
        "ترجمة أو تحويل أرقام أو اختصار أو إعادة صياغة أو تصحيح إملائي. إن لم تذكر الصحيفة القيمة صراحةً فاكتب "
        "null — لا تخمّن ولا تحسب ولا تستنتج.\n"
        'أجب بـ JSON فقط بالشكل:\n'
        '{"contracts":[{"number":"رقم العقد إن ذُكر صراحةً","date":"تاريخ العقد (يوم/شهر/سنة فقط)","object":"محل العقد والتزامات الطرفين",'
        '"amount":"قيمة العقد مع عملتها","duration":"مدة العقد مع وحدتها"}],'
        '"performed":"ما تقول المدعية إنها قامت به","breach":"الالتزام الذي أخلّ به المدعى عليه"}\n'
        "- contracts: عنصر لكل عقد مختلف بترتيب وروده؛ مصفوفة فارغة إن لم يُذكر عقد.\n"
        "- object: العبارة التي تصف محل العقد كما وردت (مثل «اتفقت مع المدعى عليه على توريد …»).\n"
        "- performed: العبارة كما وردت بعد «أنها» أو ما في معناها (مثل «نفذت كافة التزاماتها التعاقدية»).\n"
        "- breach: عبارة الالتزام المُخَلّ به كما وردت (مثل «سداد قيمة الأعمال»).\n\n"
        "نص الصحيفة:\n" + (plaint_text or '')[:st.MAX_PROMPT_CHARS])


def build_subject(plaint_text, defendants, ask):
    """مثل case_subject_telecom.build_subject لكن بصيغة العقد العام. يرجع dict: text، missing، rejected، kind، note."""
    plaint_text, ocr_fixes = st.fix_ocr(plaint_text)
    plaint = st.Plaint(plaint_text) if (plaint_text or '').strip() else None
    kind, note = st.defendant_kind(defendants, plaint)
    contracts, rejected, extra, alerts = [], [], {}, []
    if plaint is not None and ask is not None:
        obj = st.parse_response(ask(build_prompt(plaint_text)))
        raw = obj.get('contracts')
        for i, c in enumerate(raw if isinstance(raw, list) else [], 1):
            if not isinstance(c, dict):
                continue
            row, ok = {}, False
            num, _w = st.verify('number', c.get('number'), plaint)
            row['number'] = num or ''
            ok = bool(num)
            for key, kd, label in FIELDS:
                val, why = st.verify(kd, c.get(key), plaint, alerts, f'{label} ({i})')
                if val and key == 'amount':
                    val = _strip_lead(val, _LEAD_AMOUNT)
                if val and key == 'duration':
                    val = _strip_lead(val, _LEAD_DURATION)
                row[key] = val or TODO
                ok = ok or bool(val)
                if not val and st._clean(c.get(key)):
                    rejected.append((f'{label} ({i})', why))
                    if key == 'date' and not row['number']:         # رقم لا تاريخ (201814119): يصلح رقم عقد
                        n2, _w = st.verify('number', c.get(key), plaint)
                        if n2 and not st.find_date(n2):
                            row['number'], ok = n2, True
            if ok and row not in contracts:
                contracts.append(row)
        for key, label in (('performed', 'ما قامت به المدعية'), ('breach', 'الإخلال')):
            val, why = st.verify('excerpt', obj.get(key), plaint)
            extra[key] = val
            if not val and st._clean(obj.get(key)) and key != 'performed':   # «ما أنجزته» اختياري لا يُنبَّه عليه
                rejected.append((label, why))
        if not contracts and not note:
            note = 'لم تذكر الصحيفة عقداً — راجع الصيغة'
    if not contracts:
        contracts = [dict({k: TODO for k, _kd, _l in FIELDS}, number='')]
    n = len(contracts)
    missing = []
    for i, c in enumerate(contracts):
        suffix = f' ({st._ord(i)})' if n > 1 else ''
        for key, _kd, label in FIELDS:
            if c[key] == TODO:
                missing.append(label + suffix)
    for key, label in (('breach', 'الإخلال'),):
        if not extra.get(key):
            missing.append(label)
    return {'text': compose(contracts, extra.get('performed'), extra.get('breach'), kind),
            'missing': missing, 'rejected': rejected, 'kind': kind, 'note': note, 'ocr_fixes': ocr_fixes, 'alerts': alerts}
