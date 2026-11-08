# ===== qt_context_menu.py — قائمة السياق الموحّدة لكل حقول النص (2026-10-17) =====
# مرشّح أحداث على مستوى التطبيق يعترض النقر الأيمن في QLineEdit/QTextEdit/QPlainTextEdit (وما يرثها) ويعرض بدل قائمة
# Qt القياسية (السوداء/الإنجليزية/فيها «Insert Unicode control character») قائمة فاتحة بعناوين عربية:
# تراجع، إعادة، قص، نسخ، لصق، حذف، تحديد الكل. الاختصارات (Ctrl+C…) تبقى لـQt كما هي؛ المكتوب بجانب العنوان نصّ عرض فقط.
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QLineEdit, QMenu, QPlainTextEdit, QTextEdit

import qt_theme as th

MENU_FONT_STACK = '"IBM Plex Sans Arabic", "Tajawal", "Segoe UI"'
_TEXT_WIDGETS = (QLineEdit, QTextEdit, QPlainTextEdit)

MENU_QSS = f"""
QMenu {{
    background: #FFFFFF; color: {th.NAVY}; border: 1px solid {th.BORDER};
    border-radius: 8px; padding: 6px 0; font-family: {MENU_FONT_STACK}; font-size: 14px;
}}
QMenu::item {{ background: transparent; color: {th.NAVY}; padding: 7px 18px 7px 18px; margin: 0 6px; border-radius: 6px; }}
QMenu::item:selected {{ background: {th.NAVY_TINT}; color: {th.NAVY}; }}
QMenu::item:disabled {{ color: {th.TEXT_MUTED}; background: transparent; }}
QMenu::separator {{ height: 1px; background: {th.BORDER_SOFT}; margin: 5px 10px; }}
"""

LABELS = {'undo': 'تراجع', 'redo': 'إعادة', 'cut': 'قص', 'copy': 'نسخ', 'paste': 'لصق',
          'delete': 'حذف', 'select_all': 'تحديد الكل'}
_SHORTCUTS = {'undo': 'Ctrl+Z', 'redo': 'Ctrl+Y', 'cut': 'Ctrl+X', 'copy': 'Ctrl+C', 'paste': 'Ctrl+V',
              'select_all': 'Ctrl+A'}


def _target(obj):
    """حقل النص صاحب الحدث: QTextEdit/QPlainTextEdit يصل الحدث إلى viewport فنصعد إلى الأب."""
    if isinstance(obj, _TEXT_WIDGETS):
        return obj
    parent = obj.parent() if isinstance(obj, QObject) else None
    return parent if isinstance(parent, (QTextEdit, QPlainTextEdit)) and parent.viewport() is obj else None


def _state(w):
    """{'read_only','has_selection','has_text','can_undo','can_redo'} لأي نوع حقل."""
    if isinstance(w, QLineEdit):
        return {'read_only': w.isReadOnly(), 'has_selection': w.hasSelectedText(), 'has_text': bool(w.text()),
                'can_undo': w.isUndoAvailable(), 'can_redo': w.isRedoAvailable()}
    doc = w.document()
    return {'read_only': w.isReadOnly(), 'has_selection': w.textCursor().hasSelection(),
            'has_text': not doc.isEmpty(), 'can_undo': doc.isUndoAvailable(), 'can_redo': doc.isRedoAvailable()}


def _delete_selection(w):
    if isinstance(w, QLineEdit):
        w.del_()
    else:
        w.textCursor().removeSelectedText()


def _clipboard_has_text():
    return bool(QApplication.clipboard().text())


def styled_menu(parent, title=''):
    """قائمة منسدلة بنمط فاتح صريح. لازم لأي QMenu داخل ودجة لها نمط بلا محدِّد («background:transparent;»): النمط
    يتسرّب للقائمة فتظهر صندوقاً أسود فارغاً على ويندوز (خلل زر 🔄 إعادة عمل OCR، 2026-10-20)."""
    menu = QMenu(parent)
    menu.setObjectName('unifiedContextMenu')
    menu.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    menu.setStyleSheet(MENU_QSS)
    if title:
        t = menu.addAction(title)
        t.setEnabled(False)
        menu.addSeparator()
    return menu


def build_menu(w, parent=None):
    """يبني قائمة الحقل w (دون عرضها). القائمة RTL بنمط فاتح وخط IBM Plex Sans Arabic."""
    s = _state(w)
    ro, sel = s['read_only'], s['has_selection']
    menu = QMenu(parent or w)
    menu.setObjectName('unifiedContextMenu')
    menu.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    menu.setStyleSheet(MENU_QSS)
    menu.setSeparatorsCollapsible(True)

    def act(key, enabled, slot):
        text = LABELS[key] + (f'\t{_SHORTCUTS[key]}' if key in _SHORTCUTS else '')
        a = QAction(text, menu)
        a.setEnabled(bool(enabled))
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    if not ro:
        act('undo', s['can_undo'], w.undo)
        act('redo', s['can_redo'], w.redo)
        menu.addSeparator()
        act('cut', sel, w.cut)
    act('copy', sel, w.copy)
    if not ro:
        act('paste', _clipboard_has_text(), w.paste)
        act('delete', sel, lambda: _delete_selection(w))
    menu.addSeparator()
    act('select_all', s['has_text'], w.selectAll)
    return menu


class _Filter(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Type.ContextMenu:
            return False
        w = _target(obj)
        if w is None:
            return False
        if not w.isEnabled():
            return True
        if not w.hasFocus():
            w.setFocus(Qt.FocusReason.MouseFocusReason)
        menu = build_menu(w)
        pos = ev.globalPos() if hasattr(ev, 'globalPos') else w.mapToGlobal(w.rect().center())
        menu.exec(pos)
        menu.deleteLater()
        return True


_FILTER = None


def install(app=None):
    """يثبّت المرشّح مرة واحدة على التطبيق كله (آمن للاستدعاء المتكرر)."""
    global _FILTER
    app = app or QApplication.instance()
    if app is None or _FILTER is not None:
        return _FILTER
    _FILTER = _Filter(app)
    app.installEventFilter(_FILTER)
    return _FILTER
