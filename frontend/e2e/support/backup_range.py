"""Print the given percentile of one tag of the demo dataset (used to set a backup range in e2e).

Usage: python backup_range.py <data_root> <tag> <percentile>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyarrow.dataset as ds

DATASET_ID = "mill_circuit_observational_seed42"


def main(root: Path, tag: str, percentile: float) -> None:
    """Print the percentile of the tag's values."""
    table = ds.dataset(root / DATASET_ID / "data").to_table(filter=ds.field("tag_id") == tag)
    print(float(np.percentile(table["value"].to_numpy(), percentile)))


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], float(sys.argv[3]))
