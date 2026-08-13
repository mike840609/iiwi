from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from iiwi.models.outcome import EvidenceRef, Outcome, OutcomeOrigin, OutcomeStatus
from iiwi.models.report import WorklogReport
from iiwi.models.report_options import DetailLevel, ReportType
from iiwi.models.time_range import DateRange
from iiwi.renderers.markdown import MarkdownRenderer

TZ = ZoneInfo("Asia/Taipei")


def review_report(*, report_type: ReportType = ReportType.ENGINEERING) -> WorklogReport:
    return WorklogReport(
        generated_at=datetime(2026, 8, 10, 9, 30, tzinfo=TZ),
        period=DateRange(
            since=datetime(2026, 8, 3, tzinfo=TZ),
            until=datetime(2026, 8, 10, tzinfo=TZ),
        ),
        repositories=[],
        report_type=report_type,
        outcomes=[
            Outcome(
                id="completed",
                title="Delivered reviewed report rendering",
                status=OutcomeStatus.COMPLETED,
                impact="Made weekly updates reviewable.",
                rank=0,
                evidence_refs=[
                    EvidenceRef(
                        session_id="ses-a",
                        repository_id="repo-a",
                        commit="abc123",
                        file="src/iiwi/services/report.py",
                    ),
                    EvidenceRef(session_id="ses-b", repository_id="repo-a"),
                ],
            ),
            Outcome(
                id="in-progress",
                title="Finish parity coverage",
                status=OutcomeStatus.IN_PROGRESS,
                rank=1,
                origin=OutcomeOrigin.USER_ADDED,
            ),
        ],
        blockers="Need final review.",
        next_week="Exercise the reviewed path.",
        usage_text="gpt-5 123 tokens",
        usage_days=7,
    )


def render(*, report_type: ReportType, detail: DetailLevel) -> str:
    return MarkdownRenderer().render_outcomes(
        review_report(report_type=report_type), detail=detail
    )


def render_without_gaps() -> str:
    report = review_report()
    report.blockers = None
    report.next_week = None
    return MarkdownRenderer().render_outcomes(report, detail=DetailLevel.BRIEF)


@pytest.mark.parametrize(
    ("report_type", "heading", "completed_heading", "progress_heading"),
    [
        (
            ReportType.MANAGER,
            "# Weekly Work Update",
            "## Outcomes and Impact",
            "## Priorities in Progress",
        ),
        (
            ReportType.ENGINEERING,
            "# Engineering Worklog",
            "## Engineering Outcomes",
            "## Implementation Progress",
        ),
    ],
)
def test_report_type_controls_heading_and_sections(
    report_type: ReportType,
    heading: str,
    completed_heading: str,
    progress_heading: str,
) -> None:
    output = render(report_type=report_type, detail=DetailLevel.BRIEF)

    assert output.startswith(heading)
    assert completed_heading in output
    assert progress_heading in output
    assert "## Blockers" in output
    assert "## Next Week" in output


def test_report_type_changes_audience_text_beyond_the_heading() -> None:
    manager = render(report_type=ReportType.MANAGER, detail=DetailLevel.BRIEF)
    engineering = render(report_type=ReportType.ENGINEERING, detail=DetailLevel.BRIEF)

    assert "**Audience:** Manager update" in manager
    assert "**Audience:** Engineering worklog" in engineering
    assert manager != engineering


def test_report_type_renders_audience_specific_status_view() -> None:
    manager = render(report_type=ReportType.MANAGER, detail=DetailLevel.BRIEF)
    engineering = render(report_type=ReportType.ENGINEERING, detail=DetailLevel.BRIEF)

    assert "**Status view:** Decisions, blockers, and next steps" in manager
    assert "**Status view:** Implementation progress and verification" in engineering


def test_report_type_and_detail_have_independent_rendering_responsibilities() -> None:
    outputs = {
        (report_type, detail): render(report_type=report_type, detail=detail)
        for report_type in ReportType
        for detail in DetailLevel
    }

    for detail in DetailLevel:
        manager = outputs[(ReportType.MANAGER, detail)]
        engineering = outputs[(ReportType.ENGINEERING, detail)]
        assert "## Outcomes and Impact" in manager
        assert "## Priorities in Progress" in manager
        assert "## Engineering Outcomes" not in manager
        assert "## Implementation Progress" not in manager
        assert "## Engineering Outcomes" in engineering
        assert "## Implementation Progress" in engineering
        assert "## Outcomes and Impact" not in engineering
        assert "## Priorities in Progress" not in engineering

    for report_type in ReportType:
        brief = outputs[(report_type, DetailLevel.BRIEF)]
        full = outputs[(report_type, DetailLevel.FULL)]
        assert brief == full.partition("### Evidence")[0].rstrip() + "\n"
        assert "### Evidence" not in brief
        assert "## Usage" not in brief
        assert "### Evidence" in full
        assert "## Usage" in full

    for output in outputs.values():
        assert "Delivered reviewed report rendering" in output
        assert "Made weekly updates reviewable." in output
        assert "Finish parity coverage" in output
        assert "Need final review." in output
        assert "Exercise the reviewed path." in output


def test_empty_impact_is_marked_as_unsupported() -> None:
    output = render(report_type=ReportType.MANAGER, detail=DetailLevel.BRIEF)

    assert "Finish parity coverage" in output
    assert "Impact: Unsupported by extracted evidence" in output


def test_brief_hides_session_file_and_commit_evidence() -> None:
    output = render(report_type=ReportType.MANAGER, detail=DetailLevel.BRIEF)

    assert "ses-a" not in output
    assert "src/iiwi/services/report.py" not in output


def test_full_groups_evidence_by_repository() -> None:
    output = render(report_type=ReportType.ENGINEERING, detail=DetailLevel.FULL)

    assert "### Evidence" in output
    assert "repo-a" in output
    assert "ses-a" in output


def test_empty_optional_sections_are_omitted() -> None:
    output = render_without_gaps()

    assert "## Blockers" not in output
    assert "## Next Week" not in output


def test_full_evidence_redacts_credentials_in_every_reference_field() -> None:
    """EvidenceRef carries raw provenance so reconciliation can match on it.

    The outcomes template writes all four of its fields verbatim, so it is the
    last point before the artifact exists and has to redact.
    """

    report = review_report()
    report.outcomes[0].evidence_refs = [
        EvidenceRef(
            session_id="ses-ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            repository_id="git:example.com/token=ghp_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            commit="sk-cccccccccccccccccccc",
            file="src/AKIAIOSFODNN7EXAMPLE.pem",
        )
    ]

    output = MarkdownRenderer().render_outcomes(report, detail=DetailLevel.FULL)

    assert "### Evidence" in output
    assert "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in output
    assert "ghp_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" not in output
    assert "sk-cccccccccccccccccccc" not in output
    assert "AKIAIOSFODNN7EXAMPLE" not in output
