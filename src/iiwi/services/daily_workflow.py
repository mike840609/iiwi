"""Coordinate one Daily Standup refresh below the interactive controller."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import datetime

from iiwi.daily_state import cleanup_daily_state, load_daily_draft
from iiwi.errors import OutcomeSynthesisError
from iiwi.models.daily import DailyStandupDraft
from iiwi.services.daily_projection import build_daily_fallback, project_daily_standup
from iiwi.services.daily_reconcile import reconcile_daily_draft
from iiwi.services.daily_scan import DailyScanCoordinator, DailyWindow
from iiwi.services.daily_scan import daily_window as build_daily_window
from iiwi.services.outcomes import OutcomeSynthesisService


class DailyWorkflowService:
    """Build and reconcile one date-bound Daily Standup draft."""

    def __init__(
        self,
        *,
        scan_coordinator_factory: Callable[[DailyWindow], DailyScanCoordinator],
        outcome_service: OutcomeSynthesisService,
        now_factory: Callable[[], datetime],
    ) -> None:
        self._scan_coordinator_factory = scan_coordinator_factory
        self._outcome_service = outcome_service
        self._now_factory = now_factory

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
                synthesis = self._outcome_service.synthesize(daily_scan.scan)
            except OutcomeSynthesisError:
                fresh = build_daily_fallback(daily_scan=daily_scan)
            else:
                fresh = project_daily_standup(
                    daily_scan=daily_scan,
                    outcomes=synthesis.outcomes,
                    synthesis_warnings=synthesis.warnings,
                )

        if state_warning is not None:
            fresh.warnings.append(state_warning)
        return reconcile_daily_draft(previous, fresh)
