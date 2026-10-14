# Loop health report: {customer code}

## 1. Header

| Field | Value |
| --- | --- |
| Customer code | {customer_code} |
| Export id | {export_id} |
| Period analysed | {period_start} – {period_end} |
| Sample period | {sample_period_s} s |
| Number of loops | {loop_count} |
| Analyst | {analyst_name} |
| Report date | {report_date} |

## 2. Summary

| Loop | Health % | Status | Findings | Recommended action |
| --- | --- | --- | --- | --- |
| {loop_tag_1} | {health_pct_1} | {status_1} | {findings_1} | {action_1} |
| {loop_tag_2} | {health_pct_2} | {status_2} | {findings_2} | {action_2} |

Status is one of `ok`, `warning`, `problem`. Health % is the share of the period the loop
spent in good operating conditions; it is a summary, not a control-system metric.

## 3. Findings per loop

Repeat this block once per loop.

### {loop_tag}

| Indicator | Value |
| --- | --- |
| Oscillation period | {oscillation_period_s} s |
| Share of time in manual | {manual_share_pct} % |
| Share of time saturated | {saturated_share_pct} % |
| Stiction verdict | {stiction_verdict} |
| Tuning model fit R2 | {tuning_fit_r2} |

Evidence: {evidence_notes}

Stiction verdict is one of `stiction`, `no_stiction`, `inconclusive`.

## 4. What the analysis can and cannot say

- Every verdict in this report is advisory. Nothing is written to any control system.
- A stiction verdict needs both OUT and OP to be present, and a sample period faster than about 15 s.
- The stiction check is validated on simulated data only. It was found at a 4 % valve band with low
  noise, and in about 70 % of runs at 8 % with full noise.
- A periodic square-wave disturbance is a known false alarm for the stiction check.
- A tuning recommendation is withheld when stiction is suspected or when the model fit R2 is below 0.5.

## 5. Data quality

Readiness check result: {readiness_result}

Warnings:

- {data_quality_warning_1}
- {data_quality_warning_2}

## 6. Next steps

- [ ] Review the findings with {customer_contact}.
- [ ] Confirm the data quality warnings in section 5 with plant personnel.
- [ ] Re-run the analysis on a longer period for any loop marked `warning` or `problem`.
- [ ] Agree which loops enter a field check.
- [ ] Book a follow-up with the Crosscut analyst for {follow_up_date}.

## 7. Decisions for the customer

The following must be confirmed before any change is made:

- [ ] {decision_1}
- [ ] {decision_2}
- [ ] {decision_3}

No change to tuning, valve maintenance or loop configuration is made on the basis of this report
alone. The customer owns the decision and the change.