from datetime import date, datetime, timedelta, timezone

import pytest

from baltic._params import (
    check_output_format,
    check_timezone,
    format_datetime,
    parse_timestamp,
    time_windows,
    to_datetime,
)

EET = timezone(timedelta(hours=2))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2024-01-01", "2024-01-01T00:00"),
        ("2024-01-01T05:30", "2024-01-01T05:30"),
        ("2024-01-01T05:30:00", "2024-01-01T05:30"),
        (date(2024, 3, 9), "2024-03-09T00:00"),
        (datetime(2024, 3, 9, 12, 0), "2024-03-09T12:00"),
    ],
)
def test_naive_input_is_passed_through_unchanged(value, expected):
    assert format_datetime(to_datetime(value, tz="EET", name="start")) == expected


def test_aware_input_is_converted_into_the_export_timezone():
    aware = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
    # June: EET is UTC+3
    assert (
        format_datetime(to_datetime(aware, tz="EET", name="start"))
        == "2024-06-01T03:00"
    )
    assert (
        format_datetime(to_datetime(aware, tz="UTC", name="start"))
        == "2024-06-01T00:00"
    )


def test_to_datetime_rejects_garbage():
    with pytest.raises(ValueError, match="start"):
        to_datetime("not-a-date", tz="UTC", name="start")


def test_to_datetime_rejects_wrong_type():
    with pytest.raises(TypeError, match="end"):
        to_datetime(1704067200, tz="UTC", name="end")  # ty: ignore[invalid-argument-type]


def test_check_timezone():
    assert check_timezone("EET") == "EET"
    with pytest.raises(ValueError, match="tz must be one of"):
        check_timezone("Europe/Riga")


def test_check_output_format():
    assert check_output_format("xlsx") == "xlsx"
    with pytest.raises(ValueError, match="output_format must be one of"):
        check_output_format("parquet")


def test_parse_timestamp_keeps_the_offset():
    parsed = parse_timestamp("2024-01-01T00:00:00+00:00")
    assert parsed == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_time_windows_single_when_within_limit():
    start, end = datetime(2024, 1, 1), datetime(2024, 2, 1)
    assert list(time_windows(start, end, timedelta(days=366))) == [(start, end)]


def test_time_windows_are_contiguous_and_non_overlapping():
    start, end = datetime(2020, 1, 1), datetime(2023, 1, 1)
    windows = list(time_windows(start, end, timedelta(days=366)))

    assert len(windows) == 3
    assert windows[0][0] == start
    assert windows[-1][1] == end
    for previous, current in zip(windows[:-1], windows[1:], strict=True):
        assert previous[1] == current[0]


def test_time_windows_disabled():
    start, end = datetime(2000, 1, 1), datetime(2024, 1, 1)
    assert list(time_windows(start, end, None)) == [(start, end)]


def test_time_windows_rejects_inverted_range():
    moment = datetime(2024, 1, 1)
    with pytest.raises(ValueError, match="later than start"):
        list(time_windows(moment, moment, timedelta(days=1)))
