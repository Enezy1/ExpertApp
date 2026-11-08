# ===== case_info_window.py — معلومات القضية: مراجعة يدوية + جلب تلقائي صامت =====
"""
فيه مساران منفصلان بهذا الملف، بفلسفتين مختلفتين تمامًا:

1) CaseInfoWindow — شاشة مراجعة كاملة (حقول + أزرار). تُفتح فقط
   بطلب صريح من الخبير (الضغط على قضية بصفحة "القضايا المتداولة").
   تعرض كل البيانات، قابلة للتعديل اليدوي، وفيها زر رفع ملف يدويًا.

2) ensure_case_data — مسار "الزر الواحد" المستخدم وقت
   الطباعة (محضر عادي أو محضر أول جلسة). صفر تفاعل مطلوب من الخبير:
   شاشة انتظار بسيطة (بدون حقول ولا أزرار) تتأكد من القضية، تجلبها
   تلقائيًا لو احتاجت، وتقفل نفسها لوحدها دايمًا — نجحت أو فشلت —
   بدون انتظار أي قرار من المستخدم. أي بيانات ناقصة تبقى فاضية
   بالمحضر النهائي (first_session.py له حقوله الاحتياطية القابلة
   للتعديل، وهذا يكفي كخط دفاع أخير بدون فرض شاشة إضافية).

الجلب والاستخراج (شبكة الوزارة + Gemini) يشتغلون بـthread منفصل عبر
extraction_tasks.py — الواجهة ما تتجمد أبدًا. نافذة التقدم بـprogress_widget.py،
والإشعارات بـtoast_notification.py.
"""
import os
import json as _json
import datetime
import customtkinter as ctk
from tkinter import messagebox, filedialog

import case_db
from pending_cases import get_pending_cases
from documents import get_referral_judgment_for_case, get_referral_judgment_ai_fallback
from ai_providers import has_any_provider
from ui import get_case_type, get_experts
from api import get_requesting_expert, parse_case_info
from extraction_tasks import manager as task_manager, IN_PROGRESS, DONE, ERROR, SKIPPED
from progress_widget import ExtractionProgressWindow
from toast_notification import show_toast

SIDEBAR  = "#1e2535"
SIDEBAR2 = "#252f42"
BG       = "#f5f6fa"
CARD     = "#ffffff"
CARD_BD  = "#e8ecf0"
ACCENT   = "#2ecc71"
ACCENT2  = "#27ae60"
BLUE     = "#3498db"
TEXT_D   = "#1e2535"
TEXT_M   = "#5a6a80"
TEXT_L   = "#94a3b8"
WHITE    = "#ffffff"
FONT     = "Arial"

# رقم المستخدم (الخبير) — نفس الرقم المستخدم بكل روابط نظام الملف الآلي
USER_ID = "309"

EXTRACTION_PROMPT = (
    "اقرأ حكم الإحالة المرفق بعناية، واستخرج المعلومات التالية بصيغة "
    "JSON فقط (بدون أي نص قبله أو بعده، وبدون علامات ```):\n\n"
    "قاعدة عامة مهمة تنطبق على كل الحقول: اكتب أي أرقام دائماً بالأرقام "
    "اللاتينية الإنجليزية (0123456789)، حتى لو كانت مكتوبة بالحكم "
    "بأرقام هندية/عربية (٠١٢٣٤٥٦٧٨٩) — لا تنسخ شكل الأرقام كما يظهر "
    "بالمستند، حوّلها دائماً للأرقام اللاتينية بالناتج.\n\n"
    "{\n"
    '  "رقم_القضية": "...",\n'
    '  "المدعون": ["..."],\n'
    '  "المدعى_عليهم": ["..."],\n'
    '  "تاريخ_الحكم": "DD/MM/YYYY",\n'
    '  "تاريخ_حضور_الخصوم": "DD/MM/YYYY",\n'
    '  "المأمورية": "..."\n'
    "}\n\n"
    "تفاصيل كل حقل:\n\n"
    "- رقم_القضية: يتكون من رقم تسلسلي (عادة 1-5 خانات) وسنة (4 "
    "خانات)، مفصولين بشرطة (/)، يليهما نوع الدعوى ورقم الدائرة، "
    "ويظهر بمتن الحكم بعد عبارة 'في القضية رقم' أو ما يشابهها. "
    "تنبيه أول: لا تخلط بينه وبين أي رقم مكتوب بعنوان 'رقم الدعوى' "
    "بترويسة المستند أعلى الصفحة — ذاك رقم آلي داخلي، ليس المطلوب. "
    "تنبيه ثاني: النص العربي مع الأرقام بمستندات المحاكم قد يُعرض "
    "بترتيب بصري ملتبس (bidi) — لا تنسخ الشكل البصري كما هو. حدد "
    "بنفسك منطقيًا أي الرقمين هو السنة (4 خانات، قيمته بين 2015 "
    "و2030 تقريباً) وأيهما الرقم التسلسلي، واكتبهما دائماً بترتيب: "
    "تسلسلي/سنة (مثال: 3031/2026 تجاري كلي/20). "
    "تنبيه ثالث (قضايا الاستئناف خاصة): أحياناً يكون الحكم جامعاً "
    "لاستئنافين متبادلين بنفس النزاع (كل طرف استأنف على الآخر)، "
    "ويُذكر رقمان للقضية معاً (مثل 'في الاستئنافين المُقيدين برقمي: "
    "628، 964/2025 إداري/3'). بهذي الحالة، اكتب رقم_القضية بالضبط "
    "كما هو مكتوب بالحكم حرفياً بكل الأرقام المذكورة معاً، بدون "
    "اختيار رقم واحد فقط.\n\n"
    "- المدعون: كل من ورد اسمه كـ'مدعي' بالحكم، كل اسم بعنصر منفصل "
    "بالقائمة. قد يكون مدعياً واحداً أو عدة مدعين. تنبيه (قضايا "
    "الاستئناف خاصة): لو الحكم يجمع أكثر من استئناف بنفس الوقت (مثل "
    "'الأول المرفوع من... ضد...' و'الثاني المرفوع من... ضد...')، "
    "اعتمد فقط على الاستئناف الأول المذكور لتحديد المدعي، وتجاهل "
    "الاستئناف الثاني كليّاً حتى لو كانت الأطراف نفسها بترتيب معكوس.\n\n"
    "- المدعى_عليهم: كل من ورد اسمه كـ'مدعى عليه' بالحكم، كل اسم "
    "بعنصر منفصل بالقائمة. قد يكون مدعى عليه واحداً أو عدة أشخاص. "
    "ينطبق هنا نفس تنبيه الاستئناف المذكور أعلى بحقل المدعون: "
    "اعتمد فقط على الاستئناف الأول المذكور.\n\n"
    "- تاريخ_الحكم: تاريخ انعقاد جلسة المحكمة التي صدر فيها هذا "
    "الحكم (يظهر بأول الحكم، مثل 'بالجلسة المنعقدة...بتاريخ...').\n\n"
    "- تاريخ_حضور_الخصوم: التاريخ الذي حددته المحكمة لحضور الخصوم "
    "أمام لجنة الخبراء (يظهر عادة بنهاية الحكم). لو لم يُحدَّد أي "
    "تاريخ بالحكم، اكتب نص فاضي \"\".\n\n"
    "- المأمورية: حكم الإحالة يحتوي على جزئين مختلفين يجب التفريق "
    "بينهم:\n"
    "  1) الصلاحيات العامة الممنوحة للجنة (الاطلاع على الأوراق، سماع "
    "الأقوال، الانتقال، المعاينة، الاطلاع على المستندات) — هذي أدوات "
    "تحت تصرف الخبير لو احتاجها، وليست هي المطلوب منه.\n"
    "  2) المأمورية الفعلية — الأسئلة أو الأمور المحددة التي يجب على "
    "الخبير الإجابة عليها أو تنفيذها بخصوص هذي القضية بالذات (مثل: "
    "بيان طبيعة العلاقة بين الطرفين، تحديد الالتزامات، الانتقال "
    "لمعاينة موقع أو مقر شركة معين، حساب مبلغ، تحديد مسؤولية، إلخ).\n"
    "  استخرج فقط الجزء الثاني (المأمورية الفعلية)، بدون أي ذكر "
    "للصلاحيات العامة بالجزء الأول."
)


def F(s, b=False):
    return (FONT, s, "bold") if b else (FONT, s)


def _parse_ddmmyyyy(s):
    """يحوّل نص DD/MM/YYYY لكائن date فعلي، أو None لو الصيغة غير صالحة"""
    try:
        return datetime.datetime.strptime((s or '').strip(), '%d/%m/%Y').date()
    except Exception:
        return None


def autocorrect_hearing_date(judgment_date_str, hearing_date_str):
    """
    تاريخ حضور الخصوم لا يمكن منطقيًا يكون قبل تاريخ الحكم نفسه (الحكم
    هو اللي يحدد هذا التاريخ). لو طلع قبله، الأغلب خطأ قراءة بالسنة
    (مثل قراءة 2016 بدل 2026) — نحاول نصححه تلقائيًا بدون أي تدخل:
    نستبدل سنة تاريخ الحضور بسنة الحكم، وإن لم يكفِ (الشهر/اليوم لسه
    أسبق)، نجرب السنة التالية لها.

    يرجع (التاريخ_النهائي, تم_التصحيح_تلقائيًا: bool). لو تعذر التصحيح
    كليًا، يرجع ('', False) — نسيبه فاضي بصمت، بدون أي شاشة أو تنبيه.
    """
    jd = _parse_ddmmyyyy(judgment_date_str)
    hd = _parse_ddmmyyyy(hearing_date_str)
    if not hd:
        return hearing_date_str, False
    if not jd or hd >= jd:
        return hearing_date_str, False  # لا يوجد تعارض من الأساس

    for candidate_year in (jd.year, jd.year + 1):
        try:
            candidate = hd.replace(year=candidate_year)
        except ValueError:
            continue
        if candidate >= jd:
            return candidate.strftime('%d/%m/%Y'), True

    return '', False


NO_API_KEY_ERROR = "لا يوجد مفتاح ذكاء اصطناعي متاح — احفظ مفتاح Gemini من صفحة الإعدادات أولاً"


def extract_from_pdf(pdf_path, allow_local=False, force_ai=False, status=None, trim=True):
    """يرفع ملف PDF لـGemini ويرجع (dict_بيانات, None) عند النجاح، أو (None, نص_الخطأ) عند الفشل.

    allow_local: للشاشات التي يراجع فيها الخبير البيانات قبل الحفظ فقط (إضافة قضية). بلا مزود أو عند فشل
    الاتصال تُستخرج البيانات على الجهاز (local_extract) وفيها "_local" و"_warning". الحفظ الصامت (الجلب
    التلقائي) لا يستخدمه: تاريخ خاطئ محفوظ لا يُعاد استخراجه أبداً.
    force_ai: كل صفحات الحكم للذكاء مباشرة (زر «قراءة كاملة بالذكاء»). status(نص): الخطوة الجارية لنافذة التقدم."""
    if not has_any_provider():
        if allow_local:
            data = _extract_locally(pdf_path)
            if data:
                return data, None
        return None, NO_API_KEY_ERROR
    try:
        from gemini_config import generate_from_pdf
        response = generate_from_pdf(EXTRACTION_PROMPT, pdf_path, trim=trim, force_ai=force_ai, status=status,
                                     critical=True)       # حكم الإحالة مستند حاسم: Gemini أولاً بجودة عالية
        clean = response.text.strip().replace("```json", "").replace("```", "").strip()
        data = _json.loads(clean)
        return data, None
    except Exception as e:
        if allow_local:
            data = _extract_locally(pdf_path)
            if data:
                return data, None
        return None, str(e)


def extract_from_judgment(case, pdf_path, force_ai=False, status=None):
    """نافذة «تفاصيل القضية» عمل واجهة مباشر يطلبه الخبير: حصة Lite حتى 500 (لا السقف الناعم للخلفية)."""
    import gemini_quota
    with gemini_quota.mode('ui'):
        return _extract_from_judgment(case, pdf_path, force_ai, status)


def _extract_from_judgment(case, pdf_path, force_ai=False, status=None):
    """«تفاصيل القضية» (2026-10-23): حكم الإحالة كاملاً ← markdown مرة واحدة (Flash Lite) يُحفظ «حكم خبير» في مجلد القضية
    (case_sources.referral_markdown)، ثم الاستخراج من نصه بطلب نصي واحد (مهمة الاستخراج: Gemma ← Lite ← Flash).
    بلا مجلد قضية أو تعذّر التحويل ← المسار القديم على الصور (extract_from_pdf) بكل الصفحات."""
    md = engine = ''
    if case and not force_ai:
        try:
            import case_sources
            if status:
                status('تحويل حكم الإحالة كاملاً إلى نص وحفظه في ملفات القضية')
            md, engine = case_sources.referral_markdown(case, pdf_path)
        except Exception:
            md = ''
    if not md.strip() or not has_any_provider():
        return extract_from_pdf(pdf_path, force_ai=force_ai, status=status, trim=False)
    try:
        import case_research
        import gemini_config as gc
        reply = case_research.default_ask(EXTRACTION_PROMPT + gc.OCR_TEXT_NOTE + md, 'extract', timeout=120)
        clean = (reply or '').strip().replace("```json", "").replace("```", "").strip()
        gc._set_read(engine or 'local', [], True)            # المحرّك الفعلي للنص (إفصاح الخط الأحمر كما هو)
        return _json.loads(clean), None
    except Exception as e:
        try:
            import ai_providers
            if isinstance(e, (ai_providers.PersonalKeyFailure, ai_providers.UserCancelled)):
                raise
        except ImportError:
            pass
        return extract_from_pdf(pdf_path, force_ai=force_ai, status=status, trim=False)


def judgment_engine_json():
    """محرّك آخر قراءة حكم في هذا الخيط كنص JSON للحفظ في case_db.judgment_engine ('' إن لم تُسجَّل)."""
    try:
        from gemini_config import last_read
        info = last_read()
        return _json.dumps(info, ensure_ascii=False) if info else ''
    except Exception:
        return ''


def _extract_locally(pdf_path):
    """أول صفحتين وآخر صفحتين (المتن والمنطوق): طبقة النص إن وجدت، وإلا OCR الداخلي. None عند الفشل."""
    try:
        import fitz
        import local_extract
        import local_ocr
        with fitz.open(pdf_path) as d:
            n = d.page_count
            idx = sorted({i for i in (0, 1, n - 2, n - 1) if 0 <= i < n})
            texts = [d[i].get_text().strip() for i in idx]
        if sum(len(t) for t in texts) >= 200 * len(idx):
            # طبقة النص دقيقة بأي شكل أرقام: لا تنبيه على الأرقام
            text = '\n'.join(local_ocr.to_latin_digits(t) for t in texts)
            return local_extract.extract(text, indic_digits=False)
        res = local_ocr.read_pages(pdf_path, idx)
        return local_extract.extract(res.text, indic_digits=res.indic)
    except Exception:
        return None


def _is_resolved(record):
    """
    يحدد هل القضية 'مكتملة المعالجة' فعليًا — معيار مختلف حسب النوع:
    أصالة تحتاج رقم القضية (من حكم الإحالة)، استعانة تحتاج اسم الخبير
    المستعين (من سجل الحركة، ما يحتاج أي حكم إحالة من الأساس).
    """
    if not record:
        return False
    if record.get('case_type') == 'استعانة':
        return bool(record.get('requesting_expert_name'))
    return bool(record.get('court_case_number'))


def _no_progress(*_a, **_k):
    pass


def _has_case_number(data):
    return bool(data) and bool((data.get('رقم_القضية') or '').strip())


def _get_judgment_data(cookies, autocase_no, save_path, p, force_ai=False, case=None):
    """
    جلب حكم الإحالة + استخراجه، مشترك بين الأصالة والاستعانة. يدير
    المرحلتين 0 (الجلب) و1 (القراءة بالذكاء الاصطناعي) بنافذة التقدم.

    1) المسار السريع: الملف المحلي لو موجود وسليم، وإلا find_most_recent_judgment
       (اختيار برمجي بدون AI) — للقضايا العادية البسيطة.
    2) المسار الاحتياطي (فقط عند الفشل): لو ما انلقى مرشح، أو انقرأ
       المستند المختار بنجاح بس بدون رقم قضية (يعني المستند نفسه غلط،
       مو خطأ شبكة/مفتاح) — Gemini يختار من أسماء كل المستندات، ونحمّل
       المستند المختار وحده.

    يرجع (data, error, found): found=False يعني ما فيه حكم إحالة حتى
    بعد المسار الاحتياطي. أي error من extract_from_pdf (مفتاح/شبكة/Gemini)
    يرجع مباشرة بدون مسار احتياطي — نفس السلوك السابق.
    """
    sections = {}

    def say(text):   # الخطوة الفعلية الجارية (OCR داخلي/OCR.space/أي مزود) تحت مرحلة القراءة
        p(1, IN_PROGRESS, text)

    try:
        judgment, path = get_referral_judgment_for_case(
            cookies, autocase_no, USER_ID, save_path, sections_out=sections)
    except Exception:
        return None, None, False

    data = None
    tried_doc_id = None
    if judgment and path:
        p(0, DONE, "استُخدم ملف الحكم المحفوظ مسبقًا بسطح المكتب" if judgment.get('local') else "")
        p(1, IN_PROGRESS)
        data, error = extract_from_judgment(case, path, force_ai=force_ai, status=say)
        if error:
            p(1, ERROR, error)
            return None, error, True
        if _has_case_number(data):
            p(1, DONE)
            return data, None, True
        tried_doc_id = judgment.get('doc_id') or None
        p(1, IN_PROGRESS, "المستند المختار ليس حكم الإحالة غالبًا — البحث بين كل المستندات...")
    else:
        p(0, IN_PROGRESS, "البحث عن حكم الإحالة بين كل المستندات بالذكاء الاصطناعي...")

    try:
        row, path2 = get_referral_judgment_ai_fallback(
            cookies, autocase_no, USER_ID, save_path,
            sections=sections or None, exclude_doc_id=tried_doc_id)
    except Exception:
        row, path2 = None, None

    if not row:
        if data is not None:
            # المسار الاحتياطي ما لقى شي — نرجع نتيجة المستند الأول كما كانت
            p(1, DONE)
            return data, None, True
        p(0, DONE, "لا يوجد حكم إحالة بالنظام بعد")
        return None, None, False

    if data is None:
        p(0, DONE, f"اختار الذكاء الاصطناعي: {row.get('doc_type', '')}")
        p(1, IN_PROGRESS)
    data2, error2 = extract_from_judgment(case, path2, force_ai=force_ai, status=say)
    if error2:
        if data is not None:
            p(1, DONE)
            return data, None, True
        p(1, ERROR, error2)
        return None, error2, True
    p(1, DONE)
    if data is None or _has_case_number(data2):
        return data2, None, True
    return data, None, True


def _fetch_and_extract(cookies, current_user, case, save_dir, progress=None, force_ai=False):
    """
    منطق الجلب والاستخراج المشترك بين الشاشتين (مراجعة يدوية / انتظار
    صامت). يرجع (dict_جاهز_للحفظ, نص_خطأ_أو_None). الـdict دايمًا فيه
    على الأقل الحقول الأساسية (autocase_no/expert_name/title/received_date)،
    وفيه كذلك حقول الحكم (court_case_number/judgment_date/...) فقط لو
    نجح الجلب والاستخراج فعليًا.

    progress(اختياري): callback(رقم_المرحلة, الحالة, ملاحظة) — يُمرَّر من
    extraction_tasks عند التشغيل بـthread. لا يلمس الواجهة أبدًا (يحط
    رسالة بـqueue فقط)، ويرمي Cancelled لو المستخدم ألغى العملية.
    بدون تمريره (مثل نسخ Qt) السلوك مطابق تمامًا للسابق.
    """
    p = progress or _no_progress
    p(0, IN_PROGRESS)
    caso_no = case['caso_no'].strip().upper()
    base = {
        'autocase_no': case.get('autocase_no', ''),
        'expert_name': current_user,
        'title': case.get('title', ''),
        'received_date': case.get('received_date', ''),
    }

    # الكشف التلقائي عن نوع القضية أول شي — لقضايا الاستعانة، حكم
    # الإحالة غير ذي علاقة أصلاً (المعلومة المهمة هي طلب الاستعانة،
    # وهو حاليًا غير آلي بالنظام)، فنتخطى جلب/قراءة الحكم بالكامل
    # ونسجّل بس المعلومات اللي نقدر نجيبها تلقائيًا (اسم ونوع الخبير
    # المستعين). نص المأمورية يبقى للإدخال اليدوي حاليًا.
    case_type = get_case_type(cookies, caso_no, current_user) or 'أصالة'
    base['case_type'] = case_type

    # الكشف التلقائي عن لجنة/فردي — نفس منطق get_experts (clustering)
    # الموجود بـui.py، بدون أي جلب إضافي (نفس مصدر البيانات
    # ECS_CASE_FLOW). لو أكثر من عضو واحد بآخر كتلة تخص المستخدم
    # الحالي، تُعتبر لجنة وتُسجَّل أسماء الأعضاء.
    try:
        experts = get_experts(caso_no, cookies, current_user)
        base['is_committee'] = '1' if len(experts) > 1 else '0'
        base['committee_members'] = [e['name'] for e in experts] if len(experts) > 1 else []
    except Exception:
        pass

    if case_type == 'استعانة':
        requester = get_requesting_expert(cookies, caso_no)
        base['requesting_expert_name'] = requester.get('name', '')
        base['requesting_expert_type'] = requester.get('type', '')

        # نجيب autocase_no عشان نقدر نوصل لملف الحكم
        autocase_no = case.get('autocase_no', '')
        if not autocase_no:
            try:
                pending = get_pending_cases(cookies)
                match = next((c for c in pending if c['caso_no'].strip().upper() == caso_no), None)
                if match:
                    autocase_no = match['autocase_no']
                    base['autocase_no'] = autocase_no
                    base['title'] = base['title'] or match.get('title', '')
                    base['received_date'] = base['received_date'] or match.get('received_date', '')
            except Exception:
                pass

        # نجيب حكم الإحالة بالذكاء لأخذ المدعي + المدعى عليه + رقم الدعوى
        # (نفس مسار الأصالة تمامًا، بدون تاريخ الحكم ولا تاريخ حضور الخصوم)
        if autocase_no:
            try:
                save_dir = os.path.join(os.path.expanduser("~"), "Desktop", "judgments")
                os.makedirs(save_dir, exist_ok=True)
                save_path = os.path.join(save_dir, f"{caso_no}.pdf")
                data, error, found = _get_judgment_data(cookies, autocase_no, save_path, p, force_ai, case)
                if found:
                    if not error and data:
                        p(2, IN_PROGRESS)
                        base['court_case_number'] = data.get('رقم_القضية', '')
                        base['judgment_engine'] = judgment_engine_json()
                        p(2, DONE)
                        p(3, IN_PROGRESS)
                        base['plaintiffs'] = data.get('المدعون', [])
                        base['defendants'] = data.get('المدعى_عليهم', [])
                        p(3, DONE)
            except Exception:
                pass
        p(0, DONE)

        # احتياطي: parse_case_info لو ما ضبط الذكاء أو ما وجد الملف
        if not base.get('court_case_number'):
            try:
                info = parse_case_info(caso_no, cookies, current_user)
                base['court_case_number'] = info.get('case_num', '')
                if not base.get('plaintiffs'):
                    base['plaintiffs'] = info.get('plaintiffs', [])
                if not base.get('defendants'):
                    base['defendants'] = info.get('defendants', [])
            except Exception:
                pass

        return base, None

    autocase_no = case.get('autocase_no', '')
    if not autocase_no:
        try:
            pending = get_pending_cases(cookies)
            match = next((c for c in pending if c['caso_no'].strip().upper() == caso_no), None)
            if match:
                autocase_no = match['autocase_no']
                base['autocase_no'] = autocase_no
                base['title'] = base['title'] or match.get('title', '')
                base['received_date'] = base['received_date'] or match.get('received_date', '')
        except Exception:
            pass

    if not autocase_no:
        p(0, DONE, "لا يوجد ملف آلي مرتبط بالقضية")
        return base, None

    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f"{caso_no}.pdf")

    # المسار السريع (ملف محلي / اختيار برمجي) + الاحتياطي بالذكاء
    # الاصطناعي عند الفشل فقط — انظر _get_judgment_data
    data, error, found = _get_judgment_data(cookies, autocase_no, save_path, p, force_ai, case)
    if not found:
        return base, None
    if error:
        return base, error

    p(2, IN_PROGRESS)
    judgment_date = data.get('تاريخ_الحكم', '')
    hearing_date = data.get('تاريخ_حضور_الخصوم', '')
    hearing_date, corrected = autocorrect_hearing_date(judgment_date, hearing_date)

    base.update({
        'judgment_engine': judgment_engine_json(),
        'court_case_number': data.get('رقم_القضية', ''),
        'judgment_date': judgment_date,
        'hearing_date': hearing_date,
        'mission_text': data.get('المأمورية', ''),
    })
    p(2, DONE, "تم تصحيح تاريخ حضور الخصوم تلقائيًا" if corrected else "")

    p(3, IN_PROGRESS)
    base.update({
        'plaintiffs': data.get('المدعون', []),
        'defendants': data.get('المدعى_عليهم', []),
    })
    p(3, DONE)
    return base, None


# ============================================================
# 1) شاشة المراجعة اليدوية الكاملة — طلب صريح من الخبير فقط
# ============================================================

class CaseInfoWindow(ctk.CTkToplevel):
    """case: dict فيه على الأقل caso_no، وبالعادة title/received_date/autocase_no من قائمة المتداولة"""

    def __init__(self, parent, cookies, current_user, case, initial_status=None):
        super().__init__(parent)
        self.cookies = cookies
        self.current_user = current_user
        self.case = case
        self.caso_no = case['caso_no'].strip().upper()
        self._last_status = "⏳ جاري التحميل..."

        self.title(f"معلومات القضية — {self.caso_no}")
        self.geometry("600x780")
        self.configure(fg_color=BG)
        self.grab_set()

        self._build_header()
        if initial_status:
            # جاية من عملية استخراج خلصت (بنافذة التقدم أو بالخلفية) — نعرض النتيجة مباشرة
            self._last_status = initial_status
            self.after(50, self._render_form)
        else:
            self.after(150, self._load_or_fetch)

    def _build_header(self):
        top = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0, height=56)
        top.pack(fill='x'); top.pack_propagate(False)
        ctk.CTkButton(top, text="✕", width=32, height=32,
            fg_color="transparent", hover_color=SIDEBAR2,
            text_color=TEXT_L, command=self.destroy
        ).place(relx=0.03, rely=0.5, anchor='w')
        ctk.CTkLabel(top, text=f"معلومات القضية — {self.caso_no}",
            font=F(15, True), text_color=WHITE
        ).place(relx=0.97, rely=0.5, anchor='e')

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill='both', expand=True, padx=20, pady=15)

        self.status_lbl = ctk.CTkLabel(self.body, text=self._last_status,
            font=F(12, True), text_color=TEXT_M, justify='right')
        self.status_lbl.pack(anchor='e', pady=(0, 10))

    def _field(self, label_text, multiline=False, height=70):
        ctk.CTkLabel(self.body, text=label_text, font=F(12, True),
            text_color=TEXT_D).pack(anchor='e', pady=(12, 3))
        if multiline:
            widget = ctk.CTkTextbox(self.body, font=F(12), height=height,
                fg_color=WHITE, border_color=CARD_BD, border_width=1,
                text_color=TEXT_D, wrap='word')
        else:
            widget = ctk.CTkEntry(self.body, font=F(13), fg_color=WHITE,
                border_color=CARD_BD, text_color=TEXT_D, justify='right')
        widget.pack(fill='x')
        return widget

    def _render_form(self):
        for w in self.body.winfo_children():
            w.destroy()

        info = ctk.CTkFrame(self.body, fg_color=CARD, corner_radius=10,
            border_width=1, border_color=CARD_BD)
        info.pack(fill='x', pady=(0, 6))
        ctk.CTkLabel(info, text=f"{self.caso_no}  ·  {self.case.get('title', '')[:40]}",
            font=F(13, True), text_color=TEXT_D).pack(anchor='e', padx=14, pady=(10, 2))
        ctk.CTkLabel(info, text=f"تاريخ المباشرة: {self.case.get('received_date', '')}",
            font=F(11), text_color=TEXT_L).pack(anchor='e', padx=14, pady=(0, 10))

        self.status_lbl = ctk.CTkLabel(self.body, text=self._last_status,
            font=F(12, True), text_color=TEXT_M, justify='right')
        self.status_lbl.pack(anchor='e', pady=(8, 0))

        self.court_no_entry = self._field("رقم القضية بالمحكمة")
        self.judgment_date_entry = self._field("تاريخ صدور الحكم (DD/MM/YYYY)")
        self.hearing_date_entry = self._field("التاريخ المحدد لحضور الخصوم (DD/MM/YYYY)")
        self.plaintiffs_box = self._field("المدعي / المدعون (كل اسم بسطر)", multiline=True, height=60)
        self.defendants_box = self._field("المدعى عليهم (كل اسم بسطر)", multiline=True, height=60)
        self.mission_box = self._field("المأمورية", multiline=True, height=120)

        data = case_db.get_case(self.caso_no)
        if data:
            self.court_no_entry.insert(0, data.get('court_case_number') or '')
            self.judgment_date_entry.insert(0, data.get('judgment_date') or '')
            self.hearing_date_entry.insert(0, data.get('hearing_date') or '')
            self.plaintiffs_box.insert('1.0', '\n'.join(data.get('plaintiffs') or []))
            self.defendants_box.insert('1.0', '\n'.join(data.get('defendants') or []))
            self.mission_box.insert('1.0', data.get('mission_text') or '')

        btn_row = ctk.CTkFrame(self.body, fg_color="transparent")
        btn_row.pack(fill='x', pady=(18, 5))
        ctk.CTkButton(btn_row, text="🔄 إعادة المحاولة", font=F(12, True),
            fg_color="#9b59b6", hover_color="#8e44ad", text_color=WHITE,
            height=38, command=self._retry_fetch
        ).pack(side='left')
        ctk.CTkButton(btn_row, text="📎 رفع حكم إحالة يدويًا", font=F(12, True),
            fg_color=BLUE, hover_color="#2980b9", text_color=WHITE,
            height=38, command=self._upload_manual
        ).pack(side='left', padx=(8, 0))
        ctk.CTkButton(btn_row, text="💾 حفظ", font=F(12, True),
            fg_color=ACCENT, hover_color=ACCENT2, text_color=WHITE,
            height=38, width=100, command=self._save
        ).pack(side='right')

    def _load_or_fetch(self):
        """
        يُستدعى مرة عند فتح الشاشة فقط (وقت البناء). يتخطى الجلب من
        الذكاء الاصطناعي (تكلفة API) لو القضية 'محلولة' أصلاً بالقاعدة
        — الزر '🔄 إعادة المحاولة' منفصل تمامًا (_retry_fetch) ودايمًا
        يعيد الجلب والاستخراج بغض النظر عن حالة القاعدة.
        """
        existing = case_db.get_case(self.caso_no)
        if _is_resolved(existing):
            self._last_status = "✅ القضية موجودة بالقاعدة"
            self._render_form()
            return
        self._fetch_and_render("⏳ جاري البحث عن حكم الإحالة بالنظام...")

    def _retry_fetch(self):
        """
        زر 'إعادة المحاولة' — كان قبل التصحيح لا يفعل شيئًا لو أي سجل
        موجود بالقاعدة أصلاً (حتى لو ناقص/غير مكتمل)، لأن الفحص القديم
        كان 'existing' بس بدون التحقق من _is_resolved. الآن يعيد سحب
        حكم الإحالة وإرساله للذكاء الاصطناعي من جديد دائمًا — يلتقط أي
        إضافة أو تعديل صار على الحكم لاحقًا (مثلاً حكم عُدِّل أو صدر
        متأخرًا بعد أول محاولة فاشلة). save_case يدمج النتيجة الجديدة
        مع المخزّن بدون فقدان أي حقل سابق لو رجع الاستخراج الجديد فاضيًا
        بأحد الحقول.
        """
        self._fetch_and_render("⏳ جاري إعادة المحاولة (سحب الحكم من جديد)...")

    def _fetch_and_render(self, loading_status):
        """
        الجلب صار بـthread منفصل — الواجهة ما تتجمد. نافذة التقدم تعرض
        المراحل، والنتيجة توصل لـ_on_task_done بالـmain thread. لو الخبير
        صغّر نافذة التقدم وهذي الشاشة لسه مفتوحة، تتحدث تلقائيًا أول ما
        تخلص العملية (وفوقها Toast).
        """
        try:
            self.status_lbl.configure(text=loading_status)
        except Exception:
            pass
        task = start_fetch_task(self, self.cookies, self.current_user, self.case)
        if self._on_task_done not in task.listeners:
            task.listeners.append(self._on_task_done)
        show_progress_window(self, task, allow_minimize=True)

    def _on_task_done(self, task):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._last_status = task.summary
        self._render_form()

    def _upload_manual(self):
        path = filedialog.askopenfilename(
            title="اختر ملف حكم الإحالة (PDF)",
            filetypes=[("PDF files", "*.pdf")]
        )
        if not path:
            return
        import case_folder
        case_folder.adopt_manual_judgment(self.case, path)      # مجلد القضية هو الأصل: يُنسخ قبل القراءة
        try:
            self.status_lbl.configure(text="⏳ جاري قراءة الملف المرفوع بالذكاء الاصطناعي...")
        except Exception:
            pass

        def worker(progress):
            progress(0, SKIPPED, "ملف مرفوع يدويًا — لا حاجة للسحب من الملف الآلي")
            progress(1, IN_PROGRESS)
            data, error = extract_from_pdf(path)
            progress(1, ERROR if error else DONE, error or "")
            if error:
                return None, error
            progress(2, IN_PROGRESS)
            judgment_date = data.get('تاريخ_الحكم', '')
            hearing_date = data.get('تاريخ_حضور_الخصوم', '')
            hearing_date, _ = autocorrect_hearing_date(judgment_date, hearing_date)
            fields = dict(
                autocase_no=self.case.get('autocase_no', ''),
                expert_name=self.current_user,
                title=self.case.get('title', ''),
                received_date=self.case.get('received_date', ''),
                court_case_number=data.get('رقم_القضية', ''),
                judgment_date=judgment_date,
                hearing_date=hearing_date,
                mission_text=data.get('المأمورية', ''),
            )
            progress(2, DONE)
            progress(3, IN_PROGRESS)
            fields['plaintiffs'] = data.get('المدعون', [])
            fields['defendants'] = data.get('المدعى_عليهم', [])
            progress(3, DONE)
            return fields, None

        def finalize(task):
            # بالـmain thread — نفس منطق الحفظ السابق بالضبط
            if task.error:
                task.summary = f"❌ فشل الاستخراج بالذكاء الاصطناعي: {task.error}"
                task.success = False
                return
            case_db.save_case(self.caso_no, **task.result)
            task.summary = "✅ تم الاستخراج من الملف المرفوع بنجاح"
            task.success = True

        root = self._root()
        task, is_new = task_manager().start(self, ('upload', self.caso_no), self.caso_no,
                                            worker, finalize)
        if is_new:
            task.toast_factory = lambda t: _toast_for_task(root, self.cookies, self.current_user, self.case, t)
        if self._on_task_done not in task.listeners:
            task.listeners.append(self._on_task_done)
        show_progress_window(self, task, allow_minimize=True)

    def _save(self):
        plaintiffs = [p.strip() for p in self.plaintiffs_box.get('1.0', 'end').split('\n') if p.strip()]
        defendants = [d.strip() for d in self.defendants_box.get('1.0', 'end').split('\n') if d.strip()]
        case_db.save_case(self.caso_no,
            autocase_no=self.case.get('autocase_no', ''),
            expert_name=self.current_user,
            title=self.case.get('title', ''),
            received_date=self.case.get('received_date', ''),
            court_case_number=self.court_no_entry.get().strip(),
            judgment_date=self.judgment_date_entry.get().strip(),
            hearing_date=self.hearing_date_entry.get().strip(),
            plaintiffs=plaintiffs,
            defendants=defendants,
            mission_text=self.mission_box.get('1.0', 'end').strip(),
        )
        messagebox.showinfo("✅ تم", "تم حفظ بيانات القضية بنجاح")


# ============================================================
# عمليات الاستخراج بالخلفية (threading) — مشتركة بين المسارين
# ============================================================

def _judgments_dir():
    return os.path.join(os.path.expanduser("~"), "Desktop", "judgments")


def _finalize_fetch(task):
    """
    يشتغل بالـmain thread بعد ما يخلص الـworker. نفس منطق الحفظ والرسائل
    السابق حرفيًا — بس انتقل من داخل _fetch_and_render/_WaitOverlay لهنا.
    """
    result, error = task.result, task.error

    if error == NO_API_KEY_ERROR:
        # نفس المنطق بالضبط — لا نسجّل شي بالقاعدة، عشان المحاولة
        # الجاية (بعد ربط المفتاح) تعيد المحاولة من الصفر
        task.summary = (
            "⚠️ لا يوجد ربط بالذكاء الاصطناعي — اربط المفتاح من صفحة "
            "الإعدادات، ثم اضغط '🔄 إعادة المحاولة' بالأسفل"
        )
        task.success = False
        return

    if result is None:
        # استثناء غير متوقع داخل الـthread نفسه — ما فيه شي نحفظه
        task.summary = f"❌ فشل الاستخراج: {error}"
        task.success = False
        return

    if error:
        task.summary = f"❌ فشل الاستخراج بالذكاء الاصطناعي: {error}"
    elif not _is_resolved(result):
        if result.get('case_type') == 'استعانة':
            task.summary = "⚠️ تعذر تحديد الخبير المستعين تلقائيًا — أدخل البيانات يدويًا"
        else:
            task.summary = (
                "⚠️ لا يوجد حكم إحالة بالنظام بعد — أدخل البيانات يدويًا، "
                "أو ارفع الملف لو عندك نسخة"
            )
    else:
        task.summary = "✅ تم الاستخراج/التحديث بنجاح"

    task.success = _is_resolved(result) and not error
    case_db.save_case(task.caso_no, **result)


def _toast_for_task(parent, cookies, current_user, case, task):
    """Toast للمهام اللي خلصت وهي مصغّرة — مع زر يفتح شاشة القضية مباشرة"""
    root = parent.winfo_toplevel()._root() if parent.winfo_exists() else None
    if root is None:
        return

    def _open():
        CaseInfoWindow(root, cookies, current_user, case, initial_status=task.summary)

    if task.success:
        show_toast(root, "اكتمل الاستخراج",
                   f"تم استخراج بيانات القضية ‏{task.caso_no}‏ بنجاح",
                   kind="success", action_text="فتح القضية", action=_open)
    else:
        kind = "error" if (task.summary or "").startswith("❌") else "warning"
        show_toast(root, f"القضية {task.caso_no}", task.summary or "انتهت العملية",
                   kind=kind, action_text="فتح القضية", action=_open, duration_ms=9000)


def start_fetch_task(parent, cookies, current_user, case):
    """
    يبدأ (أو يرجع الشغالة أصلاً لنفس القضية) عملية سحب + استخراج
    بـthread منفصل. أكثر من قضية تشتغل بنفس الوقت، كل وحدة بمهمتها.
    """
    caso_no = case['caso_no'].strip().upper()
    save_dir = _judgments_dir()

    def worker(progress):
        # بالـworker thread — شبكة + Gemini فقط، صفر لمس للواجهة أو للقاعدة
        return _fetch_and_extract(cookies, current_user, case, save_dir, progress)

    task, is_new = task_manager().start(parent, ('fetch', caso_no), caso_no,
                                        worker, _finalize_fetch)
    if is_new:
        root = parent.winfo_toplevel()._root()
        task.toast_factory = lambda t: _toast_for_task(root, cookies, current_user, case, t)
    return task


def show_progress_window(parent, task, allow_minimize=True):
    """يعرض نافذة التقدم لمهمة (جديدة أو شغالة بالخلفية من قبل)"""
    old = task.window
    if old is not None:
        try:
            if old.winfo_exists() and old.allow_minimize == allow_minimize:
                old.lift()
                old.focus_force()
                return old
            old._close()
        except Exception:
            pass
    return ExtractionProgressWindow(parent, task, allow_minimize=allow_minimize)


def open_case_info_window(parent, cookies, current_user, case):
    """
    لو القضية محلولة بالقاعدة: تنفتح الشاشة فورًا. غير كذا: تبدأ عملية
    الاستخراج بالخلفية مع نافذة التقدم، والشاشة تنفتح تلقائيًا بعد ما
    تخلص — إلا لو الخبير صغّر النافذة، فيطلع Toast بزر "فتح القضية".
    """
    caso_no = case['caso_no'].strip().upper()
    if _is_resolved(case_db.get_case(caso_no)):
        CaseInfoWindow(parent, cookies, current_user, case,
                       initial_status="✅ القضية موجودة بالقاعدة")
        return

    task = start_fetch_task(parent, cookies, current_user, case)

    def _open_when_done(t):
        if not t.minimized:
            CaseInfoWindow(parent, cookies, current_user, case, initial_status=t.summary)
        try:
            t.listeners.remove(_open_when_done)
        except ValueError:
            pass

    # مهمة شغالة أصلاً لنفس القضية (كانت مصغّرة) — ما نكرر مستمع الفتح
    if not any(getattr(cb, '_opens_case_window', False) for cb in task.listeners):
        _open_when_done._opens_case_window = True
        task.listeners.append(_open_when_done)
    show_progress_window(parent, task, allow_minimize=True)


# ============================================================
# 2) مسار "الزر الواحد" — انتظار وقت الطباعة، صفر تفاعل
# ============================================================

def ensure_case_data(parent, cookies, current_user, case):
    """
    يتأكد من توفر بيانات القضية، ويحاول جلبها تلقائيًا لو ما زالت غير
    مكتملة (بدون أي تكلفة AI لو سبق نجح الاستخراج من قبل — فحص القاعدة
    مجاني). تُستخدم من مسارات الطباعة (محضر عادي / محضر أول جلسة).

    الجلب نفسه صار بـthread (الواجهة ما تتجمد)، ونافذة التقدم تقفل نفسها
    تلقائيًا أول ما يخلص. بدون زر تصغير هنا — المستدعي يحتاج النتيجة
    فورًا للطباعة. زر "إلغاء" يرجّع البيانات المتوفرة بالقاعدة حاليًا.

    استدعاء حاجب من ناحية المستدعي (wait_window يخلي حلقة أحداث tkinter
    شغالة، فالبرنامج ما يعلّق) — يرجع dict ببيانات القضية النهائية.
    """
    caso_no = case['caso_no'].strip().upper()
    existing = case_db.get_case(caso_no)
    if _is_resolved(existing):
        return existing

    task = start_fetch_task(parent, cookies, current_user, case)
    window = show_progress_window(parent, task, allow_minimize=False)
    parent.wait_window(window)

    if task.state == "finished" and task.error == NO_API_KEY_ERROR:
        # الجلب نفسه نجح (حكم الإحالة موجود فعليًا)، بس ما فيه مفتاح
        # نقرأه بيه — ما انحفظ شي بالقاعدة (نفس السلوك السابق)
        messagebox.showwarning(
            "⚠️ لا يوجد ربط بالذكاء الاصطناعي",
            "لم تُستخرج بيانات حكم الإحالة لأنه لا يوجد مفتاح Gemini "
            "محفوظ بصفحة الإعدادات.\n\n"
            "سيُفتح المحضر بالمعلومات المتوفرة فقط. اربط المفتاح من "
            "صفحة الإعدادات، وأعد المحاولة لاستخراج البيانات تلقائيًا."
        )
    return case_db.get_case(caso_no) or {}
