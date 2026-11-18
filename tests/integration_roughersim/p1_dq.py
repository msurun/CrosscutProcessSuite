"""L5-P1-dq: onboarding data-quality report scored against RougherSim injected sensor faults.

Records rs.sensor_faults.mix.v1, loads it with the Crosscut loader, runs the onboarding readiness
report (default detector config, nothing tuned on this scenario) and scores its sensor-fault
findings against the ground-truth fault events. Ground truth is read here, never in product code.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from crosscut_connectors.onboarding import evaluate_dataset_readiness
from crosscut_loops.sensor_faults import SensorFaultFinding, score_findings
from crosscut_sim.dataset import read_dataset, to_wide
from golden import record, roughersim_dir

SCENARIO = "scenarios/rs.sensor_faults.mix.v1.json"
FLOWSHEET = "examples/rougher_mvp.json"  # loop tag -> pv instrument, to place truth on columns
NS_PER_S = 1e9  # nanoseconds per second
MIN_PRECISION = 0.9  # owner target, event level, over all findings on all tags
MIN_RECALL = 0.8  # owner target, event level, over the injected events
SUMMARY: dict[str, Any] = {}  # numbers of the last run, for the findings document


def recorded_tags() -> dict[str, str]:
    """Instrument name -> recorded column: the recorder stores a loop's PV under the loop tag."""
    flowsheet = json.loads((roughersim_dir() / FLOWSHEET).read_text(encoding="utf-8"))
    return {loop["pv"]: loop["tag"] for loop in flowsheet["loops"]}


def load_truth_events(recording: Path) -> list[dict[str, Any]]:
    """Injected sensor faults as {tag, kind, start_s, end_s} from truth/events.parquet."""
    rows = pq.read_table(recording / "truth" / "events.parquet").to_pylist()
    columns = recorded_tags()
    return [
        {
            "tag": columns[row["target"]],
            "kind": json.loads(row["params_json"])["kind"],
            "start_s": row["t_start_s"],
            "end_s": row["t_end_s"],
        }
        for row in rows
        if row["kind"] == "fault"
    ]


def report_findings(recording: Path) -> list[SensorFaultFinding]:
    """Run the onboarding readiness report on the recording; return every sensor-fault finding."""
    ts, columns = to_wide(read_dataset(recording))
    seconds = (ts.astype("int64") - ts.astype("int64")[0]) / NS_PER_S
    report = evaluate_dataset_readiness(recording.name, seconds, columns, [])
    return [event for events in report.sensor_faults.values() for event in events]


def summarise(findings: list[SensorFaultFinding], truth: list[dict[str, Any]]) -> dict[str, Any]:
    """Precision, recall and the list of findings, for assertions and the findings document."""
    precision, recall = score_findings(findings, truth)
    per_tag: dict[str, int] = {}
    for event in findings:
        per_tag[event.tag] = per_tag.get(event.tag, 0) + 1
    return {
        "precision": precision,
        "recall": recall,
        "n_findings": len(findings),
        "per_tag": per_tag,
        "findings": [(e.tag, e.kind, e.start_s, e.end_s) for e in findings],
    }


def execute() -> None:
    """Executor of L5-P1-dq: record, report, score, assert the owner targets."""
    with tempfile.TemporaryDirectory() as tmp:
        recording = Path(tmp) / "rec"
        record(roughersim_dir(), roughersim_dir() / SCENARIO, recording)
        truth = load_truth_events(recording)
        assert len(truth) == 3, truth
        SUMMARY.update(summarise(report_findings(recording), truth))
    msg = json.dumps(SUMMARY, default=str)
    assert SUMMARY["precision"] >= MIN_PRECISION, msg
    assert SUMMARY["recall"] >= MIN_RECALL, msg
