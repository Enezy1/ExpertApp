# ===== qt_pending_page_v2.py — القضايا المتداولة بتصميم «خزانة الملفات» =====
# نفس كلاسات qt_pending_page.py العامة وبنفس التواقيع — بديل مباشر.
# منطق الأعمال (الجلب، المزامنة، الإحصائية، فتح التفاصيل/المحضر) منسوخ حرفيًا من الأصل؛
# الذي تغيّر طبقة العرض: المحجوزة أولًا بالأقرب موعدًا مع «مسطرة المهلة»، فلترة عرض فقط،
# شارات صريحة (محجوزة/استعانة)، وأيقونات مرسومة بدل الإيموجي.
import os
import threading
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QBrush, QFontMetrics
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QMessageBox, QProgressBar,
    QDialog, QFormLayout, QApplication, QCheckBox, QFrame, QPushButton, QSizePolicy
)

import qt_theme as th
import qt_icons as ic
import qt_motion as mo
from qt_widgets import SummaryLine, Card, Badge, PrimaryButton, SecondaryButton, PageHeader, KPICard, SmartDateEdit

import case_db
from referred_cases import claim_summary_initial
import case_stats
from pending_cases import (
    get_pending_cases, get_reserved_cases, sync_case_statuses,
    ensure_case_type_and_committee,
)


# ======================================================================
#  أدوات عرض صغيرة (بلا منطق أعمال)
# ======================================================================

def _disp_date(date_str):
    """عرض فقط: YYYY-MM-DD أو YYYY/MM/DD → DD/MM/YYYY، ويرجع النص كما هو لو تعذّر"""
    for fmt in ('%Y-%m-%d', '%Y/%m/%d'):
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


def _remaining_days(reserved_info):
    """عرض فقط: الأيام المتبقية من مهلة الـ21 يومًا (نفس حساب البطاقة الأصلية)"""
    if not reserved_info:
        return None
    rd = reserved_info.get('reserved_date', '')
    try:
        return (datetime.strptime(rd, '%Y-%m-%d').date() + timedelta(days=21) - datetime.now().date()).days
    except Exception:
        return None


class _DeadlineRuler(QWidget):
    """مسطرة المهلة: 21 علامة بعدد أيام المهلة، يمتلئ منها ما مضى (من اليمين — RTL)"""
    def __init__(self, remaining_days, color, parent=None):
        super().__init__(parent)
        self.elapsed = 21 if remaining_days < 0 else max(0, min(21, 21 - remaining_days))
        self.color = color
        self.setFixedSize(21 * 6 + 2, 12)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        x = self.width() - 2
        for i in range(21):
            filled = i < self.elapsed
            h = 11 if (i + 1) % 7 == 0 else 7          # علامة أطول كل أسبوع
            p.setBrush(QBrush(QColor(self.color if filled else th.RULER_TRACK)))
            p.drawRoundedRect(QRectF(x - 1.1, (self.height() - h) / 2, 2.2, h), 1.1, 1.1)
            x -= 6
        p.end()


class _FilterChip(QPushButton):
    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {th.TEXT_SECONDARY};
                border: 1px solid {th.BORDER}; border-radius: 15px;
                padding: 6px 16px; min-height: 18px; font-size: {th.FS_LABEL}px; font-weight: {th.W_MEDIUM};
            }}
            QPushButton:hover {{ border-color: {th.NAVY}; color: {th.NAVY}; }}
            QPushButton:checked {{
                background: transparent; color: white; border-color: transparent; font-weight: {th.W_BOLD};
            }}
        """)


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



def _days_phrase(n):
    """جمع عربي صحيح للأيام"""
    if n == 1:
        return "يوم واحد"
    if n == 2:
        return "يومان"
    if 3 <= n <= 10:
        return f"{n} أيام"
    return f"{n} يومًا"


def _by_days_phrase(n):
    if n == 1:
        return "بيوم واحد"
    if n == 2:
        return "بيومين"
    if 3 <= n <= 10:
        return f"بـ {n} أيام"
    return f"بـ {n} يومًا"


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


class ReferredStatsDialog(QDialog):
    """نافذة الإحصائية: تحدد فترة، وتولّد كشف واحد قابل للطباعة فيه
    القضايا المحالة والمنجزة، وفي الآخر القضايا المستبعدة (المعاد
    توزيعها) بأطرافها — بالاعتماد على سجل الحركة الفعلي لكل قضية
    (case_stats.py)، مو بس القضايا المتداولة حالياً."""
    def __init__(self, parent, cookies, current_user):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("الإحصائية")
        self.setFixedWidth(420)
        self.cookies = cookies
        self.current_user = current_user
        self.setStyleSheet(f"QDialog {{ background:{th.BG}; }}")   # محصور في النافذة — لا يسري على التلميحات

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        title = QLabel("الإحصائية")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:15px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        root.addWidget(title)

        note = QLabel(
            "يبني كشف واحد قابل للطباعة: القضايا المحالة، والمنجزة ضمنها، "
            "وفي النهاية القضايا المستبعدة (اللي أُعيد توزيعها لخبير ثاني) "
            "مع أطرافها — بالاعتماد على سجل الحركة الفعلي لكل قضية."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        note.setAlignment(th.ARIGHT)
        root.addWidget(note)

        form = QFormLayout()
        form.setLabelAlignment(th.ARIGHT)
        form.setSpacing(10)

        year_start = datetime.now().replace(month=1, day=1).strftime("%d/%m/%Y")
        today = datetime.now().strftime("%d/%m/%Y")
        self.date_from = SmartDateEdit(initial=year_start)
        self.date_to = SmartDateEdit(initial=today)
        form.addRow("من تاريخ", self.date_from)
        form.addRow("إلى تاريخ", self.date_to)
        root.addLayout(form)

        self.refresh_chk = QCheckBox("تحديث كل القضايا (حتى المفحوصة سابقاً)")
        self.refresh_chk.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:11px; border:none;")
        self.refresh_chk.setToolTip(
            "فعّلها فقط لو تشك إن نتيجة قضية معينة غلط — إعادة فحص الكل "
            "أبطأ (طلب شبكة منفصل لكل قضية)."
        )
        root.addWidget(self.refresh_chk)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        self.status_lbl.setAlignment(th.ARIGHT)
        self.status_lbl.setWordWrap(True)
        root.addWidget(self.status_lbl)

        btns = QHBoxLayout()
        cancel = SecondaryButton("إلغاء")
        cancel.clicked.connect(self.reject)
        self.gen_btn = PrimaryButton("توليد وطباعة")
        self.gen_btn.setIcon(ic.icon('print', 'white'))
        self.gen_btn.clicked.connect(self._generate)
        btns.addWidget(self.gen_btn)
        btns.addStretch()
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _on_progress(self, idx, total, caso_no):
        self.status_lbl.setText(f"جاري فحص القضايا... {idx}/{total} ({caso_no})")
        QApplication.processEvents()

    def _generate(self):
        try:
            df_raw = self.date_from.get_value()
            dt_raw = self.date_to.get_value()
            date_from = datetime.strptime(df_raw, "%Y/%m/%d")
            date_to = datetime.strptime(dt_raw, "%Y/%m/%d")
        except Exception:
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال تاريخين صحيحين")
            return
        if date_from > date_to:
            QMessageBox.warning(self, "تنبيه", "تاريخ البداية بعد تاريخ النهاية")
            return

        self.gen_btn.setEnabled(False)
        force_refresh = self.refresh_chk.isChecked()
        scan_errors = []

        try:
            self.status_lbl.setText("جاري جمع القضايا المرشّحة...")
            QApplication.processEvents()

            case_stats.run_full_scan(
                self.cookies, self.current_user,
                date_from=date_from, date_to=date_to,
                force_refresh=force_refresh,
                progress_cb=self._on_progress,
                # أخطاء الفحص ما تختفي: نجمعها وننبّه المستخدم بعد التوليد
                error_cb=lambda caso, err: scan_errors.append((caso, str(err))),
            )

            self.status_lbl.setText("جاري تجهيز التقرير...")
            QApplication.processEvents()

            referred, completed, excluded = case_stats.build_report_data(
                date_from, date_to, cookies=self.cookies, current_user=self.current_user
            )
            path = case_stats.build_full_stats_report_html(
                referred, completed, excluded, date_from, date_to, self.current_user
            )
        except Exception as e:
            self.gen_btn.setEnabled(True)
            self.status_lbl.setText("")
            QMessageBox.critical(self, "خطأ", f"تعذّر توليد التقرير:\n{th.ltr(e)}")
            return

        self.gen_btn.setEnabled(True)
        os.startfile(path)
        self.accept()
        # تنبيه بعد التوليد: كم قضية ما فُحصت (الفشل ما يختفي بصمت)
        if scan_errors:
            preview = "\n".join(f"• {caso} — {th.ltr(err)}" for caso, err in scan_errors[:8])
            more = f"\n… و{len(scan_errors) - 8} قضية أخرى" if len(scan_errors) > 8 else ""
            QMessageBox.warning(
                self, "تنبيه",
                f"تعذّر فحص {len(scan_errors)} قضية — قد تكون الأرقام ناقصة:\n\n"
                f"{preview}{more}")


class DeadlineIndicator(QWidget):
    """مسطرة المهلة (21 يومًا) + نص الأيام المتبقية بألوان قاعدة الإشارات الثلاث"""
    def __init__(self, remaining_days, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        # عرض فقط: آخر موعد = اليوم + الأيام المتبقية (نفس حساب البطاقة)
        due = datetime.now().date() + timedelta(days=remaining_days)
        days_ar = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
        when = f"{days_ar[due.weekday()]} {th.ltr(due.strftime('%d/%m'))}"

        # المسطرة بالألوان الزاهية، والنص بالدرجة الداكنة من نفس الإشارة (تباين ≥ 6:1)
        if remaining_days < 0:
            color, tone, text = th.DANGER, th.DANGER_TEXT, f"تجاوز الموعد {_by_days_phrase(abs(remaining_days))} · كان {when}"
        elif remaining_days == 0:
            color, tone, text = th.DANGER, th.DANGER_TEXT, f"الموعد اليوم · {when}"
        elif remaining_days <= 3:
            color, tone, text = th.DANGER, th.DANGER_TEXT, f"متبقي {_days_phrase(remaining_days)} · حتى {when}"
        elif remaining_days <= 7:
            color, tone, text = th.AMBER, th.AMBER_TEXT, f"متبقي {_days_phrase(remaining_days)} · حتى {when}"
        else:
            color, tone, text = th.EMERALD, th.EMERALD_TEXT, f"متبقي {_days_phrase(remaining_days)} · حتى {when}"

        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{tone}; font-size:{th.FS_CAPTION}px; font-weight:{th.W_BOLD}; border:none; background:transparent;")
        lbl.setAlignment(th.ARIGHT)

        lay.addWidget(lbl)
        lay.addWidget(_DeadlineRuler(remaining_days, color))
        self.setToolTip("كل علامة يوم من مهلة الـ21 يومًا، والعلامة الطويلة نهاية أسبوع")


class PendingCaseCard(Card):
    """ملف قضية: العنوان والشارات، ثم رقم الخبرة وتاريخ المباشرة، ثم المهلة والإجراءات"""
    # ملخص الدعوى يصل من خيط خلفي — النص الفاضي يعني إخفاء السطر
    _summary_ready = pyqtSignal(str)

    def __init__(self, case, cookies, current_user, reserved_info=None, parent=None):
        super().__init__(parent=parent)
        self.case = case
        self.cookies = cookies
        self.current_user = current_user
        self.reserved_info = reserved_info
        is_reserved = reserved_info is not None

        case_type = ''
        try:
            cached = case_db.get_case(case['caso_no'])
            if cached:
                case_type = cached.get('case_type', '')
        except Exception:
            pass

        if is_reserved:
            self.setStyleSheet(th.card_style(bg=th.BLUE_INFO_BG, border=th.INFO_BORDER))
        elif case_type == 'استعانة':
            self.setStyleSheet(th.card_style(bg=th.SECONDMENT_BG, border=th.BORDER))

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        title_lbl = ElidedLabel(case['title'] or case['caso_no'])
        title_lbl.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:{th.FS_TITLE}px; font-weight:{th.W_MEDIUM}; border:none; background:transparent;")
        title_lbl.setAlignment(th.ARIGHT)
        top.addWidget(title_lbl, 1)
        if is_reserved:
            top.addWidget(_pill("محجوزة", th.SURFACE, th.BLUE_INFO_TEXT))
        if case_type == 'استعانة':
            top.addWidget(_pill("استعانة", th.SURFACE if is_reserved else th.SURFACE, th.SECONDMENT_TEXT))
        root.addLayout(top)

        meta = QLabel(f"رقم الخبرة {th.ltr(case['caso_no'])}   ·   تاريخ المباشرة {th.ltr(_disp_date(case['received_date']))}")
        meta.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:{th.FS_LABEL}px; border:none; background:transparent;")
        meta.setAlignment(th.ARIGHT)
        root.addWidget(meta)

        # سطر ملخص الدعوى — نفس سطر صفحة القضايا المحالة (ستايل ثانوي، يُحمَّل بالخلفية)
        self._summary_lbl = None
        state, text = claim_summary_initial(case)
        if state != 'skip':
            self._summary_lbl = SummaryLine(text)
            root.addWidget(self._summary_lbl)
            if state == 'load':
                self._summary_ready.connect(self._apply_summary)
                import summary_queue           # طابور خلفي واحد (لا خيط ولا طلب لكل صف — summary_queue)
                if not summary_queue.enqueue(case, self.cookies, self._emit_summary):
                    self._apply_summary(text or '')

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 6, 0, 0)
        btn = PrimaryButton("محضر أول جلسة")
        btn.clicked.connect(self._open_first_session)
        info_btn = SecondaryButton("تفاصيل القضية")
        info_btn.clicked.connect(self._open_case_info)

        if is_reserved:
            remaining_days = _remaining_days(reserved_info)
            if remaining_days is not None:
                bottom.addWidget(DeadlineIndicator(remaining_days))
            else:
                bottom.addWidget(Badge("محجوزة ولم تُنجز", th.BLUE_INFO_BG, th.BLUE_INFO_TEXT))

        bottom.addStretch()
        bottom.addWidget(info_btn)
        bottom.addWidget(btn)
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

    def _open_case_info(self):
        from qt_case_info import open_case_info_window_qt
        try:
            open_case_info_window_qt(self.window(), self.cookies, self.current_user, self.case)
        except Exception as e:
            QMessageBox.critical(self.window(), "خطأ", f"تعذر فتح شاشة تفاصيل القضية:\n{th.ltr(e)}")

    def _open_first_session(self):
        from qt_first_session import print_first_session_qt
        try:
            print_first_session_qt(self.window(), self.case, self.cookies, self.current_user)
        except Exception as e:
            QMessageBox.critical(self.window(), "خطأ", f"تعذر فتح محضر أول جلسة:\n{th.ltr(e)}")


class PendingCasesPage(QWidget):
    # نتيجة الجلب تعود من الخيط الخلفي — حمولة واحدة (dict) بدل إشارات متفرقة
    _data_ready = pyqtSignal(object)
    _data_failed = pyqtSignal(object)

    def __init__(self, cookies, current_user, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.cookies = cookies
        self.current_user = current_user
        # حالة الجلب: '_loading' يمنع تضاعف الخيوط (ضغطة تحديث أثناء جلب جارٍ
        # ما تبدأ طلبات ثانية)، و'_load_token' يبطل نتيجة جلب قديمة لو وصل
        # تحديث أحدث قبلها.
        self._loading = False
        self._load_token = 0
        self._data_ready.connect(self._apply_data)
        self._data_failed.connect(self._apply_error)
        self._build()

    def _build(self):
        self._cases = []
        self._reserved_map = {}
        self._filter = 'all'

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 26, 34, 26)
        root.setSpacing(18)

        header_row = QHBoxLayout()
        self.header = PageHeader("القضايا المتداولة", "القضايا المحجوزة ولم تُنجز مميّزة بلون هادئ")
        stats_btn = SecondaryButton("الإحصائية")
        stats_btn.setIcon(ic.icon('chart', th.TEXT_SECONDARY, th.NAVY))
        stats_btn.clicked.connect(self._open_stats)
        refresh_btn = SecondaryButton("تحديث")
        refresh_btn.setIcon(ic.icon('refresh', th.TEXT_SECONDARY, th.NAVY))
        refresh_btn.setToolTip("تحديث (F5)")
        refresh_btn.clicked.connect(self._refresh_clicked)
        self.refresh_btn = refresh_btn  # نقدر نعطّله أثناء الجلب
        header_row.addWidget(self.header)
        header_row.addStretch()
        header_row.addWidget(stats_btn)
        header_row.addWidget(refresh_btn)
        root.addLayout(header_row)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(14)
        self.kpi_total = KPICard("إجمالي القضايا المتداولة", "0")
        self.kpi_reserved = KPICard("محجوزة ولم تُنجز", "0", value_color=th.BLUE_INFO_TEXT)
        self.kpi_secondment = KPICard("قضايا استعانة", "0", value_color=th.SECONDMENT_TEXT)
        kpi_row.addWidget(self.kpi_total)
        kpi_row.addWidget(self.kpi_reserved)
        kpi_row.addWidget(self.kpi_secondment)
        root.addLayout(kpi_row)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        self._chips = {}
        for key in ('all', 'reserved', 'secondment'):
            c = _FilterChip(key)
            c.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            chips.addWidget(c)
            self._chips[key] = c
        chips.addStretch()
        root.addLayout(chips)
        # خلفية كحلية واحدة تنزلق إلى الفلتر المختار (نفس لغة الختم المنزلق بالشريط الجانبي)
        self._chip_pill = QFrame(self)
        self._chip_pill.setStyleSheet(f"background:{th.NAVY}; border-radius:15px; border:none;")
        self._chip_pill.lower()
        self._chip_pill.hide()
        self._sync_chips({'all': 0, 'reserved': 0, 'secondment': 0})

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
        QTimer.singleShot(0, lambda: self._place_chip_pill(animate=False))

    def showEvent(self, e):
        super().showEvent(e)
        if not self._loaded and self.cookies:
            self._loaded = True
            # نعرض حالة تحميل فورية أول ما تفتح الصفحة (بدل ما تتجمد الواجهة
            # بصمت لثانية أو ثانيتين وقت أول جلب شبكي) — بعدها نجدول الجلب
            # الفعلي بتايمر قصير عشان Qt يقدر يرسم شاشة "جاري التحميل" فعليًا
            # قبل ما نبدأ الاستدعاءات الشبكية الحاجبة (blocking).
            self._show_loading()
            QTimer.singleShot(30, self.load_cases)

    def _open_stats(self):
        if not self.cookies:
            return
        dlg = ReferredStatsDialog(self, self.cookies, self.current_user)
        dlg.exec()

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
        self.scroll_layout.insertWidget(insert_at, _empty_state('clock', "جاري تحميل القضايا المتداولة..."))

    def load_cases(self):
        """يبدأ الجلب في خيط خلفي.

        سبب الخيط: الجلب سلسلة طلبات شبكة متسلسلة (قائمة المتداولة + قائمة
        المحجوزة + استكشاف نوع القضية/اللجنة لكل قضية) وكل واحد ياخذ وقتاً
        على شبكة الوزارة. لو صارت على خيط الواجهة لتجمّدت النافذة كلّها طول
        مدة الجلب ولا يردّ المستخدم على أي زر.

        كل لمس للـwidgets (العدّادات والقوائم) يصير في _apply_data — على خيط
        الواجهة — لأن Qt ما يسمح بتعديل عناصر من خيط ثاني.
        """
        if not self.cookies:
            return
        if self._loading:
            return  # جلب جارٍ — ما نشغّل خيط ثاني (عند التحديث أثناء الجلب)
        self._loading = True
        self._load_token += 1
        token = self._load_token
        cookies = self.cookies
        current_user = self.current_user
        # نثبّت مراجع الدوال الآن (وقت بدء الخيط) بدل تصفيرها وقت الاستدعاء،
        # حتى لا يتغيّر السلوك لو تغيّرت الدالة أثناء الجلب.
        _get_pending = get_pending_cases
        _get_reserved = get_reserved_cases
        _ensure_type = ensure_case_type_and_committee
        _sync_status = sync_case_statuses
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setEnabled(False)

        def work():
            try:
                cases = _get_pending(cookies)
                reserved = _get_reserved(cookies)
                reserved_map = {c['caso_no']: c for c in reserved}

                known = {c['caso_no'] for c in cases}
                for rc in reserved:
                    if rc['caso_no'] not in known:
                        cases.append(rc)

                _ensure_type(cases, cookies, current_user)
                _sync_status(cases, reserved_map, current_user)
            except Exception as e:
                self._emit_from_worker(self._data_failed, {'token': token, 'error': e})
                return
            self._emit_from_worker(self._data_ready, {
                'token': token,
                'cases': cases,
                'reserved': reserved,
                'reserved_map': reserved_map,
            })

        threading.Thread(target=work, daemon=True).start()

    def _emit_from_worker(self, signal, payload):
        """إرسال النتيجة من الخيط الخلفي بأمان.

        الخيط ممكن يكمّل بعد ما الصفحة تُحذف (لو المستخدم أغلقها أثناء الجلب)،
        أو بعد ما البرنامج بدأ الإغلاق — فنتأكد إن كائن Qt لسه حي وإن التطبيق
        ما زال شغّالاً قبل ما نبعث الإشارة. بدون هذا قد ينكسر البرنامج بخطأ
        وصول (Access Violation) بدل رسالة خطأ عادية.
        """
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
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setEnabled(True)
        cases = payload['cases']
        reserved = payload['reserved']
        reserved_map = payload['reserved_map']

        self.kpi_total.value_label.setText(str(len(cases)))
        self.kpi_reserved.value_label.setText(str(len(reserved)))

        self._cases = cases
        self._reserved_map = reserved_map
        self._render_cases()

    def _apply_error(self, payload):
        """الخطأ يوصلنا على خيط الواجهة — نفس معالجة الخطأ السابقة"""
        if payload.get('token') != self._load_token:
            return
        self._loading = False
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setEnabled(True)
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
            view = _state_view('alert', "تعذّر تحميل القضايا المتداولة", "حدث خطأ غير متوقع أثناء قراءة البيانات",
                               retry_cb=self._refresh_clicked, detail=_short(e))
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, view)

    def _show_no_login(self):
        self._clear_scroll()
        self._after_clear()
        self._unknown_figures()
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, _state_view(
            'offline', "لا يوجد اتصال بنظام الخبراء", "سجّل الدخول من جديد لعرض القضايا المتداولة"))

    def _after_clear(self):
        pass

    def _unknown_figures(self):
        """عرض فقط: لا أرقام كاذبة — «—» محايد بدل «0» حين لا توجد بيانات"""
        for k in [w for w in self.findChildren(KPICard)]:
            _kpi_tone(k, th.TEXT_SECONDARY, "—")
        if hasattr(self, "_chips"):
            self._sync_chips(None)

    # ---- عرض فقط: الفلترة والتجميع على القائمة المحمّلة نفسها (بلا أي جلب جديد) ----
    def _sync_chips(self, counts):
        names = {'all': 'الكل', 'reserved': 'محجوزة', 'secondment': 'استعانة'}
        for key, chip in self._chips.items():
            chip.setText(names[key] if counts is None else f"{names[key]}  {counts.get(key, 0)}")
            chip.setChecked(key == self._filter)
        QTimer.singleShot(0, lambda: self._place_chip_pill(animate=True))

    def _place_chip_pill(self, animate):
        pill = getattr(self, "_chip_pill", None)
        chip = self._chips.get(self._filter) if hasattr(self, "_chips") else None
        if pill is None or chip is None or not chip.isVisible():
            return
        if animate and pill.isVisible():
            mo.glide(pill, chip.geometry(), 220)
        else:
            pill.setGeometry(chip.geometry())
            pill.show()
        pill.lower()

    def _set_filter(self, key):
        """التبديل بين التصنيفات: إظهار/إخفاء البطاقات المبنية أصلاً — لا إعادة بناء ولا حركة ظهور (2026-10-25)."""
        self._filter = key
        if getattr(self, '_groups', None) is None:
            self._render_cases()
            return
        self._sync_chips(self._counts)
        self._show_filter()

    def _secondment_of(self, cases):
        """القضايا التي نوعها «استعانة» (من case_db) — يُحسب مرة واحدة لكل جلب."""
        out = set()
        for c in cases:
            try:
                cached = case_db.get_case(c['caso_no'])
                if cached and cached.get('case_type', '') == 'استعانة':
                    out.add(c['caso_no'])
            except Exception:
                pass
        return out

    def _render_cases(self):
        """تبني القائمة مرة واحدة لكل جلب (العناوين والبطاقات بالترتيب)، ثم التصنيف بالإظهار/الإخفاء (_show_filter)."""
        cases, reserved_map = self._cases, self._reserved_map
        secondment = self._secondment_of(cases)
        self._secondment = secondment
        self.kpi_secondment.value_label.setText(str(len(secondment)))
        _kpi_tone(self.kpi_total, th.TEXT_PRIMARY)
        _kpi_tone(self.kpi_reserved, th.BLUE_INFO_TEXT)
        _kpi_tone(self.kpi_secondment, th.SECONDMENT_TEXT)
        self._counts = {'all': len(cases), 'reserved': sum(1 for c in cases if c['caso_no'] in reserved_map),
                        'secondment': len(secondment)}
        self._sync_chips(self._counts)

        self._clear_scroll()
        self._groups = None
        insert_at = self.scroll_layout.count() - 1
        if not cases:
            self.scroll_layout.insertWidget(insert_at, _empty_state('folder', "لا توجد قضايا حالياً"))
            return

        reserved_list = [c for c in cases if c['caso_no'] in reserved_map]
        rest = [c for c in cases if c['caso_no'] not in reserved_map]
        reserved_list.sort(key=lambda c: (_remaining_days(reserved_map.get(c['caso_no'])) is None,
                                          _remaining_days(reserved_map.get(c['caso_no'])) or 0))
        self._groups = []
        for title, group in (("محجوزة — بانتظار التقرير", reserved_list), ("متداولة", rest)):
            if not group:
                continue
            head = _section_header(title, len(group))
            self.scroll_layout.insertWidget(insert_at, head)
            insert_at += 1
            items = []
            for case in group:
                card = PendingCaseCard(case, self.cookies, self.current_user,
                    reserved_info=reserved_map.get(case['caso_no']))
                mo.hover_edge(card, th.RAIL_LINE)
                self.scroll_layout.insertWidget(insert_at, card)
                insert_at += 1
                items.append((case['caso_no'], card))
            self._groups.append((title, head, items))
        self._empty_filter = _empty_state('folder', "لا توجد قضايا بهذا التصنيف")
        self.scroll_layout.insertWidget(insert_at, self._empty_filter)
        self._show_filter()
        mo.stagger([self.scroll_layout.itemAt(i).widget() for i in range(self.scroll_layout.count() - 1)
                    if self.scroll_layout.itemAt(i).widget().isVisibleTo(self.scroll_content)],
                   step=25, duration=200)

    def _visible(self, caso_no):
        if self._filter == 'reserved':
            return caso_no in self._reserved_map
        if self._filter == 'secondment':
            return caso_no in getattr(self, '_secondment', set())
        return True

    def _show_filter(self):
        """إظهار بطاقات التصنيف الحالي وإخفاء غيرها؛ عنوان القسم يظهر بعدد بطاقاته الظاهرة."""
        shown = 0
        for title, head, items in self._groups or []:
            n = 0
            for caso_no, card in items:
                on = self._visible(caso_no)
                card.setVisible(on)
                n += on
            head.setVisible(bool(n))
            pill = head.layout().itemAt(1).widget() if head.layout() and head.layout().count() > 1 else None
            if pill is not None and hasattr(pill, 'setText'):
                pill.setText(str(n))
            shown += n
        if getattr(self, '_empty_filter', None) is not None:
            self._empty_filter.setVisible(not shown)