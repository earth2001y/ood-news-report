---
name: config-consistency
description: エージェント設定ファイル（AGENTS.md、CLAUDE.md、.claude/、.codex/、.github/）の矛盾を検査して修正する。規約を追加・変更したとき、設定ファイルを編集したとき、ツール用の設定ディレクトリを追加したとき、「設定の矛盾を確認」「ルールの整合性をチェック」と依頼されたときに使う。リンク切れ、無効なフロントマター、実体の重複、規約の食い違いを検出する。
---

# エージェント設定の整合性検査

`.claude/`、`.codex/`、`.github/` と、ルートの `AGENTS.md` / `CLAUDE.md` の間で
設定・規約が矛盾していないかを検査し、必要なら修正する。

## 本リポジトリの構成原則

検査はこの原則に対する違反を探す。

1. **`AGENTS.md` が開発ガイドの実体。** 概要・構成・実行環境・`make` コマンドを
   持つ。Claude Code は `AGENTS.md` を自動では読まないため、`CLAUDE.md` から
   `@AGENTS.md` で取り込む。この import は必須。
2. **`.claude/rules/*.md` が規約の実体。** `paths:` でスコープを指定し、該当
   ファイルを読んだときだけ遅延ロードされる。
3. **`.claude/rules/` の内容を `AGENTS.md` / `CLAUDE.md` に複製しない。**
   `@` import は起動時に一括ロードされるため、複製すると `paths:` の遅延ロードが
   無効になる。ルールファイルを `@` でインポートしてもいけない。
4. **`.github/` は意図的な重複。** Copilot は参照先を読み込まないため、規約を
   inline で再掲する。ここだけは重複を許容し、その代わり**内容が食い違っては
   いけない**。
5. **`.codex/` は設定のみ。** Codex はルートの `AGENTS.md` をネイティブに読むため、
   規約を複製しない。
6. **スキルの実体は `.agents/skills/`。** `.claude/skills/` からの相対
   シンボリックリンクで共有する。

## 手順

### 1. 自動検査を実行する

このスキル同梱のスクリプトで機械的に検出できる矛盾を洗い出す。

```sh
make check-config
```

検出項目:

- リンク切れ（Markdown リンク、`@` import、シンボリックリンク）
- `.claude/rules/*.md` の `paths:` が実ファイルにマッチしない（typo・古い glob）
- `paths:` を持たないルール（意図せず常時ロードになっている）
- `.claude/rules/` の内容が `AGENTS.md` / `CLAUDE.md` に複製されている
- `CLAUDE.md` に `@AGENTS.md` が無い
- ルールファイルが `@` でインポートされている
- スキルの `SKILL.md` に `name` / `description` が無い、`name` がディレクトリ名と不一致
- `.claude/skills/` のリンクが `.agents/skills/` を指していない、絶対パスになっている
- 参照されている `make` ターゲットが `Makefile` に存在しない

### 2. 規約の食い違いを目視で照合する

スクリプトでは判定できない**意味の矛盾**を確認する。特に数値と固有名詞。

| 確認項目 | 実体 | 再掲先 |
| --- | --- | --- |
| 行長（100） | `pyproject.toml` | `.claude/rules/coding-style.md`、`.github/*` |
| 関数の行数（80 行） | `.claude/rules/function-design.md` | `.github/*` |
| ネスト段数（3 段） | `.claude/rules/function-design.md` | `.github/*` |
| Python バージョン（3.12+） | `pyproject.toml` | `AGENTS.md`、`.claude/rules/*`、`.github/*` |
| ruff の select | `pyproject.toml` | `.claude/rules/coding-style.md` |
| `make` の各ターゲットの実際の動作 | `Makefile` | すべて |
| docstring 規約（`[実装理由]`） | `.claude/rules/function-design.md` | `.github/*` |

`pyproject.toml` と `Makefile` が最終的な実体である。ドキュメントの記述がこれらと
食い違っていたら、**ドキュメント側を直す**。

### 3. 修正する

- **実体が重複している** → 実体を 1 箇所に決め、他方を参照に書き換える。
  ただし `.github/` は原則 4 により inline のまま内容を同期する。
- **`.github/` の内容が古い** → 実体に合わせて書き換える。冒頭に「実体は
  `AGENTS.md`、変更時は両方更新」の注記があることも確認する。
- **`paths:` が壊れている** → 実ファイルにマッチする glob に修正する。
- **リンク切れ** → 参照先の移動先を確認して修正する。参照先が削除されていたら
  参照ごと削除する。

### 4. 再検査する

```sh
make check-config
```

`make check` と `make test` も実行し、ドキュメント修正がコードに影響していない
ことを確認する。

## 注意

- **空ディレクトリは矛盾として扱わない。** `.codex/rules/`、`.github/skills/` など
  は将来の利用のために意図的に残されている場合がある。git は空ディレクトリを
  追跡しないため実害もない。削除は提案のみとし、勝手に消さない。
- **`.github/instructions/*.md` の `applyTo:` は Copilot の実機能。** Claude Code の
  `paths:` とは別物なので、片方に合わせて他方を消してはいけない。
- **フロントマターの仕様を推測しない。** `paths:`（Claude Code のルール・スキル）と
  `applyTo:`（Copilot）はいずれも実在する機能である。未知のキーを見つけたら、
  無効と決めつけて削除する前にドキュメントで確認する。
- 検査の結果ドキュメントを書き換えるときは、規約の**内容自体は変更しない**。
  矛盾の解消に必要な範囲に留め、規約を変えるべきだと判断した場合はユーザーに
  確認する。
