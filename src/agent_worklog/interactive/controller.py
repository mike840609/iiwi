"""State-machine controller for the terminal-native Agent Worklog experience."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self

import typer
from rich.console import Console

from agent_worklog.errors import (
    AgentWorklogError,
    ReportAlreadyExistsError,
    ReportOutputError,
)
from agent_worklog.interactive.input import Key, KeyPress
from agent_worklog.interactive.models import ReportDraft, Screen
from agent_worklog.interactive.render import (
    build_filtered_rows,
    build_session_preview_lines,
    build_visible_rows,
    main_menu_options,
    recoverable_error_detail_capacity,
    render_help,
    render_main_menu,
    render_recoverable_error,
    render_report_preview,
    render_report_result,
    render_report_setup,
    render_session_browser,
    render_session_preview,
    render_session_review,
    report_generate_row,
    report_preview_capacity,
    report_result_options,
    report_setup_rows,
)
from agent_worklog.interactive.selection import SelectionState
from agent_worklog.models.session import AgentSession
from agent_worklog.models.time_range import DateRange
from agent_worklog.renderers.markdown import DetailLevel
from agent_worklog.services.scan import ScanResult


class KeySource(Protocol):
    """Minimal input contract; one context restores terminal mode after each key."""

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def read_key(self) -> KeyPress: ...


@dataclass(frozen=True)
class InteractiveReportResult:
    output_path: Path | None
    content: str
    repository_count: int
    session_count: int


@dataclass(frozen=True)
class InteractiveActions:
    """Business-logic seams supplied by `cli.py`, keeping this module cycle-free."""

    new_draft: Callable[[], ReportDraft]
    choose_harness: Callable[[str], str]
    choose_period: Callable[[str | None], tuple[str, DateRange]]
    scan: Callable[[ReportDraft], ScanResult]
    generate: Callable[[ReportDraft, ScanResult, bool], InteractiveReportResult]
    doctor: Callable[[str], list[str]]
    edit_settings: Callable[[], None]
    restore_selection: Callable[[str, DateRange, bool], set[str] | None]
    save_selection: Callable[[str, DateRange, bool, set[str]], None]
    exclude_repository: Callable[[str, str], str]


@dataclass
class _ErrorState:
    kind: str
    title: str
    detail: str
    selected: int = 0
    detail_offset: int = 0


@dataclass
class _State:
    screen: Screen = Screen.MAIN
    main_cursor: int = 0
    setup_cursor: int = 0
    browser_cursor: int = 0
    review_cursor: int = 0
    result_cursor: int = 0
    preview_offset: int = 0
    draft: ReportDraft | None = None
    browser_scan: ScanResult | None = None
    selection: SelectionState | None = None
    result: InteractiveReportResult | None = None
    expanded_repositories: set[str] | None = None
    preview_session: AgentSession | None = None
    preview_offset: int = 0
    preview_return_screen: Screen | None = None
    error: _ErrorState | None = None
    review_message: str | None = None
    search_query: str = ""
    searching: bool = False
    help_return_screen: Screen | None = None

    def expansions(self) -> set[str]:
        if self.expanded_repositories is None:
            self.expanded_repositories = set()
        return self.expanded_repositories


def _read_key(input_source: KeySource) -> KeyPress:
    """Read exactly one key while guaranteeing terminal restoration before actions run."""

    with input_source:
        return input_source.read_key()


def _char(key: KeyPress, value: str) -> bool:
    return key.char is not None and key.char.casefold() == value.casefold()


def _exact_char(key: KeyPress, value: str) -> bool:
    return key.char == value


def _move(cursor: int, key: KeyPress, count: int) -> int:
    if count <= 0:
        return 0
    up = key.key is Key.UP or _char(key, "k")
    down = key.key is Key.DOWN or _char(key, "j")
    if up:
        return max(0, cursor - 1)
    if down:
        return min(count - 1, cursor + 1)
    return cursor


# Clearing and then reprinting shows the terminal an empty screen between the two,
# which is the flicker. The next frame is painted over the last instead: only the
# rows whose bytes actually changed are rewritten in place, the cursor is hidden
# while the frame lands, and one erase after the last frame row drops whatever the
# previous frame — or an action's prompt — left below it.
_CURSOR_HIDE = "\x1b[?25l"
_CURSOR_SHOW = "\x1b[?25h"
_HOME = "\x1b[H"
_ERASE_LINE = "\x1b[K"
_ERASE_BELOW = "\x1b[J"


def _paint(console: Console, frame: str, previous: list[str] | None) -> list[str]:
    """Write one frame over the last, rewriting only the rows that changed.

    Moving the cursor changes exactly two rows, so exactly two rows are
    rewritten: nothing else on screen moves, so there is nothing to flash. The
    cursor is hidden while the frame lands, then parked below it — actions that
    hand off to typer prompts print there, and the next paint positions every
    row absolutely anyway.
    """

    lines = frame.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    changed = (
        list(enumerate(lines))
        if previous is None
        else [
            (index, line)
            for index, line in enumerate(lines)
            if index >= len(previous) or previous[index] != line
        ]
    )
    out: list[str] = [_HOME] if previous is None else []
    for index, line in changed:
        out.append(f"\x1b[{index + 1};1H")
        out.append(line)
        out.append(_ERASE_LINE)
    out.append(f"\x1b[{len(lines) + 1};1H")
    out.append(_ERASE_BELOW)
    console.file.write(f"{_CURSOR_HIDE}{''.join(out)}{_CURSOR_SHOW}")
    console.file.flush()
    return lines


def _reset_search(state: _State) -> None:
    state.search_query = ""
    state.searching = False


def _new_report(state: _State, actions: InteractiveActions) -> None:
    state.draft = actions.new_draft()
    state.setup_cursor = 0
    state.selection = None
    state.result = None
    state.error = None
    state.review_message = None
    state.preview_offset = 0
    state.expanded_repositories = set()
    _reset_search(state)
    state.screen = Screen.REPORT_SETUP


def _load_browse(
    state: _State,
    actions: InteractiveActions,
    draft: ReportDraft,
) -> None:
    """Scan an already configured browse draft, preserving it for recovery actions."""

    state.draft = draft
    try:
        scan = actions.scan(draft)
    except AgentWorklogError as exc:
        state.error = _ErrorState(
            kind="browse-source",
            title=f"Could not read {draft.harness} sessions",
            detail=str(exc),
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    if scan.loaded_session_count == 0:
        if scan.excluded_session_count > 0:
            state.error = _ErrorState(
                kind="browse-empty",
                title="Sessions excluded by configuration",
                detail="All sessions matched by the selected harness and period "
                "were excluded by configuration.",
            )
        else:
            state.error = _ErrorState(
                kind="browse-empty",
                title="No sessions found",
                detail="No activity matched the selected harness and period.",
            )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    state.browser_scan = scan
    state.browser_cursor = 0
    state.error = None
    state.expanded_repositories = set()
    _reset_search(state)
    state.screen = Screen.SESSION_BROWSER


def _begin_browse(state: _State, actions: InteractiveActions) -> None:
    """Browse with configured defaults; edits happen inside the key-driven screens."""

    _load_browse(state, actions, actions.new_draft())


def _review(state: _State, actions: InteractiveActions) -> None:
    assert state.draft is not None
    draft = state.draft
    if draft.scan is None:
        try:
            scan = actions.scan(draft)
        except AgentWorklogError as exc:
            state.error = _ErrorState(
                kind="report-source",
                title=f"Could not read {draft.harness} sessions",
                detail=str(exc),
            )
            state.screen = Screen.RECOVERABLE_ERROR
            return
        if scan.loaded_session_count == 0:
            if scan.excluded_session_count > 0:
                state.error = _ErrorState(
                    kind="report-empty",
                    title="Sessions excluded by configuration",
                    detail="All sessions matched by the selected harness and period "
                    "were excluded by configuration.",
                )
            else:
                state.error = _ErrorState(
                    kind="report-empty",
                    title="No sessions found",
                    detail="No activity matched the selected harness and period.",
                )
            state.screen = Screen.RECOVERABLE_ERROR
            return
        draft.set_scan(scan)
        restored = actions.restore_selection(
            draft.harness, draft.period, draft.include_subagents
        )
        if restored is not None:
            available = {item.session.session_id for item in scan.resolved_sessions}
            draft.selected_session_ids = restored & available
    cached_scan = draft.scan
    assert cached_scan is not None
    state.selection = SelectionState.from_scan(
        cached_scan,
        selected_session_ids=draft.selected_session_ids,
    )
    state.review_cursor = 0
    state.review_message = None
    valid_repositories = set(cached_scan.sessions_by_repository)
    state.expanded_repositories = state.expansions() & valid_repositories
    _reset_search(state)
    state.screen = Screen.SESSION_REVIEW


def _open_help(state: _State) -> None:
    state.help_return_screen = state.screen
    state.screen = Screen.HELP


def _main_key(state: _State, key: KeyPress, actions: InteractiveActions) -> None:
    options = main_menu_options()
    state.main_cursor = _move(state.main_cursor, key, len(options))
    if key.key is Key.ESCAPE or _char(key, "q"):
        state.screen = Screen.EXIT
        return
    if key.char in {"1", "2", "3", "4"}:
        state.main_cursor = int(key.char) - 1
        activate = True
    else:
        activate = key.key is Key.ENTER
    if not activate:
        return

    if state.main_cursor == 0:
        _new_report(state, actions)
    elif state.main_cursor == 1:
        _begin_browse(state, actions)
    elif state.main_cursor == 2:
        draft = actions.new_draft()
        try:
            lines = actions.doctor(draft.harness)
        except AgentWorklogError as exc:
            detail = f"ERROR: {exc}"
        else:
            detail = "\n".join(lines)
        state.error = _ErrorState(
            kind="doctor-result",
            title="Check Setup",
            detail=detail,
        )
        state.screen = Screen.RECOVERABLE_ERROR
    else:
        actions.edit_settings()
        state.error = _ErrorState(
            kind="settings-result",
            title="Settings",
            detail="Settings editor finished.",
        )
        state.screen = Screen.RECOVERABLE_ERROR


def _clear_expansions_if_scan_was_invalidated(
    state: _State,
    draft: ReportDraft,
    *,
    had_scan: bool,
) -> None:
    if had_scan and draft.scan is None:
        state.expanded_repositories = set()


def _edit_setup_field(state: _State, actions: InteractiveActions, *, field: str) -> None:
    assert state.draft is not None
    draft = state.draft
    had_scan = draft.scan is not None
    if field == "Harness":
        draft.set_harness(actions.choose_harness(draft.harness))
        if draft.harness != "opencode":
            draft.set_sanitize(False)
    elif field == "Period":
        draft.set_period(*actions.choose_period(draft.period_label))
    elif field == "Detail":
        detail = DetailLevel.BRIEF if draft.detail is DetailLevel.FULL else DetailLevel.FULL
        draft.set_detail(detail)
    elif field == "Subagents":
        draft.set_include_subagents(not draft.include_subagents)
    elif field == "Narrative":
        draft.set_narrative(not draft.narrative)
    elif field == "Sanitize":
        if draft.harness == "opencode":
            draft.set_sanitize(not draft.sanitize)
    elif field == "Dry run":
        draft.set_dry_run(not draft.dry_run)
    _clear_expansions_if_scan_was_invalidated(state, draft, had_scan=had_scan)


def _setup_key(state: _State, key: KeyPress, actions: InteractiveActions) -> None:
    rows = report_setup_rows()
    state.setup_cursor = _move(state.setup_cursor, key, len(rows))
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    if _char(key, "r"):
        _review(state, actions)
        return
    if _char(key, "g"):
        _generate_from_setup(state, actions)
        return
    row = rows[state.setup_cursor]
    if row == report_generate_row():
        # Generating writes a file, so the action row answers to Enter alone —
        # a stray left/right while scrolling the settings must not produce a report.
        if key.key is Key.ENTER:
            _generate_from_setup(state, actions)
        return
    horizontal_edit = key.key in {Key.LEFT, Key.RIGHT} or _char(key, "h") or _char(key, "l")
    if key.key is not Key.ENTER and not horizontal_edit:
        return
    _edit_setup_field(state, actions, field=row)


def _tree_rows(scan: ScanResult, state: _State) -> list:
    if state.search_query:
        return build_filtered_rows(scan, state.expansions(), query=state.search_query)
    return build_visible_rows(scan, state.expansions())


def _expand_tree_row(state: _State, rows: list, cursor_name: str) -> None:
    if not rows:
        return
    cursor = getattr(state, cursor_name)
    cursor = min(cursor, len(rows) - 1)
    row = rows[cursor]
    if row.kind == "repository":
        state.expansions().add(row.repository_id)


def _collapse_tree_row(state: _State, rows: list, cursor_name: str) -> None:
    if not rows:
        return
    cursor = min(getattr(state, cursor_name), len(rows) - 1)
    row = rows[cursor]
    expanded = state.expansions()
    if row.kind == "repository":
        expanded.discard(row.repository_id)
        return
    expanded.discard(row.repository_id)
    for index in range(cursor, -1, -1):
        candidate = rows[index]
        if candidate.kind == "repository" and candidate.repository_id == row.repository_id:
            setattr(state, cursor_name, index)
            return


def _search_input(state: _State, key: KeyPress, cursor_name: str) -> bool:
    if not state.searching:
        return False
    if key.key is Key.ESCAPE:
        _reset_search(state)
    elif key.key in {Key.BACKSPACE, Key.DELETE}:
        state.search_query = state.search_query[:-1]
    elif key.key is Key.ENTER:
        state.searching = False
    elif key.char is not None and key.char.isprintable():
        state.search_query += key.char
    else:
        return True
    setattr(state, cursor_name, 0)
    return True


def _begin_search(state: _State, cursor_name: str) -> None:
    state.search_query = ""
    state.searching = True
    setattr(state, cursor_name, 0)


def _session_by_id(scan: ScanResult, session_id: str) -> AgentSession | None:
    for item in scan.resolved_sessions:
        if item.session.session_id == session_id:
            return item.session
    return None


def _open_session_preview(
    state: _State,
    session: AgentSession,
    *,
    return_screen: Screen,
) -> None:
    state.preview_session = session
    state.preview_offset = 0
    state.preview_return_screen = return_screen
    state.screen = Screen.SESSION_PREVIEW


def _preview_from_row(
    state: _State,
    scan: ScanResult,
    rows: list,
    cursor_name: str,
    *,
    return_screen: Screen,
) -> bool:
    """Open the session preview when the cursor sits on a session row."""
    if not rows:
        return False
    cursor = min(getattr(state, cursor_name), len(rows) - 1)
    row = rows[cursor]
    if row.session_id is None:
        return False
    session = _session_by_id(scan, row.session_id)
    if session is None:
        return False
    _open_session_preview(state, session, return_screen=return_screen)
    return True


def _browser_key(state: _State, key: KeyPress, actions: InteractiveActions) -> None:
    assert state.browser_scan is not None
    if _search_input(state, key, "browser_cursor"):
        return
    if _exact_char(key, "/"):
        _begin_search(state, "browser_cursor")
        return
    if _exact_char(key, "R"):
        assert state.draft is not None
        _load_browse(state, actions, state.draft)
        return
    rows = _tree_rows(state.browser_scan, state)
    state.browser_cursor = _move(state.browser_cursor, key, len(rows))
    if _char(key, "q"):
        state.screen = Screen.MAIN
        return
    if key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    if _exact_char(key, "p"):
        _preview_from_row(
            state,
            state.browser_scan,
            rows,
            "browser_cursor",
            return_screen=Screen.SESSION_BROWSER,
        )
        return
    if key.key is Key.RIGHT or _char(key, "l"):
        _expand_tree_row(state, rows, "browser_cursor")
        return
    if key.key is Key.LEFT or _char(key, "h"):
        _collapse_tree_row(state, rows, "browser_cursor")
        return
    if key.key is not Key.ENTER or not rows:
        return
    row = rows[state.browser_cursor]
    if row.kind != "repository":
        return
    expanded = state.expansions()
    if row.repository_id in expanded:
        expanded.remove(row.repository_id)
    else:
        expanded.add(row.repository_id)
    visible_count = len(_tree_rows(state.browser_scan, state))
    state.browser_cursor = min(state.browser_cursor, max(0, visible_count - 1))


def _sync_selection(state: _State, actions: InteractiveActions) -> None:
    assert state.draft is not None
    assert state.selection is not None
    draft = state.draft
    selection = state.selection
    if set(draft.selected_session_ids) == selection.selected_session_ids:
        return
    draft.selected_session_ids = set(selection.selected_session_ids)
    # The state file is bookkeeping, like the history log: a full disk or
    # read-only home must not take the interactive app down. The selection
    # simply is not remembered.
    with contextlib.suppress(OSError, AgentWorklogError):
        actions.save_selection(
            draft.harness,
            draft.period,
            draft.include_subagents,
            draft.selected_session_ids,
        )


def _generate(state: _State, actions: InteractiveActions, *, force: bool) -> None:
    assert state.draft is not None
    assert state.selection is not None
    if state.selection.selected_count == 0:
        state.review_message = "Select at least one session before generating."
        state.screen = Screen.SESSION_REVIEW
        return
    _sync_selection(state, actions)
    filtered_scan = state.selection.filtered_scan()
    try:
        result = actions.generate(state.draft, filtered_scan, force)
    except ReportAlreadyExistsError as exc:
        state.error = _ErrorState(
            kind="report-output-conflict",
            title="Could not write report",
            detail=str(exc),
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    except ReportOutputError as exc:
        state.error = _ErrorState(
            kind="report-output",
            title="Could not write report",
            detail=str(exc),
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    except AgentWorklogError as exc:
        state.error = _ErrorState(
            kind="report-generate",
            title="Could not generate report",
            detail=str(exc),
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    state.result = result
    state.result_cursor = 0
    state.preview_offset = 0
    state.review_message = None
    state.error = None
    state.screen = Screen.REPORT_RESULT


def _generate_from_setup(state: _State, actions: InteractiveActions) -> None:
    """Scan the way Review does, then generate against the selection it built.

    `_generate` needs `state.selection`, which only `_review` establishes, and
    `_review` is also what surfaces a failed or empty scan. Reusing it means
    generating from here cannot reach a state that reviewing first could not.
    """
    _review(state, actions)
    if state.screen is not Screen.SESSION_REVIEW:
        return
    _generate(state, actions, force=False)


def _rescan_review(state: _State, actions: InteractiveActions) -> None:
    assert state.draft is not None
    assert state.selection is not None
    selected = set(state.selection.selected_session_ids)
    state.draft.scan = None
    _review(state, actions)
    if state.screen is not Screen.SESSION_REVIEW or state.selection is None:
        return
    available = {
        item.session.session_id for item in state.selection.scan.resolved_sessions
    }
    state.selection.selected_session_ids = selected & available
    _sync_selection(state, actions)


def _review_key(state: _State, key: KeyPress, actions: InteractiveActions) -> None:
    assert state.draft is not None
    assert state.selection is not None
    if _search_input(state, key, "review_cursor"):
        return
    if _exact_char(key, "/"):
        _begin_search(state, "review_cursor")
        return
    if _exact_char(key, "R"):
        _rescan_review(state, actions)
        return
    rows = _tree_rows(state.selection.scan, state)
    state.review_cursor = _move(state.review_cursor, key, len(rows))
    if _char(key, "q"):
        _sync_selection(state, actions)
        state.screen = Screen.MAIN
        return
    if key.key is Key.ESCAPE or _char(key, "b"):
        _sync_selection(state, actions)
        state.screen = Screen.REPORT_SETUP
        return
    if key.key is Key.RIGHT or _char(key, "l"):
        _expand_tree_row(state, rows, "review_cursor")
        return
    if key.key is Key.LEFT or _char(key, "h"):
        _collapse_tree_row(state, rows, "review_cursor")
        return
    if _char(key, "a"):
        state.selection.select_all()
        _sync_selection(state, actions)
        state.review_message = None
        return
    if _char(key, "n"):
        state.selection.select_none()
        _sync_selection(state, actions)
        state.review_message = None
        return
    if _exact_char(key, "g"):
        _generate(state, actions, force=False)
        return
    if _exact_char(key, "p"):
        _preview_from_row(
            state,
            state.selection.scan,
            rows,
            "review_cursor",
            return_screen=Screen.SESSION_REVIEW,
        )
        return
    if _exact_char(key, "e") and rows:
        row = rows[state.review_cursor]
        if row.kind == "repository":
            try:
                message = actions.exclude_repository(
                    row.repository_id,
                    state.selection.scan.sessions_by_repository[row.repository_id][0]
                    .repository.display_name,
                )
            except AgentWorklogError as exc:
                state.error = _ErrorState(
                    kind="report-source",
                    title="Could not exclude repository",
                    detail=str(exc),
                )
                state.screen = Screen.RECOVERABLE_ERROR
                return
            _rescan_review(state, actions)
            if state.screen is Screen.SESSION_REVIEW:
                state.review_message = message
        return
    if key.key is Key.SPACE and rows:
        row = rows[state.review_cursor]
        if row.kind == "repository":
            state.selection.toggle_repository(row.repository_id)
        else:
            assert row.session_id is not None
            state.selection.toggle_session(row.session_id)
        _sync_selection(state, actions)
        state.review_message = None
        return
    if key.key is Key.ENTER and rows:
        row = rows[state.review_cursor]
        if row.kind == "repository":
            expanded = state.expansions()
            if row.repository_id in expanded:
                expanded.remove(row.repository_id)
            else:
                expanded.add(row.repository_id)
            state.review_cursor = min(
                state.review_cursor,
                max(0, len(_tree_rows(state.selection.scan, state)) - 1),
            )


def _error_options(error: _ErrorState) -> list[str]:
    if error.kind in {"doctor-result", "settings-result"}:
        return ["Main menu"]
    if error.kind == "report-path":
        return ["Back"]
    if error.kind in {"report-empty", "browse-empty"}:
        return ["Change period", "Change harness", "Back", "Main menu"]
    if error.kind == "report-output-conflict":
        return ["Overwrite once", "Back", "Main menu"]
    if error.kind in {"report-output", "report-generate"}:
        return ["Back", "Main menu"]
    return ["Change harness", "Back", "Main menu"]


def _error_back_screen(error: _ErrorState) -> Screen:
    if error.kind == "report-path":
        return Screen.REPORT_RESULT
    if error.kind in {"doctor-result", "settings-result"}:
        return Screen.MAIN
    if error.kind in {"report-output-conflict", "report-output", "report-generate"}:
        return Screen.SESSION_REVIEW
    if error.kind.startswith("report"):
        return Screen.REPORT_SETUP
    return Screen.MAIN


def _scroll_error_detail(error: _ErrorState, key: KeyPress, console: Console) -> bool:
    lines = error.detail.splitlines() or [""]
    capacity = recoverable_error_detail_capacity(
        console.size.height, len(_error_options(error)), console.size.width
    )
    page = max(1, capacity)
    max_offset = max(0, len(lines) - 1)
    if key.key is Key.PAGE_UP:
        error.detail_offset = max(0, error.detail_offset - page)
    elif key.key is Key.PAGE_DOWN:
        error.detail_offset = min(max_offset, error.detail_offset + page)
    elif key.key is Key.HOME:
        error.detail_offset = 0
    elif key.key is Key.END:
        error.detail_offset = max_offset
    else:
        return False
    return True


def _error_key(
    state: _State,
    key: KeyPress,
    actions: InteractiveActions,
    console: Console,
) -> None:
    assert state.error is not None
    error = state.error
    if _scroll_error_detail(error, key, console):
        return
    options = _error_options(error)
    error.selected = _move(error.selected, key, len(options))
    if _char(key, "q"):
        state.screen = Screen.MAIN
        return
    if key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = _error_back_screen(error)
        return
    if key.key is not Key.ENTER:
        return

    choice = options[error.selected]
    if choice == "Main menu":
        state.screen = Screen.MAIN
        return
    if choice == "Back":
        state.screen = _error_back_screen(error)
        return
    if choice == "Overwrite once":
        _generate(state, actions, force=True)
        return
    assert state.draft is not None
    if choice == "Change harness":
        state.draft.set_harness(actions.choose_harness(state.draft.harness))
        if state.draft.harness != "opencode":
            state.draft.set_sanitize(False)
    else:
        state.draft.set_period(*actions.choose_period(state.draft.period_label))
    state.selection = None
    if error.kind.startswith("browse"):
        _load_browse(state, actions, state.draft)
    else:
        state.error = None
        state.expanded_repositories = set()
        state.screen = Screen.REPORT_SETUP


def _result_key(state: _State, key: KeyPress) -> None:
    assert state.draft is not None
    assert state.result is not None
    options = report_result_options(dry_run=state.draft.dry_run)
    state.result_cursor = _move(state.result_cursor, key, len(options))
    if key.key is Key.ESCAPE or _char(key, "q") or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    if key.key is not Key.ENTER:
        return

    choice = options[state.result_cursor]
    if choice == "Preview report":
        state.preview_offset = 0
        state.screen = Screen.REPORT_PREVIEW
    elif choice == "Back to main menu":
        state.screen = Screen.MAIN
    elif choice == "Generate another report":
        state.draft.clear_scan()
        state.selection = None
        state.result = None
        state.error = None
        state.review_message = None
        state.setup_cursor = 0
        state.preview_offset = 0
        state.expanded_repositories = set()
        _reset_search(state)
        state.screen = Screen.REPORT_SETUP
    else:
        detail = (
            str(state.result.output_path)
            if state.result.output_path is not None
            else "Dry run has no output path."
        )
        state.error = _ErrorState(
            kind="report-path",
            title="Report path",
            detail=detail,
        )
        state.screen = Screen.RECOVERABLE_ERROR


def _preview_key(state: _State, key: KeyPress, console: Console) -> None:
    assert state.result is not None
    if _char(key, "q"):
        state.screen = Screen.MAIN
        return
    if key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.REPORT_RESULT
        return
    lines = state.result.content.splitlines() or [""]
    capacity = report_preview_capacity(console.size.height)
    max_offset = max(0, len(lines) - capacity) if capacity else max(0, len(lines) - 1)
    page = max(1, capacity)
    if key.key is Key.UP or _char(key, "k"):
        state.preview_offset = max(0, state.preview_offset - 1)
    elif key.key is Key.DOWN or _char(key, "j"):
        state.preview_offset = min(max_offset, state.preview_offset + 1)
    elif key.key is Key.PAGE_UP:
        state.preview_offset = max(0, state.preview_offset - page)
    elif key.key is Key.PAGE_DOWN:
        state.preview_offset = min(max_offset, state.preview_offset + page)
    elif key.key is Key.HOME or _exact_char(key, "g"):
        state.preview_offset = 0
    elif key.key is Key.END or _exact_char(key, "G"):
        state.preview_offset = max_offset


def _session_preview_key(state: _State, key: KeyPress, console: Console) -> None:
    assert state.preview_session is not None
    if _char(key, "q"):
        state.screen = Screen.MAIN
        return
    if key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = state.preview_return_screen or Screen.MAIN
        return
    lines = build_session_preview_lines(state.preview_session) or [""]
    capacity = report_preview_capacity(console.size.height)
    max_offset = max(0, len(lines) - capacity) if capacity else max(0, len(lines) - 1)
    page = max(1, capacity)
    if key.key is Key.UP or _char(key, "k"):
        state.preview_offset = max(0, state.preview_offset - 1)
    elif key.key is Key.DOWN or _char(key, "j"):
        state.preview_offset = min(max_offset, state.preview_offset + 1)
    elif key.key is Key.PAGE_UP:
        state.preview_offset = max(0, state.preview_offset - page)
    elif key.key is Key.PAGE_DOWN:
        state.preview_offset = min(max_offset, state.preview_offset + page)
    elif key.key is Key.HOME or _exact_char(key, "g"):
        state.preview_offset = 0
    elif key.key is Key.END or _exact_char(key, "G"):
        state.preview_offset = max_offset


def _help_key(state: _State, key: KeyPress) -> None:
    if _char(key, "q"):
        state.screen = Screen.MAIN
        return
    if key.key in {Key.ESCAPE, Key.ENTER} or _char(key, "b") or _exact_char(key, "?"):
        state.screen = state.help_return_screen or Screen.MAIN
        state.help_return_screen = None


def _render_screen(state: _State, console: Console) -> None:
    if state.screen is Screen.MAIN:
        render_main_menu(console, selected=state.main_cursor)
    elif state.screen is Screen.REPORT_SETUP:
        assert state.draft is not None
        render_report_setup(console, state.draft, selected=state.setup_cursor)
    elif state.screen is Screen.SESSION_BROWSER:
        assert state.browser_scan is not None
        render_session_browser(
            console,
            state.browser_scan,
            expanded_repositories=state.expansions(),
            cursor=state.browser_cursor,
            query=state.search_query,
            searching=state.searching,
        )
    elif state.screen is Screen.SESSION_REVIEW:
        assert state.selection is not None
        render_session_review(
            console,
            state.selection,
            expanded_repositories=state.expansions(),
            cursor=state.review_cursor,
            message=state.review_message,
            query=state.search_query,
            searching=state.searching,
        )
    elif state.screen is Screen.SESSION_PREVIEW:
        assert state.preview_session is not None
        render_session_preview(
            console,
            state.preview_session,
            offset=state.preview_offset,
        )
    elif state.screen is Screen.REPORT_RESULT:
        assert state.draft is not None
        assert state.result is not None
        render_report_result(
            console,
            period=state.draft.period,
            repository_count=state.result.repository_count,
            session_count=state.result.session_count,
            output_path=state.result.output_path,
            selected=state.result_cursor,
            dry_run=state.draft.dry_run,
        )
    elif state.screen is Screen.REPORT_PREVIEW:
        assert state.result is not None
        render_report_preview(
            console,
            content=state.result.content,
            offset=state.preview_offset,
        )
    elif state.screen is Screen.RECOVERABLE_ERROR:
        assert state.error is not None
        render_recoverable_error(
            console,
            title=state.error.title,
            detail=state.error.detail,
            options=_error_options(state.error),
            selected=state.error.selected,
            detail_offset=state.error.detail_offset,
        )
    elif state.screen is Screen.HELP:
        render_help(console)


def _idle_interrupt(state: _State, actions: InteractiveActions) -> None:
    """Treat Ctrl-C while waiting for a key like the screen's normal Back action."""

    if state.screen is Screen.MAIN:
        state.screen = Screen.EXIT
    elif state.screen in {Screen.REPORT_SETUP, Screen.SESSION_BROWSER}:
        state.screen = Screen.MAIN
    elif state.screen is Screen.SESSION_REVIEW:
        if state.selection is not None and state.draft is not None:
            _sync_selection(state, actions)
        state.screen = Screen.REPORT_SETUP
    elif state.screen is Screen.REPORT_RESULT:
        state.screen = Screen.MAIN
    elif state.screen is Screen.REPORT_PREVIEW:
        state.screen = Screen.REPORT_RESULT
    elif state.screen is Screen.SESSION_PREVIEW:
        state.screen = state.preview_return_screen or Screen.MAIN
    elif state.screen is Screen.RECOVERABLE_ERROR and state.error is not None:
        state.screen = _error_back_screen(state.error)
    elif state.screen is Screen.HELP:
        state.screen = state.help_return_screen or Screen.MAIN
        state.help_return_screen = None


def _dispatch(
    state: _State,
    key: KeyPress,
    actions: InteractiveActions,
    console: Console,
) -> None:
    if _exact_char(key, "?") and state.screen is not Screen.HELP:
        _open_help(state)
        return
    if state.screen is Screen.MAIN:
        _main_key(state, key, actions)
    elif state.screen is Screen.REPORT_SETUP:
        _setup_key(state, key, actions)
    elif state.screen is Screen.SESSION_BROWSER:
        _browser_key(state, key, actions)
    elif state.screen is Screen.SESSION_REVIEW:
        _review_key(state, key, actions)
    elif state.screen is Screen.REPORT_RESULT:
        _result_key(state, key)
    elif state.screen is Screen.REPORT_PREVIEW:
        _preview_key(state, key, console)
    elif state.screen is Screen.SESSION_PREVIEW:
        _session_preview_key(state, key, console)
    elif state.screen is Screen.RECOVERABLE_ERROR:
        _error_key(state, key, actions, console)
    elif state.screen is Screen.HELP:
        _help_key(state, key)


def _render(
    state: _State,
    console: Console,
    previous: list[str] | None,
) -> list[str] | None:
    """Paint the current screen over the last one, or print it plain off a TTY."""

    if not console.is_terminal:
        _render_screen(state, console)
        return None
    with console.capture() as capture:
        _render_screen(state, console)
    return _paint(console, capture.get(), previous)


def run_interactive(
    *,
    actions: InteractiveActions,
    input_source: KeySource,
    console: Console,
) -> None:
    """Run the terminal interaction until the user explicitly leaves it."""

    state = _State()
    previous_frame: list[str] | None = None
    while state.screen is not Screen.EXIT:
        previous_frame = _render(state, console, previous_frame)
        try:
            key = _read_key(input_source)
        except KeyboardInterrupt:
            _idle_interrupt(state, actions)
            continue
        origin = state.screen
        try:
            _dispatch(state, key, actions, console)
        except (KeyboardInterrupt, typer.Abort):
            # Actions run outside terminal cbreak mode. Cancelling a scan, report
            # generation, or typed legacy settings editor returns to the screen
            # that launched it instead of terminating the whole interactive app.
            state.screen = origin
