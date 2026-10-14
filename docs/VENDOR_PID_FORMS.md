# Vendor PI forms: Siemens and ABB (assumption A7)

What the tuning module needs to know about the two target systems, taken from public manuals on 2026-10-14.
Page numbers refer to the PDF page. Nothing is copied from the documents except symbols and names; the code is
`loops/src/crosscut_loops/vendor_forms.py`, tests `loops/tests/test_vendor_forms.py`.

Our SIMC/AMIGO output is a **normalised PI**: `kc` dimensionless (output fraction per PV fraction of range), `ti_s` in seconds.

## Siemens PID_Compact (S7-1200 FW >= 4.0, S7-1500): verified

| Fact | Source |
|---|---|
| Algorithm: y = Kp [ (b w - x) + 1/(TI s) (w - x) + TD s / (a TD s + 1) (c w - x) ]; b = proportional weighting, c = derivative weighting, a = derivative delay coefficient | app. example 79047707 V3.0.0 (03/2017) p.14-15; S7-1500 PID Control function manual A5E35300227-AA (12/2014) p.90 (symbol table) |
| All time parameters are in **seconds** (S7-200 used minutes for TI and TD) | FAQ 109481448 V1.0 (01/2016) p.5 |
| Gain must be positive; reverse action is `Config.InvertControl` | FAQ p.3; function manual p.91 |
| `TI = 0` switches the integral action off; `TD = 0` the derivative | function manual p.91-92 |
| Tags: `Retain.CtrlParams.Gain`, `.Ti`, `.Td`, `.TdFiltRatio` (a), `.PWeighting` (b), `.DWeighting` (c), `.Cycle` (sample time, s) | FAQ p.3-5 |
| Classic behaviour (no weighting, derivative one cycle): `TdFiltRatio = 0`, `PWeighting = 1`, `DWeighting = 1` | FAQ p.4 |
| Scaling changes the effective gain: PV in engineering units and output 0..100 by default; the same Gain with a different range gives a different loop | FAQ section 1.4, p.6-8 |
| `IntegralResetMode` decides the integral part when switching to automatic (default like S7-200: starts at 0) | FAQ p.9 |

**Mapping from our PI:** `Ti = ti_s` (no conversion), `Td = 0`, `PWeighting = 1.0`, `Gain = kc * out_span / pv_span`.
The range formula is ours, derived from the principle in FAQ 1.4; it is unit-tested but not compared with a real controller.

## ABB PidCC (AC 800M), read through the Pid01A unit: partly verified

| Fact | Source |
|---|---|
| Ideal PID: G(s) = Gain (1 + 1/(TI s) + TD s / (1 + TF s)); TF = filter time of the derivative | ABB 3AST001596D013 rev D (2009-01-23) p.9 |
| "The algorithm is based on the PidCC control module"; derivative on measurement or on deviation (selectable) | same, p.8 |
| Deviation DEV = MV - WSP (measured minus working setpoint); direct or reverse action is selectable | same, p.9 |
| Deviation is expressed in percent of the MV range; PI block and output default to -100..+100 % (scalable) | same, p.23 (section 4.12) |
| Integration is blocked inside a dead band; if TS/TI > 1 the algorithm sets TS/TI = 1 | same, p.9 |
| External parameters `Gain`, `TI`, `TD`, `TF` (initial Gain 0.5, TI 30, TD 0, TF 0) | same, p.10 |

**NOT confirmed:** the unit of TI and TD (seconds or minutes). This document does not say, and the library manual
(3BSE035982 / 3BSE041488, ABB library portal) blocked the download here (HTTP 403). A forum post says seconds; that is not
evidence. The code uses seconds and the form stays `partly_verified` until the unit is read in the library manual or the
Control Builder help of the real system. Also open: the Pid01A document is the ControlIT unit around PidCC, not the PidCC page itself.

**Mapping from our PI:** `Gain = kc` (percent in, percent out: no range scaling), `TI = ti_s` (unit to confirm), `TD = 0`.

## What we do with this

1. **Output form.** The tuning report (`tuning_report.py`) can show, next to the generic settings, the named tags of the target system
   with the evidence level, so an engineer never types a number into the wrong unit.
2. **Warnings travel with the numbers.** Each form carries its caveats (`PWeighting = 1`, `TI = 0` disables the integral, positive gain only,
   range scaling for Siemens, the open unit for ABB). A `partly_verified` form must be shown with its open point.
3. **Advisory only.** Nothing writes to a DCS. The engineer applies the values; the first real check is a step test on the plant.
4. **Closing the ABB gap** needs one of: the PidCC page of the library manual, a screenshot of the block's parameter help, or the TI value
   and unit of a loop running on the owner's system (no plant data is needed, only the unit).
5. **Siemens gap:** a soft PLC (PLCSIM) run would turn the range formula from derived to tested (stage V5 of the plan).
6. **Not covered:** PID_Compact derivative with filter (we tune PI only), ABB PidAdvancedCC, cascade, other vendors.
