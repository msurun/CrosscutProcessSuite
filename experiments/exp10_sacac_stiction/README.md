# Experiment 10: the OUT-shape stiction index on the SACAC stiction loops

Data: the 12 files of the category "Stiction" of the SACAC repository (https://sacac.org.za/resources/): 6 distinct loops
(Horch flow F, Horch level L, Eastman level LC2, Pisa power level, Pisa chemical pressure, Pisa oil&gas pressure; the
oil&gas loop also comes as 7 repeated runs DB-1..7). The repository labels all of them as valve stiction, so there are NO
negatives: this experiment can only say how often a known sticking loop is found, never how often a healthy loop is
flagged. Licence of the data is not stated: local use only, not committed (see docs/PROVENANCE.md). Sampling periods come
from the .txt files (1, 1, 20, 5, 30, 12 s). Usage: `python run.py <folder with the unzipped repository>`.

## Targets, frozen 2026-10-15 BEFORE the run (the exploratory first look is in the log)

The detector is `crosscut_loops.stiction_curvefit.curve_fit_index` on OP, thresholds 0.4 / 0.6 from the paper, untouched.
- **S1 (as shipped, 30 samples per half-cycle):** no target; report index, cycles and reason per file.
- **S2 (variant: half-cycle floor 10 samples):** target 1: at least 4 of the 6 distinct loops get a numeric index.
  Target 2: of the loops that get one, at least 50 % have an index >= 0.6 ("stiction"). Repeated runs of one loop count once
  (median index of its runs).
- **Adoption rule for the floor:** the constant is lowered in the package ONLY if (a) S2 meets both targets AND (b) the exp01
  acceptance run (`acceptance.py`, held-out seeds 11-20) with the same floor still shows 0 of 10 "stiction" for each of the
  three healthy classes and no loss in the positive cells that met their target. Otherwise it stays 30 and the miss is
  logged. The floor is never tuned on the SACAC files.
- Missing the targets is reported as it is.

## Result (2026-10-15, CORRECTED the same day after review; `python -I run.py <folder>` regenerates results/report.md, not committed)

Floor 30 (as shipped): an index for 2 of 6 loops (Eastman LC2 0.53, Pisa chemical pressure 0.87).
Floor 10 (variant): an index for 4 of 6 (Horch level 0.71, Eastman 0.53, Pisa power level 0.67, Pisa chemical 0.87).
The two loops the lower floor added are LEVEL loops, i.e. integrating processes, for which `detect_stiction` itself says the
method does not apply. Without them the only clean hit is Pisa chemical pressure (0.87), which already had an index at floor 30.

**Errors in the first write-up of this result (retracted):**
- "3 of 4 = 75 %" used only the loops that got an index. Against the 6 labelled loops it is 3 of 6; counting only loops
  inside the method's scope (self-regulating: Horch flow, Pisa chemical, Pisa oil&gas) it is 1 of 3 or 1 of 4 depending on
  how the unclassified Horch flow is counted, i.e. detection is poor on real data.
- The floor of 10 was chosen after seeing this data (about 11 samples per half-cycle in the first look), so the sentence
  "never tuned on the SACAC files" was false.
- The exp01 check was vacuous: the identical `acceptance.md` means no simulated half-cycle has 10-30 samples, so it could not
  show the lower floor is safe. Adoption rule (b) was met only because nothing was exercised.
- Both targets were easy by construction (>= 4 of 6, >= 50 % of those with an index).

Decision: the package floor is back at 30 (commit that follows this text). Eastman LC2 at 0.53 is most likely a method effect
(integrating level loop: the OP is part triangle, part parabola, which fits a sine and a triangle about equally), not a
threshold problem. Limits: 6 loops, positives only, no false-alarm information; treat everything here as anecdote.

## Round 2: score by process type (targets frozen 2026-10-15 BEFORE the run)

Basis: He et al. 2007 fit the signal of the first integrating element after the valve: OP for self-regulating processes, PV
for integrating ones (read from the abstract-level listings only, not the full paper; to be confirmed). Floor stays 30 and
nothing in the package is changed by this round.
- Level loops (integrating): Horch level, Eastman LC2, Pisa power level, scored on PV with the same `curve_fit_index`.
  **Target L: at least 2 of the 3 get an index >= 0.6.** Missing it means the PV variant does not rescue level loops.
- Self-regulating loops (Horch flow, Pisa chemical pressure, Pisa oil&gas pressure), scored on OP as in round 1: no target,
  the round-1 numbers stand (index for 1 of 3).
- Overall claim allowed after this round: "k of 6 known sticking loops flagged", nothing about false alarms or accuracy.

### Round 2 result (2026-10-15)

**Target L MISSED: 0 of 3 level loops get an index on PV.** All three are refused by the same rule: on PV a half-cycle has
fewer than 30 samples (zero-crossing chatter from measurement noise splits cycles: e.g. Pisa power level finds 175 cycles
where OP gives the same count with short halves; Eastman LC2 finds 25 on PV against 23 on OP). The raw PV is not filtered
before the segmentation, so this is "no verdict", not a verdict against the PV idea. Total over both rounds at floor 30:
1 of 6 known sticking loops flagged (Pisa chemical pressure, 0.87), LC2 inconclusive on OP (0.53), 4 without an index.
Not tried, and not to be tried without new frozen targets: low-pass filtering of PV, smoothing the zero-crossing detection.
`run2.py` reproduces this; nothing in the package changed.
