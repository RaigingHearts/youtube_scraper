"""
YouTube関連の汎用的なユーティリティ機能を提供するモジュールスクリプト。
動画IDの抽出など、YouTube特有のデータ操作をまとめる。
モジュールタイプ：単体モジュール

利用したいPythonスクリプトへインポートして利用可能:
"import youtube_utils"

メソッド構成:
├── "YouTube動画IDの形式を検証するメソッド"
│   └── "def is_valid_video_id(video_id):"
└── "YouTubeのURLから動画IDを抽出するメソッド"
    └── "def extract_video_id(url):"
コピペ編集用罫線 '━┃┏┓┛┗┣┳┫┻╋' '─│┌┐┘└├┬┤┴┼'
"""
# youtube_utils.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlsplit

logger = logging.getLogger(__name__)

# YouTube動画IDは11文字の英数字・ハイフン・アンダースコアで構成される。
_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")

# 対応するYouTubeのホスト名。
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def is_valid_video_id(video_id: str) -> bool:
    """
    YouTube動画IDの形式を検証する。

    Args:
        video_id (str): 検証する動画ID。

    Returns:
        bool: 正しい形式の場合はTrue。それ以外はFalse。
    """
    if not isinstance(video_id, str):
        return False

    return _VIDEO_ID_PATTERN.fullmatch(video_id) is not None


def extract_video_id(url: str) -> str | None:
    """
    対応するYouTubeのURLから動画IDを抽出する。

    対応するURL形式:
    - 標準URL: https://www.youtube.com/watch?v=xxxxxxxxxxx
    - 短縮URL: https://youtu.be/xxxxxxxxxxx
    - 埋め込みURL: https://www.youtube.com/embed/xxxxxxxxxxx
    - Shorts URL: https://www.youtube.com/shorts/xxxxxxxxxxx
    - Live URL: https://www.youtube.com/live/xxxxxxxxxxx
    - モバイルURL: https://m.youtube.com/watch?v=xxxxxxxxxxx
    - YouTube Music URL: https://music.youtube.com/watch?v=xxxxxxxxxxx

    Args:
        url (str): YouTube動画のURL。

    Returns:
        str | None: 抽出された動画ID。見つからない場合はNone。
    """
    if not isinstance(url, str) or not url.strip():
        logger.warning("空または不正なURLが指定されました。")
        return None

    url = url.strip()

    # スキーム省略時はHTTPSとして解析する。
    if url.startswith("//"):
        url = "https:" + url
    elif "://" not in url:
        url = "https://" + url

    try:
        parsed_url = urlsplit(url)

        # HTTP/HTTPS以外のスキームは受け付けない。
        if parsed_url.scheme.lower() not in {"http", "https"}:
            return None

        # ユーザー情報やポート番号を含むURLは受け付けない。
        if parsed_url.username is not None or parsed_url.password is not None:
            return None

        if parsed_url.port is not None:
            return None

        hostname = parsed_url.hostname
        if hostname is None or hostname.lower() not in _YOUTUBE_HOSTS:
            return None

        hostname = hostname.lower()
        path = parsed_url.path

        # URL末尾のスラッシュは1個まで許容する。
        if path.endswith("/"):
            path = path[:-1]
        video_id = None

        if hostname in {"youtu.be", "www.youtu.be"}:
            # 短縮URL: https://youtu.be/xxxxxxxxxxx
            if path.startswith("/") and path.count("/") == 1:
                video_id = path[1:]

        elif path == "/watch":
            # 標準URL・モバイルURL・YouTube Music URL
            query_params = parse_qs(
                parsed_url.query,
                keep_blank_values=True,
            )
            video_ids = query_params.get("v", [])

            # vパラメータが重複している場合は受け付けない。
            if len(video_ids) == 1:
                video_id = video_ids[0]

        elif hostname != "music.youtube.com":
            # 埋め込み・Shorts・Live URL
            path_parts = path.split("/")

            if (
                len(path_parts) == 3
                and path_parts[0] == ""
                and path_parts[1] in {"embed", "shorts", "live"}
            ):
                video_id = path_parts[2]

        if video_id is not None and is_valid_video_id(video_id):
            logger.info("YouTube動画IDを抽出しました。")
            return video_id

    except ValueError:
        # 不正なポート番号など、URL解析時の例外。
        pass

    logger.warning("対応していないURL、または不正な動画IDが指定されました。")
    return None


# コピペ用メソッドコードの例 (使用例として)
"""
# モジュールのインポート設定
import youtube_utils

# 使用例
url1 = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
url2 = "https://youtu.be/dQw4w9WgXcQ"
url3 = "https://www.youtube.com/embed/dQw4w9WgXcQ"
url4 = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
url5 = "https://www.youtube.com/live/dQw4w9WgXcQ"

print(f"URL1の動画ID: {youtube_utils.extract_video_id(url1)}")
print(f"URL2の動画ID: {youtube_utils.extract_video_id(url2)}")
print(f"URL3の動画ID: {youtube_utils.extract_video_id(url3)}")
print(f"URL4の動画ID: {youtube_utils.extract_video_id(url4)}")
print(f"URL5の動画ID: {youtube_utils.extract_video_id(url5)}")
"""
