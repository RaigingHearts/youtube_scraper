"""実Tkイベントループ上でStage 3・4の連携を検証する統合テスト。"""

import json
import os
import queue
import tempfile
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
        # 各テストの開始からroot破棄まで、Tkコールバックの登録・削除を追跡する。
        self.tk_callback_trace = []
        self.tk_after_commands = {}
        self.tk_trace_patchers = []
        original_register = tk.Misc._register
        original_deletecommand = tk.Misc.deletecommand
        original_after = tk.Misc.after
        original_after_cancel = tk.Misc.after_cancel

        def callback_name(func):
            return getattr(func, "__name__", type(func).__name__)

        def trace_register(widget, func, *args, **kwargs):
            command_name = original_register(widget, func, *args, **kwargs)
            self.tk_callback_trace.append(
                ("register", str(widget), command_name, callback_name(func))
            )
            return command_name

        def trace_deletecommand(widget, command_name):
            self.tk_callback_trace.append(
                ("deletecommand", str(widget), command_name,
                 command_name in self.tk_after_commands.values())
            )
            return original_deletecommand(widget, command_name)

        def trace_after(widget, ms, func=None, *args):
            after_id = original_after(widget, ms, func, *args)
            try:
                info = widget.tk.call("after", "info", after_id)
            except tk.TclError as exc:
                info = "inspection failed: {}".format(exc)
            command_name = info[0] if isinstance(info, tuple) and info else None
            self.tk_after_commands[after_id] = command_name
            self.tk_callback_trace.append(
                ("after", str(widget), after_id, ms,
                 callback_name(func) if func else None, command_name, info)
            )
            return after_id

        def trace_after_cancel(widget, after_id):
            try:
                info = widget.tk.call("after", "info", after_id)
            except tk.TclError as exc:
                info = "inspection failed: {}".format(exc)
            self.tk_callback_trace.append(
                ("after_cancel", str(widget), after_id,
                 self.tk_after_commands.get(after_id), info)
            )
            return original_after_cancel(widget, after_id)

        for method_name, replacement in (
            ("_register", trace_register),
            ("deletecommand", trace_deletecommand),
            ("after", trace_after),
            ("after_cancel", trace_after_cancel),
        ):
            patcher = patch.object(tk.Misc, method_name, replacement)
            patcher.start()
            self.tk_trace_patchers.append(patcher)

    def tearDown(self):
        root = getattr(self, "root", None)
        try:
            if root is not None:
                # root.destroy()前に未処理タイマーを採取し、テスト間への持ち越しを防ぐ。
                try:
                    pending_ids = list(root.tk.call("after", "info"))
                    pending = [
                        (after_id, root.tk.call("after", "info", after_id))
                        for after_id in pending_ids
                    ]
                    commands = list(root._tclCommands or [])
                except tk.TclError as exc:
                    pending_ids = []
                    pending = "inspection failed: {}".format(exc)
                    commands = []
                relevant_events = [
                    event for event in self.tk_callback_trace
                    if "_poll_gui_requests" in repr(event)
                ]

                # after / after_idle の予約を先に取り消し、対応するTclコマンドも削除する。
                if root.winfo_exists():
                    for after_id in pending_ids:
                        try:
                            root.after_cancel(after_id)
                        except tk.TclError:
                            pass

                try:
                    remaining_after = list(root.tk.call("after", "info"))
                except tk.TclError as exc:
                    remaining_after = "inspection failed: {}".format(exc)

                if relevant_events or pending:
                    print(
                        "Tk test-wide callback trace: {!r}".format(
                            {
                                "poll_callback_events": relevant_events,
                                "pending_after_before_cleanup": pending,
                                "pending_after_after_cleanup": remaining_after,
                                "registered_commands_before_cleanup": commands,
                            }
                        )
                    )
                try:
                    if root.winfo_exists():
                        root.destroy()
                except tk.TclError:
                    pass
        finally:
            for patcher in reversed(getattr(self, "tk_trace_patchers", [])):
                patcher.stop()

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
        with patch.object(tk.Misc, "_register", record_register):
            with patch.object(tk.Misc, "deletecommand", record_deletecommand):
                with patch.object(tk.Misc, "after", record_after):
                    with patch.object(tk.Misc, "after_cancel", record_after_cancel):
                        # 初回予約も監視対象に含め、登録から終了までの履歴を連続させる。
                        app._schedule_gui_request_polling()
                        try:
                            initial_pending = [
                                (after_id, self.root.tk.call("after", "info", after_id))
                                for after_id in self.root.tk.call("after", "info")
                            ]
                        except tk.TclError as exc:
                            initial_pending = "inspection failed: {}".format(exc)
                        tcl_lifecycle_events.append(
                            (
                                "initial_schedule_snapshot",
                                initial_pending,
                                list(self.root._tclCommands or []),
                            )
                        )
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



    def test_real_event_loop_interleaves_worker_progress_notifications_and_confirmation(self):
        app = self.make_app()
        main_thread_id = threading.current_thread().ident

        first_dialog_opened = threading.Event()
        second_requests_queued = threading.Event()

        observed_requests = []
        confirmation_requests = []
        pending_kinds_during_first_modal = []
        progress_updates = []
        notification_thread_ids = []
        confirmation_thread_ids = []
        worker_completion_snapshots = []

        modal_depth = {"current": 0, "maximum": 0}

        original_put = app.gui_request_queue.put
        original_finish_worker = app._finish_worker

        def observe_put(request, *args, **kwargs):
            result = original_put(request, *args, **kwargs)
            if isinstance(request, tk_async_tasks.GuiRequest):
                observed_requests.append(request)
                if request.kind == "confirmation":
                    confirmation_requests.append(request)
                    second_requests_queued.set()
            return result

        def record_finish_worker(worker_handle):
            worker_completion_snapshots.append(
                {
                    "queue_empty": app.gui_request_queue.empty(),
                    "pending_modal_requests": list(
                        app._pending_modal_requests
                    ),
                    "dialog_active": app._dialog_active,
                    "processing_pending": (
                        app._processing_pending_modal_requests
                    ),
                }
            )
            return original_finish_worker(worker_handle)

        app.gui_request_queue.put = observe_put
        app._finish_worker = record_finish_worker

        def task(handle):
            handle.publish_progress({
                "current_comments": 3,
                "total_comments": 10,
                "message": "first worker progress",
            })

            handle.gui_request_queue.put(
                tk_async_tasks.GuiRequest(
                    kind="notification",
                    payload={
                        "kind": "info",
                        "title": "initial notification",
                        "message": "first worker notification",
                    },
                )
            )

            if not first_dialog_opened.wait(2):
                raise RuntimeError(
                    "最初の通知ダイアログが開かれませんでした。"
                )

            handle.gui_request_queue.put(
                tk_async_tasks.GuiRequest(
                    kind="notification",
                    payload={
                        "kind": "info",
                        "title": "additional notification",
                        "message": "notification queued during first modal",
                    },
                )
            )

            confirmed = handle.request_confirmation(
                "continue after queued notifications"
            )
            if not confirmed:
                raise RuntimeError(
                    "確認要求が肯定応答されませんでした。"
                )

            handle.publish_progress({
                "current_comments": 7,
                "total_comments": 10,
                "message": "second worker progress",
            })

            return {
                "confirmed": confirmed,
                "status": "completed",
            }

        handle = tk_async_tasks.run_task_in_thread(
            task, app.gui_request_queue
        )
        app.worker_handle = handle

        def open_recorded_dialog(name, on_open=None):
            modal_depth["current"] += 1
            modal_depth["maximum"] = max(
                modal_depth["maximum"], modal_depth["current"]
            )
            try:
                self.run_nested_dialog(name, on_open)
            finally:
                modal_depth["current"] -= 1

        def show_notification(title, _message, **_kwargs):
            notification_thread_ids.append(
                threading.current_thread().ident
            )

            if title == "initial notification":
                def collect_requests_while_modal_is_active():
                    first_dialog_opened.set()

                    # ワーカーが追加通知と確認要求を登録するまでEventで同期する。
                    queued = second_requests_queued.wait(2)
                    if queued:
                        # 実際のポーリング処理で両要求を保留キューへ取り込む。
                        app._poll_gui_requests()
                        pending_kinds_during_first_modal.extend(
                            request.kind
                            for request in app._pending_modal_requests
                        )

                open_recorded_dialog(
                    title, collect_requests_while_modal_is_active
                )
            else:
                open_recorded_dialog(title)

        def ask_confirmation(*_args, **_kwargs):
            confirmation_thread_ids.append(
                threading.current_thread().ident
            )
            open_recorded_dialog("worker confirmation")
            return True

        def record_progress(
            _label, _bar, current, total, message
        ):
            progress_updates.append(
                (
                    current,
                    total,
                    message,
                    threading.current_thread().ident,
                )
            )

        app._schedule_gui_request_polling()

        try:
            with patch.object(
                main.tk_notifications,
                "show_info",
                side_effect=show_notification,
            ):
                with patch.object(
                    main.messagebox,
                    "askyesno",
                    side_effect=ask_confirmation,
                ):
                    with patch.object(
                        tk_async_tasks,
                        "_perform_gui_update",
                        side_effect=record_progress,
                    ):
                        self.run_event_loop_until(
                            lambda: handle.done_event.is_set()
                            and app.worker_handle is None
                            and app.gui_request_queue.empty()
                            and not app._pending_modal_requests
                        )
        finally:
            # 途中失敗時にも確認待ちワーカーを残さない。
            if handle.thread is not None and handle.thread.is_alive():
                handle.cancel_for_shutdown()
                handle.thread.join(timeout=2)

        def contains_tk_object(value):
            if isinstance(value, tk.Misc):
                return True
            if isinstance(value, dict):
                return any(
                    contains_tk_object(item)
                    for item in value.values()
                )
            if isinstance(value, (list, tuple, set)):
                return any(
                    contains_tk_object(item) for item in value
                )
            return False

        self.assertEqual(
            pending_kinds_during_first_modal,
            ["notification", "confirmation"],
        )
        self.assertEqual(
            self.dialog_order,
            [
                "initial notification",
                "additional notification",
                "worker confirmation",
            ],
        )
        self.assertEqual(modal_depth["maximum"], 1)
        self.assertEqual(modal_depth["current"], 0)

        self.assertEqual(
            [
                (current, message)
                for current, _total, message, _thread_id in progress_updates
                if message in (
                    "first worker progress",
                    "second worker progress",
                )
            ],
            [
                (3, "first worker progress"),
                (7, "second worker progress"),
            ],
        )
        self.assertTrue(progress_updates)
        self.assertTrue(
            all(
                thread_id == main_thread_id
                for _current, _total, _message, thread_id in progress_updates
            )
        )

        self.assertEqual(len(notification_thread_ids), 2)
        self.assertTrue(
            all(
                thread_id == main_thread_id
                for thread_id in notification_thread_ids
            )
        )
        self.assertEqual(
            confirmation_thread_ids,
            [main_thread_id],
        )

        self.assertEqual(
            [request.kind for request in observed_requests],
            [
                "progress",
                "notification",
                "notification",
                "confirmation",
                "progress",
            ],
        )
        self.assertTrue(
            all(
                not contains_tk_object(request.payload)
                for request in observed_requests
            ),
            "GUI要求payloadにTkinterオブジェクトが含まれています。",
        )

        self.assertEqual(len(confirmation_requests), 1)
        confirmation = confirmation_requests[0]
        self.assertTrue(confirmation.answered)
        self.assertTrue(confirmation.response)
        self.assertTrue(confirmation.response_event.is_set())
        self.assertEqual(confirmation.response_reason, "user_response")

        self.assertTrue(handle.done_event.is_set())
        self.assertIsNone(handle.exception)
        self.assertEqual(
            handle.result,
            {
                "confirmed": True,
                "status": "completed",
            },
        )
        self.assertIsNotNone(handle.thread)
        self.assertFalse(handle.thread.is_alive())

        self.assertTrue(worker_completion_snapshots)
        self.assertTrue(
            all(
                snapshot["queue_empty"]
                and not snapshot["pending_modal_requests"]
                and not snapshot["dialog_active"]
                and not snapshot["processing_pending"]
                for snapshot in worker_completion_snapshots
            ),
            "GUI要求の処理完了前にワーカー完了処理が開始されました。",
        )

        self.assertIsNone(app.worker_handle)
        self.assertTrue(app.gui_request_queue.empty())
        self.assertEqual(app._pending_modal_requests, [])
        self.assertFalse(app._dialog_active)
        self.assertFalse(app._processing_pending_modal_requests)


    def test_real_event_loop_preserves_visible_confirmation_before_shutdown(self):
        app = self.make_app()
        confirmation_queued = threading.Event()
        confirmation_returned = threading.Event()
        confirmation_requests = []
        shutdown_prompt_observations = []
        close_request_observations = []
        modal_depth = {"current": 0, "maximum": 0}

        original_put = app.gui_request_queue.put

        def observe_put(request, *args, **kwargs):
            result = original_put(request, *args, **kwargs)
            if getattr(request, "kind", None) == "confirmation":
                confirmation_requests.append(request)
                confirmation_queued.set()
            return result

        app.gui_request_queue.put = observe_put

        def task(handle):
            answer = handle.request_confirmation(
                "continue before application shutdown"
            )
            confirmation_returned.set()
            if not handle.cancel_event.wait(2):
                raise RuntimeError(
                    "終了確定後のキャンセル通知を受信できませんでした。"
                )
            return answer

        handle = tk_async_tasks.run_task_in_thread(
            task, app.gui_request_queue
        )
        app.worker_handle = handle
        self.assertTrue(
            confirmation_queued.wait(2),
            "ワーカーの確認要求がキューへ登録されませんでした。",
        )
        confirmation = confirmation_requests[0]

        def show_nested_dialog(name, on_open=None):
            modal_depth["current"] += 1
            modal_depth["maximum"] = max(
                modal_depth["maximum"], modal_depth["current"]
            )
            try:
                self.run_nested_dialog(name, on_open)
            finally:
                modal_depth["current"] -= 1

        def ask_worker_confirmation(*_args, **_kwargs):
            def request_shutdown_while_confirmation_is_visible():
                app._on_close_request()
                close_request_observations.append(
                    (
                        app._shutdown_requested,
                        app._dialog_active,
                        app._shutdown_state,
                    )
                )

            show_nested_dialog(
                "worker confirmation",
                request_shutdown_while_confirmation_is_visible,
            )
            return True

        def ask_shutdown_confirmation(*_args, **_kwargs):
            worker_resumed = confirmation_returned.wait(2)
            shutdown_prompt_observations.append(
                {
                    "worker_resumed": worker_resumed,
                    "answered": confirmation.answered,
                    "response": confirmation.response,
                    "response_reason": confirmation.response_reason,
                    "response_event_set": confirmation.response_event.is_set(),
                    "cancel_event_set": handle.cancel_event.is_set(),
                    "shutdown_state": app._shutdown_state,
                    "dialog_active": app._dialog_active,
                }
            )
            show_nested_dialog("shutdown confirmation")
            return True

        app._schedule_gui_request_polling()
        try:
            with patch.object(
                main.messagebox,
                "askyesno",
                side_effect=ask_worker_confirmation,
            ) as ask_worker:
                with patch.object(
                    main.messagebox,
                    "askyesnocancel",
                    side_effect=ask_shutdown_confirmation,
                ) as ask_shutdown:
                    self.run_event_loop_until(
                        lambda: handle.done_event.is_set()
                        and app.worker_handle is None
                        and app._shutdown_state == "closed"
                    )
        finally:
            if handle.thread is not None and handle.thread.is_alive():
                handle.cancel_for_shutdown()
                handle.thread.join(timeout=2)

        ask_worker.assert_called_once()
        ask_shutdown.assert_called_once()
        self.assertEqual(
            close_request_observations,
            [(True, True, "confirming")],
        )
        self.assertEqual(
            shutdown_prompt_observations,
            [
                {
                    "worker_resumed": True,
                    "answered": True,
                    "response": True,
                    "response_reason": "user_response",
                    "response_event_set": True,
                    "cancel_event_set": False,
                    "shutdown_state": "shutdown_pending",
                    "dialog_active": True,
                }
            ],
        )
        self.assertEqual(
            self.dialog_order,
            ["worker confirmation", "shutdown confirmation"],
        )
        self.assertEqual(modal_depth["maximum"], 1)
        self.assertEqual(modal_depth["current"], 0)

        self.assertTrue(confirmation.display_started)
        self.assertTrue(confirmation.answered)
        self.assertIs(confirmation.response, True)
        self.assertEqual(confirmation.response_reason, "user_response")
        self.assertTrue(confirmation.response_event.is_set())

        self.assertTrue(handle.cancel_event.is_set())
        self.assertEqual(handle.cancel_reason, "application_shutdown")
        self.assertTrue(handle.done_event.is_set())
        self.assertIsNone(handle.exception)
        self.assertIs(handle.result, True)
        self.assertIsNotNone(handle.thread)
        self.assertFalse(handle.thread.is_alive())
        self.assertEqual(handle.pending_confirmations, {})

        self.assertIsNone(app.worker_handle)
        self.assertEqual(app._shutdown_state, "closed")
        self.assertFalse(app._dialog_active)
        self.assertEqual(app._pending_modal_requests, [])
        self.assertTrue(app.gui_request_queue.empty())
        self.assertTrue(self.root.winfo_exists())
        self.assertIsNone(app._gui_poll_after_id)


    def test_real_event_loop_saves_video_response_returned_after_shutdown_request(self):
        app = self.make_app()
        app.api_key = "integration-test-api-key"

        api_execute_started = threading.Event()
        release_api_execute = threading.Event()
        api_execute_returned = threading.Event()
        dialog_observations = []
        shutdown_observations = []
        video_response = {
            "items": [{
                "id": "video-1",
                "snippet": {
                    "channelId": "channel-1",
                    "title": "integration video",
                },
            }]
        }

        service = MagicMock()

        def execute_video_request():
            api_execute_started.set()
            if not release_api_execute.wait(5):
                raise RuntimeError("API execute release event timed out")
            api_execute_returned.set()
            return video_response

        service.videos.return_value.list.return_value.execute.side_effect = (
            execute_video_request
        )

        def ask_shutdown_confirmation(*_args, **_kwargs):
            def observe_visible_shutdown_dialog():
                dialog_observations.append({
                    "api_execute_returned": api_execute_returned.is_set(),
                    "worker_done": handle.done_event.is_set(),
                    "cancel_event_set": handle.cancel_event.is_set(),
                    "shutdown_state": app._shutdown_state,
                })

            self.run_nested_dialog(
                "shutdown confirmation",
                observe_visible_shutdown_dialog,
            )
            return True

        def request_shutdown_during_api_call():
            app._on_close_request()
            shutdown_observations.append({
                "api_execute_returned": api_execute_returned.is_set(),
                "worker_done": handle.done_event.is_set(),
                "cancel_event_set": handle.cancel_event.is_set(),
                "save_policy": handle.save_policy,
                "shutdown_state": app._shutdown_state,
            })
            # 終了確認と終了方針の確定後、Tkイベントループ上の別コールバックで
            # API応答を解放する。通信中にGUIが応答できたことも同時に確認する。
            self.root.after_idle(release_api_execute.set)

        app._schedule_gui_request_polling()

        try:
            with patch.object(
                main.youtube_api_client,
                "get_youtube_service",
                return_value=service,
            ) as get_service:
                with patch.object(
                    main.json_data_handler,
                    "save_json_to_file",
                    return_value=True,
                ) as save_json:
                    with patch.object(
                        main.messagebox,
                        "askyesnocancel",
                        side_effect=ask_shutdown_confirmation,
                    ) as ask_shutdown:
                        with patch.object(
                            main.messagebox, "showinfo"
                        ) as shutdown_summary:
                            # APIクライアントのモックを適用した状態でワーカーを起動する。
                            handle = tk_async_tasks.run_task_in_thread(
                                app._scrape_comments_task,
                                app.gui_request_queue,
                                "abcdefghijk",
                            )
                            app.worker_handle = handle

                            self.assertTrue(
                                api_execute_started.wait(2),
                                "ワーカーが動画情報APIのexecute()へ到達しませんでした。",
                            )
                            self.root.after_idle(request_shutdown_during_api_call)

                            self.run_event_loop_until(
                                lambda: handle.done_event.is_set()
                                and app.worker_handle is None
                                and app._shutdown_state == "closed"
                            )
        finally:
            release_api_execute.set()
            if handle.thread is not None and handle.thread.is_alive():
                handle.thread.join(timeout=2)

        get_service.assert_called_once_with(
            "integration-test-api-key",
            error_callback=unittest.mock.ANY,
        )
        service.videos.return_value.list.assert_called_once_with(
            part="snippet", id="abcdefghijk"
        )
        service.videos.return_value.list.return_value.execute.assert_called_once_with()
        service.channels.return_value.list.assert_not_called()
        service.commentThreads.return_value.list.assert_not_called()
        service.comments.return_value.list.assert_not_called()

        ask_shutdown.assert_called_once()
        self.assertEqual(
            dialog_observations,
            [{
                "api_execute_returned": False,
                "worker_done": False,
                "cancel_event_set": False,
                "shutdown_state": "shutdown_pending",
            }],
        )
        self.assertEqual(
            shutdown_observations,
            [{
                "api_execute_returned": False,
                "worker_done": False,
                "cancel_event_set": True,
                "save_policy": "save_partial",
                "shutdown_state": "stopping",
            }],
        )
        self.assertTrue(api_execute_returned.is_set())
        self.assertTrue(handle.cancel_event.is_set())
        self.assertEqual(handle.cancel_reason, "application_shutdown")

        self.assertIsNone(handle.exception)
        self.assertTrue(handle.done_event.is_set())
        self.assertIsNotNone(handle.thread)
        self.assertFalse(handle.thread.is_alive())
        self.assertEqual(handle.result["fetch_result"]["fetch_status"], "cancelled")
        self.assertEqual(
            handle.result["fetch_result"]["cancel_reason"],
            "application_shutdown",
        )
        self.assertIs(
            handle.result["fetch_result"]["video_info_raw_response"],
            video_response,
        )
        self.assertEqual(
            handle.result["fetch_result"]["channel_info_raw_response"], {}
        )
        self.assertEqual(
            handle.result["fetch_result"]["comment_threads_raw_responses"], []
        )

        save_json.assert_called_once()
        self.assertIs(save_json.call_args.args[0], video_response)
        self.assertEqual(
            handle.result["saved_files"],
            handle.partial_result["saved_files"],
        )
        self.assertEqual(len(handle.result["saved_files"]), 1)
        self.assertEqual(handle.result["saved_files"][0]["kind"], "video_info")
        self.assertTrue(handle.result["saved_files"][0]["success"])
        shutdown_summary.assert_called_once()

        self.assertIsNone(app.worker_handle)
        self.assertEqual(app._shutdown_state, "closed")
        self.assertTrue(app.gui_request_queue.empty())
        self.assertEqual(app._pending_modal_requests, [])
        self.assertFalse(app._dialog_active)
        self.assertIsNone(app._gui_poll_after_id)
        self.assertTrue(self.root.winfo_exists())


    def test_real_event_loop_restores_saved_json_open_workflow(self):
        app = self.make_app()
        app.api_key = "integration-test-api-key"
        video_id = "abcdefghijk"
        video_response = {
            "items": [{
                "id": video_id,
                "snippet": {
                    "title": "saved integration video",
                    "channelId": "channel-1",
                },
            }]
        }
        fetch_result = {
            "fetch_status": "complete",
            "video_info_raw_response": video_response,
            "channel_info_raw_response": {},
            "comment_threads_raw_responses": [],
            "comment_replies_raw_responses": [],
            "notifications": [],
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            virtual_main_file = os.path.join(
                temporary_directory, "application", "main.py"
            )
            expected_output_directory = os.path.join(
                temporary_directory,
                "application",
                "youtube_data_{}_{}".format(
                    video_id, main.datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
                ),
            )

            with patch.object(
                main, "__file__", virtual_main_file
            ):
                with patch.object(
                    main.youtube_api_client,
                    "fetch_all_comments",
                    return_value=(fetch_result, 0, 0),
                ) as fetch_comments:
                    with patch.object(
                        main.tk_notifications, "show_info"
                    ) as show_info:
                        handle = tk_async_tasks.run_task_in_thread(
                            app._scrape_comments_task,
                            app.gui_request_queue,
                            video_id,
                        )
                        app.worker_handle = handle
                        app._schedule_gui_request_polling()
                        self.run_event_loop_until(
                            lambda: handle.done_event.is_set()
                            and app.worker_handle is None
                        )

            fetch_comments.assert_called_once()
            self.assertIsNone(handle.exception)
            self.assertFalse(handle.thread.is_alive())
            self.assertEqual(handle.result["fetch_result"], fetch_result)
            self.assertEqual(len(handle.result["saved_files"]), 1)

            saved_record = handle.result["saved_files"][0]
            expected_filename = "video_info_raw_{}.json".format(video_id)
            expected_path = os.path.join(
                expected_output_directory, expected_filename
            )
            self.assertEqual(
                saved_record,
                {
                    "kind": "video_info",
                    "path": expected_path,
                    "success": True,
                },
            )
            self.assertTrue(os.path.isfile(expected_path))
            with open(expected_path, "r", encoding="utf-8") as saved_file:
                self.assertEqual(json.load(saved_file), video_response)

            self.assertEqual(
                app.last_saved_video_info_file_path, expected_path
            )
            self.assertIsNone(app.last_saved_comment_file_path)
            self.assertIsNone(app.last_saved_channel_info_file_path)
            self.assertIsNone(app.last_saved_replies_file_path)
            app.open_json_button.config.assert_any_call(state=tk.NORMAL)
            app.scrape_button.config.assert_any_call(state=tk.NORMAL)
            show_info.assert_called_once()

            selected_paths = []

            def select_saved_file(_parent, _title, options):
                self.assertEqual(
                    options,
                    [("動画情報Rawデータファイル", expected_path)],
                )
                return expected_path

            with patch.object(
                main.tk_notifications,
                "show_file_selection_dialog",
                side_effect=select_saved_file,
            ) as select_file:
                with patch.object(
                    main.file_operations,
                    "open_file_in_default_app",
                    side_effect=lambda path: selected_paths.append(path) or True,
                ) as open_file:
                    app._open_json_file()

            select_file.assert_called_once_with(
                self.root,
                "ファイル選択",
                [("動画情報Rawデータファイル", expected_path)],
            )
            open_file.assert_called_once_with(expected_path)
            self.assertEqual(selected_paths, [expected_path])


if __name__ == "__main__":
    unittest.main()
