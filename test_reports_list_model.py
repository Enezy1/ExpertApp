import unittest

import case_model
import reports_list_model as rlm

CASE = {'caso_no': 'A9990001', 'autocase_no': '1', 'plaintiff': '', 'company': '',
        'defendants': [], 'received_date': '2026-10-01', 'title': 't'}
NO_SAVED = lambda _n: ([], [])


def _ws(states=None):
    """states: {key: (state, message)} ؛ None = لا مجلد."""
    def rd(_n):
        if states is None:
            return None, None
        d = case_model.new_case_data(CASE)
        d['subject'] = 'جاءت المدعية بصحيفة مفادها…'
        for k, (st, msg) in states.items():
            d['steps'][k].update(state=st, message=msg)
        return 'x', d
    return rd


def card(case=None, states=None, saved=NO_SAVED):
    return rlm.build_card(dict(CASE, **(case or {})), _ws(states), saved)


class PartiesTests(unittest.TestCase):
    def test_a2263981_title_is_single_name_saved_parties_win(self):
        # المحتوى الفعلي: METMONTH أعاد اسم المدعى عليها فقط، والمدعي شركة محفوظة في case_db
        vm = card({'title': 'لطيفه        حابس         فاضل         المطيرى'},
                  saved=lambda _n: (['شركه الاتصالات المتنقله (ش.م.ك)'], ['لطيفه حابس فاضل المطيري']))
        self.assertEqual(vm['plaintiff'], 'شركه الاتصالات المتنقله (ش.م.ك)')
        self.assertEqual(vm['defendant'], 'لطيفه حابس فاضل المطيري')

    def test_single_name_title_without_data_is_not_assigned_a_role(self):
        vm = card({'title': 'لطيفه   حابس'})
        self.assertEqual((vm['plaintiff'], vm['defendant']), ('', ''))
        self.assertEqual(vm['other_party'], 'لطيفه حابس')

    def test_person_plaintiff_company_defendant_from_title(self):
        vm = card({'title': 'لطيفه حابس ضد شركة زين'})
        self.assertEqual((vm['plaintiff'], vm['defendant']), ('لطيفه حابس', 'شركة زين'))

    def test_company_plaintiff_person_defendant_from_title(self):
        vm = card({'title': 'شركة زين ضد لطيفه حابس'})
        self.assertEqual((vm['plaintiff'], vm['defendant']), ('شركة زين', 'لطيفه حابس'))

    def test_system_defendants_used_and_plaintiff_kept(self):
        vm = card({'title': 'x', 'plaintiff': 'شركة زين', 'defendants': ['أحمد', 'سعد']})
        self.assertEqual((vm['plaintiff'], vm['defendant']), ('شركة زين', 'أحمد، سعد'))

    def test_multiple_parties_saved_deduped(self):
        vm = card(saved=lambda _n: (['أ', 'ب', 'أ'], ['ج', 'د']))
        self.assertEqual((vm['plaintiff'], vm['defendant']), ('أ، ب', 'ج، د'))

    def test_word_didd_inside_name_not_split(self):
        vm = card({'title': 'ضدان للتجارة'})
        self.assertEqual(vm['plaintiff'], ''); self.assertEqual(vm['other_party'], 'ضدان للتجارة')

    def test_title_starting_with_didd(self):
        vm = card({'title': 'ضد لطيفه'})
        self.assertEqual((vm['plaintiff'], vm['defendant']), ('', 'لطيفه'))


class StepsTests(unittest.TestCase):
    def test_not_started(self):
        for st in (None, {}):
            vm = card(states=st)
            self.assertFalse(vm['started']); self.assertEqual(vm['hint'], 'لم يبدأ التقرير بعد')
            self.assertTrue(all(s[2] == rlm.ST_IDLE for s in vm['steps']))
            self.assertFalse(vm['in_progress']); self.assertEqual(vm['accent'], 'normal')
        self.assertEqual(vm['has_workspace'], True)

    def test_display_order_and_names(self):
        names = [s[1] for s in card()['steps']]
        self.assertEqual(names, ['المستندات', 'الموضوع', 'المأمورية', 'الإجراءات', 'البحث', 'المرفقات'])

    def test_needs_input_amber_hint_and_next_not_marked(self):
        vm = card(states={'subject': ('reviewed', ''), 'mission': ('done', ''),
                          'procedures': ('needs_input', 'تحتاج إثبات حضور الأطراف')})
        self.assertEqual(vm['accent'], 'input'); self.assertTrue(vm['needs_me'])
        self.assertEqual(vm['hint'], 'الإجراءات: تحتاج إثبات حضور الأطراف')
        self.assertEqual([s[2] for s in vm['steps']][1:4], ['done', 'done', 'input'])

    def test_failed_beats_input_and_red(self):
        vm = card(states={'subject': ('needs_input', 'م'), 'documents': ('failed', 'تعذّر')})
        self.assertEqual(vm['accent'], 'failed')
        self.assertEqual(vm['hint'], 'المستندات: تعذّر')

    def test_running_is_current(self):
        vm = card(states={'subject': ('reviewed', ''), 'mission': ('running', '')})
        self.assertEqual(vm['steps'][2][2], 'current'); self.assertEqual(vm['hint'], 'المأمورية: قيد التنفيذ')

    def test_next_step_is_current_when_nothing_waits(self):
        vm = card(states={'documents': ('done', ''), 'subject': ('reviewed', ''), 'mission': ('reviewed', '')})
        self.assertEqual(vm['steps'][3][2], 'current'); self.assertTrue(vm['in_progress'])
        self.assertEqual(vm['accent'], 'normal')

    def test_all_done(self):
        from unittest import mock
        with mock.patch.object(rlm, 'attachments_complete', lambda d: True):
            vm = card(states={k: ('reviewed', '') for k in case_model.STEP_KEYS})
        self.assertEqual(vm['hint'], 'اكتملت كل الخطوات'); self.assertFalse(vm['in_progress'])

    def test_kpis_and_search(self):
        a = card(states={'subject': ('needs_input', 'x')})
        b = card({'caso_no': 'A9990002'}, states=None)
        c = card({'caso_no': 'A9990003'}, states={'subject': ('reviewed', '')})
        k = rlm.kpis([a, b, c])
        self.assertEqual((k['active'], k['preparing'], k['needs_me']), (3, 2, 1))
        self.assertEqual(len(rlm.search([a, b, c], '9990002')), 1)
        self.assertEqual(len(rlm.search([a, b, c], '')), 3)


if __name__ == '__main__':
    unittest.main()


class EmptySubjectTests(unittest.TestCase):
    def test_done_subject_without_text_is_failed_not_finished(self):
        d = case_model.new_case_data(CASE)
        d['steps']['subject'].update(state='done')
        d['stage2'] = {'error': 'ردّ المرحلة الثانية ليس JSON'}
        steps, _s = rlm.step_states(d)
        st = {k: (s, m) for k, _n, s, m in steps}['subject']
        self.assertEqual(st[0], rlm.ST_FAILED)
        self.assertIn('تعذّر', st[1])
        self.assertIn('ليس JSON', st[1])
        self.assertEqual(rlm.ST_TEXT[rlm.ST_FAILED], 'تعذّر')
