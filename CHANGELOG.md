# Changelog

All notable changes to this project are documented in this file.

## Unreleased

- **`q` means back one level, on every screen except the main menu.** It used
  to jump straight to the main menu from wherever you were, which on a child
  screen skipped a level: pressing it in Quick Review discarded the whole draft
  with no way back, and in a preview it closed the screen the preview had been
  opened from as well. `q` now does exactly what `b` does — Quick Review
  returns to the session list, a preview returns to what opened it, the error
  screen returns to its own back screen — and on the main menu it still exits.
  The error screen keeps its explicit **Main menu** option, so the top is one
  Enter away rather than gone.
- Escape clears an active session search rather than leaving the review.
  Committing a search with Enter and then pressing Escape used to navigate
  back, which is what `b` is for, leaving no way to drop the filter without
  losing your place. Escape now clears it and keeps you where you are.
- Excluding a repository no longer rescans the disk. The exclusion is applied
  to the scan already in memory and the selection is pruned to match, so the
  review comes back immediately instead of reading every session again to
  produce a smaller version of what it already had.
- The unreachable browse screen is gone. Review Activity has landed on the
  selectable review screen since the activity flows were unified, so the
  separate browse-only screen behind it had no way in — about 290 lines that
  could still be maintained but never run.

## 0.13.0 - 2026-08-16

- Quick Review says a selection is too large before the model run, not after
  it. The evidence budget used to make its cut silently during synthesis: you
  waited, and then a report arrived covering the newest sessions that fit with
  the rest listed as ungrouped candidates. The selection is now measured on
  Review Sessions, before `opencode run` is spent, and an over-budget selection
  says so on the spot — how many are selected, how many synthesis carries, and
  the payload size against the budget. Narrowing the period or deselecting what
  does not belong is the first answer; `G` takes the old behaviour deliberately,
  grouping the newest that fit and leaving the rest as ungrouped candidates with
  the same warning. The measurement is the payload's own size rather than a
  session count, so one session too large for the whole budget is caught as
  well, and a session whose evidence could not be extracted is not mistaken for
  a budget problem.
- Non-ASCII input works on POSIX terminals. Each raw byte was decoded on its
  own with `errors="ignore"`, so a CJK, accented or emoji character decoded to
  nothing at all, one byte at a time — model names, paths, time zones,
  settings values and search queries with any of those characters simply could
  not be typed. The reader now collects a whole code point before decoding it.
  The escape-sequence path is byte-for-byte unchanged: `0x1b` is neither a UTF-8
  lead nor a continuation byte, so the two cases never overlap.
- The settings editor scrolls on a short terminal. Sixteen settings plus
  section headers and chrome is 31 rows, printed unconditionally, so on a
  20- or 24-row terminal navigating to the lower settings pushed the selected
  row, its description and the footer off screen. The editor now windows to the
  terminal height, always keeping the selected row and the footer visible, and
  marks what is outside the window with `↑ N more` / `↓ N more`.
- Invalid timeouts and time zones are rejected before they are written.
  Validation checked only a leaf's primitive type, so `timeout_seconds nan` and
  `report.timezone Mars/Olympus` were accepted and saved, then crashed `doctor`
  or failed the next scan — the settings file had to be repaired by hand. A
  value now goes through its owning model's full validation, which covers
  `config set`, `config init` and the interactive editor at once, and nothing
  is written when it fails.
- A reversed date range is a usage error rather than a traceback. `--since`
  later than `--until` reached the model directly and surfaced as exit 1 with a
  Rich traceback, while every other invalid option exits 2 with one line. It is
  now `--since must be earlier than --until` at exit 2, for `scan` and `report`
  alike. An equal pair, and a `--since` in the future against the default
  `--until` of now, take the same path.
- The update check orders releases the way PEP 440 does. A hand-written tuple
  parser fell back to extracting digits for forms it did not know, so `1.0.0`
  against `1.0.0.post1`, and `999.0.0` against `1!1.0.0`, both reported no
  update available when one was. Comparison uses `packaging.version` now, and
  an index version that cannot be parsed reports a failed check instead of a
  confident wrong answer.
- Evidence extraction no longer scales quadratically. Deduplication rebuilt a
  set from the entire growing evidence list for every candidate: 1,000 items
  took 0.05s, 2,000 took 0.20s, 4,000 took 0.81s and 8,000 took 3.64s —
  doubling the input cost about four times as much. One persistent set per
  collection makes membership amortized constant, with ordering and
  case-insensitive deduplication unchanged. Busy transcripts and
  multi-repository reports feel it on both report paths, Quick Review included.
- **The automatic migration from `agent-worklog` 0.8.0 is gone.** Settings,
  report history and session selection were adopted from an old install on
  first run; that path was meant to last one release past 0.9.0 and this is
  0.13.0. Anyone still holding 0.8.0 state should run 0.12.0 once to adopt it
  before upgrading. The `IIWI_*_FILE` environment overrides are untouched.

## 0.12.0 - 2026-08-14

- Daily Standup. `iiwi daily`, or **Daily Standup** from the main menu, turns
  yesterday's and today's coding-agent activity into a short update you review
  before anything is written. There is no period or harness picker: it reads
  every enabled harness over one local-calendar window, from yesterday at 00:00
  through the moment it started, and projects that evidence into **Yesterday**,
  **Today** and **Blockers**. Activity timestamps decide which section a piece
  of work lands in, so `Activity today` means work actually happened today,
  while `Suggested from yesterday` appears only where yesterday carries explicit
  unfinished evidence and is a proposal to confirm rather than a claim that the
  work continued. `Space` includes or excludes a line, `e` edits it, `J`/`K`
  reorder, `a` adds an item the sessions do not cover, `v` shows the evidence
  behind a line, `p` renders the draft without writing it and `g` writes
  `daily-standup-YYYY-MM-DD.md`. Refreshing later in the day keeps every edit,
  exclusion and ordering already made and flags what is new since the last look;
  the reviewed draft is kept owner-only on your machine for that date and
  cleaned up after 30 days. If grouping is unavailable, Daily retries once and
  then falls back to a draft built from local evidence alone, saying so in the
  review and in the written report rather than letting raw evidence pass as a
  grouped update; a later refresh that does group successfully replaces that
  fallback instead of leaving its raw text behind. If a harness cannot be read
  the review says which one and continues on the rest.
- Blockers reports only failures worth reporting. A command exiting nonzero is
  not by itself a blocker: an agent's shell is mostly exploration, and
  exploration fails constantly without anything being blocked. Measured over one
  real Daily window — 115 sessions across three harnesses and eight
  repositories — 62 commands were observed to fail, and 50 of them were
  `git log`, `rg`, `ls`, `sed -n`, `sleep; gh pr view` and
  `echo "=== HEAD ==="`. Only the verification commands iiwi already recognizes
  can become candidates, a candidate resolved by a later completion or a later
  successful rerun drops out, and whatever survives starts excluded so an error
  is never published without review.
- History from inside the TUI. The interactive menu gains a **History** row, a
  read-only list of past reports and their output paths, reading the same
  append-only log as `iiwi history` so finding an earlier report no longer means
  leaving the app. Newly recorded entries store an absolute path: the log kept
  `output_path` exactly as it was passed, so a report written to the default
  relative `reports/…` was recorded as a string that only meant something in a
  directory the reader no longer stands in. Resolution happens at write time,
  the only moment the generating directory is known; entries already recorded
  stay as stored, since resolving them later would anchor them to the wrong
  directory.
- Settings is an editor rather than a wizard. The menu entry used to drop into
  the linear `iiwi config init` prompts, one blank line per setting, and a blank
  line never says what belongs there — two settings even defaulted to an empty
  `[]`. It now opens a full-screen editor in the style of the Generate Report
  screen: every row shows its current value, settings with a fixed set of
  choices (`enabled`, `sanitize`, `quick_review_report_type`, `source`,
  timezone) cycle through them with `←→`, and the rest edit inline on Enter with
  the current value pre-filled. A change is written the moment it is made, so
  `config list` and later runs see it. A value coming from an environment
  variable shows as `[environment]` and stays read-only, because writing it to
  the settings file would silently do nothing.
- The wordmark is a softer scarlet. `#D93B28` still reads as the bird's red
  rather than a different colour, and clears 4.6:1 on both a black and a white
  terminal. It is the one surface in the TUI that carries identity rather than
  state, so nothing that carries meaning changes and red stays free for errors.
- Quick Review says what it is doing while it groups. Synthesis is one
  `opencode run` with a ten-minute timeout, and it reported nothing at all: the
  interactive app paints each frame over the last and repaints only between key
  presses, so after `Exporting sessions` the screen held its final frame for as
  long as the model took, with no way to tell a slow run from a hung one. That
  step now shows `Grouping sessions into outcomes` with the time it has been
  running, animated from Rich's own thread so it keeps moving while the
  subprocess blocks.
- Stages that count their work draw a progress bar. Exporting sessions,
  preparing evidence and summarizing repositories already reported a total and a
  completed count and rendered them as `8/20` beside a spinner; the same numbers
  now also fill a bar. The grouping pass above deliberately has no bar: it is a
  single opaque subprocess with no total to divide by, and Rich draws a
  totalless bar as a pulse animated through colour — which with colour off, or
  through a pipe, is a solid full-width bar that reads as finished work. Where
  there is no fraction to show, the spinner and the elapsed timer say the stage
  is alive without claiming one.
- Progress output is silent off an animatable terminal rather than by accident.
  A redirected or dumb-terminal stream now skips the reporter outright, instead
  of relying on Rich to draw nothing there — `Progress` leaves a stray newline
  in that case, which the interactive app would paint over.
- Distinct repositories stay distinct. Remote normalization parsed a
  scheme-less local remote such as `../upstream.git` as a network URL, so
  unrelated clones sharing that relative origin collapsed into one repository,
  and it dropped non-default SSH ports, so `example.test:2222/org/repo` and
  `:3333` were the same identity. A scheme-less value that is not scp-style —
  git's own rule, a colon before the first slash — is now read as a local path
  and falls back to the git common-dir identity, and a non-default port stays
  part of the identity while the default ports (ssh 22, git 9418, http 80,
  https 443, ftp 21, ftps 990) are dropped so the explicit and implicit forms
  still match.
- A session from a deleted worktree is reattached only on path evidence.
  Reattachment accepted a single live repository containing the recorded
  branch, with nothing else connecting the two, so a common branch such as
  `main` could file a session under the wrong repository — and with it the
  report grouping, the exclusions and the Quick Review selection. It now takes
  two pieces of evidence: the session's recorded working directory must be
  path-related to the live repository (one nested inside the other, or both
  sharing a parent, the two layouts `git worktree` actually produces) and
  exactly one such repository carries the branch. Without both, the session
  keeps its fallback identity.
- Usage statistics reach the model instead of racing it. The full narrative
  prompt asks for a usage overview from attached statistics, but usage was
  collected after the model had already run and appended afterwards by the
  renderer — so the model had nothing to read and could invent numbers, report
  usage as unavailable, or write a section competing with the rendered
  `## Usage` block. Usage is now collected first and travels in the same
  transcript file the model reads. Brief detail and `--no-llm` are unchanged.
- An OpenCode message with no timestamp stays timestamp-less. The mapper
  substituted the session descriptor's `updated_at`/`created_at`, and the
  exact-period filter treated that substitute as authoritative, so an export
  with per-message times stripped or drifted could attribute old content to the
  requested week without saying so. Those messages now carry no timestamp and
  take the existing warning-and-exclusion path.

## 0.11.0 - 2026-08-12

- Quick Review. `Generate report` no longer writes a file straight away: it
  opens a review of evidence-backed outcomes synthesized from the sessions you
  selected, and nothing is written until you approve it. Each outcome can be
  edited, reordered, included or excluded; a cross-repository outcome can be
  split back into its source groups, and an outcome the sessions do not cover
  can be added by hand and is labelled as such in the report. The first five
  candidates are selected, the rest wait under **More candidates**, and a
  session whose evidence extraction failed stays visible under **Ungrouped
  candidates** rather than disappearing. Every title, status, impact and
  reference is reconstructed from the extracted evidence rather than taken from
  the model's prose — the model proposes the grouping, and a proposal the
  evidence does not support is replaced by one built from the evidence itself.
  `p` renders the exact draft without writing it; `g` writes that draft, at the
  Report type and Detail on screen.
- **The default Detail for interactive reports changes from Full to Brief.**
  `Generate report` now routes through Quick Review, Quick Review opens on the
  report type saved in `report.quick_review_report_type`, and that setting
  defaults to `manager` — which defaults to Brief. Brief drops the files,
  sessions and usage sections. To keep the old output, either press Enter on
  the Quick Review `Report` row to switch to Engineering, set
  `iiwi config set report.quick_review_report_type engineering`, or change
  Detail under Advanced settings, which is remembered for the run.
- Quick Review works on a full week again. Synthesis sent every selected
  session's evidence in one `opencode run` and demanded strict JSON back, so a
  realistic selection — over a hundred sessions, more than a megabyte — came
  back as prose or as nothing, and the only way out was the session-based
  fallback. The model now gets a compact index instead — session id,
  repository, title, branch, the first goal and one outcome, each whole, since
  that text is exactly what it reads to decide whether two sessions are the
  same work. At about 580 bytes a session rather than several kilobytes, the
  default `report.quick_review_max_evidence_bytes` of `40000` carries around 65
  of the most recent sessions instead of seventeen; the rest skip the model and
  stay as ungrouped candidates, with a warning naming how many were held back
  on screen and in the report. Raising that budget is not simply a matter of a
  larger number: measured over a real week, `40000` returns grouped outcomes,
  `80000` comes back without valid JSON, and `120000` runs past the 600-second
  timeout.
- Iiwi no longer reports on itself. Every `opencode run` iiwi invokes leaves a
  session in the OpenCode store, and the next scan was picking those up as
  work — fifteen of them in one real 30-day window. They are dropped during the
  scan now, so they are absent from Quick Review, Browse Activity, the
  session-based report, and every session count — except the Usage section,
  an external `opencode stats` aggregate the scan cannot filter.
- Quick Review no longer overflows the terminal. With both disclosure sections
  open on a short, narrow terminal the focused outcome's block was printed in
  full regardless of the budget, so the frame ran one row past the last line
  and the paint left a torn screen behind. The body is clamped where it is
  printed: the scroll indicators go first, then the focused block's trailing
  detail lines, and its summary row always stays visible.
- A grouped outcome's title reads as one line. When the model's proposed title
  is not supported by the evidence, the fallback used to join every session
  title in the group with slashes, so a group of eleven rendered as eleven
  clauses. It now names the session with the most extracted evidence and counts
  the rest: `The real work and 10 more sessions`. A multi-repository group
  still joins repository ids with ` / `, unchanged.
- A proposed title survives when the evidence substantively supports it. The
  check required every word longer than two characters to appear in the
  evidence; across one real synthesis that refused five of ten proposals over
  words like `polish` and `housekeeping` while every substantive term matched.
  Eighty percent of the words now suffice, recovering four of the five — the
  66.7% case is still refused. Status and impact keep their existing, stricter
  checks.
- `J`/`K` reorders within the outcome's own section. Quick Review lists
  primary, more, and ungrouped outcomes separately, but reordering worked on
  the global rank, so moving a primary outcome past a candidate hidden behind a
  disclosure row changed nothing on screen. Reordering now swaps with the
  adjacent outcome in the same section and stops at either end of it.
- The help screen documents Quick Review. `Space`, `e`, `J`/`K`, `v`, `s`, `a`,
  `p` and `g` are listed with what they do on that screen, and the four keys
  that mean something else there — `a`, `e`, `p`, `g` — are marked in the
  general list. The reference scrolls with `↑↓`/`jk` rather than running off a
  short terminal.
- The report result screen dropped its unreachable **Preview report** option.
  Interactive generation always writes a file, so the dry-run variant of that
  screen could no longer be reached.

## 0.10.0 - 2026-08-11

The interactive interface is the release. Opening `iiwi` with no arguments
leads with reviewing what the agent did rather than with generating a report,
and the two session screens behind that are now one screen.

- The home screen is activity-first. The subtitle reads `See what your agent
  did`, `Review Activity` is the first action and `Generate Report` the
  second, and the numeric shortcuts follow the visible order. The direct CLI
  commands are unchanged.
- Browse Sessions and Review Sessions are one activity explorer. The two were
  split by what you could do in them — browsing was read-only, review existed
  only to produce a report — so finding something worth reporting on meant
  leaving one screen and finding it again in the other. Both entries now open
  the same selectable repository and session tree, and `g` generates from it
  directly. Search, preview, rescan, repository exclusion, selection
  persistence, viewport behaviour, and Back are unchanged.
- Report Setup separates the actions from the configuration. `Generate report`
  and `Preview report` sit at the top, and `Preview report` takes the dry-run
  path internally so the preview opens without writing a file — `Dry run` is
  no longer a setting to find and switch. `Harness`, `Period`, and `Advanced
  settings` remain in the list; `Detail`, `Subagents`, `Narrative`, and
  `Sanitize` move under `Advanced settings`, which starts collapsed for each
  new report flow and toggles with Enter.
- The footer hints are shorter. Each screen lists the actions it is actually
  for — select, inspect, search, report, help, back on Review Activity — while
  `a`, `n`, `e`, `R`, `h`/`l`, the paging keys and the rest keep working and
  are documented under `? Help`. The rows this frees go to content.
- The main menu opens on the name drawn in ASCII rather than the word `Iiwi`
  in bold, with the version flush right on the wordmark's last row so the art
  costs four rows instead of five. Below either gate — 24 rows or 24 columns —
  the previous one-line header returns unchanged: a wordmark clipped mid-glyph
  reads as noise rather than as a name, so a small terminal gets the word.
- The wordmark is drawn in `#E0301E`, the ʻiʻiwi's plumage, at 4.6:1 contrast
  on both a black and a white terminal. It is the only place a hex colour
  appears — the rest of the interface stays on plain ANSI names so it follows
  the terminal's own theme, which is the right rule for colours that carry
  state and the wrong one for a logo. Rich degrades the colour on terminals
  without truecolor.
- The PyPI badge fix that 0.9.1 recorded lands here. It was committed on that
  release's branch but the squash merge did not carry it, so 0.9.1 shipped
  with the stuck badge URL its entry claimed to have fixed.
- Both READMEs carry the name-forms table — which casing the name takes in the
  distribution and CLI, in imports, in prose, in environment variables, and in
  the error base class — under `## Development`, beside the commands it
  applies to.

## 0.9.1 - 2026-08-10

Documentation only; no functional change. PyPI renders the description that
shipped with each release, so the rewritten README reaches the project page
only through a new version.

- Restructured both READMEs. One sentence now says what Iiwi does, and the
  hundred-line quick start is split into Quick start, The interactive menu,
  and Commands, with the report flags as a table. English drops from 236 to
  170 lines, zh-TW from 208 to 161.
- The zh-TW README documents `history`, `update`, `run`, JSON output, the `p`
  and `e` keys, and the security policy, which it was missing.
- The architecture diagram moves to `docs/architecture.md`; its nodes are
  internal class names that mean nothing to someone installing the tool.
- A banner replaces the overview screenshot at the top of both READMEs, and
  `docs/assets/social-preview.jpg` is the 1280x640 crop GitHub wants.
- The PyPI badge dropped its legacy `.svg` suffix. shields.io cached a 404
  from the window between the rename and the first `iiwi` upload, and both it
  and GitHub's camo proxy key that cache on the exact URL.
- `uv run iiwi` is documented in Development, with a note on what each command
  in that block is for.

## 0.9.0 - 2026-08-10

- Renamed the project from Agent Worklog to Iiwi. The command is now `iiwi`,
  the distribution is `iiwi` on PyPI, environment variables use the `IIWI_`
  prefix, and settings, history and session-selection state move to the `iiwi`
  application directories. State left by the previous name is adopted
  automatically on first run. There is no compatibility alias — `agent-worklog`
  is not published beyond 0.8.x.
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
