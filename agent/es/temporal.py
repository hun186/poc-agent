"""Calendar intervals for extracted Event / Event_Timeline dates.

ES stores time_iso as a date (an instant).  The companion time_precision is
needed to distinguish an entire year/month from its normalized first instant.
This module never guesses a broader precision from a full YYYY-MM-DD value.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional


_DATE_PREFIX = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?(?=$|[T ])")


@dataclass(frozen=True)
class TemporalInterval:
    start: date
    end: date
    precision: str

    @property
    def iso(self) -> str:
        return self.start.isoformat()

    def intersects(self, lower: Optional[date], upper: Optional[date]) -> bool:
        return (lower is None or self.end >= lower) and (upper is None or self.start <= upper)


def parse_temporal_interval(value: Any, precision: Any = None) -> Optional[TemporalInterval]:
    """Parse valid Gregorian year/month/day sources, including ISO datetimes.

    An unknown precision can only be used at its literal calendar granularity.
    In particular, a full date without a trustworthy precision is one day,
    not an assumed month or year. Invalid dates are never silently corrected.
    """
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str):
        return None
    match = _DATE_PREFIX.match(value.strip())
    if not match:
        return None
    year_s, month_s, day_s = match.groups()
    year = int(year_s)
    if not (1900 <= year <= 2100):
        return None
    observed = "day" if day_s is not None else "month" if month_s is not None else "year"
    wanted = precision.strip().lower() if isinstance(precision, str) else ""
    if wanted not in ("day", "month", "year"):
        wanted = observed
    try:
        # Validate all provided parts, even when coarser precision is declared.
        if day_s is not None:
            date(year, int(month_s), int(day_s))
        elif month_s is not None:
            date(year, int(month_s), 1)
        if wanted == "year":
            return TemporalInterval(date(year, 1, 1), date(year, 12, 31), wanted)
        if month_s is None:
            return None
        month = int(month_s)
        if wanted == "month":
            return TemporalInterval(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]), wanted)
        if day_s is None:
            return None
        exact = date(year, month, int(day_s))
        return TemporalInterval(exact, exact, wanted)
    except ValueError:
        return None
