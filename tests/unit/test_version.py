import tomllib
from pathlib import Path

import iiwi


def test_runtime_version_matches_project_metadata() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert iiwi.__version__ == project["project"]["version"]
