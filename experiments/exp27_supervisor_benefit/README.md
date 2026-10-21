# exp27: does the advisory supervisor beat a crisp rule in a closed-loop simulation?

Protocol FROZEN 2026-10-21 BEFORE any harness code is written or any seed is run. A miss is logged, thresholds are not moved.
Test seeds are run once. Amendments are allowed only before the first development seed and are written under "Amendments".

## Question
With a simulated operator who follows advice, does the fuzzy v2 supervisor (arm c) keep P80 on target more often than a crisp
threshold rule base (arm b), without more mill-power excursions, and does the supervisor pipeline stay silent when module 1 says
the loop is not fit for advice? This tests the pipeline and the claim "no benefit over a crisp rule" honestly. It does NOT test
anything about a real plant (assumptions A3, A4, A12, A18 stay open).

## Setup (simulator: `crosscut_sim` mill circuit, plant `step/read/write`, scenario `observational`, 48 h, 10 s samples)
- Arm a: the built-in scripted hardness-based operator (as exp09/exp11). Reference only, plus E5.
- Arms b and c: built-in operator OFF. At each operator instant t_k = k * 1800 s the supervisor looks at the last 1800 s
  (module 1 gate on `mill_feed`, snapshot = window mean of mill power and P80, same code path as `advise_series`). With probability
  p = 0.8 (draw from a generator seeded by the run seed, the SAME draws in arms b and c) the operator applies the advised
  `feed_change` as a feed setpoint step at t_k + D, D = 300 s; hold advice, silent advice and blocked gates mean no move.
  Setpoint limits are the engineering range of `sim.mc.mill_feed_sp`.
- Supervisor config for both arms (file `supervisor_config.json`, frozen by sha256 below): `silent_band` 1.0 t/h, `min_activation` 0.2,
  `min_interval_s` 1500, `display_clamp` [-20, 20], gates: `mill_feed` blocks on manual, saturated, flatline, unknown; warns on oscillating.
- Arm b rule base `baseline_rulebase.json` (crisp, one threshold rule per direction, same input and output variable ids as v2, rectangular
  terms): power above 3200 kW gives decrease_large; P80 above 158 um gives decrease_small; P80 below 142 um and power at most 3200 kW
  gives increase_small. Arm c is `fuzzy/examples/mill_feed_supervisor_v2.json` unchanged.
- Fault runs for E1: the arm c recorded data of each test seed is replayed with `advise_series` after two injected faults on the
  `mill_feed` loop (mode set to manual for 1 h; PV and OUT frozen for 1 h; each in its own replay, window of the fault placed at 20 h).

## Metrics (per seed, over the last 40 h to skip the start-up)
- onT: share of samples with |P80 - 150| <= 5 um. high: share of samples with mill power > 3300 kW.
- Advice rate: non-hold advices per hour of arm c. Silent share (E5): share of arm a operator moves with |delta SP| > 2 t/h for which the
  supervisor with v2 returns no advice (the exp11 definition, now through the supervisor pipeline).

## Seeds
Development 27001..27010 (harness check, thresholds in the config may NOT be changed after seeing them; only bugs are fixed).
Test 27101..27120, run once. Seeds 1-20 (exp09, exp11) are spent and not reused.

## Pass criteria (test seeds)
| id | criterion |
|----|-----------|
| E1 | 0 non-hold advices whose window lies fully inside an injected fault window, in both fault replays on all 20 seeds; blocked records name the fault (manual / flatline) |
| E2 | median advice rate of arm c <= 4 per hour and no two non-hold advices closer than `min_interval_s` on any seed |
| E3 | onT(c) >= onT(b) + 0.05 on at least 14 of 20 seeds |
| E4 | median over seeds of (high(c) - high(b)) <= 0.01 |
| E5 | median silent share (arm a moves, supervisor with v2) <= 0.30 |

Also reported, no target: onT and high of arm a, gate-open share of arm c in the fault-free runs (expected >= 90 %).

## Decision rule
If E1, E2, E4, E5 pass and E3 fails, the module ships with the claim "pipeline and gating verified; no benefit over a crisp rule shown
in this simulator". If E1 or E2 fails it is a defect: fix, then a new frozen round with new seeds. Never iterate on the test seeds.

## What this does not show
The operator is a simulation we wrote; acceptance probability and delay are assumptions (A18). The rule bases were shaped on this simulator
(exp11). A positive E3 would be evidence about the simulator only.

## Authorship (same-model bias control)
Supervisor package: written by Sonnet subagents under the lead. Harness, operator model and baseline rule base: written by an Opus subagent
that does not edit the supervisor package. Recorded here after the run.

## Frozen files (sha256 recorded at freeze, filled in by the commit that adds the harness and before the first dev seed)
