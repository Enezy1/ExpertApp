# اختبارات المرحلة 2د (مكان الحفظ): python -m unittest test_reports_root_setup -v
import os
import unittest

import case_workspace
import reports_root_setup as rs


class SuggestTests(unittest.TestCase):
    def test_base_options_without_onedrive(self):
        r = rs.suggest_roots(env={}, home='C:\\U')
        self.assertEqual([l for l, _ in r], ['المستندات', 'سطح المكتب'])
        self.assertTrue(r[0][1].endswith(rs.FOLDER_NAME))

    def test_onedrive_detected(self):
        r = rs.suggest_roots(env={'OneDrive': 'D:\\OD'}, home='C:\\U', exists=lambda p: True)
        self.assertEqual(r[-1][0], 'OneDrive')
        self.assertEqual(r[-1][1], os.path.join('D:\\OD', rs.FOLDER_NAME))

    def test_onedrive_commercial_and_dedupe(self):
        env = {'OneDrive': 'D:\\OD', 'OneDriveCommercial': 'D:\\OD'}
        self.assertEqual(len(rs.suggest_roots(env=env, home='C:\\U', exists=lambda p: True)), 3)
        env['OneDriveCommercial'] = 'E:\\Work'
        r = rs.suggest_roots(env=env, home='C:\\U', exists=lambda p: True)
        self.assertEqual([l for l, _ in r][2:], ['OneDrive', 'OneDrive (العمل)'])

    def test_onedrive_missing_folder_ignored(self):
        r = rs.suggest_roots(env={'OneDrive': 'D:\\gone'}, home='C:\\U', exists=lambda p: False)
        self.assertEqual(len(r), 2)


class SaveTests(unittest.TestCase):
    def test_save_then_not_asked_again(self):
        store = {'v': ''}
        self.assertFalse(rs.has_saved_root(lambda: store['v']))
        rs.save_choice('C:\\R\\تقارير', save=lambda p: store.update(v=p))
        self.assertTrue(rs.has_saved_root(lambda: store['v']))
        self.assertEqual(store['v'], 'C:\\R\\تقارير')

    def test_empty_and_too_long_rejected(self):
        with self.assertRaises(case_workspace.WorkspaceError):
            rs.save_choice('  ', save=lambda p: None)
        with self.assertRaises(case_workspace.WorkspaceError):
            rs.save_choice('C:\\' + 'ا' * 200, save=lambda p: self.fail('لا يجب الحفظ'))


if __name__ == '__main__':
    unittest.main()
