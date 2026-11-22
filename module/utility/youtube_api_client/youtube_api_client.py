"""
YouTube Data APIを利用して動画・チャンネル情報とコメントを取得するモジュール。
"""
# youtube_api_client.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Callable, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
COMMENT_FETCH_THRESHOLD = 100


def get_youtube_service(
    api_key: str,
    error_callback: Optional[Callable[[str], None]] = None,
) -> Any:
    """YouTube Data APIサービスを構築し、失敗時は秘匿化した概要を任意のcallbackへ渡す。"""
    try:
        service = build(YOUTUBE_API_SERVICE_NAME,
                        YOUTUBE_API_VERSION, developerKey=api_key)
        logger.info("YouTube APIサービスオブジェクトを構築しました。")
        return service
    except Exception as e:
        error_summary = _safe_exception_summary(e)
        logger.error("YouTube APIサービス構築エラー: %s", error_summary)
        if error_callback is not None:
            error_callback(error_summary)
        return None


def _get_api_error_reason(error: HttpError) -> Optional[str]:
    """HttpErrorのレスポンス本文からYouTube APIのエラーreasonを取得する。"""
    try:
        content = error.content
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        payload = json.loads(content)
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None

    if not isinstance(payload, dict):
        return None

    error_payload = payload.get("error")
    if not isinstance(error_payload, dict):
        return None

    error_details = error_payload.get("errors")
    if not isinstance(error_details, list):
        return None

    for detail in error_details:
        if not isinstance(detail, dict):
            continue
        reason = detail.get("reason")
        if isinstance(reason, str) and reason:
            return reason
    return None


def _token_fingerprint(token: Optional[str]) -> str:
    """ページトークンの内容を露出させず、ログ上で同一性を追跡する。"""
    if not token:
        return "none"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _safe_exception_summary(error: Exception) -> str:
    """例外文字列に含まれ得るURL・APIキー・ページトークンを出さず概要を返す。"""
    details = [type(error).__name__]
    if isinstance(error, HttpError):
        status = getattr(getattr(error, "resp", None), "status", None)
        reason = _get_api_error_reason(error)
        if status is not None:
            details.append(f"HTTP status {status}")
        if reason:
            details.append(f"API reason {reason}")
    return " / ".join(details)


def fetch_all_comments(
    api_key: str,
    video_id: str,
    progress_callback: Optional[Callable[[
        int, Optional[int], Optional[str]], None]] = None,
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
        "errors": [],
        "notifications": []
    }
    result_data = empty_result
    service_error_summaries = []
    service = get_youtube_service(
        api_key, error_callback=service_error_summaries.append
    )
    if not service:
        message = "YouTube APIサービスが利用できないため、コメント取得を中止しました。"
        result_data["errors"].append({"stage": "service", "message": message})
        result_data["notifications"].append({
            "stage": "service",
            "kind": "error",
            "title": "APIエラー",
            "message": (
                "YouTube APIサービスを構築できませんでした。\n"
                "APIキーが正しいか確認してください。\n"
                "エラー概要: {}".format(
                    service_error_summaries[0]
                    if service_error_summaries else "詳細不明"
                )
            ),
        })
        logger.error(message)
        return result_data, 0, 0

    # 取得件数はユニークコメント数として扱い、Rawレコード数は別途記録する。
    comments_fetched_count = 0
    total_threads_expected = 0
    total_replies_expected = 0
    raw_thread_records_count = 0
    raw_reply_records_count = 0
    duplicate_parent_count = 0
    duplicate_reply_count = 0
    seen_parent_ids: set[str] = set()
    seen_reply_ids: set[str] = set()
    thread_page_number = 0
    next_page_token = None
    continuation_prompted = False
    stop_after_current_thread_page = False
    user_cancelled = False
    comment_threads_completed = False
    expected_total_confirmed = False
    comments_disabled = False

    def record_error(stage: str, message: str) -> None:
        result_data["errors"].append({"stage": stage, "message": message})

    def record_notification(stage: str, kind: str, title: str, message: str) -> None:
        """従来GUI通知していた事象だけを機械可読な分類情報として返す。"""
        result_data["notifications"].append({
            "stage": stage, "kind": kind, "title": title, "message": message
        })

    # 動画情報
    channel_id: Optional[str] = None
    try:
        video_response = service.videos().list(part="snippet", id=video_id).execute()
        result_data["video_info_raw_response"] = video_response
        if video_response.get("items"):
            video_snippet = video_response["items"][0].get("snippet", {})
            channel_id = video_snippet.get("channelId")
            logger.info(f"動画情報取得: タイトル='{video_snippet.get('title', 'タイトル不明')}', "
                        f"投稿者='{video_snippet.get('channelTitle', '投稿者不明')}'"
                        )
        else:
            message = f"動画ID '{video_id}' の情報が見つかりませんでした。"
            record_error("video_info", message)
            logger.warning(message)
    except HttpError as e:
        message = f"動画情報の取得中にAPIエラーが発生しました: {_safe_exception_summary(e)}"
        record_error("video_info", message)
        logger.error(message)
        record_notification("video_info", "error", "APIエラー", message)
        return result_data, comments_fetched_count, total_threads_expected + total_replies_expected
    except Exception as e:
        message = f"動画情報取得中に予期せぬエラーが発生しました: {_safe_exception_summary(e)}"
        record_error("video_info", message)
        logger.error(message)
        record_notification("video_info", "error", "エラー", message)
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
                logger.warning(message)
        except HttpError as e:
            message = f"チャンネル情報の取得中にAPIエラーが発生しました: {_safe_exception_summary(e)}"
            record_error("channel_info", message)
            logger.error(message)
            record_notification("channel_info", "error", "APIエラー", message)
        except Exception as e:
            message = f"チャンネル情報取得中に予期せぬエラーが発生しました: {_safe_exception_summary(e)}"
            record_error("channel_info", message)
            logger.error(message)
            record_notification("channel_info", "error", "エラー", message)

    # コメントスレッドと返信
    while True:
        try:
            thread_page_number += 1
            request_page_token = next_page_token
            logger.debug(
                "コメントスレッドページ取得開始: page=%d, request_token=%s",
                thread_page_number,
                _token_fingerprint(request_page_token)
            )
            response = service.commentThreads().list(
                part="snippet,replies",
                videoId=video_id,
                maxResults=100,
                pageToken=request_page_token,
                textFormat="plainText"
            ).execute()
            result_data["comment_threads_raw_responses"].append(response)

            thread_items = response.get("items", [])
            raw_thread_records_count += len(thread_items)
            next_page_token = response.get("nextPageToken")
            logger.debug(
                "コメントスレッドページ取得完了: page=%d, records=%d, next_token=%s",
                thread_page_number,
                len(thread_items),
                _token_fingerprint(next_page_token)
            )
            comment_threads_completed = not bool(next_page_token)

            thread_items_accounted = 0
            for thread_index, thread in enumerate(thread_items, start=1):
                thread_snippet = thread.get("snippet", {})
                reply_count = thread_snippet.get("totalReplyCount", 0) or 0
                parent_comment = thread_snippet.get("topLevelComment", {})
                parent_id = parent_comment.get("id") or thread.get("id")

                if parent_id and parent_id in seen_parent_ids:
                    duplicate_parent_count += 1
                    logger.warning(
                        "親コメントの重複を検出: id=%s, page=%d, item=%d",
                        parent_id,
                        thread_page_number,
                        thread_index
                    )
                    thread_items_accounted += 1
                    if comment_threads_completed and thread_items_accounted == len(thread_items):
                        expected_total_confirmed = True
                    continue

                if parent_id:
                    seen_parent_ids.add(parent_id)
                comments_fetched_count += 1
                total_threads_expected += 1
                total_replies_expected += reply_count
                thread_items_accounted += 1
                if comment_threads_completed and thread_items_accounted == len(thread_items):
                    expected_total_confirmed = True

                if reply_count <= 0:
                    continue

                if not parent_id:
                    message = "返信数が記録されたスレッドに親コメントIDがないため、返信取得をスキップしました。"
                    record_error("reply_comments", message)
                    logger.warning(message)
                    continue

                reply_record = {"parent_id": parent_id, "raw_responses": []}
                result_data["comment_replies_raw_responses"].append(
                    reply_record)
                reply_page_token = None
                reply_page_number = 0

                while True:
                    try:
                        reply_page_number += 1
                        request_reply_page_token = reply_page_token
                        logger.debug(
                            "返信ページ取得開始: parent_id=%s, page=%d, request_token=%s",
                            parent_id,
                            reply_page_number,
                            _token_fingerprint(request_reply_page_token)
                        )
                        reply_response = service.comments().list(
                            part="snippet",
                            parentId=parent_id,
                            maxResults=100,
                            pageToken=reply_page_token,
                            textFormat="plainText"
                        ).execute()
                    except HttpError as e:
                        error_summary = _safe_exception_summary(e)
                        message = f"親コメント '{parent_id}' の返信ページ取得中にAPIエラーが発生しました: {error_summary}"
                        record_error("reply_comments", message)
                        logger.error(message)
                        if _get_api_error_reason(e) == "quotaExceeded":
                            logger.critical("返信取得中にAPIクォータ制限に達しました。")
                        record_notification(
                            "reply_comments", "error", "返信取得エラー",
                            f"親コメント '{parent_id}' の返信をすべて取得できませんでした。\n"
                            f"取得済みの返信データは保存対象に残します。\nエラー概要: {error_summary}",
                        )
                        stop_after_current_thread_page = True
                        break
                    except Exception as e:
                        error_summary = _safe_exception_summary(e)
                        message = f"親コメント '{parent_id}' の返信取得中に予期せぬエラーが発生しました: {error_summary}"
                        record_error("reply_comments", message)
                        logger.error(message)
                        record_notification(
                            "reply_comments", "error", "返信取得エラー",
                            f"親コメント '{parent_id}' の返信取得中にエラーが発生しました。\nエラー概要: {error_summary}",
                        )
                        stop_after_current_thread_page = True
                        break

                    # APIレスポンスを加工せず、ページ単位でそのまま保存する
                    reply_record["raw_responses"].append(reply_response)
                    reply_items = reply_response.get("items", [])
                    next_reply_page_token = reply_response.get("nextPageToken")
                    logger.debug(
                        "返信ページ取得完了: parent_id=%s, page=%d, records=%d, next_token=%s",
                        parent_id,
                        reply_page_number,
                        len(reply_items),
                        _token_fingerprint(next_reply_page_token)
                    )
                    raw_reply_records_count += len(reply_items)
                    fetched_on_page = 0
                    for reply_item in reply_items:
                        reply_id = reply_item.get("id")
                        if reply_id and reply_id in seen_reply_ids:
                            duplicate_reply_count += 1
                            logger.warning(
                                "返信コメントの重複を検出: id=%s, parent_id=%s",
                                reply_id,
                                parent_id
                            )
                            continue
                        if reply_id:
                            seen_reply_ids.add(reply_id)
                        fetched_on_page += 1
                    comments_fetched_count += fetched_on_page
                    if progress_callback:
                        progress_callback(
                            comments_fetched_count,
                            (total_threads_expected +
                             total_replies_expected)
                            if expected_total_confirmed
                            else None,
                            f"返信コメント取得中... ({comments_fetched_count}件)"
                        )

                    reply_page_token = next_reply_page_token
                    if not reply_page_token:
                        break
                    time.sleep(0.1)

                if stop_after_current_thread_page:
                    break

            if comment_threads_completed and thread_items_accounted == len(thread_items):
                expected_total_confirmed = True

            if progress_callback:
                progress_callback(
                    comments_fetched_count,
                    (total_threads_expected +
                     total_replies_expected)
                    if expected_total_confirmed
                    else None,
                    f"コメント取得中... ({comments_fetched_count}件)"
                )

            if stop_after_current_thread_page:
                break

            if not next_page_token:
                logger.info("コメントスレッドと返信コメントの取得を完了しました。")
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
                    logger.info("ユーザーによってコメント取得が中断されました。")
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
                logger.warning(f"{message} (API reason: {api_error_reason})")
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
                logger.warning(f"{message} (API reason: {api_error_reason})")
                record_notification("comment_threads", "warning", "動画を確認できません", message)
            else:
                error_summary = _safe_exception_summary(e)
                message = f"YouTubeコメントスレッド取得中にAPIエラーが発生しました: {error_summary}"
                record_error("comment_threads", message)
                logger.error(message)
                if _get_api_error_reason(e) == "quotaExceeded":
                    logger.critical("APIクォータ制限に達しました。")
                record_notification(
                    "comment_threads", "error", "APIエラー",
                    f"YouTubeコメントスレッド取得中にエラーが発生しました。\n取得済みデータは保存対象に残します。\nエラー概要: {error_summary}",
                )
            break
        except Exception as e:
            error_summary = _safe_exception_summary(e)
            message = f"コメントスレッド取得中に予期せぬエラーが発生しました: {error_summary}"
            record_error("comment_threads", message)
            logger.error(message)
            record_notification(
                "comment_threads", "error", "エラー",
                f"コメントスレッド取得中にエラーが発生しました。\nエラー概要: {error_summary}",
            )
            break

    # 全コメントスレッドのページングが完了した場合に限り、返信見込み数も含む
    # 合計を確定値として返す。途中中断・ページ取得失敗時は未確定(0)とする。
    total_comments_expected = (
        total_threads_expected + total_replies_expected if expected_total_confirmed else 0
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

    logger.info(
        "コメント取得終了: 状態=%s, ユニーク取得数=%d, ユニーク取得見込み=%s, "
        "親コメントRawレコード数=%d, 返信Rawレコード数=%d, "
        "親コメント重複=%d, 返信コメント重複=%d, 返信取得スレッド数=%d",
        result_data["fetch_status"],
        comments_fetched_count,
        total_comments_expected if expected_total_confirmed else "未確定",
        raw_thread_records_count,
        raw_reply_records_count,
        duplicate_parent_count,
        duplicate_reply_count,
        len(result_data["comment_replies_raw_responses"])
    )
    return result_data, comments_fetched_count, total_comments_expected
