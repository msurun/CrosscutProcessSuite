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

sha256 of the LF-normalised file (`tr -d '\r' < f | sha256sum`), 2026-10-22:

| file | sha256 |
|------|--------|
| experiments/exp28_integrating_step_test/gen28.py | c5a1f5f90b9d69af0e5607c064aaf1afc0066ccdb6e2f3cacaeae7a456c1623f |
| experiments/exp28_integrating_step_test/exp28.py | 82544c6ebd1f830572714d862d777f9863d106ed7e87da0426cd328e65659bab |
| loops/src/crosscut_loops/identification_ipdt.py | 9cf6fcd3752e56343a0b8a9e18352322daf4cde2d351e9273c4791a7f934bd19 |
| loops/src/crosscut_loops/tuning_rules_integrating.py | f8347270eb983df4d40320db229dfa5cd3263b0cf367d92faafc73b9fd5c7a38 |
| loops/src/crosscut_loops/tuning_payload_ipdt.py | 0021f0f0cac80100d3592a39f0aeec234aae599671f13af6bfb2af1d5f559cf4 |
| loops/src/crosscut_loops/tuning_report_ipdt.py | 85a4d6855f9ff8467d838a5764efb06afe351850bd979bd46f1ab585ed3dd490 |

Authorship note (harness): `gen28.py`, `exp28.py` and `test_exp28_smoke.py` were written by an Opus subagent that did not
edit `loops/`. Harness readings of points the protocol leaves open: the step size s is drawn per record from the seed
(it is not a cell dimension); B1/B2 use d from the initial slope K / tau, the single pattern on even seeds and the doublet
on odd seeds, noise and load drawn from the good-cell grids; B3 draws a good cell and cuts the tail to 20-90 % of
max(5 theta, 300) s; B4 draws k, theta and noise from the grid, load 0.5 % OUT, 1200 s; `looks_integrating` is read from
`tuning_payload` on the whole record (explicit window = record bounds, mode MAN); I3 is judged on good cells (bad accepted
fits are listed as report only); I4 false warnings are pooled over B1 and B2 (per kind shown); valve cells are judged with
the deadband in the closed loop. After amendment 1 the lead is rounded up to whole seconds, and B1/B2 keep their 1200 s window
with lead 300 s (= rest / 3); B3 cuts a record generated with the amended lead.

## Amendments

### Amendment 1 (2026-10-22, written before any development or test seed was used)
The protocol fixed the lead at 120 s, but identify_ipdt refuses records whose quiet lead is under 20 % of the record (min_pre_move_fraction = 0.2, the baseline needs it). The lead is now max(120 s, rest / 3), where rest = pattern duration + the time after the last move, so the lead is at least 25 % of the record in every cell. The 20 % lead requirement is a library rule that real records must also satisfy; the tuning screen says so in its refusal text.

### Development round 1 (2026-10-22, development seeds 28001..28072 plus scratch seeds 28901..28950; no test seed used)
First dev run (harness unchanged apart from amendment 1): accepted 1.000, accurate among accepted 0.764 (I1 miss), I3 72/72 safe, `looks_integrating` fired on 0.778.
Findings: `slope_rel_se` was too small for slow load (bootstrap block 10 samples); the warning rule missed noisy or loaded records. Library changes made
(Sonnet subagent) using development data only: block length from the residual autocorrelation; `slope_rel_se` = bootstrap SE + relative slope shift when a quadratic baseline term is
added (heuristic, 4 positives and 1 false flag on dev, weak evidence); second `looks_integrating` criterion `ipdt_explains_record_as_well` (IPDT R2 >= 0.8 and
R2_ipdt >= R2_fopdt - 0.02), 0/50 false warnings on FOPDT scratch records (tau 60 and 200 s, seeds 28901..28950).
Dev rerun: I3 72/72 safe, `looks_integrating` 1.000, I1 accuracy unchanged at 0.764 (13 of 17 inaccurate runs are dead-time errors or slope errors of 9-15 % that nothing flags),
low_confidence 4/72. Thresholds were not tuned against these seeds beyond the changes above. Expectation recorded before the test run: I1 is likely to miss again.
Development seeds 28001..28072 and scratch seeds 28901..28950 are spent.
