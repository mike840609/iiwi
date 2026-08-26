from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console

from iiwi import config_store
from iiwi.interactive.controller import (
    InteractiveActions,
    _settings_edit_key,
    _settings_key,
    _State,
    run_interactive,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft, Screen
from iiwi.interactive.render import (
    render_settings,
    settings_capacity,
    settings_display_count,
    settings_display_index,
)
from iiwi.interactive.settings import SettingsRow, build_settings_rows
from iiwi.models.time_range import DateRange

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


def _actions() -> InteractiveActions:
    draft = ReportDraft(harness="opencode", period=_period())
    return InteractiveActions(
        new_draft=lambda: draft,
        choose_harness=lambda current: current,
        choose_period=lambda current: ("Last week", _period()),
        scan=lambda current: None,
        generate=lambda current, scan, force: None,
        synthesize=lambda draft, scan, force: None,
        generate_reviewed=lambda draft, scan, review, force: None,
        edit_outcome=lambda outcome: outcome,
        add_outcome=lambda: None,
        edit_gap=lambda label, current: current,
        save_report_type=lambda report_type: None,
        doctor=lambda harness: [],
        restore_selection=lambda harness, period, include_subagents: None,
        save_selection=lambda harness, period, include_subagents, selected: None,
        exclude_repository=lambda repository_id, display_name: "excluded",
    )


def _console(height: int | None = None) -> tuple[Console, StringIO]:
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


def _viewport_settings_rows() -> list[SettingsRow]:
    """Fifteen rows across the four real sections, as the editor builds them."""
    keys = [
        "harnesses.opencode.enabled",
        "harnesses.opencode.source",
        "harnesses.opencode.cli.executable",
        "harnesses.opencode.cli.timeout_seconds",
        "harnesses.opencode.cli.run_timeout_seconds",
        "harnesses.opencode.cli.model",
        "harnesses.opencode.cli.sanitize",
        "harnesses.claude_code.enabled",
        "harnesses.claude_code.projects_directory",
        "harnesses.codex.enabled",
        "harnesses.codex.home_directory",
        "report.output_directory",
        "report.exclude_repositories",
        "report.quick_review_report_type",
        "report.quick_review_max_evidence_bytes",
    ]
    sections = [
        "OpenCode",
        "OpenCode",
        "OpenCode",
        "OpenCode",
        "OpenCode",
        "OpenCode",
        "OpenCode",
        "Claude Code",
        "Claude Code",
        "Codex",
        "Codex",
        "General",
        "General",
        "General",
        "General",
    ]
    return [
        SettingsRow(
            key=key,
            label=key.removeprefix("harnesses."),
            value="true",
            source="default",
            default="true",
            choices=("true", "false"),
            show_all=True,
            locked=False,
            variable=f"IIWI_TEST_{index}",
            section=section,
        )
        for index, (key, section) in enumerate(zip(keys, sections, strict=True))
    ]


def _open_settings(keys: list[KeyPress]) -> list[KeyPress]:
    return [char("6"), KeyPress(key=Key.ENTER), *keys]


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    for variable in (
        "IIWI_HARNESSES__OPENCODE__ENABLED",
        "IIWI_HARNESSES__OPENCODE__SOURCE",
        "IIWI_HARNESSES__OPENCODE__CLI__EXECUTABLE",
        "IIWI_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS",
        "IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS",
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL",
        "IIWI_HARNESSES__OPENCODE__CLI__SANITIZE",
        "IIWI_HARNESSES__CLAUDE_CODE__ENABLED",
        "IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY",
        "IIWI_HARNESSES__CODEX__ENABLED",
        "IIWI_HARNESSES__CODEX__HOME_DIRECTORY",
        "IIWI_REPORT__TIMEZONE",
        "IIWI_REPORT__OUTPUT_DIRECTORY",
        "IIWI_REPORT__EXCLUDE_REPOSITORIES",
        "IIWI_REPORT__QUICK_REVIEW_REPORT_TYPE",
        "IIWI_REPORT__QUICK_REVIEW_MAX_EVIDENCE_BYTES",
    ):
        monkeypatch.delenv(variable, raising=False)
    return path


def test_cycling_a_choice_writes_through_config_store(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings(
                [
                    KeyPress(key=Key.RIGHT),
                    char("q"),
                    char("q"),
                ]
            )
        ),
        console=console,
    )

    assert config_store.stored_values(config_file) == {
        "IIWI_HARNESSES__OPENCODE__ENABLED": "false"
    }
    assert "true / false" in stream.getvalue()


def test_cycling_back_restores_the_original_value(config_file: Path) -> None:
    config_store.set_value("report.quick_review_report_type", "engineering")
    console, _ = _console()
    downs = [KeyPress(key=Key.DOWN)] * 13  # cursor 0 -> 13 (report.quick_review_report_type)

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings([*downs, KeyPress(key=Key.LEFT), char("q"), char("q")])
        ),
        console=console,
    )

    assert config_store.stored_values(config_file) == {
        "IIWI_REPORT__QUICK_REVIEW_REPORT_TYPE": "manager"
    }


def test_editing_a_free_text_row_writes_the_value(config_file: Path) -> None:
    console, stream = _console()
    downs = [KeyPress(key=Key.DOWN)] * 5  # cursor 0 -> 5 (opencode.cli.model)

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings(
                [
                    *downs,
                    KeyPress(key=Key.ENTER),
                    *[char(c) for c in "deepseek-r1"],
                    KeyPress(key=Key.ENTER),
                    char("q"),
                    char("q"),
                    char("q"),
                ]
            )
        ),
        console=console,
    )

    assert config_store.stored_values(config_file) == {
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL": "deepseek-r1"
    }
    assert "harnesses.opencode.cli.model []: deepseek-r1" in stream.getvalue()


def test_editing_with_an_empty_value_restores_the_default(config_file: Path) -> None:
    config_store.set_value("report.output_directory", "out")
    downs = [KeyPress(key=Key.DOWN)] * 11  # cursor 0 -> 11 (report.output_directory)
    console, _ = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings(
                [
                    *downs,
                    KeyPress(key=Key.ENTER),  # prefilled "out"
                    KeyPress(key=Key.BACKSPACE),
                    KeyPress(key=Key.BACKSPACE),
                    KeyPress(key=Key.BACKSPACE),
                    KeyPress(key=Key.ENTER),
                    char("q"),
                    char("q"),
                    char("q"),
                ]
            )
        ),
        console=console,
    )

    assert config_store.stored_values(config_file) == {}


def test_escape_cancels_the_editor_without_writing(config_file: Path) -> None:
    downs = [KeyPress(key=Key.DOWN)] * 5
    console, _ = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings(
                [
                    *downs,
                    KeyPress(key=Key.ENTER),
                    *[char(c) for c in "deepseek-r1"],
                    KeyPress(key=Key.ESCAPE),
                    char("q"),
                    char("q"),
                ]
            )
        ),
        console=console,
    )

    assert not config_file.exists()


def test_an_invalid_value_keeps_the_old_value_and_shows_the_error(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downs = [KeyPress(key=Key.DOWN)] * 3  # cursor 0 -> 3 (timeout_seconds)
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings(
                [
                    *downs,
                    KeyPress(key=Key.ENTER),
                    *[char(c) for c in "abc"],
                    KeyPress(key=Key.ENTER),  # validation fails; editor stays open
                    KeyPress(key=Key.ESCAPE),  # cancel the still-open editor
                    char("q"),
                    char("q"),
                ]
            )
        ),
        console=console,
    )

    assert config_store.stored_values(config_file) == {}
    assert "invalid value" in stream.getvalue()


@pytest.mark.parametrize("typed", ["0", "-1"])
def test_a_too_small_evidence_budget_is_not_written_and_shows_the_error(
    config_file: Path, typed: str
) -> None:
    # cursor 0 -> 14 (report.quick_review_max_evidence_bytes), the last row  # noqa: E501
    downs = [KeyPress(key=Key.DOWN)] * 14  # cursor 0 -> 14 (report.quick_review_max_evidence_bytes), the last row  # noqa: E501
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings(
                [
                    *downs,
                    KeyPress(key=Key.ENTER),
                    # The editor prefills the current "40000"; clear it before
                    # typing, or the digits only extend the default.
                    *([KeyPress(key=Key.BACKSPACE)] * 5),
                    *[char(c) for c in typed],
                    KeyPress(key=Key.ENTER),  # validation fails; editor stays open
                    KeyPress(key=Key.ESCAPE),  # cancel the still-open editor
                    char("q"),
                    char("q"),
                ]
            )
        ),
        console=console,
    )

    assert config_store.stored_values(config_file) == {}
    assert "invalid value for report.quick_review_max_evidence_bytes" in stream.getvalue()


def test_editing_the_evidence_budget_row_to_the_smallest_budget_writes_it(
    config_file: Path,
) -> None:
    # cursor 0 -> 14 (report.quick_review_max_evidence_bytes), the last row  # noqa: E501
    downs = [KeyPress(key=Key.DOWN)] * 14  # cursor 0 -> 14 (report.quick_review_max_evidence_bytes), the last row  # noqa: E501
    console, _ = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings(
                [
                    *downs,
                    KeyPress(key=Key.ENTER),
                    *([KeyPress(key=Key.BACKSPACE)] * 5),
                    *[char(c) for c in "1000"],
                    KeyPress(key=Key.ENTER),
                    char("q"),
                    char("q"),
                ]
            )
        ),
        console=console,
    )

    assert config_store.stored_values(config_file) == {
        "IIWI_REPORT__QUICK_REVIEW_MAX_EVIDENCE_BYTES": "1000"
    }


def test_environment_rows_are_locked(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IIWI_REPORT__OUTPUT_DIRECTORY", "/tmp/out")
    downs = [KeyPress(key=Key.DOWN)] * 11  # cursor 0 -> 11 (report.output_directory)
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings(
                [
                    *downs,
                    KeyPress(key=Key.RIGHT),
                    KeyPress(key=Key.ENTER),
                    char("q"),
                    char("q"),
                ]
            )
        ),
        console=console,
    )

    assert not config_file.exists()
    assert "[environment]" in stream.getvalue()


def test_back_returns_to_the_main_menu(config_file: Path) -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings(
                [
                    char("b"),
                    char("q"),
                ]
            )
        ),
        console=console,
    )

    text = stream.getvalue()
    first_menu = text.index("Review Activity")
    settings_frame = text.index("opencode.enabled")
    assert first_menu < settings_frame < text.rindex("Review Activity")


def test_question_mark_types_into_inline_editor(config_file: Path) -> None:
    console, stream = _console()
    downs = [KeyPress(key=Key.DOWN)] * 5
    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings(
                [
                    *downs,
                    KeyPress(key=Key.ENTER),
                    char("?"),
                    char("0"),
                    KeyPress(key=Key.ENTER),
                    char("q"),
                    char("q"),
                    char("q"),
                ]
            )
        ),
        console=console,
    )
    assert config_store.stored_values(config_file) == {
        "IIWI_HARNESSES__OPENCODE__CLI__MODEL": "?0"
    }
    assert "Keyboard shortcuts" not in stream.getvalue()


def test_settings_offset_follows_the_cursor_and_saturates_at_the_end() -> None:
    rows = _viewport_settings_rows()
    count = settings_display_count(rows)
    capacity = settings_capacity(16, terminal_width=80)
    body = max(1, capacity - 2)  # the ↑/↓ indicators each take a display slot
    assert count > capacity  # height 16 really clips

    state = _State(screen=Screen.SETTINGS, settings_rows=rows)
    console, _ = _console(height=16)

    _settings_key(state, KeyPress(key=Key.DOWN), console)
    _settings_key(state, KeyPress(key=Key.DOWN), console)
    assert state.settings_offset == 0

    seen = {state.settings_offset}
    while state.settings_cursor < len(rows) - 1:
        _settings_key(state, KeyPress(key=Key.DOWN), console)
        selected = settings_display_index(rows, state.settings_cursor)
        assert state.settings_offset <= selected
        assert selected < state.settings_offset + capacity
        seen.add(state.settings_offset)
    assert max(seen) == count - body

    _settings_key(state, KeyPress(key=Key.DOWN), console)
    _settings_key(state, KeyPress(key=Key.DOWN), console)
    assert state.settings_offset == count - body

    while state.settings_cursor > 0:
        _settings_key(state, KeyPress(key=Key.UP), console)
        selected = settings_display_index(rows, state.settings_cursor)
        assert state.settings_offset <= selected
        assert selected < state.settings_offset + capacity
    assert state.settings_offset == 0


def test_space_and_delete_in_settings_inline_editor() -> None:
    state = _State(screen=Screen.SETTINGS)
    state.settings_rows = build_settings_rows()
    state.settings_cursor = next(
        index
        for index, row in enumerate(state.settings_rows)
        if row.editable and not row.locked
    )
    state.settings_editing = True
    state.settings_edit_value = "hello"

    # Test typing space
    _settings_edit_key(state, KeyPress(key=Key.SPACE))
    assert state.settings_edit_value == "hello "

    # Test typing character
    _settings_edit_key(state, KeyPress(char="w"))
    assert state.settings_edit_value == "hello w"

    # Test delete key
    _settings_edit_key(state, KeyPress(key=Key.DELETE))
    assert state.settings_edit_value == "hello "


def test_settings_editing_hint_does_not_advertise_help() -> None:
    rows = build_settings_rows()
    console, stream = _console()
    render_settings(
        console,
        rows=rows,
        selected=0,
        file_path="config.env",
        editing=True,
        edit_value="test",
        error=None,
    )
    output = stream.getvalue()
    assert "Enter Keep" in output
    assert "Esc Cancel" in output
    assert "? Help" not in output


def test_a_disabled_harness_row_refuses_cycle_and_edit(
    config_file: Path,
) -> None:
    config_store.set_value("harnesses.claude_code.enabled", "false")
    downs = [KeyPress(key=Key.DOWN)] * 8  # cursor 0 -> 8 (projects_directory)
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            _open_settings(
                [
                    *downs,
                    KeyPress(key=Key.RIGHT),
                    KeyPress(key=Key.ENTER),
                    char("q"),
                    char("q"),
                ]
            )
        ),
        console=console,
    )

    assert config_store.stored_values(config_file) == {
        "IIWI_HARNESSES__CLAUDE_CODE__ENABLED": "false"
    }
    assert "Claude Code is disabled" in stream.getvalue()


def test_enabling_the_harness_restores_editability(config_file: Path) -> None:
    config_store.set_value("harnesses.claude_code.enabled", "false")
    state = _State(screen=Screen.SETTINGS, settings_rows=build_settings_rows())
    console, _ = _console()

    state.settings_cursor = 8  # harnesses.claude_code.projects_directory
    _settings_key(state, KeyPress(key=Key.ENTER), console)
    assert state.settings_editing is False  # refused while disabled

    state.settings_cursor = 7  # harnesses.claude_code.enabled
    _settings_key(state, KeyPress(key=Key.RIGHT), console)  # cycles false -> true
    assert state.settings_cursor == 7
    assert state.settings_rows[7].value == "true"

    state.settings_cursor = 8
    _settings_key(state, KeyPress(key=Key.ENTER), console)
    assert state.settings_editing is True
    assert state.settings_rows[8].key == "harnesses.claude_code.projects_directory"


def test_hybrid_row_left_right_cycles_preset(config_file: Path) -> None:
    key = "harnesses.opencode.cli.timeout_seconds"
    config_store.set_value(key, "30")
    console, _ = _console()
    from iiwi.interactive.controller import _settings_key, _State

    state = _State(screen=Screen.SETTINGS, settings_rows=build_settings_rows())
    idx = next(i for i, r in enumerate(state.settings_rows) if r.key == key)
    state.settings_cursor = idx
    _settings_key(state, KeyPress(key=Key.RIGHT), console)
    stored = config_store.stored_values(config_file)
    assert stored["IIWI_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS"] == "60"


def test_hybrid_row_enter_opens_editor_for_custom_value(config_file: Path) -> None:
    console, _ = _console()
    from iiwi.interactive.controller import _settings_key, _State

    key = "harnesses.opencode.cli.timeout_seconds"
    state = _State(screen=Screen.SETTINGS, settings_rows=build_settings_rows())
    idx = next(i for i, r in enumerate(state.settings_rows) if r.key == key)
    state.settings_cursor = idx
    _settings_key(state, KeyPress(key=Key.ENTER), console)
    assert state.settings_editing is True
    for _ in range(len(state.settings_edit_value)):
        _settings_key(state, KeyPress(key=Key.BACKSPACE), console)
    for ch in "999":
        _settings_key(state, KeyPress(char=ch), console)
    _settings_key(state, KeyPress(key=Key.ENTER), console)
    stored = config_store.stored_values(config_file)
    assert stored["IIWI_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS"] == "999"


def test_locked_hybrid_row_refuses_cycle_and_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IIWI_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS", "30")
    console, _ = _console()
    from iiwi.interactive.controller import _settings_key, _State

    key = "harnesses.opencode.cli.timeout_seconds"
    state = _State(screen=Screen.SETTINGS, settings_rows=build_settings_rows())
    idx = next(i for i, r in enumerate(state.settings_rows) if r.key == key)
    state.settings_cursor = idx
    assert state.settings_rows[idx].locked is True
    _settings_key(state, KeyPress(key=Key.RIGHT), console)
    assert state.settings_editing is False
    _settings_key(state, KeyPress(key=Key.ENTER), console)
    assert state.settings_editing is False

