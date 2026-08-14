#!/usr/bin/env python3
"""Open OnDemand の最新情報を収集し、日本語で報告するエージェント。

OpenAI Agents SDK (openai-agents) を使用し、WebSearchTool でWeb検索を行う。実行するたびに、
作業ディレクトリの ood_report_log.md と今回の調査結果を突き合わせ、新規・更新のみを報告し、
ログに追記する。処理は2段構成で、調査担当Agentの構造化出力(OODReport)を執筆担当Agentが
ニュースレター記事(OODArticle)へ再構成する。記事本文は標準出力に加えて、
$OUTDIR/report_YYYYMMDD_HHMM.md にも保存する。ログに追記するのは調査担当Agentの
構造化出力(log_entries)であり、再構成の影響を受けない。

使い方:
    export OPENAI_API_KEY=sk-...
    python ood_news_agent.py

    # ログファイルの場所やモデル、レポート出力先を変える場合
    python ood_news_agent.py --log-path ./ood_report_log.md --model gpt-5.4 --outdir ./output

    # 記事再構成だけ別のモデルで行う場合
    python ood_news_agent.py --writer-model gpt-5.4

    # 調査対象期間(日数)を変える場合
    python ood_news_agent.py --window-days 30

    # 調査対象期間の基準日を指定する場合(既定は実行日)
    python ood_news_agent.py --base-date 2026-07-31
    BASE_DATE=2026-07-31 python ood_news_agent.py

    # 進捗を表示する場合(既定のログレベルは WARNING)
    python ood_news_agent.py --log-level INFO
    OOD_LOG_LEVEL=INFO python ood_news_agent.py
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from agents import Agent, Runner, WebSearchTool
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from openai import APIError
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 30

BASE_DATE_FORMAT = "%Y-%m-%d"

DEFAULT_LOG_LEVEL = "WARNING"

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

TEMPLATES_DIR = Path(__file__).parent / "templates"

CATEGORIES = [
    "新バージョンのリリース情報",
    "開発ロードマップの更新・公開",
    "セキュリティ脆弱性情報",
    "コミュニティイベント",
    "その他のホットトピック",
]

_jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    keep_trailing_newline=True,
)


def setup_logging(level_name: str | None) -> int:
    """ロガーの出力レベルを設定する。

    [実装理由] ログレベルをCLIオプションと環境変数の両方で指定できるようにしつつ、その解決と
    `logging.basicConfig` の呼び出しをこの関数に集約している。既定を WARNING にしているのは、
    通常実行時に利用者が見たいのは記事本文とエラーだけであり、進捗や内部状態の出力は調査時にだけ
    有効にすべきものだからである。不正な値でエラー終了せず警告して既定値で続行するのは、ログ設定の
    タイポで調査本体(API呼び出しを伴う主目的の処理)を止めてしまう方が損失が大きいためである。
    警告は設定前のレベルに依存せず届くよう、`basicConfig` を済ませた後に出力する。

    Args:
        level_name: 設定するログレベル名(大文字小文字は区別しない)。Noneの場合は既定値を使う。

    Returns:
        実際に設定したログレベルの数値(`logging.WARNING` など)。
    """
    requested = (level_name or DEFAULT_LOG_LEVEL).upper()
    invalid = requested not in LOG_LEVELS
    resolved = DEFAULT_LOG_LEVEL if invalid else requested

    logging.basicConfig(level=resolved, format="%(levelname)s: %(message)s", force=True)
    if invalid:
        logger.warning(
            "ログレベル %r は不正です。%s を使用します。指定できる値: %s",
            level_name,
            DEFAULT_LOG_LEVEL,
            ", ".join(LOG_LEVELS),
        )
    return logging.getLevelNamesMapping()[resolved]


def resolve_base_date(base_date: str | None, run_at: datetime) -> date:
    """調査対象期間の基準日を決定する。

    [実装理由] 基準日を実行日から切り離せるようにしているのは、過去のある時点を基準にした調査を
    後から再現したり、実行が数日遅れた分をさかのぼって調査したりする必要があるためである。未指定時に
    実行日を使うのは、日常的な運用では「今日までの直近N日間」が求められる挙動だからである。
    不正な書式をログレベル(setup_logging)のように警告して続行させず例外にしているのは、基準日の
    誤りが調査対象期間そのものをずらし、誤った期間のレポートを正常な結果として出力してしまうためで
    ある。実行日時(run_at)を引数で受け取るのは、この関数が現在時刻を直接読まないようにして、
    テストから基準日の解決だけを検証できるようにするためである。

    Args:
        base_date: 基準日の文字列(YYYY-MM-DD)。Noneの場合は実行日を使う。
        run_at: 実行日時。base_dateがNoneのときの基準日として使う。

    Returns:
        調査対象期間の終端となる基準日。

    Raises:
        ValueError: base_dateがYYYY-MM-DD形式として解釈できない場合。
    """
    if base_date is None:
        return run_at.date()
    try:
        return datetime.strptime(base_date, BASE_DATE_FORMAT).date()
    except ValueError as e:
        raise ValueError(
            f"基準日 {base_date!r} を解釈できません。YYYY-MM-DD 形式で指定してください。"
        ) from e


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
        "その他のホットトピック",
    ] = Field(description="5カテゴリのいずれか")
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


class OODArticle(BaseModel):
    article_markdown: str = Field(
        description="調査結果を再構成した、日本語のニュースレター記事本文(Markdown)"
    )


def build_researcher_agent(model: str) -> Agent:
    """Open OnDemand調査用の調査担当Agentを構築する。

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


def build_writer_agent(model: str) -> Agent:
    """調査結果をニュースレター記事へ再構成するAgentを構築する。

    [実装理由] 調査担当Agentの出力は箇条書き中心の報告文であり、読み物としての流れを欠く。
    同じAgentに調査と執筆の両方を担わせると、Web検索の途中経過が文章構成の判断に混ざり、
    どちらの品質も安定しないため、執筆専用のAgentとして分離している。
    WebSearchToolは入力の事実を理解するための補足調査に限定し、検索で得た新たな事実は記事に
    追加しないよう指示文で制約している。

    Args:
        model: 使用するモデル名。WebSearchTool(Responses API)対応モデルを指定する。

    Returns:
        記事執筆用に指示文と出力スキーマを設定済みのAgentインスタンス。
    """
    instructions = render_template("writer_instructions.j2", categories=CATEGORIES)
    return Agent(
        name="OOD News Writer",
        instructions=instructions,
        model=model,
        tools=[WebSearchTool(search_context_size="medium")],
        output_type=OODArticle,
    )


def compose_article(
    writer: Agent,
    report: OODReport,
    base_date: str,
    window_start: str,
    window_days: int,
    max_turns: int,
) -> str:
    """調査結果(OODReport)を執筆担当Agentに渡し、記事本文を得る。

    [実装理由] 執筆担当Agentへの入力組み立てと実行をmainから切り出しているのは、入力に含める情報
    (構造化された項目一覧と調査担当Agentの報告文)の範囲がこのステップの出力品質を左右する設計上の
    要点であり、単独で読めて単独でテストできる形にしておきたいためである。構造化データ(log_entries)
    だけでなく report_markdown も併せて渡すのは、カテゴリごとの「変更なし」判定など、構造化データに
    現れない調査担当Agentの判断を執筆側から参照できるようにするため。

    Args:
        writer: build_writer_agentで構築した執筆担当Agent。
        report: 調査担当Agentの構造化出力。
        base_date: 調査対象期間の基準日(YYYY-MM-DD)。期間の終端にあたる。
        window_start: 調査対象期間の開始日(YYYY-MM-DD)。
        window_days: 調査対象期間の日数。
        max_turns: Agent実行の最大ターン数。

    Returns:
        再構成された記事本文(Markdown)。
    """
    writer_input = render_template(
        "writer_input.j2",
        base_date=base_date,
        window_start=window_start,
        window_days=window_days,
        entries=report.log_entries,
        report_markdown=report.report_markdown,
    )
    result = Runner.run_sync(writer, input=writer_input, max_turns=max_turns)
    article: OODArticle = result.final_output
    return article.article_markdown


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


def write_report_file(outdir: Path, run_at: datetime, article_markdown: str) -> Path:
    """レポート本文を `report_<実行日時>.md` としてファイルに保存する。

    [実装理由] 標準出力だけでは実行環境によっては後から結果を追えないため、
    実行ごとに一意なファイル名(分単位のタイムスタンプ入り)で保存し、
    過去のレポートを上書きせず蓄積できるようにする。保存するのは執筆担当Agentが再構成した記事本文で
    あり、調査担当Agentの箇条書き報告文は保存しない。両方を残すとどちらが正なのか読み手が判断できず、
    ログ(ood_report_log.md)に構造化データが残っている以上、記事側は読み物として一本化する方が
    用途が明確になるためである。

    Args:
        outdir: 出力先ディレクトリ。存在しない場合は作成する。
        run_at: 実行日時。ファイル名(YYYYMMDD_HHMM)に使う。
        article_markdown: 保存する記事本文(Markdown)。

    Returns:
        書き込んだファイルのパス。
    """
    outdir.mkdir(parents=True, exist_ok=True)
    report_path = outdir / f"report_{run_at.strftime('%Y%m%d_%H%M')}.md"
    report_path.write_text(article_markdown, encoding="utf-8")
    return report_path


def build_parser() -> argparse.ArgumentParser:
    """CLI引数を定義したArgumentParserを構築する。

    [実装理由] 引数の仕様をパース実行から分離することで、定義内容を単独で確認でき、CLI以外の
    呼び出し元でも同じパーサを再利用できるようにする。

    Returns:
        CLI引数が定義されたArgumentParser。
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
        "--writer-model",
        default=os.environ.get("OOD_WRITER_MODEL"),
        help=(
            "記事再構成に使うWebSearchTool対応モデル "
            "(既定: 環境変数 OOD_WRITER_MODEL、未設定なら --model と同じ)"
        ),
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
    parser.add_argument(
        "--base-date",
        default=os.environ.get("BASE_DATE"),
        help=(
            "調査対象期間の基準日(YYYY-MM-DD)。この日を終端とし、--window-days 日前までを"
            "対象とする (既定: 環境変数 BASE_DATE、未設定なら実行日)"
        ),
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("OOD_LOG_LEVEL"),
        help=(
            f"ログの出力レベル ({'/'.join(LOG_LEVELS)}) "
            f"(既定: 環境変数 OOD_LOG_LEVEL、未設定なら {DEFAULT_LOG_LEVEL})"
        ),
    )
    parser.add_argument("--max-turns", type=int, default=40)
    return parser


API_ERROR_HINTS = {
    "credit_balance_exhausted": (
        "OpenAI APIの残高が不足している。"
        "https://platform.openai.com/settings/organization/billing/ でクレジットを追加すること。"
    ),
    "insufficient_quota": (
        "OpenAI APIの利用可能枠を超えている。"
        "https://platform.openai.com/settings/organization/billing/ で残高と上限を確認すること。"
    ),
    "invalid_api_key": (
        "OPENAI_API_KEY が無効である。キーの値が正しいか、失効していないかを確認すること。"
    ),
    "model_not_found": (
        "指定したモデルが利用できない。モデル名の綴りと、"
        "そのモデルがアカウントで利用可能かを確認すること。--model で指定し直すこと。"
    ),
}


def describe_api_error(error: APIError) -> str:
    """OpenAI APIのエラーを、対処方法を含む日本語1行メッセージに変換する。

    [実装理由] Agent実行が失敗したときにスタックトレースをそのまま見せると、原因(残高不足、キーの
    誤り、モデル名の誤りなど)と対処方法が読み取れない。エラー種別ごとの対処方法をこの関数に集約し、
    呼び出し側はログ出力に専念できるようにしている。判別に例外クラスではなく `code` を使うのは、
    残高不足とレート制限超過がどちらも RateLimitError として送られてくるなど、クラスだけでは
    対処方法を分けられないためである。未知の `code` でもAPIからのメッセージは必ず提示し、
    情報を失わないようにする。

    Args:
        error: openai パッケージが送出した APIError(またはそのサブクラス)。

    Returns:
        原因と対処方法を含む日本語のメッセージ。
    """
    hint = API_ERROR_HINTS.get(error.code or "")
    if hint is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
        status_part = f"(HTTP {status}) " if status else ""
        return f"OpenAI APIの呼び出しに失敗した。{status_part}{error.message}"
    return f"{hint}\n(APIからの応答: {error.message})"


def main() -> int:
    """CLIエントリポイント。調査・記事再構成を実行し、ログ追記・レポート保存・結果表示までを行う。

    [実装理由] 引数解析からAgent実行・ログ追記・レポート保存までを1関数にまとめているのは、これらが
    「1回の実行」というひとまとまりの処理であり、run_at・log_path・report のような途中の値を下位関数
    間で受け渡すよりも、直線的な処理として読める方が全体の流れを把握しやすいためである。ファイルI/O
    やAgent構築など再利用性のある処理は個別関数に分離し、mainはその呼び出し順序の制御に専念する。ま
    た、調査対象期間は初回実行かどうかにかかわらず既定で30日固定とし、`--window-days`(または環境変数
    WINDOW_DAYS)を指定した場合のみ上書きするという挙動も、この関数内の設計判断として含まれる。
    ログ追記を記事再構成より先に行うのは、ログの内容が調査担当Agentの構造化出力だけで確定しており、
    再構成が失敗しても収集済みの調査結果を失わないようにするためである。Agent実行を try/except で
    囲んでいるのは、API側の失敗(残高不足、キーの誤り、モデル名の誤りなど)はCLI利用者が対処できる
    運用上のエラーであり、スタックトレースではなく対処方法を示すべきものだからである。進捗と完了
    報告をINFOで出しているのは、既定のWARNINGでは記事本文とエラーだけが残り、パイプで他のコマンドへ
    渡す用途を妨げないようにするためである(記事本文のみ標準出力、ログは標準エラー出力に出す)。
    調査対象期間の基準日(base_date)とファイル名・ログ見出しに使う実行日時(run_at)を別の値として
    保持しているのは、`--base-date` で過去を基準に調査したときも「いつ実行した分か」の記録は実行
    日時のままにしておくべきであり、同じ基準日で複数回実行してもレポートファイルが衝突しないように
    するためである。

    Returns:
        プロセス終了コード。正常終了は0、APIキー未設定時・基準日の書式不正時・API呼び出し失敗時は1。
    """
    args = build_parser().parse_args()

    setup_logging(args.log_level)

    if not os.environ.get("OPENAI_API_KEY"):
        logger.error(
            "環境変数 OPENAI_API_KEY が設定されていません。"
            "export OPENAI_API_KEY=sk-... を実行するか、.env ファイルに設定してください。"
        )
        return 1

    log_path = Path(args.log_path)
    run_at = datetime.now()
    try:
        base_date = resolve_base_date(args.base_date, run_at)
    except ValueError as e:
        logger.error("%s", e)
        return 1
    window_days = args.window_days if args.window_days is not None else DEFAULT_WINDOW_DAYS
    window_start = base_date - timedelta(days=window_days)
    existing_log = load_log(log_path)

    researcher = build_researcher_agent(model=args.model)

    user_input = render_template(
        "user_input.j2",
        base_date=base_date.isoformat(),
        window_start=window_start.isoformat(),
        window_days=window_days,
        existing_log=existing_log,
    )

    period = f"{window_start.isoformat()} 〜 {base_date.isoformat()}"
    logger.info("Open OnDemand の最新情報を調査中... (対象期間: %s)", period)

    try:
        result = Runner.run_sync(researcher, input=user_input, max_turns=args.max_turns)
    except APIError as e:
        logger.error("調査に失敗しました。%s", describe_api_error(e))
        return 1
    report: OODReport = result.final_output

    append_log(log_path, run_at, report.log_entries)

    if not report.log_entries:
        logger.info("新しい情報がないため、ニュースレター記事は作成しません")
        return 0

    logger.info("調査結果をニュースレター記事に再構成中...")
    writer = build_writer_agent(model=args.writer_model or args.model)
    try:
        article_markdown = compose_article(
            writer,
            report,
            base_date=base_date.isoformat(),
            window_start=window_start.isoformat(),
            window_days=window_days,
            max_turns=args.max_turns,
        )
    except APIError as e:
        logger.error(
            "記事の再構成に失敗しました。%s\n"
            "(調査結果は %s に追記済みです。再実行すると、追記済みの項目は"
            "「変更なし」と判定され再報告されない点に注意してください)",
            describe_api_error(e),
            log_path,
        )
        return 1

    report_path = write_report_file(Path(args.outdir), run_at, article_markdown)

    print(article_markdown)
    logger.info("ログファイル %s に %d 件を追記しました", log_path, len(report.log_entries))
    logger.info("レポートを %s に保存しました", report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
