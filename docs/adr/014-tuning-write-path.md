# ADR 014: Tuning write path (PID parameters)

Status: **Accepted (implemented; owner questions open)**
Date: 2026-11-05
Builds on: ADR 011 (write path), ADR 012 (writes are a product capability), ADR 013 (roles and authority). Tracked as issues #48 and #51, Phase 3.

## Context

The Write Gateway is setpoint-oriented today:

- One tag and one value per proposal (`WriteProposal` in `interfaces.py`).
- Out-of-range values are clamped silently (`policy.py`).
- Watchdog and release logic exists for a remotely held setpoint (`engine.py` tick).
- The mode is global: in `supervised`, writes go directly to the DCS.

PID parameters differ from setpoints in five ways:

- They form an atomic set (gain, Ti, Td). Changing one without the others is a different tuning.
- A clamped gain is a different tuning, so out-of-range values must be **refused, never clamped**.
- They persist in the DCS, so there is nothing to release when the gateway stops.
- Owner decision: writes are **confirm-only**.
- No API route for proposing exists yet.

Other facts that shape the design:

- The plant map requires setpoint and source nodes; it has no parameter nodes.
- The site loop has a free-text vendor field.
- The `loop_kpi` KPI dict has no error variance and no IAE. `harris_index` is `None` without dead time.

## Decision

### 1. Proposal data

- New schema `schemas/tuning-proposal.schema.json`.
- Stored by the API in `<root>/_tuning/proposals/<id>.json`.
- The gateway audit stays authoritative for what was actually written.

Fields:

- `id` (uuid), `version`, `loop_id`, `created_by`, `created_at`.
- `expires_at`: default 8 hours, capped in code at 12 hours.
- `vendor_form`: a key from `VENDOR_FORMS`, plus evidence.
- `source`:
  - `method`: `simc` | `amigo` | `amigo_pid` | `rollback` | `manual`.
  - `robustness`.
  - `model`: `{K, tau_s, theta_s, process_kind}`.
  - `window`: `{dataset_id or history, start, end}`.
  - `step_test_id` (optional).
  - `report_digest`.
- `confidence`: `{level: high | medium | low, reasons[]}`. Level is `low` when vendor evidence is not verified, the model fit is weak, or the window is older than 24 hours.
- `caveats[]`: copied from the `VendorForm`.
- `items[]`: each `{param: gain | ti | td | tf, target, unit, from, to}`. `from` is read live from the DCS at creation.
- `preview`: model-simulated IAE ratio, overshoot, settling time, Ms, current vs proposed. Always labelled "model prediction".
- `rollback_of`.
- `status`.
- `gateway_key`.
- `applied`: `{from_read, to_read, t, approver}`.
- `review`.

Creation is refused when:

- the report has a `blocked_reason` (stiction, external oscillation, averaging level), or
- the loop has no running `loop_kpi` job.

### 2. Gateway extension

The setpoint path is unchanged.

**Policy schema.** `target_policy` becomes a `oneOf` on `kind`. A missing `kind` means `setpoint`, so existing policies stay valid. A new `pid_param` branch has `additionalProperties: false` and holds:

- `loop`, `param`, `unit`, `vendor_form`.
- `limits`.
- `max_ratio` (> 1). The new value and the current value must both lie within `[1/r, r]`.
- `readback_tolerance`.
- `min_interval_s`.
- `allowed_loop_modes`.

It has **no** rate, watchdog or hold-off fields.

**Plant map.** `oneOf` with a `pid_param` target:

- `param_node`.
- `readback_node` (optional, defaults to `param_node`).
- `data_type`: `Float` or `Double`.
- `mode_node`.
- `mode_values`.

**Types.** `ParamPolicy`, `ParamItem` and `ParamSetProposal` in `interfaces.py`.

**Confirm-only in code.**

- `KIND_MODE_CAP = {setpoint: supervised, pid_param: confirm}`.
- Effective mode is the more restrictive of the global mode and the kind cap. So in `supervised`, a parameter set is queued, not written.
- Approve accepts parameter sets only when the effective mode is `confirm`.

**Item checks.** Failures are refused, never clamped:

- `out_of_limits`.
- `ratio_exceeded`.
- `unit_mismatch`.
- `form_mismatch`.

Code-fixed checks:

- `gain > 0`. The sign is never written.
- `ti > 0`. On Siemens, Ti = 0 switches integral action off.
- `td >= 0`.

**Tick for parameter targets.** Read-back only.

- A changed value means someone changed it at the DCS. The gateway sets the state to `hold_off`, audits `param_changed_externally`, and marks the KPI review invalid.
- No release, no watchdog, no write-back.

**Authorization.**

- New permission `gw.approve.tuning`, held by `engineer` and `lead`.
- Proposing uses `gw.propose` (`engineer`).
- `svc:runtime` may never propose `pid_param`. Such a request fails with `service_cannot_propose_tuning`.
- The approver must differ from the proposer.
- Operators keep `gw.reject`.

### 3. Lifecycle

**Propose.** Producer endpoint `POST /loops/{loop_id}/tuning/proposals` (requires `gw.propose`):

1. Rebuild the report.
2. Read the current values through the connector.
3. Build the record.
4. Sign a new command `propose_params`. It is separate from `propose`, so the validation of `propose` is untouched.

Arguments: `{proposal_id, loop_id, items[], proposer, t_ns, expires_ns, reason, rollback_of}`.

**Idempotency.** Key = `sha256` of the canonical form of `(proposal_id, items, proposer, t_ns)`. A replay returns the cached decision. The same `id` with different content is refused as `id_conflict`.

**Stale rules.**

- Expiry uses `expires_ns`, not `watchdog_s`.
- `loop_busy`: only one pending parameter set per loop.
- `min_interval` between applies, per loop.
- A kill drops all pending parameter sets.

**States.** `draft -> queued -> applied | rejected | expired | refused:<code>`, then `reviewing -> reviewed:<verdict>`.

### 4. Apply

The GUI approve step shows a table with, for each item: old -> new, unit, vendor form, evidence and caveats. It also shows the preview and the expiry.

On approve the gateway re-checks, in order:

1. Kill state.
2. Target states.
3. Effective mode.
4. Expiry.
5. Approver differs from proposer.
6. `gw.approve.tuning`.

Then:

1. Read the loop mode. It must be in `allowed_loop_modes` for every item.
2. Read every item. If `|current - from| > tol`, refuse with `from_mismatch`, report the values read, and write nothing.
3. Write in fixed order: **de-tuning first** (lower gain, longer Ti). Read back after each write.
4. If a write is refused, or a read-back does not match, write back the `from` values of the items already written. Audit `partial_revert` and set the target to `stopped:readback`.
   - If the revert also fails, set `stopped:comm` and raise an alarm: "check DCS".
5. On success, audit `param_write` with `applied_from` and `applied_to`.

**Dry run.** `dry_run` runs checks 1 to 3 and logs the result. It writes nothing.

**Advisory mode.** Records only.

### 5. KPI before and after

- Pure function `compare_windows` in `loops/tuning_review.py`. It reads windows from `HistoryStore`.
- Window length `W = max(30 min, 20 * (theta + tau))`.
- Before-window: `[t_apply - W, t_apply)`.
- After-window: starts at `t_apply + 3 * (theta + tau)` and lasts `W`.

Metrics:

- `kpi_from_series`.
- Error standard deviation (PV - SP).
- IAE per hour.
- OUT travel per hour.
- Oscillation.
- Number of SP moves.

Verdicts. Thresholds are data, frozen for tests:

- `insufficient_data`: fewer than `MIN_KPI_SAMPLES`; service factor < 0.9 in either window; loop left AUTO or CAS; SP moves differ by more than 2x between windows.
- `worse`: error std up by >= 20%, or a new oscillation, or saturation up.
- `improved`: error std down by >= 20% and OUT travel up by < 50%.
- `neutral`: otherwise.

Early check: an oscillation in the first 3 cycles of the after-window gives `worse_early` immediately.

GUI text: "observed after the change; other causes (feed, SP activity) not excluded".

Executor: runtime job kind `tuning_review`, which polls applied records.

### 6. Rollback

`POST /tuning/proposals/{id}/rollback` creates a normal proposal with method `rollback`:

- `rollback_of` = the id of the original proposal.
- `to` = the audited `applied_from`.
- `from` = the audited `applied_to`.
- Same confirm and approver rules.
- If the loop was retuned in between, refuse with `from_mismatch`.
- Exempt from `min_interval` and `max_ratio`, **only** when the gateway confirms that `to` equals its own audited `applied_from` for that key.
- Limits still apply.

A `worse` or `worse_early` verdict raises a "Rollback recommended" badge and a worklist entry. Nothing is proposed automatically.

### 7. Supervisor advice (issue #51)

Supervisor advice uses the existing propose path (setpoint kind) with the same record pattern. No new gateway kind.

## Consequences

- Parameter writes never clamp. A value outside limits is refused and the owner sees why.
- In `supervised` mode, parameter sets are queued and need a second person in `confirm` mode.
- The DCS stays the last line of defence. An external change puts the loop into `hold_off` and no write-back occurs.
- Parameter logic lives in `engine_params.py`, keeping `engine.py` changes small. The 12 existing gateway scenarios must pass unchanged.
- Pending parameter sets are lost on gateway restart. This is accepted: the record expires and is re-proposed.
- A KPI verdict is observational and can be confounded by feed or SP activity. `improved` is not trusted until `compare_windows` matches the RougherSim ground truth.

## Implementation order

Each step is done by one agent.

1. Schemas and parsing: write-policy, plant-map and tuning-proposal schemas; `policy.py`; `interfaces.py`; tests.
2. Gateway `engine_params.py` (propose, approve, tick for parameter sets), plus hooks in `engine.py` (`KIND_MODE_CAP`, a kind branch in `_tick_tag` and `_release_target`); tests.
3. `service.py` (`propose_params`, list-argument validation, pending entries with kind and items); `authz.py`; `schemas/auth-roles.default.json`; `DEFAULT_ROLES`; ADR 013 table.
4. `opcua_plant.py`: parameter read and write by `data_type`, with an asyncua test.
5. Loops: `tuning_proposal.py` and `tuning_review.py` as pure modules, with tests.
6. API: `tuning_proposal_routes.py`, the proposal store, `propose_params` in `gateway_client`, `route_permissions.py`.
7. Runtime: `jobs/tuning_review.py`; add to `RUNNABLE_KINDS` in `service.py`.
8. Frontend: tuning view, pending diff card, e2e tests, RougherSim L5 row.

## Tests

Gateway, with a fake plant:

- Parameters are never written in `supervised`, across the 5 modes and all kinds.
- `svc:runtime` is refused when proposing `pid_param`.
- Refuse, never clamp.
- `from_mismatch`.
- `partial_revert`.
- External change leads to `hold_off`; `release` is never called.
- Expiry.
- `id_conflict`.
- Rollback exemption.

OPC UA: a local asyncua server with Float parameter nodes.

`compare_windows`: one synthetic series per verdict.

API:

- Route inventory.
- Operator gets 403 on propose and approve.
- Self-approval is refused.

RougherSim L5 row "P3 tuning release": rollback restores the read-back within tolerance 0.

End-to-end: propose, a second user approves, diff table, KPI panel, rollback, axe.

## Risks

- **Engine size and regressions.** Keep parameter logic in `engine_params.py`. Rerun the 12 scenarios unchanged.
- **OPC UA variant type.** Float vs Double gives `BadTypeMismatch`. Test against asyncua.
- **Wrong KPI verdicts.** Review needs history. Test `compare_windows` against RougherSim ground truth before trusting `improved`.
- **Pending sets lost on restart.** Accepted. The record expires and is re-proposed.

## Open owner questions

Defaults below are implemented as configuration and can be changed without code changes.

1. Pilot DCS: which ABB PidCC unit handles TI and TD, and is a gain change in AUTO bumpless? Default: `allowed_loop_modes` is `[MAN, AUTO]`, and ABB targets stay off until the unit is confirmed.
2. Who approves tuning writes? Default: `engineer` or `lead` (`gw.approve.tuning`). Operators can only reject, and can always take over at the DCS.
3. A step-test assistant that writes OUT in manual is not in this issue. A proposal only references a `step_test_id` from the Steps view.
