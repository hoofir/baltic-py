"""Pythonic client for the Baltic Transparency Dashboard open API.

The API is public and read-only, so the module-level helpers below are bound to
a shared default client and need no setup::

    import baltic

    baltic.reports("imbalance")
    export = baltic.export(
        "imbalance_prices", start="2024-01-01", end="2024-02-01"
    )
    export.rows()

Create a :class:`Client` explicitly to change the timeout, retry policy, default
timezone or the time window used to split long queries.
"""

from __future__ import annotations

from . import models
from ._client import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_WINDOW,
    MINUTE_MAX_WINDOW,
    Client,
    __version__,
)
from ._errors import (
    BalticBadRequest,
    BalticError,
    BalticHTTPError,
    BalticServerError,
    BalticTransportError,
)
from ._params import OUTPUT_FORMATS, TIMEZONES
from ._reports import CATEGORIES, REPORT_IDS, report, reports

_default = Client()

export = _default.export
export_many = _default.export_many
download = _default.download
download_many = _default.download_many

__all__ = [
    "CATEGORIES",
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_WINDOW",
    "MINUTE_MAX_WINDOW",
    "OUTPUT_FORMATS",
    "REPORT_IDS",
    "TIMEZONES",
    "BalticBadRequest",
    "BalticError",
    "BalticHTTPError",
    "BalticServerError",
    "BalticTransportError",
    "Client",
    "__version__",
    "download",
    "download_many",
    "export",
    "export_many",
    "models",
    "report",
    "reports",
]
