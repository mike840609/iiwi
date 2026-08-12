"""Options shared by report models and renderers."""

from enum import StrEnum


class DetailLevel(StrEnum):
    BRIEF = "brief"
    FULL = "full"


class ReportType(StrEnum):
    MANAGER = "manager"
    ENGINEERING = "engineering"
