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
