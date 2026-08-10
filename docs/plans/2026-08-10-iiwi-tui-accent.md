# Iiwi TUI Accent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the interactive TUI's generic cyan focus accents with a terminal-safe iiwi bright-red accent while preserving existing status colors and behavior.

**Architecture:** Keep the change renderer-only. Update the three centralized Rich style constants in `src/iiwi/interactive/render.py`; renderer tests assert the emitted ANSI styles for focus, actions, and activity bars while existing marker tests continue to protect green/yellow/dim semantics.

**Tech Stack:** Python 3.11+, Rich, pytest, pytest-cov, Ruff, Pyright, uv

## Global Constraints

- Use ANSI `bright_red`, not hard-coded RGB/hex colors.
- Cursor / active row uses `bold bright_red`.
- Unselected primary action uses `bright_red`.
- Activity volume bar uses `bright_red`.
- Keep green/yellow/dim selection marker semantics unchanged.
- Do not change background colors, layout, navigation, labels, shortcuts, or controller behavior.

---

### Task 1: Lock the iiwi accent contract in renderer tests

**Files:**
- Modify: `tests/unit/interactive/test_render.py`

**Interfaces:**
- Consumes: existing `_color_console`, `_glyph_style`, `_selection`, `_mixed_volume_scan`, `render_report_setup`, `render_session_review`, and `render_session_browser` test helpers/renderers.
- Produces: renderer assertions that require ANSI bright red (`91`) for focus, primary actions, and activity bars while retaining existing marker assertions.

- [ ] **Step 1: Change cursor expectations from cyan to bright red**

Update the two existing cursor-style assertions from `"1;36"` to `"1;91"` in:

```python
def test_session_review_gives_the_three_repository_glyphs_three_styles() -> None:
    ...
    assert _glyph_style(line, "▶") == "1;91"


def test_session_browser_separates_the_cursor_from_the_expansion_glyph() -> None:
    ...
    assert _glyph_style(line, "▶") == "1;91"
```

- [ ] **Step 2: Add an action-color regression test**

Add:

```python
def test_report_setup_colors_unselected_actions_with_iiwi_accent() -> None:
    console, stream = _color_console()
    render_report_setup(
        console,
        ReportDraft(harness="opencode", period=_period()),
        selected=0,
    )
    line = _row(stream.getvalue(), "Preview report")
    assert _glyph_style(line, "P") == "91"
```

- [ ] **Step 3: Add an activity-bar regression test**

Add:

```python
def test_session_browser_colors_activity_bar_with_iiwi_accent() -> None:
    console, stream = _color_console()
    render_session_browser(
        console,
        _mixed_volume_scan(),
        expanded_repositories=set(),
        cursor=0,
    )
    line = _row(stream.getvalue(), "repo-x")
    assert _glyph_style(line, "█") == "91"
```

- [ ] **Step 4: Run the targeted tests and verify RED**

Run:

```bash
uv run pytest \
  tests/unit/interactive/test_render.py::test_session_review_gives_the_three_repository_glyphs_three_styles \
  tests/unit/interactive/test_render.py::test_session_browser_separates_the_cursor_from_the_expansion_glyph \
  tests/unit/interactive/test_render.py::test_report_setup_colors_unselected_actions_with_iiwi_accent \
  tests/unit/interactive/test_render.py::test_session_browser_colors_activity_bar_with_iiwi_accent -q
```

Expected: FAIL because the renderer still emits cyan (`36`) for cursor/action/bar roles.

---

### Task 2: Apply the centralized iiwi accent styles

**Files:**
- Modify: `src/iiwi/interactive/render.py`
- Test: `tests/unit/interactive/test_render.py`

**Interfaces:**
- Consumes: existing `_CURSOR_STYLE`, `_ACTION_STYLE`, `_BAR_STYLE` constants.
- Produces: the same renderer API and interaction behavior, with new color-role values only.

- [ ] **Step 1: Make the minimal production change**

Change only:

```python
_CURSOR_STYLE = "bold bright_red"
_ACTION_STYLE = "bright_red"
_BAR_STYLE = "bright_red"
```

Keep `_MARK_STYLES`, `_EXPANSION_STYLE`, and all layout/controller code unchanged.

- [ ] **Step 2: Run the targeted tests and verify GREEN**

Run the same four-test command from Task 1.

Expected: PASS.

- [ ] **Step 3: Run the complete quality gate**

Run:

```bash
uv run pytest --cov=iiwi --cov-fail-under=80
uv run ruff check .
uv run pyright
uv build
```

Expected: all commands exit 0; coverage remains at or above 80%.

- [ ] **Step 4: Inspect the final diff**

Confirm the PR contains only:

- the two `docs/plans/` files for this change
- `src/iiwi/interactive/render.py`
- `tests/unit/interactive/test_render.py`

There must be no controller, layout, navigation, or background-color changes.
