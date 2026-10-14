# Export guide: data for loop monitoring  

*Guide for process‑control engineers who need to export historian data for analysis with the Crosscut Process Suite loop‑monitoring tools (oscillation, manual mode, saturation, flat‑line, valve stiction, tuning).*

---  

## 1. What we need  

- **Four tags per control loop**  
  1. **PV** – Process variable measurement.  
  2. **SP** – Set‑point.  
  3. **OUT** – Controller output (typically %‑open, duty‑cycle, or valve position).  
  4. **MODE** – Auto / Manual flag (we read 0 = manual, 1 = auto, 2 = cascade; if your system codes the modes differently, send the mapping or recode before export, otherwise every loop looks manual or automatic by mistake).  

- **Engineering units & ranges**  
  - Provide the units for PV and OUT (e.g., °C, kPa, % open).  
  - Include the nominal range for each tag (min‑max) so Crosscut can scale the data correctly.  

- **Tag naming**  
  - Use a consistent naming convention (e.g., `LOOP01_PV`, `LOOP01_SP`, …).  
  - If you anonymise the names, keep a local mapping table.

---  

## 2. Which loops to export  

| Category | Example loops (adjust to your plant) |
|----------|--------------------------------------|
| **Suspected poorly tuned (5‑20 loops)** | LOOP01, LOOP03, LOOP07, LOOP12, LOOP15, LOOP18, … |
| **Reference – believed to be well tuned (3‑5 loops)** | LOOP02, LOOP09, LOOP14, … |

- Export **all four tags** for every loop listed.  
- If you have more loops, you may add them, but keep the list manageable for the first review.

---  

## 3. Period & length  

- **Minimum record length:** 6 h (hard minimum).  
- **Recommended:** at least 24 h, preferably a full 7 day window.  
- Include a period when the plant operated under normal conditions (no start‑up or shutdown transients).  

> *Tip:* run the readiness check (`check_readiness` in `loops`) on the export before sending: it reports record length, sample period, missing values and stuck signals per tag.

---  

## 4. Sampling  

- **Raw historian samples** are preferred.  
- If you must down‑sample, keep the interval **≤ 10 s**.  
- **Do not use averaged or compressed data** that smooths faster dynamics:  
  - Samples > 15 s can hide valve stiction and short‑duration oscillations.  
- Turn off any automatic compression / interpolation in the historian before export.  

**How to export:**  
```text
Export raw tag values (no aggregation) from the historian
Save as a CSV file (see Section 5)
```

---  

## 5. Format  

- **File type:** CSV (comma‑separated values).  
- **Columns:**  
  1. `Timestamp` – ISO 8601 format with time‑zone offset (e.g., `2026-10-14T08:00:00+01:00`).  
  2. One column per tag (PV, SP, OUT, MODE).  
- **Decimal separator:** either `.` or `,` – Crosscut detects it automatically.  
- **Missing / bad‑quality values:** leave the cell empty (do **not** write `0`).  

**Example header row**  
```
Timestamp,LOOP01_PV,LOOP01_SP,LOOP01_OUT,LOOP01_MODE,LOOP02_PV,…
```

---  

## 6. What **not** to send  

- No recipe files, operator names, shift logs, or any personal data.  
- Do **not** include tags unrelated to the four‑tag loop model.  

**Anonymisation**  
- Use the **crosscut anonymiser** (`anonymise` in connectors) to hide:  
  - Tag names (replace with generic identifiers).  
  - Absolute timestamps (you may offset all times by a constant, keeping the relative spacing).  
  - Levels and scales (each value is multiplied by a constant and shifted; a setpoint and its measurement get the same constants).  
- Keep the mapping (original ↔ anonymised) locally; only the anonymised CSV is sent.  
- The dynamics (shape, timing, amplitude) remain intact for analysis.

---  

## 7. Checklist before sending  

- [ ] All required four tags are present for each listed loop.  
- [ ] Time window ≥ 24 h (or ≥ 6 h if unavoidable) and contains normal plant operation.  
- [ ] Sampling interval ≤ 10 s; no historian compression applied.  
- [ ] CSV follows the format described in Section 5 (ISO 8601 timestamps, empty cells for bad data).  
- [ ] All prohibited information removed or anonymised using `anonymise`.  

---  

**End of guide**. If any question arises, contact the Crosscut support team or refer to the internal data‑export policy.