# اختبارات المبالغ (رقم/حروف) وإفصاح محرّك القراءة: python -W ignore -m unittest test_amounts_engines -v
import json
import unittest

import case_subject_contract as sc
import doc_router
import test_case_subject_contract as tc

WORDS = 'خمسة آلاف وثمانمائة وستة وسبعون ديناراً وخمسمائة وأربعون فلساً'


def build(plaint_amount):
    plaint = tc.PLAINT.replace('12,500 د.ك', plaint_amount)
    reply = dict(tc.REPLY, contracts=[dict(tc.REPLY['contracts'][0], amount='مبلغ ' + plaint_amount)])
    return sc.build_subject(plaint, ['مدعى عليه تجريبي'], lambda p: json.dumps(reply, ensure_ascii=False))


class AmountInSubjectTests(unittest.TestCase):
    def test_digits_and_words_agree_written_unified(self):
        b = build(f'5,876.540 د.ك ({WORDS})')
        self.assertIn('5,876.540 د.ك', b['text'])
        self.assertEqual(b['alerts'], [])

    def test_disagreement_writes_neither_and_alerts_red_with_both(self):
        b = build(f'58760540 د.ك ({WORDS})')
        self.assertNotIn('58760540', b['text'])
        self.assertIn('مبلغ العقد', b['missing'])
        lvl, msg = b['alerts'][0]
        self.assertEqual(lvl, 'red')
        self.assertIn('58,760,540.000', msg)
        self.assertIn('5,876.540', msg)

    def test_digits_only_written_with_amber_flag(self):
        b = build('5,876.540 د.ك')
        self.assertIn('5,876.540 د.ك', b['text'])
        self.assertEqual(b['alerts'][0][0], 'amber')
        self.assertIn('لم يُتحقق منه بمصدر ثانٍ', b['alerts'][0][1])


class EngineDisclosureTests(unittest.TestCase):
    def test_alert_text(self):
        self.assertIn('قُرئت الصحيفة بمحرك OCR', doc_router.engine_alert('الصحيفة', 'local').replace('OCR المحلي', 'OCR')
                      if False else doc_router.engine_alert('الصحيفة', 'local').replace('محرك OCR المحلي', 'محرك OCR'))
        self.assertEqual(doc_router.engine_alert('الصحيفة', 'gemini'), '')

    def test_step_alerts_for_claim_read_by_ocr(self):
        data = {'engines': {'claim': {'engine': 'local', 'skipped': [['Gemini', 'لا مفتاح Gemini مضبوط']]}},
                'subject_alerts': [['amber', 'x']]}
        out = doc_router.step_alerts(data, 'subject')
        self.assertEqual(out[0][0], 'red')
        self.assertIn('لا مفتاح Gemini', out[0][1])
        self.assertEqual(out[1], ('amber', 'x'))

    def test_read_numbers_without_gemini_reports_reason_and_falls_to_text_layer(self):
        old = doc_router.GEMINI_PROVIDER_FACTORY
        doc_router.GEMINI_PROVIDER_FACTORY = None
        try:
            import ocr_vision
            saved = ocr_vision.load_key
            ocr_vision.load_key = lambda: ''
            res = doc_router.read_numbers_pdf('x.pdf', lambda p: ('محلي', 1), 'ن' * 150)
        finally:
            ocr_vision.load_key = saved
            doc_router.GEMINI_PROVIDER_FACTORY = old
        self.assertEqual(res['engine'], 'text_layer')
        self.assertTrue(any(e == 'gemini' for e, _ in res['skipped']))


if __name__ == '__main__':
    unittest.main()


class BidiTests(unittest.TestCase):
    def test_isolation_is_display_only_and_reversible(self):
        import qt_bidi
        t = 'مؤرخ 10/01/2025 بمبلغ 5,876.540 د.ك للعقد A2263981 [يُكتب]'
        iso = qt_bidi.isolate_tokens(t)
        self.assertNotEqual(iso, t)
        self.assertEqual(qt_bidi.strip_isolates(iso), t)
        self.assertEqual(qt_bidi.isolate_tokens(iso), iso)           # idempotent

    def test_editor_returns_logical_text(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        import qt_bidi
        app = QApplication.instance() or QApplication([])
        t = 'في 10/01/2025 [يُكتب]'
        e = qt_bidi.BidiPlainTextEdit(t)
        self.assertEqual(e.toPlainText(), t)
        self.assertNotEqual(qt_bidi.QPlainTextEdit.toPlainText(e), t)


class HeaderTests(unittest.TestCase):
    def test_priority_system_then_case_then_settings(self):
        import report_docx
        st = {'governorate': 'حولي', 'department': 'قسم الإعدادات'}
        kw, w = report_docx.resolve_header({'governorate': 'الفروانية'}, {'case': {'department': 'قسم القضية'}}, st)
        self.assertEqual(kw, {'governorate': 'الفروانية', 'department': 'قسم القضية'})
        self.assertEqual(w, [])
        kw, w = report_docx.resolve_header({}, {}, st)
        self.assertEqual(kw, st)

    def test_missing_keeps_default_with_warning(self):
        import report_docx
        kw, w = report_docx.resolve_header({}, {}, {})
        self.assertEqual(kw, {})
        self.assertEqual(len(w), 2)
