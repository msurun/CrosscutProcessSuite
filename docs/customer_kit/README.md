# Customer validation kit

For a first trial on a customer's own data (V6). Order of use:

1. Customer reads `EXPORT_GUIDE.md` and exports the loops.
2. Customer runs `crosscut_loops.readiness.check_readiness` on the export; fixes what fails.
3. Optional: customer hides names, scales and absolute time with `crosscut_connectors.anonymise.anonymise`
   (the mapping stays with the customer; `loops/tests/test_anonymised_findings.py` shows that the findings
   and the stiction verdict do not change).
4. Analyst runs the loop analysis and fills in `REPORT_TEMPLATE.md`.

Limits: nothing here was tried on real customer data yet; the readiness thresholds (6 h / 24 h, 15 s / 60 s,
5 % / 30 % missing, 50 % / 90 % stuck) are engineering judgement, not measured.
