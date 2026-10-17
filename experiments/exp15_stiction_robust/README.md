# exp15: robust stiction suspicion (window at high noise, short half-cycles, level loops)

Frozen 2026-10-16 BEFORE any code of this experiment. Protocol agreed with an Opus advisor after the package shipped
`stiction_suspicion.py` (exp13/14). Everything seen so far is contaminated; this round creates data that were never looked at.

## Data

| Role | Data |
|---|---|
| Dev (may be looked at, used to choose) | exp01 mill simulation seeds 1-20; `synth14.py` seeds 100-399; shifted generator seeds 1-300 |
| Final (run ONCE, at the end) | exp01 seeds 21-40; `synth14.py` seeds 500-599; shifted generator seeds 1000-1099 |
| Veto only | SACAC 19 loops: once per round after the dev gate, never used to choose between candidates |

Shifted generator (`synth_shift.py`, written before any candidate): different stiction model (full-slip, Kano-style), AR(1) coloured
noise, other time constants, kinds F and L, noise levels low / mid / high = 0.05 / 0.15 / 0.4 of the noise-free PV standard deviation.
Final seeds must appear in no dev script (checked by grep at the audit).

## Candidates (at most 2 per round, at most 4 rounds)

- Round 1, spot 1 (window at high noise): C1a = regularity normalised by acf at lag 1 instead of lag 0 (white noise only adds at lag 0),
  period from the spectral peak with parabolic interpolation, window searched on OP and on PV, the higher regularity wins.
  C1b = C1a plus epoch folding: all cycles folded on one phase grid with the fractional period, He index fitted on the folded wave
  (also the answer to fewer than 18 samples per half-cycle).
- Round 2, spot 3 if still open; Round 3, spot 2 (integrating loops): squareness index of band-limited dPV, folded; Horch for L only if
  it separates on dev data.
- Stop when all dev targets hold, or after 2 rounds in a row without gain on dev. Then the final set is run once; if it fails it is
  reported and nothing is tuned (those seeds are used up).

## Frozen targets (Wilson 95 % bounds printed; "not_ranked" counts as a miss for positives and as a score of 0 in AUC)

Final set, cells of 20 (exp01) or 100 (synthetic):
- T1 exp01 low noise, bands 4, 6, 8 %: test_valve >= 18/20 each. T2 exp01 full noise, band 8 %: >= 14/20 (the older verdict: 8/10 at dev).
- T3 negatives (wander, aggressive tuning, sine, square forcing; both noises): test_valve <= 2/20 each. Synthetic negatives
  (sine, square, tuning): <= 10 % per noise level.
- T4 AUC with abstain = 0: synth14 overall >= 0.85, kind F >= 0.85, kind L >= 0.75, records under 18 samples per half-cycle >= 0.70.
  Shifted generator: overall >= 0.80. Also reported: AUC over ranked records only.
- T5 SACAC veto: >= 5/6 flagged, <= 2 non-sticking flagged; report how many of the 9 now-unranked negatives become ranked.
- T6 exp01 verdict report (`acceptance.md`) unchanged; ruff, mypy, pytest green.
- T7 sanity: a random-score detector gets AUC 0.5 +/- 0.1 on every set, and a noise-only record is ranked (window found) in <= 5 % of
  100 records (multiple-testing guard for the 15 candidate segments).
- Limits are written into the report finding text and the README: model error beyond the shifted generator is unmeasured, real plant
  data with valve tests is missing, level loops rest on 3 real loops.

## Audit list (for the Opus audit)

sha256 of this text in the log before the first run; grep that final seeds appear in no dev script; constants table with provenance;
per-cell tables with Wilson bounds; ablations (without He, without Horch, without the new feature); exp01 verdict report unchanged.

## Dev log of rounds 1-4 (2026-10-16; dev data only: exp01 seeds 1-20, synth14 seeds 100-159, shifted seeds 1-40)

Records: the final seeds (exp01 21-40, synth14 500-599, shifted 1000-1099) have not been used.

| Round | Candidates | Dev result |
|---|---|---|
| 1 | C1a (lag-1 regularity, spectral period, window on OUT or PV), C1b (+ folding) | exp01 full noise, band 8 %: 9/20. T7 check then showed C1a finds a window in 100 % of white-noise records (lag-1 ratio explodes): REJECTED, the gain was partly spurious. C1b = C1a on exp01. |
| 2 | C2a (longest window with a significant spectral peak, prominence gate 36.5 = pooled p97 of noise-only records), C2b (+ folding) | T7 met (1.5-3 % windows on noise). exp01 full noise band 8 %: 6/20; no false alarms. |
| 3 | C3a (OUT and PV agree on a moderate peak, gate from independent noise pairs), C4a (window, else He index on the whole record) | C3a REJECTED: 10-11/20 false alarms on wander and aggressive tuning (OUT and PV in a closed loop share wander, so agreement proves nothing). C4a: band 8 % full noise 13/20, band 6 % 7/20, false alarms 0-1/20 in all exp01 classes. |
| 4 | C5a (score = curve-fit index of the epoch-folded wave), C5b (+ 25 % Horch) | exp01: square forcing now 20/20 false alarms, full noise worse than C4a. Synthetic: sine false alarms down to 3-4 %, square 77-79 %, tuning 18-28 %. NOT better overall. |

Synthetic dev AUC (abstain = 0) of the best variants versus the shipped one: shipped 0.74 (s14) / 0.67 (shifted), C4a 0.73 / 0.68, C4b 0.69 / 0.70,
C5a 0.66 / 0.71. False alarms of the shipped one on synthetic healthy loops: sine 26 %, square 49 %, tuning 8 %.

What the single-feature study (`feature_study.py`, dev) says: the curve-fit index of the folded wave separates stiction from sine forcing
(AUC 0.99 F, 0.95 L) and tuning (0.91 F), Horch is weak (0.60-0.72 F, below 0.5 for L), and square forcing is not separable by the index
(0.52) but is separable by the third-harmonic ratio of OUT (stiction OUT is triangular, square-forced OUT is not).

Status against the frozen dev expectations: T4 (AUC >= 0.85) and the synthetic part of T3 are NOT met by any candidate. By protocol
(max 4 rounds) the search stops here; the advisor decides whether a further round (a classifier on folded-wave features) is allowed.

## Amendment 1 (2026-10-16, written BEFORE any round-5 code): round 5, one candidate C6

Declared protocol deviation: round 4 gave no gain, so round 5 exceeds the stop rule. The advisor allowed it once, as a written amendment.
The final seeds (exp01 21-40, synth14 500-599, shifted 1000-1099) are still unused.

**C6 = a trained combiner on epoch-folded-wave features, one model per kind (F, L).**
- Segment: as C5 (longest window with a significant spectral peak, gate 36.5; else the whole record when its single peak passes 20.0;
  else the record is not ranked, score 0).
- Six features, fixed now: (1) he_fold = curve-fit index of the epoch-folded wave (OUT for F, PV for L; 0.5 when unavailable);
  (2) h3_out = |FFT bin 3 / bin 1| of the folded OUT wave; (3) h3_pv = the same for PV; (4) odd = Horch oddness of OUT and PV (F; 0 for L);
  (5) log2(half-period in samples); (6) ln(peak prominence).
- Model: logistic regression, L2 with lambda 1 on standardised features (training statistics only), balanced class weights, Newton steps,
  numpy only. Positives = stiction, negatives = sine, square and tuning classes together.
- Training data: synth14 dev seeds 100-399 only (all kinds and cases). Cross-validation grouped by seed (5 folds). The shifted generator
  is a read-only dev check (seeds 1-100), never used for fitting or thresholds; note `feature_study.py` already looked at shifted dev.
- Threshold, fixed now: the smallest p in {0.5, 0.6, 0.7, 0.8, 0.9} for which the cross-validated flag rate is <= 10 % on both the sine and
  the tuning class (pooled over kinds); square is reported separately. Never changed after this.
- T7 for C6: a combiner always scores, so T7 becomes "noise-only records flagged <= 5 %" (same noise kinds as t7.py, other seed).

**Dev gate (decides the finalist, dev data only).** C6 goes to the final run only if on exp01 dev (seeds 1-20) it flags square forcing in
<= 2/20 at BOTH noise levels and no other healthy class in more than 2/20, AND its synth14 CV AUC (abstain = 0) beats C4a's, AND its shifted-dev
AUC is not below C4a's by more than 0.02. Otherwise C4a is the finalist.

**Final run (once), finalist plus the shipped module as reference.** Reported: AUC with abstain = 0 and over ranked records, per kind and
per short-half-cycle subset, flags per healthy class and noise level with Wilson bounds, exp01 cells (20 seeds), T7, random-score
sanity, square-forcing false alarms split by the ratio of forcing period to integral time (where measurable), ablations on dev
(without h3, without Horch). T4 (>= 0.85) was set without a baseline (shipped 0.74 on synth14 dev); it stays, and the miss is reported.

**Shipping rule, fixed now.** The finalist ships only if on the final data: AUC not more than 0.02 below the shipped module, the T2 gain
holds (exp01 full noise band 8 %), no T3 regression on exp01 (<= 2/20 per healthy class, square excepted and reported), T7 met.
Otherwise nothing new ships. Targets are not lowered; the advice text may mention that periodic on/off or square disturbances mimic
stiction (a PI output under a square wave is roughly triangular when the forcing period is short against the integral time).

## Round 5 (amendment 1): C6 and the dev gate (2026-10-16)

C6 (logistic combiner on folded-wave features, trained on synth14 dev seeds 100-399 only). Grouped 5-fold CV on synth14: AUC 0.949
(F 0.956, L 0.917); threshold 0.6 by the frozen rule; flagged sine 10.0 %, tuning 9.3 %, square 1.8 %, stiction 86.8 %. Ablations (CV AUC):
without h3 0.871, without Horch 0.945 (Horch adds almost nothing; the third-harmonic ratios carry the separation from square forcing).
Shifted dev (seeds 1-100, read-only): AUC 0.846 versus 0.680 for C4a (L 0.903 versus 0.627); flags sine 11 %, square 6 %, tuning 29 %.
T7' (noise-only flagged): C6 1.0 %, C4a 0.7 %.
**Dev gate failed:** on exp01 dev C6 flags square forcing in 20/20 (both noise levels) and sine forcing at full noise in 20/20, against the
frozen limit of 2/20. By the frozen rule C4a is the finalist. A plausible cause, not tested: exp01 forces the SETPOINT (the record has no
SP column, a constant SP is passed), while the synthetic training set forces the LOAD; so C6 may be mis-calibrated for setpoint forcing, or
its good shifted-dev score may partly come from sharing the training generator's family. C6 was not run on the final data.

## FINAL RESULT (single run, `results/final.md`, 2026-10-16)

Finalist C4a versus the shipped module, never-seen seeds (exp01 21-40, synth14 500-599, shifted 1000-1099):

| Target | Result |
|---|---|
| T1 exp01 low noise bands 4, 6, 8 % >= 18/20 | 20/20 each (both): met |
| T2 exp01 full noise band 8 % >= 14/20 | C4a 10/20 [30 %, 70 %]; shipped 2/20 [3 %, 30 %]: MISSED, clear gain |
| T3 exp01 healthy classes <= 2/20 | C4a: 0, 0, 0, 2, 0, 0 (wander, aggressive tuning, sine; low/full noise), square 0/20: met |
| T3 synthetic healthy <= 10 % per class and noise | MISSED by both: sine 28 % (s14), square 45-59 %, tuning (s14) 5-13 % C4a vs 1-5 % shipped; shifted sine 7-50 % by noise |
| T4 AUC abstain = 0 >= 0.85 (s14 overall / F / L / short) | shipped 0.771 / 0.833 / 0.709 / 0.562; C4a 0.766 / 0.843 / 0.690 / 0.538: MISSED, no gain |
| T4 shifted AUC >= 0.80 | shipped 0.655, C4a 0.648: MISSED |
| T5 SACAC veto | shipped 6/6, 0 negatives flagged, 2 of 11 negatives ranked; C4a 6/6, 1 negative flagged, 3 of 11 ranked: met |
| T7 noise-only | C4a ranked 2/100, flagged 0/100; shipped 0/100: met |
| T6 `acceptance.md` of the shipped verdict | unchanged (not touched) |

Reading, plainly: C4a is not a better ranker in general (AUC unchanged). What it adds is detection of slow limit cycles at high noise in the
mill simulation (2/20 -> 10/20) without new false alarms there. Its price is a higher flag rate on synthetic tuning loops. Both versions
flag about 28 % of sine-forced and about 50 % of square-forced healthy synthetic loops: periodic disturbances mimic stiction by shape, so a
"test_valve" advice is a reason to test the valve, not evidence of stiction. No target of T4 or the synthetic T3 was met by any candidate.
Shipping rule (amendment 1): AUC within 0.02 of the shipped module (yes: -0.005 and -0.007), T2 gain (yes), no exp01 T3 regression (yes),
T7 (yes) -> C4a ships, with the limits in the module docstring and the report finding.

Constants of C4a and where they come from: PROMINENCE_MIN 36.5 = pooled 97th percentile of the largest peak prominence of 900 noise-only
records (white, AR(1) 0.5/0.9/0.98, random walk; `calib_prominence.py`, synthetic); all other constants are those of the shipped module.
Final seeds appear only in `final.py` (grep audit: `cache_synth.py` mentions them only in a comment).
