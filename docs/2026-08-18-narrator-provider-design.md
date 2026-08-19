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
| `codex` | `codex exec <prompt> [-m M] --skip-git-repo-check` | stdin |

`codex exec` documents the exact combination iiwi needs: "If not provided as an
argument (or if `-` is used), instructions are read from stdin. If stdin is piped
and a prompt is also provided, stdin is appended as a `<stdin>` block." The
claude and codex adapters are therefore structurally identical: prompt as an
argument, transcript on stdin.

`--strict-mcp-config` is passed with no `--mcp-config`, which disables MCP
servers for the run. `--bare` is deliberately not used: it would also disable
OAuth and keychain reads, breaking the no-API-key contract.

`codex exec` refuses to run outside a Git repository unless
`--skip-git-repo-check` is passed, and the codex adapter's workdir is a
disposable temp dir iiwi created, not a repo — so the flag is always passed
and the check protects against nothing here. `claude -p` has no equivalent
precondition: it explicitly skips its workspace-trust dialog in
non-interactive/print mode instead of refusing to run (`claude --help`).

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

Each "can read" predicate is defined beside the source it describes — an
`is_available` function in `harnesses/opencode/source.py`,
`harnesses/claude_code/source.py` and `harnesses/codex/source.py`, taking the
same arguments the source constructor already takes. One definition per harness,
so the predicate cannot drift away from what the source actually requires.

Choosing a default harness is currently implemented four separate times, and all
four consult `enabled` only. That is why a machine without OpenCode hits the
problem everywhere, not just in `report`: the interactive Review Activity screen
opens on OpenCode too, and the user has to cycle off it by hand.

`cli.py:958` and `interactive/cli_actions.py:67` are the same expression written
twice —
`Harness.OPENCODE if Harness.OPENCODE in enabled else enabled[0]`. This work
collapses them into one helper, since both sites are being changed anyway.

A new `cli._available_harnesses(settings)` filters `_enabled_harnesses` through
those predicates. Every site that picks or offers a harness uses it:

| # | Site | Today |
| --- | --- | --- |
| 1 | `--harness` default (`cli.py:73`) | Hardcoded `Harness.OPENCODE` |
| 2 | `_ask_harness` default (`cli.py:958`) | Prefer OpenCode, else `enabled[0]` |
| 3 | `_new_draft` initial harness (`interactive/cli_actions.py:67`) | Duplicate of 2 |
| 4 | `_choose_harness` cycle list (`interactive/cli_actions.py:83`) | Cycles `enabled` |
| 5 | Daily's scanner set (`interactive/cli_actions.py:495`) | Builds one scanner per `enabled` harness |
| 6 | Daily's provider choice | Did not exist |

Site 4 cycles through available harnesses rather than enabled ones: offering a
harness whose sessions cannot be read is a dead end in a key-driven UI. Site 6
is the only one that uses the "can narrate" predicate; the rest use "can read".

The interactive screen is the tool's primary entry point, so sites 3 and 4 are
what make "installing only Claude Code is enough" true in practice rather than
only on the command line.

### What is unified and what is not

The six sites all ask the same question and share one answer, but they are not
made to behave identically, and the remaining difference is deliberate.

Unified: availability has one definition per harness, and the preference order
"prefer OpenCode, else the first in `Harness` declaration order" has one
implementation. Sites 1, 2, 3 and 6 use the preference helper; site 4 cycles the
list; site 5 builds a scanner for every entry in it.

Not unified, on purpose: `report` and Review Activity select a single harness
because the user is choosing what to look at, while Daily uses every available
harness because a person's day is not partitioned by which coding agent produced
it, and reporting half of it would be under-reporting. This is the same
distinction that separates provider rule 2 from rule 3. It is a product contract
recorded in `docs/2026-08-13-daily-standup-design.md`, not an inconsistency left
over from this change.

"Prefer OpenCode, else the first in `Harness` declaration order" is the rule
`_ask_harness:958` already uses; it is reused rather than replaced, so a machine
with OpenCode installed sees no change. When nothing is available, the error
names every path and binary checked.

An explicitly passed `--harness` is always obeyed and fails loudly when
unavailable. Explicit always beats inferred.

Because `--harness` no longer has a static default, its help text reads
"defaults to the first available harness".

### Relationship to Daily's existing availability check

Daily already reports `unavailable_harnesses` (`services/daily_scan.py:83`), but
determines it empirically: it runs every scanner and records the ones that raise
`HarnessSourceError`. That check is kept and becomes a runtime safety net — a
directory can disappear between the pre-check and the scan, and the OpenCode CLI
can fail for reasons `which` cannot see. Its meaning narrows usefully, from "did
not produce sessions" to "passed the pre-check but failed while scanning".

The pre-check is what makes the two mechanisms agree, because the three sources
do not agree today. `CodexSource.discover` raises `HarnessSourceError` when its
home directory is missing (`harnesses/codex/source.py:56`) and the OpenCode
source raises when its CLI call fails, but `ClaudeCodeFileSource.discover`
returns an empty list (`harnesses/claude_code/source.py:112`). A machine with no
`~/.claude/projects` therefore has Claude Code recorded today as a successful
scan with zero sessions, which is the silent incomplete coverage the Daily design
forbids.

Filtering the scanner set by the pre-check fixes that without changing any
source's error behaviour: a harness that cannot read never gets a scanner, so it
is neither silently counted nor noisily warned about. Making
`ClaudeCodeFileSource` raise instead was rejected — it would emit a coverage
warning every day for anyone who has Claude Code enabled but has never used it.

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
Quick Review and Daily raise. For the Weekly report, Quick Review, and `doctor`
— which already resolve a single harness before narrating — one setting fixes
it: `narrator.executable` pointing at the CLI the desktop install ships. Daily
scans every enabled harness rather than one, so `narrator.executable` alone is
ambiguous there — `_resolve_executable` applies it to whichever provider Daily
is about to probe, which would make an unrelated provider appear installed
too. Daily therefore also needs `narrator.provider=codex` set alongside it.
Either way it shares `~/.codex/auth.json`, so no separate login is needed.

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

**Availability.** Each harness's `is_available` gets its own test against
`tmp_path` with `shutil.which` monkeypatched, reusing the `codex_home` fixture
(`tests/conftest.py:421`). `_available_harnesses` is then tested for the
composition. The Codex-desktop case is explicit: data present, binary absent,
reads succeed, narration fails, and the message references the documentation
section.

Two Daily cases pin the relationship between the pre-check and the runtime
safety net: a harness that fails the pre-check produces no scanner at all and no
coverage warning, while a harness that passes the pre-check and then raises
`HarnessSourceError` is still recorded in `unavailable_harnesses` with its
coverage warning.

All six harness-selection sites get a case on a machine where OpenCode is
unavailable and Claude Code is: the `--harness` default, `_ask_harness`,
`_new_draft`'s initial harness, `_choose_harness`'s cycle list, Daily's scanner
set and Daily's provider all resolve to Claude Code without configuration.

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

The narration subprocesses are tool-restricted against prompt-injection
exfiltration. `claude -p` runs with `--tools ""`, which disables the built-in
tool set outright: the transcript arrives on stdin, so narration never reads a
file, and an allowlist that kept `Read` would leave an injection able to print a
local secret into the report itself. With no tools available the model may
instead emit a made-up tool call as plain text, which dirties a report rather
than leaking from it.

`codex exec` runs with `--sandbox read-only` — explicit even though it is the
default, so a user's own `sandbox_mode = "workspace-write"` cannot widen the
narration run. Codex has no tool-allowlist flag, so the two providers are not
symmetric: the sandbox stops writes, shell escapes and network, but the model
can still read a local file and put its contents in the narrative.

Neither flag changes the credential path or the workdir isolation described
below.

`claude -p` still loads the user's global `~/.claude/CLAUDE.md`. A global
instruction such as "always answer in one sentence" would visibly distort
reports. `--bare` would prevent it but also disables OAuth, which is not
acceptable. This is documented rather than worked around.

The project-level file, and project hooks, are excluded because
`CommandRunner.run` launches the child with `cwd` set to the
`secure_temporary_directory()` workdir, not because the transcript happens to
be staged there: a subprocess's working directory is independent of any file
path passed on its command line, so a temporary transcript file alone does not
stop `claude -p` or `codex exec` from resolving `CLAUDE.md`,
`.claude/settings*.json`, and Stop/PreToolUse hooks from wherever the parent
process's cwd points — which, without an explicit `cwd`, is the user's project
directory. `OpenCodeRunner` is the one exception: it deliberately keeps
inheriting iiwi's cwd unchanged, since an existing OpenCode setup must see no
behaviour change from this design.

## Verified facts

Collected during design; recorded so implementation does not re-litigate them.

| Fact | Evidence |
| --- | --- |
| `claude -p` accepts a prompt argument, `--model`, and text on stdin | `claude --help` |
| An unauthenticated `claude -p` exits 1, writes to stdout, leaves stderr empty | Direct run against a fresh `CLAUDE_CONFIG_DIR` |
| `CLAUDE_CONFIG_DIR` fully isolates session storage but also isolates credentials | Direct run; JSONL landed in the temporary directory, `Not logged in` returned |
| `codex exec` takes a prompt argument, `-m/--model`, and appends piped stdin as a `<stdin>` block | `codex exec --help` |
| `codex exec` refuses to run outside a Git repository, so it fails at startup in the adapter's disposable temp-dir workdir; `--skip-git-repo-check` fixes it | `codex-cli 0.148.0-alpha.9`: in a non-repo temp dir, `echo "" \| codex exec "reply with OK"` exits 1 with stderr `Not inside a trusted directory and --skip-git-repo-check was not specified.`; adding `--skip-git-repo-check` to the same command exits 0 and prints the requested reply |
| The Codex desktop install ships a complete CLI outside PATH | `~/.codex/plugins/.plugin-appserver/codex --version` reports `codex-cli 0.148.0-alpha.9`; `chrome-native-hosts-v2.json` pins `cliVersion` to `appVersion` |
| `harnesses/` and `summarizers/` do not import each other | Grep in both directions |
| `report`, `scan` and `doctor` take one harness; only `daily` is multi-harness | `_HARNESS_OPTION` appears at `cli.py:430`, `:485`, `:584` and nowhere else; `daily` (`cli.py:1041`) takes no harness |
| Default-harness selection is implemented four times, none consulting availability | `cli.py:73`, `cli.py:958`, `interactive/cli_actions.py:67`, `interactive/cli_actions.py:83` |
| The three sources disagree on what "unavailable" means | Codex raises (`harnesses/codex/source.py:56`), OpenCode raises on CLI failure, Claude Code returns `[]` (`harnesses/claude_code/source.py:112`) |
| Quick Review's JSON extraction is provider-agnostic | `_extract_json_object` (`services/outcomes.py:706`) scans for the first decodable object, ignoring fences and prose |
