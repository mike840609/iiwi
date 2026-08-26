import io
import pathlib
from datetime import UTC, datetime
from unittest import mock

from iiwi.history import HistoryEntry, HistoryKind


def _entry(path: pathlib.Path, name: str = "opencode") -> HistoryEntry:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    return HistoryEntry(
        generated_at=now,
        since=now,
        until=now,
        output_path=path,
        repository_count=2,
        session_count=3,
        kind=HistoryKind.REPORT,
        harness=name,
        narrative=True,
        detail="full",
    )


def test_filtered_history_hides_missing(tmp_path, monkeypatch):
    from iiwi.interactive.controller import _filtered_history

    exists = tmp_path / "exists.md"
    exists.write_text("x")
    missing = tmp_path / "gone.md"
    entries = [_entry(exists), _entry(missing)]
    visible, hidden = _filtered_history(entries, show_missing=False)
    assert len(visible) == 1
    assert hidden == 1
    visible2, hidden2 = _filtered_history(entries, show_missing=True)
    assert len(visible2) == 2
    assert hidden2 == 0


def test_history_h_toggle_clamps_cursor(tmp_path):
    from rich.console import Console

    from iiwi.interactive.controller import _history_key, _State
    from iiwi.interactive.input import KeyPress

    console = Console(file=io.StringIO(), force_terminal=True, width=120, height=24)
    s = _State()
    s.screen = __import__("iiwi.interactive.models", fromlist=["Screen"]).Screen.HISTORY
    s.history_show_missing = True
    s.history_cursor = 1
    _history_key(s, KeyPress(char="h"), console)
    assert s.history_show_missing is False
    assert s.history_cursor <= 0


def test_history_enter_missing_shows_error(tmp_path):
    from rich.console import Console

    from iiwi.interactive.controller import _history_key, _State
    from iiwi.interactive.input import Key, KeyPress
    from iiwi.interactive.models import Screen

    console = Console(file=io.StringIO(), force_terminal=True, width=120, height=24)
    missing = tmp_path / "gone.md"
    entry = _entry(missing)
    s = _State(screen=Screen.HISTORY, history_cursor=0, history_show_missing=True)
    with mock.patch("iiwi.interactive.controller._history_entries", return_value=[entry]):
        _history_key(s, KeyPress(key=Key.ENTER), console)
        assert s.screen == Screen.RECOVERABLE_ERROR
        assert s.error is not None
        assert "not found" in s.error.detail.lower() or "missing" in s.error.detail.lower()


def test_open_history_entry_invokes_editor(tmp_path, monkeypatch):

    exists = tmp_path / "exists.md"
    exists.write_text("hello")
    entry = _entry(exists)
    monkeypatch.setenv("VISUAL", "myeditor --wait")
    called = {}

    def fake_run(cmd, check):
        called["cmd"] = cmd
        assert cmd[0] == "myeditor"
        assert cmd[-1] == str(exists)
        return mock.Mock(returncode=0)

    with mock.patch("subprocess.run", side_effect=fake_run):
        from iiwi.interactive.controller import _open_history_entry

        _open_history_entry(entry)
    assert "cmd" in called


def test_history_preview_scroll_and_open(tmp_path):
    from rich.console import Console

    from iiwi.interactive.controller import _history_preview_key, _State
    from iiwi.interactive.input import Key, KeyPress
    from iiwi.interactive.models import Screen

    exists = tmp_path / "exists.md"
    exists.write_text("\n".join([f"line {i}" for i in range(30)]))
    entry = _entry(exists)
    s = _State(screen=Screen.HISTORY_PREVIEW, history_preview_entry=entry, history_preview_offset=0)
    console = Console(file=io.StringIO(), force_terminal=True, width=80, height=24)
    _history_preview_key(s, KeyPress(key=Key.DOWN), console)
    assert s.history_preview_offset == 1
    _history_preview_key(s, KeyPress(key=Key.PAGE_DOWN), console)
    assert s.history_preview_offset > 1
    _history_preview_key(s, KeyPress(char="g"), console)
    assert s.history_preview_offset == 0
    _history_preview_key(s, KeyPress(char="b"), console)
    assert s.screen == Screen.HISTORY


def test_history_preview_open_missing_returns_error(tmp_path):
    from rich.console import Console

    from iiwi.interactive.controller import _history_preview_key, _State
    from iiwi.interactive.input import KeyPress
    from iiwi.interactive.models import Screen

    missing = tmp_path / "gone.md"
    entry = _entry(missing)
    s = _State(screen=Screen.HISTORY_PREVIEW, history_preview_entry=entry)
    console = Console(file=io.StringIO(), force_terminal=True, width=80, height=24)
    _history_preview_key(s, KeyPress(char="o"), console)
    assert s.screen == Screen.RECOVERABLE_ERROR
