# Issue #3：Stage間インターフェース・整合性確認書

## 1. 目的
Stage 1〜4の共通インターフェースと処理順序を定義し、実装時の解釈差を防ぐ。

## 2. WorkerHandle
基本属性：thread、gui_request_queue、cancel_event、done_event、result、exception。
追加管理情報：最新進捗、進捗Lock、進捗マーカー登録済みフラグ、終了時保存方針、未回答確認要求管理情報。
進捗はpublish_progress()とtake_latest_progress()で操作する。

## 3. GuiRequest
kindはprogress、notification、confirmation。payloadにTkinterオブジェクトを含めない。進捗マーカーは対象WorkerHandleを識別する。通知はFIFO。確認要求は個別Eventを持つ。

## 4. ワーカー
同時実行は1つ。ワーカー関数の第1引数はWorkerHandle。正常・例外終了のどちらでもdone_eventを設定する。スレッド開始失敗は呼び出し元へ伝える。

## 5. 進捗
最新状態をWorkerHandleに保持し、未処理マーカーを重複登録しない。メインスレッドが最新情報を取得し、Lockとフラグを一体として扱い競合・取りこぼしを防ぐ。

## 6. 通知
通常時はFIFOで1件ずつ表示し、モーダルダイアログの入れ子を避ける。終了待機中は通知ダイアログを連続表示せず、通知を保留する。ワーカー終了後、重要な通知を整理して終了前に報告する。保存失敗等はログだけに埋もれさせない。

## 7. 継続確認
メインスレッドが回答値を確定してからEventを設定する。終了時は未回答要求をFalseで解除し、確定済み応答を上書きしない。

## 8. APIクライアント
Tkinter/tk_notificationsに依存しない。cancel_eventを受け取り、API通信中は強制中断せず安全な境界で確認する。既存fetch_all_comments()の返却タプルを原則維持する。既存fetch_status="cancelled"を再利用する。

## 9. 保存
はい：取得済みデータを保存して終了。いいえ：追加保存せず終了。キャンセル：終了要求を取り消す。保存方針をcancel_event設定前に確定する。既存JSON保存関数を再利用し、ファイル単位の結果を回収する。既存ファイル削除・完了済み保存取消しはしない。

## 10. 完了・終了順序
done_event後もWorkerHandleを即時解放しない。
1. ワーカー終了検知
2. ワーカーに属する未処理GUI要求の処理
3. result/exception回収
4. GUI後処理
5. WorkerHandle解放
6. 必要な終了処理後にroot破棄

root.after()の登録・実行はメインスレッドのみ。root破棄後は新たに登録しない。

## 11. 互換性
Python 3.8.10を維持し、新規外部依存を追加しない。queue/threading等の標準ライブラリを使用する。

## 12. 実装前調査
fetch_statusとresult_data、JSON保存関数の引数・戻り値・例外、保存対象と順序、全API呼び出し箇所、API内ループ・待機、GUI要求の残存、終了時通知を確認する。

## 13. Issue #20への引き継ぎ
Issue #3は機能要件・インターフェース・受け入れ条件を定義する。Issue #20はテストコード、GUI統合環境、配置・命名・実行方法を整備する。各Stageテスト仕様と本書を参照し、単体・統合テストを構築する。

## 14. 文書登録方針
必要な設計書・テスト仕様書を一式揃え、相互のインターフェース、用語、対象範囲、完了条件、Issue #20への引き継ぎを確認した後に登録する。文書登録はソースコード変更や実装開始の承認とは別に扱う。
