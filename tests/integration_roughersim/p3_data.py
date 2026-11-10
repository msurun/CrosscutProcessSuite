"""Record the step-test scenario with RougherSim's own interpreter and load offline evidence.
Aligned arrays retain quality; independent truth is never used to fit the model.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as parquet
from golden import roughersim_dir, venv_python

SAMPLE_INTERVAL_S = 60.0  # seconds between recorder samples
RECORD_TIMEOUT_S = 600  # wall seconds allowed for one headless run
LOOPS = ("FIC203", "LIC301")  # loops exercised by the P3 acceptance rows
BASE_TAGS = ("{loop}", "{loop}_sp", "{loop}_out", "{loop}_mode")
OPTIONAL_TAGS = ("{loop}_rsp",)  # only a cascade secondary has a remote setpoint
RECORDER = """
import sys
from pathlib import Path
from dataclasses import replace
from roughersim.scenario.loader import load_scenario, Event
from roughersim.scenario.runner import run_loaded
loop = sys.argv[4]
scenario = load_scenario(Path('scenarios/rs.step_test.fic203.v1.json'))
values = [('kc', float(sys.argv[2])), ('ti_s', float(sys.argv[3]))]
events = tuple(Event(0, 'operator_write', loop, {'field': field, 'value': value})
               for field, value in values)
step = replace(next(event for event in scenario.events if event.kind == 'step_test'),
               target=loop)
others = tuple(event for event in scenario.events if event.kind != 'step_test')
run_loaded(replace(scenario, events=events + others + (step,)), Path(sys.argv[1]))
"""


def record_tuning(
    destination: Path, tuning: dict[str, float], loop_tag: str = "FIC203"
) -> dict[str, np.ndarray]:
    """Run the pinned simulator headlessly; return aligned recording arrays."""
    checkout = roughersim_dir().resolve()
    command = [str(venv_python(checkout)), "-c", RECORDER, str(destination.resolve()),
               str(tuning["gain"]), str(tuning["ti"]), loop_tag]
    environment = {**os.environ, "PYTHONPATH": str(checkout / "src")}
    subprocess.run(command, cwd=checkout, env=environment, check=True,
                   capture_output=True, text=True, timeout=RECORD_TIMEOUT_S)
    return load_recording(destination)


def load_recording(directory: Path) -> dict[str, np.ndarray]:
    """Read timestamp/tag/value/quality parquet columns without interpolating samples."""
    paths = sorted((directory / "data").rglob("*.parquet"))
    if not paths:
        raise FileNotFoundError(f"No recording parquet under {directory / 'data'}")
    table = pa.concat_tables([parquet.read_table(path) for path in paths])
    # Schema: UTC timestamp, string tag_id, numeric value, integer quality (0 = good).
    timestamps = table["ts"].cast(pa.timestamp("ns", tz="UTC")).cast(pa.int64()).to_numpy()
    columns = (timestamps, np.asarray(table["tag_id"].to_pylist()),
               table["value"].to_numpy(), table["quality"].to_numpy())
    tags = _recording_tags(columns[1])
    aligned = {tag: _align_tag(columns, tag) for tag in tags}
    reference = aligned[tags[0]][0]
    if not all(np.array_equal(reference, arrays[0]) for arrays in aligned.values()):
        raise ValueError("Recording tags have mismatched timestamps; inspect recorder output")
    seconds = (reference - reference[0]) / 1e9
    if not np.allclose(np.diff(seconds), SAMPLE_INTERVAL_S):
        raise ValueError("Expected contiguous 60 s recording samples")
    return {"time": seconds, **{tag: arrays[1] for tag, arrays in aligned.items()},
            "quality": np.maximum.reduce([arrays[2] for arrays in aligned.values()])}


def _recording_tags(names: np.ndarray) -> tuple[str, ...]:
    """Every tag of the supported loops; the remote setpoint exists only on a cascade loop."""
    present = set(names)
    return tuple(tag for loop in LOOPS for tag in _loop_tags(loop, present))


def _loop_tags(loop_tag: str, present: set[str]) -> tuple[str, ...]:
    """Required tags of one loop plus its optional remote setpoint tag."""
    base = tuple(pattern.format(loop=loop_tag) for pattern in BASE_TAGS)
    optional = tuple(pattern.format(loop=loop_tag) for pattern in OPTIONAL_TAGS)
    return base + tuple(tag for tag in optional if tag in present)


def _align_tag(columns: tuple[np.ndarray, ...], tag: str) -> tuple[np.ndarray, ...]:
    """Sort one tag and reject duplicate or absent samples."""
    timestamps, names, values, qualities = columns
    positions = np.flatnonzero(names == tag)
    positions = positions[np.argsort(timestamps[positions])]
    if not len(positions) or len(np.unique(timestamps[positions])) != len(positions):
        raise ValueError(f"Missing or duplicate samples for {tag}; inspect the recording")
    return timestamps[positions], values[positions], qualities[positions]


def load_truth(directory: Path, loop_tag: str = "FIC203") -> dict[str, float]:
    """Return one loop's FOPDT segment, refusing ambiguous changing truth."""
    payload = json.loads((directory / "truth" / "loops.json").read_text(encoding="utf-8"))
    segments = _find_segments(payload, loop_tag)
    unique = {tuple(float(segment[key]) for key in ("gain", "tau_s", "theta_s"))
              for segment in segments}
    if len(unique) != 1:
        raise ValueError(f"Expected one {loop_tag} FOPDT truth model, found {unique}")
    return dict(zip(("gain", "tau_s", "theta_s"), unique.pop(), strict=True))


def _find_segments(
    node: Any, loop_tag: str, context: str = ""
) -> list[dict[str, Any]]:
    """Walk loop/segment containers while keeping the loop identity in context."""
    if isinstance(node, list):
        return [segment for child in node
                for segment in _find_segments(child, loop_tag, context)]
    if not isinstance(node, dict):
        return []
    identity = context + " " + str(node.get("loop_id", node.get("loop", "")))
    identity += " " + str(node.get("tag_id", ""))
    if loop_tag in identity and {"gain", "tau_s", "theta_s"} <= node.keys():
        if str(node.get("model", "")).lower() != "fopdt":
            raise ValueError(f"{loop_tag} truth segment is not FOPDT")
        return [node]
    return [segment for key, child in node.items()
            for segment in _find_segments(child, loop_tag, identity + " " + key)]
