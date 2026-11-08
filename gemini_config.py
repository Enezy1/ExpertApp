# ===== gemini_config.py — حفظ وقراءة مفتاح Google Gemini API لكل خبير على حدة =====
"""
يحفظ مفتاح Gemini API بمجلد خاص بالخبير الحالي (current_expert.py) —
مب مجلد عام يتشاركه كل من يستخدم نفس الجهاز. هذا يحل مشكلة الأجهزة
المشتركة بين أكثر من خبير، حيث كل واحد له مفتاحه الخاص.

ترحيل تلقائي: لو المفتاح موجود بالمكان القديم (العام، قبل هذا
التحديث) ولسه ما فيه نسخة بمجلد الخبير الحالي، يُنقَل تلقائيًا أول
مرة — حتى ما يحتاج أي خبير كان مستخدم البرنامج قبل هذا التحديث يعيد
إدخال مفتاحه من الصفر.
"""
import os
import json
import re
import threading
import secret_store
from current_expert import expert_data_dir

_OLD_KEY_PATH = os.path.join(
    os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'gemini_key.json'
)


def _key_path():
    return os.path.join(expert_data_dir(), 'gemini_key.json')


def _migrate_if_needed():
    """
    ينقل المفتاح من المكان القديم (العام) لمجلد الخبير الحالي، لو لسه
    ما انتقل — نقل فعلي (move) لا نسخ، عشان الملف القديم يختفي فورًا
    من مكانه العام بعد أول خبير يفتح البرنامج بعد هذا التحديث. لو
    سوّيناها نسخ بدل نقل، أي خبير ثاني يفتح البرنامج بعده على نفس
    الجهاز بيرث نفس المفتاح القديم بالغلط — بالضبط المشكلة اللي نحلها.
    """
    new_path = _key_path()
    if os.path.exists(new_path):
        return
    if not os.path.exists(_OLD_KEY_PATH):
        return
    try:
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        os.replace(_OLD_KEY_PATH, new_path)
    except Exception:
        pass


def save_api_key(key):
    """يحفظ المفتاح بمجلد الخبير الحالي (مشفّراً بـDPAPI — secret_store)"""
    secret_store.write_key(_key_path(), 'gemini_api_key', key)


def load_api_key():
    """يرجع المفتاح المحفوظ للخبير الحالي، أو نص فاضي لو ما فيه أي مفتاح بعد.
    ملف قديم بنص صريح يُرحَّل للتشفير تلقائياً عند أول قراءة."""
    _migrate_if_needed()
    return secret_store.read_key(_key_path(), 'gemini_api_key')


def _ocr_key_path():
    return os.path.join(expert_data_dir(), 'ocr_key.json')


def save_ocr_key(key):
    """مفتاح OCR.space الخاص بالخبير الحالي (فاضي = حذف → يرجع لمفتاح القسم)."""
    secret_store.write_key(_ocr_key_path(), 'ocr_api_key', key)


def load_ocr_key():
    return secret_store.read_key(_ocr_key_path(), 'ocr_api_key')


def _openai_key_path():
    return os.path.join(expert_data_dir(), 'openai_key.json')


def save_openai_key(key):
    """مفتاح OpenAI (ChatGPT API) الخاص بالخبير الحالي. فاضي = حذف → يُستعمل مفتاح القسم إن وُجد."""
    secret_store.write_key(_openai_key_path(), 'openai_api_key', key)


def load_openai_key():
    return secret_store.read_key(_openai_key_path(), 'openai_api_key')


# ===== إبلاغ الخبير بفشل مفتاحه الشخصي (لا انتقال صامت لمفتاح القسم) =====
_personal_failures = {}
_personal_lock = threading.Lock()

_KEY_BAD = ('401', '403', 'invalid api key', 'incorrect api key', 'api key not valid', 'api_key_invalid',
            'permission_denied', 'unauthenticated', 'unauthorized', 'expired', 'invalid_api_key')
_KEY_QUOTA = ('429', 'quota', 'insufficient_quota', 'billing', 'resource_exhausted', 'rate limit', 'credit',
              'exceeded')


CAUSE_TEXT = {'invalid': 'المفتاح غير صالح أو منتهٍ', 'quota': 'نفد الرصيد أو الحصة',
              'rate': 'تجاوزت الحد المسموح من الطلبات', 'network': 'انقطع الاتصال بالشبكة',
              'other': 'خطأ من المزوّد'}
_QUOTA_ONLY = ('insufficient_quota', 'billing', 'credit', 'quota', 'exceeded your current')
_RATE_ONLY = ('429', 'rate limit', 'rate_limit', 'resource_exhausted', 'too many requests')


def failure_cause(e):
    """سبب فشل استدعاء بمفتاح: invalid | quota | rate | network | other (بلا أي مفتاح في الناتج)."""
    chain = [e]
    while chain[-1].__cause__ is not None and len(chain) < 4:
        chain.append(chain[-1].__cause__)
    m = ' '.join(str(x).lower() for x in chain)
    if any(t in m for t in _QUOTA_ONLY):
        return 'quota'
    if any(t in m for t in _RATE_ONLY):
        return 'rate'
    if any(t in m for t in _KEY_BAD):
        return 'invalid'
    if USER_FAIL_MSG in m or any(_is_network_error(x) for x in chain):
        return 'network'
    return 'other'


def explain_key_failure(e):
    """سبب عربي إن كان الخطأ يخص المفتاح نفسه (منتهٍ/خاطئ/بلا رصيد/حد)، وإلا ''. أخطاء الشبكة لا تُنسب للمفتاح."""
    c = failure_cause(e) if not isinstance(e, str) else failure_cause(RuntimeError(e))
    return CAUSE_TEXT[c] if c in ('invalid', 'quota', 'rate') else ''


def note_personal_failure(name, e):
    """يسجّل فشل مفتاح الخبير الشخصي لمزوّد (إن كان السبب من المفتاح) ليُعرض عليه، دون أي مفتاح."""
    why = explain_key_failure(e)
    if why:
        with _personal_lock:
            _personal_failures[name] = f'مفتاحك الشخصي لـ{name}: {why}. لم يُستعمل مفتاح القسم — راجع مفتاحك أو أزله من الإعدادات.'
    return why


def pop_personal_failures():
    """رسائل فشل المفاتيح الشخصية المتراكمة (وتُفرَّغ)."""
    with _personal_lock:
        out = list(_personal_failures.values())
        _personal_failures.clear()
    return out


_SECRET_RE = re.compile(r'((?:[?&]key=|key["\']?\s*[:=]\s*["\']?|bearer\s+|api[_-]?key["\']?\s*[:=]\s*["\']?)'
                        r')[A-Za-z0-9_\-\.]{8,}|\b(AIza[0-9A-Za-z_\-]{20,}|AQ\.[0-9A-Za-z_\-\.]{20,}|sk-[0-9A-Za-z_\-]{16,}'
                        r'|dpapi:[A-Za-z0-9+/=]{16,})', re.I)


def redact(text):
    """يخفي أي مفتاح محتمل في نص (سجل/رسالة خطأ): key=…، Bearer …، AIza…، sk-…، dpapi:…"""
    return _SECRET_RE.sub(lambda m: (m.group(1) or '') + '***', str(text))


def has_api_key():
    """تستخدمها أي وحدة ثانية بالبرنامج (مثل قراءة الحكم بالذكاء الاصطناعي)
    للتأكد من وجود مفتاح قبل أي محاولة استدعاء فعلية"""
    return bool(load_api_key())



# ===== أسماء النماذج الفعلية (2026-10-25) =====
# لا اعتماد على الأسماء المستعارة (gemini-flash-latest / gemini-flash-lite-latest): لكل نموذج حصته المستقلة باسمه الفعلي،
# والاسم المستعار يُعدّ على حصة نموذج لا نعرفه. الأسماء تُقرأ من list_models وتُرتَّب بـrank (دالة واحدة تُختبر).
# هذه القائمة احتياط فقط حين تتعذّر قراءة قائمة نماذج المفتاح (شبكة) — أسماء فعلية لا مستعارة.
GEMINI_MODEL_CANDIDATES = [
    'gemini-3.6-flash',
    'gemini-3.8-flash',
    'gemini-2.5-flash',
]
DEFAULT_NAMES = ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-3.8-flash', 'gemini-3.6-flash',
                 'gemini-3-flash', 'gemini-2.5-flash']


# أخطاء مؤقتة من جهة جوجل (ضغط على الموديل، تجاوز الحد، مهلة): الطلب ينتقل فوراً للنموذج التالي في سلسلة المهمة.
_TRANSIENT_MARKERS = (
    '503', 'unavailable', 'high demand', 'overloaded',
    '429', 'resource_exhausted',
    '500', 'internal', '504', 'deadline_exceeded',
)
# سياسة واحدة لإعادة المحاولة (2026-10-25): محاولتان في المجموع للطلب الواحد عبر كل الطبقات (_generate_on_client
# و_run_with_routes وdoc_router._call_provider_retry) — الطلب المرفوض يُحتسب من حصة اليوم.
MAX_ATTEMPTS = 2
SLEEP = None                       # الاختبارات تستبدلها؛ الافتراضي time.sleep
_BUDGET = threading.local()


class _Budget:
    """رصيد محاولات طلب واحد (يُشارك بين الخيوط عبر _call_with_timeout): left، والنماذج التي فشلت فيه bad."""

    def __init__(self, n=MAX_ATTEMPTS):
        self.left, self.bad, self.current = n, set(), ''


def attempt_budget():
    return getattr(_BUDGET, 'b', None)


class _BudgetOut(Exception):
    """نفد رصيد المحاولات لهذا الطلب (محاولتان) — لا إرسال آخر."""


_NOT_SENT = ('not_found', '404', 'not found', 'connecterror', 'connection refused', 'name resolution', 'getaddrinfo',
             'proxyerror', 'network is unreachable', '10061')


def _not_sent(e):
    """خطأ لم يصل فيه الطلب لنموذج قائم (نموذج سُحب، أو لا اتصال أصلاً): لا يُحتسب من رصيد المحاولات."""
    m = (type(e).__name__ + ' ' + str(e)).lower()
    return any(x in m for x in _NOT_SENT) and 'timeout' not in m and 'timed out' not in m


# ===== أقوى نموذج Pro متاح للمفتاح (2026-10-20) — للاستخراج والصياغة والتدقيق =====
# لا اسم ثابت في الكود: تُقرأ قائمة النماذج من الـAPI (models.list) ويُختار أحدث «pro» يدعم generateContent (بلا tts/image/
# customtools…)، أو ما اختاره الخبير في الإعدادات ([gemini_models] pro). Flash احتياطي فقط عند الفشل/تجاوز الحد، ويُسجَّل
# (2026-10-22: النموذج = ما يتيحه المفتاح فعلاً — key_model أدناه؛ «كُتب بواسطة» يذكر اسمه الفعلي فقط).
_MODELS_SECTION = 'gemini_models'
_MODELS_CACHE_TTL = 24 * 3600
_LAST_USED = __import__('threading').local()


def _models_cache_path():
    import app_paths
    return app_paths.path('gemini_models_cache.json')


_SKIP_MODEL = re.compile(r'tts|image|vision|embedding|audio|live|omni|transcribe|thinking|customtools|computer|robotics|'
                         r'lyria|veo|imagen|nano|deep-research|learnlm|aqa|native', re.I)


def _ver(v):
    try:
        return f'{float(v):g}'
    except (TypeError, ValueError):
        return ''


def model_family(name):
    """(العائلة 'lite'|'flash'|'pro'|'gemma'|''، الإصدار '3.5'|'3'…، معاينة؟) من الاسم الفعلي للنموذج.
    الاسم المستعار (-latest) والنماذج غير النصية (tts/image/…) ← ('', '', False)."""
    n = str(name or '').split('/')[-1].lower()
    if not n or n.endswith('-latest') or _SKIP_MODEL.search(n):
        return '', '', False
    m = re.fullmatch(r'gemini-(\d+(?:\.\d+)?)-(flash-lite|flash|pro)(-preview|-exp)?(?:-[\w.-]+)?', n)
    if m:
        return ('lite' if m.group(2) == 'flash-lite' else m.group(2)), _ver(m.group(1)), bool(m.group(3))
    m = re.fullmatch(r'gemma-(\d+(?:\.\d+)?)-(\d+)b(?:-a\d+b)?-it', n)
    if m:
        return 'gemma', _ver(m.group(1)), False
    return '', '', False


def rank(names, family, versions=None):
    """الأسماء الفعلية لعائلة نماذج مرتبة (دالة واحدة لكل التوجيه، بلا شبكة): الإصدار الأعلى أولاً — أو بترتيب versions
    إن أُعطي (('3.5', '3.1') ← 3.5 ثم 3.1 فقط) —، ثم المستقر قبل preview، ثم الاسم الأقصر (بلا لاحقة تاريخ).
    الأسماء المستعارة (-latest) لا تدخل أبداً."""
    vers = [_ver(v) for v in versions] if versions is not None else None
    out = {}
    for raw in names or []:
        n = str(raw).split('/')[-1]
        fam, ver, prev = model_family(n)
        if fam != family or (vers is not None and ver not in vers):
            continue
        order = vers.index(ver) if vers is not None else -float(ver)
        out[n] = (order, prev, len(n), n)
    return sorted(out, key=out.get)


def rank_pro(names):
    """نماذج Pro الفعلية من الأقوى (الإصدار الأعلى، المستقر قبل preview) — rank(names, 'pro')."""
    return rank(names, 'pro')


def list_models(client=None, api_key=None, refresh=False):
    """أسماء النماذج التي تدعم generateContent لهذا المفتاح (مخزّنة 24 ساعة في %LOCALAPPDATA%)."""
    import json as _json
    path = _models_cache_path()
    kid = key_id(api_key) if api_key else ''          # القائمة تخص المفتاح: مفتاح آخر ← تُقرأ من جديد
    if not refresh:
        try:
            with open(path, encoding='utf-8') as f:
                c = _json.load(f)
            if time.time() - c.get('at', 0) < _MODELS_CACHE_TTL and c.get('names') and (
                    not kid or c.get('kid', kid) == kid):
                return c['names']
        except (OSError, ValueError):
            pass
    if client is None:
        client = _make_client(_net_state.get('route') or ROUTE_DIRECT, 30, api_key=api_key or load_api_key())
    names = []
    for m in client.models.list():
        acts = getattr(m, 'supported_actions', None) or getattr(m, 'supported_generation_methods', None) or []
        if 'generateContent' in acts:
            names.append(str(m.name).split('/')[-1])
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            _json.dump({'at': time.time(), 'names': names, 'kid': kid}, f)
    except OSError:
        pass
    return names


def pro_setting():
    """اختيار الخبير من الإعدادات: 'auto' (أحدث Pro متاح) أو اسم نموذج بعينه."""
    cp = configparser.RawConfigParser()
    try:
        cp.read(os.path.join(_app_dir(), _NET_INI_NAME), encoding='utf-8')
    except Exception:
        return 'auto'
    return (cp.get(_MODELS_SECTION, 'pro', fallback='auto') or 'auto').strip()


def save_pro_setting(value):
    path = os.path.join(_app_dir(), _NET_INI_NAME)
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(path, encoding='utf-8')
    if not cp.has_section(_MODELS_SECTION):
        cp.add_section(_MODELS_SECTION)
    cp.set(_MODELS_SECTION, 'pro', (value or 'auto').strip())
    with open(path, 'w', encoding='utf-8') as f:
        cp.write(f)


_PRO_BLOCKED = {}                 # نموذج Pro ← وقت انتهاء الحجب (حصة المفتاح نفدت/غير متاحة: لا طلب فاشل في كل مرة)
_PRO_BLOCK_SECONDS = 30 * 60


# ===== ما يتيحه المفتاح فعلاً (2026-10-22) =====
# المفتاح المجاني قد لا يتيح Pro (حصة صفر ← 429). عند أول استعمال للمفتاح (أو زر «اختبار») يُجرَّب أحدث Pro بطلب صغير؛ إن
# رُفض بسبب الحصة/الصلاحية يُعتمد أحدث Flash من قائمة النماذج (الاسم من الـAPI لا ثابت في الكود). النتيجة تُحفظ لكل مفتاح
# (بصمته، لا المفتاح نفسه) في gemini_key_caps.json، فلا يُجرَّب Pro في كل طلب. تغيير المفتاح = بصمة جديدة = اكتشاف جديد.
_CAPS_TRANSIENT_TTL = 3600        # فشل مؤقت (503/504) أثناء التجربة: النتيجة تُعاد بعد ساعة لا تُعتمد نهائياً
_KEY_CTX = __import__('threading').local()
_NO_ACCESS = ('429', 'quota', 'resource_exhausted', 'permission', '403', 'billing', 'not_found', '404', 'not found',
              'not supported', 'free tier')


def _caps_path():
    import app_paths
    return app_paths.path('gemini_key_caps.json')


def key_id(key):
    import hashlib
    return hashlib.sha256((key or '').encode('utf-8')).hexdigest()[:16]


def _read_caps():
    import json as _json
    try:
        with open(_caps_path(), encoding='utf-8') as f:
            c = _json.load(f)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_caps(caps):
    import json as _json
    try:
        os.makedirs(os.path.dirname(_caps_path()), exist_ok=True)
        with open(_caps_path(), 'w', encoding='utf-8') as f:
            _json.dump(caps, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def rank_flash(names):
    """نماذج Flash الفعلية من الأحدث (بلا Lite ولا الاسم المستعار) — rank(names, 'flash')."""
    return rank(names, 'flash')


def rank_lite(names):
    """نماذج Flash Lite الفعلية من الأحدث (بلا الاسم المستعار) — rank(names, 'lite')."""
    return rank(names, 'lite')


def rank_gemma(names):
    """نماذج Gemma النصية مرتبة: الإصدار الأعلى ثم الأكبر حجماً (gemma-4-31b-it قبل gemma-4-26b-a4b-it).
    (2026-10-25: Gemma خارج خطة التوجيه — غير مستقر؛ تبقى الدالة لمن يضعه صراحةً في [gemini_routing].)"""
    import re as _re
    out = []
    for raw in names or []:
        n = str(raw).split('/')[-1]
        m = _re.fullmatch(r'gemma-(\d+(?:\.\d+)?)-(\d+)b(?:-a\d+b)?-it', n)
        if m:
            out.append(((float(m.group(1)), int(m.group(2)), 0 if '-a' in n else 1), n))
    return [n for _k, n in sorted(out, reverse=True)]


def key_model(api_key=None, client=None, refresh=False):
    """{'model', 'pro', 'reason', 'at'}: النموذج الذي يتيحه هذا المفتاح فعلاً (مخزّن لكل مفتاح). refresh=True يعيد الاكتشاف."""
    key = api_key if api_key is not None else load_api_key()
    kid = key_id(key)
    caps = _read_caps()
    rec = caps.get(kid)
    if rec and rec.get('model') and not refresh and not (
            rec.get('transient') and time.time() - rec.get('at', 0) > _CAPS_TRANSIENT_TTL):
        return rec
    if client is None:
        client = _make_client(_net_state.get('route') or ROUTE_DIRECT, 60, api_key=key)
    names = list_models(client, api_key=key, refresh=refresh)
    pros, flashes = rank_pro(names), rank_flash(names)
    rec = None
    reason, transient = '', False
    for m in pros[:1]:
        try:
            client.models.generate_content(model=m, contents='اكتب: نعم')
            rec = {'model': m, 'pro': True, 'reason': ''}
        except Exception as e:
            msg = str(e).lower()
            reason = short_error(e)
            transient = not any(x in msg for x in _NO_ACCESS)
    if rec is None:
        rec = {'model': (flashes or GEMINI_MODEL_CANDIDATES)[0], 'pro': False,
               'reason': (f'{pros[0]} غير متاح لهذا المفتاح: {reason}' if pros else 'لا نموذج Pro في قائمة المفتاح')}
        if transient:
            rec['transient'] = True
    rec.update(at=time.time(), tried=pros[:1])
    caps[kid] = rec
    _write_caps(caps)
    return rec


def cached_key_model(api_key=None):
    """النتيجة المحفوظة فقط (بلا أي طلب) — لسطر «مفتاحك يتيح» في الإعدادات."""
    key = api_key if api_key is not None else load_api_key()
    return _read_caps().get(key_id(key)) if key else None


def _mark_no_pro(model, why=''):
    """Pro رُفض أثناء العمل (الحصة نفدت): يُحفظ للمفتاح الجاري فلا يُجرَّب ثانية حتى «اختبار» أو تغيير المفتاح."""
    kid = getattr(_KEY_CTX, 'kid', '')
    if not kid:
        return
    caps = _read_caps()
    rec = caps.get(kid) or {}
    if rec.get('pro') or not rec:
        flashes = rank_flash(getattr(_KEY_CTX, 'names', None) or [])
        caps[kid] = {'model': (flashes or GEMINI_MODEL_CANDIDATES)[0], 'pro': False, 'at': time.time(),
                     'reason': f'{model} رُفض أثناء العمل: {why}'[:300], 'tried': [model]}
        _write_caps(caps)


def daily_quota_until(e):
    """وقت تجدد حصة اليوم إن كان الخطأ «نفدت حصة الطلبات اليومية لهذا النموذج» (PerDay)، وإلا 0."""
    import re as _re
    msg = str(e)
    if 'PerDay' not in msg and 'per_day' not in msg.lower():
        return 0
    m = _re.search(r"retryDelay'?\"?:\s*'?\"?(\d+)s", msg)
    if m:
        return time.time() + int(m.group(1))
    m = _re.search(r'retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s', msg)
    if m:
        return time.time() + int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3))
    return time.time() + 6 * 3600


def mark_exhausted(model, until):
    """نموذج نفدت حصته اليومية لهذا المفتاح: يُحفظ (بصمة المفتاح) فلا يُجرَّب حتى تتجدد — حتى بعد إغلاق البرنامج."""
    kid = getattr(_KEY_CTX, 'kid', '')
    if not kid:
        return
    caps = _read_caps()
    rec = caps.setdefault(kid, {})
    ex = rec.setdefault('exhausted', {})
    ex[model] = until
    _write_caps(caps)


def exhausted_models(api_key=None):
    """{نموذج: وقت التجدد} لما نفدت حصته اليومية ولم تتجدد بعد (لهذا المفتاح)."""
    key = api_key if api_key is not None else load_api_key()
    rec = _read_caps().get(key_id(key)) or {}
    now = time.time()
    return {m: t for m, t in (rec.get('exhausted') or {}).items() if t > now}


def pro_candidates(client=None, api_key=None):
    """[النموذج الذي يتيحه المفتاح (أحدث Pro إن أتاحه وإلا أحدث Flash)، ثم البدائل]. اختيار الخبير الصريح يتقدّم."""
    s = pro_setting()
    if s and s != 'auto':
        return [s] + [m for m in GEMINI_MODEL_CANDIDATES if m != s]
    key = api_key if api_key is not None else load_api_key()
    _KEY_CTX.kid = key_id(key)
    _KEY_CTX.quota = False
    try:
        names = list_models(client, api_key=key)
    except Exception as e:
        _log(_net_state.get('route') or ROUTE_DIRECT, 'MODELS-LIST-FAIL', note=short_error(e))
        names = []
    _KEY_CTX.names = names
    try:
        cap = key_model(key, client)
    except Exception as e:
        _log(_net_state.get('route') or ROUTE_DIRECT, 'KEY-CAPS-FAIL', note=short_error(e))
        cap = {'model': (rank_pro(names) or ['gemini-pro-latest'])[0], 'pro': True}
    first = cap['model']
    now = time.time()
    gone = exhausted_models(key)
    rest = ([m for m in rank_pro(names)[:3] if m != first and _PRO_BLOCKED.get(m, 0) < now] if cap.get('pro') else [])
    # أحدث Flash لم تنفد حصته ثم Lite آخراً — أسماء فعلية فقط (لا مستعارة ولا Gemma)
    tail = rank_flash(names) + rank_lite(names) or list(GEMINI_MODEL_CANDIDATES)
    out = []
    for m in [first] + rest + tail:
        if m not in out and m not in gone:
            out.append(m)
    return out or [first]


class QuotaExhausted(RuntimeError):
    """لا نموذج متاح لهذه المهمة الآن: حصة اليوم (المحلية أو 429 فعلي) نفدت لكل نماذج ترتيبها. لا نزول صامت لأضعف."""

    def __init__(self, task, models=()):
        self.task, self.models = task, list(models)
        super().__init__(self.message_ar())

    def message_ar(self):
        import gemini_quota
        reset = datetime.fromtimestamp(gemini_quota.next_reset()).strftime('%H:%M')
        names = '، '.join(self.models[:3]) or 'لا نموذج مطابق'
        return (f'نفدت حصة اليوم للنموذج المخصص لمهمة «{TASK_LABELS.get(self.task, self.task)}» ({names}) بمفتاح Gemini '
                f'هذا. لم يُستعمل نموذج أضعف. تتجدد الحصة منتصف الليل بتوقيت المحيط الهادئ (الساعة {reset} بتوقيتك)، '
                'أو استعمل مفتاحاً مدفوعاً.')


TASK_LABELS = {'ocr': 'تحويل الممسوح إلى نص', 'text_light': 'الفرز والملخصات', 'write': 'صياغة التقرير',
               'research': 'البحث والنتيجة'}


def task_candidates(client=None, api_key=None, task='write', tokens=0, media=False):
    """ترتيب النماذج لمهمة (ai_providers.route_models) بعد استبعاد ما نفدت حصته اليوم (429 فعلي أو العدّاد المحلي).
    المفتاح المدفوع (Pro متاح) لا تُفرض عليه الحدود المحلية. لا نموذج ← QuotaExhausted برسالة واضحة."""
    import ai_providers
    import gemini_quota
    key = api_key if api_key is not None else load_api_key()
    kid = key_id(key)
    _KEY_CTX.kid = kid
    try:
        names = list_models(client, api_key=key)
    except Exception as e:
        _log(_net_state.get('route') or ROUTE_DIRECT, 'MODELS-LIST-FAIL', note=short_error(e))
        names = []
    _KEY_CTX.names = names
    try:
        cap = key_model(key, client)
    except Exception as e:
        _log(_net_state.get('route') or ROUTE_DIRECT, 'KEY-CAPS-FAIL', note=short_error(e))
        cap = {'model': (rank_flash(names) or GEMINI_MODEL_CANDIDATES)[0], 'pro': False}
    pro_ok = bool(cap.get('pro'))
    _KEY_CTX.quota = not pro_ok
    _KEY_CTX.tokens = int(tokens or 0)
    _KEY_CTX.task = task
    s = pro_setting()
    order = ai_providers.route_models(task, names or DEFAULT_NAMES, pro_ok, tokens, media)
    primary = ai_providers.route_models(task, names or DEFAULT_NAMES, pro_ok, tokens, media, fallback=False)
    if task == 'research' and s and s != 'auto' and s not in order:
        order.insert(0, s)                         # اختيار الخبير الصريح لنموذج البحث
        primary.insert(0, s)
    _KEY_CTX.primary = set(primary)                # ما بعدها «نموذج احتياطي» في «كُتب بواسطة»
    gone = exhausted_models(key)
    now = time.time()
    out = []
    for m in order:
        if m in gone or m in out or _PRO_BLOCKED.get(m, 0) > now:
            continue
        ok, why, _wait = gemini_quota.check(kid, m, tokens, enforce=not pro_ok)
        if not ok and why in ('day', 'too_big'):
            continue
        out.append(m)
    if not out:
        _log(_net_state.get('route') or ROUTE_DIRECT, 'QUOTA-STOP', note=f'{task}: {", ".join(order[:4])}')
        raise QuotaExhausted(task, order)
    return out


def last_model_used():
    """(اسم النموذج الذي كتب آخر رد في هذا الخيط، هل هو بديل عن الأول المطلوب)."""
    return getattr(_LAST_USED, 'model', ''), getattr(_LAST_USED, 'fallback', False)


FALLBACK_NOTE = 'نموذج احتياطي — أعد الكتابة لاحقاً'


def describe_model(model, fallback=False):
    """اسم النموذج الفعلي لـ«كُتب بواسطة». fallback=True (الملاذ الأخير خارج النماذج المحددة للمهمة) ← يُلحق به
    «نموذج احتياطي — أعد الكتابة لاحقاً» حتى ينتبه الخبير."""
    if not model:
        return ''
    return f'{model} ({FALLBACK_NOTE})' if fallback else model


def is_fallback(model):
    """النموذج الذي أجاب في هذا الخيط خارج النماذج المحددة لمهمته (task_candidates)؟"""
    primary = getattr(_KEY_CTX, 'primary', None)
    return bool(model) and primary is not None and model not in primary


class _QuotaSkip(Exception):
    """العدّاد المحلي يمنع هذا النموذج الآن (حصة اليوم أو طلب أكبر من حد الدقيقة) — يُتخطى بلا إرسال."""


def _quota_send(client, model_name, kwargs):
    """إرسال واحد عبر العدّاد المحلي (إن كان مفعّلاً لهذا الخيط — task_candidates): يتخطى المنتهي قبل الإرسال، وينتظر
    حد الدقيقة إن كان قصيراً، ويسجّل كل طلب يُرسل فعلاً (الفاشل بـ429 يُحتسب أيضاً)."""
    import gemini_quota
    kid, tok = getattr(_KEY_CTX, 'kid', ''), getattr(_KEY_CTX, 'tokens', 0)
    if getattr(_KEY_CTX, 'quota', False):
        ok, why, wait = gemini_quota.check(kid, model_name, tok)
        if not ok and why == 'minute' and wait <= 65:
            (SLEEP or time.sleep)(wait)
            ok = True
        if not ok:
            raise _QuotaSkip(why)
    b = attempt_budget()
    if b is not None:
        if b.left <= 0:
            raise _BudgetOut()
        b.left -= 1
        b.current = model_name
    if kid:
        gemini_quota.record(kid, model_name, tok)       # كل طلب يُرسل يُعدّ على حصة نموذجه (المدفوع للعرض فقط)
    try:
        resp = client.models.generate_content(model=model_name, **kwargs)
    except Exception as e:
        if b is not None and _not_sent(e):
            b.left += 1                                 # لم يصل لنموذج قائم: لا يُحتسب من المحاولتين
        raise
    _LAST_USED.model = model_name
    return resp


def _daily_full(model_name, until):
    mark_exhausted(model_name, until)
    try:
        import gemini_quota
        gemini_quota.mark_full(getattr(_KEY_CTX, 'kid', ''), model_name)
    except Exception:
        pass


def _generate_on_client(client, models=None, **kwargs):
    """بديل عن client.models.generate_content(model=..., ...) المباشر — سياسة واحدة (2026-10-25):
      - محاولتان في المجموع للطلب الواحد (MAX_ATTEMPTS، رصيد مشترك مع _run_with_routes عبر attempt_budget).
      - 500/503/504/429 ← فوراً للنموذج التالي في سلسلة المهمة (لا انتظار ولا جولات). نموذج وحيد ← يُعاد مرة واحدة فقط.
      - حصة اليوم نفدت (429 يومي أو العدّاد المحلي gemini_quota) ← يُستبعد بلا إرسال ولا إعادة.
      - نموذج سُحب (404) ← التالي ولا يُحتسب من المحاولتين.
      - أي خطأ آخر (مفتاح خطأ، طلب غير صالح…) يوقف فوراً."""
    models = list(models or GEMINI_MODEL_CANDIDATES)
    original = list(models)
    preferred = models[0]
    b = attempt_budget()
    own = b is None
    if own:
        b = _Budget()
        _BUDGET.b = b
    todo = [m for m in models if m not in b.bad] or models
    last_error, skipped, repeated = None, False, set()
    try:
        while todo:
            name = todo[0]
            try:
                resp = _quota_send(client, name, kwargs)
                _LAST_USED.model, _LAST_USED.fallback = name, name != preferred
                return resp
            except _QuotaSkip:
                todo.pop(0)
                skipped = True
                continue
            except _BudgetOut:
                break
            except Exception as e:
                msg = str(e).lower()
                if 'not_found' in msg or '404' in msg or 'not found' in msg:
                    todo.pop(0)
                    last_error = e
                    continue
                if not any(m in msg for m in _TRANSIENT_MARKERS):
                    raise
                last_error = e
                b.bad.add(name)
                until = daily_quota_until(e)
                if until:                       # حصة اليوم لهذا النموذج نفدت: يُحفظ حتى تتجدد
                    _daily_full(name, until)
                    if 'pro' in name:
                        _mark_no_pro(name, short_error(e))
                    _log(_net_state.get('route') or ROUTE_DIRECT, 'DAILY-QUOTA', note=f'{name} → التالي')
                elif 'pro' in name and 'quota' in msg:   # حصة Pro نفدت ← يُحجب مؤقتاً
                    _PRO_BLOCKED[name] = time.time() + _PRO_BLOCK_SECONDS
                    _mark_no_pro(name, short_error(e))
                    _log(_net_state.get('route') or ROUTE_DIRECT, 'PRO-QUOTA', note=f'{name} → التالي')
                if len(todo) > 1 or until or name in repeated:
                    todo.pop(0)                 # التالي في سلسلة المهمة فوراً
                    continue
                repeated.add(name)              # نموذج وحيد: إعادة واحدة فقط بعد انتظار قصير
                m_ = re.search(r'retry(?:\s+in|Delay\W+)\s*([\d.]+)s', str(e), re.I)
                (SLEEP or time.sleep)(min(65.0, float(m_.group(1)) + 1) if m_ else 3.0)
    finally:
        if own:
            _BUDGET.b = None
    if last_error is None and skipped:
        raise QuotaExhausted(getattr(_KEY_CTX, 'task', '') or 'write', original)
    if last_error is None:
        raise RuntimeError('لا نموذج متاح')
    raise last_error


# ===== اتصال الشبكة: اختيار طريق البروكسي/المباشر + تبديل تلقائي + سجل للأدمن =====
# عنوان البروكسي يُقرأ من gemini_network.ini (بجانب البرنامج) — مب داخل الكود.
# لو القيمة فاضية: طريق "proxy" يستخدم إعدادات البروكسي الافتراضية للنظام.
import sys
import time
import threading
import configparser
from datetime import datetime
from current_expert import get_current_user

ROUTE_PROXY = 'proxy'
ROUTE_DIRECT = 'direct'
ROUTE_LABELS = {ROUTE_PROXY: 'بروكسي', ROUTE_DIRECT: 'مباشر'}
USER_FAIL_MSG = 'تعذر الاتصال بخدمة الذكاء الاصطناعي، حاول لاحقاً'

_PROBE_URL = 'https://generativelanguage.googleapis.com/'
_PROBE_TIMEOUT = 8
_NET_INI_NAME = 'gemini_network.ini'
_NET_INI_TEMPLATE = (
    '[network]\n'
    '; عنوان بروكسي الدوام، مثال: http://10.0.0.5:8080\n'
    '; اتركه فاضيًا لاستخدام إعدادات البروكسي الافتراضية للنظام\n'
    'proxy_url =\n'
)
_LOG_PATH = __import__('app_paths').path('gemini_connection.log')     # الاختبارات: مجلد مؤقت (EXPERTAPP_LOG_DIR)
_LOG_MAX_BYTES = 1_000_000

_net_lock = threading.Lock()
_log_ctx = threading.local()


def set_log_provider(name, key_type):
    """المزود ونوع المفتاح (خاص/افتراضي) لأسطر السجل في هذا الخيط."""
    _log_ctx.provider = f'{name}({key_type})'


def short_error(e):
    """سبب مختصر للتبديل (بدون أي مفتاح)."""
    if isinstance(e, RuntimeError) and e.__cause__ is not None:
        e = e.__cause__
    return ' '.join(f'{type(e).__name__}: {redact(str(e))[:150]}'.split())




_net_state = {'route': ROUTE_PROXY, 'checked': False, 'checking': False,
              'connected': None, 'last_check': '', 'detail': ''}


def _app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_proxy_url():
    """عنوان البروكسي من gemini_network.ini (ينشئ الملف بقالب فاضي لو غير موجود)."""
    path = os.path.join(_app_dir(), _NET_INI_NAME)
    try:
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                f.write(_NET_INI_TEMPLATE)
            return ''
        cp = configparser.ConfigParser()
        cp.read(path, encoding='utf-8')
        return cp.get('network', 'proxy_url', fallback='').strip()
    except Exception:
        return ''


def _other(route):
    return ROUTE_DIRECT if route == ROUTE_PROXY else ROUTE_PROXY


def _is_network_error(e):
    """خطأ اتصال (قطع/مهلة/بروكسي/SSL) وليس خطأ من جهة Gemini نفسه."""
    name = type(e).__name__.lower()
    msg = str(e).lower()
    if any(k in name for k in ('connect', 'timeout', 'proxy', 'ssl', 'network',
                               'remoteprotocol', 'readerror', 'writeerror')):
        return True
    return any(k in msg for k in (
        'connecterror', 'connection', 'timed out', 'timeout', 'proxy',
        'ssl', 'name resolution', 'getaddrinfo', 'network is unreachable',
        'remote end closed', 'reset by peer', 'eof occurred'))


def _payload_size(contents):
    """تقدير حجم المحتوى المرسل بالبايت (نص + ملفات)."""
    total = 0

    def walk(x):
        nonlocal total
        if x is None:
            return
        if isinstance(x, str):
            total += len(x.encode('utf-8', 'ignore'))
        elif isinstance(x, (bytes, bytearray)):
            total += len(x)
        elif isinstance(x, (list, tuple)):
            for i in x:
                walk(i)
        elif isinstance(x, dict):
            for i in x.values():
                walk(i)
        else:
            for attr in ('text', 'data', 'inline_data', 'parts'):
                v = getattr(x, attr, None)
                if v is not None:
                    walk(v)
    try:
        walk(contents)
    except Exception:
        pass
    return total


def _fmt_size(n):
    return f"{n / 1024:.1f}KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.2f}MB"


def _log(route, status, size=0, error=None, note=''):
    """سطر واحد لكل محاولة: الوقت | المستخدم | الطريق | النتيجة | الحجم | الخطأ الكامل | ملاحظة."""
    try:
        err = ''
        if error is not None:
            err = redact(f"{type(error).__name__}: {error}").replace('\r', ' ').replace('\n', ' ⏎ ')
        line = ' | '.join([
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            get_current_user(), ROUTE_LABELS.get(route, route),
            getattr(_log_ctx, 'provider', '-'), status,
            _fmt_size(size), err, note]).rstrip(' |')
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        if os.path.exists(_LOG_PATH) and os.path.getsize(_LOG_PATH) > _LOG_MAX_BYTES:
            os.replace(_LOG_PATH, _LOG_PATH + '.old')
        with open(_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _trusted_ssl_context():
    """سياق SSL يثق بشهادات مخزن ويندوز (شهادة فحص SSL الخاصة بجهة الدوام إن وُجدت)
    بالإضافة لشهادات certifi. التحقق من الشهادات يبقى مفعّلًا — لا نعطّله."""
    import ssl
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs()  # على ويندوز: مخزن الشهادات الموثوقة للنظام
    except Exception:
        pass
    return ctx


def diagnose_error(e):
    """تلميح لسبب الفشل المحتمل (للسجل/الأدمن)."""
    m = (type(e).__name__ + ' ' + str(e)).lower()
    if 'certificate' in m or 'ssl' in m:
        return 'سبب محتمل: فحص SSL من الحماية/البروكسي (شهادة غير موثوقة)'
    if '407' in m or 'proxy authentication' in m:
        return 'سبب محتمل: البروكسي يطلب مصادقة'
    if 'reset by peer' in m or 'remote end closed' in m or 'eof' in m or '10054' in m:
        return 'سبب محتمل: جدار الحماية/الشبكة قطع الاتصال'
    if 'timed out' in m or 'timeout' in m:
        return 'سبب محتمل: مهلة — الشبكة بطيئة أو الاتصال محجوب'
    if 'refused' in m or '10061' in m:
        return 'سبب محتمل: عنوان البروكسي خاطئ أو المنفذ مغلق'
    if 'getaddrinfo' in m or 'name resolution' in m:
        return 'سبب محتمل: فشل DNS'
    return ''


def _make_client(route, timeout=None, api_key=None):
    """عميل Gemini مرتبط بطريق معيّن (يحل محل العميل الممرَّر، نفس المفتاح)."""
    from google import genai
    from google.genai import types
    proxy = get_proxy_url()
    if route == ROUTE_DIRECT:
        args = {'trust_env': False}
    elif proxy:
        args = {'proxy': proxy, 'trust_env': False}
    else:
        args = {}
    args['verify'] = _trusted_ssl_context()
    return genai.Client(api_key=api_key or load_api_key(),
                        http_options=types.HttpOptions(
                            client_args=args,
                            timeout=int(timeout * 1000) if timeout else None))


def _probe_route(route):
    """طلب خفيف للسيرفر؛ أي رد (حتى خطأ HTTP) = نجاح. يرجع (ok, تفاصيل)."""
    import requests
    s = requests.Session()
    proxy = get_proxy_url()
    try:
        if route == ROUTE_DIRECT:
            s.trust_env = False
        elif proxy:
            s.trust_env = False
            s.proxies = {'http': proxy, 'https': proxy}
        r = s.get(_PROBE_URL, timeout=_PROBE_TIMEOUT)
        _log(route, 'PROBE-OK', note=f'HTTP {r.status_code}')
        return True, f'HTTP {r.status_code}'
    except Exception as e:
        _log(route, 'PROBE-FAIL', error=e, note=diagnose_error(e))
        return False, f'{type(e).__name__}: {e}'
    finally:
        s.close()


def check_connection():
    """يفحص الطريقين ويعتمد الناجح (البروكسي أولًا عند التعادل). يُستدعى بخيط خلفي."""
    with _net_lock:
        if _net_state['checking']:
            return
        _net_state['checking'] = True
    try:
        res = {r: _probe_route(r) for r in (ROUTE_PROXY, ROUTE_DIRECT)}
        old = _net_state['route']
        if res[ROUTE_PROXY][0]:
            chosen = ROUTE_PROXY
        elif res[ROUTE_DIRECT][0]:
            chosen = ROUTE_DIRECT
        else:
            chosen = old
        detail = ' / '.join(f"{ROUTE_LABELS[r]}: {'✅' if ok else '❌'} {d}"
                            for r, (ok, d) in res.items())
        with _net_lock:
            _net_state.update(route=chosen, checked=True, detail=detail,
                              last_check=datetime.now().strftime('%H:%M:%S'),
                              connected=any(ok for ok, _ in res.values()))
        if chosen != old:
            _log(chosen, 'SWITCH', note=f'فحص الاتصال: {ROUTE_LABELS[old]} → {ROUTE_LABELS[chosen]}')
    finally:
        _net_state['checking'] = False


def start_connection_check():
    """فحص بالخلفية عند بدء التشغيل بدون تعطيل الواجهة."""
    threading.Thread(target=check_connection, daemon=True).start()


def get_connection_status():
    return dict(_net_state)


def is_admin():
    """نفس صلاحية المالك/الأدمن الحالية بالتطبيق (main1_access.is_owner)."""
    try:
        import main1_access
        return main1_access.is_owner(get_current_user())
    except Exception:
        return False


def read_log_tail(max_lines=40):
    """آخر أسطر السجل — للأدمن فقط."""
    if not is_admin():
        return []
    try:
        with open(_LOG_PATH, encoding='utf-8') as f:
            return f.read().splitlines()[-max_lines:]
    except Exception:
        return []


def _adopt_route(route, previous):
    if route == previous:
        return
    with _net_lock:
        _net_state['route'] = route
    _log(route, 'SWITCH', note=f'{ROUTE_LABELS[previous]} → {ROUTE_LABELS[route]} بعد فشل الاتصال')


# ===== إعدادات PDF (ملف gemini_network.ini، قسم [pdf]) =====
_PDF_DEFAULTS = {
    'base_timeout': 60,      # ثانية
    'per_page_timeout': 10,  # ثانية لكل صفحة
    'max_timeout': 180,      # سقف المهلة
    # حكم الإحالة: الصفحة الأولى (الأطراف ورقم القضية والتاريخ) وآخر صفحتين (المنطوق وجلسة الخبراء) تكفي غالبًا.
    # كانت 8/3/3 هنا و3/1/2 في gemini_network.ini فقط — والـEXE بلا ini (dist، أجهزة الخبراء) أرسل حكمًا من 6 صفحات كاملًا
    'trim_threshold': 3,     # حكم الإحالة أكثر من هذا العدد يُقص
    'head_pages': 1,         # صفحات من البداية بعد القص
    'tail_pages': 2,         # صفحات من النهاية بعد القص
    'scan_dpi': 150,
    'jpeg_quality': 70,
    # المستندات الحاسمة (صحيفة الدعوى، حكم الإحالة، العقود، الفواتير): جودة عالية لأن الأرقام والمبالغ فيها.
    # critical_max_mb سقف حجم الملف المُرسَل (حدّ Gemini 50MB)؛ يتجاوزه ← يُخفَّض dpi ثم الجودة تدريجياً.
    'critical_dpi': 300,
    'critical_jpeg_quality': 90,
    'critical_max_mb': 30,
    'min_text_chars_per_page': 50,  # أقل من هذا = نعتبره ممسوحًا
}
SLOW_SECONDS = 10


FEATURES = {'api': 'مفاتيح API (Gemini/Groq/z.ai)', 'ocr_external': 'OCR الخارجي (OCR.space)',
            'ocr_internal': 'OCR الداخلي (على الجهاز)', 'browser': 'الاتصال بمواقع الدردشة (المتصفح)'}


def feature_on(name):
    """مفاتيح التشغيل/الإيقاف في [features] من gemini_network.ini — الافتراضي مفعّل."""
    try:
        cp = configparser.ConfigParser()
        cp.read(os.path.join(_app_dir(), _NET_INI_NAME), encoding='utf-8')
        return cp.get('features', name, fallback='1').strip().lower() not in ('0', 'false', 'no')
    except Exception:
        return True


def set_feature(name, on):
    path = os.path.join(_app_dir(), _NET_INI_NAME)
    try:
        get_proxy_url()  # يضمن وجود الملف
        cp = configparser.ConfigParser()
        cp.read(path, encoding='utf-8')
        if not cp.has_section('features'):
            cp.add_section('features')
        cp.set('features', name, '1' if on else '0')
        with open(path, 'w', encoding='utf-8') as f:
            cp.write(f)
        return True
    except Exception:
        return False


def get_pdf_settings():
    cfg = dict(_PDF_DEFAULTS)
    try:
        cp = configparser.ConfigParser()
        cp.read(os.path.join(_app_dir(), _NET_INI_NAME), encoding='utf-8')
        for k, d in _PDF_DEFAULTS.items():
            try:
                v = int(cp.get('pdf', k, fallback=d))
                cfg[k] = v if v > 0 else d
            except ValueError:
                pass
    except Exception:
        pass
    return cfg


def get_critical_color():
    """gray | rgb لتحضير المستندات الحاسمة ([pdf] critical_color في ini؛ الافتراضي gray)."""
    try:
        cp = configparser.ConfigParser()
        cp.read(os.path.join(_app_dir(), _NET_INI_NAME), encoding='utf-8')
        v = cp.get('pdf', 'critical_color', fallback='gray').strip().lower()
        return v if v in ('gray', 'rgb') else 'gray'
    except Exception:
        return 'gray'


def save_pdf_settings(trim_threshold, head_pages, tail_pages):
    """يحفظ حد القص وعدد صفحات البداية/النهاية (من شاشة الأدمن). يرجع (ok, رسالة)."""
    if not is_admin():
        return False, 'غير مخوّل'
    try:
        vals = [int(trim_threshold), int(head_pages), int(tail_pages)]
    except (TypeError, ValueError):
        return False, 'القيم يجب أن تكون أرقامًا'
    if min(vals) < 1:
        return False, 'القيم يجب أن تكون 1 فأكثر'
    if vals[1] + vals[2] > vals[0]:
        return False, 'مجموع صفحات البداية والنهاية يجب ألا يزيد عن حد القص'
    path = os.path.join(_app_dir(), _NET_INI_NAME)
    try:
        get_proxy_url()  # يضمن وجود الملف
        cp = configparser.ConfigParser()
        cp.read(path, encoding='utf-8')
        if not cp.has_section('pdf'):
            cp.add_section('pdf')
        for k, v in zip(('trim_threshold', 'head_pages', 'tail_pages'), vals):
            cp.set('pdf', k, str(v))
        with open(path, 'w', encoding='utf-8') as f:
            cp.write(f)
        return True, 'تم الحفظ'
    except Exception as e:
        return False, f'تعذر الحفظ: {e}'


def compute_timeout(pages):
    c = get_pdf_settings()
    return min(c['base_timeout'] + c['per_page_timeout'] * max(pages, 0), c['max_timeout'])


def _thread_ctx():
    """ما يلزم نقله لخيط المهلة: رصيد المحاولات المشترك ونوع العمل في العدّاد (واجهة/خلفية/طابور)."""
    import gemini_quota
    return {'budget': attempt_budget(), 'mode': gemini_quota.current_mode()}


def _apply_ctx(ctx):
    import gemini_quota
    _BUDGET.b = ctx.get('budget')
    gemini_quota.set_mode(ctx.get('mode'))


def _call_with_timeout(fn, timeout):
    """ينفذ fn بخيط مستقل؛ لو تجاوز المهلة يُهمل الطلب ويرفع TimeoutError."""
    box = {}
    ctx = _thread_ctx()

    def run():
        _apply_ctx(ctx)
        try:
            box['r'] = fn()
        except BaseException as e:  # noqa
            box['e'] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f'انتهت مهلة الطلب ({timeout}s) timeout')
    if 'e' in box:
        raise box['e']
    return box['r']


def cleanup_temp_pdfs(max_age_hours=1):
    """يمسح بقايا الملفات المؤقتة (expert_*.pdf) لو بقي منها شيء بعد إغلاق مفاجئ.
    الملف الأصلي للصحيفة/الحكم لا يُمس أبدًا."""
    import tempfile
    import glob
    try:
        for p in glob.glob(os.path.join(tempfile.gettempdir(), 'expert_*.pdf')):
            if time.time() - os.path.getmtime(p) > max_age_hours * 3600:
                os.remove(p)
    except Exception:
        pass


def prepare_pdf(pdf_path, trim=False, pages=None, critical=False):
    """يجهّز الـPDF قبل الإرسال بواسطة PyMuPDF:
      - pages: أرقام صفحات (من 0) تُرسل فقط، مثل (1, 2) للصفحتين الثانية والثالثة؛
        لو الملف أقصر منها تُرسل كل الصفحات.
      - trim: لو الصفحات > trim_threshold نأخذ أول head_pages وآخر tail_pages.
      - طبقة نصية موجودة → يرجع النص المستخرج بدل الملف.
      - ممسوح ضوئيًا → صفحات رمادية 150DPI JPEG جودة 70 تُعاد لـPDF واحد.
      - critical=True (مستند حاسم): تُرسل الصفحات صوراً دائماً (حتى مع طبقة نصية) بـcritical_dpi وcritical_jpeg_quality
        ولون critical_color، ويُخفَّض الـdpi ثم الجودة فقط إن تجاوز الملف critical_max_mb.
    يرجع dict: kind('text'|'pdf'), text, path, temp, orig_pages, sent_pages,
    size_before, size_after. عند أي فشل يرجع الملف الأصلي كما هو."""
    size_before = os.path.getsize(pdf_path)
    fallback = {'kind': 'pdf', 'text': '', 'path': pdf_path, 'temp': False,
                'orig_pages': 0, 'sent_pages': 0,
                'size_before': size_before, 'size_after': size_before}
    try:
        import fitz
        c = get_pdf_settings()
        doc = fitz.open(pdf_path)
        n = doc.page_count
        fallback['orig_pages'] = fallback['sent_pages'] = n
        idx = list(range(n))
        if pages:
            picked = [i for i in pages if 0 <= i < n]
            if picked:
                idx = picked
        elif trim and n > c['trim_threshold']:
            h, t = c['head_pages'], c['tail_pages']
            idx = list(range(h)) + list(range(n - t, n))
        texts = [doc[i].get_text().strip() for i in idx]
        info = dict(fallback, orig_pages=n, sent_pages=len(idx), idx=idx)
        if not critical and sum(len(x) for x in texts) >= c['min_text_chars_per_page'] * len(idx):
            body = '\n\n'.join(f'--- صفحة {i + 1} ---\n{x}' for i, x in zip(idx, texts))
            doc.close()
            return dict(info, kind='text', text=body, path='', size_after=len(body.encode('utf-8')))
        import tempfile
        if critical:
            dpi, q = c['critical_dpi'], c['critical_jpeg_quality']
            cs = fitz.csRGB if get_critical_color() == 'rgb' else fitz.csGRAY
            cap = c['critical_max_mb'] * 1024 * 1024
        else:
            dpi, q, cs, cap = c['scan_dpi'], c['jpeg_quality'], fitz.csGRAY, None
        while True:
            out = fitz.open()
            for i in idx:
                page = doc[i]
                pix = page.get_pixmap(dpi=dpi, colorspace=cs)
                jpg = pix.tobytes('jpeg', jpg_quality=q)
                new = out.new_page(width=page.rect.width, height=page.rect.height)
                new.insert_image(new.rect, stream=jpg)
                try:   # صفحة مقلوبة/جانبية: دوران الصفحة ليراها الذكاء والـOCR مستقيمة
                    import page_orient
                    rot = page_orient.rotation_needed(pix.tobytes('png'))
                    if rot:
                        new.set_rotation(rot)
                        _log(ROUTE_PROXY, 'ORIENT', note=f'صفحة {i + 1}: دُوّرت {rot}° لتصير مستقيمة')
                except Exception:
                    pass
            fd, tmp = tempfile.mkstemp(suffix='.pdf', prefix='expert_')
            os.close(fd)
            out.save(tmp, garbage=4, deflate=True)
            out.close()
            if cap is None or os.path.getsize(tmp) <= cap or (dpi <= 150 and q <= 60):
                break
            os.remove(tmp)                       # أكبر من السقف: خفّض dpi أولاً (حتى 150) ثم الجودة
            if dpi > 150:
                dpi = max(150, dpi - 50)
            else:
                q -= 10
        doc.close()
        after = os.path.getsize(tmp)
        if not critical and after >= size_before and len(idx) == n:
            os.remove(tmp)  # الضغط ما أفاد ولا قصينا شيء → الأصلي
            return info
        return dict(info, path=tmp, temp=True, size_after=after)
    except Exception as e:
        _log(ROUTE_PROXY, 'PREP-FAIL', error=e, note='أُرسل الملف الأصلي')
        return fallback


OCR_TEXT_NOTE = (
    "\n\nملاحظة: المستند التالي نص مستخرج آليًا (OCR) من الصفحات المذكورة فقط، "
    "وقد يحتوي أخطاء قراءة. صحّح هذه الأخطاء تلقائيًا بناءً على سياق الجملة قبل "
    "الاستخراج: حروف متشابهة أو ناقصة (مثل ة/ه، ى/ي، أ/ا، \"نيس الدائرة\" = \"رئيس الدائرة\")، "
    "كلمات ملتصقة أو مفصولة، علامات زائدة. لا تخترع معلومة غير موجودة، ولا تغيّر "
    "أرقام القضايا أو التواريخ أو المبالغ إلا إذا كان الخطأ واضحًا من السياق "
    "(مثل شهر 13 أو تاريخ حضور قبل تاريخ الحكم). "
    "اكتب كل الأرقام والتواريخ بالأرقام الإنجليزية (0-9) "
    "حتى لو كانت في النص بالأرقام العربية الهندية.\n\n")


def local_text_for(prep, pdf_path, purpose):
    """OCR الداخلي (بلا إنترنت) للصفحات الممسوحة. يرجع النص إن كان يكفي لهذا الغرض، وإلا ''.
      - summary: أي قراءة غير منهارة تكفي — النموذج يلخّص رغم أخطاء القراءة، والطلب نص صغير سريع بدل صور.
      - extract: فقط إن كانت أرقام الصفحات إنجليزية ولا جدول ولا صفحة ضعيفة. الأرقام الهندية يخطئ فيها المحرّك
        الداخلي كثيراً (11 من 38 صحيحة بأحكام حقيقية)، فالتواريخ وأرقام القضايا تبقى لـOCR.space أو الذكاء.
    أي فشل في المحرّك → '' ويكمل المسار القديم كما هو."""
    # الاستخراج: صفحة واحدة بأرقام هندية/جدول/قراءة ضعيفة تكفي لترك OCR الداخلي — نتوقف فوراً بدل قراءة البقية
    # (حكم 6 صفحات: 42ث ضائعة قبل OCR.space، بدل ~7ث)
    if not feature_on('ocr_internal'):
        return ''
    stop = None if purpose == 'summary' else (lambda pg: pg.digits == 'indic' or pg.weak or pg.table)
    try:
        import local_ocr
        res = local_ocr.read_pages(pdf_path, prep['idx'], stop=stop)
    except Exception as e:
        _log(_net_state['route'], 'LOCAL-FAIL', error=e, note='→ المسار المعتاد')
        return ''
    weak, tables = res.weak, res.tables
    note = (f"OCR داخلي: {len(res.pages)} صفحة في {res.seconds:.1f}ث"
            f"{' (توقف مبكراً)' if res.stopped else ''} | أرقام "
            f"{'هندية' if res.indic else 'إنجليزية'} | ضعيفة {weak or '-'} | جداول {tables or '-'}")
    if purpose == 'summary':
        ok = len(weak) < len(res.pages)
    else:
        ok = not res.stopped and not res.indic and not weak and not tables
    _log(_net_state['route'], 'LOCAL-OK' if ok else 'LOCAL-SKIP', len(res.text.encode('utf-8')),
         note=note + (' → يُعتمد' if ok else ' → OCR.space/الذكاء'))
    return res.text if ok else ''


def _pages_label(idx):
    """[0, 5, 6] → "1 و6 و7"."""
    return ' و'.join(str(i + 1) for i in idx or [])


_BROWSER_HINT = ' — عبر Chrome؛ إن ظهر تحقق «هل أنت إنسان» أنجزه في نافذة Chrome (إلغاء العملية يوقفه)'


_read_tls = threading.local()


def last_read():
    """معلومات آخر قراءة PDF في هذا الخيط: {'engine','label','skipped':[(محرّك، سبب)],'critical'} أو None."""
    return getattr(_read_tls, 'info', None)


def _set_read(engine, skipped, critical):
    labels = {'gemini': 'Gemini', 'external_ocr': 'OCR خارجي', 'local': 'OCR المحلي', 'text_layer': 'الطبقة النصية',
              'cloud_vision': 'Google Cloud Vision'}
    _read_tls.info = {'engine': engine, 'label': labels.get(engine, engine), 'critical': critical,
                      'skipped': [list(x) for x in skipped]}


def generate_from_pdf(prompt, pdf_path, trim=False, pages=None, purpose='extract', force_ai=False, status=None,
                      critical=False, task=None):
    """critical=True (حكم الإحالة وأمثاله): Gemini أولاً على صور عالية الجودة، ثم المسار المعتاد؛ والمحرّك الفعلي وسبب
    تخطي Gemini في last_read() ليُفصَح عنه بتنبيه أحمر. التفاصيل أدناه للمسار المعتاد."""
    _read_tls.info = None
    skipped = []
    if critical:
        import ai_providers
        import provider_sync
        provider_sync.refresh()
        cleanup_temp_pdfs()
        gem = [p for p in ai_providers.build_chain() if isinstance(p, ai_providers.GeminiProvider)]
        if not gem:
            skipped.append(('gemini', 'لا مفتاح Gemini مضبوط'))
        else:
            hq = prepare_pdf(pdf_path, trim=trim and not force_ai, pages=None if force_ai else pages, critical=True)
            try:
                if hq['kind'] != 'pdf':
                    raise RuntimeError('تعذّر تحضير الصور عالية الجودة')
                t = max_timeout = get_pdf_settings()['max_timeout']
                resp = ai_providers.run_chain(lambda p, route: p.generate(prompt, hq, route, t),
                                              hq['size_after'], max_timeout, chain=gem)
                _set_read('gemini', skipped, True)
                return resp
            except ai_providers.PersonalKeyFailure:
                raise                               # مفتاحك الشخصي فشل: توقف واسأل الخبير، لا مسار احتياطي صامت
            except Exception as e:
                skipped.append(('gemini', f'فشل: {short_error(e)}'))
            finally:
                if hq.get('temp'):
                    try:
                        os.remove(hq['path'])
                    except OSError:
                        pass
    resp = _generate_standard(prompt, pdf_path, trim, pages, purpose, force_ai, status, skipped, critical, task)
    return resp


def _generate_standard(prompt, pdf_path, trim, pages, purpose, force_ai, status, skipped, critical, task=None):
    """المسار المعتاد (نص ← OCR ← مزوّدات)، ويسجّل مصدر القراءة في last_read().
    يرجع response فيه .text. الترتيب:
      1) نختار الصفحات (pages، أو القص: الأولى + الأخيرتان حسب إعدادات [pdf]).
      2) فيه طبقة نصية → النص مباشرة. ممسوح → OCR الداخلي على الجهاز إن كفى للغرض (local_text_for)،
         وإلا OCR.space.
      3) النص → Groq ← z.ai ← Gemini (أول من ينجح).
      4) لا يوجد OCR أو فشل (خطأ/صفحة فاضية/مقلوبة/الحد) → صور الصفحات بنفس الترتيب
         Gemini (PDF واحد) ← Groq ← z.ai. Gemini أولًا للصور لأن القراءة المقسّمة
         بنماذج الرؤية المجانية أعطت بيانات خاطئة (رقم قضية من تذييل الصفحة).
    force_ai: «قراءة كاملة بالذكاء» من إعادة المحاولة — كل صفحات الملف (بلا قص)، بلا OCR داخلي ولا OCR.space:
      الممسوح يُرسل صورًا مباشرة (Gemini أولًا)، وذو الطبقة النصية نصه كاملًا.
    status(نص): يُبلَّغ بكل خطوة فعلية (لنافذة التقدم) — من يقرأ، أي صفحات، أي مزود."""
    import ai_providers
    import ocr_space
    import provider_sync
    say = status or (lambda _t: None)

    def text_chain():                 # task (مزوّد كل مهمة) إن عُيِّنت وإلا السلسلة التلقائية القديمة
        return ai_providers.build_task_chain(task) if task else ai_providers.build_text_chain()

    def image_chain():
        if task and ai_providers.get_task_specs().get(task, 'auto') != 'auto':
            return ai_providers.build_task_chain(task)
        return ai_providers.build_image_chain()
    provider_sync.refresh()  # آخر تفعيل/إيقاف من الأدمن قبل كل استخراج (فشل → النسخة المحلية)
    cleanup_temp_pdfs()
    prep = prepare_pdf(pdf_path, trim=trim and not force_ai, pages=None if force_ai else pages)
    timeout = compute_timeout(prep['sent_pages'] or prep['orig_pages'])
    pages_txt = _pages_label(prep.get('idx'))
    _log(_net_state['route'], 'PREP', prep['size_after'], note=(
        f"صفحات: أصلي {prep['orig_pages']} → مُرسَل {prep['sent_pages']} | "
        f"حجم: {_fmt_size(prep['size_before'])} → {_fmt_size(prep['size_after'])} | "
        f"{'نص مستخرج' if prep['kind'] == 'text' else 'ممسوح'}" + (' | قراءة كاملة بالذكاء' if force_ai else '')))

    def text_call(p, route):
        say(f"{p.name} يستخرج المعلومات من النص (الصفحات {pages_txt})" + _BROWSER_HINT * (p.name == 'Browser'))
        return p.generate(prompt + OCR_TEXT_NOTE, tprep, route, timeout)

    def image_call(p, route):
        say(f"{p.name} يقرأ صور الصفحات {pages_txt} مباشرة" + _BROWSER_HINT * (p.name == 'Browser'))
        return p.generate(prompt, prep, route, img_timeout)

    try:
        text = prep['text'] if prep['kind'] == 'text' else ''
        src = None
        if prep['kind'] == 'text':
            src = 'text_layer'
            say(f"الملف فيه نص جاهز — لا حاجة لقراءة الصور (الصفحات {pages_txt})")
        if not text and prep.get('idx') is not None and not force_ai:
            say(f"قراءة داخلية على الجهاز (الصفحات {pages_txt})")
            text = local_text_for(prep, pdf_path, purpose)
            if text:
                src = 'local'
        if not text and prep.get('idx') is not None and not force_ai:
            try:
                import ocr_vision
                if ocr_vision.is_available():         # OCR رقم 1 = Google Cloud Vision
                    say(f"Google Cloud Vision يقرأ الصفحات {pages_txt}")
                    set_log_provider('Google Cloud Vision', 'key')
                    text = _run_with_routes(lambda route: ocr_vision.ocr_pages(pdf_path, prep['idx'], route),
                                            prep['size_after'], timeout)
                    if text:
                        src = 'cloud_vision'
            except Exception as e:
                _log(_net_state['route'], 'OCR-FAIL', error=e, note='Vision → OCR.space')
                text = ''
        if not text and prep.get('idx') is not None and not force_ai and feature_on('ocr_external'):
            say(f"OCR.space يقرأ الصفحات {pages_txt} (الأرقام هندية أو القراءة الداخلية لا تكفي)")
            set_log_provider('OCR.space', ocr_space.get_settings()['key_type'])
            try:
                text = _run_with_routes(
                    lambda route: ocr_space.ocr_pages(pdf_path, prep['idx'], route),
                    prep['size_after'], timeout)
            except Exception as e:
                _log(_net_state['route'], 'OCR-FAIL', error=e, note='→ الصور للمزودات مباشرة')
                say("تعذّر OCR.space — إرسال صور الصفحات للذكاء مباشرة")
                text = ''
            if text:
                src = 'external_ocr'
        if text:
            tprep = dict(prep, kind='text', text=text)
            try:
                r = ai_providers.run_chain(text_call, len(text.encode('utf-8')), timeout,
                                           chain=text_chain())
                _set_read(src or 'local', skipped, critical)
                return r
            except ai_providers.PersonalKeyFailure:
                raise
            except Exception:
                if prep['kind'] == 'text':
                    raise
                _log(_net_state['route'], 'TEXT-FAIL', note='فشلت مزودات النص → الصور للمزودات')
                say("فشل الاستخراج من النص — إرسال صور الصفحات للذكاء مباشرة")
        img_timeout = get_pdf_settings()['max_timeout']
        r = ai_providers.run_chain(image_call, prep['size_after'], img_timeout,
                                   chain=image_chain())
        prov = getattr(r, 'provider', '') or 'unknown'
        _set_read('gemini' if prov.lower().startswith('gemini') else prov, skipped, critical)
        return r
    finally:
        if prep['temp']:
            try:
                os.remove(prep['path'])
            except OSError:
                pass


def _run_with_routes(fn, size, timeout):
    """fn(route) → response. مهلة لكل محاولة؛ عند تجاوزها أو فشل الاتصال: إعادة مرة ثم الطريق الآخر. أخطاء Gemini غير
    الاتصالية تمر كما هي. رصيد محاولات واحد للطلب (MAX_ATTEMPTS) يتشاركه هذا المستوى ونماذج Gemini (_generate_on_client):
    طلب انتهت مهلته يُحتسب، والمحاولة التالية تذهب للنموذج التالي (النموذج الذي علّق في b.bad)."""
    first = _net_state['route']
    last_net_error = None
    b = attempt_budget()
    own = b is None
    if own:
        b = _Budget()
        _BUDGET.b = b
    try:
        for route, tries in ((first, 2), (_other(first), 1)):
            for attempt in range(tries):
                if b.left <= 0 and last_net_error is not None:
                    raise RuntimeError(USER_FAIL_MSG) from last_net_error
                t0 = time.time()
                b.current = ''
                try:
                    resp = _call_with_timeout(lambda: fn(route), timeout)
                    dur = time.time() - t0
                    _log(route, 'OK', size, note=_dur_note(dur, timeout))
                    _adopt_route(route, first)
                    return resp
                except Exception as e:
                    dur = time.time() - t0
                    _log(route, 'FAIL', size, e,
                         note=f'محاولة {attempt + 1} {_dur_note(dur, timeout)} {diagnose_error(e)}')
                    if not _is_network_error(e):
                        _adopt_route(route, first)  # وصلنا للسيرفر = الطريق شغّال
                        raise
                    if b.current:
                        b.bad.add(b.current)        # علّق/انقطع على هذا النموذج: المحاولة التالية للتالي في السلسلة
                    last_net_error = e
                    if attempt + 1 < tries:
                        (SLEEP or time.sleep)(1)
        raise RuntimeError(USER_FAIL_MSG) from last_net_error
    finally:
        if own:
            _BUDGET.b = None


def _dur_note(dur, timeout):
    flag = ' ⚠️بطيء' if dur >= SLOW_SECONDS else ''
    return f'⏱ {dur:.1f}s/{timeout}s{flag}'


def generate_content_with_fallback(client, own_only=False, **kwargs):
    """الواجهة المعتادة (نفس التوقيع) للطلبات النصية. مهلة 60 ثانية."""
    import ai_providers
    contents = kwargs.get('contents')
    contents = contents if isinstance(contents, (list, tuple)) else [contents]
    timeout = get_pdf_settings()['base_timeout']
    return ai_providers.run_chain(lambda p, route: p.generate_text(contents, route, timeout),
                                  _payload_size(contents), timeout, own_only=own_only,
                                  chain=None if own_only else ai_providers.build_text_chain())


def mask_key(key):
    """نسخة مموهة من المفتاح للعرض فقط بالواجهة (لا تُستخدم بأي استدعاء فعلي)"""
    if not key or len(key) < 16:       # مفتاح قصير: التمويه بـ4+4 يكشف معظمه، فلا يُعرض منه شيء
        return ''
    return f"{key[:4]}...{key[-4:]}"
