"""settings_manager のインポート時副作用と明示的初期化を検証する。"""
import importlib
import os
import tempfile
import unittest


class SettingsManagerInitializationTests(unittest.TestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        os.chdir(self.temp_dir.name)

    def tearDown(self):
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def test_import_does_not_create_settings_or_key_files(self):
        from module.manager.secure_settings import settings_manager
        importlib.reload(settings_manager)

        self.assertFalse(os.path.exists(settings_manager.SETTINGS_FILE))
        self.assertFalse(os.path.exists(settings_manager.ENCRYPTION_KEY_FILE))

    def test_initialize_settings_creates_missing_files(self):
        from module.manager.secure_settings import settings_manager
        importlib.reload(settings_manager)

        settings_manager.initialize_settings()

        self.assertTrue(os.path.isfile(settings_manager.SETTINGS_FILE))
        self.assertTrue(os.path.isfile(settings_manager.ENCRYPTION_KEY_FILE))


if __name__ == "__main__":
    unittest.main()
