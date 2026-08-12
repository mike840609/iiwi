"""Ephemeral repository and session selection for interactive reports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from iiwi.interactive.density import message_volume, scan_volume
from iiwi.models.session import AgentSession
from iiwi.services.scan import ScanResult
from iiwi.sessions.hierarchy import group_resolved_sessions

_MIN_SUBSTANTIVE_ACTIVITIES = 3


class SelectionMark(StrEnum):
    ALL = "all"
    NONE = "none"
    PARTIAL = "partial"


def noise_reason(session: AgentSession) -> str | None:
    """Return a short label if a session is unlikely to belong in a report."""

    if not (session.title or "").strip():
        return "No title"
    if len(session.activities) < _MIN_SUBSTANTIVE_ACTIVITIES:
        return "Low activity"
    return None


def without_repository(scan: ScanResult, repository_id: str) -> ScanResult:
    """Return a scan with one repository's sessions removed, metadata intact.

    The in-memory exclusion keeps the current view honest without re-reading
    the disk; the persisted configuration still applies to future scans.
    """

    try:
        removed = scan.sessions_by_repository[repository_id]
    except KeyError:
        raise KeyError(repository_id) from None
    removed_ids = {item.session.session_id for item in removed}
    return ScanResult(
        period=scan.period,
        candidate_session_count=scan.candidate_session_count,
        loaded_session_count=scan.loaded_session_count - len(removed_ids),
        failed_session_count=scan.failed_session_count,
        resolved_sessions=[
            item
            for item in scan.resolved_sessions
            if item.session.session_id not in removed_ids
        ],
        sessions_by_repository={
            key: value
            for key, value in scan.sessions_by_repository.items()
            if key != repository_id
        },
        warnings=list(scan.warnings),
        excluded_session_count=scan.excluded_session_count,
    )


@dataclass
class SelectionState:
    scan: ScanResult
    selected_session_ids: set[str]

    @classmethod
    def from_scan(
        cls,
        scan: ScanResult,
        selected_session_ids: set[str] | None = None,
    ) -> SelectionState:
        all_ids = {item.session.session_id for item in scan.resolved_sessions}
        selected = all_ids if selected_session_ids is None else set(selected_session_ids)
        unknown = selected - all_ids
        if unknown:
            raise KeyError(next(iter(unknown)))
        return cls(scan=scan, selected_session_ids=selected)

    @property
    def selected_count(self) -> int:
        return len(self.selected_session_ids)

    @property
    def total_count(self) -> int:
        return len(self.scan.resolved_sessions)

    @property
    def selected_volume(self) -> int:
        """Messages carried by the selection.

        Row counts cannot answer whether a selection covers the week's work: one
        session of 300 messages and seventeen of 3 read identically as counts.
        """
        return sum(
            message_volume(item.session)
            for item in self.scan.resolved_sessions
            if item.session.session_id in self.selected_session_ids
        )

    @property
    def total_volume(self) -> int:
        return scan_volume(self.scan)

    def _all_session_ids(self) -> set[str]:
        return {item.session.session_id for item in self.scan.resolved_sessions}

    def _repository_session_ids(self, repository_id: str) -> set[str]:
        try:
            sessions = self.scan.sessions_by_repository[repository_id]
        except KeyError:
            raise KeyError(repository_id) from None
        return {item.session.session_id for item in sessions}

    def repository_mark(self, repository_id: str) -> SelectionMark:
        ids = self._repository_session_ids(repository_id)
        selected = ids & self.selected_session_ids
        if not selected:
            return SelectionMark.NONE
        if selected == ids:
            return SelectionMark.ALL
        return SelectionMark.PARTIAL

    def toggle_session(self, session_id: str) -> None:
        if session_id not in self._all_session_ids():
            raise KeyError(session_id)
        if session_id in self.selected_session_ids:
            self.selected_session_ids.remove(session_id)
        else:
            self.selected_session_ids.add(session_id)

    def toggle_repository(self, repository_id: str) -> None:
        ids = self._repository_session_ids(repository_id)
        if ids <= self.selected_session_ids:
            self.selected_session_ids.difference_update(ids)
        else:
            self.selected_session_ids.update(ids)

    def exclude_repository(self, repository_id: str) -> None:
        removed = {
            item.session.session_id
            for item in self.scan.sessions_by_repository[repository_id]
        }
        self.scan = without_repository(self.scan, repository_id)
        self.selected_session_ids.difference_update(removed)

    def select_all(self) -> None:
        self.selected_session_ids.clear()
        self.selected_session_ids.update(self._all_session_ids())

    def select_none(self) -> None:
        self.selected_session_ids.clear()

    def filtered_scan(self) -> ScanResult:
        selected = [
            item
            for item in self.scan.resolved_sessions
            if item.session.session_id in self.selected_session_ids
        ]
        return ScanResult(
            period=self.scan.period,
            candidate_session_count=self.scan.candidate_session_count,
            loaded_session_count=len(selected),
            failed_session_count=self.scan.failed_session_count,
            resolved_sessions=selected,
            sessions_by_repository=group_resolved_sessions(selected),
            warnings=list(self.scan.warnings),
            excluded_session_count=self.scan.excluded_session_count,
        )
