# ood-news-report

OpenAI Agents SDK を使い、Open OnDemand (OSC/ondemand) に関する最新情報を
Web検索で収集し、日本語で報告するエージェントです。

## 調査対象

1. 新バージョンのリリース情報
2. 開発ロードマップの更新・公開
3. セキュリティ脆弱性情報
4. コミュニティイベントの告知・CFP・開催報告
5. その他のホットトピック(上記に当てはまらない、コミュニティで注目されている話題)

調査対象期間は既定で直近30日間です(`--window-days` オプションで変更可能)。
期間の終端となる基準日は既定で実行日ですが、`--base-date` で過去や未来の日付を
指定できます。

実行するたびに `LOGDIR` で指定したディレクトリ配下の `ood_report_log.md`(報告済み項目ログ)と
今回の調査結果を照合し、完全に新規の情報は「新規」、既報告項目に進展・変更があれば
「更新」として何が変わったかを明記して報告します。変更のない既報告項目は
再報告しません。該当情報がないカテゴリは「変更なし」と明記します。

## 処理の流れ

1. **調査**: 調査担当Agent(`build_researcher_agent`)が WebSearchTool で情報を収集し、
   ログと照合して構造化データ(`OODReport`)を出力します。
2. **ログ追記**: `OODReport.log_entries` を `ood_report_log.md` に追記します。
   ログの内容は再構成の影響を受けません。
3. **記事の再構成**: 執筆担当Agent(`build_writer_agent`)が調査結果を受け取り、
   箇条書きではなく地の文のニュースレター記事(`OODArticle`)に再構成します。
   この Agent は WebSearchTool で入力の事実を補足調査できますが、記事には
    調査結果に書かれた事実のみを使います。新規・更新項目がない場合は、この記事の
    再構成を行いません。
4. **出力**: 再構成した記事を標準出力に表示し、レポートファイルに保存します。

## セットアップ

```bash
python3 -m venv .venv   # 未作成の場合
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
# Slack Incoming Webhookへ投稿する場合
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

`OPENAI_API_KEY` は `.env` ファイルに記載しても読み込まれます
(`.env.example` をコピーして使ってください)。

## 実行方法

```bash
python ood_news_agent.py
```

### オプション

| オプション | デフォルト | 説明 |
| --- | --- | --- |
| `LOGDIR` | `.log` | 報告済み項目ログの保存ディレクトリ(環境変数のみ) |
| `--model` | `gpt-5.4` | 使用するモデル(WebSearchTool対応のResponses APIモデル) |
| `--writer-model` | 環境変数 `OOD_WRITER_MODEL`、未設定なら `--model` と同じ | 記事再構成に使うモデル(WebSearchTool対応モデル) |
| `OUTDIR` | `output` | レポートファイルの出力先ディレクトリ(環境変数のみ) |
| `--window-days` | 環境変数 `WINDOW_DAYS`、未設定なら `30` | 調査対象期間(日数) |
| `--base-date` | 環境変数 `BASE_DATE`、未設定なら実行日 | 調査対象期間の基準日(`YYYY-MM-DD`)。この日を終端とする |
| `--log-level` | 環境変数 `OOD_LOG_LEVEL`、未設定なら `WARNING` | ログの出力レベル(`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`) |
| `--dry-run` | 無効 | APIによる調査・記事再構成を行うが、ログ追記・レポート保存・Slack投稿は行わない |
| `--max-turns` | `40` | Agent実行の最大ターン数 |

### 調査対象期間

`--base-date` を終端とし、そこから `--window-days` 日前までが調査対象期間です。
`--base-date` を指定しない場合は実行日が基準日になります。

```bash
# 実行日が2026-08-14なら 2026-07-15 〜 2026-08-14
python ood_news_agent.py

# 2026-07-22 〜 2026-07-31 を調査する
python ood_news_agent.py --base-date 2026-07-31 --window-days 10

# 環境変数でも指定できる(CLIオプションが優先)
BASE_DATE=2026-07-31 python ood_news_agent.py
```

基準日より後に公開・更新された情報は、調査対象期間外として報告から除外するよう
Agentに指示しています。書式が `YYYY-MM-DD` として解釈できない場合は、誤った期間の
レポートを出さないためにエラー終了します(終了コード 1、API は呼び出しません)。

ログの見出しとレポートファイル名は、基準日ではなく**実行日時**のままです。
「いつ実行した分か」の記録として一貫させるためで、同じ基準日で何度実行しても
レポートファイルは上書きされません。

### ログレベル

既定の `WARNING` では、標準出力に記事本文だけが出ます。進捗(調査中・再構成中)や
完了報告(ログ追記件数・レポートの保存先)は `INFO` なので表示されません。

```bash
# 進捗を表示する
python ood_news_agent.py --log-level INFO

# 環境変数でも指定できる(CLIオプションが優先)
OOD_LOG_LEVEL=INFO python ood_news_agent.py
```

大文字小文字は区別しません(`info` でも可)。不正な値を指定した場合は警告を出して
`WARNING` で実行を続けます(ログ設定のタイポで調査そのものを止めないため)。

ログはすべて標準エラー出力に出るため、記事本文だけを取り出すことができます。

```bash
python ood_news_agent.py --log-level INFO 2>/dev/null > report.md
```

### ドライラン

`--dry-run` を指定すると、通常どおりOpenAI APIを呼び出して調査と記事再構成を行いますが、
`LOGDIR` 配下の `ood_report_log.md` への追記、レポートファイルの保存、Slackへの投稿は行いません。
再構成した記事は標準出力に表示されるため、保存前に内容を確認する用途に使えます。

```bash
python ood_news_agent.py --dry-run
```

## 出力

- 標準出力: 日本語・カテゴリ別のニュースレター記事(リード文＋地の文の解説、出典URL付き)。
  記事本文のみで、進捗やエラーは標準エラー出力に分離される
- `$OUTDIR/report_YYYYMMDD_HHMM.md`: 標準出力と同じ記事本文を実行ごとに
  ファイルとしても保存する(ディレクトリが存在しない場合は自動作成)
  (フォーマットの詳細は [docs/report_file_format.md](docs/report_file_format.md) 参照)
- `$LOGDIR/ood_report_log.md`: 今回「新規」「更新」として報告した項目が実行日時ごとに追記される。
  ディレクトリが存在しない場合は自動作成され、既定値は `.log` である。
  記事ではなく調査担当Agentの構造化出力をそのまま記録するため、形式は従来から変わらない
  (フォーマットの詳細は [docs/ood_report_log_format.md](docs/ood_report_log_format.md) 参照)

新規・更新項目がない場合は、執筆担当Agentを実行せず、標準出力・レポートファイルへの
出力も行いません。ログへの追記もありません。

`SLACK_WEBHOOK_URL` を設定すると、レポートファイル保存後に
記事本文をSlackのmrkdwn形式へ変換してIncoming Webhookへ投稿します。未設定の場合はSlack投稿を
行いません。

## エラー時の挙動

OpenAI API の呼び出しが失敗した場合、スタックトレースではなく原因と対処方法を
`ERROR` ログとして標準エラー出力に表示し、終了コード 1 で終了します。既定の
`WARNING` でも `ERROR` は表示されるため、ログレベルの設定に関わらず失敗は分かります。

| エラーコード | 意味・対処 |
| --- | --- |
| `credit_balance_exhausted` | 残高不足。請求ページでクレジットを追加する |
| `insufficient_quota` | 利用可能枠の超過。残高と上限を確認する |
| `invalid_api_key` | `OPENAI_API_KEY` が無効。キーの値と失効を確認する |
| `model_not_found` | 指定モデルが利用できない。`--model` を見直す |

上記以外のエラーコードでも、HTTP ステータスと API からのメッセージをそのまま
提示します。

調査には成功したが記事の再構成で失敗した場合、`ood_report_log.md` への追記は
すでに完了しています(調査結果を失わないため、追記は再構成より先に行います)。
この状態で再実行すると、追記済みの項目は「変更なし」と判定されて再報告されない
点に注意してください。同じ内容を記事にしたい場合は、ログから該当セクションを
削除してから再実行します。

Slack投稿に失敗した場合は終了コード1を返します。ローカルのログとレポートファイルは
投稿前に保存されるため、記事本文は失われません。

## プロンプトのカスタマイズ

Agentへの指示文・ユーザー入力プロンプトは `templates/` 配下のJinja2テンプレートに
分離されています。コードを変更せずに文言を調整したい場合はこれらのファイルを
編集してください。

| ファイル | 用途 |
| --- | --- |
| `researcher_instructions.j2` | 調査担当Agentの指示文 |
| `researcher_input.j2` | 調査担当Agentへのユーザー入力 |
| `writer_instructions.j2` | 執筆担当Agentの指示文(記事の構成・文体) |
| `writer_input.j2` | 執筆担当Agentへのユーザー入力(調査結果の受け渡し) |

## 注意事項

- `WebSearchTool` を利用するため、Web検索機能が有効な `OPENAI_API_KEY` が必要です。
- ログファイルはテキスト全体をAgentへの入力に含めて照合を行うため、長期間の
  運用でログが大きくなった場合は、古いエントリのアーカイブを検討してください。
