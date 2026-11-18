# Benchmark protocol cmapss_degradation_v1 (frozen)

Status: protocol frozen; results NOT RUN YET. Issue #21. Provenance: `docs/PROVENANCE.md` (terms
UNVERIFIED - check before redistribution; data is never committed).

## Data

Saxena, Goebel, Simon, Eklund (2008), NASA Prognostics Data Repository, "Turbofan Engine
Degradation Simulation Data Set" (C-MAPSS). Download by hand (`run_benchmarks.py urls`) and unpack
into one folder (default `data/benchmarks/`, git-ignored): `train_FD001.txt`, `test_FD001.txt`,
`RUL_FD001.txt` and the same for FD002-FD004. Whitespace-separated, 26 columns: unit, cycle,
3 operating settings, 21 sensors.

## Split

The official split is used as is: fit on `train_FDxxx` (run-to-failure engines), predict one RUL
per test engine at its last recorded cycle, compare with `RUL_FDxxx`. All four subsets are
reported separately (FD001/FD003 one operating condition, FD002/FD004 six). No validation split
and no tuning on test data.

## Predictor

The suite has no degradation engine yet, so the runner ships a baseline: ridge regression
(lambda 1.0) on standardised settings and sensors (constant columns dropped), target = cycles to
failure capped at 125, features = mean of the last 5 cycles of the engine. No operating-condition
normalisation, so FD002/FD004 are expected to be poor. A future engine replaces `predict` only.

## Metrics

- RUL RMSE over the test engines.
- PHM08 score with d = predicted - true: sum of exp(-d/13) - 1 for d < 0 and exp(d/10) - 1 for
  d >= 0 (late predictions cost more). Lower is better for both.

## Seeds

Baseline is deterministic; seed 21 is recorded in the output for engines that are not.
Changing any value above makes a new protocol version (`_v2`).

## Results

Not run yet. Run: `python experiments/exp32_public_benchmarks/run_benchmarks.py cmapss --data <folder> --out <file>.json`.

| Subset | Engines | RMSE | PHM08 score |
|--------|---------|------|-------------|
| FD001  | 100 | not run yet | not run yet |
| FD002  | 259 | not run yet | not run yet |
| FD003  | 100 | not run yet | not run yet |
| FD004  | 248 | not run yet | not run yet |
