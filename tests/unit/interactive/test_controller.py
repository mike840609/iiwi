from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console

from iiwi.errors import HarnessSourceError
from iiwi.history import HistoryEntry, append_history
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
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> ScriptedInput:
        self.entered += 1
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.exited += 1

    def read_key(self) -> KeyPress:
        return next(self._keys)


def _console() -> Console:
    return Console(
        file=StringIO(),
        color_system=None,
        force_terminal=False,
        width=110,
    )


def _period(day: int = 3) -> DateRange:
    return DateRange(
        since=datetime(2026, 8, day, tzinfo=TZ),
        until=datetime(2026, 8, day + 7, tzinfo=TZ),
    )


def _scan(count: int = 1) -> ScanResult:
    sessions: list[ResolvedSession] = []
    for index in range(count):
        repository_id = "repo-a"
        sessions.append(
            ResolvedSession(
                session=AgentSession(
                    harness="opencode",
                    session_id=f"ses-{index}",
                    title=f"Session {index}",
                    working_directory="/tmp/repo-a",
                ),
                repository=RepositoryIdentity(
                    repository_id=repository_id,
                    display_name="repo-a",
                    identity_type=RepositoryIdentityType.PATH_FALLBACK,
                    working_directory="/tmp/repo-a",
                    resolution_method="test",
                ),
            )
        )
    groups = {"repo-a": sessions} if sessions else {}
    return ScanResult(
        period=_period(),
        candidate_session_count=count,
        loaded_session_count=count,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository=groups,
    )


def _actions(
    *,
    scan_callback=None,
    draft: ReportDraft | None = None,
    counters: dict[str, int] | None = None,
) -> InteractiveActions:
    counters = counters if counters is not None else {}
    report_draft = draft or ReportDraft(harness="opencode", period=_period())

    def count(name: str) -> None:
        counters[name] = counters.get(name, 0) + 1

    def new_draft() -> ReportDraft:
        count("draft")
        return report_draft

    def choose_harness(current: str) -> str:
        count("choose_harness")
        return "codex" if current != "codex" else "opencode"

    def choose_period(current: str | None) -> tuple[str, DateRange]:
        count("choose_period")
        return ("Last 10 days", _period(10))

    def scan(draft_value: ReportDraft) -> ScanResult:
        count("scan")
        if scan_callback is not None:
            return scan_callback(draft_value)
        return _scan()

    def generate(
        draft_value: ReportDraft,
        scan_value: ScanResult,
        force: bool,
    ) -> InteractiveReportResult:
        count("generate")
        return InteractiveReportResult(
            output_path=Path("reports/worklog.md"),
            content="report",
            repository_count=len(scan_value.sessions_by_repository),
            session_count=scan_value.loaded_session_count,
        )

    return InteractiveActions(
        new_draft=new_draft,
        choose_harness=choose_harness,
        choose_period=choose_period,
        scan=scan,
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
        doctor=lambda harness: [f"{harness}: ok"],
        edit_settings=lambda: None,
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )


def test_numeric_generate_then_back_returns_to_main_without_restarting() -> None:
    counters: dict[str, int] = {}
    input_source = ScriptedInput([char("2"), char("b"), char("q")])

    run_interactive(
        actions=_actions(counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters["draft"] == 1
    assert input_source.entered == input_source.exited == 3


def test_default_navigation_enters_read_only_activity_without_prompting_and_returns() -> None:
    counters: dict[str, int] = {}
    input_source = ScriptedInput(
        [
            KeyPress(key=Key.ENTER),
            KeyPress(key=Key.ENTER),
            KeyPress(key=Key.SPACE),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters.get("choose_harness", 0) == 0
    assert counters.get("choose_period", 0) == 0
    assert counters["scan"] == 1
    assert counters.get("generate", 0) == 0


def test_review_reuses_cached_scan_after_back() -> None:
    counters: dict[str, int] = {}
    input_source = ScriptedInput(
        [char("1"), char("r"), char("b"), char("r"), char("b"), char("b"), char("q")]
    )

    run_interactive(
        actions=_actions(counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters["scan"] == 1


def test_setup_detail_edit_does_not_require_a_scan() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    input_source = ScriptedInput(
        [
            char("2"),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            char("b"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(draft=draft),
        input_source=input_source,
        console=_console(),
    )

    assert draft.detail.value == "brief"


def test_harness_source_error_is_recoverable_by_changing_harness() -> None:
    counters: dict[str, int] = {}

    def fail_scan(draft: ReportDraft) -> ScanResult:
        raise HarnessSourceError("session store missing")

    input_source = ScriptedInput(
        [char("2"), char("r"), KeyPress(key=Key.ENTER), char("b"), char("q")]
    )

    run_interactive(
        actions=_actions(scan_callback=fail_scan, counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters["scan"] == 1
    assert counters["choose_harness"] == 1


def test_zero_sessions_is_recoverable_by_changing_period() -> None:
    counters: dict[str, int] = {}
    input_source = ScriptedInput(
        [char("2"), char("r"), KeyPress(key=Key.ENTER), char("b"), char("q")]
    )

    run_interactive(
        actions=_actions(scan_callback=lambda draft: _scan(0), counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters["scan"] == 1
    assert counters["choose_period"] == 1


def test_setup_g_enters_quick_review_then_generate_writes() -> None:
    counters: dict[str, int] = {}

    def populated_scan(draft: ReportDraft) -> ScanResult:
        sessions = [
            ResolvedSession(
                session=AgentSession(
                    harness="opencode",
                    session_id="ses-0",
                    title="Session 0",
                    working_directory="/tmp/repo-a",
                    activities=[
                        SessionActivity(
                            activity_id=f"act-{i}",
                            activity_type=ActivityType.USER_MESSAGE,
                        )
                        for i in range(5)
                    ],
                ),
                repository=RepositoryIdentity(
                    repository_id="repo-a",
                    display_name="repo-a",
                    identity_type=RepositoryIdentityType.PATH_FALLBACK,
                    working_directory="/tmp/repo-a",
                    resolution_method="test",
                ),
            )
        ]
        return ScanResult(
            period=_period(),
            candidate_session_count=1,
            loaded_session_count=1,
            failed_session_count=0,
            resolved_sessions=sessions,
            sessions_by_repository={"repo-a": sessions},
        )

    input_source = ScriptedInput([char("2"), char("g"), char("g"), char("q"), char("q")])

    run_interactive(
        actions=_actions(scan_callback=populated_scan, counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters.get("scan") == 1
    assert counters.get("generate") == 1


def test_setup_edits_the_field_under_the_cursor() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    input_source = ScriptedInput(
        [
            char("2"),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            char("l"),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(draft=draft),
        input_source=input_source,
        console=_console(),
    )

    assert draft.sanitize is True
    assert draft.dry_run is False
    assert draft.include_subagents is True
    assert draft.narrative is True


def test_setup_escape_returns_to_main_without_a_back_row() -> None:
    input_source = ScriptedInput([char("1"), KeyPress(key=Key.ESCAPE), char("q")])

    run_interactive(
        actions=_actions(),
        input_source=input_source,
        console=_console(),
    )


def test_setup_g_on_an_empty_scan_does_not_reach_the_result_screen() -> None:
    counters: dict[str, int] = {}

    def empty_scan(draft: ReportDraft) -> ScanResult:
        return ScanResult(
            period=_period(),
            candidate_session_count=0,
            loaded_session_count=0,
            failed_session_count=0,
            resolved_sessions=[],
            sessions_by_repository={},
        )

    input_source = ScriptedInput([char("2"), char("g"), char("b"), char("q"), char("q")])

    run_interactive(
        actions=_actions(scan_callback=empty_scan, counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters.get("scan") == 1
    assert counters.get("generate") is None


def _setup_populated_scan(draft: ReportDraft) -> ScanResult:
    sessions = [
        ResolvedSession(
            session=AgentSession(
                harness="opencode",
                session_id="ses-0",
                title="Session 0",
                working_directory="/tmp/repo-a",
                activities=[
                    SessionActivity(
                        activity_id=f"act-{i}",
                        activity_type=ActivityType.USER_MESSAGE,
                    )
                    for i in range(5)
                ],
            ),
            repository=RepositoryIdentity(
                repository_id="repo-a",
                display_name="repo-a",
                identity_type=RepositoryIdentityType.PATH_FALLBACK,
                working_directory="/tmp/repo-a",
                resolution_method="test",
            ),
        )
    ]
    return ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )


def test_setup_enter_on_the_action_row_enters_quick_review_then_generate_writes() -> None:
    counters: dict[str, int] = {}
    input_source = ScriptedInput(
        [char("2"), KeyPress(key=Key.ENTER), char("g"), char("q"), char("q")]
    )

    run_interactive(
        actions=_actions(scan_callback=_setup_populated_scan, counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters.get("scan") == 1
    assert counters.get("generate") == 1


def test_setup_horizontal_keys_on_the_action_row_do_not_generate() -> None:
    counters: dict[str, int] = {}
    input_source = ScriptedInput(
        [char("2"), char("l"), KeyPress(key=Key.RIGHT), char("q"), char("q")]
    )

    run_interactive(
        actions=_actions(scan_callback=_setup_populated_scan, counters=counters),
        input_source=input_source,
        console=_console(),
    )

    assert counters.get("generate") is None


def _history_entry(output_path: str) -> HistoryEntry:
    return HistoryEntry(
        generated_at=datetime(2026, 8, 12, 9, 30, tzinfo=TZ),
        harness="opencode",
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
        output_path=Path(output_path),
        repository_count=2,
        session_count=7,
        narrative=True,
        detail="full",
    )


def test_main_menu_history_opens_and_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    append_history(_history_entry("reports/worklog.md"))
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput([char("3"), char("b"), char("q")]),
        console=console,
    )

    text = console.file.getvalue()
    assert "Past Reports" in text
    assert "reports/worklog.md" in text


def test_history_enter_shows_the_recorded_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    append_history(_history_entry("reports/worklog.md"))
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [char("3"), KeyPress(key=Key.ENTER), char("b"), char("b"), char("q")]
        ),
        console=console,
    )

    text = console.file.getvalue()
    assert "Report path" in text
    assert "reports/worklog.md" in text


def test_history_enter_shows_the_cursor_row_not_the_first_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    append_history(_history_entry("reports/first.md"))
    append_history(_history_entry("reports/second.md"))
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [char("3"), char("j"), KeyPress(key=Key.ENTER), char("q"), char("q")]
        ),
        console=console,
    )

    text = console.file.getvalue()
    # The history screen lists both paths; the path screen must show the
    # cursor's row. Newest first: index 0 is second.md, cursor moves to
    # index 1 = first.md. The last occurrence of each path after the first
    # "Report path" title is the error screen's detail, so rindex ordering
    # pins which path the error screen displayed.
    first_title = text.index("Report path")
    assert text.rindex("reports/first.md") > first_title
    assert text.rindex("reports/second.md") < first_title


def test_history_g_and_G_jump_follow_the_viewport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    for index in range(20):
        append_history(_history_entry(f"reports/{index}.md"))
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [char("3"), char("G"), KeyPress(key=Key.ENTER), char("b"),
             char("g"), KeyPress(key=Key.ENTER), char("b"), char("b"), char("q")]
        ),
        console=console,
    )

    text = console.file.getvalue()
    # 20 entries exceed the test console's ~17-row viewport, so G clamps the
    # offset; Enter on the bottom row shows the oldest entry, then g jumps
    # back to the top and Enter shows the newest.
    assert text.rindex("reports/0.md") > text.index("Report path")
    assert text.rindex("reports/19.md") > text.rindex("reports/0.md")


def test_history_empty_state_ignores_enter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput([char("3"), KeyPress(key=Key.ENTER), char("b"), char("q")]),
        console=console,
    )

    text = console.file.getvalue()
    assert "No reports generated yet." in text
    assert "Report path" not in text


def test_ctrl_c_on_history_returns_to_the_main_menu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    append_history(_history_entry("reports/worklog.md"))

    class ScriptedWithInterrupt(ScriptedInput):
        """Interrupt the read after the first key, then resume the script."""

        def __init__(self, keys: list[KeyPress]) -> None:
            super().__init__(keys)
            self.pending_interrupt = True

        def read_key(self) -> KeyPress:
            if self.pending_interrupt:
                self.pending_interrupt = False
                return super().read_key()
            raise KeyboardInterrupt

    input_source = ScriptedWithInterrupt([char("3"), char("b"), char("q")])
    console = _console()

    run_interactive(
        actions=_actions(),
        input_source=input_source,
        console=console,
    )

    text = console.file.getvalue()
    # The interrupt lands on the second read (cursor on HISTORY after `3`).
    # The idle-interrupt handler must return to MAIN, so the final frame is
    # the main menu: "Past Reports" appears exactly once (the HISTORY screen
    # never re-renders) and the output ends with the main menu's footer
    # (`q Quit`), not the history screen's (`b Back`).
    assert text.count("Past Reports") == 1
    assert text.rstrip().endswith("q Quit")


def test_history_q_and_escape_return_to_the_main_menu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
    append_history(_history_entry("reports/worklog.md"))

    console = _console()
    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput([char("3"), char("q"), char("q")]),
        console=console,
    )
    text = console.file.getvalue()
    assert text.count("Past Reports") == 1
    assert text.rstrip().endswith("q Quit")

    console = _console()
    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [char("3"), KeyPress(key=Key.ESCAPE), char("q")]
        ),
        console=console,
    )
    text = console.file.getvalue()
    assert text.count("Past Reports") == 1
    assert text.rstrip().endswith("q Quit")
