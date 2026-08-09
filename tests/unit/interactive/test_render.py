from __future__ import annotations

import re
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.cells import cell_len
from rich.console import Console

from agent_worklog.interactive.models import ReportDraft
from agent_worklog.interactive.render import (
    build_visible_rows,
    render_main_menu,
    render_recoverable_error,
    render_report_result,
    render_report_setup,
    render_session_browser,
    render_session_review,
)
from agent_worklog.interactive.selection import SelectionState
from agent_worklog.models.repository import (
    RepositoryIdentity,
    RepositoryIdentityType,
    ResolvedSession,
)
from agent_worklog.models.session import ActivityType, AgentSession, SessionActivity
from agent_worklog.models.time_range import DateRange
from agent_worklog.services.scan import ScanResult

TZ = ZoneInfo("Asia/Taipei")


def _console(width: int = 100) -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(file=stream, color_system=None, force_terminal=False, width=width),
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
    """The SGR parameters in force where ``glyph`` is drawn on a rendered line."""

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
    assert "Agent Worklog" in text
    assert "▶ Generate Report" in text
    assert "Browse Sessions" in text
    assert "↑↓ jk" in text
    assert "Enter Select" in text
    assert "q Quit" in text


def test_main_menu_describes_each_option() -> None:
    """Each option carries a dim clause saying what it does, like mole's menu."""

    console, stream = _console()

    render_main_menu(console, selected=0)

    lines = stream.getvalue().splitlines()
    generate = next(line for line in lines if "Generate Report" in line)
    browse = next(line for line in lines if "Browse Sessions" in line)
    setup = next(line for line in lines if "Check Setup" in line)
    settings = next(line for line in lines if "Settings" in line)
    assert "Scan the period and produce the report" in generate
    assert "Explore sessions by repository" in browse
    assert "Diagnose the harness setup" in setup
    assert "Edit saved settings" in settings
    column = generate.index("Scan the period")
    assert browse.index("Explore sessions by repository") == column
    assert setup.index("Diagnose the harness setup") == column
    assert settings.index("Edit saved settings") == column


def test_main_menu_drops_descriptions_on_a_narrow_terminal() -> None:
    """Below the width the clauses need, options fall back to bare labels."""

    console, stream = _console(width=30)

    render_main_menu(console, selected=0)

    text = stream.getvalue()
    assert "Generate Report" in text
    assert "Scan the period and produce the report" not in text


def test_report_setup_renders_settings_as_the_navigable_list() -> None:
    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period())

    render_report_setup(console, draft, selected=0)

    text = stream.getvalue()
    assert "Generate Report" in text
    assert "Harness" in text and "OpenCode" in text
    assert "Detail" in text and "Full" in text
    assert "Subagents" in text and "Included" in text
    assert "Narrative" in text and "Enabled" in text
    assert "Sanitize" in text and "Off" in text
    assert "Dry run" in text
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
    assert "Space Toggle" in text
    assert "g Generate" in text
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
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=items,
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
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=items,
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
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories=set(),
        cursor=0,
    )

    header = stream.getvalue().splitlines()[0]
    assert header == "Review Sessions   1 / 1 selected │ 1 / 1 msg"


def test_session_review_header_omits_volume_when_the_scan_holds_no_messages() -> None:
    """A scan of pure tool-call activity would otherwise headline ``0 / 0 msgs``."""

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
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=items,
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
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=items,
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
    session_id = (
        "trunc1-with-a-very-long-session-title-"
        "that-will-clip-at-forty-cells-wide"
    )
    items = [_dense_resolved(session_id, "repo-t", last_day=5, volume=2)]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=items,
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
            harness="opencode",
            session_id="ses-untitled",
            title=None,
            working_directory="/tmp/repo-a",
        ),
        repository=RepositoryIdentity(
            repository_id="repo-a",
            display_name="repo-a",
            identity_type=RepositoryIdentityType.PATH_FALLBACK,
            working_directory="/tmp/repo-a",
            resolution_method="test",
        ),
    )
    sessions = [_resolved("ses-a1", "repo-a"), untitled]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories={"repo-a"},
        cursor=0,
    )

    assert "No title" in stream.getvalue()


def test_session_review_aligns_titles_in_one_column() -> None:
    """Ragged title starts make a long list unscannable, so metadata goes right."""

    console, stream = _console(width=80)
    items = [
        _dense_resolved("d1", "repo-x", last_day=5, volume=2, subagent=True),
        _dense_resolved("d2", "repo-x", last_day=4, volume=120),
        _dense_resolved("d3", "repo-x", last_day=6, volume=7),
    ]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=3,
        loaded_session_count=3,
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories={"repo-x"},
        cursor=0,
    )

    rows = [line for line in stream.getvalue().splitlines() if "Meta d" in line]
    assert len(rows) == 3
    assert len({line.index("Meta d") for line in rows}) == 1


def test_session_review_drops_metadata_when_too_narrow_for_both_columns() -> None:
    """Below the title floor the metadata yields, rather than squeezing titles to nothing."""

    console, stream = _console(width=24)
    items = [_dense_resolved("d1", "repo-x", last_day=5, volume=2)]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories={"repo-x"},
        cursor=0,
    )

    row = next(line for line in stream.getvalue().splitlines() if "Meta d1" in line)
    assert "Aug 5" not in row


def _meta_columns(text: str) -> list[int]:
    """Cell column where each row's metadata starts, in render order.

    Cells, not characters: the two row kinds carry different numbers of glyphs,
    so a character index would compare the wrong thing across them.
    """

    return [
        cell_len(line[: line.index("Aug")])
        for line in text.splitlines()
        if "Aug" in line
    ]


def _mixed_volume_scan() -> ScanResult:
    """One expanded repository and one collapsed, so both row kinds carry metadata."""

    expanded = [
        _dense_resolved("d1", "repo-x", last_day=5, volume=4),
        _dense_resolved("d2", "repo-x", last_day=4, volume=120),
    ]
    collapsed = [_dense_resolved("e1", "repo-y", last_day=6, volume=7)]
    items = [*expanded, *collapsed]
    return ScanResult(
        period=_period(),
        candidate_session_count=len(items),
        loaded_session_count=len(items),
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository={"repo-x": expanded, "repo-y": collapsed},
    )


def test_session_review_aligns_repository_and_session_metadata_in_one_column() -> None:
    """One metadata column across both row kinds is what lets volumes be compared by eye."""

    console, stream = _console(width=80)
    scan = _mixed_volume_scan()

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories={"repo-x"},
        cursor=0,
    )

    columns = _meta_columns(stream.getvalue())
    assert len(columns) == 4
    assert len(set(columns)) == 1


def test_session_browser_aligns_repository_and_session_metadata_in_one_column() -> None:
    """Browse shares Review's grid, so a screen switch keeps the same reading line."""

    console, stream = _console(width=80)

    render_session_browser(
        console,
        _mixed_volume_scan(),
        expanded_repositories={"repo-x"},
        cursor=0,
    )

    columns = _meta_columns(stream.getvalue())
    assert len(columns) == 4
    assert len(set(columns)) == 1


def test_session_review_drops_repository_metadata_when_too_narrow_for_both_columns() -> None:
    """A repository row yields its metadata too, rather than clipping mid-count."""

    console, stream = _console(width=24)
    items = [_dense_resolved("d1", "repo-x", last_day=5, volume=2)]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=1,
        loaded_session_count=1,
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories=set(),
        cursor=0,
    )

    row = next(line for line in stream.getvalue().splitlines() if "repo-x" in line)
    assert "Aug 5" not in row
    assert row.rstrip().endswith("1 / 1")


def test_session_review_gives_the_three_repository_glyphs_three_styles() -> None:
    """Cursor, expansion and selection mean different things; one style reads as soup."""

    console, stream = _color_console()

    render_session_review(console, _selection(), expanded_repositories={"repo-a"}, cursor=0)

    line = _row(stream.getvalue(), "repo-a")
    assert _glyph_style(line, "▶") == "1;36"
    assert _glyph_style(line, "▾") == "2"
    assert _glyph_style(line, "◐") == "33"


def _marker_palette() -> SelectionState:
    """One repository per selection state, so every marker appears on one screen."""

    everything = [_resolved("all-1", "repo-all")]
    some = [_resolved("some-1", "repo-some"), _resolved("some-2", "repo-some")]
    nothing = [_resolved("none-1", "repo-none")]
    items = [*everything, *some, *nothing]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=len(items),
        loaded_session_count=len(items),
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository={
            "repo-all": everything,
            "repo-some": some,
            "repo-none": nothing,
        },
    )
    state = SelectionState.from_scan(scan)
    state.toggle_session("some-2")
    state.toggle_repository("repo-none")
    return state


def test_session_review_colors_selection_markers_by_state() -> None:
    """The marker answers "is this in the report?", so its colour must answer it too."""

    console, stream = _color_console()

    render_session_review(
        console,
        _marker_palette(),
        expanded_repositories={"repo-some"},
        cursor=0,
    )

    text = stream.getvalue()
    assert _glyph_style(_row(text, "repo-all"), "●") == "32"
    assert _glyph_style(_row(text, "repo-some"), "◐") == "33"
    assert _glyph_style(_row(text, "repo-none"), "○") == "2"
    assert _glyph_style(_row(text, "Work on some-1"), "●") == "32"
    assert _glyph_style(_row(text, "Work on some-2"), "○") == "2"


def test_session_browser_lists_repositories_most_recent_first() -> None:
    """Harness order is arbitrary, so the freshest work would otherwise hide mid-list."""

    console, stream = _console()
    stale = _dense_resolved("s1", "repo-stale", last_day=3, volume=1)
    fresh = _dense_resolved("f1", "repo-fresh", last_day=6, volume=1)
    scan = ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=[stale, fresh],
        sessions_by_repository={"repo-stale": [stale], "repo-fresh": [fresh]},
    )

    render_session_browser(console, scan, expanded_repositories=set(), cursor=0)

    text = stream.getvalue()
    assert text.index("repo-fresh") < text.index("repo-stale")


def test_session_browser_separates_the_cursor_from_the_expansion_glyph() -> None:
    """Browse carries no markers, but its cursor and arrow still mean different things."""

    console, stream = _color_console()

    render_session_browser(
        console,
        _mixed_volume_scan(),
        expanded_repositories={"repo-x"},
        cursor=0,
    )

    line = _row(stream.getvalue(), "repo-y")
    assert _glyph_style(line, "▶") == "1;36"
    assert _glyph_style(line, "▸") == "2"


def test_undated_repositories_sort_last_without_comparing_none() -> None:
    """A scanned session always has a date, but a fixture without one must not crash."""

    dated = _dense_resolved("ses-d", "repo-dated", last_day=4, volume=1)
    undated = _resolved("ses-u", "repo-undated")
    scan = ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=[undated, dated],
        sessions_by_repository={"repo-undated": [undated], "repo-dated": [dated]},
    )

    rows = build_visible_rows(scan, set())

    assert [row.repository_id for row in rows] == ["repo-dated", "repo-undated"]


def test_session_review_lists_sessions_most_recent_first() -> None:
    """Density metadata only pays off once the rows it annotates are ordered."""

    console, stream = _console()
    items = [
        _dense_resolved("older", "repo-x", last_day=3, volume=1),
        _dense_resolved("newer", "repo-x", last_day=6, volume=1),
    ]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository={"repo-x": items},
    )

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories={"repo-x"},
        cursor=0,
    )

    text = stream.getvalue()
    assert text.index("Meta newer") < text.index("Meta older")


def test_undated_sessions_sort_after_dated_ones_in_the_same_repository() -> None:
    """A row with no date carries no signal, so it belongs below the dated work."""

    undated = _resolved("ses-undated", "repo-a")
    dated = _dense_resolved("ses-dated", "repo-a", last_day=4, volume=1)
    sessions = [undated, dated]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-a": sessions},
    )

    rows = build_visible_rows(scan, {"repo-a"})

    assert [row.session_id for row in rows if row.session_id is not None] == [
        "ses-dated",
        "ses-undated",
    ]


def test_repositories_with_equal_recency_fall_back_to_display_name() -> None:
    """Recency alone is a partial order; the name completes it so runs agree."""

    zulu = _dense_resolved("ses-z", "repo-zulu", last_day=5, volume=1)
    alpha = _dense_resolved("ses-a", "repo-alpha", last_day=5, volume=1)
    scan = ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=[zulu, alpha],
        sessions_by_repository={"repo-zulu": [zulu], "repo-alpha": [alpha]},
    )

    rows = build_visible_rows(scan, set())

    assert [row.repository_id for row in rows] == ["repo-alpha", "repo-zulu"]


def test_sessions_with_equal_recency_fall_back_to_session_id() -> None:
    """Same-day sessions share a timestamp, so the id keeps their order fixed."""

    second = _dense_resolved("ses-b", "repo-x", last_day=5, volume=1)
    first = _dense_resolved("ses-a", "repo-x", last_day=5, volume=1)
    sessions = [second, first]
    scan = ScanResult(
        period=_period(),
        candidate_session_count=2,
        loaded_session_count=2,
        failed_session_count=0,
        resolved_sessions=sessions,
        sessions_by_repository={"repo-x": sessions},
    )

    rows = build_visible_rows(scan, {"repo-x"})

    assert [row.session_id for row in rows if row.session_id is not None] == [
        "ses-a",
        "ses-b",
    ]


def _volume_scan(*repos: tuple[str, int]) -> ScanResult:
    items = [_dense_resolved(f"s-{name}", name, last_day=5, volume=vol) for name, vol in repos]
    by_repo: dict[str, list] = {}
    for item in items:
        by_repo.setdefault(item.repository.repository_id, []).append(item)
    return ScanResult(
        period=_period(),
        candidate_session_count=len(items),
        loaded_session_count=len(items),
        failed_session_count=0,
        resolved_sessions=items,
        sessions_by_repository=by_repo,
    )


def test_review_bar_fills_completely_for_the_largest_repository() -> None:
    """The peak repository fills its bar edge to edge, not lumped at a fraction."""

    console, stream = _console()
    scan = _volume_scan(("big", 100), ("small", 50))

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories=set(),
        cursor=0,
    )

    row = _row(stream.getvalue(), "big")
    assert row.count("█") == 12
    assert row.count("░") == 0
    small = _row(stream.getvalue(), "small")
    assert small.count("█") == 6


def test_review_percentages_are_shares_of_the_total_not_of_the_peak() -> None:
    """Equal volumes must read as equal shares even when they are not the peak."""

    console, stream = _console()
    scan = _volume_scan(("one", 50), ("two", 50))

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories=set(),
        cursor=0,
    )

    assert "50%" in _row(stream.getvalue(), "one")
    assert "50%" in _row(stream.getvalue(), "two")


def test_review_gives_a_low_volume_repository_at_least_one_filled_cell() -> None:
    """A near-empty repository must still show a sliver of activity, not a barren bar."""

    console, stream = _console()
    scan = _volume_scan(("huge", 1000), ("tiny", 1))

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories=set(),
        cursor=0,
    )

    assert "█" in _row(stream.getvalue(), "tiny")


def test_review_renders_no_bar_when_the_scan_holds_no_messages() -> None:
    """Nothing to measure means nothing to draw, so the bar and its percent vanish."""

    console, stream = _console()
    scan = _volume_scan(("a", 0), ("b", 0))

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories=set(),
        cursor=0,
    )

    text = stream.getvalue()
    assert "█" not in text
    assert "░" not in text
    assert "%" not in text


def test_review_drops_the_bar_column_on_a_narrow_terminal() -> None:
    """The bar is the first column to yield, so names survive a narrow screen."""

    console, stream = _console(width=60)
    scan = _volume_scan(("big", 100), ("small", 50))

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories=set(),
        cursor=0,
    )

    text = stream.getvalue()
    assert "█" not in text
    assert "░" not in text
    assert "big" in text
    assert "small" in text


def test_review_numbers_repositories_in_display_order() -> None:
    """Numbering follows the sorted display order, not the scan's raw arrival."""

    console, stream = _console()
    scan = _volume_scan(("alpha", 30), ("beta", 20), ("gamma", 10))

    render_session_review(
        console,
        SelectionState.from_scan(scan),
        expanded_repositories=set(),
        cursor=0,
    )

    text = stream.getvalue()
    assert text.count("1.") == 1
    assert text.count("2.") == 1
    assert text.count("3.") == 1


def test_report_setup_separates_the_generate_action_from_the_settings() -> None:
    """Generate is the screen's destination, so it leads the settings, not sits among them."""

    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period())

    render_report_setup(console, draft, selected=0)

    lines = stream.getvalue().splitlines()
    action = next(i for i, line in enumerate(lines) if "Generate report" in line)
    harness = next(i for i, line in enumerate(lines) if "Harness" in line)
    assert action < harness
    assert lines[action + 1].strip() == ""
    assert lines[action].startswith("▶")


def test_report_setup_describes_the_row_under_the_cursor() -> None:
    """A name and a value say what a setting is set to, never what it does."""

    console, stream = _console()
    draft = ReportDraft(harness="opencode", period=_period())

    render_report_setup(console, draft, selected=3)
    detail_help = stream.getvalue()

    console, stream = _console()
    render_report_setup(console, draft, selected=0)
    action_help = stream.getvalue()

    assert "Brief drops files" in detail_help
    assert "Brief drops files" not in action_help
    assert "Scan the period and produce the report." in action_help


def test_report_setup_explains_why_sanitize_is_unavailable() -> None:
    """`N/A` states that a setting is off the table without saying why."""

    console, stream = _console()
    draft = ReportDraft(harness="claude-code", period=_period())

    render_report_setup(console, draft, selected=6)

    text = stream.getvalue()
    assert "Sanitize     N/A" in text
    assert "Only OpenCode can redact on export" in text


def test_report_setup_gives_the_generate_action_its_own_colour() -> None:
    """The destination must not read as an eighth setting; colour carries the role."""

    console, stream = _color_console()
    draft = ReportDraft(harness="opencode", period=_period())

    render_report_setup(console, draft, selected=3)

    text = stream.getvalue()
    action = _row(text, "Generate report")
    settings = _row(text, "Dry run")
    assert _glyph_style(action, "G") == "36"
    assert "36" not in _glyph_style(settings, "D")

    console, stream = _color_console()
    render_report_setup(console, draft, selected=0)

    selected_action = _row(stream.getvalue(), "Generate report")
    assert _glyph_style(selected_action, "▶") == "1;36"


def test_report_setup_names_the_period_as_well_as_dating_it() -> None:
    """`Last week` and `Last 7 days` look alike as bare dates; the name separates them."""

    console, stream = _console()
    draft = ReportDraft(
        harness="opencode",
        period=_period(),
        period_label="This week",
    )

    render_report_setup(console, draft, selected=0)

    row = _row(stream.getvalue(), "Period")
    assert "This week ·" in row


def test_report_setup_shows_bare_dates_for_an_unnamed_period() -> None:
    """A `--since` window has no name to show, and must not render one."""

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
                activity_id="a-1",
                activity_type=ActivityType.USER_MESSAGE,
                timestamp=datetime(2026, 8, 4, 9, 30, tzinfo=TZ),
                content="bump the version\nand ship it",
            ),
            SessionActivity(
                activity_id="a-2",
                activity_type=ActivityType.ASSISTANT_MESSAGE,
                timestamp=datetime(2026, 8, 4, 9, 31, tzinfo=TZ),
                content="on it",
            ),
            SessionActivity(
                activity_id="a-3",
                activity_type=ActivityType.TOOL_CALL,
                tool_name="edit",
                timestamp=datetime(2026, 8, 4, 9, 31, tzinfo=TZ),
                content='{"file": "pyproject.toml"}',
            ),
        ],
    )


def test_build_session_preview_lines_lists_meta_and_activities() -> None:
    from agent_worklog.interactive.render import build_session_preview_lines

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
    from agent_worklog.interactive.render import build_session_preview_lines

    session = _preview_session()
    session.activities[0].content = "set OPENAI_API_KEY sk-proj-not-a-real-secret-key"

    lines = build_session_preview_lines(session)

    assert "[REDACTED]" in " ".join(lines)
    assert "sk-proj-not-a-real-secret-key" not in " ".join(lines)


def test_render_session_preview_shows_the_session() -> None:
    from agent_worklog.interactive.render import render_session_preview

    console, stream = _console()
    render_session_preview(console, _preview_session(), offset=0)

    text = stream.getvalue()
    assert "Session Preview" in text
    assert "Deploy the service" in text
    assert "bump the version" in text
    assert "b Back" in text
