"""Opt-in version check against PyPI.

This is the only Iiwi operation that touches the network, and it is
never run implicitly: the `update` command is its sole entry point, so the
"nothing leaves your machine" promise holds unless the user explicitly asks
for a version check.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

from iiwi import __version__ as _current_version
from iiwi.errors import IiwiError

LATEST_URL = "https://pypi.org/pypi/iiwi/json"
_NETWORK_TIMEOUT_SECONDS = 10.0
UPGRADE_COMMAND = "pipx upgrade iiwi"


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


def _parse_version(value: str) -> Version:
    """Parse a version for comparison, rejecting values outside PEP 440.

    The hand-written digit parser that preceded this misordered post-release,
    epoch, and local forms; `packaging` implements the reference ordering used
    by Python package metadata.
    """

    try:
        return Version(value)
    except InvalidVersion as exc:
        raise UpdateCheckError(f"the version index returned an invalid version: {value}") from exc


def _fetch_raw(*, url: str, timeout: float) -> str:
    """Fetch the version-index document; network failures surface as OSError."""

    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"iiwi/{current_version()} (version check)"},
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
        update_available=_parse_version(latest) > _parse_version(installed),
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
