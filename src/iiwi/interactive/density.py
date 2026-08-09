"""Information density for the interactive session lists and their headers."""

from datetime import datetime, tzinfo

from iiwi.models.session import ActivityType, AgentSession
from iiwi.services.scan import ScanResult

_MESSAGE_TYPES = frozenset({ActivityType.USER_MESSAGE, ActivityType.ASSISTANT_MESSAGE})


def message_volume(session: AgentSession) -> int:
    """Count user- and assistant-message activities in a session."""
    return sum(activity.activity_type in _MESSAGE_TYPES for activity in session.activities)


def last_activity_at(session: AgentSession) -> datetime | None:
    """Return the latest activity timestamp, or updated_at/created_at when the
    session has no activities at all."""
    timestamps = [
        activity.timestamp for activity in session.activities if activity.timestamp is not None
    ]
    if timestamps:
        return max(timestamps)
    if session.activities:
        return None
    return session.updated_at or session.created_at


def is_subagent(session: AgentSession) -> bool:
    """Return whether this session was spawned as a subagent."""
    return session.parent_session_id is not None


def session_meta(session: AgentSession, tz: tzinfo | None) -> str:
    """Render density for one session row, e.g. ``Aug 5 │ 12 msgs``.

    Harnesses record activity timestamps in UTC, so the day is resolved in the
    report's own timezone: a session worked at 2am local is otherwise labelled
    with the previous day, and would not match the dates in the report it feeds.
    """
    parts: list[str] = []
    timestamp = last_activity_at(session)
    if timestamp is not None:
        parts.append(_day_label(timestamp, tz))
    volume = message_volume(session)
    if volume:
        parts.append(volume_label(volume))
    return " │ ".join(parts)


def repository_meta(repository_id: str, scan: ScanResult) -> str:
    """Render density for a repository row, e.g. ``Aug 3–5 │ 240 msgs``.

    An all-undated repository returns ``""`` (no date, no summed volume): volume
    without a date is shown per-session only, while the repo row's span needs at
    least one dated session. A session with message volume always has a dated
    surviving activity after period filtering, so ``""`` is unreachable for a
    volume-bearing repository."""
    sessions = scan.sessions_by_repository[repository_id]
    tz = scan.period.since.tzinfo
    dates = [
        timestamp for item in sessions if (timestamp := last_activity_at(item.session)) is not None
    ]
    if not dates:
        return ""
    parts = [_span_label(min(dates), max(dates), tz)]
    volume = sum(message_volume(item.session) for item in sessions)
    if volume:
        parts.append(volume_label(volume))
    return " │ ".join(parts)


def scan_volume(scan: ScanResult) -> int:
    """Sum message volume across every session a scan resolved."""
    return sum(message_volume(item.session) for item in scan.resolved_sessions)


def volume_label(volume: int) -> str:
    """Render a message count with its unit, e.g. ``1 msg`` or ``240 msgs``."""
    return f"{volume} msg" if volume == 1 else f"{volume} msgs"


def _local(timestamp: datetime, tz: tzinfo | None) -> datetime:
    return timestamp if tz is None else timestamp.astimezone(tz)


def _day_label(timestamp: datetime, tz: tzinfo | None) -> str:
    local = _local(timestamp, tz)
    return f"{local:%b} {local.day}"


def _span_label(first: datetime, last: datetime, tz: tzinfo | None) -> str:
    first = _local(first, tz)
    last = _local(last, tz)
    if first.date() == last.date():
        return _day_label(first, None)
    if first.year == last.year and first.month == last.month:
        return f"{first:%b} {first.day}–{last.day}"
    return f"{_day_label(first, None)} – {_day_label(last, None)}"
