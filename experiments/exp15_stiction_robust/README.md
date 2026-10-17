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
