# ===== qt_case_track.py — مسار قضية التقرير (المرحلتان 2و و«التوصيل») =====
# CaseTrackWidget: قائمة بعلامات (○ ◐ ⚠ ✎ ✓ ✗ ⊘) تقرأ case.json فقط وتُطلق action(key, action) — بلا منطق حالات.
# CaseTrackDialog: يوصّل كل خطوة بمنطقها (case_*.py) وينفّذ الطويل في خيط خلفي، ويحدّث العرض بمؤقّت أثناء العمل.
import os
import threading

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDialog, QMessageBox, QInputDialog, QFileDialog,
)

import qt_theme as th
from qt_widgets import PrimaryButton, SecondaryButton

import ai_call_log
import case_attachments
import case_autoreview
import case_conclusion
import case_documents
import case_model
import case_procedures
import case_research
import case_subject_mission
import case_subject_telecom
import case_workspace
import report_docx
import qt_documents_dialog as qdd
from qt_review_dialogs import MinutesEditDialog, SubjectReviewDialog, show_saved_toast

SYMBOLS = {
    'pending': '○', 'running': '◐', 'needs_input': '⚠', 'done': '✎',
    'reviewed': '✓', 'failed': '✗', 'blocked': '⊘',
}
COLORS = {
    'pending': th.TEXT_MUTED, 'running': th.NAVY, 'needs_input': '#B54708', 'done': th.NAVY,
    'reviewed': th.EMERALD_TEXT, 'failed': '#B42318', 'blocked': th.TEXT_MUTED,
}
ADD_LABEL = {'subject': 'أدخل الموضوع', 'mission': 'راجع واعتمد', 'procedures': 'إضافة محضر آخر',
             'documents': 'إضافة مستندات'}
MAX_ACTIONS = 3


def actions_for(data, key):
    """أزرار السطر: [(action, نص)] حسب الحالة (دالة صرفة للاختبار)."""
    rec = (data.get('steps') or {}).get(key) or {}
    state, stale = rec.get('state', 'pending'), rec.get('stale')
    out = []
    if key == 'attachments':                       # تُبنى وتتجدد آلياً؛ لا زر بدء
        if state == 'done':
            out.append(('review', 'راجعتها'))
        return out
    if key == 'procedures':                        # تلقائية بالكامل (تحقق/حضور/اعتماد)؛ الأزرار للتعديل فقط
        if state == 'running':
            return out
        if state in ('pending', 'failed'):
            out.append(('run', 'ابدأ' if state == 'pending' else 'أعد المحاولة'))
        return out + [('add', ADD_LABEL['procedures']), ('attend', 'تعديل')]
    if state == 'pending':
        if key == 'documents':
            out.append(('add', ADD_LABEL['documents']))
        elif case_model.can_start(data, key)[0]:
            out.append(('run', 'ابدأ'))
    elif state == 'needs_input':
        if key == 'subject' and (data.get('subject') or '').strip():
            out.append(('review', 'راجع واعتمد'))
        else:
            out.append(('add', ADD_LABEL.get(key, 'أضف')))
    elif state == 'failed':
        out.append(('retry', 'أعد المحاولة'))
        if key in ('documents', 'research'):
            out.append(('waive', 'تابع رغم النقص'))
    elif state == 'done':
        out.append(('review', 'راجع واعتمد' if key in ('subject', 'mission') else 'راجعتها'))
        if key == 'documents':
            out.append(('add', ADD_LABEL['documents']))
    elif state == 'reviewed' and key in ('subject', 'mission'):
        out.append(('add' if key == 'mission' else 'review', 'عدّل'))
    if state in case_model.OK_STATES and stale and key not in ('subject', 'mission', 'procedures', 'documents'):
        out.insert(0, ('run', 'حدّث'))
    return out[:MAX_ACTIONS]


def row_model(data, key):
    """وصف سطر واحد من case.json: الرمز، العنوان، النص، الأزرار، اللون."""
    rec = (data.get('steps') or {}).get(key) or {}
    state = rec.get('state', 'pending')
    text = case_model.STATE_TEXT.get(state, state)
    prog = rec.get('progress')
    if isinstance(prog, dict) and 'done' in prog:
        text += f" ({prog['done']}/{prog['total']})"
    if rec.get('stale'):
        text += ' — تحتاج تحديثاً'
    if rec.get('message'):
        text += f" — {rec['message']}"
    return {'key': key, 'state': state, 'symbol': SYMBOLS.get(state, '○'),
            'label': case_model.STEP_LABELS[key], 'text': text,
            'actions': actions_for(data, key), 'color': COLORS.get(state, th.TEXT_MUTED)}


class CaseTrackWidget(QWidget):
    action = pyqtSignal(str, str)           # (مفتاح الخطوة، الإجراء: run/retry/add/review/waive)

    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(6)
        self._rows = {}
        for key in case_model.STEP_KEYS:
            row = QHBoxLayout()
            sym = QLabel()
            sym.setFixedWidth(22)
            sym.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl = QLabel()
            lbl.setWordWrap(True)
            lbl.setAlignment(th.ARIGHT)
            btns = []
            row.addWidget(sym)
            row.addWidget(lbl, 1)
            for _ in range(MAX_ACTIONS):
                b = SecondaryButton('')
                b.clicked.connect(lambda _=False, k=key, b=b: self.action.emit(k, b.property('action') or ''))
                row.addWidget(b)
                btns.append(b)
            self._lay.addLayout(row)
            self._rows[key] = (sym, lbl, btns)
        self._enabled = True
        if data:
            self.set_data(data)

    def set_data(self, data):
        for key in case_model.STEP_KEYS:
            m = row_model(data, key)
            sym, lbl, btns = self._rows[key]
            sym.setText(m['symbol'])
            sym.setStyleSheet(f"color:{m['color']}; font-size:16px; border:none;")
            lbl.setText(f"<b>{m['label']}:</b> {m['text']}".replace('\n', '<br>'))
            lbl.setStyleSheet(f"color:{m['color']}; font-size:13px; border:none;")
            for i, b in enumerate(btns):
                if i < len(m['actions']):
                    b.setProperty('action', m['actions'][i][0])
                    b.setText(m['actions'][i][1])
                    b.setVisible(True)
                else:
                    b.setProperty('action', '')
                    b.setVisible(False)

    def set_actions_enabled(self, on):
        self._enabled = on
        for _, _, btns in self._rows.values():
            for b in btns:
                b.setEnabled(on)


class CaseTrackDialog(QDialog):
    """المسار: يوصّل أزرار الخطوات بمنطقها. أي عمل طويل في خيط خلفي واحد في كل مرة."""
    _done = pyqtSignal(object)              # None أو Exception

    def __init__(self, base, data, parent=None, cookies=None, ask=None, fetch=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"تقرير {data['caso_no']}")
        self.setMinimumWidth(640)
        self.base, self.data = base, data
        self.cookies, self._ask, self._fetch = cookies, ask, fetch
        self._busy, self._stop = False, False
        self._after = None                  # يُنفَّذ بعد انتهاء المهمة الخلفية بنجاح (في خيط الواجهة)
        self._done.connect(self._on_done)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        path = QLabel(f"مجلد القضية: {th.ltr(base)}")
        path.setWordWrap(True)
        path.setAlignment(th.ARIGHT)
        path.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none;")
        lay.addWidget(path)
        self.folder_line = QLabel("")               # سطر مزامنة مجلد القضية: «جاهز» / «حوّلتُ N…» / ما تعذّر
        self.folder_line.setWordWrap(True)
        self.folder_line.setAlignment(th.ARIGHT)
        self.folder_line.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none;")
        lay.addLayout(self._make_folder_row(self.folder_line))
        self.track = CaseTrackWidget(parent=self)
        self.track.action.connect(self.do)
        lay.addWidget(self.track)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setAlignment(th.ARIGHT)
        self.status.setStyleSheet(f"color:{th.TEXT_SECONDARY}; font-size:12px; border:none;")
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        refresh = PrimaryButton("↻  تحديث")
        refresh.clicked.connect(lambda: self.reload())
        self.stop_btn = SecondaryButton("إيقاف")
        self.stop_btn.clicked.connect(self._request_stop)
        self.stop_btn.setVisible(False)
        self.report_btn = PrimaryButton("إصدار التقرير (Word)")
        self.report_btn.clicked.connect(self._do_report)
        open_btn = SecondaryButton("فتح المجلد")
        open_btn.clicked.connect(lambda: os.startfile(self.base))
        log_btn = SecondaryButton("سجل الذكاء الاصطناعي")
        log_btn.clicked.connect(self.show_ai_log)
        close = SecondaryButton("إغلاق")
        close.clicked.connect(self.accept)
        for b in (refresh, self.report_btn, self.stop_btn, open_btn, log_btn):
            btns.addWidget(b)
        btns.addStretch()
        btns.addWidget(close)
        lay.addLayout(btns)
        self._timer = QTimer(self)
        self._timer.setInterval(600)
        self._timer.timeout.connect(lambda: self.track.set_data(self.data))
        self._bg_timer = QTimer(self)               # تحويل مستندات بالخلفية بعد إغلاق نافذتها
        self._bg_timer.setInterval(1000)
        self._bg_timer.timeout.connect(self._poll_bg)
        self._bg_timer.start()
        self.reload(data)
        if self.AUTO_RESUME:
            QTimer.singleShot(0, self.auto_resume_documents)
        if self.AUTO_SYNC:
            QTimer.singleShot(0, lambda: self.sync_folder(fetch=True))

    AUTO_SYNC = True        # الاختبارات تعطّله
    AUTO_WRITE = True       # إعادة كتابة الموضوع/الإجراءات تلقائياً عند مصدر أحدث (case_autowrite)
    AUTO_CONTRACTS = True   # استخراج العقود بالذكاء بعد المزامنة (طلب واحد مخزّن ببصمة النصوص)
    AUTO_RESUME = True      # عملية مستندات توقفت (أُغلق البرنامج أثناءها) تُستأنف تلقائياً عند فتح القضية
    resume_failed = False

    def auto_resume_documents(self):
        """بلا «انقطعت سابقاً»: الجاهز للتحويل يُستأنف بالخلفية؛ إن تعذّر يظهر زر «استئناف» في خطوة المستندات."""
        if qdd.active_job(self.base) is not None or not case_documents.pending_docs(self.data):
            return False
        try:
            job = qdd.resume_documents(self.base, self.data)
        except Exception:
            job = None
        self.resume_failed = job is None
        if job is not None:
            self.status.setText("⏳ يُستأنف تحويل المستندات بالخلفية…")
        return job is not None

    # ---------- مجلد القضية (الأصل) ----------
    def sync_folder(self, fetch=False):
        """عند الفتح وبعد أي إضافة: البنية + الترحيل + (الجلب من النظام) + تحويل الجديد فقط، ثم المأمورية إن تغيّر الحكم."""
        if self._busy or qdd.live_data(self.base) is not None:
            return
        import case_folder

        # المراحل الثلاث (2026-10-21): هنا المرحلتان الأولى والثانية فقط. المرحلة الأولى = الفرز (طلب واحد لكل ملف،
        # مدمج في التحويل للممسوح)؛ العقد والعقود وحكم الإحالة والحضور وتاريخ الحجز كلها بالكود من الملخص (بلا طلبات).
        # المرحلة الثانية = الموضوع والإجراءات والمرفقات بطلب واحد، ولا يُعاد إلا إن تغيّر الملخص.
        import case_startup
        import case_stage2
        sort_ask = self._ask_for('الفرز') if self.AUTO_CONTRACTS else None
        stage2_ask = self._ask_for(case_stage2.PURPOSE)
        browser_stage2 = self._stage_mode('stage2') == 'browser'
        proc_job = self._procedures_job() if (fetch and self.cookies) else None

        def work():
            res = case_startup.run(self.base, self.data, self.cookies if fetch else None, ask=sort_ask,
                                   stop=lambda: self._stop)
            case_workspace.write_case_json(self.base, self.data)
            what = case_subject_mission.refresh_mission_if_changed(self.base, self.data)
            try:                                   # العقد المعتمد (من الفرز) في قائمة العقود
                import case_main_contract
                case_main_contract.republish(self.data)
            except Exception:
                pass
            case_workspace.write_case_json(self.base, self.data)
            self._count_line = (res.get('count') or {}).get('line', '')
            self._brief = case_folder.brief_status(res)
            msg = self._brief['line']
            new_min = [r for r in res['converted'] if case_folder.kind_of(r) == case_folder.MINUTES]
            if new_min and (self.data.get('procedures') or {}).get('auto_text'):
                # محضر جديد (يدوياً أو من النظام): الحضور وتاريخ الحجز من فرزه ← يُعاد حساب الإجراءات بالكود
                case_procedures.evaluate(self.base, self.data, None)
                msg += f' — أُعيد حساب الإجراءات بعد {len(new_min)} محضر جديد'
            if what == 'rerun':
                msg += ' — أُعيدت قراءة المأمورية من حكم الإحالة'
            elif what == 'flagged':
                msg += ' — تغيّر حكم الإحالة بعد اعتماد المأمورية: أعد قراءتها إن لزم'
            if proc_job is not None and self.AUTO_WRITE:   # تواريخ النظام والحضور قبل المرحلة الثانية (لا طلب ثانٍ لاحقاً)
                try:
                    proc_job()
                except Exception:
                    pass
            if self.AUTO_WRITE and not browser_stage2:      # المرحلة الثانية: تُعاد فقط إن تغيّر الملخص
                before = dict(case_stage2.state(self.data))
                st2 = case_stage2.run(self.base, self.data, stage2_ask)
                if st2.get('at') != before.get('at') and not st2.get('blocked'):
                    msg += (' — ' + st2['error']) if st2.get('error') else ' — كُتب الموضوع والإجراءات والمرفقات من الملخص'
            case_workspace.write_case_json(self.base, self.data)
            self._folder_msg = msg
        self._after = self._show_folder_line
        self._run_bg(work, "مزامنة مجلد القضية…")

    def _show_folder_line(self):
        """سطر واحد مختصر («تعذّر تحويل N ملفات») + «التفاصيل» (سبب كل ملف) + «أعد المحاولة»، بدل سيل الأخطاء."""
        brief = getattr(self, '_brief', None) or {'details': [], 'bad': False}
        msg = getattr(self, '_folder_msg', '')
        self.folder_line.setText("حالة الملفات: " + ('جاهز — كل مستندات القضية مقروءة ومحوَّلة' if msg == 'جاهز' else msg))
        self.folder_line.setStyleSheet(self.folder_line.styleSheet().split('color:')[0]
                                       + ("color:#b3261e; font-weight:700;" if brief['bad'] else ''))
        for b in self._folder_btns():
            b.setVisible(brief['bad'])

    def _make_folder_row(self, label):
        """السطر + زرا «التفاصيل» و«أعد المحاولة» (يظهران عند التعذّر فقط)."""
        row = QHBoxLayout()
        row.addWidget(label, 1)
        self.details_btn = SecondaryButton("التفاصيل")
        self.details_btn.clicked.connect(self._show_folder_details)
        self.retry_btn = SecondaryButton("أعد المحاولة")
        self.retry_btn.clicked.connect(lambda: self.sync_folder())
        for b in (self.details_btn, self.retry_btn):
            b.setVisible(False)
            row.addWidget(b)
        return row

    def _folder_btns(self):
        return [b for b in (getattr(self, 'details_btn', None), getattr(self, 'retry_btn', None)) if b is not None]

    def folder_details_text(self):
        import case_folder
        brief = getattr(self, '_brief', None) or {'details': []}
        return case_folder.details_text([(n, qdd.friendly_error(w)) for n, w in brief['details']])

    def _show_folder_details(self):
        QMessageBox.information(self, "تفاصيل ما تعذّر تحويله", self.folder_details_text() or "لا شيء.")

    # ---------- قراءة وعرض ----------
    def reload(self, data=None):
        if self._busy:
            return
        live = qdd.live_data(self.base)
        data = live or (data if isinstance(data, dict) else case_workspace.read_case_json(self.base))
        if data is None:
            QMessageBox.warning(self, "تعذّرت القراءة", "case.json غير موجود أو تالف ولا توجد نسخة سليمة.")
            return
        changed = False
        if live is None:        # لا نلمس خطوة running ما دام تحويل المستندات يعمل بالخلفية
            changed = case_model.recover_interrupted(data)
            if case_documents.recover_running(data):
                changed = True
            try:
                import case_sources
                case_sources.adopt_judgment(self.base, data)       # حكم محفوظ قديماً في Desktop\judgments يُربط بالقضية
            except Exception:
                pass
        changed = case_model.refresh_blocked(data) or changed
        if changed:
            case_workspace.write_case_json(self.base, data)
        self.data = data
        if live is None:        # المرفقات تتجدد وحدها من المحاضر والحوافظ
            try:
                case_attachments.sync_attachments(self.base, self.data)
            except Exception:
                pass
            try:
                if not getattr(self, '_report_running', False):      # إصدار Word لا يغيّر أي حالة
                    case_autoreview.run(self.base, self.data)      # الخطوات الآلية المكتملة تُعتمد وحدها
            except Exception:
                pass
        self.track.set_data(self.data)
        self._sync_report_btn()

    def _poll_bg(self):
        live = qdd.live_data(self.base)
        if live is not None and not self._busy:
            self.data = live
            self.track.set_data(live)

    def _sync_report_btn(self):
        self.report_btn.setEnabled(not self._busy)
        self.report_btn.setToolTip('يعمل في أي مرحلة: ما لم يكتمل يُترك «[يُكتب]» لتكمله في Word')

    def done(self, r):
        if self._busy:
            box = QMessageBox(self)
            box.setWindowTitle("عمل جارٍ")
            box.setText("العمل جارٍ، هل تريد إيقافه أم متابعته في الخلفية؟")
            stop = box.addButton("إيقافه", QMessageBox.ButtonRole.DestructiveRole)
            bg = box.addButton("متابعته في الخلفية", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("البقاء هنا", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is stop:
                self._stop = True               # يتوقف عند أقرب نقطة آمنة (بعد البند الجاري)
            elif clicked is not bg:
                return
        super().done(r)
        show_saved_toast(self.parent() or None, "تم الحفظ ✓")

    # ---------- التنفيذ ----------
    def do(self, key, action):
        if self._busy:
            return
        handler = getattr(self, f'_do_{key}', None)
        try:
            if action == 'review':
                self._review(key)
            elif action == 'waive':
                self._waive(key)
            elif action == 'resume':
                self.auto_resume_documents()
            elif handler:
                handler(action)
        except case_model.StepError as e:
            QMessageBox.warning(self, "لا يمكن", str(e))
        self.reload()

    def _run_bg(self, fn, text):
        """ينفّذ fn() في خيط خلفي؛ الأخطاء تُعرض عند الانتهاء."""
        self._last_job = (fn, text, getattr(self, '_after', None))     # لإعادة التشغيل بعد قرار الخبير في فشل مفتاحه الشخصي
        try:
            import ai_providers
            ai_providers.pop_key_failure()                             # فشل قديم لم يُعرض لا يتبع المهمة الجديدة
        except Exception:
            pass
        self._busy, self._stop = True, False
        self.track.set_actions_enabled(False)
        self.report_btn.setEnabled(False)
        self.status.setText(f"⏳ {text}")
        self._timer.start()

        def work():
            try:
                fn()
                self._done.emit(None)
            except Exception as e:
                self._done.emit(e)
        threading.Thread(target=work, daemon=True).start()

    def _on_done(self, err):
        if getattr(self, '_choice_active', False):                     # انتهت المهمة التي أُعيد تشغيلها بقرار الخبير
            import ai_providers
            ai_providers.clear_key_choice()
            self._choice_active = False
        self._timer.stop()
        self._busy = False
        self.stop_btn.setVisible(False)
        self.track.set_actions_enabled(True)
        self.status.setText("")
        after, self._after = self._after, None
        if isinstance(err, case_model.StepError):
            QMessageBox.warning(self, "لا يمكن", str(err))
        elif err is not None and type(err).__name__ == 'PersonalKeyFailure':
            pass                                          # نافذة الخيارات تُعرض في _offer_provider_choice (لا نافذتان)
        elif err is not None:
            QMessageBox.critical(self, "تعذّر التنفيذ", th.ltr(err))
        elif after:
            after()
        self.reload()
        self._report_running = False
        self._offer_provider_choice(stopped=err is not None and type(err).__name__ == 'PersonalKeyFailure')

    def show_ai_log(self):
        from qt_ai_log import AiLogDialog
        AiLogDialog(self.base, self).exec()

    def _request_stop(self):
        self._stop = True
        self.stop_btn.setEnabled(False)
        self.status.setText("⏳ سيتوقف بعد البند الجاري…")

    def _review(self, key):
        d, b = self.data, self.base
        if key == 'subject':
            SubjectReviewDialog(b, d, self).exec()          # الاعتماد بزر داخل النافذة فقط
        elif key == 'mission':
            from qt_mission_dialog import MissionDialog
            MissionDialog(b, d, self).exec()
        elif key == 'procedures':
            MinutesEditDialog(b, d, self, ask=self._procedures_ask()).exec()
        elif key == 'research':
            for it in d['research']:
                if it['state'] == 'done':
                    case_research.review_item(b, d, it['id'])
            case_model.set_step(d, 'research', 'reviewed')
            case_workspace.write_case_json(b, d)
        elif key == 'conclusion':
            case_conclusion.review_conclusion(b, d)
        else:
            case_model.set_step(d, key, 'reviewed')
            case_workspace.write_case_json(b, d)

    def _waive(self, key):
        if key == 'documents':
            case_documents.waive_documents(self.base, self.data, True)
        elif key == 'research':
            case_conclusion.waive_research(self.base, self.data, True)

    # ---------- الخطوات ----------
    def _do_subject(self, action):
        if action == 'add':
            text, ok = QInputDialog.getMultiLineText(self, "الموضوع", "اكتب موضوع القضية:", self.data.get('subject') or '')
            if ok:
                case_subject_mission.set_subject(self.base, self.data, text)
        elif action == 'review':
            dlg = SubjectReviewDialog(self.base, self.data, self)
            dlg.exec()
            if getattr(dlg, 'reread_requested', False):
                self._do_subject('reread')
        else:                                   # run/retry/rewrite: المرحلة الثانية (الموضوع والإجراءات والمرفقات بطلب واحد)
            import case_stage2
            ask = self._ask_for(case_stage2.PURPOSE)
            self._run_bg(lambda: case_stage2.run(self.base, self.data, ask, force=True, replace_manual=True),
                         "جارٍ كتابة الموضوع والإجراءات والمرفقات (طلب واحد)…")

    def _do_sources(self, action):
        """«تحديث من النظام» لحكم الإحالة: يجلب نسخة جديدة ويحفظها في مجلد القضية (إعادة قراءة المأمورية بعدها من زرها)."""
        if action != 'judgment':
            return
        if not self.cookies:
            raise case_model.StepError('لا اتصال بالنظام لتحديث الحكم.')
        import case_sources

        def work():
            if not case_sources.refresh_judgment(self.base, self.data, self.cookies):
                raise case_model.StepError('لم يُعثر على حكم إحالة في النظام.')
        self._run_bg(work, "تحديث حكم الإحالة من النظام…")
        self._after = lambda: QTimer.singleShot(0, self.sync_folder)     # يُحوَّل ثم تُعاد قراءة المأمورية

    def _do_mission(self, action):
        if action in ('run', 'retry'):
            self._run_bg(lambda: case_subject_mission.run_mission(self.base, self.data), "قراءة المأمورية…")
        else:
            from qt_mission_dialog import MissionDialog
            MissionDialog(self.base, self.data, self).exec()

    def _stage_mode(self, stage):
        """«جيميناي (API)» أو «عبر المتصفح» لمرحلة (browser_write)."""
        import browser_write
        return browser_write.mode(self.data, stage)

    _PURPOSE_STEP = {'الموضوع والإجراءات': 'subject', 'الموضوع': 'subject', 'الإجراءات': 'procedures', 'الحضور': 'procedures',
                     'فحص الجاهزية': 'research', 'البحث': 'research', 'اكتب رغم النقص': 'research',
                     'إعادة كتابة بند': 'research', 'النتيجة': 'conclusion', 'الأسئلة المهمة': 'questions',
                     'حكم الإحالة': 'mission'}

    def _ask_for(self, purpose):
        """مزوّد الذكاء الاصطناعي مغلَّفاً بالسجل (ai_call_log)؛ الفحص الفعلي للمزوّدين داخل الخيط الخلفي.
        المزوّد من «مزوّد كل مهمة» (ai_providers.PURPOSE_TASK)، ويُسجَّل «كُتب بواسطة» للخطوة في case.json."""
        import ai_providers
        task = ai_providers.PURPOSE_TASK.get(purpose)
        step = self._PURPOSE_STEP.get(purpose)
        base_ask = self._ask or (lambda prompt: case_research.default_ask(
            prompt, task, timeout=case_research.SHORT_TIMEOUTS.get(purpose)))
        wrapped = ai_call_log.wrap(base_ask, purpose, base=self.base)

        def call(prompt):
            out = wrapped(prompt)
            prov = ai_call_log.last_provider()
            if step and prov:
                self.data.setdefault('written_by', {})[step] = {
                    'provider': prov, 'model': ai_call_log.last_model(), 'purpose': purpose}
            return out
        return call

    def _ask_key_failure(self, f):
        """فشل مفتاح الخبير الشخصي: المهمة موقوفة ولم تنتقل لأي مزوّد آخر. يعرض السبب وخيارات بأزرار؛ ما يختاره يُطبَّق على
        إعادة تشغيل المهمة نفسها ويُذكر في «كُتب بواسطة». مفتاح القسم لا يُستعمل إلا بعد تأكيد صريح."""
        import ai_providers
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(f"تعذّر مفتاحك الشخصي لـ{f.label}")
        box.setText(f.message_ar())
        if f.detail:
            box.setDetailedText(f.detail)
        retry = box.addButton("أعد المحاولة", QMessageBox.ButtonRole.AcceptRole)
        alt = (box.addButton(f"استعمل {ai_providers.KIND_LABEL[f.alt]} (مفتاحك)", QMessageBox.ButtonRole.AcceptRole)
               if f.alt else None)
        section = (box.addButton("استعمل مفتاح القسم", QMessageBox.ButtonRole.DestructiveRole) if f.section else None)
        box.addButton("إلغاء", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is retry:
            use = 'retry'
        elif alt is not None and clicked is alt:
            use = 'alt'
        elif section is not None and clicked is section:
            ok = QMessageBox.question(
                self, "تأكيد استعمال مفتاح القسم",
                f"ستُرسل بيانات هذه المهمة عبر مفتاح {f.label} المشترك للقسم بدل مفتاحك الشخصي، ويُذكر ذلك في «كُتب بواسطة». هل توافق؟",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if ok != QMessageBox.StandardButton.Yes:
                return
            use = 'section'
        else:
            self.status.setText("أُلغيت المهمة بعد تعذّر مفتاحك الشخصي.")
            return
        job = getattr(self, '_last_job', None)
        if not job:
            self.status.setText("اضغط الزر نفسه مرة أخرى لإعادة التشغيل.")
            return
        ai_providers.set_key_choice(use, f)
        self._choice_active = True
        fn, text, after = job
        self._after = after
        self._run_bg(fn, text)

    def _offer_provider_choice(self, stopped=True):
        """بعد مهمة فشلت لغياب مزوّدها: ينبّه الخبير ويتيح بديلاً لعملية واحدة (لا انتقال صامت).
        stopped=False (المهمة اكتملت): فشل مفتاح في طلب جانبي تجاوزته المهمة لا يفتح نافذة الخيارات — سطر في الحالة فقط
        (25/10: انقطع طلب جانبي عند 180ث وانطبع التقرير، ثم ظهرت النافذة كأن المهمة توقفت)."""
        import ai_providers
        kf = ai_providers.pop_key_failure()
        if kf is not None:
            if stopped:
                self._ask_key_failure(kf)
                return
            self.status.setText(f"ℹ️ تعذّر طلب جانبي بمفتاحك الشخصي لـ{kf.label}، وأكمل البرنامج المهمة.")
        failed = ai_providers.pop_personal_failures()
        if failed:                                  # مفتاحك الشخصي فشل (منتهٍ/بلا رصيد): يُبلَّغ الخبير ولا ينتقل لمفتاح القسم بصمت
            QMessageBox.warning(self, "مفتاحك الشخصي لم يعمل", "\n\n".join(failed))
        miss = ai_providers.pop_missing()
        if not miss:
            return
        task, spec, msg, alts = miss
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("مزوّد المهمة غير متاح")
        box.setText(msg)
        picks = {}
        for name in alts[:3]:
            picks[box.addButton(f"استعمل {name} هذه المرة فقط", QMessageBox.ButtonRole.AcceptRole)] = name
        box.addButton("إلغاء", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        name = picks.get(box.clickedButton())
        if name:
            ai_providers.set_override(task, name)
            self.status.setText(f"سيُستعمل {name} في المحاولة التالية لهذه المهمة — أعد الضغط على الزر.")

    def _procedures_ask(self):
        """لا طلب حضور منفصل (المراحل الثلاث): الحضور وتاريخ الحجز من فرز كل محضر."""
        return None

    def _do_procedures(self, action):
        caso = self.data['caso_no']
        if action == 'attend':
            MinutesEditDialog(self.base, self.data, self, ask=self._procedures_ask()).exec()
            return
        if action == 'add':
            path, _ = QFileDialog.getOpenFileName(self, "اختر المحضر", "", case_procedures.FILE_FILTER)
            if path:
                ask = self._procedures_ask()
                self._run_bg(lambda: case_procedures.add_minute(self.base, self.data, path, ask=ask),
                             "جارٍ قراءة المحضر المضاف واستخراج الحضور…")
                self._after = lambda: QTimer.singleShot(0, self.sync_folder)
            return
        self._run_bg(self._procedures_job(), "جارٍ أخذ المحاضر ومقارنتها بجلسات النظام واستخراج الحضور…")

    def _procedures_job(self):
        """دالة بلا وسائط: جلسات النظام وسجل الحركة ثم المحاضر وحضورها من الفرز (بلا أي طلب ذكاء)."""
        caso = self.data['caso_no']
        fetch = self._fetch or (case_procedures.live_fetcher(self.cookies, caso) if self.cookies else None)
        flow = None
        if self.cookies and not self._fetch:
            try:
                import current_expert
                who = current_expert.get_current_user() or ''
            except Exception:
                who = ''
            flow = case_procedures.flow_fetcher(self.cookies, caso, who)
        return lambda: case_procedures.run_procedures(
            self.base, self.data, fetch, fallbacks=(case_procedures.local_fetcher(caso),), flow=flow, ask=None,
            force=True)

    def _do_documents(self, action):
        from qt_documents_dialog import DocumentsDialog
        DocumentsDialog(self.base, self.data, self).exec()
        QTimer.singleShot(0, self.sync_folder)          # ما أُضيف يدخل المزامنة (المحوَّل مسجّل فلا يُعاد)

    def _do_attachments(self, action):
        case_attachments.run_attachments(self.base, self.data, force=True)

    def _do_research(self, action):
        stale_run = case_model.state(self.data, 'research') in case_model.OK_STATES
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)
        ask = self._ask_for('البحث')
        self._run_bg(lambda: case_research.run_research(
            self.base, self.data, ask=ask, stop=lambda: self._stop, include_stale=stale_run),
            "كتابة بنود البحث بالتتابع…")

    def _do_conclusion(self, action):
        ask = self._ask_for('النتيجة')
        self._run_bg(lambda: case_conclusion.run_conclusion(self.base, self.data, ask=ask, force=action == 'rewrite'),
                     "جارٍ كتابة النتيجة…")

    def _do_report(self):
        """يجمع بيانات الجدول الأول (نظام الخبراء إن توفر اتصال) ثم يبني ملف Word في خيط خلفي."""
        if self._busy:
            return
        out = {}
        self._report_running = True

        def work():
            info = report_docx.gather_info(self.data, self.cookies)
            report_docx.remember_header(info)            # المحافظة/القسم من النظام ← الإعدادات إن كانت فارغة
            out['path'], out['warns'] = report_docx.build_report(self.base, self.data, info)
            out['ver'] = (self.data.get('report') or {}).get('version', 1)

        def after():
            msg = f"تم إصدار التقرير (النسخة {out['ver']}):\n{th.ltr(out['path'])}\n\nالنسخ السابقة بقيت كما هي."
            if out['warns']:
                msg += "\n\nملاحظات للمراجعة في Word:\n- " + "\n- ".join(out['warns'])
            QMessageBox.information(self, "التقرير", msg)
            try:
                os.startfile(out['path'])
            except OSError:
                pass
        self._after = after
        self._run_bg(work, "بناء ملف Word…")
