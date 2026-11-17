"""Tests for complete comment-reply pagination."""

import unittest
from unittest.mock import MagicMock, patch

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
        service.comments.return_value.list.assert_not_called()

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
        _show_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
