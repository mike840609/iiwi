from datetime import date, datetime
from io import StringIO

from rich.console import Console

from iiwi.interactive import controller, render
from iiwi.interactive.models import Screen
from iiwi.models.daily import (
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.models.outcome import EvidenceRef
from iiwi.renderers.daily_markdown import render_daily_standup


def _console(*, width: int = 100, height: int = 40) -> tuple[Console, StringIO]:
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


def _draft() -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=date(2026, 8, 13),
        scan_since=datetime.fromisoformat("2026-08-12T00:00:00+08:00"),
        scan_until=datetime.fromisoformat("2026-08-13T10:00:00+08:00"),
        fallback=True,
        work_items=[
            DailyStandupWorkItem(
                id="yesterday",
                repository_ids=["iiwi"],
                yesterday=DailySectionItem(
                    statement="Started the Daily Standup renderer",
                    source=DailyStatementSource.ACTIVITY_YESTERDAY,
                ),
            ),
            DailyStandupWorkItem(
                id="today",
                repository_ids=["iiwi"],
                today=DailySectionItem(
                    statement="Implement the Daily Standup renderer",
                    source=DailyStatementSource.ACTIVITY_TODAY,
                    new_activity=True,
                    evidence_refs=[
                        EvidenceRef(
                            harness="codex",
                            session_id="session-today",
                            repository_id="iiwi",
                            commit="abc1234",
                            file="src/iiwi/interactive/render.py",
                        )
                    ],
                ),
            ),
            DailyStandupWorkItem(
                id="suggested",
                repository_ids=["iiwi"],
                today=DailySectionItem(
                    statement="Continue with controller tests",
                    source=DailyStatementSource.SUGGESTED_FROM_YESTERDAY,
                    rank=1,
                ),
            ),
            DailyStandupWorkItem(
                id="blocker",
                blocker=DailySectionItem(
                    statement="Waiting for staging access",
                    source=DailyStatementSource.DETECTED_BLOCKER,
                ),
            ),
            DailyStandupWorkItem(
                id="manual",
                yesterday=DailySectionItem(
                    statement="Added review context",
                    source=DailyStatementSource.USER_ADDED,
                ),
            ),
        ],
    )


def test_daily_review_renders_provenance_and_only_approved_controls() -> None:
    console, stream = _console(height=60)

    render.render_daily_review(
        console,
        _draft(),
        cursor=4,
        expanded=set(),
    )

    text = stream.getvalue()
    for label in (
        "Activity today",
        "Suggested from yesterday",
        "Detected blocker",
        "User added",
        "New activity",
    ):
        assert label in text
    assert text.count("Fallback draft") == 1
    for hint in (
        "Space Include",
        "e Edit",
        "J/K Reorder",
        "v Evidence",
        "a Add",
        "p Preview",
        "g Generate",
        "b Back",
    ):
        assert hint in text
    assert "s Split" not in text
    assert "Activity yesterday" not in text
    assert "Report type" not in text
    assert "Detail" not in text
    assert "Next week" not in text


def test_daily_review_renders_source_coverage_warnings() -> None:
    """This fails if partial-source loss is visible only in the final artifact."""

    console, stream = _console(height=60)
    draft = _draft()
    draft.coverage_warnings = ["Claude Code activity could not be loaded."]

    render.render_daily_review(
        console,
        draft,
        cursor=0,
        expanded=set(),
    )

    assert "Claude Code activity could not be loaded." in stream.getvalue()


def test_daily_review_expanded_evidence_shows_source_references() -> None:
    console, stream = _console(height=60)

    render.render_daily_review(
        console,
        _draft(),
        cursor=4,
        expanded={"today"},
    )

    text = stream.getvalue()
    assert "Repository" in text and "iiwi" in text
    assert "Harness" in text and "codex" in text
    assert "Session" in text and "session-today" in text
    assert "Commit" in text and "abc1234" in text
    assert "File" in text and "src/iiwi/interactive/render.py" in text


def test_daily_review_controller_state_renders_without_outcome_review() -> None:
    console, stream = _console()
    state = controller._State(
        screen=Screen.DAILY_REVIEW,
        daily_review=_draft(),
        daily_cursor=4,
        daily_expanded=set(),
    )

    controller._render_screen(state, console)

    assert "Daily Standup" in stream.getvalue()
    assert "Implement the Daily Standup renderer" in stream.getvalue()


def test_daily_result_offers_main_and_report_path_only() -> None:
    console, stream = _console()

    render.render_daily_result(
        console,
        output_path=None,
        selected=0,
    )

    text = stream.getvalue()
    assert "Back to main menu" in text
    assert "Print report path" in text
    assert "Generate another report" not in text


def test_daily_statement_is_the_same_safe_single_line_in_review_and_artifact() -> None:
    draft = _draft()
    statement = "Shipped [the link](https://example.com)\n- hidden bullet\n*hidden emphasis* <tag>"
    expected = (
        r"Shipped \[the link\](https://example.com) - hidden bullet "
        r"\*hidden emphasis\* \<tag\>"
    )
    draft.work_items[0].yesterday.statement = statement  # type: ignore[union-attr]
    console, stream = _console(height=60)

    render.render_daily_review(console, draft, cursor=1, expanded=set())
    artifact = render_daily_standup(draft)

    assert expected in stream.getvalue()
    assert f"- [iiwi] {expected}\n" in artifact
    assert "\n- hidden bullet" not in artifact
    assert "\n*hidden emphasis*" not in artifact


def test_daily_review_redacts_raw_durable_provenance_before_display() -> None:
    draft = _draft()
    draft.work_items[1].repository_ids = ["token=repository-secret"]
    today = draft.work_items[1].today
    assert today is not None
    today.evidence_refs[0].session_id = "token=session-secret"
    console, stream = _console(height=60)

    render.render_daily_review(console, draft, cursor=4, expanded={"today"})

    text = stream.getvalue()
    assert "repository-secret" not in text
    assert "session-secret" not in text
    assert text.count("[REDACTED]") >= 2
