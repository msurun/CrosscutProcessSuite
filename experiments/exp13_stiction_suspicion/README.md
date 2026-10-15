# exp13: stiction as a ranked suspicion, not a verdict

Frozen on 2026-10-15 BEFORE any code of this experiment was run. Reason (Opus review after exp12 round 4):
a passive hard yes/no from one shape index is the wrong product. Commercial tools detect an oscillation
first, run several tests, and rank loops by suspicion; the valve (bump) test confirms. This experiment
changes the output and the scoring, and adds the Horch cross-correlation test.

## Honest status of the data

The 19 SACAC loops were already used in exp10-exp12, so the "held-out" split is contaminated (the floor
was changed three times after seeing results). Nothing here is a clean test. The result is a smoke test
and a demo, not an accuracy figure. Labels are repository-level, with no measured stiction size.
Label change made before the first run: `other-F-chemicals` kind L -> F (its .txt says "Level" but the
description says a flow measurement; name says F).

## What is built

1. Oscillation window: the best stretch of the record (the whole record, halves, quarters, eighths) with at
   least 6 regular cycles and an autocorrelation peak >= 0.5 at the period; ties go to the longer stretch.
2. Tests per file on that window: noise-corrected curve-fit index (candidate A on OP, on PV for kind L),
   Horch cross-correlation oddness (OP versus raw PV; NOT used for kind L: on synthetic loops it separated F with AUC 0.83 but L with 0.47, and the first difference of PV was worse; decided on synthetic data before the SACAC run).
3. Suspicion score in [0, 1] = mean of the two calibrated test scores. The Horch calibration constants
   (median oddness of synthetic non-sticking and sticking loops) come from a synthetic closed-loop
   generator only (`synth.py`), never from SACAC. A file with no oscillating window gets NO score.
4. Loop score = median over the loop's files that have a score. Level "test the valve" if score >= 0.5.

## Frozen targets

Population: SACAC loops with confidence medium or high (17: 6 sticking, 11 not). "Ranked" = has a score.

- R1 ranking: AUC (sticking above not sticking, among ranked loops) >= 0.80, and >= 0.70 on the held-out
  split alone.
- R1p permutation check: p <= 0.05 for the observed AUC under 2000 label shuffles.
- R2 recommendation: at score >= 0.5, at least 4 of the 6 sticking loops get "test the valve" and at most 2
  non-sticking ranked loops do (a needless valve test costs less than a wrong diagnosis).
- S sanity: a detector giving random scores must get mean AUC within 0.5 +/- 0.1 over 200 seeds; the
  always-abstain detector must fail R2. If not, the scoring is broken and the round is void.
- Reported, no target: share of sticking loops that are ranked; per-test AUC (He only, Horch only);
  shape-based stiction size estimate for flagged loops (no ground truth exists).

## Rules

- One round. If R1 or R2 is missed, no tuning on SACAC: report plainly and the owner decides.
- No constant is tuned on SACAC. Anything derived is derived on `synth.py` data.
- SACAC data stays local (no stated licence); only aggregate numbers go into the log.
- Step 4 (a classifier trained on synthetic loops, features from the tests above) starts only after this
  round is logged, and is scored on the same frozen SACAC targets, untouched during training.

## Result (2026-10-15, one run, nothing tuned on SACAC)

Horch calibration on synthetic F loops: non-sticking median oddness 0.51, sticking 0.69.
Ranked 8 of 17 counted loops (all 6 sticking, 2 of 11 non-sticking); 9 non-sticking loops have no
oscillation window and get no score.

| Target | Result |
|---|---|
| R1 AUC >= 0.80 and held-out >= 0.70 | 1.00 (6 vs 2), held-out 1.00: met |
| R1p permutation p <= 0.05 | 0.035: met (0.036 is the smallest p possible with 6 vs 2) |
| R2 test-the-valve >= 4/6 sticking, <= 2 false | 6/6 sticking, 0 non-sticking: met |
| S random detector AUC 0.5 +/- 0.1 | 0.52: ok |
| per-test AUC (reported) | Horch 1.00 (n=5); He index scored only 4 loops, none of the 2 negatives |

How to read it, plainly: the targets are met, but the evidence is thin. Only 2 non-sticking loops reach
the ranking (both Horch 2003 records with a 29-sample period, same source, scores 0.00), so AUC 1.00
rests on 12 pairs of which the 2 negatives are one data source. Most of the improvement over exp12 is
the output change: a sticking loop with too few samples per half-cycle (Horch flow, Pisa oil&gas) is no
longer "inconclusive" because Horch alone scores it. The He index is absent for 4 of 6 sticking loops
(period too short, or integrating level loops with Horch switched off) and weak for Pisa power (0.58).
Pisa oil&gas and Horch flow have score 1.00 from Horch only. This is a demo-level result on 19
contaminated loops, not an accuracy figure. A real test needs plant data with valve-test labels.
