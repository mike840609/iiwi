"""Project evidence-gated outcomes into a Daily Standup review draft."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import uuid4

from iiwi.extraction.pipeline import extract_evidence
from iiwi.models.daily import (
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.models.evidence import EvidenceItem, EvidenceStatus, SessionEvidence
from iiwi.models.outcome import EvidenceRef, Outcome, OutcomeBucket, OutcomeStatus
from iiwi.models.repository import ResolvedSession
from iiwi.security.redactor import redact_text
from iiwi.services.daily_scan import DailyScanResult

Source = tuple[str, str]
ActivityKey = tuple[str, str, str]


def project_daily_standup(
    *,
    daily_scan: DailyScanResult,
    outcomes: list[Outcome],
) -> DailyStandupDraft:
    """Project existing outcome titles using only their timestamped evidence."""

    activity_times, evidence_by_source = _index_scan(daily_scan)
    work_items: list[DailyStandupWorkItem] = []
    ordered_outcomes = sorted(outcomes, key=lambda item: item.rank)
    for outcome in ordered_outcomes:
        yesterday_refs = _refs_in_window(
            outcome.evidence_refs,
            activity_times,
            start=daily_scan.window.yesterday_start,
            end=daily_scan.window.today_start,
        )
        today_refs = _refs_in_window(
            outcome.evidence_refs,
            activity_times,
            start=daily_scan.window.today_start,
            end=daily_scan.window.now,
        )
        yesterday = _activity_item(
            statement=outcome.title,
            refs=yesterday_refs,
            source=DailyStatementSource.ACTIVITY_YESTERDAY,
        )
        today = _activity_item(
            statement=outcome.title,
            refs=today_refs,
            source=DailyStatementSource.ACTIVITY_TODAY,
            new_activity=True,
        )
        suggestion_refs = _yesterday_in_progress_signal_refs(
            yesterday_refs,
            activity_times=activity_times,
            evidence_by_source=evidence_by_source,
            yesterday_start=daily_scan.window.yesterday_start,
            today_start=daily_scan.window.today_start,
        )
        if (
            today is None
            and outcome.status is OutcomeStatus.IN_PROGRESS
            and suggestion_refs
        ):
            today = DailySectionItem(
                statement=outcome.title,
                evidence_refs=suggestion_refs,
                source=DailyStatementSource.SUGGESTED_FROM_YESTERDAY,
            )

        blocker = None
        if outcome.status is OutcomeStatus.IN_PROGRESS:
            blocker = _blocker_item(
                refs=outcome.evidence_refs,
                activity_times=activity_times,
                evidence_by_source=evidence_by_source,
                scan_since=daily_scan.window.yesterday_start,
                scan_until=daily_scan.window.now,
            )

        if yesterday is None and today is None and blocker is None:
            continue
        work_items.append(
            DailyStandupWorkItem(
                id=uuid4().hex,
                source_outcome_ids=[outcome.id],
                repository_ids=_stable_unique(
                    ref.repository_id for ref in outcome.evidence_refs
                ),
                yesterday=yesterday,
                today=today,
                blocker=blocker,
            )
        )

    _rank_and_bucket(work_items)
    return _draft(daily_scan=daily_scan, work_items=work_items)


def build_daily_fallback(*, daily_scan: DailyScanResult) -> DailyStandupDraft:
    """Build a deterministic Daily draft from local evidence without a model call."""

    activity_times, evidence_by_source = _index_scan(daily_scan)
    work_items: list[DailyStandupWorkItem] = []
    for resolved in daily_scan.scan.resolved_sessions:
        source = (resolved.session.harness, resolved.session.session_id)
        evidence = evidence_by_source[source]
        yesterday = _fallback_activity_item(
            resolved=resolved,
            evidence=evidence,
            activity_times=activity_times,
            start=daily_scan.window.yesterday_start,
            end=daily_scan.window.today_start,
            source=DailyStatementSource.ACTIVITY_YESTERDAY,
        )
        today = _fallback_activity_item(
            resolved=resolved,
            evidence=evidence,
            activity_times=activity_times,
            start=daily_scan.window.today_start,
            end=daily_scan.window.now,
            source=DailyStatementSource.ACTIVITY_TODAY,
            new_activity=True,
        )
        yesterday_ref = EvidenceRef(
            harness=source[0],
            session_id=source[1],
            repository_id=resolved.repository.repository_id,
            activity_ids=[
                activity.activity_id
                for activity in resolved.session.activities
                if activity.timestamp is not None
                and daily_scan.window.yesterday_start
                <= activity.timestamp
                < daily_scan.window.today_start
            ],
        )
        suggestion_refs = _yesterday_in_progress_signal_refs(
            [yesterday_ref],
            activity_times=activity_times,
            evidence_by_source=evidence_by_source,
            yesterday_start=daily_scan.window.yesterday_start,
            today_start=daily_scan.window.today_start,
        )
        if today is None and yesterday is not None and suggestion_refs:
            today = DailySectionItem(
                statement=yesterday.statement,
                evidence_refs=suggestion_refs,
                source=DailyStatementSource.SUGGESTED_FROM_YESTERDAY,
            )

        session_ref = EvidenceRef(
            harness=source[0],
            session_id=source[1],
            repository_id=resolved.repository.repository_id,
            activity_ids=[
                activity.activity_id for activity in resolved.session.activities
            ],
        )
        blocker = _blocker_item(
            refs=[session_ref],
            activity_times=activity_times,
            evidence_by_source=evidence_by_source,
            scan_since=daily_scan.window.yesterday_start,
            scan_until=daily_scan.window.now,
        )
        if yesterday is None and today is None and blocker is None:
            continue
        work_items.append(
            DailyStandupWorkItem(
                id=uuid4().hex,
                repository_ids=[resolved.repository.repository_id],
                yesterday=yesterday,
                today=today,
                blocker=blocker,
            )
        )

    _rank_and_bucket(work_items)
    return _draft(daily_scan=daily_scan, work_items=work_items, fallback=True)


def _draft(
    *,
    daily_scan: DailyScanResult,
    work_items: list[DailyStandupWorkItem],
    fallback: bool = False,
) -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=daily_scan.window.standup_date,
        scan_since=daily_scan.window.yesterday_start,
        scan_until=daily_scan.window.now,
        work_items=work_items,
        warnings=list(daily_scan.scan.warnings),
        coverage_warnings=list(daily_scan.coverage_warnings),
        successful_harnesses=list(daily_scan.successful_harnesses),
        unavailable_harnesses=list(daily_scan.unavailable_harnesses),
        repository_count=len(daily_scan.scan.sessions_by_repository),
        session_count=daily_scan.scan.loaded_session_count,
        fallback=fallback,
    )


def _index_scan(
    daily_scan: DailyScanResult,
) -> tuple[dict[ActivityKey, datetime], dict[Source, SessionEvidence]]:
    activity_times: dict[ActivityKey, datetime] = {}
    evidence_by_source: dict[Source, SessionEvidence] = {}
    for resolved in daily_scan.scan.resolved_sessions:
        source = (resolved.session.harness, resolved.session.session_id)
        evidence_by_source[source] = extract_evidence(resolved)
        for activity in resolved.session.activities:
            if activity.timestamp is not None:
                activity_times[(*source, activity.activity_id)] = activity.timestamp
    return activity_times, evidence_by_source


def _source(ref: EvidenceRef) -> Source | None:
    if ref.harness is None:
        return None
    return ref.harness, ref.session_id


def _refs_in_window(
    refs: list[EvidenceRef],
    activity_times: dict[ActivityKey, datetime],
    *,
    start: datetime,
    end: datetime,
) -> list[EvidenceRef]:
    selected: list[EvidenceRef] = []
    for ref in refs:
        source = _source(ref)
        if source is None:
            continue
        activity_ids = [
            activity_id
            for activity_id in ref.activity_ids
            if (timestamp := activity_times.get((*source, activity_id))) is not None
            and start <= timestamp < end
        ]
        if activity_ids:
            selected.append(ref.model_copy(update={"activity_ids": activity_ids}))
    return selected


def _activity_item(
    *,
    statement: str,
    refs: list[EvidenceRef],
    source: DailyStatementSource,
    new_activity: bool = False,
) -> DailySectionItem | None:
    if not refs:
        return None
    return DailySectionItem(
        statement=statement,
        evidence_refs=refs,
        source=source,
        new_activity=new_activity,
    )


def _evidence_items(evidence: SessionEvidence) -> Iterable[EvidenceItem]:
    yield from evidence.goals
    yield from evidence.commands
    yield from evidence.files_changed
    yield from evidence.errors
    yield from evidence.outcomes


def _yesterday_in_progress_signal_refs(
    refs: list[EvidenceRef],
    *,
    activity_times: dict[ActivityKey, datetime],
    evidence_by_source: dict[Source, SessionEvidence],
    yesterday_start: datetime,
    today_start: datetime,
) -> list[EvidenceRef]:
    signal_refs: list[EvidenceRef] = []
    for ref in refs:
        source = _source(ref)
        evidence = evidence_by_source.get(source) if source is not None else None
        if source is None or evidence is None:
            continue
        referenced = set(ref.activity_ids)
        signal_ids: list[str] = []
        for item in (*evidence.goals, *evidence.outcomes):
            if item.status is not EvidenceStatus.IN_PROGRESS:
                continue
            for activity_id in item.source_activity_ids:
                timestamp = activity_times.get((*source, activity_id))
                if (
                    activity_id in referenced
                    and timestamp is not None
                    and yesterday_start <= timestamp < today_start
                ):
                    signal_ids.append(activity_id)
        if signal_ids:
            signal_refs.append(
                ref.model_copy(update={"activity_ids": _stable_unique(signal_ids)})
            )
    return signal_refs


def _blocker_item(
    *,
    refs: list[EvidenceRef],
    activity_times: dict[ActivityKey, datetime],
    evidence_by_source: dict[Source, SessionEvidence],
    scan_since: datetime,
    scan_until: datetime,
) -> DailySectionItem | None:
    candidates: list[tuple[datetime, str, EvidenceRef]] = []
    for ref in refs:
        source = _source(ref)
        evidence = evidence_by_source.get(source) if source is not None else None
        if source is None or evidence is None:
            continue
        referenced = set(ref.activity_ids)
        completions = [
            timestamp
            for item in _evidence_items(evidence)
            if item.status is EvidenceStatus.COMPLETED
            for activity_id in item.source_activity_ids
            if (timestamp := activity_times.get((*source, activity_id))) is not None
            and scan_since <= timestamp < scan_until
        ]
        for error in evidence.errors:
            if error.status is not EvidenceStatus.BLOCKED:
                continue
            for activity_id in error.source_activity_ids:
                timestamp = activity_times.get((*source, activity_id))
                if (
                    activity_id not in referenced
                    or timestamp is None
                    or not scan_since <= timestamp < scan_until
                    or any(completed_at > timestamp for completed_at in completions)
                ):
                    continue
                error_ref = ref.model_copy(update={"activity_ids": [activity_id]})
                candidates.append((timestamp, redact_text(error.text), error_ref))
    if not candidates:
        return None
    _, statement, ref = max(candidates, key=lambda candidate: candidate[0])
    return DailySectionItem(
        statement=statement,
        evidence_refs=[ref],
        included=False,
        source=DailyStatementSource.DETECTED_BLOCKER,
    )


def _fallback_activity_item(
    *,
    resolved: ResolvedSession,
    evidence: SessionEvidence,
    activity_times: dict[ActivityKey, datetime],
    start: datetime,
    end: datetime,
    source: DailyStatementSource,
    new_activity: bool = False,
) -> DailySectionItem | None:
    source_key = (resolved.session.harness, resolved.session.session_id)
    activity_ids = [
        activity.activity_id
        for activity in resolved.session.activities
        if activity.timestamp is not None and start <= activity.timestamp < end
    ]
    if not activity_ids:
        return None
    in_window = set(activity_ids)
    chosen = _best_evidence(evidence.outcomes, source_key, in_window, activity_times)
    if chosen is None:
        chosen = _best_evidence(evidence.goals, source_key, in_window, activity_times)
    if chosen is not None:
        statement = chosen.text
        referenced_ids = [
            activity_id
            for activity_id in chosen.source_activity_ids
            if activity_id in in_window
        ]
    else:
        statement = resolved.session.title or resolved.repository.display_name
        referenced_ids = activity_ids
    return DailySectionItem(
        statement=redact_text(statement),
        evidence_refs=[
            EvidenceRef(
                harness=source_key[0],
                session_id=source_key[1],
                repository_id=resolved.repository.repository_id,
                activity_ids=referenced_ids,
            )
        ],
        source=source,
        new_activity=new_activity,
    )


def _best_evidence(
    items: list[EvidenceItem],
    source: Source,
    in_window: set[str],
    activity_times: dict[ActivityKey, datetime],
) -> EvidenceItem | None:
    matching = [
        item
        for item in items
        if any(activity_id in in_window for activity_id in item.source_activity_ids)
    ]
    if not matching:
        return None
    return max(
        matching,
        key=lambda item: max(
            activity_times[(*source, activity_id)]
            for activity_id in item.source_activity_ids
            if activity_id in in_window
        ),
    )


def _rank_and_bucket(work_items: list[DailyStandupWorkItem]) -> None:
    for attribute in ("yesterday", "today"):
        section_items = [
            item
            for work_item in work_items
            if (item := getattr(work_item, attribute)) is not None
        ]
        for rank, item in enumerate(section_items):
            item.rank = rank
            item.bucket = OutcomeBucket.PRIMARY if rank < 5 else OutcomeBucket.MORE
            item.included = rank < 5
    blockers = [
        work_item.blocker for work_item in work_items if work_item.blocker is not None
    ]
    for rank, blocker in enumerate(blockers):
        blocker.rank = rank
        blocker.bucket = OutcomeBucket.PRIMARY


def _stable_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
