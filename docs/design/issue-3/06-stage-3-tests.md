# Issue #3：Stage 3 テスト仕様 — 継続確認のEvent方式への移行とAPIクライアントのGUI依存解消

## 1. Event確認
確認要求登録、ワーカー待機、True継続、False中止、要求ごとのEvent独立性、回答一度限り、ダイアログ例外時のFalse解除、終了処理による未回答解除、確定済み応答の不変性を確認する。回答確定と終了解除が競合してもresponse_eventが必ず設定され、responseとresponse_reasonが後から上書きされないことを検証する。利用者のFalse回答が先に確定した場合はcontinuation_declined、終了解除が先に確定した場合はapplication_shutdownとなることを確認する。ダイアログ例外・表示不能によるFalseはconfirmation_unavailableとなることも確認する。

## 2. ダイアログ直列化
確認・通知・終了確認のモーダルダイアログが同時に表示されないことを確認する。確認表示中に終了要求が発生した場合、確認応答を一度だけ確定した後に終了処理へ移ること、終了開始後に新しい確認ダイアログを表示しないことを確認する。

## 3. APIクライアント独立性
youtube_api_client.pyがtkinterとtk_notificationsをimportせず、API処理からダイアログを表示しないことを確認する。エラー情報・ログが保持され、呼び出し元が通知内容を構成できることを確認する。

## 4. APIエラー
サービス生成、動画情報、チャンネル情報、コメントスレッド、返信ページの各エラーをモック化する。既存fetch_status、result_data、取得件数、返却タプル構造を維持する。同一エラーの二重通知が発生しないこと、従来通知されていた失敗とログのみだった状態の差異を確認する。

## 5. キャンセル理由
利用者が明示的にFalseを選んだ場合はfetch_status="cancelled"かつresult_data["cancel_reason"]="continuation_declined"となること、アプリ終了解除ではresult_data["cancel_reason"]="application_shutdown"となることを確認する。ダイアログ例外・表示不能ではconfirmation_unavailableとなることを確認する。WorkerHandle.cancel_reasonがワーカータスクからresult_dataへ伝達され、APIクライアントがWorkerHandleに依存しないことを確認する。キャンセル以外の結果ではcancel_reasonキーが存在しないことを確認する。既存のcancel_reasonキーなしデータも従来どおり読み取れることを確認する。

## 6. 継続確認統合
Trueで後続取得、Falseで中止、部分取得データの保持、上限到達が複数回発生した場合の動作を確認する。

## 7. スレッド境界・GUI統合
確認ダイアログはメインスレッド、ワーカーはEvent待機、APIクライアントはGUI非操作であることを確認する。モックAPIと実際のTkイベントループを使用する。

## 8. 完了条件
Python 3.8.10環境で、Event確認の正常・異常・競合系とAPIクライアントのGUI非依存性を検証できること。
