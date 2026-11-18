# ADR 015: APC core (shared variable model and controller host)

Status: **Accepted in direction** (owner decision 2026-11-10); detailed design per step in `docs/PHASE2_5_PLAN.md` before coding.
Builds on: ADR 009 (configuration is data), ADR 012 (writes are a product capability), ADR 013 (roles and authority), ADR 014 (tuning write path).

## Context

A review on 2026-11-10 judged the implemented modules against an APC-framework yardstick. The building blocks are sound (Write Gateway, loop
monitoring and tuning, SISO identification, explained fuzzy rules), but they are islands: each works on stored datasets and keeps its own idea
of a variable. Concretely:

- the live catalogue (`schemas/site.schema.json`) has no MV/CV roles, operator or move limits, priority or on/off; `schemas/project.schema.json`
  has MV/CV/DV roles but nothing loads it;
- the runtime schedules jobs but hosts no controller and has no controller state, overrun monitoring or heartbeat;
- connectors return no time-aligned cycle snapshot and do not turn staleness or lost communication into a variable status;
- anomaly findings and virtual-sensor validity never reach a per-variable status a controller could act on;
- the fuzzy supervisor has its own variable model, runs on request and holds all advice when one input is bad;
- the gateway sheds locally but does not tell a controller which MVs are available.

## Decision

1. Crosscut is an APC framework. A new **Phase 2.5 "APC core"** comes before Phase 3 (the module 1 release waits for it).
2. One variable model lives in the catalogue: roles MV, CV, DV and inferential CV; engineering, operator, validity, move and rate limits;
   priority; operator on/off. `project.schema.json` is merged into it or removed; there is one schema for variables.
3. A live variable status (good / uncertain / bad plus reason) is computed per cycle from source quality, staleness, communication loss,
   anomaly findings and virtual-sensor validity. Modules publish into it; controllers read from it.
4. Each base loop publishes a readiness signal (mode, saturation, valve health, gateway hold-off) used to decide whether it may serve as an MV.
5. The runtime hosts controllers: fixed cycle, overrun monitoring, state machine `off` / `standby` / `on` / `shed` with initialisation,
   restart-safe state and a heartbeat. A bad CV is dropped from the controller; an unavailable required MV or lost communication sheds it.
6. Controllers only propose writes. The Write Gateway (ADR 012-014) stays the only writer; its policy, mode ladder, roles and audit apply
   unchanged. The gateway reports MV availability back to the controller host.
7. The fuzzy supervisor is the first controller on this core; MPC (Phase 7) reuses it without a second variable model.
8. An operator console shows controller and variable state and lets the operator switch them and set operator limits, under ADR 013 roles.

## Consequences

- Phase 3 work that needs loop readiness or live status waits for the matching Phase 2.5 step; pure tuning-path fixes may continue.
- Exit test of Phase 2.5: the fuzzy supervisor runs as a controller against RougherSim in closed loop; a bad CV is dropped, a lost MV or
  comms sheds to base control, a restart restores the controller state, and the operator switches controller and variables in the console.
- Simulator results are not plant claims (PRODUCT.md section 8).

## Open points (for the Phase 2.5 plan)

- Controller cycle period range and what counts as an overrun.
- Whether the heartbeat to the DCS stays in the gateway only (today) or the controller host gets its own.
- Who may switch a controller `on` (role), and whether `on` requires the gateway target mode `confirm` or `supervised`.
