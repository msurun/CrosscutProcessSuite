"""Score live equipment models and persist explainable operator alarm events.

Per-equipment sequential state provides ISA-18.2 persistence and clearing hysteresis.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crosscut_anomaly.equipment_learning import EWMA_LIMIT, EquipmentModel, score

from crosscut_runtime.jobs import backfill

PERSISTENCE_CYCLES = 3  # Consecutive abnormal eligible samples before opening.
CLEAR_CYCLES = 5  # Consecutive normal eligible samples before closing.
BACKFILL_WINDOW_S = 3600.0  # Seconds of history used on startup or after a gap.
TOP_CONTRIBUTIONS = 5  # Maximum number of explanatory measurement tags.
GOOD_QUALITY = 0  # Connector code for a measurement safe to score.


@dataclass
class EquipmentState:
    """Keep one equipment model, hysteresis counters and its currently open event."""

    model: EquipmentModel
    document: str
    abnormal: int = 0
    normal: int = 0
    event: dict | None = None
    latest_s: float | None = None
    history: dict[float, dict[str, float]] = field(default_factory=dict)


def _utc(epoch_s: float) -> str:
    """Format epoch seconds as an aware UTC instant."""
    return datetime.fromtimestamp(epoch_s, UTC).isoformat()


def _severity(model: EquipmentModel, result: dict) -> float:
    """Return the largest dimensionless statistic divided by its alarm limit."""
    ratios = [abs(value) / EWMA_LIMIT for value in result.get("ewma", {}).values()]
    if model.pca is not None:
        for statistic in ("t2", "spe"):
            value = result.get(statistic)
            limit = getattr(model.pca, f"{statistic}_limit")
            if value is not None:
                ratios.append(value / limit if limit > 0 else float(value > 0) * 2)
    return max(ratios, default=0.0)


def _contributions(result: dict) -> list[dict]:
    """Rank tags by the larger PCA contribution share across T2 and SPE."""
    shares: dict[str, float] = {}
    for statistic in result.get("contributions", {}).values():
        for tag, share in statistic.items():
            shares[tag] = max(shares.get(tag, 0.0), float(share))
    ranked = sorted(shares.items(), key=lambda item: item[1], reverse=True)
    return [{"tag": tag, "share": share} for tag, share in ranked[:TOP_CONTRIBUTIONS]]


def _residuals(result: dict) -> list[dict]:
    """Explain residual departures in training standard deviations with EWMA trend sign."""
    return [{"tag": tag, "z": value,
             "trend": int(result.get("ewma", {}).get(tag, value) > 0)
             - int(result.get("ewma", {}).get(tag, value) < 0)}
            for tag, value in result.get("residuals", {}).items()]


class EquipmentScanJob:
    """Sample catalogue equipment and retain alarm state between scheduler cycles."""

    def __init__(self, job_doc: dict, site: dict, connector: Any, root: Path) -> None:
        """Bind one job to its catalogue, addressed connector and local data root."""
        self.job_doc = job_doc
        self.site = site
        self.connector = connector
        self.root = Path(root)
        self.clock = time.time
        self.events_path = self.root / "_runtime" / "equipment_events.jsonl"
        self.states: dict[str, EquipmentState] = {}

    def _state(self, equipment_id: str) -> EquipmentState | None:
        """Load new coefficients when their file changes; never reuse a removed model."""
        path = self.root / "_anomaly" / "equipment" / f"{equipment_id}.model.json"
        if not path.is_file():
            self.states.pop(equipment_id, None)
            return None
        document = path.read_text(encoding="utf-8")
        state = self.states.get(equipment_id)
        if state is None or state.document != document:
            model = EquipmentModel.from_dict(json.loads(document))
            model.previous, model.ewma = None, {}
            state = EquipmentState(model, document, event=self._restore_event(equipment_id))
            self.states[equipment_id] = state
        return state if state.model.pca is not None or state.model.regressions else None

    def _restore_event(self, equipment_id: str) -> dict | None:
        """Recover the latest open identity after a service restart without duplicating alarms."""
        if not self.events_path.is_file():
            return None
        revisions = {}
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["equipment"] == equipment_id:
                revisions[event["opened_utc"]] = event
        open_events = [event for event in revisions.values() if event["closed_utc"] is None]
        return max(open_events, key=lambda event: event["opened_utc"], default=None)

    def _shelved(self, equipment_id: str, now_s: float) -> bool:
        """Resolve the operator's UTC shelf expiry on every cycle."""
        path = self.root / "_runtime" / "shelved.json"
        shelves = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        expiry = shelves.get(equipment_id)
        if expiry is None:
            return False
        until = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if until.tzinfo is None:
            raise ValueError("Equipment shelf expiry needs a timezone; save an aware UTC date")
        return until.timestamp() > now_s

    def _append(self, event: dict) -> None:
        """Append an event revision; readers keep the last record for its opening identity."""
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, allow_nan=False) + "\n")

    def _event(self, equipment: dict, result: dict, now_s: float) -> dict:
        """Attach equipment-owned loops whose PV, SP or OUT appears among the top tags."""
        contributions = _contributions(result)
        top_tags = {item["tag"] for item in contributions}
        owned = set(equipment.get("loops", []))
        affected = [loop["id"] for loop in self.site.get("loops", [])
                    if loop["id"] in owned
                    and any(loop.get(role) in top_tags for role in ("pv", "sp", "out"))]
        return {"equipment": equipment["id"], "opened_utc": _utc(now_s), "closed_utc": None,
                "peak": 0.0, "contributions": contributions, "residuals": _residuals(result),
                "loops_affected": affected}

    def _hysteresis(self, state: EquipmentState, context: tuple, result: dict) -> None:
        """Count consecutive excursions and clear samples independently to prevent chatter."""
        equipment, now_s = context
        severity = _severity(state.model, result)
        # Statistics and EWMA are normalized by their limits: a ratio above one is abnormal.
        state.abnormal = state.abnormal + 1 if severity > 1 else 0
        state.normal = state.normal + 1 if severity <= 1 else 0
        persistence = int(self.job_doc.get("persistence", PERSISTENCE_CYCLES))
        if state.event is None and state.abnormal >= persistence:
            state.event = self._event(equipment, result, now_s)
        if state.event is None:
            return
        if severity > state.event["peak"]:
            details = self._event(equipment, result, now_s)
            state.event.update({key: details[key] for key in
                                ("contributions", "residuals", "loops_affected")})
            state.event["peak"] = severity
        if state.normal >= int(self.job_doc.get("clear", CLEAR_CYCLES)):
            state.event["closed_utc"] = _utc(now_s)
        self._append(state.event)
        if state.event["closed_utc"] is not None:
            state.event = None

    def _suppress(self, state: EquipmentState, now_s: float) -> None:
        """Reset continuity across stopped or shelved operation and retire any active event."""
        state.abnormal, state.normal = 0, 0
        state.model.previous, state.model.ewma = None, {}
        if state.event is not None:
            state.event["closed_utc"] = _utc(now_s)
            self._append(state.event)
            state.event = None

    def _cycle(self, equipment: dict, state: EquipmentState, sample: tuple) -> dict:
        """Score one eligible sample, separating stopped and unavailable measurements."""
        row, now_s = sample
        running = equipment.get("running")
        if running and running["tag"] in row and row[running["tag"]] <= running["above"]:
            self._suppress(state, now_s)
            return {"status": "stopped", "open_event": None}
        required = self._tags(equipment, state)
        if any(tag not in row for tag in required):
            state.abnormal, state.normal = 0, 0
            state.model.previous, state.model.ewma = None, {}
            return {"status": "anomaly" if state.event else "ok", "open_event": state.event,
                    "reason": "missing_good_values"}
        result = score(state.model, row)
        self._hysteresis(state, (equipment, now_s), result)
        return {"status": "anomaly" if state.event else "ok", "open_event": state.event,
                "t2": result["t2"], "spe": result["spe"], "ewma": result.get("ewma", {})}

    @staticmethod
    def _tags(equipment: dict, state: EquipmentState) -> list[str]:
        """Include the running tag even when it is outside the learned measurement matrix."""
        tags = list(state.model.variables)
        if equipment.get("running"):
            tags.append(equipment["running"]["tag"])
        return list(dict.fromkeys(tags))

    def _backfill(self, equipment: dict, state: EquipmentState, now_s: float) -> dict | None:
        """Replay aligned GOOD archive samples chronologically on startup and after a gap."""
        if not backfill.has_history(self.connector):
            return None
        period_s = float(self.job_doc.get("period_s", 1.0))
        window_s = float(self.job_doc.get("window_s", BACKFILL_WINDOW_S))
        start_s = backfill.plan(state.latest_s, now_s, window_s, period_s)
        if start_s is None:
            return None
        state.model.previous, state.model.ewma = None, {}
        state.abnormal, state.normal = 0, 0
        tags = self._tags(equipment, state)
        plan = backfill.BackfillPlan(tags, start_s, now_s, period_s)
        filled = backfill.backfill(self.connector, plan,
                                   lambda tag, stamp, value: self._keep(state, tag, (stamp, value)))
        for stamp, row in sorted(state.history.items()):
            is_new = state.latest_s is None or stamp > state.latest_s
            if is_new:
                self._cycle(equipment, state, (row, stamp))
                state.latest_s = stamp
        state.history = {}
        return filled

    @staticmethod
    def _keep(state: EquipmentState, tag: str, sample: tuple) -> None:
        """Collect GOOD archive values by epoch seconds for complete-row alignment."""
        stamp, value = sample
        state.history.setdefault(stamp, {})[tag] = value

    def _scan(self, equipment: dict, now_s: float) -> dict:
        """Read one model's live variables using only GOOD finite connector values."""
        state = self._state(equipment["id"])
        if state is None:
            return {"status": "no_model", "open_event": None}
        if self._shelved(equipment["id"], now_s):
            self._suppress(state, now_s)
            state.latest_s = now_s
            return {"status": "ok", "open_event": None, "shelved": True}
        filled = self._backfill(equipment, state, now_s)
        values = self.connector.read_live(self._tags(equipment, state))
        row = {tag: float(value.value) for tag, value in values.items()
               if value.quality == GOOD_QUALITY and value.value is not None
               and math.isfinite(value.value)}
        result = self._cycle(equipment, state, (row, now_s))
        state.latest_s = now_s
        if filled is not None:
            result["backfill"] = filled
        return result

    def run(self) -> dict[str, Any]:
        """Return current per-equipment status and persist any event transitions."""
        now_s = self.clock()
        catalogue = {item["id"]: item for item in self.site.get("equipment", [])}
        equipment_states = {}
        for equipment_id in self.job_doc["equipment"]:
            if equipment_id not in catalogue:
                raise ValueError(f"Unknown equipment {equipment_id!r}; repair the job catalogue")
            equipment_states[equipment_id] = self._scan(catalogue[equipment_id], now_s)
        return {"samples": len(equipment_states), "equipment": equipment_states}
