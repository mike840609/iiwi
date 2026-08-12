# Settings Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the interactive menu's Settings entry (currently the linear `iiwi config init` text wizard) with a full-screen settings editor: every setting is a row showing its current value, choice rows list all options separated by ` / ` with the active one highlighted, free-text rows edit inline on Enter, and changes persist immediately through `config_store`.

**Architecture:** A new `src/iiwi/interactive/settings.py` module derives editor rows from `config_store.setting_keys()` / `describe_settings()` (same source as `config list`, so precedence and source labels match exactly) and owns choice derivation, cycling, and persistence. A new `Screen.SETTINGS` in the existing state-machine controller renders via a new `render_settings` in render.py and handles keys in a new `_settings_key` handler. The `edit_settings` action seam is removed; the CLI `iiwi config init` command is untouched.

**Tech Stack:** Python, Rich, Typer, pydantic annotations, existing `iiwi.config_store`, `iiwi.interactive.{controller,render,models,input}`.

## Global Constraints

- Choice rows show EVERY choice in one row, joined by ` / `; the choice in force renders in `_CURSOR_STYLE` (`"bold cyan"`), the others `dim`. Never a lone value.
- The timezone row is the exception: it shows only its current value (nine zones do not fit a row); `←→` still steps the curated shortlist and Enter edits any IANA zone.
- Empty values render as dim `(default)`, never blank.
- Environment-sourced rows render a dim `[environment]` tag and are locked: `←→` and Enter do nothing on them.
- Writes go through `config_store.set_value` / `config_store.unset_value` immediately (empty typed value = restore default, matching `config set <key> ""`). `validate_value` runs before any write; on failure the editor stays open, shows the error on the detail line, and the stored value is untouched.
- Settings rows are derived, never hand-kept: a new field in `config.py` appears here automatically. The only hand-kept maps are the timezone shortlist and `source`/`timezone` key overrides.
- Row labels are the dotted key with the `harnesses.` prefix stripped (`opencode.enabled`, `report.timezone`); prompts and detail lines use the full dotted key.
- No changes to `iiwi config init` / `config set` / `config unset`, their tests, or the legacy typer fallback menu in `cli.py:_interactive_menu`.
- Validation-error display is the outcome-review message pattern (inline detail line), not the RECOVERABLE_ERROR screen — a small deviation from the spec's "error state" wording that keeps the user inside the editor.

Spec: `docs/2026-08-13-settings-editor-design.md`

---

### Task 1: Settings row model, derivation, and persistence

**Files:**
- Create: `src/iiwi/interactive/settings.py`
- Create: `tests/unit/interactive/test_settings.py`

**Interfaces:**
- Consumes: `config_store.setting_keys()`, `config_store.describe_settings()`, `config_store.set_value`, `config_store.unset_value`, `ConfigurationError`, `ReportType` (all exist).
- Produces:
  - `SettingsRow` dataclass with fields: `key: str`, `label: str`, `value: str`, `source: str`, `default: str`, `choices: tuple[str, ...]`, `show_all: bool`, `locked: bool`, `variable: str`; plus property `editable: bool` (`not show_all`).
  - `build_settings_rows() -> list[SettingsRow]`
  - `next_choice(row: SettingsRow, value: str, *, right: bool) -> str`
  - `write_setting(key: str, value: str) -> None`
  - Module constants `TIMEZONE_CHOICES`, `_KEY_CHOICES` (private).
  - `SettingsRow` is consumed by Task 2's `render_settings`; `build_settings_rows`, `next_choice`, `write_setting` by Task 3's controller.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/interactive/test_settings.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from iiwi import config_store
from iiwi.errors import ConfigurationError
from iiwi.interactive.settings import (
    TIMEZONE_CHOICES,
    SettingsRow,
    build_settings_rows,
    next_choice,
    write_setting,
)
from iiwi.models.report_options import ReportType


def _row(**overrides: object) -> SettingsRow:
    fields = dict(
        key="report.timezone",
        label="timezone",
        value="Asia/Taipei",
        source="default",
        default="Asia/Taipei",
        choices=TIMEZONE_CHOICES,
        show_all=False,
        locked=False,
        variable="IIWI_REPORT__TIMEZONE",
    )
    fields.update(overrides)
    return SettingsRow(**fields)


def test_choices_follow_each_setting_annotation() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.opencode.enabled"].choices == ("true", "false")
    assert rows["harnesses.opencode.cli.sanitize"].choices == ("true", "false")
    assert rows["report.quick_review_report_type"].choices == (
        tuple(member.value for member in ReportType)
    )
    assert rows["harnesses.opencode.source"].choices == ("cli",)
    assert rows["report.timezone"].choices == TIMEZONE_CHOICES
    assert rows["harnesses.opencode.cli.model"].choices == ()
    assert rows["harnesses.opencode.cli.model"].show_all is False


def test_choice_rows_show_all_and_timezone_does_not() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.opencode.enabled"].show_all is True
    assert rows["report.quick_review_report_type"].show_all is True
    assert rows["report.timezone"].show_all is False
    assert rows["report.timezone"].editable is True
    assert rows["harnesses.opencode.enabled"].editable is False


def test_labels_strip_the_harnesses_prefix() -> None:
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.opencode.cli.executable"].label == "opencode.cli.executable"
    assert rows["report.timezone"].label == "report.timezone"


def test_environment_sourced_rows_are_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IIWI_REPORT__TIMEZONE", "UTC")
    rows = {row.key: row for row in build_settings_rows()}
    timezone = rows["report.timezone"]
    assert timezone.value == "UTC"
    assert timezone.locked is True
    assert timezone.variable == "IIWI_REPORT__TIMEZONE"


def test_file_sourced_rows_are_not_locked(config_file: Path) -> None:
    config_store.set_value("report.timezone", "Europe/Berlin")
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["report.timezone"].source == "file"
    assert rows["report.timezone"].locked is False


def test_next_choice_wraps_at_both_ends() -> None:
    row = _row()
    assert next_choice(row, "Asia/Taipei", right=True) == "Asia/Shanghai"
    assert next_choice(row, "UTC", right=True) == "Asia/Taipei"
    assert next_choice(row, "Asia/Taipei", right=False) == "UTC"


def test_next_choice_steps_off_an_out_of_list_value() -> None:
    row = _row(value="Europe/Paris")
    assert next_choice(row, "Europe/Paris", right=True) == "Asia/Taipei"
    assert next_choice(row, "Europe/Paris", right=False) == "UTC"


def test_next_choice_is_a_noop_without_choices() -> None:
    row = _row(choices=())
    assert next_choice(row, "anything", right=True) == "anything"


def test_write_setting_persists_a_value(config_file: Path) -> None:
    write_setting("report.timezone", "Europe/Berlin")
    assert config_store.stored_values(config_file) == {
        "IIWI_REPORT__TIMEZONE": "Europe/Berlin"
    }


def test_write_setting_empty_restores_the_default(config_file: Path) -> None:
    write_setting("report.timezone", "Europe/Berlin")
    write_setting("report.timezone", "")
    assert config_store.stored_values(config_file) == {}


def test_write_setting_rejects_an_invalid_value(config_file: Path) -> None:
    with pytest.raises(ConfigurationError):
        write_setting("harnesses.opencode.cli.timeout_seconds", "abc")
    assert not config_file.exists()
```

Note: `write_setting` resolves the file through the `IIWI_CONFIG_FILE`
variable, so every test that writes needs the `config_file` fixture to pin
it to a temp path. Add it near the top of the test module (after the
imports):

```python
@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.env"
    monkeypatch.setenv("IIWI_CONFIG_FILE", str(path))
    monkeypatch.delenv("IIWI_REPORT__TIMEZONE", raising=False)
    monkeypatch.delenv("IIWI_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS", raising=False)
    return path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'iiwi.interactive.settings'`.

- [ ] **Step 3: Implement `settings.py`**

Create `src/iiwi/interactive/settings.py`:

```python
"""Settings rows for the interactive settings editor."""

from __future__ import annotations

from dataclasses import dataclass

from iiwi import config_store
from iiwi.models.report_options import ReportType

# A hand-kept shortlist, not the ~600-entry IANA set: the row shows one value
# anyway, and Enter on the row types any zone the shortlist omits.
TIMEZONE_CHOICES = (
    "Asia/Taipei",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Asia/Singapore",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Los_Angeles",
    "UTC",
)

# Keys whose choices a plain string annotation cannot express. `source` has
# one implemented value, so its "choices" are a single-entry list.
_KEY_CHOICES = {
    "harnesses.opencode.source": ("cli",),
    "report.timezone": TIMEZONE_CHOICES,
}


@dataclass(frozen=True)
class SettingsRow:
    """One setting as the editor shows it: value, source, and how to change it."""

    key: str
    label: str
    value: str
    source: str
    default: str
    choices: tuple[str, ...]
    show_all: bool
    locked: bool
    variable: str

    @property
    def editable(self) -> bool:
        """Enter opens the inline editor (free text or an out-of-list timezone)."""
        return not self.show_all


def _label(key: str) -> str:
    """The row label: the dotted key without the `harnesses.` prefix."""
    return key.removeprefix("harnesses.")


def _choices_for(annotation: type, key: str) -> tuple[str, ...]:
    if key in _KEY_CHOICES:
        return _KEY_CHOICES[key]
    if annotation is bool:
        return ("true", "false")
    if annotation is ReportType:
        return tuple(member.value for member in ReportType)
    return ()


def _show_all(key: str, choices: tuple[str, ...]) -> bool:
    """Which rows render every choice: enum/bool rows yes, timezone no."""
    return key != "report.timezone" and bool(choices)


def build_settings_rows() -> list[SettingsRow]:
    """Build editor rows from the same source `config list` uses."""

    keys = {setting.key: setting for setting in config_store.setting_keys()}
    rows = []
    for row in config_store.describe_settings():
        setting = keys[row.key]
        choices = _choices_for(setting.annotation, row.key)
        rows.append(
            SettingsRow(
                key=row.key,
                label=_label(row.key),
                value=row.value,
                source=row.source,
                default=row.default,
                choices=choices,
                show_all=_show_all(row.key, choices),
                locked=row.source == "environment",
                variable=setting.variable,
            )
        )
    return rows


def next_choice(row: SettingsRow, value: str, *, right: bool) -> str:
    """The choice one step around the row's list, wrapping at both ends."""

    if not row.choices:
        return value
    try:
        index = row.choices.index(value)
    except ValueError:
        # The value in force is outside the cycle list (e.g. a custom
        # timezone); the first step from it lands on the nearest end.
        return row.choices[0] if right else row.choices[-1]
    step = 1 if right else -1
    return row.choices[(index + step) % len(row.choices)]


def write_setting(key: str, value: str) -> None:
    """Persist one setting; an empty value restores the default.

    Raises ConfigurationError when the value is invalid or the file cannot
    be written; the editor keeps its previous value in that case.
    """

    if not value:
        config_store.unset_value(key)
    else:
        config_store.set_value(key, value)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_settings.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Lint and typecheck**

Run: `uv run ruff check src/iiwi/interactive/settings.py tests/unit/interactive/test_settings.py && uv run pyright`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/interactive/settings.py tests/unit/interactive/test_settings.py
git commit -m "feat: derive settings editor rows from config_store"
```

---

### Task 2: Settings screen rendering

**Files:**
- Modify: `src/iiwi/interactive/render.py` (imports + new `_SETTINGS_HELP` near line 82 + new `render_settings` after `render_report_setup`, ~line 1029)
- Test: `tests/unit/interactive/test_render.py` (append near the end)

**Interfaces:**
- Consumes: `SettingsRow` from Task 1; existing `_print_header`, `_print_viewport_line`, `_print_viewport_text`, `_print_hints`, `_CURSOR_STYLE`, `_CURSOR`, `_MIN_SUBTITLE_HEIGHT`, `cell_len` (all in render.py).
- Produces: `render_settings(console, *, rows, selected, file_path, editing=False, edit_value="", error=None) -> None`. Task 3's `_render_screen` calls it.

- [ ] **Step 1: Write the failing render tests**

First update the imports at the top of `tests/unit/interactive/test_render.py` (after the `from iiwi.interactive.selection import SelectionState` line):

```python
from iiwi.interactive.settings import SettingsRow, TIMEZONE_CHOICES
```

and add `render_settings` to the existing `from iiwi.interactive.render import (...)` block (alphabetical, after `render_report_setup`).

Then append at the end of the file (no imports inside the append — they live at the top, and ruff's E402 forbids mid-file imports):

```python
def _settings_row(**overrides: object) -> SettingsRow:
    fields = dict(
        key="harnesses.opencode.enabled",
        label="opencode.enabled",
        value="true",
        source="default",
        default="true",
        choices=("true", "false"),
        show_all=True,
        locked=False,
        variable="IIWI_HARNESSES__OPENCODE__ENABLED",
    )
    fields.update(overrides)
    return SettingsRow(**fields)


def test_settings_renders_choice_rows_with_every_option() -> None:
    console, stream = _console()
    rows = [
        _settings_row(),
        _settings_row(
            key="harnesses.opencode.cli.model",
            label="opencode.cli.model",
            value="",
            default="",
            choices=(),
            show_all=False,
        ),
    ]

    render_settings(console, rows=rows, selected=0, file_path="/tmp/config.env")

    text = stream.getvalue()
    assert "Settings" in text
    assert "Settings file: /tmp/config.env" in text
    assert "opencode.enabled" in text
    assert "true / false" in text
    assert "(default)" in text


def test_settings_highlights_only_the_active_choice() -> None:
    console, stream = _color_console()

    render_settings(
        console,
        rows=[
            _settings_row(value="false"),
            _settings_row(
                key="report.quick_review_report_type",
                label="quick_review_report_type",
                value="engineering",
                choices=("manager", "engineering"),
            ),
        ],
        selected=1,
        file_path="/tmp/config.env",
    )

    text = stream.getvalue()
    # Active choices are bold cyan; the rest are dim.
    assert "\x1b[1;36mfalse\x1b[0m" in text
    assert "\x1b[2mtrue\x1b[0m" in text
    assert "\x1b[1;36mengineering\x1b[0m" in text
    assert "\x1b[2mmanager\x1b[0m" in text


def test_settings_marks_environment_rows_as_locked() -> None:
    console, stream = _console()

    render_settings(
        console,
        rows=[
            _settings_row(
                key="report.timezone",
                label="timezone",
                value="UTC",
                choices=TIMEZONE_CHOICES,
                show_all=False,
                locked=True,
            )
        ],
        selected=0,
        file_path="/tmp/config.env",
    )

    text = stream.getvalue()
    assert "UTC" in text
    assert "[environment]" in text


def test_settings_renders_the_inline_editor_and_hints() -> None:
    console, stream = _console()
    rows = [
        _settings_row(),
        _settings_row(
            key="harnesses.opencode.cli.model",
            label="opencode.cli.model",
            value="",
            default="",
            choices=(),
            show_all=False,
        ),
    ]

    render_settings(
        console,
        rows=rows,
        selected=1,
        file_path="/tmp/config.env",
        editing=True,
        edit_value="deepseek",
    )

    text = stream.getvalue()
    assert "harnesses.opencode.cli.model []: deepseek" in text
    assert "Enter Keep" in text
    assert "Esc Cancel" in text


def test_settings_renders_validation_error_on_the_detail_line() -> None:
    console, stream = _console()

    render_settings(
        console,
        rows=[_settings_row()],
        selected=0,
        file_path="/tmp/config.env",
        editing=True,
        edit_value="abc",
        error="invalid value for harnesses.opencode.cli.timeout_seconds: nope",
    )

    assert "invalid value for harnesses.opencode.cli.timeout_seconds" in stream.getvalue()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_render.py -k settings -v`
Expected: FAIL — `ImportError: cannot import name 'render_settings'`.

- [ ] **Step 3: Implement `render_settings`**

In `src/iiwi/interactive/render.py`:

Add to imports (the `from iiwi.interactive.selection import ...` block or a new line):

```python
from iiwi.interactive.settings import SettingsRow
```

Add near `_SETUP_HELP` (after line 82):

```python
# The settings editor explains each row's purpose on the detail line; the
# row itself always shows its value, never what it does.
_SETTINGS_HELP = {
    "harnesses.opencode.enabled": "False makes --harness opencode fail with a configuration error.",
    "harnesses.opencode.source": "Source identifier; only cli is implemented.",
    "harnesses.opencode.cli.executable": "The opencode executable name or path.",
    "harnesses.opencode.cli.timeout_seconds": "Timeout for opencode commands.",
    "harnesses.opencode.cli.run_timeout_seconds": "How long one opencode run may take before falling back.",
    "harnesses.opencode.cli.model": "Model passed to opencode run; empty uses opencode's default.",
    "harnesses.opencode.cli.sanitize": "Ask opencode export to redact session content.",
    "harnesses.claude_code.enabled": "False forbids reading ~/.claude/projects.",
    "harnesses.claude_code.projects_directory": "Directory holding Claude Code session transcripts.",
    "harnesses.codex.enabled": "False forbids reading ~/.codex.",
    "harnesses.codex.home_directory": "Directory holding the Codex state database and sessions.",
    "report.timezone": "Calendar-week and timestamp timezone; Enter types any IANA zone.",
    "report.output_directory": "Default Markdown output directory.",
    "report.exclude_repositories": "Comma-separated repository ids left out of every scan.",
    "report.quick_review_report_type": "Default Quick Review audience.",
    "report.quick_review_max_evidence_bytes": "Largest evidence payload one Quick Review run may send.",
}
```

Add after `render_report_setup` (after line 1029):

```python
def _settings_value_text(row: SettingsRow) -> Text:
    """The value column: every choice with the active one highlighted, or the
    current value — never blank."""
    if row.show_all:
        parts: list[Text] = []
        for index, choice in enumerate(row.choices):
            if index:
                parts.append(Text(" / "))
            parts.append(
                Text(choice, style=_CURSOR_STYLE if choice == row.value else "dim")
            )
        return Text.assemble(*parts)
    value = Text(row.value) if row.value else Text("(default)", style="dim")
    if row.locked:
        return Text.assemble(value, ("  [environment]", "dim"))
    return value


def render_settings(
    console: Console,
    *,
    rows: list[SettingsRow],
    selected: int,
    file_path: str,
    editing: bool = False,
    edit_value: str = "",
    error: str | None = None,
) -> None:
    """The saved-settings editor: one row per setting, values always visible."""

    _print_header(console, "Settings")
    if console.size.height >= _MIN_SUBTITLE_HEIGHT:
        _print_viewport_line(
            console,
            f"  Settings file: {file_path}",
            style="bright_black",
        )
    console.print()
    label_cells = max((cell_len(row.label) for row in rows), default=0)
    for index, row in enumerate(rows):
        focused = selected == index
        lead = Text(_CURSOR if focused else " ", style=_CURSOR_STYLE if focused else "")
        label = Text(f"{row.label:<{label_cells}}", style=_CURSOR_STYLE if focused else "")
        text = Text.assemble(lead, " ", label, "  ", _settings_value_text(row))
        _print_viewport_text(console, text)
    console.print()
    row = rows[selected]
    if editing:
        _print_viewport_line(
            console,
            f"  {row.key} [{row.value}]: {edit_value}",
            style=_CURSOR_STYLE,
        )
        detail = error or f"{row.key} - Enter keeps the value; empty restores the default."
        _print_viewport_line(console, f"  {detail}", style="dim")
    else:
        detail = (
            f"Set by the {row.variable} environment variable."
            if row.locked
            else _SETTINGS_HELP.get(row.key, "")
        )
        _print_viewport_line(console, f"  {detail}", style="dim")
    console.print()
    _print_hints(
        console,
        ["Enter Keep", "Esc Cancel", "? Help"]
        if editing
        else ["↑↓ jk", "←→ Cycle", "Enter Edit", "? Help", "b Back"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_render.py -k settings -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full interactive render suite**

Run: `uv run pytest tests/unit/interactive/test_render.py tests/unit/interactive/test_render_painting.py -v`
Expected: PASS — the frame-painting machinery must not regress (rows are still exactly one display line each).

- [ ] **Step 6: Lint and typecheck**

Run: `uv run ruff check src/iiwi/interactive/render.py && uv run pyright`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/iiwi/interactive/render.py tests/unit/interactive/test_render.py
git commit -m "feat: render the settings editor screen"
```

---

### Task 3: Controller wiring for the Settings screen

**Files:**
- Modify: `src/iiwi/interactive/models.py` (`Screen` enum, line 17)
- Modify: `src/iiwi/interactive/controller.py` (state, imports, `_main_key` branch at line 392-417, new `_settings_key`/`_settings_edit_key`/`_persist_setting`, `_dispatch` at line 1452, `_idle_interrupt` at line 1425, `_render_screen` at line 1343, `_error_options`/`_error_back_screen` at lines 1091-1126, `InteractiveActions` field at line 99)
- Modify: `src/iiwi/interactive/cli_actions.py` (remove `_edit_settings` at line 338 and `edit_settings=_edit_settings` at line 426)
- Modify: `tests/unit/interactive/test_controller_results.py` (`_actions()` at line 144, `test_settings_completion_returns_through_a_visible_result_screen` at line 166)
- Modify: every other `InteractiveActions(...)` constructor, deleting the `edit_settings=...` line:
  - `tests/unit/interactive/test_controller.py:180`
  - `tests/unit/interactive/test_controller_generation.py:173`
  - `tests/unit/interactive/test_unified_activity_review.py:154`
  - `tests/unit/interactive/test_collapsed_advanced_settings.py:161`
  - `tests/unit/interactive/test_outcome_review_failures.py:212`
  - `tests/unit/interactive/test_outcome_review_controller.py:192, 344, 407`
  - `tests/unit/interactive/test_selection_memory.py:157`
  - `tests/unit/interactive/test_activity_first_home.py:141`
  - `tests/unit/interactive/test_review_regressions.py:201`
  - `tests/unit/interactive/test_interactive_regressions.py:165`
  - `tests/integration/test_interactive_cli.py:223, 301`

**Interfaces:**
- Consumes: `SettingsRow`, `build_settings_rows`, `next_choice`, `write_setting` from Task 1; `render_settings` from Task 2; `config_store.config_file_path`.
- Produces: `Screen.SETTINGS`; `_State` gains `settings_rows: list[SettingsRow] | None`, `settings_cursor: int = 0`, `settings_editing: bool = False`, `settings_edit_value: str = ""`, `settings_error: str | None = None`, `settings_file_path: str | None = None`. `InteractiveActions` loses the `edit_settings` field. `_error_options`/`_error_back_screen` lose their `"settings-result"` branches.

- [ ] **Step 1: Update the existing result-screen test**

In `tests/unit/interactive/test_controller_results.py`:

Replace `edit_settings=lambda: None,` (line 144) — remove the line entirely.

Replace the test (lines 166-177):

```python
def test_settings_entry_opens_the_settings_editor() -> None:
    console, stream = _console()

    run_interactive(
        actions=_actions(),
        input_source=ScriptedInput(
            [
                char("4"),
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/interactive/test_controller_results.py -k settings -v`
Expected: FAIL — `TypeError: InteractiveActions.__init__() missing 1 required keyword-only argument: 'edit_settings'` (the constructor in Step 1 dropped the field, but the dataclass still declares it).

- [ ] **Step 3: Wire the screen into the controller**

In `src/iiwi/interactive/models.py`, add to the `Screen` enum (line 17-28):

```python
    SETTINGS = "settings"
```

In `src/iiwi/interactive/controller.py`:

Add imports (with the other `iiwi.interactive` imports):

```python
from iiwi.interactive.settings import (
    SettingsRow,
    build_settings_rows,
    next_choice,
    write_setting,
)
```

Add to `_State` (after `help_offset: int = 0`, line 144):

```python
    settings_rows: list[SettingsRow] | None = None
    settings_cursor: int = 0
    settings_editing: bool = False
    settings_edit_value: str = ""
    settings_error: str | None = None
    settings_file_path: str | None = None
```

Remove `edit_settings: Callable[[], None]` from `InteractiveActions` (line 99).

Replace the Settings branch of `_main_key` (lines 410-417):

```python
    else:
        state.settings_rows = build_settings_rows()
        state.settings_cursor = 0
        state.settings_editing = False
        state.settings_edit_value = ""
        state.settings_error = None
        state.settings_file_path = str(config_store.config_file_path())
        state.screen = Screen.SETTINGS
```

Add `from iiwi import config_store` to the controller's imports.

Add the three handlers after `_setup_key` (after line 485):

```python
def _persist_setting(state: _State, key: str, value: str) -> None:
    """Write one setting through config_store and refresh the rows on success."""

    try:
        write_setting(key, value)
    except ConfigurationError as exc:
        state.settings_error = str(exc)
        return
    state.settings_error = None
    state.settings_rows = build_settings_rows()


def _settings_edit_key(state: _State, key: KeyPress) -> None:
    """The inline editor: type, backspace, Enter writes, Esc cancels."""

    assert state.settings_rows is not None
    if key.key is Key.ESCAPE:
        state.settings_editing = False
        state.settings_edit_value = ""
        state.settings_error = None
        return
    if key.key is Key.BACKSPACE:
        state.settings_edit_value = state.settings_edit_value[:-1]
        return
    if key.key is Key.ENTER:
        row = state.settings_rows[state.settings_cursor]
        _persist_setting(state, row.key, state.settings_edit_value.strip())
        if state.settings_error is None:
            state.settings_editing = False
            state.settings_edit_value = ""
        return
    if key.char is not None:
        state.settings_edit_value += key.char


def _settings_key(state: _State, key: KeyPress) -> None:
    """The saved-settings editor: cycle choices, edit rows inline, b leaves."""

    assert state.settings_rows is not None
    if state.settings_editing:
        _settings_edit_key(state, key)
        return
    state.settings_cursor = _move(state.settings_cursor, key, len(state.settings_rows))
    if key.key is Key.ESCAPE or _char(key, "b") or _char(key, "q"):
        state.screen = Screen.MAIN
        return
    row = state.settings_rows[state.settings_cursor]
    if row.locked:
        return
    right = key.key is Key.RIGHT or _char(key, "l")
    left = key.key is Key.LEFT or _char(key, "h")
    if (right or left) and row.choices:
        value = next_choice(row, row.value, right=right)
        if value != row.value:
            _persist_setting(state, row.key, value)
        return
    if key.key is Key.ENTER and row.editable:
        state.settings_editing = True
        state.settings_edit_value = row.value
        state.settings_error = None
```

In `_render_screen` (after the REPORT_SETUP branch, line 1353):

```python
    elif state.screen is Screen.SETTINGS:
        assert state.settings_rows is not None
        render_settings(
            console,
            rows=state.settings_rows,
            selected=state.settings_cursor,
            file_path=state.settings_file_path or "",
            editing=state.settings_editing,
            edit_value=state.settings_edit_value,
            error=state.settings_error,
        )
```

In `_dispatch` (after the REPORT_SETUP branch, line 1463):

```python
    elif state.screen is Screen.SETTINGS:
        _settings_key(state, key)
```

In `_idle_interrupt` (after the REPORT_SETUP branch, line 1430):

```python
    elif state.screen is Screen.SETTINGS:
        state.screen = Screen.MAIN
```

In `_error_options` (line 1092) and `_error_back_screen` (line 1116): remove `"settings-result"` from the `{"doctor-result", "settings-result"}` sets — leaving `{"doctor-result"}` / the `doctor-result` branch respectively.

Add `render_settings` to the controller's render import block (near line 34).

- [ ] **Step 4: Remove the settings action seam**

In `src/iiwi/interactive/cli_actions.py`:

Remove the `_edit_settings` function (lines 338-341) and the `edit_settings=_edit_settings,` keyword from `build_interactive_actions` (line 426).

Delete the `edit_settings=...` line from every `InteractiveActions(...)` constructor listed in the Files section (all 13 remaining occurrences — `test_controller_results.py` was handled in Step 1).

- [ ] **Step 5: Run the updated and full controller tests**

Run: `uv run pytest tests/unit/interactive/test_controller_results.py -v`
Expected: PASS.

Then the whole interactive suite plus its integration coverage:

Run: `uv run pytest tests/unit/interactive/ tests/integration/test_interactive_cli.py -v`
Expected: PASS — no constructor may still pass the removed field (a leftover raises TypeError and is caught here).

- [ ] **Step 6: Lint and typecheck**

Run: `uv run ruff check src/iiwi/interactive/ && uv run pyright`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/iiwi/interactive/models.py src/iiwi/interactive/controller.py src/iiwi/interactive/cli_actions.py tests/unit/interactive/test_controller_results.py
git commit -m "feat: open the settings editor from the main menu"
```

---

### Task 4: Controller behavior tests for the settings editor

**Files:**
- Create: `tests/unit/interactive/test_settings_controller.py`

**Interfaces:**
- Consumes: `run_interactive`, `InteractiveActions`, `Key`/`KeyPress` (all existing); `config_store.stored_values`.
- Produces: nothing new — verifies Task 3's wiring.

- [ ] **Step 1: Write the failing behavior tests**

Create `tests/unit/interactive/test_settings_controller.py`:

```python
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
    assert "false / true" in stream.getvalue()


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
                    KeyPress(key=Key.ENTER),  # selects Review Activity
                    char("q"),
                ]
            )
        ),
        console=console,
    )

    text = stream.getvalue()
    assert "Review Activity" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_settings_controller.py -v`
Expected: FAIL — `TypeError` on `InteractiveActions(...)` (missing/extra field) or the settings screen never opens (no `true / false` written).

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_settings_controller.py -v`
Expected: PASS (8 tests).

- [ ] **Step 4: Run the full interactive suite**

Run: `uv run pytest tests/unit/interactive/ -v`
Expected: PASS.

- [ ] **Step 5: Lint and typecheck**

Run: `uv run ruff check tests/unit/interactive/test_settings_controller.py && uv run pyright`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/interactive/test_settings_controller.py
git commit -m "test: cover the settings editor interactions"
```

---

### Task 5: Documentation and full verification

**Files:**
- Modify: `docs/configuration.md` (the "Setting values interactively" section, lines 29-53)
- Modify: `README.md` (the Settings line in the interactive menu section, line 65)

**Interfaces:**
- Consumes: the shipped behavior from Tasks 1-4.
- Produces: docs describing the new editor; nothing code-facing.

- [ ] **Step 1: Update the configuration guide**

In `docs/configuration.md`, after the existing `config init` walk (line 53), add a paragraph pointing at the interactive editor:

```markdown
The interactive menu's **Settings** entry opens a full-screen editor in the
same style as the rest of the menu: every setting is a row showing its
current value. Choice rows (booleans, the Quick Review report type, and the
harness source) list every option separated by ` / `, with the choice in
force highlighted; `←→` cycles them. Free-text rows (model, paths, numbers,
`exclude_repositories`) open an inline editor on Enter, pre-filled with the
current value — Enter keeps it, an empty value restores the default, Esc
cancels. The timezone row cycles a shortlist of common zones; Enter types
any IANA zone. Values set by an `IIWI_*` environment variable are shown
with an `[environment]` tag and cannot be edited from the file. Every
change is written to the settings file immediately; `config list` reflects
it right away.
```

In `README.md`, update the menu description line (line 65) so `Settings`
points at the editor:

```markdown
  Settings
```
becomes
```markdown
  Settings                       # full-screen editor, every choice listed
```

Keep the diff minimal — one line in the mockup block plus the doc paragraph.

- [ ] **Step 2: Run the complete verification battery**

```bash
uv run pytest --cov=iiwi --cov-fail-under=80
uv run ruff check .
uv run pyright
```

Expected: all green — unit, integration, coverage gate, lint, and type
check, exactly what CI runs.

- [ ] **Step 3: Manual smoke test**

Run: `uv run iiwi` in a real terminal, select **Settings** (4, Enter), and verify:

- Every row shows a value or dim `(default)` — nothing blank.
- `←→` on `opencode.enabled` flips between `true` / `false` with the active
  one highlighted and writes `IIWI_HARNESSES__OPENCODE__ENABLED` to the
  settings file (`iiwi config list` shows the file source).
- Enter on the model row pre-fills the current value; typing a model and
  Enter writes it; empty + Enter restores the default.
- `b` returns to the main menu.
- Export `IIWI_REPORT__TIMEZONE=UTC` and confirm the row shows
  `[environment]` and ignores `←→` and Enter.

- [ ] **Step 4: Commit**

```bash
git add docs/configuration.md README.md
git commit -m "docs: describe the interactive settings editor"
```
