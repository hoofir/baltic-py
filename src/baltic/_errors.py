"""Exceptions raised by :mod:`baltic`."""

from __future__ import annotations

__all__ = [
    "BalticBadRequest",
    "BalticError",
    "BalticHTTPError",
    "BalticServerError",
    "BalticTransportError",
]


class BalticError(Exception):
    """Base class for every error raised by this package."""


class BalticTransportError(BalticError):
    """The request could not be completed (network failure, timeout, DNS)."""


class BalticHTTPError(BalticError):
    """The API returned an unsuccessful HTTP status."""

    def __init__(self, status: int, url: str, body: str) -> None:
        super().__init__(f"HTTP {status} for {url}: {body[:500]}")
        self.status = status
        self.url = url
        self.body = body


class BalticBadRequest(BalticHTTPError):
    """The API rejected the query parameters (HTTP 4xx)."""

    def __init__(
        self,
        status: int,
        url: str,
        body: str,
        messages: list[str] | None = None,
    ) -> None:
        super().__init__(status, url, body)
        self.messages = messages or []

    def __str__(self) -> str:
        if not self.messages:
            return super().__str__()
        return f"HTTP {self.status} for {self.url}: {'; '.join(self.messages)}"


class BalticServerError(BalticHTTPError):
    """The API failed to serve the request (HTTP 5xx)."""
