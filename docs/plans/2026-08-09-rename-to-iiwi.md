# Rename Agent Worklog to Iiwi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the project from `agent-worklog` to `iiwi` across the package, the runtime identity (env prefix, application directories, PyPI update check), packaging, CI, docs and assets — with no compatibility layer, no alias command and no deprecated package.

**Architecture:** The rename lands in dependency order so the tree is never left un-runnable for more than one commit. The Python package `src/agent_worklog/` moves to `src/iiwi/` together with its import rewrite (inseparable — the tree does not import otherwise). Runtime identity constants live in five files and are changed as one unit, because a partial change silently splits user state across two directories. Packaging, CI, docs, assets and the documentation tests follow. Historical records under `docs/plans/` and the existing `CHANGELOG.md` entries are deliberately **not** rewritten.

**Tech Stack:** Python 3.11+, hatchling, uv, typer, pydantic-settings, platformdirs, Jinja2, pytest, ruff, pyright, GitHub Actions.

## Prerequisites (do before Task 1)

- [ ] **Confirm the name.** Everything below uses `iiwi` / `IIWI_` / `Iiwi`. If the name changes, it is a single substitution throughout this plan.
- [ ] **Claim `iiwi` on PyPI.** Verified free (HTTP 404 on `pypi.org/pypi/iiwi/json`, 2026-08-09). PyPI has no reservation mechanism — the name is claimed by the first upload, so build and upload a placeholder (`0.8.1.dev0`) before starting. Short names are being taken quickly; `mole` went from free to a 62.7k-star CLI inside eleven months.
- [ ] **Optionally claim `iiwi` on npm** (also 404). Not needed for a Python tool; cheap insurance for the brand only.
- [ ] Do **not** rename the GitHub repository yet — that is Task 8, after merge.

## Global Constraints

- **Name forms.** `agent-worklog` → `iiwi` (distribution, CLI, URLs, app dirs) · `agent_worklog` → `iiwi` (Python package, imports, coverage target) · `Agent Worklog` → `Iiwi` (prose) · `AGENT_WORKLOG_` → `IIWI_` (env prefix) · `AgentWorklogError` → `IiwiError`.
- **No backward compatibility.** No `agent-worklog` alias console script, no shim package, no dual env-prefix support, no deprecated import path. This is the stated intent of the rename.
- **Out of scope — do not rename these.** `output_directory: Path("reports")` (generic, describes the artifact); harness identifiers `opencode`, `codex`, `claude_code`; the `# Engineering Worklog` H1 inside `templates/worklog.md.j2` (generic English for the document produced, not the product name — see Decision C).
- **Historical documents are frozen.** `docs/plans/*.md` (895 occurrences, 15 dated files) and existing `CHANGELOG.md` entries (13 occurrences) keep the old name. Rewriting them would falsify dated records and would triple the review surface for no reader benefit. Only a new CHANGELOG entry is added (Task 7).
- **Pronunciation is part of the rename.** `iiwi` is not guessable from spelling; the READMEs must state it (`/ˈiː.wiː/` — "ee-wee") on the first content line. Without this the name fails in conversation.
- **Verification gate after every task:**
  ```bash
  uv run pytest --cov=iiwi --cov-fail-under=80
  uv run ruff check .
  uv run pyright
  ```
- **Final sweep** (must return zero, historical records excluded):
  ```bash
  rg -i 'agent[-_ ]?worklog' --glob '!docs/plans/**' --glob '!CHANGELOG.md' --glob '!uv.lock'
  ```

---

### Task 1: Move the package and rewrite imports

**Files:**
- Move: `src/agent_worklog/` → `src/iiwi/` (16 directories, ~60 modules)
- Modify: every `from agent_worklog...` / `import agent_worklog` in `src/` and `tests/` (1,126 occurrences across ~130 files)

**Interfaces:**
- Produces: the `iiwi` import root that every later task depends on.
- Consumes: nothing.

The move and the import rewrite **must be one commit**. `git mv` alone leaves a tree that cannot import; the rewrite alone has nowhere to point. Git still detects the renames because file contents are otherwise untouched.

- [ ] **Step 1: Move the tree with git mv**

```bash
git mv src/agent_worklog src/iiwi
```

- [ ] **Step 2: Rewrite the import root**

```bash
rg -l '\bagent_worklog\b' src tests | xargs sed -i 's/\bagent_worklog\b/iiwi/g'
```

- [ ] **Step 3: Verify the move is clean**

```bash
uv run pytest -q                     # collection must succeed
git diff --cached -M --stat | tail -5   # expect renames, not delete+add
rg '\bagent_worklog\b' src tests     # must return nothing
```

Tests referencing `AGENT_WORKLOG_*` env vars still fail here — Task 2 fixes them. Everything else must pass.

- [ ] **Step 4: Commit**

`refactor: move the agent_worklog package to iiwi`

---

### Task 2: Rename the runtime identity

**Files:**
- Modify: `src/iiwi/config.py` (line ~85, `env_prefix`)
- Modify: `src/iiwi/config_store.py` (lines ~18, ~19, ~32 — `ENV_PREFIX`, `CONFIG_FILE_VARIABLE`, `user_config_dir`)
- Modify: `src/iiwi/history.py` (line ~42, `user_data_dir`)
- Modify: `src/iiwi/state.py` (line ~32, `user_data_dir`)
- Modify: `src/iiwi/update.py` (lines ~20, ~22, ~71 — `LATEST_URL`, `UPGRADE_COMMAND`, User-Agent)
- Modify: `src/iiwi/errors.py` and 13 other call sites (`AgentWorklogError`)

**Interfaces:**
- Produces: `IIWI_` env prefix, `iiwi` application directories, PyPI update check pointed at the new project, `IiwiError`.
- Consumes: the `iiwi` package root from Task 1.

This is the task where a partial edit causes **silent** damage, so all five files change together. The three `platformdirs` calls are independent literals — missing one leaves settings in the new directory while history or session-selection memory stays in the old one, with no error surfaced.

- [ ] **Step 1: Environment prefix**

`config.py`: `env_prefix="AGENT_WORKLOG_"` → `env_prefix="IIWI_"`.
`config_store.py`: `ENV_PREFIX = "IIWI_"`, `CONFIG_FILE_VARIABLE = "IIWI_CONFIG_FILE"`, and the docstring at line ~133 that names `AGENT_WORKLOG_CONFIG_FILE`.

Every documented variable derives from the prefix, so this changes the whole user-facing surface, e.g. `AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY` → `IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY`.

- [ ] **Step 2: Application directories — all three**

| File | Call | Holds |
|---|---|---|
| `config_store.py:32` | `user_config_dir("iiwi") / "config.env"` | user settings |
| `history.py:42` | `user_data_dir("iiwi") / "history.jsonl"` | report history behind `iiwi history` |
| `state.py:32` | `user_data_dir("iiwi") / "state.json"` | per-period session selection memory |

Apply Decision B here (migrate or not).

- [ ] **Step 3: Update check**

```python
LATEST_URL = "https://pypi.org/pypi/iiwi/json"
UPGRADE_COMMAND = "pipx upgrade iiwi"
headers={"User-Agent": f"iiwi/{current_version()} (version check)"}
```

Left unchanged, `iiwi` would poll the abandoned `agent-worklog` project forever and report wrong versions — a failure with no visible symptom.

- [ ] **Step 4: Error class**

```bash
rg -l '\bAgentWorklogError\b' src tests | xargs sed -i 's/\bAgentWorklogError\b/IiwiError/g'
```

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest --cov=iiwi --cov-fail-under=80
rg 'AGENT_WORKLOG|AgentWorklog' src tests   # must return nothing
```

`refactor: rename the runtime identity to iiwi`

---

### Task 3: Packaging and CI

**Files:**
- Modify: `pyproject.toml` (`name`, `description`, `[project.scripts]`)
- Modify: `.github/workflows/ci.yml` (line ~38, `--cov=agent_worklog`)
- Modify: `.github/workflows/release.yml` (line ~36, `--cov=agent_worklog`)
- Modify: `.codex/environments/environment.toml`

**Interfaces:**
- Produces: a wheel named `iiwi` exposing the `iiwi` console script.
- Consumes: the `iiwi` package root.

- [ ] **Step 1: pyproject**

```toml
name = "iiwi"
description = "Agent Session Intelligence for engineering work"

[project.scripts]
iiwi = "iiwi.cli:app"
```

Keep the version at `0.8.0` and let the next release be `0.9.0` — see Decision A. `[tool.pyright] include = ["src"]` and the `[tool.pytest.ini_options]` comment about harness `test_mapper.py` collisions need no change.

- [ ] **Step 2: Coverage target in both workflows**

`--cov=agent_worklog` → `--cov=iiwi` in `ci.yml` and `release.yml`. The `--cov-fail-under=80` gate reports 0% against a package name that no longer exists, so this cannot be skipped.

- [ ] **Step 3: Verify the built artifact**

```bash
uv build
python -c "import zipfile,glob; print(sorted({n.split('/')[0] for n in zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist()}))"
uv run iiwi --version && uv run iiwi doctor
```

- [ ] **Step 4: Commit** — `build: rename the distribution and console script to iiwi`

---

### Task 4: READMEs and documentation

**Files:**
- Modify: `README.md` (46 occurrences), `README.zh-TW.md` (41)
- Modify: `SECURITY.md`, and `docs/*.md` excluding `docs/plans/` (294 occurrences across 20 files)
- Do **not** modify: `docs/plans/**`, `CHANGELOG.md`

**Interfaces:**
- Consumes: the CLI name, env prefix and PyPI name settled in Tasks 2–3.

- [ ] **Step 1: Bulk substitution, historical records excluded**

```bash
rg -l -i 'agent[-_ ]?worklog' README.md README.zh-TW.md SECURITY.md docs \
  --glob '!docs/plans/**' \
| xargs sed -i \
    -e 's/agent-worklog/iiwi/g' \
    -e 's/agent_worklog/iiwi/g' \
    -e 's/Agent Worklog/Iiwi/g' \
    -e 's/AGENT_WORKLOG_/IIWI_/g'
```

- [ ] **Step 2: Fix what substitution cannot**

- Badge and link URLs in both READMEs (lines 3–9) still point at `github.com/mike840609/agent-worklog` and `deepwiki.com/mike840609/agent-worklog`. Repoint to `mike840609/iiwi`. GitHub redirects after Task 8, but the badges should read correctly.
- Add the pronunciation and positioning line under the H1 of both READMEs:
  ```
  Iiwi · /ˈiː.wiː/ "ee-wee" — Agent Session Intelligence for engineering work

  Probe coding-agent sessions. Surface the work that matters.
  ```
- The `agent-worklog` menu banner reproduced in the README quick-start block, and the `$ agent-worklog` prompt line, become `iiwi`. Check the ASCII box-drawing still aligns — `Iiwi` is nine characters shorter than `Agent Worklog`, so the `══` rule and the `↑↓ jk │ …` footer may need re-padding.
- `docs/releasing.md` describes the release procedure by name; re-read it once end to end rather than trusting the substitution.

- [ ] **Step 3: Verify** — `rg -i 'agent[-_ ]?worklog' README.md README.zh-TW.md SECURITY.md docs --glob '!docs/plans/**'` returns nothing.

- [ ] **Step 4: Commit** — `docs: rename to iiwi across the READMEs and guides`

---

### Task 5: Interactive banner and template

**Files:**
- Modify: `src/iiwi/interactive/render.py` (main-menu title string)
- Review: `src/iiwi/templates/worklog.md.j2`

**Interfaces:**
- Consumes: nothing new. Purely presentational.

- [ ] **Step 1: Main menu title**

`render_main_menu` prints `Agent Worklog` as the bold title, with the version right-aligned (see `docs/plans/2026-08-09-main-menu-version.md`). Change the literal to `Iiwi`. The width check `cell_len("Agent Worklog") + 1 + cell_len(version)` must use the new title or the version will be dropped on terminals where it now fits.

- [ ] **Step 2: Subtitle**

`"Turn coding-agent sessions into engineering reports"` contains no product name and can stay. Consider `"Probe coding-agent sessions. Surface the work that matters."` for consistency with the README — optional, cosmetic.

- [ ] **Step 3: Template**

`templates/worklog.md.j2` line 13 is `# Engineering Worklog` — the heading of the generated report, not the product name. Per Decision C, leave it. The filename `worklog.md.j2` is internal; renaming it to `report.md.j2` also means updating `renderers/markdown.py:37`. Optional.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/unit/interactive -q
uv run iiwi          # eyeball the menu; confirm the rule and footer still align
```

`feat: show the Iiwi name in the interactive menu`

---

### Task 6: Documentation tests

**Files:**
- Modify: `tests/unit/test_documentation.py`

**Interfaces:**
- Consumes: the renamed READMEs and docs from Task 4.

These tests assert exact literals against the shipped documentation and are the safety net for this whole rename — they fail loudly if any doc was missed. Update them deliberately, one assertion at a time, rather than by substitution.

- [ ] **Step 1: Update the asserted literals**

| Test | Old literal | New |
|---|---|---|
| `test_readme_documents_release_gate_commands` | `pipx install agent-worklog` | `pipx install iiwi` |
| " | `agent-worklog doctor` | `iiwi doctor` |
| " | `agent-worklog scan --period last-week` | `iiwi scan --period last-week` |
| " | `agent-worklog report --period last-week` | `iiwi report --period last-week` |
| `test_configuration_documents_the_claude_code_projects_directory` | `AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY` | `IIWI_HARNESSES__…` |
| `test_readmes_document_the_config_command` | `agent-worklog config set harnesses.opencode.cli.model deepseek-r1` | `iiwi config set …` |

- [ ] **Step 2: Add a regression test for the pronunciation line**

Both READMEs must carry it; it is the mitigation for the name's one real weakness and should not silently disappear.

```python
def test_readmes_state_the_pronunciation() -> None:
    for path in ("README.md", "README.zh-TW.md"):
        assert "ee-wee" in Path(path).read_text(encoding="utf-8")
```

- [ ] **Step 3: Verify and commit** — `uv run pytest tests/unit/test_documentation.py -q`, then `test: assert the docs describe iiwi`

---

### Task 7: Assets, changelog and the PyPI transition

**Files:**
- Move: `docs/assets/agent-worklog-overview.png` → `docs/assets/iiwi-overview.png`
- Modify: `README.md`, `README.zh-TW.md` (image URLs)
- Review: `docs/assets/architecture.mmd`, `render-architecture.sh`
- Modify: `CHANGELOG.md` (new entry only)

- [ ] **Step 1: Rename the asset and its references**

```bash
git mv docs/assets/agent-worklog-overview.png docs/assets/iiwi-overview.png
rg -l 'agent-worklog-overview' README.md README.zh-TW.md docs | xargs sed -i 's/agent-worklog-overview/iiwi-overview/g'
```

Both READMEs reference assets through `raw.githubusercontent.com/mike840609/agent-worklog/refs/heads/main/...`; repoint the owner path too.

- [ ] **Step 2: Regenerate the architecture diagram if it renders the name**

`architecture.mmd` feeds `architecture.svg` via `render-architecture.sh`. If the diagram labels the CLI, edit the `.mmd` and re-run the script noted at the top of that file — do not hand-edit the SVG.

- [ ] **Step 3: New CHANGELOG entry** (existing entries stay as written)

```markdown
## [0.9.0]

### Changed

- Renamed the project from Agent Worklog to Iiwi. The command is now `iiwi`,
  the distribution is `iiwi` on PyPI, environment variables use the `IIWI_`
  prefix, and settings, history and session-selection state move to the `iiwi`
  application directories. There is no compatibility alias — `agent-worklog`
  is not published beyond 0.8.x.
```

- [ ] **Step 4: Close out the old PyPI project**

Publish a final `agent-worklog` `0.8.1` whose description says only that the project continues as `iiwi`, with the install command. **Do not yank the earlier releases** — yanking breaks pinned installs for anyone who already has it, and gains nothing.

- [ ] **Step 5: Commit** — `chore: rename assets and record the rename in the changelog`

---

### Task 8: Rename the GitHub repository (after merge)

Do this **last**, once the pull request has merged. Renaming mid-flight retargets the open PR's base and disturbs the branch.

- [ ] **Step 1:** Settings → Repository name → `iiwi`. GitHub redirects the old URLs, including clone URLs and raw asset paths, so nothing breaks immediately.
- [ ] **Step 2:** Update the local remote — `git remote set-url origin https://github.com/mike840609/iiwi`
- [ ] **Step 3:** Confirm the CI, Release and DeepWiki badges render on the repository front page. DeepWiki may need re-indexing under the new path.
- [ ] **Step 4:** Update the repository description and topics to match the new positioning.
- [ ] **Step 5:** Tag and release `0.9.0`, publishing `iiwi` to PyPI over the `0.8.1.dev0` placeholder from the prerequisites.

---

## Decisions needed before starting

**A — Version number for the first `iiwi` release.** Recommend continuing at **0.9.0**. The CHANGELOG history is real and the code is the same maturity; restarting at 0.1.0 would misrepresent it and read as a downgrade to anyone tracking the project.

**B — Migrate existing user state, or not?** The rename moves three directories: settings, report history, and per-period session-selection memory. With the old name they are simply abandoned — no error, no warning, the user just finds their settings gone. The stated position is that no existing users need backward compatibility, in which case do nothing and this is correct. If anyone may have installed `agent-worklog` 0.8.0 from PyPI, a one-time move at startup is roughly twenty lines and can be deleted after a release:

```python
# in each of config_store.py / history.py / state.py
if not new_path.exists() and (old := legacy_path()).exists():
    new_path.parent.mkdir(parents=True, exist_ok=True)
    old.rename(new_path)
```

Recommend **doing it** only if the PyPI download count for 0.8.0 is non-trivial; otherwise skip, consistent with the no-compatibility-layer rule.

**C — Does `# Engineering Worklog` stay in the generated report?** Recommend **yes**. It names the document the tool produces, which is still accurately a worklog, and it is the heading users paste into their own reports. Only the product is being renamed.

## Risks

| Risk | Mitigation |
|---|---|
| Partial `platformdirs` rename splits user state across two directories, silently | Task 2 changes all three literals in one commit; `rg 'user_(config\|data)_dir\("' src` to confirm |
| `update.py` left pointing at the old PyPI project — no visible symptom, wrong versions forever | Explicit step in Task 2; verify with `uv run iiwi update` |
| `--cov=agent_worklog` left in CI reports 0% and trips `--cov-fail-under=80` | Task 3 Step 2; CI catches it on the first push |
| Blind substitution rewrites the 15 dated plan documents, falsifying the record and tripling the diff | Every `rg`/`sed` in this plan carries `--glob '!docs/plans/**'` |
| `git mv` split from the import rewrite leaves an un-importable tree | Task 1 keeps them in one commit |
| Interactive menu box-drawing misaligns — `Iiwi` is nine characters shorter than `Agent Worklog` | Task 5 Step 4 runs the TUI and eyeballs the rule and footer |
| `iiwi` claimed on PyPI by someone else mid-rename | Prerequisite: upload a placeholder before Task 1 |
