"""複数のテストモジュールで共有するテストデータを生成する。"""

from ood_news_agent.news_models import ReportItem


def make_entry(**overrides) -> ReportItem:
    """既定値を持つ調査項目を生成する。

    [実装理由] Agent・テンプレート・CLIの各テストで同じ入力項目を使い、モジュール間で
    テストデータの既定値が食い違わないようにする。

    Args:
        **overrides: 既定値から上書きするフィールド。

    Returns:
        テスト用の調査項目。
    """
    values = {
        "category": "new_release",
        "status": "new",
        "title": "v3.1.0",
        "item_date": "2026-08-01",
        "url": "https://example.com/v3.1.0",
        "summary": "Adds new features.",
        "change_note": "",
    }
    values.update(overrides)
    return ReportItem(**values)
