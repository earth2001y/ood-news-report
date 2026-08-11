# ood-news-report

OpenAI Agents SDK を使い、Open OnDemand (OSC/ondemand) に関する最新情報を
Web検索で収集し、日本語で報告するエージェントです。

## 調査対象

1. 新バージョンのリリース情報
2. 開発ロードマップの更新・公開
3. セキュリティ脆弱性情報
4. コミュニティイベントの告知・CFP・開催報告

調査対象期間は既定で直近30日間です(`--window-days` オプションで変更可能)。

実行するたびに `ood_report_log.md`(報告済み項目ログ)と今回の調査結果を
照合し、完全に新規の情報は「新規」、既報告項目に進展・変更があれば
「更新」として何が変わったかを明記して報告します。変更のない既報告項目は
再報告しません。該当情報がないカテゴリは「変更なし」と明記します。

## セットアップ

```bash
python3 -m venv .venv   # 未作成の場合
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
```

`OPENAI_API_KEY` は `.env` ファイルに記載しても読み込まれます。

## 実行方法

```bash
python ood_news_agent.py
```

### オプション

| オプション | デフォルト | 説明 |
| --- | --- | --- |
| `--log-path` | `ood_report_log.md` | 報告済み項目ログのパス |
| `--model` | `gpt-5.4` | 使用するモデル(WebSearchTool対応のResponses APIモデル) |
| `--outdir` | 環境変数 `OUTDIR`、未設定なら `output` | レポートファイルの出力先ディレクトリ |
| `--window-days` | 環境変数 `WINDOW_DAYS`、未設定なら `30` | 調査対象期間(日数) |
| `--max-turns` | `40` | Agent実行の最大ターン数 |

## 出力

- 標準出力: 日本語・カテゴリ別・箇条書き中心のレポート(新規/更新ラベル、参照URL付き)
- `$OUTDIR/report_YYYYMMDD_HHMM.md`: 標準出力と同じレポート本文を実行ごとに
  ファイルとしても保存する(ディレクトリが存在しない場合は自動作成)
  (フォーマットの詳細は [docs/report_file_format.md](docs/report_file_format.md) 参照)
- `ood_report_log.md`: 今回「新規」「更新」として報告した項目が実行日時ごとに追記される
  (フォーマットの詳細は [docs/ood_report_log_format.md](docs/ood_report_log_format.md) 参照)

## プロンプトのカスタマイズ

Agentへの指示文・ユーザー入力プロンプトは `templates/` 配下のJinja2テンプレート
(`instructions.j2`, `user_input.j2`)に分離されています。コードを変更せずに
文言を調整したい場合はこれらのファイルを編集してください。

## 注意事項

- `WebSearchTool` を利用するため、Web検索機能が有効な `OPENAI_API_KEY` が必要です。
- ログファイルはテキスト全体をAgentへの入力に含めて照合を行うため、長期間の
  運用でログが大きくなった場合は、古いエントリのアーカイブを検討してください。
