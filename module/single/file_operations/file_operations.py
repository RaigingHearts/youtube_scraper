"""
ファイルやディレクトリの基本的な操作を提供するモジュールスクリプト。
汎用性：最高 / モジュールタイプ：単体モジュール

利用したいPythonスクリプトへインポートして利用可能:
"import file_operations"

メソッド構成:
├── "指定されたファイルをOSの既定のアプリケーションで開くメソッド"
│   └── "def open_file_in_default_app(filepath):"
コピペ編集用罫線 '━┃┏┓┛┗┣┳┫┻╋' '─│┌┐┘└├┬┤┴┼'
"""
# file_operations.py # コピーペースト作業での識別用。除去しないこと
import os
import sys
import tkinter as tk
from tkinter import messagebox

# ログ出力のためにlogger_configをインポート（循環参照に注意が必要なため、関数内でインポート）
# from logger_config import log_message

def _get_logger_config_log_message():
    """
    logger_configモジュールのlog_message関数を動的に取得する。
    """
    try:
        if 'logger_config' in sys.modules:
            from module.utility.logger_config.logger_config import log_message
            return log_message
        else:
            print("Warning: logger_config not yet loaded when file_operations tried to log.", file=sys.stderr)
            return lambda level, message: print(f"[{level.upper()}] {message}", file=sys.stderr)
    except ImportError:
        return lambda level, message: print(f"[{level.upper()}] {message}", file=sys.stderr)


def open_file_in_default_app(filepath: str) -> bool:
    """
    指定されたファイルをOSのデフォルトアプリケーションで開く。

    Args:
        filepath (str): 開くファイルの絶対パスまたは相対パス。

    Returns:
        bool: ファイルを開く処理が成功した場合はTrue、失敗した場合はFalse。
    """
    log_message = _get_logger_config_log_message()
    if os.path.exists(filepath):
        try:
            if sys.platform == "win32":
                os.startfile(filepath) # Windowsの場合
            elif sys.platform == "darwin":
                os.system(f"open {filepath}") # macOSの場合
            else:
                os.system(f"xdg-open {filepath}") # Linuxの場合
            log_message('info', f"ファイル '{filepath}' をデフォルトアプリケーションで開きました。")
            return True
        except Exception as e:
            messagebox.showerror("ファイルオープンエラー", f"ファイル '{filepath}' を開けませんでした:\n{e}")
            log_message('error', f"ファイル '{filepath}' のオープンエラー: {e}")
            return False
    else:
        messagebox.showwarning("ファイルが見つかりません", f"ファイル '{filepath}' が見つかりませんでした。")
        log_message('warning', f"ファイル '{filepath}' が見つかりません。")
        return False
