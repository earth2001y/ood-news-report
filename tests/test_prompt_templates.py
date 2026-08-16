"""prompt_templates.py が読み込むAgent用テンプレートを検証する。"""

import json

from ood_news_agent.news_models import CATEGORIES
from ood_news_agent.prompt_templates import render_template
from ood_news_agent.writer import CATEGORY_DESCRIPTIONS
from tests.factories import make_entry


class TestRenderTemplate:
    def test_instructions_contains_all_categories(self):
        # 対象: render_template("researcher_instructions.j2")
        # パターン: 全カテゴリのスキーマ値が指示文に含まれる
        rendered = render_template("researcher_instructions.j2")
        for category in CATEGORIES:
            assert category in rendered

    def test_instructions_specifies_english_status_values(self):
        # 対象: render_template("researcher_instructions.j2")
        # パターン: statusに設定する英語の識別子が指示文に明示される
        rendered = render_template("researcher_instructions.j2")
        assert 'status="new"' in rendered
        assert 'status="updated"' in rendered

    def test_researcher_instructions_uses_structured_entries_only(self):
        # 対象: render_template("researcher_instructions.j2")
        # パターン: 調査担当の出力形式がentriesだけを要求する
        rendered = render_template("researcher_instructions.j2")
        assert "【出力形式(entries)】" in rendered
        assert "report_markdown" not in rendered

    def test_report_markdown_renders_entries_and_unchanged_categories(self):
        # 対象: render_template("report_markdown.j2")
        # パターン: entriesから項目を分類し、空カテゴリは"No changes"とする
        rendered = render_template(
            "report_markdown.j2",
            categories=CATEGORIES,
            entries=[make_entry(status="updated", change_note="Severity raised to Critical.")],
        )
        assert "## new_release" in rendered
        assert "- [updated] v3.1.0 (2026-08-01) - Adds new features." in rendered
        assert "Change: Severity raised to Critical." in rendered
        assert "## roadmap" in rendered
        assert rendered.count("No changes") == len(CATEGORIES) - 1

    def test_report_markdown_contains_no_japanese(self):
        # 対象: render_template("report_markdown.j2")
        # パターン: 調査結果の報告文に日本語を含めない
        rendered = render_template(
            "report_markdown.j2",
            categories=CATEGORIES,
            entries=[make_entry(status="updated", change_note="CVSS raised to 9.1")],
        )
        assert rendered.isascii()

    def test_writer_instructions_lists_categories_in_order(self):
        # 対象: render_template("writer_instructions.j2")
        # パターン: categoriesを渡すと全カテゴリがCATEGORIESの順に番号付きで並ぶ
        rendered = render_template(
            "writer_instructions.j2",
            categories=CATEGORIES,
            category_descriptions=CATEGORY_DESCRIPTIONS,
        )
        positions = [rendered.index(f"`{category}`") for category in CATEGORIES]
        assert positions == sorted(positions)
        first_category = CATEGORIES[0]
        assert f"1. {CATEGORY_DESCRIPTIONS[first_category]} (`{first_category}`)" in rendered

    def test_writer_instructions_forbids_bracket_labels_and_allows_search(self):
        # 対象: render_template("writer_instructions.j2")
        # パターン: 角括弧ラベルを禁止し、事実の補足検索を許可する
        rendered = render_template(
            "writer_instructions.j2",
            categories=CATEGORIES,
            category_descriptions=CATEGORY_DESCRIPTIONS,
        )
        assert "角括弧ラベルは使わない" in rendered
        assert "補足情報獲得のためのWeb検索はしてよい" in rendered
        assert "事実の追加・推測・脚色は一切しない" in rendered

    def test_writer_instructions_constrains_other_topic_title_and_relations(self):
        # 対象: render_template("writer_instructions.j2")
        # パターン: other_topicのみの場合の見出し制約と、項目間の関連への言及を指示する
        rendered = render_template(
            "writer_instructions.j2",
            categories=CATEGORIES,
            category_descriptions=CATEGORY_DESCRIPTIONS,
        )
        assert "更新カテゴリが other_topic だけの場合" in rendered
        assert "各記事の間に関連がある場合" in rendered

    def test_writer_instructions_lists_only_target_categories(self):
        # 対象: render_template("writer_instructions.j2")
        # パターン: 執筆対象として渡したカテゴリだけが指示文に含まれる
        target = [CATEGORIES[0], CATEGORIES[3]]
        rendered = render_template(
            "writer_instructions.j2", categories=target, category_descriptions=CATEGORY_DESCRIPTIONS
        )
        assert f"1. {CATEGORY_DESCRIPTIONS['new_release']} (`new_release`)" in rendered
        community_description = CATEGORY_DESCRIPTIONS["community_event"]
        assert f"2. {community_description} (`community_event`)" in rendered
        assert "`roadmap`" not in rendered
        assert "`security`" not in rendered

    def test_writer_input_embeds_entries_and_report(self):
        # 対象: render_template("writer_input.j2")
        # パターン: 調査レポート本文には期間表記を入れず、各項目と報告文のみが埋め込まれる
        rendered = render_template(
            "writer_input.j2",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            entries=[make_entry(status="updated", change_note="Severity raised to Critical.")],
        )
        assert "調査対象期間:" not in rendered
        assert "2026-07-14 〜 2026-08-13" not in rendered
        assert "v3.1.0" in rendered
        assert "https://example.com/v3.1.0" in rendered
        assert "Severity raised to Critical." in rendered

    def test_writer_input_passes_research_result_in_english(self):
        # 対象: render_template("writer_input.j2")
        # パターン: 調査結果のカテゴリ・更新区分を英語の識別子のまま渡す
        rendered = render_template(
            "writer_input.j2",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            entries=[make_entry(category="security", status="updated", change_note="CVSS 9.1")],
        )
        assert "Category: security" in rendered
        assert "Status: updated" in rendered
        assert "セキュリティ脆弱性情報" not in rendered
        assert "更新" not in rendered

    def test_writer_input_marks_empty_entries(self):
        # 対象: render_template("writer_input.j2")
        # パターン: entriesが空の場合、新規・更新なしを示す文言が入る
        rendered = render_template(
            "writer_input.j2",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            entries=[],
        )
        assert "(No new or updated items in this period)" in rendered

    def test_writer_input_marks_unknown_item_date(self):
        # 対象: render_template("writer_input.j2")
        # パターン: item_dateが空文字の場合、日付が不明であることを明示する
        rendered = render_template(
            "writer_input.j2",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            entries=[make_entry(item_date="")],
        )
        assert "Date: (unknown)" in rendered

    def test_user_input_embeds_context_variables(self):
        # 対象: render_template("researcher_input.j2")
        # パターン: base_date/window_start/window_days/existing_logが本文に埋め込まれる
        rendered = render_template(
            "researcher_input.j2",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            existing_log="(まだ記録はありません。今回が初回実行です)",
        )
        assert "調査の基準日: 2026-08-13" in rendered
        assert "2026-07-14 〜 2026-08-13" in rendered
        assert "30日間" in rendered
        assert "(まだ記録はありません。今回が初回実行です)" in rendered

    def test_user_input_excludes_items_after_base_date(self):
        # 対象: render_template("researcher_input.j2")
        # パターン: 基準日より後の情報を対象外とする指示が含まれる
        rendered = render_template(
            "researcher_input.j2",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            existing_log="(初回実行)",
        )
        assert "基準日より後に公開・更新された情報" in rendered
        assert "報告に含めない" in rendered

    def test_researcher_input_lists_flat_entries_without_log_metadata(self):
        # 対象: render_template("researcher_input.j2")
        # パターン: 前回ログのentriesだけを調査回の区切りなしで埋め込む
        rendered = render_template(
            "researcher_input.j2",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            existing_log=json.dumps(
                [{"title": "v3.1.0"}, {"title": "CVE-2026-0001"}], ensure_ascii=False
            ),
        )
        assert '"title": "v3.1.0"' in rendered
        assert '"title": "CVE-2026-0001"' in rendered
        assert "datetime" not in rendered
        assert "period" not in rendered
