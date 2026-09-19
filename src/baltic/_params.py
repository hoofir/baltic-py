"""Query-parameter normalisation and time-window splitting."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Literal, TypeAlias
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ._errors import BalticError

TimeLike: TypeAlias = "str | date | datetime"
Timezone: TypeAlias = Literal["EET", "CET", "UTC"]
OutputFormat: TypeAlias = Literal["json", "csv", "xlsx"]

TIMEZONES: tuple[str, ...] = ("EET", "CET", "UTC")
OUTPUT_FORMATS: tuple[str, ...] = ("json", "csv", "xlsx")


def zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - platform dependent
        raise BalticError(
            f"no time-zone database entry for {tz!r}; install the 'tzdata' package"
        ) from exc


def check_timezone(value: str) -> str:
    if value not in TIMEZONES:
        raise ValueError(f"tz must be one of {', '.join(TIMEZONES)}, got {value!r}")
    return value


def check_output_format(value: str) -> str:
    if value not in OUTPUT_FORMATS:
        raise ValueError(
            f"output_format must be one of {', '.join(OUTPUT_FORMATS)}, got {value!r}"
        )
    return value


def to_datetime(value: TimeLike, *, tz: str, name: str) -> datetime:
    """Coerce a user-supplied instant to wall-clock time in the export timezone.

    Naive values are taken to already be in ``tz``; aware values are converted
    into it. The result is naive, matching what the API accepts.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"{name}: expected an ISO 8601 date or datetime, got {value!r}"
            ) from exc
    else:
        raise TypeError(
            f"{name}: expected str, date or datetime, got {type(value).__name__}"
        )

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(zone(tz)).replace(tzinfo=None)
    return parsed


def format_datetime(value: datetime) -> str:
    """Render an instant in the exact format the API accepts."""
    return value.strftime("%Y-%m-%dT%H:%M")


def parse_timestamp(value: str) -> datetime:
    """Parse a timestamp returned by the API into an aware datetime."""
    return datetime.fromisoformat(value)


def time_windows(
    start: datetime, end: datetime, max_window: timedelta | None
) -> Iterator[tuple[datetime, datetime]]:
    """Split ``[start, end)`` into consecutive windows of at most ``max_window``.

    The API treats ``end`` as exclusive, so the windows never overlap and the
    concatenated results contain no duplicated intervals.
    """
    if end <= start:
        raise ValueError("end must be later than start")
    if max_window is None or end - start <= max_window:
        yield start, end
        return
    cursor = start
    while cursor < end:
        stop = min(cursor + max_window, end)
        yield cursor, stop
        cursor = stop
