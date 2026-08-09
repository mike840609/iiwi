"""Exact half-open activity filtering."""

from copy import deepcopy

from iiwi.models.session import AgentSession
from iiwi.models.time_range import DateRange


def _session_timestamp_in_period(session: AgentSession, period: DateRange) -> bool:
    timestamp = session.updated_at or session.created_at
    return timestamp is not None and period.since <= timestamp < period.until


def filter_session_to_period(
    session: AgentSession,
    period: DateRange,
) -> AgentSession | None:
    """Return a copy containing only session data inside the period.

    An OpenCode metadata-only session is retained when its own timestamp is in
    range. This allows intentionally sanitized exports to contribute repository
    grouping and session metadata without inventing activities. Other harnesses,
    and sessions that originally had activities, still require at least one
    timestamped activity inside the period.
    """

    if not session.activities:
        if session.harness != "opencode":
            return None
        return deepcopy(session) if _session_timestamp_in_period(session, period) else None

    activities = [
        activity
        for activity in session.activities
        if activity.timestamp is not None
        and period.since <= activity.timestamp < period.until
    ]
    if not activities:
        return None
    filtered = deepcopy(session)
    filtered.activities = activities
    return filtered
