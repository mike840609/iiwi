"""Settings rows for the interactive settings editor."""

from __future__ import annotations

from dataclasses import dataclass

from iiwi import config_store
from iiwi.models.report_options import ReportType

# A hand-kept shortlist, not the ~600-entry IANA set: the row shows one value
# anyway, and Enter on the row types any zone the shortlist omits.
TIMEZONE_CHOICES = (
    "Asia/Taipei",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Asia/Singapore",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Los_Angeles",
    "UTC",
)

# Keys whose choices a plain string annotation cannot express. `source` has
# one implemented value, so its "choices" are a single-entry list.
_KEY_CHOICES = {
    "harnesses.opencode.source": ("cli",),
    "report.timezone": TIMEZONE_CHOICES,
}


@dataclass(frozen=True)
class SettingsRow:
    """One setting as the editor shows it: value, source, and how to change it."""

    key: str
    label: str
    value: str
    source: str
    default: str
    choices: tuple[str, ...]
    show_all: bool
    locked: bool
    variable: str

    @property
    def editable(self) -> bool:
        """Enter opens the inline editor (free text or an out-of-list timezone)."""
        return not self.show_all


def _label(key: str) -> str:
    """The row label: the dotted key without the `harnesses.` prefix."""
    return key.removeprefix("harnesses.")


def _choices_for(annotation: type, key: str) -> tuple[str, ...]:
    if key in _KEY_CHOICES:
        return _KEY_CHOICES[key]
    if annotation is bool:
        return ("true", "false")
    if annotation is ReportType:
        return tuple(member.value for member in ReportType)
    return ()


def _show_all(key: str, choices: tuple[str, ...]) -> bool:
    """Which rows render every choice: enum/bool rows yes, timezone no."""
    return key != "report.timezone" and bool(choices)


def build_settings_rows() -> list[SettingsRow]:
    """Build editor rows from the same source `config list` uses."""

    keys = {setting.key: setting for setting in config_store.setting_keys()}
    rows = []
    for row in config_store.describe_settings():
        setting = keys[row.key]
        choices = _choices_for(setting.annotation, row.key)
        rows.append(
            SettingsRow(
                key=row.key,
                label=_label(row.key),
                value=row.value,
                source=row.source,
                default=row.default,
                choices=choices,
                show_all=_show_all(row.key, choices),
                locked=row.source == "environment",
                variable=setting.variable,
            )
        )
    return rows


def next_choice(row: SettingsRow, value: str, *, right: bool) -> str:
    """The choice one step around the row's list, wrapping at both ends."""

    if not row.choices:
        return value
    try:
        index = row.choices.index(value)
    except ValueError:
        # The value in force is outside the cycle list (e.g. a custom
        # timezone); the first step from it lands on the nearest end.
        return row.choices[0] if right else row.choices[-1]
    step = 1 if right else -1
    return row.choices[(index + step) % len(row.choices)]


def write_setting(key: str, value: str) -> None:
    """Persist one setting; an empty value restores the default.

    Raises ConfigurationError when the value is invalid or the file cannot
    be written; the editor keeps its previous value in that case.
    """

    if not value:
        config_store.unset_value(key)
    else:
        config_store.set_value(key, value)
