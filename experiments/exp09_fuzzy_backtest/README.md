# exp09: backtest of the mill feed supervisor against operator moves

Targets are FROZEN before the first run (2026-10-15). A miss is logged, thresholds are not moved.

## Question
Does the advisory rule base `fuzzy/examples/mill_feed_supervisor.json` point the same way as the
simulated operator when the operator changes the mill feed setpoint (`sim.mc.mill_feed_sp`)?

## Setup
- Scenario `observational` (operator on) of the mill-circuit simulator, 48 h, seeds 1-10.
- The simulated operator acts every 1800 s and sets the feed SP from a noisy belief about the ore
  hardness (`sim.../mill_circuit.py::_operator_act`). The rule base sees only mill power and P80,
  which move with the hardness. So the test is: can power and P80 recover what the operator
  inferred from hardness.
- Operator move = change of the SP at an action instant. Fuzzy value for a move = mean of the fuzzy
  `feed_change` over the 900 s BEFORE the move (what the supervisor would have advised).
- Dead band: moves with |delta SP| <= 2 t/h are ignored (inside the "hold" zone of the output).
- Split by time: first half of each run = tuning part, second half = check part. Rules may be
  edited only on the tuning part.

## Targets (check part, median over seeds)
| id | metric | target |
|----|--------|--------|
| B1 | sign agreement on moves above the dead band | >= 0.65 |
| B2 | Pearson correlation fuzzy value vs delta SP | >= 0.30 |
| B3 | sign agreement drop, tuning to check part | <= 0.10 |
| B4 | sign agreement minus the share of the majority sign | >= 0.10 |
| B5 | share of operator moves for which the fuzzy value is silent (|value| <= 1 t/h) | <= 0.30 |

B4 guards against a rule base that always says "decrease" on a record where most moves are decreases.

## What this does not show
The operator is a simulation written by us, with a hardness-based policy that the rule base
approximates by design. Agreement here shows the pipeline works; it does NOT show agreement with a
real operator. That needs a plant record with SP and OUT (HANDOFF step 5).

## Result (first and only run, 2026-10-15; table in results/results.md)
| id | median over 10 seeds | target | met |
|----|----------------------|--------|-----|
| B1 | 0.805 | >= 0.65 | yes |
| B2 | 0.606 | >= 0.30 | yes |
| B3 | -0.099 (check part is better) | <= 0.10 | yes |
| B4 | 0.294 | >= 0.10 | yes |
| B5 | 0.428 | <= 0.30 | **NO** |

Reading: when the rule base speaks it points the right way (B1, B4), but in 43 % of the operator
moves it said nothing (|advice| <= 1 t/h). Most likely cause: small hardness shifts move the
operator by a few t/h while power and P80 stay inside the "normal"/"on_target" terms of the example
rule base. B5 stays a miss; the rule base was NOT edited (no tuning round was done, so B3 only
compares two halves of an untouched rule base and says nothing about overfitting yet).
Not verified: which moves are silent (size, sign) and whether narrower "normal" terms would fix it.
