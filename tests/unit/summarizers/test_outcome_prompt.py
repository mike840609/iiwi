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


def test_outcome_prompt_is_audience_neutral() -> None:
    prompt = build_outcome_prompt()

    assert "engineering outcomes" not in prompt.casefold()
    assert "work outcomes" in prompt.casefold()
