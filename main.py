# main.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Any, Optional

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
from module.utility.logger_config import \
    logger_config  # ロギングモジュール (旧 log_manager)
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

        # アプリケーション起動時にAPIキーを確認・プロンプト
        self._initialize_api_key()
        
        # APIキーが取得できた場合のみGUIを構築
        if self.api_key:
            self._create_widgets()
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
            logger_config.log_message('info', "APIキーが正常に設定されました。")
        else:
            logger_config.log_message('critical', "APIキーが設定されませんでした。アプリケーションのGUIは構築されません。")
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

        self.show_log_button = ttk.Button(result_frame, text="ログを表示", command=logger_config.show_log_window)
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
            logger_config.log_message('error', f"URL解析失敗: {url}")

    def _start_scrape_process(self):
        """コメント取得処理を別スレッドで開始する。"""
        if not self.api_key:
            tk_notifications.show_error("APIキーエラー", "APIキーが設定されていません。", parent=self.master)
            return

        video_id = self.video_id_entry.get().strip()
        if not video_id:
            tk_notifications.show_warning("入力エラー", "動画IDを入力してください。", parent=self.master)
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

        # tk_async_tasksモジュールを使用して、コメント取得処理を別スレッドで実行
        tk_async_tasks.run_task_in_thread(
            self.master, 
            self._scrape_comments_task, 
            video_id
        )

    def _scrape_comments_task(self, video_id: str):
        """
        コメント取得のメイン処理（別スレッドで実行される）。
        youtube_api_clientと連携し、進捗をGUIに反映させる。
        """
        logger_config.log_message('info', f"動画ID '{video_id}' のコメント取得タスクを開始します。")

        # APIキーは_initialize_api_keyで設定済みのはず
        assert self.api_key is not None, "APIキーがNoneです。これは初期化で防がれるべきです。"

        # youtube_api_clientのコールバック関数を定義
        def progress_callback(current_comments: int, total_comments: int, message: str):
            tk_async_tasks.update_progress_gui(
                self.master, self.progress_label, self.progress_bar, 
                current_comments, total_comments, message
            )
            self.master.after(0, lambda: self.comment_count_label.config(
                text=f"取得コメント数: {current_comments} / {total_comments}"
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
                    logger_config.log_message('info', f"動画情報Rawデータが '{os.path.join(output_dir, video_info_filename)}' に保存されました。")
                    self.last_saved_video_info_file_path = os.path.join(output_dir, video_info_filename)
                    video_info_saved = True
                else:
                    logger_config.log_message('error', f"動画情報Rawデータの保存に失敗しました。動画ID: {video_id}")

            # --- チャンネル情報ファイルの保存 ---
            channel_id = None
            channel_info_filename: Optional[str] = None 
            if channel_info_raw_response and channel_info_raw_response.get("items"):
                channel_id = channel_info_raw_response["items"][0].get("id")
            
            channel_info_saved = False
            if channel_id:
                channel_info_filename = f"channel_info_raw_{channel_id}.json"
                if json_data_handler.save_json_to_file(channel_info_raw_response, channel_info_filename, output_dir=output_dir):
                    logger_config.log_message('info', f"チャンネル情報Rawデータが '{os.path.join(output_dir, channel_info_filename)}' に保存されました。")
                    self.last_saved_channel_info_file_path = os.path.join(output_dir, channel_info_filename)
                    channel_info_saved = True
                else:
                    logger_config.log_message('error', f"チャンネル情報Rawデータの保存に失敗しました。チャンネルID: {channel_id}")
            else:
                logger_config.log_message('warning', f"チャンネルIDが不明なため、チャンネル情報Rawデータの保存はスキップされました。")

            # --- コメントデータファイルの保存 ---
            comment_filename = f"comments_raw_{video_id}.json"
            comments_saved = False
            if comment_threads_raw_responses:
                if json_data_handler.save_json_to_file(comment_threads_raw_responses, comment_filename, output_dir=output_dir):
                    logger_config.log_message('info', f"コメントデータが '{os.path.join(output_dir, comment_filename)}' に保存されました。")
                    self.last_saved_comment_file_path = os.path.join(output_dir, comment_filename)
                    comments_saved = True
                else:
                    logger_config.log_message('error', f"コメントデータの保存に失敗しました。動画ID: {video_id}")

            # --- 返信コメントデータファイルの保存 ---
            replies_saved = False
            replies_filename = f"comment_replies_raw_{video_id}.json"
            if comment_replies_raw_responses:
                if json_data_handler.save_json_to_file(
                    comment_replies_raw_responses, replies_filename, output_dir=output_dir
                ):
                    logger_config.log_message(
                        'info',
                        f"返信コメントRawデータが '{os.path.join(output_dir, replies_filename)}' に保存されました。"
                    )
                    self.last_saved_replies_file_path = os.path.join(output_dir, replies_filename)
                    replies_saved = True
                else:
                    logger_config.log_message('error', f"返信コメントRawデータの保存に失敗しました。動画ID: {video_id}")

            # 最終的なメッセージ表示ロジック
            message_parts = []
            if comments_saved:
                message_parts.append(f"{fetched_count} 件のコメントを '{comment_filename}' に")
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
                if fetch_status == "complete":
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
                if fetch_status == "cancelled":
                    cancellation_message = "取得を中断しました。保存できるデータはありませんでした。"
                    if error_summary:
                        cancellation_message += "\n\n取得中に発生したエラー:\n" + error_summary
                    tk_notifications.show_warning("取得中断", cancellation_message, parent=self.master)
                else:
                    tk_notifications.show_error("取得失敗", "データを保存できませんでした。\n" + error_summary, parent=self.master)

        else:
            logger_config.log_message('error', f"コメントの取得に失敗しました。動画ID: {video_id}")
            error_summary = "\n".join(error.get("message", "") for error in fetch_errors)
            tk_notifications.show_error("取得失敗", error_summary or "コメントの取得に失敗しました。ログを確認してください。", parent=self.master)

        # 処理完了後のGUI状態を更新
        self.master.after(0, lambda: self.scrape_button.config(state=tk.NORMAL))
        self.master.after(0, lambda: tk_async_tasks._perform_gui_update(
            self.progress_label, self.progress_bar, 
            self.progress_bar["maximum"], self.progress_bar["maximum"], # 完了状態に設定
            "コメント取得処理終了"
        ))


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
            logger_config.log_message('warning', "開くべきJSONファイルが見つかりませんでした。")
            return

        # tk_notificationsモジュールを使用してファイル選択ダイアログを表示
        selected_path = tk_notifications.show_file_selection_dialog(self.master, "ファイル選択", options)

        if selected_path:
            file_operations.open_file_in_default_app(selected_path) # file_operationsを使用
        else:
            logger_config.log_message('info', "ファイル選択がキャンセルされました。")


if __name__ == "__main__":
    root = tk.Tk()
    app = YouTubeCommentScraperApp(root)
    root.mainloop()
