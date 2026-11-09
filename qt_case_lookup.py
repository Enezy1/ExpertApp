# ===== qt_case_lookup.py — بحث قضية (رئيس القسم فقط) =====
# أداة بحث عامة عن أي رقم خبرة: مين عنده القضية حاليًا (فرد/لجنة، أصالة/
# استعانة)، هل منجزة ومتى، أو الجلسة القادمة لو لسه ما خلصت، + سحب حكم
# الإحالة من الملف الآلي مباشرة. تعتمد بالكامل على case_stats.py
# (get_case_snapshot/get_autocase_no/get_upcoming_session_for_case)
# ودوكيومنتس.py (get_referral_judgment_for_case) بدون أي منطق أعمال
# جديد هنا — فقط طبقة عرض.
import os

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QApplication, QDialog, QTextEdit
)

import qt_theme as th
from qt_widgets import Card, PrimaryButton, SecondaryButton, PageHeader

from case_stats import (
    get_case_snapshot, get_autocase_no, get_upcoming_session_for_case,
    build_case_actions_text, get_case_actions,
)
from pending_cases import get_title_fallback

USER_ID = "309"


def _switch_to_english():
    """يحوّل لغة الإدخال للنافذة الحالية إلى الإنجليزية (ويندوز فقط، بصمت لو فشل)"""
    try:
        import ctypes
        u = ctypes.windll.user32
        hkl = u.LoadKeyboardLayoutW("00000409", 1)
        hwnd = u.GetForegroundWindow()
        u.PostMessageW(hwnd, 0x0050, 0, hkl)  # WM_INPUTLANGCHANGEREQUEST
    except Exception:
        pass


_TMP_DIR = None
_TMP_CACHE = {}


def cleanup_temp_previews():
    """يمسح ملفات المعاينة المؤقتة (تُستدعى عند إغلاق البرنامج + كنس بقايا الجلسات السابقة عند التشغيل)"""
    import shutil
    global _TMP_DIR
    if _TMP_DIR:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
        _TMP_DIR = None
    _TMP_CACHE.clear()


def _sweep_old_previews():
    import glob, shutil, tempfile
    for d in glob.glob(os.path.join(tempfile.gettempdir(), "expert_preview_*")):
        shutil.rmtree(d, ignore_errors=True)


import atexit
_sweep_old_previews()
atexit.register(cleanup_temp_previews)


def _fetch_temp_pdf(cookies, doc):
    """ينزّل المستند لمجلد مؤقت (للمعاينة/الطباعة فقط — لا يظهر للمستخدم) ويرجع مساره"""
    import tempfile
    global _TMP_DIR
    if _TMP_DIR is None or not os.path.isdir(_TMP_DIR):
        _TMP_DIR = tempfile.mkdtemp(prefix="expert_preview_")
        _TMP_CACHE.clear()
    path = _TMP_CACHE.get(doc['doc_id'])
    if path and os.path.exists(path):
        return path
    from documents import download_judgment_pdf
    path = os.path.join(_TMP_DIR, f"{len(_TMP_CACHE) + 1}.pdf")
    download_judgment_pdf(cookies, doc['doc_id'], path)
    _TMP_CACHE[doc['doc_id']] = path
    _trim_temp_cache(keep=path)
    return path


_TMP_MAX_BYTES = 150 * 1024 * 1024   # سقف المجلد المؤقت: عند تجاوزه تُحذف الأقدم أولًا


def _trim_temp_cache(keep):
    items = []
    for did, pth in list(_TMP_CACHE.items()):
        try:
            st = os.stat(pth)
            items.append((st.st_mtime, st.st_size, did, pth))
        except OSError:
            _TMP_CACHE.pop(did, None)
    total = sum(i[1] for i in items)
    for _, size, did, pth in sorted(items):
        if total <= _TMP_MAX_BYTES:
            break
        if pth == keep:
            continue
        try:
            os.remove(pth)
        except OSError:
            continue
        _TMP_CACHE.pop(did, None)
        total -= size


def _print_pdf(path):
    """طباعة مباشرة على الطابعة الافتراضية"""
    os.startfile(path, "print")


def show_pdf_preview(parent, path, title):
    """نافذة معاينة PDF داخل التطبيق (بدون حفظ على الجهاز) + زر طباعة"""
    from PyQt6.QtPdf import QPdfDocument
    from PyQt6.QtPdfWidgets import QPdfView
    dlg = QDialog(parent)
    dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    dlg.setWindowTitle(title)
    dlg.resize(860, 760)
    lay = QVBoxLayout(dlg)
    doc = QPdfDocument(dlg)
    doc.load(path)
    view = QPdfView(dlg)
    view.setDocument(doc)
    view.setPageMode(QPdfView.PageMode.MultiPage)
    view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
    lay.addWidget(view, 1)
    row = QHBoxLayout()
    pbtn = PrimaryButton("🖨️ طباعة")
    pbtn.clicked.connect(lambda: _print_pdf(path))
    cbtn = SecondaryButton("إغلاق")
    cbtn.clicked.connect(dlg.accept)
    row.addWidget(pbtn)
    row.addStretch()
    row.addWidget(cbtn)
    lay.addLayout(row)
    dlg.exec()


def _day_name(date_str):
    try:
        from datetime import datetime
        from config import DAYS_AR
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return DAYS_AR.get(d.weekday(), '')
    except Exception:
        return ''


class CaseLookupPage(QWidget):
    def __init__(self, cookies, current_user, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.cookies = cookies
        self.current_user = current_user
        self._last_caso_no = None
        self._last_autocase_no = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 26, 34, 26)
        root.setSpacing(18)

        header = PageHeader("بحث قضية", "استعلم عن حالة أي قضية حاليًا — مين عندها، منجزة أو لأ، والجلسة القادمة")
        root.addWidget(header)

        search_card = Card()
        s_lay = QHBoxLayout(search_card)
        s_lay.setContentsMargins(16, 14, 16, 14)
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("رقم الخبرة (مثال: A2261234)")
        self.search_entry.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.search_entry.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.search_entry.setStyleSheet(f"""
            QLineEdit {{ background:white; border:1px solid {th.BORDER}; border-radius:10px;
                padding:10px 14px; font-size:14px; }}
            QLineEdit:focus {{ border:1px solid {th.NAVY}; }}
        """)
        self.search_entry.returnPressed.connect(self._on_search)
        self.search_entry.setInputMethodHints(Qt.InputMethodHint.ImhLatinOnly | Qt.InputMethodHint.ImhPreferUppercase)
        self.search_entry.installEventFilter(self)
        search_btn = PrimaryButton("🔎 بحث")
        search_btn.clicked.connect(self._on_search)
        s_lay.addWidget(search_btn)
        s_lay.addWidget(self.search_entry, 1)
        root.addWidget(search_card)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:12px; border:none;")
        self.status_lbl.setAlignment(th.ARIGHT)
        root.addWidget(self.status_lbl)

        self.result_card = Card()
        self.result_lay = QVBoxLayout(self.result_card)
        self.result_lay.setContentsMargins(20, 18, 20, 18)
        self.result_lay.setSpacing(8)
        self.result_card.hide()
        root.addWidget(self.result_card)

        root.addStretch()

    def eventFilter(self, obj, event):
        # عند الدخول لخانة رقم الخبرة: حوّل لوحة المفاتيح تلقائيًا للإنجليزي
        if obj is self.search_entry and event.type() == QEvent.Type.FocusIn:
            _switch_to_english()
        return super().eventFilter(obj, event)

    def _row(self, label_text, value_text, value_color=None, value_bold=True):
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setFixedWidth(160)
        lbl.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:12px; border:none;")
        lbl.setAlignment(th.ARIGHT)
        val = QLabel(value_text)
        val.setWordWrap(True)
        weight = 700 if value_bold else 400
        val.setStyleSheet(f"color:{value_color or th.TEXT_PRIMARY}; font-size:13px; font-weight:{weight}; border:none;")
        val.setAlignment(th.ARIGHT)
        # ⚠️ ترتيب عربي: التسمية أول يمين، والقيمة بعدها يسار (ترتيب القراءة)
        row.addWidget(lbl)
        row.addWidget(val, 1)
        self.result_lay.addLayout(row)

    def _clear_result(self):
        while self.result_lay.count():
            item = self.result_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            lay = item.layout()
            if lay:
                while lay.count():
                    sub = lay.takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

    def _on_search(self):
        caso_no = self.search_entry.text().strip().upper()
        if not caso_no:
            QMessageBox.warning(self, "تنبيه", "أدخل رقم الخبرة أولاً")
            return
        if not self.cookies:
            QMessageBox.warning(self, "تنبيه", "لا يوجد اتصال حالي بالنظام")
            return

        self.status_lbl.setText("⏳ جاري البحث...")
        self.result_card.hide()
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            snapshot = get_case_snapshot(self.cookies, caso_no)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.status_lbl.setText("")
            QMessageBox.critical(self, "خطأ", f"تعذر البحث:\n{th.ltr(e)}")
            return

        # ⚠️ «مو موجودة» ≠ «مو مستلمة»: لازم نفرّق. رقم غلط ⇐ ما فيه
        # قضية بالنظام. رقم صحيح بس ما استلمها الخبير ⇐ موجودة ومو
        # موزّعة بعد (تعرض البطاقة مع سحب الملف الآلي).
        state = snapshot.get('state') or ('ok' if snapshot.get('found') else 'not_found')
        if state == 'not_found':
            QApplication.restoreOverrideCursor()
            self.status_lbl.setText(
                f"❌ ما فيه قضية برقم الخبرة {caso_no} في نظام الخبراء — تأكد من الرقم")
            return

        title = snapshot.get('title') or ''
        autocase_no = snapshot.get('autocase_no') or ''
        if state == 'not_received':
            # الموجودة بالنظام بس مو مستلمة: الرقم الآلي والعنوان جايين
            # مع اللقطة — ما يحتاجين طلبات زيادة.
            if not autocase_no:
                try:
                    autocase_no = get_autocase_no(caso_no, self.cookies)
                except Exception:
                    pass
        else:
            try:
                title = get_title_fallback(self.cookies, caso_no) or ''
            except Exception:
                pass
            try:
                autocase_no = get_autocase_no(caso_no, self.cookies)
            except Exception:
                pass

        upcoming = None
        if state == 'ok' and not snapshot.get('completed'):
            try:
                upcoming = get_upcoming_session_for_case(self.cookies, caso_no)
            except Exception:
                pass

        QApplication.restoreOverrideCursor()
        self.status_lbl.setText("")
        self._last_caso_no = caso_no
        self._last_autocase_no = autocase_no
        self._render_result(caso_no, title, snapshot, upcoming)

    def _render_result(self, caso_no, title, snapshot, upcoming):
        self._clear_result()
        self.result_card.show()

        head = QLabel(f"{caso_no}" + (f"  ·  {title[:60]}" if title else ""))
        head.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:15px; font-weight:700; border:none;")
        head.setAlignment(th.ARIGHT)
        self.result_lay.addWidget(head)
        self.result_lay.addSpacing(6)

        if snapshot.get('state') == 'not_received':
            # ⚠️ موجودة بالنظام بس ما استلمها الخبير بعد — مو «غير موجودة».
            # (رقم غلط يطلع قبل هنا — انظر _on_search.)
            if snapshot.get('pending_distribution'):
                self._row("الحالة:", "🕒 موجودة بالنظام — فيها إحالة بس ما استلمها الخبير بعد",
                          value_color=th.AMBER)
            else:
                self._row("الحالة:", "🕒 موجودة بالنظام — لم يستلمها الخبير بعد",
                          value_color=th.AMBER)
            self._row("متداولة حاليًا عند:", "لا يوجد خبير ماسكها بعد")
            ref_date = snapshot.get('last_referral_date')
            if ref_date:
                self._row("آخر إحالة:", ref_date.strftime('%Y/%m/%d'))
            if snapshot.get('autocase_no'):
                self._row("الرقم الآلي:", snapshot['autocase_no'])
            self._row("ملاحظة:", "ملفات الملف الآلي متاحة — اسحبها من الأزرار تحت.",
                      value_color=th.TEXT_MUTED, value_bold=False)
        else:
            holders = "  ،  ".join(snapshot['current_holders'])
            holder_kind = "لجنة" if snapshot['is_committee'] else "خبير منفرد"
            holder_type = "استعانة" if snapshot['holder_type'] == 'secondment' else "أصالة"
            self._row("متداولة حاليًا عند:", holders)
            self._row("النوع:", f"{holder_kind} — {holder_type}")

            ref_date = snapshot.get('last_referral_date')
            if ref_date:
                self._row("آخر إحالة:", ref_date.strftime('%Y/%m/%d'))

            if snapshot.get('completed'):
                cdate = snapshot.get('completion_date')
                cdate_disp = cdate.strftime('%Y/%m/%d') if cdate else '—'
                by = snapshot.get('completed_by') or ''
                self._row("الحالة:", f"✅ منجزة بتاريخ {cdate_disp}" + (f" (بواسطة {by})" if by else ''),
                           value_color=th.EMERALD_TEXT)
            else:
                self._row("الحالة:", "⏳ غير منجزة بعد", value_color=th.AMBER)
                if upcoming:
                    day = _day_name(upcoming['date'])
                    date_disp = upcoming['date'].replace('-', '/')
                    self._row("الجلسة القادمة:",
                              f"{day} {date_disp} — {upcoming['time']}" + (f" ({upcoming['title']})" if upcoming.get('title') else ''))
                else:
                    self._row("الجلسة القادمة:", "لا توجد جلسة مسجَّلة قادمة")

        self.result_lay.addSpacing(10)
        btn_row = QHBoxLayout()
        pdf_btn = SecondaryButton("📁 سحب مستندات القضية من الملف الآلي")
        pdf_btn.clicked.connect(self._fetch_judgment)
        actions_btn = SecondaryButton("📝 كل إجراءات القضية")
        actions_btn.clicked.connect(self._show_actions_note)
        all_btn = SecondaryButton("👁 معاينة / تنزيل / طباعة ملفات الملف الآلي")
        all_btn.clicked.connect(self._pick_and_download)
        btn_row.addWidget(pdf_btn)
        btn_row.addWidget(all_btn)
        btn_row.addWidget(actions_btn)
        btn_row.addStretch()
        self.result_lay.addLayout(btn_row)

    def _show_actions_note(self):
        if not self._last_caso_no:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            acts = get_case_actions(self.cookies, self._last_caso_no)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "خطأ", f"تعذر جلب الإجراءات:\n{th.ltr(e)}")
            return
        QApplication.restoreOverrideCursor()

        from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
        dlg = QDialog(self)
        dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        dlg.setWindowTitle(f"إجراءات القضية — {self._last_caso_no}")
        dlg.resize(920, 560)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"سجل إجراءات القضية {self._last_caso_no} — {len(acts)} إجراء/جلسة"))

        table = QTableWidget(len(acts), 5)
        table.setHorizontalHeaderLabels(["التاريخ", "الوقت", "الإجراء", "من", "إلى"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.setStyleSheet(f"""
            QTableWidget {{ background:white; border:1px solid {th.BORDER}; border-radius:10px;
                font-size:13px; gridline-color:{th.BORDER}; }}
            QHeaderView::section {{ background:#f1f5f9; padding:8px; border:none;
                border-bottom:1px solid {th.BORDER}; font-weight:700; }}
        """)

        def cell(text, bold=False):
            it = QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if bold:
                f = it.font(); f.setBold(True); it.setFont(f)
            return it

        def who(name, dept):
            return name + (f"\n({dept})" if dept else "")

        for r, a in enumerate(acts):
            table.setItem(r, 0, cell(a['date']))
            table.setItem(r, 1, cell(a['time']))
            table.setItem(r, 2, cell(a['action'], bold=True))
            table.setItem(r, 3, cell(who(a['from_name'], a['from_dept'])))
            table.setItem(r, 4, cell(who(a['to_name'], a['to_dept'])))

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.resizeRowsToContents()
        lay.addWidget(table, 1)

        close_btn = PrimaryButton("إغلاق")
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignLeft)
        dlg.exec()

    def _pick_and_download(self):
        """يعرض كل مستندات الملف الآلي للقضية (كل الأقسام)، تختار منها وتنزّلها بمجلد."""
        if not self._last_caso_no:
            return
        if not self._last_autocase_no:
            QMessageBox.warning(self, "تنبيه", "تعذر تحديد الرقم الآلي لهذي القضية — لا يمكن الوصول للملف الآلي")
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            from documents import get_documents_page, parse_sections
            html = get_documents_page(self.cookies, self._last_autocase_no, USER_ID)
            sections = parse_sections(html)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "خطأ", f"تعذر جلب قائمة الملفات:\n{th.ltr(e)}")
            return
        QApplication.restoreOverrideCursor()

        docs = [dict(r, section=sec) for sec, rows in sections.items() for r in rows]
        if not docs:
            QMessageBox.information(self, "لا توجد ملفات", "ما فيه أي ملفات بالملف الآلي لهذي القضية حاليًا")
            return

        from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
        from documents import _parse_doc_date, SEARCH_ORDER
        dlg = QDialog(self)
        dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        dlg.setWindowTitle(f"ملفات القضية — {self._last_caso_no}")
        dlg.resize(680, 560)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"اختر الملفات المطلوب تنزيلها ({len(docs)} ملف):"))

        tree = QTreeWidget()
        tree.setColumnCount(3)
        tree.setHeaderLabels(["المستند", "التاريخ", "معاينة"])
        tree.setStyleSheet(f"QTreeWidget {{ background:white; border:1px solid {th.BORDER};"
                           f" border-radius:10px; padding:6px; font-size:13px; }}")
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(0, tree.header().ResizeMode.Stretch)
        tree.setColumnWidth(1, 120)
        tree.setColumnWidth(2, 70)

        def preview_doc(d):
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                path = _fetch_temp_pdf(self.cookies, d)
            except Exception as e:
                QApplication.restoreOverrideCursor()
                QMessageBox.critical(dlg, "خطأ", f"تعذرت المعاينة:\n{th.ltr(e)}")
                return
            QApplication.restoreOverrideCursor()
            show_pdf_preview(dlg, path, d.get('doc_type') or 'معاينة المستند')

        # الترتيب: تمييز ← استئناف ← كلية ← بقية الأقسام (إدارة الخبراء...)
        pref = ["محكمة التمييز", "محكمة الاستئناف", "المحكمة الكلية"]
        names = [n for n in pref if n in sections and sections[n]]
        names += [n for n in sections if n not in pref and sections[n]]
        for name in names:
            rows = sorted(sections[name], key=lambda r: _parse_doc_date(r['doc_date']), reverse=True)
            parent = QTreeWidgetItem(tree, [f"{name}  ({len(rows)})", ""])
            parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            parent.setCheckState(0, Qt.CheckState.Unchecked)
            f = parent.font(0); f.setBold(True); parent.setFont(0, f)
            for r in rows:
                dt = _parse_doc_date(r['doc_date'])
                date_txt = dt.strftime('%d/%m/%Y') if dt.year > 1 else (r['doc_date'] or '—')
                child = QTreeWidgetItem(parent, [r['doc_type'] or 'بدون نوع', date_txt])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Unchecked)
                child.setData(0, Qt.ItemDataRole.UserRole, dict(r, section=name))
                eye = SecondaryButton("👁")
                eye.setToolTip("معاينة الملف")
                eye.clicked.connect(lambda _=False, d=dict(r, section=name): preview_doc(d))
                tree.setItemWidget(child, 2, eye)
            parent.setExpanded(True)
        lay.addWidget(tree, 1)

        def checked_docs():
            out = []
            for i in range(tree.topLevelItemCount()):
                p = tree.topLevelItem(i)
                for j in range(p.childCount()):
                    c = p.child(j)
                    if c.checkState(0) == Qt.CheckState.Checked:
                        out.append(c.data(0, Qt.ItemDataRole.UserRole))
            return out

        btns = QHBoxLayout()
        all_btn = SecondaryButton("تحديد الكل")
        none_btn = SecondaryButton("إلغاء التحديد")
        dl_btn = PrimaryButton("⬇️ تنزيل المحدد")
        close_btn = SecondaryButton("إغلاق")

        def set_all(state):
            for i in range(tree.topLevelItemCount()):
                tree.topLevelItem(i).setCheckState(0, state)
        all_btn.clicked.connect(lambda: set_all(Qt.CheckState.Checked))
        none_btn.clicked.connect(lambda: set_all(Qt.CheckState.Unchecked))
        close_btn.clicked.connect(dlg.reject)

        def do_download():
            chosen = checked_docs()
            if not chosen:
                QMessageBox.warning(dlg, "تنبيه", "اختر ملفًا واحدًا على الأقل")
                return
            import re
            from documents import download_judgment_pdf
            folder = os.path.join(os.path.expanduser("~"), "Desktop", "judgments", str(self._last_caso_no))
            os.makedirs(folder, exist_ok=True)
            ok, failed = 0, []
            used = set()
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                for d in chosen:
                    safe = re.sub(r'[^\w؀-ۿ]+', '_', d['doc_type'] or 'مستند').strip('_')
                    dt = _parse_doc_date(d['doc_date'])
                    ds = dt.strftime('%Y-%m-%d') if dt.year > 1 else 'بدون_تاريخ'
                    base = f"{safe}_{ds}"
                    path = os.path.join(folder, base + ".pdf")
                    k = 2
                    while path in used:
                        path = os.path.join(folder, f"{base}_{k}.pdf")
                        k += 1
                    used.add(path)
                    try:
                        download_judgment_pdf(self.cookies, d['doc_id'], path)
                        ok += 1
                    except Exception:
                        failed.append(d['doc_type'])
            finally:
                QApplication.restoreOverrideCursor()
            msg = f"تم تنزيل {ok} ملف"
            if failed:
                msg += "\nفشل: " + "، ".join(failed)
            QMessageBox.information(dlg, "تم", msg)
            if ok:
                os.startfile(folder)

        def do_print():
            chosen = checked_docs()
            if not chosen:
                QMessageBox.warning(dlg, "تنبيه", "اختر ملفًا واحدًا على الأقل")
                return
            failed = []
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                for d in chosen:
                    try:
                        _print_pdf(_fetch_temp_pdf(self.cookies, d))
                    except Exception:
                        failed.append(d['doc_type'] or 'مستند')
            finally:
                QApplication.restoreOverrideCursor()
            if failed:
                QMessageBox.warning(dlg, "تنبيه", "تعذرت طباعة: " + "، ".join(failed))
            else:
                QMessageBox.information(dlg, "تمت الطباعة", f"أُرسل {len(chosen)} ملف إلى الطابعة")

        dl_btn.clicked.connect(do_download)
        print_btn = SecondaryButton("🖨️ طباعة المحدد")
        print_btn.clicked.connect(do_print)
        btns.addWidget(dl_btn)
        btns.addWidget(print_btn)
        btns.addWidget(all_btn)
        btns.addWidget(none_btn)
        btns.addStretch()
        btns.addWidget(close_btn)
        lay.addLayout(btns)
        dlg.exec()

    def _fetch_judgment(self):
        if not self._last_caso_no:
            return
        if not self._last_autocase_no:
            QMessageBox.warning(self, "تنبيه", "تعذر تحديد الرقم الآلي لهذي القضية — لا يمكن الوصول للملف الآلي")
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            from documents import get_case_documents_bundle
            case_dir = os.path.join(os.path.expanduser("~"), "Desktop", "judgments", str(self._last_caso_no))
            os.makedirs(case_dir, exist_ok=True)
            bundle = get_case_documents_bundle(
                self.cookies, self._last_autocase_no, USER_ID, case_dir)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "خطأ", f"تعذر سحب الملفات:\n{th.ltr(e)}")
            return
        QApplication.restoreOverrideCursor()

        labels = {'judgment': 'حكم الإحالة', 'claim': 'صحيفة الدعوى', 'report': 'تقرير الخبير'}
        found = [labels[k] for k, v in bundle.items() if v]
        missing = [labels[k] for k, v in bundle.items() if not v]

        if not found:
            QMessageBox.information(self, "لا توجد مستندات",
                                     "ما فيه أي من هذي المستندات متوفر بالملف الآلي لهذي القضية حاليًا:\n"
                                     + "، ".join(labels.values()))
            return

        msg = "تم سحب: " + "، ".join(found)
        if missing:
            msg += "\nغير متوفر: " + "، ".join(missing)
        QMessageBox.information(self, "تم السحب", msg)
        os.startfile(case_dir)
