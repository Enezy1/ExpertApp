# ===== doc_header.py — رأس نوع المستند في أول كل ملف markdown (2026-10-25) =====
# بعد الفرز يُكتب في أول سطر من markdown كل أصل تعليق HTML ثابت الصيغة:
#   <!-- ترويسة المستند | النوع: حافظة مستندات | المقدّم: المدعية | التاريخ: 15-10-2025 | المحضر: — | نسخة الفرز: 4 | بصمة الأصل: … -->
# تقرؤه بقية الخطوات (الملخص، الجاهزية، التقرير) بالكود دون أي طلب (read/parse). الرأس بيانات وصفية فقط: يُحذف (strip) قبل
# أي تحقق حرفي (case_triage.verify) حتى لا «يثبت» تاريخ أو صفة من الرأس نفسه. علامة «حكم خبير (حكم الإحالة)» تبقى أول
# سطر في النص بعد الرأس، وreferral_pick يقرؤها بعد حذف الرأس.
import os
import re

TAG = 'ترويسة المستند'
FIELDS = (('type', 'النوع'), ('by', 'المقدّم'), ('date', 'التاريخ'), ('minute', 'المحضر'), ('v', 'نسخة الفرز'),
          ('sha1', 'بصمة الأصل'))
_LINE = re.compile(r'\A﻿?[ \t]*<!--\s*' + TAG + r'\s*\|(.*?)-->[ \t]*(?:\r?\n)?', re.S)
EMPTY = '—'


def _clean(v):
    v = ' '.join(str(v if v not in (None, '') else EMPTY).split())
    return v.replace('|', '/').replace('-->', '—>') or EMPTY


def render(info):
    """سطر الرأس من dict بالمفاتيح type/by/date/minute/v/sha1 (الناقص «—»)."""
    return '<!-- ' + TAG + ' | ' + ' | '.join(f'{ar}: {_clean(info.get(k))}' for k, ar in FIELDS) + ' -->'


def parse(text):
    """dict الرأس من أول النص، أو {} إن لم يوجد. القيمة «—» ← ''."""
    m = _LINE.match(text or '')
    if not m:
        return {}
    names = {ar: k for k, ar in FIELDS}
    out = {}
    for piece in m.group(1).split('|'):
        k, sep, v = piece.partition(':')
        key = names.get(k.strip())
        if key and sep:
            v = v.strip()
            out[key] = '' if v == EMPTY else v
    return out


def strip(text):
    """النص بلا سطر الرأس (كما كان قبل كتابته)."""
    return _LINE.sub('', text or '', count=1)


def apply(text, info):
    """النص برأس جديد مكان القديم (أو قبله إن لم يوجد)."""
    return render(info) + '\n' + strip(text)


_TYPE = {'حافظة': 'حافظة مستندات', 'مذكرة': 'مذكرة دفاع', 'محضر': 'محضر خبرة', 'حكم': 'حكم', 'صحيفة': 'صحيفة دعوى',
         'تقرير': 'تقرير خبرة سابق', 'أخرى': 'غير مصنَّف'}


def info_from_triage(triage, sha1=''):
    """الرأس من نتيجة الفرز المتحقَّقة (e['triage']): أول جزء حقيقي، والملف المختلط أنواعه مجتمعة."""
    parts = [p for p in (triage or {}).get('parts') or [] if p.get('type') != 'أخرى'] or (triage or {}).get('parts') or []
    p0 = parts[0] if parts else {}
    kinds = list(dict.fromkeys(_TYPE.get(p.get('type'), p.get('type') or '') for p in parts if p.get('type')))
    return {'type': ' و'.join(k for k in kinds if k) or 'غير مصنَّف', 'by': p0.get('label') or '',
            'date': p0.get('date') or '', 'minute': '' if p0.get('minute_no') is None else str(p0.get('minute_no')),
            'v': str((triage or {}).get('v') or ''), 'sha1': sha1 or (triage or {}).get('sha1') or ''}


def write(base, md_rel, info):
    """يكتب الرأس في ملف markdown (ذرّياً) دون مسّ بقية نصه. يرجع True إن تغيّر الملف. فشل الكتابة صامت."""
    path = os.path.join(base, md_rel or '')
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return False
    new = apply(text, info)
    if new == text:
        return False
    try:
        import case_folder as cf
        cf._write_md(base, md_rel, new)
        return True
    except OSError:
        return False


def read(base, md_rel):
    """الرأس المكتوب في ملف markdown (بلا أي طلب)، أو {}."""
    try:
        with open(os.path.join(base, md_rel or ''), encoding='utf-8') as f:
            return parse(f.read(2000))
    except OSError:
        return {}
