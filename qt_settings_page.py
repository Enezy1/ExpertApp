# ===== qt_settings_page.py — صفحة الإعدادات (تصميم Executive الجديد) =====
# نفس منطق settings_page.py الأصلي بالكامل (حفظ/تحميل مفتاح Gemini،
# بيانات iCloud، بيانات الخبير) بدون أي تعديل — فقط طبقة العرض جديدة.
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
    QMessageBox, QApplication, QComboBox, QFileDialog, QPushButton,
    QFrame,
)
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QIcon, QDesktopServices
import os

import qt_theme as th
from qt_widgets import Card, PrimaryButton, SecondaryButton, PageHeader

from gemini_config import save_api_key, load_api_key, mask_key
from expert_settings import (
    save_specialty, load_specialty, save_location, load_location,
    save_update_folder, load_update_folder,
    save_update_online_url, load_update_online_url,
    save_update_version, load_update_version,
    save_reports_root, load_reports_root,
    save_minutes_root, load_minutes_root, default_minutes_root,
)
from icloud_calendar import (
    save_credentials as save_icloud_credentials,
    load_credentials as load_icloud_credentials,
    test_connection as test_icloud_connection,
)
from api import get_expert_profile_fields

# فحص خفيف بدون أي استيراد ثقيل (pyodbc وغيرها) — نستخدمه فقط لتحديد
# هل نبني بطاقة "إضافة قضية جديدة" أصلاً، عشان الصفحة تشتغل طبيعي لأي
# خبير ثاني حتى لو مكتبة pyodbc غير مثبتة على جهازه (تُستورد فقط داخل
# qt_main1.py، ويُستدعى هذا الملف بشكل مؤجَّل فقط لو المستخدم مخوَّل).
# الصلاحية تُدار أونلاين بالاسم عبر Supabase (main1_access.py) بدل قائمة الأسماء.
import re
import main1_access
from config import APP_VERSION
from current_expert import get_current_account


def _is_authorized_for_main1(current_user):
    return main1_access.is_authorized_for_main1(current_user, get_current_account())


def _field_label(text):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:11px; font-weight:700; border:none;")
    lbl.setAlignment(th.ARIGHT)
    return lbl


class PathLineEdit(QLineEdit):
    """خانة مسار: الضغط عليها (أو على أيقونة المجلد) يفتح استعراض المجلدات ويملؤها بدل الكتابة اليدوية."""
    def __init__(self, title="اختر المجلد", parent=None):
        super().__init__(parent)
        self._title = title
        act = self.addAction(QIcon.fromTheme("folder-open") if not QIcon.fromTheme("folder-open").isNull()
                             else self.style().standardIcon(self.style().StandardPixmap.SP_DirOpenIcon),
                             QLineEdit.ActionPosition.TrailingPosition)
        act.setToolTip("استعراض المجلدات")
        act.triggered.connect(self.browse)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            self.browse()

    def browse(self):
        start = self.text().strip() or self.placeholderText()
        path = QFileDialog.getExistingDirectory(self, self._title, start if os.path.isdir(start) else "")
        if path:
            self.setText(os.path.normpath(path))
        return path


def _path_edit(placeholder="", value="", title="اختر المجلد"):
    e = PathLineEdit(title)
    e.setPlaceholderText(placeholder)
    if value:
        e.setText(value)
    e.setStyleSheet(f"""
        QLineEdit {{ background:white; border:1px solid {th.BORDER}; border-radius:10px;
            padding:9px 12px; font-size:13px; color:{th.TEXT_PRIMARY}; }}
        QLineEdit:focus {{ border:1px solid {th.NAVY}; }}
    """)
    e.setAlignment(th.ALEFT)
    return e


def _line_edit(placeholder="", value="", ltr=False):
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    if value:
        e.setText(value)
    e.setStyleSheet(f"""
        QLineEdit {{ background:white; border:1px solid {th.BORDER}; border-radius:10px;
            padding:9px 12px; font-size:13px; color:{th.TEXT_PRIMARY}; }}
        QLineEdit:focus {{ border:1px solid {th.NAVY}; }}
    """)
    e.setAlignment(th.ALEFT if ltr else th.ARIGHT)
    return e


class SettingsPage(QWidget):
    _profile_ready = pyqtSignal(object)

    def __init__(self, cookies=None, current_user=None, parent=None):
        super().__init__(parent)
        self.cookies = cookies
        self.current_user = current_user
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 26, 34, 26)
        root.setSpacing(18)

        header = PageHeader("الإعدادات", "ربط الذكاء الاصطناعي وتقويم الآيفون وبيانات الخبير")
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # بدون تمرير أفقي: المحتوى ياخذ عرض الصفحة كامل (ما ينضغط نص3298)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        c_lay = QVBoxLayout(content)
        c_lay.setContentsMargins(2, 2, 2, 2)
        c_lay.setSpacing(16)

        # قسمان (2026-10-19): «الإعدادات العامة» للجميع، و«التشخيص» للمالك فقط (لا يظهر لغيره أصلاً)
        c_lay.addWidget(self._build_expert_card())
        c_lay.addWidget(self._build_reports_root_card())      # إعداد واحد: مجلد حفظ مستندات القضايا (المحاضر داخله)
        # ===== المفاتيح: قسمان تحت بعض — الذكاء الاصطناعي أولاً ثم OCR =====
        # (10/11/2026 — طلب العنزي: «خلهم تحت بعض»، والذكاء قبل الـOCR؛
        #  وكل قسم على طراز قوائم قوقل: شريط عنوان + شارة + صفوف.)
        c_lay.addWidget(self._build_keys_card(
            "🔑 مفاتيح الذكاء الاصطناعي",
            "لاستخراج المعلومات وصياغة التقرير والبحث. مفتاحك الشخصي لمزوّد يحجب "
            "مفتاح القسم لنفس المزوّد، وإن فشل (منتهٍ أو بلا رصيد) يُبلَّغ به ولا "
            "ينتقل البرنامج لمفتاح القسم بصمت.",
            ('gemini', 'openai')))
        c_lay.addWidget(self._build_keys_card(
            "📄 قراءة المستندات (OCR)",
            "لقراءة الأحكام والمستندات الممسوحة. مفتاحك الشخصي يُستعمل وحده؛ "
            "ولو لم تضف مفتاحاً يُستعمل مفتاح القسم (إن وُجد).",
            ('vision', 'ocrspace')))
        c_lay.addWidget(self._build_icloud_card())
        c_lay.addStretch()
        from gemini_config import is_admin
        owner = main1_access.is_owner(self.current_user, get_current_account())
        diag = None
        if owner or is_admin():
            diag = QWidget()
            d_lay = QVBoxLayout(diag)
            d_lay.setContentsMargins(2, 2, 2, 2)
            d_lay.setSpacing(16)
            if is_admin():
                d_lay.addWidget(self._build_task_providers_card())
                d_lay.addWidget(self._build_features_card())
                d_lay.addWidget(self._build_providers_card())
            if owner:
                d_lay.addWidget(self._build_access_card())
                d_lay.addWidget(self._build_update_card())
            if is_admin():
                d_lay.addWidget(self._build_debug_card())
                d_lay.addWidget(self._build_net_diag_card())
            d_lay.addStretch()
        for w in (content, diag):
            if w is None:
                continue
            for box in w.findChildren(QComboBox):          # عجلة الفأرة تمرّر الصفحة ولا تغيّر الاختيار
                box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                box.installEventFilter(self)
            from PyQt6.QtWidgets import QAbstractSpinBox
            for box in w.findChildren(QAbstractSpinBox):
                box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                box.installEventFilter(self)
        if diag is not None:
            from PyQt6.QtWidgets import QTabWidget
            tabs = QTabWidget()
            for w, name in ((content, "الإعدادات العامة"), (diag, "التشخيص")):
                sc = QScrollArea()
                sc.setWidgetResizable(True)
                sc.setFrameShape(QScrollArea.Shape.NoFrame)
                sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                sc.setWidget(w)
                tabs.addTab(sc, name)
            root.addWidget(tabs, 1)
            return
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if ev.type() == QEvent.Type.Wheel:  # تمرير الصفحة بدل تغيير القائمة المنسدلة
            w = obj.parentWidget()
            while w is not None and not isinstance(w, QScrollArea):
                w = w.parentWidget()
            if w is not None:
                QApplication.sendEvent(w.verticalScrollBar(), ev)
            return True
        return super().eventFilter(obj, ev)

    # ---------- مفاتيح تشغيل/إيقاف طبقات القراءة (للتجربة) ----------
    def _build_features_card(self):
        from PyQt6.QtWidgets import QCheckBox
        from gemini_config import FEATURES, feature_on, set_feature
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)
        title = QLabel("طبقات القراءة والذكاء (تشغيل / إيقاف)")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        sub = QLabel("أوقف ما لا تريد استخدامه لتجربة طبقة واحدة فقط. مواقع الدردشة ترفع الملف لمواقع خارجية.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        sub.setAlignment(th.ARIGHT)
        lay.addWidget(title)
        lay.addWidget(sub)
        for key, label in FEATURES.items():
            cb = QCheckBox(label)
            cb.setChecked(feature_on(key))
            cb.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:12px; border:none;")
            cb.toggled.connect(lambda on, k=key: set_feature(k, on))
            lay.addWidget(cb)
        return card

    # ---------- أقسام مفاتيح الخبير الشخصية: قراءة المستندات (OCR) ومفاتيح الذكاء الاصطناعي ----------
    # لكل مزوّد: خانة المفتاح + لصق + حفظ + اختبار + حذف، ورابط يفتح صفحة إصدار المفتاح، وسطر حالة المصدر.
    # المفتاح الشخصي يُستعمل وحده ويحجب مفتاح القسم؛ بلا مفتاح شخصي يُستعمل مفتاح القسم (يضعه الأدمن).
    KEY_CARDS = {
        'vision': {
            'title': "Google Cloud Vision",
            'sub': "محرّك OCR لقراءة المستندات الممسوحة (عربي وأرقام). المفتاح محفوظ لحسابك فقط ومشفّر على هذا الجهاز.",
            'url': "https://console.cloud.google.com/apis/credentials",
            'link': "فتح صفحة مفاتيح Google Cloud",
            'note': "فعّل Cloud Vision API في المشروع ثم أنشئ مفتاحاً.",
        },
        'ocrspace': {
            'title': "OCR.space",
            'sub': "لقراءة الأحكام الممسوحة ضوئيًا (مجاني). لو أضفت مفتاحك يُستخدم بدل مفتاح القسم.",
            'url': "https://ocr.space/ocrapi/freekey",
            'link': "الحصول على مفتاح OCR.space مجاني",
            'note': "",
        },
        'gemini': {
            'title': "Gemini (Google)",
            'sub': "مفتاح Gemini API لاستخراج الأحكام وصياغة التقرير. لو أضفته يُستخدم بدل مفتاح القسم.",
            'url': "https://aistudio.google.com/app/apikey",
            'link': "الحصول على مفتاح Gemini",
            'note': "",
        },
        'openai': {
            'title': "ChatGPT (OpenAI)",
            'sub': "مفتاح OpenAI API؛ يختار البرنامج أقوى نموذج متاح لمفتاحك تلقائياً. لو أضفته يُستخدم بدل مفتاح القسم.",
            'url': "https://platform.openai.com/api-keys",
            'link': "إنشاء مفتاح OpenAI API",
            'note': "",
        },
    }

    def _open_url(self, url):
        QDesktopServices.openUrl(QUrl(url))

    def _build_keys_card(self, title_text, note, keys):
        """
        قائمة مفاتيح على طراز قوائم قوقل: **شريط عنوان** (خلفية خفيفة + عنوان
        + شرح) وتحته **صف لكل مزوّد** (سطرين بس) — بدل بطاقة طويلة لكل مزوّد
        (7 سطور). 10/11/2026.
        """
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---------- شريط العنوان ----------
        head = QWidget()
        head.setObjectName('keys_head')
        head.setStyleSheet(
            f"QWidget#keys_head {{ background:{th.NAVY_SOFT};"
            " border-top-left-radius:16px; border-top-right-radius:16px; }")
        h = QHBoxLayout(head)
        h.setContentsMargins(18, 12, 18, 12)
        h.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(title_text)
        t.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:16px; font-weight:800; border:none;")
        t.setAlignment(th.ARIGHT)
        col.addWidget(t)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            n.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
            n.setAlignment(th.ARIGHT)
            col.addWidget(n)
        h.addLayout(col, 1)          # العنوان يمين
        lay.addWidget(head)

        # ---------- الصفوف ----------
        body = QWidget()
        b_lay = QVBoxLayout(body)
        b_lay.setContentsMargins(18, 8, 18, 12)
        b_lay.setSpacing(0)
        for i, which in enumerate(keys):
            if i:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background:{th.BORDER_SOFT}; border:none;")
                b_lay.addWidget(sep)
            b_lay.addWidget(self._build_key_row(which))
        lay.addWidget(body)
        return card

    def _build_key_row(self, which):
        """
        سطر مضغوط لمزوّد:
          سطر 1: الاسم (يمين) ... [خانة المفتاح][لصق][حفظ][اختبار][حذف]
          سطر 2: حالة المفتاح + رابط صفحة المفتاح + ملاحظة المزوّد
        """
        spec = self.KEY_CARDS[which]
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(2)

        line1 = QHBoxLayout()
        line1.setContentsMargins(0, 0, 0, 0)
        line1.setSpacing(6)
        title = QLabel(spec['title'])
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:13px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        title.setToolTip(spec['sub'])
        line1.addWidget(title)
        entry = _line_edit("الصق المفتاح هنا", ltr=True)
        entry.setEchoMode(QLineEdit.EchoMode.Password)
        paste_btn = SecondaryButton("📋 لصق")
        save_btn = PrimaryButton("💾 حفظ")
        test_btn = SecondaryButton("🧪 اختبار")
        del_btn = SecondaryButton("🗑 حذف")
        paste_btn.clicked.connect(lambda: self._paste_key(which))
        save_btn.clicked.connect(lambda: self._save_key(which))
        test_btn.clicked.connect(lambda: self._test_key(which))
        del_btn.clicked.connect(lambda: self._delete_key(which))
        line1.addWidget(entry, 1)
        for w in (paste_btn, save_btn, test_btn, del_btn):
            line1.addWidget(w)
        v.addLayout(line1)

        line2 = QHBoxLayout()
        line2.setContentsMargins(0, 0, 0, 0)
        line2.setSpacing(8)
        status = QLabel("")
        status.setWordWrap(True)
        status.setAlignment(th.ARIGHT)
        line2.addWidget(status)
        # الملاحظة بالوسط (وإن ما فيه ملاحظة: فراغ ي pushing الرابط لآخر يسار)
        if spec.get('note'):
            note = QLabel(spec['note'])
            note.setWordWrap(True)
            note.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:10px; border:none;")
            note.setAlignment(th.ARIGHT)
            line2.addWidget(note, 1)
        else:
            line2.addStretch(1)
        # الرابط **آخر يسار** في كل الصفوف (زي Gemini)
        link = QPushButton("🔗 " + spec['link'])
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.setFlat(True)
        link.setToolTip(spec['url'])
        link.setStyleSheet(f"QPushButton {{ color:{th.NAVY}; font-size:11px; font-weight:700; border:none;"
                           " text-decoration:underline; text-align:left; padding:0; }")
        link.clicked.connect(lambda: self._open_url(spec['url']))
        line2.addWidget(link, 0)
        v.addLayout(line2)

        if not hasattr(self, '_key_widgets'):
            self._key_widgets = {}
        self._key_widgets[which] = {'entry': entry, 'status': status, 'link': link}
        self._refresh_key_status(which)
        return box

    def _key_io(self, which):
        """(قراءة، حفظ) المفتاح الشخصي لكل مزوّد."""
        import gemini_config as gc
        import ocr_vision
        return {'vision': (ocr_vision.load_key, ocr_vision.save_key),
                'ocrspace': (gc.load_ocr_key, gc.save_ocr_key),
                'gemini': (gc.load_api_key, gc.save_api_key),
                'openai': (gc.load_openai_key, gc.save_openai_key)}[which]

    def _key_status_text(self, which):
        """(نص، لون): «يُستعمل مفتاحك» | «لا يوجد مفتاح شخصي، يُستعمل مفتاح القسم» | «لا يوجد مفتاح»."""
        import ai_providers
        try:
            src = ai_providers.key_source(which)
        except Exception:
            src = 'none'
        text = ai_providers.KEY_SOURCE_TEXT[src]
        if src == 'own':
            k = self._key_io(which)[0]()
            return f"✅ {text}" + (f" ({mask_key(k)})" if mask_key(k) else ""), th.EMERALD_TEXT
        if src == 'shared':
            return "ℹ️ " + text, th.TEXT_SECONDARY
        return "⚠️ " + text, '#b3261e'

    def _refresh_key_status(self, which):
        text, color = self._key_status_text(which)
        lbl = self._key_widgets[which]['status']
        lbl.setText(text)
        lbl.setStyleSheet(f"color:{color}; font-size:11px; font-weight:700; border:none;")

    def _paste_key(self, which):
        clip = QApplication.clipboard().text().strip()
        if not clip:
            QMessageBox.warning(self, "تنبيه", "الحافظة فاضية — انسخ المفتاح أولاً، ثم اضغط لصق")
            return
        self._key_widgets[which]['entry'].setText(clip)

    def _save_key(self, which):
        entry = self._key_widgets[which]['entry']
        key = entry.text().strip()
        if not key:
            QMessageBox.warning(self, "تنبيه", "الصق المفتاح أولاً")
            return
        try:
            self._key_io(which)[1](key)             # بلا فحص لبادئة المفتاح: التحقق باتصال «اختبار» فقط
        except OSError:
            QMessageBox.critical(self, "تعذّر الحفظ", "تعذّر حفظ المفتاح مشفّراً على هذا الجهاز.")
            return
        entry.clear()
        self._refresh_key_status(which)
        QMessageBox.information(self, "✅ تم", f"تم حفظ مفتاح {self.KEY_CARDS[which]['title']} (مشفّر على جهازك)")

    def _delete_key(self, which):
        self._key_io(which)[1]('')
        self._refresh_key_status(which)

    def _test_key(self, which):
        """اتصال تجريبي بمفتاح الخبير الشخصي وحده (لا مفتاح القسم) ويعرض النتيجة بالعربية."""
        import gemini_config as gc
        name = self.KEY_CARDS[which]['title']
        if not self._key_io(which)[0]():
            QMessageBox.warning(self, "تنبيه", "لا يوجد مفتاح شخصي محفوظ — احفظ المفتاح أولاً")
            return
        self._key_widgets[which]['status'].setText("⏳ جاري الاختبار...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok, msg = self._run_key_test(which)
        except Exception as e:
            ok, msg = False, gc.short_error(e)
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh_key_status(which)
        if ok:
            QMessageBox.information(self, f"✅ {name} يعمل", gc.redact(msg))
        else:
            why = gc.explain_key_failure(msg)
            QMessageBox.critical(self, f"❌ فشل اختبار {name}",
                                 (why + "\n\n" if why else "تعذّر الاتصال.\n\n") + th.ltr(gc.redact(msg)))

    def _run_key_test(self, which):
        if which == 'vision':
            import ocr_vision
            return ocr_vision.test()
        import ai_providers
        if which == 'ocrspace':
            return ai_providers.test_own_ocrspace()
        if which == 'openai':
            return ai_providers.test_own_openai()
        return ai_providers.test_own_gemini()

    # ---------- تحذير: مفاتيح بنص صريح ----------
    def _build_secrets_warning(self):
        import secret_audit
        text = secret_audit.warning_text()
        if not text:
            return None
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 14, 20, 14)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{th.ERROR_TEXT if hasattr(th, 'ERROR_TEXT') else '#b3261e'}; font-size:12px;"
                          " font-weight:700; border:none;")
        lbl.setAlignment(th.ARIGHT)
        lay.addWidget(lbl)
        return card

    # ---------- بطاقة: مزوّد كل مهمة ----------
    def _build_task_providers_card(self):
        import ai_providers
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)
        title = QLabel("مزوّد كل مهمة")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        sub = QLabel("اختر من يتولى كل مهمة. البحث والنتيجة بـ Gemini وحده (أقوى نموذج Pro متاح لمفتاحك، وFlash احتياطياً "
                     "فقط عند الفشل/تجاوز الحد ويظهر ذلك في «كُتب بواسطة»)؛ Groq والنماذج الصغيرة لا تُستعمل للصياغة. "
                     "عند غياب المزوّد المختار ينبّهك البرنامج ولا ينتقل لأضعف بصمت.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        sub.setAlignment(th.ARIGHT)
        lay.addWidget(title)
        lay.addWidget(sub)
        names = [r['name'] for r in ai_providers.get_provider_configs()
                 if r.get('kind') == 'openai' and not ai_providers._is_groq(r)]        # Groq لا يُستعمل في أي مهمة
        presets = [('تلقائي (الأرخص أولاً)', 'auto'), ('Gemini ثم OpenAI-compatible (بدون Groq)', 'gemini,openai'),
                   ('Gemini فقط', 'gemini')] + [(f'{n} صراحةً', n) for n in names]
        cur = ai_providers.get_task_specs()
        self._task_combos = {}
        for task, label in ai_providers.TASKS.items():
            row = QHBoxLayout()
            box = QComboBox()
            for text, spec in presets:
                box.addItem(text, spec)
            idx = box.findData(cur[task])
            if idx < 0:
                box.addItem(ai_providers.describe_spec(cur[task]), cur[task])
                idx = box.count() - 1
            box.setCurrentIndex(idx)
            box.currentIndexChanged.connect(lambda _=0, t=task: self._save_task_provider(t))
            self._task_combos[task] = box
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:12px; border:none;")
            lbl.setAlignment(th.ARIGHT)
            row.addWidget(box, 1)
            row.addWidget(lbl)
            lay.addLayout(row)
        lay.addLayout(self._gemini_model_row())
        return card

    def _gemini_model_row(self):
        """نموذج Gemini للاستخراج والصياغة والتدقيق: «تلقائي — أحدث Pro متاح» (قائمة النماذج من الـAPI) أو نموذج بعينه.
        Flash يبقى احتياطياً فقط عند الفشل/تجاوز الحد ويظهر للخبير في «كُتب بواسطة»."""
        import gemini_config as gc
        row = QHBoxLayout()
        box = QComboBox()
        box.addItem("تلقائي — أحدث Gemini Pro متاح (موصى به)", 'auto')
        try:
            names = gc.list_models() if gc.load_api_key() else []
        except Exception:
            names = []
        for n in gc.rank_pro(names) + [n for n in names if 'flash' in n and 'tts' not in n and 'image' not in n]:
            box.addItem(n, n)
        cur = gc.pro_setting()
        i = box.findData(cur)
        if i < 0:
            box.addItem(cur, cur)
            i = box.count() - 1
        box.setCurrentIndex(i)
        box.currentIndexChanged.connect(lambda _=0, b=box: self._save_gemini_model(b))
        self._gemini_model_box = box
        ref = SecondaryButton("تحديث القائمة")
        ref.clicked.connect(self._refresh_gemini_models)
        lbl = QLabel("نموذج Gemini (الاستخراج والصياغة والتدقيق)")
        lbl.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:12px; border:none;")
        lbl.setAlignment(th.ARIGHT)
        row.addWidget(ref)
        row.addWidget(box, 1)
        row.addWidget(lbl)
        return row

    def _save_gemini_model(self, box):
        import gemini_config as gc
        try:
            gc.save_pro_setting(box.currentData())
        except OSError as e:
            QMessageBox.warning(self, "تنبيه", f"تعذّر الحفظ: {e}")

    def _refresh_gemini_models(self):
        import gemini_config as gc
        try:
            names = gc.list_models(refresh=True)
        except Exception as e:
            QMessageBox.warning(self, "نماذج Gemini", f"تعذّرت قراءة قائمة النماذج من Gemini: {gc.short_error(e)}")
            return
        box = self._gemini_model_box
        cur = box.currentData()
        box.blockSignals(True)
        box.clear()
        box.addItem("تلقائي — أحدث Gemini Pro متاح (موصى به)", 'auto')
        for n in gc.rank_pro(names) + [n for n in names if 'flash' in n and 'tts' not in n and 'image' not in n]:
            box.addItem(n, n)
        i = box.findData(cur)
        box.setCurrentIndex(i if i >= 0 else 0)
        box.blockSignals(False)
        best = (gc.rank_pro(names) or ['—'])[0]
        QMessageBox.information(self, "نماذج Gemini", f"أحدث Pro متاح لمفتاحك: {best}")

    def _save_task_provider(self, task):
        import ai_providers
        try:
            ai_providers.save_task_spec(task, self._task_combos[task].currentData())
        except OSError as e:
            QMessageBox.warning(self, "تنبيه", f"تعذّر الحفظ: {e}")

    # ---------- بطاقة 2: تقويم iCloud ----------
    def _build_icloud_card(self):
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)

        title = QLabel("ربط تقويم الآيفون (iCloud)")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        sub = QLabel("مواعيد الجلسات الجديدة تُرسَل تلقائيًا لتقويمك الافتراضي بالآيفون")
        sub.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        sub.setAlignment(th.ARIGHT)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(8)

        existing_apple_id, existing_app_pw = load_icloud_credentials()

        id_row = QHBoxLayout()
        self.apple_id_entry = _line_edit("بريد Apple ID", existing_apple_id or "", ltr=True)
        id_paste = SecondaryButton("📋 لصق")
        id_paste.clicked.connect(lambda: self._paste_into(self.apple_id_entry, "البريد"))
        id_row.addWidget(id_paste)
        id_row.addWidget(self.apple_id_entry, 1)
        lay.addLayout(id_row)
        lay.addSpacing(6)

        pw_row = QHBoxLayout()
        self.app_pw_entry = _line_edit("App-Specific Password (xxxx-xxxx-xxxx-xxxx)", existing_app_pw or "", ltr=True)
        pw_paste = SecondaryButton("📋 لصق")
        pw_paste.clicked.connect(lambda: self._paste_into(self.app_pw_entry, "كلمة المرور"))
        pw_row.addWidget(pw_paste)
        pw_row.addWidget(self.app_pw_entry, 1)
        lay.addLayout(pw_row)

        note = QLabel("تحصل عليه من appleid.apple.com ← الأمان ← كلمات مرور خاصة بالتطبيق\n(مب كلمة مرور حسابك الأصلية)")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:10px; border:none;")
        note.setAlignment(th.ARIGHT)
        lay.addSpacing(6)
        lay.addWidget(note)

        self.icloud_status_lbl = QLabel("")
        self.icloud_status_lbl.setStyleSheet(f"color:{th.EMERALD_TEXT}; font-size:11px; font-weight:700; border:none;")
        self.icloud_status_lbl.setAlignment(th.ARIGHT)
        lay.addSpacing(6)
        lay.addWidget(self.icloud_status_lbl)

        btn_row = QHBoxLayout()
        test_btn = SecondaryButton("🧪 اختبار")
        test_btn.clicked.connect(self._test_icloud)
        save_btn = PrimaryButton("💾 حفظ")
        save_btn.clicked.connect(self._save_icloud)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        btn_row.addWidget(test_btn)
        lay.addSpacing(4)
        lay.addLayout(btn_row)

        self._refresh_icloud_status()
        return card

    def _paste_into(self, entry, label):
        clip = QApplication.clipboard().text().strip()
        if not clip:
            QMessageBox.warning(self, "تنبيه", f"الحافظة فاضية — انسخ {label} أولاً، ثم اضغط لصق")
            return
        entry.setText(clip)

    def _refresh_icloud_status(self):
        aid, apw = load_icloud_credentials()
        if aid and apw:
            self.icloud_status_lbl.setText(f"✅ مربوط بحساب: {th.ltr(aid)}")
        else:
            self.icloud_status_lbl.setText("⚠️ لا يوجد حساب مربوط بعد")

    def _save_icloud(self):
        aid = self.apple_id_entry.text().strip()
        apw = self.app_pw_entry.text().strip()
        if not aid or not apw:
            QMessageBox.warning(self, "تنبيه", "يرجى تعبية البريد وكلمة المرور أولاً")
            return
        save_icloud_credentials(aid, apw)
        self._refresh_icloud_status()
        QMessageBox.information(self, "✅ تم", "تم حفظ بيانات تقويم iCloud بنجاح")

    def _test_icloud(self):
        self.icloud_status_lbl.setText("⏳ جاري الاختبار...")
        QApplication.processEvents()
        ok, info = test_icloud_connection()
        if ok:
            QMessageBox.information(self, "✅ الاتصال يعمل", f"تم الاتصال بنجاح بتقويم: {th.ltr(info)}")
        else:
            QMessageBox.critical(self, "❌ فشل الاتصال", f"تعذر الاتصال بـ iCloud:\n\n{th.ltr(info)}")
        self._refresh_icloud_status()

    # ---------- بطاقة 3: بيانات الخبير ----------
    def _build_expert_card(self):
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(4)

        title = QLabel("بيانات الخبير")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        sub = QLabel("تُضاف مرة واحدة. الشق التخصصي يُستخدم بمحاضر الاستعانة، والمقر/الدور/المكتب/الجناح بإخطارات الحكومة")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:10px; border:none;")
        sub.setAlignment(th.ARIGHT)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(8)

        existing_specialty = load_specialty()
        existing_loc = load_location()

        # كل خانة **سطر واحد**: التسمية يمين والحقل يسار (نفس ترتيب صفحة
        # «إضافة قضية») — الحقول تحت بعض وما فيه عمودين ضيقين (10/11/2026 —
        # طلب العنزي: رجّعها تحت بعض).
        def field(attr, label_text, placeholder, value=''):
            row = QWidget()
            r_lay = QHBoxLayout(row)
            r_lay.setContentsMargins(0, 0, 0, 0)
            r_lay.setSpacing(10)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(170)
            lbl.setWordWrap(True)
            lbl.setAlignment(th.ARIGHT)
            lbl.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:11px; border:none;")
            r_lay.addWidget(lbl)
            e = _line_edit(placeholder, value)
            r_lay.addWidget(e, 1)
            setattr(self, attr, e)
            return row

        from expert_settings import load_report_header
        hdr = load_report_header()
        items = [
            ('specialty_entry', 'الشق التخصصي', 'مثال: حاسب آلي', existing_specialty),
            ('maqar_entry', 'المقر', 'مثال: مبنى الإدارة العامة للخبراء - الرقعي', existing_loc.get('maqar', '')),
            ('dor_entry', 'الدور', 'مثال: الثاني', existing_loc.get('dor', '')),
            ('maktab_entry', 'المكتب', 'مثال: 12', existing_loc.get('maktab', '')),
            ('janah_entry', 'الجناح', 'مثال: ب', existing_loc.get('janah', '')),
            ('gov_entry', 'المحافظة (ترويسة التقرير)',
             'تلقائي من النظام — غيّرها إذا كنت من قسم آخر', hdr['governorate']),
            ('dept_entry', 'القسم (ترويسة التقرير)',
             'تلقائي من النظام — مثال: قسم قضايا الكهرباء والكمبيوتر العاصمه', hdr['department']),
        ]
        for attr, label_text, placeholder, value in items:
            lay.addWidget(field(attr, label_text, placeholder, value))
            lay.addSpacing(6)
        lay.addSpacing(2)

        self.profile_status_lbl = QLabel("")
        self.profile_status_lbl.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:11px; border:none;")
        self.profile_status_lbl.setAlignment(th.ARIGHT)
        btn_row = QHBoxLayout()
        save_btn = PrimaryButton("💾 حفظ")
        save_btn.clicked.connect(lambda: self._save_expert())
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.profile_status_lbl)
        lay.addLayout(btn_row)

        # جلب تلقائي من الموقع عند فتح الإعدادات (بالخلفية، بدون زر)
        self._profile_ready.connect(self._apply_profile)
        self._start_profile_fetch()

        return card

    def _start_profile_fetch(self):
        if not self.cookies:
            return
        import threading
        self.profile_status_lbl.setText("⏳ جاري جلب بياناتك من الموقع...")

        def work():
            found = {}
            try:
                f, _raw = get_expert_profile_fields(self.cookies)
                found.update(f or {})
            except Exception:
                pass
            # المحافظة/القسم: من سجل الحركة لآخر قضية (نفس مصدر المحضر)
            try:
                found.update(self._fetch_section_fields())
            except Exception:
                pass
            self._profile_ready.emit(found)
        threading.Thread(target=work, daemon=True).start()

    def _recent_caso_nos(self, limit=4):
        """أرقام آخر قضايا هذا الخبير (من القاعدة المحلية) — لمصدر المحافظة/القسم."""
        import case_db
        try:
            casos = set(case_db.get_active_cases(self.current_user))
        except Exception:
            casos = set()
        if not casos:
            try:
                casos = set(case_db.get_all_caso_nos())
            except Exception:
                casos = set()
        rows = []
        for c in casos:
            try:
                d = case_db.get_case(c) or {}
            except Exception:
                d = {}
            exp = (d.get('expert_name') or '').strip()
            if exp and self.current_user and exp != self.current_user:
                continue
            stamp = (d.get('updated_at') or d.get('received_date') or '')
            rows.append((stamp, c))
        rows.sort(reverse=True)
        return [c for _, c in rows[:limit]]

    def _fetch_section_fields(self):
        """
        المحافظة/القسم من **سجل الحركة** لآخر قضية لهذا الخبير: خانة القسم
        بعد «توزيع للخبراء» (نفس المصدر اللي يقرأه المحضر) — مثل
        «قسم قضايا الكهرباء والكمبيوتر العاصمه» ⟵ المحافظة «العاصمة».
        تُملأ الحقول الفاضية فقط، فما تكتب فوق ما ضبطه الخبير.
        """
        from api import parse_case_info
        for caso in self._recent_caso_nos(2):
            try:
                info = parse_case_info(caso, self.cookies, self.current_user)
            except Exception:
                continue
            gov = (info.get('governorate') or '').strip()
            dep = (info.get('department') or '').strip()
            if gov or dep:
                return {'governorate': gov, 'department': dep}
        return {}

    def _apply_profile(self, found):
        """يعبّي الحقول الفاضية فقط (لا يكتب فوق ما أدخله الخبير يدويًا) ويحفظ تلقائيًا."""
        if not found:
            self.profile_status_lbl.setText("")
            return
        fields = [('specialty', self.specialty_entry), ('maqar', self.maqar_entry),
                  ('dor', self.dor_entry), ('maktab', self.maktab_entry),
                  ('janah', self.janah_entry),
                  ('governorate', self.gov_entry), ('department', self.dept_entry)]
        filled = 0
        for key, entry in fields:
            if found.get(key) and not entry.text().strip():
                entry.setText(found[key])
                filled += 1
        if filled:
            self._save_expert(silent=True)
            self.profile_status_lbl.setText("✅ تم جلب بياناتك من الموقع وحفظها تلقائيًا")
        else:
            self.profile_status_lbl.setText("")

    def _save_expert(self, silent=False):
        specialty = self.specialty_entry.text().strip()
        if specialty:
            save_specialty(specialty)
        from expert_settings import save_report_header
        save_report_header(self.gov_entry.text(), self.dept_entry.text())
        save_location(
            maqar=self.maqar_entry.text().strip(),
            dor=self.dor_entry.text().strip(),
            maktab=self.maktab_entry.text().strip(),
            janah=self.janah_entry.text().strip(),
        )
        if not silent:
            QMessageBox.information(self, "✅ تم", "تم حفظ بيانات الخبير بنجاح")

    # ---------- بطاقة 4: تشخيص سجل حركة قضية (أداة تطوير مؤقتة) ----------
    def _build_reports_root_card(self):
        import case_workspace
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)
        title = QLabel("📁 مجلد حفظ مستندات القضايا")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        sub = QLabel("مجلد لكل رقم خبرة فيه كل مستنداتها، والمحاضر تُحفظ داخل مجلد كل قضية في «محاضر». "
                     "اضغط الخانة لاختيار المجلد؛ فارغ = الافتراضي")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:10px; border:none;")
        sub.setAlignment(th.ARIGHT)
        lay.addWidget(title)
        lay.addWidget(sub)
        row = QHBoxLayout()
        self.reports_root_entry = _path_edit(case_workspace.default_root(), load_reports_root(),
                                             "اختر مجلد حفظ مستندات القضايا")
        save_btn = PrimaryButton("💾 حفظ")
        save_btn.clicked.connect(self._save_reports_root)
        row.addWidget(save_btn)
        row.addWidget(self.reports_root_entry, 1)
        lay.addSpacing(4)
        lay.addLayout(row)
        return card

    def _save_reports_root(self):
        import os
        import case_workspace
        path = self.reports_root_entry.text().strip()
        if path:
            if not os.path.isabs(path):
                QMessageBox.warning(self, "تنبيه", "اكتب مساراً كاملاً (مثل C:\تقارير)")
                return
            try:
                case_workspace.check_path_lengths(os.path.join(path, "A0000000"))
            except case_workspace.WorkspaceError as e:
                QMessageBox.warning(self, "تنبيه", str(e))
                return
        save_reports_root(path)
        QMessageBox.information(self, "✅ تم", "تم حفظ مجلد حفظ مستندات القضايا")

    def _build_minutes_root_card(self):
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)
        title = QLabel("📁 مكان حفظ المحاضر")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        sub = QLabel("تُحفظ فيه محاضر الجلسات (مجلد لكل رقم خبرة)، ومنه تأخذ خطوة «الإجراءات» محاضر القضية تلقائياً. "
                     "اتركه فارغاً للافتراضي (سطح المكتب\\محاضر)")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:10px; border:none;")
        sub.setAlignment(th.ARIGHT)
        lay.addWidget(title)
        lay.addWidget(sub)
        row = QHBoxLayout()
        cur = load_minutes_root()
        self.minutes_root_entry = _line_edit(default_minutes_root(),
                                             '' if cur == default_minutes_root() else cur, ltr=True)
        save_btn = PrimaryButton("💾 حفظ")
        save_btn.clicked.connect(self._save_minutes_root)
        row.addWidget(save_btn)
        row.addWidget(self.minutes_root_entry, 1)
        lay.addSpacing(4)
        lay.addLayout(row)
        return card

    def _save_minutes_root(self):
        import os
        path = self.minutes_root_entry.text().strip()
        if path and not os.path.isabs(path):
            QMessageBox.warning(self, "تنبيه", "اكتب مساراً كاملاً (مثل C:\\محاضر)")
            return
        save_minutes_root(path)
        QMessageBox.information(self, "✅ تم", "تم حفظ مكان المحاضر")

    def _build_access_card(self):
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)

        title = QLabel("👥 صلاحية «إضافة قضية جديدة»")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        sub = QLabel("امنح أي خبير صلاحية إضافة القضايا الجديدة عبر اسمه — تُحفظ على القاعدة"
                     " الأونلاين وتظهر عنده على أي جهاز فورًا، بدون تحديث البرنامج")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:10px; border:none;")
        sub.setAlignment(th.ARIGHT)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(8)

        manage_btn = SecondaryButton("👥 إدارة الخبراء المخوّلين")
        manage_btn.clicked.connect(self._open_access_manager)
        lay.addWidget(manage_btn, 0, Qt.AlignmentFlag.AlignRight)
        return card

    # ---------- بطاقة: إعدادات التحديث (للأدمن/المالك فقط) ----------
    def _build_update_card(self):
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)

        title = QLabel("🔄 إعدادات التحديث")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        sub = QLabel("مصدران للتحديث: الأول مجلد على شبكة الدوام (يُوضع فيه ملف EXE الجديد)، "
                     "وبعده رابط أونلاين يُجرّب لو الشبكة الداخلية مو متاحة. "
                     "عند الحفظ يُنشر المصدران مع رقم النسخة لكل الأجهزة.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:10px; border:none;")
        sub.setAlignment(th.ARIGHT)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(8)

        ver_lbl = QLabel(f"النسخة الحالية: {th.ltr(APP_VERSION)}")
        ver_lbl.setStyleSheet(f"color:{th.EMERALD_TEXT}; font-size:11px; font-weight:700; border:none;")
        ver_lbl.setAlignment(th.ARIGHT)
        lay.addWidget(ver_lbl)

        row = QHBoxLayout()
        self.update_folder_entry = _path_edit(
            r"\\10.220.191.151\ExpertAppUpdates", load_update_folder(), "اختر مكان البرنامج (مجلد التحديثات)")
        save_btn = PrimaryButton("💾 حفظ ونشر")
        save_btn.clicked.connect(self._save_update_folder)
        self.update_version_entry = _line_edit(
            "1.0.2", load_update_version() or APP_VERSION, ltr=True)
        self.update_version_entry.setMaximumWidth(110)
        row.addWidget(save_btn)
        row.addWidget(self.update_version_entry)
        row.addWidget(self.update_folder_entry, 1)
        lay.addSpacing(4)
        lay.addLayout(row)

        # المصدر الثاني: رابط أونلاين (يُجرّب بعد الداخلي)
        import updater as _updater
        row2 = QHBoxLayout()
        self.update_online_entry = _line_edit(
            _updater.GITHUB_RELEASES_PAGE,
            load_update_online_url() or _updater.GITHUB_RELEASES_PAGE, ltr=True)
        row2.addWidget(_field_label("رابط أونلاين:"))
        row2.addWidget(self.update_online_entry, 1)
        lay.addSpacing(4)
        lay.addLayout(row2)
        return card

    def _save_update_folder(self):
        # حماية مضاعفة: البطاقة أصلاً لا تُبنى إلا للمالك، ونتحقق هنا مرة ثانية
        if not main1_access.is_owner(self.current_user, get_current_account()):
            return
        path = self.update_folder_entry.text().strip()
        if not path:
            QMessageBox.warning(self, "تنبيه", "يرجى كتابة مسار مجلد التحديثات أولاً")
            return
        version = self.update_version_entry.text().strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            QMessageBox.warning(self, "تنبيه", "صيغة رقم النسخة غير صحيحة — استخدم الشكل 1.0.2")
            return
        online = self.update_online_entry.text().strip() if hasattr(self, 'update_online_entry') else ''
        save_update_folder(path)
        save_update_version(version)
        if online:
            save_update_online_url(online)
        import updater
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        ok, err = updater.publish_app_version(path, version, online_url=online)
        QApplication.restoreOverrideCursor()
        if ok:
            QMessageBox.information(self, "✅ تم", "تم حفظ المصدرين ونشر رقم النسخة للسحابة")
        else:
            QMessageBox.critical(self, "❌ فشل النشر",
                f"تم حفظ المسار محليًا لكن تعذر رفعه للسحابة:\n\n{th.ltr(err)}")

    def _open_access_manager(self):
        from qt_main1_access_dialog import open_main1_access_dialog
        open_main1_access_dialog(self, self.current_user)

    # ---------- بطاقة: تشخيص اتصال Gemini (للأدمن فقط) ----------
    def _build_net_diag_card(self):
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)

        title = QLabel("🌐 تشخيص اتصال الذكاء الاصطناعي")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        lay.addWidget(title)

        self.net_status_lbl = QLabel("")
        self.net_status_lbl.setWordWrap(True)
        self.net_status_lbl.setStyleSheet(f"color:{th.EMERALD_TEXT}; font-size:11px; font-weight:700; border:none;")
        self.net_status_lbl.setAlignment(th.ARIGHT)
        lay.addWidget(self.net_status_lbl)

        self.net_log_lbl = QLabel("")
        self.net_log_lbl.setWordWrap(True)
        self.net_log_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.net_log_lbl.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:10px; border:none;")
        self.net_log_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.net_log_lbl.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        lay.addWidget(self.net_log_lbl)

        from gemini_config import get_pdf_settings
        pc = get_pdf_settings()
        trim_lbl = QLabel("قص حكم الإحالة: حد القص / صفحات البداية / صفحات النهاية")
        trim_lbl.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:10px; border:none;")
        trim_lbl.setAlignment(th.ARIGHT)
        lay.addSpacing(6)
        lay.addWidget(trim_lbl)
        trim_row = QHBoxLayout()
        self.pdf_trim_entry = _line_edit("3", str(pc['trim_threshold']), ltr=True)
        self.pdf_head_entry = _line_edit("1", str(pc['head_pages']), ltr=True)
        self.pdf_tail_entry = _line_edit("2", str(pc['tail_pages']), ltr=True)
        pdf_save_btn = SecondaryButton("💾 حفظ")
        pdf_save_btn.clicked.connect(self._save_pdf_settings)
        trim_row.addWidget(pdf_save_btn)
        for w in (self.pdf_tail_entry, self.pdf_head_entry, self.pdf_trim_entry):
            w.setMaximumWidth(70)
            trim_row.addWidget(w)
        trim_row.addStretch()
        lay.addLayout(trim_row)

        self.net_recheck_btn = SecondaryButton("🔄 إعادة فحص الاتصال")
        self.net_recheck_btn.clicked.connect(self._recheck_net)
        lay.addSpacing(6)
        lay.addWidget(self.net_recheck_btn, 0, Qt.AlignmentFlag.AlignRight)

        self._refresh_net_diag()
        return card

    def _refresh_net_diag(self):
        from gemini_config import get_connection_status, read_log_tail, ROUTE_LABELS
        st = get_connection_status()
        if st['checking']:
            txt = "⏳ جاري فحص الاتصال..."
        elif not st['checked']:
            txt = "لم يتم الفحص بعد"
        else:
            ok = "✅ متصل" if st.get('connected') else "❌ لا يوجد اتصال"
            txt = (f"{ok} — الطريق المعتمد: {ROUTE_LABELS[st['route']]}"
                   f" — آخر فحص {st['last_check']}\n{st['detail']}")
        self.net_status_lbl.setText(txt)
        lines = read_log_tail(15)
        self.net_log_lbl.setText("\n".join(l[:400] for l in lines) or "لا توجد أخطاء مسجلة")

    def _save_pdf_settings(self):
        from gemini_config import save_pdf_settings
        ok, msg = save_pdf_settings(self.pdf_trim_entry.text(),
                                    self.pdf_head_entry.text(),
                                    self.pdf_tail_entry.text())
        (QMessageBox.information if ok else QMessageBox.warning)(self, "حفظ" if ok else "تنبيه", msg)

    def _recheck_net(self):
        import threading
        from gemini_config import check_connection
        self.net_recheck_btn.setEnabled(False)
        threading.Thread(target=check_connection, daemon=True).start()
        self._net_timer = QTimer(self)
        self._net_timer.timeout.connect(self._poll_net)
        self._net_timer.start(500)
        self._refresh_net_diag()

    def _poll_net(self):
        from gemini_config import get_connection_status
        self._refresh_net_diag()
        if not get_connection_status()['checking']:
            self._net_timer.stop()
            self.net_recheck_btn.setEnabled(True)

    # ---------- المزودات الاحتياطية (للأدمن فقط) ----------
    def _provider_head_text(self, p):
        key = f"🔑 {p['masked']}" if p['has_key'] else "⚠️ بدون مفتاح"
        return f"{p['name']} — {p['model']}   {key}"

    def _build_providers_card(self):
        from PyQt6.QtWidgets import QCheckBox
        from ai_providers import list_providers_for_admin
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)
        title = QLabel("🤖 المزودات الاحتياطية للذكاء الاصطناعي")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        sub = QLabel("المزود المفعّل هنا يُفعَّل لكل خبراء القسم تلقائيًا (حتى بدون مفتاح خاص)."
                     " الترتيب بالأولوية (الرقم الأصغر أولًا). اترك خانة المفتاح فاضية"
                     " للإبقاء على المفتاح الحالي.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:10px; border:none;")
        sub.setAlignment(th.ARIGHT)
        lay.addWidget(title)
        lay.addWidget(sub)

        # مصدر الإعدادات (Supabase / نسخة محلية) — الحفظ يفعّل المفتاح لكل القسم
        self.sb_status_lbl = QLabel("")
        self.sb_status_lbl.setWordWrap(True)
        self.sb_status_lbl.setStyleSheet(f"color:{th.EMERALD_TEXT}; font-size:11px; font-weight:700; border:none;")
        self.sb_status_lbl.setAlignment(th.ARIGHT)
        lay.addSpacing(6)
        lay.addWidget(self.sb_status_lbl)
        import provider_sync
        from PyQt6.QtWidgets import QCheckBox
        self.share_chk = QCheckBox("السماح للقسم باستخدام مفاتيحي")
        self.share_chk.setChecked(provider_sync.is_shared())
        self.share_chk.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:12px; font-weight:700;")
        self.share_chk.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.share_chk.toggled.connect(self._toggle_share)
        lay.addWidget(self.share_chk, 0, Qt.AlignmentFlag.AlignRight)
        self._refresh_sb_status()

        self._prov_rows = {}
        for p in list_providers_for_admin():
            name = p['name']
            head = QLabel(self._provider_head_text(p))
            head.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:12px; font-weight:700; border:none;")
            head.setAlignment(th.ARIGHT)
            lay.addSpacing(8)
            lay.addWidget(head)
            row = QHBoxLayout()
            key = _line_edit("الصق المفتاح الجديد هنا", ltr=True)
            key.setEchoMode(QLineEdit.EchoMode.Password)
            prio = _line_edit("الأولوية", str(p['priority']), ltr=True)
            prio.setMaximumWidth(70)
            en = QCheckBox("مفعّل")
            en.setChecked(p['enabled'])
            save = PrimaryButton("✅ حفظ وتفعيل للقسم")
            test = SecondaryButton("🧪 اختبار")
            delete = SecondaryButton("🗑 حذف المفتاح")
            save.clicked.connect(lambda _=False, n=name: self._save_provider(n))
            test.clicked.connect(lambda _=False, n=name: self._test_provider(n))
            delete.clicked.connect(lambda _=False, n=name: self._delete_provider_key(n))
            for w in (delete, test, save, en, prio):
                row.addWidget(w)
            row.addWidget(key, 1)
            lay.addLayout(row)
            self._prov_rows[name] = (key, prio, en, head)
        return card

    def _refresh_sb_status(self):
        import provider_sync
        share = "✅ مفعّلة للقسم" if provider_sync.is_shared() else "⛔ موقوفة عن القسم (تعمل عندك فقط)"
        self.sb_status_lbl.setText(f"مفاتيحك: {share}\nمصدر إعدادات المزودات: {provider_sync.status()['source']}")

    def _toggle_share(self, enabled):
        import provider_sync
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok, msg = provider_sync.set_shared(enabled)
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            self.share_chk.blockSignals(True)
            self.share_chk.setChecked(not enabled)
            self.share_chk.blockSignals(False)
        self._refresh_sb_status()
        (QMessageBox.information if ok else QMessageBox.warning)(self, "المشاركة" if ok else "تنبيه", msg)

    def _refresh_provider_head(self, name):
        from ai_providers import list_providers_for_admin
        p = next(x for x in list_providers_for_admin() if x['name'] == name)
        self._prov_rows[name][3].setText(self._provider_head_text(p))

    def _save_provider(self, name):
        from ai_providers import save_provider_config
        key, prio, en, _ = self._prov_rows[name]
        try:
            pr = int(prio.text())
        except ValueError:
            QMessageBox.warning(self, "تنبيه", "الأولوية يجب أن تكون رقمًا")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok, msg = save_provider_config(name, api_key=key.text().strip() or None,
                                           enabled=en.isChecked(), priority=pr)
        finally:
            QApplication.restoreOverrideCursor()
        key.clear()
        self._refresh_provider_head(name)
        self._refresh_sb_status()
        (QMessageBox.information if ok else QMessageBox.warning)(self, "حفظ" if ok else "تنبيه", msg)

    def _delete_provider_key(self, name):
        from ai_providers import save_provider_config
        if QMessageBox.question(self, "تأكيد", f"حذف مفتاح {name}؟") != QMessageBox.StandardButton.Yes:
            return
        ok, msg = save_provider_config(name, api_key='')
        self._refresh_provider_head(name)
        (QMessageBox.information if ok else QMessageBox.warning)(self, "حذف", msg)

    def _test_provider(self, name):
        from ai_providers import test_provider
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok, msg = test_provider(name)
        finally:
            QApplication.restoreOverrideCursor()
        if ok:
            QMessageBox.information(self, "✅ يعمل", msg)
        else:
            QMessageBox.critical(self, "❌ فشل", th.ltr(msg))

    def _build_debug_card(self):
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)

        title = QLabel("🛠️ تشخيص سجل حركة قضية")
        title.setStyleSheet(f"color:{th.TEXT_PRIMARY}; font-size:14px; font-weight:700; border:none;")
        title.setAlignment(th.ARIGHT)
        sub = QLabel("يصدّر ملف نصي فيه كل خلايا سجل الحركة الخام لقضية معيّنة، مرقّمة —"
                     " يستخدم فقط لتشخيص مشاكل الإحصائية (لا يغيّر أي شي بالبرنامج)")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{th.TEXT_MUTED}; font-size:10px; border:none;")
        sub.setAlignment(th.ARIGHT)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(8)

        row = QHBoxLayout()
        self.debug_case_entry = _line_edit("رقم الخبرة (مثال: A2261234)", ltr=True)
        dump_btn = SecondaryButton("📄 تصدير التشخيص")
        dump_btn.clicked.connect(self._dump_case_flow)
        row.addWidget(dump_btn)
        row.addWidget(self.debug_case_entry, 1)
        lay.addLayout(row)

        return card

    def _dump_case_flow(self):
        caso_no = self.debug_case_entry.text().strip().upper()
        if not caso_no:
            QMessageBox.warning(self, "تنبيه", "أدخل رقم الخبرة أولاً")
            return
        if not self.cookies:
            QMessageBox.warning(self, "تنبيه", "لا يوجد اتصال حالي بالنظام")
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            import os
            from case_stats import dump_case_flow_debug, get_my_name
            my_name = get_my_name(self.cookies)
            text = dump_case_flow_debug(self.cookies, caso_no, my_name)
            out_dir = os.path.join(os.path.expanduser("~"), "Desktop")
            path = os.path.join(out_dir, f"تشخيص_{caso_no}.txt")
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "خطأ", f"تعذر التصدير:\n{th.ltr(e)}")
            return
        QApplication.restoreOverrideCursor()
        os.startfile(path)
