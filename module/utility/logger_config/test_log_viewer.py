"""ログ閲覧ウィンドウのファイル読み込み・表示動作を検証する。"""

import unittest
from unittest.mock import MagicMock, mock_open, patch

from module.utility.logger_config import log_viewer


class LogViewerTests(unittest.TestCase):
    def setUp(self):
        self.window = MagicMock()
        self.text_area = MagicMock()
        self.button = MagicMock()

    def show_window(self):
        with patch.object(log_viewer.tk, "Toplevel", return_value=self.window):
            with patch.object(
                log_viewer, "ScrolledText", return_value=self.text_area
            ):
                with patch.object(log_viewer.tk, "Button", return_value=self.button):
                    window = log_viewer.show_log_window(parent=MagicMock())
        self.assertIs(window, self.window)
        # show_log_window performs an initial load; isolate each test's explicit refresh.
        self.text_area.reset_mock()
        return self.button.call_args.kwargs["command"]

    def test_existing_log_file_is_read_as_utf8_and_displayed(self):
        refresh = self.show_window()
        with patch.object(log_viewer.os.path, "exists", return_value=True):
            with patch("builtins.open", mock_open(read_data="ログ内容")) as open_file:
                refresh()

        open_file.assert_called_once_with(
            log_viewer.LOG_FILE, "r", encoding="utf-8"
        )
        self.text_area.delete.assert_called_once_with("1.0", log_viewer.tk.END)
        self.text_area.insert.assert_called_once_with(log_viewer.tk.END, "ログ内容")
        self.text_area.see.assert_called_once_with(log_viewer.tk.END)

    def test_missing_log_file_displays_not_created_message(self):
        refresh = self.show_window()
        with patch.object(log_viewer.os.path, "exists", return_value=False):
            with patch("builtins.open") as open_file:
                refresh()

        open_file.assert_not_called()
        self.text_area.insert.assert_called_once_with(
            log_viewer.tk.END, "ログファイルはまだ存在しません。"
        )
        self.text_area.see.assert_not_called()

    def test_log_read_oserror_is_displayed_and_logged(self):
        refresh = self.show_window()
        with patch.object(log_viewer.os.path, "exists", return_value=True):
            with patch("builtins.open", side_effect=OSError("access denied")):
                with self.assertLogs(log_viewer.logger, level="ERROR") as captured:
                    refresh()

        self.text_area.insert.assert_called_once()
        displayed_message = self.text_area.insert.call_args.args[1]
        self.assertIn("ログファイルの読み込み中にエラーが発生しました", displayed_message)
        self.assertIn("access denied", displayed_message)
        self.assertTrue(captured.output)

    def test_refresh_button_reloads_log_content(self):
        refresh = self.show_window()
        file_handle = mock_open(read_data="最新ログ").return_value
        with patch.object(log_viewer.os.path, "exists", return_value=True):
            with patch("builtins.open", return_value=file_handle) as open_file:
                refresh()

        self.text_area.delete.assert_called_once_with("1.0", log_viewer.tk.END)
        open_file.assert_called_once_with(
            log_viewer.LOG_FILE, "r", encoding="utf-8"
        )
        self.text_area.insert.assert_called_once_with(log_viewer.tk.END, "最新ログ")
