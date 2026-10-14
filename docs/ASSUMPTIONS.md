# Assumption register

Every assumption that the simulators or the code make about real plants and real systems, with the level at which it
is (or will be) tested. Review at the end of every stage; add a row whenever a new assumption appears.
Status: open / partly tested / retired.

| ID | Assumption | Where it lives | How to test it | Level | Status |
|---|---|---|---|---|---|
| A1 | Process noise is stationary and Gaussian-like with a correlation time of minutes | simulators (OU noise) | public datasets, lab testbed, customer data | L3, L4, L6 | open |
| A2 | The exogenous variation of the actual actuator state (not of the setpoint) is fast compared with confounders | experiment 0, identification design | experiments on lab testbed and customer data | L4, L6 | open |
| A3 | Ore hardness varies slowly (hours) relative to operator moves (30 min) and process dynamics (minutes) | mill circuit plant | customer data, literature | L6 | open |
| A4 | Operators change setpoints in steps at regular intervals as a function of observed ore properties | operator model | interviews, customer data | L6 | open |
| A5 | Actuator inner loops behave like a first-order lag with additive disturbance | mill circuit plant | lab testbed, customer data | L4, L6 | open |
| A6 | CAS/remote-setpoint handshake, tracking and bumpless transfer work the same way in the target DCS families | write gateway design, simulated loops | soft PLC, then vendor documentation and pilot | L5, L7 | open |
| A7 | PID algorithm forms and units (gain vs proportional band, time units) can be converted between vendors | PID tuning module (planned) | vendor documentation, soft PLC; see `docs/VENDOR_PID_FORMS.md`: Siemens verified from public manuals (2026-10-14), ABB structure verified, unit of TI/TD open | L5 | partly tested |
| A8 | Historian exports are CSV/Excel with a limited set of layouts and status strings | importers (planned) | messy-data corpus, customer exports | L2, L6 | open |
| A9 | Quality codes map to Good/Uncertain/Bad without loss of information needed by the algorithms | ADR 003 | OPC UA tests, customer data | L5, L6 | open |
| A10 | A heartbeat counter written by the suite is an acceptable watchdog for the target control systems | server design | soft PLC, vendor review | L5, L7 | open |
| A11 | Wood-Berry coefficients and BLT tuning are transcribed correctly | Wood-Berry plant | compare with the original paper | L1 | open |
| A12 | Ore-hardness-dependent gains are of the right order of magnitude | mill circuit table | literature, customer data | L6 | open |
| A13 | Customers accept an on-premises, read-only first deployment | product strategy | pilot conversations | L7 | open |
| A14 | A single time base (UTC) is available or can be reconstructed for all sources | ADR 003 | corpus, customer data | L2, L6 | open |

## Benefit estimate (C4)

- Model: the operator keeps the mean `margin_sigmas` standard deviations away from a limit. Cutting the standard deviation by the fraction `std_reduction` frees `margin_sigmas * std * std_reduction` of room, capped at today's gap to the limit; money is room times a user-given value per PV unit and hour.
- Not claimed: that the freed room can be used (needs a trial), that the process is stationary, or that the value per unit is constant. `std_reduction` is an assumption of the user, not an output of the monitoring code.

## Loop health score (C5)

- Model: health % = 100 x time in use x time not saturated x time not frozen x (0.4 + 0.6 x Harris index clamped to 0..1) x 0.7 if a sustained oscillation x 0.6 if stiction is suspected; a loop that is mostly in manual has no score ("not in use"). An uncomputable Harris index counts as 0.5.
- The weights (0.4 floor, 0.7, 0.6) are a first guess to make the ranking sensible, not a calibrated quantity; they live as named constants in `loops/src/crosscut_loops/overview.py` and must be tuned on real or benchmark data (stage 1, E2).
- Stiction (C2, revised 2026-10-11): the old periodicity test took the maximum autocorrelation at small lags (always near 1), so every noise-driven loop looked like a limit cycle. Now the signal must show a clear first autocorrelation repeat peak (>= 0.15) AND a zero-crossing cycle count consistent with that period (ratio <= 3.5). Measured on simulated data: 0 of 40 random-wander series flagged, 29 of 40 simulated stiction loops found (the rest never enter a limit cycle), 20 of 20 healthy oscillating loops cleared. Only a PV-based, simulated-valve validation exists: real stiction data is still needed (open). The overview additionally requires the oscillation detector to agree and no saturation finding.
- Loops come from an explicit `project.json` next to the dataset (`loops` array of the project schema: id, name, pv, sp, out, mode, optional delay_s, ultimate_period_s, amplitude_limit); without that file they are discovered by naming convention (PV tag `X` with `X_sp`, `X_out`, `X_mode`).
- Loop settings default to placeholders (dead time 30 s, natural period 600 s, amplitude limit 2 % of the range) unless the project file gives them per loop.
