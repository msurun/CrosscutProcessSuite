"""Tests of the descriptive operating envelope: known optimum per mode, exclusions, determinism."""

import numpy as np
import pytest
from crosscut_anomaly.operating_envelope import INSUFFICIENT, EnvelopeError, operating_envelope


def _data(seed: int = 1) -> tuple[dict, np.ndarray, np.ndarray]:
    """Mode A peaks at x=30, mode B at x=70 (recovery = 90 - 0.01 (x - peak)^2 + noise)."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(0, 100, 4000)
    labels = np.where(np.arange(4000) % 2 == 0, "A", "B").astype(object)
    peak = np.where(labels == "A", 30.0, 70.0)
    y = 90 - 0.01 * (x - peak) ** 2 + rng.normal(0, 0.5, 4000)
    return {"rec": y, "x": x}, labels, np.zeros(4000, bool)


def _best_centres(result: dict, mode: str) -> list[float]:
    """Centre of every flagged best bin of a one-variable result."""
    edges = result["edges"][0]
    return [(edges[c["index"][0]] + edges[c["index"][0] + 1]) / 2
            for c in result["modes"][mode]["cells"] if c["best"]]


def _run(data, labels, stopped, **kwargs) -> dict:
    """Run with the common test options."""
    options = {"outcome": "rec", "variables": ["x"], "sample_period_s": 60.0, "bins": 10,
               "min_count": 20, "tolerance": 0.3}
    return operating_envelope(data, labels, stopped, **{**options, **kwargs})


def test_known_optimum_per_mode_is_recovered() -> None:
    """Each mode's best bins sit around its own peak, not the other's."""
    data, labels, stopped = _data()
    result = _run(data, labels, stopped)
    assert any(abs(c - 30) <= 10 for c in _best_centres(result, "A"))
    assert all(abs(c - 30) <= 20 for c in _best_centres(result, "A"))
    assert all(abs(c - 70) <= 20 for c in _best_centres(result, "B"))


def test_min_direction_flips_the_best_bin() -> None:
    """With direction min the best bins are at the edges of the range, far from the peak."""
    data, labels, stopped = _data()
    result = _run(data, labels, stopped, direction="min")
    assert all(abs(c - 30) > 30 for c in _best_centres(result, "A"))


def test_stopped_samples_are_excluded() -> None:
    """A stopped sample with an extreme outcome changes no quantile and is counted aside."""
    data, labels, stopped = _data()
    stopped[:200] = True
    data["rec"][:200] = 1e6
    result = _run(data, labels, stopped)
    assert result["excluded_stopped"] == 200
    top = max(c["p90"] for m in result["modes"].values() for c in m["cells"] if c["p90"])
    assert top < 100
    assert sum(m["samples"] for m in result["modes"].values()) == 3800


def test_insufficient_data_bins_are_marked() -> None:
    """Empty and thin bins carry the marker, no quantiles and never count as best."""
    data, labels, stopped = _data()
    result = _run(data, labels, stopped, min_count=250)
    cells = [c for m in result["modes"].values() for c in m["cells"]]
    thin = [c for c in cells if c["status"] == INSUFFICIENT]
    assert thin and all(c["p50"] is None and not c["best"] for c in thin)
    assert any(c["status"] == "ok" for c in cells)


def test_two_variables_and_determinism() -> None:
    """A 2-D grid has bins^2 cells per mode and the result repeats exactly."""
    data, labels, stopped = _data()
    data["z"] = data["x"][::-1].copy()
    first = _run(data, labels, stopped, variables=["x", "z"], bins=4)
    assert len(first["modes"]["A"]["cells"]) == 16
    assert first == _run(data, labels, stopped, variables=["x", "z"], bins=4)


def test_coverage_sums_to_one_per_mode() -> None:
    """Counts of the bins partition the mode's samples."""
    data, labels, stopped = _data()
    mode = _run(data, labels, stopped)["modes"]["A"]
    assert sum(c["count"] for c in mode["cells"]) == mode["samples"]
    assert sum(c["coverage"] for c in mode["cells"]) == pytest.approx(1.0)


def test_errors_are_specific() -> None:
    """Unknown tags, bad options and all-stopped data raise EnvelopeError."""
    data, labels, stopped = _data()
    with pytest.raises(EnvelopeError):
        _run(data, labels, stopped, outcome="nope")
    with pytest.raises(EnvelopeError):
        _run(data, labels, stopped, direction="up")
    with pytest.raises(EnvelopeError):
        _run(data, labels, np.ones(4000, bool))
