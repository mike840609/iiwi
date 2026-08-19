"""Requirement coverage for the incremental session cache."""

import os
import sqlite3
import threading
import zlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from iiwi import __version__
from iiwi.cache import (
    CachingSessionSource,
    SessionCache,
    adapter_version,
    cache_file_path,
)
from iiwi.metrics import PerformanceMetrics
from iiwi.models.session import (
    ActivityType,
    AgentSession,
    SessionActivity,
    SessionDescriptor,
)
from iiwi.models.time_range import DateRange

TZ = ZoneInfo("Asia/Taipei")


def descriptor(session_id: str, *, updated_at: datetime | None) -> SessionDescriptor:
    return SessionDescriptor(
        harness="opencode",
        session_id=session_id,
        updated_at=updated_at,
    )


def session_for(session_id: str, *, body: str = "original") -> AgentSession:
    return AgentSession(
        harness="opencode",
        session_id=session_id,
        activities=[
            SessionActivity(
                activity_id=f"{session_id}:a1",
                activity_type=ActivityType.USER_MESSAGE,
                timestamp=datetime(2026, 7, 22, tzinfo=TZ),
                content=body,
            )
        ],
    )


def cache_at(path: Path, *, sanitized: bool = False) -> SessionCache:
    return SessionCache(path=path, adapter_version=adapter_version(sanitized=sanitized))


class CountingSource:
    """A source that records every load, and whose content tracks `updated_at`.

    Content that changes with the timestamp is what turns "did it reload?" into
    "did it serve the *right* version?" — a cache that reloads but returns the
    old payload would pass the weaker check.
    """

    def __init__(self, updated: dict[str, datetime | None]) -> None:
        self.updated = dict(updated)
        self.load_calls: list[str] = []

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return [
            descriptor(session_id, updated_at=stamp)
            for session_id, stamp in self.updated.items()
        ]

    def load(self, target: SessionDescriptor) -> AgentSession:
        self.load_calls.append(target.session_id)
        stamp = self.updated[target.session_id]
        return session_for(target.session_id, body=f"body@{stamp}")


def caching(source: CountingSource, path: Path, **kwargs) -> CachingSessionSource:
    """Wrap a source around a cache at `path`; pass metrics explicitly instead."""

    return CachingSessionSource(
        source=source,  # type: ignore[arg-type]
        cache=cache_at(path, **kwargs),
    )


def load_all(wrapped: CachingSessionSource, source: CountingSource) -> list[AgentSession]:
    period = DateRange(
        since=datetime(2026, 7, 20, tzinfo=TZ),
        until=datetime(2026, 7, 27, tzinfo=TZ),
    )
    return [wrapped.load(item) for item in wrapped.discover(period)]


# --- the acceptance criteria --------------------------------------------------


def test_the_first_run_exports_everything(tmp_path: Path) -> None:
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = CountingSource({"s1": stamp, "s2": stamp, "s3": stamp})

    load_all(caching(source, tmp_path / "c.db"), source)

    assert source.load_calls == ["s1", "s2", "s3"]


def test_a_second_run_over_unchanged_sessions_exports_nothing(tmp_path: Path) -> None:
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = CountingSource({"s1": stamp, "s2": stamp, "s3": stamp})
    load_all(caching(source, tmp_path / "c.db"), source)
    source.load_calls.clear()

    load_all(caching(source, tmp_path / "c.db"), source)

    assert source.load_calls == []


def test_only_the_changed_session_is_exported_again(tmp_path: Path) -> None:
    """The whole point: yesterday's fifty sessions should not be re-read today."""

    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = CountingSource({"s1": stamp, "s2": stamp, "s3": stamp})
    load_all(caching(source, tmp_path / "c.db"), source)
    source.load_calls.clear()
    source.updated["s2"] = datetime(2026, 7, 23, tzinfo=TZ)

    sessions = load_all(caching(source, tmp_path / "c.db"), source)

    assert source.load_calls == ["s2"]
    bodies = {item.session_id: item.activities[0].content for item in sessions}
    assert bodies["s2"] == "body@2026-07-23 00:00:00+08:00"
    assert bodies["s1"] == "body@2026-07-22 00:00:00+08:00"


def test_a_cached_session_is_identical_to_a_freshly_loaded_one(tmp_path: Path) -> None:
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = CountingSource({"s1": stamp})
    fresh = load_all(caching(source, tmp_path / "c.db"), source)

    cached = load_all(caching(source, tmp_path / "c.db"), source)

    assert cached == fresh


# --- invalidation -------------------------------------------------------------


def test_an_upgraded_iiwi_ignores_payloads_from_another_release(tmp_path: Path) -> None:
    """A mapper change must not be served through by a cache from the last version."""

    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = CountingSource({"s1": stamp})
    path = tmp_path / "c.db"
    older = SessionCache(path=path, adapter_version="0.0.1|raw")
    older.put(descriptor("s1", updated_at=stamp), session_for("s1"))

    assert cache_at(path).get(descriptor("s1", updated_at=stamp)).session is None
    load_all(caching(source, path), source)
    assert source.load_calls == ["s1"]


def test_opening_the_cache_drops_rows_from_another_release(tmp_path: Path) -> None:
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    path = tmp_path / "c.db"
    SessionCache(path=path, adapter_version="0.0.1|raw").put(
        descriptor("s1", updated_at=stamp), session_for("s1")
    )

    cache_at(path)

    with sqlite3.connect(path) as connection:
        remaining = connection.execute("SELECT COUNT(*) FROM session_cache").fetchone()
    assert remaining[0] == 0


def test_both_sanitize_variants_of_one_release_survive_pruning(tmp_path: Path) -> None:
    """Toggling --sanitize must not make each run throw away the other's work."""

    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    path = tmp_path / "c.db"
    cache_at(path, sanitized=False).put(descriptor("s1", updated_at=stamp), session_for("s1"))
    cache_at(path, sanitized=True).put(descriptor("s2", updated_at=stamp), session_for("s2"))

    cache_at(path, sanitized=False)

    assert cache_at(path, sanitized=False).get(descriptor("s1", updated_at=stamp)).session
    assert cache_at(path, sanitized=True).get(descriptor("s2", updated_at=stamp)).session


def test_a_raw_payload_is_never_served_to_a_sanitized_run(tmp_path: Path) -> None:
    """`--sanitize` changes what OpenCode exports, so the two must not share rows."""

    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    path = tmp_path / "c.db"
    cache_at(path, sanitized=False).put(
        descriptor("s1", updated_at=stamp), session_for("s1", body="unredacted")
    )

    lookup = cache_at(path, sanitized=True).get(descriptor("s1", updated_at=stamp))

    assert lookup.session is None


def test_the_version_carries_both_the_release_and_the_sanitize_mode() -> None:
    assert adapter_version(sanitized=False) == f"{__version__}|raw"
    assert adapter_version(sanitized=True) == f"{__version__}|sanitized"


def test_a_session_with_no_update_time_is_never_cached(tmp_path: Path) -> None:
    """Without a freshness signal, a hit could serve a session that has since grown."""

    source = CountingSource({"s1": None})
    load_all(caching(source, tmp_path / "c.db"), source)
    source.load_calls.clear()

    load_all(caching(source, tmp_path / "c.db"), source)

    assert source.load_calls == ["s1"]


def test_a_stale_row_is_reported_as_stale_rather_than_missing(tmp_path: Path) -> None:
    path = tmp_path / "c.db"
    cache_at(path).put(
        descriptor("s1", updated_at=datetime(2026, 7, 22, tzinfo=TZ)), session_for("s1")
    )

    lookup = cache_at(path).get(
        descriptor("s1", updated_at=datetime(2026, 7, 23, tzinfo=TZ))
    )

    assert lookup.session is None
    assert lookup.stale is True


# --- failure is never fatal ---------------------------------------------------


def test_an_unreadable_cache_falls_back_to_loading_and_warns_once(tmp_path: Path) -> None:
    path = tmp_path / "c.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a database")
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = CountingSource({"s1": stamp, "s2": stamp})

    wrapped = caching(source, path)
    sessions = load_all(wrapped, source)

    assert [item.session_id for item in sessions] == ["s1", "s2"]
    assert source.load_calls == ["s1", "s2"]
    assert len(wrapped.drain_warnings()) == 1


def test_a_corrupt_payload_is_reloaded_rather_than_raised(tmp_path: Path) -> None:
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    path = tmp_path / "c.db"
    source = CountingSource({"s1": stamp})
    load_all(caching(source, path), source)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE session_cache SET payload = ?", (b"garbage",))
        connection.commit()
    source.load_calls.clear()

    sessions = load_all(caching(source, path), source)

    assert source.load_calls == ["s1"]
    assert sessions[0].session_id == "s1"


def test_a_payload_that_decompresses_to_nonsense_is_reloaded(tmp_path: Path) -> None:
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    path = tmp_path / "c.db"
    source = CountingSource({"s1": stamp})
    load_all(caching(source, path), source)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE session_cache SET payload = ?", (zlib.compress(b'{"not": "a session"}'),)
        )
        connection.commit()
    source.load_calls.clear()

    load_all(caching(source, path), source)

    assert source.load_calls == ["s1"]


def test_a_cache_that_cannot_be_created_still_lets_the_scan_run(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the cache directory should be", encoding="utf-8")
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = CountingSource({"s1": stamp})

    wrapped = caching(source, blocked / "sessions.db")
    sessions = load_all(wrapped, source)

    assert [item.session_id for item in sessions] == ["s1"]
    assert len(wrapped.drain_warnings()) == 1


def test_one_broken_cache_produces_one_warning_not_one_per_session(
    tmp_path: Path,
) -> None:
    """Two hundred identical lines would bury the warnings worth reading."""

    path = tmp_path / "c.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a database")
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = CountingSource({f"s{index}": stamp for index in range(20)})

    wrapped = caching(source, path)
    load_all(wrapped, source)

    assert len(wrapped.drain_warnings()) == 1


def test_warnings_are_drained_rather_than_repeated(tmp_path: Path) -> None:
    path = tmp_path / "c.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a database")
    source = CountingSource({"s1": datetime(2026, 7, 22, tzinfo=TZ)})
    wrapped = caching(source, path)
    load_all(wrapped, source)

    assert len(wrapped.drain_warnings()) == 1
    assert wrapped.drain_warnings() == []


# --- privacy ------------------------------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_the_cache_is_readable_only_by_its_owner(tmp_path: Path) -> None:
    """It holds the user's unredacted conversations, like every file iiwi writes."""

    path = tmp_path / "nested" / "sessions.db"

    cache_at(path)

    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_the_default_location_is_the_platform_cache_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IIWI_CACHE_FILE", raising=False)

    assert cache_file_path().name == "sessions.db"
    assert cache_file_path().parent.name == "iiwi"


def test_the_override_variable_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IIWI_CACHE_FILE", str(tmp_path / "elsewhere.db"))

    assert cache_file_path() == tmp_path / "elsewhere.db"


# --- metrics ------------------------------------------------------------------


def test_hits_misses_and_stale_rows_are_counted(tmp_path: Path) -> None:
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    path = tmp_path / "c.db"
    source = CountingSource({"s1": stamp, "s2": stamp, "s3": stamp})
    load_all(caching(source, path), source)
    source.updated["s3"] = datetime(2026, 7, 24, tzinfo=TZ)
    metrics = PerformanceMetrics()

    wrapped = CachingSessionSource(
        source=source,  # type: ignore[arg-type]
        cache=cache_at(path),
        metrics=metrics,
    )
    load_all(wrapped, source)

    assert metrics.counts["cache_hits"] == 2
    assert metrics.counts["cache_stale"] == 1
    assert "cache_misses" not in metrics.counts


def test_a_cold_run_counts_only_misses(tmp_path: Path) -> None:
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    source = CountingSource({"s1": stamp, "s2": stamp})
    metrics = PerformanceMetrics()

    wrapped = CachingSessionSource(
        source=source,  # type: ignore[arg-type]
        cache=cache_at(tmp_path / "c.db"),
        metrics=metrics,
    )
    load_all(wrapped, source)

    assert metrics.counts["cache_misses"] == 2
    assert "cache_hits" not in metrics.counts


# --- concurrency --------------------------------------------------------------


def test_the_cache_survives_being_used_from_several_threads(tmp_path: Path) -> None:
    """Sessions load on a thread pool, so every cache call is a concurrent one."""

    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    path = tmp_path / "c.db"
    source = CountingSource({f"s{index}": stamp for index in range(24)})
    metrics = PerformanceMetrics()
    wrapped = CachingSessionSource(
        source=source,  # type: ignore[arg-type]
        cache=cache_at(path),
        metrics=metrics,
    )
    targets = wrapped.discover(
        DateRange(
            since=datetime(2026, 7, 20, tzinfo=TZ),
            until=datetime(2026, 7, 27, tzinfo=TZ),
        )
    )

    errors: list[BaseException] = []

    def run(target: SessionDescriptor) -> None:
        try:
            wrapped.load(target)
        except BaseException as exc:  # noqa: BLE001 - recorded and re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(target,)) for target in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert metrics.counts["cache_misses"] == 24
    assert wrapped.drain_warnings() == []
    # Every one of them landed: the second run has nothing left to export.
    source.load_calls.clear()
    load_all(caching(source, path), source)
    assert source.load_calls == []


def test_a_cache_that_breaks_mid_run_still_finishes_the_scan(tmp_path: Path) -> None:
    """The database can go bad after it opened; the scan must not go with it."""

    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    path = tmp_path / "c.db"
    source = CountingSource({"s1": stamp, "s2": stamp})
    wrapped = caching(source, path)
    path.write_bytes(b"no longer a database")

    sessions = load_all(wrapped, source)

    assert [item.session_id for item in sessions] == ["s1", "s2"]
    assert source.load_calls == ["s1", "s2"]
    assert len(wrapped.drain_warnings()) == 1


def test_a_session_that_will_not_serialize_is_skipped_not_raised(
    tmp_path: Path,
) -> None:
    """`SessionActivity.metadata` takes arbitrary objects, so this can happen."""

    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    path = tmp_path / "c.db"
    unserializable = session_for("s1")
    unserializable.activities[0].metadata = {"handle": object()}

    cache_at(path).put(descriptor("s1", updated_at=stamp), unserializable)

    assert cache_at(path).get(descriptor("s1", updated_at=stamp)).session is None


def test_a_payload_stored_as_text_is_treated_as_absent(tmp_path: Path) -> None:
    stamp = datetime(2026, 7, 22, tzinfo=TZ)
    path = tmp_path / "c.db"
    cache_at(path).put(descriptor("s1", updated_at=stamp), session_for("s1"))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE session_cache SET payload = 'plain text'")
        connection.commit()

    lookup = cache_at(path).get(descriptor("s1", updated_at=stamp))

    assert lookup.session is None
    assert lookup.stale is True
