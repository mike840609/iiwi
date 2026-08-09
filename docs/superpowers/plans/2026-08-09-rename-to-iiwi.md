# Rename Agent Worklog to Iiwi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the project from `agent-worklog` to `iiwi` across the package, runtime identity, packaging, CI, documentation and assets, adopting state left behind by the old name.

**Architecture:** Task 1 is one mechanical rename covering code, packaging, CI, documentation and the documentation tests — these cannot be split, because `pyproject.toml`'s `name` is what tells hatchling where the package lives, and `tests/unit/test_documentation.py` compares `setting_keys()` (derived from `ENV_PREFIX`) against variable names parsed out of `docs/configuration.md`. Task 2 adds the only new behaviour, a one-time adoption of settings, history and session-selection state from the old application directories, built test-first. Task 3 renames assets and records the change. Historical records are deliberately not rewritten.

**Tech Stack:** Python 3.11+, hatchling, uv, typer, pydantic-settings, platformdirs, Jinja2, pytest, ruff, pyright, GitHub Actions.

## Global Constraints

- Working directory `/Users/chuntsai/Projects/agent-worklog`, branch `rename-to-iiwi`. The spec is `docs/superpowers/specs/2026-08-09-rename-to-iiwi-design.md`.
- **Name forms, exact:** `agent-worklog` → `iiwi` (distribution, CLI, URLs, application directories) · `agent_worklog` → `iiwi` (Python package, imports, coverage target) · `Agent Worklog` → `Iiwi` (prose) · `AGENT_WORKLOG_` → `IIWI_` (environment prefix) · `AgentWorklogError` → `IiwiError`.
- **This is macOS. `sed -i` will not work.** BSD `sed` requires a backup-suffix argument and fails on the GNU form. Every substitution in this plan uses `perl -pi -e`. Do not substitute `sed`.
- **No backward compatibility beyond state adoption.** No `agent-worklog` console-script alias, no shim package, no dual environment-prefix support, no deprecated import path.
- **Version stays `0.8.0` in `pyproject.toml`.** The next release will be `0.9.0`; this branch does not bump it.
- **Do not rename:** `output_directory: Path("reports")`; harness identifiers `opencode`, `codex`, `claude_code`; `# Engineering Worklog` in `src/iiwi/templates/worklog.md.j2`; the generated filename pattern `worklog-<dates>.md` in `cli.py:155`; the template filename `worklog.md.j2`.
- **Frozen records — never substitute inside these:** `docs/plans/**`, `CHANGELOG.md`'s existing entries, `docs/superpowers/**`, and these thirteen files directly under `docs/`: `mvp-design.md`, `p0-interactive-ux-implementation-plan.md`, `p0-interactive-ux-design.md`, `interactive-menu-design.md`, `opencode-sanitize-default-design.md`, `opencode-run-report-engine-design.md`, `v0.4.0-release-design.md`, `claude-code-adapter-design.md`, `codex-adapter-design.md`, `main-menu-version-design.md`, `cli-progress-feedback-design.md`, `2026-08-08-session-density-design.md`, `report-scan-detail-levels-design.md`.
- **The seven living documents** — the only files under `docs/` that get renamed: `docs/configuration.md`, `docs/guides.md`, `docs/privacy.md`, `docs/releasing.md`, `docs/cli-reference.md`, `docs/limitations.md`, `docs/usage-statistics.md`.
- **Verification gate, run after every task:**
  ```bash
  uv run pytest --cov=iiwi --cov-fail-under=80
  uv run ruff check .
  uv run pyright
  ```
- **No PyPI credentials are needed anywhere in this plan.** Claiming the name happens at release time, outside this branch.

---

### Task 1: The mechanical rename

**Files:**
- Move: `src/agent_worklog/` → `src/iiwi/` (16 directories, ~60 modules)
- Modify: every file under `src/` and `tests/` containing the old name (~130 files)
- Modify: `pyproject.toml:2`, `:4`, `:34`
- Modify: `.github/workflows/ci.yml:38`, `.github/workflows/release.yml:36`
- Modify: `.codex/environments/environment.toml:3`, `:14`
- Modify: `README.md`, `README.zh-TW.md`, `SECURITY.md`, and the seven living documents
- Modify: `uv.lock` (regenerated)
- Test: `tests/unit/test_documentation.py`

**Interfaces:**
- Produces: the `iiwi` import root, the `IIWI_` environment prefix, `IiwiError`, the `iiwi` console script, and `iiwi` application directories. Every later task depends on all of it.
- Consumes: nothing.

This whole task is one commit. Three separate constraints force it:

1. `git mv` without the import rewrite leaves a tree that cannot import.
2. `pyproject.toml` has no `[tool.hatch.build]` section, so hatchling infers the package directory from `name = "agent-worklog"`. Rename the directory without renaming the project and `uv sync` can no longer find the package.
3. `tests/unit/test_documentation.py:132-137` builds `known` from `setting_keys()`, which derives from `config_store.ENV_PREFIX`, and builds `documented` by regex over `docs/configuration.md`. Change the prefix without the document and the two sets stop matching.

There is no new behaviour here. The existing test suite is the correctness check.

- [ ] **Step 1: Move the package**

```bash
git mv src/agent_worklog src/iiwi
```

- [ ] **Step 2: Rewrite src and tests**

One pass, five substitutions. They are independent — no substitution can consume another's input — so the order is cosmetic.

```bash
rg -l -i 'agent[-_ ]?worklog' src tests | xargs perl -pi -e '
  s/\bagent_worklog\b/iiwi/g;
  s/AGENT_WORKLOG_/IIWI_/g;
  s/\bAgentWorklogError\b/IiwiError/g;
  s/agent-worklog/iiwi/g;
  s/Agent Worklog/Iiwi/g;
'
```

This reaches things a package-only rewrite would miss, including:

| Site | Was |
|---|---|
| `tests/conftest.py:25-27` | the autouse fixture setting `AGENT_WORKLOG_CONFIG_FILE`, `_HISTORY_FILE`, `_STATE_FILE` |
| `tests/conftest.py` | fixture git remotes `git@github.com:mike/agent-worklog.git` and the directory `-repo-agent-worklog` |
| `src/iiwi/history.py:17`, `state.py:23` | `HISTORY_FILE_VARIABLE`, `STATE_FILE_VARIABLE` |
| `src/iiwi/cli.py:171` | f-string `AGENT_WORKLOG_HARNESSES__{harness.name}__ENABLED` |
| `src/iiwi/interactive/cli_actions.py:221,226,239` | environment name and the `agent-worklog config unset` hint |
| `src/iiwi/summarizers/opencode_run.py:183`, `security/secure_files.py:19` | temp-directory prefixes |

The conftest fixture is the one that fails quietly if missed: it redirects the three state files away from the developer's real machine paths, and a stale name would silently point the suite at real user state.

- [ ] **Step 3: Confirm git recorded renames, not delete-plus-add**

```bash
git add -A src tests
git diff --cached -M --stat | tail -5
rg -i 'agent[-_ ]?worklog' src tests
```

Expected: the stat summary shows renames; the `rg` returns nothing.

- [ ] **Step 4: Set the application directories**

The three `platformdirs` calls now read `user_config_dir("iiwi")` and `user_data_dir("iiwi")` from Step 2. Confirm all three changed — a partial rename splits user state across two directories with no error surfaced:

```bash
rg -n 'user_(config|data)_dir\(' src
```

Expected exactly three lines: `config_store.py:32`, `history.py:42`, `state.py:32`, each with `"iiwi"`.

- [ ] **Step 5: Verify the update check points at the new project**

```bash
rg -n 'pypi.org|pipx upgrade|User-Agent' src/iiwi/update.py
```

Expected:

```python
LATEST_URL = "https://pypi.org/pypi/iiwi/json"
UPGRADE_COMMAND = "pipx upgrade iiwi"
headers={"User-Agent": f"iiwi/{current_version()} (version check)"},
```

Left pointing at the old project this has no visible symptom — it polls an abandoned entry and reports wrong versions forever. `iiwi` does not exist on PyPI yet, so the endpoint returns 404 until 0.9.0 ships; `urlopen` raises `HTTPError`, a subclass of `OSError`, which `update.py` already handles.

- [ ] **Step 6: Packaging**

Edit `pyproject.toml`:

```toml
[project]
name = "iiwi"
version = "0.8.0"
description = "Agent Session Intelligence for engineering work"
```

```toml
[project.scripts]
iiwi = "iiwi.cli:app"
```

Leave `version`, `[build-system]`, `[tool.pytest.ini_options]`, `[tool.ruff]` and `[tool.pyright]` untouched.

- [ ] **Step 7: CI and the Codex environment**

`.github/workflows/ci.yml:38` and `.github/workflows/release.yml:36`:

```yaml
uv run pytest --cov=iiwi --cov-fail-under=80
```

`.codex/environments/environment.toml`:

```toml
name = "Iiwi"
```
```toml
command = "uv run pytest --cov=iiwi --cov-fail-under=80"
```

`--cov=agent_worklog` left in place measures a package that no longer exists, reports 0%, and trips the 80% gate.

- [ ] **Step 8: Regenerate the lockfile and confirm the tree installs**

```bash
uv lock
uv sync --extra dev
uv run iiwi --version
```

Expected: `uv run iiwi --version` prints `0.8.0`. If `uv sync` reports it cannot find the package, `pyproject.toml`'s `name` and the `src/` directory disagree — recheck Steps 1 and 6.

- [ ] **Step 9: Rewrite the READMEs, SECURITY.md and the seven living documents**

The file list is explicit. Do not glob `docs/` — that would rewrite the frozen records.

```bash
perl -pi -e '
  s/\bagent_worklog\b/iiwi/g;
  s/AGENT_WORKLOG_/IIWI_/g;
  s/agent-worklog/iiwi/g;
  s/Agent Worklog/Iiwi/g;
' README.md README.zh-TW.md SECURITY.md \
  docs/configuration.md docs/guides.md docs/privacy.md docs/releasing.md \
  docs/cli-reference.md docs/limitations.md docs/usage-statistics.md
```

Note this rewrites `github.com/mike840609/agent-worklog` to `github.com/mike840609/iiwi` in the badge and link URLs on lines 3–10 of both READMEs, which is what we want — the repository is renamed after this branch merges, and GitHub redirects until then.

It also rewrites `docs/assets/agent-worklog-overview.png` references to `iiwi-overview.png`. The file itself is renamed in Task 3, so the READMEs point at a missing image between now and then. That is a documentation link, not a test dependency, and nothing in the suite loads it.

- [ ] **Step 10: Add the pronunciation line to both READMEs**

The name is not guessable from its spelling; without this it fails in conversation. Insert directly below the `# Iiwi` H1 and above the badges in `README.md`:

```markdown
# Iiwi

Iiwi · /ˈiː.wiː/ "ee-wee" — Agent Session Intelligence for engineering work

Probe coding-agent sessions. Surface the work that matters.

The ʻiʻiwi is a scarlet Hawaiian honeycreeper whose long curved bill reaches
nectar others cannot. This project uses the anglicised pronunciation.
```

And in `README.zh-TW.md`:

```markdown
# Iiwi

Iiwi · /ˈiː.wiː/ "ee-wee" — 為工程工作而生的 Agent Session Intelligence

探測 coding-agent 工作階段，浮現真正重要的工作。

ʻiʻiwi 是夏威夷的緋紅色旋蜜雀，彎長的喙能探到其他鳥觸及不了的花蜜。
本專案採用英語化的發音。
```

- [ ] **Step 11: Read `docs/releasing.md` end to end**

It describes the release procedure by name and by command. A substitution cannot tell whether a sentence still reads correctly. Read it once and fix any sentence the rewrite left awkward.

- [ ] **Step 12: Review what the substitution did to the documentation tests**

`tests/unit/test_documentation.py` was rewritten by Step 2 along with everything else in `tests/`. Its assertions now read `pipx install iiwi`, `iiwi doctor`, `IIWI_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY` and so on, matching the documents rewritten in Step 9. Read the file and confirm each assertion is asserting something real rather than something vacuous.

One test needs hardening. `test_every_variable_in_the_configuration_doc_is_a_real_setting` asserts `documented <= known`, which passes trivially when `documented` is empty — exactly what would happen if `docs/configuration.md` had been missed. Its sibling test already guards against this; this one does not. Add the guard:

```python
    configuration = Path("docs/configuration.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"IIWI_[A-Z0-9_]+", configuration))
    known = {setting.variable for setting in setting_keys()}
    known.add("IIWI_CONFIG_FILE")

    assert documented, "no documented variables found; the pattern stopped matching"
    assert documented <= known, f"documented but not settable: {documented - known}"
```

- [ ] **Step 13: Add the pronunciation regression test**

The pronunciation line is the mitigation for the name's one real weakness and should not silently disappear. Append to `tests/unit/test_documentation.py`:

```python
def test_readmes_state_the_pronunciation() -> None:
    for path in ("README.md", "README.zh-TW.md"):
        assert "ee-wee" in Path(path).read_text(encoding="utf-8")
```

- [ ] **Step 14: Run the full gate**

```bash
uv run pytest --cov=iiwi --cov-fail-under=80
uv run ruff check .
uv run pyright
```

Expected: all pass. If `test_readme_documents_release_gate_commands` fails, Step 9 missed a README. If `test_every_variable_in_the_configuration_doc_is_a_real_setting` fails on the new guard, `docs/configuration.md` was not rewritten.

- [ ] **Step 15: Eyeball the interactive menu**

```bash
uv run iiwi
```

Expected: the bold title reads `Iiwi` with the version right-aligned, the rule spans the full terminal width, and the footer hints are intact. Press `q` to exit. Resize the terminal narrow and re-run to exercise the fallback branch at `render.py:400`, which carries a second copy of the title.

The title needs no re-padding despite being nine characters shorter: `render.py:386-390` computes padding from `console.size.width` and draws the rule as `_RULE_CHAR * console.size.width`.

- [ ] **Step 16: Run both sweeps**

```bash
rg -i --hidden -g '!.git/**' -g '!docs/**' -g '!CHANGELOG.md' -g '!uv.lock' \
  'agent[-_ ]?worklog' .

rg -i 'agent[-_ ]?worklog' docs/configuration.md docs/guides.md docs/privacy.md \
  docs/releasing.md docs/cli-reference.md docs/limitations.md docs/usage-statistics.md
```

Both must return nothing. The first excludes `docs/` wholesale; the second names the seven living documents, so the frozen records stay out of scope by construction.

`--hidden` is not optional. Without it `rg` skips dotted directories, and `.github/workflows/` and `.codex/` — the two places a leftover `--cov=agent_worklog` would hide — are never searched. `-g '!.git/**'` is what keeps `--hidden` from flooding the output with reflog and worktree metadata, which carries the old name permanently and correctly.

- [ ] **Step 17: Commit**

```bash
git add -A
git commit -m "refactor: rename the project from agent-worklog to iiwi"
```

---

### Task 2: Adopt state left by the old name

**Files:**
- Create: `src/iiwi/paths.py`
- Create: `tests/unit/test_paths.py`
- Modify: `src/iiwi/config_store.py:32`
- Modify: `src/iiwi/history.py:42`
- Modify: `src/iiwi/state.py:32`

**Interfaces:**
- Consumes: the `iiwi` import root and the `iiwi` application directories from Task 1.
- Produces: `iiwi.paths.adopt_legacy(new_path: Path, legacy_path: Path) -> Path`. Returns `new_path` in every case. No later task depends on it.

`agent-worklog` 0.8.0 is live on PyPI with ten releases and roughly a thousand downloads a month. That number is probably dominated by mirrors, but it cannot be distinguished from real installs, and the costs are asymmetric: this is one function and three call sites, deletable in one release, while being wrong means a user silently loses their settings and history with no error and no warning.

All three path resolvers share one shape — an environment override first, then a `platformdirs` default. **Only the default branch is wrapped.** Every existing test of these three functions goes through the override (see the autouse fixture in `tests/conftest.py`), so a migration firing ahead of the override check would corrupt the entire suite in a way that looks like an unrelated failure.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_paths.py`:

```python
"""Adoption of state written under the pre-rename name."""

from __future__ import annotations

from pathlib import Path

import pytest

from iiwi.paths import adopt_legacy


def _fail_if_called(*args: object, **kwargs: object) -> Path:
    raise AssertionError("adoption ran despite an explicit override")


def test_moves_legacy_file_when_the_new_one_is_absent(tmp_path: Path) -> None:
    legacy = tmp_path / "agent-worklog" / "history.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("kept\n", encoding="utf-8")
    new = tmp_path / "iiwi" / "history.jsonl"

    assert adopt_legacy(new, legacy) == new
    assert new.read_text(encoding="utf-8") == "kept\n"
    assert not legacy.exists()


def test_keeps_the_new_file_when_both_exist(tmp_path: Path) -> None:
    legacy = tmp_path / "agent-worklog" / "history.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("old\n", encoding="utf-8")
    new = tmp_path / "iiwi" / "history.jsonl"
    new.parent.mkdir(parents=True)
    new.write_text("current\n", encoding="utf-8")

    adopt_legacy(new, legacy)

    assert new.read_text(encoding="utf-8") == "current\n"
    assert legacy.read_text(encoding="utf-8") == "old\n"


def test_does_nothing_when_there_is_no_legacy_file(tmp_path: Path) -> None:
    legacy = tmp_path / "agent-worklog" / "history.jsonl"
    new = tmp_path / "iiwi" / "history.jsonl"

    assert adopt_legacy(new, legacy) == new
    assert not new.exists()
    assert not new.parent.exists()


def test_is_idempotent(tmp_path: Path) -> None:
    legacy = tmp_path / "agent-worklog" / "config.env"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("kept\n", encoding="utf-8")
    new = tmp_path / "iiwi" / "config.env"

    adopt_legacy(new, legacy)
    adopt_legacy(new, legacy)

    assert new.read_text(encoding="utf-8") == "kept\n"


@pytest.mark.parametrize(
    ("module", "resolver", "directory_function", "filename"),
    [
        ("iiwi.config_store", "config_file_path", "user_config_dir", "config.env"),
        ("iiwi.history", "history_file_path", "user_data_dir", "history.jsonl"),
        ("iiwi.state", "state_file_path", "user_data_dir", "state.json"),
    ],
)
def test_each_resolver_adopts_its_legacy_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module: str,
    resolver: str,
    directory_function: str,
    filename: str,
) -> None:
    """The autouse fixture sets the override, so clear it to reach the real branch."""

    import importlib

    for variable in ("IIWI_CONFIG_FILE", "IIWI_HISTORY_FILE", "IIWI_STATE_FILE"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(
        importlib.import_module(module),
        directory_function,
        lambda name: str(tmp_path / name),
    )

    legacy = tmp_path / "agent-worklog" / filename
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("kept\n", encoding="utf-8")

    resolved = getattr(importlib.import_module(module), resolver)()

    assert resolved == tmp_path / "iiwi" / filename
    assert resolved.read_text(encoding="utf-8") == "kept\n"
    assert not legacy.exists()


@pytest.mark.parametrize(
    ("module", "resolver", "variable"),
    [
        ("iiwi.config_store", "config_file_path", "IIWI_CONFIG_FILE"),
        ("iiwi.history", "history_file_path", "IIWI_HISTORY_FILE"),
        ("iiwi.state", "state_file_path", "IIWI_STATE_FILE"),
    ],
)
def test_the_override_wins_and_attempts_no_move(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module: str,
    resolver: str,
    variable: str,
) -> None:
    import importlib

    override = tmp_path / "explicit" / "file"
    monkeypatch.setenv(variable, str(override))
    monkeypatch.setattr(
        importlib.import_module(module),
        "adopt_legacy",
        _fail_if_called,
    )

    assert getattr(importlib.import_module(module), resolver)() == override
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/unit/test_paths.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'iiwi.paths'`.

- [ ] **Step 3: Write the implementation**

Create `src/iiwi/paths.py`:

```python
"""Adoption of state written under the name this project had before the rename.

Delete this module and its three call sites one release after 0.9.0. It exists
only so that an installed `agent-worklog` does not silently lose its settings,
history and session-selection memory.
"""

from __future__ import annotations

from pathlib import Path

LEGACY_APP_NAME = "agent-worklog"


def adopt_legacy(new_path: Path, legacy_path: Path) -> Path:
    """Move state written under the old name, then return the new path.

    Both paths live under the same user directory, so the rename never crosses
    a filesystem. The existence guard makes the call idempotent and means an
    already-migrated file always wins over a stale legacy one.
    """

    if not new_path.exists() and legacy_path.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        legacy_path.rename(new_path)
    return new_path
```

- [ ] **Step 4: Wire up the three call sites**

`src/iiwi/config_store.py` — add the import beside the existing ones and replace the final `return`:

```python
from iiwi.paths import LEGACY_APP_NAME, adopt_legacy
```

```python
    return adopt_legacy(
        Path(user_config_dir("iiwi")) / "config.env",
        Path(user_config_dir(LEGACY_APP_NAME)) / "config.env",
    )
```

`src/iiwi/history.py`:

```python
from iiwi.paths import LEGACY_APP_NAME, adopt_legacy
```

```python
    return adopt_legacy(
        Path(user_data_dir("iiwi")) / "history.jsonl",
        Path(user_data_dir(LEGACY_APP_NAME)) / "history.jsonl",
    )
```

`src/iiwi/state.py`:

```python
from iiwi.paths import LEGACY_APP_NAME, adopt_legacy
```

```python
    return adopt_legacy(
        Path(user_data_dir("iiwi")) / "state.json",
        Path(user_data_dir(LEGACY_APP_NAME)) / "state.json",
    )
```

Leave the `override` branch above each of these exactly as it is. `paths.py` imports nothing from the project, so none of these creates an import cycle.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_paths.py -v
```

Expected: all pass.

- [ ] **Step 6: Run the full gate**

```bash
uv run pytest --cov=iiwi --cov-fail-under=80
uv run ruff check .
uv run pyright
```

Expected: all pass. A failure in `tests/unit/test_config_store.py`, `test_history.py` or `test_state.py` means the adoption was placed above the override check rather than below it.

- [ ] **Step 7: Commit**

```bash
git add src/iiwi/paths.py tests/unit/test_paths.py \
  src/iiwi/config_store.py src/iiwi/history.py src/iiwi/state.py
git commit -m "feat: adopt settings, history and state left by the old name"
```

---

### Task 3: Assets and changelog

**Files:**
- Move: `docs/assets/agent-worklog-overview.png` → `docs/assets/iiwi-overview.png`
- Review: `docs/assets/architecture.mmd`, `docs/assets/render-architecture.sh`
- Modify: `CHANGELOG.md` (new entry only)

**Interfaces:**
- Consumes: the README image references already rewritten in Task 1 Step 9.
- Produces: nothing. This task is presentational and editorial.

- [ ] **Step 1: Rename the asset**

```bash
git mv docs/assets/agent-worklog-overview.png docs/assets/iiwi-overview.png
```

The READMEs already point at `iiwi-overview.png` — Task 1 Step 9 rewrote the references. Confirm no reference is left dangling:

```bash
rg -n 'iiwi-overview|agent-worklog-overview' README.md README.zh-TW.md docs
ls docs/assets/
```

Expected: every hit reads `iiwi-overview.png`, and that file exists.

- [ ] **Step 2: Check whether the architecture diagram carries the name**

```bash
rg -i 'agent[-_ ]?worklog' docs/assets/architecture.mmd docs/assets/render-architecture.sh
```

If either returns nothing, skip to Step 3. If the `.mmd` labels the CLI, edit the `.mmd` and regenerate:

```bash
head -5 docs/assets/render-architecture.sh   # read the invocation it documents
bash docs/assets/render-architecture.sh
```

Never hand-edit `architecture.svg`; it is generated.

- [ ] **Step 3: Add the changelog entry**

Insert at the top of `CHANGELOG.md`, above the existing `0.8.0` entry. Existing entries stay exactly as written — rewriting dated records would falsify them.

```markdown
## [0.9.0]

### Changed

- Renamed the project from Agent Worklog to Iiwi. The command is now `iiwi`,
  the distribution is `iiwi` on PyPI, environment variables use the `IIWI_`
  prefix, and settings, history and session-selection state move to the `iiwi`
  application directories. State left by the previous name is adopted
  automatically on first run. There is no compatibility alias — `agent-worklog`
  is not published beyond 0.8.x.
```

- [ ] **Step 4: Run the full gate and both sweeps**

```bash
uv run pytest --cov=iiwi --cov-fail-under=80
uv run ruff check .
uv run pyright

rg -i --hidden -g '!.git/**' -g '!docs/**' -g '!CHANGELOG.md' -g '!uv.lock' \
  'agent[-_ ]?worklog' .
rg -i 'agent[-_ ]?worklog' docs/configuration.md docs/guides.md docs/privacy.md \
  docs/releasing.md docs/cli-reference.md docs/limitations.md docs/usage-statistics.md
```

Expected: gate passes, both sweeps return nothing.

- [ ] **Step 5: Verify the built artifact**

```bash
uv build
python -c "import zipfile,glob; print(sorted({n.split('/')[0] for n in zipfile.ZipFile(sorted(glob.glob('dist/*.whl'))[-1]).namelist()}))"
uv run iiwi doctor
rm -rf dist
```

Expected: the wheel's top-level entries are `iiwi` and a `*.dist-info` directory, and `iiwi doctor` runs.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: rename the overview asset and record the rename"
```

---

## After the branch merges

None of this belongs on the branch. Do it in order — renaming the repository while the pull request is open retargets its base and disturbs the branch.

- [ ] Settings → Repository name → `iiwi`. GitHub redirects the old URLs, including clone and raw asset paths.
- [ ] `git remote set-url origin https://github.com/mike840609/iiwi`
- [ ] Confirm the CI, Release, PyPI and DeepWiki badges render on the front page. DeepWiki may need re-indexing under the new path.
- [ ] Update the repository description and topics to the new positioning.
- [ ] **Register the PyPI pending publisher.** Trusted publishing has no project to authenticate against until `iiwi` exists on PyPI, so without this the publish job in `release.yml` fails outright. Project name `iiwi`, repository `mike840609/iiwi`, workflow `release.yml`, environment `pypi`. It must name the repository as it is called at that moment — the OIDC claim carries the current name and GitHub's redirect does not rewrite it.
- [ ] Bump `pyproject.toml` to `version = "0.9.0"`, tag `v0.9.0` and push. This upload is what claims the name on PyPI.
- [ ] Publish a final `agent-worklog` 0.8.1 whose description says only that the project continues as `iiwi`, with the install command. **Do not yank the earlier releases** — yanking breaks pinned installs for anyone who already has them and gains nothing.

## Risks

| Risk | Mitigation |
|---|---|
| A partial application-directory rename splits user state silently | Task 1 Step 4 asserts exactly three `platformdirs` call sites, all reading `"iiwi"` |
| `tests/conftest.py`'s autouse fixture keeps the old variable names and the suite reads the developer's real state | Task 1 Step 2 substitutes `AGENT_WORKLOG_` across all of `tests/`; Step 3's sweep confirms |
| `update.py` left pointing at the old PyPI project — wrong versions forever, no symptom | Task 1 Step 5 checks all three literals explicitly |
| `--cov=agent_worklog` left in CI reports 0% and trips the 80% gate | Task 1 Step 7; CI catches it on the first push |
| `pyproject.toml`'s `name` left behind, so hatchling cannot find the moved package | Task 1 Step 8 runs `uv sync` and `uv run iiwi --version` before anything else depends on it |
| Blind substitution rewrites the 28 frozen records | Every substitution names its files; none globs `docs/` |
| A GNU-flavoured `sed -i` from an older runbook fails on macOS | Every command here uses `perl -pi -e`; called out in Global Constraints |
| Adoption fires ahead of the environment override and corrupts the suite | Only the `platformdirs` branch is wrapped; `test_the_override_wins_and_attempts_no_move` fails loudly if it moves |
| `test_every_variable_in_the_configuration_doc_is_a_real_setting` passes vacuously on an empty match set | Task 1 Step 12 adds the missing non-empty guard |
| `iiwi` claimed on PyPI by someone else before 0.9.0 ships | Accepted; exposure ends at release. Upload a `0.8.1.dev0` placeholder with a temporary token only if the branch will sit for a month or more |
