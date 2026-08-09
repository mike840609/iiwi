"""Repository-first session relationship indexing."""

from collections import defaultdict
from dataclasses import dataclass

from iiwi.models.repository import ResolvedSession


@dataclass(frozen=True)
class SessionRelationshipIndex:
    """Parent/child metadata without changing repository ownership."""

    parent_by_session: dict[str, str]
    children_by_parent: dict[str, list[str]]

    @classmethod
    def build(cls, sessions: list[ResolvedSession]) -> "SessionRelationshipIndex":
        parent_by_session: dict[str, str] = {}
        children: dict[str, list[str]] = defaultdict(list)
        for resolved in sessions:
            parent_id = resolved.session.parent_session_id
            if not parent_id:
                continue
            session_id = resolved.session.session_id
            parent_by_session[session_id] = parent_id
            children[parent_id].append(session_id)
        return cls(
            parent_by_session=parent_by_session,
            children_by_parent=dict(children),
        )


def group_resolved_sessions(
    sessions: list[ResolvedSession],
) -> dict[str, list[ResolvedSession]]:
    """Group by each session's own resolved repository."""

    grouped: dict[str, list[ResolvedSession]] = defaultdict(list)
    for resolved in sessions:
        grouped[resolved.repository.repository_id].append(resolved)
    return dict(grouped)


def count_child_sessions_by_repository(
    sessions: list[ResolvedSession],
) -> dict[str, int]:
    """Count child sessions in the repository where each child actually ran."""

    counts: dict[str, int] = defaultdict(int)
    for resolved in sessions:
        if resolved.session.parent_session_id:
            counts[resolved.repository.repository_id] += 1
    return dict(counts)
