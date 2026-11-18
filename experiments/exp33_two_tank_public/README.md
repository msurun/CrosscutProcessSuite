# exp33: two-tank lab plant, public closed-loop level data (issue #86; protocol frozen 2026-11-18)

Question: do the Crosscut loop engines behave sensibly on real level-loop data from a controller whose tuning is
logged? Source: Gomez-Gonzalez et al., "Two-Tank Water System Dataset ...", Zenodo
doi:10.5281/zenodo.17688566 (v2.0 file `Dataset_v2.zip`, record 23529910), licence CC BY 4.0 (read from the Zenodo
API, `license.id = cc-by-4.0`). Data stays outside the repo (scratch folder); only code and results are committed.
Provenance row: `docs/PROVENANCE.md`.

Before freezing, only the dataset's own `README.txt` / `CHANGELOG.md` and per-file summary statistics (mean level,
share of saturation, median Kp, Ti, number of setpoint levels) were read. No Crosscut engine had been run on the data.

## Data (from the dataset README)

25 runs, 1 Hz, 30600 samples (8.5 h), staircase setpoint 10 -> 90 % in 5 % steps, 1800 s per step. SISO: pump command
`Control_Signal_pct` (%) -> upper tank `Level_pct` (%). Controller: adaptive incremental PID (Dahlin synthesis, lambda
3 s) retuned every sample from an RLS model; logged `Kp`, `Ki = Kp/Ti`, `Kd = Kp*Td` (v2 columns are corrected). The
RLS model has an input delay of two samples. All loops are in closed loop AUTO.
Groups: Baseline (10 runs, manual drain closed, no saturation, no dropouts) is the main set. PassiveOutflow (11) and
Disturbance (4) have frequent pump saturation and sensor dropouts (`Level_pct == 0`); they are used only where a target
says so. Mode is taken as AUTO (1) for every sample. Units: level and output in %, `Kc` dimensionless (% per %), `Ti` s.
Logged tuning of a run = median `Kp` and median `Kp/Ki` over rows 3.. with `Kp > 0` and `Ki > 0`.

## Protocol and targets (frozen)

**D1 (precondition, data reading):** `Kp` reproduces `-(a1 + 2 a2) Q / b1`, `Q = 1 - exp(-1/3)` (README formula) within
1 % on at least 90 % of the rows 3.. of every Baseline run. If D1 fails, the column mapping is wrong and the tuning
targets A1/A2 are not evaluated.

**S1 (setpoint-step KPIs against a reference):**
(a) the script's own step KPI function (IAE, overshoot, 5 % settling time after a setpoint step) on a synthetic first
order lag (tau 100 s, step 5, dt 1 s, 1800 s) gives IAE within 1 % of `A*tau = 500`, overshoot 0 and settling time
within 1 % of `tau*ln(20) = 299.6 s`;
(b) `tuning_review.window_metrics(...).iae_per_h` equals an independent numpy reference
`sum(|SP-PV|[:-1]) / (n-1) * 3600` within 0.1 % on all 25 runs.
Reported, no target: median IAE, overshoot and settling time of the 16 steps per group.

**M1 (monitor):** `monitor.analyze_loop` with `LoopSettings(delay_s=2, process_kind="integrating", scan_period_s=1,
known={out_range, delay})` (ultimate period and amplitude limit are unknown, so oscillation limits are withheld):
`saturation_fraction` within 0.01 of the independent share of `Control_Signal_pct` at 0 or 100, and
`classification == "saturated"` exactly when that share exceeds 0.2, on all 25 runs.

**I1 (closed-loop identification, repeatability):** `identification_cl.identify_fopdt_closed_loop(out, level, sp, 1 s,
max delay 20 s)` on each of the 10 Baseline runs (the same physical plant, repeated on different days). A run is
identified when no exception is raised. Met when at least 8 of 10 runs are identified and the integrator-equivalent
rate `k = gain / time_constant` of at least 8 of the 10 runs lies within +-30 % of the median `k` of the identified
runs. **I2 (delay):** at least 8 of 10 Baseline runs identify a delay in [1, 3] s (truth: 2 samples, dataset README).

**A1 (tuning assessment against the logged tuning):** `history_tuning.tune_from_history` on each Baseline run (full
record, dt 1 s). Runs with `status == "ok"` (high or medium confidence) are "assessed". For each, the recommended SIMC
`(Kc, Ti)` is compared with the logged `(Kc, Ti)`; the logged tuning is "in the SIMC band" when both ratios are within a
factor 3 (either direction). A1 is met when at least 3 runs are assessed and at least 80 % of them are in the band
(a recommendation to retune a loop that the band says is fine counts against). With fewer than 3 assessed runs A1 is
"not exercised", not met. Reported: confidence, windows used, fitted model, recommended vs logged values per run.
**A2 (vendor-form mapping):** `convert_pi(PiSettings(Kc, Ti), form)` on the logged tuning gives, for every Baseline
run, `gain_seconds` = (Kc, Ti s), `gain_minutes` Ti = Ti/60, `proportional_band_minutes` PB = 100/Kc and
`gain_repeats_per_minute` = 60/Ti, each within 1e-9 relative.

No target is changed after seeing results; a miss is reported as a miss. A generic engine gap found on the way is
recorded below as a FINDING (results go to `results.md`).

## Run

`python experiments/exp33_two_tank_public/run_exp33.py --data <folder containing the extracted Dataset/ folder>`;
exit 0 and nothing written when the files are absent. Prints the markdown tables used in `results.md`.

## Outcome (2026-11-18, details in `results.md`)

D1, S1, M1, I2, A2 met; I1 not met (the Baseline runs are not one plant: k falls with valve opening); A1 not exercised
(1 of 10 runs reached medium confidence). Findings: the settling KPI needs a band wider than the 8-bit level
quantisation; history tuning is unconfident on this closed-loop staircase data; delay is floored at one sample.
