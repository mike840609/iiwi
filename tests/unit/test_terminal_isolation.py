"""Guard for the _isolate_terminal_env fixture in tests/conftest.py.

Without it, a contributor running with NO_COLOR=1 TERM=dumb fails the style and
table-wrapping assertions across test_render.py and test_logging.py. This test
fails first, and says why, instead of leaving six unrelated tests red.
"""

from io import StringIO

from rich.console import Console


def test_rich_ignores_the_contributors_terminal_environment() -> None:
    stream = StringIO()
    console = Console(file=stream, color_system="truecolor", force_terminal=True, width=120)

    console.print("styled", style="red")

    # NO_COLOR strips styles even from an explicitly coloured console.
    assert "\x1b[" in stream.getvalue()
    # TERM=dumb pins the size to 80x25 regardless of the width passed here.
    assert console.size.width == 120
