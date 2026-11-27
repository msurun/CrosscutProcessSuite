"""Online soft sensor: one cycle at a time, with lab bias, validity status and backup failover.

Pure logic for the runtime job (#157). Each ``tick`` receives the good, fresh input values of
this cycle, builds the lagged feature row from a short bin buffer, predicts with the stored PLS
model, folds in lab results that have been reported (stamp + report delay <= now), and returns
the published output. Modes: shadow (never used downstream), backup (used only while the
physical instrument it backs is bad or stale; hysteresis from backup.py) and primary.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import numpy as np

from crosscut_softsensor.backup import BACKUP, MEASURED, _step, invalid_reasons
from crosscut_softsensor.bias import BiasTracker
from crosscut_softsensor.config import SoftSensorConfig
from crosscut_softsensor.pls import PlsModel
from crosscut_softsensor.reference import build_model_features, lag_gap

MODES = ("off", "shadow", "backup", "primary")
EVENT_LIMIT = 200  # failover events kept in the state
ESTIMATE_KEEP_S = 6 * 3600.0  # estimate history kept beyond the lab report delay
STAMP_MEANINGS = ("sample", "start", "middle", "end")


def stamp_offset(meaning: str, window_s: float) -> float:
    """Seconds to add to a lab stamp to get the sample time (composite window of ``window_s``).

    A stamp at the start of a composite means the sample centre is window/2 later; at the end,
    window/2 earlier (same convention as alignment.py).
    """
    if meaning not in STAMP_MEANINGS:
        raise ValueError(f"stamp meaning must be one of {list(STAMP_MEANINGS)}")
    return {"start": window_s / 2, "end": -window_s / 2}.get(meaning, 0.0)


def _utc(t_s: float) -> str:
    """ISO UTC instant of epoch seconds."""
    return datetime.fromtimestamp(t_s, UTC).isoformat()


def _finite(value: float | None) -> float | None:
    """None for NaN/inf/None, else the float (JSON-safe)."""
    return None if value is None or not math.isfinite(value) else float(value)


class OnlineSensor:
    """State and one-cycle logic of a soft sensor running online."""

    def __init__(self, config: SoftSensorConfig, model: PlsModel) -> None:
        """Bind the configuration and fitted model; start with empty buffers."""
        bc = config.bias_correction
        self.config, self.model = config, model
        self.tracker = BiasTracker(model.cv_sigma, bc.weight, bc.k_sigma, bc.consecutive)
        self.buffer: dict[int, dict[str, float]] = {}
        self.estimates: list[list[float]] = []  # [t_s, raw estimate]
        self.lab_watermark = -math.inf  # last processed lab stamp
        self.last_lab: dict[str, Any] | None = None
        self.instrument = MEASURED
        self.valid_since: float | None = None
        self.history: list[list[float]] = []  # [t_s, measured, flag] for frozen detection
        self.events: list[dict[str, Any]] = []

    # -- cycle -----------------------------------------------------------------------------
    def tick(
        self, now_s: float, values: dict[str, float], problems: dict[str, str], mode: str
    ) -> dict[str, Any]:
        """One cycle: ``values`` are good fresh tags, ``problems`` maps unusable tags to reasons."""
        estimate, validity = self._predict(now_s, values)
        raw = _finite(estimate)
        if raw is not None:
            self.estimates.append([now_s, raw])
        self._prune(now_s)
        bias = self.tracker.state.bias_ewma
        corrected = None if raw is None else raw + (0.0 if math.isnan(bias) else bias)
        status, reason = self._status(validity, problems, now_s)
        output = {"t_utc": _utc(now_s), "status": status, "reason": reason, "estimate": raw,
                  "bias": _finite(bias), "drift": self.tracker.state.drift,
                  "effective_mode": mode, "corrected": corrected}
        return self._publish(output, now_s, values, problems, mode)

    def _predict(self, now_s: float, values: dict[str, float]) -> tuple[float, str]:
        """Update the bin buffer and predict from the newest feature row."""
        period, gap = self.config.sample_period_s, lag_gap(self.config)
        current = int(now_s // period)
        self.buffer.setdefault(current, {}).update(values)
        for stale in [b for b in self.buffer if b < current - gap]:
            del self.buffer[stale]
        tags = [*self.config.input_tags, *(r.tag for r in self.config.reference_inputs)]
        columns = {tag: np.array([self.buffer.get(b, {}).get(tag, math.nan)
                                  for b in range(current - gap, current + 1)]) for tag in tags}
        x = build_model_features(columns, self.config).x[-1:]
        return float(self.model.predict(x)[0]), self.model.validity(x)[0]

    def _prune(self, now_s: float) -> None:
        """Drop estimates older than the lab report delay plus a margin."""
        floor = now_s - self.config.lab_delay_s - ESTIMATE_KEEP_S
        self.estimates = [e for e in self.estimates if e[0] >= floor]

    def _status(self, validity: str, problems: dict[str, str], now_s: float) -> tuple[str, str]:
        """Status good/uncertain/bad and the reason for this cycle."""
        if validity == "missing_input":
            if problems:
                return "bad", ";".join(f"{tag}:{why}" for tag, why in sorted(problems.items()))
            return "bad", "warming_up" if self._warming(now_s) else "missing_input"
        if validity != "ok":
            return "uncertain", validity
        if self.tracker.state.drift:
            return "uncertain", "lab_bias_drift"
        return "good", ""

    def _warming(self, now_s: float) -> bool:
        """True while the buffer does not yet span the longest lag."""
        oldest = min(self.buffer, default=int(now_s // self.config.sample_period_s))
        return int(now_s // self.config.sample_period_s) - oldest < lag_gap(self.config)

    # -- lab -------------------------------------------------------------------------------
    def apply_labs(
        self, now_s: float, labs: list[tuple[float, float]], offset_s: float = 0.0
    ) -> None:
        """Fold in lab results reported by now (stamp + report delay); each result only once."""
        for stamp, value in sorted(labs):
            if stamp <= self.lab_watermark or stamp + self.config.lab_delay_s > now_s:
                continue
            sample_t = stamp + offset_s
            partner = self._estimate_at(sample_t)
            self.tracker.update(sample_t, value, math.nan if partner is None else partner)
            self.lab_watermark = stamp
            if partner is not None:
                self.last_lab = {"sample_utc": _utc(sample_t), "lab": float(value),
                                 "estimate": partner, "residual": float(value) - partner}

    def _estimate_at(self, t_s: float) -> float | None:
        """Raw estimate of the nearest cycle at or before ``t_s`` (no lab leakage), else None."""
        earlier = [e for e in self.estimates if e[0] <= t_s]
        return earlier[-1][1] if earlier else None

    # -- publish and failover --------------------------------------------------------------
    def _publish(
        self, out: dict[str, Any], now_s: float, values: dict[str, float],
        problems: dict[str, str], mode: str,
    ) -> dict[str, Any]:
        """Choose the published value for the mode; backup mode runs the failover machine."""
        soft = out.pop("corrected")
        measured = values.get(self.config.backup.measured_tag) if self.config.backup else None
        if mode == "backup" and self.config.backup is not None:
            self._failover(now_s, values, problems)
            use_soft = self.instrument == BACKUP
            if not use_soft:
                return {**out, "value": measured, "source": "instrument", "status": "good",
                        "reason": "", "used_downstream": False}
        else:
            self.instrument, self.valid_since = MEASURED, None
            use_soft = mode == "primary"
        source = "softsensor" if soft is not None else "none"
        return {**out, "value": soft, "source": source, "used_downstream": use_soft}

    def _failover(self, now_s: float, values: dict[str, float], problems: dict[str, str]) -> None:
        """Advance the instrument state with the validity checks and hysteresis of backup.py."""
        cfg = self.config.backup
        assert cfg is not None
        measured = values.get(cfg.measured_tag, math.nan)
        flag = values.get(cfg.flag_tag, math.nan) if cfg.flag_tag else 0.0
        self.history = [h for h in self.history if now_s - h[0] <= cfg.frozen_s + 1.0]
        self.history.append([now_s, measured, flag])
        rows = np.array(self.history)
        reasons = invalid_reasons(rows[:, 1], rows[:, 2] if cfg.flag_tag else None, rows[:, 0], cfg)
        reason = problems.get(cfg.measured_tag, reasons[-1])
        previous = self.instrument
        self.instrument, self.valid_since, why = _step(
            self.instrument, self.valid_since, now_s, reason, cfg.return_hold_s)
        if self.instrument != previous:
            names = {MEASURED: "instrument", BACKUP: "softsensor"}
            self.events.append({"t_utc": _utc(now_s), "from": names[previous],
                                "to": names[self.instrument], "reason": why})
            del self.events[:-EVENT_LIMIT]

    # -- persistence -----------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dynamic state (the model and configuration are reloaded from files)."""
        return {
            "tracker": self.tracker.to_dict(),
            "buffer": {str(b): v for b, v in self.buffer.items()},
            "estimates": self.estimates, "lab_watermark": _finite(self.lab_watermark),
            "last_lab": self.last_lab, "instrument": self.instrument,
            "valid_since": self.valid_since, "history": self.history, "events": self.events,
        }

    def load_state(self, doc: dict[str, Any]) -> None:
        """Restore the dynamic state written by ``to_dict`` (a restart keeps bias and events)."""
        self.tracker = BiasTracker.from_dict(doc["tracker"])
        self.buffer = {int(b): dict(v) for b, v in doc["buffer"].items()}
        self.estimates, self.last_lab = doc["estimates"], doc["last_lab"]
        mark = doc["lab_watermark"]
        self.lab_watermark = -math.inf if mark is None else float(mark)
        self.instrument, self.valid_since = doc["instrument"], doc["valid_since"]
        self.history, self.events = doc["history"], doc["events"]
