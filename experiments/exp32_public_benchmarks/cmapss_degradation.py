"""NASA C-MAPSS (Saxena et al. 2008) loader, frozen RUL protocol, metrics and a baseline.

The user downloads the dataset zip and unpacks train_FD00x.txt, test_FD00x.txt and RUL_FD00x.txt
into one local folder; nothing is committed. Each file is whitespace separated with 26 columns:
unit, cycle, 3 operating settings, 21 sensors. Protocol: docs/benchmarks/cmapss_degradation_v1.md.
The suite has no degradation engine yet, so the protocol is predictor-agnostic and the shipped
predictor is a ridge regression on a capped RUL target (a documented baseline, not an engine).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

SUBSETS = ("FD001", "FD002", "FD003", "FD004")
N_COLUMNS = 26
RUL_CAP = 125.0  # piece-wise linear target: constant while the engine is healthy
WINDOW = 5  # test features: mean of the last WINDOW cycles of an engine
RIDGE = 1.0
SEED = 21  # the baseline is deterministic; the seed is recorded for engines that are not


def subset_present(folder: Path, subset: str) -> bool:
    """True when the train, test and RUL file of ``subset`` exist in ``folder``."""
    names = (f"train_{subset}.txt", f"test_{subset}.txt", f"RUL_{subset}.txt")
    return all((folder / n).is_file() for n in names)


def load_units(path: Path) -> dict[int, np.ndarray]:
    """Read a train or test file into {unit: cycles by 24 columns (3 settings + 21 sensors)}."""
    raw = np.loadtxt(path, ndmin=2)
    if raw.shape[1] != N_COLUMNS:
        raise ValueError(f"{path.name}: expected {N_COLUMNS} columns, found {raw.shape[1]}")
    return {int(u): raw[raw[:, 0] == u, 2:] for u in np.unique(raw[:, 0])}


def load_rul(path: Path) -> np.ndarray:
    """True remaining cycles at the last test cycle, one per engine in unit order."""
    return np.loadtxt(path, ndmin=1)


def train_targets(units: dict[int, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """All training rows and their capped RUL (cycles to failure, at most RUL_CAP)."""
    xs = list(units.values())
    ys = [np.minimum(np.arange(len(u) - 1, -1, -1, dtype=float), RUL_CAP) for u in xs]
    return np.vstack(xs), np.concatenate(ys)


def fit_ridge(x: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
    """Standardise (constant columns dropped) and solve the ridge normal equations."""
    keep = x.std(axis=0) > 1e-9
    mean, scale = x[:, keep].mean(axis=0), x[:, keep].std(axis=0)
    z = (x[:, keep] - mean) / scale
    a = z.T @ z + RIDGE * np.eye(z.shape[1])
    return {"keep": keep, "mean": mean, "scale": scale, "b0": np.array(y.mean()),
            "w": np.linalg.solve(a, z.T @ (y - y.mean()))}


def predict(model: dict[str, np.ndarray], units: dict[int, np.ndarray]) -> np.ndarray:
    """RUL per engine from the mean of its last WINDOW cycles, clipped to [0, RUL_CAP]."""
    rows = np.array([u[-WINDOW:].mean(axis=0) for _, u in sorted(units.items())])
    z = (rows[:, model["keep"]] - model["mean"]) / model["scale"]
    return np.clip(model["b0"] + z @ model["w"], 0.0, RUL_CAP)


def rmse(pred: np.ndarray, true: np.ndarray) -> float:
    """Root mean squared error of the RUL prediction."""
    return float(np.sqrt(np.mean((pred - true) ** 2)))


def phm08_score(pred: np.ndarray, true: np.ndarray) -> float:
    """PHM08 score, d = pred - true: sum of exp(-d/13) - 1 if early (d < 0), else exp(d/10) - 1."""
    d = pred - true
    return float(np.sum(np.where(d < 0, np.exp(-d / 13.0), np.exp(d / 10.0)) - 1.0))


def run_subset(folder: Path, subset: str) -> dict:
    """Fit on train_<subset>, predict the last cycle of every test engine, score both metrics."""
    train = load_units(folder / f"train_{subset}.txt")
    test = load_units(folder / f"test_{subset}.txt")
    true = load_rul(folder / f"RUL_{subset}.txt")
    if len(true) != len(test):
        raise ValueError(f"RUL_{subset}.txt has {len(true)} rows for {len(test)} test engines")
    pred = predict(fit_ridge(*train_targets(train)), test)
    return {"engines": len(test), "rmse": rmse(pred, true), "phm08_score": phm08_score(pred, true)}


def run_protocol(folder: Path) -> dict:
    """Execute cmapss_degradation_v1 on every subset present in ``folder``."""
    done = {s: run_subset(folder, s) for s in SUBSETS if subset_present(folder, s)}
    return {"protocol": "cmapss_degradation_v1", "seed": SEED, "subsets": done}
