from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from iiwi.errors import ReportAlreadyExistsError
from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft
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


def _console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(file=stream, color_system=None, force_terminal=False, width=100),
        stream,
    )


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


def _resolved(session_id: str, repository_id: str) -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id=session_id,
            title=session_id,
            working_directory=f"/tmp/{repository_id}",
            activities=_activities(),
        ),
        repository=RepositoryIdentity(
            repository_id=repository_id,
            display_name=repository_id,
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory=f"/tmp/{repository_id}",
            resolution_method="test",
        ),
    )


def _scan() -> ScanResult:
    sessions = [
        _resolved("ses-a1", "repo-a"),
        _resolved("ses-a2", "repo-a"),
        _resolved("ses-b1", "repo-b"),
    ]
    return ScanResult(
        period=_period(),
        candidate_session_count=3,
        loaded_session_count=3,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions[:2], "repo-b": sessions[2:]},
    )


def _actions(
    *,
    draft: ReportDraft,
    scan_calls: list[ScanResult],
    generation_calls: list[tuple[ScanResult, bool]],
    generate_callback=None,
) -> InteractiveActions:
    scan = _scan()

    def do_scan(_draft: ReportDraft) -> ScanResult:
        scan_calls.append(scan)
        return scan

    def generate(
        _draft: ReportDraft,
        selected_scan: ScanResult,
        force: bool,
    ) -> InteractiveReportResult:
        generation_calls.append((selected_scan, force))
        if generate_callback is not None:
            return generate_callback(selected_scan, force)
        return InteractiveReportResult(
            output_path=Path("reports/worklog.md"),
            content="report-content",
            repository_count=len(selected_scan.sessions_by_repository),
            session_count=selected_scan.loaded_session_count,
        )

    return InteractiveActions(
        new_draft=lambda: draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: ("Last week", _period()),
        scan=do_scan,
        generate=generate,
        synthesize=lambda draft, scan: OutcomeReviewDraft(
            outcomes=_synthesized_outcomes(), report_type=draft.report_type
        ),
        generate_reviewed=lambda draft, scan, review, force: generate(
            draft, scan, force
        ),
        edit_outcome=lambda outcome: outcome,
        add_outcome=lambda: None,
        edit_gap=lambda label, current: current,
        save_report_type=lambda report_type: None,
        doctor=lambda harness: [],
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )


def test_repository_and_individual_toggles_filter_generation_without_rescan() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    scan_calls: list[ScanResult] = []
    generation_calls: list[tuple[ScanResult, bool]] = []
    console, _ = _console()
    keys = ScriptedInput(
        [
            char("3"),
            char("r"),
            KeyPress(key=Key.SPACE),
            KeyPress(key=Key.ENTER),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.SPACE),
            char("g"),
            char("g"),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(
            draft=draft,
            scan_calls=scan_calls,
            generation_calls=generation_calls,
        ),
        input_source=keys,
        console=console,
    )

    assert len(scan_calls) == 1
    assert len(generation_calls) == 1
    selected_scan, force = generation_calls[0]
    assert force is False
    assert [item.session.session_id for item in selected_scan.resolved_sessions] == [
        "ses-a1",
        "ses-b1",
    ]


def test_zero_selection_blocks_generate_until_sessions_are_selected() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    scan_calls: list[ScanResult] = []
    generation_calls: list[tuple[ScanResult, bool]] = []
    console, stream = _console()
    keys = ScriptedInput(
        [
            char("3"),
            char("r"),
            char("n"),
            char("g"),
            char("a"),
            char("g"),
            char("g"),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(
            draft=draft,
            scan_calls=scan_calls,
            generation_calls=generation_calls,
        ),
        input_source=keys,
        console=console,
    )

    assert len(generation_calls) == 1
    assert "Select at least one session" in stream.getvalue()


def test_existing_output_requires_explicit_overwrite_once() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    scan_calls: list[ScanResult] = []
    generation_calls: list[tuple[ScanResult, bool]] = []

    def generate(selected_scan: ScanResult, force: bool) -> InteractiveReportResult:
        if not force:
            raise ReportAlreadyExistsError("report already exists: reports/worklog.md")
        return InteractiveReportResult(
            output_path=Path("reports/worklog.md"),
            content="report-content",
            repository_count=len(selected_scan.sessions_by_repository),
            session_count=selected_scan.loaded_session_count,
        )

    console, stream = _console()
    keys = ScriptedInput(
        [
            char("3"),
            char("r"),
            char("g"),
            char("g"),
            KeyPress(key=Key.ENTER),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(
            draft=draft,
            scan_calls=scan_calls,
            generation_calls=generation_calls,
            generate_callback=generate,
        ),
        input_source=keys,
        console=console,
    )

    assert [force for _, force in generation_calls] == [False, True]
    assert "Overwrite once" in stream.getvalue()


def test_generate_another_preserves_options_but_clears_scan_and_selection() -> None:
    draft = ReportDraft(harness="opencode", period=_period(), narrative=False)
    scan_calls: list[ScanResult] = []
    generation_calls: list[tuple[ScanResult, bool]] = []
    console, _ = _console()
    keys = ScriptedInput(
        [
            char("3"),
            char("r"),
            char("g"),
            char("g"),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(
            draft=draft,
            scan_calls=scan_calls,
            generation_calls=generation_calls,
        ),
        input_source=keys,
        console=console,
    )

    assert draft.narrative is False
    assert draft.scan is None
    assert draft.selected_session_ids == set()


def test_result_print_path_action_keeps_result_screen_active() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    scan_calls: list[ScanResult] = []
    generation_calls: list[tuple[ScanResult, bool]] = []
    console, stream = _console()
    keys = ScriptedInput(
        [
            char("3"),
            char("r"),
            char("g"),
            char("g"),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(
            draft=draft,
            scan_calls=scan_calls,
            generation_calls=generation_calls,
        ),
        input_source=keys,
        console=console,
    )

    assert stream.getvalue().count("reports/worklog.md") >= 2
