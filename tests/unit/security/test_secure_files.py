import os
from pathlib import Path

import pytest

from iiwi.errors import ReportAlreadyExistsError, ReportOutputError
from iiwi.security.secure_files import atomic_secure_write, secure_temporary_directory


def test_atomic_write_rejects_existing_file_without_force(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text("old")

    with pytest.raises(ReportOutputError, match="already exists"):
        atomic_secure_write(path, "new")

    assert path.read_text() == "old"


def test_atomic_write_rejects_file_created_after_initial_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "report.md"
    real_fsync = os.fsync

    def create_racing_destination(descriptor: int) -> None:
        if not path.exists():
            path.write_text("racing writer", encoding="utf-8")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", create_racing_destination)

    with pytest.raises(ReportAlreadyExistsError, match="already exists"):
        atomic_secure_write(path, "new content", force=False)

    assert path.read_text(encoding="utf-8") == "racing writer"


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode semantics")
def test_atomic_write_sets_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "report.md"

    atomic_secure_write(path, "content")

    assert path.read_text() == "content"
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode semantics")
def test_secure_temporary_directory_uses_0700_and_is_removed() -> None:
    with secure_temporary_directory() as directory:
        assert directory.stat().st_mode & 0o777 == 0o700
        retained = directory
    assert not retained.exists()
