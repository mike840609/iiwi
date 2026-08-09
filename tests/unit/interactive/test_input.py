from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from iiwi.interactive.input import (
    Key,
    KeyPress,
    TerminalInput,
    _windows_read,
    normalize_posix_sequence,
)


def test_arrow_enter_space_escape_and_char_sequences_normalize() -> None:
    assert normalize_posix_sequence("\x1b[A") == KeyPress(key=Key.UP)
    assert normalize_posix_sequence("\x1b[B") == KeyPress(key=Key.DOWN)
    assert normalize_posix_sequence("\x1b[D") == KeyPress(key=Key.LEFT)
    assert normalize_posix_sequence("\x1b[C") == KeyPress(key=Key.RIGHT)
    assert normalize_posix_sequence("\r") == KeyPress(key=Key.ENTER)
    assert normalize_posix_sequence("\n") == KeyPress(key=Key.ENTER)
    assert normalize_posix_sequence(" ") == KeyPress(key=Key.SPACE)
    assert normalize_posix_sequence("\x1b") == KeyPress(key=Key.ESCAPE)
    assert normalize_posix_sequence("j") == KeyPress(char="j")
    assert normalize_posix_sequence("k") == KeyPress(char="k")


def test_paging_home_end_delete_and_backspace_sequences_normalize() -> None:
    assert normalize_posix_sequence("\x1b[5~") == KeyPress(key=Key.PAGE_UP)
    assert normalize_posix_sequence("\x1b[6~") == KeyPress(key=Key.PAGE_DOWN)
    assert normalize_posix_sequence("\x1b[H") == KeyPress(key=Key.HOME)
    assert normalize_posix_sequence("\x1b[F") == KeyPress(key=Key.END)
    assert normalize_posix_sequence("\x1b[3~") == KeyPress(key=Key.DELETE)
    assert normalize_posix_sequence("\x7f") == KeyPress(key=Key.BACKSPACE)


def test_unknown_escape_sequence_is_preserved_as_char_input() -> None:
    assert normalize_posix_sequence("x") == KeyPress(char="x")


def test_terminal_context_restores_after_exception() -> None:
    events: list[str] = []
    terminal = TerminalInput(
        setup=lambda: events.append("setup") or "token",
        restore=lambda token: events.append(f"restore:{token}"),
        reader=lambda: "q",
    )

    with pytest.raises(RuntimeError, match="boom"), terminal:
        raise RuntimeError("boom")

    assert events == ["setup", "restore:token"]


def test_read_key_normalizes_the_injected_reader() -> None:
    terminal = TerminalInput(
        setup=lambda: None,
        restore=lambda token: None,
        reader=lambda: "\x1b[A",
    )

    assert terminal.read_key() == KeyPress(key=Key.UP)


def test_windows_adapter_translates_extended_arrow_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    values = iter(["\xe0", "H", "\xe0", "P", "\xe0", "K", "\xe0", "M"])
    fake_msvcrt = SimpleNamespace(getwch=lambda: next(values))
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    assert normalize_posix_sequence(_windows_read()) == KeyPress(key=Key.UP)
    assert normalize_posix_sequence(_windows_read()) == KeyPress(key=Key.DOWN)
    assert normalize_posix_sequence(_windows_read()) == KeyPress(key=Key.LEFT)
    assert normalize_posix_sequence(_windows_read()) == KeyPress(key=Key.RIGHT)


def test_windows_adapter_preserves_regular_character(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_msvcrt = SimpleNamespace(getwch=lambda: "q")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    assert _windows_read() == "q"
