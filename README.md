# Iiwi

**Iiwi** · /ˈiː.wiː/ "ee-wee" — turns your coding-agent sessions into a weekly
engineering report, without anything leaving your machine.

[![CI](https://github.com/mike840609/iiwi/actions/workflows/ci.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/ci.yml)
[![Release](https://github.com/mike840609/iiwi/actions/workflows/release.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/iiwi.svg)](https://pypi.org/project/iiwi/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/iiwi/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/mike840609/iiwi/blob/main/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mike840609/iiwi/pulls)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mike840609/iiwi)

English | [繁體中文](https://github.com/mike840609/iiwi/blob/main/README.zh-TW.md)

![Iiwi — see what your agents did](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/iiwi-banner.jpg)

The weekly status update is work you already did once. Iiwi reads the sessions
your coding agent already recorded, groups them by repository, and writes the
report. Works with OpenCode, Claude Code, and Codex.

- **Nothing leaves your machine.** Your local `opencode run` writes the narrative — no network, no API key.
- **Finds your sessions anywhere.** Every project, whichever folder you run from.
- **Groups by repository.** Worktrees collapse into one entry; child and subagent sessions stay with it.
- **Redacts first.** Common secret patterns are stripped locally before anything is written.

## Quick start

Needs Python 3.11+ and `git`. Plus one harness: OpenCode (the default, needs an
`opencode` executable) or Claude Code / Codex (no CLI, just a readable transcript
store at `~/.claude/projects` or `~/.codex`).

```bash
pipx install iiwi                 # or: pip install iiwi

iiwi doctor                       # is the harness ready?
iiwi report --period last-week    # write the report
```

The report lands under `reports/`.
Pass `--dry-run` to print the report to the terminal instead of writing a file.

## The interactive menu

Run `iiwi` with no arguments if you would rather not remember flags:

```text
$ iiwi
Iiwi
══════════════════════════════════════════════════════
Turn coding-agent sessions into engineering reports

▶ Generate Report
  Browse Sessions
  Check Setup
  Settings

↑↓ jk │ Enter Select │ 1-4 │ ? Help │ q Quit
```

Choosing **Generate a report** shows every setting at once instead of asking one
question at a time — `↑↓` moves, `←→` changes a value, and a line under the list
explains the setting you are on. Press `g` to generate, or `r` to open
**Review sessions** first, which weighs each repository by how much of the period
it actually accounts for:

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

`Space` toggles a repository or a single session, `p` previews a transcript
(redacted), and `e` excludes a repository from every future scan. Your selection
is remembered per period.

## Commands

```bash
iiwi doctor                       # is the harness ready?
iiwi scan --period last-week      # preview how sessions group
iiwi report --period last-week    # write the report
iiwi history                      # reports already written
iiwi update                       # check PyPI for a newer release
iiwi run                          # the same questions, one at a time
```

| Flag | What it does |
|---|---|
| `--harness claude-code` / `--harness codex` | Read another harness's sessions — the narrative still comes from your local `opencode run` |
| `--no-llm` | Deterministic structured report; works whether or not OpenCode is installed |
| `--sanitize` | OpenCode's stronger redaction, which intentionally removes most work evidence |
| `--dry-run` | Print the report instead of writing a file |
| `--json` | Redacted machine-readable output for `scan`, `doctor`, `history`, and `update` (the default when stdout is piped) |

`iiwi --help` lists everything, and `run` is the linear wizard if you prefer being
asked. In scripts, name a subcommand directly — with no terminal to prompt at, the
menu exits with status 3 rather than reading stdin.

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

Everything happens on your machine: sessions are read from disk, common secret
patterns are redacted, and the redacted transcript is handed to your locally
installed `opencode run`. No API key, and `update` is the only command that touches
the network.

Reports may still contain private goals, filenames, commands, and full working
paths — always review one before sharing it. See
[Privacy and security](https://github.com/mike840609/iiwi/blob/main/docs/privacy.md)
for the full data flow and current limits.

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

## License

MIT
