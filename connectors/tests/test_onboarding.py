"""Tests for module onboarding and readiness checks (Phase 1, #39).

Verifies exit criteria from Phase 1 plan:
1. Clean synthetic dataset reports all green (ok).
2. Dataset with missing OUT reports Loop amber (warning).
3. Dataset with no target reports Soft Sensor red (not_ready) with clear reason.
4. Custom site catalogue readiness thresholds are applied.
"""

from __future__ import annotations

import numpy as np
from crosscut_connectors.onboarding import (
    VERDICT_NOT_READY,
    VERDICT_OK,
    VERDICT_WARNING,
    config_from_site,
    evaluate_dataset_readiness,
)
from crosscut_loops.overview import LoopTags


def _clean_dataset() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Generate 30 h of clean synthetic 10 s data for all module tags."""
    t_s = np.arange(0.0, 30 * 3600.0, 10.0)
    rng = np.random.default_rng(42)
    cols = {
        "FIC101.PV": 50.0 + rng.normal(0, 0.1, len(t_s)),
        "FIC101.SP": np.full(len(t_s), 50.0),
        "FIC101.OUT": 45.0 + rng.normal(0, 0.2, len(t_s)),
        "FIC101.MODE": np.full(len(t_s), 1.0),
        "FEED_RATE": 100.0 + rng.normal(0, 0.5, len(t_s)),
        "DENSITY": 1.4 + rng.normal(0, 0.02, len(t_s)),
        "PRODUCT_CONC": 80.0 + rng.normal(0, 0.3, len(t_s)),
    }
    return t_s, cols


def _site_doc() -> dict[str, object]:
    """Complete site catalogue document matching the clean dataset."""
    tag_names = ("FIC101.PV", "FIC101.SP", "FIC101.OUT", "FEED_RATE", "DENSITY", "PRODUCT_CONC")
    return {
        "schema_version": 1,
        "site": {"name": "Synthetic Clean Plant"},
        "tags": [{"id": k} for k in tag_names],
        "signals": [
            {"tag": "FIC101.PV", "role": "pv", "loop": "FIC101"},
            {"tag": "FIC101.SP", "role": "sp", "loop": "FIC101"},
            {"tag": "FIC101.OUT", "role": "out", "loop": "FIC101"},
            {"tag": "FEED_RATE", "role": "input"},
            {"tag": "DENSITY", "role": "input"},
            {"tag": "PRODUCT_CONC", "role": "target"},
        ],
        "loops": [{"id": "FIC101", "pv": "FIC101.PV", "sp": "FIC101.SP", "out": "FIC101.OUT"}],
        "labs": [{"tag": "PRODUCT_CONC", "stamp": {"meaning": "end"}}],
        "readiness": {
            "min_duration_h": 6.0,
            "warn_duration_h": 24.0,
        },
    }


def _make_loop(out: str = "FIC101.OUT") -> LoopTags:
    return LoopTags("FIC101", "FIC101.PV", "FIC101.SP", out, "FIC101.MODE", "%", 0.0, 100.0)


def test_clean_dataset_reports_all_green() -> None:
    t_s, columns = _clean_dataset()
    site = _site_doc()
    loops = [_make_loop()]

    res = evaluate_dataset_readiness("ds1", t_s, columns, loops, site)

    assert res.verdict == VERDICT_OK
    assert res.modules["loops"].status == VERDICT_OK
    assert res.modules["anomaly"].status == VERDICT_OK
    assert res.modules["softsensor"].status == VERDICT_OK


def test_missing_out_reports_loop_amber() -> None:
    t_s, columns = _clean_dataset()
    site = _site_doc()
    # Loop defined without OUT tag (monitoring only)
    loops = [_make_loop(out="")]

    res = evaluate_dataset_readiness("ds1", t_s, columns, loops, site)

    assert res.modules["loops"].status == VERDICT_WARNING
    assert any("no OUT tag mapped" in r for r in res.modules["loops"].reasons)
    # Overall dataset verdict becomes warning
    assert res.verdict == VERDICT_WARNING


def test_no_target_reports_softsensor_red_with_reason() -> None:
    t_s, columns = _clean_dataset()
    site = _site_doc()
    # Remove target role from signals
    site["signals"] = [s for s in site["signals"] if s.get("role") != "target"]
    loops = [_make_loop()]

    res = evaluate_dataset_readiness("ds1", t_s, columns, loops, site)

    assert res.modules["softsensor"].status == VERDICT_NOT_READY
    assert any("No target tag mapped" in r for r in res.modules["softsensor"].reasons)
    assert res.verdict == VERDICT_NOT_READY


def test_custom_site_readiness_thresholds() -> None:
    site = {
        "readiness": {
            "min_duration_h": 12.0,
            "warn_duration_h": 48.0,
            "max_sample_period_s": 30.0,
        }
    }
    cfg = config_from_site(site)
    assert cfg.min_duration_h == 12.0
    assert cfg.warn_duration_h == 48.0
    assert cfg.max_sample_period_s == 30.0
