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

## Owner decisions (2026-11-18)

- Controller cycle period: default 30 s, allowed range 10 s to 5 min (`cycle_s` 10-300 in `site.schema.json`). An overrun is a start
  later than period x 1.1 after the previous start (`OVERRUN_MARGIN`).
- Overruns in a row before `shed`: configurable per controller (`max_overruns`), default 5.
- An operator may switch a controller `on` (permission `ctl.operate`, held by `operator` and up). Gateway target mode `supervised` is
  enough; `confirm` is not required. In `off`, `advisory` or `dry_run` the gateway refuses the writes (`mode_no_write`).

- Heartbeat and liveness (owner, 2026-11-18): exactly ONE heartbeat goes to the DCS, sent by the gateway (unchanged). The runtime is
  monitored too, inside Crosscut:
  - the runtime process sends a liveness beat to the gateway through the file mailbox (signed command, no DCS access);
  - each controller that is `on` sends its cycle beat (controller id, state, cycle count) to the gateway every cycle;
  - the gateway marks a controller lost when no beat arrives within `liveness_cycles` x `cycle_s` (default 3), releases the targets
    proposed by that controller to the DCS (local setpoint), and audits `runtime_lost`; a lost runtime process does the same for every
    controller it hosts;
  - liveness of the runtime and of each controller is shown in the operator console with an alarm;
  - the per-target write watchdog (`watchdog_s`) stays as the second line; a configuration with `watchdog_s` < 2 x `cycle_s` is refused.

Liveness implementation (#112):
- Mailbox command `liveness` (args: kind `runtime`|`controller`, id, state, count, cycle_s, liveness_cycles, targets), sent by the service principal `svc:controller:<id>` / `svc:runtime:runtime` with the existing `gw.propose` permission (service role unchanged, no new permission). The controller beat goes out after every controller cycle; the runtime process beat every 10 s (3 cycles = 30 s) while controllers are hosted.
- The beat carries the sender's own `cycle_s` and `liveness_cycles` (site `controllers[].liveness_cycles`, integer >= 2, default 3), so the gateway needs no site file. `gateway/liveness.py` keeps the newest beat per sender; lost = silence longer than `liveness_cycles x cycle_s`, and only when the controller was `on` in its last beat or still holds a target. A lost controller has every target it holds (proposer `controller:<id>`) released through the normal release path and one `runtime_lost` audit event (reason `controller:<id>` or `runtime`). A lost runtime does the same for all controllers. A new beat clears the flag. One runtime per gateway is assumed. No DCS write is added; the gateway's own heartbeat stays the only one.
- The `watchdog_s` >= 2 x `cycle_s` rule is checked where both are known: the gateway, on each beat (the beat names the controller's target tags). A violating beat is refused (error reply, audit `liveness_refused`), so the controller never counts as alive and its targets are released after the liveness window. Site and policy are separate files, so there is no earlier common point.
- No beat, no writes: a proposal whose proposer is `controller:<id>` is refused with `liveness_missing` (audited as a refused proposal) unless that controller has a fresh, accepted beat (a refused beat also drops the earlier one). Other proposers are unaffected.
- A failed release of a lost controller's target stays pending and is retried on every gateway tick; the failure is audited once per target.
- Read-only exposure: gateway `state.json` has `liveness` (age_s, state, count, lost per sender); `GET /controllers[/{id}]` adds `gateway_liveness` {known, age_s, lost, runtime_lost, runtime_age_s} and `liveness_cycles`; the Controllers page shows the beat age and an alarm text when lost.
