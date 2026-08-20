import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import iiwi.services.scan as scan_module
from iiwi.cache import CachingSessionSource, SessionCache, adapter_version
from iiwi.errors import HarnessSourceError, SessionParseError
from iiwi.metrics import MetricStage, PerformanceMetrics
from iiwi.models.repository import RepositoryIdentity, RepositoryIdentityType
from iiwi.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
)
from iiwi.models.time_range import DateRange
from iiwi.progress import ProgressStage
from iiwi.services.scan import ScanResult, ScanService
from tests.progress import RecordingProgressReporter

TZ = ZoneInfo("Asia/Taipei")


class FakeSource:
    def __init__(self) -> None:
        self.fail_session_ids: set[str] = set()
        self.fail_all = False
        self.activity_timestamps: dict[str, datetime] = {}
        self.descriptors = [
            SessionDescriptor(harness="opencode", session_id="good-1"),
            SessionDescriptor(harness="opencode", session_id="bad"),
            SessionDescriptor(harness="opencode", session_id="good-2"),
        ]

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return self.descriptors

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        if self.fail_all or descriptor.session_id in self.fail_session_ids:
            raise SessionParseError(f"failed export: {descriptor.session_id}")
        return AgentSession(
            harness="opencode",
            session_id=descriptor.session_id,
            activities=[
                SessionActivity(
                    activity_id=f"{descriptor.session_id}:a1",
                    activity_type=ActivityType.USER_MESSAGE,
                    timestamp=self.activity_timestamps.get(
                        descriptor.session_id,
                        datetime(2026, 7, 22, tzinfo=TZ),
                    ),
                    content="Add weekly report generation",
                )
            ],
        )


class StaticResolver:
    def resolve(self, session: AgentSession) -> RepositoryIdentity:
        return RepositoryIdentity(
            repository_id="git:github.com/mike/iiwi",
            display_name="Iiwi",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            normalized_remote="github.com/mike/iiwi",
            branch="main",
            resolution_method="git_origin_remote",
        )


def _identity(repository_id: str, display_name: str) -> RepositoryIdentity:
    return RepositoryIdentity(
        repository_id=repository_id,
        display_name=display_name,
        identity_type=RepositoryIdentityType.GIT_REMOTE,
        normalized_remote=repository_id.removeprefix("git:"),
        branch="main",
        resolution_method="git_origin_remote",
    )


class IdResolver:
    """Resolve each session to the identity its session id names."""

    def __init__(self, mapping: dict[str, RepositoryIdentity]) -> None:
        self._mapping = mapping

    def resolve(self, session: AgentSession) -> RepositoryIdentity:
        return self._mapping[session.session_id]


def period() -> DateRange:
    return DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )


class PromptlessSource:
    """A root transcript whose human prompts the mapper could not identify."""

    def __init__(
        self,
        *,
        parent_session_id: str | None = None,
        harness: str = "claude-code",
    ) -> None:
        self.parent_session_id = parent_session_id
        self.harness = harness

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return [SessionDescriptor(harness=self.harness, session_id="old-transcript")]

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        return AgentSession(
            harness=self.harness,
            session_id=descriptor.session_id,
            parent_session_id=self.parent_session_id,
            activities=[
                SessionActivity(
                    activity_id="a-1",
                    activity_type=ActivityType.ASSISTANT_MESSAGE,
                    timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                    content="I updated the fetcher.",
                ),
                SessionActivity(
                    activity_id="a-2",
                    activity_type=ActivityType.TOOL_CALL,
                    timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                    content="pytest -q",
                    tool_name="Bash",
                ),
            ],
        )


def test_scan_warns_when_assistant_work_has_no_user_messages() -> None:
    """A pre-2.1.187 transcript yields no goals; that must not be silent."""

    service = ScanService(
        source=PromptlessSource(), period=period(), resolver=StaticResolver()
    )

    result = service.scan()

    assert result.loaded_session_count == 1
    assert any(
        "old-transcript" in warning and "no user messages" in warning
        for warning in result.warnings
    ), result.warnings


def test_scan_does_not_warn_when_a_session_has_user_messages() -> None:
    service = ScanService(source=FakeSource(), period=period(), resolver=StaticResolver())

    result = service.scan()

    assert not any("no user messages" in warning for warning in result.warnings)


def test_scan_does_not_warn_about_a_promptless_subagent_session() -> None:
    """A subagent is spawned with its parent's prompt, so it holds no human prompt.

    Measured over one week, 44 of 44 subagent transcripts have none. Warning about
    every one of them would bury the single root session that lost its goals.
    """

    service = ScanService(
        source=PromptlessSource(parent_session_id="root-session"),
        period=period(),
        resolver=StaticResolver(),
    )

    result = service.scan()

    assert result.loaded_session_count == 1
    assert not any("no user messages" in warning for warning in result.warnings)


def test_scan_continues_after_one_export_failure() -> None:
    source = FakeSource()
    source.fail_session_ids = {"bad"}
    service = ScanService(source=source, period=period(), resolver=StaticResolver())

    result = service.scan()

    assert result.loaded_session_count == 2
    assert result.failed_session_count == 1
    assert any("bad" in warning for warning in result.warnings)
    assert list(result.sessions_by_repository) == ["git:github.com/mike/iiwi"]


def test_scan_reports_every_discovered_descriptor_as_processed() -> None:
    source = FakeSource()
    source.fail_session_ids = {"bad"}
    source.activity_timestamps["good-2"] = datetime(2026, 7, 1, tzinfo=TZ)
    progress = RecordingProgressReporter()
    service = ScanService(
        source=source,
        period=period(),
        resolver=StaticResolver(),
        progress=progress,
    )

    result = service.scan()

    assert result.loaded_session_count == 1
    assert result.failed_session_count == 1
    assert progress.events == [
        ("start", ProgressStage.DISCOVERING_SESSIONS, None),
        ("start", ProgressStage.EXPORTING_SESSIONS, 3),
        ("advance", 1),
        ("advance", 2),
        ("advance", 3),
    ]


def test_promptless_warning_names_claude_code_only_for_claude_code() -> None:
    """No other harness has the pre-2.1.187 transcript problem to blame."""

    claude = ScanService(
        source=PromptlessSource(), period=period(), resolver=StaticResolver()
    ).scan()
    codex = ScanService(
        source=PromptlessSource(harness="codex"),
        period=period(),
        resolver=StaticResolver(),
    ).scan()

    claude_warning = next(w for w in claude.warnings if "no user messages" in w)
    codex_warning = next(w for w in codex.warnings if "no user messages" in w)
    assert "2.1.187" in claude_warning
    assert "Claude Code" not in codex_warning
    assert "2.1.187" not in codex_warning


DOTFILES_ID = "git:github.com/mike/dotfiles"
WORK_ID = "git:github.com/mike/work"


def _dotfiles(session_id: str) -> RepositoryIdentity:
    return _identity(DOTFILES_ID, "Dotfiles")


def _work(session_id: str) -> RepositoryIdentity:
    return _identity(WORK_ID, "Work")


def _source(session_ids: list[str]) -> FakeSource:
    source = FakeSource()
    source.descriptors = [
        SessionDescriptor(harness="opencode", session_id=session_id)
        for session_id in session_ids
    ]
    return source


def test_an_empty_excluded_set_leaves_the_scan_unchanged() -> None:
    source = _source(["good-1", "good-2"])
    source.fail_session_ids = {"bad"}
    resolver = IdResolver({"good-1": _work("good-1"), "good-2": _work("good-2")})

    baseline = ScanService(source=source, period=period(), resolver=resolver).scan()
    with_exclusions = ScanService(
        source=source,
        period=period(),
        resolver=resolver,
        excluded_repository_ids=frozenset(),
    ).scan()

    assert with_exclusions == baseline
    assert with_exclusions.excluded_session_count == 0


def test_configuring_exclude_repositories_removes_only_that_repository() -> None:
    source = _source(["dotfiles-1", "dotfiles-2", "work-1"])
    resolver = IdResolver(
        {
            "dotfiles-1": _dotfiles("dotfiles-1"),
            "dotfiles-2": _dotfiles("dotfiles-2"),
            "work-1": _work("work-1"),
        }
    )
    service = ScanService(
        source=source,
        period=period(),
        resolver=resolver,
        excluded_repository_ids=frozenset({DOTFILES_ID}),
    )

    result = service.scan()

    assert result.loaded_session_count == 1
    assert result.excluded_session_count == 2
    assert list(result.sessions_by_repository) == [WORK_ID]
    assert [item.session.session_id for item in result.resolved_sessions] == ["work-1"]


def test_excluded_sessions_are_counted_and_named_in_a_warning() -> None:
    source = _source(["dotfiles-1", "notes-1"])
    resolver = IdResolver(
        {
            "dotfiles-1": _identity("git:github.com/mike/dotfiles", "Dotfiles"),
            "notes-1": _identity("git:github.com/mike/notes", "Notes"),
        }
    )
    service = ScanService(
        source=source,
        period=period(),
        resolver=resolver,
        excluded_repository_ids=frozenset(
            {"git:github.com/mike/dotfiles", "git:github.com/mike/notes"}
        ),
    )

    result = service.scan()

    assert result.loaded_session_count == 0
    assert result.excluded_session_count == 2
    assert result.warnings == [
        "Excluded 2 sessions from configured repositories: Dotfiles, Notes"
    ]


def test_a_configured_repository_with_no_activity_warns_nothing() -> None:
    source = _source(["work-1"])
    resolver = IdResolver({"work-1": _work("work-1")})
    service = ScanService(
        source=source,
        period=period(),
        resolver=resolver,
        excluded_repository_ids=frozenset({DOTFILES_ID}),
    )

    result = service.scan()

    assert result.loaded_session_count == 1
    assert result.excluded_session_count == 0
    assert not any("excluded" in warning for warning in result.warnings)


def test_when_every_session_is_excluded_the_scan_counts_them_all() -> None:
    source = _source(["dotfiles-1", "dotfiles-2", "dotfiles-3"])
    resolver = IdResolver(
        {
            "dotfiles-1": _dotfiles("dotfiles-1"),
            "dotfiles-2": _dotfiles("dotfiles-2"),
            "dotfiles-3": _dotfiles("dotfiles-3"),
        }
    )
    service = ScanService(
        source=source,
        period=period(),
        resolver=resolver,
        excluded_repository_ids=frozenset({DOTFILES_ID}),
    )

    result = service.scan()

    assert result.loaded_session_count == 0
    assert result.excluded_session_count == 3
    assert any("Excluded 3 sessions" in warning for warning in result.warnings)


class BranchAwareSource:
    """A live-repository session and a detached-worktree session that still
    carries the branch its (now-deleted) worktree was checked out to."""

    def __init__(self, *, live_cwd: str, detached_cwd: str, branch: str) -> None:
        self._live_cwd = live_cwd
        self._detached_cwd = detached_cwd
        self._branch = branch

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return [
            SessionDescriptor(harness="claude-code", session_id="live-1"),
            SessionDescriptor(harness="claude-code", session_id="detached-1"),
        ]

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        is_detached = descriptor.session_id == "detached-1"
        return AgentSession(
            harness="claude-code",
            session_id=descriptor.session_id,
            working_directory=self._detached_cwd if is_detached else self._live_cwd,
            branch=self._branch if is_detached else None,
            activities=[
                SessionActivity(
                    activity_id=f"{descriptor.session_id}:a1",
                    activity_type=ActivityType.USER_MESSAGE,
                    timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                    content="Add weekly report generation",
                )
            ],
        )


def test_scan_reattaches_a_detached_session_by_branch(tmp_path, fake_runner) -> None:
    """A worktree removed from disk leaves its session with a fallback identity;
    the live repository sharing its branch absorbs it back, and the scan says so."""

    live_dir = tmp_path / "repo-a"
    live_dir.mkdir()
    source = BranchAwareSource(
        live_cwd=str(live_dir),
        detached_cwd=str(tmp_path / "repo-a-wt"),
        branch="feature/from-worktree",
    )
    resolver = IdResolver(
        {
            "live-1": RepositoryIdentity(
                repository_id="git:github.com/mike/repo-a",
                display_name="Repo A",
                identity_type=RepositoryIdentityType.GIT_REMOTE,
                normalized_remote="github.com/mike/repo-a",
                branch="main",
                working_directory=str(live_dir),
                resolution_method="git_origin_remote",
            ),
            "detached-1": RepositoryIdentity(
                repository_id="harness:claude-code:detached-1",
                display_name="detached-1",
                identity_type=RepositoryIdentityType.HARNESS_PROJECT,
                working_directory=str(tmp_path / "repo-a-wt"),
                resolution_method="harness_project_id",
            ),
        }
    )
    fake_runner.set_output(
        "for-each-ref --format=%(refname) refs/heads refs/remotes",
        "refs/heads/feature/from-worktree",
    )
    service = ScanService(
        source=source, period=period(), resolver=resolver, runner=fake_runner
    )

    result = service.scan()

    assert list(result.sessions_by_repository) == ["git:github.com/mike/repo-a"]
    assert {
        item.session.session_id
        for item in result.sessions_by_repository["git:github.com/mike/repo-a"]
    } == {"live-1", "detached-1"}
    assert any(
        "Reattached 1 session(s) to their repository by branch" in warning
        for warning in result.warnings
    ), result.warnings
    assert not any("fallback repository identity" in warning for warning in result.warnings)


def test_scan_with_nothing_to_reattach_behaves_like_the_baseline(fake_runner) -> None:
    """A scan wired with a runner but no detachable sessions must match a scan
    run without one at all — reattachment must be invisible when it finds nothing."""

    baseline = ScanService(
        source=FakeSource(), period=period(), resolver=StaticResolver()
    ).scan()
    with_runner = ScanService(
        source=FakeSource(),
        period=period(),
        resolver=StaticResolver(),
        runner=fake_runner,
    ).scan()

    assert with_runner == baseline
    assert not any("Reattached" in warning for warning in baseline.warnings)


class IiwiAuthoredSource:
    """One human session beside two sessions iiwi's own runs left behind."""

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return [
            SessionDescriptor(harness="opencode", session_id="human"),
            SessionDescriptor(harness="opencode", session_id="synthesis"),
            SessionDescriptor(harness="opencode", session_id="narrative"),
        ]

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        titles = {
            "human": "Add weekly report generation",
            "synthesis": "iiwi-internal: outcome synthesis",
            "narrative": "Iiwi - 2026-07-20 to 2026-07-27",
        }
        return AgentSession(
            harness="opencode",
            session_id=descriptor.session_id,
            title=titles[descriptor.session_id],
            activities=[
                SessionActivity(
                    activity_id=f"{descriptor.session_id}:a1",
                    activity_type=ActivityType.USER_MESSAGE,
                    timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                    content="Add weekly report generation",
                )
            ],
        )


def test_scan_excludes_the_sessions_iiwi_itself_created() -> None:
    result = ScanService(
        source=IiwiAuthoredSource(),
        resolver=StaticResolver(),
        period=period(),
    ).scan()

    assert [item.session.session_id for item in result.resolved_sessions] == ["human"]
    assert result.loaded_session_count == 1
    assert result.warnings == []


class IiwiAuthoredWithMissingTimestampSource:
    """An iiwi-authored session that also carries a timestamp-less activity.

    Iiwi's own runs always set a title, so this combination is real: a dropped
    session must not surface the timestamp-less-activity warning, which would
    name a session absent from every count and list in the result.
    """

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return [SessionDescriptor(harness="opencode", session_id="synthesis")]

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        return AgentSession(
            harness="opencode",
            session_id=descriptor.session_id,
            title="iiwi-internal: outcome synthesis",
            activities=[
                SessionActivity(
                    activity_id="synthesis:a1",
                    activity_type=ActivityType.USER_MESSAGE,
                    timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                    content="Synthesize outcomes",
                ),
                SessionActivity(
                    activity_id="synthesis:a2",
                    activity_type=ActivityType.ASSISTANT_MESSAGE,
                    timestamp=None,
                    content="...",
                ),
            ],
        )


def test_scan_drops_an_iiwi_authored_session_before_any_warning_fires() -> None:
    """A timestamp-less activity on a dropped session must not warn about it —
    the warning would name a session that appears nowhere else in the result."""

    result = ScanService(
        source=IiwiAuthoredWithMissingTimestampSource(),
        resolver=StaticResolver(),
        period=period(),
    ).scan()

    assert result.resolved_sessions == []
    assert result.warnings == []


# --- performance instrumentation ----------------------------------------------


def scan_with_metrics(source: FakeSource) -> PerformanceMetrics:
    metrics = PerformanceMetrics()
    ScanService(
        source=source,
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=TZ),
            until=datetime(2026, 7, 27, tzinfo=TZ),
        ),
        resolver=StaticResolver(),
        metrics=metrics,
    ).scan()
    return metrics


def test_a_scan_times_discovery_export_and_repository_resolution_separately() -> None:
    """Export is the suspected cost; it must be separable from what surrounds it."""

    metrics = scan_with_metrics(FakeSource())

    assert set(metrics.durations) == {
        MetricStage.DISCOVER_SESSIONS,
        MetricStage.EXPORT_SESSIONS,
        MetricStage.RESOLVE_REPOSITORIES,
    }


def test_a_scan_records_the_counts_that_explain_its_timings() -> None:
    source = FakeSource()

    metrics = scan_with_metrics(source)

    assert metrics.counts == {
        "candidate_sessions": 3,
        "loaded_sessions": 3,
        "failed_sessions": 0,
        "repositories": 1,
    }


def test_a_failed_export_is_counted_and_still_timed() -> None:
    """A harness failing slowly is a performance problem, not just a warning."""

    source = FakeSource()
    source.fail_session_ids = {"bad"}

    metrics = scan_with_metrics(source)

    assert metrics.counts["candidate_sessions"] == 3
    assert metrics.counts["loaded_sessions"] == 2
    assert metrics.counts["failed_sessions"] == 1
    assert metrics.durations[MetricStage.EXPORT_SESSIONS] > 0


def test_a_scan_with_no_sessions_records_zeroed_counts_not_missing_ones() -> None:
    source = FakeSource()
    source.descriptors = []

    metrics = scan_with_metrics(source)

    assert metrics.counts == {
        "candidate_sessions": 0,
        "loaded_sessions": 0,
        "failed_sessions": 0,
        "repositories": 0,
    }
    assert MetricStage.EXPORT_SESSIONS not in metrics.durations


def test_a_scan_without_a_collector_still_scans() -> None:
    """Instrumentation is optional wiring, never a precondition for scanning."""

    result = ScanService(
        source=FakeSource(),
        period=DateRange(
            since=datetime(2026, 7, 20, tzinfo=TZ),
            until=datetime(2026, 7, 27, tzinfo=TZ),
        ),
        resolver=StaticResolver(),
    ).scan()

    assert result.loaded_session_count == 3


# --- concurrent session loading -----------------------------------------------


def scan_period() -> DateRange:
    return DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )


def probe_session(session_id: str) -> AgentSession:
    return AgentSession(
        harness="opencode",
        session_id=session_id,
        activities=[
            SessionActivity(
                activity_id=f"{session_id}:a1",
                activity_type=ActivityType.USER_MESSAGE,
                timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                content="Add weekly report generation",
            )
        ],
    )


class BarrierSource:
    """A source whose loads block until `parties` of them are in flight at once.

    A barrier rather than a sleep: if loading ever went back to serial the
    barrier could not fill, so a regression fails the test outright instead of
    merely making it slower, and a loaded CI box cannot make it flaky.
    """

    def __init__(
        self,
        session_ids: list[str],
        *,
        parties: int,
        failing: frozenset[str] = frozenset(),
        timeout: float = 10.0,
    ) -> None:
        self.descriptors = [
            SessionDescriptor(harness="opencode", session_id=session_id)
            for session_id in session_ids
        ]
        self._barrier = threading.Barrier(parties, timeout=timeout)
        self._failing = failing
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return self.descriptors

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            self._barrier.wait()
            if descriptor.session_id in self._failing:
                raise SessionParseError(f"failed export: {descriptor.session_id}")
            return probe_session(descriptor.session_id)
        finally:
            with self._lock:
                self._in_flight -= 1


class ReverseOrderSource:
    """A source that finishes its loads in reverse descriptor order.

    Exists to separate two things a serial loader conflated: the order loads
    *complete* in, and the order their results are *handled* in. Only the second
    is a promise this service makes.
    """

    def __init__(self, session_ids: list[str], *, timeout: float = 10.0) -> None:
        self.descriptors = [
            SessionDescriptor(harness="opencode", session_id=session_id)
            for session_id in session_ids
        ]
        self._last_loaded = threading.Event()
        self._timeout = timeout
        self._lock = threading.Lock()
        self.completion_order: list[str] = []

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return self.descriptors

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        first = self.descriptors[0].session_id
        last = self.descriptors[-1].session_id
        if descriptor.session_id == first:
            self._last_loaded.wait(self._timeout)
        with self._lock:
            self.completion_order.append(descriptor.session_id)
        if descriptor.session_id == last:
            self._last_loaded.set()
        return probe_session(descriptor.session_id)


def run_scan(source, *, progress=None, metrics=None) -> ScanResult:
    return ScanService(
        source=source,
        period=scan_period(),
        resolver=StaticResolver(),
        progress=progress,
        metrics=metrics,
    ).scan()


def test_sessions_are_loaded_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    """The point of the change: four exports wait on each other, not in a queue."""

    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", 4)
    source = BarrierSource(["s1", "s2", "s3", "s4"], parties=4)

    result = run_scan(source)

    assert source.max_in_flight == 4
    assert result.loaded_session_count == 4


def test_concurrency_stays_within_the_worker_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unbounded loading would launch one coding-agent subprocess per session."""

    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", 2)
    source = BarrierSource(["s1", "s2", "s3", "s4", "s5", "s6"], parties=2)

    result = run_scan(source)

    assert source.max_in_flight == 2
    assert result.loaded_session_count == 6


def test_results_follow_descriptor_order_not_completion_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", 4)
    source = ReverseOrderSource(["s1", "s2", "s3"])

    result = run_scan(source)

    assert source.completion_order == ["s2", "s3", "s1"]
    assert [
        resolved.session.session_id for resolved in result.resolved_sessions
    ] == ["s1", "s2", "s3"]


def test_warnings_follow_descriptor_order_not_completion_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warning order is user-visible output; concurrency must not shuffle it."""

    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", 4)
    source = BarrierSource(
        ["s1", "s2", "s3", "s4"],
        parties=4,
        failing=frozenset({"s1", "s3"}),
    )

    result = run_scan(source)

    assert [warning.split()[1] for warning in result.warnings] == ["s1", "s3"]


def test_progress_still_advances_once_per_descriptor_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", 4)
    progress = RecordingProgressReporter()

    run_scan(ReverseOrderSource(["s1", "s2", "s3"]), progress=progress)

    advances = [event[1] for event in progress.events if event[0] == "advance"]
    assert advances == [1, 2, 3]


def test_an_early_failure_does_not_cancel_the_sessions_queued_behind_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`Executor.map` would end the run here; every later session must survive."""

    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", 4)
    source = BarrierSource(["s1", "s2", "s3", "s4"], parties=4, failing=frozenset({"s1"}))

    result = run_scan(source)

    assert result.failed_session_count == 1
    assert [
        resolved.session.session_id for resolved in result.resolved_sessions
    ] == ["s2", "s3", "s4"]


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_the_scan_result_is_identical_at_every_worker_count(
    workers: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The acceptance criterion: parallelism changes the clock, nothing else."""

    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", 1)
    serial_source = FakeSource()
    serial_source.fail_session_ids = {"bad"}
    serial = run_scan(serial_source)

    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", workers)
    parallel_source = FakeSource()
    parallel_source.fail_session_ids = {"bad"}
    parallel = run_scan(parallel_source)

    assert parallel == serial


def test_the_export_metric_measures_waiting_not_the_sum_across_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Summing per-session durations would report more time than the scan took.

    Deliberately relative rather than an absolute number of seconds: the claim
    is that the stage cannot outrun the clock, which holds on any machine.
    """

    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", 4)
    metrics = PerformanceMetrics()
    source = BarrierSource(["s1", "s2", "s3", "s4"], parties=4)

    started = time.perf_counter()
    run_scan(source, metrics=metrics)
    elapsed = time.perf_counter() - started

    assert metrics.durations[MetricStage.EXPORT_SESSIONS] <= elapsed


def test_every_load_failing_still_raises_rather_than_reporting_an_empty_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", 4)
    source = BarrierSource(
        ["s1", "s2", "s3", "s4"],
        parties=4,
        failing=frozenset({"s1", "s2", "s3", "s4"}),
    )

    with pytest.raises(HarnessSourceError):
        run_scan(source)


def test_an_unexpected_load_error_still_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the two documented failures are per-session; anything else is a bug."""

    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", 4)

    class BrokenSource:
        descriptors = [SessionDescriptor(harness="opencode", session_id="s1")]

        def discover(self, period: DateRange) -> list[SessionDescriptor]:
            return self.descriptors

        def load(self, descriptor: SessionDescriptor) -> AgentSession:
            raise RuntimeError("mapper blew up")

    with pytest.raises(RuntimeError, match="mapper blew up"):
        run_scan(BrokenSource())


# --- the session cache, seen from a whole scan --------------------------------


class StampedSource:
    """A source whose descriptors carry update times, so they can be cached."""

    def __init__(self, updated: dict[str, datetime]) -> None:
        self.updated = dict(updated)
        self.load_calls: list[str] = []

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return [
            SessionDescriptor(harness="opencode", session_id=session_id, updated_at=stamp)
            for session_id, stamp in self.updated.items()
        ]

    def load(self, target: SessionDescriptor) -> AgentSession:
        self.load_calls.append(target.session_id)
        return probe_session(target.session_id)


def cached_scan(source: StampedSource, path, **kwargs) -> ScanResult:
    return run_scan(
        CachingSessionSource(
            source=source,
            cache=SessionCache(path=path, adapter_version=adapter_version(sanitized=False)),
            **kwargs,
        )
    )


def test_a_cached_scan_produces_the_same_result_as_an_uncached_one(tmp_path) -> None:
    """The acceptance criterion: the cache changes the clock, not the report."""

    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    uncached = run_scan(StampedSource({"s1": stamp, "s2": stamp, "s3": stamp}))
    source = StampedSource({"s1": stamp, "s2": stamp, "s3": stamp})
    cached_scan(source, tmp_path / "c.db")

    warm = cached_scan(source, tmp_path / "c.db")

    assert warm == uncached


def test_a_warm_scan_exports_nothing(tmp_path) -> None:
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = StampedSource({"s1": stamp, "s2": stamp, "s3": stamp})
    cached_scan(source, tmp_path / "c.db")
    source.load_calls.clear()

    result = cached_scan(source, tmp_path / "c.db")

    assert source.load_calls == []
    assert result.loaded_session_count == 3


def test_a_broken_cache_warns_through_the_scan_result(tmp_path) -> None:
    """A cache problem is worth saying out loud, and worth saying only once."""

    path = tmp_path / "c.db"
    path.write_bytes(b"not a database")
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = StampedSource({"s1": stamp, "s2": stamp})

    result = cached_scan(source, path)

    assert result.loaded_session_count == 2
    assert [w for w in result.warnings if "session cache" in w]
    assert len([w for w in result.warnings if "session cache" in w]) == 1


def test_cache_counters_reach_the_performance_summary(tmp_path) -> None:
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = StampedSource({"s1": stamp, "s2": stamp})
    cached_scan(source, tmp_path / "c.db")
    metrics = PerformanceMetrics()

    cached_scan(source, tmp_path / "c.db", metrics=metrics)

    assert metrics.counts["cache_hits"] == 2


def test_a_cached_scan_still_loads_concurrently(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caching sits inside the thread pool, so a cold scan keeps its parallelism."""

    monkeypatch.setattr(scan_module, "_SESSION_LOAD_WORKERS", 4)
    barrier = BarrierSource(["s1", "s2", "s3", "s4"], parties=4)
    for target in barrier.descriptors:
        target.updated_at = datetime(2026, 7, 22, tzinfo=TZ)

    result = run_scan(
        CachingSessionSource(
            source=barrier,
            cache=SessionCache(
                path=tmp_path / "c.db",
                adapter_version=adapter_version(sanitized=False),
            ),
        )
    )

    assert barrier.max_in_flight == 4
    assert result.loaded_session_count == 4
