"""Summarizer contract and deterministic evidence helpers."""

from abc import ABC, abstractmethod

from iiwi.models.evidence import RepositoryEvidence
from iiwi.models.report import RepositorySummary, SessionRef


class RepositorySummarizer(ABC):
    @abstractmethod
    def summarize(self, evidence: RepositoryEvidence) -> RepositorySummary:
        """Create a repository summary from structured evidence."""


def _normalized_title(title: str | None) -> str | None:
    """Collapse whitespace so free-text titles stay on one Markdown list item.

    Length is not this function's job: `extract_evidence` caps the title when it
    enters the evidence, which is the only point that also covers the outbound
    LLM request.
    """

    if title is None:
        return None
    return " ".join(title.split()) or None


def session_refs(evidence: RepositoryEvidence) -> list[SessionRef]:
    """Return session identifiers exactly as recorded; never model-generated.

    Unlike the summary lists, this one is deliberately uncapped: it is the report's
    only index back to individual sessions, and a busy repository is exactly where
    that index is needed. Operators bound it with `--root-only` or a shorter period.
    """

    return [
        SessionRef(
            session_id=session.session_id,
            title=_normalized_title(session.title),
        )
        for session in evidence.sessions
    ]


def session_directories(evidence: RepositoryEvidence) -> list[str]:
    """Return the distinct working directories seen for one repository."""

    directories: list[str] = []
    for session in evidence.sessions:
        directory = (session.working_directory or "").strip()
        if directory and directory not in directories:
            directories.append(directory)
    return sorted(directories)
