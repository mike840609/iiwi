### Task 2: Deterministic Outcome Synthesis Boundary

**Files:**
- Create: `src/iiwi/services/outcomes.py`
- Create: `src/iiwi/summarizers/outcome_prompt.py`
- Modify: `src/iiwi/errors.py`
- Test: `tests/unit/services/test_outcomes.py`
- Test: `tests/unit/summarizers/test_outcome_prompt.py`

**Interfaces:**
- Consumes: `ScanResult`, `extract_evidence(ResolvedSession)`, `OpenCodeRunner.run()`, and Task 1 outcome models.
- Produces: `OutcomeSynthesisService(runner).synthesize(scan) -> OutcomeSynthesisResult`.
- Produces: `OutcomeSynthesisError(IiwiError)` and `build_outcome_prompt() -> str`.

- [ ] **Step 1: Write failing service tests for ranking, evidence, merge confidence, and degradation**

Create `tests/unit/services/test_outcomes.py` around a `StaticRunner` whose `run()` returns supplied JSON. Cover these exact cases:

```python
def test_preselects_five_and_retains_the_remainder_in_more() -> None:
    service = service_for_json(payload_with_six_single_session_outcomes())
    result = service.synthesize(scan_with_six_sessions())
    assert [item.bucket for item in result.outcomes[:5]] == [OutcomeBucket.PRIMARY] * 5
    assert result.outcomes[5].bucket is OutcomeBucket.MORE
    assert len(result.outcomes) == 6


def test_high_confidence_cross_repo_merge_requires_two_independent_signals() -> None:
    result = service_for_json(cross_repo_payload(
        confidence="high",
        linkage_signals=[
            {"kind": "branch_or_issue", "value": "IIWI-42"},
            {"kind": "direct_reference", "value": "same feature rollout"},
        ],
    )).synthesize(two_repo_scan())
    assert len(result.outcomes) == 1
    assert {ref.repository_id for ref in result.outcomes[0].evidence_refs} == {
        "repo-a", "repo-b"
    }


@pytest.mark.parametrize("signals", [
    [{"kind": "similar_wording", "value": "auth"}],
    [{"kind": "timestamp_proximity", "value": "same hour"}],
    [{"kind": "branch_or_issue", "value": "IIWI-42"}],
])
def test_unsupported_cross_repo_merge_is_split_by_repository(signals) -> None:
    result = service_for_json(cross_repo_payload(
        confidence="high", linkage_signals=signals
    )).synthesize(two_repo_scan())
    assert len(result.outcomes) == 2


def test_model_cannot_attach_evidence_from_an_unknown_session() -> None:
    with pytest.raises(OutcomeSynthesisError, match="unknown session"):
        service_for_json(payload_for_sessions(["invented-session"])).synthesize(one_scan())


def test_unsupported_impact_is_left_empty() -> None:
    result = service_for_json(payload(impact="", source_session_ids=["ses-a"])) \
        .synthesize(one_scan())
    assert result.outcomes[0].impact == ""


def test_one_extraction_failure_becomes_ungrouped_without_blocking_success(monkeypatch) -> None:
    monkeypatch.setattr(outcomes, "extract_evidence", fail_only("ses-b"))
    result = service_for_json(payload_for_sessions(["ses-a"])).synthesize(two_session_scan())
    assert result.failed_session_ids == ["ses-b"]
    assert any(item.bucket is OutcomeBucket.UNGROUPED for item in result.outcomes)


def test_invalid_or_empty_model_output_is_a_complete_synthesis_error() -> None:
    with pytest.raises(OutcomeSynthesisError, match="valid outcome JSON"):
        service_for_raw("not-json").synthesize(one_scan())
```

- [ ] **Step 2: Run the service tests and verify they fail at import**

Run: `uv run pytest tests/unit/services/test_outcomes.py tests/unit/summarizers/test_outcome_prompt.py -q`

Expected: FAIL because the synthesis service and prompt module do not exist.

- [ ] **Step 3: Implement the JSON contract and evidence reconstruction**

In `src/iiwi/services/outcomes.py`, define private Pydantic response models with only these model-controlled fields:

```python
class _LinkSignal(BaseModel):
    kind: Literal["shared_work_id", "branch_or_issue", "direct_reference", "similar_wording", "timestamp_proximity"]
    value: str


class _ProposedOutcome(BaseModel):
    title: str
    status: OutcomeStatus
    impact: str = ""
    source_session_ids: list[str]
    confidence: EvidenceConfidence
    linkage_signals: list[_LinkSignal] = Field(default_factory=list)


class _SynthesisPayload(BaseModel):
    outcomes: list[_ProposedOutcome]
```

`OutcomeSynthesisService.synthesize()` must:

1. Extract and redact evidence session by session; collect extraction failures.
2. Send `model_dump_json(indent=2)` evidence to `OpenCodeRunner.run()` with `build_outcome_prompt()`.
3. Strip an optional fenced `json` wrapper, parse with `_SynthesisPayload.model_validate_json()`, and raise `OutcomeSynthesisError` on empty/invalid output.
4. Rebuild every `EvidenceRef` from known `SessionEvidence`; never accept model-generated repository, file, commit, or activity ids.
5. Reject unknown source session ids.
6. Permit a multi-repository outcome only for HIGH confidence and either a `shared_work_id` signal or two distinct allowed linkage kinds from `{branch_or_issue, direct_reference}`.
7. Split unsupported multi-repository proposals into one outcome per repository.
8. Use `sha256("\0".join([normalized_title, *sorted(session_ids)]).encode()).hexdigest()[:16]` for stable synthesized ids, so two distinct outcomes sourced from one session cannot collide.
9. Sort in returned proposal order, assign ranks, mark the first five `PRIMARY` and the remainder `MORE`.
10. Create one `UNGROUPED` outcome per extraction failure with title from the session, empty Impact, and its known session/repository reference.

Create `build_outcome_prompt()` with the exact JSON keys above, the 3–5 ranking target, the merge confidence contract, an explicit instruction that Impact must be `""` when unsupported, and a rule forbidding unknown session ids.

- [ ] **Step 4: Run synthesis and prompt tests**

Run: `uv run pytest tests/unit/services/test_outcomes.py tests/unit/summarizers/test_outcome_prompt.py -q`

Expected: PASS.

- [ ] **Step 5: Run extraction regression tests**

Run: `uv run pytest tests/unit/extraction tests/unit/summarizers/test_opencode_run.py -q`

Expected: PASS; synthesis reuses extraction without changing its conservative behavior.

- [ ] **Step 6: Commit synthesis**

```bash
git add src/iiwi/services/outcomes.py src/iiwi/summarizers/outcome_prompt.py src/iiwi/errors.py tests/unit/services/test_outcomes.py tests/unit/summarizers/test_outcome_prompt.py
git commit -m "feat: synthesize evidence-backed outcomes"
```

---
