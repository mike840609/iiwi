# Privacy and security

Iiwi is local-first, but coding-agent transcripts are sensitive inputs. This
document defines what the MVP protects and what remains the operator's responsibility.

## Data flow

With `--harness opencode`:

1. Iiwi queries candidate session metadata with `opencode db`.
2. It requests each transcript with `opencode export <session-id> --sanitize`.

With `--harness claude-code`:

1. Iiwi lists the JSONL transcript files under the configured
   `projects_directory` (default `~/.claude/projects`), including subagent transcripts
   unless `--root-only` is used.
2. It reads each file directly from disk. There is no harness-side export or sanitize
   step here: Claude Code provides no export command, so the raw JSONL — with whatever
   tool output, file contents, environment values, and hook output Claude Code wrote to
   it — is read into memory before the mapper described in "Claude Code has no sanitize
   step" below runs.

With `--harness codex`:

1. Iiwi finds the newest `state_<n>.sqlite` under the configured
   `home_directory` (default `~/.codex`) and queries it for threads whose activity
   overlaps the period, or, when that database is absent or its schema cannot be read,
   scans the `sessions/` and `archived_sessions/` rollout files under the same directory
   instead.
2. It reads each session's rollout JSONL file directly from disk. Codex provides no
   export command either, so the raw JSONL — with whatever tool output, file contents,
   and free-form status text Codex wrote to it — is read into memory before the mapper
   described in "Codex has no sanitize step" below runs.

All three harnesses then continue:

3. Transcript data is parsed in memory and filtered to the requested activity range.
4. Structured evidence is recursively redacted.
5. `report` builds a usage section: for OpenCode, by requesting aggregate counters with
   `opencode stats` over a trailing window that contains the report period; for Claude
   Code and Codex, from token counters already attached to each mapped activity, which
   cover the report period rather than a window ending now. Either way the usage output
   holds model, token, and tool totals rather than session content, and it is redacted
   before it reaches the report.
6. The redacted evidence is rendered to the structured report, or grouped into a
   redacted raw transcript for the locally installed narration CLI to narrate.
7. Markdown is written with an atomic replacement and owner-only `0600` permissions on
   POSIX systems.

Iiwi does not persist raw OpenCode exports or raw Claude Code or Codex
transcripts beyond the in-memory read above. The secure writer may create a short-lived
sibling file during atomic report replacement; it is removed after completion or failure.

## Redaction boundary

The redactor covers common patterns including:

- bearer and basic authorization values;
- OpenAI-style provider keys;
- GitHub tokens;
- AWS access keys and secret assignments;
- password, token, secret, and API-key assignments, including prefixed env-style names
  such as `DB_PASSWORD=` and `OPENAI_API_KEY=`;
- `pwd=` connection-string passwords, but not `pwd:` shell output;
- Slack, Stripe, Google, and npm tokens recognised by their fixed prefixes;
- credentials embedded in URLs and `curl -u` arguments;
- JWT-like tokens, detected only when both segments carry the `eyJ` JSON header marker;
- private-key blocks.

Redaction is applied recursively to evidence metadata, to OpenCode, Claude Code, and Codex
usage output, before rendering, before verbose warnings are written to reports, and before
the narration CLI invocation. For Claude Code and Codex, redaction runs after the
mapper minimization described below, on the fields that minimization leaves behind.

Pattern-based redaction is not a proof that every secret has been removed. New credential
formats, arbitrary customer identifiers, source code, internal hostnames, filenames,
working-directory paths, session titles, and business-sensitive descriptions may remain.

## OpenCode sanitization

Every OpenCode transcript request includes `--sanitize`. This is a defense-in-depth input
boundary, not a replacement for Iiwi redaction. A command fails the acceptance
suite if an OpenCode export is invoked without that flag.

## Claude Code has no sanitize step

Claude Code has no export command at all, so there is nothing equivalent to `opencode
export --sanitize` for Iiwi to request. With `--harness claude-code`, Iiwi reads
`~/.claude/projects/**/*.jsonl` directly, and those files contain full tool output,
whole file contents, environment dumps, and hook output exactly as Claude Code wrote
them to disk.

What replaces the missing sanitize step is not a scrub of that file on disk — it is that
the JSONL mapper deliberately keeps only a narrow slice of each record before anything
else in Iiwi sees it:

- human prompts (tool results, hook injections, and system reminders that Claude Code
  also writes as `type: "user"` records are excluded, so they are never mistaken for
  human intent);
- assistant message text;
- tool names;
- one command or file path per tool call, when the call carries one.

Not every tool call has a `command`, `file_path`, `path`, or `notebook_path` field.
WebFetch's `url`, WebSearch's `query`, Task's `description`/`prompt`/`subagent_type`,
TodoWrite's whole `todos` list, a path-less Glob call, and MCP tool calls in general all
fall outside that set. For those, the mapper falls back to serializing the tool's entire
input object to JSON and truncating it to 200 characters, so what the mapper keeps is not
one command or path but as much of the full call as fits in that budget.

Everything else is dropped at that boundary and never reaches a report or the narration
CLI's transcript:
tool `stdout` and `stderr`, model thinking blocks, hook output, and system reminders. The
only trace a tool result leaves behind is two derived booleans — whether its `stderr` was
empty, and whether the call was interrupted. That is also why a Claude Code report never
states that a verification command passed: with no exit code and no captured output, the
report records only that the command ran, under "In Progress".

The same pattern-based secret checks described above still run on top of that reduced set
of fields, exactly as they do for OpenCode evidence.

This is a description of a deliberate design choice about what Iiwi retains, not
a guarantee about what Claude Code itself writes to disk, and not a claim that the
retained fields are free of secrets — a command, file path, or a truncated serialized
tool input can itself contain a credential, and pattern checks cannot find every possible
secret. Reports built from Claude Code sessions may still contain prompts, commands, file
paths, and full working-directory paths, exactly as reports built from OpenCode sessions
do.

## Codex has no sanitize step

Codex has no export command either, so `--harness codex` reads the rollout JSONL files
directly, and those files contain full tool output, whole file contents, and free-form
status text exactly as Codex wrote them to disk.

What replaces the missing sanitize step is the same kind of boundary as Claude Code's: the
rollout mapper deliberately keeps only a narrow slice of each record before anything else
in Iiwi sees it — user and assistant messages, tool names, and one field per
record type:

- `exec_command`'s `cmd` argument, the one Codex tool whose arguments name a command;
- `patch_apply_end`'s changed file paths, never the change value itself, which holds
  either a unified diff (`unified_diff`, the majority case, for an update to an existing
  file) or the whole file (`content`, for a new file);
- nothing at all for `exec`, whose input is an arbitrary JavaScript program rather than a
  command, and for every other tool call, which is recorded with empty content so its
  token usage is still attributable to an activity.

Two kinds of content are therefore dropped in the mapper rather than downstream: the
change value of every `patch_apply_end` entry — whichever of `unified_diff` or `content`
it carries — and the input of every `exec` call. Only the changed file's path and the
tool's name survive for those two record types. A rename's destination path lives in
`move_path`, inside that same discarded value, so it never reaches Key Files either.

Everything else is dropped at that boundary and never reaches a report or the narration
CLI's transcript:
tool `stdout` and `stderr`, and Codex's free-form status text. Codex records exit codes
only inside that free-form text, in several formats, so Iiwi does not parse it —
the mapper stores no `exit_code` and no `stderr_empty` for a Codex command, which is why no
Codex report claims a command passed or failed. The one structured outcome signal Codex
does provide is `patch_apply_end`'s `success` flag, used to decide whether a patch's paths
are worth reporting at all — and even then it reports a file change, not a verification
result.

The same pattern-based secret checks described above still run on top of that reduced set
of fields, exactly as they do for OpenCode and Claude Code evidence.

This is a description of a deliberate design choice about what Iiwi retains, not
a guarantee about what Codex itself writes to disk, and not a claim that the retained
fields are free of secrets. Reports built from Codex sessions may still contain prompts,
commands, file paths, and full working-directory paths, exactly as reports built from the
other two harnesses do.

## The 300-character evidence budget

The mapper alone does not bound how much text a single retained field can hold. A Bash
`input.command` is kept whole, and a heredoc puts the entire body of the file it writes
inside that one command string — as far as length goes, `cat > design.md <<'EOF' … EOF` or
`gh pr create --body-file - <<'EOF' … EOF` is a file, not a command. The 200-character
truncation described above applies only to the JSON fallback, which is the rare path.

The bound that does apply to a report is in the extraction layer, and it covers all three
harnesses: **every evidence item's text is capped at 300 characters**
(`EVIDENCE_TEXT_MAX_LENGTH` in `extraction/pipeline.py`), with a trailing `…` marking the
cut so a reader can tell that text was removed. 300 characters identify any real command
while refusing to carry a file, a diff, or a write-up. Nothing longer than that reaches
the rendered Markdown, the report's provenance lists, or the narration CLI
invocation.

Redaction cannot substitute for this cap, which is why the cap exists. A pasted design
document, an incident write-up, or a block of source code contains no credential pattern,
so `redact_text` passes it through untouched; only a length budget removes it.

One neighbouring fallback is closed for the same reason. A file tool call that carries no
path key at all would otherwise have its serialized input treated as a file path and
listed under "Key Files", which for a `Write`-shaped call means the beginning of the
file's own `content`. Text that does not look like a single path is refused instead, so
such a call contributes no "Key File" entry rather than an entry made of file contents.

## Narrative report data

The report invokes a local narration CLI subprocess — `opencode`, `claude`, or
`codex`, resolved as described under [Narrator](configuration.md#narrator). The
payload is a grouped, redacted raw transcript plus a summarization prompt. It
contains session content that the structured evidence pipeline also sees: session
titles and absolute working directories, goals, commands, and filenames. They are
redacted for secrets like every other field, but redaction does not remove what a
path identifies. A directory such as `/Users/<operator>/work/<client>/service`
still names the operator and often a client or employer.

The transcript is a temporary file that is removed after the invocation, and the
prose returns to the same process. Use `--no-llm` to produce the deterministic
structured report without invoking a narration CLI at all.

## The session cache

Iiwi stores each normalized session in a SQLite database so a repeat run does not
re-export sessions that have not changed. This is a real change in where your data
rests: content that previously existed only for the duration of a run is now written
to disk.

- **Location.** `sessions.db` in the platform cache directory — `~/Library/Caches/iiwi`
  on macOS, `$XDG_CACHE_HOME/iiwi` (usually `~/.cache/iiwi`) on Linux. `IIWI_CACHE_FILE`
  overrides it.
- **Permissions.** The file is created mode `0600` inside a `0700` directory, the same
  as every other file iiwi writes.
- **Contents.** The normalized session, *before* the redaction that runs when a report is
  written. Redaction happens on the way into a report, not on the way into the cache, so
  the cache holds the same unredacted material the harness handed over — the same
  material already sitting in `~/.claude/projects`, the OpenCode store, or `~/.codex`.
  With `--sanitize`, OpenCode's redacted export is what gets stored; sanitized and raw
  payloads are kept under separate keys and are never served across that boundary.
- **Turning it off.** Set `IIWI_CACHE__ENABLED=false` (or `cache.enabled` in the settings
  file). Every run then exports every session and writes nothing to disk.
- **Clearing it.** Delete the file. Nothing depends on it; the next run rebuilds what it
  needs.

## Reports remain sensitive

A generated report can still reveal proprietary information, including:

- project and repository names;
- user goals and feature descriptions;
- commands and test names;
- filenames and branch names;
- absolute working-directory paths, printed verbatim per repository;
- session titles, which are free text written during the session;
- aggregate model, token, and tool usage counters;
- errors and unresolved work;
- the fact that particular repositories were active.

Working-directory paths deserve separate attention. Redaction targets credential patterns
and deliberately leaves paths intact, so a report can state where work happened. On a
typical machine those paths carry the operator's username and often a client or employer
name, for example `/Users/<operator>/work/<client>/service`.

Treat reports as internal engineering records. Review them before posting to chat systems,
issue trackers, shared drives, or public repositories.

## Logs and partial failures

The CLI does not intentionally print raw transcripts, environment values, authorization
headers, or credentials embedded in remotes. Partial export or transcript-read failures
are reported using session IDs and redacted error text.

## Operator responsibilities

- Keep the OpenCode storage (or, for Claude Code, `~/.claude/projects`; or, for Codex,
  `~/.codex`) and generated reports protected by appropriate filesystem permissions.
- Review generated content before distribution.
- Rotate any credential that appears unredacted and report the pattern so the redactor can
  be extended.

## OpenCode raw export default

OpenCode sessions are loaded with raw `opencode export` by default. The complete
JSON stays in subprocess stdout and Python memory; Iiwi does not persist or
log it. Extracted evidence still passes through the local redactor before rendering
or before it reaches the narration CLI invocation.

The resolved narration CLI is invoked with the redacted grouped transcript; it runs
locally with the user's own model configuration, and no API key is read. `--sanitize`
asks OpenCode to remove session text and tool data, producing a deliberately limited
narrative.
`--dry-run` prints report content to stdout, so terminal history, CI logs, and shell
redirection must be treated as sensitive outputs.
