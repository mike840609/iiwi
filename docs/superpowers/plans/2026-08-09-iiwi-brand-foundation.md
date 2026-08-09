# Iiwi Brand Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the current Agent Worklog package and public product surface cleanly to **Iiwi** for release `0.9.0`, with no compatibility layer and no change to scan/report behavior.

**Architecture:** Treat the rename as four bounded identity surfaces: package/import identity, runtime/config/data identity, CLI/user-visible identity, and distribution/docs/release identity. Change each surface behind tests, keep the existing service graph intact, then add a stale-brand guard and run the complete release verification gate.

**Tech Stack:** Python 3.11+, Typer, Rich, Pydantic Settings, platformdirs, pytest, Ruff, Pyright, Hatchling, uv, GitHub Actions, PyPI Trusted Publishing.

## Global Constraints

- Product display name is `Iiwi`; technical identifier is `iiwi`.
- Bird spelling `ʻIʻiwi` is used only in explanatory brand copy; source paths, package names, commands, URLs, and environment variables stay ASCII.
- First Iiwi release is `0.9.0`.
- Distribution, CLI, and Python package are all exactly `iiwi`.
- Environment prefix is exactly `IIWI_` with `__` as the nested delimiter.
- Override variables are exactly `IIWI_CONFIG_FILE`, `IIWI_HISTORY_FILE`, and `IIWI_STATE_FILE`.
- platformdirs application name is exactly `iiwi`.
- No legacy aliases, import shims, config migration, old-variable fallback, dual-data-directory lookup, or compatibility publication is added.
- Core scan, repository-resolution, evidence-selection, summarization, redaction, and report-generation behavior must not be refactored in this phase.
- Current product copy may say `Agent Session Intelligence for engineering work`, but must not claim search, memory, RAG, dashboards, alerts, or other unimplemented platform features.
- Historical `docs/plans/**`, historical design documents, and old changelog history are not rewritten as if they had always used Iiwi.
- `.superpowers/` remains ignored and uncommitted; specs and plans live under `docs/superpowers/`.
- Full test coverage remains at least 80%.

---

## File map

The implementation intentionally follows existing file responsibilities.

- `pyproject.toml`: distribution metadata and console entry point.
- `uv.lock`: locked editable project identity/version after `uv lock`.
- `src/iiwi/**`: renamed package tree; no architectural reshuffle.
- `src/iiwi/errors.py`: Iiwi-branded base error type.
- `src/iiwi/config.py`, `config_store.py`: environment prefix and config location.
- `src/iiwi/history.py`, `state.py`: Iiwi-owned local data locations.
- `src/iiwi/update.py`: Iiwi PyPI index, user agent, and upgrade command.
- `src/iiwi/cli.py`, `interactive/render.py`, `interactive/controller.py`: public CLI and terminal identity.
- `tests/**`: imports renamed mechanically plus focused identity/runtime tests.
- `tests/unit/test_brand_identity.py`: one current-surface guard against accidental old-brand strings.
- `README.md`, `README.zh-TW.md`, `SECURITY.md`, current `docs/*.md`: current public and operational copy.
- `.github/workflows/ci.yml`, `.github/workflows/release.yml`: coverage/build identity.
- `docs/releasing.md`: Trusted Publisher and release recovery commands for `iiwi`.
- `CHANGELOG.md`: one new rename entry under Unreleased; existing historical bullets remain intact unless they describe the current unreleased command and therefore need to be accurate for 0.9.0.

---

### Task 1: Rename the distribution and Python package identity

**Files:**
- Create by rename: `src/iiwi/**` from `src/agent_worklog/**`
- Delete by rename: `src/agent_worklog/**`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/iiwi/__init__.py`
- Modify: `src/iiwi/errors.py`
- Modify: every current source/test import that starts with `agent_worklog`
- Modify: `tests/unit/test_version.py`
- Create: `tests/unit/test_brand_identity.py`

**Interfaces:**
- Consumes: existing public modules and existing test suite.
- Produces: import package `iiwi`, version `iiwi.__version__ == "0.9.0"`, base error `IiwiError`, and console-script metadata consumed by later tasks.

- [ ] **Step 1: Add failing package-identity tests before moving source files**

Create `tests/unit/test_brand_identity.py` with the first identity assertions:

```python
import importlib.util
import tomllib
from pathlib import Path


def _project() -> dict[str, object]:
    return tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))


def test_distribution_and_console_script_are_iiwi_only() -> None:
    project = _project()["project"]
    assert project["name"] == "iiwi"
    assert project["version"] == "0.9.0"
    assert project["scripts"] == {"iiwi": "iiwi.cli:app"}


def test_only_iiwi_import_package_exists() -> None:
    assert importlib.util.find_spec("iiwi") is not None
    assert importlib.util.find_spec("agent" + "_worklog") is None
```

Update `tests/unit/test_version.py` to import Iiwi:

```python
import tomllib
from pathlib import Path

import iiwi


def test_runtime_version_matches_project_metadata() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert iiwi.__version__ == project["project"]["version"] == "0.9.0"
```

- [ ] **Step 2: Run the focused tests and verify they fail for the old identity**

Run:

```bash
uv run pytest tests/unit/test_brand_identity.py tests/unit/test_version.py -q
```

Expected: FAIL because `pyproject.toml` still names `agent-worklog` and the `iiwi` package does not yet exist.

- [ ] **Step 3: Perform the mechanical package rename and metadata update**

Use Git-aware moves so history follows the package:

```bash
git mv src/agent_worklog src/iiwi
```

Update `pyproject.toml` exactly to:

```toml
[project]
name = "iiwi"
version = "0.9.0"
description = "Agent Session Intelligence for engineering work"

[project.scripts]
iiwi = "iiwi.cli:app"
```

Preserve all existing dependency and tool configuration blocks unchanged.

In `src/iiwi/__init__.py` use:

```python
"""Iiwi package."""

__version__ = "0.9.0"
```

Rename the error base in `src/iiwi/errors.py`:

```python
class IiwiError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(IiwiError):
    ...
```

Make `HarnessSourceError`, `ReportOutputError`, and `NoSessionsError` inherit from `IiwiError`; preserve the existing subclass graph below them. Update `src/iiwi/update.py`, `src/iiwi/interactive/controller.py`, and any other imports/usages of the old error class to `IiwiError`.

Mechanically replace imports across `src/iiwi/**`, `tests/**`, and non-historical tooling from `agent_worklog` to `iiwi`. Do not rename generic fixture data such as a repository display name that intentionally models a repository called `agent-worklog`; only current application identity/imports are in scope.

- [ ] **Step 4: Regenerate the lock file**

Run:

```bash
uv lock
```

Verify the editable project block in `uv.lock` now begins with:

```toml
[[package]]
name = "iiwi"
version = "0.9.0"
source = { editable = "." }
```

- [ ] **Step 5: Run package-identity tests**

Run:

```bash
uv run pytest tests/unit/test_brand_identity.py tests/unit/test_version.py -q
```

Expected: PASS.

- [ ] **Step 6: Run import-level smoke tests before proceeding**

Run:

```bash
uv run python -c 'import iiwi; print(iiwi.__version__)'
uv run python -c 'from iiwi.cli import app; print(type(app).__name__)'
```

Expected output includes `0.9.0`; both commands exit 0.

- [ ] **Step 7: Commit the package identity slice**

```bash
git add pyproject.toml uv.lock src tests/unit/test_brand_identity.py tests/unit/test_version.py tests/conftest.py
git commit -m "refactor: rename package to iiwi"
```

---

### Task 2: Rename runtime configuration, data directories, and update identity

**Files:**
- Modify: `src/iiwi/config.py`
- Modify: `src/iiwi/config_store.py`
- Modify: `src/iiwi/history.py`
- Modify: `src/iiwi/state.py`
- Modify: `src/iiwi/cli.py`
- Modify: `src/iiwi/update.py`
- Modify: `tests/conftest.py`
- Modify: `tests/unit/test_config.py`
- Modify: `tests/unit/test_config_store.py`
- Modify: `tests/unit/test_history.py`
- Modify: `tests/unit/test_state.py`
- Modify: `tests/unit/test_update.py`
- Modify: runtime-related cases in `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: package `iiwi` from Task 1.
- Produces: only `IIWI_*` settings, Iiwi-owned platformdirs paths, and update metadata for PyPI project `iiwi`.

- [ ] **Step 1: Change tests first to assert the new environment contract and old-prefix non-support**

In `tests/unit/test_config.py`, change configurable variables to `IIWI_*` and add:

```python
def test_old_environment_prefix_is_not_consumed(monkeypatch: pytest.MonkeyPatch) -> None:
    old_name = "AGENT_" + "WORKLOG_REPORT__TIMEZONE"
    monkeypatch.setenv(old_name, "UTC")
    monkeypatch.delenv("IIWI_REPORT__TIMEZONE", raising=False)

    settings = AppSettings()

    assert settings.report.timezone == "Asia/Taipei"
```

In `tests/unit/test_config_store.py`, assert:

```python
assert keys["harnesses.opencode.cli.model"].variable == (
    "IIWI_HARNESSES__OPENCODE__CLI__MODEL"
)
```

and update the default path test to:

```python
monkeypatch.delenv("IIWI_CONFIG_FILE", raising=False)
path = config_file_path()
assert path.name == "config.env"
assert "iiwi" in str(path)
```

Add direct path tests in `tests/unit/test_history.py` and `tests/unit/test_state.py` using monkeypatch of their override variables where needed; default path assertions must contain `iiwi` and the expected filename.

Update `tests/unit/test_update.py` to assert:

```python
def test_behind_installation_reports_update_and_upgrade_command() -> None:
    info = check_for_update(fetcher=_fetcher(_LATEST_JSON), current="0.8.0")
    assert info.update_available is True
    assert info.upgrade_command == "pipx upgrade iiwi"


def test_update_uses_the_iiwi_index() -> None:
    seen: list[str] = []
    check_for_update(
        fetcher=lambda url: seen.append(url) or json.dumps(_LATEST_JSON),
        current="0.9.0",
    )
    assert seen == ["https://pypi.org/pypi/iiwi/json"]
```

- [ ] **Step 2: Run the focused runtime tests and confirm they fail**

```bash
uv run pytest \
  tests/unit/test_config.py \
  tests/unit/test_config_store.py \
  tests/unit/test_history.py \
  tests/unit/test_state.py \
  tests/unit/test_update.py \
  -q
```

Expected: failures mentioning old `AGENT_WORKLOG_*`, old platformdirs app name, and old update command/index.

- [ ] **Step 3: Implement the Iiwi settings and local-data identity**

In `src/iiwi/config.py`:

```python
model_config = SettingsConfigDict(
    env_prefix="IIWI_",
    env_nested_delimiter="__",
    extra="ignore",
)
```

In `src/iiwi/config_store.py`:

```python
ENV_PREFIX = "IIWI_"
CONFIG_FILE_VARIABLE = "IIWI_CONFIG_FILE"
...
return Path(user_config_dir("iiwi")) / "config.env"
```

In `src/iiwi/history.py`:

```python
HISTORY_FILE_VARIABLE = "IIWI_HISTORY_FILE"
...
return Path(user_data_dir("iiwi")) / "history.jsonl"
```

In `src/iiwi/state.py`:

```python
STATE_FILE_VARIABLE = "IIWI_STATE_FILE"
...
return Path(user_data_dir("iiwi")) / "state.json"
```

In `src/iiwi/cli.py`, the disabled-harness hint must be constructed as:

```python
variable = f"IIWI_HARNESSES__{harness.name}__ENABLED"
```

Update `tests/conftest.py` autouse isolation fixture to set only:

```python
monkeypatch.setenv("IIWI_CONFIG_FILE", str(tmp_path / "config.env"))
monkeypatch.setenv("IIWI_HISTORY_FILE", str(tmp_path / "history.jsonl"))
monkeypatch.setenv("IIWI_STATE_FILE", str(tmp_path / "state.json"))
```

Do not set old aliases in the fixture.

- [ ] **Step 4: Implement Iiwi update metadata**

In `src/iiwi/update.py` set:

```python
LATEST_URL = "https://pypi.org/pypi/iiwi/json"
UPGRADE_COMMAND = "pipx upgrade iiwi"
```

and the request user agent to:

```python
headers={"User-Agent": f"iiwi/{current_version()} (version check)"}
```

Keep network timing, JSON parsing, version ordering, and exit behavior unchanged.

- [ ] **Step 5: Run the focused runtime suite**

```bash
uv run pytest \
  tests/unit/test_config.py \
  tests/unit/test_config_store.py \
  tests/unit/test_history.py \
  tests/unit/test_state.py \
  tests/unit/test_update.py \
  tests/unit/test_cli.py \
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit the runtime identity slice**

```bash
git add src/iiwi tests/conftest.py tests/unit
git commit -m "refactor: move runtime identity to iiwi"
```

---

### Task 3: Rename CLI and terminal-visible product identity

**Files:**
- Modify: `src/iiwi/cli.py`
- Modify: `src/iiwi/interactive/render.py`
- Modify: `src/iiwi/interactive/controller.py`
- Modify: any other current `src/iiwi/**` docstring/error/output containing the old display name
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/unit/interactive/test_render.py`
- Modify: relevant interactive/controller tests only where product identity is asserted

**Interfaces:**
- Consumes: `iiwi` package and runtime identity from Tasks 1-2.
- Produces: public `iiwi` CLI/help/version and terminal screens displaying `Iiwi`.

- [ ] **Step 1: Add failing user-visible identity assertions**

In `tests/unit/test_cli.py` add:

```python
def test_version_reports_iiwi_release() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.9.0" in result.stdout


def test_help_uses_iiwi_product_description() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Agent Session Intelligence" in result.stdout
```

Update `tests/unit/interactive/test_render.py` main-menu assertion from the old display name to:

```python
assert "Iiwi" in text
```

Also assert the first-screen supporting copy includes:

```python
assert "Probe coding-agent sessions" in text
```

- [ ] **Step 2: Run CLI/render tests and verify the brand assertions fail**

```bash
uv run pytest tests/unit/test_cli.py tests/unit/interactive/test_render.py -q
```

Expected: FAIL on old product copy while unrelated behavior tests remain green.

- [ ] **Step 3: Update current product strings without changing command behavior**

Set the Typer app help in `src/iiwi/cli.py` to:

```python
app = typer.Typer(
    help="Agent Session Intelligence for engineering work.",
)
```

Update current source module docstrings that identify the application from `Agent Worklog` to `Iiwi`.

In the interactive main screen, render:

```text
Iiwi
══════════════════════════════════════════════════════
Probe coding-agent sessions. Surface the work that matters.
```

Keep menu option names (`Generate Report`, `Browse Sessions`, `Check Setup`, `Settings`) and all navigation semantics unchanged.

Do not introduce mascot ASCII art or color-palette work in this task; that belongs to the later visual milestone.

- [ ] **Step 4: Search current source for old display identity and fix only live surfaces**

Run:

```bash
rg -n 'Agent Worklog|agent-worklog|agent_worklog|AGENT_WORKLOG' src/iiwi tests \
  --glob '!tests/fixtures/**'
```

For source files, every hit must be removed or deliberately converted to a test construction that verifies old identity is ignored. Fixture repository names/remote URLs that merely model a repository named `agent-worklog` may remain only if the test meaning depends on that fixture value; otherwise rename the fixture to neutral data such as `sample-app`.

- [ ] **Step 5: Run CLI and interactive suites**

```bash
uv run pytest tests/unit/test_cli.py tests/unit/interactive tests/acceptance -q
```

Expected: PASS with the same report/session behavior under Iiwi identity.

- [ ] **Step 6: Commit the public CLI slice**

```bash
git add src/iiwi tests
git commit -m "feat: brand the cli as Iiwi"
```

---

### Task 4: Rewrite current documentation, workflows, and release instructions

**Files:**
- Modify: `README.md`
- Modify: `README.zh-TW.md`
- Modify: `SECURITY.md`
- Modify: `docs/cli-reference.md`
- Modify: `docs/configuration.md`
- Modify: `docs/guides.md`
- Modify: `docs/privacy.md`
- Modify: `docs/limitations.md`
- Modify: `docs/usage-statistics.md`
- Modify: `docs/releasing.md`
- Modify: `CHANGELOG.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`
- Modify/rename current overview asset and its README reference if the filename embeds the old brand
- Modify: `tests/unit/test_documentation.py`
- Extend: `tests/unit/test_brand_identity.py`

**Interfaces:**
- Consumes: final command/runtime names from Tasks 1-3.
- Produces: current docs and automation that consistently install, run, test, and publish `iiwi`.

- [ ] **Step 1: Change documentation contract tests before editing prose**

Update the release-gate test to:

```python
def test_readme_documents_release_gate_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "pipx install iiwi" in readme
    assert "iiwi doctor" in readme
    assert "iiwi scan --period last-week" in readme
    assert "iiwi report --period last-week" in readme
```

Change the config-document variable regex and known override to `IIWI_` / `IIWI_CONFIG_FILE`:

```python
documented = set(re.findall(r"IIWI_[A-Z0-9_]+", configuration))
known = {setting.variable for setting in setting_keys()}
known.add("IIWI_CONFIG_FILE")
```

Change documented command extraction to match `iiwi config ...`.

Add README identity assertions:

```python
assert "# Iiwi" in readme
assert "Iiwi *(ee-EE-wee)*" in readme
assert "Agent Session Intelligence for engineering work" in readme
assert "Probe coding-agent sessions. Surface the work that matters." in readme
```

- [ ] **Step 2: Run documentation tests and confirm failure**

```bash
uv run pytest tests/unit/test_documentation.py tests/unit/test_brand_identity.py -q
```

Expected: FAIL because current docs/workflows still reference the old identity.

- [ ] **Step 3: Rewrite the two READMEs around the approved truthful positioning**

The English opening must communicate, in this order:

```markdown
# Iiwi

**Iiwi** *(ee-EE-wee)* — Agent Session Intelligence for engineering work.

**Probe coding-agent sessions. Surface the work that matters.**

Iiwi reads coding-agent sessions from OpenCode, Claude Code, and Codex, groups the work by
Git repository, selects and redacts useful evidence, and turns it into engineering reports.
```

The Traditional Chinese README should carry the same meaning without inventing additional platform capabilities.

Replace install/command examples with `iiwi`, PyPI badges with project `iiwi`, and future repository links with `mike840609/iiwi`. Prefer relative links for files inside the repository so the branch remains readable before the GitHub rename.

Rename a current overview asset path such as `docs/assets/agent-worklog-overview.png` to `docs/assets/iiwi-overview.png` if the asset is still used; update references. Do not recreate the artwork merely for Phase 1 unless visible text inside the image itself says the old brand.

- [ ] **Step 4: Update current operational docs and preserve technical claims**

Across the listed current docs:

- product references become `Iiwi`;
- commands become `iiwi ...`;
- environment examples become `IIWI_*`;
- config/data path examples use `iiwi`;
- repository URLs become `mike840609/iiwi`;
- privacy wording still states that `update` is the only operation that accesses the network;
- harness limitations and existing redaction caveats remain substantively unchanged.

Do not rewrite historical files under `docs/plans/**` or historical design docs for old changes.

In `CHANGELOG.md`, add the first Unreleased bullet:

```markdown
- Rename the project to **Iiwi**: the distribution, Python package, CLI, environment
  prefix, config/data directories, update index, documentation, and release flow now use
  `iiwi` / `IIWI_*`. No compatibility alias is provided because the project has no user
  migration requirement yet.
```

Update existing Unreleased bullets that literally document commands being shipped in 0.9.0, such as `agent-worklog --version`, to their `iiwi` form. Leave older released/history material intact.

- [ ] **Step 5: Update CI and release automation**

In `.github/workflows/ci.yml`:

```yaml
- name: Test with coverage
  run: uv run pytest --cov=iiwi --cov-fail-under=80
```

In `.github/workflows/release.yml`:

```yaml
- name: Verify package
  run: |
    uv run pytest --cov=iiwi --cov-fail-under=80
    uv run ruff check .
    uv run pyright
    uv build
    uv tool run twine check dist/*
```

Update `docs/releasing.md` Trusted Publisher values exactly to:

```text
PyPI project name: iiwi
GitHub owner: mike840609
Repository: iiwi
Workflow filename: release.yml
Environment: pypi
```

and all install/recovery commands to the new PyPI/repository identity.

- [ ] **Step 6: Add the stale-current-brand guard**

Extend `tests/unit/test_brand_identity.py` with a finite explicit list of live surfaces so historical records are intentionally outside the scan:

```python
CURRENT_TEXT_FILES = (
    Path("pyproject.toml"),
    Path("README.md"),
    Path("README.zh-TW.md"),
    Path("SECURITY.md"),
    Path("docs/cli-reference.md"),
    Path("docs/configuration.md"),
    Path("docs/guides.md"),
    Path("docs/privacy.md"),
    Path("docs/limitations.md"),
    Path("docs/usage-statistics.md"),
    Path("docs/releasing.md"),
    Path(".github/workflows/ci.yml"),
    Path(".github/workflows/release.yml"),
)


def test_current_public_surfaces_do_not_use_the_old_brand() -> None:
    forbidden = (
        "agent" + "-worklog",
        "agent" + "_worklog",
        "AGENT_" + "WORKLOG",
        "Agent " + "Worklog",
    )
    for path in CURRENT_TEXT_FILES:
        text = path.read_text(encoding="utf-8")
        for value in forbidden:
            assert value not in text, f"{path}: stale brand {value!r}"
```

Source/test imports are separately guarded by package-import tests and `rg`; do not scan historical changelog text or historical design/plan files.

- [ ] **Step 7: Run the documentation and brand suite**

```bash
uv run pytest tests/unit/test_documentation.py tests/unit/test_brand_identity.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit the documentation/release slice**

```bash
git add README.md README.zh-TW.md SECURITY.md CHANGELOG.md docs .github tests/unit
git commit -m "docs: establish Iiwi brand foundation"
```

---

### Task 5: Full verification and release-preflight checks

**Files:**
- Modify only files exposed by verification failures attributable to the rename.
- Do not refactor unrelated failing areas under this task.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a release-ready `iiwi-0.9.0` code/package state before external repository/PyPI control-plane changes.

- [ ] **Step 1: Run the complete test suite with the release coverage target**

```bash
uv run pytest --cov=iiwi --cov-fail-under=80
```

Expected: PASS, coverage >= 80%.

- [ ] **Step 2: Run lint and type checking**

```bash
uv run ruff check .
uv run pyright
```

Expected: both PASS.

- [ ] **Step 3: Build and inspect the distribution**

```bash
rm -rf dist
uv build
uv tool run twine check dist/*
ls -1 dist
```

Expected filenames begin with:

```text
iiwi-0.9.0.tar.gz
iiwi-0.9.0-py3-none-any.whl
```

- [ ] **Step 4: Verify the installed command surface from the project environment**

```bash
uv run iiwi --version
uv run iiwi --help
uv run iiwi doctor --help
uv run iiwi scan --help
uv run iiwi report --help
uv run iiwi history --help
uv run iiwi update --help
uv run iiwi config --help
uv run iiwi run --help
```

Expected: every command exits 0 for help/version and uses Iiwi identity.

- [ ] **Step 5: Prove the old technical identity is absent from live source/package metadata**

```bash
python - <<'PY'
import importlib.util
assert importlib.util.find_spec("iiwi") is not None
assert importlib.util.find_spec("agent" + "_worklog") is None
PY

rg -n 'agent-worklog|agent_worklog|AGENT_WORKLOG|Agent Worklog' \
  pyproject.toml src/iiwi README.md README.zh-TW.md SECURITY.md \
  docs/cli-reference.md docs/configuration.md docs/guides.md docs/privacy.md \
  docs/limitations.md docs/usage-statistics.md docs/releasing.md \
  .github/workflows/ci.yml .github/workflows/release.yml
```

Expected: the Python assertions pass; `rg` returns no hits and therefore exits 1.

- [ ] **Step 6: Review the diff only for rename scope**

```bash
git diff main...HEAD --stat
git diff main...HEAD -- pyproject.toml src/iiwi tests README.md README.zh-TW.md SECURITY.md docs .github CHANGELOG.md
```

Confirm there is no service-architecture refactor, report-output semantic change, or new platform feature mixed into the rename.

- [ ] **Step 7: Commit any verification-only corrections**

If verification required rename-specific corrections, commit them together:

```bash
git add -A
git commit -m "test: verify Iiwi brand migration"
```

If no files changed, do not create an empty commit.

---

### Task 6: GitHub/PyPI control-plane cutover before `v0.9.0`

**Files:**
- No code file changes expected after Task 5 unless a control-plane value was documented incorrectly.

**Interfaces:**
- Consumes: verified release-ready branch from Task 5.
- Produces: repository and Trusted Publisher configuration capable of publishing the first Iiwi release.

- [ ] **Step 1: Merge the verified implementation branch before renaming the repository**

The branch must be green and reviewed before the repository name changes. Do not tag yet.

- [ ] **Step 2: Rename the GitHub repository**

Rename:

```text
mike840609/agent-worklog -> mike840609/iiwi
```

Then verify the default branch is still `main`, Actions remain enabled, and the `pypi` environment still exists.

- [ ] **Step 3: Configure the Iiwi PyPI Trusted Publisher**

Create/configure the pending publisher with exactly:

```text
PyPI project: iiwi
Owner: mike840609
Repository: iiwi
Workflow: release.yml
Environment: pypi
```

Do not publish a compatibility release to the old project.

- [ ] **Step 4: Run the Release workflow manually**

A `workflow_dispatch` run must complete the build job and skip publish/release jobs. Verify its package artifact contains the `iiwi-0.9.0` wheel and sdist.

- [ ] **Step 5: Re-check public links after the repository rename**

Verify README badges, Security advisory link, DeepWiki link if supported for the renamed repository, and release instructions resolve under `mike840609/iiwi`. Correct only broken current links and rerun documentation tests if needed.

- [ ] **Step 6: Do not tag until the separate release decision**

Phase 1 implementation ends with a publish-capable repository. Creating and pushing `v0.9.0` is the release action itself and should happen only when the user explicitly chooses to publish.

---

## Final self-review checklist

- Spec coverage: Tasks 1-6 cover package/CLI/import identity, version 0.9.0, errors, configuration prefix, config/history/state paths, update index/user-agent/upgrade command, user-visible terminal identity, documentation, workflows, stale-brand checking, build verification, GitHub rename, and Trusted Publishing.
- Historical-record exemption: the stale-brand guard uses an explicit current-surface file list and therefore does not contradict the decision to preserve historical plans/designs/changelog history.
- No compatibility layer: no task adds an old entry point, old import package, old environment fallback, or data migration.
- No placeholder implementation steps: every code-bearing task gives exact target strings/snippets and verification commands.
- Type/name consistency: `iiwi`, `Iiwi`, `IiwiError`, `IIWI_`, `IIWI_CONFIG_FILE`, `IIWI_HISTORY_FILE`, `IIWI_STATE_FILE`, version `0.9.0`, and repository `mike840609/iiwi` are consistent across tasks.
