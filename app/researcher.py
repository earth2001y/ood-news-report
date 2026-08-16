"""Open OnDemand の最新情報を検索し、構造化された調査結果を生成する。"""

from typing import TypedDict

from agents import Agent, Runner, WebSearchTool

from .news_models import OODReport
from .prompt_templates import render_template


class ResearchPeriod(TypedDict):
    """調査対象期間をテンプレートへ渡すための値。"""

    base_date: str
    window_start: str
    window_days: int


def build_researcher_agent(model: str) -> Agent:
    """Open OnDemand調査用のAgentを構築する。

    [実装理由] Web検索と構造化出力の設定を調査担当モジュールに閉じ込め、CLIから
    OpenAI Agents SDK固有の構築手順を切り離す。ログ保存用データだけを出力させることで、
    後続処理が型の決まった調査結果を扱えるようにしている。

    Args:
        model: 使用するモデル名。WebSearchTool対応モデルを指定する。

    Returns:
        調査用の指示文・Web検索ツール・出力スキーマを設定したAgent。
    """
    instructions = render_template("researcher_instructions.j2")
    return Agent(
        name="OOD News Reporter",
        instructions=instructions,
        model=model,
        tools=[WebSearchTool(search_context_size="medium")],
        output_type=OODReport,
    )


def build_researcher_prompt(existing_log: str, period: ResearchPeriod) -> str:
    """調査条件と過去ログから調査担当Agentへの入力を組み立てる。

    [実装理由] 調査固有の入力項目をこのモジュールに集約し、CLIがテンプレートの詳細を
    知らなくても調査を実行できるようにしている。日付を文字列で受け取ることで、期間計算と
    表示形式の決定は呼び出し側の責務として保つ。

    Args:
        existing_log: 過去に報告した項目のMarkdown。
        period: 調査対象期間の基準日・開始日・日数。

    Returns:
        レンダリング済みの調査入力プロンプト。
    """
    return render_template("researcher_input.j2", **period, existing_log=existing_log)


def run_researcher(
    model: str, existing_log: str, period: ResearchPeriod, max_turns: int
) -> OODReport:
    """調査担当Agentを構築・実行し、構造化された調査結果を返す。

    [実装理由] Agentの構築、入力生成、SDKの実行を調査担当モジュールで完結させることで、
    CLIは期間の決定やエラー表示などの制御フローに集中できる。API例外は呼び出し側に伝播させ、
    CLI以外の利用者も用途に合った失敗処理を選べるようにしている。

    Args:
        model: 使用するモデル名。
        existing_log: 過去に報告した項目のMarkdown。
        period: 調査対象期間の基準日・開始日・日数。
        max_turns: Agent実行の最大ターン数。

    Returns:
        新規または更新された項目だけを含む調査結果。
    """
    agent = build_researcher_agent(model)
    prompt = build_researcher_prompt(existing_log, period)
    result = Runner.run_sync(agent, input=prompt, max_turns=max_turns)
    report: OODReport = result.final_output
    return report
