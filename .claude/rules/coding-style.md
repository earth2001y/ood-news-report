---
paths:
  - "**/*.py"
---

# コーディングルール（Python）

- Python コードは **PEP 8** に準拠する。
- ruff の設定は [pyproject.toml](../../pyproject.toml) に従う（line-length 100、
  `select = ["E", "F", "I", "W", "UP", "B"]`、target-version py312）。
- Lint と Format は **ruff** で検査する（flake8 は使わない）。
- Python 3.12 以上を対象とする。システム Python ではなく `.venv/bin/python3` と
  `.venv/bin/ruff` を使う。
- 関数を呼び出すとき、可変長引数とデフォルト値を
  持つ引数を除き、引数はキーワード指定せず位置引数で渡す。
- エラーメッセージは `print()` で出力せず、`logging` のロガーから `ERROR` レベル
  （`logger.error(...)`）で出力する。
- ロガーから出力するメッセージは原則として英語で記述する。外部サービスの応答や
  ユーザー由来の値は、必要に応じて原文のまま含めてよい。
- 日本語の docstring やコメントを折り返すときは禁則処理に従い、行頭に `、` `。`
  `)` `」` `』` `】` `,` `.` などの句読点・閉じ括弧を置かない。

## 検証

- コードを変更したら `make test`（pytest）を実行する。
- 静的検査は `make check`（`ruff check .` + `ruff format --check .`）。
- 自動整形は `make format`（`ruff check --fix .` + `ruff format .`）。
- 開発操作は可能な限り `make` に集約する（`make help` で一覧）。
