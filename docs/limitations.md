# Current support and limits

The README summarizes the supported tools and the key caveats. This page lists them in
full, including the ones that apply only to a specific harness.

## General

- OpenCode, Claude Code, and Codex are the supported coding-agent tools; select one with
  `--harness`.
- For `--harness opencode`, Iiwi gets session data through the OpenCode
  command-line tool. It does not read the SQLite database directly.
- Markdown is the only report format.
- Iiwi does not keep a cache between runs and does not provide an `inspect`
  command.
- Repository grouping uses the Git information available when the report is created.
- Older OpenCode sessions may use a backup ID if their working folders have been deleted.
- Sessions iiwi's own `opencode run` creates are excluded from every scan, so
  they are absent from outcomes, session lists, and counts — except the Usage
  section, an external `opencode stats` aggregate the scan cannot filter.

## Usage statistics

- The usage window caveat applies to OpenCode only: `opencode stats` covers a period
  that ends when the report is created, so it is wider than the report period. Claude
  Code and Codex usage is built from the sessions themselves, so it covers the report
  period, to within a single model turn at each end of it.
- Codex usage counts each API request's full input, which is what Codex itself reports.
  It is not a count of distinct tokens.

## Claude Code

- Claude Code sessions have no exit codes, so no Claude Code report claims that a test or
  lint command passed or failed. A verification command whose stderr was empty is listed
  under "In Progress" as `Ran verification command: <command>`, and a command that
  redirects its stderr (`2>`, `&>`, `|&`) produces no outcome at all, because for those
  commands an empty stderr says nothing. Non-empty stderr is not treated as failure
  either — Git writes to stderr on success. Verification results are reported as passing
  only for OpenCode, where a real exit code is available. Codex sets neither an exit code
  nor this stderr signal, so it never reaches that heuristic either.
- A Claude Code session that spans several working directories is grouped under the
  last one.

## Codex

- A Codex report shows goals, changed files, and token usage. It does not list commands.
  A command recorded through `exec_command` reaches the narrative `opencode run` summary
  and nothing else; with `--no-llm` it is not in the report at all.
- Commands run from inside Codex's `exec` tool are not recorded even that far. `exec`
  takes a JavaScript program rather than a command, so there is no command to record.
- No Codex report claims that a command passed or failed. Codex records exit codes only
  inside free-form tool output, in several formats, so only `patch_apply_end`'s structured
  `success` flag is trusted — and it reports a file change, not a verification result.
- When there is no readable Codex state database and Iiwi falls back to scanning
  rollout files, session titles are lost: rollout files carry an `agent_nickname` but never
  a `title`, which lives only in the state database.
- A Codex message sent with attachments — a browser context, mentioned files, a shell
  command and its output, a slash command, a background-task notice, or a resume summary —
  contributes no goal. Iiwi cannot tell a genuine request apart from the rest of
  that envelope without parsing an undocumented format, and it would rather lose the goal
  than mis-attribute one.

## OpenCode sanitized reports

OpenCode's `--sanitize` replaces conversation text, tool input and output, paths, and
patches with redaction placeholders. Iiwi cannot restore that content. It
filters placeholders and keeps available database metadata, repository grouping,
session counts, and usage statistics, but detailed goals and outcomes are unavailable.
