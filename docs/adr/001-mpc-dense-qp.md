# ADR 001 addendum: bounded dense MPC QP implementation (#185)

Status: implementation decision, 2026-11-27; scoped to Phase 7.4 and the explicit
dependency-free solver requirement of issue #185.

The Python reference continues using OSQP. The C++ core uses an original dense ADMM
implementation rather than adding OSQP packaging to both platform builds. This scoped
choice supersedes the design note's C++ OSQP choice for this implementation only.

For `min 0.5*x'P*x+q'x`, `l <= A*x <= u`, split `z=A*x`. Each iteration solves
`(P + sigma*I + rho*A'A)*x_new = sigma*x_old - q + A'*(rho*z-y)` with a cached dense
Cholesky factor, over-relaxes with alpha=1.6, projects onto `[l,u]`, then updates the
unscaled dual `y`. The proximal term sigma=1e-6 leaves the limiting objective unchanged.
Ten diagonal Ruiz equilibration passes and a scalar objective normalization reduce
engineering-unit conditioning differences. Decision scaling is undone before acceptance.

Each attempt starts at zero, has at most 10000 iterations and checks primal feasibility
and dual stationarity every 25 iterations with fixed absolute/relative tolerance 1e-7.
Rho starts at 0.1 and adapts deterministically every 50 iterations from residual ratios,
bounded to [1e-6,1e6]. There is no random order, warm start or elapsed-time stopping rule.
A dual difference ray certifies primal infeasibility (`A'v` approximately zero and
`u'v_positive+l'v_negative < 0`); reaching the cap is a numerical failure, not proof
that relaxing another CV is justified. Accepted decisions must independently satisfy
the original engineering-unit inequalities within 2e-5.

Both target and dynamic costs, priority weights, step-response convolution, input delays,
CV bias, narrowing funnels, cumulative MV bounds, move/rate bounds and priority groups
follow `crosscut_mpc.planning` and `crosscut_mpc.qp`. Fixed-zero slack columns are eliminated
for the first hard attempt; subsequent attempts add only enabled nonnegative symmetric
CV slacks, with squared penalty `1000*priority_weight`. This is algebraically equivalent
to fixing the other slack columns to zero. MV constraints never receive slack.

`mpc_cycle` uses plain nested dictionaries and explicit model/history state, including
previous model state for actual-readback reconciliation. It holds on initialisation,
holds on solver failure and latches shed after three failures. It proposes moves only.

Parity tolerances and the timing budget are defined in `core/tests/test_mpc_parity.py`.
Floating-point iteration counts and failure reason wording need not match OSQP; public
cycle status codes must match tested cases. There is no plant validation or universal
hard-real-time claim: dense cost grows with horizons, CVs and enabled slack rows. The
timing test covers the 60-second Wood-Berry cycle with margin below its 6-second budget.
