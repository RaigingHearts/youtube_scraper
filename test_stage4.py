"""Stage 4専用テスト：協調的キャンセルとアプリケーション終了制御。"""

import queue
import threading
import unittest
from unittest.mock import MagicMock, patch

import main
from module.utility.tk_async_tasks import tk_async_tasks
from module.utility.youtube_api_client import youtube_api_client


class Stage4AppTestCase(unittest.TestCase):
    """Tkルートを生成せず、終了制御に必要なGUI状態だけを用意する。"""

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

    def make_running_handle(self, app):
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        return handle


class ShutdownStateTests(Stage4AppTestCase):
    """S4-01～S4-07：終了確認と状態遷移。"""

    def test_s4_01_shutdown_without_worker_destroys_root_immediately(self):
        app = self.make_app()

        with patch.object(main.messagebox, "askyesnocancel") as ask:
            app._begin_shutdown()

        ask.assert_not_called()
        self.assertEqual(app._shutdown_state, "closed")
        app.master.destroy.assert_called_once_with()
        self.assertFalse(app._shutdown_notifications)

    def test_s4_02_yes_selects_partial_save_and_cancels_worker(self):
        app = self.make_app()
        handle = self.make_running_handle(app)

        with patch.object(main.messagebox, "askyesnocancel", return_value=True) as ask:
            with patch.object(app, "_schedule_gui_request_polling") as schedule:
                app._begin_shutdown()

        ask.assert_called_once()
        self.assertEqual(app._shutdown_state, "stopping")
        self.assertEqual(handle.save_policy, "save_partial")
        self.assertFalse(handle.shutdown_pending)
        self.assertTrue(handle.shutdown_decision_event.is_set())
        self.assertTrue(handle.cancel_event.is_set())
        self.assertEqual(handle.cancel_reason, "application_shutdown")
        schedule.assert_called_once_with()

    def test_s4_03_no_selects_skip_additional_save_and_cancels_worker(self):
        app = self.make_app()
        handle = self.make_running_handle(app)

        with patch.object(main.messagebox, "askyesnocancel", return_value=False):
            with patch.object(app, "_schedule_gui_request_polling"):
                app._begin_shutdown()

        self.assertEqual(app._shutdown_state, "stopping")
        self.assertEqual(handle.save_policy, "skip_additional_save")
        self.assertTrue(handle.shutdown_decision_event.is_set())
        self.assertTrue(handle.cancel_event.is_set())
        self.assertEqual(handle.cancel_reason, "application_shutdown")

    def test_s4_04_cancel_releases_barrier_without_cancelling_worker_and_resumes_fifo(self):
        app = self.make_app()
        handle = self.make_running_handle(app)
        first = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "first", "message": "one"},
        )
        second = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "warning", "title": "second", "message": "two"},
        )
        app._pending_modal_requests.extend([first, second])

        with patch.object(main.messagebox, "askyesnocancel", return_value=None):
            with patch.object(app, "_drain_pending_modal_requests") as drain:
                with patch.object(app, "_schedule_gui_request_polling") as schedule:
                    app._begin_shutdown()

        self.assertEqual(app._shutdown_state, "running")
        self.assertFalse(handle.shutdown_pending)
        self.assertTrue(handle.shutdown_decision_event.is_set())
        self.assertFalse(handle.cancel_event.is_set())
        self.assertIsNone(handle.cancel_reason)
        self.assertEqual(app._pending_modal_requests, [first, second])
        drain.assert_called_once_with()
        schedule.assert_called_once_with()

    def test_s4_05_shutdown_after_save_started_does_not_change_save_policy(self):
        app = self.make_app()
        handle = self.make_running_handle(app)
        self.assertTrue(handle.begin_save())

        with patch.object(main.messagebox, "askyesnocancel", return_value=False) as ask:
            with patch.object(app, "_schedule_gui_request_polling"):
                app._begin_shutdown()

        self.assertIn("保存処理はすでに開始されています", ask.call_args[0][1])
        self.assertTrue(handle.save_started)
        self.assertIsNone(handle.save_policy)
        self.assertTrue(handle.cancel_event.is_set())
        self.assertEqual(app._shutdown_state, "stopping")

    def test_s4_06_worker_already_complete_skips_shutdown_confirmation(self):
        app = self.make_app()
        handle = self.make_running_handle(app)
        handle.done_event.set()

        with patch.object(main.messagebox, "askyesnocancel") as ask:
            with patch.object(app, "_schedule_gui_request_polling") as schedule:
                app._begin_shutdown()

        ask.assert_not_called()
        self.assertEqual(app._shutdown_state, "stopping")
        self.assertFalse(handle.cancel_event.is_set())
        schedule.assert_called_once_with()

    def test_s4_07_repeated_close_request_does_not_repeat_shutdown_dialog(self):
        app = self.make_app()
        handle = self.make_running_handle(app)

        with patch.object(main.messagebox, "askyesnocancel", return_value=True) as ask:
            with patch.object(app, "_schedule_gui_request_polling"):
                app._on_close_request()
                app._on_close_request()

        ask.assert_called_once()
        self.assertEqual(app._shutdown_state, "stopping")
        self.assertTrue(handle.cancel_event.is_set())


class ObservedEvent:
    """Event待機開始を通知し、待機中のLock解放を検証する。"""

    def __init__(self):
        self._event = threading.Event()
        self.wait_started = threading.Event()

    def clear(self):
        self._event.clear()

    def set(self):
        self._event.set()

    def is_set(self):
        return self._event.is_set()

    def wait(self, timeout=None):
        self.wait_started.set()
        return self._event.wait(timeout)


class ShutdownSaveBarrierTests(Stage4AppTestCase):
    """S4-08～S4-14：保存判断バリアと競合状態。"""

    def test_s4_08_begin_save_waits_without_holding_shutdown_lock(self):
        handle = tk_async_tasks.WorkerHandle(queue.Queue())
        handle.shutdown_decision_event = ObservedEvent()
        self.assertEqual(handle.begin_shutdown_decision(), "pending")
        result = []
        worker = threading.Thread(target=lambda: result.append(handle.begin_save()))

        worker.start()
        self.assertTrue(handle.shutdown_decision_event.wait_started.wait(2))
        acquired = handle.shutdown_lock.acquire(timeout=2)
        self.assertTrue(acquired)
        if acquired:
            handle.shutdown_lock.release()

        self.assertTrue(worker.is_alive())
        self.assertEqual(result, [])
        handle.resolve_shutdown_decision("save_partial")
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [True])
        self.assertTrue(handle.save_started)

    def test_s4_09_pending_decision_allows_save_after_save_partial_choice(self):
        handle = tk_async_tasks.WorkerHandle(queue.Queue())
        handle.shutdown_decision_event = ObservedEvent()
        self.assertEqual(handle.begin_shutdown_decision(), "pending")
        result = []
        worker = threading.Thread(target=lambda: result.append(handle.begin_save()))

        worker.start()
        self.assertTrue(handle.shutdown_decision_event.wait_started.wait(2))
        self.assertEqual(result, [])
        self.assertTrue(handle.resolve_shutdown_decision("save_partial"))
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [True])
        self.assertEqual(handle.save_policy, "save_partial")
        self.assertTrue(handle.save_started)

    def test_s4_10_skip_additional_save_releases_waiter_without_starting_save(self):
        handle = tk_async_tasks.WorkerHandle(queue.Queue())
        handle.shutdown_decision_event = ObservedEvent()
        self.assertEqual(handle.begin_shutdown_decision(), "pending")
        result = []
        worker = threading.Thread(target=lambda: result.append(handle.begin_save()))

        worker.start()
        self.assertTrue(handle.shutdown_decision_event.wait_started.wait(2))
        self.assertEqual(result, [])
        self.assertTrue(handle.resolve_shutdown_decision("skip_additional_save"))
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [False])
        self.assertEqual(handle.save_policy, "skip_additional_save")
        self.assertFalse(handle.save_started)

    def test_s4_11_cancelled_shutdown_releases_waiter_for_normal_save(self):
        handle = tk_async_tasks.WorkerHandle(queue.Queue())
        handle.shutdown_decision_event = ObservedEvent()
        self.assertEqual(handle.begin_shutdown_decision(), "pending")
        result = []
        worker = threading.Thread(target=lambda: result.append(handle.begin_save()))

        worker.start()
        self.assertTrue(handle.shutdown_decision_event.wait_started.wait(2))
        self.assertEqual(result, [])
        self.assertTrue(handle.resolve_shutdown_decision(None))
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [True])
        self.assertIsNone(handle.save_policy)
        self.assertTrue(handle.save_started)
        self.assertFalse(handle.cancel_event.is_set())
        self.assertIsNone(handle.cancel_reason)

    def test_s4_12_save_started_first_prevents_shutdown_pending_state(self):
        handle = tk_async_tasks.WorkerHandle(queue.Queue())

        self.assertTrue(handle.begin_save())
        self.assertEqual(handle.begin_shutdown_decision(), "save_started")

        self.assertTrue(handle.save_started)
        self.assertFalse(handle.shutdown_pending)
        self.assertIsNone(handle.save_policy)
        self.assertFalse(handle.shutdown_decision_event.is_set())

    def test_s4_13_shutdown_cancel_is_set_before_decision_event_is_released(self):
        handle = tk_async_tasks.WorkerHandle(queue.Queue())

        class InspectingEvent:
            def __init__(self):
                self.event = threading.Event()
                self.state_when_set = None

            def clear(self):
                self.event.clear()

            def set(self):
                self.state_when_set = (
                    handle.cancel_event.is_set(),
                    handle.cancel_reason,
                )
                self.event.set()

            def is_set(self):
                return self.event.is_set()

            def wait(self, timeout=None):
                return self.event.wait(timeout)

        observed_event = InspectingEvent()
        handle.shutdown_decision_event = observed_event
        self.assertEqual(handle.begin_shutdown_decision(), "pending")

        self.assertTrue(
            handle.resolve_shutdown_decision("save_partial", cancel=True)
        )

        self.assertEqual(
            observed_event.state_when_set,
            (True, "application_shutdown"),
        )
        self.assertTrue(observed_event.is_set())
        self.assertFalse(handle.shutdown_pending)

    def test_s4_14_save_start_and_shutdown_pending_have_one_winning_order(self):
        handle = tk_async_tasks.WorkerHandle(queue.Queue())
        start_gate = threading.Barrier(3)
        decision_result = []
        save_result = []
        errors = []

        def decide_shutdown():
            try:
                start_gate.wait()
                decision_result.append(handle.begin_shutdown_decision())
            except BaseException as exc:
                errors.append(exc)

        def begin_save():
            try:
                start_gate.wait()
                save_result.append(handle.begin_save())
            except BaseException as exc:
                errors.append(exc)

        decision_thread = threading.Thread(target=decide_shutdown)
        save_thread = threading.Thread(target=begin_save)
        decision_thread.start()
        save_thread.start()
        start_gate.wait()

        decision_thread.join(2)
        self.assertFalse(decision_thread.is_alive())
        self.assertEqual(len(decision_result), 1)

        if decision_result[0] == "pending":
            self.assertTrue(handle.resolve_shutdown_decision("save_partial"))
        else:
            self.assertEqual(decision_result[0], "save_started")

        save_thread.join(2)
        self.assertFalse(save_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(save_result, [True])
        self.assertTrue(handle.save_started)
        self.assertFalse(handle.shutdown_pending)
        if decision_result[0] == "pending":
            self.assertEqual(handle.save_policy, "save_partial")
        else:
            self.assertIsNone(handle.save_policy)


if __name__ == "__main__":
    unittest.main()


class ShutdownWorkerRaceTests(Stage4AppTestCase):
    """S4-15～S4-20：自然完了との競合とワーカー終了待ち。"""

    def test_s4_15_shutdown_decision_reports_complete_after_worker_finishes(self):
        handle = tk_async_tasks.WorkerHandle(queue.Queue())
        handle.done_event.set()

        self.assertEqual(handle.begin_shutdown_decision(), "complete")
        self.assertFalse(handle.shutdown_pending)
        self.assertFalse(handle.cancel_event.is_set())
        self.assertFalse(handle.shutdown_decision_event.is_set())

    def test_s4_16_worker_completion_wins_before_shutdown_decision_resolution(self):
        handle = tk_async_tasks.WorkerHandle(queue.Queue())
        self.assertEqual(handle.begin_shutdown_decision(), "pending")

        handle.done_event.set()
        resolved = handle.resolve_shutdown_decision(
            "save_partial", cancel=True
        )

        self.assertFalse(resolved)
        self.assertFalse(handle.shutdown_pending)
        self.assertTrue(handle.shutdown_decision_event.is_set())
        self.assertIsNone(handle.save_policy)
        self.assertFalse(handle.cancel_event.is_set())
        self.assertIsNone(handle.cancel_reason)

    def test_s4_17_finish_worker_waits_until_thread_is_not_alive(self):
        app = self.make_app()
        handle = self.make_running_handle(app)
        handle.done_event.set()
        handle.thread = MagicMock()
        handle.thread.is_alive.return_value = True

        app._shutdown_state = "stopping"
        app._finish_worker(handle)

        handle.thread.join.assert_called_once_with(timeout=0)
        self.assertIs(app.worker_handle, handle)
        self.assertEqual(app._shutdown_state, "stopping")
        app.master.destroy.assert_not_called()

    def test_s4_18_finish_worker_waits_until_gui_request_queue_is_drained(self):
        app = self.make_app()
        handle = self.make_running_handle(app)
        handle.done_event.set()
        handle.thread = MagicMock()
        handle.thread.is_alive.return_value = False
        request = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "pending", "message": "notice"},
        )
        app.gui_request_queue.put(request)
        app._shutdown_state = "stopping"

        app._finish_worker(handle)

        self.assertIs(app.worker_handle, handle)
        self.assertEqual(app._shutdown_state, "stopping")
        self.assertFalse(handle.exception_notification_queued)
        app.master.destroy.assert_not_called()

    def test_s4_19_shutdown_finalizes_only_after_worker_thread_has_joined(self):
        app = self.make_app()
        handle = self.make_running_handle(app)
        handle.done_event.set()
        handle.thread = MagicMock()
        handle.thread.is_alive.return_value = False
        handle.result = {"saved_files": []}
        app._shutdown_state = "stopping"

        app._finish_worker(handle)

        self.assertIsNone(app.worker_handle)
        self.assertEqual(app._shutdown_state, "closed")
        app.master.destroy.assert_called_once_with()
        self.assertEqual(app.open_json_button.config.call_args.kwargs["state"], main.tk.DISABLED)
        self.assertEqual(app.scrape_button.config.call_args.kwargs["state"], main.tk.NORMAL)

    def test_s4_20_shutdown_cancellation_is_cooperative_not_forced_thread_termination(self):
        gui_queue = queue.Queue()
        worker_started = threading.Event()
        allow_worker_exit = threading.Event()

        def task(handle):
            worker_started.set()
            allow_worker_exit.wait()
            return "finished"

        handle = tk_async_tasks.run_task_in_thread(task, gui_queue)
        self.assertTrue(worker_started.wait(2))
        self.assertFalse(handle.thread.daemon)

        handle.cancel_for_shutdown()

        self.assertTrue(handle.cancel_event.is_set())
        self.assertFalse(handle.done_event.is_set())
        self.assertTrue(handle.thread.is_alive())

        allow_worker_exit.set()
        handle.thread.join(2)

        self.assertFalse(handle.thread.is_alive())
        self.assertTrue(handle.done_event.is_set())
        self.assertEqual(handle.result, "finished")



if __name__ == "__main__":
    unittest.main()


class CancelDuringWait:
    """ページ間待機でキャンセルを通知する決定的なテストEvent。"""

    def __init__(self):
        self.cancelled = False
        self.wait_calls = []

    def is_set(self):
        return self.cancelled

    def set(self):
        self.cancelled = True

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        self.cancelled = True
        return True


class ShutdownApiCancellationTests(unittest.TestCase):
    """S4-21～S4-28：API通信・ページ境界での協調的キャンセル。"""

    def make_service(self, thread_response=None, reply_responses=None):
        service = MagicMock()
        service.videos.return_value.list.return_value.execute.return_value = {
            "items": [{
                "snippet": {
                    "channelId": "channel-1",
                    "title": "Test",
                    "channelTitle": "Uploader",
                }
            }]
        }
        service.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "channel-1"}]
        }
        service.commentThreads.return_value.list.return_value.execute.return_value = (
            thread_response if thread_response is not None else {"items": []}
        )
        service.comments.return_value.list.return_value.execute.side_effect = (
            reply_responses if reply_responses is not None else []
        )
        return service

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_s4_21_pre_cancelled_request_does_not_initialize_api_service(
        self, get_service
    ):
        cancel_event = threading.Event()
        cancel_event.set()

        data, fetched, expected = youtube_api_client.fetch_all_comments(
            "key", "video", cancel_event=cancel_event
        )

        get_service.assert_not_called()
        self.assertEqual(data["fetch_status"], "cancelled")
        self.assertEqual(data["video_info_raw_response"], {})
        self.assertEqual(data["comment_threads_raw_responses"], [])
        self.assertEqual((fetched, expected), (0, 0))

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_s4_22_cancel_during_video_execute_keeps_response_and_stops_followups(
        self, get_service
    ):
        cancel_event = threading.Event()
        service = self.make_service()
        video_response = {"items": [{"snippet": {"channelId": "channel-1"}}]}

        def execute_video():
            cancel_event.set()
            return video_response

        service.videos.return_value.list.return_value.execute.side_effect = (
            execute_video
        )
        get_service.return_value = service

        data, fetched, expected = youtube_api_client.fetch_all_comments(
            "key", "video", cancel_event=cancel_event
        )

        self.assertEqual(data["fetch_status"], "cancelled")
        self.assertIs(data["video_info_raw_response"], video_response)
        service.channels.return_value.list.assert_not_called()
        service.commentThreads.return_value.list.assert_not_called()
        self.assertEqual((fetched, expected), (0, 0))

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_s4_23_cancel_during_channel_execute_keeps_response_and_skips_threads(
        self, get_service
    ):
        cancel_event = threading.Event()
        service = self.make_service()
        channel_response = {"items": [{"id": "channel-1"}]}

        def execute_channel():
            cancel_event.set()
            return channel_response

        service.channels.return_value.list.return_value.execute.side_effect = (
            execute_channel
        )
        get_service.return_value = service

        data, fetched, expected = youtube_api_client.fetch_all_comments(
            "key", "video", cancel_event=cancel_event
        )

        self.assertEqual(data["fetch_status"], "cancelled")
        self.assertTrue(data["video_info_raw_response"]["items"])
        self.assertIs(data["channel_info_raw_response"], channel_response)
        service.commentThreads.return_value.list.assert_not_called()
        self.assertEqual((fetched, expected), (0, 0))

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_s4_24_cancel_during_thread_execute_keeps_page_and_accounts_all_parents(
        self, get_service
    ):
        cancel_event = threading.Event()
        page = {
            "items": [
                {"id": "parent-1", "snippet": {
                    "totalReplyCount": 1,
                    "topLevelComment": {"id": "parent-1"},
                }},
                {"id": "parent-2", "snippet": {
                    "totalReplyCount": 0,
                    "topLevelComment": {"id": "parent-2"},
                }},
            ],
            "nextPageToken": "thread-page-2",
        }
        service = self.make_service()

        def execute_threads():
            cancel_event.set()
            return page

        service.commentThreads.return_value.list.return_value.execute.side_effect = (
            execute_threads
        )
        get_service.return_value = service

        data, fetched, expected = youtube_api_client.fetch_all_comments(
            "key", "video", cancel_event=cancel_event
        )

        self.assertEqual(data["fetch_status"], "cancelled")
        self.assertEqual(data["comment_threads_raw_responses"], [page])
        self.assertEqual(fetched, 2)
        self.assertEqual(expected, 0)
        self.assertEqual(
            data["comment_replies_raw_responses"],
            [{"parent_id": "parent-1", "raw_responses": []}],
        )
        service.commentThreads.return_value.list.assert_called_once()
        service.comments.return_value.list.assert_not_called()

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_s4_25_cancel_during_reply_execute_keeps_page_and_stops_next_reply_page(
        self, get_service
    ):
        cancel_event = threading.Event()
        thread_page = {"items": [{
            "id": "parent-1",
            "snippet": {
                "totalReplyCount": 2,
                "topLevelComment": {"id": "parent-1"},
            },
        }]}
        reply_page = {
            "items": [{"id": "reply-1"}],
            "nextPageToken": "reply-page-2",
        }
        service = self.make_service(thread_page)

        def execute_reply():
            cancel_event.set()
            return reply_page

        service.comments.return_value.list.return_value.execute.side_effect = (
            execute_reply
        )
        get_service.return_value = service

        data, fetched, expected = youtube_api_client.fetch_all_comments(
            "key", "video", cancel_event=cancel_event
        )

        self.assertEqual(data["fetch_status"], "cancelled")
        self.assertEqual(
            data["comment_replies_raw_responses"],
            [{"parent_id": "parent-1", "raw_responses": [reply_page]}],
        )
        self.assertEqual((fetched, expected), (2, 3))
        service.comments.return_value.list.assert_called_once()

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_s4_26_reply_exception_after_cancel_keeps_remaining_parent_comments(
        self, get_service
    ):
        cancel_event = threading.Event()
        thread_page = {"items": [
            {"id": "parent-1", "snippet": {
                "totalReplyCount": 1,
                "topLevelComment": {"id": "parent-1"},
            }},
            {"id": "parent-2", "snippet": {
                "totalReplyCount": 0,
                "topLevelComment": {"id": "parent-2"},
            }},
        ]}
        service = self.make_service(thread_page)

        def fail_reply_after_cancel():
            cancel_event.set()
            raise RuntimeError("simulated reply failure")

        service.comments.return_value.list.return_value.execute.side_effect = (
            fail_reply_after_cancel
        )
        get_service.return_value = service

        data, fetched, expected = youtube_api_client.fetch_all_comments(
            "key", "video", cancel_event=cancel_event
        )

        self.assertEqual(data["fetch_status"], "cancelled")
        self.assertEqual(fetched, 2)
        self.assertEqual(expected, 3)
        self.assertEqual(
            data["comment_replies_raw_responses"],
            [{"parent_id": "parent-1", "raw_responses": []}],
        )
        self.assertEqual(len(data["errors"]), 1)
        self.assertEqual(data["errors"][0]["stage"], "reply_comments")
        self.assertEqual(len(data["notifications"]), 1)
        service.comments.return_value.list.assert_called_once()

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_s4_27_cancel_during_thread_page_wait_prevents_next_page(
        self, get_service
    ):
        cancel_event = CancelDuringWait()
        first_page = {
            "items": [{
                "id": "parent-1",
                "snippet": {
                    "totalReplyCount": 0,
                    "topLevelComment": {"id": "parent-1"},
                },
            }],
            "nextPageToken": "thread-page-2",
        }
        service = self.make_service(first_page)
        get_service.return_value = service

        data, fetched, expected = youtube_api_client.fetch_all_comments(
            "key", "video", cancel_event=cancel_event
        )

        self.assertEqual(data["fetch_status"], "cancelled")
        self.assertEqual(fetched, 1)
        self.assertEqual(expected, 0)
        self.assertEqual(cancel_event.wait_calls, [0.1])
        service.commentThreads.return_value.list.assert_called_once()

    @patch.object(youtube_api_client, "get_youtube_service")
    def test_s4_28_cancel_during_reply_page_wait_prevents_next_page(
        self, get_service
    ):
        cancel_event = CancelDuringWait()
        thread_page = {"items": [{
            "id": "parent-1",
            "snippet": {
                "totalReplyCount": 2,
                "topLevelComment": {"id": "parent-1"},
            },
        }]}
        first_reply_page = {
            "items": [{"id": "reply-1"}],
            "nextPageToken": "reply-page-2",
        }
        service = self.make_service(thread_page, [first_reply_page])
        get_service.return_value = service

        data, fetched, expected = youtube_api_client.fetch_all_comments(
            "key", "video", cancel_event=cancel_event
        )

        self.assertEqual(data["fetch_status"], "cancelled")
        self.assertEqual(fetched, 2)
        self.assertEqual(expected, 3)
        self.assertEqual(cancel_event.wait_calls, [0.1])
        self.assertEqual(
            data["comment_replies_raw_responses"],
            [{"parent_id": "parent-1", "raw_responses": [first_reply_page]}],
        )
        service.comments.return_value.list.assert_called_once()


class ShutdownPartialResultTests(Stage4AppTestCase):
    """S4-29～S4-30：部分取得結果と終了時保存方針の接続。"""

    def setUp(self):
        self.app = self.make_app()
        self.app.api_key = "stage4-test-api-key"
        self.handle = self.make_running_handle(self.app)

    def make_cancelled_result(self):
        return {
            "video_info_raw_response": {"items": [{"id": "video-1"}]},
            "channel_info_raw_response": {"items": [{"id": "channel-1"}]},
            "comment_threads_raw_responses": [{"items": [{"id": "parent-1"}]}],
            "comment_replies_raw_responses": [{
                "parent_id": "parent-1",
                "raw_responses": [{"items": [{"id": "reply-1"}]}],
            }],
            "fetch_status": "cancelled",
            "cancel_reason": "application_shutdown",
            "errors": [],
            "notifications": [],
        }

    def test_s4_29_save_partial_persists_available_data_and_records_results(self):
        self.assertTrue(
            self.handle.resolve_shutdown_decision(
                "save_partial", cancel=True
            )
        )
        fetch_result = self.make_cancelled_result()

        with patch.object(
            main.youtube_api_client,
            "fetch_all_comments",
            return_value=(fetch_result, 2, 0),
        ):
            with patch.object(
                main.json_data_handler, "save_json_to_file", return_value=True
            ) as save_file:
                result = self.app._scrape_comments_task(
                    self.handle, "abcdefghijk"
                )

        self.assertEqual(save_file.call_count, 4)
        self.assertEqual(
            [record["kind"] for record in result["saved_files"]],
            ["video_info", "channel_info", "comments", "replies"],
        )
        self.assertTrue(all(record["success"] for record in result["saved_files"]))
        self.assertEqual(
            self.handle.partial_result["saved_files"], result["saved_files"]
        )
        self.assertEqual(
            result["fetch_result"]["cancel_reason"], "application_shutdown"
        )
        self.assertTrue(self.handle.cancel_event.is_set())

    def test_s4_30_skip_additional_save_does_not_call_save_or_delete_existing_data(
        self
    ):
        self.assertTrue(
            self.handle.resolve_shutdown_decision(
                "skip_additional_save", cancel=True
            )
        )
        fetch_result = self.make_cancelled_result()

        with patch.object(
            main.youtube_api_client,
            "fetch_all_comments",
            return_value=(fetch_result, 2, 0),
        ):
            with patch.object(
                main.json_data_handler, "save_json_to_file"
            ) as save_file:
                result = self.app._scrape_comments_task(
                    self.handle, "abcdefghijk"
                )

        save_file.assert_not_called()
        self.assertEqual(result["saved_files"], [])
        self.assertEqual(self.handle.partial_result["saved_files"], [])
        self.assertEqual(
            result["fetch_result"]["cancel_reason"], "application_shutdown"
        )
        notification_requests = [
            request for request in list(self.app.gui_request_queue.queue)
            if request.kind == "notification"
        ]
        self.assertEqual(len(notification_requests), 1)
        self.assertIn(
            "追加保存は行っていません",
            notification_requests[0].payload["message"],
        )


if __name__ == "__main__":
    unittest.main()
