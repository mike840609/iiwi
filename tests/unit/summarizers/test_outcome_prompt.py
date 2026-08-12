from iiwi.summarizers.outcome_prompt import build_outcome_prompt


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
    assert "empty fields are omitted" in prompt


def test_outcome_prompt_forbids_inventing_the_references_it_cannot_see() -> None:
    prompt = build_outcome_prompt()

    assert "Iiwi reconstructs those from the full local evidence" in prompt
    assert "Never invent a file, commit, or" in prompt
    assert "activity id to fill the gap" in prompt


def test_outcome_prompt_is_audience_neutral() -> None:
    prompt = build_outcome_prompt()

    assert "engineering outcomes" not in prompt.casefold()
    assert "work outcomes" in prompt.casefold()
