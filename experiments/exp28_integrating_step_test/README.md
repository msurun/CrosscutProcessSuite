# exp28: step-test tuning of integrating (level) loops: identification, refusals, safety of the proposed PI

Protocol FROZEN 2026-10-22 BEFORE the harness is written and before any seed is run. A miss is logged, thresholds are not moved.
Test seeds are run once. Amendments only before the first development seed, written under "Amendments".

## Question
For a level loop (pure integrator with dead time) recorded during an OUT step test, does `identify_ipdt` recover the ramp slope k' and the dead time,
does it refuse the records it cannot judge, are the settings from `simc_pi_integrating` safe on the true plant, and is the "looks integrating"
warning right? Everything is synthetic. The real flotation-cell record supplied by the owner is used afterwards as an exploration only.

## Simulated records (generator written by a different model than `identify_ipdt`; plant class from `exp26.../g26_level.py` may be reused)
dt = 1 s. Plant: dPV/dt = k (u(t - theta) + d(t)), u = OUT - 50 (OUT limits 0..100), PV starts at 50; measurement noise white; load d = Ornstein-Uhlenbeck
(time constant 200 s). The loop is in MAN. Step test = OUT moves from 50: lead 120 s with no move, then the pattern, then at least max(5 theta, 300) s after the
last move. Step size s in {4, 8} % OUT, step duration d = round(10 / (k s)) s clipped to [60, 900] (so PV moves about 10 % of range).
Patterns: `single` (+s, held), `doublet` (+s for d, then -s back to 50, held), `train` (+s, -2s, +2s, -s: four moves, each d).
Good cells: k in {0.002, 0.01, 0.05} %PV per %OUT per s, theta in {5, 30} s, pattern in {single, doublet, train}, noise std in {0.05, 0.2} % PV,
load std in {0, 0.5} % OUT = 72 cells. Valve deadband cells (report only): the same 72 with a deadband of 0.5 % OUT on the actuator.
Bad records (must be refused when the loop is marked integrating): B1 FOPDT process (K = 1, tau = 60 s, theta = 10 s, 1200 s window) with the single and doublet
patterns; B2 the same with tau = 200 s; B3 a good record truncated so that the time after the last move is below max(5 theta, 300) s; B4 no OUT move, OU load only.
25 runs per bad kind.

## Seeds
Development 28001..28072 (one per good cell in cell order; harness check; only bugs may be fixed). Test: good cells 28101..28388 (4 consecutive seeds per cell in cell order),
valve cells 28501..28788 (same layout, report only), bad kinds 28401..28500 (25 per kind in order B1..B4).

## Procedure
Per run: `identify_ipdt(t, out, pv)`. Accepted = verdict ok or low_confidence. For accepted fits: PI = `simc_pi_integrating` with tau_c from `lambda_from_robustness_integrating`
at robustness 0.5, simulated on the TRUE plant of the cell without load and noise (exp26 amendment): +5 % setpoint step at t = 50 s, long enough (T = 50 + 40 (theta + 4 / (k Kc))).
Settled: max |PV - SP| over the last 25 % of the response <= 10 % of the step; not oscillating: error changes sign at most 4 times after PV first reaches the new setpoint
(exp26 definitions). `looks_integrating` is evaluated by the shipped tuning payload code with the loop marked self-regulating (good cells) and marked self-regulating on B1 and B2.

## Pass criteria (test seeds)
| id | criterion |
|----|-----------|
| I1 | accepted share of good-cell runs >= 70 %; among accepted: relative error of k' <= 15 % and |theta error| <= max(1 s, 0.30 theta) in >= 90 % of runs |
| I2 | bad records: blocked in >= 90 % of runs of each kind B1..B4, and verdict ok in <= 5 % of all bad runs |
| I3 | every accepted fit gives a PI that is settled and not oscillating on the true plant: 100 % (a single unsafe case fails I3) |
| I4 | `looks_integrating` fires in >= 90 % of good-cell runs marked self-regulating; false warnings on B1 and B2 marked self-regulating <= 10 % |

Reported, no target: results per cell, valve-deadband cells (limit cycles expected), overshoot of the proposed PI, share low_confidence, refusal reason histogram.

## Decision rule
If I3 fails: the tool refuses to propose settings from `low_confidence` fits (or the criterion that let the unsafe fit through is tightened in a NEW frozen round on new seeds); nothing ships claiming validated level-loop tuning.
If I1, I2 or I4 miss: documented miss, the GUI and README say what is not validated. Never iterate on the test seeds.

## What this does not show
Simulated integrator with dead time only. Real flotation cells are coupled in series, valves stick, and the level sensor has its own dynamics. The real record is read for plausibility (up/down k',
sign, order of magnitude against valve capacity divided by cell area); no pass/fail.

## Authorship
`identify_ipdt` and `simc_pi_integrating`: Sonnet subagents. Generator and harness: an Opus subagent that does not edit `loops/`. Recorded after the run.

## Frozen files
(sha256 of the harness, generator and the identification and rules modules, filled in before the first development seed.)
