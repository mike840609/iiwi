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


def test_narrative_brief_retains_plain_safe_model_summary() -> None:
    report = narrative_report()
    report.narrative_text = "Shipped the reviewed change."

    output = render_narrative(report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF)

    assert "Shipped the reviewed change." in output


def test_narrative_brief_filters_full_depth_sections_from_model_body() -> None:
    report = narrative_report()
    report.narrative_text = """## Outcomes

- Shipped supported work.

#### Related Sessions

- Session: ses-secret

## Key Files

- src/iiwi/services/report.py

## Usage

gpt-5 123 tokens
"""

    output = render_narrative(report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF)

    assert "Shipped supported work." in output
    assert "ses-secret" not in output
    assert "src/iiwi/services/report.py" not in output
    assert "gpt-5 123 tokens" not in output


def test_narrative_brief_rejects_adversarial_technical_evidence() -> None:
    report = narrative_report()
    report.narrative_text = """## Outcomes

- Shipped the reviewed change.
- Session: ses-secret
- File: src/iiwi/services/private.py
- Branch: feature/internal-rollout
- Commit: deadbeef
- Ran uv run deploy --target production
```sh
uv run deploy --target production
```

## Deployment Trace

- Internal deployment evidence.

## In Progress

- Complete the next reviewed change.

## Usage

gpt-5 123 tokens
"""

    output = render_narrative(report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF)

    assert "Shipped the reviewed change." in output
    assert "Complete the next reviewed change." in output
    assert "ses-secret" not in output
    assert "src/iiwi/services/private.py" not in output
    assert "feature/internal-rollout" not in output
    assert "deadbeef" not in output
    assert "uv run deploy" not in output
    assert "Internal deployment evidence." not in output
    assert "gpt-5 123 tokens" not in output


def test_narrative_brief_rejects_whitespace_delimited_session_evidence() -> None:
    report = narrative_report()
    report.narrative_text = """## Outcomes

- Session ses_abc
- Safe reader-facing summary.
- The planning session clarified priorities.
- Session ID arbitrary-id
"""

    output = render_narrative(report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF)

    assert "Safe reader-facing summary." in output
    assert "The planning session clarified priorities." in output
    assert "Session ses_abc" not in output
    assert "Session ID arbitrary-id" not in output

    full_output = render_narrative(
        report, timezone="Asia/Taipei", detail=DetailLevel.FULL
    )

    assert "Session ses_abc" in full_output
    assert "Session ID arbitrary-id" in full_output


def test_narrative_brief_rejects_setext_technical_sections_and_space_delimited_evidence() -> None:
    report = narrative_report()
    report.narrative_text = """Outcomes
========

- Shipped the reviewed change.
- Commit deadbeef
- Branch feature/internal-rollout

Deployment Trace
----------------

Internal deployment evidence.

In Progress
-----------

- Complete the next reviewed change.
"""

    output = render_narrative(report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF)

    assert "Shipped the reviewed change." in output
    assert "Complete the next reviewed change." in output
    assert "Commit deadbeef" not in output
    assert "Branch feature/internal-rollout" not in output
    assert "Deployment Trace" not in output
    assert "Internal deployment evidence." not in output

    full_output = render_narrative(report, timezone="Asia/Taipei", detail=DetailLevel.FULL)

    assert "Deployment Trace" in full_output
    assert "Commit deadbeef" in full_output


def test_narrative_brief_rejects_setext_headings_inside_tilde_fences() -> None:
    report = narrative_report()
    report.narrative_text = """~~~markdown
Outcomes
========

- Internal deployment evidence.
~~~
"""

    output = render_narrative(report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF)

    assert "Outcomes" not in output
    assert "========" not in output
    assert "Internal deployment evidence." not in output


def test_narrative_brief_keeps_prose_that_reads_like_a_command() -> None:
    report = narrative_report()
    report.narrative_text = """## Outcomes

- We had to make a call on pricing and go with tiered plans.
- The team will go over the results with sales.
- Make the migration plan concrete.
- We make progress on the api/v2 endpoint.
"""

    output = render_narrative(report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF)

    assert "We had to make a call on pricing and go with tiered plans." in output
    assert "The team will go over the results with sales." in output
    assert "Make the migration plan concrete." in output
    assert "We make progress on the api/v2 endpoint." in output


def test_narrative_brief_rejects_ambiguous_commands_with_arguments() -> None:
    report = narrative_report()
    report.narrative_text = """## Outcomes

- Shipped the reviewed change.
make -j4 build
go test ./...
uv run pytest -q
$ docker compose up
"""

    output = render_narrative(report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF)

    assert "Shipped the reviewed change." in output
    assert "make -j4 build" not in output
    assert "go test" not in output
    assert "uv run pytest" not in output
    assert "docker compose up" not in output


def test_narrative_brief_drops_allowed_headings_left_without_content() -> None:
    report = narrative_report()
    report.narrative_text = """## Outcomes

- Shipped the reviewed change.

## Next Week

- Commit deadbeef

Blockers
--------

- Session: ses-secret
"""

    output = render_narrative(report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF)

    assert "Shipped the reviewed change." in output
    assert "## Outcomes" in output
    assert "Next Week" not in output
    assert "Blockers" not in output


def test_narrative_brief_keeps_allowed_headings_that_retain_a_line() -> None:
    report = narrative_report()
    report.narrative_text = """## Outcomes

- Commit deadbeef
- Shipped the reviewed change.

## Next Week

- Complete the next reviewed change.
"""

    output = render_narrative(report, timezone="Asia/Taipei", detail=DetailLevel.BRIEF)

    assert "## Outcomes" in output
    assert "Shipped the reviewed change." in output
    assert "## Next Week" in output
    assert "Complete the next reviewed change." in output
    assert "deadbeef" not in output


def test_narrative_full_keeps_usage() -> None:
    report = narrative_report()
    report.usage_text = "gpt-5 123 tokens"

    assert "## Usage" in render_narrative(
        report, timezone="Asia/Taipei", detail=DetailLevel.FULL
    )
