"""Server-computed validation record that feeds the deployment gate (and nothing else may).

``build_record`` runs the #156 comparison table (structure against causal lab baselines, forward
blocked CV, same information cutoff) and stamps it with dataset, window, code version, the hash
of the fitted model file and a content hash. ``problems`` re-checks a stored record: any edit,
refit or preset change makes it unusable, so the gate refuses until validation is run again.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_softsensor import comparison, deployment_gate, pls

SOURCES = (comparison, deployment_gate, pls)  # modules whose text defines the code version


def code_version() -> str:
    """SHA-256 over the source of the comparison, gate and PLS modules."""
    digest = hashlib.sha256()
    for module in SOURCES:
        digest.update(Path(str(module.__file__)).read_bytes())
    return digest.hexdigest()[:16]


def file_sha256(path: Path) -> str:
    """SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(record: Mapping[str, Any]) -> str:
    """Hash of the canonical JSON of a record without its ``hash`` field."""
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def _clean(value: Any) -> Any:
    """JSON-safe copy: NaN and infinity become None."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


def build_record(
    preset: Mapping[str, Any], structure: str, table: comparison.ComparisonTable,
    origin: dict[str, Any],
) -> dict[str, Any]:
    """The stored record; ``origin`` holds dataset_id, window and the model file hash."""
    row = next(r for r in table.rows if r["method"] == structure)
    reference = next(r for r in table.rows if r["method"] == row["strongest_baseline"])
    results = {"rmse_model": row["rmse"], "rmse_baseline": reference["rmse"],
               "scored_coverage": row["coverage"], "n_samples": row["n"],
               "baseline": preset["deployment_gate"]["baseline"],
               "same_information_cutoff": True}
    record = {"preset": preset["key"], "structure": structure, **origin,
              "code_version": code_version(), "created_utc": datetime.now(UTC).isoformat(),
              "strongest_baseline": row["strongest_baseline"], "results": results,
              "table": list(table.rows)}
    record = _clean(record)
    record["hash"] = content_hash(record)
    return record  # type: ignore[no-any-return]


def problems(record: Mapping[str, Any], model_file: Path) -> list[str]:
    """Reasons a stored record may not feed the gate (empty = intact and current)."""
    found = []
    if record.get("hash") != content_hash(record):
        found.append("stored validation hash does not match its content")
    if not model_file.is_file() or record.get("model_file_sha256") != file_sha256(model_file):
        found.append("stored validation was not computed for the current model")
    if record.get("code_version") != code_version():
        found.append("stored validation was computed by a different code version")
    return found
