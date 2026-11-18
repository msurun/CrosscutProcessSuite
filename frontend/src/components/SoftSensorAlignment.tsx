// Scan the physical delay between laboratory samples and a user-selected online signal.
// Keep the profile visible so a weak or ambiguous optimum is apparent before choosing a delay.
import { useState, type FormEvent } from "react";
import { scanAlignment, type AlignmentRequest, type AlignmentResult } from "../alignmentApi";
import type { Translate } from "../findings";
import { describeSoftError } from "./SoftSensorState";

// Seconds; a broad initial range is editable because plant residence times vary.
const DEFAULT_RANGE = { min_delay_s: -3600, max_delay_s: 3600, step_s: 60 };
const RANGE_FIELDS = ["min_delay_s", "max_delay_s", "step_s"] as const;
interface PanelProps { datasetId: string; sensorId: string; t: Translate }
interface RangeProps { request: AlignmentRequest; change: (value: AlignmentRequest) => void; t: Translate }

/** Numeric range fields use seconds, matching the API and catalogue. */
function DelayRange({ request, change, t }: RangeProps) {
  return <>{RANGE_FIELDS.map((field) => (
    <label className="field" key={field}>
      <span className="field-label">{t(`soft.alignment.${field}`)}</span>
      <input className="field-input" type="number" required step="any" min={field === "step_s" ? Number.MIN_VALUE : undefined}
        value={request[field]} onChange={(event) => change({ ...request, [field]: event.target.valueAsNumber })} />
    </label>
  ))}</>;
}

/** Table retains every candidate score, including unavailable correlations. */
function AlignmentProfile({ result, t }: { result: AlignmentResult; t: Translate }) {
  return <details><summary>{t("soft.alignment.profile")}</summary>
    <table><caption>{t("soft.alignment.profile")}</caption>
      <thead><tr><th scope="col">{t("soft.alignment.delay")}</th><th scope="col">{t("soft.alignment.correlation")}</th></tr></thead>
      <tbody>{result.profile.map((point) => <tr key={point.delay_s}>
        <td>{point.delay_s}</td><td>{point.correlation?.toFixed(3) ?? "—"}</td>
      </tr>)}</tbody>
    </table>
  </details>;
}

/** Display the optimum together with its uncertainty rather than a shift alone. */
function AlignmentSummary({ result, t }: { result: AlignmentResult; t: Translate }) {
  return <div data-testid="alignment-result">
    <p role="status">{t("soft.alignment.result", { best: result.best_delay_s, low: result.interval_low_s, high: result.interval_high_s })}</p>
    <p>{t("soft.alignment.method", { method: result.method })}</p>
    <AlignmentProfile result={result} t={t} />
  </div>;
}

/** Run a scan and expose progress, result and specific server errors. */
function useAlignmentScan(props: PanelProps) {
  const [request, change] = useState<AlignmentRequest>({ reference_tag: "", ...DEFAULT_RANGE });
  const [result, setResult] = useState<AlignmentResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setError(null); setResult(null);
    scanAlignment(props.datasetId, props.sensorId, request).then(setResult)
      .catch((failure: unknown) => setError(describeSoftError(failure, props.t)))
      .finally(() => setBusy(false));
  };
  return { request, change, result, error, busy, submit };
}

/** Alignment panel on the lab page; scans never overwrite configuration. */
export function SoftSensorAlignment(props: PanelProps) {
  const state = useAlignmentScan(props);
  const { t } = props;
  return <section aria-label={t("soft.alignment.title")}>
    <h3>{t("soft.alignment.title")}</h3><p className="hint">{t("soft.alignment.hint")}</p>
    <form onSubmit={state.submit}>
      <label className="field"><span className="field-label">{t("soft.alignment.reference")}</span>
        <input className="field-input" required value={state.request.reference_tag}
          onChange={(event) => state.change({ ...state.request, reference_tag: event.target.value })} />
      </label>
      <DelayRange request={state.request} change={state.change} t={t} />
      <button type="submit" disabled={state.busy || !state.request.reference_tag.trim()}>{t(state.busy ? "soft.alignment.scanning" : "soft.alignment.scan")}</button>
    </form>
    {state.error !== null && <p role="alert" className="status status-error">{state.error}</p>}
    {state.result !== null && <AlignmentSummary result={state.result} t={t} />}
  </section>;
}
