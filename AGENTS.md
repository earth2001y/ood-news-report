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
コミュニティイベント、その他のトピック）を Web 検索で収集し、日本語で報告する
CLI エージェント。

詳細な使い方は `README.md` を参照すること。

## 主な構成

- `app/`: 調査・執筆の 2 段処理を実装する Python パッケージ。
  - `__main__.py`: `python -m app` の実行エントリポイント。
  - `cli.py`: 期間・ログ・出力・エラー処理を担い、調査担当と執筆担当を接続する。
    - `setup_logging`: ログレベルを解決して設定する（`--log-level` / 環境変数
      `OOD_LOG_LEVEL`、既定は `WARNING`）。不正な値は警告して既定値で続行する。
    - `resolve_base_date`: 調査対象期間の基準日を決定する（`--base-date` / 環境変数
      `BASE_DATE`、未指定なら実行日）。書式不正は `ValueError` にする。
    - `resolve_log_dir` / `resolve_max_log_runs` / `log_file_path` / `list_log_files`:
      調査ログの保存先（環境変数 `LOGDIR`）、読み込む調査回数の上限（`--max-log-runs` /
      環境変数 `MAX_LOG_RUNS`、既定は 10、0 以下で上限なし）、調査回ごとのファイル名、
      読み込み対象ファイルの一覧を決める。
    - `read_log_entries` / `load_log` / `append_log`: 調査ログは調査回ごとに 1 ファイル
      （`ood_research_log_YYYYMMDD_HHMM.json`）とし、`append_log` は既存ファイルへ追記せず
      新しいファイルを書き出す。`load_log` は上限の範囲で複数ファイルを読み込み、各ファイルの
      `entries` を結合して 1 つの Markdown にする。記録するのは `OODReport.entries` であり、
      執筆後の記事ではない。
    - `write_report_file`: 記事を `$OUTDIR/report_YYYYMMDD_HHMM.md` に保存する。
    - `describe_api_error`: OpenAI API のエラーを、対処方法を含む英語メッセージに
      変換する。対処方法の文言は `API_ERROR_HINTS` に集約する。
    - `main`: CLI エントリポイント。Agent 実行は `APIError` を捕捉し、
      スタックトレースではなく `ERROR` ログを出して終了コード 1 を返す。
  - `news_models.py`: `ReportItem` / `OODReport` の構造化出力スキーマと、`CATEGORIES` /
    `STATUSES` の照合キー。フィールドの説明は英語で書き、`summary` / `change_note` も
    英語で出力させる。
  - `researcher.py`: 調査担当 Agent。Agent と入力プロンプトの構築、Web 検索を伴う実行を担う。
  - `writer.py`: 執筆担当 Agent。`OODArticle` の出力スキーマ、`CATEGORY_DESCRIPTIONS`、
    Agent と入力プロンプトの構築、記事執筆の実行を担う。調査結果の日本語化はこの
    Agent の役割である。入力の事実を理解するため Web 検索ツールを持つが、検索で得た
    新たな事実を記事へ追加しないよう指示する。
  - `prompt_templates.py`: ルートの `templates/` にある Jinja2 テンプレートを
    共通の規則でレンダリングする。
- `templates/`: Agent の指示文と入力プロンプト。調査結果は執筆担当 Agent へ渡すまで
  英語で一貫させ、記事の日本語（セクション見出しを含む）は執筆担当 Agent が生成する。
- `docs/`: ログおよびレポートのファイル形式。
- `tests/`: pytest テスト。
- `pyproject.toml`: ruff と pytest の設定。
- `Makefile`: 開発用コマンド。

`.research_log/`（`LOGDIR` で変更可）配下の調査回ごとの調査ログと `output/` は実行時に
生成され、Git の追跡対象外である。

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
