"""Tests for the JSON persistence utility."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from module.single.json_data_handler import json_data_handler


class SaveJsonToFileTests(unittest.TestCase):
    def test_saves_dictionary_as_formatted_utf8_json(self):
        data = {"title": "日本語", "count": 3}

        with tempfile.TemporaryDirectory() as output_dir:
            result = json_data_handler.save_json_to_file(
                data, "result.json", output_dir
            )

            self.assertTrue(result)
            path = os.path.join(output_dir, "result.json")
            with open(path, "r", encoding="utf-8") as saved_file:
                content = saved_file.read()

        self.assertEqual(json.loads(content), data)
        self.assertIn('"title": "日本語"', content)
        self.assertNotIn("\\u65e5", content)
        self.assertIn('    "title":', content)

    def test_saves_list_data(self):
        data = [{"video_id": "abc123"}, {"video_id": "xyz789"}]

        with tempfile.TemporaryDirectory() as output_dir:
            result = json_data_handler.save_json_to_file(
                data, "videos.json", output_dir
            )
            with open(os.path.join(output_dir, "videos.json"), "r",
                      encoding="utf-8") as saved_file:
                saved_data = json.load(saved_file)

        self.assertTrue(result)
        self.assertEqual(saved_data, data)

    def test_creates_missing_output_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = os.path.join(temp_dir, "nested", "results")

            result = json_data_handler.save_json_to_file(
                {"ok": True}, "result.json", output_dir
            )

            self.assertTrue(result)
            self.assertTrue(os.path.isdir(output_dir))
            self.assertTrue(os.path.isfile(os.path.join(output_dir, "result.json")))

    def test_uses_script_directory_when_output_directory_is_omitted(self):
        with tempfile.TemporaryDirectory() as script_dir:
            script_path = os.path.join(script_dir, "main.py")
            target_path = os.path.join(script_dir, "result.json")

            with patch.object(json_data_handler.sys, "argv", [script_path]):
                result = json_data_handler.save_json_to_file(
                    {"source": "script-directory"}, "result.json"
                )

            self.assertTrue(result)
            with open(target_path, "r", encoding="utf-8") as saved_file:
                self.assertEqual(
                    json.load(saved_file), {"source": "script-directory"}
                )

    def test_directory_creation_failure_returns_false_and_logs_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = os.path.join(temp_dir, "unavailable")
            with patch.object(json_data_handler.os.path, "exists", return_value=False):
                with patch.object(
                    json_data_handler.os, "makedirs",
                    side_effect=OSError("permission denied")
                ):
                    with self.assertLogs(
                        "module.single.json_data_handler.json_data_handler",
                        level="ERROR"
                    ) as captured:
                        result = json_data_handler.save_json_to_file(
                            {"ok": True}, "result.json", output_dir
                        )

        self.assertFalse(result)
        self.assertTrue(any("ディレクトリ" in message for message in captured.output))

    def test_file_write_failure_returns_false_and_logs_error(self):
        with tempfile.TemporaryDirectory() as output_dir:
            with patch(
                "builtins.open", side_effect=IOError("disk full")
            ):
                with self.assertLogs(
                    "module.single.json_data_handler.json_data_handler",
                    level="ERROR"
                ) as captured:
                    result = json_data_handler.save_json_to_file(
                        {"ok": True}, "result.json", output_dir
                    )

        self.assertFalse(result)
        self.assertTrue(any("保存中にエラー" in message for message in captured.output))


if __name__ == "__main__":
    unittest.main()
