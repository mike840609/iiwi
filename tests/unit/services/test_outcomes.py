from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from iiwi.errors import OutcomeSynthesisError
from iiwi.models import OutcomeBucket
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import AgentSession
from iiwi.models.time_range import DateRange
from iiwi.services import outcomes
from iiwi.services.outcomes import OutcomeSynthesisService
from iiwi.services.scan import ScanResult


@dataclass
class StaticRunner:
    output: str
    calls: list[dict[str, str]] = field(default_factory=list)

    def run(self, *, transcript: str, prompt: str, title: str) -> str:
        self.calls.append({"transcript": transcript, "prompt": prompt, "title": title})
        return self.output


def service_for_json(value: dict[str, object]) -> OutcomeSynthesisService:
    return OutcomeSynthesisService(StaticRunner(json.dumps(value)))


def service_for_raw(value: str) -> OutcomeSynthesisService:
    return OutcomeSynthesisService(StaticRunner(value))


def payload(
    *,
    title: str = "Completed outcome",
    impact: str = "Verified result",
    source_session_ids: list[str],
    confidence: str = "high",
    linkage_signals: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "outcomes": [
            {
                "title": title,
                "status": "completed",
                "impact": impact,
                "source_session_ids": source_session_ids,
                "confidence": confidence,
                "linkage_signals": linkage_signals or [],
            }
        ]
    }


def payload_for_sessions(session_ids: list[str]) -> dict[str, object]:
    return payload(source_session_ids=session_ids)


def payload_with_six_single_session_outcomes() -> dict[str, object]:
    return {
        "outcomes": [
            {
                "title": f"Outcome {index}",
                "status": "completed",
                "impact": "",
                "source_session_ids": [f"ses-{index}"],
                "confidence": "high",
                "linkage_signals": [],
            }
            for index in range(1, 7)
        ]
    }


def cross_repo_payload(
    *, confidence: str, linkage_signals: list[dict[str, str]]
) -> dict[str, object]:
    return payload(
        title="Shared rollout",
        source_session_ids=["ses-a", "ses-b"],
        confidence=confidence,
        linkage_signals=linkage_signals,
    )


def resolved(session_id: str, repository_id: str = "repo-a") -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="test",
            session_id=session_id,
            title=f"Session {session_id}",
        ),
        repository=RepositoryIdentity(
            repository_id=repository_id,
            display_name=repository_id,
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            resolution_method="test",
        ),
    )


def scan_with(sessions: list[ResolvedSession]) -> ScanResult:
    now = datetime(2026, 8, 10, tzinfo=UTC)
    return ScanResult(
        period=DateRange(since=now - timedelta(days=7), until=now),
        candidate_session_count=len(sessions),
        loaded_session_count=len(sessions),
        failed_session_count=0,
        resolved_sessions=sessions,
    )


def one_scan() -> ScanResult:
    return scan_with([resolved("ses-a")])


def two_session_scan() -> ScanResult:
    return scan_with([resolved("ses-a"), resolved("ses-b")])


def scan_with_six_sessions() -> ScanResult:
    return scan_with([resolved(f"ses-{index}") for index in range(1, 7)])


def two_repo_scan() -> ScanResult:
    return scan_with([resolved("ses-a", "repo-a"), resolved("ses-b", "repo-b")])


def fail_only(session_id: str):
    original = outcomes.extract_evidence

    def extract(resolved_session: ResolvedSession):
        if resolved_session.session.session_id == session_id:
            raise RuntimeError("extraction failed")
        return original(resolved_session)

    return extract


def test_preselects_five_and_retains_the_remainder_in_more() -> None:
    service = service_for_json(payload_with_six_single_session_outcomes())
    result = service.synthesize(scan_with_six_sessions())
    assert [item.bucket for item in result.outcomes[:5]] == [OutcomeBucket.PRIMARY] * 5
    assert result.outcomes[5].bucket is OutcomeBucket.MORE
    assert len(result.outcomes) == 6


def test_high_confidence_cross_repo_merge_requires_two_independent_signals() -> None:
    result = service_for_json(
        cross_repo_payload(
            confidence="high",
            linkage_signals=[
                {"kind": "branch_or_issue", "value": "IIWI-42"},
                {"kind": "direct_reference", "value": "same feature rollout"},
            ],
        )
    ).synthesize(two_repo_scan())
    assert len(result.outcomes) == 1
    assert {ref.repository_id for ref in result.outcomes[0].evidence_refs} == {
        "repo-a",
        "repo-b",
    }


@pytest.mark.parametrize(
    "signals",
    [
        [{"kind": "similar_wording", "value": "auth"}],
        [{"kind": "timestamp_proximity", "value": "same hour"}],
        [{"kind": "branch_or_issue", "value": "IIWI-42"}],
    ],
)
def test_unsupported_cross_repo_merge_is_split_by_repository(signals) -> None:
    result = service_for_json(
        cross_repo_payload(confidence="high", linkage_signals=signals)
    ).synthesize(two_repo_scan())
    assert len(result.outcomes) == 2


@pytest.mark.parametrize(
    "signals",
    [
        [{"kind": "shared_work_id", "value": ""}],
        [{"kind": "shared_work_id", "value": "  "}],
        [
            {"kind": "branch_or_issue", "value": " "},
            {"kind": "direct_reference", "value": "same feature rollout"},
        ],
        [
            {"kind": "branch_or_issue", "value": "IIWI-42"},
            {"kind": "direct_reference", "value": "\t"},
        ],
    ],
)
def test_blank_cross_repo_linkage_signals_cannot_authorize_merge(signals) -> None:
    result = service_for_json(
        cross_repo_payload(confidence="high", linkage_signals=signals)
    ).synthesize(two_repo_scan())

    assert len(result.outcomes) == 2


def test_model_cannot_attach_evidence_from_an_unknown_session() -> None:
    with pytest.raises(OutcomeSynthesisError, match="unknown session"):
        service_for_json(payload_for_sessions(["invented-session"])).synthesize(one_scan())


def test_model_cannot_supply_repository_references() -> None:
    model_output = payload_for_sessions(["ses-a"])
    model_output["outcomes"][0]["repository_id"] = "invented-repository"

    with pytest.raises(OutcomeSynthesisError, match="valid outcome JSON"):
        service_for_json(model_output).synthesize(one_scan())


def test_unsupported_impact_is_left_empty() -> None:
    result = service_for_json(payload(impact="", source_session_ids=["ses-a"])).synthesize(
        one_scan()
    )
    assert result.outcomes[0].impact == ""


def test_one_extraction_failure_becomes_ungrouped_without_blocking_success(
    monkeypatch,
) -> None:
    monkeypatch.setattr(outcomes, "extract_evidence", fail_only("ses-b"))
    result = service_for_json(payload_for_sessions(["ses-a"])).synthesize(two_session_scan())
    assert result.failed_session_ids == ["ses-b"]
    assert any(item.bucket is OutcomeBucket.UNGROUPED for item in result.outcomes)


def test_invalid_or_empty_model_output_is_a_complete_synthesis_error() -> None:
    with pytest.raises(OutcomeSynthesisError, match="valid outcome JSON"):
        service_for_raw("not-json").synthesize(one_scan())
