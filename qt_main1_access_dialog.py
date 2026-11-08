# ===== qt_main1_access_dialog.py — نافذة إدارة صلاحية "إضافة قضية جديدة" (المالك فقط) =====
"""
نافذة يفتحها المالك (محمد العنزي) من صفحة الإعدادات، ليمنح أو يسحب صلاحية ميزة
"إضافة قضية جديدة" لأي خبير آخر — عبر اختيار اسمه من قائمة أسماء الخبراء المسجّلين
أونلاين (experts_registry.list_experts)، بدون كتابة يدوية حرة.

⚠️ مصدر الأسماء موحّد أونلاين (Supabase) لا Access — كل خبير يفتح البرنامج يُسجَّل
اسمه تلقائيًا بسجل الخبراء (experts_registry)، فالقائمة تشتغل من أي مكان (بيت أو
دوام) وتتراكم تلقائيًا، بدل الاعتماد على قاعدة Access المتوفرة فقط على شبكة الدوام.
والصلاحية بالاسم لا برقم الحساب (رقم الحساب غير موثوق).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QListWidget, QMessageBox, QApplication,
)

import qt_theme as th
from qt_widgets import PrimaryButton, SecondaryButton
import main1_access
import experts_registry


class Main1AccessDialog(QDialog):
    def __init__(self, parent=None, current_user=""):
        super().__init__(parent)
        self.current_user = current_user or ""
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("صلاحية إضافة قضية جديدة")
        self.setFixedWidth(500)
        self.setStyleSheet(f"background:{th.BG};")
        self._build()
        self._load_expert_names()
        self._reload()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 22, 22, 22)
        lay.setSpacing(12)

        title = QLabel("منح صلاحية «إضافة قضية جديدة»")
        title.setStyleSheet(
            f"color:{th.TEXT_PRIMARY}; font-size:16px; font-weight:700; border:none;"
        )
        lay.addWidget(title)

        hint = QLabel(
            "اختر اسم الخبير من القائمة لمنحه صلاحية إضافة القضايا الجديدة. القائمة "
            "تُبنى تلقائيًا من أسماء الخبراء الذين فتحوا البرنامج (مصدر أونلاين موحّد)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:12px; border:none;")
        lay.addWidget(hint)

        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setEditable(True)  # يسمح بالبحث/التصفية مع الاختيار من القائمة
        self.combo.setStyleSheet(
            f"QComboBox{{background:white; border:1px solid {th.BORDER}; border-radius:10px;"
            f"padding:9px 12px; font-size:13px; color:{th.TEXT_PRIMARY};}}"
            f"QComboBox:focus{{border:1px solid {th.NAVY};}}"
        )
        add_btn = PrimaryButton("➕ منح")
        add_btn.clicked.connect(self._grant)
        row.addWidget(self.combo, 1)
        row.addWidget(add_btn)
        lay.addLayout(row)

        self.names_status = QLabel("")
        self.names_status.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        lay.addWidget(self.names_status)

        lst_lbl = QLabel("الخبراء المخوّلون حاليًا:")
        lst_lbl.setStyleSheet(
            f"color:{th.TEXT_SECONDARY}; font-size:12px; font-weight:700; border:none;"
        )
        lay.addWidget(lst_lbl)

        self.lst = QListWidget()
        self.lst.setMinimumHeight(200)
        self.lst.setStyleSheet(
            f"QListWidget{{background:white; border:1px solid {th.BORDER}; border-radius:10px;"
            f"padding:6px; font-size:13px; color:{th.TEXT_PRIMARY};}}"
            "QListWidget::item{padding:6px 8px;}"
            f"QListWidget::item:selected{{background:{th.BLUE_INFO_BG}; color:{th.BLUE_INFO_TEXT}; border-radius:6px;}}"
        )
        lay.addWidget(self.lst)

        btns = QHBoxLayout()
        refresh_btn = SecondaryButton("↻ تحديث")
        refresh_btn.clicked.connect(self._reload_all)
        revoke_btn = SecondaryButton("🗑 سحب الصلاحية عن المحدد")
        revoke_btn.clicked.connect(self._revoke)
        btns.addWidget(revoke_btn)
        btns.addStretch()
        btns.addWidget(refresh_btn)
        lay.addLayout(btns)

    # ---------- تحميل أسماء الخبراء (من السجل الأونلاين) ----------
    def _load_expert_names(self):
        names = []
        try:
            names = experts_registry.list_experts()
        except Exception:
            names = []
        # احتياط: لو السجل الأونلاين فاضٍ (أول تشغيل، أو لا إنترنت) نحاول Access
        if not names:
            try:
                from db_writer import get_expert_names
                names = get_expert_names()
            except Exception:
                names = []
        self.combo.clear()
        if names:
            self.combo.addItems(names)
            self.combo.setCurrentIndex(-1)
            self.names_status.setText(f"عدد الأسماء المتاحة: {len(names)}")
        else:
            self.names_status.setText(
                "لا توجد أسماء بعد (تُبنى القائمة تلقائيًا كل ما يفتح خبير البرنامج) —"
                " يمكنك كتابة الاسم يدويًا مؤقتًا."
            )

    def _reload_all(self):
        self._load_expert_names()
        self._reload()

    # ---------- قائمة المخوّلين ----------
    def _reload(self):
        self.lst.clear()
        self.lst.addItem("… جاري التحميل من القاعدة الأونلاين")
        QApplication.processEvents()
        names = main1_access.list_authorized()
        self.lst.clear()
        if not names:
            self.lst.addItem("لا يوجد خبراء مخوّلون بعد (عدا المالك)")
            return
        for n in names:
            self.lst.addItem(n)

    def _grant(self):
        name = self.combo.currentText().strip()
        if not name:
            QMessageBox.warning(self, "تنبيه", "اختر اسم خبير من القائمة أو اكتبه.")
            return
        ok, msg = main1_access.grant_access(name, granted_by=self.current_user)
        if ok:
            self.combo.setCurrentIndex(-1)
            self._reload()
            QMessageBox.information(self, "تم", f"تم منح صلاحية إضافة القضايا للخبير:\n{name}")
        else:
            QMessageBox.critical(self, "فشل", msg)

    def _revoke(self):
        item = self.lst.currentItem()
        placeholder = ("لا يوجد", "… جاري", "عدا المالك")
        if not item or any(p in item.text() for p in placeholder):
            QMessageBox.warning(self, "تنبيه", "اختر اسم خبير من القائمة أولًا.")
            return
        name = item.text().strip()
        confirm = QMessageBox.question(
            self, "تأكيد السحب",
            f"سحب صلاحية إضافة القضايا عن الخبير:\n{name}؟",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        ok, msg = main1_access.revoke_access(name)
        if ok:
            self._reload()
            QMessageBox.information(self, "تم", f"تم سحب الصلاحية عن الخبير:\n{name}")
        else:
            QMessageBox.critical(self, "فشل", msg)


def open_main1_access_dialog(parent, current_user=""):
    "نقطة الدخول — يفتحها زر واحد بصفحة الإعدادات (للمالك فقط)"
    dlg = Main1AccessDialog(parent, current_user=current_user)
    dlg.exec()
