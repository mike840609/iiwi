# Disabled-Harness Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the interactive settings editor, rows under a disabled harness render dim, explain themselves on the detail line, and refuse edits until the harness is re-enabled.

**Architecture:** `SettingsRow` gains a computed `disabled_reason`; `build_settings_rows()` fills it from the current `enabled` values; the renderer mutes unfocused muted rows and swaps the detail-line help for the reason; the controller treats a muted row exactly like a locked one. Row rebuilds after every write give live restore-on-enable for free.

**Tech Stack:** Python 3.11+, pydantic models, Rich `Text` rendering, pytest via `uv run pytest`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-25-disabled-harness-settings-design.md`
- Reason copy verbatim: `"<Label> is disabled; enable <prefix>enabled to make this take effect."` where `<Label>` is the section name (`OpenCode` / `Claude Code` / `Codex`) and `<prefix>` is the dotted key prefix, e.g. `Claude Code is disabled; enable harnesses.claude_code.enabled to make this take effect.`
- Detail-line precedence stays: `error` > locked message > `disabled_reason` > `_SETTINGS_HELP`.
- The `.enabled` row itself and every non-harness row are never disabled.
- Do not touch the CLI (`iiwi config list/set`) or add tags/collapsing.
- Verify each task with: `uv run pytest <changed test files> -v`, then `uv run ruff check .` and `uv run pyright` before committing.

---

### Task 1: `SettingsRow.disabled_reason` computed in `build_settings_rows`

**Files:**
- Modify: `src/iiwi/interactive/settings.py`
- Test: `tests/unit/interactive/test_settings.py`

**Interfaces:**
- Consumes: `config_store.describe_settings()` (rows expose `.key` and `.value` strings) — unchanged.
- Produces: `SettingsRow.disabled_reason: str = ""` (new keyword field, safe default); `build_settings_rows() -> list[SettingsRow]` fills it. Later tasks read `row.disabled_reason` only.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/interactive/test_settings.py`:

```python
def test_a_disabled_harness_mutes_its_other_rows(config_file: Path) -> None:
    config_store.set_value("harnesses.claude_code.enabled", "false")
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.claude_code.projects_directory"].disabled_reason == (
        "Claude Code is disabled; enable harnesses.claude_code.enabled"
        " to make this take effect."
    )


def test_the_enabled_row_itself_is_never_disabled(config_file: Path) -> None:
    config_store.set_value("harnesses.claude_code.enabled", "false")
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["harnesses.claude_code.enabled"].disabled_reason == ""


def test_disabling_opencode_reaches_its_nested_cli_rows(config_file: Path) -> None:
    config_store.set_value("harnesses.opencode.enabled", "false")
    rows = {row.key: row for row in build_settings_rows()}
    reason = rows["harnesses.opencode.cli.executable"].disabled_reason
    assert reason.startswith("OpenCode is disabled;")


def test_non_harness_rows_are_never_disabled(config_file: Path) -> None:
    config_store.set_value("harnesses.claude_code.enabled", "false")
    rows = {row.key: row for row in build_settings_rows()}
    assert rows["report.timezone"].disabled_reason == ""


def test_no_row_is_disabled_while_every_harness_is_enabled() -> None:
    assert all(row.disabled_reason == "" for row in build_settings_rows())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_settings.py -v -k disabled`
Expected: FAIL — `SettingsRow` has no attribute `disabled_reason` (TypeError in the `_row`-style constructors / dataclass).

- [ ] **Step 3: Implement**

In `src/iiwi/interactive/settings.py`:

Add the field after `section` (keyword use everywhere keeps positions stable):

```python
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
    section: str = ""
    # Why Enter and ←→ must ignore this row right now, or "" while it may be
    # changed. Non-empty only under a harness whose `enabled` is false.
    disabled_reason: str = ""
```

Add the helper next to `_section_for` (reuses `_SECTION_LABELS`; `report.*` falls through because `values.get("report.enabled")` is never `"false"`):

```python
def _disabled_reason(key: str, values: dict[str, str]) -> str:
    """Why the editor refuses to touch this row, or "" while it stays live."""

    for prefix, label in _SECTION_LABELS.items():
        if not key.startswith(prefix):
            continue
        enabled_key = f"{prefix}enabled"
        if key == enabled_key or values.get(enabled_key) != "false":
            break
        return (
            f"{label} is disabled; enable {enabled_key}"
            " to make this take effect."
        )
    return ""
```

Rewrite `build_settings_rows` to read the values once, then annotate:

```python
def build_settings_rows() -> list[SettingsRow]:
    """Build editor rows from the same source `config list` uses."""

    keys = {setting.key: setting for setting in config_store.setting_keys()}
    described = config_store.describe_settings()
    values = {row.key: row.value for row in described}
    rows = []
    for row in described:
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
                section=_section_for(row.key),
                disabled_reason=_disabled_reason(row.key, values),
            )
        )
    return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_settings.py -v`
Expected: PASS (all, including the pre-existing ones).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run pyright
git add src/iiwi/interactive/settings.py tests/unit/interactive/test_settings.py
git commit -m "feat: mark settings rows under a disabled harness with a reason"
```

---

### Task 2: Renderer mutes disabled rows and explains them on the detail line

**Files:**
- Modify: `src/iiwi/interactive/render.py:1490-1707` (`_settings_value_text`, `_settings_display_items`, `render_settings`)
- Test: `tests/unit/interactive/test_render.py`

**Interfaces:**
- Consumes: `SettingsRow.disabled_reason: str` from Task 1; existing `_CURSOR_STYLE`, `_SETTINGS_HELP`.
- Produces: `_settings_value_text(row: SettingsRow, *, muted: bool = False) -> Text` — new keyword-only parameter, default keeps the old signature working. No other exported surface changes.

- [ ] **Step 1: Write the failing tests**

The file already defines `_settings_row(**overrides)` (line 1109) and `_color_console()`; ANSI dim is `\x1b[2m…\x1b[0m` and the cursor style `\x1b[1;36m…\x1b[0m`. Append:

```python
_DISABLED_REASON = (
    "Claude Code is disabled; enable harnesses.claude_code.enabled"
    " to make this take effect."
)


def test_settings_dims_an_unfocused_disabled_row() -> None:
    console, stream = _color_console()

    render_settings(
        console,
        rows=[
            _settings_row(disabled_reason=_DISABLED_REASON),
            _settings_row(
                key="harnesses.codex.home_directory",
                label="codex.home_directory",
                value=str(Path.home() / ".codex"),
                default=str(Path.home() / ".codex"),
                choices=(),
                show_all=False,
                section="Codex",
            ),
        ],
        selected=1,
        file_path="/tmp/config.env",
    )

    text = stream.getvalue()
    # The muted row's label goes dim. label_cells pads to the longest
    # label (20 cells), so "opencode.enabled" carries four trailing spaces
    # inside the escape pair.
    assert "\x1b[2mopencode.enabled    \x1b[0m" in text
    # …its active choice loses the highlight entirely…
    assert "\x1b[1;36mtrue\x1b[0m" not in text
    # …and its inactive choice is already dim.
    assert "\x1b[2mfalse\x1b[0m" in text


def test_a_focused_disabled_row_keeps_the_cursor_highlight() -> None:
    console, stream = _color_console()

    render_settings(
        console,
        rows=[_settings_row(disabled_reason=_DISABLED_REASON)],
        selected=0,
        file_path="/tmp/config.env",
    )

    text = stream.getvalue()
    assert "\x1b[1;36mtrue\x1b[0m" in text


def test_settings_shows_the_disabled_reason_on_the_detail_line() -> None:
    console, stream = _console()

    render_settings(
        console,
        rows=[_settings_row(disabled_reason=_DISABLED_REASON)],
        selected=0,
        file_path="/tmp/config.env",
    )

    text = stream.getvalue()
    assert _DISABLED_REASON in text
    # The reason replaces this row's normal help copy (_SETTINGS_HELP,
    # render.py:110): "False makes --harness opencode fail with a
    # configuration error."
    assert "False makes --harness opencode fail" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_render.py -v -k disabled`
Expected: FAIL — `_settings_row()` raises TypeError on the unknown `disabled_reason` override (Task 1 landed the field, so construction succeeds; the failures are the missing dim/reason output).

- [ ] **Step 3: Implement**

In `src/iiwi/interactive/render.py`:

Replace `_settings_value_text` (line 1490):

```python
def _settings_value_text(row: SettingsRow, *, muted: bool = False) -> Text:
    """The value column: every choice with the active one highlighted, or the
    current value — never blank. A muted row drops the active choice's
    highlight so nothing on the line draws the eye."""
    active = "" if muted else _CURSOR_STYLE
    if row.show_all:
        parts: list[Text] = []
        for index, choice in enumerate(row.choices):
            if index:
                parts.append(Text(" / ", style="dim" if muted else ""))
            parts.append(
                Text(choice, style=active if choice == row.value else "dim")
            )
        text = Text.assemble(*parts)
        if row.locked:
            return Text.assemble(text, ("  [environment]", "dim"))
        return text
    if row.value:
        value = Text(row.value, style="dim" if muted else "")
    else:
        value = Text("(default)", style="dim")
    if row.locked:
        return Text.assemble(value, ("  [environment]", "dim"))
    return value
```

In `_settings_display_items` (line 1587), replace the `focused` block and the append:

```python
        focused = selected == index
        style = _CURSOR_STYLE if focused else ("dim" if row.disabled_reason else "")
        lead = Text(_CURSOR if focused else " ", style=style)
        label = Text(f"{row.label:<{label_cells}}", style=style)
        value = _settings_value_text(row, muted=bool(row.disabled_reason) and not focused)
        items.append(Text.assemble(lead, " ", label, "  ", value))
```

In `render_settings` (lines 1683-1689), insert the reason between the locked message and the help:

```python
    else:
        detail = error or (
            f"Set by the {row.variable} environment variable."
            if row.locked
            else row.disabled_reason or _SETTINGS_HELP.get(row.key, "")
        )
        _print_viewport_line(console, f"  {detail}", style="dim")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/interactive/test_render.py tests/unit/interactive/test_settings_controller.py -v`
Expected: PASS — including pre-existing render and controller tests (they exercise `render_settings` end to end).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run pyright
git add src/iiwi/interactive/render.py tests/unit/interactive/test_render.py
git commit -m "feat: render disabled-harness settings rows dim with a reason"
```

---

### Task 3: Controller ignores edits on disabled rows

**Files:**
- Modify: `src/iiwi/interactive/controller.py:671-673` (`_settings_key`)
- Test: `tests/unit/interactive/test_settings_controller.py`

**Interfaces:**
- Consumes: `SettingsRow.disabled_reason: str` from Task 1; existing `_settings_key(state, key, console)`, `_persist_setting`, `run_interactive` scripted-input harness.
- Produces: no signature changes; disabled rows behave identically to locked rows.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/interactive/test_settings_controller.py` (reuses `config_file`, `_actions`, `_open_settings`, `_console`, `char`, and the direct `_State` style of `test_settings_offset_follows_the_cursor_and_saturates_at_the_end`):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/interactive/test_settings_controller.py -v -k disabled_or_restores`
Expected: FAIL — the first test writes nothing extra but the second fails at `settings_editing is True` (editor opened on the disabled row), and/or the first test's detail line lacks the reason if Task 2 was skipped.

- [ ] **Step 3: Implement**

In `src/iiwi/interactive/controller.py`, `_settings_key`, replace:

```python
    row = state.settings_rows[state.settings_cursor]
    if row.locked:
        return
```

with:

```python
    row = state.settings_rows[state.settings_cursor]
    if row.locked or row.disabled_reason:
        return
```

(The write in Step 1 of the first test predates the run, so the assertion proves ←→/Enter added nothing; the reason on screen comes from Task 2.)

- [ ] **Step 4: Run the full interactive suite to verify everything passes**

Run: `uv run pytest tests/unit/interactive -v`
Expected: PASS.

- [ ] **Step 5: Full gates, then commit**

```bash
uv run ruff check . && uv run pyright && uv run pytest --cov=iiwi --cov-fail-under=80
git add src/iiwi/interactive/controller.py tests/unit/interactive/test_settings_controller.py
git commit -m "feat: ignore edits on settings rows under a disabled harness"
```

---

## Self-Review Notes

- Spec coverage: field + computation (Task 1), dim/focus/detail-precedence (Task 2), edit gating + live re-enable (Task 3), all three test files from the spec, CLI untouched — complete.
- Copy is byte-identical across Tasks 1–3 (`"…enable harnesses.claude_code.enabled to make this take effect."`).
- `disabled_reason` is referenced consistently; `_settings_value_text` gains only a defaulted keyword parameter.
