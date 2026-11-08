# ===== documents.py — جلب مستندات القضية (حكم الإحالة) من نظام الملف الآلي =====
import os
import requests
import re
import datetime
from config import BASE_URL

# IP السيرفر الداخلي لخدمة الملف الآلي — ثابت بغض النظر عن جهاز المستخدم
DOC_SERVER_IP = "10.100.105.6"

# ترتيب البحث المتفق عليه: نتوقف عند أول مرحلة فيها مستندات
SEARCH_ORDER = [
    "محكمة التمييز",
    "محكمة الاستئناف",
    "المحكمة الكلية",
]

# الأقسام التي لا نبحث فيها أبداً (مرجعية فقط، لا تُستخدم في الكود لكن للتوضيح)
IGNORED_SECTIONS = [
    "الادارة العامة للتنفيذ",
    "الادارة العامة للخبراء",
]


def build_doc_link(autocase_no, user_id):
    """
    يبني رابط ShowImg.php لقضية معينة عبر رقمها الآلي (autocase_no) ورقم المستخدم.
    البنية: id=12&app=EXPERT&usr={user_id}&ip={IP}&dt={timestamp}&AutocaseNo={autocase_no}&hx=1
    تُحوَّل إلى Hex ثم تُمرَّر كـ DocId.
    """
    dt = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    plain = f'id=12&app=EXPERT&usr={user_id}&ip={DOC_SERVER_IP}&dt={dt}&AutocaseNo={autocase_no}&hx=1'
    hex_str = plain.encode().hex()
    return f'{BASE_URL}/ShowImg.php?DocId={hex_str}'


def get_documents_page(cookies, autocase_no, user_id):
    """يجلب صفحة المستندات الكاملة (كل الأقسام) لقضية معينة"""
    url = build_doc_link(autocase_no, user_id)
    r = requests.get(url, cookies=cookies, verify=False)
    return r.text


def parse_sections(html):
    """
    يقسّم صفحة المستندات إلى أقسام (محكمة الاستئناف / المحكمة الكلية / محكمة التمييز / ...)
    يرجع dict: {اسم_القسم: [قائمة صفوف المستندات]}
    كل صف هو dict: {'doc_id', 'case_no', 'doc_type', 'doc_date', 'entry_date'}
    """
    sections = {}

    # كل قسم محصور بين <i class="fa fa-cogs"></i> اسم_القسم ... حتى القسم التالي
    portlet_pattern = re.compile(
        r'<i class="fa fa-cogs"></i>\s*([^<]+?)</div>.*?(?=<i class="fa fa-cogs"></i>|<div class="modal"|\Z)',
        re.DOTALL
    )

    # DocId بصيغة GUID — يقبل الصيغة القديمة id={XXXXXXXX-...} والجديدة
    # (منذ أكتوبر 2026) DocId=%7BXXXXXXXX-...%7D داخل <a href> مع أسطر/مسافات بين الخلايا
    # الأعمدة الخمسة بعده: رقم القضية، نوع المستند، تاريخ المستند، تاريخ الإدخال
    row_pattern = re.compile(
        r'(?:DocId|id)=(?:%7B|\{)([0-9A-Fa-f-]+)(?:%7D|\})[^>]*>.*?</button>\s*</td>'
        r'\s*<td>([^<]*)</td>'
        r'\s*<td>([^<]*)</td>'
        r'\s*<td>([^<]*)</td>'
        r'\s*<td>([^<]*)</td>',
        re.DOTALL | re.IGNORECASE
    )

    for match in portlet_pattern.finditer(html):
        section_name = match.group(1).strip()
        section_html = match.group(0)

        rows = []
        for rm in row_pattern.finditer(section_html):
            doc_id, case_no, doc_type, doc_date, entry_date = rm.groups()
            rows.append({
                'doc_id': '{' + doc_id.strip() + '}',
                'case_no': case_no.strip(),
                'doc_type': doc_type.strip(),
                'doc_date': doc_date.strip(),
                'entry_date': entry_date.strip(),
            })

        sections[section_name] = rows

    return sections


def is_judgment_candidate(row):
    """
    أي مستند نوعه يحوي كلمة 'حكم' — مرشح محتمل ليكون حكم الإحالة.
    تسمية نوع المستند بالنظام تعتمد على من أدخلها يدوياً وغير موثوقة
    (شفنا فعلياً: 'حكم خبير'، وأحياناً 'حكم إحالة' أو 'حكم المحكمة'
    بصيغ مختلفة) — فلا نحاول نخمّن الاسم الدقيق هنا، فقط نجمع كل شي
    محتمل، والقرار النهائي بأيها حكم الإحالة الفعلي يُترك للذكاء
    الاصطناعي بعد قراءة محتوى كل مستند بالفعل.
    """
    return 'حكم' in row['doc_type']


def find_judgment_candidates(sections):
    """
    يرجع كل مستندات 'حكم' المحتملة بأول قسم فيه أي مستندات (بنفس
    ترتيب البحث المتفق عليه: تمييز -> استئناف -> كلية)، مرتبة من
    الأحدث للأقدم بتاريخ المستند. قد ترجع قائمة فاضية لو القسم فيه
    مستندات لكن بدون أي شي يحوي كلمة 'حكم'، أو قائمة بعنصر واحد أو
    أكثر لو فيه عدة أحكام محتملة (حكم أول درجة + حكم استئناف مثلاً).

    يرجع [] لو كل الأقسام الثلاثة فاضية تماماً.
    """
    def parse_doc_date(d):
        d = (d or '').strip()
        for fmt in ('%m/%d/%Y %I:%M:%S %p', '%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%d'):
            try:
                return datetime.datetime.strptime(d, fmt)
            except:
                continue
        return datetime.datetime.min

    for section_name in SEARCH_ORDER:
        rows = sections.get(section_name, [])
        if not rows:
            continue  # القسم فاضٍ، ننتقل للمرحلة التالية

        candidates = [r for r in rows if is_judgment_candidate(r)]
        candidates.sort(key=lambda r: parse_doc_date(r['doc_date']), reverse=True)
        return candidates  # ممكن تكون [] لو القسم فيه مستندات بدون أي 'حكم'

    return []


def get_referral_judgment_pdf_url(doc_id):
    """يبني رابط تحميل ملف PDF لمستند معين عبر doc_id"""
    return f"{BASE_URL}/get_pdf_stream.php?DocId={doc_id}"


def download_judgment_pdf(cookies, doc_id, save_path):
    """يحمّل ملف PDF لمستند معين ويحفظه في save_path"""
    url = get_referral_judgment_pdf_url(doc_id)
    r = requests.get(url, cookies=cookies, verify=False)
    with open(save_path, 'wb') as f:
        f.write(r.content)
    strip_server_stamp(save_path)
    return save_path


_STAMP_RE = re.compile(r'^\s*\d+\s+\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M\s*$')


def strip_server_stamp(path):
    """يحذف الختم المائل اللي يضيفه السيرفر فوق كل صفحة (رقم المستخدم + تاريخ
    ووقت التحميل، مثل '309 14/10/2026 1:39 AM') لأنه يخرّب قراءة OCR.
    يحذف النص فقط ويترك الصورة الممسوحة كما هي. أي فشل → يبقى الملف الأصلي."""
    try:
        import fitz
        doc = fitz.open(path)
        changed = False
        for page in doc:
            found = False
            for b in page.get_text("dict")["blocks"]:
                if b["type"] != 0:
                    continue
                for line in b["lines"]:
                    t = "".join(s["text"] for s in line["spans"])
                    if _STAMP_RE.match(t):
                        for q in page.search_for(t.strip(), quads=True):
                            page.add_redact_annot(q)
                            found = True
            if found:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0)
                changed = True
        if changed:
            tmp = path + ".tmp"
            doc.save(tmp, garbage=3, deflate=True)
            doc.close()
            os.replace(tmp, path)
        else:
            doc.close()
    except Exception:
        pass


def find_most_recent_judgment(sections):
    """
    يرجع أحدث مستند 'حكم' بتاريخه (الأقرب لليوم) من بين كل المرشحين.

    المنطق: لا يمكن أن تصدر المحكمة حكماً جديداً بعد حكم الإحالة للخبرة
    بنفس القضية — لأن الإحالة فعليًا تسلّم مرحلة الفصل بالقضية للجنة
    الخبراء. فأحدث حكم موجود بالقضية غالباً هو حكم الإحالة نفسه.

    هذا تخمين برمجي بسيط (بدون أي استدعاء للذكاء الاصطناعي بهذي
    الخطوة) — يوفر استهلاك التوكن المجاني، ويكفي لاختيار مستند واحد
    بثقة عالية قبل أي قراءة فعلية بالذكاء الاصطناعي.

    يرجع dict للمستند المختار، أو None لو ما فيه أي مرشح بكل الأقسام.
    """
    candidates = find_judgment_candidates(sections)
    return candidates[0] if candidates else None


def is_valid_local_pdf(path):
    """
    يتأكد إن ملف الحكم المحفوظ مسبقًا (بسطح المكتب) موجود وسليم: حجمه
    أكبر من صفر ويبدأ بتوقيع PDF الفعلي (%PDF) — عشان نتجنب ملف فاضي أو
    فاسد من محاولة سابقة فشلت بالمنتصف، أو صفحة HTML (جلسة منتهية)
    انحفظت بالغلط بامتداد pdf.
    """
    try:
        if not (path and os.path.exists(path) and os.path.getsize(path) > 0):
            return False
        with open(path, 'rb') as f:
            return f.read(5) == b'%PDF-'
    except Exception:
        return False


# صف وهمي يمثّل "ملف محلي موجود مسبقًا" — بنفس مفاتيح صف المستند العادي
# عشان أي مستدعي قديم يتعامل معه بدون تعديل. doc_id فاضي = مو معروف.
def _local_judgment_row(path):
    return {
        'doc_id': '', 'case_no': '', 'doc_type': 'ملف محلي محفوظ مسبقًا',
        'doc_date': '', 'entry_date': '', 'local': True, 'path': path,
    }


def get_referral_judgment_for_case(cookies, autocase_no, user_id, save_path,
                                   use_local=True, sections_out=None):
    """
    دالة موحّدة (الاستخدام الأساسي): تجلب صفحة المستندات، تختار أحدث
    مستند 'حكم' برمجياً (بدون أي ذكاء اصطناعي بهذي الخطوة — انظر
    find_most_recent_judgment)، وتحمّله كملف PDF واحد إلى save_path.

    use_local: لو الملف موجود أصلاً بـsave_path وسليم (is_valid_local_pdf)،
    نتخطى جلب صفحة المستندات والتحميل كليًا ونرجع الملف المحلي مباشرة
    (الصف المرجّع فيه 'local': True). يفيد خصوصًا بإعادة محاولة
    الاستخراج (بعد ربط مفتاح Gemini مثلاً) بدون أي طلب شبكة.

    sections_out (اختياري): dict يُعبّى بأقسام صفحة المستندات لو انجلبت
    فعليًا — عشان المسار الاحتياطي (get_referral_judgment_ai_fallback)
    يستخدمها بدون ما يعيد نفس الطلب.

    يرجع (judgment_row, save_path) أو (None, None) لو ما فيه أي مرشح.
    """
    if use_local and is_valid_local_pdf(save_path):
        return _local_judgment_row(save_path), save_path

    html = get_documents_page(cookies, autocase_no, user_id)
    sections = parse_sections(html)
    if sections_out is not None:
        sections_out.update(sections)
    judgment = find_most_recent_judgment(sections)
    if not judgment:
        return None, None
    download_judgment_pdf(cookies, judgment['doc_id'], save_path)
    return judgment, save_path


# ============================================================
# المسار الاحتياطي بالذكاء الاصطناعي — فقط لما يفشل الاختيار البرمجي
# ============================================================

AI_PICK_PROMPT = (
    "أمامك قائمة بأسماء مستندات قضية من نظام الملف الآلي لمحاكم الكويت "
    "(لكل مستند: رقم تسلسلي، القسم، رقم القضية، نوع المستند، تاريخه). "
    "المطلوب: من بين أسماء هذي المستندات، أي واحد غالبًا هو حكم الإحالة "
    "للخبرة (الحكم الذي أحال القضية لإدارة الخبراء)؟\n"
    "أجب برقم المستند التسلسلي فقط (مثال: 7)، بدون أي نص آخر. "
    "لو ما فيه أي مستند منطقي يمكن يكون حكم الإحالة، أجب بـ 0.\n\n"
)


def list_all_documents(sections):
    """
    يجمع كل المستندات بكل الأقسام الثلاثة (تمييز/استئناف/كلية) — القائمة
    الكاملة، مو بس اللي نوعها 'حكم' — بقائمة مسطحة، كل عنصر فيه اسم القسم.
    """
    docs = []
    for section_name in SEARCH_ORDER:
        for row in sections.get(section_name, []):
            docs.append(dict(row, section=section_name))
    return docs


def ai_pick_referral_judgment(docs, exclude_doc_id=None):
    """
    يرسل أسماء/أنواع/تواريخ المستندات فقط (نص — بدون أي محتوى PDF،
    توفيرًا للتوكن) لـGemini ويسأله أي واحد غالبًا حكم الإحالة.
    exclude_doc_id: مستند جُرّب قبل وطلع غلط — يُستبعد من القائمة.
    يرجع صف المستند المختار، أو None (ما فيه مفتاح / فشل / ما لقى شي منطقي).
    """
    candidates = [d for d in docs if d.get('doc_id') and d.get('doc_id') != exclude_doc_id]
    if not candidates:
        return None
    try:
        from gemini_config import generate_content_with_fallback
        from ai_providers import has_any_provider
        if not has_any_provider():
            return None
        client = None  # العميل يُنشأ داخل طبقة المزودات لكل مزود

        lines = [
            f"{i}. [{d['section']}] رقم القضية: {d['case_no']} | نوع المستند: "
            f"{d['doc_type']} | تاريخ المستند: {d['doc_date']}"
            for i, d in enumerate(candidates, start=1)
        ]
        response = generate_content_with_fallback(
            client, contents=[AI_PICK_PROMPT + "\n".join(lines)])
        m = re.search(r'\d+', (response.text or ''))
        if not m:
            return None
        idx = int(m.group(0))
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1]
        return None
    except Exception as e:
        claim_log(f"ai_pick_referral_judgment: فشل — {type(e).__name__}: {e}")
        return None


def get_referral_judgment_ai_fallback(cookies, autocase_no, user_id, save_path,
                                      sections=None, exclude_doc_id=None):
    """
    المسار الاحتياطي (يُستدعى فقط لما يفشل find_most_recent_judgment أو
    يطلع المستند المختار غلط): يجمع قائمة كل المستندات، يخلي Gemini يختار
    حكم الإحالة من أسمائها فقط، ثم يحمّل المستند المختار وحده (ملف واحد)
    إلى save_path.

    sections: أقسام صفحة المستندات لو انجلبت أصلاً (لتفادي طلب مكرر)،
    وإلا تُجلب هنا.

    يرجع (row, save_path) أو (None, None).
    """
    if not sections:
        html = get_documents_page(cookies, autocase_no, user_id)
        if is_login_page(html):
            return None, None
        sections = parse_sections(html)
    docs = list_all_documents(sections)
    if not docs:
        return None, None
    row = ai_pick_referral_judgment(docs, exclude_doc_id=exclude_doc_id)
    if not row:
        return None, None
    download_judgment_pdf(cookies, row['doc_id'], save_path)
    return row, save_path


def is_claim_candidate(row):
    """
    أي مستند نوعه يحوي كلمة من CLAIM_KEYWORDS ('صحيفة' ...) — مرشح
    ليكون صحيفة الدعوى. نفس فلسفة is_judgment_candidate: لا نخمّن الاسم
    الدقيق لأن تسميته يدوية.
    """
    return any(k in row['doc_type'] for k in CLAIM_KEYWORDS)


def find_claim_candidates(sections):
    """
    يرجع كل مستندات صحيفة الدعوى المحتملة من كل الأقسام، مرتبة من الأقدم
    للأحدث بتاريخ المستند (الأقدم غالباً هو مستند الدعوى الأصلي، وما بعده
    صحائف تعديل/استئناف).
    """
    candidates = []
    for rows in sections.values():
        candidates.extend(r for r in rows if is_claim_candidate(r))
    candidates.sort(key=lambda r: _parse_doc_date(r['doc_date']))
    return candidates


def claim_log(msg):
    """سجل تشخيصي صامت (claim_summary.log بجانب البرنامج) — لتتبع سبب غياب الملخص"""
    try:
        import app_paths
        base = os.environ.get(app_paths.ENV) or (app_paths.data_dir() if app_paths.under_tests() else
                                                   os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, 'claim_summary.log'),
                  'a', encoding='utf-8') as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except Exception:
        pass


class LoginPageError(Exception):
    """السيرفر رجّع صفحة تسجيل دخول (جلسة منتهية) — فشل مؤقت، لا يُحفظ عنه شي"""


def is_login_page(html):
    """يكشف صفحة تسجيل الدخول بالنص الخام: كلمة password أو 'تسجيل الدخول'
    أو وسم <input type="password">"""
    h = (html or '').lower()
    return ('password' in h
            or 'تسجيل الدخول' in h
            or bool(re.search(r'<input[^>]*type=["\']?password', h)))


def get_claim_for_case(cookies, autocase_no, user_id, save_path):
    """
    نفس نمط get_referral_judgment_for_case: يجلب صفحة المستندات، يختار
    أقدم صحيفة دعوى، ويحمّلها PDF واحد إلى save_path.
    يرجع (claim_row, save_path, status) حيث status أحد:
      'OK'           — تم التحميل
      'NO_AUTOCASE'  — autocase_no فاضي أو الصفحة بدون أي أقسام مستندات
      'NO_CLAIM_DOC' — فيه مستندات لكن بدون صحيفة دعوى
    وأي فشل فعلي (شبكة/تحميل/صفحة تسجيل دخول) يرفع استثناء ليُعامَل
    كفشل مؤقت (referred_cases يخفي السطر بدون حفظ شي).
    """
    if not (autocase_no or '').strip():
        return None, None, 'NO_AUTOCASE'
    html = get_documents_page(cookies, autocase_no, user_id)
    if is_login_page(html):
        raise LoginPageError("جلسة منتهية — صفحة تسجيل دخول")
    sections = parse_sections(html)
    if not sections:
        claim_log(f"autocase={autocase_no}: الصفحة بدون أقسام مستندات")
        return None, None, 'NO_AUTOCASE'
    candidates = find_claim_candidates(sections)
    if not candidates:
        types = [(sec, r['doc_type']) for sec, rows in sections.items() for r in rows]
        claim_log(f"autocase={autocase_no}: لا صحيفة دعوى — أنواع المستندات: {types}")
        return None, None, 'NO_CLAIM_DOC'
    download_judgment_pdf(cookies, candidates[0]['doc_id'], save_path)
    return candidates[0], save_path, 'OK'


# تصنيف نوع المستند بالكلمة المفتاحية — نفس فلسفة is_judgment_candidate
# بالضبط (تسمية نوع المستند غير موثوقة، تعتمد على من أدخلها يدويًا).
# ⚠️ كلمات صحيفة الدعوى وتقرير الخبير لم تُتحقَّق بعد على بيانات حقيقية
# (بعكس 'حكم' اللي جُرِّب فعليًا) — لو ما انلقت مستندات لقضية تعرف إن
# عندها صحيفة/تقرير فعليًا، ابعت لي أنواع المستندات الحقيقية المعروضة
# بصفحة الملف الآلي لهذي القضية عشان نضبط الكلمات المفتاحية.
CLAIM_KEYWORDS = ('صحيفة', 'لائحة دعوى', 'صحيفه')
REPORT_KEYWORDS = ('تقرير',)


def classify_document(row):
    """يرجع 'judgment' / 'claim' / 'report' / None حسب نوع المستند"""
    t = row['doc_type']
    if 'حكم' in t:
        return 'judgment'
    if any(k in t for k in CLAIM_KEYWORDS):
        return 'claim'
    if any(k in t for k in REPORT_KEYWORDS):
        return 'report'
    return None


def _parse_doc_date(d):
    d = (d or '').strip()
    for fmt in ('%m/%d/%Y %I:%M:%S %p', '%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(d, fmt)
        except Exception:
            continue
    return datetime.datetime.min


def get_case_documents_bundle(cookies, autocase_no, user_id, out_dir):
    """
    يجيب أهم ثلاث مستندات للقضية (حكم الإحالة، صحيفة الدعوى، تقرير
    الخبير — أي منها موجود فقط) ويحمّلها كلها لمجلد out_dir بأسماء
    واضحة. يبحث بكل الأقسام الثلاثة (تمييز/استئناف/كلية) مجتمعة — عكس
    حكم الإحالة اللي يتوقف عند أول قسم فيه مستندات، لأن صحيفة الدعوى
    مثلاً غالبًا تكون بالمحكمة الكلية حتى لو القضية وصلت للتمييز لاحقًا.

    لكل نوع (لو فيه أكثر من مستند مرشح): يختار الأحدث بتاريخه (نفس
    منطق find_most_recent_judgment).

    يرجع dict: {'judgment': path_or_None, 'claim': path_or_None,
    'report': path_or_None} — المسارات فقط لما تم تحميله فعليًا.
    """
    html = get_documents_page(cookies, autocase_no, user_id)
    sections = parse_sections(html)

    by_type = {'judgment': [], 'claim': [], 'report': []}
    for section_rows in sections.values():
        for row in section_rows:
            kind = classify_document(row)
            if kind:
                by_type[kind].append(row)

    labels = {
        'judgment': 'حكم_الإحالة',
        'claim': 'صحيفة_الدعوى',
        'report': 'تقرير_الخبير',
    }

    result = {}
    for kind, rows in by_type.items():
        if not rows:
            result[kind] = None
            continue
        rows.sort(key=lambda r: _parse_doc_date(r['doc_date']), reverse=True)
        best = rows[0]
        path = os.path.join(out_dir, f"{labels[kind]}.pdf")
        download_judgment_pdf(cookies, best['doc_id'], path)
        result[kind] = path

    return result


def get_judgment_candidates_for_case(cookies, autocase_no, user_id, save_dir):
    """
    دالة موحّدة: تجلب صفحة المستندات، تحدد كل مستندات 'حكم' المرشحة
    (قد تكون مستند واحد أو أكثر)، وتحمّل كل واحد منها كملف PDF منفصل
    داخل save_dir. يرجع قائمة [(judgment_row, saved_path), ...] —
    قائمة فاضية لو ما فيه أي مرشح بكل الأقسام الثلاثة.

    ملاحظة: هذي دالة احتياطية/تشخيصية فقط (تجلب كل المرشحين بدون أي
    فلترة بالتاريخ) — الاستخدام الأساسي بالبرنامج هو
    get_referral_judgment_for_case التي تختار أحدث مستند فقط برمجيًا
    لتوفير استهلاك التوكن.
    """
    import os
    html = get_documents_page(cookies, autocase_no, user_id)
    sections = parse_sections(html)
    candidates = find_judgment_candidates(sections)

    results = []
    for i, row in enumerate(candidates):
        safe_type = re.sub(r'[^\w\u0600-\u06FF]+', '_', row['doc_type']).strip('_')
        path = os.path.join(save_dir, f"candidate_{i+1}_{safe_type}.pdf")
        download_judgment_pdf(cookies, row['doc_id'], path)
        results.append((row, path))

    return results