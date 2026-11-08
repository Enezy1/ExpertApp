# اختبارات المرحلة 2ج (قالب Word): python -m unittest test_report_docx -v
import json
import os
import tempfile
import unittest

from docx import Document

import case_attachments as ca
import case_conclusion as cc
import case_model as cm
import case_research as cr
import case_workspace as cw
import report_docx as rd

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)

ITEM_MD = ('### فحص العقد\n\nالعقد مؤرخ في 2020 [P1-1].\n\n- التزام أول\n- التزام ثانٍ\n\n'
           '| البند | المبلغ |\n|---|---|\n| أ | 100 |\n| ب | 200 |\n')


def research_ask(prompt):
    return f'{ITEM_MD}\n{cr.SUMMARY_MARK}\nخلاصة'


def concl_ask(prompt):
    n = prompt.split('## النقطة (رقم ', 1)[1].split(')', 1)[0]
    return f'ثبت للخبرة في النقطة {n} كذا.'


def doc_text(path):
    d = Document(path)
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            for c in row.cells:
                parts.append(c.text)
    return '\n'.join(parts), d


def finish(d, k, final='done'):
    cm.set_step(d, k, 'running')
    cm.set_step(d, k, 'done')
    if final == 'reviewed':
        cm.set_step(d, k, 'reviewed')


class MdTests(unittest.TestCase):
    def test_blocks(self):
        b = rd.md_blocks('<!-- صفحة 1 -->\n## عنوان\nسطر 1\nسطر 2\n\n- أ\n- ب\n\n1. ج\n2. د\n\n'
                         '| h1 | h2 |\n|---|---|\n| x | y |')
        self.assertEqual(b[0], ('sub', 'عنوان'))
        self.assertEqual(b[1], ('p', 'سطر 1 سطر 2'))
        self.assertEqual(b[2], ('bullets', ['أ', 'ب']))
        self.assertEqual(b[3], ('numbered', ['ج', 'د']))
        self.assertEqual(b[4], ('table', [['h1', 'h2'], ['x', 'y']]))
        self.assertEqual(len(b), 5)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        d = self.data
        d['subject'] = 'نزاع حول فواتير خدمات الاتصالات'
        d['mission'] = {'raw': 'ندبت المحكمة الخبير: 1- بيان الفواتير 2- بيان السداد', 'confirmed': True,
                        'next_id': 3, 'points': [{'id': 'q1', 'n': 1, 'text': 'بيان الفواتير'},
                                                 {'id': 'q2', 'n': 2, 'text': 'بيان السداد'}]}
        d['sessions'] = {'count_system': 2, 'expected_minutes': 2, 'missing': [],
                         'minutes': [{'no': 1, 'date': '2026-09-01', 'file': 'x', 'md': ''},
                                     {'no': 2, 'date': '2026-09-15', 'file': 'y', 'md': ''}]}
        d['portfolios'] = [{'id': 'P1', 'submitter': 'المدعية', 'date': '2026-09-01', 'seq': 1, 'docs': [
            {'uid': 'd1', 'no': 1, 'file': '01_اصول/P1/001.pdf', 'md': '', 'type': 'عقد', 'contract': '',
             'convert': {'state': 'done', 'message': ''}}]}]
        finish(d, 'mission', 'reviewed')
        finish(d, 'procedures')
        finish(d, 'documents')
        ca.run_attachments(self.base, d)
        cr.run_research(self.base, d, ask=research_ask)
        cc.run_conclusion(self.base, d, ask=concl_ask)
        self.info = {'source': 'محكمة الاستئناف', 'court_case_number': '2026/1234 تجاري',
                     'plaintiffs': ['شركة وهمية للاتصالات'], 'defendants': ['مدعى عليه تجريبي'],
                     'governorate': 'العاصمة', 'department': 'قضايا الكهرباء والكمبيوتر',
                     'experts': [('الخبير المهندس', 'خبير تجريبي')]}

    def tearDown(self):
        self._tmp.cleanup()

    def test_full_report_contents_and_order(self):
        path, warns = rd.build_report(self.base, self.data, self.info, today='16/10/2026')
        self.assertTrue(os.path.exists(path))
        text, d = doc_text(path)
        order = ['التـقـرير', 'الموضوع:', 'المأمورية:', 'الإجراءات:', 'البحث ورأي الخبرة:', 'النتيجة:', 'المرفقات:']
        pos = [text.index(h) for h in order]
        self.assertEqual(pos, sorted(pos))
        for s in ('A9990001', '16/10/2026', 'محكمة الاستئناف', '2026/1234 تجاري', 'شركة وهمية للاتصالات',
                  'نزاع حول فواتير', 'ندبت المحكمة الخبير: 1- بيان الفواتير 2- بيان السداد',
                  'الجلسة رقم 2 بتاريخ 2026-09-15', '1) بيان الفواتير:', 'التزام أول', '200',
                  'ثبت للخبرة في النقطة 2', 'عدد ( 2 ) محضر أعمال.', 'حافظة مستندات المدعية المؤرخة 01/09/2026.', 'خبير تجريبي'):
            self.assertIn(s, text, s)
        self.assertNotIn('<!--', text)
        self.assertGreaterEqual(len(d.tables), 4)
        sec = d.sections[0]
        self.assertEqual((int(sec.page_width), int(sec.page_height)), (11906 * 635, 16838 * 635))
        self.assertIn('وزارة العدل', sec.header.part.element.xml)

    def test_warnings_for_missing_info_and_unreviewed_steps(self):
        path, warns = rd.build_report(self.base, self.data, {}, today='01/01/2026')
        text, _ = doc_text(path)
        self.assertIn(rd.BLANK, text)
        w = '\n'.join(warns)
        for s in ('الواردة من', 'اسم الخبير', 'المحافظة', 'القسم', 'لم يراجعها الخبير'):
            self.assertIn(s, w)
        self.assertNotIn('«المأمورية» لم يراجعها', w)                 # المأمورية روجعت

    def test_each_issue_is_a_new_version_and_previous_stays(self):
        p1, _ = rd.build_report(self.base, self.data, self.info)
        with open(p1, 'rb') as f:
            before = f.read()
        p2, _ = rd.build_report(self.base, self.data, self.info)
        self.assertNotEqual(p1, p2)
        self.assertTrue(p1.endswith('التقرير_v1.docx') and p2.endswith('التقرير_v2.docx'))
        with open(p1, 'rb') as f:
            self.assertEqual(f.read(), before)                  # الأولى كما هي
        d = cw.read_case_json(self.base)
        self.assertEqual(set(d['files']), {'التقرير/التقرير_v1.docx', 'التقرير/التقرير_v2.docx'})
        self.assertEqual(d['files']['التقرير/التقرير_v1.docx']['by'], 'app')
        self.assertEqual((d['report']['file'], d['report']['version']), ('التقرير/التقرير_v2.docx', 2))

    def test_works_at_any_stage_with_placeholders(self):
        """قضية جديدة تماماً: لا موضوع ولا مأمورية ولا محاضر ولا بنود — يُولَّد الملف بعلامات «[يُكتب]»."""
        with tempfile.TemporaryDirectory() as t:
            base, data = cw.ensure_workspace(CASE, t)
            path, warns = rd.build_report(base, data, {})
            text, _ = doc_text(path)
            self.assertTrue(os.path.exists(path))
            self.assertGreaterEqual(text.count(rd.TODO), 5)
            for h in ('الموضوع:', 'المأمورية:', 'الإجراءات:', 'البحث ورأي الخبرة:', 'النتيجة:', 'المرفقات:'):
                self.assertIn(h, text)
            self.assertTrue(any('[يُكتب]' in w for w in warns))

    def test_partial_stage_keeps_what_exists(self):
        """الموضوع والمأمورية فقط: تظهر نصوصهما، وبقية الأقسام تحمل العلامة."""
        with tempfile.TemporaryDirectory() as t:
            base, data = cw.ensure_workspace(CASE, t)
            data['subject'] = 'موضوع تجريبي'
            data['mission'] = {'raw': 'مأمورية تجريبية', 'confirmed': False, 'next_id': 2,
                               'points': [{'id': 'q1', 'n': 1, 'text': 'نقطة'}]}
            path, _ = rd.build_report(base, data, {})
            text, _ = doc_text(path)
            self.assertIn('موضوع تجريبي', text)
            self.assertIn('مأمورية تجريبية', text)
            # 2026-10-20: لا يُنسخ نص المأمورية تحت «النتيجة» ولا «[يُكتب]» (كان: «نقطة: [يُكتب]»)
            concl = text.split('النتيجة:', 1)[1].split('المرفقات:', 1)[0]
            self.assertNotIn('نقطة', concl)
            self.assertNotIn('[يُكتب]', concl)

    def test_many_parties_and_experts(self):
        info = dict(self.info, plaintiffs=['طرف أول', 'طرف ثاني'],
                    experts=[('الخبير المهندس', 'خبير س'), ('الخبير المهندس', 'خبير ص')])
        path, _ = rd.build_report(self.base, self.data, info)
        text, _ = doc_text(path)
        for s in ('طرف أول', 'طرف ثاني', 'خبير س', 'خبير ص'):
            self.assertIn(s, text)


if __name__ == '__main__':
    unittest.main()
