from iiwi.services.outcomes import _CompactSession
from iiwi.summarizers.outcome_prompt import build_outcome_prompt


def attachment_paragraph() -> str:
    """The paragraph that tells the model what the attachment carries."""

    paragraphs = [
        paragraph
        for paragraph in build_outcome_prompt().split("\n\n")
        if "compact index" in paragraph
    ]
    assert len(paragraphs) == 1
    return paragraphs[0]


def test_outcome_prompt_requires_the_constrained_json_contract() -> None:
    prompt = build_outcome_prompt()

    for key in (
        "outcomes",
        "title",
        "status",
        "impact",
        "source_session_ids",
        "confidence",
        "linkage_signals",
        "kind",
        "value",
    ):
        assert key in prompt


def test_outcome_prompt_preserves_evidence_first_merge_rules() -> None:
    prompt = build_outcome_prompt()

    assert "3–5" in prompt
    assert 'Impact must be ""' in prompt
    assert "unknown session ids" in prompt
    assert "shared_work_id" in prompt
    assert "branch_or_issue" in prompt
    assert "direct_reference" in prompt


def test_outcome_prompt_describes_the_compact_index_it_is_given() -> None:
    prompt = build_outcome_prompt()

    assert "compact index" in prompt
    for field in ("session_id", "repository_id", "title", "branch", "goal", "outcome"):
        assert field in prompt
    assert "Empty fields are omitted" in prompt


def test_outcome_prompt_never_claims_the_payload_truncates_a_field() -> None:
    """The compact index sends goal and outcome whole; saying otherwise is a lie.

    A model told a complete sentence is a fragment discounts its trailing clause,
    which may be the only thing separating two sessions.
    """

    assert "truncat" not in build_outcome_prompt().casefold()


def test_outcome_prompt_names_the_payload_fields_and_no_others() -> None:
    paragraph = attachment_paragraph()

    for name in _CompactSession.model_fields:
        assert name in paragraph
    # Nothing else survives `_compact_session`, so nothing else may be promised.
    for absent in (
        "commands",
        "files_changed",
        "errors",
        "working_directory",
        "source_activity_ids",
        "extraction_method",
        "started_at",
    ):
        assert absent not in paragraph


def test_outcome_prompt_forbids_inventing_the_references_it_cannot_see() -> None:
    prompt = build_outcome_prompt()

    assert "Iiwi reconstructs those from the full local evidence" in prompt
    assert "Never invent a file, commit, or" in prompt
    assert "activity id to fill the gap" in prompt


def test_outcome_prompt_is_audience_neutral() -> None:
    prompt = build_outcome_prompt()

    assert "engineering outcomes" not in prompt.casefold()
    assert "work outcomes" in prompt.casefold()
