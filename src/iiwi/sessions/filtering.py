"""Exact half-open activity filtering."""

import re
from copy import deepcopy

from iiwi.models.session import AgentSession
from iiwi.models.time_range import DateRange

IIWI_SESSION_TITLE_PREFIX = "iiwi-internal: "
# Titles iiwi wrote before the prefix existed. Matched exactly, never by
# prefix, so a human session named "Iiwi main menu rework" still counts as
# work. "Iiwi narrative summary" is not a string iiwi's code emits — it came
# from iiwi's own runner during diagnostics with a non-default title — but the
# sessions it matches are iiwi machinery, which is what this predicate is for.
_LEGACY_IIWI_TITLES = frozenset(
    {"Iiwi outcome synthesis", "Iiwi narrative summary"}
)
_LEGACY_IIWI_NARRATIVE = re.compile(
    r"^Iiwi - \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}$"
)


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


def is_iiwi_authored(session: AgentSession) -> bool:
    """Return whether iiwi's own `opencode run` created this session."""

    title = (session.title or "").strip()
    if not title:
        return False
    return (
        title.startswith(IIWI_SESSION_TITLE_PREFIX)
        or title in _LEGACY_IIWI_TITLES
        or _LEGACY_IIWI_NARRATIVE.match(title) is not None
    )
