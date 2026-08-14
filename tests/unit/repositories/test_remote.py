import pytest

from iiwi.repositories.remote import normalize_git_remote, repository_display_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("git@github.com:mike/assets-tracker.git", "github.com/mike/assets-tracker"),
        ("https://github.com/mike/assets-tracker.git", "github.com/mike/assets-tracker"),
        ("ssh://git@github.com/mike/assets-tracker.git", "github.com/mike/assets-tracker"),
        ("git://GitHub.COM/mike/Assets-Tracker.git", "github.com/mike/Assets-Tracker"),
    ],
)
def test_remote_protocols_normalize_to_same_identity(raw: str, expected: str) -> None:
    assert normalize_git_remote(raw) == expected


def test_remote_credentials_are_removed() -> None:
    assert normalize_git_remote("https://token@github.com/mike/repo.git") == "github.com/mike/repo"


@pytest.mark.parametrize(
    "local_path",
    [
        "../upstream.git",
        "./local/repo.git",
        "/abs/path/to/repo.git",
        "~/my/repo.git",
        "relative/path/to/repo.git",
        "folder/name:with-colon.git",
    ],
)
def test_scheme_less_local_paths_raise_value_error(local_path: str) -> None:
    with pytest.raises(ValueError, match="local path"):
        normalize_git_remote(local_path)


def test_non_default_ssh_ports_remain_distinct() -> None:
    assert (
        normalize_git_remote("ssh://git@example.test:2222/org/repo.git")
        == "example.test:2222/org/repo"
    )
    assert (
        normalize_git_remote("ssh://git@example.test:3333/org/repo.git")
        == "example.test:3333/org/repo"
    )


def test_default_ssh_port_is_omitted_from_identity() -> None:
    assert normalize_git_remote("ssh://git@example.test:22/org/repo.git") == "example.test/org/repo"
    assert normalize_git_remote("ssh://git@example.test/org/repo.git") == "example.test/org/repo"


def test_default_http_ports_are_omitted_from_identity() -> None:
    assert normalize_git_remote("https://example.test:443/org/repo.git") == "example.test/org/repo"
    assert normalize_git_remote("http://example.test:80/org/repo.git") == "example.test/org/repo"


def test_non_default_https_port_is_included_in_identity() -> None:
    assert (
        normalize_git_remote("https://example.test:8443/org/repo.git")
        == "example.test:8443/org/repo"
    )


def test_default_git_protocol_port_is_omitted_from_identity() -> None:
    assert normalize_git_remote("git://example.test:9418/org/repo.git") == "example.test/org/repo"
    assert normalize_git_remote("git://example.test/org/repo.git") == "example.test/org/repo"


def test_repository_display_name_humanizes_final_component() -> None:
    assert repository_display_name("github.com/mike/iiwi") == "Iiwi"
