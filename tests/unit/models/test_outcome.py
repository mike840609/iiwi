import pytest

from iiwi.models.outcome import (
    EvidenceRef,
    Outcome,
    OutcomeBucket,
    OutcomeOrigin,
    OutcomeReviewDraft,
    OutcomeSourceGroup,
    OutcomeStatus,
)
from iiwi.models.report_options import DetailLevel, ReportType


def outcome(identifier: str, rank: int, *, bucket=OutcomeBucket.PRIMARY) -> Outcome:
    ref = EvidenceRef(session_id=f"ses-{identifier}", repository_id="repo-a")
    return Outcome(
        id=identifier,
        title=f"Outcome {identifier}",
        status=OutcomeStatus.COMPLETED,
        rank=rank,
        bucket=bucket,
        evidence_refs=[ref],
        source_groups=[OutcomeSourceGroup(id=f"group-{identifier}", evidence_refs=[ref])],
    )


def test_manager_defaults_to_brief_and_explicit_detail_survives_type_change() -> None:
    draft = OutcomeReviewDraft(
        outcomes=[outcome("a", 0)], report_type=ReportType.MANAGER
    )
    assert draft.detail is DetailLevel.BRIEF

    draft.set_detail(DetailLevel.FULL)
    draft.set_report_type(ReportType.ENGINEERING)
    draft.set_report_type(ReportType.MANAGER)

    assert draft.detail is DetailLevel.FULL
    assert draft.detail_overridden is True


def test_constructor_detail_remains_explicit_after_report_type_change() -> None:
    draft = OutcomeReviewDraft(
        outcomes=[outcome("a", 0)],
        report_type=ReportType.MANAGER,
        detail=DetailLevel.FULL,
    )

    draft.set_report_type(ReportType.MANAGER)

    assert draft.detail is DetailLevel.FULL
    assert draft.detail_overridden is True


def test_reorder_normalizes_ranks_without_dropping_candidates() -> None:
    draft = OutcomeReviewDraft(outcomes=[outcome("a", 0), outcome("b", 1)])
    draft.move("b", -1)
    assert [(item.id, item.rank) for item in draft.ordered()] == [("b", 0), ("a", 1)]


def _primary_order(draft: OutcomeReviewDraft) -> list[str]:
    """The primary section as Quick Review lists it — the only order visible there."""

    return [
        item.id for item in draft.ordered() if item.bucket is OutcomeBucket.PRIMARY
    ]


def test_reorder_passes_a_rank_neighbour_hidden_in_another_bucket() -> None:
    draft = OutcomeReviewDraft(
        outcomes=[
            outcome("a", 0),
            outcome("hidden", 1, bucket=OutcomeBucket.MORE),
            outcome("b", 2),
        ]
    )

    draft.move("a", 1)

    assert _primary_order(draft) == ["b", "a"]
    assert [item.id for item in draft.ordered()] == ["b", "hidden", "a"]


def test_reorder_does_nothing_at_either_end_of_its_own_bucket() -> None:
    draft = OutcomeReviewDraft(
        outcomes=[
            outcome("a", 0),
            outcome("b", 1),
            outcome("candidate", 2, bucket=OutcomeBucket.MORE),
        ]
    )

    draft.move("a", -1)
    draft.move("b", 1)

    assert [(item.id, item.rank) for item in draft.ordered()] == [
        ("a", 0),
        ("b", 1),
        ("candidate", 2),
    ]


def test_split_restores_source_groups_and_preserves_evidence() -> None:
    first = EvidenceRef(session_id="ses-a", repository_id="repo-a")
    second = EvidenceRef(session_id="ses-b", repository_id="repo-b")
    merged = Outcome(
        id="merged",
        title="Shared delivery",
        status=OutcomeStatus.COMPLETED,
        rank=0,
        evidence_refs=[first, second],
        source_groups=[
            OutcomeSourceGroup(id="a", title="API", evidence_refs=[first]),
            OutcomeSourceGroup(id="b", title="UI", evidence_refs=[second]),
        ],
    )
    draft = OutcomeReviewDraft(outcomes=[merged])

    draft.split("merged")

    assert [item.title for item in draft.ordered()] == ["API", "UI"]
    assert [item.evidence_refs for item in draft.ordered()] == [[first], [second]]


def test_split_children_do_not_inherit_unsupported_parent_impact() -> None:
    first = EvidenceRef(session_id="ses-a", repository_id="repo-a")
    second = EvidenceRef(session_id="ses-b", repository_id="repo-a")
    merged = Outcome(
        id="merged",
        title="Combined claim",
        status=OutcomeStatus.COMPLETED,
        impact="Aggregate impact only supported by the merge",
        rank=0,
        evidence_refs=[first, second],
        source_groups=[
            OutcomeSourceGroup(id="a", title="API", evidence_refs=[first]),
            OutcomeSourceGroup(id="b", title="UI", evidence_refs=[second]),
        ],
    )
    draft = OutcomeReviewDraft(outcomes=[merged])

    draft.split("merged")

    assert [item.impact for item in draft.ordered()] == ["", ""]


def test_including_more_candidate_promotes_it_to_primary_review_order() -> None:
    more = outcome("more", 1, bucket=OutcomeBucket.MORE)
    more.included = False
    draft = OutcomeReviewDraft(outcomes=[outcome("primary", 0), more])

    draft.toggle_included("more")

    promoted = next(item for item in draft.outcomes if item.id == "more")
    assert promoted.included is True
    assert promoted.bucket is OutcomeBucket.PRIMARY


def test_add_user_outcome_has_no_invented_evidence() -> None:
    draft = OutcomeReviewDraft(outcomes=[])
    added = draft.add_user_outcome("Reviewed launch design", "Reduced ambiguity")
    assert added.origin is OutcomeOrigin.USER_ADDED
    assert added.evidence_refs == []
    assert added.bucket is OutcomeBucket.PRIMARY


def test_split_without_source_groups_preserves_parent_and_raises_value_error() -> None:
    parent = Outcome(
        id="ungrouped",
        title="Ungrouped outcome",
        status=OutcomeStatus.IN_PROGRESS,
        rank=0,
        origin=OutcomeOrigin.USER_ADDED,
    )
    draft = OutcomeReviewDraft(outcomes=[parent])

    with pytest.raises(ValueError, match="cannot split outcome without source groups"):
        draft.split("ungrouped")

    assert draft.outcomes == [parent]
