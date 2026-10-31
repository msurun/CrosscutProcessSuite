"""Golden-hash recipe for RougherSim recordings pinned by Crosscut.

Crosscut pins one RougherSim release (``pin.json``) and guards a sha256 per
(scenario, seed). A moved hash means the simulator model changed under the pin.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
PIN_PATH = HERE / "pin.json"
SCENARIOS = ("rs.nominal.base.v1", "rs.step_test.fic203.v1")
SIG_DIGITS = 6
CODE_PATHS = ("src", "scenarios", "profiles", "pyproject.toml")


def golden_hash(dataset_dir: Path) -> str:
    """Return the golden sha256 of one recording written by ``roughersim record``.

    Recipe (every step is needed to reproduce the value):

    1. ``loops``: parsed ``truth/loops.json``.
    2. ``events``: rows of ``truth/events.parquet`` as dicts (column order of the
       file); ``params_json`` stays the raw string.
    3. ``recording``: rows ``[ts_ns, tag_id, value, quality]`` of every Parquet
       file under ``data/`` (files sorted by relative path, rows in file order);
       ``ts_ns`` is the UTC timestamp as integer nanoseconds.
    4. Every float anywhere is rounded to 6 significant digits
       (``float(f"{x:.6g}")``); NaN and infinity become the strings "nan",
       "inf", "-inf". Rounding absorbs cross-platform float noise.
    5. Payload ``{"events": ..., "loops": ..., "recording": ...}`` is serialised
       as canonical JSON (``sort_keys=True``, separators ``(",", ":")``,
       ``ensure_ascii=True``) and encoded as UTF-8.
    6. The golden is the hex sha256 of those bytes.

    ``dataset.json``/``tags.json`` are left out on purpose: they carry run
    metadata (paths, git commit, timestamps) and the data is hashed directly.
    """
    truth = dataset_dir / "truth"
    payload = {
        "loops": _round(json.loads((truth / "loops.json").read_text(encoding="utf-8"))),
        "events": _round(pq.read_table(truth / "events.parquet").to_pylist()),
        "recording": _recording_rows(dataset_dir / "data"),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _recording_rows(data_dir: Path) -> list[list[Any]]:
    """Return ``[ts_ns, tag_id, value, quality]`` rows of all Parquet files."""
    rows: list[list[Any]] = []
    paths = sorted(data_dir.rglob("*.parquet"), key=lambda p: p.relative_to(data_dir).as_posix())
    for path in paths:
        table = pq.read_table(path, columns=["ts", "tag_id", "value", "quality"])
        ts_ns = table.column("ts").cast(pa.timestamp("ns", tz="UTC")).cast(pa.int64()).to_pylist()
        tags = table.column("tag_id").to_pylist()
        values = table.column("value").to_pylist()
        quality = table.column("quality").to_pylist()
        rows.extend(
            [t, g, _round(v), q] for t, g, v, q in zip(ts_ns, tags, values, quality, strict=True)
        )
    return rows


def _round(obj: Any) -> Any:
    """Round floats to ``SIG_DIGITS`` significant digits, recursively."""
    if isinstance(obj, float):
        if math.isnan(obj):
            return "nan"
        if math.isinf(obj):
            return "inf" if obj > 0 else "-inf"
        return float(f"{obj:.{SIG_DIGITS}g}")
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    return obj


def load_pin() -> dict[str, Any]:
    """Read ``pin.json``."""
    pin: dict[str, Any] = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    return pin


def write_golden(pin: dict[str, Any], key: str, digest: str) -> None:
    """Store one golden in ``pin.json`` (only the goldens map; tag/sha stay by hand)."""
    pin["goldens"][key] = digest
    PIN_PATH.write_text(json.dumps(pin, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def roughersim_dir() -> Path:
    """RougherSim checkout: ``ROUGHERSIM_DIR`` or the sibling ``../RougherSim``."""
    env = os.environ.get("ROUGHERSIM_DIR")
    return Path(env) if env else HERE.parents[2] / "RougherSim"


def venv_python(rs_dir: Path) -> Path:
    """Interpreter for RougherSim: ``ROUGHERSIM_PYTHON``, else the checkout's ``.venv``."""
    override = os.environ.get("ROUGHERSIM_PYTHON")
    if override:
        return Path(override)
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        if (rs_dir / rel).exists():
            return rs_dir / rel
    return Path(sys.executable)


def git(rs_dir: Path, *args: str) -> str:
    """Run git in the RougherSim checkout and return stripped stdout ('' on failure)."""
    proc = subprocess.run(
        ["git", "-C", str(rs_dir), *args], capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def checkout_problem(rs_dir: Path, pin: dict[str, Any]) -> str | None:
    """Return why the checkout is not the pinned one, or None when it is."""
    if not (rs_dir / "scenarios").is_dir():
        return f"RougherSim not found at {rs_dir} (set ROUGHERSIM_DIR)"
    head = git(rs_dir, "rev-parse", "HEAD")
    if head != pin["commit_sha"]:
        tag = git(rs_dir, "describe", "--tags", "--exact-match") or "no tag"
        return (
            f"RougherSim at {head[:12] or '?'} ({tag}), "
            f"pin is {pin['tag']} {pin['commit_sha'][:12]}"
        )
    # Only paths that can change a recording count; edits to docs do not.
    dirty = git(rs_dir, "status", "--porcelain", "--untracked-files=no", "--", *CODE_PATHS)
    if dirty:
        return "RougherSim checkout has local modifications in src/scenarios/profiles"
    return None


def record(rs_dir: Path, scenario: Path, out: Path) -> None:
    """Run ``roughersim record`` through the RougherSim venv; raise on failure."""
    code = "import sys; from roughersim.cli import main; sys.exit(main(sys.argv[1:]))"
    cmd = [str(venv_python(rs_dir)), "-c", code, "record", str(scenario), "--out", str(out)]
    # PYTHONPATH makes the checked checkout win over an editable install of another one.
    env = {**os.environ, "PYTHONPATH": str(rs_dir / "src")}
    subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=rs_dir, env=env)
