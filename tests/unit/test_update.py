"""Opt-in version check against PyPI."""

from __future__ import annotations

import json

import pytest

from iiwi.update import UpdateCheckError, check_for_update

_LATEST_JSON = {"info": {"version": "0.9.0"}}


def _fetcher(payload: object) -> object:
    return lambda url: json.dumps(payload)


def test_up_to_date_installation_reports_no_update() -> None:
    info = check_for_update(fetcher=_fetcher(_LATEST_JSON), current="0.9.0")

    assert info.current == "0.9.0"
    assert info.latest == "0.9.0"
    assert info.update_available is False


def test_behind_installation_reports_update_and_upgrade_command() -> None:
    info = check_for_update(fetcher=_fetcher(_LATEST_JSON), current="0.8.0")

    assert info.update_available is True
    assert info.upgrade_command == "pipx upgrade iiwi"


def test_newer_than_latest_means_up_to_date() -> None:
    info = check_for_update(fetcher=_fetcher({"info": {"version": "0.8.0"}}), current="0.9.0")

    assert info.update_available is False


def test_version_ordering_is_numeric_not_lexicographic() -> None:
    behind = check_for_update(fetcher=_fetcher({"info": {"version": "0.10.0"}}), current="0.9.0")

    assert behind.update_available is True


def test_a_release_is_newer_than_its_own_prerelease() -> None:
    info = check_for_update(fetcher=_fetcher({"info": {"version": "0.9.0"}}), current="0.9.0rc1")

    assert info.update_available is True
    newer = check_for_update(fetcher=_fetcher({"info": {"version": "0.9.0rc2"}}), current="0.9.0")
    assert newer.update_available is False


def test_malformed_json_raises_update_check_error() -> None:
    with pytest.raises(UpdateCheckError):
        check_for_update(fetcher=lambda url: "this is not json", current="0.8.0")


def test_missing_version_field_raises_update_check_error() -> None:
    with pytest.raises(UpdateCheckError):
        check_for_update(fetcher=_fetcher({"info": {}}), current="0.8.0")


def test_network_failure_raises_update_check_error() -> None:
    def fail(_url: str) -> str:
        raise OSError("connection refused")

    with pytest.raises(UpdateCheckError):
        check_for_update(fetcher=fail, current="0.8.0")


def test_current_version_defaults_to_the_installed_version() -> None:
    import iiwi

    info = check_for_update(fetcher=_fetcher({"info": {"version": "0.9.0"}}))

    assert info.current == iiwi.__version__
