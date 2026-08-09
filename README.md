# Iiwi

[![CI](https://github.com/mike840609/iiwi/actions/workflows/ci.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/ci.yml)
[![Release](https://github.com/mike840609/iiwi/actions/workflows/release.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/iiwi.svg)](https://pypi.org/project/iiwi/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/iiwi/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/mike840609/iiwi/blob/main/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mike840609/iiwi/pulls)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mike840609/iiwi)

English | [繁體中文](https://github.com/mike840609/iiwi/blob/main/README.zh-TW.md)

**Iiwi** *(ee-EE-wee)* — Agent Session Intelligence for engineering work.

**Probe coding-agent sessions. Surface the work that matters.**

Iiwi reads coding-agent sessions from OpenCode, Claude Code, and Codex, groups the work by Git repository, selects and redacts useful evidence, and turns it into engineering reports.

![Agent sessions are grouped into weekly engineering reports](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/iiwi-overview.png)

## Why

- **Nothing leaves your machine.** The narrative review is written by your locally
  installed `opencode run` — no network request, no API key.
- **Finds your sessions wherever they are.** All projects, no matter which folder you
  run from.
- **Groups by repository.** Git worktrees of the same repository collapse into one
  entry, with child and subagent sessions kept alongside it.
- **Redacts before it writes.** Session content is checked for common secret patterns
  locally, before any report or narrative call.

Supports OpenCode, Claude Code, and Codex.

## Requirements

- Python 3.11 or newer.
- Git available as `git`.
- One coding-agent harness: OpenCode (default), Claude Code, or Codex. OpenCode needs
  an `opencode` executable; Claude Code and Codex need no CLI, only a readable
  transcript store (`~/.claude/projects` or `~/.codex`).

## Install

```bash
pipx install iiwi
```

Or `pip install iiwi` in a regular Python environment.

## Quick start

Run it with no arguments for the terminal-native menu:

```text
$ iiwi
Iiwi
══════════════════════════════════════════════════════
Probe coding-agent sessions. Surface the work that matters.

▶ Generate Report
  Browse Sessions
  Check Setup
  Settings

↑↓ jk │ Enter Select │ 1-4 │ ? Help │ q Quit
```

Choosing Generate a report opens the settings first, so you can change only what matters
before scanning — the cursor sits on the value it changes. **Generate report** sits below
them, or press `g`; a line under the list says what the setting you are on actually does.
`r` opens **Review sessions**, which groups the scan by repository; press `Space` on a
repository to toggle the whole group, or expand it and toggle individual sessions.

```text
Generate Report
══════════════════════════════════════════════════════

  Harness      OpenCode
  Period       Aug 03 – Aug 10
▶ Detail       Full
  Subagents    Included
  Narrative    Enabled
  Sanitize     Off
  Dry run      Off

  Generate report

Full keeps every section. Brief drops files, sessions and usage.

↑↓ jk │ ←→ hl Change │ Enter Select │ r Review │ g Generate │ ? Help │ b Back
```

Review Sessions weighs each repository by how much of the period it actually accounts for,
so the biggest contributors are visible without opening anything:

```text
Review Sessions   6 / 6 selected │ 252 / 252 msgs
══════════════════════════════════════════════════════
Select sessions to include in the report:

  1. ▾ ████████████  71% ● iiwi   3 / 3    Aug 5 │ 180 msgs
▶      ████░░░░░░░░  24% ● Add the interactive menu Aug 5 │ 60 msgs
       ████░░░░░░░░  24% ● Redact before writing    Aug 5 │ 60 msgs
       ████░░░░░░░░  24% ● Group worktrees          Aug 5 │ 60 msgs
  2. ▸ ████░░░░░░░░  24% ● obsidian-wiki   2 / 2    Aug 4 │ 60 msgs
  3. ▸ █░░░░░░░░░░░   5% ● dotfiles   1 / 1         Aug 3 │ 12 msgs

↑↓ jk │ ←→ hl │ Space Toggle │ p Preview │ e Exclude │ a All │ g Generate │ / Search │ ? Help │ b Back
```

Press `p` on a session row to scroll its transcript inline — redacted before
it is drawn, so the preview never shows more than the report itself would.
Your selection is remembered per period: a rescan (or a changed setting that
rescans) restores what you unselected, and sessions that no longer exist are
dropped automatically. Press `e` on a repository row to exclude it from every
future scan — the repository is appended to `report.exclude_repositories`, the
same persistent setting `config set` writes, and the review rescans so the
repository disappears immediately. Undo with
`iiwi config unset report.exclude_repositories`.

Or drive the commands directly:

```bash
iiwi doctor                       # is the harness ready?
iiwi scan --period last-week      # preview how sessions group
iiwi report --period last-week    # write the report
iiwi history                      # list the reports already written
iiwi update                       # check PyPI for a newer release
```

`scan`, `doctor`, `history`, and `update` emit JSON when stdout is piped, or
when asked with `--json` — `iiwi scan --period last-week | jq
'.repositories'` works out of the box, and every value is redacted before it is
emitted. `--no-json` forces the human output, and `history --json` returns the
recorded reports as an array.

The report defaults to a narrative weekly review written by your local `opencode run`.
Add `--no-llm` for the deterministic structured report, which works for every harness
whether or not OpenCode is installed:

```bash
iiwi report --period last-week --no-llm
```

Output lands under `reports/`. For another harness, add `--harness claude-code` or
`--harness codex` — the narrative default behaves the same for all of them, reading
that harness's sessions and still calling your local `opencode run`.

Prefer to be asked instead of remembering flags? The `run` command keeps the linear
wizard and previews the scan before writing:

```bash
iiwi run
```

Pass `--dry-run` to print the report to the terminal instead of writing a file.

Use `iiwi --help` for the command list. In scripts, name a subcommand
directly — with no terminal to prompt at, the menu exits with status 3 rather than
reading from stdin.

## Documentation

| Page | What's in it |
|---|---|
| [CLI reference](https://github.com/mike840609/iiwi/blob/main/docs/cli-reference.md) | Every command, option, and exit code |
| [Configuration](https://github.com/mike840609/iiwi/blob/main/docs/configuration.md) | Settings file, environment variables, precedence |
| [Privacy and security](https://github.com/mike840609/iiwi/blob/main/docs/privacy.md) | Data flow, redaction boundary, what reports still contain |
| [Security policy](https://github.com/mike840609/iiwi/blob/main/SECURITY.md) | Threat model and how to report a vulnerability |
| [Usage guides](https://github.com/mike840609/iiwi/blob/main/docs/guides.md) | Reporting periods, subagents, repository grouping, output handling |
| [Usage statistics](https://github.com/mike840609/iiwi/blob/main/docs/usage-statistics.md) | How the usage section is built, and its window caveat |
| [Support and limits](https://github.com/mike840609/iiwi/blob/main/docs/limitations.md) | The per-harness caveat list |
| [Releasing](https://github.com/mike840609/iiwi/blob/main/docs/releasing.md) | How a release is cut |

## Privacy

OpenCode exports are raw by default so reports retain useful work details. Iiwi
redacts common secret patterns locally, then hands a grouped, redacted transcript to
your locally installed `opencode run`, which writes the narrative — nothing leaves your
machine and no API key is needed. The only command that touches the network is
`update`, which checks PyPI for a newer release when you run it. Use `--no-llm` for the
deterministic structured report, or `--sanitize` for OpenCode's stronger redaction,
which intentionally removes most work evidence.

Reports may still contain private goals, filenames, commands, and full working paths.
Always review a report before sharing it. See
[Privacy and security](https://github.com/mike840609/iiwi/blob/main/docs/privacy.md)
for the full data-flow details and current limits.

## Configuration

Settings come from an environment variable first, then the settings file, then the
default. `config init` walks through every setting; `config set` writes one:

```bash
iiwi config init                                          # walk through all
iiwi config set harnesses.opencode.cli.model deepseek-r1  # write one
iiwi config list                                          # show all, with sources
iiwi config unset report.timezone                         # back to the default
```

See the
[configuration guide](https://github.com/mike840609/iiwi/blob/main/docs/configuration.md)
for the complete list of settings and their environment-variable names.

## Architecture

<!-- Rendered image, not a mermaid block: the GitHub mobile app and PyPI show
     mermaid source as plain text. Edit docs/assets/architecture.mmd and follow
     the regenerate command at the top of that file. -->

![Architecture: CLI reads one of three session sources, scans and resolves repositories, then extracts, redacts, summarizes, and writes the report](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/architecture.svg)

Iiwi runs one of three sources per harness, loads only the sessions that overlap
the requested period, groups them by repository, redacts and summarizes the evidence, and
writes the Markdown report atomically with owner-only permissions.

## Development

```bash
git clone https://github.com/mike840609/iiwi.git
cd iiwi
uv sync --locked --extra dev

uv run pytest --cov=iiwi --cov-fail-under=80
uv run ruff check .
uv run pyright
```

## License

MIT
