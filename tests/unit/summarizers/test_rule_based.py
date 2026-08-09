from iiwi.models.evidence import (
    EvidenceConfidence,
    EvidenceItem,
    EvidenceStatus,
    RepositoryEvidence,
    SessionEvidence,
)
from iiwi.summarizers.rule_based import RuleBasedSummarizer


def item(text: str, status: EvidenceStatus, confidence: EvidenceConfidence) -> EvidenceItem:
    return EvidenceItem(
        text=text,
        source_activity_ids=[f"source:{text}"],
        confidence=confidence,
        extraction_method="test",
        status=status,
    )


def test_rule_summary_separates_completed_and_in_progress() -> None:
    evidence = RepositoryEvidence(
        repository_id="git:github.com/mike/iiwi",
        display_name="Iiwi",
        normalized_remote="github.com/mike/iiwi",
        branches=["main"],
        sessions=[
            SessionEvidence(
                session_id="s1",
                repository_id="git:github.com/mike/iiwi",
                goals=[item("Add cache", EvidenceStatus.IN_PROGRESS, EvidenceConfidence.HIGH)],
                outcomes=[
                    item("Tests passed", EvidenceStatus.COMPLETED, EvidenceConfidence.HIGH),
                    item("Claimed done", EvidenceStatus.UNKNOWN, EvidenceConfidence.LOW),
                ],
                files_changed=[
                    item("src/cache.py", EvidenceStatus.UNKNOWN, EvidenceConfidence.HIGH)
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert "Tests passed" in summary.completed
    assert "Add cache" in summary.in_progress
    assert "Claimed done" not in summary.completed
    assert summary.key_files == ["src/cache.py"]
    assert summary.session_count == 1


def test_rule_summary_returns_complete_deduplicated_sorted_lists() -> None:
    """Truncation belongs to the renderer, which is the report's only cap."""

    evidence = RepositoryEvidence(
        repository_id="repo",
        display_name="Repo",
        sessions=[
            SessionEvidence(
                session_id="s1",
                repository_id="repo",
                outcomes=[
                    item(
                        f"Completed {index:02d}",
                        EvidenceStatus.COMPLETED,
                        EvidenceConfidence.HIGH,
                    )
                    for index in range(22)
                ]
                + [
                    item(
                        "Completed 00",
                        EvidenceStatus.COMPLETED,
                        EvidenceConfidence.HIGH,
                    )
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert len(summary.completed) == 22
    assert summary.completed[0] == "Completed 00"
    assert summary.completed[-1] == "Completed 21"
    assert not any("Additional items omitted" in text for text in summary.completed)


def test_medium_confidence_completed_evidence_is_marked_inferred() -> None:
    """An observed outcome reads plainly; an inferred one is labelled as inferred."""

    evidence = RepositoryEvidence(
        repository_id="git:github.com/mike/iiwi",
        display_name="Iiwi",
        sessions=[
            SessionEvidence(
                session_id="sess-1",
                repository_id="git:github.com/mike/iiwi",
                outcomes=[
                    EvidenceItem(
                        text="Coverage threshold met",
                        source_activity_ids=["a-1"],
                        confidence=EvidenceConfidence.MEDIUM,
                        extraction_method="test_only_medium_signal",
                        status=EvidenceStatus.COMPLETED,
                    ),
                    EvidenceItem(
                        text="Verification passed: ruff check .",
                        source_activity_ids=["a-2"],
                        confidence=EvidenceConfidence.HIGH,
                        extraction_method="successful_verification_command",
                        status=EvidenceStatus.COMPLETED,
                    ),
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert "Coverage threshold met (inferred)" in summary.completed
    assert "Verification passed: ruff check ." in summary.completed


def test_unobserved_outcomes_are_listed_in_progress_not_completed() -> None:
    """A Claude Code verification run has no exit code, so no success is claimed.

    The item must still reach the report: an unobserved outcome belongs under
    In Progress, never under Completed, and never nowhere.
    """

    evidence = RepositoryEvidence(
        repository_id="git:github.com/mike/iiwi",
        display_name="Iiwi",
        sessions=[
            SessionEvidence(
                session_id="sess-1",
                repository_id="git:github.com/mike/iiwi",
                outcomes=[
                    EvidenceItem(
                        text="Ran verification command: pytest -q",
                        source_activity_ids=["a-1"],
                        confidence=EvidenceConfidence.MEDIUM,
                        extraction_method="stderr_heuristic",
                        status=EvidenceStatus.UNKNOWN,
                    )
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert summary.completed == []
    assert summary.in_progress == ["Ran verification command: pytest -q"]


def test_low_confidence_outcomes_are_still_excluded() -> None:
    """Assistant self-claims stay out of the report entirely, in every section."""

    evidence = RepositoryEvidence(
        repository_id="git:github.com/mike/iiwi",
        display_name="Iiwi",
        sessions=[
            SessionEvidence(
                session_id="sess-1",
                repository_id="git:github.com/mike/iiwi",
                outcomes=[
                    EvidenceItem(
                        text="I implemented the retry",
                        source_activity_ids=["a-1"],
                        confidence=EvidenceConfidence.LOW,
                        extraction_method="assistant_claim",
                        status=EvidenceStatus.COMPLETED,
                    ),
                    EvidenceItem(
                        text="I fixed the flaky test",
                        source_activity_ids=["a-2"],
                        confidence=EvidenceConfidence.LOW,
                        extraction_method="assistant_claim",
                        status=EvidenceStatus.UNKNOWN,
                    ),
                ],
            )
        ],
    )

    summary = RuleBasedSummarizer().summarize(evidence)

    assert summary.completed == []
    assert summary.in_progress == []
