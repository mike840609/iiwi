# Security

Agent Worklog turns coding-agent session transcripts into engineering reports,
so its threat model is about transcript data — what is read, what is written,
and what leaves the machine. The guiding principle is:

> **Nothing leaves your machine.** The narrative review is written by your
> locally installed `opencode run` — no network request, no API key.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability. Report it privately to
the maintainers via GitHub's private vulnerability reporting at
<https://github.com/mike840609/agent-worklog/security/advisories>, or by
contacting the maintainers directly. We aim to acknowledge reports within 3
business days.

## Data flow and boundaries

- **Inputs**: session transcripts are read only from your local harness stores
  (`~/.claude/projects`, `~/.codex`, or the OpenCode CLI's export), filtered to
  the requested period, and grouped by Git repository.
- **Redaction**: session content is checked for common secret patterns
  (`sk-...`, API-key shapes, credentials) **before** any report, narrative
  call, or JSON output is produced. The interactive session preview redacts
  the same way.
- **Narrative**: the prose review is produced by your locally installed
  `opencode run` from the redacted, grouped transcript. No cloud call.
- **Writes**: the report file is written atomically with owner-only
  permissions. The report history log (`~/.local/share/agent-worklog/` or the
  platform data dir) is append-only and holds only metadata — no transcript
  content.

## What reports still contain

Redaction removes secret-shaped strings, not work evidence. A report may still
include private goals, filenames, commands, and full working paths. **Always
review a report before sharing it.** For stronger redaction, `--sanitize`
(OpenCode only) intentionally removes most work evidence at export time.

See [Privacy and security](docs/privacy.md) for the full data-flow details and
current per-harness limits.

## Safer defaults

- `--dry-run` prints the report instead of writing a file.
- Reports refuse to overwrite an existing file unless `--force` is given.
- `--no-llm` produces the deterministic structured report without invoking
  `opencode`.
- Every harness can be switched off in configuration, which makes commands
  fail rather than read that harness's store.
