"""
TkinterのGUIスレッドをブロックすることなく、時間のかかる処理をバックグラウンドで実行するためのモジュールスクリプト。
タスクの進捗状況をGUIにフィードバックしたり、完了時に結果をGUIに反映させたりするメカニズムを提供する。
Tkinterアプリケーション特化 / モジュールタイプ：ユーティリティモジュール

利用したいPythonスクリプトへインポートして利用可能:
"import tk_async_tasks"

メソッド構成:
├── "バックグラウンドタスクを実行し、GUIの進捗を更新する"
│   └── "def run_task_in_thread(master_root, task_function, *args, **kwargs):"
├── "GUIのプログレスバーとラベルを更新する（スレッドセーフな実処理）"
│   └── "def update_progress_gui(master_root, progress_label, progress_bar, current_comments, total_comments):"
├── "ユーザーに続行を確認するダイアログを表示する（スレッドセーフ）"
│   └── "def confirm_continuation_gui(master_root, message):"
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
from tkinter import ttk, messagebox
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


def run_task_in_thread(task_function: Callable, gui_request_queue, *args, **kwargs) -> WorkerHandle:
    """
    ワーカーを起動し、実行状態・結果・例外を保持するWorkerHandleを返す。

    新方式:
        run_task_in_thread(task_function, gui_request_queue, *args, **kwargs)
        task_functionにはWorkerHandleを第1引数として渡す。

    旧方式:
        run_task_in_thread(master_root, task_function, *args, **kwargs)
        移行期間中の既存呼び出しではWorkerHandleをタスクへ渡さず、従来どおり実行する。
    """
    legacy_call = isinstance(task_function, tk.Misc)
    if legacy_call:
        legacy_task_function = gui_request_queue
        request_queue = queue.Queue()
        actual_task_function = legacy_task_function
    else:
        if not isinstance(gui_request_queue, queue.Queue):
            raise TypeError("gui_request_queue must be an instance of queue.Queue")
        request_queue = gui_request_queue
        actual_task_function = task_function

    task_name = getattr(actual_task_function, "__name__", repr(actual_task_function))
    handle = WorkerHandle(gui_request_queue=request_queue)

    def worker_wrapper():
        try:
            if legacy_call:
                handle.result = actual_task_function(*args, **kwargs)
            else:
                handle.result = actual_task_function(handle, *args, **kwargs)
        except BaseException as exc:
            handle.exception = exc
            logger.exception("ワーカー '%s' の実行中に例外が発生しました。", task_name)
        finally:
            handle.done_event.set()
            logger.info("ワーカー '%s' が終了しました。", task_name)

    thread = threading.Thread(target=worker_wrapper, name="youtube-scraper-worker")
    thread.daemon = True  # 非daemon化は終了制御を実装するStage 4で行う。
    handle.thread = thread

    logger.info("タスク '%s' を別スレッドで開始します。", task_name)
    try:
        thread.start()
    except BaseException:
        # 起動失敗はワーカー関数の例外終了として扱わず、呼び出し元へ伝播させる。
        handle.done_event.set()
        raise

    return handle

def update_progress_gui(master_root, progress_label, progress_bar, current_comments, total_comments):"
├── "ユーザーに続行を確認するダイアログを表示する（スレッドセーフ）"
│   └── "def confirm_continuation_gui(master_root, message):"
コピペ編集用罫線 '━┃┏┓┛┗┣┳┫┻╋' '─│┌┐┘└├┬┤┴┼'
"""
# tk_async_tasks.py # コピーペースト作業での識別用。除去しないこと
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Any
# ログ出力のためにlogger_configをインポート
import logging

logger = logging.getLogger(__name__)

def run_task_in_thread(master_root: tk.Tk, task_function: Callable, *args, **kwargs):
    """
    時間のかかるタスクを別スレッドで実行し、GUIをブロックしないようにする。

    Args:
        master_root (tk.Tk): Tkinterのルートウィンドウオブジェクト。
        task_function (Callable): 別スレッドで実行する関数。
        *args: task_functionに渡す位置引数。
        **kwargs: task_functionに渡すキーワード引数。
    """
    logger.info(f"タスク '{task_function.__name__}' を別スレッドで開始します。")
    thread = threading.Thread(target=task_function, args=args, kwargs=kwargs)
    thread.daemon = True # メインスレッド終了時にサブスレッドも終了するように設定
    thread.start()

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


def confirm_continuation_gui(master_root: tk.Tk, message: str) -> bool:
    """
    ユーザーに続行を確認するダイアログを表示する（スレッドセーフ）。
    別スレッドから呼び出された場合でも、GUIスレッドでダイアログを表示し、結果を待つ。

    Args:
        master_root (tk.Tk): Tkinterのルートウィンドウオブジェクト。
        message (str): 確認ダイアログに表示するメッセージ。

    Returns:
        bool: ユーザーが「はい」を選択した場合はTrue、それ以外はFalse。
    """
    # Tkinterダイアログはメインスレッドで実行する必要があるため、
    # BooleanVarとafter()、wait_variable()を組み合わせて同期的に結果を取得する。
    result_var = tk.BooleanVar(master_root)
    
    def show_dialog():
        answer = messagebox.askyesno("確認", message, parent=master_root)
        result_var.set(answer)

    master_root.after(0, show_dialog) # メインスレッドでダイアログを表示
    master_root.wait_variable(result_var) # ダイアログの結果を待つ
    
    return result_var.get()

# コピペ用メソッドコードの例 (使用例として)
"""
# モジュールのインポート設定
import tk_async_tasks
import logger_config
import tkinter as tk
from tkinter import ttk, messagebox

class YourApplication:
    def __init__(self, master):
        self.master = master
        # 進捗表示用のウィジェットを準備
        self.progress_label = ttk.Label(master, text="準備完了")
        self.progress_label.pack()
        self.progress_bar = ttk.Progressbar(master, orient="horizontal", length=200, mode="determinate")
        self.progress_bar.pack()
        
        ttk.Button(master, text="タスク開始", command=self._start_my_task).pack()

    def _start_my_task(self):
        # GUIを初期状態に戻す
        tk_async_tasks.update_progress_gui(self.master, self.progress_label, self.progress_bar, 0, 0, "タスク開始中...")
        
        # 時間のかかるタスクを別スレッドで実行
        tk_async_tasks.run_task_in_thread(
            self.master, 
            self._my_long_running_task, 
            "arg1", "arg2", 
            progress_callback=self._on_task_progress,
            confirm_callback=self._on_task_confirm
        )

    def _my_long_running_task(self, param1, param2, progress_callback, confirm_callback):
        # ここに時間のかかる処理を記述
        logger.info(f"長時間タスク開始: {param1}, {param2}")
        total_items = 100
        for i in range(total_items):
            # 処理の進捗をGUIに通知
            progress_callback(i + 1, total_items, f"処理中... ({i+1}/{total_items})")
            
            # 例: APIクォータ制限に近づいた場合にユーザーに確認
            if i == 50:
                if not confirm_callback("50%完了しました。続行しますか？"):
                    logger.info("ユーザーがタスクを中断しました。")
                    break
            
            # 実際の処理（例: 時間のかかる計算やI/O）
            import time
            time.sleep(0.05)
        
        logger.info("長時間タスク完了。")
        # 最終的なGUI更新（完了メッセージなど）
        tk_async_tasks.update_progress_gui(self.master, self.progress_label, self.progress_bar, total_items, total_items, "タスク完了！")

    def _on_task_progress(self, current, total, message):
        # _my_long_running_taskから呼び出される進捗更新コールバック
        tk_async_tasks.update_progress_gui(self.master, self.progress_label, self.progress_bar, current, total, message)

    def _on_task_confirm(self, message):
        # _my_long_running_taskから呼び出される確認コールバック
        return tk_async_tasks.confirm_continuation_gui(self.master, message)

# アプリケーション実行部分
if __name__ == "__main__":
    root = tk.Tk()
    root.title("非同期タスクテスト")
    app = YourApplication(root)
    root.mainloop()
"""
