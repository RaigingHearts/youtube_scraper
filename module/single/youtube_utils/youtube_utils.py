"""
YouTube関連の汎用的なユーティリティ機能を提供するモジュールスクリプト。
動画IDの抽出など、YouTube特有のデータ操作をまとめる。
モジュールタイプ：単体モジュール

利用したいPythonスクリプトへインポートして利用可能:
"import youtube_utils"

メソッド構成:
├── "YouTubeのURLから動画IDを抽出するメソッド"
│   └── "def extract_video_id(url):"
コピペ編集用罫線 '━┃┏┓┛┗┣┳┫┻╋' '─│┌┐┘└├┬┤┴┼'
"""
# youtube_utils.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import re
import sys

# ログ出力のためにlogger_configをインポート
from module.utility.logger_config import logger_config

def extract_video_id(url: str) -> str | None:
    """
    YouTubeのURLから動画IDを抽出する。
    対応するURL形式:
    - 標準URL: https://www.youtube.com/watch?v=xxxxxxxxxxx
    - 短縮URL: https://youtu.be/xxxxxxxxxxx
    - 埋め込みURL: https://www.youtube.com/embed/xxxxxxxxxxx

    Args:
        url (str): YouTube動画のURL。

    Returns:
        str | None: 抽出された動画ID。見つからない場合はNone。
    """
    # 短縮URL (youtu.be)
    match = re.search(r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})', url)
    if match:
        logger_config.log_message('info', f"短縮URLから動画IDを抽出しました: {match.group(1)}")
        return match.group(1)

    # 標準URL (youtube.com/watch?v=)
    match = re.search(r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})', url)
    if match:
        logger_config.log_message('info', f"標準URLから動画IDを抽出しました: {match.group(1)}")
        return match.group(1)

    # 埋め込みURL (youtube.com/embed/)
    match = re.search(r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})', url)
    if match:
        logger_config.log_message('info', f"埋め込みURLから動画IDを抽出しました: {match.group(1)}")
        return match.group(1)

    logger_config.log_message('warning', f"URL '{url}' から有効なYouTube動画IDを抽出できませんでした。")
    return None # メソッド定義の末尾

# コピペ用メソッドコードの例 (使用例として)
"""
# モジュールのインポート設定
import youtube_utils

# 使用例
url1 = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
url2 = "https://youtu.be/dQw4w9WgXcQ"
url3 = "https://www.youtube.com/embed/dQw4w9WgXcQ"
invalid_url = "https://www.google.com"

print(f"URL1の動画ID: {youtube_utils.extract_video_id(url1)}")
print(f"URL2の動画ID: {youtube_utils.extract_video_id(url2)}")
print(f"URL3の動画ID: {youtube_utils.extract_video_id(url3)}")
print(f"無効なURLの動画ID: {youtube_utils.extract_video_id(invalid_url)}")
"""
