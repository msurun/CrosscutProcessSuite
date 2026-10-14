# Overshoot Diagnosis: mill_feed Retuned Loop (exp03)

Overshoot and IAE of the same mill_feed setpoint step across four variants and seeds 1..5. Blocked rows mean the fit guard rejected the step window.

## Variants
- **A_baseline**: mill_feed SIMC from noisy step test, other loops detuned (exp03)
- **B_interaction**: all three loops get their own SIMC gains from noisy step tests
- **C_model_error**: mill_feed SIMC from a noise-free step test, other loops detuned
- **D_robustness**: variant A with robustness 1.0 instead of 0.5

## Results by Variant and Seed
| Variant | Seed | Overshoot | IAE |
|---|---|---|---|
| A_baseline | 1 | 8.9% | 7790.5 |
| A_baseline | 2 | 9.4% | 7812.9 |
| A_baseline | 3 | 11.7% | 8190.8 |
| A_baseline | 4 | 9.9% | 7975.0 |
| A_baseline | 5 | 9.3% | 7641.6 |
| B_interaction | 1 | 8.9% | 7790.5 |
| B_interaction | 2 | 9.4% | 7812.9 |
| B_interaction | 3 | 11.7% | 8190.8 |
| B_interaction | 4 | 9.9% | 7975.0 |
| B_interaction | 5 | 9.3% | 7641.6 |
| C_model_error | 1 | 23.7% | 11195.5 |
| C_model_error | 2 | 13.7% | 9158.7 |
| C_model_error | 3 | 13.9% | 9147.1 |
| C_model_error | 4 | 13.6% | 9214.5 |
| C_model_error | 5 | 40.2% | 12328.3 |
| D_robustness | 1 | 13.3% | 8545.9 |
| D_robustness | 2 | 14.8% | 8580.4 |
| D_robustness | 3 | 18.0% | 9102.1 |
| D_robustness | 4 | 14.4% | 8715.6 |
| D_robustness | 5 | 15.1% | 8285.1 |

## Median per Variant
| Variant | Median Overshoot | Median IAE |
|---|---|---|
| A_baseline | 9.4% | 7812.9 |
| B_interaction | 9.4% | 7812.9 |
| C_model_error | 13.9% | 9214.5 |
| D_robustness | 14.8% | 8580.4 |

## Reading
Variants A and B are identical: loop mill_feed is not coupled to the other loops' gains in this plant, so interaction is excluded. The earlier raw overshoot of 58-67 % was noise: with the 60 s smoothed metric it is the loop's real overshoot (median 9.4 % for A, see the table). Variants C (noise-free identification, median 13.9 %) and D (robustness 1.0, median 14.8 %) are for comparison of the model-error and robustness effects.
