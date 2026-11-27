"""Instantiate preset structures over role-ordered engineering-unit features.

Physics transforms are explicit public equations or labelled calibration proxies;
no expression strings are executed and integration is supplied as a causal feature.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from crosscut_softsensor.config import SoftSensorConfig
from crosscut_softsensor.pls import PlsModel, fit_pls
from crosscut_softsensor.structures import (
    GradientBoostingStructure,
    HybridStructure,
    PhysicsStructure,
    RidgeStructure,
    Structure,
)

SECONDS_PER_HOUR = 3600.0  # Converts kW/kPa = m3/s to m3/h.
WATER_DENSITY_KG_M3 = 1000.0  # Reference water density for the mixture balance.
KPA_PER_BAR = 100.0  # Valve flow coefficient is referenced to one bar pressure drop.


def _positive_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """Return a ratio, marking nonpositive denominators invalid."""
    result = np.full(numerator.shape, np.nan)
    np.divide(numerator, denominator, out=result, where=denominator > 0)
    return result


def _belt(values: np.ndarray) -> np.ndarray:
    """Net drive power in kW, a calibrated mass-flow proxy while the belt runs."""
    # P_net = force * speed: for fixed conveyor geometry force scales with load.
    # Mass flow is belt load times speed, so net kW scales with t/h, not load alone.
    return np.where(values[:, 2] > 0, values[:, 0] - values[:, 1], np.nan)


def _pump(values: np.ndarray) -> np.ndarray:
    """Ideal hydraulic flow in m3/h; fitted gain represents efficiency."""
    # Q = P / delta_p. Rows contain [motor kW, discharge kPa, suction kPa, rpm].
    flow = SECONDS_PER_HOUR * _positive_ratio(values[:, 0], values[:, 1] - values[:, 2])
    return np.where(values[:, 3] > 0, flow, np.nan)


def _valve(values: np.ndarray) -> np.ndarray:
    """Incompressible valve flow in m3/h from a supplied position-specific coefficient."""
    # Q = Kv * sqrt(delta_p_bar / SG); cv_curve is the supplied m3/h coefficient.
    relative_density = values[:, 3] / WATER_DENSITY_KG_M3
    pressure_bar = (values[:, 1] - values[:, 2]) / KPA_PER_BAR
    ratio = _positive_ratio(pressure_bar, relative_density)
    return values[:, 0] * np.sqrt(np.where(ratio >= 0, ratio, np.nan))


def _slurry(values: np.ndarray) -> np.ndarray:
    """Dry solids flow in t/h from volume flow, bulk density and solids specific gravity."""
    # Mixture balance: solids kg/m3 = (rho_mix-rho_water)/(1-1/SG_solids).
    inverse_gravity = _positive_ratio(np.ones(len(values)), values[:, 2])
    density = _positive_ratio(values[:, 1] - WATER_DENSITY_KG_M3, 1 - inverse_gravity)
    density_valid = (values[:, 1] >= WATER_DENSITY_KG_M3) & (
        values[:, 1] <= values[:, 2] * WATER_DENSITY_KG_M3
    )
    flow = values[:, 0] * density / WATER_DENSITY_KG_M3
    return np.where(density_valid & (values[:, 0] >= 0), flow, np.nan)


def _cyclone(values: np.ndarray) -> np.ndarray:
    """Return an ASSUMPTION pressure-loading proxy, not the full Plitt correlation."""
    # Proxy = (flow / open cyclones) / sqrt(pressure); gain supplies target um units.
    loading = _positive_ratio(values[:, 0], values[:, 1])
    return _positive_ratio(loading, np.sqrt(np.where(values[:, 2] > 0, values[:, 2], np.nan)))


def _inventory(values: np.ndarray) -> np.ndarray:
    """Return preintegrated net mass in tonnes, independent of fit/predict batch boundaries."""
    # The upstream causal feature is integral((in-out) dt / 3600), with flows in t/h.
    # Reintegrating sparse fold rows would omit intervening process samples and leak state.
    return values[:, 0]


FORMULAS = {
    "belt_net_power": _belt,
    "pump_hydraulic_power": _pump,
    "valve_incompressible": _valve,
    "slurry_mass_balance": _slurry,
    "cyclone_loading_proxy": _cyclone,
    "integrated_net_mass": _inventory,
}


def physics_formula(
    preset: Mapping[str, Any], feature_names: Sequence[str]
) -> Callable[[np.ndarray], np.ndarray]:
    """Bind a preset-declared transform to role columns; missing roles raise ValueError."""
    specification = preset["model"].get("physics")
    if specification is None or specification["formula"] not in FORMULAS:
        raise ValueError(f"{preset['key']}: declare a supported model.physics formula")
    missing = set(specification["roles"]) - set(feature_names)
    if missing:
        raise ValueError(f"{preset['key']}: supply physics feature roles {sorted(missing)}")
    columns = [feature_names.index(role) for role in specification["roles"]]
    transform = FORMULAS[specification["formula"]]
    return lambda values: transform(values[:, columns])


class PlsStructure:
    """Adapt existing PLS to fit/predict on (samples, features) arrays in declared units."""

    def __init__(self, feature_names: Sequence[str]) -> None:
        """Retain role column order without generating additional lag columns."""
        self.config = SoftSensorConfig(
            id="preset", target_tag="target", input_tags=tuple(feature_names), lags_s=(0.0,)
        )
        self.model: PlsModel | None = None

    def fit(self, x: np.ndarray, y: np.ndarray) -> PlsStructure:
        """Fit PLS on labelled training rows; predictions retain target units."""
        self.model = fit_pls(x, y, self.config)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Return one estimate per row, raising before calibration."""
        if self.model is None:
            raise ValueError("Fit the PLS structure before predicting")
        return self.model.predict(x)


def create_structure(
    preset: Mapping[str, Any], name: str, feature_names: Sequence[str]
) -> Structure:
    """Build an allowed structure; X columns follow feature_names, y has target units."""
    if name not in preset["model"]["allowed_now"]:
        raise ValueError(f"{preset['key']}: structure {name!r} is not allowed")
    if name == "ridge":
        return RidgeStructure()
    if name == "gradient_boosting":
        return GradientBoostingStructure()
    if name == "pls":
        return PlsStructure(feature_names)
    formula = physics_formula(preset, feature_names)
    if name == "physics_template":
        return PhysicsStructure(formula)
    if name == "hybrid":
        return HybridStructure(formula)
    raise ValueError(f"{preset['key']}: unsupported structure {name!r}")
