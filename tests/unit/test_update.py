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


def test_post_release_is_newer_than_its_final_release() -> None:
    info = check_for_update(fetcher=_fetcher({"info": {"version": "1.0.0.post1"}}), current="1.0.0")

    assert info.update_available is True

    up_to_date = check_for_update(
        fetcher=_fetcher({"info": {"version": "1.0.0"}}), current="1.0.0.post1"
    )
    assert up_to_date.update_available is False


def test_final_release_is_newer_than_its_dev_release() -> None:
    info = check_for_update(fetcher=_fetcher({"info": {"version": "1.1.0"}}), current="1.1.0.dev1")

    assert info.update_available is True

    up_to_date = check_for_update(
        fetcher=_fetcher({"info": {"version": "1.1.0.dev1"}}), current="1.1.0"
    )
    assert up_to_date.update_available is False


def test_epoch_dominates_all_release_versions() -> None:
    info = check_for_update(fetcher=_fetcher({"info": {"version": "1!1.0.0"}}), current="2.0.0")

    assert info.update_available is True


def test_local_segment_is_ignored_when_only_one_side_has_it() -> None:
    info = check_for_update(
        fetcher=_fetcher({"info": {"version": "1.0.0"}}), current="1.0.0+local.1"
    )

    assert info.update_available is False


def test_prerelease_ordering_follows_the_pep440_ladder() -> None:
    alpha_to_beta = check_for_update(
        fetcher=_fetcher({"info": {"version": "1.0.0b1"}}), current="1.0.0a1"
    )
    assert alpha_to_beta.update_available is True

    rc_to_final = check_for_update(
        fetcher=_fetcher({"info": {"version": "1.0.0"}}), current="1.0.0rc1"
    )
    assert rc_to_final.update_available is True

    equal = check_for_update(fetcher=_fetcher({"info": {"version": "1.0.0"}}), current="1.0.0")
    assert equal.update_available is False


@pytest.mark.parametrize("invalid", ["not-a-version", "1.0.0..1"])
def test_invalid_index_version_raises_update_check_error(invalid: str) -> None:
    with pytest.raises(UpdateCheckError):
        check_for_update(fetcher=_fetcher({"info": {"version": invalid}}), current="1.0.0")
