"""Rich-independent progress events for long-running application services."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class ProgressStage(StrEnum):
    """Stable semantic stages rendered by the CLI."""

    DISCOVERING_SESSIONS = "discovering_sessions"
    EXPORTING_SESSIONS = "exporting_sessions"
    PREPARING_EVIDENCE = "preparing_evidence"
    SUMMARIZING_REPOSITORIES = "summarizing_repositories"
    COLLECTING_USAGE = "collecting_usage"
    RENDERING_REPORT = "rendering_report"
    WRITING_REPORT = "writing_report"


class ProgressReporter(Protocol):
    """Receive absolute progress updates from synchronous services."""

    def start(
        self,
        stage: ProgressStage,
        *,
        total: int | None = None,
    ) -> None: ...

    def advance(self, completed: int) -> None: ...

    def finish(self) -> None: ...


class NullProgressReporter:
    """Ignore progress events while preserving the service interface."""

    def start(
        self,
        stage: ProgressStage,
        *,
        total: int | None = None,
    ) -> None:
        pass

    def advance(self, completed: int) -> None:
        pass

    def finish(self) -> None:
        pass
