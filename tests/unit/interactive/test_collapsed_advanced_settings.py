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


def _actions(draft: ReportDraft) -> InteractiveActions:
    def generate(
        draft_value: ReportDraft,
        scan_value: ScanResult,
        force: bool,
    ) -> InteractiveReportResult:
        return InteractiveReportResult(
            output_path=Path("reports/worklog.md"),
            content="report",
            repository_count=0,
            session_count=0,
        )

    return InteractiveActions(
        new_draft=lambda: draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: ("Last 7 days", _period()),
        scan=lambda draft_value: ScanResult(
            period=_period(),
            candidate_session_count=0,
            loaded_session_count=0,
            failed_session_count=0,
            resolved_sessions=[],
            sessions_by_repository={},
        ),
        generate=generate,
        doctor=lambda harness: [f"{harness}: ok"],
        edit_settings=lambda: None,
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )


def test_setup_rows_hide_advanced_fields_by_default() -> None:
    assert report_setup_rows(advanced=False) == [
        "Generate report",
        "Harness",
        "Period",
        "Advanced settings",
    ]


def test_setup_rows_show_advanced_fields_when_expanded() -> None:
    rows = report_setup_rows(advanced=True)

    assert rows[:4] == [
        "Generate report",
        "Harness",
        "Period",
        "Advanced settings",
    ]
    assert rows[4:] == ["Detail", "Subagents", "Narrative", "Sanitize", "Dry run"]


def test_collapsed_setup_renders_only_primary_controls() -> None:
    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period())

    render_report_setup(console, draft, selected=0, advanced=False)

    text = stream.getvalue()
    assert "Harness" in text
    assert "Period" in text
    assert "Advanced settings" in text
    assert "Detail" not in text
    assert "Subagents" not in text
    assert "Narrative" not in text
    assert "Sanitize" not in text
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
