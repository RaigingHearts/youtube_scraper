# Issue #3：Stage 1 テスト仕様 — GUI要求キューとワーカー管理

## 1. 対象
GuiRequest、WorkerHandle、run_task_in_thread()、main.pyのGUI要求ポーリング、ワーカー開始・終了管理。

## 2. 単体テスト
- GuiRequestがkind、payload、request_id、必要なresponse_event・response・answeredを保持する。
- 要求ごとのpayload/Eventが独立し、Tkinterオブジェクトを含まない。
- WorkerHandleのEvent初期状態、result、exception、各Lock・フラグの初期状態を確認する。
- 正常・例外終了の両方でdone_eventが設定される。
- ワーカーが呼び出し元と異なるスレッドで実行される。
- 位置引数・キーワード引数・WorkerHandleの受け渡しを確認する。
- 正常時のresult、例外時のexceptionとログを確認する。
- Thread.start()失敗が呼び出し元へ伝わり、done_eventとGUI復旧処理が適切に扱われる。ワーカー本体の例外と混同しない。

## 3. キュー処理
登録順、要求種別振り分け、1回の処理上限、上限到達後の残件処理、空キュー、1要求の例外後も後続処理が続くこと、未知の要求種別、次回ポーリング予約を確認する。

## 4. スレッド境界
GUI要求処理がメインスレッドで実行され、ワーカーからウィジェット、Tk変数、after()を直接操作しないことを確認する。

## 5. ライフサイクル
重複起動を防止し、done_event後も完了情報・未処理GUI要求の回収後にWorkerHandleを解放する。例外終了後も次のワーカーを開始できること。起動失敗後にボタン状態・進捗表示・内部参照が復旧することを確認する。

## 6. GUI統合
TkイベントループとモックAPIを使用し、正常・例外・起動失敗終了、GUI応答性、要求処理、完了後のGUI状態更新を検証する。実API通信は行わない。

## 7. 環境・完了条件
unittest、Python 3.8.10。GUI不要のテストは可能な限りヘッドレスで実行し、GUI統合はデスクトップ環境で実行する。テスト配置・命名・CI方式はIssue #20で決定する。
