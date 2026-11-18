# Benchmark protocol tep_anomaly_v1 (frozen)

Status: protocol frozen; results NOT RUN YET. Issue #21. Provenance: `docs/PROVENANCE.md` (licence
UNVERIFIED - check before redistribution; data is never committed).

## Data

Rieth, Amsel, Tran, Cook (2017), Harvard Dataverse, doi:10.7910/DVN/6C3JR1. Download by hand
(`python experiments/exp32_public_benchmarks/run_benchmarks.py urls`) the .RData files
`TEP_FaultFree_Training`, `TEP_FaultFree_Testing`, `TEP_Faulty_Testing` and convert each to a CSV
with the same base name in one folder (default `data/benchmarks/`, git-ignored). Columns:
`faultNumber, simulationRun, sample, xmeas_1..xmeas_41, xmv_1..xmv_11` (52 variables, 3 min
sampling). `TEP_Faulty_Training` is not used.

## Split

- Training: fault-free training file, 10 runs drawn with `numpy.random.default_rng(21)` from the
  runs present (without replacement, sorted). All rows of these runs fit one PCA model.
- Test: 10 runs drawn with seed 22 from the fault-free testing file; the same run numbers are
  used for fault 1-20 of the faulty testing file (960 samples = 48 h, fault enters after sample
  160 = 8 h, 0-based index 160).
- Detector: `crosscut_anomaly` with variance_fraction 0.90, alpha 0.99, min_consecutive 5,
  close_after 10, no dynamic lags, no stuck rule, sample period 180 s. Each run is scanned alone.

## Metrics (per fault, over the 10 runs)

- Detection rate: share of runs with an event starting at or after index 160.
- Detection delay: first such event's start index minus 160, mean over detected runs, in samples
  and minutes (x 3).
- False alarm rate: samples inside events before index 160 divided by pre-onset samples (events
  starting before 160 are false alarms and are never credited as detection).
- Fault-free false alarm rate: the same measure over all samples of the fault-free test runs.

## Seeds

Run picks 21 (training) and 22 (test). The detector is deterministic. Changing any value above
makes a new protocol version (`_v2`); do not tune on these runs.

## Results

Not run yet. Run: `python experiments/exp32_public_benchmarks/run_benchmarks.py tep --data <folder> --out <file>.json`.

| Fault | Detection rate | Mean delay (min) | False alarm rate |
|-------|----------------|------------------|------------------|
| 1-20  | not run yet    | not run yet      | not run yet      |
| fault-free | -         | -                | not run yet      |
