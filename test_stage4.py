"""Stage 4専用テスト：協調的キャンセルとアプリケーション終了制御。"""

import queue
import threading
import unittest
from unittest.mock import MagicMock, patch

import main
from module.utility.tk_async_tasks import tk_async_tasks


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
