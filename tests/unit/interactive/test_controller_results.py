from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from iiwi.errors import OutcomeSynthesisError, ReportAlreadyExistsError
from iiwi.interactive import controller as interactive_controller
from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft, Screen
from iiwi.models.outcome import (
    EvidenceRef,
    Outcome,
    OutcomeReviewDraft,
    OutcomeStatus,
)
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


def _synthesized_outcomes() -> list[Outcome]:
    """Quick Review declines to generate with nothing included, so stub one outcome."""
    return [
        Outcome(
            id="outcome-1",
            title="Outcome 1",
            status=OutcomeStatus.IN_PROGRESS,
            impact="Impact",
            rank=0,
            evidence_refs=[EvidenceRef(session_id="ses-0", repository_id="repo-a")],
        )
    ]


def char(value: str) -> KeyPress:
    return KeyPress(char=value)


class ScriptedInput:
    def __init__(self, keys: list[KeyPress]) -> None:
        self._keys: Iterator[KeyPress] = iter(keys)

    def __enter__(self) -> ScriptedInput:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read_key(self) -> KeyPress:
        return next(self._keys)


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _activities(count: int = 5) -> list[SessionActivity]:
    """Real scans never yield activity-less sessions; keep fixtures substantive."""

    return [
        SessionActivity(activity_id=f"act-{i}", activity_type=ActivityType.USER_MESSAGE)
        for i in range(count)
    ]


def _scan() -> ScanResult:
    repository = RepositoryIdentity(
        repository_id="repo-a",
        display_name="repo-a",
        identity_type=RepositoryIdentityType.PATH_FALLBACK,
        working_directory="/tmp/repo-a",
        resolution_method="test",
    )
    resolved = ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="ses-a",
            title="Session A",
            working_directory="/tmp/repo-a",
            activities=_activities(),
        ),
        repository=repository,
    )
    return ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=[resolved],
        sessions_by_repository={"repo-a": [resolved]},
    )


def _console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return Console(file=stream, color_system=None, force_terminal=False, width=100), stream


def _actions() -> InteractiveActions:
    draft = ReportDraft(harness="opencode", period=_period())
    return InteractiveActions(
        new_draft=lambda: draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: ("Last week", _period()),
        scan=lambda current: _scan(),
        generate=lambda current, scan, force: InteractiveReportResult(
            output_path=Path("reports/worklog.md"),
            content="report",
            repository_count=1,
            session_count=1,
        ),
        synthesize=lambda draft, scan, force: OutcomeReviewDraft(
            outcomes=_synthesized_outcomes(), report_type=draft.report_type
        ),
        generate_reviewed=lambda draft, scan, review, force: InteractiveReportResult(
            output_path=None if draft.dry_run else Path("reports/worklog.md"),
            content="report",
            repository_count=1,
            session_count=1,
        ),
        edit_outcome=lambda outcome: outcome,
        add_outcome=lambda: None,
        edit_gap=lambda label, current: current,
        save_report_type=lambda report_type: None,
        doctor=lambda harness: ["OK opencode version: 1.0", "OK git: git version 2.0"],
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )


def test_doctor_result_uses_a_persistent_result_screen() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput([char("5"), KeyPress(key=Key.ENTER), char("q")]),
        console=console,
    )

    text = stream.getvalue()
    assert "Check Setup" in text
    assert "OK opencode version: 1.0" in text
    assert "OK git: git version 2.0" in text


def test_settings_entry_opens_the_settings_editor() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [
                char("6"),
                KeyPress(key=Key.ENTER),
                char("q"),
                char("q"),
            ]
        ),
        console=console,
    )

    text = stream.getvalue()
    assert "Settings" in text
    assert "Settings file:" in text
    assert "opencode.enabled" in text
    assert "true / false" in text


def test_print_report_path_opens_a_persistent_path_screen() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [
                char("3"),
                char("r"),
                char("g"),
                char("g"),
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.ENTER),
                char("b"),
                char("q"),
                char("q"),
            ]
        ),
        console=console,
    )

    text = stream.getvalue()
    assert "Report path" in text
    assert text.count("reports/worklog.md") >= 2


def test_p_opens_session_preview_from_review_and_back_returns_to_it() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [
                char("3"),
                char("r"),
                KeyPress(key=Key.RIGHT),
                KeyPress(key=Key.DOWN),
                char("p"),
                char("b"),
                char("b"),
                char("q"),
                char("q"),
            ]
        ),
        console=console,
    )

    text = stream.getvalue()
    assert "Session Preview" in text
    assert "Session A" in text


def test_p_opens_session_preview_from_activity_and_returns() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [
                char("1"),
                KeyPress(key=Key.RIGHT),
                KeyPress(key=Key.DOWN),
                char("p"),
                char("b"),
                char("q"),
                char("q"),
            ]
        ),
        console=console,
    )

    text = stream.getvalue()
    assert "Session Preview" in text


def test_p_on_a_repository_row_does_not_open_a_preview() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [
                char("3"),
                char("r"),
                char("p"),
                char("b"),
                char("b"),
                char("q"),
            ]
        ),
        console=console,
    )

    text = stream.getvalue()
    assert "Session Preview" not in text


def test_stale_fallback_notice_does_not_reach_later_reports() -> None:
    """A failed fallback attempt must not pin its notice onto later generates.

    The fallback notice is scoped to one attempt: the generate it rides into
    consumes it as an initial warning. When that attempt fails and the user
    backs out, a later unrelated successful generate must start clean instead
    of embedding "Outcome synthesis unavailable" without a retry ever running.
    """

    console, _stream = _console()
    generate_notices: list[str | None] = []

    def flaky_generate(
        current: ReportDraft, scan: ScanResult, force: bool
    ) -> InteractiveReportResult:
        generate_notices.append(current.generation_notice)
        if len(generate_notices) == 1:
            raise ReportAlreadyExistsError("reports/worklog.md already exists")
        return InteractiveReportResult(
            output_path=Path("reports/worklog.md"),
            content="report",
            repository_count=1,
            session_count=1,
        )

    def failed_synthesis(
        draft: ReportDraft, scan: ScanResult, force: bool
    ) -> OutcomeReviewDraft:
        raise OutcomeSynthesisError("narration CLI failed")

    actions = replace(
        _actions(),
        generate=flaky_generate,
        synthesize=failed_synthesis,
    )

    run_interactive(
        actions=actions,
        input_source=ScriptedInput(
            [
                char("3"),  # Generate Report setup
                char("r"),  # Quick Review session tree
                char("g"),  # synthesis fails -> recoverable error screen
                KeyPress(key=Key.DOWN),  # select "Use session-based report"
                KeyPress(key=Key.ENTER),  # fallback generate hits output conflict
                char("b"),  # Back to the session tree
                char("b"),  # Back to report setup
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.DOWN),  # cursor on "Advanced settings"
                KeyPress(key=Key.ENTER),  # reveal the advanced rows
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.DOWN),  # cursor on "Narrative"
                KeyPress(key=Key.RIGHT),  # narrative off: g generates directly
                char("r"),  # back into the session tree
                char("g"),  # plain successful session-based generate
                char("q"),  # result -> main menu
                char("q"),  # exit
            ]
        ),
        console=console,
    )

    assert len(generate_notices) == 2
    assert generate_notices[0] == (
        "Outcome synthesis unavailable; generated the session-based report."
    )
    assert generate_notices[1] is None


def test_report_preview_scroll_survives_a_session_preview_roundtrip() -> None:
    """A session preview's scrolling must leave the report preview's offset alone."""
    console, _ = _console()
    state = interactive_controller._State(
        screen=Screen.REPORT_PREVIEW,
        result=InteractiveReportResult(
            output_path=None,
            content="\n".join(f"report line {i}" for i in range(60)),
            repository_count=1,
            session_count=1,
        ),
        preview_return_screen=Screen.OUTCOME_REVIEW,
    )
    for _ in range(5):
        interactive_controller._preview_key(state, KeyPress(key=Key.DOWN), console)
    assert state.preview_offset == 5

    session = _scan().resolved_sessions[0].session
    interactive_controller._open_session_preview(
        state, session, return_screen=Screen.SESSION_REVIEW
    )
    assert state.screen is Screen.SESSION_PREVIEW
    interactive_controller._session_preview_key(state, KeyPress(key=Key.DOWN), console)
    interactive_controller._session_preview_key(state, KeyPress(key=Key.HOME), console)

    assert state.preview_offset == 5
