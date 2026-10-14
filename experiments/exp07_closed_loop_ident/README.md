# exp07: identifying a FOPDT model from closed-loop data (setpoint as instrument)

Question (C3 part 2): `identify_fopdt` is a direct least-squares ARX fit on (OUT, PV). With the controller in AUTO and an
unmeasured, coloured load disturbance, OUT is correlated with the disturbance, so the estimate is biased (see exp00). Does an
instrumental-variable fit that uses only the setpoint as instrument (`identification_cl.identify_fopdt_closed_loop`, two-stage
least squares, setpoint lags as instruments) remove the bias?

Setup: true process K = 2, T = 50 s, L = 10 s, dt = 1 s (`crosscut_sim.core.Fopdt`), SIMC PI with tau_c = L, 4 h per run,
setpoint steps of +-1 every 20-40 min (random), load disturbance = Ornstein-Uhlenbeck at the process input (sd 0.5, correlation time
600 s) plus PV noise sd 0.05, seeds 1-20. Compare the direct fit and the IV fit on the same data.

## Acceptance targets (frozen before the first run, 2026-10-14)

- **I1:** median absolute relative gain error of the IV fit is at most 15 %.
- **I2:** the median absolute relative gain error of the IV fit is at most 0.7 x that of the direct fit (a real improvement); if the
  direct fit is already within 15 % the experiment says so and I2 is reported as "not needed", not as a pass.
- **I3:** the IV fit's median delay error is at most 3 samples and its median time-constant error at most 30 %.
- **I4:** with a constant setpoint (no excitation) the IV function raises ValueError instead of returning a model.

If a target is missed the finding is logged as it is; the thresholds are not changed afterwards.

## Result (run 2026-10-14, `python exp07.py` and `python exp07.py 21`)

**Version 1 of the method** (rows per delay, residual scored on the raw output), seeds 1-20: direct fit gain error 42 % (median, gain too low),
time constant +131 %, delay -1 sample; IV fit gain error 16 %, time constant +379 % and delay +14 samples. Targets: I1 FAIL, I2 PASS, I3 FAIL, I4 PASS.
The delay choice was the culprit: on the raw output the disturbance dominates the residual, so long delays won.

**Version 2** (diagnosed on seeds 1-20, then checked on fresh seeds 21-40; targets unchanged): all delays scored on the same rows and on the
setpoint-explained part of the output (projected residual). Seeds 1-20: gain 16.0 %, time constant 15.2 %, delay error 1 sample. **Seeds 21-40 (not used for the
change):** gain 19.1 % (p90 75 %), time constant 26.0 %, delay error 1 sample; direct fit on the same seeds: gain 41.1 %, time constant +133 %.
Targets on the fresh seeds: **I1 FAIL** (19.1 % > 15 %), I2 PASS (0.46 x the direct error), I3 PASS, I4 PASS.

Reading: the direct fit is badly biased with a coloured load disturbance (gain 40 % low, time constant 2.3 times too large), and the setpoint-instrument fit removes most
of it (time constant and delay now usable), but the gain is still 16-19 % off and has a heavy tail (p90 75 % on seeds 21-40). Use the result as an
advisory model with that error bar, and prefer a step test with the controller in MAN when it is allowed. Limits: one plant (K 2, T 50, L 10), one controller tuning,
strong coloured disturbance, setpoint toggles every 20-40 min; with a weaker disturbance the direct fit improves. The instrument lags (40 samples) were not tuned.

Instrument lags (checked afterwards on seeds 1-20, diagnosis only): 20 / 40 / 80 / 150 / 250 lags give a median gain error of 15.9 / 16.0 / 16.1 / 16.3 / 16.8 % and a time-constant error of
13 / 15 / 14 / 20 / 21 %. The number of lags is therefore not what keeps the gain above the 15 % target; the remaining error is a property of the method on this data.
