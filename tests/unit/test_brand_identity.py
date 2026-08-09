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
    old_package = "agent" + "_worklog"
    assert Path("src/iiwi").is_dir()
    assert not (Path("src") / old_package).exists()
    assert importlib.util.find_spec("iiwi") is not None
    assert importlib.util.find_spec(old_package) is None


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
    Path("docs/assets/architecture.mmd"),
    Path("docs/assets/architecture.svg"),
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
