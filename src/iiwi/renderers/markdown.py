"""Markdown rendering for worklog reports."""

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from iiwi.models.report import WorklogReport
from iiwi.models.report_options import DetailLevel, ReportType

# The renderer is the report's only truncation point. Both summarizers now emit
# complete lists, so the omitted-item count is always the real remainder.
_SECTION_LIMITS = {
    DetailLevel.FULL: 20,
    DetailLevel.BRIEF: 5,
}
_BRIEF_NARRATIVE_ALLOWED_HEADINGS = frozenset(
    {"outcomes", "in progress", "blockers", "next week", "warnings"}
)
_FILE_PATH_PATTERN = re.compile(r"\b[\w.-]+/[\w./-]+\.[A-Za-z0-9]{1,12}\b")
_SESSION_LINE_PATTERN = re.compile(
    r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?session(?: id)?(?:\s*:\s*|\s+)\S+",
    re.IGNORECASE,
)
_EVIDENCE_LINE_PATTERN = re.compile(
    r"\b(?:branch|commit|command|file|path|revision)(?:\s*:|\s+)", re.IGNORECASE
)
_SESSION_ID_PATTERN = re.compile(r"\bses-[\w-]+\b", re.IGNORECASE)
_COMMAND_LINE_PATTERN = re.compile(
    r"(?:^|\s)(?:[$>#]\s*|bash\b|cargo\b|curl\b|docker\b|git\b|go\b|"
    r"make\b|npm\b|pnpm\b|pytest\b|python\b|sh\b|uv\b|yarn\b|zsh\b)",
    re.IGNORECASE,
)


def _is_setext_underline(value: str) -> bool:
    """Return whether a stripped line is a Setext heading underline."""

    return bool(re.fullmatch(r"(?:={3,}|-{3,})", value.strip()))


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
        self._outcomes_template = environment.get_template("outcomes.md.j2")

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


    def render_outcomes(
        self,
        report: WorklogReport,
        *,
        detail: DetailLevel = DetailLevel.FULL,
    ) -> str:
        """Render an outcome review using the report-type-specific template."""

        detail = DetailLevel(detail)
        timezone = getattr(report.period.since.tzinfo, "key", str(report.period.since.tzinfo))
        evidence_by_repository: dict[str, list] = {}
        for outcome in report.outcomes:
            if not outcome.included:
                continue
            for reference in outcome.evidence_refs:
                evidence_by_repository.setdefault(reference.repository_id, []).append(reference)
        output = self._outcomes_template.render(
            report=report,
            report_type=report.report_type or ReportType.ENGINEERING,
            timezone=timezone,
            full=detail is DetailLevel.FULL,
            evidence_by_repository=evidence_by_repository,
        )
        return f"{output.rstrip()}\n"


def render_narrative(
    report: WorklogReport,
    *,
    timezone: str,
    detail: DetailLevel = DetailLevel.FULL,
) -> str:
    """Wrap a narrative body under the standard worklog header.

    The narrative prose from `opencode run` is rendered verbatim below the
    shared header so a narrative report and a structured report read as the same
    artifact; usage and warnings render in the same positions as the template.
    """

    detail = DetailLevel(detail)
    narrative_text = report.narrative_text or ""
    if detail is DetailLevel.BRIEF:
        narrative_text = _brief_narrative_body(narrative_text)
    lines = [
        "# Engineering Worklog",
        "",
        "**Period:** "
        f"{report.period.since.strftime('%Y-%m-%d %H:%M')} – "
        f"{report.period.until.strftime('%Y-%m-%d %H:%M')}",
        f"**Timezone:** {timezone}",
        f"**Generated:** {report.generated_at.strftime('%Y-%m-%d %H:%M')}",
        "",
        narrative_text,
    ]
    if detail is DetailLevel.FULL and report.usage_text:
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


def _brief_narrative_body(value: str) -> str:
    """Keep only reader-facing sections without technical evidence details."""

    lines = value.splitlines()
    kept: list[str] = []
    has_headings = False
    in_code_block = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if stripped.startswith("#") or (
            stripped
            and index + 1 < len(lines)
            and _is_setext_underline(lines[index + 1])
        ):
            has_headings = True
            break

    allowed_section = not has_headings
    in_code_block = False
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_code_block = not in_code_block
            index += 1
            continue
        if in_code_block:
            index += 1
            continue
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().casefold()
            allowed_section = heading in _BRIEF_NARRATIVE_ALLOWED_HEADINGS
            if allowed_section:
                kept.append(line)
            index += 1
            continue
        if (
            stripped
            and index + 1 < len(lines)
            and _is_setext_underline(lines[index + 1])
        ):
            allowed_section = stripped.casefold() in _BRIEF_NARRATIVE_ALLOWED_HEADINGS
            if allowed_section:
                kept.extend((line, lines[index + 1]))
            index += 2
            continue
        if not allowed_section:
            index += 1
            continue
        if (
            _FILE_PATH_PATTERN.search(line)
            or _SESSION_LINE_PATTERN.search(line)
            or _SESSION_ID_PATTERN.search(line)
            or _EVIDENCE_LINE_PATTERN.search(line)
            or _COMMAND_LINE_PATTERN.search(line)
        ):
            index += 1
            continue
        kept.append(line)
        index += 1
    return "\n".join(kept).strip()
