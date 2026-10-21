# ADR 010: Module 2 is an advisory supervisor that cannot write to a plant

Status: **proposed** (2026-10-21), written by the assistant for the owner's review. Work proceeds on the proposal.
Builds on ADR 009 (configuration is data) and `docs/NEXT_MODULE_OPTIONS.md`.

## Context

Module 1 (loop monitoring and tuning) is closed. The fuzzy engine, backtest, versions and API already exist, but nothing
turns a rule-base output into advice that is gated by loop health, explained, logged and acknowledged by an operator.
The main risk, stated in `NEXT_MODULE_OPTIONS.md`, is that a fuzzy supervisor is easy to build and hard to show better
than a simple crisp rule. The earlier backtest (exp09) also left 43 % of operator moves facing a silent rule base.

## Decision

1. **Scope.** Module 2 is a process-level setpoint advisor (the first target is the mill feed setpoint) whose advice is
   gated by module 1 loop state, written to an append-only hash-chained audit log, acknowledged by a person, and judged
   against a crisp baseline rule in closed-loop simulation. It is not a fuzzy re-implementation of the module 1 worklist.
2. **No-write invariant.** The package `crosscut_supervisor` and its routes never import `opcua` or `connectors` and
   write only under `_advisory/` and `_supervisor/` of the data root. A test walks the import graph and fails otherwise.
3. **Mode enum.** The configuration schema allows `mode` in `["off", "advisory"]` only. A `closed_loop` value is
   impossible until a write-path ADR is accepted.
4. **Fail closed.** A missing loop row, a not-assessed gate, or an input that is NaN or outside its variable range gives a
   blocked gate and an advice record without magnitude.
5. **Configuration is data** (ADR 009): a schema-validated JSON file names the fuzzy system and version, the output, the
   target loop, the gates and the thresholds. No user code runs in the process.
6. **Honest language.** The strongest firing strength is called `activation`, never confidence. The `who` of an
   acknowledgement is free text, not authenticated. Evidence claims are limited to "in our simulator, with our operator
   model".

## Non-goals

Any OPC UA or DCS write, CAS or closed-loop mode, MPC, auto-calibration of membership functions, user authentication,
live OPC UA subscription (dataset and replay only), soft-sensor inputs, a fuzzy re-scoring of the worklist, user code.

## Consequences

- The module can ship without a plant connection and still be useful as a logged, reviewable advice trail.
- If the benefit experiment (exp27, criterion E3) fails, the module ships with the claim "pipeline and gating verified; no
  benefit over a crisp rule shown".
- A later write path needs its own ADR, an operator-authority model and a new schema version.
