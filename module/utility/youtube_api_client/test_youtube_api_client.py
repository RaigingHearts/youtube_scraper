"""Tests for complete comment-reply pagination."""

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


class FetchAllCommentsReplyTests(unittest.TestCase):
    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_fetches_all_reply_pages_and_preserves_raw_responses(self, _show_error, get_service):
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
        self.assertEqual(data["comment_replies_raw_responses"], [{
            "parent_id": "parent-1",
            "raw_responses": [first_reply_page, second_reply_page]
        }])
        self.assertEqual(service.comments.return_value.list.call_count, 2)

    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_thread_without_replies_does_not_call_comments_list(self, _show_error, get_service):
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
        self.assertEqual(data["fetch_status"], "complete")
        service.comments.return_value.list.assert_not_called()

    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_comment_thread_api_failure_without_comments_is_failed(self, _show_error, get_service):
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
        _show_error.assert_called_once()

    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_service_initialization_failure_is_failed(self, _show_error, get_service):
        get_service.return_value = None

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(data["fetch_status"], "failed")
        self.assertEqual(data["errors"][0]["stage"], "service")
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)

    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_empty_comment_result_is_complete(self, _show_error, get_service):
        service = make_service({"pageInfo": {"totalResults": 0}, "items": []}, [])
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(data["fetch_status"], "complete")
        self.assertEqual(data["errors"], [])
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)

    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_missing_channel_metadata_makes_result_partial(self, _show_error, get_service):
        service = make_service(
            {"pageInfo": {"totalResults": 0}, "items": []},
            []
        )
        service.channels.return_value.list.return_value.execute.return_value = {"items": []}
        get_service.return_value = service

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments("key", "video")

        self.assertEqual(data["fetch_status"], "partial")
        self.assertEqual(data["errors"][0]["stage"], "channel_info")
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)

    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_user_declining_continuation_is_cancelled(self, _show_error, get_service):
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
        self.assertEqual(fetched_count, 100)
        self.assertEqual(expected_count, 0)  # 未取得ページが残るため総数は未確定

    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_reply_page_error_keeps_already_fetched_raw_data(self, _show_error, get_service):
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
        _show_error.assert_called_once()


    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_mult_page_thread_estimate_is_cumulative_and_duplicates_are_counted_as_records(
        self, _show_error, get_service
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
            # APIのpageInfo値は合計値として使わず、items件数を累積する
            "pageInfo": {"totalResults": 1},
            "items": [
                {"id": "parent-1", "snippet": {
                    "totalReplyCount": 1, "topLevelComment": {"id": "parent-1"}
                }}
            ]
        }
        service = make_service(first_page, [
            {"items": [{"id": "reply-1"}]},
            {"items": [{"id": "reply-1"}]}
        ])
        service.commentThreads.return_value.list.return_value.execute.side_effect = [
            first_page, second_page
        ]
        get_service.return_value = service
        progress_updates = []

        data, fetched_count, expected_count = youtube_api_client.fetch_all_comments(
            "key", "video",
            progress_callback=lambda current, total, message: progress_updates.append((current, total))
        )

        # 3親レコード + 2返信レコード。重複親・返信もRaw取得レコードとして数える。
        self.assertEqual(fetched_count, 5)
        self.assertEqual(expected_count, 5)
        self.assertEqual(data["fetch_status"], "complete")
        self.assertEqual(len(data["comment_threads_raw_responses"]), 2)
        self.assertEqual(service.comments.return_value.list.call_count, 2)
        self.assertTrue(any(total is None for _, total in progress_updates))
        self.assertEqual(progress_updates[-1][1], 5)

    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_progress_total_remains_unknown_when_user_cancels_before_last_page(
        self, _show_error, get_service
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
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_comments_disabled_error_has_dedicated_status(self, show_error, get_service):
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
        show_error.assert_not_called()

    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_other_forbidden_error_remains_failed(self, show_error, get_service):
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
        show_error.assert_called_once()

    @patch.object(youtube_api_client, "get_youtube_service")
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    @patch.object(youtube_api_client.tk_notifications, "show_warning")
    def test_video_not_found_error_has_actionable_guidance(
        self, show_warning, show_error, get_service
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
        show_warning.assert_called_once()
        show_error.assert_not_called()


class SensitiveErrorLoggingTests(unittest.TestCase):
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
    @patch.object(youtube_api_client.tk_notifications, "show_error")
    def test_http_error_details_are_sanitized_in_result_log_and_notification(
        self, show_error, get_service
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
            + str(show_error.call_args)
        )
        self.assertIn("HTTP status 403", exposed_outputs)
        self.assertIn("API reason forbidden", exposed_outputs)
        self.assertNotIn("secret-api-key", exposed_outputs)
        self.assertNotIn("secret-page-token", exposed_outputs)
        self.assertNotIn("youtube.googleapis.com", exposed_outputs)


if __name__ == "__main__":
    unittest.main()
