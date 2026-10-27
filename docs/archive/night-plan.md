# Plan for the unattended night 2026-10-22/23

Working plan for one unattended session. Each step ends green (ruff, mypy, pytest, vitest, e2e with axe where a GUI exists) before the next starts. Decisions stay in ADRs; this file is the order of work and the stop rules.

## Rules

| Rule | Meaning |
|---|---|
| Small steps | Each step is one reviewable change. Verify before the next one. |
| Commit per green step | Commit after each green step. Push `main` is allowed. Never force-push. |
| GUI with each feature | Every implemented feature has its UI, strings in en/pl/es, vitest, and an e2e check with axe. |
| Frozen criteria | Pass criteria are written here or in the experiment README before the first run. |
| Stop on a miss | When a frozen criterion misses, stop that module line and write the result honestly in its README. |
| No test-seed retuning | Tune only on development seeds. Never retune on test seeds. |
| Lead checks math | The lead re-derives T2 and SPE limits against one textbook example and checks every delegate's math. |
| Hygiene per module | PROVENANCE row, ASSUMPTIONS row, HANDOFF rewritten to the current state, memory updated. |

## Seed ranges

| Use | Seeds |
|---|---|
| Development | 29001-29199 |
| Frozen test | 29201-29399 |
| Reserve | 29401 and up |
| exp28 round 2 (already fixed) | 30001-30788 |

## Ruled out tonight

| Candidate | Reason |
|---|---|
| MPC | No write path exists or is approved. |
| Optimisation | The owner has not given an objective (see `docs/OWNER_TASKS.md`). |
| DML operating-range recommender | Its only truth is the author's own generator, so it cannot be validated. |

## Step 0: exp28 round 2 (integrating-loop dead time)

Protocol is frozen in `experiments/exp28_integrating_step_test/README.md`. Do not change it.

| Item | Done when |
|---|---|
| Run round 2 on seeds 30001-30788 | Results written to the exp28 README with the upper bound of the integrating-loop dead time. |
| GUI | Dead-time range shown as a range (lower to upper bound). Settings use the upper bound and say so in the label. |
| Verify | GUI en/pl/es strings, vitest, e2e with axe. |

## Step 1: Module 3, anomaly detection

Package `anomaly/`. Advisory only.

| Part | Content |
|---|---|
| Method | PCA with Hotelling T2 and SPE. Limits per Jackson and Mudholkar (1979) for SPE and MacGregor and Kourti (1995) for multivariate monitoring. |
| Schema | `schemas/anomaly.schema.json` |
| Guard | Advisory-only guard test copied from `supervisor/tests/test_no_write_guard.py`. |
| Fault generator | Freeze, drift, spike, bad_quality, dropout, taken from `sim/src/crosscut_sim/faults.py`. Written by a different model than the author of the detector. |
| Frozen criteria | Set before the first run: false alarms <= 1 per 24 h on quiet data; detection >= 80 % for drift and for freeze. |
| GUI | Anomalies view: T2 and SPE chart with limits, contribution bars for the flagged sample. |
| Miss | If a criterion misses, stop the line and record it in `anomaly/README.md`. |

Lead re-derives the T2 and SPE limits against one textbook example before any run.

## Step 2: Module 4, soft sensor skeleton

Package `softsensor/`.

| Part | Content |
|---|---|
| Method | PLS (Wold 2001) with lag features, drift flag and validity flag. |
| Evidence | Simulator only. Hidden quality variable from a generator written by a different model than the author. |
| Experiment | Protocol for flotation silica prepared under `experiments/`. Not run unless real data is local. |
| GUI | Predicted vs lab chart with validity flags, with strings en/pl/es. |

## Step 3: ADR 011 write path and gateway test skeleton

| Part | Content |
|---|---|
| ADR 011 | Write path design: authority model, watchdog, rejected writes, rate and limit clamp. Owner review is pending. |
| Test suite | Simulator-only gateway test skeleton. Scenarios: CAS handover, watchdog loss, rejected write, rate and limit clamp. All marked xfail. |
| Static test | Forbids any asyncua write call in the new packages (`anomaly/`, `softsensor/`). |

## Hygiene checklist (each module)

- [ ] PROVENANCE row
- [ ] ASSUMPTIONS row
- [ ] HANDOFF rewritten to the current state (outdated points deleted)
- [ ] Memory updated

## Stop conditions

| Condition | Action |
|---|---|
| Frozen criterion misses | Stop that module line, write the honest result in its README. |
| Two failed attempts on the same problem | Escalate to the advisor and record the cause. |
| Any step cannot go green | Commit nothing from that step, record the blocker in HANDOFF. |
