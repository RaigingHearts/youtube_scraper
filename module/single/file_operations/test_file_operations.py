"""Tests for opening files with the operating system's default application."""

import os
import tempfile
import unittest
from unittest.mock import patch

from module.single.file_operations import file_operations


class OpenFileInDefaultAppTests(unittest.TestCase):
    def test_windows_uses_startfile_with_the_requested_path(self):
        with tempfile.NamedTemporaryFile() as target:
            with patch.object(file_operations.sys, "platform", "win32"):
                with patch.object(
                    file_operations.os, "startfile", create=True
                ) as startfile:
                    with self.assertLogs(
                        "module.single.file_operations.file_operations",
                        level="INFO"
                    ):
                        result = file_operations.open_file_in_default_app(
                            target.name
                        )

        self.assertTrue(result)
        startfile.assert_called_once_with(target.name)

    def test_macos_uses_open_command(self):
        with tempfile.NamedTemporaryFile() as target:
            with patch.object(file_operations.sys, "platform", "darwin"):
                with patch.object(file_operations.os, "system", return_value=0) as system:
                    result = file_operations.open_file_in_default_app(target.name)

        self.assertTrue(result)
        system.assert_called_once_with("open " + target.name)

    def test_linux_uses_xdg_open_command(self):
        with tempfile.NamedTemporaryFile() as target:
            with patch.object(file_operations.sys, "platform", "linux"):
                with patch.object(file_operations.os, "system", return_value=0) as system:
                    result = file_operations.open_file_in_default_app(target.name)

        self.assertTrue(result)
        system.assert_called_once_with("xdg-open " + target.name)

    def test_missing_file_shows_warning_and_returns_false(self):
        with patch.object(file_operations.os.path, "exists", return_value=False):
            with patch.object(file_operations.messagebox, "showwarning") as warning:
                with self.assertLogs(
                    "module.single.file_operations.file_operations",
                    level="WARNING"
                ):
                    result = file_operations.open_file_in_default_app(
                        "missing-file.json"
                    )

        self.assertFalse(result)
        warning.assert_called_once()
        self.assertEqual(warning.call_args[0][0], "ファイルが見つかりません")

    def test_os_open_failure_shows_error_logs_and_returns_false(self):
        with tempfile.NamedTemporaryFile() as target:
            with patch.object(file_operations.sys, "platform", "win32"):
                with patch.object(
                    file_operations.os, "startfile", create=True,
                    side_effect=OSError("application unavailable")
                ):
                    with patch.object(file_operations.messagebox, "showerror") as error:
                        with self.assertLogs(
                            "module.single.file_operations.file_operations",
                            level="ERROR"
                        ) as captured:
                            result = file_operations.open_file_in_default_app(
                                target.name
                            )

        self.assertFalse(result)
        error.assert_called_once()
        self.assertEqual(error.call_args[0][0], "ファイルオープンエラー")
        self.assertTrue(any("オープンエラー" in message for message in captured.output))


if __name__ == "__main__":
    unittest.main()
