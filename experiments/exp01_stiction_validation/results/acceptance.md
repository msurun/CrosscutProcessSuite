# Stiction detector acceptance report

Seeds 1..10: development, seeds 11..20: held-out. First 2 h dropped as settling time.

## Positives (valve sticks)

| class | noise | seed set | n | stiction | no_stiction | inconclusive | detection rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sticking band 2% (low noise) | low | development | 10 | 0 | 0 | 10 | 0.0% |
| sticking band 2% (full noise) | full | development | 10 | 0 | 0 | 10 | 0.0% |
| sticking band 4% (low noise) | low | development | 10 | 10 | 0 | 0 | 100.0% |
| sticking band 4% (full noise) | full | development | 10 | 0 | 0 | 10 | 0.0% |
| sticking band 6% (low noise) | low | development | 10 | 10 | 0 | 0 | 100.0% |
| sticking band 6% (full noise) | full | development | 10 | 1 | 0 | 9 | 10.0% |
| sticking band 8% (low noise) | low | development | 10 | 10 | 0 | 0 | 100.0% |
| sticking band 8% (full noise) | full | development | 10 | 6 | 0 | 4 | 60.0% |
| sticking band 2% (low noise) | low | held-out | 10 | 0 | 0 | 10 | 0.0% |
| sticking band 2% (full noise) | full | held-out | 10 | 0 | 0 | 10 | 0.0% |
| sticking band 4% (low noise) | low | held-out | 10 | 10 | 0 | 0 | 100.0% |
| sticking band 4% (full noise) | full | held-out | 10 | 0 | 0 | 10 | 0.0% |
| sticking band 6% (low noise) | low | held-out | 10 | 10 | 0 | 0 | 100.0% |
| sticking band 6% (full noise) | full | held-out | 10 | 2 | 0 | 8 | 20.0% |
| sticking band 8% (low noise) | low | held-out | 10 | 10 | 0 | 0 | 100.0% |
| sticking band 8% (full noise) | full | held-out | 10 | 8 | 0 | 2 | 80.0% |

## Negatives (healthy valve)

| class | noise | seed set | n | stiction | no_stiction | inconclusive | false-alarm rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| nominal wander (low noise) | low | development | 10 | 0 | 0 | 10 | 0.0% (95% UB 27.8%) |
| nominal wander (full noise) | full | development | 10 | 0 | 0 | 10 | 0.0% (95% UB 27.8%) |
| aggressive tuning (low noise) | low | development | 10 | 0 | 0 | 10 | 0.0% (95% UB 27.8%) |
| aggressive tuning (full noise) | full | development | 10 | 0 | 0 | 10 | 0.0% (95% UB 27.8%) |
| sine forcing (low noise) | low | development | 10 | 0 | 10 | 0 | 0.0% (95% UB 27.8%) |
| sine forcing (full noise) | full | development | 10 | 0 | 8 | 2 | 0.0% (95% UB 27.8%) |
| square forcing (adversarial) (low noise) | low | development | 10 | 10 | 0 | 0 | 100.0% (95% UB 100.0%) |
| square forcing (adversarial) (full noise) | full | development | 10 | 10 | 0 | 0 | 100.0% (95% UB 100.0%) |
| nominal wander (low noise) | low | held-out | 10 | 0 | 0 | 10 | 0.0% (95% UB 27.8%) |
| nominal wander (full noise) | full | held-out | 10 | 0 | 0 | 10 | 0.0% (95% UB 27.8%) |
| aggressive tuning (low noise) | low | held-out | 10 | 0 | 0 | 10 | 0.0% (95% UB 27.8%) |
| aggressive tuning (full noise) | full | held-out | 10 | 0 | 0 | 10 | 0.0% (95% UB 27.8%) |
| sine forcing (low noise) | low | held-out | 10 | 0 | 10 | 0 | 0.0% (95% UB 27.8%) |
| sine forcing (full noise) | full | held-out | 10 | 0 | 10 | 0 | 0.0% (95% UB 27.8%) |
| square forcing (adversarial) (low noise) | low | held-out | 10 | 10 | 0 | 0 | 100.0% (95% UB 100.0%) |
| square forcing (adversarial) (full noise) | full | held-out | 10 | 10 | 0 | 0 | 100.0% (95% UB 100.0%) |
