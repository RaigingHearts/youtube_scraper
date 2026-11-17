"""
Pythonアプリケーションのロギング機能を管理するモジュールスクリプト。
アプリケーションの実行状況を記録し、コンソール出力とファイル出力の両方に対応する。
汎用性：最高 / モジュールタイプ：ユーティリティモジュール

利用したいPythonスクリプトへインポートして利用可能:
"import logger_config"

メソッド構成:
├── "指定されたレベルでメッセージをログに記録"
│   └── "def log_message(level, message):"
├── "ログファイルの内容を別ウィンドウに表示"
│   └── "def show_log_window():"
コピペ編集用罫線 '━┃┏┓┛┗┣┳┫┻╋' '─│┌┐┘└├┬┤┴┼'
"""
# logger_config.py # コピーペースト作業での識別用。除去しないこと
import logging
import os
import tkinter as tk
from datetime import datetime
from tkinter.scrolledtext import ScrolledText

# このモジュールスクリプトで利用するログ出力用のファイル名
# アプリケーション固有のファイル名命名規則に従い、プレフィックスを推奨
# 例: "your_app_name-trace.log"
LOG_FILE = "trace.log" 

# ロガーの設定
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # デフォルトのログレベルをINFOに設定

# ファイルハンドラ
# ログファイルのパスは、メインスクリプトと同じフォルダを基準とする
file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
file_handler.setLevel(logging.INFO) # ファイル出力のログレベルをINFOに設定

# フォーマッタ
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

# ハンドラを追加
# 同じハンドラが複数回追加されないようにチェック
if not logger.handlers:
    logger.addHandler(file_handler)
    # コンソールにも出力する場合（デバッグ用）
    # console_handler = logging.StreamHandler()
    # console_handler.setFormatter(formatter)
    # logger.addHandler(console_handler)

def log_message(level: str, message: str):
    """
    指定されたレベルでメッセージをログに記録する。

    Args:
        level (str): ログレベル ('info', 'warning', 'error', 'critical', 'debug')
        message (str): ログに記録するメッセージ
    """
    if level == 'info':
        logger.info(message)
    elif level == 'warning':
        logger.warning(message)
    elif level == 'error':
        logger.error(message)
    elif level == 'critical':
        logger.critical(message)
    else:
        logger.debug(message) # デフォルトはdebug

def show_log_window():
    """
    ログファイルの内容を別ウィンドウに表示する。
    これはTkinterアプリケーション特化の機能であり、GUIアプリケーションでのみ利用されることを想定。
    """
    log_window = tk.Toplevel()
    log_window.title("ログ表示")
    log_window.geometry("800x600")

    text_area = ScrolledText(log_window, wrap=tk.WORD, width=100, height=30)
    text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    def load_log_content():
        """ログファイルの内容を読み込み、テキストエリアに表示する。"""
        text_area.delete('1.0', tk.END) # 既存の内容をクリア
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, 'r', encoding='utf-8') as f:
                    content = f.read()
                    text_area.insert(tk.END, content)
                text_area.see(tk.END) # 最下部までスクロール
            except IOError as e:
                text_area.insert(tk.END, f"ログファイルの読み込み中にエラーが発生しました: {e}")
                log_message('error', f"ログファイル '{LOG_FILE}' の読み込みエラー: {e}")
        else:
            text_area.insert(tk.END, "ログファイルはまだ存在しません。")
            log_message('info', f"ログファイル '{LOG_FILE}' が見つかりません。")

    load_log_content()

    # 「最新のログを読み込む」ボタン
    refresh_button = tk.Button(log_window, text="最新のログを読み込む", command=load_log_content)
    refresh_button.pack(pady=5)

    # ウィンドウが閉じられたときにTkinterのメインループに影響を与えないようにする
    log_window.protocol("WM_DELETE_WINDOW", log_window.destroy) 
    log_window.mainloop() # Toplevelウィンドウの独自のmainloopは避けるべきだが、簡易表示のため使用
