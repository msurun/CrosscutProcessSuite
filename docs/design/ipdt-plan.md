# Plan: integrating (level) loops in the step-test tuning path (2026-10-22)

Origin: the owner will supply a real step test of a flotation machine level loop. Analysis by the opus advisor; GUI is part of every step.

## Diagnosis (code as of 2026-10-22)
`tuning_payload._report_for` never reads `loop.process_kind`. A ramp response goes through `identify_fopdt` (ARX with a ~ 1) and can end three ways:
(a) every a >= 1 is rejected, the wizard shows `blocked_code="model_failed"`; (b) a just below 1, the output-error refinement stretches tau up to 20x,
the fit verdict is "good", K and tau are huge, SIMC reduces to the IPDT rule so the numbers are right but the model display is nonsense, and
`closed_loop_step` (`tuning_view.py` about 141-148) runs 6(tau+theta)/(theta/10) Euler steps, possibly millions, so the request can hang;
(c) noise or drift biases a, giving a moderate tau and Ti = tau far too short (exp26 saw Ti at 0.02-0.07 of the correct value); `_guard_poor_fit`
(R2 >= 0.5) does not refuse it. No model term absorbs a baseline drift or load imbalance.

## Design
- `identification_ipdt.py`: `IpdtModel(slope_per_s, delay_s)` (slope in PV unit per second per % OUT). For each theta on a fractional grid solve least squares for
  y = y0 + beta*t + k' * integral(u(t - theta) - u0) dt; the beta column absorbs drift and the unknown balance OUT; theta = argmin SSE, refined like `identification_oe`.
  Works for single steps, doublets and step trains.
- Refusals. Block: R2 < 0.8, pre-move lead under 20 % of the window, time after the move under max(5 theta, 300 s), theta on a grid edge.
  Low confidence: relative standard error of k' (block bootstrap) > 20 %, or up and down k' differ by more than 25 %.
- Tuning `simc_pi_integrating`: Kc = 1 / (k' (tau_c + theta)), Ti = 4 (tau_c + theta) (Skogestad 2003, J. Process Control 13:291, tau1 -> infinity limit), no D term.
  Optional `max_swing` input: Kc_min = delta_u_load / delta_y_max, so tau_c = 1 / (k' Kc) - theta. AMIGO integrating only if its formula is verified against the source.
- Routing: `process_kind` selects the model in `_report_for`. Warning-only `looks_integrating` (FOPDT tau > 3 x window, or model_failed with IPDT R2 >= 0.8)
  and the reverse check for loops marked integrating. `closed_loop_step` gets a cap on the step count and an integrator branch.
- GUI (every step): process kind chooser and hint in the knowledge editor, the looks-integrating warning, the fitted ramp in the response chart, the
  recommendation with Kc and Ti for the integrating case, vendor forms, refusal reason text, en/pl/es strings, vitest and an e2e with axe.

## exp28 (frozen before any run)
Plant: the g26 integrator plus `crosscut_sim.valve`. Seeds: development 28001-28050, test 28101-28400 (only exp27's 27xxx ranges were found spent).
Pass: on accepted fits k' error <= 15 % and theta error <= max(dt, 30 %) in >= 90 % of runs; bad cases refused in >= 90 %; accepted settings 100 % settled and
not oscillating (exp26 criteria); `looks_integrating` false warnings <= 10 %. Cells with a valve deadband are report-only. The real flotation record is exploratory:
compare up and down k', check against valve Cv divided by cell area. Cells in series are coupled.

## Steps
I0 cap on closed-loop step count (hang fix) | I1 identification_ipdt + tests | I2 SIMC integrating rules + tests | I3 routing, warnings, payload |
I4 GUI (api.ts union, TuningPage branch, knowledge editor hint, warnings, strings, e2e) | I5 exp28 protocol frozen, harness by a different model, dev run, test run once |
I6 import helper and format check for the owner's record, docs, handoff.
