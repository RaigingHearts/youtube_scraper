"""実Tkイベントループ上でStage 3・4の連携を検証する統合テスト。"""

import queue
import threading
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import main
from module.utility.tk_async_tasks import tk_async_tasks


class TkStageIntegrationTests(unittest.TestCase):
    """実Tkイベントループを使用し、ダイアログは非表示Toplevelで代替する。"""

    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as exc:
            raise unittest.SkipTest(
                "Tk GUI環境を利用できないため統合テストをスキップ: {}".format(exc)
            )
        self.dialog_order = []

    def tearDown(self):
        root = getattr(self, "root", None)
        if root is not None:
            try:
                if root.winfo_exists():
                    root.destroy()
            except tk.TclError:
                pass

    def make_app(self):
        app = main.YouTubeCommentScraperApp.__new__(
            main.YouTubeCommentScraperApp
        )
        app.master = self.root
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

    def run_nested_dialog(self, name, on_open=None):
        """wait_window()でネストしたTkイベントループを実行する。"""
        self.dialog_order.append(name)
        window = tk.Toplevel(self.root)
        window.withdraw()

        def finish():
            if on_open is not None:
                on_open()
            self.root.after_idle(window.destroy)

        self.root.after_idle(finish)
        self.root.wait_window(window)

    def start_confirmation_worker(self, app, message):
        """確認要求を出すワーカーを起動し、要求のキュー登録を待つ。"""
        confirmation_queued = threading.Event()
        original_put = app.gui_request_queue.put

        def observe_put(request, *args, **kwargs):
            result = original_put(request, *args, **kwargs)
            if getattr(request, "kind", None) == "confirmation":
                confirmation_queued.set()
            return result

        app.gui_request_queue.put = observe_put

        def task(handle):
            return handle.request_confirmation(message)

        handle = tk_async_tasks.run_task_in_thread(
            task, app.gui_request_queue
        )
        app.worker_handle = handle
        self.assertTrue(
            confirmation_queued.wait(2),
            "ワーカーの確認要求がキューへ登録されませんでした。",
        )
        return handle

    def run_event_loop_until(self, predicate, timeout_ms=3000):
        """条件成立まで実Tkイベントループを回し、時間切れを明示する。"""
        state = {"check_id": None, "timeout_id": None, "timed_out": False}

        def check_condition():
            if predicate():
                self.root.quit()
                return
            state["check_id"] = self.root.after(5, check_condition)

        def timeout():
            state["timed_out"] = True
            self.root.quit()

        state["check_id"] = self.root.after(0, check_condition)
        state["timeout_id"] = self.root.after(timeout_ms, timeout)
        self.root.mainloop()

        for after_id in (
            state["check_id"],
            state["timeout_id"],
        ):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass

        self.assertFalse(
            state["timed_out"], "Tkイベントループがタイムアウトしました。"
        )
        self.assertTrue(predicate(), "終了条件が成立していません。")

    def queue_during_active_modal(self, app):
        """確認要求と通知をモーダル表示中に処理し、終了要求を発行する。"""
        # 確認要求に続けて通知を登録し、ネストしたイベントループ内で
        # ポーリングを一度だけ再入させて、両方を保留列へ退避させる。
        app.gui_request_queue.put(
            tk_async_tasks.GuiRequest(
                kind="notification",
                payload={
                    "kind": "warning",
                    "title": "queued notification",
                    "message": "queued while modal was active",
                },
            )
        )
        app._poll_gui_requests()
        self.assertEqual(len(app._pending_modal_requests), 2)
        self.assertEqual(
            [request.kind for request in app._pending_modal_requests],
            ["confirmation", "notification"],
        )
        app._on_close_request()
        self.assertTrue(app._shutdown_requested)

    def test_real_event_loop_answers_worker_confirmation(self):
        app = self.make_app()
        handle = self.start_confirmation_worker(app, "continue integration task")

        def ask_confirmation(*_args, **_kwargs):
            self.run_nested_dialog("worker confirmation")
            return True

        app._schedule_gui_request_polling()
        with patch.object(
            main.messagebox, "askyesno", side_effect=ask_confirmation
        ):
            self.run_event_loop_until(
                lambda: handle.done_event.is_set()
                and app.worker_handle is None
            )

        self.assertTrue(handle.result)
        self.assertTrue(handle.thread is not None)
        self.assertFalse(handle.thread.is_alive())
        self.assertEqual(
            handle.cancel_reason, None,
            "肯定応答でワーカーのキャンセル理由が設定されています。",
        )
        self.assertEqual(self.dialog_order, ["worker confirmation"])
        self.assertEqual(app._shutdown_state, "running")

    def test_cancelled_shutdown_resumes_pending_modals_in_fifo_order(self):
        app = self.make_app()
        app.gui_request_queue.put(
            tk_async_tasks.GuiRequest(
                kind="notification",
                payload={
                    "kind": "info",
                    "title": "initial notification",
                    "message": "first modal",
                },
            )
        )
        handle = self.start_confirmation_worker(app, "worker confirmation")

        def show_info(title, _message, **_kwargs):
            if title == "initial notification":
                self.run_nested_dialog(
                    "initial notification",
                    lambda: self.queue_during_active_modal(app),
                )
            else:
                self.run_nested_dialog(title)

        def ask_confirmation(*_args, **_kwargs):
            self.run_nested_dialog("worker confirmation")
            return True

        app._schedule_gui_request_polling()
        with patch.object(
            main.tk_notifications, "show_info", side_effect=show_info
        ):
            with patch.object(
                main.tk_notifications, "show_warning", side_effect=show_info
            ):
                with patch.object(
                    main.messagebox, "askyesnocancel", return_value=None
                ) as ask_shutdown:
                    with patch.object(
                        main.messagebox, "askyesno",
                        side_effect=ask_confirmation,
                    ):
                        self.run_event_loop_until(
                            lambda: handle.done_event.is_set()
                            and app.worker_handle is None
                        )

        self.assertEqual(ask_shutdown.call_count, 1)
        self.assertTrue(handle.result)
        self.assertFalse(handle.cancel_event.is_set())
        self.assertEqual(
            self.dialog_order,
            [
                "initial notification",
                "worker confirmation",
                "queued notification",
            ],
        )
        self.assertEqual(app._shutdown_state, "running")
        self.assertEqual(app._pending_modal_requests, [])

    def test_confirmed_shutdown_answers_pending_confirmation_and_summarizes_notice(self):
        app = self.make_app()
        app.gui_request_queue.put(
            tk_async_tasks.GuiRequest(
                kind="notification",
                payload={
                    "kind": "info",
                    "title": "initial notification",
                    "message": "first modal",
                },
            )
        )
        handle = self.start_confirmation_worker(app, "worker confirmation")

        def show_info(title, _message, **_kwargs):
            if title == "initial notification":
                self.run_nested_dialog(
                    "initial notification",
                    lambda: self.queue_during_active_modal(app),
                )
            else:
                self.run_nested_dialog(title)

        # ポーリング実行中に終了要求が出た際、root破棄ではなく
        # mainloop終了だけが要求されることを確認する。
        shutdown_diagnostics = {
            "events": [],
            "poll_depth": 0,
            "quit_poll_depth": None,
        }
        original_poll = app._poll_gui_requests
        original_schedule = app._schedule_gui_request_polling
        original_quit = app.master.quit
        original_register = tk.Misc._register
        original_deletecommand = tk.Misc.deletecommand
        original_after = tk.Misc.after
        original_after_cancel = tk.Misc.after_cancel
        tcl_lifecycle_events = []
        after_command_map = {}

        def widget_label(widget):
            try:
                return "{}:{}".format(type(widget).__name__, str(widget))
            except tk.TclError:
                return type(widget).__name__

        def callback_label(func):
            return getattr(func, "__name__", type(func).__name__)

        def record_register(widget, func, *args, **kwargs):
            command_name = original_register(widget, func, *args, **kwargs)
            tcl_lifecycle_events.append(
                ("register", widget_label(widget), command_name, callback_label(func))
            )
            return command_name

        def record_deletecommand(widget, command_name):
            tcl_lifecycle_events.append(
                ("deletecommand", widget_label(widget), command_name,
                 command_name in after_command_map.values())
            )
            return original_deletecommand(widget, command_name)

        def record_after(widget, ms, func=None, *args):
            after_id = original_after(widget, ms, func, *args)
            try:
                after_info = widget.tk.call("after", "info", after_id)
            except tk.TclError as exc:
                after_info = "inspection failed: {}".format(exc)
            command_name = None
            if isinstance(after_info, tuple) and after_info:
                command_name = after_info[0]
            after_command_map[after_id] = command_name
            tcl_lifecycle_events.append(
                ("after", widget_label(widget), after_id, ms,
                 callback_label(func) if func else None, command_name, after_info)
            )
            return after_id

        def record_after_cancel(widget, after_id):
            command_name = after_command_map.get(after_id)
            try:
                before = widget.tk.call("after", "info", after_id)
            except tk.TclError as exc:
                before = "inspection failed: {}".format(exc)
            tcl_lifecycle_events.append(
                ("after_cancel_before", widget_label(widget), after_id,
                 command_name, before)
            )
            result = original_after_cancel(widget, after_id)
            tcl_lifecycle_events.append(
                ("after_cancel_after", widget_label(widget), after_id, command_name)
            )
            return result

        def record_poll():
            shutdown_diagnostics["poll_depth"] += 1
            depth = shutdown_diagnostics["poll_depth"]
            shutdown_diagnostics["events"].append(
                ("poll_enter", depth, app._gui_poll_after_id, app._shutdown_state)
            )
            try:
                return original_poll()
            finally:
                shutdown_diagnostics["events"].append(
                    (
                        "poll_exit",
                        depth,
                        app._gui_poll_after_id,
                        app._shutdown_state,
                    )
                )
                shutdown_diagnostics["poll_depth"] -= 1

        def record_schedule():
            previous_id = app._gui_poll_after_id
            original_schedule()
            shutdown_diagnostics["events"].append(
                (
                    "schedule",
                    shutdown_diagnostics["poll_depth"],
                    previous_id,
                    app._gui_poll_after_id,
                    app._shutdown_state,
                )
            )

        def record_quit():
            shutdown_diagnostics["quit_poll_depth"] = (
                shutdown_diagnostics["poll_depth"]
            )
            shutdown_diagnostics["events"].append(
                ("quit", shutdown_diagnostics["poll_depth"], app._shutdown_state)
            )
            try:
                pending = []
                for after_id in self.root.tk.call("after", "info"):
                    pending.append(
                        (after_id, self.root.tk.call("after", "info", after_id))
                    )
            except tk.TclError as exc:
                pending = "inspection failed: {}".format(exc)
            tcl_lifecycle_events.append(
                ("quit_snapshot", pending, list(self.root._tclCommands or []))
            )
            return original_quit()

        app._poll_gui_requests = record_poll
        app._schedule_gui_request_polling = record_schedule
        app.master.quit = record_quit
        app._schedule_gui_request_polling()
        with patch.object(tk.Misc, "_register", record_register):
            with patch.object(tk.Misc, "deletecommand", record_deletecommand):
                with patch.object(tk.Misc, "after", record_after):
                    with patch.object(tk.Misc, "after_cancel", record_after_cancel):
                        with patch.object(
                            main.tk_notifications, "show_info", side_effect=show_info
                        ):
                            with patch.object(
                                main.messagebox, "askyesnocancel", return_value=True
                            ) as ask_shutdown:
                                with patch.object(
                                    main.messagebox, "askyesno"
                                ) as ask_worker_confirmation:
                                    with patch.object(
                                        main.messagebox, "showinfo"
                                    ) as show_summary:
                                        self.run_event_loop_until(
                                            lambda: app._shutdown_state == "closed"
                                        )

        self.assertEqual(ask_shutdown.call_count, 1)
        ask_worker_confirmation.assert_not_called()
        self.assertFalse(handle.result)
        self.assertTrue(handle.cancel_event.is_set())
        self.assertEqual(handle.cancel_reason, "application_shutdown")
        self.assertIsNone(app.worker_handle)
        self.assertEqual(app._shutdown_state, "closed")

        # mainloop()終了後、tearDown()によるroot.destroy()前のTcl状態を採取する。
        pending_after_ids = self.root.tk.call("after", "info")
        pending_after = []
        for after_id in pending_after_ids:
            try:
                pending_after.append(
                    (after_id, self.root.tk.call("after", "info", after_id))
                )
            except tk.TclError as exc:
                pending_after.append((after_id, "inspection failed: {}".format(exc)))
        try:
            poll_commands = self.root.tk.call(
                "info", "commands", "*poll_gui_requests*"
            )
        except tk.TclError as exc:
            poll_commands = "inspection failed: {}".format(exc)
        tcl_diagnostics = {
            "pending_after": pending_after,
            "poll_commands": poll_commands,
            "registered_tk_commands": list(self.root._tclCommands or []),
            "app_poll_after_id": app._gui_poll_after_id,
            "shutdown_state": app._shutdown_state,
            "root_exists": bool(self.root.winfo_exists()),
        }
        print(
            "Tk shutdown callback diagnostics: {!r}".format(
                shutdown_diagnostics
            )
        )
        print(
            "Tk post-mainloop Tcl diagnostics: {!r}".format(
                tcl_diagnostics
            )
        )
        print(
            "Tk Tcl command lifecycle events: {!r}".format(
                tcl_lifecycle_events
            )
        )
        self.assertEqual(
            shutdown_diagnostics["quit_poll_depth"],
            1,
            "ポーリングコールバック内からmainloop終了が要求されていません: {!r}".format(
                shutdown_diagnostics
            ),
        )
        self.assertTrue(
            self.root.winfo_exists(),
            "mainloop終了前にrootが破棄されています。",
        )
        self.assertEqual(len(app._shutdown_notifications), 1)
        self.assertEqual(
            app._shutdown_notifications[0]["title"], "queued notification"
        )
        show_summary.assert_called_once()
        self.assertIn(
            "queued notification",
            show_summary.call_args.args[1],
        )
        self.assertIn(
            "queued while modal was active",
            show_summary.call_args.args[1],
        )


if __name__ == "__main__":
    unittest.main()
