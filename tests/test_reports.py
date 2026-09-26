import json
from pathlib import Path

import pytest

import baltic
from baltic._catalog import MAX_REPORTS_PER_REQUEST
from baltic._reports import resolve
from baltic.models import Report

SPEC = Path(__file__).resolve().parents[1] / "spec" / "openapi.json"


def test_export_endpoints_declare_the_same_report_ids():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))

    def report_ids(path):
        parameters = spec["paths"][path]["get"]["parameters"]
        schema = next(
            parameter["schema"] for parameter in parameters if parameter["name"] == "id"
        )
        if "enum" in schema:
            return schema["enum"]
        return schema["items"]["enum"]

    single = report_ids("/api/v1/export")
    multiple = report_ids("/api/v1/export-multiple")

    assert set(single) == set(multiple)
    assert set(baltic.REPORT_IDS) == set(single)


def test_every_report_has_an_id_and_a_title():
    assert len(baltic.REPORT_IDS) == len(set(baltic.REPORT_IDS)) >= 65
    assert all(item.id and item.title for item in baltic.reports())


def test_report_lookup():
    report = baltic.report("imbalance_prices")
    assert report.title == "Imbalance prices"
    assert "PT15M" in report.resolutions
    assert baltic.report(report) is report


def test_unknown_report_suggests_close_matches():
    with pytest.raises(ValueError, match="did you mean imbalance_prices"):
        baltic.report("imbalance_price")


def test_unknown_report_without_close_matches():
    with pytest.raises(ValueError, match="unknown report 'zzz'$"):
        baltic.report("zzz")


def test_search_matches_id_and_title():
    assert baltic.report("imbalance_prices") in baltic.reports("IMBALANCE")
    assert baltic.reports("cross-zonal") == [baltic.report("cross_zonal_capacities")]
    assert baltic.reports("no such thing") == []


def test_filter_by_category():
    reserves = baltic.reports(category="Reserves")
    assert reserves
    assert all("Reserves" in item.categories for item in reserves)


def test_categories_are_known():
    assert "Balancing" in baltic.CATEGORIES
    with pytest.raises(ValueError, match="unknown category"):
        baltic.reports(category="Nope")


def test_resolve_accepts_a_single_report():
    assert resolve("imbalance_prices", multiple=False) == ["imbalance_prices"]
    assert resolve(Report(id="neutrality", title="x"), multiple=False) == ["neutrality"]


def test_resolve_rejects_an_empty_selection():
    with pytest.raises(ValueError, match="at least one report"):
        resolve([], multiple=True)


def test_resolve_enforces_the_api_limit():
    too_many = list(baltic.REPORT_IDS[: MAX_REPORTS_PER_REQUEST + 1])
    with pytest.raises(ValueError, match="at most 4 reports"):
        resolve(too_many, multiple=True)
    assert len(resolve(too_many[:-1], multiple=True)) == MAX_REPORTS_PER_REQUEST
