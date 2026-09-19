import io
import json
import urllib.parse
import zipfile
from datetime import timedelta

import pytest
from conftest import payload

import baltic
from baltic import _client


def zipped(*payloads):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for item in payloads:
            archive.writestr(f"{item['id']}.json", json.dumps(item))
    return buffer.getvalue()


def params(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


@pytest.fixture
def recorder(monkeypatch):
    """Replace the transport and record every URL the client requests."""
    calls: list[str] = []
    responses: list[object] = []

    def fake_get_data(url, **_kwargs):
        calls.append(url)
        return responses.pop(0) if responses else payload()

    def fake_get_bytes(url, **_kwargs):
        calls.append(url)
        return responses.pop(0) if responses else zipped(payload())

    monkeypatch.setattr(_client, "get_data", fake_get_data)
    monkeypatch.setattr(_client, "get_bytes", fake_get_bytes)
    return calls, responses


# -- export -----------------------------------------------------------------


def test_export_builds_the_documented_query(recorder):
    calls, _ = recorder
    baltic.Client().export("imbalance_prices", start="2024-01-01", end="2024-01-02")

    assert len(calls) == 1
    assert calls[0].startswith(
        "https://api-baltic.transparency-dashboard.eu/api/v1/export?"
    )
    assert params(calls[0]) == {
        "id": "imbalance_prices",
        "start_date": "2024-01-01T00:00",
        "end_date": "2024-01-02T00:00",
        "output_time_zone": "UTC",
        "output_format": "json",
    }


def test_export_returns_a_parsed_export(recorder):
    export = baltic.Client().export(
        "imbalance_prices", start="2024-01-01", end="2024-01-02"
    )
    assert export.unit == "EUR/MWh"
    assert export.rows()[0]["Estonia / Final"] == 118.03


def test_timezone_defaults_can_be_set_on_the_client_and_overridden(recorder):
    calls, _ = recorder
    client = baltic.Client(tz="EET")
    client.export("imbalance_prices", start="2024-01-01", end="2024-01-02")
    client.export("imbalance_prices", start="2024-01-01", end="2024-01-02", tz="CET")

    assert params(calls[0])["output_time_zone"] == "EET"
    assert params(calls[1])["output_time_zone"] == "CET"


def test_unknown_report_is_rejected_before_any_request(recorder):
    calls, _ = recorder
    with pytest.raises(ValueError, match="unknown report"):
        baltic.Client().export("nope", start="2024-01-01", end="2024-01-02")
    assert calls == []


def test_unknown_timezone_is_rejected_before_any_request(recorder):
    calls, _ = recorder
    with pytest.raises(ValueError, match="tz must be one of"):
        baltic.Client().export(
            "imbalance_prices",
            start="2024-01-01",
            end="2024-01-02",
            tz="Europe/Riga",  # ty: ignore[invalid-argument-type]
        )
    assert calls == []


def test_inverted_range_is_rejected(recorder):
    with pytest.raises(ValueError, match="later than start"):
        baltic.Client().export("imbalance_prices", start="2024-01-02", end="2024-01-01")


# -- windowing --------------------------------------------------------------


def test_long_range_is_split_into_windows(recorder):
    calls, responses = recorder
    responses.extend([payload(hour=0), payload(hour=1)])
    client = baltic.Client(max_window=timedelta(days=30))
    export = client.export("imbalance_prices", start="2024-01-01", end="2024-03-01")

    assert len(calls) == 2
    assert params(calls[0])["start_date"] == "2024-01-01T00:00"
    # end is exclusive, so window N ends where window N+1 starts
    assert params(calls[0])["end_date"] == params(calls[1])["start_date"]
    assert params(calls[1])["end_date"] == "2024-03-01T00:00"
    assert len(export) == 4


def test_windowing_can_be_disabled(recorder):
    calls, _ = recorder
    baltic.Client(max_window=None).export(
        "imbalance_prices", start="2000-01-01", end="2024-01-01"
    )
    assert len(calls) == 1


def test_minute_resolution_reports_use_a_shorter_window(recorder):
    calls, responses = recorder
    responses.extend([payload(hour=h) for h in range(5)])
    client = baltic.Client()
    client.export("current_balancing_state_v2", start="2024-01-01", end="2025-01-01")

    assert len(calls) == 4  # 366 days at 92 days per window
    assert params(calls[0])["end_date"] == "2024-04-02T00:00"


# -- export_many ------------------------------------------------------------


def test_export_many_sends_one_comma_separated_id_parameter(recorder):
    calls, _ = recorder
    baltic.Client().export_many(
        ["imbalance_prices", "neutrality"], start="2024-01-01", end="2024-01-02"
    )

    assert "/api/v1/export-multiple?" in calls[0]
    assert params(calls[0])["id"] == "imbalance_prices,neutrality"


def test_export_many_unpacks_the_archive(recorder):
    _, responses = recorder
    responses.append(zipped(payload("imbalance_prices"), payload("neutrality")))
    exports = baltic.Client().export_many(
        ["imbalance_prices", "neutrality"], start="2024-01-01", end="2024-01-02"
    )

    assert list(exports) == ["imbalance_prices", "neutrality"]
    assert len(exports["neutrality"]) == 2


def test_export_many_concatenates_each_report_across_windows(recorder):
    _, responses = recorder
    responses.extend(
        [
            zipped(payload("imbalance_prices", hour=0), payload("neutrality", hour=0)),
            zipped(payload("imbalance_prices", hour=1), payload("neutrality", hour=1)),
        ]
    )
    client = baltic.Client(max_window=timedelta(days=30))
    exports = client.export_many(
        ["imbalance_prices", "neutrality"], start="2024-01-01", end="2024-03-01"
    )

    assert len(exports["imbalance_prices"]) == 4
    assert len(exports["neutrality"]) == 4


def test_export_many_accepts_a_plain_json_body(recorder):
    _, responses = recorder
    responses.append(json.dumps({"data": payload()}).encode())
    exports = baltic.Client().export_many(
        ["imbalance_prices"], start="2024-01-01", end="2024-01-02"
    )
    assert list(exports) == ["imbalance_prices"]


def test_export_many_reports_a_corrupt_archive(recorder):
    _, responses = recorder
    responses.append(b"PKnot-an-archive")
    with pytest.raises(baltic.BalticError, match="could not read the archive"):
        baltic.Client().export_many(
            ["imbalance_prices"], start="2024-01-01", end="2024-01-02"
        )


def test_too_many_reports_are_rejected_before_any_request(recorder):
    calls, _ = recorder
    with pytest.raises(ValueError, match="at most 4 reports"):
        baltic.Client().export_many(
            list(baltic.REPORT_IDS[:5]), start="2024-01-01", end="2024-01-02"
        )
    assert calls == []


# -- downloads --------------------------------------------------------------


def test_download_returns_the_body_untouched(recorder):
    calls, responses = recorder
    responses.append(b"start;end;value\n")
    body = baltic.Client().download(
        "imbalance_prices", start="2024-01-01", end="2024-01-02", output_format="csv"
    )

    assert body == b"start;end;value\n"
    assert params(calls[0])["output_format"] == "csv"


def test_download_is_never_windowed(recorder):
    calls, _ = recorder
    baltic.Client(max_window=timedelta(days=30)).download(
        "imbalance_prices", start="2020-01-01", end="2024-01-01"
    )
    assert len(calls) == 1
    assert params(calls[0])["end_date"] == "2024-01-01T00:00"


def test_download_many_returns_the_archive(recorder):
    calls, responses = recorder
    responses.append(b"PK\x03\x04")
    body = baltic.Client().download_many(
        ["imbalance_prices", "neutrality"],
        start="2024-01-01",
        end="2024-01-02",
        output_format="xlsx",
    )

    assert body == b"PK\x03\x04"
    assert params(calls[0])["output_format"] == "xlsx"


def test_unknown_output_format_is_rejected(recorder):
    with pytest.raises(ValueError, match="output_format must be one of"):
        baltic.Client().download(
            "imbalance_prices",
            start="2024-01-01",
            end="2024-01-02",
            output_format="parquet",  # ty: ignore[invalid-argument-type]
        )


# -- configuration ----------------------------------------------------------


def test_base_url_scheme_is_validated():
    with pytest.raises(ValueError, match="http or https"):
        baltic.Client(base_url="file:///etc").export(
            "imbalance_prices", start="2024-01-01", end="2024-01-02"
        )


def test_client_is_a_context_manager(recorder):
    with baltic.Client() as client:
        assert client.export("imbalance_prices", start="2024-01-01", end="2024-01-02")


def test_module_level_helpers_share_a_default_client():
    assert baltic.export.__self__ is baltic.download.__self__
    assert baltic.export.__self__.base_url == baltic.DEFAULT_BASE_URL
