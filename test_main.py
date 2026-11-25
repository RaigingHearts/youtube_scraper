"""main.py のGUI要求キュー・ワーカー管理のテスト。

GUI不要の単体テストを中心に、Tkイベントループを使う統合テストも含める。
YouTube API通信・ファイル保存・モーダル表示は実行しない。
"""
import queue
import threading
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import main
from module.utility.tk_async_tasks import tk_async_tasks


class YouTubeCommentScraperAppTestCase(unittest.TestCase):
    def make_app(self):
        app = main.YouTubeCommentScraperApp.__new__(
            main.YouTubeCommentScraperApp
        )
        app.master = MagicMock()
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
        app.last_saved_comment_file_path = None
        app.last_saved_video_info_file_path = None
        app.last_saved_channel_info_file_path = None
        app.last_saved_replies_file_path = None
        app.total_comments_expected = 0
        return app


class ApplicationLifecycleTests(YouTubeCommentScraperAppTestCase):
    def test_finalize_shutdown_quits_mainloop_without_destroying_root(self):
        app = self.make_app()

        app._finalize_shutdown()

        self.assertEqual(app._shutdown_state, "closed")
        app.master.quit.assert_called_once_with()
        app.master.destroy.assert_not_called()

    def test_main_destroys_root_after_mainloop_raises(self):
        root = MagicMock()
        root.mainloop.side_effect = RuntimeError("mainloop failed")

        with patch.object(main.logger_config, "configure_logging"):
            with patch.object(main.settings_manager, "initialize_settings"):
                with patch.object(main.tk, "Tk", return_value=root):
                    with patch.object(main, "YouTubeCommentScraperApp"):
                        with self.assertRaisesRegex(RuntimeError, "mainloop failed"):
                            main.main()

        root.mainloop.assert_called_once_with()
        root.destroy.assert_called_once_with()


class GuiPollingTests(YouTubeCommentScraperAppTestCase):
    def test_initial_poll_is_scheduled_after_50ms(self):
        app = self.make_app()
        app._schedule_gui_request_polling()
        app.master.after.assert_called_once_with(50, app._poll_gui_requests)
        self.assertEqual(app._gui_poll_after_id, app.master.after.return_value)

    def test_empty_queue_still_reschedules_polling(self):
        app = self.make_app()
        app._poll_gui_requests()
        self.assertTrue(app.gui_request_queue.empty())
        app.master.after.assert_called_once_with(50, app._poll_gui_requests)

    def test_polling_is_not_scheduled_twice(self):
        app = self.make_app()
        app._gui_poll_after_id = "already-scheduled"
        app._schedule_gui_request_polling()
        app.master.after.assert_not_called()
        self.assertEqual(app._gui_poll_after_id, "already-scheduled")

    def test_polling_after_destroyed_root_catches_tcl_error(self):
        app = self.make_app()
        app.master.after.side_effect = tk.TclError("root destroyed")
        app._schedule_gui_request_polling()
        self.assertIsNone(app._gui_poll_after_id)

    def test_poll_processes_at_most_50_requests_and_reschedules(self):
        app = self.make_app()
        for _ in range(55):
            app.gui_request_queue.put(tk_async_tasks.GuiRequest(kind="unknown"))
        with patch.object(app, "_handle_gui_request") as handle_request:
            app._poll_gui_requests()
        self.assertEqual(handle_request.call_count, 50)
        self.assertEqual(app.gui_request_queue.qsize(), 5)
        app.master.after.assert_called_once_with(50, app._poll_gui_requests)

    def test_poll_continues_after_request_handler_raises(self):
        app = self.make_app()
        first = tk_async_tasks.GuiRequest(kind="first")
        second = tk_async_tasks.GuiRequest(kind="second")
        app.gui_request_queue.put(first)
        app.gui_request_queue.put(second)

        def handle(request):
            if request is first:
                raise RuntimeError("request failed")

        with patch.object(app, "_handle_gui_request", side_effect=handle) as mocked:
            app._poll_gui_requests()
        self.assertEqual(mocked.call_count, 2)
        self.assertTrue(app.gui_request_queue.empty())
        app.master.after.assert_called_once_with(50, app._poll_gui_requests)

    def test_poll_logs_and_continues_after_invalid_object(self):
        app = self.make_app()
        app.gui_request_queue.put(object())
        app.gui_request_queue.put(tk_async_tasks.GuiRequest(kind="unknown"))
        with self.assertLogs(main.logger, level="WARNING"):
            app._poll_gui_requests()
        self.assertTrue(app.gui_request_queue.empty())
        app.master.after.assert_called_once_with(50, app._poll_gui_requests)

    def test_progress_request_updates_widgets_on_polling_thread(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        handle.latest_progress = {
            "current_comments": 7,
            "total_comments": 12,
            "message": "取得中",
        }
        handle.progress_marker_queued = True
        app.worker_handle = handle
        app.gui_request_queue.put(tk_async_tasks.GuiRequest(kind="progress"))
        with patch.object(tk_async_tasks, "_perform_gui_update") as update:
            app._poll_gui_requests()
        update.assert_called_once_with(
            app.progress_label, app.progress_bar, 7, 12, "取得中"
        )
        app.comment_count_label.config.assert_called_once_with(
            text="取得コメント数: 7 / 12"
        )

    def test_unknown_request_kind_does_not_stop_polling(self):
        app = self.make_app()
        app.gui_request_queue.put(tk_async_tasks.GuiRequest(kind="not-supported"))
        with self.assertLogs(main.logger, level="WARNING"):
            app._poll_gui_requests()
        self.assertTrue(app.gui_request_queue.empty())
        app.master.after.assert_called_once_with(50, app._poll_gui_requests)


class NotificationDispatchTests(YouTubeCommentScraperAppTestCase):
    def test_notification_kinds_are_dispatched_to_matching_handlers(self):
        cases = (
            ("info", "show_info"),
            ("warning", "show_warning"),
            ("error", "show_error"),
        )
        for kind, handler_name in cases:
            with self.subTest(kind=kind):
                app = self.make_app()
                request = tk_async_tasks.GuiRequest(
                    kind="notification",
                    payload={"kind": kind, "title": "title", "message": "message"},
                )
                with patch.object(main.tk_notifications, handler_name) as handler:
                    app._handle_gui_request(request)
                handler.assert_called_once_with(
                    "title", "message", parent=app.master
                )

    def test_notification_display_exception_is_contained_and_dialog_state_resets(self):
        app = self.make_app()
        request = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "title", "message": "message"},
        )
        with self.assertLogs(main.logger, level="ERROR"):
            with patch.object(
                main.tk_notifications, "show_info",
                side_effect=RuntimeError("dialog failed"),
            ):
                app._show_modal_request(request)
        self.assertFalse(app._dialog_active)


class WorkerLifecycleTests(YouTubeCommentScraperAppTestCase):
    def make_finished_handle(self, app, result=None, exception=None):
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        handle.result = result
        handle.exception = exception
        handle.done_event.set()
        app.worker_handle = handle
        return handle

    def test_existing_worker_prevents_duplicate_start(self):
        app = self.make_app()
        app.worker_handle = object()
        with self.assertLogs(main.logger, level="WARNING"):
            with patch.object(tk_async_tasks, "run_task_in_thread") as run_task:
                app._start_scrape_process()
        run_task.assert_not_called()

    def test_new_worker_can_start_after_previous_worker_finishes(self):
        app = self.make_app()
        previous = self.make_finished_handle(app, result={"saved_files": []})
        with patch.object(tk_async_tasks, "_perform_gui_update"):
            app._finish_worker(previous)
        self.assertIsNone(app.worker_handle)

        app.api_key = "test-key"
        app.video_id_entry = MagicMock()
        app.video_id_entry.get.return_value = "abcdefghijk"
        next_handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        with patch.object(main.youtube_utils, "is_valid_video_id", return_value=True):
            with patch.object(
                tk_async_tasks, "run_task_in_thread", return_value=next_handle
            ) as run_task:
                with patch.object(tk_async_tasks, "_perform_gui_update"):
                    app._start_scrape_process()
        run_task.assert_called_once_with(
            app._scrape_comments_task, app.gui_request_queue, "abcdefghijk"
        )
        self.assertIs(app.worker_handle, next_handle)

    def test_finish_worker_waits_until_gui_queue_is_empty(self):
        app = self.make_app()
        handle = self.make_finished_handle(app, result={})
        app.gui_request_queue.put(tk_async_tasks.GuiRequest(kind="unknown"))
        app._finish_worker(handle)
        self.assertIs(app.worker_handle, handle)
        app.scrape_button.config.assert_not_called()

    def test_finish_worker_restores_widgets_and_saved_file_paths(self):
        app = self.make_app()
        handle = self.make_finished_handle(
            app,
            result={
                "saved_files": [{
                    "kind": "comments",
                    "path": "output/comments.json",
                    "success": True,
                }],
                "fetched_count": 4,
                "total_expected": 4,
            },
        )
        app._finish_worker(handle)
        self.assertIsNone(app.worker_handle)
        self.assertEqual(app.last_saved_comment_file_path, "output/comments.json")
        app.open_json_button.config.assert_called_once_with(state=tk.NORMAL)
        app.scrape_button.config.assert_called_once_with(state=tk.NORMAL)
        app.progress_label.config.assert_called_once_with(
            text="コメント取得処理終了"
        )

    def test_finish_worker_keeps_json_button_disabled_without_saved_files(self):
        app = self.make_app()
        handle = self.make_finished_handle(app, result={"saved_files": []})
        app._finish_worker(handle)
        app.open_json_button.config.assert_called_once_with(state=tk.DISABLED)
        self.assertIsNone(app.worker_handle)

    def test_finish_worker_restores_scrape_button_when_json_button_recovery_raises(self):
        app = self.make_app()
        handle = self.make_finished_handle(app, result={"saved_files": []})
        app.open_json_button.config.side_effect = [
            RuntimeError("json button failed"),
            None,
        ]

        with self.assertLogs(main.logger, level="ERROR"):
            app._finish_worker(handle)

        self.assertIsNone(app.worker_handle)
        app.scrape_button.config.assert_called_once_with(state=tk.NORMAL)
        app.progress_label.config.assert_called_once_with(
            text="コメント取得処理終了"
        )

        # JSONボタンの一時的な復旧失敗があっても、取得ボタンから再取得できる。
        app.api_key = "test-key"
        app.video_id_entry = MagicMock()
        app.video_id_entry.get.return_value = "abcdefghijk"
        next_handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        with patch.object(main.youtube_utils, "is_valid_video_id", return_value=True):
            with patch.object(
                tk_async_tasks, "run_task_in_thread", return_value=next_handle
            ) as run_task:
                app._start_scrape_process()
        run_task.assert_called_once()
        self.assertIs(app.worker_handle, next_handle)

    def test_finish_worker_restores_json_button_when_scrape_button_recovery_raises(self):
        app = self.make_app()
        handle = self.make_finished_handle(app, result={"saved_files": []})
        app.scrape_button.config.side_effect = RuntimeError("scrape button failed")

        with self.assertLogs(main.logger, level="ERROR"):
            app._finish_worker(handle)

        self.assertIsNone(app.worker_handle)
        app.open_json_button.config.assert_called_once_with(state=tk.DISABLED)
        app.progress_label.config.assert_called_once_with(
            text="コメント取得処理終了"
        )

    def test_finish_worker_queues_exception_notification_before_release(self):
        app = self.make_app()
        handle = self.make_finished_handle(
            app, exception=RuntimeError("worker failed")
        )
        app._finish_worker(handle)
        self.assertIs(app.worker_handle, handle)
        self.assertTrue(handle.exception_notification_queued)
        request = app.gui_request_queue.get_nowait()
        self.assertEqual(request.kind, "notification")
        self.assertEqual(request.payload["kind"], "error")
        self.assertEqual(request.payload["message"], "worker failed")

    def test_start_gui_preparation_failure_restores_controls_and_allows_retry(self):
        app = self.make_app()
        app.api_key = "test-key"
        app.video_id_entry = MagicMock()
        app.video_id_entry.get.return_value = "abcdefghijk"
        # 初回の無効化で一度だけ失敗し、復旧時の設定は成功させる。
        app.open_json_button.config.side_effect = [
            RuntimeError("json button preparation failed"),
            None,
            None,
        ]

        with patch.object(main.youtube_utils, "is_valid_video_id", return_value=True):
            with patch.object(tk_async_tasks, "run_task_in_thread") as run_task:
                with patch.object(main.tk_notifications, "show_error") as show_error:
                    with self.assertLogs(main.logger, level="ERROR"):
                        app._start_scrape_process()

        run_task.assert_not_called()
        show_error.assert_called_once()
        self.assertIsNone(app.worker_handle)
        app.scrape_button.config.assert_any_call(state=tk.DISABLED)
        app.scrape_button.config.assert_any_call(state=tk.NORMAL)
        app.open_json_button.config.assert_called_with(state=tk.DISABLED)

        next_handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        with patch.object(main.youtube_utils, "is_valid_video_id", return_value=True):
            with patch.object(
                tk_async_tasks, "run_task_in_thread", return_value=next_handle
            ) as retry_task:
                app._start_scrape_process()

        retry_task.assert_called_once()
        self.assertIs(app.worker_handle, next_handle)

    def test_start_failure_restores_gui_and_keeps_json_button_disabled(self):
        app = self.make_app()
        app.api_key = "test-key"
        app.video_id_entry = MagicMock()
        app.video_id_entry.get.return_value = "abcdefghijk"
        app.last_saved_comment_file_path = "old-path"
        with patch.object(main.youtube_utils, "is_valid_video_id", return_value=True):
            with patch.object(
                tk_async_tasks, "run_task_in_thread",
                side_effect=RuntimeError("thread start failed"),
            ):
                with patch.object(main.tk_notifications, "show_error") as show_error:
                    with patch.object(tk_async_tasks, "_perform_gui_update") as update:
                        app._start_scrape_process()
        self.assertIsNone(app.worker_handle)
        app.scrape_button.config.assert_any_call(state=tk.DISABLED)
        app.scrape_button.config.assert_any_call(state=tk.NORMAL)
        app.open_json_button.config.assert_any_call(state=tk.DISABLED)
        self.assertIsNone(app.last_saved_comment_file_path)
        update.assert_called()
        show_error.assert_called_once()

    def test_new_worker_can_start_after_previous_start_failure(self):
        app = self.make_app()
        app.api_key = "test-key"
        app.video_id_entry = MagicMock()
        app.video_id_entry.get.return_value = "abcdefghijk"

        with patch.object(main.youtube_utils, "is_valid_video_id", return_value=True):
            with patch.object(
                tk_async_tasks, "run_task_in_thread",
                side_effect=RuntimeError("thread start failed"),
            ):
                with patch.object(main.tk_notifications, "show_error"):
                    with patch.object(tk_async_tasks, "_perform_gui_update"):
                        app._start_scrape_process()

        self.assertIsNone(app.worker_handle)

        next_handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        with patch.object(main.youtube_utils, "is_valid_video_id", return_value=True):
            with patch.object(
                tk_async_tasks, "run_task_in_thread", return_value=next_handle
            ) as run_task:
                with patch.object(tk_async_tasks, "_perform_gui_update"):
                    app._start_scrape_process()

        run_task.assert_called_once_with(
            app._scrape_comments_task, app.gui_request_queue, "abcdefghijk"
        )
        self.assertIs(app.worker_handle, next_handle)

    def test_worker_exception_is_recovered_after_error_notification(self):
        app = self.make_app()
        handle = self.make_finished_handle(
            app, exception=RuntimeError("worker failed")
        )
        handle.partial_result["saved_files"].append({
            "kind": "comments",
            "path": "output/partial-comments.json",
            "success": True,
        })

        with self.assertLogs(main.logger, level="ERROR"):
            app._finish_worker(handle)
        self.assertIs(app.worker_handle, handle)
        request = app.gui_request_queue.get_nowait()
        self.assertEqual(request.kind, "notification")

        with self.assertLogs(main.logger, level="ERROR"):
            with patch.object(
                main.tk_notifications, "show_error",
                side_effect=RuntimeError("dialog failed"),
            ):
                app._show_modal_request(request)

        self.assertFalse(app._dialog_active)
        app._finish_worker(handle)

        self.assertIsNone(app.worker_handle)
        self.assertEqual(
            app.last_saved_comment_file_path, "output/partial-comments.json"
        )
        app.scrape_button.config.assert_called_once_with(state=tk.NORMAL)
        app.open_json_button.config.assert_called_once_with(state=tk.NORMAL)


class TkEventLoopIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:
            raise unittest.SkipTest(
                "Tk GUI環境を利用できないため統合テストをスキップ: {}".format(exc)
            )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "root", None) is not None:
            try:
                cls.root.destroy()
            except tk.TclError:
                pass

    def test_real_event_loop_dispatches_queued_notification(self):
        app = YouTubeCommentScraperAppTestCase().make_app()
        app.master = self.root
        app.gui_request_queue.put(
            tk_async_tasks.GuiRequest(
                kind="notification",
                payload={
                    "kind": "info",
                    "title": "test",
                    "message": "event-loop",
                },
            )
        )
        with patch.object(main.tk_notifications, "show_info") as show_info:
            app._poll_gui_requests()
            self.root.update()
        show_info.assert_called_once_with("test", "event-loop", parent=self.root)
        if app._gui_poll_after_id is not None:
            try:
                self.root.after_cancel(app._gui_poll_after_id)
            except tk.TclError:
                pass
            app._gui_poll_after_id = None


    def _run_event_loop_until(self, app, predicate, timeout_ms=3000):
        """実Tkイベントループを回し、条件成立またはタイムアウトで終了する。"""
        state = {"check_id": None, "timeout_id": None, "timed_out": False}

        def check_condition():
            if predicate():
                self.root.quit()
                return
            state["check_id"] = self.root.after(10, check_condition)

        def timeout():
            state["timed_out"] = True
            self.root.quit()

        state["check_id"] = self.root.after(0, check_condition)
        state["timeout_id"] = self.root.after(timeout_ms, timeout)
        self.root.mainloop()

        for after_id in (state["check_id"], state["timeout_id"],
                         app._gui_poll_after_id):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        app._gui_poll_after_id = None
        self.assertFalse(state["timed_out"], "Tkイベントループがタイムアウトしました。")
        self.assertTrue(predicate(), "終了条件が成立していません。")

    def _make_event_loop_app(self):
        app = YouTubeCommentScraperAppTestCase().make_app()
        app.master = self.root
        app.api_key = "test-key"
        app.video_id_entry = MagicMock()
        app.video_id_entry.get.return_value = "abcdefghijk"
        return app

    def test_real_event_loop_drains_more_than_50_requests_after_notification_error(self):
        app = self._make_event_loop_app()
        app.gui_request_queue.put(
            tk_async_tasks.GuiRequest(
                kind="notification",
                payload={
                    "kind": "info",
                    "title": "first",
                    "message": "dialog failure",
                },
            )
        )
        for _ in range(55):
            app.gui_request_queue.put(tk_async_tasks.GuiRequest(kind="unknown"))

        app._schedule_gui_request_polling()
        with self.assertLogs(main.logger, level="WARNING"):
            with patch.object(
                main.tk_notifications, "show_info",
                side_effect=RuntimeError("dialog failed"),
            ) as show_info:
                self._run_event_loop_until(app, app.gui_request_queue.empty)

        show_info.assert_called_once_with(
            "first", "dialog failure", parent=self.root
        )
        self.assertTrue(app.gui_request_queue.empty())

    def test_real_event_loop_processes_worker_requests_before_releasing_handle(self):
        app = self._make_event_loop_app()
        request_count = 55
        requests_seen = []
        finish_observations = []
        update_thread_ids = []
        notification_thread_ids = []
        main_thread_id = threading.current_thread().ident
        original_put = app.gui_request_queue.put
        original_finish = app._finish_worker

        def contains_tk_object(value):
            if isinstance(value, tk.Misc):
                return True
            if isinstance(value, dict):
                return any(
                    contains_tk_object(key) or contains_tk_object(item)
                    for key, item in value.items()
                )
            if isinstance(value, (list, tuple, set)):
                return any(contains_tk_object(item) for item in value)
            return False

        def recording_put(item, *args, **kwargs):
            if isinstance(item, tk_async_tasks.GuiRequest):
                requests_seen.append(item)
            return original_put(item, *args, **kwargs)

        def fake_fetch_all_comments(
            _api_key, _video_id, progress_callback, **_kwargs
        ):
            progress_callback(4, request_count, "worker progress")
            return (
                {
                    "notifications": [
                        {
                            "kind": "warning",
                            "title": "API notice {}".format(index),
                            "message": "worker notice {}".format(index),
                        }
                        for index in range(request_count)
                    ],
                    "fetch_status": "failed",
                    "video_info_raw_response": {},
                    "channel_info_raw_response": {},
                    "comment_threads_raw_responses": [],
                    "comment_replies_raw_responses": [],
                },
                4,
                request_count,
            )

        def record_update(*_args, **_kwargs):
            update_thread_ids.append(threading.current_thread().ident)

        def record_notification(*_args, **_kwargs):
            notification_thread_ids.append(threading.current_thread().ident)

        def observe_finish(handle):
            finish_observations.append(
                (
                    app.gui_request_queue.qsize(),
                    handle.done_event.is_set(),
                    len(notification_thread_ids),
                )
            )
            return original_finish(handle)

        app.gui_request_queue.put = recording_put
        app._schedule_gui_request_polling()
        with patch.object(
            main.youtube_utils, "is_valid_video_id", return_value=True
        ):
            with patch.object(
                main.youtube_api_client,
                "fetch_all_comments",
                side_effect=fake_fetch_all_comments,
            ):
                with patch.object(
                    main.json_data_handler, "save_json_to_file"
                ) as save_json:
                    with patch.object(
                        main.tk_notifications,
                        "show_warning",
                        side_effect=record_notification,
                    ):
                        with patch.object(
                            tk_async_tasks,
                            "_perform_gui_update",
                            side_effect=record_update,
                        ):
                            with patch.object(
                                app, "_finish_worker", side_effect=observe_finish
                            ):
                                self.root.after(0, app._start_scrape_process)
                                self._run_event_loop_until(
                                    app,
                                    lambda: len(requests_seen) == request_count + 1
                                    and app.worker_handle is None,
                                )
                    save_json.assert_not_called()

        self.assertEqual(len(requests_seen), request_count + 1)
        self.assertEqual(
            sum(request.kind == "progress" for request in requests_seen), 1
        )
        self.assertEqual(
            sum(request.kind == "notification" for request in requests_seen),
            request_count,
        )
        self.assertTrue(
            all(not contains_tk_object(request.payload) for request in requests_seen),
            "ワーカーから登録されたGUI要求payloadにTkinterオブジェクトが含まれています。",
        )
        self.assertEqual(len(notification_thread_ids), request_count)
        self.assertTrue(
            all(thread_id == main_thread_id for thread_id in notification_thread_ids)
        )
        self.assertTrue(update_thread_ids)
        self.assertTrue(all(thread_id == main_thread_id for thread_id in update_thread_ids))
        self.assertEqual(
            finish_observations,
            [(0, True, request_count)],
            "未処理要求が残っている間にワーカー完了処理が実行されました。",
        )
        self.assertIsNone(app.worker_handle)
        self.assertTrue(app.gui_request_queue.empty())

    def test_real_event_loop_collects_normal_and_exception_worker_completion(self):
        for should_raise in (False, True):
            with self.subTest(should_raise=should_raise):
                app = self._make_event_loop_app()
                task_started = threading.Event()

                def task(_handle, _video_id):
                    task_started.set()
                    if should_raise:
                        raise RuntimeError("integration worker failed")
                    return {"saved_files": []}

                app._scrape_comments_task = task
                app._schedule_gui_request_polling()
                with patch.object(
                    main.youtube_utils, "is_valid_video_id", return_value=True
                ):
                    with patch.object(main.tk_notifications, "show_error") as show_error:
                        self.root.after(0, app._start_scrape_process)
                        if should_raise:
                            with self.assertLogs(main.logger, level="ERROR"):
                                self._run_event_loop_until(
                                    app,
                                    lambda: task_started.is_set()
                                    and app.worker_handle is None,
                                )
                        else:
                            self._run_event_loop_until(
                                app,
                                lambda: task_started.is_set()
                                and app.worker_handle is None,
                            )

                self.assertIsNone(app.worker_handle)
                app.scrape_button.config.assert_any_call(state=tk.NORMAL)
                if should_raise:
                    show_error.assert_called_once_with(
                        "取得失敗", "integration worker failed",
                        parent=self.root,
                    )
                else:
                    show_error.assert_not_called()

    def test_real_event_loop_recovers_gui_after_thread_start_failure(self):
        app = self._make_event_loop_app()
        app._schedule_gui_request_polling()
        with patch.object(
            main.youtube_utils, "is_valid_video_id", return_value=True
        ):
            with patch.object(
                tk_async_tasks.threading.Thread,
                "start",
                side_effect=RuntimeError("integration start failure"),
            ):
                with patch.object(main.tk_notifications, "show_error") as show_error:
                    self.root.after(0, app._start_scrape_process)
                    self.root.after(20, self.root.quit)
                    self.root.mainloop()

        if app._gui_poll_after_id is not None:
            try:
                self.root.after_cancel(app._gui_poll_after_id)
            except tk.TclError:
                pass
            app._gui_poll_after_id = None

        self.assertIsNone(app.worker_handle)
        app.scrape_button.config.assert_any_call(state=tk.NORMAL)
        app.open_json_button.config.assert_any_call(state=tk.DISABLED)
        show_error.assert_called_once_with(
            "起動失敗", "integration start failure", parent=self.root
        )


class ApiKeyStartupTests(YouTubeCommentScraperAppTestCase):
    def test_api_key_success_builds_gui_and_starts_polling(self):
        root = MagicMock()
        with patch.object(
            main.tk_app_settings, "check_and_prompt_api_key",
            return_value="configured-key",
        ) as get_api_key:
            with patch.object(main.YouTubeCommentScraperApp, "_create_widgets") as create_widgets:
                with patch.object(
                    main.YouTubeCommentScraperApp, "_schedule_gui_request_polling"
                ) as schedule_polling:
                    app = main.YouTubeCommentScraperApp(root)
        self.assertEqual(app.api_key, "configured-key")
        get_api_key.assert_called_once_with(root, None)
        create_widgets.assert_called_once_with()
        root.protocol.assert_called_once_with("WM_DELETE_WINDOW", app._on_close_request)
        schedule_polling.assert_called_once_with()
        root.destroy.assert_not_called()

    def test_api_key_cancellation_skips_gui_setup_and_destroys_root(self):
        root = MagicMock()
        with patch.object(
            main.tk_app_settings, "check_and_prompt_api_key", return_value=None
        ):
            with patch.object(main.YouTubeCommentScraperApp, "_create_widgets") as create_widgets:
                with patch.object(
                    main.YouTubeCommentScraperApp, "_schedule_gui_request_polling"
                ) as schedule_polling:
                    app = main.YouTubeCommentScraperApp(root)
        self.assertIsNone(app.api_key)
        create_widgets.assert_not_called()
        root.protocol.assert_not_called()
        schedule_polling.assert_not_called()
        root.destroy.assert_called_once_with()

if __name__ == "__main__":
    unittest.main()


class ExistingInputWorkflowTests(YouTubeCommentScraperAppTestCase):
    def setUp(self):
        self.app = self.make_app()
        self.app.url_entry = MagicMock()
        self.app.video_id_entry = MagicMock()

    def test_parse_url_warns_and_stops_when_url_is_empty(self):
        self.app.url_entry.get.return_value = "   "

        with patch.object(main.tk_notifications, "show_warning") as warning:
            self.app._parse_url()

        warning.assert_called_once_with(
            "入力エラー", "URLを入力してください。", parent=self.app.master
        )
        self.app.video_id_entry.delete.assert_not_called()
        self.app.video_id_entry.insert.assert_not_called()

    def test_parse_url_inserts_extracted_video_id_and_shows_success(self):
        self.app.url_entry.get.return_value = " https://www.youtube.com/watch?v=abcdefghijk "

        with patch.object(
            main.youtube_utils, "extract_video_id", return_value="abcdefghijk"
        ) as extract:
            with patch.object(main.tk_notifications, "show_info") as info:
                self.app._parse_url()

        extract.assert_called_once_with(
            "https://www.youtube.com/watch?v=abcdefghijk"
        )
        self.app.video_id_entry.delete.assert_called_once_with(0, tk.END)
        self.app.video_id_entry.insert.assert_called_once_with(0, "abcdefghijk")
        info.assert_called_once_with(
            "解析完了", "動画ID: abcdefghijk を解析しました。",
            parent=self.app.master,
        )

    def test_parse_url_reports_invalid_url_without_changing_video_id(self):
        self.app.url_entry.get.return_value = "https://example.invalid/video"

        with patch.object(main.youtube_utils, "extract_video_id", return_value=None):
            with patch.object(main.tk_notifications, "show_error") as error:
                with self.assertLogs(main.logger, level="ERROR"):
                    self.app._parse_url()

        error.assert_called_once_with(
            "解析失敗", "有効なYouTube URLではありません。",
            parent=self.app.master,
        )
        self.app.video_id_entry.delete.assert_not_called()
        self.app.video_id_entry.insert.assert_not_called()

    def test_start_scrape_rejects_missing_api_key(self):
        self.app.api_key = None

        with patch.object(main.tk_notifications, "show_error") as error:
            with patch.object(tk_async_tasks, "run_task_in_thread") as run_task:
                self.app._start_scrape_process()

        error.assert_called_once_with(
            "APIキーエラー", "APIキーが設定されていません。",
            parent=self.app.master,
        )
        run_task.assert_not_called()

    def test_start_scrape_rejects_empty_video_id(self):
        self.app.api_key = "test-key"
        self.app.video_id_entry.get.return_value = "  "

        with patch.object(main.tk_notifications, "show_warning") as warning:
            with patch.object(tk_async_tasks, "run_task_in_thread") as run_task:
                self.app._start_scrape_process()

        warning.assert_called_once_with(
            "入力エラー", "動画IDを入力してください。",
            parent=self.app.master,
        )
        run_task.assert_not_called()

    def test_start_scrape_rejects_invalid_video_id(self):
        self.app.api_key = "test-key"
        self.app.video_id_entry.get.return_value = "not-a-valid-id"

        with patch.object(main.youtube_utils, "is_valid_video_id", return_value=False):
            with patch.object(main.tk_notifications, "show_error") as error:
                with patch.object(tk_async_tasks, "run_task_in_thread") as run_task:
                    self.app._start_scrape_process()

        error.assert_called_once_with(
            "入力エラー",
            "動画IDは11文字の英数字・ハイフン・アンダースコアで入力してください。",
            parent=self.app.master,
        )
        run_task.assert_not_called()

    def test_start_scrape_resets_gui_and_saved_paths_before_starting_worker(self):
        self.app.api_key = "test-key"
        self.app.video_id_entry.get.return_value = "abcdefghijk"
        self.app.last_saved_comment_file_path = "old-comments.json"
        self.app.last_saved_video_info_file_path = "old-video.json"
        self.app.last_saved_channel_info_file_path = "old-channel.json"
        self.app.last_saved_replies_file_path = "old-replies.json"
        handle = tk_async_tasks.WorkerHandle(self.app.gui_request_queue)

        with patch.object(main.youtube_utils, "is_valid_video_id", return_value=True):
            with patch.object(
                tk_async_tasks, "run_task_in_thread", return_value=handle
            ) as run_task:
                with patch.object(tk_async_tasks, "_perform_gui_update") as update:
                    self.app._start_scrape_process()

        run_task.assert_called_once_with(
            self.app._scrape_comments_task, self.app.gui_request_queue, "abcdefghijk"
        )
        self.assertIs(self.app.worker_handle, handle)
        self.app.scrape_button.config.assert_called_once_with(state=tk.DISABLED)
        self.app.open_json_button.config.assert_called_once_with(state=tk.DISABLED)
        update.assert_called_once_with(
            self.app.progress_label, self.app.progress_bar, 0, 0, "コメント取得中..."
        )
        self.app.comment_count_label.config.assert_called_once_with(
            text="取得コメント数: 0 / 0"
        )
        self.assertIsNone(self.app.last_saved_comment_file_path)
        self.assertIsNone(self.app.last_saved_video_info_file_path)
        self.assertIsNone(self.app.last_saved_channel_info_file_path)
        self.assertIsNone(self.app.last_saved_replies_file_path)
