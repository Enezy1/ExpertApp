# ===== case_startup.py — خط البداية التلقائي عند فتح «مسار التقرير» (2026-10-21) =====
# قبل أي خطوة أخرى يعمل في الخلفية (خيط صفحة القضية) بالترتيب:
#   1) التأكد من الملفات الموجودة في مجلد القضية          6) سحب حكم الإحالة من النظام — فقط إن لم يوجد بين المستندات
#   2) إضافة كل الملفات الموجودة في المجلد إلى القائمة     7) سحب صحيفة الدعوى — فقط إن لم توجد بين المستندات
#   3) التحقق: لكل ملف markdown                          8) العقد من الفرز (case_main_contract، بلا طلب)
#   4) التحويل إلى markdown (حارس الحلقة loop_guard)     9) تحديث الملخص.md (case_summary)
#   5) الفرز والتسمية والنقل (case_sort + case_triage: طلب واحد لكل ملف، مدمج في التحويل للممسوح)
# المستندات أولاً: ما في المجلد يُقرأ ويُفرز قبل أي اتصال بالنظام، فلا يُسحب حكم/صحيفة موجودان أصلاً بين المستندات.
# الحالة الحية لكل خطوة وعدادها في data['startup'] + سجل _LIVE (لوحة الخطوات تقرؤه كل ثانية).
# يُستأنف إن أُغلق: كل خطوة لا تكرر ما أُنجز (manifest + بصمة sha1 للتحويل والفرز، doc_id للجلب، بصمة النصوص للعقد).
import os
import threading
from datetime import datetime

import case_folder as cf
import case_layout as cl

STEPS = (('scan', 'التأكد من الملفات الموجودة في مجلد القضية'),
         ('list', 'إضافة كل الملفات الموجودة في المجلد إلى القائمة'),
         ('check', 'التحقق: لكل ملف نسخة markdown'),
         ('convert', 'التحويل إلى markdown'),
         ('sort', 'الفرز والتسمية والنقل'),
         ('judgment', 'سحب حكم الإحالة من النظام (إن لم يوجد بين المستندات)'),
         ('plaint', 'سحب صحيفة الدعوى (إن لم توجد بين المستندات)'),
         ('contract', 'البحث عن العقد'),
         ('summary', 'تحديث الملخص.md'))
STEP_KEYS = tuple(k for k, _ in STEPS)
LABELS = dict(STEPS)
PENDING, RUNNING, DONE, SKIPPED, FAILED, INPUT = 'pending', 'running', 'done', 'skipped', 'failed', 'needs_input'
STATE_TEXT = {PENDING: 'بانتظار', RUNNING: 'جارٍ', DONE: 'تم', SKIPPED: 'لا يلزم', FAILED: 'تعذّر',
              INPUT: 'يحتاج قرارك'}

_LIVE = {}
_LOCK = threading.Lock()


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _key(base):
    return os.path.normcase(os.path.abspath(base))


def live(base):
    """نسخة من الحالة الحية لعملية جارية (أو None)."""
    with _LOCK:
        st = _LIVE.get(_key(base))
        return {k: dict(v) for k, v in st.items()} if st else None


def is_running(base):
    with _LOCK:
        return _key(base) in _LIVE


def state(data):
    """{key: {state, count, total, message, at}} لكل الخطوات التسع (الناقص pending)."""
    st = (data.get('startup') or {}).get('steps') or {}
    return {k: dict({'state': PENDING, 'count': 0, 'total': 0, 'message': ''}, **(st.get(k) or {})) for k in STEP_KEYS}


def counter_text(s):
    if s.get('total'):
        return f"{s.get('count', 0)} من {s['total']}"
    return str(s['count']) if s.get('count') else ''


class Run:
    def __init__(self, base, data, on_update=None):
        self.base, self.data, self.on_update = base, data, on_update
        self.steps = state(data)
        for k in STEP_KEYS:                      # تشغيل جديد: الجاري من إغلاق سابق يعود «بانتظار»
            if self.steps[k]['state'] == RUNNING:
                self.steps[k]['state'] = PENDING

    def set(self, key, st=None, count=None, total=None, message=None):
        s = self.steps[key]
        if st is not None:
            s['state'] = st
        if count is not None:
            s['count'] = count
        if total is not None:
            s['total'] = total
        if message is not None:
            s['message'] = message
        s['at'] = _now()
        self.data.setdefault('startup', {})['steps'] = self.steps
        with _LOCK:
            _LIVE[_key(self.base)] = {k: dict(v) for k, v in self.steps.items()}
        if self.on_update:
            try:
                self.on_update(key, dict(s))
            except Exception:
                pass


# ---------- الخطوات ----------

def loose_files(base):
    """ملفات وُضعت مباشرة في جذر مجلد القضية (غير الملخص) — تُنقل إلى «أخرى» لتدخل القائمة."""
    out = []
    try:
        names = os.listdir(base)
    except OSError:
        return out
    for n in sorted(names):
        p = os.path.join(base, n)
        if os.path.isfile(p) and n != cl.SUMMARY and not cf.is_ignored(n):
            out.append(n)
    return out


def originals(base):
    """[المسار النسبي] لكل ملف في المجلدات الأربعة (أي نوع، عدا المؤقت)."""
    out = []
    for folder in cf.FOLDERS:
        for dp, dirs, fs in os.walk(os.path.join(base, folder)):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for n in fs:
                if not cf.is_ignored(n):
                    out.append(os.path.relpath(os.path.join(dp, n), base).replace('\\', '/'))
    return sorted(out)


def run(base, data, cookies=None, user_id='309', ask=None, contract_ask=None, convert=None, stop=None,
        on_update=None, fetch=None, referral_ask=None):
    """يشغّل الخطوات التسع. fetch(kind) -> [rel] بديل الجلب من النظام (الاختبارات). يرجع نتيجة المزامنة (sync)."""
    stop = stop or (lambda: False)
    r = Run(base, data, on_update)
    res = {'converted': [], 'failed': [], 'missing': [], 'total': 0, 'message': '', 'count': {}}
    notes = []
    data.setdefault('startup', {})['started_at'] = _now()
    try:
        # 1) البنية + ترحيل القضايا القديمة + ما في المجلد
        r.set('scan', RUNNING)
        moved = cl.migrate(base)
        cl.ensure(base)
        if not data.get('folder_migration'):
            cf.migrate_legacy(base, data)
        try:
            cf.collect_local_minutes(base, data['caso_no'])
        except Exception as e:
            notes.append(f'تعذّر نسخ المحاضر المحلية: {e}')
        try:                                       # «صحيفة الدعوى (2)/(3)» المكررة ← مجلد «مكررات» (لا حذف)
            import case_sources
            import case_stage2
            s2 = data.get('stage2') or {}
            before = case_stage2.signature(base, data) if s2.get('sig') and len(case_sources.claim_files(base)) > 1 else None
            dup = case_sources.dedupe_claims(base, data)
            if dup and before and s2.get('sig') == before:
                s2['sig'] = case_stage2.signature(base, data)   # نقل المكرر ليس تغيّراً في البيانات: لا إعادة كتابة للموضوع
            if dup:
                notes.append(f'نُقلت {cf.files_word(len(dup))} مكررة من صحيفة الدعوى إلى «{case_sources.DUP_DIR}»')
        except Exception as e:
            notes.append(f'تعذّر فحص نسخ صحيفة الدعوى المكررة: {e}')
        files = originals(base)
        r.set('scan', DONE, count=len(files), message=(f"رُحِّلت البنية القديمة ({len(moved['moved'])} ملفاً)"
                                                       if moved and moved.get('moved') else ''))
        # 2) كل الملفات (أي نوع) في القائمة: الموضوع في جذر القضية ← «أخرى»
        r.set('list', RUNNING)
        for n in loose_files(base):
            try:
                cl.safe_move(os.path.join(base, n), os.path.join(base, cf.OTHER, n))
            except (OSError, cl.MoveError) as e:
                notes.append(f'تعذّر نقل {n} إلى أخرى: {e}')
        files = originals(base)
        unsup = cf.unsupported(base)
        r.set('list', DONE, count=len(files),
              message=f'{len(unsup)} بصيغة لا تُحوَّل' if unsup else '')
        # 3) التحقق: لكل ملف markdown
        r.set('check', RUNNING)
        man = cf.load_manifest(base)
        scanned = cf.scan(base, man['files'])
        busy = {d.get('file') for p in data.get('portfolios') or [] for d in p.get('docs') or []
                if (d.get('convert') or {}).get('state') in ('pending', 'running')}
        partial = []                               # markdown موجود (بعد مسح الكاش/برنامج آخر) ومكتمل = محوَّل؛ الناقص يُعاد
        if cf.adopt_existing(base, man['files'], scanned, busy, rejected=partial):
            cf.save_manifest(base, man)
        need = [rel for rel, f in scanned.items() if rel not in busy and cf._stale(base, man['files'].get(rel), f)]
        msg = [f'{len(need)} بلا markdown مكتمل'] if need else []
        if partial:
            msg.append(f'منها {len(partial)} نسخة ناقصة ستُعاد: ' + '، '.join(
                f'{os.path.basename(rel)} ({why})' for rel, why in partial[:3]))
        r.set('check', DONE, count=len(scanned) - len(need), total=len(scanned), message=' — '.join(msg))
        # 4) التحويل (الجديد/المتغيّر فقط، مع حارس الحلقة)
        if stop():
            raise _Stopped()
        r.set('convert', RUNNING if need else SKIPPED, count=0, total=len(need))

        def on_file(rel, i, n):
            r.set('convert', count=i, total=n, message=os.path.basename(rel))
        res = cf.sync_case_folder(base, data, convert, stop, on_file=on_file)
        bad = [x for x in res['failed']]
        if need:
            r.set('convert', FAILED if bad and not res['converted'] else DONE,
                  count=len(res['converted']), total=len(need),
                  message=(f'تعذّر تحويل {cf.files_word(len(bad))}' if bad else ''))
        # 5) الفرز والتسمية والنقل
        if stop():
            raise _Stopped()
        import case_sort
        import case_triage
        todo = case_triage.pending(base, data=data)   # ما لم يُفرز بنسخته الحالية (بصمة)؛ القضية المكتوبة لا يُعاد فرزها لتغيّر VERSION
        man_now = cf.load_manifest(base)
        carried = [x for x in todo if (man_now['files'][x].get('triage_raw') or {}).get('sha1')
                   == man_now['files'][x].get('sha1')]                # الفرز جاء مع طلب التحويل نفسه
        if not todo:
            r.set('sort', SKIPPED if not case_sort.questions(data) else INPUT, count=0, total=0,
                  message=_q_msg(case_sort.questions(data)))
        elif ask is None and not carried:
            r.set('sort', SKIPPED, total=len(todo), message='لا مزوّد ذكاء متاح للفرز — تبقى في «أخرى»')
        else:
            r.set('sort', RUNNING, count=0, total=len(todo))
            out = case_sort.run(base, data, ask, stop,
                                on_file=lambda rel, i, n: r.set('sort', count=i, total=n, message=os.path.basename(rel)))
            qs = case_sort.questions(data)
            r.set('sort', INPUT if qs else (FAILED if out['errors'] and not out['sorted'] else DONE),
                  count=len(out['sorted']), total=len(todo),
                  message=_q_msg(qs) or (f"تعذّر فرز {cf.files_word(len(out['errors']))}" if out['errors'] else ''))
        try:                                       # الحوافظ والمذكرات من الفرز (للمرفقات بالكود)
            data['triage_docs'] = case_triage.attachment_items(base)
        except Exception:
            pass
        _register_sources(base, data)
        # 6–7) حكم الإحالة وصحيفة الدعوى من النظام: فقط ما لم يُوجد بين المستندات بعد قراءتها وفرزها
        for key, kind in (('judgment', cf.JUDGMENT), ('plaint', cf.PLAINT)):
            if stop():
                break
            if cf.has_kind(base, kind):
                r.set(key, SKIPPED, count=1, message='موجود بين المستندات')
                continue
            r.set(key, RUNNING)
            try:
                if fetch is not None:
                    got = fetch(kind)
                elif cookies:
                    got = cf.fetch_from_system(base, data, cookies, user_id, kinds={kind})
                else:
                    got = []
                    if kind == cf.JUDGMENT:                  # حكم محفوظ قديماً في Desktop\judgments
                        import case_sources
                        if case_sources.adopt_judgment(base, data):
                            got = [case_sources.record(data, 'judgment').get('file')]
                if got:
                    r.set(key, DONE, count=len(got), message='سُحب من النظام')
                elif cf.has_kind(base, kind):
                    r.set(key, DONE, count=1)
                else:
                    r.set(key, FAILED if cookies or fetch else SKIPPED,
                          message='غير موجود في النظام' if cookies or fetch else 'غير موجود بين المستندات ولا اتصال بالنظام — يُسحب عند توفره')
            except Exception as e:
                r.set(key, FAILED, message=f'تعذّر السحب: {e}')
        if any(r.steps[k]['state'] == DONE for k in ('judgment', 'plaint')) and not stop():
            more = cf.sync_case_folder(base, data, convert, stop)       # ما سُحب يُحوَّل إلى markdown
            res['converted'] += more['converted']
            res['failed'] += more['failed']
            if more['converted'] and not stop():           # ويُفرز في التشغيل نفسه (طلب واحد لكل ملف، لا عند الفتح التالي)
                import case_sort
                case_sort.run(base, data, ask, stop)
                try:
                    import case_triage
                    data['triage_docs'] = case_triage.attachment_items(base)
                except Exception:
                    pass
        _register_sources(base, data)
        try:                                       # الفهرس وحكم الإحالة بعد الفرز (الأسماء الجديدة)
            import case_index
            case_index.write_index(base, data)
        except Exception as e:
            notes.append(f'تعذّر بناء فهرس المستندات: {e}')
        try:
            import referral_pick
            referral_pick.pick(base, data, None)           # حكم الإحالة بالكود (بلا طلب ذكاء)
        except Exception as e:
            notes.append(f'تعذّر تحديد حكم الإحالة: {e}')
        # 8) العقد: من أقدم حافظة
        if stop():
            raise _Stopped()
        r.set('contract', RUNNING)
        try:
            import case_main_contract as mc
            got = mc.find(base, data, None, from_triage=True)      # من الفرز وحده: لا طلب لكل حافظة
            if got.get('found'):
                c = got['contract']
                r.set('contract', DONE, count=1, message=mc.short(c))
            else:
                r.set('contract', SKIPPED if not got.get('searched') else DONE, count=0,
                      message=got.get('message') or 'لم يُعثر على عقد في الحوافظ')
        except Exception as e:
            if cf.is_key_failure(e):
                raise
            r.set('contract', FAILED, message=f'تعذّر البحث عن العقد: {e}')
        # 9) الملخص
        r.set('summary', RUNNING)
        try:
            import case_summary
            case_summary.write(base, data)
            r.set('summary', DONE, count=1)
        except Exception as e:
            r.set('summary', FAILED, message=f'تعذّر تحديث الملخص: {e}')
    except _Stopped:
        for k in STEP_KEYS:
            if r.steps[k]['state'] == RUNNING:
                r.set(k, PENDING, message='أُوقف — يُستأنف عند الفتح التالي')
    except Exception as e:
        if not cf.is_key_failure(e):
            raise
        # فشل مفتاحك الشخصي: الخطوة الجارية «تعذّر» بالسبب، والباقي ينتظر اختيارك (أعد المحاولة/البديل/مفتاح القسم)
        for k in STEP_KEYS:
            if r.steps[k]['state'] == RUNNING:
                r.set(k, FAILED, message=str(e).splitlines()[0] if str(e) else 'فشل مفتاحك الشخصي')
        raise
    finally:
        with _LOCK:
            _LIVE.pop(_key(base), None)
        data['startup']['finished_at'] = _now()
    if notes:
        res['message'] = ' — '.join([res.get('message') or ''] + notes).strip(' —')
        if 'folder_sync' in data:
            data['folder_sync']['message'] = res['message']
    return res


class _Stopped(Exception):
    pass


def _register_sources(base, data):
    """«حكم الإحالة»/«صحيفة الدعوى» في مستندات_النظام تُسجَّل مصدراً (data['sources']) فتقرؤها خطوتا المأمورية والموضوع."""
    try:
        import case_sources
    except Exception:
        return
    for kind, ck in (('judgment', cf.JUDGMENT), ('claim', cf.PLAINT)):
        try:
            if case_sources.local_file(base, data, kind):
                continue
            if kind == 'claim':                    # المسار الواحد للصحيفة: يحفظ رقم المستند وبصمات المحتوى المسجّلة
                case_sources.find_claim(base, data)
                continue
            names = sorted(os.listdir(os.path.join(base, cf.SYSDOCS)))
            hit = next((n for n in names if os.path.splitext(n)[0] == cf.SYSTEM_NAMES[ck]
                        and n.lower().endswith('.pdf') and case_sources.is_pdf(os.path.join(base, cf.SYSDOCS, n))), None)
            if hit:
                case_sources.store(base, data, kind, os.path.join(base, cf.SYSDOCS, hit), origin='folder')
        except Exception:
            continue


def _register_tasks():
    """مزوّد «الفرز» و«العقد»: مهمة الاستخراج ← نماذج text_light (Gemma ثم Flash Lite ثم Flash — ai_providers.MODEL_ROUTES)،
    والتحقق الحرفي بالكود (case_triage.verify) كما هو."""
    try:
        import ai_providers
        ai_providers.PURPOSE_TASK.setdefault('الفرز', 'extract')
        ai_providers.PURPOSE_TASK.setdefault('العقد', 'extract')
    except Exception:
        pass


_register_tasks()


def _q_msg(qs):
    if not qs:
        return ''
    return f'{cf.files_word(len(qs))} يحتاج قرارك' if len(qs) > 1 else qs[0][1]


def complete(data):
    """انتهى خط البداية بلا خطوة جارية أو بانتظار؟"""
    st = state(data)
    return all(s['state'] in (DONE, SKIPPED, FAILED, INPUT) for s in st.values())
