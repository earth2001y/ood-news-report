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
        "category": "新バージョンのリリース情報",
        "status": "新規",
        "title": "v3.1.0",
        "item_date": "2026-08-01",
        "url": "https://example.com/v3.1.0",
        "summary": "新機能が追加された",
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

`entries` の各項目は `ReportItem` のフィールドに対応します。`status` は `新規` または
`更新` のいずれかで、変更のない項目は含めません。`更新` の場合は `change_note` に変更内容を
記録します。

## 動作上の注意

- 報告対象の項目が1件もない実行では、ログファイルに記録を追加しません。
- `--base-date` で対象期間の基準日を変更しても、`datetime` は実際の実行日時です。
- Agentへの入力では、全調査回の `entries` を1つのフラットなMarkdownとして扱い、`datetime` と
  `period` は含めません。項目があるカテゴリは見出しと箇条書きで出力します。
- 手動編集する場合も、ログ全体をJSON配列として維持してください。JSONとして解釈できない内容は
  次回実行時に読み込めません。
