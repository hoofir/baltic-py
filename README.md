# baltic-py

[![CI](https://github.com/hoofir/baltic-py/actions/workflows/ci.yml/badge.svg)](https://github.com/hoofir/baltic-py/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/baltic-py.svg)](https://pypi.org/project/baltic-py/)
[![Python](https://img.shields.io/pypi/pyversions/baltic-py.svg)](https://pypi.org/project/baltic-py/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A small Python client for the [Baltic Transparency Dashboard](https://baltic.transparency-dashboard.eu/) (BTD) [open API](https://baltic.transparency-dashboard.eu/documentation/api) — the balancing market data published by the Baltic TSOs *AST*, *Elering* and *Litgrid*.

- **No dependencies.** Standard library only (plus `tzdata` on Windows).
- **No setup.** The API is public and unauthenticated — `import baltic` and go.
- **Discoverable.** The 65 report IDs ship with the package, searchable by name
  and category, with typo suggestions.
- **Long ranges just work.** Multi-year queries are split into windows and
  stitched back together for you.
- **Table-shaped data out.** The API's column/value matrix is parsed into
  labelled rows, ready for `pandas`, `polars` or `csv`.

---

## Quickstart

### Install

```bash
pip install baltic-py
```

Requires Python 3.11 or newer.

### Query data

```python
import baltic

# What can I ask for?
baltic.reports("imbalance")
# [Report(id='imbalance_prices', title='Imbalance prices', ...),
#  Report(id='imbalance_volumes_v2', title='Imbalance volumes', ...), ...]

export = baltic.export("imbalance_prices", start="2024-01-01", end="2024-01-02")

export.title  # 'Imbalance prices'
export.unit  # 'EUR/MWh'
export.resolution  # 'PT15M'
len(export)  # 96

export.rows()[0]
# {'start': datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
#  'end': datetime(2024, 1, 1, 0, 15, tzinfo=UTC),
#  'Estonia / Final': 118.03, 'Estonia / Preliminary': None,
#  'Latvia / Final': 118.03, 'Latvia / Preliminary': None,
#  'Lithuania / Final': 118.03, 'Lithuania / Preliminary': None}
```

Into a dataframe:

```python
import pandas as pd

df = pd.DataFrame(export.rows()).set_index("start")
tidy = pd.DataFrame(export.records())  # long format instead
```

---

## Guide

### Finding reports

Every export is identified by a report ID. The catalog ships with the package,
so browsing it costs no network call:

```python
baltic.REPORT_IDS  # all 65 IDs
baltic.CATEGORIES  # ('Activations', 'Balancing', 'Bids', 'Capacities', ...)

baltic.reports(category="Reserves")
baltic.reports("mfrr bid")
baltic.report("imbalance_prices").resolutions  # ('PT15M',)
```

Unknown IDs are rejected before any request is made, with suggestions:

```python
baltic.export("imbalance_price", start="2024-01-01", end="2024-01-02")
# ValueError: unknown report 'imbalance_price', did you mean imbalance_prices
# or imbalance_volumes or balancing_energy_prices?
```

Several reports in one round trip — the API allows up to four and returns them
as a ZIP archive, which is unpacked for you:

```python
exports = baltic.export_many(
    ["imbalance_prices", "imbalance_volumes_v2"],
    start="2024-01-01",
    end="2024-01-02",
)
exports["imbalance_prices"].rows()
```

### Dates and time zones

`start` and `end` accept a string, a `date` or a `datetime`. **`end` is
exclusive**, so `start="2024-01-01", end="2024-02-01"` is exactly January.

The `tz` argument (`"UTC"`, `"EET"` or `"CET"`, default `"UTC"`) is the *export*
time zone. It decides how naive values are read, and how `csv`/`xlsx`
timestamps are rendered. Aware datetimes are converted into it:

```python
from datetime import date, datetime

# 1 January 2024, 00:00 Baltic time
baltic.export("imbalance_prices", start="2024-01-01", end=date(2024, 1, 2), tz="EET")

# aware input is converted to the export time zone for you
baltic.export(
    "imbalance_prices", start=datetime(2024, 1, 1, tzinfo=UTC), end=..., tz="EET"
)
```

Regardless of `tz`, the `start`/`end` of every returned interval is a
timezone-aware UTC instant, which is what the API emits.

### `export()` vs `download()`

- `export()` parses the JSON payload into an [`Export`](#the-export-object).
- `download()` returns the response bytes untouched, for `csv`, `xlsx` or
  `json`, exactly as the dashboard's download button produces them.

```python
from pathlib import Path

Path("prices.xlsx").write_bytes(
    baltic.download(
        "imbalance_prices",
        start="2024-01-01",
        end="2024-02-01",
        output_format="xlsx",
        tz="EET",
    )
)

# several reports in one ZIP
Path("bundle.zip").write_bytes(
    baltic.download_many(["imbalance_prices", "neutrality_component"], ...)
)
```

### Long time ranges

A year of 15-minute data is ~35 000 intervals and ~4 MB, so wide queries are
slow. `export()` and `export_many()` therefore split any range longer than
`max_window` (default 366 days) into consecutive requests and concatenate the
results. Because `end` is exclusive, the windows do not overlap and no interval
is duplicated:

```python
# transparently issued as several requests
export = baltic.export("imbalance_prices", start="2015-01-01", end="2024-01-01")
```

Minute-resolution reports (`current_balancing_state_v2`) are ~500 000 intervals
per year, so they are capped at 92 days per request instead.

`download()` is never split — CSV and XLSX files cannot be concatenated safely.

### The `Export` object

| Attribute | Meaning |
| --- | --- |
| `id`, `title`, `description` | Report identity; `description` is the dashboard's HTML blurb |
| `unit` | Measurement unit, e.g. `'EUR/MWh'` |
| `resolution`, `timezone`, `local_timezone` | `'PT15M'`, `'EET'`, `'Europe/Tallinn'` |
| `created` | When the API built the export |
| `columns` | `tuple[Column, ...]`, each with `index`, `label`, `groups`, `name` |
| `intervals` | `tuple[Interval, ...]`, each with `start`, `end`, `values` |

`values` is positional with respect to `columns`, so two flattening helpers are
provided:

```python
export.rows()  # wide: one dict per interval, one key per column
export.records()  # long: one dict per interval *and* column
```

Column names join the API's group levels with the leaf label, e.g.
`"Baltics / Upward / Min bid"`:

```python
[c.name for c in export.columns]
export.columns[0].groups  # ('Baltics', 'Upward')
```

### Errors

Everything raises a subclass of `baltic.BalticError`:

| Exception | Raised when |
| --- | --- |
| `BalticBadRequest` | HTTP 4xx, or a `200` with `error: true`. Exposes `.status` and `.messages` |
| `BalticServerError` | HTTP 5xx, after retries are exhausted |
| `BalticTransportError` | Network failure or timeout |

```python
try:
    baltic.export("imbalance_prices", start="2024-01-01", end="2024-01-02", tz="UTC")
except baltic.BalticBadRequest as exc:
    print(exc.status)  # 400
    print(exc.messages)  # ['Invalid value for `start_date`: "…"']
```

Invalid arguments (an unknown report, an unknown `tz`, an unparseable date, more
than four reports) raise `ValueError` before any request is made.

### Configuring a client

The module-level helpers use a shared default client. Create your own to change
its behaviour:

```python
from datetime import timedelta

with baltic.Client(
    timeout=300, retries=5, tz="EET", max_window=timedelta(days=90)
) as client:
    export = client.export("mfrr_bid_prices", start="2024-01-01", end="2024-04-01")
```

| Argument | Default | Purpose |
| --- | --- | --- |
| `base_url` | `https://api-baltic.transparency-dashboard.eu` | API root; must be http or https |
| `timeout` | `120.0` | Per-request socket timeout in seconds |
| `retries` | `3` | Extra attempts on transport errors and 5xx |
| `backoff` | `0.5` | Base delay for exponential retry backoff |
| `tz` | `"UTC"` | Default export time zone |
| `max_window` | `366 days` | Longest span per request; `None` disables splitting |

---

## API surface

| API endpoint | Method | Returns |
| --- | --- | --- |
| `GET /api/v1/export` | `export()` | `Export` |
| `GET /api/v1/export` | `download()` | `bytes` (`csv`, `xlsx` or `json`) |
| `GET /api/v1/export-multiple` | `export_many()` | `dict[str, Export]` |
| `GET /api/v1/export-multiple` | `download_many()` | `bytes` (ZIP archive) |
| — | `reports()`, `report()` | Offline report catalog |

Each method is available both on a `Client` instance and at module level
(`baltic.export(...)`).

The API's `json_header_groups` flag is not exposed: it only adds table-header
spans, and the same grouping is already available as `Column.groups`.

---

## Contributing

```bash
make setup     # create the venv and install dev dependencies
make check     # ruff lint, format check, ty type check, deptry
make test      # fast offline tests
make test-live # end-to-end tests against the real API
```

`make test` never touches the network. The live suite is deselected by default
and exercises both endpoints, every output format, the windowing logic and the
report catalog against the real API.

### Keeping up with the API

Only `src/baltic/_catalog.py` is generated; the client is hand-written, because
the API has just two endpoints and its Swagger 2.0 definition describes the
response shape only through an example.

```bash
make spec-check   # fail if the published metadata differs from spec/
make spec         # refresh spec/openapi.json and spec/reports.json
make catalog      # regenerate src/baltic/_catalog.py from them
```

CI runs `make spec-check` weekly, so new or renamed reports show up as a
reviewable diff.

### Notes on the API

Behaviour verified against the live API and worked around in the client:

- Both endpoints answer with a `{"error", "message", "data"}` envelope and can
  report failures with HTTP 200 and `error: true`.
- `export-multiple` needs its report IDs comma-separated in a single `id`
  parameter; repeating `id=` silently keeps only the last one. It answers with a
  ZIP archive, and rejects more than four reports with HTTP 422.
- `start_date` and `end_date` must be `yyyy-MM-ddTHH:mm` with no time zone; they
  are read in `output_time_zone`.
- Interval timestamps are always emitted as UTC instants, whatever
  `output_time_zone` was requested.
- A range that predates the report answers HTTP 500 instead of an empty export;
  a range in the future returns intervals whose values are all `None`.
- Report titles, resolutions and categories are not part of the documented
  spec; they are vendored in `spec/reports.json` from the dashboard's own report
  listing, and only used at code-generation time.

---

## License

MIT — see [LICENSE](LICENSE). This project is not affiliated with AST, Elering,
Litgrid or Baltic Transparency Dashboard.
