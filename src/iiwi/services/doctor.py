"""Environment diagnostics."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from iiwi.config import AppSettings
from iiwi.harnesses.codex.source import describe_discovery
from iiwi.process import CommandResult


class Runner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class DoctorResult:
    checks: list[DoctorCheck]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


@dataclass(frozen=True)
class NarratorDescription:
    """Which CLI narrates, and whether that came from config or the harness."""

    provider: str
    executable: str
    source: str


def _check(runner: Runner, name: str, args: list[str]) -> DoctorCheck:
    try:
        result = runner.run(args)
    except (FileNotFoundError, TimeoutError, OSError) as exc:
        return DoctorCheck(name=name, ok=False, detail=type(exc).__name__)
    detail = result.stdout.strip() if result.returncode == 0 else result.stderr.strip()
    return DoctorCheck(name=name, ok=result.returncode == 0, detail=detail)


def _narrator_check(
    narrator: NarratorDescription,
    *,
    codex_home: Path | None = None,
) -> DoctorCheck:
    """Name the resolved narrator and say whether it was configured or derived."""

    resolved = shutil.which(narrator.executable)
    if resolved is not None:
        return DoctorCheck(
            name="narrator",
            ok=True,
            detail=f"{narrator.provider} (from {narrator.source}) -> {resolved}",
        )
    detail = (
        f"{narrator.executable} not found (from {narrator.source}); "
        "set narrator.provider or narrator.executable"
    )
    # A Codex desktop install ships its CLI outside PATH, under a private
    # directory that a future release can relocate. Point at the docs instead
    # of hardcoding a path that would break silently.
    if narrator.provider == "codex" and codex_home is not None and codex_home.is_dir():
        detail += "; see the Codex desktop section of docs/configuration.md"
    return DoctorCheck(name="narrator", ok=False, detail=detail)


def run_doctor(
    settings: AppSettings,
    *,
    runner: Runner,
    narrator: NarratorDescription,
    harness: str = "opencode",
) -> DoctorResult:
    """Validate the selected harness, the resolved narrator, and Git."""

    checks: list[DoctorCheck] = []
    if harness == "claude-code":
        directory = settings.harnesses.claude_code.projects_directory
        readable = directory.is_dir() and os.access(directory, os.R_OK)
        checks.append(
            DoctorCheck(
                name="claude code projects directory",
                ok=readable,
                detail=str(directory),
            )
        )
    elif harness == "codex":
        directory = settings.harnesses.codex.home_directory
        readable = directory.is_dir() and os.access(directory, os.R_OK)
        # Naming the discovery path makes a silent fallback to the slower
        # directory scan visible before a report takes minutes to produce.
        detail = (
            f"{directory} ({describe_discovery(directory)})"
            if readable
            else str(directory)
        )
        checks.append(
            DoctorCheck(name="codex home directory", ok=readable, detail=detail)
        )
    else:
        executable = settings.harnesses.opencode.cli.executable
        checks.append(_check(runner, "opencode version", [executable, "--version"]))
        checks.append(_check(runner, "opencode database", [executable, "db", "path"]))
    checks.append(
        _narrator_check(narrator, codex_home=settings.harnesses.codex.home_directory)
    )
    checks.append(_check(runner, "git", ["git", "--version"]))
    return DoctorResult(checks=checks)
