from datetime import datetime
from zoneinfo import ZoneInfo

from iiwi.models.report import WorklogReport
from iiwi.models.report_options import DetailLevel
from iiwi.models.time_range import DateRange
from iiwi.renderers.markdown import render_narrative

TZ = ZoneInfo("Asia/Taipei")


def narrative_report() -> WorklogReport:
    return WorklogReport(
        generated_at=datetime(2026, 7, 29, 20, 0, tzinfo=TZ),
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=TZ),
            until=datetime(2026, 7, 27, tzinfo=TZ),
        ),
        repositories=[],
        narrative_text="# Weekly Engineering Review\n\n## Executive Summary\n- Did work.",
    )


def test_render_narrative_wraps_the_body_under_the_worklog_header() -> None:
    out = render_narrative(narrative_report(), timezone="Asia/Taipei")

    assert out.startswith("# Engineering Worklog\n")
    assert "**Period:** 2026-07-20 00:00 – 2026-07-27 00:00" in out
    assert "**Timezone:** Asia/Taipei" in out
    assert "**Generated:** 2026-07-29 20:00" in out
    assert "# Weekly Engineering Review" in out
    assert "- Did work." in out


def test_render_narrative_emits_usage_and_warnings_when_present() -> None:
    report = narrative_report()
    report.usage_text = "gpt-5-mini  1234 tokens"
    report.warnings = ["opencode run unavailable; used structured fallback"]

    out = render_narrative(report, timezone="Asia/Taipei")

    assert "## Usage" in out
    assert "gpt-5-mini  1234 tokens" in out
    assert "## Warnings" in out
    assert "- opencode run unavailable" in out


def test_render_narrative_omits_usage_and_warnings_when_absent() -> None:
    out = render_narrative(narrative_report(), timezone="Asia/Taipei")

    assert "## Usage" not in out
    assert "## Warnings" not in out


def test_render_narrative_normalizes_to_a_single_trailing_newline() -> None:
    out = render_narrative(narrative_report(), timezone="Asia/Taipei")

    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_narrative_brief_omits_usage() -> None:
    report = narrative_report()
    report.usage_text = "gpt-5 123 tokens"

    assert "## Usage" not in render_narrative(
        report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF
    )


def test_narrative_full_keeps_usage() -> None:
    report = narrative_report()
    report.usage_text = "gpt-5 123 tokens"

    assert "## Usage" in render_narrative(
        report, timezone="Asia/Taipei", detail=DetailLevel.FULL
    )
