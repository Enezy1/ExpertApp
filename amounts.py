# ===== amounts.py — المبالغ بالدينار الكويتي: كلمات عربية ↔ رقم، والتحقق من تطابق الرقم والحروف (2026-10-17) =====
# الدينار = 1000 فلس (3 خانات عشرية). كل الحساب بـDecimal. لا يُكتب مبلغ في التقرير إلا إذا تطابق بالأرقام والحروف؛
# وإن ورد بأحدهما فقط يُكتب مع علامة «لم يُتحقق منه بمصدر ثانٍ»؛ وإن اختلفا يُترك «[يُكتب]» مع تنبيه أحمر بالرقمين.
import re
from decimal import Decimal, InvalidOperation

OK, MISMATCH, DIGITS_ONLY, WORDS_ONLY, NONE = 'verified', 'mismatch', 'digits_only', 'words_only', 'none'
UNVERIFIED_MARK = 'لم يُتحقق منه بمصدر ثانٍ'
_CUR = 'د.ك'

_DIAC = re.compile('[ً-ٰٟـ]')


def norm(t):
    """تطبيع للمطابقة: بلا تشكيل/تطويل، ألف واحدة، ى←ي، ة←ه، ئ←ي، ؤ←و."""
    t = _DIAC.sub('', str(t or ''))
    for a, b in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ى', 'ي'), ('ة', 'ه'), ('ئ', 'ي'), ('ؤ', 'و'), ('ء', '')):
        t = t.replace(a, b)
    return t


_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩٬٫', '0123456789,.')

# ---------- كلمات ← رقم ----------
_UNITS = {'واحد': 1, 'واحده': 1, 'احد': 1, 'اثنان': 2, 'اثنين': 2, 'اثنتان': 2, 'اثنتين': 2, 'اثنا': 2, 'اثني': 2,
          'ثلاثه': 3, 'ثلاث': 3, 'اربعه': 4, 'اربع': 4, 'خمسه': 5, 'خمس': 5, 'سته': 6, 'ست': 6, 'سبعه': 7,
          'سبع': 7, 'ثمانيه': 8, 'ثماني': 8, 'ثمان': 8, 'تسعه': 9, 'تسع': 9}
_TEN = ('عشره', 'عشر')
_TENS = {'عشرون': 20, 'عشرين': 20, 'ثلاثون': 30, 'ثلاثين': 30, 'اربعون': 40, 'اربعين': 40, 'خمسون': 50,
         'خمسين': 50, 'ستون': 60, 'ستين': 60, 'سبعون': 70, 'سبعين': 70, 'ثمانون': 80, 'ثمانين': 80,
         'تسعون': 90, 'تسعين': 90}
_HUND_BASE = {'ثلاث': 3, 'اربع': 4, 'خمس': 5, 'ست': 6, 'سبع': 7, 'ثمان': 8, 'تسع': 9}
_HUND_SUF = ('مايه', 'ميه', 'مايت', 'ميت')
_SCALES = {'الف': 1000, 'الاف': 1000, 'الفا': 1000, 'مليون': 10 ** 6, 'ملايين': 10 ** 6, 'مليونا': 10 ** 6,
           'مليار': 10 ** 9, 'مليارات': 10 ** 9, 'مليارا': 10 ** 9}
_DUALS = {'الفان': 2000, 'الفين': 2000, 'مليونان': 2 * 10 ** 6, 'مليونين': 2 * 10 ** 6,
          'ملياران': 2 * 10 ** 9, 'مليارين': 2 * 10 ** 9,
          'مايتان': 200, 'مايتين': 200, 'ميتان': 200, 'ميتين': 200, 'مايتا': 200, 'مايتي': 200}
_DINAR = ('دينار', 'دينارا', 'ديناران', 'دينارين', 'دنانير')
_FILS = ('فلس', 'فلسا', 'فلسان', 'فلسين', 'فلوس')
_IGNORE = {'فقط', 'لا', 'غير', 'كويتي', 'كويتيا', 'كويتيه', 'ال', 'مبلغ', 'وقدره', 'قدره', 'بالحروف', 'اي', 'ما', 'يعادل'}


def _tokens(words):
    out = []
    for w in re.findall(r'[ء-ي]+', norm(words)):
        out.append(w)
    return out


def _strip_and(w, known):
    if w in known:
        return w
    if w.startswith('و') and w[1:] in known:
        return w[1:]
    return w


def _known(w):
    return (w in _UNITS or w in _TEN or w in _TENS or w in _SCALES or w in _DUALS or w in _HUND_SUF
            or w in ('مايه', 'ميه') or any(w == b + x for b in _HUND_BASE for x in _HUND_SUF))


def _small(tokens):
    """قيمة عدد صغير/كبير من كلمات (بلا ذكر العملة). يرجع Decimal أو None إن وُجدت كلمة غير مفهومة/فارغ."""
    total, cur, seen = 0, 0, False
    last_unit = None
    i = 0
    allk = set(_UNITS) | set(_TEN) | set(_TENS) | set(_SCALES) | set(_DUALS) | set(_HUND_BASE)
    while i < len(tokens):
        raw = tokens[i]
        w = raw[1:] if raw.startswith('و') and not _known(raw) else raw
        if w.startswith('ال') and _known(w[2:]):
            w = w[2:]
        if w in _IGNORE or raw in _IGNORE:
            i += 1
            continue
        if w in _DUALS:
            v = _DUALS[w]
            if v >= 1000:
                total += v
            else:
                cur += v
            last_unit = None
        elif w in _SCALES:
            total += (cur or 1) * _SCALES[w]
            cur = 0
            last_unit = None
        elif w in _TENS:
            cur += _TENS[w]
            last_unit = None
        elif w in _TEN:
            cur += 10                                       # «ثلاثة عشر» = 13
            last_unit = None
        elif w in _UNITS:
            if last_unit:
                return None
            cur += _UNITS[w]
            last_unit = _UNITS[w]
        elif w in _HUND_SUF or w in ('مايه', 'ميه'):        # «ثلاث مائة» مفصولة، أو «مائة»
            if last_unit and 3 <= last_unit <= 9:
                cur += last_unit * 100 - last_unit
            else:
                cur += 100
            last_unit = None
        else:
            hit = any(w == base + suf for base in _HUND_BASE for suf in _HUND_SUF)
            if not hit:
                return None
            cur += next(n for base, n in _HUND_BASE.items() if w.startswith(base)) * 100
            last_unit = None
        seen = True
        i += 1
    if not seen:
        return None
    return Decimal(total + cur)


def words_to_decimal(text):
    """«خمسة آلاف وثمانمائة وستة وسبعون ديناراً وخمسمائة وأربعون فلساً» ← Decimal('5876.540'). None إن لم يُفهم."""
    toks = _tokens(text)
    toks = [t for t in toks if t not in _IGNORE]
    # «دينار واحد» في أول المبلغ / «… وفلس واحد» بعد الدينار (to_words) = 1 — لا «ديناراً وأحد عشر فلساً»
    if len(toks) > 1 and toks[0] == 'دينار' and toks[1] in ('واحد', 'واحدا'):
        del toks[1]
    for i in range(len(toks) - 1, 0, -1):
        if toks[i] in ('واحد', 'واحدا') and _strip_and(toks[i - 1], ('فلس',)) == 'فلس' \
                and (i == 1 or _strip_and(toks[i - 2], _DINAR) in _DINAR):
            del toks[i]
    d_idx = next((i for i, t in enumerate(toks) if _strip_and(t, _DINAR) in _DINAR), None)
    f_idx = next((i for i, t in enumerate(toks) if _strip_and(t, _FILS) in _FILS), None)
    if d_idx is None and f_idx is None:
        return None
    dinars = fils = Decimal(0)
    if d_idx is not None:
        dv = _small(toks[:d_idx]) if d_idx else None
        if dv is None:
            if toks[d_idx].lstrip('و') in ('ديناران', 'دينارين') and d_idx == 0:
                dv = Decimal(2)
            elif d_idx == 0 or (d_idx > 0 and not toks[:d_idx]):
                dv = Decimal(1)
            else:
                return None
        dinars = dv
        rest = toks[d_idx + 1:]
    else:
        rest = toks
    if f_idx is not None:
        f_start = (d_idx + 1) if d_idx is not None else 0
        fv = _small(toks[f_start:f_idx]) if f_idx > f_start else \
            Decimal(2 if _strip_and(toks[f_idx], _FILS) in ('فلسان', 'فلسين') else 1)
        if fv is None or fv >= 1000:
            return None
        fils = fv
        if toks[f_idx + 1:]:
            return None
    elif rest:
        return None
    return dinars + fils / Decimal(1000)


# ---------- أرقام ----------
_NUM_RE = re.compile(r'(?<![\d.,])\d[\d,٬]*(?:[.٫]\d+)?(?![\d])')


def digits_to_decimal(text):
    """أول مبلغ بالأرقام في النص (فواصل آلاف، 3 خانات عشرية على الأكثر) ← Decimal، أو None. يقبل الأرقام الهندية."""
    t = str(text or '').translate(_AR_DIGITS)
    m = _NUM_RE.search(t)
    if not m:
        return None
    s = m.group(0).rstrip(',')
    try:
        return Decimal(s.replace(',', ''))
    except InvalidOperation:
        return None


def fmt_kwd(d):
    """«5,876.540 د.ك» (3 خانات دائماً)."""
    return f"{Decimal(d).quantize(Decimal('0.001')):,} {_CUR}"


# ---------- رقم ← كلمات (2026-10-20): المبلغ بالحروف في البحث والنتيجة يكتبه الكود لا النموذج ----------
_W_ONES = ('', 'واحد', 'اثنان', 'ثلاثة', 'أربعة', 'خمسة', 'ستة', 'سبعة', 'ثمانية', 'تسعة')
_W_TEENS = ('عشرة', 'أحد عشر', 'اثنا عشر', 'ثلاثة عشر', 'أربعة عشر', 'خمسة عشر', 'ستة عشر', 'سبعة عشر',
            'ثمانية عشر', 'تسعة عشر')
_W_TENS = ('', '', 'عشرون', 'ثلاثون', 'أربعون', 'خمسون', 'ستون', 'سبعون', 'ثمانون', 'تسعون')
_W_HUNDREDS = ('', 'مائة', 'مائتان', 'ثلاثمائة', 'أربعمائة', 'خمسمائة', 'ستمائة', 'سبعمائة', 'ثمانمائة', 'تسعمائة')
# (مفرد، مثنى، جمع 3–10، تمييز 11–99) لكل مرتبة
_W_SCALES = ((10 ** 9, ('مليار', 'ملياران', 'مليارات', 'مليار')),
             (10 ** 6, ('مليون', 'مليونان', 'ملايين', 'مليون')),
             (1000, ('ألف', 'ألفان', 'آلاف', 'ألف')))


def _below_1000(n, construct=False):
    """0–999 بالكلمات. construct: «مائتا» بدل «مائتان» قبل المعدود (مائتا ألف)."""
    h, r = divmod(n, 100)
    parts = []
    if h:
        parts.append('مائتا' if (h == 2 and construct and not r) else _W_HUNDREDS[h])
    if r:
        if r < 10:
            parts.append(_W_ONES[r])
        elif r < 20:
            parts.append(_W_TEENS[r - 10])
        else:
            u, t = r % 10, r // 10
            parts.append(f'{_W_ONES[u]} و{_W_TENS[t]}' if u else _W_TENS[t])
    return ' و'.join(parts)


def int_to_words(n):
    """عدد صحيح موجب بالكلمات: 209511 ← «مائتان وتسعة آلاف وخمسمائة وأحد عشر». 0 ← «صفر»."""
    n = int(n)
    if n == 0:
        return 'صفر'
    parts = []
    for scale, (one, two, plural, many) in _W_SCALES:
        k, n = divmod(n, scale)
        if not k:
            continue
        r = k % 100                       # التمييز يتبع آخر العدد: 209 ← «آلاف»، 211 ← «ألف»، 200 ← «مائتا ألف»
        if k == 1:
            parts.append(one)
        elif k == 2:
            parts.append(two)
        elif 3 <= r <= 10:
            parts.append(f'{_below_1000(k)} {plural}')
        else:
            parts.append(f'{_below_1000(k, construct=True)} {many}')
    if n:
        parts.append(_below_1000(n))
    return ' و'.join(parts)


def _unit_word(n, forms):
    """التمييز بحسب العدد: (واحد، مثنى، 3–10، 11–99، غير ذلك)."""
    one, two, plural, acc, gen = forms
    if n == 1:
        return f'{one} واحد'
    if n == 2:
        return two
    r = n % 100
    if 3 <= r <= 10:
        return plural
    if 11 <= r <= 99:
        return acc
    return gen


_DINAR_FORMS = ('دينار', 'ديناران', 'دنانير', 'ديناراً', 'دينار')
_FILS_FORMS = ('فلس', 'فلسان', 'فلوس', 'فلساً', 'فلس')


def to_words(d):
    """المبلغ بالدينار الكويتي بالحروف: «مائتان وتسعة آلاف وخمسمائة وأحد عشر ديناراً وخمسمائة وخمسة عشر فلساً
    كويتي فقط لا غير». يُقرّب إلى الفلس (ROUND_HALF_UP). words_to_decimal(to_words(x)) == x."""
    from decimal import ROUND_HALF_UP
    v = abs(Decimal(d).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP))
    dinars = int(v)
    fils = int((v - dinars) * 1000)
    parts = []
    if dinars == 1 or dinars == 2:
        parts.append(_unit_word(dinars, _DINAR_FORMS))
    elif dinars:
        parts.append(f'{int_to_words(dinars)} {_unit_word(dinars, _DINAR_FORMS)}')
    if fils == 1 or fils == 2:
        parts.append(_unit_word(fils, _FILS_FORMS))
    elif fils:
        parts.append(f'{int_to_words(fils)} {_unit_word(fils, _FILS_FORMS)}')
    if not parts:
        parts.append('صفر دينار')
    return ' و'.join(parts) + ' كويتي فقط لا غير'


def _words_part(text):
    """جزء الحروف من نص المبلغ: بين قوسين، أو بعد «فقط/وقدره/مبلغ»، أو كلمات قبل «دينار»."""
    t = str(text or '')
    for m in re.finditer(r'[(\[«]([^)\]»]{3,200})(?:[)\]»]|$)', t):
        if words_to_decimal(m.group(1)) is not None:
            return m.group(1)
    toks = re.findall(r'[ء-يً-ٟ]+', t)
    if not any(norm(x).lstrip('و') in _DINAR + _FILS for x in toks):
        return ''
    if not any(_known(norm(x)) or _known(norm(x)[1:]) or norm(x)[:1] == 'و' and _known(norm(x)[1:]) for x in toks):
        return ''                                           # «دينار» وحدها ليست مبلغاً بالحروف
    return ' '.join(toks)


def reconcile(value, context=''):
    """يقارن المبلغ بالأرقام (من value) بالمبلغ بالحروف (من value ثم من context بعده مباشرة).
    يرجع dict: status، digits، words (Decimal|None)، value (المعتمد أو None)، display، message."""
    digits = digits_to_decimal(value)
    wtxt = _words_part(value)
    if not wtxt and context:
        wtxt = _words_part(context)
    words = words_to_decimal(wtxt) if wtxt else None
    if digits is not None and digits != digits.quantize(Decimal('0.001')):
        digits_bad = True
    else:
        digits_bad = False
    out = {'digits': digits, 'words': words, 'value': None, 'display': '', 'message': ''}
    if digits is None and words is None:
        out['status'] = NONE
        return out
    if digits is not None and words is not None:
        if digits == words and not digits_bad:
            out.update(status=OK, value=digits, display=fmt_kwd(digits))
        else:
            out.update(status=MISMATCH, message=(
                f'تعارض في المبلغ: بالأرقام {fmt_kwd(digits)} وبالحروف {fmt_kwd(words)} — لم يُكتب أيٌّ منهما، '
                'راجع الصحيفة الأصلية'))
        return out
    v = digits if digits is not None else words
    if digits_bad:
        out.update(status=MISMATCH, message=f'المبلغ بالأرقام {digits} أكثر من 3 خانات عشرية — راجع الصحيفة الأصلية')
        return out
    which = 'بالأرقام فقط' if digits is not None else 'بالحروف فقط'
    out.update(status=DIGITS_ONLY if digits is not None else WORDS_ONLY, value=v, display=fmt_kwd(v),
               message=f'المبلغ {fmt_kwd(v)} ورد {which}: {UNVERIFIED_MARK}')
    return out
