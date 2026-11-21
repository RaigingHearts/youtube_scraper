# Issue #3：Stage間インターフェース・整合性確認書

## 1. 目的と優先順位
Stage 1〜4の共通インターフェースと処理順序を定義し、実装時の解釈差を防ぐ。本書はStage間の共通契約の規範文書とする。各Stage設計書・テスト仕様書と矛盾がある場合は、本書の共通契約を優先し、実装前に該当文書を同期修正する。

## 2. WorkerHandle
WorkerHandleは一つのワーカー実行のライフサイクルを管理する。最低限、次を保持する。
- thread：実行スレッド
- gui_request_queue：GUI要求キュー
- cancel_event：協調的キャンセル要求
- done_event：ワーカー関数の終了通知
- result：ワーカー関数の戻り値
- exception：未処理例外
- progress_lock、latest_progress、progress_marker_queued：進捗集約
- confirmation_lockおよびpending_confirmations：未回答確認要求
- shutdown_lock、shutdown_decision_event、shutdown_pending：終了判断バリア
- save_policy、save_started：終了時保存方針と保存開始状態
- cancel_reason：キャンセル原因の補足情報

Eventは初期状態unset、フラグはFalse、result/exception/latest_progressは未設定状態から開始する。実装上のデータ型はPython 3.8.10で扱える標準型とし、新規外部依存を追加しない。

## 3. GuiRequest共通仕様
GuiRequestはkind、payload、request_idを持ち、payloadにTkinterオブジェクトを含めない。request_idはWorkerHandle内で一意とし、要求と応答の対応付けに用いる。
- progress：payloadは空または進捗対象の識別情報。進捗値本体はWorkerHandle.latest_progressに保持する。
- notification：payloadはkind(info/warning/error)、title、messageを持つ。
- confirmation：payloadはmessageを持ち、要求本体はresponse_event、response、answeredを保持する。response_eventは要求ごとに独立する。

未知のkindはログへ記録し、その要求だけを失敗扱いとして後続要求の処理を継続する。

## 4. ワーカー起動・終了契約
run_task_in_thread(task_function, gui_request_queue, *args, **kwargs)はWorkerHandleを生成し、task_functionへWorkerHandleを第1引数として渡す。ラッパーは戻り値をresultへ格納し、未処理例外をexceptionへ格納してログに記録する。いずれの場合もfinallyでdone_eventを設定する。
Thread.start()失敗は起動呼び出し元へ伝播させ、main.pyがGUI状態を復旧できるようにする。起動失敗をワーカー関数の例外終了として偽装しない。ワーカー関数の例外はdone_eventで終了を通知した後、メインスレッドがexceptionを回収して利用者向け通知を行う。

同時実行ワーカーは1つ。done_event後も要求・result・exception・保存結果の回収とGUI後処理が終わるまではWorkerHandleを解放しない。

## 5. 進捗契約
publish_progress()はprogress_lock内でlatest_progressを置換する。progress_marker_queued=Falseならprogressマーカーをキューに登録し、同じLock保護区間でTrueにする。take_latest_progress()は同じLock内で最新値を取得し、progress_marker_queued=Falseに戻す。キュー登録・最新値更新・マーカーフラグの変更を一体として扱い、取りこぼしを防ぐ。進捗マーカーは最新値を取得するための通知であり、各更新履歴を表すものではない。

## 6. 通知契約
通常稼働時はnotification要求をFIFOで一件ずつメインスレッドに表示する。モーダルダイアログを同時に表示しない。1件の表示例外はログに記録し、後続要求の処理を継続する。
終了処理開始後は個別の通知ダイアログを表示せず、通知要求をFIFOで退避する。ワーカー終了後、種類・本文・発生順を保った一つの終了時サマリーとして報告する。情報・警告・エラーのいずれも黙って破棄しない。通知がない場合はサマリーを表示しない。

## 7. 継続確認契約
メインスレッドが回答値を確定してからresponse_eventを設定する。回答確定と終了時解除はconfirmation_lock等で排他的に行い、answered=Trueの要求を上書きしない。終了確定時に未回答要求をFalseで解除してEventを必ず設定する。遅延したダイアログ応答はanswered=Trueなら破棄する。確認・通知・終了確認のモーダルダイアログは直列化する。

## 8. APIクライアント契約
youtube_api_client.pyはtkinterおよびtk_notificationsに依存しない。APIエラーのログとresult_data内のエラー情報を維持し、利用者向け通知はワーカーがnotification要求として登録する。
fetch_all_comments()の返却タプルは(result_data, fetched_count, total_expected)を維持する。既存fetch_statusの意味を維持し、キャンセルはfetch_status="cancelled"を使用する。キャンセル理由が判別可能な場合、result_data.cancel_reasonを任意項目として付与する。
- continuation_declined：継続確認で利用者が中止した。
- application_shutdown：アプリ終了に伴う協調的キャンセル。
cancel_reasonは補足情報であり、既存のfetch_statusや返却タプルを置き換えない。

## 9. 取得タスクの結果契約
_scrape_comments_task()はGUI所有状態を変更せず、結果を戻り値として返す。取得結果は少なくとも次を含む構造化データとする。
- fetch_result：APIクライアントのresult_data
- fetched_count：取得件数
- total_expected：予想総件数
- saved_files：保存を試みたファイルごとの結果一覧
- cancel_reason：該当する場合のキャンセル理由

saved_filesの各要素はkind、path、successを持ち、失敗時はerror等の補足を持つ。保存結果を返却構造に集約し、GUI属性last_saved_*_file_path等はmain.pyが成功結果から更新する。resultはこの取得タスク結果を保持する。未処理例外はWorkerHandle.exceptionに保持し、部分的な保存結果を失わないよう可能な限り例外情報と分離して回収する。

## 10. 終了判断・保存開始の同期契約
終了確認ダイアログを表示する前にmain.pyはshutdown_lock内でshutdown_pending=Trueとし、shutdown_decision_eventを未設定にする。ワーカーは保存開始直前に同じLockを取得する。
- pending=Trueならロックを解放してshutdown_decision_eventを待つ。Lockを保持したままEvent待機してはならない。
- pending=Falseかつ通常保存が必要なら、同じLock内でsave_started=Trueとして保存開始を確定する。
- 選択確定後、main.pyはsave_policyを設定し、pending=FalseにしてEventを設定する。キャンセル選択ではcancel_eventを設定しない。はい／いいえではcancel_eventを設定する。
- save_policy=save_partialなら取得済みデータの保存を許可する。
- save_policy=skip_additional_saveならまだ開始していない保存を開始しない。
- 保存開始済みの場合は選択で強制中断しない。

終了要求と保存開始は同じLockで調停する。どちらが先に確定したかにより一意に動作し、終了確認中にワーカーが無断で保存へ進む競合を防ぐ。キャンセル選択後は通常の保存方針へ復帰する。

## 11. キャンセル境界
APIリクエスト開始前にcancel_eventを確認する。execute()実行中は強制中断しない。レスポンスが返った場合はそのレスポンスに含まれるデータを処理・保持してからキャンセルを確認し、後続API要求へ進まない。親コメント・返信ページ処理、ページ間待機、保存開始前にも確認する。ページ間待機はcancel_event.wait(0.1)を使用する。API通信に新規タイムアウトは設定しない。

## 12. 状態遷移
標準状態はrunning、confirming、shutdown_pending、stopping、complete、closedとする。
- running -> confirming -> running：継続確認への回答が確定した。
- running/confirming -> shutdown_pending：終了確認を開始した。確認中の要求は直列化し、未回答要求を解除する。
- shutdown_pending -> running/confirming：終了キャンセル。元の通常処理へ戻り、cancel_eventを設定しない。
- shutdown_pending -> stopping：はい／いいえの終了方針を確定し、cancel_eventを設定した。
- stopping -> complete：ワーカー終了、結果回収、GUI後処理が完了した。
- complete -> closed：終了時通知を報告し、WorkerHandleを解放してrootを破棄した。

ワーカー自然終了が終了ダイアログ表示中に発生した場合は、選択を遅れて適用せず、通常の完了回収へ移る。二重の完了処理・追加保存を行わない。

## 13. 終了時の通知・破棄順序
終了時は、ワーカー終了検知、未処理要求回収、result/exception/保存結果回収、GUI後処理、通知サマリー表示、WorkerHandle解放、root破棄の順とする。終了待機中もGUIイベントループを動作させる。root破棄後にafter()を登録しない。

## 14. 互換性・旧方式の撤去
Python 3.8.10を維持し、新規外部依存を追加しない。queue/threading等の標準ライブラリを使用する。
旧run_task_in_thread呼び出し、confirm_continuation_gui()、BooleanVar/wait_variable方式、ワーカーからのroot.after()、Tk通知呼び出しは、全呼び出し箇所の移行と検索確認が完了したStageで撤去する。移行期間中は互換経路を残してもよいが、新旧方式を同じ処理経路で混在させない。

## 15. 実装前調査・Issue #20への引き継ぎ
fetch_statusとresult_data、JSON保存関数の引数・戻り値・例外、保存対象と順序、全API呼び出し箇所、API内ループ・待機、GUI要求の残存、終了時通知を確認する。
Issue #3は機能要件・インターフェース・受け入れ条件を定義する。Issue #20はテストコード、GUI統合環境、配置・命名・実行方法を整備する。各Stageテスト仕様と本書を参照し、単体・統合テストを構築する。

### 15.1 テスト環境の確認結果（2026-11-21）
既存テストを対象に、Python 3.8.10環境でテスト探索・実行方法を確認した。
- このリポジトリの現在のディレクトリ構成では、unittest discoverによるサブディレクトリの再帰探索に、テストファイルを含む各階層のパッケージ化（空の__init__.py）が必要だった。
- module/以下の親ディレクトリおよびテスト配置先の各ディレクトリに合計13個の空の__init__.pyを追加した検証環境では、リポジトリルートからテストを一括探索できた。
- python -m unittest discover -v：50テストを検出し、全件成功。
- python -m pytest -v（pytest 8.3.5）：同じ50テストを検出し、全件成功。
- この結果は、検証時点で存在した既存テスト50件の探索・実行結果であり、Issue #3のStage 1〜4で定義した新規テストが実装済み、または検証済みであることを意味しない。

テストランナーは、Python標準ライブラリで追加依存のないunittestを基本候補とし、pytestを補助的に利用する案をIssue #20で確定する。Tkinterのイベントループを伴う統合テストは、ヘッドレス環境で実行できる単体テストと区別し、実デスクトップ環境での検証方法・実行条件をIssue #20で整備する。テストコードの配置・命名・実行手順もIssue #20で最終決定する。

## 16. 文書登録方針
必要な設計書・テスト仕様書を一式揃え、相互のインターフェース、用語、対象範囲、完了条件、Issue #20への引き継ぎを確認した後に登録する。文書登録はソースコード変更や実装開始の承認とは別に扱う。
