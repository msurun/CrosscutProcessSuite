# ADR 012: Writing to the control system is a product capability

Status: **accepted in principle by the owner** (2026-10-27); the gateway safety design (ADR 011) remains to be reviewed before any
write to a real system.
Supersedes: the no-write stance of ADR 010 (the supervisor "cannot write") and the "design only, nothing may ever write" framing of
ADR 011. ADR 011's safety design stays and becomes the specification of the Write Gateway.
Builds on ADR 001 (language split), ADR 009 (configuration is data) and ADR 011 (write path).

## Context

The product goal is to optimise processes: the fuzzy supervisor, MPC, optimisation and PID tuning. Without writing to the control
system none of this can act; an advisor that only suggests leaves the last step to the operator and limits the benefit.

Earlier documents hardened "advisory first" into "no writes by design" without an owner decision. On 2026-10-27 the owner decided
otherwise: writes are part of the product, through one Write Gateway, with `confirm` and `supervised` modes in the first version.
The first complete product is loop monitoring plus PID tuning, deployed as an on-premise server with a browser client.

## Decision

1. **Writing is a product capability, but only the Write Gateway writes.** The gateway is a separate process, the only holder of
   write credentials and the only code that imports a write function. Analysis packages (`loops`, `fuzzy`, `supervisor`, `anomaly`,
   `softsensor`, later MPC) produce schema-validated write proposals. The existing CI guard tests keep their checks; their meaning
   changes from "nothing writes" to "only the gateway writes".
2. **Allowed write targets.** Every target is listed per tag in the write policy (schema `write-policy`, ADR 009):
   (a) setpoints of PID loops in an externally settable mode (cascade or remote setpoint, vendor specific);
   (b) PID tuning parameters (gain, integral time, derivative time in the vendor form), in `confirm` mode only, never `supervised`,
   with the previous values stored so that a one-click rollback proposal can be made;
   (c) output tags of virtual sensors (estimates published to the DCS).
   Never the controller output, never the mode, never a valve or drive directly.
   Open owner decision: a step-test assistant that proposes OUT steps on a loop in manual, in `confirm` mode only.
3. **Modes per target, default off.** `off`, `advisory`, `dry_run`, `confirm` (an operator accepts each write) and `supervised`
   (writes within the policy without per-write confirmation). Version 1 implements all five. `supervised` is allowed only for
   target types (a) and (c).
4. **Safety behaviours from ADR 011 are mandatory and tested:** clamp to limits and rate, read-back verification with automatic
   stop on mismatch, heartbeat and watchdog with fallback to the local setpoint, operator priority with hold-off, a kill switch
   honoured within one gateway cycle, fail closed on any error, idempotent writes, and a hash-chained audit log of every proposal,
   decision and write.
5. **Authentication and roles before `confirm`.** Local users with two roles: `engineer` edits the policy and enables modes,
   `operator` confirms or rejects writes. Every write records the authenticated user. Who may enable `supervised` is an owner
   decision recorded in the policy.
6. **Test ladder before any real system.** First, the 12 gateway scenarios pass against a DCS simulator (a separate project that
   imitates ABB 800xA / AC 800M over OPC UA; a Siemens profile later). Then a real vendor stack where legally available
   (Siemens PLCSIM Advanced trial, ABB SoftController with a licence). Finally a supervised site test run by the owner in `confirm`
   mode. The first write protocol is OPC UA.
7. **Responsibility.** The plant's own PID stays the last controller. Whether a plant accepts external writes, how its cascade
   handover works and which management-of-change approval is needed are verified on site, not assumed.

## Non-goals

Writes of the controller output or the mode, direct valve or drive control, safety-instrumented functions, cloud operation,
`supervised` writes to tuning parameters, user code in the gateway.

## Consequences

- MPC, fuzzy closed loop and virtual-sensor publishing become possible after Phase 2 (Write Gateway v1).
- The ADR 010 mode enum gains `confirm` and `supervised`, reachable only through the gateway.
- The guard tests change in wording only; they still fail if an analysis package imports a write capability.
- `docs/PRODUCT.md` section 5 summarises this ADR.

## Open points for the owner

1. The first pilot DCS (ABB or Siemens), and its cascade, remote-setpoint and parameter-write conventions.
2. Watchdog periods and hold-off times the operators accept.
3. Who may enable `supervised`.
4. Whether the step-test assistant is in scope for version 1.
5. Company approval needed before a site test (management of change, functional-safety review).