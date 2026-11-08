# قائمة القضايا المحجوزة: الرقم الآلي من زر «الملف الالى» لا من «رقم الاجراء» (خطأ 2026-10-21: الملف الآلي فارغ للمحجوزة)
# python -W ignore -m unittest test_pending_cases -v
import unittest
from unittest import mock

import pending_cases as pc

HEAD = ('<table><thead><tr><th> الملف الالى </th><th> تفاصيل </th><th>رقم الاجراء</th><th>تاريخ المباشره </th>'
        '<th>جلسه الحجز </th><th>الرقم الالى </th><th> رقم الخبرة </th><th>المدعى</th></tr></thead><tbody>')


def row(caso, auto, action, onset, booked, link=True):
    btn = (f"<button onclick=\"aftershowImg('{caso}',{auto})\"><a href='./ShowImg.php?DocId=xx'><i></i></a></button>"
           if link else '<button></button>')
    return (f'<td width="8%"> {btn}</td><td width="8%"> <button onclick="showImg(\'{caso}\')"><i></i></button></td>'
            f'<td>{action}</td><td>{onset}</td><td>{booked}</td><td>{auto}</td><td>{caso}</td><td> </td></tr>')


class ReservedTests(unittest.TestCase):
    def run_with(self, html):
        resp = mock.Mock(text=html)
        with mock.patch.object(pc.requests, 'post'), mock.patch.object(pc.requests, 'get', return_value=resp):
            return pc.get_reserved_cases({})

    def test_autocase_is_not_action_number(self):
        html = HEAD + row('A2263973', '261932780', '4738796', '06/10/2026', '2026-10-18') \
            + row('A2263970', '260517110', '4738797', '06/10/2026', '2026-10-19') + '</tbody></table>'
        got = {c['caso_no']: c for c in self.run_with(html)}
        self.assertEqual(got['A2263970']['autocase_no'], '260517110')
        self.assertEqual(got['A2263970']['action_no'], '4738797')
        self.assertEqual(got['A2263973']['autocase_no'], '261932780')
        self.assertEqual(got['A2263970']['received_date'], '2026-10-06')
        self.assertEqual(got['A2263970']['reserved_date'], '2026-10-19')

    def test_column_fallback_without_button(self):
        html = HEAD + row('A2263970', '260517110', '4738797', '06/10/2026', '2026-10-19', link=False) + '</tbody></table>'
        self.assertEqual(self.run_with(html)[0]['autocase_no'], '260517110')

    def test_map_from_buttons(self):
        self.assertEqual(pc.reserved_autocase_map("x aftershowImg('A2263970',260517110) y"), {'A2263970': '260517110'})


if __name__ == '__main__':
    unittest.main()
