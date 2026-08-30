"""Lookup helpers over the generated report catalog."""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from typing import TypeAlias

from ._catalog import MAX_REPORTS_PER_REQUEST, REPORTS
from .models import Report

ReportLike: TypeAlias = "str | Report"

REPORT_IDS: tuple[str, ...] = tuple(item.id for item in REPORTS)
CATEGORIES: tuple[str, ...] = tuple(
    sorted({category for item in REPORTS for category in item.categories})
)

_BY_ID: dict[str, Report] = {item.id: item for item in REPORTS}


def report(report_id: ReportLike) -> Report:
    """Look up a single report by ID.

    Raises ``ValueError`` with close matches for an unknown ID, so typos are
    caught before a request is made.
    """
    if isinstance(report_id, Report):
        return report_id
    try:
        return _BY_ID[report_id]
    except KeyError:
        suggestions = difflib.get_close_matches(report_id, REPORT_IDS, n=3, cutoff=0.5)
        hint = f", did you mean {' or '.join(suggestions)}?" if suggestions else ""
        raise ValueError(f"unknown report {report_id!r}{hint}") from None


def reports(search: str | None = None, *, category: str | None = None) -> list[Report]:
    """List the available reports, optionally filtered.

    ``search`` matches the ID and the title case-insensitively; ``category``
    must be one of :data:`CATEGORIES`.
    """
    if category is not None and category not in CATEGORIES:
        raise ValueError(
            f"unknown category {category!r}, expected one of {', '.join(CATEGORIES)}"
        )
    needle = (search or "").casefold()
    return [
        item
        for item in REPORTS
        if (
            not needle
            or needle in item.id.casefold()
            or needle in item.title.casefold()
        )
        and (category is None or category in item.categories)
    ]


def resolve(value: ReportLike | Sequence[ReportLike], *, multiple: bool) -> list[str]:
    """Validate one or more reports and return their IDs."""
    values: Sequence[ReportLike]
    values = [value] if isinstance(value, str | Report) else list(value)
    if not values:
        raise ValueError("at least one report is required")
    if multiple and len(values) > MAX_REPORTS_PER_REQUEST:
        raise ValueError(
            f"the API exports at most {MAX_REPORTS_PER_REQUEST} reports per request, "
            f"got {len(values)}"
        )
    return [report(item).id for item in values]
