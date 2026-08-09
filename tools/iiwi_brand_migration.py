# ruff: noqa
"""One-shot, branch-only executor for the approved Iiwi brand migration plan.

This file is temporary. GitHub Actions runs it in an isolated checkout because the
interactive sandbox cannot reach github.com. Each task follows a red/green cycle,
commits only after its focused tests pass, and finishes with the full release gate.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path.cwd()


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    return subprocess.run(args, cwd=ROOT, check=check, text=True)


def expect_red(*args: str) -> None:
    result = run(*args, check=False)
    if result.returncode == 0:
        raise RuntimeError(f"expected RED test failure but command passed: {' '.join(args)}")
    print("RED confirmed", flush=True)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace(path: str, replacements: tuple[tuple[str, str], ...]) -> None:
    content = read(path)
    updated = content
    for old, new in replacements:
        updated = updated.replace(old, new)
    if updated != content:
        write(path, updated)


def replace_python_tree(root: str, replacements: tuple[tuple[str, str], ...]) -> None:
    for path in sorted((ROOT / root).rglob("*.py")):
        replace(str(path.relative_to(ROOT)), replacements)


def append_once(path: str, marker: str, content: str) -> None:
    current = read(path)
    if marker not in current:
        write(path, current.rstrip() + "\n\n" + content.strip() + "\n")


def commit(message: str) -> None:
    run("git", "add", "-A")
    status = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=ROOT, check=False
    )
    if status.returncode == 0:
        raise RuntimeError(f"task produced no staged changes: {message}")
    run("git", "commit", "-m", message)


def task1_package_identity() -> None:
    print("\n=== Task 1: package identity ===", flush=True)
    write(
        "tests/unit/test_brand_identity.py",
        '''import importlib.util
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
    old_package = "agent" + "_worklog"
    assert Path("src/iiwi").is_dir()
    assert not (Path("src") / old_package).exists()
    assert importlib.util.find_spec("iiwi") is not None
    assert importlib.util.find_spec(old_package) is None
''',
    )
    expect_red("uv", "run", "pytest", "tests/unit/test_brand_identity.py", "-q")

    run("git", "mv", "src/agent_worklog", "src/iiwi")
    replace_python_tree("src/iiwi", (("agent_worklog", "iiwi"), ("AgentWorklogError", "IiwiError")))
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path.name == "test_brand_identity.py":
            continue
        replace(
            str(path.relative_to(ROOT)),
            (("agent_worklog", "iiwi"), ("AgentWorklogError", "IiwiError")),
        )

    pyproject = read("pyproject.toml")
    pyproject = pyproject.replace('name = "agent-worklog"', 'name = "iiwi"', 1)
    pyproject = pyproject.replace('version = "0.8.0"', 'version = "0.9.0"', 1)
    pyproject = pyproject.replace(
        'description = "Turn coding-agent sessions into repository-based engineering reports"',
        'description = "Agent Session Intelligence for engineering work"',
        1,
    )
    pyproject = pyproject.replace(
        'agent-worklog = "agent_worklog.cli:app"', 'iiwi = "iiwi.cli:app"', 1
    )
    write("pyproject.toml", pyproject)

    write("src/iiwi/__init__.py", '"""Iiwi package."""\n\n__version__ = "0.9.0"\n')
    run("uv", "lock")
    run("uv", "sync", "--extra", "dev")
    run(
        "uv",
        "run",
        "pytest",
        "tests/unit/test_brand_identity.py",
        "tests/unit/test_version.py",
        "-q",
    )
    run("uv", "run", "python", "-c", "import iiwi; assert iiwi.__version__ == '0.9.0'")
    run("uv", "run", "python", "-c", "from iiwi.cli import app; assert app is not None")
    commit("refactor: rename package to iiwi")


def task2_runtime_identity() -> None:
    print("\n=== Task 2: runtime identity ===", flush=True)
    runtime_test_files = (
        "tests/conftest.py",
        "tests/unit/test_config.py",
        "tests/unit/test_config_store.py",
        "tests/unit/test_history.py",
        "tests/unit/test_state.py",
        "tests/unit/test_update.py",
        "tests/unit/test_cli.py",
        "tests/unit/interactive/test_cli_actions.py",
    )
    for path in runtime_test_files:
        replace(path, (("AGENT_WORKLOG", "IIWI"),))
    for test_path in sorted((ROOT / "tests").rglob("*.py")):
        replace(str(test_path.relative_to(ROOT)), (("AGENT_WORKLOG", "IIWI"),))
    replace("tests/unit/test_config_store.py", (("agent-worklog", "iiwi"),))
    replace("tests/unit/test_cli.py", (("agent-worklog", "iiwi"),))
    replace(
        "tests/unit/test_update.py",
        (("pipx upgrade agent-worklog", "pipx upgrade iiwi"),),
    )

    append_once(
        "tests/unit/test_config.py",
        "test_old_environment_prefix_is_not_consumed",
        '''def test_old_environment_prefix_is_not_consumed(monkeypatch: pytest.MonkeyPatch) -> None:
    old_name = "AGENT_" + "WORKLOG_REPORT__TIMEZONE"
    monkeypatch.setenv(old_name, "UTC")
    monkeypatch.delenv("IIWI_REPORT__TIMEZONE", raising=False)

    settings = AppSettings()

    assert settings.report.timezone == "Asia/Taipei"''',
    )

    history = read("tests/unit/test_history.py")
    if "history_file_path," not in history:
        history = history.replace("    append_history,\n", "    append_history,\n    history_file_path,\n", 1)
        write("tests/unit/test_history.py", history)
    append_once(
        "tests/unit/test_history.py",
        "test_history_default_path_uses_iiwi_app_name",
        '''def test_history_default_path_uses_iiwi_app_name(monkeypatch) -> None:
    monkeypatch.delenv("IIWI_HISTORY_FILE", raising=False)

    path = history_file_path()

    assert path.name == "history.jsonl"
    assert "iiwi" in str(path)''',
    )

    state = read("tests/unit/test_state.py")
    if "state_file_path," not in state:
        state = state.replace("    save_selection,\n", "    save_selection,\n    state_file_path,\n", 1)
        write("tests/unit/test_state.py", state)
    append_once(
        "tests/unit/test_state.py",
        "test_state_default_path_uses_iiwi_app_name",
        '''def test_state_default_path_uses_iiwi_app_name(monkeypatch) -> None:
    monkeypatch.delenv("IIWI_STATE_FILE", raising=False)

    path = state_file_path()

    assert path.name == "state.json"
    assert "iiwi" in str(path)''',
    )

    append_once(
        "tests/unit/test_update.py",
        "test_update_uses_the_iiwi_index",
        '''def test_update_uses_the_iiwi_index() -> None:
    seen: list[str] = []

    check_for_update(
        fetcher=lambda url: seen.append(url) or json.dumps(_LATEST_JSON),
        current="0.9.0",
    )

    assert seen == ["https://pypi.org/pypi/iiwi/json"]''',
    )

    expect_red(
        "uv",
        "run",
        "pytest",
        "tests/unit/test_config.py",
        "tests/unit/test_config_store.py",
        "tests/unit/test_history.py",
        "tests/unit/test_state.py",
        "tests/unit/test_update.py",
        "tests/unit/test_cli.py",
        "tests/unit/interactive/test_cli_actions.py",
        "-q",
    )

    replace_python_tree("src/iiwi", (("AGENT_WORKLOG", "IIWI"), ("agent-worklog", "iiwi")))
    run(
        "uv",
        "run",
        "pytest",
        "tests/unit/test_config.py",
        "tests/unit/test_config_store.py",
        "tests/unit/test_history.py",
        "tests/unit/test_state.py",
        "tests/unit/test_update.py",
        "tests/unit/test_cli.py",
        "tests/unit/interactive/test_cli_actions.py",
        "-q",
    )
    commit("refactor: move runtime identity to iiwi")


def task3_cli_identity() -> None:
    print("\n=== Task 3: CLI identity ===", flush=True)
    for path in sorted((ROOT / "tests/unit/interactive").rglob("*.py")):
        replace(str(path.relative_to(ROOT)), (("Agent Worklog", "Iiwi"),))

    for test_path in sorted((ROOT / "tests").rglob("*.py")):
        replace(str(test_path.relative_to(ROOT)), (("Agent Worklog", "Iiwi"),))

    replace(
        "tests/unit/repositories/test_remote.py",
        (('== "Iiwi"', '== "Agent Worklog"'),),
    )
    replace(
        "tests/integration/test_end_to_end.py",
        (('content.count("### Iiwi")', 'content.count("### Agent Worklog")'),),
    )

    render_test = read("tests/unit/interactive/test_render.py")
    render_test = render_test.replace("_console(width=19)", "_console(width=10)", 1)
    render_test = render_test.replace(
        "test_main_menu_fits_the_version_at_exactly_twenty_cells",
        "test_main_menu_fits_the_version_at_exactly_eleven_cells",
        1,
    )
    render_test = render_test.replace(
        "13 title cells + 1 gap + 6 version cells, so width 20",
        "4 title cells + 1 gap + 6 version cells, so width 11",
        1,
    )
    render_test = render_test.replace("_console(width=20)", "_console(width=11)", 1)
    needle = '    assert "Iiwi" in text\n'
    if "Probe coding-agent sessions" not in render_test and needle in render_test:
        render_test = render_test.replace(
            needle,
            needle + '    assert "Probe coding-agent sessions" in text\n',
            1,
        )
        write("tests/unit/interactive/test_render.py", render_test)

    cli_test = read("tests/unit/test_cli.py")
    needle = '    assert "report" in result.stdout\n'
    if "Agent Session Intelligence" not in cli_test and needle in cli_test:
        cli_test = cli_test.replace(
            needle,
            needle + '    assert "Agent Session Intelligence" in result.stdout\n',
            1,
        )
        write("tests/unit/test_cli.py", cli_test)

    expect_red(
        "uv",
        "run",
        "pytest",
        "tests/unit/test_cli.py",
        "tests/unit/interactive",
        "-q",
    )

    replace_python_tree("src/iiwi", (("Agent Worklog", "Iiwi"),))
    replace(
        "src/iiwi/cli.py",
        (
            (
                "Turn coding-agent sessions into repository-based engineering reports.",
                "Agent Session Intelligence for engineering work.",
            ),
        ),
    )
    replace(
        "src/iiwi/interactive/render.py",
        (
            (
                "Turn coding-agent sessions into engineering reports",
                "Probe coding-agent sessions. Surface the work that matters.",
            ),
        ),
    )
    run(
        "uv",
        "run",
        "pytest",
        "tests/unit/test_cli.py",
        "tests/unit/interactive",
        "-q",
    )
    commit("feat: brand the cli as Iiwi")


def add_brand_guard() -> None:
    path = "tests/unit/test_brand_identity.py"
    append_once(
        path,
        "test_current_public_surfaces_do_not_use_the_old_brand",
        '''CURRENT_TEXT_FILES = (
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
    Path("docs/assets/architecture.mmd"),
    Path("docs/assets/architecture.svg"),
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
''',
    )


def rewrite_readmes() -> None:
    readme = read("README.md")
    old = "Iiwi turns coding-agent sessions into weekly reports for managers, saving\nengineers time."
    new = (
        "**Iiwi** *(ee-EE-wee)* — Agent Session Intelligence for engineering work.\n\n"
        "**Probe coding-agent sessions. Surface the work that matters.**\n\n"
        "Iiwi reads coding-agent sessions from OpenCode, Claude Code, and Codex, groups "
        "the work by Git repository, selects and redacts useful evidence, and turns it "
        "into engineering reports."
    )
    if old in readme:
        readme = readme.replace(old, new, 1)
    readme = readme.replace(
        "Turn coding-agent sessions into engineering reports",
        "Probe coding-agent sessions. Surface the work that matters.",
    )
    write("README.md", readme)

    zh = read("README.zh-TW.md")
    old_zh = "Iiwi 把 coding-agent 的工作階段整理成給主管看的週報，替工程師省下時間。"
    new_zh = (
        "**Iiwi** *(ee-EE-wee)* — 為工程工作提供 Agent Session Intelligence。\n\n"
        "**探查 coding-agent 工作階段，找出真正重要的工作。**\n\n"
        "Iiwi 讀取 OpenCode、Claude Code 與 Codex 的工作階段，依 Git repository "
        "整理工作、挑選並去敏有用證據，再產生工程報告。"
    )
    if old_zh in zh:
        zh = zh.replace(old_zh, new_zh, 1)
    zh = zh.replace(
        "Turn coding-agent sessions into engineering reports",
        "Probe coding-agent sessions. Surface the work that matters.",
    )
    write("README.zh-TW.md", zh)


def update_changelog() -> None:
    path = "CHANGELOG.md"
    text = read(path)
    start = text.index("## Unreleased")
    next_heading = text.find("\n## ", start + len("## Unreleased"))
    if next_heading == -1:
        next_heading = len(text)
    prefix = text[:start]
    current = text[start:next_heading]
    suffix = text[next_heading:]
    for old, new in (
        ("AGENT_WORKLOG", "IIWI"),
        ("agent_worklog", "iiwi"),
        ("agent-worklog", "iiwi"),
        ("Agent Worklog", "Iiwi"),
    ):
        current = current.replace(old, new)
    rename_bullet = (
        "- Rename the project to **Iiwi**: the distribution, Python package, CLI, environment\n"
        "  prefix, config/data directories, update index, documentation, and release flow now use\n"
        "  `iiwi` / `IIWI_*`. No compatibility alias is provided because the project has no user\n"
        "  migration requirement yet.\n"
    )
    if "Rename the project to **Iiwi**" not in current:
        current = current.replace("## Unreleased\n\n", "## Unreleased\n\n" + rename_bullet, 1)
    write(path, prefix + current + suffix)


def task4_docs_release() -> None:
    print("\n=== Task 4: docs and release identity ===", flush=True)
    for path in ("tests/unit/test_documentation.py", "tests/unit/test_interactive_documentation.py"):
        replace(
            path,
            (
                ("mike840609/agent-worklog", "mike840609/iiwi"),
                ("AGENT_WORKLOG", "IIWI"),
                ("agent_worklog", "iiwi"),
                ("agent-worklog", "iiwi"),
                ("Agent Worklog", "Iiwi"),
            ),
        )
    append_once(
        "tests/unit/test_documentation.py",
        "test_readme_introduces_the_iiwi_brand",
        '''def test_readme_introduces_the_iiwi_brand() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "# Iiwi" in readme
    assert "*(ee-EE-wee)*" in readme
    assert "Agent Session Intelligence for engineering work" in readme
    assert "Probe coding-agent sessions. Surface the work that matters." in readme''',
    )
    replace(
        "tests/unit/test_documentation.py",
        (("Iiwi *(ee-EE-wee)*", "**Iiwi** *(ee-EE-wee)*"),),
    )
    add_brand_guard()
    expect_red(
        "uv",
        "run",
        "pytest",
        "tests/unit/test_documentation.py",
        "tests/unit/test_interactive_documentation.py",
        "tests/unit/test_brand_identity.py",
        "-q",
    )

    current_files = (
        "README.md",
        "README.zh-TW.md",
        "SECURITY.md",
        "docs/cli-reference.md",
        "docs/configuration.md",
        "docs/guides.md",
        "docs/privacy.md",
        "docs/limitations.md",
        "docs/usage-statistics.md",
        "docs/releasing.md",
        "docs/assets/architecture.mmd",
        "docs/assets/architecture.svg",
    )
    replacements = (
        ("mike840609/agent-worklog", "mike840609/iiwi"),
        ("AGENT_WORKLOG", "IIWI"),
        ("agent_worklog", "iiwi"),
        ("agent-worklog", "iiwi"),
        ("Agent Worklog", "Iiwi"),
    )
    for path in current_files:
        replace(path, replacements)

    rewrite_readmes()
    update_changelog()

    old_asset = ROOT / "docs/assets/agent-worklog-overview.png"
    new_asset = ROOT / "docs/assets/iiwi-overview.png"
    if old_asset.exists() and not new_asset.exists():
        run("git", "mv", str(old_asset.relative_to(ROOT)), str(new_asset.relative_to(ROOT)))

    run(
        "uv",
        "run",
        "pytest",
        "tests/unit/test_documentation.py",
        "tests/unit/test_interactive_documentation.py",
        "tests/unit/test_brand_identity.py",
        "-q",
    )
    commit("docs: establish Iiwi brand foundation")


def verify_all() -> None:
    print("\n=== Task 5: full verification ===", flush=True)
    run("uv", "run", "pytest", "--cov=iiwi", "--cov-fail-under=80")
    run("uv", "run", "ruff", "check", ".")
    run("uv", "run", "pyright")
    dist = ROOT / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    run("uv", "build")
    run("uv", "tool", "run", "twine", "check", *(str(path) for path in sorted(dist.iterdir()) if path.name.endswith((".whl", ".tar.gz"))))
    artifacts = sorted(path.name for path in dist.iterdir())
    print("artifacts:", artifacts, flush=True)
    if "iiwi-0.9.0.tar.gz" not in artifacts:
        raise RuntimeError(f"missing Iiwi sdist: {artifacts}")
    if not any(name.startswith("iiwi-0.9.0-") and name.endswith(".whl") for name in artifacts):
        raise RuntimeError(f"missing Iiwi wheel: {artifacts}")
    for args in (
        ("--version",),
        ("--help",),
        ("doctor", "--help"),
        ("scan", "--help"),
        ("report", "--help"),
        ("history", "--help"),
        ("update", "--help"),
        ("config", "--help"),
        ("run", "--help"),
    ):
        run("uv", "run", "iiwi", *args)

    forbidden = ("agent_worklog", "AGENT_WORKLOG", "Agent Worklog", "agent-worklog")
    for path in sorted((ROOT / "src/iiwi").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for value in forbidden:
            if value in text:
                raise RuntimeError(f"stale brand in {path}: {value}")


def main() -> None:
    run("git", "config", "user.name", "Iiwi Migration Bot")
    run("git", "config", "user.email", "actions@users.noreply.github.com")
    task1_package_identity()
    task2_runtime_identity()
    task3_cli_identity()
    task4_docs_release()
    verify_all()
    print("\nIiwi migration verified; commits are ready to push.", flush=True)


if __name__ == "__main__":
    main()
