from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console

from iiwi import cli
from iiwi import errors as app_errors
from iiwi.interactive import cli_actions
from iiwi.interactive import input as interactive_input
from iiwi.interactive import render as interactive_render
from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from iiwi.interactive.input import Key, KeyPress, normalize_posix_sequence
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


def _period(day: int = 3) -> DateRange:
    return DateRange(
        since=datetime(2026, 8, day, tzinfo=TZ),
        until=datetime(2026, 8, day + 7, tzinfo=TZ),
    )


def _activities(count: int = 5) -> list[SessionActivity]:
    """Real scans never yield activity-less sessions; keep fixtures substantive."""

    return [
        SessionActivity(activity_id=f"act-{i}", activity_type=ActivityType.USER_MESSAGE)
        for i in range(count)
    ]


def _resolved(session_id: str, title: str = "Session 0") -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id=session_id,
            title=title,
            working_directory="/tmp/repo-a",
            activities=_activities(),
        ),
        repository=RepositoryIdentity(
            repository_id="repo-a",
            display_name="repo-a",
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory="/tmp/repo-a",
            resolution_method="test",
        ),
    )


def _scan() -> ScanResult:
    sessions = [_resolved("ses-0")]
    return ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )


def _actions(
    *,
    counters: dict[str, int] | None = None,
    scan_callback=None,
    draft: ReportDraft | None = None,
) -> InteractiveActions:
    counters = counters if counters is not None else {}
    report_draft = draft or ReportDraft(harness="opencode", period=_period())

    def count(name: str) -> None:
        counters[name] = counters.get(name, 0) + 1

    def do_scan(value: ReportDraft) -> ScanResult:
        count("scan")
        if scan_callback is not None:
            return scan_callback(value)
        return _scan()

    return InteractiveActions(
        new_draft=lambda: report_draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: ("Last week", _period()),
        scan=do_scan,
        generate=lambda draft, scan, force: InteractiveReportResult(
            output_path=Path("reports/worklog.md"),
            content="\n".join(f"line {index}" for index in range(60)),
            repository_count=1,
            session_count=scan.loaded_session_count,
        ),
        synthesize=lambda draft, scan: OutcomeReviewDraft(
            outcomes=_synthesized_outcomes(), report_type=draft.report_type
        ),
        generate_reviewed=lambda draft, scan, review, force: InteractiveReportResult(
            output_path=None if draft.dry_run else Path("reports/worklog.md"),
            content="\n".join(f"line {index}" for index in range(60)),
            repository_count=1,
            session_count=scan.loaded_session_count,
        ),
        edit_outcome=lambda outcome: outcome,
        add_outcome=lambda: None,
        edit_gap=lambda label, current: current,
        save_report_type=lambda report_type: None,
        doctor=lambda harness: [f"{harness}: ok"],
        edit_settings=lambda: None,
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )


def _console(*, width: int = 100, height: int = 25) -> tuple[Console, StringIO]:
    stream = StringIO()
    console = Console(
        file=stream,
        color_system=None,
        force_terminal=False,
        width=width,
        height=height,
    )
    return console, stream


def test_recoverable_error_keeps_actions_inside_viewport_with_long_detail() -> None:
    console, stream = _console(width=48, height=16)
    detail = "\n".join(f"stderr line {index} " + "x" * 100 for index in range(40))

    interactive_render.render_recoverable_error(
        console,
        title="Could not read OpenCode sessions",
        detail=detail,
        options=["Overwrite once", "Back", "Main menu"],
        selected=0,
    )

    lines = stream.getvalue().splitlines()
    assert len(lines) <= 15
    assert any("Overwrite once" in line for line in lines)
    assert any("Main menu" in line for line in lines)
    assert any("more" in line for line in lines)


def test_fixed_screens_do_not_wrap_in_narrow_terminal() -> None:
    console, main_stream = _console(width=30, height=30)
    interactive_render.render_main_menu(console, selected=0)
    assert len(main_stream.getvalue().splitlines()) == 15

    console, setup_stream = _console(width=30, height=30)
    interactive_render.render_report_setup(
        console,
        ReportDraft(harness="opencode", period=_period()),
        selected=0,
    )
    assert len(setup_stream.getvalue().splitlines()) == 18

    console, result_stream = _console(width=30, height=30)
    interactive_render.render_report_result(
        console,
        period=_period(),
        repository_count=1,
        session_count=1,
        output_path=Path("/very/long/output/path/that/must/not/wrap/worklog.md"),
        selected=0,
    )
    assert len(result_stream.getvalue().splitlines()) == 14


def test_preview_capacity_reserves_final_terminal_line() -> None:
    assert interactive_render.report_preview_capacity(20) == 12
    assert interactive_render.report_preview_capacity(9) == 1
    assert interactive_render.report_preview_capacity(8) == 0


def test_posix_navigation_sequences_include_horizontal_and_paging_keys() -> None:
    expected = {
        "\x1b[D": "LEFT",
        "\x1b[C": "RIGHT",
        "\x1b[5~": "PAGE_UP",
        "\x1b[6~": "PAGE_DOWN",
        "\x1b[H": "HOME",
        "\x1b[F": "END",
    }
    for sequence, member in expected.items():
        key = getattr(Key, member, None)
        assert key is not None, f"missing Key.{member}"
        assert normalize_posix_sequence(sequence) == KeyPress(key=key)


def test_posix_reader_consumes_complete_escape_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = iter([b"\x1b", b"[", b"5", b"~"])
    monkeypatch.setattr(interactive_input.sys, "stdin", SimpleNamespace(fileno=lambda: 7))
    monkeypatch.setattr(interactive_input.os, "read", lambda fd, size: next(chunks))
    monkeypatch.setattr(
        interactive_input.select,
        "select",
        lambda readable, writable, exceptional, timeout: ([7], [], []),
    )

    assert interactive_input._posix_read() == "\x1b[5~"


def test_ctrl_c_during_scan_returns_to_previous_screen_instead_of_exiting() -> None:
    calls = 0

    def interrupt_once(_draft: ReportDraft) -> ScanResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt
        return _scan()

    console, _ = _console()
    keys = ScriptedInput([char("2"), char("r"), char("b"), char("q")])

    run_interactive(
        actions=_actions(scan_callback=interrupt_once),
        input_source=keys,
        console=console,
    )

    assert calls == 1


def test_harness_and_period_editors_do_not_fall_back_to_typed_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(report=SimpleNamespace(timezone="Asia/Taipei"))
    now = datetime(2026, 8, 7, 12, tzinfo=TZ)
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_enabled_harnesses",
        lambda value: [cli.Harness.OPENCODE, cli.Harness.CODEX],
    )
    monkeypatch.setattr(cli, "_now_in_timezone", lambda timezone: now)
    monkeypatch.setattr(
        cli,
        "_prompt",
        lambda prompt: pytest.fail(f"interactive UI must not call typed prompt: {prompt}"),
    )

    assert cli_actions._choose_harness("opencode") == "codex"
    assert cli_actions._choose_period("This week") == (
        "Last week",
        DateRange.previous_week(now=now),
    )


def test_browser_supports_horizontal_expand_collapse_and_rescan() -> None:
    counters: dict[str, int] = {}
    console, stream = _console()
    keys = ScriptedInput(
        [
            KeyPress(key=Key.ENTER),
            char("l"),
            char("h"),
            char("R"),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(counters=counters),
        input_source=keys,
        console=console,
    )

    assert "Session 0" in stream.getvalue()
    assert counters["scan"] == 2


def test_question_mark_opens_keyboard_help() -> None:
    console, stream = _console()
    keys = ScriptedInput([char("?"), char("b"), char("q")])

    run_interactive(actions=_actions(), input_source=keys, console=console)

    assert "Keyboard shortcuts" in stream.getvalue()


def test_search_filter_helper_matches_session_titles_and_repository_names() -> None:
    sessions = [_resolved("ses-a", "Alpha feature"), _resolved("ses-b", "Beta fix")]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )
    helper = getattr(interactive_render, "build_filtered_rows", None)
    assert helper is not None, "missing search/filter row builder"

    rows = helper(scan, set(), query="beta")

    assert [row.session_id for row in rows if row.session_id is not None] == ["ses-b"]


def test_preview_supports_page_and_boundary_navigation() -> None:
    page_down = getattr(Key, "PAGE_DOWN", None)
    assert page_down is not None, "missing Key.PAGE_DOWN"
    console, stream = _console(height=12)
    draft = ReportDraft(harness="opencode", period=_period())
    keys = ScriptedInput(
        [
            char("2"),
            KeyPress(key=Key.ENTER),
            char("p"),
            KeyPress(key=page_down),
            char("G"),
            char("g"),
            char("b"),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(actions=_actions(draft=draft), input_source=keys, console=console)

    text = stream.getvalue()
    assert "line 59" in text
    assert text.count("line 0") >= 2


def test_report_output_conflicts_have_a_distinct_error_type() -> None:
    conflict_type = getattr(app_errors, "ReportAlreadyExistsError", None)
    assert conflict_type is not None
    assert issubclass(conflict_type, app_errors.ReportOutputError)


def test_cli_source_file_ends_with_newline() -> None:
    assert Path(cli.__file__).read_bytes().endswith(b"\n")
