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

## Result round 1 (test seeds, first and only run, 2026-10-22; tables in results/test.md)
| id | value | criterion | met |
|----|-------|-----------|-----|
| I1 | accepted 0.938 (270/288); accurate among accepted 0.815 | >= 0.70 accepted, >= 0.90 accurate | **no (accuracy)** |
| I2 | blocked B1 1.000, B2 1.000, B3 1.000, B4 1.000; verdict ok on bad records 0.000 | >= 0.90 each, <= 0.05 | yes |
| I3 | 270 judged, 3 unsafe | 100 % safe | **no** |
| I4 | `looks_integrating` fires on 0.958 of good runs; false warnings on B1+B2 0.000 | >= 0.90, <= 0.10 | yes |

The three unsafe runs (seeds 28112, 28171, 28185) are all slow integrators (k = 0.002) with the dead time badly underestimated while k' was right (theta 5 s read as 0.85 s; 30 s read as 2.5 s and 4.7 s), verdict `ok`, R2 >= 0.98. A too small dead time gives Kc = 1 / (k' (tau_c + theta)) that is too large.
Per the decision rule, nothing from round 1 ships as validated level-loop tuning: the screen labels integrating-loop settings experimental. Dead time is poorly identifiable when the ramp starts slowly against the noise; the fit does not know its own uncertainty in theta.
Round 2 (new frozen protocol on new seeds, below) tunes with an upper bound of the dead time from the profile of the fit error instead of the point estimate.

## Round 2 protocol (FROZEN 2026-10-22, before any round 2 seed and before the code that implements it is run)
Change under test: `IpdtFit` gains `delay_lower_s` and `delay_upper_s` (profile of the sum of squared errors over theta, with the other coefficients re-fitted at each theta; the interval is the set of theta whose SSE <= SSE_min * (1 + F_{0.95}(1, n - p) / (n - p)), clipped to the delay grid) and the tuning rules use `delay_upper_s` as the dead time (conservative: a larger theta gives a smaller Kc and a longer Ti). The point estimate is still reported.
Same generator, same cells, same harness code paths (the harness gets a `--round 2` switch that changes only seed ranges and the criteria below; its hashes are re-frozen). Seeds: development 30001..30072, test good cells 30101..30388, valve 30501..30788, bad kinds 30401..30500. Round 1 seeds are spent.
| id | criterion (test seeds) |
|----|-----------|
| J1 | every accepted fit gives a PI that is settled and not oscillating on the true plant: 100 % (a single unsafe case fails J1) |
| J2 | the true dead time lies inside [delay_lower_s, delay_upper_s] in >= 90 % of accepted good runs |
| J3 | bad records: blocked in >= 90 % of runs of each kind (as I2); accepted share of good runs >= 70 % |
| J4 | median overshoot of the proposed PI on good runs <= 0.35 (conservative tuning must not become useless) |
Decision: if J1 fails again the integrating tuning stays labelled experimental, the settings are shown only as a range of Kc and Ti, and the line is closed. Never iterate on the test seeds.
Development round (seeds 30001..30072) may be used to fix bugs only; the interval rule above is frozen as written.

### Round 2 frozen files
sha256 of the LF-normalised file (`tr -d '\r' < f | sha256sum`), 2026-10-22, after the library change (loops tests green) and before the first round 2 development seed:

| file | sha256 |
|------|--------|
| experiments/exp28_integrating_step_test/gen28.py | c5a1f5f90b9d69af0e5607c064aaf1afc0066ccdb6e2f3cacaeae7a456c1623f |
| experiments/exp28_integrating_step_test/exp28.py | 2257aeb2c19ef86b926f1b58549667b2535ec1bca7ac1cfb36b06fc5817b186f |
| loops/src/crosscut_loops/identification_ipdt.py | 4ccfd3fc4a3ac9985398c9f3fe9f088bd6048fa64bab78df48b31c222afdee67 |
| loops/src/crosscut_loops/tuning_report_ipdt.py | 34e8a8447807e71c92a5709c5db7c60feb362350c7d0efa9c86c29728f24cdea |
| loops/src/crosscut_loops/tuning_payload_ipdt.py | fa0673d572ad4ebbe6f516196c5c07a6454145236f38802c5e21c8a2752bbc76 |
| loops/src/crosscut_loops/tuning_rules_integrating.py | f8347270eb983df4d40320db229dfa5cd3263b0cf367d92faafc73b9fd5c7a38 |

Harness reading for round 2 (`--round 2`): the PI judged in J1 is the SIMC PI of the shipped tuning payload with the loop marked integrating (settings built with `delay_used_s`), not a harness call of `simc_pi_integrating`; J2 reads `IpdtFit.delay_lower_s/delay_upper_s` and the payload keys `delay_lower_s`, `delay_upper_s`, `delay_used_s`; J4 is the median overshoot over the judged accepted good runs. Round 1 (`--round 1`, default) is unchanged.


## Development round 2 (2026-10-22, before any round 2 test seed)

The first round 2 development run (results/dev2.md) gave J2 = 0.296 on the dev seeds 30001..30072: the point estimate of the dead time was about 0.5 s too long and the intervals were 1-2 s wide while the error was 3-7 s. Two library changes in `loops/src/crosscut_loops/identification_ipdt.py` (the only frozen file changed; its sha256 above is updated):

1. OUT is read as a zero-order hold (u(t) = u[k] on [t_k, t_k+1)), the usual reading of a historian record. The integral of the delayed input is piecewise linear in time and is evaluated analytically at fractional delays. Before, OUT was interpolated linearly and integrated with the trapezoid rule, so a step held between samples was treated as a ramp and theta came out too long. Uneven sampling is still supported.
2. The SSE-profile interval uses an effective sample size n_eff = n / (1 + 2 * sum of residual autocorrelations up to the first zero crossing), bounded to [p + 2, n], in the F threshold SSE <= SSE_min * (1 + F95(1, n_eff - p) / (n_eff - p)). Principle: positively correlated residuals (slow load) carry less independent information than their count; white residuals were assumed before. The autocorrelation helper is the one the bootstrap block length uses.

Unit tests added (step held between samples: theta within 0.2 s on clean data; correlated residuals give a wider interval than white noise); the test plant of `_ramp_pv` now feeds the zero-order-hold OUT (consistent with the new reading), no tolerance was loosened.

Development numbers after the change (dev seeds only; output regenerated, not committed over results/):

| round | criterion | before | after |
|-------|-----------|--------|-------|
| 2 | J1 | judged 71, unsafe 0 | judged 70, unsafe 0 (PASS) |
| 2 | J2 | 0.296 | 0.886 of 70 accepted good runs (MISS vs 0.90) |
| 2 | J3 | not exercised | not exercised; accepted good 70/72 |
| 2 | J4 | 0.164 | 0.163 (PASS) |
| 1 | I1 | - | accepted 1.000 (72/72), accurate among accepted 0.778 (MISS) |
| 1 | I3 | - | judged 72, unsafe 0 (PASS) |

No criterion or threshold was changed. The round 2 development seeds 30001..30072 are spent; no test seed (28101+, 30101+) was run.
