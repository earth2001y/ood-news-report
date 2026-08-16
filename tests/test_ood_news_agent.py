"""ood_news_agent.py の各関数に対するユニットテスト。"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime
from typing import get_args

import httpx
import pytest
from openai import APIConnectionError, RateLimitError

import ood_news_agent as ood
from ood_news_agent import OODArticle, OODReport, ReportItem


@pytest.fixture(autouse=True)
def _clear_optional_env(monkeypatch):
    """実行環境の任意設定がテスト結果に影響しないよう、未設定(既定値)の状態に揃える。"""
    for name in (
        "OOD_LOG_LEVEL",
        "BASE_DATE",
        "WINDOW_DAYS",
        "SLACK_WEBHOOK_URL",
        "LOGDIR",
        "OUTDIR",
    ):
        monkeypatch.delenv(name, raising=False)


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


def _make_api_error(code="credit_balance_exhausted", status=429, message="no credits remaining"):
    """OpenAI APIが返すエラーを模した RateLimitError を組み立てる。"""
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(
        status, json={"error": {"message": message, "code": code}}, request=request
    )
    return RateLimitError(
        f"Error code: {status} - {message}", response=response, body={"code": code}
    )


def _raise(error):
    """lambda の中から例外を送出するためのヘルパー。"""
    raise error


def _stub_agents(monkeypatch, report, article_markdown):
    """main が実行する調査・執筆の2つのAgentをモックに置き換え、渡されたモデル名を記録する。"""
    models = {}

    class _Sentinel:
        def __init__(self, kind):
            self.kind = kind

    def _build_researcher_agent(model):
        models["researcher"] = model
        return _Sentinel("researcher")

    def _build_writer_agent(model, categories=None):
        models["writer"] = model
        if categories is not None:
            models["writer_categories"] = categories
        return _Sentinel("writer")

    def _run_sync(agent, input, max_turns):
        is_researcher = agent.kind == "researcher"
        output = report if is_researcher else OODArticle(article_markdown=article_markdown)
        return type("_FakeResult", (), {"final_output": output})

    monkeypatch.setattr(ood, "build_researcher_agent", _build_researcher_agent)
    monkeypatch.setattr(ood, "build_writer_agent", _build_writer_agent)
    monkeypatch.setattr(ood.Runner, "run_sync", _run_sync)
    return models


class TestSetupLogging:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
            ("CRITICAL", logging.CRITICAL),
        ],
    )
    def test_valid_level_names(self, given, expected):
        # 対象: setup_logging
        # パターン: 有効なレベル名を渡すと、そのレベルが設定される
        assert ood.setup_logging(given) == expected
        assert logging.getLogger().level == expected

    def test_lowercase_is_accepted(self):
        # 対象: setup_logging
        # パターン: 小文字で指定しても大文字と同じように解釈される
        assert ood.setup_logging("info") == logging.INFO

    def test_none_falls_back_to_default_warning(self):
        # 対象: setup_logging
        # パターン: Noneの場合、既定のWARNINGが設定される
        assert ood.setup_logging(None) == logging.WARNING
        assert logging.getLogger().level == logging.WARNING

    def test_invalid_level_warns_and_uses_default(self, capsys):
        # 対象: setup_logging
        # パターン: 不正な値の場合、警告を出して既定のWARNINGで続行する
        assert ood.setup_logging("VERBOSE") == logging.WARNING
        err = capsys.readouterr().err
        assert "WARNING: " in err
        assert "'VERBOSE'" in err
        # 指定できる値を警告に列挙する
        assert "DEBUG" in err

    def test_info_message_is_hidden_at_default_level(self, capsys):
        # 対象: setup_logging
        # パターン: 既定のWARNINGでは、INFOのメッセージが出力されない
        ood.setup_logging(None)
        ood.logger.info("進捗メッセージ")
        assert "進捗メッセージ" not in capsys.readouterr().err

    def test_info_message_is_shown_when_info_requested(self, capsys):
        # 対象: setup_logging
        # パターン: INFO指定時、INFOのメッセージが標準エラー出力に現れる
        ood.setup_logging("INFO")
        ood.logger.info("進捗メッセージ")
        assert "進捗メッセージ" in capsys.readouterr().err


class TestResolveBaseDate:
    def test_none_uses_run_date(self):
        # 対象: resolve_base_date
        # パターン: 未指定の場合、実行日時の日付部分を基準日とする
        run_at = datetime(2026, 8, 14, 9, 57)
        assert ood.resolve_base_date(None, run_at) == date(2026, 8, 14)

    def test_explicit_date_overrides_run_date(self):
        # 対象: resolve_base_date
        # パターン: 指定した日付が実行日より優先される
        run_at = datetime(2026, 8, 14, 9, 57)
        assert ood.resolve_base_date("2026-07-31", run_at) == date(2026, 7, 31)

    @pytest.mark.parametrize(
        "given",
        ["2026/07/31", "20260731", "2026-13-01", "2026-07-32", "昨日", "", "2026-07"],
    )
    def test_invalid_format_raises_value_error(self, given):
        # 対象: resolve_base_date
        # パターン: YYYY-MM-DD として解釈できない値はValueErrorになる
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            ood.resolve_base_date(given, datetime(2026, 8, 14, 9, 57))

    def test_future_date_is_accepted(self):
        # 対象: resolve_base_date
        # パターン: 未来日でも拒否しない(先の期間を指定する用途を妨げない)
        run_at = datetime(2026, 8, 14, 9, 57)
        assert ood.resolve_base_date("2026-12-31", run_at) == date(2026, 12, 31)


class TestReportItemCategory:
    def test_literal_matches_categories(self):
        # 対象: ReportItem.category
        # パターン: 許容値がCATEGORIESと順序を含めて一致する（定義の二重管理による乖離の検出）
        allowed = get_args(ReportItem.model_fields["category"].annotation)
        assert list(allowed) == ood.CATEGORIES

    def test_accepts_other_hot_topics(self):
        # パターン: 追加カテゴリ「その他のホットトピック」の項目を構築できる
        entry = _make_entry(category="その他のホットトピック")
        assert entry.category == "その他のホットトピック"


class TestRenderTemplate:
    def test_instructions_contains_all_categories(self):
        # 対象: render_template("researcher_instructions.j2")
        # パターン: 全カテゴリ名が指示文に含まれる
        rendered = ood.render_template("researcher_instructions.j2")
        for category in ood.CATEGORIES:
            assert category in rendered

    def test_researcher_instructions_uses_structured_entries_only(self):
        # 対象: render_template("researcher_instructions.j2")
        # パターン: 調査担当の出力形式がentriesだけを要求する
        rendered = ood.render_template("researcher_instructions.j2")
        assert "【出力形式(entries)】" in rendered
        assert "report_markdown" not in rendered

    def test_report_markdown_renders_entries_and_unchanged_categories(self):
        # 対象: render_template("report_markdown.j2")
        # パターン: entriesから項目を分類し、空カテゴリは「変更なし」とする
        rendered = ood.render_template(
            "report_markdown.j2",
            categories=ood.CATEGORIES,
            entries=[_make_entry(status="更新", change_note="深刻度がCriticalに変更")],
        )
        assert "## 新バージョンのリリース情報" in rendered
        assert "- [更新] v3.1.0 (2026-08-01) - 新機能が追加された" in rendered
        assert "変更点: 深刻度がCriticalに変更" in rendered
        assert "## 開発ロードマップの更新・公開" in rendered
        assert rendered.count("変更なし") == len(ood.CATEGORIES) - 1

    def test_writer_instructions_lists_categories_in_order(self):
        # 対象: render_template("writer_instructions.j2")
        # パターン: categoriesを渡すと全カテゴリがCATEGORIESの順で番号付きで並ぶ
        rendered = ood.render_template("writer_instructions.j2", categories=ood.CATEGORIES)
        positions = [rendered.index(category) for category in ood.CATEGORIES]
        assert positions == sorted(positions)
        assert f"1. {ood.CATEGORIES[0]}" in rendered

    def test_writer_instructions_forbids_bracket_labels_and_allows_supplemental_search(self):
        # 対象: render_template("writer_instructions.j2")
        # パターン: 角括弧ラベルを禁止し、事実の補足検索を許可する
        rendered = ood.render_template("writer_instructions.j2", categories=ood.CATEGORIES)
        assert "角括弧ラベルは使わない" in rendered
        assert "補足情報獲得のためのWeb検索はしてよい" in rendered
        assert "事実の追加・推測・脚色は一切しない" in rendered

    def test_writer_instructions_lists_only_target_categories(self):
        # 対象: render_template("writer_instructions.j2")
        # パターン: 執筆対象として渡したカテゴリだけが指示文に含まれる
        target = [ood.CATEGORIES[0], ood.CATEGORIES[3]]
        rendered = ood.render_template("writer_instructions.j2", categories=target)
        assert "1. 新バージョンのリリース情報" in rendered
        assert "2. コミュニティイベント" in rendered
        assert "開発ロードマップの更新・公開" not in rendered
        assert "セキュリティ脆弱性情報" not in rendered

    def test_writer_input_embeds_entries_and_report(self):
        # 対象: render_template("writer_input.j2")
        # パターン: 調査レポート本文には期間表記を入れず、各項目と報告文のみが埋め込まれる
        rendered = ood.render_template(
            "writer_input.j2",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            entries=[_make_entry(status="更新", change_note="深刻度がCriticalに変更")],
        )
        assert "調査対象期間:" not in rendered
        assert "2026-07-14 〜 2026-08-13" not in rendered
        assert "v3.1.0" in rendered
        assert "https://example.com/v3.1.0" in rendered
        assert "深刻度がCriticalに変更" in rendered

    def test_writer_input_marks_empty_entries(self):
        # 対象: render_template("writer_input.j2")
        # パターン: entriesが空の場合、新規・更新なしを示す文言が入る
        rendered = ood.render_template(
            "writer_input.j2",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            entries=[],
        )
        assert "(今回の期間内に新規・更新の項目はありませんでした)" in rendered

    def test_writer_input_marks_unknown_item_date(self):
        # 対象: render_template("writer_input.j2")
        # パターン: item_dateが空文字の場合、日付が不明であることを明示する
        rendered = ood.render_template(
            "writer_input.j2",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            entries=[_make_entry(item_date="")],
        )
        assert "日付: (不明)" in rendered

    def test_user_input_embeds_context_variables(self):
        # 対象: render_template("researcher_input.j2")
        # パターン: base_date/window_start/window_days/existing_logが本文に埋め込まれる
        rendered = ood.render_template(
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
        rendered = ood.render_template(
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
        rendered = ood.render_template(
            "researcher_input.j2",
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            existing_log=json.dumps(
                [{"title": "v3.1.0"}, {"title": "CVE-2026-0001"}],
                ensure_ascii=False,
            ),
        )
        assert '"title": "v3.1.0"' in rendered
        assert '"title": "CVE-2026-0001"' in rendered
        assert "datetime" not in rendered
        assert "period" not in rendered


class TestLoadLog:
    def test_missing_file_returns_empty_markdown_placeholder(self, tmp_path):
        # 対象: load_log
        # パターン: ログファイルが存在しない場合、項目なしのMarkdownを返す
        log_path = tmp_path / "ood_research_log.json"
        assert ood.load_log(log_path) == "(報告済み項目はありません)"

    def test_empty_file_returns_empty_markdown_placeholder(self, tmp_path):
        # 対象: load_log
        # パターン: ログファイルが空白のみの場合、項目なしのMarkdownを返す
        log_path = tmp_path / "ood_research_log.json"
        log_path.write_text("   \n", encoding="utf-8")
        assert ood.load_log(log_path) == "(報告済み項目はありません)"

    def test_existing_json_entries_are_flattened_to_markdown(self, tmp_path):
        # 対象: load_log
        # パターン: 実行記録からentriesだけを抽出し、調査回をまたいだMarkdownとして返す
        log_path = tmp_path / "ood_research_log.json"
        log_path.write_text(
            '[{"datetime": "2026-08-13T09:30:00", "period": {}, '
            '"entries": [{"category": "新バージョンのリリース情報", "status": "新規", '
            '"title": "v3.1.0", "item_date": "2026-08-01", "url": "https://example.com/v3.1.0", '
            '"summary": "新機能が追加された", "change_note": ""}]}, '
            '{"datetime": "2026-08-14T09:30:00", "period": {}, '
            '"entries": [{"category": "新バージョンのリリース情報", "status": "更新", '
            '"title": "v3.1.0", "item_date": "2026-08-02", "url": "https://example.com/v3.1.0", '
            '"summary": "修正が追加された", "change_note": "変更点あり"}]}]\n',
            encoding="utf-8",
        )
        rendered = ood.load_log(log_path)
        assert rendered.startswith("### 新バージョンのリリース情報")
        assert rendered.count("- [") == 2
        assert "v3.1.0 (2026-08-01)" in rendered
        assert "v3.1.0 (2026-08-02)" in rendered
        assert "変更点: 変更点あり" in rendered
        assert "2026-08-13T09:30:00" not in rendered
        assert '"datetime"' not in rendered


class TestAppendLog:
    def test_no_entries_does_not_create_file(self, tmp_path):
        # 対象: append_log
        # パターン: entriesが空の場合、ファイルを作成しない
        log_path = tmp_path / "ood_research_log.json"
        ood.append_log(log_path, datetime(2026, 8, 13, 9, 30), [], "2026-07-14", "2026-08-13", 30)
        assert not log_path.exists()

    def test_creates_file_with_header_when_absent(self, tmp_path):
        # 対象: append_log
        # パターン: ログファイルが存在しない場合、JSON記録を新規作成し、対象期間を記録する
        log_path = tmp_path / "ood_research_log.json"
        ood.append_log(
            log_path,
            datetime(2026, 8, 13, 9, 30),
            [_make_entry()],
            "2026-07-14",
            "2026-08-13",
            30,
        )
        record = json.loads(log_path.read_text(encoding="utf-8"))[0]
        assert record["datetime"] == "2026-08-13T09:30:00"
        assert record["period"] == {
            "start": "2026-07-14",
            "end": "2026-08-13",
            "days": 30,
        }
        assert record["entries"] == [_make_entry().model_dump()]

    def test_appends_without_duplicating_header(self, tmp_path):
        # 対象: append_log
        # パターン: ログファイルが既存の場合、既存配列を保って記録を追記する
        log_path = tmp_path / "ood_research_log.json"
        log_path.write_text("[]\n", encoding="utf-8")
        ood.append_log(
            log_path,
            datetime(2026, 8, 13, 10, 0),
            [_make_entry(item_date="")],
            "2026-07-14",
            "2026-08-13",
            30,
        )
        records = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(records) == 1
        assert records[0]["period"]["days"] == 30
        assert records[0]["entries"][0]["item_date"] == ""

    def test_groups_entries_by_category_order(self, tmp_path):
        # 対象: append_log
        # パターン: entriesの順序に関わらず、CATEGORIESの順で出力される
        log_path = tmp_path / "ood_research_log.json"
        entries = [
            _make_entry(category="コミュニティイベント", title="GOOD Conference 2026"),
            _make_entry(category="新バージョンのリリース情報", title="v3.1.0"),
        ]
        ood.append_log(
            log_path,
            datetime(2026, 8, 13, 9, 30),
            entries,
            "2026-07-14",
            "2026-08-13",
            30,
        )
        record = json.loads(log_path.read_text(encoding="utf-8"))[0]
        assert [entry["category"] for entry in record["entries"]] == [
            "コミュニティイベント",
            "新バージョンのリリース情報",
        ]

    def test_update_status_includes_change_note(self, tmp_path):
        # 対象: append_log
        # パターン: status="更新"の項目が[更新]ラベル付きで出力される
        log_path = tmp_path / "ood_research_log.json"
        entry = _make_entry(status="更新", change_note="深刻度がCriticalに変更")
        ood.append_log(
            log_path,
            datetime(2026, 8, 13, 9, 30),
            [entry],
            "2026-07-14",
            "2026-08-13",
            30,
        )
        record = json.loads(log_path.read_text(encoding="utf-8"))[0]
        assert record["entries"][0]["status"] == "更新"
        assert record["entries"][0]["change_note"] == "深刻度がCriticalに変更"


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


class TestPostToSlack:
    def test_converts_markdown_to_slack_mrkdwn(self):
        # 対象: markdown_to_slack_mrkdwn
        # パターン: 見出し・リンク・強調・コード・箇条書きをSlack記法へ変換する
        markdown = (
            "# 見出し\n\n**重要**です。`設定値`を確認します。\n- 項目 ([出典](https://example.com))"
        )

        assert ood.markdown_to_slack_mrkdwn(markdown) == (
            "*見出し*\n\n*重要*です。 `設定値` を確認します。\n• 項目 (<https://example.com|出典>)"
        )

    def test_posts_article_as_json_text(self, monkeypatch):
        # 対象: post_to_slack
        # パターン: 記事本文をJSONのtextとしてPOSTする
        captured = {}

        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        def _urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response()

        monkeypatch.setattr(ood, "urlopen", _urlopen)

        ood.post_to_slack("https://hooks.slack.com/services/test", "# 記事本文")

        request = captured["request"]
        assert request.method == "POST"
        assert request.get_header("Content-type") == "application/json"
        assert json.loads(request.data) == {"text": "*記事本文*"}
        assert captured["timeout"] == ood.SLACK_TIMEOUT_SECONDS

    def test_raises_when_slack_returns_non_success_status(self, monkeypatch):
        # 対象: post_to_slack
        # パターン: Slackが成功以外のHTTPステータスを返した場合、RuntimeErrorになる
        class _Response:
            status = 202

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        monkeypatch.setattr(ood, "urlopen", lambda request, timeout: _Response())

        with pytest.raises(RuntimeError, match="HTTP 202"):
            ood.post_to_slack("https://hooks.slack.com/services/test", "記事本文")


class TestBuildResearcherAgent:
    def test_sets_model_instructions_and_output_type(self):
        # 対象: build_researcher_agent
        # パターン: 指定したmodel・instructions・output_type・toolsが設定される
        researcher = ood.build_researcher_agent(model="gpt-5.4")
        assert researcher.model == "gpt-5.4"
        assert researcher.output_type is OODReport
        assert "Open OnDemand" in researcher.instructions
        assert len(researcher.tools) == 1


class TestBuildWriterAgent:
    def test_sets_model_output_type_and_web_search_tool(self):
        # 対象: build_writer_agent
        # パターン: 出力スキーマがOODArticleで、Web検索ツールを1つ持つ
        writer = ood.build_writer_agent(model="gpt-test")
        assert writer.model == "gpt-test"
        assert writer.output_type is OODArticle
        assert len(writer.tools) == 1
        assert "ニュースレター記事" in writer.instructions


class TestComposeArticle:
    def test_returns_article_markdown_from_agent_output(self, monkeypatch):
        # 対象: compose_article
        # パターン: 執筆担当Agentの出力からarticle_markdownを取り出して返す
        class _FakeResult:
            final_output = OODArticle(article_markdown="# 記事本文")

        monkeypatch.setattr(ood.Runner, "run_sync", lambda agent, input, max_turns: _FakeResult())
        report = OODReport(entries=[_make_entry()])

        article = ood.compose_article(
            object(),
            report,
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            max_turns=12,
        )

        assert article == "# 記事本文"

    def test_passes_entries_and_report_to_agent(self, monkeypatch):
        # 対象: compose_article
        # パターン: 構造化項目から生成した報告文が入力に含まれる
        captured = {}

        class _FakeResult:
            final_output = OODArticle(article_markdown="# 記事本文")

        def _fake_run_sync(agent, input, max_turns):
            captured["input"] = input
            captured["max_turns"] = max_turns
            return _FakeResult()

        monkeypatch.setattr(ood.Runner, "run_sync", _fake_run_sync)
        report = OODReport(entries=[_make_entry()])

        ood.compose_article(
            object(),
            report,
            base_date="2026-08-13",
            window_start="2026-07-14",
            window_days=30,
            max_turns=12,
        )

        assert "v3.1.0" in captured["input"]
        assert "## 新バージョンのリリース情報" in captured["input"]
        assert captured["max_turns"] == 12


class TestMainNoNewInformation:
    def test_skips_writing_when_research_has_no_new_information(
        self, monkeypatch, tmp_path, capsys
    ):
        # 対象: main
        # パターン: 調査結果の項目が空の場合、執筆・出力・ファイル保存を行わず正常終了する
        report = OODReport(entries=[])
        models = _stub_agents(monkeypatch, report, "記事本文")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])

        assert ood.main() == 0

        assert "writer" not in models
        assert capsys.readouterr().out == ""
        assert not (tmp_path / "ood_research_log.json").exists()
        assert not (tmp_path / "output").exists()


class TestParseArguments:
    def test_parses_cli_values(self, monkeypatch):
        # 対象: build_parser
        # パターン: 指定したCLI引数がNamespaceに格納される
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ood_news_agent.py",
                "--model",
                "gpt-test",
                "--writer-model",
                "gpt-writer",
                "--window-days",
                "7",
                "--base-date",
                "2026-07-31",
                "--max-turns",
                "12",
            ],
        )

        args = ood.build_parser().parse_args()

        assert args.model == "gpt-test"
        assert args.writer_model == "gpt-writer"
        assert args.window_days == 7
        assert args.base_date == "2026-07-31"
        assert args.max_turns == 12

    def test_base_date_defaults_to_none(self, monkeypatch):
        # 対象: build_parser
        # パターン: --base-date未指定かつ環境変数なしの場合、None(=実行日扱い)になる
        monkeypatch.delenv("BASE_DATE", raising=False)
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])
        assert ood.build_parser().parse_args().base_date is None

    def test_base_date_reads_environment_variable(self, monkeypatch):
        # 対象: build_parser
        # パターン: 環境変数 BASE_DATE が既定値として使われる
        monkeypatch.setenv("BASE_DATE", "2026-07-01")
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])
        assert ood.build_parser().parse_args().base_date == "2026-07-01"

    def test_cli_base_date_overrides_environment_variable(self, monkeypatch):
        # 対象: build_parser
        # パターン: 環境変数より --base-date の指定が優先される
        monkeypatch.setenv("BASE_DATE", "2026-07-01")
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py", "--base-date", "2026-07-31"])
        assert ood.build_parser().parse_args().base_date == "2026-07-31"

    def test_writer_model_defaults_to_none(self, monkeypatch):
        # 対象: build_parser
        # パターン: --writer-model未指定かつ環境変数なしの場合、Noneになる
        monkeypatch.delenv("OOD_WRITER_MODEL", raising=False)
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])
        assert ood.build_parser().parse_args().writer_model is None

    def test_slack_webhook_url_is_not_a_cli_argument(self, monkeypatch):
        # 対象: build_parser
        # パターン: Slack Webhook URLをコマンド引数で指定すると受け付けない
        monkeypatch.setattr(
            sys,
            "argv",
            ["ood_news_agent.py", "--slack-webhook-url", "https://hooks.slack.com/services/test"],
        )
        with pytest.raises(SystemExit):
            ood.build_parser().parse_args()

    def test_outdir_is_not_a_cli_argument(self, monkeypatch):
        # 対象: build_parser
        # パターン: OUTDIR は環境変数でのみ指定し、CLI引数では受け付けない
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py", "--outdir", "custom-output"])
        with pytest.raises(SystemExit):
            ood.build_parser().parse_args()

    def test_logdir_is_not_a_cli_argument(self, monkeypatch):
        # 対象: build_parser
        # パターン: LOGDIR は環境変数でのみ指定し、CLI引数では受け付けない
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py", "--logdir", "custom-logs"])
        with pytest.raises(SystemExit):
            ood.build_parser().parse_args()

    def test_log_level_defaults_to_none(self, monkeypatch):
        # 対象: build_parser
        # パターン: --log-level未指定かつ環境変数なしの場合、None(=既定値扱い)になる
        monkeypatch.delenv("OOD_LOG_LEVEL", raising=False)
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])
        assert ood.build_parser().parse_args().log_level is None

    def test_log_level_reads_environment_variable(self, monkeypatch):
        # 対象: build_parser
        # パターン: 環境変数 OOD_LOG_LEVEL が既定値として使われる
        monkeypatch.setenv("OOD_LOG_LEVEL", "DEBUG")
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])
        assert ood.build_parser().parse_args().log_level == "DEBUG"

    def test_cli_log_level_overrides_environment_variable(self, monkeypatch):
        # 対象: build_parser
        # パターン: 環境変数より --log-level の指定が優先される
        monkeypatch.setenv("OOD_LOG_LEVEL", "DEBUG")
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py", "--log-level", "ERROR"])
        assert ood.build_parser().parse_args().log_level == "ERROR"

    def test_dry_run_is_enabled_by_option(self, monkeypatch):
        # 対象: build_parser
        # パターン: --dry-runを指定するとドライランが有効になる
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py", "--dry-run"])
        assert ood.build_parser().parse_args().dry_run is True

    def test_resolve_log_path_uses_default_log_directory(self, monkeypatch, tmp_path):
        # 対象: resolve_log_path
        # パターン: LOGDIR未設定時は log ディレクトリを使い、存在しないなら作成する
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LOGDIR", raising=False)

        log_path = ood.resolve_log_path()

        assert log_path == tmp_path / "log" / "ood_research_log.json"
        assert log_path.parent.is_dir()

    def test_resolve_log_path_uses_environment_directory(self, monkeypatch, tmp_path):
        # 対象: resolve_log_path
        # パターン: LOGDIRを指定したとき、そのディレクトリ配下にログを出力する
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOGDIR", "custom-logs")

        log_path = ood.resolve_log_path()

        assert log_path == tmp_path / "custom-logs" / "ood_research_log.json"
        assert log_path.parent.is_dir()


class TestDescribeApiError:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("credit_balance_exhausted", "クレジットを追加"),
            ("insufficient_quota", "残高と上限を確認"),
            ("invalid_api_key", "OPENAI_API_KEY が無効"),
            ("model_not_found", "モデル名の綴り"),
        ],
    )
    def test_known_codes_include_remedy(self, code, expected):
        # 対象: describe_api_error
        # パターン: 既知のエラーコードには対処方法とAPI応答の両方が含まれる
        message = ood.describe_api_error(_make_api_error(code=code, message="原文メッセージ"))
        assert expected in message
        assert "原文メッセージ" in message

    def test_unknown_code_falls_back_to_status_and_message(self):
        # 対象: describe_api_error
        # パターン: 未知のエラーコードでもHTTPステータスとAPIのメッセージを提示する
        message = ood.describe_api_error(
            _make_api_error(code="something_new", status=500, message="internal error")
        )
        assert "HTTP 500" in message
        assert "internal error" in message

    def test_connection_error_without_response(self):
        # 対象: describe_api_error
        # パターン: responseを持たない接続エラーでも例外にならずメッセージを返す
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        message = ood.describe_api_error(APIConnectionError(request=request))
        assert "OpenAI APIの呼び出しに失敗した" in message


class TestMain:
    def test_dry_run_outputs_article_without_writing_or_posting(
        self, tmp_path, monkeypatch, capsys
    ):
        # 対象: main
        # パターン: ドライランでも調査・記事再構成を実行し、記事は標準出力だけに出す
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        log_path = tmp_path / "logs" / "ood_research_log.json"
        outdir = tmp_path / "output"
        fake_report = OODReport(entries=[_make_entry()])
        models = _stub_agents(monkeypatch, fake_report, "# 記事本文")
        monkeypatch.setattr(
            ood,
            "post_to_slack",
            lambda *args: (_ for _ in ()).throw(AssertionError("Slack投稿が実行された")),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ood_news_agent.py",
                "--dry-run",
            ],
        )

        assert ood.main() == 0

        assert models == {
            "researcher": "gpt-5.4",
            "writer": "gpt-5.4",
            "writer_categories": [ood.CATEGORIES[0]],
        }
        assert capsys.readouterr().out.strip() == "# 記事本文"
        assert not log_path.exists()
        assert not outdir.exists()

    def test_posts_article_to_configured_slack_webhook(self, tmp_path, monkeypatch):
        # 対象: main
        # パターン: Slack Webhook URL指定時、保存した記事本文を投稿する
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        fake_report = OODReport(entries=[_make_entry()])
        _stub_agents(monkeypatch, fake_report, "# 記事本文")
        captured = {}

        def _post_to_slack(webhook_url, article_markdown):
            captured["webhook_url"] = webhook_url
            captured["article_markdown"] = article_markdown

        monkeypatch.setattr(ood, "post_to_slack", _post_to_slack)
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])

        assert ood.main() == 0

        assert captured == {
            "webhook_url": "https://hooks.slack.com/services/test",
            "article_markdown": "# 記事本文",
        }

    def test_base_date_defines_investigation_window(self, tmp_path, monkeypatch, capsys):
        # 対象: main
        # パターン: --base-date指定時、その日を終端とする期間が調査担当Agentに渡る
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        captured_input = {}

        empty_report = OODReport(entries=[])

        def _run_sync(agent, input, max_turns):
            captured_input.setdefault("text", input)
            return type("_R", (), {"final_output": empty_report})

        monkeypatch.setattr(ood, "build_researcher_agent", lambda model: object())
        monkeypatch.setattr(ood, "build_writer_agent", lambda model, categories=None: object())
        monkeypatch.setattr(ood.Runner, "run_sync", _run_sync)
        monkeypatch.setattr(ood, "compose_article", lambda *a, **kw: "# 記事本文")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ood_news_agent.py",
                "--base-date",
                "2026-07-31",
                "--window-days",
                "10",
                "--log-level",
                "INFO",
            ],
        )

        assert ood.main() == 0

        # 基準日を終端に、window-days 日前が開始日になる
        assert "調査の基準日: 2026-07-31" in captured_input["text"]
        assert "2026-07-21 〜 2026-07-31" in captured_input["text"]
        assert "2026-07-21 〜 2026-07-31" in capsys.readouterr().err

    def test_base_date_does_not_change_report_filename(self, tmp_path, monkeypatch):
        # 対象: main
        # パターン: 基準日を過去にしても、ファイル名は実行日時で、JSONログに対象期間を記録する
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        log_path = tmp_path / "logs" / "ood_research_log.json"
        outdir = tmp_path / "output"
        fake_report = OODReport(entries=[_make_entry()])
        _stub_agents(monkeypatch, fake_report, "# 記事本文")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ood_news_agent.py",
                "--base-date",
                "2020-01-01",
            ],
        )

        assert ood.main() == 0

        today = datetime.now().strftime("%Y%m%d")
        report_files = [p.name for p in outdir.glob("report_*.md")]
        assert len(report_files) == 1
        assert report_files[0].startswith(f"report_{today}_")
        record = json.loads(log_path.read_text(encoding="utf-8"))[0]
        assert record["datetime"].startswith(datetime.now().strftime("%Y-%m-%dT"))
        assert record["period"] == {
            "start": "2019-12-02",
            "end": "2020-01-01",
            "days": 30,
        }

    def test_invalid_base_date_returns_error_without_calling_api(
        self, tmp_path, monkeypatch, capsys
    ):
        # 対象: main
        # パターン: 基準日の書式が不正な場合、Agentを実行せず終了コード1とERRORログを返す
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        log_path = tmp_path / "logs" / "ood_research_log.json"
        outdir = tmp_path / "output"
        monkeypatch.setenv("OUTDIR", str(outdir))

        def _must_not_run(agent, input, max_turns):
            raise AssertionError("基準日が不正なのにAgentが実行された")

        monkeypatch.setattr(ood.Runner, "run_sync", _must_not_run)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ood_news_agent.py",
                "--base-date",
                "2026/07/31",
            ],
        )

        assert ood.main() == 1
        err = capsys.readouterr().err
        assert "YYYY-MM-DD" in err
        assert "'2026/07/31'" in err
        assert not log_path.exists()
        assert not outdir.exists()

    def test_progress_is_hidden_at_default_level(self, tmp_path, monkeypatch, capsys):
        # 対象: main
        # パターン: 既定のWARNINGでは、標準出力は記事のみで進捗ログが出ない
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        fake_report = OODReport(entries=[_make_entry()])
        _stub_agents(monkeypatch, fake_report, "# 記事本文")
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])

        assert ood.main() == 0

        captured = capsys.readouterr()
        # 記事本文は標準出力、進捗はINFOなので既定レベルでは出力されない
        assert captured.out.strip() == "# 記事本文"
        assert "調査中" not in captured.err
        assert "保存しました" not in captured.err

    def test_progress_is_shown_when_info_level_requested(self, tmp_path, monkeypatch, capsys):
        # 対象: main
        # パターン: --log-level INFO指定時、進捗と完了報告が標準エラー出力に出る
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        fake_report = OODReport(entries=[_make_entry()])
        _stub_agents(monkeypatch, fake_report, "# 記事本文")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ood_news_agent.py",
                "--log-level",
                "INFO",
            ],
        )

        assert ood.main() == 0

        captured = capsys.readouterr()
        assert captured.out.strip() == "# 記事本文"
        assert "調査中" in captured.err
        assert "再構成中" in captured.err
        assert "1 件を追記しました" in captured.err
        assert "保存しました" in captured.err

    def test_invalid_log_level_warns_and_continues(self, tmp_path, monkeypatch, capsys):
        # 対象: main
        # パターン: 不正なログレベルでも処理を中断せず、警告を出して正常終了する
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        fake_report = OODReport(entries=[])
        _stub_agents(monkeypatch, fake_report, "# 記事本文")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ood_news_agent.py",
                "--log-level",
                "VERBOSE",
            ],
        )

        assert ood.main() == 0
        assert "ログレベル 'VERBOSE' は不正です" in capsys.readouterr().err

    def test_missing_api_key_returns_error(self, monkeypatch, capsys, caplog):
        # 対象: main
        # パターン: OPENAI_API_KEY未設定時、終了コード1とERRORログを返す
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])
        with caplog.at_level(logging.ERROR):
            exit_code = ood.main()
        assert exit_code == 1
        err = capsys.readouterr().err
        assert "OPENAI_API_KEY" in err
        assert err.startswith("ERROR: ")

    def test_research_api_error_returns_error_without_writing(self, tmp_path, monkeypatch, capsys):
        # 対象: main
        # パターン: 調査中のAPIエラー時、ログ・レポートを書かず終了コード1とERRORログを返す
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        log_path = tmp_path / "logs" / "ood_research_log.json"
        outdir = tmp_path / "output"
        monkeypatch.setattr(ood, "build_researcher_agent", lambda model: object())
        monkeypatch.setattr(
            ood.Runner,
            "run_sync",
            lambda agent, input, max_turns: _raise(_make_api_error()),
        )
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])

        exit_code = ood.main()

        assert exit_code == 1
        err = capsys.readouterr().err
        assert "調査に失敗しました" in err
        assert "クレジットを追加" in err
        assert not log_path.exists()
        assert not outdir.exists()

    def test_writer_api_error_keeps_log_and_returns_error(self, tmp_path, monkeypatch, capsys):
        # 対象: main
        # パターン: 再構成中のAPIエラー時、ログ追記は保持しレポートを書かず終了コード1を返す
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        log_path = tmp_path / "logs" / "ood_research_log.json"
        outdir = tmp_path / "output"
        fake_report = OODReport(entries=[_make_entry()])
        monkeypatch.setattr(ood, "build_researcher_agent", lambda model: object())
        monkeypatch.setattr(ood, "build_writer_agent", lambda model, categories=None: object())
        monkeypatch.setattr(
            ood.Runner,
            "run_sync",
            lambda agent, input, max_turns: type("_R", (), {"final_output": fake_report}),
        )
        monkeypatch.setattr(ood, "compose_article", lambda *a, **kw: _raise(_make_api_error()))
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])

        exit_code = ood.main()

        assert exit_code == 1
        assert "記事の再構成に失敗しました" in capsys.readouterr().err
        # 調査結果は失われない
        assert log_path.exists()
        assert "v3.1.0" in log_path.read_text(encoding="utf-8")
        assert not outdir.exists()

    def test_success_writes_log_and_article(self, tmp_path, monkeypatch, capsys):
        # 対象: main
        # パターン: 調査→再構成の2段実行を元にログ追記・レポート保存・標準出力を行い、
        #           終了コード0を返す
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        log_path = tmp_path / "logs" / "ood_research_log.json"
        outdir = tmp_path / "output"
        fake_report = OODReport(entries=[_make_entry()])
        _stub_agents(monkeypatch, fake_report, "# 今回のニュースレター")
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])

        exit_code = ood.main()

        assert exit_code == 0
        assert log_path.exists()
        report_files = list(outdir.glob("report_*.md"))
        assert len(report_files) == 1
        # レポートファイル・標準出力は箇条書き報告文ではなく再構成後の記事になる
        assert report_files[0].read_text(encoding="utf-8") == "# 今回のニュースレター"
        out = capsys.readouterr().out
        assert "# 今回のニュースレター" in out
        assert "# 今回のレポート" not in out

    def test_writer_model_falls_back_to_model(self, tmp_path, monkeypatch):
        # 対象: main
        # パターン: --writer-model未指定の場合、執筆担当Agentも--modelのモデルで構築される
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        monkeypatch.delenv("OOD_WRITER_MODEL", raising=False)
        fake_report = OODReport(entries=[_make_entry()])
        models = _stub_agents(monkeypatch, fake_report, "記事")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ood_news_agent.py",
                "--model",
                "gpt-test",
            ],
        )

        assert ood.main() == 0
        assert models == {
            "researcher": "gpt-test",
            "writer": "gpt-test",
            "writer_categories": [ood.CATEGORIES[0]],
        }

    def test_writer_model_overrides_model(self, tmp_path, monkeypatch):
        # 対象: main
        # パターン: --writer-model指定時、調査担当と執筆担当で別のモデルが使われる
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        fake_report = OODReport(entries=[_make_entry()])
        models = _stub_agents(monkeypatch, fake_report, "記事")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ood_news_agent.py",
                "--model",
                "gpt-test",
                "--writer-model",
                "gpt-writer",
            ],
        )

        assert ood.main() == 0
        assert models == {
            "researcher": "gpt-test",
            "writer": "gpt-writer",
            "writer_categories": [ood.CATEGORIES[0]],
        }

    def test_no_entries_does_not_create_log_file(self, tmp_path, monkeypatch):
        # 対象: main
        # パターン: entriesが空の場合、ログファイルは作成されず終了コード0を返す
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOGDIR", str(tmp_path / "logs"))
        monkeypatch.setenv("OUTDIR", str(tmp_path / "output"))
        log_path = tmp_path / "logs" / "ood_research_log.json"
        fake_report = OODReport(entries=[])
        _stub_agents(monkeypatch, fake_report, "記事")
        monkeypatch.setattr(sys, "argv", ["ood_news_agent.py"])

        exit_code = ood.main()

        assert exit_code == 0
        assert not log_path.exists()
