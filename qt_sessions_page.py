# ===== qt_sessions_page.py — صفحة جدول الجلسات بتصميم «دفتر اليومية» =====
# يعيد استخدام كل منطق الأعمال الأصلي (api.py, mahdar.py, gov_notice.py,
# case_db.py, icloud_calendar.py) — طبقة العرض: خط زمني كحلي، فصول الأيام،
# شريط الأسبوع، خط «الآن» الزمردي، ودرج «بدون جلسة قادمة» المطويّ.
# النسخة السابقة محفوظة في qt_sessions_page_old.py.bak
import os
import requests
import threading
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPointF, QPoint, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QCursor, QFontMetrics, QPixmap, QIcon, QPainterPath, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame,
    QMessageBox, QDialog, QLineEdit, QComboBox, QFormLayout, QApplication,
    QRadioButton, QButtonGroup, QSizePolicy, QMenu, QWidgetAction, QPushButton
)

import qt_theme as th
import qt_icons as ic
import qt_motion as mo
from qt_widgets import (
    Card, Badge, PrimaryButton, SecondaryButton, PageHeader, KPICard, soft_shadow,
    SmartDateEdit, SmartTimeEdit,
)

from config import SESSION_TYPES, BASE_URL, GOV_KEYWORDS, SESSION_COLORS
from api import get_day_name, get_sessions, get_all_case_sessions, parse_case_info, get_case_parties_summary, compute_session_number
from mahdar import fill_mahdar
from gov_notice import fill_gov_notice
from weekly_report import build_weekly_report_html, _week_bounds, suggest_default_period
import case_db

# دوال منطقية بحتة (لا تعتمد على tkinter) — نعيد استخدامها من ui.py كما هي
from ui import get_experts, clean_spaces, detect_gov_parties


# ---------- ألوان «دفتر اليومية» — كلها رموز من qt_theme ----------
RAIL_LINE       = th.RAIL_LINE         # الخط الزمني — كحلي مخفّف جدًا
TYPE_BADGE_BG   = th.NAVY_TINT         # خلفية شارة نوع الجلسة (النص كحلي)
SECONDMENT_BG   = th.SECONDMENT_BG     # بطاقة الاستعانة
SECONDMENT_TEXT = th.SECONDMENT_TEXT   # نص شارة الاستعانة
PAST_SURFACE    = th.BG                # جلسة مضى وقتها اليوم — تذوب في ورق الصفحة

WEEK_DAYS_AR = ['الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس']


def _fmt_time(time_str):
    try:
        h, mn = int(time_str.split(':')[0]), int(time_str.split(':')[1])
        sfx = "مساءً" if h >= 12 else "صباحاً"
        dh = h if h <= 12 else h - 12
        if dh == 0:
            dh = 12
        return f"{dh:02d}:{mn:02d}", sfx
    except Exception:
        return time_str, ""


def _disp_date(date_str):
    """عرض فقط: يحوّل YYYY/MM/DD أو YYYY-MM-DD إلى DD/MM/YYYY (صيغة العرض الموحّدة).
    لا تُستخدم للتخزين أو المقارنة — القيم الأصلية تبقى كما هي."""
    for fmt in ('%Y/%m/%d', '%Y-%m-%d'):
        try:
            return datetime.strptime((date_str or '').strip()[:10], fmt).strftime('%d/%m/%Y')
        except ValueError:
            continue
    return date_str


def _elide(text, limit):
    """عرض فقط: يقصّ النص الأطول من limit ويضيف «…». يرجع (النص المعروض، هل قُصّ)"""
    text = (text or '').strip()
    if len(text) <= limit:
        return text, False
    return text[:limit - 1].rstrip() + "…", True


class AddSessionDialog(QDialog):
    """نافذة إضافة جلسة قادمة — نسخة Qt من AddSessionWindow الأصلية بنفس منطق الحفظ"""
    def __init__(self, parent, cookies, caso_no, case_name, last_time, on_success):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("إضافة جلسة قادمة")
        self.setFixedWidth(420)
        self.cookies = cookies
        self.caso_no = caso_no
        self.case_name = case_name
        self.on_success = on_success
        self.setStyleSheet(f"QDialog {{ background:{th.BG}; }}")   # محصور في النافذة — لا يسري على التلميحات

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        banner = Card(bg=th.BLUE_INFO_BG, border=th.BLUE_INFO_BG)
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(14, 10, 14, 10)
        t = QLabel(caso_no)
        t.setStyleSheet(f"color:{th.BLUE_INFO_TEXT}; font-weight:700; font-size:13px; border:none;")
        t.setAlignment(th.ARIGHT)
        shown, cut = _elide(case_name, 44)
        s = QLabel(shown)
        if cut:
            s.setToolTip(case_name)
        s.setStyleSheet(f"color:{th.BLUE_INFO_TEXT}; font-size:11px; border:none;")
        s.setAlignment(th.ARIGHT)
        bl.addWidget(t)
        bl.addWidget(s)
        root.addWidget(banner)

        form = QFormLayout()
        form.setLabelAlignment(th.ARIGHT)
        form.setSpacing(10)

        self.date_edit = SmartDateEdit(initial=datetime.now().strftime("%Y/%m/%d"))
        self.time_edit = SmartTimeEdit(initial=last_time or "10:30")

        self.type_combo = QComboBox()
        self.type_combo.addItems(list(SESSION_TYPES.keys()))
        self.type_combo.setStyleSheet(self._field_style())
        self.type_combo.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        lbl_date = QLabel("التاريخ (مثال: 15 أو 15/7 أو 15/7/2026)")
        lbl_time = QLabel("التوقيت (مثال: 10 أو 1030)")
        lbl_type = QLabel("نوع الجلسة")
        for l in (lbl_date, lbl_time, lbl_type):
            l.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none;")

        form.addRow(lbl_date, self.date_edit)
        form.addRow(lbl_time, self.time_edit)
        form.addRow(lbl_type, self.type_combo)
        root.addLayout(form)

        btns = QHBoxLayout()
        cancel = SecondaryButton("إلغاء")
        cancel.clicked.connect(self.reject)
        save = PrimaryButton("حفظ الجلسة")
        save.clicked.connect(self._submit)
        btns.addWidget(save)
        btns.addStretch()
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _field_style(self):
        return f"""
            QLineEdit, QComboBox {{
                background: white; border: 1px solid {th.BORDER}; border-radius: 10px;
                padding: 9px 12px; font-size: 13px; color: {th.TEXT_PRIMARY};
            }}
            QLineEdit:focus, QComboBox:focus {{ border: 1px solid {th.NAVY}; }}
        """

    def _submit(self):
        dv = self.date_edit.get_value().strip()
        tv = self.time_edit.get_value().strip()
        typev = self.type_combo.currentText().strip()
        if not dv or not tv or typev not in SESSION_TYPES:
            QMessageBox.warning(self, "تنبيه", "يرجى تعبئة كل الحقول بشكل صحيح")
            return
        try:
            import urllib3
            urllib3.disable_warnings()
            r = requests.post(f"{BASE_URL}/includes/insert.php",
                data={'ECS_IN_REGNO': self.caso_no, 'EMET_MEET_DTE': dv,
                      'EMET_MEET_TIME': tv, 'EMET_TYPE': SESSION_TYPES[typev]},
                cookies=self.cookies, verify=False)
            code = r.text.strip()
            msgs = {'1': 'تم الحفظ بنجاح', '2': 'حدث خطأ', '3': 'تعارض في التوقيت',
                    '4': 'هذه جلسة حجز', '5': 'إجازة رسمية', '6': 'أقل من 7 أيام'}
            msg = msgs.get(code, f"نتيجة: {code}")
            if code == '1':
                try:
                    case_db.upsert_session(self.caso_no, dv, tv, typev, self.case_name)
                except Exception:
                    pass
                try:
                    from db_writer import insert_event_record
                    insert_event_record(self.caso_no, dv, tv, typev)
                except Exception:
                    pass
                self._sync_to_calendar(dv, tv)
                QMessageBox.information(self, "تم", msg)
                self.accept()
                self.on_success()
            else:
                QMessageBox.warning(self, "تنبيه", msg)
        except Exception as e:
            QMessageBox.critical(self, "خطأ", str(e))

    def _sync_to_calendar(self, dv, tv):
        try:
            from icloud_calendar import has_credentials, add_calendar_event
            if not has_credentials():
                return
            summary = get_case_parties_summary(self.caso_no, self.cookies, '')
            start_dt = datetime.strptime(f"{dv} {tv}", "%Y/%m/%d %H:%M")
            add_calendar_event(f"{summary} - {self.caso_no}", start_dt, description=self.case_name or '')
        except Exception:
            pass


class WeeklyReportDialog(QDialog):
    """نافذة اختيار فترة كشف الجلسات قبل الطباعة — نسخة Qt من WeeklyReportDialog الأصلية"""
    def __init__(self, parent, cookies, expert_name):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("طباعة كشف الجلسات")
        self.setFixedWidth(440)
        self.cookies = cookies
        self.expert_name = expert_name
        self.setStyleSheet(f"QDialog {{ background:{th.BG}; }}")   # محصور في النافذة — لا يسري على التلميحات

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        title = QLabel("طباعة كشف الجلسات الأسبوعي")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:15px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        root.addWidget(title)

        default = suggest_default_period()
        self.group = QButtonGroup(self)

        this_s, this_e = _week_bounds(offset_weeks=0)
        next_s, next_e = _week_bounds(offset_weeks=1)

        self.rb_this = QRadioButton(f"هذا الأسبوع  ({this_s.strftime('%d/%m/%Y')} — {this_e.strftime('%d/%m/%Y')})")
        self.rb_next = QRadioButton(f"الأسبوع القادم  ({next_s.strftime('%d/%m/%Y')} — {next_e.strftime('%d/%m/%Y')})")
        self.rb_custom = QRadioButton("تحديد فترة مخصّصة")
        for rb in (self.rb_this, self.rb_next, self.rb_custom):
            rb.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:13px; border:none; padding:4px 0;")
            rb.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.group.addButton(rb)
            root.addWidget(rb)

        {'this': self.rb_this, 'next': self.rb_next, 'custom': self.rb_custom}[default].setChecked(True)

        self.custom_frame = QWidget()
        cf_lay = QFormLayout(self.custom_frame)
        cf_lay.setLabelAlignment(th.ARIGHT)
        self.date_from = QLineEdit(this_s.strftime('%Y/%m/%d'))
        self.date_to = QLineEdit(this_e.strftime('%Y/%m/%d'))
        for de in (self.date_from, self.date_to):
            de.setStyleSheet(f"""
                QLineEdit {{ background:white; border:1px solid {th.BORDER}; border-radius:10px; padding:8px 12px; font-size:13px; }}
                QLineEdit:focus {{ border:1px solid {th.NAVY}; }}
            """)
            de.setAlignment(th.ARIGHT)
        cf_lay.addRow("من", self.date_from)
        cf_lay.addRow("إلى", self.date_to)
        root.addWidget(self.custom_frame)

        self.rb_this.toggled.connect(self._sync_custom_state)
        self.rb_next.toggled.connect(self._sync_custom_state)
        self.rb_custom.toggled.connect(self._sync_custom_state)
        self._sync_custom_state()

        ori_row = QHBoxLayout()
        ori_lbl = QLabel("اتجاه الورقة")
        ori_lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none;")
        self.ori_group = QButtonGroup(self)
        self.rb_landscape = QRadioButton("بالعرض")
        self.rb_portrait = QRadioButton("بالطول")
        for rb in (self.rb_landscape, self.rb_portrait):
            rb.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:12px; border:none;")
            self.ori_group.addButton(rb)
        self.rb_landscape.setChecked(True)
        ori_row.addWidget(ori_lbl)
        ori_row.addStretch()
        ori_row.addWidget(self.rb_portrait)
        ori_row.addWidget(self.rb_landscape)
        root.addLayout(ori_row)

        btns = QHBoxLayout()
        cancel = SecondaryButton("إلغاء")
        cancel.clicked.connect(self.reject)
        gen = PrimaryButton("طباعة")
        gen.clicked.connect(self._generate)
        btns.addWidget(gen)
        btns.addStretch()
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _sync_custom_state(self):
        self.custom_frame.setEnabled(self.rb_custom.isChecked())

    def _generate(self):
        if self.rb_this.isChecked():
            start, end = _week_bounds(offset_weeks=0)
        elif self.rb_next.isChecked():
            start, end = _week_bounds(offset_weeks=1)
        else:
            try:
                start = datetime.strptime(self.date_from.text().strip(), '%Y/%m/%d')
                end = datetime.strptime(self.date_to.text().strip(), '%Y/%m/%d')
            except Exception:
                QMessageBox.warning(self, "تنبيه", "يرجى إدخال تاريخين صحيحين")
                return
            if end < start:
                QMessageBox.warning(self, "تنبيه", "تاريخ النهاية قبل تاريخ البداية")
                return
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            all_s = get_sessions(self.cookies, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
            orientation = 'landscape' if self.rb_landscape.isChecked() else 'portrait'
            path = build_weekly_report_html(all_s, start, end, self.expert_name,
                orientation=orientation, cookies=self.cookies)
            QApplication.restoreOverrideCursor()
            os.startfile(path)
            self.accept()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "خطأ", str(e))


# ======================================================================
#  عناصر العرض الجديدة — رسم فقط، بلا أي منطق أعمال
# ======================================================================

def _parse_day(date_str):
    """عرض فقط: يقرأ YYYY/MM/DD أو YYYY-MM-DD ويرجع date أو None"""
    for fmt in ('%Y/%m/%d', '%Y-%m-%d'):
        try:
            return datetime.strptime((date_str or '').strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def _session_kind(sdata):
    """عرض فقط: نوع الجلسة من لونها بنظام الخبراء (SESSION_COLORS) — لون غير معروف = بدون شارة"""
    color = (sdata.get('backgroundColor') or '').strip().lower()
    return {k.lower(): v for k, v in SESSION_COLORS.items()}.get(color, '')


def _pill(text, bg, fg):
    """شارة صغيرة داخل سطر البيانات (أصغر من Badge العامة لتجلس بجانب رقم الخبرة)"""
    lbl = QLabel(text)
    lbl.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:9px; padding:2px 10px;"
                      f" font-size:11px; font-weight:700; border:none;")
    lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return lbl


def _menu_icon(kind):
    """أيقونة خطية مرسومة بالكود (بلا ملفات — آمنة مع PyInstaller):
    كحلي بالوضع العادي، زمردي داكن عند المرور (QIcon.Mode.Active)"""
    icon = QIcon()
    for mode, color in ((QIcon.Mode.Normal, th.NAVY), (QIcon.Mode.Active, th.EMERALD_TEXT),
                        (QIcon.Mode.Selected, th.EMERALD_TEXT)):
        pm = QPixmap(36, 36)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.scale(2, 2)                      # رسم على شبكة 18×18 بدقة مضاعفة
        pen = QPen(QColor(color), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == 'calendar':             # ورقة تقويم: حلقتان + سطر رأس + نقطة يوم
            p.drawRoundedRect(QRectF(2.5, 4.0, 13.0, 11.5), 2.2, 2.2)
            p.drawLine(QPointF(6.0, 2.4), QPointF(6.0, 5.6))
            p.drawLine(QPointF(12.0, 2.4), QPointF(12.0, 5.6))
            p.drawLine(QPointF(2.5, 7.8), QPointF(15.5, 7.8))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(color)))
            p.drawEllipse(QPointF(11.4, 11.6), 1.4, 1.4)
        elif kind == 'gov':                # مبنى حكومي: سقف مثلث + ثلاثة أعمدة + قاعدة
            roof = QPainterPath()
            roof.moveTo(2.2, 6.6)
            roof.lineTo(9.0, 2.4)
            roof.lineTo(15.8, 6.6)
            roof.closeSubpath()
            p.drawPath(roof)
            for x in (4.8, 9.0, 13.2):
                p.drawLine(QPointF(x, 8.8), QPointF(x, 13.2))
            p.drawLine(QPointF(2.2, 15.6), QPointF(15.8, 15.6))
        elif kind == 'session':            # ساعة + علامة إضافة: جلسة قادمة
            p.drawEllipse(QPointF(7.6, 10.0), 5.6, 5.6)
            p.drawLine(QPointF(7.6, 10.0), QPointF(7.6, 6.9))
            p.drawLine(QPointF(7.6, 10.0), QPointF(9.8, 11.3))
            p.drawLine(QPointF(14.6, 1.9), QPointF(14.6, 6.3))
            p.drawLine(QPointF(12.4, 4.1), QPointF(16.8, 4.1))
        p.end()
        pm.setDevicePixelRatio(2)
        icon.addPixmap(pm, mode)
    return icon


def _desk_menu(parent, caption=''):
    """قائمة منسدلة بهوية «مكتب الخبير»: ورقة بيضاء بزوايا 12px، مرور زمردي، RTL"""
    menu = QMenu(parent)
    menu.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    menu.aboutToShow.connect(lambda: mo.fade_window(menu, 120))
    # زوايا دائرية حقيقية — بدون إطار نافذة النظام المربّع خلفها
    menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint
                        | Qt.WindowType.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    menu.setStyleSheet(f"""
        QMenu {{
            background: {th.SURFACE}; border: 1px solid {th.BORDER};
            border-radius: 12px; padding: 6px;
        }}
        QMenu::item {{
            color: {th.TEXT_PRIMARY}; font-size: 13px;
            padding: 9px 14px; border-radius: 8px; margin: 1px 0;
            background: transparent;
        }}
        QMenu::item:selected {{ background: {th.EMERALD_BG}; color: {th.EMERALD_TEXT}; }}
        QMenu::icon {{ padding: 0 10px; }}
        QMenu::separator {{ height: 1px; background: {th.BORDER_SOFT}; margin: 6px 10px; }}
    """)
    if caption:
        cap = QLabel(caption)
        cap.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:{th.FS_CAPTION}px; font-weight:{th.W_MEDIUM};"
                          f" padding:6px 14px 6px 14px; background:transparent;")
        cap.setAlignment(th.ARIGHT)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(cap)
        wa.setEnabled(False)
        menu.addAction(wa)
    return menu


def _menu_anchor(btn, menu):
    """موضع القائمة: تحت الزر مباشرة، حافتها اليمنى على حافة الزر اليمنى (RTL)"""
    right_bottom = btn.mapToGlobal(QPoint(btn.width(), btn.height() + 6))
    return QPoint(right_bottom.x() - menu.sizeHint().width(), right_bottom.y())



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


class ElidedLabel(QLabel):
    """عنوان سطر واحد يقصّ بـ«…» حسب العرض المتاح فعلًا، والاسم الكامل بتلميح —
    يمنع الأسماء الطويلة من فرض عرض أدنى يدفع الأزرار خارج الشاشة"""
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


def _mahdar_files(caso, max_age_sec=None, today_only=False):
    """قراءة فقط: ملفات المحاضر (أرقام.docx) بمجلد القضية — نفس المسار الذي يكتب فيه _print.
    لا تنشئ مجلدًا ولا تكتب شيئًا. ملف «اخطار_حكومة.docx» لا يُحسب محضرًا."""
    import re
    from expert_settings import minutes_read_dirs
    names, seen = [], set()
    for folder in minutes_read_dirs(caso or ""):          # مجلد القضية\محاضر ثم المكان القديم (توافق)
        try:
            for n in os.listdir(folder):
                m = re.fullmatch(r"(?:محضر الخبرة رقم )?(\d+)\.docx", n)
                n = f"{m.group(1)}.docx" if m else n
                if m and n not in seen:
                    seen.add(n)
                    names.append((folder, n))
        except OSError:
            continue
    now = datetime.now()
    out = []
    for folder, n in names:
        real = os.path.join(folder, n)
        if not os.path.exists(real):
            real = os.path.join(folder, f"محضر الخبرة رقم {n}")
        try:
            m = datetime.fromtimestamp(os.path.getmtime(real))
        except OSError:
            continue
        if max_age_sec is not None and (now - m).total_seconds() > max_age_sec:
            continue
        if today_only and m.date() != now.date():
            continue
        out.append(n)
    return out


def _sessions_phrase(n):
    if n == 1:
        return "جلسة واحدة"
    if n == 2:
        return "جلستان"
    if 3 <= n <= 10:
        return f"{n} جلسات"
    return f"{n} جلسة"


class SealStamp(QWidget):
    """«الختم»: دائرتان زمرديتان وكلمة «تم» مائلة — تُطبع مرة واحدة بحركة ضغطة ختم (320ms)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(68, 68)
        self._t = 1.0

    def stamp(self):
        from PyQt6.QtCore import QVariantAnimation
        if not mo.motion_enabled():
            self._t = 1.0
            self.update()
            return
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(320)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._tick)
        self._anim.start()

    def _tick(self, v):
        self._t = float(v)
        self.update()

    def paintEvent(self, e):
        t = self._t
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setOpacity(0.92 * t)
        c = self.width() / 2
        p.translate(c, c)
        s = 1.15 - 0.15 * t                     # يضغط من 115% إلى 100%
        p.scale(s, s)
        p.rotate(-10)
        col = QColor(th.EMERALD)
        p.setPen(QPen(col, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), 29, 29)
        p.setPen(QPen(col, 1.0))
        p.drawEllipse(QPointF(0, 0), 24.5, 24.5)
        f = p.font()
        f.setPixelSize(17)
        f.setWeight(QFont.Weight.ExtraBold)
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(-24, -14, 48, 28), Qt.AlignmentFlag.AlignCenter, "تم")
        p.end()


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


class RailGutter(QWidget):
    """عمود الخط الزمني على حافة القراءة (يمين) — خط متصل + عقدة لكل صف"""
    def __init__(self, kind='session', today=False, parent=None):
        super().__init__(parent)
        self.kind = kind          # 'session' | 'day' | 'now'
        self.today = today
        self.past = False
        self.setFixedWidth(36)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_past(self, past):
        self.past = past
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx = self.width() / 2
        cy = self.height() / 2
        p.setPen(QPen(QColor(RAIL_LINE), 2))
        p.drawLine(QPointF(cx, 0), QPointF(cx, self.height()))

        if self.kind == 'day':
            if self.today:
                p.setPen(QPen(QColor(th.EMERALD), 3))
                p.setBrush(QBrush(QColor(th.SURFACE)))
                p.drawEllipse(QPointF(cx, cy), 7.5, 7.5)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(th.NAVY)))
                p.drawEllipse(QPointF(cx, cy), 6.5, 6.5)
        elif self.kind == 'now':
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(th.EMERALD)))
            p.drawEllipse(QPointF(cx, cy), 5, 5)
        else:
            p.setPen(QPen(QColor(th.TEXT_MUTED if self.past else th.NAVY), 2))
            p.setBrush(QBrush(QColor(PAST_SURFACE if self.past else th.SURFACE)))
            p.drawEllipse(QPointF(cx, cy), 4.5, 4.5)
        p.end()


class _DayTile(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, day_date, parent=None):
        super().__init__(parent)
        self.day_date = day_date
        self.key = day_date.strftime('%Y/%m/%d')
        self.count = 0
        self.setObjectName("dayTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(74)

        lay = QVBoxLayout(self)
        self._compact = False
        self._unknown = False
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(0)
        self.name_lbl = QLabel(WEEK_DAYS_AR[(day_date.weekday() + 1) % 7])
        self.num_lbl = QLabel(day_date.strftime('%d'))
        self.dots = _CountDots()
        for w in (self.name_lbl, self.num_lbl):
            w.setAlignment(th.ARIGHT)
        lay.addWidget(self.name_lbl)
        lay.addWidget(self.num_lbl)
        lay.addWidget(self.dots)
        self._apply()

    def set_compact(self, compact):
        """عرض فقط: خانة أقصر برقم 18px على الشاشات القصيرة — بلا قص"""
        if compact == self._compact:
            return
        self._compact = compact
        self.setFixedHeight(64 if compact else 74)
        self.layout().setContentsMargins(12, 6 if compact else 8, 12, 6 if compact else 8)
        self._apply()

    def set_unknown(self, unknown):
        """عرض فقط: لا بيانات (خطأ/بلا اتصال) — مظهر محايد بدل الإيحاء بيوم فارغ"""
        self._unknown = unknown
        if unknown:
            self.count = 0
            self.dots.set_count(0)
            self.setToolTip("غير متاح — لم تُحمَّل الجلسات")
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self._apply()

    def set_count(self, n):
        self._unknown = False
        self.count = n
        self.dots.set_count(n, today=self._is_today())
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if n else Qt.CursorShape.ArrowCursor))
        self.setToolTip(f"{n} جلسة" if n > 2 else ("جلستان" if n == 2 else ("جلسة واحدة" if n == 1 else "لا توجد جلسات")))
        self._apply()

    def _is_today(self):
        return self.day_date == datetime.now().date()

    def _apply(self):
        today = self._is_today()
        past = self.day_date < datetime.now().date()
        if today:
            bg, border, name_c, num_c = th.NAVY, th.NAVY, th.SIDEBAR_TEXT_MUTED, "white"
        elif getattr(self, "_unknown", False):
            bg, border, name_c, num_c = th.SURFACE, th.BORDER, th.TEXT_SECONDARY, th.TEXT_SECONDARY
        elif self.count and not past:
            bg, border, name_c, num_c = th.SURFACE, th.BORDER, th.TEXT_SECONDARY, th.NAVY
        else:
            bg, border, name_c, num_c = "transparent", th.BORDER_SOFT, th.TEXT_MUTED, th.TEXT_MUTED
        hover = "" if today or not self.count else f"QFrame#dayTile:hover {{ border-color: {th.NAVY}; }}"
        self.setStyleSheet(f"""
            QFrame#dayTile {{ background:{bg}; border:1px solid {border}; border-radius:{th.RADIUS_CARD - 4}px; }}
            {hover}
        """)
        self.name_lbl.setStyleSheet(f"color:{name_c}; font-size:{th.FS_LABEL}px; font-weight:{th.W_MEDIUM}; background:transparent; border:none;")
        self.num_lbl.setStyleSheet(f"color:{num_c}; font-size:{18 if getattr(self, '_compact', False) else th.FS_DISPLAY}px; font-weight:{th.W_BOLD}; background:transparent; border:none;")

    def mousePressEvent(self, e):
        if self.count:
            self.clicked.emit(self.key)
        super().mousePressEvent(e)


class _CountDots(QWidget):
    """نقاط بعدد الجلسات (حتى 6) — قراءة الكثافة بلمحة"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.n = 0
        self.today = False
        self.setFixedHeight(10)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_count(self, n, today=False):
        self.n, self.today = n, today
        self.update()

    def paintEvent(self, e):
        if not self.n:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(th.EMERALD if self.today else th.NAVY)))
        shown = min(self.n, 6)
        x = self.width() - 4   # تبدأ من اليمين (RTL)
        for _ in range(shown):
            p.drawEllipse(QPointF(x, 5), 3, 3)
            x -= 9
        p.end()


class WeekStrip(QWidget):
    """شريط أسبوع العمل الكويتي (أحد→خميس) — الضغط على يوم ينزلق لفصله بالقائمة"""
    day_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        today = datetime.now().date()
        sunday = today - timedelta(days=(today.weekday() + 1) % 7)
        if today.weekday() in (4, 5):        # جمعة/سبت → أسبوع العمل القادم
            sunday += timedelta(days=7)
        self.tiles = []
        for i in range(5):
            t = _DayTile(sunday + timedelta(days=i))
            t.clicked.connect(self.day_clicked.emit)
            lay.addWidget(t, 1)
            self.tiles.append(t)

    def set_unknown(self):
        for t in self.tiles:
            t.set_unknown(True)

    def set_sessions(self, sessions_data):
        counts = {}
        for s in sessions_data:
            k = (s.get('start', '') or '')[:10]
            counts[k] = counts.get(k, 0) + 1
        for t in self.tiles:
            t.set_count(counts.get(t.key, 0))


class NowMarker(QWidget):
    """خط «الآن» الزمردي — يُوضع بين جلسات اليوم في موضعه الزمني"""
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.rail = RailGutter('now')
        self.lbl = QLabel()
        self.lbl.setStyleSheet(f"color:{th.EMERALD}; font-size:11px; font-weight:700; background:transparent; border:none;")
        line = QFrame()
        line.setFixedHeight(2)
        line.setStyleSheet(f"background:{th.EMERALD}; border:none; border-radius:1px;")
        self.line = line
        self._done = None
        lay.addWidget(self.rail)
        lay.addWidget(self.lbl)
        lay.addWidget(line, 1)
        self.setFixedHeight(24)
        self.refresh()
        self._done = None           # أول تحديث حقيقي يحدّد الحالة بلا حركة — الرسم فقط عند التحوّل

    def refresh(self, day_done=False):
        prev, self._done = self._done, day_done
        if day_done:
            self.lbl.setText("انتهت جلسات اليوم")
        else:
            self.lbl.setText(f"الآن  {th.ltr(datetime.now().strftime('%H:%M'))}")
        if prev is False and day_done:
            self._draw_line()

    def _draw_line(self):
        """لحظة واحدة: حين تنتهي آخر جلسة، يمتدّ الخط من جهة القراءة إلى آخره (400ms)"""
        if not mo.motion_enabled():
            return
        full = max(1, self.line.width())
        a = QPropertyAnimation(self.line, b"maximumWidth", self)
        a.setDuration(400)
        a.setStartValue(0)
        a.setEndValue(full)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.finished.connect(lambda: self.line.setMaximumWidth(16777215))
        self._line_anim = a
        a.start()


class _Chevron(QWidget):
    """سهم صغير مرسوم: لأسفل والدرج مطويّ، ويدور 180° عند الفتح (200ms)"""
    def __init__(self, open_=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._angle = 180.0 if open_ else 0.0
        self._anim = None

    def set_open(self, open_, animate=True):
        to = 180.0 if open_ else 0.0
        if not animate or not mo.motion_enabled():
            self._angle = to
            self.update()
            return
        from PyQt6.QtCore import QVariantAnimation
        if self._anim is not None:
            self._anim.stop()
        a = QVariantAnimation(self)
        a.setStartValue(float(self._angle))
        a.setEndValue(to)
        a.setDuration(200)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(lambda v: (setattr(self, "_angle", float(v)), self.update()))
        self._anim = a
        a.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.translate(7, 7)
        p.rotate(self._angle)
        pen = QPen(QColor(th.TEXT_SECONDARY), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(-4, -2)
        path.lineTo(0, 2)
        path.lineTo(4, -2)
        p.drawPath(path)
        p.end()


class NoUpcomingDrawer(QWidget):
    """درج «قضايا بدون جلسة قادمة» — مطويّ افتراضيًا، يُفتح بحركة ارتفاع ناعمة"""
    toggled = pyqtSignal(bool)

    def __init__(self, count, open_=False, parent=None):
        super().__init__(parent)
        self._open = open_
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 10)
        outer.setSpacing(0)
        indent = QWidget()
        indent.setFixedWidth(48)            # عرض عمود الخط الزمني + المسافة
        outer.addWidget(indent)

        self.frame = Card()
        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)

        self.head = QFrame()
        self.head.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.head.setStyleSheet("background:transparent; border:none;")
        hl = QHBoxLayout(self.head)
        hl.setContentsMargins(20, 14, 20, 14)
        hl.setSpacing(10)
        title = QLabel("قضايا بدون جلسة قادمة")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:13px; font-weight:700; border:none;")
        cnt = _pill(str(count), th.DANGER_BG, th.DANGER_TEXT)
        self.hint = QLabel()
        self.hint.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:{th.FS_LABEL}px; font-weight:{th.W_MEDIUM}; border:none;")
        hl.addWidget(title)
        hl.addWidget(cnt)
        hl.addStretch()
        hl.addWidget(self.hint)
        self.chev = _Chevron(open_)
        hl.addWidget(self.chev)
        self.head.mousePressEvent = lambda e: self.toggle()

        self.body = QWidget()
        self.body.setStyleSheet("background:transparent;")
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 6)
        self.body_lay.setSpacing(0)

        fl.addWidget(self.head)
        fl.addWidget(self.body)
        outer.addWidget(self.frame, 1)

        self._anim = QPropertyAnimation(self.body, b"maximumHeight", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.body.setMaximumHeight(16777215 if open_ else 0)
        self._sync_hint()

    def add_row(self, w):
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{th.BORDER_SOFT}; border:none;")
        self.body_lay.addWidget(sep)
        self.body_lay.addWidget(w)
        self._rows = getattr(self, "_rows", []) + [w]

    def _sync_hint(self):
        self.hint.setText("إخفاء" if self._open else "عرض")
        chev = getattr(self, "chev", None)
        if chev is not None:
            chev.set_open(self._open, animate=True)

    def toggle(self):
        self._open = not self._open
        full = self.body.sizeHint().height()
        self._anim.stop()
        self._anim.setStartValue(self.body.height() if self._open else full)
        self._anim.setEndValue(full if self._open else 0)
        if self._open:
            self._anim.finished.connect(self._release)
        self._anim.start()
        if self._open:
            mo.stagger(getattr(self, "_rows", []), step=20, duration=180)
        self._sync_hint()
        self.toggled.emit(self._open)

    def _release(self):
        try:
            self._anim.finished.disconnect(self._release)
        except TypeError:
            pass
        if self._open:
            self.body.setMaximumHeight(16777215)


# ======================================================================


class SessionCardQt(QWidget):
    """صف جلسة بدفتر اليومية: عقدة على الخط الزمني + بطاقة (وقت، اسم، نوع، إجراء رئيسي واحد)"""
    def __init__(self, sdata, cookies, user, on_refresh, title_fallback_fn=None, parent=None):
        super().__init__(parent)
        self.cookies = cookies
        self.user = user
        self.on_refresh = on_refresh
        self.caso = sdata.get('description', '')
        self.date = sdata.get('start', '').split(' ')[0] if sdata.get('start') else ''
        self.time = sdata.get('start', '').split(' ')[1] if len(sdata.get('start', '').split(' ')) > 1 else ''

        title = sdata.get('title', '').strip().replace(self.caso, '').strip()
        if not title and title_fallback_fn:
            title = title_fallback_fn(self.caso)
        self.case_title = title

        case_type = ''
        try:
            cached = case_db.get_case(self.caso)
            if cached:
                case_type = cached.get('case_type', '')
        except Exception:
            pass
        self._secondment = (case_type == 'استعانة')
        self._past = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self.rail = RailGutter('session')
        self.body = Card(bg=SECONDMENT_BG if self._secondment else th.SURFACE)
        root = QHBoxLayout(self.body)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(16)

        # كتلة الوقت — مستقلة بتباين هادئ
        self.time_block = QFrame()
        self.time_block.setFixedWidth(78)
        tb_lay = QVBoxLayout(self.time_block)
        tb_lay.setContentsMargins(6, 10, 6, 10)
        tb_lay.setSpacing(2)
        dh, sfx = _fmt_time(self.time)
        self.t1 = QLabel(dh)
        self.t1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.t2 = QLabel(sfx)
        self.t2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tb_lay.addWidget(self.t1)
        tb_lay.addWidget(self.t2)

        # كتلة التفاصيل — الاسم أبرز عنصر، وتحته سطر: رقم الخبرة + نوع الجلسة + استعانة
        info = QVBoxLayout()
        info.setSpacing(6)
        self.name_lbl = ElidedLabel(title if title else self.caso)
        self.name_lbl.setAlignment(th.ARIGHT)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        num_lbl = QLabel(f"رقم الخبرة {th.ltr(self.caso)}")
        num_lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none; background:transparent;")
        meta.addWidget(num_lbl)
        kind = _session_kind(sdata)
        if kind:
            meta.addWidget(_pill(kind, TYPE_BADGE_BG, th.NAVY))
        if self._secondment:
            meta.addWidget(_pill("استعانة", th.SURFACE, SECONDMENT_TEXT))
        if _mahdar_files(self.caso, today_only=True):
            meta.addWidget(_pill("محضر اليوم جاهز", th.EMERALD_BG, th.EMERALD_TEXT))
        meta.addStretch()
        info.addWidget(self.name_lbl)
        info.addLayout(meta)

        # كتلة الإجراءات
        actions = QHBoxLayout()
        actions.setSpacing(6)
        print_btn = PrimaryButton("طباعة المحضر")
        print_btn.clicked.connect(self._print)
        print_btn.clicked.connect(self._after_print)     # عرض فقط: يعمل بعد انتهاء _print
        more_btn = SecondaryButton("إجراءات أخرى")
        more_btn.clicked.connect(self._show_more_actions)
        self.more_btn = more_btn
        actions.addWidget(more_btn)
        actions.addWidget(print_btn)

        root.addWidget(self.time_block)
        root.addLayout(info, 3)
        root.addStretch()
        root.addLayout(actions)

        body_wrap = QVBoxLayout()
        body_wrap.setContentsMargins(0, 5, 0, 5)
        body_wrap.addWidget(self.body)
        row.addWidget(self.rail)
        row.addLayout(body_wrap, 1)
        self._apply_state()
        mo.hover_edge(self.body, th.RAIL_LINE)

    # ---- عرض فقط ----
    def _after_print(self):
        """لو أُنشئ محضر لهذه القضية خلال آخر دقيقتين (فحص مجلد للقراءة فقط) → يُطبع الختم"""
        if not _mahdar_files(self.caso, max_age_sec=120):
            return
        seal = getattr(self, "_seal", None)
        if seal is None:
            seal = self._seal = SealStamp(self.body)
        x = int(self.body.width() * 0.40) - seal.width() // 2
        y = (self.body.height() - seal.height()) // 2
        seal.move(max(0, x), max(0, y))
        seal.show()
        seal.raise_()
        seal.stamp()

    def start_dt(self):
        try:
            return datetime.strptime(f"{self.date} {self.time[:5]}", "%Y/%m/%d %H:%M")
        except Exception:
            return None

    def set_past(self, past):
        if past == self._past:
            return
        self._past = past
        self._apply_state()

    def _apply_state(self):
        if self._past:
            bg = PAST_SURFACE
            self.body.setGraphicsEffect(None)
        else:
            bg = SECONDMENT_BG if self._secondment else th.SURFACE
            soft_shadow(self.body)
        self.body.setStyleSheet(f"""
            QFrame#card {{ background:{bg}; border:1px solid {th.BORDER}; border-radius:{th.RADIUS_CARD}px; }}
        """)
        tb_bg = "transparent" if self._past else th.NAVY_SOFT
        self.time_block.setStyleSheet(f"background:{tb_bg}; border-radius:12px; border:none;")
        self.t1.setStyleSheet(f"color:{th.TEXT_MUTED if self._past else th.NAVY}; font-size:15px; font-weight:700; border:none; background:transparent;")
        self.t2.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:10px; border:none; background:transparent;")
        self.name_lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY if self._past else th.TEXT_PRIMARY}; font-size:{th.FS_TITLE}px; font-weight:{th.W_MEDIUM}; border:none; background:transparent;")
        self.rail.set_past(self._past)

    def _show_more_actions(self):
        menu = _desk_menu(self)
        a1 = menu.addAction(_menu_icon('calendar'), "إضافة للتقويم")
        a2 = menu.addAction(_menu_icon('gov'), "إخطار جهة حكومية")
        menu.addSeparator()   # ما يكتب في نظام الخبراء مفصول عمّا يبقى على جهازك
        a3 = menu.addAction(_menu_icon('session'), "إضافة جلسة قادمة")
        action = menu.exec(_menu_anchor(self.more_btn, menu))
        if action == a1:
            self._add_to_calendar()
        elif action == a2:
            self._print_gov_notice()
        elif action == a3:
            dlg = AddSessionDialog(self.window(), self.cookies, self.caso, self.case_title, self.time, self.on_refresh)
            dlg.exec()

    def _busy(self, on):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor if on else Qt.CursorShape.ArrowCursor)

    def _ensure_case_data(self):
        """main thread — لو تحتاج استخراج، نافذة التقدم تشتغل بدون تجميد"""
        from qt_first_session import ensure_case_data_qt
        case_dict = {'caso_no': self.caso, 'title': self.case_title, 'received_date': '', 'autocase_no': ''}
        return ensure_case_data_qt(self.window(), self.cookies, self.user, case_dict)

    def _fetch_common(self, case_data):
        """تشتغل بالـthread — طلبات الملف الآلي فقط، بدون أي لمس للواجهة"""
        import case_header
        h = case_header.fetch_header(self.cookies, self.user, self.caso, case_data)
        return h['info'], h['es'], h['plaintiffs'], h['defendants'], h['court_case_number']

    def _run_job(self, work, on_done):
        """
        يشغّل work() بالخلفية (البرنامج يظل يستجيب)، وبعدها on_done(نتيجة)
        بالـmain thread. يمنع الضغط المكرر على نفس البطاقة أثناء التنفيذ.
        """
        from qt_extraction import run_in_background
        if getattr(self, '_job_running', False):
            return
        self._job_running = True
        self._busy(True)

        def _ok(result):
            self._busy(False)
            try:
                self._job_running = False
                on_done(result)
            except RuntimeError:
                pass   # البطاقة انحذفت (تحديث الصفحة) قبل ما تخلص العملية
            except Exception as e:
                QMessageBox.critical(self.window(), "خطأ", str(e))

        def _fail(msg):
            self._busy(False)
            try:
                self._job_running = False
                QMessageBox.critical(self, "خطأ", msg)
            except RuntimeError:
                pass

        run_in_background(work, _ok, _fail)

    def _print(self):
        if getattr(self, '_job_running', False):
            return
        try:
            case_data = self._ensure_case_data()
        except Exception as e:
            QMessageBox.critical(self, "خطأ", str(e))
            return

        def work():
            common = self._fetch_common(case_data)
            num = compute_session_number(self.cookies, self.caso, self.date)
            return common, num

        self._run_job(work, self._print_done)

    def _print_done(self, result):
        (info, es, plaintiffs, defendants, court_case_number), num = result
        pl = [clean_spaces(p) for p in plaintiffs]
        pl_s = pl[0] if len(pl) == 1 else '\n'.join([f"{i+1}- {p}" for i, p in enumerate(pl)])
        df = [clean_spaces(d) for d in defendants]
        df_s = df[0] if len(df) == 1 else '\n'.join([f"{i+1}- {d}" for i, d in enumerate(df)])

        from expert_settings import minute_path
        path = minute_path(self.caso, num)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        fill_mahdar(path, {
            'رقم_المحضر': str(num), 'اليوم': get_day_name(self.date),
            'التاريخ': self.date, 'رقم_الخبرة': self.caso, 'الساعة': self.time,
            'رقم_الدعوى': court_case_number, 'الواردة_من': info.get('source', ''),
            'المرفوعة_من': pl_s, 'المرفوعة_ضد': df_s,
            'الخبير': es, 'المحافظة': info.get('governorate', ''),
            'القسم': info.get('department', ''),
        })
        QMessageBox.information(self, "تم", f"تم إنشاء المحضر!\n\n{th.ltr(path)}")
        os.startfile(path)

    def _print_gov_notice(self):
        if getattr(self, '_job_running', False):
            return
        try:
            case_data = self._ensure_case_data()
        except Exception as e:
            QMessageBox.critical(self, "خطأ", str(e))
            return
        self._run_job(lambda: self._fetch_common(case_data), self._gov_notice_done)

    def _gov_notice_done(self, common):
        info, es, plaintiffs, defendants, court_case_number = common
        pl = [clean_spaces(p) for p in plaintiffs]
        pl_s = pl[0] if len(pl) == 1 else '\n'.join([f"{i+1}- {p}" for i, p in enumerate(pl)])
        df = [clean_spaces(d) for d in defendants]
        df_s = df[0] if len(df) == 1 else '\n'.join([f"{i+1}- {d}" for i, d in enumerate(df)])
        gov_parties = detect_gov_parties(plaintiffs, defendants)
        gov_text = '  ،  '.join(gov_parties)

        from expert_settings import load_location
        loc = load_location()
        from expert_settings import notice_path
        path = notice_path(self.caso)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        fill_gov_notice(path, {
            'رقم_الدعوى': court_case_number, 'الواردة_من': info.get('source', ''),
            'رقم_الخبرة': self.caso, 'المرفوعة_من': pl_s, 'المرفوعة_ضد': df_s,
            'الخبير': es, 'المحافظة': info.get('governorate', ''), 'القسم': info.get('department', ''),
            'التاريخ': self.date, 'اليوم': get_day_name(self.date), 'الساعة': self.time,
            'المقر': loc.get('maqar', ''), 'الدور': loc.get('dor', ''),
            'المكتب': loc.get('maktab', ''), 'الجناح': loc.get('janah', ''), 'الجهة': gov_text,
        })
        if not gov_parties:
            QMessageBox.information(self, "تم", f"تم إنشاء الإخطار!\n\nملاحظة: لم يتم التعرّف تلقائيًا على جهة حكومية — اكتبها يدويًا.\n\n{th.ltr(path)}")
        else:
            QMessageBox.information(self, "تم", f"تم إنشاء الإخطار!\n\n{th.ltr(path)}")
        os.startfile(path)

    def _add_to_calendar(self):
        try:
            from icloud_calendar import has_credentials, add_calendar_event
            if not has_credentials():
                QMessageBox.warning(self, "تنبيه", "لا يوجد حساب iCloud مربوط — اربطه من صفحة الإعدادات أولاً")
                return
            summary = get_case_parties_summary(self.caso, self.cookies, self.user)
            time_clean = self.time[:5]
            start_dt = datetime.strptime(f"{self.date} {time_clean}", "%Y/%m/%d %H:%M")
            ok, err = add_calendar_event(f"{summary} - {self.caso}", start_dt)
            if ok:
                QMessageBox.information(self, "تم", "تمت إضافة الجلسة لتقويمك بنجاح")
            else:
                QMessageBox.critical(self, "فشل", f"تعذرت الإضافة:\n\n{err}")
        except Exception as e:
            QMessageBox.critical(self, "فشل", f"تعذرت الإضافة:\n\n{e}")


class DayDivider(QWidget):
    """فصل يوم بدفتر اليومية: رقم اليوم كبير + اسمه + التاريخ الكامل + شارة اليوم/غدًا"""
    def __init__(self, day, date, parent=None):
        super().__init__(parent)
        self.date_key = date
        d = _parse_day(date)
        today = datetime.now().date()
        is_today = (d == today)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        self.rail = RailGutter('day', today=is_today)
        outer.addWidget(self.rail)
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 18, 0, 6)
        lay.setSpacing(12)
        outer.addLayout(lay, 1)

        num = QLabel(d.strftime('%d') if d else '')
        num.setStyleSheet(f"color:{th.EMERALD if is_today else th.NAVY}; font-size:{th.FS_HERO}px; font-weight:{th.W_HEAVY}; border:none; background:transparent;")

        names = QVBoxLayout()
        names.setSpacing(0)
        day_lbl = QLabel(day)
        day_lbl.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:13px; font-weight:700; border:none; background:transparent;")
        date_lbl = QLabel(th.ltr(_disp_date(date)))
        date_lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none; background:transparent;")
        for w in (day_lbl, date_lbl):
            w.setAlignment(th.ARIGHT)
        names.addWidget(day_lbl)
        names.addWidget(date_lbl)

        lay.addWidget(num)
        lay.addLayout(names)
        if is_today:
            lay.addWidget(_pill("اليوم", th.EMERALD_BG, th.EMERALD_TEXT))
        elif d and d == today + timedelta(days=1):
            lay.addWidget(_pill("غدًا", TYPE_BADGE_BG, th.NAVY))
        lay.addStretch()


def _norm_session_date(s):
    """تاريخ الجلسة موحّد بصيغة 'YYYY-MM-DD'.

    ⚠️ نظام الوزارة يرجّع تاريخ الجلسة أحيانًا بفاصل '/' وأحيانًا '-' (نفس
    الملاحظة بweekly_report.py). المقارنة النصية بين حدّ الفترة والتاريخ
    تفشل بصمت لو التنسيقين مختلفين — فكانت الجلسات ذات التاريخ بـ'-'
    تختفي من الصفحة كلها. نوحّدها هنا مثل ما سوّاها weekly_report.
    """
    parts = (s.get('start') or '').split(' ')
    return (parts[0] if parts else '').replace('/', '-')


class SessionsPage(QWidget):
    connection_state = pyqtSignal(str)     # عرض فقط: 'ok' / 'lost' / 'none' → الشريط الجانبي
    # نتيجة الجلب تعود من الخيط الخلفي (حمولة واحدة dict)
    _sessions_ready = pyqtSignal(object)
    _sessions_failed = pyqtSignal(object)

    def __init__(self, cookies, current_user, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.cookies = cookies
        self.current_user = current_user
        self.sessions_data = []
        self.week_offset = 0
        self._title_map = {}
        # '_loading' يمنع تضاعف الخيوط، و'_load_token' يبطل نتيجة جلب قديمة
        self._loading = False
        self._load_token = 0
        self._sessions_ready.connect(self._apply_sessions)
        self._sessions_failed.connect(self._apply_sessions_error)
        self._build()

    def _build(self):
        self._day_widgets = {}
        self._now_marker = None
        self._drawer_open = False

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 26, 34, 26)
        root.setSpacing(18)

        header_row = QHBoxLayout()
        self.header = PageHeader("جدول الجلسات الأسبوعية", " ")
        report_btn = SecondaryButton("طباعة كشف الجلسات")
        report_btn.clicked.connect(self._open_weekly_report_dialog)
        header_row.addWidget(self.header)
        header_row.addStretch()
        header_row.addWidget(report_btn)
        root.addLayout(header_row)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(14)
        self.kpi_count = KPICard("جلسات قادمة", "0")
        self.kpi_no_upcoming = KPICard("بدون جلسة قادمة", "0", value_color=th.AMBER)
        self.kpi_status = KPICard("حالة الاتصال — اضغط للتحديث", "—", value_color=th.TEXT_SECONDARY)
        self.kpi_status.setCursor(Qt.CursorShape.PointingHandCursor)
        self.kpi_status.clicked.connect(self._refresh_connection_and_sessions)
        kpi_row.addWidget(self.kpi_count)
        kpi_row.addWidget(self.kpi_no_upcoming)
        kpi_row.addWidget(self.kpi_status)
        root.addLayout(kpi_row)

        self.week_strip = WeekStrip()
        self.week_strip.day_clicked.connect(self._scroll_to_day)
        root.addWidget(self.week_strip)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(2, 2, 2, 2)
        self.scroll_layout.setSpacing(0)       # الخط الزمني متصل — المسافات داخل كل صف
        self.scroll_layout.addStretch()
        self.scroll.setWidget(self.scroll_content)
        root.addWidget(self.scroll, 1)

        self._scroll_anim = QPropertyAnimation(self.scroll.verticalScrollBar(), b"value", self)
        self._scroll_anim.setDuration(280)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._now_timer = QTimer(self)
        self._now_timer.setInterval(60_000)
        self._now_timer.timeout.connect(self._place_now_marker)
        self._now_timer.start()

        if not self.cookies:
            self._show_no_login()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        def tiles(compact):
            for t in getattr(getattr(self, "week_strip", None), "tiles", []):
                t.set_compact(compact)
        _fit_page(self, tiles)

    def set_connected(self, user):
        self.current_user = user
        self.kpi_status.value_label.setText("متصل")
        self.load_sessions()

    def _open_weekly_report_dialog(self):
        if not self.cookies:
            QMessageBox.warning(self, "تنبيه", "لا يوجد اتصال حالياً")
            return
        dlg = WeeklyReportDialog(self.window(), self.cookies, self.current_user)
        dlg.exec()

    def _refresh_connection_and_sessions(self):
        self.kpi_status.value_label.setText("جاري التحديث...")
        self.kpi_status.value_label.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:22px; font-weight:600; border:none;")
        QApplication.processEvents()
        # فحص الاتصال + جلب الجلسات — كله بالخلفية (كان طلب شبكة على خيط
        # الواجهة فيجمّد النافذة). حالة الاتصال ترجع معنا وتُعرض هنا.
        if not self.cookies:
            self.kpi_status.value_label.setText("انقطع الاتصال")
            self.kpi_status.value_label.setStyleSheet(f"color:{th.DANGER}; font-size:22px; font-weight:600; border:none;")
            return
        if self._loading:
            return
        self._loading = True
        self._load_token += 1
        token = self._load_token

        today = datetime.now()
        start = (today - timedelta(days=1)).strftime('%Y-%m-%d')
        end = (today + timedelta(days=30)).strftime('%Y-%m-%d')
        sf, ef = today.strftime('%Y-%m-%d'), end

        def work():
            self._session_worker(start, end, sf, ef, token, append=False,
                                 check_connection=True)

        threading.Thread(target=work, daemon=True).start()

    def _clear_scroll(self):
        while self.scroll_layout.count() > 1:
            item = self.scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _dedupe_same_day(self, sessions_list):
        seen = set()
        result = []
        for s in sessions_list:
            key = (s.get('description', ''), s.get('start', '')[:10])
            if key in seen:
                continue
            seen.add(key)
            result.append(s)
        return result

    def _record_sessions_locally(self, sessions_list):
        for s in sessions_list or []:
            caso = s.get('description', '')
            if not caso:
                continue
            parts = s.get('start', '').split(' ')
            date = parts[0] if parts else ''
            time = parts[1] if len(parts) > 1 else ''
            title = s.get('title', '').strip().replace(caso, '').strip()
            try:
                case_db.upsert_session(caso, date, time, '', title)
            except Exception:
                pass

    def _get_title_fallback(self, caso_no):
        if caso_no in self._title_map:
            return self._title_map[caso_no]
        try:
            import re
            r = requests.post(f"{BASE_URL}/includes/basic_info_result.php",
                data={'id': '1', 'title': caso_no, 'met_date': '', 'met_time': '', 'description': caso_no},
                cookies=self.cookies, verify=False, timeout=5)
            h4s = re.findall(r'<h4[^>]*>(.*?)</h4>', r.text)
            h4s = [re.sub(r'<[^>]+>', '', h).strip() for h in h4s]
            defendant = ''
            for h in h4s:
                if 'المدعى عليه' in h:
                    defendant = h.split(':', 1)[-1].strip()
                    break
            self._title_map[caso_no] = defendant
            return defendant
        except Exception:
            self._title_map[caso_no] = ''
            return ''

    def _prefetch_titles(self, sessions_list):
        """يجلب عناوين القضايا الناقصة مسبقاً — يُنادى من الخيط الخلفي.

        السبب: بطاقة الجلسة كانت تجلب العنوان من الشبكة وقت العرض، يعني
        طلب شبكة لكل بطاقة على خيط الواجهة = تجميد النافذة. نجلبهم كلهم
        بالخلفية قبل العرض، فيبقى الكاش نظيفاً والعرض يصير فوري بلا أي
        طلب شبكة على خيط الواجهة.
        """
        for s in sessions_list or []:
            caso = s.get('description', '')
            if not caso or caso in self._title_map:
                continue
            title = (s.get('title') or '').strip().replace(caso, '').strip()
            if title:
                continue
            try:
                self._get_title_fallback(caso)
            except Exception:
                pass

    def _session_worker(self, start, end, sf, ef, token, append, check_connection=False):
        """جلب الجلسات بالخلفية — يُعيد النتيجة عبر إشارة للواجهة."""
        cookies = self.cookies
        _get_sessions = get_sessions
        connected = None

        try:
            if check_connection:
                try:
                    from api import get_logged_in_name
                    connected = bool(get_logged_in_name(cookies))
                except Exception:
                    connected = False
            all_s = _get_sessions(cookies, start, end)
            self._record_sessions_locally(all_s)
            new_s = sorted([s for s in all_s if sf <= _norm_session_date(s) <= ef],
                           key=lambda x: x.get('start', ''))
            self._prefetch_titles(new_s)
            data = self._dedupe_same_day(new_s)
        except Exception as e:
            self._emit_from_worker(self._sessions_failed,
                                   {'token': token, 'error': e, 'append': append,
                                    'connected': connected})
            return

        self._emit_from_worker(self._sessions_ready,
                               {'token': token, 'data': data, 'append': append,
                                'connected': connected})

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

    def load_sessions(self):
        """يبدأ الجلب في خيط خلفي.

        السبب: الجلب طلب شبكة (بمهلة 15 ثانية) + استدعاء عنوان لكل جلسة
        بلا عنوان — وكان كله على خيط الواجهة، فالنافذة تتجمد كاملة وقت
        الفتح. الخيط يرجع النتيجة عبر إشارة، والعرض يبقى على خيط الواجهة.
        """
        if not self.cookies:
            return
        if self._loading:
            return  # جلب جارٍ — ما نشغّل خيط ثاني
        self._loading = True
        self._load_token += 1
        token = self._load_token

        today = datetime.now()
        start = (today - timedelta(days=1)).strftime('%Y-%m-%d')
        end = (today + timedelta(days=30)).strftime('%Y-%m-%d')
        sf, ef = today.strftime('%Y-%m-%d'), end

        def work():
            self._session_worker(start, end, sf, ef, token, append=False)

        threading.Thread(target=work, daemon=True).start()

    def load_next_week(self):
        if self._loading:
            return  # جلب جارٍ — ما نشغّل خيط ثاني (وناسف عدّاد الأسبوع)
        self.week_offset += 7
        self._loading = True
        self._load_token += 1
        token = self._load_token
        week_offset = self.week_offset

        today = datetime.now()
        start = (today + timedelta(days=week_offset)).strftime('%Y-%m-%d')
        end = (today + timedelta(days=week_offset + 7)).strftime('%Y-%m-%d')
        sf, ef = start, end

        def work():
            self._session_worker(start, end, sf, ef, token, append=True)

        threading.Thread(target=work, daemon=True).start()

    def _apply_sessions(self, payload):
        """يُستدعى على خيط الواجهة (عن طريق الإشارة) — هنا فقط نلمس الـwidgets"""
        if payload.get('token') != self._load_token:
            return  # نتيجة جلب أقدم من جلب أحدث — نتجاهلها
        self._loading = False
        if payload.get('connected') is not None:
            if payload['connected']:
                self.kpi_status.value_label.setText("متصل")
                self.kpi_status.value_label.setStyleSheet(f"color:{th.EMERALD}; font-size:22px; font-weight:600; border:none;")
            else:
                self.kpi_status.value_label.setText("انقطع الاتصال")
                self.kpi_status.value_label.setStyleSheet(f"color:{th.DANGER}; font-size:22px; font-weight:600; border:none;")
        if payload.get('append'):
            self.sessions_data = self._dedupe_same_day(self.sessions_data + payload['data'])
        else:
            self.sessions_data = payload['data']
            self.week_offset = 0
        self._render()

    def _apply_sessions_error(self, payload):
        """الخطأ يوصلنا على خيط الواجهة — نفس معالجة الخطأ السابقة"""
        if payload.get('token') != self._load_token:
            return
        self._loading = False
        e = payload['error']
        if payload.get('append'):
            QMessageBox.critical(self, "خطأ", str(e))
        else:
            self._show_error(e)

    def _render(self):
        self._last_day = datetime.now().date()
        self._figures_unknown = False
        self._clear_scroll()
        self._day_widgets = {}
        self._now_marker = None

        no_upcoming = []
        try:
            no_upcoming = case_db.get_no_upcoming_cases(self.current_user)
        except Exception:
            pass
        known_upcoming = {s.get('description', '') for s in self.sessions_data}
        no_upcoming = [c for c in no_upcoming if c['caso_no'] not in known_upcoming]

        self.kpi_count.value_label.setText(str(len(self.sessions_data)))
        self.kpi_no_upcoming.value_label.setText(str(len(no_upcoming)))
        self.week_strip.set_sessions(self.sessions_data)
        # عرض فقط: ألوان صادقة بعد تحميل ناجح
        _kpi_tone(self.kpi_count, th.TEXT_PRIMARY)
        _kpi_tone(self.kpi_no_upcoming, th.AMBER if no_upcoming else th.TEXT_SECONDARY)
        if self.kpi_status.value_label.text() == "متصل":
            _kpi_tone(self.kpi_status, th.EMERALD)
        if self.cookies:
            self._conn_state = 'ok'
            self.connection_state.emit('ok')

        insert_at = self.scroll_layout.count() - 1

        if no_upcoming:
            drawer = NoUpcomingDrawer(len(no_upcoming), open_=self._drawer_open)
            drawer.toggled.connect(lambda o: setattr(self, '_drawer_open', o))
            for c in no_upcoming:
                drawer.add_row(self._build_no_upcoming_card(c))
            self.scroll_layout.insertWidget(insert_at, drawer)
            insert_at += 1

        if not self.sessions_data:
            self.scroll_layout.insertWidget(insert_at, _state_view(
                'calendar', "لا توجد جلسات قادمة", "تظهر هنا جلسات الثلاثين يومًا القادمة"))
            insert_at += 1
        else:
            cur = None
            for s in self.sessions_data:
                p = s.get('start', '').split(' ')
                date = p[0] if p else ''
                day = get_day_name(date)
                if date != cur:
                    cur = date
                    divider = DayDivider(day, date)
                    self._day_widgets[date] = divider
                    self.scroll_layout.insertWidget(insert_at, divider)
                    insert_at += 1
                card = SessionCardQt(s, self.cookies, self.current_user, self.load_sessions,
                    title_fallback_fn=self._get_title_fallback)
                self.scroll_layout.insertWidget(insert_at, card)
                insert_at += 1

        more_btn = SecondaryButton("تحميل جلسات الأسبوع القادم")
        more_btn.clicked.connect(self.load_next_week)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 16, 0, 0)
        wrap_w = QWidget()
        wrap_w.setLayout(wrap)
        wrap.addStretch()
        wrap.addWidget(more_btn)
        wrap.addStretch()
        self.scroll_layout.insertWidget(insert_at, wrap_w)

        mo.stagger([self.scroll_layout.itemAt(i).widget() for i in range(self.scroll_layout.count())
                    if isinstance(self.scroll_layout.itemAt(i).widget(), (NoUpcomingDrawer, DayDivider, SessionCardQt))])
        self._place_now_marker()


    # ---- عرض فقط: حالات الخطأ داخل القائمة بدل النافذة المنبثقة ----
    def _show_error(self, e):
        self._clear_scroll()
        self._after_clear()
        self._unknown_figures()
        if _is_network_error(e):
            _kpi_tone(self.kpi_status, th.DANGER, "انقطع الاتصال")
            self._conn_state = 'lost'
            self.connection_state.emit('lost')
            view = _state_view('offline', "لا يوجد اتصال بنظام الخبراء",
                               "تأكّد من الاتصال بشبكة الدوام ثم أعد المحاولة", retry_cb=self.load_sessions)
        else:
            view = _state_view('alert', "تعذّر تحميل الجلسات", "حدث خطأ غير متوقع أثناء قراءة البيانات",
                               retry_cb=self.load_sessions, detail=_short(e))
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, view)

    def _show_no_login(self):
        self._clear_scroll()
        self._after_clear()
        self._unknown_figures()
        _kpi_tone(self.kpi_status, th.TEXT_SECONDARY, "غير متصل")
        self._conn_state = 'none'
        self.connection_state.emit('none')
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, _state_view(
            'offline', "لا يوجد اتصال بنظام الخبراء", "سجّل الدخول من جديد لعرض الجلسات"))

    def _unknown_figures(self):
        """عرض فقط: لا أرقام كاذبة — «—» محايد بدل «0» حين لا توجد بيانات"""
        self._figures_unknown = True
        _kpi_tone(self.kpi_count, th.TEXT_SECONDARY, "—")
        _kpi_tone(self.kpi_no_upcoming, th.TEXT_SECONDARY, "—")
        self.week_strip.set_unknown()
        self._update_greeting()

    def _after_clear(self):
        self._day_widgets = {}
        self._now_marker = None

    # ---- دفتر اليومية: عرض فقط ----
    def _today_cards(self):
        today_key = datetime.now().strftime('%Y/%m/%d')
        out = []
        for i in range(self.scroll_layout.count()):
            w = self.scroll_layout.itemAt(i).widget()
            if isinstance(w, SessionCardQt) and w.date == today_key:
                out.append((i, w))
        return out

    def _update_greeting(self):
        """تحية اليوم من بيانات الجلسات المحمّلة نفسها (عرض فقط) — تتحدّث كل دقيقة"""
        lbl = getattr(self.header, "subtitle_label", None)
        if lbl is None:
            return
        if not self.cookies or getattr(self, "_figures_unknown", False):
            lbl.setText("")            # لا تحية من بيانات قديمة بجانب أرقام «—»
            return
        now = datetime.now()
        hello = "صباح الخير" if now.hour < 12 else "مساء الخير"
        today_key = now.strftime('%Y/%m/%d')
        now_hm = now.strftime('%H:%M')

        def when(s, with_day):
            p = s.get('start', '').split(' ')
            date, tm = (p[0] if p else ''), (p[1][:5] if len(p) > 1 else '')
            dh, sfx = _fmt_time(tm)
            return (f"{get_day_name(date)} " if with_day else "") + f"{dh} {sfx}".strip()

        future = [s for s in self.sessions_data
                  if (s.get('start', '')[:10] > today_key) or
                     (s.get('start', '')[:10] == today_key and s.get('start', '')[11:16] >= now_hm)]
        today = [s for s in self.sessions_data if s.get('start', '')[:10] == today_key]
        today_left = [s for s in today if s.get('start', '')[11:16] >= now_hm]

        if now.weekday() in (4, 5):
            text = "عطلة نهاية الأسبوع" + (f" — أقرب جلسة {when(future[0], True)}" if future else "")
        elif today_left:
            text = f"{hello} — لديك {_sessions_phrase(len(today))} اليوم، أقربها {when(today_left[0], False)}"
        elif today:
            text = f"{hello} — انتهت جلسات اليوم ({_sessions_phrase(len(today))})"
        elif future:
            text = f"{hello} — لا جلسات اليوم، أقربها {when(future[0], True)}"
        else:
            text = f"{hello} — لا جلسات قادمة"
        lbl.setText(text)

    def _rollover_day(self):
        """عرض فقط: لو تغيّر التاريخ والتطبيق مفتوح — يُعاد بناء شريط الأسبوع وفصول الأيام
        من البيانات المحمّلة نفسها (بلا أي جلب جديد). يرجع True لو أعاد الرسم."""
        last = getattr(self, "_last_day", None)
        if last is None or last == datetime.now().date():
            return False
        old = self.week_strip
        self.week_strip = WeekStrip()
        self.week_strip.day_clicked.connect(self._scroll_to_day)
        self.layout().replaceWidget(old, self.week_strip)
        old.deleteLater()
        self._fit_strip_now()
        self._render()
        return True

    def _fit_strip_now(self):
        compact = self.height() < COMPACT_BELOW_H
        for t in self.week_strip.tiles:
            t.set_compact(compact)

    def _place_now_marker(self):
        """يضع خط «الآن» بين جلسات اليوم ويُبهت ما مضى وقته — يُستدعى بعد الرسم وكل دقيقة"""
        if self._rollover_day():
            return
        self._update_greeting()
        if self._now_marker is not None:
            self.scroll_layout.removeWidget(self._now_marker)
        cards = self._today_cards()
        if not cards:
            if self._now_marker is not None:
                self._now_marker.hide()
            return
        now = datetime.now()
        target = None
        for idx, card in cards:
            st = card.start_dt()
            card.set_past(bool(st and st < now))
            if target is None and st and st >= now:
                target = idx
        day_done = target is None
        if target is None:
            target = cards[-1][0] + 1
        if self._now_marker is None:
            self._now_marker = NowMarker()
        self._now_marker.refresh(day_done)
        self.scroll_layout.insertWidget(target, self._now_marker)
        self._now_marker.show()

    def _scroll_to_day(self, key):
        w = self._day_widgets.get(key)
        if w is None:
            return
        bar = self.scroll.verticalScrollBar()
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(bar.value())
        self._scroll_anim.setEndValue(min(bar.maximum(), max(0, w.y() - 4)))
        self._scroll_anim.start()

    def _build_no_upcoming_card(self, info):
        caso = info.get('caso_no', '')
        title = ''
        try:
            cached = case_db.get_case(caso)
            if cached:
                title = cached.get('title', '') or ''
        except Exception:
            pass
        if not title:
            title = info.get('title', '') or self._get_title_fallback(caso)

        last_date_disp = th.ltr(_disp_date(info.get('session_date', '')))

        row = QFrame()
        row.setStyleSheet("background:transparent; border:none;")
        root = QHBoxLayout(row)
        root.setContentsMargins(20, 12, 20, 12)
        root.setSpacing(14)

        add_btn = SecondaryButton("إضافة جلسة قادمة")
        add_btn.clicked.connect(lambda: self._open_add_dialog(caso, title))

        info_lay = QVBoxLayout()
        info_lay.setSpacing(4)
        name_lbl = ElidedLabel(title or caso)
        name_lbl.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:{th.FS_TITLE}px; font-weight:{th.W_MEDIUM}; border:none;")
        name_lbl.setAlignment(th.ARIGHT)
        sub_lbl = QLabel(f"{th.ltr(caso)}  ·  آخر جلسة معروفة {last_date_disp}")
        sub_lbl.setStyleSheet(f"color:{th.DANGER_TEXT}; font-size:12px; border:none;")
        sub_lbl.setAlignment(th.ARIGHT)
        info_lay.addWidget(name_lbl)
        info_lay.addWidget(sub_lbl)

        root.addLayout(info_lay, 3)
        root.addStretch()
        root.addWidget(add_btn)
        return row

    def _open_add_dialog(self, caso, title):
        dlg = AddSessionDialog(self.window(), self.cookies, caso, title, "10:30", self.load_sessions)
        dlg.exec()

