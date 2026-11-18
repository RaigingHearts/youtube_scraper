"""Tkinterを利用したログ閲覧ウィンドウ。"""
import logging
import os
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

from module.utility.logger_config.logger_config import LOG_FILE

logger = logging.getLogger(__name__)


def show_log_window(parent=None):
    """ログファイルの内容を別ウィンドウに表示する。"""
    log_window = tk.Toplevel(parent) if parent is not None else tk.Toplevel()
    log_window.title("ログ表示")
    log_window.geometry("800x600")

    text_area = ScrolledText(log_window, wrap=tk.WORD, width=100, height=30)
    text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    def load_log_content():
        """ログファイルの内容を読み込み、テキストエリアに表示する。"""
        text_area.delete("1.0", tk.END)
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as log_file:
                    text_area.insert(tk.END, log_file.read())
                text_area.see(tk.END)
            except OSError as error:
                text_area.insert(
                    tk.END, "ログファイルの読み込み中にエラーが発生しました: {}".format(error)
                )
                logger.exception("ログファイル '%s' の読み込みに失敗しました。", LOG_FILE)
        else:
            text_area.insert(tk.END, "ログファイルはまだ存在しません。")

    load_log_content()

    refresh_button = tk.Button(
        log_window, text="最新のログを読み込む", command=load_log_content
    )
    refresh_button.pack(pady=5)
    log_window.protocol("WM_DELETE_WINDOW", log_window.destroy)
    return log_window
