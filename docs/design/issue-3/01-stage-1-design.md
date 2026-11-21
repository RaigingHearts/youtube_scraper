# Issue #3：Stage 1 詳細設計 — GUI要求基盤とワーカー管理

## 1. 目的
ワーカーからメインスレッドへGUI要求を渡す共通基盤を用意する。進捗・通知・継続確認の具体的な移行は後続Stageで行う。

## 2. 責務
### main.py
GUI要求キューの生成・所有、WorkerHandleの保持、メインスレッドでのポーリング、要求振り分け、ワーカー終了監視を担当する。

### tk_async_tasks.py
GuiRequest、WorkerHandle、ワーカー生成・実行管理を定義する。既存関数は全呼び出し箇所の移行が完了するまで維持する。

## 3. GuiRequest
属性はkind、payload、必要に応じresponse_eventとresponse。kindはprogress、notification、confirmation。payloadにTkinterウィジェットやTk変数を含めない。

## 4. WorkerHandle
基本属性はthread、gui_request_queue、cancel_event、done_event、result、exception。Stage 2以降の進捗管理情報、保存方針、未回答確認要求管理情報を追加する。共通仕様はStage間インターフェース仕様書に従う。

## 5. 起動関数
run_task_in_thread(task_function, gui_request_queue, *args, **kwargs) -> WorkerHandleを用意する。ワーカー関数にはWorkerHandleを第1引数として渡す。ラッパーは戻り値をresultへ格納し、例外をexceptionへ格納してログに記録し、成功・失敗のどちらでもfinallyでdone_eventを設定する。thread参照を設定してから開始する。スレッド開始失敗は呼び出し元が認識できるようにする。

## 6. ポーリング
main.pyがメインスレッド上でroot.after()を使って監視する。初期値は50ms間隔、1回最大50件。1要求の処理例外で後続要求や次回ポーリングを止めない。空キューは正常として扱う。

## 7. ワーカー管理
同時実行ワーカーは1つ。既存ワーカーの実行中、または完了後処理が終わる前は新規起動しない。完了情報・GUI要求を回収してからWorkerHandleを解放する。Stage 1では既存daemon設定を維持し、非daemon化はStage 4の終了制御と同時に行う。

## 8. 互換性・完了条件
Python 3.8.10互換、新規外部依存なし。ワーカーが別スレッドで実行され、結果・例外・終了状態を回収でき、GUI要求をメインスレッドで処理できること。
