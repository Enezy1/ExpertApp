# اختبارات مكتبتي الصياغة: python -W ignore -m unittest test_drafting_library -v
import os
import tempfile
import unittest

import case_procedures as cp
import case_subject_ai as sa
import drafting_library as dl

REPORTS = r'C:\Users\Dell\Documents\MEGA\محمد العنزي\التقارير'      # قراءة فقط؛ لا يكتب الاختبار فيه
HERE = os.path.dirname(os.path.abspath(__file__))


def snapshot(root):
    out = {}
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


class LibraryFiles(unittest.TestCase):
    def test_both_files_load_with_rules_and_models(self):
        rules, models = dl.parse(dl._read(dl.program_path(dl.SUBJECT_FILE)))      # ملف البرنامج وحده
        self.assertIn('الخبير مذكّر', rules)
        self.assertIn('الموضوع من الصحيفة فقط', rules)
        self.assertEqual({m['type'] for m in models}, set(sa.CASE_TYPES))
        self.assertGreaterEqual(len(models), 9)
        prules, pmodels = dl.parse(dl._read(dl.program_path(dl.PROCEDURES_FILE)))
        self.assertIn('الصيغة المعتمدة', prules)
        self.assertTrue({'الأساسي', 'الأحدث', 'الانتقال', 'الشهود', 'إعادة_التوزيع'} <= {m['type'] for m in pmodels})

    def test_no_placeholder_todo_in_subject_models(self):
        _r, models = dl.parse(dl._read(dl.program_path(dl.SUBJECT_FILE)))
        for m in models:
            self.assertNotIn('[يُكتب]', m['text'], m['title'])

    def test_each_case_type_picks_its_own_model(self):
        _rules, models = dl.parse(dl._read(dl.program_path(dl.SUBJECT_FILE)))
        for kind in sa.CASE_TYPES:
            self.assertEqual(sa.pick_models(models, '', kind=kind)[0]['type'], kind)

    def test_type_detection(self):
        d = sa.detect_type
        self.assertEqual(d('', 'اتصالات'), ('اتصالات', True))
        self.assertEqual(d('جاءت المدعية بصحيفة مفادها أنها مقاول من الباطن بموجب عقد مؤرخ 1/1/2020')[0], 'مقاول_باطن')
        self.assertEqual(d('بموجب عقد مؤرخ 1/1/2020 وكذلك ملحق للعقد بتاريخ 2/2/2020 وعقد آخر بتاريخ 3/3/2020')[0],
                         'عقد_ملحق')
        self.assertEqual(d('أفاد المدعي أنه قام بسداد كامل قيمة العقد بموجب عقد مؤرخ 5/5/2019')[0], 'سداد_واخلال')
        self.assertEqual(d('قام الشاكي بالشكوى لدى النيابة')[0], 'شكوى_جزائية')
        self.assertEqual(d('جاء المستأنف بصحيفة استئناف ضد الحكم')[0], 'استئناف')
        self.assertEqual(d('فوجئت المدعية بمحضر مخالفة وغرامة وخاطبت البلدية')[0], 'بلا_عقد')
        self.assertEqual(d('بموجب عقد مؤرخ 1/1/2020 تعهدت المدعية بتنفيذ أعمال'), ('عقد_مقاولة', True))
        self.assertFalse(d('')[1])                       # لا نص ← غير واضح (يسأل الخبير)

    def test_rules_reach_prompt_and_no_todo_in_text(self):
        prompts = []

        def ask(prompt):
            prompts.append(prompt)
            return '{"claim":"الحكم بإلزام المدعى عليها بسداد 100 د.ك"}'
        plaint = 'جاءت المدعية بصحيفة مفادها أنها مقاول من الباطن وتطلب الحكم بإلزام المدعى عليها بسداد 100 د.ك'
        b = sa.build_subject(plaint, ['شركة'], ask)
        self.assertIn('قواعد الصياغة', prompts[0])
        self.assertIn('الخبير مذكّر', prompts[0])
        self.assertEqual(b['type'], 'مقاول_باطن')
        self.assertNotIn('[', b['text'])

    def test_add_model_goes_under_type_and_is_picked(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = sa.STYLE_PATH
            sa.STYLE_PATH = os.path.join(tmp, 'm.md')
            try:
                sa.add_model('نموذج إيجار', ['إيجار'], 'جاءت المدعية بصحيفة مفادها أنها أجّرت العين.', kind='عقد_مقاولة')
                models = sa.load_models()
                self.assertEqual(models[-1]['type'], 'عقد_مقاولة')
                self.assertEqual(sa.pick_models(models, '', kind='عقد_مقاولة')[0]['title'], 'نموذج إيجار')
            finally:
                sa.STYLE_PATH = old


class ProceduresLibrary(unittest.TestCase):
    def test_templates_loaded_from_file(self):
        tpl, choice = cp.load_templates()
        self.assertEqual(choice, 'الأساسي')
        self.assertEqual(tpl['الأساسي'], cp.PROCEDURES_TEMPLATE)
        self.assertIn('وتبين محاضر أعمالنا', tpl['الأحدث'])

    def test_edit_in_file_changes_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'p.md')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('# القواعد\n\n- الصيغة المعتمدة: الأحدث\n\n# النماذج\n\n## x\nالنوع: الأحدث\n'
                        'أ {received} ب {ruling} ج {attendance}{extras} د {booked}\n')
            old = cp.STYLE_PATH
            cp.STYLE_PATH = path
            try:
                tpl, choice = cp.load_templates()
                self.assertEqual(choice, 'الأحدث')
                self.assertTrue(tpl['الأحدث'].startswith('أ {received}'))
            finally:
                cp.STYLE_PATH = old

    def test_extras_only_when_found_and_appeal_wording(self):
        data = {'subject': 'جاء المستأنف بصحيفة', 'sessions': {}, 'procedures': {
            'received': {'date': '2026-01-05'}, 'judgment': {'date': '2025-12-24'}, 'booked': {'date': '2026-03-01'},
            'extras': {'transfer': [{'date': '2026-02-10', 'present': None}], 'witness': [], 'redistribution': False},
            'attendance': {'result': []}}}
        t = cp.compose_text(data)
        self.assertIn('حكم الاستئناف الصادر بجلسة 24/12/2025', t)
        self.assertIn('وبتاريخ 10/02/2026 تم الانتقال والمعاينة', t)
        self.assertIn('\n\nالانتقال:\nبجلسة الخبرة المؤرخة 10/02/2026', t)
        self.assertNotIn('تخلف', t)                    # لا تخلف بلا اكتمال المحاضر
        self.assertNotIn('تم مناقشة', t)
        data['procedures']['extras'] = {'transfer': [], 'witness': [], 'redistribution': False}
        self.assertNotIn('الانتقال', cp.compose_text(data))
        data['procedures']['extras']['redistribution'] = True
        self.assertTrue(cp.compose_text(data).startswith(
            'استلمنا ملف الدعوى بحالته بعد إعادة توزيعه بتاريخ 05/01/2026'))

    def test_detect_extras_from_minutes(self):
        minutes = [{'path': 'a', 'name': 'a'}, {'path': 'b', 'name': 'b'}]
        texts = {'a': ['محضر جلسة 10/2/2026', 'تم الانتقال إلى الموقع'], 'b': ['محضر جلسة 11/2/2026', 'جلسة لسماع شهود']}
        ex = cp.detect_extras(minutes, texts, {})
        self.assertEqual([x['date'] for x in ex['transfer']], ['2026-02-10'])
        self.assertEqual([x['date'] for x in ex['witness']], ['2026-02-11'])
        self.assertFalse(ex['redistribution'])


class ReportsFolderUntouched(unittest.TestCase):
    @unittest.skipUnless(os.path.isdir(REPORTS), 'مجلد التقارير غير موجود')
    def test_reports_folder_not_modified_by_loading_or_composing(self):
        before = snapshot(REPORTS)
        dl.load(dl.SUBJECT_FILE)
        dl.load(dl.PROCEDURES_FILE)
        sa.load_library()
        cp.load_templates()
        self.assertEqual(before, snapshot(REPORTS))

    def test_library_code_never_references_reports_folder(self):
        for name in ('drafting_library.py', 'case_subject_ai.py'):
            with open(os.path.join(HERE, name), encoding='utf-8') as f:
                self.assertNotIn('MEGA', f.read())


if __name__ == '__main__':
    unittest.main()
