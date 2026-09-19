"""End-to-end tests against the live BTD API.

Deselected by default because they need network access and depend on published
data. Run them with ``make test-live``.
"""

import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest

import baltic
from baltic.models import Export

pytestmark = pytest.mark.live

SPEC = Path(__file__).resolve().parents[1] / "spec" / "openapi.json"

# A settled day, far enough in the past that every report has final values.
START = "2024-06-01"
END = "2024-06-02"


@pytest.fixture(scope="session")
def client():
    return baltic.Client(timeout=180)


def assert_export(export, report_id):
    assert isinstance(export, Export)
    assert export.id == report_id
    assert export.columns, "expected at least one column"
    assert export.intervals, "expected at least one interval"
    assert all(len(i.values) == len(export.columns) for i in export.intervals)


# -- exports ----------------------------------------------------------------


def test_export(client):
    export = client.export("imbalance_prices", start=START, end=END)

    assert_export(export, "imbalance_prices")
    assert export.title == "Imbalance prices"
    assert export.unit == "EUR/MWh"
    assert export.resolution == "PT15M"
    assert export.timezone == "UTC"
    assert len(export) == 96  # 24 h at PT15M


@pytest.mark.parametrize(
    "report_id",
    [
        "imbalance_prices",
        "imbalance_volumes_v2",
        "cross_zonal_capacities",
        "mfrr_bid_prices",
        "neutrality_component",
        "system_services",
    ],
)
def test_every_kind_of_report_parses(client, report_id):
    assert_export(client.export(report_id, start=START, end=END), report_id)


def test_rows_are_labelled(client):
    export = client.export("imbalance_prices", start=START, end=END)
    row = export.rows()[0]

    assert row["start"] == datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert row["end"] - row["start"] == timedelta(minutes=15)
    assert "Estonia / Final" in row
    assert set(row) == {"start", "end", *export.column_names}


def test_records_cover_every_cell(client):
    export = client.export("cross_zonal_capacities", start=START, end=END)
    assert len(export.records()) == len(export.intervals) * len(export.columns)


def test_nested_column_groups(client):
    export = client.export("mfrr_bid_prices", start=START, end=END)
    assert any(len(column.groups) == 2 for column in export.columns)
    assert "Baltics / Upward / Min bid" in export.column_names


def test_export_many(client):
    reports = ["imbalance_prices", "cross_zonal_capacities"]
    exports = client.export_many(reports, start=START, end=END)

    assert list(exports) == reports
    for report_id in reports:
        assert_export(exports[report_id], report_id)


def test_export_many_with_a_single_report(client):
    exports = client.export_many(["imbalance_prices"], start=START, end=END)
    assert_export(exports["imbalance_prices"], "imbalance_prices")


def test_export_many_matches_export(client):
    single = client.export("imbalance_prices", start=START, end=END)
    many = client.export_many(["imbalance_prices"], start=START, end=END)
    assert many["imbalance_prices"].rows() == single.rows()


# -- time zones and dates ---------------------------------------------------


def test_timezone_shifts_the_requested_range(client):
    utc = client.export("imbalance_prices", start=START, end=END, tz="UTC")
    eet = client.export("imbalance_prices", start=START, end=END, tz="EET")

    assert utc.intervals[0].start == datetime(2024, 6, 1, tzinfo=timezone.utc)
    # June: EET is UTC+3, so the local day starts three hours earlier in UTC.
    assert eet.intervals[0].start == datetime(2024, 5, 31, 21, tzinfo=timezone.utc)
    assert eet.timezone == "EET"
    assert eet.local_timezone == "Europe/Tallinn"


def test_aware_input_is_converted_into_the_export_timezone(client):
    midnight_utc = datetime(2024, 6, 1, tzinfo=timezone.utc)
    export = client.export("imbalance_prices", start=midnight_utc, end=END, tz="EET")
    assert export.intervals[0].start == midnight_utc


def test_date_and_string_inputs_agree(client):
    as_text = client.export("imbalance_prices", start=START, end=END)
    as_date = client.export(
        "imbalance_prices", start=date(2024, 6, 1), end=date(2024, 6, 2)
    )
    as_datetime = client.export(
        "imbalance_prices", start=datetime(2024, 6, 1), end=datetime(2024, 6, 2)
    )
    assert as_text.rows() == as_date.rows() == as_datetime.rows()


# -- windowing --------------------------------------------------------------


def test_long_range_is_stitched_back_together(client):
    windowed = baltic.Client(timeout=180, max_window=timedelta(days=10))
    whole = client.export("imbalance_prices", start="2024-06-01", end="2024-07-01")
    split = windowed.export("imbalance_prices", start="2024-06-01", end="2024-07-01")

    assert len(split) == len(whole) == 30 * 96
    assert split.rows() == whole.rows()


def test_windows_do_not_overlap(client):
    windowed = baltic.Client(timeout=180, max_window=timedelta(days=1))
    export = windowed.export("imbalance_prices", start="2024-06-01", end="2024-06-04")
    starts = [interval.start for interval in export.intervals]
    assert len(set(starts)) == len(starts) == 3 * 96


# -- downloads --------------------------------------------------------------


@pytest.mark.parametrize(
    ("output_format", "magic"),
    [("csv", b"datetime_from"), ("xlsx", b"PK"), ("json", b'{"error"')],
)
def test_download(client, output_format, magic):
    body = client.download(
        "imbalance_prices", start=START, end=END, output_format=output_format
    )
    assert body.startswith(magic)


def test_download_many_is_an_archive(client):
    body = client.download_many(
        ["imbalance_prices", "cross_zonal_capacities"],
        start=START,
        end=END,
        output_format="csv",
    )
    with zipfile.ZipFile(BytesIO(body)) as archive:
        names = archive.namelist()
    assert len(names) == 2
    assert any(name.startswith("imbalance-prices.") for name in names)


# -- errors -----------------------------------------------------------------


def test_range_without_data_returns_null_values(client):
    export = client.export("imbalance_prices", start="2030-01-01", end="2030-01-02")
    assert export.columns
    assert export.intervals
    assert all(value is None for row in export.intervals for value in row.values)


def test_range_before_the_report_existed_is_a_server_error():
    # The API answers HTTP 500 rather than an empty export for pre-history ranges.
    client = baltic.Client(timeout=60, retries=0)
    with pytest.raises(baltic.BalticServerError) as excinfo:
        client.export("imbalance_prices", start="1999-01-01", end="1999-01-02")
    assert excinfo.value.status == 500


def test_bad_request_reports_the_api_message(client):
    # The client validates report IDs, so go around it to reach the API's own 400.
    url = client.base_url + (
        "/api/v1/export?id=not_a_report&start_date=2024-06-01T00:00&"
        "end_date=2024-06-02T00:00&output_time_zone=UTC&output_format=json"
    )
    with pytest.raises(baltic.BalticBadRequest) as excinfo:
        client._bytes(url)
    assert excinfo.value.status == 400
    assert excinfo.value.messages == ["Invalid export ID."]


def test_too_many_reports_is_enforced_by_the_api(client):
    url = client.base_url + (
        "/api/v1/export-multiple?id=" + ",".join(baltic.REPORT_IDS[:5]) + "&"
        "start_date=2024-06-01T00:00&end_date=2024-06-02T00:00&"
        "output_time_zone=UTC&output_format=json"
    )
    with pytest.raises(baltic.BalticBadRequest) as excinfo:
        client._bytes(url)
    assert excinfo.value.status == 422


def test_unreachable_host_raises_transport_error():
    offline = baltic.Client(base_url="https://baltic.invalid", timeout=5, retries=0)
    with pytest.raises(baltic.BalticTransportError):
        offline.export("imbalance_prices", start=START, end=END)


# -- catalog drift ----------------------------------------------------------


def test_catalog_matches_the_published_spec(client):
    """Detect reports the API added or dropped since the catalog was generated."""
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    declared = next(
        parameter["enum"]
        for parameter in spec["paths"]["/api/v1/export"]["get"]["parameters"]
        if parameter["name"] == "id"
    )
    assert set(baltic.REPORT_IDS) == set(declared)


@pytest.mark.parametrize("report", baltic.reports(), ids=lambda r: r.id)
def test_every_catalog_report_is_exportable(client, report):
    """Slow but exhaustive: every documented report ID is accepted by the API."""
    export = client.export(report, start=START, end=END)
    assert export.id == report.id
    assert export.columns
