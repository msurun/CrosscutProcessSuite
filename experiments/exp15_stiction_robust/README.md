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
