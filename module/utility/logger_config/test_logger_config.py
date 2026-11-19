"""logger_config の初期化と出力を検証する。"""
import importlib
import logging
import os
import tempfile
import unittest

from module.utility.logger_config import logger_config


class LoggerConfigTests(unittest.TestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        os.chdir(self.temp_dir.name)
        self.root_logger = logging.getLogger()
        self.original_level = self.root_logger.level
        self.discovery_logger = logging.getLogger("googleapiclient.discovery")
        self.original_discovery_level = self.discovery_logger.level
        self._remove_managed_handlers()

    def tearDown(self):
        self._remove_managed_handlers()
        self.root_logger.setLevel(self.original_level)
        self.discovery_logger.setLevel(self.original_discovery_level)
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _remove_managed_handlers(self):
        for handler in list(self.root_logger.handlers):
            if getattr(handler, "_youtube_scraper_managed_handler", False):
                self.root_logger.removeHandler(handler)
                handler.close()

    def _managed_handlers(self):
        return [
            handler for handler in self.root_logger.handlers
            if getattr(handler, "_youtube_scraper_managed_handler", False)
        ]

    def test_import_does_not_create_log_file(self):
        importlib.reload(logger_config)
        self.assertFalse(os.path.exists(logger_config.LOG_FILE))

    def test_configure_logging_writes_and_is_idempotent(self):
        log_path = os.path.join(self.temp_dir.name, "application.log")
        first_handler = logger_config.configure_logging(log_path)
        second_handler = logger_config.configure_logging(log_path)

        self.assertIs(first_handler, second_handler)
        self.assertEqual(self._managed_handlers(), [first_handler])

        logging.getLogger("test.named.module").info("logging test message")
        first_handler.flush()

        with open(log_path, "r", encoding="utf-8") as log_file:
            contents = log_file.read()
        self.assertIn("INFO - logging test message", contents)

    def test_reconfiguration_changes_log_file(self):
        first_path = os.path.join(self.temp_dir.name, "first.log")
        second_path = os.path.join(self.temp_dir.name, "second.log")
        first_handler = logger_config.configure_logging(first_path)

        second_handler = logger_config.configure_logging(second_path)

        self.assertIsNot(first_handler, second_handler)
        self.assertTrue(first_handler.stream is None)
        self.assertEqual(second_handler.baseFilename, os.path.abspath(second_path))
        self.assertEqual(self._managed_handlers(), [second_handler])

        logging.getLogger("test.named.module").info("written to second file")
        second_handler.flush()

        with open(second_path, "r", encoding="utf-8") as log_file:
            contents = log_file.read()
        self.assertIn("INFO - written to second file", contents)
        self.assertFalse(os.path.exists(first_path) and os.path.getsize(first_path) > 0)

    def test_reconfiguration_updates_root_and_handler_levels(self):
        log_path = os.path.join(self.temp_dir.name, "levels.log")
        handler = logger_config.configure_logging(log_path, logging.INFO)

        same_handler = logger_config.configure_logging(log_path, logging.DEBUG)

        self.assertIs(handler, same_handler)
        self.assertEqual(self.root_logger.level, logging.DEBUG)
        self.assertEqual(handler.level, logging.DEBUG)
        self.assertEqual(self._managed_handlers(), [handler])

        logging.getLogger("test.named.module").debug("debug after reconfiguration")
        handler.flush()
        with open(log_path, "r", encoding="utf-8") as log_file:
            contents = log_file.read()
        self.assertIn("DEBUG - debug after reconfiguration", contents)

    def test_debug_mode_suppresses_google_api_url_but_keeps_application_debug(self):
        log_path = os.path.join(self.temp_dir.name, "debug.log")
        handler = logger_config.configure_logging(log_path, logging.DEBUG)

        self.assertEqual(self.root_logger.level, logging.DEBUG)
        self.assertEqual(self.discovery_logger.level, logging.INFO)

        self.discovery_logger.debug(
            "URL being requested: GET https://example.invalid/?key=secret-key"
            "&pageToken=secret-token"
        )
        logging.getLogger("module.application").debug("safe application diagnostic")
        handler.flush()

        with open(log_path, "r", encoding="utf-8") as log_file:
            contents = log_file.read()
        self.assertNotIn("URL being requested", contents)
        self.assertNotIn("secret-key", contents)
        self.assertNotIn("secret-token", contents)
        self.assertIn("DEBUG - safe application diagnostic", contents)

    def test_reconfiguration_with_invalid_path_preserves_existing_handler(self):
        valid_path = os.path.join(self.temp_dir.name, "valid.log")
        handler = logger_config.configure_logging(valid_path, logging.INFO)
        invalid_path = os.path.join(self.temp_dir.name, "missing", "invalid.log")

        with self.assertRaises(OSError):
            logger_config.configure_logging(invalid_path, logging.DEBUG)

        self.assertEqual(self._managed_handlers(), [handler])
        self.assertEqual(self.root_logger.level, logging.INFO)
        self.assertEqual(handler.level, logging.INFO)
        logging.getLogger("test.named.module").info("still using original handler")
        handler.flush()
        with open(valid_path, "r", encoding="utf-8") as log_file:
            self.assertIn("still using original handler", log_file.read())


if __name__ == "__main__":
    unittest.main()
