# ood_research_log.json フォーマット仕様

`ood_research_log.json` は、[ood_news_agent.py](../ood_news_agent.py) が実行ごとに
「新規」または「更新」として報告した項目を蓄積するJSONログです。生成・追記処理は
`append_log` 関数が担います。次回実行時には `load_log` が各記録の `entries` だけを抽出して
調査回をまたいだフラットなMarkdownに変換し、Agentへの入力として既報告項目との照合に使います。

このファイルはリポジトリには含めません(`.gitignore` 対象)。実行環境ごとにローカルで
蓄積されます。

## 全体構造

ログ全体は、実行ごとの記録を格納するJSON配列です。

```json
[
  {
    "datetime": "2026-08-13T09:30:00",
    "period": {
      "start": "2026-07-14",
      "end": "2026-08-13",
      "days": 30
    },
    "entries": [
      {
        "category": "new_release",
        "status": "new",
        "title": "v3.1.0",
        "item_date": "2026-08-01",
        "url": "https://example.com/v3.1.0",
        "summary": "Adds new features for interactive app management.",
        "change_note": ""
      }
    ]
  }
]
```

## 記録のキー

| キー | 型 | 説明 |
| --- | --- | --- |
| `datetime` | 文字列 | 実際に調査を実行した日時。ISO 8601形式。 |
| `period` | オブジェクト | 調査対象期間。`start`、`end`、`days`を持つ。 |
| `period.start` | 文字列 | 調査期間の開始日(`YYYY-MM-DD`)。 |
| `period.end` | 文字列 | 調査期間の終端日(`YYYY-MM-DD`)。 |
| `period.days` | 整数 | 調査対象期間の日数。 |
| `entries` | 配列 | `OODReport.entries` をJSON化した項目一覧。 |

`entries` の各項目は `ReportItem` のフィールドに対応します。`status` は `new` または
`updated` のいずれかで、変更のない項目は含めません。`updated` の場合は `change_note` に
変更内容を記録します。

`summary` と `change_note` は英語で記録します。調査結果は執筆担当 Agent へ渡すまで英語で
一貫させ、日本語への翻訳はレポート生成時に執筆担当 Agent が行うためです。

`category` と `status` は照合用の識別子で、英語の固定値です。`category` は次の 5 種類です。

| `category` | 内容 |
| --- | --- |
| `new_release` | 新バージョンのリリース情報 |
| `roadmap` | 開発ロードマップの更新・公開 |
| `security` | セキュリティ脆弱性情報 |
| `community_event` | コミュニティイベント |
| `other_topic` | その他のトピック |

記事のセクション見出しに使う日本語の文言は、執筆担当 Agent が英語の識別子から訳して
決めます（`ood_news_agent.py` に対応表は持ちません）。カテゴリの並び順と、各識別子の
内容を説明する英語の文面は `CATEGORIES` と `CATEGORY_DESCRIPTIONS` で管理します。

## 動作上の注意

- 報告対象の項目が1件もない実行では、ログファイルに記録を追加しません。
- `--base-date` で対象期間の基準日を変更しても、`datetime` は実際の実行日時です。
- Agentへの入力では、全調査回の `entries` を1つのフラットなMarkdownとして扱い、`datetime` と
  `period` は含めません。項目があるカテゴリは見出しと箇条書きで出力します。見出しは
  `### new_release` のように `category` の識別子、状態は `- [updated]` のように `status` の
  識別子をそのまま使い、Markdown全体を英語で組み立てます。
- 手動編集する場合も、ログ全体をJSON配列として維持してください。JSONとして解釈できない内容は
  次回実行時に読み込めません。
