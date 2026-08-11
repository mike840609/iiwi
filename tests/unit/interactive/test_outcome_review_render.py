from __future__ import annotations

from io import StringIO

from rich.console import Console

from iiwi.interactive import controller, render
from iiwi.interactive.models import Screen
from iiwi.models.outcome import (
    EvidenceRef,
    Outcome,
    OutcomeBucket,
    OutcomeOrigin,
    OutcomeReviewDraft,
    OutcomeStatus,
)
from iiwi.models.report_options import ReportType


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


def _outcome(
    identifier: str,
    title: str,
    rank: int,
    *,
    bucket: OutcomeBucket = OutcomeBucket.PRIMARY,
    included: bool = True,
    origin: OutcomeOrigin = OutcomeOrigin.SYNTHESIZED,
    impact: str = "",
    evidence_refs: list[EvidenceRef] | None = None,
) -> Outcome:
    refs = evidence_refs
    if refs is None and origin is OutcomeOrigin.SYNTHESIZED:
        refs = [EvidenceRef(session_id=f"session-{identifier}", repository_id="repo-a")]
    return Outcome(
        id=identifier,
        title=title,
        status=OutcomeStatus.IN_PROGRESS,
        impact=impact,
        included=included,
        rank=rank,
        origin=origin,
        bucket=bucket,
        evidence_refs=refs or [],
    )


def _review() -> OutcomeReviewDraft:
    return OutcomeReviewDraft(
        report_type=ReportType.MANAGER,
        outcomes=[
            _outcome(
                "primary-a",
                "Shipped the evidence-first review",
                0,
                impact="Managers can verify progress before publishing.",
                evidence_refs=[
                    EvidenceRef(
                        session_id="session-primary-a",
                        repository_id="iiwi",
                        commit="abc1234",
                        file="src/iiwi/interactive/render.py",
                    )
                ],
            ),
            _outcome(
                "primary-b",
                "Kept the existing repaint loop",
                1,
                impact="Interactive screens remain stable.",
            ),
            _outcome(
                "manual",
                "Added release context",
                2,
                origin=OutcomeOrigin.USER_ADDED,
                impact="Readers understand the rollout.",
            ),
            _outcome(
                "more",
                "Polished secondary copy",
                3,
                bucket=OutcomeBucket.MORE,
                included=False,
            ),
            _outcome(
                "ungrouped",
                "Investigated an unmatched session",
                4,
                bucket=OutcomeBucket.UNGROUPED,
                included=False,
            ),
        ],
        blockers="Waiting for review",
        next_week="Ship the renderer",
    )


def test_outcome_review_rows_follow_the_review_hierarchy() -> None:
    rows = render.outcome_review_rows(_review())

    assert [(row.kind, row.outcome_id) for row in rows] == [
        ("settings", None),
        ("outcome", "primary-a"),
        ("outcome", "primary-b"),
        ("outcome", "manual"),
        ("more", None),
        ("outcome", "more"),
        ("ungrouped", None),
        ("outcome", "ungrouped"),
        ("blockers", None),
        ("next_week", None),
        ("preview", None),
        ("generate", None),
    ]


def test_outcome_review_renders_visual_hierarchy_and_controls() -> None:
    console, stream = _console(height=50)

    render.render_outcome_review(
        console,
        _review(),
        cursor=1,
        expanded_evidence=set(),
    )

    text = stream.getvalue()
    assert "Quick Review" in text
    assert "Manager" in text and "Brief" in text
    assert "3 selected" in text
    assert "More candidates" in text
    assert "Blockers" in text and "Next week" in text
    assert "Space Include" in text
    assert "e Edit" in text
    assert "J/K Reorder" in text
    assert "v Evidence" in text
    assert "s Split" in text
    assert "a Add" in text
    assert "p Preview" in text and "g Generate" in text


def test_only_the_focused_outcome_expands_beyond_one_display_line() -> None:
    console, stream = _console()

    render.render_outcome_review(
        console,
        _review(),
        cursor=1,
        expanded_evidence=set(),
    )

    lines = stream.getvalue().splitlines()
    assert sum("Kept the existing repaint loop" in line for line in lines) == 1
    assert "Interactive screens remain stable." not in stream.getvalue()
    assert "Status" in stream.getvalue() and "In progress" in stream.getvalue()
    assert "Impact" in stream.getvalue()
    assert "Managers can verify progress before publishing." in stream.getvalue()
    assert "Evidence" in stream.getvalue() and "1 reference" in stream.getvalue()


def test_expanded_focused_evidence_adds_repository_session_and_file_rows() -> None:
    collapsed_console, collapsed_stream = _console()
    expanded_console, expanded_stream = _console()
    review = _review()

    render.render_outcome_review(
        collapsed_console,
        review,
        cursor=1,
        expanded_evidence=set(),
    )
    render.render_outcome_review(
        expanded_console,
        review,
        cursor=1,
        expanded_evidence={"primary-a"},
    )

    collapsed = collapsed_stream.getvalue()
    expanded = expanded_stream.getvalue()
    assert "Repository  iiwi" not in collapsed
    assert "Repository  iiwi" in expanded
    assert "Session     session-primary-a" in expanded
    assert "File        src/iiwi/interactive/render.py" in expanded


def test_user_added_and_ungrouped_outcomes_are_visibly_labelled() -> None:
    console, stream = _console(height=50)

    render.render_outcome_review(
        console,
        _review(),
        cursor=3,
        expanded_evidence={"__ungrouped_candidates__"},
    )

    text = stream.getvalue()
    assert "Added release context" in text and "User-added" in text
    assert "Investigated an unmatched session" in text and "Ungrouped" in text


def test_controller_outcome_review_state_renders_quick_review_with_focus() -> None:
    console, stream = _console()
    state = controller._State(
        screen=Screen.OUTCOME_REVIEW,
        outcome_review=_review(),
        outcome_cursor=1,
        expanded_evidence=set(),
    )

    controller._render_screen(state, console)

    text = stream.getvalue()
    assert "Quick Review" in text
    assert "▶" in text
    assert "Shipped the evidence-first review" in text
