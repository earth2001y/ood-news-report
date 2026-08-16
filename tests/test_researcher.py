"""researcher.py の調査担当Agentを検証する。"""

import ood_news_agent.researcher as researcher
from ood_news_agent.news_models import OODReport
from tests.factories import make_entry


class TestBuildResearcherAgent:
    def test_sets_model_instructions_and_output_type(self):
        # 対象: build_researcher_agent
        # パターン: 指定したmodel・instructions・output_type・toolsが設定される
        agent = researcher.build_researcher_agent(model="gpt-5.4")
        assert agent.model == "gpt-5.4"
        assert agent.output_type is OODReport
        assert "Open OnDemand" in agent.instructions
        assert len(agent.tools) == 1


class TestRunResearcher:
    def test_builds_prompt_and_returns_structured_output(self, monkeypatch):
        # 対象: researcher.run_researcher
        # パターン: 調査条件を入力へ埋め込み、Agentの構造化出力を返す
        captured = {}
        expected = OODReport(entries=[make_entry()])

        def _run_sync(agent, input, max_turns):
            captured["model"] = agent.model
            captured["input"] = input
            captured["max_turns"] = max_turns
            return type("_Result", (), {"final_output": expected})

        monkeypatch.setattr(researcher.Runner, "run_sync", _run_sync)

        report = researcher.run_researcher(
            model="gpt-test",
            existing_log="### new_release\n- v3.0.0",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            max_turns=12,
        )

        assert report is expected
        assert captured["model"] == "gpt-test"
        assert "2026-07-14 〜 2026-08-13" in captured["input"]
        assert "v3.0.0" in captured["input"]
        assert captured["max_turns"] == 12
