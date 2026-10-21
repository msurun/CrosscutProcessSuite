// src/components/ContextBar.tsx

/**
 * Compact header strip summarising the loaded dataset: id, time period, sample period,
 * tag count and (optionally) when the analysis finished and how long it took.
 * Read-only context for every screen; no controls, no data fetching.
 */

import type { DatasetSummary } from "../api";
import type { Translate } from "../findings";
import { formatFixed } from "../format";

/** One time unit used to render the sample period; `seconds` is the size of that unit. */
interface PeriodUnit {
  seconds: number;
  /** Translation key appended to the number: "s", "min" or "h". */
  suffixLabel: string;
}

/** Units from smallest to largest; the largest one giving a value >= 1 wins. */
const PERIOD_UNITS: readonly PeriodUnit[] = [
  { seconds: 1, suffixLabel: "s" },
  { seconds: 60, suffixLabel: "min" },
  { seconds: 3600, suffixLabel: "h" },
];

/** Placeholder shown when a value cannot be computed. */
const DASH = "–";

/** Rendered when a dataset has fewer than two samples, so no period can exist. */
const INSUFFICIENT_SAMPLES = 2;

/** Time zone of every timestamp in the bar: the data are stamped in UTC, so it is shown explicitly. */
const DISPLAY_TIME_ZONE = "UTC";

/** Short date + time formatter options, in UTC; identical for the period and analysis times. */
const SHORT_DATE_TIME: Intl.DateTimeFormatOptions = { dateStyle: "short", timeStyle: "short", timeZone: DISPLAY_TIME_ZONE };

type AnalysisInfo = { finishedAt: Date; tookMs: number };

type ContextBarProps = {
  /** The currently loaded dataset, or undefined before any is chosen (then nothing is shown). */
  dataset: DatasetSummary | undefined;
  /** The last finished analysis, or null before the first run. */
  analysis: AnalysisInfo | null;
  /** Translator for every user-visible string; keys are defined by the callers below. */
  t: Translate;
};

/**
 * Format a timestamp in UTC with a zone mark ("1/1/24, 12:00 AM UTC"), in the language of
 * `<html lang>`. Read at call time so a runtime language switch takes effect immediately.
 */
function formatTimestamp(time: Date): string {
  const lang = document.documentElement.lang || undefined;
  return `${new Intl.DateTimeFormat(lang, SHORT_DATE_TIME).format(time)} ${DISPLAY_TIME_ZONE}`;
}

/**
 * Render sample period `seconds` with the largest unit giving a value >= 1,
 * at most one decimal digit (e.g. "10 s", "1.5 min", "2 h").
 */
function formatSamplePeriod(seconds: number): string {
  const chosen = chooseUnit(seconds);
  const value = formatFixed(seconds / chosen.seconds, 1);
  return `${value} ${chosen.suffixLabel}`;
}

/** Pick the largest unit not greater than `seconds`; falls back to the smallest unit. */
function chooseUnit(seconds: number): PeriodUnit {
  let selected = PERIOD_UNITS[0];
  for (const unit of PERIOD_UNITS) {
    if (seconds / unit.seconds >= 1) {
      selected = unit;
    }
  }
  return selected;
}

/** Sample-to-sample period in seconds, or the dash when it cannot be computed. */
function samplePeriodSeconds(dataset: DatasetSummary): string {
  if (dataset.n_samples < INSUFFICIENT_SAMPLES) {
    return DASH;
  }
  const startMs = Date.parse(dataset.time_range.start_utc);
  const endMs = Date.parse(dataset.time_range.end_utc);
  const spanSeconds = (endMs - startMs) / 1000;
  return formatSamplePeriod(spanSeconds / (dataset.n_samples - 1));
}

/** "start – end" range of the dataset in the user's language. */
function formatPeriod(dataset: DatasetSummary): string {
  const start = formatTimestamp(new Date(dataset.time_range.start_utc));
  const end = formatTimestamp(new Date(dataset.time_range.end_utc));
  return `${start} ${DASH} ${end}`;
}

/** The short form of a source kind (`dataset.source.kind`, e.g. "sim"), or empty. */
function sourceKind(dataset: DatasetSummary): string {
  const kind = dataset.source["kind"];
  return typeof kind === "string" ? kind : "";
}

/** One `<div>` with a small `<dt>` label and a `<dd>` value. */
function ContextItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="context-item">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** The dataset-id item, with the source-kind badge after the id when one is present. */
function DatasetItem({ dataset, t }: { dataset: DatasetSummary; t: Translate }) {
  const kind = sourceKind(dataset);
  return (
    <ContextItem label={t("context.dataset")}>
      {dataset.id}
      {kind !== "" && <span className="badge">{kind}</span>}
    </ContextItem>
  );
}

/** Time items: period, sample period, tag count and, when present, when the analysis finished. */
function TimeItems({ dataset, analysis, t }: {
  dataset: DatasetSummary;
  analysis: AnalysisInfo | null;
  t: Translate;
}) {
  return (
    <>
      <ContextItem label={t("context.period")}>{formatPeriod(dataset)}</ContextItem>
      <ContextItem label={t("context.samplePeriod")}>{samplePeriodSeconds(dataset)}</ContextItem>
      <ContextItem label={t("context.tags")}>{String(dataset.n_tags)}</ContextItem>
      {analysis !== null && (
        <ContextItem label={t("context.analysedAt")}>
          {formatTimestamp(analysis.finishedAt)}{" "}
          {t("context.took", { seconds: formatFixed(analysis.tookMs / 1000, 1) })}
        </ContextItem>
      )}
    </>
  );
}

/**
 * Render the dataset context strip; returns null when no dataset is loaded.
 */
export function ContextBar({ dataset, analysis, t }: ContextBarProps) {
  if (dataset === undefined) {
    return null;
  }
  return (
    <section className="context-bar" aria-label={t("context.label")}>
      <dl className="context-list">
        <DatasetItem dataset={dataset} t={t} />
        <TimeItems dataset={dataset} analysis={analysis} t={t} />
      </dl>
    </section>
  );
}
