# ADR 016: Setpoint handover and writes to the setpoint-source or mode node

Status: **Proposed** (2026-11-10), for the owner's decision. Until decided, the behaviour described under "Today" stays as is, with the
safety fix of PR #73.
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

Open (owner).
