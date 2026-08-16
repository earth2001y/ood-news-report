"""調査担当と執筆担当の間で受け渡すニュース項目のデータモデルを定義する。"""

from typing import Literal

from pydantic import BaseModel, Field

# カテゴリと状態は、Agentの構造化出力・ログの照合キーであるため英語の識別子で持つ。
# 調査結果は執筆担当Agentへ渡すまで英語で一貫させ、日本語化は執筆担当Agentに任せる。
CATEGORIES = ["new_release", "roadmap", "security", "community_event", "other_topic"]

STATUSES = ["new", "updated"]


class ReportItem(BaseModel):
    category: Literal["new_release", "roadmap", "security", "community_event", "other_topic"] = (
        Field(description="One of the five categories")
    )
    status: Literal["new", "updated"] = Field(
        description='"new" for items absent from the log, "updated" for reported items that '
        "changed. Omit unchanged items entirely."
    )
    title: str = Field(description="Item title (version name, CVE ID, event name, etc.)")
    item_date: str = Field(
        description="Publication or update date in YYYY-MM-DD format. Empty string if unknown."
    )
    url: str = Field(description="URL of the information source")
    summary: str = Field(description="Concise summary in English")
    change_note: str = Field(
        default="",
        description=(
            'When status is "updated", state in English what changed and how. '
            "Empty string for new items."
        ),
    )


class OODReport(BaseModel):
    entries: list[ReportItem] = Field(
        description='Only the items reported as "new" or "updated" this run '
        "(exclude unchanged items)"
    )
