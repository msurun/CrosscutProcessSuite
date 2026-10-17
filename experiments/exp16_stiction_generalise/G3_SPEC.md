# G3 generator specification (physics only; the implementer sees nothing else)

Write `g3.py` in this folder: a generator of closed-loop records for a SISO PI/PID loop with a
sticking or healthy valve. Python 3.12, numpy only. No access to, or knowledge of, any detector.

## API

`simulate_g3(rng: np.random.Generator, kind: str, case: str, noise: str) -> G3Record`
- `kind`: "F" self-regulating (flow/pressure/temperature type) or "L" integrating (level type).
- `case`: "stick" (valve stiction present) or one healthy case among
  "load_sine", "load_square", "load_multitone", "sp_square", "sp_steps", "tuning_aggressive",
  "tuning_sluggish", "quiet" (no oscillation).
- `noise`: "low", "mid", "high" (measurement noise std as 0.2 %, 1 %, 4 % of the PV swing in
  the record; the generator decides the swing from the case).
- `G3Record` dataclass: `sp, pv, op` (float arrays, same length), `label` (1 for "stick", else 0),
  `dt_s`, `meta` (dict with every drawn parameter, for audit).

## Plant (draw all parameters from log-uniform ranges below; document them in the module docstring)

- F: first-order plus dead time, gain 0.5-3, time constant 5-200 s, dead time 0.1-2 time constants
  (include deadtime-dominant draws), optional second lag.
- L: integrator with gain 0.002-0.05 1/s, dead time 1-20 s, optional first-order lag.
- Sampling dt 1, 2 or 5 s; record length 2000-8000 samples after discarding a 500-sample
  settling period. Controller: PI (Ti 0.3-3 times the dominant time scale; Kc such that the
  healthy loop is stable with phase margin 40-70 degrees), optional derivative filter. Optional
  cascade: an inner fast loop (time constant 1/10 of outer) whose setpoint is the outer OP;
  the recorded `op` is the signal that drives the valve, `sp` is the OUTER setpoint.
- Valve: static gain 1, optional first-order actuator lag.

## Stiction (case "stick")

Randomly choose one model: (a) Choudhury two-parameter (deadband S, slip J) with S 0.5-6 %,
J 0-0.7 S; (b) Kano simple-sticking-band model; (c) He one-parameter model. Valve position
changes only when the input leaves the band; after sticking it slips. Draw a constant load so
the loop sits away from equilibrium and a limit cycle forms. Reject draws that do not
oscillate (fewer than 5 cycles) and redraw.

## Healthy disturbance cases

- load_sine / load_square / load_multitone: a periodic load disturbance entering at the plant
  input; period 0.5-10 times the loop dominant time scale (so periods both shorter and longer
  than Ti occur); amplitude giving PV swing of 3-20 % of range; multitone = 2-3 incommensurate
  tones. No valve nonlinearity (ideal valve; optional tiny quantisation).
- sp_square / sp_steps: the SETPOINT is a square wave (period as above) or a random staircase of
  4-12 steps; the `sp` output must contain it.
- tuning_aggressive / tuning_sluggish: Kc raised x2.5-4 resp. Ti x3-6; small noise-driven or
  random-walk load; ideal valve.
- quiet: random-walk load only.

## Measurement chain (all cases, applied to PV and OP as recorded)

- Measurement noise as given by `noise`, white or AR(1) with coefficient 0-0.8 (random).
- Sensor lowpass filter with time constant 0-3 samples (random).
- Quantisation of PV and OP to 0.05-0.5 % of range (random, both independently).
- Optional historian compression (30 % of records): deadband compression of PV and OP with a
  0.1-0.5 % deadband followed by linear-interpolation resampling to the regular grid.
- Optional missing data (10 % of records): 1-3 gaps of 3-30 samples filled by hold-last-value.
- Output scaled to percent of range 0-100 with a random offset.

## Requirements

- Deterministic given `rng`. Pure function, no global state, no file output.
- Functions <= 20 lines, docstring on every function, 2-4 line file header.
- A self-test `python g3.py` simulates 3 records of every kind/case/noise combination (one seed),
  checks finite arrays, equal lengths, label correctness and prints a table of length, dt,
  number of PV cycles (by zero crossings of detrended PV). Do not add anything else.

## Simulation conventions (added after a first implementation drifted: follow exactly)

- Deviation variables. Valve position v and controller output op are in percent, equilibrium
  v = 50. Plant input u = (v - 50) + load (load is an additive deviation at the plant input,
  percent). Plant output deviation y: F: y = gain * lag(u delayed by dead time); L: dy/dt =
  gain * (u delayed) then optional lag. Measured pv = 50 + y, clipped to 0..100.
  Both plants start at y = 0 with the controller integral initialised so that op = 50 - load[0]
  (steady state), so no start-up transient dominates.
- Positional PI on e = sp - pv: op = op_bias + Kc*(e +
  I/Ti), I' = e, clip op to 0..100 with conditional-integration anti-windup, where op_bias is
  chosen so the initial state is steady state. Derivative (if used) on pv through a filter.
- Tuning (SIMC): F: tau_eff = tau + tau2; tau_c = max(theta, 0.3 * tau_eff) * U(1, 2);
  Kc = tau_eff / (gain * (tau_c + theta)); Ti = min(tau_eff, 4 * (tau_c + theta)) * U(0.5, 2).
  L: tau_c = theta * U(1, 3); Kc = 1 / (gain * 2 * (tau_c + theta)); Ti = 4 * (tau_c + theta) *
  U(1, 3). tuning_aggressive multiplies Kc by U(2.5, 4) (stable loops still preferred: if the
  closed loop diverges, redraw); tuning_sluggish multiplies Ti by U(3, 6).
- Time scale for excitation periods: F: tau_eff + theta; L: 4 * (tau_c + theta).
- A record is valid only if pv stays finite and its peak-to-peak is at least 1 percent.
