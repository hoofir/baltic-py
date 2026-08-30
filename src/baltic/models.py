"""Typed views over the BTD export payload.

The API returns a table: a list of ``columns`` describing what is measured, and
a list of intervals whose ``values`` are positional with respect to those
columns. :class:`Export` keeps that shape and offers :meth:`Export.rows` and
:meth:`Export.records` to flatten it for dataframes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Self

from ._params import parse_timestamp

__all__ = ["Column", "Export", "Interval", "Report"]

_GROUP_KEYS = ("group_level_0", "group_level_1", "group_level_2")
_SEPARATOR = " / "


@dataclass(frozen=True, slots=True)
class Report:
    """An exportable report, as listed in the API documentation."""

    id: str
    title: str
    resolutions: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"{self.id} - {self.title}"


@dataclass(frozen=True, slots=True)
class Column:
    """One measured series within an export."""

    index: int
    label: str
    groups: tuple[str, ...] = ()
    resolution: str | None = None

    @property
    def name(self) -> str:
        """Human-readable identifier, e.g. ``"Estonia / Upward"``."""
        return _SEPARATOR.join((*self.groups, self.label))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        groups = tuple(
            str(data[key]) for key in _GROUP_KEYS if data.get(key) not in (None, "")
        )
        return cls(
            index=int(data["index"]),
            label=str(data.get("label", "")),
            groups=groups,
            resolution=data.get("res"),
        )


@dataclass(frozen=True, slots=True)
class Interval:
    """One time step. ``values`` is positional with respect to the columns."""

    start: datetime
    end: datetime
    values: tuple[float | None, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            start=parse_timestamp(data["from"]),
            end=parse_timestamp(data["to"]),
            values=tuple(data.get("values") or ()),
        )


@dataclass(frozen=True, slots=True)
class Export:
    """A single report exported over a time range.

    ``start``/``end`` of every interval are timezone-aware instants; the API
    always emits them in UTC regardless of the requested export timezone.
    """

    id: str
    title: str
    unit: str | None = None
    resolution: str | None = None
    timezone: str | None = None
    local_timezone: str | None = None
    description: str = ""
    created: datetime | None = None
    columns: tuple[Column, ...] = ()
    intervals: tuple[Interval, ...] = ()

    def __len__(self) -> int:
        return len(self.intervals)

    def __repr__(self) -> str:
        span = f"{self.intervals[0].start:%Y-%m-%d}" if self.intervals else "empty"
        return (
            f"<Export {self.id!r} {len(self.columns)} columns, "
            f"{len(self.intervals)} intervals from {span}>"
        )

    @property
    def column_names(self) -> tuple[str, ...]:
        """Column names, de-duplicated so they are safe as dictionary keys."""
        names: list[str] = []
        seen: set[str] = set()
        for column in self.columns:
            name = column.name
            if name in seen:
                name = f"{name} [{column.index}]"
            seen.add(name)
            names.append(name)
        return tuple(names)

    def rows(self) -> list[dict[str, Any]]:
        """One dictionary per interval, one key per column (wide format)."""
        names = self.column_names
        return [
            {
                "start": interval.start,
                "end": interval.end,
                **dict(zip(names, interval.values, strict=False)),
            }
            for interval in self.intervals
        ]

    def records(self) -> list[dict[str, Any]]:
        """One dictionary per interval *and* column (long format)."""
        names = self.column_names
        return [
            {
                "start": interval.start,
                "end": interval.end,
                "column": name,
                "groups": column.groups,
                "label": column.label,
                "value": value,
            }
            for interval in self.intervals
            for name, column, value in zip(
                names, self.columns, interval.values, strict=False
            )
        ]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            unit=data.get("measurement_unit"),
            resolution=data.get("resolution"),
            timezone=data.get("timezone"),
            local_timezone=data.get("local_timezone"),
            description=str(data.get("description") or ""),
            created=_parse_optional(data.get("creation_time")),
            columns=tuple(Column.from_dict(c) for c in data.get("columns") or ()),
            intervals=tuple(
                Interval.from_dict(i) for i in data.get("timeseries") or ()
            ),
        )

    @classmethod
    def concat(cls, parts: list[Self]) -> Self:
        """Join consecutive windows of the same report into one export."""
        if not parts:
            raise ValueError("cannot concatenate an empty list of exports")
        head = parts[0]
        intervals = list(head.intervals)
        for part in parts[1:]:
            if part.column_names != head.column_names:
                raise ValueError(
                    f"{head.id}: columns changed between windows, "
                    "query the sub-ranges separately"
                )
            intervals.extend(part.intervals)
        return replace(head, intervals=tuple(intervals))


def _parse_optional(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_timestamp(value)
    except ValueError:
        return None
