from __future__ import annotations

import re
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.cells import cell_len
from rich.console import Console

import iiwi.history as history_module
from iiwi.history import HistoryEntry
from iiwi.interactive.models import ReportDraft
from iiwi.interactive.render import (
    build_visible_rows,
    history_capacity,
    render_history,
    render_main_menu,
    render_recoverable_error,
    render_report_result,
    render_report_setup,
    render_session_browser,
    render_session_review,
    render_settings,
    report_generate_row,
    report_result_options,
    report_setup_rows,
)
from iiwi.interactive.selection import SelectionState
from iiwi.interactive.settings import TIMEZONE_CHOICES, SettingsRow
from iiwi.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from iiwi.models.session import ActivityType, AgentSession, SessionActivity
from iiwi.models.time_range import DateRange
from iiwi.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


def _console(width: int = 100, height: int | None = None) -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(
            file=stream,
            color_system=None,
            force_terminal=False,
            width=width,
            height=height,
        ),
        stream,
    )


def _color_console(width: int = 100) -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(
            file=stream,
            color_system="truecolor",
            force_terminal=True,
            width=width,
            height=25,
        ),
        stream,
    )


def _row(text: str, needle: str) -> str:
    return next(line for line in text.splitlines() if needle in line)


def _glyph_style(line: str, glyph: str) -> str:
    codes = re.findall(r"\x1b\[([0-9;]*)m", line[: line.index(glyph)])
    return codes[-1] if codes else ""


def _period() -> DateRange:
    return DateRange(
        since=datetime(2026, 8, 3, tzinfo=TZ),
        until=datetime(2026, 8, 10, tzinfo=TZ),
    )


def _resolved(session_id: str, repo: str) -> ResolvedSession:
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id=session_id,
            title=f"Work on {session_id}",
            working_directory=f"/tmp/{repo}",
        ),
        repository=RepositoryIdentity(
            repository_id=repo,
            display_name=repo,
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory=f"/tmp/{repo}",
            resolution_method="test",
        ),
    )


def _selection(
    *,
    failed_session_count: int = 0,
    warnings: list[str] | None = None,
) -> SelectionState:
    sessions = [
        _resolved("ses-a1", "repo-a"),
        _resolved("ses-a2", "repo-a"),
        _resolved("ses-b1", "repo-b"),
    ]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=3,
        loaded_session_count=3,
        failed_session_count=failed_session_count,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions[:2], "repo-b": sessions[2:]},
        warnings=warnings or [],
    )
    state = SelectionState.from_scan(scan)
    state.toggle_session("ses-a2")
    state.toggle_repository("repo-b")
    return state


def test_main_menu_renders_navigation_and_footer() -> None:
    console, stream = _console()

    render_main_menu(console, selected=0)

    text = stream.getvalue()
    assert "|___|_|\\_/\\_/|_|" in text
    assert "▶ Review Activity" in text
    assert "Generate Report" in text
    assert "↑↓ jk" in text
    assert "Enter Select" in text
    assert "q Quit" in text


def test_main_menu_describes_each_option() -> None:
    console, stream = _console()

    render_main_menu(console, selected=0)

    lines = stream.getvalue().splitlines()
    review = next(line for line in lines if "Review Activity" in line)
    generate = next(line for line in lines if "Generate Report" in line)
    setup = next(line for line in lines if "Check Setup" in line)
    settings = next(line for line in lines if "Settings" in line)
    assert "Explore sessions by repository" in review
    assert "Configure and produce a report" in generate
    assert "Diagnose the harness setup" in setup
    assert "Edit saved settings" in settings
    column = review.index("Explore sessions by repository")
    assert generate.index("Configure and produce a report") == column
    assert setup.index("Diagnose the harness setup") == column
    assert settings.index("Edit saved settings") == column


def test_main_menu_orders_history_before_the_non_functional_rows() -> None:
    console, stream = _console()

    render_main_menu(console, selected=0)

    text = stream.getvalue()
    assert "1-6" in text
    assert text.index("History") < text.index("Check Setup")
    assert text.index("Check Setup") < text.index("Settings")


def test_main_menu_describes_history() -> None:
    console, stream = _console()

    render_main_menu(console, selected=0)

    history = next(
        line for line in stream.getvalue().splitlines() if "History" in line
    )
    assert "List past reports and their paths" in history


def test_main_menu_drops_descriptions_on_a_narrow_terminal() -> None:
    console, stream = _console(width=30)

    render_main_menu(console, selected=0)

    text = stream.getvalue()
    assert "Review Activity" in text
    assert "Explore sessions by repository" not in text


def test_report_setup_renders_settings_as_the_navigable_list() -> None:
    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period())

    render_report_setup(console, draft, selected=0)

    text = stream.getvalue()
    assert "Generate Report" in text
    assert "Harness" in text and "OpenCode" in text
    assert "Period" in text
    assert "Advanced settings" in text
    assert "Detail" in text and "Full" in text
    assert "Subagents" in text and "Included" in text
    assert "Narrative" in text and "Enabled" in text
    assert "Sanitize" in text and "Off" in text
    assert "Preview report" not in text
    assert "Dry run" not in text
    assert "▶ Generate report" in text
    assert "  Settings" in text
    assert "g Generate" in text
    assert "r Review" in text
    assert "b Back" in text


def test_session_review_renders_group_marks_expansion_and_controls() -> None:
    console, stream = _console()
    state = _selection()

    render_session_review(
        console,
        state,
        expanded_repositories={"repo-a"},
        cursor=0,
    )

    text = stream.getvalue()
    assert "Review Sessions" in text
    assert "1 / 3 selected" in text
    assert "◐ repo-a" in text
    assert "○ repo-b" in text
    assert "Work on ses-a1" in text
    assert "Work on ses-a2" in text
    assert "Space Select" in text
    assert "g Report" in text
    assert "b Back" in text


def test_session_review_surfaces_scan_warnings() -> None:
    console, stream = _console()
    state = _selection(
        failed_session_count=1,
        warnings=["skipped ses-x1: unreadable transcript"],
    )

    render_session_review(console, state, expanded_repositories=set(), cursor=0)

    text = stream.getvalue()
    assert "⚠" in text
    assert "1 session(s) failed to load" in text
    assert "1 warning(s)" in text


def test_session_review_hides_warning_line_when_scan_is_clean() -> None:
    console, stream = _console()
    state = _selection()

    render_session_review(console, state, expanded_repositories=set(), cursor=0)

    assert "⚠" not in stream.getvalue()


def test_session_review_names_the_period_it_is_filtered_to() -> None:
    """Nothing else on this screen names the window, so without it a quiet week
    and a failed scan render identically."""

    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period(), period_label="Last 7 days")

    render_session_review(
        console,
        _selection(),
        expanded_repositories=set(),
        cursor=0,
        draft=draft,
    )

    text = stream.getvalue()
    assert "Last 7 days ·" in text
    assert "Aug 03 – Aug 10" in text


def test_session_review_without_a_draft_keeps_the_plain_subtitle() -> None:
    console, stream = _console()

    render_session_review(console, _selection(), expanded_repositories=set(), cursor=0)

    text = stream.getvalue()
    assert "Select sessions to include in the report:" in text
    assert "Aug 03" not in text


def test_session_browser_surfaces_scan_warnings() -> None:
    console, stream = _console()
    state = _selection(warnings=["skipped ses-x1: unreadable transcript"])

    render_session_browser(console, state.scan, expanded_repositories=set(), cursor=0)

    text = stream.getvalue()
    assert "⚠" in text
    assert "1 warning(s)" in text


def test_report_result_renders_summary_and_next_actions() -> None:
    console, stream = _console()

    render_report_result(
        console,
        period=_period(),
        repository_count=2,
        session_count=3,
        output_path=Path("reports/worklog.md"),
        selected=0,
    )

    text = stream.getvalue()
    assert "Report generated" in text
    assert "Repositories" in text and "2" in text
    assert "Sessions" in text and "3" in text
    assert "reports/worklog.md" in text
    assert "Back to main menu" in text
    assert "Generate another report" in text
    assert "Print report path" in text


def test_recoverable_error_renders_safe_detail_and_options() -> None:
    console, stream = _console()

    render_recoverable_error(
        console,
        title="Could not read OpenCode sessions",
        detail="session store missing",
        options=["Change harness", "Back", "Main menu"],
        selected=1,
    )

    text = stream.getvalue()
    assert "Could not read OpenCode sessions" in text
    assert "session store missing" in text
    assert "▶ Back" in text


def _dense_resolved(
    session_id: str,
    repo: str,
    *,
    last_day: int,
    volume: int,
    subagent: bool = False,
) -> ResolvedSession:
    activities = [
        SessionActivity(
            activity_id=f"{session_id}:m{i}",
            activity_type=ActivityType.USER_MESSAGE if i == 0 else ActivityType.ASSISTANT_MESSAGE,
            timestamp=datetime(2026, 8, last_day, tzinfo=TZ),
            content="hi",
        )
        for i in range(volume)
    ]
    return ResolvedSession(
        session=AgentSession(
            harness="opencode",
            session_id=session_id,
            title=f"Meta {session_id}",
            parent_session_id="parent" if subagent else None,
            created_at=datetime(2026, 8, last_day, tzinfo=TZ),
            activities=activities,
        ),
        repository=RepositoryIdentity(
            repository_id=repo,
            display_name=repo,
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory=f"/tmp/{repo}",
            resolution_method="test",
        ),
    )


def test_session_review_renders_density_and_subagent_tag() -> None:
    console, stream = _console()
    items = [
        _dense_resolved("d1", "repo-x", last_day=5, volume=2, subagent=True),
        _dense_resolved("d2", "repo-x", last_day=4, volume=1),
    ]
    scan = ScanResult(
        period=_period(), candidate_session_count=2, loaded_session_count=2,
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )
    state = SelectionState.from_scan(scan)

    render_session_review(console, state, expanded_repositories={"repo-x"}, cursor=1)

    text = stream.getvalue()
    assert "Aug 5 │ 2 msgs" in text
    assert "Aug 4 │ 1 msg" in text
    assert "[sub]" in text


def test_session_review_header_totals_selected_and_available_message_volume() -> None:
    console, stream = _console()
    items = [
        _dense_resolved("d1", "repo-x", last_day=5, volume=12),
        _dense_resolved("d2", "repo-x", last_day=4, volume=8),
    ]
    scan = ScanResult(
        period=_period(), candidate_session_count=2, loaded_session_count=2,
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )
    state = SelectionState.from_scan(scan)
    state.toggle_session("d2")

    render_session_review(console, state, expanded_repositories=set(), cursor=0)

    header = stream.getvalue().splitlines()[0]
    assert header == "Review Sessions   1 / 2 selected │ 12 / 20 msgs"


def test_session_review_header_renders_a_lone_message_in_the_singular() -> None:
    console, stream = _console()
    items = [_dense_resolved("d1", "repo-x", last_day=5, volume=1)]
    scan = ScanResult(
        period=_period(), candidate_session_count=1, loaded_session_count=1,
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )

    render_session_review(
        console, SelectionState.from_scan(scan), expanded_repositories=set(), cursor=0,
    )

    header = stream.getvalue().splitlines()[0]
    assert header == "Review Sessions   1 / 1 selected │ 1 / 1 msg"


def test_session_review_header_omits_volume_when_the_scan_holds_no_messages() -> None:
    console, stream = _console()

    render_session_review(console, _selection(), expanded_repositories=set(), cursor=0)

    header = stream.getvalue().splitlines()[0]
    assert header == "Review Sessions   1 / 3 selected"


def test_session_browser_renders_repository_and_session_density() -> None:
    console, stream = _console()
    items = [
        _dense_resolved("d1", "repo-a", last_day=3, volume=1),
        _dense_resolved("d2", "repo-a", last_day=5, volume=2),
    ]
    scan = ScanResult(
        period=_period(), candidate_session_count=2, loaded_session_count=2,
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={"repo-a": items},
    )

    render_session_browser(console, scan, expanded_repositories={"repo-a"}, cursor=0)

    text = stream.getvalue()
    assert "Aug 3–5 │ 3 msgs" in text
    assert "Aug 5 │ 2 msgs" in text


def test_session_browser_header_totals_message_volume() -> None:
    console, stream = _console()
    items = [
        _dense_resolved("d1", "repo-a", last_day=3, volume=1),
        _dense_resolved("d2", "repo-a", last_day=5, volume=2),
    ]
    scan = ScanResult(
        period=_period(), candidate_session_count=2, loaded_session_count=2,
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={"repo-a": items},
    )

    render_session_browser(console, scan, expanded_repositories=set(), cursor=0)

    header = stream.getvalue().splitlines()[0]
    assert header == "Browse Sessions   2 sessions │ 3 msgs"


def test_session_browser_header_omits_volume_when_the_scan_holds_no_messages() -> None:
    console, stream = _console()
    render_session_browser(console, _selection().scan, expanded_repositories=set(), cursor=0)
    header = stream.getvalue().splitlines()[0]
    assert header == "Browse Sessions   3 sessions"


def test_session_review_density_survives_truncation() -> None:
    console, stream = _console(width=40)
    session_id = "trunc1-with-a-very-long-session-title-that-will-clip-at-forty-cells-wide"
    items = [_dense_resolved(session_id, "repo-t", last_day=5, volume=2)]
    scan = ScanResult(
        period=_period(), candidate_session_count=1, loaded_session_count=1,
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={"repo-t": items},
    )
    state = SelectionState.from_scan(scan)

    render_session_review(console, state, expanded_repositories={"repo-t"}, cursor=0)

    text = stream.getvalue()
    assert "Aug 5 │ 2 msgs" in text
    assert f"Meta {session_id}" not in text


def test_session_review_labels_a_deselected_noise_session_with_its_reason() -> None:
    console, stream = _console()
    untitled = ResolvedSession(
        session=AgentSession(
            harness="opencode", session_id="ses-untitled", title=None,
            working_directory="/tmp/repo-a",
        ),
        repository=RepositoryIdentity(
            repository_id="repo-a", display_name="repo-a",
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory="/tmp/repo-a", resolution_method="test",
        ),
    )
    sessions = [_resolved("ses-a1", "repo-a"), untitled]
    scan = ScanResult(
        period=_period(), candidate_session_count=2, loaded_session_count=2,
        failed_session_count=0, resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )

    render_session_review(
        console, SelectionState.from_scan(scan),
        expanded_repositories={"repo-a"}, cursor=0,
    )
    assert "No title" in stream.getvalue()


def test_session_review_aligns_titles_in_one_column() -> None:
    console, stream = _console(width=80)
    items = [
        _dense_resolved("d1", "repo-x", last_day=5, volume=2, subagent=True),
        _dense_resolved("d2", "repo-x", last_day=4, volume=120),
        _dense_resolved("d3", "repo-x", last_day=6, volume=7),
    ]
    scan = ScanResult(
        period=_period(), candidate_session_count=3, loaded_session_count=3,
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )
    render_session_review(
        console, SelectionState.from_scan(scan),
        expanded_repositories={"repo-x"}, cursor=0,
    )
    rows = [line for line in stream.getvalue().splitlines() if "Meta d" in line]
    assert len(rows) == 3
    assert len({line.index("Meta d") for line in rows}) == 1


def test_session_review_drops_metadata_when_too_narrow_for_both_columns() -> None:
    console, stream = _console(width=24)
    items = [_dense_resolved("d1", "repo-x", last_day=5, volume=2)]
    scan = ScanResult(
        period=_period(), candidate_session_count=1, loaded_session_count=1,
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )
    render_session_review(
        console, SelectionState.from_scan(scan),
        expanded_repositories={"repo-x"}, cursor=0,
    )
    row = next(line for line in stream.getvalue().splitlines() if "Meta d1" in line)
    assert "Aug 5" not in row


def _meta_columns(text: str) -> list[int]:
    return [
        cell_len(line[: line.index("Aug")])
        for line in text.splitlines()
        if "Aug" in line
    ]


def _mixed_volume_scan() -> ScanResult:
    expanded = [
        _dense_resolved("d1", "repo-x", last_day=5, volume=4),
        _dense_resolved("d2", "repo-x", last_day=4, volume=120),
    ]
    collapsed = [_dense_resolved("e1", "repo-y", last_day=6, volume=7)]
    items = [*expanded, *collapsed]
    return ScanResult(
        period=_period(), candidate_session_count=len(items), loaded_session_count=len(items),
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={"repo-x": expanded, "repo-y": collapsed},
    )


def test_session_review_aligns_repository_and_session_metadata_in_one_column() -> None:
    console, stream = _console(width=80)
    scan = _mixed_volume_scan()
    render_session_review(
        console, SelectionState.from_scan(scan),
        expanded_repositories={"repo-x"}, cursor=0,
    )
    columns = _meta_columns(stream.getvalue())
    assert len(columns) == 4
    assert len(set(columns)) == 1


def test_session_browser_aligns_repository_and_session_metadata_in_one_column() -> None:
    console, stream = _console(width=80)
    render_session_browser(
        console, _mixed_volume_scan(),
        expanded_repositories={"repo-x"}, cursor=0,
    )
    columns = _meta_columns(stream.getvalue())
    assert len(columns) == 4
    assert len(set(columns)) == 1


def test_session_review_drops_repository_metadata_when_too_narrow_for_both_columns() -> None:
    console, stream = _console(width=24)
    items = [_dense_resolved("d1", "repo-x", last_day=5, volume=2)]
    scan = ScanResult(
        period=_period(), candidate_session_count=1, loaded_session_count=1,
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )
    render_session_review(
        console, SelectionState.from_scan(scan),
        expanded_repositories=set(), cursor=0,
    )
    row = next(line for line in stream.getvalue().splitlines() if "repo-x" in line)
    assert "Aug 5" not in row
    assert row.rstrip().endswith("1 / 1")


def test_session_review_gives_the_three_repository_glyphs_three_styles() -> None:
    console, stream = _color_console()
    render_session_review(console, _selection(), expanded_repositories={"repo-a"}, cursor=0)
    line = _row(stream.getvalue(), "repo-a")
    assert _glyph_style(line, "▶") == "1;36"
    assert _glyph_style(line, "▾") == "2"
    assert _glyph_style(line, "◐") == "33"


def _marker_palette() -> SelectionState:
    everything = [_resolved("all-1", "repo-all")]
    some = [_resolved("some-1", "repo-some"), _resolved("some-2", "repo-some")]
    nothing = [_resolved("none-1", "repo-none")]
    items = [*everything, *some, *nothing]
    scan = ScanResult(
        period=_period(), candidate_session_count=len(items), loaded_session_count=len(items),
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={
            "repo-all": everything, "repo-some": some, "repo-none": nothing,
        },
    )
    state = SelectionState.from_scan(scan)
    state.toggle_session("some-2")
    state.toggle_repository("repo-none")
    return state


def test_session_review_colors_selection_markers_by_state() -> None:
    console, stream = _color_console()
    render_session_review(
        console, _marker_palette(),
        expanded_repositories={"repo-some"}, cursor=0,
    )
    text = stream.getvalue()
    assert _glyph_style(_row(text, "repo-all"), "●") == "32"
    assert _glyph_style(_row(text, "repo-some"), "◐") == "33"
    assert _glyph_style(_row(text, "repo-none"), "○") == "2"
    assert _glyph_style(_row(text, "Work on some-1"), "●") == "32"
    assert _glyph_style(_row(text, "Work on some-2"), "○") == "2"


def test_session_browser_lists_repositories_most_recent_first() -> None:
    console, stream = _console()
    stale = _dense_resolved("s1", "repo-stale", last_day=3, volume=1)
    fresh = _dense_resolved("f1", "repo-fresh", last_day=6, volume=1)
    scan = ScanResult(
        period=_period(), candidate_session_count=2, loaded_session_count=2,
        failed_session_count=0, resolved_sessions=[stale, fresh],
        sessions_by_repository={"repo-stale": [stale], "repo-fresh": [fresh]},
    )
    render_session_browser(console, scan, expanded_repositories=set(), cursor=0)
    text = stream.getvalue()
    assert text.index("repo-fresh") < text.index("repo-stale")


def test_session_browser_separates_the_cursor_from_the_expansion_glyph() -> None:
    console, stream = _color_console()
    render_session_browser(
        console, _mixed_volume_scan(), expanded_repositories={"repo-x"}, cursor=0,
    )
    line = _row(stream.getvalue(), "repo-y")
    assert _glyph_style(line, "▶") == "1;36"
    assert _glyph_style(line, "▸") == "2"


def test_undated_repositories_sort_last_without_comparing_none() -> None:
    dated = _dense_resolved("ses-d", "repo-dated", last_day=4, volume=1)
    undated = _resolved("ses-u", "repo-undated")
    scan = ScanResult(
        period=_period(), candidate_session_count=2, loaded_session_count=2,
        failed_session_count=0, resolved_sessions=[undated, dated],
        sessions_by_repository={"repo-undated": [undated], "repo-dated": [dated]},
    )
    rows = build_visible_rows(scan, set())
    assert [row.repository_id for row in rows] == ["repo-dated", "repo-undated"]


def test_session_review_lists_sessions_most_recent_first() -> None:
    console, stream = _console()
    items = [
        _dense_resolved("older", "repo-x", last_day=3, volume=1),
        _dense_resolved("newer", "repo-x", last_day=6, volume=1),
    ]
    scan = ScanResult(
        period=_period(), candidate_session_count=2, loaded_session_count=2,
        failed_session_count=0, resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )
    render_session_review(
        console, SelectionState.from_scan(scan), expanded_repositories={"repo-x"}, cursor=0,
    )
    text = stream.getvalue()
    assert text.index("Meta newer") < text.index("Meta older")


def test_undated_sessions_sort_after_dated_ones_in_the_same_repository() -> None:
    undated = _resolved("ses-undated", "repo-a")
    dated = _dense_resolved("ses-dated", "repo-a", last_day=4, volume=1)
    sessions = [undated, dated]
    scan = ScanResult(
        period=_period(), candidate_session_count=2, loaded_session_count=2,
        failed_session_count=0, resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )
    rows = build_visible_rows(scan, {"repo-a"})
    assert [row.session_id for row in rows if row.session_id is not None] == [
        "ses-dated", "ses-undated",
    ]


def test_repositories_with_equal_recency_fall_back_to_display_name() -> None:
    zulu = _dense_resolved("ses-z", "repo-zulu", last_day=5, volume=1)
    alpha = _dense_resolved("ses-a", "repo-alpha", last_day=5, volume=1)
    scan = ScanResult(
        period=_period(), candidate_session_count=2, loaded_session_count=2,
        failed_session_count=0, resolved_sessions=[zulu, alpha],
        sessions_by_repository={"repo-zulu": [zulu], "repo-alpha": [alpha]},
    )
    rows = build_visible_rows(scan, set())
    assert [row.repository_id for row in rows] == ["repo-alpha", "repo-zulu"]


def test_sessions_with_equal_recency_fall_back_to_session_id() -> None:
    second = _dense_resolved("ses-b", "repo-x", last_day=5, volume=1)
    first = _dense_resolved("ses-a", "repo-x", last_day=5, volume=1)
    sessions = [second, first]
    scan = ScanResult(
        period=_period(), candidate_session_count=2, loaded_session_count=2,
        failed_session_count=0, resolved_sessions=sessions,
        sessions_by_repository={"repo-x": sessions},
    )
    rows = build_visible_rows(scan, {"repo-x"})
    assert [row.session_id for row in rows if row.session_id is not None] == [
        "ses-a", "ses-b",
    ]


def _volume_scan(*repos: tuple[str, int]) -> ScanResult:
    items = [
        _dense_resolved(f"s-{name}", name, last_day=5, volume=vol)
        for name, vol in repos
    ]
    by_repo: dict[str, list] = {}
    for item in items:
        by_repo.setdefault(item.repository.repository_id, []).append(item)
    return ScanResult(
        period=_period(), candidate_session_count=len(items), loaded_session_count=len(items),
        failed_session_count=0, resolved_sessions=items, sessions_by_repository=by_repo,
    )


def test_review_bar_fills_completely_for_the_largest_repository() -> None:
    console, stream = _console()
    scan = _volume_scan(("big", 100), ("small", 50))
    render_session_review(
        console, SelectionState.from_scan(scan), expanded_repositories=set(), cursor=0,
    )
    row = _row(stream.getvalue(), "big")
    assert row.count("█") == 12
    assert row.count("░") == 0
    small = _row(stream.getvalue(), "small")
    assert small.count("█") == 6


def test_review_percentages_are_shares_of_the_total_not_of_the_peak() -> None:
    console, stream = _console()
    scan = _volume_scan(("one", 50), ("two", 50))
    render_session_review(
        console, SelectionState.from_scan(scan), expanded_repositories=set(), cursor=0,
    )
    assert "50%" in _row(stream.getvalue(), "one")
    assert "50%" in _row(stream.getvalue(), "two")


def test_review_gives_a_low_volume_repository_at_least_one_filled_cell() -> None:
    console, stream = _console()
    scan = _volume_scan(("huge", 1000), ("tiny", 1))
    render_session_review(
        console, SelectionState.from_scan(scan), expanded_repositories=set(), cursor=0,
    )
    assert "█" in _row(stream.getvalue(), "tiny")


def test_review_renders_no_bar_when_the_scan_holds_no_messages() -> None:
    console, stream = _console()
    scan = _volume_scan(("a", 0), ("b", 0))
    render_session_review(
        console, SelectionState.from_scan(scan), expanded_repositories=set(), cursor=0,
    )
    text = stream.getvalue()
    assert "█" not in text
    assert "░" not in text
    assert "%" not in text


def test_review_drops_the_bar_column_on_a_narrow_terminal() -> None:
    console, stream = _console(width=60)
    scan = _volume_scan(("big", 100), ("small", 50))
    render_session_review(
        console, SelectionState.from_scan(scan), expanded_repositories=set(), cursor=0,
    )
    text = stream.getvalue()
    assert "█" not in text
    assert "░" not in text
    assert "big" in text
    assert "small" in text


def test_review_numbers_repositories_in_display_order() -> None:
    console, stream = _console()
    scan = _volume_scan(("alpha", 30), ("beta", 20), ("gamma", 10))
    render_session_review(
        console, SelectionState.from_scan(scan), expanded_repositories=set(), cursor=0,
    )
    text = stream.getvalue()
    assert text.count("1.") == 1
    assert text.count("2.") == 1
    assert text.count("3.") == 1


def test_report_setup_separates_the_generate_action_from_the_settings() -> None:
    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period())
    render_report_setup(console, draft, selected=0)
    lines = stream.getvalue().splitlines()
    action = next(i for i, line in enumerate(lines) if "Generate report" in line)
    harness = next(i for i, line in enumerate(lines) if "Harness" in line)
    assert action < harness
    assert lines[action + 1].strip() == ""
    assert lines[action].startswith("▶")


def test_setup_leaves_previewing_to_quick_review() -> None:
    rows = report_setup_rows()
    assert rows[0] == report_generate_row()
    assert "Preview report" not in rows
    # Quick Review owns previewing outright: the result screen has already
    # written the file, so it never offers one.
    assert "Preview report" not in report_result_options()


def test_report_setup_describes_the_row_under_the_cursor() -> None:
    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period())
    render_report_setup(console, draft, selected=4)
    detail_help = stream.getvalue()
    console, stream = _console()
    render_report_setup(console, draft, selected=0)
    action_help = stream.getvalue()
    assert "Brief drops files" in detail_help
    assert "Brief drops files" not in action_help
    assert "Scan the period and produce the report." in action_help


def test_report_setup_explains_why_sanitize_is_unavailable() -> None:
    console, stream = _console()
    draft = ReportDraft(harness="claude-code", period=_period())
    render_report_setup(console, draft, selected=7)
    text = stream.getvalue()
    assert "Sanitize" in text and "N/A" in text
    assert "Only OpenCode can redact on export" in text


def test_report_setup_gives_the_generate_action_its_own_colour() -> None:
    console, stream = _color_console()
    draft = ReportDraft(harness="opencode", period=_period())
    render_report_setup(console, draft, selected=5)
    text = stream.getvalue()
    action = _row(text, "Generate report")
    settings = _row(text, "Harness")
    assert _glyph_style(action, "G") == "36"
    assert "36" not in _glyph_style(settings, "H")
    console, stream = _color_console()
    render_report_setup(console, draft, selected=0)
    selected_action = _row(stream.getvalue(), "Generate report")
    assert _glyph_style(selected_action, "▶") == "1;36"


def test_report_setup_names_the_period_as_well_as_dating_it() -> None:
    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period(), period_label="This week")
    render_report_setup(console, draft, selected=0)
    row = _row(stream.getvalue(), "Period")
    assert "This week ·" in row


def test_report_setup_shows_bare_dates_for_an_unnamed_period() -> None:
    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period())
    render_report_setup(console, draft, selected=0)
    row = _row(stream.getvalue(), "Period")
    assert "·" not in row


def _preview_session() -> AgentSession:
    return AgentSession(
        harness="opencode",
        session_id="ses-1",
        title="Deploy the service",
        working_directory="/tmp/repo-a",
        branch="main",
        activities=[
            SessionActivity(
                activity_id="a-1", activity_type=ActivityType.USER_MESSAGE,
                timestamp=datetime(2026, 8, 4, 9, 30, tzinfo=TZ),
                content="bump the version\nand ship it",
            ),
            SessionActivity(
                activity_id="a-2", activity_type=ActivityType.ASSISTANT_MESSAGE,
                timestamp=datetime(2026, 8, 4, 9, 31, tzinfo=TZ), content="on it",
            ),
            SessionActivity(
                activity_id="a-3", activity_type=ActivityType.TOOL_CALL,
                tool_name="edit", timestamp=datetime(2026, 8, 4, 9, 31, tzinfo=TZ),
                content='{"file": "pyproject.toml"}',
            ),
        ],
    )


def test_build_session_preview_lines_lists_meta_and_activities() -> None:
    from iiwi.interactive.render import build_session_preview_lines
    lines = build_session_preview_lines(_preview_session())
    assert lines[0] == "Deploy the service"
    assert "/tmp/repo-a" in lines
    assert "branch: main" in lines
    assert "2 msgs" in lines
    assert "[08-04 09:30] You" in lines
    assert "  bump the version" in lines
    assert "  and ship it" in lines
    assert "[08-04 09:31] Tool call: edit" in lines
    assert '  {"file": "pyproject.toml"}' in lines


def test_build_session_preview_lines_redacts_secret_shaped_content() -> None:
    from iiwi.interactive.render import build_session_preview_lines
    session = _preview_session()
    session.activities[0].content = "set OPENAI_API_KEY sk-proj-not-a-real-secret-key"
    lines = build_session_preview_lines(session)
    assert "[REDACTED]" in " ".join(lines)
    assert "sk-proj-not-a-real-secret-key" not in " ".join(lines)


def test_render_session_preview_shows_the_session() -> None:
    from iiwi.interactive.render import render_session_preview
    console, stream = _console()
    render_session_preview(console, _preview_session(), offset=0)
    text = stream.getvalue()
    assert "Session Preview" in text
    assert "Deploy the service" in text
    assert "b Back" in text


def test_main_menu_draws_the_wordmark_when_it_fits() -> None:
    from iiwi.interactive.render import _WORDMARK, render_main_menu
    console, stream = _console(width=100, height=30)
    render_main_menu(console, selected=0)
    text = stream.getvalue()
    for line in _WORDMARK[:-1]:
        assert line in text
    assert _WORDMARK[-1] in text


def test_main_menu_paints_every_wordmark_row_iiwi_scarlet() -> None:
    from iiwi.interactive.render import _WORDMARK, render_main_menu
    console, stream = _color_console()
    render_main_menu(console, selected=0)
    text = stream.getvalue()
    # Exact escape, so a stray `bold` cannot creep back in: terminals render it
    # as their bright variant, which is the glare this colour exists to avoid.
    for line in _WORDMARK:
        assert "\x1b[38;2;217;59;40m" in _row(text, line)


def test_main_menu_keeps_the_version_dim_beside_the_scarlet_wordmark() -> None:
    import iiwi
    from iiwi.interactive.render import _WORDMARK, render_main_menu
    console, stream = _color_console()
    render_main_menu(console, selected=0)
    last_row = _row(stream.getvalue(), _WORDMARK[-1])
    assert _glyph_style(last_row, f"v{iiwi.__version__}") == "2"


def test_main_menu_version_sits_flush_right_on_the_wordmark() -> None:
    import iiwi
    from iiwi.interactive.render import _WORDMARK, render_main_menu
    console, stream = _console(width=100, height=30)
    render_main_menu(console, selected=0)
    version = f"v{iiwi.__version__}"
    last_row = _row(stream.getvalue(), _WORDMARK[-1])
    assert last_row.rstrip().endswith(version)
    assert cell_len(last_row.rstrip()) == 100


def test_main_menu_falls_back_to_the_title_row_on_a_short_terminal() -> None:
    import iiwi
    from iiwi.interactive.render import _WORDMARK, render_main_menu
    console, stream = _console(width=100, height=20)
    render_main_menu(console, selected=0)
    text = stream.getvalue()
    assert _WORDMARK[-1] not in text
    title_line = _row(text, "Iiwi")
    assert f"v{iiwi.__version__}" in title_line


def test_main_menu_falls_back_to_the_title_row_on_a_narrow_terminal() -> None:
    from iiwi.interactive.render import _WORDMARK, render_main_menu
    console, stream = _console(width=23, height=30)
    render_main_menu(console, selected=0)
    text = stream.getvalue()
    assert _WORDMARK[-1] not in text
    assert "Iiwi" in text


def test_main_menu_shows_the_project_link_under_the_subtitle() -> None:
    from iiwi.interactive.render import _MAIN_SUBTITLE, _PROJECT_LABEL, render_main_menu
    console, stream = _console(width=100, height=30)
    render_main_menu(console, selected=0)
    lines = stream.getvalue().splitlines()
    assert lines[lines.index(_PROJECT_LABEL) - 1].startswith(_MAIN_SUBTITLE)


def test_main_menu_link_survives_the_compact_header() -> None:
    from iiwi.interactive.render import _PROJECT_LABEL, _WORDMARK, render_main_menu
    console, stream = _console(width=100, height=20)
    render_main_menu(console, selected=0)
    text = stream.getvalue()
    assert _WORDMARK[-1] not in text
    assert _PROJECT_LABEL in text


def test_main_menu_drops_the_link_with_the_subtitle() -> None:
    from iiwi.interactive.render import _MAIN_SUBTITLE, _PROJECT_LABEL, render_main_menu
    console, stream = _console(width=100, height=15)
    render_main_menu(console, selected=0)
    text = stream.getvalue()
    assert _MAIN_SUBTITLE not in text
    assert _PROJECT_LABEL not in text
    assert "Iiwi" in text


def test_main_menu_drops_the_link_when_it_would_be_truncated() -> None:
    from iiwi.interactive.render import _PROJECT_LABEL, render_main_menu
    console, stream = _console(width=20, height=30)
    render_main_menu(console, selected=0)
    assert "github.com" not in stream.getvalue()
    assert cell_len(_PROJECT_LABEL) > 20


def test_main_menu_link_is_clickable_on_a_terminal() -> None:
    from iiwi.interactive.render import _PROJECT_LABEL, _PROJECT_URL, render_main_menu
    console, stream = _color_console(width=100)
    render_main_menu(console, selected=0)
    text = stream.getvalue()
    assert _PROJECT_LABEL in text
    assert "\x1b]8;id=" in text
    assert f";{_PROJECT_URL}\x1b\\" in text


def test_main_menu_wordmark_appears_at_its_exact_width_gate() -> None:
    from iiwi.interactive.render import _MIN_WORDMARK_WIDTH, _WORDMARK, render_main_menu
    console, stream = _console(width=_MIN_WORDMARK_WIDTH, height=30)
    render_main_menu(console, selected=0)
    assert _WORDMARK[-1] in stream.getvalue()


def test_main_menu_omits_the_version_on_a_narrow_terminal() -> None:
    import iiwi
    from iiwi.interactive.render import render_main_menu
    console, stream = _console(width=10)
    render_main_menu(console, selected=0)
    text = stream.getvalue()
    assert "Iiwi" in text
    assert f"v{iiwi.__version__}" not in text


def test_main_menu_fits_the_version_at_exact_width() -> None:
    import iiwi
    from iiwi.interactive.render import render_main_menu
    width = cell_len("Iiwi") + 1 + cell_len(f"v{iiwi.__version__}")
    console, stream = _console(width=width)
    render_main_menu(console, selected=0)
    title_line = _row(stream.getvalue(), "Iiwi")
    assert f"v{iiwi.__version__}" in title_line


def _history_entry(index: int, output_path: str) -> HistoryEntry:
    return HistoryEntry(
        generated_at=datetime(2026, 8, 12, 9, 30, tzinfo=ZoneInfo("Asia/Taipei")),
        harness="opencode",
        since=datetime(2026, 8, 3, tzinfo=ZoneInfo("Asia/Taipei")),
        until=datetime(2026, 8, 10, tzinfo=ZoneInfo("Asia/Taipei")),
        output_path=Path(output_path),
        repository_count=2,
        session_count=7,
        narrative=True,
        detail="full",
    )


def test_history_renders_entries_with_the_cursor_on_the_selected_row() -> None:
    console, stream = _console()

    render_history(
        console,
        entries=[_history_entry(0, "reports/a.md"), _history_entry(1, "reports/b.md")],
        selected=1,
        offset=0,
    )

    text = stream.getvalue()
    assert "Past Reports" in text
    assert "reports/a.md" in text
    assert "reports/b.md" in text
    assert "▶" in text


def test_history_renders_daily_standup_without_a_fake_harness() -> None:
    console, stream = _console(width=160)
    report = _history_entry(0, "reports/report.md")
    daily = HistoryEntry(
        generated_at=report.generated_at,
        since=report.since,
        until=report.until,
        output_path=Path("reports/daily.md"),
        repository_count=report.repository_count,
        session_count=report.session_count,
        kind=history_module.HistoryKind.DAILY_STANDUP,
        harnesses=("opencode", "codex"),
    )

    render_history(console, entries=[report, daily], selected=1, offset=0)

    text = stream.getvalue()
    assert "opencode" in text
    assert "Daily Standup" in text
    assert "multiple" not in text


def test_history_renders_empty_state_when_there_are_no_entries() -> None:
    console, stream = _console()

    render_history(console, entries=[], selected=0, offset=0)

    text = stream.getvalue()
    assert "No reports generated yet." in text


def test_history_scrolls_its_viewport() -> None:
    console, stream = _console()
    entries = [_history_entry(i, f"reports/{i}.md") for i in range(20)]

    render_history(console, entries=entries, selected=19, offset=10)

    lines = stream.getvalue().splitlines()
    assert "reports/10.md" in lines[3]
    assert "reports/0.md" not in lines[3]


def test_history_capacity_reserves_the_footer() -> None:
    assert history_capacity(30) == 22
def _settings_row(**overrides: object) -> SettingsRow:
    fields = dict(
        key="harnesses.opencode.enabled",
        label="opencode.enabled",
        value="true",
        source="default",
        default="true",
        choices=("true", "false"),
        show_all=True,
        locked=False,
        variable="IIWI_HARNESSES__OPENCODE__ENABLED",
    )
    fields.update(overrides)
    return SettingsRow(**fields)


def test_settings_renders_section_headers() -> None:
    console, stream = _console()
    rows = [
        _settings_row(section="OpenCode"),
        _settings_row(
            key="harnesses.opencode.cli.model",
            label="opencode.cli.model",
            value="",
            default="",
            choices=(),
            show_all=False,
            section="OpenCode",
        ),
        _settings_row(
            key="report.timezone",
            label="timezone",
            value="UTC",
            default="Asia/Taipei",
            choices=TIMEZONE_CHOICES,
            show_all=False,
            locked=True,
            section="General",
        ),
    ]

    render_settings(console, rows=rows, selected=0, file_path="/tmp/config.env")

    text = stream.getvalue()
    # Each section header appears once, before its first row, with a blank
    # line separating blocks.
    assert text.count("OpenCode") == 1
    assert text.count("General") == 1
    assert text.index("  OpenCode") < text.index("opencode.enabled")
    assert text.index("  General") < text.index("timezone")
    assert "\n\n  General" in text


def test_settings_renders_choice_rows_with_every_option() -> None:
    console, stream = _console()
    rows = [
        _settings_row(),
        _settings_row(
            key="harnesses.opencode.cli.model",
            label="opencode.cli.model",
            value="",
            default="",
            choices=(),
            show_all=False,
        ),
    ]

    render_settings(console, rows=rows, selected=0, file_path="/tmp/config.env")

    text = stream.getvalue()
    assert "Settings" in text
    assert "Settings file: /tmp/config.env" in text
    assert "opencode.enabled" in text
    assert "true / false" in text
    assert "(default)" in text


def test_settings_highlights_only_the_active_choice() -> None:
    console, stream = _color_console()

    render_settings(
        console,
        rows=[
            _settings_row(value="false"),
            _settings_row(
                key="report.quick_review_report_type",
                label="quick_review_report_type",
                value="engineering",
                choices=("manager", "engineering"),
            ),
        ],
        selected=1,
        file_path="/tmp/config.env",
    )

    text = stream.getvalue()
    # Active choices are bold cyan; the rest are dim.
    assert "\x1b[1;36mfalse\x1b[0m" in text
    assert "\x1b[2mtrue\x1b[0m" in text
    assert "\x1b[1;36mengineering\x1b[0m" in text
    assert "\x1b[2mmanager\x1b[0m" in text


def test_settings_marks_environment_rows_as_locked() -> None:
    console, stream = _console()

    render_settings(
        console,
        rows=[
            _settings_row(locked=True),
            _settings_row(
                key="report.timezone",
                label="timezone",
                value="UTC",
                choices=TIMEZONE_CHOICES,
                show_all=False,
                locked=True,
            ),
        ],
        selected=0,
        file_path="/tmp/config.env",
    )

    text = stream.getvalue()
    choice_line = next(line for line in text.splitlines() if "true / false" in line)
    assert "[environment]" in choice_line
    value_line = next(line for line in text.splitlines() if "UTC" in line)
    assert "[environment]" in value_line


def test_settings_renders_the_inline_editor_and_hints() -> None:
    console, stream = _console()
    rows = [
        _settings_row(),
        _settings_row(
            key="harnesses.opencode.cli.model",
            label="opencode.cli.model",
            value="",
            default="",
            choices=(),
            show_all=False,
        ),
    ]

    render_settings(
        console,
        rows=rows,
        selected=1,
        file_path="/tmp/config.env",
        editing=True,
        edit_value="deepseek",
    )

    text = stream.getvalue()
    assert "harnesses.opencode.cli.model []: deepseek" in text
    assert "Enter Keep" in text
    assert "Esc Cancel" in text


def test_settings_renders_validation_error_on_the_detail_line() -> None:
    console, stream = _console()

    render_settings(
        console,
        rows=[_settings_row()],
        selected=0,
        file_path="/tmp/config.env",
        editing=True,
        edit_value="abc",
        error="invalid value for harnesses.opencode.cli.timeout_seconds: nope",
    )

    assert "invalid value for harnesses.opencode.cli.timeout_seconds" in stream.getvalue()


def test_settings_renders_a_cycle_error_on_the_detail_line() -> None:
    console, stream = _console()

    render_settings(
        console,
        rows=[_settings_row()],
        selected=0,
        file_path="/tmp/config.env",
        error="could not write config file: read-only file system",
    )

    assert "could not write config file: read-only file system" in stream.getvalue()
