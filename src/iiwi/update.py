"""Opt-in version check against PyPI.

This is the only Agent Worklog operation that touches the network, and it is
never run implicitly: the `update` command is its sole entry point, so the
"nothing leaves your machine" promise holds unless the user explicitly asks
for a version check.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from iiwi import __version__ as _current_version
from iiwi.errors import IiwiError

LATEST_URL = "https://pypi.org/pypi/agent-worklog/json"
_NETWORK_TIMEOUT_SECONDS = 10.0
UPGRADE_COMMAND = "pipx upgrade agent-worklog"


class UpdateCheckError(IiwiError):
    """Raised when the version check could not be completed."""


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str
    update_available: bool
    upgrade_command: str


def current_version() -> str:
    """The version this installation reports."""

    return _current_version


def _version_tuple(value: str) -> tuple[int, ...]:
    """A comparable view of a version, covering the forms this project uses.

    `1.2.3` beats `1.2.3rc1`: a release is newer than its own pre-release,
    which a naive digit extraction would get backwards. Suffix ranks put `rc`
    above `b` above `a`; the release sentinel sits above every rank, so a
    release is strictly greater than every pre-release of the same numbers.
    """

    match = re.fullmatch(r"(\d+(?:\.\d+)*)(?:[-.]([ab]|rc)(\d+))?", value.strip())
    if match is None:
        # Digit extraction is approximate for unusual PEP 440 forms — it would
        # order `0.9.0.post1` and `0.9.0rc1` wrongly — but it is only reached
        # for versions outside the forms this project publishes.
        return tuple(int(part) for part in re.findall(r"\d+", value)) or (0,)
    numbers = tuple(int(part) for part in match.group(1).split("."))
    suffix = match.group(2)
    if suffix is None:
        return (*numbers, 10)
    rank = {"a": 1, "b": 2, "rc": 3}[suffix]
    return (*numbers, rank, int(match.group(3) or "0"))


def _fetch_raw(*, url: str, timeout: float) -> str:
    """Fetch the version-index document; network failures surface as OSError."""

    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"agent-worklog/{current_version()} (version check)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def _parse_latest(raw: str) -> str:
    """Extract the latest version from the index document."""

    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise UpdateCheckError("the version index returned an unreadable document") from exc
    info = payload.get("info") if isinstance(payload, dict) else None
    latest = info.get("version") if isinstance(info, dict) else None
    if not isinstance(latest, str) or not latest:
        raise UpdateCheckError("the version index returned no version")
    return latest


def check_for_update(
    *,
    fetcher: Callable[[str], str] | None = None,
    current: str | None = None,
    url: str = LATEST_URL,
    timeout: float = _NETWORK_TIMEOUT_SECONDS,
) -> UpdateInfo:
    """Compare the installed version against the latest published one.

    `fetcher` is the test seam: a callable receiving the URL and returning the
    raw JSON body, replacing the network fetch.
    """

    installed = current if current is not None else current_version()
    if fetcher is None:
        try:
            raw = _fetch_raw(url=url, timeout=timeout)
        except OSError as exc:
            raise UpdateCheckError(f"could not reach the version index: {exc}") from exc
    else:
        try:
            raw = fetcher(url)
        except (OSError, ValueError) as exc:
            raise UpdateCheckError(f"could not reach the version index: {exc}") from exc
    latest = _parse_latest(raw)
    return UpdateInfo(
        current=installed,
        latest=latest,
        update_available=_version_tuple(latest) > _version_tuple(installed),
        upgrade_command=UPGRADE_COMMAND,
    )


def update_to_json(info: UpdateInfo) -> str:
    """Render the check result as JSON for scripting consumers."""

    return json.dumps(
        {
            "current": info.current,
            "latest": info.latest,
            "update_available": info.update_available,
            "upgrade_command": info.upgrade_command,
        },
        indent=2,
        ensure_ascii=False,
    )


def update_error_to_json(message: str) -> str:
    """Render a failed check as JSON, keeping the error machine-readable."""

    return json.dumps({"error": message}, indent=2, ensure_ascii=False)
