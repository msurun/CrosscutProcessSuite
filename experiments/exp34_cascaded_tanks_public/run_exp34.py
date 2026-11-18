"""exp34 runner: Cascaded Tanks public data against the frozen targets K1-K4 of README.md.

Usage: python run_exp34.py --data DIR (folder holding dataBenchmark.csv). Prints aggregate
numbers only; without the data it prints "not run: data unavailable" and exits 0. The data is
CC BY-SA 4.0 and never committed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from crosscut_loops.identification_ipdt import identify_ipdt
from crosscut_loops.metrics import saturation_fraction
from crosscut_loops.step_fit import StepFit, effective_delay_s, fit_step
from crosscut_loops.tuning_rules_integrating import simc_pi_integrating, tau_c_for_max_swing

TS_S = 4.0
CLIP_V = 9.95
PRE = 20


def load(data_dir: Path) -> dict[str, tuple[np.ndarray, np.ndarray]] | None:
    """Return {'Est': (u, y), 'Val': (u, y)} or None when the CSV is missing."""
    path = data_dir / "dataBenchmark.csv"
    if not path.is_file():
        for hit in data_dir.rglob("dataBenchmark.csv"):
            path = hit
            break
    if not path.is_file():
        return None
    raw = np.genfromtxt(path, delimiter=",", skip_header=1)[:, :4]
    return {"Est": (raw[:, 0], raw[:, 2]), "Val": (raw[:, 1], raw[:, 3])}


def _fit_line(fit: StepFit) -> str:
    """One-line summary of a StepFit."""
    eff, floored = effective_delay_s(fit, TS_S)
    gain = f"{fit.gain.value:.3g}" if fit.gain else "-"
    tau = f"{fit.tau_s.value:.3g}" if fit.tau_s else "-"
    slope = f"{fit.slope.value:.3g}" if fit.slope else "-"
    return (
        f"{fit.model}: r2={fit.r2:.3f} bic={fit.bic:.1f} gain={gain} tau={tau} slope={slope} "
        f"theta={fit.theta_s.value:.3g} eff_delay={eff:.3g}{'(floor)' if floored else ''} "
        f"edges={list(fit.edges)}"
    )


def analyse(name: str, u: np.ndarray, y: np.ndarray) -> dict[str, bool]:
    """Run the procedure on one set, print numbers and return the K1-K4 outcomes."""
    t = np.arange(len(u)) * TS_S
    ipdt = identify_ipdt(t, u, y)
    print(
        f"[{name}] identify_ipdt: {ipdt.verdict} {list(ipdt.reasons)} r2={ipdt.r_squared:.3f} "
        f"slope={ipdt.model.slope_per_s:.3g} delay={ipdt.model.delay_s:.3g}"
    )
    fits = {}
    for model in ("ipdt", "fopdt"):
        try:
            fits[model] = fit_step(t, y, u, PRE, model)
            print(f"[{name}] fit_step {_fit_line(fits[model])}")
        except ValueError as exc:
            print(f"[{name}] fit_step {model} raised {type(exc).__name__}: {exc}")
    sat = saturation_fraction(y, 0.0, 10.0)
    print(f"[{name}] saturation_fraction(y, 0, 10) = {sat:.4f}")
    _clip_free(name, t, u, y)
    _tuning(name, ipdt)
    fop = fits.get("fopdt")
    return {
        "K1": ipdt.verdict != "ok",
        "K2": "fopdt" in fits and "ipdt" in fits and fits["fopdt"].bic < fits["ipdt"].bic,
        "K3": 0.02 <= sat <= 0.08,
        "K4": fop is not None and fop.gain is not None and fop.gain.value > 0,
    }


def _clip_free(name: str, t: np.ndarray, u: np.ndarray, y: np.ndarray) -> None:
    """Report-only fits on the segment before the first clipped sample."""
    hits = np.flatnonzero(y >= CLIP_V)
    n = int(hits[0]) if hits.size else len(y)
    ipdt = identify_ipdt(t[:n], u[:n], y[:n])
    print(f"[{name}] clip-free n={n}: identify_ipdt {ipdt.verdict} {list(ipdt.reasons)}")
    for model in ("ipdt", "fopdt"):
        try:
            fit = fit_step(t[:n], y[:n], u[:n], PRE, model)
            print(f"[{name}] clip-free fit_step {_fit_line(fit)}")
        except ValueError as exc:
            print(f"[{name}] clip-free fit_step {model} raised {type(exc).__name__}: {exc}")


def _tuning(name: str, ipdt) -> None:
    """Report-only: what an averaging-level user would be offered from the IPDT fit."""
    slope, delay = ipdt.model.slope_per_s, max(ipdt.delay_used_s, TS_S)
    if slope <= 0:
        print(f"[{name}] tuning: no recommendation (IPDT slope {slope:.3g} not positive)")
        return
    tau_c = tau_c_for_max_swing(slope, delay, 10.0, 5.0)
    pi = simc_pi_integrating(slope, delay, tau_c)
    print(f"[{name}] tuning (report only): tau_c={tau_c:.3g} s, PI={pi}")


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns 0 also when the data is missing."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    args = ap.parse_args(argv)
    sets = load(args.data) if args.data.is_dir() else None
    if sets is None:
        print("not run: data unavailable")
        return 0
    outcome = {name: analyse(name, *uy) for name, uy in sets.items()}
    for k in ("K1", "K2", "K3", "K4"):
        met = all(o[k] for o in outcome.values())
        per_set = ", ".join(f"{n}={o[k]}" for n, o in outcome.items())
        print(f"{k}: {'met' if met else 'NOT met'} ({per_set})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
