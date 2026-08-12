#!/usr/bin/env python3
"""Open OnDemand の最新情報を収集し、日本語で報告するエージェント。

OpenAI Agents SDK (openai-agents) を使用し、WebSearchTool でWeb検索を行う。実行するたびに、
作業ディレクトリの ood_report_log.md と今回の調査結果を突き合わせ、新規・更新のみを報告し、
ログに追記する。レポート本文は標準出力に加えて、$OUTDIR/report_YYYYMMDD_HHMM.md にも保存する。

使い方:
    export OPENAI_API_KEY=sk-...
    python ood_news_agent.py

    # ログファイルの場所やモデル、レポート出力先を変える場合
    python ood_news_agent.py --log-path ./ood_report_log.md --model gpt-5.4 --outdir ./output

    # 調査対象期間(日数)を変える場合
    python ood_news_agent.py --window-days 30
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from agents import Agent, Runner, WebSearchTool
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

load_dotenv()

DEFAULT_WINDOW_DAYS = 30

TEMPLATES_DIR = Path(__file__).parent / "templates"

CATEGORIES = [
    "新バージョンのリリース情報",
    "開発ロードマップの更新・公開",
    "セキュリティ脆弱性情報",
    "コミュニティイベント",
]

_jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    keep_trailing_newline=True,
)


def render_template(name: str, **context: object) -> str:
    """`templates/` ディレクトリのJinja2テンプレートをレンダリングする。

    [実装理由] Agentへの指示文やユーザー入力プロンプトをPythonコード中にf文字列でハードコードする
    と、文言調整のたびにコード変更が必要になりレビューもしづらいため、テンプレートファイルに分離して
    いる。

    Args:
        name: `templates/` ディレクトリ内のテンプレートファイル名。
        **context: テンプレートに渡す変数。

    Returns:
        レンダリング済みの文字列。
    """
    return _jinja_env.get_template(name).render(**context)


class ReportItem(BaseModel):
    category: Literal[
        "新バージョンのリリース情報",
        "開発ロードマップの更新・公開",
        "セキュリティ脆弱性情報",
        "コミュニティイベント",
    ] = Field(description="4カテゴリのいずれか")
    status: Literal["新規", "更新"] = Field(description="変更なしの項目はここに含めない")
    title: str = Field(description="項目のタイトル(バージョン名、CVE ID、イベント名など)")
    item_date: str = Field(description="公開日・更新日。YYYY-MM-DD形式。不明な場合は空文字")
    url: str = Field(description="情報源のURL")
    summary: str = Field(description="日本語での簡潔な要約")
    change_note: str = Field(
        default="",
        description="status が『更新』の場合、何がどう変わったかを明記。新規の場合は空文字",
    )


class OODReport(BaseModel):
    report_markdown: str = Field(
        description="ユーザーにそのまま提示する、日本語・カテゴリ別・箇条書き中心の最終レポート本文"
    )
    log_entries: list[ReportItem] = Field(
        description="今回『新規』または『更新』として報告した項目のみのリスト(変更なしは含めない)"
    )


def build_agent(model: str) -> Agent:
    """Open OnDemand調査用のAgentを構築する。

    [実装理由] WebSearchToolによるWeb検索と、構造化出力(OODReport)を組み合わせたAgentを生成する。
    レポート本文(report_markdown)とログ追記用データ(log_entries)を出力スキーマ上で分離しているのは、
    ログファイルへの書き込みをLLMの自由記述に委ねず、
    呼び出し側(append_log)で確定的に行えるようにするため。

    Args:
        model: 使用するモデル名。WebSearchTool(Responses API)対応モデルを指定する。

    Returns:
        調査・報告用に指示文とツールを設定済みのAgentインスタンス。
    """
    instructions = render_template("instructions.j2")
    return Agent(
        name="OOD News Reporter",
        instructions=instructions,
        model=model,
        tools=[WebSearchTool(search_context_size="medium")],
        output_type=OODReport,
    )


def load_log(log_path: Path) -> str:
    """報告済み項目ログをテキストとして読み込む。

    [実装理由] ログ本文をそのままAgentへの入力に埋め込み、
    既報告項目との照合をLLM側のテキスト理解に任せる設計のため、構造化パースはせず生テキストを返す。
    ファイルが存在しない/空の場合も呼び出し側でエラーにせず処理を継続できるよう、
    その旨を示す文言を返す。

    Args:
        log_path: ood_report_log.md のパス。

    Returns:
        ログファイルの内容。存在しない、または空の場合は初回実行を示す文言。
    """
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8").strip()
        return content if content else "(まだ記録はありません。今回が初回実行です)"
    return "(ログファイルが存在しません。今回が初回実行です)"


def append_log(log_path: Path, run_at: datetime, entries: list[ReportItem]) -> None:
    """今回「新規」「更新」と判定された項目をログファイルに追記する。

    [実装理由] LLMの出力(entries)を整形しつつファイル書き込みを行う処理をPython側に置くことで、書き
    込み内容と形式を確定的に保証する(LLMにファイル操作ツールを直接与えると、書式崩れや二重書き込みの
    リスクがあるため避けている)。entriesが空(変更なし)の場合は、ログを不必要に肥大化させないよう何も
    書き込まない。見出しに時刻(HH:MM)まで含めるのは、同じ日に複数回実行した場合でも
    docs/ood_report_log_format.md の仕様どおり実行分を区別できるようにするため。

    Args:
        log_path: ood_report_log.md のパス。
        run_at: 実行日時。追記セクションの見出し(YYYY-MM-DD HH:MM)に使う。
        entries: 今回「新規」または「更新」として報告した項目のリスト。

    Returns:
        None
    """
    if not entries:
        return
    lines = [f"\n## {run_at.strftime('%Y-%m-%d %H:%M')} 実行分\n"]
    for cat in CATEGORIES:
        cat_entries = [e for e in entries if e.category == cat]
        if not cat_entries:
            continue
        lines.append(f"### {cat}\n")
        for e in cat_entries:
            date_part = f" ({e.item_date})" if e.item_date else ""
            lines.append(f"- [{e.status}] {e.title}{date_part} - {e.summary} - {e.url}")
        lines.append("")
    text = "\n".join(lines) + "\n"

    if log_path.exists():
        with log_path.open("a", encoding="utf-8") as f:
            f.write(text)
    else:
        header = "# Open OnDemand 情報収集 報告ログ\n"
        with log_path.open("w", encoding="utf-8") as f:
            f.write(header + text)


def write_report_file(outdir: Path, run_at: datetime, report_markdown: str) -> Path:
    """レポート本文を `report_<実行日時>.md` としてファイルに保存する。

    [実装理由] 標準出力だけでは実行環境によっては後から結果を追えないため、
    実行ごとに一意なファイル名(分単位のタイムスタンプ入り)で保存し、
    過去のレポートを上書きせず蓄積できるようにする。

    Args:
        outdir: 出力先ディレクトリ。存在しない場合は作成する。
        run_at: 実行日時。ファイル名(YYYYMMDD_HHMM)に使う。
        report_markdown: 保存するレポート本文(Markdown)。

    Returns:
        書き込んだファイルのパス。
    """
    outdir.mkdir(parents=True, exist_ok=True)
    report_path = outdir / f"report_{run_at.strftime('%Y%m%d_%H%M')}.md"
    report_path.write_text(report_markdown, encoding="utf-8")
    return report_path


def main() -> int:
    """CLIエントリポイント。調査を実行し、ログ追記・レポート保存・結果表示までを行う。

    [実装理由] 引数解析からAgent実行・ログ追記・レポート保存までを1関数にまとめているのは、これらが
    「1回の実行」というひとまとまりの処理であり、run_at・log_path・report のような途中の値を下位関数
    間で受け渡すよりも、直線的な処理として読める方が全体の流れを把握しやすいためである。ファイルI/O
    やAgent構築など再利用性のある処理は個別関数に分離し、mainはその呼び出し順序の制御に専念する。ま
    た、調査対象期間は初回実行かどうかにかかわらず既定で30日固定とし、`--window-days`(または環境変数
    WINDOW_DAYS)を指定した場合のみ上書きするという挙動も、この関数内の設計判断として含まれる。

    Returns:
        プロセス終了コード。正常終了は0、APIキー未設定時は1。
    """
    parser = argparse.ArgumentParser(description="Open OnDemand 最新情報収集エージェント")
    parser.add_argument(
        "--log-path",
        default="ood_report_log.md",
        help="報告済み項目ログのパス (既定: ./ood_report_log.md)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OOD_AGENT_MODEL", "gpt-5.4"),
        help="使用するモデル (既定: gpt-5.4。WebSearchTool対応モデルを指定すること)",
    )
    parser.add_argument(
        "--outdir",
        default=os.environ.get("OUTDIR", "output"),
        help="レポートファイルの出力先ディレクトリ (既定: 環境変数 OUTDIR、未設定なら ./output)",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=os.environ.get("WINDOW_DAYS"),
        help=f"調査対象期間(日数) (既定: 環境変数 WINDOW_DAYS、未設定なら{DEFAULT_WINDOW_DAYS}日)",
    )
    parser.add_argument("--max-turns", type=int, default=40)
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "エラー: 環境変数 OPENAI_API_KEY が設定されていません。\n"
            "export OPENAI_API_KEY=sk-... を実行するか、.env ファイルに設定してください。",
            file=sys.stderr,
        )
        return 1

    log_path = Path(args.log_path)
    run_at = datetime.now()
    today = run_at.date()
    window_days = args.window_days if args.window_days is not None else DEFAULT_WINDOW_DAYS
    window_start = today - timedelta(days=window_days)
    existing_log = load_log(log_path)

    agent = build_agent(model=args.model)

    user_input = render_template(
        "user_input.j2",
        today=today.isoformat(),
        window_start=window_start.isoformat(),
        window_days=window_days,
        existing_log=existing_log,
    )

    period = f"{window_start.isoformat()} 〜 {today.isoformat()}"
    print(f"Open OnDemand の最新情報を調査中... (対象期間: {period})", file=sys.stderr)

    result = Runner.run_sync(agent, input=user_input, max_turns=args.max_turns)
    report: OODReport = result.final_output

    append_log(log_path, run_at, report.log_entries)
    report_path = write_report_file(Path(args.outdir), run_at, report.report_markdown)

    print(report.report_markdown)
    print(
        f"\n(ログファイル {log_path} に {len(report.log_entries)} 件を追記しました)"
        f"\n(レポートを {report_path} に保存しました)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
