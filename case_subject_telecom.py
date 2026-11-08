# ===== case_subject_telecom.py — صيغة «الموضوع» لقضايا الاتصالات =====
# المدعية شركة من [telecom_companies] (زين/أوريدو/stc…): يُركَّب الموضوع من قالب ثابت وقيمه من صحيفة الدعوى حرفياً.
# النموذج (ask) يستخرج الحقول فقط؛ الكود هو الذي يتحقق منها على نص الصحيفة ويركّب الجملة:
#   - كل قيمة يجب أن ترد في الصحيفة بنصها (مقارنة بالرموز: الأرقام بقيمتها Decimal لا بشكلها 18.5 = 18.500 = ١٨٫٥٠٠،
#     وإهمال الترقيم والتشكيل وتنوين الفتح)، ويُكتب في الموضوع النص كما ورد في الصحيفة لا كما أعاده النموذج.
#   - المبالغ والمدد: كل رقم فيها يُفحص بـDecimal (موجود في الصحيفة وموجب).
#   - ما لم يرد أو لم يتحقق يبقى «[يُكتب]» — لا تخمين. باقي القضايا لا يمسّها هذا الملف (صيغة العقد العام).
# منطق صرف بلا واجهة؛ الشبكة/PDF في fetch_claim_text فقط (يُستدعى من خيط خلفي).
import json
import re
import threading
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

import telecom_config

TODO = '[يُكتب]'
USER_ID = '309'                 # كما في بقية الوحدات (documents/referred_cases)
MAX_PROMPT_CHARS = 60_000
MAX_CLAIM_CHARS = 1500
MAX_EXCERPT_CHARS = 600
OCR_MAX_PAGES = 6

# ---------- التطبيع والرموز ----------
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬', '01234567890123456789.,')
_BIDI = re.compile('[‎‏‪-‮⁦-⁩]')
_MARKS = re.compile('[ؐ-ًؚ-ٰٟۖ-ۭـ]')
_LETTERS = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ى': 'ي', 'ة': 'ه', 'ؤ': 'و', 'ئ': 'ي'})
_TOKEN = re.compile(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|[\wؐ-ًؚ-ٰٟۖ-ۭـ]+')
_NUMBER = re.compile(r'\d+(?:\.\d+)?')


def _is_num(tok):
    return bool(_NUMBER.fullmatch(tok))


def _norm_token(tok):
    """رمز مطبَّع للمقارنة: الرقم بقيمته Decimal، والكلمة بلا تشكيل ولا تنوين فتح، وبلا ألف أخيرة (شهراً = شهر)."""
    if tok[0].isdigit():
        try:
            return format(Decimal(tok.replace(',', '')).normalize(), 'f')
        except InvalidOperation:
            return tok
    t = re.sub('(?:ًا|اً|ً)$', '', tok)
    t = _MARKS.sub('', t).translate(_LETTERS).lower()
    if len(t) > 3 and t.endswith('ا'):
        t = t[:-1]
    return t


def _display(text):
    return _BIDI.sub('', unicodedata.normalize('NFKC', str(text or '')).translate(_DIGITS))


def _tokens(display):
    out = []
    for m in _TOKEN.finditer(display):
        n = _norm_token(m.group())
        if n:
            out.append((n, m.start(), m.end()))
    return out


def _decimals(value):
    return [Decimal(n) for n, _, _ in _tokens(_display(value)) if _is_num(n)]


class Plaint:
    """نص الصحيفة بعد التطبيع: رموز بمواضعها في النص المعروض (الأرقام لاتينية) لاستخراج النص الأصلي حرفياً."""

    def __init__(self, text):
        self.display = _display(text)
        self.toks = _tokens(self.display)
        self.numbers = {Decimal(n) for n, _, _ in self.toks if _is_num(n)}
        self._dates = None

    def dates(self):
        if self._dates is None:
            self._dates = plaint_dates(self.display)
        return self._dates

    def find(self, value):
        """النص كما ورد في الصحيفة لقيمة أعادها النموذج، أو None إن لم ترد متصلةً فيها."""
        want = [n for n, _, _ in _tokens(_display(value))]
        have = [n for n, _, _ in self.toks]
        k = len(want)
        if not k:
            return None
        for i in range(len(have) - k + 1):
            if have[i:i + k] == want:
                return re.sub(r'\s+', ' ', self.display[self.toks[i][1]:self.toks[i + k - 1][2]]).strip()
        return None

    def wording(self):
        """(مذكر، مؤنث، جمع) = عدد مرات «المدعى عليه/عليها/عليهم» في الصحيفة (بلا تساهل الألف الأخيرة)."""
        t = _MARKS.sub('', self.display).translate(_LETTERS)

        def count(forms):
            return len(re.findall(rf'(?<!\w)[وفبلك]?المدعي\s+(?:{forms})(?!\w)', t))
        return count('عليه'), count('عليها'), count('عليهم|عليهما|عليهن')


# ---------- التواريخ ----------
_MONTHS = {'يناير': 1, 'كانون الثاني': 1, 'فبراير': 2, 'شباط': 2, 'مارس': 3, 'اذار': 3, 'ابريل': 4, 'نيسان': 4,
           'مايو': 5, 'ايار': 5, 'يونيو': 6, 'حزيران': 6, 'يوليو': 7, 'تموز': 7, 'اغسطس': 8, 'اب': 8,
           'سبتمبر': 9, 'ايلول': 9, 'اكتوبر': 10, 'تشرين الاول': 10, 'نوفمبر': 11, 'تشرين الثاني': 11,
           'ديسمبر': 12, 'كانون الاول': 12}
_MONTH_ALT = '|'.join(sorted((re.sub(r'(?:\\ | )', r'\\s+', re.escape(k)) for k in _MONTHS), key=len, reverse=True))
_SEP = r'[/.\-\\]'          # الشرطة المائلة، النقطة، الواصلة، والمائلة العكسية (19\4\2018)
_NUM_DATE = re.compile(rf'(?<![\d/.\-\\])(\d{{1,4}})\s*{_SEP}\s*(\d{{1,2}})\s*{_SEP}\s*(\d{{1,4}})(?!\d)')
_WORD_DATE = re.compile(rf'(?<!\d)(\d{{1,2}})\s+(?:من\s+)?(?:شهر\s+)?({_MONTH_ALT})\s+(?:من\s+)?(?:سنه\s+|عام\s+)?(\d{{4}})(?!\d)')
_BLOB = re.compile(r'(?<!\d)(\d{6,10})(?!\d)')
_CUE = re.compile(r'(?:مؤرخ|المؤرخ|بتاريخ|بتأريخ|تاريخ|بجلسة|حرر)')
YEAR_MIN, YEAR_MAX = 1990, 2030


def _valid_date(d, m, y):
    try:
        return YEAR_MIN <= y <= YEAR_MAX and bool(date(y, m, d))
    except ValueError:
        return False


def _numeric_dates(t):
    """[(d, m, y, النص الأصلي)] من الصيغ الرقمية: 19/4/2018، 19\4\2018، 2018/4/19، 19-4-2018، 19.4.2018."""
    out = []
    for m in _NUM_DATE.finditer(t):
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if len(m.group(3)) == 4 and _valid_date(a, b, c):
            out.append((a, b, c, m.group(0).strip()))
        elif len(m.group(1)) == 4 and _valid_date(c, b, a):
            out.append((c, b, a, m.group(0).strip()))
    return out


def _ocr_blob_dates(blob):
    """تاريخ مقلوب/ملتصق بقراءة OCR RTL: 2018\4\19 تُقرأ 201814119 (المائلة العكسية تصير «1»). كل التقسيمات الصالحة
    (سنة أولاً أو سنة أخيراً)؛ مجموعة (d, m, y)."""
    found = set()
    for y_first in (True, False):
        for ylen in (4,):
            if y_first:
                y, rest = int(blob[:4]), blob[4:]
                if blob[:4].isdigit() and rest.startswith('1'):
                    r2 = rest[1:]
                    for i in (1, 2):                               # الشهر 1-2 رقم ثم «1» ثم اليوم
                        if len(r2) > i and r2[i] == '1':
                            mo, d = r2[:i], r2[i + 1:]
                            if mo.isdigit() and d.isdigit() and 1 <= len(d) <= 2 and _valid_date(int(d), int(mo), y):
                                found.add((int(d), int(mo), y))
            elif len(blob) >= 4:
                y, rest = int(blob[-4:]), blob[:-4]
                if rest.endswith('1'):
                    r2 = rest[:-1]
                    for i in (1, 2):                               # اليوم ثم «1» ثم الشهر
                        if len(r2) > i + 1 and r2[i] == '1':
                            d, mo = r2[:i], r2[i + 1:]
                            if d.isdigit() and mo.isdigit() and 1 <= len(mo) <= 2 and _valid_date(int(d), int(mo), y):
                                found.add((int(d), int(mo), y))
    return found


def parse_date(text, ocr_blob=False):
    """(d, m, y) لأول تاريخ فعلي في النص (الأرقام الهندية والمائلة العكسية والسنة أولاً أو أخيراً، وبالكلمات)،
    أو None. ocr_blob=True يقبل أيضاً الكتلة المقلوبة 201814119 إن كان النص كله هي (لا يُخلط برقم عقد إلا بقرار المتصل)."""
    t = _MARKS.sub('', _display(text))
    nd = _numeric_dates(t)
    if nd:
        return nd[0][:3]
    norm = t.translate(_LETTERS).lower()
    for m in _WORD_DATE.finditer(norm):
        month = _MONTHS.get(re.sub(r'\s+', ' ', m.group(2)))
        if month and _valid_date(int(m.group(1)), month, int(m.group(3))):
            return int(m.group(1)), month, int(m.group(3))
    if ocr_blob:
        s = re.sub(r'\D', '', t) if re.fullmatch(r'\s*\d{6,10}\s*', t) else ''
        cands = _ocr_blob_dates(s) if s else set()
        if len(cands) == 1:
            return next(iter(cands))
    return None


def find_date(text):
    """أول تاريخ فعلي (يوم/شهر/سنة: 10/01/2025، 10-1-2025، 19\4\2018، 2025/01/10، 10 يناير 2025) في النص كما ورد، أو None.
    الأرقام وحدها (201814119) ليست تاريخاً. السنة أربعة أرقام (1990–2030)، واليوم والشهر يُفحصان بالتقويم."""
    t = _MARKS.sub('', _display(text))
    nd = _numeric_dates(t)
    if nd:
        return nd[0][3]
    norm = t.translate(_LETTERS).lower()
    for m in _WORD_DATE.finditer(norm):
        month = _MONTHS.get(re.sub(r'\s+', ' ', m.group(2)))
        if month and _valid_date(int(m.group(1)), month, int(m.group(3))):
            return t[m.start():m.end()].strip()
    return None


def fmt_date(dmy):
    """(d, m, y) ← «dd/mm/yyyy»."""
    return f'{dmy[0]:02d}/{dmy[1]:02d}/{dmy[2]}'


def plaint_dates(display):
    """مجموعة (d, m, y) لكل تاريخ وارد في نص الصحيفة بأي صيغة مدعومة، بما فيها الكتلة المقلوبة 201814119 متى سبقتها
    كلمة تاريخ (مؤرخ/بتاريخ…) — بلا كلمة كهذه تبقى رقماً (رقم عقد) لا تاريخاً."""
    t = _MARKS.sub('', display)
    out = {d[:3] for d in _numeric_dates(t)}
    norm = t.translate(_LETTERS).lower()
    for m in _WORD_DATE.finditer(norm):
        month = _MONTHS.get(re.sub(r'\s+', ' ', m.group(2)))
        if month and _valid_date(int(m.group(1)), month, int(m.group(3))):
            out.add((int(m.group(1)), month, int(m.group(3))))
    for m in _BLOB.finditer(t):
        before = t[max(0, m.start() - 40):m.start()]
        if _CUE.search(before):
            c = _ocr_blob_dates(m.group(1))
            if len(c) == 1:
                out |= c
    return out


# ---------- تصحيح أخطاء OCR الواضحة جداً ----------
# أخطاء الحروف المتشابهة المعروفة في كلمات قانونية محددة فقط (غ↔ع، ذ↔د، ن↔ت، ز↔ر…). لا يمسّ أي رمز فيه رقم
# (الأرقام والتواريخ) ولا الأسماء: التصحيح بجذر كلمة كاملة من القائمة مع سوابق/لواحق نحوية فقط.
OCR_FIXES = (('المدغى', 'المدعى'), ('المذعى', 'المدعى'), ('غليه', 'عليه'),
             ('غليها', 'عليها'), ('غليهم', 'عليهم'), ('الدغوى', 'الدعوى'), ('الذعوى', 'الدعوى'),
             ('النزام', 'التزام'), ('اشتزاك', 'اشتراك'), ('الانصال', 'الاتصال'), ('صحبفة', 'صحيفة'),
             ('صحيقة', 'صحيفة'), ('المحكمت', 'المحكمة'), ('الخدمات', 'الخدمات'))
_AR = '؀-ۿ'
_OCR_RES = [(bad, good, re.compile(rf'(?<![{_AR}\d])([وفبلك]{{0,2}})(?:{re.escape(bad)})((?:ات(?:ها|هم|هما|ه)?|ها|هم|هما|ين|ون|ان|ه)?)(?![{_AR}\d])'))
            for bad, good in OCR_FIXES if bad != good]


def fix_ocr(text):
    """(النص المصحَّح، [(الخطأ، الصواب، العدد)]). لا يغيّر رقماً ولا تاريخاً ولا اسماً."""
    out, log = str(text or ''), []
    for bad, good, rx in _OCR_RES:
        out, n = rx.subn(lambda m, g=good: m.group(1) + g + m.group(2), out)
        if n:
            log.append((bad, good, n))
    return out, log


# ---------- التحقق من الحقول ----------

def _clean(v):
    if isinstance(v, bool) or v is None:
        return ''
    s = re.sub(r'\s+', ' ', str(v)).strip()
    return '' if s.lower() in ('null', 'none', 'n/a') else s


def verify(kind, value, plaint, alerts=None, label=''):
    """(النص كما ورد في الصحيفة أو None، سبب الرفض). kind: date | amount | duration | claim | excerpt."""
    value = _clean(value)
    if not value:
        return None, 'لم يُذكر في الصحيفة'
    if kind == 'date':        # التاريخ يُتحقق منه بقيمته (يوم/شهر/سنة) في الصحيفة بأي صيغة: لا تخمين ولا نص مقلوب
        dmy = parse_date(value, ocr_blob=True)
        if dmy is None:
            return None, 'ليس تاريخاً صالحاً (يوم/شهر/سنة بين 1990 و2030)'
        if dmy not in plaint.dates():
            return None, f'التاريخ {fmt_date(dmy)} غير وارد في الصحيفة'
        return fmt_date(dmy), ''
    nums = _decimals(value)
    if kind in ('date', 'amount') and not nums:
        return None, 'لا رقم فيه'
    for d in nums:                                        # المبالغ والمدد والتواريخ: Decimal
        if d not in plaint.numbers:
            return None, f'الرقم {format(d.normalize(), "f")} غير وارد في الصحيفة'
        if kind in ('amount', 'duration') and d <= 0:
            return None, f'الرقم {format(d.normalize(), "f")} غير موجب'
    found = plaint.find(value)
    if found is None:
        return None, 'لم يرد حرفياً في الصحيفة'
    if kind in ('amount', 'claim'):                       # المبلغ بالأرقام والحروف: يُعتمد المتطابق فقط
        import amounts
        at = plaint.display.find(found)
        r = amounts.reconcile(found, plaint.display[at + len(found):at + len(found) + 160] if at >= 0 else '')
        pre = f'{label}: ' if label else ''
        if r['status'] == amounts.MISMATCH:
            if alerts is not None:
                alerts.append(('red', pre + r['message']))
            return None, r['message']
        if kind == 'amount' and r['status'] in (amounts.DIGITS_ONLY, amounts.WORDS_ONLY):
            if alerts is not None:
                alerts.append(('amber', pre + r['message']))
        if kind == 'amount' and r['status'] != amounts.NONE:
            return r['display'], ''
    if kind == 'date':
        d = find_date(found)
        if d is None:
            return None, f'«{found}» ليس تاريخاً صالحاً (يوم/شهر/سنة)'
        return d, ''
    if kind == 'number' and (len(found) > 40 or len(found.split()) > 3):
        return None, 'رقم العقد غير صالح'
    if kind == 'claim' and (len(found) > MAX_CLAIM_CHARS or len(found.split()) < 3):
        return None, 'مقتطف المطالبة غير صالح'
    if kind == 'excerpt' and (len(found) > MAX_EXCERPT_CHARS or len(found.split()) < 2):
        return None, 'المقتطف غير صالح (قصير جداً أو طويل جداً)'
    return found, ''


# ---------- جنس المدعى عليه ----------
_COMPANY_WORDS = {'شركه', 'موسسه', 'بنك', 'مجموعه', 'مصنع', 'مكتب', 'مجمع', 'co', 'company', 'ltd', 'llc', 'wll'}
_COMPANY_RAW = re.compile(r'ش\s*\.\s*م\s*\.\s*ك|ذ\s*\.\s*م\s*\.\s*م')
_FORMS = {
    'm': ('المدعى عليه', 'الأخير', 'لم يلتزم'),
    'f': ('المدعى عليها', 'الأخيرة', 'لم تلتزم'),
    'p': ('المدعى عليهم', 'الأخيرين', 'لم يلتزموا'),
}


def _is_company(name):
    if _COMPANY_RAW.search(_display(name)):
        return True
    return any((n[2:] if n.startswith('ال') else n) in _COMPANY_WORDS for n, _, _ in _tokens(_display(name)))


def defendant_kind(defendants, plaint=None):
    """('m'|'f'|'p'، ملاحظة أو ''): جمع إن تعدد المدعى عليهم؛ شركة ← مؤنث؛ وإلا بحسب ما كتبته الصحيفة نفسها
    («المدعى عليه/عليها»). لا نخمّن الجنس من الاسم؛ إن لم يتضح اعتُمد المذكر مع تنبيه للخبير."""
    names = [d.strip() for d in defendants or [] if isinstance(d, str) and d.strip()]
    if len(names) >= 2:
        return 'p', ''
    m, f, p = plaint.wording() if plaint is not None else (0, 0, 0)
    if len(names) == 1:
        if _is_company(names[0]):
            return 'f', ''
        if f and not m and not p:
            return 'f', ''
        if m and not f and not p:
            return 'm', ''
        return 'm', 'جنس المدعى عليه غير محسوم من الصحيفة — اعتُمد «المدعى عليه»، راجعه'
    if p or (m and f):
        return 'p', 'عدد المدعى عليهم من نص الصحيفة — راجع الصيغة'
    if f:
        return 'f', ''
    if m:
        return 'm', ''
    return 'm', 'جنس المدعى عليه غير معروف — اعتُمد «المدعى عليه»، راجعه'


# ---------- التركيب ----------
_ORDINALS = ('الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس', 'السابع', 'الثامن', 'التاسع', 'العاشر')


def _ord(i):
    return _ORDINALS[i] if i < len(_ORDINALS) else f'رقم {i + 1}'


def _per_contract(values):
    if len(values) == 1:
        return values[0]
    return ' و'.join(f'{v} للعقد {_ord(i)}' for i, v in enumerate(values))


def contract_ref(c):
    """«رقم X مؤرخ D» (الرقم إن وُجد فقط؛ التاريخ دائماً وإلا «[يُكتب]»)."""
    num = f"رقم {c['number']} " if c.get('number') else ''
    return f"{num}مؤرخ {c['date']}"


def compose(contracts, claim, kind):
    """contracts: [{'date','monthly','duration','number'?}] (القيمة المفقودة TODO). الصيغة ثابتة كما اعتمدها الخبير.
    القيم هنا عبارات اسمية فيبقى الموضع «[يُكتب]» سليماً نحوياً (بخلاف مقاطع الأفعال في case_subject_contract)."""
    who, last, neg = _FORMS[kind]
    to_who = 'ل' + who[1:]                       # ل + ال = لل: «للمدعى عليه»
    refs = ' وعقد آخر '.join(contract_ref(c) for c in contracts)
    claim = (claim or TODO).strip().rstrip('.،؛ ')
    return (f"جاءت المدعية بصحيفة مفادها أنها بموجب عقد اشتراك {refs} قامت المدعية بتقديم خدمات الاتصال "
            f"لصالح {who}، وذلك مقابل اشتراك شهري {_per_contract([c['monthly'] for c in contracts])} "
            f"مع مدة التزام وقدرها {_per_contract([c['duration'] for c in contracts])}. "
            f"وأفادت المدعية على حسب دعواها أنها قدّمت الخدمة {to_who} إلا أن {last} {neg} بالسداد، "
            f"فتم رفع الدعوى الماثلة، وطلبت {claim}.")


# ---------- الاستخراج ----------

def build_prompt(plaint_text):
    return (
        "أنت تستخرج بيانات من صحيفة دعوى رفعتها شركة اتصالات على عميلها. انسخ كل قيمة حرفياً كما وردت في نص "
        "الصحيفة أدناه، دون تعديل أو ترجمة أو تحويل أرقام أو اختصار أو إعادة صياغة أو تصحيح إملائي. "
        "إن لم تذكر الصحيفة القيمة صراحةً فاكتب null — لا تخمّن ولا تحسب ولا تستنتج.\n"
        'أجب بـ JSON فقط بالشكل:\n'
        '{"contracts":[{"number":"رقم العقد إن ذُكر صراحةً","date":"تاريخ عقد الاشتراك (يوم/شهر/سنة فقط)","monthly":"قيمة الاشتراك الشهري مع عملتها",'
        '"duration":"مدة الالتزام مع وحدتها"}],"claim":"المطالبة"}\n'
        "- contracts: عنصر لكل عقد اشتراك مختلف في الصحيفة بترتيب ورودها؛ مصفوفة فارغة إن لم يُذكر عقد.\n"
        "- claim: طلب المدعية الختامي منسوخاً من فعل الطلب (يبدأ من «الحكم بـ…» أو «بإلزام…» دون عبارة "
        "«ليسمع/لسماع»)، متضمناً المبلغ المطالَب به وما ذُكر معه من فوائد أو رسوم أو مصاريف كما وردت، "
        "وينتهي عند نهاية الطلب.\n\n"
        "نص الصحيفة:\n" + (plaint_text or '')[:MAX_PROMPT_CHARS])


def parse_response(txt):
    m = re.search(r'\{.*\}', txt or '', re.S)
    try:
        obj = json.loads(m.group(0))
    except (AttributeError, ValueError):
        raise ValueError('ردّ الذكاء الاصطناعي ليس JSON صالحاً') from None
    if not isinstance(obj, dict):
        raise ValueError('ردّ الذكاء الاصطناعي ليس JSON صالحاً')
    return obj


def build_subject(plaint_text, defendants, ask):
    """يركّب موضوع الاتصالات. plaint_text فارغ أو ask=None ← قالب كله «[يُكتب]».
    يرفع ValueError إن لم يكن ردّ ask JSON، وما يرفعه ask يمرّ كما هو. يرجع dict:
    text، missing (أسماء الحقول الناقصة)، rejected (حقول ردّها الكود وسببها)، kind، note."""
    plaint_text, ocr_fixes = fix_ocr(plaint_text)
    plaint = Plaint(plaint_text) if (plaint_text or '').strip() else None
    kind, note = defendant_kind(defendants, plaint)
    contracts, claim, rejected, alerts = [], None, [], []
    if plaint is not None and ask is not None:
        obj = parse_response(ask(build_prompt(plaint_text)))
        raw = obj.get('contracts')
        for i, c in enumerate(raw if isinstance(raw, list) else [], 1):
            if not isinstance(c, dict):
                continue
            row, ok = {}, False
            for key, kd, label in (('number', 'number', 'رقم العقد'), ('date', 'date', 'تاريخ العقد'),
                                   ('monthly', 'amount', 'الاشتراك الشهري'), ('duration', 'duration', 'مدة الالتزام')):
                val, why = verify(kd, c.get(key), plaint, alerts, f'{label} ({i})')
                if key == 'number':
                    row[key] = val or ''
                    ok = ok or bool(val)
                    continue
                row[key] = val or TODO
                ok = ok or bool(val)
                if not val and _clean(c.get(key)):
                    rejected.append((f'{label} ({i})', why))
                    if key == 'date' and not row.get('number'):      # رقم لا تاريخ (201814119): يصلح رقم عقد
                        num, _w = verify('number', c.get(key), plaint)
                        if num and not find_date(num):
                            row['number'] = num
                            ok = True
            if ok and row not in contracts:         # عقد لم يتحقق منه شيء لا دليل على وجوده؛ والمكرر يسقط
                contracts.append(row)
        claim, why = verify('claim', obj.get('claim'), plaint, alerts, 'المطالبة')
        if not claim and _clean(obj.get('claim')):
            rejected.append(('المطالبة', why))
    if not contracts:
        contracts = [{'date': TODO, 'monthly': TODO, 'duration': TODO, 'number': ''}]
    n = len(contracts)
    missing = []
    for i, c in enumerate(contracts):
        suffix = f' ({_ord(i)})' if n > 1 else ''
        for key, label in (('date', 'تاريخ العقد'), ('monthly', 'الاشتراك الشهري'), ('duration', 'مدة الالتزام')):
            if c[key] == TODO:
                missing.append(label + suffix)
    if not claim:
        missing.append('المطالبة')
    return {'text': compose(contracts, claim, kind), 'missing': missing, 'rejected': rejected,
            'kind': kind, 'note': note, 'ocr_fixes': ocr_fixes, 'alerts': alerts}


# ---------- التحديد والجلب ----------

def telecom_company(row, case, companies=None):
    """الاسم الأساسي لشركة الاتصالات إن كانت المدعية منها (من case_db ثم بيانات القضية ثم عنوانها)، وإلا None."""
    plaintiffs = row.get('plaintiffs') or []
    cands = ([plaintiffs] if isinstance(plaintiffs, str) else list(plaintiffs))
    cands += [case.get('plaintiff'), case.get('company'), telecom_config.split_plaintiff(case.get('title'))]
    if companies is None:
        companies = telecom_config.load_companies()
    for c in cands:
        name = telecom_config.match_company(c, companies) if isinstance(c, str) and c.strip() else None
        if name:
            return name
    return None


def _local_read(path):
    import local_ocr
    import fitz
    with fitz.open(path) as d:
        pages = min(d.page_count, OCR_MAX_PAGES)
    return chr(10).join(p.text for p in local_ocr.read_pages(path, list(range(pages))).pages), pages


_tls = threading.local()


def last_read():
    """معلومات آخر قراءة صحيفة في هذا الخيط: {'engine','label','skipped':[(محرّك، سبب)]} أو None."""
    return getattr(_tls, 'info', None)


def pdf_text(path, stronger=False):
    """نص PDF صحيفة الدعوى: الأرقام فيها حاسمة فتُقرأ بـGemini مباشرة ولو وُجدت طبقة نصية، ثم Cloud Vision ثم OCR
    الخارجي، ثم الطبقة النصية، ثم المحلي. لا يسقط صامتاً إلى أضعف: المحرّك الفعلي وأسباب تخطي الأقوى تُسجَّل في
    last_read() ويفصح عنها الكود بتنبيه أحمر. (stronger للتوافق: السلوك الآن دائماً الأقوى.)"""
    import fitz
    import doc_router
    with fitz.open(path) as d:
        layer = chr(10).join(p.get_text() for p in d)
    res = doc_router.read_numbers_pdf(path, _local_read, layer)
    _tls.info = {'engine': res['engine'], 'label': doc_router.ENGINE_LABELS.get(res['engine'], res['engine']),
                 'skipped': [(doc_router.ENGINE_LABELS.get(e, e), why) for e, why in res['skipped']]}
    return re.sub(r'<!--.*?-->', '', res['text'])


def fetch_claim_text(cookies, autocase_no, stronger=False, base=None, data=None, refresh=False):
    """نص أقدم صحيفة دعوى بمستندات القضية، أو None إن لم توجد. فشل الشبكة/الجلسة يرفع استثناءً. (خيط خلفي فقط)
    base+data: يُبحث محلياً أولاً (النص المحفوظ ← الملف المحفوظ ← النظام)، وما يُجلب يُحفظ في 01_اصول\مصادر ويُسجَّل في
    case.json['sources']. refresh=True («تحديث من النظام») يتجاوز المحلي ويجلب من جديد. stronger يعيد قراءة الملف المحلي
    بمحرك أقوى دون جلب جديد."""
    import os
    import tempfile
    import case_sources as src
    track = base is not None and data is not None
    if track and not refresh:
        if not stronger:
            cached = src.load_text(base, data, 'claim')
            if cached:                                             # نص محفوظ لنسخة الملف نفسها: لا جلب ولا OCR
                _tls.info = dict(cached[1])
                return cached[0]
        local = src.local_file(base, data, 'claim') or src.find_claim(base, data)
        if local:                                                  # الملف محفوظ: اقرأه بلا اتصال
            text = pdf_text(local, stronger)
            src.save_text(base, data, 'claim', text, last_read())
            return text
    from documents import get_claim_for_case
    if not cookies:
        raise RuntimeError('لا اتصال بالنظام ولا صحيفة محفوظة')
    fd, path = tempfile.mkstemp(suffix='.pdf', prefix='claim_')
    os.close(fd)
    try:
        row, saved, status = get_claim_for_case(cookies, autocase_no, USER_ID, path)
        if status != 'OK':
            return None
        text = pdf_text(saved, stronger)
        if track:                                                  # المسار الواحد بالمحتوى (لا نسخة لكل تنزيل)
            rec, added = src.store_claim(base, data, saved, doc_id=(row or {}).get('doc_id') or '', info=last_read())
            if added and added == rec.get('file'):
                src.save_text(base, data, 'claim', text, last_read())
                judg = src.judgments_dir()
                if os.path.isdir(judg):
                    try:
                        import shutil
                        shutil.copy2(saved, os.path.join(judg, f"{data['caso_no']}_claim.pdf"))
                    except OSError:
                        pass
        return text
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
