"""
Tkinterアプリケーション内でユーザーにメッセージや通知を一貫した方法で表示するためのモジュールスクリプト。
情報メッセージ、警告、エラー、確認ダイアログなど、様々な種類のメッセージに対応する。
Tkinterアプリケーション特化 / モジュールタイプ：ユーティリティモジュール

利用したいPythonスクリプトへインポートして利用可能:
"import tk_notifications"

メソッド構成:
├── "情報メッセージボックスを表示する"
│   └── "def show_info(title, message, parent=None):"
├── "警告メッセージボックスを表示する"
│   └── "def show_warning(title, message, parent=None):"
├── "エラーメッセージボックスを表示する"
│   └── "def show_error(title, message, parent=None):"
├── "はい/いいえの確認ダイアログを表示する"
│   └── "def ask_yes_no(title, message, parent=None):"
├── "文字列入力ダイアログを表示する"
│   └── "def ask_string(title, prompt, initialvalue=None, show='*', parent=None):"
├── "カスタムファイル選択ダイアログを表示し、選択されたファイルパスを返す"
│   └── "def show_file_selection_dialog(master_root, title, options):"
コピペ編集用罫線 '━┃┏┓┛┗┣┳┫┻╋' '─│┌┐┘└├┬┤┴┼'
"""
# tk_notifications.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import List, Tuple, Any, Optional
import sys

# ログ出力のためにlogger_configをインポート
from module.utility.logger_config import logger_config

def show_info(title: str, message: str, parent: Optional[tk.Tk | tk.Toplevel] = None):
    """
    情報メッセージボックスを表示する。

    Args:
        title (str): ダイアログのタイトル。
        message (str): 表示するメッセージ。
        parent (Optional[tk.Tk | tk.Toplevel]): 親ウィンドウ。
    """
    logger_config.log_message('info', f"GUI情報メッセージ: {title} - {message}")
    messagebox.showinfo(title, message, parent=parent)

def show_warning(title: str, message: str, parent: Optional[tk.Tk | tk.Toplevel] = None):
    """
    警告メッセージボックスを表示する。

    Args:
        title (str): ダイアログのタイトル。
        message (str): 表示するメッセージ。
        parent (Optional[tk.Tk | tk.Toplevel]): 親ウィンドウ。
    """
    logger_config.log_message('warning', f"GUI警告メッセージ: {title} - {message}")
    messagebox.showwarning(title, message, parent=parent)

def show_error(title: str, message: str, parent: Optional[tk.Tk | tk.Toplevel] = None):
    """
    エラーメッセージボックスを表示する。

    Args:
        title (str): ダイアログのタイトル。
        message (str): 表示するメッセージ。
        parent (Optional[tk.Tk | tk.Toplevel]): 親ウィンドウ。
    """
    logger_config.log_message('error', f"GUIエラーメッセージ: {title} - {message}")
    messagebox.showerror(title, message, parent=parent)

def ask_yes_no(title: str, message: str, parent: Optional[tk.Tk | tk.Toplevel] = None) -> bool:
    """
    はい/いいえの確認ダイアログを表示する。

    Args:
        title (str): ダイアログのタイトル。
        message (str): 表示するメッセージ。
        parent (Optional[tk.Tk | tk.Toplevel]): 親ウィンドウ。

    Returns:
        bool: ユーザーが「はい」を選択した場合はTrue、それ以外はFalse。
    """
    logger_config.log_message('info', f"GUI確認ダイアログ: {title} - {message}")
    return messagebox.askyesno(title, message, parent=parent)

def ask_string(title: str, prompt: str, initialvalue: Optional[str] = None, show: str = '*', parent: Optional[tk.Tk | tk.Toplevel] = None) -> Optional[str]:
    """
    文字列入力ダイアログを表示する。

    Args:
        title (str): ダイアログのタイトル。
        prompt (str): 入力を促すメッセージ。
        initialvalue (Optional[str]): 初期表示される値。
        show (str): 入力文字の表示形式（例: '*' でパスワード表示）。
        parent (Optional[tk.Tk | tk.Toplevel]): 親ウィンドウ。

    Returns:
        Optional[str]: 入力された文字列。キャンセルされた場合はNone。
    """
    logger_config.log_message('info', f"GUI文字列入力ダイアログ: {title} - {prompt}")
    return simpledialog.askstring(title, prompt, initialvalue=initialvalue, show=show, parent=parent)

def show_file_selection_dialog(master_root: tk.Tk, title: str, options: List[Tuple[str, str]]) -> Optional[str]:
    """
    複数のファイルパスから一つを選択させるカスタムダイアログを表示する。

    Args:
        master_root (tk.Tk): Tkinterのルートウィンドウオブジェクト。
        title (str): ダイアログのタイトル。
        options (List[Tuple[str, str]]): (表示ラベル, ファイルパス) のタプルのリスト。

    Returns:
        Optional[str]: 選択されたファイルのパス。キャンセルされた場合はNone。
    """
    logger_config.log_message('info', f"GUIファイル選択ダイアログ表示: {title}")

    if not options:
        show_warning("ファイルが見つかりません", "開くべきファイルが指定されていません。", parent=master_root)
        logger_config.log_message('warning', "ファイル選択ダイアログにオプションが提供されませんでした。")
        return None

    # 選択肢が一つだけなら直接開く
    if len(options) == 1:
        label, path = options[0]
        show_info("ファイルを開く", f"{label} ({os.path.basename(path)}) を開きます。", parent=master_root)
        return path

    # 複数の選択肢がある場合、カスタムダイアログで選択させる
    choice_window = tk.Toplevel(master_root)
    choice_window.title(title)
    choice_window.geometry("400x200")
    choice_window.transient(master_root) # 親ウィンドウの上に表示
    choice_window.grab_set() # 親ウィンドウの操作をロック

    tk.Label(choice_window, text="開きたいファイルを選択してください:").pack(pady=10)

    selected_path = tk.StringVar(choice_window)
    # 最初のオプションをデフォルト選択
    if options:
        selected_path.set(options[0][1])

    for label, path in options:
        # ファイル名のみを表示してパスが長くなりすぎないようにする
        display_text = f"{label} ({os.path.basename(path)})"
        tk.Radiobutton(choice_window, text=display_text, variable=selected_path, value=path).pack(anchor="w", padx=20)

    result_path = None
    def on_open():
        nonlocal result_path
        result_path = selected_path.get()
        choice_window.destroy()

    tk.Button(choice_window, text="開く", command=on_open).pack(pady=10)
    
    # ウィンドウが閉じるまで待機
    master_root.wait_window(choice_window) 
    
    logger_config.log_message('info', f"ファイル選択ダイアログで '{result_path}' が選択されました。")
    return result_path

# コピペ用メソッドコードの例 (使用例として)
"""
# モジュールのインポート設定
import tk_notifications
import tkinter as tk
from tkinter import ttk

class YourApplication:
    def __init__(self, master):
        self.master = master
        master.title("通知テストアプリ")
        
        ttk.Button(master, text="情報表示", command=self._show_info_example).pack(pady=5)
        ttk.Button(master, text="警告表示", command=self._show_warning_example).pack(pady=5)
        ttk.Button(master, text="エラー表示", command=self._show_error_example).pack(pady=5)
        ttk.Button(master, text="確認ダイアログ", command=self._ask_yes_no_example).pack(pady=5)
        ttk.Button(master, text="文字列入力", command=self._ask_string_example).pack(pady=5)
        ttk.Button(master, text="ファイル選択ダイアログ", command=self._show_file_selection_example).pack(pady=5)

    def _show_info_example(self):
        tk_notifications.show_info("情報", "これは情報メッセージです。", parent=self.master)

    def _show_warning_example(self):
        tk_notifications.show_warning("警告", "これは警告メッセージです。", parent=self.master)

    def _show_error_example(self):
        tk_notifications.show_error("エラー", "これはエラーメッセージです。", parent=self.master)

    def _ask_yes_no_example(self):
        if tk_notifications.ask_yes_no("確認", "続行しますか？", parent=self.master):
            print("ユーザーは「はい」を選択しました。")
        else:
            print("ユーザーは「いいえ」を選択しました。")

    def _ask_string_example(self):
        user_input = tk_notifications.ask_string("入力", "何か入力してください:", initialvalue="デフォルト値", parent=self.master)
        if user_input is not None:
            print(f"入力された文字列: {user_input}")
        else:
            print("入力がキャンセルされました。")

    def _show_file_selection_example(self):
        import os
        # 仮のファイルパスリスト
        options = [
            ("ファイルA", os.path.join(os.getcwd(), "test_file_a.txt")),
            ("ファイルB (ログ)", os.path.join(os.getcwd(), "logs", "app.log")),
            ("ファイルC (設定)", os.path.join(os.getcwd(), "config", "settings.json")),
        ]
        
        # 存在しないファイルはオプションから除外するなどのロジックを呼び出し元で実装することが推奨
        # 例: options = [(label, path) for label, path in options if os.path.exists(path)]

        selected_file = tk_notifications.show_file_selection_dialog(self.master, "ファイルを選択", options)
        if selected_file:
            print(f"選択されたファイル: {selected_file}")
        else:
            print("ファイル選択がキャンセルされました。")

if __name__ == "__main__":
    root = tk.Tk()
    app = YourApplication(root)
    root.mainloop()
"""
