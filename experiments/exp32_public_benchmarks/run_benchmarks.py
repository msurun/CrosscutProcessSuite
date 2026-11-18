"""CLI for the public benchmarks: ``tep``, ``cmapss`` (need a data folder) and ``urls``.

Usage: python run_benchmarks.py {tep|cmapss} --data DIR [--out results.json]; ``urls`` prints
where to download the files by hand. A missing data folder or file set is a clean skip (exit 0,
nothing written), so CI without data stays green. The data is never committed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import cmapss_degradation  # noqa: E402
import tep_anomaly  # noqa: E402

URLS = {
    "tep": "https://doi.org/10.7910/DVN/6C3JR1 (Harvard Dataverse; 4 .RData files, convert to CSV)",
    "cmapss": "https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/"
              "pcoe/pcoe-data-set-repository/ (Turbofan Engine Degradation Simulation Data Set)",
}


def _present(kind: str, folder: Path) -> bool:
    """Whether the files the protocol of ``kind`` reads exist in ``folder``."""
    if kind == "tep":
        return tep_anomaly.data_present(folder)
    return any(cmapss_degradation.subset_present(folder, s) for s in cmapss_degradation.SUBSETS)


def run(kind: str, folder: Path, out: Path | None) -> int:
    """Run one protocol; print SKIP and return 0 when the data is absent."""
    if not _present(kind, folder):
        print(f"SKIP {kind}: expected files not found in {folder}")
        return 0
    module = tep_anomaly if kind == "tep" else cmapss_degradation
    text = json.dumps(module.run_protocol(folder), indent=2)
    if out is not None:
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["tep", "cmapss", "urls"])
    parser.add_argument("--data", type=Path, default=Path("data/benchmarks"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.kind == "urls":
        print("\n".join(f"{k}: {v}" for k, v in URLS.items()))
        return 0
    return run(args.kind, args.data, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
