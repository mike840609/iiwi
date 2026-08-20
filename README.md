# Iiwi

**Iiwi** · /ˈiː.wiː/ "ee-wee"

**Turn your AI coding work into clear engineering reports.**

[![CI](https://github.com/mike840609/iiwi/actions/workflows/ci.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/ci.yml)
[![Release](https://github.com/mike840609/iiwi/actions/workflows/release.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/iiwi)](https://pypi.org/project/iiwi/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/iiwi/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/mike840609/iiwi/blob/main/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mike840609/iiwi/pulls)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mike840609/iiwi)

English | [繁體中文](https://github.com/mike840609/iiwi/blob/main/README.zh-TW.md)

![Iiwi — see what your agents did](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/iiwi-banner.jpg)

You already did the work. Iiwi turns the history left by your coding agents into
an update you can review and share.

Iiwi works with OpenCode, Claude Code, and Codex. It finds what you worked on,
keeps related work together, and turns it into a Markdown report without making
you reread old agent conversations.

- **Works across projects.** Iiwi finds your coding-agent sessions wherever you worked.
- **Keeps related work together.** Sessions are grouped by repository.
- **You stay in control.** Choose and edit what belongs in the final report.
- **Protects sensitive information.** Common secret patterns are removed before reports are written.

## How it works

1. **Read** — Iiwi finds local AI coding history from OpenCode, Claude Code, or Codex.
2. **Review** — Keep, edit, reorder, or remove the work that matters.
3. **Generate** — Create a Markdown report you can share with your team.

## What you get

A reviewed report can look like this:

```markdown
# Weekly engineering update

## My Project
- Simplified the report workflow and made review easier to use.
- Added Claude Code and Codex session support.
- Fixed documentation checks in CI.

## Blockers
- None
```

## Quick start

Requires Python 3.11+ and `git`.

```bash
pipx install iiwi                 # or: pip install iiwi

iiwi doctor                      # check that Iiwi can read your setup
iiwi                             # open the interactive menu
```

From the menu, choose what you want to do and Iiwi walks you through the rest.

Two useful shortcuts:

```bash
iiwi daily                       # prepare today's standup update
iiwi report --period last-week   # prepare last week's report
```

Reports are saved under `reports/` by default.

## Use the interactive menu

Run `iiwi` with no arguments when you do not want to remember commands or flags.

The menu lets you review recent work, prepare a standup, generate reports, check past
reports, verify your setup, and change settings.

When generating a report, Iiwi shows the work it found first. Pick what belongs, edit
anything you want to change, and Iiwi writes the Markdown report.

For the full review workflow and keyboard controls, see the
[Quick Review guide](docs/evidence-first-quick-review.md). For the daily flow, see the
[Daily Standup guide](docs/daily-standup.md).

## Use the CLI directly

The interactive menu is the easiest place to start. If you prefer commands, these cover
the most common cases:

```bash
iiwi doctor                       # check your setup
iiwi daily                        # prepare a daily standup
iiwi report --period last-week    # generate last week's report
```

Run `iiwi --help` for the rest, or see the
[CLI reference](docs/cli-reference.md) for every command, flag, example, and exit code.

## Configuration

You can start using Iiwi without changing any settings.

If you want to change things such as the model, timezone, paths, or defaults, use:

```bash
iiwi config init                  # walk through the settings
iiwi config list                  # see the settings currently in use
```

See the [configuration guide](docs/configuration.md) for all available settings and
advanced setup.

## Privacy

Iiwi reads and processes your session history on your machine. If you use AI drafting,
Iiwi redacts common secret patterns before passing the text to the CLI you configured for
drafting. What that CLI does next depends on its own configuration.

Reports can still contain private goals, filenames, commands, and working paths, so review
a report before sharing it.

See [Privacy and security](docs/privacy.md) for the full data flow, redaction behavior,
and current limits.

## Documentation

Most day-to-day details live in the guides below instead of this README:

- [CLI reference](docs/cli-reference.md) — commands, flags, examples, and exit codes
- [Quick Review guide](docs/evidence-first-quick-review.md) — review controls and report flow
- [Daily Standup](docs/daily-standup.md) — Yesterday / Today / Blockers workflow
- [Configuration](docs/configuration.md) — settings, models, paths, and environment variables
- [Privacy and security](docs/privacy.md) — what stays local and what reports can contain
- [Support and limits](docs/limitations.md) — current harness-specific limits

For contributors and deeper technical details, see
[Architecture](docs/architecture.md), [Security policy](SECURITY.md), and the rest of the
[`docs/`](docs/) directory.

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
