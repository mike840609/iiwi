"""A best-effort store of already-normalized sessions, keyed by source freshness.

Exporting a session is by far the most expensive thing a scan does, and almost
none of it is new work: a week's sessions stop changing the moment they end, so
the same `opencode export` runs again on every report for sessions that have not
moved in days. This keeps the normalized `AgentSession` rather than the raw
export, so a hit skips the mapper as well as the subprocess.

The cache is an optimization and never a dependency. Every failure path here
degrades to "load it from the harness like before" and reports one warning, so a
missing directory, an unreadable file, a locked database, or a payload written by
an older iiwi can slow a report down but can never fail one or change what it
says.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_cache_dir
from pydantic import ValidationError

from iiwi import __version__
from iiwi.harnesses.base import HarnessSessionSource
from iiwi.metrics import PerformanceMetrics
from iiwi.models.session import AgentSession, SessionDescriptor
from iiwi.models.time_range import DateRange

CACHE_FILE_VARIABLE = "IIWI_CACHE_FILE"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_cache (
    harness TEXT NOT NULL,
    session_id TEXT NOT NULL,
    source_updated_at TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    payload BLOB NOT NULL,
    cached_at TEXT NOT NULL,
    PRIMARY KEY (harness, session_id, adapter_version)
)
"""


def cache_file_path() -> Path:
    """Return the cache database, honoring an explicit override for tests."""

    override = os.environ.get(CACHE_FILE_VARIABLE)
    if override:
        return Path(override).expanduser()
    return Path(user_cache_dir("iiwi")) / "sessions.db"


def adapter_version(*, sanitized: bool) -> str:
    """The identity of the code and options that produced a cached payload.

    The iiwi version stands in for "the mappers as of this release". A hand-kept
    constant would be cheaper to bump but is forgotten in exactly the release
    that changes a mapper, and a cache that quietly serves sessions the current
    mapper would build differently is worse than no cache at all: the report
    loses content and says nothing about why. The cost of tying it to the
    release is one cold scan per upgrade. (Editing a mapper *within* a version
    is the one case this cannot see; delete the cache file while doing that.)

    `sanitized` belongs to that identity too. OpenCode's `--sanitize` changes
    what the export contains, so a raw payload must never be handed to a run
    that asked for a redacted one.
    """

    return f"{__version__}|{'sanitized' if sanitized else 'raw'}"


@dataclass(frozen=True)
class CacheLookup:
    """What a lookup found: the session, and whether a superseded row existed."""

    session: AgentSession | None = None
    stale: bool = False


class SessionCache:
    """Store normalized sessions in SQLite, keyed by harness, id, and version.

    Opens a connection per operation rather than holding one. Sessions load
    concurrently, SQLite connections are not shareable across threads, and a
    connection costs tens of microseconds against the ~1s subprocess it exists
    to avoid — so the simplest thread-safe option is also fast enough to be
    invisible.
    """

    def __init__(
        self,
        *,
        path: Path,
        adapter_version: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._path = path
        self._adapter_version = adapter_version
        self._timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._problem: str | None = None
        self._usable = self._prepare()

    def _note_problem(self, reason: str) -> None:
        """Remember the first failure only.

        One unreadable cache produces one warning, not one per session: a
        report topped by two hundred identical lines has buried the session
        warnings that actually needed reading.

        It also stops trying. A cache that failed once — locked, corrupt, or
        unreadable — is not going to succeed for the next session, and each
        retry pays the full connect timeout again. Marking the cache unusable
        here is what turns "one warning" into "one warning *and one delay*",
        which is the degradation the module docstring promises.
        """

        with self._lock:
            if self._problem is None:
                self._problem = reason
            self._usable = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=self._timeout_seconds)
        try:
            yield connection
        finally:
            connection.close()

    def _prepare(self) -> bool:
        """Create the database and drop payloads written by another release."""

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if os.name == "posix":
                self._path.parent.chmod(0o700)
            with self._connect() as connection:
                connection.execute(_SCHEMA)
                # Rows from other releases can never be served again, so they
                # are pure growth. Matching on the version prefix rather than
                # the whole string keeps both sanitize variants of the current
                # release, which a user who toggles `--sanitize` still needs.
                connection.execute(
                    "DELETE FROM session_cache WHERE adapter_version NOT LIKE ?",
                    (f"{__version__}|%",),
                )
                connection.commit()
            if os.name == "posix":
                # Sessions are the user's unredacted conversations; the file is
                # readable only by them, like every other thing iiwi writes.
                self._path.chmod(0o600)
        except (sqlite3.Error, OSError) as exc:
            self._note_problem(f"session cache unavailable ({exc}); exporting every session")
            return False
        return True

    def get(self, descriptor: SessionDescriptor) -> CacheLookup:
        """Return the cached session for this descriptor, if it is still current."""

        fingerprint = _fingerprint(descriptor)
        if not self._usable or fingerprint is None:
            return CacheLookup()
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT source_updated_at, payload FROM session_cache "
                    "WHERE harness = ? AND session_id = ? AND adapter_version = ?",
                    (descriptor.harness, descriptor.session_id, self._adapter_version),
                ).fetchone()
        except sqlite3.Error as exc:
            self._note_problem(f"session cache unreadable ({exc}); exporting every session")
            return CacheLookup()
        if row is None:
            return CacheLookup()
        stored_fingerprint, payload = row
        if stored_fingerprint != fingerprint:
            return CacheLookup(stale=True)
        session = _decode(payload)
        if session is None:
            # A payload this version cannot read is indistinguishable from one
            # that was never there; the reload below will overwrite it.
            return CacheLookup(stale=True)
        return CacheLookup(session=session)

    def put(self, descriptor: SessionDescriptor, session: AgentSession) -> None:
        """Store one freshly loaded session, or quietly decline to."""

        fingerprint = _fingerprint(descriptor)
        if not self._usable or fingerprint is None:
            return
        payload = _encode(session)
        if payload is None:
            return
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO session_cache "
                    "(harness, session_id, source_updated_at, adapter_version, "
                    "payload, cached_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        descriptor.harness,
                        descriptor.session_id,
                        fingerprint,
                        self._adapter_version,
                        payload,
                        datetime.now(tz=UTC).isoformat(),
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            self._note_problem(
                f"session cache not writable ({exc}); "
                "it will not speed up the next run"
            )

    def drain_warnings(self) -> list[str]:
        with self._lock:
            problem, self._problem = self._problem, None
        return [problem] if problem is not None else []


class CachingSessionSource(HarnessSessionSource):
    """Serve sessions from the cache, falling through to the harness on a miss.

    A wrapper rather than a branch inside `ScanService`: scanning is about
    filtering and grouping whatever a source hands back, and it stays free of
    the question of where that came from. It also means the cache is exercised
    by the same concurrency the real sources are.
    """

    def __init__(
        self,
        *,
        source: HarnessSessionSource,
        cache: SessionCache,
        metrics: PerformanceMetrics | None = None,
    ) -> None:
        self._source = source
        self._cache = cache
        self._metrics = metrics if metrics is not None else PerformanceMetrics()
        self._lock = threading.Lock()
        self._counts = {"cache_hits": 0, "cache_misses": 0, "cache_stale": 0}

    def _record(self, name: str) -> None:
        # Loads run on several threads, so the increment and the publish both
        # happen under this lock; the main thread only reads the totals once
        # every loader has finished.
        with self._lock:
            self._counts[name] += 1
            self._metrics.count(name, self._counts[name])

    def discover(self, period: DateRange) -> list[SessionDescriptor]:
        return self._source.discover(period)

    def load(self, descriptor: SessionDescriptor) -> AgentSession:
        lookup = self._cache.get(descriptor)
        if lookup.session is not None:
            self._record("cache_hits")
            return lookup.session
        self._record("cache_stale" if lookup.stale else "cache_misses")
        session = self._source.load(descriptor)
        self._cache.put(descriptor, session)
        return session

    def drain_warnings(self) -> list[str]:
        return self._cache.drain_warnings()


def _fingerprint(descriptor: SessionDescriptor) -> str | None:
    """The value that decides whether a stored payload is still current.

    A descriptor with no `updated_at` is never cached rather than cached
    forever: without it there is no way to notice the session has changed, and
    a report built from a session that has since grown is a wrong report.
    """

    if descriptor.updated_at is None:
        return None
    return descriptor.updated_at.isoformat()


def _encode(session: AgentSession) -> bytes | None:
    """Compress the normalized session, or decline if it will not serialize.

    Transcripts are repetitive text, so compression is most of the difference
    between a cache measured in hundreds of megabytes and one measured in tens.
    `SessionActivity.metadata` accepts arbitrary objects, so serialization is
    allowed to fail here; that session simply misses next time.
    """

    try:
        return zlib.compress(session.model_dump_json().encode("utf-8"))
    except (TypeError, ValueError, zlib.error):
        return None


def _decode(payload: object) -> AgentSession | None:
    if not isinstance(payload, bytes):
        return None
    try:
        return AgentSession.model_validate_json(zlib.decompress(payload))
    except (zlib.error, ValidationError, ValueError):
        return None
