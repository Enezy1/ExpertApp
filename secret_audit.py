# ===== secret_audit.py — أين تُخزَّن مفاتيح API بنص صريح؟ (2026-10-17) =====
# يفحص فقط (لا يغيّر ولا يرسل شيئاً ولا يعرض قيمة مفتاح): gemini_network.ini، ai_providers_cache.json، ومفاتيح الخبير
# (gemini_key.json / ocr_key.json / vision_key.json / openai_key.json) + سجلات التشغيل (تسرّب مفتاح في سطر).
# المفتاح الصريح = قيمة غير فارغة بلا ختم تشفير «dpapi:». (2026-10-21) المفاتيح الشخصية ونسخة القسم المحلية تُشفَّر
# بـDPAPI (secret_store.py) مع ترحيل تلقائي؛ هذا الفحص يكشف ما بقي صريحاً (غالباً gemini_network.ini فقط).
import configparser
import json
import os

import gemini_config as gc
from current_expert import expert_data_dir

PROPOSAL = ('المفاتيح الشخصية ونسخة القسم المحلية تُشفَّر تلقائياً بـDPAPI؛ انقل أي مفتاح بقي في gemini_network.ini '
            'إلى شاشة الأدمن (المزودات) ثم احذفه من الملف.')


def _cache_path():
    try:
        import provider_sync
        return provider_sync._CACHE_PATH
    except Exception:
        return os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'ai_providers_cache.json')


def _json_keys(path, names):
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return 0
    rows = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in names and isinstance(v, str) and v.strip() and not v.startswith(('enc:', 'dpapi:')):
                    rows.append(k)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    return len(rows)


def find_plaintext_keys():
    """[(مسار الملف، عدد المفاتيح الصريحة)] — لا قيم."""
    out = []
    ini = os.path.join(gc._app_dir(), gc._NET_INI_NAME)
    try:
        cp = configparser.RawConfigParser()
        cp.read(ini, encoding='utf-8')
        n = sum(1 for s in cp.sections() for k, v in cp.items(s) if k == 'api_key' and v.strip())
        if n:
            out.append((ini, n))
    except Exception:
        pass
    cache = _cache_path()
    n = _json_keys(cache, {'api_key'})
    if n:
        out.append((cache, n))
    d = expert_data_dir()
    for name, key in (('gemini_key.json', 'gemini_api_key'), ('ocr_key.json', 'ocr_api_key'),
                      ('vision_key.json', 'vision_api_key'), ('openai_key.json', 'openai_api_key')):
        p = os.path.join(d, name)
        if _json_keys(p, {key}):
            out.append((p, 1))
    return out


def _log_paths():
    paths = [gc._LOG_PATH, gc._LOG_PATH + '.old',
             os.path.join(os.environ.get('LOCALAPPDATA') or '', 'ExpertApp', 'ai_calls.log')]
    return [p for p in paths if p and os.path.exists(p)]


def find_key_leaks_in_logs():
    """[(مسار السجل، عدد الأسطر التي يظهر فيها مفتاح كامل)] — لا قيم تُعرض ولا تُحفظ."""
    out = []
    for p in _log_paths():
        n = 0
        try:
            with open(p, encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if gc._SECRET_RE.search(line):
                        n += 1
        except OSError:
            continue
        if n:
            out.append((p, n))
    return out


def warning_text():
    """نص التحذير للإعدادات، أو '' إن لم توجد مفاتيح صريحة."""
    found = find_plaintext_keys()
    if not found:
        return ''
    lines = [f'• {os.path.basename(p)}: {n} مفتاح' for p, n in found]
    return ('⚠ مفاتيح API مخزّنة بنص صريح على هذا الجهاز (يقرؤها أي من يصل لملفاتك أو نسخك الاحتياطية):\n'
            + '\n'.join(lines) + '\n' + PROPOSAL)
