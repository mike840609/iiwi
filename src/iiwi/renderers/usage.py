"""Aggregate per-model token usage from mapped session activities.

Harness-agnostic: it reads only `activity.metadata["model"]` and
`activity.metadata["usage"]`, which the Claude Code and Codex mappers both
populate. OpenCode does not use this — `opencode stats` reports its own totals.
"""

from __future__ import annotations

from iiwi.errors import HarnessSourceError
from iiwi.services.scan import ScanResult

_COLUMNS = (
    ("Input", "input_tokens"),
    ("Output", "output_tokens"),
    ("Cache read", "cache_read_tokens"),
    ("Cache write", "cache_write_tokens"),
)

# The two harnesses that call this module by their `Harness.value` slug. The
# error text below should read like prose ("Claude Code", not "claude-code"),
# so the slug is mapped to a display name rather than title-cased blindly.
_HARNESS_DISPLAY_NAMES = {
    "claude-code": "Claude Code",
    "codex": "Codex",
}


def _totals_by_model(scan: ScanResult) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    for resolved in scan.resolved_sessions:
        for activity in resolved.session.activities:
            model = activity.metadata.get("model")
            usage = activity.metadata.get("usage")
            if not isinstance(model, str) or not isinstance(usage, dict):
                continue
            row = totals.setdefault(model, {})
            for _, key in _COLUMNS:
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    row[key] = row.get(key, 0) + value
    # Claude Code writes `model: "<synthetic>"` for local and error placeholders,
    # and a Codex turn can report a zero delta; either would otherwise add a row
    # that reports nothing.
    return {model: row for model, row in totals.items() if any(row.values())}


def render_activity_usage(scan: ScanResult, *, harness: str) -> str:
    """Return an aligned per-model token table for the scanned sessions.

    Unlike `opencode stats`, this needs no trailing window: usage rides on the
    activities that `filter_session_to_period` already narrowed, so the table
    covers the report period instead of one ending at generation time.

    It is exact to the activity rather than to the second. Usage from a model
    turn that emitted no activity of its own is carried by a neighbouring
    activity from the same model, so a turn sitting on the period boundary can
    be counted on the other side of it.
    """

    totals = _totals_by_model(scan)
    if not totals:
        display_name = _HARNESS_DISPLAY_NAMES.get(harness, harness)
        raise HarnessSourceError(f"{display_name} sessions carried no token usage")

    ordered = sorted(
        totals.items(),
        key=lambda item: (-item[1].get("output_tokens", 0), item[0]),
    )
    grand_total = {
        key: sum(row.get(key, 0) for _, row in ordered) for _, key in _COLUMNS
    }

    headers = ["Model", *(label for label, _ in _COLUMNS)]
    rows = [
        [model, *(f"{row.get(key, 0):,}" for _, key in _COLUMNS)]
        for model, row in ordered
    ]
    rows.append(["Total", *(f"{grand_total[key]:,}" for _, key in _COLUMNS)])

    widths = [
        max(len(cell) for cell in column) for column in zip(headers, *rows, strict=True)
    ]
    lines = [_format_row(headers, widths)]
    lines.extend(_format_row(row, widths) for row in rows)
    return "\n".join(lines)


def _format_row(cells: list[str], widths: list[int]) -> str:
    first = cells[0].ljust(widths[0])
    rest = "".join(
        f"  {cell.rjust(width)}" for cell, width in zip(cells[1:], widths[1:], strict=True)
    )
    return first + rest
