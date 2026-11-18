"""One site file (non-UTC zone, missing code -777) gives identical datasets from CSV and SQL."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
from crosscut_connectors.csv_import import import_csv
from crosscut_connectors.csv_long import import_csv_long
from crosscut_connectors.import_target import ImportTarget
from crosscut_connectors.site import SiteImportSettings, read_import_settings
from crosscut_connectors.sql_import import import_sql
from crosscut_sim.dataset import read_dataset, to_wide

SITE = {"site": {"timezone": "Europe/Warsaw"}, "import": {"missing_codes": [-777]}}
STAMPS = ["2026-01-01 12:00:00", "2026-01-01 12:01:00", "2026-01-01 12:02:00"]
VALUES = {"A": [1.5, -777.0, 3.5], "B": [2.5, 4.5, -777.0]}


def _settings() -> SiteImportSettings:
    """Settings as every importer must obtain them: from the one site reader."""
    return read_import_settings(SITE)


def _target(out: Path, settings: SiteImportSettings) -> ImportTarget:
    """Target carrying the site zone and settings."""
    return ImportTarget(out, "ds", tz=settings.timezone, settings=settings)


def _long_rows() -> list[tuple[str, str, float]]:
    """(time, tag, value) rows of the shared sample."""
    return [(t, tag, VALUES[tag][i]) for i, t in enumerate(STAMPS) for tag in VALUES]


def _wide_csv(path: Path) -> None:
    """Write the sample as a wide CSV."""
    lines = ["time;A;B"] + [
        f"{t};{VALUES['A'][i]};{VALUES['B'][i]}" for i, t in enumerate(STAMPS)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _long_csv(path: Path) -> None:
    """Write the sample as a long CSV."""
    lines = ["time;tag;value"] + [f"{t};{tag};{v}" for t, tag, v in _long_rows()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sql_db(path: Path) -> None:
    """Write the sample into a sqlite table."""
    with sqlite3.connect(path) as con:
        con.execute("create table h (time text, tag text, value real)")
        con.executemany("insert into h values (?, ?, ?)", _long_rows())


def _read(out: Path) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Wide timestamps and columns of a written dataset."""
    return to_wide(read_dataset(out))


def test_missing_code_and_zone_give_identical_datasets_from_every_importer(tmp_path: Path) -> None:
    """Wide CSV, long CSV and SQL agree on UTC instants and on -777 read as missing."""
    settings = _settings()
    _wide_csv(tmp_path / "w.csv")
    _long_csv(tmp_path / "l.csv")
    _sql_db(tmp_path / "h.db")
    import_csv(tmp_path / "w.csv", tmp_path / "wide", dataset_id="ds", settings=settings)
    import_csv_long(tmp_path / "l.csv", _target(tmp_path / "long", settings))
    import_sql(
        tmp_path / "h.db", "select time, tag, value from h", _target(tmp_path / "sql", settings)
    )
    results = [_read(tmp_path / name) for name in ("wide", "long", "sql")]
    time0, cols0 = results[0]
    assert str(time0[0]).startswith("2026-01-01T11:00")  # 12:00 Warsaw is 11:00 UTC
    assert np.isnan(cols0["A"][1]) and np.isnan(cols0["B"][2])
    for time_ns, columns in results[1:]:
        assert np.array_equal(time_ns, time0)
        for tag, column in columns.items():
            np.testing.assert_array_equal(column, cols0[tag])
