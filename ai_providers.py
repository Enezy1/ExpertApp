# ===== ai_providers.py — طبقة مزودات الذكاء الاصطناعي الموحدة (Gemini + احتياطي) =====
"""
كل مزود يأخذ نفس المدخلات (التعليمات + الملف المُجهَّز من prepare_pdf) ويرجع
كائنًا فيه .text — نفس شكل رد Gemini الذي يعتمد عليه باقي التطبيق.

ترتيب الاستخدام: مفتاح المستخدم الخاص (Gemini) ← Gemini الافتراضي ← المزودات
الاحتياطية بترتيب الأولوية. كل مزود يمر على منطق الطريق (إعادة + تبديل
بروكسي/مباشر) في gemini_config._run_with_routes قبل الانتقال للمزود التالي.

إعدادات المزودات (العنوان، النموذج، المفتاح، التفعيل، الأولوية، حدود الصور)
تُقرأ من get_provider_configs() — من gemini_network.ini حاليًا، ومن Supabase
لاحقًا. لا يوجد أي عنوان أو اسم نموذج مكتوب داخل منطق المزودات.

إضافة مزود جديد متوافق مع OpenAI = صف إعدادات فقط (kind=openai).
مزود بواجهة مختلفة = كلاس يرث Provider ويُسجَّل في PROVIDER_KINDS.
"""
import base64
import configparser
import os
import re
import threading
import time

import gemini_config as gc

KEY_OWN = 'خاص'
KEY_DEFAULT = 'افتراضي'


class AIResponse:
    """نفس الشكل المستخدم من رد Gemini (response.text)."""
    def __init__(self, text, provider=''):
        self.text = text
        self.provider = provider


class Provider:
    """الواجهة الموحدة. generate(prompt, prep, route, timeout) → AIResponse."""
    def __init__(self, name, api_key, key_type=KEY_DEFAULT, model='', base_url='', **opts):
        self.name = name
        self.api_key = api_key
        self.key_type = key_type
        self.model = model
        self.base_url = base_url
        self.opts = opts
        self._cancel = getattr(_tls, 'cancel_event', None)   # حدث إلغاء مهمتي فقط (لا مهمة غيري)

    def generate(self, prompt, prep, route, timeout):
        raise NotImplementedError

    def generate_files(self, prompt, paths, route, timeout):
        """طلب نصي ومعه ملفات PDF (إعادة قراءة مستند في طلب البحث). المزوّد بلا دعم عدة ملفات: ملف واحد فقط."""
        if len(paths) == 1:
            return self.generate(prompt, {'kind': 'pdf', 'path': paths[0]}, route, timeout)
        raise NotImplementedError(f'{self.name}: لا يدعم إرسال عدة ملفات في طلب واحد')


def _upload_ascii(client, path):
    """رفع ملف إلى Gemini باسم إنجليزي مؤقت: مكتبة google-genai تضع اسم الملف في ترويسة HTTP (ASCII فقط)،
    فالاسم العربي («حكم المحكمة الكلية….pdf») كان يفشل بـ'ascii' codec can't encode."""
    import shutil
    import tempfile
    try:
        os.path.basename(path).encode('ascii')
        return client.files.upload(file=path)
    except UnicodeEncodeError:
        pass
    tmp = tempfile.mkdtemp(prefix='gem_up_')
    try:
        dst = os.path.join(tmp, 'document' + (os.path.splitext(path)[1].lower() or '.pdf'))
        shutil.copyfile(path, dst)
        return client.files.upload(file=dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class GeminiProvider(Provider):
    """Gemini: نص مستخرج أو PDF واحد (بعد القص والضغط) — لا صور منفصلة. النموذج حسب المهمة (self.task ← MODEL_ROUTES:
    ocr / text_light / write / research) وما يتيحه المفتاح وما بقي من حصته (gc.task_candidates)، ويُحفظ اسمه الفعلي في
    last_model لـ«كُتب بواسطة» والسجل. بلا مهمة ← write."""
    task = ''

    def _models(self, client, contents=None, media=False):
        return gc.task_candidates(client, self.api_key, self.task or 'write',
                                  tokens=_estimate(contents), media=media)

    def _done(self, resp):
        used, _fb = gc.last_model_used()
        fallback = (self.task or 'write') in FALLBACK_TASKS and gc.is_fallback(used)
        self.last_model = gc.describe_model(used, fallback) or self.model or ''
        self.fallback = fallback
        return AIResponse(resp.text or '', self.name)

    def _run(self, client, models, contents):
        # بلا أي إعداد تفكير (thinking_budget…) في أي طلب: Lite وGemma يرفضانه بـ400، والطلب المرفوض يستهلك الحصة
        return gc._generate_on_client(client, models=models, contents=contents)

    def generate(self, prompt, prep, route, timeout):
        client = gc._make_client(route, timeout, api_key=self.api_key)
        if prep['kind'] == 'text':
            contents = [prompt, prep['text']]
            models = self._models(client, contents)
        else:
            models = self._models(client, [prompt], media=True)       # قبل الرفع: لا رفع بلا نموذج متاح
            contents = [prompt, _upload_ascii(client, prep['path'])]
        return self._done(self._run(client, models, contents))

    def generate_text(self, contents, route, timeout):
        client = gc._make_client(route, timeout, api_key=self.api_key)
        return self._done(self._run(client, self._models(client, contents), contents))

    def generate_files(self, prompt, paths, route, timeout):
        client = gc._make_client(route, timeout, api_key=self.api_key)
        models = self._models(client, [prompt], media=True)                # قبل الرفع: لا رفع بلا نموذج متاح
        contents = [prompt] + [_upload_ascii(client, p) for p in paths]
        return self._done(self._run(client, models, contents))


def _estimate(contents):
    import gemini_quota
    return gemini_quota.estimate_tokens(contents or [])


# ===== توجيه نماذج Gemini حسب المهمة (2026-10-23، الخطة المجانية 2026-10-25) =====
# لكل مهمة سلسلة نماذج بأسمائها الفعلية من list_models (gc.rank)، قابلة للتعديل من [gemini_routing] في gemini_network.ini.
# لكل نموذج حصة مستقلة (المفتاح المجاني): Lite 3.5 و3.1 = 500/يوم لكل منهما؛ Flash 3.8 و3.6 و3 و2.5 = 20/يوم لكل منها.
#   ocr        تحويل الممسوح إلى markdown: Lite 3.5 ← 3.1.
#   text_light الفرز والملخص والمأمورية وتفاصيل العقد والحضور والإجراءات: Lite 3.5 ← 3.1.
#   write      الموضوع والإجراءات والمرفقات: Flash 3.6.
#   research   تقرير البحث والنتيجة: أعلى نموذج متاح (top = Pro إن أتاحه المفتاح، ثم Flash 3.8). 3.8 محجوز لهذه المهمة.
# الملاذ الأخير فقط حين يتعذّر المحدَّد تماماً (FALLBACK_ROUTES): بقية Flash (3 ثم 2.5) للكتابة والبحث، وLite آخراً للكتابة
# وحدها — البحث لا يهبط إلى Lite أبداً. ما كتبه نموذج احتياطي يُعلَّم في «كُتب بواسطة» (gc.describe_model).
# الصيغة: عائلة (lite | flash | pro | top | gemma) أو عائلة:إصدار (lite:3.5، flash:3.6) أو اسم نموذج صريح أو اسم مهمة أخرى.
# Gemma خارج الخطة (غير مستقر)؛ يبقى ممكناً بذكره صراحةً فقط. Pro و3.8 لا يدخلان غير research مهما كُتب.
MODEL_ROUTES = {'ocr': 'lite:3.5,lite:3.1', 'text_light': 'lite:3.5,lite:3.1', 'write': 'flash:3.6', 'research': 'top'}
FALLBACK_ROUTES = {'write': 'flash:3,flash:2.5,lite:3.5,lite:3.1', 'research': 'flash:3,flash:2.5'}
FALLBACK_TASKS = ('write', 'research')
RESEARCH_ONLY = {('flash', '3.8')}
TASK_MODEL = {'extract': 'text_light', 'summarize': 'text_light', 'write': 'write', 'research': 'research'}
GEMMA_MAX_TOKENS = 10_000
TRIAGE_BATCH_CHARS = 80_000            # إعادة الفرز المجمّعة: حجم الدفعة الواحدة ([gemini_routing] triage_batch_chars)
ROUTES_VERSION = 2                     # 2 = الخطة المجانية (لا Gemma، Lite للنسخ والفرز، 3.6 للكتابة، 3.8 للبحث)
_OLD_DEFAULTS = {'ocr': 'lite,flash', 'text_light': 'gemma,lite,flash', 'write': 'flash,lite', 'research': 'top'}
_ROUTE_SECTION = 'gemini_routing'


def _route_ini():
    cp = configparser.RawConfigParser()
    try:
        cp.read(os.path.join(gc._app_dir(), gc._NET_INI_NAME), encoding='utf-8')
    except Exception:
        return {}
    return {k.lower(): v.strip() for k, v in cp.items(_ROUTE_SECTION)} if cp.has_section(_ROUTE_SECTION) else {}


def get_model_routes():
    """{مهمة: سلسلة، مهمة_fallback: سلسلة} — الافتراضي + [gemini_routing]. قيم الافتراضي القديم (قبل routes_version 2:
    Gemma وFlash للنسخ…) تُتجاهل فلا يبقى ملف قديم على الخطة السابقة."""
    out = dict(MODEL_ROUTES)
    out.update({f'{t}_fallback': v for t, v in FALLBACK_ROUTES.items()})
    ini = _route_ini()
    try:
        old = int(float(ini.get('routes_version', 1))) < ROUTES_VERSION
    except (TypeError, ValueError):
        old = True
    for k in list(out):
        v = ini.get(k)
        if v and not (old and _OLD_DEFAULTS.get(k) == v):
            out[k] = v
    return out


def gemma_max_tokens():
    try:
        return int(float(_route_ini().get('gemma_max_tokens', GEMMA_MAX_TOKENS)))
    except (TypeError, ValueError):
        return GEMMA_MAX_TOKENS


def triage_batch_chars():
    try:
        return max(5_000, int(float(_route_ini().get('triage_batch_chars', TRIAGE_BATCH_CHARS))))
    except (TypeError, ValueError):
        return TRIAGE_BATCH_CHARS


def _spec_models(task, spec, names, pro_ok, tokens, media, gemma_max):
    out = []
    for tok in [x.strip().lower() for x in (spec or '').split(',') if x.strip()]:
        fam, _sep, ver = tok.partition(':')
        vers = (ver,) if ver else None
        if fam == 'gemma':
            got = [] if media or (tokens or 0) > gemma_max else gc.rank_gemma(names)[:2]
        elif fam in ('lite', 'flash'):
            got = gc.rank(names, fam, vers)
        elif fam == 'pro':
            got = gc.rank(names, 'pro', vers)[:2] if (task == 'research' and pro_ok) else []
        elif fam == 'top':
            got = (gc.rank_pro(names)[:1] if pro_ok and task == 'research' else []) + gc.rank(names, 'flash', ('3.8',))
        else:
            got = [n for n in names if str(n).lower() == tok]           # اسم نموذج صريح
        out += got
    return out


def route_models(task, names, pro_ok=False, tokens=0, media=False, routes=None, gemma_max=None, fallback=True):
    """أسماء النماذج الفعلية لمهمة بالترتيب من قائمة نماذج المفتاح (بلا شبكة — دالة نقية تُختبر). fallback=False ←
    النماذج المحددة للمهمة وحدها (ما بعدها «نموذج احتياطي»). قيود ثابتة: Pro و3.8 للبحث وحده، والبحث لا يهبط إلى Lite/Gemma."""
    routes = routes or get_model_routes()
    gemma_max = gemma_max_tokens() if gemma_max is None else gemma_max
    spec = (routes.get(task) or routes.get('write') or MODEL_ROUTES['write']).strip()
    if spec in MODEL_ROUTES and spec != task:            # «write = text_light»: سلسلة مهمة أخرى كما هي
        spec = (routes.get(spec) or MODEL_ROUTES[spec]).strip()
    got = _spec_models(task, spec, names, pro_ok, tokens, media, gemma_max)
    if fallback:
        fb = routes.get(f'{task}_fallback', FALLBACK_ROUTES.get(task, ''))
        got += _spec_models(task, fb, names, pro_ok, tokens, media, gemma_max)
    out = []
    for m in got:
        fam, ver, _p = gc.model_family(m)
        if task != 'research' and (fam == 'pro' or (fam, ver) in RESEARCH_ONLY):
            continue
        if task == 'research' and fam in ('lite', 'gemma'):
            continue
        if m not in out:
            out.append(m)
    return out


PRO_TASKS = ('research',)          # Pro (إن أتاحه المفتاح) للبحث والنتيجة فقط — بقية المهام حسب MODEL_ROUTES


class OpenAICompatProvider(Provider):
    """أي API متوافق مع OpenAI (z.ai، Groq، ...). الصفحات تُرسل كصور JPEG،
    وتُقسَّم على عدة طلبات حسب max_images و max_image_kb ثم تُجمع النتائج بالترتيب."""
    def _post(self, messages, route, timeout):
        import requests
        s = requests.Session()
        proxy = gc.get_proxy_url()
        if route == gc.ROUTE_DIRECT or proxy:
            s.trust_env = False
        if route == gc.ROUTE_PROXY and proxy:
            s.proxies = {'http': proxy, 'https': proxy}
        try:
            for attempt in range(3):
                r = s.post(self.base_url.rstrip('/') + '/chat/completions',
                           headers={'Authorization': f'Bearer {self.api_key}'},
                           json=self._body(messages),
                           timeout=timeout, verify=_ca_bundle())
                wait = _rate_limit_wait(r)
                if wait is None or attempt == 2:
                    break
                time.sleep(wait)  # حد الطلبات بالدقيقة (الخطة المجانية) — ننتظر ونعيد
            if r.status_code >= 400:
                # نص الخطأ من السيرفر فقط — المفتاح لا يظهر فيه
                raise ProviderHTTPError(f'{self.name} HTTP {r.status_code}: {r.text[:500]}')
            return r.json()['choices'][0]['message']['content'] or ''
        finally:
            s.close()

    def _body(self, messages):
        body = {'model': self.model, 'messages': messages}
        if not re.match(r'(o\d|gpt-5)', (self.model or '').lower()):
            body['temperature'] = 0              # نماذج التفكير لدى OpenAI ترفض أي قيمة غير الافتراضية (HTTP 400)
        if 'openrouter.ai' in (self.base_url or ''):
            # OpenRouter يجرّب النماذج بالترتيب تلقائيًا لو الأول مزدحم/محدود مؤقتًا
            body['models'] = [self.model] + [m for m in _OPENROUTER_FALLBACKS if m != self.model]
        if self.opts.get('max_tokens'):
            if re.match(r'(o\d|gpt-5)', (self.model or '').lower()):
                body['max_completion_tokens'] = int(self.opts['max_tokens']) * 4     # نماذج التفكير ترفض max_tokens وتستهلك رموز تفكير
            else:
                body['max_tokens'] = int(self.opts['max_tokens'])
        return body

    def _images(self, prep):
        """صور الصفحات (JPEG رمادي بالـDPI والجودة من الإعدادات)، مع تصغير الصفحة
        لو تجاوزت max_image_kb."""
        import fitz
        c = gc.get_pdf_settings()
        max_kb = int(self.opts.get('max_image_kb') or 3500)
        doc = fitz.open(prep['path'])
        out = []
        try:
            for page in doc:
                dpi, q = int(self.opts.get('dpi') or c['scan_dpi']), c['jpeg_quality']
                while True:
                    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
                    jpg = pix.tobytes('jpeg', jpg_quality=q)
                    if len(jpg) * 4 / 3 <= max_kb * 1024 or dpi <= 90:
                        break
                    dpi -= 20
                out.append(base64.b64encode(jpg).decode('ascii'))
        finally:
            doc.close()
        return out

    def generate(self, prompt, prep, route, timeout):
        if prep['kind'] == 'text':
            return AIResponse(self._post(
                [{'role': 'user', 'content': prompt + '\n\n' + prep['text']}],
                route, timeout), self.name)
        imgs = self._images(prep)
        per = max(1, int(self.opts.get('max_images') or 1))
        try:
            return self._generate_images(prompt, imgs, per, route, timeout)
        except ProviderHTTPError as e:
            # المزود يذكر حده الفعلي ("supports up to 3 images") → نعيد التقسيم عليه
            import re
            m = re.search(r'up to (\d+) images?', str(e), re.I)
            if not m or int(m.group(1)) >= per:
                raise
            self.opts['max_images'] = int(m.group(1))
            return self._generate_images(prompt, imgs, int(m.group(1)), route, timeout)

    def _generate_images(self, prompt, imgs, per, route, timeout):
        chunks = [imgs[i:i + per] for i in range(0, len(imgs), per)]
        if len(chunks) == 1:
            return AIResponse(self._post([_vision_msg(prompt, chunks[0])], route, timeout), self.name)
        # الملف تجاوز حد الصور: نستخرج من كل جزء ثم ندمج بطلب نصي أخير بنفس التعليمات
        parts = []
        for n, ch in enumerate(chunks, 1):
            note = (f'\n\n(هذا الجزء {n} من {len(chunks)} من نفس المستند. '
                    'انقل كل ما يخص التعليمات من هذا الجزء كما هو بدون أي تنسيق.)')
            parts.append(self._post([_vision_msg(prompt + note, ch)], route, timeout))
        merged = '\n\n'.join(f'--- الجزء {i} ---\n{p}' for i, p in enumerate(parts, 1))
        final = (prompt + '\n\nالمستند طويل وتمت قراءته على أجزاء بالترتيب. هذا ما استُخرج '
                 'من كل جزء — ادمجه وأعطِ الرد النهائي بالصيغة المطلوبة أعلاه:\n\n' + merged)
        return AIResponse(self._post([{'role': 'user', 'content': final}], route, timeout), self.name)

    def generate_text(self, contents, route, timeout):
        text = '\n\n'.join(c for c in contents if isinstance(c, str))
        return AIResponse(self._post([{'role': 'user', 'content': text}], route, timeout), self.name)


class UserCancelled(BaseException):
    """المستخدم ألغى العملية — BaseException ليمر عبر run_chain دون الانتقال للمزود التالي."""


_tls = threading.local()


def set_cancel_event(ev):
    """يربط خيط المهمة الحالي بحدث إلغائها — المزودات المنشأة بعده تتوقف حين يُضبط."""
    _tls.cancel_event = ev


class BrowserProvider(Provider):
    """احتياطي بلا API: يشغّل browser-ai-bot (Chrome حقيقي + مواقع دردشة مجانية) في عملية
    منفصلة. يُستخدم آخر السلسلة، وللأرقام الهندية حين لا يكفي OCR. الصور تُرسل صفحة
    صفحة بدقة عالية. البيانات تمر بمواقع خارجية — يُعطَّل من
    [browser_bot] enabled=0 في gemini_network.ini."""
    DEFAULT_DIR = r'C:\Users\Dell\Documents\تلقائي\browser-ai-bot'

    @classmethod
    def bot_dir(cls):
        cp = configparser.ConfigParser()
        d = cls.DEFAULT_DIR
        try:
            cp.read(os.path.join(gc._app_dir(), gc._NET_INI_NAME), encoding='utf-8')
            if not gc.feature_on('browser'):
                return None
            if cp.get('browser_bot', 'enabled', fallback='1').strip().lower() in ('0', 'false', 'no'):
                return None
            d = cp.get('browser_bot', 'path', fallback='').strip() or d
        except Exception:
            pass
        return d if os.path.isfile(os.path.join(d, 'run_job.py')) else None

    def _cancelled(self):
        return bool(self._cancel is not None and self._cancel.is_set())

    def _run(self, prompt, images, timeout):
        import json
        import subprocess
        import sys
        import tempfile
        d = self.bot_dir()
        if not d:
            raise RuntimeError('browser-ai-bot غير متوفر')
        with tempfile.TemporaryDirectory(prefix='expert_bb_') as tmp:
            job, out = os.path.join(tmp, 'job.json'), os.path.join(tmp, 'out.json')
            with open(job, 'w', encoding='utf-8') as f:
                json.dump({'prompt': prompt, 'images': images,
                           'order': self.opts.get('order')}, f, ensure_ascii=False)
            py = 'python' if getattr(sys, 'frozen', False) else sys.executable
            if self._cancelled():
                raise UserCancelled()
            proc = subprocess.Popen([py, 'run_job.py', job, out], cwd=d,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                deadline = time.time() + int(self.opts.get('max_seconds') or 420)
                while proc.poll() is None:
                    if self._cancelled():
                        proc.kill()
                        raise UserCancelled()
                    if time.time() > deadline:
                        proc.kill()
                        raise RuntimeError('انتهت مهلة المتصفح')
                    time.sleep(0.5)
            finally:
                if proc.poll() is None:
                    proc.kill()
            if self._cancelled():
                raise UserCancelled()
            if not os.path.isfile(out):
                raise RuntimeError('browser-ai-bot لم ينتج رداً')
            with open(out, encoding='utf-8') as f:
                res = json.load(f)
        if not res.get('ok'):
            raise RuntimeError(res.get('error') or 'فشل المتصفح')
        return AIResponse(res['reply'], 'browser/' + res.get('provider', ''))

    def generate(self, prompt, prep, route, timeout):
        if prep['kind'] == 'text':
            return self._run(prompt + '\n\n' + prep['text'], [], timeout)
        import fitz
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp(prefix='expert_bbimg_')
        doc = fitz.open(prep['path'])
        try:
            paths = []
            for i, page in enumerate(doc):
                fp = os.path.join(tmp, f'p{i + 1}.png')
                page.get_pixmap(dpi=int(self.opts.get('dpi') or 150)).save(fp)
                paths.append(fp)
            doc.close()
            return self._run(prompt, paths, timeout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def generate_text(self, contents, route, timeout):
        text = '\n\n'.join(c for c in contents if isinstance(c, str))
        return self._run(text, [], timeout)


class ProviderHTTPError(Exception):
    pass


# نماذج مجانية بديلة (تقبل الصور) يجرّبها OpenRouter تلقائيًا بعد النموذج الأساسي
_OPENROUTER_FALLBACKS = ['google/gemma-4-26b-a4b-it:free']


def _rate_limit_wait(r):
    """ثوانٍ للانتظار لو الرد تجاوز حد الدقيقة القابل للانتظار، وإلا None.
    طلب أكبر من الحد نفسه (Requested > Limit) لا يفيده الانتظار."""
    if r.status_code not in (413, 429):
        return None
    t = r.text
    if 'temporarily rate-limit' in t:        # OpenRouter: النموذج المجاني مزدحم عند مزوده مؤقتًا
        return 10
    if 'per minute' not in t and 'rate_limit' not in t:
        return None
    m = re.search(r'Limit (\d+), Requested (\d+)', t)
    if m and int(m.group(2)) > int(m.group(1)):
        return None
    m = re.search(r'try again in (?:(\d+)m)?([\d.]+)s', t)
    secs = (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else 20
    return min(secs + 1, 40)


def _vision_msg(prompt, images_b64):
    content = [{'type': 'text', 'text': prompt}]
    content += [{'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b}'}}
                for b in images_b64]
    return {'role': 'user', 'content': content}


def _ca_bundle():
    """شهادات certifi — التحقق من الشهادات يبقى مفعّلًا."""
    try:
        import certifi
        return certifi.where()
    except Exception:
        return True


# ===== مفتاح OpenAI الشخصي: أقوى نموذج متاح للمفتاح يُختار تلقائياً من قائمة النماذج (بلا اسم ثابت) =====
_OPENAI_SKIP = re.compile(r'(audio|realtime|transcribe|tts|image|search|codex|instruct|embed|moderation|whisper|'
                          r'dall|davinci|babbage|computer|research|-pro|preview|chat-latest|oss|sora|live|diariz)', re.I)
_OPENAI_DATED = re.compile(r'-(\d{4}-\d{2}-\d{2}|\d{4})$')
_OPENAI_GPT = re.compile(r'^gpt-(\d+(?:\.\d+)?)o?(?:-(mini|nano))?$')
_OPENAI_TIER = {None: 3, 'mini': 2, 'nano': 1}


def rank_openai_models(ids, limit=3):
    """معرّفات النماذج الصالحة للمحادثة بالصور، الأقوى أولاً: أحدث إصدار gpt-N ثم الكامل قبل mini قبل nano؛
    الاسم المستعار (بلا تاريخ) قبل اللقطة المؤرَّخة، وتُستبعد الصوتية/الصور/البحث/المعاينة/pro."""
    ids = [i for i in dict.fromkeys(str(x).strip() for x in ids or []) if i]
    aliases = {i.lower() for i in ids if not _OPENAI_DATED.search(i.lower())}
    scored = []
    for i in ids:
        low = i.lower()
        if _OPENAI_SKIP.search(low):
            continue
        base = _OPENAI_DATED.sub('', low)
        if base != low and base in aliases:
            continue                                        # اللقطة المؤرَّخة تُهمَل ما دام اسمها المستعار موجوداً
        m = _OPENAI_GPT.match(base)
        if not m:
            continue
        scored.append((float(m.group(1)), _OPENAI_TIER[m.group(2)], base == low, i))
    scored.sort(reverse=True)
    return [s[3] for s in scored[:limit]]


_openai_models_cache = {}                                    # sha256(key)[:16] → (وقت، [نماذج]) — لا يُخزَّن المفتاح نفسه
_OPENAI_MODELS_TTL = 24 * 3600


class OpenAIOwnProvider(OpenAICompatProvider):
    """ChatGPT بمفتاح الخبير الشخصي: النموذج يُختار من قائمة نماذج المفتاح نفسه (الأقوى المتاح)، ويُجرَّب التالي
    إن رفض المفتاح الوصول لنموذج. الأخطاء الأخرى (مفتاح خاطئ/بلا رصيد) تمرّ كما هي ليُبلَّغ بها الخبير."""

    def _models(self, route, timeout):
        import hashlib
        import requests
        tag = hashlib.sha256(self.api_key.encode('utf-8')).hexdigest()[:16]
        hit = _openai_models_cache.get(tag)
        if hit and time.time() - hit[0] < _OPENAI_MODELS_TTL:
            return hit[1]
        s = requests.Session()
        proxy = gc.get_proxy_url()
        if route == gc.ROUTE_DIRECT or proxy:
            s.trust_env = False
        if route == gc.ROUTE_PROXY and proxy:
            s.proxies = {'http': proxy, 'https': proxy}
        try:
            r = s.get(self.base_url.rstrip('/') + '/models', headers={'Authorization': f'Bearer {self.api_key}'},
                      timeout=timeout, verify=_ca_bundle())
        finally:
            s.close()
        if r.status_code >= 400:
            raise ProviderHTTPError(f'{self.name} HTTP {r.status_code}: {gc.redact(r.text[:300])}')
        ranked = rank_openai_models([m.get('id', '') for m in r.json().get('data') or []])
        if not ranked:
            raise ProviderHTTPError(f'{self.name}: لا يوجد نموذج محادثة متاح لهذا المفتاح')
        _openai_models_cache[tag] = (time.time(), ranked)
        return ranked

    def _post(self, messages, route, timeout):
        last = None
        for m in self._models(route, timeout):
            self.model = m
            try:
                out = super()._post(messages, route, timeout)
                self.last_model = m
                return out
            except ProviderHTTPError as e:
                msg = str(e)
                if re.search(r'HTTP (403|404)', msg) and 'model' in msg.lower():
                    last = e
                    continue
                raise
        raise last or ProviderHTTPError(f'{self.name}: لا نموذج متاح')


# kind → كلاس. مزود بواجهة جديدة غير متوافقة مع OpenAI يُضاف هنا.
PROVIDER_KINDS = {
    'gemini': GeminiProvider,
    'openai': OpenAICompatProvider,
    'browser': BrowserProvider,
}


# ===== الإعدادات =====
_INI_FIELDS = ('kind', 'base_url', 'model', 'api_key', 'enabled', 'priority',
               'max_images', 'max_image_kb', 'dpi', 'max_tokens')


def _local_provider_configs():
    """أقسام [provider:<name>] في gemini_network.ini (للاختبار قبل Supabase)."""
    cp = configparser.ConfigParser()
    try:
        cp.read(os.path.join(gc._app_dir(), gc._NET_INI_NAME), encoding='utf-8')
    except Exception:
        return []
    rows = []
    for sec in cp.sections():
        if not sec.startswith('provider:'):
            continue
        row = {f: cp.get(sec, f, fallback='').strip() for f in _INI_FIELDS}
        row['name'] = sec.split(':', 1)[1].strip()
        row['enabled'] = row['enabled'].lower() not in ('0', 'false', 'no', '')
        row['priority'] = int(row['priority'] or 100)
        rows.append(row)
    return rows


def get_provider_configs():
    """صفوف المزودات (dict) بالمفتاح مفكوكًا: إعدادات القسم من Supabase (أو نسختها
    المحلية المشفرة) تتقدم على ملف الإعدادات المحلي لنفس الاسم."""
    rows = {r['name']: r for r in _local_provider_configs()}
    try:
        import provider_sync
        for r in provider_sync.get_configs():
            local = rows.get(r['name'], {})
            rows[r['name']] = dict(r, api_key=r.get('api_key') or local.get('api_key', ''))
    except Exception:
        pass
    return list(rows.values())


OPENAI_NAME = 'chatgpt'                    # نفس اسم صف القسم (شاشة الأدمن) — تُحجَب نسخته حين يوجد مفتاح شخصي
OPENAI_BASE = 'https://api.openai.com/v1'


def _is_openai_row(r):
    return (r.get('name') or '').lower() == OPENAI_NAME or 'api.openai.com' in (r.get('base_url') or '')


def key_source(which):
    """مصدر مفتاح مزوّد للخبير الحالي: 'own' | 'shared' | 'none'. which: gemini | openai | ocrspace | vision.
    Vision شخصي فقط (لا مفتاح قسم)."""
    import ocr_vision
    own = {'gemini': gc.load_api_key, 'openai': gc.load_openai_key, 'ocrspace': gc.load_ocr_key,
           'vision': ocr_vision.load_key}[which]()
    if own:
        return 'own'
    if which == 'vision':
        return 'none'
    rows = [r for r in get_provider_configs() if r.get('enabled') and r.get('api_key')]
    if which == 'gemini':
        hit = any(r.get('kind') == 'gemini' for r in rows)
    elif which == 'openai':
        hit = any(_is_openai_row(r) for r in rows)
    else:
        hit = any(r['name'] == 'ocrspace' for r in rows)
    return 'shared' if hit else 'none'


KEY_SOURCE_TEXT = {'own': 'يُستعمل مفتاحك',
                   'shared': 'لا يوجد مفتاح شخصي، يُستعمل مفتاح القسم',
                   'none': 'لا يوجد مفتاح'}


def provider_label(p):
    """اسم المزوّد لسطر «كُتب بواسطة»: مع «(مفتاحك)» أو «(مفتاح القسم)»، ومع ملاحظة اختيار الخبير بعد فشل مفتاحه."""
    name = 'ChatGPT' if p.name.lower() == OPENAI_NAME else p.name
    if getattr(p, 'key_type', '') == KEY_OWN:
        label = f'{name} (مفتاحك)'
    elif getattr(p, 'key_type', '') == KEY_DEFAULT and not isinstance(p, BrowserProvider):
        label = f'{name} (مفتاح القسم)'
    else:
        label = name
    ch = get_key_choice()
    if ch and ch.get('use') == 'alt' and not label.startswith(ch['label']):
        label += f" — بدلاً من {ch['label']} (مفتاحك) باختيارك بعد تعذّره"
    elif ch and ch.get('use') == 'section' and getattr(p, 'key_type', '') == KEY_DEFAULT:
        label += ' — باختيارك بعد تعذّر مفتاحك الشخصي'
    elif ch and ch.get('use') == 'retry' and getattr(p, 'key_type', '') == KEY_OWN:
        label += ' — بعد إعادة المحاولة'
    return label


def pop_personal_failures():
    return gc.pop_personal_failures()


def _is_groq(x):
    """Groq (مزوّد أو صف إعدادات) لا يدخل أي سلسلة أبداً: عربيته ضعيفة وحدّه المجاني يُنتج بيانات خاطئة."""
    name = (x.get('name') if isinstance(x, dict) else getattr(x, 'name', '')) or ''
    url = (x.get('base_url') if isinstance(x, dict) else getattr(x, 'base_url', '')) or ''
    return name.lower() == 'groq' or 'groq.com' in url


def build_chain():
    """قائمة المزودات بالترتيب المطلوب. Groq مستبعد دائماً. بعد فشل مفتاح الخبير الشخصي يحكم اختيارُه (get_key_choice):
    'alt' = المزوّد البديل بمفتاحه الشخصي فقط (الفاشل يُستبعد كله بما فيه مفتاح القسم)، 'section' = مفتاح القسم للمزوّد
    الفاشل بموافقته الصريحة، 'retry' = كما هو."""
    chain = []
    api_on = gc.feature_on('api')
    own = gc.load_api_key() if api_on else ''
    own_oa = gc.load_openai_key() if api_on else ''
    skip_kinds = set()
    choice = get_key_choice()
    if choice and choice.get('use') in ('alt', 'section'):
        bad = choice.get('kind')
        if bad == 'gemini':
            own = ''
        elif bad == 'openai':
            own_oa = ''
        if choice['use'] == 'alt':
            skip_kinds.add(bad)
    # مفتاح الخبير الشخصي لمزوّد يُستعمل وحده لذلك المزوّد: مفتاح القسم له يُحجب ولا يُجرَّب (لا انتقال صامت)
    if own:
        chain.append(GeminiProvider('Gemini', own, KEY_OWN))
    if own_oa:
        chain.append(OpenAIOwnProvider(OPENAI_NAME, own_oa, KEY_OWN, '', OPENAI_BASE, max_images=10,
                                       max_image_kb=3500, max_tokens=4000))
    rows = sorted((r for r in get_provider_configs() if api_on and r.get('enabled') and r.get('api_key')),
                  key=lambda r: r['priority'])
    # Gemini الافتراضي دائمًا قبل الاحتياطي
    rows.sort(key=lambda r: (r.get('kind') != 'gemini', r['priority']))
    for r in rows:
        cls = PROVIDER_KINDS.get(r.get('kind') or 'openai')
        if not cls or _is_groq(r):
            continue
        if cls is GeminiProvider and (own or 'gemini' in skip_kinds):
            continue
        if _is_openai_row(r) and (own_oa or 'openai' in skip_kinds):
            continue
        chain.append(cls(r['name'], r['api_key'], KEY_DEFAULT, r.get('model', ''),
                         r.get('base_url', ''), max_images=r.get('max_images'),
                         max_image_kb=r.get('max_image_kb'), dpi=r.get('dpi'), max_tokens=r.get('max_tokens')))
    if own_oa:                                   # Gemini أولاً ثم ChatGPT الشخصي قبل بقية الاحتياطي (أولوية 5 كمزوّد القسم)
        me = next(p for p in chain if isinstance(p, OpenAIOwnProvider))
        chain.remove(me)
        pos = max([i + 1 for i, p in enumerate(chain) if isinstance(p, GeminiProvider)] or [0])
        chain.insert(pos, me)
    if BrowserProvider.bot_dir():  # آخر حلقة: بلا API (أو بعد فشل الكل)
        chain.append(BrowserProvider('Browser', '', KEY_DEFAULT, dpi=150, order=['duckai', 'notrack', 'aifree']))
    return chain


def build_text_chain():
    """لنص مستخرج (OCR/طبقة نصية): الاحتياطي الأرخص أولًا بالأولوية (Groq ثم z.ai)،
    ثم Gemini (مفتاح المستخدم ثم الافتراضي) كآخر خيار."""
    chain = build_chain()
    return ([p for p in chain if not isinstance(p, GeminiProvider)]
            + [p for p in chain if isinstance(p, GeminiProvider)])


def build_image_chain():
    """للصور: Gemini (مفتاح المستخدم ثم الافتراضي) ثم الاحتياطي بالأولوية."""
    chain = build_chain()
    return ([p for p in chain if isinstance(p, GeminiProvider)]
            + [p for p in chain if not isinstance(p, GeminiProvider)])


def has_any_provider():
    return bool(build_chain())


def run_chain(call, size, timeout, own_only=False, chain=None):
    """call(provider, route) → AIResponse. يجرب كل مزود (بمنطق الطريق كاملًا) وينتقل للتالي عند الفشل — إلا فشل مفتاح
    الخبير الشخصي (Gemini/ChatGPT): تتوقف المهمة بـPersonalKeyFailure ولا ينتقل لأي مزود آخر ولا لمفتاح القسم
    قبل اختياره الصريح. Groq لا يُجرَّب أبداً. عند فشل الجميع: رسالة المستخدم البسيطة."""
    chain = build_chain() if chain is None else chain
    chain = [p for p in chain if not _is_groq(p)]
    if own_only:  # اختبار مفتاح المستخدم: بدون انتقال لمزودات أخرى
        chain = [p for p in chain if p.key_type == KEY_OWN]
    if not chain:
        raise RuntimeError(gc.USER_FAIL_MSG)
    blocked = _blocked_failure()
    if blocked:
        raise blocked                           # نفس المهمة بعد فشل مفتاحها الشخصي: لا شبكة ولا مزوّد آخر قبل قرار الخبير
    prev = None
    quota = None
    for p in chain:
        gc.set_log_provider(p.name, p.key_type)
        if prev:
            gc._log(gc._net_state['route'], 'PROVIDER-SWITCH', note=f'{prev[0]} → {p.name} | السبب: {prev[1]}')
        try:
            resp = gc._run_with_routes(lambda route, p=p: call(p, route), size, timeout)
            if p.key_type == KEY_OWN:
                _clear_pending()
            return resp
        except UserCancelled:
            raise
        except PersonalKeyFailure:
            raise
        except gc.QuotaExhausted as e:
            # حصة اليوم نفدت لنماذج المهمة: ليست فشل مفتاح. مفتاحك الشخصي ← توقف برسالة واضحة؛ مفتاح القسم ← التالي
            quota = e
            if p.key_type == KEY_OWN:
                raise
            prev = (p.name, 'نفدت الحصة')
        except Exception as e:
            prev = (p.name, gc.short_error(e))
            if p.key_type == KEY_OWN and not isinstance(p, BrowserProvider):
                gc._log(gc._net_state['route'], 'PERSONAL-KEY-STOP', error=e,
                        note=f'{p.name}: توقفت المهمة بانتظار قرار الخبير')
                raise personal_failure(p, e) from e
    gc._log(gc._net_state['route'], 'ALL-FAIL', note='فشلت كل المزودات')
    if quota is not None:
        raise quota
    notes = gc.pop_personal_failures()
    raise RuntimeError(gc.USER_FAIL_MSG + ('\n' + '\n'.join(notes) if notes else ''))


# ===== فشل المفتاح الشخصي: توقف + خيارات صريحة (2026-10-21) =====
KIND_LABEL = {'gemini': 'Gemini', 'openai': 'ChatGPT'}
_key_lock = threading.Lock()
_pending_failure = None            # PersonalKeyFailure — تقرؤه الواجهة مرة واحدة بعد انتهاء المهمة
_key_choice = None                 # قرار الخبير للمهمة الجارية: {'use','kind','alt','label'}
BLOCK_SECONDS = 120


class PersonalKeyFailure(RuntimeError):
    """فشل مفتاح الخبير الشخصي لمزوّد. المهمة تتوقف ولا ينتقل البرنامج لمزوّد آخر؛ والخبير يختار (أعد المحاولة /
    استعمل المزوّد الشخصي الآخر / استعمل مفتاح القسم بموافقته / إلغاء)."""

    def __init__(self, kind, cause, detail='', alt=None, section=False):
        self.kind, self.cause, self.detail = kind, cause, gc.redact(detail)[:300]
        self.alt, self.section = alt, section             # alt: 'openai'|'gemini'|None ؛ section: هل يتوفر مفتاح قسم؟
        self.label = KIND_LABEL.get(kind, kind)
        self.created = time.time()
        super().__init__(self.message_ar())

    def message_ar(self):
        return (f"تعذّر العمل بمفتاحك الشخصي لـ{self.label}: {gc.CAUSE_TEXT.get(self.cause, gc.CAUSE_TEXT['other'])}.\n"
                "أوقف البرنامج المهمة ولم ينتقل إلى أي مزوّد آخر. اختر ما تريد.")


def _section_has(kind):
    try:
        rows = [r for r in get_provider_configs() if r.get('enabled') and r.get('api_key') and not _is_groq(r)]
    except Exception:
        return False
    return any((r.get('kind') == 'gemini') if kind == 'gemini' else _is_openai_row(r) for r in rows)


def personal_failure(p, e):
    """يبني PersonalKeyFailure من فشل مزوّد بمفتاح شخصي ويسجّله (للواجهة ولمنع إعادة المحاولة الصامتة في الخيط)."""
    kind = 'gemini' if isinstance(p, GeminiProvider) else 'openai' if isinstance(p, OpenAICompatProvider) else p.name.lower()
    other = 'openai' if kind == 'gemini' else 'gemini' if kind == 'openai' else None
    has_alt = bool(other) and gc.feature_on('api') and bool(gc.load_openai_key() if other == 'openai' else gc.load_api_key())
    f = PersonalKeyFailure(kind, gc.failure_cause(e), gc.short_error(e), alt=other if has_alt else None,
                           section=_section_has(kind))
    global _pending_failure
    with _key_lock:
        _pending_failure = f
    if threading.current_thread() is not threading.main_thread():
        _tls.key_failure = f
    return f


def _blocked_failure():
    f = getattr(_tls, 'key_failure', None)
    if f is not None and time.time() - f.created < BLOCK_SECONDS:
        return f
    _tls.key_failure = None
    return None


def _clear_pending():
    global _pending_failure
    with _key_lock:
        _pending_failure = None
    _tls.key_failure = None


def pop_key_failure(max_age=600):
    """آخر فشل مفتاح شخصي لم يُعرض على الخبير (أو None) — يُفرَّغ بالقراءة."""
    global _pending_failure
    with _key_lock:
        f, _pending_failure = _pending_failure, None
    return f if f is not None and time.time() - f.created < max_age else None


def set_key_choice(use, failure):
    """قرار الخبير بعد الفشل: use = 'retry' | 'alt' | 'section'. يسري على المهمة الجارية حتى clear_key_choice()."""
    global _key_choice
    _key_choice = {'use': use, 'kind': failure.kind, 'alt': failure.alt, 'label': failure.label}
    _clear_pending()


def get_key_choice():
    return _key_choice


def clear_key_choice():
    global _key_choice
    _key_choice = None


def reset_key_state():
    """للاختبارات: تفريغ كل حالة الفشل والاختيار."""
    _clear_pending()
    clear_key_choice()
    _missing.clear()
    _override.clear()


# ===== إدارة المزودات (للأدمن فقط) =====
_OPTION_FIELDS = ('max_images', 'max_image_kb', 'dpi', 'max_tokens', 'daily_limit',
                  'monthly_limit', 'engine3_monthly_limit', 'safety_margin')
# القيم الأولية لو القسم غير موجود في ملف الإعدادات (نسخة exe قديمة)
_DEFAULT_PROVIDERS = {
    'ocrspace': {'kind': 'ocr', 'base_url': 'https://api.ocr.space/parse/image',
                 'model': 'engine 3 → 2', 'api_key': '', 'enabled': 1, 'priority': 1},
    'zai': {'kind': 'openai', 'base_url': 'https://api.z.ai/api/paas/v4',
            'model': 'glm-4.6v-flash', 'api_key': '', 'enabled': 1, 'priority': 10,
            'max_images': 1, 'max_image_kb': 3500},
    'groq': {'kind': 'openai', 'base_url': 'https://api.groq.com/openai/v1',
             'model': 'qwen/qwen3.8-27b', 'api_key': '',
             'enabled': 1, 'priority': 20, 'max_images': 2, 'max_image_kb': 3500, 'dpi': 110,
             'max_tokens': 900},
    # OpenRouter — نماذج ":free" مجانية (حد ~20 طلب/دقيقة و50 طلب/يوم بدون رصيد). قد تتغير أسماء النماذج المجانية؛
    # لو توقف النموذج بدّل model من شاشة المزودات أو من https://openrouter.ai/models?q=free
    'openrouter': {'kind': 'openai', 'base_url': 'https://openrouter.ai/api/v1',
                   'model': 'google/gemma-4-31b-it:free', 'api_key': '',
                   'enabled': 1, 'priority': 30, 'max_images': 3, 'max_image_kb': 3500,
                   'max_tokens': 1500},
    # ChatGPT (OpenAI) — مدفوع بالاستهلاك؛ المفتاح من https://platform.openai.com/api-keys. gpt-4o-mini يقرأ الصور
    # ويقبل temperature=0؛ نماذج التفكير (o1/o3/o4/gpt-5) تُرسل بلا temperature (_body).
    'chatgpt': {'kind': 'openai', 'base_url': 'https://api.openai.com/v1',
                'model': 'gpt-4o-mini', 'api_key': '',
                'enabled': 1, 'priority': 5, 'max_images': 10, 'max_image_kb': 3500,
                'max_tokens': 4000},
}


def save_provider_config(name, api_key=None, enabled=None, priority=None):
    """يحفظ إعدادات مزود للقسم كله في Supabase (يتطلب دخول الأدمن). api_key=None =
    بدون تغيير. يرجع (ok, رسالة) — الرسالة لا تحتوي المفتاح أبدًا."""
    if not gc.is_admin():
        return False, 'غير مخوّل'
    import provider_sync
    cur = next((r for r in get_provider_configs() if r['name'] == name), None)
    base = dict(_DEFAULT_PROVIDERS.get(name, {}), **(cur or {}))
    opts = {k: base[k] for k in _OPTION_FIELDS if base.get(k) not in (None, '')}
    return provider_sync.upsert(name, {
        'kind': base.get('kind') or 'openai', 'base_url': base.get('base_url', ''),
        'model': base.get('model', ''),
        'api_key': api_key if api_key is not None else (base.get('api_key') or None),
        'enabled': bool(base.get('enabled')) if enabled is None else bool(enabled),
        'priority': int(base.get('priority') or 100) if priority is None else int(priority),
        'options': opts})


def _save_local_provider_config(name, api_key=None, enabled=None, priority=None):
    """(احتياطي) الحفظ في gemini_network.ini على هذا الجهاز فقط."""
    path = os.path.join(gc._app_dir(), gc._NET_INI_NAME)
    try:
        gc.get_proxy_url()  # يضمن وجود الملف
        cp = configparser.ConfigParser()
        cp.read(path, encoding='utf-8')
        sec = f'provider:{name}'
        if not cp.has_section(sec):
            cp.add_section(sec)
            for k, v in _DEFAULT_PROVIDERS.get(name, {}).items():
                cp.set(sec, k, str(v))
        if api_key is not None:
            cp.set(sec, 'api_key', api_key.strip())
        if enabled is not None:
            cp.set(sec, 'enabled', '1' if enabled else '0')
        if priority is not None:
            cp.set(sec, 'priority', str(int(priority)))
        with open(path, 'w', encoding='utf-8') as f:
            cp.write(f)
        return True, 'تم الحفظ'
    except Exception as e:
        return False, f'تعذر الحفظ: {type(e).__name__}'


def list_providers_for_admin():
    """كل المزودات (المحفوظة + الافتراضية) بمفتاح مموّه فقط — للعرض."""
    rows = {r['name']: r for r in get_provider_configs()}
    for n, d in _DEFAULT_PROVIDERS.items():
        rows.setdefault(n, dict(d, name=n, enabled=bool(d['enabled'])))
    out = []
    for r in sorted(rows.values(), key=lambda r: int(r.get('priority') or 100)):
        out.append({'name': r['name'], 'model': r.get('model', ''),
                     'enabled': bool(r.get('enabled')), 'priority': r.get('priority'),
                     'has_key': bool(r.get('api_key')),
                     'masked': gc.mask_key(r.get('api_key') or '')})
    return out


def test_provider(name):
    """طلب نصي قصير عبر المزود (بنفس منطق الطريق). يرجع (ok, رسالة)."""
    if not gc.is_admin():
        return False, 'غير مخوّل'
    r = next((x for x in get_provider_configs() if x['name'] == name), None)
    if not r or not r.get('api_key'):
        return False, 'لا يوجد مفتاح محفوظ لهذا المزود'
    if r.get('kind') == 'ocr':
        return _test_ocr()
    cls = PROVIDER_KINDS.get(r.get('kind') or 'openai', OpenAICompatProvider)
    p = cls(name, r['api_key'], KEY_DEFAULT, r.get('model', ''), r.get('base_url', ''),
            max_images=r.get('max_images'), max_image_kb=r.get('max_image_kb'), dpi=r.get('dpi'), max_tokens=r.get('max_tokens'))
    gc.set_log_provider(name, 'اختبار')
    try:
        resp = gc._run_with_routes(
            lambda route: p.generate_text(['قل بالضبط: تم الربط بنجاح'], route, 30), 0, 30)
        return True, resp.text.strip()[:200]
    except Exception as e:
        return False, gc.short_error(e)


def _test_own(p):
    """طلب نصي قصير عبر مزوّد واحد بمفتاح الخبير الشخصي (بلا انتقال لغيره ولا لمفتاح القسم). يرجع (ok, رسالة)."""
    gc.set_log_provider(p.name, 'اختبار')
    try:
        resp = gc._run_with_routes(
            lambda route: p.generate_text(['قل بالضبط: تم الربط بنجاح'], route, 30), 0, 30)
        model = getattr(p, 'last_model', '') or ''
        return True, resp.text.strip()[:200] + (f'\n\nالنموذج المستعمل: {model}' if model else '')
    except Exception as e:
        return False, gc.short_error(e)


def test_own_gemini():
    """«اختبار»: يعيد اكتشاف ما يتيحه المفتاح (أحدث Pro أو أحدث Flash) ويحفظه، ثم طلب قصير بالنموذج المكتشف."""
    key = gc.load_api_key()
    if not key:
        return False, 'لا يوجد مفتاح Gemini شخصي'
    try:
        cap = gc.key_model(key, refresh=True)
    except Exception as e:
        return False, gc.short_error(e)
    ok, msg = _test_own(GeminiProvider('Gemini', key, KEY_OWN))
    line = f"مفتاحك يتيح: {cap['model']}" + ('' if cap.get('pro') else ' (Pro غير متاح لهذا المفتاح)')
    return ok, msg + '\n\n' + line


def test_own_openai():
    key = gc.load_openai_key()
    if not key:
        return False, 'لا يوجد مفتاح OpenAI شخصي'
    return _test_own(OpenAIOwnProvider(OPENAI_NAME, key, KEY_OWN, '', OPENAI_BASE, max_tokens=200))


def test_own_ocrspace():
    if not gc.load_ocr_key():
        return False, 'لا يوجد مفتاح OCR.space شخصي'
    return _test_ocr()


def _test_ocr():
    """صفحة صغيرة فيها نص عربي → OCR.space بالطريق المعتمد."""
    import fitz
    import tempfile
    import ocr_space
    doc = fitz.open()
    page = doc.new_page(width=420, height=160)
    page.insert_htmlbox(page.rect + (20, 20, -20, -20),
                        '<p dir="rtl" style="font-size:24px">حكمت المحكمة بندب خبير من إدارة '
                        'الخبراء وحددت جلسة لمثول الخصوم أمام الخبير</p>')
    fd, tmp = tempfile.mkstemp(suffix='.pdf', prefix='expert_')
    os.close(fd)
    doc.save(tmp)
    doc.close()
    gc.set_log_provider('OCR.space', 'اختبار')
    try:
        text = gc._run_with_routes(lambda route: ocr_space.ocr_pages(tmp, [0], route), 0, 60)
        q = ocr_space.quota_status()
        return True, (' '.join(text.splitlines()[1:]) + '\n\n'
                      f"الاستخدام هذا الشهر: {q['month_total']} طلب "
                      f"(محرك 3: {q['month_e3']}) — اليوم: {q['day_total']}")
    except Exception as e:
        return False, gc.short_error(e)
    finally:
        os.remove(tmp)


# ===== مزوّد كل مهمة (2026-10-17) =====
# [task_providers] في gemini_network.ini: مهمة = auto | قائمة مفصولة بفواصل من: gemini | openai | اسم مزوّد.
#   auto = السلسلة القديمة (build_text_chain: الأرخص أولاً). openai = كل مزوّد من نوع openai ما عدا groq (لا يدخل إلا بذكر اسمه).
# الصياغة والبحث والنتيجة افتراضياً gemini ثم openai: عربية Groq/z.ai أضعف. لا انتقال صامت لأضعف: غياب المفتاح
# يرفع ProviderMissing برسالة، والخبير يختار (بديل لهذه العملية فقط أو يضبط مفتاحاً).
TASKS = {'extract': 'استخراج / تصنيف', 'summarize': 'تلخيص', 'write': 'صياغة نصوص التقرير',
         'research': 'البحث والنتيجة'}
TASK_DEFAULTS = {'extract': 'auto', 'summarize': 'auto', 'write': 'gemini,openai', 'research': 'gemini,openai'}
PURPOSE_TASK = {'الموضوع': 'write', 'الإجراءات': 'write', 'الحضور': 'extract', 'فحص الجاهزية': 'extract',
                'البحث': 'research', 'اكتب رغم النقص': 'research', 'إعادة كتابة بند': 'research',
                'النتيجة': 'research', 'الأسئلة المهمة': 'write', 'حكم الإحالة': 'extract',
                'العقود': 'extract', 'تاريخ الحجز': 'extract'}
_TASK_SECTION = 'task_providers'


class ProviderMissing(RuntimeError):
    """لا مزوّد مطابق لما اختير للمهمة (لا انتقال صامت لمزوّد أضعف)."""

    def __init__(self, task, spec, message, alternatives=()):
        super().__init__(message)
        self.task, self.spec, self.alternatives = task, spec, list(alternatives)


def get_task_specs():
    import configparser
    out = dict(TASK_DEFAULTS)
    try:
        cp = configparser.RawConfigParser()
        cp.read(os.path.join(gc._app_dir(), gc._NET_INI_NAME), encoding='utf-8')
        if cp.has_section(_TASK_SECTION):
            for t in TASKS:
                v = cp.get(_TASK_SECTION, t, fallback='').strip()
                if v:
                    out[t] = v
    except Exception:
        pass
    return out


def save_task_spec(task, spec):
    import configparser
    path = os.path.join(gc._app_dir(), gc._NET_INI_NAME)
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(path, encoding='utf-8')
    if not cp.has_section(_TASK_SECTION):
        cp.add_section(_TASK_SECTION)
    cp.set(_TASK_SECTION, task, spec)
    with open(path, 'w', encoding='utf-8') as f:
        cp.write(f)


def ensure_task_defaults():
    """يكتب القسم الافتراضي في ini إن لم يوجد (لا يمسّ قيمة موجودة)."""
    cur = get_task_specs()
    import configparser
    cp = configparser.RawConfigParser()
    cp.read(os.path.join(gc._app_dir(), gc._NET_INI_NAME), encoding='utf-8')
    for t, v in cur.items():
        if not (cp.has_section(_TASK_SECTION) and cp.get(_TASK_SECTION, t, fallback='').strip()):
            save_task_spec(t, v)


def ensure_model_defaults():
    """يكتب [gemini_routing] و[model_limits] الافتراضيين في ini إن لم يوجدا (لا يمسّ قسماً موجوداً) ليعدّلهما الأدمن."""
    import gemini_quota
    path = os.path.join(gc._app_dir(), gc._NET_INI_NAME)
    cp = configparser.RawConfigParser()
    cp.read(path, encoding='utf-8')
    blocks = []
    route_block = (f'[{_ROUTE_SECTION}]\n; سلسلة النماذج لكل مهمة: lite | flash | pro | top | عائلة:إصدار (lite:3.5) | اسم نموذج | اسم مهمة\n'
                   '; *_fallback = الملاذ الأخير حين يتعذّر المحدَّد تماماً (يُعلَّم «نموذج احتياطي» في «كُتب بواسطة»)\n'
                   + ''.join(f'{k} = {v}\n' for k, v in MODEL_ROUTES.items())
                   + ''.join(f'{k}_fallback = {v}\n' for k, v in FALLBACK_ROUTES.items())
                   + f'triage_batch_chars = {TRIAGE_BATCH_CHARS}\nroutes_version = {ROUTES_VERSION}\n')
    limits_block = (f'[{gemini_quota.SECTION}]\n; حصص المفتاح المجاني لكل نموذج (rpm طلب/دقيقة، tpm توكن/دقيقة، rpd طلب/يوم)\n'
                    + ''.join(f'{fam}_{k} = {v}\n' for fam, lim in gemini_quota.DEFAULT_LIMITS.items() if fam != 'gemma'
                              for k, v in lim.items())
                    + ''.join(f'{fam}_soft_rpd = {v}\n' for fam, v in gemini_quota.SOFT_RPD.items())
                    + f'queue_share = {gemini_quota.QUEUE_SHARE}\nqueue_cases_per_day = {gemini_quota.QUEUE_CASES_PER_DAY}\n')
    try:
        old = ''
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                old = f.read()
    except OSError:
        return False
    text = old
    ini = _route_ini() if cp.has_section(_ROUTE_SECTION) else {}
    if cp.has_section(_ROUTE_SECTION) and str(ini.get('routes_version', '1')).strip() != str(ROUTES_VERSION):
        # ترحيل مرة واحدة: القسم القديم (Gemma وFlash للنسخ) ← الخطة الجديدة؛ ما غيّره الأدمن عن الافتراضي القديم يبقى
        keep = {k: v for k, v in ini.items() if k in MODEL_ROUTES and v != _OLD_DEFAULTS.get(k)}
        new = route_block
        for k, v in keep.items():
            new = re.sub(rf'(?m)^{k} = .*$', f'{k} = {v}', new, count=1)
        text = re.sub(rf'(?ms)^\[{_ROUTE_SECTION}\]\s*\n.*?(?=^\[|\Z)', lambda _m: new + '\n', text, count=1)
    elif not cp.has_section(_ROUTE_SECTION):
        blocks.append(route_block)
    if not cp.has_section(gemini_quota.SECTION):
        blocks.append(limits_block)
    elif not cp.has_option(gemini_quota.SECTION, 'lite_soft_rpd'):
        add = ''.join(f'{fam}_soft_rpd = {v}\n' for fam, v in gemini_quota.SOFT_RPD.items()) + \
            f'queue_share = {gemini_quota.QUEUE_SHARE}\nqueue_cases_per_day = {gemini_quota.QUEUE_CASES_PER_DAY}\n'
        text = re.sub(rf'(\[{gemini_quota.SECTION}\][^\n]*\n)', lambda m: m.group(1) + add, text, count=1)
    if blocks:
        text = text.rstrip('\n') + ('\n\n' if text.strip() else '') + '\n'.join(blocks)
    if text == old:
        return False
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return True
    except OSError:
        return False


def describe_spec(spec):
    names = {'auto': 'تلقائي (الأرخص أولاً)', 'gemini': 'Gemini', 'openai': 'OpenAI-compatible'}
    return ' ثم '.join(names.get(x.strip(), x.strip()) for x in spec.split(',') if x.strip())


def build_task_chain(task, spec=None):
    """سلسلة المزوّدات لمهمة. فارغة ← ProviderMissing (لا سقوط صامت إلى أضعف)."""
    spec = (spec or get_task_specs().get(task) or 'auto').strip()
    if spec == 'auto':
        return [p for p in build_text_chain() if not _is_groq(p)]
    full = [p for p in build_chain() if not _is_groq(p)]       # Groq لا يدخل أي مهمة حتى لو ذُكر صراحةً
    tokens = [x.strip() for x in spec.split(',') if x.strip()]
    chain = []
    for tok in tokens:
        low = tok.lower()
        if low == 'gemini':
            picked = [p for p in full if isinstance(p, GeminiProvider)]
        elif low == 'openai':
            picked = [p for p in full if isinstance(p, OpenAICompatProvider) and p.name.lower() != 'groq'
                      and p.name.lower() not in [t.lower() for t in tokens]]
        else:
            picked = [p for p in full if p.name.lower() == low]
        for p in picked:
            if p not in chain:
                chain.append(p)
    if not chain:
        have = sorted({p.name for p in full if not isinstance(p, BrowserProvider)})
        raise ProviderMissing(
            task, spec,
            f'لا يتوفر مزوّد لمهمة «{TASKS.get(task, task)}» (المضبوط: {describe_spec(spec)}) — لم يُضبط مفتاحه. '
            'اضبط المفتاح أو غيّر المزوّد من الإعدادات ← مزوّد كل مهمة.'
            + (f' المتاح الآن: {"، ".join(have)}.' if have else ''), have)
    return chain


# اختيار الخبير عند غياب مزوّد المهمة: بديل لعملية واحدة فقط (يُستهلك عند أول بناء سلسلة تالٍ لتلك المهمة)
_missing = {}
_override = {}


def pop_missing():
    """آخر ProviderMissing لم يُعرض على الخبير بعد: (task، spec، رسالة، بدائل) أو None."""
    return _missing.pop('last', None)


def set_override(task, spec):
    _override[task] = spec


_build_task_chain_raw = build_task_chain


def build_task_chain(task, spec=None):          # noqa: F811 — يغلّف الأصل بالاختيار المؤقت وتسجيل النقص
    ch = get_key_choice()
    if ch and ch.get('use') == 'alt' and ch.get('alt'):
        spec = OPENAI_NAME if ch['alt'] == 'openai' else ch['alt']       # اختار الخبير المزوّد الشخصي الآخر: وحده يحلّ محل مواصفة المهمة
    spec = spec or _override.pop(task, None)
    try:
        chain = _build_task_chain_raw(task, spec)
        for p in chain:                                    # نموذج Gemini حسب المهمة (MODEL_ROUTES)
            if isinstance(p, GeminiProvider):
                p.task = TASK_MODEL.get(task, task if task in MODEL_ROUTES else 'write')
        return chain
    except ProviderMissing as e:
        _missing['last'] = (e.task, e.spec, str(e), e.alternatives)
        raise
