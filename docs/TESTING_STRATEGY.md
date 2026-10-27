# Testing strategy without access to a real installation

Last updated: 2026-10-27

## Problem

The suite will eventually write setpoints to real control systems, but during development there is no plant to
test on. The goal is to build confidence in steps, to know exactly which assumptions remain unproven at each step,
and to make the first contact with a real installation as small and safe as possible.

## Principles

1. **Climb a ladder of realism.** Every level proves something specific and leaves something unproven; the unproven
   part is written down in [ASSUMPTIONS.md](ASSUMPTIONS.md) with a plan to retire it.
2. **Test the write path against something we did not write.** Our own OPC UA test server only checks our own
   assumptions; RougherSim or a third-party OPC UA server checks real protocol behaviour.
3. **Make failure modes first-class test inputs.** Real data is messy; the simulators must be able to produce the mess.
4. **Reduce what a first customer has to do.** A read-only product that the customer runs on exported data is the
   cheapest way to meet real data without touching a live plant.
5. **Never test on a plant without a written agreement.** No employer, customer or third-party plant, data or
   documents are used without explicit written permission (see ADR 006 and the provenance rules).

## Ladder

| Level | What | Proves | Does not prove | Stage |
|---|---|---|---|---|
| L0 | Unit and contract tests, CI on Linux and Windows | code and data contracts behave as specified | anything about reality | done |
| L1 | Simulators with known ground truth (Wood-Berry, grinding circuit) | methods recover known effects under stated assumptions | real noise, real faults | done |
| L2 | Fault injection and a messy-data corpus | robustness to bad data, dropouts, stiction, odd export formats | real statistics of these faults | 1 |
| L3 | Public real datasets | behaviour on real measurements for soft sensors, anomaly detection, degradation | closed-loop behaviour | 1 to 2 |
| L4 | Physical lab testbed (e.g. a Temperature Control Lab kit) | real sensor noise, actuator limits, real-time behaviour on actual hardware | industrial scale, DCS semantics | 2 |
| L5 | Virtual DCS: RougherSim (separate repo), ABB 800xA profile over OPC UA with PID block modes, heartbeat watchdog, ground-truth channel and test hooks | write-path semantics, online runtime and tuning cycle against a DCS-like black box; closed-loop behaviour with known ground truth | conformance with a real 800xA; real plant dynamics | 1 to 3 |
| L6 | Customer-run read-only validation on exported data | real data formats and quality, real loop performance | closed-loop control, operator acceptance | 1 to 3 |
| L7 | Pilot under agreement: shadow, then advisor, then one closed loop | everything, for one site | other sites | 3 to 4 |

## L2: reality-gap catalogue (fault injection)

Scenario options to add to the simulators (each is a test input and a documentation item):

- sensors: freeze (flat line), spikes, slow drift, stuck-at, bad or uncertain quality, intermittent dropouts,
  calibration offsets, noise bursts;
- actuators: stiction and backlash, rate limits, saturation, dead zones;
- loops: operator switches modes at random, loop stays in manual, tuning too aggressive or too slow;
- time: timestamp jitter, duplicated and out-of-order samples, daylight saving shifts, clock offset between systems;
- data sources: laboratory results that are sparse and delayed, tags renamed or added mid-history;
- process: start-up and shutdown transients, ore or feed changes, liner or equipment wear (non-stationarity),
  model mismatch between the identified and the true process.

The owner's practical experience with real plants is the best source for this list; it is written down here as
generic phenomena, never as data from a specific site.

**Messy-data corpus:** a generator that writes CSV and spreadsheet files imitating common historian exports
(decimal commas, merged headers, text status strings such as "Bad Input", duplicated timestamps, mixed time zones,
units in headers) so that importers are tested against hostile but realistic files.

## L3: public datasets (check licences and availability before use)

- Flotation plant quality data from a mining process (public on Kaggle): soft sensor and data-quality work.
- Anomaly detection benchmarks (for example SKAB, Numenta Anomaly Benchmark).
- Degradation data (for example NASA C-MAPSS turbofan, IMS bearings) for remaining-useful-life methods.
- Process benchmarks (Tennessee Eastman) for multivariable behaviour.

Each dataset used gets a row in [PROVENANCE.md](PROVENANCE.md) with its licence.

## L4: physical lab testbed

A low-cost thermal control kit (heater, temperature sensors, microcontroller; tens of dollars) gives real noise,
real actuator limits and real-time behaviour. It is bridged to the suite through OPC UA and used to run the full
chain: data collection, identification, PID tuning report, and later a supervised closed loop.

## L5: virtual DCS

(a) RougherSim replaces the soft PLC. It is a separate private repository (msurun/RougherSim, local clone at
..\RougherSim) that imitates an ABB 800xA DCS over OPC UA: PID blocks with modes, heartbeat watchdog, a
process model behind them, a ground-truth channel and test hooks (comm loss, write reject, read-back mismatch,
scripted operator actions, mode-change race).

(b) Crosscut treats RougherSim as a black box. It is tested only through OPC UA and the historian export. Ground
truth is read only by the test, never by product code.

(c) Harness: directory `tests/integration_roughersim/`, pytest marker `roughersim`, skipped when RougherSim is not
installed. The RougherSim version is pinned in a lock file (git tag) and bumped deliberately. The suite runs in a
nightly CI job and before each phase exit, not in the fast per-commit gate.

(d) Every test states its scenario, seed, speed factor and pass criterion.

(e) Honest limit: success means "in our simulator, with our operator model", not a plant claim.

Scenarios: nominal, hardness_shift, step_test, stiction, sensor_faults, operator_actions. Milestones in RougherSim:
M5 scenarios and recording (Crosscut-format Parquet plus ground truth), M6 ABB OPC UA profile, M7 gateway test hooks.

### L5 acceptance matrix

| Crosscut phase | RougherSim milestone needed | Scenario | Pass criterion |
|---|---|---|---|
| P1 (connector, catalogue, runtime) | M5 then M6 | nominal | before M6: Crosscut loader reads the recording unchanged and loop triage works; after M6: catalogue built in the GUI, live loop KPI within tolerance of the ground-truth KPI, no file edited by hand (e2e) |
| P1 data quality | M5 | sensor_faults | onboarding data-quality report flags injected faults with agreed precision and recall |
| P2 Write Gateway | M7 | all 12 gateway scenarios | 12 strict-xfail scenarios in gateway/tests pass without manual intervention; e2e proposal -> confirm -> write -> read-back -> audit entry; kill switch stops writes within one cycle |
| P3 tuning release | M4+M6 | step_test, stiction, nominal | weak loop detected -> step test -> tuning -> write after confirmation -> KPI improves vs ground truth -> rollback restores the old parameters |
| P4 virtual-sensor engine | post-MVP (lab samples) | hardness_shift | generic engine reproduces ground-truth quality within stated error; validity flag trips on injected analyser fault |
| P6 fuzzy closed loop | M7 | operator_actions, hardness_shift | proposals flow through the gateway in confirm then supervised; operator action always wins |
| P7 MPC | after MVP | step_test, hardness_shift | MPC writes setpoints through the gateway in supervised mode and respects constraints |

## L6 and L7: customer-run validation and pilot

- **Customer-run validation kit:** a short guide for exporting data (tag list template, CSV format, time range),
  a data-readiness checklist, an anonymization script and a report template. The customer runs the analysis on their
  own machine and shares only the report. No network access to the plant is needed.
- **Pilot partner:** an academic pilot plant, a research institute or a friendly site. Preconditions: written
  agreement and NDA, data processing terms, an IT/OT security review, a rollback plan and insurance clarified.
  Sequence: historical data, shadow mode, advisor, one closed loop with hard limits in the DCS.

## Exit criteria (indicative, to be tuned)

- L2: loop monitoring and data cleaning flag the injected faults with agreed precision and recall; no crash on any
  corpus file.
- L3: soft sensors and anomaly detection reproduce published baselines on the public datasets.
- L5: all rows of the L5 acceptance matrix for the current phase pass against the pinned RougherSim version without
  manual intervention.
- L6/L7: defined per partner agreement.

## Backlog

| ID | Task | Stage |
|---|---|---|
| V1 | Fault-injection layer for the simulators (list above) | 1 |
| V2 | Messy-export corpus generator and importer robustness tests | 1 |
| V3 | Public dataset benchmarks (flotation quality, anomaly, degradation) | 1 to 2 |
| V4 | Lab testbed bridge via OPC UA | 2 |
| V5 | Virtual DCS = RougherSim (separate repo, plan in its docs/IMPLEMENTATION_PLAN.md); replaces the soft PLC | 2 to 3 |
| V6 | Customer-run validation kit (export guide, checklist, anonymizer, report) | 1 |
| V7 | Pilot partner package (agreement outline, security checklist) | 3 |
| V8 | Keep [ASSUMPTIONS.md](ASSUMPTIONS.md) current at every stage review | continuous |
| V9 | Integration harness tests/integration_roughersim/ with pinned version and `roughersim` marker | 1 |
| V10 | Nightly CI job running the L5 acceptance matrix | 2 |
