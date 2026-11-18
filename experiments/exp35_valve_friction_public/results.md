# exp35 results (run 2026-11-18, protocol and targets as frozen in README.md, commit f085030)

Command: `run35.py --data <folder with the two CSV files>`; raw numbers in `result35.json`. No parameter was changed
after seeing the result. S_ref = 26.42 % of span (published Choudhury S), tolerance 5.0.

| File | blocks | Crosscut deadband (bracket) | |err| | Reference median (n reversals, IQR) | |err| | resolution_le |
|---|---|---|---|---|---|---|
| ramps | 2841 | 31.28 (30.28, 32.28] | 4.86 | 32.61 (15; 32.26-34.76) | 6.19 | <= 2.0 |
| sinusoidal | 2768 | 31.16 (30.16, 32.16] | 4.74 | 32.18 (11; 32.00-32.79) | 5.76 | <= 2.0 |

| Target | ramps | sinusoidal | Verdict |
|---|---|---|---|
| T1 Crosscut within 5.0 of S_ref | met (4.86) | met (4.74) | met, but by 0.14 and 0.26 only |
| T2 reference within 5.0 of S_ref | MISSED (6.19) | MISSED (5.76) | missed |
| T3 bracket contains S_ref (info) | no | no | - |
| T4 resolution consistent with J (info) | yes (<= 2.0) | yes (<= 2.0) | - |

**Verdict under the frozen rule: inconclusive.** T1 passes on both files, but T2 failed, so the agreement with the published
S is not corroborated by the independent computation and the acceptance of #84 is NOT claimed as reproduced.

## What the numbers say

- The two estimators (Crosscut bracket method and the zigzag reference) agree with each other within about 1.3 % of span
  on both files (31.3 vs 32.6; 31.2 vs 32.2), and the two files agree with each other. The observed travel after a
  reversal before the stem visibly moves is about 31 to 33 % of the input span.
- Both sit about 5 to 6 % above the compiled Choudhury S (26.42). The Crosscut estimate passes only because its midpoint
  convention (bracket midpoint, gate at half the free-valve response) reads about 1 % lower than the reference gate.
- Hypotheses, NOT tested: (a) the model S is not the same quantity as the first visible stem move (the visible-move gate
  adds a few % of travel because the stem slips by only J = 0.09 % at first, and the model also has the offset D = 14.5);
  (b) the compiled parameters are not the estimate for these exact files; (c) block means of u% and the stem lag under
  the 50-sample block add a systematic offset. Separating them needs the thesis and a simulated Choudhury valve driven
  through the same pipeline (a model-consistency check), which was not done.
- T4 and resolution: with a 2 % step the analysis certifies only "<= 2.0 %"; J = 0.086 % cannot be tested this way.

## Generic findings for the product

- The stroke test analysis runs unchanged on a real measured-stem record rebuilt as a staircase and returns a stable
  deadband (31.2 to 31.3 on two different excitations), so it is not fragile on real noise; accuracy against a model
  parameter is unproven.
- The planned default step sizes (1.0 and 0.25 %) could not bracket this valve (deadband about 30 % of span); a larger
  first step size option is needed for stiff or very sticky valves (the docs already note that the CLI has none).
- Comparing against a model parameter is weak validation: a valve test needs a directly measured reference (stem position
  versus a known step). This data has the stem position, so a true staircase test from it is possible only by replay;
  a real stroke test record with positioner feedback is still missing.
- DAMADICS remains blocked on terms.
