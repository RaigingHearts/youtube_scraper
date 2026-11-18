"""
JSONデータの整形とJSONファイルへの保存を行うモジュールスクリプト。
汎用性：最高 / モジュールタイプ：単体モジュール

利用したいPythonスクリプトへインポートして利用可能:
"import json_data_handler"

メソッド構成:
├── "JSONデータを整形してJSONファイルに保存するメソッド"
│   └── "def save_json_to_file(data, filename, output_dir=None):"
コピペ編集用罫線 '━┃┏┓┛┗┣┳┫┻╋' '─│┌┐┘└├┬┤┴┼'
"""
# json_data_handler.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import json
import logging
import os
import sys
# import tkinter as tk # 不要なインポートを削除
# from tkinter import messagebox # 不要なインポートを削除

logger = logging.getLogger(__name__)

def save_json_to_file(data: dict | list, filename: str, output_dir: str = None) -> bool: # type:ignore
    """
    データを整形してJSONファイルに保存する。
    出力先ディレクトリを指定しない場合、メインスクリプトと同じフォルダを基準とする。
    指定されたディレクトリが存在しない場合は作成を試みる。

    Args:
        data (dict | list): 保存するJSONデータ（辞書またはリスト）。
        filename (str): 保存するファイル名。
        output_dir (str, optional): 出力先のディレクトリパス。Noneの場合、実行スクリプトのディレクトリ。

    Returns:
        bool: ファイルの保存が成功した場合はTrue、失敗した場合はFalse。
    """

    if output_dir:
        # 指定された出力ディレクトリが存在しない場合、作成を試みる
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                logger.info(f"出力ディレクトリ '{output_dir}' を作成しました。")
            except OSError as e:
                # messagebox.showerror("ディレクトリ作成エラー", f"ディレクトリ '{output_dir}' の作成中にエラーが発生しました:\n{e}") # Tkinter依存の処理を削除
                logger.error(f"ディレクトリ '{output_dir}' の作成中にエラーが発生しました: {e}")
                return False
        file_path = os.path.join(output_dir, filename)
    else:
        # output_dirが指定されない場合、実行スクリプトのディレクトリを基準とする
        current_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        file_path = os.path.join(current_dir, filename)

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info(f"JSONデータが '{file_path}' に保存されました。")
        return True
    except IOError as e:
        # messagebox.showerror("ファイルの保存エラー", f"ファイル '{filename}' の保存中にエラーが発生しました:\n{e}") # Tkinter依存の処理を削除
        logger.error(f"ファイル '{filename}' の保存中にエラーが発生しました: {e}")
        return False
