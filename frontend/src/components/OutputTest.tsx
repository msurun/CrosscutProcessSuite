// Explicit human confirmation of a bounded manual-output test (ADR 017).
// All plant writes and restoration decisions remain in the Write Gateway.
import { useEffect, useState } from "react";
import { apiFetch } from "../http";
import type { Translate } from "../findings";

interface TestValues { target: string; amplitude: string; duration: string }
const EMPTY_VALUES: TestValues = { target: "", amplitude: "", duration: "" };
const STATUS_INTERVAL_MS = 1000; // One second between gateway status reads.

/** Observe automatic aborts independently of the browser that confirmed the test. */
async function readStatus(target: string): Promise<string> {
  const response = await apiFetch("/api/gateway/status");
  if (!response.ok) return "status_unavailable_check_DCS";
  const result = await response.json() as { targets: Record<string, string> };
  return result.targets[target] ?? "status_unavailable_check_DCS";
}

/** Stop polling on unmount so an obsolete response cannot update another target. */
function useOutputStatus(target: string, update: (status: string) => void) {
  useEffect(() => {
    if (!target) return;
    let disposed = false;
    const timer = window.setInterval(() => {
      readStatus(target).then((status) => { if (!disposed) update(status); })
        .catch(() => { if (!disposed) update("status_unavailable_check_DCS"); });
    }, STATUS_INTERVAL_MS);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [target, update]);
}

/** Send a command through the shared authenticated and CSRF-protected client. */
async function sendCommand(values: TestValues, cancel: boolean): Promise<string> {
  const path = cancel ? `/${encodeURIComponent(values.target)}/cancel` : "";
  const body = cancel ? {} : {
    target: values.target, amplitude: Number(values.amplitude), duration_s: Number(values.duration),
  };
  const response = await apiFetch(`/api/gateway/output-tests${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const result = await response.json() as { reason_code?: string; detail?: string };
  if (!response.ok) throw new Error(result.detail ?? String(response.status));
  return result.reason_code ?? "restore_requested";
}

/** Keep the confirmation disabled while a command is in flight. */
function useOutputCommand(values: TestValues) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [watchedTarget, setWatchedTarget] = useState("");
  useOutputStatus(watchedTarget, setStatus);
  async function run(cancel: boolean) {
    setBusy(true);
    try {
      setStatus(await sendCommand(values, cancel));
      setWatchedTarget(values.target);
    }
    catch (failure) { setStatus(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  }
  return { busy, status, run };
}

/** Label every input, and show units before asking for confirmation. */
function TestFields({ values, setValues, t }: {
  values: TestValues; setValues: (values: TestValues) => void; t: Translate;
}) {
  return <>{(["target", "amplitude", "duration"] as const).map((field) => (
    <label key={field} className="field">{t(`outTest.${field}`)}
      <input value={values[field]} type={field === "target" ? "text" : "number"}
        step="any" min={field === "duration" ? "0.001" : undefined}
        onChange={(event) => setValues({ ...values, [field]: event.target.value })} />
    </label>
  ))}</>;
}

/** A deliberate confirmation with an always-available cancel/restore action. */
function TestActions({ values, command, t }: {
  values: TestValues; command: ReturnType<typeof useOutputCommand>; t: Translate;
}) {
  const valid = Object.values(values).every((value) => value.trim() !== "") &&
    Number(values.amplitude) !== 0 && Number(values.duration) > 0;
  return <div className="toolbar">
    <button disabled={command.busy || !valid} onClick={() => void command.run(false)}>
      {t("outTest.confirm")}
    </button>
    <button disabled={command.busy || !values.target} onClick={() => void command.run(true)}>
      {t("outTest.cancel")}
    </button>
  </div>;
}

/** Render a separate live-write section alongside historical step analysis. */
export function OutputTest({ t }: { t: Translate }) {
  const [values, setValues] = useState(EMPTY_VALUES);
  const command = useOutputCommand(values);
  return <section aria-label={t("outTest.title")}>
    <h3>{t("outTest.title")}</h3>
    <p>{t("outTest.notice")}</p>
    <TestFields values={values} setValues={setValues} t={t} />
    <TestActions values={values} command={command} t={t} />
    <p role="status">{command.status && t("outTest.result", { reason: command.status })}</p>
  </section>;
}
