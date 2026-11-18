"""Validation report (#40) on synthetic data with a known delay, bias and noise.

Truth: an analyser reads the process 1800 s late with +0.5 offset and small noise; the lab
composite (6 h, stamped at its end) is the process mean with its own small noise.
"""

from pathlib import Path

import numpy as np
import pytest
from crosscut_softsensor import validation_report as report_module
from crosscut_softsensor.validation_report import (
    ReportError,
    compute_report,
    json_text,
    write_report,
)
from crosscut_softsensor.validation_template import TEMPLATE_V1, template_sha256

TEMPLATE_V1_SHA256 = "2e02595ab90108414df1b05ce90d143dfcd1cbbfa8d0d932d107d023bd627322"
DELAY_S = 1800.0
BIAS = 0.5
ANALYSER_NOISE_SD = 0.05
LAB_NOISE_SD = 0.1
COMPOSITE_S = 21600.0
START = np.datetime64("2030-01-01T00:00:00")


def _stamp(seconds: float) -> str:
    """Wall-clock text of START plus seconds."""
    return str(START + np.timedelta64(int(seconds), "s")).replace("T", " ")


def _process(t_s: np.ndarray) -> np.ndarray:
    """A deterministic process signal with hour-scale and day-scale content (arbitrary unit)."""
    rng = np.random.default_rng(40)
    rows = []
    for _ in range(12):
        period, phase = rng.uniform(3, 30) * 3600.0, rng.uniform(0, 6.28)
        rows.append(np.sin(2 * np.pi * t_s / period + phase))
    return 5.0 + np.sum(rows, axis=0)


def _write_dataset(path: Path, missing_code: float | None = None) -> None:
    """A 12-day long-format CSV: analyser every 5 min, lab composites every 6 h, one process tag."""
    rng = np.random.default_rng(41)
    t_s = np.arange(0.0, 12 * 86400.0, 300.0)
    analyser = _process(t_s - DELAY_S) + BIAS + rng.normal(0, ANALYSER_NOISE_SD, len(t_s))
    lines = ["timestamp,tag,value"]
    lines += [f"{_stamp(t)},AN,{v:.6f}" for t, v in zip(t_s, analyser, strict=True)]
    lines += [f"{_stamp(t)},PV,{v:.6f}" for t, v in zip(t_s, _process(t_s), strict=True)]
    fine = np.arange(0.0, 12 * 86400.0, 60.0)
    truth = _process(fine)
    for end in np.arange(COMPOSITE_S, 12 * 86400.0 - 3600.0, COMPOSITE_S):
        mean = truth[(fine > end - COMPOSITE_S) & (fine <= end)].mean()
        lines.append(f"{_stamp(end)},LAB,{mean + rng.normal(0, LAB_NOISE_SD):.6f}")
    if missing_code is not None:
        lines.append(f"{_stamp(100)},LAB,{missing_code}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _config() -> dict:
    """The run config: tag roles, 6 h composite stamped at its end, +-1 h delay search."""
    return {
        "analyser_tag": "AN", "lab_tag": "LAB", "process_tags": ["PV"],
        "composite_window_s": COMPOSITE_S, "stamp": {"meaning": "end"},
        "delay_scan": {"min_delay_s": -3600, "max_delay_s": 3600, "step_s": 300,
                       "bootstrap_samples": 40},
        "thresholds": {"max_abs_bias": 1.0, "min_correlation": 0.99},
    }


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    """The synthetic CSV on disk."""
    path = tmp_path / "data.csv"
    _write_dataset(path)
    return path


def test_report_states_the_known_delay_bias_and_noise(dataset: Path) -> None:
    """The report recovers delay, bias and scatter within tolerance of the planted truth."""
    result = compute_report(dataset, _config())
    assert abs(result["alignment"]["best_delay_s"] - DELAY_S) <= 600
    agreement = result["agreement"]
    assert agreement["bias"] == pytest.approx(BIAS, abs=0.15)
    expected_sd = np.hypot(ANALYSER_NOISE_SD, LAB_NOISE_SD)
    assert agreement["diff_sd"] == pytest.approx(expected_sd, abs=0.1)
    assert agreement["correlation"] > 0.99
    assert abs(result["drift"]["trend_per_day"]) < 0.1
    assert result["thresholds"]["max_abs_bias"]["result"] == "pass"
    assert result["thresholds"]["max_rmse"]["result"] == "not assessed"


def test_same_input_gives_byte_identical_json_and_markdown(dataset: Path, tmp_path: Path) -> None:
    """Two runs write identical bytes."""
    for name in ("a", "b"):
        write_report(compute_report(dataset, _config()), tmp_path / name)
    for name in ("report.json", "report.md"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    stored = (tmp_path / "a" / "report.json").read_text(encoding="utf-8")
    assert json_text(compute_report(dataset, _config())) == stored


def test_report_records_template_version_and_hash(dataset: Path, tmp_path: Path) -> None:
    """Both outputs carry the template version and SHA-256."""
    result = compute_report(dataset, _config())
    assert result["template"] == {"version": "1", "sha256": template_sha256()}
    markdown = report_module.render_markdown(result)
    assert template_sha256() in markdown
    assert "$" not in markdown


def test_template_v1_is_frozen() -> None:
    """Changing the template text needs a new version: V1 is pinned by hash."""
    assert template_sha256(TEMPLATE_V1) == TEMPLATE_V1_SHA256


def test_missing_tag_and_bad_config_are_refused(dataset: Path) -> None:
    """A tag without rows or a config without a required key raises ReportError."""
    with pytest.raises(ReportError):
        compute_report(dataset, {**_config(), "lab_tag": "NOPE"})
    with pytest.raises(ReportError):
        compute_report(dataset, {"analyser_tag": "AN"})
    with pytest.raises(ReportError):
        compute_report(dataset, {**_config(), "thresholds": {"bogus": 1}})
