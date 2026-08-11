### Task 5: Rendered-line-aware Single-screen TUI

**Files:**
- Modify: `src/iiwi/interactive/render.py`
- Modify: `src/iiwi/interactive/controller.py`
- Create: `tests/unit/interactive/test_outcome_review_render.py`
- Modify: `tests/unit/interactive/test_viewport_wrapping_regressions.py`

**Interfaces:**
- Consumes: `OutcomeReviewDraft`, cursor index, expanded evidence ids, and optional status message.
- Produces: `outcome_review_rows(draft) -> list[OutcomeReviewRow]` and `render_outcome_review(console, draft, *, cursor, expanded_evidence, message=None) -> None`.

- [ ] **Step 1: Write failing visual hierarchy tests**

Create renderer tests asserting the screen includes:

```python
assert "Quick Review" in text
assert "Manager" in text and "Brief" in text
assert "3 selected" in text
assert "More candidates" in text
assert "Blockers" in text and "Next week" in text
assert "Space Include" in text
assert "e Edit" in text
assert "J/K Reorder" in text
assert "v Evidence" in text
assert "s Split" in text
assert "a Add" in text
assert "p Preview" in text and "g Generate" in text
```

Assert an unfocused outcome occupies one display line; the focused outcome adds Status, non-empty Impact, and evidence summary; pressing `v` adds repository/session/file rows; user-added and ungrouped items carry visible labels.

- [ ] **Step 2: Write the terminal matrix regression**

Extend `test_viewport_wrapping_regressions.py` with long title, Impact, repository, file, and error strings. For widths `(40, 60, 80, 100, 140)`, heights `(20, 24, 30)`, and first/middle/last focus, assert:

```python
lines = stream.getvalue().splitlines()
assert len(lines) <= height - 1
assert any("Quick Review" in line for line in lines)
assert any("▶" in line for line in lines)
assert any("p Preview" in line or "g Generate" in line for line in lines)
```

- [ ] **Step 3: Run the renderer tests and confirm failure**

Run: `uv run pytest tests/unit/interactive/test_outcome_review_render.py tests/unit/interactive/test_viewport_wrapping_regressions.py -q`

Expected: FAIL because the Quick Review renderer does not exist.

- [ ] **Step 4: Implement block rows and display-line budgeting**

Add a frozen `OutcomeReviewRow(kind, outcome_id=None)` and build rows in this order: settings, primary outcomes, More candidates control and included children when open, Ungrouped candidates control and children when present/open, Blockers, Next week, Preview, Generate.

Render each logical row into a `list[Text]` block. Only the focused outcome expands. Calculate every block's height from its actual rendered lines at the current width; use `Text.truncate(width, overflow="ellipsis")` before printing. The viewport algorithm must reserve header, blank separators, message, scroll indicators, and packed hint lines, then choose the largest contiguous block window containing the focused block. When space is tight, remove evidence detail first, then Impact continuation lines, while retaining the focused summary.

Reuse `_print_viewport_text()` and `_print_hints()`; do not introduce Textual or a second repaint loop.

- [ ] **Step 5: Run renderer and viewport tests**

Run: `uv run pytest tests/unit/interactive/test_outcome_review_render.py tests/unit/interactive/test_viewport_wrapping_regressions.py -q`

Expected: PASS at every width/height/focus combination.

- [ ] **Step 6: Run all interactive tests**

Run: `uv run pytest tests/unit/interactive -q`

Expected: PASS.

- [ ] **Step 7: Commit the TUI**

```bash
git add src/iiwi/interactive/render.py src/iiwi/interactive/controller.py tests/unit/interactive/test_outcome_review_render.py tests/unit/interactive/test_viewport_wrapping_regressions.py
git commit -m "feat: render outcome quick review TUI"
```

---
