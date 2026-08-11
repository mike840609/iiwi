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
    ("report_type", "heading"),
    [
        (ReportType.MANAGER, "# Weekly Work Update"),
        (ReportType.ENGINEERING, "# Engineering Worklog"),
    ],
)
def test_report_type_controls_heading_and_sections(
    report_type: ReportType, heading: str
) -> None:
    output = render(report_type=report_type, detail=DetailLevel.BRIEF)

    assert output.startswith(heading)
    assert "## Outcomes" in output
    assert "## In Progress" in output
    assert "## Blockers" in output
    assert "## Next Week" in output


def test_report_type_changes_audience_text_beyond_the_heading() -> None:
    manager = render(report_type=ReportType.MANAGER, detail=DetailLevel.BRIEF)
    engineering = render(report_type=ReportType.ENGINEERING, detail=DetailLevel.BRIEF)

    assert "**Audience:** Manager update" in manager
    assert "**Audience:** Engineering worklog" in engineering
    assert manager != engineering


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
