"""Stage 3専用テスト：継続確認Event方式とAPIクライアント境界。"""

import ast
import inspect
import queue
import threading
import unittest
from unittest.mock import MagicMock, patch

import main
from module.utility.tk_async_tasks import tk_async_tasks
from module.utility.youtube_api_client import youtube_api_client


class Stage3AppTestCase(unittest.TestCase):
    def make_app(self):
        app = main.YouTubeCommentScraperApp.__new__(
            main.YouTubeCommentScraperApp
        )
        app.master = MagicMock()
        app.gui_request_queue = queue.Queue()
        app.worker_handle = None
        app.api_key = "test-api-key"
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

    def start_confirmation(self, handle, message="continue?"):
        result = []
        started = threading.Event()

        def worker():
            started.set()
            result.append(handle.request_confirmation(message))

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(started.wait(2))
        request = handle.gui_request_queue.get(timeout=2)
        return thread, request, result


class ConfirmationRequestLifecycleTests(Stage3AppTestCase):
    def test_request_is_registered_before_queue_delivery_and_waits_for_its_event(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle

        thread, request, result = self.start_confirmation(handle)

        self.assertEqual(request.kind, "confirmation")
        self.assertEqual(request.payload["message"], "continue?")
        self.assertIn(request.request_id, handle.pending_confirmations)
        self.assertFalse(request.response_event.is_set())
        self.assertEqual(result, [])

        app._answer_confirmation(request, True, "user_response")
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [True])
        self.assertNotIn(request.request_id, handle.pending_confirmations)
        self.assertTrue(request.answered)
        self.assertEqual(request.response_reason, "user_response")

    def test_true_and_false_user_answers_have_distinct_cancel_semantics(self):
        for answer, expected_cancel_reason in (
            (True, None),
            (False, "continuation_declined"),
        ):
            with self.subTest(answer=answer):
                app = self.make_app()
                handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
                app.worker_handle = handle
                thread, request, result = self.start_confirmation(handle)

                with patch.object(main.messagebox, "askyesno", return_value=answer):
                    app._handle_gui_request(request)
                thread.join(2)

                self.assertFalse(thread.is_alive())
                self.assertEqual(result, [answer])
                self.assertEqual(request.response, answer)
                self.assertEqual(request.response_reason, "user_response")
                self.assertEqual(handle.cancel_reason, expected_cancel_reason)
                self.assertEqual(request.response_event.is_set(), True)

    def test_dialog_exception_resolves_request_as_confirmation_unavailable(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        thread, request, result = self.start_confirmation(handle)

        with self.assertLogs(main.logger, level="ERROR"):
            with patch.object(
                main.messagebox, "askyesno",
                side_effect=RuntimeError("dialog failed"),
            ):
                app._handle_gui_request(request)
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [False])
        self.assertFalse(request.response)
        self.assertEqual(request.response_reason, "confirmation_unavailable")
        self.assertEqual(handle.cancel_reason, "confirmation_unavailable")
        self.assertTrue(request.response_event.is_set())

    def test_confirmation_answer_is_applied_only_once(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        request = tk_async_tasks.GuiRequest(kind="confirmation")

        app._answer_confirmation(request, True, "user_response")
        app._answer_confirmation(request, False, "confirmation_unavailable")

        self.assertTrue(request.answered)
        self.assertTrue(request.response)
        self.assertEqual(request.response_reason, "user_response")
        self.assertIsNone(handle.cancel_reason)
        self.assertTrue(request.response_event.is_set())

    def test_each_confirmation_request_has_an_independent_response_event(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        first_thread, first, first_result = self.start_confirmation(
            handle, "first"
        )
        second_thread, second, second_result = self.start_confirmation(
            handle, "second"
        )

        self.assertNotEqual(first.request_id, second.request_id)
        self.assertIsNot(first.response_event, second.response_event)
        self.assertFalse(first.response_event.is_set())
        self.assertFalse(second.response_event.is_set())

        app._answer_confirmation(second, False, "user_response")
        self.assertTrue(second.response_event.is_set())
        self.assertFalse(first.response_event.is_set())
        app._answer_confirmation(first, True, "user_response")

        first_thread.join(2)
        second_thread.join(2)
        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(first_result, [True])
        self.assertEqual(second_result, [False])
        self.assertEqual(handle.cancel_reason, "continuation_declined")
        self.assertEqual(handle.pending_confirmations, {})

    def test_shutdown_before_display_resolves_unanswered_request_without_dialog(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        thread, request, result = self.start_confirmation(handle)

        handle.cancel_for_shutdown()
        with patch.object(main.messagebox, "askyesno") as askyesno:
            app._handle_gui_request(request)

        thread.join(2)
        askyesno.assert_not_called()
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [False])
        self.assertEqual(request.response_reason, "application_shutdown")
        self.assertEqual(handle.cancel_reason, "application_shutdown")
        self.assertTrue(request.response_event.is_set())
        self.assertEqual(handle.pending_confirmations, {})


class ConfirmationRaceTests(Stage3AppTestCase):
    def test_display_started_request_is_not_overwritten_by_shutdown(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        thread, request, result = self.start_confirmation(handle)

        def shutdown_while_dialog_is_open(*args, **kwargs):
            self.assertTrue(request.display_started)
            handle.cancel_for_shutdown()
            return True

        with patch.object(
            main.messagebox, "askyesno",
            side_effect=shutdown_while_dialog_is_open,
        ):
            app._handle_gui_request(request)
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [True])
        self.assertTrue(request.response)
        self.assertEqual(request.response_reason, "user_response")
        self.assertEqual(handle.cancel_reason, "application_shutdown")
        self.assertTrue(handle.cancel_event.is_set())

    def test_user_decline_first_cause_is_preserved_when_shutdown_follows(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        request = tk_async_tasks.GuiRequest(kind="confirmation")
        handle.pending_confirmations[request.request_id] = request

        app._answer_confirmation(request, False, "user_response")
        handle.cancel_for_shutdown()

        self.assertFalse(request.response)
        self.assertEqual(request.response_reason, "user_response")
        self.assertEqual(handle.cancel_reason, "continuation_declined")
        self.assertTrue(request.response_event.is_set())
        self.assertTrue(handle.cancel_event.is_set())

    def test_true_answer_then_shutdown_keeps_response_but_records_shutdown_cause(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        request = tk_async_tasks.GuiRequest(kind="confirmation")
        handle.pending_confirmations[request.request_id] = request

        app._answer_confirmation(request, True, "user_response")
        handle.cancel_for_shutdown()

        self.assertTrue(request.response)
        self.assertEqual(request.response_reason, "user_response")
        self.assertEqual(handle.cancel_reason, "application_shutdown")
        self.assertTrue(request.response_event.is_set())
        self.assertTrue(handle.cancel_event.is_set())

    def test_answer_and_shutdown_race_always_releases_event_once(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        request = tk_async_tasks.GuiRequest(kind="confirmation")
        handle.pending_confirmations[request.request_id] = request
        barrier = threading.Barrier(3)
        failures = []

        def answer():
            try:
                barrier.wait(2)
                app._answer_confirmation(request, False, "user_response")
            except BaseException as exc:
                failures.append(exc)

        def shutdown():
            try:
                barrier.wait(2)
                handle.cancel_for_shutdown()
            except BaseException as exc:
                failures.append(exc)

        answer_thread = threading.Thread(target=answer)
        shutdown_thread = threading.Thread(target=shutdown)
        answer_thread.start()
        shutdown_thread.start()
        barrier.wait(2)
        answer_thread.join(2)
        shutdown_thread.join(2)

        self.assertFalse(answer_thread.is_alive())
        self.assertFalse(shutdown_thread.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(request.answered)
        self.assertTrue(request.response_event.is_set())
        self.assertIn(
            (request.response_reason, handle.cancel_reason),
            (
                ("user_response", "continuation_declined"),
                ("application_shutdown", "application_shutdown"),
            ),
        )
        self.assertTrue(handle.cancel_event.is_set())


class ModalDialogSerializationTests(Stage3AppTestCase):
    def test_reentrant_requests_are_queued_and_displayed_in_fifo_order(self):
        app = self.make_app()
        displayed = []
        active = []
        max_active = [0]
        second = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "second", "message": ""},
        )
        third = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "third", "message": ""},
        )

        def show_info(title, message, parent=None):
            active.append(title)
            max_active[0] = max(max_active[0], len(active))
            displayed.append(title)
            if title == "first":
                app._handle_gui_request(second)
                app._handle_gui_request(third)
                self.assertEqual(app._pending_modal_requests, [second, third])
            active.pop()

        first = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "first", "message": ""},
        )
        with patch.object(main.tk_notifications, "show_info", side_effect=show_info):
            app._handle_gui_request(first)

        self.assertEqual(displayed, ["first", "second", "third"])
        self.assertEqual(max_active[0], 1)
        self.assertEqual(app._pending_modal_requests, [])
        self.assertFalse(app._dialog_active)

    def test_confirmation_and_notification_share_the_same_fifo_modal_queue(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        displayed = []
        confirmation = tk_async_tasks.GuiRequest(
            kind="confirmation", payload={"message": "continue?"}
        )
        second_notice = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "warning", "title": "second", "message": ""},
        )

        def show_first(title, message, parent=None):
            displayed.append(title)
            app._handle_gui_request(confirmation)
            app._handle_gui_request(second_notice)

        def ask_confirmation(title, message, parent=None):
            displayed.append("confirmation")
            return True

        def show_warning(title, message, parent=None):
            displayed.append(title)

        first = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "first", "message": ""},
        )
        with patch.object(main.tk_notifications, "show_info", side_effect=show_first):
            with patch.object(main.messagebox, "askyesno", side_effect=ask_confirmation):
                with patch.object(main.tk_notifications, "show_warning", side_effect=show_warning):
                    app._handle_gui_request(first)

        self.assertEqual(displayed, ["first", "confirmation", "second"])
        self.assertTrue(confirmation.response)
        self.assertEqual(confirmation.response_reason, "user_response")
        self.assertEqual(app._pending_modal_requests, [])
        self.assertFalse(app._dialog_active)

    def test_display_exception_releases_modal_state_and_processes_queued_request(self):
        app = self.make_app()
        displayed = []
        second = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "second", "message": ""},
        )

        def show_first(title, message, parent=None):
            app._handle_gui_request(second)
            raise RuntimeError("display failed")

        def show_second(title, message, parent=None):
            displayed.append(title)

        first = tk_async_tasks.GuiRequest(
            kind="notification",
            payload={"kind": "info", "title": "first", "message": ""},
        )
        with self.assertLogs(main.logger, level="ERROR"):
            with patch.object(main.tk_notifications, "show_info", side_effect=show_first):
                with patch.object(main.tk_notifications, "show_warning", side_effect=show_second):
                    app._handle_gui_request(first)

        self.assertEqual(displayed, ["second"])
        self.assertFalse(app._dialog_active)
        self.assertEqual(app._pending_modal_requests, [])

    def test_confirmation_received_during_shutdown_is_not_displayed(self):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        app._shutdown_state = "stopping"
        request = tk_async_tasks.GuiRequest(kind="confirmation")

        with patch.object(main.messagebox, "askyesno") as askyesno:
            app._handle_gui_request(request)

        askyesno.assert_not_called()
        self.assertFalse(request.response)
        self.assertEqual(request.response_reason, "application_shutdown")
        self.assertEqual(handle.cancel_reason, "application_shutdown")
        self.assertTrue(request.response_event.is_set())


class ApiClientBoundaryTests(unittest.TestCase):
    def test_api_client_source_has_no_tkinter_or_tk_notification_dependency(self):
        source_path = inspect.getsourcefile(youtube_api_client)
        with open(source_path, "r", encoding="utf-8") as source_file:
            syntax_tree = ast.parse(source_file.read())

        imported_modules = []
        referenced_names = []
        for node in ast.walk(syntax_tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.append(node.module or "")
            elif isinstance(node, ast.Name):
                referenced_names.append(node.id)
            elif isinstance(node, ast.Attribute):
                referenced_names.append(node.attr)

        self.assertFalse(
            any(name == "tkinter" or name.startswith("tkinter.") for name in imported_modules)
        )
        self.assertFalse(
            any("tk_notifications" in name for name in imported_modules)
        )
        self.assertNotIn("tk_notifications", referenced_names)
        self.assertNotIn("tkinter", referenced_names)
        self.assertFalse(hasattr(youtube_api_client, "tk_notifications"))

    def test_service_failure_returns_one_sanitized_notification_without_gui_action(self):
        with patch.object(
            youtube_api_client, "build",
            side_effect=RuntimeError("secret-api-key-must-not-leak"),
        ):
            result = youtube_api_client.fetch_all_comments("secret-key", "video")

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        data, fetched_count, expected_count = result
        self.assertEqual(data["fetch_status"], "failed")
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)
        self.assertEqual(len(data["notifications"]), 1)
        notice = data["notifications"][0]
        self.assertEqual(notice["stage"], "service")
        self.assertEqual(notice["kind"], "error")
        self.assertIn("APIキーが正しいか確認", notice["message"])
        self.assertIn("RuntimeError", notice["message"])
        self.assertNotIn("secret-api-key-must-not-leak", notice["message"])
        self.assertNotIn("secret-key", notice["message"])

    def test_pre_cancelled_api_request_preserves_tuple_and_omits_cancel_reason(self):
        cancel_event = threading.Event()
        cancel_event.set()

        result = youtube_api_client.fetch_all_comments(
            "test-key", "video", cancel_event=cancel_event
        )

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        data, fetched_count, expected_count = result
        self.assertEqual(data["fetch_status"], "cancelled")
        self.assertNotIn("cancel_reason", data)
        self.assertEqual(fetched_count, 0)
        self.assertEqual(expected_count, 0)


class ScrapeTaskConfirmationHandoffTests(Stage3AppTestCase):
    def run_task_with_confirmation(self, answer, fetch_status):
        app = self.make_app()
        handle = tk_async_tasks.WorkerHandle(app.gui_request_queue)
        app.worker_handle = handle
        callback_result = []
        callback_thread = []

        def fake_fetch(api_key, video_id, progress_callback=None,
                       confirm_callback=None, cancel_event=None):
            self.assertEqual(api_key, "test-api-key")
            self.assertEqual(video_id, "video-id")
            self.assertIs(cancel_event, handle.cancel_event)

            def ask_from_worker():
                callback_result.append(confirm_callback("continue?"))

            thread = threading.Thread(target=ask_from_worker)
            callback_thread.append(thread)
            thread.start()
            request = app.gui_request_queue.get(timeout=2)
            self.assertEqual(request.kind, "confirmation")
            with patch.object(main.messagebox, "askyesno", return_value=answer):
                app._handle_gui_request(request)
            thread.join(2)
            self.assertFalse(thread.is_alive())

            return {
                "fetch_status": fetch_status,
                "errors": [],
                "notifications": [],
                "video_info_raw_response": {},
                "channel_info_raw_response": {},
                "comment_threads_raw_responses": [],
                "comment_replies_raw_responses": [],
            }, 0, 0

        with patch.object(
            main.youtube_api_client, "fetch_all_comments",
            side_effect=fake_fetch,
        ):
            result = app._scrape_comments_task(handle, "video-id")

        return app, handle, result, callback_result

    def test_true_confirmation_is_forwarded_to_api_callback_and_continues(self):
        app, handle, result, callback_result = self.run_task_with_confirmation(
            True, "complete"
        )

        self.assertEqual(callback_result, [True])
        self.assertIsNone(handle.cancel_reason)
        self.assertEqual(result["fetch_result"]["fetch_status"], "complete")
        self.assertNotIn("cancel_reason", result["fetch_result"])
        notices = list(app.gui_request_queue.queue)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].kind, "notification")
        self.assertEqual(notices[0].payload["title"], "取得完了")

    def test_false_confirmation_is_forwarded_and_cancel_reason_is_preserved(self):
        app, handle, result, callback_result = self.run_task_with_confirmation(
            False, "cancelled"
        )

        self.assertEqual(callback_result, [False])
        self.assertEqual(handle.cancel_reason, "continuation_declined")
        self.assertEqual(result["fetch_result"]["fetch_status"], "cancelled")
        self.assertEqual(
            result["fetch_result"]["cancel_reason"], "continuation_declined"
        )
        notices = list(app.gui_request_queue.queue)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].payload["title"], "取得中断")


if __name__ == "__main__":
    unittest.main()
