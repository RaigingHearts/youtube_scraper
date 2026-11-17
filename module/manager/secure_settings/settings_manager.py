"""
Pythonスクリプトプログラム内で利用する設定項目を管理するモジュールスクリプト。
APIキーなどの機密性の高い設定情報を安全に管理・取得する。
汎用性：最高 / モジュールタイプ：管理モジュール

設定ファイルを利用するPythonスクリプトに流用可能:
"import settings_manager"

メソッド構成:
├── "暗号化キーを生成し、ファイルに保存する。"
│   └── "def generate_key():"
├── "暗号化キーをファイルから読み込む。存在しない場合は生成する。"
│   └── "def load_key():"
├── "Fernetオブジェクトを返す。"
│   └── "def get_fernet():"
├── "設定をJSONファイルに保存する。"
│   └── "def save_settings(settings):"
├── "設定をJSONファイルから読み込む。"
│   └── "def load_settings():"
├── "APIキーを暗号化する。"
│   └── "def encrypt_api_key(api_key):"
├── "暗号化されたAPIキーを復号化する。"
│   └── "def decrypt_api_key(encrypted_api_key):"
コピペ編集用罫線 '━┃┏┓┛┗┣┳┫┻╋' '─│┌┐┘└├┬┤┴┼'
"""
# settings_manager.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import json
import os
import sys

# 文字列の暗号化･復号化を制御するライブラリ"pip install cryptography"で導入してから利用すべし。
# workspacedata.txtのpip listにcryptographyが含まれていることを確認済み
from cryptography.fernet import Fernet

# このモジュールで管理される設定ファイル名
# アプリケーション固有のファイル名命名規則に従い、混同を避ける
APP_NAME_PREFIX = "youtube_scraper" # アプリケーションの名称を定義 (例: "your_app_name")
SETTINGS_FILE = f"{APP_NAME_PREFIX}-settings.json"
# この管理モジュール用の平文文字列暗号化キーファイル名
ENCRYPTION_KEY_FILE = f"{APP_NAME_PREFIX}-encryption_key.key"

# ログ出力のためにlogger_configをインポート（循環参照に注意が必要なため、関数内でインポート）
# from logger_config import log_message 

def _get_logger_config_log_message():
    """
    logger_configモジュールのlog_message関数を動的に取得する。
    これにより、settings_managerとlogger_config間の循環参照を避ける。
    """
    try:
        # モジュールが既にロードされているか確認
        if 'logger_config' in sys.modules:
            from module.utility.logger_config.logger_config import log_message
            return log_message
        else:
            # モジュールがまだロードされていない場合（通常はmain.pyで先にロードされる）
            # ここではエラーログを出力できないため、標準エラーに直接出力
            print("Warning: logger_config not yet loaded when settings_manager tried to log.", file=sys.stderr)
            return lambda level, message: print(f"[{level.upper()}] {message}", file=sys.stderr)
    except ImportError:
        return lambda level, message: print(f"[{level.upper()}] {message}", file=sys.stderr)


def generate_key() -> bytes:
    """
    暗号化キーを生成し、ファイルに保存する。
    このキーファイルはGitリポジトリから除外されるべき。
    """
    log_message = _get_logger_config_log_message()
    key = Fernet.generate_key()
    try:
        with open(ENCRYPTION_KEY_FILE, "wb") as key_file:
            key_file.write(key)
        log_message('info', f"新しい暗号化キーが '{ENCRYPTION_KEY_FILE}' に生成・保存されました。")
        log_message('warning', f"'{ENCRYPTION_KEY_FILE}' は機密情報です。Gitリポジトリの追跡から除外してください。")
    except IOError as e:
        log_message('error', f"暗号化キーの保存中にエラーが発生しました: {e}")
    return key

def load_key() -> bytes:
    """
    暗号化キーをファイルから読み込む。存在しない場合は生成する。
    """
    log_message = _get_logger_config_log_message()
    if os.path.exists(ENCRYPTION_KEY_FILE):
        try:
            with open(ENCRYPTION_KEY_FILE, "rb") as key_file:
                key = key_file.read()
            log_message('info', f"暗号化キーが '{ENCRYPTION_KEY_FILE}' から読み込まれました。")
            return key
        except IOError as e:
            log_message('error', f"暗号化キーの読み込み中にエラーが発生しました: {e}")
            # エラー発生時は新しいキーを生成して続行
            return generate_key()
    else:
        log_message('info', f"暗号化キーファイル '{ENCRYPTION_KEY_FILE}' が見つかりません。新しいキーを生成します。")
        return generate_key()

def get_fernet() -> Fernet:
    """
    Fernetオブジェクトを返す。
    """
    key = load_key()
    return Fernet(key)

def save_settings(settings: dict):
    """
    設定をJSONファイルに保存する。
    設定ファイルはメインスクリプトと同じフォルダ、または専用フォルダに配置される。
    """
    log_message = _get_logger_config_log_message()
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        log_message('info', f"設定が '{SETTINGS_FILE}' に保存されました。")
    except IOError as e:
        log_message('error', f"設定ファイルの保存中にエラーが発生しました: {e}")

def load_settings() -> dict:
    """
    設定をJSONファイルから読み込む。ファイルが存在しない場合はデフォルト設定を返す。
    """
    log_message = _get_logger_config_log_message()
    if not os.path.exists(SETTINGS_FILE):
        log_message('warning', f"設定ファイル '{SETTINGS_FILE}' が見つかりません。デフォルト設定をロードします。")
        return {"api_key": None} # デフォルト設定
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
            log_message('info', f"設定が '{SETTINGS_FILE}' から読み込まれました。")
            return settings
    except json.JSONDecodeError as e:
        log_message('error', f"設定ファイルの読み込み中にエラーが発生しました（JSON形式が無効です）: {e}")
        return {"api_key": None} # 無効な場合はデフォルト設定を返す
    except IOError as e:
        log_message('error', f"設定ファイルの読み込み中にエラーが発生しました: {e}")
        return {"api_key": None} # エラー発生時はデフォルト設定を返す

def encrypt_api_key(api_key: str) -> str:
    """
    APIキーを暗号化する。
    """
    log_message = _get_logger_config_log_message()
    f = get_fernet()
    try:
        encrypted_bytes = f.encrypt(api_key.encode('utf-8'))
        log_message('info', "APIキーが暗号化されました。")
        return encrypted_bytes.decode('utf-8')
    except Exception as e:
        log_message('error', f"APIキーの暗号化に失敗しました: {e}")
        return "" # 暗号化失敗時は空文字列を返す

def decrypt_api_key(encrypted_api_key: str) -> str | None:
    """
    暗号化されたAPIキーを復号化する。
    """
    log_message = _get_logger_config_log_message()
    f = get_fernet()
    try:
        decrypted_bytes = f.decrypt(encrypted_api_key.encode('utf-8'))
        log_message('info', "APIキーが復号化されました。")
        return decrypted_bytes.decode('utf-8')
    except Exception as e:
        log_message('error', f"APIキーの復号化に失敗しました: {e}")
        return None # 復号化失敗時はNoneを返す

# 初期設定ファイルの作成（もし存在しない場合）
# アプリケーションの起動時に一度だけ実行されることを想定
if not os.path.exists(SETTINGS_FILE):
    save_settings({"api_key": None})

# 暗号化キーの確認と生成
# アプリケーションの起動時にキーが存在しない場合に自動生成
load_key()
