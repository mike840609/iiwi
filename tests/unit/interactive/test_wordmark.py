from __future__ import annotations

from io import StringIO

from rich.console import Console

from iiwi.interactive.render import render_main_menu

EXPECTED_G_WORDMARK = (
    "██╗ ██╗ ██╗     ██╗ ██╗",
    "██║ ██║ ██║     ██║ ██║",
    "██║ ██║ ██║ ██╗ ██║ ██║",
    "██║ ██║ ██║████╗██║ ██║",
    "██║ ██║ ╚███╔████╔╝ ██║",
    "╚═╝ ╚═╝  ╚══╝╚═══╝  ╚═╝",
)


def test_main_menu_uses_the_selected_g_wordmark() -> None:
    stream = StringIO()
    console = Console(
        file=stream,
        color_system=None,
        force_terminal=False,
        width=100,
        height=30,
    )

    render_main_menu(console, selected=0)

    lines = stream.getvalue().splitlines()
    assert tuple(lines[:5]) == EXPECTED_G_WORDMARK[:5]
    assert lines[5].startswith(EXPECTED_G_WORDMARK[5])
