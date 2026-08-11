"""Deterministic boundary between model proposals and extracted evidence."""

from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from iiwi.errors import OutcomeSynthesisError
from iiwi.extraction.pipeline import extract_evidence
from iiwi.models import (
    EvidenceRef,
    Outcome,
    OutcomeBucket,
    OutcomeSourceGroup,
    OutcomeStatus,
    OutcomeSynthesisResult,
)
from iiwi.models.evidence import EvidenceConfidence, SessionEvidence
from iiwi.security.redactor import redact_value
from iiwi.services.scan import ScanResult
from iiwi.summarizers.opencode_run import OpenCodeRunner
from iiwi.summarizers.outcome_prompt import build_outcome_prompt


class _LinkSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "shared_work_id",
        "branch_or_issue",
        "direct_reference",
        "similar_wording",
        "timestamp_proximity",
    ]
    value: str


class _ProposedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    status: OutcomeStatus
    impact: str = ""
    source_session_ids: list[str]
    confidence: EvidenceConfidence
    linkage_signals: list[_LinkSignal] = Field(default_factory=list)


class _SynthesisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcomes: list[_ProposedOutcome]


class _EvidencePayload(BaseModel):
    sessions: list[SessionEvidence]


_ALLOWED_LINKAGE_KINDS = frozenset({"branch_or_issue", "direct_reference"})


class OutcomeSynthesisService:
    """Turn model-selected session ids into traceable, deterministic outcomes."""

    def __init__(self, runner: OpenCodeRunner) -> None:
        self._runner = runner

    def synthesize(self, scan: ScanResult) -> OutcomeSynthesisResult:
        evidence_by_session: dict[str, SessionEvidence] = {}
        failed_sessions = []
        for resolved in scan.resolved_sessions:
            try:
                extracted = extract_evidence(resolved)
                redacted = redact_value(extracted.model_dump(mode="json"))
                evidence_by_session[extracted.session_id] = SessionEvidence.model_validate(
                    redacted
                )
            except Exception:  # Extraction failures remain visible candidates.
                failed_sessions.append(resolved)

        if not evidence_by_session:
            return OutcomeSynthesisResult(
                outcomes=self._ungrouped_outcomes(failed_sessions),
                failed_session_ids=[item.session.session_id for item in failed_sessions],
            )

        output = self._runner.run(
            transcript=_EvidencePayload(
                sessions=list(evidence_by_session.values())
            ).model_dump_json(indent=2),
            prompt=build_outcome_prompt(),
            title="Iiwi outcome synthesis",
        )
        payload = self._parse_payload(output)
        outcomes: list[Outcome] = []
        for proposal in payload.outcomes:
            selected = self._selected_evidence(proposal, evidence_by_session)
            outcomes.extend(self._outcomes_for_proposal(proposal, selected))

        for rank, outcome in enumerate(outcomes):
            outcome.rank = rank
            outcome.bucket = OutcomeBucket.PRIMARY if rank < 5 else OutcomeBucket.MORE

        ungrouped = self._ungrouped_outcomes(failed_sessions, rank_start=len(outcomes))
        return OutcomeSynthesisResult(
            outcomes=[*outcomes, *ungrouped],
            failed_session_ids=[item.session.session_id for item in failed_sessions],
        )

    @staticmethod
    def _parse_payload(output: str) -> _SynthesisPayload:
        raw = _strip_json_fence(output)
        if not raw:
            raise OutcomeSynthesisError("model did not return valid outcome JSON")
        try:
            payload = _SynthesisPayload.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            raise OutcomeSynthesisError("model did not return valid outcome JSON") from exc
        if not payload.outcomes:
            raise OutcomeSynthesisError("model did not return valid outcome JSON")
        return payload

    @staticmethod
    def _selected_evidence(
        proposal: _ProposedOutcome,
        evidence_by_session: dict[str, SessionEvidence],
    ) -> list[SessionEvidence]:
        if not proposal.source_session_ids:
            raise OutcomeSynthesisError("outcome must reference at least one source session")
        selected = []
        for session_id in proposal.source_session_ids:
            evidence = evidence_by_session.get(session_id)
            if evidence is None:
                raise OutcomeSynthesisError(f"unknown session: {session_id}")
            if evidence not in selected:
                selected.append(evidence)
        return selected

    def _outcomes_for_proposal(
        self,
        proposal: _ProposedOutcome,
        selected: list[SessionEvidence],
    ) -> list[Outcome]:
        by_repository: dict[str, list[SessionEvidence]] = {}
        for evidence in selected:
            by_repository.setdefault(evidence.repository_id, []).append(evidence)

        if len(by_repository) == 1 or self._may_merge_cross_repository(proposal):
            return [
                self._outcome(
                    proposal,
                    selected,
                    source_groups=self._source_groups(by_repository)
                    if len(by_repository) > 1
                    else [],
                )
            ]
        return [
            self._outcome(proposal, repository_evidence)
            for repository_evidence in by_repository.values()
        ]

    @staticmethod
    def _may_merge_cross_repository(proposal: _ProposedOutcome) -> bool:
        if proposal.confidence is not EvidenceConfidence.HIGH:
            return False
        kinds = {signal.kind for signal in proposal.linkage_signals}
        return "shared_work_id" in kinds or kinds >= _ALLOWED_LINKAGE_KINDS

    @staticmethod
    def _outcome(
        proposal: _ProposedOutcome,
        selected: list[SessionEvidence],
        *,
        source_groups: list[OutcomeSourceGroup] | None = None,
    ) -> Outcome:
        session_ids = [item.session_id for item in selected]
        return Outcome(
            id=_synthesized_id(proposal.title, session_ids),
            title=proposal.title,
            status=proposal.status,
            impact=proposal.impact,
            rank=0,
            evidence_refs=[
                EvidenceRef(
                    session_id=item.session_id,
                    repository_id=item.repository_id,
                )
                for item in selected
            ],
            source_groups=source_groups or [],
        )

    @staticmethod
    def _source_groups(
        by_repository: dict[str, list[SessionEvidence]],
    ) -> list[OutcomeSourceGroup]:
        return [
            OutcomeSourceGroup(
                id=repository_id,
                evidence_refs=[
                    EvidenceRef(
                        session_id=item.session_id,
                        repository_id=item.repository_id,
                    )
                    for item in evidence
                ],
            )
            for repository_id, evidence in by_repository.items()
        ]

    @staticmethod
    def _ungrouped_outcomes(
        failed_sessions,
        *,
        rank_start: int = 0,
    ) -> list[Outcome]:
        return [
            Outcome(
                id=_synthesized_id(
                    resolved.session.title or resolved.session.session_id,
                    [resolved.session.session_id],
                ),
                title=resolved.session.title or resolved.session.session_id,
                status=OutcomeStatus.IN_PROGRESS,
                impact="",
                rank=rank_start + index,
                bucket=OutcomeBucket.UNGROUPED,
                evidence_refs=[
                    EvidenceRef(
                        session_id=resolved.session.session_id,
                        repository_id=resolved.repository.repository_id,
                    )
                ],
            )
            for index, resolved in enumerate(failed_sessions)
        ]


def _strip_json_fence(output: str) -> str:
    value = output.strip()
    if value.startswith("```json") and value.endswith("```"):
        return value[len("```json") : -len("```")].strip()
    return value


def _synthesized_id(title: str, session_ids: list[str]) -> str:
    normalized_title = " ".join(title.split()).casefold()
    value = "\0".join([normalized_title, *sorted(session_ids)])
    return sha256(value.encode()).hexdigest()[:16]
