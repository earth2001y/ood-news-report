---
paths:
  - "tests/**/*.py"
  - "**/test_*.py"
  - "**/conftest.py"
---

# テスト指針

- テストフレームワークには **pytest** を使う。設定は
  [pyproject.toml](../../pyproject.toml) の `[tool.pytest.ini_options]`
  （`testpaths = ["tests"]`、`addopts = "-q"`）に従う。
- テストは `tests/` 配下に置き、ファイル名は `test_*.py` とする。
- 各テスト関数には、**テスト対象**と**テストパターン**をコメントで明記する。
  テスト関数には docstring による機能説明・実装理由は必須としない。
- Python コードを新規に作成するときは、対応するテストも合わせて作成する。
- コードを修正したら `make test` を実行する。
- 外部 API（WebSearchTool、OpenAI API）に依存するテストは、実際の通信を行わない
  ようスタブまたはモックに置き換える。`OPENAI_API_KEY` がなくてもテストが通る
  状態を保つ。
