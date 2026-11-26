"""Store and load an identified MIMO model as an `ident_model` artifact (ADR 004, note 2.2).

The payload `model.json` holds the matrices; the manifest carries per-pair metrics and the
data window. Loading verifies payload hashes and, when given, the hash named by the catalogue.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from crosscut_artifacts.manifest import (
    ArtifactError,
    ArtifactIntegrityError,
    ArtifactMetadata,
    read_manifest,
    sha256_bytes,
    write_artifact,
)

from .identification import IdentifiedModel, PairQuality

ARTIFACT_TYPE = "ident_model"
PAYLOAD = "model.json"
CREATOR = {"tool": "crosscut_mpc.identification", "version": "0.0.1"}


class IdentModelIntegrityError(ArtifactIntegrityError):
    """Raised when the stored model does not match its manifest or the expected hash."""


def _payload_bytes(model: IdentifiedModel) -> bytes:
    """Deterministic JSON: sorted keys, fixed layout; matrices are (CV, input) lists."""
    doc = {
        "input_names": list(model.input_names),
        "cv_names": list(model.cv_names),
        "gains": model.gains.tolist(),
        "time_constants_s": model.time_constants_s.tolist(),
        "dead_times_s": model.dead_times_s.tolist(),
        "cycle_s": model.cycle_s,
    }
    return json.dumps(doc, sort_keys=True, indent=1).encode("utf-8")


def _metrics(model: IdentifiedModel) -> dict[str, object]:
    """Per-pair fit metrics keyed "input->cv", plus the overall verdict."""
    pairs = {
        f"{name}->{cv}": {
            "free_run_r2": q.free_run_r2 if np.isfinite(q.free_run_r2) else None,
            "excitation_events": q.excitation_events,
            "passed": q.passed,
            "reasons": list(q.reasons),
        }
        for cv, row in zip(model.cv_names, model.quality, strict=True)
        for name, q in zip(model.input_names, row, strict=True)
    }
    return {"method": model.method, "accepted": model.accepted, "pairs": pairs}


def save_ident_model(
    out_dir: str | Path,
    model: IdentifiedModel,
    dataset_hashes: list[str] | None = None,
    created_utc: str | None = None,
) -> str:
    """Write the artifact and return the SHA-256 of the payload (what the catalogue stores)."""
    payload = _payload_bytes(model)
    metadata = ArtifactMetadata(
        creator=CREATOR,
        inputs=[{"sha256": h} for h in dataset_hashes or []],
        metrics=_metrics(model),
        valid_context={"data_windows_s": {k: list(v) for k, v in model.windows.items()}},
        created_utc=created_utc,
    )
    write_artifact(out_dir, ARTIFACT_TYPE, {PAYLOAD: payload}, metadata)
    return sha256_bytes(payload)


def load_ident_model(path: str | Path, expected_sha256: str | None = None) -> IdentifiedModel:
    """Load and verify an artifact; raise IdentModelIntegrityError on any hash mismatch."""
    try:
        manifest = read_manifest(path, verify=True)
    except ArtifactIntegrityError as err:
        raise IdentModelIntegrityError(str(err)) from err
    if manifest["artifact_type"] != ARTIFACT_TYPE:
        raise ArtifactError(f"not an {ARTIFACT_TYPE} artifact: {manifest['artifact_type']}")
    recorded = next(e["sha256"] for e in manifest["payload"] if e["path"] == PAYLOAD)
    if expected_sha256 is not None and expected_sha256 != recorded:
        raise IdentModelIntegrityError("payload hash differs from the hash named by the catalogue")
    doc = json.loads((Path(path) / PAYLOAD).read_text(encoding="utf-8"))
    pairs = manifest["metrics"]["pairs"]
    quality = tuple(
        tuple(_quality_from(pairs[f"{name}->{cv}"]) for name in doc["input_names"])
        for cv in doc["cv_names"]
    )
    windows = {k: (v[0], v[1]) for k, v in manifest["valid_context"]["data_windows_s"].items()}
    return IdentifiedModel(
        tuple(doc["input_names"]), tuple(doc["cv_names"]), np.array(doc["gains"]),
        np.array(doc["time_constants_s"]), np.array(doc["dead_times_s"]), doc["cycle_s"],
        quality, windows, manifest["metrics"]["method"],
    )


def _quality_from(metric: dict[str, object]) -> PairQuality:
    """Rebuild a PairQuality from its manifest entry (null R2 means -inf)."""
    r2 = metric["free_run_r2"]
    return PairQuality(
        float(r2) if r2 is not None else float("-inf"),  # type: ignore[arg-type]
        int(metric["excitation_events"]),  # type: ignore[call-overload]
        bool(metric["passed"]),
        tuple(metric["reasons"]),  # type: ignore[arg-type]
    )
