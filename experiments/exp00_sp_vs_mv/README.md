# Experiment 0: setpoints versus actuator signals in closed-loop identification

**Question.** In the synthetic grinding circuit the operator changes the setpoints every 30 minutes as a function of
the ore hardness, and the hardness also drives the product size (P80). Which input signals recover the true causal
gain of the HPGR pressing force (and of mill feed and cyclone water) on P80 from such closed-loop data?

**Setup.** `python experiments/exp00_sp_vs_mv/exp00.py --seeds 5 --hours 48` (about 30 s). Data comes from the
`mill_circuit` plant through the standard dataset pipeline (5 s step, 30 s samples). Two scenarios:
`observational` (operator on, confounded) and `excited` (operator off, random-binary setpoint moves, the
unconfounded reference). Estimator: least-squares FIR model (30 min horizon, intercept); the gain is the sum of the
FIR coefficients. Signal variants: setpoint (SP), measured actuator state (PV), controller output (OUT), each raw or
high-passed (10 min moving average removed from inputs and output), and PV with the noisy hardness estimate as an
extra regressor. Truth: `MillCircuitPlant.true_gain` at hardness 14. Results: `results/results.md`,
`results/results.csv`, `results/gains.png`.

## Result for the pressing force (true gain -20 um per N/mm2, mean +/- std over 5 seeds)

| variant | observational (confounded) | excited (reference) |
|---|---|---|
| SP raw | 0.1 +/- 5.0 | -22.2 +/- 5.3 |
| SP high-pass | -20.4 +/- 1.5 | -19.2 +/- 2.3 |
| PV raw | -0.1 +/- 4.8 | -22.3 +/- 5.4 |
| PV high-pass | -21.2 +/- 1.3 | -19.7 +/- 2.0 |
| OUT raw | 0.1 +/- 0.3 | -1.5 +/- 0.4 |
| OUT high-pass | -1.0 +/- 0.1 | -1.1 +/- 0.2 |
| PV raw + hardness estimate | -11.4 +/- 2.8 | -20.8 +/- 2.4 |

## What it shows

1. **Confounding is real.** With the operator on, the raw SP and PV models see no effect of the pressing force at
   all (about 0 instead of -20), and for mill feed and cyclone water they even get the wrong sign.
2. **Fast variation identifies the gain.** After high-passing, both SP- and PV-based models recover the gain
   (-20.4 and -21.2 versus -20) because the slow hardness-driven variation is removed and what remains is the
   response to the fast moves.
3. **In this simulator the decisive factor is the timescale, not SP versus PV.** SP high-pass works as well as
   PV high-pass. The claim "train on the actuator signal, not on the setpoint" is therefore only supported to the
   extent that the actuator signal carries fast, exogenous variation (process noise); it was not distinguished from
   simple high-pass filtering here.
4. **The controller output is a poor input.** The loop makes OUT counter-move disturbances, so it is a poor proxy for
   the actual actuator state (gain estimates are strongly biased).
5. **Adjusting for a noisy confounder helps only partly** (-11.4): the hardness estimate is sampled every 30 minutes
   and noisy.

## Limits

The plant is synthetic and its confounder is slow (4 h) relative to the operator moves (30 min) and the process
dynamics (minutes); the result depends on that timescale separation. The gain varies with hardness, so the truth is
quoted at hardness 14 only. Five seeds give rough error bars. No real plant data was used.
