# اختبارات دفعة 2026-10-18: تحويل كل أصل إلى markdown + فحص العدد + الفهرس، رقم المحضر من نصه وترتيبه،
# استخراج الجلسات من المحاضر بدليل حرفي، تحديد حكم الإحالة (الأحدث/استئناف مقابل كلية/سؤال الذكاء ثم التحقق)،
# المأمورية حرفياً، و«إعادة الكتابة» مع حماية النص المعدَّل يدوياً.
# python -W ignore -m unittest test_folder_minutes_referral -v
import json
import os
import shutil
import tempfile
import unittest
import zipfile

import case_convert
import case_folder as cf
import case_index
import case_minutes_ai as mai
import case_procedures as cp
import case_rewrite
import case_subject_mission as sm
import case_workspace as cw
import referral_pick

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(t):
    return f'<w:p><w:r><w:t>{t}</w:t></w:r></w:p>'


def make_docx(path, paras, header=(), table=None):
    body = ''.join(_p(t) for t in paras)
    if table:
        body += '<w:tbl>' + ''.join('<w:tr>' + ''.join(f'<w:tc>{_p(c)}</w:tc>' for c in row) + '</w:tr>'
                                    for row in table) + '</w:tbl>'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', f'<w:document {W}><w:body>{body}</w:body></w:document>')
        if header:
            z.writestr('word/header2.xml', f'<w:hdr {W}>' + ''.join(_p(t) for t in header) + '</w:hdr>')


def make_pdf(path, text=None):
    import fitz
    d = fitz.open()
    pg = d.new_page()
    if text:
        pg.insert_text((50, 80), text, fontsize=11)
    else:                                                     # «ممسوح»: صورة بلا طبقة نص
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60), False)
        pix.clear_with(200)
        pg.insert_image(fitz.Rect(50, 50, 300, 300), pixmap=pix)
    d.save(path)
    d.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, 'A2260001')
        self.base, self.data = cw.ensure_workspace({'caso_no': 'A2260001', 'autocase_no': '1'}, root=self.tmp)
        cf.ensure_structure(self.base)
        self._fb = case_convert.FALLBACK
        case_convert.FALLBACK = lambda path, folder: ('<!-- صفحة 1 -->\nنص من المحرك', 1, 'gemini')

    def tearDown(self):
        case_convert.FALLBACK = self._fb
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def place(folder, name):
        """البنية المختصرة: أنواع النظام في مستندات_النظام باسم يبدأ بنوعها (kind_of)."""
        prefix = {cf.JUDGMENT: 'حكم', cf.PLAINT: 'صحيفة', cf.MINUTES: 'محضر'}.get(folder)
        if prefix:
            return cf.SYSDOCS, name if name.startswith(prefix) else f'{prefix} {name}'
        return folder, name

    def rel(self, folder, name):
        return '/'.join(self.place(folder, name))

    def put(self, folder, name):
        folder, name = self.place(folder, name)
        os.makedirs(os.path.join(self.base, folder), exist_ok=True)
        return os.path.join(self.base, folder, name)

    def md(self, rel):
        with open(os.path.join(self.base, cf.md_rel(rel)), encoding='utf-8') as f:
            return f.read()


# ---------- 1) التحويل ----------

class ConvertTests(Base):
    def test_docx_direct_with_table_and_header(self):
        make_docx(self.put(cf.OTHER, 'عقد.docx'), ['عقد مقاولة', 'الطرف الأول: شركة ألف'],
                  header=['رأس الصفحة'], table=[['البند', 'القيمة'], ['أعمال', '1,500']])
        res = cf.sync_case_folder(self.base, self.data)
        self.assertEqual(res['converted'], [self.rel(cf.OTHER, 'عقد.docx')])
        t = self.md(self.rel(cf.OTHER, 'عقد.docx'))
        self.assertIn('| البند | القيمة |', t)
        self.assertIn('رأس الصفحة', t)
        self.assertEqual(cf.load_manifest(self.base)['files'][self.rel(cf.OTHER, 'عقد.docx')]['engine'], 'direct')

    def test_text_pdf_uses_text_layer_without_ocr(self):
        make_pdf(self.put(cf.JUDGMENT, 'j.pdf'), 'The court decided to refer the case to the experts department today.')
        called = []
        case_convert.FALLBACK = lambda *a: called.append(a) or ('x', 1, 'gemini')
        cf.sync_case_folder(self.base, self.data)
        self.assertEqual(called, [])
        self.assertEqual(cf.load_manifest(self.base)['files'][self.rel(cf.JUDGMENT, 'j.pdf')]['engine'], 'text_layer')

    def test_scanned_pdf_goes_to_existing_engine_and_discloses_it(self):
        make_pdf(self.put(cf.PLAINT, 's.pdf'))
        cf.sync_case_folder(self.base, self.data)
        e = cf.load_manifest(self.base)['files'][self.rel(cf.PLAINT, 's.pdf')]
        self.assertEqual(e['engine'], 'gemini')
        self.assertIn('قُرئ بمحرك: gemini', self.md(self.rel(cf.PLAINT, 's.pdf')))

    def test_reversed_arabic_layer_is_not_sound(self):
        good = 'قررت المحكمة في الدعوى من حيث الشكل على أن هذا هو الحكم الذي صدر في الجلسة التي حضرها الخصوم ' * 3
        bad = ' '.join(w[::-1] for w in good.split())
        self.assertTrue(case_convert.arabic_order_ok(good))
        self.assertFalse(case_convert.arabic_order_ok(bad))

    def test_rtf_csv_xlsx_txt(self):
        bs = chr(92)
        rtf = ('{' + bs + 'rtf1' + bs + 'ansi' + bs + 'ansicpg1256 {' + bs + 'fonttbl{' + bs + 'f0 Arial;}}' + bs + 'f0 '
               + bs + 'u1593?' + bs + 'u1602?' + bs + 'u1583? ' + bs + 'par Line two}')
        with open(self.put(cf.OTHER, 'a.rtf'), 'w', encoding='latin-1') as f:
            f.write(rtf)
        with open(self.put(cf.OTHER, 'b.csv'), 'w', encoding='utf-8') as f:
            f.write('البند,المبلغ\nتوريد,100\n')
        import openpyxl
        wb = openpyxl.Workbook()
        wb.active.append(['x', 'y'])
        wb.active.append([1, 2])
        wb.save(self.put(cf.OTHER, 'c.xlsx'))
        with open(self.put(cf.OTHER, 'd.txt'), 'w', encoding='utf-8') as f:
            f.write('نص عادي')
        res = cf.sync_case_folder(self.base, self.data)
        self.assertEqual(len(res['converted']), 4, res['failed'])
        self.assertIn('عقد', self.md(self.rel(cf.OTHER, 'a.rtf')))
        self.assertIn('| توريد | 100 |', self.md(self.rel(cf.OTHER, 'b.csv')))
        self.assertIn('| 1 | 2 |', self.md(self.rel(cf.OTHER, 'c.xlsx')))
        self.assertTrue(res['count']['ok'])

    def test_doc_without_word_reports_reason(self):
        with open(self.put(cf.OTHER, 'old.doc'), 'wb') as f:
            f.write(b'\xd0\xcf\x11\xe0')
        old = case_convert.DOC_CONVERTERS
        case_convert.DOC_CONVERTERS = ()
        try:
            res = cf.sync_case_folder(self.base, self.data)
        finally:
            case_convert.DOC_CONVERTERS = old
        self.assertIn('Microsoft Word', res['failed'][0][1])

    def test_count_mismatch_red_line_names_and_reasons(self):
        make_docx(self.put(cf.OTHER, 'ok.docx'), ['نص'])
        with open(self.put(cf.OTHER, 'x.xyz'), 'w') as f:
            f.write('?')
        make_docx(self.put(cf.OTHER, 'empty.docx'), [])
        res = cf.sync_case_folder(self.base, self.data)
        c = res['count']
        self.assertEqual((c['originals'], c['markdown'], c['ok']), (3, 1, False))
        self.assertIn('x.xyz (صيغة غير مدعومة (.xyz))', c['line'])
        self.assertIn('empty.docx (لم يُستخرج نص من ملف Word)', c['line'])
        self.assertEqual(self.data['folder_sync']['count']['line'], c['line'])

    def test_index_lists_docs_and_contract_kinds(self):
        make_docx(self.put(cf.OTHER, 'حافظة.docx'),
                  ['أمر تغيير رقم 3', 'بتاريخ 12/05/2024', 'الطرف الأول: وزارة الأشغال', 'الطرف الثاني: شركة باء',
                   'بقيمة 25,000.500 د.ك'])
        cf.sync_case_folder(self.base, self.data)
        path = os.path.join(self.base, case_index.INDEX_NAME)
        with open(path, encoding='utf-8') as f:
            t = f.read()
        self.assertIn('| 1 | أمر تغيير | 12/05/2024 | وزارة الأشغال، شركة باء | 25,000.500 د.ك |', t)
        self.assertEqual(self.data['doc_index'][0]['type'], 'أمر تغيير')


# ---------- 5) رقم المحضر ----------

class MinuteNumberTests(Base):
    def test_number_comes_from_header_not_file_name(self):
        """الحالة: ملف 1.docx ورأسه «رقم المحضر 2» ← المحضر 2 مع تنبيه."""
        p = self.put(cf.MINUTES, '1.docx')
        make_docx(p, ['فتح المحضر بتاريخه', 'وقد حضر في الموعد المحدد كل من:'],
                  header=['محضر أعمال الخبرة', 'رقم المحضر', '2', 'التاريـخ', '06/07/2026'])
        mins = cp.find_minutes('A2260001', root=os.path.join(self.tmp, 'none'), base=self.base)
        self.assertEqual((mins[0]['no'], mins[0]['no_source'], mins[0]['date']), (2, 'text', '2026-07-06'))
        self.assertTrue(any('اعتُمد رقم النص' in w for w in cp.order_warnings(mins)))

    def test_order_by_date_then_number_and_warn_on_conflict(self):
        make_docx(self.put(cf.MINUTES, 'a.docx'), ['x'], header=['رقم المحضر', '3', 'التاريخ', '01/03/2026'])
        make_docx(self.put(cf.MINUTES, 'b.docx'), ['x'], header=['رقم المحضر', '2', 'التاريخ', '10/03/2026'])
        make_docx(self.put(cf.MINUTES, 'c.docx'), ['x'], header=['رقم المحضر', '1', 'التاريخ', '15/02/2026'])
        mins = cp.find_minutes('A2260001', root=os.path.join(self.tmp, 'none'), base=self.base)
        self.assertEqual([m['no'] for m in mins], [1, 3, 2])          # بالتاريخ
        self.assertTrue(any('لا يتبع الترتيب' in w for w in cp.order_warnings(mins)))

    def test_number_from_text_variants(self):
        self.assertEqual(cp.number_from_text('محضر أعمال رقم (٤)'), 4)
        self.assertEqual(cp.number_from_text('الجلسة رقم 7'), 7)
        self.assertIsNone(cp.number_from_text('صفحة رقم 1 من 1'))


# ---------- 4) الجلسات من المحاضر بالذكاء ----------

class MinutesAITests(unittest.TestCase):
    def test_only_literal_evidence_is_accepted(self):
        items = [{'ref': 'M1', 'name': '2.docx', 'path': 'p',
                  'text': 'بتاريخ 06/07/2026 حضر ممثل الشركة المدعية السيد فلان ولم يحضر المدعى عليه رغم إعلانه'}]
        raw = json.dumps({'minutes': [{'ref': 'M1', 'number': 2, 'date': '06/07/2026',
                                       'present': [{'party': 'الشركة', 'evidence': 'حضر ممثل الشركة المدعية'}],
                                       'absent': [{'party': 'خالد', 'evidence': 'تخلف خالد عن الحضور'}],
                                       'visit': {'yes': True, 'evidence': 'انتقلنا إلى الموقع'}}]}, ensure_ascii=False)
        recs, bad = mai.verify(raw, items, ['الشركة', 'خالد'])
        self.assertEqual([p['index'] for p in recs[0]['present']], [0])
        self.assertEqual(recs[0]['absent'], [])                     # الدليل غير وارد حرفياً
        self.assertIsNone(recs[0]['visit'])
        self.assertEqual(recs[0]['date'], '2026-07-06')
        self.assertEqual(len(bad), 2)

    def test_merge_does_not_override_certain(self):
        att = {'parties': ['أ', 'ب'], 'result': [{'present': True, 'certain': True}, {'present': False, 'certain': False}]}
        ai = {'records': [{'name': 'm', 'present': [{'index': 1, 'evidence': 'e'}], 'absent': [{'index': 0, 'evidence': 'e'}]}]}
        mai.merge_attendance(att, ai)
        self.assertEqual([(r['present'], r['certain']) for r in att['result']], [(True, True), (True, True)])
        self.assertTrue(att['extracted'])


# ---------- 6) حكم الإحالة ----------

REFER = 'وقبل الفصل في الموضوع بندب إدارة الخبراء لتندب أحد خبرائها تكون مهمته الاطلاع على العقد وبيان المستحق. وحددت جلسة'


class ReferralTests(Base):
    def write(self, folder, name, text):
        p = self.put(folder, name)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(text)
        return p

    def test_latest_wins_appeal_over_older_first_instance(self):
        self.write(cf.OTHER, 'حكم كلي 2025-01-10.txt', 'المحكمة الكلية\n' + REFER)
        self.write(cf.OTHER, 'حكم استئناف 2026-02-01.txt', 'محكمة الاستئناف\n' + REFER.replace('العقد', 'الملحق'))
        self.write(cf.OTHER, 'مذكرة 2026-05-01.txt', 'مذكرة دفاع بلا إحالة')
        cf.sync_case_folder(self.base, self.data)
        rec = referral_pick.pick(self.base, self.data)
        self.assertEqual((os.path.basename(rec['file']), rec['method']), ('حكم استئناف 2026-02-01.txt', 'auto'))
        txt, red = referral_pick.line(self.data)
        self.assertTrue(not red and 'التأكيد للخبير' in txt)      # تنبيه لا لون أحمر
        import case_memory
        case_memory.regenerate(self.base, self.data)
        with open(case_memory.memory_path(self.base), encoding='utf-8') as f:
            self.assertIn('حُدِّد تلقائياً، تأكد منه', f.read())
        sm.run_mission(self.base, self.data, get_case=lambda c: {}, force=True)
        self.assertIn('الملحق', self.data['mission']['raw'])

    def test_same_date_prefers_appeal(self):
        self.write(cf.OTHER, 'أ 2026-02-01.txt', 'المحكمة الكلية\n' + REFER)
        self.write(cf.OTHER, 'ب 2026-02-01.txt', 'محكمة الاستئناف\n' + REFER)
        cf.sync_case_folder(self.base, self.data)
        self.assertEqual(os.path.basename(referral_pick.pick(self.base, self.data)['file']), 'ب 2026-02-01.txt')

    def test_system_judgment_kept_when_latest(self):
        self.write(cf.JUDGMENT, 'حكم 2026-03-01.txt', REFER)
        self.write(cf.OTHER, 'قديم 2025-03-01.txt', REFER)
        cf.sync_case_folder(self.base, self.data)
        rec = referral_pick.pick(self.base, self.data)
        self.assertEqual((rec['method'], rec['note']), ('system', ''))

    def test_ask_ai_then_verify_mission(self):
        self.write(cf.OTHER, 'م1.txt', 'مستند أول بلا كلمات إحالة')
        self.write(cf.OTHER, 'م2.txt', 'نص حكم: تكون مهمته الاطلاع على الأوراق. وحددت جلسة')
        cf.sync_case_folder(self.base, self.data)
        names = [os.path.basename(d['file']) for d in referral_pick.documents(self.base)]
        rec = referral_pick.pick(self.base, self.data, ask=lambda p: '{"index": %d}' % (names.index('م2.txt') + 1))
        self.assertEqual((os.path.basename(rec['file']), rec['method']), ('م2.txt', 'ai'))

    def test_ai_choice_without_mission_is_rejected(self):
        self.write(cf.OTHER, 'م1.txt', 'مستند أول بلا كلمات إحالة')
        cf.sync_case_folder(self.base, self.data)
        self.assertIsNone(referral_pick.pick(self.base, self.data, ask=lambda p: '{"index": 1}'))
        self.assertIn('لا يحتوي مأمورية', self.data['judgment_pick_error'])

    def test_mission_literal_check(self):
        pts = [{'n': 1, 'text': 'الاطلاع على العقد'}, {'n': 2, 'text': 'تصفية الحساب بين الطرفين'}]
        self.assertEqual(sm.literal_check(pts, REFER), [2])


# ---------- 3) إعادة الكتابة وحماية النص اليدوي ----------

class RewriteTests(Base):
    def test_manual_procedures_text_never_auto_replaced(self):
        proc = self.data.setdefault('procedures', {})
        proc.update(auto_text='قديم', text='نصي أنا', edited=True)
        self.data['sessions'] = {}
        cp.re_evaluate(self.base, self.data)
        self.assertEqual(self.data['procedures']['text'], 'نصي أنا')
        self.assertIn('نصك لم يُمسّ', self.data['procedures']['changed_notice'])
        self.assertTrue(case_rewrite.is_manual(self.data, 'procedures'))

    def test_subject_manual_flag_and_rephrase_guard(self):
        self.data['steps']['subject'] = {'state': 'needs_input'}
        sm.set_subject(self.base, self.data, 'جاءت المدعية بعقد مؤرخ 01/02/2020 بمبلغ 500 د.ك.')
        self.assertTrue(case_rewrite.is_manual(self.data, 'subject'))
        self.data['subject_facts'] = {'amount': '500 د.ك'}
        with self.assertRaises(case_rewrite.RewriteError):
            case_rewrite.rewrite_subject(self.base, self.data, ask=lambda p: 'نص بمبلغ 900 د.ك')
        self.assertIn('500', self.data['subject'])                  # لم يُستبدل
        case_rewrite.rewrite_subject(self.base, self.data,
                                     ask=lambda p: 'أفادت المدعية بموجب عقد مؤرخ 01/02/2020 بمبلغ 500 د.ك.')
        self.assertTrue(self.data['subject'].startswith('أفادت'))
        self.assertFalse(case_rewrite.is_manual(self.data, 'subject'))

    def test_rewrite_sends_text_even_without_new_documents(self):
        seen = []
        self.data['subject'] = 'النص الحالي 2020'
        self.data['subject_facts'] = {'contract_date': '2020'}
        self.data['steps']['subject'] = {'state': 'done'}
        case_rewrite.rewrite_subject(self.base, self.data, ask=lambda p: seen.append(p) or 'صياغة جديدة 2020')
        self.assertIn('النص الحالي 2020', seen[0])
        self.assertIn('contract_date', seen[0])

    def test_edited_mission_not_replaced_by_new_judgment(self):
        self.data['mission'] = {'points': [{'id': 'q1', 'n': 1, 'text': 'نقطتي'}], 'edited': True}
        with open(self.put(cf.JUDGMENT, 'j.txt'), 'w', encoding='utf-8') as f:
            f.write(REFER)
        cf.sync_case_folder(self.base, self.data)
        self.assertEqual(sm.refresh_mission_if_changed(self.base, self.data, get_case=lambda c: {}), 'flagged')
        self.assertEqual(self.data['mission']['points'][0]['text'], 'نقطتي')


# ---------- 2) أزرار صفحة القضية ----------

class CasePageButtonsTests(Base):
    def setUp(self):
        super().setUp()
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        import qt_case_page as qp
        self.qp = qp
        self.saved = (qp.CasePageDialog.AUTO_SYNC, qp.CasePageDialog.AUTO_ASK_TYPE, qp.CasePageDialog.AUTO_PROCEDURES)
        qp.CasePageDialog.AUTO_SYNC = qp.CasePageDialog.AUTO_ASK_TYPE = qp.CasePageDialog.AUTO_PROCEDURES = False
        cw.write_case_json(self.base, self.data)

    def tearDown(self):
        (self.qp.CasePageDialog.AUTO_SYNC, self.qp.CasePageDialog.AUTO_ASK_TYPE,
         self.qp.CasePageDialog.AUTO_PROCEDURES) = self.saved
        super().tearDown()

    def labels(self, dlg):
        from PyQt6.QtWidgets import QPushButton
        return {b.text() for b in dlg.card.findChildren(QPushButton) if b.isVisibleTo(dlg.card) or True}

    def test_removed_buttons_and_mission_reread(self):
        dlg = self.qp.CasePageDialog(self.base, cw.read_case_json(self.base))
        dlg.open_step('subject')
        got = self.labels(dlg)
        for gone in ('نوع القضية…', 'احفظ هذا النص كنموذج', 'تحديث الصحيفة من النظام'):
            self.assertNotIn(gone, got)
        self.assertIn('أعد الكتابة', got)                     # المرحلة الثانية: «أعد الكتابة» وبجانبه طريقة الكتابة
        self.assertIn('جيميناي (API)', {__import__('qt_bidi').strip_isolates(t) for t in got})
        self.assertTrue(hasattr(dlg, '_save_subject_as_model') and hasattr(dlg, '_choose_subject_type'))
        dlg.open_step('mission')
        self.assertIn('أعد القراءة من الحكم', self.labels(dlg))
        self.assertFalse(dlg.editor.isReadOnly())
        dlg.open_step('procedures')
        self.assertIn('إعادة الكتابة', self.labels(dlg))
        dlg.deleteLater()

    def test_auto_pick_red_line_in_header(self):
        self.data['judgment_pick'] = {'file': 'أخرى/ح.txt', 'note': referral_pick.AUTO_NOTE, 'reason': 'x',
                                      'date': '2026-02-01'}
        cw.write_case_json(self.base, self.data)
        dlg = self.qp.CasePageDialog(self.base, cw.read_case_json(self.base))
        self.assertFalse(dlg.pick_line.isVisibleTo(dlg))         # لا سطر أحمر في الرأس؛ التنبيه في بطاقة المأمورية
        dlg.open_step('mission')
        texts = ' '.join(l.text() for l in dlg.card.findChildren(self.qp.QLabel))
        self.assertIn('التأكيد للخبير', texts)
        dlg.deleteLater()


if __name__ == '__main__':
    unittest.main()
