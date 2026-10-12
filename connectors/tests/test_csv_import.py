"""Round-trip tests: render clean simulator data as messy CSV exports, import, compare."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from crosscut_connectors.csv_import import import_csv
from crosscut_connectors.messy import STYLES, render_messy_csv
from crosscut_sim.core import BAD, GOOD, Scenario
from crosscut_sim.dataset import read_dataset, to_wide
from crosscut_sim.plants.wood_berry import WoodBerryPlant

LOCAL_TZ = "Europe/Warsaw"
LOCAL_STYLES = {"semicolon_comma", "tab_local"}
TAGS = ["sim.wb.top_comp", "sim.wb.bottom_comp", "sim.wb.steam"]
START_NS = 1_767_225_600_000_000_000  # 2026-01-01T00:00:00Z
GAP = slice(100, 110)


@pytest.fixture(scope="module")
def truth() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Return reference timestamps and per-tag signals from a 600-step wood berry run."""
    plant = WoodBerryPlant()
    plant.reset(4, Scenario(duration_s=600.0))
    rows = []
    for _ in range(600):
        rows.append([plant.read(tag)[0] for tag in TAGS])
        plant.step()
    values = np.array(rows)
    values[GAP, 0] = np.nan
    ts_ns = START_NS + np.arange(600, dtype=np.int64) * 1_000_000_000
    return ts_ns, {tag: values[:, j] for j, tag in enumerate(TAGS)}


def imported(
    style: str, truth: tuple[np.ndarray, dict[str, np.ndarray]], tmp_path: Path
) -> tuple[np.ndarray, dict[str, np.ndarray], object, Path]:
    """Round-trip a truth table through CSV export and import; return the reimported parts."""
    ts_ns, columns = truth
    csv_path = tmp_path / "export.csv"
    csv_path.write_bytes(render_messy_csv(ts_ns, columns, style, local_tz=LOCAL_TZ))
    tz = LOCAL_TZ if style in LOCAL_STYLES else "UTC"
    out = tmp_path / "ds"
    report = import_csv(csv_path, out, dataset_id="messy", tz=tz)
    table = read_dataset(out)
    ts, wide = to_wide(table)
    return ts.astype(np.int64), wide, report, out


@pytest.mark.parametrize("style", STYLES)
def test_import_recovers_timestamps_and_values(
    style: str, truth: tuple[np.ndarray, dict[str, np.ndarray]], tmp_path: Path
) -> None:
    ts, wide, _, _ = imported(style, truth, tmp_path)
    assert ts.tolist() == truth[0].tolist()
    for tag, expected in truth[1].items():
        np.testing.assert_allclose(wide[tag], expected, rtol=1e-9, equal_nan=True)


@pytest.mark.parametrize("style", STYLES)
def test_missing_values_get_bad_quality_and_the_rest_good(
    style: str, truth: tuple[np.ndarray, dict[str, np.ndarray]], tmp_path: Path
) -> None:
    _, _, _, out = imported(style, truth, tmp_path)
    table = read_dataset(out)
    values = table["value"].to_numpy()
    quality = table["quality"].to_numpy()
    assert np.all(quality[np.isnan(values)] == BAD)
    assert np.all(quality[~np.isnan(values)] == GOOD)
    assert int(np.isnan(values).sum()) == 10


def test_report_describes_what_was_detected(
    truth: tuple[np.ndarray, dict[str, np.ndarray]], tmp_path: Path
) -> None:
    _, _, report, _ = imported("semicolon_comma", truth, tmp_path)
    assert (report.delimiter, report.decimal) == (";", ",")  # type: ignore[attr-defined]
    assert report.n_rows == 600  # type: ignore[attr-defined]


def test_duplicate_timestamps_are_dropped_and_counted(
    truth: tuple[np.ndarray, dict[str, np.ndarray]], tmp_path: Path
) -> None:
    _, _, report, _ = imported("duplicates_unsorted", truth, tmp_path)
    assert report.n_duplicates_dropped == 5  # type: ignore[attr-defined]
    assert report.was_unsorted is True  # type: ignore[attr-defined]


def test_clean_export_reports_no_problems(
    truth: tuple[np.ndarray, dict[str, np.ndarray]], tmp_path: Path
) -> None:
    _, _, report, _ = imported("plain", truth, tmp_path)
    assert report.n_duplicates_dropped == 0 and report.was_unsorted is False  # type: ignore[attr-defined]


def test_unsafe_header_characters_are_replaced_in_tag_ids(tmp_path: Path) -> None:
    path = tmp_path / "e.csv"
    path.write_text("time,TIC 101/PV\n2026-01-01T00:00:00Z,1.5\n2026-01-01T00:00:01Z,2.5\n")
    out = tmp_path / "ds"
    import_csv(path, out, dataset_id="x")
    _, wide = to_wide(read_dataset(out))
    assert list(wide) == ["TIC_101_PV"]


def test_file_without_a_timestamp_column_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "e.csv"
    path.write_text("a,b\n1,2\n3,4\n")
    with pytest.raises(ValueError, match="timestamp"):
        import_csv(path, tmp_path / "ds", dataset_id="x")


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "e.csv"
    path.write_text("")
    with pytest.raises(ValueError, match="empty"):
        import_csv(path, tmp_path / "ds", dataset_id="x")
