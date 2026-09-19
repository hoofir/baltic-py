"""Transport-level tests: retries, backoff, gzip and the JSON envelope.

``urlopen`` is stubbed, so nothing here touches the network.
"""

import gzip
import io
import json
import urllib.error
from email.message import Message

import pytest

from baltic import _http
from baltic._errors import (
    BalticBadRequest,
    BalticHTTPError,
    BalticServerError,
    BalticTransportError,
)

URL = "https://api-baltic.transparency-dashboard.eu/api/v1/export"

OK = json.dumps({"error": False, "message": None, "data": {"id": "x"}}).encode()


class FakeResponse:
    def __init__(self, body=OK, encoding=None):
        self._body = body
        self.headers = Message()
        if encoding:
            self.headers["Content-Encoding"] = encoding

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def http_error(code, body=b"", encoding=None):
    headers = Message()
    if encoding:
        headers["Content-Encoding"] = encoding
    return urllib.error.HTTPError(URL, code, "err", headers, io.BytesIO(body))


def error_body(*messages):
    return json.dumps({"error": True, "message": list(messages), "data": None}).encode()


@pytest.fixture
def transport(monkeypatch):
    """Queue outcomes for successive urlopen calls and count the attempts."""
    outcomes: list[object] = []
    attempts: list[str] = []

    def fake_urlopen(request, timeout=None):
        attempts.append(request.full_url)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(_http.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(_http.time, "sleep", lambda _: None)
    return outcomes, attempts


def get_bytes(*, timeout=10, retries=2, backoff=0.5, user_agent="test"):
    return _http.get_bytes(
        URL,
        timeout=timeout,
        retries=retries,
        backoff=backoff,
        user_agent=user_agent,
    )


def get_data(*, timeout=10, retries=2, backoff=0.5, user_agent="test"):
    return _http.get_data(
        URL,
        timeout=timeout,
        retries=retries,
        backoff=backoff,
        user_agent=user_agent,
    )


# -- success paths ----------------------------------------------------------


def test_returns_the_raw_body(transport):
    outcomes, _ = transport
    outcomes.append(FakeResponse(body=b"PK\x03\x04"))
    assert get_bytes() == b"PK\x03\x04"


def test_gzip_body_is_decompressed(transport):
    outcomes, _ = transport
    outcomes.append(FakeResponse(body=gzip.compress(OK), encoding="gzip"))
    assert get_data() == {"id": "x"}


def test_envelope_is_unwrapped(transport):
    outcomes, _ = transport
    outcomes.append(FakeResponse())
    assert get_data() == {"id": "x"}


def test_request_headers_are_set(transport, monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["headers"] = dict(request.headers)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(_http.urllib.request, "urlopen", fake_urlopen)
    get_data(user_agent="baltic-py/1.2.3", timeout=42)

    assert captured["headers"]["Accept-encoding"] == "gzip"
    assert captured["headers"]["User-agent"] == "baltic-py/1.2.3"
    assert captured["timeout"] == 42


# -- envelope errors --------------------------------------------------------


def test_error_flag_on_a_200_is_raised(transport):
    outcomes, _ = transport
    outcomes.append(FakeResponse(body=error_body("Invalid export ID.")))
    with pytest.raises(BalticBadRequest) as excinfo:
        get_data()
    assert excinfo.value.messages == ["Invalid export ID."]
    assert "Invalid export ID." in str(excinfo.value)


def test_missing_envelope_is_reported(transport):
    outcomes, _ = transport
    outcomes.append(FakeResponse(body=b'{"nope": 1}'))
    with pytest.raises(BalticHTTPError, match="unexpected response envelope"):
        get_data()


def test_invalid_json_raises_without_retrying(transport):
    outcomes, attempts = transport
    outcomes.append(FakeResponse(body=b"not json"))
    with pytest.raises(BalticHTTPError, match="invalid JSON"):
        get_data(retries=3)
    assert len(attempts) == 1


# -- status handling --------------------------------------------------------


def test_client_error_is_not_retried(transport):
    outcomes, attempts = transport
    outcomes.append(http_error(400, error_body("Missing date start.")))
    with pytest.raises(BalticBadRequest) as excinfo:
        get_data(retries=5)
    assert excinfo.value.status == 400
    assert excinfo.value.messages == ["Missing date start."]
    assert len(attempts) == 1


def test_string_message_is_normalised_to_a_list(transport):
    outcomes, _ = transport
    body = json.dumps({"error": True, "message": "boom", "data": None}).encode()
    outcomes.append(http_error(422, body))
    with pytest.raises(BalticBadRequest) as excinfo:
        get_data()
    assert excinfo.value.messages == ["boom"]


def test_non_json_error_body_still_raises(transport):
    outcomes, _ = transport
    outcomes.append(http_error(400, b"<html>nope</html>"))
    with pytest.raises(BalticBadRequest) as excinfo:
        get_data()
    assert excinfo.value.messages == []
    assert "nope" in excinfo.value.body
    assert str(excinfo.value).startswith("HTTP 400")


@pytest.mark.parametrize("body", [b"[1, 2]", b'{"message": null}', b"nope"])
def test_unparseable_messages_are_empty(body):
    assert _http.messages(body) == []


def test_gzip_error_body_is_decompressed(transport):
    outcomes, _ = transport
    outcomes.append(http_error(400, gzip.compress(error_body("nope")), "gzip"))
    with pytest.raises(BalticBadRequest) as excinfo:
        get_data()
    assert excinfo.value.messages == ["nope"]


def test_server_error_is_retried_then_succeeds(transport):
    outcomes, attempts = transport
    outcomes.extend([http_error(503), FakeResponse()])
    assert get_data(retries=2) == {"id": "x"}
    assert len(attempts) == 2


def test_server_error_raises_after_retries_are_exhausted(transport):
    outcomes, attempts = transport
    outcomes.extend([http_error(500, b"boom")] * 3)
    with pytest.raises(BalticServerError) as excinfo:
        get_data(retries=2)
    assert excinfo.value.status == 500
    assert len(attempts) == 3, "initial attempt plus two retries"


def test_transport_failure_is_retried(transport):
    outcomes, attempts = transport
    outcomes.extend([urllib.error.URLError("dns"), FakeResponse()])
    assert get_data(retries=1) == {"id": "x"}
    assert len(attempts) == 2


def test_transport_failure_raises_after_retries(transport):
    outcomes, attempts = transport
    outcomes.extend([urllib.error.URLError("dns")] * 2)
    with pytest.raises(BalticTransportError, match="dns"):
        get_data(retries=1)
    assert len(attempts) == 2


def test_timeout_is_retried_then_raises(transport):
    outcomes, attempts = transport
    outcomes.extend([TimeoutError("slow")] * 2)
    with pytest.raises(BalticTransportError, match="timed out"):
        get_data(retries=1)
    assert len(attempts) == 2


def test_retries_can_be_disabled(transport):
    outcomes, attempts = transport
    outcomes.append(http_error(502))
    with pytest.raises(BalticServerError):
        get_data(retries=0)
    assert len(attempts) == 1


def test_backoff_grows_exponentially(transport, monkeypatch):
    outcomes, _ = transport
    delays: list[float] = []
    monkeypatch.setattr(_http.time, "sleep", delays.append)
    outcomes.extend([http_error(500)] * 4)

    with pytest.raises(BalticServerError):
        get_data(retries=3, backoff=0.5)

    assert delays == [0.5, 1.0, 2.0]


def test_no_sleep_after_the_final_attempt(transport, monkeypatch):
    outcomes, _ = transport
    delays: list[float] = []
    monkeypatch.setattr(_http.time, "sleep", delays.append)
    outcomes.append(http_error(500))

    with pytest.raises(BalticServerError):
        get_data(retries=0)

    assert delays == []


# -- URL building -----------------------------------------------------------


@pytest.mark.parametrize(
    ("base", "path", "params", "expected"),
    [
        ("https://x.test", "/A", None, "https://x.test/A"),
        ("https://x.test/", "A", None, "https://x.test/A"),
        ("https://x.test", "/A", {}, "https://x.test/A"),
        ("https://x.test", "/A", {"b": 1}, "https://x.test/A?b=1"),
        ("https://x.test", "/A", {"id": "a,b"}, "https://x.test/A?id=a%2Cb"),
    ],
)
def test_build_url(base, path, params, expected):
    assert _http.build_url(base, path, params) == expected


@pytest.mark.parametrize("base", ["file:///etc/passwd", "ftp://x.test", "x.test"])
def test_build_url_rejects_non_http_schemes(base):
    with pytest.raises(ValueError, match="http or https"):
        _http.build_url(base, "/A", None)
