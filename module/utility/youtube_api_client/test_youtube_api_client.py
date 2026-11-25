"""Tests for complete comment-reply pagination."""

import json
import unittest
from unittest.mock import MagicMock, patch

from googleapiclient.errors import HttpError

from module.utility.youtube_api_client import youtube_api_client


def make_service(thread_response, reply_responses):
    service = MagicMock()
    service.videos.return_value.list.return_value.execute.return_value = {
        "items": [{"snippet": {"channelId": "channel-1", "title": "Test", "channelTitle": "Uploader"}}]
    }
    service.channels.return_value.list.return_value.execute.return_value = {"items": [{"id": "channel-1"}]}
    service.commentThreads.return_value.list.return_value.execute.return_value = thread_response
    service.comments.return_value.list.return_value.execute.side_effect = reply_responses
    return service


def assert_notification(test_case, data, expected_stage, expected_kind):
    notifications = data["notifications"]
    test_case.assertEqual(len(notifications), 1)
    notification = notifications[0]
    test_case.assertEqual(
        set(notification), {"stage", "kind", "title", "message"}
    )
    test_case.assertEqual(notification["stage"], expected_stage)
    test_case.assertEqual(notification["kind"], expected_kind)
    test_case.assertTrue(notification["title"])
    test_case.assertTrue(notification["message"])


class FetchAllCommentsReplyTests(unittest.TestCase):
    @patch.object(youtube_api_client, "get_youtube_service")
    def test_fetches_all_reply_pages_and_preserves_raw_responses(self, get_service):
        thread_response = {
            "pageInfo": {"totalResults": 1},
            "items": [{
                "id": "parent-1",
                "snippet": {
                    "totalReplyCount": 3,
                    "topLevelComment": {"id": "parent-1"}
                },
                "replies": {"comments": [{"id": "reply-1"}]}
            }]
        }
        first_reply_page = {
            "items": [{"id": "reply-1"}, {"id": "reply-2"}],
            "nextPageToken": "reply-page-2"
        }
        second_reply_page = {"items": [{"id": "reply-3"}]}
        service = make_service(thread_response, [first_reply_page, second_reply_page])
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(fetched_count, 4)
        self.assertEqual(expected_count, 4)
        self.assertEqual(data["comment_threads_raw_responses"], [thread_response])
        self.assertEqual(data["notifications"], [])
        self.assertEqual(data["comment_replies_raw_responses"], [{
            "parent_id": "parent-1",
            "raw_responses": [first_reply_page, second_reply_page]
        }])
        self.assertEqual(service.comments.return_value.list.call_count, 2)

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_thread_without_replies_does_not_call_comments_list(self, get_service):
        thread_response = {
            "pageInfo": {"totalResults": 1},
            "items": [{
                "id": "parent-1",
                "snippet": {
                    "totalReplyCount": 0,
                    "topLevelComment": {"id": "parent-1"}
                }
            }]
        }
        service = make_service(thread_response, [])
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(fetched_count, 1)
        self.assertEqual(expected_count, 1)
        self.assertEqual(data["comment_replies_raw_responses"], [])
        self.assertEqual(data["notifications"], [])
        self.assertEqual(data["fetch_status"], "complete")
        service.comments.return_value.list.assert_not_called()

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_comment_thread_api_failure_without_comments_is_failed(self, get_service):
        service = make_service({"items": []}, [])
        service.commentThreads.return_value.list.return_value.execute.side_effect = RuntimeError(
            "simulated thread API failure"
        )
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(data["fetch_status"], "failed")
        self.assertEqual(data["errors"][0]["stage"], "comment_threads")
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)
        assert_notification(self, data, "comment_threads", "error")

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_service_initialization_failure_is_failed(self, get_service):
        get_service.return_value = None

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(data["fetch_status"], "failed")
        self.assertEqual(data["errors"][0]["stage"], "service")
        assert_notification(self, data, "service", "error")
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_empty_comment_result_is_complete(self, get_service):
        service = make_service({"pageInfo": {"totalResults": 0}, "items": []}, [])
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(data["fetch_status"], "complete")
        self.assertEqual(data["notifications"], [])
        self.assertEqual(data["errors"], [])
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_missing_channel_metadata_makes_result_partial(self, get_service):
        service = make_service(
            {"pageInfo": {"totalResults": 0}, "items": []},
            []
        )
        service.channels.return_value.list.return_value.execute.return_value = {"items": []}
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(data["fetch_status"], "partial")
        self.assertEqual(data["errors"][0]["stage"], "channel_info")
        self.assertEqual(data["notifications"], [])
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_user_declining_continuation_is_cancelled(self, get_service):
        first_page = {
            "pageInfo": {"totalResults": 101},
            "items": [{
                "id": f"parent-{index}",
                "snippet": {"totalReplyCount": 0, "topLevelComment": {"id": f"parent-{index}"}}
            } for index in range(100)],
            "nextPageToken": "page-2"
        }
        service = make_service(first_page, [])
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments(
            "key", "video", confirm_callback=lambda _message: False
        )

        self.assertEqual(data["fetch_status"], "cancelled")
        self.assertEqual(data["notifications"], [])
        self.assertEqual(fetched_count, 100)
        self.assertEqual(expected_count, 0)  # 未取得ページが残るため総数は未確定

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_quota_exceeded_in_comment_threads_has_non_continuable_notification(
        self, get_service
    ):
        service = make_service({"items": []}, [])
        service.commentThreads.return_value.list.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=403),
            content=b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}'
        )
        get_service.return_value = service
        confirm_callback = MagicMock(return_value=True)

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments(
            "key", "video", confirm_callback=confirm_callback
        )

        self.assertEqual(data["fetch_status"], "failed")
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)
        self.assertEqual(data["comment_threads_raw_responses"], [])
        self.assertEqual(len(data["notifications"]), 1)
        notification = data["notifications"][0]
        self.assertEqual(notification["title"], "APIクォータ超過")
        self.assertIn("今回の取得を中断", notification["message"])
        self.assertIn("取得済みのデータは保存対象", notification["message"])
        self.assertIn("再実行", notification["message"])
        confirm_callback.assert_not_called()

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_quota_exceeded_during_reply_fetch_preserves_partial_data(
        self, get_service
    ):
        thread_response = {
            "pageInfo": {"totalResults": 1},
            "items": [{
                "id": "parent-1",
                "snippet": {
                    "totalReplyCount": 1,
                    "topLevelComment": {"id": "parent-1"}
                }
            }]
        }
        service = make_service(thread_response, [])
        service.comments.return_value.list.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=403),
            content=b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}'
        )
        get_service.return_value = service
        confirm_callback = MagicMock(return_value=True)

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments(
            "key", "video", confirm_callback=confirm_callback
        )

        self.assertEqual(data["fetch_status"], "partial")
        self.assertEqual(fetched_count, 1)
        self.assertEqual(expected_count, 2)
        self.assertEqual(data["comment_threads_raw_responses"], [thread_response])
        self.assertEqual(data["comment_replies_raw_responses"], [])
        notification = data["notifications"][0]
        self.assertEqual(notification["stage"], "reply_comments")
        self.assertEqual(notification["title"], "APIクォータ超過")
        self.assertIn("今回の取得を中断", notification["message"])
        self.assertIn("取得済みのデータは保存対象", notification["message"])
        confirm_callback.assert_not_called()

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_reply_page_error_keeps_already_fetched_raw_data(self, get_service):
        thread_response = {
            "pageInfo": {"totalResults": 1},
            "items": [{
                "id": "parent-1",
                "snippet": {
                    "totalReplyCount": 2,
                    "topLevelComment": {"id": "parent-1"}
                }
            }]
        }
        first_reply_page = {
            "items": [{"id": "reply-1"}],
            "nextPageToken": "reply-page-2"
        }
        service = make_service(thread_response, [first_reply_page, RuntimeError("simulated API failure")])
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(fetched_count, 2)
        self.assertEqual(expected_count, 3)
        self.assertEqual(data["comment_replies_raw_responses"][0]["raw_responses"], [first_reply_page])
        self.assertEqual(data["fetch_status"], "partial")
        self.assertEqual(data["errors"][0]["stage"], "reply_comments")
        assert_notification(self, data, "reply_comments", "error")


    @patch.object(youtube_api_client, "get_youtube_service")
    def test_duplicate_parent_thread_is_preserved_raw_but_reply_fetch_is_deduplicated(
        self, get_service
    ):
        first_page = {
            "pageInfo": {"totalResults": 2},
            "items": [
                {"id": "parent-1", "snippet": {
                    "totalReplyCount": 1, "topLevelComment": {"id": "parent-1"}
                }},
                {"id": "parent-2", "snippet": {
                    "totalReplyCount": 0, "topLevelComment": {"id": "parent-2"}
                }}
            ],
            "nextPageToken": "page-2"
        }
        second_page = {
            "pageInfo": {"totalResults": 1},
            "items": [
                {"id": "parent-1", "snippet": {
                    "totalReplyCount": 1, "topLevelComment": {"id": "parent-1"}
                }}
            ]
        }
        reply_page = {"items": [{"id": "reply-1"}]}
        service = make_service(first_page, [reply_page])
        service.commentThreads.return_value.list.return_value.execute.side_effect = [
            first_page, second_page
        ]
        get_service.return_value = service
        progress_updates = []

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments(
            "key", "video",
            progress_callback=lambda current, total, message: progress_updates.append((current, total))
        )

        # ユニーク親2件 + ユニーク返信1件。Raw親スレッドは両ページ分を保持する。
        self.assertEqual(fetched_count, 3)
        self.assertEqual(expected_count, 3)
        self.assertEqual(data["fetch_status"], "complete")
        self.assertEqual(len(data["comment_threads_raw_responses"]), 2)
        self.assertEqual(
            data["comment_replies_raw_responses"],
            [{"parent_id": "parent-1", "raw_responses": [reply_page]}]
        )
        self.assertEqual(service.comments.return_value.list.call_count, 1)
        self.assertTrue(any(total is None for _, total in progress_updates))
        self.assertEqual(progress_updates[-1][1], 3)

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_duplicate_reply_ids_are_counted_once_and_raw_pages_are_preserved(
        self, get_service
    ):
        thread_response = {
            "items": [{
                "id": "parent-1",
                "snippet": {
                    "totalReplyCount": 2,
                    "topLevelComment": {"id": "parent-1"}
                }
            }]
        }
        first_reply_page = {
            "items": [{"id": "reply-1"}],
            "nextPageToken": "reply-page-2"
        }
        second_reply_page = {
            "items": [{"id": "reply-1"}, {"id": "reply-2"}]
        }
        service = make_service(thread_response, [first_reply_page, second_reply_page])
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(fetched_count, 3)
        self.assertEqual(expected_count, 3)
        self.assertEqual(
            data["comment_replies_raw_responses"],
            [{
                "parent_id": "parent-1",
                "raw_responses": [first_reply_page, second_reply_page]
            }]
        )
        self.assertEqual(service.comments.return_value.list.call_count, 2)

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_progress_total_remains_unknown_when_user_cancels_before_last_page(
        self, get_service
    ):
        first_page = {
            "pageInfo": {"totalResults": 100},
            "items": [{
                "id": f"parent-{index}",
                "snippet": {"totalReplyCount": 0, "topLevelComment": {"id": f"parent-{index}"}}
            } for index in range(100)],
            "nextPageToken": "page-2"
        }
        service = make_service(first_page, [])
        get_service.return_value = service
        progress_updates = []

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments(
            "key", "video",
            progress_callback=lambda current, total, message: progress_updates.append((current, total)),
            confirm_callback=lambda _message: False
        )

        self.assertEqual(data["fetch_status"], "cancelled")
        self.assertEqual(fetched_count, 100)
        self.assertEqual(expected_count, 0)
        self.assertTrue(progress_updates)
        self.assertIsNone(progress_updates[-1][1])




    @patch.object(youtube_api_client, "get_youtube_service")
    def test_comments_disabled_error_has_dedicated_status(self, get_service):
        service = make_service({"items": []}, [])
        service.commentThreads.return_value.list.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=403),
            content=b'{"error":{"errors":[{"reason":"commentsDisabled"}]}}'
        )
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(data["fetch_status"], "comments_disabled")
        self.assertEqual(data["errors"][0]["reason"], "commentsDisabled")
        self.assertEqual(data["errors"][0]["stage"], "comment_threads")
        self.assertTrue(data["video_info_raw_response"]["items"])
        self.assertTrue(data["channel_info_raw_response"]["items"])
        self.assertEqual(data["comment_threads_raw_responses"], [])
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)
        self.assertEqual(data["notifications"], [])

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_other_forbidden_error_remains_failed(self, get_service):
        service = make_service({"items": []}, [])
        service.commentThreads.return_value.list.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=403),
            content=b'{"error":{"errors":[{"reason":"forbidden"}]}}'
        )
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(data["fetch_status"], "failed")
        self.assertNotEqual(data["fetch_status"], "comments_disabled")
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)
        assert_notification(self, data, "comment_threads", "error")

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_video_not_found_error_has_actionable_guidance(
        self, get_service
    ):
        service = make_service({"items": []}, [])
        service.videos.return_value.list.return_value.execute.return_value = {"items": []}
        service.commentThreads.return_value.list.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=404),
            content=b'{"error":{"errors":[{"reason":"videoNotFound"}]}}'
        )
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(data["fetch_status"], "failed")
        self.assertEqual(data["errors"][-1]["stage"], "comment_threads")
        self.assertEqual(data["errors"][-1]["reason"], "videoNotFound")
        self.assertIn("動画の削除", data["errors"][-1]["message"])
        self.assertIn("URLや動画IDの間違い", data["errors"][-1]["message"])
        self.assertIn("非公開設定", data["errors"][-1]["message"])
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)
        assert_notification(self, data, "comment_threads", "warning")

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_progress_total_is_confirmed_only_after_last_thread_is_processed(
        self, get_service
    ):
        thread_response = {
            "items": [
                {
                    "id": "parent-1",
                    "snippet": {
                        "totalReplyCount": 1,
                        "topLevelComment": {"id": "parent-1"}
                    }
                },
                {
                    "id": "parent-2",
                    "snippet": {
                        "totalReplyCount": 0,
                        "topLevelComment": {"id": "parent-2"}
                    }
                }
            ]
        }
        reply_page = {"items": [{"id": "reply-1"}]}
        service = make_service(thread_response, [reply_page])
        get_service.return_value = service
        progress_updates = []

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments(
            "key",
            "video",
            progress_callback=lambda current, total, message: (
                progress_updates.append((current, total))
            )
        )

        self.assertEqual(data["fetch_status"], "complete")
        self.assertEqual(fetched_count, 3)
        self.assertEqual(expected_count, 3)

        # 最初の親コメントの返信取得中は、2件目の親コメントが未集計。
        self.assertEqual(progress_updates[0], (2, None))

        # 最終スレッドの処理終了後に総数が確定する。
        self.assertEqual(progress_updates[-1], (3, 3))


    @patch.object(youtube_api_client, "get_youtube_service")
    def test_expected_total_remains_unknown_when_reply_error_skips_later_threads(
        self, get_service
    ):
        thread_response = {
            "items": [
                {
                    "id": "parent-1",
                    "snippet": {
                        "totalReplyCount": 1,
                        "topLevelComment": {"id": "parent-1"}
                    }
                },
                {
                    "id": "parent-2",
                    "snippet": {
                        "totalReplyCount": 0,
                        "topLevelComment": {"id": "parent-2"}
                    }
                }
            ]
        }
        service = make_service(thread_response, [RuntimeError("simulated reply failure")])
        get_service.return_value = service
        progress_updates = []

        with self.assertLogs(youtube_api_client.logger, level="INFO") as captured:
            data, fetched_count, expected_count = youtube_api_client.fetch_all_comments(
                "key",
                "video",
                progress_callback=lambda current, total, message: (
                    progress_updates.append((current, total))
                )
            )

        self.assertEqual(data["fetch_status"], "partial")
        self.assertEqual(fetched_count, 1)
        self.assertEqual(expected_count, 0)
        self.assertEqual(progress_updates[-1], (1, None))
        self.assertIn("ユニーク取得見込み=未確定", "\n".join(captured.output))
        assert_notification(self, data, "reply_comments", "error")

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_expected_total_is_confirmed_when_reply_error_occurs_on_last_thread(
        self, get_service
    ):
        thread_response = {
            "items": [
                {
                    "id": "parent-1",
                    "snippet": {
                        "totalReplyCount": 0,
                        "topLevelComment": {"id": "parent-1"}
                    }
                },
                {
                    "id": "parent-2",
                    "snippet": {
                        "totalReplyCount": 1,
                        "topLevelComment": {"id": "parent-2"}
                    }
                }
            ]
        }
        service = make_service(thread_response, [RuntimeError("simulated reply failure")])
        get_service.return_value = service
        progress_updates = []

        with self.assertLogs(youtube_api_client.logger, level="INFO") as captured:
            data, fetched_count, expected_count = youtube_api_client.fetch_all_comments(
                "key",
                "video",
                progress_callback=lambda current, total, message: (
                    progress_updates.append((current, total))
                )
            )

        self.assertEqual(data["fetch_status"], "partial")
        self.assertEqual(fetched_count, 2)
        self.assertEqual(expected_count, 3)
        self.assertEqual(progress_updates[-1], (2, 3))
        self.assertIn("ユニーク取得見込み=3", "\n".join(captured.output))
        assert_notification(self, data, "reply_comments", "error")


class SensitiveErrorLoggingTests(unittest.TestCase):
    def test_api_error_reason_parser_handles_unexpected_json_shapes(self):
        malformed_payloads = [
            [],
            {"error": None},
            {"error": []},
            {"error": {"errors": None}},
            {"error": {"errors": {}}},
            {"error": {"errors": [None, "not-an-object", {"reason": 403}]}},
        ]

        for payload in malformed_payloads:
            with self.subTest(payload=payload):
                error = HttpError(
                    resp=MagicMock(status=403),
                    content=json.dumps(payload).encode("utf-8")
                )
                self.assertIsNone(youtube_api_client._get_api_error_reason(error))

    def test_api_error_reason_parser_skips_invalid_entries_and_returns_string_reason(self):
        error = HttpError(
            resp=MagicMock(status=403),
            content=(
                b'{"error":{"errors":[null,"invalid",'
                b'{"reason":403},{"reason":"quotaExceeded"}]}}'
            )
        )

        self.assertEqual(
            youtube_api_client._get_api_error_reason(error),
            "quotaExceeded"
        )

    def test_safe_exception_summary_omits_request_uri_and_secrets(self):
        error = HttpError(
            resp=MagicMock(status=403),
            content=b'{"error":{"errors":[{"reason":"forbidden"}]}}',
            uri=(
                "https://youtube.googleapis.com/youtube/v3/commentThreads"
                "?key=secret-api-key&pageToken=secret-page-token"
            )
        )

        summary = youtube_api_client._safe_exception_summary(error)

        self.assertIn("HttpError", summary)
        self.assertIn("HTTP status 403", summary)
        self.assertIn("API reason forbidden", summary)
        self.assertNotIn("secret-api-key", summary)
        self.assertNotIn("secret-page-token", summary)
        self.assertNotIn("youtube.googleapis.com", summary)

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_http_error_details_are_sanitized_in_result_log_and_notification(
        self, get_service
    ):
        service = make_service({"items": []}, [])
        service.commentThreads.return_value.list.return_value.execute.side_effect = HttpError(
            resp=MagicMock(status=403),
            content=b'{"error":{"errors":[{"reason":"forbidden"}]}}',
            uri=(
                "https://youtube.googleapis.com/youtube/v3/commentThreads"
                "?key=secret-api-key&pageToken=secret-page-token"
            )
        )
        get_service.return_value = service

        with self.assertLogs(youtube_api_client.logger, level="ERROR") as captured:
            data, _, _ = youtube_api_client.fetch_all_comments("key", "video")

        exposed_outputs = (
            str(data["errors"])
            + "\n".join(captured.output)
            + str(data["notifications"])
        )
        self.assertIn("HTTP status 403", exposed_outputs)
        self.assertIn("API reason forbidden", exposed_outputs)
        self.assertNotIn("secret-api-key", exposed_outputs)
        self.assertNotIn("secret-page-token", exposed_outputs)
        self.assertNotIn("youtube.googleapis.com", exposed_outputs)
        assert_notification(self, data, "comment_threads", "error")


if __name__ == "__main__":
    unittest.main()
