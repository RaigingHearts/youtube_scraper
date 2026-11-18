"""アプリケーション全体の標準 logging 設定を管理する。"""
import logging

LOG_FILE = "trace.log"
_LOG_HANDLER_MARKER = "_youtube_scraper_managed_handler"


def configure_logging(log_file=LOG_FILE, level=logging.INFO):
    """アプリケーション共通のログ出力先と書式を設定する。

    モジュールのインポート時にはファイルを開かず、起動処理から明示的に呼び出す。
    複数回呼び出しても、このモジュールが追加した FileHandler は重複登録しない。
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers:
        if getattr(handler, _LOG_HANDLER_MARKER, False):
            return handler

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    setattr(file_handler, _LOG_HANDLER_MARKER, True)
    root_logger.addHandler(file_handler)
    return file_handler
