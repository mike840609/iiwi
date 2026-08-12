from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console

from iiwi import config_store
from iiwi.interactive.controller import InteractiveActions, run_interactive
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft
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
        synthesize=lambda draft, scan: None,
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


def _console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return Console(file=stream, color_system=None, force_terminal=False, width=100), stream


def _open_settings(keys: list[KeyPress]) -> list[KeyPress]:
    return [char("4"), KeyPress(key=Key.ENTER), *keys]


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
    downs = [KeyPress(key=Key.DOWN)] * 14  # cursor 0 -> 14 (report.quick_review_report_type)

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
    downs = [KeyPress(key=Key.DOWN)] * 12  # cursor 0 -> 12 (report.output_directory)
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


def test_environment_rows_are_locked(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IIWI_REPORT__TIMEZONE", "UTC")
    downs = [KeyPress(key=Key.DOWN)] * 11  # cursor 0 -> 11 (report.timezone)
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
