"""Convert the labelled ISDB loops from isdb10.mat to one npz per loop (sp, pv, op, dt_s).

Usage: python -I isdb_to_npz.py <isdb10.mat> <labels.csv> <out dir>   (needs scipy; untrusted file,
so run isolated). Only arrays are written; no detector is run. Loops without an OP column are
skipped and listed. The output folder stays outside the repository.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import scipy.io as sio


def main(mat: Path, labels: Path, out: Path) -> None:
    """Write <section>_<loop>.npz for every loop of the label table."""
    data = sio.loadmat(mat, squeeze_me=True, struct_as_record=False)["cdata"]
    out.mkdir(parents=True, exist_ok=True)
    for row in csv.DictReader(labels.open(encoding="utf-8")):
        section, name = row["loop"].split("/")
        loop = getattr(getattr(data, section), name)
        arrays = {k: np.atleast_1d(np.asarray(getattr(loop, k), float)) for k in ("SP", "PV", "OP")}
        if len({len(a) for a in arrays.values()}) != 1 or len(arrays["OP"]) < 10:
            print("skipped (no usable OP):", row["loop"])
            continue
        np.savez(
            out / f"{section}_{name}.npz",
            sp=arrays["SP"],
            pv=arrays["PV"],
            op=arrays["OP"],
            dt_s=float(loop.Ts),
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
