# Experiment 11: how many samples per half-cycle does the stiction index need?

Why: `MIN_SAMPLES_PER_HALF_CYCLE = 30` in `stiction_curvefit.py` has no justification, and on the SACAC loops (exp10) it is the
main reason for "no verdict" (regular half-cycles of 10-25 samples are refused). Lowering it to 10 on the strength of those
loops was reverted for exactly that reason. Here the floor is derived from synthetic signals, with SACAC used only as a check.

## Design, frozen 2026-10-15 BEFORE the run

Signal: OP made of 40 alternating half-cycles of L samples (each length scaled by uniform 0.9-1.1), amplitude uniform 0.8-1.2,
shape = half-sine (healthy, no verdict "stiction" wanted) or triangle with the apex at 0.4-0.6 of the half-cycle (sticking),
plus white noise of sd s (as a share of the mean amplitude). Grid: L in {6, 8, 10, 12, 15, 20, 25, 30, 40, 60}; s in
{0.05, 0.15, 0.30}; 200 trials per cell (seed 1..200). `curve_fit_index` is called with the floor set to 1 so that only the
shape decision is measured; "refused" (no index for another reason) is counted separately.
Metrics per cell: detection = share of triangle trials with index >= 0.6, false alarm = share of sine trials with index >= 0.6.

**Criterion:** F = the smallest L in the grid such that for s in {0.05, 0.15} and for L and every larger grid value,
detection >= 80 % and false alarm <= 5 %. The s = 0.30 rows are reported, not required.

**Decision rule for the package:** if F <= 20, the shipped floor becomes F only if, in addition, none of the 6 real
negatives of exp10 round 3 gets an index >= 0.6 with floor F (run3 with the new floor; the SACAC data is a check, never an
input to F). Otherwise the floor stays 30 and the finding is logged. The synthetic sine/triangle pair is the textbook ideal;
real sticking OP is less clean, so F is a lower bound of what is needed, not a proof.

## Result (2026-10-15; table in results/sweep.md)

**Criterion NOT met: F = none**, so the shipped floor stays 30 and nothing in the package changed.
- Short half-cycles are unsafe: with 12 samples or fewer a healthy half-sine is read as a triangle in 21-100 % of trials
  (false alarm at L=10: 58-78 %, at L=6: about 100 %). The earlier floor of 10 was therefore wrong, not just unjustified.
- Noise is the bigger problem than length. At noise sd 0.15 of the amplitude detection falls from 84 % (L=15) to 4 % (L=30)
  and the rest is refused or reads about 0.5; at sd 0.30 nothing is detected at any length. Reason (derivation, not tested
  here): white noise adds the same variance to both fit errors, so SI = (a + v) / (a + b + 2v) tends to 0.5 when the noise
  variance v exceeds the small difference between the sine and triangle fits. This fits the real data: LC2 gave 0.53.
- Idea not tried, needs its own frozen targets: subtract an estimated noise variance from both errors (noise-aware index).
Limits: ideal shapes, white noise only, 200 trials per cell, no real data used in the derivation of F.
