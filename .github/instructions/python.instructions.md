---
applyTo: "**/*.py"
---

# Python standards

実体は [AGENTS.md](../../AGENTS.md) の「Python の関数設計」。Copilot は参照先を
読み込まないため、Python ファイル編集時に適用する規約のみ再掲する。
環境・検証コマンドは [copilot-instructions.md](../copilot-instructions.md) を参照。

- モジュール先頭に責務を説明する docstring を記載する
- モジュール外から呼び出す関数には `_` で始まらない名前を付ける
- テスト以外のすべての関数に Google スタイルの docstring を付け、機能説明と実装
  理由をブロックとして分ける
- 実装理由は `[実装理由]` で始める
- 関数の本体は 80 行以内に収める（docstring は含めず、コメントと空行は含める）
- `for` / `while` / `if` / `match` / `try` のネストは 3 段以内に保つ
- `print()` でのエラー出力は避け、ロガーの `error` レベルを使う
- 日本語の docstring やコメントを折り返すとき、行頭に句読点や閉じ括弧を置かない
- 各テスト関数には、テスト対象とテストパターンをコメントで明記する
