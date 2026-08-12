from datetime import datetime
from zoneinfo import ZoneInfo

from iiwi.errors import SessionParseError
from iiwi.models.repository import RepositoryIdentity, RepositoryIdentityType
from iiwi.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
)
from iiwi.models.time_range import DateRange
from iiwi.progress import ProgressStage
from iiwi.services.scan import ScanService
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
        detached_cwd="/deleted/worktree",
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
                working_directory="/deleted/worktree",
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
