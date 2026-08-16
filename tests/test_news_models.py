"""news_models.py のデータモデルと識別子を検証する。"""

from typing import get_args

import ood_news_agent.news_models as news_models
from ood_news_agent.news_models import ReportItem
from tests.factories import make_entry


class TestReportItemCategory:
    def test_literal_matches_categories(self):
        # 対象: ReportItem.category
        # パターン: 許容値がCATEGORIESと順序を含めて一致する
        allowed = get_args(ReportItem.model_fields["category"].annotation)
        assert list(allowed) == news_models.CATEGORIES

    def test_accepts_other_topics(self):
        # 対象: ReportItem.category
        # パターン: 追加カテゴリ「その他のトピック」の項目を構築できる
        entry = make_entry(category="other_topic")
        assert entry.category == "other_topic"

    def test_status_literal_matches_statuses(self):
        # 対象: ReportItem.status
        # パターン: 許容値がSTATUSESと順序を含めて一致する
        allowed = get_args(ReportItem.model_fields["status"].annotation)
        assert list(allowed) == news_models.STATUSES
