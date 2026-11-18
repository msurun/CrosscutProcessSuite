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
| L5-P1 | ready, partial | The "GUI e2e" part of the criterion (catalogue built in the browser) is not driven; the catalogue is built from the export helper through the schema. The live KPI is checked against nominal expectations (service factor, frozen share), not against a numeric ground-truth KPI: a live server starts without warm-up, so level loops (LIC301, LIC311, LIC321, LIC331) show 13 to 50 % saturation in the first minutes. |
| L5-P1-dq | pending (feature missing) | `check_readiness` and `evaluate_dataset_readiness` return per-tag shares over the whole export (missing share, flat share) and no time windows. The scenario `rs.sensor_faults.mix.v1` injects a 5400 s freeze (LIT311), a 14400 s drift (DIT202) and spikes (FIT401) in 24 h; the freeze is 6 % of the record, below the 50 % flat warning, and no check detects drift or spikes. Needs a windowed fault detector in the onboarding report plus agreed precision and recall targets (owner item). |
| L5-P3 | ready | The FIC203 chain stays a strict xfail (fit_step tau grid starts at 60 s); the LIC301 chain meets the criterion. |
| L5-P4 | pending (feature missing) | No generic virtual-sensor engine with a validity flag exists (softsensor is per-site); milestone is post-MVP and needs lab samples (owner item). |
| L5-P6 | pending (feature missing) | The fuzzy closed loop in confirm then supervised mode with an "operator wins" test needs a hardness_shift plant map and the P6 product feature. Rows C01..C05 cover only P2.5. |
| L5-P7 | pending (feature missing) | No MPC exists. |
