import pytest

from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import AgentSession
from iiwi.sessions.hierarchy import (
    SessionRelationshipIndex,
    count_child_sessions_by_repository,
    group_resolved_sessions,
)


@pytest.fixture
def resolved_root() -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(harness="opencode", session_id="root"),
        repository=RepositoryIdentity(
            repository_id="git:github.com/org/backend",
            display_name="Backend",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            normalized_remote="github.com/org/backend",
            resolution_method="git_origin_remote",
        ),
    )


@pytest.fixture
def resolved_cross_repo_child() -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id="child",
            parent_session_id="root",
        ),
        repository=RepositoryIdentity(
            repository_id="git:github.com/org/frontend",
            display_name="Frontend",
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            normalized_remote="github.com/org/frontend",
            resolution_method="git_origin_remote",
        ),
    )


def test_child_session_in_another_repository_stays_in_that_repository(
    resolved_root: ResolvedSession,
    resolved_cross_repo_child: ResolvedSession,
) -> None:
    grouped = group_resolved_sessions([resolved_root, resolved_cross_repo_child])

    assert [item.session.session_id for item in grouped["git:github.com/org/backend"]] == [
        "root"
    ]
    assert [item.session.session_id for item in grouped["git:github.com/org/frontend"]] == [
        "child"
    ]


def test_relationship_index_tracks_parent_without_moving_repository(
    resolved_root: ResolvedSession,
    resolved_cross_repo_child: ResolvedSession,
) -> None:
    index = SessionRelationshipIndex.build([resolved_root, resolved_cross_repo_child])

    assert index.parent_by_session["child"] == "root"
    assert index.children_by_parent["root"] == ["child"]
    assert count_child_sessions_by_repository(
        [resolved_root, resolved_cross_repo_child]
    ) == {"git:github.com/org/frontend": 1}
