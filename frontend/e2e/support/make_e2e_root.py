"""Build the complete data root the Playwright specs in `frontend/e2e/` need.

Usage: python make_e2e_root.py <target dir>

Creates the demo datasets `mill_circuit_{stiction,step_test,observational}_seed42` with
`crosscut_sim.run` (6 h at 10 s) and `level_integrating_demo` with `make_level_dataset.py`.
The lab CSV of the soft sensor spec is made by that spec itself. Refuses a non-empty target.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCENARIOS = ("stiction", "step_test", "observational")
HERE = Path(__file__).resolve().parent


def _simulate(scenario: str, work: Path) -> Path:
    """Run the mill circuit simulation for one scenario into `work`; returns the dataset folder."""
    out = work / scenario
    out.mkdir()
    command = [
        sys.executable, "-m", "crosscut_sim.run", "--plant", "mill_circuit", "--scenario", scenario,
        "--duration", "6h", "--sample-period", "10", "--out", str(out),
    ]  # fmt: skip
    subprocess.run(command, check=True)
    found = list(out.glob("mill_circuit_*_seed42"))
    if len(found) != 1:
        raise RuntimeError(f"expected one dataset for {scenario} in {out}, found {found}")
    return found[0]


def build(target: Path) -> None:
    """Fill `target` (missing or empty) with every dataset the e2e specs use."""
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty target: {target}")
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for scenario in SCENARIOS:
            dataset = _simulate(scenario, Path(tmp))
            shutil.move(str(dataset), str(target / dataset.name))
    subprocess.run([sys.executable, str(HERE / "make_level_dataset.py"), str(target)], check=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    build(Path(sys.argv[1]))
