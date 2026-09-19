"""Shared fixtures: a trimmed but faithful copy of a real export payload."""

import pytest


def payload(report_id="imbalance_prices", intervals=2, hour=0):
    return {
        "id": report_id,
        "export_id": "N09a-G_btkRcE0",
        "measurement_unit": "EUR/MWh",
        "resolution": "PT15M",
        "precision": 3,
        "default_display": "table",
        "title": "Imbalance prices",
        "description": "<p>The imbalance price.</p>",
        "timezone": "UTC",
        "local_timezone": "UTC",
        "creation_time": "2026-08-30T16:04:42+00:00",
        "column_group_levels": 1,
        "columns": [
            {
                "index": 0,
                "col": 0,
                "label": "Final",
                "group_level_0": "Estonia",
                "res": "PT15M",
            },
            {
                "index": 1,
                "col": 1,
                "label": "Preliminary",
                "group_level_0": "Estonia",
                "res": "PT15M",
            },
        ],
        "timeseries": [
            {
                "from": f"2024-01-01T{hour:02d}:{15 * i:02d}:00+00:00",
                "to": f"2024-01-01T{hour:02d}:{15 * (i + 1):02d}:00+00:00",
                "values": [118.03 + i, None],
            }
            for i in range(intervals)
        ],
    }


@pytest.fixture
def export_payload():
    return payload()
