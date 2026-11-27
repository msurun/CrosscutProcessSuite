"""Tests for loop KPIs per operating mode and the exclusion of stopped samples (#146)."""

import math
from typing import Any

from crosscut_runtime.jobs.loop_kpi import LoopKpiJob

N = 400
SITE = {
    "equipment": [{"id": "mill", "level": "equipment", "loops": ["FIC"],
                   "running": {"tag": "RUN", "above": 0.5, "confirmed": True}}],
    "modes": [
        {"id": "stopped", "condition": {"clauses": [{"tag": "SPEED", "op": "<", "value": 1}]}},
        {"id": "high", "condition": {"clauses": [{"tag": "FEED", "op": ">", "value": 150}]}},
        {"id": "normal", "condition": {"clauses": [{"tag": "FEED", "op": ">", "value": 50}]}},
    ],
}
LOOP = {"id": "FIC", "pv": "pv", "sp": "sp", "out": "out", "mode": "mode"}
JOB = {"id": "j", "kind": "loop_kpi", "source": "s", "loops": ["FIC"], "period_s": 1.0,
       "window_s": 3600.0, "enabled": True}


def _job(site: dict[str, Any], feed: list[float], speed: list[float],
         run: list[float] | None = None) -> LoopKpiJob:
    """A job whose window holds N samples: PV oscillates, OUT mid-range, loop in AUTO."""
    job = LoopKpiJob(JOB, {"FIC": LOOP}, connector=None, site=site)
    for i in range(N):
        pv = 50.0 + 5.0 * math.sin(2 * math.pi * i / 60.0)
        values = {"pv": pv, "sp": 50.0, "out": 40.0 + i % 3, "mode": 1.0, "FEED": feed[i],
                  "SPEED": speed[i], "RUN": 1.0 if run is None else run[i]}
        for tag, value in values.items():
            job.window.add(tag, float(i), value)
    return job


def _kpi(job: LoopKpiJob) -> dict[str, Any] | None:
    return job._loop_kpi(LOOP, {c: c for c in ("pv", "sp", "out", "mode")})


def test_kpi_is_kept_per_mode_and_headline_is_current_mode() -> None:
    """Two modes with enough samples give two KPIs; the headline is the newest sample's mode."""
    feed = [100.0] * 200 + [200.0] * 200
    kpi = _kpi(_job(SITE, feed, [5.0] * N))
    assert kpi is not None
    assert set(kpi["by_mode"]) == {"normal", "high"}
    assert kpi["mode"] == "high" and kpi["kpi_scope"] == "mode"
    assert kpi["n_samples"] == kpi["by_mode"]["high"]["n_samples"] == 200
    assert kpi["excluded_samples"] == 0


def test_stopped_samples_are_excluded() -> None:
    """Samples in mode stopped or with the running signal false never reach a KPI."""
    speed = [0.0] * 100 + [5.0] * 300
    kpi = _kpi(_job(SITE, [100.0] * N, speed))
    assert kpi is not None
    assert "stopped" not in kpi["by_mode"]
    assert kpi["excluded_samples"] == 100 and kpi["n_samples"] == 300
    off = _kpi(_job(SITE, [100.0] * N, [5.0] * N, [0.0] * 100 + [1.0] * 300))
    assert off is not None and off["excluded_samples"] == 100


def test_currently_stopped_has_no_kpi_and_thin_mode_falls_back() -> None:
    """A stopped newest sample gives no KPI; a mode below the threshold uses all running."""
    assert _kpi(_job(SITE, [100.0] * N, [5.0] * 399 + [0.0])) is None
    feed = [100.0] * 380 + [200.0] * 20
    kpi = _kpi(_job(SITE, feed, [5.0] * N))
    assert kpi is not None and kpi["mode"] == "high" and kpi["kpi_scope"] == "all_running"


def test_without_modes_the_kpi_is_unchanged() -> None:
    """No catalogue modes: no mode keys, so live equals offline as before."""
    kpi = _kpi(_job({}, [100.0] * N, [5.0] * N))
    assert kpi is not None and "by_mode" not in kpi and kpi["n_samples"] == N
