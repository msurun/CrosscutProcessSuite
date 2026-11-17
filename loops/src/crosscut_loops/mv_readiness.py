"""Readiness of a base loop to serve as a manipulated variable (MV) of an APC controller.

Pure function over the live loop-KPI row (the dict that runtime ``loop_kpi.kpi_from_series``
produces, with the optional monitor fields ``flatline_fraction`` and ``stiction_advice``) and an
optional valve row. Not to be confused with ``readiness.py`` (historian export readiness).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Defaults are starting points, not plant constants: a site passes its own values.
DEFAULT_MAX_SATURATION = 0.2  # share of the window with OUT at a limit, 0..1
DEFAULT_MAX_FLATLINE = 0.5  # share of the window with PV not moving, 0..1
DEFAULT_MIN_SERVICE_FACTOR = 0.5  # share of the window in AUTO with valid data, 0..1
STICTION_TEST_ADVICE = "test_valve"  # monitor stiction_advice that flags the valve


def _fraction(row: Mapping[str, Any], key: str) -> float | None:
    """Return row[key] as a float, or None when absent or not a number (unknown, not bad)."""
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def _above(row: Mapping[str, Any], key: str, limit: float) -> bool:
    """True when the row has a known value for key that is above limit."""
    value = _fraction(row, key)
    return value is not None and value > limit


def _is_manual(row: Mapping[str, Any], min_service_factor: float) -> bool:
    """True when the loop was not in automatic mode for enough of the window."""
    if row.get("classification") == "manual":
        return True
    service = _fraction(row, "service_factor")
    return service is not None and service < min_service_factor


def _valve_suspect(kpi_row: Mapping[str, Any], valve_row: Mapping[str, Any] | None) -> bool:
    """True when the valve row (else the KPI row) advises a valve test."""
    source = valve_row if valve_row is not None else kpi_row
    return source.get("stiction_advice") == STICTION_TEST_ADVICE


def loop_readiness(
    kpi_row: Mapping[str, Any],
    valve_row: Mapping[str, Any] | None = None,
    *,
    max_saturation: float = DEFAULT_MAX_SATURATION,
    max_flatline: float = DEFAULT_MAX_FLATLINE,
    min_service_factor: float = DEFAULT_MIN_SERVICE_FACTOR,
) -> dict[str, Any]:
    """Decide whether a loop may serve as an MV; return ``{"ready": bool, "reasons": [...]}``.

    Reasons: ``saturated`` (``saturation_fraction`` above ``max_saturation``), ``pv_frozen``
    (``flatline_fraction`` above ``max_flatline``), ``manual`` (classification "manual" or
    ``service_factor`` below ``min_service_factor``) and ``valve`` (``stiction_advice`` equals
    "test_valve" in ``valve_row``, or in ``kpi_row`` without one). A missing or None field is
    unknown and never counts as a reason; fractions are 0..1.
    """
    checks = (
        ("manual", _is_manual(kpi_row, min_service_factor)),
        ("saturated", _above(kpi_row, "saturation_fraction", max_saturation)),
        ("pv_frozen", _above(kpi_row, "flatline_fraction", max_flatline)),
        ("valve", _valve_suspect(kpi_row, valve_row)),
    )
    reasons = [name for name, failed in checks if failed]
    return {"ready": not reasons, "reasons": reasons}
