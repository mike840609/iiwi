# Narrator Provider Design

Date: 2026-08-18
Status: Approved design

## Goal

Remove iiwi's hard dependency on the `opencode` executable for producing report
prose, so that a machine with only Claude Code or only Codex installed can
generate every report iiwi offers, with no configuration.

The session-reading layer is not the problem and does not change. The three
`HarnessSessionSource` implementations already have no dependency on each other.
What every report path shares today is a single narrative engine that shells out
to `opencode run`.

## Current state

Reading is already independent:

- `harnesses/opencode/source.py`, `harnesses/claude_code/source.py` and
  `harnesses/codex/source.py` each implement `HarnessSessionSource`
  (`harnesses/base.py:9`) and import nothing from one another.
- `src/iiwi/harnesses/` does not import `src/iiwi/summarizers/`, and the reverse
  is also true. The only place that knows about both is the composition root.

Narration is not. `OpenCodeRunner` (`summarizers/opencode_run.py:160`) runs
`opencode run`, and all three producing paths go through it:

| Path | Call site |
| --- | --- |
| Weekly narrative | `services/report.py:208` |
| Quick Review synthesis | `services/outcomes.py:332` |
| Daily standup | `interactive/cli_actions.py:470` |

So `--harness claude-code` changes only where sessions are read from; the prose
still requires `opencode` on the machine (README.md:141 already states this).

Three further leaks of the OpenCode brand into shared layers exist today and are
in scope because they defeat the goal:

1. The prompt templates sent to the model say "the attached **OpenCode** session
   transcript" (`summarizers/opencode_run.py:19` and `:105`). Scanning Codex
   sessions today already tells the model something false.
2. Failure messages hardcode `opencode run` (`services/report.py:188` and
   `:248`).
3. `build_summary_prompt`, which is harness-agnostic, lives in
   `summarizers/opencode_run.py`.

## Product contract

| Situation | Behaviour |
| --- | --- |
| Existing user upgrades, changes nothing | Identical behaviour to today |
| Only Claude Code installed | Works with no configuration; `opencode` not required |
| Only Codex installed (CLI on PATH) | Works with no configuration |
| Only Codex desktop (data present, no CLI on PATH) | Reads fine; narration needs one `narrator.executable` setting |
| Scan one harness, narrate with another | Supported by setting `narrator.provider` |

No API key is introduced. iiwi continues to drive a CLI the user already has.

## Architecture

| Layer | Package | Relationship to OpenCode |
| --- | --- | --- |
| Reading | `harnesses/` | Three equal implementations (already true) |
| Narration | `summarizers/` | Three equal implementations (this change) |
| Composition | `cli.py`, `interactive/cli_actions.py` | The only layer aware of both |

**Direction invariant:** `src/iiwi/harnesses/` must not import
`src/iiwi/summarizers/`. This holds today and is pinned by a test rather than by
convention, because a violation would produce no symptom until someone tries to
replace the narration layer.

Provider resolution lives in `cli._build_narrator(settings, harness)`, beside the
existing `_build_scan_service` and `_build_report_service`.
`interactive/cli_actions.py` reuses it through the `from iiwi import cli` import
it already uses. Resolution is deliberately not placed in `summarizers/`, which
would make that package depend on `config`.

### Narration contract

New module `src/iiwi/summarizers/narrator.py`:

```python
class NarrativeRunner(Protocol):
    def run(self, *, transcript: str, prompt: str, title: str) -> str: ...


class NarrativeRunError(Exception): ...


OpenCodeRunError = NarrativeRunError  # alias; existing catch sites unchanged
```

The signature is the one `OpenCodeRunner` already has, so this promotes an
existing shape to a contract rather than inventing an abstraction. The two
`except OpenCodeRunError` sites (`services/report.py:246`,
`interactive/cli_actions.py:459`) keep working through the alias.

`narrator.py` also takes ownership of `build_summary_prompt` and the two prompt
templates. `summarizers/opencode_run.py` is left holding only the OpenCode
adapter.

## Adapters

All three command surfaces were verified against the real executables before
this design was accepted; none is assumed.

| Provider | Command | Transcript |
| --- | --- | --- |
| `opencode` | `opencode run <prompt> --title T --file F --print-logs [--model M]` | `--file` |
| `claude` | `claude -p <prompt> --strict-mcp-config [--model M]` | stdin |
| `codex` | `codex exec <prompt> [-m M]` | stdin |

`codex exec` documents the exact combination iiwi needs: "If not provided as an
argument (or if `-` is used), instructions are read from stdin. If stdin is piped
and a prompt is also provided, stdin is appended as a `<stdin>` block." The
claude and codex adapters are therefore structurally identical: prompt as an
argument, transcript on stdin.

`--strict-mcp-config` is passed with no `--mcp-config`, which disables MCP
servers for the run. `--bare` is deliberately not used: it would also disable
OAuth and keychain reads, breaking the no-API-key contract.

## Availability

Two different questions, deliberately answered by different predicates, because
they can disagree: a machine can hold a complete `~/.codex` session store while
no `codex` binary is on PATH.

| Harness | Can read | Can narrate |
| --- | --- | --- |
| `opencode` | `which(harnesses.opencode.cli.executable)` | `which(resolved executable)` |
| `claude-code` | `harnesses.claude_code.projects_directory.is_dir()` | `which(resolved executable)` |
| `codex` | `harnesses.codex.home_directory.is_dir()` | `which(resolved executable)` |

`enabled` and `available` are separate concepts. `enabled` is policy — whether an
operator permits the harness at all. `available` is fact. `available ⊆ enabled`.

A new `cli._available_harnesses(settings)` filters `_enabled_harnesses` by the
"can read" predicate and is used in three places:

1. The default value of `--harness` (`cli.py:72`) becomes the first available
   harness, preferring OpenCode when it is available.
2. `_ask_harness` (`cli.py:954`) offers the same default.
3. Daily's provider choice, which has no single harness, uses the "can narrate"
   predicate.

"Prefer OpenCode, else the first in `Harness` declaration order" is the rule
`_ask_harness:958` already uses; it is reused rather than replaced, so a machine
with OpenCode installed sees no change. When nothing is available, the error
names every path and binary checked.

An explicitly passed `--harness` is always obeyed and fails loudly when
unavailable. Explicit always beats inferred.

Because `--harness` no longer has a static default, its help text reads
"defaults to the first available harness".

## Resolution rules

### Provider

| # | Condition | Result |
| --- | --- | --- |
| 1 | `narrator.provider` is set | Use it; a value other than `opencode`/`claude`/`codex` is a configuration error |
| 2 | Empty, single-harness path | The same-named provider. No substitution when its binary is missing |
| 3 | Empty, multi-harness path (Daily only) | Among harnesses that are enabled and can narrate: prefer OpenCode, else the first in `Harness` declaration order |

Rule 2 does not substitute a different provider. Silently switching models
produces reports whose style changes between weeks for reasons the user cannot
trace; the failure paths below are honest instead.

### Executable, model, timeout

One governing rule: **a fallback to `harnesses.opencode.cli.*` applies only when
the resolved provider is `opencode`.** Without this, a leftover OpenCode model
name would be passed to `claude --model` and fail.

| Setting | Set | Empty, provider is `opencode` | Otherwise |
| --- | --- | --- | --- |
| `narrator.executable` | Use it | `harnesses.opencode.cli.executable` | `claude` / `codex` |
| `narrator.model` | Use it | `harnesses.opencode.cli.model` (deprecated) | Omit `--model`; the CLI's own default applies |
| `narrator.timeout_seconds` | Use it | `harnesses.opencode.cli.run_timeout_seconds` (deprecated) | `600.0` |

## Configuration

New top-level section:

```python
class NarratorSettings(BaseModel):
    """How iiwi turns a transcript into prose."""

    provider: str = ""          # "" derives from the harness
    executable: str = ""        # "" uses the provider's default binary name
    model: str = ""
    timeout_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
```

`timeout_seconds` is `float | None` because it needs an "unset" state that the
`gt=0` constraint cannot express; this mirrors the empty-string-as-unset idiom
the surrounding settings already use, and validation still applies to real
values.

`setting_keys()` (`config_store.py:92`) walks the model tree rather than a
hand-kept list, so `config set narrator.provider`, `config list` and the
interactive settings editor all support the new keys with no CLI changes.

### What stays where it is

`harnesses.opencode.cli.executable`, `.timeout_seconds` and `.sanitize` remain
harness settings. They drive `opencode export`, `opencode stats` and
`opencode db` (`cli.py:241`, `cli.py:270`, `services/doctor.py:74`) and have no
narration role. Only `.model` and `.run_timeout_seconds` are purely narration
settings, so the split is two fields wide, not a whole section.

### Compatibility

`AppSettings` is `extra="ignore"` (`config.py:124`), so deleting the two moved
fields would make an existing `IIWI_HARNESSES__OPENCODE__CLI__MODEL` silently
stop taking effect. That is the worst available outcome and is not acceptable.

Instead both fields stay in the model, marked `Field(deprecated=True)`, and are
read as fallbacks under the governing rule above. When either holds a value,
`cli._load_settings()` writes one notice to stderr naming the replacement key.
The notice does not travel through `initial_warnings`, which would print a
configuration migration inside the report body.

No `config migrate` command is written and the user's settings file is never
rewritten. The fallback already keeps old settings working, so rewriting a file
iiwi does not own would be an irreversible action bought for cosmetics. The
removal release is recorded in the changelog.

## Self-authored session exclusion

`is_iiwi_authored` (`sessions/filtering.py:59`) keeps iiwi's own runs out of the
next report by matching the `iiwi-internal: ` prefix on the session title. Only
`opencode run` accepts `--title`. Claude Code's title comes from a
model-generated `ai-title` record (`harnesses/claude_code/mapper.py:204`) and
Codex's from the state database's `title` column
(`harnesses/codex/thread_catalog.py:110`).

Without a fix, every report iiwi writes would be counted as the user's work in
the following report.

**Resolution:** move the marker from the title to the first line of the prompt.

Every adapter's `run` already receives `title`, so the adapter prepends
`iiwi-internal: <title>` plus a blank line to the prompt it sends. No caller
signature changes and no prompt builder needs to learn the title. The OpenCode
adapter keeps passing `--title` as well, so existing stores keep matching on the
old signal.

`is_iiwi_authored` gains a second signal: the first `USER_MESSAGE` activity's
content starts with the prefix. `SessionActivity.content` already carries this
for all three harnesses.

**Rejected:** pointing `CLAUDE_CONFIG_DIR` at a temporary directory. It isolates
session storage completely — verified: the JSONL lands in the temporary
directory and `~/.claude` stays clean — but credentials live in the same
directory, so an isolated run reports `Not logged in`, contradicting the
no-API-key contract.

## Failure behaviour

A `claude -p` run without credentials exits 1 and writes
`Not logged in · Please run /login` to **stdout**, leaving stderr empty. The
current message construction, `result.stderr.strip() or "opencode run failed"`
(`summarizers/opencode_run.py:235`), would discard that and report a generic
failure. Adapters therefore prefer stderr and fall back to the first line of
captured stdout.

| Path | Missing or failing narrator |
| --- | --- |
| Weekly report | Existing degradation: structured report plus a warning (`services/report.py:246`) |
| Quick Review, Daily | No degradation path exists; the error surfaces |

Both messages name the resolved provider and point at `narrator.provider` and
`narrator.executable`. When `~/.codex` exists but `which(codex)` fails, the
message additionally points at the Codex desktop section of
`docs/configuration.md`. It does not embed the bundled binary's path: that path
lives under a private directory and hardcoding it would break silently on a
future release.

No provider fallback chain and no login pre-check. A pre-check would require
spending a real request on every invocation to learn something the exit code
already reports.

## Doctor

The existing harness checks are unchanged; they describe the data source. One
row is added unconditionally:

```text
narrator   ok   claude (from --harness claude-code) → /path/to/claude
narrator   ok   codex  (from narrator.provider)     → /path/to/codex
narrator   --   opencode not found (from --harness opencode)
```

The parenthetical states whether the provider was configured or derived, which
is what makes "scan Codex, narrate with Claude" visible at a glance.

## Scenarios

Assuming default configuration throughout.

**Only OpenCode installed.** Available harnesses `{opencode}`; provider
`opencode`; executable from `harnesses.opencode.cli.executable`; model from the
deprecated fallback. Identical to today's behaviour.

**Only Claude Code installed.** Available harnesses `{claude-code}`; provider
`claude`; executable `claude`; no `--model`, so Claude's own default applies. A
leftover `harnesses.opencode.cli.model` is not inherited, because the provider is
not `opencode`.

**Only Codex installed, CLI on PATH.** Available harnesses `{codex}`; provider
`codex`; executable `codex`; no `-m`.

**Only Codex desktop, no CLI on PATH.** `~/.codex` is a directory, so the harness
can read and reports scan normally. Narration resolves to `codex`, whose binary
is absent: the weekly report degrades to structured output with a warning, and
Quick Review and Daily raise. One setting fixes it —
`narrator.executable` pointing at the CLI the desktop install ships — and it
shares `~/.codex/auth.json`, so no separate login is needed.

## Testing

Requirement-driven, offline, no real model calls.

**Adapters.** Reuse the `RecordingRunner` fake from
`tests/unit/summarizers/test_opencode_run.py`. Assertions are on the constructed
argv and stdin, never on model output.

- `opencode`: argv contains `run`, `--title`, `--file`, `--print-logs`; `--model`
  appears only when a model is resolved.
- `claude`: argv contains `-p`, the prompt and `--strict-mcp-config`; the
  transcript arrives on stdin; `--model` is absent when no model is resolved.
- `codex`: argv contains `exec` and the prompt; the transcript arrives on stdin;
  `-m` appears only when a model is resolved.
- All: a non-zero return code with empty stderr produces a message taken from the
  first line of stdout.

**Resolution.** `_build_narrator` is pure logic; a parametrised test covers every
row of the four rule tables, including a leftover
`harnesses.opencode.cli.model` with `narrator.provider = claude`, which must not
be inherited. The four scenarios above each get an end-to-end resolution
assertion.

**Availability.** `_available_harnesses` against `tmp_path` with `shutil.which`
monkeypatched, reusing the `codex_home` fixture (`tests/conftest.py:421`). The
Codex-desktop case is explicit: data present, binary absent, reads succeed,
narration fails, and the message references the documentation section.

**Self-authored exclusion.** One case per harness: a session whose first user
message carries the prefix is excluded; one without it is retained; the OpenCode
legacy-title path still matches.

**Direction invariant.** An `ast` scan of `src/iiwi/harnesses/**` asserting no
`iiwi.summarizers` import.

**Compatibility.** A settings file holding only the deprecated keys resolves
field-for-field to today's values and emits exactly one stderr notice.

**Documentation.** `tests/unit/test_documentation.py:180` asserts both the new
and deprecated keys are documented, plus a new assertion that
`docs/configuration.md` contains the Codex desktop section the error message
points at.

No end-to-end test invokes a real CLI. All three interfaces were verified from
their own `--help` output; a live run would cost the user's quota, require
network access, and not be reproducible.

## Out of scope

A `config migrate` command; rewriting the user's settings file; a provider
plugin registry; direct API access; a provider fallback chain; login
pre-checks; driving `~/.codex/ipc/ipc.sock`, which is an undocumented private
protocol whose capability the CLI already exposes; hardcoding the Codex desktop
binary path into iiwi.

## Known residual risk

`claude -p` still loads the user's global `~/.claude/CLAUDE.md`. A global
instruction such as "always answer in one sentence" would visibly distort
reports. `--bare` would prevent it but also disables OAuth, which is not
acceptable. The project-level file is already excluded because runs happen inside
`secure_temporary_directory()`. This is documented rather than worked around.

## Verified facts

Collected during design; recorded so implementation does not re-litigate them.

| Fact | Evidence |
| --- | --- |
| `claude -p` accepts a prompt argument, `--model`, and text on stdin | `claude --help` |
| An unauthenticated `claude -p` exits 1, writes to stdout, leaves stderr empty | Direct run against a fresh `CLAUDE_CONFIG_DIR` |
| `CLAUDE_CONFIG_DIR` fully isolates session storage but also isolates credentials | Direct run; JSONL landed in the temporary directory, `Not logged in` returned |
| `codex exec` takes a prompt argument, `-m/--model`, and appends piped stdin as a `<stdin>` block | `codex exec --help` |
| The Codex desktop install ships a complete CLI outside PATH | `~/.codex/plugins/.plugin-appserver/codex --version` reports `codex-cli 0.148.0-alpha.9`; `chrome-native-hosts-v2.json` pins `cliVersion` to `appVersion` |
| `harnesses/` and `summarizers/` do not import each other | Grep in both directions |
| Quick Review's JSON extraction is provider-agnostic | `_extract_json_object` (`services/outcomes.py:706`) scans for the first decodable object, ignoring fences and prose |
