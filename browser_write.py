# ===== browser_write.py — الكتابة عبر المتصفح للمرحلتين الثانية والثالثة (2026-10-21) =====
# بديل «جيميناي (API)» يختاره الخبير من زر بجانب «أعد الكتابة» (لكل مرحلة: data['ai_mode'][stage] = api | browser):
#   1) البرنامج يجهّز نفس الطلب حرفياً (الملخص + القواعد + النماذج + شكل JSON المطلوب) — prepare.
#   2) يفتح المتصفح على الموقع المختار: Copilot، أو أحد مواقع browser-ai-bot التي أضافها الخبير (config.json).
#      إن كان الموقع من مواقع browser-ai-bot والبرنامج متوفراً ← يلصق الطلب ويأخذ الرد تلقائياً (auto_send)؛
#      وإلا يُنسخ الطلب إلى الحافظة ويُفتح الموقع ليلصقه الخبير.
#   3) زر «لصق الرد» ← accept: الرد يمر على نفس التحقق بالكود (case_stage2.apply_reply / report_v3.import_full_reply)،
#      ويُذكر في «كُتب بواسطة»: «عبر المتصفح (اسم الموقع)».
import json
import os

import case_workspace as cw

STAGES = ('stage2', 'stage3')
STAGE_LABELS = {'stage2': 'الموضوع والإجراءات والمرفقات', 'stage3': 'البحث ورأي الخبرة'}
MODES = (('api', 'جيميناي (API)'), ('browser', 'عبر المتصفح'))
COPILOT = {'key': 'copilot', 'label': 'Copilot', 'url': 'https://copilot.microsoft.com/', 'auto': False}
PROMPT_REL = '_نظام/04_تقرير/طلب_المتصفح_{stage}.md'


def sites():
    """[{key,label,url,auto}] — Copilot أولاً ثم مواقع browser-ai-bot (لصق تلقائي إن كان البرنامج متوفراً)."""
    out = [dict(COPILOT)]
    try:
        import ai_providers
        d = ai_providers.BrowserProvider.bot_dir()
    except Exception:
        d = None
    if not d:
        return out
    try:
        with open(os.path.join(d, 'config.json'), encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return out
    for p in cfg.get('providers') or []:
        url = p.get('site_url') or ''
        if not url or p.get('enabled') is False and p.get('name') != 'copilot':
            continue
        if p.get('name') == 'copilot':
            out[0].update(auto=p.get('enabled') is not False)     # الرابط copilot.microsoft.com دائماً (لا m365)
            continue
        out.append({'key': p.get('name'), 'label': p.get('name'), 'url': url, 'auto': True})
    return out


def site(key):
    return next((s for s in sites() if s['key'] == key), dict(COPILOT))


def mode(data, stage):
    return ((data.get('ai_mode') or {}).get(stage) or 'api')


def set_mode(base, data, stage, value):
    data.setdefault('ai_mode', {})[stage] = value if value in dict(MODES) else 'api'
    cw.write_case_json(base, data)


def chosen_site(data):
    return (data.get('ai_mode') or {}).get('site') or COPILOT['key']


def set_site(base, data, key):
    data.setdefault('ai_mode', {})['site'] = key
    cw.write_case_json(base, data)


def prepare(base, data, stage):
    """نص الطلب نفسه الذي يُرسل عبر API، ويُحفظ ملفاً للمراجعة. يرجع (النص، المسار)."""
    if stage == 'stage2':
        import case_stage2
        s = case_stage2.state(data)
        miss = case_stage2.missing_inputs(base, data)
        if 'صحيفة الدعوى' in miss:
            import case_model as cm
            raise cm.StepError('ينقص: صحيفة الدعوى — لا يُكتب الموضوع قبلها.')
        text = case_stage2.build_prompt(base, data)
        s['browser_sig'] = case_stage2.signature(base, data)
    else:
        import report_v3
        text = report_v3.browser_prompt(base, data)
    import case_documents as cd
    rel = PROMPT_REL.format(stage=stage)
    cd._write_md(base, rel, text)
    data.setdefault('ai_mode', {}).setdefault('prepared', {})[stage] = {'at': _now()}
    cw.write_case_json(base, data)
    return text, os.path.join(base, rel)


def auto_send(site_key, prompt):
    """يلصق الطلب في الموقع عبر browser-ai-bot ويرجع الرد، أو يرفع استثناءً (يُنسخ للحافظة حينها)."""
    import ai_providers
    if not ai_providers.BrowserProvider.bot_dir():
        raise RuntimeError('browser-ai-bot غير متوفر على هذا الجهاز')
    p = ai_providers.BrowserProvider('browser', '', order=[site_key], max_seconds=600)
    return p._run(prompt, [], 600).text


def accept(base, data, stage, reply, site_key=''):
    """الرد الملصوق ← نفس التحقق بالكود. يرجع ملخص القبول/الرفض."""
    import case_model as cm
    if not (reply or '').strip():
        raise cm.StepError('الرد فارغ — الصق الرد كاملاً.')
    label = site(site_key)['label'] if site_key else 'المتصفح'
    if stage == 'stage2':
        import case_stage2
        try:
            return case_stage2.apply_reply(base, data, reply, source=f'browser:{label}')
        except ValueError as e:
            raise cm.StepError(f'لم أجد JSON صالحاً في الرد ({e}).')
    import report_v3
    return report_v3.import_full_reply(base, data, reply, source=f'browser:{label}')


_BROWSERS = (r'%ProgramFiles%\Google\Chrome\Application\chrome.exe',
             r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe',
             r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe',
             r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe',
             r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe',
             r'%ProgramFiles%\Mozilla Firefoxirefox.exe')


def browser_exe():
    """مسار متصفح حقيقي (Chrome ثم Edge ثم Firefox). لا نمرّر الرابط لنظام ويندوز مباشرة: روابط Copilot
    تفتح برنامج Copilot المثبَّت بدل المتصفح."""
    for p in _BROWSERS:
        x = os.path.expandvars(p)
        if os.path.isfile(x):
            return x
    return ''


def open_site(url, launcher=None):
    """يفتح الرابط في نافذة متصفح جديدة ظاهرة بحجم كامل. يرجع الأمر المستعمل (للاختبار)."""
    import subprocess
    exe = browser_exe()
    if exe:
        args = [exe, '--new-window', '--start-maximized', url] if 'firefox' not in exe.lower() else [exe, '-new-window', url]
    else:                                   # بلا متصفح معروف: المتصفح الافتراضي عبر webbrowser (لا بروتوكول التطبيق)
        import webbrowser
        (launcher or webbrowser.open_new)(url)
        return ['webbrowser', url]
    (launcher or (lambda a: subprocess.Popen(a, close_fds=True)))(args)
    return args


def _now():
    from datetime import datetime
    return datetime.now().isoformat(timespec='seconds')
