"""Pure Rich rendering for the interactive Iiwi screens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from iiwi import __version__
from iiwi.interactive.density import (
    is_subagent,
    last_activity_at,
    message_volume,
    repository_meta,
    scan_volume,
    session_meta,
    volume_label,
)
from iiwi.interactive.models import ReportDraft
from iiwi.interactive.selection import SelectionMark, SelectionState, noise_reason
from iiwi.models.repository import ResolvedSession
from iiwi.models.session import ActivityType, AgentSession
from iiwi.models.time_range import DateRange
from iiwi.security.redactor import redact_text
from iiwi.services.scan import ScanResult


@dataclass(frozen=True)
class VisibleRow:
    kind: str
    repository_id: str
    session_id: str | None = None


_MAIN_OPTIONS = ["Generate Report", "Browse Sessions", "Check Setup", "Settings"]
_MAIN_DESCRIPTIONS = {
    "Generate Report": "Scan the period and produce the report",
    "Browse Sessions": "Explore sessions by repository",
    "Check Setup": "Diagnose the harness setup",
    "Settings": "Edit saved settings",
}
_PRIMARY_SETUP_FIELDS = ["Harness", "Period"]
_ADVANCED_SETUP_FIELDS = ["Detail", "Subagents", "Narrative", "Sanitize", "Dry run"]
_ADVANCED_ROW = "Advanced settings"
_GENERATE_ROW = "Generate report"
_SETTINGS_LABEL = "Settings"
_SETUP_LABEL_CELLS = 18
_SETUP_HELP = {
    "Harness": "Which coding agent's sessions to read: OpenCode, Claude Code or Codex.",
    "Period": "The date window the report covers.",
    "Advanced settings": "Show or hide less common report options.",
    "Detail": "Full keeps every section. Brief drops files, sessions and usage.",
    "Subagents": "Include sessions spawned as subagents, or only the ones you started.",
    "Narrative": "Write the prose review with the local opencode run, or emit structure only.",
    "Sanitize": "Ask OpenCode to redact session content on export.",
    "Dry run": "Print the report instead of writing a file.",
    "Generate report": "Scan the period and produce the report.",
}
_RESULT_OPTIONS = ["Back to main menu", "Generate another report", "Print report path"]
_DRY_RUN_RESULT_OPTIONS = ["Preview report", "Back to main menu", "Generate another report"]
_ERROR_HINTS = ["↑↓ jk", "PgUp/PgDn Detail", "Enter Select", "? Help", "b Back"]
_MARKERS = {
    SelectionMark.ALL: "●",
    SelectionMark.NONE: "○",
    SelectionMark.PARTIAL: "◐",
}
_MARK_STYLES = {
    SelectionMark.ALL: "green",
    SelectionMark.NONE: "dim",
    SelectionMark.PARTIAL: "yellow",
}
_CURSOR_STYLE = "bold cyan"
_ACTION_STYLE = "cyan"
_EXPANSION_STYLE = "dim"
_ROW_GAP = 3
_MIN_TITLE_CELLS = 12
_UNDATED = datetime.min.replace(tzinfo=UTC)
_CURSOR = "▶"
_RULE_CHAR = "═"
_HINT_SEPARATOR = " │ "
_BAR_FULL = "█"
_BAR_EMPTY = "░"
_BAR_CELLS = 12
_BAR_STYLE = "cyan"
_PERCENT_CELLS = 4
_MIN_BAR_WIDTH = 80
_MIN_SUBTITLE_HEIGHT = 16
_MAIN_SUBTITLE = "Turn coding-agent sessions into engineering reports"
_WORDMARK = (
    " ___ _        _",
    "|_ _(_)_ __ _(_)",
    " | || \\ V  V / |",
    "|___|_|\\_/\\_/|_|",
)
_MIN_WORDMARK_HEIGHT = 24
_MIN_WORDMARK_WIDTH = 24
_PROJECT_URL = "https://github.com/mike840609/iiwi"
_PROJECT_LABEL = "github.com/mike840609/iiwi"
_REVIEW_SUBTITLE = "Select sessions to include in the report:"
_BROWSE_SUBTITLE = "Select a repository to explore:"


def main_menu_options() -> list[str]:
    return list(_MAIN_OPTIONS)


def report_setup_rows(*, advanced: bool = True) -> list[str]:
    rows = [_GENERATE_ROW, *_PRIMARY_SETUP_FIELDS, _ADVANCED_ROW]
    if advanced:
        rows.extend(_ADVANCED_SETUP_FIELDS)
    return rows


def report_generate_row() -> str:
    return _GENERATE_ROW


def _option(label: str, index: int, selected: int) -> str:
    return f"{_CURSOR if index == selected else ' '} {label}"


def _print_viewport_line(console: Console, value: str, *, style: str = "") -> None:
    console.print(Text(value, style=style), no_wrap=True, overflow="ellipsis")


def _print_viewport_text(console: Console, text: Text) -> None:
    console.print(text, no_wrap=True, overflow="ellipsis")


def _print_header(console: Console, title: str, *, subtitle: str | None = None) -> None:
    _print_viewport_line(console, title, style="bold")
    _print_viewport_line(console, _RULE_CHAR * console.size.width, style="dim")
    if subtitle and console.size.height >= _MIN_SUBTITLE_HEIGHT:
        _print_viewport_line(console, subtitle, style="dim")


def _header_lines(console: Console, subtitle: str | None) -> int:
    return 3 if subtitle and console.size.height >= _MIN_SUBTITLE_HEIGHT else 2


def _hint_lines(hints: list[str], width: int) -> list[str]:
    packed: list[str] = []
    line: list[str] = []
    for hint in hints:
        if line and cell_len(_HINT_SEPARATOR.join([*line, hint])) > width:
            packed.append(_HINT_SEPARATOR.join(line))
            line = [hint]
        else:
            line.append(hint)
    if line:
        packed.append(_HINT_SEPARATOR.join(line))
    return packed


def _print_hints(console: Console, hints: list[str]) -> None:
    for line in _hint_lines(hints, console.size.width):
        _print_viewport_line(console, line, style="dim")


@dataclass(frozen=True)
class _BarScale:
    peak: int
    total: int
    cells: int


def _bar_scale(scan: ScanResult, rows: list[VisibleRow], *, console_width: int) -> _BarScale:
    volumes = [
        sum(message_volume(item.session) for item in scan.sessions_by_repository[row.repository_id])
        for row in rows
        if row.kind == "repository"
    ]
    total = sum(volumes)
    enabled = bool(total) and console_width >= _MIN_BAR_WIDTH
    return _BarScale(peak=max(volumes, default=0), total=total, cells=_BAR_CELLS if enabled else 0)


def _bar_cell(scale: _BarScale, volume: int) -> Text:
    if not scale.cells:
        return Text("")
    filled = 0 if not volume else max(1, round(volume / scale.peak * scale.cells))
    filled = min(filled, scale.cells)
    percent = f"{volume / scale.total:.0%}" if scale.total else ""
    return Text.assemble(
        (_BAR_FULL * filled, _BAR_STYLE),
        (_BAR_EMPTY * (scale.cells - filled), "dim"),
        " ",
        (f"{percent:>{_PERCENT_CELLS}}", "dim"),
        " ",
    )


def session_row_meta(session: AgentSession, tz: tzinfo | None, reason: str | None = None) -> str:
    facts = " │ ".join(fact for fact in (session_meta(session, tz), reason) if fact)
    if not is_subagent(session):
        return facts
    return f"[sub] {facts}" if facts else "[sub]"


def _cursor_glyph(active: bool) -> tuple[str, str]:
    return (_CURSOR, _CURSOR_STYLE) if active else (" ", "")


def _expansion_glyph(expanded: bool) -> tuple[str, str]:
    return ("▾" if expanded else "▸", _EXPANSION_STYLE)


def _mark_glyph(mark: SelectionMark) -> tuple[str, str]:
    return _MARKERS[mark], _MARK_STYLES[mark]


@dataclass(frozen=True)
class _ListRow:
    lead: Text
    title: str
    meta: str
    selected: bool


def _meta_column_width(rows: list[_ListRow], *, console_width: int) -> int:
    widest_meta = max((cell_len(row.meta) for row in rows), default=0)
    widest_lead = max((row.lead.cell_len for row in rows), default=0)
    affordable = console_width - widest_lead - _ROW_GAP - _MIN_TITLE_CELLS
    return min(widest_meta, max(0, affordable))


def _list_row(row: _ListRow, *, meta_width: int, console_width: int) -> Text:
    row_style = _CURSOR_STYLE if row.selected else ""
    text = row.lead.copy()
    if not row.meta or cell_len(row.meta) > meta_width:
        text.append(row.title, style=row_style)
        return text
    body = Text(row.title, style=row_style)
    body.truncate(
        console_width - row.lead.cell_len - meta_width - _ROW_GAP,
        overflow="ellipsis",
        pad=True,
    )
    text.append_text(body)
    text.append(" " * _ROW_GAP)
    text.append(row.meta, style="dim")
    return text


def _print_list_rows(console: Console, rows: list[_ListRow]) -> None:
    width = console.size.width
    meta_width = _meta_column_width(rows, console_width=width)
    for row in rows:
        _print_viewport_text(console, _list_row(row, meta_width=meta_width, console_width=width))


def _print_option_line(console: Console, label: str, index: int, selected: int) -> None:
    _print_viewport_line(
        console,
        _option(label, index, selected),
        style=_CURSOR_STYLE if index == selected else "",
    )


def _period_label(period: DateRange) -> str:
    return f"{period.since:%b %d} – {period.until:%b %d}"


def _period_value(draft: ReportDraft) -> str:
    dates = _period_label(draft.period)
    return f"{draft.period_label} · {dates}" if draft.period_label else dates


def _harness_label(harness: str) -> str:
    return {
        "opencode": "OpenCode",
        "claude-code": "Claude Code",
        "codex": "Codex",
    }.get(harness, harness)


def _bool_label(value: bool, enabled: str, disabled: str) -> str:
    return enabled if value else disabled


def report_result_options(*, dry_run: bool) -> list[str]:
    return list(_DRY_RUN_RESULT_OPTIONS if dry_run else _RESULT_OPTIONS)


def report_preview_capacity(terminal_height: int) -> int:
    return max(0, terminal_height - 8)


def _print_wordmark(console: Console) -> None:
    version = f"v{__version__}"
    for line in _WORDMARK[:-1]:
        _print_viewport_line(console, line, style="bold cyan")
    last = _WORDMARK[-1]
    padding = console.size.width - cell_len(last) - cell_len(version)
    _print_viewport_text(
        console,
        Text.assemble((last, "bold cyan"), " " * padding, (version, "dim")),
    )


def render_main_menu(console: Console, *, selected: int) -> None:
    title = "Iiwi"
    version = f"v{__version__}"
    if (
        console.size.height >= _MIN_WORDMARK_HEIGHT
        and console.size.width >= _MIN_WORDMARK_WIDTH
    ):
        _print_wordmark(console)
        _print_viewport_line(console, _RULE_CHAR * console.size.width, style="dim")
        _print_viewport_line(console, _MAIN_SUBTITLE, style="dim")
    elif cell_len(title) + 1 + cell_len(version) <= console.size.width:
        padding = console.size.width - cell_len(title) - cell_len(version)
        title_line = Text.assemble((title, "bold"), " " * padding, (version, "dim"))
        _print_viewport_text(console, title_line)
        _print_viewport_line(console, _RULE_CHAR * console.size.width, style="dim")
        if console.size.height >= _MIN_SUBTITLE_HEIGHT:
            _print_viewport_line(console, _MAIN_SUBTITLE, style="dim")
    else:
        _print_header(console, "Iiwi", subtitle=_MAIN_SUBTITLE)
    if (
        console.size.height >= _MIN_SUBTITLE_HEIGHT
        and cell_len(_PROJECT_LABEL) <= console.size.width
    ):
        _print_viewport_line(console, _PROJECT_LABEL, style=f"dim link {_PROJECT_URL}")
    console.print()
    label_width = max(cell_len(label) for label in _MAIN_OPTIONS)
    for index, label in enumerate(_MAIN_OPTIONS):
        focused = index == selected
        lead = Text("▶ " if focused else "  ", style=_CURSOR_STYLE if focused else "")
        title_text = Text(label, style=_CURSOR_STYLE if focused else "")
        description = _MAIN_DESCRIPTIONS[label]
        if cell_len(description) <= console.size.width - lead.cell_len - label_width - _ROW_GAP:
            title_text.truncate(label_width, overflow="ellipsis", pad=True)
            text = Text.assemble(lead, title_text, " " * _ROW_GAP, (description, "dim"))
        else:
            text = Text.assemble(lead, title_text)
        _print_viewport_text(console, text)
    console.print()
    _print_hints(console, ["↑↓ jk", "Enter Select", "1-4", "? Help", "q Quit"])


def _setup_value(draft: ReportDraft, field: str) -> str:
    if field == "Harness":
        return _harness_label(draft.harness)
    if field == "Period":
        return _period_value(draft)
    if field == "Detail":
        return draft.detail.value.title()
    if field == "Subagents":
        return _bool_label(draft.include_subagents, "Included", "Excluded")
    if field == "Narrative":
        return _bool_label(draft.narrative, "Enabled", "Disabled")
    if field == "Sanitize":
        if draft.harness != "opencode":
            return "N/A"
        return _bool_label(draft.sanitize, "On", "Off")
    return _bool_label(draft.dry_run, "On", "Off")


def _setup_help(draft: ReportDraft, row: str) -> str:
    if row == "Sanitize" and draft.harness != "opencode":
        return "Only OpenCode can redact on export, so this does nothing here."
    return _SETUP_HELP[row]


def render_report_setup(
    console: Console,
    draft: ReportDraft,
    *,
    selected: int,
    advanced: bool = True,
) -> None:
    _print_header(console, "Generate Report")
    console.print()
    action_selected = selected == 0
    _print_viewport_line(
        console,
        f"{_CURSOR if action_selected else ' '} {_GENERATE_ROW}",
        style=_CURSOR_STYLE if action_selected else _ACTION_STYLE,
    )
    console.print()
    if console.size.height >= _MIN_SUBTITLE_HEIGHT:
        _print_viewport_line(console, f"  {_SETTINGS_LABEL}", style="bright_black")
    rows = report_setup_rows(advanced=advanced)
    for index, field in enumerate(rows[1:], start=1):
        focused = selected == index
        if field == _ADVANCED_ROW:
            cursor = _CURSOR if focused else " "
            glyph = "▾" if advanced else "▸"
            _print_viewport_line(
                console,
                f"{cursor} {field:<{_SETUP_LABEL_CELLS}}{glyph}",
                style=_CURSOR_STYLE if focused else "",
            )
            continue
        style = (
            _CURSOR_STYLE
            if focused
            else ("dim" if field == "Sanitize" and draft.harness != "opencode" else "")
        )
        cursor = _CURSOR if focused else " "
        _print_viewport_line(
            console,
            f"{cursor} {field:<{_SETUP_LABEL_CELLS}}{_setup_value(draft, field)}",
            style=style,
        )
    console.print()
    _print_viewport_line(console, _setup_help(draft, rows[selected]), style="dim")
    console.print()
    _print_hints(
        console,
        [
            "↑↓ jk",
            "←→ hl Change",
            "Enter Select",
            "r Review",
            "g Generate",
            "? Help",
            "b Back",
            "q Menu",
        ],
    )


def _session_recency(session: AgentSession) -> datetime:
    timestamp = last_activity_at(session)
    return _UNDATED if timestamp is None else timestamp


def _repository_recency(sessions: list[ResolvedSession]) -> datetime:
    return max((_session_recency(item.session) for item in sessions), default=_UNDATED)


def _ordered_repositories(scan: ScanResult) -> list[tuple[str, list[ResolvedSession]]]:
    by_name = sorted(
        scan.sessions_by_repository.items(),
        key=lambda item: (_repository_display_name(scan, item[0]), item[0]),
    )
    return sorted(by_name, key=lambda item: _repository_recency(item[1]), reverse=True)


def _ordered_sessions(sessions: list[ResolvedSession]) -> list[ResolvedSession]:
    by_id = sorted(sessions, key=lambda item: item.session.session_id)
    return sorted(by_id, key=lambda item: _session_recency(item.session), reverse=True)


def build_visible_rows(scan: ScanResult, expanded_repositories: set[str]) -> list[VisibleRow]:
    rows: list[VisibleRow] = []
    for repository_id, sessions in _ordered_repositories(scan):
        rows.append(VisibleRow(kind="repository", repository_id=repository_id))
        if repository_id not in expanded_repositories:
            continue
        rows.extend(
            VisibleRow(kind="session", repository_id=repository_id, session_id=item.session.session_id)
            for item in _ordered_sessions(sessions)
        )
    return rows


def _repository_display_name(scan: ScanResult, repository_id: str) -> str:
    sessions = scan.sessions_by_repository[repository_id]
    if not sessions:
        return repository_id
    return redact_text(sessions[0].repository.display_name)


def _repository_numbers(rows: list[VisibleRow]) -> tuple[dict[str, int], int]:
    numbers: dict[str, int] = {}
    count = 0
    for row in rows:
        if row.kind == "repository":
            count += 1
            numbers[row.repository_id] = count
    return numbers, len(str(count)) + 1


def _session_titles(scan: ScanResult) -> dict[str, str]:
    return {
        item.session.session_id: redact_text(item.session.title or item.session.session_id)
        for item in scan.resolved_sessions
    }


def _sessions_by_id(scan: ScanResult) -> dict[str, AgentSession]:
    return {item.session.session_id: item.session for item in scan.resolved_sessions}


def build_filtered_rows(
    scan: ScanResult,
    expanded_repositories: set[str],
    *,
    query: str,
) -> list[VisibleRow]:
    needle = query.strip().casefold()
    if not needle:
        return build_visible_rows(scan, expanded_repositories)
    titles = _session_titles(scan)
    rows: list[VisibleRow] = []
    for repository_id, sessions in _ordered_repositories(scan):
        repository_matches = needle in _repository_display_name(scan, repository_id).casefold()
        matching_sessions = [
            item for item in sessions if needle in titles[item.session.session_id].casefold()
        ]
        if not repository_matches and not matching_sessions:
            continue
        rows.append(VisibleRow(kind="repository", repository_id=repository_id))
        visible_sessions = sessions if repository_matches else matching_sessions
        rows.extend(
            VisibleRow(kind="session", repository_id=repository_id, session_id=item.session.session_id)
            for item in _ordered_sessions(visible_sessions)
        )
    return rows


def _visible_window(
    rows: list[VisibleRow],
    *,
    cursor: int,
    terminal_height: int,
    reserved_lines: int,
) -> tuple[list[tuple[int, VisibleRow]], int, int]:
    if not rows:
        return [], 0, 0
    capacity = max(0, terminal_height - reserved_lines - 4)
    if capacity == 0:
        return [], 0, len(rows)
    if len(rows) <= capacity:
        return list(enumerate(rows)), 0, 0
    cursor = min(max(cursor, 0), len(rows) - 1)
    start = min(max(0, cursor - capacity // 2), len(rows) - capacity)
    end = start + capacity
    return list(enumerate(rows[start:end], start=start)), start, len(rows) - end


def _render_search_status(console: Console, query: str, searching: bool) -> None:
    if searching or query:
        _print_viewport_line(console, f"Search: {query}{'_' if searching else ''}", style="dim")


def _scan_warning_label(scan: ScanResult) -> str | None:
    if not scan.warnings and not scan.failed_session_count:
        return None
    parts = []
    if scan.failed_session_count:
        parts.append(f"{scan.failed_session_count} session(s) failed to load")
    if scan.warnings:
        parts.append(f"{len(scan.warnings)} warning(s)")
    return "⚠ " + "   ".join(parts)


def _review_header(selection: SelectionState) -> str:
    counts = f"Review Sessions   {selection.selected_count} / {selection.total_count} selected"
    if not selection.total_volume:
        return counts
    volume = f"{selection.selected_volume} / {volume_label(selection.total_volume)}"
    return f"{counts} │ {volume}"


def render_session_review(
    console: Console,
    selection: SelectionState,
    *,
    expanded_repositories: set[str],
    cursor: int,
    message: str | None = None,
    query: str = "",
    searching: bool = False,
) -> None:
    _print_header(console, _review_header(selection), subtitle=_REVIEW_SUBTITLE)
    warning_label = _scan_warning_label(selection.scan)
    if warning_label:
        _print_viewport_line(console, warning_label, style="yellow")
    if message:
        _print_viewport_line(console, message)
    _render_search_status(console, query, searching)
    hints = [
        "↑↓ jk", "←→ hl", "Space Toggle", "a All", "n None", "g Generate",
        "p Preview", "e Exclude repo", "R Rescan", "/ Search", "? Help", "b Back",
    ]
    console.print()
    rows = build_filtered_rows(selection.scan, expanded_repositories, query=query)
    visible, hidden_above, hidden_below = _visible_window(
        rows,
        cursor=cursor,
        terminal_height=console.size.height,
        reserved_lines=(3 if message else 2)
        + _header_lines(console, _REVIEW_SUBTITLE)
        + len(_hint_lines(hints, console.size.width))
        + (1 if warning_label else 0)
        + (1 if searching or query else 0),
    )
    if hidden_above:
        _print_viewport_line(console, f"↑ {hidden_above} more", style="dim")
    titles = _session_titles(selection.scan)
    sessions = _sessions_by_id(selection.scan)
    metas = {
        row.session_id: session_row_meta(
            sessions[row.session_id], selection.scan.period.since.tzinfo,
            noise_reason(sessions[row.session_id]),
        )
        for _, row in visible if row.session_id is not None
    }
    repository_numbers, number_width = _repository_numbers(rows)
    bar_scale = _bar_scale(selection.scan, rows, console_width=console.size.width)
    tree: list[_ListRow] = []
    for index, row in visible:
        cursor_here = index == cursor
        if row.kind == "repository":
            expanded = row.repository_id in expanded_repositories or bool(query)
            mark = selection.repository_mark(row.repository_id)
            selected_count = sum(
                item.session.session_id in selection.selected_session_ids
                for item in selection.scan.sessions_by_repository[row.repository_id]
            )
            total = len(selection.scan.sessions_by_repository[row.repository_id])
            name = _repository_display_name(selection.scan, row.repository_id)
            volume = sum(
                message_volume(item.session)
                for item in selection.scan.sessions_by_repository[row.repository_id]
            )
            tree.append(
                _ListRow(
                    lead=Text.assemble(
                        _cursor_glyph(cursor_here), " ",
                        f"{repository_numbers[row.repository_id]:>{number_width - 1}}.", " ",
                        _expansion_glyph(expanded), " ", _bar_cell(bar_scale, volume),
                        _mark_glyph(mark), " ",
                    ),
                    title=f"{name}   {selected_count} / {total}",
                    meta=repository_meta(row.repository_id, selection.scan),
                    selected=cursor_here,
                )
            )
        else:
            assert row.session_id is not None
            mark = SelectionMark.ALL if row.session_id in selection.selected_session_ids else SelectionMark.NONE
            tree.append(
                _ListRow(
                    lead=Text.assemble(
                        _cursor_glyph(cursor_here), " ", " " * number_width, " ", " ", " ",
                        _bar_cell(bar_scale, message_volume(sessions[row.session_id])),
                        _mark_glyph(mark), " ",
                    ),
                    title=titles[row.session_id],
                    meta=metas[row.session_id],
                    selected=cursor_here,
                )
            )
    _print_list_rows(console, tree)
    if hidden_below:
        _print_viewport_line(console, f"↓ {hidden_below} more", style="dim")
    console.print()
    _print_hints(console, hints)


def _browser_header(scan: ScanResult) -> str:
    sessions = f"Browse Sessions   {scan.loaded_session_count} sessions"
    volume = scan_volume(scan)
    if not volume:
        return sessions
    return f"{sessions} │ {volume_label(volume)}"


def render_session_browser(
    console: Console,
    scan: ScanResult,
    *,
    expanded_repositories: set[str],
    cursor: int,
    query: str = "",
    searching: bool = False,
) -> None:
    _print_header(console, _browser_header(scan), subtitle=_BROWSE_SUBTITLE)
    warning_label = _scan_warning_label(scan)
    if warning_label:
        _print_viewport_line(console, warning_label, style="yellow")
    _render_search_status(console, query, searching)
    hints = ["↑↓ jk", "←→ hl", "p Preview", "R Rescan", "/ Search", "? Help", "b Back"]
    console.print()
    rows = build_filtered_rows(scan, expanded_repositories, query=query)
    visible, hidden_above, hidden_below = _visible_window(
        rows,
        cursor=cursor,
        terminal_height=console.size.height,
        reserved_lines=2 + _header_lines(console, _BROWSE_SUBTITLE)
        + len(_hint_lines(hints, console.size.width))
        + (1 if warning_label else 0)
        + (1 if searching or query else 0),
    )
    if hidden_above:
        _print_viewport_line(console, f"↑ {hidden_above} more", style="dim")
    titles = _session_titles(scan)
    sessions = _sessions_by_id(scan)
    metas = {
        row.session_id: session_row_meta(sessions[row.session_id], scan.period.since.tzinfo)
        for _, row in visible if row.session_id is not None
    }
    repository_numbers, number_width = _repository_numbers(rows)
    bar_scale = _bar_scale(scan, rows, console_width=console.size.width)
    tree: list[_ListRow] = []
    for index, row in visible:
        cursor_here = index == cursor
        if row.kind == "repository":
            expanded = row.repository_id in expanded_repositories or bool(query)
            name = _repository_display_name(scan, row.repository_id)
            count = len(scan.sessions_by_repository[row.repository_id])
            volume = sum(message_volume(item.session) for item in scan.sessions_by_repository[row.repository_id])
            tree.append(
                _ListRow(
                    lead=Text.assemble(
                        _cursor_glyph(cursor_here), " ",
                        f"{repository_numbers[row.repository_id]:>{number_width - 1}}.", " ",
                        _expansion_glyph(expanded), " ", _bar_cell(bar_scale, volume),
                    ),
                    title=f"{name}   {count}",
                    meta=repository_meta(row.repository_id, scan),
                    selected=cursor_here,
                )
            )
        else:
            assert row.session_id is not None
            tree.append(
                _ListRow(
                    lead=Text.assemble(
                        _cursor_glyph(cursor_here), " ", " " * number_width, " ", " ", " ",
                        _bar_cell(bar_scale, message_volume(sessions[row.session_id])),
                    ),
                    title=titles[row.session_id],
                    meta=metas[row.session_id],
                    selected=cursor_here,
                )
            )
    _print_list_rows(console, tree)
    if hidden_below:
        _print_viewport_line(console, f"↓ {hidden_below} more", style="dim")
    console.print()
    _print_hints(console, hints)


def render_report_result(
    console: Console,
    *, period: DateRange, repository_count: int, session_count: int,
    output_path: Path | None, selected: int, dry_run: bool = False,
) -> None:
    _print_header(console, "✓ Dry run complete" if dry_run else "✓ Report generated")
    console.print()
    _print_viewport_line(console, f"Period         {_period_label(period)}")
    _print_viewport_line(console, f"Repositories   {repository_count}")
    _print_viewport_line(console, f"Sessions       {session_count}")
    output = "Not written (dry run)" if dry_run else str(output_path)
    _print_viewport_line(console, f"Output         {output}")
    console.print()
    for index, label in enumerate(report_result_options(dry_run=dry_run)):
        _print_option_line(console, label, index, selected)
    console.print()
    _print_hints(console, ["↑↓ jk", "Enter Select", "? Help", "q Menu"])


def render_report_preview(console: Console, *, content: str, offset: int) -> None:
    _print_header(console, "Report Preview")
    console.print()
    lines = content.splitlines() or [""]
    capacity = report_preview_capacity(console.size.height)
    max_start = max(0, len(lines) - capacity) if capacity else len(lines)
    start = min(max(offset, 0), max_start)
    end = min(len(lines), start + capacity)
    if start:
        _print_viewport_line(console, f"↑ {start} more", style="dim")
    for line in lines[start:end]:
        _print_viewport_line(console, line)
    if end < len(lines):
        _print_viewport_line(console, f"↓ {len(lines) - end} more", style="dim")
    _print_hints(console, ["↑↓ jk Scroll", "PgUp/PgDn", "g/G Top/Bottom", "? Help", "b Back"])


_ACTIVITY_LABELS = {
    ActivityType.USER_MESSAGE: "You",
    ActivityType.ASSISTANT_MESSAGE: "Assistant",
    ActivityType.TOOL_CALL: "Tool call",
    ActivityType.TOOL_RESULT: "Tool result",
    ActivityType.COMMAND: "Command",
    ActivityType.FILE_CHANGE: "File change",
    ActivityType.ERROR: "Error",
    ActivityType.SYSTEM: "System",
}


def build_session_preview_lines(session: AgentSession) -> list[str]:
    lines: list[str] = []
    lines.append(redact_text((session.title or "").strip() or session.session_id))
    if session.working_directory:
        lines.append(redact_text(session.working_directory))
    if session.branch:
        lines.append(f"branch: {redact_text(session.branch)}")
    volume = message_volume(session)
    if volume:
        lines.append(volume_label(volume))
    lines.append("")
    for activity in session.activities:
        label = _ACTIVITY_LABELS.get(activity.activity_type, activity.activity_type.value)
        if activity.tool_name:
            label = f"{label}: {redact_text(activity.tool_name)}"
        stamp = f"[{activity.timestamp:%m-%d %H:%M}] " if activity.timestamp else ""
        lines.append(f"{stamp}{label}")
        content = redact_text(activity.content).strip()
        if content:
            lines.extend(f"  {content_line}" for content_line in content.splitlines())
    return lines


def render_session_preview(console: Console, session: AgentSession, *, offset: int) -> None:
    _print_header(console, "Session Preview")
    console.print()
    lines = build_session_preview_lines(session) or [""]
    capacity = report_preview_capacity(console.size.height)
    max_start = max(0, len(lines) - capacity) if capacity else len(lines)
    start = min(max(offset, 0), max_start)
    end = min(len(lines), start + capacity)
    if start:
        _print_viewport_line(console, f"↑ {start} more", style="dim")
    for line in lines[start:end]:
        _print_viewport_line(console, line)
    if end < len(lines):
        _print_viewport_line(console, f"↓ {len(lines) - end} more", style="dim")
    _print_hints(console, ["↑↓ jk Scroll", "PgUp/PgDn", "g/G Top/Bottom", "? Help", "b Back"])


def _detail_window(
    lines: list[str], *, offset: int, capacity: int
) -> tuple[list[str], int, int]:
    if capacity <= 0 or not lines:
        return [], 0, len(lines)
    offset = min(max(offset, 0), max(0, len(lines) - 1))
    hidden_above = offset
    indicator_slots = 1 if hidden_above else 0
    body_capacity = max(0, capacity - indicator_slots)
    end = min(len(lines), offset + body_capacity)
    hidden_below = len(lines) - end
    if hidden_below and body_capacity > 0:
        body_capacity -= 1
        end = min(len(lines), offset + body_capacity)
        hidden_below = len(lines) - end
    return lines[offset:end], hidden_above, hidden_below


def recoverable_error_detail_capacity(terminal_height: int, option_count: int, console_width: int) -> int:
    footer_lines = len(_hint_lines(_ERROR_HINTS, console_width))
    return max(0, terminal_height - option_count - 6 - footer_lines)


def render_recoverable_error(
    console: Console,
    *, title: str, detail: str, options: list[str], selected: int, detail_offset: int = 0,
) -> None:
    _print_header(console, f"✗ {title}")
    console.print()
    lines = redact_text(detail).splitlines() or [""]
    visible, hidden_above, hidden_below = _detail_window(
        lines,
        offset=detail_offset,
        capacity=recoverable_error_detail_capacity(
            console.size.height, len(options), console.size.width
        ),
    )
    if hidden_above:
        _print_viewport_line(console, f"↑ {hidden_above} more detail lines", style="dim")
    for line in visible:
        _print_viewport_line(console, line)
    if hidden_below:
        _print_viewport_line(console, f"↓ {hidden_below} more detail lines", style="dim")
    console.print()
    for index, label in enumerate(options):
        _print_option_line(console, label, index, selected)
    console.print()
    _print_hints(console, _ERROR_HINTS)


def render_help(console: Console) -> None:
    _print_header(console, "Keyboard shortcuts")
    console.print()
    for line in (
        "↑↓ / jk        Move selection or scroll one line",
        "←→ / hl        Collapse / expand tree rows or change setup values",
        "Enter / Space  Activate / toggle",
        "PgUp / PgDn    Scroll error details or report preview by a page",
        "g / G          Jump to top / bottom in report preview",
        "p              Preview a session's transcript",
        "e              Exclude a repository from future scans (Review only)",
        "R              Rescan sessions",
        "/              Search repositories and session titles",
        "?              Open this help",
        "b / Esc        Back",
        "q              Main menu / quit from main menu",
        "Ctrl-C         Cancel the current operation and go back",
    ):
        _print_viewport_line(console, line)
    console.print()
    _print_hints(console, ["b / Esc / Enter Back"])
