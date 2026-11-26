"""Expose the pure Python reference MPC API for linear-plant L1 tests.

Runtime host and gateway integration belong to the later Phase 7.3 stage.
"""

from .artifact import IdentModelIntegrityError, load_ident_model, save_ident_model
from .config import Controller, Limits, Settings
from .engine import ControllerState, Result, cycle, initialise
from .identification import (
    Dataset,
    IdentificationRejected,
    IdentifiedModel,
    PairSpec,
    identify_mimo,
)
from .model import FopdtModel, ModelState, advance, initial_model_state
from .planning import CycleInputs, steady_target

__all__ = [
    "Dataset", "IdentModelIntegrityError", "IdentificationRejected", "IdentifiedModel", "PairSpec",
    "identify_mimo", "load_ident_model", "save_ident_model",
    "Controller", "ControllerState", "CycleInputs", "FopdtModel", "Limits", "ModelState",
    "Result", "Settings", "advance", "cycle", "initial_model_state", "initialise", "steady_target",
]
