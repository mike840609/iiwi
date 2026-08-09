"""Markdown rendering for worklog reports."""

from enum import StrEnum
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from iiwi.models.report import WorklogReport


class DetailLevel(StrEnum):
    BRIEF = "brief"
    FULL = "full"


# The renderer is the report's only truncation point. Both summarizers now emit
# complete lists, so the omitted-item count is always the real remainder.
_SECTION_LIMITS = {
    DetailLevel.FULL: 20,
    DetailLevel.BRIEF: 5,
}


class MarkdownRenderer:
    """Render a WorklogReport using the bundled safe summary template."""

    def __init__(self) -> None:
        template_directory = Path(__file__).parents[1] / "templates"
        environment = Environment(
            loader=FileSystemLoader(template_directory),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        self._template = environment.get_template("worklog.md.j2")

    def render(
        self,
        report: WorklogReport,
        *,
        detail: DetailLevel = DetailLevel.FULL,
    ) -> str:
        # `detail` may arrive as a plain string from a library caller. StrEnum
        # hashes as `str`, so `_SECTION_LIMITS[detail]` below would already
        # succeed on `"full"`, but `detail is DetailLevel.FULL` would not — an
        # inconsistent state no CLI invocation can produce. Normalizing here
        # makes both checks agree and rejects unknown values outright.
        detail = DetailLevel(detail)
        tzinfo = report.period.since.tzinfo
        timezone = getattr(tzinfo, "key", str(tzinfo))
        output = self._template.render(
            report=report,
            timezone=timezone,
            section_limit=_SECTION_LIMITS[detail],
            full=detail is DetailLevel.FULL,
        )
        return f"{output.rstrip()}\n"


def render_narrative(report: WorklogReport, *, timezone: str) -> str:
    """Wrap a narrative body under the standard worklog header.

    The narrative prose from `opencode run` is rendered verbatim below the
    shared header so a narrative report and a structured report read as the same
    artifact; usage and warnings render in the same positions as the template.
    """

    lines = [
        "# Engineering Worklog",
        "",
        "**Period:** "
        f"{report.period.since.strftime('%Y-%m-%d %H:%M')} – "
        f"{report.period.until.strftime('%Y-%m-%d %H:%M')}",
        f"**Timezone:** {timezone}",
        f"**Generated:** {report.generated_at.strftime('%Y-%m-%d %H:%M')}",
        "",
        report.narrative_text or "",
    ]
    if report.usage_text:
        lines += ["", "## Usage"]
        if report.usage_days:
            lines += [
                "",
                "Window: the last "
                f"{report.usage_days} days ending at generation time. It contains "
                "the report period but does not match it exactly, because OpenCode "
                "reports usage only for a window ending now.",
            ]
        lines += ["", "```text", report.usage_text, "```"]
    if report.warnings:
        lines += ["", "## Warnings"]
        lines += [f"- {warning}" for warning in report.warnings]
    return "\n".join(lines).rstrip() + "\n"
