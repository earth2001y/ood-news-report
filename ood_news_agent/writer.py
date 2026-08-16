"""構造化された Open OnDemand の調査結果を日本語の記事へ再構成する。"""

from agents import Agent, Runner, WebSearchTool
from pydantic import BaseModel, Field

from .news_models import CATEGORIES, OODReport
from .prompt_templates import render_template

# 識別子だけでは意図が伝わらないため、執筆担当Agentへの指示文で各カテゴリの内容を
# 英語で説明する。見出しの日本語表現は執筆担当Agentが決める。
CATEGORY_DESCRIPTIONS = {
    "new_release": "New version releases",
    "roadmap": "Development roadmap updates and announcements",
    "security": "Security vulnerabilities",
    "community_event": "Community events",
    "other_topic": "Other topics",
}


class OODArticle(BaseModel):
    article_markdown: str = Field(
        description="調査結果を再構成した、日本語のニュースレター記事本文(Markdown)"
    )


def build_writer_agent(model: str, categories: list[str] | None = None) -> Agent:
    """調査結果をニュースレター記事へ再構成するAgentを構築する。

    [実装理由] 調査と執筆を別のAgentにすることで、事実収集と文章構成の判断を分離する。
    英語の調査結果から日本語記事への翻訳もこのAgentの責務とし、カテゴリの識別子と説明だけを
    渡すことで、用語と文体の決定を執筆担当に一元化している。

    Args:
        model: 使用するモデル名。WebSearchTool対応モデルを指定する。
        categories: 記事に含めるカテゴリ。Noneの場合は全カテゴリを対象にする。

    Returns:
        執筆用の指示文・Web検索ツール・出力スキーマを設定したAgent。
    """
    target_categories = categories if categories is not None else CATEGORIES
    instructions = render_template(
        "writer_instructions.j2",
        categories=target_categories,
        category_descriptions=CATEGORY_DESCRIPTIONS,
    )
    return Agent(
        name="OOD News Writer",
        instructions=instructions,
        model=model,
        tools=[WebSearchTool(search_context_size="medium")],
        output_type=OODArticle,
    )


def build_writer_prompt(report: OODReport) -> str:
    """構造化された調査結果から執筆担当Agentへの入力を組み立てる。

    [実装理由] 構造化項目とカテゴリ別Markdownの両方を執筆担当へ渡す処理をこのモジュールに
    閉じ込め、記事の入力形式をCLIやログ保存処理から独立して変更できるようにしている。

    Args:
        report: 調査担当Agentの構造化出力。

    Returns:
        レンダリング済みの記事執筆入力プロンプト。
    """
    return render_template(
        "writer_input.j2",
        entries=report.entries,
        report_markdown=render_template(
            "report_markdown.j2", categories=CATEGORIES, entries=report.entries
        ),
    )


def compose_article(model: str, report: OODReport, max_turns: int) -> str:
    """調査結果を執筆担当Agentで日本語の記事へ再構成する。

    [実装理由] Agentの構築、入力生成、SDKの実行を執筆担当モジュールで完結させることで、
    CLIから記事生成の実装詳細を切り離す。実際に項目があるカテゴリだけを指示へ渡し、空の
    セクションを生成しにくくしている。API例外は用途ごとに処理できるよう呼び出し側へ伝播させる。

    Args:
        model: 使用するモデル名。
        report: 調査担当Agentの構造化出力。
        max_turns: Agent実行の最大ターン数。

    Returns:
        再構成された日本語の記事本文(Markdown)。
    """
    categories = [
        category
        for category in CATEGORIES
        if any(entry.category == category for entry in report.entries)
    ]
    agent = build_writer_agent(model, categories)
    prompt = build_writer_prompt(report)
    result = Runner.run_sync(agent, input=prompt, max_turns=max_turns)
    article: OODArticle = result.final_output
    return article.article_markdown
