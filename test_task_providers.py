# مزوّد كل مهمة: python -W ignore -m unittest test_task_providers -v
import os
import tempfile
import unittest
from unittest import mock

import ai_providers as ap
import gemini_config as gc

# قيم ثابتة لقسم [task_providers] بدل ini الجهاز الحقيقي (كان يغيّر النتائج من جهاز لآخر)
FIXED_INI = """[task_providers]
extract = auto
summarize = auto
write = gemini,openai
research = gemini,openai
"""


def fake_chain(*specs):
    out = []
    for kind, name in specs:
        cls = ap.GeminiProvider if kind == 'gemini' else ap.OpenAICompatProvider
        out.append(cls(name, 'k', ap.KEY_DEFAULT, 'm'))
    return out


class TaskChainTests(unittest.TestCase):
    def setUp(self):
        """ini مؤقت بقيم ثابتة بدل gemini_network.ini الحقيقي؛ وتنظيف حالة الاختيار المؤقت العامة."""
        self._tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(self._tmp.name, gc._NET_INI_NAME), 'w', encoding='utf-8') as f:
            f.write(FIXED_INI)
        patcher = mock.patch.object(gc, '_app_dir', return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        ap._override.clear()
        ap._missing.clear()
        self.addCleanup(ap._override.clear)
        self.addCleanup(ap._missing.clear)

    def chain(self, task, *specs, spec=None):
        with mock.patch.object(ap, 'build_chain', return_value=fake_chain(*specs)):
            return [p.name for p in ap.build_task_chain(task, spec)]

    def test_write_default_is_gemini_then_openai_without_groq(self):
        got = self.chain('write', ('openai', 'groq'), ('openai', 'zai'), ('gemini', 'Gemini'))
        self.assertEqual(got, ['Gemini', 'zai'])

    def test_groq_never_used_even_when_named(self):
        # سياسة 2026-10-21: Groq خارج كل المهام والسلاسل الاحتياطية، ولو ذُكر صراحةً
        with mock.patch.object(ap, 'build_chain', return_value=fake_chain(('openai', 'groq'), ('gemini', 'Gemini'))):
            with self.assertRaises(ap.ProviderMissing):
                ap.build_task_chain('write', 'groq')
        self.assertEqual(self.chain('write', ('openai', 'groq'), ('openai', 'zai'), spec='gemini,openai,groq'), ['zai'])

    def test_no_silent_downgrade_when_gemini_missing(self):
        with mock.patch.object(ap, 'build_chain', return_value=fake_chain(('openai', 'zai'))):
            with self.assertRaises(ap.ProviderMissing) as cm:
                ap.build_task_chain('write', 'gemini')
        self.assertIn('صياغة نصوص التقرير', str(cm.exception))
        self.assertNotIn('groq', cm.exception.alternatives)
        self.assertEqual(ap.pop_missing()[0], 'write')

    def test_one_shot_override(self):
        ap.set_override('write', 'zai')
        with mock.patch.object(ap, 'build_chain', return_value=fake_chain(('openai', 'zai'))):
            self.assertEqual([p.name for p in ap.build_task_chain('write')], ['zai'])
            self.assertNotIn('write', ap._override)           # استُهلك الاختيار

    def test_auto_keeps_old_text_chain(self):
        with mock.patch.object(ap, 'build_text_chain', return_value=['x']) as m:
            self.assertEqual(ap.build_task_chain('extract'), ['x'])
        m.assert_called_once()

    def test_defaults(self):
        self.assertEqual(ap.TASK_DEFAULTS['research'], 'gemini,openai')
        self.assertEqual(ap.PURPOSE_TASK['الموضوع'], 'write')


if __name__ == '__main__':
    unittest.main()
