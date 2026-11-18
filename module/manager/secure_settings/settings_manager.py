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
import logging
import os

# 文字列の暗号化･復号化を制御するライブラリ"pip install cryptography"で導入してから利用すべし。
# workspacedata.txtのpip listにcryptographyが含まれていることを確認済み
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# このモジュールで管理される設定ファイル名
# アプリケーション固有のファイル名命名規則に従い、混同を避ける
APP_NAME_PREFIX = "youtube_scraper" # アプリケーションの名称を定義 (例: "your_app_name")
SETTINGS_FILE = f"{APP_NAME_PREFIX}-settings.json"
# この管理モジュール用の平文文字列暗号化キーファイル名
ENCRYPTION_KEY_FILE = f"{APP_NAME_PREFIX}-encryption_key.key"

def generate_key() -> bytes:
    """
    暗号化キーを生成し、ファイルに保存する。
    このキーファイルはGitリポジトリから除外されるべき。
    """

    key = Fernet.generate_key()
    try:
        with open(ENCRYPTION_KEY_FILE, "wb") as key_file:
            key_file.write(key)
        logger.info(f"新しい暗号化キーが '{ENCRYPTION_KEY_FILE}' に生成・保存されました。")
        logger.warning(f"'{ENCRYPTION_KEY_FILE}' は機密情報です。Gitリポジトリの追跡から除外してください。")
    except IOError as e:
        logger.error(f"暗号化キーの保存中にエラーが発生しました: {e}")
    return key

def load_key() -> bytes:
    """
    暗号化キーをファイルから読み込む。存在しない場合は生成する。
    """

    if os.path.exists(ENCRYPTION_KEY_FILE):
        try:
            with open(ENCRYPTION_KEY_FILE, "rb") as key_file:
                key = key_file.read()
            logger.info(f"暗号化キーが '{ENCRYPTION_KEY_FILE}' から読み込まれました。")
            return key
        except IOError as e:
            logger.error(f"暗号化キーの読み込み中にエラーが発生しました: {e}")
            # エラー発生時は新しいキーを生成して続行
            return generate_key()
    else:
        logger.info(f"暗号化キーファイル '{ENCRYPTION_KEY_FILE}' が見つかりません。新しいキーを生成します。")
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

    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        logger.info(f"設定が '{SETTINGS_FILE}' に保存されました。")
    except IOError as e:
        logger.error(f"設定ファイルの保存中にエラーが発生しました: {e}")

def load_settings() -> dict:
    """
    設定をJSONファイルから読み込む。ファイルが存在しない場合はデフォルト設定を返す。
    """

    if not os.path.exists(SETTINGS_FILE):
        logger.warning(f"設定ファイル '{SETTINGS_FILE}' が見つかりません。デフォルト設定をロードします。")
        return {"api_key": None} # デフォルト設定
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
            logger.info(f"設定が '{SETTINGS_FILE}' から読み込まれました。")
            return settings
    except json.JSONDecodeError as e:
        logger.error(f"設定ファイルの読み込み中にエラーが発生しました（JSON形式が無効です）: {e}")
        return {"api_key": None} # 無効な場合はデフォルト設定を返す
    except IOError as e:
        logger.error(f"設定ファイルの読み込み中にエラーが発生しました: {e}")
        return {"api_key": None} # エラー発生時はデフォルト設定を返す

def encrypt_api_key(api_key: str) -> str:
    """
    APIキーを暗号化する。
    """

    f = get_fernet()
    try:
        encrypted_bytes = f.encrypt(api_key.encode('utf-8'))
        logger.info("APIキーが暗号化されました。")
        return encrypted_bytes.decode('utf-8')
    except Exception as e:
        logger.error(f"APIキーの暗号化に失敗しました: {e}")
        return "" # 暗号化失敗時は空文字列を返す

def decrypt_api_key(encrypted_api_key: str) -> str | None:
    """
    暗号化されたAPIキーを復号化する。
    """

    f = get_fernet()
    try:
        decrypted_bytes = f.decrypt(encrypted_api_key.encode('utf-8'))
        logger.info("APIキーが復号化されました。")
        return decrypted_bytes.decode('utf-8')
    except Exception as e:
        logger.error(f"APIキーの復号化に失敗しました: {e}")
        return None # 復号化失敗時はNoneを返す

def initialize_settings() -> None:
    """設定ファイルと暗号化キーをアプリケーション起動時に初期化する。"""
    if not os.path.exists(SETTINGS_FILE):
        save_settings({"api_key": None})
    load_key()
