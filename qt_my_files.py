# ===== qt_my_files.py — «الملف الآلي»: الملف الآلي + الإجراءات للخبير لقضاياه فقط =====
# طبقة عرض فقط فوق منطق موجود أصلاً — لا منطق أعمال جديد:
#   • القضايا الحالية  ← get_pending_cases + get_reserved_cases (رصيد الخبير نفسه)
#   • المنجزة          ← case_stats.run_full_scan/build_report_data (نفس كشف الإحصائية)
#   • الملف الآلي والإجراءات ← نوافذ CaseLookupPage (بحث رئيس القسم) بدون تكرار كود.
# الحماية: لا خانة إدخال رقم قضية هنا؛ القائمة تُبنى من حساب الخبير نفسه فقط،
# فلا يصل لقضية غيره.
import threading
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QMessageBox,
    QLineEdit, QComboBox, QApplication,
)

import qt_theme as th
from qt_widgets import Card, Badge, PrimaryButton, SecondaryButton, PageHeader

import case_stats
from pending_cases import get_pending_cases, get_reserved_cases
from qt_case_lookup import CaseLookupPage

MODE_CURRENT, MODE_DONE = 'current', 'done'
PERIODS = ["آخر 12 شهرًا", "من 12 إلى 24 شهرًا مضت", "من 24 إلى 36 شهرًا مضت"]


def _fmt(d):
    """يقبل YYYY-MM-DD أو DD/MM/YYYY أو datetime ويرجّع YYYY/MM/DD"""
    if isinstance(d, datetime):
        return d.strftime('%Y/%m/%d')
    d = (d or '').strip()
    for f in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(d, f).strftime('%Y/%m/%d')
        except Exception:
            pass
    return d or '—'


class MyFilesPage(QWidget):
    _loaded = pyqtSignal(str, object)     # (token, rows | Exception)
    _progress = pyqtSignal(str)

    def __init__(self, cookies, current_user, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.cookies = cookies
        self.current_user = current_user
        self.mode = MODE_CURRENT
        self._rows = []
        self._token = ''
        # حقول تحتاجها نوافذ CaseLookupPage المُعاد استخدامها
        self._last_caso_no = None
        self._last_autocase_no = None
        self._loaded.connect(self._on_loaded)
        self._progress.connect(self._on_progress)
        self._built = False
        self._build()

    # ---------- واجهة ----------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 26, 34, 26)
        root.setSpacing(14)

        head_row = QHBoxLayout()
        head_row.addWidget(PageHeader(
            "الملف الآلي",
            "الملف الآلي وإجراءات كل قضية من قضاياك — عرض وتنزيل وطباعة"))
        head_row.addStretch()
        refresh = SecondaryButton("↻  تحديث")
        refresh.clicked.connect(self.reload)
        head_row.addWidget(refresh)
        root.addLayout(head_row)

        tabs = QHBoxLayout()
        self.btn_current = PrimaryButton("القضايا الحالية")
        self.btn_done = SecondaryButton("المنجزة")
        self.btn_current.clicked.connect(lambda: self._set_mode(MODE_CURRENT))
        self.btn_done.clicked.connect(lambda: self._set_mode(MODE_DONE))
        self.period = QComboBox()
        self.period.addItems(PERIODS)
        self.period.currentIndexChanged.connect(self.reload)
        self.period.hide()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث برقم القضية أو عنوانها…")
        self.search.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.search.setStyleSheet(f"""
            QLineEdit {{ background:white; border:1px solid {th.BORDER}; border-radius:10px;
                padding:8px 12px; font-size:13px; }}
            QLineEdit:focus {{ border:1px solid {th.NAVY}; }}
        """)
        self.search.textChanged.connect(self._render)
        tabs.addWidget(self.btn_current)
        tabs.addWidget(self.btn_done)
        tabs.addWidget(self.period)
        tabs.addStretch()
        tabs.addWidget(self.search, 1)
        root.addLayout(tabs)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:12px; border:none;")
        self.status.setAlignment(th.ARIGHT)
        root.addWidget(self.status)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        self.list_lay = QVBoxLayout(content)
        self.list_lay.setContentsMargins(2, 2, 2, 2)
        self.list_lay.setSpacing(10)
        self.list_lay.addStretch()
        self.scroll.setWidget(content)
        root.addWidget(self.scroll, 1)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._built and self.cookies:
            self._built = True
            self.reload()

    def _set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        self.btn_current.setStyleSheet(th.primary_button_style() if mode == MODE_CURRENT else th.secondary_button_style())
        self.btn_done.setStyleSheet(th.primary_button_style() if mode == MODE_DONE else th.secondary_button_style())
        self.period.setVisible(mode == MODE_DONE)
        self.reload()

    # ---------- جلب البيانات (خيط خلفي) ----------
    def reload(self, *_):
        if not self.cookies:
            return
        token = f"{self.mode}:{self.period.currentIndex()}:{datetime.now().timestamp()}"
        self._token = token
        self._rows = []
        self._render()
        self.status.setText("⏳ جاري التحميل...")
        mode, idx = self.mode, self.period.currentIndex()
        threading.Thread(target=self._work, args=(token, mode, idx), daemon=True).start()

    def _work(self, token, mode, idx):
        try:
            if mode == MODE_CURRENT:
                rows = []
                for c in get_pending_cases(self.cookies):
                    rows.append({'caso_no': c['caso_no'], 'title': c.get('title', ''),
                                 'autocase_no': c.get('autocase_no', ''),
                                 'date': _fmt(c.get('received_date')), 'badge': 'متداولة'})
                for c in get_reserved_cases(self.cookies):
                    rows.append({'caso_no': c['caso_no'], 'title': c.get('title', ''),
                                 'autocase_no': c.get('autocase_no', ''),
                                 'date': _fmt(c.get('received_date')), 'badge': 'محجوزة'})
            else:
                today = datetime.now()
                end = today - timedelta(days=365 * idx)
                start = end - timedelta(days=365)
                case_stats.run_full_scan(
                    self.cookies, self.current_user, date_from=start, date_to=end,
                    progress_cb=lambda i, t, n: self._progress.emit(
                        f"⏳ جاري فحص القضايا... {i}/{t}") if self._token == token else None)
                # نقرأ كل المفحوص حتى end ثم نفلتر بتاريخ الإنجاز (لا الإحالة)
                _, completed, _ = case_stats.build_report_data(
                    datetime(2000, 1, 1), end, cookies=self.cookies, current_user=self.current_user)
                sf, ef = start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')
                rows = []
                for c in completed:
                    cd = c.get('completion_date') or ''
                    if sf <= cd <= ef:
                        rows.append({'caso_no': c['caso_no'], 'title': c.get('title', ''),
                                     'autocase_no': '', 'date': _fmt(cd),
                                     'badge': 'منجزة', 'sort': cd})
                rows.sort(key=lambda r: r['sort'], reverse=True)
            self._loaded.emit(token, rows)
        except Exception as e:
            self._loaded.emit(token, e)

    def _on_progress(self, text):
        self.status.setText(text)

    def _on_loaded(self, token, result):
        if token != self._token:
            return                    # نتيجة قديمة (المستخدم بدّل التبويب)
        if isinstance(result, Exception):
            self.status.setText("")
            QMessageBox.critical(self, "خطأ", f"تعذّر تحميل القضايا:\n{th.ltr(result)}")
            return
        self._rows = result
        self.status.setText(f"{len(result)} قضية")
        self._render()

    # ---------- عرض ----------
    def _clear(self):
        while self.list_lay.count() > 1:
            w = self.list_lay.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _render(self, *_):
        self._clear()
        q = self.search.text().strip().lower()
        rows = [r for r in self._rows
                if not q or q in r['caso_no'].lower() or q in (r['title'] or '').lower()]
        if not rows:
            empty = QLabel("لا توجد قضايا" if not self.status.text().startswith("⏳") else "")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:14px; padding:50px; border:none;")
            self.list_lay.insertWidget(0, empty)
            return
        for i, r in enumerate(rows):
            self.list_lay.insertWidget(i, self._card(r))

    def _card(self, r):
        card = Card()
        lay = QHBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)

        title = r['caso_no'] + (f"  ·  {r['title'][:55]}" if r['title'] else "")
        t = QLabel(title)
        t.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:600; border:none;")
        t.setAlignment(th.ARIGHT)
        lay.addWidget(t, 1)

        if r['badge'] == 'منجزة':
            lay.addWidget(Badge("منجزة", th.EMERALD_BG, th.EMERALD_TEXT))
            when = f"أُنجزت {r['date']}"
        elif r['badge'] == 'محجوزة':
            lay.addWidget(Badge("محجوزة", th.BLUE_INFO_BG, th.BLUE_INFO_TEXT))
            when = f"استلام {r['date']}"
        else:
            when = f"استلام {r['date']}"
        d = QLabel(when)
        d.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:11px; border:none;")
        lay.addWidget(d)

        files_btn = PrimaryButton("📁 الملف الآلي")
        files_btn.clicked.connect(lambda _=False, x=r: self._open_files(x))
        acts_btn = SecondaryButton("📝 الإجراءات")
        acts_btn.clicked.connect(lambda _=False, x=r: self._open_actions(x))
        lay.addWidget(files_btn)
        lay.addWidget(acts_btn)
        return card

    # ---------- فتح الملف الآلي / الإجراءات (إعادة استخدام نوافذ بحث القضية) ----------
    def _bind(self, r):
        self._last_caso_no = r['caso_no']
        autocase = r.get('autocase_no') or ''
        if not autocase:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                autocase = case_stats.get_autocase_no(r['caso_no'], self.cookies)
            finally:
                QApplication.restoreOverrideCursor()
            r['autocase_no'] = autocase
        self._last_autocase_no = autocase

    def _open_files(self, r):
        self._bind(r)
        CaseLookupPage._pick_and_download(self)

    def _open_actions(self, r):
        self._bind(r)
        CaseLookupPage._show_actions_note(self)
