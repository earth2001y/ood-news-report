# CLAUDE.md

プロジェクトの概要・構成・実行環境は [AGENTS.md](AGENTS.md) を実体とし、
`@` インポートで取り込む（Claude Code は `AGENTS.md` を自動では読まない）。

@AGENTS.md

## コーディングルール・設計指針・テスト指針

`.claude/rules/` 配下に独立させ、`paths:` でスコープを指定している。該当する
ファイルを読んだときだけコンテキストに読み込まれるため、常時ロードはしない。

| ファイル | 適用範囲 | 内容 |
| --- | --- | --- |
| [coding-style.md](.claude/rules/coding-style.md) | `**/*.py` | PEP 8、ruff、ロガー、禁則処理、検証コマンド |
| [function-design.md](.claude/rules/function-design.md) | `**/*.py` | 命名、80 行、3 段ネスト、Google スタイル docstring |
| [testing.md](.claude/rules/testing.md) | `tests/**/*.py`、`**/test_*.py`、`**/conftest.py` | pytest、テストコメント、モック方針 |

これらは `@` でインポートしない。`@` インポートは起動時に一括ロードされ、
`paths:` による遅延ロードが無効になるため。

## スキル

実体は `.agents/skills/`、`.claude/skills/` からシンボリックリンクで参照する。
本文は呼び出し時のみ読み込まれる。

| スキル | 用途 |
| --- | --- |
| [git-commits](.agents/skills/git-commits/SKILL.md) | コミットメッセージの作成 |
| [config-consistency](.agents/skills/config-consistency/SKILL.md) | 設定・ルールの矛盾検査（`make check-config`） |

## Claude Code 固有の設定

- [.claude/settings.json](.claude/settings.json) — 権限設定。
- [.claude/skills/](.claude/skills/) — `.agents/skills/` へのシンボリックリンク。

## 参照ドキュメント

- [README.md](README.md) — セットアップと使い方。
- [docs/ood_report_log_format.md](docs/ood_report_log_format.md) — ログの形式。
- [docs/report_file_format.md](docs/report_file_format.md) — レポートファイルの形式。
