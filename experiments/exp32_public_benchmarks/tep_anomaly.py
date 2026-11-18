"""Tennessee Eastman (Rieth et al. 2017) loader, frozen anomaly protocol and metrics.

The user downloads the four files (see run_benchmarks.py urls) into a local folder and converts
each .RData to CSV with the same base name (pyreadr or R); nothing is committed. A CSV has the
columns faultNumber, simulationRun, sample, xmeas_1..xmeas_41, xmv_1..xmv_11.
Protocol: docs/benchmarks/tep_anomaly_v1.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow.csv as pacsv
from crosscut_anomaly.config import AnomalyConfig, load_config
from crosscut_anomaly.detect import scan
from crosscut_anomaly.pca_model import fit_from_config

TAGS = tuple([f"xmeas_{i}" for i in range(1, 42)] + [f"xmv_{i}" for i in range(1, 12)])
FILES = {
    "train": "TEP_FaultFree_Training.csv",
    "test_free": "TEP_FaultFree_Testing.csv",
    "test_fault": "TEP_Faulty_Testing.csv",
}
SAMPLE_PERIOD_S = 180.0
ONSET_INDEX = 160  # testing runs: fault enters after 8 h = 160 samples (0-based index 160)
FAULTS = tuple(range(1, 21))
N_RUNS = 10
TRAIN_SEED, TEST_SEED = 21, 22  # run picks; frozen in the protocol document
CONFIG_DOC = {
    "schema_version": "1.0.0", "id": "tep_benchmark_v1", "tags": list(TAGS), "mode": "advisory",
    "variance_fraction": 0.90, "alpha": 0.99, "min_consecutive": 5, "close_after": 10,
    "sample_period_s": SAMPLE_PERIOD_S,
}


@dataclass(frozen=True)
class TepTable:
    """One file as arrays: fault number, run number and the 52 variables per row."""

    fault: np.ndarray
    run: np.ndarray
    x: np.ndarray

    def record(self, fault: int, run: int) -> np.ndarray:
        """Rows (samples by 52 tags) of one run of one fault, in file order."""
        return self.x[(self.fault == fault) & (self.run == run)]


@dataclass(frozen=True)
class RunScore:
    """Outcome of one run: detection delay in samples (None = missed) and pre-onset alarms."""

    delay: int | None
    false_alarm_samples: int
    pre_samples: int


def load_table(path: Path) -> TepTable:
    """Read one converted CSV file; raises ValueError naming a missing column."""
    table = pacsv.read_csv(path)
    missing = [c for c in ("faultNumber", "simulationRun", *TAGS) if c not in table.column_names]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing[:3]}")
    x = np.column_stack([table[t].to_numpy() for t in TAGS]).astype(float)
    return TepTable(table["faultNumber"].to_numpy(), table["simulationRun"].to_numpy(), x)


def data_present(folder: Path) -> bool:
    """True when all three CSV files the protocol reads exist in ``folder``."""
    return all((folder / name).is_file() for name in FILES.values())


def pick_runs(available: np.ndarray, seed: int, n: int = N_RUNS) -> list[int]:
    """The frozen run choice: ``n`` distinct run numbers drawn with a seeded generator, sorted."""
    runs = np.unique(available)
    chosen = np.random.default_rng(seed).choice(runs, size=min(n, len(runs)), replace=False)
    return sorted(int(r) for r in chosen)


def score_run(spans: list[tuple[int, int]], onset: int, n: int) -> RunScore:
    """Score event spans (start, end inclusive, row indices) of one record.

    The first event starting at or after ``onset`` is the detection (delay = start - onset).
    Samples inside events before ``onset`` are false alarms, clipped at ``onset``.
    """
    false_alarms = sum(max(0, min(end + 1, onset) - start) for start, end in spans if start < onset)
    later = [start for start, _ in spans if start >= onset]
    return RunScore(min(later) - onset if later else None, false_alarms, min(onset, n))


def summarise(scores: list[RunScore]) -> dict[str, float | None]:
    """Detection rate, mean delay (samples and minutes) over detected runs, alarm rate."""
    delays = [s.delay for s in scores if s.delay is not None]
    pre = sum(s.pre_samples for s in scores)
    mean = float(np.mean(delays)) if delays else None
    return {
        "runs": len(scores), "detection_rate": len(delays) / len(scores),
        "mean_delay_samples": mean,
        "mean_delay_min": None if mean is None else mean * SAMPLE_PERIOD_S / 60.0,
        "false_alarm_rate": sum(s.false_alarm_samples for s in scores) / pre,
    }


def _spans(model, config: AnomalyConfig, rows: np.ndarray) -> list[tuple[int, int]]:
    """Run the existing detector on one record and return its event spans."""
    t = np.arange(len(rows)) * SAMPLE_PERIOD_S
    return [(e.start_index, e.end_index) for e in scan(model, t, rows, config=config).events]


def _score_free(model, config: AnomalyConfig, rows: np.ndarray) -> RunScore:
    """Fault-free record: every sample counts as pre-onset."""
    return score_run(_spans(model, config, rows), len(rows), len(rows))


def _score_fault(model, config: AnomalyConfig, rows: np.ndarray) -> RunScore:
    """Faulty record: the fault enters at ONSET_INDEX."""
    return score_run(_spans(model, config, rows), ONSET_INDEX, len(rows))


def run_protocol(folder: Path) -> dict:
    """Execute tep_anomaly_v1 on the files in ``folder`` and return the results dictionary."""
    config = load_config(CONFIG_DOC)
    train = load_table(folder / FILES["train"])
    train_runs = pick_runs(train.run, TRAIN_SEED)
    model = fit_from_config(np.vstack([train.record(0, r) for r in train_runs]), config)
    free = load_table(folder / FILES["test_free"])
    faulty = load_table(folder / FILES["test_fault"])
    runs = pick_runs(free.run, TEST_SEED)
    free_scores = [_score_free(model, config, free.record(0, r)) for r in runs]
    per_fault = {
        f: summarise([_score_fault(model, config, faulty.record(f, r)) for r in runs])
        for f in FAULTS
    }
    return {"protocol": "tep_anomaly_v1", "train_runs": train_runs, "test_runs": runs,
            "seeds": [TRAIN_SEED, TEST_SEED], "k": model.k,
            "fault_free": summarise(free_scores), "faults": per_fault}
