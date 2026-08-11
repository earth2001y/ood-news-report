# CLAUDE.md

## プロジェクト概要

OpenAI Agents SDK (`openai-agents`) を使い、Open OnDemand (OSC/ondemand) の
最新情報(新バージョンリリース、ロードマップ、セキュリティ脆弱性、
コミュニティイベント)をWeb検索で収集し、日本語で報告するCLIエージェント。

詳細な使い方は [README.md](../README.md) を参照。

## 構成

- `ood_news_agent.py` — エージェント本体(単一ファイル)。
  - `ReportItem` / `OODReport`: Agentの構造化出力スキーマ(Pydantic)。
  - `build_agent`: WebSearchTool・出力スキーマを設定したAgentを構築。
  - `load_log` / `append_log`: `ood_report_log.md` の読み込み・追記。
    ログ照合(新規/更新/変更なしの判定)はLLM側で行い、ファイル書き込みは
    Python側で確定的に行う設計。
  - `main`: CLIエントリポイント。
- `ood_report_log.md` — 実行ごとに追記される報告済み項目ログ(初回実行時は
  存在しない。自動生成される)。
- `requirements.txt` — 依存パッケージ(`openai-agents`, `python-dotenv`)。

## 実行前提

- `OPENAI_API_KEY` が必要(WebSearchTool を使うため、Web検索が有効なAPIキー)。
- 仮想環境は `.venv/` を使う。

## コーディングルール

`.claude/rules/` 配下を参照。特に本プロジェクトでは
[function-design.md](rules/function-design.md)(関数ごとのGoogleスタイル
docstring、80行/3段ネストの制約)を全 `.py` ファイルに適用する。
