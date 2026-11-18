"""
YouTube Data APIを利用して動画・チャンネル情報とコメントを取得するモジュール。
"""
# youtube_api_client.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

from module.utility.logger_config import logger_config
from module.utility.tk_notifications import tk_notifications

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
COMMENT_FETCH_THRESHOLD = 100


def get_youtube_service(api_key: str) -> Any:
    """YouTube Data APIサービスオブジェクトを構築して返す。"""
    try:
        service = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=api_key)
        logger_config.log_message('info', "YouTube APIサービスオブジェクトを構築しました。")
        return service
    except Exception as e:
        logger_config.log_message('error', f"YouTube APIサービス構築エラー: {e}")
        tk_notifications.show_error(
            "APIエラー",
            f"YouTube APIサービスを構築できませんでした。\nAPIキーが正しいか確認してください。\nエラー: {e}"
        )
        return None


def _report_api_error(title: str, message: str) -> None:
    """API取得エラーをログとGUI通知に記録する。"""
    logger_config.log_message('error', message)
    tk_notifications.show_error(title, message)


def _get_api_error_reason(error: HttpError) -> Optional[str]:
    """HttpErrorのレスポンス本文からYouTube APIのエラーreasonを取得する。"""
    try:
        content = error.content
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        payload = json.loads(content)
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None

    error_details = payload.get("error", {}).get("errors", [])
    for detail in error_details:
        reason = detail.get("reason")
        if reason:
            return reason
    return None


def fetch_all_comments(
    api_key: str,
    video_id: str,
    progress_callback: Optional[Callable[[int, int, Optional[str]], None]] = None,
    confirm_callback: Optional[Callable[[str], bool]] = None
) -> tuple[dict, int, int]:
    """
    動画情報・チャンネル情報・コメントスレッドと、各スレッドの返信を取得する。

    既存の comment_threads_raw_responses は commentThreads.list のRawレスポンス配列として維持する。
    返信は comment_replies_raw_responses に親コメントIDとRawレスポンスページを紐付けて格納する。
    戻り値の3要素タプルは既存呼び出し元との互換性のため維持する。
    """
    empty_result = {
        "video_info_raw_response": {},
        "channel_info_raw_response": {},
        "comment_threads_raw_responses": [],
        "comment_replies_raw_responses": [],
        "fetch_status": "failed",
        "errors": []
    }
    result_data = empty_result
    service = get_youtube_service(api_key)
    if not service:
        message = "YouTube APIサービスが利用できないため、コメント取得を中止しました。"
        result_data["errors"].append({"stage": "service", "message": message})
        logger_config.log_message('error', message)
        return result_data, 0, 0

    comments_fetched_count = 0
    total_threads_expected = 0
    total_replies_expected = 0
    next_page_token = None
    continuation_prompted = False
    stop_after_current_thread_page = False
    user_cancelled = False
    comment_threads_completed = False
    comments_disabled = False

    def record_error(stage: str, message: str) -> None:
        result_data["errors"].append({"stage": stage, "message": message})

    # 動画情報
    channel_id: Optional[str] = None
    try:
        video_response = service.videos().list(part="snippet", id=video_id).execute()
        result_data["video_info_raw_response"] = video_response
        if video_response.get("items"):
            video_snippet = video_response["items"][0].get("snippet", {})
            channel_id = video_snippet.get("channelId")
            logger_config.log_message(
                'info',
                f"動画情報取得: タイトル='{video_snippet.get('title', 'タイトル不明')}', "
                f"投稿者='{video_snippet.get('channelTitle', '投稿者不明')}'"
            )
        else:
            message = f"動画ID '{video_id}' の情報が見つかりませんでした。"
            record_error("video_info", message)
            logger_config.log_message('warning', message)
    except HttpError as e:
        message = f"動画情報の取得中にAPIエラーが発生しました: {e}"
        record_error("video_info", message)
        _report_api_error("APIエラー", message)
        return result_data, comments_fetched_count, total_threads_expected + total_replies_expected
    except Exception as e:
        message = f"動画情報取得中に予期せぬエラーが発生しました: {e}"
        record_error("video_info", message)
        _report_api_error("エラー", message)
        return result_data, comments_fetched_count, total_threads_expected + total_replies_expected

    # チャンネル情報
    if channel_id:
        try:
            result_data["channel_info_raw_response"] = service.channels().list(
                part="snippet", id=channel_id
            ).execute()
            if not result_data["channel_info_raw_response"].get("items"):
                message = f"チャンネルID '{channel_id}' の情報が見つかりませんでした。"
                record_error("channel_info", message)
                logger_config.log_message('warning', message)
        except HttpError as e:
            message = f"チャンネル情報の取得中にAPIエラーが発生しました: {e}"
            record_error("channel_info", message)
            _report_api_error("APIエラー", message)
        except Exception as e:
            message = f"チャンネル情報取得中に予期せぬエラーが発生しました: {e}"
            record_error("channel_info", message)
            _report_api_error("エラー", message)

    # コメントスレッドと返信
    while True:
        try:
            response = service.commentThreads().list(
                part="snippet,replies",
                videoId=video_id,
                maxResults=100,
                pageToken=next_page_token,
                textFormat="plainText"
            ).execute()
            result_data["comment_threads_raw_responses"].append(response)

            thread_items = response.get("items", [])
            # pageInfo.totalResults はページ単位の値として返る場合があるため、
            # 全ページのitems数を累積して親コメントの取得見込み数を求める。
            total_threads_expected += len(thread_items)
            # 現在ページ内の返信見込み数を先に集計し、返信取得途中でも
            # このページまでの見込み数が欠落しないようにする。
            total_replies_expected += sum(
                (thread.get("snippet", {}).get("totalReplyCount", 0) or 0)
                for thread in thread_items
            )
            next_page_token = response.get("nextPageToken")
            comment_threads_completed = not bool(next_page_token)

            for thread in thread_items:
                comments_fetched_count += 1  # スレッドの親コメント
                thread_snippet = thread.get("snippet", {})
                reply_count = thread_snippet.get("totalReplyCount", 0) or 0

                if reply_count <= 0:
                    continue

                parent_comment = thread_snippet.get("topLevelComment", {})
                parent_id = parent_comment.get("id") or thread.get("id")
                if not parent_id:
                    message = "返信数が記録されたスレッドに親コメントIDがないため、返信取得をスキップしました。"
                    record_error("reply_comments", message)
                    logger_config.log_message('warning', message)
                    continue

                reply_record = {"parent_id": parent_id, "raw_responses": []}
                result_data["comment_replies_raw_responses"].append(reply_record)
                reply_page_token = None

                while True:
                    try:
                        reply_response = service.comments().list(
                            part="snippet",
                            parentId=parent_id,
                            maxResults=100,
                            pageToken=reply_page_token,
                            textFormat="plainText"
                        ).execute()
                    except HttpError as e:
                        message = f"親コメント '{parent_id}' の返信ページ取得中にAPIエラーが発生しました: {e}"
                        record_error("reply_comments", message)
                        logger_config.log_message('error', message)
                        if getattr(getattr(e, "resp", None), "status", None) == 403 and "quotaExceeded" in str(e):
                            logger_config.log_message('critical', "返信取得中にAPIクォータ制限に達しました。")
                        tk_notifications.show_error(
                            "返信取得エラー",
                            f"親コメント '{parent_id}' の返信をすべて取得できませんでした。\n"
                            f"取得済みの返信データは保存対象に残します。\n{e}"
                        )
                        stop_after_current_thread_page = True
                        break
                    except Exception as e:
                        message = f"親コメント '{parent_id}' の返信取得中に予期せぬエラーが発生しました: {e}"
                        record_error("reply_comments", message)
                        logger_config.log_message('error', message)
                        tk_notifications.show_error(
                            "返信取得エラー",
                            f"親コメント '{parent_id}' の返信取得中にエラーが発生しました。\n{e}"
                        )
                        stop_after_current_thread_page = True
                        break

                    # APIレスポンスを加工せず、ページ単位でそのまま保存する
                    reply_record["raw_responses"].append(reply_response)
                    fetched_on_page = len(reply_response.get("items", []))
                    comments_fetched_count += fetched_on_page
                    if progress_callback:
                        progress_callback(
                            comments_fetched_count,
                            (total_threads_expected + total_replies_expected) if comment_threads_completed else None,
                            f"返信コメント取得中... ({comments_fetched_count}件)"
                        )

                    reply_page_token = reply_response.get("nextPageToken")
                    if not reply_page_token:
                        break
                    time.sleep(0.1)

                if stop_after_current_thread_page:
                    break

            if progress_callback:
                progress_callback(
                    comments_fetched_count,
                    (total_threads_expected + total_replies_expected) if comment_threads_completed else None,
                    f"コメント取得中... ({comments_fetched_count}件)"
                )

            if stop_after_current_thread_page:
                break

            if not next_page_token:
                logger_config.log_message('info', "コメントスレッドと返信コメントの取得を完了しました。")
                break

            if (
                not continuation_prompted
                and comments_fetched_count >= COMMENT_FETCH_THRESHOLD
                and confirm_callback
            ):
                continuation_prompted = True
                message = (
                    f"現在までに {comments_fetched_count} 件のコメントを取得しました。 "
                    "まだコメントが残っている可能性があります。\n"
                    "さらにコメントの取得を続けますか？"
                )
                if not confirm_callback(message):
                    user_cancelled = True
                    logger_config.log_message('info', "ユーザーによってコメント取得が中断されました。")
                    break

            time.sleep(0.1)

        except HttpError as e:
            api_error_reason = _get_api_error_reason(e)
            if api_error_reason == "commentsDisabled":
                comments_disabled = True
                message = "この動画ではコメントがオフに設定されているため、コメントを取得できません。"
                result_data["errors"].append({
                    "stage": "comment_threads",
                    "reason": api_error_reason,
                    "message": message
                })
                logger_config.log_message('warning', f"{message} (API reason: {api_error_reason})")
            elif api_error_reason == "videoNotFound":
                message = (
                    "動画を確認できませんでした。投稿されている動画の削除、URLや動画IDの間違い・"
                    "ミスコピー、投稿者による非公開設定などの可能性があります。"
                )
                result_data["errors"].append({
                    "stage": "comment_threads",
                    "reason": api_error_reason,
                    "message": message
                })
                logger_config.log_message('warning', f"{message} (API reason: {api_error_reason})")
                tk_notifications.show_warning("動画を確認できません", message)
            else:
                message = f"YouTubeコメントスレッド取得中にAPIエラーが発生しました: {e}"
                record_error("comment_threads", message)
                logger_config.log_message('error', message)
                if getattr(getattr(e, "resp", None), "status", None) == 403 and "quotaExceeded" in str(e):
                    logger_config.log_message('critical', "APIクォータ制限に達しました。")
                tk_notifications.show_error(
                    "APIエラー",
                    f"YouTubeコメントスレッド取得中にエラーが発生しました。\n取得済みデータは保存対象に残します。\n{e}"
                )
            break
        except Exception as e:
            message = f"コメントスレッド取得中に予期せぬエラーが発生しました: {e}"
            record_error("comment_threads", message)
            logger_config.log_message('error', message)
            tk_notifications.show_error("エラー", f"コメントスレッド取得中にエラーが発生しました。\n{e}")
            break

    # 全コメントスレッドのページングが完了した場合に限り、返信見込み数も含む
    # 合計を確定値として返す。途中中断・ページ取得失敗時は未確定(0)とする。
    total_comments_expected = (
        total_threads_expected + total_replies_expected if comment_threads_completed else 0
    )
    if comments_disabled:
        result_data["fetch_status"] = "comments_disabled"
    elif user_cancelled:
        result_data["fetch_status"] = "cancelled"
    elif result_data["errors"]:
        result_data["fetch_status"] = "partial" if comments_fetched_count > 0 or comment_threads_completed else "failed"
    elif comment_threads_completed:
        result_data["fetch_status"] = "complete"
    else:
        result_data["fetch_status"] = "failed"

    logger_config.log_message(
        'info',
        f"コメント取得終了: 状態={result_data['fetch_status']}, 取得数={comments_fetched_count}, "
        f"取得見込み={total_comments_expected if comment_threads_completed else '未確定'}, "
        f"返信スレッド数={len(result_data['comment_replies_raw_responses'])}"
    )
    return result_data, comments_fetched_count, total_comments_expected
