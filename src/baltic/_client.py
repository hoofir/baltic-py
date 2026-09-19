"""The synchronous Baltic Transparency Dashboard client."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Sequence
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from types import TracebackType
from typing import Self

from . import _reports
from ._errors import BalticError
from ._http import build_url, get_bytes, get_data
from ._params import (
    OutputFormat,
    TimeLike,
    Timezone,
    check_output_format,
    check_timezone,
    format_datetime,
    time_windows,
    to_datetime,
)
from ._reports import ReportLike
from .models import Export

DEFAULT_BASE_URL = "https://api-baltic.transparency-dashboard.eu"
DEFAULT_MAX_WINDOW = timedelta(days=366)
#: Minute-resolution reports return ~500k rows per year, so they get a shorter window.
MINUTE_MAX_WINDOW = timedelta(days=92)

_EXPORT = "/api/v1/export"
_EXPORT_MULTIPLE = "/api/v1/export-multiple"

try:
    __version__ = version("baltic-py")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"


class Client:
    """Access to the Baltic Transparency Dashboard open API.

    The API is public, read-only and unauthenticated, so a client is little more
    than a configuration holder.

    Args:
        base_url: API root. Only ``http`` and ``https`` are accepted.
        timeout: Per-request socket timeout in seconds.
        retries: Extra attempts for transport failures and 5xx responses.
        backoff: Base delay in seconds for the exponential retry backoff.
        tz: Default export timezone. It decides how naive ``start``/``end``
            values are read and how ``csv``/``xlsx`` timestamps are rendered.
        max_window: Longest time span requested in a single call. Longer ranges
            are split into consecutive windows and stitched back together. The
            API treats ``end`` as exclusive, so no interval is duplicated. Pass
            ``None`` to always issue a single request.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        retries: int = 3,
        backoff: float = 0.5,
        tz: Timezone = "UTC",
        max_window: timedelta | None = DEFAULT_MAX_WINDOW,
        user_agent: str = f"baltic-py/{__version__}",
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.tz = check_timezone(tz)
        self.max_window = max_window
        self.user_agent = user_agent

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    # -- exports -----------------------------------------------------------

    def export(
        self,
        report: ReportLike,
        *,
        start: TimeLike,
        end: TimeLike,
        tz: Timezone | None = None,
    ) -> Export:
        """Export one report as a parsed :class:`~baltic.models.Export`."""
        report_id = _reports.resolve(report, multiple=False)[0]
        zone = check_timezone(tz or self.tz)
        parts = [
            Export.from_dict(
                get_data(
                    self._url(_EXPORT, [report_id], window, zone, "json"),
                    timeout=self.timeout,
                    retries=self.retries,
                    backoff=self.backoff,
                    user_agent=self.user_agent,
                )
            )
            for window in self._windows(start, end, zone, [report_id])
        ]
        return Export.concat(parts)

    def export_many(
        self,
        reports: Sequence[ReportLike],
        *,
        start: TimeLike,
        end: TimeLike,
        tz: Timezone | None = None,
    ) -> dict[str, Export]:
        """Export several reports at once, keyed by report ID.

        The API serves these as a ZIP archive of one file per report and accepts
        at most :data:`~baltic._catalog.MAX_REPORTS_PER_REQUEST` of them.
        """
        report_ids = _reports.resolve(reports, multiple=True)
        zone = check_timezone(tz or self.tz)
        parts: dict[str, list[Export]] = {report_id: [] for report_id in report_ids}
        for window in self._windows(start, end, zone, report_ids):
            url = self._url(_EXPORT_MULTIPLE, report_ids, window, zone, "json")
            for payload in _unpack(self._bytes(url), url):
                export = Export.from_dict(payload)
                parts.setdefault(export.id, []).append(export)
        return {
            report_id: Export.concat(windows)
            for report_id, windows in parts.items()
            if windows
        }

    # -- raw downloads -----------------------------------------------------

    def download(
        self,
        report: ReportLike,
        *,
        start: TimeLike,
        end: TimeLike,
        output_format: OutputFormat = "csv",
        tz: Timezone | None = None,
    ) -> bytes:
        """Download one report verbatim, as ``csv``, ``xlsx`` or ``json`` bytes.

        Downloads are never split into windows: the file formats cannot be
        concatenated safely.
        """
        report_id = _reports.resolve(report, multiple=False)[0]
        zone = check_timezone(tz or self.tz)
        window = self._window(start, end, zone)
        url = self._url(
            _EXPORT, [report_id], window, zone, check_output_format(output_format)
        )
        return self._bytes(url)

    def download_many(
        self,
        reports: Sequence[ReportLike],
        *,
        start: TimeLike,
        end: TimeLike,
        output_format: OutputFormat = "csv",
        tz: Timezone | None = None,
    ) -> bytes:
        """Download several reports as the bytes of a ZIP archive."""
        report_ids = _reports.resolve(reports, multiple=True)
        zone = check_timezone(tz or self.tz)
        window = self._window(start, end, zone)
        url = self._url(
            _EXPORT_MULTIPLE,
            report_ids,
            window,
            zone,
            check_output_format(output_format),
        )
        return self._bytes(url)

    # -- internals ---------------------------------------------------------

    def _url(
        self,
        path: str,
        report_ids: Sequence[str],
        window: tuple[datetime, datetime],
        tz: str,
        output_format: str,
    ) -> str:
        return build_url(
            self.base_url,
            path,
            {
                "id": ",".join(report_ids),
                "start_date": format_datetime(window[0]),
                "end_date": format_datetime(window[1]),
                "output_time_zone": tz,
                "output_format": output_format,
            },
        )

    def _bytes(self, url: str) -> bytes:
        return get_bytes(
            url,
            timeout=self.timeout,
            retries=self.retries,
            backoff=self.backoff,
            user_agent=self.user_agent,
        )

    def _window(
        self, start: TimeLike, end: TimeLike, tz: str
    ) -> tuple[datetime, datetime]:
        first = to_datetime(start, tz=tz, name="start")
        last = to_datetime(end, tz=tz, name="end")
        if last <= first:
            raise ValueError("end must be later than start")
        return first, last

    def _windows(
        self, start: TimeLike, end: TimeLike, tz: str, report_ids: Sequence[str]
    ) -> list[tuple[datetime, datetime]]:
        first, last = self._window(start, end, tz)
        return list(time_windows(first, last, self._max_window(report_ids)))

    def _max_window(self, report_ids: Sequence[str]) -> timedelta | None:
        if self.max_window is None:
            return None
        if any("PT1M" in _reports.report(i).resolutions for i in report_ids):
            return min(self.max_window, MINUTE_MAX_WINDOW)
        return self.max_window


def _unpack(body: bytes, url: str) -> list[dict[str, object]]:
    """Read the export payloads out of an export-multiple response."""
    if body[:2] != b"PK":
        payload = json.loads(body)
        return [payload["data"]] if isinstance(payload, dict) else []
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            return [
                json.loads(archive.read(name)) for name in sorted(archive.namelist())
            ]
    except (zipfile.BadZipFile, ValueError) as exc:
        raise BalticError(
            f"could not read the archive returned by {url}: {exc}"
        ) from exc
