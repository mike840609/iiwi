"""Contract tests for Daily Standup Markdown rendering."""

from datetime import date, datetime

from iiwi.models.daily import (
    DailySectionItem,
    DailyStandupDraft,
    DailyStandupWorkItem,
    DailyStatementSource,
)
from iiwi.renderers.daily_markdown import render_daily_standup


def _item(statement: str, *, included: bool = True, rank: int = 0) -> DailySectionItem:
    return DailySectionItem(
        statement=statement,
        included=included,
        rank=rank,
        source=DailyStatementSource.ACTIVITY_TODAY,
    )


def _draft(*, work_items: list[DailyStandupWorkItem]) -> DailyStandupDraft:
    return DailyStandupDraft(
        standup_date=date(2026, 8, 13),
        scan_since=datetime.fromisoformat("2026-08-12T00:00:00+08:00"),
        scan_until=datetime.fromisoformat("2026-08-13T09:00:00+08:00"),
        work_items=work_items,
        warnings=["Review labels: codex", "Fallback draft"],
        coverage_warnings=["OpenCode activity could not be loaded."],
        fallback=True,
    )


def test_render_daily_standup_matches_the_reviewed_artifact_contract() -> None:
    """This fails if a reader-visible Daily section, warning, or label changes."""

    draft = _draft(
        work_items=[
            DailyStandupWorkItem(
                id="auth",
                repository_ids=["web", "api", "sdk", "api"],
                yesterday=_item("Finished the authentication migration."),
            ),
            DailyStandupWorkItem(
                id="daily",
                repository_ids=["iiwi"],
                today=_item("Implement the Daily Standup draft."),
            ),
            DailyStandupWorkItem(
                id="excluded",
                repository_ids=["ignored"],
                yesterday=_item("This stays in review.", included=False),
                blocker=_item("This also stays in review.", included=False),
            ),
        ]
    )

    assert render_daily_standup(draft) == (
        "# Daily Standup — 2026-08-13\n\n"
        "> Warning: OpenCode activity could not be loaded.\n\n"
        "## Yesterday\n"
        "- [api, sdk, web] Finished the authentication migration.\n\n"
        "## Today\n"
        "- [iiwi] Implement the Daily Standup draft.\n\n"
        "## Blockers\n"
        "- None\n"
    )


def test_render_daily_standup_uses_plain_bullets_for_manual_items_and_empty_sections() -> None:
    """This fails if blank repository labels or empty-section placeholders leak."""

    draft = _draft(
        work_items=[
            DailyStandupWorkItem(
                id="manual",
                yesterday=DailySectionItem(
                    statement="Manual statement",
                    source=DailyStatementSource.USER_ADDED,
                ),
            )
        ]
    )

    assert render_daily_standup(draft) == (
        "# Daily Standup — 2026-08-13\n\n"
        "> Warning: OpenCode activity could not be loaded.\n\n"
        "## Yesterday\n"
        "- Manual statement\n\n"
        "## Today\n"
        "- None\n\n"
        "## Blockers\n"
        "- None\n"
    )
