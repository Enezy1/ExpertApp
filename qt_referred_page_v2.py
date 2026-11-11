# ===== qt_referred_page_v2.py — القضايا المحالة بتصميم «صندوق الوارد» =====
# نفس كلاسات qt_referred_page.py العامة وبنفس التواقيع — بديل مباشر.
# منطق الأعمال (الجلب، التأكيد، submit_action) منسوخ حرفيًا من الأصل؛ الذي تغيّر
# طبقة العرض: كل إحالة مذكرة واردة ببيانات منظّمة (من قسم / من موظف / ملاحظات)،
# فصل الإحالات المباشرة عن الاستعانات، وأيقونات مرسومة بدل الرموز.
import threading
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QMessageBox, QFrame, QSizePolicy, QPushButton
)

import qt_theme as th
import qt_icons as ic
import qt_motion as mo
from qt_widgets import SummaryLine, Card, Badge, PrimaryButton, SecondaryButton, PageHeader, KPICard

from referred_cases import (
    get_referred_cases, submit_action,
    REFERRED_LIST_TYPE, SECONDMENT_LIST_TYPE,
    ACTION_MUBASHARA, ACTION_RETURN, ACTION_RETURN_SECONDMENT,
    claim_summary_initial,
)


# ======================================================================
#  أدوات عرض صغيرة (بلا منطق أعمال)
# ======================================================================

def _disp_date(date_str):
    """عرض فقط: يوحّد التاريخ إلى DD/MM/YYYY لو أمكن، وإلا يرجعه كما هو"""
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime((date_str or '').strip()[:10], fmt).strftime('%d/%m/%Y')
        except ValueError:
            continue
    return date_str


def _pill(text, bg, fg):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:9px; padding:2px 10px;"
                      f" font-size:{th.FS_CAPTION}px; font-weight:{th.W_BOLD}; border:none;")
    lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return lbl


class ElidedLabel(QLabel):
    """سطر واحد يقصّ بـ«…» حسب العرض الفعلي، والنص الكامل بتلميح"""
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._full = (text or '').strip()
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(80)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refit()

    def changeEvent(self, e):
        super().changeEvent(e)
        self._refit()

    def _refit(self):
        shown = QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, self.width()))
        if shown != self.text():
            self.setText(shown)
        self.setToolTip(self._full if shown != self._full else "")


def _fact(caption, value, stretch_wrap=False):
    """حقل بيانات بعنوان صغير — «من قسم» / «من موظف» / «ملاحظات»"""
    box = QFrame()
    box.setObjectName("fact")
    box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    box.setStyleSheet(f"QFrame#fact {{ background:{th.BG}; border:1px solid {th.BORDER_SOFT}; border-radius:10px; }}")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(12, 8, 12, 9)
    lay.setSpacing(2)
    c = QLabel(caption)
    c.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:{th.FS_CAPTION}px; font-weight:{th.W_MEDIUM}; border:none; background:transparent;")
    v = QLabel(value)
    v.setWordWrap(True)
    v.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:{th.FS_BODY}px; border:none; background:transparent;")
    for w in (c, v):
        w.setAlignment(th.ARIGHT)
    lay.addWidget(c)
    lay.addWidget(v)
    return box


def _section_header(title, count):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(4, 14, 4, 4)
    lay.setSpacing(10)
    t = QLabel(title)
    t.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:{th.FS_BODY}px; font-weight:{th.W_BOLD}; border:none;")
    n = _pill(str(count), th.NAVY_TINT, th.NAVY)
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background:{th.BORDER}; border:none;")
    lay.addWidget(t)
    lay.addWidget(n)
    lay.addWidget(line, 1)
    return w



def _state_view(kind, title, sub='', retry_cb=None, detail=None):
    """حالة داخل القائمة (فراغ / لا اتصال / تعذّر التحميل) — أيقونة + عنوان + سطر توضيح
    + زر «إعادة المحاولة» اختياري يستدعي دالة التحميل الموجودة نفسها (لا منطق جديد)"""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 56, 0, 56)
    lay.setSpacing(8)
    icon = QLabel()
    tone = th.DANGER if kind == 'alert' else th.TEXT_MUTED
    icon.setPixmap(ic.pixmap(kind, tone, 36))
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    t = QLabel(title)
    t.setAlignment(Qt.AlignmentFlag.AlignCenter)
    t.setStyleSheet(f"color:{th.TEXT_PRIMARY if retry_cb else th.TEXT_SECONDARY}; font-size:{th.FS_TITLE}px;"
                    f" font-weight:{th.W_BOLD if retry_cb else th.W_MEDIUM}; border:none;")
    lay.addWidget(icon)
    lay.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setWordWrap(True)
        s.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:{th.FS_LABEL}px; border:none;")
        lay.addWidget(s)
    if detail:
        # النص التقني مخفي خلف «عرض التفاصيل» — قابل للتحديد والنسخ لمن يحتاجه
        d = QLabel(th.ltr(detail))
        d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d.setWordWrap(True)
        d.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        d.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:{th.FS_CAPTION}px; border:none;")
        d.hide()
        toggle = QPushButton("عرض التفاصيل")
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle.setStyleSheet(f"QPushButton {{ background:transparent; border:none; color:{th.NAVY};"
                             f" font-size:{th.FS_CAPTION}px; font-weight:{th.W_MEDIUM}; text-decoration:underline; }}")
        def _flip():
            d.setVisible(not d.isVisible())
            toggle.setText("إخفاء التفاصيل" if d.isVisible() else "عرض التفاصيل")
        toggle.clicked.connect(_flip)
        trow = QHBoxLayout()
        trow.addStretch()
        trow.addWidget(toggle)
        trow.addStretch()
        lay.addLayout(trow)
        lay.addWidget(d)
    if retry_cb:
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        btn = PrimaryButton("إعادة المحاولة")
        btn.setIcon(ic.icon('refresh', 'white'))
        btn.clicked.connect(retry_cb)
        row.addStretch()
        row.addWidget(btn)
        row.addStretch()
        lay.addLayout(row)
    return w


def _kpi_tone(kpi, color, text=None):
    """عرض فقط: يلوّن قيمة خانة رقم (ويغيّر نصها اختياريًا) بنفس خط KPICard"""
    if text is not None:
        kpi.value_label.setText(text)
    kpi.value_label.setStyleSheet(f"color:{color}; font-size:{th.FS_DISPLAY}px; font-weight:{th.W_BOLD}; border:none;")


def _is_network_error(e):
    """عرض فقط: هل الخطأ انقطاع/مهلة شبكة؟ (لاختيار نص الحالة المناسب)"""
    import requests
    return isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


def _short(text, n=160):
    text = " ".join(str(text or '').split())
    return text if len(text) <= n else text[:n - 1] + "…"


# ---- التكيّف مع الشاشة (عرض فقط) ----
CONTENT_MAX_W = 1180      # عمود المحتوى لا يتجاوز هذا العرض — يتوسّط الشاشات العريضة
COMPACT_BELOW_H = 760     # تحت هذا الارتفاع: حشوات أصغر حتى تبقى للقائمة مساحة


def _fit_page(page, extra=None):
    """يضبط هوامش الصفحة: عمود متوسّط على الشاشات العريضة، ووضع مضغوط على القصيرة"""
    root = page.layout()
    if root is None:
        return
    compact = page.height() < COMPACT_BELOW_H
    side = max(34, (page.width() - CONTENT_MAX_W) // 2)
    v = 16 if compact else 26
    root.setContentsMargins(side, v, side, v)
    root.setSpacing(12 if compact else 18)
    for kpi in page.findChildren(KPICard):
        lay = kpi.layout()
        if lay is not None:
            lay.setContentsMargins(18, 10 if compact else 16, 18, 10 if compact else 16)
    if extra:
        extra(compact)


def _empty_state(kind, title, sub=''):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 56, 0, 56)
    lay.setSpacing(8)
    icon = QLabel()
    icon.setPixmap(ic.pixmap(kind, th.TEXT_MUTED, 36))
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    t = QLabel(title)
    t.setAlignment(Qt.AlignmentFlag.AlignCenter)
    t.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:{th.FS_TITLE}px; font-weight:{th.W_MEDIUM}; border:none;")
    lay.addWidget(icon)
    lay.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:{th.FS_LABEL}px; border:none;")
        lay.addWidget(s)
    return w


def _summary_state(case):
    """حالة سطر الملخص بدون ما تسقط البطاقة: قضايا قديمة بالقاعدة المحلية فيها
    case_summary = NULL (أُضيف العمود بعد إنشائها) فـclaim_summary_initial يرمي
    AttributeError ← البطاقة ما تنبني ← الصفحة تطلع فاضية بينما الأرقام تظهر."""
    try:
        return claim_summary_initial(case)
    except Exception:
        return ('load', None) if (case.get('autocase_no') or '') else ('skip', None)


class ReferredCaseCard(Card):
    """مذكرة واردة: المدعى + الشارات + تاريخ الورود، ثم حقول المحيل، ثم مباشرة/إعادة"""
    # ملخص الدعوى يصل من خيط خلفي — النص الفاضي يعني إخفاء السطر
    _summary_ready = pyqtSignal(str)

    def __init__(self, case, cookies, on_done=None, parent=None):
        super().__init__(parent=parent)
        self.case = case
        self.cookies = cookies
        self.on_done = on_done
        is_secondment = case.get('is_secondment', False)

        if is_secondment:
            self.setStyleSheet(th.card_style(bg=th.SECONDMENT_BG, border=th.BORDER))

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        title_lbl = ElidedLabel(case['plaintiff'] or case['caso_no'])
        title_lbl.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:{th.FS_TITLE}px; font-weight:{th.W_MEDIUM}; border:none; background:transparent;")
        title_lbl.setAlignment(th.ARIGHT)
        top.addWidget(title_lbl, 1)
        if is_secondment:
            top.addWidget(_pill("استعانة", th.SURFACE, th.SECONDMENT_TEXT))
        root.addLayout(top)

        meta_txt = f"رقم الخبرة {th.ltr(case['caso_no'])}"
        if case['date']:
            meta_txt += f"   ·   ورد في {th.ltr(_disp_date(case['date']))}"
        meta = QLabel(meta_txt)
        meta.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:{th.FS_LABEL}px; border:none; background:transparent;")
        meta.setAlignment(th.ARIGHT)
        root.addWidget(meta)

        facts = []
        if case['from_dept']:
            facts.append(("من قسم", case['from_dept']))
        if case['from_emp']:
            facts.append(("من الخبير", case['from_emp']))
        if case['notes']:
            facts.append(("ملاحظات", case['notes']))
        if facts:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(0, 4, 0, 0)
            for cap, val in facts:
                row.addWidget(_fact(cap, val), 2 if cap == "ملاحظات" else 1)
            root.addLayout(row)

        # سطر ملخص الدعوى (ميزة إضافية): بنفس ستايل سطر «رقم الخبرة» الثانوي.
        # الأزرار تُبنى بعده وتبقى فعّالة فوراً بغض النظر عن حالة الملخص.
        self._summary_lbl = None
        state, text = _summary_state(case)
        if state != 'skip':
            self._summary_lbl = SummaryLine(text)
            root.addWidget(self._summary_lbl)
            if state == 'load':
                self._summary_ready.connect(self._apply_summary)
                import summary_queue           # طابور خلفي واحد (لا خيط ولا طلب لكل صف — summary_queue)
                if not summary_queue.enqueue(case, self.cookies, self._emit_summary):
                    self._apply_summary(text or '')

        return_action = ACTION_RETURN_SECONDMENT if is_secondment else ACTION_RETURN
        return_label = "إعادة استعانة لرئيس القسم" if is_secondment else "إعادة لرئيس القسم"

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 6, 0, 0)
        accept_btn = PrimaryButton("مباشرة (استلام)")
        accept_btn.setIcon(ic.icon('check', 'white'))
        accept_btn.clicked.connect(lambda: self._confirm_and_submit(ACTION_MUBASHARA, "مباشرة"))
        return_btn = SecondaryButton(return_label)
        return_btn.setIcon(ic.icon('return', th.DANGER))
        return_btn.setStyleSheet(th.secondary_button_style() + f"""
            QPushButton {{ color:{th.DANGER}; border-color:{th.DANGER}; }}
            QPushButton:hover {{ background:{th.DANGER_BG}; color:{th.DANGER_TEXT}; border-color:{th.DANGER}; }}
        """)
        return_btn.clicked.connect(lambda: self._confirm_and_submit(return_action, return_label))

        bottom.addWidget(accept_btn)
        bottom.addWidget(return_btn)
        bottom.addStretch()
        root.addLayout(bottom)

    def _emit_summary(self, summary):
        """من خيط الطابور: الإشارة تنقل الملخص لخيط الواجهة."""
        try:
            self._summary_ready.emit(summary or '')
        except RuntimeError:
            pass  # البطاقة أُتلفت (أُعيد رسم القائمة) قبل انتهاء الطابور

    def _apply_summary(self, summary):
        if not self._summary_lbl:
            return
        if summary:
            self._summary_lbl.set_summary(summary)
        else:
            self._summary_lbl.hide()   # فشل/لا صحيفة — يختفي بصمت

    def _confirm_and_submit(self, action_type, action_label):
        msg = (
            f"سيتم تنفيذ الإجراء التالي على نظام الخبراء:\n\n"
            f"القضية: {self.case['caso_no']}\n"
            f"المدعى: {self.case['plaintiff'] or '—'}\n"
            f"الإجراء: {action_label}\n\n"
        )
        if action_type in (ACTION_RETURN, ACTION_RETURN_SECONDMENT):
            msg += "⚠️ الإعادة ترفض استلام القضية وترجعها لرئيس القسم.\n\n"
        msg += "هل تريد المتابعة؟"

        reply = QMessageBox.question(
            self.window(), "تأكيد الإجراء", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            ok, message = submit_action(self.cookies, [self.case['task_id']], action_type)
        except Exception as e:
            ok, message = False, str(e)

        if ok:
            QMessageBox.information(self.window(), "✅ تم",
                f"تمت {action_label} للقضية {self.case['caso_no']} بنجاح")
            if self.on_done:
                self.on_done()
        else:
            QMessageBox.critical(self.window(), "❌ فشل",
                f"تعذّر تنفيذ الإجراء:\n\n{th.ltr(message)}")


class ReferredCasesPage(QWidget):
    countChanged = pyqtSignal(int)   # عدد القضايا المحالة الحالي (للشارة بالشريط الجانبي)
    # نتيجة الجلب تعود من الخيط الخلفي (حمولة واحدة dict)
    _data_ready = pyqtSignal(object)
    _data_failed = pyqtSignal(object)

    def __init__(self, cookies, current_user, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.cookies = cookies
        self.current_user = current_user
        # '_loading' يمنع تضاعف الخيوط، و'_load_token' يبطل نتيجة جلب قديمة
        self._loading = False
        self._load_token = 0
        self._data_ready.connect(self._apply_data)
        self._data_failed.connect(self._apply_error)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 26, 34, 26)
        root.setSpacing(18)

        header_row = QHBoxLayout()
        self.header = PageHeader(
            "القضايا المحالة",
            "القضايا التي أحالها رئيس القسم — اختر مباشرة للاستلام أو إعادة للرفض",
        )
        refresh_btn = SecondaryButton("تحديث")
        refresh_btn.setIcon(ic.icon('refresh', th.TEXT_SECONDARY, th.NAVY))
        refresh_btn.clicked.connect(self._refresh_clicked)
        header_row.addWidget(self.header)
        header_row.addStretch()
        header_row.addWidget(refresh_btn)
        root.addLayout(header_row)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(14)
        self.kpi_total = KPICard("إجمالي القضايا المحالة", "0")
        self.kpi_secondment = KPICard("قضايا استعانة", "0", value_color=th.SECONDMENT_TEXT)
        kpi_row.addWidget(self.kpi_total)
        kpi_row.addWidget(self.kpi_secondment)
        root.addLayout(kpi_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(2, 2, 2, 2)
        self.scroll_layout.setSpacing(10)
        self.scroll_layout.addStretch()
        self.scroll.setWidget(self.scroll_content)
        root.addWidget(self.scroll, 1)

        self._loaded = False
        if not self.cookies:
            self._show_no_login()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        _fit_page(self)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._loaded and self.cookies:
            self._loaded = True
            self._show_loading()
            QTimer.singleShot(30, self.load_cases)

    def _clear_scroll(self):
        while self.scroll_layout.count() > 1:
            item = self.scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _refresh_clicked(self):
        self._show_loading()
        QTimer.singleShot(30, self.load_cases)

    def _show_loading(self):
        self._clear_scroll()
        insert_at = self.scroll_layout.count() - 1
        self.scroll_layout.insertWidget(insert_at, _empty_state('clock', "جاري تحميل القضايا المحالة..."))

    def load_cases(self):
        """يبدأ الجلب في خيط خلفي.

        السبب: الجلب طلبان شبكيان (قائمة عادية + قائمة استعانة) كل واحد
        بمهلة 15 ثانية، وكانوا ينفَّذان على خيط الواجهة — فالنافذة تتجمد
        كاملة وقت الفتح. الخيوط ترجع النتيجة عبر إشارة، والعرض (العدّادات
        والقوائم) يبقى على خيط الواجهة لأن Qt ما يسمح بلمس الـwidgets من
        خيط ثاني.
        """
        if not self.cookies:
            return
        if self._loading:
            return  # جلب جارٍ — ما نشغّل خيط ثاني (عند التحديث أثناء الجلب)
        self._loading = True
        self._load_token += 1
        token = self._load_token
        cookies = self.cookies
        # نثبّت مراجع الدوال الآن (وقت بدء الخيط) حتى لا يتغيّر السلوك
        _get_referred = get_referred_cases
        _normal_type, _secondment_type = REFERRED_LIST_TYPE, SECONDMENT_LIST_TYPE

        def work():
            try:
                cases = _get_referred(cookies, _normal_type)
                secondment_cases = _get_referred(cookies, _secondment_type)
            except Exception as e:
                self._emit_from_worker(self._data_failed, {'token': token, 'error': e})
                return
            self._emit_from_worker(self._data_ready, {
                'token': token,
                'cases': cases + secondment_cases,
                'secondment_count': len(secondment_cases),
            })

        threading.Thread(target=work, daemon=True).start()

    def _emit_from_worker(self, signal, payload):
        """إرسال النتيجة من الخيط الخلفي بأمان — لو الصفحة انحذفت ما يكسر شي"""
        try:
            from PyQt6 import sip
            from PyQt6.QtWidgets import QApplication
            if sip.isdeleted(self) or QApplication.instance() is None:
                return
            signal.emit(payload)
        except RuntimeError:
            pass

    def _apply_data(self, payload):
        """يُستدعى على خيط الواجهة (عن طريق الإشارة) — هنا فقط نلمس الـwidgets"""
        if payload.get('token') != self._load_token:
            return  # نتيجة جلب أقدم من جلب أحدث — نتجاهلها
        self._loading = False
        cases = payload['cases']
        self.countChanged.emit(len(cases))
        self.kpi_total.value_label.setText(str(len(cases)))
        self.kpi_secondment.value_label.setText(str(payload['secondment_count']))
        self._render_cases(cases)

    def _apply_error(self, payload):
        """الخطأ يوصلنا على خيط الواجهة — نفس معالجة الخطأ السابقة"""
        if payload.get('token') != self._load_token:
            return
        self._loading = False
        self._show_error(payload['error'])


    # ---- عرض فقط: حالات الخطأ داخل القائمة بدل النافذة المنبثقة ----
    def _show_error(self, e):
        self._clear_scroll()
        self._after_clear()
        self._unknown_figures()
        if _is_network_error(e):
            view = _state_view('offline', "لا يوجد اتصال بنظام الخبراء",
                               "تأكّد من الاتصال بشبكة الدوام ثم أعد المحاولة", retry_cb=self._refresh_clicked)
        else:
            view = _state_view('alert', "تعذّر تحميل القضايا المحالة", "حدث خطأ غير متوقع أثناء قراءة البيانات",
                               retry_cb=self._refresh_clicked, detail=_short(e))
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, view)

    def _show_no_login(self):
        self._clear_scroll()
        self._after_clear()
        self._unknown_figures()
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, _state_view(
            'offline', "لا يوجد اتصال بنظام الخبراء", "سجّل الدخول من جديد لعرض القضايا المحالة"))

    def _after_clear(self):
        pass

    def _unknown_figures(self):
        """عرض فقط: لا أرقام كاذبة — «—» محايد بدل «0» حين لا توجد بيانات"""
        for k in [w for w in self.findChildren(KPICard)]:
            _kpi_tone(k, th.TEXT_SECONDARY, "—")
        if hasattr(self, "_chips"):
            self._sync_chips(None)

    def _stamp_then_reload(self, card):
        """عرض فقط: ختم «تم» يُطبع على المذكرة (320ms)، ثم نفس التحديث الأصلي load_cases"""
        try:
            from qt_sessions_page import SealStamp
            seal = SealStamp(card)
            seal.move(max(0, int(card.width() * 0.40) - seal.width() // 2), max(0, (card.height() - seal.height()) // 2))
            seal.show()
            seal.raise_()
            seal.stamp()
        except Exception:
            pass
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(self.load_cases)
        t.start(700 if mo.motion_enabled() else 250)

    # ---- عرض فقط: فصل الإحالات المباشرة عن الاستعانات (نفس القائمة المجلوبة) ----
    def _render_cases(self, cases):
        _kpi_tone(self.kpi_total, th.TEXT_PRIMARY)
        _kpi_tone(self.kpi_secondment, th.SECONDMENT_TEXT if self.kpi_secondment.value_label.text() not in ("0", "—") else th.TEXT_SECONDARY)
        self._clear_scroll()
        insert_at = self.scroll_layout.count() - 1
        if not cases:
            self.scroll_layout.insertWidget(insert_at, _empty_state('inbox', "لا توجد قضايا محالة حالياً"))
            return
        direct = [c for c in cases if not c.get('is_secondment', False)]
        second = [c for c in cases if c.get('is_secondment', False)]
        for title, group in (("إحالات مباشرة", direct), ("استعانات", second)):
            if not group:
                continue
            self.scroll_layout.insertWidget(insert_at, _section_header(title, len(group)))
            insert_at += 1
            for case in group:
                card = ReferredCaseCard(case, self.cookies, on_done=self.load_cases)
                # on_done لا تُستدعى إلا بعد نجاح الإجراء (داخل _confirm_and_submit كما هي) —
                # نمرّر بدلها ختمًا على المذكرة نفسها ثم نفس التحديث load_cases
                card.on_done = (lambda w=card: self._stamp_then_reload(w))
                mo.hover_edge(card, th.RAIL_LINE)
                self.scroll_layout.insertWidget(insert_at, card)
                insert_at += 1

        quick = False
        self._quick_render = False
        mo.stagger([self.scroll_layout.itemAt(i).widget() for i in range(self.scroll_layout.count() - 1)],
                   step=18 if quick else 25, duration=140 if quick else 200)
