"""Reconcile fresh Daily evidence with reviewer-owned same-day state."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import uuid4

from iiwi.models.daily import (
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.models.outcome import EvidenceRef

ExactKey = tuple[str, str, str]
CoarseKey = tuple[str, str]
RefKey = tuple[str | None, str, str, str | None, str | None]

_SECTION_ATTRIBUTES = ("yesterday", "today", "blocker")


def reconcile_daily_draft(
    previous: DailyStandupDraft | None,
    fresh: DailyStandupDraft,
) -> DailyStandupDraft:
    """Preserve review decisions while admitting only evidence-identified activity."""

    previous_items = previous.work_items if previous is not None else []
    matches: dict[int, DailyStandupWorkItem] = {}
    unmatched_fresh: list[DailyStandupWorkItem] = []
    used_previous: set[int] = set()

    for fresh_item in fresh.work_items:
        match = _matching_previous(previous_items, fresh_item)
        if match is None or match in used_previous:
            unmatched_fresh.append(fresh_item)
            continue
        matches[match] = fresh_item
        used_previous.add(match)

    next_ranks = {
        attribute: _next_rank(previous_items, attribute)
        for attribute in _SECTION_ATTRIBUTES
    }
    reconciled: list[DailyStandupWorkItem] = []
    for index, previous_item in enumerate(previous_items):
        matched_fresh = matches.get(index)
        if matched_fresh is None:
            reconciled.append(previous_item.model_copy(deep=True))
            continue
        reconciled.append(
            _merge_work_item(
                previous_item,
                matched_fresh,
                next_ranks=next_ranks,
            )
        )

    for fresh_item in unmatched_fresh:
        reconciled.append(_new_work_item(fresh_item, next_ranks=next_ranks))

    return fresh.model_copy(update={"work_items": reconciled}, deep=True)


def _matching_previous(
    previous_items: list[DailyStandupWorkItem],
    fresh_item: DailyStandupWorkItem,
) -> int | None:
    fresh_exact, fresh_coarse = _evidence_keys(fresh_item)
    exact_matches: list[int] = []
    coarse_matches: list[int] = []
    for index, previous_item in enumerate(previous_items):
        previous_exact, previous_coarse = _evidence_keys(previous_item)
        if fresh_exact & previous_exact:
            exact_matches.append(index)
        elif fresh_coarse & previous_coarse:
            coarse_matches.append(index)
    if exact_matches:
        return exact_matches[0] if len(exact_matches) == 1 else None
    return coarse_matches[0] if len(coarse_matches) == 1 else None


def _evidence_keys(
    work_item: DailyStandupWorkItem,
) -> tuple[set[ExactKey], set[CoarseKey]]:
    exact: set[ExactKey] = set()
    coarse: set[CoarseKey] = set()
    for section in _sections(work_item):
        for ref in section.evidence_refs:
            if ref.harness is None:
                continue
            source = (ref.harness, ref.session_id)
            coarse.add(source)
            exact.update((*source, activity_id) for activity_id in ref.activity_ids)
    return exact, coarse


def _sections(work_item: DailyStandupWorkItem) -> Iterable[DailySectionItem]:
    for attribute in _SECTION_ATTRIBUTES:
        section = getattr(work_item, attribute)
        if section is not None:
            yield section


def _merge_work_item(
    previous: DailyStandupWorkItem,
    fresh: DailyStandupWorkItem,
    *,
    next_ranks: dict[str, int],
) -> DailyStandupWorkItem:
    previous_exact, _ = _evidence_keys(previous)
    sections: dict[str, DailySectionItem | None] = {}
    for attribute in _SECTION_ATTRIBUTES:
        previous_section = getattr(previous, attribute)
        fresh_section = getattr(fresh, attribute)
        if previous_section is None and fresh_section is not None:
            added = fresh_section.model_copy(deep=True)
            added.rank = _take_rank(next_ranks, attribute)
            added.new_activity = added.new_activity or bool(
                _section_exact_keys(added) - previous_exact
            )
            sections[attribute] = added
        elif previous_section is not None and fresh_section is None:
            sections[attribute] = previous_section.model_copy(deep=True)
        elif previous_section is not None and fresh_section is not None:
            sections[attribute] = _merge_section(
                previous_section,
                fresh_section,
                previous_work_exact=previous_exact,
            )
        else:
            sections[attribute] = None

    return DailyStandupWorkItem(
        id=previous.id,
        source_outcome_ids=_stable_unique(
            [*previous.source_outcome_ids, *fresh.source_outcome_ids]
        ),
        repository_ids=_stable_unique(
            [*previous.repository_ids, *fresh.repository_ids]
        ),
        **sections,
    )


def _merge_section(
    previous: DailySectionItem,
    fresh: DailySectionItem,
    *,
    previous_work_exact: set[ExactKey],
) -> DailySectionItem:
    reviewer_owned = (
        previous.user_edited
        or previous.source is DailyStatementSource.USER_ADDED
    )
    return DailySectionItem(
        statement=previous.statement if reviewer_owned else fresh.statement,
        evidence_refs=_merge_refs(previous.evidence_refs, fresh.evidence_refs),
        included=previous.included,
        rank=previous.rank,
        bucket=previous.bucket,
        user_edited=previous.user_edited if reviewer_owned else fresh.user_edited,
        source=previous.source if reviewer_owned else fresh.source,
        new_activity=(
            previous.new_activity
            or fresh.new_activity
            or bool(_section_exact_keys(fresh) - previous_work_exact)
        ),
    )


def _new_work_item(
    fresh: DailyStandupWorkItem,
    *,
    next_ranks: dict[str, int],
) -> DailyStandupWorkItem:
    new_item = fresh.model_copy(update={"id": uuid4().hex}, deep=True)
    for attribute in _SECTION_ATTRIBUTES:
        section = getattr(new_item, attribute)
        if section is None:
            continue
        section.rank = _take_rank(next_ranks, attribute)
        section.new_activity = True
    return new_item


def _merge_refs(
    previous: list[EvidenceRef],
    fresh: list[EvidenceRef],
) -> list[EvidenceRef]:
    merged: list[EvidenceRef] = []
    positions: dict[RefKey, int] = {}
    for ref in [*previous, *fresh]:
        key = (ref.harness, ref.session_id, ref.repository_id, ref.commit, ref.file)
        position = positions.get(key)
        if position is None:
            positions[key] = len(merged)
            merged.append(ref.model_copy(deep=True))
            continue
        existing = merged[position]
        existing.activity_ids = _stable_unique(
            [*existing.activity_ids, *ref.activity_ids]
        )
    return merged


def _section_exact_keys(section: DailySectionItem) -> set[ExactKey]:
    keys: set[ExactKey] = set()
    for ref in section.evidence_refs:
        if ref.harness is None:
            continue
        keys.update(
            (ref.harness, ref.session_id, activity_id)
            for activity_id in ref.activity_ids
        )
    return keys


def _next_rank(items: list[DailyStandupWorkItem], attribute: str) -> int:
    ranks = [
        section.rank
        for item in items
        if (section := getattr(item, attribute)) is not None
    ]
    return max(ranks, default=-1) + 1


def _take_rank(next_ranks: dict[str, int], attribute: str) -> int:
    rank = next_ranks[attribute]
    next_ranks[attribute] += 1
    return rank


def _stable_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
