# ===== summary_queue.py — طابور خلفي واحد لملخصات القضايا من صحيفة الدعوى (2026-10-23) =====
# السبب (تشخيص 2026-10-22): كل صف قضية بلا ملخص كان يفتح خيطاً مستقلاً ويرسل صفحتين من الصحيفة بالتوازي، والفشل لا يُحفظ،
# فكل تحديث للقائمة يعيد إرسال الجميع — مئات الطلبات الصغيرة على Flash Lite بعد نفاد Flash.
# الآن خيط عامل واحد يعالج القضايا بالتتابع:
#   الصحيفة تُسحب (documents.get_claim_for_case) ← تُحفظ في مجلد القضية (case_sources.store) ← تُحوَّل markdown مرة واحدة
#   (طبقة النص إن سلمت، وإلا محرّك «best» = Gemini بمهمة ocr: Flash Lite) وتُسجَّل في manifest فلا يعاد تحويلها
#   ← نصها يُرسل بطلب واحد لمهمة text_light (Gemma ← Lite ← Flash) ← الملخص يُحفظ في case_db.
# بصمة لكل قضية (autocase_no + بصمة الصحيفة) في %LOCALAPPDATA%\ExpertApp\summary_queue.json: لا يُعاد ما نجح، والفشل لا
# يُعاد قبل FAIL_RETRY_SECONDS. الطلبات من نوع «طابور» (gemini_quota.mode('queue')): حدود الدقيقة يحترمها العدّاد.
# (2026-10-25) القضايا الأحدث استلاماً أولاً، وسقف يومي (queue_cases_per_day = 40 في [model_limits])، ويتوقف الطابور عند بلوغ
# 70% من السقف الناعم لـLite (gemini_quota.queue_room) — يبقى الباقي للفرز التلقائي ولعمل الواجهة.
import json
import os
import queue
import tempfile
import threading
import time

FAIL_RETRY_SECONDS = 6 * 3600
USER_ID = '309'                        # نفس referred_cases.USER_ID
PATH_OVERRIDE = None
PROCESS = None                         # الاختبارات تستبدل خط المعالجة: fn(case, cookies) -> نص الملخص أو ''
ROOM = None                            # الاختبارات: fn() -> هل بقي في حصة Lite مكان للطابور

_q = queue.PriorityQueue()             # (−تاريخ الاستلام، تسلسل، القضية، الكوكيز): الأحدث أولاً
_seq = [0]
_lock = threading.Lock()
_waiting = {}                          # caso_no ← [callbacks]
_worker = None
_status = {'busy': '', 'done': 0, 'failed': 0, 'capped': 0}
_LOCAL_MARK = '(ملخص محلي) '


def _path():
    if PATH_OVERRIDE:
        return PATH_OVERRIDE
    import app_paths
    return app_paths.path('summary_queue.json')


def _load():
    try:
        with open(_path(), encoding='utf-8') as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(s):
    try:
        os.makedirs(os.path.dirname(_path()), exist_ok=True)
        with open(_path(), 'w', encoding='utf-8') as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _key(case):
    return (case.get('caso_no') or '').strip().upper()


def recently_failed(case, now=None):
    rec = _load().get(_key(case)) or {}
    now = time.time() if now is None else now
    return (not rec.get('ok') and rec.get('autocase') == (case.get('autocase_no') or '')
            and now - float(rec.get('at') or 0) < FAIL_RETRY_SECONDS)


def _remember(case, ok, note=''):
    with _lock:
        s = _load()
        s[_key(case)] = {'autocase': case.get('autocase_no') or '', 'ok': bool(ok), 'at': time.time(),
                         'note': str(note or '')[:200]}
        _save(s)


def status():
    """حالة صغيرة للواجهة/السجل: {'busy': رقم القضية الجارية أو '', 'queued', 'done', 'failed'}."""
    return dict(_status, queued=_q.qsize())


def enqueue(case, cookies, on_done=None):
    """يضيف قضية للطابور (مرة واحدة مهما تكرر الطلب). on_done(نص) يُستدعى من الخيط العامل ('' عند الفشل).
    يرجع False إن لم تُضف (فشلت مؤخراً أو بلا رقم)."""
    key = _key(case)
    if not key:
        return False
    with _lock:
        if key in _waiting:
            if on_done:
                _waiting[key].append(on_done)
            return True
    if recently_failed(case) or daily_left() <= 0:
        return False
    with _lock:
        _waiting[key] = [on_done] if on_done else []
        _seq[0] += 1
        seq = _seq[0]
    _q.put((-_date_key(case), seq, case, cookies))
    _ensure_worker()
    return True


def _date_key(case):
    d = ''.join(ch for ch in str(case.get('received_date') or '') if ch.isdigit())
    return int(d[:8]) if len(d) >= 8 else 0


def _day(s):
    import gemini_quota
    d = s.get('_day') if isinstance(s.get('_day'), dict) else {}
    return d if d.get('day') == gemini_quota.pacific_day() else {'day': gemini_quota.pacific_day(), 'n': 0}


def daily_left():
    """كم قضية بقي للطابور اليوم (السقف queue_cases_per_day، بيوم المحيط الهادئ كالحصص)."""
    import gemini_quota
    return gemini_quota.queue_cases_per_day() - int(_day(_load()).get('n') or 0)


def _count_today():
    with _lock:
        s = _load()
        d = _day(s)
        d['n'] = int(d.get('n') or 0) + 1
        s['_day'] = d
        _save(s)


def quota_room():
    """هل بقي في حصة Lite اليوم مكان للطابور (أقل من 70% من السقف الناعم لأحد نموذجي text_light)؟ المفتاح المدفوع: نعم."""
    if ROOM is not None:
        return ROOM()
    if PROCESS is not None:
        return True
    try:
        import ai_providers
        import gemini_config as gc
        import gemini_quota
        g = next((p for p in ai_providers.build_chain() if isinstance(p, ai_providers.GeminiProvider)), None)
        if g is None or (gc.cached_key_model(g.api_key) or {}).get('pro'):
            return True
        try:
            with open(gc._models_cache_path(), encoding='utf-8') as f:
                names = json.load(f).get('names') or []
        except (OSError, ValueError):
            names = []
        models = ai_providers.route_models('text_light', names or gc.DEFAULT_NAMES, fallback=False)
        return gemini_quota.queue_room(gc.key_id(g.api_key), models)
    except Exception:
        return True


def _ensure_worker():
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name='summary-queue', daemon=True)
            _worker.start()


def _run():
    import gemini_quota
    while True:
        _p, _s, case, cookies = _q.get()
        key = _key(case)
        if daily_left() <= 0 or not quota_room():      # سقف اليوم أو 70% من Lite: تنتظر الغد (لا تُحسب فشلاً)
            _status['capped'] += 1
            with _lock:
                cbs = _waiting.pop(key, [])
            for cb in cbs:
                try:
                    cb('')
                except Exception:
                    pass
            _q.task_done()
            continue
        _status['busy'] = key
        summary, note = '', ''
        _count_today()
        try:
            with gemini_quota.mode('queue'):
                summary = (PROCESS or process)(case, cookies) or ''
        except Exception as e:                         # أي فشل: يُحفظ ولا يُعاد قبل المهلة (لا عاصفة إعادات)
            note = f'{type(e).__name__}: {e}'
        ok = bool(summary) and not summary.startswith(_LOCAL_MARK)   # الملخص المحلي يُعرض ويُعاد بالذكاء بعد المهلة
        _remember(case, ok, note)
        _status['done' if ok else 'failed'] += 1
        _status['busy'] = ''
        _log(key, summary, note)
        with _lock:
            cbs = _waiting.pop(key, [])
        for cb in cbs:
            try:
                cb(summary)
            except Exception:
                pass
        _q.task_done()


def _log(key, summary, note):
    try:
        import ai_call_log
        ai_call_log.record('ملخص القضية (خلفي)', bool(summary), '', 0.0, f'{key}: {note or summary[:80]}')
    except Exception:
        pass


# ---------- خط المعالجة ----------

def claim_markdown(base, data, pdf_path=None, doc_id=''):
    """نص الصحيفة markdown من المحفوظ في مجلد القضية (المسار الواحد case_sources.store_claim / find_claim: لا نسخة جديدة
    لصحيفة محفوظة) — وإلا تحويل واحد يُسجَّل في manifest (فلا تعيده مزامنة المجلد) وبجانبها. يرجع (النص، المسار النسبي)."""
    import case_folder as cf
    import case_sources
    import case_workspace as cw
    if pdf_path and not os.path.abspath(pdf_path).startswith(os.path.abspath(base) + os.sep):
        case_sources.store_claim(base, data, pdf_path, doc_id=doc_id)
    if not case_sources.find_claim(base, data):
        raise ValueError('لا صحيفة دعوى محفوظة')
    rec = case_sources.record(data, 'claim')
    rec['sha1'] = case_sources._sha1(os.path.join(base, rec['file']))
    rel = rec['file']
    got = case_sources.load_text(base, data, 'claim')
    if got:
        return got[0], rel
    man = cf.load_manifest(base)
    e = man['files'].get(rel) or {}
    md_path = os.path.join(base, e.get('md') or cf.md_rel(rel))
    if e.get('state') == 'done' and e.get('sha1') == rec['sha1'] and os.path.isfile(md_path):
        with open(md_path, encoding='utf-8') as f:
            text = f.read()
    else:
        convert = cf.CONVERTER or cf._default_convert
        text, _pages, engine = convert(os.path.join(base, rel), cf.PLAINT)[:3]
        if not (text or '').strip():
            raise ValueError('لم يُستخرج نص من الصحيفة')
        cf._write_md(base, cf.md_rel(rel), text)
        cf.record_converted(base, rel, cf.md_rel(rel))
        rec['engine'] = engine
    case_sources.save_text(base, data, 'claim', text)
    cw.write_case_json(base, data)
    return text, rel


def summarize_text(text, ask=None):
    """طلب واحد لمهمة text_light (ai_providers.MODEL_ROUTES) على نص الصحيفة."""
    import summarizer
    if ask is None:
        import case_research
        ask = lambda p: case_research.default_ask(p, 'summarize', timeout=90)     # noqa: E731
    body = text if len(text) <= 20_000 else text[:20_000]           # الملخص سطر واحد: بداية الصحيفة وطلباتها تكفي
    out = (ask(summarizer.SUMMARY_PROMPT + '\n\nنص صحيفة الدعوى:\n' + body) or '').strip().strip('"«»').strip()
    return ' '.join(out.split())


def process(case, cookies):
    """الخط الكامل لقضية واحدة. يرجع الملخص ('' إن لا صحيفة)."""
    import case_db
    import case_workspace as cw
    import documents as dm
    caso_no = _key(case)
    autocase_no = case.get('autocase_no') or ''
    import case_sources
    fd, tmp = tempfile.mkstemp(suffix='.pdf', prefix='claim_')
    os.close(fd)
    try:
        try:
            base, data = cw.ensure_workspace(case)
        except Exception:                               # بلا مجلد قضية (لم يُضبط الجذر)
            base = data = None
        local = case_sources.find_claim(base, data) if base else None
        if local:                                       # الصحيفة محفوظة في القضية: لا تنزيل جديد
            saved, row = local, None
        else:
            row, saved, st = dm.get_claim_for_case(cookies, autocase_no, USER_ID, tmp)
            if st != 'OK':
                case_db.save_case(caso_no, autocase_no=autocase_no, case_summary=st)
                return ''
        try:
            if base is None:
                raise ValueError('لا مجلد قضية')
            text, _rel = claim_markdown(base, data, None if local else saved,
                                        doc_id=(row or {}).get('doc_id') or '')
        except Exception:                               # بلا مجلد قضية: نص بلا حفظ
            import case_convert
            text = case_convert.convert(saved, '')[0]
        try:
            summary = summarize_text(text)
        except Exception:
            import summarizer                           # بلا مزوّد/نفدت الحصة: ملخص محلي من طلبات الصحيفة (لا يُحفظ)
            return summarizer._local_summary(saved, '')[0] or ''
        if summary:
            case_db.save_case(caso_no, autocase_no=autocase_no, case_summary=summary)
        return summary
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
