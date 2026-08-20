"""Stage timings and counters behind the CLI's `--verbose` performance summary.

Services record; the CLI renders. Keeping the two apart is what lets `scan` and
`report` print the same table without either service knowing a console exists.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum


class MetricStage(StrEnum):
    """Timed stages, declared in the order the summary prints them.

    Deliberately separate from `ProgressStage`: progress names what the user is
    waiting on, timing names what the clock was spent on, and the two do not
    divide the work the same way. Exporting a session and resolving its
    repository share one progress bar but are two different costs, and narration
    hides inside the "summarizing" bar even though it is the whole bill.
    """

    DISCOVER_SESSIONS = "discover_sessions"
    EXPORT_SESSIONS = "export_sessions"
    RESOLVE_REPOSITORIES = "resolve_repositories"
    PREPARE_EVIDENCE = "prepare_evidence"
    PREPARE_TRANSCRIPT = "prepare_transcript"
    SUMMARIZE_REPOSITORIES = "summarize_repositories"
    COLLECT_USAGE = "collect_usage"
    NARRATE = "narrate"
    RENDER_REPORT = "render_report"
    WRITE_REPORT = "write_report"


@dataclass
class PerformanceMetrics:
    """Accumulate per-stage wall time plus the counts that explain it.

    Always a real object, never `None`: a `perf_counter` pair costs nanoseconds,
    so a null variant would buy nothing and cost every caller a branch.
    """

    durations: dict[MetricStage, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)

    @contextmanager
    def measure(self, stage: MetricStage) -> Iterator[None]:
        """Add one entry's wall time to `stage`, exception or not.

        Stages accumulate because most are entered once per session or per
        repository, and a run that failed partway still spent the time it
        spent — which is precisely what a performance report has to show.
        """

        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            self.durations[stage] = self.durations.get(stage, 0.0) + elapsed

    def count(self, name: str, value: int) -> None:
        self.counts[name] = value

    def label(self, name: str, value: str) -> None:
        self.labels[name] = value

    @property
    def total_seconds(self) -> float:
        """Sum of the measured stages.

        Not wall clock: stages never nest, so this adds up cleanly, and the gap
        against a stopwatch is the unmeasured glue — which is the honest signal
        that a stage worth timing is still missing.
        """

        return sum(self.durations.values())

    def ordered_durations(self) -> list[tuple[MetricStage, float]]:
        """Recorded stages in declaration order, so output never reorders itself."""

        return [
            (stage, self.durations[stage])
            for stage in MetricStage
            if stage in self.durations
        ]
