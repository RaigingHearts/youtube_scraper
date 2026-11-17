"""
Youtube Data APIを利用するためのモジュールスクリプト。
動画情報、チャンネル情報、コメントをAPIから取得する機能を提供する。
モジュールタイプ：ユーティリティモジュール

利用したいPythonスクリプトへインポートして利用可能:
"import youtube_api_client"

メソッド構成:
├── "APIキーを利用してYoutubeサービスオブジェクトを構築"
│   └── "def get_youtube_service(api_key):"
├── "指定された動画のコメントをすべて取得する"
│   └── "def fetch_all_comments(api_key, video_id, progress_callback=None, confirm_callback=None):"
コピペ編集用罫線 '━┃┏┓┛┗┣┳┫┻╋' '─│┌┐┘└├┬┤┴┼'
"""
# youtube_api_client.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import time
from typing import Any, Callable, Optional

# ロギングと通知、ユーティリティモジュールをインポート
from module.utility.logger_config import logger_config
from module.utility.tk_notifications import tk_notifications # TkinterのメッセージボックスなどのGUI通知用
# utilsはyoutube_utilsに分割されたため、ここでは直接インポートしない
# youtube_utilsは動画ID抽出に特化しているため、APIクライアント自体は直接使用しない

# Youtube Data APIクライアントライブラリ"pip install google-api-python-client"で導入して利用すべし。
# workspacedata.txtのpip listにgoogle-api-python-clientが含まれていることを確認済み
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# APIキーは設定ファイルから取得するため、ここではプレースホルダ
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

def get_youtube_service(api_key: str) -> Any:
    """
    YouTube Data APIサービスオブジェクトを構築して返す。

    Args:
        api_key (str): YouTube Data APIキー。

    Returns:
        Any: 構築されたYouTube Data APIサービスオブジェクト。失敗した場合はNone。
    """
    try:
        service = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=api_key)
        logger_config.log_message('info', "YouTube APIサービスオブジェクトを構築しました。")
        return service
    except Exception as e:
        logger_config.log_message('error', f"YouTube APIサービス構築エラー: {e}")
        tk_notifications.show_error("APIエラー", f"YouTube APIサービスを構築できませんでした。\nAPIキーが正しいか確認してください。\nエラー: {e}")
        return None

def fetch_all_comments(api_key: str, video_id: str, 
                       progress_callback: Optional[Callable[[int, int, Optional[str]], None]] = None, 
                       confirm_callback: Optional[Callable[[str], bool]] = None) -> tuple[dict, int, int]:
    """
    指定された動画のコメントをすべて取得する。
    動画情報、チャンネル情報、コメントスレッドのRawレスポンスを返す。

    Args:
        api_key (str): YouTube Data APIキー。
        video_id (str): コメントを取得するYouTube動画のID。
        progress_callback (Optional[Callable]): 進捗を更新するためのコールバック関数。
                                                引数: (current_comments: int, total_comments: int, message: Optional[str])
        confirm_callback (Optional[Callable]): 取得継続を確認するためのコールバック関数。
                                               引数: (message: str) -> bool

    Returns:
        tuple[dict, int, int]:
        - result_data (dict): 動画情報のRawレスポンス、チャンネル情報のRawレスポンス、コメントのRawレスポンスを含む辞書。
        - comments_fetched_count (int): 実際に取得したコメント数。
        - total_comments_expected (int): APIから取得できるコメント総数の目安（APIの制限により正確でない場合がある）。
    """
    service: Any = get_youtube_service(api_key)
    if not service:
        logger_config.log_message('error', "YouTube APIサービスが利用できないため、コメント取得を中止します。")
        return {"video_info_raw_response": {}, "channel_info_raw_response": {}, "comment_threads_raw_responses": []}, 0, 0

    result_data = {
        "video_info_raw_response": {},
        "channel_info_raw_response": {},
        "comment_threads_raw_responses": []
    }

    comments_fetched_count = 0
    total_comments_expected = 0
    next_page_token = None
    
    # 仮の上限値（ユーザーに確認を求めるしきい値）
    COMMENT_FETCH_THRESHOLD = 100 

    # --- 動画情報の取得 ---
    channel_id: Optional[str] = None
    try:
        video_request = service.videos().list(
            part="snippet",
            id=video_id
        )
        video_response = video_request.execute()
        
        result_data["video_info_raw_response"] = video_response

        video_title = "タイトル不明"
        channel_title = "投稿者不明"
        if video_response and video_response.get("items"):
            video_snippet = video_response["items"][0]["snippet"]
            video_title = video_snippet.get("title", video_title)
            channel_title = video_snippet.get("channelTitle", channel_title)
            channel_id = video_snippet.get("channelId")
            logger_config.log_message('info', f"動画情報取得: タイトル='{video_title}', 投稿者='{channel_title}'")
        else:
            logger_config.log_message('warning', f"動画ID '{video_id}' の情報が見つかりませんでした。")

    except HttpError as e:
        logger_config.log_message('error', f"動画情報取得中にAPIエラーが発生しました: {e}")
        tk_notifications.show_error("APIエラー", f"動画情報の取得中にエラーが発生しました:\n{e}")
    except Exception as e:
        logger_config.log_message('error', f"動画情報取得中に予期せぬエラーが発生しました: {e}")
        tk_notifications.show_error("エラー", f"動画情報取得中に予期せぬエラーが発生しました:\n{e}")

    # --- チャンネル情報の取得 ---
    if channel_id:
        try:
            channel_request = service.channels().list(
                part="snippet",
                id=channel_id
            )
            channel_response = channel_request.execute()
            
            result_data["channel_info_raw_response"] = channel_response
            logger_config.log_message('info', f"チャンネル情報取得: チャンネルID='{channel_id}'")
        except HttpError as e:
            logger_config.log_message('error', f"チャンネル情報取得中にAPIエラーが発生しました: {e}")
            tk_notifications.show_error("APIエラー", f"チャンネル情報の取得中にエラーが発生しました:\n{e}")
        except Exception as e:
            logger_config.log_message('error', f"チャンネル情報取得中に予期せぬエラーが発生しました: {e}")
            tk_notifications.show_error("エラー", f"チャンネル情報取得中に予期せぬエラーが発生しました:\n{e}")
    else:
        logger_config.log_message('warning', f"動画情報からチャンネルIDが見つからなかったため、チャンネル情報は取得されませんでした。")

    # --- コメントの取得 ---
    while True:
        try:
            request = service.commentThreads().list(
                part="snippet,replies",
                videoId=video_id,
                maxResults=100,
                pageToken=next_page_token,
                textFormat="plainText"
            )
            response = request.execute()
            
            result_data["comment_threads_raw_responses"].append(response)

            for item in response.get("items", []):
                comments_fetched_count += 1
                if "replies" in item:
                    comments_fetched_count += len(item["replies"].get("comments", []))

            if "pageInfo" in response and "totalResults" in response["pageInfo"]:
                if total_comments_expected == 0: # 最初のページで総コメント数の目安を設定
                    total_comments_expected = response["pageInfo"].get("totalResults", 0)

            if progress_callback:
                # 進捗メッセージをより具体的に
                progress_message = f"コメント取得中... ({comments_fetched_count}件)"
                progress_callback(comments_fetched_count, total_comments_expected, progress_message)

            next_page_token = response.get("nextPageToken")

            # コメント取得上限の確認
            if next_page_token and comments_fetched_count >= COMMENT_FETCH_THRESHOLD:
                if confirm_callback:
                    message = (f"現在までに {comments_fetched_count} 件のコメントを取得しました。 "
                               f"まだコメントが残っている可能性があります。\n"
                               f"さらにコメントの取得を続けますか？")
                    if not confirm_callback(message):
                        logger_config.log_message('info', "ユーザーによってコメント取得が中断されました。")
                        break # ユーザーがキャンセルした場合

            if not next_page_token:
                logger_config.log_message('info', "すべてのコメントの取得を完了しました。")
                break # すべてのコメントを取得完了

        except HttpError as e:
            logger_config.log_message('error', f"YouTube APIエラーが発生しました: {e}")
            if e.resp.status == 403 and "quotaExceeded" in str(e):
                logger_config.log_message('critical', "APIクォータ制限に達しました。")
                if confirm_callback:
                    message = ("YouTube Data APIのクォータ制限に達しました。\n"
                               "しばらく経ってから再度お試しください。\n"
                               "プログラムを終了しますか？ (「はい」で終了、「いいえ」で続行を試みますが、再度エラーになる可能性があります)")
                    if not confirm_callback(message):
                        # ユーザーが「いいえ」を選択した場合、ループを抜けて終了
                        return result_data, comments_fetched_count, total_comments_expected
                # ユーザーが「はい」を選択した場合、または確認なしの場合、終了
                return result_data, comments_fetched_count, total_comments_expected
            
            tk_notifications.show_error("APIエラー", f"YouTube APIエラーが発生しました:\n{e}")
            return result_data, comments_fetched_count, total_comments_expected # エラー発生時はここまでで終了

        except Exception as e:
            logger_config.log_message('error', f"予期せぬエラーが発生しました: {e}")
            tk_notifications.show_error("エラー", f"予期せぬエラーが発生しました:\n{e}")
            return result_data, comments_fetched_count, total_comments_expected

        time.sleep(0.1) # APIリクエストの間隔を少し開ける

    return result_data, comments_fetched_count, total_comments_expected

# コピペ用メソッドコードの例 (使用例として)
"""
# モジュールのインポート設定
import youtube_api_client
import logger_config
import tk_notifications # Tkinterの通知表示モジュール

# 使用例 (GUIアプリケーションのバックエンド処理から呼び出すことを想定)
def fetch_comments_for_gui(api_key, video_id, progress_label, progress_bar, master_root):
    # 進捗更新コールバック
    def on_progress(current, total, message):
        master_root.after(0, lambda: progress_label.config(text=f"{message} - {current}/{total}"))
        master_root.after(0, lambda: progress_bar.config(maximum=total, value=current))

    # 確認ダイアログコールバック
    def on_confirm(message):
        return tk_notifications.ask_yes_no("確認", message, parent=master_root)

    logger_config.log_message('info', f"GUI経由でコメント取得を開始: 動画ID='{video_id}'")
    result_data, fetched_count, total_expected = youtube_api_client.fetch_all_comments(
        api_key,
        video_id,
        progress_callback=on_progress,
        confirm_callback=on_confirm
    )
    
    if result_data:
        tk_notifications.show_info("完了", f"コメント取得が完了しました。{fetched_count}件のコメントを取得。", parent=master_root)
    else:
        tk_notifications.show_error("エラー", "コメント取得中に問題が発生しました。ログを確認してください。", parent=master_root)

# 注意: このコードはGUIアプリケーションのメインスレッドとは別のスレッドで実行されるべきです。
# そのため、tk_async_tasksモジュールと組み合わせて使用することを推奨します。
"""
