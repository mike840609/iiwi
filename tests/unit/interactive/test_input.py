from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pytest

from iiwi.interactive.input import (
    Key,
    KeyPress,
    TerminalInput,
    _posix_read,
    _windows_read,
    normalize_posix_sequence,
)

# Fragment gaps must exceed the pre-fix 20ms escape window (else the old reader
# would pass these tests) yet stay under the fixed 50ms window.
_FRAGMENT_GAP_SECONDS = 0.025
_FAST_GAP_SECONDS = 0.005


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


class _ScriptedByteSource:
    """Feed byte fragments to the posix reader one os.read call at a time."""

    def __init__(self, fragments: list[bytes], gap_seconds: float) -> None:
        self._fragments = list(fragments)
        self._gap_seconds = gap_seconds

    def poll(self, timeout: float) -> bool:
        if not self._fragments:
            return False
        time.sleep(min(timeout, self._gap_seconds))
        return timeout >= self._gap_seconds

    def read(self, _fd: int, _size: int) -> bytes:
        if not self._fragments:
            return b""
        return self._fragments.pop(0)


def _patch_posix_stdin(
    monkeypatch: pytest.MonkeyPatch,
    source: _ScriptedByteSource,
) -> None:
    import iiwi.interactive.input as input_module

    monkeypatch.setattr(input_module.sys, "stdin", SimpleNamespace(fileno=lambda: 0))
    monkeypatch.setattr(input_module.os, "read", source.read)

    def fake_select(readable, _writable, _errors, timeout):
        if source.poll(timeout):
            return (readable, [], [])
        return ([], [], [])

    monkeypatch.setattr(input_module.select, "select", fake_select)


def _terminal_reading_posix() -> TerminalInput:
    return TerminalInput(
        setup=lambda: None,
        restore=lambda token: None,
        reader=_posix_read,
    )


def test_arrow_key_survives_slow_delivery_across_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _ScriptedByteSource([b"\x1b", b"[", b"A"], gap_seconds=_FRAGMENT_GAP_SECONDS)
    _patch_posix_stdin(monkeypatch, source)

    assert _terminal_reading_posix().read_key() == KeyPress(key=Key.UP)


def test_multibyte_character_survives_fragmented_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _ScriptedByteSource([b"\xe4", b"\xb8", b"\xad"], gap_seconds=_FRAGMENT_GAP_SECONDS)
    _patch_posix_stdin(monkeypatch, source)

    assert _terminal_reading_posix().read_key() == KeyPress(char="中")


def test_long_modify_other_keys_sequence_is_not_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    sequence = "\x1b[27;5;13~"
    source = _ScriptedByteSource(
        [char.encode() for char in sequence],
        gap_seconds=_FAST_GAP_SECONDS,
    )
    _patch_posix_stdin(monkeypatch, source)

    press = _terminal_reading_posix().read_key()

    assert press == KeyPress(key=Key.ESCAPE)
    assert press.char is None


def test_ss3_arrow_and_home_end_keys_are_mapped() -> None:
    assert normalize_posix_sequence("\x1bOA") == KeyPress(key=Key.UP)
    assert normalize_posix_sequence("\x1bOB") == KeyPress(key=Key.DOWN)
    assert normalize_posix_sequence("\x1bOD") == KeyPress(key=Key.LEFT)
    assert normalize_posix_sequence("\x1bOC") == KeyPress(key=Key.RIGHT)
    assert normalize_posix_sequence("\x1bOH") == KeyPress(key=Key.HOME)
    assert normalize_posix_sequence("\x1bOF") == KeyPress(key=Key.END)


def test_unknown_escape_sequence_becomes_escape_not_garbage() -> None:
    assert normalize_posix_sequence("\x1b[1;5C") == KeyPress(key=Key.ESCAPE)


def test_doubled_escape_becomes_escape() -> None:
    assert normalize_posix_sequence("\x1b\x1b") == KeyPress(key=Key.ESCAPE)


def test_windows_unknown_extended_code_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    values = iter(["\xe0", ";"])
    fake_msvcrt = SimpleNamespace(getwch=lambda: next(values))
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    assert _windows_read() == ""

    values = iter(["\xe0", ";"])
    press = TerminalInput(
        setup=lambda: None,
        restore=lambda token: None,
        reader=_windows_read,
    ).read_key()

    assert press == KeyPress(key=Key.ESCAPE)
    assert press.char is None


def test_eof_returns_escape_instead_of_spinning() -> None:
    terminal = TerminalInput(
        setup=lambda: None,
        restore=lambda token: None,
        reader=lambda: "",
    )

    assert terminal.read_key() == KeyPress(key=Key.ESCAPE)
