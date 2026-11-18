"""exp39: blind soft-sensor test on the public flotation data (protocol frozen in README.md).

`develop` mode uses only the development range, picks the lag set and writes frozen_config.json.
`sealed` mode fits on development only, scores the sealed span once and prints aggregate numbers.
Usage: python exp39.py develop|sealed <MiningProcess_Flotation_Plant_Database.csv>
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp04_public_flotation"))

from crosscut_softsensor.bias import BiasTracker  # noqa: E402
from crosscut_softsensor.config import SoftSensorConfig  # noqa: E402
from crosscut_softsensor.features import build_lagged  # noqa: E402
from crosscut_softsensor.pls import PlsModel, fit_pls  # noqa: E402
from flotation_public import LAB_COLUMNS, load_flotation_csv  # noqa: E402

SHA256 = "ae0231a0bd2e14aac39cf978d81db6c71907a42aade19327816692c4e30cb956"
FIRST_LABEL = np.datetime64("2017-03-10T01:00:00")
SEALED_START = np.datetime64("2017-08-13T00:00:00")
HOUR_S = 3600.0
TARGET = "% Silica Concentrate"
INPUTS = (
    "Starch Flow", "Amina Flow", "Ore Pulp Flow", "Ore Pulp pH", "Ore Pulp Density",
    *(f"Flotation Column 0{i} Air Flow" for i in range(1, 8)),
    *(f"Flotation Column 0{i} Level" for i in range(1, 8)),
)
LAG_CANDIDATES_H = ([0], [0, 1], [0, 1, 2], [0, 1, 2, 3])
VALIDATION_SHARE = 0.2
REPORT_DELAY_H = 2  # newest lab known at the end of hour h is that of hour h-2 (README)
EWMA_WEIGHT = 0.3
FROZEN = HERE / "frozen_config.json"
LIMITS = {"T1": 0.90, "T2": 0.95, "T3": 1.05, "T4": 0.10}


@dataclass(frozen=True)
class Hourly:
    """Hourly grid: process means, stamp-value lab target, hour-present flag."""

    x: dict[str, np.ndarray]
    y: np.ndarray
    present: np.ndarray

    def head(self, n: int) -> Hourly:
        """First n hours, all later hours blanked (same length, so lags stay valid)."""
        keep = np.arange(len(self.y)) < n
        return Hourly({k: np.where(keep, v, np.nan) for k, v in self.x.items()},
                      np.where(keep, self.y, np.nan), self.present)


def sha256_of(path: Path) -> str:
    """Hex sha256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def to_hourly(path: Path) -> Hourly:
    """Hourly means of the process tags and the first row of each hour for the target."""
    data = load_flotation_csv(path)
    hour = np.floor(data.t_s / HOUR_S).astype(int)
    n = int(hour.max()) + 1
    counts = np.bincount(hour, minlength=n)
    present = counts > 0
    x = {}
    for tag in INPUTS:
        mean = np.bincount(hour, weights=data.columns[tag], minlength=n) / np.maximum(counts, 1)
        x[tag] = np.where(present, mean, np.nan)
    first = np.unique(hour, return_index=True)[1]
    y = np.full(n, np.nan)
    y[hour[first]] = data.columns[TARGET][first]
    return Hourly(x, y, present)


def cut_hour() -> int:
    """Index of the first sealed hour."""
    return int((SEALED_START - FIRST_LABEL) / np.timedelta64(1, "h"))


def make_config(lags_h: list[int]) -> SoftSensorConfig:
    """Soft-sensor configuration on the hourly grid."""
    return SoftSensorConfig(
        id="exp39", target_tag=TARGET, input_tags=INPUTS, lags_s=tuple(h * HOUR_S for h in lags_h),
        sample_period_s=HOUR_S, max_components=8, cv_blocks=5,
    )


def features(hourly: Hourly, config: SoftSensorConfig) -> np.ndarray:
    """Lagged feature matrix; row h uses hours <= h only."""
    return build_lagged(hourly.x, config.input_tags, config.lags_s, config.sample_period_s)[0]


def fit_on(x: np.ndarray, y: np.ndarray, config: SoftSensorConfig, rows: slice) -> PlsModel:
    """Fit on the rows of ``rows`` only (labels outside are hidden)."""
    y_fit = np.full_like(y, np.nan)
    y_fit[rows] = y[rows]
    return fit_pls(x, y_fit, config)


def predict_rows(model: PlsModel, x: np.ndarray) -> np.ndarray:
    """Predictions, NaN where any feature is missing."""
    out = np.full(len(x), np.nan)
    ok = ~np.isnan(x).any(axis=1)
    out[ok] = model.predict(x[ok])
    return out


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    """Root mean square error over rows where both exist."""
    ok = ~(np.isnan(a) | np.isnan(b))
    return float(np.sqrt(np.mean((a[ok] - b[ok]) ** 2)))


def develop(hourly: Hourly) -> dict:
    """Choose the lag set on development (fit first 80 %, validate on the last 20 %)."""
    cut = cut_hour()
    dev = hourly.head(cut)
    split = int(cut * (1 - VALIDATION_SHARE))
    scores = {}
    for lags in LAG_CANDIDATES_H:
        config = make_config(lags)
        x = features(dev, config)
        model = fit_on(x, dev.y, config, slice(0, split))
        pred = predict_rows(model, x[split:cut])
        scores[str(lags)] = (rmse(pred, dev.y[split:cut]), model.n_components)
    best = min(scores, key=lambda k: scores[k][0])
    return {"lags_h": json.loads(best), "validation": scores}


def last_known(y: np.ndarray, delay_h: int) -> np.ndarray:
    """Most recent lab value present at hour <= h - delay (carried forward at any age)."""
    out = np.full(len(y), np.nan)
    carried = np.nan
    for h in range(len(y)):
        if h - delay_h >= 0 and not np.isnan(y[h - delay_h]):
            carried = y[h - delay_h]
        out[h] = carried
    return out


def corrected(pred: np.ndarray, y: np.ndarray, model: PlsModel, start: int) -> np.ndarray:
    """M3: prediction plus EWMA bias of the sealed-span labs known at the end of the hour."""
    tracker = BiasTracker(model.cv_sigma, EWMA_WEIGHT)
    out = np.full(len(pred), np.nan)
    for h in range(start, len(pred)):
        k = h - REPORT_DELAY_H
        if k >= start:
            tracker.update(float(k), y[k], pred[k])
        bias = tracker.state.bias_ewma
        out[h] = pred[h] + (0.0 if np.isnan(bias) else bias)
    return out


def metrics(pred: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """RMSE, MAE and R2 against the lab values."""
    err = pred - y
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return {"rmse": float(np.sqrt(np.mean(err**2))), "mae": float(np.mean(np.abs(err))),
            "r2": 1 - float(np.sum(err**2)) / ss_tot}


def leakage_checks(hourly: Hourly, config: SoftSensorConfig, model: PlsModel, cut: int) -> dict:
    """T5: no future lags, no lab input, refit with the sealed span blanked is identical."""
    blank = hourly.head(cut)
    refit = fit_on(features(blank, config), blank.y, config, slice(0, cut))
    return {
        "lags_not_future": all(lag >= 0 for lag in config.lags_s),
        "labs_not_inputs": not (set(INPUTS) & set(LAB_COLUMNS)),
        "refit_identical_without_sealed": refit.sha256() == model.sha256(),
    }


def sealed(hourly: Hourly) -> str:
    """Fit on development once, score the sealed span once, return markdown."""
    cut = cut_hour()
    config = make_config(json.loads(FROZEN.read_text())["lags_h"])
    x = features(hourly, config)
    model = fit_on(x, hourly.y, config, slice(0, cut))
    pred = predict_rows(model, x)
    m0 = last_known(hourly.y, REPORT_DELAY_H)
    methods = {
        "M0": m0, "M0_delay1": last_known(hourly.y, 1),
        "MM": np.full(len(pred), float(np.nanmean(hourly.y[:cut]))),
        "M2": pred, "M3": corrected(pred, hourly.y, model, cut),
    }
    span = np.arange(len(pred)) >= cut
    has_lab = span & ~np.isnan(hourly.y)
    scored = has_lab & ~np.isnan(pred) & ~np.isnan(m0)
    s = {n: metrics(v[scored], hourly.y[scored]) for n, v in methods.items()}
    counts = (int(scored.sum()), int(has_lab.sum()), int((span & ~hourly.present).sum()))
    return report(s, counts, model, config, leakage_checks(hourly, config, model, cut))


def report(s: dict, counts: tuple[int, int, int], model: PlsModel,
           config: SoftSensorConfig, leak: dict[str, bool]) -> str:
    """Markdown of the aggregate numbers and the five targets."""
    n_scored, n_lab, n_absent = counts
    lines = ["| method | RMSE | MAE | R2 |", "|---|---|---|---|"]
    lines += [f"| {k} | {v['rmse']:.4f} | {v['mae']:.4f} | {v['r2']:.3f} |" for k, v in s.items()]
    ratios = {"T1": s["M2"]["rmse"] / s["M0"]["rmse"], "T2": s["M2"]["rmse"] / s["MM"]["rmse"],
              "T3": s["M3"]["rmse"] / s["M2"]["rmse"], "T4": 1 - n_scored / n_lab}
    fast = s["M2"]["rmse"] / s["M0_delay1"]["rmse"]
    lines += [
        "",
        f"scored hours {n_scored}, sealed hours with lab {n_lab}, absent hours in span {n_absent}",
        f"lags_h {[x / HOUR_S for x in config.lags_s]}, components {model.n_components}, "
        f"cv_sigma {model.cv_sigma:.4f}, M2/M0_delay1 {fast:.3f}",
    ]
    lines += [f"{k} value {v:.3f} limit {LIMITS[k]} {'PASS' if v <= LIMITS[k] else 'MISS'}"
              for k, v in ratios.items()]
    lines.append(f"T5 {leak} {'PASS' if all(leak.values()) else 'MISS'}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """Entry point."""
    if len(argv) != 3 or argv[1] not in ("develop", "sealed"):
        print(__doc__)
        return 2
    path = Path(argv[2])
    if sha256_of(path) != SHA256:
        print("sha256 mismatch")
        return 1
    hourly = to_hourly(path)
    if argv[1] == "develop":
        result = develop(hourly)
        FROZEN.write_text(json.dumps({"lags_h": result["lags_h"]}) + "\n")
        print(json.dumps(result, indent=1))
    else:
        print(sealed(hourly))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
