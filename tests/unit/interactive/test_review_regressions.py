from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from iiwi.errors import IiwiError
from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft
from iiwi.interactive.render import render_report_setup, render_session_review
from iiwi.interactive.selection import SelectionState
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


def _console(*, height: int = 30) -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(
            file=stream,
            color_system=None,
            force_terminal=False,
            width=100,
            height=height,
        ),
        stream,
    )


def _period(day: int = 3) -> DateRange:
    return DateRange(
        since=datetime(2026, 8, day, tzinfo=TZ),
        until=datetime(2026, 8, day + 7, tzinfo=TZ),
    )


def _activities(count: int = 5, *, at: datetime | None = None) -> list[SessionActivity]:
    """Real scans never yield activity-less or undated sessions; keep fixtures substantive.

    filter_session_to_period drops every activity without a timestamp, so a
    dateless activity cannot survive a scan and must not stand in for one here.
    """

    moment = at or datetime(2026, 8, 5, tzinfo=TZ)
    return [
        SessionActivity(
            activity_id=f"act-{i}",
            activity_type=ActivityType.USER_MESSAGE,
            timestamp=moment,
        )
        for i in range(count)
    ]


def _resolved(
    session_id: str,
    *,
    repository_id: str = "repo-a",
    repository_name: str | None = None,
    title: str | None = None,
    at: datetime | None = None,
) -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id=session_id,
            title=title or session_id,
            working_directory=f"/tmp/{repository_id}",
            activities=_activities(at=at),
        ),
        repository=RepositoryIdentity(
            repository_id=repository_id,
            display_name=repository_name or repository_id,
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory=f"/tmp/{repository_id}",
            resolution_method="test",
        ),
    )


def _scan(count: int = 1, *, unsafe_labels: bool = False, excluded: int = 0) -> ScanResult:
    sessions = [
        _resolved(
            f"ses-{index}",
            repository_name="repo [/] name" if unsafe_labels else "repo-a",
            title="add [link=x] support" if unsafe_labels and index == 0 else f"Session {index}",
            at=datetime(2026, 8, 9, tzinfo=TZ) - timedelta(minutes=index),
        )
        for index in range(count)
    ]
    return ScanResult(
        period=_period(),
        candidate_session_count=count,
        loaded_session_count=count,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions} if sessions else {},
        excluded_session_count=excluded,
    )


def _actions(
    *,
    draft: ReportDraft,
    scan_callback,
    choose_period,
    counters: dict[str, int],
    content: str = "report-content",
    exclude_fails: bool = False,
) -> InteractiveActions:
    def count(name: str) -> None:
        counters[name] = counters.get(name, 0) + 1

    def do_scan(value: ReportDraft) -> ScanResult:
        count("scan")
        return scan_callback(value)

    def generate(
        _draft: ReportDraft,
        selected_scan: ScanResult,
        _force: bool,
    ) -> InteractiveReportResult:
        count("generate")
        return InteractiveReportResult(
            output_path=None if _draft.dry_run else Path("reports/worklog.md"),
            content=content,
            repository_count=len(selected_scan.sessions_by_repository),
            session_count=selected_scan.loaded_session_count,
        )

    def exclude(repository_id: str, display_name: str) -> str:
        if exclude_fails:
            raise IiwiError("exclusion failed")
        return "excluded"

    return InteractiveActions(
        new_draft=lambda: draft,
        choose_harness=lambda current: current,
        choose_period=choose_period,
        scan=do_scan,
        generate=generate,
        synthesize=lambda draft, scan, force: OutcomeReviewDraft(
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
        exclude_repository=exclude,
    )


def test_non_opencode_sanitize_enter_stays_in_report_setup() -> None:
    draft = ReportDraft(harness="claude-code", period=_period())
    counters: dict[str, int] = {}
    console, _ = _console()
    keys = ScriptedInput(
        [
            char("3"),
            *[KeyPress(key=Key.DOWN) for _ in range(6)],
            KeyPress(key=Key.ENTER),
            char("r"),
            char("b"),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(
            draft=draft,
            scan_callback=lambda value: _scan(),
            choose_period=lambda current: ("Last week", _period()),
            counters=counters,
        ),
        input_source=keys,
        console=console,
    )

    assert counters.get("scan", 0) == 1
    assert draft.harness == "claude-code"
    assert draft.sanitize is False


def test_activity_empty_change_period_retries_with_changed_draft() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    counters: dict[str, int] = {}
    period_calls = 0

    def choose_period(current: str | None) -> tuple[str, DateRange]:
        nonlocal period_calls
        period_calls += 1
        return ("Last 10 days", _period(10))

    def scan_callback(value: ReportDraft) -> ScanResult:
        return _scan(0) if value.period == _period() else _scan(1)

    console, _ = _console()
    keys = ScriptedInput(
        [
            char("1"),
            KeyPress(key=Key.ENTER),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(
            draft=draft,
            scan_callback=scan_callback,
            choose_period=choose_period,
            counters=counters,
        ),
        input_source=keys,
        console=console,
    )

    assert period_calls == 1
    assert counters.get("scan", 0) == 2
    assert draft.period == _period(10)


def test_activity_empty_state_says_configuration_exclusion() -> None:
    """An empty activity review whose cause is the exclusion setting must say so."""

    draft = ReportDraft(harness="opencode", period=_period())
    counters: dict[str, int] = {}
    console, stream = _console()
    keys = ScriptedInput([char("1"), char("b"), char("q")])

    run_interactive(
        actions=_actions(
            draft=draft,
            scan_callback=lambda value: _scan(0, excluded=2),
            choose_period=lambda current: ("Last week", _period()),
            counters=counters,
        ),
        input_source=keys,
        console=console,
    )

    text = stream.getvalue()
    assert "excluded by configuration" in text
    assert "No activity matched" not in text


def test_report_empty_state_says_configuration_exclusion() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    counters: dict[str, int] = {}
    console, stream = _console()
    keys = ScriptedInput([char("3"), char("r"), char("b"), char("q"), char("q")])

    run_interactive(
        actions=_actions(
            draft=draft,
            scan_callback=lambda value: _scan(0, excluded=2),
            choose_period=lambda current: ("Last week", _period()),
            counters=counters,
        ),
        input_source=keys,
        console=console,
    )

    text = stream.getvalue()
    assert "excluded by configuration" in text
    assert "No activity matched" not in text


def test_user_labels_are_rendered_as_literal_text_not_rich_markup() -> None:
    selection = SelectionState.from_scan(_scan(1, unsafe_labels=True))
    console, stream = _console()

    render_session_review(
        console,
        selection,
        expanded_repositories={"repo-a"},
        cursor=1,
    )

    text = stream.getvalue()
    assert "repo [/] name" in text
    assert "add [link=x] support" in text


def test_preview_action_can_preview_generated_report_content() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    counters: dict[str, int] = {}
    console, stream = _console()
    keys = ScriptedInput(
        [
            char("3"),
            KeyPress(key=Key.ENTER),
            char("p"),
            char("b"),
            char("b"),
            char("q"),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(
            draft=draft,
            scan_callback=lambda value: _scan(),
            choose_period=lambda current: ("Last week", _period()),
            counters=counters,
            content="# Dry run report\n\nBody\n",
        ),
        input_source=keys,
        console=console,
    )

    text = stream.getvalue()
    assert "Report Preview" in text
    assert "# Dry run report" in text
    assert "Body" in text


def test_session_review_uses_terminal_height_viewport_around_cursor() -> None:
    selection = SelectionState.from_scan(_scan(18))
    console, stream = _console(height=12)

    render_session_review(
        console,
        selection,
        expanded_repositories={"repo-a"},
        cursor=18,
    )

    text = stream.getvalue()
    assert "Session 17" in text
    assert "Session 0" not in text
    assert "more" in text


def test_review_back_and_reenter_preserves_repository_expansion() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    counters: dict[str, int] = {}
    console, stream = _console()
    keys = ScriptedInput(
        [
            char("3"),
            char("r"),
            KeyPress(key=Key.ENTER),
            char("b"),
            char("r"),
            char("b"),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(
            draft=draft,
            scan_callback=lambda value: _scan(1),
            choose_period=lambda current: ("Last week", _period()),
            counters=counters,
        ),
        input_source=keys,
        console=console,
    )

    assert stream.getvalue().count("Session 0") >= 2


def test_report_setup_footer_omits_redundant_main_menu_shortcut() -> None:
    console, stream = _console()

    render_report_setup(
        console,
        ReportDraft(harness="opencode", period=_period()),
        selected=0,
    )

    assert "q Menu" not in stream.getvalue()


def test_selection_from_scan_copies_caller_owned_set() -> None:
    scan = _scan(1)
    selected = {"ses-0"}
    state = SelectionState.from_scan(scan, selected_session_ids=selected)

    state.toggle_session("ses-0")

    assert selected == {"ses-0"}
    assert state.selected_session_ids == set()


def test_exclude_failure_returns_to_session_review() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    counters: dict[str, int] = {}
    console, stream = _console()

    def choose_period(current: str | None) -> tuple[str, DateRange]:
        return ("Last week", _period())

    actions = _actions(
        draft=draft,
        scan_callback=lambda _: _scan(1),
        choose_period=choose_period,
        counters=counters,
        exclude_fails=True,
    )
    input_source = ScriptedInput(
        [
            char("3"),
            char("r"),
            char("e"),
            char("b"),
            char("q"),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=actions,
        input_source=input_source,
        console=console,
    )

    text = stream.getvalue()
    assert "Could not exclude repository" in text
    last_review = text.rindex("Review Sessions")
    assert text.count("Could not exclude repository") == 1
    assert "Review Sessions" in text[last_review:]
