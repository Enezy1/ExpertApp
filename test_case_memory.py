# اختبارات المرحلة 2ز (ملف الذاكرة): python -m unittest test_case_memory -v
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

import case_memory as mem
import case_model as cm
import case_workspace as cw

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)


def put(base, rel, text):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text)
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        d = self.data
        d['subject'] = 'نزاع حول فواتير'
        d['mission'] = {'raw': '1- بيان الفواتير 2- بيان السداد', 'confirmed': True,
                        'points': [{'n': 1, 'text': 'بيان الفواتير'}, {'n': 2, 'text': 'بيان السداد'}]}
        d['sessions'] = {'count_system': 4, 'minutes': [{'date': '2026-09-01', 'file': 'م1.pdf', 'md': ''}]}
        sha = put(self.base, '02_markdown/P1-001.md', '<!-- صفحة 1 -->\nنص العقد')
        d['portfolios'] = [{'id': 'P1', 'submitter': 'المدعية', 'date': '2026-09-01', 'docs': [
            {'no': 1, 'file': '01_اصول/P1/001.pdf', 'md': '02_markdown/P1-001.md', 'type': 'عقد',
             'contract': 'رقم|1', 'pages': 1, 'sha1': sha, 'convert': {'state': 'done', 'message': ''}}]}]
        sha = put(self.base, '04_تقرير/بنود/01.md', 'رأي البند الأول')
        d['research'] = [{'n': 1, 'state': 'reviewed', 'file': '04_تقرير/بنود/01.md', 'summary': 's', 'sha1': sha}]
        cm.set_step(d, 'subject', 'running')
        cm.set_step(d, 'subject', 'done')
        cw.write_case_json(self.base, d)
        self.path = mem.memory_path(self.base)

    def tearDown(self):
        self._tmp.cleanup()

    def read(self):
        with open(self.path, encoding='utf-8', newline='') as f:
            return f.read()

    def test_full_generation_has_all_sections_in_order(self):
        mem.regenerate(self.base, self.data)
        t = self.read()
        pos = [t.index(f'<!-- BEGIN:{s} ') for s in mem.SECTION_IDS]
        self.assertEqual(pos, sorted(pos))
        for needle in ('نزاع حول فواتير', '1- بيان الفواتير', '1. بيان الفواتير', 'نص العقد',
                       '<!-- صفحة 1 -->', 'رأي البند الأول', '- الموضوع: كُتبت', 'رقم' + chr(92) + '|1'):
            self.assertIn(needle, t)
        self.assertIsNotNone(mem._parse(t))

    def test_update_one_section_leaves_others_byte_identical(self):
        mem.regenerate(self.base, self.data)
        before = self.read()
        self.data['subject'] = 'موضوع جديد'
        self.assertEqual(mem.update_section(self.base, self.data, 'case'), 'updated')
        after = self.read()
        self.assertIn('موضوع جديد', after)
        old = {m.group(1): m.group(0) for m in mem._SEC_RE.finditer(before)}
        new = {m.group(1): m.group(0) for m in mem._SEC_RE.finditer(after)}
        for s in mem.SECTION_IDS:
            if s == 'case':
                self.assertNotEqual(old[s], new[s])
            else:
                self.assertEqual(old[s], new[s], s)
        self.assertTrue(os.path.exists(self.path + '.bak'))
        self.assertIsNotNone(mem._parse(after))

    def test_missing_markers_regenerates_and_quarantines(self):
        mem.regenerate(self.base, self.data)
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('# ملف عبث بلا علامات')
        self.assertEqual(mem.update_section(self.base, self.data, 'status'), 'regenerated')
        self.assertIsNotNone(mem._parse(self.read()))
        bad = [n for n in os.listdir(os.path.dirname(self.path)) if '.corrupt-' in n]
        self.assertEqual(len(bad), 1)

    def test_manual_edit_detected_by_sha(self):
        mem.regenerate(self.base, self.data)
        t = self.read().replace('نزاع حول فواتير', 'نزاع معدّل يدوياً')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(t)
        self.assertEqual(mem.update_section(self.base, self.data, 'status'), 'regenerated')
        self.assertIn('نزاع حول فواتير', self.read())
        self.assertNotIn('معدّل يدوياً', self.read())

    def test_missing_file_generated(self):
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(mem.update_section(self.base, self.data, 'mission'), 'regenerated')
        self.assertTrue(os.path.exists(self.path))

    def test_doc_sha_mismatch_and_missing_md_flagged(self):
        put(self.base, '02_markdown/P1-001.md', 'نص مختلف')
        self.data['portfolios'][0]['docs'].append(
            {'no': 2, 'file': 'x', 'md': '02_markdown/ضائع.md', 'type': 'فاتورة', 'convert': {}})
        mem.regenerate(self.base, self.data)
        t = self.read()
        self.assertIn('بصمة الملف لا تطابق', t)
        self.assertIn('الملف غير موجود', t)

    def test_crash_mid_write_keeps_old_file_intact(self):
        mem.regenerate(self.base, self.data)
        before = self.read()
        self.data['subject'] = 'لن يُحفظ'
        real = os.replace

        def flaky(src, dst):
            if dst == self.path:
                raise OSError('انقطاع متعمَّد')
            return real(src, dst)
        with mock.patch('case_memory.os.replace', side_effect=flaky):
            with self.assertRaises(OSError):
                mem.update_section(self.base, self.data, 'case')
        self.assertEqual(self.read(), before)
        self.assertIsNotNone(mem._parse(self.read()))
        self.assertFalse([n for n in os.listdir(os.path.dirname(self.path)) if n.endswith('.tmp')])

    def test_unknown_section(self):
        with self.assertRaises(KeyError):
            mem.update_section(self.base, self.data, 'nope')

    def test_empty_case_renders(self):
        with tempfile.TemporaryDirectory() as root:
            base, data = cw.ensure_workspace(CASE, root)
            mem.regenerate(base, data)
            with open(mem.memory_path(base), encoding='utf-8') as f:
                self.assertIsNotNone(mem._parse(f.read()))


if __name__ == '__main__':
    unittest.main()
