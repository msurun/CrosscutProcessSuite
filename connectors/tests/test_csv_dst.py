"""Local times that occur twice at the DST fall-back must stay two different instants.

Europe/Warsaw sets the clocks back on 2026-10-25 at 03:00 to 02:00, so 02:00-02:59 happens twice.
A file in time order lists the first pass before the second; the importer must not drop either.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from crosscut_connectors.csv_import import import_csv
from crosscut_sim.dataset import read_dataset, to_wide

ZONE = "Europe/Warsaw"
NS_PER_HOUR = 3_600_000_000_000


def _times_of(path: Path, out_dir: Path) -> np.ndarray:
    """Import a CSV and return its UTC time index as int64 nanoseconds."""
    import_csv(path, out_dir, dataset_id="dst", tz=ZONE)
    t_ns, _ = to_wide(read_dataset(out_dir))
    return t_ns.astype("datetime64[ns]").astype(np.int64)


def _write(path: Path, local_times: list[str]) -> Path:
    """Write a two-column semicolon CSV with the given naive local timestamps."""
    rows = [f"2026-10-25 {text};{index}" for index, text in enumerate(local_times)]
    lines = ["time;level", *rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_repeated_hour_is_kept_as_a_second_pass(tmp_path: Path) -> None:
    """Seven rows through the fall-back give seven distinct, increasing instants."""
    times = ["01:30:00", "02:00:00", "02:30:00", "02:00:00", "02:30:00", "03:00:00", "03:30:00"]
    path = _write(tmp_path / "a.csv", times)
    report = import_csv(path, tmp_path / "out", dataset_id="d", tz=ZONE)
    assert report.n_rows == 7
    assert report.n_duplicates_dropped == 0
    assert report.n_dst_repeats_resolved == 2


def test_the_second_pass_is_one_hour_after_the_first(tmp_path: Path) -> None:
    """02:00 appears at 00:00 UTC and again at 01:00 UTC."""
    times = ["02:00:00", "02:30:00", "02:00:00", "02:30:00"]
    instants = _times_of(_write(tmp_path / "a.csv", times), tmp_path / "out")
    assert instants[2] - instants[0] == NS_PER_HOUR
    assert instants[3] - instants[1] == NS_PER_HOUR


def test_a_day_without_a_dst_change_reports_no_repeats(tmp_path: Path) -> None:
    """Ordinary rows are not touched by the fall-back logic."""
    path = tmp_path / "a.csv"
    path.write_text("time;x\n2026-06-01 02:00:00;1\n2026-06-01 02:30:00;2\n", encoding="utf-8")
    report = import_csv(path, tmp_path / "out", dataset_id="d", tz=ZONE)
    assert report.n_dst_repeats_resolved == 0
