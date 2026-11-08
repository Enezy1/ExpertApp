# ===== qt_case_info.py — معلومات القضية (تصميم Executive الجديد) =====
# يعيد استخدام كامل منطق case_info_window.py الأصلي (الاستخراج بالذكاء
# الاصطناعي، تصحيح التاريخ، الحفظ بالقاعدة) بدون أي تعديل — فقط طبقة
# العرض (شاشة المراجعة اليدوية الكاملة) جديدة بالكامل بـPyQt6.
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QMessageBox, QScrollArea, QApplication, QFileDialog
)

import qt_theme as th
from qt_widgets import Card, PrimaryButton, SecondaryButton

import case_db
from case_info_window import (
    _is_resolved, _fetch_and_extract, extract_from_pdf,
    autocorrect_hearing_date, NO_API_KEY_ERROR, _finalize_fetch, _judgments_dir,
)
from extraction_tasks import IN_PROGRESS, DONE, ERROR, SKIPPED
from qt_extraction import task_manager, show_progress


def start_fetch_task_qt(cookies, current_user, case, force_ai=False):
    """
    يبدأ سحب حكم الإحالة + Gemini بـthread منفصل (أو يرجع العملية الشغالة
    أصلاً لنفس القضية). الحفظ بالقاعدة يتم بالـmain thread عبر _finalize_fetch.
    يرجع (task, is_new).
    """
    caso_no = case['caso_no'].strip().upper()
    save_dir = _judgments_dir()

    def worker(progress):
        return _fetch_and_extract(cookies, current_user, case, save_dir, progress, force_ai=force_ai)

    return task_manager().start(('fetch', caso_no), caso_no, worker, _finalize_fetch)


_OPEN_DIALOGS = []


def _open_dialog(parent, cookies, current_user, case, status):
    """غير حاجبة: البرنامج يبقى قابلاً للاستخدام أثناء فتح تفاصيل القضية (طلب الخبير 2026-10-19)."""
    from PyQt6.QtCore import Qt
    dlg = CaseInfoDialogQt(parent, cookies, current_user, case, initial_status=status)
    dlg.setModal(False)
    dlg.setWindowModality(Qt.WindowModality.NonModal)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    _OPEN_DIALOGS.append(dlg)
    dlg.destroyed.connect(lambda *_a, d=dlg: _OPEN_DIALOGS.remove(d) if d in _OPEN_DIALOGS else None)
    dlg.show()
    dlg.raise_()
    return dlg


def open_case_info_window_qt(parent, cookies, current_user, case):
    """
    القضية محلولة بالقاعدة -> الشاشة تنفتح فورًا. غير كذا -> نافذة التقدم
    (الواجهة ما تتجمد)، والشاشة تنفتح تلقائيًا أول ما يخلص الاستخراج —
    إلا لو الخبير ضغط "تصغير"، فيطلع Toast بزر "فتح القضية".
    """
    caso_no = case['caso_no'].strip().upper()
    if _is_resolved(case_db.get_case(caso_no)):
        _open_dialog(parent, cookies, current_user, case, "✅ القضية موجودة بالقاعدة")
        return

    task, is_new = start_fetch_task_qt(cookies, current_user, case)
    if is_new:
        task.on_toast_open = lambda: _open_dialog(parent, cookies, current_user, case, task.summary)

        def _when_done():
            if not task.minimized:
                _open_dialog(parent, cookies, current_user, case, task.summary)
        task.done.connect(_when_done)
    show_progress(parent, task, allow_minimize=True)


class CaseInfoDialogQt(QDialog):
    def __init__(self, parent, cookies, current_user, case, initial_status=None):
        super().__init__(parent)
        self._initial_status = initial_status
        self.cookies = cookies
        self.current_user = current_user
        self.case = case
        self.caso_no = case['caso_no'].strip().upper()
        self._last_status = "⏳ جاري التحميل..."

        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"معلومات القضية — {self.caso_no}")
        self.setFixedWidth(600)
        self.setMinimumHeight(700)
        self.setStyleSheet(f"background:{th.BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(f"background:{th.NAVY};")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 0, 20, 0)
        h_title = QLabel(f"معلومات القضية — {self.caso_no}")
        h_title.setStyleSheet("color:white; font-size:14px; font-weight:700; border:none;")
        h_lay.addWidget(h_title)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(20, 16, 20, 16)
        self.body_lay.setSpacing(4)
        scroll.setWidget(self.body)
        root.addWidget(scroll, 1)

        self.status_lbl = QLabel(self._last_status)
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; font-weight:700; border:none;")
        self.status_lbl.setAlignment(th.ARIGHT)
        self.body_lay.addWidget(self.status_lbl)

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(150, self._load_or_fetch)

    def _clear_body(self):
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _field(self, label_text, multiline=False, height=70):
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:12px; font-weight:700; border:none;")
        lbl.setAlignment(th.ARIGHT)
        self.body_lay.addSpacing(10)
        self.body_lay.addWidget(lbl)
        self.body_lay.addSpacing(4)

        if multiline:
            widget = QTextEdit()
            widget.setFixedHeight(height)
            widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            widget.setStyleSheet(f"""
                QTextEdit {{ background:white; border:1px solid {th.BORDER}; border-radius:10px;
                    padding:8px 10px; font-size:12px; }}
            """)
        else:
            widget = QLineEdit()
            widget.setAlignment(th.ARIGHT)
            widget.setStyleSheet(f"""
                QLineEdit {{ background:white; border:1px solid {th.BORDER}; border-radius:10px;
                    padding:9px 12px; font-size:13px; }}
                QLineEdit:focus {{ border:1px solid {th.NAVY}; }}
            """)
        self.body_lay.addWidget(widget)
        return widget

    def _render_form(self):
        self._clear_body()

        info = Card()
        info_lay = QVBoxLayout(info)
        info_lay.setContentsMargins(14, 10, 14, 10)
        info_lay.setSpacing(2)
        t = QLabel(f"{self.caso_no}  ·  {(self.case.get('title', '') or '')[:40]}")
        t.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:13px; font-weight:700; border:none;")
        t.setAlignment(th.ARIGHT)
        d = QLabel(f"تاريخ المباشرة: {self.case.get('received_date', '')}")
        d.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        d.setAlignment(th.ARIGHT)
        info_lay.addWidget(t)
        info_lay.addWidget(d)
        self.body_lay.addWidget(info)

        self.status_lbl = QLabel(self._last_status)
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; font-weight:700; border:none;")
        self.status_lbl.setAlignment(th.ARIGHT)
        self.body_lay.addSpacing(8)
        self.body_lay.addWidget(self.status_lbl)

        self.court_no_entry = self._field("رقم القضية بالمحكمة")
        self.judgment_date_entry = self._field("تاريخ صدور الحكم (DD/MM/YYYY)")
        self.hearing_date_entry = self._field("التاريخ المحدد لحضور الخصوم (DD/MM/YYYY)")
        self.plaintiffs_box = self._field("المدعي / المدعون (كل اسم بسطر)", multiline=True, height=60)
        self.defendants_box = self._field("المدعى عليهم (كل اسم بسطر)", multiline=True, height=60)
        self.mission_box = self._field("المأمورية", multiline=True, height=120)

        data = case_db.get_case(self.caso_no)
        if data:
            self.court_no_entry.setText(data.get('court_case_number') or '')
            self.judgment_date_entry.setText(data.get('judgment_date') or '')
            self.hearing_date_entry.setText(data.get('hearing_date') or '')
            self.plaintiffs_box.setPlainText('\n'.join(data.get('plaintiffs') or []))
            self.defendants_box.setPlainText('\n'.join(data.get('defendants') or []))
            self.mission_box.setPlainText(data.get('mission_text') or '')

        btn_row = QHBoxLayout()
        retry_btn = SecondaryButton("🔄 إعادة المحاولة")
        retry_btn.clicked.connect(self._retry_fetch)
        # لو الاستخراج العادي (OCR داخلي/OCR.space ثم نص للذكاء) طلع فيه خطأ: كل صفحات الحكم صورًا للذكاء مباشرة
        full_ai_btn = SecondaryButton("🤖 قراءة كاملة بالذكاء")
        full_ai_btn.setToolTip("يرسل كل صفحات حكم الإحالة صورًا للذكاء الاصطناعي مباشرة (Gemini أولًا) — "
                               "بدون القراءة الداخلية ولا OCR.space ولا قص الصفحات. أبطأ وأدق")
        full_ai_btn.clicked.connect(self._retry_full_ai)
        upload_btn = SecondaryButton("📎 رفع حكم إحالة يدويًا")
        upload_btn.clicked.connect(self._upload_manual)
        save_btn = PrimaryButton("💾 حفظ")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        btn_row.addWidget(upload_btn)
        btn_row.addWidget(full_ai_btn)
        btn_row.addWidget(retry_btn)
        self.body_lay.addSpacing(16)
        self.body_lay.addLayout(btn_row)
        self.body_lay.addStretch()

    def _load_or_fetch(self):
        if self._initial_status:
            # جاية من عملية استخراج خلصت للتو — نعرض النتيجة مباشرة
            self._last_status = self._initial_status
            self._render_form()
            return
        existing = case_db.get_case(self.caso_no)
        if _is_resolved(existing):
            self._last_status = "✅ القضية موجودة بالقاعدة"
            self._render_form()
            return
        self._fetch_and_render("⏳ جاري البحث عن حكم الإحالة بالنظام...")

    def _retry_fetch(self):
        self._fetch_and_render("⏳ جاري إعادة المحاولة (سحب الحكم من جديد)...")

    def _retry_full_ai(self):
        self._fetch_and_render("⏳ قراءة كاملة بالذكاء: كل صفحات الحكم صورًا للذكاء الاصطناعي...", force_ai=True)

    def _fetch_and_render(self, loading_status, force_ai=False):
        """الجلب بـthread منفصل — النتيجة توصل لـ_on_task_done بالـmain thread"""
        self.status_lbl.setText(loading_status)
        task, is_new = start_fetch_task_qt(self.cookies, self.current_user, self.case, force_ai=force_ai)
        self._attach(task, is_new)

    def _attach(self, task, is_new):
        if is_new:
            parent = self.parentWidget()
            task.on_toast_open = lambda: _open_dialog(
                parent, self.cookies, self.current_user, self.case, task.summary)
        task.done.connect(self._on_task_done)
        show_progress(self, task, allow_minimize=True)

    def _on_task_done(self):
        task = self.sender()
        try:
            self._last_status = task.summary
            self._render_form()
        except RuntimeError:
            pass  # الشاشة انقفلت قبل ما تخلص العملية

    def _upload_manual(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر ملف حكم الإحالة (PDF)", "", "PDF files (*.pdf)")
        if not path:
            return
        import case_folder
        case_folder.adopt_manual_judgment(self.case, path)      # مجلد القضية هو الأصل: يُنسخ قبل القراءة
        self.status_lbl.setText("⏳ جاري قراءة الملف المرفوع بالذكاء الاصطناعي...")
        case, user, caso_no = self.case, self.current_user, self.caso_no

        def worker(progress):
            # بالـthread — Gemini فقط، بدون أي لمس للواجهة أو القاعدة
            progress(0, SKIPPED, "ملف مرفوع يدويًا — لا حاجة للسحب من الملف الآلي")
            progress(1, IN_PROGRESS)
            data, error = extract_from_pdf(path)
            progress(1, ERROR if error else DONE, error or "")
            if error:
                return None, error
            progress(2, IN_PROGRESS)
            judgment_date = data.get('تاريخ_الحكم', '')
            hearing_date = data.get('تاريخ_حضور_الخصوم', '')
            hearing_date, _corrected = autocorrect_hearing_date(judgment_date, hearing_date)
            fields = dict(
                autocase_no=case.get('autocase_no', ''),
                expert_name=user,
                title=case.get('title', ''),
                received_date=case.get('received_date', ''),
                court_case_number=data.get('رقم_القضية', ''),
                judgment_date=judgment_date,
                hearing_date=hearing_date,
                mission_text=data.get('المأمورية', ''),
            )
            progress(2, DONE)
            progress(3, IN_PROGRESS)
            fields['plaintiffs'] = data.get('المدعون', [])
            fields['defendants'] = data.get('المدعى_عليهم', [])
            progress(3, DONE)
            return fields, None

        def finalize(task):
            # بالـmain thread — نفس منطق الحفظ السابق
            if task.error:
                task.summary = f"❌ فشل الاستخراج بالذكاء الاصطناعي: {th.ltr(task.error)}"
                task.success = False
                return
            case_db.save_case(caso_no, **task.result)
            task.summary = "✅ تم الاستخراج من الملف المرفوع بنجاح"
            task.success = True

        task, is_new = task_manager().start(('upload', caso_no), caso_no, worker, finalize)
        self._attach(task, is_new)

    def _save(self):
        plaintiffs = [p.strip() for p in self.plaintiffs_box.toPlainText().split('\n') if p.strip()]
        defendants = [d.strip() for d in self.defendants_box.toPlainText().split('\n') if d.strip()]
        case_db.save_case(self.caso_no,
            autocase_no=self.case.get('autocase_no', ''),
            expert_name=self.current_user,
            title=self.case.get('title', ''),
            received_date=self.case.get('received_date', ''),
            court_case_number=self.court_no_entry.text().strip(),
            judgment_date=self.judgment_date_entry.text().strip(),
            hearing_date=self.hearing_date_entry.text().strip(),
            plaintiffs=plaintiffs,
            defendants=defendants,
            mission_text=self.mission_box.toPlainText().strip(),
        )
        QMessageBox.information(self, "✅ تم", "تم حفظ بيانات القضية بنجاح")
