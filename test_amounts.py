import unittest
from decimal import Decimal as D
import amounts as a


class WordsTests(unittest.TestCase):
    def test_full(self):
        self.assertEqual(a.words_to_decimal('خمسة آلاف وثمانمائة وستة وسبعون ديناراً وخمسمائة وأربعون فلساً'), D('5876.540'))

    def test_simple(self):
        self.assertEqual(a.words_to_decimal('ألف دينار'), D('1000'))
        self.assertEqual(a.words_to_decimal('مائة وخمسون ديناراً فقط لا غير'), D('150'))
        self.assertEqual(a.words_to_decimal('ألفان وخمسمائة دينار'), D('2500'))
        self.assertEqual(a.words_to_decimal('ثلاثة عشر ألف دينار وخمسة وعشرون فلساً'), D('13000.025'))
        self.assertEqual(a.words_to_decimal('مائتان وخمسة دنانير'), D('205'))
        self.assertEqual(a.words_to_decimal('ثلاث مائة دينار'), D('300'))

    def test_unparseable(self):
        self.assertIsNone(a.words_to_decimal('كلام آخر'))
        self.assertIsNone(a.words_to_decimal('خمسة غريبة دينار'))


class ReconcileTests(unittest.TestCase):
    def test_match(self):
        r = a.reconcile('مبلغ 5,876.540 د.ك (خمسة آلاف وثمانمائة وستة وسبعون ديناراً وخمسمائة وأربعون فلساً)')
        self.assertEqual((r['status'], r['display']), (a.OK, '5,876.540 د.ك'))

    def test_mismatch_never_written(self):
        r = a.reconcile('58760540 (خمسة آلاف وثمانمائة وستة وسبعون ديناراً وخمسمائة وأربعون فلساً)')
        self.assertEqual(r['status'], a.MISMATCH)
        self.assertIsNone(r['value'])
        self.assertIn('5,876.540', r['message'])

    def test_one_source(self):
        r = a.reconcile('5876.540 دينار')
        self.assertEqual((r['status'], r['value']), (a.DIGITS_ONLY, D('5876.540')))
        self.assertIn(a.UNVERIFIED_MARK, r['message'])
        r = a.reconcile('', 'فقط خمسة آلاف دينار')
        self.assertEqual(r['status'], a.WORDS_ONLY)

    def test_indic_digits_and_context(self):
        r = a.reconcile('٥٬٠٠٠ دينار', 'أي خمسة آلاف دينار')
        self.assertEqual(r['status'], a.OK)

    def test_fmt(self):
        self.assertEqual(a.fmt_kwd(D('5876.54')), '5,876.540 د.ك')


if __name__ == '__main__':
    unittest.main()
