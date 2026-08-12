"""Deterministic boundary between model proposals and extracted evidence."""

from __future__ import annotations

import re
from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from iiwi.config import DEFAULT_QUICK_REVIEW_MAX_EVIDENCE_BYTES
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
from iiwi.models.evidence import EvidenceConfidence, EvidenceStatus, SessionEvidence
from iiwi.security.redactor import redact_text, redact_value
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
_COMMIT_PATTERN = re.compile(
    r"\b(?:commit|revision|rev)\b\s*(?:[:=]\s*)?(?P<commit>[0-9a-f]{7,40})\b",
    re.IGNORECASE,
)


class OutcomeSynthesisService:
    """Turn model-selected session ids into traceable, deterministic outcomes."""

    def __init__(
        self,
        runner: OpenCodeRunner,
        *,
        max_evidence_bytes: int = DEFAULT_QUICK_REVIEW_MAX_EVIDENCE_BYTES,
    ) -> None:
        self._runner = runner
        self._max_evidence_bytes = max_evidence_bytes

    def synthesize(self, scan: ScanResult) -> OutcomeSynthesisResult:
        evidence_by_session: dict[str, SessionEvidence] = {}
        local_texts_by_session: dict[str, list[str]] = {}
        started_at: dict[str, datetime] = {}
        failed_sessions = []
        for resolved in scan.resolved_sessions:
            try:
                extracted = extract_evidence(resolved)
                redacted = redact_value(extracted.model_dump(mode="json"))
                evidence = SessionEvidence.model_validate(redacted)
                evidence_by_session[extracted.session_id] = evidence
                if resolved.session.created_at is not None:
                    started_at[extracted.session_id] = resolved.session.created_at
                local_texts_by_session[evidence.session_id] = _local_texts(
                    evidence,
                    extra_values=[
                        resolved.session.branch,
                        resolved.repository.branch,
                        resolved.repository.repository_id,
                        resolved.repository.display_name,
                    ],
                )
            except Exception:  # Extraction failures remain visible candidates.
                failed_sessions.append(resolved)

        if not evidence_by_session:
            raise OutcomeSynthesisError(
                "could not extract evidence from any selected session"
            )

        sent = _sessions_within_budget(
            _most_recent_first(evidence_by_session, started_at),
            max_bytes=self._max_evidence_bytes,
        )
        sent_by_session = {evidence.session_id: evidence for evidence in sent}
        held_back = len(evidence_by_session) - len(sent_by_session)
        warnings = (
            [
                f"{held_back} older session(s) did not fit the Quick Review "
                "evidence budget and were left as ungrouped candidates"
            ]
            if held_back
            else []
        )

        try:
            output = self._runner.run(
                transcript=_EvidencePayload(sessions=sent).model_dump_json(indent=2),
                prompt=build_outcome_prompt(),
                title="Iiwi outcome synthesis",
            )
        except OSError as exc:
            raise OutcomeSynthesisError(str(exc)) from exc
        payload = self._parse_payload(output)
        outcomes: list[Outcome] = []
        used_session_ids: set[str] = set()
        seen_proposals: set[tuple[object, ...]] = set()
        for proposal in payload.outcomes:
            selected = self._selected_evidence(proposal, sent_by_session)
            used_session_ids.update(item.session_id for item in selected)
            signature = _proposal_signature(proposal, selected)
            if signature in seen_proposals:
                continue
            proposal_index = len(seen_proposals)
            seen_proposals.add(signature)
            outcomes.extend(
                self._outcomes_for_proposal(
                    proposal,
                    selected,
                    local_texts_by_session,
                    proposal_index=proposal_index,
                )
            )

        for rank, outcome in enumerate(outcomes):
            outcome.rank = rank
            outcome.bucket = OutcomeBucket.PRIMARY if rank < 5 else OutcomeBucket.MORE
            outcome.included = rank < 5

        omitted = [
            evidence
            for session_id, evidence in evidence_by_session.items()
            if session_id not in used_session_ids
        ]
        ungrouped = [
            *self._ungrouped_evidence_outcomes(omitted, rank_start=len(outcomes)),
            *self._ungrouped_failed_outcomes(
                failed_sessions,
                rank_start=len(outcomes) + len(omitted),
            ),
        ]
        return OutcomeSynthesisResult(
            outcomes=[*outcomes, *ungrouped],
            failed_session_ids=[item.session.session_id for item in failed_sessions],
            warnings=warnings,
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
        local_texts_by_session: dict[str, list[str]],
        *,
        proposal_index: int,
    ) -> list[Outcome]:
        by_repository: dict[str, list[SessionEvidence]] = {}
        for evidence in selected:
            by_repository.setdefault(evidence.repository_id, []).append(evidence)

        if len(by_repository) == 1 or self._may_merge_cross_repository(
            proposal, selected, local_texts_by_session
        ):
            return [
                self._outcome(
                    proposal,
                    selected,
                    local_texts_by_session,
                    source_groups=self._source_groups(
                        proposal,
                        selected,
                        local_texts_by_session,
                        group_by_repository=len(by_repository) > 1,
                    )
                    if len(selected) > 1
                    else [],
                    discriminator=str(proposal_index),
                )
            ]
        return [
            self._outcome(
                proposal,
                repository_evidence,
                local_texts_by_session,
                source_groups=self._source_groups(
                    proposal,
                    repository_evidence,
                    local_texts_by_session,
                    group_by_repository=False,
                )
                if len(repository_evidence) > 1
                else [],
                discriminator=f"{proposal_index}:{repository_id}",
            )
            for repository_id, repository_evidence in by_repository.items()
        ]

    @staticmethod
    def _may_merge_cross_repository(
        proposal: _ProposedOutcome,
        selected: list[SessionEvidence],
        local_texts_by_session: dict[str, list[str]],
    ) -> bool:
        if proposal.confidence is not EvidenceConfidence.HIGH:
            return False

        def observed_by_repository(value: str) -> bool:
            return _value_is_observed_in_every_repository(
                value, selected, local_texts_by_session
            )

        if any(
            signal.kind == "shared_work_id"
            and signal.value.strip()
            and observed_by_repository(signal.value)
            for signal in proposal.linkage_signals
        ):
            return True
        return all(
            any(
                signal.kind == kind
                and signal.value.strip()
                and observed_by_repository(signal.value)
                for signal in proposal.linkage_signals
            )
            for kind in _ALLOWED_LINKAGE_KINDS
        )

    @staticmethod
    def _outcome(
        proposal: _ProposedOutcome,
        selected: list[SessionEvidence],
        local_texts_by_session: dict[str, list[str]],
        *,
        source_groups: list[OutcomeSourceGroup] | None = None,
        discriminator: str,
    ) -> Outcome:
        session_ids = [item.session_id for item in selected]
        title = _supported_title(proposal.title, selected, local_texts_by_session)
        status = _supported_status(proposal.status, selected)
        impact = _supported_impact(proposal.impact, selected, local_texts_by_session)
        return Outcome(
            id=_synthesized_id(title, session_ids, discriminator=discriminator),
            title=title,
            status=status,
            impact=impact,
            rank=0,
            evidence_refs=[
                reference for item in selected for reference in _evidence_refs(item)
            ],
            source_groups=source_groups or [],
        )

    @staticmethod
    def _source_groups(
        proposal: _ProposedOutcome,
        selected: list[SessionEvidence],
        local_texts_by_session: dict[str, list[str]],
        *,
        group_by_repository: bool,
    ) -> list[OutcomeSourceGroup]:
        groups: dict[str, list[SessionEvidence]] = {}
        for evidence in selected:
            key = evidence.repository_id if group_by_repository else evidence.session_id
            groups.setdefault(key, []).append(evidence)
        source_groups: list[OutcomeSourceGroup] = []
        for key, evidence_items in groups.items():
            source_groups.append(
                OutcomeSourceGroup(
                    id=key,
                    title=key
                    if group_by_repository
                    else _fallback_title(evidence_items),
                    impact=_supported_impact(
                        proposal.impact,
                        evidence_items,
                        local_texts_by_session,
                    ),
                    status=_supported_status(proposal.status, evidence_items),
                    evidence_refs=[
                        reference
                        for item in evidence_items
                        for reference in _evidence_refs(item)
                    ],
                )
            )
        return source_groups

    @staticmethod
    def _ungrouped_failed_outcomes(
        failed_sessions,
        *,
        rank_start: int = 0,
    ) -> list[Outcome]:
        return [
            Outcome(
                id=_synthesized_id(
                    redact_text(resolved.session.title or resolved.session.session_id),
                    [resolved.session.session_id],
                    discriminator="failed",
                ),
                title=redact_text(resolved.session.title or resolved.session.session_id),
                status=OutcomeStatus.IN_PROGRESS,
                impact="",
                included=False,
                rank=rank_start + index,
                bucket=OutcomeBucket.UNGROUPED,
                evidence_refs=[
                    EvidenceRef(
                        session_id=redact_text(resolved.session.session_id),
                        repository_id=redact_text(resolved.repository.repository_id),
                    )
                ],
            )
            for index, resolved in enumerate(failed_sessions)
        ]

    @staticmethod
    def _ungrouped_evidence_outcomes(
        omitted: list[SessionEvidence],
        *,
        rank_start: int = 0,
    ) -> list[Outcome]:
        return [
            Outcome(
                id=_synthesized_id(
                    _fallback_title([evidence]),
                    [evidence.session_id],
                    discriminator="omitted",
                ),
                title=_fallback_title([evidence]),
                status=OutcomeStatus.IN_PROGRESS,
                impact="",
                included=False,
                rank=rank_start + index,
                bucket=OutcomeBucket.UNGROUPED,
                evidence_refs=_evidence_refs(evidence),
            )
            for index, evidence in enumerate(omitted)
        ]


def _most_recent_first(
    evidence_by_session: dict[str, SessionEvidence],
    started_at: dict[str, datetime],
) -> list[SessionEvidence]:
    """Order evidence newest first, leaving undated sessions in scan order."""

    scanned = list(evidence_by_session.values())
    dated = [item for item in scanned if item.session_id in started_at]
    # Python's sort keeps equal timestamps in scan order, both ways round.
    dated.sort(key=lambda item: started_at[item.session_id], reverse=True)
    return [*dated, *(item for item in scanned if item.session_id not in started_at)]


def _sessions_within_budget(
    ordered: list[SessionEvidence],
    *,
    max_bytes: int,
) -> list[SessionEvidence]:
    """Take sessions in order while the serialized payload stays in budget.

    The first session is always taken: a payload the model can refuse is still
    worth more than an empty one, and the sessions left behind stay visible as
    ungrouped candidates either way.
    """

    selected: list[SessionEvidence] = []
    total = 0
    for evidence in ordered:
        size = len(evidence.model_dump_json(indent=2).encode())
        if selected and total + size > max_bytes:
            break
        selected.append(evidence)
        total += size
    return selected


def _strip_json_fence(output: str) -> str:
    value = output.strip()
    if value.startswith("```json") and value.endswith("```"):
        return value[len("```json") : -len("```")].strip()
    return value


def _proposal_signature(
    proposal: _ProposedOutcome,
    selected: list[SessionEvidence],
) -> tuple[object, ...]:
    def normalize(value: str) -> str:
        return " ".join(value.split()).casefold()

    return (
        normalize(proposal.title),
        proposal.status,
        normalize(proposal.impact),
        tuple(sorted(item.session_id for item in selected)),
        proposal.confidence,
        tuple(
            sorted(
                (signal.kind, normalize(signal.value))
                for signal in proposal.linkage_signals
            )
        ),
    )


def _synthesized_id(
    title: str,
    session_ids: list[str],
    *,
    discriminator: str,
) -> str:
    normalized_title = " ".join(title.split()).casefold()
    value = "\0".join([normalized_title, *sorted(session_ids), discriminator])
    return sha256(value.encode()).hexdigest()[:16]


def _evidence_refs(evidence: SessionEvidence) -> list[EvidenceRef]:
    files = [item.text for item in evidence.files_changed]
    commit = _commit_from_evidence(evidence)
    if not files:
        return [
            EvidenceRef(
                session_id=evidence.session_id,
                repository_id=evidence.repository_id,
                commit=commit,
            )
        ]
    return [
        EvidenceRef(
            session_id=evidence.session_id,
            repository_id=evidence.repository_id,
            commit=commit,
            file=file,
        )
        for file in files
    ]


def _commit_from_evidence(evidence: SessionEvidence) -> str | None:
    for value in _local_texts(evidence):
        match = _COMMIT_PATTERN.search(value)
        if match:
            return match.group("commit")
    return None


def _local_texts(
    evidence: SessionEvidence,
    *,
    extra_values: list[str | None] | None = None,
) -> list[str]:
    texts = [
        evidence.session_id,
        evidence.repository_id,
        evidence.title,
        evidence.working_directory,
        *(extra_values or []),
    ]
    for collection in (
        evidence.goals,
        evidence.commands,
        evidence.files_changed,
        evidence.errors,
        evidence.outcomes,
    ):
        for item in collection:
            texts.append(item.text)
            texts.extend(item.source_activity_ids)
    return [value for value in texts if value]


def _corpus(
    selected: list[SessionEvidence],
    local_texts_by_session: dict[str, list[str]],
) -> str:
    return "\n".join(
        text
        for evidence in selected
        for text in local_texts_by_session.get(evidence.session_id, _local_texts(evidence))
    ).casefold()


def _value_is_observed(
    value: str,
    selected: list[SessionEvidence],
    local_texts_by_session: dict[str, list[str]],
) -> bool:
    normalized = " ".join(value.split()).casefold()
    if not normalized:
        return False
    return normalized in _corpus(selected, local_texts_by_session)


def _value_is_observed_in_every_repository(
    value: str,
    selected: list[SessionEvidence],
    local_texts_by_session: dict[str, list[str]],
) -> bool:
    evidence_by_repository: dict[str, list[SessionEvidence]] = {}
    for evidence in selected:
        evidence_by_repository.setdefault(evidence.repository_id, []).append(evidence)
    return all(
        _value_is_observed(value, repository_evidence, local_texts_by_session)
        for repository_evidence in evidence_by_repository.values()
    )


def _supported_title(
    proposed: str,
    selected: list[SessionEvidence],
    local_texts_by_session: dict[str, list[str]],
) -> str:
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", proposed.casefold())
        if len(word) > 2
    ]
    corpus = _corpus(selected, local_texts_by_session)
    if words and all(word in corpus for word in words):
        return proposed
    return _fallback_title(selected)


def _fallback_title(selected: list[SessionEvidence]) -> str:
    if len(selected) == 1:
        return selected[0].title or selected[0].session_id
    repositories = sorted({item.repository_id for item in selected})
    if len(repositories) > 1:
        return " / ".join(repositories)
    return " / ".join(item.title or item.session_id for item in selected)


def _supported_status(
    proposed: OutcomeStatus,
    selected: list[SessionEvidence],
) -> OutcomeStatus:
    if proposed is OutcomeStatus.IN_PROGRESS:
        return OutcomeStatus.IN_PROGRESS
    for evidence in selected:
        if any(
            item.status is EvidenceStatus.COMPLETED
            and item.confidence is EvidenceConfidence.HIGH
            for item in evidence.outcomes
        ):
            return OutcomeStatus.COMPLETED
    return OutcomeStatus.IN_PROGRESS


def _supported_impact(
    proposed: str,
    selected: list[SessionEvidence],
    local_texts_by_session: dict[str, list[str]],
) -> str:
    value = " ".join(proposed.split())
    if not value:
        return ""
    return proposed if value.casefold() in _corpus(selected, local_texts_by_session) else ""
