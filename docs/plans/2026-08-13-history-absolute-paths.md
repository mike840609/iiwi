# Absolute Paths in the Report History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `append_history` stores `output_path` resolved to an absolute path, anchored to the generation working directory, so later readers see a path that still locates the file.

**Architecture:** One change in the storage layer (`append_history` in `src/iiwi/history.py`): `replace(entry, output_path=entry.output_path.expanduser().resolve())` before serialization. Display code, readers, and legacy entries are untouched.

**Tech Stack:** Python, pathlib, dataclasses.

## Global Constraints

- Resolution happens in `append_history` only — the single writer used by both the CLI (`cli.py`) and the interactive flow (`interactive/cli_actions.py`). No call-site changes.
- Order matters: `expanduser()` first (anchor `~` to the writing user's home), then `resolve()` (anchor the relative path to the generation CWD, normalize symlinks). `resolve(strict=False)` is the default — a missing file must not raise.
- Display/reading code is untouched: the History TUI screen, `iiwi history`, and `history_to_json` keep showing the stored string. Legacy entries (already-written relative strings) are left as stored.
- The generation-time "Report written to" message still prints the path as passed.

Spec: `docs/2026-08-13-history-absolute-paths-design.md`

---

### Task 1: `append_history` resolves the output path at write time

**Files:**
- Modify: `src/iiwi/history.py:10-12` (add `replace` to the dataclass import), `src/iiwi/history.py:66-74` (`append_history`)
- Modify: `tests/unit/test_history.py` (update 2 assertions, add 4 tests)
- Modify: `tests/unit/test_cli.py:551` (update 1 assertion)

**Interfaces:**
- Consumes: `HistoryEntry` (src/iiwi/history.py:22-34), `_open_for_append` (src/iiwi/history.py:50), `history_file_path` (src/iiwi/history.py:37)
- Produces: `append_history(entry, *, path: Path | None = None) -> None` — same signature; every entry now serializes an absolute `output_path`. `read_history` and `history_to_json` unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_history.py`:

```python
def test_append_resolves_relative_output_paths(tmp_path) -> None:
    path = tmp_path / "history.jsonl"

    append_history(_entry(), path=path)

    entries = read_history(path=path)
    assert entries[0].output_path == Path(
        "reports/worklog-2026-07-27_2026-08-03.md"
    ).resolve()
    assert entries[0].output_path.is_absolute()


def test_append_leaves_absolute_output_paths_unchanged(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    target = (tmp_path / "reports" / "worklog.md").resolve()
    entry = HistoryEntry(
        generated_at=datetime(2026, 8, 3, 9, 0, tzinfo=TZ),
        harness="opencode",
        since=datetime(2026, 7, 27, 0, 0, tzinfo=TZ),
        until=datetime(2026, 8, 3, 0, 0, tzinfo=TZ),
        output_path=target,
        repository_count=1,
        session_count=2,
        narrative=True,
        detail="full",
    )

    append_history(entry, path=path)

    assert read_history(path=path)[0].output_path == target


def test_append_expands_tilde_output_paths_against_the_writing_home(
    tmp_path, monkeypatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("USERPROFILE", raising=False)
    path = tmp_path / "history.jsonl"
    entry = HistoryEntry(
        generated_at=datetime(2026, 8, 3, 9, 0, tzinfo=TZ),
        harness="opencode",
        since=datetime(2026, 7, 27, 0, 0, tzinfo=TZ),
        until=datetime(2026, 8, 3, 0, 0, tzinfo=TZ),
        output_path=Path("~/worklog.md"),
        repository_count=1,
        session_count=2,
        narrative=True,
        detail="full",
    )

    append_history(entry, path=path)

    assert read_history(path=path)[0].output_path == (home / "worklog.md").resolve()


def test_old_relative_entries_read_back_verbatim(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(
        json.dumps(_entry().__dict__, default=str) + "\n",
        encoding="utf-8",
    )

    entries = read_history(path=path)

    assert str(entries[0].output_path) == "reports/worklog-2026-07-27_2026-08-03.md"
```

Update the two assertions that pin the old relative behavior:

`tests/unit/test_history.py:63`:

```python
    assert str(entries[1].output_path) == str(
        Path("reports/other.md").resolve()
    )
```

`tests/unit/test_history.py:124`:

```python
    assert raw["output_path"] == str(
        Path("reports/worklog-2026-07-27_2026-08-03.md").resolve()
    )
```

And `tests/unit/test_cli.py:551`:

```python
    assert payload[0]["output_path"] == str(Path("reports/worklog.md").resolve())
```

(Test CWD is the repo root; `.resolve()` in the assertions matches whatever
`append_history` computes, so the tests stay correct on symlinked checkout
paths. `tests/unit/test_cli.py` already imports `Path`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_history.py tests/unit/test_cli.py -q`
Expected: FAIL — the four new tests (relative path stays relative, tilde not expanded) and the three updated assertions.

- [ ] **Step 3: Implement**

`src/iiwi/history.py`, import line 11:

```python
from dataclasses import asdict, dataclass, replace
```

`append_history` (src/iiwi/history.py:66):

```python
def append_history(entry: HistoryEntry, *, path: Path | None = None) -> None:
    """Record one report, appending it to the end of the log.

    The output path is anchored to the generation working directory: it is
    resolved here, while that directory is still the process CWD, so a later
    reader in another directory sees a path that still locates the file.
    `expanduser` runs first so a `~` is expanded against the writing user's
    home, never the reader's. Entries written before this resolution are
    left as stored.
    """

    entry = replace(entry, output_path=entry.output_path.expanduser().resolve())
    destination = path or history_file_path()
    descriptor = _open_for_append(destination)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(entry), default=_json_default, ensure_ascii=False))
        handle.write("\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_history.py tests/unit/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Run the affected modules plus lint**

Run: `uv run pytest tests/unit/interactive/test_controller.py -q` (the interactive history tests append relative paths and assert them as substrings of rendered text — absolute paths still contain those substrings, so they must keep passing)
Run: `uv run ruff check src tests`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/iiwi/history.py tests/unit/test_history.py tests/unit/test_cli.py
git commit -m "feat: anchor history output paths to the generation directory"
```

---

### Task 2: Full-suite verification

**Files:** none (verification only)

**Interfaces:** consumes Task 1

- [ ] **Step 1: Run the complete test suite**

Run: `uv run pytest -q`
Expected: PASS (the whole suite, including the interactive history tests from PR #94's branch — note: this branch is based on `origin/main`, so those tests are not present yet; when PR #94 merges, its history tests keep passing because absolute paths contain the asserted relative substrings).

- [ ] **Step 2: Run the linters**

Run: `uv run ruff check src tests`
Expected: clean.

- [ ] **Step 3: Typecheck**

Run: `uv run pyright src` (pyright is the configured type checker, `[tool.pyright]` in pyproject.toml)
Expected: clean.

- [ ] **Step 4: Manual smoke test**

Run: `iiwi report --period last-week` from a directory, then `iiwi history` — the log must show an absolute path for the report just written.
Expected: the stored path is absolute.
