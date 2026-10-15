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

## Result (2026-10-15; `python -I run.py <folder>` regenerates results/report.md, which is not committed)

Floor 30 (as shipped): an index for 2 of 6 loops (Eastman LC2 0.53, Pisa chemical pressure 0.87).
Floor 10: an index for 4 of 6 (Horch level 0.71, Eastman 0.53, Pisa power level 0.67, Pisa chemical 0.87).
Target 1 (>= 4 of 6) met; target 2 (>= 50 % with index >= 0.6) met, 3 of 4 = 75 %. Still without an index: Horch flow
(half-cycle lengths vary too much) and Pisa oil&gas pressure (all 8 files, fewer than 10 samples per half-cycle).
Adoption rule: the exp01 acceptance run with floor 10 reproduced `results/acceptance.md` byte for byte (0 of 10
"stiction" on every healthy class, unchanged positives), so the package floor is now 10. Eastman LC2 stays between
0.4 and 0.6 (neither verdict). Limits: 6 loops, positives only, no false-alarm information from real data.
