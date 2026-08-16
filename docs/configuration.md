# Configuration

Iiwi reads every setting from an environment variable, and reads a settings
file for the ones the environment does not set. For each setting it takes the
environment variable, then the settings file, then the default.

- Prefix: `IIWI_`
- Nested delimiter: `__`
- Boolean values: `true` or `false`

Every setting is optional. Leaving one out — or setting it to an empty value — uses
the default listed in the tables below.

## The settings file

`iiwi config` reads and writes a settings file so that a value survives the
shell it was set in:

```bash
iiwi config path                        # where the file is
iiwi config list                        # every setting, value, and source
iiwi config init                        # walk through every setting
iiwi config set harnesses.opencode.cli.model deepseek-r1   # write one setting
iiwi config set harnesses.opencode.cli.model               # ask for the value
iiwi config set harnesses.opencode.cli.model ""            # empty: back to the default
iiwi config unset harnesses.opencode.cli.model             # same thing, spelled out
```

## Setting values interactively

`iiwi config init` walks through every setting in turn, showing the value in
force in brackets:

```
$ iiwi config init
Settings file: /home/dev/.config/iiwi/config.env
Press Enter to keep the value in brackets. Every setting is optional.
report.timezone [Asia/Taipei]:
llm.model [gpt-5-mini]: gpt-5
Wrote 1 setting to /home/dev/.config/iiwi/config.env
```

Pressing Enter leaves a setting alone; nothing is written for it. Only the settings you
answer are recorded, so a run where you answer nothing writes no file at all. Use
`config unset` to take a setting that is already in the file back to its default —
an empty answer means "leave this as it is", not "erase it".

`iiwi config set <key>` with no value asks for that one setting the same way.
A value the settings would reject is refused and asked again, so a typo partway through
`config init` does not throw away the answers before it.

Both need a terminal. In a pipeline or in CI there is nobody to answer, so they exit
with code 3 rather than reading from stdin; pass the value as an argument there.

The interactive menu's **Settings** entry opens a full-screen editor in the
same style as the rest of the menu: every setting is a row showing its
current value. Choice rows (booleans, the Quick Review report type, and the
harness source) list every option separated by ` / `, with the choice in
force highlighted; `←→` cycles them. Free-text rows (model, paths, numbers,
`exclude_repositories`) open an inline editor on Enter, pre-filled with the
current value — Enter keeps it, an empty value restores the default, Esc
cancels. The timezone row cycles a shortlist of common zones; Enter types
any IANA zone. Values set by an `IIWI_*` environment variable are shown
with an `[environment]` tag and cannot be edited from the file. Every
change is written to the settings file immediately; `config list` reflects
it right away.

Keys are the lowercase, dot-separated form of the variable name, so
`IIWI_HARNESSES__OPENCODE__CLI__MODEL` is `harnesses.opencode.cli.model` and
`IIWI_HARNESSES__OPENCODE__CLI__EXECUTABLE` is
`harnesses.opencode.cli.executable`. `config list` shows every setting's key, its
current value, whether that value came from the environment, the file, or the default,
and what the default is.

The file is a `config.env` in the user configuration directory — run
`iiwi config path` to see the exact location, which differs by platform. Set
`IIWI_CONFIG_FILE` to use a different file — for example a dedicated
`iiwi.env` for one project, not a general project `.env` file, which invites
foreign variables and secrets that have nothing to do with Iiwi into the same
file. The file is created readable and writable only by its owner on macOS and Linux.

`config list` prints every value — including whatever you put in the file — unredacted,
by design: these are your own settings, shown at your own request.

An exported variable always beats the file, so
`IIWI_HARNESSES__OPENCODE__CLI__MODEL=deepseek-r1 iiwi report` still
wins over a file that sets the same key. `config set` and `config unset` say so when
the setting they just touched is already exported.

`config set` refuses an unknown key and a value the settings would reject, so a typo
fails at the moment you make it rather than on the next report. Both exit with code 3.

## OpenCode harness

| Environment variable | Default | Purpose |
|---|---|---|
| `IIWI_HARNESSES__OPENCODE__ENABLED` | `true` | Set to `false` to make `--harness opencode` fail with a configuration error (exit code 3). |
| `IIWI_HARNESSES__OPENCODE__SOURCE` | `cli` | Source identifier; only `cli` is implemented. |
| `IIWI_HARNESSES__OPENCODE__CLI__EXECUTABLE` | `opencode` | OpenCode executable name or path. |
| `IIWI_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS` | `30` | Timeout for OpenCode commands. |

Example:

```bash
export IIWI_HARNESSES__OPENCODE__CLI__EXECUTABLE="$HOME/bin/opencode"
export IIWI_HARNESSES__OPENCODE__CLI__TIMEOUT_SECONDS="60"
iiwi doctor
```

## Claude Code harness

| Environment variable | Default | Purpose |
|---|---|---|
| `IIWI_HARNESSES__CLAUDE_CODE__ENABLED` | `true` | Set to `false` to make `--harness claude-code` fail with a configuration error (exit code 3). |
| `IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY` | `~/.claude/projects` | Directory containing per-project session transcripts. |

Selecting the harness is a CLI concern, not a settings one: pass `--harness claude-code`
to `doctor`, `scan`, or `report`. No executable or CLI timeout setting applies, because
Iiwi reads the JSONL transcripts under `projects_directory` directly and never
launches a Claude Code process.

`ENABLED` is a refusal, not a default: setting it to `false` does not switch the other
harness on, it makes `doctor`, `scan`, and `report` refuse the disabled one. Use it to
forbid reading a transcript store on a machine where that is not permitted.

Example:

```bash
export IIWI_HARNESSES__CLAUDE_CODE__ENABLED="true"
export IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY="$HOME/.claude/projects"
iiwi doctor --harness claude-code
```

## Codex harness

| Environment variable | Default | Purpose |
|---|---|---|
| `IIWI_HARNESSES__CODEX__ENABLED` | `true` | Set to `false` to make `--harness codex` fail with a configuration error (exit code 3). |
| `IIWI_HARNESSES__CODEX__HOME_DIRECTORY` | `~/.codex` | Directory holding the Codex state database and rollout files. |

One setting covers all three locations Iiwi reads — `state_<n>.sqlite`,
`sessions/`, and `archived_sessions/` are fixed positions under it.

Selecting the harness is a CLI concern, not a settings one: pass `--harness codex` to
`doctor`, `scan`, or `report`. No executable or CLI timeout setting applies, because
Iiwi reads the state database or the rollout JSONL files under `home_directory`
directly and never launches a Codex process.

`ENABLED` behaves exactly as it does for Claude Code: setting it to `false` does not
switch another harness on, it makes `doctor`, `scan`, and `report` refuse the disabled one.

Example:

```bash
export IIWI_HARNESSES__CODEX__ENABLED="true"
export IIWI_HARNESSES__CODEX__HOME_DIRECTORY="$HOME/.codex"
iiwi doctor --harness codex
```

## Report settings

| Environment variable | Default | Purpose |
|---|---|---|
| `IIWI_REPORT__TIMEZONE` | `Asia/Taipei` | Calendar-week and naive ISO timestamp timezone. |
| `IIWI_REPORT__OUTPUT_DIRECTORY` | `reports` | Default Markdown output directory. |
| `IIWI_REPORT__EXCLUDE_REPOSITORIES` | `""` | Comma-separated repository ids to permanently leave out of every scan and report. |
| `IIWI_REPORT__QUICK_REVIEW_REPORT_TYPE` | `manager` | Default Quick Review audience: `manager` or `engineering`. Manager defaults to Brief; Engineering defaults to Full unless Detail was explicitly changed. |
| `IIWI_REPORT__QUICK_REVIEW_MAX_EVIDENCE_BYTES` | `40000` | Largest evidence payload one Quick Review synthesis run may send to `opencode run`. |

The `--output` CLI option overrides the configured output directory for one invocation.

Repositories are matched by their `repository_id` — the string `scan` groups sessions
under — not by the display name shown in the report. A repository with no activity in a
period produces no warning; one that was actually excluded adds a warning naming it and
the number of sessions dropped, and when exclusion removes everything the command says so
instead of reporting "no activity found".

```bash
iiwi config set report.exclude_repositories "dotfiles,notes-vault"
```

The exact Quick Review key is `report.quick_review_report_type`, and its
environment variable is `IIWI_REPORT__QUICK_REVIEW_REPORT_TYPE`. For example:

```bash
iiwi config set report.quick_review_report_type manager
```

Changing the Report row during Quick Review also saves this default for the next
interactive report.

`report.quick_review_max_evidence_bytes` bounds the evidence Quick Review sends to
one `opencode run`. Past roughly this size the model stops returning the strict
JSON synthesis needs — a full week of sessions used to return nothing at all, and
Quick Review always fell back to the session-based report. Synthesis sends the
most recent sessions that fit; the sessions beyond the budget become ungrouped
candidates in the review, and a warning names how many were held back.

Each session costs roughly 580 bytes of that budget, so the default of `40000`
covers about the 65 most recent sessions and leaves the rest as ungrouped
candidates. That per-session cost is also the floor: `1000` is the smallest
value the setting accepts, because a budget no single session fits in leaves
every selection over budget and Quick Review refuses all of them. That budget is
a hard limit rather than an estimate: synthesis measures the payload exactly as
it will be sent, so what goes to the model stays under the number you set.
Raising it has a real ceiling rather than free headroom: against a busy week of
175 sessions, `40000` returned grouped outcomes, `80000` came back without valid
outcome JSON, and `120000` ran past the 600-second `run_timeout_seconds`. Those
runs used the default local model, so a more capable one may reach further —
raise the budget a step at a time and confirm synthesis still succeeds. When it
does not, Quick Review's recovery screen still offers the session-based report,
so a budget set too high degrades the review rather than breaking it.

## OpenCode run settings

The default narrative report runs the locally installed `opencode run`. These
settings control that invocation. An empty `MODEL` uses opencode's default model.

| Environment variable | Default | Purpose |
|---|---|---|
| `IIWI_HARNESSES__OPENCODE__CLI__EXECUTABLE` | `opencode` | The `opencode` executable used for export, stats, and the narrative report. |
| `IIWI_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS` | `600.0` | How long a single `opencode run` may take before Iiwi falls back to the structured report. |
| `IIWI_HARNESSES__OPENCODE__CLI__MODEL` | `""` | Optional model passed as `--model` to `opencode run`. Empty means opencode's default. |

To pin a specific model for report narratives:

```bash
export IIWI_HARNESSES__OPENCODE__CLI__MODEL="gpt-5.3"
iiwi report --period last-week
```

To disable the narrative for one command and emit the deterministic structured report:

```bash
iiwi report --period last-week --no-llm
```

## Precedence

For each setting, Iiwi takes the environment variable, then the settings file,
then the default. CLI period and output options apply to the current invocation only
and override the settings that back them. Environment settings provide defaults for
harness execution, timezone, output directory, and the narrative `opencode run`
invocation.

## OpenCode export privacy

`IIWI_HARNESSES__OPENCODE__CLI__SANITIZE` defaults to `false`.
Set it to `true` to request `opencode export --sanitize`. The CLI flags
`--sanitize` and `--no-sanitize` override this setting for one invocation.
