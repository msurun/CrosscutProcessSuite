# ADR 016: Setpoint handover and writes to the setpoint-source or mode node

Status: **Accepted** (owner decision 2026-11-10: the recommendation below).
Builds on: ADR 011 (safety rules), ADR 012 (writes are a product capability), ADR 015 (APC core).

## Context

ADR 012 item 3 and PRODUCT.md section 5 say the gateway never writes the controller output and **never the mode**. The implemented gateway
(Phase 2) nevertheless writes one node besides the setpoint:

- `take_remote`: before the first setpoint write the adapter writes `take_remote.value` to `take_remote.node` so the DCS takes the remote
  setpoint (with `settle_s` wait, L5 finding 1).
- `release`: on watchdog, kill, comm loss, read-back failure or operator takeover the adapter writes `release_value` to `source_node` to hand
  the setpoint back to local control.

Whether that node is a separate setpoint-source switch or the loop **mode** depends on the vendor. In the ABB 800xA style plant map used with
RougherSim both point at `Loop/<id>/Mode` (`take_remote` writes RSP, `release` writes CAS). So today the gateway does write the mode on some
systems. The Phase 2.5 L5 rows found that `release` could switch a loop the operator had just put in MAN back to CAS; PR #73 makes `release`
write only while the node still shows the remote value.

## Options

1. **Never write mode or source.** The DCS owns the handover: an operator or DCS logic puts the loop in remote; the gateway only writes the
   setpoint while the loop is remote, and stops (no release write) when it is not. Watchdog shed is DCS logic on the gateway heartbeat.
   Safest and matches ADR 012 literally; needs DCS-side logic at every site.
2. **Write only the handover node, both ways, with guards** (today plus PR #73). Allowed only for a node the plant map marks as
   `handover`, only between the two configured values (`remote_value` and `release_value`), never to MAN/AUTO/OUT, release only while the
   gateway still owns the setpoint, take only on an explicit operator or engineer action (not automatically on the first write). ADR 012
   item 3 is amended to say so.
3. **Release only.** The gateway may hand back (write `release_value` while it owns the setpoint) but never takes remote; taking remote
   stays a DCS operator action. A middle ground: the fail-safe direction is automated, the risky direction is human.

## Recommendation (assistant)

Option 3 as the default, option 2 as a per-site setting that a lead enables in the policy, recorded in the audit. It keeps the fail-safe
release that the L5 rows rely on, removes the automatic take-over of a loop, and makes the remaining mode write explicit and guarded.

## Decision

1. Default (option 3): the gateway never takes remote. It writes a setpoint only while the source node already shows `remote_value`;
   otherwise the proposal is refused with `not_remote`. Taking remote is a DCS operator action.
2. The gateway may release (write `release_value` to the source node) only while it still owns the setpoint (PR #73).
3. Option 2 is a per-site setting `allow_take_remote` in the write policy (default `false`). Enabling it is a policy change, so it needs the
   lead's pin (ADR 013); the audit records it. Even then the gateway writes only the configured `remote_value` / `release_value`, never
   MAN, AUTO or OUT.
4. ADR 012 item 3 and PRODUCT.md section 5 are amended: "never the controller output; the mode or setpoint-source node only for the
   handover described in ADR 016".
