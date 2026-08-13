# Absolute Paths in the Report History

**Date:** 2026-08-13

## Summary

The history log stores `output_path` exactly as the caller passed it. A report
generated from a relative path (the default `reports/…`) is recorded as a
relative string, so a user reading `iiwi history` or the interactive History
screen later sees a path that only means something relative to the directory
that no longer exists in the record. This design resolves the path to absolute
at write time — the only moment the correct anchor (the generation CWD) is
known — at the single storage chokepoint, and leaves display, old entries, and
the generated-time "Report written to" message untouched.

## Goals

- Every newly recorded history entry carries an absolute output path.
- The resolution happens at write time, not display time: a relative path has
  no correct meaning once the generation CWD is gone, and resolving at display
  time would anchor against the *viewer's* CWD instead.
- One code change point: `append_history` is the only writer for both the CLI
  and the interactive flow.

## Non-goals

- No display-side changes: the History screen, `iiwi history`, and the path
  display screen keep showing the stored string, whatever it is.
- No migration of existing entries. Old relative strings stay as stored —
  resolving them later would use the wrong anchor.
- No change to the "Report written to" message at generation time; it still
  prints the path as passed (relative stays relative).
- No change to `--output` or `output_directory` handling; the CLI already
  supports absolute paths there.

## Design

### `append_history` resolves the path

`append_history(entry, *, path=...)` (src/iiwi/history.py:66) gains a
resolved copy of the entry's `output_path` before serializing:

```python
resolved = entry.output_path.expanduser().resolve()
entry = HistoryEntry(**{**asdict(entry), "output_path": resolved})
```

- `expanduser()` first so `~` is anchored to the writing user's home, not the
  reader's.
- `resolve()` then makes the path absolute against the current working
  directory — which at append time is the generation directory, the only
  correct anchor — and normalizes symlinks (e.g. macOS `/tmp` →
  `/private/tmp`), so the recorded path is the file's real location.
- `resolve(strict=False)` is the default: the report file exists at append
  time, but a missing file must not raise.

The interactive flow appends history only for real (non-dry-run) writes
(src/iiwi/interactive/cli_actions.py:154, 241), so resolution happens exactly
once per written report, at generation time.

## Error handling

- `resolve()` cannot fail for a well-formed path; no new failure mode is
  introduced.
- Paths that are already absolute pass through unchanged.
- `~` in a recorded path is expanded at write time, so the stored value never
  depends on the reader's home directory.

## Testing

- `append_history` with a relative path records the absolute path, resolved
  against the test's current working directory.
- `append_history` with an absolute path records it unchanged (modulo
  symlink normalization).
- `append_history` with a `~`-prefixed path records the expanded path, not
  the literal `~`.
- `read_history` returns the recorded absolute path unchanged — display code
  needs no change.
- Old-format entries (relative strings) read back verbatim.
- CLI `iiwi report` followed by `iiwi history` shows the absolute path in the
  log for a default relative-output invocation.
