"""Cross-project session scanning orchestration."""

from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from iiwi.errors import HarnessSourceError, SessionParseError
from iiwi.harnesses.base import HarnessSessionSource
from iiwi.metrics import MetricStage, PerformanceMetrics
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionDescriptor
from iiwi.models.time_range import DateRange
from iiwi.progress import NullProgressReporter, ProgressReporter, ProgressStage
from iiwi.repositories.resolver import Runner, reattach_by_branch
from iiwi.sessions.filtering import filter_session_to_period, is_iiwi_authored
from iiwi.sessions.hierarchy import group_resolved_sessions

_ASSISTANT_ACTIVITY_TYPES = frozenset(
    {ActivityType.ASSISTANT_MESSAGE, ActivityType.TOOL_CALL}
)

# Loading a session is dominated by waiting, not computing: OpenCode spawns an
# `opencode export` subprocess per session, and the file-backed harnesses read a
# transcript off disk. Four at a time hides most of that latency. The CPU count
# caps it rather than merely informing it because each OpenCode load is a whole
# coding-agent process, which a small machine should not be asked to host four of.
_SESSION_LOAD_WORKERS = min(4, os.cpu_count() or 1)


class Resolver(Protocol):
    def resolve(self, session: AgentSession) -> RepositoryIdentity: ...


def _has_assistant_work_but_no_prompt(session: AgentSession) -> bool:
    """Detect a root session whose prompts were filtered out or that never had any.

    A Claude Code transcript written before roughly version 2.1.187 carries no
    `origin` key, so the mapper's `origin.kind == "human"` filter — which exists to
    keep hook output and system reminders out of the report's goals — drops every
    user message in that file. This is an example: 10 of 72 recent Claude Code root
    sessions are affected, one of them with 188 assistant records. Loosening the
    filter would readmit the noise it was written to block, so the loss is reported
    instead of guessed at.

    Child and subagent sessions are exempt. A subagent is spawned with a prompt its
    parent wrote, not one a human typed, so it holds no human prompt by design:
    measured over one week, 44 of 44 subagent transcripts have none, against 1 of 10
    root sessions. Warning about them would bury the one case that means something.
    """

    if session.parent_session_id is not None:
        return False
    types = {activity.activity_type for activity in session.activities}
    return bool(types & _ASSISTANT_ACTIVITY_TYPES) and (
        ActivityType.USER_MESSAGE not in types
    )


def _missing_prompt_warning(session: AgentSession) -> str:
    """Explain a session that recorded work but no prompts, per harness.

    The Claude Code case has a known cause worth naming. No other harness does,
    so the generic sentence stops the report from blaming a Claude Code version
    for a Codex or OpenCode session.
    """

    base = (
        f"Session {session.session_id} recorded assistant work but no user "
        "messages, so it contributes no goals"
    )
    if session.harness == "claude-code":
        return (
            f"{base}; a Claude Code transcript written before version 2.1.187 "
            "does not mark human prompts"
        )
    return base


@dataclass(frozen=True)
class ScanResult:
    period: DateRange
    candidate_session_count: int
    loaded_session_count: int
    failed_session_count: int
    resolved_sessions: list[ResolvedSession] = field(default_factory=list)
    sessions_by_repository: dict[str, list[ResolvedSession]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    excluded_session_count: int = 0


class ScanService:
    """Discover, independently load, filter, and repository-resolve sessions."""

    def __init__(
        self,
        *,
        source: HarnessSessionSource,
        period: DateRange,
        resolver: Resolver,
        progress: ProgressReporter | None = None,
        excluded_repository_ids: frozenset[str] = frozenset(),
        runner: Runner | None = None,
        metrics: PerformanceMetrics | None = None,
    ) -> None:
        self._source = source
        self._period = period
        self._resolver = resolver
        self._progress = progress if progress is not None else NullProgressReporter()
        self._excluded_repository_ids = excluded_repository_ids
        self._runner = runner
        self._metrics = metrics if metrics is not None else PerformanceMetrics()

    def _loaded_or_warned(
        self,
        descriptor: SessionDescriptor,
        future: Future[AgentSession],
        warnings: list[str],
    ) -> AgentSession | None:
        """Wait for one session's load, turning its failure into a warning.

        Timed here because this is where the calling thread actually waits. With
        several loaders running, the total wait collapses toward the export
        phase's wall time, which is the number the performance summary should
        show — a sum of per-session durations across workers would exceed the
        clock and make the stage look slower for being faster.
        """

        try:
            with self._metrics.measure(MetricStage.EXPORT_SESSIONS):
                return future.result()
        except (SessionParseError, HarnessSourceError) as exc:
            warnings.append(f"Session {descriptor.session_id} export failed: {exc}")
            return None

    def scan(self) -> ScanResult:
        self._progress.start(ProgressStage.DISCOVERING_SESSIONS)
        with self._metrics.measure(MetricStage.DISCOVER_SESSIONS):
            descriptors = self._source.discover(self._period)
        self._progress.start(
            ProgressStage.EXPORTING_SESSIONS,
            total=len(descriptors),
        )
        warnings: list[str] = []
        failed_count = 0
        successful_exports = 0

        # Pass 1: load, filter to period, and resolve each session's repository
        # identity. Reattachment (below) needs every identity up front, so the
        # exclusion check and the fallback-identity warning wait for pass 2.
        #
        # Loads run concurrently; everything downstream of one stays on this
        # thread and is consumed in descriptor order. That split is deliberate:
        # warning order, progress counting, the repository resolver's Git cache,
        # and the order of `resolved_sessions` all stay exactly what they were
        # when loading was serial, so only the waiting is parallel.
        #
        # `submit` up front rather than `Executor.map`: map's iterator is a
        # generator that dies on the first result that raises, which would turn
        # one unreadable transcript into a scan that silently drops every session
        # queued behind it. Independent per-session failure is the contract here.
        pairs: list[tuple[AgentSession, RepositoryIdentity]] = []
        executor = ThreadPoolExecutor(
            max_workers=_SESSION_LOAD_WORKERS,
            thread_name_prefix="iiwi-session-load",
        )
        try:
            futures = [
                executor.submit(self._source.load, descriptor)
                for descriptor in descriptors
            ]
            for completed, (descriptor, future) in enumerate(
                zip(descriptors, futures, strict=True),
                start=1,
            ):
                try:
                    session = self._loaded_or_warned(descriptor, future, warnings)
                    if session is None:
                        failed_count += 1
                        continue
                    successful_exports += 1
                    # iiwi's own opencode runs are machinery, not the user's work. This
                    # runs before any warning append below, so a dropped session never
                    # surfaces a warning naming a session absent from the rest of the
                    # result.
                    if is_iiwi_authored(session):
                        continue
                    missing_timestamp_count = sum(
                        activity.timestamp is None for activity in session.activities
                    )
                    if missing_timestamp_count:
                        warnings.append(
                            f"Session {session.session_id} has {missing_timestamp_count} "
                            "timestamp-less activities that were excluded"
                        )
                    if _has_assistant_work_but_no_prompt(session):
                        warnings.append(_missing_prompt_warning(session))
                    filtered = filter_session_to_period(session, self._period)
                    if filtered is None:
                        continue
                    with self._metrics.measure(MetricStage.RESOLVE_REPOSITORIES):
                        repository = self._resolver.resolve(filtered)
                    pairs.append((filtered, repository))
                finally:
                    self._progress.advance(completed)
        finally:
            # Not a `with` block: `Executor.__exit__` waits for every queued
            # load, so a Ctrl-C or an unexpected error partway through a
            # hundred-session scan would sit through the whole remaining export
            # queue before surfacing. Cancelling the backlog leaves only the
            # handful already in flight to finish.
            executor.shutdown(cancel_futures=True)

        if descriptors and successful_exports == 0 and failed_count == len(descriptors):
            raise HarnessSourceError(
                f"all {descriptors[0].harness} session loads failed"
            )

        if self._runner is not None:
            with self._metrics.measure(MetricStage.RESOLVE_REPOSITORIES):
                pairs, reattached_count = reattach_by_branch(pairs, runner=self._runner)
        else:
            reattached_count = 0
        if reattached_count:
            warnings.append(
                f"Reattached {reattached_count} session(s) to their repository by "
                "branch after their worktree was removed"
            )

        # Pass 2: exclusion and the fallback-identity warning, now that fallback
        # identities have had their chance to be reattached.
        resolved_sessions: list[ResolvedSession] = []
        excluded_session_count = 0
        excluded_repository_names: dict[str, str] = {}
        for filtered, repository in pairs:
            if repository.repository_id in self._excluded_repository_ids:
                # The setting could name a repository with no sessions in this
                # period; only a hit here counts, so nothing is reported lost
                # that was never present.
                excluded_session_count += 1
                excluded_repository_names[repository.repository_id] = (
                    repository.display_name
                )
                continue
            if repository.identity_type in {
                RepositoryIdentityType.HARNESS_PROJECT,
                RepositoryIdentityType.PATH_FALLBACK,
                RepositoryIdentityType.UNKNOWN,
            }:
                warnings.append(
                    f"Session {filtered.session_id} used fallback repository identity "
                    f"{repository.repository_id}"
                )
            resolved_sessions.append(
                ResolvedSession(session=filtered, repository=repository)
            )

        if excluded_session_count:
            warnings.append(
                f"Excluded {excluded_session_count} sessions from configured "
                f"repositories: {', '.join(sorted(excluded_repository_names.values()))}"
            )

        sessions_by_repository = group_resolved_sessions(resolved_sessions)
        self._metrics.count("candidate_sessions", len(descriptors))
        self._metrics.count("loaded_sessions", len(resolved_sessions))
        self._metrics.count("failed_sessions", failed_count)
        self._metrics.count("repositories", len(sessions_by_repository))

        return ScanResult(
            period=self._period,
            candidate_session_count=len(descriptors),
            loaded_session_count=len(resolved_sessions),
            failed_session_count=failed_count,
            resolved_sessions=resolved_sessions,
            sessions_by_repository=sessions_by_repository,
            warnings=warnings,
            excluded_session_count=excluded_session_count,
        )
