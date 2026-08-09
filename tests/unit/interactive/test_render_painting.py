"""The interactive loop paints frames over each other rather than clearing between them.

Moving the cursor rewrites only the two rows it changes, the same way mole's
up/down menus do: nothing else on screen moves, so there is nothing to flash.
"""

from __future__ import annotations

import re
from io import StringIO

from rich.console import Console

from iiwi.interactive import controller


def _terminal_console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(file=stream, force_terminal=True, width=60, height=20, color_system=None),
        stream,
    )


def _plain_console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(file=stream, force_terminal=False, width=60, height=20, color_system=None),
        stream,
    )


def _strip_cursor(text: str) -> str:
    text = re.sub(r"\x1b\[(\d+);1H", lambda m: "" if m.group(1) == "1" else "\n", text)
    text = text.replace("\x1b[H", "")
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)


def _paint_rows(written: str) -> list[int]:
    return [int(row) for row in re.findall(r"\x1b\[(\d+);1H(?!\x1b\[J)", written)]


def test_a_frame_never_clears_the_screen() -> None:
    """Clearing then reprinting is what showed a blank screen between frames."""

    console, stream = _terminal_console()

    controller._render(controller._State(), console, None)

    written = stream.getvalue()
    assert "\x1b[2J" not in written
    assert "\x1b[3J" not in written


def test_the_first_frame_starts_at_home_and_erases_below_itself() -> None:
    """Home puts the frame over anything below the cursor; the trailing erase drops leftovers."""

    console, stream = _terminal_console()

    controller._render(controller._State(), console, None)

    written = stream.getvalue()
    assert written.startswith("\x1b[?25l\x1b[H")
    assert written.endswith("\x1b[J\x1b[?25h")


def test_every_painted_line_erases_only_its_own_tail() -> None:
    """A line must clear what the previous frame left to its right, and nothing more."""

    console, stream = _terminal_console()

    controller._render(controller._State(), console, None)

    written = stream.getvalue()
    body = written[len("\x1b[?25l\x1b[H") : -len("\x1b[J\x1b[?25h")]
    chunks = body.split("\x1b[K")[:-1]
    assert chunks
    assert all(";1H" in chunk for chunk in chunks)


def test_cursor_movement_rewrites_only_the_two_rows_it_changes() -> None:
    """Up/down repaints the old and new cursor rows and nothing else."""

    console, stream = _terminal_console()
    state = controller._State()
    previous = controller._render(state, console, None)
    assert previous is not None

    stream.truncate(0)
    stream.seek(0)
    state.main_cursor = 1
    controller._render(state, console, previous)

    written = stream.getvalue()
    assert "\x1b[H" not in written
    assert "\x1b[2J" not in written
    rows = _paint_rows(written)
    assert len(rows) == 2
    assert rows[1] == rows[0] + 1
    assert "▶" in written


def test_repeated_cursor_movement_stays_row_local() -> None:
    """Holding a cursor key down must never grow into a full repaint."""

    console, stream = _terminal_console()
    state = controller._State()
    previous = controller._render(state, console, None)
    assert previous is not None

    for cursor in range(1, 4):
        state.main_cursor = cursor
        stream.truncate(0)
        stream.seek(0)
        next_previous = controller._render(state, console, previous)
        assert next_previous is not None
        previous = next_previous
        rows = _paint_rows(stream.getvalue())
        assert len(rows) == 2


def test_a_screen_change_repaints_what_changed_without_clearing() -> None:
    """Switching screens rewrites the differing rows only; nothing is cleared."""

    console, stream = _terminal_console()
    state = controller._State()
    previous = controller._render(state, console, None)
    assert previous is not None

    stream.truncate(0)
    stream.seek(0)
    state.screen = controller.Screen.HELP
    controller._render(state, console, previous)

    written = stream.getvalue()
    assert "\x1b[2J" not in written
    assert _paint_rows(written)  # some rows were rewritten
    assert written.endswith("\x1b[?25h")


def test_a_shorter_next_frame_erases_what_the_previous_left_below() -> None:
    """A short screen painted after a tall one must not leave the tall one's rows behind."""

    console, stream = _terminal_console()
    state = controller._State()
    previous = controller._render(state, console, None)
    assert previous is not None

    state.screen = controller.Screen.HELP
    help_previous = controller._render(state, console, previous)
    assert help_previous is not None

    state.screen = controller.Screen.MAIN
    state.main_cursor = 0
    stream.truncate(0)
    stream.seek(0)
    controller._render(state, console, help_previous)

    written = stream.getvalue()
    plain_console, plain_stream = _plain_console()
    controller._render_screen(controller._State(), plain_console)
    main_lines = plain_stream.getvalue().splitlines()
    assert f"\x1b[{len(main_lines) + 1};1H" in written
    assert written.endswith("\x1b[J\x1b[?25h")


def test_painting_does_not_change_what_the_screen_says() -> None:
    """The cursor control is the only difference between the two paths."""

    console, stream = _terminal_console()
    controller._render(controller._State(), console, None)
    painted = stream.getvalue()

    plain_console, plain_stream = _plain_console()
    controller._render_screen(controller._State(), plain_console)

    assert _strip_cursor(painted) == plain_stream.getvalue()


def test_a_non_terminal_console_is_painted_with_nothing() -> None:
    """Captured output and CI logs must stay free of cursor control."""

    console, stream = _plain_console()

    controller._render(controller._State(), console, None)

    written = stream.getvalue()
    assert "\x1b[H" not in written
    assert "\x1b[K" not in written
    assert "\x1b[J" not in written
    assert "\x1b[?25l" not in written
