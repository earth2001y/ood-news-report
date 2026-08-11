# CLAUDE.md

## プロジェクト概要

OpenAI Agents SDK (`openai-agents`) を使い、Open OnDemand (OSC/ondemand) の
最新情報(新バージョンリリース、ロードマップ、セキュリティ脆弱性、
コミュニティイベント)をWeb検索で収集し、日本語で報告するCLIエージェント。

詳細な使い方は [README.md](../README.md) を参照。

## 構成

- `ood_news_agent.py` — エージェント本体(単一ファイル)。
  - `ReportItem` / `OODReport`: Agentの構造化出力スキーマ(Pydantic)。
  - `render_template`: `templates/` 配下のJinja2テンプレートをレンダリング。
    プロンプト文言をf文字列でコードにハードコードせず、テンプレートファイルに
    分離するために使う。
  - `build_agent`: WebSearchTool・出力スキーマを設定したAgentを構築。
    指示文は `render_template("instructions.j2")` で生成する。
  - `load_log` / `append_log`: `ood_report_log.md` の読み込み・追記。
    ログ照合(新規/更新/変更なしの判定)はLLM側で行い、ファイル書き込みは
    Python側で確定的に行う設計。
  - `write_report_file`: レポート本文を `$OUTDIR/report_YYYYMMDD_HHMM.md`
    として保存する。
  - `main`: CLIエントリポイント。Agentへのユーザー入力は
    `render_template("user_input.j2", ...)` で生成する。
- `templates/` — Agentへのプロンプト用Jinja2テンプレート。
  - `instructions.j2` — Agentの指示文(静的、変数なし)。
  - `user_input.j2` — 実行ごとのユーザー入力(調査対象期間・既存ログを埋め込む)。
- `ood_report_log.md` — 実行ごとに追記される報告済み項目ログ(初回実行時は
  存在しない。自動生成される)。リポジトリには含めない(`.gitignore` 対象)。
  フォーマットは [docs/ood_report_log_format.md](../docs/ood_report_log_format.md) 参照。
- `output/` — 実行ごとのレポートファイルの保存先(既定。`--outdir` /
  環境変数 `OUTDIR` で変更可)。リポジトリには含めない(`.gitignore` 対象)。
  フォーマットは [docs/report_file_format.md](../docs/report_file_format.md) 参照。
- `requirements.txt` — 依存パッケージ(`openai-agents`, `python-dotenv`,
  `jinja2`, `ruff`)。
- `pyproject.toml` — ruff の設定。
- `Makefile` — `make check`(ruff lint + format検証)/ `make format`(自動整形)。

## 実行前提

- `OPENAI_API_KEY` が必要(WebSearchTool を使うため、Web検索が有効なAPIキー)。
- 仮想環境は `.venv/` を使う。

## 開発時の静的検査

- コード変更後は `make check` を通すこと(ruff check + ruff format --check)。
- 自動整形が必要な場合は `make format` を実行する。

## コーディングルール

`.claude/rules/` 配下を参照。特に本プロジェクトでは
[function-design.md](rules/function-design.md)(関数ごとのGoogleスタイル
docstring、80行/3段ネストの制約)を全 `.py` ファイルに適用する。
