# exp16: does the stiction suspicion generalise? (protocol, frozen before any ISDB or G3 result)

Why: exp15 showed the shipped suspicion is a weak ranking and every number so far comes from
generators written together with the detector (exp01, synth14, shifted) plus 17 SACAC loops.
Opus advice (2026-10-17): add independent data, cover setpoint forcing, select by the WORST
family, stop early. This file fixes the rules before the data are looked at.

## Independent data (sealed, used once)

- ISDB v1.0 (Jelali & Huang 2010; `ISDB.zip` from the book page; see PROVENANCE). Local only.
  sha256 isdb10.mat 4dd329b5af3f9bd6e9070bce3fd46e001bb763a21c9fb8be026571b9d364e7df.
- `isdb_labels.csv` (sha256 d5518507e9ff2d73e240460644fd1d14123a767804ad60e4d1cdd8cd11eff283):
  labels read ONLY from the providers' `BriefComments` text by a fixed rule
  (`stick` = comment says stiction; `other` = no stiction / no oscillation / tuning problem /
  disturbance / quantisation / faulty sensor / marginal stability / dead zone; `low` confidence =
  "(likely)" or "intermittent"). Test series and uncommented Thornhill tags are not labelled.
- 10 ISDB series are the same data as SACAC files (PV correlation > 0.999) and are marked
  `sacac-twin`; they are excluded. Counted set = `overlap == independent` and
  `confidence == high`: 13 sticking (12 F, 1 L) and 14 other (9 F, 5 L). The 17 "likely" loops
  are reported separately, never counted. Everything is small: Wilson intervals are mandatory and
  the ISDB result is a veto/sanity check, not a score to optimise.
- No detector has run on ISDB before the final run. It is run once, for the shipped module and
  the finalist together, in `final16.py` (single use, refuses a second run).

## Synthetic families (leave-one-family-out)

- G1 = synth14 (exp14). G2 = shifted generator (exp15). G3 = new generator written from a physics
  spec (`G3_SPEC.md`) by a different model that saw only the spec: setpoint forcing, cascade,
  load disturbances (sine, square, multi-tone), deadtime-dominant and integrating plants, sensor
  filter, quantisation, historian deadband compression, missing samples, Choudhury / Kano / He
  stiction models. Independence check before use: compare feature distributions of G3 against
  G1/G2 (a two-sample test per feature); report it, do not tune G3 afterwards.
- exp01 gets an SP column and setpoint-forcing cases (new seeds only).

## Candidates and selection

- Max 3 rounds, max 2 candidates per round, features fixed in advance (at most 2 new physical
  features: ellipse-versus-parallelogram shape of the OUT/PV loop, loop area ratio).
- Selection metric: worst-family LOFO AUC with abstain = 0 (train on two families, score the
  third; worst of three). Stop after the first round whose best worst-family gain is < 0.02.
- Test seeds: sha256 of (salt + stream name), salt = the hash of a commit made after the finalist
  and this README are frozen. Final data used once.

## Acceptance for shipping a new scorer

All of: worst-family AUC >= shipped + 0.03 with the 95 % paired-bootstrap interval excluding 0;
exp01 healthy classes still <= 2/20 flagged per cell and T7 (noise only) <= 5 %; ISDB counted
set: sticking flagged not fewer than shipped - 1 and other flagged not more than shipped + 1;
coverage-versus-error curve for the abstain rule reported; unproven items listed (precision in a
real plant, level loops, half-cycles < 18 samples). Failure is reported, not tuned away.

## Always, independent of the scorer

Package wording: when the oscillation could be periodic forcing, the advice says so and asks for
a gain-change / valve test; the score stays a ranking, never a diagnosis.

## Dev log

### 2026-10-17 G3 build log (all before any final seed exists)

- g3_valve, g3_chain, g3_excite, g3_sim written by a delegated model (deepseek) from G3_SPEC.md only.
  First g3_sim drifted (plant without deviation variables, integrator exploded). Fix = spec
  amendment "Simulation conventions" + regeneration of g3_sim; then I fixed by hand a double
  integration of the PI error (line removed) and added a validity rule in g3_sim
  (`_record_valid`): swing <= 60 % and tail/head growth <= 3 for non-setpoint cases; for "stick"
  records an ideal-valve twin of the same plant must swing < 0.5x. The twin rule is an
  ASYMMETRIC selection (stick only), declared here. Setpoint cases got a small random-walk load.
- G3 is frozen from this entry on (sha256 below). No detector result was used to change G3 after
  the first probe; the probe (shipped module AUC 0.55 on G3) preceded the validity rule, and the
  rule was added because label-validity checks showed oscillation unrelated to the valve.
- Independence (family_distance.py, dev): feature KS distances G1-G3 / G2-G3 are larger than
  G1-G2 for ln_prom (0.54 / 0.60 vs 0.12), he_fold, log2_half. G3 is not a copy of G1/G2.
- Realism vs SACAC (realism.py, no detector): oscillation window found in 68 % of G3 stick
  and 54 % of G3 healthy records (SACAC 7/13 and 5/22 files); median period 86 / 90 samples
  (SACAC 49 / 29); std(PV)/std(OUT) median 0.37 / 0.42 (SACAC 1.0 / 0.55); half-cycle < 18
  samples 16 % / 23 % (SACAC 43 % / 60 %). G3 is in range but slower, with fewer short
  half-cycles, so the short-half-cycle limit stays an unproven item.
- Hashes:
  c8b249b62fc12de6c71334320c9326c9d6f290575afb7a593fb41d88e5532039  g3.py
  6756b7ef7e5b4664ff4689f7bf86a32e4e7aec0d3d188fc40bab933ac2709a28  g3_sim.py
  816d6e8c7218f9b416d4482a02b4dca936b1f217c70d3e5775b91173b9dc3442  g3_valve.py
  56002c883cc9cbd959db6bac1cb729d41d47dcc32f02e2d8514646c223b83aed  g3_chain.py
  ad2642bcccfe9e2db608e57907114550ced0a987ebdcbe81181fdd631457c0fb  g3_excite.py
  ec4e94254f113c125e7295616adafb11aa60199507fda76a730f0341ab4293fa  G3_SPEC.md

### Amendments before the final seeds (Opus review 2026-10-17)

1. One threshold is frozen now from the original rule only (exp01 healthy <= 2/20 per cell and T7
   <= 5 %), out-of-family probabilities; it serves the acceptance checks, not the product score.
2. The product score is a RANK within the loop list ("rank N of M, relative, not calibrated,
   not a diagnosis"); the `test_valve` advice and the forcing caveat stay. Minimum list size
   for the rank wording goes into the unproven items.
3. Round 1 has exactly two candidates: C7a = C6 features retrained on G1+G2+G3; C7b = C7a plus
   ellipse-versus-parallelogram shape and loop-area ratio. Stop if C7b gains < 0.02 worst-family
   AUC over C7a. No more ablations.
4. Acceptance additions (reported, not selecting): worst-family sensitivity at a fixed 10 %
   healthy-flag rate per family, pAUC at FPR <= 0.1, AUC on the ranked subset with coverage.
   The paired-bootstrap interval of worst-family AUC against shipped is computed on final seeds.

### 2026-10-17 round 1 result and freeze (dev only; no final seed exists yet)

- LOFO worst-family AUC (dev): shipped 0.549, C7a 0.739, C7b 0.678 (area/squareness features
  lowered coverage and G3). C7b gain over C7a is negative, so the stop rule applies: finalist = C7a.
- Threshold frozen by pick_threshold.py (original rule, exp01 dev healthy cells <= 2/20, T7 <= 5 %):
  0.5 (worst healthy cell 1/20, T7 2 %, band 8 full noise 10/20 versus shipped 13/20).
  c7_model.json had stored the train_c7 default 0.9; it was set to 0.5 here, before any seed.
- Smoke run of final16.py (EXP16_SMOKE=1: salt "smoke", 2 seeds per cell, no ISDB) passed technically.
  Dev look at SACAC loops with C7a (SACAC is veto-only, already used in exp13-15): all 6 sticking
  loops score 0.69-0.89, but 3 of the 5 ranked non-sticking loops score >= 0.79; the veto may fail
  on false flags. It is reported as is, not tuned.
- Final: salt = full hash 2bb08f93e76a59b760f2d8ae4d1cc71b8b9543fa (commit made after the finalist
  features/model were frozen). Hashes of the two files after the threshold edit:
  6439a0b6208b10d3f4576b8eba129204c408c5a58ba7005221c4c17de16fe4ba  c7_model.json
  5fc13364e1c4ad0f0c5330f781eef727fcbb80a89d6468bf58aea892574c2348  final16.py

## FINAL RESULT (2026-10-17, results/final16.md, single run, salted seeds): C7a is NOT shipped

- Synthetic: worst-family AUC shipped 0.522 -> C7a 0.714 (gain +0.192, paired bootstrap 95 %
  interval [+0.165, +0.218]); G1 0.749 -> 0.915, G2 0.661 -> 0.898, G3 0.522 -> 0.714. exp01
  healthy cells 0/20 everywhere, T7 1/100, sticking at full noise band 8: 9/20 (shipped 13/20).
- SACAC veto: sticking 6/6 flagged for both, non-sticking flagged 3 (shipped 1; veto <= 2) -> MISSED.
- ISDB counted set (13 sticking, 14 other, independent, high confidence): shipped flags 6/13 and
  1/14 (AUC abstain=0 0.670); C7a flags 5/13 and 10/14 (AUC 0.324, below chance) -> MISSED.
- Verdict: the acceptance rule requires ISDB other flagged <= shipped + 1; C7a flags 10 of 14.
  The rule is applied as written. The shipped module stays; only the weaker wording changed.

What this says (interpretation, not tuned away): gains across three synthetic families do not
transfer to independent real loops. On real "other" loops (disturbances, quantisation, sensor
faults, tuning problems) C7a ranks almost every record (12/14) and scores most of them high, so
the learned shapes are driven by features of the simulators (sustained clean oscillation = stiction)
rather than by stiction. The shipped module abstains on half of those loops, which is why it looks
better there. ISDB is now used for C7a; it must not be used to select a next candidate.

Unproven or open: precision in a real plant; what real non-stiction oscillations look like to the
features (an ISDB-derived training set would need new sealed data); level loops (5 of the
counted ISDB "other" loops); half-cycles < 18 samples (G3 had few); rank wording needs a minimum
loop-list size; exp01 has no setpoint forcing (G3 covers it synthetically only).
Round 2 is not started: the Opus rule allows at most 3 rounds, but a further round would be
selected against ISDB, which is burned for this purpose.
