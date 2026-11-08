# ===== loop_guard.py — كشف التحويل الدائر في حلقة (2026-10-21) =====
# نماذج القراءة (جيميناي خصوصاً) قد تعلق فتكرر السطر/الجملة نفسها حتى نهاية حدّ الإخراج. الفحص على الناتج:
#   (1) سطر غير قصير يتكرر أكثر من MAX_LINE_REPEAT مرة،
#   (2) n-gram طويل (NGRAM كلمة) يتكرر أكثر من MAX_NGRAM_REPEAT مرة،
#   (3) طول غير منطقي مقارنة بعدد الصفحات (> MAX_CHARS_PER_PAGE لكل صفحة)،
#   (4) ذيل النص: الجزء الأخير مكوَّن من وحدة واحدة مكررة (تكرار متصل بلا فواصل أسطر).
# المهلة بلا تقدّم تُراقَب في case_folder.convert_guarded (watchdog). ناتج فيه حلقة لا يُحفظ أبداً.
import re
from collections import Counter

MAX_LINE_REPEAT = 12           # سطر (≥ MIN_LINE_CHARS) يتكرر أكثر من هذا ← حلقة
MIN_LINE_CHARS = 25
NGRAM = 12                     # n-gram طويل
MAX_NGRAM_REPEAT = 15
MAX_CHARS_PER_PAGE = 12000     # صفحة A4 كثيفة جداً ≈ 4–6 آلاف حرف
TAIL_CHARS = 3000
TAIL_MIN_UNIT, TAIL_MAX_UNIT = 8, 400

_COMMENT = re.compile(r'<!--.*?-->', re.S)
_WS = re.compile(r'\s+')
# أسطر تتكرر مشروعة: فواصل الصفحات وخطوط الجداول والرؤوس المتكررة القصيرة
_BENIGN = re.compile(r'^(?:[-=|:_\s*#]+|---\s*صفحة\s*\d+\s*---|=====PAGE=====)$')


class LoopDetected(Exception):
    """التحويل دار في حلقة؛ الرسالة سبب واضح بالعربي."""


def _lines(text):
    for raw in _COMMENT.sub('\n', text or '').splitlines():
        line = _WS.sub(' ', raw).strip()
        if len(line) >= MIN_LINE_CHARS and not _BENIGN.match(line):
            yield line


def _tail_loop(text):
    """يرجع الوحدة المكررة إن كان ذيل النص تكراراً متصلاً لوحدة واحدة (≥ 6 مرات)."""
    tail = _WS.sub(' ', (text or '')[-TAIL_CHARS:]).strip()
    if len(tail) < TAIL_MIN_UNIT * 6:
        return None
    for size in range(TAIL_MIN_UNIT, min(TAIL_MAX_UNIT, len(tail) // 6) + 1):
        unit = tail[-size:]
        reps, pos = 0, len(tail)
        while pos - size >= 0 and tail[pos - size:pos] == unit:
            reps += 1
            pos -= size
        if reps >= 6 and reps * size >= len(tail) * 0.5 and len(set(unit.strip())) > 3:
            return unit.strip()
    return None


def detect(text, pages=0):
    """سبب الحلقة (نص عربي) أو None."""
    if not text:
        return None
    # تذييل/رأس يتكرر مرة في كل صفحة (فواتير بتذييل ثابت) ليس حلقة: الحد يكبر بعدد الصفحات (مرتان لكل صفحة)
    line_max, gram_max = max(MAX_LINE_REPEAT, 2 * (pages or 0)), max(MAX_NGRAM_REPEAT, 2 * (pages or 0))
    lines = Counter(_lines(text))
    if lines:
        line, n = lines.most_common(1)[0]
        if n > line_max:
            return f'تكرار السطر نفسه {n} مرة: «{line[:60]}»'
    words = _WS.sub(' ', _COMMENT.sub(' ', text)).split()
    if len(words) >= NGRAM * MAX_NGRAM_REPEAT:
        grams = Counter(tuple(words[i:i + NGRAM]) for i in range(0, len(words) - NGRAM + 1))
        g, n = grams.most_common(1)[0]
        if n > gram_max and len(set(g)) > 3:
            return f'تكرار عبارة طويلة {n} مرة: «{" ".join(g)[:60]}»'
    if pages and len(text) > MAX_CHARS_PER_PAGE * max(1, pages):
        return f'طول الناتج غير منطقي ({len(text)} حرفاً لـ{pages} صفحة)'
    unit = _tail_loop(text)
    if unit:
        return f'نهاية النص تكرار متصل لـ«{unit[:60]}»'
    return None


def check(text, pages=0):
    """يرفع LoopDetected إن وُجدت حلقة."""
    why = detect(text, pages)
    if why:
        raise LoopDetected(why)
    return text
