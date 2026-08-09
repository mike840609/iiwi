"""Resolve canonical repository identities for normalized sessions."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Protocol

from iiwi.models.repository import RepositoryIdentity, RepositoryIdentityType
from iiwi.models.session import AgentSession
from iiwi.process import CommandResult
from iiwi.repositories.remote import normalize_git_remote, repository_display_name


class Runner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


def _hash_identity(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:12]


def _normalize_local_path(value: str, *, base: str | None = None) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() and base is not None:
        path = Path(base).expanduser() / path
    return str(path.resolve(strict=False))


def _basename(value: str, fallback: str) -> str:
    name = Path(value).name
    return repository_display_name(name) if name else fallback


class RepositoryResolver:
    """Apply remote/common-dir/harness/path/unknown identity priority."""

    def __init__(self, *, runner: Runner) -> None:
        self._runner = runner
        self._git_cache: dict[str, dict[tuple[str, ...], CommandResult]] = {}

    def _git(self, cwd: str, *args: str) -> CommandResult:
        cache = self._git_cache.setdefault(_normalize_local_path(cwd), {})
        cached = cache.get(args)
        if cached is not None:
            return cached
        try:
            result = self._runner.run(["git", "-C", cwd, *args])
        except (FileNotFoundError, TimeoutError, OSError) as exc:
            result = CommandResult(returncode=1, stdout="", stderr=type(exc).__name__)
        cache[args] = result
        return result

    def resolve(self, session: AgentSession) -> RepositoryIdentity:
        cwd = session.working_directory
        branch: str | None = None
        common_dir: str | None = None

        if cwd:
            remote_result = self._git(cwd, "remote", "get-url", "origin")
            if remote_result.returncode == 0 and remote_result.stdout.strip():
                try:
                    normalized_remote = normalize_git_remote(remote_result.stdout.strip())
                except ValueError:
                    normalized_remote = None
                if normalized_remote is not None:
                    branch_result = self._git(cwd, "branch", "--show-current")
                    if branch_result.returncode == 0:
                        branch = branch_result.stdout.strip() or None
                    return RepositoryIdentity(
                        repository_id=f"git:{normalized_remote}",
                        display_name=repository_display_name(normalized_remote),
                        identity_type=RepositoryIdentityType.GIT_REMOTE,
                        normalized_remote=normalized_remote,
                        branch=branch,
                        working_directory=cwd,
                        resolution_method="git_origin_remote",
                    )

            common_result = self._git(cwd, "rev-parse", "--git-common-dir")
            branch_result = self._git(cwd, "branch", "--show-current")
            if branch_result.returncode == 0:
                branch = branch_result.stdout.strip() or None
            if common_result.returncode == 0 and common_result.stdout.strip():
                common_dir = _normalize_local_path(common_result.stdout.strip(), base=cwd)

            if common_dir is not None:
                return RepositoryIdentity(
                    repository_id=f"git-common:{_hash_identity(common_dir)}",
                    display_name=_basename(cwd, "Local Repository"),
                    identity_type=RepositoryIdentityType.GIT_COMMON_DIR,
                    branch=branch,
                    working_directory=cwd,
                    resolution_method="git_common_dir",
                )

        if session.project_id_hint:
            return RepositoryIdentity(
                repository_id=f"harness:{session.harness}:{session.project_id_hint}",
                display_name=session.project_id_hint,
                identity_type=RepositoryIdentityType.HARNESS_PROJECT,
                branch=branch,
                working_directory=cwd,
                resolution_method="harness_project_id",
            )

        if cwd:
            normalized_path = _normalize_local_path(cwd)
            return RepositoryIdentity(
                repository_id=f"path:{_hash_identity(normalized_path)}",
                display_name=_basename(normalized_path, "Local Project"),
                identity_type=RepositoryIdentityType.PATH_FALLBACK,
                branch=branch,
                working_directory=cwd,
                resolution_method="normalized_path",
            )

        return RepositoryIdentity(
            repository_id=f"unknown:{session.harness}:{session.session_id}",
            display_name="Unknown",
            identity_type=RepositoryIdentityType.UNKNOWN,
            resolution_method="per_session_unknown",
        )


_LIVE_IDENTITY_TYPES = frozenset(
    {RepositoryIdentityType.GIT_REMOTE, RepositoryIdentityType.GIT_COMMON_DIR}
)
_CANDIDATE_IDENTITY_TYPES = frozenset(
    {RepositoryIdentityType.HARNESS_PROJECT, RepositoryIdentityType.PATH_FALLBACK}
)


def _live_repositories(
    resolved: list[tuple[AgentSession, RepositoryIdentity]],
) -> dict[str, RepositoryIdentity]:
    """Distinct live repositories, deduplicated by id.

    Several sessions in `resolved` typically resolve to the same repository; the
    branch lookup must run once per repository, not once per session, so this
    collapses duplicates before any git call happens.
    """

    live: dict[str, RepositoryIdentity] = {}
    for _, identity in resolved:
        if (
            identity.identity_type in _LIVE_IDENTITY_TYPES
            and identity.working_directory
            and Path(identity.working_directory).exists()
        ):
            live.setdefault(identity.repository_id, identity)
    return live


def _branches_at(cwd: str, *, runner: Runner, cache: dict[str, frozenset[str]]) -> frozenset[str]:
    """Every branch a live repository has, local or remote-tracking, normalized.

    A single `for-each-ref` over `refs/heads` and `refs/remotes` covers both.
    `%(refname)` rather than `%(refname:short)` is what makes the two
    distinguishable afterwards: a merged list of short names cannot tell a local
    branch that happens to contain a slash (this repo has `feat/ux-enhancement`)
    from a remote-tracking ref that needs its leading remote name stripped
    (`origin/feat/ux-enhancement` -> `feat/ux-enhancement`) — both would print as
    `feat/ux-enhancement`-shaped strings. Guessing wrong there is exactly the
    silent-wrong-attachment failure this function exists to avoid.
    """

    cached = cache.get(cwd)
    if cached is not None:
        return cached

    try:
        result = runner.run(
            ["git", "-C", cwd, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes"]
        )
    except (FileNotFoundError, TimeoutError, OSError):
        result = None

    names: set[str] = set()
    if result is not None and result.returncode == 0:
        for line in result.stdout.splitlines():
            ref = line.strip()
            if not ref:
                continue
            if ref.startswith("refs/heads/"):
                names.add(ref.removeprefix("refs/heads/"))
            elif ref.startswith("refs/remotes/"):
                _, _, branch = ref.removeprefix("refs/remotes/").partition("/")
                if branch and branch != "HEAD":
                    names.add(branch)

    frozen = frozenset(names)
    cache[cwd] = frozen
    return frozen


def reattach_by_branch(
    resolved: list[tuple[AgentSession, RepositoryIdentity]],
    *,
    runner: Runner,
) -> tuple[list[tuple[AgentSession, RepositoryIdentity]], int]:
    """Reattach a detached worktree's session to its live repository by branch.

    A worktree removed from disk defeats `RepositoryResolver.resolve`'s git
    lookups, so the session falls back to a harness/path identity and appears as
    its own detached row. The branch Claude Code recorded for that worktree
    usually still exists in the live repository it was cut from, so this matches
    on it — but only when exactly one live repository has that branch. `main`
    exists in nearly every repository; a wrong match would silently put
    someone's work under the wrong heading, so an ambiguous or absent match
    leaves the entry untouched rather than guessing.
    """

    live_repositories = _live_repositories(resolved)
    branch_cache: dict[str, frozenset[str]] = {}

    reattached_count = 0
    reattached: list[tuple[AgentSession, RepositoryIdentity]] = []
    for session, identity in resolved:
        branch = session.branch
        if identity.identity_type in _CANDIDATE_IDENTITY_TYPES and branch:
            matches = [
                live
                for live in live_repositories.values()
                if live.working_directory is not None
                and branch
                in _branches_at(live.working_directory, runner=runner, cache=branch_cache)
            ]
            if len(matches) == 1:
                matched = matches[0]
                reattached.append(
                    (
                        session,
                        matched.model_copy(
                            update={
                                "working_directory": identity.working_directory,
                                "branch": branch,
                            }
                        ),
                    )
                )
                reattached_count += 1
                continue
        reattached.append((session, identity))

    return reattached, reattached_count
