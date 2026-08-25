"""Coordinate one Daily Standup refresh below the interactive controller."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import datetime

from iiwi.daily_state import cleanup_daily_state, load_daily_draft
from iiwi.errors import OutcomeSynthesisError
from iiwi.models.daily import DailyStandupDraft, DailyStatementSource
from iiwi.models.outcome import OutcomeSynthesisResult
from iiwi.progress import NullProgressReporter, ProgressReporter, ProgressStage
from iiwi.services.daily_projection import (
    build_daily_fallback,
    daily_extraction_warning,
    project_daily_standup,
)
from iiwi.services.daily_reconcile import reconcile_daily_draft
from iiwi.services.daily_scan import DailyScanCoordinator, DailyWindow
from iiwi.services.daily_scan import daily_window as build_daily_window
from iiwi.services.outcomes import OutcomeSynthesisService
from iiwi.services.scan import ScanResult


class DailyWorkflowService:
    """Build and reconcile one date-bound Daily Standup draft."""

    def __init__(
        self,
        *,
        scan_coordinator_factory: Callable[[DailyWindow], DailyScanCoordinator],
        outcome_service: OutcomeSynthesisService,
        now_factory: Callable[[], datetime],
        progress: ProgressReporter | None = None,
    ) -> None:
        self._scan_coordinator_factory = scan_coordinator_factory
        self._outcome_service = outcome_service
        self._now_factory = now_factory
        self._progress = progress or NullProgressReporter()

    def refresh(
        self,
        previous: DailyStandupDraft | None = None,
    ) -> DailyStandupDraft:
        window = build_daily_window(self._now_factory())
        with contextlib.suppress(OSError):
            cleanup_daily_state(window.standup_date)

        state_warning: str | None = None
        if previous is None or previous.standup_date != window.standup_date:
            loaded = load_daily_draft(window.standup_date)
            previous = loaded.draft
            state_warning = loaded.warning

        daily_scan = self._scan_coordinator_factory(window).scan()
        has_activity = any(
            resolved.session.activities
            for resolved in daily_scan.scan.resolved_sessions
        )
        if not has_activity:
            fresh = project_daily_standup(daily_scan=daily_scan, outcomes=[])
        else:
            try:
                synthesis = self._synthesize(daily_scan.scan)
            except OutcomeSynthesisError as exc:
                fresh = build_daily_fallback(daily_scan=daily_scan)
                # A coverage warning, not an ordinary one: this is the only list
                # the Markdown artifact prints, so the reader of a fallback draft
                # learns from the report itself that no model grouped this work.
                fresh.coverage_warnings.append(
                    f"Outcome synthesis failed ({exc}); this draft is raw local "
                    "evidence, not model-grouped work."
                )
            else:
                synthesis_warnings = list(synthesis.warnings)
                extraction_warning = daily_extraction_warning(
                    len(synthesis.failed_session_ids)
                )
                if extraction_warning is not None:
                    synthesis_warnings.append(extraction_warning)
                fresh = project_daily_standup(
                    daily_scan=daily_scan,
                    outcomes=synthesis.outcomes,
                    synthesis_warnings=synthesis_warnings,
                )

        if state_warning is not None:
            fresh.warnings.append(state_warning)
        if _supersedes_fallback(previous, fresh):
            previous = None
        return reconcile_daily_draft(previous, fresh)

    def _synthesize(self, scan: ScanResult) -> OutcomeSynthesisResult:
        """Synthesize outcomes, retrying once before the fallback takes over.

        The observed failures are transient — a model turn that returns no valid
        outcome JSON — so one retry recovers the day rather than publishing raw
        evidence text until tomorrow.

        An over-budget window is forced through rather than refused: the Daily
        window is fixed by its date, so there is no narrower selection to offer.
        Synthesis groups the newest sessions that fit and names what it left out
        in its warnings, which the draft carries to the reader.
        """

        self._progress.start(ProgressStage.SYNTHESIZING_OUTCOMES)
        try:
            return self._outcome_service.synthesize(scan, force=True)
        except OutcomeSynthesisError:
            return self._outcome_service.synthesize(scan, force=True)
        finally:
            self._progress.finish()


def _supersedes_fallback(
    previous: DailyStandupDraft | None,
    fresh: DailyStandupDraft,
) -> bool:
    """Report whether a model-grouped draft replaces an unreviewed fallback outright.

    Fallback items are one per session and model-grouped items one per outcome,
    so a single fresh item routinely covers several previous ones. Reconciling
    reads that as ambiguous: every raw fallback statement stays, and the grouped
    item arrives excluded — a successful refresh publishing worse text than the
    failure it replaced. Nothing in an untouched fallback draft is the
    reviewer's, so it is dropped. A fallback draft the reviewer has edited keeps
    the merge, because their wording outranks the duplication.
    """

    if previous is None or not previous.fallback or fresh.fallback:
        return False
    return not any(
        section.user_edited or section.source is DailyStatementSource.USER_ADDED
        for item in previous.work_items
        for section in (item.yesterday, item.today, item.blocker)
        if section is not None
    )
