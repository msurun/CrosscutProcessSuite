// Builds and saves the trend chart of one loop (PV, SP, OUT and MODE when present) for "Open in Trends" (#207).
// Pure draft building on top of trendChartModel; only openLoopChart talks to the API.
import type { LoopSummary, TagInfo } from "./api";
import { addSeries, emptyDraft } from "./trendChartModel";
import { createChart, type TrendChartDraft } from "./trendChartsApi";

/** The loop's tags in drawing order; MODE is left out when the loop has none. */
function loopTags(loop: LoopSummary): string[] {
  return [loop.pv, loop.sp, loop.out, loop.mode].filter((tag) => tag !== "" && tag != null);
}

/** Draft named "<loop> PV/SP/OUT" holding the loop's tags of `datasetId`; units come from `tags` when known. */
export function loopChartDraft(datasetId: string, loop: LoopSummary, tags: readonly TagInfo[]): TrendChartDraft {
  const unitOf = (tag: string) => tags.find((one) => one.id === tag)?.unit;
  return loopTags(loop).reduce(
    (draft, tag) => addSeries(draft, { source: datasetId, tag, unit: unitOf(tag) }).draft,
    emptyDraft(`${loop.name} PV/SP/OUT`),
  );
}

/** Saves the loop's chart and returns its new id. */
export async function openLoopChart(datasetId: string, loop: LoopSummary, tags: readonly TagInfo[]): Promise<string> {
  return (await createChart(loopChartDraft(datasetId, loop, tags))).id;
}
