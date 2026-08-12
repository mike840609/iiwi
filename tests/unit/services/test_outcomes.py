from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from iiwi.errors import OutcomeSynthesisError
from iiwi.models import OutcomeBucket, OutcomeReviewDraft
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
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


def activity(
    activity_id: str,
    activity_type: ActivityType,
    content: str,
    *,
    tool_name: str | None = None,
    metadata: dict[str, object] | None = None,
) -> SessionActivity:
    return SessionActivity(
        activity_id=activity_id,
        activity_type=activity_type,
        content=content,
        tool_name=tool_name,
        metadata=metadata or {},
    )


def resolved(
    session_id: str,
    repository_id: str = "repo-a",
    *,
    title: str | None = None,
    branch: str | None = None,
    activities: list[SessionActivity] | None = None,
    created_at: datetime | None = None,
) -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="test",
            session_id=session_id,
            title=title or f"Session {session_id}",
            branch=branch,
            created_at=created_at,
            activities=activities or [],
        ),
        repository=RepositoryIdentity(
            repository_id=repository_id,
            display_name=repository_id,
            identity_type=RepositoryIdentityType.GIT_REMOTE,
            branch=branch,
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


def two_repo_scan_with_linkage_evidence() -> ScanResult:
    return scan_with(
        [
            resolved(
                "ses-a",
                "repo-a",
                branch="IIWI-42",
                activities=[
                    activity(
                        "a-user",
                        ActivityType.USER_MESSAGE,
                        "Implement same feature rollout for the API.",
                    )
                ],
            ),
            resolved(
                "ses-b",
                "repo-b",
                branch="IIWI-42",
                activities=[
                    activity(
                        "b-user",
                        ActivityType.USER_MESSAGE,
                        "Implement same feature rollout for the UI.",
                    )
                ],
            ),
        ]
    )


def dated(session_id: str, *, day: int) -> ResolvedSession:
    """One session with enough evidence to measure and a distinct start time."""

    return resolved(
        session_id,
        created_at=datetime(2026, 8, day, tzinfo=UTC),
        activities=[
            activity(
                f"{session_id}-{index}",
                ActivityType.USER_MESSAGE,
                f"Investigate the {session_id} regression, step {index}. "
                + "Describe the failing path in detail. " * 5,
            )
            for index in range(4)
        ],
    )


def compact_entry(session: ResolvedSession) -> outcomes._CompactSession:
    extracted = outcomes.extract_evidence(session)
    redacted = outcomes.SessionEvidence.model_validate(
        outcomes.redact_value(extracted.model_dump(mode="json"))
    )
    return outcomes._compact_session(
        redacted,
        branch=session.session.branch or session.repository.branch,
    )


def compact_entry_size(session: ResolvedSession) -> int:
    """One session's entry on its own, without the index that carries it."""

    return len(compact_entry(session).as_json().encode())


def payload_size(sessions: list[ResolvedSession]) -> int:
    """The bytes these sessions actually cost as one sent payload."""

    return len(outcomes._index_json([compact_entry(session) for session in sessions]).encode())


def full_evidence_size(session: ResolvedSession) -> int:
    """The payload cost the same session would have carried as full evidence."""

    return len(outcomes.extract_evidence(session).model_dump_json(indent=2).encode())


def sent_sessions(runner: StaticRunner) -> list[dict[str, str]]:
    return json.loads(runner.calls[0]["transcript"])["sessions"]


def sent_session_ids(runner: StaticRunner) -> list[str]:
    return [session["session_id"] for session in sent_sessions(runner)]


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


def test_unsupported_model_claims_are_not_copied_from_activity_free_session() -> None:
    result = service_for_json(
        payload(
            title="Invented launch outcome",
            impact="Revenue increased",
            source_session_ids=["ses-a"],
        )
    ).synthesize(one_scan())

    outcome = result.outcomes[0]
    assert outcome.title == "Session ses-a"
    assert outcome.status == "in_progress"
    assert outcome.impact == ""


def test_evidence_refs_include_locally_extracted_file_references() -> None:
    result = service_for_json(
        payload(
            title="Updated checkout renderer",
            impact="",
            source_session_ids=["ses-a"],
        )
    ).synthesize(
        scan_with(
            [
                resolved(
                    "ses-a",
                    activities=[
                        activity(
                            "file-a",
                            ActivityType.FILE_CHANGE,
                            "src/checkout/render.py",
                        )
                    ],
                )
            ]
        )
    )

    assert [reference.file for reference in result.outcomes[0].evidence_refs] == [
        "src/checkout/render.py"
    ]


def test_arbitrary_hex_identifier_is_not_commit_evidence() -> None:
    result = service_for_json(payload_for_sessions(["ses-a"])).synthesize(
        scan_with([resolved("ses-a", title="Tracked identifier 8badf00d")])
    )

    assert result.outcomes[0].evidence_refs[0].commit is None


def test_contextual_revision_is_commit_evidence() -> None:
    result = service_for_json(payload_for_sessions(["ses-a"])).synthesize(
        scan_with(
            [
                resolved(
                    "ses-a",
                    activities=[
                        activity(
                            "revision",
                            ActivityType.USER_MESSAGE,
                            "Revision: 1a2b3c4 completed the reviewed change.",
                        )
                    ],
                )
            ]
        )
    )

    assert result.outcomes[0].evidence_refs[0].commit == "1a2b3c4"


def test_model_omission_preserves_extracted_session_as_ungrouped_candidate() -> None:
    result = service_for_json(payload_for_sessions(["ses-a"])).synthesize(two_session_scan())

    assert [outcome.bucket for outcome in result.outcomes] == [
        OutcomeBucket.PRIMARY,
        OutcomeBucket.UNGROUPED,
    ]
    assert result.outcomes[1].title == "Session ses-b"
    assert result.outcomes[1].included is False


def test_exact_duplicate_model_proposals_share_one_traceable_candidate() -> None:
    result = service_for_json(
        {
            "outcomes": [
                {
                    "title": "Repeated title",
                    "status": "in_progress",
                    "impact": "",
                    "source_session_ids": ["ses-a"],
                    "confidence": "high",
                    "linkage_signals": [],
                },
                {
                    "title": "Repeated title",
                    "status": "in_progress",
                    "impact": "",
                    "source_session_ids": ["ses-a"],
                    "confidence": "high",
                    "linkage_signals": [],
                },
            ]
        }
    ).synthesize(one_scan())

    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.rank == 0
    assert outcome.bucket is OutcomeBucket.PRIMARY
    assert outcome.included is True
    assert [reference.session_id for reference in outcome.evidence_refs] == ["ses-a"]


def test_high_confidence_cross_repo_merge_requires_two_independent_signals() -> None:
    result = service_for_json(
        cross_repo_payload(
            confidence="high",
            linkage_signals=[
                {"kind": "branch_or_issue", "value": "IIWI-42"},
                {"kind": "direct_reference", "value": "same feature rollout"},
            ],
        )
    ).synthesize(two_repo_scan_with_linkage_evidence())
    assert len(result.outcomes) == 1
    assert {ref.repository_id for ref in result.outcomes[0].evidence_refs} == {
        "repo-a",
        "repo-b",
    }


def test_cross_repo_merge_requires_each_linkage_signal_in_each_repository() -> None:
    result = service_for_json(
        cross_repo_payload(
            confidence="high",
            linkage_signals=[
                {"kind": "branch_or_issue", "value": "IIWI-42"},
                {"kind": "direct_reference", "value": "same feature rollout"},
            ],
        )
    ).synthesize(
        scan_with(
            [
                resolved("ses-a", "repo-a", branch="IIWI-42"),
                resolved(
                    "ses-b",
                    "repo-b",
                    activities=[
                        activity(
                            "b-user",
                            ActivityType.USER_MESSAGE,
                            "Implement same feature rollout for the UI.",
                        )
                    ],
                ),
            ]
        )
    )

    assert len(result.outcomes) == 2


def test_linkage_signal_values_must_be_observed_in_local_evidence() -> None:
    result = service_for_json(
        cross_repo_payload(
            confidence="high",
            linkage_signals=[
                {"kind": "branch_or_issue", "value": "IIWI-999"},
                {"kind": "direct_reference", "value": "unobserved shared wording"},
            ],
        )
    ).synthesize(two_repo_scan_with_linkage_evidence())

    assert len(result.outcomes) == 2


def test_real_cross_repo_merge_splits_into_named_repository_outcomes() -> None:
    result = service_for_json(
        cross_repo_payload(
            confidence="high",
            linkage_signals=[
                {"kind": "branch_or_issue", "value": "IIWI-42"},
                {"kind": "direct_reference", "value": "same feature rollout"},
            ],
        )
    ).synthesize(two_repo_scan_with_linkage_evidence())
    draft = OutcomeReviewDraft(outcomes=result.outcomes)

    draft.split(result.outcomes[0].id)

    assert [outcome.title for outcome in draft.ordered()] == ["repo-a", "repo-b"]
    assert [
        [reference.repository_id for reference in outcome.evidence_refs]
        for outcome in draft.ordered()
    ] == [["repo-a"], ["repo-b"]]


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
    result = service_for_json(
        payload_for_sessions(["ses-a", "invented-session"])
    ).synthesize(one_scan())

    assert [reference.session_id for reference in result.outcomes[0].evidence_refs] == [
        "ses-a"
    ]


def test_model_cannot_supply_repository_references() -> None:
    model_output = payload_for_sessions(["ses-a"])
    model_output["outcomes"][0]["repository_id"] = "invented-repository"

    result = service_for_json(model_output).synthesize(one_scan())

    assert [
        reference.repository_id for reference in result.outcomes[0].evidence_refs
    ] == ["repo-a"]


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


def test_ungrouped_failed_session_titles_are_redacted(monkeypatch) -> None:
    monkeypatch.setattr(outcomes, "extract_evidence", fail_only("ses-b"))
    result = service_for_json(payload_for_sessions(["ses-a"])).synthesize(
        scan_with(
            [
                resolved("ses-a"),
                resolved("ses-b", title="token=secret-title"),
            ]
        )
    )

    ungrouped = next(item for item in result.outcomes if item.bucket is OutcomeBucket.UNGROUPED)
    assert "secret-title" not in ungrouped.title
    assert "[REDACTED]" in ungrouped.title


def test_ungrouped_failed_session_references_are_redacted(monkeypatch) -> None:
    secret_id = "token=secret-session"
    monkeypatch.setattr(outcomes, "extract_evidence", fail_only(secret_id))

    result = service_for_json(payload_for_sessions(["ses-a"])).synthesize(
        scan_with([resolved("ses-a"), resolved(secret_id)])
    )

    ungrouped = next(item for item in result.outcomes if item.bucket is OutcomeBucket.UNGROUPED)
    assert "secret-session" not in ungrouped.evidence_refs[0].session_id
    assert "[REDACTED]" in ungrouped.evidence_refs[0].session_id


def test_all_extraction_failures_raise_complete_synthesis_error(monkeypatch) -> None:
    monkeypatch.setattr(outcomes, "extract_evidence", fail_only("ses-a"))

    with pytest.raises(OutcomeSynthesisError, match="could not extract evidence"):
        service_for_raw("not called").synthesize(one_scan())


def test_invalid_or_empty_model_output_is_a_complete_synthesis_error() -> None:
    with pytest.raises(OutcomeSynthesisError, match="valid outcome JSON"):
        service_for_raw("not-json").synthesize(one_scan())


@pytest.mark.parametrize(
    "template",
    [
        "```\n{payload}\n```",
        "Here is the summary:\n\n```json\n{payload}\n```\n\nLet me know if that helps.",
        "{payload}",
    ],
)
def test_outcome_json_is_read_through_surrounding_output(template) -> None:
    output = template.format(payload=json.dumps(payload_for_sessions(["ses-a"])))

    result = service_for_raw(output).synthesize(one_scan())

    assert [reference.session_id for reference in result.outcomes[0].evidence_refs] == [
        "ses-a"
    ]


def test_output_without_any_json_object_is_a_complete_synthesis_error() -> None:
    with pytest.raises(OutcomeSynthesisError, match="valid outcome JSON"):
        service_for_raw("I could not find any outcomes to report.").synthesize(one_scan())


def test_unknown_outcome_field_is_ignored_and_the_outcome_still_builds() -> None:
    model_output = payload_for_sessions(["ses-a"])
    model_output["outcomes"][0]["reasoning"] = "invented commentary"

    result = service_for_json(model_output).synthesize(one_scan())

    assert [outcome.bucket for outcome in result.outcomes] == [OutcomeBucket.PRIMARY]
    assert result.outcomes[0].title == "Session ses-a"


def test_unrecognized_linkage_kind_cannot_authorize_cross_repo_merge() -> None:
    result = service_for_json(
        cross_repo_payload(
            confidence="high",
            linkage_signals=[{"kind": "vibes", "value": "IIWI-42"}],
        )
    ).synthesize(two_repo_scan_with_linkage_evidence())

    assert len(result.outcomes) == 2


def test_proposal_keeping_one_known_session_builds_from_that_session_only() -> None:
    result = service_for_json(
        payload_for_sessions(["ses-a", "invented-session"])
    ).synthesize(two_session_scan())

    assert [reference.session_id for reference in result.outcomes[0].evidence_refs] == [
        "ses-a"
    ]
    assert result.outcomes[1].bucket is OutcomeBucket.UNGROUPED
    assert result.outcomes[1].title == "Session ses-b"


def test_proposal_without_a_known_session_is_skipped_beside_valid_proposals() -> None:
    result = service_for_json(
        {
            "outcomes": [
                {
                    "title": "Known outcome",
                    "status": "in_progress",
                    "impact": "",
                    "source_session_ids": ["ses-a"],
                    "confidence": "high",
                    "linkage_signals": [],
                },
                {
                    "title": "Invented outcome",
                    "status": "in_progress",
                    "impact": "",
                    "source_session_ids": ["invented-session"],
                    "confidence": "high",
                    "linkage_signals": [],
                },
            ]
        }
    ).synthesize(two_session_scan())

    assert [outcome.bucket for outcome in result.outcomes] == [
        OutcomeBucket.PRIMARY,
        OutcomeBucket.UNGROUPED,
    ]
    assert [reference.session_id for reference in result.outcomes[0].evidence_refs] == [
        "ses-a"
    ]
    assert result.outcomes[1].title == "Session ses-b"


def test_all_proposals_skipped_returns_ungrouped_candidates_without_raising() -> None:
    result = service_for_json(payload_for_sessions(["invented-session"])).synthesize(
        two_session_scan()
    )

    assert [outcome.bucket for outcome in result.outcomes] == [
        OutcomeBucket.UNGROUPED,
        OutcomeBucket.UNGROUPED,
    ]
    assert [outcome.title for outcome in result.outcomes] == [
        "Session ses-a",
        "Session ses-b",
    ]


def test_evidence_inside_the_budget_reaches_the_model_and_warns_about_nothing() -> None:
    sessions = [dated("ses-a", day=9), dated("ses-b", day=8)]
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a", "ses-b"])))

    result = OutcomeSynthesisService(runner, max_evidence_bytes=100_000).synthesize(
        scan_with(sessions)
    )

    assert sent_session_ids(runner) == ["ses-a", "ses-b"]
    assert result.warnings == []


def test_sessions_past_the_budget_never_reach_the_model() -> None:
    sessions = [dated("ses-a", day=9), dated("ses-b", day=8), dated("ses-c", day=7)]
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(
        runner,
        max_evidence_bytes=payload_size(sessions[:2]),
    ).synthesize(scan_with(sessions))

    assert sent_session_ids(runner) == ["ses-a", "ses-b"]


def test_sessions_past_the_budget_remain_excluded_ungrouped_candidates() -> None:
    sessions = [dated("ses-a", day=9), dated("ses-b", day=8)]
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    result = OutcomeSynthesisService(
        runner,
        max_evidence_bytes=compact_entry_size(sessions[0]),
    ).synthesize(scan_with(sessions))

    held_back = next(
        item for item in result.outcomes if item.bucket is OutcomeBucket.UNGROUPED
    )
    assert held_back.title == "Session ses-b"
    assert held_back.included is False
    assert [reference.session_id for reference in held_back.evidence_refs] == ["ses-b"]


def test_budget_warning_names_how_many_sessions_were_held_back() -> None:
    sessions = [dated(f"ses-{index}", day=9 - index) for index in range(3)]
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-0"])))

    result = OutcomeSynthesisService(
        runner,
        max_evidence_bytes=compact_entry_size(sessions[0]),
    ).synthesize(scan_with(sessions))

    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("2 older session(s) did not fit")


def test_the_most_recent_sessions_are_the_ones_synthesized() -> None:
    sessions = [dated("ses-old", day=3), dated("ses-new", day=9), dated("ses-mid", day=6)]
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-new"])))

    OutcomeSynthesisService(
        runner,
        max_evidence_bytes=payload_size([sessions[1], sessions[2]]),
    ).synthesize(scan_with(sessions))

    assert sent_session_ids(runner) == ["ses-new", "ses-mid"]


def test_a_session_larger_than_the_whole_budget_is_still_sent() -> None:
    sessions = [dated("ses-a", day=9), dated("ses-b", day=8)]
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(runner, max_evidence_bytes=1).synthesize(scan_with(sessions))

    assert sent_session_ids(runner) == ["ses-a"]


def test_the_budget_counts_the_index_around_the_entries_not_just_the_entries() -> None:
    """The entries alone fit; the payload that carries them does not."""

    sessions = [dated("ses-a", day=9), dated("ses-b", day=8)]
    budget = compact_entry_size(sessions[0]) + compact_entry_size(sessions[1]) + 1
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(runner, max_evidence_bytes=budget).synthesize(
        scan_with(sessions)
    )

    assert budget < payload_size(sessions)
    assert sent_session_ids(runner) == ["ses-a"]
    assert len(runner.calls[0]["transcript"].encode()) <= budget


def test_undated_sessions_keep_their_scan_order_behind_dated_ones() -> None:
    sessions = [resolved("ses-first"), resolved("ses-second"), dated("ses-dated", day=1)]
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-first"])))

    OutcomeSynthesisService(runner, max_evidence_bytes=100_000).synthesize(
        scan_with(sessions)
    )

    assert sent_session_ids(runner) == ["ses-dated", "ses-first", "ses-second"]


def detailed(
    session_id: str,
    repository_id: str = "repo-a",
    *,
    branch: str | None = "feature/checkout",
    goal: str = "Investigate the checkout regression.",
    file: str = "src/checkout/render.py",
    command: str = "npm run deploy-preview",
    failing_command: str = "cargo build --release",
    verification_command: str | None = None,
    claim: str | None = "Completed the checkout regression fix.",
) -> ResolvedSession:
    """One session carrying every kind of evidence the extractor recognizes.

    A passing `verification_command` becomes an outcome ahead of the claim, which
    is how real sessions order them.
    """

    verification = (
        [
            activity(
                f"{session_id}-verification",
                ActivityType.COMMAND,
                verification_command,
                metadata={"exit_code": 0},
            )
        ]
        if verification_command
        else []
    )
    return resolved(
        session_id,
        repository_id,
        branch=branch,
        activities=[
            activity(f"{session_id}-goal", ActivityType.USER_MESSAGE, goal),
            activity(
                f"{session_id}-command",
                ActivityType.COMMAND,
                command,
                metadata={"exit_code": 0},
            ),
            activity(
                f"{session_id}-error",
                ActivityType.COMMAND,
                failing_command,
                metadata={"exit_code": 1},
            ),
            activity(f"{session_id}-file", ActivityType.FILE_CHANGE, file),
            *verification,
            *(
                [activity(f"{session_id}-claim", ActivityType.ASSISTANT_MESSAGE, claim)]
                if claim
                else []
            ),
        ],
    )


def test_the_model_receives_only_the_fields_grouping_needs() -> None:
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(runner).synthesize(scan_with([detailed("ses-a")]))

    assert sent_sessions(runner) == [
        {
            "session_id": "ses-a",
            "repository_id": "repo-a",
            "title": "Session ses-a",
            "branch": "feature/checkout",
            "goal": "Investigate the checkout regression.",
            "outcome": "Completed the checkout regression fix.",
        }
    ]


def test_commands_files_and_errors_never_reach_the_model() -> None:
    """Including the passing verification command, which the outcome field carried."""

    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(runner).synthesize(
        scan_with(
            [
                detailed(
                    "ses-a",
                    verification_command="pytest -q tests/unit/checkout/test_render.py",
                )
            ]
        )
    )

    transcript = runner.calls[0]["transcript"]
    assert "npm run deploy-preview" not in transcript
    assert "cargo build --release" not in transcript
    assert "src/checkout/render.py" not in transcript
    assert "tests/unit/checkout/test_render.py" not in transcript
    assert sent_sessions(runner)[0]["outcome"] == "Completed the checkout regression fix."


def test_the_session_claim_is_sent_rather_than_the_verification_that_precedes_it() -> None:
    """Every session running one test command would otherwise send one outcome."""

    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(runner).synthesize(
        scan_with(
            [
                resolved(
                    "ses-a",
                    activities=[
                        activity("a-goal", ActivityType.USER_MESSAGE, "Fix the parser."),
                        activity(
                            "a-verify-1",
                            ActivityType.COMMAND,
                            "pytest -q tests/unit/parser",
                            metadata={"exit_code": 0},
                        ),
                        activity(
                            "a-verify-2",
                            ActivityType.COMMAND,
                            "ruff check .",
                            metadata={"exit_code": 0},
                        ),
                        activity(
                            "a-claim",
                            ActivityType.ASSISTANT_MESSAGE,
                            "Fixed the nested-quote parser bug.",
                        ),
                    ],
                )
            ]
        )
    )

    assert sent_sessions(runner)[0]["outcome"] == "Fixed the nested-quote parser bug."


def test_a_session_without_a_claim_still_sends_its_first_outcome() -> None:
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(runner).synthesize(
        scan_with([detailed("ses-a", verification_command="pytest -q", claim=None)])
    )

    assert sent_sessions(runner)[0]["outcome"] == "Verification passed: pytest -q"


def test_the_goal_field_still_takes_the_first_goal() -> None:
    """Goals come from user messages in order, so first is genuinely first."""

    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(runner).synthesize(
        scan_with(
            [
                resolved(
                    "ses-a",
                    activities=[
                        activity(
                            "a-goal-1",
                            ActivityType.USER_MESSAGE,
                            "Investigate the checkout regression.",
                        ),
                        activity(
                            "a-goal-2",
                            ActivityType.USER_MESSAGE,
                            "Also rename the pricing module.",
                        ),
                        activity(
                            "a-claim",
                            ActivityType.ASSISTANT_MESSAGE,
                            "Completed the checkout regression fix.",
                        ),
                    ],
                )
            ]
        )
    )

    assert sent_sessions(runner)[0]["goal"] == "Investigate the checkout regression."


def test_branch_is_redacted_before_it_reaches_the_model() -> None:
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(runner).synthesize(
        scan_with([detailed("ses-a", branch="token=secret-branch")])
    )

    assert "secret-branch" not in runner.calls[0]["transcript"]
    assert sent_sessions(runner)[0]["branch"] == "token=[REDACTED]"


def test_a_linkage_signal_repeating_the_redacted_branch_is_observed_locally() -> None:
    """The model can only echo the branch it was shown, so both sides are redacted."""

    branch = "feature/checkout.rendering.regression"
    redacted_branch = outcomes.redact_text(branch)
    assert redacted_branch != branch
    runner = StaticRunner(
        json.dumps(
            cross_repo_payload(
                confidence="high",
                linkage_signals=[
                    {"kind": "branch_or_issue", "value": redacted_branch},
                    {"kind": "direct_reference", "value": "same feature rollout"},
                ],
            )
        )
    )

    result = OutcomeSynthesisService(runner).synthesize(
        scan_with(
            [
                resolved(
                    "ses-a",
                    "repo-a",
                    branch=branch,
                    activities=[
                        activity(
                            "a-user",
                            ActivityType.USER_MESSAGE,
                            "Implement same feature rollout for the API.",
                        )
                    ],
                ),
                resolved(
                    "ses-b",
                    "repo-b",
                    branch=branch,
                    activities=[
                        activity(
                            "b-user",
                            ActivityType.USER_MESSAGE,
                            "Implement same feature rollout for the UI.",
                        )
                    ],
                ),
            ]
        )
    )

    assert [session["branch"] for session in sent_sessions(runner)] == [redacted_branch] * 2
    assert len(result.outcomes) == 1
    assert {ref.repository_id for ref in result.outcomes[0].evidence_refs} == {
        "repo-a",
        "repo-b",
    }


def test_sessions_without_branch_goal_or_outcome_send_no_blank_fields() -> None:
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(runner).synthesize(scan_with([resolved("ses-a")]))

    assert sent_sessions(runner) == [
        {"session_id": "ses-a", "repository_id": "repo-a", "title": "Session ses-a"}
    ]


def test_long_goal_and_outcome_text_reaches_the_model_whole() -> None:
    """Most real goals run past 120 characters, and the overlap is the signal."""

    goal = "Investigate the regression. " * 10
    claim = "Completed the regression fix. " * 10
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-a"])))

    OutcomeSynthesisService(runner).synthesize(
        scan_with([detailed("ses-a", goal=goal, claim=claim)])
    )

    sent = sent_sessions(runner)[0]
    assert len(goal) > 120
    assert sent["goal"] == goal.strip()
    assert len(claim) > 120
    assert sent["outcome"] == claim.strip()


def test_the_budget_now_buys_far_more_sessions_than_full_evidence_would() -> None:
    sessions = [dated(f"ses-{index}", day=9 - index) for index in range(3)]
    budget = payload_size(sessions)
    runner = StaticRunner(json.dumps(payload_for_sessions(["ses-0"])))

    result = OutcomeSynthesisService(runner, max_evidence_bytes=budget).synthesize(
        scan_with(sessions)
    )

    assert sent_session_ids(runner) == ["ses-0", "ses-1", "ses-2"]
    assert result.warnings == []
    # The same budget would not have covered even one session of full evidence.
    assert full_evidence_size(sessions[0]) > budget


def redaction_rewriting_session_ids():
    """Redaction that renames the session it redacts, as it may one day do."""

    original = outcomes.redact_value

    def redact(value):
        redacted = original(value)
        if isinstance(redacted, dict) and "session_id" in redacted:
            return {**redacted, "session_id": f"anon-{redacted['session_id']}"}
        return redacted

    return redact


def test_synthesis_survives_redaction_rewriting_the_session_id(monkeypatch) -> None:
    """Every dict is keyed on the id redaction produced, which is the id sent."""

    monkeypatch.setattr(outcomes, "redact_value", redaction_rewriting_session_ids())
    sessions = [dated("ses-old", day=3), dated("ses-new", day=9)]
    runner = StaticRunner(json.dumps(payload_for_sessions(["anon-ses-new"])))

    result = OutcomeSynthesisService(runner, max_evidence_bytes=100_000).synthesize(
        scan_with(sessions)
    )

    assert sent_session_ids(runner) == ["anon-ses-new", "anon-ses-old"]
    assert [reference.session_id for reference in result.outcomes[0].evidence_refs] == [
        "anon-ses-new"
    ]


def test_grouping_still_builds_evidence_refs_the_model_never_saw() -> None:
    sessions = [
        detailed("ses-a", file="src/checkout/render.py", command="git show commit 1a2b3c4"),
        detailed("ses-b", file="src/checkout/totals.py", command="git show commit 5d6e7f8"),
    ]
    runner = StaticRunner(
        json.dumps(payload(title="Checkout regression", source_session_ids=["ses-a", "ses-b"]))
    )

    result = OutcomeSynthesisService(runner).synthesize(scan_with(sessions))

    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.title == "Checkout regression"
    assert [reference.file for reference in outcome.evidence_refs] == [
        "src/checkout/render.py",
        "src/checkout/totals.py",
    ]
    assert [reference.commit for reference in outcome.evidence_refs] == [
        "1a2b3c4",
        "5d6e7f8",
    ]
    transcript = runner.calls[0]["transcript"]
    assert "src/checkout/render.py" not in transcript
    assert "src/checkout/totals.py" not in transcript
    assert "1a2b3c4" not in transcript
    assert "5d6e7f8" not in transcript
