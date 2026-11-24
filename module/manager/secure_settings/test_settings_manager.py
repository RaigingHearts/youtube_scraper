"""settings_manager の暗号化と設定ファイル入出力を検証する。"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from module.manager.secure_settings import settings_manager


class SettingsManagerTests(unittest.TestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        os.chdir(self.temp_dir.name)

    def tearDown(self):
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def test_generate_and_load_key_round_trip(self):
        generated = settings_manager.generate_key()
        self.assertTrue(os.path.isfile(settings_manager.ENCRYPTION_KEY_FILE))
        with open(settings_manager.ENCRYPTION_KEY_FILE, "rb") as key_file:
            self.assertEqual(key_file.read(), generated)
        self.assertEqual(settings_manager.load_key(), generated)

    def test_load_key_generates_key_when_file_is_missing(self):
        key = settings_manager.load_key()
        self.assertTrue(key)
        self.assertTrue(os.path.isfile(settings_manager.ENCRYPTION_KEY_FILE))

    def test_encrypt_and_decrypt_api_key_round_trip(self):
        original = "test-api-key"
        encrypted = settings_manager.encrypt_api_key(original)
        self.assertTrue(encrypted)
        self.assertNotEqual(encrypted, original)
        self.assertEqual(settings_manager.decrypt_api_key(encrypted), original)

    def test_decrypt_api_key_returns_none_for_invalid_token(self):
        settings_manager.generate_key()
        with self.assertLogs(settings_manager.logger, level="ERROR"):
            result = settings_manager.decrypt_api_key("not-a-valid-token")
        self.assertIsNone(result)

    def test_save_and_load_settings_preserves_unicode_and_values(self):
        expected = {"api_key": "encrypted-value", "label": "設定値"}
        settings_manager.save_settings(expected)
        self.assertEqual(settings_manager.load_settings(), expected)
        with open(settings_manager.SETTINGS_FILE, "r", encoding="utf-8") as file_obj:
            self.assertIn("設定値", file_obj.read())

    def test_load_settings_returns_default_when_file_is_missing(self):
        self.assertEqual(settings_manager.load_settings(), {"api_key": None})

    def test_load_settings_returns_default_for_invalid_json(self):
        with open(settings_manager.SETTINGS_FILE, "w", encoding="utf-8") as file_obj:
            file_obj.write("{invalid")
        with self.assertLogs(settings_manager.logger, level="ERROR"):
            result = settings_manager.load_settings()
        self.assertEqual(result, {"api_key": None})

    def test_save_settings_contains_io_error_without_raising(self):
        with patch("builtins.open", side_effect=IOError("disk unavailable")):
            with self.assertLogs(settings_manager.logger, level="ERROR"):
                settings_manager.save_settings({"api_key": "value"})

    def test_load_settings_returns_default_when_read_fails(self):
        with open(settings_manager.SETTINGS_FILE, "w", encoding="utf-8") as file_obj:
            json.dump({"api_key": "value"}, file_obj)
        with patch("builtins.open", side_effect=IOError("read unavailable")):
            with self.assertLogs(settings_manager.logger, level="ERROR"):
                result = settings_manager.load_settings()
        self.assertEqual(result, {"api_key": None})


if __name__ == "__main__":
    unittest.main()
