# CLI reference

Every command, option, and exit code. For a guided tour instead, see the
[README](../README.md); for settings, the
[configuration guide](configuration.md); and for outcome review, the
[evidence-first Quick Review guide](evidence-first-quick-review.md).

## Commands

| Command | What it does |
|---|---|
| `doctor` | Checks that the selected harness and `git` are ready to use. |
| `scan` | Shows which sessions fall in a period and how they group into repositories. |
| `report` | Writes the Markdown report for a period. |
| `history` | Lists the reports this tool has written. |
| `update` | Checks PyPI for a newer release. |
| `run` | Walks you through the wizard: pick a harness and period, preview the scan, then write the report. |
| `config` | Shows and edits the settings file: `path`, `list`, `init`, `set`, `unset`. |

Running `iiwi` with no arguments opens the key-driven interactive menu.
`iiwi --help` prints the command list instead, and `iiwi
--version` prints the installed version. Direct subcommands remain unchanged
and are still the supported interface for scripts, CI, and pipelines.

## Interactive mode

The bare command uses `↑/↓` or `j/k` to move, `Enter` to select, and `q` to leave the
current flow. The main screen offers Generate Report, Browse Sessions, Check Setup, and
Settings. Completed actions return to an interactive screen or the main menu instead of
requiring a new process.

Generate Report opens a summary before scanning. Harness, period, detail, subagent
inclusion, narrative mode, sanitize mode, and dry-run mode can be changed independently;
only harness, period, subagent inclusion, and sanitize changes invalidate a cached scan.
When editing harness or period, Enter keeps the value already shown in the draft. Sanitize
is shown as unavailable for non-OpenCode harnesses rather than acting like a selectable
setting that can change those sources.

Review Sessions groups the scanned activity by repository. On a repository row, `Space`
toggles the whole repository and `Enter` expands or collapses it. Inside an expanded
repository, `Space` toggles an individual session and `p` opens a scrollable preview of
that session's transcript (redacted before display). The repository marker is derived from
its children: `●` means all selected, `○` means none selected, and `◐` means partially
selected. `a` selects all sessions, `n` selects none, `g` synthesizes the selected
sessions and opens Quick Review, and `b` returns to the setup summary. A report cannot
be generated with zero selected sessions. Long session
lists use the terminal height as a viewport, keeping the active row visible and showing
`↑ N more` / `↓ N more` when rows exist outside the current window. Browse Sessions also
answers to `p` on a session row.

The selection is remembered per harness, period, and subagent setting in a local state
file. A rescan — including one triggered by changing a setting that clears the scan —
restores the previous selection, with session ids that no longer exist dropped
automatically; periods with no stored selection start from the noise-free default.

### Quick Review

Quick Review is outcome-first and targets a 30–60 second review. It preselects up
to five synthesized outcomes. Every additional result remains available under
**More candidates**; a reviewer can exclude a primary outcome and include one of
these candidates instead. A session whose evidence could not be synthesized stays
visible under **Ungrouped candidates** rather than disappearing.

The review keys are:

```text
Space Include/exclude │ e Edit │ J/K Reorder │ v Evidence │ s Split │ a Add
p Preview │ g Generate │ b Back
```

`Space` includes or excludes the focused outcome. `e` edits its title, status, and
Impact. `J/K` reorders it, `v` expands its evidence, and `s` splits a merged
cross-repository outcome back into its traceable source groups. `a` creates a
User-added outcome. Blockers and Next week are optional editable rows.

`p Preview` renders the current in-memory draft without writing a file; `b` returns
from the preview with edits intact. `g Generate` writes the reviewed draft. A
recoverable preview or output error returns to the same draft. A complete synthesis
failure offers Retry and an explicit, labeled session-based report fallback. Partial
synthesis opens Quick Review with the successful outcomes and the remaining
Ungrouped candidates.

On a repository row, `e` adds the repository to the persistent
`report.exclude_repositories` setting and rescans, so the repository vanishes from the
review and from every future scan. The same setting can be edited with
`config set report.exclude_repositories ...` and reset with `config unset`.

Interactive reports use the normal default output path. If that path already exists, the
recovery screen offers **Overwrite once**; it does not silently replace the file. After a
successful report, the result screen can return to the main menu, start another report
with the same option values, or print the report path. Browse Sessions is read-only in
this release.

## Shared options

`scan` and `report` share these options:

| Option | What it does |
|---|---|
| `--days N` | Reports the last N days, ending now. |
| `--period last-week` | Reports the previous full calendar week. `last-week` is the only accepted value. |
| `--since ISO` | Starts the period at an exact time. |
| `--until ISO` | Ends the period at an exact time. Requires `--since`. |
| `--harness NAME` | Harness to read sessions from: `opencode` (default), `claude-code`, or `codex`. |
| `--root-only` | Leaves out child and subagent sessions. |
| `--sanitize / --no-sanitize` | Enables or disables OpenCode export redaction. Raw export is the default. OpenCode only. |
| `--verbose` | Also shows export, fallback, and narrative warnings. For `scan`, also lists each repository's session titles and working folders. |
| `--quiet` | Shows only the session count for `scan`, or the output path for `report`. |
| `--json / --no-json` | Emits machine-readable JSON (redacted) instead of the human output. When stdout is piped, JSON is the default; `--no-json` forces the human output. `doctor` and `history` accept the same flag. |

Three rules apply:

- Give exactly one of `--days`, `--period`, or `--since` (`scan` and `report`).
- Use `--until` only together with `--since` (`scan` and `report`).
- Do not use `--verbose` and `--quiet` together (all three commands).
- Do not use `--json` and `--quiet` together (`scan` and `doctor`).

## Machine-readable output

`scan --json`, `doctor --json`, and `history --json` print a single JSON
document to stdout; progress stays on stderr. Every value is redacted before
it is emitted, matching the redaction the interactive and file paths apply.

`scan --json` emits:

```json
{
  "period": { "since": "...", "until": "..." },
  "candidate_session_count": 10,
  "loaded_session_count": 8,
  "failed_session_count": 1,
  "excluded_session_count": 0,
  "repositories": [
    {
      "id": "git:github.com/mike/iiwi",
      "name": "Iiwi",
      "sessions": [
        { "id": "...", "title": "...", "messages": 42, "directory": "/path" }
      ]
    }
  ],
  "warnings": []
}
```

`doctor --json` emits `{"harness": "...", "ok": true, "checks": [{"name": "...",
"ok": true, "detail": "..."}]}`, and `history --json` emits an array of
recorded reports. When stdout is not a terminal, `scan`, `doctor`, `history`,
and `update` switch to JSON automatically, so
`iiwi scan --period last-week | jq '.repositories'`
just works; `--quiet` keeps its human contract and opts out of the auto-switch.

## Progress output

While `scan` and `report` are working, they show a transient progress status with the
current stage. Session and repository stages also show a `completed/total` count.
`--quiet` hides the progress status. For `report --dry-run`, progress is written to
stderr so stdout contains only Markdown.

## report

`report` also accepts:

| Option | What it does |
|---|---|
| `--output PATH` | Writes to this file instead of the default folder. |
| `--force` | Replaces the output file if it already exists. |
| `--dry-run` | Prints the Markdown instead of writing a file. |
| `--no-llm` | Skips the local `opencode run` narrative and emits the deterministic structured report. |
| `--detail LEVEL` | How much detail the report contains: `full` (default) or `brief`. |

`--detail brief` produces a short report for a status update: it keeps the
header, and for each repository the `Repository:` remote line, the session
counts, and the summary and up to five each of Completed, Problems Resolved,
and In Progress. It leaves out Key Files, Directories, Sessions, Branches, and
the usage table. Warnings are always kept, at both detail levels, because they
report data the tool could not read rather than work you did.

## run

`run` accepts `--verbose`, `--dry-run`, and `--detail brief|full`. When `--detail`
is omitted, it asks the harness, the period, the detail level, and the pruning
questions one at a time, previews the scan for approval, and only then writes the
session-based report. `--detail` supplies that answer without a prompt; it does not
invoke outcome synthesis. `--dry-run` prints the report instead of writing a file,
and skips the output-path question since nothing is written for it to answer.

`run` and `config init` need an interactive terminal, so they refuse to run when stdin
is not a terminal; `scan` and `report` cover the non-interactive route.

## doctor

`doctor` accepts `--harness NAME`, `--quiet`, `--verbose`, and `--json`. `--quiet` hides the
list of checks and reports only through the exit code; `--verbose` does not change what
`doctor` prints.

With `--harness claude-code`, `doctor` checks that the configured `~/.claude/projects`
directory exists and is readable, instead of checking for the `opencode` executable and
database. With `--harness codex`, `doctor` checks that the configured `~/.codex`
directory exists and is readable, and reports which discovery path it will take: the
state database by name, or `directory scan` when none is present.

## history

`history` lists every report this tool has written, newest first: when it was
generated, the period, the harness, session and repository counts, whether the
narrative review was used, and the output path. It accepts `--json` and prints
`No reports generated yet.` when the log is empty. Reports written with
`--dry-run` are not recorded, and a history write failure never fails the
report that triggered it.

## update

`update` compares the installed version against the latest release on PyPI and
accepts `--json`. It is the only command that touches the network, and it only
does so when run. When an update is available, the command prints the new
version and the upgrade command and exits with code 8; up to date means exit 0.
An unreachable index is not an error — offline machines are legitimate — so a
failed check prints the reason and exits 0, and in JSON mode emits
`{"error": "..."}`.

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | Success |
| 2 | Invalid command options |
| 3 | Settings error |
| 4 | No matching activity |
| 5 | Harness or Git dependency error |
| 7 | Report file error |
| 8 | Update available (`update` only) |

If one session cannot be read, Iiwi skips it and adds a warning to the report.
If no sessions can be read, the command stops with an error instead of creating an empty
report.
