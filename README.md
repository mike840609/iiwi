# Iiwi

**Iiwi** · /ˈiː.wiː/ "ee-wee"

**Turn your coding-agent sessions into clear engineering reports.**

[![CI](https://github.com/mike840609/iiwi/actions/workflows/ci.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/ci.yml)
[![Release](https://github.com/mike840609/iiwi/actions/workflows/release.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/iiwi)](https://pypi.org/project/iiwi/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/iiwi/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/mike840609/iiwi/blob/main/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mike840609/iiwi/pulls)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mike840609/iiwi)

English | [繁體中文](https://github.com/mike840609/iiwi/blob/main/README.zh-TW.md)

![Iiwi — see what your agents did](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/iiwi-banner.jpg)

You already did the work. Iiwi helps turn it into an update.

Iiwi reads the sessions recorded by OpenCode, Claude Code, and Codex, finds what
you worked on, and turns it into a draft report. Review what matters, make a few
edits, and generate a Markdown report you can share with your team.

- **Works across projects.** Iiwi finds your coding-agent sessions wherever you worked.
- **Keeps related work together.** Sessions are grouped by repository.
- **You review before sharing.** Choose what matters and edit the result before generating the report.
- **Protects sensitive information.** Common secret patterns are removed before reports are written.

## Quick start

Requires Python 3.11+ and `git`. Iiwi can read local session history from OpenCode,
Claude Code, or Codex. OpenCode is the default; Claude Code and Codex only need
their local session folders to be readable.

Report drafting uses your locally installed `opencode run`. If it is unavailable,
Iiwi can fall back to a simpler session-based report.

```bash
pipx install iiwi                 # or: pip install iiwi

iiwi doctor                       # check your setup
iiwi daily                        # review yesterday, today, and blockers
iiwi report --period last-week    # write last week's report
```

Reports are written under `reports/` by default. Add `--dry-run` to preview a
report in the terminal without writing a file.

## The interactive menu

Run `iiwi` with no arguments if you would rather use a menu than remember flags:

```text
$ iiwi
 ___ _        _
|_ _(_)_ __ _(_)
 | || \ V  V / |
|___|_|\_/\_/|_|                                v0.9.1
══════════════════════════════════════════════════════
Turn coding-agent sessions into engineering reports
github.com/mike840609/iiwi

▶ Review Activity
  Daily Standup
  Generate Report
  History
  Check Setup
  Settings

↑↓ jk │ Enter Select │ 1-6 │ ? Help │ q Quit
```

**Generate Report** lets you choose the report settings, review the sessions Iiwi
found, and then generate the report. **Review Sessions** shows the work grouped by
repository so you can quickly keep or exclude what belongs in the update:

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

**Daily Standup**, or `iiwi daily`, opens a Yesterday / Today / Blockers review
for recent work. **History** lists reports Iiwi has already written.

Before a report is written, Quick Review lets you keep, edit, reorder, split, or
add work items so the final Markdown reflects what you actually want to share.
For the full keyboard flow, report modes, and recovery behavior, see the
[evidence-first Quick Review guide](https://github.com/mike840609/iiwi/blob/main/docs/evidence-first-quick-review.md).
For Daily Standup details, see the
[Daily Standup guide](https://github.com/mike840609/iiwi/blob/main/docs/daily-standup.md).

## Commands

```bash
iiwi doctor                       # check your setup
iiwi daily                        # review yesterday, today, and blockers
iiwi scan --period last-week      # preview the sessions Iiwi found
iiwi report --period last-week    # write last week's report
iiwi history                      # list reports already written
iiwi update                       # check PyPI for a newer release
iiwi run                          # use the step-by-step wizard
```

| Flag | What it does |
|---|---|
| `--harness claude-code` / `--harness codex` | Read sessions from Claude Code or Codex instead of OpenCode |
| `--no-llm` | Create a structured report without using OpenCode for the narrative |
| `--sanitize` | Use stronger redaction when privacy matters more than report detail |
| `--dry-run` | Print the report instead of writing a file |
| `--json` | Return redacted machine-readable output for supported commands |

`iiwi --help` lists every command and option. Use `iiwi run` if you prefer a
step-by-step wizard; for scripts, call the subcommand you need directly.

## Configuration

Settings come from an environment variable first, then the settings file, then the
default:

```bash
iiwi config init                                          # walk through all
iiwi config set harnesses.opencode.cli.model deepseek-r1  # write one
iiwi config list                                          # show all, with sources
iiwi config unset report.timezone                         # back to the default
```

Every setting and its environment-variable name is in the
[configuration guide](https://github.com/mike840609/iiwi/blob/main/docs/configuration.md).

## Privacy

Session reading, redaction, and report generation stay on your machine. Iiwi
passes the redacted session text to your locally installed `opencode run`; no API
key is required. `iiwi update` is the command that checks the network for a newer
release on PyPI.

Reports can still contain private goals, filenames, commands, and full working
paths, so review a report before sharing it. See
[Privacy and security](https://github.com/mike840609/iiwi/blob/main/docs/privacy.md)
for the full data flow and current limits.

## Documentation

| Page | What's in it |
|---|---|
| [CLI reference](https://github.com/mike840609/iiwi/blob/main/docs/cli-reference.md) | Every command, option, and exit code |
| [Daily Standup](https://github.com/mike840609/iiwi/blob/main/docs/daily-standup.md) | Yesterday/Today/Blockers review, refresh, warnings, and output |
| [Evidence-first Quick Review](https://github.com/mike840609/iiwi/blob/main/docs/evidence-first-quick-review.md) | Outcome review keys, report modes, recovery, and current exclusions |
| [Configuration](https://github.com/mike840609/iiwi/blob/main/docs/configuration.md) | Settings file, environment variables, precedence |
| [Privacy and security](https://github.com/mike840609/iiwi/blob/main/docs/privacy.md) | Data flow, redaction boundary, what reports still contain |
| [Security policy](https://github.com/mike840609/iiwi/blob/main/SECURITY.md) | Threat model and how to report a vulnerability |
| [Usage guides](https://github.com/mike840609/iiwi/blob/main/docs/guides.md) | Reporting periods, subagents, repository grouping, output handling |
| [Usage statistics](https://github.com/mike840609/iiwi/blob/main/docs/usage-statistics.md) | How the usage section is built, and its window caveat |
| [Support and limits](https://github.com/mike840609/iiwi/blob/main/docs/limitations.md) | The per-harness caveat list |
| [Architecture](https://github.com/mike840609/iiwi/blob/main/docs/architecture.md) | How a report is produced, end to end |
| [Releasing](https://github.com/mike840609/iiwi/blob/main/docs/releasing.md) | How a release is cut |

## The name

The ʻiʻiwi is a scarlet Hawaiian honeycreeper whose long curved bill reaches nectar
others cannot — which is what this tool does with the sessions your agent left
behind. Pronounced the anglicised way, "ee-wee".

## Development

```bash
git clone https://github.com/mike840609/iiwi.git
cd iiwi
uv sync --locked --extra dev                    # install the project and its dev tools

uv run iiwi                                     # run your working copy
uv run pytest --cov=iiwi --cov-fail-under=80    # tests, with the coverage gate CI enforces
uv run ruff check .                             # lint
uv run pyright                                  # type check
```

The last three are exactly what CI runs, so a green local run means a green PR.

### Name forms

The name is cased by where it appears:

| Context | Form |
|---|---|
| Distribution, CLI, URLs, application directories | `iiwi` |
| Python package and imports | `iiwi` |
| Prose | `Iiwi` |
| Environment variables | `IIWI_` prefix |
| Error base class | `IiwiError` |

## License

MIT
