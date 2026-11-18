# exp34: Cascaded Tanks public data (open-loop pump voltage to level, with overflow), issue #83

Protocol FROZEN 2026-11-18 BEFORE any engine was run on the data. A miss is logged, thresholds are not moved.
The data is licensed CC BY-SA 4.0: used locally only, never committed, no derived series or plots committed (only aggregate numbers in results.md).

## Data
Schoukens and Noel, Cascaded Tanks benchmark (IFAC 2017), 4TU.ResearchData doi:10.4121/12960104, `CascadedTanksFiles.zip` (7 520 592 bytes, md5 f832776e... matches the 4TU record).
`dataBenchmark.csv`: columns uEst, uVal (pump voltage, V), yEst, yVal (level of the lower tank, V), Ts = 4 s, 1024 samples per set. y reaches the 10 V sensor limit
when the upper tank overflows (hard nonlinearity). Before freezing I looked at the CSV shape, ranges and the share of samples at 10 V (about 4 to 5 %), and at the
input increments (smooth multisine, no step events, max |du| 0.3 V per sample). I did not run any Crosscut engine.

## Question
Two coupled tanks are SELF-REGULATING (level settles for a constant pump voltage) and nonlinear (outflow ~ sqrt(level), overflow). The input is a random multisine, not a step test.
Does the toolchain avoid claiming an integrating level process and an averaging-level tuning here, does it prefer FOPDT, and does it flag the overflow?
Units: u in V is used as OUT, y in V as PV (the loop engines do not need %; slopes are V per s per V).

## Procedure (script `run_exp34.py --data DIR`; sets: Est and Val, t = 4 s * k)
1. `identify_ipdt(t, u, y)` on the whole record, default settings; verdict and reasons.
2. `fit_step(t, y, u, pre=20, "ipdt")` and `fit_step(..., "fopdt")` on the whole record; compare BIC, report r2, tau, theta, `edges`, `effective_delay_s(fit, 4.0)`.
3. `saturation_fraction(y, 0.0, 10.0)` (shipped margin 0.5 % of range, so y >= 9.95 V counts).
4. Clip-free segment: samples before the first y >= 9.95 V; repeat steps 1 and 2 there (report only).
5. Report only: if the IPDT slope is positive, `tau_c_for_max_swing` with load 10 % OUT, max swing 5 V, and `simc_pi_integrating`, to show what a user would be offered.

## Targets (both sets must pass)
| id | criterion |
|----|-----------|
| K1 | `identify_ipdt` on the whole record is NOT verdict "ok" (self-regulating process must not get a trusted integrating model / averaging-level tuning). |
| K2 | `fit_step` FOPDT BIC is lower than IPDT BIC on the whole record (the self-regulating model wins). |
| K3 | `saturation_fraction(y, 0, 10)` is between 0.02 and 0.08 (overflow / sensor limit visible; a saturation-detecting monitor would see it). |
| K4 | `fit_step` runs on both sets without exception and its FOPDT fit has gain > 0 (right sign: more pump, higher level). |

## Decision rule
K1 miss: the integrating identification can bless a self-regulating nonlinear record, a generic engine gap (record as a finding, fix only in a separate frozen round).
K2/K3/K4 misses are logged. No tuning on the results.

## What this does not show
No step test exists in this record, the input is a multisine, so step-event detection and the averaging-level recommendation under real step conditions are not tested; the plant is a lab rig
(small tanks, volts, 4 s sampling), not a plant level loop. Whole-record fits of a nonlinear plant with a linear model are expected to be poor; the target is the refusal and model choice, not accuracy.

## Frozen files
`run_exp34.py` is written after this README is committed and only reads the data from the folder given on the command line. Without data it prints "not run: data unavailable" and exits 0.
