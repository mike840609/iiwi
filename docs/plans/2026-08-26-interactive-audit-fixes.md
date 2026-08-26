# Interactive Mode Audit Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 15 findings from the 2026-08-26 interactive-mode audit as independent PRs, ordered by severity.

**Architecture:** Three execution lanes keyed by file overlap to avoid merge conflicts. Lane 1 owns `cli_actions.py` + `input.py`; Lane 2 owns `controller.py`; Lane 3 owns `render.py`. Every PR branches off `origin/main` in its own git worktree under `.worktrees/`, implements TDD-style, runs the exact CI gates locally, pushes, and opens a PR. No PR merges its own branch.

**Tech Stack:** Python 3.11+, uv, pytest + coverage, ruff, pyright, Rich, gh CLI.

## Global Constraints

- Exact CI parity gates (README promises green-local = green-PR): `uv run pytest --cov=iiwi --cov-fail-under=80`, `uv run ruff check .`, `uv run pyright`
- Conventional Commits: `fix:`, `feat:`, `refactor:` — subject ≤ 72 chars
- Minimal diffs. NO unrelated refactoring, NO reformatting of untouched lines
- Every behavior change ships a test (TDD: failing test first)
- Worktree per PR: `git worktree add .worktrees/<pr-slug> -b <branch>` from `origin/main`; run `uv sync --locked --extra dev` once inside the worktree before gates
- Branch naming: `fix/<kebab-slug>`; base: `main`
- PR body template:
  ```markdown
  ## Problem
  <finding summary + file:line>

  ## Symptom
  <user-visible breakage>

  ## Fix
  <what changed and why this shape>

  ## Tests
  <test names added/updated>
  ```
- Never touch: the untracked files in the main checkout (`docs/superpowers/plans/2026-08-25-disabled-harness-settings.md`, `docs/superpowers/specs/`), `dist/`, `reports/`
- Do NOT merge PRs, do NOT push to `main`

---

### Task 1 (PR-A · P0 privacy) — Interactive reports honor configured sanitize default

**Files:**
- Modify: `src/iiwi/interactive/cli_actions.py:62-74` (`_new_draft`)
- Test: `tests/unit/interactive/test_cli_actions.py`

**Interfaces:** Consumes `cli._effective_sanitize(settings, harness, None)` (exists, used at cli_actions.py:492). Produces no new API.

- [ ] **Step 1: Failing test** — in `test_cli_actions.py`, mirror the existing fixture style used by Daily tests (which already prove `_effective_sanitize` works for daily):
```python
def test_new_draft_uses_configured_sanitize_default(monkeypatch, ...):
    # arrange settings whose effective sanitize for the harness resolves True
    # (follow the monkeypatch pattern the daily-start tests use for _load_settings)
    draft = build_interactive_actions(...)._new_draft()  # or however existing tests construct drafts
    assert draft.sanitize is True
```
Also assert the unset-config case stays `False`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/interactive/test_cli_actions.py -k sanitize -v` → new test FAILS (`sanitize is False`)
- [ ] **Step 3: Implement** — in `_new_draft`, replace `sanitize=False` construction arg with `sanitize=cli._effective_sanitize(settings, draft_harness, None)` computed from the same `settings = cli._load_settings()` the harness resolution already performs. Harness toggle on the setup screen intentionally keeps the user's explicit toggle (no `detail_overridden`-style tracking for sanitize in v1).
- [ ] **Step 4: Full gates**: `uv run pytest --cov=iiwi --cov-fail-under=80 && uv run ruff check . && uv run pyright` → PASS. If `tests/unit/test_documentation.py` complains about privacy/config docs drift, update the sentence in `docs/configuration.md`/`docs/privacy.md` that describes where the sanitize default applies.
- [ ] **Step 5: Commit** `fix: honor configured sanitize default in interactive reports`; push `fix/interactive-sanitize-default`; `gh pr create`.

---

### Task 2 (PR-B · P0 correctness) — Interrupted rescan must not leave stale selection consumable

**Files:**
- Modify: `src/iiwi/interactive/controller.py:849-871` (`_generate_from_setup`, `_rescan_review`) and the shared scan-error routing inside `_review` (~440-490)
- Test: `tests/unit/interactive/test_review_regressions.py` (add class/function)

**Interfaces:** Produces module-private helper `_scan_for_review(state, actions) -> ScanResult | None` that runs `actions.scan` with the SAME except-routing `_review` uses today (`ScanError`/`IiwiError` → `report-source` error screen) and returns `None` on failure. Both `_review` and `_rescan_review` consume it.

- [ ] **Step 1: Failing tests**
```python
def test_interrupted_rescan_keeps_previous_scan_and_selection():
    # drive to SESSION_REVIEW with a seeded scan (existing helpers),
    # make actions.scan raise KeyboardInterrupt, press "R"
    # assert: state.screen is SESSION_REVIEW, state.draft.scan IS the old object,
    #         state.selection.selected_session_ids unchanged
def test_synthesis_after_failed_rescan_uses_old_sessions():
    # continue previous scenario: press "g"; assert synthesize received the OLD
    # filtered scan (recording fake), not an empty/partial one
```
- [ ] **Step 2: Run** → both FAIL today (draft.scan is None after interrupt)
- [ ] **Step 3: Implement** — reorder `_rescan_review` to commit-on-success:
```python
def _rescan_review(state: _State, actions: InteractiveActions) -> None:
    selected = set(state.selection.selected_session_ids)
    scan = _scan_for_review(state, actions)      # may route to error screen
    if scan is None:
        return                                    # state untouched; old tree still valid
    _clear_outcome_review(state)
    state.draft.scan = scan
    _finish_review_selection(state, actions, selected)  # extracted tail of today's _review:
        # restore∩available → SelectionState.from_scan → expansions prune → cursors reset → sync
```
Refactor `_review` to call the same `_scan_for_review` + `_finish_review_selection` pair so there is one scan-error route and one selection-rebuild path. `_generate_from_setup` needs no extra guard: on interrupt it restores REPORT_SETUP with `selection is None`, and the next `g` rescans.
- [ ] **Step 4: Gates** full suite → PASS (existing rescan tests keep passing; they exercise the success path through the same helpers)
- [ ] **Step 5: Commit** `fix: keep previous scan intact when a rescan is interrupted`; push `fix/rescan-interrupt-stale-selection`; PR.

---

### Task 3 (PR-C · P0/P1) — Terminal input hardening cluster

**Files:**
- Modify: `src/iiwi/interactive/input.py` (whole module is in scope)
- Test: `tests/unit/interactive/test_input.py`

Covers audit findings M2, M3, M4, M5, m1, m6, m7. All in one PR because they share the reader loop and its timing constants.

**Interfaces:** `TerminalInput(read_key)` public behavior preserved; `normalize_posix_sequence(value: str) -> KeyPress` preserved for mapped inputs. New internal constants: `_ESCAPE_BYTE_TIMEOUT = 0.05`, `_CONTINUATION_MAX_TRIES = 10`, `_MAX_SEQUENCE_BYTES = 16`.

- [ ] **Step 1: Failing tests** (inject byte streams via the existing `reader=` injection seam):
```python
def test_arrow_key_survives_slow_ssh_delivery():     # M2
    # reader yields "\x1b", then "[", then "A" with >20ms gaps → Key.UP (needs 0.05 window)
def test_multibyte_cjk_survives_fragmented_delivery():  # M3
    # reader yields b"\xe4" then pauses, then b"\xbd" then b"\xa0" ("中") → char == "中"
def test_long_modify_other_keys_sequence_not_truncated():  # M4
    # reader yields "\x1b[27;5;13~" (10 bytes) → NOT garbage chars; collapses to ESCAPE (unmapped)
def test_ss3_arrow_keys_mapped():                    # m1
    # "\x1bOA".."\x1bOD" → UP/DOWN/LEFT/RIGHT; "\x1bOH"/"\x1bOF" → HOME/END
def test_unknown_escape_sequence_becomes_escape():   # M4+m7
    # "\x1b[1;5C" → Key.ESCAPE (never inject "[1;5C" as chars)
def test_double_escape_becomes_single_escape_press_pair():  # m7
    # "\x1b\x1b" delivered together → first read_key returns ESCAPE, second read_key returns ESCAPE
def test_windows_unknown_extended_code_is_ignored():  # M5
    # feed windows-style second-char ";" (F1) through mapping → ignored, not ";"
def test_eof_returns_escape_instead_of_busy_looping():  # m6
    # reader returns "" → KeyPress(key=Key.ESCAPE)
```
- [ ] **Step 2: Run** → all FAIL
- [ ] **Step 3: Implement**
  1. `_posix_read`: escape-window select timeout `0.02` → `_ESCAPE_BYTE_TIMEOUT`; loop bound 7 → `_MAX_SEQUENCE_BYTES - 1`.
  2. UTF-8 continuation loop: on select timeout, RETRY up to `_CONTINUATION_MAX_TRIES` before giving up (drop only the incomplete char after ~500ms of silence — remote links pause longer than 20ms but far less than 500ms between bytes of one character).
  3. Mapping additions: `\x1bOA/B/C/D` → arrows, `\x1bOH`/`\x1bOF` → HOME/END.
  4. `normalize_posix_sequence`: if unmapped AND `value.startswith("\x1b")` and `len(value) >= 1` → `KeyPress(key=Key.ESCAPE)` (unknown sequences must never leak printable bytes into text inputs). Special-case `"\x1b\x1b"`: return ESCAPE and leave the trailing `\x1b` unconsumed is impossible in this pull-based API — instead detect the doubled prefix and return ESCAPE for the whole buffer (documented; double-Esc as one cancel is acceptable UX).
  5. `_windows_read`: `mapping.get(second, "")` — unknown extended codes yield `""`; `read_key` maps `""` → `KeyPress(key=Key.ESCAPE)`? NO — empty means "ignore": return `KeyPress()` (no key, no char) and ensure every controller `_char()`/`key.key is` branch naturally skips it (verify `_search_input`'s final `else: append char` guards `if key.char:`).
  6. EOF (`os.read` → `b""` / msvcrt OSError at EOF): return `KeyPress(key=Key.ESCAPE)` so the idle loop routes to Back/quit rather than spinning.
- [ ] **Step 4: Gates** full suite → PASS. Pay attention to `test_collapsed_advanced_settings.py`, `test_settings_controller.py`, search-input tests — the `KeyPress()` no-op must not break text editing.
- [ ] **Step 5: Commit** `fix: harden terminal key decoding for remote links and long sequences`; push `fix/input-decoding-hardening`; PR.

---

### Task 4 (PR-E · P1 feedback) — Paint pending-action feedback before long ops block

**Files:**
- Modify: `src/iiwi/interactive/controller.py` — `run_interactive` (2054-2081), `_begin_daily_review` (1010-1015), `_begin_outcome_review` synthesis branch (~1270-1340), `_generate` (~800-850)
- Test: `tests/unit/interactive/test_controller_generation.py` + new `test_pending_feedback.py`

**Interfaces:** Produces `def _paint_pending(state: _State, console: Console, message: str) -> None` — renders the CURRENT screen frame via the existing `_render_screen`, then one dim line `f"⏳ {message}  (Ctrl-C to cancel)"` below it, flushed immediately. Handlers that start long ops call it right before the blocking `actions.*` call.

- [ ] **Step 1: Failing test** — recording fake Console passed through `run_interactive(console=fake, input_source=[key])`: pressing the Daily Standup option with a slow fake `actions.start_daily` must emit the pending line BEFORE `start_daily` is invoked (assert ordering via a shared event log list).
- [ ] **Step 2: Run** → FAIL (nothing painted before the call)
- [ ] **Step 3: Implement** — thread `console` into the three handler call sites (extend their signatures; `_dispatch` and `_main_key` already sit inside `run_interactive`'s scope — follow however `_settings_key(state, key, console)` receives it today, that is the established pattern). Replace the bare `state.daily_message = ...` assignment with: assign message (kept for post-hoc display) AND `_paint_pending(...)`. Same for outcome synthesis ("Synthesizing outcomes…") and report generation ("Generating report…").
- [ ] **Step 4: Gates** → PASS (frame-diff renderer unaffected: pending line is printed after the frame, erased naturally next cycle by the existing erase-below mechanism — verify with one `test_render_painting.py` smoke if the harness allows)
- [ ] **Step 5: Commit** `feat: show pending feedback before long interactive operations`; push `feat/pending-op-feedback`; PR.

---

### Task 5 (PR-F · P2) — Error back-screen remembers originating screen

**Files:**
- Modify: `src/iiwi/interactive/controller.py` — `_ErrorState` dataclass (+`back: Screen | None = None`), the `report-source`/`report-empty` raisers (~448-455), `_error_back_screen` (~1584-1585)
- Test: `tests/unit/interactive/test_controller.py`

- [ ] **Step 1: Failing test**: enter SESSION_REVIEW from MAIN (`review_from_main=True`), force `actions.scan` to raise on `R`; press Enter/Esc on error screen → expect `Screen.SESSION_REVIEW`, today gives `REPORT_SETUP`.
- [ ] **Step 2: FAIL** → **Step 3: implement** — raiser sets `back=state.screen`; `_error_back_screen` prefers `error.back` before the kind-prefix heuristic. Other kinds untouched.
- [ ] **Step 4: gates** → **Step 5:** commit `fix: send failed-rescan errors back to the screen they came from`; push `fix/error-back-origin-screen`; PR.

---

### Task 6 (PR-G · P2) — Refocus outcome cursor after toggling a MORE candidate

**Files:**
- Modify: `src/iiwi/interactive/controller.py:1493-1495` (Space branch in `_outcome_review_key`), new helper near `_focus_daily_item`
- Test: `tests/unit/interactive/test_outcome_review_controller.py`

- [ ] **Step 1: Failing test** (mirror `test_daily_review_controller.py`'s focus-after-toggle test): focus a MORE-bucket row, Space → cursor stays on THAT outcome (now relocated into primary list), identified by `outcome_id`, not index.
- [ ] **Step 2: FAIL** → **Step 3:** implement `_focus_outcome(state, rows, outcome_id)` mirroring `_focus_daily_item` (next() over visible rows; clamp if absent); call after `toggle_included`.
- [ ] **Step 4: gates** → **Step 5:** commit `fix: keep outcome cursor on the toggled MORE candidate`; push `fix/outcome-toggle-refocus`; PR.

---

### Task 7 (PR-H · P2) — generation_notice cleared once consumed

**Files:**
- Modify: `src/iiwi/interactive/controller.py` — `_generate` success block (~841-846) sets `state.draft.generation_notice = None`; simplify the two conditional clears in `_error_key` (~1658-1680) to rely on it
- Test: `tests/unit/interactive/test_controller_results.py`

- [ ] **Step 1: Failing test**: set fallback notice → generate fails (output conflict) → Back → generate succeeds via plain `g` → resulting `InteractiveReportResult.warnings` contain NO synthesis-unavailable warning.
- [ ] **Step 2: FAIL** → **Step 3:** implement the centralized clear.
- [ ] **Step 4: gates** → **Step 5:** commit `fix: stop leaking stale fallback notice into later reports`; push `fix/generation-notice-lifecycle`; PR.

---

### Task 8 (PR-I · P2) — Independent preview offsets, drop duplicate field

**Files:**
- Modify: `src/iiwi/interactive/controller.py:197,203` (remove dup declaration; add `session_preview_offset: int = 0`), `_session_preview_key`/`_preview_key` bodies (~1782-1827)
- Test: `tests/unit/interactive/test_controller_results.py`

- [ ] **Step 1: Failing test**: scroll REPORT_PREVIEW to offset 5 → open a session preview → scroll to 0 → back → report preview offset STILL 5.
- [ ] **Step 2: FAIL** → **Step 3:** wire session preview to the new field; delete the duplicate `preview_offset` annotation at line 197.
- [ ] **Step 4: gates** → **Step 5:** commit `refactor: separate session and report preview scroll offsets`; push `refactor/preview-offsets-split`; PR.

---

### Task 9 (PR-J · P2) — Doctor honors per-harness CLI timeout

**Files:**
- Modify: `src/iiwi/interactive/cli_actions.py:368-370` (`_doctor`)
- Test: `tests/unit/interactive/test_cli_actions.py`

- [ ] **Step 1: Failing test**: settings where `harnesses.claude_code.cli.timeout_seconds=99` ≠ opencode's; call doctor("claude-code") with a recording runner factory → constructed CommandRunner got 99.
- [ ] **Step 2: FAIL** → **Step 3:** resolve via a small match on harness name over `settings.harnesses.<name>.cli.timeout_seconds` (getattr chain, fallback to opencode section for safety).
- [ ] **Step 4: gates** → **Step 5:** commit `fix: use the checked harness's CLI timeout in doctor`; push `fix/doctor-per-harness-timeout`; PR.

---

### Task 10 (PR-D · P1 render) — Hint-bar wrapping counted in every screen's capacity

**Files:**
- Modify: `src/iiwi/interactive/render.py` — `history_capacity` (1320-1329), `settings_capacity` (1511-1521), `help_capacity` (2313-2322), `report_preview_capacity`/`session-preview equivalent` (~2091), plus their callers; `src/iiwi/interactive/controller.py` — ONLY the call-site plumbing (pass `console.size.width` where a capacity helper is called: `_settings_key` 665-670 has console; `_history_key`, `_preview_key`, `_session_preview_key`, `_help_key` may need the console param threaded exactly like `_settings_key`)
- Test: `tests/unit/interactive/test_render.py`, `tests/unit/interactive/test_viewport_wrapping_regressions.py`, `tests/unit/interactive/test_render_painting.py`

**Interfaces:** New signatures (breaking internally, single-repo update): `history_capacity(terminal_height: int, terminal_width: int) -> int`, same shape for `settings_capacity(terminal_height, *, editing, terminal_width)`, `help_capacity(terminal_height, terminal_width)`, preview capacities likewise. Chrome accounting switches from hardcoded `1` hint line to `len(_hint_lines(<screen hints>, width))`.

- [ ] **Step 1: Failing tests**: for each affected screen, render at height 24 / width 60 through the existing painting harness; assert total emitted lines ≤ terminal height (today history@60col overflows by 1).
- [ ] **Step 2: FAIL** → **Step 3: implement** the signature + accounting changes; keep `recoverable_error_detail_capacity` as the reference (it already derives footer from `_hint_lines`).
- [ ] **Step 4: gates** full suite → PASS (controller tests calling these helpers directly must be updated to the new signatures — mechanical).
- [ ] **Step 5:** commit `fix: account for wrapping hint bars in every screen's capacity`; push `fix/hint-wrap-capacity`; PR.

---

### Task 11 (PR-K · P3 render polish) — Small-terminal degradation fixes

**Files:**
- Modify: `src/iiwi/interactive/render.py` — outcome/daily body floors (`max(1, ...)` at ~738, ~1082), `render_history` indicators (~2071-2076), zero-capacity preview branch (~2091), `_history_entry_line` padding (~2039-2044)
- Test: `tests/unit/interactive/test_render.py`, `test_viewport_wrapping_regressions.py`

Four nits, one module, one review:
1. **m2**: replace `max(1, budget - fixed)` with `max(0, ...)` in outcome + daily review bodies; downstream focused-window slicing must tolerate empty windows (guard `if not window: return`). Below-height-7 screens now degrade to header+hints instead of overflowing.
2. **m4**: `render_history` prints `↑ {offset} more` / `↓ {len-end} more` indicators exactly like previews.
3. **m5**: when preview capacity is 0, print one dim line `Content needs a taller terminal.` plus `↓ {len(lines)} more` instead of the bogus `↑ N more` with zero rows.
4. **m8**: `_history_entry_line` pads columns with `cell_len`-aware spacing (use rich.cell_len) instead of `{label:>10}` char-padding.

- [ ] **Step 1: failing tests per nit** (heights 6/8 renders; history with 30 entries at height 12 asserts indicator strings present; preview at capacity 0 asserts no `↑`; CJK working-dir path alignment test)
- [ ] **Step 2: FAIL** → **Step 3: implement** → **Step 4: gates** → **Step 5:** commit `fix: degrade gracefully on very short terminals`; push `fix/small-terminal-polish`; PR.

---

## Execution Order & Lanes

| Lane | Sequence (strictly serial within lane) | File ownership |
|---|---|---|
| 1 | Task 1 (A) → Task 9 (J) → Task 3 (C) | cli_actions.py, input.py |
| 2 | Task 2 (B) → Task 4 (E) → Task 5 (F) → Task 6 (G) → Task 7 (H) → Task 8 (I) | controller.py |
| 3 | starts after Task 4 merges-or-completes: Task 10 (D) → Task 11 (K) | render.py (+controller call-site hunks) |

Importance order across lanes at merge time: A, B, C, D, E, F, G, H, I, J, K.

## Merge Protocol (after all PRs are open and green)

Merge squashes in importance order: A → B → C → D → E → F → G → H → I → J → K. After each merge, `gh pr list` + rebase any later PR showing conflicts (`git fetch origin && git rebase origin/main` in its worktree, force-push-with-lease). Watch CI with `gh pr checks <n> --watch` per merge; on red, fix in the same worktree and push.
