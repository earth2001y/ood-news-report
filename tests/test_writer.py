"""app.writer の執筆担当Agentを検証する。"""

import app.writer as writer
from app.news_models import CATEGORIES, OODReport
from app.writer import OODArticle
from tests.factories import make_entry


class TestCategoryDescriptions:
    def test_covers_all_categories(self):
        # 対象: CATEGORY_DESCRIPTIONS
        # パターン: 全カテゴリキーに英語の説明が定義され、順序もCATEGORIESと一致する
        assert list(writer.CATEGORY_DESCRIPTIONS) == CATEGORIES

    def test_descriptions_are_english(self):
        # 対象: CATEGORY_DESCRIPTIONS
        # パターン: 説明に日本語を含まず、執筆担当への入力が英語で統一される
        joined = "".join(writer.CATEGORY_DESCRIPTIONS.values())
        assert joined.isascii()


class TestBuildWriterAgent:
    def test_sets_model_output_type_and_web_search_tool(self):
        # 対象: build_writer_agent
        # パターン: 出力スキーマがOODArticleで、Web検索ツールを1つ持つ
        agent = writer.build_writer_agent("gpt-test")
        assert agent.model == "gpt-test"
        assert agent.output_type is OODArticle
        assert len(agent.tools) == 1
        assert "ニュースレター記事" in agent.instructions
        assert "執筆するライター" in agent.instructions


class TestWriteArticle:
    def test_returns_article_markdown_from_agent_output(self, monkeypatch):
        # 対象: write_article
        # パターン: 執筆担当Agentの出力からarticle_markdownを取り出して返す
        class _FakeResult:
            final_output = OODArticle(article_markdown="# 記事本文")

        monkeypatch.setattr(
            writer.Runner, "run_sync", lambda agent, input, max_turns: _FakeResult()
        )
        report = OODReport(entries=[make_entry()])

        article = writer.write_article("gpt-test", report, 12)

        assert article == "# 記事本文"

    def test_passes_entries_and_report_to_agent(self, monkeypatch):
        # 対象: write_article
        # パターン: 構造化項目から生成した報告文が入力に含まれる
        captured = {}

        class _FakeResult:
            final_output = OODArticle(article_markdown="# 記事本文")

        def _fake_run_sync(agent, input, max_turns):
            captured["input"] = input
            captured["max_turns"] = max_turns
            return _FakeResult()

        monkeypatch.setattr(writer.Runner, "run_sync", _fake_run_sync)
        report = OODReport(entries=[make_entry()])

        writer.write_article("gpt-test", report, 12)

        assert "v3.1.0" in captured["input"]
        assert "## new_release" in captured["input"]
        assert captured["max_turns"] == 12

    def test_builds_instructions_for_categories_present_in_report(self, monkeypatch):
        # 対象: writer.write_article
        # パターン: 調査結果に項目があるカテゴリだけを執筆対象として指示する
        captured = {}

        class _FakeResult:
            final_output = OODArticle(article_markdown="# 記事本文")

        def _fake_run_sync(agent, input, max_turns):
            captured["instructions"] = agent.instructions
            return _FakeResult()

        monkeypatch.setattr(writer.Runner, "run_sync", _fake_run_sync)
        report = OODReport(entries=[make_entry(category="community_event")])

        writer.write_article("gpt-test", report, 12)

        instructions = captured["instructions"]
        assert "1. Community events (`community_event`)" in instructions
        assert "New version releases (`new_release`)" not in instructions

    def test_passes_category_and_status_to_writer_in_english(self, monkeypatch):
        # 対象: write_article
        # パターン: カテゴリ・更新区分を日本語化せず、英語の識別子のまま執筆担当へ渡す
        captured = {}

        class _FakeResult:
            final_output = OODArticle(article_markdown="# 記事本文")

        def _fake_run_sync(agent, input, max_turns):
            captured["input"] = input
            return _FakeResult()

        monkeypatch.setattr(writer.Runner, "run_sync", _fake_run_sync)
        report = OODReport(
            entries=[
                make_entry(category="security", status="updated", change_note="CVSS raised to 9.1")
            ]
        )

        writer.write_article("gpt-test", report, 12)

        assert "Category: security" in captured["input"]
        assert "Status: updated" in captured["input"]
        assert "## security" in captured["input"]
        assert "セキュリティ脆弱性情報" not in captured["input"]
