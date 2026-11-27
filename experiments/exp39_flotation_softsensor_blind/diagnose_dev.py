"""Development-only analyses for the exp39 diagnosis (issue #154, part 2).

Works on the hourly development arrays only; the sealed span of the frozen protocol is never
kept: `development_hourly` cuts at `exp39.cut_hour()` and asserts that nothing later survives.
Usage: python diagnose_dev.py <MiningProcess_Flotation_Plant_Database.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

GROUPS = {
    "reagents": ("Starch Flow", "Amina Flow"),
    "pulp": ("Ore Pulp Flow", "Ore Pulp pH", "Ore Pulp Density"),
    "air": tuple(f"Flotation Column 0{i} Air Flow" for i in range(1, 8)),
    "levels": tuple(f"Flotation Column 0{i} Level" for i in range(1, 8)),
}
MAX_ACF_LAG = 24
MAX_XCORR_LAG = 6


def assert_development_only(n_hours: int, cut: int) -> None:
    """Refuse any array that reaches into the sealed span (hours >= cut)."""
    if n_hours > cut:
        raise ValueError(f"{n_hours} hours loaded but the sealed span starts at hour {cut}")


def development_hourly(path: Path) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Hourly tag means and target, truncated to the development span (sealed rows dropped)."""
    import exp39  # lazy: needs pyarrow and the softsensor package

    if exp39.sha256_of(path) != exp39.SHA256:
        raise ValueError("sha256 mismatch")
    hourly = exp39.to_hourly(path)
    cut = exp39.cut_hour()
    x = {k: v[:cut].copy() for k, v in hourly.x.items()}
    y = hourly.y[:cut].copy()
    del hourly
    assert_development_only(len(y), cut)
    return x, y


def pair_stats(y: np.ndarray, lag: int) -> tuple[float, float, int]:
    """Correlation of y[h-lag], y[h] and the mean squared difference over present pairs."""
    a, b = y[: len(y) - lag], y[lag:]
    ok = ~(np.isnan(a) | np.isnan(b))
    if ok.sum() < 3:
        raise ValueError("too few present pairs")
    rho = float(np.corrcoef(a[ok], b[ok])[0, 1])
    return rho, float(np.mean((b[ok] - a[ok]) ** 2)), int(ok.sum())


def acf_table(y: np.ndarray, kmax: int = MAX_ACF_LAG) -> list[dict[str, float]]:
    """Autocorrelation and the persistence MSE identity for lags 1..kmax.

    Identity for equal means and variances s2: E[(y_h - y_{h-k})^2] = 2 s2 (1 - rho_k).
    Here s2 is the variance of the pooled present values; `ratio` = measured / identity.
    """
    s2 = float(np.nanvar(y))
    rows = []
    for k in range(1, kmax + 1):
        rho, mse, n = pair_stats(y, k)
        rows.append({"lag": k, "rho": rho, "mse": mse, "identity": 2 * s2 * (1 - rho),
                     "ratio": mse / (2 * s2 * (1 - rho)), "n": n})
    return rows


def lag_xcorr(x: np.ndarray, y: np.ndarray, kmax: int = MAX_XCORR_LAG,
              difference: bool = False) -> list[float]:
    """corr(x[h-k], y[h]) for k = 0..kmax; with `difference` both are first-differenced."""
    xs, ys = (np.diff(x), np.diff(y)) if difference else (x, y)
    out = []
    for k in range(kmax + 1):
        a, b = xs[: len(xs) - k], ys[k:]
        ok = ~(np.isnan(a) | np.isnan(b))
        out.append(float(np.corrcoef(a[ok], b[ok])[0, 1]) if ok.sum() > 2 else float("nan"))
    return out


def known_lab(y: np.ndarray, delay_h: int) -> np.ndarray:
    """Newest lab present at hour <= h - delay (carried forward), as in exp39.last_known."""
    out = np.full(len(y), np.nan)
    carried = np.nan
    for h in range(len(y)):
        if h - delay_h >= 0 and not np.isnan(y[h - delay_h]):
            carried = y[h - delay_h]
        out[h] = carried
    return out


def common_rows(*arrays: np.ndarray) -> np.ndarray:
    """Boolean mask of hours where every array is finite."""
    return np.logical_and.reduce([~np.isnan(a) for a in arrays])


def rmse_on(pred: np.ndarray, y: np.ndarray, mask: np.ndarray) -> float:
    """RMSE of pred against y over the mask (silica percentage points)."""
    return float(np.sqrt(np.mean((pred[mask] - y[mask]) ** 2)))


def month_keys(first_label: np.datetime64, n_hours: int) -> np.ndarray:
    """Calendar month string 'YYYY-MM' of every hour label."""
    stamps = first_label + np.arange(n_hours) * np.timedelta64(1, "h")
    return stamps.astype("datetime64[M]").astype(str)


def monthly_bias(resid: np.ndarray, months: np.ndarray) -> list[tuple[str, float, float, int]]:
    """Per month: mean residual (pred - lab), residual RMSE and count over finite residuals."""
    out = []
    for m in sorted(set(months)):
        r = resid[(months == m) & ~np.isnan(resid)]
        if len(r):
            out.append((str(m), float(r.mean()), float(np.sqrt(np.mean(r**2))), len(r)))
    return out


def fit_predict(x: dict[str, np.ndarray], y: np.ndarray, tags: tuple[str, ...], split: int):
    """PLS1 with lag 0 on `tags`, fitted on hours < split; returns (model, prediction)."""
    import exp39
    from crosscut_softsensor.config import SoftSensorConfig

    cfg = SoftSensorConfig(id="exp39d", target_tag=exp39.TARGET, input_tags=tags, lags_s=(0.0,),
                           sample_period_s=exp39.HOUR_S, max_components=8, cv_blocks=5)
    xm = np.column_stack([x[t] for t in tags])
    model = exp39.fit_on(xm, y, cfg, slice(0, split))
    return model, exp39.predict_rows(model, xm)


def ablation(x, y, split: int, mask: np.ndarray) -> dict[str, tuple[float, int]]:
    """Validation RMSE (rows `mask`, hours >= split) dropping or keeping one tag group."""
    from exp39 import INPUTS

    def score(tags):
        _, pred = fit_predict(x, y, tags, split)
        return rmse_on(pred, y, mask)

    out = {"all": (score(INPUTS), len(INPUTS))}
    for name, tags in GROUPS.items():
        rest = tuple(t for t in INPUTS if t not in tags)
        out[f"drop {name}"] = (score(rest), len(rest))
        out[f"only {name}"] = (score(tags), len(tags))
    return out


def baselines(x, y, split: int) -> dict[str, float]:
    """Development validation RMSE of persistence, mean and frozen PLS on identical rows."""
    import exp39

    cut = len(y)
    model, pred = fit_predict(x, y, exp39.INPUTS, split)
    m0, m1 = known_lab(y, exp39.REPORT_DELAY_H), known_lab(y, 1)
    m3 = exp39.corrected(pred, y, model, split)
    mean = np.full(cut, float(np.nanmean(y[:split])))
    mask = (np.arange(cut) >= split) & common_rows(y, pred, m0, m1, m3)
    out = {"rows": float(mask.sum()), "components": float(model.n_components)}
    for name, p in {"M0 persistence (h-2)": m0, "M0 persistence (h-1)": m1, "MM mean": mean,
                    "M2 PLS": pred, "M3 PLS + EWMA bias": m3}.items():
        out[name] = rmse_on(p, y, mask)
    return out


def report(path: Path) -> str:
    """Run every analysis on development data and return a text block."""
    import exp39

    x, y = development_hourly(path)
    split = int(len(y) * (1 - exp39.VALIDATION_SHARE))
    lines = ["## acf", "lag, rho, mse, identity, ratio, n"]
    for r in acf_table(y):
        lines.append(f"{r['lag']}, {r['rho']:.3f}, {r['mse']:.3f}, {r['identity']:.3f}, "
                     f"{r['ratio']:.3f}, {r['n']}")
    lines += ["## baselines", str(baselines(x, y, split)), "## lag xcorr level | difference"]
    for tag in exp39.INPUTS:
        lines.append(f"{tag}: " + " ".join(f"{v:+.2f}" for v in lag_xcorr(x[tag], y)) + " | "
                     + " ".join(f"{v:+.2f}" for v in lag_xcorr(x[tag], y, difference=True)))
    _, pred = fit_predict(x, y, exp39.INPUTS, split)
    mask = (np.arange(len(y)) >= split) & common_rows(y, pred, *x.values())
    lines += ["## ablation", str(ablation(x, y, split, mask)), "## monthly bias"]
    months = month_keys(exp39.FIRST_LABEL, len(y))
    lines += [str(r) for r in monthly_bias(pred - y, months)]
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(Path(sys.argv[1])))
