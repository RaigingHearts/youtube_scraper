# main.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import os
import queue
import logging
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox
from typing import Any, Optional

logger = logging.getLogger(__name__)

# モジュールスクリプトのインポート設定
from module.manager.secure_settings import settings_manager  # 設定管理モジュール
from module.manager.tk_app_settings import \
    tk_app_settings  # アプリケーション設定管理モジュール (APIキープロンプトなど)
from module.single.file_operations import \
    file_operations  # ファイル・ディレクトリ操作モジュール (utilsから切り出し)
from module.single.json_data_handler import \
    json_data_handler  # JSONデータ操作ヘルパーモジュール (utilsから切り出し)
from module.single.youtube_utils import \
    youtube_utils  # YouTube関連ユーティリティモジュール (utilsから切り出し)
from module.utility.logger_config import logger_config, log_viewer  # ロギング設定・GUIログ表示
from module.utility.tk_async_tasks import \
    tk_async_tasks  # 非同期タスク実行モジュール (スレッド、進捗更新)
from module.utility.tk_notifications import \
    tk_notifications  # メッセージ/通知表示モジュール (メッセージボックス、ダイアログ)
from module.utility.youtube_api_client import \
    youtube_api_client  # YouTube Data APIクライアントモジュール


class YouTubeCommentScraperApp:
    def __init__(self, master: tk.Tk):
        """
        YouTubeコメント取得ツールのメインアプリケーションクラス。

        Args:
            master (tk.Tk): Tkinterのルートウィンドウオブジェクト。
        """
        self.master = master
        master.title("YouTubeコメント取得ツール")
        master.geometry("900x550")
        master.resizable(False, False)

        self.api_key: str | None = None
        self.total_comments_expected: int = 0  # APIから取得できるコメント総数の目安
        self.last_saved_comment_file_path: str | None = None  # 最後に保存したコメントファイルのパス
        self.last_saved_video_info_file_path: str | None = None  # 最後に保存した動画情報ファイルのパス
        self.last_saved_channel_info_file_path: str | None = None  # 最後に保存したチャンネル情報ファイルのパス
        self.last_saved_replies_file_path: str | None = None  # 最後に保存した返信コメントファイルのパス

        # Stage 1: GUI要求キューとワーカー参照をアプリケーション側で所有する。
        self.gui_request_queue = queue.Queue()
        self.worker_handle: Optional[tk_async_tasks.WorkerHandle] = None
        self._gui_poll_after_id = None
        self._dialog_active = False
        self._pending_modal_requests = []
        self._processing_pending_modal_requests = False
        self._shutdown_state = "running"
        self._shutdown_requested = False
        self._shutdown_notifications = []
        self._shutdown_summary_shown = False

        # アプリケーション起動時にAPIキーを確認・プロンプト
        self._initialize_api_key()
        
        # APIキーが取得できた場合のみGUIを構築
        if self.api_key:
            self._create_widgets()
            master.protocol("WM_DELETE_WINDOW", self._on_close_request)
            self._schedule_gui_request_polling()
        else:
            # APIキーが設定されなかった場合はアプリケーションを終了
            # tk_app_settingsですでにログ出力されているため、ここではGUIを破棄するのみ
            master.destroy()

    def _initialize_api_key(self):
        """APIキーが存在しない場合は入力ダイアログを表示し、設定する。"""
        # tk_app_settingsモジュールを使用してAPIキーの確認とプロンプトを行う
        self.api_key = tk_app_settings.check_and_prompt_api_key(self.master, self.api_key)
        # tk_app_settings内でdestroyは行わないため、ここでapi_keyがNoneの場合の処理を続ける
        if self.api_key:
            logger.info("APIキーが正常に設定されました。")
        else:
            logger.critical("APIキーが設定されませんでした。アプリケーションのGUIは構築されません。")
            # APIキーがない場合は_create_widgetsを呼び出さないため、ここで終了

    def _create_widgets(self):
        """GUIウィジェットを作成する。"""
        # フレーム設定
        input_frame = ttk.LabelFrame(self.master, text="動画情報入力", padding=(10, 10))
        input_frame.pack(padx=10, pady=10, fill="x", expand=True)

        progress_frame = ttk.LabelFrame(self.master, text="進行状況", padding=(10, 10))
        progress_frame.pack(padx=10, pady=10, fill="x", expand=True)

        result_frame = ttk.LabelFrame(self.master, text="結果と操作", padding=(10, 10))
        result_frame.pack(padx=10, pady=10, fill="x", expand=True)

        # 入力フレーム内のウィジェット
        ttk.Label(input_frame, text="YouTube URL:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.url_entry = ttk.Entry(input_frame, width=60)
        self.url_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.url_entry.bind("<Return>", self._parse_url_event)

        parse_button = ttk.Button(input_frame, text="URLから動画IDを解析", command=self._parse_url)
        parse_button.grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(input_frame, text="または 動画ID:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.video_id_entry = ttk.Entry(input_frame, width=60)
        self.video_id_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        self.scrape_button = ttk.Button(input_frame, text="コメント取得開始", command=self._start_scrape_process)
        self.scrape_button.grid(row=1, column=2, padx=5, pady=5)

        # 進行状況フレーム内のウィジェット
        self.progress_label = ttk.Label(progress_frame, text="準備完了")
        self.progress_label.pack(padx=5, pady=5, anchor="w")

        self.progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", length=600, mode="determinate")
        self.progress_bar.pack(padx=5, pady=5, fill="x")

        self.comment_count_label = ttk.Label(progress_frame, text="取得コメント数: 0 / 0")
        self.comment_count_label.pack(padx=5, pady=5, anchor="w")

        # 結果フレーム内のウィジェット
        self.open_json_button = ttk.Button(result_frame, text="取得完了JSONファイルを開く", command=self._open_json_file, state=tk.DISABLED)
        self.open_json_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.show_log_button = ttk.Button(result_frame, text="ログを表示", command=lambda: log_viewer.show_log_window(self.master))
        self.show_log_button.pack(side=tk.LEFT, padx=5, pady=5)

    def _parse_url_event(self, event: Any):
        """EnterキーでURL解析をトリガーする。"""
        self._parse_url()

    def _parse_url(self):
        """URLから動画IDを解析し、フィールドに設定する。"""
        url = self.url_entry.get().strip()
        if not url:
            tk_notifications.show_warning("入力エラー", "URLを入力してください。", parent=self.master)
            return

        video_id = youtube_utils.extract_video_id(url) # youtube_utilsを使用
        if video_id:
            self.video_id_entry.delete(0, tk.END)
            self.video_id_entry.insert(0, video_id)
            tk_notifications.show_info("解析完了", f"動画ID: {video_id} を解析しました。", parent=self.master)
        else:
            tk_notifications.show_error("解析失敗", "有効なYouTube URLではありません。", parent=self.master)
            logger.error(f"URL解析失敗: {url}")

    def _start_scrape_process(self):
        """コメント取得処理を別スレッドで開始する。"""
        if self.worker_handle is not None:
            logger.warning("前のワーカーの完了処理が残っているため、新規起動を拒否しました。")
            return
        if not self.api_key:
            tk_notifications.show_error("APIキーエラー", "APIキーが設定されていません。", parent=self.master)
            return

        video_id = self.video_id_entry.get().strip()
        if not video_id:
            tk_notifications.show_warning("入力エラー", "動画IDを入力してください。", parent=self.master)
            return

        if not youtube_utils.is_valid_video_id(video_id):
            tk_notifications.show_error(
                "入力エラー",
                "動画IDは11文字の英数字・ハイフン・アンダースコアで入力してください。",
                parent=self.master
            )
            logger.warning("不正な形式の動画IDが入力されました。")
            return

        # GUIの状態を更新
        self.scrape_button.config(state=tk.DISABLED)
        self.open_json_button.config(state=tk.DISABLED)
        tk_async_tasks._perform_gui_update(self.progress_label, self.progress_bar, 0, 0, "コメント取得中...") # 初期化メッセージ
        self.comment_count_label.config(text="取得コメント数: 0 / 0") # カウントもリセット

        self.last_saved_comment_file_path = None
        self.last_saved_video_info_file_path = None
        self.last_saved_channel_info_file_path = None
        self.last_saved_replies_file_path = None

        # WorkerHandleを保持し、完了・例外・GUI要求をメインスレッドで回収する。
        try:
            self.worker_handle = tk_async_tasks.run_task_in_thread(
                self._scrape_comments_task,
                self.gui_request_queue,
                video_id
            )
        except Exception as exc:
            logger.exception("ワーカーの起動に失敗しました。")
            self.scrape_button.config(state=tk.NORMAL)
            self.open_json_button.config(state=tk.NORMAL)
            tk_async_tasks._perform_gui_update(
                self.progress_label, self.progress_bar, 0, 0, "準備完了"
            )
            tk_notifications.show_error("起動失敗", str(exc), parent=self.master)

    def _scrape_comments_task(self, worker_handle: tk_async_tasks.WorkerHandle, video_id: str):
        """
        コメント取得のメイン処理（別スレッドで実行される）。
        ワーカーからGUIを操作せず、進捗・通知・保存結果をWorkerHandle経由で渡す。
        """
        logger.info("動画ID '%s' のコメント取得タスクを開始します。", video_id)

        api_key = self.api_key
        assert api_key is not None, "APIキーがNoneです。これは初期化で防がれるべきです。"

        saved_files = worker_handle.partial_result.setdefault("saved_files", [])
        worker_handle.partial_result["saved_files"] = saved_files

        def progress_callback(
            current_comments: int,
            total_comments: int | None,
            message: str
        ) -> None:
            worker_handle.publish_progress({
                "current_comments": current_comments,
                "total_comments": total_comments,
                "message": message,
            })

        def confirm_callback(message: str) -> bool:
            return worker_handle.request_confirmation(message)

        def save_file(kind: str, data: Any, filename: str) -> bool:
            """保存を試みたファイルの成否を、確定直後にpartial_resultへ記録する。"""
            path = os.path.join(output_dir, filename)
            error_message = None
            try:
                success = bool(
                    json_data_handler.save_json_to_file(
                        data, filename, output_dir=output_dir
                    )
                )
            except Exception as exc:
                success = False
                error_message = "{}: {}".format(type(exc).__name__, exc)
                logger.exception(
                    "%sの保存中に予期しない例外が発生しました。", kind
                )

            record = {
                "kind": kind,
                "path": path,
                "success": success,
            }
            if error_message:
                record["error"] = error_message
            saved_files.append(record)

            if success:
                logger.info("%sを '%s' に保存しました。", kind, path)
            else:
                logger.error("%sの保存に失敗しました。保存先: %s", kind, path)
            return success

        result_data, fetched_count, total_expected = youtube_api_client.fetch_all_comments(
            api_key,
            video_id,
            progress_callback=progress_callback,
            confirm_callback=confirm_callback,
            cancel_event=worker_handle.cancel_event,
        )

        # APIクライアントはGUIを操作せず、既存通知相当の分類情報を返す。
        for api_notification in result_data.get("notifications", []):
            worker_handle.gui_request_queue.put(
                tk_async_tasks.GuiRequest(
                    kind="notification",
                    payload={
                        "kind": api_notification.get("kind", "error"),
                        "title": api_notification.get("title", "APIエラー"),
                        "message": api_notification.get("message", ""),
                    },
                )
            )

        fetch_status = result_data.get("fetch_status", "failed")
        if fetch_status == "cancelled":
            with worker_handle.confirmation_lock:
                cancel_reason = worker_handle.cancel_reason
            if cancel_reason:
                result_data["cancel_reason"] = cancel_reason
        video_info_raw_response = result_data.get("video_info_raw_response", {})
        channel_info_raw_response = result_data.get("channel_info_raw_response", {})
        comment_threads_raw_responses = result_data.get(
            "comment_threads_raw_responses", []
        )
        comment_replies_raw_responses = result_data.get(
            "comment_replies_raw_responses", []
        )

        # 既存の保存先命名規則とファイル名・保存順を維持する。
        current_dir = (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__))
        )
        current_date = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
        output_folder_name = "youtube_data_{}_{}".format(video_id, current_date)
        output_dir = os.path.join(current_dir, output_folder_name)

        video_info_filename = "video_info_raw_{}.json".format(video_id)
        channel_info_filename = None
        comment_filename = "comments_raw_{}.json".format(video_id)
        replies_filename = "comment_replies_raw_{}.json".format(video_id)

        video_info_saved = False
        channel_info_saved = False
        comments_saved = False
        replies_saved = False

        channel_id = None
        if channel_info_raw_response and channel_info_raw_response.get("items"):
            channel_id = channel_info_raw_response["items"][0].get("id")

        has_save_data = bool(
            video_info_raw_response
            or channel_id
            or comment_threads_raw_responses
            or comment_replies_raw_responses
        )
        save_allowed = worker_handle.begin_save() if has_save_data else False
        with worker_handle.shutdown_lock:
            save_policy = worker_handle.save_policy
        shutdown_save_skipped = (
            has_save_data
            and not save_allowed
            and save_policy == "skip_additional_save"
        )

        if save_allowed and video_info_raw_response:
            video_info_saved = save_file(
                "video_info", video_info_raw_response, video_info_filename
            )

        if channel_id:
            if save_allowed:
                channel_info_filename = "channel_info_raw_{}.json".format(channel_id)
                channel_info_saved = save_file(
                    "channel_info", channel_info_raw_response, channel_info_filename
                )
        else:
            logger.warning(
                "チャンネルIDが不明なため、チャンネル情報Rawデータの保存はスキップされました。"
            )

        if save_allowed and comment_threads_raw_responses:
            comments_saved = save_file(
                "comments", comment_threads_raw_responses, comment_filename
            )

        if save_allowed and comment_replies_raw_responses:
            replies_saved = save_file(
                "replies", comment_replies_raw_responses, replies_filename
            )

        message_parts = []
        if comments_saved:
            message_parts.append(
                "ユニークコメント数: {} 件（保存するRawデータは重複レコードを保持） - '{}'".format(
                    fetched_count, comment_filename
                )
            )
        if replies_saved:
            message_parts.append(
                "返信コメントRawデータを '{}' に".format(replies_filename)
            )
        if video_info_saved:
            message_parts.append(
                "動画情報Rawデータを '{}' に".format(video_info_filename)
            )
        if channel_info_saved and channel_info_filename:
            message_parts.append(
                "チャンネル情報Rawデータを '{}' に".format(channel_info_filename)
            )

        saved_summary = (
            "、\n".join(message_parts)
            + "を '{}' フォルダに保存しました。".format(output_folder_name)
            if message_parts
            else "保存できたファイルはありません。"
        )
        if shutdown_save_skipped:
            saved_summary += "\nアプリケーション終了要求により追加保存は行っていません。"
        failed_records = [record for record in saved_files if not record["success"]]
        failure_summary = ""
        if failed_records:
            failure_summary = "\n\n保存に失敗したファイル: " + "、".join(
                os.path.basename(record["path"]) for record in failed_records
            )

        # APIクライアントが既に通知するAPIエラーをfetch_result["errors"]から
        # 再通知しない。ここではタスク状態・保存結果という別の事象だけを通知する。
        notification = None
        if fetch_status == "comments_disabled":
            notification = (
                "warning",
                "コメント取得不可",
                "この動画ではコメントがオフに設定されているため、コメントを取得できませんでした。\n"
                + saved_summary
                + failure_summary,
            )
        elif fetch_status == "cancelled":
            with worker_handle.confirmation_lock:
                cancel_reason = worker_handle.cancel_reason
            if cancel_reason == "application_shutdown":
                cancel_message = "アプリケーション終了要求により取得を中断しました。"
            elif cancel_reason == "continuation_declined":
                cancel_message = "継続確認で中止が選択されたため、取得を中断しました。"
            elif cancel_reason == "confirmation_unavailable":
                cancel_message = "継続確認ダイアログを表示できなかったため、取得を中断しました。"
            else:
                cancel_message = "ユーザー操作により取得を中断しました。"
            notification = (
                "warning",
                "取得中断",
                cancel_message + "\n"
                + saved_summary
                + failure_summary,
            )
        elif fetch_status == "partial":
            notification = (
                "warning",
                "部分取得",
                "一部のデータを取得できませんでした。保存結果は次のとおりです。\n"
                + saved_summary
                + failure_summary,
            )
        elif failed_records:
            notification = (
                "warning",
                "ファイル保存に一部失敗",
                "取得処理は終了しましたが、ファイルの保存に失敗しました。\n"
                + saved_summary
                + failure_summary,
            )
        elif fetch_status == "complete":
            notification = (
                "info",
                "取得完了",
                "コメントの取得処理が完了しました。\n"
                + saved_summary
                + failure_summary,
            )

        if notification is not None:
            notification_kind, title, message = notification
            worker_handle.gui_request_queue.put(
                tk_async_tasks.GuiRequest(
                    kind="notification",
                    payload={
                        "kind": notification_kind,
                        "title": title,
                        "message": message,
                    },
                )
            )

        # normal resultとpartial_resultの保存結果を一致させる。
        return {
            "fetch_result": result_data,
            "fetched_count": fetched_count,
            "total_expected": total_expected,
            "saved_files": list(saved_files),
            "output_folder_name": output_folder_name,
        }

    def _schedule_gui_request_polling(self):
        """GUI要求キューとワーカー状態をメインスレッドで定期確認する。"""
        if self._shutdown_state == "closed" or self._gui_poll_after_id is not None:
            return
        try:
            self._gui_poll_after_id = self.master.after(50, self._poll_gui_requests)
        except tk.TclError:
            self._gui_poll_after_id = None

    def _on_close_request(self):
        """ウィンドウ終了要求を一度だけ受け付ける。"""
        if self._shutdown_state not in ("running", "confirming"):
            return
        if self._dialog_active:
            self._shutdown_requested = True
            return
        self._begin_shutdown()

    def _begin_shutdown(self):
        """保存開始との競合を調停して終了方針を確認する。"""
        if self._shutdown_state != "running":
            return
        if self._dialog_active:
            self._shutdown_requested = True
            return

        # 終了処理の開始点で要求フラグを解除する。
        # モーダル表示終了直後からここへ到達するまではフラグを維持し、
        # 保留中のモーダル要求が終了確認より先に再表示されるのを防ぐ。
        self._shutdown_requested = False

        handle = self.worker_handle
        if handle is None:
            self._shutdown_state = "stopping"
            self._collect_pending_shutdown_requests()
            self._finalize_shutdown()
            return
        if handle.done_event.is_set():
            self._shutdown_state = "stopping"
            self._collect_pending_shutdown_requests()
            self._schedule_gui_request_polling()
            return

        decision_state = handle.begin_shutdown_decision()
        if decision_state == "complete":
            self._shutdown_state = "stopping"
            self._collect_pending_shutdown_requests()
            self._schedule_gui_request_polling()
            return

        self._shutdown_state = "shutdown_pending"
        if decision_state == "save_started":
            shutdown_message = (
                "保存処理はすでに開始されています。\n"
                "開始済みの保存は中断できず、はい／いいえの選択では変更されません。\n"
                "終了する場合ははい／いいえ、処理を続ける場合はキャンセルを選択してください。"
            )
        else:
            shutdown_message = (
                "コメント取得処理が実行中です。\n"
                "はい：取得済みデータを保存して終了\n"
                "いいえ：追加保存を行わず終了\n"
                "キャンセル：取得処理を続行"
            )
        self._dialog_active = True
        try:
            choice = messagebox.askyesnocancel(
                "終了確認",
                shutdown_message,
                parent=self.master,
            )
        except Exception:
            logger.exception("終了確認ダイアログの表示に失敗しました。")
            choice = None
        finally:
            self._dialog_active = False

        if choice is None:
            worker_still_running = handle.resolve_shutdown_decision(None)
            if not worker_still_running:
                self._shutdown_state = "stopping"
                self._collect_pending_shutdown_requests()
                self._schedule_gui_request_polling()
                return
            self._shutdown_state = "running"
            self._shutdown_requested = False
            self._drain_pending_modal_requests()
            self._schedule_gui_request_polling()
            return

        save_policy = (
            None if decision_state == "save_started"
            else ("save_partial" if choice else "skip_additional_save")
        )
        worker_still_running = handle.resolve_shutdown_decision(
            save_policy, cancel=True
        )
        self._shutdown_state = "stopping"
        self._collect_pending_shutdown_requests()
        self._schedule_gui_request_polling()

    def _collect_pending_shutdown_requests(self):
        """終了確定時に保留モーダル要求を通知サマリーへ移す。"""
        while self._pending_modal_requests:
            request = self._pending_modal_requests.pop(0)
            if request.kind == "notification":
                self._shutdown_notifications.append(request.payload)
            elif request.kind == "confirmation" and not request.answered:
                self._answer_confirmation(
                    request, False, "application_shutdown"
                )

    def _finalize_shutdown(self, completed_handle=None):
        """ワーカーとGUI要求の回収後、通知サマリー、Handle解放、root破棄を行う。"""
        if self._shutdown_state == "closed":
            return
        if self.worker_handle is not None and self.worker_handle is not completed_handle:
            return
        if completed_handle is not None:
            if not completed_handle.done_event.is_set():
                return
            if completed_handle.thread is not None and completed_handle.thread.is_alive():
                return
        elif self.worker_handle is None:
            self._shutdown_state = "complete"
        if not self.gui_request_queue.empty() or self._pending_modal_requests:
            return
        if self._dialog_active or self._processing_pending_modal_requests:
            return
        if self._gui_poll_after_id is not None:
            try:
                self.master.after_cancel(self._gui_poll_after_id)
            except tk.TclError:
                logger.debug("GUIポーリングの予約は既に解除されています。")
            self._gui_poll_after_id = None

        if self._shutdown_notifications and not self._shutdown_summary_shown:
            self._shutdown_summary_shown = True
            lines = []
            for index, notice in enumerate(self._shutdown_notifications, start=1):
                kind = str(notice.get("kind", "info")).upper()
                title = notice.get("title", "通知")
                message = notice.get("message", "")
                lines.append("{}. [{}] {}\n{}".format(index, kind, title, message))
            self._dialog_active = True
            try:
                messagebox.showinfo(
                    "終了時の通知",
                    "終了処理中に発生した通知です。\n\n" + "\n\n".join(lines),
                    parent=self.master,
                )
            except Exception:
                logger.exception("終了時通知サマリーの表示に失敗しました。")
            finally:
                self._dialog_active = False

        if completed_handle is not None and self.worker_handle is completed_handle:
            self.worker_handle = None
        self._shutdown_state = "closed"
        try:
            self.master.destroy()
        except tk.TclError:
            logger.debug("rootは既に破棄されています。")
        except Exception:
            logger.exception("rootの破棄中に予期しない例外が発生しました。")

    def _poll_gui_requests(self):
        """最大50件ずつGUI要求を処理し、残件があれば次回も確認する。"""
        if self._shutdown_state == "closed":
            return
        self._gui_poll_after_id = None
        self._drain_pending_modal_requests()
        processed = 0
        while processed < 50:
            try:
                request = self.gui_request_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            try:
                self._handle_gui_request(request)
            except Exception:
                logger.exception("GUI要求の処理中に例外が発生しました。")

        handle = self.worker_handle
        if handle is not None and handle.done_event.is_set() and self.gui_request_queue.empty():
            self._finish_worker(handle)

        if (
            self._shutdown_state in ("stopping", "complete")
            and self.worker_handle is None
            and self.gui_request_queue.empty()
            and not self._pending_modal_requests
        ):
            self._finalize_shutdown()

        # 上限到達時に残件がある場合も、次回ポーリングを必ず予約する。
        self._schedule_gui_request_polling()

    def _handle_gui_request(self, request: tk_async_tasks.GuiRequest):
        """要求種別に応じた処理をメインスレッドで振り分ける。"""
        if not isinstance(request, tk_async_tasks.GuiRequest):
            logger.warning("GuiRequest以外のオブジェクトを受信しました: %r", request)
            return

        if request.kind == "progress":
            handle = self.worker_handle
            progress = handle.take_latest_progress() if handle is not None else None
            if not progress:
                return
            current = progress.get("current_comments", progress.get("current_value", 0))
            total = progress.get("total_comments", progress.get("max_value"))
            message = progress.get("message")
            tk_async_tasks._perform_gui_update(
                self.progress_label, self.progress_bar, current, total, message
            )
            if hasattr(self, "comment_count_label"):
                count_text = (f"取得コメント数: {current} / {total}"
                              if total is not None else f"取得コメント数: {current} / 確定待ち")
                self.comment_count_label.config(text=count_text)
            return

        if request.kind == "notification":
            if self._shutdown_state == "shutdown_pending":
                self._pending_modal_requests.append(request)
                return
            if self._shutdown_state in ("stopping", "complete"):
                self._shutdown_notifications.append(request.payload)
                return
            if self._dialog_active:
                self._pending_modal_requests.append(request)
                return
            self._show_modal_request(request)
            return

        if request.kind == "confirmation":
            if self._shutdown_state in ("shutdown_pending", "stopping", "complete"):
                if self._shutdown_state != "shutdown_pending" and not request.answered:
                    self._answer_confirmation(
                        request, False, "application_shutdown"
                    )
                else:
                    self._pending_modal_requests.append(request)
                return
            if self._dialog_active:
                self._pending_modal_requests.append(request)
                return
            self._show_modal_request(request)
            return

        logger.warning("未知のGUI要求種別を受信しました: %s", request.kind)

    def _answer_confirmation(self, request, response: bool, response_reason: str) -> None:
        """確認応答を一度だけ確定し、要求固有Eventを解除する。"""
        handle = self.worker_handle
        if handle is None:
            # 終了処理が先に応答を確定していた場合、遅延したダイアログ応答で上書きしない。
            if request.answered:
                return
            if request.response_event is not None:
                request.response = False
                request.response_reason = "confirmation_unavailable"
                request.answered = True
                request.response_event.set()
            return
        with handle.confirmation_lock:
            if request.answered:
                return
            request.response = bool(response)
            request.response_reason = response_reason
            request.answered = True
            if not response and handle.cancel_reason is None:
                if response_reason == "user_response":
                    handle.cancel_reason = "continuation_declined"
                elif response_reason == "confirmation_unavailable":
                    handle.cancel_reason = "confirmation_unavailable"
                elif response_reason == "application_shutdown":
                    handle.cancel_reason = "application_shutdown"
            request.response_event.set()

    def _show_modal_request(self, request: tk_async_tasks.GuiRequest) -> None:
        """確認・通知ダイアログを直列表示し、ネストしたpoll再入を許容する。"""
        if self._dialog_active:
            self._pending_modal_requests.append(request)
            return
        self._dialog_active = True
        try:
            if request.kind == "confirmation":
                handle = self.worker_handle
                self._shutdown_state = "confirming"
                if request.answered:
                    return
                if handle is None:
                    self._answer_confirmation(request, False, "confirmation_unavailable")
                    return
                with handle.confirmation_lock:
                    already_answered = request.answered
                    shutdown_started = handle.cancel_event.is_set()
                    if not already_answered and not shutdown_started:
                        # このLock内で表示開始を確定し、終了処理との競合に境界を設ける。
                        request.display_started = True
                if already_answered:
                    return
                if shutdown_started:
                    self._answer_confirmation(request, False, "application_shutdown")
                else:
                    try:
                        answer = messagebox.askyesno(
                            "確認", request.payload.get("message", ""), parent=self.master
                        )
                        self._answer_confirmation(request, answer, "user_response")
                    except Exception:
                        logger.exception("継続確認ダイアログの表示に失敗しました。")
                        self._answer_confirmation(request, False, "confirmation_unavailable")
            else:
                payload = request.payload
                notification_kind = payload.get("kind", "info")
                title = payload.get("title", "通知")
                message = payload.get("message", "")
                try:
                    if notification_kind == "warning":
                        tk_notifications.show_warning(title, message, parent=self.master)
                    elif notification_kind == "error":
                        tk_notifications.show_error(title, message, parent=self.master)
                    else:
                        tk_notifications.show_info(title, message, parent=self.master)
                except Exception:
                    logger.exception("通知ダイアログの表示に失敗しました。")
        finally:
            self._dialog_active = False
            if self._shutdown_state == "confirming":
                self._shutdown_state = "running"
        if self._shutdown_requested and self._shutdown_state == "running":
            try:
                self.master.after_idle(self._begin_shutdown)
            except tk.TclError:
                logger.debug("終了要求の予約時にrootが破棄されていました。")
        if (
            not self._shutdown_requested
            and not self._processing_pending_modal_requests
        ):
            self._drain_pending_modal_requests()

    def _drain_pending_modal_requests(self) -> None:
        """保留中のモーダル要求をFIFO順に一件ずつ処理する。"""
        if (
            self._dialog_active
            or self._processing_pending_modal_requests
            or self._shutdown_requested
            or self._shutdown_state in ("shutdown_pending", "stopping", "complete", "closed")
        ):
            return
        self._processing_pending_modal_requests = True
        try:
            while (
                self._pending_modal_requests
                and not self._dialog_active
                and not self._shutdown_requested
            ):
                request = self._pending_modal_requests.pop(0)
                self._show_modal_request(request)
        finally:
            self._processing_pending_modal_requests = False

    def _finish_worker(self, handle: tk_async_tasks.WorkerHandle):
        """ワーカー結果・部分保存結果をメインスレッドで回収し、GUI状態を復旧する。"""
        if self.worker_handle is not handle or not handle.done_event.is_set():
            return
        if handle.thread is not None:
            handle.thread.join(timeout=0)
            if handle.thread.is_alive():
                return
        if (
            not self.gui_request_queue.empty()
            or self._dialog_active
            or self._pending_modal_requests
            or self._processing_pending_modal_requests
        ):
            return

        # ワーカー例外も通常通知と同じGUI要求経路へ載せ、モーダル表示を一元化する。
        if handle.exception is not None and not handle.exception_notification_queued:
            logger.error(
                "ワーカーが例外終了しました。",
                exc_info=(
                    type(handle.exception),
                    handle.exception,
                    handle.exception.__traceback__,
                ),
            )
            self.gui_request_queue.put(
                tk_async_tasks.GuiRequest(
                    kind="notification",
                    payload={
                        "kind": "error",
                        "title": "取得失敗",
                        "message": str(handle.exception),
                    },
                )
            )
            handle.exception_notification_queued = True
            return

        result = handle.result if isinstance(handle.result, dict) else {}
        if handle.exception is None:
            saved_files = result.get("saved_files", [])
        else:
            saved_files = handle.partial_result.get("saved_files", [])

        # GUI所有の保存先属性はメインスレッドでのみ更新する。
        path_attributes = {
            "video_info": "last_saved_video_info_file_path",
            "channel_info": "last_saved_channel_info_file_path",
            "comments": "last_saved_comment_file_path",
            "replies": "last_saved_replies_file_path",
        }
        valid_saved_paths = []
        for record in saved_files:
            if not isinstance(record, dict) or record.get("success") is not True:
                continue
            kind = record.get("kind")
            path = record.get("path")
            attribute = path_attributes.get(kind)
            if attribute is None or not isinstance(path, str) or not path:
                logger.warning("不正な保存結果レコードを無視しました: %r", record)
                continue
            setattr(self, attribute, path)
            valid_saved_paths.append(path)

        if handle.exception is None and "total_expected" in result:
            self.total_comments_expected = result["total_expected"]
        if handle.exception is None and "fetched_count" in result:
            fetched_count = result["fetched_count"]
            total_expected = result.get("total_expected")
            count_text = (
                "取得コメント数: {} / {}".format(fetched_count, total_expected)
                if total_expected is not None
                else "取得コメント数: {} / 確定待ち".format(fetched_count)
            )
            try:
                self.comment_count_label.config(text=count_text)
            except Exception:
                logger.exception("取得件数表示の復旧に失敗しました。")

        # 例外通知は上でGUI要求キューへ登録済み。ここでは結果回収とGUI復旧だけを行う。
        try:
            # 例外終了時もpartial_resultから復元した保存ファイルを利用可能にする。
            self.open_json_button.config(
                state=tk.NORMAL if valid_saved_paths else tk.DISABLED
            )
            self.scrape_button.config(state=tk.NORMAL)
            maximum = self.progress_bar["maximum"]
            tk_async_tasks._perform_gui_update(
                self.progress_label,
                self.progress_bar,
                maximum,
                maximum,
                "コメント取得処理終了",
            )
        except Exception:
            logger.exception("ワーカー完了後のGUI状態復旧に失敗しました。")
        finally:
            if self._shutdown_state in ("stopping", "complete"):
                self._shutdown_state = "complete"
            else:
                self.worker_handle = None

        if self._shutdown_state == "complete":
            self._finalize_shutdown(completed_handle=handle)

    def _open_json_file(self):
        """保存されたJSONファイルを開く。"""
        options = []
        if self.last_saved_comment_file_path:
            options.append(("コメントデータファイル", self.last_saved_comment_file_path))
        if self.last_saved_video_info_file_path:
            options.append(("動画情報Rawデータファイル", self.last_saved_video_info_file_path))
        if self.last_saved_channel_info_file_path:
            options.append(("チャンネル情報Rawデータファイル", self.last_saved_channel_info_file_path))
        if self.last_saved_replies_file_path:
            options.append(("返信コメントRawデータファイル", self.last_saved_replies_file_path))

        if not options:
            tk_notifications.show_warning("ファイルが見つかりません", "保存されたJSONファイルが見つかりませんでした。", parent=self.master)
            logger.warning("開くべきJSONファイルが見つかりませんでした。")
            return

        # tk_notificationsモジュールを使用してファイル選択ダイアログを表示
        selected_path = tk_notifications.show_file_selection_dialog(self.master, "ファイル選択", options)

        if selected_path:
            file_operations.open_file_in_default_app(selected_path) # file_operationsを使用
        else:
            logger.info("ファイル選択がキャンセルされました。")


def main() -> None:
    """アプリケーションを初期化してGUIを起動する。"""
    logger_config.configure_logging()
    settings_manager.initialize_settings()
    root = tk.Tk()
    YouTubeCommentScraperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
