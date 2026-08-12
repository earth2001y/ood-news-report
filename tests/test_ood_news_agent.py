"""ood_news_agent.py の各関数に対するユニットテスト。"""

from __future__ import annotations

import sys
from datetime import datetime

import ood_news_agent as ood
from ood_news_agent import OODReport, ReportItem


def _make_entry(**overrides):
    defaults = dict(
        category="新バージョンのリリース情報",
        status="新規",
        title="v3.1.0",
        item_date="2026-08-01",
        url="https://example.com/v3.1.0",
        summary="新機能が追加された",
        change_note="",
    )
    defaults.update(overrides)
    return ReportItem(**defaults)


class TestRenderTemplate:
    def test_instructions_contains_all_categories(self):
        # 対象: render_template("instructions.j2")
        # パターン: 4カテゴリ名すべてが指示文に含まれる
        rendered = ood.render_template("instructions.j2")
        for category in ood.CATEGORIES:
            assert category in rendered

    def test_user_input_embeds_context_variables(self):
        # 対象: render_template("user_input.j2")
        # パターン: today/window_start/window_days/existing_logが本文に埋め込まれる
        rendered = ood.render_template(
            "user_input.j2",
            today="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            existing_log="(まだ記録はありません。今回が初回実行です)",
        )
        assert "2026-08-13" in rendered
        assert "2026-07-14" in rendered
        assert "30" in rendered
        assert "(まだ記録はありません。今回が初回実行です)" in rendered


class TestLoadLog:
    def test_missing_file_returns_placeholder(self, tmp_path):
        # 対象: load_log
        # パターン: ログファイルが存在しない場合、初回実行を示す文言を返す
        log_path = tmp_path / "ood_report_log.md"
        assert ood.load_log(log_path) == "(ログファイルが存在しません。今回が初回実行です)"

    def test_empty_file_returns_placeholder(self, tmp_path):
        # 対象: load_log
        # パターン: ログファイルが空白のみの場合、初回実行を示す文言を返す
        log_path = tmp_path / "ood_report_log.md"
        log_path.write_text("   \n", encoding="utf-8")
        assert ood.load_log(log_path) == "(まだ記録はありません。今回が初回実行です)"

    def test_existing_content_is_stripped(self, tmp_path):
        # 対象: load_log
        # パターン: 既存の記録がある場合、前後の空白を除いた本文を返す
        log_path = tmp_path / "ood_report_log.md"
        log_path.write_text("\n# ログ\n内容\n\n", encoding="utf-8")
        assert ood.load_log(log_path) == "# ログ\n内容"


class TestAppendLog:
    def test_no_entries_does_not_create_file(self, tmp_path):
        # 対象: append_log
        # パターン: entriesが空の場合、ファイルを作成しない
        log_path = tmp_path / "ood_report_log.md"
        ood.append_log(log_path, datetime(2026, 8, 13, 9, 30), [])
        assert not log_path.exists()

    def test_creates_file_with_header_when_absent(self, tmp_path):
        # 対象: append_log
        # パターン: ログファイルが存在しない場合、見出し付きで新規作成する
        log_path = tmp_path / "ood_report_log.md"
        ood.append_log(log_path, datetime(2026, 8, 13, 9, 30), [_make_entry()])
        text = log_path.read_text(encoding="utf-8")
        assert text.startswith("# Open OnDemand 情報収集 報告ログ\n")
        assert "## 2026-08-13 09:30 実行分" in text
        assert "### 新バージョンのリリース情報" in text
        assert (
            "- [新規] v3.1.0 (2026-08-01) - 新機能が追加された - https://example.com/v3.1.0" in text
        )

    def test_appends_without_duplicating_header(self, tmp_path):
        # 対象: append_log
        # パターン: ログファイルが既存の場合、見出しを重複させず追記する
        log_path = tmp_path / "ood_report_log.md"
        log_path.write_text("# Open OnDemand 情報収集 報告ログ\n", encoding="utf-8")
        ood.append_log(log_path, datetime(2026, 8, 13, 10, 0), [_make_entry(item_date="")])
        text = log_path.read_text(encoding="utf-8")
        assert text.count("# Open OnDemand 情報収集 報告ログ") == 1
        assert "- [新規] v3.1.0 - 新機能が追加された - https://example.com/v3.1.0" in text

    def test_groups_entries_by_category_order(self, tmp_path):
        # 対象: append_log
        # パターン: entriesの順序に関わらず、CATEGORIESの順で出力される
        log_path = tmp_path / "ood_report_log.md"
        entries = [
            _make_entry(category="コミュニティイベント", title="GOOD Conference 2026"),
            _make_entry(category="新バージョンのリリース情報", title="v3.1.0"),
        ]
        ood.append_log(log_path, datetime(2026, 8, 13, 9, 30), entries)
        text = log_path.read_text(encoding="utf-8")
        assert text.index("新バージョンのリリース情報") < text.index("コミュニティイベント")

    def test_update_status_includes_change_note(self, tmp_path):
        # 対象: append_log
        # パターン: status="更新"の項目が[更新]ラベル付きで出力される
        log_path = tmp_path / "ood_report_log.md"
        entry = _make_entry(status="更新", change_note="深刻度がCriticalに変更")
        ood.append_log(log_path, datetime(2026, 8, 13, 9, 30), [entry])
        text = log_path.read_text(encoding="utf-8")
        assert "[更新] v3.1.0" in text


class TestWriteReportFile:
    def test_creates_outdir_and_returns_expected_path(self, tmp_path):
        # 対象: write_report_file
        # パターン: 出力先ディレクトリが未作成でも作成し、期待ファイル名で保存する
        outdir = tmp_path / "output"
        run_at = datetime(2026, 8, 13, 9, 30)
        report_path = ood.write_report_file(outdir, run_at, "# レポート本文")
        assert report_path == outdir / "report_20260813_0930.md"
        assert report_path.read_text(encoding="utf-8") == "# レポート本文"

    def test_same_minute_run_overwrites_previous_file(self, tmp_path):
        # 対象: write_report_file
        # パターン: 同じ分に2回実行すると、同名ファイルが上書きされる
        outdir = tmp_path / "output"
        run_at = datetime(2026, 8, 13, 9, 30)
        ood.write_report_file(outdir, run_at, "1回目")
        report_path = ood.write_report_file(outdir, run_at, "2回目")
        assert report_path.read_text(encoding="utf-8") == "2回目"


class TestBuildAgent:
    def test_sets_model_instructions_and_output_type(self):
        # 対象: build_agent
        # パターン: 指定したmodel・instructions・output_type・toolsが設定される
        agent = ood.build_agent(model="gpt-5.4")
        assert agent.model == "gpt-5.4"
        assert agent.output_type is OODReport
        assert "Open OnDemand" in agent.instructions
        assert len(agent.tools) == 1


class TestMain:
    def test_missing_api_key_returns_error(self, monkeypatch, capsys):
        # 対象: main
        # パターン: OPENAI_API_KEY未設定時、終了コード1とエラーメッセージを返す
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])
        exit_code = ood.main()
        assert exit_code == 1
        assert "OPENAI_API_KEY" in capsys.readouterr().err

    def test_success_writes_log_and_report(self, tmp_path, monkeypatch, capsys):
        # 対象: main
        # パターン: Agent実行結果を元にログ追記・レポート保存・標準出力を行い、終了コード0を返す
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        log_path = tmp_path / "ood_report_log.md"
        outdir = tmp_path / "output"
        fake_report = OODReport(report_markdown="# 今回のレポート", log_entries=[_make_entry()])

        class _FakeResult:
            final_output = fake_report

        monkeypatch.setattr(ood.Runner, "run_sync", lambda agent, input, max_turns: _FakeResult())
        monkeypatch.setattr(ood, "build_agent", lambda model: object())
        monkeypatch.setattr(
            sys,
            "argv",
            ["ood_news_agent.py", "--log-path", str(log_path), "--outdir", str(outdir)],
        )

        exit_code = ood.main()

        assert exit_code == 0
        assert log_path.exists()
        report_files = list(outdir.glob("report_*.md"))
        assert len(report_files) == 1
        assert report_files[0].read_text(encoding="utf-8") == "# 今回のレポート"
        assert "# 今回のレポート" in capsys.readouterr().out

    def test_no_log_entries_does_not_create_log_file(self, tmp_path, monkeypatch):
        # 対象: main
        # パターン: log_entriesが空の場合、ログファイルは作成されず終了コード0を返す
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        log_path = tmp_path / "ood_report_log.md"
        outdir = tmp_path / "output"
        fake_report = OODReport(report_markdown="変更なし", log_entries=[])

        class _FakeResult:
            final_output = fake_report

        monkeypatch.setattr(ood.Runner, "run_sync", lambda agent, input, max_turns: _FakeResult())
        monkeypatch.setattr(ood, "build_agent", lambda model: object())
        monkeypatch.setattr(
            sys,
            "argv",
            ["ood_news_agent.py", "--log-path", str(log_path), "--outdir", str(outdir)],
        )

        exit_code = ood.main()

        assert exit_code == 0
        assert not log_path.exists()
