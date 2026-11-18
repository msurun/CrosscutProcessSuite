# Phase 2.5 plan: APC core

Module: APC core (PRODUCT.md section 3.2). Decision record: ADR 015. Owner decision 2026-11-10: Phase 2.5 comes before Phase 3.
Every step: its own branch and PR, gates `ruff`, `mypy --strict` on changed Python, `pytest` for the touched packages, `vitest`, `tsc`, and
`e2e` with axe for every GUI slice. Simulator results are not plant claims.

## Correction to the 2026-11-10 review

`schemas/project.schema.json` is not dead: it describes the offline dataset (`sim/.../dataset.py`, `loops/.../plant_import_write.py`).
Its MV/CV/DV roles annotate a dataset; they are not a controller configuration. Step 1 therefore keeps it as the dataset format and puts the
controller variable model in the site catalogue only. ADR 015 decision 2 is read this way ("one schema for controller variables").

## Steps

| # | Step | Content | Done when |
|---|---|---|---|
| 1 | Controller variable model | `site.schema.json`: `controllers[]` with id, type, cycle period, required MVs; `variables[]` binding a catalogue tag or loop to role MV / CV / DV / inferential CV with engineering, operator, validity, move and rate limits, priority, operator on/off default. Cross-reference checks in `site_refs.py` (an MV must be a loop with a remote-setpoint mode; limits nested: validity contains engineering contains operator). Schema-driven editor shows it | Example site has one fuzzy controller; invalid nesting and dangling references fail with clear messages; editor e2e |
| 2 | Cycle snapshot | Connector keeps one session, reads all tags of a cycle in one batch, stamps the snapshot; reconnect with back-off. Live read API unchanged for old callers | Snapshot test against the OPC UA test server; comm loss produces a snapshot with every value bad and reason `comm_loss` |
| 3 | Live variable status | Runtime service computes per variable: good / uncertain / bad plus reason (`quality`, `stale`, `comm_loss`, `out_of_validity`, `anomaly`, `operator_off`). Stale = source timestamp older than N cycles (N in the controller config). Anomaly instrument events (stuck, quality) mark the tag; virtual-sensor validity joins in Phase 4a. Published in runtime state and `GET /runtime/variables` | Unit tests per reason; anomaly stuck event turns the tag bad within one cycle |
| 4 | Loop readiness and MV availability | Gateway command `mv_availability` per target: mode allows remote SP, not in hold-off, not killed, policy mode allows writes. Runtime adds output saturation and valve health from the live loop KPI job. Result: available / unavailable plus reason | Gateway and runtime tests; a loop dropped to manual is unavailable in the next cycle |
| 5 | Controller host | `Controller` protocol (initialise from current values, step(snapshot, status) -> moves, explain). Host in the runtime: fixed cycle, overrun counter and last duration, state machine `off` / `standby` / `on` / `shed` with `init` on entry to `on`; bad CV dropped from the step; required MV unavailable or comm loss -> `shed`; state persisted atomically and restored after restart as `standby` (never straight to `on`); heartbeat in runtime state | State-machine tests for every transition; restart test; overrun test with a slow fake controller |
| 6 | Fuzzy supervisor as first controller | Adapter binds fuzzy variables to catalogue variables (no own limits), moves within move and operator limits, proposals through the gateway in the target's mode (`confirm` first). Replaces the request-only path for deployed supervisors; replay and backtest stay | Unit tests; supervisor proposes only while `on`; one bad input drops only that CV |
| 7 | Operator console | New view: controllers (state, last cycle, overrun, explanation of the last move), variables (status, reason, value, limits); controller on/off and variable on/off, operator limits within engineering limits; roles per ADR 013; audited | vitest + e2e with axe; operator role can switch, viewer cannot |
| 8 | Closed loop on RougherSim | L5 rows: controller runs against RougherSim through the gateway; injected transmitter failure drops the CV; base loop to manual sheds the controller; runtime restart returns in `standby`; console switch works | Rows green in nightly CI against pinned RougherSim |

Order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8. Steps 2 and 4 may run in parallel after step 1.

## Proposed defaults for the open points of ADR 015 (owner confirms or changes)

1. **Cycle period:** configurable per controller, 1 s to 3600 s, default 30 s for a fuzzy supervisor. Overrun = a cycle that starts later
   than one period after the previous start; counted and shown. After 3 overruns in a row the controller goes to `shed`.
2. **Heartbeat:** the DCS-facing heartbeat stays in the gateway only (one watchdog the DCS has to monitor). The controller host publishes its
   own liveness in runtime state, and the gateway refuses controller proposals when that liveness is older than two cycles.
3. **Who switches a controller `on`:** operator or engineer role (ADR 013); `on` is allowed only when every required MV target is in gateway
   mode `confirm` or `supervised`. In `advisory` the controller can run, but only as advice.

## Out of scope for Phase 2.5

MPC, virtual-sensor online job (Phase 4a, joins step 3 then), loop templates and vendor profiles as data, catalogue versioning (stage 3 of the
review plan), real DCS connection.
