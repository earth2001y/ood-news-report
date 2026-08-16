#!/usr/bin/env python3
"""エージェント設定ファイルの矛盾を機械的に検出するスクリプト。

`.claude/`、`.codex/`、`.github/` とルートの `AGENTS.md` / `CLAUDE.md` を対象に、
リンク切れ・無効な `paths:`・実体の重複・シンボリックリンクの不整合を検査する。
config-consistency スキルから呼び出される。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RULES_DIR = ROOT / ".claude" / "rules"
SKILLS_SRC = ROOT / ".agents" / "skills"
SKILLS_LINK = ROOT / ".claude" / "skills"

# 検査対象の Markdown。.venv と .git は除外する。
EXCLUDE_PARTS = {".venv", ".git", "output"}

problems: list[str] = []


def report(category: str, message: str) -> None:
    """検出した問題を記録する。

    [実装理由] 検査項目ごとに即座に出力すると分類が混ざって読みにくいため、
    いったん蓄積して最後にまとめて表示する。
    """
    problems.append(f"[{category}] {message}")


def markdown_files() -> list[Path]:
    """検査対象の Markdown ファイルを列挙する。

    [実装理由] 仮想環境や出力ディレクトリ配下の Markdown は本リポジトリの規約
    対象外であり、検出してもノイズになるため除外する。
    """
    return sorted(
        p for p in ROOT.rglob("*.md") if not EXCLUDE_PARTS & set(p.relative_to(ROOT).parts)
    )


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """`paths:` の glob をパス照合用の正規表現に変換する。

    [実装理由] `fnmatch` は `**` を単一の `*` と同じに扱いディレクトリ境界を
    区別しないため、`**/` を「0 個以上のディレクトリ」として明示的に展開する。
    """
    escaped = re.escape(pattern)
    escaped = escaped.replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*")
    escaped = escaped.replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    return re.compile(f"^{escaped}$")


def parse_frontmatter(text: str) -> str | None:
    """Markdown 冒頭の YAML フロントマターを取り出す。

    [実装理由] PyYAML を依存に追加せずに済むよう、`---` で囲まれたブロックを
    文字列として取得し、必要なキーだけ正規表現で読む方針にした。
    """
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return match.group(1) if match else None


def check_links() -> None:
    """Markdown のリンクと `@` import の参照先が存在するか検査する。

    [実装理由] 参照の張り替え漏れは設定矛盾の中で最も頻出かつ機械判定が容易で
    あるため、最初に検査する。
    """
    for path in markdown_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for target in re.findall(r"^@(\S+)", text, re.M):
            if not (ROOT / target).exists():
                report("link", f"{rel}: @{target} が存在しない")
        for _, target in re.findall(r"\[([^\]]+)\]\(([^)#]+)", text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (path.parent / target).exists():
                report("link", f"{rel}: リンク切れ -> {target}")


def check_rule_paths() -> None:
    """`.claude/rules/*.md` の `paths:` が実ファイルにマッチするか検査する。

    [実装理由] glob の typo や対象ディレクトリの改名でルールが一切読み込まれ
    なくなっても無言で失敗するため、実ファイルとの照合で早期に検出する。
    まだ存在しない規約ファイル（`conftest.py` など）を先回りで指定するのは
    正当な用法なので、既知のファイル名は未マッチでも警告しない。
    """
    # 未作成でも正当な glob。typo と「これから作る」を区別するために列挙する。
    allowed_absent = {"**/conftest.py", "**/__init__.py"}
    if not RULES_DIR.is_dir():
        return
    py_files = [
        str(p.relative_to(ROOT))
        for p in ROOT.rglob("*.py")
        if not EXCLUDE_PARTS & set(p.relative_to(ROOT).parts)
    ]
    for rule in sorted(RULES_DIR.glob("*.md")):
        rel = rule.relative_to(ROOT)
        front = parse_frontmatter(rule.read_text(encoding="utf-8"))
        if front is None:
            report("rules", f"{rel}: フロントマターが無い（常時ロードになる）")
            continue
        if not re.search(r"^paths:", front, re.M):
            report("rules", f"{rel}: paths: が無い（常時ロードになる）")
            continue
        patterns = re.findall(r'^\s*-\s*"?([^"\s]+)"?\s*$', front, re.M)
        for pattern in patterns:
            if pattern in allowed_absent:
                continue
            regex = glob_to_regex(pattern)
            if not any(regex.match(f) for f in py_files):
                report("rules", f"{rel}: paths の '{pattern}' にマッチするファイルが無い")


def check_no_duplication() -> None:
    """ルールの内容が常時ロードされる文書に複製されていないか検査する。

    [実装理由] `@` import は起動時に一括ロードされるため、ルール本文を
    `AGENTS.md` や `CLAUDE.md` に複製すると `paths:` の遅延ロードが無効になる。
    """
    always_loaded = [ROOT / "AGENTS.md", ROOT / "CLAUDE.md"]
    # ルール本文に固有で、かつ再掲されやすい特徴的な文言。
    markers = {
        "80 行": "関数の行数制限",
        "3 段": "ネスト段数制限",
        "[実装理由]": "docstring 規約",
        "PEP 8": "コーディング規約",
    }
    for doc in always_loaded:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        body = re.sub(r"^\s*[|>].*$", "", text, flags=re.M)  # 表と引用は参照とみなす
        for marker, label in markers.items():
            if marker in body:
                report(
                    "duplication",
                    f"{doc.name}: {label}（'{marker}'）が本文にある。"
                    ".claude/rules/ に集約し、参照に書き換える",
                )


def check_claude_md() -> None:
    """`CLAUDE.md` の import 構成が原則どおりか検査する。

    [実装理由] Claude Code は `AGENTS.md` を自動では読まないため
    `@AGENTS.md` が必須である一方、ルールファイルの `@` import は遅延ロードを
    壊すため禁止しており、両者を同時に検査する。
    """
    claude_md = ROOT / "CLAUDE.md"
    if not claude_md.exists():
        report("claude-md", "CLAUDE.md が無い（Claude Code は AGENTS.md を読まない）")
        return
    text = claude_md.read_text(encoding="utf-8")
    imports = re.findall(r"^@(\S+)", text, re.M)
    if "AGENTS.md" not in imports:
        report("claude-md", "CLAUDE.md に @AGENTS.md が無い")
    for target in imports:
        if target.startswith(".claude/rules/"):
            report(
                "claude-md",
                f"CLAUDE.md が @{target} をインポートしている。"
                "paths: の遅延ロードが無効になるため参照に変更する",
            )


def check_skills() -> None:
    """スキルの実体とシンボリックリンクの整合性を検査する。

    [実装理由] 実体を `.agents/skills/` に置きリンクで共有する構成のため、
    リンク切れや絶対パス化に気付けるようにする。絶対パスは他環境で壊れる。
    """
    if not SKILLS_SRC.is_dir():
        return
    for skill_dir in sorted(p for p in SKILLS_SRC.iterdir() if p.is_dir()):
        name = skill_dir.name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            report("skills", f"{name}: SKILL.md が無い")
            continue
        front = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        if front is None:
            report("skills", f"{name}: フロントマターが無い")
            continue
        declared = re.search(r"^name:\s*(\S+)", front, re.M)
        if not declared:
            report("skills", f"{name}: name: が無い")
        elif declared.group(1) != name:
            report("skills", f"{name}: name '{declared.group(1)}' がディレクトリ名と不一致")
        if not re.search(r"^description:\s*\S", front, re.M):
            report("skills", f"{name}: description: が無い（自動呼び出しされない）")

        link = SKILLS_LINK / name
        if not link.exists():
            report("skills", f"{name}: .claude/skills/{name} のリンクが無い")
        elif not link.is_symlink():
            report("skills", f"{name}: .claude/skills/{name} がリンクではない（実体の重複）")
        else:
            target = link.readlink()
            if target.is_absolute():
                report("skills", f"{name}: リンクが絶対パス（他環境で壊れる）: {target}")
            elif link.resolve() != skill_dir.resolve():
                report("skills", f"{name}: リンク先が実体と異なる: {target}")


def check_make_targets() -> None:
    """ドキュメントが参照する `make` ターゲットが実在するか検査する。

    [実装理由] `Makefile` のターゲット名変更に追従できていないドキュメントは、
    読んだエージェントが存在しないコマンドを実行する原因になる。
    """
    makefile = ROOT / "Makefile"
    if not makefile.exists():
        return
    text = makefile.read_text(encoding="utf-8")
    targets = set(re.findall(r"^([a-zA-Z0-9_-]+):", text, re.M))
    for path in markdown_files():
        rel = path.relative_to(ROOT)
        referenced = set(re.findall(r"`make ([a-zA-Z0-9_-]+)`", path.read_text(encoding="utf-8")))
        for target in sorted(referenced - targets):
            report("make", f"{rel}: `make {target}` は Makefile に存在しない")


def main() -> int:
    """すべての検査を実行し、結果を表示する。

    [実装理由] 終了コードで成否を返し、矛盾があれば 1 を返すことで、
    スキルの手順内から結果を機械的に判定できるようにする。
    """
    check_links()
    check_rule_paths()
    check_no_duplication()
    check_claude_md()
    check_skills()
    check_make_targets()

    if not problems:
        print("OK: 設定・ルールの矛盾は検出されませんでした。")
        return 0

    print(f"{len(problems)} 件の問題を検出しました:\n")
    for problem in problems:
        print(f"  - {problem}")
    print("\n意味の矛盾（数値・固有名詞の食い違い）は SKILL.md の手順 2 で目視確認する。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
