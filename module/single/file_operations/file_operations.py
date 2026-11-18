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
import logging
import os
import sys
import tkinter as tk
from tkinter import messagebox

logger = logging.getLogger(__name__)

def open_file_in_default_app(filepath: str) -> bool:
    """
    指定されたファイルをOSのデフォルトアプリケーションで開く。

    Args:
        filepath (str): 開くファイルの絶対パスまたは相対パス。

    Returns:
        bool: ファイルを開く処理が成功した場合はTrue、失敗した場合はFalse。
    """

    if os.path.exists(filepath):
        try:
            if sys.platform == "win32":
                os.startfile(filepath) # Windowsの場合
            elif sys.platform == "darwin":
                os.system(f"open {filepath}") # macOSの場合
            else:
                os.system(f"xdg-open {filepath}") # Linuxの場合
            logger.info(f"ファイル '{filepath}' をデフォルトアプリケーションで開きました。")
            return True
        except Exception as e:
            messagebox.showerror("ファイルオープンエラー", f"ファイル '{filepath}' を開けませんでした:\n{e}")
            logger.error(f"ファイル '{filepath}' のオープンエラー: {e}")
            return False
    else:
        messagebox.showwarning("ファイルが見つかりません", f"ファイル '{filepath}' が見つかりませんでした。")
        logger.warning(f"ファイル '{filepath}' が見つかりません。")
        return False
