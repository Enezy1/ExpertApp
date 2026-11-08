# ===== qt_expert_reports.py — «تقارير الخبراء»: قضايا شركات الاتصالات (المرحلة 1) =====
# قائمة بطاقات للقضايا المتداولة التي مدعيتها إحدى شركات الإعدادات.
# الضغط على بطاقة يفتح شاشة صغيرة ببيانات القضية وزر «ابدأ كتابة تقرير».
# شكل القائمة: qt_report_card.py (تصميم design/) + reports_list_model.py (بيانات البطاقة).
# المرحلة 2و: الزر ينشئ مجلد القضية + case.json ويفتح «صفحة القضية» (qt_case_page.CasePageDialog؛ المنطق من qt_case_track).
import json
import os
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QDialog,
    QMessageBox, QPushButton, QButtonGroup, QRadioButton, QFileDialog, QFrame, QLineEdit,
)

import qt_theme as th
from qt_widgets import PrimaryButton, SecondaryButton
import qt_icons
import qt_report_card as rc
import reports_list_model as rlm

import telecom_config
import telecom_reports
import case_workspace
import reports_root_setup
from qt_case_page import CasePageDialog


STARTFILE = None          # الاختبارات تستبدله؛ الافتراضي os.startfile


def open_case_folder(base):
    """يفتح مجلد القضية في مستكشف ويندوز (os.startfile) — لا شيء غيره. يرجع True إن فتح."""
    if not base or not os.path.isdir(base):
        return False
    (STARTFILE or os.startfile)(base)
    return True


def _fmt(d):
    d = (d or '').strip()
    return d.replace('-', '/') if d else '—'


_PREFS = os.path.join(os.path.dirname(telecom_config.ini_path()), 'expert_reports_prefs.json')


def _load_only_telecom():
    try:
        with open(_PREFS, encoding='utf-8') as f:
            return bool(json.load(f).get('only_telecom', True))
    except (OSError, ValueError, AttributeError):
        return True


def _save_only_telecom(v):
    try:
        with open(_PREFS, 'w', encoding='utf-8') as f:
            json.dump({'only_telecom': bool(v)}, f)
    except OSError:
        pass


class CaseDetailDialog(QDialog):
    """بيانات القضية + زر «ابدأ كتابة تقرير» (نقطة دخول المرحلة 2)."""

    def __init__(self, case, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"قضية {case['caso_no']}")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        rows = [
            ("رقم الخبرة", case['caso_no']),
            ("الرقم الآلي", case.get('autocase_no') or '—'),
            ("المدعية", case.get('plaintiff') or case['company'] or '—'),
            ("الشركة", case['company'] or '—'),
            ("المدعى عليه", '، '.join(case.get('defendants') or []) or '—'),
            ("تاريخ الاستلام", _fmt(case.get('received_date'))),
            ("عنوان القضية", case.get('title') or '—'),
        ]
        for k, v in rows:
            l = QLabel(f"<b>{k}:</b> {v}")
            l.setWordWrap(True)
            l.setAlignment(th.ARIGHT)
            l.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:13px; border:none;")
            lay.addWidget(l)
        lay.addSpacing(8)
        self.case = case
        self.start_btn = PrimaryButton("ابدأ كتابة تقرير")
        self.start_btn.clicked.connect(self._start_report)
        row = QHBoxLayout()
        row.addWidget(self.start_btn)
        row.addStretch()
        close = SecondaryButton("إغلاق")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)


    def _start_report(self):
        if not reports_root_setup.has_saved_root():
            if RootChoiceDialog(self).exec() != QDialog.DialogCode.Accepted:
                return
        try:
            base, data = case_workspace.ensure_workspace(self.case)
        except case_workspace.WorkspaceError as e:
            QMessageBox.critical(self, "تعذّر إنشاء مجلد القضية", str(e))
            return
        except OSError as e:
            QMessageBox.critical(self, "تعذّر إنشاء مجلد القضية", th.ltr(e))
            return
        CasePageDialog(base, data, self, cookies=getattr(self.parent(), 'cookies', None)).exec()


class RootChoiceDialog(QDialog):
    """أول استخدام: اختيار مكان حفظ تقارير الخبرة (يُغيَّر لاحقاً من الإعدادات)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("مكان حفظ تقارير الخبرة")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        intro = QLabel("أين تريد حفظ مجلدات القضايا؟ يمكنك تغييره لاحقاً من الإعدادات.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self._group = QButtonGroup(self)
        for i, (label, path) in enumerate(reports_root_setup.suggest_roots()):
            rb = QRadioButton(f"{label}\n{path}")
            rb.setProperty('root', path)
            self._group.addButton(rb, i)
            lay.addWidget(rb)
            if i == 0:
                rb.setChecked(True)
        self._custom = None
        other = SecondaryButton("اختيار مجلد آخر…")
        other.clicked.connect(self._pick_other)
        lay.addWidget(other)
        row = QHBoxLayout()
        ok = PrimaryButton("حفظ ومتابعة")
        ok.clicked.connect(self._accept)
        cancel = SecondaryButton("إلغاء")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addStretch()
        row.addWidget(cancel)
        lay.addLayout(row)

    def _pick_other(self):
        d = QFileDialog.getExistingDirectory(self, "اختر مجلداً")
        if not d:
            return
        path = os.path.normpath(os.path.join(d, reports_root_setup.FOLDER_NAME))
        rb = QRadioButton(f"مجلد مختار\n{path}")
        rb.setProperty('root', path)
        self._group.addButton(rb)
        self.layout().insertWidget(self.layout().count() - 2, rb)
        rb.setChecked(True)

    def _accept(self):
        rb = self._group.checkedButton()
        try:
            reports_root_setup.save_choice(rb.property('root') if rb else '')
        except case_workspace.WorkspaceError as e:
            QMessageBox.warning(self, "مكان غير صالح", str(e))
            return
        except OSError as e:
            QMessageBox.critical(self, "تعذّر الحفظ", th.ltr(e))
            return
        self.accept()


class ExpertReportsPage(QWidget):
    """شاشة القائمة. الشكل في qt_report_card، والمنطق في reports_list_model.
    (2026-10-25) كل المتداولة تُجلب مرة واحدة للجلسة (telecom_reports.fetch_all) وتُحفظ في الذاكرة؛ التبديل بين «كل
    القضايا» و«نزاعات الاتصالات فقط» تصفية محلية فورية (filter_cases) بلا طلبات. الجلب يتجدد بزر «تحديث البيانات» فقط
    (وعند فتح البرنامج من جديد). القضية الغامضة العنوان تظهر فور تحديد مدعيتها من النظام (parse_case_info بالخلفية)."""
    _loaded = pyqtSignal(str, object)     # (token, result dict | Exception)
    _case_done = pyqtSignal(str, object)  # (token, (قضية محدَّثة، بطاقتها))

    def __init__(self, cookies, current_user, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        rc.load_plex()
        self.setObjectName('expertReportsPage')
        self.setStyleSheet(f"QWidget#expertReportsPage{{background:{rc.SURFACE};}} QLabel,QPushButton,QLineEdit{{{rc.base_qss()}}}")
        self.cookies = cookies
        self.current_user = current_user
        self._token = ''
        self._built = False
        self._result = None
        self._all = None                  # نتيجة fetch_all في الذاكرة للجلسة (لا كاش على القرص)
        self._vms = {}                    # رقم القضية ← بطاقتها (تُبنى بالخلفية مرة واحدة)
        self._cards = []                  # بطاقات الفلتر الحالي (قبل البحث)
        self._loaded.connect(self._on_loaded)
        self._case_done.connect(self._on_case_done)
        self._build()
        from PyQt6.QtCore import QTimer
        self._relist = QTimer(self)       # قضايا تتحدد تباعاً: إعادة عرض واحدة كل 250ms لا لكل قضية
        self._relist.setSingleShot(True)
        self._relist.setInterval(250)
        self._relist.timeout.connect(self._apply_filter)

    def _build(self):
        # الصفحة كلها تتمرر بشريط واحد: العنوان والمؤشرات والفلاتر والبطاقات داخل نفس المنطقة
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;} QScrollArea>QWidget>QWidget{background:transparent;}"
            "QScrollBar:vertical{background:transparent; width:10px; margin:0;}"
            "QScrollBar::handle:vertical{background:#c4c6cc; border-radius:5px; min-height:30px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        content = QWidget()
        content.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(34, 26, 34, 26)
        root.setSpacing(14)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel("منصة إنشاء التقارير")
        self.title.setStyleSheet(f"font-size:26px; font-weight:700; color:{rc.INK}; border:none;")
        self.count = QLabel("")
        self.count.setStyleSheet(f"font-size:13px; color:{rc.INK_SOFT}; border:none;")
        titles.addWidget(self.title)
        titles.addWidget(self.count)
        head.addLayout(titles)
        head.addStretch()
        self.conn = QLabel("")            # يظهر فقط عند خطأ اتصال حقيقي
        self.conn.setStyleSheet(f"font-size:12px; color:{rc.ERROR}; background:{rc.ERROR_SOFT};"
                                f"border-radius:10px; padding:3px 12px;")
        self.conn.hide()
        head.addWidget(self.conn)
        self.refresh_btn = QPushButton("تحديث البيانات")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setIcon(qt_icons.icon('refresh', rc.INK))
        self.refresh_btn.setStyleSheet(
            f"QPushButton{{background:{th.BTN2_BG}; color:{th.NAVY}; border:1px solid {th.BTN2_BORDER};"
            f"border-radius:{rc.R_LG}px; padding:8px 16px; font-size:13px; font-weight:700;}}"
            f"QPushButton:hover{{background:{th.BTN2_HOVER};}}")
        self.refresh_btn.clicked.connect(self.reload)
        head.addWidget(self.refresh_btn)
        root.addLayout(head)

        self.kpi_row = QHBoxLayout()
        self.kpi_row.setSpacing(14)
        root.addLayout(self.kpi_row)

        bar = QFrame()
        bar.setObjectName('filters')
        bar.setStyleSheet(rc.card_frame_qss('filters'))
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.setSpacing(8)
        self.only_telecom = _load_only_telecom()
        self.tg_telecom = QPushButton("نزاعات الاتصالات فقط")
        self.tg_all = QPushButton("كل القضايا")
        for b, v in ((self.tg_telecom, True), (self.tg_all, False)):
            b.setCheckable(True)
            b.setChecked(self.only_telecom == v)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=v: self._set_mode(v))
            bl.addWidget(b)
        self._style_toggle()
        bl.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث برقم القضية أو الاسم…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(280)
        self.search.setStyleSheet(
            f"QLineEdit{{background:#f1f4f7; border:1px solid transparent; border-radius:{rc.R_LG}px;"
            f"padding:8px 12px; font-size:13px; color:{rc.INK};}}"
            f"QLineEdit:focus{{background:{rc.CARD}; border:1px solid {rc.SECONDARY};}}")
        self.search.textChanged.connect(self._render_list)
        bl.addWidget(self.search)
        root.addWidget(bar)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{rc.GRAY_TEXT}; font-size:12px; border:none;")
        self.status.setAlignment(th.ARIGHT)
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.list_lay = QVBoxLayout()
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(12)
        root.addLayout(self.list_lay)
        root.addStretch(1)

    def _style_toggle(self):
        for b in (self.tg_telecom, self.tg_all):
            on = b.isChecked()
            b.setStyleSheet(
                f"QPushButton{{padding:7px 16px; font-size:13px; font-weight:{700 if on else 500};"
                f"border:none; border-radius:{rc.R_LG}px;"
                f"color:{'white' if on else rc.INK_SOFT}; background:{rc.PRIMARY_DARK if on else rc.CONTAINER};}}")

    def _set_mode(self, only):
        self.tg_telecom.setChecked(only)
        self.tg_all.setChecked(not only)
        self._style_toggle()
        if only != self.only_telecom:
            self.only_telecom = only
            _save_only_telecom(only)
            self._apply_filter()                      # تصفية محلية فورية: لا جلب من النظام

    def showEvent(self, e):
        super().showEvent(e)
        if not self._built:
            self._built = True
            self.reload()

    # ---------- جلب (خيط خلفي) — مرة واحدة للجلسة، ويتجدد بزر «تحديث البيانات» فقط ----------
    def reload(self, *_):
        self._token = str(id(object()))
        token = self._token
        self._result = None
        self._all = None
        self._vms = {}
        self._clear()
        self.conn.hide()
        if not self.cookies:
            self.status.setText("لا يوجد اتصال بنظام الخبراء — سجّل الدخول ثم اضغط تحديث.")
            return
        self.status.setText("⏳ جاري التحميل...")
        threading.Thread(target=self._work, args=(token,), daemon=True).start()

    def _work(self, token):
        def ready(res):                               # المرحلة الأولى (العنوان والمحفوظ): تُعرض فوراً
            snap = {'all': [dict(c) for c in res['all']], 'total': res['total'], 'configured': res['configured'],
                    '_vms': {c['caso_no']: rlm.build_card(self._card_case(c)) for c in res['all']}}
            self._loaded.emit(token, snap)

        def one(case):                                # قضية غامضة تحدّدت مدعيتها: تظهر فور تحديدها
            self._case_done.emit(token, (case, rlm.build_card(self._card_case(case))))
        try:
            telecom_reports.fetch_all(self.cookies, on_ready=ready, on_case=one, stop=lambda: token != self._token)
        except Exception as e:
            self._loaded.emit(token, e)

    @staticmethod
    def _card_case(e):
        return {k: e.get(k) for k in ('caso_no', 'autocase_no', 'title', 'received_date', 'company', 'plaintiff',
                                      'defendants', 'source')}

    @staticmethod
    def _build_vms(cases):
        out = []
        for c in cases:
            out.append(rlm.build_card(c))
        return out

    def _on_loaded(self, token, result):
        if token != self._token:
            return
        if isinstance(result, Exception):
            self.status.setText(f"تعذّر تحميل القضايا (تحقق من الاتصال ثم اضغط تحديث): {th.ltr(result)}")
            self.conn.setText("تعذّر الاتصال بنظام الخبراء")
            self.conn.show()
            return
        self._vms = result.pop('_vms', {}) or {}
        self._all = result
        self._apply_filter()

    def _on_case_done(self, token, payload):
        if token != self._token or self._all is None:
            return
        case, vm = payload
        for i, c in enumerate(self._all['all']):
            if c['caso_no'] == case['caso_no']:
                self._all['all'][i] = case
        self._vms[case['caso_no']] = vm
        self._relist.start()

    def _apply_filter(self):
        """التصفية المحلية للنتيجة المحفوظة (بلا طلبات): «كل القضايا» أو «نزاعات الاتصالات فقط»."""
        if self._all is None:
            return
        res = telecom_reports.filter_cases(self._all, self.only_telecom)
        self._result = res
        self._cards = [self._vms[c['caso_no']] for c in res['cases'] if c['caso_no'] in self._vms]
        self._render_header(res)
        self._render_list()

    # ---------- عرض ----------
    def _clear(self):
        while self.list_lay.count():
            w = self.list_lay.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _render_header(self, res):
        k = rlm.kpis(self._cards)
        self.count.setText(f"{k['active']} قضية")
        while self.kpi_row.count():
            w = self.kpi_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        for title, val, alert in (("القضايا النشطة", k['active'], False),
                                  ("قيد إعداد التقرير", k['preparing'], False),
                                  ("تنتظر إجراءً مني", k['needs_me'], k['needs_me'] > 0)):
            self.kpi_row.addWidget(rc.StatCard(title, val, alert), 1)
        msg = f"{len(res['cases'])} قضية من {res['total']} متداولة"
        if res.get('resolving'):
            msg += f" — ⏳ جاري تحديد المدعية في {res['resolving']} قضية"
        if res['unresolved']:
            msg += f" — تعذّر تحديد المدعية في {res['unresolved']} قضية (اضغط تحديث لإعادة المحاولة)"
        self.status.setText(msg)

    def _render_list(self, *_):
        res = self._result
        if res is None:
            return
        self._clear()
        if self.only_telecom and not res['configured']:
            self.status.setText("لا توجد شركات في قسم [telecom_companies] داخل gemini_network.ini.")
            return
        if res['total'] == 0:
            self.status.setText("لم تُرجع القضايا المتداولة أي قضية — إن كان هذا غير متوقع فتحقق من الاتصال ثم اضغط تحديث.")
            return
        shown = rlm.search(self._cards, self.search.text())
        if not shown:
            empty = QLabel("لا نتائج مطابقة للبحث" if self._cards else
                           ("لا توجد قضايا لشركات الاتصالات" if self.only_telecom else "لا توجد قضايا"))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color:{rc.GRAY_TEXT}; font-size:14px; padding:50px; border:none;")
            self.list_lay.insertWidget(0, empty)
            return
        for i, vm in enumerate(shown):
            card = rc.ReportCaseCard(vm)
            card.open_track.connect(lambda v: CaseDetailDialog(v['case'], self)._start_report())
            card.open_documents.connect(self._open_documents)
            self.list_lay.insertWidget(i, card)

    def _open_documents(self, vm):
        """أيقونة المجلد الصغيرة: تفتح مجلد القضية في مستكشف ويندوز فقط (2026-10-21)."""
        open_case_folder(vm['base'])
