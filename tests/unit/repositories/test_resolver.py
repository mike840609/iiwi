from dataclasses import dataclass, field
from pathlib import Path

from iiwi.models.repository import RepositoryIdentity, RepositoryIdentityType
from iiwi.models.session import AgentSession
from iiwi.process import CommandResult
from iiwi.repositories.resolver import RepositoryResolver, reattach_by_branch


def test_same_remote_groups_different_worktrees(fake_git_runner) -> None:
    fake_git_runner.set_output("remote get-url origin", "git@github.com:mike/repo.git")
    fake_git_runner.set_output("rev-parse --git-common-dir", "/repo/.git")
    fake_git_runner.set_output("branch --show-current", "feature/test")
    resolver = RepositoryResolver(runner=fake_git_runner)

    first = resolver.resolve(
        AgentSession(harness="opencode", session_id="s1", working_directory="/worktree/a")
    )
    second = resolver.resolve(
        AgentSession(harness="opencode", session_id="s2", working_directory="/worktree/b")
    )

    assert first.repository_id == second.repository_id == "git:github.com/mike/repo"
    assert first.branch == "feature/test"


def test_same_basename_with_different_owners_remains_different(fake_git_runner) -> None:
    first_runner = fake_git_runner
    first_runner.set_output("remote get-url origin", "git@github.com:team-a/api.git")
    second_runner = type(fake_git_runner)()
    second_runner.set_output("remote get-url origin", "git@github.com:team-b/api.git")

    first = RepositoryResolver(runner=first_runner).resolve(
        AgentSession(harness="opencode", session_id="s1", working_directory="/a/api")
    )
    second = RepositoryResolver(runner=second_runner).resolve(
        AgentSession(harness="opencode", session_id="s2", working_directory="/b/api")
    )

    assert first.repository_id == "git:github.com/team-a/api"
    assert second.repository_id == "git:github.com/team-b/api"


def test_no_remote_falls_back_to_hashed_git_common_dir(fake_git_runner) -> None:
    fake_git_runner.set_result(
        "remote get-url origin",
        CommandResult(returncode=2, stdout="", stderr="no remote"),
    )
    fake_git_runner.set_output("rev-parse --git-common-dir", "/private/repo/.git")
    resolver = RepositoryResolver(runner=fake_git_runner)

    identity = resolver.resolve(
        AgentSession(harness="opencode", session_id="s1", working_directory="/worktree/a")
    )

    assert identity.identity_type == RepositoryIdentityType.GIT_COMMON_DIR
    assert identity.repository_id.startswith("git-common:")
    assert "/private/repo" not in identity.repository_id


def test_deleted_path_falls_back_to_harness_project_id(fake_git_runner) -> None:
    fake_git_runner.returncode = 1
    resolver = RepositoryResolver(runner=fake_git_runner)

    identity = resolver.resolve(
        AgentSession(
            harness="opencode",
            session_id="s1",
            working_directory="/deleted/worktree",
            project_id_hint="project-1",
        )
    )

    assert identity.repository_id == "harness:opencode:project-1"
    assert identity.identity_type == RepositoryIdentityType.HARNESS_PROJECT


def test_missing_all_hints_uses_per_session_unknown(fake_git_runner) -> None:
    identity = RepositoryResolver(runner=fake_git_runner).resolve(
        AgentSession(harness="opencode", session_id="s1")
    )

    assert identity.repository_id == "unknown:opencode:s1"
    assert identity.identity_type == RepositoryIdentityType.UNKNOWN


def test_git_remote_short_circuits_common_dir(fake_git_runner) -> None:
    fake_git_runner.set_output("remote get-url origin", "git@github.com:mike/repo.git")
    fake_git_runner.set_output("branch --show-current", "feature/test")
    resolver = RepositoryResolver(runner=fake_git_runner)

    identity = resolver.resolve(
        AgentSession(harness="opencode", session_id="s1", working_directory="/worktree/a")
    )

    assert identity.identity_type == RepositoryIdentityType.GIT_REMOTE
    assert identity.branch == "feature/test"
    git_calls = [call for call in fake_git_runner.calls if call[0] == "git"]
    assert ["git", "-C", "/worktree/a", "rev-parse", "--git-common-dir"] not in git_calls


def test_same_cwd_memoizes_git_lookups_across_sessions(fake_git_runner) -> None:
    fake_git_runner.set_output("remote get-url origin", "git@github.com:mike/repo.git")
    fake_git_runner.set_output("branch --show-current", "feature/test")
    resolver = RepositoryResolver(runner=fake_git_runner)

    first = resolver.resolve(
        AgentSession(harness="opencode", session_id="s1", working_directory="/worktree/a")
    )
    second = resolver.resolve(
        AgentSession(harness="opencode", session_id="s2", working_directory="/worktree/a")
    )

    assert first.repository_id == second.repository_id
    git_calls = [call for call in fake_git_runner.calls if call[0] == "git"]
    assert len(git_calls) == 2
    assert git_calls == [
        ["git", "-C", "/worktree/a", "remote", "get-url", "origin"],
        ["git", "-C", "/worktree/a", "branch", "--show-current"],
    ]


@dataclass
class BranchListRunner:
    """Fake `reattach_by_branch` git runner: refs keyed by the `-C` working directory.

    A `cwd` with no entry in `refs_by_cwd` fails the git call (returncode 1),
    modeling a repository git cannot read from.
    """

    refs_by_cwd: dict[str, list[str]] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)

    def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        cwd = args[2]
        if cwd not in self.refs_by_cwd:
            return CommandResult(returncode=1, stdout="", stderr="not a git repository")
        return CommandResult(returncode=0, stdout="\n".join(self.refs_by_cwd[cwd]), stderr="")


@dataclass
class RaisingRunner:
    """A runner whose git calls always raise, modeling a missing git executable."""

    def run(self, args: list[str]) -> CommandResult:
        raise FileNotFoundError("git not found")


def _live_identity(repository_id: str, cwd: str) -> RepositoryIdentity:
    return RepositoryIdentity(
        repository_id=repository_id,
        display_name=repository_id,
        identity_type=RepositoryIdentityType.GIT_REMOTE,
        working_directory=cwd,
        branch="main",
        resolution_method="git_origin_remote",
    )


def _fallback_pair(
    session_id: str, *, branch: str | None, cwd: str = "/deleted/worktree"
) -> tuple[AgentSession, RepositoryIdentity]:
    session = AgentSession(
        harness="claude-code",
        session_id=session_id,
        working_directory=cwd,
        branch=branch,
    )
    identity = RepositoryIdentity(
        repository_id=f"harness:claude-code:{session_id}",
        display_name=session_id,
        identity_type=RepositoryIdentityType.HARNESS_PROJECT,
        working_directory=cwd,
        resolution_method="harness_project_id",
    )
    return session, identity


def _by_session_id(
    reattached: list[tuple[AgentSession, RepositoryIdentity]],
) -> dict[str, RepositoryIdentity]:
    return {session.session_id: identity for session, identity in reattached}


def test_reattaches_a_fallback_entry_with_exactly_one_branch_match(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo-a"
    repo_dir.mkdir()
    live_session = AgentSession(
        harness="claude-code", session_id="live-1", working_directory=str(repo_dir)
    )
    live_identity = _live_identity("git:github.com/mike/repo-a", str(repo_dir))
    session, fallback_identity = _fallback_pair(
        "detached-1", branch="fix/foo", cwd="/deleted/worktree"
    )
    runner = BranchListRunner(
        refs_by_cwd={str(repo_dir): ["refs/heads/fix/foo", "refs/heads/main"]}
    )

    reattached, count = reattach_by_branch(
        [(live_session, live_identity), (session, fallback_identity)], runner=runner
    )

    assert count == 1
    result = _by_session_id(reattached)["detached-1"]
    assert result.repository_id == "git:github.com/mike/repo-a"
    assert result.identity_type == RepositoryIdentityType.GIT_REMOTE
    # The matched live repository's identity is kept, but the candidate's own
    # working directory and branch — where the work actually happened — survive.
    assert result.working_directory == "/deleted/worktree"
    assert result.branch == "fix/foo"


def test_a_branch_in_two_live_repositories_is_left_untouched(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_a.mkdir()
    repo_b = tmp_path / "repo-b"
    repo_b.mkdir()
    live_a = AgentSession(
        harness="claude-code", session_id="live-a", working_directory=str(repo_a)
    )
    live_b = AgentSession(
        harness="claude-code", session_id="live-b", working_directory=str(repo_b)
    )
    identity_a = _live_identity("git:github.com/mike/a", str(repo_a))
    identity_b = _live_identity("git:github.com/mike/b", str(repo_b))
    session, fallback_identity = _fallback_pair("detached-1", branch="shared-branch")
    runner = BranchListRunner(
        refs_by_cwd={
            str(repo_a): ["refs/heads/shared-branch"],
            str(repo_b): ["refs/heads/shared-branch"],
        }
    )

    reattached, count = reattach_by_branch(
        [(live_a, identity_a), (live_b, identity_b), (session, fallback_identity)],
        runner=runner,
    )

    assert count == 0
    assert _by_session_id(reattached)["detached-1"] is fallback_identity


def test_a_branch_in_no_live_repository_is_left_untouched(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo-a"
    repo_dir.mkdir()
    live_session = AgentSession(
        harness="claude-code", session_id="live-1", working_directory=str(repo_dir)
    )
    live_identity = _live_identity("git:github.com/mike/a", str(repo_dir))
    session, fallback_identity = _fallback_pair("detached-1", branch="ghost-branch")
    runner = BranchListRunner(refs_by_cwd={str(repo_dir): ["refs/heads/main"]})

    reattached, count = reattach_by_branch(
        [(live_session, live_identity), (session, fallback_identity)], runner=runner
    )

    assert count == 0
    assert _by_session_id(reattached)["detached-1"] is fallback_identity


def test_a_fallback_entry_without_a_branch_is_left_untouched(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo-a"
    repo_dir.mkdir()
    live_session = AgentSession(
        harness="claude-code", session_id="live-1", working_directory=str(repo_dir)
    )
    live_identity = _live_identity("git:github.com/mike/a", str(repo_dir))
    session, fallback_identity = _fallback_pair("detached-1", branch=None)
    runner = BranchListRunner(refs_by_cwd={str(repo_dir): ["refs/heads/main"]})

    reattached, count = reattach_by_branch(
        [(live_session, live_identity), (session, fallback_identity)], runner=runner
    )

    assert count == 0
    assert _by_session_id(reattached)["detached-1"] is fallback_identity


def test_a_live_repository_with_a_deleted_working_directory_is_not_a_match_source() -> None:
    live_session = AgentSession(
        harness="claude-code", session_id="live-1", working_directory="/does/not/exist/repo"
    )
    live_identity = _live_identity("git:github.com/mike/a", "/does/not/exist/repo")
    session, fallback_identity = _fallback_pair("detached-1", branch="fix/foo")
    runner = BranchListRunner(refs_by_cwd={"/does/not/exist/repo": ["refs/heads/fix/foo"]})

    reattached, count = reattach_by_branch(
        [(live_session, live_identity), (session, fallback_identity)], runner=runner
    )

    assert count == 0
    assert runner.calls == []
    assert _by_session_id(reattached)["detached-1"] is fallback_identity


def test_a_remote_tracking_branch_matches_after_stripping_the_remote_name(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo-a"
    repo_dir.mkdir()
    live_session = AgentSession(
        harness="claude-code", session_id="live-1", working_directory=str(repo_dir)
    )
    live_identity = _live_identity("git:github.com/mike/a", str(repo_dir))
    session, fallback_identity = _fallback_pair("detached-1", branch="fix/foo")
    runner = BranchListRunner(refs_by_cwd={str(repo_dir): ["refs/remotes/origin/fix/foo"]})

    reattached, count = reattach_by_branch(
        [(live_session, live_identity), (session, fallback_identity)], runner=runner
    )

    assert count == 1
    assert _by_session_id(reattached)["detached-1"].repository_id == "git:github.com/mike/a"


def test_a_raising_git_call_is_treated_as_no_branches_not_an_error(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo-a"
    repo_dir.mkdir()
    live_session = AgentSession(
        harness="claude-code", session_id="live-1", working_directory=str(repo_dir)
    )
    live_identity = _live_identity("git:github.com/mike/a", str(repo_dir))
    session, fallback_identity = _fallback_pair("detached-1", branch="fix/foo")
    runner = RaisingRunner()

    reattached, count = reattach_by_branch(
        [(live_session, live_identity), (session, fallback_identity)], runner=runner
    )

    assert count == 0
    assert _by_session_id(reattached)["detached-1"] is fallback_identity
