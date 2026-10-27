# Crosscut Process Suite — Product definition

This document is the single product definition of the Crosscut Process Suite. It replaces `docs/PROJECT_DESIGN.md`, which is kept only as a historical record. The ADRs in `docs/adr/` override this document where they conflict. Date: 2026-10-27.

## 1. Product definition

Crosscut is an on-prem server with a browser console in which a process engineer configures the system **without programming** (the *no-code* principle): they connect a historian or DCS of any vendor, analyse and model the process (loops, virtual sensors, anomalies, rules, MPC, optimisation), run the models online, and change setpoints in the control system through one safe **Write Gateway**, in modes `advisory` → `confirm` → `supervised`.

| User | Role |
|---|---|
| Process engineer | Connects sources, builds the project catalogue, designs and deploys models. Owns no-code configuration. |
| Operator | Works the console, accepts or rejects proposed writes in `confirm` mode. |
| Controls engineer | Owns the write policy, the gateway configuration and the safety settings. Supervises anything that touches a controller. |

Principles that do not change: plant data validates features and never defines them. No tag name, unit, missing-value code, window or threshold of one plant may be a constant in `*/src`. Every feature works on any tag, lab, analyser and loop the user configures. Real plant data stays outside the repository.

## 2. Owner decisions of 2026-10-27

1. Writes are a product capability, implemented through one Write Gateway. `confirm` and `supervised` modes are in scope for v1.
2. First complete product: loop monitoring plus PID tuning, from data intake to online work with writes.
3. Connector order: OPC UA → PI → SQL/ODBC → the rest.
4. Deployment: on-prem server plus browser. No cloud.
5. A DCS simulator imitating ABB 800xA is a separate project (Phase 1a).

Earlier documents recorded a "no writes to a plant" position (PROJECT_DESIGN §1, ADR 010, ADR 011 preamble). That position is superseded by ADR 012. The safety rules of ADR 011 remain in force.

## 3. Architecture layers

| Layer | Responsibility | Exists today | Gap |
|---|---|---|---|
| **Connect** | Read history and live values, browse metadata; write only through the gateway | CSV wide/long import, SQLite and any DB-API/ODBC connection (pyodbc is not a dependency), OPC UA polling and subscription, a Parquet collector | One connector interface. No PI Web API, IP.21, PHD, AVEVA, OPC DA/HDA |
| **Project catalogue** | Sources, tags, units, ranges, missing codes, time zone, loops (PV/SP/OUT/mode/PID parameters in vendor form), lab definitions; edited in the GUI | Does not exist. Import settings (missing codes, −9999 sentinel) live in `loops/.../plant_import.py` as code-level settings | Whole layer. The −9999 default constant must be removed (issue #42) |
| **Engines** | Offline design mode and online run mode for each module | Loops, fuzzy, supervisor, anomaly, soft sensor: offline, on demand, over a stored window | Online run mode. Generic schema-driven configuration editor |
| **Runtime** | On-prem service (Windows service or systemd) runs deployed jobs cyclically: loop KPI, anomaly scan, soft-sensor estimate, fuzzy advice. Status, error log, start/stop from the GUI | Does not exist | Whole layer |
| **Write Gateway** | Separate process. Writes proposals only. Policy as data, read-back, watchdog, operator priority, kill switch, audit | `gateway/` holds interfaces and 12 strict-xfail scenarios. Write code exists only against a simulator | Full implementation (Phase 2) |
| **Web console** | Browser UI: Trends, Loops, Fuzzy, Advisor, Anomalies, Soft sensor, Import, Steps | React + TypeScript frontend, e2e suite green. Some configurations are read-only in the GUI | Configuration editing for supervisor, anomaly and soft sensor; proposal queue; login and roles |

## 4. Modules

### 4.1 Loop monitoring and PID tuning — first release

**Purpose.** Triage of loops: which are healthy, which need attention, and what to do next.

**Ships today.** Worklist with findings (manual, saturated, flatline, oscillating), ACF oscillation test, valve checks and guided stroke test, tuning report (SIMC/AMIGO, FOPDT; integrating loops experimental), benefit estimate, Steps view.

**Gap to product.** Module-level tuning must be closed as a product loop: detection → test → tuning → write after confirmation → KPI check → one-click rollback. The blind worklist review and a real valve stroke test remain owner tasks.

**Phase.** 3.

### 4.2 Virtual sensors

**Purpose.** Estimate a quality variable from lagged process tags when the lab is late and sparse or an analyser is delayed.

**Ships today.** The engine (`softsensor/`) is generic with respect to tags, but:

- it supports PLS only and runs offline only;
- the GUI can only read a configuration; a new configuration can be added only with the "Load example" button;
- there is no `reference input` in the code. An online analyser can only be an ordinary input tag. PROJECT_DESIGN §4.4 claimed a reference input exists; this document corrects that;
- bias correction is always on; its parameters are constants in `softsensor/.../bias.py`.

**Validation case.** The plant-1 analyser work (exp31, `tools/analyzer_vs_lab.py`, `tools/lab_extract.py`) is a validation case for the generic engine, not a feature in itself. It is absorbed in Phase 4.

**Gap to product (Phase 4).** Target types lab, analyser, or both as user configuration: stamp meaning (start, end, or middle plus offset), composite sample window, analyser latency, missing codes and validity ranges. Lag search. Explicit `reference input`. Bias correction switchable, parameters in the schema. Model library: PLS, ridge/linear, one non-linear model (gradient boosting), always blocked CV, comparison table against "last lab value". GUI wizard: target → proposed inputs → train and compare → deploy to runtime → optionally write the estimate to a DCS tag through the gateway.

**Phase.** 4.

### 4.3 Anomaly detection (part of monitoring)

**Purpose.** Flag drift, freeze and out-of-model events, and name contributing tags.

**Ships today.** PCA with T2 and SPE, lagged columns, stuck-sensor rule, possible-ramp warning. exp29 round 3 met its criteria.

**Gap to product.** Becomes a monitoring job in the runtime. Detector limits need real quiet data (≥ 2 weeks plus labelled events, owner task). Configuration editable in the GUI (supervisor/anomaly configurations are read-only today).

**Phase.** 1 (online job) and 3 (product view).

### 4.4 Fuzzy / expert supervisor

**Purpose.** Process-level advice (first validation case: a feed rate), gated by loop state, explained, logged, acknowledged.

**Ships today.** Fuzzy Studio (full editing of variables and rules, versions, replay, backtest); advisory supervisor gated by module-1 loop state, explained by its dominant rules; hash-chained audit log with operator acknowledgement; modes `off` and `advisory`. exp27 met its frozen criteria in simulation.

**Gap to product.** Supervisor configuration editable in the GUI (Phase 1 generic editor). Advice becomes a write proposal to the gateway: `confirm` first, `supervised` later.

**Phase.** 1 (configuration editor) and 6 (closed loop).

### 4.5 MPC

**Purpose.** Constrained multivariable control above the base PID layer.

**Ships today.** Nothing. There is a plan and a C++20 smoke test with a Python parity test.

**Gap to product.** Identification from step tests (Steps view plus a generalised driver-response tool), an editable model matrix in the GUI, linear MPC with constraints (QP), C++ runtime per ADR 001, setpoint writes through the gateway in `supervised` mode.

**Phase.** 7.

### 4.6 ML and optimisation

**Purpose.** Operating-range recommendation and an economic layer (RTO) above MPC and fuzzy.

**Ships today.** Nothing. The only "ML" in the repository is PLS and PCA.

**Gap to product.** Real historian data, a checkable confounding analysis, the economic objective and limits (owner decision, not decided). Plan of work to be proposed by the assistant and accepted by the owner.

**Phase.** 8.

## 5. Writing to the control system

ADR 012 ("Writes are a product capability", `docs/adr/012-writes-are-a-product-capability.md`) replaces the no-write position of ADR 010 and ADR 011. It is written alongside this document. The safety rules of ADR 011 keep their force.

- Only the Write Gateway writes. It is a separate process. Analysis packages never import write code and never hold credentials. CI guard tests now mean "only the gateway writes", not "nothing writes".
- Write policy is data (schema `write-policy`). Limits, maximum step, maximum rate, minimum interval, allowed loop modes, hold-off time, watchdog period, read-back tolerance. No override flag.
- Read-back verification of every write. Watchdog the control system can monitor. Operator priority: any manual change disables writing to that target for the hold-off time. Kill switch honoured within one gateway cycle, not bypassable by configuration. Hash-chained audit of every proposal, decision and write.
- Allowed targets: setpoints of loops in cascade or remote-setpoint mode; PID tuning parameters (`confirm` only); output tags of virtual sensors. Never the controller output or the mode. A step-test assistant writing OUT in manual is an open owner decision (section 10).
- Modes per target, default `off`: `off`, `advisory`, `dry_run`, `confirm`, `supervised`. Version 1 implements all five. PID tuning parameters are written in `confirm` only; `supervised` is allowed for loop setpoints and virtual-sensor tags within the policy. Who may enable `supervised` is an owner decision (section 10).
- Authentication, roles (engineer, operator) and login are required before `confirm`. Local users only.
- The simulator of Phase 1a replaces the "soft PLC" of earlier plans. The 12 gateway scenarios become real tests against it in Phase 2.

## 6. DCS simulator (separate repository, Phase 1a)

A separate project that Crosscut sees only as a black box through OPC UA and historian export. Ground truth is exposed on a separate channel. It is the base for a future simplified flowsheet-modelling tool for metallurgists.

The repository is RougherSim (github.com/msurun/RougherSim, private, no licence yet); its plan is `docs/IMPLEMENTATION_PLAN.md` there, milestones M0-M7.

- **Process model as data.** Flowsheet JSON plus a unit library: feeder and conveyor with transport delay, ball mill, sump with pump, hydrocyclone, flotation bank of 3–4 cells with level and air (kinetic model), a simple cleaner, a concentrate thickener. Valves with deadband and stiction. Transmitters with noise, quantisation and historian compression. Separate mass balance for solids, water and minerals. Realistic couplings: integrating levels, inter-cell interaction, ore hardness and feed disturbances. About 20–30 PID loops including cascades. Starting point is the existing grinding model in `sim/`.
- **Vendor profile as a replaceable layer.** First ABB 800xA / AC 800M: OPC UA address space and 800xA-style naming; PID block semantics (Man/Auto/Cascade/Remote SP, tracking, bumpless, Gain/Ti/Td names and units); alarms and events; historian export format. We do not imitate Operator Workplace or Aspect Objects. Second profile: Siemens (PCS 7 / S7 PID).
- **Operating modes.** Real time and accelerated. Scripted operator actions. Fault injection. Scenario recording.
- **Limitation to state openly.** The imitation proves our understanding of 800xA, not conformance with a real 800xA. Real-stack checks: Siemens PLCSIM Advanced trial (cheap check of the Siemens profile); ABB SoftController only with a legal ABB licence, in a legal environment, done by the owner. No unofficial downloads.

The DCS simulator replaces the "soft PLC" for the gateway scenarios in Phase 2 and for the tuning cycle in Phase 3.

Tests of Crosscut against RougherSim are a product deliverable, not an afterthought: every phase exit that names the simulator maps to a row of the L5 acceptance matrix in `docs/TESTING_STRATEGY.md` (scenario, seed, pass criterion), run through the harness `tests/integration_roughersim/` against a pinned RougherSim version. Ground truth is read only by tests.

## 7. Phases

Every phase has a short detailed plan before its start and its own gates: `ruff`, `pytest` for the whole repository, `vitest`, `tsc`, `build`, `e2e:all`.

| Phase | Goal | Exit criteria |
|---|---|---|
| **Phase 0** — Cleanup, no new features | This document replaces PROJECT_DESIGN. ADR 012 replaces the no-write position. Guard tests change meaning. `docs/archive/` for one-off plans and documents. `tools/` marked for absorption. Anti-drift rule in `CLAUDE.md`. GitHub milestones 0–8. Closed experiment lines (stiction, ACF, idle) are **not** moved; `experiments/README.md` indexes their status | All gates green after moves. No dead links in docs. `git mv` preserves history |
| **Phase 1** — Online foundation | One connector interface (browse, metadata, history, live, write-through-gateway only). Project catalogue plus GUI editor. Runtime as an on-prem service. Generic configuration editor generated from `schemas/*.schema.json` | Simulated OPC UA server → catalogue built in the GUI → runtime computes live loop KPI and shows it in the console. No file edited by hand (e2e test) |
| **Phase 1a** — DCS simulator | See section 6 | Simulator runs as OPC UA server in ABB profile. Phase 1 Crosscut connects, builds the catalogue, computes live KPI. Mass balance closes (test). Loop step responses match ground truth |
| **Phase 2** — Write Gateway v1 | Implementation per ADR 012: `off`, `advisory`, `dry_run`, `confirm`, then `supervised`. First write protocol: OPC UA. Write policy schema and GUI editor. Proposal queue in the console. Roles and login | All 12 gateway scenarios pass against the Phase 1a DCS simulator. e2e shows proposal → confirm → write → read-back → audit entry; kill switch stops in one cycle. Gateway, policy and permissions pass review |
| **Phase 3** — Module 1 as a complete product (first release) | Online monitoring of all catalogue loops. Tuning path from detection to write after confirmation, KPI check, one-click rollback. Optional step-test assistant | Full cycle on the DCS simulator: weak loop detected → test → tuning → write after confirmation → KPI improvement → rollback works. Then a pilot at the owner's site in `confirm` mode |
| **Phase 4** — Universal virtual-sensor engine | See section 4.2 | A lab-and-analyser configuration built entirely in the GUI reproduces the exp31 numbers. exp30 (synthetic) still meets its criteria. Blind test on the next data delivery |
| **Phase 5** — Connectors | PI (PI Web API, optionally AF SDK); SQL/ODBC profiles (IP.21, PHD, AVEVA/Wonderware Historian, WinCC); OPC DA/HDA through a wrapper or proxy UA; Excel and Parquet | Each connector covers history, live read and metadata. Each has a test on a recorded fixture. Real-source tests are owner tasks. Writes stay gateway-only |
| **Phase 6** — Fuzzy closed loop | Supervisor advice becomes setpoint write proposals through the gateway: `confirm` first, then `supervised` | Write proposals flow through the gateway; run in `confirm` then `supervised` tested against the DCS simulator |
| **Phase 7** — MPC | Identification from step tests and an editable model matrix in the GUI. Linear MPC with constraints (QP) checked on `sim/`. C++ runtime per ADR 001 | MPC writes setpoints through the gateway in `supervised` mode against the DCS simulator |
| **Phase 8** — ML and optimisation | Operating-range recommendation and an economic layer (RTO) above MPC and fuzzy | Plan accepted by the owner. Economic objective and limits supplied by the owner |

## 8. Evidence discipline and claim limits

- Frozen protocols: an experiment freezes and commits its protocol before any run. Test seeds run once. Misses ship visibly; thresholds are not moved.
- Experiments serve the product features in this document. They are not a separate line of work.
- Simulator success is not a plant claim. Findings say "in our simulator, with our operator model".
- Real plant data stays outside the repository.

See `docs/TESTING_STRATEGY.md` (L0–L7 ladder), `docs/ASSUMPTIONS.md` (unproven assumptions and retirement plans), `experiments/README.md` (experiment index and status).

## 9. Anti-drift rule

Enforced for every task, and written into the repository `CLAUDE.md` in Phase 0:

1. Every task names the module and phase in this document.
2. Work on plant data yields a generic engine feature plus an example configuration, or nothing.
3. A new top-level element (package, experiment line, tool) requires the owner's approval.

## 10. Open owner decisions

| # | Decision | Blocks |
|---|---|---|
| 1 | First pilot DCS (ABB or Siemens) for PID-parameter writes and CAS conventions | Phase 3 pilot |
| 2 | Whether the step-test assistant may propose OUT writes in manual (`confirm` mode) | Phase 3 exit criteria |
| 3 | Licence of the separate DCS simulator project RougherSim (name decided); whether Siemens PLCSIM Advanced (trial) is the second check | Phase 1a |
| 4 | Whether there is legal access to ABB SoftController (Compact Control Builder) to check the ABB profile on a real stack | Phase 1a ABB verification |
| 5 | ADR 008 licence (AGPL-3.0-only) review | Release terms |
| 6 | Blind worklist review (≈20 loops) | Module 1 evidence |
| 7 | One real valve stroke test | Module 1 evidence |
| 8 | Optimisation objective (economic value per PV unit, operating limits) | Phase 8 |
| 9 | Write authority model: who may enable `confirm`/`supervised`, who may change policy, what the operator can always do | Phase 2 `supervised` |

Also still relevant from PROJECT_DESIGN §8: real level step test (integrating loop), anomaly real data (≥ 2 weeks quiet plus labelled events), soft-sensor real data (lab timestamps, delay, tags), lab-stamp and missing-value-code meaning, analyser latency, UaExpert check and one ABB `PidCC` TI/TD export, ramp-warning precision against real archive gaps, next data delivery kept untouched for a blind exp31 test.

## 11. Document map

| Document | Use |
|---|---|
| `README.md` | Status, per-module claim limits, quick start |
| `docs/PRODUCT.md` | This document: the single product definition |
| `docs/PRODUCT.pl.md` | Polish companion of this document |
| `docs/HANDOFF.md` | State of work, real-data notes, working rules |
| `docs/IMPLEMENTATION_LOG.md` | Per-step implementation detail |
| `docs/TESTING_STRATEGY.md` | L0–L7 ladder, fault-injection catalogue, backlog |
| `docs/ASSUMPTIONS.md` | Unproven assumptions and retirement plans |
| `docs/PROVENANCE.md` | Public sources and third-party datasets |
| `docs/OWNER_TASKS.md` | What only the owner can do; what to bring back |
| `docs/adr/001` | C++ runtime, Python offline tooling (accepted) |
| `docs/adr/008` | AGPL-3.0-only licensing |
| `docs/adr/009` | Configuration is data (proposed) |
| `docs/adr/010` | Advisory supervisor, no writes (proposed; write position superseded by ADR 012) |
| `docs/adr/011` | Write path design; safety rules still in force |
| `docs/adr/012` | Writes are a product capability |
| `experiments/README.md` | Experiment index and status (closed lines stay in place) |
| `docs/archive/` | One-off plans and documents |
| `docs/PROJECT_DESIGN.md` | Historical record only; not maintained |