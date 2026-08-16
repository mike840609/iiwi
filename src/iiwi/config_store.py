"""Locate, inspect, and edit the user's settings file."""

from __future__ import annotations

import difflib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key
from platformdirs import user_config_dir
from pydantic import BaseModel, ValidationError

from iiwi.config import AppSettings
from iiwi.errors import ConfigurationError

ENV_PREFIX = "IIWI_"
CONFIG_FILE_VARIABLE = "IIWI_CONFIG_FILE"


def config_file_path() -> Path:
    """Return the settings file, honoring an explicit override.

    The override is what makes the file testable, and it doubles as the escape
    hatch for anyone who wants a per-project file instead of one per machine.
    """

    override = os.environ.get(CONFIG_FILE_VARIABLE)
    if override:
        return Path(override).expanduser()
    return Path(user_config_dir("iiwi")) / "config.env"


def _as_text(value: object) -> str:
    """Render a default the way a user would type it into the file."""

    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@dataclass(frozen=True)
class SettingKey:
    """One settable leaf: its dotted name, its variable, and its fallback.

    `owner` and `name` let `validate_value` run the owning model's own
    validation — Field constraints and validators — on the incoming string.
    """

    key: str
    variable: str
    annotation: type
    default: str
    owner: type[BaseModel]
    name: str


@dataclass(frozen=True)
class SettingRow:
    """One setting as `config list` shows it."""

    key: str
    value: str
    source: str
    default: str


def _walk(model: type[BaseModel], prefix: tuple[str, ...]) -> Iterator[SettingKey]:
    for name, field in model.model_fields.items():
        annotation = field.annotation
        path = (*prefix, name)
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            yield from _walk(annotation, path)
            continue
        default = field.get_default(call_default_factory=True, validated_data={})
        dotted = ".".join(path)
        yield SettingKey(
            key=dotted,
            variable=ENV_PREFIX + dotted.upper().replace(".", "__"),
            # `field.annotation` is typed as `type[Any] | None` by pydantic, so
            # non-class annotations (e.g. a generic) fall back to `str` purely
            # to satisfy the type checker here — validation itself runs through
            # the owning model, not this annotation.
            annotation=annotation if isinstance(annotation, type) else str,
            default=_as_text(default),
            owner=model,
            name=name,
        )


def setting_keys() -> tuple[SettingKey, ...]:
    """Every settable leaf, derived from the model tree, not a hand-kept list.

    A new field in `config.py` becomes settable the moment it exists; neither
    this module nor the CLI has to learn its name.
    """

    return tuple(_walk(AppSettings, ()))


def resolve_key(key: str) -> SettingKey:
    """Reject an unknown key before it can reach the file."""

    index = {setting.key: setting for setting in setting_keys()}
    normalized = key.strip().lower()
    found = index.get(normalized)
    if found is not None:
        return found
    suggestions = difflib.get_close_matches(normalized, index, n=1)
    hint = f"; did you mean {suggestions[0]}?" if suggestions else ""
    raise ConfigurationError(f"unknown setting: {key}{hint}")


def validate_value(setting: SettingKey, value: str) -> None:
    """Reject a value the settings model would reject at load time.

    Environment values arrive as strings, so validating through the owning
    model is the same parse pydantic-settings performs, Field constraints and
    validators included: a bad number or timezone fails here, not on the next
    run.
    """

    try:
        setting.owner.model_validate({setting.name: value})
    except ValidationError as exc:
        detail = exc.errors()[0]["msg"]
        raise ConfigurationError(f"invalid value for {setting.key}: {detail}") from exc


def _resolve_path(path: Path | None) -> Path:
    """The one place the "explicit path, else the resolved default" idiom lives."""

    return path or config_file_path()


def _prepare_file(path: Path) -> None:
    """Create the file the first time only, owner-only, before dotenv writes to it.

    The mode is set only on a file this call creates: a pre-existing file —
    for instance one `IIWI_CONFIG_FILE` points at that some other
    tool or teammate already owns — must keep whatever mode it already has,
    not silently become 0600 on the first `config set`. `O_EXCL` makes
    "create if absent" atomic instead of a check-then-act race.
    """

    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return
        try:
            # The mode above is masked by umask; fchmod pins the exact bits,
            # mirroring secure_files.py's atomic_secure_write.
            if os.name == "posix":
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ConfigurationError(f"cannot prepare settings file: {path}: {exc}") from exc


def stored_values(path: Path | None = None) -> dict[str, str]:
    """Return the variables the settings file defines, ignoring valueless lines."""

    file_path = _resolve_path(path)
    try:
        values = dotenv_values(file_path)
    except OSError as exc:
        raise ConfigurationError(f"cannot read settings file: {file_path}: {exc}") from exc
    return {name: value for name, value in values.items() if value is not None}


def set_value(key: str, value: str, *, path: Path | None = None) -> SettingKey:
    """Record one setting, replacing any earlier entry for it."""

    setting = resolve_key(key)
    # Validate before touching the disk: a rejected value must not leave a file
    # behind that the user then has to clean up.
    validate_value(setting, value)
    file_path = _resolve_path(path)
    _prepare_file(file_path)
    try:
        written, _, _ = set_key(str(file_path), setting.variable, value)
    except OSError as exc:
        raise ConfigurationError(f"cannot write settings file: {file_path}: {exc}") from exc
    if not written:
        raise ConfigurationError(f"failed to write settings file: {file_path}")
    return setting


def unset_value(key: str, *, path: Path | None = None) -> tuple[SettingKey, bool]:
    """Remove one setting; report whether the file actually held it."""

    setting = resolve_key(key)
    file_path = _resolve_path(path)
    if setting.variable not in stored_values(file_path):
        # Asking dotenv to remove an absent key logs a warning to stderr, and a
        # no-op is not a warning: the user asked for the default and has it.
        return setting, False
    try:
        removed, _ = unset_key(str(file_path), setting.variable)
    except OSError as exc:
        raise ConfigurationError(f"cannot write settings file: {file_path}: {exc}") from exc
    # Symmetric with set_value's check of set_key's return value: the key was
    # confirmed present just above, so a falsy result here means the write
    # itself failed, not that there was nothing to remove.
    if not removed:
        raise ConfigurationError(f"failed to write settings file: {file_path}")
    return setting, True


def describe_settings(path: Path | None = None) -> tuple[SettingRow, ...]:
    """Report every setting with the value in force and where it comes from.

    Deliberately built from the file and the environment rather than from a
    loaded `AppSettings`: one bad value must not stop `config list` from showing
    which value is bad, or `config unset` from removing it.
    """

    file_path = _resolve_path(path)
    stored = stored_values(file_path)
    rows = []
    for setting in setting_keys():
        environment_value = os.environ.get(setting.variable)
        file_value = stored.get(setting.variable)
        if environment_value is not None:
            value, source = environment_value, "environment"
        elif file_value is not None:
            value, source = file_value, "file"
        else:
            value, source = setting.default, "default"
        rows.append(
            SettingRow(
                key=setting.key,
                value=value,
                source=source,
                default=setting.default,
            )
        )
    return tuple(rows)
