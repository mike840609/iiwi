# Main Menu Art: Banner, Bird, Version and GitHub Link

**Date:** 2026-08-10
**Status:** Approved
**Scope:** Main-menu header of the interactive terminal only. No other screens, no new commands, no new dependencies.

## Goal

Give the interactive main menu a proper identity header: a block-letter wordmark, an ASCII iiwi bird (the bird the project is named after), the version flush right, and a clickable GitHub link — while preserving the codebase's rule that chrome recedes on short terminals.

## Context

Today `render_main_menu` (`src/iiwi/interactive/render.py:383`) prints:

```
Iiwi                                  v0.9.1
═══════════════════════════════════════════
Turn coding-agent sessions into engineering reports
```

- The "logo" is the word `Iiwi` in bold, left-aligned, with the version right-padded on the same line.
- The codebase's stated design rule is that chrome (rule, subtitle, guidance lines) recedes first on small terminals (`_MIN_SUBTITLE_HEIGHT = 16`, render.py:122).
- The repo URL is `https://github.com/mike840609/iiwi` (git remote `origin`).
- No figlet/pyfiglet dependency exists; art is embedded as constants.

## Design

### New tall-terminal header (terminal height ≥ 24, width ≥ 36)

```
   ╭╮  ╭─────╮   ___ _        _
   ││ ( • █ ╭╯  |_ _(_)_ __ _(_)
   ╰╯  ╰───╯╯    | || \ V  V / |
        ╱   ╲    |___|_|\_/\_/|_|
                                v0.9.1
═══════════════════════════════════════════
Turn coding-agent sessions into engineering reports
github.com/mike840609/iiwi
```

Element by element:

1. **Bird** (left, 4 rows, plain line art): tail `╭╮/││/╰╯`, body `╭─╮`, eye `•`, wing `█`, curved bill `╭╯` descending to a tip `╯`, feet `╱╲`. No color — plain default foreground.
2. **Wordmark** (right, 4 rows): figlet "small"-font `Iiwi`, styled `bold cyan` (the current title color). Lines: `" ___ _        _"`, `"|_ _(_)_ __ _(_)"`, `" | || \ V  V / |"`, `"|___|_|\\_/\\_/|_|"`.
3. **Version**: its own line directly under the art block, flush right (padding to `console.size.width`), dim.
4. **Rule**: `═` × width, dim — unchanged.
5. **Subtitle**: `Turn coding-agent sessions into engineering reports`, dim — unchanged, gated by `_MIN_SUBTITLE_HEIGHT` (16) as today.
6. **GitHub link**: `github.com/mike840609/iiwi`, dim, styled `link https://github.com/mike840609/iiwi` (Rich OSC 8 hyperlink; renders as plain text on terminals without hyperlink support). Printed only when the subtitle prints (same `_MIN_SUBTITLE_HEIGHT` gate), directly under it.

### Thresholds and fallbacks

| Terminal | Renders |
| --- | --- |
| height ≥ 24 and width ≥ 36 | Bird + wordmark side by side, version line, rule, subtitle, link |
| height ≥ 24 and width < 36 | Wordmark alone (bird drops first — it is the newest chrome), version line, rule, subtitle, link |
| 16 ≤ height < 24 | Current compact header unchanged (`Iiwi` + version, rule, subtitle), with the link under the subtitle — the link rides the subtitle's gate everywhere |
| height < 16 | Current behavior: title + rule only |

Width of the art block: bird 15 cells + 2-cell gap + wordmark 16 cells = 33 cells; the 36 threshold leaves a 3-cell margin. Below 36 cells the bird is dropped because trailing-space composition and the version padding would otherwise crowd a narrow screen.

The version is always shown on the version line when the banner block renders; when it does not (short terminals), the existing `Iiwi … v0.9.1` line keeps the version visible — the version must never disappear.

## Implementation notes

### `src/iiwi/interactive/render.py`

New module constants:

```python
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

`render_main_menu` restructured:

- If `height >= _MIN_BANNER_HEIGHT`: compose the art block — join bird and wordmark per row with a 2-space gap (pad the bird's shorter rows with spaces so both columns align), truncate to `console.size.width`; print art lines with the bird plain and the wordmark `bold cyan` (two `Text` spans or one `Text.assemble` per row).
- Print the version line: `Text.assemble(" " * padding, (version, "dim"))` with `padding = max(0, width - cell_len(version))`, via `_print_viewport_text`.
- Then the existing rule, subtitle, and a new link line (`_print_viewport_line(console, _PROJECT_LABEL, style=f"dim link {_PROJECT_URL}")`) inside the subtitle's height gate.
- Else: existing compact path untouched (`Iiwi` + version, rule, subtitle).

The wide-branch title/version block (`render.py:384-402`) is replaced by the above; the narrow fallback `_print_header(console, "Iiwi", subtitle=…)` stays as-is.

### Tests (`tests/unit/interactive/test_render.py` and `tests/unit/interactive/test_viewport_wrapping_regressions.py`)

Existing tests that assert `"Iiwi"` in the menu output (test_render.py:121-137, 1166-1197) must be re-pointed: tall-terminal expectations become the wordmark art line `|___|_|\_/\_/|_|`; compact expectations keep `"Iiwi"`.

New assertions:

1. Tall + wide (e.g. 30×80): bird row `╭╮  ╭─────╮` present, wordmark row present, version line ends with `v<version>` and has no leading content beyond padding, link row `github.com/mike840609/iiwi` present.
2. Tall + narrow (30×36): wordmark present, bird absent.
3. Short (20 rows): art absent, `"Iiwi"` + version line present, link present (subtitle gate ≥ 16).
4. Height 15 rows: title + rule only; subtitle and link both absent.
5. Version never missing in any configuration.

The viewport-wrapping regression (test_viewport_wrapping_regressions.py:168) budget must be re-checked: the tall-tall menu now spends 4 (art) + 1 (version) + 1 (rule) + 1 (subtitle) + 1 (link) + 1 blank + 4 options + 1 blank + 1 hints = 15 rows before content; the regression's terminal height must leave the option list fully visible.

### Out of scope

- No pyfiglet dependency — art is a frozen constant (deterministic, zero new deps).
- No color beyond `bold cyan` wordmark and `dim`/link styles (codebase rule: plain ANSI names).
- No other screens, no `--version` changes, no config option to toggle the art.

## Verification

```
uv run pytest --cov=iiwi --cov-fail-under=80
uv run iiwi   # 30-row x 100-col terminal: art, version right, link; 20-row: compact
```

Manual check on a wide terminal: the version's right edge aligns with the rule's right edge.
