"""Preview MPC and a declared current-PID snapshot on an identified plant.

The endpoint reads catalogue bindings and verified artifacts; it has no gateway dependency.
"""

from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from crosscut_artifacts.manifest import ArtifactError
from crosscut_connectors.site import SiteError, load_site
from crosscut_mpc.artifact import load_ident_model
from crosscut_mpc.benefit import BenefitScenario, simulate_benefit
from crosscut_mpc.config import Controller, Limits, Settings
from crosscut_mpc.economics import Economics
from crosscut_mpc.simulator import PidTuning, Scenario, simulate
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from crosscut_api.auth.actor import ActorContext, actor_of

MAX_VARIABLES = 8  # Limit QP dimensions and preview response size.
MAX_PREDICTED_VALUES = 240  # CV-by-horizon entries bound dense QP slack matrices.
MAX_MOVE_VALUES = 48  # MV-by-move-horizon decision variables.
MAX_PREVIEW_VALUES = 50_000  # Total CV predictions across the experiment.
ID_PATTERN = r"^[A-Za-z0-9_-]+$"
Finite = Annotated[float, Field(allow_inf_nan=False)]
Vector = Annotated[list[Finite], Field(min_length=1, max_length=MAX_VARIABLES)]
ActorDep = Annotated[ActorContext, Depends(actor_of)]


class PreviewInput(BaseModel):
    """Reject unrecognised request fields rather than silently changing a simulation."""

    model_config = ConfigDict(extra="forbid")


class LimitInput(PreviewInput):
    """Engineering-unit bounds and per-second rates, matching the reference engine."""

    mv_lower: Vector
    mv_upper: Vector
    cv_lower: Vector
    cv_upper: Vector
    priorities: Vector
    move_max: Vector
    rate_max: Vector
    target_rate: Vector
    funnel_start: Vector
    funnel_end: Vector


class SettingInput(PreviewInput):
    """Bound work per preview while preserving the engine's numerical settings."""

    prediction_horizon: int = Field(default=60, ge=1, le=120)
    move_horizon: int = Field(default=8, ge=1, le=12)
    move_suppression: Finite = Field(default=1.0, gt=0)


class ScenarioInput(PreviewInput):
    """One deterministic step experiment, with indices in artifact matrix order."""

    kind: Literal["sp_step", "dv_step", "constraint_active"] = "sp_step"
    steps: int = Field(default=120, ge=2, le=300)
    step_at: int = Field(default=5, ge=0, le=299)
    amplitude: Finite = 1.0
    cv_index: int = Field(default=0, ge=0, lt=MAX_VARIABLES)
    dv_index: int = Field(default=0, ge=0, lt=MAX_VARIABLES)


class PidInput(PreviewInput):
    """Explicit signed-gain PID snapshot bound to a catalogue loop; times are seconds."""

    loop_id: str = Field(min_length=1, max_length=128)
    kp: Finite
    ti_s: Finite = Field(gt=0)
    td_s: Finite = Field(default=0.0, ge=0)
    cv_index: int = Field(default=0, ge=0, lt=MAX_VARIABLES)


class SimulationInput(PreviewInput):
    """Artifact identity, controller bindings and explicitly entered preview configuration."""

    artifact_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    controller_id: str = Field(min_length=1, max_length=128)
    limits: LimitInput
    settings: SettingInput = Field(default_factory=SettingInput)
    scenario: ScenarioInput = Field(default_factory=ScenarioInput)
    pid_tunings: list[PidInput] = Field(min_length=1, max_length=MAX_VARIABLES)


def _soft(values: list[float | None] | None, size: int, default: float) -> list[float]:
    """A soft-limit vector with null entries (and a missing vector) meaning no limit."""
    if values is None:
        return [default] * size
    if len(values) != size:
        raise ValueError("Soft limit vectors must match the CV or MV count")
    return [default if value is None else value for value in values]


class EconomicsInput(PreviewInput):
    """Per-hour value of each CV unit and cost of each MV unit, in model order."""

    cv_value: Vector
    mv_cost: Vector
    cv_soft_lower: list[Finite | None] | None = Field(default=None, max_length=MAX_VARIABLES)
    cv_soft_upper: list[Finite | None] | None = Field(default=None, max_length=MAX_VARIABLES)
    mv_soft_lower: list[Finite | None] | None = Field(default=None, max_length=MAX_VARIABLES)
    mv_soft_upper: list[Finite | None] | None = Field(default=None, max_length=MAX_VARIABLES)

    def build(self) -> Economics:
        """The engine economics; null soft limits become infinite."""
        cvs, mvs = len(self.cv_value), len(self.mv_cost)
        return Economics(
            np.array(self.cv_value), np.array(self.mv_cost),
            np.array(_soft(self.cv_soft_lower, cvs, -np.inf)),
            np.array(_soft(self.cv_soft_upper, cvs, np.inf)),
            np.array(_soft(self.mv_soft_lower, mvs, -np.inf)),
            np.array(_soft(self.mv_soft_upper, mvs, np.inf)))


class BenefitInput(PreviewInput):
    """Artifact, limits, settings and an economic objective for a benefit report."""

    artifact_id: str = Field(min_length=1, max_length=128, pattern=ID_PATTERN)
    controller_id: str = Field(min_length=1, max_length=128)
    limits: LimitInput
    settings: SettingInput = Field(default_factory=SettingInput)
    economics: EconomicsInput
    steps: int = Field(default=150, ge=10, le=300)
    targets: list[Finite] = Field(default_factory=list, max_length=MAX_VARIABLES)


def artifact_directory(root: Path, artifact_id: str) -> Path:
    """Resolve a model id inside the MPC model store, refusing symlink escapes."""
    directory = (root / "_mpc" / "models").resolve()
    candidate = directory / artifact_id
    for path in (candidate, candidate / "manifest.json", candidate / "model.json"):
        if not path.resolve().is_relative_to(directory):
            raise HTTPException(status_code=422, detail="artifact_outside_model_store")
    if not candidate.is_dir():
        raise HTTPException(status_code=404, detail="unknown_ident_model")
    return candidate


def catalogue_variables(root: Path, controller_id: str) -> list[dict[str, Any]]:
    """Read a controller's variables; missing catalogue data is an explicit refusal."""
    try:
        site = load_site(root)
    except SiteError as error:
        raise HTTPException(status_code=409, detail="no_site") from error
    controller = next((row for row in site.get("controllers", [])
                       if row["id"] == controller_id), None)
    if controller is None:
        raise HTTPException(status_code=404, detail="unknown_controller")
    return list(controller["variables"])


def bound_pid_tunings(variables: list[dict[str, Any]],
                      body: SimulationInput) -> tuple[PidTuning, ...]:
    """Require one declared PID snapshot per MV, in catalogue MV order."""
    loops = [row.get("binding", {}).get("loop") for row in variables if row["role"] == "MV"]
    if loops != [row.loop_id for row in body.pid_tunings]:
        raise ValueError("Provide one current PID snapshot per catalogue MV loop, in MV order")
    if len(loops) != len(body.limits.mv_lower):
        raise ValueError("MV limits must match the catalogue MV loops")
    return tuple(PidTuning(row.kp, row.ti_s, row.td_s, row.cv_index)
                 for row in body.pid_tunings)


def validate_preview_size(variables: list[dict[str, Any]], body: SimulationInput) -> None:
    """Bound dense solver memory and total work before starting a preview."""
    outputs = sum(row["role"] in ("CV", "ICV") for row in variables)
    predicted = outputs * body.settings.prediction_horizon
    moves = len(body.pid_tunings) * body.settings.move_horizon
    if predicted > MAX_PREDICTED_VALUES or moves > MAX_MOVE_VALUES:
        raise ValueError("Reduce horizons or variable count for an interactive preview")
    if predicted * body.scenario.steps > MAX_PREVIEW_VALUES:
        raise ValueError("Reduce experiment length or prediction horizon for a preview")


def validate_model_names(names: tuple[str, ...], variables: list[dict[str, Any]]) -> None:
    """Match ordered model channels to variable ids or their explicit catalogue bindings."""
    if len(names) != len(variables):
        raise ValueError("Model channels must match the catalogue variable count")
    for name, variable in zip(names, variables, strict=True):
        identities = {variable["id"], *variable.get("binding", {}).values()}
        if name not in identities:
            raise ValueError(f"Model channel {name!r} does not match variable {variable['id']!r}")


def load_preview_controller(root: Path, body: SimulationInput,
                            variables: list[dict[str, Any]]) -> Controller:
    """Verify artifact identity, ordering and dimensions before constructing the controller."""
    model = load_ident_model(artifact_directory(root, body.artifact_id))
    plant = model.to_mpc_model()
    if plant.gains.shape[0] > MAX_VARIABLES or plant.gains.shape[1] > MAX_VARIABLES:
        raise ValueError("Preview models support at most eight outputs and eight inputs")
    outputs = [row for row in variables if row["role"] in ("CV", "ICV")]
    inputs = [row for role in ("MV", "DV") for row in variables if row["role"] == role]
    validate_model_names(model.cv_names, outputs)
    validate_model_names(model.input_names, inputs)
    limits = Limits(**{name: np.asarray(value) for name, value in body.limits.model_dump().items()})
    return Controller(plant, limits, Settings(**body.settings.model_dump()))


def run_preview(root: Path, body: SimulationInput) -> dict[str, Any]:
    """Load a verified model, validate catalogue dimensions and run without persistence."""
    variables = catalogue_variables(root, body.controller_id)
    validate_preview_size(variables, body)
    controller = load_preview_controller(root, body, variables)
    result = simulate(controller, bound_pid_tunings(variables, body),
                      Scenario(**body.scenario.model_dump()))
    names = {"cv_names": [row["id"] for row in variables if row["role"] in ("CV", "ICV")],
             "mv_names": [row["id"] for row in variables if row["role"] == "MV"]}
    return {**result, **names, "pid_source": "entered_snapshot"}


def run_benefit(root: Path, body: BenefitInput) -> dict[str, Any]:
    """Run the economic against the tracking MPC on a verified model; nothing is persisted."""
    variables = catalogue_variables(root, body.controller_id)
    outputs = sum(row["role"] in ("CV", "ICV") for row in variables)
    movers = sum(row["role"] == "MV" for row in variables)
    if outputs * body.settings.prediction_horizon > MAX_PREDICTED_VALUES or             movers * body.settings.move_horizon > MAX_MOVE_VALUES or             outputs * body.settings.prediction_horizon * body.steps * 2 > 2 * MAX_PREVIEW_VALUES:
        raise ValueError("Reduce experiment length, horizons or variable count for a preview")
    shell = SimulationInput(artifact_id=body.artifact_id, controller_id=body.controller_id,
                            limits=body.limits, settings=body.settings,
                            pid_tunings=[PidInput(loop_id="-", kp=1.0, ti_s=1.0)])
    controller = load_preview_controller(root, shell, variables)
    controller = replace(controller, economics=body.economics.build())
    result = simulate_benefit(controller, BenefitScenario(body.steps, tuple(body.targets)))
    names = {"cv_names": [row["id"] for row in variables if row["role"] in ("CV", "ICV")],
             "mv_names": [row["id"] for row in variables if row["role"] == "MV"]}
    return {**result, **names}


def build_simulation_router(root: Path) -> APIRouter:
    """Build the read-only simulation preview endpoint, accessible with gw.view."""
    router = APIRouter()

    @router.post("/mpc/simulate")
    def preview(body: SimulationInput, actor: ActorDep) -> dict[str, Any]:
        """Compare controllers on the model without contacting a gateway or writing files."""
        actor.require("gw.view")
        try:
            return run_preview(root, body)
        except (ArtifactError, ValueError, KeyError, TypeError, OSError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/mpc/simulate/benefit")
    def benefit(body: BenefitInput, actor: ActorDep) -> dict[str, Any]:
        """Economic against setpoint-tracking MPC on the model: value per hour, binding limits."""
        actor.require("gw.view")
        try:
            return run_benefit(root, body)
        except (ArtifactError, ValueError, KeyError, TypeError, OSError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return router
