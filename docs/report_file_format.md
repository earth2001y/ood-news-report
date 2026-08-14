# レポートファイル フォーマット仕様

[ood_news_agent.py](../ood_news_agent.py) は、実行するたびに調査レポートを
標準出力に表示するのと同時に、`$OUTDIR/report_YYYYMMDD_HHMM.md` としても
保存します。書き込み処理は `write_report_file` 関数が担います。

`ood_report_log.md`(既報告項目ログ、[docs/ood_report_log_format.md](ood_report_log_format.md)
参照)とは別物です。レポートファイルは「その回の実行で得られた最終的な報告文」の
スナップショットであり、過去の実行分と統合・追記されることはありません。

このファイルもリポジトリには含めません(`.gitignore` の `/output/` で除外)。
実行環境ごとにローカルで蓄積されるものです。

## 出力先・ファイル名

```
$OUTDIR/report_<YYYYMMDD>_<HHMM>.md
```

- `$OUTDIR` は `--outdir` オプション、または環境変数 `OUTDIR` で指定する出力先
  ディレクトリ。どちらも指定しない場合は `output`。
- ディレクトリが存在しない場合は実行時に自動作成される。
- `<YYYYMMDD>_<HHMM>` はAgent実行日時(分単位)。例: `20260811_1432`。
  実行ごとに異なるファイル名になるため、過去のレポートファイルは上書きされず
  蓄積される。

## ファイルの内容

ファイルの内容は、標準出力に表示されるレポート本文(`OODReport.report_markdown`)
と完全に同一のMarkdownテキストであり、ヘッダーやメタデータなどは付加されない。

本文自体の構成は、Agentへの指示で以下のように規定されている。

- 日本語で記述する。
- カテゴリごとに簡潔にまとめる。見出しは最小限(カテゴリ名程度)にし、箇条書き中心。
- 各項目に「新規」または「更新」のラベルを明記する。
- 各項目に情報源のURLを添える。
- 該当する新規・更新情報がないカテゴリは「変更なし」と明記する。
- 前置き・後書きなどの冗長な説明は含めない。

対象カテゴリは常に以下の4種類。

1. 新バージョンのリリース情報
2. 開発ロードマップの更新・公開
3. セキュリティ脆弱性情報
4. コミュニティイベント

## 例

```markdown
## 新バージョンのリリース情報

変更なし

## 開発ロードマップの更新・公開

- [新規] Updated dashboard MOTD config options? (2026-07-06) - ロードマップ/機能要望カテゴリで、ダッシュボードの MOTD 設定オプション見直しに関する新規トピックが期間内に公開された。 - https://discourse.openondemand.org/c/feature-requests-and-roadmap-discussion/48

## セキュリティ脆弱性情報

- [更新] CVE-2026-26002 (2026-06-17) - Open OnDemand の Files アプリに関する CVE-2026-26002 で、NVD 記録に期間内更新があり、SSVC 情報と affected versions 情報が追加された。 - https://nvd.nist.gov/vuln/detail/CVE-2026-26002

## コミュニティイベント

- [新規] Open OnDemand Tips and Tricks - Americas (2026-08-06) - Open OnDemand 公式サイトのイベント欄で、2026-08-06 開催の Tips and Tricks - Americas が確認できた。 - https://www.openondemand.org/
```

実際のカテゴリ見出しレベルや箇条書きの体言止め・句読点などの細部はAgentの
生成結果によって多少ゆれる(厳密なテンプレート出力ではなく、指示に沿った
自然文生成であるため)。上記は一例であり、完全に固定されたテンプレートではないが、
ラベルは必ずカギ括弧`[]`で囲う。

## ood_report_log.md との関係

- レポートファイルに書かれる「新規」「更新」項目のうち、`log_entries` として
  構造化抽出されたものだけが `ood_report_log.md` に別形式で追記される。
- レポートファイルの文章表現と `ood_report_log.md` の1行要約は、内容としては
  対応しているが、書式(Markdownの構造・語順)は異なる。突き合わせが必要な
  場合は実行日時(レポートファイル名の `<YYYYMMDD>_<HHMM>` と、ログの見出し
  `## <YYYY-MM-DD HH:MM> 実行分`)で対応付ける。
