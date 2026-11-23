"""tk_app_settings のAPIキー取得・入力・保存フローを検証する。"""
import unittest
from unittest.mock import MagicMock, patch

from module.manager.tk_app_settings import tk_app_settings


class TkAppSettingsTests(unittest.TestCase):
    def setUp(self):
        self.root = MagicMock()

    def test_saved_api_key_is_decrypted_without_prompting(self):
        with patch.object(tk_app_settings.settings_manager, "load_settings",
                          return_value={"api_key": "encrypted"}):
            with patch.object(tk_app_settings.settings_manager,
                              "decrypt_api_key", return_value="saved-key"):
                with patch.object(tk_app_settings, "_prompt_for_api_key") as prompt:
                    result = tk_app_settings.check_and_prompt_api_key(self.root)
        self.assertEqual(result, "saved-key")
        prompt.assert_not_called()

    def test_missing_api_key_prompts_and_returns_entered_key(self):
        with patch.object(tk_app_settings.settings_manager, "load_settings",
                          return_value={"api_key": None}):
            with patch.object(tk_app_settings, "_prompt_for_api_key",
                              return_value="entered-key") as prompt:
                result = tk_app_settings.check_and_prompt_api_key(self.root)
        self.assertEqual(result, "entered-key")
        prompt.assert_called_once_with(self.root)

    def test_decryption_failure_reports_error_then_prompts_again(self):
        with patch.object(tk_app_settings.settings_manager, "load_settings",
                          return_value={"api_key": "unreadable"}):
            with patch.object(tk_app_settings.settings_manager,
                              "decrypt_api_key", return_value=None):
                with patch.object(tk_app_settings.messagebox, "showerror") as show_error:
                    with patch.object(tk_app_settings, "_prompt_for_api_key",
                                      return_value="replacement-key") as prompt:
                        result = tk_app_settings.check_and_prompt_api_key(self.root)
        self.assertEqual(result, "replacement-key")
        show_error.assert_called_once()
        prompt.assert_called_once_with(self.root)

    def test_prompt_encrypts_and_saves_entered_key(self):
        with patch.object(tk_app_settings.simpledialog, "askstring",
                          return_value="entered-key") as askstring:
            with patch.object(tk_app_settings.settings_manager,
                              "encrypt_api_key", return_value="encrypted-key"):
                with patch.object(tk_app_settings.settings_manager,
                                  "save_settings") as save_settings:
                    with patch.object(tk_app_settings.messagebox, "showinfo") as show_info:
                        result = tk_app_settings._prompt_for_api_key(self.root)
        self.assertEqual(result, "entered-key")
        askstring.assert_called_once_with(
            "APIキー入力", "YouTube Data APIキーを入力してください:",
            show="*", parent=self.root,
        )
        save_settings.assert_called_once_with({"api_key": "encrypted-key"})
        show_info.assert_called_once()

    def test_prompt_returns_none_and_warns_when_cancelled(self):
        with patch.object(tk_app_settings.simpledialog, "askstring", return_value=None):
            with patch.object(tk_app_settings.messagebox, "showwarning") as show_warning:
                result = tk_app_settings._prompt_for_api_key(self.root)
        self.assertIsNone(result)
        show_warning.assert_called_once()

    def test_prompt_returns_none_when_encryption_fails(self):
        with patch.object(tk_app_settings.simpledialog, "askstring",
                          return_value="entered-key"):
            with patch.object(tk_app_settings.settings_manager,
                              "encrypt_api_key", return_value=""):
                with patch.object(tk_app_settings.settings_manager,
                                  "save_settings") as save_settings:
                    with patch.object(tk_app_settings.messagebox, "showerror") as show_error:
                        result = tk_app_settings._prompt_for_api_key(self.root)
        self.assertIsNone(result)
        save_settings.assert_not_called()
        show_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
