"""Deterministic repository summarization."""

from iiwi.models.evidence import (
    EvidenceConfidence,
    EvidenceItem,
    EvidenceStatus,
    RepositoryEvidence,
)
from iiwi.models.report import RepositorySummary
from iiwi.summarizers.base import (
    RepositorySummarizer,
    session_directories,
    session_refs,
)


def _unique_sorted(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        normalized = " ".join(item.split()).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return sorted(unique, key=str.casefold)


# MEDIUM evidence is inferred rather than observed, so it is labelled in the
# report instead of being presented as a confirmed outcome.
_INFERRED_SUFFIX = " (inferred)"
_REPORTABLE_CONFIDENCE = (EvidenceConfidence.HIGH, EvidenceConfidence.MEDIUM)


def _completed(items: list[EvidenceItem]) -> list[str]:
    return [
        item.text + (_INFERRED_SUFFIX if item.confidence == EvidenceConfidence.MEDIUM else "")
        for item in items
        if item.status == EvidenceStatus.COMPLETED
        and item.confidence in _REPORTABLE_CONFIDENCE
    ]


def _unobserved(items: list[EvidenceItem]) -> list[str]:
    """Return outcome evidence whose result was never observed.

    A verification command whose harness recorded no outcome at all — no exit
    code and no tool-error flag — is recorded as having run and nothing more:
    MEDIUM confidence, status UNKNOWN. Those items must not appear under
    Completed, but they are real work and would otherwise disappear from the
    report entirely, so they are listed as in progress. LOW items — an assistant
    claiming its own success — stay excluded.
    """

    return [
        item.text
        for item in items
        if item.status == EvidenceStatus.UNKNOWN
        and item.confidence == EvidenceConfidence.MEDIUM
    ]


class RuleBasedSummarizer(RepositorySummarizer):
    """Map high-confidence evidence into conservative report sections."""

    def summarize(self, evidence: RepositoryEvidence) -> RepositorySummary:
        completed: list[str] = []
        goals: list[str] = []
        unobserved: list[str] = []
        key_files: list[str] = []

        # `problems_resolved` stays empty here on purpose. Error evidence is always
        # recorded BLOCKED, never COMPLETED, so selecting resolved problems from it
        # could only ever return nothing. The LLM summarizer fills the field from
        # the same error evidence, which is where the section comes from.
        for session in evidence.sessions:
            completed.extend(_completed(session.outcomes))
            goals.extend(
                item.text
                for item in session.goals
                if item.status != EvidenceStatus.COMPLETED
            )
            unobserved.extend(_unobserved(session.outcomes))
            key_files.extend(item.text for item in session.files_changed)

        completed_keys = {item.casefold() for item in completed}
        in_progress = [
            item
            for item in (*goals, *unobserved)
            if item.casefold() not in completed_keys
        ]
        session_count = len(evidence.sessions)
        summary_text = (
            f"{session_count} session{'s' if session_count != 1 else ''} "
            f"captured for {evidence.display_name}."
        )

        return RepositorySummary(
            repository_id=evidence.repository_id,
            display_name=evidence.display_name,
            normalized_remote=evidence.normalized_remote,
            summary=summary_text,
            completed=_unique_sorted(completed),
            in_progress=_unique_sorted(in_progress),
            key_files=_unique_sorted(key_files),
            directories=session_directories(evidence),
            sessions=session_refs(evidence),
            session_count=session_count,
            child_session_count=evidence.child_session_count,
            branches=_unique_sorted(evidence.branches),
        )
