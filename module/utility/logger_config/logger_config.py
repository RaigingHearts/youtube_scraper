"""アプリケーション全体の標準 logging 設定を管理する。"""
import logging
import os

LOG_FILE = "trace.log"
_LOG_HANDLER_MARKER = "_youtube_scraper_managed_handler"


def configure_logging(log_file=LOG_FILE, level=logging.INFO):
    """アプリケーション共通のログ出力先と書式を設定する。

    モジュールのインポート時にはファイルを開かず、起動処理から明示的に呼び出す。
    複数回呼び出された場合も、このモジュールが管理する FileHandler は
    1つだけ維持し、出力先とログレベルを最新の指定に合わせる。
    """
    root_logger = logging.getLogger()
    managed_handlers = [
        handler for handler in root_logger.handlers
        if getattr(handler, _LOG_HANDLER_MARKER, False)
    ]

    target_path = os.path.normcase(os.path.abspath(os.fspath(log_file)))

    # 同じ出力先なら既存ハンドラーを再利用し、レベルだけ同期する。
    matching_handler = next(
        (
            handler for handler in managed_handlers
            if os.path.normcase(os.path.abspath(handler.baseFilename))
            == target_path
        ),
        None,
    )

    if matching_handler is not None:
        matching_handler.setLevel(level)
        for handler in managed_handlers:
            if handler is matching_handler:
                continue
            root_logger.removeHandler(handler)
            handler.close()
        root_logger.setLevel(level)
        return matching_handler

    # 新しいハンドラーの作成に失敗した場合、既存の出力先を維持できるよう、
    # 既存ハンドラーを取り外す前に新しいファイルを開く。
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    setattr(file_handler, _LOG_HANDLER_MARKER, True)

    for handler in managed_handlers:
        root_logger.removeHandler(handler)
        handler.close()

    root_logger.addHandler(file_handler)
    root_logger.setLevel(level)
    return file_handler
