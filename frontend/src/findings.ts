/** Turns backend findings (a stable code plus parameters) into sentences in the chosen language. */

import type { LoopFinding, LoopSummary } from "./api";

/** Translator signature shared with `i18n.translate` once the language is bound. */
export type Translate = (key: string, params?: Record<string, string | number>) => string;

/** Sentence for one finding, e.g. "Saturated 31 % of the time". */
export function findingText(t: Translate, finding: LoopFinding): string {
  return t(`finding.${finding.code}`, finding.params);
}

/** The most important finding of a loop as a sentence, or the "no problems" text. */
export function mainFindingText(t: Translate, loop: LoopSummary): string {
  const first = loop.findings[0];
  return first ? findingText(t, first) : t("loops.noFindings");
}

/** Hints for the "what to do next" list: one per finding, or "no action needed". */
export function nextStepTexts(t: Translate, loop: LoopSummary): string[] {
  if (loop.findings.length === 0) return [t("next.ok")];
  return loop.findings.map((finding) => t(`next.${finding.code}`));
}

const STATUS_PRIORITY: Record<string, number> = { problem: 0, warning: 1, ok: 2, unused: 3 };

/** Sort order for the overview: problems first, then the lowest health. */
export function compareLoops(a: LoopSummary, b: LoopSummary): number {
  const byStatus = STATUS_PRIORITY[a.status] - STATUS_PRIORITY[b.status];
  if (byStatus !== 0) return byStatus;
  return (a.health_percent ?? 101) - (b.health_percent ?? 101);
}
