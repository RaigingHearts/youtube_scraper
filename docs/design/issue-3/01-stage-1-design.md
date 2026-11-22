# Issue #3：Stage 1 詳細設計 — GUI要求基盤とワーカー管理

## 1. 目的
ワーカーからメインスレッドへGUI要求を渡す共通基盤を用意する。進捗・通知・継続確認の具体的な移行は後続Stageで行う。

## 2. 責務
### main.py
GUI要求キューの生成・所有、WorkerHandleの保持、メインスレッドでのポーリング、要求振り分け、ワーカー終了監視、WorkerHandleに格納された戻り値・例外の回収を担当する。Stage 1では戻り値をWorkerHandle.resultから回収可能な状態にすることまでを基盤責務とし、取得結果の内容をGUI所有状態へ反映する処理はStage 2で実装する。

### tk_async_tasks.py
GuiRequest、WorkerHandle、ワーカー生成・実行管理を定義する。既存関数・旧方式は全呼び出し箇所の移行が完了するまで互換性を保ち、移行完了後に削除する。

## 3. GuiRequest
共通属性はkind、payload、request_idとする。kindはprogress、notification、confirmation。confirmationではresponse_event、response、answeredを追加で保持する。payloadにTkinterウィジェット、Tk変数、rootを含めない。各種payloadの具体的なキーは09-cross-stage-interface.mdに従う。

## 4. WorkerHandle
基本属性はthread、gui_request_queue、cancel_event、done_event、result、exception。追加属性は最新進捗情報、進捗Lock、進捗マーカー登録済みフラグ、確認要求管理、終了判断用Lock/Event、終了判断待ちフラグ、保存方針、保存開始状態、保存途中結果partial_result、cancel_reasonを含む。partial_resultは保存処理開始前に初期化し、少なくともsaved_filesの空リストを持つ。実装上の属性名・初期値は共通インターフェース仕様書を正とする。

## 5. 起動関数
run_task_in_thread(task_function, gui_request_queue, *args, **kwargs) -> WorkerHandleを用意する。ワーカー関数にはWorkerHandleを第1引数として渡す。ラッパーは戻り値をresultへ格納し、例外をexceptionへ格納してログに記録し、成功・失敗のどちらでもfinallyでdone_eventを設定する。thread参照とWorkerHandleを呼び出し元が保持できる状態にしてから開始する。Thread.start()失敗は握りつぶさず呼び出し元へ伝え、done_eventを設定し、main.pyがGUI状態を復旧できるようにする。起動失敗時に通常のワーカー完了処理と混同しない。

## 6. ポーリング
main.pyがメインスレッド上でroot.after()を使って監視する。初期値は50ms間隔、1回最大50件。1要求の処理例外や未知の要求種別で後続要求・次回ポーリングを止めない。上限件数に達した時点でキューに残件があれば、次回ポーリングを必ず予約する。root破棄後はafter()を登録しない。

## 7. ワーカー管理
同時実行ワーカーは1つ。既存ワーカーの実行中、または完了後処理が終わる前は新規起動しない。done_event後もGUI要求・result・exception・保存結果を回収するまではWorkerHandleを解放しない。Stage 1では既存daemon設定を維持し、非daemon化はStage 4の終了制御と同時に行う。

## 8. 結果・例外の受け渡し
WorkerHandle.resultはワーカー関数の戻り値をそのまま保持し、exceptionは未処理例外を保持する。Stage 1では、これらをメインスレッド側から回収できるライフサイクル基盤を用意する。取得タスク固有の戻り値を解析し、GUI所有属性やウィジェット状態へ反映する処理はStage 2で実装する。ワーカーはGUI所有状態を更新しない。Thread.start()失敗、ワーカー例外、通常終了を別の経路として処理する。取得タスクの構造化された戻り値は09-cross-stage-interface.mdで定義し、そのGUI反映はStage 2設計・テスト仕様に従う。

## 9. 互換性・完了条件
Python 3.8.10互換、新規外部依存なし。ワーカーが別スレッドで実行され、戻り値・例外・終了状態をWorkerHandle経由で回収でき、GUI要求をメインスレッドで処理できること。取得結果のGUI所有状態への反映はStage 2の完了条件とする。起動失敗後もボタン等のGUI状態が復旧し、次回実行が可能であること。


## 10. Stage 2との責務境界

Stage 1はワーカー戻り値を `WorkerHandle.result` に保持し、完了後にメインスレッド側から回収可能にする基盤までを提供する。取得結果の構造を解釈し、取得件数・保存先・ファイル単位の保存結果等をGUI所有状態へ反映する処理はStage 2で実装する。したがって、Stage 1時点で `_finish_worker()` が取得結果を画面へ反映していないことだけを理由にStage 1基盤を不合格とはしない。一方、Stage 2では `03-stage-2-design.md` および `03-stage-2-tests.md` に従い、結果の回収とGUI反映を完了させる。
