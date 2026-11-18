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
        self._remove_managed_handlers()

    def tearDown(self):
        self._remove_managed_handlers()
        self.root_logger.setLevel(self.original_level)
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _remove_managed_handlers(self):
        for handler in list(self.root_logger.handlers):
            if getattr(handler, "_youtube_scraper_managed_handler", False):
                self.root_logger.removeHandler(handler)
                handler.close()

    def test_import_does_not_create_log_file(self):
        importlib.reload(logger_config)
        self.assertFalse(os.path.exists(logger_config.LOG_FILE))

    def test_configure_logging_writes_and_is_idempotent(self):
        log_path = os.path.join(self.temp_dir.name, "application.log")
        first_handler = logger_config.configure_logging(log_path)
        second_handler = logger_config.configure_logging(log_path)

        managed_handlers = [
            handler for handler in self.root_logger.handlers
            if getattr(handler, "_youtube_scraper_managed_handler", False)
        ]
        self.assertIs(first_handler, second_handler)
        self.assertEqual(len(managed_handlers), 1)

        logging.getLogger("test.named.module").info("logging test message")
        first_handler.flush()

        with open(log_path, "r", encoding="utf-8") as log_file:
            contents = log_file.read()
        self.assertIn("INFO - logging test message", contents)


if __name__ == "__main__":
    unittest.main()
