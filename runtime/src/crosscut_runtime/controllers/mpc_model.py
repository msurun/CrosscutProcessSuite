"""Load and check the identified model of an MPC controller (Phase 7.3, design note 2.2).

The catalogue names the ``ident_model`` artifact and its SHA-256. The runtime refuses to build the
controller when the artifact is missing, its hash differs, a pair failed the identification gate,
the sample time differs from the controller cycle or the model channels do not match the
variables. Every refusal is a ``ModelRefused`` whose message starts with a stable code.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crosscut_artifacts.manifest import ArtifactError
from crosscut_mpc.artifact import IdentModelIntegrityError, load_ident_model
from crosscut_mpc.identification import IdentificationRejected
from crosscut_mpc.model import FopdtModel

MODEL_STORE = ("_mpc", "models")
SHA256 = re.compile(r"[0-9a-fA-F]{64}")
CYCLE_TOLERANCE = 0.01  # relative difference between model sample time and controller cycle


class ModelRefused(ValueError):
    """The model cannot drive this controller (the message starts with the reason code)."""


@dataclass(frozen=True)
class BoundModel:
    """The checked plant model and the variable ids in model order (MVs, CVs, DVs)."""

    plant: FopdtModel
    mv_ids: tuple[str, ...]
    cv_ids: tuple[str, ...]
    dv_ids: tuple[str, ...]


def model_directory(root: Path, artifact: str) -> Path:
    """The artifact folder inside the model store; a path leaving the store is refused."""
    store = root.joinpath(*MODEL_STORE).resolve()
    if not isinstance(artifact, str) or not artifact.strip():
        raise ModelRefused("model_missing: the catalogue names no artifact id")
    path = (store / artifact).resolve()
    if path == store or not path.is_relative_to(store) or not path.is_dir():
        raise ModelRefused(f"model_missing: no ident_model {artifact!r} in the model store")
    return path


def _match(
    names: Sequence[str], variables: Sequence[Mapping[str, Any]], role: str
) -> tuple[str, ...]:
    """Variable ids of ``role`` in model order; a name is a variable id or its tag or loop."""
    pool = [v for v in variables if v["role"] == role]
    if len(names) != len(pool):
        raise ModelRefused(
            f"model_names: model has {len(names)} {role} channels, catalogue {len(pool)}"
        )
    ids = []
    for name in names:
        found = [v["id"] for v in pool if name in {v["id"], *v["binding"].values()}]
        if len(found) != 1 or found[0] in ids:
            raise ModelRefused(f"model_names: channel {name!r} matches no single {role} variable")
        ids.append(found[0])
    return tuple(ids)


def load_bound_model(
    root: Path, doc: Mapping[str, Any], cycle_s: float
) -> BoundModel:
    """Load, verify and bind the model of controller ``doc``; ``ModelRefused`` on any problem."""
    ref = doc["mpc"]["model"]
    sha = ref.get("sha256")
    if not isinstance(sha, str) or SHA256.fullmatch(sha) is None:
        raise ModelRefused("model_hash: the catalogue needs the 64 hex digit SHA-256 of the model")
    path = model_directory(root, ref.get("artifact"))
    try:
        model = load_ident_model(path, sha.lower())
        plant = model.to_mpc_model()
    except IdentModelIntegrityError as error:
        raise ModelRefused(f"model_hash: {error}") from error
    except IdentificationRejected as error:
        raise ModelRefused(f"model_gate: {error}") from error
    except (ArtifactError, KeyError, ValueError, OSError) as error:
        raise ModelRefused(f"model_unreadable: {error}") from error
    if abs(plant.cycle_s - cycle_s) > CYCLE_TOLERANCE * cycle_s:
        raise ModelRefused(f"model_cycle: model {plant.cycle_s} s, controller {cycle_s} s")
    variables = doc["variables"]
    count = sum(v["role"] == "MV" for v in variables)
    names = model.input_names
    return BoundModel(
        plant,
        _match(names[:count], variables, "MV"),
        _match(model.cv_names, variables, "CV"),
        _match(names[count:], variables, "DV"),
    )
