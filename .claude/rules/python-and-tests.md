---
paths:
  - "*.py"
  - "**/*.py"
  - "Makefile"
---

# ルール: Python

## 環境

- Python 3。必ず `.venv/bin/python3` と `.venv/bin/ruff` を使う（システム Python を使わない）。開発操作は `make` に集約（`make help`）。
- Python コードは **PEP 8** に準拠する。
- PEP 8 準拠、Lint、Format は **ruff** で検査できる（flake8 は無効）。コミット前に `make format`（`ruff check --fix .` + `ruff format .`）を通す。lint + test なら `make check`。
- ruff の定義は [pyproject.toml](../../pyproject.toml) に書いてある（line-length 100、select=E/F/I/W/UP/B）。

## 実装の作法

- エラーメッセージは `print()` で出力せず、`logging` のロガーから `ERROR` レベル
  （`logger.error(...)`）で出力する。

