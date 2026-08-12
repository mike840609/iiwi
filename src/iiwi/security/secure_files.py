"""Secure temporary directories and atomic report writes."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from iiwi.errors import ReportAlreadyExistsError, ReportOutputError


@contextmanager
def secure_temporary_directory() -> Iterator[Path]:
    """Create a mode-0700 temporary directory and remove it on exit."""

    directory = Path(tempfile.mkdtemp(prefix="iiwi-"))
    try:
        if os.name == "posix":
            directory.chmod(0o700)
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def atomic_secure_write(path: Path, content: str, *, force: bool = False) -> None:
    """Atomically write UTF-8 text, refusing overwrite unless explicitly allowed."""

    destination = path.expanduser()
    if destination.exists() and not force:
        raise ReportAlreadyExistsError(f"report already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if force:
            os.replace(temporary_path, destination)
        else:
            try:
                os.link(temporary_path, destination)
            except FileExistsError as exc:
                raise ReportAlreadyExistsError(
                    f"report already exists: {destination}"
                ) from exc
            temporary_path.unlink()
        temporary_path = None
        if os.name == "posix":
            destination.chmod(0o600)
    except OSError as exc:
        raise ReportOutputError(f"failed to write report: {destination}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
