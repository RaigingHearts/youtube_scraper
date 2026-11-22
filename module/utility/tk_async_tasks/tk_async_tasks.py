"""
TkinterのGUIスレッドをブロックすることなく、時間のかかる処理をバックグラウンドで実行するためのモジュールスクリプト。
タスクの進捗状況をGUIにフィードバックしたり、完了時に結果をGUIに反映させたりするメカニズムを提供する。
Tkinterアプリケーション特化 / モジュールタイプ：ユーティリティモジュール

利用したいPythonスクリプトへインポートして利用可能:
"import tk_async_tasks"

メソッド構成:
├── "バックグラウンドタスクを実行し、GUIの進捗を更新する"
│   └── "def run_task_in_thread(task_function, gui_request_queue, *args, **kwargs):"
├── "GUIのプログレスバーとラベルを更新する（スレッドセーフな実処理）"
│   └── "def update_progress_gui(master_root, progress_label, progress_bar, current_comments, total_comments):"
├── "WorkerHandleが確認要求を登録し、要求固有のEventで応答を待つ"
│   └── "def WorkerHandle.request_confirmation(message):"
コピペ編集用罫線 '━┃┏┓┛┗┣┳┫┻╋' '─│┌┐┘└├┬┤┴┼'
"""
# tk_async_tasks.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
import uuid
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class GuiRequest:
    """ワーカーからメインスレッドへ渡すGUI要求。payloadにTkinterオブジェクトを含めない。"""

    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    response_event: Optional[threading.Event] = None
    response: Optional[bool] = None
    answered: bool = False
    response_reason: Optional[str] = None
    display_started: bool = False

    def __post_init__(self):
        if self.kind == "confirmation" and self.response_event is None:
            self.response_event = threading.Event()


@dataclass
class WorkerHandle:
    """一つのワーカー実行に関する状態・結果・同期オブジェクトを保持する。"""

    gui_request_queue: queue.Queue
    thread: Optional[threading.Thread] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    done_event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    exception: Optional[BaseException] = None
    partial_result: Dict[str, Any] = field(default_factory=lambda: {"saved_files": []})

    progress_lock: threading.Lock = field(default_factory=threading.Lock)
    latest_progress: Optional[Dict[str, Any]] = None
    progress_marker_queued: bool = False

    confirmation_lock: threading.Lock = field(default_factory=threading.Lock)
    pending_confirmations: Dict[str, GuiRequest] = field(default_factory=dict)

    shutdown_lock: threading.Lock = field(default_factory=threading.Lock)
    shutdown_decision_event: threading.Event = field(default_factory=threading.Event)
    shutdown_pending: bool = False
    save_policy: Optional[str] = None
    save_started: bool = False
    cancel_reason: Optional[str] = None
    exception_notification_queued: bool = False

    def publish_progress(self, progress: Dict[str, Any]) -> None:
        """最新進捗を保持し、未登録の場合だけキューマーカーを追加する。"""
        with self.progress_lock:
            self.latest_progress = progress
            if not self.progress_marker_queued:
                self.gui_request_queue.put(GuiRequest(kind="progress"))
                self.progress_marker_queued = True

    def take_latest_progress(self) -> Optional[Dict[str, Any]]:
        """最新進捗を取得し、次のマーカー登録を許可する。"""
        with self.progress_lock:
            progress = self.latest_progress
            self.progress_marker_queued = False
            return progress

    def request_confirmation(self, message: str) -> bool:
        """GUIへ確認を要求し、要求固有のEventで回答を待つ。"""
        request = GuiRequest(kind="confirmation", payload={"message": message})
        with self.confirmation_lock:
            if self.cancel_event.is_set():
                return False
            self.pending_confirmations[request.request_id] = request
            try:
                self.gui_request_queue.put(request)
            except BaseException:
                self.pending_confirmations.pop(request.request_id, None)
                raise
        try:
            request.response_event.wait()
            return bool(request.response)
        finally:
            with self.confirmation_lock:
                self.pending_confirmations.pop(request.request_id, None)

    def begin_shutdown_decision(self) -> str:
        """保存開始との競合を調停し、終了判断待ち状態を設定する。"""
        with self.shutdown_lock:
            if self.done_event.is_set():
                return "complete"
            if self.save_started:
                return "save_started"
            self.shutdown_pending = True
            self.shutdown_decision_event.clear()
            return "pending"

    def resolve_shutdown_decision(self, save_policy: Optional[str]) -> None:
        """終了判断を確定し、保存判断バリアで待つワーカーを解放する。"""
        if save_policy not in (None, "save_partial", "skip_additional_save"):
            raise ValueError("unsupported save_policy: {}".format(save_policy))
        with self.shutdown_lock:
            self.save_policy = save_policy
            self.shutdown_pending = False
            self.shutdown_decision_event.set()

    def begin_save(self) -> bool:
        """保存開始を終了判断と排他的に確定する。Falseなら追加保存を行わない。"""
        while True:
            with self.shutdown_lock:
                if self.shutdown_pending:
                    wait_for_decision = True
                else:
                    wait_for_decision = False
                    if self.save_policy == "skip_additional_save":
                        return False
                    self.save_started = True
                    return True
            if wait_for_decision:
                self.shutdown_decision_event.wait()

    def cancel_for_shutdown(self) -> None:
        """終了によるキャンセルを確定し、表示開始前の未回答確認要求をFalseで解除する。"""
        with self.confirmation_lock:
            if self.cancel_reason is None:
                self.cancel_reason = "application_shutdown"
            for request in list(self.pending_confirmations.values()):
                # 表示開始前の要求だけを終了処理が解除する。
                # 表示開始をLock内で確定した要求は、ダイアログ応答または
                # 表示例外によってGUI側が完了させる。
                if request.answered or request.display_started:
                    continue
                request.response = False
                request.response_reason = "application_shutdown"
                request.answered = True
                request.response_event.set()
            self.cancel_event.set()


def run_task_in_thread(task_function: Callable, gui_request_queue, *args, **kwargs) -> WorkerHandle:
    """
    ワーカーを起動し、実行状態・結果・例外を保持するWorkerHandleを返す。

    run_task_in_thread(task_function, gui_request_queue, *args, **kwargs)
    task_functionにはWorkerHandleを第1引数として渡す。
    """
    if not isinstance(gui_request_queue, queue.Queue):
        raise TypeError("gui_request_queue must be an instance of queue.Queue")

    actual_task_function = task_function
    task_name = getattr(actual_task_function, "__name__", repr(actual_task_function))
    handle = WorkerHandle(gui_request_queue=gui_request_queue)

    def worker_wrapper():
        try:
            handle.result = actual_task_function(handle, *args, **kwargs)
        except BaseException as exc:
            handle.exception = exc
            logger.exception("ワーカー '%s' の実行中に例外が発生しました。", task_name)
        finally:
            handle.done_event.set()
            logger.info("ワーカー '%s' が終了しました。", task_name)

    thread = threading.Thread(target=worker_wrapper, name="youtube-scraper-worker")
    thread.daemon = False
    handle.thread = thread

    logger.info("タスク '%s' を別スレッドで開始します。", task_name)
    try:
        thread.start()
    except BaseException:
        # 起動失敗はワーカー関数の例外終了として扱わず、呼び出し元へ伝播させる。
        handle.done_event.set()
        raise

    return handle

def update_progress_gui(master_root: tk.Tk, progress_label: ttk.Label, progress_bar: ttk.Progressbar, 
                        current_value: int, max_value: int | None = None, message: str | None = None):
    """
    GUIのプログレスバーとラベルを更新する（スレッドセーフな実処理）。
    この関数はメインスレッドから呼び出されることを想定しているが、
    別スレッドからの更新要求は `master_root.after()` を介して行う。

    Args:
        master_root (tk.Tk): Tkinterのルートウィンドウオブジェクト。
        progress_label (ttk.Label): 進捗メッセージを表示するラベルウィジェット。
        progress_bar (ttk.Progressbar): 進捗バーウィジェット。
        current_value (int): 現在の進捗値。
        max_value (int | None): 最大進捗値。Noneの場合、indeterminateモードになる。
        message (str | None): 表示する進捗メッセージ。Noneの場合、デフォルトメッセージ。
    """
    # Tkinterウィジェットの更新はメインスレッドで行う必要があるため、after()を使用
    master_root.after(0, _perform_gui_update, progress_label, progress_bar, current_value, max_value, message)

def _perform_gui_update(progress_label: ttk.Label, progress_bar: ttk.Progressbar, 
                        current_value: int, max_value: int | None, message: str | None):
    """
    GUI更新の実処理。`update_progress_gui`から`after()`経由で呼び出される。
    """
    if message:
        progress_label.config(text=message)
    
    if max_value is not None and max_value > 0:
        progress_bar.stop()
        progress_bar.config(mode="determinate", maximum=max_value, value=current_value)
        # 分子が分母に到達しても、取得処理全体の終了を意味しない。
        # 実際の完了表示は呼び出し元のタスク終了処理に任せる。
    else:
        # 最大値が不明な場合、indeterminateモードに
        if progress_bar["mode"] != "indeterminate":
            progress_bar.config(mode="indeterminate")
            progress_bar.start()
        if not message: # メッセージが指定されていない場合のみデフォルトメッセージ
             progress_label.config(text=f"処理中... ({current_value}件)")

    if current_value == 0 and max_value == 0: # 初期化状態
        progress_bar.stop()
        progress_bar.config(value=0, mode="determinate")
        progress_label.config(text="準備完了")


