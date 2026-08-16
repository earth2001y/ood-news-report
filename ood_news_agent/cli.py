#!/usr/bin/env python3
"""Open OnDemand の最新情報を収集し、日本語で報告するエージェント。

OpenAI Agents SDK (openai-agents) を使用し、WebSearchTool でWeb検索を行う。実行するたびに、
$LOGDIR 配下の調査ログ(調査回ごとの ood_research_log_YYYYMMDD_HHMM.json)と今回の調査結果を
突き合わせ、新規・更新のみを報告し、その回のログファイルを新たに書き出す。処理は2段構成で、
調査担当Agentの構造化出力(OODReport)を執筆担当Agentがニュースレター記事(OODArticle)へ
再構成する。記事本文は標準出力に加えて、$OUTDIR/report_YYYYMMDD_HHMM.md にも保存する。
ログに書き出すのは調査担当Agentの構造化出力(entries)であり、再構成の影響を受けない。

使い方:
    export OPENAI_API_KEY=sk-...
    python -m ood_news_agent

    # ログ保存先やモデル、レポート出力先を変える場合
    OUTDIR=./output LOGDIR=./logs python -m ood_news_agent --model gpt-5.4

    # 記事再構成だけ別のモデルで行う場合
    python -m ood_news_agent --writer-model gpt-5.4

    # 調査対象期間(日数)を変える場合
    python -m ood_news_agent --window-days 30

    # 調査担当Agentへ渡す過去の調査ログを直近5回分に制限する場合
    python -m ood_news_agent --max-log-runs 5
    MAX_LOG_RUNS=5 python -m ood_news_agent

    # 調査対象期間の基準日を指定する場合(既定は実行日)
    python -m ood_news_agent --base-date 2026-07-31
    BASE_DATE=2026-07-31 python -m ood_news_agent

    # 進捗を表示する場合(既定のログレベルは WARNING)
    python -m ood_news_agent --log-level INFO
    OOD_LOG_LEVEL=INFO python -m ood_news_agent

    # APIで調査・記事再構成を行い、結果を標準出力にだけ表示する場合
    python -m ood_news_agent --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from openai import APIError

from .news_models import CATEGORIES, OODReport, ReportItem
from .researcher import ResearchPeriod, run_researcher
from .writer import compose_article

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 30

DEFAULT_MAX_LOG_RUNS = 10

# 調査回ごとのログファイル名。実行日時を分単位で埋め込み、名前順が時系列順になるようにする。
LOG_FILE_PREFIX = "ood_research_log_"
LOG_FILE_SUFFIX = ".json"
LOG_FILE_TIMESTAMP_FORMAT = "%Y%m%d_%H%M"
LOG_FILE_GLOB = f"{LOG_FILE_PREFIX}*{LOG_FILE_SUFFIX}"

SLACK_TIMEOUT_SECONDS = 10

BASE_DATE_FORMAT = "%Y-%m-%d"

DEFAULT_LOG_LEVEL = "WARNING"

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def setup_logging(level_name: str | None = DEFAULT_LOG_LEVEL) -> int:
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
            "Invalid log level %r; using %s. Valid values: %s",
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
        raise ValueError(f"Could not parse base date {base_date!r}. Use YYYY-MM-DD format.") from e


def resolve_log_dir() -> Path:
    """調査ログの保存先ディレクトリを決定する。

    [実装理由] ログ保存先をCLI引数で変えられる仕組みは、運用が不安定になりやすく、同じ環境で
    実行される複数プロセスがログを混ぜてしまうリスクがある。環境変数 LOGDIR を使うことで、実行
    環境ごとに保存先を切り替えやすくし、デフォルト値 `.research_log` に統一することで簡潔な運用に
    している。
    ディレクトリが未作成でも自動で作るのは、ログの出力先が事前に存在しないことが多く、手動作成を
    必要とすると再実行のたびに失敗するためである。
    単一ファイルのパスではなくディレクトリを返すのは、調査ログを調査回ごとのファイルに分けて
    出力する設計に変えたためである。

    Returns:
        調査ログを格納するディレクトリ。ディレクトリは自動作成する。
    """
    log_dir = Path(os.environ.get("LOGDIR", ".research_log")).expanduser()
    if not log_dir.is_absolute():
        log_dir = Path.cwd() / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def resolve_max_log_runs(max_log_runs: int | None) -> int:
    """調査担当Agentへ渡す過去の調査回数の上限を決定する。

    [実装理由] 調査回ごとにログを分割すると実行を重ねるほどファイルが増え、全件を連結すると
    Agentへの入力が際限なく膨らんでプロンプト長の上限やコストを圧迫する。読み込む調査回数に上限を
    設けることで、入力量を運用側で抑えられるようにしている。0以下を「上限なし」として扱うのは、
    照合のために全履歴を渡したい運用を、別のフラグを増やさずに表現できるようにするためである。

    Args:
        max_log_runs: 読み込む調査回数の上限。Noneの場合は既定値を使う。

    Returns:
        読み込む調査回数の上限。0以下の場合は上限なしを意味する0を返す。
    """
    resolved = DEFAULT_MAX_LOG_RUNS if max_log_runs is None else max_log_runs
    return max(resolved, 0)


def log_file_path(log_dir: Path, run_at: datetime) -> Path:
    """今回の調査結果を書き出すログファイルのパスを組み立てる。

    [実装理由] ファイル名の規則(接頭辞とタイムスタンプ書式)を1か所に閉じ込め、書き出し側
    (append_log)と読み込み側(load_log の走査対象)で規則が食い違わないようにしている。分単位の
    タイムスタンプを使うのは、名前の辞書順が調査回の時系列順と一致し、新しい回を選ぶ処理で
    ファイルの内容を読まずに済むためである。

    Args:
        log_dir: 調査ログを格納するディレクトリ。
        run_at: 実行日時。ファイル名(YYYYMMDD_HHMM)に使う。

    Returns:
        今回の調査回に対応するログファイルのパス。
    """
    timestamp = run_at.strftime(LOG_FILE_TIMESTAMP_FORMAT)
    return log_dir / f"{LOG_FILE_PREFIX}{timestamp}{LOG_FILE_SUFFIX}"


def list_log_files(log_dir: Path, max_log_runs: int) -> list[Path]:
    """読み込む対象の調査ログファイルを、古い順に並べて返す。

    [実装理由] 上限を超える場合に新しい回を残すのは、既報告項目の照合で重要なのは直近の調査結果で
    あり、古い回から捨てても照合の実用性を保てるためである。返す並びは古い順に戻しており、Agentへ
    渡す入力が実際の時系列と同じ順序になるようにしている。ファイル名の辞書順で並べ替えるのは、
    タイムスタンプが固定長のゼロ埋め書式であり、名前順が時系列順と一致するためである。

    Args:
        log_dir: 調査ログを格納するディレクトリ。
        max_log_runs: 読み込む調査回数の上限。0以下の場合は上限を設けない。

    Returns:
        読み込む対象のログファイルのパス。古い順に並ぶ。存在しない場合は空リスト。
    """
    if not log_dir.is_dir():
        return []
    paths = sorted(path for path in log_dir.glob(LOG_FILE_GLOB) if path.is_file())
    if max_log_runs > 0 and len(paths) > max_log_runs:
        skipped = len(paths) - max_log_runs
        logger.info(
            "Found %d research logs; loading the newest %d and excluding %d older logs",
            len(paths),
            max_log_runs,
            skipped,
        )
        paths = paths[-max_log_runs:]
    return paths


def resolve_outdir() -> Path:
    """レポート出力ディレクトリを決定する。

    [実装理由] 出力先がCLIで変更可能だと、同一環境での再実行やスクリプト連携で意図しない
    保存先へ書き出してしまう。環境変数 OUTDIR のみで制御し、未設定時は .output へ落とすことで
    実行環境を簡潔に揃え、ディレクトリ未作成時は自動生成して失敗しないようにしている。

    Returns:
        レポートファイル保存先ディレクトリ。ディレクトリは自動作成する。
    """
    outdir = Path(os.environ.get("OUTDIR", "output")).expanduser()
    if not outdir.is_absolute():
        outdir = Path.cwd() / outdir
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def read_log_entries(log_path: Path) -> list[dict]:
    """調査回1件分のログファイルからentriesを取り出す。

    [実装理由] 1ファイルの読み込みとJSON解釈をここに閉じ込め、load_log 側は複数ファイルの結合だけを
    担うようにしている。空ファイルを項目なしとして扱うのは、書き込み途中や手動編集で内容が空になった
    ファイルが1つあるだけで調査全体を止めてしまうのを避けるためである。

    Args:
        log_path: 調査回1件分のログファイルのパス。

    Returns:
        ファイル内の `entries` のリスト。存在しない、または空の場合は空リスト。
    """
    if not log_path.exists():
        return []
    content = log_path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    record = json.loads(content)
    return list(record.get("entries", []))


def load_log(log_dir: Path, max_log_runs: int = 0) -> str:
    """調査回ごとのログファイルを結合し、entriesだけをフラットなMarkdownとして読み込む。

    [実装理由] 調査担当Agentが照合に必要とするのは過去の項目情報だけであり、調査日時や対象期間を
    入力に含めると項目比較のノイズになる。調査回ごとのファイルからentriesを連結し、カテゴリ別の
    Markdownへ変換することで、ログの保存形式とAgent入力形式を分離する。ログを1ファイルに追記せず
    調査回ごとに分けたうえで読み込み時に結合するのは、実行が並行しても互いのログを壊さず、古い回の
    ログを個別に退避・削除できるようにするためである。読み込む回数に上限を設けるのは、実行を
    重ねてもAgentへの入力が際限なく膨らまないようにするためである。

    Args:
        log_dir: 調査ログを格納するディレクトリ。
        max_log_runs: 読み込む調査回数の上限。0以下の場合は上限を設けない。

    Returns:
        過去のentriesをフラットにしたMarkdown。項目が1件もない場合は項目なしの文言。
    """
    entries = [
        entry for path in list_log_files(log_dir, max_log_runs) for entry in read_log_entries(path)
    ]
    if not entries:
        return "(報告済み項目はありません)"

    lines = []
    for category in CATEGORIES:
        category_entries = [entry for entry in entries if entry.get("category") == category]
        if not category_entries:
            continue
        lines.append(f"### {category}")
        for entry in category_entries:
            date_part = f" ({entry['item_date']})" if entry.get("item_date") else ""
            lines.append(
                f"- [{entry['status']}] {entry['title']}{date_part} - "
                f"{entry['summary']} - {entry['url']}"
            )
            if entry.get("change_note"):
                lines.append(f"  Change: {entry['change_note']}")
        lines.append("")
    return "\n".join(lines).strip()


def append_log(
    log_dir: Path,
    run_at: datetime,
    entries: list[ReportItem],
    window_start: str,
    base_date: str,
    window_days: int,
) -> Path | None:
    """今回「新規」「更新」と判定された項目を、この調査回のJSONログとして書き出す。

    [実装理由] LLMの出力(entries)をJSONへ変換してファイル書き込みを行う処理をPython側に置くことで、
    保存内容と形式を確定的に保証する。entriesが空(変更なし)の場合は、意味のない空の調査回ファイルを
    増やさないよう何も書き込まない。実行日時と調査対象期間を同じ記録に保存することで、項目がいつどの
    期間の調査で得られたかを機械的に追跡できるようにする。
    既存ファイルへ追記せず調査回ごとに新しいファイルを書き出すのは、読み込み・全体の再書き込みを
    伴う追記をやめることで、ログが肥大化しても書き込み量が一定に保たれ、途中で失敗しても過去の回の
    記録を壊さないためである。

    Args:
        log_dir: 調査ログを格納するディレクトリ。存在しない場合は作成する。
        run_at: 実行日時。ログファイル名(YYYYMMDD_HHMM)と記録の `datetime` に使う。
        entries: 今回「新規」または「更新」として報告した項目のリスト。
        window_start: 調査期間の開始日(YYYY-MM-DD)。
        base_date: 調査期間の終端日(YYYY-MM-DD)。
        window_days: 調査期間の日数。

    Returns:
        書き出したログファイルのパス。entriesが空で何も書き出さなかった場合はNone。
    """
    if not entries:
        return None
    record = {
        "datetime": run_at.isoformat(),
        "period": {"start": window_start, "end": base_date, "days": window_days},
        "entries": [entry.model_dump() for entry in entries],
    }
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_file_path(log_dir, run_at)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_report_file(outdir: Path, run_at: datetime, article_markdown: str) -> Path:
    """レポート本文を `report_<実行日時>.md` としてファイルに保存する。

    [実装理由] 標準出力だけでは実行環境によっては後から結果を追えないため、
    実行ごとに一意なファイル名(分単位のタイムスタンプ入り)で保存し、
    過去のレポートを上書きせず蓄積できるようにする。保存するのは執筆担当Agentが再構成した記事本文で
    あり、調査担当Agentの箇条書き報告文は保存しない。両方を残すとどちらが正なのか読み手が判断できず、
    調査ログ(ood_research_log_*.json)に構造化データが残っている以上、記事側は読み物として
    一本化する方が用途が明確になるためである。

    Args:
        outdir: 出力先ディレクトリ。存在しない場合は作成する。
        run_at: 実行日時。ファイル名(YYYYMMDD_HHMM)に使う。
        article_markdown: 保存する記事本文(Markdown)。

    Returns:
        書き込んだファイルのパス。
    """
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"report_{run_at.strftime('%Y%m%d_%H%M')}.md"
    path.write_text(article_markdown, encoding="utf-8")
    return path


def post_to_slack(webhook_url: str, article_markdown: str) -> None:
    """記事本文をSlack Incoming Webhookへ投稿する。

    [実装理由] Slack公式SDKを追加せず標準ライブラリでWebhookへ送信することで、CLIの依存関係を
    増やさず、既存のレポート生成処理から独立した単純な通知機能にしている。Slackは通常のMarkdown
    ではなくmrkdwnを解釈するため、送信前に記事をSlack向けの記法へ変換し、見出しや出典リンクを
    Slack上でも読みやすく表示する。

    Args:
        webhook_url: Slack Incoming WebhookのURL。
        article_markdown: Slackへ投稿する記事本文。

    Raises:
        HTTPError: Slack WebhookがHTTPエラーを返した場合。
        URLError: Slack Webhookへ接続できない場合。
    """
    slack_text = markdown_to_slack_mrkdwn(article_markdown)
    payload = json.dumps({"text": slack_text}, ensure_ascii=False).encode("utf-8")
    request = Request(
        webhook_url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urlopen(request, timeout=SLACK_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"Slack webhook returned HTTP {response.status}")


def markdown_to_slack_mrkdwn(markdown: str) -> str:
    """記事MarkdownをSlackのmrkdwn形式へ変換する。

    [実装理由] Slack Incoming Webhookは通常のMarkdownをレンダリングせず、独自のmrkdwn記法を使う。
    MarkdownリンクをSlackリンクへ変換し、見出しと箇条書きもSlackで意味が伝わる表現へ置き換える一方、
    URL以外の入力値はそのまま保持して記事の内容を変えないようにしている。

    Args:
        markdown: 変換前の記事Markdown。

    Returns:
        Slack mrkdwn形式の記事本文。
    """
    lines = []
    for line in markdown.splitlines():
        line = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", line)
        line = re.sub(r"^\s*[-*]\s+", "• ", line)
        line = re.sub(r"\[([^]]+)\]\(([^)]+)\)", r"<\2|\1>", line)
        line = re.sub(r"(?<!\s)`([^`\n]+)`", r" `\1`", line)
        line = re.sub(r"`([^`\n]+)`(?!\s)", r"`\1` ", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", line)
        lines.append(line)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """CLI引数を定義したArgumentParserを構築する。

    [実装理由] 引数の仕様をパース実行から分離することで、定義内容を単独で確認でき、CLI以外の
    呼び出し元でも同じパーサを再利用できるようにする。

    Returns:
        CLI引数が定義されたArgumentParser。
    """
    parser = argparse.ArgumentParser(description="Open OnDemand 最新情報収集エージェント")
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
        "--window-days",
        type=int,
        default=os.environ.get("WINDOW_DAYS"),
        help=f"調査対象期間(日数) (既定: 環境変数 WINDOW_DAYS、未設定なら{DEFAULT_WINDOW_DAYS}日)",
    )
    parser.add_argument(
        "--max-log-runs",
        type=int,
        default=os.environ.get("MAX_LOG_RUNS"),
        help=(
            "調査担当Agentへ渡す過去の調査ログの件数(調査回数)の上限。0以下で上限なし "
            f"(既定: 環境変数 MAX_LOG_RUNS、未設定なら{DEFAULT_MAX_LOG_RUNS}回)"
        ),
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="APIによる調査・記事再構成は行い、調査ログ保存・レポート保存・Slack投稿は行わない",
    )
    parser.add_argument("--max-turns", type=int, default=40)
    return parser


API_ERROR_HINTS = {
    "credit_balance_exhausted": (
        "The OpenAI API credit balance is depleted. Add credits at "
        "https://platform.openai.com/settings/organization/billing/."
    ),
    "insufficient_quota": (
        "The OpenAI API quota has been exceeded. Check the balance and usage limits at "
        "https://platform.openai.com/settings/organization/billing/."
    ),
    "invalid_api_key": (
        "OPENAI_API_KEY is invalid. Check that the key is correct and has not been revoked."
    ),
    "model_not_found": (
        "The requested model is unavailable. Check the model name and confirm that your account "
        "can access it, or specify another model with --model."
    ),
}


def describe_api_error(error: APIError) -> str:
    """OpenAI APIのエラーを、対処方法を含む英語メッセージに変換する。

    [実装理由] Agent実行が失敗したときにスタックトレースをそのまま見せると、原因(残高不足、キーの
    誤り、モデル名の誤りなど)と対処方法が読み取れない。エラー種別ごとの対処方法をこの関数に集約し、
    呼び出し側はログ出力に専念できるようにしている。判別に例外クラスではなく `code` を使うのは、
    残高不足とレート制限超過がどちらも RateLimitError として送られてくるなど、クラスだけでは
    対処方法を分けられないためである。未知の `code` でもAPIからのメッセージは必ず提示し、
    情報を失わないようにする。

    Args:
        error: openai パッケージが送出した APIError(またはそのサブクラス)。

    Returns:
        原因と対処方法を含む英語のメッセージ。
    """
    hint = API_ERROR_HINTS.get(error.code or "")
    if hint is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
        status_part = f"(HTTP {status}) " if status else ""
        return f"OpenAI API request failed. {status_part}{error.message}"
    return f"{hint}\n(API response: {error.message})"


def run_researcher_agent(
    model: str,
    existing_log: str,
    base_date: date,
    window_start: date,
    window_days: int,
    max_turns: int,
) -> OODReport | None:
    """調査担当Agentを実行し、結果を返す。

    [実装理由] main から API 呼び出しと入力構築を切り出すことで、調査の条件と失敗処理が
    別の関数で見通しよく保守できるようにしている。これにより main は制御フローに集中し、
    80 行を超えない長さを維持できる。

    Args:
        model: 調査担当Agentに使用するモデル名。
        existing_log: 過去に報告した項目のMarkdown。
        base_date: 調査対象期間の基準日。
        window_start: 調査対象期間の開始日。
        window_days: 調査対象期間の日数。
        max_turns: Agent実行の最大ターン数。
    """
    period = f"{window_start.isoformat()} to {base_date.isoformat()}"
    logger.info("Researching the latest Open OnDemand news... (period: %s)", period)
    try:
        return run_researcher(
            model=model,
            existing_log=existing_log,
            period=ResearchPeriod(
                base_date=base_date.isoformat(),
                window_start=window_start.isoformat(),
                window_days=window_days,
            ),
            max_turns=max_turns,
        )
    except APIError as e:
        logger.error("Research failed. %s", describe_api_error(e))
        return None


def persist_report(article_markdown: str, outdir: Path, run_at: datetime) -> Path | None:
    """記事をファイルへ保存し、設定があればSlackへ通知する。

    [実装理由] 永続化処理を独立した関数に切り出して、finalize_report の分岐を浅く保つ。
    Slack 連携の失敗もこの関数で吸収し、上位の関数は「保存できたかどうか」の判定だけを知れば
    よいようにしている。
    """
    path = write_report_file(outdir, run_at, article_markdown)
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return path

    logger.info("Posting report to Slack...")
    try:
        post_to_slack(webhook_url, article_markdown)
    except (HTTPError, URLError, RuntimeError, TimeoutError) as e:
        logger.error("Failed to post report to Slack: %s", e)
        return None
    return path


def run_writer_agent(report: OODReport, log_path: Path, model: str, max_turns: int) -> str | None:
    """調査結果を執筆担当Agentで記事へ再構成する。

    [実装理由] 執筆担当Agentの作成・実行と、ファイル保存・Slack投稿を分離することで、
    Agent実行の失敗と副作用を伴う永続化処理を独立して扱えるようにしている。

    Args:
        report: 調査担当Agentの構造化出力。
        log_path: 調査結果を保存したログファイルのパス。
        model: 執筆担当Agentに使用するモデル名。
        max_turns: Agent実行の最大ターン数。
    """
    logger.info("Composing a newsletter article from the research results...")
    try:
        article_markdown = compose_article(model=model, report=report, max_turns=max_turns)
    except APIError as e:
        logger.error(
            "Article composition failed. %s\n"
            "(The research results have already been saved to %s. On rerun, saved items may be "
            "classified as unchanged and omitted.)",
            describe_api_error(e),
            log_path,
        )
        return None
    return article_markdown


def finalize_report(
    args: argparse.Namespace,
    report: OODReport,
    log_path: Path,
    run_at: datetime,
    article_markdown: str,
) -> tuple[str, Path | None] | None:
    """記事本文を保存し、設定があればSlackへ投稿する。

    [実装理由] Agent実行を終えた記事本文だけを受け取ることで、結果の生成と永続化の責務を
    分離し、ドライラン時に副作用を確実に抑止できるようにしている。
    """

    if args.dry_run:
        print(article_markdown)
        logger.info("Dry run: skipping research log, report, and Slack delivery")
        return article_markdown, None

    path = persist_report(article_markdown, resolve_outdir(), run_at)
    if path is None:
        return None

    print(article_markdown)
    logger.info("Saved %d entries to research log %s", len(report.entries), log_path)
    logger.info("Saved report to %s", path)
    return article_markdown, path


def main() -> int:
    """CLIエントリポイント。調査・記事再構成を実行し、必要に応じて結果を永続化する。

    [実装理由] 実行順序の制御だけをこの関数に残し、各処理の詳細はヘルパー関数に分離している。
    これにより、CLI の入口としての責務が明確になり、各処理の単体テストや保守がしやすくなる。

    Returns:
        プロセス終了コード。正常終了は0、APIキー未設定時・基準日の書式不正時・API呼び出し失敗時は1。
    """
    args = build_parser().parse_args()
    setup_logging(args.log_level)

    if not os.environ.get("OPENAI_API_KEY"):
        logger.error(
            "OPENAI_API_KEY is not set. Run export OPENAI_API_KEY=sk-... or add it to .env."
        )
        return 1

    log_dir = resolve_log_dir()
    run_at = datetime.now()
    try:
        base_date = resolve_base_date(args.base_date, run_at)
    except ValueError as e:
        logger.error("%s", e)
        return 1

    window_days = args.window_days if args.window_days is not None else DEFAULT_WINDOW_DAYS
    window_start = base_date - timedelta(days=window_days)
    existing_log = load_log(log_dir, resolve_max_log_runs(args.max_log_runs))
    report = run_researcher_agent(
        args.model, existing_log, base_date, window_start, window_days, args.max_turns
    )
    if report is None:
        return 1

    log_path = None
    if not args.dry_run:
        log_path = append_log(
            log_dir,
            run_at,
            report.entries,
            window_start.isoformat(),
            base_date.isoformat(),
            window_days,
        )

    if not report.entries:
        logger.info("No new information found; skipping newsletter article generation")
        return 0

    writer_model = args.writer_model or args.model
    article_markdown = run_writer_agent(report, log_path or log_dir, writer_model, args.max_turns)
    if article_markdown is None:
        return 1

    result = finalize_report(args, report, log_path or log_dir, run_at, article_markdown)
    if result is None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
