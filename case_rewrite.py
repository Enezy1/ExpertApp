# ===== case_rewrite.py — «إعادة الكتابة» للموضوع والإجراءات (2026-10-18) =====
# الزر يرسل الحقائق المتحقَّق منها + النص الحالي إلى مزوّد «الصياغة» (write = جيميناي بحسب جدول المزوّدين)
# لإعادة الصياغة ولو لم يُضف جديد. الضمانة: لا رقم ولا تاريخ في النص الجديد إلا وهو في النص الحالي أو الحقائق؛
# وإلا يُعاد الطلب مرة بتنبيه، ثم يُرفض (يبقى النص كما هو والخطأ بنص واضح).
# حماية النص اليدوي: is_manual(data, key) — الواجهة تطلب تأكيداً قبل الاستبدال؛ لا استبدال تلقائي أبداً.
import json
import re

import case_model as cm

_NUM = re.compile(r'\d[\d,./\\-]*\d|\d')
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


class RewriteError(cm.StepError):
    pass


def numbers(text):
    """الأرقام بقيمتها (الفواصل لا تهمّ): «5,876.540» = «5876.540»."""
    out = set()
    for m in _NUM.finditer((text or '').translate(_DIGITS)):
        for part in re.split(r'[/\\-]', m.group(0)):
            v = part.replace(',', '').strip('.')
            if v:
                out.add(v.lstrip('0') or '0')
    return out


def foreign_numbers(new, *sources):
    allowed = set()
    for s in sources:
        allowed |= numbers(s if isinstance(s, str) else json.dumps(s, ensure_ascii=False))
    return sorted(numbers(new) - allowed)


def is_manual(data, key):
    if key == 'subject':
        return bool(data.get('subject_edited'))
    if key == 'procedures':
        return bool((data.get('procedures') or {}).get('edited'))
    if key == 'mission':
        return bool((data.get('mission') or {}).get('edited'))
    return False


def build_prompt(kind, text, facts, rules='', bad=None):
    label = {'subject': 'الموضوع', 'procedures': 'الإجراءات'}[kind]
    p = (f"أنت خبير قضائي. أعد صياغة فقرة «{label}» في تقرير الخبرة بلغة قضائية سليمة واضحة يفهمها القاضي من أول قراءة، "
         "بأسلوب قواعد الصياغة أدناه. لا تضف واقعة ولا رقماً ولا تاريخاً غير وارد في «النص الحالي» أو «الحقائق»؛ "
         "لا تحذف واقعة واردة؛ الأسماء لا تُذكر بل الصفات؛ لا أقواس فارغة ولا «[يُكتب]» إلا إن وردت في النص الحالي.\n\n"
         f"قواعد الصياغة:\n{rules}\n\nالحقائق المتحقَّق منها:\n{json.dumps(facts or {}, ensure_ascii=False, indent=1)}\n\n"
         f"النص الحالي:\n{text}\n\n")
    if bad:
        p += "تنبيه: صياغتك السابقة أضافت أرقاماً غير واردة: " + '، '.join(bad) + ". أعدها دونها.\n"
    return p + "أعد الفقرة فقط نصاً عادياً."


def rephrase(kind, text, facts, ask, rules=''):
    """النص المعاد صياغته بعد التحقق، أو RewriteError."""
    if ask is None:
        raise RewriteError('لا يتوفر مزوّد ذكاء اصطناعي لإعادة الصياغة.')
    if not (text or '').strip():
        raise RewriteError('لا نص لإعادة صياغته.')
    bad = None
    for _ in range(2):
        out = ' '.join(str(ask(build_prompt(kind, text, facts, rules, bad)) or '').split()) if kind == 'subject' \
            else '\n\n'.join(' '.join(p.split()) for p in str(ask(build_prompt(kind, text, facts, rules, bad)) or '').split('\n\n') if p.strip())
        bad = foreign_numbers(out, text, facts)
        import ai_call_log
        ai_call_log.verdict(bool(out.strip() and not bad), 'صياغة سليمة' if out.strip() and not bad
                            else 'أرقام غير واردة: ' + '، '.join(bad or ['نص فارغ']))
        if out.strip() and not bad:
            return out
    raise RewriteError('رُفضت الصياغة الجديدة: أضاف النموذج أرقاماً غير واردة (' + '، '.join(bad or ['نص فارغ']) + ')')


def _rules(kind):
    try:
        import drafting_library as dl
        return dl.load(dl.SUBJECT_FILE if kind == 'subject' else dl.PROCEDURES_FILE)[0]
    except Exception:
        return ''


def rewrite_subject(base, data, ask):
    """يعيد صياغة الموضوع الحالي من حقائقه. بلا نص حالي ← RewriteError (المستدعي يشغّل run_subject)."""
    import case_subject_mission as sm
    facts = data.get('subject_facts') or {}
    new = rephrase('subject', data.get('subject') or '', facts, ask, _rules('subject'))
    data['subject'] = new
    data['subject_edited'] = False
    st = cm.state(data, 'subject')
    if st in cm.OK_STATES:
        cm.mark_modified(data, 'subject')
        if st == 'reviewed':
            cm.set_step(data, 'subject', 'done', 'أُعيدت صياغته بالذكاء الاصطناعي')
    else:
        if st != 'needs_input':
            cm.set_step(data, 'subject', 'needs_input')
        cm.set_step(data, 'subject', 'done', 'أُعيدت صياغته بالذكاء الاصطناعي')
    sm._save(base, data, 'case')
    return cm.state(data, 'subject')


def rewrite_procedures(base, data, ask):
    """«إعادة الكتابة» للإجراءات = إعادة القراءة والحساب ثم النص من الصيغة المعتمدة (نماذج_صياغة_الإجراءات.md) حرفياً.
    لا يُرسل نص إلى الذكاء للصياغة أبداً (كان يؤلّف ما جرى في الجلسات)؛ الذكاء يستخرج الحقائق فقط داخل evaluate:
    الحضور والتخلف والانتقال/المعاينة/الشهود، والاستلام والحجز من النظام."""
    import case_procedures as cp
    proc = data.setdefault('procedures', {})
    cp.evaluate(base, data, ask)
    proc.update(text=cp.compose_text(data), edited=False)
    proc.pop('edited_by', None)
    proc.pop('changed_notice', None)
    if cm.state(data, 'procedures') in cm.OK_STATES:
        cm.mark_modified(data, 'procedures')
    cp._save(base, data)
    return cm.state(data, 'procedures')
