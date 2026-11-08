# اختبارات «مجلد القضية هو الأصل» (case_folder): البنية، الرفع اليدوي، المزامنة، المأمورية من حكم الإحالة، الترحيل.
# python -W ignore -m unittest test_case_folder -v
import json
import os
import tempfile
import unittest

import case_documents as cd
import case_folder as cf
import case_model as cm
import case_subject_mission as sm
import case_workspace as cw

CASE = {'caso_no': 'A9990001', 'autocase_no': '999000111', 'claim_no': '2026/1', 'title': 'اختبار'}

JUDGMENT_MD = ('<!-- صفحة 1 -->\nباسم حضرة صاحب السمو أمير البلاد\nحكمت المحكمة وقبل الفصل في الموضوع بندب إدارة '
               'الخبراء لتندب بدورها أحد خبرائها تكون مهمته: 1- الاطلاع على العقد المؤرخ 1/1/2024 '
               '2- بيان المبالغ المستحقة للمدعية في ذمة المدعى عليه. وصرحت له بالانتقال وحددت جلسة 5/5/2026.')


def fake_convert(path, folder):
    with open(path, 'rb') as f:
        raw = f.read()
    if raw == b'BAD':
        raise ValueError('الملف تالف')
    if path.endswith(('.md', '.txt')):
        return raw.decode('utf-8'), 1
    return f'<!-- صفحة 1 -->\nنص {os.path.basename(path)}', 1


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, 'ws')
        self.base, self.data = cw.ensure_workspace(CASE, self.root)
        self.src_dir = os.path.join(self._tmp.name, 'src')
        os.makedirs(self.src_dir)
        self.calls = []
        self._old = cf.CONVERTER, cf.CLASSIFIER, cd.CLASSIFIER

        def conv(path, folder):
            self.calls.append(os.path.basename(path))
            return fake_convert(path, folder)
        cf.CONVERTER = conv
        cf.CLASSIFIER = lambda p: {'type': 'غير معروف'}

    def tearDown(self):
        cf.CONVERTER, cf.CLASSIFIER, cd.CLASSIFIER = self._old
        self._tmp.cleanup()

    def src(self, name, content=None):
        p = os.path.join(self.src_dir, name)
        with open(p, 'wb') as f:
            f.write(name.encode() if content is None else content)
        return p

    def all_files(self):
        return sorted(os.path.relpath(os.path.join(d, n), self._tmp.name)
                      for d, _, fs in os.walk(self._tmp.name) for n in fs)


class StructureTests(Base):
    def test_new_case_creates_structure(self):
        for d in cf.FOLDERS:
            self.assertTrue(os.path.isdir(os.path.join(self.base, d)), d)
            self.assertTrue(os.path.isdir(os.path.join(self.base, 'markdown', d)), d)
        self.assertTrue(os.path.exists(os.path.join(self.base, '_نظام', 'case.json')))
        self.assertTrue(os.path.isdir(os.path.join(self.base, 'التقرير')))
        self.assertEqual(sorted(n for n in os.listdir(self.base)),
                         sorted(['_نظام', 'markdown', 'التقرير', 'أخرى', 'حوافظ', 'مذكرات', 'مستندات_النظام', 'الملخص.md']))

    def test_default_root_is_documents(self):
        self.assertIn('تقارير الخبراء', cw.default_root())
        self.assertNotIn('Desktop', cw.default_root())


class ManualUploadTests(Base):
    def test_manual_pdf_copied_converted_and_in_sync(self):
        rel = cf.add_original(self.base, self.src('حافظة المدعية.pdf'), cf.OTHER)
        self.assertEqual(rel, 'أخرى/حافظة المدعية.pdf')
        res = cf.sync_case_folder(self.base, self.data)
        self.assertEqual(res['converted'], [rel])
        self.assertIn('حوّلتُ 1', res['message'])
        with open(os.path.join(self.base, 'markdown', 'أخرى', 'حافظة المدعية.md'), encoding='utf-8') as f:
            self.assertIn('نص حافظة المدعية.pdf', f.read())
        self.assertEqual(cf.sync_case_folder(self.base, self.data)['message'], 'جاهز')

    def test_documents_dialog_path_copies_into_type_folder_and_is_not_reconverted(self):
        cd.CLASSIFIER = lambda p: {'type': 'حكم', 'confidence': 1.0, 'reason': 't', 'snippet': ''}
        p = cd.add_portfolio(self.data, 'المحكمة', '')
        items = cd.plan_batch(self.data, p['id'], [self.src('الحكم.pdf')])
        cd.import_batch(self.base, self.data, p['id'], items, convert=lambda path: fake_convert(path, ''))
        doc = self.data['portfolios'][0]['docs'][0]
        self.assertEqual(doc['file'], 'أخرى/الحكم.pdf')                 # الفرز الآلي (case_sort) يسمّيه وينقله
        self.assertEqual(doc['md'], 'markdown/أخرى/الحكم.md')
        res = cf.sync_case_folder(self.base, self.data)
        self.assertEqual(res['converted'], [])                       # مسجّل في manifest
        self.assertEqual(res['message'], 'جاهز')

    def test_unknown_goes_to_other_and_bad_folder_refused(self):
        self.assertEqual(cf.add_original(self.base, self.src('x.pdf')), 'أخرى/x.pdf')
        with self.assertRaises(cf.NeedsFolder):
            cf.add_original(self.base, self.src('y.pdf'), 'مجلد_غريب')

    def test_same_name_never_replaced_and_identical_not_duplicated(self):
        a = cf.add_original(self.base, self.src('عقد.pdf', b'one'), cf.OTHER)
        b = cf.add_original(self.base, self.src('عقد.pdf', b'two'), cf.OTHER)
        c = cf.add_original(self.base, self.src('عقد.pdf', b'two'), cf.OTHER)
        self.assertEqual((a, b, c), ('أخرى/عقد.pdf', 'أخرى/عقد (2).pdf', 'أخرى/عقد (2).pdf'))
        with open(os.path.join(self.base, a), 'rb') as f:
            self.assertEqual(f.read(), b'one')

    def test_long_arabic_name_fits_windows_limit(self):
        name = 'حافظة مستندات مقدمة من وكيل المدعى عليها بجلسة الخبرة ' * 6 + '.pdf'
        rel = cf.add_original(self.base, self.src('long.pdf'), cf.OTHER, name)
        self.assertLess(len(os.path.join(self.base, cf.md_rel(rel))), 260)
        cf.sync_case_folder(self.base, self.data)
        self.assertTrue(os.path.exists(os.path.join(self.base, cf.md_rel(rel))))


class SyncTests(Base):
    def test_count_difference_converts_only_the_extra(self):
        for n in ('1.pdf', '2.pdf'):
            cf.add_original(self.base, self.src(n), cf.MINUTES)
        cf.sync_case_folder(self.base, self.data)
        self.calls.clear()
        cf.add_original(self.base, self.src('3.pdf'), cf.MINUTES)
        res = cf.sync_case_folder(self.base, self.data)
        self.assertEqual(self.calls, ['محضر الخبرة رقم 3.pdf'])
        self.assertEqual(res['converted'], ['مستندات_النظام/محضر الخبرة رقم 3.pdf'])

    def test_changed_file_is_reconverted(self):
        rel = cf.add_original(self.base, self.src('1.pdf'), cf.MINUTES)
        cf.sync_case_folder(self.base, self.data)
        self.calls.clear()
        with open(os.path.join(self.base, rel), 'ab') as f:
            f.write(b' more')
        cf.sync_case_folder(self.base, self.data)
        self.assertEqual(self.calls, ['محضر الخبرة رقم 1.pdf'])

    def test_deleted_original_is_reported_and_derived_kept(self):
        rel = cf.add_original(self.base, self.src('1.pdf'), cf.MINUTES)
        cf.sync_case_folder(self.base, self.data)
        os.remove(os.path.join(self.base, rel))
        res = cf.sync_case_folder(self.base, self.data)
        self.assertEqual(res['missing'], [rel])
        self.assertIn('حُذف', res['message'])
        self.assertTrue(os.path.exists(os.path.join(self.base, cf.md_rel(rel))))

    def test_failed_conversion_reported_with_reason_and_retried(self):
        cf.add_original(self.base, self.src('bad.pdf', b'BAD'), cf.OTHER)
        res = cf.sync_case_folder(self.base, self.data)
        self.assertIn('تعذّر تحويل bad.pdf (الملف تالف)', res['message'])
        self.assertEqual(self.data['folder_sync']['failed'][0][0], 'أخرى/bad.pdf')

    def test_existing_markdown_adopted_after_manifest_wiped(self):
        """26/10: مُسح الكاش (manifest) فأعاد تحويل 14 ملفاً رغم وجود markdown لها ← تُعتمد بلا تحويل."""
        rel = cf.add_original(self.base, self.src('1.pdf'), cf.MINUTES)
        cf.sync_case_folder(self.base, self.data)
        os.remove(cf.manifest_path(self.base))
        self.calls.clear()
        res = cf.sync_case_folder(self.base, self.data)
        self.assertEqual(self.calls, [])
        self.assertEqual(res['converted'], [])
        entry = cf.load_manifest(self.base)['files'][rel]
        self.assertEqual((entry['state'], entry['origin']), ('done', 'existing_md'))

    def test_markdown_from_other_program_adopted(self):
        rel = cf.add_original(self.base, self.src('1.pdf'), cf.MINUTES)
        md = os.path.join(self.base, cf.md_rel(rel))
        os.makedirs(os.path.dirname(md), exist_ok=True)
        with open(md, 'w', encoding='utf-8') as f:
            f.write('# نص محوَّل ببرنامج آخر')
        cf.sync_case_folder(self.base, self.data)
        self.assertEqual(self.calls, [])

    def test_empty_markdown_is_not_adopted(self):
        rel = cf.add_original(self.base, self.src('1.pdf'), cf.MINUTES)
        md = os.path.join(self.base, cf.md_rel(rel))
        os.makedirs(os.path.dirname(md), exist_ok=True)
        open(md, 'w', encoding='utf-8').close()
        cf.sync_case_folder(self.base, self.data)
        self.assertEqual(self.calls, ['محضر الخبرة رقم 1.pdf'])

    def _real_pdf(self, pages):
        import fitz
        doc = fitz.open()
        for _ in range(pages):
            doc.new_page()
        p = os.path.join(self.src_dir, 'حافظة.pdf')
        doc.save(p)
        doc.close()
        return cf.add_original(self.base, p, cf.OTHER)

    def _put_md(self, rel, text):
        md = os.path.join(self.base, cf.md_rel(rel))
        os.makedirs(os.path.dirname(md), exist_ok=True)
        with open(md, 'w', encoding='utf-8') as f:
            f.write(text)

    def test_complete_markdown_matches_pdf_pages(self):
        rel = self._real_pdf(3)
        self._put_md(rel, ''.join(f'<!-- صفحة {i} -->\nنص الصفحة رقم {i} كامل\n' for i in (1, 2, 3)))
        self.assertEqual(cf.md_complete(self.base, rel, cf.md_rel(rel)), (True, ''))
        cf.sync_case_folder(self.base, self.data)
        self.assertEqual(self.calls, [])

    def test_markdown_missing_pages_is_reconverted(self):
        """النسخة توقفت عند الصفحة 2 من 4 ← ناقصة ← تُحوَّل من جديد."""
        rel = self._real_pdf(4)
        self._put_md(rel, '<!-- صفحة 1 -->\nأ\n<!-- صفحة 2 -->\nب\n')
        ok, why = cf.md_complete(self.base, rel, cf.md_rel(rel))
        self.assertFalse(ok)
        self.assertIn('ناقصة 2 من 4', why)
        rejected = []
        files = cf.scan(self.base, {})
        self.assertEqual(cf.adopt_existing(self.base, {}, files, rejected=rejected), [])
        self.assertEqual(rejected[0][0], rel)

    def test_markdown_with_partial_warning_or_empty_pages_rejected(self):
        rel = self._real_pdf(2)
        self._put_md(rel, '<!-- ⚠ الصفحات 1–2: عدد الصفحات في ردّ Gemini (1) لا يطابق الفعلي (2) — النص مدموج -->\n'
                          '<!-- صفحة 1 -->\nنص\n<!-- صفحة 2 -->\nنص\n')
        self.assertFalse(cf.md_complete(self.base, rel, cf.md_rel(rel))[0])
        rel8 = self._real_pdf(8)
        self._put_md(rel8, ''.join(f'<!-- صفحة {i} -->\n' + ('نص\n' if i <= 4 else '') for i in range(1, 9)))
        self.assertIn('بلا نص', cf.md_complete(self.base, rel8, cf.md_rel(rel8))[1])

    def test_documents_step_done_when_all_converted(self):
        """A2263970: كل الملفات محوَّلة و«المستندات» بقيت «بانتظار» ← «لا يمكن بدء البحث — تحتاج اكتمالها»."""
        import case_model as cm
        cf.add_original(self.base, self.src('1.pdf'), cf.MINUTES)
        cf.add_original(self.base, self.src('bad.pdf', b'BAD'), cf.OTHER)
        cf.sync_case_folder(self.base, self.data)
        self.assertEqual(cm.state(self.data, 'documents'), 'needs_input')        # ملف لم يُحوَّل
        os.remove(os.path.join(self.base, cf.OTHER, 'bad.pdf'))
        cf.sync_case_folder(self.base, self.data)
        self.assertEqual(cm.state(self.data, 'documents'), 'done')
        self.assertNotIn('المستندات', '؛ '.join(cm.unmet(self.data, 'research')))

    def test_documents_step_left_to_portfolios_window(self):
        import case_model as cm
        self.data['portfolios'] = [{'docs': []}]
        cf.add_original(self.base, self.src('1.pdf'), cf.MINUTES)
        cf.sync_case_folder(self.base, self.data)
        self.assertEqual(cm.state(self.data, 'documents'), 'pending')

    def test_temp_files_ignored(self):
        for n in ('~$عقد.docx', 'x.pdf.part', 'Thumbs.db', '.hidden.pdf', 'a.tmp'):
            with open(os.path.join(self.base, cf.OTHER, n), 'wb') as f:
                f.write(b'x')
        self.assertEqual(cf.sync_case_folder(self.base, self.data)['total'], 0)

    def test_manifest_is_valid_json_and_no_temp_left(self):
        cf.add_original(self.base, self.src('1.pdf'), cf.MINUTES)
        cf.sync_case_folder(self.base, self.data)
        with open(cf.manifest_path(self.base), encoding='utf-8') as f:
            m = json.load(f)
        self.assertIn('مستندات_النظام/محضر الخبرة رقم 1.pdf', m['files'])
        self.assertFalse([n for n in os.listdir(os.path.join(self.base, '_نظام')) if n.endswith('.tmp')])

    def test_fetch_from_system_places_each_kind_and_skips_seen(self):
        rows = [{'doc_id': 1, 'doc_type': 'حكم تمهيدي', 'doc_date': '01/02/2026'},
                {'doc_id': 2, 'doc_type': 'صحيفة دعوى', 'doc_date': '01/01/2026'},
                {'doc_id': 3, 'doc_type': 'محضر جلسة', 'doc_date': '03/01/2026'},
                {'doc_id': 4, 'doc_type': 'تقرير خبير', 'doc_date': '04/01/2026'},
                {'doc_id': 5, 'doc_type': 'إعلان', 'doc_date': '04/01/2026'}]
        got = []

        def dl(doc_id, path):
            got.append(doc_id)
            with open(path, 'wb') as f:
                f.write(f'%PDF-{doc_id}'.encode())
        new = cf.fetch_from_system(self.base, self.data, None, list_rows=lambda: rows, download=dl)
        self.assertEqual(sorted(cf.kind_of(x) for x in new), sorted([cf.JUDGMENT, cf.PLAINT, cf.MINUTES, cf.PRIOR]))
        self.assertIn('مستندات_النظام/حكم الإحالة.pdf', new)
        self.assertIn('مستندات_النظام/صحيفة الدعوى.pdf', new)
        self.assertIn('مستندات_النظام/تقرير خبرة سابق 04-01-2026.pdf', new)
        self.assertEqual(cf.fetch_from_system(self.base, self.data, None, list_rows=lambda: rows, download=dl), [])
        self.assertEqual(sorted(got), [1, 2, 3, 4])


class MissionTests(Base):
    def _judgment(self, text, name='حكم.txt'):
        cf.add_original(self.base, self.src(name, text.encode('utf-8')), cf.JUDGMENT)
        cf.sync_case_folder(self.base, self.data)

    def test_manual_judgment_mission_shows_in_report_writing(self):
        self._judgment(JUDGMENT_MD)
        state = sm.run_mission(self.base, self.data, get_case=lambda c: {'mission_text': ''})
        self.assertEqual(state, 'needs_input')
        pts = [p['text'] for p in self.data['mission']['points']]
        self.assertEqual(len(pts), 2)
        self.assertIn('الاطلاع على العقد', pts[0])
        self.assertNotIn('وصرحت', ' '.join(pts))
        self.assertEqual(self.data['mission']['source']['from'], 'folder')

    def test_folder_wins_over_old_case_db_and_db_is_fallback(self):
        sm.run_mission(self.base, self.data, get_case=lambda c: {'mission_text': '1- قديم'})
        self.assertEqual(self.data['mission']['points'][0]['text'], 'قديم')
        self._judgment(JUDGMENT_MD)
        self.assertEqual(sm.refresh_mission_if_changed(self.base, self.data, get_case=lambda c: {}), 'rerun')
        self.assertIn('الاطلاع على العقد', self.data['mission']['points'][0]['text'])

    def test_changed_judgment_after_approval_is_flagged_not_overwritten(self):
        self._judgment(JUDGMENT_MD)
        sm.run_mission(self.base, self.data, get_case=lambda c: {})
        sm.confirm_mission(self.base, self.data)
        before = list(self.data['mission']['points'])
        self._judgment(JUDGMENT_MD.replace('العقد', 'الاتفاقية'), 'حكم جديد.txt')
        self.assertEqual(sm.refresh_mission_if_changed(self.base, self.data), 'flagged')
        self.assertEqual(self.data['mission']['points'], before)
        self.assertTrue(self.data['mission']['source_changed'])

    def test_adopt_manual_judgment_copies_into_folder(self):
        root = self.root
        old = cw.reports_root
        cw.reports_root = lambda: root
        try:
            rel = cf.adopt_manual_judgment(CASE, self.src('upload.pdf', b'%PDF-' + b'x' * 300))
        finally:
            cw.reports_root = old
        self.assertEqual(rel, 'مستندات_النظام/حكم الإحالة.pdf')
        self.assertEqual(cw.read_case_json(self.base)['sources']['judgment']['origin'], 'manual')


class MigrationTests(Base):
    def test_migration_copies_and_deletes_nothing(self):
        b = self.base
        for d in ('P1', 'مصادر', 'محاضر'):
            os.makedirs(os.path.join(b, '_نظام', '01_اصول', d))
        os.makedirs(os.path.join(b, '_نظام', '02_markdown'))
        for rel, raw in (('_نظام/01_اصول/P1/001.pdf', b'doc'), ('_نظام/01_اصول/مصادر/حكم_الإحالة.pdf', b'judg'),
                         ('_نظام/01_اصول/محاضر/2.docx', b'min'), ('_نظام/02_markdown/P1-001.md', 'نص'.encode())):
            with open(os.path.join(b, rel), 'wb') as f:
                f.write(raw)
        self.data['sources'] = {'judgment': {'file': '_نظام/01_اصول/مصادر/حكم_الإحالة.pdf'}}
        p = cd.add_portfolio(self.data, 'المدعية', '')
        p['docs'].append({'uid': 'd1', 'no': 1, 'seq': 1, 'file': '_نظام/01_اصول/P1/001.pdf', 'md': '_نظام/02_markdown/P1-001.md',
                          'orig_name': 'عقد الإيجار.pdf', 'doc_type': 'حافظة مستندات',
                          'convert': {'state': 'done', 'message': ''}})
        before = self.all_files()
        moves = cf.migrate_legacy(b, self.data)
        after = self.all_files()
        self.assertFalse(set(before) - set(after))                    # لا شيء حُذف
        self.assertEqual(len(moves), 3)
        self.assertEqual(self.data['portfolios'][0]['docs'][0]['file'], 'أخرى/عقد الإيجار.pdf')
        self.assertEqual(self.data['sources']['judgment']['file'], 'مستندات_النظام/حكم الإحالة.pdf')
        self.assertTrue(os.path.exists(os.path.join(b, 'مستندات_النظام', 'محضر الخبرة رقم 2.docx')))
        with open(os.path.join(b, cf.LOG_REL), encoding='utf-8') as f:
            self.assertIn('_نظام/01_اصول/P1/001.pdf', f.read())
        self.calls.clear()
        res = cf.sync_case_folder(b, self.data)                       # المحوَّل سابقاً لا يُعاد تحويله
        self.assertNotIn('عقد الإيجار.pdf', self.calls)
        self.assertNotIn('أخرى/عقد الإيجار.pdf', res['converted'])

    def test_root_migration_copies_whole_case_keeps_old(self):
        old_root = os.path.join(self._tmp.name, 'desk')
        os.makedirs(os.path.join(old_root, 'B1'))
        with open(os.path.join(old_root, 'B1', 'case.json'), 'w', encoding='utf-8') as f:
            f.write('{}')
        new_root = os.path.join(self._tmp.name, 'docs')
        self.assertTrue(cf.migrate_root('B1', new_root, old_root))
        self.assertTrue(os.path.exists(os.path.join(old_root, 'B1', 'case.json')))
        self.assertTrue(os.path.exists(os.path.join(new_root, 'B1', 'case.json')))
        self.assertFalse(cf.migrate_root('B1', new_root, old_root))       # لا يكتب فوق الموجود


if __name__ == '__main__':
    unittest.main()
