# ===== qt_first_session.py — محضر أول جلسة (تصميم Executive الجديد) =====
# يعيد استخدام كل منطق الأعمال المعقّد من first_session.py الأصلي كما هو
# (استخراج الجلسة القادمة، فتح المحضر، بناء نصوص المهمة، تفادي تعارض
# التوقيت...) بدون أي تكرار أو تعديل — فقط طبقتا العرض (نافذة الجلسة
# القادمة والنافذة اليدوية) أُعيد بناؤهما بـ PyQt6.
import os
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QCheckBox, QMessageBox, QScrollArea, QApplication
)

import qt_theme as th
from qt_widgets import Card, PrimaryButton, SecondaryButton, SmartDateEdit, SmartTimeEdit

from config import SESSION_TYPES
from api import (get_day_name, parse_case_info, insert_session,
                  get_original_experts, get_case_parties_summary, session_exists)
from mahdar import fill_mahdar
from dates import normalize_date
from ui import get_experts
from expert_settings import load_specialty
import case_db

from first_session import (
    get_upcoming_session, find_open_record_session, compute_closing_time,
    format_date_display, build_mission_text, build_secondment_mission_text,
    insert_session_no_conflict, COURT_SESSION_CODE,
)


def ensure_case_data_qt(parent, cookies, current_user, case):
    """
    نسخة Qt من ensure_case_data — نفس التوقيع والسلوك (يرجع dict بيانات
    القضية بعد ما يخلص). لو القضية تحتاج استخراج، السحب + Gemini يشتغلون
    بـthread منفصل ونافذة التقدم تعرض المراحل — البرنامج ما يتجمد.
    بدون زر تصغير هنا: المحضر يحتاج البيانات فورًا. "إلغاء" يكمل
    بالبيانات المتوفرة حاليًا بالقاعدة.
    """
    from case_info_window import _is_resolved, NO_API_KEY_ERROR
    from qt_case_info import start_fetch_task_qt
    from qt_extraction import ExtractionProgressDialog

    caso_no = case['caso_no'].strip().upper()
    existing = case_db.get_case(caso_no)
    if _is_resolved(existing):
        return existing

    task, _ = start_fetch_task_qt(cookies, current_user, case)
    if task.window is not None:
        try:
            task.window._finish()   # كانت مفتوحة بوضع قابل للتصغير
        except RuntimeError:
            pass
    # مؤشر الانتظار (الدائرة) ما له داعي — نافذة التقدم تعرض الحالة
    while QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()
    dlg = ExtractionProgressDialog(parent, task, allow_minimize=False)
    dlg.exec()

    if task.state == "finished" and task.error == NO_API_KEY_ERROR:
        QMessageBox.warning(parent, "⚠️ لا يوجد ربط بالذكاء الاصطناعي",
            "لم تُستخرج بيانات حكم الإحالة لأنه لا يوجد مفتاح Gemini "
            "محفوظ بصفحة الإعدادات.\n\n"
            "سيُفتح المحضر بالمعلومات المتوفرة فقط. اربط المفتاح من "
            "صفحة الإعدادات، وأعد المحاولة لاستخراج البيانات تلقائيًا.")
    return case_db.get_case(caso_no) or {}


def open_first_session_window_qt(parent, cookies, current_user, caso_no, received_date, case_data=None):
    """نقطة الدخول — نفس توقيع open_first_session_window الأصلية"""
    controller = FirstSessionControllerQt(
        parent, cookies, current_user, caso_no, received_date, case_data=case_data)
    controller.run()


def print_first_session_qt(parent, case, cookies, current_user):
    """
    نسخة Qt من pending_cases.print_first_session — يتأكد من بيانات
    القضية أولاً (ensure_case_data_qt) ثم يفتح نافذة محضر أول جلسة.
    هذي نقطة الدخول اللي يستدعيها زر "محضر أول جلسة" بصفحة القضايا المتداولة.
    """
    case_data = ensure_case_data_qt(parent, cookies, current_user, case)
    open_first_session_window_qt(
        parent, cookies, current_user,
        case['caso_no'], case['received_date'], case_data=case_data
    )


class NextSessionDialogQt(QDialog):
    """نافذة إدخال الجلسة القادمة (تاريخ + وقت) قبل فتح المحضر — نسخة Qt"""
    def __init__(self, parent, caso_no, case_name, is_secondment, default_time="10:30"):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("إضافة الجلسة القادمة")
        self.setFixedWidth(440)
        self.setStyleSheet(f"background:{th.BG};")
        self.is_secondment = is_secondment
        self.result_date = ""
        self.result_time = ""
        self.result_by_original = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        banner = Card(bg=th.BLUE_INFO_BG, border=th.BLUE_INFO_BG)
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(14, 10, 14, 10)
        t = QLabel(caso_no)
        t.setStyleSheet(f"color:{th.BLUE_INFO_TEXT}; font-weight:700; font-size:13px; border:none;")
        t.setAlignment(th.ARIGHT)
        s = QLabel((case_name or '')[:44])
        s.setStyleSheet(f"color:{th.BLUE_INFO_TEXT}; font-size:11px; border:none;")
        s.setAlignment(th.ARIGHT)
        bl.addWidget(t)
        bl.addWidget(s)
        root.addWidget(banner)

        note = QLabel("حدد تاريخ ووقت الجلسة القادمة — ستُسجَّل بالنظام كجلسة مناقشة ثم يُفتح المحضر.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        note.setAlignment(th.ARIGHT)
        root.addWidget(note)

        row = QHBoxLayout()
        date_col = QVBoxLayout()
        date_lbl = QLabel("التاريخ")
        date_lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:11px; border:none;")
        date_lbl.setAlignment(th.ARIGHT)
        self.date_edit = SmartDateEdit()
        date_col.addWidget(date_lbl)
        date_col.addWidget(self.date_edit)

        time_col = QVBoxLayout()
        time_lbl = QLabel("التوقيت")
        time_lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:11px; border:none;")
        time_lbl.setAlignment(th.ARIGHT)
        self.time_edit = SmartTimeEdit(default_time)
        time_col.addWidget(time_lbl)
        time_col.addWidget(self.time_edit)

        row.addLayout(date_col)
        row.addLayout(time_col)
        root.addLayout(row)

        self.orig_checkbox = None
        if is_secondment:
            self.orig_checkbox = QCheckBox("محددة من الخبير الأصلي")
            self.orig_checkbox.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.orig_checkbox.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:12px;")
            root.addWidget(self.orig_checkbox)

        btns = QHBoxLayout()
        cancel = SecondaryButton("إلغاء")
        cancel.clicked.connect(self.reject)
        save = PrimaryButton("حفظ وفتح المحضر")
        save.clicked.connect(self._submit)
        btns.addWidget(save)
        btns.addStretch()
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _submit(self):
        dv = self.date_edit.get_value().strip()
        tv = self.time_edit.get_value().strip()
        if not dv:
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال التاريخ")
            return
        if not tv:
            QMessageBox.warning(self, "تنبيه", "يرجى إدخال التوقيت")
            return
        self.result_date = dv
        self.result_time = tv
        self.result_by_original = self.orig_checkbox.isChecked() if self.orig_checkbox else False
        self.accept()


class FirstSessionManualDialog(QDialog):
    """
    النافذة الكاملة — تظهر فقط لو ناقص شي يحتاج إدخال يدوي (نفس فلسفة
    الأصل: أغلب الحالات تمر بالمسار الصامت بدون ما تظهر هذي النافذة إطلاقاً)
    """
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"محضر أول جلسة — {controller.caso_no}")
        self.setFixedWidth(560)
        self.setMinimumHeight(600)
        self.setStyleSheet(f"background:{th.BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(f"background:{th.NAVY};")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 0, 20, 0)
        h_title = QLabel(f"محضر أول جلسة — {controller.caso_no}")
        h_title.setStyleSheet("color:white; font-size:14px; font-weight:700; border:none;")
        h_lay.addWidget(h_title)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.form_lay = QVBoxLayout(content)
        self.form_lay.setContentsMargins(22, 18, 22, 18)
        self.form_lay.setSpacing(4)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        c = controller
        if c.is_secondment:
            self._build_secondment_fields(c)
        else:
            self._build_asala_fields(c)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{th.BORDER}; margin-top:14px; margin-bottom:14px;")
        self.form_lay.addWidget(sep)

        if c.upcoming:
            kind = "جلسة محكمة" if c.upcoming['is_court_session'] else "جلسة عادية"
            info_txt = (f"الجلسة القادمة المضافة بالنظام: {kind}\n"
                        f"{format_date_display(c.upcoming['date'])} الساعة {c.upcoming['time']}")
        else:
            info_txt = "⚠ لا توجد جلسة قادمة مضافة بالنظام — يرجى وضعها بالنظام أولاً، أو تعبئة الحقول بالأسفل يدويًا"

        info_lbl = QLabel(info_txt)
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(f"color:{th.DANGER}; font-size:11px; font-weight:700; border:none;")
        info_lbl.setAlignment(th.ARIGHT)
        self.form_lay.addWidget(info_lbl)
        self.form_lay.addSpacing(10)

        self.new_date_edit = None
        self.new_time_edit = None
        if not c.is_secondment:
            self._label("تاريخ الجلسة الجديدة")
            self.new_date_edit = SmartDateEdit(
                initial=c.upcoming['date'] if c.upcoming else "",
                danger=bool(c.upcoming))
            self.form_lay.addWidget(self.new_date_edit)
            self.form_lay.addSpacing(10)

            self._label("ساعة الجلسة الجديدة")
            self.new_time_edit = SmartTimeEdit(
                initial=c.upcoming['time'] if c.upcoming else "10:00",
                danger=bool(c.upcoming))
            self.form_lay.addWidget(self.new_time_edit)
            self.form_lay.addSpacing(10)

        submit_btn = PrimaryButton("🖨  إصدار المحضر")
        submit_btn.clicked.connect(self._generate_manual)
        self.form_lay.addSpacing(16)
        self.form_lay.addWidget(submit_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.form_lay.addStretch()

    def _label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:12px; font-weight:700; border:none;")
        lbl.setAlignment(th.ARIGHT)
        self.form_lay.addWidget(lbl)
        self.form_lay.addSpacing(4)
        return lbl

    def _build_asala_fields(self, c):
        self._label("تاريخ صدور الحكم (DD/MM/YYYY)")
        self.judgment_date_entry = QLineEdit()
        self.judgment_date_entry.setPlaceholderText("مثال: 20/05/2025")
        self.judgment_date_entry.setStyleSheet(f"""
            QLineEdit {{ background:white; border:1px solid {th.BORDER}; border-radius:10px;
                padding:9px 12px; font-size:13px; }}
        """)
        self.judgment_date_entry.setAlignment(th.ARIGHT)
        if c.case_data.get('judgment_date'):
            self.judgment_date_entry.setText(c.case_data['judgment_date'])
        self.form_lay.addWidget(self.judgment_date_entry)
        self.form_lay.addSpacing(14)

        is_court_preview = bool(c.upcoming and c.upcoming['is_court_session'])
        hearing_label = "التاريخ المحدد من المحكمة لحضور الطرفين أمام الخبرة"
        if is_court_preview:
            hearing_label += "  (تلقائي = تاريخ الجلسة القادمة)"
        self._label(hearing_label)

        self.hearing_date_entry = QLineEdit()
        self.hearing_date_entry.setPlaceholderText("مثال: 17/06/2025")
        border = th.DANGER if is_court_preview else th.BORDER
        self.hearing_date_entry.setStyleSheet(f"""
            QLineEdit {{ background:white; border:1px solid {border}; border-radius:10px;
                padding:9px 12px; font-size:13px; color:{th.DANGER if is_court_preview else th.TEXT_PRIMARY}; }}
        """)
        self.hearing_date_entry.setAlignment(th.ARIGHT)
        if is_court_preview:
            self.hearing_date_entry.setText(format_date_display(c.upcoming['date']))
            self.hearing_date_entry.setEnabled(False)
        elif c.case_data.get('hearing_date'):
            self.hearing_date_entry.setText(c.case_data['hearing_date'])
        self.form_lay.addWidget(self.hearing_date_entry)

    def _build_secondment_fields(self, c):
        self._label("نوع الخبير المستعين (هندسي/حسابي)")
        self.requesting_type_entry = QLineEdit()
        self.requesting_type_entry.setPlaceholderText("مثال: الحسابي")
        self.requesting_type_entry.setStyleSheet(f"""
            QLineEdit {{ background:white; border:1px solid {th.DANGER}; border-radius:10px;
                padding:9px 12px; font-size:13px; color:{th.DANGER}; }}
        """)
        self.requesting_type_entry.setAlignment(th.ARIGHT)
        if c.case_data.get('requesting_expert_type'):
            self.requesting_type_entry.setText(c.case_data['requesting_expert_type'])
        self.form_lay.addWidget(self.requesting_type_entry)
        self.form_lay.addSpacing(10)

        self._label("اسم الخبير المستعين (مُستخرج من سجل الحركة، عدّله لو غير دقيق)")
        self.requesting_name_entry = QLineEdit()
        self.requesting_name_entry.setPlaceholderText("اسم الخبير")
        self.requesting_name_entry.setStyleSheet(f"""
            QLineEdit {{ background:white; border:1px solid {th.DANGER}; border-radius:10px;
                padding:9px 12px; font-size:13px; color:{th.DANGER}; }}
        """)
        self.requesting_name_entry.setAlignment(th.ARIGHT)
        if c.case_data.get('requesting_expert_name'):
            self.requesting_name_entry.setText(c.case_data['requesting_expert_name'])
        self.form_lay.addWidget(self.requesting_name_entry)
        self.form_lay.addSpacing(10)

        self._label("الشق التخصصي")
        self.specialty_entry = QLineEdit()
        self.specialty_entry.setPlaceholderText("مثال: حاسب آلي")
        self.specialty_entry.setStyleSheet(f"""
            QLineEdit {{ background:white; border:1px solid {th.BORDER}; border-radius:10px;
                padding:9px 12px; font-size:13px; }}
        """)
        self.specialty_entry.setAlignment(th.ARIGHT)
        saved_specialty = load_specialty()
        if saved_specialty:
            self.specialty_entry.setText(saved_specialty)
        self.form_lay.addWidget(self.specialty_entry)
        self.form_lay.addSpacing(10)

        self._label("نص المأمورية (يدوي — لا يوجد استخراج تلقائي حاليًا)")
        self.mission_box = QTextEdit()
        self.mission_box.setFixedHeight(100)
        self.mission_box.setStyleSheet(f"""
            QTextEdit {{ background:white; border:1px solid {th.BORDER}; border-radius:10px;
                padding:8px 10px; font-size:12px; }}
        """)
        self.mission_box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        if c.case_data.get('mission_text'):
            self.mission_box.setPlainText(c.case_data['mission_text'])
        self.form_lay.addWidget(self.mission_box)

    def _generate_manual(self):
        c = self.controller
        new_date_raw = new_time = None
        if not c.is_secondment:
            new_date_raw = self.new_date_edit.get_value().strip()
            new_time = self.new_time_edit.get_value().strip()
            if not new_date_raw or not new_time:
                QMessageBox.warning(self, "تنبيه", "يرجى إدخال تاريخ وساعة الجلسة الجديدة")
                return
        elif c.upcoming:
            new_date_raw = c.upcoming['date']
            new_time = c.upcoming['time']

        if c.is_secondment:
            requesting_type = self.requesting_type_entry.text().strip()
            specialty = self.specialty_entry.text().strip()
            mission_raw = self.mission_box.toPlainText().strip()

            orig = get_original_experts(c.cookies, c.caso_no)
            original_names = orig.get('names', [])
            original_type = requesting_type or orig.get('type_label', '')

            if not original_names:
                manual_name = self.requesting_name_entry.text().strip()
                if not manual_name:
                    QMessageBox.warning(self, "تنبيه", "تعذر تحديد الخبير المستعين — يرجى إدخاله يدويًا")
                    return
                original_names = [manual_name]

            if c.secondment_by_original is not None:
                date_specified = c.secondment_by_original
            else:
                date_specified = bool(c.upcoming)

            mission_text = build_secondment_mission_text(
                original_names, original_type, specialty, mission_raw,
                c.opening_time, date_specified, new_date_raw, new_time
            )
        else:
            judgment_date = self.judgment_date_entry.text().strip()
            hearing_date = self.hearing_date_entry.text().strip()
            if not judgment_date or not hearing_date:
                QMessageBox.warning(self, "تنبيه", "يرجى إدخال تاريخ صدور الحكم والتاريخ المحدد من المحكمة")
                return
            received_display = datetime.strptime(c.received_date, '%Y-%m-%d').strftime('%d/%m/%Y')
            mission_text = build_mission_text(
                judgment_date, hearing_date, c.opening_time,
                received_date=received_display,
                new_date_raw=new_date_raw, new_time=new_time
            )

        if not mission_text:
            QMessageBox.critical(self, "خطأ", "تعذر بناء نص المهمة — تحقق من الحقول")
            return

        c._finalize(mission_text, new_date_raw, new_time, manual_dialog=self)


class FirstSessionControllerQt:
    """
    المتحكّم الرئيسي — يقابل FirstSessionWindow الأصلية بالكامل، بس بدون
    وراثة من أي ودجت مرئي: النافذة اليدوية (FirstSessionManualDialog)
    تُبنى وتُعرض فقط لو فعلاً احتجناها؛ أغلب الحالات (وجود جلسة قادمة +
    بيانات أصالة كاملة) تمر بمسار صامت 100% بدون أي نافذة تظهر إطلاقًا —
    نفس فلسفة "الزر الواحد" بالأصل تمامًا.
    """
    def __init__(self, parent, cookies, current_user, caso_no, received_date,
                 opening_time='10:00', case_data=None):
        self.parent = parent
        self.cookies = cookies
        self.current_user = current_user
        self.caso_no = caso_no
        self.received_date = received_date
        self.opening_time = opening_time
        self.case_data = case_data or {}

        self.open_record = find_open_record_session(self.cookies, self.caso_no, self.received_date)
        self.upcoming = get_upcoming_session(self.cookies, self.caso_no, self.received_date)
        self.is_secondment = self.case_data.get('case_type') == 'استعانة'
        self.secondment_by_original = None
        self._manual_dialog = None

    def run(self):
        if self.upcoming is None:
            proceed = self._ensure_next_session()
            if not proceed:
                return  # المستخدم ألغى نافذة الجلسة القادمة — لا نكمل
        self._route_after_upcoming()

    def _hearing_is_past(self):
        hearing_date = (self.case_data.get('hearing_date') or '').strip()
        if not hearing_date:
            return None
        try:
            h = datetime.strptime(hearing_date, '%d/%m/%Y').date()
            r = datetime.strptime(self.received_date, '%Y-%m-%d').date()
            return h < r
        except Exception:
            return None

    def _ensure_next_session(self):
        case_name = self.case_data.get('case_name') or self.caso_no

        if self.is_secondment:
            return self._ask_next_session(case_name, is_secondment=True)

        past = self._hearing_is_past()
        if past is None:
            return True  # بيانات ناقصة — نكمل للنافذة اليدوية الكاملة

        if past:
            return self._ask_next_session(case_name, is_secondment=False)

        hearing_date = self.case_data.get('hearing_date', '').strip()
        try:
            court_date_raw = datetime.strptime(hearing_date, '%d/%m/%Y').strftime('%Y/%m/%d')
        except Exception:
            return True

        # خط دفاع: لو الجلسة هذي مضافة أصلاً بالنظام (مثلاً إعادة فتح/
        # طباعة محضر أول جلسة لنفس القضية)، ما نعيد إضافتها — insert_session_no_conflict
        # لوحده ما يميّز "مضافة أصلاً" عن "تعارض حقيقي" ويزيح الوقت
        # ويضيف جلسة ثانية مكررة بالغلط.
        if session_exists(self.cookies, self.caso_no, court_date_raw, '12:00'):
            self.upcoming = {'date': court_date_raw, 'time': '12:00', 'is_court_session': True}
            return True

        result, final_time = insert_session_no_conflict(
            self.cookies, self.caso_no, court_date_raw, '12:00', COURT_SESSION_CODE)
        self.upcoming = {'date': court_date_raw, 'time': final_time, 'is_court_session': True}
        if result == '1':
            self._sync_calendar_silent(court_date_raw, final_time)
        return True

    def _ask_next_session(self, case_name, is_secondment):
        dlg = NextSessionDialogQt(self.parent, self.caso_no, case_name, is_secondment)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        self._on_next_session_submitted(dlg.result_date, dlg.result_time, dlg.result_by_original)
        return True

    def _on_next_session_submitted(self, date_raw, time_str, by_original):
        discussion_code = SESSION_TYPES.get('مناقشة', next(iter(SESSION_TYPES.values())))

        # خط دفاع: نفس الفكرة — لو الجلسة هذي مضافة أصلاً بالنظام،
        # ما نكررها.
        if session_exists(self.cookies, self.caso_no, date_raw, time_str):
            self.upcoming = {'date': date_raw, 'time': time_str, 'is_court_session': False}
            self.secondment_by_original = by_original
            self._sync_calendar_silent(date_raw, time_str)
            QMessageBox.information(self.parent, "تم", "هذي الجلسة مضافة فعلاً بالنظام مسبقاً — ما راح نكررها.")
            return

        conflict_flag = {'hit': False}

        def note():
            conflict_flag['hit'] = True

        result, final_time = insert_session_no_conflict(
            self.cookies, self.caso_no, date_raw, time_str,
            discussion_code, on_conflict_note=note)

        if result == '1':
            self.upcoming = {'date': date_raw, 'time': final_time, 'is_court_session': False}
            self.secondment_by_original = by_original
            self._sync_calendar_silent(date_raw, final_time)
            extra = ""
            if conflict_flag['hit']:
                extra = f"\n\nكانت هناك جلسة بنفس الوقت، فتم ضبط الوقت إلى {final_time} تلقائيًا."
            QMessageBox.information(self.parent, "تم", f"تمت إضافة الجلسة القادمة بالنظام.{extra}")
        else:
            warnings = {
                '2': 'تعذر تسجيل الجلسة (خطأ عام).',
                '5': 'هذا اليوم إجازة بالنظام.',
                '6': 'يجب أن يكون التاريخ بعد 7 أيام على الأقل حسب قواعد النظام.',
            }
            msg = warnings.get(result, f'نتيجة غير متوقعة من النظام: {result}')
            QMessageBox.warning(self.parent, "تنبيه",
                f"{msg}\n\nسيُفتح المحضر، لكن راجع جدولة الجلسة يدويًا لو لزم.")
            self.upcoming = {'date': date_raw, 'time': time_str, 'is_court_session': False}
            self.secondment_by_original = by_original

    def _sync_calendar_silent(self, date_raw, time_str):
        try:
            from icloud_calendar import has_credentials, add_calendar_event
            if has_credentials():
                summary = get_case_parties_summary(self.caso_no, self.cookies, self.current_user)
                start_dt = datetime.strptime(f"{date_raw} {time_str}", "%Y/%m/%d %H:%M")
                add_calendar_event(f"{summary} - {self.caso_no}", start_dt)
        except Exception:
            pass

    def _route_after_upcoming(self):
        if self.is_secondment:
            can_auto = False
            judgment_date = hearing_date = ''
        else:
            judgment_date = self.case_data.get('judgment_date', '')
            hearing_date = self.case_data.get('hearing_date', '')
            can_auto = bool(judgment_date and hearing_date and self.upcoming)

        if can_auto:
            received_display = datetime.strptime(self.received_date, '%Y-%m-%d').strftime('%d/%m/%Y')
            new_date_raw = self.upcoming['date']
            new_time = self.upcoming['time']
            mission_text = build_mission_text(
                judgment_date, hearing_date, self.opening_time,
                received_date=received_display,
                new_date_raw=new_date_raw, new_time=new_time
            )
            self._finalize(mission_text, new_date_raw, new_time)
        else:
            self._manual_dialog = FirstSessionManualDialog(self, self.parent)
            self._manual_dialog.exec()

    def _finalize(self, mission_text, new_date_raw=None, new_time=None, manual_dialog=None):
        owner = manual_dialog or self.parent
        if not mission_text:
            QMessageBox.critical(owner, "خطأ", "تعذر بناء نص المهمة — تحقق من الحقول")
            return

        try:
            if not self.upcoming:
                type_code = SESSION_TYPES.get('مناقشة', next(iter(SESSION_TYPES.values())))
                if session_exists(self.cookies, self.caso_no, new_date_raw, new_time):
                    # مضافة أصلاً بالنظام — لا نكرر الإضافة
                    result = '1'
                else:
                    try:
                        result = insert_session(self.cookies, self.caso_no, new_date_raw, new_time, type_code)
                    except Exception:
                        result = None

                warnings = {
                    '2': 'تعذر تسجيل الجلسة الجديدة بالنظام (خطأ عام).',
                    '3': 'تعارض بالتوقيت مع جلسة أخرى بالنظام.',
                    '4': 'يوجد جلسة حجز بنفس الفترة بالنظام.',
                    '5': 'هذا اليوم إجازة بالنظام.',
                    '6': 'يجب أن يكون التاريخ بعد 7 أيام على الأقل من اليوم حسب قواعد النظام.',
                }
                if result in warnings:
                    QMessageBox.warning(owner, "تنبيه بجدولة الجلسة",
                        f"{warnings[result]}\n\nسيُصدَر المحضر رغم ذلك، لكن يرجى إضافة الجلسة "
                        f"يدويًا من صفحة الجلسات لو لم تُسجَّل.")
                elif result == '1':
                    try:
                        from icloud_calendar import has_credentials, add_calendar_event
                        if has_credentials():
                            summary = get_case_parties_summary(self.caso_no, self.cookies, self.current_user)
                            start_dt = datetime.strptime(f"{new_date_raw} {new_time}", "%Y/%m/%d %H:%M")
                            add_calendar_event(f"{summary} - {self.caso_no}", start_dt)
                        else:
                            QMessageBox.warning(owner, "تنبيه",
                                "لم تُضَف الجلسة لتقويم آيفونك — لا يوجد حساب iCloud مربوط.\n\n"
                                "اربط حسابك من صفحة الإعدادات لتفعيل المزامنة التلقائية.")
                    except Exception:
                        pass

            if manual_dialog:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

            info = parse_case_info(self.caso_no, self.cookies, self.current_user)

            exps = get_experts(self.caso_no, self.cookies, self.current_user)
            if exps:
                chairs = [x for x in exps if x['role'] == 'رئيس لجنة']
                members = [x for x in exps if x['role'] != 'رئيس لجنة']
                if len(exps) == 1:
                    es = exps[0]['name']
                elif len(exps) >= 3 and chairs:
                    es = f"{members[0]['name']}  ،  {chairs[0]['name']}  ،  {members[1]['name'] if len(members) > 1 else ''}"
                else:
                    es = '  ،  '.join([x['name'] for x in exps])
            else:
                es = self.current_user

            def clean_spaces(n):
                return ' '.join(n.split())

            plaintiffs = self.case_data.get('plaintiffs') or info.get('plaintiffs', [])
            defendants = self.case_data.get('defendants') or info.get('defendants', [])
            court_case_number = self.case_data.get('court_case_number') or info.get('case_num', '')

            pl = [clean_spaces(p) for p in plaintiffs]
            pl_s = pl[0] if len(pl) == 1 else '\n'.join([f"{i+1}- {p}" for i, p in enumerate(pl)])
            df = [clean_spaces(d) for d in defendants]
            df_s = df[0] if len(df) == 1 else '\n'.join([f"{i+1}- {d}" for i, d in enumerate(df)])

            if self.open_record and self.open_record.get('date'):
                session1_date_raw = self.open_record['date']
                session1_time = self.open_record['time'] or self.opening_time
                need_insert_open_record = False
            else:
                received_dt = datetime.strptime(self.received_date, '%Y-%m-%d')
                session1_date_raw = received_dt.strftime('%Y/%m/%d')
                session1_time = self.opening_time
                need_insert_open_record = True
                # خط دفاع أخير: find_open_record_session تبحث بسجل
                # الحركة، وممكن تتأخر بالتحديث. نتأكد كمان من تقويم
                # الجلسات مباشرة قبل ما نضيف فتح محضر مكرر.
                if session_exists(self.cookies, self.caso_no, session1_date_raw, session1_time):
                    need_insert_open_record = False

            if need_insert_open_record:
                open_code = SESSION_TYPES.get('فتح محضر', '150004')
                try_time = session1_time
                for _ in range(60):
                    try:
                        res = insert_session(self.cookies, self.caso_no, session1_date_raw, try_time, open_code)
                    except Exception:
                        res = None
                    if res == '1':
                        session1_time = try_time
                        break
                    if res in ('3', '4'):
                        t = datetime.strptime(try_time, '%H:%M') + timedelta(minutes=1)
                        try_time = t.strftime('%H:%M')
                        continue
                    break

            day_name = get_day_name(session1_date_raw)
            date_str = datetime.strptime(session1_date_raw, '%Y/%m/%d').strftime('%d/%m/%Y')

            # المحافظة/القسم: من النظام أولاً، وإلا من إعدادات الخبير — عشان
            # شخص من قسم ثاني يقدر يطبع المحضر باسم محافظته (2026-11-09).
            from expert_settings import resolve_report_header
            gov, dep = resolve_report_header(info)

            data = {
                'رقم_المحضر': '1',
                'اليوم': day_name,
                'التاريخ': date_str,
                'رقم_الخبرة': self.caso_no,
                'الساعة': session1_time,
                'المحافظة': gov,
                'القسم': dep,
                'رقم_الدعوى': court_case_number,
                'الواردة_من': info.get('source', ''),
                'المرفوعة_من': pl_s,
                'المرفوعة_ضد': df_s,
                'الخبير': es,
                'نص_الحضور': 'لم يحضر أحد.',
                'نص_المهمة': mission_text,
            }

            from expert_settings import minute_path
            out_path = minute_path(self.caso_no, 1)          # «مستندات_النظام\محضر الخبرة رقم 1.docx»
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            fill_mahdar(out_path, data)

            if manual_dialog:
                QApplication.restoreOverrideCursor()
            try:
                os.startfile(out_path)
            except Exception:
                pass
            if manual_dialog:
                manual_dialog.accept()
            else:
                QMessageBox.information(owner, "تم",
                    f"تم إصدار المحضر بنجاح:\n{th.ltr(out_path)}")

        except PermissionError:
            if manual_dialog:
                QApplication.restoreOverrideCursor()
            QMessageBox.critical(owner, "الملف مفتوح",
                "هذا الملف مفتوح حاليًا ببرنامج آخر (Word غالبًا).\n\n"
                "أغلق الملف أولاً، ثم حاول إصدار المحضر مرة ثانية.")
        except Exception as e:
            if manual_dialog:
                QApplication.restoreOverrideCursor()
            QMessageBox.critical(owner, "خطأ", f"تعذر إصدار المحضر:\n{e}")
