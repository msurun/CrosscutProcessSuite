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
