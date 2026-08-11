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
from iiwi.interactive.render import render_report_setup, report_setup_rows
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


class ScriptedInput:
    def __init__(self, keys: list[KeyPress]) -> None:
        self._keys: Iterator[KeyPress] = iter(keys)

    def __enter__(self) -> ScriptedInput:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read_key(self) -> KeyPress:
        return next(self._keys)


def char(value: str) -> KeyPress:
    return KeyPress(char=value)


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(
            file=stream,
            color_system=None,
            force_terminal=False,
            width=100,
            height=25,
        ),
        stream,
    )


def _scan() -> ScanResult:
    session = AgentSession(
        harness="opencode",
        session_id="ses-1",
        title="Preview me",
        working_directory="/tmp/repo",
        activities=[
            SessionActivity(
                activity_id="act-1",
                activity_type=ActivityType.USER_MESSAGE,
            )
        ],
    )
    resolved = ResolvedSession(
        session=session,
        repository=RepositoryIdentity(
            repository_id="repo",
            display_name="repo",
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory="/tmp/repo",
            resolution_method="test",
        ),
    )
    return ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=[resolved],
        sessions_by_repository={"repo": [resolved]},
    )


def _actions(
    draft: ReportDraft,
    *,
    generation_modes: list[bool] | None = None,
) -> InteractiveActions:
    scan = _scan()

    def generate(
        draft_value: ReportDraft,
        scan_value: ScanResult,
        force: bool,
    ) -> InteractiveReportResult:
        if generation_modes is not None:
            generation_modes.append(draft_value.dry_run)
        return InteractiveReportResult(
            output_path=None if draft_value.dry_run else Path("reports/worklog.md"),
            content="preview-content",
            repository_count=1,
            session_count=1,
        )

    return InteractiveActions(
        new_draft=lambda: draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: ("Last 7 days", _period()),
        scan=lambda draft_value: scan,
        generate=generate,
        synthesize=lambda draft, scan: OutcomeReviewDraft(
            outcomes=[], report_type=draft.report_type
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
        restore_selection=lambda harness, period, include_subagents: {"ses-1"},
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )


def test_setup_rows_hide_advanced_fields_by_default() -> None:
    assert report_setup_rows(advanced=False) == [
        "Generate report",
        "Preview report",
        "Harness",
        "Period",
        "Advanced settings",
    ]


def test_setup_rows_show_advanced_fields_when_expanded() -> None:
    rows = report_setup_rows(advanced=True)

    assert rows[:5] == [
        "Generate report",
        "Preview report",
        "Harness",
        "Period",
        "Advanced settings",
    ]
    assert rows[5:] == ["Detail", "Subagents", "Narrative", "Sanitize"]


def test_collapsed_setup_renders_actions_and_primary_controls() -> None:
    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period())

    render_report_setup(console, draft, selected=0, advanced=False)

    text = stream.getvalue()
    assert "Generate report" in text
    assert "Preview report" in text
    assert "Harness" in text
    assert "Period" in text
    assert "Advanced settings" in text
    assert "Detail" not in text
    assert "Subagents" not in text
    assert "Narrative" not in text
    assert "Sanitize" not in text
    assert "Dry run" not in text


def test_advanced_children_are_indented_when_expanded() -> None:
    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period())

    render_report_setup(console, draft, selected=5, advanced=True)

    text = stream.getvalue()
    assert "▶   Detail" in text
    assert "    Subagents" in text
    assert "Dry run" not in text


def test_enter_on_advanced_settings_expands_instead_of_editing_detail() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    console, _ = _console()
    input_source = ScriptedInput(
        [
            char("2"),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(draft),
        input_source=input_source,
        console=console,
    )

    assert draft.detail.value == "full"


def test_preview_report_runs_as_dry_run_and_returns_to_setup() -> None:
    draft = ReportDraft(harness="opencode", period=_period())
    generation_modes: list[bool] = []
    console, stream = _console()
    input_source = ScriptedInput(
        [
            char("2"),
            KeyPress(key=Key.DOWN),
            KeyPress(key=Key.ENTER),
            char("b"),
            KeyPress(key=Key.ENTER),
            char("b"),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(draft, generation_modes=generation_modes),
        input_source=input_source,
        console=console,
    )

    assert generation_modes == [True, True]
    assert draft.dry_run is False
    assert "preview-content" in stream.getvalue()


def test_generate_report_forces_real_output_mode() -> None:
    draft = ReportDraft(harness="opencode", period=_period(), dry_run=True)
    generation_modes: list[bool] = []
    console, _ = _console()
    input_source = ScriptedInput(
        [
            char("2"),
            KeyPress(key=Key.ENTER),
            char("q"),
            char("q"),
        ]
    )

    run_interactive(
        actions=_actions(draft, generation_modes=generation_modes),
        input_source=input_source,
        console=console,
    )

    assert generation_modes == [False]
