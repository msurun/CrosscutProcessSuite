/**
 * "Replay" panel: runs a rule base over recorded data and draws one trend pane per input and output.
 *
 * The fuzzy output may contain `null` for "no rule fired"; that draws as a gap in the line.
 */

import { variableLabel } from "../fuzzyNames";
import { useCallback, useEffect, useRef, useState } from "react";
import { replayFuzzy, type FuzzyReplay } from "../api";
import type { Translate } from "../findings";
import type { FuzzyDocument, FuzzyVariable } from "../fuzzy";
import { TrendPane } from "./TrendPane";

/** Maximum number of points requested for one replay; keeps the chart light. */
const MAX_POINTS = 1200;

/** Height of an input pane, in CSS pixels. */
const INPUT_PANE_HEIGHT = 140;

/** Height of an output pane, in CSS pixels.
 *
 * Output panes are taller because they show two series (fuzzy and actual).
 */
const OUTPUT_PANE_HEIGHT = 160;

/** Shared zoom/pan group of all panes of this panel. */
const SYNC_KEY = "fuzzy-replay";

/** Colour of a single-series pane. */
const INPUT_COLOR = "--series-1";

/** Colours of the fuzzy and the actual output series, in that order. */
const OUTPUT_COLORS = ["--series-3", "--series-2"];

/** Nanoseconds in one second; the chart x axis expects seconds. */
const NS_PER_S = 1e9;

type ReplayStatus = "idle" | "loading" | "ready" | "error";

interface ReplayState {
  status: ReplayStatus;
  result: FuzzyReplay | null;
  errorReason: string;
}

const EMPTY_STATE: ReplayState = { status: "idle", result: null, errorReason: "" };

/**
 * Run the rule base over the recorded data of `datasetId`.
 *
 * A late response of an older click is dropped, so the panel always shows the newest request.
 */
function useReplay(datasetId: string, document: FuzzyDocument): ReplayState & { run: () => void } {
  const [state, setState] = useState<ReplayState>(EMPTY_STATE);
  const requestCounter = useRef(0);

  const run = useCallback(() => {
    requestCounter.current += 1;
    const requestId = requestCounter.current;
    setState({ status: "loading", result: null, errorReason: "" });

    replayFuzzy(datasetId, document, { maxPoints: MAX_POINTS })
      .then((result) => {
        if (requestId !== requestCounter.current) return;
        setState({ status: "ready", result, errorReason: "" });
      })
      .catch((error: unknown) => {
        if (requestId !== requestCounter.current) return;
        setState({ status: "error", result: null, errorReason: describeError(error) });
      });
  }, [datasetId, document]);

  useEffect(() => {
    run();
  }, [run]);

  return { ...state, run };
}

/** Human-readable text for a rejected request promise. */
function describeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

/** Seconds since the Unix epoch, converted from the replay's UTC nanoseconds. */
function toSeconds(t: number[]): number[] {
  return t.map((nanoseconds) => nanoseconds / NS_PER_S);
}

/** Trend pane of one input variable: always a single fuzzy-input series. */
function InputPane({ variable, replay, t }: { variable: FuzzyVariable; replay: FuzzyReplay; t: Translate }) {
  const values = replay.inputs[variable.id] ?? [];
  const label = t("fuzzy.replay.input", { name: variableLabel(t, variable) });
  const data = [toSeconds(replay.t), values];

  return (
    <TrendPane
      data={data}
      labels={[label]}
      colors={[INPUT_COLOR]}
      unit={variable.unit}
      height={INPUT_PANE_HEIGHT}
      syncKey={SYNC_KEY}
    />
  );
}

/** Trend pane of one output variable: fuzzy output, plus the recorded tag when present. */
function OutputPane({ variable, replay, t }: { variable: FuzzyVariable; replay: FuzzyReplay; t: Translate }) {
  const fuzzy = replay.outputs[variable.id] ?? [];
  const actual = replay.actual[variable.id];
  const fuzzyLabel = t("fuzzy.replay.output", { name: variableLabel(t, variable) });

  const labels = [fuzzyLabel];
  const colors = [OUTPUT_COLORS[0]];
  const data = [toSeconds(replay.t), fuzzy];
  if (actual !== undefined) {
    labels.push(t("fuzzy.replay.actual", { tag: variable.tag ?? "" }));
    colors.push(OUTPUT_COLORS[1]);
    data.push(actual);
  }

  return (
    <TrendPane
      data={data}
      labels={labels}
      colors={colors}
      unit={variable.unit}
      height={OUTPUT_PANE_HEIGHT}
      syncKey={SYNC_KEY}
    />
  );
}

/**
 * Panel that replays `document` over `datasetId` and draws the result.
 *
 * The replay starts on mount and whenever `datasetId` changes; the button reruns it.
 */
export function ReplayPanel({
  datasetId,
  document,
  t,
}: {
  datasetId: string;
  document: FuzzyDocument;
  t: Translate;
}) {
  const { status, result, errorReason, run } = useReplay(datasetId, document);

  return (
    <>
      <h3>{t("fuzzy.replay")}</h3>
      <p className="hint">{t("fuzzy.replay.hint")}</p>
      <button type="button" className="filter-chip" onClick={run}>
        {t("fuzzy.replay.run")}
      </button>

      {status === "loading" && <p className="status">{t("trends.loading")}</p>}
      {status === "error" && (
        <p className="status status-error">{t("trends.error", { reason: errorReason })}</p>
      )}
      {status === "ready" && result !== null && (
        <>
          {document.inputs.map((variable) => (
            <InputPane key={variable.id} variable={variable} replay={result} t={t} />
          ))}
          {document.outputs.map((variable) => (
            <OutputPane key={variable.id} variable={variable} replay={result} t={t} />
          ))}
        </>
      )}
    </>
  );
}
