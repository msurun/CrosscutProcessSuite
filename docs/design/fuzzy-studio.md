# Design notes: graphical fuzzy configuration ("Fuzzy Studio")

Status: idea capture (2026-10-10), not yet scheduled. Planned module: expert/fuzzy layer, GUI part of stage 3.

## Why

Graphical configuration of fuzzy logic is attractive to process engineers because it is visual, immediate and uses
the vocabulary of operators. The aim is an editor in which an engineer can build, understand and tune a fuzzy
controller or a fuzzy supervisor of an MPC without writing anything. These notes capture UX ideas; they are
original requirements, not a description of any other product, and no third-party code, screens or documents are
to be copied.

## Core ideas

- **Variables panel:** inputs and outputs with engineering units and ranges taken from the tag catalog;
  linguistic terms ("low", "normal", "high", "rising"), colour-coded.
- **Membership function editor:** curves drawn over the real range of the variable (triangular, trapezoidal,
  Gaussian), dragged with handles, snapping to sensible values, with the current process value shown as a moving
  marker so that the engineer sees which terms are active right now and by how much.
- **Rule editor, two views of the same rules:** a matrix (term of input A by term of input B gives an output term)
  for compact two-input rules, and readable sentences ("IF mill load IS high AND power IS rising THEN feed
  decrease LARGE") for the general case. Rule weights and enable switches per rule.
- **Live inference panel:** shows the inputs, the rules that fire (bar per rule), the aggregated output shape and
  the defuzzified output. Works on live data, on a replayed historical period or on a manual what-if slider.
- **Replay and backtest on history:** a timeline with the fuzzy output next to what the operator did, so that rules
  are tuned against real behaviour before they are allowed to write anything.
- **Explanations:** for every decision a one-line reason (the dominant rules); the same text goes to the operator
  display and to the audit log.
- **Safe by construction:** output limits, rate limits and the write gateway apply to fuzzy outputs exactly as to any
  other source; modes off / advisory / closed loop per output.
- **Combining with MPC:** the same editor configures a fuzzy supervisor that changes MPC weights, zones or modes, or
  a fuzzy correction fed into MPC as a measured disturbance (topologies D to F of the strategy designer).
- **Auto-calibration:** the range recommender proposes membership breakpoints and rule thresholds from history; the
  engineer accepts, edits or rejects them.
- **Versioning and diff:** every change is a version with a visual diff of curves and rules; import and export as
  JSON validated by a schema.

## Open questions

- Which defuzzification methods to support first (centroid, weighted average)?
- How to present multi-input rule bases beyond two inputs without overwhelming the user?
- How to show uncertainty when inputs are soft-sensor estimates?
