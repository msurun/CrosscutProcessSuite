# exp17: tuning from historian data (no dedicated step test)

Question: how many real loops contain natural setpoint steps, and can the loop be tuned from them?
Code: `loops/src/crosscut_loops/history_windows.py` (finds steps), `history_tuning.py` (output-error
FOPDT fit per window, cross-checked on the other windows, graded high / medium / low / none).
Closed-loop IV identification was tried first and rejected: on short windows it gave the right gain
and the wrong time constant (4 s against 60 s); the output-error fit recovers gain, time constant
and dead time within 1-2 % on clean data.

## Simulation (known plant K=2, tau=60 s, theta=8 s, PI loop, five setpoint steps)
- No load disturbance: 8 of 8 seeds graded high and accurate (gain, tau within 2 %, delay within 1-2 samples).
- Load disturbance 0.1 and 0.3 of the noise scale used in tests/test_history_tuning.py: all seeds
  graded low (windows disagree), none graded high. Recommendation then: guided bump test.
- No setpoint step: no_excitation, nothing is guessed.

## Real data (counts only, no ground truth; run17.py)
- SACAC files: 19 of 37 records have a setpoint step; confidence 17 low, 20 none (no step).
- ISDB labelled loops: 8 of 49 have a step; 7 low, 42 none.
- No real loop reached high or medium. Tuning from history is therefore rarely available; the product
  answer for most loops is "recommend a bump test", with history tuning as a bonus where the data allow.

Unproven: accuracy on real plants (no tuning ground truth exists); behaviour with ramp or rate-limited
setpoint changes; cascade secondary loops; level (integrating) loops (the fit is FOPDT only).
