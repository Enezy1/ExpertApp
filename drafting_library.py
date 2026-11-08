# ===== drafting_library.py — قراءة/كتابة مكتبتي الصياغة (نماذج_صياغة_الموضوع.md / نماذج_صياغة_الإجراءات.md) =====
# الملفان في مجلد البرنامج (BASE_DIR) ويُحمَّلان عند كل توليد؛ الخبير يعدّلهما بيده أو بزر «احفظ هذا النص كنموذج».
# الشكل:  «# القواعد» (نص حر) ثم «# النماذج» وتحته أقسام «## عنوان» ويليه (اختيارياً، بأي ترتيب) سطرا
#   «النوع: مفتاح_النوع» و«الكلمات: كلمة، كلمة» ثم نص النموذج. هذا الملف لا يلمس مجلد التقارير أبداً.
# الإضافة من الخبير: تُكتب في ملف البرنامج، وإن تعذّرت الكتابة (Program Files/EXE) ففي نسخة الخبير
# (expert_data_dir) التي تُحمَّل بعده ويتقدّم نموذجها المكرَّر العنوان.
import os
import re

import config

SUBJECT_FILE = 'نماذج_صياغة_الموضوع.md'
PROCEDURES_FILE = 'نماذج_صياغة_الإجراءات.md'
RESEARCH_FILE = 'نماذج_صياغة_البحث.md'          # البحث ورأي الخبرة + «قواعد النتيجة» (2026-10-20)
RULES_HEAD = '# القواعد'
MODELS_HEAD = '# النماذج'


def program_path(name):
    return os.path.join(config.BASE_DIR, name)


def user_path(name):
    from current_expert import expert_data_dir
    return os.path.join(expert_data_dir(), name)


def _read(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def parse(md):
    """(rules, [{'title','type','tags','text'}]) من نص الملف."""
    md = md or ''
    rules = section(md, 'القواعد')
    rules = re.split(r'(?m)^##\s+', rules)[0]
    models = []
    body = md
    mm = re.search(r'(?m)^#\s+النماذج\s*$', md)
    if mm:
        body = md[mm.end():]
    for block in re.split(r'(?m)^##\s+', body)[1:]:
        lines = block.strip('\n').split('\n')
        title, rest = lines[0].strip(), lines[1:]
        kind, tags = '', []
        while rest and re.match(r'\s*(النوع|الكلمات)\s*:', rest[0]):
            key, _sep, val = rest[0].partition(':')
            if key.strip() == 'النوع':
                kind = val.strip()
            else:
                tags = [t.strip() for t in re.split(r'[،,]', val) if t.strip()]
            rest = rest[1:]
        text = '\n'.join(rest).strip()
        if title and text:
            models.append({'title': title, 'type': kind, 'tags': tags, 'text': text})
    return rules.strip(), models


def section(md, title):
    """نص القسم «# title» حتى العنوان التالي من المستوى نفسه («# …»)، أو '' إن لم يوجد."""
    m = re.search(rf'(?m)^#\s+{re.escape(title)}\s*$', md or '')
    if not m:
        return ''
    end = re.search(r'(?m)^#\s+\S', md[m.end():])
    return (md[m.end(): m.end() + end.start()] if end else md[m.end():]).strip()


def load_section(name, title, override_path=None):
    """قسم مسمّى (مثل «قواعد النتيجة») من ملف البرنامج، ونسخة الخبير تتقدّم إن احتوته."""
    if override_path:
        return section(_read(override_path), title)
    try:
        mine = section(_read(user_path(name)), title)
    except Exception:
        mine = ''
    return mine or section(_read(program_path(name)), title)


def render(m):
    head = f"## {m['title']}\n"
    if m.get('type'):
        head += f"النوع: {m['type']}\n"
    if m.get('tags'):
        head += f"الكلمات: {'، '.join(m['tags'])}\n"
    return head + m['text'].strip() + '\n'


def load(name, override_path=None):
    """(rules, models). override_path (للاختبارات) يحلّ محل ملفي البرنامج والخبير. الملف المفقود ← ('', [])."""
    if override_path:
        return parse(_read(override_path))
    rules, models = parse(_read(program_path(name)))
    try:
        u_rules, u_models = parse(_read(user_path(name)))
    except Exception:
        u_rules, u_models = '', []
    seen = {m['title']: i for i, m in enumerate(models)}
    texts = {' '.join(m['text'].split()) for m in models}
    for m in u_models:                       # نماذج الخبير الإضافية تتقدّم على المكرَّر العنوان
        if ' '.join(m['text'].split()) in texts:
            continue                         # نسخة قديمة مزروعة من نموذج موجود في ملف البرنامج
        if m['title'] in seen:
            models[seen[m['title']]] = m
        else:
            models.append(m)
    return u_rules or rules, models


def append_model(name, model, override_path=None):
    """يضيف نموذجاً (يرجع مسار الملف المكتوب). ملف البرنامج أولاً، وعند تعذّر الكتابة نسخة الخبير."""
    block = '\n' + render(model)
    if override_path:
        paths = [override_path]
    else:
        paths = [program_path(name), user_path(name)]
    last = None
    for p in paths:
        try:
            if not os.path.exists(p):
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, 'w', encoding='utf-8') as f:
                    f.write(f'{MODELS_HEAD}\n')
            with open(p, 'a', encoding='utf-8') as f:
                f.write(block)
            return p
        except OSError as e:
            last = e
    raise last
