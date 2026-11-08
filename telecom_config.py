# ===== telecom_config.py — شركات الاتصالات لميزة «تقارير الخبراء» =====
# القسم [telecom_companies] في gemini_network.ini (بجانب البرنامج).
# كل سطر:  الاسم_الأساسي = صيغة1 | صيغة2 | صيغة3
# الاسم الأساسي نفسه يُطابَق أيضاً دون الحاجة لتكراره في الصيغ.
import os
import re
import sys

SECTION = 'telecom_companies'
_INI_NAME = 'gemini_network.ini'

_TASHKEEL = re.compile(r'[ؐ-ًؚ-ٰٟۖ-ۭـ]')
_CHAR_MAP = str.maketrans({'ة': 'ه', 'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ى': 'ي', 'ؤ': 'و', 'ئ': 'ي'})


# الشركات الثلاث الافتراضية؛ تُكتب في [telecom_companies] ويعدّلها المستخدم يدوياً في الملف.
DEFAULT_COMPANIES = {
    'أوريدو': ['الوطنية للاتصالات المتنقلة', 'اوريدو', 'Ooredoo', 'الوطنية للاتصالات'],
    'زين': ['شركة الاتصالات المتنقلة', 'زين', 'Zain', 'MTC'],
    'stc': ['شركة الاتصالات الكويتية', 'stc', 'اس تي سي', 'الاتصالات الكويتية'],
}


def ini_path():
    base = (os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
            else os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, _INI_NAME)


def normalize(text):
    """توحيد: ة/ه، أ/إ/آ/ا، ى/ي، حذف التشكيل والتطويل، توحيد المسافات، أحرف صغيرة."""
    t = _TASHKEEL.sub('', str(text or '')).translate(_CHAR_MAP).lower()
    t = re.sub(r'[^\w\s]', ' ', t)           # علامات الترقيم → مسافة
    return ' '.join(t.split())


def _parse_section(text):
    """يقرأ القسم من نص الملف مباشرة (بلا configparser حتى لا نلمس بقية الملف)."""
    out, inside = {}, False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('[') and line.endswith(']'):
            inside = (line[1:-1].strip() == SECTION)
            continue
        if not inside or not line or line[0] in ';#' or '=' not in line:
            continue
        name, _, rest = line.partition('=')
        name = name.strip()
        if name:
            out[name] = [a.strip() for a in rest.split('|') if a.strip()]
    return out


def load_companies(path=None):
    """{الاسم_الأساسي: [صيغ بديلة]} — الافتراضية إن لم يوجد الملف أو كان القسم فارغاً."""
    try:
        with open(path or ini_path(), encoding='utf-8') as f:
            return _parse_section(f.read()) or {k: list(v) for k, v in DEFAULT_COMPANIES.items()}
    except OSError:
        return {k: list(v) for k, v in DEFAULT_COMPANIES.items()}


def save_companies(companies, path=None):
    """يستبدل القسم فقط ويترك بقية الملف (المزودات والمفاتيح…) كما هو."""
    path = path or ini_path()
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    kept, inside = [], False
    for ln in lines:
        s = ln.strip()
        if s.startswith('[') and s.endswith(']'):
            inside = (s[1:-1].strip() == SECTION)
        if not inside:
            kept.append(ln)
    while kept and not kept[-1].strip():
        kept.pop()
    block = [f'[{SECTION}]']
    for name, aliases in companies.items():
        name = name.strip()
        if name:
            block.append(f"{name} = {' | '.join(a.strip() for a in aliases if a.strip())}")
    new = kept + ([''] if kept else []) + block
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(new) + '\n')


def match_company(text, companies=None):
    """اسم الشركة الأساسي إن ورد اسمها أو إحدى صيغها في النص، وإلا None.
    تفضَّل الصيغة الأطول (حتى لا تبتلع «الاتصالات المتنقلة» صيغة «الوطنية للاتصالات المتنقلة»).
    المطابقة على حدود الكلمة، مع السماح ببادئة عربية شائعة (و/ب/ل/ف/ك + ال)."""
    norm = normalize(text)
    if not norm:
        return None
    if companies is None:
        companies = load_companies()
    best, best_len = None, 0
    for name, aliases in companies.items():
        for form in [name] + list(aliases):
            f = normalize(form)
            if len(f) > best_len and re.search(rf'(?<!\w)[وبلفك]?(?:ال)?{re.escape(f)}(?!\w)', norm):
                best, best_len = name, len(f)
    return best


_DIDD = re.compile(r'(?<!\w)ضد(?!\w)')


def split_plaintiff(title):
    """المدعية = الجزء الذي قبل «ضد» في عنوان القضية؛ '' إن لم يتضح الفصل."""
    parts = _DIDD.split(str(title or ''), maxsplit=1)
    return parts[0].strip() if len(parts) == 2 and parts[0].strip() else ''
