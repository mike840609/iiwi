from __future__ import annotations

from datetime import date, datetime
from io import StringIO
from zoneinfo import ZoneInfo

from rich.console import Console

from iiwi.interactive import render
from iiwi.interactive.render import (
    build_visible_rows,
    render_report_preview,
    render_session_review,
)
from iiwi.interactive.selection import SelectionState
from iiwi.models.daily import (
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.models.outcome import (
    EvidenceRef,
    Outcome,
    OutcomeBucket,
    OutcomeReviewDraft,
    OutcomeStatus,
)
from iiwi.models.report_options import ReportType
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import AgentSession
from iiwi.models.time_range import DateRange
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


def _console(*, width: int = 40, height: int = 20) -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(
            file=stream,
            color_system=None,
            force_terminal=False,
            width=width,
            height=height,
        ),
        stream,
    )


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _scan(count: int, *, long_titles: bool = False) -> ScanResult:
    sessions: list[ResolvedSession] = []
    for index in range(count):
        title = (
            f"Session {index} " + "very-long-branch-or-commit-title-" * 5
            if long_titles
            else f"Session {index}"
        )
        sessions.append(
            ResolvedSession(
                session=AgentSession(
                    harness="opencode",
                    session_id=f"ses-{index}",
                    title=title,
                    working_directory="/tmp/repo-a",
                ),
                repository=RepositoryIdentity(
                    repository_id="repo-a",
                    display_name="repo-a",
                    identity_type=RepositoryIdentityType.PATH_FALLBACK,
                    working_directory="/tmp/repo-a",
                    resolution_method="test",
                ),
            )
        )
    return ScanResult(
        period=_period(),
        candidate_session_count=count,
        loaded_session_count=count,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )


def _display_lines(stream: StringIO) -> list[str]:
    return stream.getvalue().splitlines()


def _long_daily_review() -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=date(2026, 8, 13),
        scan_since=_period().since,
        scan_until=_period().until,
        fallback=True,
        work_items=[
            DailyStandupWorkItem(
                id=f"daily-{index}",
                repository_ids=["very-long-repository-name-" * 5],
                today=DailySectionItem(
                    statement=f"Daily {index}\n\n" + "very-long-statement-" * 12,
                    source=DailyStatementSource.ACTIVITY_TODAY,
                    rank=index,
                    new_activity=True,
                    evidence_refs=[
                        EvidenceRef(
                            harness="codex",
                            session_id="very-long-session-id-" * 8,
                            repository_id="very-long-repository-name-" * 5,
                            commit="deadbeef" * 8,
                            file="deeply-nested-directory/" * 8 + "daily.py",
                        )
                    ],
                ),
            )
            for index in range(12)
        ],
    )


def test_daily_review_narrow_short_viewport_keeps_focus_and_hints_visible() -> None:
    review = _long_daily_review()
    rows = render.visible_daily_review_rows(review, set())

    for width in (40, 60):
        for height in (14, 16, 20):
            for cursor in (0, len(rows) // 2, len(rows) - 1):
                console, stream = _console(width=width, height=height)
                render.render_daily_review(
                    console,
                    review,
                    cursor=cursor,
                    expanded={"daily-5"},
                )
                lines = _display_lines(stream)
                assert len(lines) <= height - 1, (width, height, cursor)
                assert any("▶" in line for line in lines), (width, height, cursor)
                assert any(
                    "p Preview" in line or "g Generate" in line for line in lines
                ), (width, height, cursor)
                assert all(len(line) <= width for line in lines), (width, height, cursor)


def test_daily_review_many_warnings_stay_within_the_viewport_budget() -> None:
    """A scan across three harnesses emits one warning per unusable session.

    Twenty-five is an ordinary day, and every one of them used to print, so the
    frame overflowed the terminal no matter what the body capacity clamped to.
    """

    review = _long_daily_review()
    review.coverage_warnings = ["Codex activity could not be loaded."]
    review.warnings = [f"Session {index} has no timestamps." for index in range(25)]

    for height in (14, 20, 24):
        console, stream = _console(width=80, height=height)
        render.render_daily_review(console, review, cursor=0, expanded=set())
        lines = _display_lines(stream)
        assert len(lines) <= height - 1, height
        # The harness outage is the one warning that must never be collapsed.
        assert any("Codex activity could not be loaded." in line for line in lines)
        assert any("more warning(s) not shown" in line for line in lines)


def test_daily_summary_collapses_newlines_and_uses_ellipsis_instead_of_wrapping() -> None:
    console, stream = _console(width=40, height=20)

    render.render_daily_review(
        console,
        _long_daily_review(),
        cursor=2,
        expanded=set(),
    )

    statement_lines = [
        line for line in _display_lines(stream) if "Daily 0" in line
    ]
    assert len(statement_lines) == 1
    assert "…" in statement_lines[0]


def test_session_review_long_titles_do_not_exceed_terminal_display_budget() -> None:
    console, stream = _console(width=40, height=20)
    selection = SelectionState.from_scan(_scan(12, long_titles=True))

    render_session_review(
        console,
        selection,
        expanded_repositories={"repo-a"},
        cursor=12,
    )

    assert len(_display_lines(stream)) <= console.size.height - 1
    rows = build_visible_rows(selection.scan, {"repo-a"})
    cursor_row = rows[12]
    assert cursor_row.session_id is not None
    titles = {
        item.session.session_id: item.session.title
        for item in selection.scan.resolved_sessions
    }
    assert titles[cursor_row.session_id][:10] in stream.getvalue()


def test_report_preview_long_lines_do_not_exceed_terminal_display_budget() -> None:
    console, stream = _console(width=40, height=20)
    content = "\n".join(
        f"Line {index} " + "long-report-content-" * 8
        for index in range(20)
    )

    render_report_preview(console, content=content, offset=5)

    assert len(_display_lines(stream)) <= console.size.height - 1
    assert "Line 5" in stream.getvalue()


def test_session_review_reserves_last_terminal_line_when_both_indicators_show() -> None:
    console, stream = _console(width=100, height=12)
    selection = SelectionState.from_scan(_scan(20))

    render_session_review(
        console,
        selection,
        expanded_repositories={"repo-a"},
        cursor=10,
    )

    text = stream.getvalue()
    assert "↑ " in text
    assert "↓ " in text
    assert len(_display_lines(stream)) <= console.size.height - 1


def test_report_preview_reserves_last_terminal_line_when_both_indicators_show() -> None:
    console, stream = _console(width=100, height=12)
    content = "\n".join(f"Line {index}" for index in range(30))

    render_report_preview(console, content=content, offset=10)

    text = stream.getvalue()
    assert "↑ " in text
    assert "↓ " in text
    assert len(_display_lines(stream)) <= console.size.height - 1


def _bucketed_outcome_review() -> OutcomeReviewDraft:
    """A review with content in all three sections, every field wider than 140 cells."""

    buckets = (
        [OutcomeBucket.PRIMARY] * 4
        + [OutcomeBucket.MORE] * 3
        + [OutcomeBucket.UNGROUPED] * 2
    )
    outcomes = [
        Outcome(
            id=f"outcome-{index}",
            title=f"Outcome {index}\n\n" + "very-long-title-" * 10,
            status=OutcomeStatus.IN_PROGRESS,
            impact="A long impact explanation\n" + "continues-across-lines-" * 12,
            rank=index,
            bucket=bucket,
            evidence_refs=[
                EvidenceRef(
                    session_id=f"session-{index}-" + "long-session-id-" * 6,
                    repository_id="repository-\n" + "long-repository-name-" * 8,
                    commit="deadbeef" * 8,
                    file="src/\n" + "deeply-nested-directory/" * 8 + "renderer.py",
                )
            ],
        )
        for index, bucket in enumerate(buckets)
    ]
    return OutcomeReviewDraft(
        outcomes=outcomes,
        report_type=ReportType.MANAGER,
        blockers="Blocked by\n\n" + "long-blocker-detail-" * 12,
        next_week="Next week\n\n" + "long-plan-detail-" * 12,
    )


def test_interactive_screens_fit_every_reasonable_terminal_size() -> None:
    """Chrome grew a rule, a subtitle and a wrapping status bar; none may crowd out the list.

    Fourteen rows is the floor these screens guarantee: below it the fixed chrome alone
    can exceed the terminal. Above it, every size must render inside its budget with the
    cursor row on screen.

    Quick Review is measured in all three of its expansion states, because what the
    focused block costs depends on them: at 40x14 with both disclosure sections open
    the focused outcome alone used to outrun the whole body budget.
    """

    scan = _scan(12, long_titles=True)
    selection = SelectionState.from_scan(scan)
    expanded = {"repo-a"}
    rows = build_visible_rows(scan, expanded)
    review = _bucketed_outcome_review()
    expansion_states = (
        set(),
        {review.ordered()[0].id},
        {render.MORE_CANDIDATES_SECTION, render.UNGROUPED_CANDIDATES_SECTION},
    )

    for width in (40, 60, 80, 100, 140):
        for height in (14, 16, 20, 24, 40):
            for cursor in (0, len(rows) // 2, len(rows) - 1):
                console, stream = _console(width=width, height=height)
                render_session_review(
                    console, selection, expanded_repositories=expanded, cursor=cursor
                )
                lines = _display_lines(stream)
                assert len(lines) <= height - 1, (width, height, cursor)
                assert any("▶" in line for line in lines), (width, height, cursor)

            for expansions in expansion_states:
                review_rows = render.visible_outcome_review_rows(review, expansions)
                for cursor in (0, len(review_rows) // 2, len(review_rows) - 1):
                    where = (width, height, cursor, sorted(expansions))
                    console, stream = _console(width=width, height=height)
                    render.render_outcome_review(
                        console,
                        review,
                        cursor=cursor,
                        expanded_evidence=expansions,
                    )
                    lines = _display_lines(stream)
                    assert len(lines) <= height - 1, where
                    assert any("▶" in line for line in lines), where


def test_help_fits_every_reasonable_terminal_size() -> None:
    """The reference grew a Quick Review section; it scrolls rather than overflowing."""

    for width in (40, 60, 80, 100, 140):
        for height in (14, 16, 20, 24, 40):
            console, stream = _console(width=width, height=height)
            render.render_help(console)
            lines = _display_lines(stream)
            assert len(lines) <= height - 1, (width, height)
            assert any("Keyboard shortcuts" in line for line in lines), (width, height)


def _long_outcome_review() -> OutcomeReviewDraft:
    outcomes = [
        Outcome(
            id=f"outcome-{index}",
            title=f"Outcome {index}\n\n\n" + "very-long-title-" * 10,
            status=OutcomeStatus.IN_PROGRESS,
            impact=(
                "A long impact explanation\n"
                + "continues-across-rendered-lines-" * 12
            ),
            rank=index,
            evidence_refs=[
                EvidenceRef(
                    session_id=f"session-{index}-" + "long-session-id-" * 6,
                    repository_id="repository-\n" + "long-repository-name-" * 8,
                    commit="deadbeef" * 8,
                    file=(
                        "src/\n" + "deeply-nested-directory/" * 8 + "renderer.py"
                    ),
                )
            ],
        )
        for index in range(12)
    ]
    return OutcomeReviewDraft(
        outcomes=outcomes,
        report_type=ReportType.MANAGER,
        blockers="Blocked by\n\n\n" + "long-blocker-detail-" * 12,
        next_week="Next week\n\n\n" + "long-plan-detail-" * 12,
    )


def test_outcome_review_fits_width_height_and_focus_matrix() -> None:
    review = _long_outcome_review()
    rows = render.outcome_review_rows(review)
    focuses = (0, len(rows) // 2, len(rows) - 1)
    expanded = {outcome.id for outcome in review.outcomes}
    error = "Could not refresh review:\n\n\n" + "long-error-detail-" * 20

    for width in (40, 60, 80, 100, 140):
        for height in (20, 24, 30):
            for cursor in focuses:
                console, stream = _console(width=width, height=height)
                render.render_outcome_review(
                    console,
                    review,
                    cursor=cursor,
                    expanded_evidence=expanded,
                    message=error,
                )

                lines = stream.getvalue().splitlines()
                assert len(lines) <= height - 1, (width, height, cursor)
                assert any("Quick Review" in line for line in lines), (width, height, cursor)
                assert any("▶" in line for line in lines), (width, height, cursor)
                assert any(
                    "p Preview" in line or "g Generate" in line for line in lines
                ), (width, height, cursor)
