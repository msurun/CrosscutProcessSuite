# Screen sketches: Data Studio, trend viewer, loop views

Status: draft for owner review (2026-10-11). Covers tasks D1 (sketches), D2 (trend viewer), D3 (loop views).
These are original layouts. References below are sources of ideas only; no third-party screens or assets are copied.
Claims marked (unverified) come from search snippets and must be checked against the primary source before they
become a requirement.

## Design principles

1. **Calm by default.** Neutral grey base; colour only for abnormal states and for data series (ISA-101 / high-performance
   HMI idea, unverified against the standard text).
2. **Never colour alone.** Every status has a shape and a word: `● OK`, `▲ Warning`, `■ Problem`, `○ Not in use`.
3. **Answer first, detail on demand.** Overview (which loops need attention) -> loop detail (why) -> evidence (the time
   window and the numbers). Each step is one click; breadcrumbs always show the way back.
4. **Show system status.** Every screen shows dataset, time range, data freshness and progress of long jobs.
5. **Findings link to evidence.** A finding such as "stiction suspected" opens the trend zoomed to the window that
   produced it.
6. **Plain language first, numbers second.** "Loop is saturated 31 % of the time" with the metric in a tooltip.
7. **Read-only until stage 3.** No screen in stage 1 writes to a plant; the header shows a permanent `READ-ONLY` badge.
8. **Colour-blind safe.** Series use the Okabe-Ito palette (`#0072B2 #D55E00 #009E73 #E69F00 #56B4E9 #CC79A7 #F0E442`);
   status uses shape + text + a muted amber/red, never red/green alone.

## Navigation map

```
Data Studio (datasets) -> Trend viewer (any tags)
                      \-> Loop overview -> Loop detail -> Tuning report -> Benefit report
```

Left rail (icons + labels): Datasets, Trends, Loops, Reports. Top bar: dataset name, time range, `READ-ONLY`.

## S1. Datasets (entry screen)

```
+--------------------------------------------------------------------------------+
| Crosscut            Datasets | Trends | Loops | Reports        READ-ONLY        |
+--------------------------------------------------------------------------------+
| Datasets                                         [ + Import CSV / SQL / OPC UA ]|
| [ search...            ]                                                        |
| Name                 Source        Tags  Period                 Quality         |
| mill_nominal_48h     simulator     21    10-01 00:00 - 10-03    ● 99.8 % good   |
| export_messy.csv     CSV           14    09-20 - 09-27          ▲ 3 % bad       |
| historian_week_41    SQL           212   10-05 - 10-11          ● 99.1 % good   |
+--------------------------------------------------------------------------------+
| Selected: export_messy.csv         [ Open trends ]  [ Analyse loops ]           |
| Import notes: 2 duplicate timestamps removed, decimal comma detected, tz = local |
+--------------------------------------------------------------------------------+
```

Import is a three-step wizard (source, preview with detected format, confirm) so that a wrong guess is visible before data
is loaded. The quality column makes bad data visible before analysis.

## S2. Trend viewer

```
+--------------------------------------------------------------------------------+
| mill_nominal_48h   [1h][8h][24h][All][Custom]   ⟲ Undo zoom   Cursor: shared ▾  |
+-------------+------------------------------------------------------------------+
| Tags        |  Pane 1  (PV, SP)   unit: t/h                          [link ⛓] |
| [search..]  |  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~                                     |
| ▸ sim.mc    |  Pane 2  (OUT)      unit: %                            [link ⛓] |
|   ☑ hpgr_pv |  ____/‾‾‾\____                                                    |
|   ☑ hpgr_sp |  Pane 3  (MODE)     MAN ░░  AUTO ▓▓▓▓▓▓  CAS ░░                   |
|   ☐ ...     |                                                                  |
|             |  [=====|  overview strip with draggable window  |=============]   |
+-------------+------------------------------------------------------------------+
| Cursor 10-02 14:05:12   hpgr_pv 412.3 t/h   hpgr_sp 410.0   OUT 63.1 %  (good)  |
+--------------------------------------------------------------------------------+
```

- Panes share one time axis; a **shared crosshair** reads all values at the bottom (Grafana-style shared tooltip).
- **Zoom:** drag a box, wheel, or drag the overview strip; `Undo zoom` restores the previous range (Process Analyst-style).
- **Link icon** per pane shows whether the pane follows the common range; unlinked panes keep their own range, so zoom
  never surprises (the confusion reported by PI Vision users).
- Mode is a **shaded band** (MAN / AUTO / CAS), not a line. Bad-quality samples are drawn hollow and listed in the legend.
- Min/max downsampling (already in the API) keeps spikes visible when zoomed out; a small badge shows `downsampled`.
- Tag tree is searchable; dropping a tag on a pane adds it; drop between panes creates a new pane.

## S3. Loop overview (the page the engineer opens every morning)

```
+--------------------------------------------------------------------------------+
| Loops   mill_nominal_48h   last analysis 10-11 09:12 (fresh)      [ Re-run ⟳ ]  |
+--------------------------------------------------------------------------------+
| ▲ 3 need attention   ■ 1 problem   ● 14 OK   ○ 2 not in use                     |
| Filter: [All ▾] [Problem type ▾] [search ...]        Sort: Priority ▾            |
+--------------------------------------------------------------------------------+
|   Status  Loop              Health   Main finding                  In use  Trend |
| ■ Problem hpgr_press_pc      ▓▓░░░░ 22  Stiction suspected         94 %   ~~/\/  |
| ▲ Warn    cyclone_water_fc   ▓▓▓░░░ 41  Oscillating, T = 14 min    88 %   ~^~^~  |
| ▲ Warn    mill_feed_wic      ▓▓▓▓░░ 55  Saturated 31 % of time     97 %   ___‾‾  |
| ○ Unused  sump_level_lc      –          Manual 71 % of time         29 %   ------ |
| ● OK      mill_power_pc      ▓▓▓▓▓▓ 91  –                          99 %   ~~~~~  |
+--------------------------------------------------------------------------------+
```

- One row per loop, sorted by priority (problem types first, then lowest health). Counts on top are clickable filters.
- **Health** is one composite 0-100 number (idea from commercial effectiveness scores: share of time in use, within an
  error band and not saturated), always with the formula in a tooltip and in `docs/ASSUMPTIONS.md` before it ships.
- **Main finding** is a sentence generated from `LoopReport.findings`; the sparkline shows the last day of PV.
- Row click opens S4. Not-in-use loops are greyed, not red: "not in use" is a fact, not a fault.

## S4. Loop detail

```
+--------------------------------------------------------------------------------+
| Loops > hpgr_press_pc     ■ Problem: stiction suspected         [Open in Trends] |
+--------------------------------------------------------------------------------+
| WHY (plain language)                              | KEY NUMBERS                  |
| The valve moves in jumps, which causes a         | In use (AUTO/CAS)   94 %     |
| steady cycle of period 14 min. Tuning will not   | Saturated            2 %     |
| remove it; check the valve first.                | Harris index       0.18 (low)|
|                                                  | Oscillation T     14.0 min   |
+--------------------------------------------------+ Stiction (THD)  1.3 (suspect)|
| PV / SP      ~~~~~~~~~~~~~~~~~~~~~~~~~~~        +------------------------------+
| OUT          ____/‾‾‾\____/‾‾‾\____            | WHAT TO DO NEXT              |
| MODE         AUTO ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓             | 1. Inspect valve / positioner |
| (window: the 6 h that produced the finding)     | 2. Tuning report: blocked     |
|                                                  |    until stiction is resolved |
+--------------------------------------------------+------------------------------+
| [ Tuning report ]  [ Benefit report ]  Evidence: PV-OUT plot ▸  Metric definitions ▸ |
+--------------------------------------------------------------------------------+
```

- Top-left sentence = the answer; numbers are supporting evidence. "What to do next" avoids a dead end and explains
  why the tuning report is blocked (rule already in `tuning_report`).
- The embedded trend is the S2 component, pre-zoomed to the window that triggered the finding.
- Optional evidence: PV-vs-OUT scatter (stiction shows as a loop/parallelogram), shown on demand.

## S5. PID tuning report (wizard, 3 steps)

```
 1 Select data window  ->  2 Check model  ->  3 Choose robustness and export
```

1. **Window:** suggested AUTO step-response stretches are highlighted on the trend; the user can adjust.
2. **Model check:** measured response vs fitted FOPDT overlaid; fit quality as a plain verdict (`good / fair / poor`);
   a warning if the data is closed-loop or stiction was detected.
3. **Result:** robustness slider (`Smooth` <-> `Fast`) updating a simulated step response live; table of Kp/Ti in DCS
   parameter forms (gain, proportional band, repeats/min, seconds); `Export Markdown`. Current vs proposed settings
   side by side. Nothing is written to the plant.

## S6. Benefit report

Inputs on the left (assumptions with units, defaults from `ASSUMPTIONS.md`, each editable and marked as "assumption"),
result on the right: a distribution sketch of PV now vs expected, freed room to the limit, and value per hour with the
assumption list printed under the number. Principle: **no number without its assumptions next to it.**

## Loops of use (flows)

- **Daily check (2 min):** Loops -> filter "need attention" -> open worst loop -> read WHY.
- **Diagnose (10 min):** loop detail -> evidence trend -> decide: fix hardware, or open tuning report.
- **Tune (20 min):** tuning report -> pick window -> check model -> export settings.
- **Prove value:** benefit report -> export for the review meeting.

Every flow ends with an exportable artefact (Markdown / CSV) and never requires leaving the browser.

## Component notes (for implementation)

- Charts: uPlot (ADR 007), synchronised cursor via its sync API; one `TrendPane` component reused in S2 and S4.
- Status chip component takes `{level, label}` and always renders icon + word.
- Data comes from the existing API; needed additions: `/datasets/{id}/loops` (reports), `/loops/{id}/window`.
- Accessibility: keyboard zoom (`+`/`-`), focus order top bar -> filters -> table, 4.5:1 text contrast.
- Tests: Vitest for the chip and downsample badge; Playwright for the S3 -> S4 -> S2 click path on a simulator dataset.

## References (ideas only)

- ISA High Performance HMI overview: https://www.isa.org/getmedia/06130a38-f7af-4b35-8c9c-2c34f25c1977/The-High-Performance-HMI-Overview-v2-01.pdf
- Corso Systems summary of the High Performance HMI Handbook: https://corsosystems.com/posts/the-high-performance-hmi-handbook-and-you-part-1
- Control Station PlantESP (composite loop effectiveness): https://controlstation.com/plantesp/
- Valmet PlantTriage: https://www.valmet.com/automation/services/process-performance/pid-tuning-process-control/planttriage/
- Honeywell Loop Scout (ranking, stiction flag): https://www.automationworld.com/products/control/article/13304529/milestone-for-honeywell-loop-scout
- AVEVA PI Vision trend ranges / zoom behaviour: https://community.aveva.com/pi-square-community/f/forum/98970/trends-with-multiple-time-ranges-in-pi-vision/360642
- AVEVA Process Analyst (zoom undo): https://docs.aveva.com/bundle/plant-scada/page/1126207.html
- Grafana shared crosshair / tooltip: https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/modify-dashboard-settings/
- Nielsen Norman Group, 10 usability heuristics: https://www.nngroup.com/articles/ten-usability-heuristics/
- Okabe-Ito palette (verify hex values at https://jfly.uni-koeln.de/color/).

## Decisions (owner, 2026-10-11)

1. **Health score:** shown as a percentage (0-100 %) next to the categorical status; the formula is documented in
   `docs/ASSUMPTIONS.md` before it ships and visible in a tooltip. S3 and S4 show "Health 22 %".
2. **Languages:** English, Polish and Spanish from the start, with an open mechanism for adding more:
   - all UI text lives in per-language catalogues (`locales/<code>.json`, keys are stable identifiers, English is the
     fallback for missing keys); no text hard-coded in components;
   - the language is chosen in the top bar and remembered; numbers, dates and decimal separators follow the locale
     (decimal comma in pl/es);
   - generated finding sentences ("Stiction suspected", "Saturated 31 % of time") are templates with parameters in the
     same catalogues, not strings built in Python; the API returns a finding code plus parameters, the UI renders it;
   - adding a language = copying `en.json`, translating, registering the code; a test fails if a catalogue lacks a key
     that `en.json` has (reported as a warning for community languages).
3. **Themes:** light and dark, selectable in the top bar (default: follow the operating system). Both themes use design
   tokens (CSS variables), so the status colours, series palette and contrast (4.5:1) are verified per theme. Status
   still relies on shape + text, so the themes change only appearance, never meaning.
