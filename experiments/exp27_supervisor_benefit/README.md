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

Harness note (Opus subagent, 2026-10-20): wrote `exp27.py`, `test_exp27_smoke.py`, `supervisor_config.json` and
`baseline_rulebase.json`; did not modify `supervisor/`. Choices the protocol leaves open, fixed before the first dev seed:
- Advice per operator instant via `crosscut_supervisor.replay.advise_at` (module 1 `analyze_dataset` + `gate_state` + `advise`,
  window (t_k - 1800 s, t_k]); first instant t_1 = 1800 s. Acceptance: `default_rng(seed).random(n_instants) < 0.8`, one draw per
  instant whether or not advice exists, so arms b and c see identical draws. Accepted step: SP := clip(SP + feed_change, 0, 300) at t_k + 300 s.
- Arms b/c prepend `("operator", 0.0)` to the observational scenario params, which also stops the built-in press and water moves.
- mill_feed `LoopTags` carry `delay_s` 30 and `ultimate_period_s` 600 (as `supervisor/tests/test_replay.py`); without them module 1
  rates the loop `not_assessed` and the frozen `unknown` block closes every gate (seen in the first smoke run).
- Baseline: input terms rectangular (trap a=b, c=d); output terms copied unchanged from v2, so only the antecedents differ.
- E1: a non-hold advice counts when every sample of its window is faulted; "named" = a blocked record whose window touches the fault
  carries `manual:mill_feed` / `flatline:mill_feed`. E2 checks the closed-loop arm c advices AND the min spacing of the `advise_series`
  fault replays. E3 pass = wins >= 0.7 x seeds (14/20 on test). E5 window ends on the last sample before the arm a move; hold or silence = no advice.
- Dev seeds 27001..27010 (results/dev.md, informational): E1 0 inside, named 20/20; E2 median 1.65/h; E3 9/10; E4 -0.0018; E5 0.206;
  gate-open share 1.00. No harness bug found after the `not_assessed` fix above; runtime 305 s.

## Frozen files (sha256 recorded at freeze, filled in by the commit that adds the harness and before the first dev seed)
sha256 of the LF-normalised bytes (= git blob content; `tr -d '\r' < f | sha256sum`). On a Windows checkout with autocrlf v2 is CRLF.

| file | sha256 |
|------|--------|
| `experiments/exp27_supervisor_benefit/supervisor_config.json` | `ab88cf3f30d81fd5b5b7707464a3d5aebd9e28302932fedc872fd1e82b057c02` |
| `experiments/exp27_supervisor_benefit/baseline_rulebase.json` | `c9fe983431f21a93d2f32af2f9bc9717de1cc2fd6e7a52ad8e7d9e9f1e63edc3` |
| `experiments/exp27_supervisor_benefit/exp27.py` | `0d6b5fad2add9ec68133aec4bb9a740e7b61a1f761ff0b9aeb30c1466e4f0fb4` |
| `fuzzy/examples/mill_feed_supervisor_v2.json` | `a901cd75d6e9e140fff631151dc2544e10fee79583d0dcf14e0f7261cd4ac83a` |
