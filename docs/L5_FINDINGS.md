# L5 findings: Crosscut gateway against RougherSim (rs-v0.11.0)

Rows L5-G01..G12 and the tuning check run the real `WriteGateway` on the real `OpcUaPlant`
against a RougherSim OPC UA server (`tests/integration_roughersim/test_l5_gateway_rows.py`,
plant map `plant_maps/rougher_fic203.json`, target loop FIC203). RougherSim is a synthetic
simulator; nothing here says how a real 800xA behaves.

| # | Finding | Impact | Resolution |
|---|---|---|---|
| 1 | A mode change applies on the next plant step; a setpoint (Rsp) write right after `Mode := RSP` is refused with BadInvalidState. | `take_remote` before the setpoint always failed: the engine saw a rejected write and stopped the target. | Adapter fix: optional `take_remote.settle_s` (schema + `OpcUaPlant.write`, default 0 = unchanged, tests added). Plant map uses 1.6 s wall. A real DCS may need the same, or a poll of the effective mode. |
| 2 | Mode node doubles as the setpoint-source node (source = `Mode == 3`, local = 1). | None: `source_node = mode_node`, `remote_value 3`, `local_value 1` is expressible as is. | Plant map only. |
| 3 | Heartbeat is an Int32 counter. | None: the adapter already writes the node's own variant type. | Verified, no change. |
| 4 | PID parameters are Double, writable in any mode. | None: `data_type: Double`; exact read-back and rollback with tolerance 0 pass. | Plant map only. |
| 5 | In CAS the Sp/Rsp node is the cascade primary's output and drifts (about 0.5 per s after start). | The first write is clamped to `last_value +- max_step`, with `last_value` the drifting read-back. Fixed numeric proposals do not work. | Scenarios propose relative to the current read-back. A real cascade secondary may behave the same. |
| 6 | DCS watchdog (`--watchdog-s`, default 30) counts wall-clock seconds, not simulation seconds. | Heartbeat period must be wall time; the harness keeps the heartbeat alive while it waits for sim time. | Harness uses `--watchdog-s 4`; G02 sleeps 5.5 s wall. |
| 7 | After the DCS watchdog trip the loop stays in AUTO (not restored). The engine sees source `local` and goes to `hold_off`. | Intended "operator wins" semantics. | G02 asserts `hold_off` after the trip. |
| 8 | A refused Rsp write after a successful `Mode := RSP` leaves the loop in AUTO after the engine's release (previously CAS). | `write() == False` means "setpoint unchanged", not "plant unchanged": the cascade is lost until the operator restores CAS. | Recorded; G03 asserts the loop is not in RSP. Possible follow-up: release value CAS for cascade secondaries (owner decision, the agreed value is AUTO). |
| 9 | `comm_loss` makes every node return BadCommunicationError, which `OpcUaPlant` classifies as transport failure (client dropped). | Fail-closed works (target `stopped:comm`, release logged `release_failed`), but the setpoint source cannot be read while the link is down. | G07 asserts the fail-closed state and the audit entry, not "local". |
| 10 | The engine's own `watchdog_s` releases a target when its last write is older than that policy value, measured in proposal time. | A 5 s policy watchdog releases the target in any scenario that waits tens of simulated seconds. | RougherSim policy uses `watchdog_s = 600`. |
| 11 | Engine proposal window (`bad_time`) follows the last `tick`, so a proposal needs a tick first. | Harness ticks before each proposal (as production does). G09 deliberately skips the tick to test the propose-time check. | Test harness only. |
| 12 | Hook times are absolute simulation seconds from server start (operator hooks at 30 s and 60 s). | The harness must connect and write before the hook fires. | G05 runs at speed 8, G09 at speed 4, with a guard that fails clearly when the harness is too slow. |
| 13 | RougherSim has no step API; time advances at `--speed` times wall clock. | Tests wait for `Application/System/TimeS`, so they take real seconds (about 1.5 min for 12 rows). | Harness `advance()`. |
| 14 | `golden.checkout_problem` refuses a checkout with local modifications. | Blocks development while the RougherSim session has uncommitted changes. | `ROUGHERSIM_ALLOW_DIRTY=1` overrides (development only; CI uses the clean pin). |

Not reproduced one-to-one: G03/G07 cannot assert "no write at all" at the plant for the take
(Mode) write, only for the setpoint; G07 cannot assert a local setpoint (finding 9).
Open: the full P3 row (step test, KPI, rollback) needs the closed-loop pieces and stays pending.

## TF3: delayed parameter read-back (issue #54)

With RougherSim hooks, a written PID parameter and its offset can appear one plant step late.
The gateway keeps the write intent open and verifies every written parameter again on an
engine tick after the set's longest `verify_after_s` settle time (2.0 seconds when omitted).
A delayed mismatch is **never written back**: it cannot be told apart from an operator's
change at the DCS, so the gateway handles it exactly like an external change (the target is
held off, the applied record is marked invalid through `param_changed_externally`, no plant
write) and adds the audit event `readback_mismatch_delayed`. The set's intent is closed after
that audit; a failed read leaves it open for reconciliation. Ordinary external-change
monitoring skips a settling target; a DCS change inside the window is caught by the delayed pass
and kept, not overwritten. A new proposal (apply or rollback) for a target with a pending verification
runs that verification synchronously first, so an immediate rollback after a good apply is
accepted instead of refused with `reconcile_required`.

TF3 now asserts this behaviour (xfail removed): the apply is accepted, the test advances the
gateway ticks past the settle time and checks that no plant write follows, that
`param_changed_externally` and `readback_mismatch_delayed` are audited for Gain, that there is no
`partial_revert`, and that Gain is in hold_off. The old plant-baseline restoration assertion is dropped.

## C02: failed transmitter (RougherSim 0.13.0, hook API 1.2.0)

The pv_fault hooks `gw.pv_fault_dic202.v1` / `gw.pv_fault_lit201.v1` fail the PV node from t=0. The
CV_B address was wrong (`LIT201/Pv`); the node is `LIC201/Pv`. C02a (a second good CV keeps the
controller `on`) passes. The host's state machine (`state.py`) sheds only from `on`: with the only
CV bad from t=0 `switch_on` is refused (`standby`, reason `no_good_cv`, no proposals; own test).
C02b uses `gw.pv_fault_dic202_late.v1` (RougherSim 0.13.1, fault from 120 s): the controller is
`on`, then sheds with `no_good_cv`. All C rows pass; no xfail left.

## Matrix rows P1, P1-dq, P2-e2e, P3, P4, P6, P7 (issue #53)

Ready with executors: L5-P1 (`p1_live.py`: nominal recording -> `roughersim export-crosscut-project`
-> site catalogue validated with `validate_site` and addressed by OPC UA node -> `LoopKpiJob` on
`roughersim serve` for 60 ticks -> a KPI row with `service_factor`, `saturation_fraction`,
`flatline_fraction`, `classification` for each of the 13 loops), L5-P2-e2e (gateway scenario tests
plus the 12 G rows) and L5-P3 (the LIC301 chain of `test_l5_p3.py`: detect, identify, propose,
apply through the confirm-mode gateway, KPI improves, rollback replay).

| Row | State | What blocks it |
|---|---|---|
| L5-P1 | ready, partial | The "GUI e2e" part of the criterion is driven by L5-nocode (#151, below); `p1_live.py` still builds its catalogue from the export helper through the schema. The live KPI is checked against nominal expectations (service factor, frozen share), not against a numeric ground-truth KPI: a live server starts without warm-up, so level loops (LIC301, LIC311, LIC321, LIC331) show 13 to 50 % saturation in the first minutes. |
| L5-P1-dq | pending (held-out target missed, strict xfail `test_l5_dq.py`) | Executor `p1_dq.py` runs the onboarding report (`evaluate_dataset_readiness`, `sensor_faults`) with the default `SensorFaultConfig` on `rs.sensor_faults.mix.v1` (seed 100005, rs-v0.13.1), 60 s sampling, 24 h; nothing tuned on it. Result 2026-11-18: precision 0.50 (2 of 4 findings), recall 0.67 (2 of 3 events) against targets 0.9 / 0.8. Hits: LIC311 freeze (10800-16140 s vs truth 10800-16200 s) and DIC202 drift (19800-36000 s vs 21600-36000 s). Misses: the FIC401 spikes (+0.05 on a 0.003 sigma signal, 20 sigma, but probability 0.02 gives about 1.2 spikes per 3600 s window while the default needs 3 returning excursions per window). False alarms, 1 per tag on 2 tags: LIC311_out freeze (the controller output freezes with the frozen PV, a real consequence in the closed loop but not an injected fault on that tag) and LIC331_out drift (21600-28800 s, a genuine slow level-loop output ramp of 14 points in 2 h, no fault injected). Open decisions for the owner: how to score consequences on OUT tags (restrict the report to PV tags, or credit propagated faults) and whether spike_min_count 3 is right for sparse spikes. Detector defaults were not changed. Second measurement 2026-11-18 after a detector fix round (the fix round followed the first measurement and was made after seeing seed 100005, so that seed is development data, not a blind result; defaults unchanged): the report now gets site roles (`recorded_loops()`, loop PV/SP/OUT/mode) so only measured tags are scanned, OUT findings and findings overlapping a PV freeze are dropped as consequences, spikes are clustered. Development seed 100005: precision 1.00 (3 of 3), recall 1.00 (DIC202 drift 19800-36000 s, FIC401 spike cluster 34440-38280 s, LIC311 freeze 10800-16140 s). Held-out seed 100105 (scenario copy with only the seed changed, run once): precision 0.75 (3 of 4), recall 1.00; one false alarm, a FIC203 drift at 21600-28800 s (exactly the 2 h minimum window) on a flow-loop PV with no fault injected there. The row stays pending until the held-out precision reaches 0.9; `test_l5_dq.py` runs the held-out seed as a strict xfail. |
| L5-nocode (#151) | ready | Phase 1 and 3 exit criterion "no file edited by hand": `frontend/e2e/l5-nocode.spec.ts`, 9 steps, one browser run against live RougherSim, nightly L5 only. From an empty data root (no site.json, no jobs.json) the spec adds the OPC UA source with the connection test, builds the catalogue from the source browse with the `isa_suffix` preset (the 13 loops of the plant with their PV, SP, OUT and MODE tags, plus the Gain and Ti tags of FIC203 ticked by hand), creates the `loop_kpi` job in the Runtime view, sees the live KPI, raises the gateway to confirm (advisory, dry_run, confirm), proposes a SIMC change from the Tuning view (engineer), sees it in the gateway queue, approves it (lead, a second person), checks the server parameters and that the control error |PV - RSP| of the plant changed by at least 2 %, then rolls back (engineer proposes, lead approves) and checks the previous Gain and Ti on the server. The spec imports no file-writing function (one step asserts that) and starts with the site and job files absent; only the GUI and the API write. The rig (`frontend/e2e/support/start_l5_stack.py`, started by `run_e2e.mjs` with `E2E_L5_NOCODE=1`) provides what a plant already has and nothing of the project: the pinned `roughersim serve`, a history extract of FIC203 (the pinned step-test scenario at 5 s sampling, imported as dataset `l5_fic203` whose tag ids are the ones the wizard proposes) and the gateway with the plant owner's signed policy and plant map (`FIC203.Gain`, `FIC203.Ti`). Found while building it: OPC UA browse names repeat under every loop (`Pv`, `Sp`, `Out`, `Mode` under 13 loops), so the catalogue wizard produced colliding tag ids and no loop; a repeated name now becomes `<parent>.<name>` (`FIC203.Pv`, `catalogue_source_routes.unique_names`). On Windows the runtime service stopped when the API read `state.json` during its rename (`PermissionError`); `store.replace_file` now retries. The KPI check is a change check, not an improvement check: the SIMC tuning moves the control error, not necessarily down; the before and after values are attached to the Playwright report. |
| L5-P3 | ready | The FIC203 chain stays a strict xfail (fit_step tau grid starts at 60 s); the LIC301 chain meets the criterion. |
| L5-P4 | pending (feature missing) | No generic virtual-sensor engine with a validity flag exists (softsensor is per-site); milestone is post-MVP and needs lab samples (owner item). |
| L5-P6 | ready | `p6_rows.py` runs the fuzzy controller on `gw.hardness_shift_operator_override.v1` (rs-v0.13.2: hardness +0.2 at 60 s, operator takes FIC203 to AUTO / SP 200 at 600 s). Result 2026-11-18, 3 of 3 cases pass on the live server: in confirm, proposals queue with no RSP write until one is approved, then exactly that value is written and read back; in supervised, moves stay within move_max and the policy limits; at the takeover the gateway enters hold_off (audit `operator_override`), the controller sheds with `mv_unavailable`, no RSP write follows the takeover, a switch_on inside hold-off writes nothing, and the operator AUTO mode and SP 200 are preserved. The last write is stamped at the takeover instant itself (same sim step, before the operator action is seen); none follows. Same day: the controller rig now sends runtime and controller liveness beats; without them C01/C03/C05 failed with `liveness_missing` since the liveness gate (#112), unnoticed because L5 rows skip in CI. |
| L5-P7 | partial (7.5 validation pending) | The MPC engine and runtime exist (7.2, 7.3); the frozen-protocol comparison against PID and fuzzy is #186. |
| L5-P7a (#184) | ready, advisory only (skips without the grinding bed) | `mpc_rows.py` / `test_l5_mpc_rows.py` run the `mpc` controller of the runtime wiring on the RougherSim grinding MIMO bed (M9 #22, step-test truth #24): MVs WIC101 (fresh feed) and FIC102 (mill water), CVs PDT204 and DIC202, model built from the truth gains and dead times of `rs.grinding.step_test_sequential.v1` (seed 100024; only the four self-regulating pairs, the other pairs integrate and are outside a FOPDT model). The gateway answers `mode_no_write`, so the host stays in `advisory`: first cycle bumpless (`bumpless_start`, the current setpoints), 7 later cycles with reason codes for each MV, every advised move inside `move_max` and the catalogue range, nothing proposed and the plant setpoints unchanged. Result 2026-11-27: passes on the live server (RougherSim `origin/main` with #22-#24; the pin `rs-v0.13.2` has no grinding bed, so the test skips on the pin until the pin moves). No confirm or supervised run: MPC proposals reach the plant only through the gateway path of the fuzzy controller (`gateway_adapter.make_gateway_ports`: signed `propose`, role `service`, `gw.propose`), after the controls engineer enables supervised mode. Caveat: PDT204 and DIC202 respond almost proportionally to both MVs (gain ratios 0.35 and 0.34), so the 2x2 matrix is ill-conditioned; this bed does not show the benefit of MPC over PID, #186 needs a better pair choice. |

## Running L5-nocode (#151) locally

Needs the RougherSim checkout at the pin (`tests/integration_roughersim/pin.json`; the rig refuses another
commit), the Crosscut Python packages installed, `npm ci` in `frontend` and a Chromium for Playwright.

```
cd frontend
E2E_L5_NOCODE=1 ROUGHERSIM_DIR=<RougherSim at the pin> node e2e/support/run_e2e.mjs e2e/l5-nocode.spec.ts
```

`ROUGHERSIM_PYTHON` names the RougherSim interpreter when the checkout has no `.venv` (a git worktree at the
pinned commit works). The launcher builds an empty data root with authentication on and one user per role,
starts the API, Vite, the runtime service and the rig, runs the spec and stops everything. The rig records the
FIC203 step test at the start (3 to 4 minutes); `L5_RECORDING=<folder>` reuses a recording of an earlier run.
The run takes about 2 minutes after that. The normal e2e run and the gateway run never execute this spec: the
Playwright config gives it its own project, only when `E2E_L5_NOCODE=1`. Nightly it is a step of
`.github/workflows/nightly-l5.yml`; the report of a failed run is uploaded as `l5-nocode-report`.
