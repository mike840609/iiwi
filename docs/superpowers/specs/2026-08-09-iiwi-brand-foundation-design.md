# Iiwi Brand Foundation Design

## Goal

Rename Agent Worklog cleanly to **Iiwi** and establish the minimum truthful brand foundation for the next release without changing the core scan, repository-resolution, evidence-selection, summarization, or report-generation behavior.

The product display name is **Iiwi**. The ASCII technical identifier is **`iiwi`**. The Hawaiian bird name **ʻIʻiwi** is used only when explaining the mascot/brand story; source paths, package names, commands, URLs, and environment variables stay ASCII.

## Context and constraints

- The current distribution and CLI are `agent-worklog`, while the Python import package is `agent_worklog`.
- Configuration and local state currently use the `AGENT_WORKLOG_*` prefix and `agent-worklog` platformdirs application name.
- The update checker currently points directly at the `agent-worklog` PyPI project and prints `pipx upgrade agent-worklog`.
- CI and release coverage target the `agent_worklog` package.
- The README, current documentation, badges, release instructions, and tests contain the old product name and command.
- There are currently no users who require compatibility with the old CLI, import package, configuration prefix, or local data paths.
- `.superpowers/` must not be committed. Superpowers design and plan documents live under `docs/superpowers/`.
- Historical changelog entries and historical design/plan documents are records of work done under the old name and are not rewritten merely to remove the old name.

## Chosen approach: clean-cut rename

Use a single coherent identity everywhere that is part of the current product surface:

| Surface | Old | New |
|---|---|---|
| Product | Agent Worklog | Iiwi |
| PyPI distribution | `agent-worklog` | `iiwi` |
| CLI | `agent-worklog` | `iiwi` |
| Python package | `agent_worklog` | `iiwi` |
| Environment prefix | `AGENT_WORKLOG_` | `IIWI_` |
| Config override | `AGENT_WORKLOG_CONFIG_FILE` | `IIWI_CONFIG_FILE` |
| History override | `AGENT_WORKLOG_HISTORY_FILE` | `IIWI_HISTORY_FILE` |
| State override | `AGENT_WORKLOG_STATE_FILE` | `IIWI_STATE_FILE` |
| platformdirs app name | `agent-worklog` | `iiwi` |
| GitHub repository | `mike840609/agent-worklog` | `mike840609/iiwi` |
| Update index | PyPI `agent-worklog` JSON | PyPI `iiwi` JSON |
| Upgrade command | `pipx upgrade agent-worklog` | `pipx upgrade iiwi` |

No legacy aliases, import shims, config migration, environment-variable fallback, or dual-data-directory lookup are added.

### Rejected alternatives

1. **Brand/CLI rename while keeping `agent_worklog` imports.** Smaller diff, but leaves the project with two identities and makes future documentation, tracebacks, coverage, and plugin integration confusing.
2. **Temporary compatibility layer.** Useful for an installed user base, but with no users it adds dead code and migration tests for no benefit.

## Product positioning and copy

Phase 1 establishes a broader but still truthful position:

> **Iiwi — Agent Session Intelligence for engineering work.**

Primary supporting line:

> **Probe coding-agent sessions. Surface the work that matters.**

The README must still explain the actual current capability explicitly: Iiwi reads OpenCode, Claude Code, and Codex sessions, groups work by repository, selects/redacts useful evidence, and produces engineering reports. It must not claim that search, memory, dashboards, alerts, RAG, or other future platform features already exist.

The pronunciation appears once near the first brand introduction:

> **Iiwi** *(ee-EE-wee)*

The brand story may mention that the ʻIʻiwi probes flowers with its curved bill for nectar; this is a metaphor, not a technical claim.

## Source-code rename

Rename the package directory from `src/agent_worklog/` to `src/iiwi/` and update all internal imports from `agent_worklog...` to `iiwi...`.

Rename internal brand-bearing symbols where the old product name leaks into current APIs or user-visible errors. In particular, `AgentWorklogError` becomes `IiwiError`; subclasses continue to preserve their existing behavior and exit semantics.

Do not refactor unrelated modules or change service boundaries during the rename. This phase is intentionally mechanical except where a stale brand identifier would otherwise remain in a current surface.

## CLI and runtime identity

`pyproject.toml` exposes exactly one console script:

```toml
[project.scripts]
iiwi = "iiwi.cli:app"
```

The CLI help, interactive headers, module docstrings that identify the product, version output, error messages, JSON-neutral metadata, and current examples use **Iiwi** / `iiwi` consistently.

The next release version is **0.9.0**. The rename is a material user-facing change and the existing repository already contains unreleased work after 0.8.0, so the first Iiwi package/release uses 0.9.0 rather than attempting to reuse the existing `v0.8.0` tag.

## Configuration and local application data

Because there are no users to migrate, the runtime identity changes completely:

- Pydantic settings prefix becomes `IIWI_`.
- `config_store` constants become `IIWI_CONFIG_FILE` and `IIWI_`.
- Harness-disable error hints name `IIWI_HARNESSES__...` variables.
- History and interactive-state override variables become `IIWI_HISTORY_FILE` and `IIWI_STATE_FILE`.
- `platformdirs.user_config_dir`, `user_data_dir`, and any other brand-owned directory lookup use `iiwi`.

Existing `agent-worklog` config/state/history directories are intentionally not imported or read.

## Update and release flow

The opt-in update check changes to the `iiwi` PyPI JSON endpoint, sends an `iiwi/<version>` user agent, and prints `pipx upgrade iiwi`.

Release verification changes coverage from `--cov=agent_worklog` to `--cov=iiwi`.

Before the first `v0.9.0` release:

1. Rename the GitHub repository to `mike840609/iiwi`.
2. Create/configure the PyPI `iiwi` project through Trusted Publishing using owner `mike840609`, repository `iiwi`, workflow `release.yml`, environment `pypi`.
3. Keep the GitHub environment named `pypi`.
4. Run the release workflow manually once to build and validate without publishing.
5. Tag and publish `v0.9.0` only after the `iiwi` Trusted Publisher is correct.

The old `agent-worklog` PyPI project is not republished as a compatibility package in this phase.

## Documentation scope

Update current user-facing and operational documentation, including at minimum:

- `README.md`
- `README.zh-TW.md`
- `SECURITY.md`
- `docs/cli-reference.md`
- `docs/configuration.md`
- `docs/guides.md`
- `docs/privacy.md`
- `docs/limitations.md`
- `docs/usage-statistics.md`
- `docs/releasing.md`
- current architecture/overview asset source text or labels when they display the old brand
- current GitHub/PyPI/DeepWiki badges and repository links

Historical records remain historical. This exemption covers old release notes already recorded in `CHANGELOG.md`, old files under `docs/plans/`, and design documents whose purpose is to describe a past Agent Worklog change. New Unreleased changelog text gets an explicit rename entry and uses Iiwi for current/future statements.

## Visual foundation in Phase 1

Phase 1 does not require a polished final mascot illustration. It establishes only the brand rules needed to keep later visual work coherent:

- product spelling: `Iiwi`
- technical spelling: `iiwi`
- bird spelling in explanatory copy: `ʻIʻiwi`
- pronunciation: `ee-EE-wee`
- core metaphor: **probe → surface useful signal**
- visual direction: an ʻIʻiwi-inspired bird, with the curved bill as the distinctive mark

A full logo system, color palette, GitHub avatar, social preview, and terminal art belong to the later visual-identity milestone, not this code/package rename.

## Testing strategy

The rename must be test-driven where behavior or public identity changes.

Tests must cover at least:

1. `pyproject.toml` identifies distribution `iiwi` and only the `iiwi` console script.
2. `import iiwi` exposes version `0.9.0`; current tests no longer import `agent_worklog`.
3. CLI help/version and interactive product headers say Iiwi and invoke through `iiwi`.
4. Settings resolve `IIWI_*` variables and no longer consume `AGENT_WORKLOG_*` variables.
5. Config/history/state default paths use platformdirs application name `iiwi`.
6. Update checks target PyPI project `iiwi`, use an Iiwi user agent, and return `pipx upgrade iiwi`.
7. Documentation contract tests assert `pipx install iiwi` and representative `iiwi ...` commands.
8. CI and release workflow coverage target `iiwi`.
9. A stale-brand guard scans current source, tests, workflow files, and current user-facing docs for accidental `agent-worklog`, `agent_worklog`, `AGENT_WORKLOG`, or `Agent Worklog`, while explicitly excluding historical records defined above.
10. Full `pytest`, Ruff, Pyright, package build, and Twine checks pass.

## Acceptance criteria

Phase 1 is complete when all of the following are true:

- `uv run iiwi --version` reports `0.9.0`.
- `uv run iiwi --help`, `doctor`, `scan`, `report`, `history`, `update`, `config`, and `run` retain their existing behavior under the new command.
- `uv build` produces `iiwi-0.9.0` distributions.
- No current runtime import requires `agent_worklog`.
- No legacy console-script alias is installed.
- New installs/configuration use only `iiwi` / `IIWI_*` / Iiwi-owned platformdirs paths.
- The update command checks the Iiwi PyPI project.
- Current public docs and release instructions use the new identity consistently.
- Historical docs remain intact rather than being rewritten as if they had always used Iiwi.
- Test coverage remains at least 80%, Ruff passes, Pyright passes, built distributions pass `twine check`.

## Out of scope

The following are deliberately deferred:

- search across historical sessions
- persistent knowledge/memory/RAG features
- dashboards, alerts, or analytics UI
- API/server architecture for an intelligence platform
- final logo artwork and mascot asset set
- compatibility with the old CLI/package/config paths
- automatic migration from old local data
- publishing a shim or deprecation release to `agent-worklog`
