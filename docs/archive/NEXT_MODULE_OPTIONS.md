# Next module: options and a recommendation (draft for discussion, 2026-10-19)

Written after module 1 (loop monitoring and tuning) was closed on what simulation can prove. Not a plan: the owner
decides. The snapshot in `docs/IMPLEMENTATION_LOG.md` lists the modules the suite aims at: soft sensors, anomaly
detection, MPC, fuzzy/expert rules, ML-based operating-range recommendation, optimisation.

## How I would judge a candidate

1. **Can it be validated without plant data?** Module 1 taught that synthetic success says little about plants, and
   that real public data (SACAC, ISDB) can be used once or twice before it stops being independent. A module whose
   evidence is only its own simulator needs a stated path to real evidence.
2. **Read-only or writing?** The write path (gateway, V4/V5/V7 in the plan) is a separate safety project. Until its
   test suite passes, everything stays advisory.
3. **Does it fit ADR 009?** Rules, models and parameters must be declarative files; no user code in the process.
4. **Does it reuse what exists?** Findings, KPIs, simulators, artifact schemas, the frozen-protocol discipline.

## Candidates

| Candidate | State today | Read-only? | Evidence without plant data | Main risk |
| --- | --- | --- | --- | --- |
| Fuzzy / expert supervisor | model, inference, versions, backtest, rule matrix and an editor design exist (`fuzzy/`, `docs/design/fuzzy-studio.md`); schema `fuzzy.schema.json` | yes (advice) | closed-loop simulation with the mill circuit; backtest on synthetic history | easy to build, hard to show it beats a simple rule |
| Soft sensors | not started | yes | synthetic plants with a hidden quality variable; honest only with a plant-like generator written by another model | drift, data quality, no ground truth in public sets |
| Anomaly detection | not started | yes | injected faults in the simulator (the sim already has fault injection) | false-alarm rate is the whole product; needs real quiet data |
| ML operating-range recommendation | DML planned in PROVENANCE | yes | causal estimates are only checkable where the generator's truth is known | confounding in real historian data |
| MPC | runtime core and write gateway planned (ADR 001) | **no** | closed-loop simulation is solid evidence for the controller, not for the plant | needs the write-path safety work first |

## Recommendation

Next: **the fuzzy / expert supervisor as an advisory layer, wired to module 1's findings and tested on the mill
circuit simulator**, because it is the closest to done, read-only, ADR 009-clean (rules are JSON) and gives a chance
to test the "configuration is data" boundary on a real user-supplied artefact. In parallel, **do not start MPC** until
a short design note defines the write gateway and its test suite; MPC without it would be a controller nobody may
connect.

Two things would change this: (a) the owner has access to real, shareable historian data (then soft sensors or
anomaly detection become the stronger choice, with real evidence from day one); (b) a customer asks for MPC, in which
case the write-path design comes first.

## Questions for the owner

1. Is there any real data (even a few weeks of one circuit) that may be used for development and, in anonymised
   form, for validation? That decides soft sensors / anomaly detection.
2. How soon does module 1 need real evidence (one valve stroke test, the blind worklist review) before module 2 gets
   attention?
3. Does the first user of module 2 need a visible UI (frontend, needs Node.js) or a report/CLI?
