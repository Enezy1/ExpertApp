# ===== qt_bidi.py — اتجاه العربية للعرض فقط: عزل التواريخ والأرقام والمبالغ و«[يُكتب]» (2026-10-17) =====
# الدالة المخصصة للمشروع في qt_theme.ltr تلفّ بـ U+2066…U+2069. هنا نطبّقها على رموز محددة داخل نص عربي عند العرض
# فقط: النص المخزَّن (case.json) والمكتوب في Word لا يتغيّران أبداً؛ المحرّر يجرّد المحارف الاتجاهية عند toPlainText.
import re

from PyQt6.QtWidgets import QPlainTextEdit

LRI, RLI, FSI, PDI = '⁦', '⁧', '⁨', '⁩'
_CTRL = re.compile('[⁦-⁩]')
# بين قوسين مربعين (مثل «[يُكتب]» و«[ناقص: …]») | تاريخ/رقم بفواصل | رقم/مبلغ مع د.ك | رمز لاتيني+رقم (A2263981)
_TOKEN = re.compile(r'(\[[^\]\n]{1,80}\])|(\d{1,4}(?:[/.\-]\d{1,4}){1,2})|(\d[\d,]*(?:\.\d+)?(?:\s*د\.ك)?)'
                    r'|([A-Za-z]{1,3}\d[\w\-/]*)')


def strip_isolates(text):
    return _CTRL.sub('', text or '')


def isolate_tokens(text):
    """يعزل الرموز العددية واللاتينية (LRI) و«[…]» (FSI) للعرض. idempotent: لا يضاعف العزل. نص HTML يُترك."""
    if not text or '<' in text:
        return text
    text = strip_isolates(text)

    def wrap(m):
        s = m.group(0)
        return f'{FSI}{s}{PDI}' if m.group(1) else f'{LRI}{s}{PDI}'
    return _TOKEN.sub(wrap, text)


class BidiPlainTextEdit(QPlainTextEdit):
    """محرّر يعرض النص معزولاً ويعيد دائماً النص المنطقي (بلا محارف اتجاهية) من toPlainText."""

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        if text:
            self.setPlainText(text)

    def setPlainText(self, text):
        super().setPlainText(isolate_tokens(text))

    def toPlainText(self):
        return strip_isolates(super().toPlainText())
