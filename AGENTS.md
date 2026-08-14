# AGENTS.md

> **このファイルが開発ガイドの実体である。** エージェント向けの規約は原則ここに
> 一元化し、各ツールの設定ディレクトリからは参照する。
>
> - `CLAUDE.md` — Claude Code 用。`@AGENTS.md` で本ファイルを取り込む。
> - `.claude/rules/*.md` — コーディングルール・設計指針・テスト指針の実体。
>   `paths:` でスコープ指定し、該当ファイルを読んだときだけ読み込まれる。
>   本ファイルには内容を複製しない（複製すると常時ロードになり遅延読み込みの
>   意味がなくなる）。
> - `.codex/config.toml` — Codex の設定のみ。規約は本ファイルを読む。
> - `.github/copilot-instructions.md`、`.github/instructions/*.md` — Copilot は
>   参照先を読み込まないため、必要な規約のみ**意図的に再掲**している。規約を
>   変更したときは、これらも合わせて更新する。
> - `.agents/skills/` — スキルの実体。`.claude/skills/` はここへのシンボリック
>   リンク。

## プロジェクト概要

OpenAI Agents SDK (`openai-agents`) を使い、Open OnDemand (OSC/ondemand) の
最新情報（新バージョンリリース、ロードマップ、セキュリティ脆弱性、
コミュニティイベント、その他のホットトピック）を Web 検索で収集し、日本語で報告する
CLI エージェント。

詳細な使い方は `README.md` を参照すること。

## 主な構成

- `ood_news_agent.py`: エージェント本体。調査担当 Agent の構造化出力を執筆担当
  Agent が記事へ再構成する 2 段構成である。
  - `ReportItem` / `OODReport` / `OODArticle`: 構造化出力スキーマ。
  - `setup_logging`: ログレベルを解決して設定する（`--log-level` / 環境変数
    `OOD_LOG_LEVEL`、既定は `WARNING`）。不正な値は警告して既定値で続行する。
  - `render_template`: `templates/` の Jinja2 テンプレートをレンダリングする。
  - `build_researcher_agent`: WebSearchTool と出力スキーマを設定した調査担当 Agent を
    構築する。
  - `build_writer_agent`: 調査結果を記事へ再構成する執筆担当 Agent を構築する
    （Web 検索ツールは持たせない）。
  - `compose_article`: 調査結果を執筆担当 Agent に渡し、記事本文を得る。
  - `load_log` / `append_log`: `ood_report_log.md` を読み込み、追記する。追記する
    のは `OODReport.log_entries` であり、再構成後の記事ではない。
  - `write_report_file`: 記事を `$OUTDIR/report_YYYYMMDD_HHMM.md` に保存する。
  - `describe_api_error`: OpenAI API のエラーを、対処方法を含む日本語メッセージに
    変換する。対処方法の文言は `API_ERROR_HINTS` に集約する。
  - `main`: CLI エントリポイント。Agent 実行は `APIError` を捕捉し、
    スタックトレースではなく `ERROR` ログを出して終了コード 1 を返す。
- `templates/`: Agent の指示文とユーザー入力の Jinja2 テンプレート
  （調査担当は `instructions.j2` / `user_input.j2`、執筆担当は
  `writer_instructions.j2` / `writer_input.j2`）。
- `docs/`: ログおよびレポートのファイル形式。
- `tests/`: pytest テスト。
- `pyproject.toml`: ruff と pytest の設定。
- `Makefile`: 開発用コマンド。

`ood_report_log.md` と `output/` は実行時に生成され、Git の追跡対象外である。

## 実行環境

- Python 3.12 以上を使用する。
- 仮想環境は `.venv/` を使用し、システム Python ではなく
  `.venv/bin/python3` と `.venv/bin/ruff` を実行する。
- WebSearchTool の実行には `OPENAI_API_KEY` が必要である。
- 開発操作は可能な限り `make` に集約する。利用可能なコマンドは `make help` で
  確認する。

## 変更と検証

- コードを変更したら `make test`（pytest）を実行する。
- 静的検査は `make check`、自動整形は `make format` を実行する。
- 本ファイルや `.claude/` / `.codex/` / `.github/` の設定を変更したら
  `make check-config` で矛盾を検査する（config-consistency スキル）。
- 検証が失敗している場合は、原因を確認してから修正する。

## コーディングルール・設計指針・テスト指針

以下のファイルに独立させている。Claude Code では `paths:` により、該当する
ファイルを読んだときだけ読み込まれる。他のツールを使う場合は作業対象に応じて
該当ファイルを開くこと。

| ファイル | 適用範囲 | 内容 |
| --- | --- | --- |
| `.claude/rules/coding-style.md` | `**/*.py` | PEP 8、ruff、ロガー、禁則処理、検証コマンド |
| `.claude/rules/function-design.md` | `**/*.py` | 命名、80 行、3 段ネスト、Google スタイル docstring |
| `.claude/rules/testing.md` | `tests/**/*.py`、`**/test_*.py`、`**/conftest.py` | pytest、テストコメント、モック方針 |

## Git コミット

詳細な規約は `.agents/skills/git-commits/SKILL.md` を参照する。要点は次のとおり。

- コミットメッセージは日本語で記載する。
- 1 行目に変更内容を簡潔に書き、空行の後に追加・変更内容と影響範囲を Markdown の
  箇条書きで記載する。
- 改行と Markdown の書式を保持するため、`git commit -F -` にヒアドキュメントで
  渡す。
- ユーザーから明示的に依頼されない限り、コミットは作成しない。
