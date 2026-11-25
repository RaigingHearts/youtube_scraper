# YouTubeコメント取得ツール

YouTube Data API v3を利用して、指定したYouTube動画の情報、コメントスレッド、および返信コメントを取得し、JSON形式で保存するGUIアプリケーションです。

TkinterによるGUIを備え、動画URLまたは動画IDを指定してコメントを取得できます。取得処理の進捗確認、取得データの保存、ログの確認などを行えます。

## 開発履歴（参考・振り返り）

本表は、実用アプリとしての初期状態から、mainへ取り込まれた主要な機能改善を振り返って整理した参考履歴です。

| 参考バージョン | 開発段階 | 主な内容 |
|---|---|---|
| **v1.0.0** | 初期実用版 | GUIから動画情報・コメント・返信を取得し、JSONへ保存する基本アプリ。基準コミット：[ver_1.0](https://github.com/RaigingHearts/youtube_scraper/commit/0862b044389011ea6f07023b3113964c5d26f4e7) |
| **v1.1.0** | 返信コメントの完全取得 | [PR #8](https://github.com/RaigingHearts/youtube_scraper/pull/8)：返信コメントのページング取得を整備 |
| **v1.2.0** | 取得状態・進捗の改善 | [PR #9](https://github.com/RaigingHearts/youtube_scraper/pull/9)、[#11](https://github.com/RaigingHearts/youtube_scraper/pull/11)、[#14](https://github.com/RaigingHearts/youtube_scraper/pull/14)：取得状態、累積進捗、コメント無効動画への対応 |
| **v1.3.0** | 取得品質・共通基盤・安全性 | [PR #16](https://github.com/RaigingHearts/youtube_scraper/pull/16)、[#17](https://github.com/RaigingHearts/youtube_scraper/pull/17)、[#18](https://github.com/RaigingHearts/youtube_scraper/pull/18)：logging統一、コメント重複への対策、ログへの認証情報露出防止 |
| **v1.4.0** | 入力検証 | [PR #19](https://github.com/RaigingHearts/youtube_scraper/pull/19)：YouTube URL形式の対応拡張と動画ID検証 |
| **v1.5.0** | GUI処理基盤の改善 | [PR #27](https://github.com/RaigingHearts/youtube_scraper/pull/27)：TkinterのGUI操作をメインスレッドへ集約し、ワーカー・通知・終了処理を整理 |
| **v1.6.0** | テスト整備 | [PR #28](https://github.com/RaigingHearts/youtube_scraper/pull/28)：ユニットテスト・Tkイベントループ統合テストの整備と検証記録 |
| **v1.7.0** | 取得中断・例外時の安定化 | [PR #31](https://github.com/RaigingHearts/youtube_scraper/pull/31)、[#32](https://github.com/RaigingHearts/youtube_scraper/pull/32)：クォータ超過時の中断と部分データ保持、例外時のGUI状態復旧 |

この番号は開発経緯を読みやすくするための**遡及的な参考表記**であり、GitHub Releasesや正式なバージョンタグとして公開したものではありません。最初の実用アプリを基準に整理しています。GitHub上の「Initial commit」はLICENSEのみのコミットであるため、アプリの基準点には実用アプリを含む ver_1.0 コミットを採用しています。

PR #21〜#26のリポジトリ整理・設計資料・テスト配置整備は、開発を支える管理・品質基盤の改善として扱い、アプリケーション機能のバージョン番号には個別加算していません。OpenのPR #30も、未マージのため履歴には含めていません。

## 開発方針・開発環境

本プロジェクトは、旧世代の開発環境を現在も意識的に活用しながら開発・保守を継続しています。

最新の開発環境への移行を前提とせず、既存環境での開発・動作確認を基本とし、必要な機能改善や保守を段階的に進めています。

主な開発環境は以下のとおりです。

| 項目 | 環境 |
|---|---|
| OS | Windows 7 |
| Python | 3.8.10 |
| エディタ | Visual Studio Code 1.70.2 |
| GUI | Tkinter |

上記は本プロジェクトで使用している開発環境を示すものであり、他のOS・Pythonバージョンでの動作を保証するものではありません。

## 主な機能

- **動画URL解析**：YouTube動画URLから動画IDを抽出します。
- **動画ID入力**：動画IDを直接入力して取得対象を指定できます。
- **動画情報取得**：動画の基本情報を取得します。
- **チャンネル情報取得**：動画に紐付くチャンネル情報を取得します。
- **コメント取得**：コメントスレッドと返信コメントを取得します。
- **重複排除**：コメントIDを用いて重複を判定し、ユニークコメント数を集計します。
- **Rawデータ保存**：APIレスポンスをJSON形式で保存します。
- **進捗表示**：コメント取得の進行状況と取得件数をGUIに表示します。
- **継続確認**：取得件数などが設定された条件に達した場合、ユーザーへ継続を確認します。
- **APIキー管理**：APIキーを暗号化してローカルに保存します。
- **ログ記録・表示**：アプリケーションの動作状況やエラーをログファイルに記録し、GUIから確認できます。
- **取得ファイルを開く**：取得完了後、保存されたJSONファイルをOSの既定アプリケーションで開けます。

## プロジェクト構成

アプリケーションは、機能ごとに分割したモジュールと、アプリケーション全体を統括する `main.py` で構成されています。

| ディレクトリ | 主な役割 |
|---|---|
| `module/manager/secure_settings/` | APIキーなどの設定情報の保存・読み込み・暗号化 |
| `module/manager/tk_app_settings/` | Tkinterアプリケーションの設定管理 |
| `module/single/file_operations/` | ファイル操作 |
| `module/single/json_data_handler/` | JSONデータの保存・処理 |
| `module/single/youtube_utils/` | YouTube動画IDの検証・URL解析 |
| `module/utility/logger_config/` | ログ設定・ログ表示 |
| `module/utility/tk_async_tasks/` | バックグラウンド処理・GUI進捗更新 |
| `module/utility/tk_notifications/` | メッセージボックス・確認ダイアログ |
| `module/utility/youtube_api_client/` | YouTube Data APIとの通信・データ取得 |

`main.py` がアプリケーションの起動、GUI構築、および各モジュールの連携を担当します。

## 必要なライブラリ

外部ライブラリとして、以下を使用します。

- `google-api-python-client`
- `cryptography`

TkinterはPython標準ライブラリです。

プロジェクトのルートディレクトリで、以下を実行してください。

```bash
python -m pip install google-api-python-client cryptography
```

### 旧環境でのライブラリ導入について

Windows 7・Python 3.8.10などの旧環境では、ライブラリのバージョンによってインストールや動作に制約が生じる場合があります。

特に `cryptography` は、利用するバージョンによって対応するPython・OS・ビルド環境が異なります。

インストールに問題が発生した場合は、使用環境に対応したライブラリのバージョンを確認してください。過去の環境向けのバージョン固定を行う場合も、互換性とセキュリティ上の影響を確認したうえで判断してください。

## APIキーの準備

本アプリケーションを利用するには、Google Cloud ConsoleでYouTube Data API v3のAPIキーを取得する必要があります。

1. [Google Cloud Console](https://console.cloud.google.com/)にアクセスします。
2. Googleアカウントでログインし、プロジェクトを作成または選択します。
3. APIライブラリから「YouTube Data API v3」を有効にします。
4. 「APIとサービス」から認証情報を開き、APIキーを作成します。
5. 必要に応じてAPIキーに利用制限を設定します。

APIキーは第三者に知られないよう管理してください。利用するAPIをYouTube Data API v3に限定するなど、適切な制限を設定することを推奨します。

## セットアップと起動

1. リポジトリをローカル環境へ取得します。
2. プロジェクトのルートディレクトリを開きます。
3. 必要なライブラリをインストールします。
4. プロジェクトのルートディレクトリを作業ディレクトリとして、以下を実行します。

```bash
python main.py
```

初回起動時、APIキーが登録されていない場合は入力ダイアログが表示されます。

APIキーを入力すると、暗号化された設定情報がローカルに保存されます。

## 基本的な使い方

### 1. 動画の指定

GUIの「YouTube URL」欄に対象動画のURLを入力します。

「URLから動画IDを解析」ボタンを押すと、対応するURLから動画IDを抽出し、「動画ID」欄に設定します。

動画IDを直接入力することもできます。

対応する主なURL形式は以下のとおりです。

- `https://www.youtube.com/watch?v=動画ID`
- `https://youtu.be/動画ID`
- `https://www.youtube.com/embed/動画ID`
- `https://www.youtube.com/shorts/動画ID`
- `https://www.youtube.com/live/動画ID`
- `https://m.youtube.com/watch?v=動画ID`
- `https://music.youtube.com/watch?v=動画ID`

動画IDを直接入力する場合は、11文字の英数字・ハイフン・アンダースコアで構成された形式である必要があります。

### 2. コメント取得

「コメント取得開始」ボタンを押すと、取得処理が開始されます。

取得処理はバックグラウンドで実行され、GUIには進捗状況と取得件数が表示されます。

APIのクォータ制限や取得件数に関する確認が表示された場合は、ダイアログの案内に従って操作してください。

### 3. 取得結果の確認

取得処理が終了すると、取得データがJSONファイルとして保存されます。

GUIの「取得完了JSONファイルを開く」ボタンから、保存されたファイルを選択して開くことができます。

## 保存されるデータ

取得データは、`main.py` または実行ファイルのあるディレクトリを基準に、動画IDと取得日時を含む専用フォルダへ保存されます。

フォルダ名の形式：

```text
youtube_data_{動画ID}_{取得日時}
```

保存される主なデータファイルは以下のとおりです。

| ファイル名 | 内容 |
|---|---|
| `video_info_raw_{動画ID}.json` | 動画情報のRaw APIレスポンス |
| `channel_info_raw_{チャンネルID}.json` | チャンネル情報のRaw APIレスポンス |
| `comments_raw_{動画ID}.json` | コメントスレッドのRaw APIレスポンス |
| `comment_replies_raw_{動画ID}.json` | 返信コメントのRaw APIレスポンス |

返信コメントのデータは、親コメントIDと取得したRawレスポンスページを関連付けて保存します。

### 重複レコードについて

コメント取得処理では、コメントIDを用いて重複を判定し、取得件数はユニークコメント数として集計します。

一方、保存するRaw APIレスポンスは取得時の内容を保持するため、重複レコードが含まれる場合があります。

そのため、GUIに表示される取得件数と、Raw JSON内のレコード数は一致しないことがあります。

## 設定ファイルとログ

### APIキー・暗号化キー

以下のファイルが使用されます。

| ファイル名 | 内容 |
|---|---|
| `youtube_scraper-settings.json` | 暗号化されたAPIキーを含む設定情報 |
| `youtube_scraper-encryption_key.key` | APIキーの暗号化・復号に使用する鍵 |

これらのファイルは、起動時の作業ディレクトリを基準に作成されます。

暗号化キーと設定ファイルの両方が第三者に渡ると、APIキーを保護できなくなる可能性があります。両ファイルは適切に管理し、Gitリポジトリへ登録しないでください。

### ログファイル

アプリケーションのログは `trace.log` に記録されます。

GUIの「ログを表示」ボタンから内容を確認できます。

ログファイルも起動時の作業ディレクトリを基準に作成されます。

## テスト

プロジェクトのルートディレクトリから、テスト一式を実行できます。

```bash
python -m unittest discover -v
```

テストはルート直下の test_*.py と、各モジュール内の test_*.py に配置されています。各テストディレクトリには、unittest discover が再帰的に探索できるよう __init__.py を配置しています。

一部のテストは実Tkイベントループを使用します。Tk GUI環境を利用できない場合、該当する統合テストはスキップされます。

特定のモジュールだけを実行する場合は、例えば以下を使用できます。

```bash
python -m unittest module.single.youtube_utils.test_youtube_utils -v
python -m unittest module.utility.youtube_api_client.test_youtube_api_client -v
python -m unittest module.utility.logger_config.test_logger_config -v
python -m unittest module.utility.logger_config.test_log_viewer -v
```

テストの成功は、実際のYouTube Data APIを利用した取得確認や、実機GUIの手動受入試験を実施したことを意味しません。実API・実機GUIの確認は、必要性と費用対効果を踏まえて別途判断します。

## 注意事項

- YouTube Data APIにはクォータ制限があります。大量のコメントを取得すると、割り当てられたクォータを消費する場合があります。
- 動画側でコメントが無効化されている場合、コメントを取得できません。
- APIエラーや通信エラーなどにより、取得結果が部分的になる場合があります。
- Raw JSONには動画・チャンネル・コメントに関する情報が含まれます。公開・共有する際は内容を確認してください。
- APIキーおよび暗号化キーを含むローカル設定ファイルは、公開リポジトリへ登録しないでください。
- 旧世代のOS・Python環境では、外部ライブラリやGoogle側サービスの仕様変更により、将来的に利用できなくなる可能性があります。

## ライセンス

本プロジェクトはMIT Licenseの下で公開されています。詳細はリポジトリ内の `LICENSE` ファイルを参照してください。

主な外部ライブラリ：

- `google-api-python-client`：Apache License 2.0
- `cryptography`：Apache License 2.0 または BSD 3-Clause License

TkinterはPython標準ライブラリの一部です。
