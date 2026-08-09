"""Timezone-aware report period semantics."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, model_validator


class DateRange(BaseModel):
    """A half-open, timezone-aware interval: since <= timestamp < until."""

    since: datetime
    until: datetime

    @model_validator(mode="after")
    def validate_order(self) -> DateRange:
        if self.since.tzinfo is None or self.until.tzinfo is None:
            raise ValueError("date range values must be timezone-aware")
        if self.since >= self.until:
            raise ValueError("since must be earlier than until")
        return self

    @classmethod
    def from_days(cls, *, days: int, now: datetime) -> DateRange:
        if days < 1:
            raise ValueError("days must be at least 1")
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return cls(since=now - timedelta(days=days), until=now)

    @classmethod
    def previous_week(cls, *, now: datetime) -> DateRange:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        current_monday = (now - timedelta(days=now.weekday())).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return cls(
            since=current_monday - timedelta(days=7),
            until=current_monday,
        )

    @classmethod
    def current_week(cls, *, now: datetime) -> DateRange:
        """Monday 00:00 of the week in progress, up to now."""

        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        monday = (now - timedelta(days=now.weekday())).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return cls(since=monday, until=now)
