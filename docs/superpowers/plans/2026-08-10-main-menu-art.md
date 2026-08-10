# Main Menu Art, Version and GitHub Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the interactive main menu a banner wordmark, an ASCII iiwi bird, a flush-right version, and a clickable GitHub link — with chrome receding on small terminals.

**Architecture:** Pure Rich rendering change in `render_main_menu` (`src/iiwi/interactive/render.py`). New module constants hold frozen art; a private `_print_main_menu_logo` composes bird + wordmark per row. Height gates select the tall (art) vs compact (current) header. No new dependencies, no new screens, no controller changes.

**Tech Stack:** Python 3.12+, Rich (console, Text, cell_len), pytest.

## Global Constraints

- Art is embedded as frozen string constants — **no pyfiglet or any new dependency**.
- `_MIN_BANNER_HEIGHT = 24` (tall header), `_MIN_BANNER_WIDTH = 36` (bird shows only at ≥36 cells; wordmark shows alone below).
- `_MIN_SUBTITLE_HEIGHT = 16` (existing) gates subtitle and GitHub link together — they always co-appear.
- The version **must never disappear** in any configuration.
- Link label `github.com/mike840609/iiwi`; link style exactly `f"dim link {_PROJECT_URL}"` with `_PROJECT_URL = "https://github.com/mike840609/iiwi"`.
- Wordmark style `bold cyan`; bird plain (no style); version `dim`. Plain ANSI names only.
- Test command: `uv run pytest --cov=iiwi --cov-fail-under=80` (full suite must pass).
- Commit messages follow the repo's conventional style (`feat: ...`).

---

### Task 1: Art constants and the logo composition helper

**Files:**
- Modify: `src/iiwi/interactive/render.py` — add constants next to the other `_MAIN_*`/`_MIN_*` constants (render.py:39-127) and the helper near `main_menu_options` (render.py:130)
- Test: `tests/unit/interactive/test_render.py`

**Interfaces:**
- Produces: `_BIRD: tuple[str, ...]`, `_BANNER: tuple[str, ...]`, `_PROJECT_URL: str`, `_PROJECT_LABEL: str`, `_MAIN_SUBTITLE: str`, `_MIN_BANNER_HEIGHT: int`, `_MIN_BANNER_WIDTH: int`, `_print_main_menu_logo(console: Console) -> None` (prints the bird/wordmark block, truncating rather than wrapping; wordmark in `bold cyan`, bird plain). Task 2 consumes all of these.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/interactive/test_render.py` (import `_print_main_menu_logo` inside each test, matching the file's inline-import style):

```python
def test_main_menu_logo_composes_bird_and_wordmark_side_by_side() -> None:
    from iiwi.interactive.render import _print_main_menu_logo

    console, stream = _console(width=100)
    _print_main_menu_logo(console)

    lines = stream.getvalue().splitlines()
    assert lines == [
        "   ╭╮  ╭─────╮   ___ _        _",
        "   ││ ( • █ ╭╯  |_ _(_)_ __ _(_)",
        "   ╰╯  ╰───╯╯    | || \\ V  V / |",
        "        ╱   ╲    |___|_|\\_/\\_/|_|",
    ]


def test_main_menu_logo_drops_the_bird_below_thirty_six_cells() -> None:
    from iiwi.interactive.render import _print_main_menu_logo

    console, stream = _console(width=35)
    _print_main_menu_logo(console)

    text = stream.getvalue()
    assert "╭─────╮" not in text
    assert "|___|_|\\_/\\_/|_|" in text


def test_main_menu_logo_truncates_instead_of_wrapping() -> None:
    from iiwi.interactive.render import _print_main_menu_logo

    console, stream = _console(width=10)
    _print_main_menu_logo(console)

    assert not any(len(line) > 10 for line in stream.getvalue().splitlines())
```

(These fail because the constants and helper do not exist yet.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/interactive/test_render.py::test_main_menu_logo_composes_bird_and_wordmark_side_by_side tests/unit/interactive/test_render.py::test_main_menu_logo_drops_the_bird_below_thirty_six_cells tests/unit/interactive/test_render.py::test_main_menu_logo_truncates_instead_of_wrapping -v`
Expected: FAIL with `ImportError`/`AttributeError` or assertion failure.

- [ ] **Step 3: Implement the constants and helper**

In `src/iiwi/interactive/render.py`, add with the other constants (render.py:39-127):

```python
_MAIN_SUBTITLE = "Turn coding-agent sessions into engineering reports"
_BIRD = (
    "   ╭╮  ╭─────╮",
    "   ││ ( • █ ╭╯",
    "   ╰╯  ╰───╯╯",
    "        ╱   ╲",
)
_BANNER = (
    " ___ _        _",
    "|_ _(_)_ __ _(_)",
    " | || \\ V  V / |",
    "|___|_|\\_/\\_/|_|",
)
_PROJECT_URL = "https://github.com/mike840609/iiwi"
_PROJECT_LABEL = "github.com/mike840609/iiwi"
_MIN_BANNER_HEIGHT = 24
_MIN_BANNER_WIDTH = 36
```

Add next to `main_menu_options` (render.py:130):

```python
def _print_main_menu_logo(console: Console) -> None:
    """Print the bird and wordmark side by side, truncating rather than wrapping."""

    gap = "  "
    bird_width = max(cell_len(line) for line in _BIRD)
    show_bird = console.size.width >= _MIN_BANNER_WIDTH
    for index, banner_line in enumerate(_BANNER):
        if show_bird:
            bird_line = _BIRD[index]
            left = bird_line + " " * (bird_width - cell_len(bird_line)) + gap
        else:
            left = ""
        _print_viewport_text(
            console,
            Text.assemble((left, ""), (banner_line, "bold cyan")),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/interactive/test_render.py::test_main_menu_logo_composes_bird_and_wordmark_side_by_side tests/unit/interactive/test_render.py::test_main_menu_logo_drops_the_bird_below_thirty_six_cells tests/unit/interactive/test_render.py::test_main_menu_logo_truncates_instead_of_wrapping -v`
Expected: PASS. `render_main_menu` is still untouched — wiring the helper into the menu is Task 2.

- [ ] **Step 5: Commit**

```bash
git add src/iiwi/interactive/render.py tests/unit/interactive/test_render.py
git commit -m "feat: add main-menu banner and bird art constants"
```

---

### Task 2: Restructure the main menu header (tall + compact paths, version, link)

**Files:**
- Modify: `src/iiwi/interactive/render.py:383-421` — replace `render_main_menu` body
- Modify: `tests/unit/interactive/test_render.py` — update existing menu tests (lines 118-129, 1164-1198), add new tests
- Modify: `tests/unit/interactive/test_interactive_regressions.py:170-192` — update the exact-line-count expectation
- Modify: `tests/unit/interactive/test_render.py:35-40` — extend `_console` with a `height` parameter

**Interfaces:**
- Consumes: Task 1's `_BIRD`, `_BANNER`, `_PROJECT_URL`, `_PROJECT_LABEL`, `_MAIN_SUBTITLE`, `_MIN_BANNER_HEIGHT`, `_MIN_BANNER_WIDTH`, `_print_main_menu_logo`.
- Produces: the new `render_main_menu` behavior described in the spec (`docs/superpowers/specs/2026-08-10-main-menu-art-design.md`).

- [ ] **Step 1: Extend the test console helper with a height**

In `tests/unit/interactive/test_render.py`, replace (line 35-40):

```python
def _console(width: int = 100) -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(file=stream, color_system=None, force_terminal=False, width=width),
        stream,
    )
```

with:

```python
def _console(width: int = 100, height: int | None = None) -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(
            file=stream,
            color_system=None,
            force_terminal=False,
            width=width,
            height=height,
        ),
        stream,
    )
```

Run: `uv run pytest tests/unit/interactive/test_render.py -q`
Expected: PASS (default height 25 unchanged — Rich defaults non-terminal consoles to 25 rows).

- [ ] **Step 2: Update the existing menu tests to the tall header**

In `tests/unit/interactive/test_render.py`:

`test_main_menu_renders_navigation_and_footer` (line 124) — the bold "Iiwi" word is gone in tall mode; assert the wordmark art instead:

```python
    assert "|___|_|\\_/\\_/|_|" in text
```

Replace `test_main_menu_title_row_shows_the_version_right_aligned` (1164-1172) with a flush-right assertion:

```python
def test_main_menu_version_line_is_flush_right() -> None:
    import iiwi
    from iiwi.interactive.render import render_main_menu

    console, stream = _console(width=100)
    render_main_menu(console, selected=0)

    version = f"v{iiwi.__version__}"
    version_line = _row(stream.getvalue(), version)
    assert version_line.endswith(version)
    assert cell_len(version_line) == 100
```

Replace `test_main_menu_omits_the_version_on_a_narrow_terminal` (1175-1184): the version is now its own line that always fits, so it shows even at 10 cells:

```python
def test_main_menu_version_always_fits_on_its_own_line() -> None:
    import iiwi
    from iiwi.interactive.render import render_main_menu

    console, stream = _console(width=10)
    render_main_menu(console, selected=0)

    assert f"v{iiwi.__version__}" in stream.getvalue()
```

Delete `test_main_menu_fits_the_version_at_exactly_eleven_cells` (1187-1198) — the old title-cell math no longer exists.

Run: `uv run pytest tests/unit/interactive/test_render.py -q`
Expected: FAIL at `render_main_menu` — the tall header is not implemented yet (compacts still pass except the new flush-right/version tests).

- [ ] **Step 3: Implement the new `render_main_menu`**

Replace the body of `render_main_menu` (render.py:383-421) with:

```python
def render_main_menu(console: Console, *, selected: int) -> None:
    if console.size.height >= _MIN_BANNER_HEIGHT:
        _print_main_menu_logo(console)
        version = f"v{__version__}"
        padding = max(0, console.size.width - cell_len(version))
        _print_viewport_text(console, Text.assemble(" " * padding, (version, "dim")))
        _print_viewport_line(console, _RULE_CHAR * console.size.width, style="dim")
        _print_viewport_line(console, _MAIN_SUBTITLE, style="dim")
        _print_viewport_line(console, _PROJECT_LABEL, style=f"dim link {_PROJECT_URL}")
    else:
        _print_header(console, "Iiwi", subtitle=_MAIN_SUBTITLE)
        if console.size.height >= _MIN_SUBTITLE_HEIGHT:
            _print_viewport_line(
                console, _PROJECT_LABEL, style=f"dim link {_PROJECT_URL}"
            )
    console.print()
```

Note: the tall branch prints subtitle + link unconditionally — its height gate (24) already exceeds the subtitle gate (16). The compact branch re-checks `_MIN_SUBTITLE_HEIGHT` because `_print_header` applies that gate internally to the subtitle.

- [ ] **Step 4: Update the narrow-terminal line-count regression**

In `tests/unit/interactive/test_interactive_regressions.py:173`, the main menu at 30×30 now renders 16 lines (4 art + 1 version + 1 rule + 1 subtitle + 1 link + 1 blank + 4 options + 1 blank + 2 wrapped hint lines). Update:

```python
    assert len(main_stream.getvalue().splitlines()) == 16
```

- [ ] **Step 5: Add tests for the compact and boundary paths**

Append to `tests/unit/interactive/test_render.py`:

```python
def test_main_menu_compact_header_at_short_terminal() -> None:
    import iiwi
    from iiwi.interactive.render import render_main_menu

    console, stream = _console(width=100, height=20)
    render_main_menu(console, selected=0)

    text = stream.getvalue()
    assert "|___|_|\\_/\\_/|_|" not in text
    title_line = _row(text, "Iiwi")
    assert f"v{iiwi.__version__}" in title_line
    assert _MAIN_SUBTITLE in text
    assert _PROJECT_LABEL in text


def test_main_menu_art_gate_at_twenty_four_rows() -> None:
    console, stream = _console(width=100, height=23)
    render_main_menu(console, selected=0)
    assert "|___|_|\\_/\\_/|_|" not in stream.getvalue()

    console, stream = _console(width=100, height=24)
    render_main_menu(console, selected=0)
    assert "|___|_|\\_/\\_/|_|" in stream.getvalue()


def test_main_menu_drops_subtitle_and_link_below_sixteen_rows() -> None:
    from iiwi.interactive.render import _MAIN_SUBTITLE, _PROJECT_LABEL, render_main_menu

    console, stream = _console(width=100, height=15)
    render_main_menu(console, selected=0)

    text = stream.getvalue()
    assert _MAIN_SUBTITLE not in text
    assert _PROJECT_LABEL not in text
    assert "Iiwi" in text


def test_main_menu_link_is_a_clickable_hyperlink() -> None:
    console, stream = _color_console(width=100)
    render_main_menu(console, selected=0)

    text = stream.getvalue()
    assert _PROJECT_LABEL in text
    assert "\x1b]8;;https://github.com/mike840609/iiwi\x1b\\" in text
```

`_color_console` already exists in the file (line 43) with `force_terminal=True`, which makes Rich emit the OSC 8 hyperlink escape.

Run: `uv run pytest tests/unit/interactive/test_render.py tests/unit/interactive/test_interactive_regressions.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest --cov=iiwi --cov-fail-under=80`
Expected: all pass. If the default-height (25-row) menu tests drift on exact line counts anywhere else, fix the count to the actual rendered value — the counts in this plan were derived by hand and the suite is the source of truth.

- [ ] **Step 7: Manual smoke check**

Run `uv run iiwi` in a terminal at ≥24 rows and ≥36 columns: art block, flush-right version, subtitle, and clickable link (Cmd/Ctrl-click in iTerm2/kitty). Then shrink the terminal below 24 rows: compact header with link. Version visible in both.

- [ ] **Step 8: Commit**

```bash
git add src/iiwi/interactive/render.py tests/unit/interactive/test_render.py tests/unit/interactive/test_interactive_regressions.py
git commit -m "feat: render main-menu banner, flush-right version and GitHub link"
```
