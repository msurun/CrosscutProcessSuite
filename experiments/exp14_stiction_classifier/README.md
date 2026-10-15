# exp14: stiction classifier trained on synthetic loops only

Frozen on 2026-10-15 BEFORE any code of this experiment was run. No plant data with valve-test labels is
available (owner, 2026-10-15), so the only evidence is synthetic loops plus the 17 counted SACAC loops,
which are already contaminated by exp10-exp13. Everything below is a smoke test, not an accuracy figure.

## Design

- Synthetic training loops (`synth14.py`, seeds 100-199): PI loop with a stiction valve (positive) versus
  healthy valve with (a) sinusoidal load, (b) square-wave load, (c) aggressive tuning limit cycle with a
  delay (negatives). Kinds F and L, noise 0.02-0.15 of the oscillation, decimation 1/2/4/8 so that
  samples per half-cycle range from about 5 to 100.
- Features per record on its oscillation window (exp13 `suspicion.py`): He index (OP; PV for kind L) and a
  missing flag, Horch oddness (kind F only, else 0 plus flag), log samples per half-cycle, regularity,
  kind L flag. Model: logistic regression with L2 (numpy, no new dependency).
- Probability >= 0.5 means "test the valve". No threshold is tuned.

## Frozen targets

- C1 synthetic held-out (seeds 300-399, same generator): AUC >= 0.85.
- C2 baseline on the same synthetic held-out: AUC of the exp13 hand score is reported; C1 must beat it
  or the classifier is not worth having.
- C3 SACAC, same population and rules as exp13: R1 (AUC >= 0.80, held-out >= 0.70), R2 (>= 4/6 sticking
  flagged, <= 2 non-sticking ranked flagged), plus not worse than exp13 on both.
- C4 per-feature ablation on synthetic held-out (drop Horch, drop He): reported, no target.

## Rules

- One training run, one SACAC run. SACAC is not used for training, feature choice or the threshold.
- If C1 or C2 fails, keep the exp13 hand score and say so. If only C3 fails, report plainly; no tuning.
- SACAC stays local; only aggregates are logged.
