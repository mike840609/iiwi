# Usage guides

Deep dives for the topics the README only summarizes. For every command, option,
and exit code, see the [CLI reference](cli-reference.md).

## Reporting periods

The `last-week` period means the previous full calendar week in the configured time
zone. It starts on Monday at 00:00 and ends just before the next Monday at 00:00.

```bash
iiwi report --period last-week
```

Use `--days` to report activity from a number of recent days:

```bash
iiwi report --days 7
```

Use ISO timestamps to set exact start and end times:

```bash
iiwi report \
  --since 2026-07-20T00:00:00+08:00 \
  --until 2026-07-27T00:00:00+08:00
```

You must provide one of `--period`, `--days`, or `--since`. If you use `--until`, you
must also use `--since`.

## Subagent sessions

Subagent sessions are included by default. Each one is linked to the repository it actually
ran in, so a subagent that worked in another checkout appears under that repository. To
report only root sessions:

```bash
iiwi report --period last-week --root-only
```

Both `scan` and `report` accept `--root-only`.

## Repository grouping

Iiwi checks each session separately to decide which repository it belongs to.
It uses the following information in order:

1. The Git `origin` remote.
2. An ID created from a hash of the shared Git directory.
3. The harness project ID — OpenCode's project ID, or the per-project directory name
   Claude Code stores transcripts under.
4. An ID created from a hash of the working directory.
5. A separate unknown ID for the session.

SSH and HTTPS addresses for the same repository are treated as the same repository.
Different branches are also grouped together. If a child session works in another
repository, it stays linked to that repository.

## Narrative report

`report` defaults to a narrative weekly review written by a narration CLI —
`opencode`, `claude`, or `codex`, resolved from the harness you read sessions from
unless `narrator.provider` overrides it (see
[Narrator](configuration.md#narrator)). Iiwi builds a grouped, redacted raw
transcript from the session content and passes it to that locally launched CLI with a
summarization prompt; the prose comes back and is wrapped under the standard report
header.

Iiwi itself does not read a model API key or make a model API request. The narration CLI
is a separate program, however, and may use its own credentials, provider, and network
connection according to that CLI's configuration. See [Privacy and security](privacy.md)
for the full data boundary.

```bash
iiwi report --period last-week
```

If the narration CLI is missing, times out, or produces no output, Iiwi
falls back to the deterministic structured report and records a warning. Use
`--no-llm` to always take the structured path:

```bash
iiwi report --period last-week --no-llm
```

The narrative carries the same per-session redaction the structured report does,
but it is not metadata-only: it includes goals, filenames, commands, and working
paths where they appear in the transcript.

## Output and file handling

Set the output file with `--output`:

```bash
iiwi report \
  --period last-week \
  --no-llm \
  --output weekly.md
```

Iiwi does not replace an existing file unless you use `--force`:

```bash
iiwi report --period last-week --output weekly.md --force
```

Use `--dry-run` to preview the Markdown without writing a file:

```bash
iiwi report --period last-week --no-llm --dry-run
```

Use `--verbose` to show export and narrative fallback warnings. Use `--quiet` to show only the
output path after a successful report.

## OpenCode privacy modes

`iiwi report --days 7` runs the resolved narration CLI over a raw OpenCode export
transcript. Add `--sanitize` to ask OpenCode to redact the export; the narrative still
runs, but the transcript loses most work details. Add `--no-llm` to produce the
deterministic structured report instead.
