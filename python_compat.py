"""Compatibility helpers for the project's supported Python runtimes."""

import enum


if hasattr(enum, "StrEnum"):
    StrEnum = enum.StrEnum
else:
    class StrEnum(str, enum.Enum):
        """Python 3.10-compatible subset of :class:`enum.StrEnum`."""

        def __str__(self) -> str:
            return self.value
