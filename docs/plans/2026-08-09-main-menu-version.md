# Main Menu Title-Row Version Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the installed version, right-aligned and dim, on the main menu's title row.

**Architecture:** `render_main_menu` in `src/agent_worklog/interactive/render.py` builds its own title line as a Rich `Text` (bold title + right-aligned dim version) instead of handing `_print_header` a plain string. All other screens and `_print_header` itself are untouched. On narrow terminals where title + version cannot fit, the bare title is printed without the version.

**Tech Stack:** Python 3.11+, Rich (`Text.assemble`, `cell_len`), pytest, typer CLI.

## Global Constraints

- Version source: `from agent_worklog import __version__` — the package `__init__` only defines the constant; no import cycle.
- Version format on screen: `v{__version__}` (e.g. `v0.8.0`).
- Title style: `"bold"` (as `_print_header` uses today). Version style: `"dim"`.
- Rule and subtitle lines below the title are printed exactly as `_print_header` prints them today; the subtitle stays `"Turn coding-agent sessions into engineering reports"` — no version in it.
- Drop the version (title wins) when `cell_len("Agent Worklog") + 1 + cell_len(version)` exceeds `console.size.width`.
- Other screens, `_print_header`, `agent-worklog --version`, and the `update` command are out of scope.
- No new dependencies.

---

### Task 1: Render the version in the main menu title row

**Files:**
- Modify: `src/agent_worklog/interactive/render.py` (add `__version__` import; rework the title line inside `render_main_menu`)
- Test: `tests/unit/interactive/test_render.py`

**Interfaces:**
- Consumes: `agent_worklog.__version__` (str, e.g. `"0.8.0"`), existing `_print_viewport_line`, `_print_viewport_text`, `_print_header`, `cell_len`, `Text.assemble`, `_RULE_CHAR`, `_MIN_SUBTITLE_HEIGHT`.
- Produces: nothing new for later tasks — `render_main_menu(console, *, selected)` keeps its exact signature.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/interactive/test_render.py`:

```python
def test_main_menu_title_row_shows_the_version_right_aligned() -> None:
    import agent_worklog
    from agent_worklog.interactive.render import render_main_menu

    console, stream = _console(width=100)
    render_main_menu(console, selected=0)

    title_line = _row(stream.getvalue(), "Agent Worklog")
    assert f"v{agent_worklog.__version__}" in title_line


def test_main_menu_omits_the_version_on_a_narrow_terminal() -> None:
    import agent_worklog
    from agent_worklog.interactive.render import render_main_menu

    console, stream = _console(width=25)
    render_main_menu(console, selected=0)

    text = stream.getvalue()
    assert "Agent Worklog" in text
    assert f"v{agent_worklog.__version__}" not in text
```

Note: `_row(text, needle)` and `_console(width)` already exist in this file (see lines 35-59).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/unit/interactive/test_render.py -q -k "title_row_shows_the_version or omits_the_version_on_a_narrow"`
Expected: both FAIL — the version never appears in current output.

- [ ] **Step 3: Implement the title-row version**

In `src/agent_worklog/interactive/render.py`:

1. Add the import next to the other module imports (after `from rich.text import Text`):

```python
from agent_worklog import __version__
```

2. Replace the body of `render_main_menu` (currently starts at the `_print_header(...)` call) with:

```python
def render_main_menu(console: Console, *, selected: int) -> None:
    title = "Agent Worklog"
    version = f"v{__version__}"
    if cell_len(title) + 1 + cell_len(version) <= console.size.width:
        padding = console.size.width - cell_len(title) - cell_len(version)
        title_line = Text.assemble((title, "bold"), " " * padding, (version, "dim"))
        _print_viewport_text(console, title_line)
    else:
        _print_viewport_line(console, title, style="bold")
    _print_viewport_line(console, _RULE_CHAR * console.size.width, style="dim")
    if console.size.height >= _MIN_SUBTITLE_HEIGHT:
        _print_viewport_line(
            console,
            "Turn coding-agent sessions into engineering reports",
            style="dim",
        )
    console.print()
    # ... the rest of the menu body (options, hints) stays exactly as it is.
```

Keep the existing `label_width = ...` loop and `_print_hints` block unchanged. `_print_viewport_text` already exists in this module (defined near `_print_viewport_line`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/unit/interactive/test_render.py -q`
Expected: ALL PASS, including the two new tests and every existing menu/painting test.

- [ ] **Step 5: Run the full suite and linters**

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev pyright
```

Expected: 633 tests pass (631 current + 2 new), ruff clean, pyright 0 errors.

- [ ] **Step 6: Commit**

```bash
git add src/agent_worklog/interactive/render.py tests/unit/interactive/test_render.py
git commit -m "feat: show the installed version in the main menu title row"
```
