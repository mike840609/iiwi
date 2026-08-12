"""Cross-project session scanning orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from iiwi.errors import HarnessSourceError, SessionParseError
from iiwi.harnesses.base import HarnessSessionSource
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession
from iiwi.models.time_range import DateRange
from iiwi.progress import NullProgressReporter, ProgressReporter, ProgressStage
from iiwi.repositories.resolver import Runner, reattach_by_branch
from iiwi.sessions.filtering import filter_session_to_period, is_iiwi_authored
from iiwi.sessions.hierarchy import group_resolved_sessions

_ASSISTANT_ACTIVITY_TYPES = frozenset(
    {ActivityType.ASSISTANT_MESSAGE, ActivityType.TOOL_CALL}
)


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
    ) -> None:
        self._source = source
        self._period = period
        self._resolver = resolver
        self._progress = progress if progress is not None else NullProgressReporter()
        self._excluded_repository_ids = excluded_repository_ids
        self._runner = runner

    def scan(self) -> ScanResult:
        self._progress.start(ProgressStage.DISCOVERING_SESSIONS)
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
        pairs: list[tuple[AgentSession, RepositoryIdentity]] = []
        for completed, descriptor in enumerate(descriptors, start=1):
            try:
                try:
                    session = self._source.load(descriptor)
                except (SessionParseError, HarnessSourceError) as exc:
                    failed_count += 1
                    warnings.append(
                        f"Session {descriptor.session_id} export failed: {exc}"
                    )
                    continue
                successful_exports += 1
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
                # iiwi's own opencode runs are machinery, not the user's work.
                if is_iiwi_authored(session):
                    continue
                filtered = filter_session_to_period(session, self._period)
                if filtered is None:
                    continue
                repository = self._resolver.resolve(filtered)
                pairs.append((filtered, repository))
            finally:
                self._progress.advance(completed)

        if descriptors and successful_exports == 0 and failed_count == len(descriptors):
            raise HarnessSourceError(
                f"all {descriptors[0].harness} session loads failed"
            )

        if self._runner is not None:
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

        return ScanResult(
            period=self._period,
            candidate_session_count=len(descriptors),
            loaded_session_count=len(resolved_sessions),
            failed_session_count=failed_count,
            resolved_sessions=resolved_sessions,
            sessions_by_repository=group_resolved_sessions(resolved_sessions),
            warnings=warnings,
            excluded_session_count=excluded_session_count,
        )
