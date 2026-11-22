# main.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import os
import queue
import logging
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
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

        # アプリケーション起動時にAPIキーを確認・プロンプト
        self._initialize_api_key()
        
        # APIキーが取得できた場合のみGUIを構築
        if self.api_key:
            self._create_widgets()
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
        youtube_api_clientと連携し、進捗をGUIに反映させる。
        """
        logger.info(f"動画ID '{video_id}' のコメント取得タスクを開始します。")

        # APIキーは_initialize_api_keyで設定済みのはず
        assert self.api_key is not None, "APIキーがNoneです。これは初期化で防がれるべきです。"

        # youtube_api_clientのコールバック関数を定義
        def progress_callback(current_comments: int, total_comments: int | None, message: str):
            tk_async_tasks.update_progress_gui(
                self.master, self.progress_label, self.progress_bar, 
                current_comments, total_comments, message
            )
            self.master.after(0, lambda: self.comment_count_label.config(
                text=(f"取得コメント数: {current_comments} / {total_comments}" if total_comments is not None else f"取得コメント数: {current_comments} / 確定待ち")
            ))

        def confirm_callback(message: str) -> bool:
            return tk_async_tasks.confirm_continuation_gui(self.master, message)

        result_data, fetched_count, total_expected = youtube_api_client.fetch_all_comments(
            self.api_key,
            video_id,
            progress_callback=progress_callback, # type:ignore
            confirm_callback=confirm_callback
        )
        
        self.total_comments_expected = total_expected

        fetch_status = result_data.get("fetch_status", "failed")
        fetch_errors = result_data.get("errors", [])
        if result_data:
            video_info_raw_response = result_data.get("video_info_raw_response", {})
            channel_info_raw_response = result_data.get("channel_info_raw_response", {})
            comment_threads_raw_responses = result_data.get("comment_threads_raw_responses", [])
            comment_replies_raw_responses = result_data.get("comment_replies_raw_responses", [])

            # --- 動画IDを名前にした専用フォルダを作成 ---
            current_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__)) # メインスクリプトのディレクトリを基準とする
            current_date = datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
            output_folder_name = f"youtube_data_{video_id}_{current_date}" # 例: youtube_data_dQw4w9WgXcQ
            output_dir = os.path.join(current_dir, output_folder_name)

            # json_data_handler.save_json_to_file がディレクトリ作成をサポートしているため、直接渡す
            # --- 動画情報ファイルの保存 ---
            video_info_filename = f"video_info_raw_{video_id}.json"
            video_info_saved = False
            if video_info_raw_response:
                if json_data_handler.save_json_to_file(video_info_raw_response, video_info_filename, output_dir=output_dir):
                    logger.info(f"動画情報Rawデータが '{os.path.join(output_dir, video_info_filename)}' に保存されました。")
                    self.last_saved_video_info_file_path = os.path.join(output_dir, video_info_filename)
                    video_info_saved = True
                else:
                    logger.error(f"動画情報Rawデータの保存に失敗しました。動画ID: {video_id}")

            # --- チャンネル情報ファイルの保存 ---
            channel_id = None
            channel_info_filename: Optional[str] = None 
            if channel_info_raw_response and channel_info_raw_response.get("items"):
                channel_id = channel_info_raw_response["items"][0].get("id")
            
            channel_info_saved = False
            if channel_id:
                channel_info_filename = f"channel_info_raw_{channel_id}.json"
                if json_data_handler.save_json_to_file(channel_info_raw_response, channel_info_filename, output_dir=output_dir):
                    logger.info(f"チャンネル情報Rawデータが '{os.path.join(output_dir, channel_info_filename)}' に保存されました。")
                    self.last_saved_channel_info_file_path = os.path.join(output_dir, channel_info_filename)
                    channel_info_saved = True
                else:
                    logger.error(f"チャンネル情報Rawデータの保存に失敗しました。チャンネルID: {channel_id}")
            else:
                logger.warning(f"チャンネルIDが不明なため、チャンネル情報Rawデータの保存はスキップされました。")

            # --- コメントデータファイルの保存 ---
            comment_filename = f"comments_raw_{video_id}.json"
            comments_saved = False
            if comment_threads_raw_responses:
                if json_data_handler.save_json_to_file(comment_threads_raw_responses, comment_filename, output_dir=output_dir):
                    logger.info(f"コメントデータが '{os.path.join(output_dir, comment_filename)}' に保存されました。")
                    self.last_saved_comment_file_path = os.path.join(output_dir, comment_filename)
                    comments_saved = True
                else:
                    logger.error(f"コメントデータの保存に失敗しました。動画ID: {video_id}")

            # --- 返信コメントデータファイルの保存 ---
            replies_saved = False
            replies_filename = f"comment_replies_raw_{video_id}.json"
            if comment_replies_raw_responses:
                if json_data_handler.save_json_to_file(
                    comment_replies_raw_responses, replies_filename, output_dir=output_dir
                ):
                    logger.info(f"返信コメントRawデータが '{os.path.join(output_dir, replies_filename)}' に保存されました。"
                    )
                    self.last_saved_replies_file_path = os.path.join(output_dir, replies_filename)
                    replies_saved = True
                else:
                    logger.error(f"返信コメントRawデータの保存に失敗しました。動画ID: {video_id}")

            # 最終的なメッセージ表示ロジック
            message_parts = []
            if comments_saved:
                message_parts.append(
                    f"ユニークコメント数: {fetched_count} 件"
                    f"（保存するRawデータは重複レコードを保持）"
                    f" - '{comment_filename}'"
                )
            if replies_saved:
                message_parts.append(f"返信コメントRawデータを '{replies_filename}' に")
            if video_info_saved:
                message_parts.append(f"動画情報Rawデータを '{video_info_filename}' に")
            if channel_info_saved:
                if channel_info_filename: #type:ignore
                    message_parts.append(f"チャンネル情報Rawデータを '{channel_info_filename}' に")

            if message_parts:
                saved_summary = "、\n".join(message_parts) + f"を '{output_folder_name}' フォルダに保存しました。"
                error_summary = "\n".join(error.get("message", "") for error in fetch_errors)
                if fetch_status == "comments_disabled":
                    tk_notifications.show_warning(
                        "コメント取得不可",
                        "この動画ではコメントがオフに設定されているため、コメントを取得できませんでした。\n"
                        + (
                            "取得済みのコメントデータは保存されています。\n"
                            if comments_saved else "コメントデータは保存されていません。\n"
                        ) + saved_summary,
                        parent=self.master
                    )
                elif fetch_status == "complete":
                    tk_notifications.show_info("取得完了", "コメントの取得が正常に完了しました。\n" + saved_summary, parent=self.master)
                elif fetch_status == "cancelled":
                    cancellation_message = "ユーザー操作により取得を中断しました。取得済みデータを保存しました。\n" + saved_summary
                    if error_summary:
                        cancellation_message += "\n\n取得中に発生したエラー:\n" + error_summary
                    tk_notifications.show_warning("取得中断", cancellation_message, parent=self.master)
                elif fetch_status == "partial":
                    tk_notifications.show_warning("部分取得", "一部のデータを取得できませんでした。保存済みデータは部分的な内容です。\n" + saved_summary + (f"\n\nエラー:\n{error_summary}" if error_summary else ""), parent=self.master)
                else:
                    tk_notifications.show_error("取得失敗", "必要なデータを取得できませんでした。取得済みデータのみ保存しました。\n" + saved_summary + (f"\n\nエラー:\n{error_summary}" if error_summary else ""), parent=self.master)
                self.master.after(0, lambda: self.open_json_button.config(state=tk.NORMAL))
            else:
                error_summary = "\n".join(error.get("message", "") for error in fetch_errors)
                if fetch_status == "comments_disabled":
                    tk_notifications.show_warning(
                        "コメント取得不可",
                        "この動画ではコメントがオフに設定されているため、コメントを取得できませんでした。"
                        + ("\n\n" + error_summary if error_summary else ""),
                        parent=self.master
                    )
                elif fetch_status == "cancelled":
                    cancellation_message = "取得を中断しました。保存できるデータはありませんでした。"
                    if error_summary:
                        cancellation_message += "\n\n取得中に発生したエラー:\n" + error_summary
                    tk_notifications.show_warning("取得中断", cancellation_message, parent=self.master)
                else:
                    tk_notifications.show_error("取得失敗", "データを保存できませんでした。\n" + error_summary, parent=self.master)

        else:
            logger.error(f"コメントの取得に失敗しました。動画ID: {video_id}")
            error_summary = "\n".join(error.get("message", "") for error in fetch_errors)
            tk_notifications.show_error("取得失敗", error_summary or "コメントの取得に失敗しました。ログを確認してください。", parent=self.master)

    def _schedule_gui_request_polling(self):
        """GUI要求キューとワーカー状態をメインスレッドで定期確認する。"""
        if self._gui_poll_after_id is not None:
            return
        try:
            self._gui_poll_after_id = self.master.after(50, self._poll_gui_requests)
        except tk.TclError:
            self._gui_poll_after_id = None

    def _poll_gui_requests(self):
        """最大50件ずつGUI要求を処理し、残件があれば次回も確認する。"""
        self._gui_poll_after_id = None
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
            payload = request.payload
            notification_kind = payload.get("kind", "info")
            title = payload.get("title", "通知")
            message = payload.get("message", "")
            if notification_kind == "warning":
                tk_notifications.show_warning(title, message, parent=self.master)
            elif notification_kind == "error":
                tk_notifications.show_error(title, message, parent=self.master)
            else:
                tk_notifications.show_info(title, message, parent=self.master)
            return

        if request.kind == "confirmation":
            # 継続確認のダイアログ処理はStage 3で導入する。現段階では待機を残さない。
            handle = self.worker_handle
            if handle is not None:
                with handle.confirmation_lock:
                    if not request.answered:
                        request.response = False
                        request.response_reason = "confirmation_unavailable"
                        request.answered = True
                        if request.response_event is not None:
                            request.response_event.set()
            elif request.response_event is not None:
                request.response = False
                request.response_reason = "confirmation_unavailable"
                request.answered = True
                request.response_event.set()
            logger.warning("Stage 3実装前の継続確認要求をFalseで解除しました。")
            return

        logger.warning("未知のGUI要求種別を受信しました: %s", request.kind)

    def _finish_worker(self, handle: tk_async_tasks.WorkerHandle):
        """完了情報をGUIスレッドで回収し、GUI状態を復旧する。"""
        if self.worker_handle is not handle or not handle.done_event.is_set():
            return
        if not self.gui_request_queue.empty():
            return

        try:
            if handle.exception is not None:
                logger.error("ワーカーが例外終了しました。",
                             exc_info=(type(handle.exception), handle.exception, handle.exception.__traceback__))
                try:
                    tk_notifications.show_error("取得失敗", str(handle.exception), parent=self.master)
                except Exception:
                    logger.exception("ワーカー例外の通知表示に失敗しました。")
        finally:
            # 通知表示の成否にかかわらずGUI状態を復旧してからWorkerHandleを解放する。
            self.scrape_button.config(state=tk.NORMAL)
            maximum = self.progress_bar["maximum"]
            try:
                tk_async_tasks._perform_gui_update(
                    self.progress_label, self.progress_bar, maximum, maximum, "コメント取得処理終了"
                )
            finally:
                self.worker_handle = None


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
