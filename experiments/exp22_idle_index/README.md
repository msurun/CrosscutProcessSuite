# exp22: idle index for sluggish loops on simulated PI loops (protocol frozen 2026-10-19, BEFORE any run)

Question: does the idle index (Hagglund 1999; our implementation in `crosscut_loops/idle_index.py`, spec below)
separate sluggish PI loops from well-tuned and aggressive ones on closed-loop simulations with load disturbances,
noise and both process-gain signs, with no per-loop knowledge? Everything is synthetic. A pass supports "a sluggish
finding works on the simulated suite", nothing about plants.

## Detector spec (implementation by one model, generator by a different model)

`idle_index(pv, sp, out, dt_s) -> IdleIndex(value, gain_sign, counted, stride, reason)`; arrays of equal length.

1. NaN in any input or unequal lengths: ValueError. Fewer than 200 samples: value None, reason "too short".
2. Error e = sp - pv. Time scale: q = first lag where the biased ACF of the linearly detrended e is <= 0, at most
   n // 4. Stride L = max(1, round(q / 4)). Increments dy[k] = pv[k+L] - pv[k], du[k] = out[k+L] - out[k],
   k = 0..n-L-1, kept only where sp[k..k+L] is constant (setpoint changes are not load recoveries).
3. Noise gate. Per signal x in {pv, out}: sigma_x = 1.4826 * median(|x[k+2] - 2 x[k+1] + x[k]|) / sqrt(6) (white
   noise std from second differences; smooth motion contributes little). An increment pair counts when
   |dy| > 2 * sqrt(2) * sigma_pv and |du| > 2 * sqrt(2) * sigma_out, and both are non-zero.
4. Gain sign: s = sign(sum_k (out[k+1] - out[k]) * e[k]) over samples with constant sp. With integral action the
   output drifts in the direction of the error times the process-gain sign, so s is that sign for a correctly
   configured loop. s = 0: value None, reason "gain sign unknown".
5. Ii = s * (n_pos - n_neg) / (n_pos + n_neg) over counted pairs, where n_pos counts du * dy > 0. Fewer than 30
   counted pairs: value None, reason "too little movement". Ii near +1: output and measurement keep moving the same
   way (with positive gain) during recovery, i.e. the controller is slow; negative: fast correction.

## Simulated loops (generator spec G22, written by a different model than the detector)

`g22_loops.simulate(case, seed) -> dict(t_s, pv, sp, out, true_gain_sign)`, dt = 1 s, n = 8000 samples, using
`crosscut_sim.core.Fopdt` and `crosscut_sim.pid.PID` (positional ISA PI, output limits 0..100, bias 50).

- Plants (9): gain K in {+1, -1, +3} paired with (tau, theta) in {(20, 2), (60, 10), (150, 30)} - every K with every
  pair. For K < 0 the controller is direct acting (`direct=True`) with positive Kc.
- Tunings (4): base SIMC with tau_c = theta: Kc = tau / (|K| (tau_c + theta)), Ti = min(tau, 4 (tau_c + theta)).
  "good" = base; "aggressive" = Kc x 1.8, Ti x 0.7; "sluggish" = Kc x 0.2, Ti x 4; "mild" = Kc x 0.5, Ti x 2.
- Load disturbance d added to the controller output before the plant (plant input u + d), three kinds:
  "steps": d is piecewise constant, new level uniform in [-15, 15] at Poisson times with mean spacing
  10 (tau + theta) samples; "steps_ou": steps plus an Ornstein-Uhlenbeck component (std 2, time constant tau);
  "ou": OU only (std 5, time constant tau).
- Measurement noise on pv: white, std in {0, 0.005, 0.02} x 10 |K| (fraction of the PV response to a 10 % step).
- SP constant at 50; PV operating point 50 (plant output in deviation + 50).
- Seeds: development 0..19, test 100..119 per cell (9 x 4 x 3 x 3 = 324 cells).

## Targets (frozen)

Flag rule: sluggish when Ii > theta. theta is chosen on development seeds from {0.0, 0.1, 0.2, 0.3, 0.4, 0.5}:
the smallest theta whose false-flag share (Ii > theta among "good" and "aggressive" runs) is <= 10 % pooled and
<= 25 % in every plant x disturbance cell. A None value never flags.

- **S1 (sensitivity):** "sluggish" runs flagged >= 80 % pooled (dev to choose, test to confirm).
- **F1 (false flags):** "good" + "aggressive" flagged <= 10 % pooled on the test seeds.
- Reported, no target: "mild" flag share, None shares and reasons, gain-sign accuracy against `true_gain_sign`,
  per plant / disturbance / noise shares.
- If no theta in the grid meets the dev condition, or S1/F1 miss on the test seeds: the idle index is reported as
  a number only, without a "sluggish" finding. Constants are not edited after the development run.
- If it passes: monitor adds `idle_index` to LoopReport and a "sluggish suspected" finding when Ii > theta and
  the loop is not oscillating (an oscillating loop has its own finding).
