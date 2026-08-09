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


def test_repository_display_name_humanizes_final_component() -> None:
    assert repository_display_name("github.com/mike/agent-worklog") == "Agent Worklog"
