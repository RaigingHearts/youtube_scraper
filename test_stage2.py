"""Stage 2専用テスト：進捗・通知・取得結果・保存結果の受け渡し。"""

import ast
import inspect
import queue
import threading
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import main
from module.utility.tk_async_tasks import tk_async_tasks


def make_app(master=None):
    """GUIを構築せず、Stage 2のワーカー／GUI連携に必要な状態だけを用意する。"""
    app = main.YouTubeCommentScraperApp.__new__(
        main.YouTubeCommentScraperApp
    )
    app.master = master if master is not None else MagicMock()
    app.api_key = "stage2-test-api-key"
    app.gui_request_queue = queue.Queue()
    app.worker_handle = None
    app._gui_poll_after_id = None
    app._dialog_active = False
    app._pending_modal_requests = []
    app._processing_pending_modal_requests = False
    app._shutdown_state = "running"
    app._shutdown_requested = False
    app._shutdown_notifications = []
    app._shutdown_summary_shown = False
    app.progress_label = MagicMock()
    app.progress_bar = MagicMock()
    app.progress_bar.__getitem__.return_value = 100
    app.comment_count_label = MagicMock()
    app.scrape_button = MagicMock()
    app.open_json_button = MagicMock()
    app.video_id_entry = MagicMock()
    app.video_id_entry.get.return_value = "abcdefghijk"
    app.last_saved_comment_file_path = None
    app.last_saved_video_info_file_path = None
    app.last_saved_channel_info_file_path = None
    app.last_saved_replies_file_path = None
    app.total_comments_expected = 0
    return app


def make_fetch_result(
    fetch_status="failed",
    notifications=None,
    errors=None,
    video_info=None,
    channel_info=None,
    comments=None,
    replies=None,
):
    return {
        "fetch_status": fetch_status,
        "notifications": list(notifications or []),
        "errors": list(errors or []),
        "video_info_raw_response": video_info or {},
        "channel_info_raw_response": channel_info or {},
        "comment_threads_raw_responses": list(comments or []),
        "comment_replies_raw_responses": list(replies or []),
    }


class ScrapeTaskProgressAndNotificationTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.handle = tk_async_tasks.WorkerHandle(self.app.gui_request_queue)

    def run_task_with_result(self, fetch_result, fetched_count=3, total_expected=9):
        with patch.object(
            main.youtube_api_client,
            "fetch_all_comments",
            return_value=(fetch_result, fetched_count, total_expected),
        ):
            return self.app._scrape_comments_task(self.handle, "abcdefghijk")

    def test_progress_updates_are_published_and_coalesced_without_tk_payload(self):
        fetch_result = make_fetch_result()

        def fetch(_api_key, _video_id, progress_callback, **_kwargs):
            progress_callback(1, 8, "first")
            progress_callback(4, 8, "middle")
            progress_callback(7, 8, "latest")
            return fetch_result, 7, 8

        with patch.object(main.youtube_api_client, "fetch_all_comments", side_effect=fetch):
            result = self.app._scrape_comments_task(self.handle, "abcdefghijk")

        self.assertEqual(result["fetched_count"], 7)
        self.assertEqual(self.app.gui_request_queue.qsize(), 1)
        request = self.app.gui_request_queue.get_nowait()
        self.assertEqual(request.kind, "progress")
        self.assertEqual(request.payload, {})
        self.assertEqual(
            self.handle.take_latest_progress(),
            {
                "current_comments": 7,
                "total_comments": 8,
                "message": "latest",
            },
        )

    def test_api_notifications_are_forwarded_once_without_replaying_errors(self):
        notices = [
            {"kind": "warning", "title": "API warning", "message": "notice one"},
            {"kind": "error", "title": "API error", "message": "notice two"},
        ]
        errors = [
            {"stage": "video_info", "message": "same event one"},
            {"stage": "comments", "message": "same event two"},
        ]
        self.run_task_with_result(
            make_fetch_result(notifications=notices, errors=errors)
        )

        requests = list(self.app.gui_request_queue.queue)
        self.assertEqual([request.kind for request in requests], [
            "notification", "notification"
        ])
        self.assertEqual(
            [request.payload for request in requests],
            [
                {"kind": "warning", "title": "API warning", "message": "notice one"},
                {"kind": "error", "title": "API error", "message": "notice two"},
            ],
        )

    def test_fetch_errors_without_api_notifications_are_not_reissued(self):
        fetch_result = make_fetch_result(
            errors=[{"stage": "service", "message": "API service failed"}]
        )
        self.run_task_with_result(fetch_result)
        self.assertTrue(self.app.gui_request_queue.empty())

    def test_task_specific_notification_is_added_after_api_notifications(self):
        fetch_result = make_fetch_result(
            fetch_status="complete",
            notifications=[
                {"kind": "warning", "title": "API notice", "message": "API detail"}
            ],
        )
        self.run_task_with_result(fetch_result)

        requests = list(self.app.gui_request_queue.queue)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].payload["title"], "API notice")
        self.assertEqual(requests[1].payload["title"], "取得完了")
        self.assertEqual(requests[1].payload["kind"], "info")

    def test_cancel_reason_is_copied_into_cancelled_fetch_result(self):
        self.handle.cancel_reason = "continuation_declined"
        result = self.run_task_with_result(
            make_fetch_result(fetch_status="cancelled")
        )
        self.assertEqual(
            result["fetch_result"]["cancel_reason"], "continuation_declined"
        )

    def test_scrape_task_source_has_no_direct_tk_or_gui_access(self):
        source = inspect.getsource(
            main.YouTubeCommentScraperApp._scrape_comments_task
        )
        tree = ast.parse(source)
        self.assertNotIn("tk_notifications", source)
        self.assertNotIn("wait_variable", source)
        self.assertNotIn("BooleanVar", source)
        self.assertNotIn(".after(", source)
        self.assertNotIn(".config(", source)

        self_attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }
        self.assertEqual(self_attributes, {"api_key"})


class ScrapeTaskSaveResultTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.handle = tk_async_tasks.WorkerHandle(self.app.gui_request_queue)
        self.fetch_result = make_fetch_result(
            fetch_status="partial",
            video_info={"items": [{"id": "video"}]},
            channel_info={"items": [{"id": "channel-123"}]},
            comments=[{"items": [{"id": "comment"}]}],
            replies=[{"items": [{"id": "reply"}]}],
        )

    def run_task(self, save_side_effect=True):
        with patch.object(
            main.youtube_api_client,
            "fetch_all_comments",
            return_value=(self.fetch_result, 2, 5),
        ):
            with patch.object(
                main.json_data_handler,
                "save_json_to_file",
                side_effect=save_side_effect,
            ) as save_file:
                result = self.app._scrape_comments_task(
                    self.handle, "abcdefghijk"
                )
        return result, save_file

    def test_result_contains_required_fields_and_all_saved_file_kinds(self):
        result, save_file = self.run_task(True)

        self.assertEqual(
            set(result.keys()),
            {
                "fetch_result",
                "fetched_count",
                "total_expected",
                "saved_files",
                "output_folder_name",
            },
        )
        self.assertEqual(result["fetched_count"], 2)
        self.assertEqual(result["total_expected"], 5)
        self.assertEqual(
            [record["kind"] for record in result["saved_files"]],
            ["video_info", "channel_info", "comments", "replies"],
        )
        self.assertTrue(all(record["success"] for record in result["saved_files"]))
        self.assertTrue(
            all(record["path"].endswith(".json") for record in result["saved_files"])
        )
        self.assertEqual(save_file.call_count, 4)
        self.assertEqual(
            self.handle.partial_result["saved_files"], result["saved_files"]
        )

    def test_save_failure_is_recorded_and_later_files_are_attempted(self):
        result, save_file = self.run_task([False, True, False, True])

        self.assertEqual(save_file.call_count, 4)
        self.assertEqual(
            [record["success"] for record in result["saved_files"]],
            [False, True, False, True],
        )
        self.assertEqual(
            [record["kind"] for record in result["saved_files"]],
            ["video_info", "channel_info", "comments", "replies"],
        )
        self.assertEqual(
            self.handle.partial_result["saved_files"], result["saved_files"]
        )

    def test_save_exception_is_recorded_and_later_files_are_attempted(self):
        result, save_file = self.run_task(
            [
                RuntimeError("disk unavailable"),
                True,
                RuntimeError("permission denied"),
                True,
            ]
        )

        self.assertEqual(save_file.call_count, 4)
        self.assertEqual(
            [record["success"] for record in result["saved_files"]],
            [False, True, False, True],
        )
        self.assertIn("RuntimeError: disk unavailable", result["saved_files"][0]["error"])
        self.assertIn("RuntimeError: permission denied", result["saved_files"][2]["error"])

    def test_partial_result_is_updated_immediately_after_each_save_attempt(self):
        snapshots = []

        def save_and_snapshot(*_args, **_kwargs):
            snapshots.append(
                list(self.handle.partial_result["saved_files"])
            )
            return True

        with patch.object(
            main.youtube_api_client,
            "fetch_all_comments",
            return_value=(self.fetch_result, 2, 5),
        ):
            with patch.object(
                main.json_data_handler,
                "save_json_to_file",
                side_effect=save_and_snapshot,
            ):
                result = self.app._scrape_comments_task(
                    self.handle, "abcdefghijk"
                )

        self.assertEqual(len(snapshots), 4)
        self.assertEqual([len(snapshot) for snapshot in snapshots], [0, 1, 2, 3])
        self.assertEqual(
            len(self.handle.partial_result["saved_files"]), 4
        )
        self.assertEqual(
            self.handle.partial_result["saved_files"], result["saved_files"]
        )

    def test_unexpected_exception_after_save_keeps_partial_result(self):
        fetch_result = make_fetch_result(
            fetch_status="complete",
            video_info={"items": [{"id": "video"}]},
        )
        with patch.object(
            main.youtube_api_client,
            "fetch_all_comments",
            return_value=(fetch_result, 0, 0),
        ):
            with patch.object(
                main.json_data_handler, "save_json_to_file", return_value=True
            ):
                with patch.object(
                    self.handle.gui_request_queue,
                    "put",
                    side_effect=RuntimeError("queue unavailable"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
                        self.app._scrape_comments_task(
                            self.handle, "abcdefghijk"
                        )

        self.assertEqual(len(self.handle.partial_result["saved_files"]), 1)
        record = self.handle.partial_result["saved_files"][0]
        self.assertEqual(record["kind"], "video_info")
        self.assertTrue(record["success"])
        self.assertTrue(record["path"].endswith("video_info_raw_abcdefghijk.json"))


class Stage2GuiHandoffTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.main_thread_id = threading.get_ident()

    def make_finished_handle(self, result=None, exception=None, partial_result=None):
        handle = tk_async_tasks.WorkerHandle(self.app.gui_request_queue)
        handle.result = result
        handle.exception = exception
        if partial_result is not None:
            handle.partial_result = partial_result
        handle.done_event.set()
        self.app.worker_handle = handle
        return handle

    def test_progress_request_updates_gui_on_main_thread(self):
        handle = tk_async_tasks.WorkerHandle(self.app.gui_request_queue)
        handle.publish_progress(
            {
                "current_comments": 6,
                "total_comments": 12,
                "message": "progress update",
            }
        )
        self.app.worker_handle = handle
        request = self.app.gui_request_queue.get_nowait()
        observed = []

        with patch.object(
            main.tk_async_tasks,
            "_perform_gui_update",
            side_effect=lambda *_args: observed.append(threading.get_ident()),
        ):
            self.app._handle_gui_request(request)

        self.assertEqual(observed, [self.main_thread_id])
        self.app.comment_count_label.config.assert_called_once_with(
            text="取得コメント数: 6 / 12"
        )

    def test_finish_worker_restores_only_successful_saved_paths(self):
        result = {
            "fetched_count": 4,
            "total_expected": 9,
            "saved_files": [
                {"kind": "video_info", "path": "video.json", "success": True},
                {"kind": "channel_info", "path": "channel.json", "success": False},
                {"kind": "comments", "path": "comments.json", "success": True},
                {"kind": "replies", "path": "replies.json", "success": False},
            ],
        }
        handle = self.make_finished_handle(result=result)

        self.app._finish_worker(handle)

        self.assertEqual(self.app.last_saved_video_info_file_path, "video.json")
        self.assertIsNone(self.app.last_saved_channel_info_file_path)
        self.assertEqual(self.app.last_saved_comment_file_path, "comments.json")
        self.assertIsNone(self.app.last_saved_replies_file_path)
        self.app.open_json_button.config.assert_called_once_with(state=tk.NORMAL)
        self.app.scrape_button.config.assert_called_once_with(state=tk.NORMAL)
        self.app.comment_count_label.config.assert_called_once_with(
            text="取得コメント数: 4 / 9"
        )
        self.assertIsNone(self.app.worker_handle)

    def test_finish_worker_recovers_partial_saved_paths_after_exception(self):
        handle = self.make_finished_handle(
            exception=RuntimeError("worker failed"),
            partial_result={
                "saved_files": [
                    {"kind": "comments", "path": "partial-comments.json", "success": True},
                    {"kind": "replies", "path": "failed-replies.json", "success": False},
                ]
            },
        )
        with self.assertLogs(main.logger, level="ERROR"):
            self.app._finish_worker(handle)

        # 例外通知はGUI要求キューへ送られる。通知処理後に結果回収を再開する。
        request = self.app.gui_request_queue.get_nowait()
        self.assertEqual(request.kind, "notification")
        self.assertEqual(request.payload["title"], "取得失敗")
        self.app._finish_worker(handle)

        self.assertEqual(
            self.app.last_saved_comment_file_path, "partial-comments.json"
        )
        self.assertIsNone(self.app.last_saved_replies_file_path)
        self.app.open_json_button.config.assert_called_with(state=tk.NORMAL)
        self.assertIsNone(self.app.worker_handle)

    def test_finish_worker_disables_open_button_when_no_successful_file_exists(self):
        handle = self.make_finished_handle(
            result={
                "saved_files": [
                    {"kind": "comments", "path": "not-saved.json", "success": False}
                ]
            }
        )
        self.app._finish_worker(handle)
        self.app.open_json_button.config.assert_called_once_with(state=tk.DISABLED)


class Stage2NotificationOrderingTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app()

    def test_modal_requests_are_deferred_and_drained_in_fifo_order(self):
        first = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "first", "message": "1"},
        )
        second = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "warning", "title": "second", "message": "2"},
        )
        self.app._dialog_active = True
        self.app._handle_gui_request(first)
        self.app._handle_gui_request(second)

        self.assertEqual(self.app._pending_modal_requests, [first, second])
        calls = []
        self.app._dialog_active = False
        with patch.object(
            main.tk_notifications,
            "show_info",
            side_effect=lambda title, *_args, **_kwargs: calls.append(title),
        ):
            with patch.object(
                main.tk_notifications,
                "show_warning",
                side_effect=lambda title, *_args, **_kwargs: calls.append(title),
            ):
                self.app._drain_pending_modal_requests()

        self.assertEqual(calls, ["first", "second"])
        self.assertEqual(self.app._pending_modal_requests, [])

    def test_notification_failure_does_not_block_later_fifo_notifications(self):
        first = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "first", "message": "1"},
        )
        second = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "second", "message": "2"},
        )
        self.app._pending_modal_requests = [first, second]
        shown = []

        call_count = {"value": 0}

        def show_notice(title, *_args, **_kwargs):
            call_count["value"] += 1
            if call_count["value"] == 1:
                raise RuntimeError("first dialog failed")
            shown.append(title)

        with self.assertLogs(main.logger, level="ERROR"):
            with patch.object(
                main.tk_notifications,
                "show_info",
                side_effect=show_notice,
            ) as show_info:
                self.app._drain_pending_modal_requests()

        self.assertEqual(show_info.call_count, 2)
        self.assertEqual(shown, ["second"])
        self.assertEqual(self.app._pending_modal_requests, [])


class Stage2RealEventLoopIntegrationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest("Tk display is unavailable: {}".format(exc))
        self.root.withdraw()
        self.app = make_app(self.root)
        self.main_thread_id = threading.get_ident()

    def tearDown(self):
        if getattr(self, "root", None) is not None:
            try:
                self.root.destroy()
            except tk.TclError:
                pass

    def run_event_loop_until(self, predicate, timeout_ms=5000):
        state = {"finished": False, "timed_out": False}

        def check():
            if predicate():
                state["finished"] = True
                self.root.quit()
                return
            self.root.after(10, check)

        def timeout():
            state["timed_out"] = True
            self.root.quit()

        check_id = self.root.after(0, check)
        timeout_id = self.root.after(timeout_ms, timeout)
        self.root.mainloop()

        for after_id in (check_id, timeout_id, self.app._gui_poll_after_id):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        self.app._gui_poll_after_id = None
        self.assertTrue(state["finished"], "Tk event loop did not reach completion")
        self.assertFalse(state["timed_out"], "Tk event loop timed out")

    def test_real_worker_progress_notifications_and_saved_results_reach_gui(self):
        progress_thread_ids = []
        notification_thread_ids = []
        task_started = threading.Event()
        start_returned = threading.Event()

        fetch_result = make_fetch_result(
            fetch_status="complete",
            notifications=[
                {"kind": "warning", "title": "API notice", "message": "API detail"}
            ],
            video_info={"items": [{"id": "video"}]},
            comments=[{"items": [{"id": "comment"}]}],
        )

        def fake_fetch(_api_key, _video_id, progress_callback, **_kwargs):
            task_started.set()
            progress_callback(3, 8, "worker progress")
            return fetch_result, 3, 8

        self.app._schedule_gui_request_polling()
        with patch.object(
            main.youtube_utils, "is_valid_video_id", return_value=True
        ):
            with patch.object(
                main.youtube_api_client,
                "fetch_all_comments",
                side_effect=fake_fetch,
            ):
                with patch.object(
                    main.json_data_handler, "save_json_to_file", return_value=True
                ) as save_file:
                    with patch.object(
                        main.tk_async_tasks,
                        "_perform_gui_update",
                        side_effect=lambda *_args: progress_thread_ids.append(
                            threading.get_ident()
                        ),
                    ):
                        with patch.object(
                            main.tk_notifications,
                            "show_warning",
                            side_effect=lambda *_args, **_kwargs: notification_thread_ids.append(
                                threading.get_ident()
                            ),
                        ):
                            with patch.object(
                                main.tk_notifications,
                                "show_info",
                                side_effect=lambda *_args, **_kwargs: notification_thread_ids.append(
                                    threading.get_ident()
                                ),
                            ):
                                def start_scrape():
                                    self.app._start_scrape_process()
                                    start_returned.set()

                                self.root.after(0, start_scrape)
                                self.run_event_loop_until(
                                    lambda: start_returned.is_set()
                                    and task_started.is_set()
                                    and self.app.worker_handle is None
                                )

        self.assertEqual(save_file.call_count, 2)
        self.assertEqual(
            progress_thread_ids,
            [self.main_thread_id, self.main_thread_id, self.main_thread_id],
        )
        self.assertEqual(
            notification_thread_ids,
            [self.main_thread_id, self.main_thread_id],
        )
        self.assertEqual(
            self.app.last_saved_video_info_file_path is not None, True
        )
        self.assertEqual(
            self.app.last_saved_comment_file_path is not None, True
        )
        self.assertEqual(self.app.total_comments_expected, 8)
        self.assertTrue(self.app.gui_request_queue.empty())


if __name__ == "__main__":
    unittest.main()
