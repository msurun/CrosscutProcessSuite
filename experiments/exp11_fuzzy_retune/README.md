# exp11: narrowed mill feed supervisor (v2) on fresh seeds

Targets are FROZEN before the first run (2026-10-19). A miss is logged, thresholds are not moved.

## Why
exp09 met B1-B4 but missed B5 (43 % silent). A diagnosis on the tuning half of seeds 1-10 showed the silent
moves sit at power 3000 +- 27 kW and P80 150 +- 2 um, the centre of the `normal` / `on_target` terms, while
the operator moves the feed by 4.8 t/h on average. The terms were wider than the real spread.

## Tuning (tuning half of seeds 1-10 only, 4 candidates tried: orig, A, A+rules, B)
`fuzzy/examples/mill_feed_supervisor_v2.json` = candidate "A+rules": narrower `normal` / `on_target` terms and
one added rule (low power + fine P80 -> increase_large). On the tuning half: B1 0.70, B2 0.51, B4 0.14, B5 0.11
(orig: 0.75 / 0.52 / 0.19 / 0.42). Candidate B had B5 0.06 but B1 0.70 and B2 0.50, so it was not better. The
tuning half of seeds 1-10 is spent; the check below uses NEW seeds 11-20, both halves of each run.

## Targets (seeds 11-20, check half, median over seeds, v2 rule base)
| id | metric | target |
|----|--------|--------|
| C1 | sign agreement | >= 0.65 |
| C2 | Pearson correlation | >= 0.30 |
| C3 | sign agreement drop, tuning half to check half | <= 0.10 |
| C4 | sign agreement minus majority share | >= 0.10 |
| C5 | silent share | <= 0.30 |
The original rule base is run on the same seeds as a reference (no target).

## What this does not show
Same simulated operator as exp09 (written by us); the terms were fitted to this simulator's spread. This shows
the retune generalises across seeds, not that it fits a real plant or a real operator.

## Result (first and only run, 2026-10-19; table in results/results.md)
| id | v2 | original (same seeds) | target | met |
|----|----|----|----|----|
| C1 | 0.724 | 0.772 | >= 0.65 | yes |
| C2 | 0.632 | 0.617 | >= 0.30 | yes |
| C3 | -0.028 | -0.078 | <= 0.10 | yes |
| C4 | 0.202 | 0.229 | >= 0.10 | yes |
| C5 | 0.085 | 0.382 | <= 0.30 | yes |

Reading: the retune removes the silent moves (38 % -> 8.5 %) at a cost of about 5 points of sign agreement;
correlation is unchanged. All targets met on seeds not used for tuning. Limit: same simulated operator, terms
fitted to this simulator's spread (see "What this does not show"). Next evidence needed: a real record with SP/OUT.
