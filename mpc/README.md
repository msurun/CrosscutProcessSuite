# Python MPC reference (Phase 7.2a)

`crosscut_mpc` is a numerical reference, with no runtime or gateway writes. Inputs
and results use deviations from one common operating point in signal engineering
units. Time constants, delays and cycle time use seconds. Matrix rows are CVs;
columns are MVs followed by optional measured DVs. Supply the intersection of
engineering and operator MV limits as `Limits.mv_lower` and `mv_upper`.

Construct `FopdtModel`, `Limits`, `Settings`, and `Controller`. Call
`initialise(controller, CycleInputs(...))`, then repeatedly call
`result, state = cycle(controller, state, inputs)`. Supply measured CVs and actual
MV read-back each cycle, including when the previous proposal was refused. The
first cycle holds the current MVs. `result.moves` contains proposed absolute MV
deviations; `move_plan` contains future MV increments. Only apply the first move.
`predicted_cvs` contains samples 1 through Np. Result fields are plain Python data;
state carries numerical model arrays separately. Persist the returned state only
for the next numerical cycle; restart by initialising from fresh measurements.

The target QP minimises weighted squared distance to the operator target with one
nonnegative symmetric CV slack. The dynamic QP tracks its rate-limited result,
penalises moves, and intersects CV limits with linearly narrowing funnels. Smaller
priority numbers mean higher priority. First all CV slacks are fixed to zero;
then priority groups are enabled from lowest priority upward until feasible.
Relaxed rows retain a squared slack penalty. This is ordered constraint relaxation,
with weighted tracking within a feasible group, rather than lexicographic tracking.
Actuator bounds, move maxima and rates remain hard. A failed solve holds the MVs;
three consecutive failures latch `shed` until explicit reinitialisation. A successful
relaxed solve resets the failure count. Numerical failure also holds safely.

OSQP uses fixed tolerances and iteration cap, fresh initialisation, stable ordering,
and penalty updates every 50 iterations (no timing-based adaptation). Moves,
predictions, statuses and iteration counts are reproducible for identical inputs
on the same numerical stack. Reported solve time is telemetry and varies.
Diagnostics identify active MV/CV operator limits by variable and horizon sample;
relaxed CV indices cover either layer. Limits are soft on CVs, including funnels,
so a relaxed solution can violate a reported CV bound.

Run `python -m pytest mpc/tests sim/tests` with this worktree's `*/src` on
`PYTHONPATH`. These are synthetic L1 checks, including the independent Wood-Berry
simulator in manual actuator mode. C++ parity, artefact loading, live quality/mode
handling and runtime host integration belong to later stages; no plant claim.
