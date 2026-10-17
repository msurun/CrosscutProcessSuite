# exp15 final run (single use)

## exp01 mill simulation, final seeds 21-40 (test_valve counts)

| class | shipped | C4a |
|---|---|---|
| sticking band 2% (low noise) | 0/20 [0%, 16%] | 0/20 [0%, 16%] |
| sticking band 2% (full noise) | 0/20 [0%, 16%] | 0/20 [0%, 16%] |
| sticking band 4% (low noise) | 20/20 [84%, 100%] | 20/20 [84%, 100%] |
| sticking band 4% (full noise) | 0/20 [0%, 16%] | 3/20 [5%, 36%] |
| sticking band 6% (low noise) | 20/20 [84%, 100%] | 20/20 [84%, 100%] |
| sticking band 6% (full noise) | 0/20 [0%, 16%] | 2/20 [3%, 30%] |
| sticking band 8% (low noise) | 20/20 [84%, 100%] | 20/20 [84%, 100%] |
| sticking band 8% (full noise) | 2/20 [3%, 30%] | 10/20 [30%, 70%] |
| nominal wander (low noise) | 0/20 [0%, 16%] | 0/20 [0%, 16%] |
| nominal wander (full noise) | 0/20 [0%, 16%] | 0/20 [0%, 16%] |
| aggressive tuning (low noise) | 0/20 [0%, 16%] | 0/20 [0%, 16%] |
| aggressive tuning (full noise) | 0/20 [0%, 16%] | 2/20 [3%, 30%] |
| sine forcing (low noise) | 0/20 [0%, 16%] | 0/20 [0%, 16%] |
| sine forcing (full noise) | 0/20 [0%, 16%] | 0/20 [0%, 16%] |
| square forcing (adversarial) (low noise) | 0/20 [0%, 16%] | 0/20 [0%, 16%] |
| square forcing (adversarial) (full noise) | 0/20 [0%, 16%] | 0/20 [0%, 16%] |

- C4a T1 band 4 % low noise >= 18/20: met
- C4a T1 band 6 % low noise >= 18/20: met
- C4a T1 band 8 % low noise >= 18/20: met
- C4a T2 band 8 % full noise >= 14/20: MISSED
- C4a T3 nominal wander (low noise) <= 2/20: met
- C4a T3 nominal wander (full noise) <= 2/20: met
- C4a T3 aggressive tuning (low noise) <= 2/20: met
- C4a T3 aggressive tuning (full noise) <= 2/20: met
- C4a T3 sine forcing (low noise) <= 2/20: met
- C4a T3 sine forcing (full noise) <= 2/20: met

## shipped: synthetic final sets

- s14: AUC abstain=0 overall 0.771 (ranked only 0.841); F 0.833; L 0.709; half-cycle < 18: 0.562 (n=281)
  random-score sanity AUC 0.50
  flagged sine noise mid: 68/200 [28%, 41%]
  flagged square noise mid: 104/200 [45%, 59%]
  flagged tuning noise mid: 4/200 [1%, 5%]
  stiction flagged 137/200 [62%, 75%]
- shift: AUC abstain=0 overall 0.655 (ranked only 0.725); F 0.730; L 0.610; half-cycle < 18: 0.532 (n=850)
  random-score sanity AUC 0.50
  flagged sine noise high: 87/200 [37%, 50%]
  flagged sine noise low: 21/200 [7%, 16%]
  flagged sine noise mid: 39/200 [15%, 26%]
  flagged square noise high: 100/200 [43%, 57%]
  flagged square noise low: 91/200 [39%, 52%]
  flagged square noise mid: 91/200 [39%, 52%]
  flagged tuning noise high: 26/200 [9%, 18%]
  flagged tuning noise low: 7/200 [2%, 7%]
  flagged tuning noise mid: 27/200 [9%, 19%]
  stiction flagged 267/600 [41%, 48%]
## C4a: synthetic final sets

- s14: AUC abstain=0 overall 0.766 (ranked only 0.846); F 0.843; L 0.690; half-cycle < 18: 0.538 (n=281)
  random-score sanity AUC 0.50
  flagged sine noise mid: 69/200 [28%, 41%]
  flagged square noise mid: 104/200 [45%, 59%]
  flagged tuning noise mid: 16/200 [5%, 13%]
  stiction flagged 141/200 [64%, 76%]
- shift: AUC abstain=0 overall 0.648 (ranked only 0.740); F 0.734; L 0.590; half-cycle < 18: 0.533 (n=850)
  random-score sanity AUC 0.50
  flagged sine noise high: 86/200 [36%, 50%]
  flagged sine noise low: 22/200 [7%, 16%]
  flagged sine noise mid: 42/200 [16%, 27%]
  flagged square noise high: 101/200 [44%, 57%]
  flagged square noise low: 90/200 [38%, 52%]
  flagged square noise mid: 92/200 [39%, 53%]
  flagged tuning noise high: 26/200 [9%, 18%]
  flagged tuning noise low: 7/200 [2%, 7%]
  flagged tuning noise mid: 28/200 [10%, 19%]
  stiction flagged 262/600 [40%, 48%]

## T7 noise-only records (100)

- shipped: ranked 0/100, flagged 0/100 -> met
- C4a: ranked 2/100, flagged 0/100 -> met

## SACAC veto (T5: >= 5/6 flagged, <= 2 non-sticking flagged)

- SACAC shipped: sticking flagged 6/6, non-sticking flagged 0, non-sticking ranked 2/11
- SACAC C4a: sticking flagged 6/6, non-sticking flagged 1, non-sticking ranked 3/11
