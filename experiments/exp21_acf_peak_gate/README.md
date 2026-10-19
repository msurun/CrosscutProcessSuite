# exp21: ACF detector with a lag-dependent band and a peak gate (protocol frozen 2026-10-19, BEFORE any run)

Question: can a variant of the ACF regularity detector (`crosscut_loops.oscillation_acf`) remove the false alarms
that exp20 found on fast noise (shipped detector A: 11 % on AR(1) phi 0.5, n = 3000) while detecting records with
5-10 cycles, which A misses entirely? Everything here is synthetic. A winner supports "works on the synthetic
suite", nothing about plants; SACAC and ISDB are not used (seen twice).

## Signals

The exp20 generator `experiments/exp20_acf_short_records/g20_signals.py` (spec `G20_SPEC.md`, written by a different
model than the detector), unchanged, imported from there; the same positive and negative cells as exp20.
Seeds: development 2000..2099 per cell; test 3000..3099 per cell, used once, after the choice. exp20's dev seeds
0..99 are spent; its test seeds 1000..1099 are left unused on purpose.

Disclosure: before this protocol, design exploration ran on seeds 5000..5029 (30 per cell, scratch script, not
committed). It showed that bands which grow with a cumulative Bartlett sum remove all sensitivity below 20 cycles, that
an unbiased ACF with a band scaled by 1/(n - k) recovers short records but keeps false alarms (up to 23 % on AR(0.5)),
and that a peak gate removed nearly all false alarms (worst 3 % on AR(0.9) n=3000). Those seeds are not reused.

## Why the false alarms happen (diagnosis from exp20, design seeds)

With fast-decorrelating noise the 95 % band is crossed at about 5 % of all lags by chance. Over n/2 or 3n/4 lags
that gives tens of isolated exceedances of random sign; the hysteresis rule turns sign changes between them into
"zero crossings" with roughly exponential spacing, and r > 1 then happens by chance in some records. A real cycle
instead produces wide ACF lobes whose peaks stand far outside the band. The peak gate tests exactly that.

## Candidates (defined now; none may be added after the development run)

All keep the Thornhill regularity r = mean(Tp) / (3 std(Tp)) > 1 and the hysteresis crossing rule, at most 11
crossings.

| Id | ACF scaling | Noise band at lag k (sigma_k; band = 1.96 sigma_k) | Min crossings | Max lag | Peak gate |
| --- | --- | --- | --- | --- | --- |
| A (shipped) | biased | Bartlett, q = first zero crossing, constant | 7 | n/2 | none |
| F | unbiased (divide lag-k sum by n - k) | sqrt((1 + 2 sum_{j<q} r_j^2) / (n - k)) | 5 | 3n/4 | none |
| G | unbiased | as F | 5 | 3n/4 | 3 sigma_k |
| H | unbiased | as F | 5 | 3n/4 | 4 sigma_k |
| I | biased | as A (constant) | 5 | 3n/4 | 3 sigma_k |

Peak gate: after r > 1, take the largest ACF value between the second and the third crossing (the first positive
lobe after lag 0, centred near one period). The record is regular only if that value exceeds peak_z * sigma_k at
its lag. Reason when it fails: "weak ACF peak".

The 1/(n - k) band follows from the unbiased estimator: the lag-k sum has n - k terms, so its sampling variance
grows as 1/(n - k) instead of 1/n (Bartlett's formula with the effective sample count).

## Targets (frozen)

- **F (false alarms), hard, unchanged from exp20:** detected share <= 5 % in EVERY negative cell, and <= 2 % pooled.
- **S (sensitivity):** pooled detection over positive cells with c >= 5 and SNR >= 1.
- **L (long records):** detection in positive cells with c = 20 and SNR >= 1.
- **Selection on development seeds:** among candidates other than A that meet F, the one with the highest S;
  ties go to the earlier letter. If none meets F, nothing ships.
- **Ship rule, on test seeds, once:** run the chosen candidate AND A on the test seeds. Ship if the candidate
  meets F, its S is at least 10 percentage points above A's S, and its L is no more than 2 points below A's L.
  Otherwise A stays and the miss is reported. Constants are not edited after the development run.
- Changed from exp20, and why: exp20 asked for absolute S >= 90 % and L >= 98 %. A itself reaches 51 % and 86 %
  on that suite, because the suite contains SNR-1 sines in AR(0.9) noise that no candidate detects well. The question
  now is whether a candidate is safer and better than what ships. The absolute goals are still reported as
  "goal met / not met".
- Reported, no target: per-cell shares, reason counts, c in {3, 4}, SNR 0.5.

## Afterwards (if a candidate ships)

The winner's constants become the `AcfConfig` defaults in the package; the loop report adds an "inconclusive: too few
cycles in the record" note when the reason is "too few ACF zero crossings". That note is a reporting change, not a detection change.

## RESULT (2026-10-19; dev 2000..2099 `results21_dev.md`, test 3000..3099 `results21_test.md`)

Development: G, H and I met F; G had the highest S and was chosen. Test (once, G vs A):

| | F (worst cell / pooled) | S (c >= 5, SNR >= 1) | L (c = 20, SNR >= 1) |
| --- | --- | --- | --- |
| G | PASS (3.0 % / 0.5 %) | 82.5 % | 80.6 % |
| A (shipped) | would fail (AR(0.5) n=3000: 12 %) | 50.1 % | 84.9 % |

**Ship: no.** G loses 4.3 points of L against A, the rule allows 2. A stays in the package, unchanged.

What was learned:
- The peak gate removes the fast-noise false alarms of A (worst cell 12 % -> 1-3 %) and the short-record misses
  (S +32 points). It is the first variant that is both safer and more sensitive than A.
- G's L loss sits in n = 300, c = 20 (period 15 samples): 99 -> 91 % even for a clean sine; F (same ACF, no gate)
  loses the same, so the cause is the unbiased ACF / 3n/4 lag range, not the gate.
- Protocol flaw, mine: the selection rule ranked by S alone and did not apply the L tolerance on the development
  seeds. Candidate I (biased ACF, constant Bartlett band, peak gate 3) had F pass, S 79.2 % and L 84.7 % on dev and
  would have met the ship rule. Choosing I now from these results would be selection after the test; a new round
  (exp23) with fresh seeds and the L tolerance inside the selection rule is the honest route.
