"""Minimal HTTP transport built on the standard library."""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPResponse
from typing import Any

from ._errors import (
    BalticBadRequest,
    BalticHTTPError,
    BalticServerError,
    BalticTransportError,
)

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def build_url(base_url: str, path: str, params: dict[str, Any] | None) -> str:
    scheme = urllib.parse.urlsplit(base_url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"base_url must use http or https, got {base_url!r}")
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def _read(response: HTTPResponse | urllib.error.HTTPError) -> bytes:
    body = response.read()
    if response.headers.get("Content-Encoding") == "gzip":
        return gzip.decompress(body)
    return body


def messages(body: bytes) -> list[str]:
    """Pull the ``message`` field out of the API's JSON error envelope."""
    try:
        payload = json.loads(body)
    except ValueError:
        return []
    if not isinstance(payload, dict):
        return []
    message = payload.get("message")
    if isinstance(message, str):
        return [message]
    if isinstance(message, list):
        return [str(item) for item in message]
    return []


def get_bytes(
    url: str,
    *,
    timeout: float,
    retries: int,
    backoff: float,
    user_agent: str,
) -> bytes:
    """Perform a GET request and return the raw response body.

    Retries transport failures and 5xx responses with exponential backoff.
    """
    request = urllib.request.Request(  # noqa: S310 - scheme validated in build_url
        url,
        headers={
            "Accept": "*/*",
            "Accept-Encoding": "gzip",
            "User-Agent": user_agent,
        },
        method="GET",
    )

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return _read(response)
        except urllib.error.HTTPError as exc:
            body = _read(exc)
            text = body.decode("utf-8", "replace")
            if exc.code < 500:
                raise BalticBadRequest(exc.code, url, text, messages(body)) from None
            last_error = BalticServerError(exc.code, url, text)
        except urllib.error.URLError as exc:
            last_error = BalticTransportError(f"request to {url} failed: {exc.reason}")
        except TimeoutError as exc:
            last_error = BalticTransportError(f"request to {url} timed out: {exc}")

        if attempt < retries:
            time.sleep(backoff * 2**attempt)

    assert last_error is not None
    raise last_error


def get_data(
    url: str,
    *,
    timeout: float,
    retries: int,
    backoff: float,
    user_agent: str,
) -> Any:
    """GET a JSON envelope and return its ``data`` payload.

    Every BTD response is wrapped in ``{"error": ..., "message": ..., "data": ...}``.
    The API also answers some rejected queries with HTTP 200 and ``error: true``.
    """
    body = get_bytes(
        url, timeout=timeout, retries=retries, backoff=backoff, user_agent=user_agent
    )
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise BalticHTTPError(200, url, f"invalid JSON response: {exc}") from exc
    if not isinstance(payload, dict) or "data" not in payload:
        raise BalticHTTPError(200, url, f"unexpected response envelope: {payload!r}")
    if payload.get("error"):
        raise BalticBadRequest(
            200, url, body.decode("utf-8", "replace"), messages(body)
        )
    return payload["data"]
