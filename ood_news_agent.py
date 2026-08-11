#!/usr/bin/env python3
"""Open OnDemand の最新情報を収集し、日本語で報告するエージェント。

OpenAI Agents SDK (openai-agents) を使用し、WebSearchTool でWeb検索を行う。
実行するたびに、作業ディレクトリの ood_report_log.md と今回の調査結果を
突き合わせ、新規・更新のみを報告し、ログに追記する。レポート本文は標準出力に
加えて、$OUTDIR/report_YYYYMMDD_HHMM.md にも保存する。

使い方:
    export OPENAI_API_KEY=sk-...
    python ood_news_agent.py

    # ログファイルの場所やモデル、レポート出力先を変える場合
    python ood_news_agent.py --log-path ./ood_report_log.md --model gpt-5.4 --outdir ./output
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from agents import Agent, Runner, WebSearchTool

DEFAULT_WINDOW_DAYS = 14
FIRST_RUN_WINDOW_DAYS = 60

CATEGORIES = [
    "新バージョンのリリース情報",
    "開発ロードマップの更新・公開",
    "セキュリティ脆弱性情報",
    "コミュニティイベント",
]

REFERENCE_SOURCES = """
1. 新バージョンのリリース情報
   - https://github.com/OSC/ondemand/releases
   - https://github.com/OSC/ondemand/blob/master/CHANGELOG.md
   - https://discourse.openondemand.org/c/announcements/46
2. 開発ロードマップの更新・公開
   - https://discourse.openondemand.org/c/feature-requests-and-roadmap-discussion/48
3. セキュリティ脆弱性情報
   - https://github.com/OSC/ondemand/security/advisories
   - NVD (https://nvd.nist.gov/)
   - OSV.dev (https://osv.dev/)
4. コミュニティイベントの告知・CFP・開催報告
   - https://www.openondemand.org/ (トップページのイベント欄)
   - Discourse Announcements (https://discourse.openondemand.org/c/announcements/46)
   - GOOD Conference 公式サイト
""".strip()


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

    WebSearchToolによるWeb検索と、構造化出力(OODReport)を組み合わせたAgentを
    生成する。レポート本文(report_markdown)とログ追記用データ(log_entries)を
    出力スキーマ上で分離しているのは、ログファイルへの書き込みをLLMの自由記述に
    委ねず、呼び出し側(append_log)で確定的に行えるようにするため。

    Args:
        model: 使用するモデル名。WebSearchTool(Responses API)対応モデルを指定する。

    Returns:
        調査・報告用に指示文とツールを設定済みのAgentインスタンス。
    """
    instructions = f"""あなたは Open OnDemand (OSC/ondemand) に関する最新情報を調査し、
日本語で報告するリサーチエージェントです。

【調査対象カテゴリと参照先例】
{REFERENCE_SOURCES}

【調査範囲】
- ユーザーメッセージで与えられる「調査対象期間」内に公開・更新された情報のみを対象とする。
- 各カテゴリについて web_search ツールを使い、複数のクエリ
  (例: site:github.com/OSC/ondemand releases, site:discourse.openondemand.org roadmap,
  Open OnDemand CVE, Open OnDemand conference 2026 等)で調査すること。
- 参照先例のURL・サイトは出発点であり、他に関連する信頼できる情報源が見つかればそれも使ってよい。

【既報告項目との照合】
- ユーザーメッセージで、前回までの報告済み項目一覧(ログ)が渡される。ログが空の場合は初回実行である。
- 今回見つけた情報をログの既報告項目と照合し、以下のルールで分類する。
  - ログに存在しない完全に新規の情報 → status="新規"
  - ログの既報告項目と同一だが、内容に進展・変更がある場合
    (例: パッチバージョンの追加、CVEの深刻度・影響範囲の更新、イベント日程や会場の変更、
    ロードマップ項目の進捗変化など) → status="更新"。
    change_note に何がどう変わったかを具体的に明記する。
  - ログの既報告項目と全く変化がない場合 → 報告対象外(log_entries に含めない。再報告しない)
- 該当する新規・更新情報が全く見つからないカテゴリは、report_markdown 内でそのカテゴリを
  「変更なし」と明記する(見出しは残すが内容は「変更なし」のみ)。

【出力形式(report_markdown)】
- 日本語。
- カテゴリごとに簡潔にまとめる。見出しは最小限(カテゴリ名のみを見出しとする程度)にし、箇条書き中心。
- 各項目に「新規」または「更新」のラベルを明記する。
- 各項目に情報源のURLを添える。
- 前置きや後書きの冗長な説明は不要。簡潔に。

【出力形式(log_entries)】
- 今回「新規」または「更新」として報告した項目のみを構造化データとして返す
  (変更なしの項目は含めない)。
- これは呼び出し元プログラムがログファイルに追記するために使う。
  report_markdown の内容と整合させること。
"""
    return Agent(
        name="OOD News Reporter",
        instructions=instructions,
        model=model,
        tools=[WebSearchTool(search_context_size="medium")],
        output_type=OODReport,
    )


def load_log(log_path: Path) -> str:
    """報告済み項目ログをテキストとして読み込む。

    ログ本文をそのままAgentへの入力に埋め込み、既報告項目との照合をLLM側の
    テキスト理解に任せる設計のため、構造化パースはせず生テキストを返す。
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

    LLMの出力(entries)を検証・整形しつつファイル書き込みを行う処理を
    Python側に置くことで、書き込み内容と形式を確定的に保証する
    (LLMにファイル操作ツールを直接与えると、書式崩れや二重書き込みの
    リスクがあるため避けている)。entriesが空(変更なし)の場合は、
    ログを不必要に肥大化させないよう何も書き込まない。
    見出しに時刻(HH:MM)まで含めるのは、同じ日に複数回実行した場合でも
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

    標準出力だけでは実行環境によっては後から結果を追えないため、
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
    """CLIエントリポイント。ログ読み込み→調査実行→レポート表示→ログ追記を行う。

    引数解析・APIキー確認・調査期間の算出・Agent実行・ログ追記・レポート保存
    までを1関数にまとめているのは、これらが「1回の実行」というひとまとまりの
    処理であり、途中の値(run_at, log_path, report)を複数の下位関数に分けて
    渡すよりも直線的な処理として読めた方が全体の流れを把握しやすいため。
    ファイルI/OやAgent構築など再利用性のある処理は個別関数に分離してある。
    ログファイルが存在しない初回実行時は、直近14日間では過去の蓄積情報を
    取り漏らすため、調査対象期間を直近60日間に広げる。

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
    is_first_run = not log_path.exists()
    window_days = FIRST_RUN_WINDOW_DAYS if is_first_run else DEFAULT_WINDOW_DAYS
    window_start = today - timedelta(days=window_days)
    existing_log = load_log(log_path)

    agent = build_agent(model=args.model)

    user_input = f"""本日日付: {today.isoformat()}
調査対象期間: {window_start.isoformat()} 〜 {today.isoformat()} (直近{window_days}日間)

--- 前回までの報告済み項目ログ (ood_report_log.md の内容) ---
{existing_log}
--- ログ終わり ---

上記の調査対象期間について、指示された4カテゴリを調査し、ログと照合した上で
OODReport 形式で出力してください。
"""

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
