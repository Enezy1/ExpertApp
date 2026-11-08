# ===== summarizer.py — ملخص القضية بسطر واحد من صحيفة الدعوى (Gemini) =====
import re

from ai_providers import has_any_provider

NO_API_KEY_ERROR = "لا يوجد مفتاح ذكاء اصطناعي متاح — احفظ مفتاح Gemini من صفحة الإعدادات أولاً"
LOCAL_MARK = "(ملخص محلي) "

SUMMARY_PROMPT = (
    "اقرأ صحيفة الدعوى المرفقة، واكتب جملة واحدة واضحة بالعربي (حتى 25 "
    "كلمة تقريباً) توضّح: نوع القضية (تعاقدية، تعويض، إيجارية، تجارية...) "
    "ثم من يطالب بماذا وعلى أي أساس. اذكر الأطراف بصفاتهم فقط (مقاول "
    "الباطن، المقاول الرئيسي، المورّد، المؤجر، المالك، الشركة...) وليس "
    "بأسمائهم، ولا تذكر أرقام قضايا ولا أي مقدمة.\n"
    "أمثلة على الصيغة المطلوبة:\n"
    "\"قضية تعاقدية — مقاول الباطن يطالب بقيمة الأجهزة المورَّدة\"\n"
    "\"قضية إيجارية — المؤجر يطالب بالأجرة المتأخرة وإخلاء العين المؤجرة\"\n"
    "\"قضية تعويض — المدعي يطالب بتعويض عن أضرار حادث مروري\"\n"
    "أعد نص الجملة فقط، نص عادي مباشر بدون JSON وبدون علامات تنسيق "
    "وبدون علامات تنصيص. اكتب أي أرقام بالأرقام اللاتينية."
)


def summarize_claim_pdf(pdf_path):
    """يرسل صحيفة الدعوى للذكاء (نص OCR الداخلي إن كان مقروءاً، وإلا المسار المعتاد) ويرجع
    (ملخص_نصي, None) أو (None, نص_الخطأ). بلا أي مزود أو اتصال: ملخص محلي من طلبات الصحيفة."""
    if not has_any_provider():
        return _local_summary(pdf_path, NO_API_KEY_ERROR)
    try:
        from gemini_config import generate_from_pdf
        response = generate_from_pdf(SUMMARY_PROMPT, pdf_path, pages=(1, 2), purpose='summary', task='summarize')
        text = (response.text or '').strip().strip('"«»').strip()
        text = ' '.join(text.split())  # سطر واحد دائماً
        if not text:
            return None, "رد فاضي من Gemini"
        return text, None
    except Exception as e:
        return _local_summary(pdf_path, str(e))


# الطلبات في آخر الصحيفة: "ليسمعا الحكم بإلزام …" أو "الحكم له بـ …"
_ASK = re.compile(r'(?:ليسمع\w*\s+)?(?:الحكم|يحكم|القضاء)\s+(?:له|لها|لهم\s+)?(?:بإلزام|بالزام|بفسخ|بإخلاء|بإبطال|بتعويض|'
                  r'بأحقية|باحقية|بندب|بصحة|ببطلان|برد|بأداء|بادا|بالتعويض|بإلغاء|بالغاء)')


_HEAR = re.compile(r'(?:سماع\w*|ليسمع\w*)\s+الحكم')


def _local_summary(pdf_path, error):
    """بدون ذكاء: أول طلب في الصحيفة ("الحكم بإلزام …") بحد 25 كلمة، معلَّماً أنه محلي. لا شيء ⇒ الخطأ الأصلي."""
    try:
        import fitz
        import local_ocr
        with fitz.open(pdf_path) as d:
            idx = sorted({i for i in (1, 2, d.page_count - 1) if 0 <= i < d.page_count})
            text = ' '.join(d[i].get_text() for i in idx).strip()
        if len(text) < 100:
            text = ' '.join(p.text for p in local_ocr.read_pages(pdf_path, idx).pages)
        flat = ' '.join(local_ocr.to_latin_digits(text).split())
        m = _HEAR.search(flat) or _ASK.search(flat)
        if not m:
            return None, error
        # شوائب القراءة (": Q") لا تدخل الملخص
        words = [w for w in flat[m.end() if m.re is _HEAR else m.start():].split()
                 if local_ocr.noise_ratio(w) == 0 and w not in (':', 'عليه', 'عليهم', 'عليها')][:25]
        while words and not re.search('[ء-ي]', words[0]):
            words.pop(0)   # رقم أو رمز شارد قبل الطلب
        if len(words) < 4:
            return None, error
        return LOCAL_MARK + ' '.join(words).rstrip('،,.:') + ' …', None
    except Exception:
        return None, error
