# ADR 011: Write path to a control system (design only, simulator-only skeleton)

Status: **proposed** (2026-10-23), written by the assistant for the owner's review. Nothing in this repository can write to a plant,
and nothing may until this ADR is accepted, its open points are decided and its test suite passes.
Builds on ADR 001 (language split), ADR 009 (configuration is data, extension by process boundary) and ADR 010 (advisory supervisor).

## Context

Modules 1 to 4 are advisory: they read data, give findings and advice, and log what an operator decides. MPC and any closed-loop use of the fuzzy
supervisor need to change something in the control system. A write path is a safety function, not a feature: a wrong write can damage
equipment or injure people, and the plant owner, not this software, carries the responsibility. The design must therefore make unsafe writes
impossible by construction, make every write visible, and let the plant take control back instantly.

## Decision (proposed)

1. **One gateway, separate process.** All writes go through a single Write Gateway program that talks to the control system. Analysis packages
   (`loops`, `fuzzy`, `supervisor`, `anomaly`, `softsensor`, and later MPC) never import an OPC UA client write function and never hold credentials.
   They hand the gateway a *write proposal* (data, schema-validated). Static tests in CI fail if any of those packages imports a write capability
   (extension of the supervisor and anomaly guard tests).
2. **Modes per target, default off.** `off` (nothing happens), `advisory` (today), `dry_run` (the gateway computes and logs the write it would do, sends nothing),
   `confirm` (an operator accepts each proposed write in the HMI, then the gateway writes), `supervised` (writes within the policy without per-write confirmation).
   Only `off`, `advisory` and `dry_run` exist in the first implementation. `confirm` needs this ADR accepted; `supervised` additionally needs the owner's authority model (open point 1).
3. **What may be written.** Only the setpoint of a PID loop that is in an externally settable mode (cascade or remote setpoint, vendor specific). Never the controller output, never
   the mode, never a valve or drive directly, never a tag that is not listed in the write policy. The plant's own PID remains the last controller.
4. **Write policy is data** (schema `write-policy`, ADR 009): per target tag the engineering limits, the maximum step, the maximum rate, the minimum interval, the allowed modes of the loop,
   the operator hold-off time after a manual action, the watchdog period and the read-back tolerance. The gateway refuses anything outside the policy; there is no override flag.
5. **Safety behaviours the gateway must have** (each is a test scenario below): clamp to limits and rate; read-back verification of every write and automatic stop on mismatch;
   a heartbeat the control system can monitor, so that on heartbeat loss the plant returns to its local setpoint; operator priority (any operator change of setpoint or mode disables
   writing to that target for the hold-off time and requires an explicit re-enable); a kill switch that is honoured within one gateway cycle and cannot be bypassed by configuration;
   fail closed on any error, timeout or unknown state; idempotent writes (a repeated proposal does not write twice); every proposal, decision and write is appended to the hash-chained audit log (the `AuditLog` of the supervisor package).
6. **Test suite before code.** A simulator-only suite (package `gateway`, tests only at first) describes the behaviours above as scenarios against a simulated control system.
   They start as expected failures (`xfail`, strict) and become real tests as the gateway is implemented. The gateway is not connected to anything real until the suite passes and the owner has run a supervised site test.
7. **Honest scope.** Whether a given plant accepts writes from an external system, how its cascade handover works and which vendor conventions apply (ABB, Siemens, others) is plant specific and is verified on site, not assumed.

## Test scenarios (skeleton, all strict xfail)

CAS handover (take and give back a loop); watchdog loss (heartbeat stops, plant returns to local setpoint); rejected write (control system refuses, gateway stops and reports); limit and rate clamp;
operator override and hold-off; read-back mismatch; communication loss in the middle of a write sequence; duplicate proposal (idempotence); mode change race; tampered policy file (hash mismatch refuses to start);
kill switch; dry run sends nothing.

## Non-goals

Writes of controller output or mode, direct valve or drive control, safety-instrumented functions, authentication and user management (until the owner decides the authority model), cloud operation, any write to a real system from this repository.

## Open points for the owner

1. Authority model: who may enable `confirm` and `supervised`, who may change the policy, what the operator can always do, how responsibility is recorded.
2. Vendor conventions on the sites in question (cascade, remote setpoint, tracking, bumpless transfer) and who on the plant side supervises the first tests.
3. Watchdog periods and hold-off times the operators accept.
4. Regulatory or company approval needed before any write test (management of change, functional safety review).
5. Whether the first customer wants closed-loop use at all, or advisory and `confirm` only.

## Consequences

- MPC and closed-loop supervisors cannot be connected until the suite passes; this is intended.
- Advisory modules stay unchanged and keep their guard tests.
- The skeleton gives a concrete checklist for the owner's review before any code that can write exists.
