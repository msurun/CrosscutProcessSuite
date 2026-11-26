"""Executes a confirmed multi-MV step plan as ordinary gateway proposals (MPC 7.1a, ADR 017 style).

The plan is a stored record under ``<root>/_mpc/step-plans/<id>.json``. Nothing here writes to a
plant: each due step is sent with the gateway ``propose`` command of the human who confirmed, so in
``confirm`` mode it only queues and an operator still approves it at the gateway. The runner keeps
one step queue at a time and stops the whole plan on the first refusal, rejection, operator
takeover (live setpoint differs from the expected one), approval timeout, or a gateway that has
left ``confirm`` mode. It never returns an MV to its baseline by itself: after an abort the record
lists the displaced MVs and the operator decides.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from crosscut_api.auth.actor import ActorContext

NS = 1_000_000_000
PENDING_GRACE_S = 15.0  # a queued step may be missing from state.json this long after the send
APPROVAL_WINDOW_S = 600.0  # an unapproved step older than this stops the plan
CLAIM_GRACE_S = 60.0  # a claim without a plan record is a crash leftover after this long
CLOCK_SKEW_S = 5.0  # a step stamped further in the future than this means the clock moved
SP_TOLERANCE = 1e-6  # relative tolerance when comparing a live setpoint with an expected value
Doc = dict[str, Any]


def plans_dir(root: Path) -> Path:
    """Folder of the plan records."""
    return root / "_mpc" / "step-plans"


def load_plan(root: Path, plan_id: str) -> Doc | None:
    """The stored record of a plan, or None when it does not exist."""
    try:
        return json.loads((plans_dir(root) / f"{plan_id}.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def save_plan(root: Path, plan: Doc) -> None:
    """Write a record atomically (temporary file, then replace)."""
    folder = plans_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{plan['id']}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def all_plans(root: Path) -> list[Doc]:
    """Every stored record, oldest first."""
    folder = plans_dir(root)
    names = sorted(folder.glob("*.json")) if folder.is_dir() else []
    plans = [load_plan(root, name.stem) for name in names]
    return [p for p in plans if p is not None]


def running_plan(root: Path) -> Doc | None:
    """The plan that is still running, if any (only one may run)."""
    return next((p for p in all_plans(root) if p["status"] == "running"), None)


def same_value(live: float, expected: float) -> bool:
    """True when two setpoints agree within a small relative tolerance."""
    return math.isclose(live, expected, rel_tol=SP_TOLERANCE, abs_tol=SP_TOLERANCE)


def claims_dir(root: Path) -> Path:
    """Folder of the per-MV claims that keep two plans off the same setpoint."""
    return root / "_mpc" / "claims"


def _claim_path(root: Path, tag: str) -> Path:
    """Claim file of one MV tag (hash of the tag, so any tag text is a safe file name)."""
    return claims_dir(root) / (hashlib.sha256(tag.encode()).hexdigest() + ".claim")


def _claim_is_stale(root: Path, path: Path) -> bool:
    """A claim is stale when its plan is no longer running (finished, aborted or crash leftover).

    A claim whose record does not exist yet is only stale after ``CLAIM_GRACE_S``: the owner
    claims first and saves the record a moment later.
    """
    try:
        plan = load_plan(root, path.read_text(encoding="utf-8").strip())
        age_s = time.time() - path.stat().st_mtime
    except OSError:
        return True
    if plan is None:
        return age_s > CLAIM_GRACE_S
    return plan["status"] != "running"


def claim_tags(root: Path, plan_id: str, tags: list[str]) -> list[str]:
    """Atomically claim every tag (O_CREAT|O_EXCL file per tag); return the tags held by others.

    Works across processes. A claim whose plan is not running is stale and is taken over. When
    any tag is held by another running plan, nothing stays claimed and the held tags are returned.
    """
    claims_dir(root).mkdir(parents=True, exist_ok=True)
    taken: list[str] = []
    held: list[str] = []
    for tag in sorted(set(tags)):
        path = _claim_path(root, tag)
        if _try_claim(root, path, plan_id):
            taken.append(tag)
        else:
            held.append(tag)
    if held:
        release_tags(root, plan_id, taken)
    return held


def _try_claim(root: Path, path: Path, plan_id: str) -> bool:
    """Create the claim file exclusively; replace a stale one once."""
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not _claim_is_stale(root, path):
                return False
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(plan_id)
        return True
    return False


def release_tags(root: Path, plan_id: str, tags: list[str]) -> None:
    """Remove the claims this plan holds (a claim owned by another plan is left alone)."""
    for tag in set(tags):
        path = _claim_path(root, tag)
        try:
            if path.read_text(encoding="utf-8").strip() == plan_id:
                path.unlink(missing_ok=True)
        except OSError:
            continue


@dataclass
class Runner:
    """What ``advance`` needs: root, gateway client, actor, live-SP reader, clock, audit hook."""

    root: Path
    client: Any
    actor: ActorContext
    read_sp: Callable[[str], float]
    now_ns: Callable[[], int]
    audit: Callable[..., None]


def advance(plan: Doc, run: Runner) -> Doc:
    """Move a running plan one step forward (resolve queued steps, then send the due ones)."""
    if plan["status"] != "running":
        return plan
    reason = _gateway_reason(run) or _resolve_queued(plan, run) or _takeover(plan, run)
    if not reason and not any(s["status"] == "queued" for s in plan["steps"]):
        reason = _send_due(plan, run)
    if reason:
        return abort(plan, run, reason)
    if all(s["status"] == "applied" for s in plan["steps"]):
        plan["status"] = "completed"
        release_tags(run.root, plan["id"], list(plan["baselines"]))
        run.audit("mpc_step_plan_completed", plan=plan["id"])
    return plan


def _gateway_reason(run: Runner) -> str:
    """Abort reason when the gateway is no longer in confirm mode (nothing may be auto-approved)."""
    try:
        mode = run.client.mode()
    except (OSError, KeyError, ValueError, TypeError):
        return "gateway_unreadable"
    return "" if mode == "confirm" else "gateway_mode_changed"


def _pending_for(run: Runner, step: Doc) -> Doc | None:
    """The gateway pending entry of a step (same tag and send time), or None."""
    for entry in run.client.pending():
        if entry.get("target_tag") == step["tag"] and entry.get("t_ns") == step["t_ns"]:
            return entry
    return None


def _resolve_queued(plan: Doc, run: Runner) -> str:
    """Judge each queued step: still pending, applied, rejected or taken over; '' to go on."""
    for step in plan["steps"]:
        if step["status"] != "queued":
            continue
        reason = _resolve_one(plan, run, step)
        if reason:
            return reason
    return ""


def _resolve_one(plan: Doc, run: Runner, step: Doc) -> str:
    """Abort reason for one queued step, or '' when it is pending or has just been applied."""
    age_s = (run.now_ns() - step["sent_ns"]) / NS
    if age_s < -CLOCK_SKEW_S:
        return "clock_skew"
    age_s = max(age_s, 0.0)
    if _pending_for(run, step) is not None:
        step["seen_pending"] = True
        return "approval_timeout" if age_s > APPROVAL_WINDOW_S else ""
    if not step["seen_pending"] and age_s < PENDING_GRACE_S:
        return ""
    try:
        live = run.read_sp(step["tag"])
    except HTTPException:
        return "no_live_sp"
    if same_value(live, step["value"]):
        _mark_applied(plan, step, run.now_ns())
        return ""
    return "step_rejected" if same_value(live, step["from_value"]) else "operator_takeover"


def _mark_applied(plan: Doc, step: Doc, now_ns: int) -> None:
    """Record the apply time and slip the schedule anchor if the approval was late."""
    step["status"], step["applied_ns"] = "applied", now_ns
    plan["anchor_ns"] = max(plan["anchor_ns"], now_ns - int(step["at_s"] * NS))


def _takeover(plan: Doc, run: Runner) -> str:
    """Abort reason when an MV that is not mid-step no longer sits at its last applied value."""
    queued = {s["tag"] for s in plan["steps"] if s["status"] == "queued"}
    for tag, expected in _expected_values(plan).items():
        if tag in queued:
            continue
        try:
            if not same_value(run.read_sp(tag), expected):
                return "operator_takeover"
        except HTTPException:
            return "no_live_sp"
    return ""


def _expected_values(plan: Doc) -> dict[str, float]:
    """Last applied value per tag (tags with no applied step are not checked yet)."""
    expected: dict[str, float] = {}
    for step in plan["steps"]:
        if step["status"] == "applied":
            expected[step["tag"]] = step["value"]
    return expected


def _send_due(plan: Doc, run: Runner) -> str:
    """Send every planned step whose slipped time has come; abort reason on the first failure."""
    now = run.now_ns()
    for step in plan["steps"]:
        if step["status"] != "planned" or plan["anchor_ns"] + int(step["at_s"] * NS) > now:
            continue
        reason = _gateway_reason(run) or _send_step(plan, run, step, now)  # mode, right now
        if reason:
            return reason
    return ""


def _from_value(plan: Doc, tag: str) -> float:
    """The value the MV holds before the next step: last queued or applied step, else baseline."""
    value = plan["baselines"][tag]
    for step in plan["steps"]:
        if step["tag"] == tag and step["status"] in ("queued", "applied"):
            value = step["value"]
    return value


def _send_step(plan: Doc, run: Runner, step: Doc, now: int) -> str:
    """Audit, then propose one step through the normal gateway command; abort reason or ''."""
    run.audit("mpc_step_proposed", plan=plan["id"], step=str(step["index"]), tag=step["tag"],
              value=str(step["value"]))
    args = {
        "target_tag": step["tag"], "value": step["value"], "proposer": run.actor.actor,
        "t_ns": now + step["index"],
        "reason": f"mpc-step-plan:{plan['id']} step {step['index'] + 1}/{len(plan['steps'])}"
                  f" {step['mv']}",
    }
    step["from_value"] = _from_value(plan, step["tag"])
    try:
        decision = run.client.propose(args, run.actor)
    except TimeoutError:
        step["status"] = "unknown"
        return "outcome_unknown_check_audit"
    except (PermissionError, ValueError, KeyError, OSError) as error:
        step["status"] = "refused"
        return f"gateway_error:{type(error).__name__}"
    if not decision.get("accepted"):
        step["status"], step["reason_code"] = "refused", str(decision.get("reason_code", ""))
        return f"step_refused:{step['reason_code']}"
    step.update(status="queued", t_ns=args["t_ns"], sent_ns=now, seen_pending=False)
    return ""


def abort(plan: Doc, run: Runner, reason: str) -> Doc:
    """Stop the plan: reject its queued steps, keep the rest unsent, list the displaced MVs."""
    if plan["status"] != "running":
        return plan
    for step in plan["steps"]:
        if step["status"] == "queued":
            _reject_pending(run, step)
        elif step["status"] == "planned":
            step["status"] = "skipped"
    plan["status"], plan["abort_reason"] = "aborted", reason
    plan["displaced"] = _displaced(plan)
    release_tags(run.root, plan["id"], list(plan["baselines"]))
    run.audit("mpc_step_plan_aborted", plan=plan["id"], reason=reason)
    return plan


def _reject_pending(run: Runner, step: Doc) -> None:
    """Discard a queued step at the gateway; a step that is no longer pending needs nothing."""
    entry = _pending_for(run, step)
    if entry is None:  # applied or rejected meanwhile: only the DCS value tells which
        step["status"] = "unresolved_check_dcs"
        return
    try:
        run.client.reject(entry["key"], run.actor)
        step["status"] = "rejected"
    except (PermissionError, ValueError, KeyError, OSError, TimeoutError):
        step["status"] = "reject_failed_check_gateway"


def _displaced(plan: Doc) -> list[Doc]:
    """MVs whose last applied value is not their baseline: the operator must restore them."""
    rows = []
    for tag, value in _expected_values(plan).items():
        baseline = plan["baselines"][tag]
        if not same_value(value, baseline):
            rows.append({"tag": tag, "baseline": baseline, "last_applied": value})
    return rows
