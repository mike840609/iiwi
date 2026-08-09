# Changelog

All notable changes to this project are documented in this file.

## Unreleased

- Rename the project to **Iiwi**: the distribution, Python package, CLI, environment
  prefix, config/data directories, update index, documentation, and release flow now use
  `iiwi` / `IIWI_*`. No compatibility alias is provided because the project has no user
  migration requirement yet.
- `iiwi --version` prints the installed version.
- `update` checks PyPI for a newer release and prints the upgrade command. It
  is the only command that touches the network and is never run implicitly;
  an available update exits with code 8, an unreachable index is reported but
  not an error.
- The Review Sessions selection is remembered per period, harness, and
  subagent setting: a rescan — or a setting change that clears the scan —
  restores what you unselected, and stale session ids are dropped
  automatically. The selection lives in a local state file, metadata only.
- Press `e` on a repository row in Review Sessions to exclude it from every
  future scan: the repository is appended to the persistent
  `report.exclude_repositories` setting (the same one `config set` writes) and
  the review rescans so the repository disappears immediately.
- `scan`, `doctor`, and the new `history` command emit machine-readable JSON.
  When stdout is piped, `scan` and `doctor` switch to JSON automatically — the
  way `mo status | jq` just works — and `--no-json` forces the human output.
  Every value is redacted before it is emitted, the same boundary the report
  and interactive paths use; `--quiet` keeps its documented contract and opts
  out of the auto-switch.
- `history` lists every report the tool has written — when it was generated,
  the period, harness, session and repository counts, whether the narrative
  review was used, and the output path. The log is append-only, lives in the
  platform data directory, and records no transcript content; a history write
  failure never fails the report that triggered it.
- Session previews: press `p` on a session row in Review Sessions or Browse
  Sessions to scroll the session's transcript inline. The preview is redacted
  before it is drawn, so it never shows more than the report itself would.
- The main menu explains each option with a dim clause in its own column, the
  way mole's menu does: `Generate Report` says what it will produce, `Settings`
  says what it edits. On a terminal too narrow for the clauses, the options fall
  back to bare labels.
- The Generate Report screen leads with its action. `Generate report` now sits
  first, above a blank line and a grey `Settings` label, with the settings beneath
  it — the screen opens on the action, so Enter immediately produces the report
  and the settings stay one arrow down. The cursor row takes the cursor's own
  bold-cyan colour on every screen, so where the cursor sits reads as one thing
  instead of two.
- Moving the cursor no longer flashes the screen. Every keypress cleared the
  terminal and then reprinted the whole frame, so between the erase and the last
  line there was a blank or half-drawn screen to see. Frames are now painted over
  each other instead: only the rows whose bytes actually changed are rewritten in
  place, so an up/down move repaints just the two cursor rows, and the cursor is
  hidden while the frame lands and parked below it afterwards. Nothing is ever
  cleared. Output to a pipe or a log is unchanged — the cursor control is only
  emitted to a real terminal.
- Sessions from a deleted git worktree rejoin their repository. Identity comes from
  running git in the session's working directory, so once a worktree is removed
  there is nothing to ask, and its sessions detached into a separate row named
  after the mangled path they used to live at. Worktrees are made and cleaned up
  routinely, so every finished piece of work eventually drifted out of the
  repository it belonged to — on one week's scan, 15 of 45 sessions. Claude Code
  records the branch each session ran on, and that branch usually still exists, so
  a detached session is reattached to the repository holding its branch. Only an
  unambiguous match counts: a branch that two repositories both have, like `main`,
  reattaches to neither, because filing someone's work under the wrong heading is
  worse than leaving it where it fell. The inference is never silent — the scan
  says how many sessions moved. Codex and OpenCode transcripts record no branch,
  so this reaches Claude Code sessions only.
- The interactive menu opens on the week in progress rather than the last complete
  one. Run it on a Friday and every session since Monday was outside the window,
  with nothing on screen saying so — the scan looked empty and the tool looked
  broken. The period row now names its window as well as dating it, so `This week`
  and `Last week` stop reading as two similar pairs of dates.
- `←→` on the period reaches all five windows. It advertised four and delivered
  two: the cycle located the current window by comparing timestamps against a
  freshly derived list, and a rolling window's end is the moment it was built, so
  every other press failed to match and snapped back to the first entry. `Last 14
  days` and `Last 30 days` could not be selected at all. Windows are identified by
  name now, which no clock can invalidate.
- The interactive screens now read as one instrument panel. Every repository carries a
  proportional bar and a percentage of the period's message volume, so the week's real
  weight is visible without opening a row, and repositories are numbered in display order
  so a long list can be talked about. Each screen titles itself above a rule and states
  what it is asking for, and the scattered footer hints collapse into a single
  pipe-separated status bar — one line on a normal terminal, where the review screen
  previously spent two. The cursor is now `▶` and the expansion arrows are `▾`/`▸`, so the
  three glyphs stacked in the gutter differ in shape rather than only in colour. The bar
  column is dropped below 80 columns, where the title matters more than the decoration.
- The Generate Report screen no longer prints its settings twice. It listed every
  setting's value in a read-only block and then repeated all seven names as a menu
  below it, with an action and a Back row mixed into the same list — fourteen lines
  carrying seven facts, and the value under edit sitting eight rows from the cursor
  editing it. The settings are now the list: the cursor rests on a value and `←→`
  changes it in place, with `Generate report` on its own row below them rather than
  buried among the settings it acts on. The screen previously had no way to generate
  at all despite its title, so that row — and `g` alongside it — is new. It answers to
  Enter only, because generating writes a file and a stray arrow key while scrolling
  the settings should not produce one. Dispatch now follows the field under the cursor
  rather than its position in a list, so a reordered or added setting cannot silently
  edit its neighbour.
  Each row also explains itself: a line under the list says what the setting the cursor
  is on actually does, since a name and a value only ever said what it was set to.
  `Sanitize` reading `N/A` on Claude Code or Codex now says why rather than leaving the
  reader to guess.
  The action row carries the cursor's own colour so it does not read as an eighth
  setting, with bold still reserved for wherever the cursor actually is — colour for
  role, weight for position, the split the row glyphs already use.
- Session review and browse rows now show density — a dim date and message count
  per session (the conversation actually recorded in the report period), a `[sub]`
  tag for subagent sessions, and a date span plus message total per repository —
  so the interactive screens carry enough signal to judge whether a session
  belongs in the weekly report without opening it. Titles stay left-aligned in a
  fixed column with the metadata in its own column to the right, so a long list
  reads down a single column of titles.
- The session review and browse headers now total message volume alongside the
  session count, so the selection can be judged by how much of the period it
  covers rather than by how many rows it holds.
- Repository and session rows now share one metadata column, so repositories can
  be weighed against each other by reading down the screen instead of by
  arithmetic. The cursor, expansion and selection glyphs each take their own
  colour rather than sharing the row's style, so the three meanings stacked in
  the gutter read as three signals instead of one run of symbols.
- Add a `report.exclude_repositories` setting, a comma-separated list of repository
  ids to leave out of every scan and report. A repository like `dotfiles` stops
  reappearing every week to be unticked by hand in the interactive picker. The
  exclusion is never silent: it adds a scan warning naming the repositories and how
  many sessions were dropped, and when the exclusion removes everything the command
  says the sessions were excluded rather than that none were found.

## 0.8.0 - 2026-08-07

- Running `agent-worklog` with no arguments opens a menu for generating a report, scanning
  sessions, checking the setup, or editing settings, instead of printing help. Each entry
  hands off to the existing command, so the menu restates none of their questions.
  `agent-worklog --help` still prints the command list. Scanning from the menu covers the
  last full week, the same period `run` offers first.
- `agent-worklog run` accepts `--dry-run`, printing the report instead of writing a file,
  matching what `report --dry-run` already did. A dry run skips the output-path question,
  since nothing is written for it to answer.
- Add `agent-worklog run`, an interactive wizard that asks the harness, the period, the
  detail level, and the pruning questions one at a time, previews the scan for approval,
  and only then writes the report. It reuses the settings catalog and prompt seams the
  `config` commands added, so it needs no list it must maintain itself.
- Previewed scans are reused rather than re-run: `run` scans once, shows the grouping for
  a yes-or-no review, and passes that same `ScanResult` into report generation so nothing
  is scanned a second time.
- Refuse to prompt when stdin is not a terminal, with exit code 3 and a message naming
  the non-interactive alternative. A `run` piped in CI fails fast instead of hanging.
- Add `agent-worklog config init`, which walks every setting in turn showing the value
  in force, and let `agent-worklog config set <key>` ask for the value when it is left
  out. Both derive their prompts from the same settings catalog `config list` uses, so
  a new field in the settings model is offered without a wizard script to maintain.
- Treat an empty answer at a prompt as "leave this setting alone" rather than as the
  empty value `config set <key> ""` writes. Nothing is recorded for a setting you press
  Enter on, so a walkthrough you answer nothing in writes no file at all; `config unset`
  stays the way to take a setting already in the file back to its default.
- Ask again instead of aborting when a prompted value is one the settings would reject,
  so a typo partway through `config init` does not discard the answers before it.
- Refuse to prompt when stdin is not a terminal, with exit code 3 and a message naming
  the non-interactive way to do the same thing. In CI or a pipeline there is nobody to
  answer, and consuming piped stdin would be a stranger failure than saying so.

## 0.7.0 - 2026-08-06

- `report` now defaults to a narrative weekly review written by the locally installed
  `opencode run`; no network request, API key, or other service is involved.
- `--no-llm` skips the narrative and emits the deterministic structured report.
- Removed `--allow-remote-llm` and the OpenAI-compatible remote summarizer (and its
  `httpx` dependency).
- Added `AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS` (default `600.0`)
  and `AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL` (default empty) to control the
  narrative invocation.
- Add `agent-worklog config` with `path`, `list`, `set`, and `unset`, so a setting can be
  recorded once instead of exported from a shell profile. Values go to a `config.env` in
  the user configuration directory, which pydantic-settings loads below the environment:
  an exported variable still wins, and `config set` says so when one already shadows the
  setting it just wrote.
- Report every setting as optional. `config list` shows each setting's value, whether it
  came from the environment, the file, or the default, and what the default is; setting a
  value to the empty string removes the entry and restores the default, as `unset` does.
- Derive the settable key list from the settings model rather than a hand-kept registry,
  so a new field in `config.py` is settable and listed the moment it exists. `config set`
  rejects an unknown key — with the closest match as a hint — and a value the settings
  would reject, both with exit code 3.
- Split the README into a condensed landing page and dedicated published docs. The
  README now points to three new files in `docs/` that hold the detail it used to
  carry: `docs/guides.md` (reporting periods, subagents, repository grouping, LLM
  summaries, and output handling), `docs/usage-statistics.md` (the usage window
  caveat), and `docs/limitations.md` (the full per-harness limit list). `README.md`
  drops from 434 to 228 lines and the Traditional Chinese `README.zh-TW.md` is
  mirrored to the same shape. Documentation links stay absolute so they resolve from
  PyPI, which renders the README as its long description. The Codex-limit assertions
  in `tests/unit/test_documentation.py` now read `docs/limitations.md` because the
  content moved there.

## 0.6.0 - 2026-08-06

- OpenCode exports are raw by default.
- `--sanitize/--no-sanitize` and the nested environment setting control OpenCode redaction.
- Remote LLM summaries require `--allow-remote-llm` per invocation.
- `--no-llm` and `--allow-remote-llm` are mutually exclusive.
- Sanitized placeholders are omitted while database session metadata is retained.

## 0.5.0

- Add `codex` to `--harness`. Sessions are discovered from `~/.codex/state_<n>.sqlite`,
  which already indexes every session with its rollout path, working directory,
  timestamps, and parent edge, so a period query is one SQL statement instead of
  opening every rollout file; a scan of `sessions/` and `archived_sessions/` is the
  fallback when that database is absent or its schema has changed.
- No Codex report claims that a command passed or failed. Codex records exit codes
  only inside free-form tool output text, in at least three formats, so a regex over
  it would fail silently the day Codex changes it. `patch_apply_end`'s `success` flag
  is the one structured signal used, and it reports a file change.
- Leave commands run from inside Codex's `exec` tool out of the report. `exec` takes
  an arbitrary JavaScript program rather than a command — a strict parse for a single
  wrapped `exec_command` call matched none of 4,963 measured calls — so its input is
  never put in an activity, which also keeps it out of outbound LLM requests.
- Build the Codex usage table by differencing the running `total_token_usage` rather
  than summing `last_token_usage`, which over-counted by 3.7% on a measured session
  because Codex emits some `token_count` events more than once.
- Drop the change values Codex records in `patch_apply_end.changes` in the mapper —
  a unified diff (`unified_diff`) for the majority `update` case, or a whole file
  (`content`) for a new one. Only the changed paths reach a session, so neither a
  diff nor a written file's full body carries toward the report's 300-character cap.
- Move the per-model usage table out of the Claude Code package. It reads only
  activity metadata, so Claude Code and Codex now share one implementation.
- Stop naming Claude Code in the missing-prompt warning for sessions from other
  harnesses.
- Lose Codex session titles when falling back to the rollout scan: across 238 measured
  rollout files, no `session_meta` payload carried a `title` key, only
  `agent_nickname` (171 of 238), and only the state database's `threads.title` column
  has the real title.
- Fix the rollout fallback picking the wrong session id. `session_meta.session_id` is the
  originating/root thread id, inherited by every resumed session and every subagent, not
  the session's own id; `session_meta.id` is. Measured against a real `~/.codex`, 220
  rollout files carried 220 distinct `id`s but only 42 distinct `session_id`s, so the
  fallback path was collapsing 220 real sessions onto 42 report entries. The descriptor
  now prefers `id`, falling back to `session_id` only when `id` is absent.
- Stop treating machine-injected `event_msg/user_message` payloads as human goals.
  Codex writes attached shell input/output, browser context, file-mention envelopes,
  slash-command records, task notifications, and resume summaries using the same
  `user_message` record type as a real prompt, and none of them carried a marker the
  mapper checked for. Measured against real data, 88 of 592 `user_message` payloads
  were machine-injected, including raw local command output that `docs/privacy.md`
  promises never reaches a report. The mapper now drops a `user_message` whose text
  opens with one of a documented set of markers, contributing no goal for it; a message
  sent with attachments therefore contributes no goal at all rather than a
  mis-attributed one.

## 0.4.1

- Redact the repository name in `scan`'s table and in `scan --verbose`'s
  repository heading, and stop the table from interpreting that name as Rich
  markup. Both call sites now match the session listing's existing handling, so
  the same repository's name can no longer read differently across the two
  views of one `scan` run.
- Report Claude Code verification commands as completed when the harness observed
  them succeed. Claude Code records no exit code, so the extractor treated every
  command as having an unobservable outcome and `Completed` was empty in every
  report — measured across 282 real sessions, it fired zero times. Claude Code
  does record `is_error` on the tool result, which is observed rather than
  inferred, and the mapper was dropping it: a *failed* call records
  `toolUseResult` as a plain error string instead of an object, and the mapper
  required an object before reading anything. On the same 282 sessions this
  yields 354 completed verifications and 143 observed failures, where both were
  previously zero. Where a real exit code exists it still wins, being the more
  precise signal.
- Stop treating a test command named inside a heredoc as a verification run.
  `gh pr create --body "$(cat <<'EOF' … pytest … EOF)"` runs no tests; matching
  the whole command string accounted for 26 of 378 matches on real transcripts.
  This was harmless while such items were only recorded as having run, but an
  observed success would have promoted each one to a false "Verification passed"
  claim in the report.
- Move report list truncation from the rule-based summarizer into the Markdown
  renderer, so there is one truncation point and the `Additional items omitted`
  count is always the real remainder. LLM-produced lists are now capped at 20
  items like rule-based ones; they were previously unbounded. The overflow line
  under `Key Files` is no longer wrapped in backticks — previously the
  summarizer injected it into the `key_files` list itself, so the template's
  code-item formatting wrapped it like a filename, which it never was.
- Add `--detail {full,brief}` to `report`, defaulting to `full`, which is the
  existing output. `--detail brief` keeps the header, and for each repository the
  summary and up to five each of Completed, Problems Resolved, and In Progress;
  it leaves out Key Files, Directories, Sessions, Branches, and the usage table.
  Warnings are kept at both levels.
- List each repository's session titles and working directories under
  `scan --verbose`, so the selected sessions can be checked without generating a
  report. Titles and directories are redacted before printing; the Claude Code
  path has no upstream sanitize step.

## 0.4.0

- Rewrite both README capability lists as outcome-oriented capability summaries while
  keeping harness-specific acquisition and accounting details in their dedicated sections.
- Keep the runtime and project versions consistent with release metadata, and correct the
  stale Claude Code stderr limitation.
- Add `--harness {opencode,claude-code}` to `doctor`, `scan`, and `report`, defaulting
  to `opencode`. Read Claude Code session transcripts directly from
  `AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY` (default
  `~/.claude/projects`); `--harness claude-code` runs no external harness CLI, and
  `doctor` instead checks that the projects directory exists and is readable, plus
  `git --version`.
- Build the Claude Code usage table from token counters recorded on the sessions
  themselves, so it covers the report period rather than a trailing window ending at
  report generation time, which is what `opencode stats` still reports. Every model turn
  in the period is counted, including turns that emitted only internal reasoning; their
  tokens are carried by the neighbouring recorded activity, which is also the table's one
  imprecision — a turn on the period boundary can be counted on the other side of it.
- Report Claude Code verification commands without claiming an outcome. Claude Code tool
  results carry no exit code, so a command whose stderr was empty is recorded as `Ran
  verification command: <command>` at MEDIUM confidence with an unknown status, and
  appears under "In Progress" rather than "Completed". A command that redirects or
  discards its stderr (`2>`, `&>`, `|&`) produces no outcome at all, because its empty
  stderr is an artefact of the redirection. "Verification passed" remains reserved for the
  OpenCode path, which observes a real exit code.
- Stop treating non-empty stderr as a failed command on the Claude Code path. Git writes
  to stderr on success, so the rule produced 31 items of `git stash` and `cd … && uv sync`
  noise against real transcripts — none of which any report section renders, while all of
  them travelled in the outbound LLM request. Only an observed exit code now records a
  failure, which keeps the LLM and `--no-llm` reports describing the same set of problems.
- Cap every evidence item's text at 300 characters for both harnesses, marking the cut
  with an ellipsis. A Claude Code `input.command` is retained whole, so a heredoc used to
  write a file previously carried that file's entire body into the report and into
  optional LLM requests; secret-pattern redaction cannot detect such text.
- Group a Claude Code session that spans several working directories under the last
  one, and read subagent transcripts alongside root sessions, excluded by `--root-only`
  like OpenCode child sessions.
- Warn when a root session records assistant work but no user messages. A Claude Code
  transcript written before roughly version 2.1.187 does not mark human prompts, so such
  a session contributes no goals; the warning replaces a silent loss. Subagent sessions
  are exempt, because a subagent is spawned with its parent's prompt and holds no human
  prompt by design.
- Skip models whose usage totals are all zero in the Claude Code usage table, so the
  `<synthetic>` placeholder Claude Code writes for local and error turns no longer adds
  an all-zero row.
- Honor `AGENT_WORKLOG_HARNESSES__*__ENABLED`. Selecting a disabled harness now fails
  with a configuration error (exit code 3) instead of the setting being ignored.
- Move the shared subprocess runner out of the OpenCode package into
  `agent_worklog.process.CommandRunner` so both harnesses depend on one implementation.
## 0.3.0

- Add a transient, single-line progress status to `scan` and `report`, showing the
  current stage and accurate session or repository counts during long operations.
- Keep progress on stderr so `report --dry-run` stdout remains valid Markdown, and
  suppress progress completely with `--quiet`.
- Keep progress labels generic to avoid exposing session, path, repository, warning,
  or API details; clip long statuses to one row on narrow terminals.

## 0.2.0

- Re-release 0.1.1 under a correct semantic version. That release added features, so it
  belongs in a minor version. The contents are otherwise unchanged; prefer 0.2.0.

## 0.1.1

- Add a Traditional Chinese README and a status badge row, and declare MIT and
  Python 3.11–3.13 classifiers so the PyPI project page reports them.
- Add `--root-only` to `scan` and `report` to exclude child and subagent sessions. Child
  sessions remain included by default and stay attributed to the repository they ran in.
- List each repository's session titles, session IDs, and working directories in the report.
  Session identifiers are always derived from recorded evidence, never from an LLM response.
- Add a `## Usage` report section from `opencode stats`. The window runs from the report
  period's start to generation time, because OpenCode reports usage only for a window ending
  now; the report states this. An unavailable `opencode stats` becomes a warning, not a
  failed report.
- Translate subprocess timeouts and launch failures inside the command runner, so a hung
  `opencode` or `git` call degrades to a failed check or a fallback identity instead of an
  unhandled traceback.
- Read the clock once per `report` invocation, so `--days N` no longer reports an N+1 day
  usage window. An invalid timezone is now reported before invalid period selectors.

## 0.1.0

- Add an installable Python 3.11+ CLI with `doctor`, `scan`, and `report` commands.
- Query OpenCode sessions across all projects through the OpenCode CLI.
- Select sessions by interval overlap and filter exact half-open activity ranges.
- Export transcripts with `--sanitize` and tolerate individual export failures.
- Normalize Git remotes and group sessions from multiple worktrees by repository.
- Preserve repository ownership for parent and child sessions.
- Extract provenance-aware evidence and recursively redact common secrets.
- Generate secure deterministic Markdown reports.
- Add optional OpenAI-compatible structured summaries with retry and fallback.
- Add Python 3.11–3.13 CI and trusted-publishing release automation.
