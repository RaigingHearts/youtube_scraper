"""
Tkinterアプリケーションのユーザー設定やアプリケーション固有の設定を管理するモジュールスクリプト。
特にAPIキーなどの設定の入力・保存・読み込みをGUIを介して行う機能を提供する。
Tkinterアプリケーション特化 / モジュールタイプ：管理モジュール

利用したいPythonスクリプトへインポートして利用可能:
"import tk_app_settings"

メソッド構成:
├── "APIキーが存在しない場合にTkinterダイアログで入力を促し、安全に保存する"
│   └── "def check_and_prompt_api_key(master_root, current_api_key=None):"
├── "APIキーを入力するためのTkinterダイアログを表示し、保存する"
│   └── "def _prompt_for_api_key(master_root):"
コピペ編集用罫線 '━┃┏┓┛┗┣┳┫┻╋' '─│┌┐┘└├┬┤┴┼'
"""
# tk_app_settings.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog
# settings_managerモジュールをインポート
from module.manager.secure_settings import settings_manager
# 標準 logging を利用
import logging

logger = logging.getLogger(__name__)

def check_and_prompt_api_key(master_root: tk.Tk, current_api_key: str | None = None) -> str | None:
    """
    APIキーが存在しない場合、または復号化に失敗した場合にTkinterダイアログで入力を促し、安全に保存する。
    この関数はAPIキーの取得のみを行い、アプリケーションの終了判断は呼び出し元に任せる。
    
    Args:
        master_root (tk.Tk): Tkinterのルートウィンドウオブジェクト。
        current_api_key (str | None): 現在のAPIキー（もしあれば）。

    Returns:
        str | None: 取得または設定されたAPIキー。キャンセルされた場合はNone。
    """
    api_key = current_api_key
    settings = settings_manager.load_settings()

    if settings.get("api_key"):
        decrypted_key = settings_manager.decrypt_api_key(settings["api_key"])
        if decrypted_key:
            api_key = decrypted_key
            logger.info("保存されたAPIキーをロードしました。")
        else:
            messagebox.showerror("APIキーエラー", "APIキーの復号化に失敗しました。再入力してください。")
            api_key = _prompt_for_api_key(master_root)
    else:
        api_key = _prompt_for_api_key(master_root)
    
    if api_key:
        logger.info("APIキーが正常に設定されました。")
    else:
        logger.warning("APIキーが入力されませんでした。")
        # ここでmaster_root.destroy()を呼び出すと、main.py側のdestroyと重複してエラーになるため削除
    
    return api_key

def _prompt_for_api_key(master_root: tk.Tk) -> str | None:
    """
    APIキーを入力するためのTkinterダイアログを表示し、入力されたキーを安全に保存する。

    Args:
        master_root (tk.Tk): Tkinterのルートウィンドウオブジェクト。

    Returns:
        str | None: 入力されたAPIキー。キャンセルされた場合はNone。
    """
    api_key_dialog = simpledialog.askstring("APIキー入力", "YouTube Data APIキーを入力してください:", show='*', parent=master_root)
    if api_key_dialog:
        encrypted_key = settings_manager.encrypt_api_key(api_key_dialog)
        if encrypted_key:
            settings_manager.save_settings({"api_key": encrypted_key})
            messagebox.showinfo("APIキー保存", "APIキーが安全に保存されました。", parent=master_root)
            logger.info("新しいAPIキーが入力され、保存されました。")
            return api_key_dialog
        else:
            messagebox.showerror("APIキー保存エラー", "APIキーの暗号化に失敗しました。保存できませんでした。", parent=master_root)
            logger.error("APIキーの暗号化失敗により保存できませんでした。")
            return None
    else:
        messagebox.showwarning("APIキーなし", "APIキーが入力されていません。機能が制限されます。", parent=master_root)
        logger.warning("APIキーの入力がキャンセルされました。")
        return None

# コピペ用メソッドコードの例 (使用例として)
"""
# モジュールのインポート設定
import tk_app_settings

class YourApplication:
    def __init__(self, master):
        self.master = master
        self.api_key = None
        self._initialize_api_key()

    def _initialize_api_key(self):
        # アプリケーション起動時にAPIキーを確認・プロンプト
        self.api_key = tk_app_settings.check_and_prompt_api_key(self.master)
        if not self.api_key:
            # APIキーが取得できなかった場合、アプリケーションを終了するなど適切な処理を行う
            print("APIキーが設定されていないため、アプリケーションを終了します。")
            # self.master.destroy() # アプリケーションを終了する場合
"""
