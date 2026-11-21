# Issue #3：Stage 3 詳細設計 — 継続確認のEvent方式への移行とAPIクライアントのGUI依存解消

## 1. 目的
継続確認をthreading.Event方式へ移行し、youtube_api_client.pyからTkinter依存を除去する。

## 2. 継続確認
ワーカーはconfirmation要求をGUI要求キューへ登録し、要求ごとのEventを待つ。要求には確認内容、response_event、responseを含める。メインスレッドはダイアログで回答を得て、responseを確定してからEventを設定する。Trueは継続、Falseは中止。

ダイアログ表示例外時はFalseを既定値としてEventを設定する。未回答要求はWorkerHandleに関連付けて管理し、終了処理で解除できるようにする。回答確定後の値を上書きしない。

## 3. APIクライアントのGUI依存解消
youtube_api_client.pyからtkinterおよびtk_notificationsのimportとダイアログ呼び出しを除去する。APIクライアントは結果・エラー情報を返し、通知はmain.pyがGUI要求キュー経由で行う。既存ログとエラー情報の意味は可能な限り維持する。

## 4. 返却構造
fetch_all_comments()の既存返却タプル(result_data, fetched_count, total_expected)を原則維持する。fetch_status等の既存状態と意味を調査し、新しいエラー体系を安易に追加しない。

現行コードにはfetch_status="cancelled"が存在する。Stage 4の終了要求によるキャンセルでも再利用する。従来の継続確認による中断との意味の整合性を維持する。

## 5. キャンセル引数への準備
Stage 4でfetch_all_comments()にthreading.Eventを渡せるようにする。APIクライアントはEventだけを扱い、TkinterやWorkerHandleに依存しない。

## 6. 旧方式の整理
confirm_continuation_gui()、BooleanVar、wait_variableを利用する旧方式は全呼び出し箇所の移行後に削除する。

## 7. 完了条件
Event確認が正常・異常系で解除され、APIクライアントにGUI依存がなく、既存の返却タプル・取得結果・エラー状態の意味が維持されること。
