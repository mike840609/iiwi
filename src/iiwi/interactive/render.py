"""Pure Rich rendering for the interactive Iiwi screens."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from iiwi import __version__
from iiwi.history import HistoryEntry, HistoryKind
from iiwi.interactive.daily_review import (
    TODAY_MORE_SECTION,
    YESTERDAY_MORE_SECTION,
    DailyReviewRow,
    visible_daily_review_rows,
)
from iiwi.interactive.density import (
    is_subagent,
    last_activity_at,
    message_volume,
    repository_meta,
    session_meta,
    volume_label,
)
from iiwi.interactive.models import ReportDraft, Screen
from iiwi.interactive.selection import SelectionMark, SelectionState, noise_reason
from iiwi.interactive.settings import SettingsRow
from iiwi.models.daily import (
    DailySection,
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.models.outcome import (
    Outcome,
    OutcomeBucket,
    OutcomeOrigin,
    OutcomeReviewDraft,
)
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


@dataclass(frozen=True)
class OutcomeReviewRow:
    kind: str
    outcome_id: str | None = None


_MAIN_OPTIONS = [
    "Review Activity",
    "Daily Standup",
    "Generate Report",
    "History",
    "Check Setup",
    "Settings",
]
# The main menu explains what each option does, the way mole's menu does: one
# dim clause per row, aligned under the widest label.
_MAIN_DESCRIPTIONS = {
    "Review Activity": "Explore sessions by repository",
    "Daily Standup": "Draft yesterday, today and blockers",
    "Generate Report": "Configure and produce a report",
    "History": "List past reports and their paths",
    "Check Setup": "Diagnose the harness setup",
    "Settings": "Edit saved settings",
}
# Keep the common choices visible and put the lower-frequency report knobs
# behind a disclosure row so the default setup remains quick to scan.
_PRIMARY_SETUP_FIELDS = ["Harness", "Period"]
_ADVANCED_SETUP_FIELDS = ["Detail", "Subagents", "Narrative", "Sanitize"]
_ADVANCED_ROW = "Advanced settings"
# Report setup begins with its one terminal action. Previewing lives on Quick
# Review, one screen later, where the outcomes it would render are on screen.
_GENERATE_ROW = "Generate report"
_ACTION_ROWS = [_GENERATE_ROW]
_SETTINGS_LABEL = "Settings"
_SETUP_LABEL_CELLS = 18
# Each row's name and value say what it is set to, never what it does. One line
# under the cursor's row carries that, rather than seven lines of it at once.
_SETUP_HELP = {
    "Harness": "Which coding agent's sessions to read: OpenCode, Claude Code or Codex.",
    "Period": "The date window the report covers.",
    "Advanced settings": "Show or hide less common report options.",
    "Detail": "Full keeps every section. Brief drops files, sessions and usage.",
    "Subagents": "Include sessions spawned as subagents, or only the ones you started.",
    "Narrative": "Write the prose review with the local opencode run, or emit structure only.",
    "Sanitize": "Ask OpenCode to redact session content on export.",
    "Generate report": "Scan the period and produce the report.",
}
# The settings editor explains each row's purpose on the detail line; the
# row itself always shows its value, never what it does.
_SETTINGS_HELP = {
    "harnesses.opencode.enabled": "False makes --harness opencode fail with a configuration error.",
    "harnesses.opencode.source": "Source identifier; only cli is implemented.",
    "harnesses.opencode.cli.executable": "The opencode executable name or path.",
    "harnesses.opencode.cli.timeout_seconds": "Timeout for opencode commands.",
    "harnesses.opencode.cli.run_timeout_seconds": (
        "How long one opencode run may take before falling back."
    ),
    "harnesses.opencode.cli.model": "Model passed to opencode run; empty uses opencode's default.",
    "harnesses.opencode.cli.sanitize": "Ask opencode export to redact session content.",
    "harnesses.claude_code.enabled": "False forbids reading ~/.claude/projects.",
    "harnesses.claude_code.projects_directory": (
        "Directory holding Claude Code session transcripts."
    ),
    "harnesses.codex.enabled": "False forbids reading ~/.codex.",
    "harnesses.codex.home_directory": "Directory holding the Codex state database and sessions.",
    "report.timezone": "Calendar-week and timestamp timezone; Enter types any IANA zone.",
    "report.output_directory": (
        "Default Markdown output directory; relative paths resolve against "
        "where Iiwi runs."
    ),
    "report.exclude_repositories": "Comma-separated repository ids left out of every scan.",
    "report.quick_review_report_type": "Default Quick Review audience.",
    "report.quick_review_max_evidence_bytes": (
        "Largest evidence payload one Quick Review run may send."
    ),
}
_RESULT_OPTIONS = ["Back to main menu", "Generate another report", "Print report path"]
_ERROR_HINTS = [
    "↑↓ jk",
    "PgUp/PgDn Detail",
    "Enter Select",
    "? Help",
    "b Back",
]
_MARKERS = {
    SelectionMark.ALL: "●",
    SelectionMark.NONE: "○",
    SelectionMark.PARTIAL: "◐",
}
# Three glyphs sit side by side carrying three unrelated meanings, so colour is
# what tells them apart. Plain ANSI names only, to follow the terminal's theme.
_MARK_STYLES = {
    SelectionMark.ALL: "green",
    SelectionMark.NONE: "dim",
    SelectionMark.PARTIAL: "yellow",
}
_CURSOR_STYLE = "bold cyan"
# The cursor row takes the cursor's own colour, so where the cursor sits reads as
# one thing. The action keeps its role colour when it is not the cursor row.
_ACTION_STYLE = "cyan"
# The expansion arrow recedes behind the glyphs that carry a decision.
_EXPANSION_STYLE = "dim"
_ROW_GAP = 3
_MIN_TITLE_CELLS = 12
# Aware, so it orders against the aware UTC timestamps the harnesses record.
_UNDATED = datetime.min.replace(tzinfo=UTC)
# mole-style visual language: a ▶ cursor, a ═ rule under each screen title, and
# a single pipe-separated status bar. The bar scale is shared by every row on
# screen, so one glyph column means one thing.
_CURSOR = "▶"
_RULE_CHAR = "═"
_HINT_SEPARATOR = " │ "
_BAR_FULL = "█"
_BAR_EMPTY = "░"
_BAR_CELLS = 12
_BAR_STYLE = "cyan"
# The one place a hard-coded colour belongs: a wordmark is identity, not state,
# so it should not repaint itself per terminal theme the way the functional
# colours above deliberately do. ʻIʻiwi vermilion; Rich degrades it on terminals
# without truecolor. Nothing that carries meaning wears it -- red stays free for
# errors, and a red cursor beside the green/yellow marks would not survive
# red-green colour blindness. Not bold: terminals answer bold with their bright
# variant, which is what makes a saturated red glare -- so the fix is dropping
# bold, not dulling the hue. A half-step off the bird's actual plumage, ΔE 8.9
# from it and still reading as the same red, clearing 4.6:1 on both a black and
# a white terminal.
_WORDMARK_STYLE = "#D93B28"
_PERCENT_CELLS = 4  # "100%" at its widest
# Bars are the first thing to go on a narrow terminal: the title column matters
# more than the decoration.
_MIN_BAR_WIDTH = 80
# ponytail: the guidance line is the first chrome to go on a short terminal, the same
# trade the bar column makes on a narrow one — content outranks decoration. Below this
# height the list would otherwise render zero rows.
_MIN_SUBTITLE_HEIGHT = 16
_MAIN_SUBTITLE = "See what your agent did"
# The main menu opens on the name, drawn rather than written, when the terminal
# can spend four rows on it. A partial wordmark reads as noise, so both gates are
# all-or-nothing: below either one the one-line title comes back unchanged.
_WORDMARK = (
    " ___ _        _",
    "|_ _(_)_ __ _(_)",
    " | || \\ V  V / |",
    "|___|_|\\_/\\_/|_|",
)
_MIN_WORDMARK_HEIGHT = 24
# 16 cells of wordmark plus `v0.0.0` on the same row, with a gap between them.
_MIN_WORDMARK_WIDTH = 24
# Where to file a bug, one Cmd-click away in a terminal that supports OSC 8 and
# still readable as text in one that does not.
_PROJECT_URL = "https://github.com/mike840609/iiwi"
_PROJECT_LABEL = "github.com/mike840609/iiwi"
_REVIEW_SUBTITLE = "Select sessions to include in the report:"
# The two disclosure rows live in the same expansion set as the per-outcome
# evidence toggles, so they need ids no outcome can own. Defined once here and
# imported by the controller, because the cursor and the highlight must key off
# the same two strings.
MORE_CANDIDATES_SECTION = "__more_candidates__"
UNGROUPED_CANDIDATES_SECTION = "__ungrouped_candidates__"
_OUTCOME_REVIEW_HINTS = [
    "↑↓ jk",
    "Space Include",
    "e Edit",
    "J/K Reorder",
    "v Evidence",
    "s Split",
    "a Add",
    "p Preview",
    "g Generate",
    "? Help",
    "b Back",
]
_DAILY_REVIEW_HINTS = [
    "↑↓ jk",
    "Space Include",
    "e Edit",
    "J/K Reorder",
    "v Evidence",
    "a Add",
    "p Preview",
    "g Generate",
    "? Help",
    "b Back",
]
_DAILY_RESULT_OPTIONS = ["Back to main menu", "Print report path"]
_DAILY_SOURCE_LABELS: dict[DailyStatementSource, str | None] = {
    DailyStatementSource.ACTIVITY_YESTERDAY: None,
    DailyStatementSource.ACTIVITY_TODAY: "Activity today",
    DailyStatementSource.SUGGESTED_FROM_YESTERDAY: "Suggested from yesterday",
    DailyStatementSource.DETECTED_BLOCKER: "Detected blocker",
    DailyStatementSource.USER_ADDED: "User added",
}


def main_menu_options() -> list[str]:
    """Return the main-menu actions in display order."""

    return list(_MAIN_OPTIONS)


def report_setup_rows(*, advanced: bool = True) -> list[str]:
    """Return setup actions and settings in keyboard-navigation order."""

    rows = [*_ACTION_ROWS, *_PRIMARY_SETUP_FIELDS, _ADVANCED_ROW]
    if advanced:
        rows.extend(_ADVANCED_SETUP_FIELDS)
    return rows


def report_generate_row() -> str:
    """Return the write-to-disk action label."""

    return _GENERATE_ROW


def _option(label: str, index: int, selected: int) -> str:
    return f"{_CURSOR if index == selected else ' '} {label}"


def _print_viewport_line(
    console: Console,
    value: str,
    *,
    style: str = "",
) -> None:
    """Print exactly one display line, truncating rather than wrapping."""

    console.print(
        Text(value, style=style),
        no_wrap=True,
        overflow="ellipsis",
    )


def _print_viewport_text(console: Console, text: Text) -> None:
    """Print a pre-composed row, truncating rather than wrapping."""
    console.print(text, no_wrap=True, overflow="ellipsis")


def _print_header(console: Console, title: str, *, subtitle: str | None = None) -> None:
    """Print the screen title, a rule under it, and an optional subtitle below that."""
    _print_viewport_line(console, title, style="bold")
    _print_viewport_line(console, _RULE_CHAR * console.size.width, style="dim")
    if subtitle and console.size.height >= _MIN_SUBTITLE_HEIGHT:
        _print_viewport_line(console, subtitle, style="dim")


def _header_lines(console: Console, subtitle: str | None) -> int:
    """How many lines `_print_header` will actually spend, so reservations match."""
    return 3 if subtitle and console.size.height >= _MIN_SUBTITLE_HEIGHT else 2


def _hint_lines(hints: list[str], width: int) -> list[str]:
    """Pack hints into as few ` │ `-joined lines as the width allows."""

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
    """Lay the hints out as mole's single status bar, wrapping only when forced.

    Truncating would silently drop `q Quit` off the right edge on a narrow
    terminal, so an over-long bar takes a second line instead.
    """
    for line in _hint_lines(hints, console.size.width):
        _print_viewport_line(console, line, style="dim")


def outcome_review_rows(draft: OutcomeReviewDraft) -> list[OutcomeReviewRow]:
    """Return every structural Quick Review row in display order.

    More and ungrouped outcomes remain in this structural list so callers can
    preserve their identity. Rendering filters those children until their
    disclosure row is open.
    """

    ordered = draft.ordered()
    rows = [OutcomeReviewRow("settings")]
    rows.extend(
        OutcomeReviewRow("outcome", outcome.id)
        for outcome in ordered
        if outcome.bucket is OutcomeBucket.PRIMARY
    )
    more = [outcome for outcome in ordered if outcome.bucket is OutcomeBucket.MORE]
    if more:
        rows.append(OutcomeReviewRow("more"))
        rows.extend(OutcomeReviewRow("outcome", outcome.id) for outcome in more)
    ungrouped = [
        outcome for outcome in ordered if outcome.bucket is OutcomeBucket.UNGROUPED
    ]
    if ungrouped:
        rows.append(OutcomeReviewRow("ungrouped"))
        rows.extend(OutcomeReviewRow("outcome", outcome.id) for outcome in ungrouped)
    rows.extend(
        [
            OutcomeReviewRow("blockers"),
            OutcomeReviewRow("next_week"),
            OutcomeReviewRow("preview"),
            OutcomeReviewRow("generate"),
        ]
    )
    return rows


def visible_outcome_review_rows(
    draft: OutcomeReviewDraft,
    expanded_evidence: set[str],
) -> list[OutcomeReviewRow]:
    """Return the Quick Review rows actually on screen, in cursor order.

    This is the one list the cursor addresses and the highlight paints, so the
    controller navigates it rather than deriving its own copy.
    """

    outcomes = {outcome.id: outcome for outcome in draft.outcomes}
    more_open = MORE_CANDIDATES_SECTION in expanded_evidence
    ungrouped_open = UNGROUPED_CANDIDATES_SECTION in expanded_evidence
    visible: list[OutcomeReviewRow] = []
    for row in outcome_review_rows(draft):
        if row.kind != "outcome" or row.outcome_id is None:
            visible.append(row)
            continue
        outcome = outcomes[row.outcome_id]
        if outcome.bucket is OutcomeBucket.MORE and not more_open:
            continue
        if outcome.bucket is OutcomeBucket.UNGROUPED and not ungrouped_open:
            continue
        visible.append(row)
    return visible


@dataclass(frozen=True)
class _OutcomeReviewBlock:
    row: OutcomeReviewRow
    lines: list[Text]


def _single_line(value: str) -> str:
    """Collapse hard line breaks in fields whose viewport contract is one row."""

    return " ".join(value.splitlines())


def _daily_display_text(value: str) -> str:
    """Redact and flatten one Daily field for the screen.

    safe_daily_text() layers Markdown escaping on top of this, which belongs in
    the written artifact and nowhere near a terminal: the reviewer would read
    their own edit back as `the \\_private\\_ helper`. _daily_evidence_lines
    already renders repository ids this way, so this is also what stops the two
    panes disagreeing about the same string.
    """

    return _single_line(redact_text(value))


def _truncated_text(text: Text, width: int) -> Text:
    fitted = text.copy()
    fitted.truncate(max(1, width), overflow="ellipsis")
    return fitted


def _labelled_wrapped_lines(
    console: Console,
    *,
    indent: str,
    label: str,
    value: str,
    style: str = "",
    limit: int | None = None,
) -> list[Text]:
    """Wrap a value beside a fixed label and return its actual display lines."""

    prefix = f"{indent}{label:<12}"
    available = max(1, console.size.width - cell_len(prefix))
    wrapped = list(
        Text(value, style=style).wrap(
            console,
            available,
            overflow="fold",
            no_wrap=False,
        )
    ) or [Text("")]
    if limit is not None:
        truncated = len(wrapped) > limit
        wrapped = wrapped[:limit]
        if truncated and wrapped:
            wrapped[-1].append("…", style=style)
    lines: list[Text] = []
    for index, value_line in enumerate(wrapped):
        lead = prefix if index == 0 else " " * cell_len(prefix)
        lines.append(
            _truncated_text(Text.assemble((lead, "dim"), value_line), console.size.width)
        )
    return lines


def _outcome_summary(outcome: Outcome, *, focused: bool, width: int) -> Text:
    style = _CURSOR_STYLE if focused else ""
    summary = Text.assemble(
        (_CURSOR if focused else " ", style),
        " ",
        ("●" if outcome.included else "○", "green" if outcome.included else "dim"),
        " ",
    )
    if outcome.origin is OutcomeOrigin.USER_ADDED:
        summary.append("User-added ", style="magenta")
    if outcome.bucket is OutcomeBucket.UNGROUPED:
        summary.append("Ungrouped ", style="yellow")
    summary.append(_single_line(outcome.title), style=style)
    return _truncated_text(summary, width)


def _evidence_detail_lines(console: Console, outcome: Outcome) -> list[Text]:
    lines: list[Text] = []
    for reference in outcome.evidence_refs:
        values = [
            ("Repository", reference.repository_id),
            ("Session", reference.session_id),
            ("Commit", reference.commit),
            ("File", reference.file),
        ]
        lines.extend(
            _labelled_wrapped_lines(
                console,
                indent="      ",
                label=label,
                value=_single_line(redact_text(value)),
                limit=1,
            )[0]
            for label, value in values
            if value
        )
    return lines


def _outcome_block(
    console: Console,
    outcome: Outcome,
    *,
    focused: bool,
    evidence_expanded: bool,
    evidence_details: bool = True,
    impact_line_limit: int | None = None,
) -> list[Text]:
    lines = [_outcome_summary(outcome, focused=focused, width=console.size.width)]
    if not focused:
        return lines
    status = outcome.status.value.replace("_", " ").capitalize()
    lines.extend(
        _labelled_wrapped_lines(
            console,
            indent="    ",
            label="Status",
            value=status,
            limit=1,
        )
    )
    impact = outcome.impact.strip()
    lines.extend(
        _labelled_wrapped_lines(
            console,
            indent="    ",
            label="Impact",
            value=impact or "Unsupported by extracted evidence",
            style="" if impact else "dim",
            limit=impact_line_limit,
        )
    )
    reference_count = len(outcome.evidence_refs)
    evidence = f"{reference_count} reference{'s' if reference_count != 1 else ''}"
    lines.extend(
        _labelled_wrapped_lines(
            console,
            indent="    ",
            label="Evidence",
            value=evidence,
            limit=1,
        )
    )
    if evidence_expanded and evidence_details:
        lines.extend(_evidence_detail_lines(console, outcome))
    return lines


def _review_control_line(
    draft: OutcomeReviewDraft,
    row: OutcomeReviewRow,
    *,
    focused: bool,
    expanded_evidence: set[str],
    width: int,
) -> Text:
    cursor = _CURSOR if focused else " "
    style = _CURSOR_STYLE if focused else ""
    if row.kind == "settings":
        assert draft.detail is not None
        value = f"{draft.report_type.value.title()} │ {draft.detail.value.title()}"
        text = Text.assemble((f"{cursor} Report       ", style), (value, style))
    elif row.kind == "more":
        open_ = MORE_CANDIDATES_SECTION in expanded_evidence
        text = Text(f"{cursor} {'▾' if open_ else '▸'} More candidates", style=style)
    elif row.kind == "ungrouped":
        open_ = UNGROUPED_CANDIDATES_SECTION in expanded_evidence
        text = Text(f"{cursor} {'▾' if open_ else '▸'} Ungrouped candidates", style=style)
    elif row.kind == "blockers":
        value = _single_line(draft.blockers or "Not set")
        text = Text(f"{cursor} Blockers    {value}", style=style)
    elif row.kind == "next_week":
        value = _single_line(draft.next_week or "Not set")
        text = Text(f"{cursor} Next week   {value}", style=style)
    elif row.kind == "preview":
        text = Text(f"{cursor} Preview report", style=style or _ACTION_STYLE)
    elif row.kind == "generate":
        text = Text(f"{cursor} Generate report", style=style or _ACTION_STYLE)
    else:
        raise ValueError(f"Unknown outcome review row: {row.kind}")
    return _truncated_text(text, width)


def _build_outcome_review_blocks(
    console: Console,
    draft: OutcomeReviewDraft,
    rows: list[OutcomeReviewRow],
    *,
    cursor: int,
    expanded_evidence: set[str],
    focused_capacity: int,
) -> list[_OutcomeReviewBlock]:
    outcomes = {outcome.id: outcome for outcome in draft.outcomes}
    blocks: list[_OutcomeReviewBlock] = []
    for index, row in enumerate(rows):
        focused = index == cursor
        if row.kind != "outcome":
            lines = [
                _review_control_line(
                    draft,
                    row,
                    focused=focused,
                    expanded_evidence=expanded_evidence,
                    width=console.size.width,
                )
            ]
        else:
            assert row.outcome_id is not None
            outcome = outcomes[row.outcome_id]
            lines = _outcome_block(
                console,
                outcome,
                focused=focused,
                evidence_expanded=row.outcome_id in expanded_evidence,
            )
            if focused and len(lines) > focused_capacity:
                lines = _outcome_block(
                    console,
                    outcome,
                    focused=True,
                    evidence_expanded=row.outcome_id in expanded_evidence,
                    evidence_details=False,
                )
            if focused and len(lines) > focused_capacity:
                lines = _outcome_block(
                    console,
                    outcome,
                    focused=True,
                    evidence_expanded=False,
                    evidence_details=False,
                    impact_line_limit=1,
                )
        blocks.append(_OutcomeReviewBlock(row=row, lines=lines))
    return blocks


def _outcome_block_window(
    blocks: list[_OutcomeReviewBlock],
    *,
    cursor: int,
    capacity: int,
) -> tuple[int, int]:
    """Choose the largest contiguous block window containing the focus."""

    best: tuple[int, int] | None = None
    best_score: tuple[int, int, int] | None = None
    for start in range(cursor, -1, -1):
        used = 0
        for end in range(start, len(blocks)):
            used += len(blocks[end].lines)
            if not (start <= cursor <= end):
                continue
            indicators = int(start > 0) + int(end < len(blocks) - 1)
            if used + indicators > capacity:
                continue
            count = end - start + 1
            score = (count, used, -abs((start + end) - (2 * cursor)))
            if best_score is None or score > best_score:
                best = (start, end + 1)
                best_score = score
    if best is not None:
        return best
    return cursor, cursor + 1


def _outcome_review_body(
    blocks: list[_OutcomeReviewBlock],
    *,
    start: int,
    end: int,
    cursor: int,
    capacity: int,
) -> list[Text]:
    """Compose the printed body, clamped to ``capacity`` display lines.

    ``_outcome_block_window`` fits every window it can find, but the focused
    block can still be taller than the budget once the shrink rungs run out —
    at 40x14 with both disclosure sections open it is. Rather than grow another
    rung, the frame sheds here: the scroll indicators go first, then the focused
    block's trailing detail lines. Its summary line is what says where the
    cursor is, so that one never goes.
    """

    above = Text(f"↑ {start} more", style="dim") if start > 0 else None
    below = Text(f"↓ {len(blocks) - end} more", style="dim") if end < len(blocks) else None
    window = [list(block.lines) for block in blocks[start:end]]

    def used() -> int:
        return (
            sum(len(lines) for lines in window)
            + (above is not None)
            + (below is not None)
        )

    if used() > capacity and above is not None:
        above = None
    if used() > capacity and below is not None:
        below = None
    focused = cursor - start
    if used() > capacity and 0 <= focused < len(window):
        keep = max(1, len(window[focused]) - (used() - capacity))
        window[focused] = window[focused][:keep]

    body: list[Text] = []
    if above is not None:
        body.append(above)
    for lines in window:
        body.extend(lines)
    if below is not None:
        body.append(below)
    return body[:capacity]


def render_outcome_review(
    console: Console,
    draft: OutcomeReviewDraft,
    *,
    cursor: int,
    expanded_evidence: set[str],
    period: DateRange | None = None,
    message: str | None = None,
) -> None:
    """Render Quick Review inside one terminal frame using display-line budgets."""

    rows = visible_outcome_review_rows(draft, expanded_evidence)
    cursor = min(max(0, cursor), max(0, len(rows) - 1))
    hints = _hint_lines(_OUTCOME_REVIEW_HINTS, console.size.width)
    terminal_budget = max(0, console.size.height - 1)
    fixed_lines = 2 + 2 + len(hints) + int(message is not None)
    body_capacity = max(1, terminal_budget - fixed_lines)
    indicator_floor = int(cursor > 0) + int(cursor < len(rows) - 1)
    focused_capacity = max(1, body_capacity - indicator_floor)
    blocks = _build_outcome_review_blocks(
        console,
        draft,
        rows,
        cursor=cursor,
        expanded_evidence=expanded_evidence,
        focused_capacity=focused_capacity,
    )
    start, end = _outcome_block_window(blocks, cursor=cursor, capacity=body_capacity)

    selected = sum(outcome.included for outcome in draft.outcomes)
    period_suffix = f"  {_period_label(period)}" if period is not None else ""
    _print_viewport_text(
        console,
        _truncated_text(
            Text.assemble(
                ("Quick Review", "bold"),
                (period_suffix, "dim"),
                (f"  {selected} selected", "dim"),
            ),
            console.size.width,
        ),
    )
    _print_viewport_text(
        console,
        _truncated_text(Text(_RULE_CHAR * console.size.width, style="dim"), console.size.width),
    )
    console.print()
    if message is not None:
        _print_viewport_text(
            console,
            _truncated_text(
                Text(_single_line(message), style="yellow"),
                console.size.width,
            ),
        )
    body = _outcome_review_body(
        blocks,
        start=start,
        end=end,
        cursor=cursor,
        capacity=body_capacity,
    )
    for line in body:
        _print_viewport_text(console, _truncated_text(line, console.size.width))
    console.print()
    _print_hints(console, _OUTCOME_REVIEW_HINTS)


@dataclass(frozen=True)
class _DailyReviewBlock:
    row: DailyReviewRow
    lines: list[Text]


def _daily_section_item(
    draft: DailyStandupDraft,
    row: DailyReviewRow,
) -> tuple[DailyStandupWorkItem, DailySectionItem]:
    assert row.work_item_id is not None
    return next(
        pair
        for pair in draft.ordered_items(row.section)
        if pair[0].id == row.work_item_id
    )


def _daily_section_line(
    draft: DailyStandupDraft,
    row: DailyReviewRow,
    *,
    focused: bool,
    width: int,
) -> Text:
    selected = sum(item.included for _, item in draft.ordered_items(row.section))
    label = {
        DailySection.YESTERDAY: "Yesterday",
        DailySection.TODAY: "Today",
        DailySection.BLOCKERS: "Blockers",
    }[row.section]
    style = _CURSOR_STYLE if focused else "bold"
    return _truncated_text(
        Text(f"{_CURSOR if focused else ' '} {label}  {selected} selected", style=style),
        width,
    )


def _daily_more_line(
    row: DailyReviewRow,
    *,
    focused: bool,
    expanded: set[str],
    width: int,
) -> Text:
    disclosure = {
        DailySection.YESTERDAY: YESTERDAY_MORE_SECTION,
        DailySection.TODAY: TODAY_MORE_SECTION,
    }[row.section]
    style = _CURSOR_STYLE if focused else ""
    return _truncated_text(
        Text(
            f"{_CURSOR if focused else ' '} {'▾' if disclosure in expanded else '▸'} "
            "More candidates",
            style=style,
        ),
        width,
    )


def _daily_evidence_lines(
    console: Console,
    work_item: DailyStandupWorkItem,
    item: DailySectionItem,
) -> list[Text]:
    lines: list[Text] = []
    if work_item.repository_ids:
        lines.extend(
            _labelled_wrapped_lines(
                console,
                indent="      ",
                label="Repository",
                value=", ".join(redact_text(value) for value in work_item.repository_ids),
                limit=1,
            )
        )
    for reference in item.evidence_refs:
        values = (
            ("Harness", reference.harness),
            ("Session", reference.session_id),
            ("Commit", reference.commit),
            ("File", reference.file),
        )
        for label, value in values:
            if value:
                lines.extend(
                    _labelled_wrapped_lines(
                        console,
                        indent="      ",
                        label=label,
                        value=_single_line(redact_text(value)),
                        limit=1,
                    )
                )
    return lines


def _daily_item_block(
    console: Console,
    work_item: DailyStandupWorkItem,
    item: DailySectionItem,
    *,
    focused: bool,
    evidence_expanded: bool,
) -> list[Text]:
    style = _CURSOR_STYLE if focused else ""
    repositories = ""
    if work_item.repository_ids:
        repository_text = _truncated_text(
            Text(
                f"[{', '.join(_daily_display_text(value) for value in work_item.repository_ids)}]"
            ),
            max(8, min(18, console.size.width // 3)),
        )
        repositories = f"{repository_text.plain} "
    summary = Text.assemble(
        (_CURSOR if focused else " ", style),
        " ",
        ("●" if item.included else "○", "green" if item.included else "dim"),
        " ",
        (repositories, "dim"),
        (_daily_display_text(item.statement), style),
    )
    source_label = _DAILY_SOURCE_LABELS[item.source]
    labels = [source_label] if source_label is not None else []
    if item.new_activity:
        labels.append("New activity")
    lines = [_truncated_text(summary, console.size.width)]
    if labels:
        lines.append(
            _truncated_text(
                Text(f"      {' │ '.join(labels)}", style="dim"),
                console.size.width,
            )
        )
    if focused and evidence_expanded:
        lines.extend(_daily_evidence_lines(console, work_item, item))
    return lines


def _build_daily_review_blocks(
    console: Console,
    draft: DailyStandupDraft,
    rows: list[DailyReviewRow],
    *,
    cursor: int,
    expanded: set[str],
    focused_capacity: int,
) -> list[_DailyReviewBlock]:
    blocks: list[_DailyReviewBlock] = []
    for index, row in enumerate(rows):
        focused = index == cursor
        if row.kind == "section":
            lines = [
                _daily_section_line(
                    draft,
                    row,
                    focused=focused,
                    width=console.size.width,
                )
            ]
        elif row.kind == "more":
            lines = [
                _daily_more_line(
                    row,
                    focused=focused,
                    expanded=expanded,
                    width=console.size.width,
                )
            ]
        else:
            work_item, item = _daily_section_item(draft, row)
            lines = _daily_item_block(
                console,
                work_item,
                item,
                focused=focused,
                evidence_expanded=work_item.id in expanded,
            )
            if focused and len(lines) > focused_capacity:
                lines = lines[: max(1, focused_capacity)]
        blocks.append(_DailyReviewBlock(row=row, lines=lines))
    return blocks


def _daily_block_window(
    blocks: list[_DailyReviewBlock],
    *,
    cursor: int,
    capacity: int,
) -> tuple[int, int]:
    """Choose the largest contiguous Daily block window containing focus."""

    best: tuple[int, int] | None = None
    best_score: tuple[int, int, int] | None = None
    for start in range(cursor, -1, -1):
        used = 0
        for end in range(start, len(blocks)):
            used += len(blocks[end].lines)
            if not start <= cursor <= end:
                continue
            indicators = int(start > 0) + int(end < len(blocks) - 1)
            if used + indicators > capacity:
                continue
            score = (end - start + 1, used, -abs((start + end) - 2 * cursor))
            if best_score is None or score > best_score:
                best = (start, end + 1)
                best_score = score
    return best if best is not None else (cursor, cursor + 1)


def _daily_review_body(
    blocks: list[_DailyReviewBlock],
    *,
    start: int,
    end: int,
    cursor: int,
    capacity: int,
) -> list[Text]:
    above = Text(f"↑ {start} more", style="dim") if start > 0 else None
    below = (
        Text(f"↓ {len(blocks) - end} more", style="dim")
        if end < len(blocks)
        else None
    )
    window = [list(block.lines) for block in blocks[start:end]]

    def used() -> int:
        return sum(len(lines) for lines in window) + int(above is not None) + int(
            below is not None
        )

    if used() > capacity:
        above = None
    if used() > capacity:
        below = None
    focused = cursor - start
    if used() > capacity and 0 <= focused < len(window):
        window[focused] = window[focused][: max(1, len(window[focused]) - used() + capacity)]

    body: list[Text] = []
    if above is not None:
        body.append(above)
    for lines in window:
        body.extend(lines)
    if below is not None:
        body.append(below)
    return body[:capacity]


_DAILY_WARNING_LINES = 3


def _daily_warning_lines(draft: DailyStandupDraft) -> list[str]:
    """Return a bounded warning block for the Daily frame.

    `draft.warnings` merges every scanner's warnings across every enabled
    harness — one per session with timestamp-less activities, one per fallback
    repository identity — so 25 is an ordinary day. Printing all of them
    overflows the viewport no matter what `body_capacity` clamps to, which is
    why the count is capped here and reflected in `fixed_lines`. Coverage
    warnings come first so a harness outage is never the line that gets
    collapsed.
    """

    warnings = [*draft.coverage_warnings, *draft.warnings]
    if len(warnings) <= _DAILY_WARNING_LINES:
        return [f"Warning: {redact_text(warning)}" for warning in warnings]
    shown = warnings[: _DAILY_WARNING_LINES - 1]
    remaining = len(warnings) - len(shown)
    return [
        *(f"Warning: {redact_text(warning)}" for warning in shown),
        f"Warning: {remaining} more warning(s) not shown",
    ]


def render_daily_review(
    console: Console,
    draft: DailyStandupDraft,
    *,
    cursor: int,
    expanded: set[str],
    message: str | None = None,
) -> None:
    """Render Daily Quick Review within the current terminal viewport."""

    rows = visible_daily_review_rows(draft, expanded)
    cursor = min(max(0, cursor), max(0, len(rows) - 1))
    hints = _hint_lines(_DAILY_REVIEW_HINTS, console.size.width)
    terminal_budget = max(0, console.size.height - 1)
    warning_lines = _daily_warning_lines(draft)
    fixed_lines = 4 + len(hints) + len(warning_lines) + int(message is not None)
    body_capacity = max(1, terminal_budget - fixed_lines)
    focused_capacity = max(
        1,
        body_capacity - int(cursor > 0) - int(cursor < len(rows) - 1),
    )
    blocks = _build_daily_review_blocks(
        console,
        draft,
        rows,
        cursor=cursor,
        expanded=expanded,
        focused_capacity=focused_capacity,
    )
    start, end = _daily_block_window(blocks, cursor=cursor, capacity=body_capacity)

    suffix = "  Fallback draft" if draft.fallback else ""
    _print_viewport_text(
        console,
        _truncated_text(
            Text.assemble(
                (f"Daily Standup — {draft.standup_date:%b %d}", "bold"),
                (suffix, "yellow"),
            ),
            console.size.width,
        ),
    )
    _print_viewport_line(console, _RULE_CHAR * console.size.width, style="dim")
    console.print()
    for warning in warning_lines:
        _print_viewport_line(console, _single_line(warning), style="yellow")
    if message is not None:
        _print_viewport_line(
            console,
            _single_line(redact_text(message)),
            style="yellow",
        )
    for line in _daily_review_body(
        blocks,
        start=start,
        end=end,
        cursor=cursor,
        capacity=body_capacity,
    ):
        _print_viewport_text(console, _truncated_text(line, console.size.width))
    console.print()
    _print_hints(console, _DAILY_REVIEW_HINTS)


def daily_result_options() -> list[str]:
    """Return the Daily result actions in keyboard order."""

    return list(_DAILY_RESULT_OPTIONS)


def render_daily_result(
    console: Console,
    *,
    output_path: Path | None,
    selected: int,
) -> None:
    """Render the first-class Daily generation result."""

    _print_header(console, "✓ Daily Standup generated")
    console.print()
    _print_viewport_line(console, f"Output         {output_path}")
    console.print()
    for index, label in enumerate(daily_result_options()):
        _print_option_line(console, label, index, selected)
    console.print()
    _print_hints(console, ["↑↓ jk", "Enter Select", "? Help", "q Back"])


@dataclass(frozen=True)
class _BarScale:
    """One scale shared by every row on screen. ``cells == 0`` disables the column."""

    peak: int  # max repository volume in the filtered set
    total: int  # total volume in the filtered set
    cells: int  # _BAR_CELLS, or 0 when disabled


def _bar_scale(
    scan: ScanResult,
    rows: list[VisibleRow],
    *,
    console_width: int,
) -> _BarScale:
    volumes = [
        sum(message_volume(item.session) for item in scan.sessions_by_repository[row.repository_id])
        for row in rows
        if row.kind == "repository"
    ]
    total = sum(volumes)
    enabled = bool(total) and console_width >= _MIN_BAR_WIDTH
    return _BarScale(peak=max(volumes, default=0), total=total, cells=_BAR_CELLS if enabled else 0)


def _bar_cell(scale: _BarScale, volume: int) -> Text:
    """Return the pre-styled bar+percent block."""
    if not scale.cells:
        return Text("")
    filled = 0 if not volume else max(1, round(volume / scale.peak * scale.cells))
    filled = min(filled, scale.cells)
    percent = f"{volume / scale.total:.0%}" if scale.total else ""
    block = Text.assemble(
        (_BAR_FULL * filled, _BAR_STYLE),
        (_BAR_EMPTY * (scale.cells - filled), "dim"),
        " ",
        (f"{percent:>{_PERCENT_CELLS}}", "dim"),
        " ",
    )
    return block


def session_row_meta(
    session: AgentSession,
    tz: tzinfo | None,
    reason: str | None = None,
) -> str:
    """Compose the dim right-hand metadata for one session row."""
    facts = " │ ".join(fact for fact in (session_meta(session, tz), reason) if fact)
    if not is_subagent(session):
        return facts
    return f"[sub] {facts}" if facts else "[sub]"


def _cursor_glyph(active: bool) -> tuple[str, str]:
    """The cursor holds column 0 on both row kinds, so the left edge never moves."""

    return (_CURSOR, _CURSOR_STYLE) if active else (" ", "")


def _expansion_glyph(expanded: bool) -> tuple[str, str]:
    return ("▾" if expanded else "▸", _EXPANSION_STYLE)


def _mark_glyph(mark: SelectionMark) -> tuple[str, str]:
    return _MARKERS[mark], _MARK_STYLES[mark]


@dataclass(frozen=True)
class _ListRow:
    """One tree row, decomposed so both kinds lay out against the same columns."""

    lead: Text
    title: str
    meta: str
    selected: bool


def _meta_column_width(rows: list[_ListRow], *, console_width: int) -> int:
    """Width of the metadata column every visible row shares.

    Measured across both kinds, because a per-kind width is exactly how the
    repository and session rows drifted onto different columns. The cap keeps
    the widest lead's title above its floor: one very long session's metadata
    would otherwise starve every title on screen, the whole column with it.
    """

    widest_meta = max((cell_len(row.meta) for row in rows), default=0)
    widest_lead = max((row.lead.cell_len for row in rows), default=0)
    affordable = console_width - widest_lead - _ROW_GAP - _MIN_TITLE_CELLS
    return min(widest_meta, max(0, affordable))


def _list_row(row: _ListRow, *, meta_width: int, console_width: int) -> Text:
    """Left-align the title in a fixed column, with dim metadata in its own column.

    The title absorbs truncation so the metadata column holds still: a ragged
    left edge on the titles is what makes a long list hard to scan. Metadata too
    wide for the shared column is dropped rather than squeezed, so a narrow
    terminal never leaves a row as an ellipsis with no name in it. The lead
    arrives pre-styled, its glyphs already separated by role.
    """
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
    """Print a tree, every row laid against the one metadata column it shares."""

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
    """The setup row names the window as well as dating it, so `Last week` and
    `Last 7 days` stop looking like the same thing on a Saturday."""

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


def report_result_options() -> list[str]:
    """Return the actions shown on the result screen."""

    return list(_RESULT_OPTIONS)


def report_preview_capacity(terminal_height: int) -> int:
    """Content lines available while reserving the terminal's final display row."""

    return max(0, terminal_height - 8)


def history_capacity(terminal_height: int) -> int:
    """History rows that fit while reserving the header, blanks, and hints."""

    return max(0, terminal_height - 8)


def _print_wordmark(console: Console) -> None:
    """Print the wordmark, carrying the version flush right on its last row so
    the art costs four lines rather than five."""

    version = f"v{__version__}"
    for line in _WORDMARK[:-1]:
        _print_viewport_line(console, line, style=_WORDMARK_STYLE)
    last = _WORDMARK[-1]
    padding = console.size.width - cell_len(last) - cell_len(version)
    _print_viewport_text(
        console,
        Text.assemble((last, _WORDMARK_STYLE), " " * padding, (version, "dim")),
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
        # The wordmark's height gate already clears _MIN_SUBTITLE_HEIGHT.
        _print_viewport_line(console, _MAIN_SUBTITLE, style="dim")
    elif cell_len(title) + 1 + cell_len(version) <= console.size.width:
        padding = console.size.width - cell_len(title) - cell_len(version)
        title_line = Text.assemble((title, "bold"), " " * padding, (version, "dim"))
        _print_viewport_text(console, title_line)
        _print_viewport_line(console, _RULE_CHAR * console.size.width, style="dim")
        if console.size.height >= _MIN_SUBTITLE_HEIGHT:
            _print_viewport_line(
                console,
                _MAIN_SUBTITLE,
                style="dim",
            )
    else:
        _print_header(
            console,
            "Iiwi",
            subtitle=_MAIN_SUBTITLE,
        )
    # The link is chrome of the same rank as the subtitle, so it lives or dies
    # with it; truncated to half a URL it would read as neither.
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
        title = Text(label, style=_CURSOR_STYLE if focused else "")
        description = _MAIN_DESCRIPTIONS[label]
        if cell_len(description) <= console.size.width - lead.cell_len - label_width - _ROW_GAP:
            title.truncate(label_width, overflow="ellipsis", pad=True)
            text = Text.assemble(lead, title, " " * _ROW_GAP, (description, "dim"))
        else:
            text = Text.assemble(lead, title)
        _print_viewport_text(console, text)
    console.print()
    _print_hints(
        console,
        ["↑↓ jk", "Enter Select", "1-6", "? Help", "q Quit"],
    )


def _setup_value(draft: ReportDraft, field: str) -> str:
    """The current value shown beside one setting's name."""
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
    raise ValueError(f"Unknown report setup field: {field}")


def _setup_help(draft: ReportDraft, row: str) -> str:
    """The line describing what one row does, not what it is set to."""
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
    rows = report_setup_rows(advanced=advanced)
    for index, action in enumerate(_ACTION_ROWS):
        focused = selected == index
        _print_viewport_line(
            console,
            f"{_CURSOR if focused else ' '} {action}",
            style=_CURSOR_STYLE if focused else _ACTION_STYLE,
        )
    console.print()
    if console.size.height >= _MIN_SUBTITLE_HEIGHT:
        _print_viewport_line(console, f"  {_SETTINGS_LABEL}", style="bright_black")
    settings_start = len(_ACTION_ROWS)
    for index, field in enumerate(rows[settings_start:], start=settings_start):
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
        if field in _ADVANCED_SETUP_FIELDS:
            line = (
                f"{cursor}   {field:<{_SETUP_LABEL_CELLS - 2}}"
                f"{_setup_value(draft, field)}"
            )
        else:
            line = f"{cursor} {field:<{_SETUP_LABEL_CELLS}}{_setup_value(draft, field)}"
        _print_viewport_line(console, line, style=style)
    console.print()
    _print_viewport_line(console, _setup_help(draft, rows[selected]), style="dim")
    console.print()
    _print_hints(
        console,
        [
            "↑↓ jk",
            "←→ Change",
            "r Review",
            "g Generate",
            "? More",
            "b Back",
        ],
    )


def _settings_value_text(row: SettingsRow) -> Text:
    """The value column: every choice with the active one highlighted, or the
    current value — never blank."""
    if row.show_all:
        parts: list[Text] = []
        for index, choice in enumerate(row.choices):
            if index:
                parts.append(Text(" / "))
            parts.append(
                Text(choice, style=_CURSOR_STYLE if choice == row.value else "dim")
            )
        text = Text.assemble(*parts)
        if row.locked:
            return Text.assemble(text, ("  [environment]", "dim"))
        return text
    value = Text(row.value) if row.value else Text("(default)", style="dim")
    if row.locked:
        return Text.assemble(value, ("  [environment]", "dim"))
    return value


def settings_capacity(terminal_height: int, *, editing: bool = False) -> int:
    """Settings display lines that fit while the footer stays on screen.

    Chrome: title and rule (2), a blank before and after the list, the detail
    line (1, or 2 while editing), a blank before the hints, the hint bar, and
    the terminal's final display row. The subtitle adds one line at the height
    that shows it, and the inline editor's value line adds one more.
    """

    chrome = 8 + (1 if terminal_height >= _MIN_SUBTITLE_HEIGHT else 0) + (1 if editing else 0)
    return max(0, terminal_height - chrome)


def settings_display_count(rows: list[SettingsRow]) -> int:
    """Settings body lines: one per row, plus a header per section and a blank
    line separating sections."""

    count = 0
    previous_section = ""
    for row in rows:
        if row.section and row.section != previous_section:
            if previous_section:
                count += 1
            count += 1
            previous_section = row.section
        count += 1
    return count


def settings_display_index(rows: list[SettingsRow], row_index: int) -> int:
    """Display-list position of ``rows[row_index]``, counting headers and blanks."""

    display = 0
    previous_section = ""
    for index, row in enumerate(rows):
        if row.section and row.section != previous_section:
            if previous_section:
                display += 1
            display += 1
            previous_section = row.section
        if index == row_index:
            return display
        display += 1
    return display


def settings_display_offset(
    rows: list[SettingsRow],
    row_index: int,
    *,
    offset: int,
    capacity: int,
) -> int:
    """Clamp the settings viewport so the selected row stays visible.

    Mirrors ``_history_key``'s clamp, in display space. Up to two display slots
    go to the ↑/↓ indicators, so they are reserved before the selected row is
    placed; when everything fits no scrolling is needed.
    """

    if capacity <= 0 or not rows:
        return 0
    count = settings_display_count(rows)
    selected = settings_display_index(rows, row_index)
    if count <= capacity:
        return 0
    body = max(1, capacity - 2)
    if row_index == 0:
        return 0
    offset = min(max(offset, 0), selected)
    offset = min(offset, max(0, count - body))
    if selected >= offset + body:
        offset = max(0, selected - body + 1)
    return offset


def _settings_display_items(
    rows: list[SettingsRow],
    *,
    selected: int,
    label_cells: int,
) -> list[Text]:
    """Every body line the list renders: section headers, separators, and rows."""

    items: list[Text] = []
    previous_section = ""
    for index, row in enumerate(rows):
        if row.section and row.section != previous_section:
            if previous_section:
                items.append(Text(""))
            items.append(Text(f"  {row.section}", style="bright_black"))
            previous_section = row.section
        focused = selected == index
        lead = Text(_CURSOR if focused else " ", style=_CURSOR_STYLE if focused else "")
        label = Text(f"{row.label:<{label_cells}}", style=_CURSOR_STYLE if focused else "")
        items.append(Text.assemble(lead, " ", label, "  ", _settings_value_text(row)))
    return items


def _settings_window(
    display: list[Text],
    *,
    offset: int,
    capacity: int,
) -> tuple[list[Text], int, int]:
    """Slice the settings body, with ↑/↓ indicators taking slots like _detail_window."""

    count = len(display)
    if capacity <= 0 or not display:
        return [], 0, count
    offset = min(max(offset, 0), max(0, count - 1))
    hidden_above = offset
    body_capacity = max(0, capacity - (1 if hidden_above else 0))
    end = min(count, offset + body_capacity)
    hidden_below = count - end
    if hidden_below and body_capacity > 0:
        body_capacity -= 1
        end = min(count, offset + body_capacity)
        hidden_below = count - end
    return display[offset:end], hidden_above, hidden_below


def render_settings(
    console: Console,
    *,
    rows: list[SettingsRow],
    selected: int,
    file_path: str,
    editing: bool = False,
    edit_value: str = "",
    error: str | None = None,
    offset: int = 0,
) -> None:
    """The saved-settings editor: one row per setting, values always visible.

    The list scrolls like history: the selected row and the footer (detail line
    plus hints) always stay on screen, and ↑/↓ indicators mark clipped lines.
    """

    _print_header(console, "Settings")
    if console.size.height >= _MIN_SUBTITLE_HEIGHT:
        _print_viewport_line(
            console,
            f"  Settings file: {file_path}",
            style="bright_black",
        )
    console.print()
    label_cells = max((cell_len(row.label) for row in rows), default=0)
    capacity = settings_capacity(console.size.height, editing=editing)
    offset = settings_display_offset(rows, selected, offset=offset, capacity=capacity)
    display = _settings_display_items(rows, selected=selected, label_cells=label_cells)
    visible, hidden_above, hidden_below = _settings_window(
        display,
        offset=offset,
        capacity=capacity,
    )
    if hidden_above:
        _print_viewport_line(console, f"↑ {hidden_above} more", style="dim")
    for item in visible:
        _print_viewport_text(console, item)
    if hidden_below:
        _print_viewport_line(console, f"↓ {hidden_below} more", style="dim")
    console.print()
    row = rows[selected]
    if editing:
        _print_viewport_line(
            console,
            f"  {row.key} [{row.value}]: {edit_value}",
            style=_CURSOR_STYLE,
        )
        detail = error or f"{row.key} - Enter keeps the value; empty restores the default."
        _print_viewport_line(console, f"  {detail}", style="dim")
    else:
        detail = error or (
            f"Set by the {row.variable} environment variable."
            if row.locked
            else _SETTINGS_HELP.get(row.key, "")
        )
        _print_viewport_line(console, f"  {detail}", style="dim")
    console.print()
    _print_hints(
        console,
        ["Enter Keep", "Esc Cancel", "? Help"]
        if editing
        else ["↑↓ jk", "←→ Cycle", "Enter Edit", "? Help", "b Back"],
    )


def _session_recency(session: AgentSession) -> datetime:
    """Undated sessions sort last, and never reach a ``None`` comparison."""

    timestamp = last_activity_at(session)
    return _UNDATED if timestamp is None else timestamp


def _repository_recency(sessions: list[ResolvedSession]) -> datetime:
    return max((_session_recency(item.session) for item in sessions), default=_UNDATED)


def _ordered_repositories(scan: ScanResult) -> list[tuple[str, list[ResolvedSession]]]:
    """Order repositories by most recent activity first, then by display name.

    Recency alone is a partial order, so equal timestamps would otherwise settle
    into whatever order the scan happened to yield. Sorting is stable, so the
    name pass runs first and the recency pass keeps it as the tie-break. The id
    joins that key because redaction can map two distinct repositories onto the
    same display name, which would leave the order arbitrary again.
    """

    by_name = sorted(
        scan.sessions_by_repository.items(),
        key=lambda item: (_repository_display_name(scan, item[0]), item[0]),
    )
    return sorted(by_name, key=lambda item: _repository_recency(item[1]), reverse=True)


def _ordered_sessions(sessions: list[ResolvedSession]) -> list[ResolvedSession]:
    """Order a repository's sessions by most recent activity first, then by id."""

    by_id = sorted(sessions, key=lambda item: item.session.session_id)
    return sorted(by_id, key=lambda item: _session_recency(item.session), reverse=True)


def build_visible_rows(
    scan: ScanResult,
    expanded_repositories: set[str],
) -> list[VisibleRow]:
    rows: list[VisibleRow] = []
    for repository_id, sessions in _ordered_repositories(scan):
        rows.append(VisibleRow(kind="repository", repository_id=repository_id))
        if repository_id not in expanded_repositories:
            continue
        rows.extend(
            VisibleRow(
                kind="session",
                repository_id=repository_id,
                session_id=item.session.session_id,
            )
            for item in _ordered_sessions(sessions)
        )
    return rows


def _repository_display_name(scan: ScanResult, repository_id: str) -> str:
    sessions = scan.sessions_by_repository[repository_id]
    if not sessions:
        return repository_id
    return redact_text(sessions[0].repository.display_name)


def _repository_numbers(rows: list[VisibleRow]) -> tuple[dict[str, int], int]:
    """Number repositories in filtered display order, plus the shared column width.

    The number is an absolute display index, so a repository keeps its number
    while the viewport scrolls underneath. The width covers every visible repo:
    ``len(str(count))`` digits plus the dot, so the column holds still at 9 and
    at 10 repositories.
    """
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
    return {
        item.session.session_id: item.session for item in scan.resolved_sessions
    }


def build_filtered_rows(
    scan: ScanResult,
    expanded_repositories: set[str],
    *,
    query: str,
) -> list[VisibleRow]:
    """Build tree rows filtered by repository name or session title."""

    needle = query.strip().casefold()
    if not needle:
        return build_visible_rows(scan, expanded_repositories)

    titles = _session_titles(scan)
    rows: list[VisibleRow] = []
    for repository_id, sessions in _ordered_repositories(scan):
        repository_matches = needle in _repository_display_name(scan, repository_id).casefold()
        matching_sessions = [
            item
            for item in sessions
            if needle in titles[item.session.session_id].casefold()
        ]
        if not repository_matches and not matching_sessions:
            continue
        rows.append(VisibleRow(kind="repository", repository_id=repository_id))
        visible_sessions = sessions if repository_matches else matching_sessions
        rows.extend(
            VisibleRow(
                kind="session",
                repository_id=repository_id,
                session_id=item.session.session_id,
            )
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
    """Keep the active row visible without allowing long scans to flood the terminal."""

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
        label = f"Search: {query}{'_' if searching else ''}"
        _print_viewport_line(console, label, style="dim")


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
    """Compose the Review Sessions title, volume clause included.

    A scan can legitimately be all tool-call activity, and a ``0 / 0 msgs``
    suffix is noise, so the clause is dropped rather than shown empty.
    """
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
    _print_header(
        console,
        _review_header(selection),
        subtitle=_REVIEW_SUBTITLE,
    )
    warning_label = _scan_warning_label(selection.scan)
    if warning_label:
        _print_viewport_line(console, warning_label, style="yellow")
    if message:
        _print_viewport_line(console, message)
    _render_search_status(console, query, searching)
    hints = [
        "↑↓ jk",
        "Space Select",
        "p Inspect",
        "/ Search",
        "g Report",
        "? More",
        "b Back",
    ]
    console.print()
    rows = build_filtered_rows(selection.scan, expanded_repositories, query=query)
    visible, hidden_above, hidden_below = _visible_window(
        rows,
        cursor=cursor,
        terminal_height=console.size.height,
        reserved_lines=(3 if message else 2) + _header_lines(console, _REVIEW_SUBTITLE)
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
            sessions[row.session_id],
            selection.scan.period.since.tzinfo,
            noise_reason(sessions[row.session_id]),
        )
        for _, row in visible
        if row.session_id is not None
    }
    repository_numbers, number_width = _repository_numbers(rows)
    bar_scale = _bar_scale(selection.scan, rows, console_width=console.size.width)
    tree: list[_ListRow] = []
    for index, row in visible:
        cursor_here = index == cursor
        if row.kind == "repository":
            expanded = row.repository_id in expanded_repositories or bool(query)
            mark = selection.repository_mark(row.repository_id)
            selected = sum(
                item.session.session_id in selection.selected_session_ids
                for item in selection.scan.sessions_by_repository[row.repository_id]
            )
            total = len(selection.scan.sessions_by_repository[row.repository_id])
            name = _repository_display_name(selection.scan, row.repository_id)
            volume = sum(
                message_volume(item.session)
                for item in selection.scan.sessions_by_repository[row.repository_id]
            )
            bar_block = _bar_cell(bar_scale, volume)
            tree.append(
                _ListRow(
                    lead=Text.assemble(
                        _cursor_glyph(cursor_here),
                        " ",
                        f"{repository_numbers[row.repository_id]:>{number_width - 1}}.",
                        " ",
                        _expansion_glyph(expanded),
                        " ",
                        bar_block,
                        _mark_glyph(mark),
                        " ",
                    ),
                    title=f"{name}   {selected} / {total}",
                    meta=repository_meta(row.repository_id, selection.scan),
                    selected=cursor_here,
                )
            )
        else:
            assert row.session_id is not None
            mark = (
                SelectionMark.ALL
                if row.session_id in selection.selected_session_ids
                else SelectionMark.NONE
            )
            bar_block = _bar_cell(bar_scale, message_volume(sessions[row.session_id]))
            tree.append(
                _ListRow(
                    lead=Text.assemble(
                        _cursor_glyph(cursor_here),
                        " ",
                        " " * number_width,
                        " ",
                        " ",
                        " ",
                        bar_block,
                        _mark_glyph(mark),
                        " ",
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
    *,
    period: DateRange,
    repository_count: int,
    session_count: int,
    output_path: Path | None,
    selected: int,
    dry_run: bool = False,
) -> None:
    _print_header(
        console,
        "✓ Dry run complete" if dry_run else "✓ Report generated",
    )
    console.print()
    _print_viewport_line(console, f"Period         {_period_label(period)}")
    _print_viewport_line(console, f"Repositories   {repository_count}")
    _print_viewport_line(console, f"Sessions       {session_count}")
    output = "Not written (dry run)" if dry_run else str(output_path)
    _print_viewport_line(console, f"Output         {output}")
    console.print()
    for index, label in enumerate(report_result_options()):
        _print_option_line(console, label, index, selected)
    console.print()
    _print_hints(
        console,
        ["↑↓ jk", "Enter Select", "? Help", "q Back"],
    )


def _history_entry_line(entry: HistoryEntry, *, selected: bool) -> str:
    period = f"{entry.since:%Y-%m-%d} – {entry.until:%Y-%m-%d}"
    is_daily = entry.kind is HistoryKind.DAILY_STANDUP
    label = "Daily Standup" if is_daily else (entry.harness or "")
    narrative = "—" if is_daily else ("narrative" if entry.narrative else "structure")
    return (
        f"{_CURSOR if selected else ' '} "
        f"{entry.generated_at:%Y-%m-%d %H:%M}  {period}  "
        f"{label:>10}  {entry.session_count:>3} sess "
        f"{entry.repository_count:>2} repos  {narrative}  {entry.output_path}"
    )


def render_history(
    console: Console,
    *,
    entries: Sequence[HistoryEntry],
    selected: int,
    offset: int,
) -> None:
    """Render the generated-report log, newest first, as a scrollable list.

    The caller passes entries already ordered newest first. `selected` is the
    cursor's global entry index; `offset` is the first visible entry index.
    """

    _print_header(console, "Past Reports")
    console.print()
    capacity = history_capacity(console.size.height)
    if not entries:
        _print_viewport_line(console, "No reports generated yet.", style="dim")
        console.print()
        _print_hints(
            console,
            ["↑↓ jk Scroll", "? Help", "b Back"],
        )
        return
    end = min(len(entries), offset + capacity)
    for index in range(offset, end):
        _print_viewport_line(
            console,
            _history_entry_line(entries[index], selected=index == selected),
        )
    console.print()
    _print_hints(
        console,
        ["↑↓ jk Scroll", "Enter Path", "PgUp/PgDn", "g/G Top/Bottom", "? Help", "b Back"],
    )


def render_report_preview(console: Console, *, content: str, offset: int) -> None:
    """Render a literal, scrollable dry-run report preview."""

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
    _print_hints(
        console,
        [
            "↑↓ jk Scroll",
            "PgUp/PgDn",
            "g/G Top/Bottom",
            "? Help",
            "b Back",
        ],
    )


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
    """Render one session as scrollable preview lines, redacted before display.

    The preview shows what the session actually said, so it cannot rely on the
    report pipeline's redaction that happens later: every line leaves here
    already scrubbed, the same boundary the CLI's verbose listing uses.
    """
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
        label = _ACTIVITY_LABELS.get(
            activity.activity_type, activity.activity_type.value
        )
        if activity.tool_name:
            label = f"{label}: {redact_text(activity.tool_name)}"
        stamp = f"[{activity.timestamp:%m-%d %H:%M}] " if activity.timestamp else ""
        lines.append(f"{stamp}{label}")
        content = redact_text(activity.content).strip()
        if content:
            lines.extend(f"  {content_line}" for content_line in content.splitlines())
    return lines


def render_session_preview(
    console: Console,
    session: AgentSession,
    *,
    offset: int,
) -> None:
    """Render a scrollable, redacted preview of one session's transcript."""

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
    _print_hints(
        console,
        [
            "↑↓ jk Scroll",
            "PgUp/PgDn",
            "g/G Top/Bottom",
            "? Help",
            "b Back",
        ],
    )


def _detail_window(
    lines: list[str],
    *,
    offset: int,
    capacity: int,
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


def recoverable_error_detail_capacity(
    terminal_height: int,
    option_count: int,
    console_width: int,
) -> int:
    """Rows available for error detail while actions remain visible.

    The footer height is derived from the screen's own hint lines at the given
    width, so the capacity always matches what actually renders.
    """

    footer_lines = len(_hint_lines(_ERROR_HINTS, console_width))
    return max(0, terminal_height - option_count - 6 - footer_lines)


def render_recoverable_error(
    console: Console,
    *,
    title: str,
    detail: str,
    options: list[str],
    selected: int,
    detail_offset: int = 0,
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


# Quick Review overloads four of the general keys, so those four carry a mark
# and the section below says what they do there. Without it the general list
# reads as authoritative on a screen where `a`, `e`, `p` and `g` all differ.
_HELP_LINES = (
    "↑↓ / jk        Move selection or scroll one line",
    "←→ / hl        Collapse / expand tree rows or change setup values",
    "Enter / Space  Activate / toggle",
    "a *            Select all sessions",
    "n              Select no sessions",
    "PgUp / PgDn    Scroll error details or report preview by a page",
    "g * / G        Jump to top / bottom in report preview",
    "G              Group an over-budget selection anyway (Review only)",
    "p *            Preview a session's transcript",
    "e *            Exclude a repository from future scans (Review only)",
    "R              Rescan sessions",
    "/              Search repositories and session titles",
    "?              Open this help",
    "b / Esc        Back",
    "q              Back / quit from the main menu",
    "Ctrl-C         Cancel the current operation and go back",
    "",
    "Quick Review   * these keys mean something else here",
    "Space          Include or exclude the focused outcome",
    "e              Edit the focused outcome's title, status and impact",
    "J / K          Reorder the focused outcome within its section",
    "v              Show or hide the focused outcome's evidence",
    "s              Split a merged outcome into its source groups",
    "a              Add an outcome of your own",
    "p              Preview the report without writing it",
    "g              Generate the report",
)
_DAILY_HELP_LINES = (
    "Daily Quick Review",
    "↑↓ / jk        Move between sections and statements",
    "Space          Include or exclude the focused statement",
    "e              Edit the focused statement",
    "J / K          Reorder the focused statement within its section",
    "v              Show or hide the focused statement's evidence",
    "a              Add a statement to the focused section",
    "p              Preview the Daily Standup without writing it",
    "g              Generate the Daily Standup",
    "?              Open or close this help",
    "b / Esc        Back to the main menu",
    "q              Back to the main menu",
    "Ctrl-C         Cancel the current operation and go back",
)
_HELP_HINTS = ["↑↓ jk Scroll", "b / Esc / Enter Back"]


def help_lines(screen: Screen | None = None) -> list[str]:
    """Return every keyboard-reference line, in display order."""

    if screen is Screen.DAILY_REVIEW:
        return list(_DAILY_HELP_LINES)
    return list(_HELP_LINES)


def help_capacity(terminal_height: int) -> int:
    """Reference lines available beside the help screen's own fixed chrome.

    The list outgrew a short terminal once Quick Review joined it, so it scrolls
    like the previews rather than spilling past the terminal's last row. Six
    lines of chrome: title, rule, two blanks, one hint bar, and the row this
    screen leaves free.
    """

    return max(0, terminal_height - 6)


def render_help(
    console: Console,
    *,
    offset: int = 0,
    screen: Screen | None = None,
) -> None:
    """Render the shared keyboard shortcut reference."""

    _print_header(console, "Keyboard shortcuts")
    console.print()
    visible, hidden_above, hidden_below = _detail_window(
        help_lines(screen),
        offset=offset,
        capacity=help_capacity(console.size.height),
    )
    if hidden_above:
        _print_viewport_line(console, f"↑ {hidden_above} more", style="dim")
    for line in visible:
        _print_viewport_line(console, line)
    if hidden_below:
        _print_viewport_line(console, f"↓ {hidden_below} more", style="dim")
    console.print()
    _print_hints(console, _HELP_HINTS)
