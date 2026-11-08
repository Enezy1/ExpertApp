# ===== qt_case_page.py — «صفحة القضية» (مسار التقرير بشكل design/ و Stitch) =====
# بديل نافذة المسار القديمة بالشكل فقط: رأس (رجوع + رقم القضية + الأطراف) ← مسار أفقي بسبع خطوات
# ← بطاقة بيضاء واحدة لمحرّر الخطوة المفتوحة ← شريط سفلي (السابق | الأسئلة المهمة | إصدار التقرير | اعتماد والانتقال).
# كل المنطق مُعاد استخدامه: CasePageDialog يرث CaseTrackDialog (التنفيذ الخلفي، المحاضر، المستندات، الإصدار…)
# والحالات تُقرأ من case.json عبر reports_list_model.step_states. لا منطق حالات جديد هنا.
# «الإجراءات» تعمل وحدها عند فتح الخطوة (أخذ المحاضر + الجلسات + الحضور + الاعتماد)؛ الأزرار للتعديل فقط.
# «إعادة الكتابة» تعرض «جارٍ…» داخل البطاقة ثم النتيجة أو الخطأ بنص واضح (مع سطر من ai_call_log).
import os
import re
import threading
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit, QComboBox,
    QTabWidget, QListWidget, QLineEdit, QDialog, QMessageBox, QScrollArea, QSizePolicy, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QInputDialog,
)

import qt_theme as th
from qt_bidi import BidiPlainTextEdit, isolate_tokens
import qt_report_card as rc
from qt_case_track import CaseTrackDialog

import ai_call_log
import case_conclusion
import case_documents
import case_memory
import case_model
import case_procedures
import case_readiness
import case_research
import case_subject_mission as sm
import case_workspace
import conclusion_pipeline
import research_pipeline
import reports_list_model as rlm
from qt_documents_dialog import portfolio_colors
import qt_documents_dialog as qdd

NAVY, SLATE = rc.PRIMARY_DARK, rc.SECONDARY
TEAL = ('#DDF1EF', '#0B5F5A')
AMBER_TAG = (rc.AMBER_SOFT, rc.AMBER)
F = rc.FONT.replace("Tahoma", "Tahoma,'Segoe UI Symbol'")
LONG_LABELS = {'documents': 'المستندات', 'research': 'البحث ورأي الخبرة'}
EDITABLE = ('subject', 'mission', 'procedures', 'research', 'conclusion')
AUTOSAVE_MS = 1200


# ---------- دوال صرفة (للاختبار) ----------

def step_list(data):
    """[(key, اسم العرض, حالة معروضة, رسالة)] بالترتيب السباعي."""
    steps, _ = rlm.step_states(data)
    return [(k, LONG_LABELS.get(k, n), st, m) for k, n, st, m in steps]


def current_step(data):
    """الخطوة التي تُفتح افتراضياً: أول فاشلة/تحتاج مدخلاً/حالية، وإلا أول غير منتهية، وإلا الأخيرة."""
    steps = step_list(data)
    steps = [s for s in steps if s[0] != 'attachments'] + [s for s in steps if s[0] == 'attachments']
    if any(s[2] != rlm.ST_DONE for s in steps[:-1]):     # المرفقات آلية: لا تُفتح أولاً ما بقي غيرها
        steps = steps[:-1]
    for want in ((rlm.ST_FAILED, rlm.ST_INPUT, rlm.ST_CURRENT), (rlm.ST_IDLE,)):
        for k, _n, st, _m in steps:
            if st in want:
                return k
    return steps[-1][0]


def neighbour(key, delta):
    keys = [k for k, _ in rlm.DISPLAY_STEPS]
    i = keys.index(key) + delta
    return keys[i] if 0 <= i < len(keys) else None


def parties_line(data):
    pl, df, other = case_parties(data)
    if pl or df:
        return f"المدعي: {'، '.join(pl) or '—'}   ضد   المدعى عليه: {'، '.join(df) or '—'}"
    return f"الأطراف: {other}" if other else ''


def contracts(data):
    """العقود: المستخرجة من المحتوى (case_contracts) إن وُجدت، وإلا القديمة من رقم العقد في المستندات."""
    import case_contracts
    ai = case_contracts.items(data)
    if ai:
        return [dict(c, contract=c.get('date') or '', type=c['kind'], submitter='', pid=c['scope'], uid='', ai=True)
                for c in ai]
    out, seen = [], set()
    for p, d in case_documents.all_docs(data):
        c = (d.get('contract') or '').strip()
        if c and c not in seen:
            seen.add(c)
            out.append({'contract': c, 'type': d.get('type') or 'عقد', 'submitter': p.get('submitter', ''),
                        'pid': p['id'], 'uid': d['uid'], 'md': d.get('md') or ''})
    return out


def _md_has_text(base, rel):
    if not base or not rel:
        return True                     # بلا مجلد (اختبارات صرفة): الحالة وحدها
    try:
        with open(os.path.join(base, rel), encoding='utf-8') as f:
            return bool(re.sub(r'<!--.*?-->|\s', '', f.read(20000), flags=re.S))
    except OSError:
        return False


def content_title(d, index=None):
    """عنوان المستند من محتواه المقروء (النوع/التاريخ/الأطراف) لا من اسم الملف."""
    row = next((r for r in index or [] if r.get('file') == d.get('file')), {})
    kind = d.get('kind') if d.get('kind') and d.get('kind') != 'أخرى' else row.get('type') or d.get('kind') or ''
    date = d.get('doc_date') or row.get('date') or ''
    parties = d.get('parties') or row.get('parties') or []
    t = ' '.join(x for x in (kind, f"بتاريخ {date}" if date else '') if x)
    if parties:
        t += f" — {'، '.join(parties[:2])}"
    return t or d.get('type') or d.get('doc_type') or 'مستند لم يتضح نوعه من محتواه'


def docs_split(data, base=None):
    """(متوفرة، ناقصة) بحسب المحتوى المقروء: المتوفر = حُوّل وله نص markdown فعلي؛ الناقص = فشل/بلا نص/ينتظر."""
    have, miss = [], []
    index = data.get('doc_index') or []
    for i, (p, d) in enumerate(case_documents.all_docs(data)):
        st = (d.get('convert') or {}).get('state')
        row = {'title': content_title(d, index),
               'no': d.get('no'), 'submitter': p.get('submitter', ''), 'pid': p['id'],
               'why': (d.get('convert') or {}).get('message') or ''}
        if st == 'done' and d.get('file') and not d.get('needs_type') and _md_has_text(base, d.get('md')):
            have.append(row)
        else:
            row['why'] = row['why'] or ('يحتاج تحديد النوع' if d.get('needs_type') else
                                        'لم يُقرأ له نص' if st == 'done' else 'لم يُحوَّل بعد')
            miss.append(row)
    return have, miss


def tag_colors(submitter, index=0):
    """عنبري للمدعية، تيل للمدعى عليه، وغيرهما من لوحة الحوافظ."""
    s = submitter or ''
    if any(w in s for w in ('عليه', 'عليها', 'عليهم')):
        return TEAL
    if any(w in s for w in ('المدعي', 'مدعي', 'المدعية')):
        return AMBER_TAG
    return portfolio_colors(s, index)


# ---------- قطع الشكل ----------

def _lbl(text, size=13, color=rc.INK, bold=False, wrap=True):
    l = QLabel(isolate_tokens(text))
    l.setWordWrap(wrap)
    l.setAlignment(th.ARIGHT | Qt.AlignmentFlag.AlignVCenter)
    l.setStyleSheet(f"font-family:{F}; font-size:{size}px; color:{color}; font-weight:{700 if bold else 400};"
                    "border:none; background:transparent;")
    return l


def _tag(text, colors):
    bg, fg = colors
    l = _lbl(text, 11, fg, True, wrap=False)
    l.setStyleSheet(l.styleSheet() + f"background:{bg}; border-radius:8px; padding:2px 10px;")
    l.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return l


def _btn(text, primary=False):
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        qss = (f"QPushButton{{background:{NAVY}; color:white; border:none; border-radius:8px; padding:9px 22px;"
               f"font-family:{F}; font-size:13px; font-weight:600;}} QPushButton:hover{{background:{SLATE};}}"
               "QPushButton:disabled{background:#9aa4ae;}")
    else:
        qss = (f"QPushButton{{background:{th.BTN2_BG}; color:{NAVY}; border:1px solid {th.BTN2_BORDER}; border-radius:8px;"
               f"padding:8px 18px; font-family:{F}; font-size:13px; font-weight:600;}}"
               f"QPushButton:hover{{background:{th.BTN2_HOVER}; border-color:{NAVY};}}"
               "QPushButton:disabled{background:#F1F3F5; color:#8B97A3; border-color:#C5CED6;}")
    b.setStyleSheet(qss)
    return b


EDIT_QSS = (f"QPlainTextEdit{{background:{rc.SURFACE}; border:1px solid #e1e6eb; border-radius:8px; padding:10px;"
            f"font-family:{F}; font-size:14px; color:{rc.INK};}} QPlainTextEdit:focus{{border-color:{SLATE};}}")
# كل QComboBox في الصفحة: نمط صريح للقائمة المنبثقة (QAbstractItemView) — بدونه تتسرّب «background:transparent» من الصفحة
# فتظهر القائمة شاشة سوداء فارغة (نمط _site_box نفسه)
COMBO_QSS = ("QComboBox{background:white; color:#0f1c2c; border:1px solid #cbd5e1; border-radius:8px; padding:5px 10px;}"
             "QComboBox QAbstractItemView{background:white; color:#0f1c2c; selection-background-color:#e8f3fb;"
             "selection-color:#0f1c2c; border:1px solid #cbd5e1;}")

STEP_RING = {   # (تعبئة، إطار، رمز، لون الاسم) — يُستعمل لشارة حالة البطاقة
    rlm.ST_DONE: (SLATE, SLATE, '✓', NAVY),
    rlm.ST_CURRENT: ('white', NAVY, '', NAVY),
    rlm.ST_INPUT: (rc.AMBER_SOFT, rc.AMBER, '!', rc.AMBER),
    rlm.ST_FAILED: (rc.ERROR_SOFT, rc.ERROR, '×', rc.ERROR),
    rlm.ST_IDLE: (rc.CONTAINER, rc.IDLE, '', rc.GRAY_TEXT),
}

# ---- شكل الصفحة (رأس أبيض بخطوط شعرية فوق أرضية رمادية فاتحة، 2026-10-21) ----
PAGE_BG = '#f3f6f9'
HAIR = '#e3e8ef'
MUTED = '#64748b'
INK2 = '#334155'
BRAND = '#1f6fae'                   # مربع الشعار
BRAND_INK = '#1565a8'               # رقم القضية
AMBER_FILL, AMBER_HALO, AMBER_LINE = '#f59e0b', '#fde7b0', '#f4c46a'
# مظهر نقطة المسار: (تعبئة، إطار، أيقونة، هالة الخطوة المفتوحة، لون الاسم)
STEP_LOOK = {
    rlm.ST_DONE: (NAVY, NAVY, 'check', '#cbd5e1', INK2),
    rlm.ST_CURRENT: ('white', NAVY, None, '#c9d6e6', NAVY),
    rlm.ST_INPUT: (AMBER_FILL, AMBER_FILL, 'alert', AMBER_HALO, '#b45309'),
    rlm.ST_FAILED: ('#dc2626', '#dc2626', 'close', '#fecaca', '#b42318'),
    rlm.ST_IDLE: ('white', '#cbd5e1', None, '#e2e8f0', '#475569'),
}
STEP_PILL = {rlm.ST_INPUT: ('#fffbeb', AMBER_LINE), rlm.ST_FAILED: ('#fef2f2', '#fca5a5')}
ALERT_TAG = ''                     # أُزيل وسم «يتطلب مراجعة مدقق الخبراء» (2026-10-22)
DOCS_MIN_H = 430                 # أقل ارتفاع للوحة المستندات: أقل منه تتراكب منطقة الإفلات، فتتمرّر الصفحة بدلاً


def _hair():
    """خط شعري أفقي بين أشرطة الرأس."""
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{HAIR}; border:none;")
    return f


def _icon_lbl(kind, color, size, box, bg='transparent', radius=None):
    """أيقونة مرسومة داخل مربع/دائرة ملوّنة (بلا رموز يونيكود: تظهر مربعات على بعض الأجهزة)."""
    import qt_icons
    l = QLabel()
    l.setFixedSize(box, box)
    l.setAlignment(Qt.AlignmentFlag.AlignCenter)
    l.setPixmap(qt_icons.pixmap(kind, color, size))
    l.setStyleSheet(f"background:{bg}; border:none; border-radius:{box // 2 if radius is None else radius}px;")
    return l


def alert_view(level, text):
    """(العنوان، النص، الوسم) لتنبيه محرّك/مبالغ: «d5: قُرئت … بمحرك OCR خارجي: …» ← «تنبيه OCR خارجي (d5):»."""
    ref, body = '', text
    m = re.match(r'^([^:\s]{1,40}):\s+(.*)$', text, re.S)
    if m and not m.group(1).startswith('قُرئت'):
        ref, body = m.group(1), m.group(2)
    eng = re.search(r'بمحرك\s+(.+?):', body)
    head = 'تنبيه' + (f' {eng.group(1)}' if eng else '') + (f' ({ref})' if ref else '') + ':'
    if eng:
        body = body.replace(eng.group(0), eng.group(0)[:-1] + '؛', 1)
    return head, body.strip(), ALERT_TAG if level == 'red' else ''


def case_parties(data):
    """(مدّعون، مدّعى عليهم، طرف غير محدد): النظام ← المحفوظ في case_db ← الحضور المستخرج من المحاضر.
    (كان الرأس يقرأ ما جلبه النظام فقط، فيظهر المدعى عليه «—» لقضايا لم يُعِد النظام أسماء خصومها.)"""
    data = data or {}
    case = data.get('case') or {}
    pl, df, other = rlm.resolve_parties(case, rlm._saved_parties(data.get('caso_no') or case.get('caso_no') or ''))
    if not df:
        att = ((data.get('procedures') or {}).get('attendance') or {}).get('result') or []
        df = [' '.join(str(r['name']).split()) for r in att if r.get('name') and r.get('role') != 'plaintiff']
        if not pl:
            pl = [' '.join(str(r['name']).split()) for r in att if r.get('name') and r.get('role') == 'plaintiff']
        if df:
            other = ''
    return pl, df, other


def parties_html(data):
    """شريط القضية: رقم القضية | المدعي | المدعى عليه (تسميات خافتة وأسماء عريضة)."""
    pl, df, other = case_parties(data)
    lab = f"<span style='color:{MUTED}; font-size:11px'>%s</span>&nbsp;"
    name = f"<span style='color:{NAVY}; font-size:13px; font-weight:700'>%s</span>"
    sep = f"&nbsp;&nbsp;&nbsp;<span style='color:#cbd5e1'>|</span>&nbsp;&nbsp;&nbsp;"
    no = (data or {}).get('caso_no') or ''
    out = (lab % "رقم القضية:" + f"<span style='color:{BRAND_INK}; font-size:13px; font-weight:700'>{th.ltr(no)}</span>"
           if no else '')
    if pl or df:
        parts = [lab % "المدعي:" + name % ('، '.join(pl) or '—'), lab % "المدعى عليه:" + name % ('، '.join(df) or '—')]
    elif other:
        parts = [lab % "الأطراف:" + name % other]
    else:
        parts = []
    return sep.join(([out] if out else []) + parts)


class _Connector(QWidget):
    """خط نحيف بين خطوتين يُرسم مباشرة بلا خلفية (QWidget العادي يأخذ لون خلفية GLOBAL_QSS فيظهر مستطيلاً رمادياً)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setMinimumWidth(8)
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setPen(QPen(QColor('#d5dde6'), 2))
        y = self.height() // 2
        p.drawLine(2, y, max(2, self.width() - 2), y)
        p.end()


class StepperWidget(QWidget):
    """المسار الأفقي: سبع خطوات بأرقام، الضغط يفتح الخطوة. يوفّر set_data/set_actions_enabled
    ليحلّ محل CaseTrackWidget داخل منطق CaseTrackDialog."""
    action = pyqtSignal(str, str)
    selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._items, self._open = {}, None
        for i, (key, _n) in enumerate(rlm.DISPLAY_STEPS):
            if i:
                lay.addWidget(_Connector(self), 1, Qt.AlignmentFlag.AlignTop)
            btn = QPushButton()
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFlat(True)
            btn.clicked.connect(lambda _=False, k=key: self.selected.emit(k))
            col = QVBoxLayout(btn)
            col.setContentsMargins(4, 0, 4, 2)
            col.setSpacing(4)
            dot = QLabel(str(i + 1))
            dot.setFixedSize(30, 30)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QLabel()
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name.setWordWrap(True)                 # نافذة ضيقة/تكبير 150%: الاسم سطران بدل القص
            col.addWidget(dot, 0, Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(name, 0, Qt.AlignmentFlag.AlignHCenter)
            btn.setMinimumSize(64, 54)
            btn.setMaximumWidth(170)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            btn.setStyleSheet("QPushButton{border:none; background:transparent; border-radius:10px;}"
                              "QPushButton:hover{background:#f1f5f9;}")
            lay.addWidget(btn)
            self._items[key] = (btn, dot, name, i + 1)
        self._steps = []

    def set_open(self, key):
        self._open = key
        self._paint()

    def set_data(self, data):
        self._steps = step_list(data)
        self._paint()

    def _paint(self):
        import qt_icons
        for key, name, st, msg in self._steps:
            btn, dot, lbl, n = self._items[key]
            fill, ring, icon, halo, fg = STEP_LOOK[st]
            is_open = key == self._open
            if icon:                                # أيقونة مرسومة بيضاء فوق التعبئة
                dot.setText('')
                dot.setPixmap(qt_icons.pixmap(icon, 'white', 13))
            else:
                dot.setText(str(n))                 # setText يمسح أي أيقونة سابقة
            # المفتوحة: هالة 4px حول الدائرة؛ غيرها: دائرة 34px بإطار 2px داخل المربع نفسه (لا يتحرك الخط)
            box = (f"margin:0px; border:3px solid {halo}; border-radius:15px;" if is_open
                   else f"margin:2px; border:2px solid {ring}; border-radius:13px;")
            dot.setStyleSheet(f"font-family:{F}; font-size:12px; font-weight:700; background:{fill};"
                              f"color:{NAVY if st == rlm.ST_CURRENT else '#64748b'}; {box}")
            lbl.setText(name)
            lbl.setWordWrap(not is_open)            # المفتوحة شارة بسطر واحد (لا تُقص داخل إطارها)
            pill_bg, pill_line = STEP_PILL.get(st, ('#eef2f7', '#cbd5e1'))
            lbl.setStyleSheet(f"font-family:{F}; font-size:11px; color:{fg}; font-weight:{700 if is_open else 500};"
                              + (f"background:{pill_bg}; border:1px solid {pill_line}; border-radius:5px; padding:0px 8px;"
                                 if is_open else "background:transparent; border:none; padding:1px 0px;"))
            lbl.setMinimumWidth(lbl.fontMetrics().horizontalAdvance(name) + 26 if is_open else 0)
            btn.setMinimumWidth(max(72, lbl.minimumWidth() + 12))
            btn.setToolTip(f"{name} — {rlm.ST_TEXT[st]}" + (f"\n{msg}" if msg else ''))

    def set_actions_enabled(self, on):
        pass                                # التنقل بين الخطوات متاح دائماً؛ الأزرار في البطاقة تُعطَّل


def subject_missing_text(data):
    """سطر «ناقص» للموضوع: ما لم يُتحقق منه، والمطالبة إن غابت (الغياب الاختياري لا يُعدّ نقصاً)."""
    m = data.get('subject_missing') or {}
    out = list(m.get('unverified') or [])
    out += [a for a in m.get('absent') or [] if a == 'المطالبة']
    if case_procedures.TODO in (data.get('subject') or ''):
        out.append(f"مواضع «{case_procedures.TODO}» في النص")
    return '، '.join(out)


def question_line(q):
    """سطر العرض النصي (للتوافق): النص + البند + الحالة."""
    tag = f"[البند {q['point_n']}] " if q.get('point_n') else ''
    done = f"  ✓ أُغلق: {q.get('closed_by') or ''}" if q.get('status') == 'closed' else ''
    return f"{tag}{q['text']}{done}"


class QuestionsDialog(QDialog):
    """«الأسئلة المهمة»: يولّدها الذكاء الاصطناعي من نقاط المأمورية وفحص الجاهزية، في جدولين: مهام الخبير وطلبات للخصوم
    (م، الموجَّه إليه، المطلوب، البند، الحالة) بنص يلتف داخل الخلية بلا قص ولا تمرير أفقي. الإضافة اليدوية تبقى.
    «طباعة» تطبع الجدولين نفسهما."""
    _generated = pyqtSignal(object)            # None أو Exception

    HEADERS = ("م", "الموجَّه إليه", "المطلوب", "البند", "الحالة")

    def __init__(self, base, data, parent=None, ask=None, auto=True):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("الأسئلة المهمة")
        self.setMinimumSize(720, 520)
        self.base, self.data, self._ask = base, data, ask
        self.setStyleSheet(f"QDialog{{background:white;}} * {{font-family:{F};}}")
        lay = QVBoxLayout(self)
        lay.addWidget(_lbl("الأسئلة المهمة لهذه القضية", 15, NAVY, True))
        self.info = _lbl("", 11, rc.GRAY_TEXT)
        lay.addWidget(self.info)
        self.table_expert = self._make_table()
        self.table_party = self._make_table()
        lay.addWidget(_lbl("مهام الخبير", 13, NAVY, True))
        lay.addWidget(self.table_expert, 1)
        self.empty_expert = _lbl("", 12, rc.GRAY_TEXT)
        lay.addWidget(self.empty_expert)
        lay.addWidget(_lbl("طلبات للخصوم", 13, NAVY, True))
        lay.addWidget(self.table_party, 1)
        self.empty_party = _lbl("", 12, rc.GRAY_TEXT)
        lay.addWidget(self.empty_party)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("إضافة يدوية: اكتب المطلوب ثم «إضافة»")
        self.edit.returnPressed.connect(self._add)
        self.kind_box = QComboBox()
        self.kind_box.setStyleSheet(COMBO_QSS)
        self.kind_box.addItem("طلب لخصم", 'party')
        self.kind_box.addItem("مهمة للخبير", 'expert')
        add = _btn("إضافة", True)
        add.clicked.connect(self._add)
        self.gen_btn = _btn("توليد بالذكاء")
        self.gen_btn.clicked.connect(self.generate)
        self.gen_btn.setEnabled(ask is not None)
        printb = _btn("طباعة")
        printb.clicked.connect(self._print)
        close = _btn("إغلاق")
        close.clicked.connect(self.accept)
        row.addWidget(self.edit, 1)
        for w in (self.kind_box, add, self.gen_btn, printb, close):
            row.addWidget(w)
        lay.addLayout(row)
        self._generated.connect(self._on_generated)
        self.refresh()
        if auto and ask is not None and not any(q.get('ai') for q in case_readiness.normalize_questions(data)) \
                and (data.get('mission') or {}).get('points'):
            QTimer.singleShot(0, self.generate)

    def _make_table(self):
        t = QTableWidget(0, len(self.HEADERS))
        t.setHorizontalHeaderLabels(self.HEADERS)
        t.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        t.setWordWrap(True)
        t.setTextElideMode(Qt.TextElideMode.ElideNone)
        t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.verticalHeader().setVisible(False)
        h = t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)       # «المطلوب» يأخذ الباقي ويلتف
        for col, w in ((0, 36), (1, 110), (3, 56), (4, 80)):
            t.setColumnWidth(col, w)
        t.setStyleSheet("QTableWidget{border:1px solid #e1e6eb; border-radius:8px; font-size:13px;}"
                        "QHeaderView::section{background:#EAF1F6; color:#0F2747; border:none; padding:6px; font-weight:700;}")
        return t

    def _fill(self, table, rows, empty_label, empty_text):
        table.setRowCount(len(rows))
        for i, q in enumerate(rows):
            cells = (str(i + 1), q.get('to') or '—', q['text'], str(q.get('point_n') or '—'),
                     'مغلق ✓' if q.get('status') == 'closed' else 'مفتوح')
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(th.ARIGHT | Qt.AlignmentFlag.AlignVCenter)
                if q.get('status') == 'closed':
                    item.setForeground(QColor(rc.GRAY_TEXT))
                table.setItem(i, c, item)
        table.resizeRowsToContents()
        empty_label.setText("" if rows else empty_text)
        table.setVisible(bool(rows))

    def refresh(self):
        import case_questions
        experts, parties = case_questions.split(self.data)
        self._fill(self.table_expert, experts, self.empty_expert,
                   "لا مهام للخبير بعد — اضغط «توليد بالذكاء» أو أضف مهمة يدوياً.")
        self._fill(self.table_party, parties, self.empty_party,
                   "لا طلبات للخصوم بعد — اضغط «توليد بالذكاء» أو أضف طلباً يدوياً.")
        wb = (self.data.get('written_by') or {}).get('questions')
        self.info.setText(("كُتب بواسطة: " + wb['provider'] + (f" / {wb['model'].split(' (احتياطي')[0]}" if wb.get('model') else '')) if wb
                          else "تُولَّد من نقاط المأمورية في حكم الإحالة ثم ما ينقص بحسب فحص الجاهزية.")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        for t in (self.table_expert, self.table_party):
            t.resizeRowsToContents()

    # ---- التوليد في خيط خلفي ----
    def generate(self):
        if self._ask is None or getattr(self, '_gen_running', False):
            return
        import case_questions
        self._gen_running = True
        self.gen_btn.setEnabled(False)
        self.info.setText("⏳ يولّد الذكاء الاصطناعي الأسئلة…")

        def work():
            try:
                case_questions.generate(self.base, self.data, self._ask)
                self._generated.emit(None)
            except Exception as e:
                self._generated.emit(e)
        threading.Thread(target=work, daemon=True).start()

    def _on_generated(self, err):
        self._gen_running = False
        self.gen_btn.setEnabled(self._ask is not None)
        self.refresh()
        if err is not None:
            self.info.setText(f"تعذّر التوليد: {err}")

    def _add(self):
        q = self.edit.text().strip()
        if not q:
            return
        qs = case_readiness.normalize_questions(self.data)
        kind = self.kind_box.currentData()
        rec = {'id': f'm{len(qs) + 1}', 'text': q, 'status': 'open', 'auto': False, 'kind': kind,
               'to': 'الخبير' if kind == 'expert' else ''}
        qs.append(rec)
        case_workspace.write_case_json(self.base, self.data)
        self.edit.clear()
        self.refresh()

    def _print(self):
        from PyQt6.QtGui import QTextDocument
        from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
        doc = QTextDocument()
        doc.setHtml(case_readiness.questions_html(self.data))
        printer = QPrinter()
        if QPrintDialog(printer, self).exec() == QDialog.DialogCode.Accepted:
            doc.print(printer)


class CasePageDialog(CaseTrackDialog):
    """صفحة القضية. يعيد استخدام كل _do_* و_run_bg و_do_report و_review من CaseTrackDialog."""

    def __init__(self, base, data, parent=None, cookies=None, ask=None, fetch=None):
        QDialog.__init__(self, parent)
        rc.load_plex()
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"القضية {data['caso_no']}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint     # تكبير النافذة لملء الشاشة
                            | Qt.WindowType.WindowMinimizeButtonHint)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(f"QDialog{{background:{PAGE_BG};}}")
        self._fit_to_screen(parent)
        self.base, self.data = base, data
        self.cookies, self._ask, self._fetch = cookies, ask, fetch
        self._busy, self._stop, self._after = False, False, None
        self._open, self._dirty, self._loading, self._last_pick = None, False, False, None
        self._busy_text, self._notice, self._rewriting = '', None, None
        self._proc_auto_done, self._proc_picked = False, False
        self.editor = self.picker = None
        self._done.connect(self._on_done)
        self._queue_claim_summary()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # ---- الرأس الأبيض المضغوط: شريط القضية (الرقم | المدعي | المدعى عليه) ثم المسار ----
        chrome = QFrame()
        chrome.setObjectName('chrome')
        chrome.setStyleSheet(f"QFrame#chrome{{background:white; border:none; border-bottom:1px solid {HAIR};}}")
        cl = QVBoxLayout(chrome)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.add_docs_btn = None
        self.title = None
        self.parties = _lbl(parties_html(data), 13, NAVY)
        self.parties.setTextFormat(Qt.TextFormat.RichText)
        self.parties.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.parties.setContentsMargins(20, 7, 20, 7)
        cl.addWidget(self.parties)
        cl.addWidget(_hair())
        self.track = StepperWidget(self)
        self.track.selected.connect(self.open_step)
        tw = QVBoxLayout()
        tw.setContentsMargins(32, 8, 32, 6)
        tw.addWidget(self.track)
        cl.addLayout(tw)
        outer.addWidget(chrome)
        # ---- منطقة العمل (أرضية رمادية فاتحة) ----
        root = QVBoxLayout()
        root.setContentsMargins(20, 12, 20, 10)
        root.setSpacing(10)
        outer.addLayout(root, 1)
        self.pick_line = _lbl("", 12, rc.ERROR, True)          # «حُدِّد تلقائياً، تأكد منه» لحكم الإحالة
        self.pick_line.setVisible(False)
        root.addWidget(self.pick_line)
        # ---- البطاقة ----
        self.card = QFrame()
        self.card.setObjectName('stepcard')
        self.card.setStyleSheet(rc.card_frame_qss('stepcard', border='#e3e8ed'))
        self.card_lay = QVBoxLayout(self.card)
        self.card_lay.setContentsMargins(26, 22, 26, 22)
        self.card_lay.setSpacing(12)
        scroll = QScrollArea()
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        from qt_documents_panel import SCROLL_QSS
        scroll.setStyleSheet(SCROLL_QSS)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.card)
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background:transparent;")
        root.addWidget(scroll, 1)
        self.status = _lbl("", 12, rc.GRAY_TEXT)
        root.addWidget(self.status)
        self.folder_line = _lbl("", 11, rc.GRAY_TEXT)        # مزامنة مجلد القضية + فحص العدد (أحمر عند الاختلاف)
        root.addLayout(self._make_folder_row(self.folder_line))
        # ---- الشريط السفلي (RTL: «السابق» أول عنصر = أقصى اليمين، والاعتماد أقصى اليسار) ----
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.prev_btn = _btn("السابق")
        self.prev_btn.clicked.connect(lambda: self._go(-1))
        self.q_btn = _btn("الأسئلة المهمة")
        self.q_btn.clicked.connect(lambda: QuestionsDialog(self.base, self.data, self, ask=self._ask_for('الأسئلة المهمة'),
                                                           auto=False).exec())     # التوليد بالذكاء بزره فقط
        self.report_btn = _btn("إصدار التقرير بصيغة وورد")
        self.report_btn.clicked.connect(self._do_report)
        self.ai_log_btn = _btn("سجل الذكاء الاصطناعي")
        self.ai_log_btn.clicked.connect(self.show_ai_log)
        self.ai_log_btn.setStyleSheet(self.ai_log_btn.styleSheet().replace('padding:8px 18px', 'padding:5px 12px')
                                      .replace('font-size:13px', 'font-size:11px'))
        self.stop_btn = _btn("إيقاف")
        self.stop_btn.clicked.connect(self._request_stop)
        self.stop_btn.setVisible(False)
        self.saved = _lbl("تم الحفظ تلقائياً", 11, rc.GRAY_TEXT, wrap=False)
        self.next_btn = _btn("التالي", True)
        self.next_btn.clicked.connect(self.go_next)
        for b in (self.prev_btn, self.q_btn, self.report_btn, self.ai_log_btn, self.stop_btn, self.next_btn):
            b.setMinimumWidth(b.sizeHint().width())          # لا يُضغط زر حتى يُقص نصه
            bar.addWidget(b)
            if b is self.stop_btn:
                bar.addStretch(1)
                bar.addWidget(self.saved)
        root.addLayout(bar)

        self._timer = QTimer(self)
        self._timer.setInterval(600)
        self._timer.timeout.connect(lambda: self.track.set_data(self.data))
        self._bg_timer = QTimer(self)
        self._bg_timer.setInterval(1000)
        self._bg_timer.timeout.connect(self._poll_bg)
        self._bg_timer.start()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(AUTOSAVE_MS)
        self._save_timer.timeout.connect(self.autosave)
        self._rp_timer = QTimer(self)                 # شريط تقدم كل محور/عقد أثناء كتابة البحث
        self._rp_timer.setInterval(1000)
        self._rp_timer.timeout.connect(self._rp_tick)
        self._rp_timer.start()
        self.reload(data)
        # أول ما يراه الخبير: قائمة المستندات ولوحة خط البداية الحيّة (case_startup) — ثم الخطوة الحالية بالمسار
        self.open_step('documents' if self.STARTUP_VIEW else current_step(self.data))
        if self.AUTO_RESUME:
            QTimer.singleShot(0, self.auto_resume_documents)
        if self.AUTO_SYNC:                    # التحميل تلقائي عند فتح القضية (لا زر «تحديث من النظام»)
            QTimer.singleShot(0, lambda: self.sync_folder(fetch=True))

    AUTO_PROCEDURES = True          # تُطفأ في بعض الاختبارات
    STARTUP_VIEW = True             # الفتح على قائمة المستندات + لوحة الخطوات (تُطفأ في اختبارات الخطوات القديمة)

    def _queue_claim_summary(self):
        """فتح صفحة القضية: ملخص الصحيفة بالطابور الخلفي (summary_queue) إن لم يُحفظ بعد — لا يجمّد الواجهة ولا يكرَّر."""
        try:
            import summary_queue
            from referred_cases import claim_summary_initial
            case = {'caso_no': self.data.get('caso_no', ''), 'autocase_no': self.data.get('autocase_no', '')}
            if self.cookies and case['autocase_no'] and claim_summary_initial(case)[0] == 'load':
                summary_queue.enqueue(case, self.cookies)
        except Exception:
            pass

    def _fit_to_screen(self, parent):
        """حجم يناسب الشاشة الفعلية (1366×768 بتكبير 150% = 910×512 منطقياً): نافذة أكبر من الشاشة كانت تُقص من اليمين."""
        scr = (parent.screen() if parent is not None else None) or QGuiApplication.primaryScreen()
        av = scr.availableGeometry() if scr is not None else None
        aw, ah = (av.width(), av.height()) if av is not None else (1280, 800)
        self.setMinimumSize(min(720, max(480, aw - 20)), min(460, max(360, ah - 20)))
        self.resize(max(self.minimumWidth(), min(1180, aw - 40)), max(self.minimumHeight(), min(800, ah - 60)))
        if av is not None:
            self.move(av.x() + (aw - self.width()) // 2, av.y() + max(0, (ah - self.height()) // 2))

    # ---------- العرض ----------
    def reload(self, data=None):
        super().reload(data)
        if hasattr(self, 'pick_line'):
            import referral_pick
            txt, red = referral_pick.line(self.data)
            self.pick_line.setText(txt if red else '')
            self.pick_line.setVisible(bool(red and txt))
        if self._open and not self._dirty and not self._busy:
            self._render_card()
        if getattr(self, '_open', None) and not self._busy:     # مستند جديد ← إعادة الفحص تلقائياً
            QTimer.singleShot(0, self._auto_readiness)
            QTimer.singleShot(0, self._auto_conclusion)

    def _sync_report_btn(self):
        self.report_btn.setEnabled(not self._busy)       # دائماً فعّال إلا أثناء عمل جارٍ
        self.report_btn.setToolTip('يُصدر ما اكتمل، والناقص «[يُكتب]» لتكمله في وورد')

    def _on_done(self, err):
        self._busy_text = ''
        if self._rewriting:
            self._notice = self._rewrite_notice(err)
            self._rewriting = None
        super()._on_done(err)                                 # reload() يعيد رسم البطاقة بالنتيجة
        for b in self.card.findChildren(QPushButton):
            b.setEnabled(True)
        self.next_btn.setEnabled(True)

    def _run_bg(self, fn, text):
        if self._dirty:
            self.autosave()
        super()._run_bg(fn, text)
        self._busy_text = text
        if self._open:
            self._render_card()                               # «جارٍ…» داخل البطاقة نفسها
        for b in self.card.findChildren(QPushButton):
            b.setEnabled(False)
        if self.editor is not None:
            self.editor.setReadOnly(True)
        self.next_btn.setEnabled(False)

    def _rewrite_notice(self, err):
        """(نص، خطأ؟) بعد إعادة الكتابة: الخطأ بنص واضح، أو النجاح، مع سطر آخر استدعاء للمزوّد."""
        key, since, pid = self._rewriting
        log = ai_call_log.describe(ai_call_log.last(since=since))
        if err is not None:
            return (f"تعذّرت إعادة الكتابة: {err}" + (f"\n{log}" if log else ''), True)
        rec = (self.data.get('steps') or {}).get(key) or {}
        bad, why = rec.get('state') == 'failed', rec.get('message') or ''
        if key == 'research' and pid:
            it = next((i for i in self.data.get('research') or [] if i['id'] == pid), {})
            bad, why = it.get('state') == 'failed', it.get('message') or ''
        if bad:
            return (f"تعذّرت إعادة الكتابة: {why or 'سبب غير معروف'}" + (f"\n{log}" if log else ''), True)
        done = 'تمت إعادة الكتابة.' + (f' {why}' if why and key == 'subject' else '')
        return (done + (f"\n{log}" if log else ''), False)

    def open_step(self, key):
        if self._dirty:
            self.autosave()
        if key != self._open:
            self._notice = None
        self._open = key
        self.track.set_open(key)
        self.prev_btn.setEnabled(neighbour(key, -1) is not None)
        last = neighbour(key, +1) is None                 # آخر خطوة: «التالي» يصير «إصدار التقرير»
        self.next_btn.setText("إصدار التقرير" if last else "التالي")
        self.next_btn.setMinimumWidth(self.next_btn.sizeHint().width())
        self._render_card()
        if key == 'procedures':
            self._auto_procedures()
        if key == 'research':
            self._auto_readiness()

    def _auto_procedures(self):
        """أول فتح للخطوة: يأخذ المحاضر ويجلب الجلسات ويستخرج الحضور ويعتمد وحده (مرة لكل فتح للصفحة)."""
        if self._proc_auto_done or self._busy or not self.AUTO_PROCEDURES:
            return
        self._proc_auto_done = True
        self._after = self._after_procedures
        self.do('procedures', 'run')

    def _after_procedures(self):
        """لا نافذة اختيار ملف إلا إن لم يُعثر على أي محضر."""
        if not (self.data.get('sessions') or {}).get('minutes') and not self._proc_picked:
            self._proc_picked = True
            QTimer.singleShot(0, lambda: self.do('procedures', 'add'))

    def _go(self, delta):
        k = neighbour(self._open, delta)
        if k:
            self.open_step(k)

    def _clear_card(self):
        while self.card_lay.count():
            it = self.card_lay.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.deleteLater()
            elif it.layout():
                self._clear_layout(it.layout())

    def _clear_layout(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
            elif it.layout():
                self._clear_layout(it.layout())

    def _render_card(self):
        self._loading = True
        self._clear_card()
        key = self._open
        st = dict((k, (n, s, m)) for k, n, s, m in step_list(self.data))
        name, disp, msg = st[key]
        fill, ring, _g, fg = STEP_RING[disp]
        bare = key == 'documents'                       # المستندات: أقسامها وبطاقاتها على الأرضية مباشرة (بلا بطاقة حاوية)
        self.card.setStyleSheet("QFrame#stepcard{background:transparent; border:none;}" if bare
                                else rc.card_frame_qss('stepcard', border='#e3e8ed'))
        self.card_lay.setContentsMargins(*((0, 0, 0, 0) if bare else (26, 22, 26, 22)))
        self.card_lay.setSpacing(10 if bare else 12)
        if key != 'documents':                          # المستندات تأخذ الصفحة كلها؛ اسمها ظاهر في المسار أعلاه
            head = QHBoxLayout()
            head.addWidget(_lbl(name, 18, NAVY, True, wrap=False))
            head.addWidget(_tag(rlm.ST_TEXT[disp], (fill if disp != rlm.ST_CURRENT else rc.SECONDARY_SOFT, fg)))
            head.addStretch()
            self.card_lay.addLayout(head)
        if msg and key not in ('procedures', 'documents'):     # المستندات تعرض حالتها داخل اللوحة                 # الإجراءات تعرض قائمتها المفصّلة بدل الرسالة
            self.card_lay.addWidget(_lbl(msg, 12, fg if disp in (rlm.ST_INPUT, rlm.ST_FAILED) else rc.GRAY_TEXT))
        if self._busy and self._busy_text:
            b = _lbl(f"⏳ {self._busy_text}", 13, NAVY, True)
            b.setStyleSheet(b.styleSheet() + f"background:{rc.SECONDARY_SOFT}; border-radius:8px; padding:8px 12px;")
            self.card_lay.addWidget(b)
            self._busy_lbl = b
        elif self._notice:
            text, bad = self._notice
            n = _lbl(text.replace('\n', '<br>'), 12, rc.ERROR if bad else NAVY)
            n.setStyleSheet(n.styleSheet() + f"background:{rc.ERROR_SOFT if bad else rc.SECONDARY_SOFT};"
                                              "border-radius:8px; padding:8px 12px;")
            self.card_lay.addWidget(n)
        wb = (self.data.get('written_by') or {}).get(key)
        if wb:                                           # أي مزوّد/نموذج كتب نص هذه الخطوة
            self.card_lay.addWidget(_lbl("كُتب بواسطة: " + wb['provider'] + (f" / {wb['model'].split(' (احتياطي')[0]}" if wb.get('model') else ''),
                                         11, rc.GRAY_TEXT))
        self.editor = None
        self.picker = None
        getattr(self, f'_card_{key}')()
        self.card_lay.addStretch()
        self._loading = False
        if self.editor is not None:
            self.editor.setFixedHeight(160)
            QTimer.singleShot(0, self._fit_docs_tabs)

    def _actions_row(self, items):
        row = QHBoxLayout()
        row.addStretch()
        for text, fn, primary in items:
            b = _btn(text, primary)
            b.clicked.connect(fn)
            b.setEnabled(not self._busy)
            row.addWidget(b)
        self.card_lay.addLayout(row)

    def _add_editor(self, text, min_h=260):
        self.editor = BidiPlainTextEdit(text)
        self.editor.setStyleSheet(EDIT_QSS)
        self.editor.setMinimumHeight(min_h)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor.textChanged.connect(self._on_edit)
        self.card_lay.addWidget(self.editor)

    def _sources_line(self, kind):
        """سطر «المحفوظ محلياً»: تاريخ الجلب والمحرك، أو أنه لم يُحفظ بعد."""
        import case_sources
        rec = case_sources.record(self.data, kind)
        label = case_sources.LABELS[kind]
        if not rec.get('file'):
            self.card_lay.addWidget(_lbl(f"{label}: غير محفوظة محلياً بعد — تُجلب من النظام تلقائياً عند فتح القضية.", 11, rc.GRAY_TEXT))
            return
        eng = rec.get('label') or rec.get('engine') or 'غير مسجَّل'
        self.card_lay.addWidget(_lbl(f"{label}: محفوظة محلياً ({rec.get('fetched_at', '')}) — المحرك: {eng}. "
                                     "تُستعمل من مجلد القضية، والأحدث يُجلب تلقائياً عند فتح القضية.", 11, rc.GRAY_TEXT))

    def _std_actions(self, rewrite=None, approve=False, extra=()):
        """approve=True فقط لخطوتي البحث والنتيجة («اعتماد رأيي»)؛ الباقي يعتمد نفسه متى اكتمل."""
        items = []
        if rewrite:
            items.append(("إعادة الكتابة", rewrite, False))
        items.extend(extra)
        if approve:
            items.append(("اعتماد رأيي", self.approve_current, False))
        self._actions_row(items)

    # ---------- محررات الخطوات ----------
    def _alerts_block(self, step):
        """تنبيهات المحرّك والمبالغ بالأحمر/العنبري أعلى بطاقة الخطوة (لا تُكتب في التقرير)."""
        import doc_router
        if step == 'documents':
            self._read_alerts()
            return
        for level, text in doc_router.step_alerts(self.data, step):
            self.card_lay.addWidget(self._alert_banner(level, text))

    def _read_alerts(self):
        """مستند قُرئ بمحرّك OCR قد يخطئ في الأرقام: اسمه الحقيقي وما على الخبير فعله، وزرّان فقط."""
        import case_folder
        try:
            rows = [r for r in case_folder.doc_rows(self.base, self.data) if r.get('alert')]
        except Exception:
            rows = []
        for r in rows:
            box = QFrame()
            box.setObjectName('alert')
            box.setStyleSheet("QFrame#alert{background:#fffbeb; border:1px solid #f8d78b; border-radius:8px;}")
            h = QHBoxLayout(box)
            h.setContentsMargins(10, 6, 10, 6)
            h.setSpacing(8)
            h.addWidget(_icon_lbl('alert', '#b45309', 14, 20), 0, Qt.AlignmentFlag.AlignTop)
            h.addWidget(_lbl(r['alert'], 12, '#92400e'), 1)
            again = _btn("أعد القراءة بجيميناي")
            again.clicked.connect(lambda _=False, rel=r['rel']: self._reread_doc(rel, 'gemini'))
            ok = _btn("راجعته")
            ok.clicked.connect(lambda _=False, rel=r['rel']: self._ocr_reviewed(rel))
            for b in (again, ok):
                b.setEnabled(not self._busy)
                h.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            self.card_lay.addWidget(box)

    def _alert_banner(self, level, text):
        """سطر تنبيه عنبري مضغوط: أيقونة صغيرة، العنوان العريض والنص في سطر يلتف، والوسم يساراً (للأحمر)."""
        head, body, tag = alert_view(level, text)
        box = QFrame()
        box.setObjectName('alert')
        box.setStyleSheet("QFrame#alert{background:#fffbeb; border:1px solid #f8d78b; border-radius:8px;}")
        h = QHBoxLayout(box)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)
        h.addWidget(_icon_lbl('alert', '#b45309', 14, 20), 0, Qt.AlignmentFlag.AlignTop)
        msg = _lbl(f"<b style='color:#7a2e0e'>{head}</b>&nbsp; {body}", 12, '#92400e')
        msg.setTextFormat(Qt.TextFormat.RichText)
        h.addWidget(msg, 1)
        if tag:
            t = _lbl(tag, 10, '#78350f', True, wrap=False)
            t.setStyleSheet(t.styleSheet() + "background:#fcd88a; border-radius:5px; padding:1px 8px;")
            h.addWidget(t, 0, Qt.AlignmentFlag.AlignTop)
        return box


    def _card_subject(self):
        self._alerts_block('subject')
        self._autowrite_block('subject')
        if case_procedures.TODO in (self.data.get('subject') or ''):
            self.card_lay.addWidget(_lbl(f"في النص «{case_procedures.TODO}»: لم يرد في صحيفة الدعوى أو لم يُتحقق منه "
                                         "حرفياً — أكمله ثم اعتمد.", 12, rc.AMBER))
        self._sources_line('claim')
        self._stage2_status()
        self._add_editor(self.data.get('subject') or '')
        self._stage_actions('stage2', lambda: self._rewrite('subject'))
        if (self.AUTO_ASK_TYPE and self.data.get('subject_type_unclear') and not self.data.get('subject_type_asked')
                and not self._busy):                 # النوع يُحدَّد تلقائياً؛ وإن لم يتضح يُسأل الخبير مرة واحدة
            self.data['subject_type_asked'] = True
            case_workspace.write_case_json(self.base, self.data)
            QTimer.singleShot(0, self._choose_subject_type)

    AUTO_ASK_TYPE = True             # تُطفأ في الاختبارات

    # ---------- المرحلة الثانية والكتابة عبر المتصفح (2026-10-21) ----------
    def _stage2_status(self):
        """سبب الفشل/ما ينقص/أخطاء التحقق بالأحمر فوق الموضوع — لا تُترك الخانة فارغة بصمت."""
        import case_stage2
        text, red = case_stage2.status_line(self.base, self.data)
        if text:
            lbl = _lbl(text, 12, rc.ERROR if red else rc.GRAY_TEXT, red)
            if red:
                lbl.setStyleSheet(lbl.styleSheet() + f"background:{rc.ERROR_SOFT}; border-radius:8px; padding:6px 10px;")
            self.card_lay.addWidget(lbl)

    def _stage_actions(self, stage, rewrite):
        """«أعد الكتابة» + زر الطريقة («جيميناي (API)» / «عبر المتصفح») + الموقع و«اكتب عبر المتصفح» و«لصق الرد»."""
        import browser_write as bw
        mode = bw.mode(self.data, stage)
        row = QHBoxLayout()
        row.addStretch()
        if mode == 'browser':
            self._site_box = QComboBox()
            # نمط صريح للقائمة ونافذتها: بدونه تتسرّب «background:transparent» فتظهر القائمة فارغة ولا يُختار شيء
            self._site_box.setStyleSheet(COMBO_QSS)
            self._site_box.setMinimumWidth(190)
            cur = bw.chosen_site(self.data)
            for st in bw.sites():
                self._site_box.addItem(st['label'] + (' (لصق تلقائي)' if st['auto'] else ''), st['key'])
                if st['key'] == cur:
                    self._site_box.setCurrentIndex(self._site_box.count() - 1)
            self._site_box.currentIndexChanged.connect(
                lambda _i: bw.set_site(self.base, self.data, self._site_box.currentData()))
            row.addWidget(self._site_box)
            for text, fn in (("اكتب عبر المتصفح", lambda: self._browser_write(stage)),
                             ("لصق الرد", lambda: self._browser_paste(stage))):
                b = _btn(text)
                b.clicked.connect(fn)
                b.setEnabled(not self._busy)
                row.addWidget(b)
        if stage == 'stage3':                 # في البحث: الطريقة تُختار أعلاه، و«اكتب عبر المتصفح» هو الكتابة نفسها
            self.card_lay.addLayout(row)
            return
        b = _btn("أعد الكتابة")
        b.clicked.connect(rewrite)
        b.setEnabled(not self._busy)
        row.addWidget(b)
        m = _btn(isolate_tokens(dict(bw.MODES)[mode]))
        m.setToolTip("طريقة الكتابة: اضغط للتبديل بين جيميناي والمتصفح")
        m.clicked.connect(lambda: self._toggle_mode(stage))
        m.setEnabled(not self._busy)
        row.addWidget(m)
        self.card_lay.addLayout(row)

    def _toggle_mode(self, stage):
        import browser_write as bw
        bw.set_mode(self.base, self.data, stage, 'api' if bw.mode(self.data, stage) == 'browser' else 'browser')
        if stage == 'stage3':
            research_pipeline.state(self.data)['delivery'] = bw.mode(self.data, stage)
            case_workspace.write_case_json(self.base, self.data)
        self._render_card()

    def _browser_write(self, stage):
        """يجهّز الطلب نفسه ويفتح الموقع المختار: لصق تلقائي عبر browser-ai-bot إن أمكن، وإلا نسخ إلى الحافظة."""
        import browser_write as bw
        if self._busy:
            return
        site = bw.site(bw.chosen_site(self.data))
        out = {}

        def work():
            out['text'], out['path'] = bw.prepare(self.base, self.data, stage)
            if site.get('auto') and self.AUTO_BROWSER:
                try:
                    out['reply'] = bw.auto_send(site['key'], out['text'])
                except Exception as e:                       # تعذّر اللصق التلقائي ← الحافظة
                    out['auto_error'] = str(e) or e.__class__.__name__
            if out.get('reply'):
                out['res'] = bw.accept(self.base, self.data, stage, out['reply'], site['key'])

        def after():
            if out.get('res') is not None:
                self._notice = self._accept_notice(stage, out['res'], site['label'])
            else:
                try:
                    QGuiApplication.clipboard().setText(out.get('text') or '')
                except Exception:
                    pass
                if self.OPEN_EXTERNAL:
                    try:
                        bw.open_site(site['url'])         # المتصفح نفسه بحجم كامل (لا برنامج Copilot المثبَّت)
                    except Exception:
                        pass
                why = f" (تعذّر اللصق التلقائي: {out['auto_error']})" if out.get('auto_error') else ''
                self._notice = (f"نُسخ الطلب إلى الحافظة وفُتح {site['label']}{why} — الصقه هناك، ثم انسخ الرد كاملاً "
                                "واضغط «لصق الرد» (يمر على نفس التحقق).", False)
            self._render_card()
        self._after = after
        self._run_bg(work, f"جارٍ تجهيز الطلب ({bw.STAGE_LABELS[stage]}) للكتابة عبر {site['label']}…")

    def _browser_paste(self, stage, text=None):
        """«لصق الرد»: الرد يمر على نفس التحقق بالكود ويُذكر «عبر المتصفح» في «كُتب بواسطة»."""
        import browser_write as bw
        if self._busy:
            return
        if text is None:
            text, ok = QInputDialog.getMultiLineText(self, "لصق الرد", "الصق رد الموقع كاملاً (JSON):")
            if not ok:
                return
        site = bw.site(bw.chosen_site(self.data))
        try:
            res = bw.accept(self.base, self.data, stage, text, site['key'])
        except case_model.StepError as e:
            self._notice = (str(e), True)
            self._render_card()
            return
        self._notice = self._accept_notice(stage, res, site['label'])
        self.reload()

    @staticmethod
    def _accept_notice(stage, res, label):
        if stage == 'stage2':
            bad = res.get('rejected') or {}
            if not bad:
                return (f"قُبل رد {label}: الموضوع والإجراءات والمرفقات اجتازت التحقق بالكود.", False)
            import case_stage2
            return ("رُفض بالتحقق بالكود — " + '؛ '.join(f"{case_stage2.LABELS[k]}: {'، '.join(v[:2])}"
                                                     for k, v in bad.items()), True)
        a = res.get('audit') or {}
        msg = f"قُبل رد {label}: {len(res.get('accepted') or [])} خانة"
        if res.get('rejected'):
            msg += f"، ورُفضت {len(res['rejected'])} (كُتبت بجمل الكود)"
        if a and not a.get('ok', True):
            return (msg + ' — فشل التدقيق: ' + '؛ '.join((a.get('errors') or [])[:3]), True)
        return (msg + ' — اجتاز التدقيق.', bool(res.get('rejected')))

    AUTO_BROWSER = True             # اللصق التلقائي عبر browser-ai-bot (تُطفأ في الاختبارات)

    def _missing_line(self, text):
        """ما يحتاجه الخبير يظهر سطراً أحمر «ناقص: …» (لا زر اعتماد)."""
        if text:
            self.card_lay.addWidget(_lbl(f"ناقص: {text}", 12, rc.ERROR, True))

    def _choose_subject_type(self):
        """الخبير يحدّد نوع القضية (يسأل البرنامج حين لا يتضح من الصحيفة) ← يُعاد توليد الموضوع بنموذج ذلك النوع."""
        import case_subject_ai as sa
        from PyQt6.QtWidgets import QInputDialog
        labels = list(sa.CASE_TYPES.values())
        cur = sa.CASE_TYPES.get(self.data.get('subject_type'), labels[0])
        label, ok = QInputDialog.getItem(self, "نوع القضية", "اختر نوع القضية لصياغة الموضوع:", labels,
                                         labels.index(cur), False)
        if not ok:
            return
        self.data['subject_type'] = next(k for k, v in sa.CASE_TYPES.items() if v == label)
        self.data['subject_type_chosen'] = True
        self.data.pop('subject_type_unclear', None)
        self.autosave()
        self._rewrite('subject')

    def _save_subject_as_model(self):
        """يضيف نص الموضوع الحالي إلى «نماذج_صياغة_الموضوع.md» ليُستعمل أسلوبه في الكتابة القادمة."""
        import case_subject_ai as sa
        from PyQt6.QtWidgets import QInputDialog
        self.autosave()
        text = (self.data.get('subject') or '').strip()
        if not text:
            QMessageBox.warning(self, "لا نص", "لا يوجد نص موضوع لحفظه كنموذج.")
            return
        title, ok = QInputDialog.getText(self, "نموذج جديد", "عنوان النموذج:", text=f"نموذج من القضية {self.data['caso_no']}")
        if not ok:
            return
        tags, ok = QInputDialog.getText(self, "نموذج جديد", "كلمات مفتاحية للقضايا المشابهة (مفصولة بفاصلة):")
        if not ok:
            return
        path = sa.add_model(title, [t.strip() for t in tags.replace('،', ',').split(',') if t.strip()], text,
                            kind=self.data.get('subject_type') or '')
        self._notice = (f"أُضيف النموذج إلى: {path}", False)
        self._render_card()

    def _card_mission(self):
        self._alerts_block('mission')
        m = self.data.get('mission') or {}
        import referral_pick
        txt, red = referral_pick.line(self.data)
        if txt:
            self.card_lay.addWidget(_lbl(txt, 12, rc.ERROR if red else rc.GRAY_TEXT, red))
        if m.get('source_changed'):
            self._missing_line("تغيّر حكم الإحالة بعد تعديلك للمأمورية — «أعد القراءة من الحكم» إن لزم")
        head = QHBoxLayout()
        head.addWidget(_lbl("نقاط المأمورية (نقطة بكل سطر — عدّل مباشرة، الترقيم تلقائي):", 12, rc.GRAY_TEXT))
        head.addStretch()
        b = QPushButton("أعد القراءة من الحكم")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"QPushButton{{border:1px solid #c9d3dc; border-radius:6px; background:transparent; color:{SLATE};"
                        f"font-family:{F}; font-size:11px; padding:2px 8px;}}")
        b.setEnabled(not self._busy)
        b.clicked.connect(lambda: self._rewrite('mission'))
        head.addWidget(b)
        self.card_lay.addLayout(head)
        self._add_editor('\n'.join(p['text'] for p in m.get('points') or []) or (m.get('raw') or ''))

    def _card_procedures(self):
        """تلقائية: «تم الاطلاع على N محضر» + قائمة التحقق + نص الإجراءات القابل للتعديل + زرّا التعديل فقط."""
        proc = self.data.get('procedures') or {}
        self._autowrite_block('procedures')
        if proc.get('changed_notice'):
            self.card_lay.addWidget(_lbl("⚠ " + proc['changed_notice'], 12, rc.ERROR, True))
        if proc.get('auto_text'):
            self.card_lay.addWidget(_lbl(case_procedures.summary_line(self.data), 15, NAVY, True))
            self._missing_line(case_procedures.missing_line(self.data))
            rows = []
            for c in case_procedures.build_checks(self.data):
                mark, col = (('✓', rc.SECONDARY) if c['ok'] else ('×', rc.ERROR) if c['ok'] is False
                             else ('•', rc.GRAY_TEXT))
                rows.append(f"<span style='color:{col}'>{mark}</span> {c['text']}")
            self.card_lay.addWidget(_lbl('<br>'.join(rows), 13, rc.INK))
            self.card_lay.addWidget(_lbl("نص الإجراءات في التقرير (يُحدَّث وحده، وتعديلك يُحفظ تلقائياً):",
                                         12, rc.GRAY_TEXT))
            self._add_editor((self.data.get('procedures') or {}).get('text') or '', min_h=150)
        elif not self._busy:
            self.card_lay.addWidget(_lbl("تُؤخذ المحاضر وتُقارن بجلسات النظام تلقائياً عند فتح هذه الخطوة.",
                                         13, rc.GRAY_TEXT))
        self._actions_row([("إعادة الكتابة", lambda: self._rewrite('procedures'), False),
                           ("إضافة محضر آخر", lambda: self.do('procedures', 'add'), False),
                           ("تعديل", lambda: self.do('procedures', 'attend'), False)])

    def _card_documents(self):
        """لوحة المستندات الواحدة: الإضافة والقائمة، و«ما يفعله البرنامج الآن» بخطوات خط البداية. العقود في «البحث ورأي الخبرة»."""
        self._alerts_block('documents')
        from qt_documents_panel import DocumentsPanel
        self.docs_panel = DocumentsPanel(self.base, self.data, self, on_changed=self._after_docs_panel,
                                         caso_no=self.data.get('caso_no', ''))
        self.docs_panel.step_source = lambda: self.data     # خطوات خط البداية من بيانات الصفحة الحالية
        self.docs_panel.retry.connect(self._retry_conversion)
        self.docs_panel.answer.connect(self._answer_sort)
        self.docs_panel.reread.connect(self._reread_doc)
        self.docs_panel.retriage.connect(self._retriage_docs)
        self._docs_tabs = self.docs_panel
        self.docs_panel.setFixedHeight(DOCS_MIN_H)
        QTimer.singleShot(0, self._fit_docs_tabs)        # تملأ الصفحة؛ القائمة واللوحة تتمرّران داخلياً
        self.card_lay.addWidget(self.docs_panel)
        items = []
        if case_documents.pending_docs(self.data) and qdd.active_job(self.base) is None:
            items.append(("استئناف", lambda: self.do('documents', 'resume'), False))
        if case_model.state(self.data, 'documents') == 'failed':
            items.append(("تابع رغم النقص", lambda: self.do('documents', 'waive'), False))
        if items:
            self._actions_row(items)

    def _contracts_block(self):
        """العقود بين المدعية والمدعى عليه (تاريخه وما تضمّنه وقيمته) — داخل البحث لأن العقد جزء منه."""
        import case_contracts
        recs = (self.data.get('contracts') or {}).get('items') or []
        if recs and any('evidence' not in c for c in recs):
            try:                                     # مكان إثبات كل عقد من وجه الحافظة
                case_contracts.attach_evidence(self.base, self.data)
                case_workspace.write_case_json(self.base, self.data)
            except Exception:
                pass
        between = case_contracts.items(self.data, case_contracts.SCOPE_IN)
        extra = case_contracts.not_in_plaint(self.data)
        if not between and not extra:
            return
        box = QFrame()
        box.setObjectName('contracts')
        box.setStyleSheet(f"QFrame#contracts{{background:{rc.SURFACE}; border:1px solid #e1e6eb; border-radius:10px;}}")
        l = QVBoxLayout(box)
        l.setContentsMargins(14, 10, 14, 10)
        l.addWidget(_lbl("العقود", 14, NAVY, True))
        for i, c in enumerate(between, 1):
            r = QHBoxLayout()
            r.addWidget(_lbl(f"{i}.", 13, NAVY, True, wrap=False), 0, Qt.AlignmentFlag.AlignTop)
            r.addWidget(_lbl(case_contracts.contract_line(c), 13, rc.INK), 1)
            l.addLayout(r)
        if extra:
            l.addWidget(_lbl("ℹ قُدّمت عقود لم تُذكر في صحيفة الدعوى: "
                             + '؛ '.join(case_contracts.contract_line(c) for c in extra), 12, rc.GRAY_TEXT))
        self.card_lay.addWidget(box)

    def _retry_conversion(self, rel):
        """زر «إعادة» لملف «تعذّر التحويل»: يُمسح فشله من manifest فيُعاد تحويله من البداية في المزامنة."""
        import case_folder
        man = case_folder.load_manifest(self.base)
        e = man['files'].get(rel)
        if e is not None:
            e['state'], e['message'] = 'pending', ''
            e.pop('loop', None)
            case_folder.save_manifest(self.base, man)
        self.sync_folder()

    def _reread_doc(self, rel, engine=''):
        """السهم الدائري/«أعد القراءة بجيميناي»: تحويل الملف وفرزه من جديد (شريط التقدّم في صفّه)، ثم المزامنة
        (الملخص والموضوع يتجددان إن تغيّر ما فُرز)."""
        import case_folder
        ask = self._ask_for('الفرز')
        name = os.path.splitext(os.path.basename(rel))[0]

        def work():
            import gemini_quota
            with gemini_quota.mode('ui'):                 # زر مباشر: حصة الواجهة (حتى 500) لا سقف الخلفية الناعم
                case_folder.reread_file(self.base, self.data, rel, ask=ask, engine=engine or None)
            case_workspace.write_case_json(self.base, self.data)
        self._after = self.sync_folder
        self._run_bg(work, f"إعادة قراءة «{name}» (التحويل ثم الفرز)…")

    @staticmethod
    def requests_word(n):
        return 'طلب واحد' if n == 1 else 'طلبان' if n == 2 else f'{n} طلبات' if 3 <= n <= 10 else f'{n} طلباً'

    def _retriage_docs(self, rels):
        """أيقونة «إعادة فرز»: من markdown الموجود (بلا تحويل ولا OCR) بطلبات مجمّعة (case_sort.retriage — دفعة لكل ~80
        ألف حرف). rels=None = «إعادة فرز الكل» بعد تأكيد يوضح عدد الطلبات المتوقع."""
        import case_folder
        import case_sort
        if self._busy:
            return
        n, req = case_sort.retriage_plan(self.base, rels)
        if not n:
            QMessageBox.information(self, "إعادة الفرز", "لا مستند محوَّل لإعادة فرزه.")
            return
        if rels is None and QMessageBox.question(
                self, "إعادة فرز الكل",
                f"ستُعاد فرز {case_folder.files_word(n)} من نصوصها المحوَّلة (بلا OCR) في {self.requests_word(req)} "
                "للذكاء الاصطناعي، وتُعاد تسمية الملفات ونقلها حسب النتيجة. ما حدّدته بيدك لا يُمسّ. متابعة؟"
        ) != QMessageBox.StandardButton.Yes:
            return
        ask = self._ask_for('الفرز')
        name = os.path.splitext(os.path.basename(rels[0]))[0] if rels else ''

        def work():
            import gemini_quota
            with gemini_quota.mode('ui'):
                case_sort.retriage(self.base, self.data, ask, rels=rels)
            case_workspace.write_case_json(self.base, self.data)
        self._after = self.sync_folder
        self._run_bg(work, f"إعادة فرز «{name}» من markdown…" if rels else
                     f"إعادة فرز {case_folder.files_word(n)} ({self.requests_word(req)})…")

    def _ocr_reviewed(self, rel):
        """«راجعته»: يُخفى تنبيه القراءة لهذا المستند."""
        import case_folder
        case_folder.mark_reviewed(self.base, self.data, rel)
        case_workspace.write_case_json(self.base, self.data)
        self._render_card()

    def _answer_sort(self, rel):
        """زر «تحديد» لملف لم يُحسم فرزه: سؤال واحد (النوع/المقدّم/التاريخ) ثم التسمية والنقل."""
        import case_sort
        from qt_startup_panel import SortAnswerDialog
        q = dict(case_sort.questions(self.data)).get(rel, '')
        dlg = SortAnswerDialog(os.path.basename(rel), q, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()

        def work():
            case_sort.answer(self.base, self.data, rel, **v)
            case_workspace.write_case_json(self.base, self.data)
        self._after = self.sync_folder
        self._run_bg(work, "تسمية المستند ونقله…")

    def _autowrite_block(self, key):
        """ملاحظة المصدر («كُتب من صحيفة الدعوى»…) وسؤال «توفر مصدر أحدث، أعد الكتابة؟» بزر لنص عدّله الخبير."""
        import case_autowrite
        note, newer = case_autowrite.line(self.data, key)
        if note:
            self.card_lay.addWidget(_lbl(f"ℹ {note}", 11, rc.GRAY_TEXT))
        if newer:
            row = QHBoxLayout()
            row.addWidget(_lbl(f"⚠ {newer}", 12, rc.AMBER, True), 1)
            b = _btn("أعد الكتابة")
            b.setEnabled(not self._busy)
            b.clicked.connect(lambda: self._accept_newer(key))
            row.addWidget(b)
            self.card_lay.addLayout(row)

    def _accept_newer(self, key):
        import case_autowrite
        if self._dirty:
            self.autosave()
        import case_stage2
        ask = self._ask_for(case_stage2.PURPOSE) if key == 'subject' else None
        fn = ((lambda: case_stage2.run(self.base, self.data, ask, force=True, replace_manual=True)) if key == 'subject'
              else (lambda: case_procedures.evaluate(self.base, self.data, None)))

        def work():
            case_autowrite.accept_newer(self.base, self.data, key, fn)
            case_workspace.write_case_json(self.base, self.data)
        self._run_bg(work, "إعادة الكتابة من المصدر الأحدث…")

    def _do_documents(self, action):
        """«إضافة مستندات» تفتح خطوة المستندات (اللوحة المضمَّنة) بدل نافذة؛ بقية الأفعال كما في الأب."""
        if action == 'add':
            self.open_step('documents')
            return
        super()._do_documents(action)

    def _fit_docs_tabs(self):
        """ارتفاع تبويبات المستندات (أو محرّر الخطوة) = المساحة المرئية ناقص بقية البطاقة: البطاقة لا تتمرّر،
        فالمسار فوق والأزرار تحت ثابتة دائماً ولا تختفي."""
        if self._open != 'documents':
            ed = self.editor
            if ed is None:
                return
            try:
                other = self.card.sizeHint().height() - ed.height()
                ed.setFixedHeight(max(110, self._scroll.viewport().height() - other - 4))
            except RuntimeError:
                pass
            return
        tabs = getattr(self, '_docs_tabs', None)
        if tabs is None:
            return
        try:
            other = self.card.sizeHint().height() - tabs.height()
        except RuntimeError:                    # البطاقة أُعيد رسمها
            return
        tabs.setFixedHeight(max(DOCS_MIN_H, self._scroll.viewport().height() - other - 4))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._fit_docs_tabs)

    def _after_docs_panel(self):
        """انتهى عمل اللوحة: ما أُضيف يدخل مزامنة المجلد (المحوَّل مسجّل فلا يُعاد) ثم تتحدّث الخطوة."""
        QTimer.singleShot(0, self.sync_folder)

    @staticmethod
    def contract_text(c):
        """سطر العقد ونصّ ما لم يتحقق (للأحمر)."""
        bits = [c['kind'], f"بتاريخ {c['date']}" if c.get('date') else '',
                f"بين {' و'.join(c['parties'])}" if c.get('parties') else '',
                f"بقيمة {c['value']}" if c.get('value') else '', f"مدته {c['duration']}" if c.get('duration') else '',
                f"— {c['scope_of_work']}" if c.get('scope_of_work') else '',
                f"({c['doc']}" + (f"، ص {c['page']})" if c.get('page') else ')')]
        why = []
        if c.get('scope_reason') and c.get('scope') != 'بين طرفي الدعوى':
            why.append(f"السبب: {c['scope_reason']}")
        if c.get('in_plaint') is True:
            why.append('مذكور في الصحيفة')
        elif c.get('in_claim') is False and c.get('claim_reason'):
            why.append(f"غير مرتبط بالطلبات: {c['claim_reason']}")
        elif c.get('in_claim') and c.get('claim_reason'):
            why.append(f"مرتبط بالطلبات: {c['claim_reason']}")
        if why:
            bits.append('— ' + '؛ '.join(why))
        bad = [lab for k, lab in (('date', 'التاريخ'), ('value', 'القيمة')) if (c.get('checks') or {}).get(k) is False]
        return ' '.join(b for b in bits if b), (f"⚠ لم يُتحقق من {' و'.join(bad)} في نص المستند" if bad else '')

    def _contract_row(self, c):
        import case_contracts
        text, bad = self.contract_text(c)
        r = QHBoxLayout()
        r.addWidget(_lbl(text + (f"  {bad}" if bad else ''), 12, rc.ERROR if bad else rc.INK, bool(bad)), 1)
        if c['scope'] != case_contracts.SCOPE_IN:
            r.addWidget(_tag(c['scope'], (rc.SURFACE, rc.GRAY_TEXT) if hasattr(rc, 'SURFACE') else tag_colors('', 3)))
        return r

    def _picker(self, items, fmt):
        self.picker = QComboBox()
        self.picker.setStyleSheet(COMBO_QSS)          # القائمة المنبثقة بيضاء (لا شاشة سوداء من خلفية الصفحة الشفافة)
        for it in items:
            self.picker.addItem(fmt(it), it['id'])
        self.picker.currentIndexChanged.connect(self._on_pick)
        self.card_lay.addWidget(self.picker)

    AUTO_READINESS = True           # تُطفأ في بعض الاختبارات

    def _readiness_block(self):
        """بطاقة «الجاهزية»: لكل بند جاهز/ناقص ودرجته وجملة واضحة؛ «اكتب رغم النقص» للناقص."""
        r = self.data.get('readiness') or {}
        box = QFrame()
        box.setObjectName('ready')
        box.setStyleSheet(f"QFrame#ready{{background:{rc.SURFACE}; border:1px solid #e1e6eb; border-radius:10px;}}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.addWidget(_lbl("الجاهزية", 14, NAVY, True))
        if not r:
            lay.addWidget(_lbl("لم يُفحص بعد — يجري الفحص تلقائياً عند فتح الخطوة.", 12, rc.GRAY_TEXT))
        for res in r.get('items') or []:
            row = QHBoxLayout()
            ok = res['state'] == case_readiness.READY
            row.addWidget(_tag(f"{'جاهز' if ok else 'تعذّر الفحص' if res['state'] == 'error' else 'ناقص'} {res['score']}%",
                               (rc.SECONDARY_SOFT, NAVY) if ok else (rc.AMBER_SOFT, rc.AMBER)))
            row.addWidget(_lbl(case_readiness.sentence(self.data, res)
                               + ('' if ok or res['state'] == 'error' else ' — بانتظار مستند'), 12, rc.INK), 1)
            lay.addLayout(row)
        if r.get('closed'):
            lay.addWidget(_lbl(f"أُغلق {len(r['closed'])} طلباً سُدّ بالمستندات الجديدة.", 12, rc.SECONDARY))
        if any(res['state'] not in (case_readiness.READY, 'error') for res in r.get('items') or []):
            lay.addWidget(_lbl("البند الناقص يُكتب مع ملاحظة حمراء «ناقص» (لا أرقام ناقصة).", 11, rc.GRAY_TEXT))
        self.card_lay.addWidget(box)

    def _run_readiness(self):
        """فحص الجاهزية بالكود من الملخص (بلا طلب ذكاء — المراحل الثلاث)."""
        if self._busy:
            return
        before = (self.data.get('readiness') or {}).get('code_sig')
        try:
            case_readiness.run_code(self.base, self.data)
        except case_model.StepError:
            return
        if (self.data.get('readiness') or {}).get('code_sig') != before and self._open and not self._dirty:
            self._render_card()

    def _auto_readiness(self):
        """فتح خطوة البحث أو تغيّر الملخص ← فحص بالكود (لا طلب؛ لا كتابة إن لم يتغيّر شيء)."""
        if self._busy or not self.AUTO_READINESS or not (self.data.get('mission') or {}).get('points'):
            return
        if self._open == 'research' or self.data.get('readiness'):
            self._run_readiness()

    # ---------- البحث ورأي الخبرة بأسلوب الخبير (research_pipeline، 2026-10-20) ----------
    DELIVERY_LABELS = (('api', 'جيميناي'), ('browser', 'عبر المتصفح'))
    COPILOT_URL = 'https://m365.cloud.microsoft/chat'

    def _delivery(self):
        d = research_pipeline.state(self.data).get('delivery') or 'api'
        return 'browser' if d in ('copilot', 'browser') else 'api'           # «ملف prompt.md» أُزيل (2026-10-22)

    def _write_ready(self):
        """«كتابة البحث ورأي الخبرة» (المرحلة الثالثة): طلب واحد عبر API، أو عبر المتصفح، أو ملف prompt.md."""
        if self._busy or not (self.data.get('mission') or {}).get('points'):
            return
        mode = self._delivery()
        if mode in ('browser', 'copilot'):
            self._browser_write('stage3')
            return
        import report_v3
        ask = self._ask_for('البحث')
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)
        self._start_rewrite('research', None)
        self._run_bg(lambda: report_v3.write_full(self.base, self.data, ask=ask, stop=lambda: self._stop,
                                                  on_progress=self._rp_progress_cb),
                     "جارٍ كتابة البحث كاملاً (الحقائق ثم المحاور) ثم النتيجة… يرجى الانتظار: كتابة التقرير "
                     "تحتاج وقتاً (قد تصل إلى عدة دقائق) — لا تغلق البرنامج.")

    def _rp_progress_cb(self, axis, sec):
        """من الخيط الخلفي: لقطة تقدم تقرؤها الواجهة كل ثانية (لا لمس للودجات من الخيط)."""
        secs = research_pipeline.all_sections(self.data)
        done = sum(1 for _a, s in secs if s['state'] in (research_pipeline.S_DRAFTED, research_pipeline.S_MERGED,
                                                          research_pipeline.S_FAILED, research_pipeline.S_BLOCKED))
        label = sec.get('contract_title') or sec.get('title') or ''
        self._rp_progress = {'text': f"{done} من {len(secs)} — {axis['ordinal']}" + (f" / {label}" if label else ''),
                             'bars': {s['key']: s.get('progress') or 0 for _a, s in secs}}

    def sync_step_text(self):
        """الخطوة الجارية لمزامنة المجلد (تنزيل OneDrive، أو خطوة خط البداية وعدّادها) — '' إن لا شيء."""
        import case_startup
        import cloud_files
        cloud = cloud_files.current()
        if cloud:
            return cloud
        live = case_startup.live(self.base) or {}
        for k, label in case_startup.STEPS:
            s = live.get(k) or {}
            if s.get('state') == case_startup.RUNNING:
                bits = [label, case_startup.counter_text(s), os.path.basename(s.get('message') or '')]
                return ' — '.join(b for b in bits if b)
        return ''

    def _rp_tick(self):
        snap = getattr(self, '_rp_progress', None)
        if self._busy and not (snap and self._open == 'research'):
            step = self.sync_step_text()                  # مزامنة المجلد بالخلفية: الخطوة الجارية بوضوح
            lbl = getattr(self, '_busy_lbl', None)
            if step and lbl is not None:
                try:
                    lbl.setText(f"⏳ {self._busy_text} — {step}")
                except RuntimeError:
                    pass
            return
        if not snap or not self._busy or self._open != 'research':
            return
        lbl = getattr(self, '_busy_lbl', None)
        if lbl is not None:
            try:
                lbl.setText(f"⏳ {self._busy_text} — {snap['text']}")
            except RuntimeError:
                pass
        for key, val in snap['bars'].items():
            bar = (getattr(self, '_rp_bars', {}) or {}).get(key)
            if bar is not None:
                try:
                    bar.setValue(int(val))
                except RuntimeError:
                    pass

    def _axis_of_point(self, pid):
        return next((a for a in research_pipeline.state(self.data).get('axes') or [] if pid in a['point_ids']), None)

    def _write_despite(self, pid):
        """«اكتب رغم النقص» لبند ناقص: يكتب محوره كله مع ملاحظة «ناقص» حمراء (لا أرقام ناقصة)."""
        res = case_readiness.item(self.data, pid)
        if self._busy or res is None:
            return
        if not research_pipeline.state(self.data).get('axes'):
            research_pipeline.build_plan(self.base, self.data)
        axis = self._axis_of_point(pid)
        if axis is None:
            return
        self._start_rewrite('research', None)
        ask = self._ask_for('اكتب رغم النقص')
        self._run_bg(lambda: research_pipeline.run(self.base, self.data, ask=ask, only_axes={axis['key']},
                                                   despite_missing=True, on_progress=self._rp_progress_cb),
                     f"جارٍ كتابة المحور {axis['ordinal']} رغم النقص (الناقص ملاحظة حمراء منفصلة)…")

    def _rewrite_axis(self, axis_key):
        """«أعد صياغة هذا المحور»: الحقائق والحساب والصياغة من جديد؛ المدموج يعود مسودة للمعاينة."""
        if self._busy:
            return
        axis = next((a for a in research_pipeline.state(self.data).get('axes') or [] if a['key'] == axis_key), None)
        if axis is None:
            return
        if any(s.get('edited') for s in axis['sections']) and QMessageBox.question(
                self, "أعد صياغة هذا المحور", "عدّلتَ نص هذا المحور بيدك. إعادة الصياغة ستستبدله بمسودة جديدة. متابعة؟"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._start_rewrite('research', None)
        ask = self._ask_for('إعادة كتابة بند')
        ready, _miss = research_pipeline.axis_ready(self.data, axis)
        self._run_bg(lambda: research_pipeline.rewrite_axis(self.base, self.data, axis_key, ask=ask,
                                                            despite_missing=not ready),
                     f"جارٍ إعادة صياغة المحور {axis['ordinal']}…")

    def _export_prompt(self, mode):
        """ملف prompt.md واحد (للنموذج الخاص أو Copilot): الحقائق المتحقَّقة والأرقام الجاهزة والأقسام بالترتيب."""
        ask = self._ask_for('البحث')
        out = {}

        def work():
            out['path'] = research_pipeline.export_prompt(self.base, self.data, ask=ask, delivery=mode)

        def after():
            path = out.get('path')
            if not path:
                return
            if mode == 'copilot':
                try:
                    with open(path, encoding='utf-8') as f:
                        QGuiApplication.clipboard().setText(f.read())
                    if self.OPEN_EXTERNAL:
                        from PyQt6.QtCore import QUrl
                        from PyQt6.QtGui import QDesktopServices
                        QDesktopServices.openUrl(QUrl(self.COPILOT_URL))
                except Exception:
                    pass
                self._notice = ("نُسخ الطلب إلى الحافظة وفُتح Copilot — الصقه هناك، ثم انسخ الرد كاملاً واضغط «لصق الرد».",
                                False)
            else:
                self._notice = (f"كُتب الملف: {path} — أرسله لنموذجك، ثم «استيراد الرد».", False)
                if self.OPEN_EXTERNAL:
                    try:
                        os.startfile(os.path.dirname(path))
                    except (OSError, AttributeError):
                        pass
            self._render_card()
        self._after = after
        self._run_bg(work, "جارٍ تجهيز الحقائق والأرقام وكتابة prompt.md…")

    OPEN_EXTERNAL = True            # تُطفأ في الاختبارات (فتح المجلد/المتصفح)
    AUTO_CONCLUSION = True          # توليد النتيجة بعد اعتماد البحث (API)

    def _import_reply(self, from_file, text=None):
        """يستورد ردّ نموذج الخبير/Copilot: كل قسم يمر بفحص الكود نفسه فيصير مسودة للمعاينة."""
        if self._busy:
            return
        if text is None and from_file:
            path, _ = QFileDialog.getOpenFileName(self, "ملف الرد", self.base, "نص (*.md *.txt);;كل الملفات (*.*)")
            if not path:
                return
            with open(path, encoding='utf-8', errors='replace') as f:
                text = f.read()
        elif text is None:
            from PyQt6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getMultiLineText(self, "لصق الرد", "الصق الرد كاملاً (بعلامات ===القسم …===):")
            if not ok:
                return
        try:
            res = research_pipeline.import_reply(self.base, self.data, text, source=self._delivery())
        except case_model.StepError as e:
            QMessageBox.warning(self, "تعذّر الاستيراد", str(e))
            return
        msg = f"قُبل {len(res['accepted'])} قسماً مسودةً للمعاينة"
        if res['rejected']:
            msg += f"، ورُفض {len(res['rejected'])}: " + '؛ '.join(f"{k} ({w[:80]})" for k, w in res['rejected'][:4])
        if res.get('conclusion'):
            msg += f". النتيجة: {res['conclusion']}"
        self._notice = (msg, bool(res['rejected']))
        self.reload()

    def _fx_dialog(self):
        """سعر الصرف وتاريخه (اجتهاد الخبير) — يدخل الحساب بالكود ويُسجَّل في «قرارات تحتاج مراجعة»."""
        from PyQt6.QtWidgets import QFormLayout, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("سعر الصرف")
        dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        form = QFormLayout(dlg)
        cur = QComboBox()
        cur.setStyleSheet(COMBO_QSS)
        for code in ('USD', 'EUR', 'GBP', 'SAR', 'AED'):
            cur.addItem(f"{research_pipeline.calc.CURRENCY_NAMES[code]} ({code})", code)
        fx = (research_pipeline.state(self.data).get('decisions') or {}).get('fx') or {}
        rate, date, basis = QLineEdit(), QLineEdit(), QLineEdit()
        date.setPlaceholderText("dd/mm/yyyy")
        basis.setPlaceholderText("سبب اختيار التاريخ (مثل: تاريخ انتهاء العقد)")

        def fill():
            v = fx.get(cur.currentData()) or {}
            rate.setText(v.get('rate', ''))
            date.setText(v.get('date', ''))
            basis.setText(v.get('basis', ''))
        cur.currentIndexChanged.connect(lambda _i: fill())
        fill()
        form.addRow("العملة", cur)
        form.addRow("السعر (د.ك لكل وحدة)", rate)
        form.addRow("تاريخ السعر", date)
        form.addRow("الأساس", basis)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            research_pipeline.set_fx(self.base, self.data, cur.currentData(), rate.text(), date.text(), basis.text())
        except (case_model.StepError, research_pipeline.calc.CalcError) as e:
            QMessageBox.warning(self, "سعر الصرف", str(e))
            return
        self._notice = ("حُفظ سعر الصرف — أعد صياغة محور الحساب ليدخل الحساب.", False)
        self._render_card()

    def _set_delivery(self, mode):
        import browser_write as bw
        mode = 'browser' if mode == 'copilot' else mode            # Copilot صار أحد مواقع «عبر المتصفح»
        r = research_pipeline.state(self.data)
        if r.get('delivery') == mode:
            return
        r['delivery'] = mode
        self.data.setdefault('ai_mode', {})['stage3'] = 'browser' if mode == 'browser' else 'api'
        case_workspace.write_case_json(self.base, self.data)
        if mode == 'browser':
            bw.set_mode(self.base, self.data, 'stage3', 'browser')
        QTimer.singleShot(0, self._render_card)

    def _delivery_block(self):
        from PyQt6.QtWidgets import QRadioButton, QButtonGroup
        box = QFrame()
        box.setObjectName('deliv')
        box.setStyleSheet(f"QFrame#deliv{{background:{rc.SURFACE}; border:1px solid #e1e6eb; border-radius:10px;}}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.addWidget(_lbl("طريقة الكتابة", 14, NAVY, True))
        row = QHBoxLayout()
        grp = QButtonGroup(box)
        mode = self._delivery()
        self._delivery_buttons = {}
        for key, label in self.DELIVERY_LABELS:
            rb = QRadioButton(label)
            rb.setChecked(key == mode)
            rb.setEnabled(not self._busy)
            rb.toggled.connect(lambda on, k=key: on and self._set_delivery(k))
            grp.addButton(rb)
            row.addWidget(rb)
            self._delivery_buttons[key] = rb
        row.addStretch()
        lay.addLayout(row)
        hint = {'api': "طلب واحد لجيميناي: الملخص + المستندات الحاسمة ← الحقائق المالية والخانات القصيرة، ثم يحسب الكود "
                       "الأرقام ويركّب المحاور والنتيجة ويدقّقها ويدمجها في التقرير.",
                'browser': "الطلب نفسه يُفتح في الموقع المختار (لصق تلقائي إن أمكن، وإلا الحافظة)؛ «لصق الرد» يمر على نفس التحقق.",
                'file': "يجهّز البرنامج الحقائق المتحقَّقة والأرقام في prompt.md واحد لنموذجك الخاص، ثم تستورد الرد فيُفحص بالكود."
                }.get(mode, '')
        lay.addWidget(_lbl(hint, 11, rc.GRAY_TEXT))
        self.card_lay.addWidget(box)
        written = bool(self.data.get('research_written') or research_pipeline.state(self.data).get('axes'))
        if mode == 'browser':
            self._stage_actions('stage3', self._write_ready)
            return
        go = _btn("إعادة الكتابة" if written else "اكتب البحث", True)
        go.setToolTip("البحث كاملاً من جديد (الحقائق والحساب والمحاور) ثم النتيجة، ويُدمج في التقرير تلقائياً")
        go.setEnabled(bool((self.data.get('mission') or {}).get('points')) and not self._busy)
        go.clicked.connect(self._write_ready)
        row2 = QHBoxLayout()
        row2.addStretch()
        row2.addWidget(go)
        self.card_lay.addLayout(row2)

    @staticmethod
    def axis_name(a):
        """اسم المحور في القوائم: عنوانه (أو موضوعه المختصر) بدل «نص المحور»."""
        t = ' '.join(str(a.get('title') or '').split()).rstrip(':')
        return (t if len(t) <= 60 else t[:58] + '…') or 'نص المحور'

    def _rewrite_btn(self, a, failed):
        """أيقونة خفيفة «إعادة كتابة هذا البند» بنمط السهم الدائري؛ تبرز (إطار أحمر) عند «تعذّر»."""
        import qt_icons
        b = QPushButton()
        b.setIcon(qt_icons.icon('pen', rc.ERROR if failed else '#475569', active=NAVY, size=15))
        b.setFixedSize(26, 26)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip("إعادة كتابة هذا البند (هذا المحور وحده — بقية المحاور المدموجة لا تُمسّ)")
        b.setStyleSheet(f"QPushButton{{background:{rc.ERROR_SOFT if failed else 'white'};"
                        f"border:1px solid {rc.ERROR if failed else '#e1e6eb'}; border-radius:8px;}}"
                        "QPushButton:hover{background:#f8fafc; border-color:#cbd5e1;}")
        b.setEnabled(not self._busy)
        b.clicked.connect(lambda _=False, k=a['key']: self._rewrite_axis(k))
        return b

    def _plan_block(self):
        """لكل محور: عنوانه؛ لكل عقد/قسم: حالته وشريط تقدم وأيقونة «إعادة كتابة هذا البند» (المحور وحده)."""
        from PyQt6.QtWidgets import QProgressBar
        self._rp_bars = {}
        names = {'total': 'تصفية الحساب الإجمالية', 'objections': 'اعتراضات الأطراف والرد عليها'}
        for a in research_pipeline.state(self.data).get('axes') or []:
            box = QFrame()
            box.setObjectName('axis')
            box.setStyleSheet("QFrame#axis{background:#ffffff; border:1px solid #e1e6eb; border-radius:10px;}")
            lay = QVBoxLayout(box)
            lay.setContentsMargins(14, 8, 14, 8)
            head = QHBoxLayout()
            t = research_pipeline.heading(a)
            head.addWidget(_lbl(t if len(t) <= 110 else t[:108] + '…:', 13, NAVY, True), 1)
            lay.addLayout(head)
            for s in a['sections']:
                row = QHBoxLayout()
                label = s.get('contract_title') or names.get(s['kind']) or ''
                row.addWidget(_lbl(label, 12, rc.INK), 1)
                st = s['state']
                bad = st in (research_pipeline.S_FAILED, research_pipeline.S_BLOCKED)
                row.addWidget(_tag(research_pipeline.STATE_TEXT.get(st, st),
                                   (rc.ERROR_SOFT, rc.ERROR) if bad else (rc.SECONDARY_SOFT, NAVY)))
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(int(s.get('progress') or 0))
                bar.setFixedWidth(110)
                bar.setTextVisible(False)
                self._rp_bars[s['key']] = bar
                row.addWidget(bar)
                row.addWidget(self._rewrite_btn(a, st == research_pipeline.S_FAILED))
                lay.addLayout(row)
                if bad and s.get('message'):
                    lay.addWidget(_lbl(s['message'], 11, rc.ERROR))
            self.card_lay.addWidget(box)

    def _research_notes_block(self):
        """الملاحظات الحمراء منفصلة عن النص: ناقص، قرارات تحتاج مراجعة الخبير (مع البدائل)، فروق أرقام، المحذوف."""
        import report_v3
        import report_audit
        errs = (research_pipeline.state(self.data).get('audit') or {}).get('errors') or []
        if report_v3.audit_line(self.data) and errs:     # سطر واحد يُفتح للتفاصيل بجمل عربية (لا رموز)
            head = QPushButton(report_audit.summary_line(errs))
            head.setCursor(Qt.CursorShape.PointingHandCursor)
            head.setStyleSheet(f"QPushButton{{text-align:right; color:{rc.ERROR}; background:{rc.ERROR_SOFT};"
                               "border:none; border-radius:8px; padding:8px 12px; font-weight:700;}")
            det = _lbl('<br>'.join('• ' + report_audit.plain(e) for e in errs), 12, rc.ERROR)
            det.setVisible(False)
            head.clicked.connect(lambda _=False, d=det: d.setVisible(not d.isVisible()))
            self.card_lay.addWidget(head)
            self.card_lay.addWidget(det)
        notes = research_pipeline.notes_list(self.data)
        if not notes:
            return
        groups = {}
        for kind, text, where in notes:
            if kind == 'فشل التدقيق':
                continue                                  # يظهر في السطر الواحد أعلاه
            groups.setdefault(kind, []).append(f"({where}) {text}")
        for kind in (research_pipeline.N_MISSING, research_pipeline.N_DECISION, research_pipeline.N_DIFF,
                     research_pipeline.N_REMOVED, research_pipeline.N_DEDUP):
            rows = groups.get(kind) or []
            if not rows:
                continue
            title = 'قرارات تحتاج مراجعة الخبير' if kind == research_pipeline.N_DECISION else kind
            shown = rows[:8] + ([f"… و{len(rows) - 8} أخرى (ملاحظات_البحث.md)"] if len(rows) > 8 else [])
            self.card_lay.addWidget(_lbl(f"⚠ {title}:<br>" + '<br>'.join('• ' + x for x in shown), 12, rc.ERROR, False))

    def _preview(self, key):
        if self.picker is None:
            return
        i = self.picker.findData('S:' + key)
        if i >= 0:
            self.picker.setCurrentIndex(i)

    def _preview_block(self):
        """المعاينة قبل الدمج: كل قسم كُتب (مسودة/مدموج) + النتيجة؛ التعديل يُحفظ تلقائياً."""
        entries = []
        for a, s in research_pipeline.all_sections(self.data):
            if not s.get('file'):
                continue
            label = s.get('contract_title') or {'total': 'تصفية الحساب الإجمالية',
                                                'objections': 'الاعتراضات'}.get(s['kind']) or self.axis_name(a)
            entries.append({'id': 'S:' + s['key'],
                            '_label': f"{a['ordinal']} — {label[:60]} ({research_pipeline.STATE_TEXT[s['state']]})"})
        rec = conclusion_pipeline.record(self.data)
        if rec:
            entries.append({'id': 'C2', '_label': 'النتيجة' + (' — عدّلها الخبير' if rec.get('edited') else '')})
        for n in conclusion_pipeline.notes(self.base, self.data):
            self.card_lay.addWidget(_lbl(f"⚠ النتيجة: {n}", 12, rc.ERROR, True))
        if not entries:
            self.card_lay.addWidget(_lbl("لم يُكتب البحث بعد — اضغط «اكتب البحث».", 13, rc.GRAY_TEXT))
            return
        self._picker(entries, lambda e: e['_label'])
        self._add_editor(self._v2_text(entries[0]['id']))
        self._last_pick = entries[0]['id']

    def _v2_text(self, pid):
        pid = str(pid or '')
        if pid == 'C2':
            rec = conclusion_pipeline.record(self.data)
            return conclusion_pipeline.text_of(rec) if rec else ''
        if pid.startswith('S:'):
            _a, s = research_pipeline.section(self.data, pid[2:])
            return research_pipeline.section_text(self.base, s) if s else ''
        return ''

    def _auto_conclusion(self):
        """النتيجة تُولَّد وتُحدَّث وحدها (بلا ضغط «اكتب») حين يكتمل/يُدمج البحث أو يتغيّر نصه؛ ونتيجة عدّلها الخبير
        بيده لا تُستبدل (تظهر ملاحظة «البحث تغيّر بعد تعديلك للنتيجة»؛ «إعادة الكتابة» تكتبهما). محاولة واحدة لكل نص بحث."""
        if (self._busy or not self.AUTO_CONCLUSION or not case_conclusion.is_v2(self.data)
                or self._delivery() != 'api' or not conclusion_pipeline.needs_regen(self.base, self.data)):
            return
        sig = conclusion_pipeline.current_sha(self.base, self.data)
        if getattr(self, '_auto_concl_sig', None) == sig:
            return
        self._auto_concl_sig = sig
        ask = self._ask_for('النتيجة')

        def work():
            try:
                case_conclusion.run_conclusion(self.base, self.data, ask=ask)
            except case_model.StepError:
                pass                                   # السبب محفوظ في v2_error ويظهر ملاحظة حمراء، بلا نافذة منبثقة
        self._run_bg(work, "جارٍ كتابة النتيجة من نص البحث…")

    def _merge_current(self):
        pid = str(self.picker.currentData() if self.picker is not None else '')
        if self._busy or not pid.startswith('S:'):
            return
        self.autosave()
        try:
            research_pipeline.merge_section(self.base, self.data, pid[2:])
        except case_model.StepError as e:
            QMessageBox.warning(self, "دمج", str(e))
            return
        self.reload()

    def _merge_all(self):
        if self._busy:
            return
        self.autosave()
        n = research_pipeline.merge_all(self.base, self.data)
        self._notice = (f"دُمج {n} قسماً في نص البحث.", False) if n else ("لا مسودات جديدة للدمج.", False)
        self.reload()

    def _card_research(self):
        """البحث ورأي الخبرة ومعه النتيجة: الجاهزية ← طريقة الكتابة ← المحاور والعقود بشريط تقدم ← الملاحظات الحمراء
        ← المعاينة قبل الدمج ← النتيجة («أعد صياغة النتيجة»)."""
        self._contracts_block()
        self._readiness_block()
        self._delivery_block()
        if case_conclusion.is_v2(self.data):
            self._plan_block()
            self._research_notes_block()
            self._preview_block()
            return
        items = [it for it in self.data.get('research') or [] if it['state'] in case_model.OK_STATES
                 or it.get('file')]
        answers = (self.data.get('conclusion') or {}).get('answers') or []
        if not items and not answers:
            self.card_lay.addWidget(_lbl("لم يُكتب بند بعد — «كتابة البحث ورأي الخبرة» للجاهزة، "
                                         "أو «اكتب رغم النقص» للناقص.", 13, rc.GRAY_TEXT))
            return
        entries = [dict(it, _label=f"البحث — {(it.get('point_text') or '')[:70]}"
                        + ('' if it['state'] in case_model.OK_STATES else ' — لم يُكتب')) for it in items]
        entries += [dict(id='C:' + a['id'], _label=f"النتيجة — {(a.get('point_text') or '')[:70]}") for a in answers]
        self._picker(entries, lambda e: e['_label'])
        self._add_editor(self._research_text(items[0]['id']) if items else (answers[0].get('text') or ''))
        extra = [] if answers else [("كتابة النتيجة", lambda: self._rewrite('conclusion'), False)]
        self._std_actions(rewrite=self._rewrite_item, approve=True, extra=extra)

    def _card_conclusion(self):
        answers = (self.data.get('conclusion') or {}).get('answers') or []
        if not answers:
            self.card_lay.addWidget(_lbl("لم تُكتب النتيجة بعد.", 13, rc.GRAY_TEXT))
            self._std_actions(rewrite=lambda: self._rewrite('conclusion'), approve=False)
            return
        self._picker(answers, lambda a: f"النقطة {a['n']}: {(a.get('point_text') or '')[:70]}")
        self._add_editor(answers[0].get('text') or '')
        self._std_actions(rewrite=lambda: self._rewrite('conclusion'), approve=True)

    def _card_attachments(self):
        att = self.data.get('attachments') or []
        if not att:
            self.card_lay.addWidget(_lbl("تتكوّن المرفقات وحدها من المحاضر وحوافظ المستندات.", 13, rc.GRAY_TEXT))
        for a in att:
            if a.get('note'):
                self.card_lay.addWidget(_lbl(f"ℹ {a['title']}", 12, rc.AMBER))
            else:
                self.card_lay.addWidget(_lbl(f"{a['no']}. {a['title']}", 13, rc.INK))
        self._std_actions()

    # ---------- التعديل والحفظ التلقائي ----------
    def _research_text(self, pid):
        it = next((i for i in self.data.get('research') or [] if i['id'] == pid), None)
        if not it or not it.get('file'):
            return ''
        raw, _ = case_memory._read_text(self.base, it['file'])
        return research_pipeline.clean_display(case_memory._dec(raw)) if raw is not None else ''

    def _on_pick(self, _i):
        if self._dirty:
            self.autosave(self._last_pick)
        self._loading = True
        pid = self.picker.currentData()
        if self._open == 'research' and (str(pid).startswith('S:') or pid == 'C2'):
            self.editor.setPlainText(self._v2_text(pid))          # البحث الجديد: قسم أو النتيجة
        elif self._open == 'research' and not str(pid).startswith('C:'):
            self.editor.setPlainText(self._research_text(pid))
        else:
            pid = str(pid)[2:] if str(pid).startswith('C:') else pid
            a = next((a for a in self.data['conclusion'].get('answers') or [] if a['id'] == pid), {})
            self.editor.setPlainText(a.get('text') or '')
        self._loading = False
        self._last_pick = pid

    def _on_edit(self):
        if self._loading:
            return
        self._dirty = True
        if self.picker is not None:
            self._last_pick = self.picker.currentData()
        self.saved.setText("…")
        self._save_timer.start()

    def autosave(self, pid=None):
        """يحفظ نص المحرّر بلا اعتماد، عبر دوال المنطق نفسها."""
        self._save_timer.stop()
        if not self._dirty or self.editor is None:
            return
        self._dirty = False
        key, txt = self._open, self.editor.toPlainText().strip()
        pid = pid or (self.picker.currentData() if self.picker is not None else None)
        try:
            if key == 'subject':
                if txt != (self.data.get('subject') or '').strip():
                    sm.set_subject(self.base, self.data, txt)
            elif key == 'mission':
                pts = [l.strip() for l in txt.splitlines() if l.strip()]
                if pts != [p['text'] for p in self.data['mission'].get('points') or []]:
                    sm.set_mission(self.base, self.data, points=pts)
            elif key == 'procedures':
                case_procedures.set_procedures_text(self.base, self.data, txt)
            elif key == 'research' and pid and str(pid).startswith('S:'):
                research_pipeline.set_section_text(self.base, self.data, str(pid)[2:], txt)
            elif key == 'research' and pid == 'C2':
                conclusion_pipeline.set_text(self.base, self.data, txt)
            elif key == 'research' and pid and str(pid).startswith('C:'):
                self._save_conclusion(str(pid)[2:], txt)
            elif key == 'research' and pid:
                self._save_research(pid, txt)
            elif key == 'conclusion' and pid:
                self._save_conclusion(pid, txt)
        except case_model.StepError as e:
            self.saved.setText("")
            QMessageBox.warning(self, "لم يُحفظ", str(e))
            return
        self.saved.setText("تم الحفظ تلقائياً")
        self.track.set_data(self.data)

    def _save_research(self, pid, txt):
        import hashlib
        it = next(i for i in self.data['research'] if i['id'] == pid)
        rel = it.get('file') or os.path.join(case_research.ITEMS_DIR, f"{it['n']:02d}.md").replace('\\', '/')
        case_documents._write_md(self.base, rel, txt + '\n')
        with open(os.path.join(self.base, rel), 'rb') as f:
            it['sha1'] = hashlib.sha1(f.read()).hexdigest()
        it.update(file=rel, state='done', message='')
        case_research._progress(self.data)
        if case_model.state(self.data, 'research') == 'reviewed':
            case_model.set_step(self.data, 'research', 'done')
        case_research._save(self.base, self.data, 'items')

    def _save_conclusion(self, pid, txt):
        a = next(a for a in self.data['conclusion']['answers'] if a['id'] == pid)
        if a.get('text') == txt:
            return
        a['text'], a['missing'] = txt, False
        if case_model.state(self.data, 'conclusion') == 'reviewed':
            case_model.set_step(self.data, 'conclusion', 'done')
            self.data['conclusion']['state'] = 'done'
        case_conclusion._save(self.base, self.data)

    # ---------- إعادة الكتابة والاعتماد ----------
    def _start_rewrite(self, key, pid=None):
        self.autosave()
        self._notice = None
        self._rewriting = (key, datetime.now().isoformat(timespec='seconds'), pid)

    def _rewrite(self, key):
        """«إعادة الكتابة» تفرض الإعادة ولو كانت الخطوة مكتملة/معتمدة. سبب العطل السابق: كانت تُستدعى بلا force
        فترجع run_subject/run_conclusion فوراً دون أي عمل ودون رسالة."""
        if self._busy:
            return
        import case_rewrite
        rec2 = conclusion_pipeline.record(self.data) if key == 'conclusion' else None
        if rec2 and rec2.get('edited') and QMessageBox.question(
                self, "أعد صياغة النتيجة", "عدّلتَ نص النتيجة بيدك. إعادة الصياغة ستستبدله بنص جديد من البحث. متابعة؟"
        ) != QMessageBox.StandardButton.Yes:
            return
        if case_rewrite.is_manual(self.data, key) and QMessageBox.question(
                self, "إعادة الكتابة", "عدّلتَ هذا النص بيدك. إعادة الكتابة ستستبدله بنص جديد. متابعة؟"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._start_rewrite(key)
        pre = self._pre_rewrite_sync
        if key == 'mission':
            self._run_bg(lambda: (pre(), sm.run_mission(self.base, self.data, force=True)),
                         "جارٍ إعادة قراءة المأمورية من حكم الإحالة…")
        elif key == 'conclusion':
            self.do('conclusion', 'rewrite')
        elif key == 'procedures':                # بالكود من المحاضر وفرزها (لا طلب ذكاء)
            self._run_bg(lambda: (pre(), case_rewrite.rewrite_procedures(self.base, self.data, None)),
                         "جارٍ إعادة كتابة الإجراءات من المحاضر…")
        elif self._stage_mode('stage2') == 'browser':
            self._rewriting = None
            self._browser_write('stage2')
            return
        else:                                    # المرحلة الثانية: الموضوع والإجراءات والمرفقات بطلب واحد
            import case_stage2
            ask = self._ask_for(case_stage2.PURPOSE)
            self._run_bg(lambda: (pre(), case_stage2.run(self.base, self.data, ask, force=True, replace_manual=True)),
                         "جارٍ كتابة الموضوع والإجراءات والمرفقات (طلب واحد)…")
        if not self._busy:                      # رُفض فوراً (StepError ظهر للخبير) ← لا ننتظر نتيجة
            self._rewriting = None

    def _pre_rewrite_sync(self):
        """إن أُضيف مستند جديد للمجلد: إعادة القراءة والمزامنة أولاً (داخل الخيط الخلفي). يرجع True إن زامن."""
        import case_folder
        import case_startup
        if not case_folder.has_pending(self.base):
            return False
        case_startup.run(self.base, self.data, None, ask=self._ask_for('الفرز'), stop=lambda: self._stop)
        case_workspace.write_case_json(self.base, self.data)
        return True

    def _claim_fn(self):
        import case_sources
        import case_subject_telecom
        cookies, autocase = self.cookies, self.data.get('autocase_no') or ''
        if not (cookies or case_sources.has_local(self.base, self.data, 'claim')):
            return None
        return lambda: case_subject_telecom.fetch_claim_text(cookies, autocase, False, self.base, self.data, False)

    def _rewrite_item(self):
        if self._busy:
            return
        pid = self.picker.currentData()
        if str(pid).startswith('C:') or pid == 'C2':
            self._rewrite('conclusion')
            return
        if str(pid).startswith('S:'):                     # البحث الجديد: «إعادة الكتابة» = أعد صياغة محور القسم
            a, _s = research_pipeline.section(self.data, str(pid)[2:])
            if a is not None:
                self._rewrite_axis(a['key'])
            return
        self._start_rewrite('research', pid)
        ask = self._ask_for('إعادة كتابة بند')
        self._run_bg(lambda: case_research.rewrite_item(self.base, self.data, pid, ask=ask),
                     "جارٍ إعادة كتابة البند…")

    def approve_current(self):
        """يعتمد الخطوة المفتوحة. يرجع True إن صارت «راجعها الخبير»."""
        if self._busy:
            return False
        self.autosave()
        key = self._open
        try:
            if key == 'subject':
                if not (self.data.get('subject') or '').strip():
                    raise case_model.StepError("الموضوع فارغ.")
                if case_procedures.TODO in self.data['subject'] and QMessageBox.question(
                        self, "اعتماد الموضوع", f"في الموضوع «{case_procedures.TODO}» لم يُكمل بعد. اعتماد رغم ذلك؟"
                ) != QMessageBox.StandardButton.Yes:
                    return False
                if case_model.state(self.data, 'subject') not in case_model.OK_STATES:
                    sm.set_subject(self.base, self.data, self.data['subject'])
                sm.review_subject(self.base, self.data)
            elif key == 'mission':
                sm.confirm_mission(self.base, self.data)
            elif key == 'procedures':                  # تُعتمد وحدها متى اكتملت؛ هنا فقط نشرح ما ينقص
                st = case_model.state(self.data, 'procedures')
                if st == 'done':
                    case_model.set_step(self.data, 'procedures', 'reviewed', self.data['steps']['procedures']['message'])
                    case_workspace.write_case_json(self.base, self.data)
                elif st != 'reviewed':
                    raise case_model.StepError("لم تكتمل الإجراءات بعد — ينقص: "
                                               + (case_procedures.missing_line(self.data) or 'تشغيل الخطوة'))
            else:
                if case_model.state(self.data, key) == 'reviewed':
                    pass
                elif case_model.state(self.data, key) not in case_model.OK_STATES:
                    raise case_model.StepError("لم تكتمل هذه الخطوة بعد — أكملها أولاً.")
                else:
                    self._review(key)
                if key == 'research' and case_model.state(self.data, 'conclusion') == 'done':
                    self._review('conclusion')          # النتيجة ضمن البحث ← تُعتمد معه
        except case_model.StepError as e:
            QMessageBox.warning(self, "لا يمكن الاعتماد", str(e))
            self.reload()
            return False
        self.saved.setText("تم الحفظ تلقائياً")
        self.reload()
        return True

    def go_next(self):
        """«التالي»: ينتقل دون اعتماد ودون تحذير يمنع (الاعتماد الصريح في البحث والنتيجة فقط)."""
        self.autosave()
        nxt = neighbour(self._open, +1)
        if nxt:
            self.open_step(nxt)
        else:
            self._do_report()

    def approve_and_next(self):
        if self.approve_current():
            nxt = neighbour(self._open, +1)
            if nxt:
                self.open_step(nxt)

    def done(self, r):
        self.autosave()
        super().done(r)
