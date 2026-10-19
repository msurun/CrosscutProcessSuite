# exp23: biased ACF with a peak gate, selection with the L tolerance (protocol frozen 2026-10-19, BEFORE any run)

Follow-up of exp21 (read its README first). exp21 showed that a peak gate removes the fast-noise false alarms of the
shipped detector A and adds about 30 points of short-record sensitivity, but its chosen candidate G (unbiased ACF)
lost 4.3 points on long records and was not shipped. The flaw was in my selection rule (S only). This round fixes the
rule and keeps the ACF biased. Everything is synthetic; a winner says nothing about plants.

## Signals

The exp20 generator (`experiments/exp20_acf_short_records/g20_signals.py`), unchanged, same cells.
Seeds: development 4000..4099 per cell, test 6000..6099 per cell (used once). Seeds 0..99, 2000..2099, 3000..3099
and 5000..5029 are spent and not used.

What is already known about the candidates (stated so the reader can judge the selection): on exp21's development
seeds candidate I below had F pass, S 79.2 %, L 84.7 % against A's 50.6 % / 86.2 %. J and M are new.

## Candidates (fixed now)

| Id | ACF | Band | Min crossings | Max lag | Peak gate |
| --- | --- | --- | --- | --- | --- |
| A (shipped) | biased | Bartlett, constant | 7 | n/2 | none |
| I | biased | Bartlett, constant | 5 | 3n/4 | 3 sigma |
| J | biased | Bartlett, constant | 5 | 3n/4 | 2.5 sigma |
| M | biased | Bartlett, constant | 5 | n/2 | 3 sigma |

## Targets (frozen)

- F, S, L defined as in exp20/exp21 (F hard: every negative cell <= 5 %, pooled <= 2 %).
- **Selection on development seeds:** among I, J, M, those that meet F AND have L no more than 2 points below A's L
  on the same seeds; the highest S wins, ties to the earlier letter. None eligible: nothing ships.
- **Ship rule on test seeds (once, winner and A):** F met, S >= A's S + 10 points, L >= A's L - 2 points.
- If it ships: the winner's constants become the `AcfConfig` defaults; the loop report says "inconclusive: too few
  cycles in the record" when the reason is "too few ACF zero crossings". Not a claim about real loops.
