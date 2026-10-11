# ADR 006: Simulators provide known causal truth, not believable physics

Status: accepted (2026-10-10)

The simulators (`crosscut-sim`) exist to test methods against ground truth: exact process gains (also as a function of
ore hardness), controlled disturbances, an operator model that confounds setpoints, deterministic seeds. They are
deliberately simplified and use illustrative coefficients. Consequence: results show whether a method can recover known
effects under stated conditions; they must not be presented as predictions for a real plant.
