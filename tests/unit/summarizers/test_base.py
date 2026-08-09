from iiwi.models.evidence import RepositoryEvidence, SessionEvidence
from iiwi.models.report import SessionRef
from iiwi.summarizers.base import session_directories, session_refs


def _evidence(*sessions: SessionEvidence) -> RepositoryEvidence:
    return RepositoryEvidence(
        repository_id="git:github.com/mike/iiwi",
        display_name="Iiwi",
        sessions=list(sessions),
    )


def test_session_refs_carries_session_id_and_title_in_order() -> None:
    evidence = _evidence(
        SessionEvidence(session_id="s1", repository_id="repo", title="Fix the exporter"),
        SessionEvidence(session_id="s2", repository_id="repo"),
    )

    assert session_refs(evidence) == [
        SessionRef(session_id="s1", title="Fix the exporter"),
        SessionRef(session_id="s2", title=None),
    ]


def test_session_refs_normalizes_free_text_titles_to_one_line() -> None:
    evidence = _evidence(
        SessionEvidence(
            session_id="s1",
            repository_id="repo",
            title="Fix the exporter\n```\n- injected list item",
        ),
        SessionEvidence(session_id="s2", repository_id="repo", title="  \n  "),
    )

    assert session_refs(evidence) == [
        SessionRef(session_id="s1", title="Fix the exporter ``` - injected list item"),
        SessionRef(session_id="s2", title=None),
    ]


def test_session_directories_deduplicates_sorts_and_skips_blank() -> None:
    evidence = _evidence(
        SessionEvidence(session_id="s1", repository_id="repo", working_directory="/worktrees/b"),
        SessionEvidence(session_id="s2", repository_id="repo", working_directory="/worktrees/a"),
        SessionEvidence(session_id="s3", repository_id="repo", working_directory="/worktrees/b"),
        SessionEvidence(session_id="s4", repository_id="repo", working_directory="   "),
        SessionEvidence(session_id="s5", repository_id="repo"),
    )

    assert session_directories(evidence) == ["/worktrees/a", "/worktrees/b"]
