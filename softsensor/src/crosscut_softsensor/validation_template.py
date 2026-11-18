"""Frozen, versioned Markdown template of the validation report (issue #40).

The text below is dataset independent: it holds headings, fixed wording and `$placeholders`
only. Every report records TEMPLATE_VERSION and the SHA-256 of TEMPLATE_V1. To change the
wording, add TEMPLATE_V2 with a new version and hash; never edit V1 (a test pins its hash).
"""

from __future__ import annotations

import hashlib

TEMPLATE_VERSION = "1"

TEMPLATE_V1 = """# Validation report: $analyser_tag against $lab_tag

Template version $template_version, SHA-256 $template_sha256.
Generator $generator. Dataset `$dataset_name`, SHA-256 $dataset_sha256.
Config SHA-256 $config_sha256.

## 1. Data coverage

$coverage_table

## 2. Stamp and missing-code checks

$stamp_table

## 3. Alignment

Sign convention: $sign_convention.
Best delay $best_delay_s s (95 percent interval $interval_low_s to $interval_high_s s,
$alignment_pairs pairs, search boundary reached: $boundary).

## 4. Agreement at the best delay

Pairs: $pairs. Differences are analyser minus lab, in the tag unit.

$agreement_table

Bland-Altman limits of agreement: $loa_lower to $loa_upper (bias plus or minus $z standard
deviations of the differences).

## 5. Drift over time

Trend of the difference: $trend_per_day per day.

$drift_table

## 6. Process tags

$process_table

## 7. Checks against configured thresholds

$threshold_table

Thresholds are configuration fields; "not assessed" means none was configured.
"""


def template_sha256(text: str = TEMPLATE_V1) -> str:
    """SHA-256 of the template text (UTF-8), recorded in every report."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
