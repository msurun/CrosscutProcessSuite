"""Verify the frozen MetroPT protocol using small synthetic records.

No test reads the external dataset or evaluates the real scoring period.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from experiments.exp42_metropt3_equipment.exp42 import (
    CONFIG,
    MEASUREMENTS,
    STATE_COLUMNS,
    ReplayConnector,
    count_false_alarms,
    coverage,
    equipment_document,
    load_metropt3,
    match_events,
    normal_rows,
    run,
    summarize,
    train_model,
)


@pytest.fixture
def frame() -> pd.DataFrame:
    """Return three synthetic CSV rows with all named signals and an ignored index."""
    signals = {name: [1.0, 2.0, 3.0] for name in MEASUREMENTS + STATE_COLUMNS}
    return pd.DataFrame({"timestamp": pd.date_range("2020-02-01", periods=3, freq="10s"),
                         "Unnamed: 0": [0, 10, 20], **signals})


def test_loader_returns_aligned_times_matrix_and_states(tmp_path: Path, frame: pd.DataFrame):
    """CSV metadata must not enter the model matrix."""
    path = tmp_path / "synthetic.csv"
    frame.to_csv(path, index=False)
    times, matrix, states = load_metropt3(path)
    assert times[1] - times[0] == pd.Timedelta(seconds=10)
    assert matrix.shape == (3, 7)
    assert states.columns.tolist() == STATE_COLUMNS
    np.testing.assert_array_equal(matrix[:, 0], [1, 2, 3])


@pytest.mark.parametrize("problem", ["missing", "duplicate", "unsorted", "invalid", "text"])
def test_loader_rejects_invalid_input(tmp_path: Path, frame: pd.DataFrame, problem: str):
    """Each malformed input fails explicitly rather than being repaired."""
    mutations = {
        "missing": lambda value: value.drop(columns="Motor_current"),
        "duplicate": lambda value: value.assign(timestamp=value.timestamp.iloc[0]),
        "unsorted": lambda value: value.iloc[::-1],
        "invalid": lambda value: value.assign(timestamp="bad timestamp"),
        "text": lambda value: value.assign(Motor_current="not numeric"),
    }
    path = tmp_path / "invalid.csv"
    mutations[problem](frame).to_csv(path, index=False)
    with pytest.raises(ValueError):
        load_metropt3(path)


def test_loader_preserves_missing_rows(tmp_path: Path, frame: pd.DataFrame):
    """Unavailable measurements must remain in the coverage denominator."""
    frame.loc[1, "Motor_current"] = np.nan
    path = tmp_path / "missing.csv"
    frame.to_csv(path, index=False)
    times, matrix, _ = load_metropt3(path)
    assert len(times) == 3
    assert np.isnan(matrix[1, 0])


@pytest.mark.parametrize("opening", ["2020-04-17 22:00", "2020-04-18 23:59"])
def test_event_matching_includes_both_window_boundaries(opening: str):
    """The two-hour allowance and source end time are inclusive."""
    assert match_events(pd.DatetimeIndex([opening])) == [True, False, False, False]


def test_event_matching_does_not_credit_an_earlier_open_alarm():
    """An opening before the warning interval remains a miss."""
    assert match_events(pd.DatetimeIndex(["2020-04-17 21:59:59"])) == [False] * 4


def test_repeated_alarms_credit_a_failure_only_once():
    """Recall counts failures rather than alarm count."""
    assert match_events(pd.DatetimeIndex(["2020-04-18", "2020-04-18 01:00"])) == [
        True, False, False, False]


def test_false_alarm_count_deduplicates_revisions_and_excludes_warning_windows():
    """Only distinct unmatched openings count toward false-alarm rate."""
    openings = pd.DatetimeIndex(["2020-04-17 21:59:59", "2020-04-17 21:59:59",
                                 "2020-04-17 22:00", "2020-04-18 23:59",
                                 "2020-04-19"])
    assert count_false_alarms(openings) == 2


def test_no_openings_detects_no_events_and_has_no_false_alarms():
    """An empty alarm log is valid evaluation input."""
    openings = pd.DatetimeIndex([])
    assert count_false_alarms(openings) == 0
    assert match_events(openings) == [False] * 4


def test_coverage_includes_every_unscored_row():
    """Warmup and unavailable rows cannot disappear from the denominator."""
    assert coverage(np.array([True, True, False, False])) == 0.5


@pytest.mark.parametrize("mask", [np.array([], dtype=bool), np.array([1]), np.ones((2, 2))])
def test_coverage_rejects_invalid_masks(mask: np.ndarray):
    """Undefined coverage and nonboolean masks must fail loudly."""
    with pytest.raises(ValueError, match="boolean"):
        coverage(mask)


def test_normal_exposure_excludes_warning_windows():
    """Even early-warning rows are removed from normal time exposure."""
    times = pd.DatetimeIndex(["2020-04-17 21:59:50", "2020-04-17 22:00", "2020-04-19"])
    np.testing.assert_array_equal(normal_rows(times), [True, False, True])


def test_summary_uses_observed_normal_time_and_all_rows():
    """A long archive gap must not inflate normal exposure."""
    times = pd.DatetimeIndex(["2020-03-01", "2020-08-01"])
    metrics = summarize(times, pd.DatetimeIndex(["2020-03-01"]), np.array([True, False]))
    assert metrics["normal_days"] == 20 / 86400
    assert metrics["false_alarms_per_normal_day"] == 4320
    assert metrics["coverage"] == 0.5


def test_summary_rejects_zero_normal_exposure():
    """An undefined false-alarm rate must not pass the target."""
    with pytest.raises(ValueError, match="normal scoring exposure"):
        summarize(pd.DatetimeIndex(["2020-04-18"]), pd.DatetimeIndex([]), np.array([True]))


def test_connector_only_exposes_finite_good_values():
    """Unavailable channels must reach runtime as missing GOOD evidence."""
    connector = ReplayConnector()
    connector.row = {"finite": 1.0, "missing": np.nan}
    assert list(connector.read_live(["finite", "missing"])) == ["finite"]
    assert connector.capabilities() == set()


def test_training_requires_february_rows():
    """Scoring rows alone cannot become training data."""
    with pytest.raises(ValueError, match="February"):
        train_model(pd.DatetimeIndex(["2020-03-01"]), {}, equipment_document())


def test_full_runner_writes_results_on_synthetic_data(tmp_path: Path):
    """Public learn/scan integration works without reading real scoring data."""
    generator = np.random.default_rng(160)
    times = pd.date_range("2020-02-01", periods=350, freq="10s").append(
        pd.date_range("2020-03-01", periods=10, freq="10s"))
    # Shape n x 15, independent synthetic channels; no process claim is implied.
    matrix = generator.normal(size=(len(times), len(MEASUREMENTS + STATE_COLUMNS)))
    frame = pd.DataFrame(matrix, columns=MEASUREMENTS + STATE_COLUMNS)
    frame.insert(0, "timestamp", times)
    path, output = tmp_path / "synthetic.csv", tmp_path / "results.md"
    frame.to_csv(path, index=False)
    run(path, output)
    assert '"scoring_rows": 10' in output.read_text()
    assert '"coverage": 0.9' in output.read_text()
    assert CONFIG["learning"]["exclusions"] == []
