"""Safe, normalized terminal key input for the interactive CLI."""

from __future__ import annotations

import os
import select
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

# Timing constants tolerate remote links, which pause far longer than local
# terminals between bytes of one sequence. _CONTINUATION_MAX_TRIES x
# _ESCAPE_BYTE_TIMEOUT is the ~500ms budget for an incomplete UTF-8 character;
# _MAX_SEQUENCE_BYTES covers long reports such as xterm modifyOtherKeys and
# SGR mouse sequences.
_ESCAPE_BYTE_TIMEOUT = 0.05
_CONTINUATION_MAX_TRIES = 10
_MAX_SEQUENCE_BYTES = 16


class Key(StrEnum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    PAGE_UP = "page_up"
    PAGE_DOWN = "page_down"
    HOME = "home"
    END = "end"
    ENTER = "enter"
    SPACE = "space"
    ESCAPE = "escape"
    BACKSPACE = "backspace"
    DELETE = "delete"


@dataclass(frozen=True)
class KeyPress:
    key: Key | None = None
    char: str | None = None


def normalize_posix_sequence(value: str) -> KeyPress:
    """Convert one terminal sequence into a logical key press."""

    mapping = {
        "\x1b[A": Key.UP,
        "\x1b[B": Key.DOWN,
        "\x1b[D": Key.LEFT,
        "\x1b[C": Key.RIGHT,
        # SS3 forms sent by terminals in application cursor mode (tmux, and
        # inner TUI apps that leave DECCKM set).
        "\x1bOA": Key.UP,
        "\x1bOB": Key.DOWN,
        "\x1bOD": Key.LEFT,
        "\x1bOC": Key.RIGHT,
        "\x1bOH": Key.HOME,
        "\x1bOF": Key.END,
        "\x1b[5~": Key.PAGE_UP,
        "\x1b[6~": Key.PAGE_DOWN,
        "\x1b[H": Key.HOME,
        "\x1b[1~": Key.HOME,
        "\x1b[F": Key.END,
        "\x1b[4~": Key.END,
        "\x1b[3~": Key.DELETE,
        "\r": Key.ENTER,
        "\n": Key.ENTER,
        " ": Key.SPACE,
        "\x1b": Key.ESCAPE,
        "\x08": Key.BACKSPACE,
        "\x7f": Key.BACKSPACE,
    }
    key = mapping.get(value)
    if key is not None:
        return KeyPress(key=key)
    if value.startswith("\x1b"):
        # Unmapped escape-prefixed input (unknown CSI/SS3 sequences, doubled
        # Esc) must never leak raw bytes into text inputs; one cancel press is
        # the safe interpretation.
        return KeyPress(key=Key.ESCAPE)
    return KeyPress(char=value)


def _posix_setup() -> object:
    import termios
    import tty

    fd = sys.stdin.fileno()
    attributes = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    return fd, attributes


def _posix_restore(token: object) -> None:
    import termios

    fd, attributes = token  # type: ignore[misc]
    termios.tcsetattr(fd, termios.TCSADRAIN, attributes)


def _escape_sequence_complete(sequence: str) -> bool:
    """Whether a CSI/SS3 escape sequence has reached its final byte."""

    if len(sequence) < 3:
        return False
    final = sequence[-1]
    return final == "~" or "@" <= final <= "~"


def _utf8_character_length(lead: int) -> int:
    """Total bytes in the UTF-8 code point a lead byte begins."""

    if lead < 0x80:
        return 1
    if 0xC2 <= lead <= 0xDF:
        return 2
    if 0xE0 <= lead <= 0xEF:
        return 3
    if 0xF0 <= lead <= 0xF4:
        return 4
    # Invalid lead bytes (overlong 0xC0-0xC1, stray continuations 0x80-0xBF,
    # or 0xF5-0xFF) are consumed alone and dropped by errors="ignore".
    return 1


def _read_byte_tolerating_delays(fd: int) -> bytes | None:
    """Read one byte, retrying through remote-link pauses before giving up."""

    for _ in range(_CONTINUATION_MAX_TRIES):
        readable, _, _ = select.select([fd], [], [], _ESCAPE_BYTE_TIMEOUT)
        if readable:
            return os.read(fd, 1)
    return None


def _posix_read() -> str:
    fd = sys.stdin.fileno()
    first = os.read(fd, 1)
    if not first:
        return ""

    if first == b"\x1b":
        sequence = "\x1b"
        for _ in range(_MAX_SEQUENCE_BYTES - 1):
            readable, _, _ = select.select([fd], [], [], _ESCAPE_BYTE_TIMEOUT)
            if not readable:
                break
            sequence += os.read(fd, 1).decode(errors="ignore")
            if _escape_sequence_complete(sequence):
                break
        return sequence

    collected = bytearray(first)
    for _ in range(_utf8_character_length(first[0]) - 1):
        byte = _read_byte_tolerating_delays(fd)
        if byte is None:
            break
        collected += byte
    return bytes(collected).decode(errors="ignore")


def _windows_setup() -> object:
    return None


def _windows_restore(token: object) -> None:
    return None


def _windows_read() -> str:
    import msvcrt

    try:
        first = msvcrt.getwch() or ""  # type: ignore[attr-defined]
    except OSError:
        # EOF on a closed console reads as empty so read_key exits gracefully.
        return ""
    if first in {"\x00", "\xe0"}:
        try:
            second = msvcrt.getwch() or ""  # type: ignore[attr-defined]
        except OSError:
            return ""
        mapping = {
            "H": "\x1b[A",
            "P": "\x1b[B",
            "K": "\x1b[D",
            "M": "\x1b[C",
            "I": "\x1b[5~",
            "Q": "\x1b[6~",
            "G": "\x1b[H",
            "O": "\x1b[F",
            "S": "\x1b[3~",
        }
        # Unknown extended codes read as empty instead of leaking the raw
        # second character (";<=>?@ABCD", "s"/"t", ...) into text inputs.
        return mapping.get(second, "")
    return first


class TerminalInput:
    """Context-managed one-key reader that always restores terminal mode."""

    def __init__(
        self,
        *,
        setup: Callable[[], object] | None = None,
        restore: Callable[[object], None] | None = None,
        reader: Callable[[], str] | None = None,
    ) -> None:
        if setup is None or restore is None or reader is None:
            if os.name == "nt":
                setup = setup or _windows_setup
                restore = restore or _windows_restore
                reader = reader or _windows_read
            else:
                setup = setup or _posix_setup
                restore = restore or _posix_restore
                reader = reader or _posix_read
        self._setup = setup
        self._restore = restore
        self._reader = reader
        self._token: object | None = None
        self._entered = False

    def __enter__(self) -> TerminalInput:
        self._token = self._setup()
        self._entered = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._entered:
            self._restore(self._token)
            self._entered = False
            self._token = None

    def read_key(self) -> KeyPress:
        value = self._reader()
        if value == "":
            # Empty reads mean EOF (posix os.read -> b"", windows OSError or
            # ignored extended code): surface Escape so idle loops exit
            # gracefully instead of spinning on unhandled empty keypresses.
            return KeyPress(key=Key.ESCAPE)
        return normalize_posix_sequence(value)
