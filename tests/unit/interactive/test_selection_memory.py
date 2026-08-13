"""Selection memory and repository exclusion in the interactive flow."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from iiwi.interactive.controller import (
    InteractiveActions,
    InteractiveReportResult,
    run_interactive,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft
from iiwi.models.outcome import OutcomeReviewDraft
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


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


def _scan(session_ids: list[str] | None = None) -> ScanResult:
    session_ids = session_ids or ["ses-a"]
    sessions: list[ResolvedSession] = []
    for session_id in session_ids:
        sessions.append(
            ResolvedSession(
                session=AgentSession(
                    harness="opencode",
                    session_id=session_id,
                    title=f"Work on {session_id}",
                    working_directory="/tmp/repo-a",
                    activities=[
                        SessionActivity(
                            activity_id=f"act-{session_id}-{index}",
                            activity_type=ActivityType.USER_MESSAGE,
                        )
                        for index in range(5)
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
        )
    return ScanResult(
        period=_period(),
        candidate_session_count=len(sessions),
        loaded_session_count=len(sessions),
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions} if sessions else {},
    )


class Recorder:
    def __init__(self) -> None:
        self.restore_calls: list[tuple[str, DateRange, bool]] = []
        self.save_calls: list[tuple[str, DateRange, bool, set[str]]] = []
        self.exclude_calls: list[tuple[str, str]] = []
        self.scan_calls = 0
        self.restored: set[str] | None = None
        self.exclude_result: str = "Excluded repo-a; future scans will skip it."

    def new_draft(self) -> ReportDraft:
        return ReportDraft(harness="opencode", period=_period())

    def scan(self, draft: ReportDraft) -> ScanResult:
        self.scan_calls += 1
        return _scan()

    def restore_selection(
        self, harness: str, period: DateRange, include_subagents: bool
    ) -> set[str] | None:
        self.restore_calls.append((harness, period, include_subagents))
        return self.restored

    def save_selection(
        self,
        harness: str,
        period: DateRange,
        include_subagents: bool,
        selected_session_ids: set[str],
    ) -> None:
        self.save_calls.append((harness, period, include_subagents, selected_session_ids))

    def exclude_repository(self, repository_id: str, display_name: str) -> str:
        self.exclude_calls.append((repository_id, display_name))
        return self.exclude_result

    def actions(self) -> InteractiveActions:
        return InteractiveActions(
            new_draft=self.new_draft,
            choose_harness=lambda current: current,
            choose_period=lambda current: ("Last week", _period()),
            scan=self.scan,
            generate=lambda draft, scan, force: InteractiveReportResult(
                output_path=Path("reports/worklog.md"),
                content="report",
                repository_count=1,
                session_count=1,
            ),
            synthesize=lambda draft, scan: OutcomeReviewDraft(
                outcomes=[], report_type=draft.report_type
            ),
            generate_reviewed=lambda draft, scan, review, force: InteractiveReportResult(
                output_path=Path("reports/worklog.md"),
                content="report",
                repository_count=1,
                session_count=1,
            ),
            edit_outcome=lambda outcome: outcome,
            add_outcome=lambda: None,
            edit_gap=lambda label, current: current,
            save_report_type=lambda report_type: None,
            doctor=lambda harness: ["ok"],
            edit_settings=lambda: None,
            restore_selection=self.restore_selection,
            save_selection=self.save_selection,
            exclude_repository=self.exclude_repository,
        )


def _console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(file=stream, color_system=None, force_terminal=False, width=100),
        stream,
    )


def test_restore_applies_a_stored_selection_to_a_fresh_scan() -> None:
    recorder = Recorder()
    recorder.restored = {"ses-a"}

    draft = recorder.new_draft()
    recorder.new_draft = lambda: draft
    console, _ = _console()
    run_interactive(
        actions=recorder.actions(),
        input_source=ScriptedInput(
            [char("2"), char("r"), char("b"), char("b"), char("q"), char("q")]
        ),
        console=console,
    )

    assert draft.selected_session_ids == {"ses-a"}


def test_restore_drops_ids_the_new_scan_does_not_have() -> None:
    recorder = Recorder()
    recorder.restored = {"ses-a", "ses-gone"}
    recorder.scan = lambda draft: _scan(session_ids=["ses-a"])

    draft = recorder.new_draft()
    recorder.new_draft = lambda: draft
    console, _ = _console()
    run_interactive(
        actions=recorder.actions(),
        input_source=ScriptedInput(
            [char("2"), char("r"), char("b"), char("b"), char("q"), char("q")]
        ),
        console=console,
    )

    assert draft.selected_session_ids == {"ses-a"}


def test_no_stored_selection_keeps_the_noise_free_default() -> None:
    recorder = Recorder()
    recorder.restored = None

    draft = recorder.new_draft()
    recorder.new_draft = lambda: draft
    console, _ = _console()
    run_interactive(
        actions=recorder.actions(),
        input_source=ScriptedInput(
            [char("2"), char("r"), char("b"), char("b"), char("q"), char("q")]
        ),
        console=console,
    )

    assert draft.selected_session_ids == {"ses-a"}


def test_selection_is_saved_when_it_changes_but_not_when_it_does_not() -> None:
    recorder = Recorder()
    draft = recorder.new_draft()
    recorder.new_draft = lambda: draft
    console, _ = _console()

    run_interactive(
        actions=recorder.actions(),
        input_source=ScriptedInput(
            [
                char("2"),
                char("r"),
                KeyPress(key=Key.RIGHT),
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.SPACE),
                char("b"),
                char("b"),
                char("q"),
                char("q"),
            ]
        ),
        console=console,
    )

    assert len(recorder.save_calls) == 1
    assert recorder.save_calls[0][0] == "opencode"
    assert recorder.save_calls[0][2] is True
    assert recorder.save_calls[0][3] == set()

    recorder.save_calls.clear()
    run_interactive(
        actions=recorder.actions(),
        input_source=ScriptedInput(
            [char("2"), char("r"), char("b"), char("b"), char("q"), char("q")]
        ),
        console=console,
    )

    assert recorder.save_calls == []


def test_a_failing_selection_save_does_not_crash_the_tui() -> None:
    """A selection that cannot be persisted is forgotten, not fatal.

    The state file is bookkeeping, like the history log: an unwritable home
    directory (or a full disk) must not take the interactive app down with a
    traceback mid-session.
    """

    class FailingRecorder(Recorder):
        def save_selection(
            self,
            harness: str,
            period: DateRange,
            include_subagents: bool,
            selected_session_ids: set[str],
        ) -> None:
            raise OSError("disk full")

    recorder = FailingRecorder()
    console, _ = _console()

    run_interactive(
        actions=recorder.actions(),
        input_source=ScriptedInput(
            [
                char("2"),
                char("r"),
                KeyPress(key=Key.RIGHT),
                KeyPress(key=Key.DOWN),
                KeyPress(key=Key.SPACE),
                char("b"),
                char("b"),
                char("q"),
            ]
        ),
        console=console,
    )


def test_exclude_key_on_a_repository_row_excludes_without_rescan() -> None:
    recorder = Recorder()
    console, stream = _console()

    run_interactive(
        actions=recorder.actions(),
        input_source=ScriptedInput(
            [char("2"), char("r"), char("e"), char("b"), char("b"), char("q")]
        ),
        console=console,
    )

    assert recorder.exclude_calls == [("repo-a", "repo-a")]
    assert recorder.scan_calls == 1
    assert "future scans will skip it" in stream.getvalue()


def test_excluded_repository_stays_excluded_when_reentering_review() -> None:
    recorder = Recorder()
    console, stream = _console()

    run_interactive(
        actions=recorder.actions(),
        input_source=ScriptedInput(
            [
                char("2"),
                char("r"),
                char("e"),
                char("b"),
                char("r"),
                char("b"),
                char("b"),
                char("q"),
            ]
        ),
        console=console,
    )

    assert recorder.exclude_calls == [("repo-a", "repo-a")]
    assert recorder.scan_calls == 1
    assert (
        stream.getvalue().count("repo-a   1 / 1")
        + stream.getvalue().count("repo-a   0 / 1")
    ) == 1


def test_exclude_key_on_a_session_row_does_not_exclude() -> None:
    recorder = Recorder()
    console, _ = _console()

    run_interactive(
        actions=recorder.actions(),
        input_source=ScriptedInput(
            [
                char("2"),
                char("r"),
                KeyPress(key=Key.RIGHT),
                KeyPress(key=Key.DOWN),
                char("e"),
                char("b"),
                char("b"),
                char("q"),
                char("q"),
            ]
        ),
        console=console,
    )

    assert recorder.exclude_calls == []
