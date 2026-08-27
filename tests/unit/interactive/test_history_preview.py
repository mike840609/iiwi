"""History preview: filtering, the missing toggle, opening, and scrolling."""

from __future__ import annotations

import io
import pathlib
import subprocess
from datetime import UTC, datetime
from unittest import mock

import pytest
from rich.console import Console

from iiwi.history import HistoryEntry, HistoryKind
from iiwi.interactive.controller import (
    _filtered_history,
    _history_key,
    _history_preview_key,
    _open_history_entry,
    _State,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import Screen


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


def _console(width: int = 120, height: int = 24) -> Console:
    return Console(file=io.StringIO(), force_terminal=True, width=width, height=height)


def test_filtered_history_hides_missing(tmp_path: pathlib.Path) -> None:
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


def test_history_h_toggle_clamps_cursor(tmp_path: pathlib.Path) -> None:
    """Hiding missing entries must pull a cursor that is now past the end back in.

    The clamp is what stops the next `Enter` from indexing off the shortened
    visible list, so the toggle has to run against a list that actually shrinks.
    """

    present = tmp_path / "present.md"
    present.write_text("kept", encoding="utf-8")
    entries = [_entry(present), _entry(tmp_path / "gone-a.md"), _entry(tmp_path / "gone-b.md")]
    state = _State(screen=Screen.HISTORY, history_show_missing=True, history_cursor=2)
    with mock.patch("iiwi.interactive.controller._history_entries", return_value=entries):
        _history_key(state, KeyPress(char="h"), _console())

    assert state.history_show_missing is False
    assert state.history_cursor == 0
    assert state.history_offset == 0


def test_history_enter_survives_entries_vanishing_under_a_stale_cursor(
    tmp_path: pathlib.Path,
) -> None:
    """A cursor left past the end by files deleted outside iiwi must not crash.

    The list is re-read on every keystroke, so between `G` and `Enter` it can
    shrink; `Enter` is not a movement key, so nothing else clamps the cursor.
    """

    present = tmp_path / "present.md"
    present.write_text("kept", encoding="utf-8")
    entries = [_entry(present), _entry(tmp_path / "gone-a.md"), _entry(tmp_path / "gone-b.md")]
    state = _State(screen=Screen.HISTORY, history_cursor=2)
    with mock.patch("iiwi.interactive.controller._history_entries", return_value=entries):
        _history_key(state, KeyPress(key=Key.ENTER), _console())

    assert state.screen is Screen.HISTORY_PREVIEW
    assert state.history_preview_content == "kept"


def test_history_enter_missing_shows_error(tmp_path: pathlib.Path) -> None:
    missing = tmp_path / "gone.md"
    state = _State(screen=Screen.HISTORY, history_cursor=0, history_show_missing=True)
    with mock.patch("iiwi.interactive.controller._history_entries", return_value=[_entry(missing)]):
        _history_key(state, KeyPress(key=Key.ENTER), _console())

    assert state.screen is Screen.RECOVERABLE_ERROR
    assert state.error is not None
    assert state.error.kind == "history-missing"
    assert str(missing) in state.error.detail


def test_open_history_entry_invokes_editor(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exists = tmp_path / "exists.md"
    exists.write_text("hello")
    monkeypatch.setenv("VISUAL", "myeditor --wait")
    called: dict[str, object] = {}

    def fake_run(cmd, check, timeout):  # noqa: ANN001, ANN202
        called["cmd"] = cmd
        called["timeout"] = timeout
        return mock.Mock(returncode=0)

    with mock.patch("subprocess.run", side_effect=fake_run):
        _open_history_entry(_entry(exists))

    assert called["cmd"] == ["myeditor", "--wait", str(exists)]
    # An editor blocks for as long as the user edits; a timeout would kill it.
    assert called["timeout"] is None


def test_open_history_entry_blank_editor_falls_back_to_the_platform_launcher(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whitespace-only $EDITOR must not make iiwi execute the report itself."""

    exists = tmp_path / "exists.md"
    exists.write_text("hello")
    monkeypatch.setenv("EDITOR", "   ")
    monkeypatch.delenv("VISUAL", raising=False)
    called: dict[str, object] = {}

    def fake_run(cmd, check, timeout):  # noqa: ANN001, ANN202
        called["cmd"] = cmd
        called["timeout"] = timeout
        return mock.Mock(returncode=0)

    with mock.patch("subprocess.run", side_effect=fake_run):
        _open_history_entry(_entry(exists))

    cmd = called["cmd"]
    assert isinstance(cmd, list)
    assert cmd != [str(exists)]
    assert cmd[0] in {"open", "xdg-open", "cmd"}
    assert called["timeout"] is not None


def test_open_reports_a_missing_editor_as_an_open_failure_not_a_missing_report(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`subprocess` raises FileNotFoundError for a missing *editor* too.

    Reporting that as "File not found" tells the user their report was deleted
    when the report is right there and only $EDITOR is wrong.
    """

    exists = tmp_path / "exists.md"
    exists.write_text("hello")
    monkeypatch.setenv("VISUAL", "definitely-not-installed-editor")
    state = _State(screen=Screen.HISTORY_PREVIEW, history_preview_entry=_entry(exists))
    with mock.patch("subprocess.run", side_effect=FileNotFoundError(2, "No such file")):
        _history_preview_key(state, KeyPress(char="o"), _console())

    assert state.screen is Screen.RECOVERABLE_ERROR
    assert state.error is not None
    assert state.error.kind == "history-open"
    assert "definitely-not-installed-editor" in state.error.detail


def test_open_failure_still_forces_a_full_repaint(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The editor owns the terminal, so the next frame cannot be a row diff."""

    exists = tmp_path / "exists.md"
    exists.write_text("hello")
    monkeypatch.setenv("VISUAL", "myeditor")
    state = _State(screen=Screen.HISTORY_PREVIEW, history_preview_entry=_entry(exists))
    with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)):
        _history_preview_key(state, KeyPress(char="o"), _console())

    assert state.force_repaint is True


def test_open_failure_surfaces_a_nonzero_exit(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exists = tmp_path / "exists.md"
    exists.write_text("hello")
    monkeypatch.setenv("VISUAL", "myeditor")
    state = _State(screen=Screen.HISTORY_PREVIEW, history_preview_entry=_entry(exists))
    with mock.patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["myeditor"])):
        _history_preview_key(state, KeyPress(char="o"), _console())

    assert state.screen is Screen.RECOVERABLE_ERROR
    assert state.error is not None
    assert state.error.kind == "history-open"


def test_history_preview_scroll_and_open(tmp_path: pathlib.Path) -> None:
    exists = tmp_path / "exists.md"
    content = "\n".join(f"line {index}" for index in range(30))
    exists.write_text(content)
    state = _State(
        screen=Screen.HISTORY_PREVIEW,
        history_preview_entry=_entry(exists),
        history_preview_content=content,
        history_preview_offset=0,
    )
    console = _console(width=80)
    _history_preview_key(state, KeyPress(key=Key.DOWN), console)
    assert state.history_preview_offset == 1
    _history_preview_key(state, KeyPress(key=Key.PAGE_DOWN), console)
    assert state.history_preview_offset > 1
    _history_preview_key(state, KeyPress(char="g"), console)
    assert state.history_preview_offset == 0
    _history_preview_key(state, KeyPress(char="b"), console)
    assert state.screen is Screen.HISTORY


def test_history_preview_scrolls_without_rereading_the_file(tmp_path: pathlib.Path) -> None:
    """Scrolling reads the cached content, not the disk, on every keystroke."""

    exists = tmp_path / "exists.md"
    content = "\n".join(f"line {index}" for index in range(30))
    exists.write_text(content)
    state = _State(
        screen=Screen.HISTORY_PREVIEW,
        history_preview_entry=_entry(exists),
        history_preview_content=content,
    )
    exists.unlink()
    _history_preview_key(state, KeyPress(key=Key.DOWN), _console(width=80))

    assert state.screen is Screen.HISTORY_PREVIEW
    assert state.history_preview_offset == 1


def test_history_preview_refreshes_content_after_the_editor_returns(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exists = tmp_path / "exists.md"
    exists.write_text("before", encoding="utf-8")
    monkeypatch.setenv("VISUAL", "myeditor")
    state = _State(
        screen=Screen.HISTORY_PREVIEW,
        history_preview_entry=_entry(exists),
        history_preview_content="before",
    )

    def fake_run(cmd, check, timeout):  # noqa: ANN001, ANN202
        exists.write_text("after", encoding="utf-8")
        return mock.Mock(returncode=0)

    with mock.patch("subprocess.run", side_effect=fake_run):
        _history_preview_key(state, KeyPress(char="o"), _console())

    assert state.history_preview_content == "after"


def test_history_preview_open_missing_returns_error(tmp_path: pathlib.Path) -> None:
    missing = tmp_path / "gone.md"
    state = _State(screen=Screen.HISTORY_PREVIEW, history_preview_entry=_entry(missing))
    _history_preview_key(state, KeyPress(char="o"), _console(width=80))

    assert state.screen is Screen.RECOVERABLE_ERROR
    assert state.error is not None
    assert state.error.kind == "history-missing"
