# Issue #3：TkinterのGUI操作をメインスレッドに集約する — 全体設計書

## 1. 目的
バックグラウンド処理からのTkinter直接操作をなくし、GUI操作をメインスレッドへ集約する。長時間のYouTube API取得中もGUIの応答性を維持し、進捗・通知・継続確認・終了処理を安全に行う。

## 2. 基本方針
- Tkinterのウィジェット、Tk変数、ダイアログ、after()はメインスレッドだけが操作する。
- ワーカーからのGUI要求はqueue.Queueで渡す。
- WorkerHandleでワーカーの実行状態、結果、例外、キャンセル、進捗、確認要求を管理する。
- 継続確認はthreading.Eventで同期する。
- youtube_api_client.pyからTkinter依存を除去する。
- キャンセルは協調的に行い、実行中のAPI execute()を強制終了しない。
- 取得済みデータと既存の保存形式・利用者向け機能を可能な限り維持する。

## 3. 対象
main.py、module/utility/tk_async_tasks/、module/utility/youtube_api_client/、module/utility/tk_notifications/および関連する取得・進捗・終了処理。

## 4. 対象外
YouTube API取得方式の刷新、APIタイムアウトの新規設定、JSON構造の全面変更、GUIデザインの大幅変更、Issue #10の対象機能。テストコード整備の実作業はIssue #20が担当する。

## 5. スレッド責務
メインスレッドはTkinter操作、GUI要求処理、進捗・通知・確認表示、ワーカー監視、終了制御を担当する。ワーカーはAPI通信、データ処理、ファイル保存、進捗登録、GUI要求登録、キャンセル確認を担当し、Tkinterへ直接触れない。

## 6. 通信・ワーカー管理
GUI要求はGuiRequestを介してqueue.Queueへ登録する。要求種別はprogress、notification、confirmation。ワーカー終了はGUIキューとは別にWorkerHandle.done_eventで検知する。詳細はStage間インターフェース仕様書に従う。

## 7. 継続確認
ワーカーは確認要求をキューへ登録し、個別のthreading.Eventを待つ。メインスレッドがTrue/Falseを確定してEventを設定する。終了開始時には未回答要求をFalseで解除し、確定済み応答を上書きしない。

## 8. APIクライアント
youtube_api_client.pyはTkinterおよびtk_notificationsに依存しない。API処理の結果・エラー情報を返し、利用者への通知はmain.pyがキュー経由で表示する。既存のfetch_all_comments()の返却タプル(result_data, fetched_count, total_expected)は原則維持する。

## 9. キャンセル・終了
ワーカー実行中の終了要求では、保存して終了／追加保存せず終了／終了を取り消して継続、の三択を提示する。保存方針を確定してからcancel_eventを設定する。API通信中は待機し、通信後の安全な境界でキャンセルを確認する。ワーカー終了、未処理GUI要求の処理、結果回収、GUI後処理の後にrootを破棄する。

## 10. 段階
1. GUI要求基盤とワーカー管理
2. 進捗・通知のキュー経由化
3. Event確認とAPIクライアントのGUI依存解消
4. 協調的キャンセルと終了制御
5. Issue #20のテスト仕様に基づく検証

## 11. 完了条件
ワーカーからTkinterへの直接操作がなく、GUI要求がメインスレッドで処理され、APIクライアントがGUI非依存であり、キャンセル・部分取得・保存・終了が安全に動作し、API通信中もGUIが応答すること。Python 3.8.10互換性を維持する。

## 12. 実装前確認
fetch_status、result_data、JSON保存関数、全API呼び出し箇所、保存対象と保存順、例外処理を再確認する。現行API通信に明示的タイムアウトがないため、本Issueでは新規設定しない。
