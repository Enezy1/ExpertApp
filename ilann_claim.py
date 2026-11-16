# ===== ilann_claim.py — سحب عنوان الطرف من صحيفة الدعوى (Gemini) =====
# وحدة مساعدة لنافذة «طلب إعلان»: تجيب صحيفة الدعوى، ترسلها للذكاء الاصطناعي
# (نفس طلب Gemini الموجود مسبقاً — مو بناء جديد)، وتستخرج عنوان الطرف المطلوب
# (مدعي / مدعى عليه) وبيانات محاميه إن وُجد.
#
# القاعدة (من العنزي 14/11/2026):
#   • لو المدعي (أو المدعى عليه) عنده محامٍ ⟵ وسيلة الإعلان تصير «مندوب» (10001)،
#     ويكتب اسم المحامي ورقم الفاكس والهاتف (إذا وُجدوا) في خانات الاتصال تحت.
#   • لو ما فيه محامٍ ⟵ العنوان ينكتب «مثل ما هو مكتوب» في خانات العنوان.
#
# شروط (14/11/2026 — الجولة الثانية، بعد تجربة الخبير):
#   • **الاستخراج يردّ الطرفين معاً**: طلب واحد ⟵ «المدعي» و«المدعى عليه» (عنوان كل
#     واحد + محاميه: اسم/هاتف/فاكس)، وبعدها **نختار المطابق محلياً**:
#     **بالصفة أولاً** (مدعي/مدعى عليه) ثم بالاسم.
#     (قبل: الطلب كان لطرف واحد، والنتيجة رجعت ببيانات المدعي للمدعى عليه.)
#   • **الملف بجذر مجلد رقم الخبرة**: صحيفة الدعوى PDF ومارك داونها **مباشرة**
#     في «<تقارير الخبراء>\<رقم الخبرة>\» — بلا «مستندات_النظام\» ولا «markdown\».
#     (العنزي: «الفولدر الاول لا تحطه بفولدر فرعي.. راح اشيلهم».)
#   • **ما ننزّل صحيفة الدعوى مرتين**: أول شي ندوّر على النسخة المحفوظة بالجهاز
#     (بالجذر أولاً، ثم المسار القديم).
#   • **Gemini أولاً**: critical=True ⟵ صور عالية الجودة للذكاء (الصحيفة ممسوح غالبا).
#   • **الرسائل بالعربي وتقول شنو مالقيت**: «صحيفة الدعوى ما تحتوي على عنوان المدعى عليه
#     — الموجود بالصحيفة: …».
#
# ⚠️ ما فيه كتابة بالنظام — هذا استخراج فقط، والتعبئة في نموذج «طلب إعلان».
# ⚠️ ما في أي تعامل مع «الإنجاز» ولا «الأتعاب».
import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile

import ilann


# ---------------------------------------------------------------------------
# برومبت الاستخراج
# ---------------------------------------------------------------------------

#: برومبت استخراج **الطرفين معاً** — JSON فقط، وبالحقول نفسها اللي في نموذج الوزارة.
#: الطلب يردّ «المدعي» و«المدعى عليه» (كل واحد بصفة وعنوان ومحاميه)، وبعدها
#: المطابقة تصير محلياً (بالصفة ثم بالاسم) — عشان ما تختلط بيانات الطرفين.
CLAIM_PARTIES_PROMPT = """أنت مساعد في وزارة العدل الكويتية. أمامك صحيفة دعوى (PDF) قضائية.

المطلوب: استخراج **طرفين** من صحيفة الدعوى مع كل بيانات كل واحد:
  1. **المدعي** (المدعية) — عنوانه كما هو مكتوب + محاميه (اسم/هاتف/فاكس) إن وُجد.
  2. **المدعى عليه** — عنوانه كما هو مكتوب + محاميه (اسم/هاتف/فاكس) إن وُجد.

⚠️ مهم: كل عنوان ومحامٍ يرجع لصاحبه. **لا تنسخ عنوان المدعي لصف المدعى عليه**
ولا عنوان المدعى عليه لصف المدعي. لو ما لقيت عنوان طرف ⟵ خلّيه null.

أعد **JSON فقط** (بدون أي نص قبله أو بعده، وبدون ```):
{
  "parties": [
    {
      "role": "المدعي" أو "المدعى عليه" (حسب موقع الطرف بالسمية)",
      "party": "اسم الطرف كما ورد بالسمية",
      "quote": "الجملة نفسها التي كُتب فيها العنوان — من نص صحيفة الدعوى بالحرف",
      "address": {
        "city": "المحافظة (العاصمة / حولي / الجهراء / الأحمدي / الفروانية / مبارك الكبير) أو null",
        "area": "المنطقة أو الحي أو null",
        "street": "الشارع أو null",
        "jadda": "الجادة أو null",
        "block": "القطعة أو null",
        "building": "المبنى أو المسيمة أو null",
        "floor": "الدور أو null",
        "unit": "رقم الوحدة أو الشقة أو المكتب أو null",
        "unit_type": "نوع الوحدة (شقة / مكتب / محل ...) أو null",
        "description": "العنوان كاملاً كما هو مكتوب حرفياً أو null"
      },
      "has_lawyer": false,
      "lawyer": {
        "name": "اسم المحامي أو null",
        "phone": "هاتف المحامي أو null",
        "fax": "فاكس المحامي أو null",
        "address": {
          "description": "عنوان المحامي كما هو مكتوب أو null"
        }
      }
    }
  ]
}

قواعد:
• انسخ كل عنوان **حرفياً** كما هو مكتوب بالسمية في "description" — هذا أهم حقل.
• في "quote" انسخ **الجملة نفسها** التي فيها العنوان (من نص صحيفة الدعوى بالحرف)
  — نتحقق منها محلياً، ولو ما كانت موجودة بالنص نعدّ الرد غير موثوق.
• "role" يا "المدعي" يا "المدعى عليه" — حسب موقع الطرف بالسمية بالضبط.
• **العنوان يبقى مقرون بصاحبه**: عنوان المدعي ما ينكتب لصف المدعى عليه والعكس.
  ولو ما لقيت عنوان طرف ⟵ "description": null و"quote": null و"has_lawyer": false.
• لو للطرف محامٍ ⟵ "has_lawyer": true مع اسمه وهاتفه وفاكسه (ولا تخمّن أي رقم).
• الأرقام بالأرقام اللاتينية فقط، ولا تخمّن أي رقم.
• لا تضف شرحاً ولا ملاحظات — JSON فقط.
"""

#: برومبت **موجّه** لطرف واحد (احتياط: لو الرد ما رجّع أطرافاً واضحة).
#: يذكر الاسم **والصفة** ويمنع نقل عنوان الطرف الآخر.
CLAIM_ADDRESS_PROMPT = """أنت مساعد في وزارة العدل الكويتية. أمامك صحيفة دعوى (PDF) قضائية.

المطلوب: استخراج **عنوان** طرف واحد فقط، محدد بالاسم والصفة:
الطرف: «{party_name}»
الصفة: {party_type}

⚠️ مهم — العنوان المطلوب هو الذي يخص **هذا الطرف بصفة فقط**:
• لو الصفة «مدعى عليه» ⟵ العنوان المطلوب هو عنوان **المدعى عليه** (خصم المدعي)،
  و**مو** عنوان المدعي.
• لو الصفة «مدعى» ⟵ العنوان المطلوب هو عنوان **المدعي** (المدعية)،
  و**مو** عنوان المدعى عليه.
• لو ما لقيت عنوان هذا الطرف ⟵ "found": false (لا تنقل عنوان الطرف الآخر أبداً).

ابحث في «بيان الدعوى» (حيث يُكتب عنوان خصم المدعي، وعنوان المدعى عليه)،
ومن بين كل العناوين اختر ما يخص هذا الطرف.

أعد **JSON فقط** (بدون أي نص قبله أو بعده، وبدون ```):
{{
  "found": true,
  "address": {{
    "city": "المحافظة (العاصمة / حولي / الجهراء / الأحمدي / الفروانية / مبارك الكبير) أو null",
    "area": "المنطقة أو الحي أو null",
    "street": "الشارع أو null",
    "jadda": "الجادة أو null",
    "block": "القطعة أو null",
    "building": "المبنى أو المسيمة أو null",
    "floor": "الدور أو null",
    "unit": "رقم الوحدة أو الشقة أو المكتب أو null",
    "unit_type": "نوع الوحدة (شقة / مكتب / محل ...) أو null",
    "description": "العنوان كاملاً كما هو مكتوب حرفياً أو null"
  }},
  "has_lawyer": false,
  "lawyer": {{
    "name": "اسم المحامي أو null",
    "phone": "هاتف المحامي أو null",
    "fax": "فاكس المحامي أو null",
    "address": {{
      "city": "المحافظة أو null",
      "area": "المنطقة أو null",
      "street": "الشارع أو null",
      "jadda": "الجادة أو null",
      "block": "القطعة أو null",
      "building": "المبنى أو المسيمة أو null",
      "floor": "الدور أو null",
      "unit": "رقم الوحدة أو الشقة أو المكتب أو null",
      "unit_type": "نوع الوحدة (شقة / مكتب / محل ...) أو null",
      "description": "عنوان المحامي كاملاً كما هو مكتوب أو null"
    }}
  }}
}}

قواعد:
• "found" = true فقط لو لقيت **عنوان** هذا الطرف بصفة؛ false لو ما لقي.
• انسخ العنوان **حرفياً** كما هو مكتوب (بما فيه «منطقة»، «قطعة»، «شارع»، «منزل»، «دور»،
  «شقة») في "description" — هذا أهم حقل.
• لو العنوان مختصر (مثل «الكويت») فاكتبه كما هو، ولا تكمّل عليه من عندك.
• الأرقام بالأرقام اللاتينية فقط، ولا تخمّن أي رقم.
• "has_lawyer": true لو للطرف محامٍ مذكور بالسمية (اسمه، أو «المحامي: …»، أو «الموكل»).
• لا تضف شرحاً ولا ملاحظات — JSON فقط.
"""

#: برومبت المحاولة الثانية — كل الأطراف بالسمية (نفس برومبت الطرفين)
ALL_ADDRESSES_PROMPT = CLAIM_PARTIES_PROMPT


# ---------------------------------------------------------------------------
# ربط حقول العنوان المستخرجة (من رد الذكاء) بحقول نموذج الوزارة
# ---------------------------------------------------------------------------

ADDR_FIELD_MAP = (
    ('street', 'ADRS_STREET'),
    ('jadda', 'ADRS_KASIMA'),
    ('block', 'ADRS_BLOCK'),
    ('building', 'ADRS_BUILDING_NO'),
    ('floor', 'ADRS_FLOOR'),
    ('unit', 'ADRS_UNIT_NO'),
    ('unit_type', 'ADRS_UNIT_TYPE'),
    ('description', 'ADRS_DESCR'),
)

#: كود «مندوب» في نموذج الوزارة (وسيلة الإعلان)
METHOD_REPRESENTATIVE = '10001'

#: اسم ملف صحيفة الدعوى داخل «مستندات النظام» — للبحث عن النسخة القديمة فقط
CLAIM_FILE_NAME = 'صحيفة_الدعوى.pdf'

#: أسماء ملف صحيفة الدعوى بالمسار القديم (داخل «مستندات النظام»): الاسم الحالي
#: «صحيفة الدعوى.pdf» والقديم «صحيفة_الدعوى.pdf»
LEGACY_CLAIM_NAMES = ('صحيفة الدعوى.pdf', CLAIM_FILE_NAME)

#: اسم صحيفة الدعوى **بجذر مجلد القضية** (بلا مجلدات فرعية — طلب العنزي 14/11/2026)
CLAIM_ROOT_NAME = 'صحيفة الدعوى'
CLAIM_ROOT_PDF = CLAIM_ROOT_NAME + '.pdf'
CLAIM_ROOT_MD = CLAIM_ROOT_NAME + '.md'
#: نسخة تُحفظ لو تغيّر محتوى الصحيفة (ما نكتب فوق أصل موجود)
CLAIM_ROOT_PREV = CLAIM_ROOT_NAME + ' — نسخة سابقة.pdf'

#: صيغة الصفة ⟶ تسمية تُقرأ بالعربي في الرسالة
PARTY_LABELS = {
    'مدعي': 'المدعي',
    'مدعى': 'المدعى',
    'مدعي عليه': 'المدعى عليه',
    'مدعى عليه': 'المدعى عليه',
    'مدعيه': 'المدعية',
    'مدعيه عليه': 'المدعية عليه',
}

#: دورا الطرف (المدعي / المدعى عليه)
ROLE_PLAINTIFF = 'plaintiff'
ROLE_DEFENDANT = 'defendant'

#: كلمات دالة على «المدعى عليه» بصفة النظام أو برد الذكاء (بعد التطبيع)
DEFENDANT_WORDS = ('مدعي عليه', 'خصم', 'defendant')
#: كلمات دالة على «المدعي» بصفة النظام أو برد الذكاء (بعد التطبيع)
PLAINTIFF_WORDS = ('مدعي', 'plaintiff')

#: تسميات الأدوار بالعربي (لرسالة «شنو مالقيت»)
ROLE_LABELS = {ROLE_PLAINTIFF: 'المدعي', ROLE_DEFENDANT: 'المدعى عليه'}

#: الأرقام الهندية والعربية ⟵ لاتينية (النظام يقبل الأرقام اللاتينية فقط)
_DIGIT_SETS = (('٠١٢٣٤٥٦٧٨٩', '0123456789'), ('۰۱۲۳۴۵۶۷۸۹', '0123456789'))

#: حدّ التطابق الاسمي (تشابه الكلمات) عند المطابقة المحلية
NAME_MATCH_MIN = 0.6
#: حدّ أخفّ يُستعمل **لما الصفة مطابقة**: الاسم يكفي أن يتشارك كلمة واحدة
#: (الاسم بالسمية ممكن يختلف عن النظام — «ش.م.ك» ≈ «ش م ك»)
ROLE_MATCH_MIN = 0.25


# ---------------------------------------------------------------------------
# أدوات نصية
# ---------------------------------------------------------------------------

def normalize(text):
    """تطبيع النص للمقارنة (المحافظة/المنطقة): «محافظه العاصمه» ≈ «العاصمة»."""
    s = (text or '').strip().lower()
    s = s.replace('محافظه', '').replace('محافظة', '')
    s = re.sub(r'[\s\-_،,.:/\\]+', '', s)
    s = s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    s = s.replace('ة', 'ه').replace('ى', 'ي').replace('ؤ', 'و').replace('ئ', 'ي')
    return s


def normalize_words(text):
    """تطبيع يحافظ على الكلمات (للمطابقة الاسمية): «ش.م.ك» ≈ «ش م ك»."""
    s = (text or '').strip().lower()
    s = re.sub(r'[\u064B-\u0652\u0670]', '', s)          # التشكيل
    s = s.replace('محافظه', '').replace('محافظة', '')
    s = re.sub(r'[^\w\u0600-\u06FF]+', ' ', s)            # النقاط والفواصل ⟵ فراغ
    s = s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    s = s.replace('ة', 'ه').replace('ى', 'ي').replace('ؤ', 'و').replace('ئ', 'ي')
    return re.sub(r'\s+', ' ', s).strip()


def latin_digits(text):
    """يحوّل الأرقام الهندية/العربية إلى لاتينية (النظام يقبل اللاتينية)."""
    s = str(text or '')
    for src, dst in _DIGIT_SETS:
        for i, ch in enumerate(src):
            s = s.replace(ch, dst[i])
    return s


def clean(text):
    """ينظّف قيمة من رد الذكاء (فراغ أو «null» أو «None» ⟵ فراغ حقيقي)."""
    return ilann.clean_value(text)


def parse_json(text):
    """يرجّع dict من رد Gemini (يتحمل ```json وأي نص زايد)."""
    raw = (text or '').strip()
    if not raw:
        return None
    m = re.search(r'\{.*\}', raw, re.S)
    if m:
        raw = m.group(0)
    try:
        data = json.loads(raw)
    except Exception:
        # محاولة أخيرة: توسيع الأقواس المكسورة
        try:
            data = json.loads(raw + '}')
        except Exception:
            return None
    return data if isinstance(data, dict) else None


def match_governorate(text, cities=None):
    """يرجّع كود المحافظة المطابق لنص (من قائمة النموذج) أو ''."""
    target = normalize(text)
    if not target:
        return ''
    for code, label in (cities or ilann.GOVERNORATES):
        n = normalize(label)
        if not n:
            continue
        if target == n or target in n or n in target:
            return str(code)
    return ''


def match_zone(area, zones):
    """يرجّع كود المنطقة المطابق لنص (من مناطق المحافظة) أو ''."""
    target = normalize(area)
    if not target:
        return ''
    for code, label in (zones or []):
        n = normalize(label)
        if not n:
            continue
        if target == n or target in n or n in target:
            return str(code)
    return ''


def name_score(a, b):
    """تشابه اسمي 0..1 (كلمات مشتركة بعد التطبيع)."""
    aw, bw = normalize_words(a), normalize_words(b)
    if not aw or not bw:
        return 0.0
    if normalize(a) == normalize(b):
        return 1.0
    A, B = set(aw.split()), set(bw.split())
    if not A or not B:
        return 0.0
    inter = A & B
    if not inter:
        return 0.0
    return len(inter) / float(len(A | B))


def party_role(text):
    """دور الطرف من نص الصفة: «مدعى» ⟵ مدعي · «مدعي عليه» ⟵ مدعى عليه.

    يشتغل على صفة النظام («مدعى» / «مدعي عليه») وعلى رد الذكاء
    («المدعي» / «المدعى عليه») وعلى القيم اللاتينية (plaintiff/defendant).
    """
    t = normalize_words(text or '')
    if not t:
        return ''
    if any(w in t for w in DEFENDANT_WORDS):
        return ROLE_DEFENDANT
    if any(w in t for w in PLAINTIFF_WORDS):
        return ROLE_PLAINTIFF
    return ''


def role_label(role):
    """تسمية الدور بالعربي («المدعي» / «المدعى عليه»)."""
    return ROLE_LABELS.get(role or '', 'الطرف')


def match_party(rows, party_name):
    """يرجّع أقرب طرف بالاسم من قائمة أطراف ({'party','address',...}) أو None."""
    best = None
    for row in rows or []:
        name = clean(row.get('party'))
        if not name:
            continue
        score = name_score(party_name, name)
        if score >= NAME_MATCH_MIN and (best is None or score > best[0]):
            best = (score, row)
    return best[1] if best else None


def select_party(rows, party_name, party_type=''):
    """اختيار الطرف المطلوب من أطراف صحيفة الدعوى.

    **بالصفة أولاً** ثم بالاسم — عشان بيانات المدعي ما تطلع للمدعى عليه:
      1. لو فيه صفوف بنفس صفة النظام ⟵ نختار منها الأقرب بالاسم.
         (لو الصفة وحدة ⟵ ناخذها حتى لو الاسم مختلف قليلاً.)
      2. وإلا ⟵ نختار الأقرب بالاسم من كل الأطراف.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows:
        return None
    role = party_role(party_type)
    pool = rows
    role_matched = False
    if role:
        same = [r for r in rows
                if party_role(r.get('role') or r.get('party_type') or '') == role]
        if same:
            pool = same
            role_matched = True
    best = None
    for row in pool:
        score = name_score(party_name, clean(row.get('party')))
        if best is None or score > best[0]:
            best = (score, row)
    if best is None:
        return None
    score, row = best
    if role_matched:
        # الصفة مطابقة ⟵ الاسم ممكن يختلف قليلاً (ش.م.ك ≈ ش م ك).
        # لو أكثر من طرف بنفس الصفة ⟵ لازم الاسم يطابق تماماً.
        need = NAME_MATCH_MIN if len(pool) > 1 else ROLE_MATCH_MIN
        if score < need:
            return None
        return row
    if score < NAME_MATCH_MIN:
        return None
    return row


def party_row_to_data(row):
    """صف طرف (من قائمة أطراف صحيفة الدعوى) ⟵ نفس شكل رد الطرف الواحد."""
    if not isinstance(row, dict):
        return None
    addr = row.get('address')
    lawyer = row.get('lawyer')
    addr = addr if isinstance(addr, dict) else {}
    lawyer = lawyer if isinstance(lawyer, dict) else {}
    return {
        'found': True,
        'address': addr,
        'has_lawyer': bool(row.get('has_lawyer')) or bool(clean(lawyer.get('name'))),
        'lawyer': lawyer,
        'role': clean(row.get('role')),
        'party': clean(row.get('party')),
    }


def party_label(party_type, party_name=''):
    """تسمية الطرف بالعربي للرسالة («المدعى عليه» …)."""
    t = (party_type or '').strip()
    return PARTY_LABELS.get(t, t or party_name or 'الطرف')


def not_found_message(party_type, party_name, found_names=None):
    """رسالة «شنو مالقيت» — بالعربي وبالتفصيل."""
    label = party_label(party_type, party_name)
    msg = 'لم نجد أي عنوان لـ%s' % label
    names = [n for n in (found_names or []) if n]
    if names:
        msg += ' — الموجود بالصحيفة: %s' % ' · '.join(names[:4])
    return msg


# ---------------------------------------------------------------------------
# استخراج محلي من نص صحيفة الدعوى (بلا ذكاء) — احتياط مضمون
# ---------------------------------------------------------------------------

#: كلمات تدل على سطر فيه عنوان (مطابقة بحدود الكلمة — «حي» ما تطابق «صيحة»)
ADDRESS_HINTS = ('قطعة', 'شارع', 'جادة', 'منزل', 'الدور', 'دور', 'شقة', 'بناية',
                 'مبنى', 'منطقة', 'الحي', 'حي', 'برج', 'عمارة', 'محل', 'مكتب',
                 'صالة', 'قطعي', 'مجمع', 'فيلا', 'مستودع', 'ورشة', 'ملكية',
                 'قسيمة', 'مقرها', 'مقر', 'مسكن', 'موطن')

#: البادئات اللي نشيلها من نص العنوان (تبقى الوصف فقط)
_ADDRESS_LABELS = ('الكائن مقرها', 'مقرها', 'الخصم', 'الطالبة', 'الطالب',
                   'المطلوب ضده', 'الموطن', 'العنوان', 'المسكن', 'يقع',
                   '(addrno)', 'منزل')

#: كلمات تدل على سطر فيه محامي
LAWYER_HINTS = ('المحامي', 'المحامية', 'محام', 'وكيل', 'موكل')

#: تسميات الهاتف (عربي وإنجليزي)
PHONE_LABELS = ('هاتف', 'تلفون', 'موبايل', 'جوال', 'tel', 'tel.', 'phone', 'mob')

#: تسميات الفاكس (عربي وإنجليزي)
FAX_LABELS = ('فاكس', 'fax')

#: رقم هاتف/فاكس (7–8 أرقام، ورمز الدولة اختياري)
_PHONE_RE = re.compile(r'(?:\+?965[\s\-]?)?\d{7,8}')

#: خانات العنوان من نص العنوان (حرفي)
_BLOCK_RE = re.compile(r'قطعة\s*([^\s،,\-]+)')
_STREET_RE = re.compile(r'شارع\s+([^\s،,]+(?:\s+[^\s،,]+)?)')
_FLOOR_RE = re.compile(r'(?:الدور|دور)\s*([^\s،,]+)')
_UNIT_RE = re.compile(r'(?:شقة|وحدة|مكتب|محل|منزل|صالة)\s*([^\s،,]+)')
_AREA_RE = re.compile(r'(?:منطقة|حي)\s+([^\s،,]+(?:\s+[^\s،,]+)?)')

#: أقصى نص نرسله للذكاء (حروف)
CLAIM_TEXT_MAX = 24000


def _address_rx():
    """تعبير يطابق كلمات العنوان **بحدود الكلمة** (حرف عربي قبلها أو بعدها ⟵ لا)."""
    body = '|'.join(re.escape(h) for h in ADDRESS_HINTS)
    return re.compile(r'(?<![؀-ۿ])(?:' + body + r')(?![؀-ۿ])')


#: matcher لكلمات العنوان (يبني مرة واحدة)
_ADDRESS_RX = _address_rx()


def _has_address_hint(line):
    """هل السطر فيه كلمة عنوان (بحدود الكلمة)؟"""
    return bool(line) and bool(_ADDRESS_RX.search(line))


def claim_lines(text):
    """أسطر نص صحيفة الدعوى (نظيفة)."""
    return [l.strip() for l in (text or '').splitlines()]


def claim_text_for_ai(text, max_chars=CLAIM_TEXT_MAX):
    """نص الصحيفة المرسل للذكاء — كله (مو صفحتين) مع حد أقصى."""
    t = (text or '').strip()
    return t[:max_chars] if len(t) > max_chars else t


def quote_in_text(quote, text):
    """هل الاقتباس موجود فعلاً بنص صحيفة الدعوى؟ (يمنع رد مو حقيقي)"""
    q = normalize_words(quote)
    if len(q) < 8:
        return False
    return q in normalize_words(text)


def party_line_hits(lines, party_name):
    """أرقام أسطر اسم الطرف داخل نص صحيفة الدعوى (أعلى تشابه)."""
    norm = [normalize_words(l) for l in lines]
    target = normalize_words(party_name)
    keys = [k for k in target.split() if len(k) > 2]
    if not keys:
        return []
    scored = []
    for i, n in enumerate(norm):
        if not n:
            continue
        if target and target in n:
            scored.append((99, i))
            continue
        shared = sum(1 for k in keys if k in n)
        if shared:
            scored.append((shared, i))
    if not scored:
        return []
    best = max(s for s, _ in scored)
    if best < 2 and len(keys) >= 2:
        return []       # الاسم ما طابق كاملاً — ما نخمّن
    return [i for s, i in scored if s >= best]


def _clean_address_line(line):
    """يشيل بادئة العنوان («الكائن مقرها:») ويقصّ الذيل."""
    out = (line or '').strip()
    for label in _ADDRESS_LABELS:
        if out.startswith(label):
            out = out[len(label):].lstrip(' :،-–—')
            break
    return out.strip(' :،-–—')


def address_line_near(lines, hits, party_name):
    """أفضل سطر فيه عنوان قريب من اسم الطرف — (النص، الفهرس) أو ('', -1).

    العنوان يكمل بالأسطر التالية فنضمّها (سطرين على الأكثر).
    """
    target = normalize_words(party_name)
    best = None
    for i in hits:
        for j in range(max(0, i - 3), min(len(lines), i + 9)):
            line = lines[j]
            if not _has_address_hint(line):
                continue
            score = 2 * (4 - min(3, abs(j - i)))     # الأقرب لاسم الطرف
            if j > i:
                score += 1                         # العنوان عادة **بعد** اسم الطرف
            if target and target in normalize_words(line):
                score += 4
            if best is None or score > best[0]:
                best = (score, j)
    if not best:
        return '', -1
    j = best[1]
    parts = [_clean_address_line(lines[j])]
    for k in range(j + 1, min(len(lines), j + 3)):     # تكملة العنوان
        nxt = lines[k]
        if not nxt or not _has_address_hint(nxt):
            break
        parts.append(_clean_address_line(nxt))
    return ' '.join(p for p in parts if p).strip(), j


def parse_address_fields(description):
    """خانات العنوان من نصه (قطعة/شارع/دور/شقة/منطقة)."""
    out = {}
    d = description or ''
    for key, rx in (('block', _BLOCK_RE), ('street', _STREET_RE),
                    ('floor', _FLOOR_RE), ('unit', _UNIT_RE), ('area', _AREA_RE)):
        m = rx.search(d)
        if m:
            out[key] = latin_digits(m.group(1).strip('.').strip())
    return out


def governorate_in_text(text):
    """اسم المحافظة المذكورة بنص صحيفة الدعوى ('' لو ما ظهرت)."""
    flat = normalize(text)
    for _code, label in ilann.GOVERNORATES:
        n = normalize(label)
        if n and n in flat:
            return label
    return ''


def contacts_from_text(text):
    """(هاتف، فاكس) من نص صحيفة الدعوى — التسميات بالعربي أو الإنجليزي."""
    phone = fax = ''
    for line in claim_lines(text):
        low = line.lower()
        cut = -1
        for label in FAX_LABELS:
            pos = low.find(label)
            if pos >= 0:
                cut = pos
                break
        head, tail = (line[:cut], line[cut:]) if cut > 0 else (line, '')
        if cut > 0:
            m = _PHONE_RE.search(tail)
            if m and not fax:
                fax = m.group(0).strip()
        if any(label in low for label in PHONE_LABELS):
            m = _PHONE_RE.search(head)
            if m and not phone:
                phone = m.group(0).strip()
    return phone, fax


def lawyer_from_text(text):
    """اسم المحامي من نص صحيفة الدعوى (الكلمات قبل «المحامي/المحامية»)."""
    for line in claim_lines(text):
        low = line.lower()
        positions = [low.find(h) for h in LAWYER_HINTS if h in low]
        if not positions:
            continue
        before = line[:min(positions)]
        words = [w for w in re.split(r'[\s،,:؛/\\()\[\]\-]+', before) if w]
        words = [w for w in words if re.search(r'[\u0600-\u06ff]', w)]
        if len(words) >= 2:
            return ' '.join(words[-3:]).strip()
    return ''


def local_address(text, party_name, party_type=''):
    """استخراج عنوان الطرف من نص صحيفة الدعوى محلياً (بلا ذكاء).

    احتياط مضمون: لو العنوان مكتوب فعلاً بالصحيفة — نلقاه بالكود.
    يرجع نفس شكل رد الذكاء، أو None.
    """
    lines = claim_lines(text)
    if not lines:
        return None
    hits = party_line_hits(lines, party_name)
    if not hits:
        return None
    desc, _idx = address_line_near(lines, hits, party_name)
    if not desc:
        return None
    fields = parse_address_fields(desc)
    address = {'city': governorate_in_text(text), 'area': fields.get('area', ''),
               'street': fields.get('street', ''), 'jadda': '', 'block': fields.get('block', ''),
               'building': '', 'floor': fields.get('floor', ''), 'unit': fields.get('unit', ''),
               'unit_type': '', 'description': desc}
    lname = lawyer_from_text(text)
    phone, fax = contacts_from_text(text)
    lawyer = {'name': lname, 'phone': phone, 'fax': fax, 'address': {'description': ''}}
    return {'found': True, 'address': address,
            'has_lawyer': bool(lname or phone or fax), 'lawyer': lawyer,
            'role': party_type or '', 'party': party_name or '', 'local': True}
# ---------------------------------------------------------------------------
# تحويل رد الذكاء ⟶ قيم نموذج «طلب إعلان»
# ---------------------------------------------------------------------------

def build_values(data, cities=None, zones=None):
    """يحوّل رد الذكاء إلى قيم حقول نموذج «طلب إعلان».

    القواعد (من العنزي 14/11/2026):
      • **بلا محامٍ** ⟵ العنوان «مثل ما هو مكتوب»: خانات العنوان تُملأ بالتفاصيل
        المستخرجة، والنص الكامل للعنوان يروح «الوصف» (ADRS_DESCR).
      • **مع محامٍ**  ⟵ وسيلة الإعلان تصير «مندوب» (10001)، واسم المحامي وفاكسه
        وهاتفه تروح خانات الاتصال تحت (رقم الاتصال + عنوان آخر + الملاحظات).

    يرجّع dict:
        {'fields': {اسم الحقل: القيمة}, 'city_code', 'zone_code', 'area',
         'method', 'has_lawyer', 'lawyer_name', 'lawyer_phone', 'lawyer_fax'}
    """
    data = data or {}
    addr = data.get('address') or {}
    lawyer = data.get('lawyer') or {}

    name = clean(lawyer.get('name'))
    phone = latin_digits(clean(lawyer.get('phone')))
    fax = latin_digits(clean(lawyer.get('fax')))
    has_lawyer = bool(data.get('has_lawyer')) or bool(name or phone or fax)

    fields = {}
    for src, dst in ADDR_FIELD_MAP:
        value = latin_digits(clean(addr.get(src)))
        if value:
            # ⚠️ قصّ حسب حدّ النظام (maxlength) — مثل الموقع بالضبط.
            #    بدونه يرفض السيرفر القيمة بـORA-12899 (15/11/2026):
            #    «value too large for column … ADRS_BUILDING_NO (actual: 9, maximum: 5)»
            fields[dst] = ilann.truncate_field(dst, value)

    # العنوان «مثل ما هو مكتوب»: لو ما في وصف كامل نركّبه من الأجزاء
    if not fields.get('ADRS_DESCR'):
        parts = [fields.get(k) for k in ('ADRS_STREET', 'ADRS_BLOCK',
                                         'ADRS_BUILDING_NO', 'ADRS_FLOOR',
                                         'ADRS_UNIT_NO') if fields.get(k)]
        if parts:
            fields['ADRS_DESCR'] = ' '.join(parts)

    city_code = match_governorate(addr.get('city'), cities)
    zone_code = match_zone(addr.get('area'), zones)

    method = ''
    if has_lawyer:
        method = METHOD_REPRESENTATIVE
        contact = phone or fax
        if contact:
            fields['ADDRNO'] = contact[:12]
        if name:
            fields['MAIN_CNTD_TYPE_DESC'] = ('المحامي: %s' % name)[:150]
        bits = []
        if name:
            bits.append('المحامي: %s' % name)
        if phone:
            bits.append('هاتف: %s' % phone)
        if fax:
            bits.append('فاكس: %s' % fax)
        note = ' · '.join(bits)
        lawyer_desc = clean((lawyer.get('address') or {}).get('description'))
        if lawyer_desc and len(note) + len(lawyer_desc) + 16 <= 150:
            note = '%s · عنوان المحامي: %s' % (note, lawyer_desc)
        if note:
            fields['EIF_NOTE'] = note[:150]

    return {
        'fields': fields,
        'city_code': city_code,
        'zone_code': zone_code,
        'area': clean(addr.get('area')),
        'method': method,
        'has_lawyer': has_lawyer,
        'lawyer_name': name,
        'lawyer_phone': phone,
        'lawyer_fax': fax,
    }


def summary_of(values):
    """سطر ملخّص للنتيجة (يظهر جنب الزر)."""
    values = values or {}
    if values.get('has_lawyer'):
        lawyer = values.get('lawyer_name') or 'محامي'
        bits = ['العنوان مستخرج', 'المحامي: %s' % lawyer, 'وسيلة الإعلان: مندوب']
        if values.get('lawyer_phone'):
            bits.append('هاتف: %s' % values['lawyer_phone'])
        if values.get('lawyer_fax'):
            bits.append('فاكس: %s' % values['lawyer_fax'])
        return ' · '.join(bits)
    bits = ['العنوان مستخرج (مثل ما هو مكتوب بالصحيفة)']
    if values.get('area'):
        bits.append('المنطقة: %s' % values['area'])
    return ' · '.join(bits)


# ---------------------------------------------------------------------------
# ملف صحيفة الدعوى على الجهاز — **بجذر مجلد رقم الخبرة**
# ---------------------------------------------------------------------------

def _file_ok(path):
    """ملف موجود وحجمه أكبر من صفر."""
    try:
        return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _sha1(path):
    h = hashlib.sha1()
    try:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
    except OSError:
        return ''
    return h.hexdigest()


def _case_base(caso_no):
    """مسار مجلد القضية (الجذر المسجّل بالإعدادات) — '' لو تعذّر."""
    if not caso_no:
        return ''
    try:
        import case_workspace
        return case_workspace.case_dir(str(caso_no).strip())
    except Exception:
        return ''


def sysdocs_dir(caso_no, create=False):
    """مجلد «مستندات النظام» داخل مجلد القضية — مسار قديم (للبحث فقط)."""
    if not caso_no:
        return ''
    try:
        import case_workspace
        import case_folder
        base = case_workspace.case_dir(str(caso_no).strip())
    except Exception:
        return ''
    path = os.path.join(base, case_folder.SYSDOCS)
    if create:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            return ''
    return path


def find_local_claim(caso_no):
    """مسار صحيفة الدعوى المحفوظة بالجهاز (لو موجودة) — عشان ما ننزّلها مرتين.

    **أحدث نسخة** موجودة (بالجذر أو بالمسار القديم) — مو أي نسخة.
    """
    base = _case_base(caso_no)
    if not base:
        return ''
    got = _newest_claim_copy(base)
    return got[0] if got else ''

def ensure_case_dir(caso_no):
    """مجلد القضية تحت «تقارير الخبراء» المسجّل بالإعدادات — يُنشأ إن لزم.

    يرجع (base, data) — نفس عقد case_workspace.ensure_workspace.
    """
    import case_workspace
    return case_workspace.ensure_workspace({'caso_no': str(caso_no or '').strip()})


def claim_rel_paths():
    """(المسار النسبي للـPDF، المسار النسبي للمارك داون) لصحيفة الدعوى.

    **بجذر مجلد القضية** — بلا مجلدات فرعية (طلب العنزي 14/11/2026).
    """
    return CLAIM_ROOT_PDF, CLAIM_ROOT_MD


def _mtime(path):
    """وقت تعديل الملف (0 لو ما موجود)."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _same_path(a, b):
    """نفس المسار؟ (مقارنة لا تتأثر بحالة الأحرف)."""
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:
        return False


def _claim_candidates(base):
    """[(PDF، مارك داون)] لكل نسخ صحيفة الدعوى المعروفة.

    **بالجذر** (المكان الجديد) + **بالمسار القديم** («مستندات النظام») — بكل اسمَيها.
    """
    import case_folder as cf
    out = [(os.path.join(base, CLAIM_ROOT_PDF), os.path.join(base, CLAIM_ROOT_MD))]
    for name in LEGACY_CLAIM_NAMES:
        pdf = os.path.join(base, cf.SYSDOCS, name)
        md_rel = cf.md_rel('%s/%s' % (cf.SYSDOCS, name)).replace('/', os.sep)
        out.append((pdf, os.path.join(base, md_rel)))
    return out


def _newest_claim_copy(base):
    """أحدث نسخة صحيفة دعوى موجودة — ((PDF، مارك داون الخاص فيها)) أو None.

    newest = الأحدث وقت تعديل — عشان ما نرجع لنسخة قديمة نسيها بالجذر.
    """
    best = None
    for pdf, md in _claim_candidates(base):
        if not _file_ok(pdf):
            continue
        t = _mtime(pdf)
        if best is None or t > best[0]:
            best = (t, pdf, md)
    if not best:
        return None
    return best[1], best[2]


def _best_claim_markdown(base, pdf_mtime):
    """مارك داون صالحة للـPDF — الأحدث وقت تعديل (وإلا فهي لنسخة أقدم) — أو ''."""
    best = None
    for _pdf, md in _claim_candidates(base):
        if not _file_ok(md):
            continue
        t = _mtime(md)
        if t < pdf_mtime:
            continue
        if best is None or t > best[0]:
            best = (t, md)
    return best[1] if best else ''


def _copy_file(src, dst):
    """نسخ ملف (نسخ ذرّي: ملف مؤقت ⟵ os.replace)."""
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    tmp = dst + '.part'
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def _write_text(path, text):
    """كتابة نص ذرّية (مؤقت ⟵ os.replace)."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.md.', suffix='.tmp',
                               dir=os.path.dirname(path) or '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text or '')
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _register_claim(base, data, pdf):
    """يسجّل صحيفة الدعوى في case.json (المسار النسبي للجذر) — عشان باقي البرنامج يلاقيها."""
    rec = dict((data.get('sources') or {}).get('claim') or {})
    rel = os.path.relpath(pdf, base).replace('\\', '/')
    rec.update({
        'file': rel,
        'sha1': _sha1(pdf),
        'origin': rec.get('origin') or 'system',
        'fetched_at': rec.get('fetched_at')
        or datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })
    data.setdefault('sources', {})['claim'] = rec
    return rec


def _store_claim_pdf(base, data, src_path):
    """ينسخ صحيفة الدعوى **لجذر مجلد القضية** ويسجّلها.

    لو الموجود بالجذر، المحتوى مختلف ⟵ القديم ينحفظ «نسخة سابقة» (ما نكتب فوق أصل).
    """
    import case_sources as cs
    dst = os.path.join(base, CLAIM_ROOT_PDF)
    if _file_ok(dst):
        try:
            same = cs.content_key(dst) == cs.content_key(src_path)
        except Exception:
            same = False
        if not same:
            try:
                shutil.copy2(dst, os.path.join(base, CLAIM_ROOT_PREV))
            except OSError:
                pass
    _copy_file(src_path, dst)
    _register_claim(base, data, dst)
    return dst


def _read_text(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def convert_to_markdown(pdf_path, kind=None):
    """PDF ⟶ مارك داون (مع الحفاظ على كل الكلمات والصيغ) — محرّك المستند.

    يرجع (نص، صفحات، محرّك).
    """
    import case_folder as cf
    kind = kind or cf.PLAINT
    convert = cf.CONVERTER or cf._default_convert
    text, pages, engine, _retries = cf.convert_guarded(convert, pdf_path, kind)
    return text, pages, engine


def ensure_claim_markdown(cookies, caso_no, auto_no, user_id='309', progress=None):
    """يتأكد إن صحيفة الدعوى **بجذر مجلد رقم الخبرة** ومحوّلة مارك داون.

    الترتيب (طلب العنزي 15/11/2026 — «ما جيت تفتح هل هي موجودة»):
      1. **نسخة موجودة؟** ⟵ **نستخدمها** (ما ننزّل ولا نحوّل) — **الأحدث** وقت تعديل،
         وبالجذر أو بالمسار القديم (ننسخها للجذر مرة وحدة ونتخلص منها).
      2. ما موجودة؟ ⟵ ننزّل **أحدث** صحيفة من الملف الآلي ونحفظها **بجذر المجلد**.
      3. المارك داون موجودة؟ (وأحدث من الـPDF) ⟵ **وقف** · لا ⟵ نحوّلها ونحفظها بالجذر.

    يرجع dict: {'ok','base','rel','md_rel','pdf','md','text','engine','message'}
    """
    import case_sources as cs
    import case_workspace as cw

    def say(text):
        if progress:
            try:
                progress(text)
            except Exception:
                pass

    if not caso_no:
        return {'ok': False, 'message': 'ما فيه رقم خبرة — ما قدرنا نحدد مجلد القضية.'}
    try:
        base, data = ensure_case_dir(caso_no)
    except Exception as e:
        return {'ok': False, 'message': 'تعذّر تجهيز مجلد القضية: %s' % e}

    rel, md_rel = claim_rel_paths()
    pdf = os.path.join(base, rel)
    md = os.path.join(base, md_rel)

    def finish(text, engine, message):
        """تسجيل النص المحفوظ + case.json ⟵ عشان باقي البرنامج ما يعيد التحويل."""
        try:
            cs.save_text(base, data, 'claim', text,
                         {'engine': engine, 'label': engine, 'skipped': []})
            cw.write_case_json(base, data)
        except Exception:
            pass    # فشل التسجيل ما يوقف النتيجة
        return {'ok': True, 'base': base, 'rel': rel, 'md_rel': md_rel,
                'pdf': pdf, 'md': md, 'text': text, 'engine': engine,
                'message': message}

    def convert_now():
        """تحويل الـPDF الموجودة لمارك داون (بالجذر)."""
        say('نحوّل صحيفة الدعوى لمارك داون…')
        try:
            text, pages, engine = convert_to_markdown(pdf)
        except Exception as e:
            return None, None, {'ok': False, 'pdf': pdf,
                                'message': 'تعذّر تحويل صحيفة الدعوى لمارك داون: %s' % e}
        if not (text or '').strip():
            return None, None, {'ok': False, 'pdf': pdf,
                                'message': 'ما قدرنا نقرأ صحيفة الدعوى (فارغة بعد التحويل).'}
        try:
            _write_text(md, text)
        except OSError as e:
            return None, None, {'ok': False, 'pdf': pdf,
                                'message': 'تعذّر حفظ مارك داون صحيفة الدعوى: %s' % e}
        return text, engine, None

    # (1) **نسخة موجودة؟** ⟵ نستخدمها (مو تنزيل ولا تحويل)
    got = _newest_claim_copy(base)
    if got:
        src_pdf, _src_md = got
        copied = False
        if not _same_path(src_pdf, pdf):
            # موجودة بمجلد فرعي ⟵ ننسخها للجذر (والقديم ينحفظ «نسخة سابقة»)
            try:
                _store_claim_pdf(base, data, src_pdf)
                copied = True
            except OSError as e:
                return {'ok': False, 'pdf': pdf,
                        'message': 'تعذّر نسخ صحيفة الدعوى لجذر المجلد: %s' % e}
        else:
            _register_claim(base, data, pdf)
        # المارك داون: لازم تكون **أحدث** من الـPDF (إلا فهي لنسخة أقدم)
        src_md = _best_claim_markdown(base, _mtime(pdf))
        if src_md:
            text = _read_text(src_md)
            if text.strip():
                if not _same_path(src_md, md):
                    try:
                        _copy_file(src_md, md)
                    except OSError:
                        pass
                note = ('نسخنا صحيفة الدعوى الموجودة لجذر المجلد — ما نزلناها من جديد.'
                        if copied else
                        'استخدمنا صحيفة الدعوى الموجودة بمجلد رقم الخبرة — ما نزلناها من جديد.')
                return finish(text, 'موجود مسبقاً', note)
        # الـPDF موجودة بس المارك داون ناقصة/قديمة ⟵ نحوّلها (مرة وحدة)
        text, engine, err = convert_now()
        if err:
            return err
        return finish(text, engine,
                      'حوّلنا صحيفة الدعوى الموجودة لمارك داون (ما نزلناها من جديد).')

    # (2) ما موجودة ⟵ ننزّل **أحدث** صحيفة من الملف الآلي
    if not auto_no:
        return {'ok': False, 'pdf': pdf,
                'message': 'ما فيه رقم آلي للقضية — تعذّر جلب صحيفة الدعوى.'}
    say('نزّلنا صحيفة الدعوى من الملف الآلي…')
    fd, tmp = tempfile.mkstemp(suffix='.pdf', prefix='ilann_claim_')
    os.close(fd)
    try:
        _path, status = fetch_newest_claim(cookies, auto_no, tmp, user_id)
        if status == 'NO_AUTOCASE':
            return {'ok': False, 'pdf': pdf,
                    'message': 'ما فيه رقم آلي للقضية — تعذّر جلب صحيفة الدعوى.'}
        if status != 'OK':
            return {'ok': False, 'pdf': pdf,
                    'message': 'ما فيه صحيفة دعوى متاحة بالملف الآلي لهذه القضية.'}
        _store_claim_pdf(base, data, tmp)
    except Exception as e:
        return {'ok': False, 'pdf': pdf,
                'message': 'تعذّر تنزيل صحيفة الدعوى: %s' % e}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    # (3) التحويل لمارك داون
    text, engine, err = convert_now()
    if err:
        return err
    return finish(text, engine,
                  'نزّلنا صحيفة الدعوى وحولناها مارك داون بمجلد رقم الخبرة.')


def _doc_date(value):
    """تاريخ المستند (لاختيار الأحدث) — نفس صيغ نظام الوزارة."""
    v = (value or '').strip()
    for fmt in ('%m/%d/%Y %I:%M:%S %p', '%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(v, fmt)
        except Exception:
            continue
    return datetime.datetime.min


def fetch_newest_claim(cookies, autocase_no, out_path, user_id='309'):
    """ينزّل **أحدث** صحيفة دعوى (نفس اختيار زر «الملف الآلي») إلى out_path.

    يرجّع (path, status) — status: 'OK' / 'NO_CLAIM_DOC' / 'NO_AUTOCASE'
    """
    from documents import (get_documents_page, parse_sections, classify_document,
                           download_judgment_pdf, is_login_page, LoginPageError)
    if not (autocase_no or '').strip():
        return None, 'NO_AUTOCASE'
    html = get_documents_page(cookies, autocase_no, user_id)
    if is_login_page(html):
        raise LoginPageError('جلسة منتهية — صفحة تسجيل دخول')
    sections = parse_sections(html)
    rows = []
    for section_rows in (sections or {}).values():
        for row in section_rows or []:
            try:
                kind = classify_document(row)
            except Exception:
                kind = None
            if kind == 'claim':
                rows.append(row)
    if not rows:
        return None, 'NO_CLAIM_DOC'
    rows.sort(key=lambda r: _doc_date(r.get('doc_date')), reverse=True)
    download_judgment_pdf(cookies, rows[0].get('doc_id'), out_path)
    return out_path, 'OK'


# ---------------------------------------------------------------------------
# الاستخراج بالذكاء
# ---------------------------------------------------------------------------

def _ask_gemini(pdf_path, prompt):
    """طلب واحد للذكاء — **Gemini أولاً** (critical=True ⟵ صور عالية الجودة).

    يرجّع (data, error).
    """
    from gemini_config import generate_from_pdf
    try:
        resp = generate_from_pdf(prompt, pdf_path, pages=(1, 2, 3),
                                 purpose='extract', task='text_light', critical=True)
    except Exception as e:
        if type(e).__name__ == 'PersonalKeyFailure':
            return None, 'مفتاحك الشخصي للذكاء فشل — جرّب مرة ثانية.'
        return None, 'تعذّر إرسال صحيفة الدعوى للذكاء: %s' % e
    text = (getattr(resp, 'text', '') or '').strip()
    data = parse_json(text)
    if not data:
        return None, 'ما قدرنا نفهم رد الذكاء على صحيفة الدعوى — جرّب مرة ثانية.'
    return data, None


def _rows_of(data):
    """أطراف الرد: قائمة «parties» أو رد طرف واحد (للتوافق مع الردود القديمة)."""
    if not isinstance(data, dict):
        return []
    rows = data.get('parties')
    if isinstance(rows, list) and rows:
        return [r for r in rows if isinstance(r, dict)]
    if 'address' in data or 'found' in data:
        return [data]
    return []


def _unlabeled_single(data, rows):
    """رد بطرف واحد **بلا هوية** (ما قال مين هو) — ما نعرف مين هو ⟵ ما نقبله."""
    if not isinstance(data, dict):
        return False
    if isinstance(data.get('parties'), list):
        return False
    if len(rows) != 1:
        return False
    row = rows[0]
    return not (clean(row.get('party')) or clean(row.get('role')))


def _has_address(data):
    """هل الرد فيه عنوان فعلي (مو بس اسم محافظة)؟"""
    addr = (data or {}).get('address') or {}
    for key, value in addr.items():
        if key == 'city':
            continue
        if clean(value):
            return True
    return False


def _pick_from_rows(rows, party_name, party_type, sent_text=''):
    """يختار الطرف المطلوب من أطراف صحيفة الدعوى — (data, error)."""
    row = select_party(rows, party_name, party_type)
    if row:
        data = party_row_to_data(row)
        quote = clean(row.get('quote'))
        if quote and sent_text and not quote_in_text(quote, sent_text):
            # الاقتباس ما موجود بنص الصحيفة ⟵ الرد مو موثوق، ما نعبّئ منه
            return None, None
        if not _has_address(data):
            return None, None      # ما فيه عنوان بالرد ⟵ نكمّل بالاستخراج المحلي
        return data, None
    names = [clean(r.get('party')) for r in rows if isinstance(r, dict)]
    return None, not_found_message(party_type, party_name, names)


def _ask_targeted(ask, party_name, party_type, sent_text=''):
    """طلب موجّه للطرف الواحد (بالاسم والصفة) — احتياط."""
    prompt = CLAIM_ADDRESS_PROMPT.format(party_name=party_name or 'غير معروف',
                                         party_type=party_type or '')
    data, err = ask(prompt)
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, 'ما قدرنا نفهم رد الذكاء على صحيفة الدعوى — جرّب مرة ثانية.'
    if isinstance(data.get('parties'), list) and data['parties']:
        # الرد بقائمة أطراف ⟵ نختار المطابق ونقول «شنو مالقيت» لو ما طابق
        return _pick_from_rows(_rows_of(data), party_name, party_type, sent_text)
    if data.get('found'):
        out = party_row_to_data(data)
        out['found'] = True
        return out, None
    return None, not_found_message(party_type, party_name, [])


def _extract_with(ask, party_name, party_type, sent_text=''):
    """الاستخراج — ثلاث طبقات:

    1. **الذكاء**: طلب واحد للطرفين (المدعي + المدعى عليه) — والاقتباس يتحقق منه
       محلياً (لو ما كان بنص prestação ⟵ الرد مو موثوق).
    2. **محلياً**: بحث بالاسم في نص صحيفة الدعوى واستخراج سطر العنوان (بلا ذكاء).
    3. **طلب موجّه**: للطرف الواحد بالاسم والصفة.
    """
    data, err = ask(CLAIM_PARTIES_PROMPT)
    if err:
        local = local_address(sent_text, party_name, party_type)
        if local:
            return local, None
        return None, err
    rows = _rows_of(data)
    picked, perr = _pick_from_rows(rows, party_name, party_type, sent_text)
    if picked:
        return picked, None
    # ما طابق (أو الاقتباس ما تأكد) ⟵ **محلياً** أول، ثم طلب موجّه
    local = local_address(sent_text, party_name, party_type)
    if local:
        return local, None
    targeted, terr = _ask_targeted(ask, party_name, party_type, sent_text)
    if targeted:
        return targeted, None
    return None, terr or perr


def extract_party_address(pdf_path, party_name, party_type):
    """يستخرج عنوان الطرف من ملف صحيفة الدعوى (PDF). يرجع (data, error).

    الطلب الأول: **الطرفين معاً** (المدعي + المدعى عليه)، وبعدها المطابقة محلياً.
    """
    def ask(p):
        return _ask_gemini(pdf_path, p)

    return _extract_with(ask, party_name, party_type)


#: كم صفحة من نص صحيفة الدعوى نحتفظ بها (مرجع قديم — الحين نرسل النص كله)
CLAIM_PAGES_TO_SEND = 2


def first_pages(text, pages=CLAIM_PAGES_TO_SEND):
    """أول N صفحات من نص المارك داون (فاصل الصفحة: «<!-- صفحة N -->»)."""
    t = text or ''
    marks = re.findall(r'<!--\s*صفحة\s+\d+\s*-->', t)
    if marks:
        chunks = re.split(r'<!--\s*صفحة\s+\d+\s*-->', t)
        return '\n'.join(c.strip() for c in chunks[1:pages + 1] if c.strip()).strip()
    return t[:pages * 4000]


def extract_party_address_from_text(text, party_name, party_type,
                                    pages=CLAIM_PAGES_TO_SEND):
    """يرسل **نص** صحيفة الدعوى للذكاء ويستخرج عنوان الطرف.

    نرسل **النص كله** (مو صفحتين) — العنوان ممكن يكون بأي صفحة.
    ويرجع (data, error).
    """
    import case_research
    chunk = claim_text_for_ai(text)
    if not chunk.strip():
        return None, 'نص صحيفة الدعوى فاضي.'

    def ask(p):
        full = '%s\n\n--- نص صحيفة الدعوى ---\n%s' % (p, chunk)
        try:
            reply = case_research.default_ask(full, task='extract', spec='gemini,openai')
        except Exception as e:
            if type(e).__name__ == 'ProviderMissing':
                return None, 'ما فيه مزوّد ذكاء جاهز للاستخراج — راجع الإعدادات.'
            return None, 'تعذّر إرسال نص صحيفة الدعوى للذكاء: %s' % e
        data = parse_json(reply)
        if not data:
            return None, 'ما قدرنا نفهم رد الذكاء على صحيفة الدعوى — جرّب مرة ثانية.'
        return data, None

    return _extract_with(ask, party_name, party_type, chunk)


def fetch_and_extract(cookies, autocase_no, party_name, party_type, user_id='309',
                      caso_no='', progress=None):
    """الجلب + التحويل + الاستخراج. يرجع (data, error, message).

    المسار (طلب العنزي 14/11/2026):
      1. مجلد رقم الخبرة + صحيفة الدعوى + المارك داون (تأكّد ⟵ نزّل ⟵ حوّل).
      2. نرسل **أول صفحتين** من نص المارك داون للذكاء ونستخرج عنوان الطرف.
      3. لو النص ما نفع ⟵ نجرّب الملف مباشرة (Gemini بصور عالية الجودة).
    """
    prep = ensure_claim_markdown(cookies, caso_no, autocase_no, user_id, progress)
    text = prep.get('text') or ''
    note = prep.get('message') or ''

    def done(data):
        return data, None, ('تم استخراج العنوان من صحيفة الدعوى. ' + note).strip()

    if text:
        if progress:
            progress('جاري سحب المعلومات من صحيفة الدعوى…')
        data, err = extract_party_address_from_text(text, party_name, party_type)
        if data:
            return done(data)
        pdf = prep.get('pdf') or ''
        if pdf and os.path.exists(pdf):
            data2, err2 = extract_party_address(pdf, party_name, party_type)
            if data2:
                return done(data2)
            err = err2 or err
        return None, err, None

    pdf = prep.get('pdf') or ''
    if pdf and os.path.exists(pdf):
        if progress:
            progress('جاري سحب المعلومات من صحيفة الدعوى…')
        data, err = extract_party_address(pdf, party_name, party_type)
        if data:
            return done(data)
        return None, err, None
    return None, None, note or 'ما فيه صحيفة دعوى متاحة بالملف الآلي لهذه القضية.'
