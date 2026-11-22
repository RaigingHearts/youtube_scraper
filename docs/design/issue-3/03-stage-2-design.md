# Issue #3：Stage 2 詳細設計 — 進捗表示と通知のキュー経由化

## 1. 目的
進捗表示と通知ダイアログをメインスレッドへ集約し、ワーカーがGUI所有状態を読み書きしない構造にする。

## 2. 進捗集約
進捗は最新状態が重要であり、古い更新をキューに蓄積しない。WorkerHandleに最新進捗情報、progress_lock、progress_marker_queuedを保持する。

ワーカー側publish_progress()はprogress_lock内で最新情報を更新する。progress_marker_queuedがFalseの場合だけ、同じWorkerHandleを識別できるprogressマーカーをキューへ登録し、フラグをTrueにする。キュー登録とフラグ更新は同じLock保護区間で行う。

メイン側take_latest_progress()は同じLock内で最新情報を取得し、マーカー登録済みフラグをFalseにする。取得・フラグ解除後に発生した更新は新しいマーカーを登録できる。メイン側が古いマーカーを消費した直後に新しい更新が来る場合も、Lockにより更新の取りこぼしと重複抑制の競合を防ぐ。マーカーを処理した後に進捗値が存在しない場合は正常な空状態として扱う。

## 3. 通知
notification要求はkind(info/warning/error)、title、messageを持ち、通常キューでFIFO処理する。通常稼働中は通知を原則省略せず、メインスレッドで1件ずつ表示する。ダイアログ表示中に別のモーダルダイアログを重ねない。通知表示の例外はログに記録し、後続要求とポーリングを継続する。

同一の事象について、APIクライアント等から既存通知が発生する移行例外と、ワーカー側からの通知要求を重ねて登録しない。Stage 2で新たに追加・移行する通知経路では、通知の発生元と責務を整理し、同じエラーを二重表示しない。終了処理中の通知退避・終了時サマリー化・表示抑制はStage 4の責務とし、Stage 2では通常稼働中のFIFO表示を実装する。

## 4. main.py
進捗マーカーから最新情報を取得してGUIへ反映する。通知要求はtk_notifications経由で表示する。ワーカー完了時のresult、exception、partial_resultを回収し、取得結果・保存先・ファイル単位の保存結果をGUI側の状態へ反映する。GUI属性の更新はメインスレッドだけで行う。

正常終了時はresult.saved_filesを、例外終了時はpartial_result["saved_files"]を保存結果の確定情報として扱う。保存先パス属性はsuccess=Trueかつ実際に保存が完了したレコードからのみ更新する。失敗・未試行のファイルを保存済みとして扱わず、少なくとも1件の有効な保存済みファイルがある場合は、そのファイルを開くためのGUI操作を利用可能にする。

## 5. _scrape_comments_task()
直接after()を呼ばず、ウィジェットを参照せず、tk_notificationsを直接呼ばない。進捗はWorkerHandle経由、通知はGUI要求キュー経由とする。API通信とファイル操作はワーカー側で行い、GUI更新に必要な値は戻り値に含める。last_saved_*_file_path、total_comments_expected等はメインスレッドが更新し、プログレスバー最大値などGUI状態をワーカーから読み取らない。

Stage 2では、継続確認に用いる既存のconfirm_continuation_gui()／BooleanVar／after()／wait_variable()経路が残存することを移行例外として許容する。この確認経路のキュー化とAPIクライアント内通知のGUI非依存化はStage 3で行う。Stage 2で新たな確認経路を追加してはならない。

## 6. APIクライアント（Stage 2の移行例外）
Stage 2では、youtube_api_client.py内部のtk_notifications呼び出しはまだ残存し得る。これは現行APIクライアントのGUI依存をStage 3で解消するための、Stage 2に限った明示的な移行例外である。したがってStage 2の「ワーカーからGUIへの直接アクセスを行わない」という完了条件・テスト対象は、main.pyおよび_scrape_comments_task()自身が行うGUI操作・通知経路に適用する。APIクライアント内部から発生する既存の直接通知はStage 2では例外として扱い、Stage 3で完全に撤去する。Stage 2で新たな直接GUI操作や通知経路を追加してはならない。

## 7. 保存結果レコードの共通形式
保存結果はファイル単位で記録し、`kind`は次の固定値を使用する。
- `video_info`
- `channel_info`
- `comments`
- `replies`

各レコードは`{kind, path, success}`を必須項目とし、`path`は保存先の完全なパス、`success`は保存処理の実成否を表す真偽値とする。失敗時は必要に応じて`error`等の補足情報を持たせる。ファイルの保存試行が確定した直後に`WorkerHandle.partial_result["saved_files"]`へ追加し、正常終了時の戻り値`saved_files`と同じ内容にする。未試行ファイルのレコードは追加しない。

## 8. 完了条件
main.py由来の進捗・通知表示がメインスレッドで行われ、進捗が集約され、ワーカー側の_scrape_comments_task()がGUI所有状態を直接変更せず、結果・保存情報が戻り値およびpartial_resultで受け渡され、既存の取得・保存動作が維持されること。main.py自身によるGUI更新はメインスレッド上で行うため、GUI操作そのものを撤去対象とはしない。Stage 2ではAPIクライアント由来の既存tk_notifications呼び出しと既存の継続確認GUI経路のみを移行例外として許容し、これらの撤去はStage 3の完了条件とする。終了時の通知抑制・集約はStage 4で扱う。
