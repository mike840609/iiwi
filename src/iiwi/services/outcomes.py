"""Deterministic boundary between model proposals and extracted evidence."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from iiwi.config import DEFAULT_QUICK_REVIEW_MAX_EVIDENCE_BYTES
from iiwi.errors import IiwiError, OutcomeSynthesisError
from iiwi.extraction.pipeline import extract_evidence
from iiwi.models import (
    EvidenceRef,
    Outcome,
    OutcomeBucket,
    OutcomeSourceGroup,
    OutcomeStatus,
    OutcomeSynthesisResult,
)
from iiwi.models.evidence import (
    EvidenceConfidence,
    EvidenceItem,
    EvidenceStatus,
    SessionEvidence,
)
from iiwi.models.repository import ResolvedSession
from iiwi.security.redactor import redact_text, redact_value
from iiwi.services.scan import ScanResult
from iiwi.sessions.filtering import IIWI_SESSION_TITLE_PREFIX
from iiwi.summarizers.opencode_run import OpenCodeRunner
from iiwi.summarizers.outcome_prompt import build_outcome_prompt


class _LinkSignal(BaseModel):
    # Unknown fields are ignored, never read: only kinds this module recognizes
    # can gate anything, so an invented kind simply never matches.
    model_config = ConfigDict(extra="ignore")

    kind: str
    value: str


class _ProposedOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    status: OutcomeStatus
    impact: str = ""
    source_ids: list[str]
    confidence: EvidenceConfidence
    linkage_signals: list[_LinkSignal] = Field(default_factory=list)


class _SynthesisPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    outcomes: list[_ProposedOutcome]


class _CompactSession(BaseModel):
    """The only thing the model needs to group sessions: nothing else is sent.

    Iiwi reconstructs titles, statuses, impacts, and every evidence reference
    from local evidence afterwards, so commands, changed files, and errors would
    only cost budget the grouping cannot spend.
    """

    source_id: str
    repository_id: str
    title: str | None = None
    branch: str | None = None
    goal: str | None = None
    outcome: str | None = None

    def as_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class _CompactIndex(BaseModel):
    sessions: list[_CompactSession]


def _index_json(sessions: list[_CompactSession]) -> str:
    """The exact payload the model is sent.

    The budget is measured through this function and the transcript is built by
    it, so what is counted and what is sent cannot drift apart.
    """

    return _CompactIndex(sessions=sessions).model_dump_json(indent=2, exclude_none=True)


@dataclass(frozen=True)
class _ExtractedSessions:
    """What the extraction loop learned from one scan, shared by every caller."""

    evidence_by_source: dict[str, SessionEvidence]
    compact_by_source: dict[str, _CompactSession]
    local_texts_by_source: dict[str, list[str]]
    started_at: dict[str, datetime]
    failed_sessions: list[ResolvedSession]


def _extract_sessions(scan: ScanResult) -> _ExtractedSessions:
    """Run the boundary extraction once for a scan.

    `extract_evidence` plus a recursive redaction of every session's full
    evidence is the expensive half of a generate, so `synthesize` runs it once
    and measures the budget from what it produced.
    """

    evidence_by_source: dict[str, SessionEvidence] = {}
    compact_by_source: dict[str, _CompactSession] = {}
    local_texts_by_source: dict[str, list[str]] = {}
    started_at: dict[str, datetime] = {}
    failed_sessions: list[ResolvedSession] = []
    for resolved in scan.resolved_sessions:
        try:
            extracted = extract_evidence(resolved)
            redacted = redact_value(extracted.model_dump(mode="json"))
            model_evidence = SessionEvidence.model_validate(redacted)
            source_id = _source_id(extracted)
            compact = _compact_session(
                model_evidence,
                source_id=source_id,
                branch=resolved.session.branch or resolved.repository.branch,
            )
            local_texts = _local_texts(
                model_evidence,
                # These come from the resolved session rather than the
                # redacted evidence, so they are redacted here: the corpus
                # validates model output, and the model only ever saw the
                # redacted form.
                extra_values=[
                    redact_text(value)
                    for value in (
                        resolved.session.branch,
                        resolved.repository.branch,
                        resolved.repository.repository_id,
                        resolved.repository.display_name,
                    )
                    if value
                ],
            )
        except Exception:  # Extraction failures remain visible candidates.
            failed_sessions.append(resolved)
            continue
        # Every map is written together. A session recorded in one and missing
        # from another is counted as extracted and as failed at the same time,
        # and `_corpus` then has no redacted texts to read for it.
        # Durable provenance stays raw and local. The model sees only this
        # opaque token and the separately redacted compact fields.
        evidence_by_source[source_id] = extracted
        compact_by_source[source_id] = compact
        local_texts_by_source[source_id] = local_texts
        if resolved.session.created_at is not None:
            started_at[source_id] = resolved.session.created_at
    return _ExtractedSessions(
        evidence_by_source=evidence_by_source,
        compact_by_source=compact_by_source,
        local_texts_by_source=local_texts_by_source,
        started_at=started_at,
        failed_sessions=failed_sessions,
    )


@dataclass(frozen=True)
class SynthesisBudgetEstimate:
    """What a selection costs, measured before any model call is spent."""

    selected_count: int
    fit_count: int
    bytes_used: int
    max_bytes: int

    @property
    def over_limit(self) -> bool:
        """Whether the payload synthesis would send is larger than the budget.

        Bytes, not counts. `_sessions_within_budget` always keeps the first
        session, so one selected session larger than the whole budget leaves
        `fit_count == selected_count` while the payload still cannot be sent.
        The comparison runs both ways — a selection inside the budget is never
        trimmed — so it covers the held-back case too, and it does not read a
        session that failed extraction as a budget problem.
        """

        return self.bytes_used > self.max_bytes


class SynthesisBudgetExceededError(IiwiError):
    """Raised when the selection is larger than one synthesis can carry.

    Carries the measurement, so a caller that decides to send what fits anyway
    already knows the cost and never re-extracts the selection to learn it.
    """

    def __init__(self, estimate: SynthesisBudgetEstimate) -> None:
        super().__init__(
            f"{estimate.selected_count} selected session(s) need "
            f"{estimate.bytes_used} bytes of evidence, over the "
            f"{estimate.max_bytes}-byte Quick Review budget"
        )
        self.estimate = estimate


@dataclass(frozen=True)
class _BudgetedPayload:
    """The sessions synthesis will send, beside the measurement of all of them."""

    sent: list[_CompactSession]
    estimate: SynthesisBudgetEstimate


def _budgeted_payload(
    extracted: _ExtractedSessions,
    *,
    selected_count: int,
    max_bytes: int,
) -> _BudgetedPayload:
    """Order newest first, trim to the budget, and measure what that cost.

    Ordering and trim live here alone, and the estimate is read off the very
    list the model is then sent, so what the guard reports and what synthesis
    sends cannot drift apart.
    """

    ordered = [
        extracted.compact_by_source[source_id]
        for source_id in _most_recent_first(extracted.evidence_by_source, extracted.started_at)
    ]
    sent = _sessions_within_budget(ordered, max_bytes=max_bytes)
    return _BudgetedPayload(
        sent=sent,
        estimate=SynthesisBudgetEstimate(
            # What the user selected, not what extraction produced: this number
            # is read beside the checked rows, and a session whose extraction
            # failed is still one of them. Deselecting it has to move the count.
            selected_count=selected_count,
            fit_count=len(sent),
            bytes_used=len(_index_json(ordered).encode()),
            max_bytes=max_bytes,
        ),
    )


def _budget_warnings(estimate: SynthesisBudgetEstimate, *, held_back: int) -> list[str]:
    """Account for what the budget cost a selection that was sent anyway.

    Quick Review names the cost before the run and can narrow the selection;
    the Daily window is fixed by its date, so for Daily this is the whole
    account of work the byte counter left out of the standup.
    """

    if held_back:
        return [
            f"{held_back} older session(s) did not fit the Quick Review evidence "
            f"budget ({estimate.bytes_used} / {estimate.max_bytes} bytes) and were "
            "left as ungrouped candidates"
        ]
    if estimate.over_limit:
        return [
            f"The selected evidence is {estimate.bytes_used} bytes, over the "
            f"{estimate.max_bytes}-byte Quick Review budget, and was sent anyway"
        ]
    return []


# Measured, not guessed: across one live synthesis the all-or-nothing gate
# refused five of ten proposals at 84.6%, 66.7%, 85.7%, 90.9% and 90.0% word
# support, and the words that missed were "selection", "improvements",
# "feature", "wave", "polish", "bars" and "housekeeping" — summarizing
# vocabulary, not claims about the work. Status and impact keep their own,
# stricter gates.
_TITLE_SUPPORT_RATIO = 0.8

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

    def synthesize(self, scan: ScanResult, *, force: bool = False) -> OutcomeSynthesisResult:
        """Group the selection into outcomes, refusing more than the budget carries.

        The budget is decided here, where the extraction it measures already
        happens, rather than by a probe each entry point has to remember: one
        extraction pass per generate, and every caller guarded by construction.
        `force` sends the newest sessions that fit and leaves the rest as
        ungrouped candidates — for a caller that has seen the cost, or whose
        window cannot be narrowed.
        """

        extracted = _extract_sessions(scan)
        if not extracted.evidence_by_source:
            raise OutcomeSynthesisError("could not extract evidence from any selected session")

        budgeted = _budgeted_payload(
            extracted,
            selected_count=len(scan.resolved_sessions),
            max_bytes=self._max_evidence_bytes,
        )
        if budgeted.estimate.over_limit and not force:
            raise SynthesisBudgetExceededError(budgeted.estimate)
        sent_by_source = {
            entry.source_id: extracted.evidence_by_source[entry.source_id]
            for entry in budgeted.sent
        }
        warnings = _budget_warnings(
            budgeted.estimate,
            held_back=len(extracted.evidence_by_source) - len(sent_by_source),
        )

        try:
            output = self._runner.run(
                transcript=_index_json(budgeted.sent),
                prompt=build_outcome_prompt(),
                title=f"{IIWI_SESSION_TITLE_PREFIX}outcome synthesis",
            )
        except OSError as exc:
            raise OutcomeSynthesisError(str(exc)) from exc
        payload = self._parse_payload(output)
        outcomes: list[Outcome] = []
        used_source_ids: set[str] = set()
        seen_proposals: set[tuple[object, ...]] = set()
        for proposal in payload.outcomes:
            selected = self._selected_evidence(proposal, sent_by_source)
            if not selected:
                # No known session survived: skip the proposal and leave its
                # sessions available as ungrouped candidates.
                continue
            used_source_ids.update(_source_id(item) for item in selected)
            signature = _proposal_signature(proposal, selected)
            if signature in seen_proposals:
                continue
            proposal_index = len(seen_proposals)
            seen_proposals.add(signature)
            outcomes.extend(
                self._outcomes_for_proposal(
                    proposal,
                    selected,
                    extracted.local_texts_by_source,
                    proposal_index=proposal_index,
                )
            )

        for rank, outcome in enumerate(outcomes):
            outcome.rank = rank
            outcome.bucket = OutcomeBucket.PRIMARY if rank < 5 else OutcomeBucket.MORE
            outcome.included = rank < 5

        omitted = [
            evidence
            for source_id, evidence in extracted.evidence_by_source.items()
            if source_id not in used_source_ids
        ]
        ungrouped = [
            *self._ungrouped_evidence_outcomes(omitted, rank_start=len(outcomes)),
            *self._ungrouped_failed_outcomes(
                extracted.failed_sessions,
                rank_start=len(outcomes) + len(omitted),
            ),
        ]
        return OutcomeSynthesisResult(
            outcomes=[*outcomes, *ungrouped],
            failed_session_ids=[item.session.session_id for item in extracted.failed_sessions],
            warnings=warnings,
        )

    @staticmethod
    def _parse_payload(output: str) -> _SynthesisPayload:
        raw = _extract_json_object(output)
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
        evidence_by_source: dict[str, SessionEvidence],
    ) -> list[SessionEvidence]:
        selected = []
        for source_id in proposal.source_ids:
            # Unknown ids are dropped rather than fatal: the surviving sessions
            # still bound every claim, so a narrower selection is only safer.
            evidence = evidence_by_source.get(source_id)
            if evidence is not None and evidence not in selected:
                selected.append(evidence)
        return selected

    def _outcomes_for_proposal(
        self,
        proposal: _ProposedOutcome,
        selected: list[SessionEvidence],
        local_texts_by_source: dict[str, list[str]],
        *,
        proposal_index: int,
    ) -> list[Outcome]:
        by_repository: dict[str, list[SessionEvidence]] = {}
        for evidence in selected:
            by_repository.setdefault(evidence.repository_id, []).append(evidence)

        if len(by_repository) == 1 or self._may_merge_cross_repository(
            proposal, selected, local_texts_by_source
        ):
            return [
                self._outcome(
                    proposal,
                    selected,
                    local_texts_by_source,
                    source_groups=self._source_groups(
                        proposal,
                        selected,
                        local_texts_by_source,
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
                local_texts_by_source,
                source_groups=self._source_groups(
                    proposal,
                    repository_evidence,
                    local_texts_by_source,
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
        local_texts_by_source: dict[str, list[str]],
    ) -> bool:
        if proposal.confidence is not EvidenceConfidence.HIGH:
            return False

        def observed_by_repository(value: str) -> bool:
            return _value_is_observed_in_every_repository(value, selected, local_texts_by_source)

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
        local_texts_by_source: dict[str, list[str]],
        *,
        source_groups: list[OutcomeSourceGroup] | None = None,
        discriminator: str,
    ) -> Outcome:
        source_ids = [_source_id(item) for item in selected]
        title = _supported_title(proposal.title, selected, local_texts_by_source)
        status = _supported_status(proposal.status, selected)
        impact = _supported_impact(proposal.impact, selected, local_texts_by_source)
        return Outcome(
            id=_synthesized_id(title, source_ids, discriminator=discriminator),
            title=title,
            status=status,
            impact=impact,
            rank=0,
            evidence_refs=[reference for item in selected for reference in _evidence_refs(item)],
            source_groups=source_groups or [],
        )

    @staticmethod
    def _source_groups(
        proposal: _ProposedOutcome,
        selected: list[SessionEvidence],
        local_texts_by_source: dict[str, list[str]],
        *,
        group_by_repository: bool,
    ) -> list[OutcomeSourceGroup]:
        groups: dict[str, list[SessionEvidence]] = {}
        for evidence in selected:
            key = evidence.repository_id if group_by_repository else _source_id(evidence)
            groups.setdefault(key, []).append(evidence)
        source_groups: list[OutcomeSourceGroup] = []
        for key, evidence_items in groups.items():
            source_groups.append(
                OutcomeSourceGroup(
                    id=key,
                    title=(
                        redact_text(key)
                        if group_by_repository
                        else _fallback_title(evidence_items)
                    ),
                    impact=_supported_impact(
                        proposal.impact,
                        evidence_items,
                        local_texts_by_source,
                    ),
                    status=_supported_status(proposal.status, evidence_items),
                    evidence_refs=[
                        reference for item in evidence_items for reference in _evidence_refs(item)
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
                    [_source_token(resolved.session.harness, resolved.session.session_id)],
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
                        session_id=resolved.session.session_id,
                        repository_id=resolved.repository.repository_id,
                        harness=resolved.session.harness,
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
                    [_source_id(evidence)],
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
    evidence_by_source: dict[str, SessionEvidence],
    started_at: dict[str, datetime],
) -> list[str]:
    """Order evidence newest first, leaving undated sessions in scan order."""

    scanned = list(evidence_by_source)
    dated = [source_id for source_id in scanned if source_id in started_at]
    # Python's sort keeps equal timestamps in scan order, both ways round.
    dated.sort(key=lambda source_id: started_at[source_id], reverse=True)
    return [*dated, *(source_id for source_id in scanned if source_id not in started_at)]


def _compact_session(
    evidence: SessionEvidence,
    *,
    source_id: str,
    branch: str | None,
) -> _CompactSession:
    """Reduce redacted evidence to the fields grouping actually reads.

    Every field but the branch is already redacted; the branch comes from the
    resolved session, so it is redacted here before it can reach the model.
    """

    return _CompactSession(
        source_id=source_id,
        repository_id=evidence.repository_id,
        title=_omit_if_blank(evidence.title),
        branch=_omit_if_blank(redact_text(branch) if branch else None),
        goal=_first_text(evidence.goals),
        outcome=_claimed_outcome_text(evidence.outcomes),
    )


def _omit_if_blank(value: str | None) -> str | None:
    return value if value and value.strip() else None


def _first_text(items: list[EvidenceItem]) -> str | None:
    """The first non-blank text, whole.

    Extraction already caps evidence text; shortening it again here would only
    strip the overlap grouping reads to decide whether two sessions are the same
    work. How many sessions fit is the budget's decision, not this function's.
    """

    for item in items:
        text = _omit_if_blank(item.text)
        if text is not None:
            return text
    return None


def _claimed_outcome_text(items: list[EvidenceItem]) -> str | None:
    """The session's own claim about what it accomplished, when it made one.

    Outcomes are appended in activity order, and the mechanical ones land first:
    a passing verification command reads "Verification passed: pytest …" whatever
    the work was. Sending that would give every session in a repository running
    one test command an identical outcome — similar wording, to a model whose one
    job is to group by wording — while the claim that distinguishes them, which
    extraction appends later, never arrives at all. Goals stay first-wins: they
    come from user messages in activity order, where first is genuinely first.
    """

    claims = [item for item in items if item.extraction_method == "assistant_claim"]
    return _first_text(claims) or _first_text(items)


def _sessions_within_budget(
    ordered: list[_CompactSession],
    *,
    max_bytes: int,
) -> list[_CompactSession]:
    """Take sessions in order while the serialized payload stays in budget.

    The per-entry sizes only choose candidates: they miss the index envelope,
    the deeper indentation each entry picks up inside it, and the separators
    between entries, so the selection is then measured as it will actually be
    sent and trimmed from the oldest end until it fits. Serializing repeatedly
    costs nothing here — this runs once per synthesis and usually trims nothing.

    The first session is always taken: a payload the model can refuse is still
    worth more than an empty one, and the sessions left behind stay visible as
    ungrouped candidates either way.
    """

    selected: list[_CompactSession] = []
    total = 0
    for entry in ordered:
        size = len(entry.as_json().encode())
        if selected and total + size > max_bytes:
            break
        selected.append(entry)
        total += size
    while len(selected) > 1 and len(_index_json(selected).encode()) > max_bytes:
        selected.pop()
    return selected


def _extract_json_object(output: str) -> str:
    """Return the first JSON object in the output, ignoring fences and prose."""
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            _, end = decoder.raw_decode(output, index)
        except ValueError:
            continue
        return output[index:end]
    return ""


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
        tuple(sorted(_source_id(item) for item in selected)),
        proposal.confidence,
        tuple(
            sorted((signal.kind, normalize(signal.value)) for signal in proposal.linkage_signals)
        ),
    )


def _synthesized_id(
    title: str,
    source_ids: list[str],
    *,
    discriminator: str,
) -> str:
    normalized_title = " ".join(title.split()).casefold()
    value = "\0".join([normalized_title, *sorted(source_ids), discriminator])
    return sha256(value.encode()).hexdigest()[:16]


def _evidence_refs(evidence: SessionEvidence) -> list[EvidenceRef]:
    files = [item.text for item in evidence.files_changed]
    commit = _commit_from_evidence(evidence)
    activity_ids = _activity_ids(evidence)
    if not files:
        return [
            EvidenceRef(
                session_id=evidence.session_id,
                repository_id=evidence.repository_id,
                harness=evidence.harness,
                activity_ids=activity_ids,
                commit=commit,
            )
        ]
    return [
        EvidenceRef(
            session_id=evidence.session_id,
            repository_id=evidence.repository_id,
            harness=evidence.harness,
            activity_ids=activity_ids,
            commit=commit,
            file=file,
        )
        for file in files
    ]


def _activity_ids(evidence: SessionEvidence) -> list[str]:
    return sorted(
        {
            activity_id
            for collection in (
                evidence.goals,
                evidence.commands,
                evidence.files_changed,
                evidence.errors,
                evidence.outcomes,
            )
            for item in collection
            for activity_id in item.source_activity_ids
        }
    )


def _source_id(evidence: SessionEvidence) -> str:
    return _source_token(evidence.harness, evidence.session_id)


def _source_token(harness: str, session_id: str) -> str:
    """Return an opaque model token without exposing durable identifiers."""

    durable_key = json.dumps(
        [harness, session_id],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"source-{sha256(durable_key.encode()).hexdigest()}"


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
        evidence.harness,
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
    local_texts_by_source: dict[str, list[str]],
) -> str:
    # Indexed, not `.get(..., _local_texts(evidence))`. The fallback read the
    # raw evidence, which is kept unredacted on purpose, so a missing entry
    # would quietly validate model output against text the model never saw.
    # `_extract_sessions` writes this map for every session it keeps, so a
    # missing key is a broken invariant and should say so.
    return "\n".join(
        text for evidence in selected for text in local_texts_by_source[_source_id(evidence)]
    ).casefold()


def _value_is_observed(
    value: str,
    selected: list[SessionEvidence],
    local_texts_by_source: dict[str, list[str]],
) -> bool:
    normalized = " ".join(value.split()).casefold()
    if not normalized:
        return False
    return normalized in _corpus(selected, local_texts_by_source)


def _value_is_observed_in_every_repository(
    value: str,
    selected: list[SessionEvidence],
    local_texts_by_source: dict[str, list[str]],
) -> bool:
    evidence_by_repository: dict[str, list[SessionEvidence]] = {}
    for evidence in selected:
        evidence_by_repository.setdefault(evidence.repository_id, []).append(evidence)
    return all(
        _value_is_observed(value, repository_evidence, local_texts_by_source)
        for repository_evidence in evidence_by_repository.values()
    )


def _supported_title(
    proposed: str,
    selected: list[SessionEvidence],
    local_texts_by_source: dict[str, list[str]],
) -> str:
    words = [word for word in re.findall(r"[a-z0-9]+", proposed.casefold()) if len(word) > 2]
    if not words:
        return _fallback_title(selected)
    corpus = _corpus(selected, local_texts_by_source)
    supported = sum(1 for word in words if word in corpus)
    if supported / len(words) >= _TITLE_SUPPORT_RATIO:
        return proposed
    return _fallback_title(selected)


def _evidence_weight(evidence: SessionEvidence) -> int:
    """Count what extraction learned about a session: goals, commands, errors,
    and outcomes.

    Not the evidence-reference count: references are one per changed file, so a
    rename sweep across fifty files would outrank the feature work beside it.
    `files_changed` is excluded for the same reason — how much a session touched
    is not how substantive it was.
    """

    return sum(
        len(collection)
        for collection in (
            evidence.goals,
            evidence.commands,
            evidence.errors,
            evidence.outcomes,
        )
    )


def _fallback_title(selected: list[SessionEvidence]) -> str:
    if len(selected) == 1:
        return redact_text(selected[0].title or selected[0].session_id)
    repositories = sorted({item.repository_id for item in selected})
    if len(repositories) > 1:
        return " / ".join(redact_text(repository) for repository in repositories)
    anchor = max(selected, key=_evidence_weight)
    others = len(selected) - 1
    plural = "session" if others == 1 else "sessions"
    title = redact_text(anchor.title or anchor.session_id)
    return f"{title} and {others} more {plural}"


def _supported_status(
    proposed: OutcomeStatus,
    selected: list[SessionEvidence],
) -> OutcomeStatus:
    if proposed is OutcomeStatus.IN_PROGRESS:
        return OutcomeStatus.IN_PROGRESS
    for evidence in selected:
        if any(
            item.status is EvidenceStatus.COMPLETED and item.confidence is EvidenceConfidence.HIGH
            for item in evidence.outcomes
        ):
            return OutcomeStatus.COMPLETED
    return OutcomeStatus.IN_PROGRESS


def _supported_impact(
    proposed: str,
    selected: list[SessionEvidence],
    local_texts_by_source: dict[str, list[str]],
) -> str:
    value = " ".join(proposed.split())
    if not value:
        return ""
    return proposed if value.casefold() in _corpus(selected, local_texts_by_source) else ""
