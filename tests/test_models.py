from datetime import datetime, timezone

import pytest
from conftest import payload

from baltic.models import Column, Export, Interval, Report


def test_export_is_parsed(export_payload):
    export = Export.from_dict(export_payload)

    assert export.id == "imbalance_prices"
    assert export.unit == "EUR/MWh"
    assert export.resolution == "PT15M"
    assert export.local_timezone == "UTC"
    assert export.created == datetime(2026, 8, 30, 16, 4, 42, tzinfo=timezone.utc)
    assert len(export) == 2


def test_intervals_are_aware_datetimes(export_payload):
    interval = Export.from_dict(export_payload).intervals[0]
    assert interval.start == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert interval.end == datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc)
    assert interval.values == (118.03, None)


def test_column_name_joins_groups_and_label():
    column = Column(index=0, label="Min bid", groups=("Baltics", "Upward"))
    assert column.name == "Baltics / Upward / Min bid"


def test_empty_group_levels_are_dropped():
    column = Column.from_dict(
        {"index": 3, "label": "Total", "group_level_0": "", "group_level_1": None}
    )
    assert column.groups == ()
    assert column.name == "Total"


def test_duplicate_column_names_are_disambiguated():
    export = Export(
        id="x",
        title="X",
        columns=(Column(index=0, label="A"), Column(index=1, label="A")),
    )
    assert export.column_names == ("A", "A [1]")


def test_rows_are_wide(export_payload):
    rows = Export.from_dict(export_payload).rows()
    assert rows[0] == {
        "start": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "end": datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc),
        "Estonia / Final": 118.03,
        "Estonia / Preliminary": None,
    }


def test_records_are_long(export_payload):
    records = Export.from_dict(export_payload).records()
    assert len(records) == 4
    assert records[0] == {
        "start": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "end": datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc),
        "column": "Estonia / Final",
        "groups": ("Estonia",),
        "label": "Final",
        "value": 118.03,
    }


def test_concat_appends_intervals_in_order():
    first = Export.from_dict(payload(hour=0))
    second = Export.from_dict(payload(hour=1))
    joined = Export.concat([first, second])

    assert len(joined) == 4
    assert joined.title == first.title
    assert [i.start for i in joined.intervals] == [
        *[i.start for i in first.intervals],
        *[i.start for i in second.intervals],
    ]


def test_concat_rejects_mismatched_columns(export_payload):
    other = payload()
    other["columns"] = other["columns"][:1]
    with pytest.raises(ValueError, match="columns changed"):
        Export.concat([Export.from_dict(export_payload), Export.from_dict(other)])


def test_concat_rejects_nothing_to_join():
    with pytest.raises(ValueError, match="empty list"):
        Export.concat([])


def test_missing_optional_fields_are_tolerated():
    export = Export.from_dict({"id": "x"})
    assert export == Export(id="x", title="")
    assert export.rows() == []
    assert "0 columns" in repr(export)


def test_unparseable_creation_time_is_ignored():
    assert Export.from_dict({"id": "x", "creation_time": "soon"}).created is None


def test_report_str():
    assert str(Report(id="a", title="A")) == "a - A"


def test_interval_without_values():
    interval = Interval.from_dict(
        {"from": "2024-01-01T00:00:00+00:00", "to": "2024-01-01T01:00:00+00:00"}
    )
    assert interval.values == ()
