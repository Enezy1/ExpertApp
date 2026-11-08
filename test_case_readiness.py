# اختبارات «فحص الجاهزية» بمزوّد وهمي: python -W ignore -m unittest test_case_readiness -v
# بند جاهز، بند ناقص (مذكرة دفاع غير مرفقة) ← طلب صحيح، إضافة المستند تُغلق الطلب، «اكتب رغم النقص»،
# وقضية فيها بند جاهز وآخر ناقص. لا متطلب «موجود» بلا موضع محدد، ولا رقم من النموذج خارج جدول الوقائع.
import json
import os
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import case_documents as cd
import case_model as cm
import case_readiness as rd
import case_research as cr
import case_workspace as cw

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'test_data', 'dummy_case.json'), encoding='utf-8') as _f:
    CASE = json.load(_f)

CONTRACT = ('<!-- صفحة 1 -->\nعقد اشتراك\n<!-- صفحة 2 -->\nحيث اتفق الطرفان على أن يسدد المدعى عليه اشتراكاً '
            'شهرياً قدره 46.500 دينار لمدة 24 شهراً من تاريخ التوقيع')
DEFENSE = '<!-- صفحة 1 -->\nمذكرة بدفاع المدعى عليه مقدمة أمام المحكمة يدفع فيها بانقضاء العقد بالإلغاء'
P1 = {'id': 'q1', 'n': 1, 'text': 'بيان قيمة الاشتراك الشهري ومدة الالتزام في العقد'}
P2 = {'id': 'q2', 'n': 2, 'text': 'بحث دفاع المدعى عليه بانقضاء العقد'}


class FakeAsk:
    """يردّ لكل بند بمتطلباته؛ «مذكرة الدفاع» موجودة فقط إن كان نصها ضمن الطلب (كما يفعل نموذج حقيقي)."""

    def __init__(self):
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        if 'بحث دفاع المدعى عليه' in prompt.split('## المستندات')[0]:
            found = ({'doc': 'P2-1', 'page': 1, 'quote': 'مذكرة بدفاع المدعى عليه مقدمة أمام المحكمة'}
                     if 'مذكرة بدفاع' in prompt else None)
            reqs = [{'need': 'مذكرة الدفاع المقدمة أمام المحكمة', 'from': 'المدعى عليه',
                     'why': 'لبيان أوجه دفاعه بانقضاء العقد', 'found': found}]
        else:
            reqs = [{'need': 'العقد المبيّن لقيمة الاشتراك ومدته', 'from': 'المدعية', 'why': 'لتحديد الالتزام',
                     'found': {'doc': 'P1-1', 'page': 2, 'quote': 'يسدد المدعى عليه اشتراكاً شهرياً قدره 46.500 دينار'}}]
        return json.dumps({'requirements': reqs}, ensure_ascii=False)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base, self.data = cw.ensure_workspace(CASE, self._tmp.name)
        d = self.data
        d['subject'] = 'نزاع اشتراك'
        d['mission'] = {'raw': '1- ... 2- ...', 'confirmed': True, 'next_id': 3, 'points': [dict(P1), dict(P2)]}
        for s in ('running', 'done', 'reviewed'):
            cm.set_step(d, 'mission', s)
        self.add_doc('المدعية', CONTRACT, 'عقد')
        cw.write_case_json(self.base, d)
        self.ask = FakeAsk()

    def tearDown(self):
        self._tmp.cleanup()

    def add_doc(self, who, text, typ):
        src = os.path.join(self._tmp.name, f'{typ}.pdf')
        open(src, 'wb').write(text.encode('utf-8'))
        p = cd.add_portfolio(self.data, who, '2026-09-01')
        cd.import_batch(self.base, self.data, p['id'], [{'src': src, 'no': 1}],
                        convert=lambda path, t=text: (t, 2),
                        classify=lambda path: {'type': 'حافظة مستندات', 'confidence': 1.0, 'reason': 'اختبار'})
        cd.find_doc(self.data, p['docs'][0]['uid'])[1]['type'] = typ
        cw.write_case_json(self.base, self.data)

    def run_check(self):
        return rd.run_readiness(self.base, self.data, ask=self.ask)

    def res(self, pid):
        return rd.item(self.data, pid)


class ReadinessTests(Base):
    def test_ready_item_has_exact_location(self):
        self.run_check()
        r = self.res('q1')
        self.assertEqual((r['state'], r['score']), ('ready', 100))
        self.assertEqual(r['requirements'][0]['where'], 'حافظة P1 (المدعية) — مستند P1-1 «عقد» — صفحة 2')
        self.assertIn('البند 1 جاهز (100%)', rd.sentence(self.data, r))

    def test_missing_defense_memo_creates_formal_request(self):
        self.run_check()
        r = self.res('q2')
        self.assertEqual((r['state'], r['score'], r['missing']), ('missing', 0, ['مذكرة الدفاع المقدمة أمام المحكمة']))
        qs = rd.open_questions(self.data, 'q2')
        self.assertEqual(len(qs), 1)
        q = qs[0]
        self.assertEqual((q['to'], q['point_n'], q['auto']), ('المدعى عليه', 2, True))
        self.assertEqual(q['text'], 'تكليف المدعى عليه بتقديم مذكرة الدفاع المقدمة أمام المحكمة')      # سطر موجز بلا تعليل
        self.assertEqual(rd.sentence(self.data, r), 'البند 2 ناقص (0%): لم يُرفق مذكرة الدفاع المقدمة أمام المحكمة، '
                                                    'أُضيف طلب تقديمه للأسئلة المهمة.')
        self.assertIn(q['text'], rd.questions_html(self.data))
        self.assertEqual(cw.read_case_json(self.base)['questions'][0]['id'], q['id'])      # محفوظ في case.json

    def test_claimed_location_not_in_text_is_missing(self):
        """القاعدة الصارمة: النموذج ادّعى موضعاً لكن الاقتباس غير وارد حرفياً ← ناقص."""
        def liar(prompt):
            return json.dumps({'requirements': [{'need': 'كشف الحساب', 'from': 'المدعية', 'why': 'للمديونية',
                                                 'found': {'doc': 'P1-1', 'page': 1,
                                                           'quote': 'كشف حساب العميل للفترة من يناير إلى يونيو'}}]},
                              ensure_ascii=False)
        rd.run_readiness(self.base, self.data, ask=liar)
        r = self.res('q1')
        self.assertEqual(r['state'], 'missing')
        self.assertTrue(r['requirements'][0]['claimed'])

    def test_adding_document_closes_request_and_keeps_others(self):
        self.run_check()
        self.data['questions'].append({'id': 'm9', 'text': 'سؤال يدوي', 'status': 'open', 'auto': False})
        qid = rd.open_questions(self.data, 'q2')[0]['id']
        self.add_doc('المدعى عليه', DEFENSE, 'مذكرة دفاع')
        self.assertTrue(rd.is_stale(self.data))
        self.run_check()
        q = next(q for q in self.data['questions'] if q['id'] == qid)
        self.assertEqual(q['status'], 'closed')
        self.assertIn('مستند P2-1', q['closed_by'])
        self.assertEqual(self.res('q2')['state'], 'ready')
        self.assertEqual([q['id'] for q in rd.open_questions(self.data)], ['m9'])           # اليدوي باقٍ
        self.assertEqual(self.data['readiness']['closed'], [qid])

    def test_case_with_ready_and_missing_items(self):
        self.run_check()
        self.assertEqual(rd.ready_ids(self.data), ['q1'])
        self.assertEqual(cr.run_research(self.base, self.data, ask=lambda p: f'نص [P1-1]\n{cr.SUMMARY_MARK}\nخ',
                                         only=set(rd.ready_ids(self.data))), 'needs_input')
        states = {i['id']: i['state'] for i in self.data['research']}
        self.assertEqual(states, {'q1': 'done', 'q2': 'pending'})
        self.assertIn('بانتظار مستند', self.data['steps']['research']['message'])

    def test_write_despite_missing_puts_marker(self):
        self.run_check()
        cr.sync_items(self.data)
        r = self.res('q2')
        cr.rewrite_item(self.base, self.data, 'q2', ask=lambda p: f'يدفع المدعى عليه بانقضاء العقد.\n{cr.SUMMARY_MARK}\nخ',
                        missing=r['missing'])
        it = next(i for i in self.data['research'] if i['id'] == 'q2')
        with open(os.path.join(self.base, it['file']), encoding='utf-8') as f:
            body = f.read()
        self.assertIn('[ناقص: مذكرة الدفاع المقدمة أمام المحكمة]', body)
        self.assertEqual(it['written_with_missing'], r['missing'])

    def test_model_number_outside_facts_is_marked(self):
        self.run_check()
        cr.sync_items(self.data)
        cr.rewrite_item(self.base, self.data, 'q1',
                        ask=lambda p: f'الاشتراك 46.500 دينار والمديونية 789.529 دينار [P1-1].\n{cr.SUMMARY_MARK}\nخ')
        it = next(i for i in self.data['research'] if i['id'] == 'q1')
        with open(os.path.join(self.base, it['file']), encoding='utf-8') as f:
            body = f.read()
        self.assertIn('الاشتراك 46.500 دينار', body)                          # من جدول الوقائع
        self.assertIn('[رقم غير موثّق: 789.529]', body)
        self.assertTrue(os.path.exists(os.path.join(self.base, rd.FACTS_REL)))

    def test_mission_counts_as_confirmed(self):
        self.data['steps']['mission']['state'] = 'needs_input'     # صحيحة ما لم يعدّلها الخبير
        self.run_check()
        self.assertEqual(cm.state(self.data, 'mission'), 'reviewed')


class PageTests(Base):
    """بطاقة «الجاهزية» في صفحة القضية."""

    def setUp(self):
        super().setUp()
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        import ai_call_log
        ai_call_log.PATH_OVERRIDE = os.path.join(tempfile.gettempdir(), 'expertapp_test_ai_calls.log')
        cm.set_step(self.data, 'documents', 'running')
        cm.set_step(self.data, 'documents', 'done')
        cw.write_case_json(self.base, self.data)

    def wait(self, dlg):
        end = time.time() + 10
        while (dlg._busy or not dlg.data.get('readiness')) and time.time() < end:
            self.app.processEvents()
            time.sleep(0.02)
        for _ in range(5):
            self.app.processEvents()

    def test_card_shows_items_and_buttons(self):
        """المراحل الثلاث: الجاهزية بالكود من الملخص (بلا أي طلب ذكاء)؛ الناقص طلب للخصم في «الأسئلة المهمة»."""
        import qt_case_page as qp
        qp.CasePageDialog.AUTO_SYNC = qp.CasePageDialog.AUTO_ASK_TYPE = False
        from PyQt6.QtWidgets import QPushButton
        with mock.patch.object(qp.CasePageDialog, 'AUTO_PROCEDURES', False):
            dlg = qp.CasePageDialog(self.base, cw.read_case_json(self.base), ask=self.ask)
            dlg.open_step('research')                                # يُفحص بالكود فوراً
            self.wait(dlg)
            labels = ' '.join(__import__('qt_bidi').strip_isolates(l.text()) for l in dlg.card.findChildren(qp.QLabel))
            self.assertIn('البند 1 ناقص (0%): لم يُرفق العقد بين طرفي الدعوى، أُضيف طلب تقديمه', labels)
            self.assertIn('بانتظار مستند', labels)
            self.assertEqual(self.ask.calls, [])                     # لا طلب لكل نقطة
            btns = {b.text(): b for b in dlg.card.findChildren(QPushButton)}
            self.assertTrue(btns['اكتب البحث'].isEnabled())            # زر واحد؛ الناقص يُكتب ملاحظة «ناقص»
            self.assertNotIn('اكتب رغم النقص', btns)
            q = qp.QuestionsDialog(self.base, dlg.data, dlg, auto=False)
            self.assertIn('تكليف المدعية بتقديم العقد بين طرفي الدعوى', q.table_party.item(0, 2).text())
            # العقد ثبت في الملخص (الفرز) ← البند جاهز ويُغلق طلبه
            dlg.data['main_contract'] = {'found': True, 'contract': {'file': 'حوافظ/حافظة.pdf'}}
            dlg._run_readiness()
            labels = ' '.join(__import__('qt_bidi').strip_isolates(l.text()) for l in dlg.card.findChildren(qp.QLabel))
            self.assertIn('البند 1 جاهز (100%)', labels)
            self.assertEqual(self.ask.calls, [])

if __name__ == '__main__':
    unittest.main()
