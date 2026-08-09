"""Adoption of state written under the pre-rename name."""

from __future__ import annotations

from pathlib import Path

import pytest

from iiwi.paths import adopt_legacy


def _fail_if_called(*args: object, **kwargs: object) -> Path:
    raise AssertionError("adoption ran despite an explicit override")


def test_moves_legacy_file_when_the_new_one_is_absent(tmp_path: Path) -> None:
    legacy = tmp_path / "agent-worklog" / "history.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("kept\n", encoding="utf-8")
    new = tmp_path / "iiwi" / "history.jsonl"

    assert adopt_legacy(new, legacy) == new
    assert new.read_text(encoding="utf-8") == "kept\n"
    assert not legacy.exists()


def test_keeps_the_new_file_when_both_exist(tmp_path: Path) -> None:
    legacy = tmp_path / "agent-worklog" / "history.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("old\n", encoding="utf-8")
    new = tmp_path / "iiwi" / "history.jsonl"
    new.parent.mkdir(parents=True)
    new.write_text("current\n", encoding="utf-8")

    adopt_legacy(new, legacy)

    assert new.read_text(encoding="utf-8") == "current\n"
    assert legacy.read_text(encoding="utf-8") == "old\n"


def test_does_nothing_when_there_is_no_legacy_file(tmp_path: Path) -> None:
    legacy = tmp_path / "agent-worklog" / "history.jsonl"
    new = tmp_path / "iiwi" / "history.jsonl"

    assert adopt_legacy(new, legacy) == new
    assert not new.exists()
    assert not new.parent.exists()


def test_is_idempotent(tmp_path: Path) -> None:
    legacy = tmp_path / "agent-worklog" / "config.env"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("kept\n", encoding="utf-8")
    new = tmp_path / "iiwi" / "config.env"

    adopt_legacy(new, legacy)
    adopt_legacy(new, legacy)

    assert new.read_text(encoding="utf-8") == "kept\n"


@pytest.mark.parametrize(
    ("module", "resolver", "directory_function", "filename"),
    [
        ("iiwi.config_store", "config_file_path", "user_config_dir", "config.env"),
        ("iiwi.history", "history_file_path", "user_data_dir", "history.jsonl"),
        ("iiwi.state", "state_file_path", "user_data_dir", "state.json"),
    ],
)
def test_each_resolver_adopts_its_legacy_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module: str,
    resolver: str,
    directory_function: str,
    filename: str,
) -> None:
    """The autouse fixture sets the override, so clear it to reach the real branch."""

    import importlib

    for variable in ("IIWI_CONFIG_FILE", "IIWI_HISTORY_FILE", "IIWI_STATE_FILE"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(
        importlib.import_module(module),
        directory_function,
        lambda name: str(tmp_path / name),
    )

    legacy = tmp_path / "agent-worklog" / filename
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("kept\n", encoding="utf-8")

    resolved = getattr(importlib.import_module(module), resolver)()

    assert resolved == tmp_path / "iiwi" / filename
    assert resolved.read_text(encoding="utf-8") == "kept\n"
    assert not legacy.exists()


@pytest.mark.parametrize(
    ("module", "resolver", "variable"),
    [
        ("iiwi.config_store", "config_file_path", "IIWI_CONFIG_FILE"),
        ("iiwi.history", "history_file_path", "IIWI_HISTORY_FILE"),
        ("iiwi.state", "state_file_path", "IIWI_STATE_FILE"),
    ],
)
def test_the_override_wins_and_attempts_no_move(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module: str,
    resolver: str,
    variable: str,
) -> None:
    import importlib

    override = tmp_path / "explicit" / "file"
    monkeypatch.setenv(variable, str(override))
    monkeypatch.setattr(
        importlib.import_module(module),
        "adopt_legacy",
        _fail_if_called,
    )

    assert getattr(importlib.import_module(module), resolver)() == override
