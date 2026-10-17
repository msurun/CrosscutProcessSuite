# exp16 final run (single use), salt 2bb08f93e76a59b760f2d8ae4d1cc71b8b9543fa

## exp01 (test_valve counts of 20; exp01 has no setpoint forcing: unproven)

- sticking band 2% (low noise): shipped 0/20 [0%, 16%], C7a 0/20 [0%, 16%]
- sticking band 2% (full noise): shipped 1/20 [1%, 24%], C7a 1/20 [1%, 24%]
- sticking band 4% (low noise): shipped 20/20 [84%, 100%], C7a 20/20 [84%, 100%]
- sticking band 4% (full noise): shipped 2/20 [3%, 30%], C7a 1/20 [1%, 24%]
- sticking band 6% (low noise): shipped 20/20 [84%, 100%], C7a 20/20 [84%, 100%]
- sticking band 6% (full noise): shipped 6/20 [15%, 52%], C7a 1/20 [1%, 24%]
- sticking band 8% (low noise): shipped 20/20 [84%, 100%], C7a 20/20 [84%, 100%]
- sticking band 8% (full noise): shipped 13/20 [43%, 82%], C7a 9/20 [26%, 66%]
- nominal wander (low noise): shipped 0/20 [0%, 16%], C7a 0/20 [0%, 16%]
- nominal wander (full noise): shipped 0/20 [0%, 16%], C7a 0/20 [0%, 16%]
- aggressive tuning (low noise): shipped 0/20 [0%, 16%], C7a 0/20 [0%, 16%]
- aggressive tuning (full noise): shipped 0/20 [0%, 16%], C7a 0/20 [0%, 16%]
- sine forcing (low noise): shipped 0/20 [0%, 16%], C7a 0/20 [0%, 16%]
- sine forcing (full noise): shipped 0/20 [0%, 16%], C7a 0/20 [0%, 16%]
- square forcing (adversarial) (low noise): shipped 0/20 [0%, 16%], C7a 0/20 [0%, 16%]
- square forcing (adversarial) (full noise): shipped 0/20 [0%, 16%], C7a 0/20 [0%, 16%]
- C7a healthy cells <= 2/20: met

## Synthetic families (final seeds)

### shipped
- G1: AUC 0.749; ranked-only 0.814 (coverage 76%); sens@10%FP 53%; pAUC(FPR<=0.1) 0.21; flagged: stick 68%, healthy 31%
- G2: AUC 0.661; ranked-only 0.742 (coverage 77%); sens@10%FP 34%; pAUC(FPR<=0.1) 0.23; flagged: stick 45%, healthy 26%
- G3: AUC 0.522; ranked-only 0.726 (coverage 46%); sens@10%FP 24%; pAUC(FPR<=0.1) 0.11; flagged: stick 31%, healthy 22%
- worst family AUC 0.522
### C7a
- G1: AUC 0.915; ranked-only 0.933 (coverage 98%); sens@10%FP 80%; pAUC(FPR<=0.1) 0.57; flagged: stick 85%, healthy 14%
- G2: AUC 0.898; ranked-only 0.908 (coverage 99%); sens@10%FP 73%; pAUC(FPR<=0.1) 0.48; flagged: stick 76%, healthy 12%
- G3: AUC 0.714; ranked-only 0.851 (coverage 57%); sens@10%FP 55%; pAUC(FPR<=0.1) 0.38; flagged: stick 64%, healthy 28%
- worst family AUC 0.714

## T7 noise-only (100 records, flagged)

- shipped: 1/100
- C7a: 1/100

## SACAC veto (>= 5/6 sticking flagged, <= 2 non-sticking flagged)

- shipped: sticking flagged 6/6, non-sticking flagged 1, ranked 3/11
- C7a: sticking flagged 6/6, non-sticking flagged 3, ranked 5/11

## ISDB counted set (independent, high confidence; veto only, n is small)

- shipped stick: flagged 6/13 [23%, 71%], ranked 8/13
- shipped other: flagged 1/14 [1%, 31%], ranked 7/14
- shipped AUC (abstain=0) 0.670
- C7a stick: flagged 5/13 [18%, 64%], ranked 6/13
- C7a other: flagged 10/14 [45%, 88%], ranked 12/14
- C7a AUC (abstain=0) 0.324

## Acceptance: worst-family gain +0.192, bootstrap +0.192 [+0.165, +0.218]

- worst-family AUC gain >= 0.03: met
- paired bootstrap interval excludes 0: met
- exp01 healthy cells <= 2/20: met
- T7 noise-only <= 5 %: met
- ISDB sticking flagged >= shipped - 1: met
- ISDB other flagged <= shipped + 1: MISSED
- SHIP C7a: NO