"""State-machine controller for the terminal-native Iiwi experience."""

from __future__ import annotations

import contextlib
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self

import typer
from rich.console import Console
from rich.text import Text

from iiwi import config_store
from iiwi.errors import (
    ConfigurationError,
    DailySourceUnavailableError,
    IiwiError,
    OutcomeSynthesisError,
    ReportAlreadyExistsError,
    ReportOutputError,
)
from iiwi.history import HistoryEntry, read_history
from iiwi.interactive.daily_review import (
    TODAY_MORE_SECTION,
    YESTERDAY_MORE_SECTION,
    DailyReviewRow,
    visible_daily_review_rows,
)
from iiwi.interactive.input import Key, KeyPress
from iiwi.interactive.models import ReportDraft, Screen
from iiwi.interactive.render import (
    MORE_CANDIDATES_SECTION,
    UNGROUPED_CANDIDATES_SECTION,
    OutcomeReviewRow,
    build_filtered_rows,
    build_session_preview_lines,
    build_visible_rows,
    daily_result_options,
    help_capacity,
    help_lines,
    history_capacity,
    main_menu_options,
    recoverable_error_detail_capacity,
    render_daily_result,
    render_daily_review,
    render_help,
    render_history,
    render_history_preview,
    render_main_menu,
    render_outcome_review,
    render_recoverable_error,
    render_report_preview,
    render_report_result,
    render_report_setup,
    render_session_preview,
    render_session_review,
    render_settings,
    report_generate_row,
    report_preview_capacity,
    report_result_options,
    report_setup_rows,
    settings_capacity,
    settings_display_offset,
    visible_outcome_review_rows,
)
from iiwi.interactive.selection import SelectionState
from iiwi.interactive.settings import (
    SettingsRow,
    build_settings_rows,
    next_choice,
    write_setting,
)
from iiwi.models.daily import DailySection, DailyStandupDraft
from iiwi.models.outcome import Outcome, OutcomeReviewDraft
from iiwi.models.report_options import ReportType
from iiwi.models.session import AgentSession
from iiwi.models.time_range import DateRange
from iiwi.renderers.markdown import DetailLevel
from iiwi.services.outcomes import SynthesisBudgetExceededError
from iiwi.services.scan import ScanResult

_ADVANCED_ROW = "Advanced settings"
_SESSION_FALLBACK_NOTICE = "Outcome synthesis unavailable; generated the session-based report."


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


def _daily_start_not_configured(
    previous: DailyStandupDraft | None,
) -> DailyStandupDraft:
    raise NotImplementedError("Daily Standup actions are not configured")


def _daily_continue_not_configured(
    error: DailySourceUnavailableError,
    previous: DailyStandupDraft | None,
) -> DailyStandupDraft:
    raise NotImplementedError("Daily Standup actions are not configured")


def _daily_persist_not_configured(draft: DailyStandupDraft) -> str | None:
    return "Daily Standup state persistence is not configured."


def _daily_report_not_configured(
    draft: DailyStandupDraft,
) -> InteractiveReportResult:
    raise NotImplementedError("Daily Standup actions are not configured")


def _daily_edit_not_configured(statement: str) -> str | None:
    return None


def _daily_add_not_configured(section: DailySection) -> str | None:
    return None


@dataclass(frozen=True)
class InteractiveActions:
    """Business-logic seams supplied by `cli.py`, keeping this module cycle-free."""

    new_draft: Callable[[], ReportDraft]
    choose_harness: Callable[[str], str]
    choose_period: Callable[[str | None], tuple[str, DateRange]]
    scan: Callable[[ReportDraft], ScanResult]
    generate: Callable[[ReportDraft, ScanResult, bool], InteractiveReportResult]
    synthesize: Callable[[ReportDraft, ScanResult, bool], OutcomeReviewDraft]
    generate_reviewed: Callable[
        [ReportDraft, ScanResult, OutcomeReviewDraft, bool],
        InteractiveReportResult,
    ]
    edit_outcome: Callable[[Outcome], Outcome]
    add_outcome: Callable[[], Outcome | None]
    edit_gap: Callable[[str, str | None], str | None]
    save_report_type: Callable[[ReportType], None]
    doctor: Callable[[str], list[str]]
    restore_selection: Callable[[str, DateRange, bool], set[str] | None]
    save_selection: Callable[[str, DateRange, bool, set[str]], None]
    exclude_repository: Callable[[str, str], str]
    start_daily: Callable[[DailyStandupDraft | None], DailyStandupDraft] = (
        _daily_start_not_configured
    )
    continue_daily_empty: Callable[
        [DailySourceUnavailableError, DailyStandupDraft | None], DailyStandupDraft
    ] = _daily_continue_not_configured
    persist_daily: Callable[[DailyStandupDraft], str | None] = _daily_persist_not_configured
    preview_daily: Callable[[DailyStandupDraft], InteractiveReportResult] = (
        _daily_report_not_configured
    )
    generate_daily: Callable[[DailyStandupDraft], InteractiveReportResult] = (
        _daily_report_not_configured
    )
    edit_daily_statement: Callable[[str], str | None] = _daily_edit_not_configured
    add_daily_statement: Callable[[DailySection], str | None] = _daily_add_not_configured


@dataclass
class _ErrorState:
    kind: str
    title: str
    detail: str
    retry: str | None = None
    selected: int = 0
    detail_offset: int = 0
    daily_source_error: DailySourceUnavailableError | None = None
    # Screen the error was raised from. Set only by raisers that can fire from
    # more than one screen; _error_back_screen falls back to the kind prefix.
    back: Screen | None = None


@dataclass
class _State:
    screen: Screen = Screen.MAIN
    main_cursor: int = 0
    setup_cursor: int = 0
    setup_advanced: bool = False
    review_cursor: int = 0
    result_cursor: int = 0
    history_cursor: int = 0
    history_offset: int = 0
    history_show_missing: bool = False
    history_preview_entry: HistoryEntry | None = None
    history_preview_offset: int = 0
    preview_offset: int = 0
    draft: ReportDraft | None = None
    selection: SelectionState | None = None
    result: InteractiveReportResult | None = None
    expanded_repositories: set[str] | None = None
    preview_session: AgentSession | None = None
    session_preview_offset: int = 0
    preview_return_screen: Screen | None = None
    error: _ErrorState | None = None
    review_message: str | None = None
    review_from_main: bool = False
    outcome_review: OutcomeReviewDraft | None = None
    outcome_review_selection_key: tuple[tuple[str, ...], DetailLevel] | None = None
    outcome_cursor: int = 0
    outcome_message: str | None = None
    expanded_evidence: set[str] | None = None
    daily_review: DailyStandupDraft | None = None
    daily_cursor: int = 0
    daily_message: str | None = None
    daily_expanded: set[str] | None = None
    daily_result: InteractiveReportResult | None = None
    daily_result_cursor: int = 0
    search_query: str = ""
    searching: bool = False
    help_return_screen: Screen | None = None
    help_offset: int = 0
    settings_rows: list[SettingsRow] | None = None
    settings_cursor: int = 0
    settings_offset: int = 0
    settings_editing: bool = False
    settings_edit_value: str = ""
    settings_error: str | None = None
    settings_file_path: str | None = None

    def expansions(self) -> set[str]:
        if self.expanded_repositories is None:
            self.expanded_repositories = set()
        return self.expanded_repositories

    def evidence_expansions(self) -> set[str]:
        if self.expanded_evidence is None:
            self.expanded_evidence = set()
        return self.expanded_evidence

    def daily_expansions(self) -> set[str]:
        if self.daily_expanded is None:
            self.daily_expanded = set()
        return self.daily_expanded


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


def _paint_pending(state: _State, console: Console, message: str) -> None:
    """Paint the current frame plus one dim progress line before a long op blocks.

    Handlers assign their status message before the blocking action runs, but
    that message only reaches the screen on the next loop iteration — minutes
    later. Painting here gives immediate feedback, and the next regular paint's
    erase-below removes the line once the action returns.
    """

    line = f"⏳ {message}  (Ctrl-C to cancel)"
    if not console.is_terminal:
        _render_screen(state, console)
        console.print(Text(line, style="dim"))
        return
    with console.capture() as capture:
        _render_screen(state, console)
        console.print(Text(line, style="dim"))
    # previous=None forces one absolute-positioned repaint: the pending line
    # lands below the frame rows, where the next cycle's erase-below finds it.
    _paint(console, capture.get(), None)


def _reset_search(state: _State) -> None:
    state.search_query = ""
    state.searching = False


def _clear_outcome_review(state: _State) -> None:
    state.outcome_review = None
    state.outcome_review_selection_key = None
    state.outcome_cursor = 0
    state.outcome_message = None
    state.expanded_evidence = set()


def _new_report(state: _State, actions: InteractiveActions) -> None:
    try:
        draft = actions.new_draft()
    except IiwiError as exc:
        # new_draft resolves the default harness before any scan runs, so
        # ConfigurationError (e.g. no harness available) reaches here on an
        # unusable config. Every other menu entry shows that as a recoverable
        # error rather than letting it escape _dispatch and kill the app.
        # Not "report-start": _error_back_screen routes any kind starting
        # with "report" to REPORT_SETUP, which asserts state.draft is not
        # None on render — exactly the state this failure leaves it in.
        state.error = _ErrorState(
            kind="new-report-start",
            title="Could not start report",
            detail=str(exc),
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    state.draft = draft
    state.setup_cursor = 0
    state.setup_advanced = False
    state.selection = None
    state.result = None
    state.error = None
    state.review_message = None
    state.review_from_main = False
    _clear_outcome_review(state)
    state.preview_offset = 0
    state.session_preview_offset = 0
    state.preview_return_screen = None
    state.expanded_repositories = set()
    _reset_search(state)
    state.screen = Screen.REPORT_SETUP


def _load_activity(
    state: _State,
    actions: InteractiveActions,
    draft: ReportDraft,
) -> None:
    """Load configured activity into the same selectable tree used by reports."""

    _clear_outcome_review(state)
    state.draft = draft
    try:
        scan = actions.scan(draft)
    except IiwiError as exc:
        state.error = _ErrorState(
            kind="activity-source",
            title=f"Could not read {draft.harness} sessions",
            detail=str(exc),
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    if scan.loaded_session_count == 0:
        if scan.excluded_session_count > 0:
            state.error = _ErrorState(
                kind="activity-empty",
                title="Sessions excluded by configuration",
                detail="All sessions matched by the selected harness and period "
                "were excluded by configuration.",
            )
        else:
            state.error = _ErrorState(
                kind="activity-empty",
                title="No sessions found",
                detail="No activity matched the selected harness and period.",
            )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    draft.set_scan(scan)
    restored = actions.restore_selection(draft.harness, draft.period, draft.include_subagents)
    if restored is not None:
        available = {item.session.session_id for item in scan.resolved_sessions}
        draft.selected_session_ids = restored & available
    state.selection = SelectionState.from_scan(
        scan,
        selected_session_ids=draft.selected_session_ids,
    )
    state.review_cursor = 0
    state.review_message = None
    state.review_from_main = True
    state.error = None
    state.expanded_repositories = set()
    _reset_search(state)
    state.screen = Screen.SESSION_REVIEW


def _begin_activity_review(state: _State, actions: InteractiveActions) -> None:
    """Open the unified activity review with configured defaults."""

    try:
        draft = actions.new_draft()
    except IiwiError as exc:
        # new_draft resolves the default harness before any scan runs, so
        # ConfigurationError (e.g. no harness available) reaches here on an
        # unusable config. Every other menu entry shows that as a recoverable
        # error rather than letting it escape _dispatch and kill the app.
        state.error = _ErrorState(
            kind="activity-start",
            title="Could not start Review Activity",
            detail=str(exc),
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    _load_activity(state, actions, draft)


def _scan_for_review(state: _State, actions: InteractiveActions) -> ScanResult | None:
    """Run actions.scan, routing failures to the report-source error screen."""

    assert state.draft is not None
    draft = state.draft
    # A failed rescan interrupts Session Review itself: Back mirrors where the
    # review's own Back key goes rather than always assuming Report Setup.
    back = state.screen if state.review_from_main else Screen.REPORT_SETUP
    try:
        scan = actions.scan(draft)
    except IiwiError as exc:
        state.error = _ErrorState(
            kind="report-source",
            title=f"Could not read {draft.harness} sessions",
            detail=str(exc),
            back=back,
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return None
    if scan.loaded_session_count == 0:
        if scan.excluded_session_count > 0:
            state.error = _ErrorState(
                kind="report-empty",
                title="Sessions excluded by configuration",
                detail="All sessions matched by the selected harness and period "
                "were excluded by configuration.",
                back=back,
            )
        else:
            state.error = _ErrorState(
                kind="report-empty",
                title="No sessions found",
                detail="No activity matched the selected harness and period.",
                back=back,
            )
        state.screen = Screen.RECOVERABLE_ERROR
        return None
    return scan


def _review(state: _State, actions: InteractiveActions) -> None:
    assert state.draft is not None
    draft = state.draft
    if draft.scan is None:
        scan = _scan_for_review(state, actions)
        if scan is None:
            return
        draft.set_scan(scan)
    _finish_review_selection(state, actions, None)


def _finish_review_selection(
    state: _State,
    actions: InteractiveActions,
    previously_selected: set[str] | None,
) -> None:
    """Rebuild the review selection from draft.scan.

    previously_selected carries a rescan's pre-scan selection: it wins over the
    rebuilt one, intersected with what the new scan still offers. Callers that
    only opened the review pass None and leave the restored selection in place.
    """

    assert state.draft is not None
    draft = state.draft
    scan = draft.scan
    assert scan is not None
    restored = actions.restore_selection(draft.harness, draft.period, draft.include_subagents)
    if restored is not None:
        available = {item.session.session_id for item in scan.resolved_sessions}
        draft.selected_session_ids = restored & available
    state.selection = SelectionState.from_scan(
        scan,
        selected_session_ids=draft.selected_session_ids,
    )
    state.review_cursor = 0
    state.review_message = None
    valid_repositories = set(scan.sessions_by_repository)
    state.expanded_repositories = state.expansions() & valid_repositories
    _reset_search(state)
    state.screen = Screen.SESSION_REVIEW
    if previously_selected is not None:
        available = {item.session.session_id for item in scan.resolved_sessions}
        state.selection.selected_session_ids = previously_selected & available
        _sync_selection(state, actions)


def _open_help(state: _State) -> None:
    state.help_return_screen = state.screen
    state.help_offset = 0
    state.screen = Screen.HELP


def _main_key(
    state: _State,
    key: KeyPress,
    actions: InteractiveActions,
    console: Console,
) -> None:
    options = main_menu_options()
    state.main_cursor = _move(state.main_cursor, key, len(options))
    if key.key is Key.ESCAPE or _char(key, "q"):
        state.screen = Screen.EXIT
        return
    if key.char in {"1", "2", "3", "4", "5", "6"}:
        state.main_cursor = int(key.char) - 1
        activate = True
    else:
        activate = key.key is Key.ENTER
    if not activate:
        return

    if state.main_cursor == 0:
        _begin_activity_review(state, actions)
    elif state.main_cursor == 1:
        _begin_daily_review(state, actions, console)
    elif state.main_cursor == 2:
        _new_report(state, actions)
    elif state.main_cursor == 3:
        state.history_cursor = 0
        state.history_offset = 0
        state.screen = Screen.HISTORY
    elif state.main_cursor == 4:
        try:
            draft = actions.new_draft()
            lines = actions.doctor(draft.harness)
        except IiwiError as exc:
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
        state.settings_rows = build_settings_rows()
        state.settings_cursor = 0
        state.settings_offset = 0
        state.settings_editing = False
        state.settings_edit_value = ""
        state.settings_error = None
        state.settings_file_path = str(config_store.config_file_path())
        state.screen = Screen.SETTINGS


def _clear_expansions_if_scan_was_invalidated(
    state: _State,
    draft: ReportDraft,
    *,
    had_scan: bool,
) -> None:
    if had_scan and draft.scan is None:
        state.expanded_repositories = set()
        _clear_outcome_review(state)


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
    _clear_expansions_if_scan_was_invalidated(state, draft, had_scan=had_scan)


def _setup_key(
    state: _State,
    key: KeyPress,
    actions: InteractiveActions,
    console: Console,
) -> None:
    rows = report_setup_rows(advanced=state.setup_advanced)
    state.setup_cursor = _move(state.setup_cursor, key, len(rows))
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    if _char(key, "r"):
        assert state.draft is not None
        state.draft.set_dry_run(False)
        state.review_from_main = False
        _review(state, actions)
        return
    if _char(key, "g"):
        _generate_from_setup(state, actions, console)
        return
    row = rows[state.setup_cursor]
    if row == report_generate_row():
        # Actions answer to Enter alone. Left/right remains reserved for changing
        # settings, so scrolling across an action can never execute it by accident.
        if key.key is Key.ENTER:
            _generate_from_setup(state, actions, console)
        return
    horizontal_edit = key.key in {Key.LEFT, Key.RIGHT} or _char(key, "h") or _char(key, "l")
    if key.key is not Key.ENTER and not horizontal_edit:
        return
    if row == _ADVANCED_ROW:
        advanced_index = rows.index(_ADVANCED_ROW)
        state.setup_advanced = not state.setup_advanced
        if not state.setup_advanced:
            state.setup_cursor = min(state.setup_cursor, advanced_index)
        return
    _edit_setup_field(state, actions, field=row)


def _persist_setting(state: _State, key: str, value: str) -> None:
    """Write one setting through config_store and refresh the rows on success."""

    try:
        write_setting(key, value)
    except ConfigurationError as exc:
        state.settings_error = str(exc)
        return
    state.settings_error = None
    state.settings_rows = build_settings_rows()


def _settings_edit_key(state: _State, key: KeyPress) -> None:
    """The inline editor: type, backspace, Enter writes, Esc cancels."""

    assert state.settings_rows is not None
    if key.key is Key.ESCAPE:
        state.settings_editing = False
        state.settings_edit_value = ""
        state.settings_error = None
        return
    if key.key in {Key.BACKSPACE, Key.DELETE}:
        state.settings_edit_value = state.settings_edit_value[:-1]
        return
    if key.key is Key.ENTER:
        row = state.settings_rows[state.settings_cursor]
        _persist_setting(state, row.key, state.settings_edit_value.strip())
        if state.settings_error is None:
            state.settings_editing = False
            state.settings_edit_value = ""
        return
    if key.key is Key.SPACE:
        state.settings_edit_value += " "
        return
    if key.char is not None:
        state.settings_edit_value += key.char


def _settings_key(state: _State, key: KeyPress, console: Console) -> None:
    """The saved-settings editor: cycle choices, edit rows inline, b leaves."""

    assert state.settings_rows is not None
    if state.settings_editing:
        _settings_edit_key(state, key)
        return
    state.settings_cursor = _move(state.settings_cursor, key, len(state.settings_rows))
    if key.key is Key.ESCAPE or _char(key, "b") or _char(key, "q"):
        state.screen = Screen.MAIN
        return
    state.settings_offset = settings_display_offset(
        state.settings_rows,
        state.settings_cursor,
        offset=state.settings_offset,
        capacity=settings_capacity(
            console.size.height,
            editing=state.settings_editing,
            terminal_width=console.size.width,
        ),
    )
    row = state.settings_rows[state.settings_cursor]
    if row.locked or row.disabled_reason:
        return
    right = key.key is Key.RIGHT or _char(key, "l")
    left = key.key is Key.LEFT or _char(key, "h")
    if (right or left) and row.choices:
        value = next_choice(row, row.value, right=right)
        if value != row.value:
            _persist_setting(state, row.key, value)
        return
    if key.key is Key.ENTER and row.editable:
        state.settings_editing = True
        state.settings_edit_value = row.value
        state.settings_error = None


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
    elif key.key is Key.SPACE:
        state.search_query += " "
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
    state.session_preview_offset = 0
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
    with contextlib.suppress(OSError, IiwiError):
        actions.save_selection(
            draft.harness,
            draft.period,
            draft.include_subagents,
            draft.selected_session_ids,
        )


def _generate(
    state: _State,
    actions: InteractiveActions,
    console: Console,
    *,
    force: bool,
) -> None:
    assert state.draft is not None
    assert state.selection is not None
    if state.selection.selected_count == 0:
        state.review_message = "Select at least one session before generating."
        state.screen = Screen.SESSION_REVIEW
        return
    _sync_selection(state, actions)
    filtered_scan = state.selection.filtered_scan()
    _paint_pending(state, console, "Generating report…")
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
    except IiwiError as exc:
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
    # The generation notice is scoped to this attempt: cli_actions injected it
    # as an initial warning here, so consuming it now keeps a failed earlier
    # attempt from leaking its notice into this and every later generate.
    state.draft.generation_notice = None
    state.screen = Screen.REPORT_RESULT


def _generate_from_setup(
    state: _State,
    actions: InteractiveActions,
    console: Console,
) -> None:
    """Route the setup action to Quick Review before writing output."""
    assert state.draft is not None
    state.review_from_main = False
    _review(state, actions)
    if state.screen is Screen.SESSION_REVIEW:
        _begin_outcome_review(state, actions, console)


def _rescan_review(state: _State, actions: InteractiveActions) -> None:
    """Rescan commit-on-success: a failed or cancelled scan changes nothing.

    Mutating draft.scan before the scan ran left a cancelled rescan holding a
    stale selection over a null draft, and the next generate silently built
    from pre-rescan sessions. The scan now runs first; the current view stays
    fully intact whenever it does not complete.
    """

    assert state.draft is not None
    assert state.selection is not None
    selected = set(state.selection.selected_session_ids)
    scan = _scan_for_review(state, actions)
    if scan is None:
        return
    _clear_outcome_review(state)
    state.draft.set_scan(scan)
    _finish_review_selection(state, actions, selected)


def _review_key(
    state: _State,
    key: KeyPress,
    actions: InteractiveActions,
    console: Console,
) -> None:
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
    if key.key is Key.ESCAPE and state.search_query:
        _reset_search(state)
        return
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        _sync_selection(state, actions)
        state.screen = Screen.MAIN if state.review_from_main else Screen.REPORT_SETUP
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
        _begin_outcome_review(state, actions, console)
        return
    if _exact_char(key, "G"):
        # The guard's way out. Synthesis groups what it can carry and leaves
        # the rest as ungrouped candidates with a warning naming how many —
        # what an over-budget selection produced before the guard existed.
        # A byte counter refusing the work outright is the same editorial call
        # the guard was added to stop it from making.
        _begin_outcome_review(state, actions, console, force=True)
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
                    state.selection.scan.sessions_by_repository[row.repository_id][
                        0
                    ].repository.display_name,
                )
            except IiwiError as exc:
                state.error = _ErrorState(
                    kind="exclude-source",
                    title="Could not exclude repository",
                    detail=str(exc),
                )
                state.screen = Screen.RECOVERABLE_ERROR
                return
            state.selection.exclude_repository(row.repository_id)
            state.draft.scan = state.selection.scan
            _clear_outcome_review(state)
            _sync_selection(state, actions)
            rows = _tree_rows(state.selection.scan, state)
            state.review_cursor = min(state.review_cursor, max(0, len(rows) - 1))
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


def _outcome_review_rows(state: _State) -> list[OutcomeReviewRow]:
    """Return the Quick Review rows the cursor addresses — the rendered ones."""

    assert state.outcome_review is not None
    return visible_outcome_review_rows(state.outcome_review, state.evidence_expansions())


def _daily_review_rows(state: _State) -> list[DailyReviewRow]:
    """Return the Daily rows addressed by both cursor and renderer."""

    assert state.daily_review is not None
    return visible_daily_review_rows(state.daily_review, state.daily_expansions())


def _open_daily_review(state: _State, draft: DailyStandupDraft) -> None:
    state.daily_review = draft
    state.daily_cursor = min(
        state.daily_cursor,
        max(0, len(visible_daily_review_rows(draft, state.daily_expansions())) - 1),
    )
    state.daily_message = None
    state.daily_result = None
    state.daily_result_cursor = 0
    state.error = None
    state.screen = Screen.DAILY_REVIEW


def _begin_daily_review(
    state: _State,
    actions: InteractiveActions,
    console: Console,
) -> None:
    """Start or refresh Daily while preserving its independent review draft."""

    message = "Scanning sessions and synthesizing outcomes… this can take a few minutes."
    state.daily_message = message
    _paint_pending(state, console, message)
    try:
        draft = actions.start_daily(state.daily_review)
    except DailySourceUnavailableError as exc:
        state.error = _ErrorState(
            kind="daily-source",
            title="Could not read Daily Standup sources",
            detail=str(exc),
            retry="daily-source",
            daily_source_error=exc,
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    except IiwiError as exc:
        # start_daily reads settings, the enabled harnesses and the clock before
        # it ever scans, so ConfigurationError reaches here on an unusable
        # config. NarrativeRunError reaches here too: Daily builds its
        # narrator from whichever harness is installed (see
        # cli._build_daily_narrator), and that provider-selection step can
        # fail before any scan starts. NarrativeRunError subclasses IiwiError,
        # so this single arm catches it. Every other menu entry shows failures
        # like this as a recoverable error rather than letting them escape
        # _dispatch and kill the app.
        state.error = _ErrorState(
            kind="daily-start",
            title="Could not start Daily Standup",
            detail=str(exc),
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    _open_daily_review(state, draft)


def _persist_daily_review(state: _State, actions: InteractiveActions) -> None:
    assert state.daily_review is not None
    state.daily_message = actions.persist_daily(state.daily_review)


def _move_daily_item(
    state: _State,
    target: DailyReviewRow,
    delta: int,
) -> bool:
    assert state.daily_review is not None
    assert target.work_item_id is not None
    rows = _daily_review_rows(state)
    current = next(
        index
        for index, row in enumerate(rows)
        if row.kind == "item"
        and row.section is target.section
        and row.work_item_id == target.work_item_id
    )
    neighbour_index = current + delta
    if not 0 <= neighbour_index < len(rows):
        return False
    neighbour = rows[neighbour_index]
    if neighbour.kind != "item" or neighbour.section is not target.section:
        return False
    assert neighbour.work_item_id is not None
    section_items = {
        work_item.id: item for work_item, item in state.daily_review.ordered_items(target.section)
    }
    item = section_items[target.work_item_id]
    neighbour_item = section_items[neighbour.work_item_id]
    if item.rank == neighbour_item.rank:
        return False
    item.rank, neighbour_item.rank = neighbour_item.rank, item.rank
    _focus_daily_item(state, target)
    return True


def _focus_daily_item(state: _State, target: DailyReviewRow) -> None:
    """Resolve focus by stable row identity after a mutation changes row order."""

    assert target.work_item_id is not None
    state.daily_cursor = next(
        index
        for index, row in enumerate(_daily_review_rows(state))
        if row.kind == "item"
        and row.section is target.section
        and row.work_item_id == target.work_item_id
    )


def _focus_outcome(
    state: _State,
    rows: list[OutcomeReviewRow],
    outcome_id: str,
) -> None:
    """Resolve focus by stable row identity after a mutation changes row order."""

    state.outcome_cursor = next(
        (
            index
            for index, row in enumerate(rows)
            if row.kind == "outcome" and row.outcome_id == outcome_id
        ),
        min(state.outcome_cursor, max(0, len(rows) - 1)),
    )


def _generate_daily_review(
    state: _State,
    actions: InteractiveActions,
    *,
    preview: bool,
) -> None:
    assert state.daily_review is not None
    try:
        result = (
            actions.preview_daily(state.daily_review)
            if preview
            else actions.generate_daily(state.daily_review)
        )
    except IiwiError as exc:
        state.error = _ErrorState(
            kind="daily-preview" if preview else "daily-write",
            title="Could not preview Daily Standup" if preview else "Could not write Daily Standup",
            detail=str(exc),
            retry="daily-preview" if preview else None,
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    state.daily_message = None
    state.error = None
    if preview:
        state.result = result
        state.preview_offset = 0
        state.preview_return_screen = Screen.DAILY_REVIEW
        state.screen = Screen.REPORT_PREVIEW
    else:
        state.daily_result = result
        state.daily_result_cursor = 0
        state.preview_return_screen = None
        state.screen = Screen.DAILY_RESULT


def _daily_review_key(
    state: _State,
    key: KeyPress,
    actions: InteractiveActions,
) -> None:
    assert state.daily_review is not None
    rows = _daily_review_rows(state)
    state.daily_cursor = min(state.daily_cursor, len(rows) - 1)
    target = rows[state.daily_cursor]

    if _exact_char(key, "J") and target.kind == "item":
        if _move_daily_item(state, target, 1):
            _persist_daily_review(state, actions)
        return
    if _exact_char(key, "K") and target.kind == "item":
        if _move_daily_item(state, target, -1):
            _persist_daily_review(state, actions)
        return

    state.daily_cursor = _move(state.daily_cursor, key, len(rows))
    target = rows[state.daily_cursor]
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    if _exact_char(key, "p"):
        _generate_daily_review(state, actions, preview=True)
        return
    if _exact_char(key, "g"):
        _generate_daily_review(state, actions, preview=False)
        return
    if _exact_char(key, "a"):
        statement = actions.add_daily_statement(target.section)
        if statement is not None:
            created = state.daily_review.add_user_item(target.section, statement)
            _persist_daily_review(state, actions)
            rows = _daily_review_rows(state)
            state.daily_cursor = next(
                index
                for index, row in enumerate(rows)
                if row.kind == "item"
                and row.section is target.section
                and row.work_item_id == created.id
            )
        return
    if target.kind == "more":
        if key.key is Key.ENTER:
            disclosure = (
                YESTERDAY_MORE_SECTION
                if target.section is DailySection.YESTERDAY
                else TODAY_MORE_SECTION
            )
            state.daily_expansions().symmetric_difference_update({disclosure})
        return
    if target.kind != "item":
        return

    assert target.work_item_id is not None
    if key.key is Key.SPACE:
        state.daily_review.toggle_included(target.section, target.work_item_id)
        _focus_daily_item(state, target)
        _persist_daily_review(state, actions)
    elif _exact_char(key, "v"):
        state.daily_expansions().symmetric_difference_update({target.work_item_id})
    elif _exact_char(key, "e"):
        current = next(
            item
            for work_item, item in state.daily_review.ordered_items(target.section)
            if work_item.id == target.work_item_id
        )
        statement = actions.edit_daily_statement(current.statement)
        if statement is not None:
            state.daily_review.edit(
                target.section,
                target.work_item_id,
                statement,
            )
            _persist_daily_review(state, actions)


def _daily_result_key(state: _State, key: KeyPress) -> None:
    assert state.daily_result is not None
    options = daily_result_options()
    state.daily_result_cursor = _move(state.daily_result_cursor, key, len(options))
    if key.key is Key.ESCAPE or _char(key, "q") or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    if key.key is not Key.ENTER:
        return
    if options[state.daily_result_cursor] == "Back to main menu":
        state.screen = Screen.MAIN
        return
    state.error = _ErrorState(
        kind="daily-path",
        title="Daily Standup path",
        detail=str(state.daily_result.output_path),
    )
    state.screen = Screen.RECOVERABLE_ERROR


def _begin_outcome_review(
    state: _State,
    actions: InteractiveActions,
    console: Console,
    *,
    force: bool = False,
) -> None:
    assert state.draft is not None
    assert state.selection is not None
    if state.selection.selected_count == 0:
        state.review_message = "Select at least one session before generating."
        state.screen = Screen.SESSION_REVIEW
        return
    # Quick Review is the LLM path, so the Narrative toggle is what opts out of
    # it. Turning it off must not still spend a synthesis run.
    if not state.draft.narrative:
        # A plain generate never inherits a pending fallback notice: that
        # notice belongs to the fallback attempt that set it, and this
        # attempt decides it does not carry one.
        state.draft.generation_notice = None
        _generate(state, actions, console, force=False)
        return
    _sync_selection(state, actions)
    filtered_scan = state.selection.filtered_scan()
    selection_key = (
        tuple(sorted(item.session.session_id for item in filtered_scan.resolved_sessions)),
        state.draft.detail,
    )
    # The cache short-circuit comes first. A review only exists because this
    # selection already cleared the guard, and synthesizing again re-extracts
    # every session — the whole cost this screen switch exists to avoid.
    if state.outcome_review is not None and state.outcome_review_selection_key == selection_key:
        state.outcome_cursor = min(
            state.outcome_cursor,
            max(0, len(_outcome_review_rows(state)) - 1),
        )
        state.review_message = None
        state.error = None
        state.screen = Screen.OUTCOME_REVIEW
        return
    try:
        _paint_pending(state, console, "Synthesizing outcomes…")
        state.outcome_review = actions.synthesize(state.draft, filtered_scan, force)
    except SynthesisBudgetExceededError as exc:
        # Synthesis measured the selection on the extraction pass it was going to
        # run anyway and refused before spending the model call.
        budget = exc.estimate
        state.review_message = (
            f"{budget.selected_count} selected; synthesis handles about "
            f"{budget.fit_count}. Narrow the period, deselect what does "
            f"not belong in the update, or press G to group the newest "
            f"that fit and leave the rest as ungrouped candidates. "
            f"({budget.bytes_used} / {budget.max_bytes} bytes)"
        )
        state.error = None
        state.screen = Screen.SESSION_REVIEW
        return
    except OutcomeSynthesisError as exc:
        state.error = _ErrorState(
            kind="outcome-synthesis",
            title="Could not synthesize outcomes",
            detail=str(exc),
            retry="outcome-synthesis",
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    state.outcome_review_selection_key = selection_key
    state.outcome_cursor = 0
    # Anything synthesis had to hold back is on screen as the review opens,
    # not only in the written report.
    state.outcome_message = (
        state.outcome_review.warnings[0] if state.outcome_review.warnings else None
    )
    state.expanded_evidence = set()
    state.review_message = None
    state.error = None
    state.screen = Screen.OUTCOME_REVIEW


def _generate_outcome_review(
    state: _State,
    actions: InteractiveActions,
    *,
    preview: bool,
    force: bool = False,
) -> None:
    assert state.draft is not None
    assert state.selection is not None
    assert state.outcome_review is not None
    # A report with every outcome excluded is a header and nothing else, so say
    # so here rather than writing the empty file.
    if not any(outcome.included for outcome in state.outcome_review.outcomes):
        state.outcome_message = "Include at least one outcome before generating."
        return
    draft = state.draft
    draft.set_dry_run(preview)
    try:
        result = actions.generate_reviewed(
            draft,
            state.selection.filtered_scan(),
            state.outcome_review,
            force,
        )
    except ReportAlreadyExistsError as exc:
        state.error = _ErrorState(
            kind="outcome-preview" if preview else "outcome-write",
            title="Could not write report",
            detail=str(exc),
            retry="outcome-preview" if preview else "outcome-write",
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    except ReportOutputError as exc:
        state.error = _ErrorState(
            kind="outcome-preview" if preview else "outcome-write",
            title="Could not preview report" if preview else "Could not write report",
            detail=str(exc),
            retry="outcome-preview" if preview else None,
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    except IiwiError as exc:
        state.error = _ErrorState(
            kind="outcome-preview" if preview else "outcome-write",
            title="Could not preview report" if preview else "Could not write report",
            detail=str(exc),
            retry="outcome-preview" if preview else None,
        )
        state.screen = Screen.RECOVERABLE_ERROR
        return
    finally:
        draft.set_dry_run(False)
    state.result = result
    state.result_cursor = 0
    state.preview_offset = 0
    state.outcome_message = None
    state.error = None
    if preview:
        state.preview_return_screen = Screen.OUTCOME_REVIEW
        state.screen = Screen.REPORT_PREVIEW
    else:
        state.preview_return_screen = None
        state.screen = Screen.REPORT_RESULT


def _cycle_report_type(state: _State, actions: InteractiveActions) -> None:
    assert state.draft is not None
    assert state.outcome_review is not None
    review = state.outcome_review
    report_type = (
        ReportType.ENGINEERING if review.report_type is ReportType.MANAGER else ReportType.MANAGER
    )
    review.set_report_type(report_type)
    assert review.detail is not None
    state.draft.report_type = review.report_type
    state.draft.detail = review.detail
    state.draft.detail_overridden = review.detail_overridden
    if state.outcome_review_selection_key is not None:
        selected_session_ids, _ = state.outcome_review_selection_key
        state.outcome_review_selection_key = (
            selected_session_ids,
            state.draft.detail,
        )
    state.outcome_message = None
    try:
        actions.save_report_type(report_type)
    except ConfigurationError as exc:
        state.outcome_message = (
            f"Report type changed, but the preference could not be remembered: {exc}"
        )


def _move_reviewed_outcome(
    state: _State,
    target: OutcomeReviewRow,
    delta: int,
) -> None:
    assert state.outcome_review is not None
    assert target.outcome_id is not None
    state.outcome_review.move(target.outcome_id, delta)
    rows = _outcome_review_rows(state)
    state.outcome_cursor = next(
        index
        for index, row in enumerate(rows)
        if row.kind == "outcome" and row.outcome_id == target.outcome_id
    )


def _outcome_review_key(
    state: _State,
    key: KeyPress,
    actions: InteractiveActions,
) -> None:
    assert state.outcome_review is not None
    rows = _outcome_review_rows(state)
    state.outcome_cursor = min(state.outcome_cursor, len(rows) - 1)
    target = rows[state.outcome_cursor]

    if _exact_char(key, "J") and target.kind == "outcome":
        _move_reviewed_outcome(state, target, 1)
        return
    if _exact_char(key, "K") and target.kind == "outcome":
        _move_reviewed_outcome(state, target, -1)
        return

    state.outcome_cursor = _move(state.outcome_cursor, key, len(rows))
    target = rows[state.outcome_cursor]
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.SESSION_REVIEW
        return
    if _exact_char(key, "p"):
        _generate_outcome_review(state, actions, preview=True)
        return
    if _exact_char(key, "g"):
        _generate_outcome_review(state, actions, preview=False)
        return
    if _exact_char(key, "a"):
        added = actions.add_outcome()
        if added is not None:
            created = state.outcome_review.add_user_outcome(
                added.title,
                added.impact,
                added.status,
            )
            rows = _outcome_review_rows(state)
            state.outcome_cursor = next(
                index for index, row in enumerate(rows) if row.outcome_id == created.id
            )
        return
    if target.kind != "outcome":
        if key.key is not Key.ENTER:
            return
        if target.kind == "settings":
            _cycle_report_type(state, actions)
        elif target.kind == "more":
            expansions = state.evidence_expansions()
            expansions.symmetric_difference_update({MORE_CANDIDATES_SECTION})
        elif target.kind == "ungrouped":
            expansions = state.evidence_expansions()
            expansions.symmetric_difference_update({UNGROUPED_CANDIDATES_SECTION})
        elif target.kind == "blockers":
            state.outcome_review.blockers = actions.edit_gap(
                "Blockers", state.outcome_review.blockers
            )
        elif target.kind == "next_week":
            state.outcome_review.next_week = actions.edit_gap(
                "Next week", state.outcome_review.next_week
            )
        elif target.kind == "preview":
            _generate_outcome_review(state, actions, preview=True)
        elif target.kind == "generate":
            _generate_outcome_review(state, actions, preview=False)
        return

    assert target.outcome_id is not None
    if key.key is Key.SPACE:
        state.outcome_review.toggle_included(target.outcome_id)
        _focus_outcome(state, _outcome_review_rows(state), target.outcome_id)
        return
    if _exact_char(key, "v"):
        state.evidence_expansions().symmetric_difference_update({target.outcome_id})
        return
    if _exact_char(key, "e"):
        outcome = next(
            item for item in state.outcome_review.outcomes if item.id == target.outcome_id
        )
        edited = actions.edit_outcome(outcome.model_copy(deep=True))
        state.outcome_review.edit(
            target.outcome_id,
            title=edited.title,
            status=edited.status,
            impact=edited.impact,
        )
        return
    if _exact_char(key, "s"):
        try:
            state.outcome_review.split(target.outcome_id)
        except ValueError as exc:
            state.outcome_message = str(exc)
        state.outcome_cursor = min(
            state.outcome_cursor,
            len(_outcome_review_rows(state)) - 1,
        )


def _error_options(error: _ErrorState) -> list[str]:
    if error.kind == "exclude-source":
        return ["Back"]
    if error.kind in {"doctor-result"}:
        return ["Main menu"]
    if error.kind in {"new-report-start", "activity-start", "daily-start"}:
        # No "Change harness"/"Change period": both of those assume
        # state.draft is already set, but these two kinds fire when building
        # the draft itself is what failed, so state.draft is still None.
        return ["Back", "Main menu"]
    if error.kind == "report-path":
        return ["Back"]
    if error.kind in {"history-path", "history-missing", "history-open", "history-preview"}:
        return ["Back"]
    if error.kind == "daily-path":
        return ["Back"]
    if error.kind == "daily-source":
        return ["Retry", "Continue with empty draft", "Back"]
    if error.kind == "daily-preview":
        return ["Retry", "Back to Daily Review", "Main menu"]
    if error.kind == "daily-write":
        return ["Back to Daily Review", "Main menu"]
    if error.kind in {"report-empty", "activity-empty"}:
        return ["Change period", "Change harness", "Back", "Main menu"]
    if error.kind == "outcome-synthesis":
        return ["Retry", "Use session-based report", "Back"]
    if error.kind == "outcome-preview":
        return ["Retry", "Back to Quick Review", "Main menu"]
    if error.kind == "outcome-write":
        if error.retry == "outcome-write":
            return ["Overwrite once", "Back to Quick Review", "Main menu"]
        return ["Back to Quick Review", "Main menu"]
    if error.kind == "report-output-conflict":
        return ["Overwrite once", "Back", "Main menu"]
    if error.kind in {"report-output", "report-generate"}:
        return ["Back", "Main menu"]
    return ["Change harness", "Back", "Main menu"]


def _error_back_screen(error: _ErrorState) -> Screen:
    if error.back is not None:
        return error.back
    if error.kind == "exclude-source":
        return Screen.SESSION_REVIEW
    if error.kind == "report-path":
        return Screen.REPORT_RESULT
    if error.kind in {"history-path", "history-missing", "history-open", "history-preview"}:
        return Screen.HISTORY
    if error.kind == "daily-path":
        return Screen.DAILY_RESULT
    if error.kind in {"daily-source", "daily-start"}:
        return Screen.MAIN
    if error.kind in {"daily-preview", "daily-write"}:
        return Screen.DAILY_REVIEW
    if error.kind == "doctor-result":
        return Screen.MAIN
    if error.kind == "outcome-synthesis":
        return Screen.SESSION_REVIEW
    if error.kind in {"outcome-preview", "outcome-write"}:
        return Screen.OUTCOME_REVIEW
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
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
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
    if choice == "Back to Quick Review":
        state.screen = Screen.OUTCOME_REVIEW
        return
    if choice == "Back to Daily Review":
        state.screen = Screen.DAILY_REVIEW
        return
    if choice == "Retry":
        if error.retry == "daily-source":
            _begin_daily_review(state, actions, console)
        elif error.retry == "daily-preview":
            _generate_daily_review(state, actions, preview=True)
        elif error.retry == "outcome-synthesis":
            _begin_outcome_review(state, actions, console)
        elif error.retry == "outcome-preview":
            _generate_outcome_review(state, actions, preview=True)
        return
    if choice == "Continue with empty draft":
        assert error.daily_source_error is not None
        draft = actions.continue_daily_empty(
            error.daily_source_error,
            state.daily_review,
        )
        _open_daily_review(state, draft)
        return
    if choice == "Use session-based report":
        # The notice rides into this one attempt only: _generate clears it on
        # success and leaves it set on failure so the error screen keeps its
        # context until the next attempt decides.
        assert state.draft is not None
        state.draft.generation_notice = _SESSION_FALLBACK_NOTICE
        _generate(state, actions, console, force=False)
        return
    if choice == "Overwrite once":
        if error.retry == "outcome-write":
            _generate_outcome_review(
                state,
                actions,
                preview=False,
                force=True,
            )
        else:
            _generate(state, actions, console, force=True)
        return
    assert state.draft is not None
    if choice == "Change harness":
        state.draft.set_harness(actions.choose_harness(state.draft.harness))
        if state.draft.harness != "opencode":
            state.draft.set_sanitize(False)
    else:
        state.draft.set_period(*actions.choose_period(state.draft.period_label))
    state.selection = None
    if error.kind.startswith("activity"):
        _load_activity(state, actions, state.draft)
    else:
        state.error = None
        state.expanded_repositories = set()
        state.screen = Screen.REPORT_SETUP


def _history_entries() -> list[HistoryEntry]:
    """The generated-report log, newest first, as the history screen shows it."""

    return list(reversed(read_history()))


def _filtered_history(
    entries: list[HistoryEntry], show_missing: bool
) -> tuple[list[HistoryEntry], int]:
    if show_missing:
        return entries, 0
    visible = [e for e in entries if e.output_path.exists()]
    return visible, len(entries) - len(visible)


def _open_history_entry(entry: HistoryEntry) -> None:
    path = entry.output_path
    if not path.exists():
        raise FileNotFoundError(f"{path} — file no longer exists")
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ""
    if editor:
        cmd = [*shlex.split(editor), str(path)]
    elif sys.platform == "darwin":
        cmd = ["open", str(path)]
    else:
        cmd = ["xdg-open", str(path)]
    subprocess.run(cmd, check=True)


def _history_key(state: _State, key: KeyPress, console: Console) -> None:
    if key.key is Key.ESCAPE or _char(key, "q") or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    if _exact_char(key, "h"):
        state.history_show_missing = not state.history_show_missing
        # clamp cursor/offset to new visible size
        entries = _history_entries()
        visible, _ = _filtered_history(entries, state.history_show_missing)
        count = len(visible)
        if count == 0:
            state.history_cursor = 0
            state.history_offset = 0
        else:
            cap = history_capacity(console.size.height, console.size.width)
            state.history_cursor = min(state.history_cursor, count - 1)
            state.history_offset = min(state.history_offset, max(0, count - cap))
            if state.history_cursor < state.history_offset:
                state.history_offset = state.history_cursor
            if state.history_cursor >= state.history_offset + cap:
                state.history_offset = max(0, state.history_cursor - cap + 1)
        return
    # Resolve visible entries for navigation
    all_entries = _history_entries()
    visible, hidden = _filtered_history(all_entries, state.history_show_missing)
    count = len(visible)
    if not count:
        return
    capacity = history_capacity(console.size.height, console.size.width)
    page = max(1, capacity)
    state.history_cursor = _move(state.history_cursor, key, count)
    if key.key is Key.PAGE_UP:
        state.history_cursor = max(0, state.history_cursor - page)
    elif key.key is Key.PAGE_DOWN:
        state.history_cursor = min(count - 1, state.history_cursor + page)
    elif key.key is Key.HOME or _exact_char(key, "g"):
        state.history_cursor = 0
    elif key.key is Key.END or _exact_char(key, "G"):
        state.history_cursor = count - 1
    state.history_offset = min(state.history_offset, max(0, count - capacity))
    if state.history_cursor < state.history_offset:
        state.history_offset = state.history_cursor
    if state.history_cursor >= state.history_offset + capacity:
        state.history_offset = max(0, state.history_cursor - capacity + 1)
    # Actions on visible entry
    if _exact_char(key, "o"):
        entry = visible[state.history_cursor]
        try:
            _open_history_entry(entry)
        except FileNotFoundError as exc:
            state.error = _ErrorState(
                kind="history-missing", title="File not found", detail=str(exc)
            )
            state.screen = Screen.RECOVERABLE_ERROR
        except (OSError, subprocess.CalledProcessError) as exc:
            state.error = _ErrorState(
                kind="history-open", title="Could not open report", detail=str(exc)
            )
            state.screen = Screen.RECOVERABLE_ERROR
        return
    if key.key is Key.ENTER or _exact_char(key, "p"):
        entry = visible[state.history_cursor]
        if not entry.output_path.exists():
            state.error = _ErrorState(
                kind="history-missing",
                title="File not found",
                detail=f"{entry.output_path} — file no longer exists",
            )
            state.screen = Screen.RECOVERABLE_ERROR
            return
        try:
            # Read to validate before switching screen so error stays on History
            entry.output_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            state.error = _ErrorState(
                kind="history-preview", title="Could not preview report", detail=str(exc)
            )
            state.screen = Screen.RECOVERABLE_ERROR
            return
        state.history_preview_entry = entry
        state.history_preview_offset = 0
        state.screen = Screen.HISTORY_PREVIEW
        return


def _result_key(state: _State, key: KeyPress) -> None:
    assert state.draft is not None
    assert state.result is not None
    options = report_result_options()
    state.result_cursor = _move(state.result_cursor, key, len(options))
    if key.key is Key.ESCAPE or _char(key, "q") or _char(key, "b"):
        state.screen = Screen.MAIN
        return
    if key.key is not Key.ENTER:
        return

    choice = options[state.result_cursor]
    if choice == "Back to main menu":
        state.screen = Screen.MAIN
    elif choice == "Generate another report":
        state.draft.clear_scan()
        state.selection = None
        _clear_outcome_review(state)
        state.result = None
        state.error = None
        state.review_message = None
        state.review_from_main = False
        state.setup_cursor = 0
        state.setup_advanced = False
        state.preview_offset = 0
        state.session_preview_offset = 0
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
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = state.preview_return_screen or Screen.REPORT_RESULT
        state.preview_return_screen = None
        return
    lines = state.result.content.splitlines() or [""]
    capacity = report_preview_capacity(console.size.height, console.size.width)
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
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = state.preview_return_screen or Screen.MAIN
        state.preview_return_screen = None
        return
    lines = build_session_preview_lines(state.preview_session) or [""]
    capacity = report_preview_capacity(console.size.height, console.size.width)
    max_offset = max(0, len(lines) - capacity) if capacity else max(0, len(lines) - 1)
    page = max(1, capacity)
    if key.key is Key.UP or _char(key, "k"):
        state.session_preview_offset = max(0, state.session_preview_offset - 1)
    elif key.key is Key.DOWN or _char(key, "j"):
        state.session_preview_offset = min(max_offset, state.session_preview_offset + 1)
    elif key.key is Key.PAGE_UP:
        state.session_preview_offset = max(0, state.session_preview_offset - page)
    elif key.key is Key.PAGE_DOWN:
        state.session_preview_offset = min(max_offset, state.session_preview_offset + page)
    elif key.key is Key.HOME or _exact_char(key, "g"):
        state.session_preview_offset = 0
    elif key.key is Key.END or _exact_char(key, "G"):
        state.session_preview_offset = max_offset


def _history_preview_key(state: _State, key: KeyPress, console: Console) -> None:
    assert state.history_preview_entry is not None
    if _char(key, "q") or key.key is Key.ESCAPE or _char(key, "b"):
        state.screen = Screen.HISTORY
        return
    if _exact_char(key, "o"):
        try:
            _open_history_entry(state.history_preview_entry)
        except FileNotFoundError as exc:
            state.error = _ErrorState(
                kind="history-missing", title="File not found", detail=str(exc)
            )
            state.screen = Screen.RECOVERABLE_ERROR
        except (OSError, subprocess.CalledProcessError) as exc:
            state.error = _ErrorState(
                kind="history-open", title="Could not open report", detail=str(exc)
            )
            state.screen = Screen.RECOVERABLE_ERROR
        return
    try:
        content = state.history_preview_entry.output_path.read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        content = ""
    lines = content.splitlines() or [""]
    capacity = report_preview_capacity(console.size.height, console.size.width)
    max_offset = max(0, len(lines) - capacity) if capacity else max(0, len(lines) - 1)
    page = max(1, capacity)
    if key.key is Key.UP or _char(key, "k"):
        state.history_preview_offset = max(0, state.history_preview_offset - 1)
    elif key.key is Key.DOWN or _char(key, "j"):
        state.history_preview_offset = min(max_offset, state.history_preview_offset + 1)
    elif key.key is Key.PAGE_UP:
        state.history_preview_offset = max(0, state.history_preview_offset - page)
    elif key.key is Key.PAGE_DOWN:
        state.history_preview_offset = min(max_offset, state.history_preview_offset + page)
    elif key.key is Key.HOME or _exact_char(key, "g"):
        state.history_preview_offset = 0
    elif key.key is Key.END or _exact_char(key, "G"):
        state.history_preview_offset = max_offset


def _help_key(state: _State, key: KeyPress, console: Console) -> None:
    if (
        _char(key, "q")
        or key.key in {Key.ESCAPE, Key.ENTER}
        or _char(key, "b")
        or _exact_char(key, "?")
    ):
        state.screen = state.help_return_screen or Screen.MAIN
        state.help_return_screen = None
        return
    # The reference outgrew a short terminal, so it scrolls like the previews.
    capacity = help_capacity(console.size.height, console.size.width)
    max_offset = max(0, len(help_lines(state.help_return_screen)) - capacity)
    page = max(1, capacity)
    if key.key is Key.UP or _char(key, "k"):
        state.help_offset = max(0, state.help_offset - 1)
    elif key.key is Key.DOWN or _char(key, "j"):
        state.help_offset = min(max_offset, state.help_offset + 1)
    elif key.key is Key.PAGE_UP:
        state.help_offset = max(0, state.help_offset - page)
    elif key.key is Key.PAGE_DOWN:
        state.help_offset = min(max_offset, state.help_offset + page)


def _render_screen(state: _State, console: Console) -> None:
    if state.screen is Screen.MAIN:
        render_main_menu(console, selected=state.main_cursor)
    elif state.screen is Screen.REPORT_SETUP:
        assert state.draft is not None
        render_report_setup(
            console,
            state.draft,
            selected=state.setup_cursor,
            advanced=state.setup_advanced,
        )
    elif state.screen is Screen.SETTINGS:
        assert state.settings_rows is not None
        render_settings(
            console,
            rows=state.settings_rows,
            selected=state.settings_cursor,
            file_path=state.settings_file_path or "",
            editing=state.settings_editing,
            edit_value=state.settings_edit_value,
            error=state.settings_error,
            offset=state.settings_offset,
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
    elif state.screen is Screen.OUTCOME_REVIEW:
        assert state.outcome_review is not None
        render_outcome_review(
            console,
            state.outcome_review,
            cursor=state.outcome_cursor,
            expanded_evidence=state.evidence_expansions(),
            period=state.draft.period if state.draft is not None else None,
            message=state.outcome_message,
        )
    elif state.screen is Screen.DAILY_REVIEW:
        assert state.daily_review is not None
        render_daily_review(
            console,
            state.daily_review,
            cursor=state.daily_cursor,
            expanded=state.daily_expansions(),
            message=state.daily_message,
        )
    elif state.screen is Screen.SESSION_PREVIEW:
        assert state.preview_session is not None
        render_session_preview(
            console,
            state.preview_session,
            offset=state.session_preview_offset,
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
    elif state.screen is Screen.DAILY_RESULT:
        assert state.daily_result is not None
        render_daily_result(
            console,
            output_path=state.daily_result.output_path,
            selected=state.daily_result_cursor,
        )
    elif state.screen is Screen.HISTORY:
        all_entries = _history_entries()
        visible, hidden = _filtered_history(all_entries, state.history_show_missing)
        render_history(
            console,
            entries=visible,
            selected=state.history_cursor,
            offset=state.history_offset,
            hidden_count=hidden,
        )
    elif state.screen is Screen.HISTORY_PREVIEW:
        assert state.history_preview_entry is not None
        # File validated on Enter/p, but read again for display; guard OSError
        try:
            content = state.history_preview_entry.output_path.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError as exc:
            content = f"Could not read report: {exc}"
        render_history_preview(
            console,
            content=content,
            offset=state.history_preview_offset,
            file_name=state.history_preview_entry.output_path.name,
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
        render_help(
            console,
            offset=state.help_offset,
            screen=state.help_return_screen,
        )


def _idle_interrupt(state: _State, actions: InteractiveActions) -> None:
    """Treat Ctrl-C while waiting for a key like the screen's normal Back action."""

    if state.screen is Screen.MAIN:
        state.screen = Screen.EXIT
    elif state.screen is Screen.REPORT_SETUP or state.screen is Screen.SETTINGS:
        state.screen = Screen.MAIN
    elif state.screen is Screen.SESSION_REVIEW:
        if state.selection is not None and state.draft is not None:
            _sync_selection(state, actions)
        state.screen = Screen.MAIN if state.review_from_main else Screen.REPORT_SETUP
    elif state.screen is Screen.OUTCOME_REVIEW:
        state.screen = Screen.SESSION_REVIEW
    elif state.screen is Screen.DAILY_REVIEW or state.screen in {
        Screen.REPORT_RESULT,
        Screen.DAILY_RESULT,
        Screen.HISTORY,
    }:
        state.screen = Screen.MAIN
    elif state.screen is Screen.HISTORY_PREVIEW:
        state.screen = Screen.HISTORY
    elif state.screen is Screen.REPORT_PREVIEW:
        state.screen = state.preview_return_screen or Screen.REPORT_RESULT
        state.preview_return_screen = None
    elif state.screen is Screen.SESSION_PREVIEW:
        state.screen = state.preview_return_screen or Screen.MAIN
        state.preview_return_screen = None
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
    if (
        _exact_char(key, "?")
        and state.screen is not Screen.HELP
        and not state.searching
        and not state.settings_editing
    ):
        _open_help(state)
        return
    if state.screen is Screen.MAIN:
        _main_key(state, key, actions, console)
    elif state.screen is Screen.REPORT_SETUP:
        _setup_key(state, key, actions, console)
    elif state.screen is Screen.SETTINGS:
        _settings_key(state, key, console)
    elif state.screen is Screen.SESSION_REVIEW:
        _review_key(state, key, actions, console)
    elif state.screen is Screen.OUTCOME_REVIEW:
        _outcome_review_key(state, key, actions)
    elif state.screen is Screen.DAILY_REVIEW:
        _daily_review_key(state, key, actions)
    elif state.screen is Screen.REPORT_RESULT:
        _result_key(state, key)
    elif state.screen is Screen.DAILY_RESULT:
        _daily_result_key(state, key)
    elif state.screen is Screen.HISTORY:
        _history_key(state, key, console)
    elif state.screen is Screen.HISTORY_PREVIEW:
        _history_preview_key(state, key, console)
    elif state.screen is Screen.REPORT_PREVIEW:
        _preview_key(state, key, console)
    elif state.screen is Screen.SESSION_PREVIEW:
        _session_preview_key(state, key, console)
    elif state.screen is Screen.RECOVERABLE_ERROR:
        _error_key(state, key, actions, console)
    elif state.screen is Screen.HELP:
        _help_key(state, key, console)


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
    initial_screen: Screen = Screen.MAIN,
) -> None:
    """Run the terminal interaction until the user explicitly leaves it."""

    state = _State(screen=initial_screen)
    if initial_screen is Screen.DAILY_REVIEW:
        # The Daily screen cannot render until start_daily returns a draft, so
        # the pending line paints over the main menu while the scan blocks.
        state.screen = Screen.MAIN
        _begin_daily_review(state, actions, console)
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
