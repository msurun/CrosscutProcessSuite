// frontend/src/components/TuningProposeButton.tsx
/**
 * "Propose write to DCS" on the Loops tuning view (ADR 014). It only creates a proposal: a second
 * person must approve it in the Tuning view before the gateway writes anything. The button needs
 * gw.propose, a running loop_kpi job for the loop (the live values are read through its
 * connector) and a reachable gateway that is not off; otherwise it is disabled with the reason.
 */

import { useEffect, useState } from "react";
import { fetchRuntimeJobs, fetchRuntimeStatus, type VendorKey } from "../api";
import { useCan } from "../AuthContext";
import type { Translate } from "../findings";
import { fetchGatewayStatus } from "../gatewayApi";
import { formatHash } from "../route";
import { createTuningProposal, type ProposeBody, type TuningMethod, type TuningProposal } from "../tuningApi";
import { baseStatus, codeMessage, errorText, statusDetail } from "../tuningRules";
import { DisabledReason } from "./DisabledReason";
import { ModalDialog } from "./ModalDialog";

const BAD_JOB_STATES = ["error", "unsupported"];
const VENDOR_FORMS: readonly VendorKey[] = ["siemens_pid_compact", "abb_pidcc"];
const METHODS: readonly TuningMethod[] = ["simc", "amigo", "amigo_pid"];

/** Why the proposal cannot be made now; "ok" when it can and "loading" before the first answer. */
export type Readiness = "loading" | "ok" | "noJob" | "noGateway" | "gatewayOff";

async function jobIsLive(loop: string): Promise<boolean> {
  try {
    const [status, doc] = await Promise.all([fetchRuntimeStatus(), fetchRuntimeJobs()]);
    const state = new Map(status.jobs.map((job) => [job.id, job.status]));
    return (
      status.service.running &&
      doc.jobs.some(
        (job) =>
          job.kind === "loop_kpi" &&
          job.enabled &&
          (job.loops ?? []).includes(loop) &&
          !BAD_JOB_STATES.includes(state.get(job.id) ?? ""),
      )
    );
  } catch {
    return false;
  }
}

/** Reads the runtime and gateway once and tells whether a proposal for `loop` can be made. */
export function useReadiness(loop: string): Readiness {
  const [value, setValue] = useState<Readiness>("loading");
  useEffect(() => {
    let alive = true;
    void readinessOf(loop).then((next) => {
      if (alive) setValue(next);
    });
    return () => {
      alive = false;
    };
  }, [loop]);
  return value;
}

/** The runtime is asked first, so a loop without a live job never touches the gateway route. */
async function readinessOf(loop: string): Promise<Readiness> {
  if (!(await jobIsLive(loop))) return "noJob";
  const mode = await fetchGatewayStatus().then(
    (status) => status.mode,
    () => null,
  );
  if (mode === null) return "noGateway";
  return mode === "off" ? "gatewayOff" : "ok";
}

export interface ProposeContext {
  datasetId: string;
  loopName: string;
  /** Vendor form already chosen for the loop (knowledge), or null/undefined to ask. */
  vendor: VendorKey | null | undefined;
  window: { start_s: number; end_s: number };
  robustness: number;
}

interface Form {
  vendor: string;
  method: TuningMethod;
  reason: string;
}

function bodyOf(ctx: ProposeContext, form: Form): ProposeBody {
  return {
    vendor_form: form.vendor,
    method: form.method,
    reason: form.reason.trim(),
    dataset_id: ctx.datasetId,
    start_s: ctx.window.start_s,
    end_s: ctx.window.end_s,
    robustness: ctx.robustness,
  };
}

function Result({ proposal, datasetId, t }: { proposal: TuningProposal; datasetId: string; t: Translate }) {
  const refused = baseStatus(proposal.status) === "refused";
  const href = formatHash({ dataset: datasetId, view: "tuning", loop: null, sub: "detail" });
  return (
    <div className={refused ? "notice notice-warning" : "notice"} role="status" data-testid="tuning-propose-result">
      <p>
        {refused
          ? t("tuning.propose.refused", { reason: codeMessage(statusDetail(proposal.status), t) })
          : t("tuning.propose.created")}
      </p>
      <a href={href} data-testid="tuning-propose-link">
        {t("tuning.propose.open")}
      </a>
    </div>
  );
}

function VendorField({
  form,
  implied,
  onChange,
  t,
}: {
  form: Form;
  implied: VendorKey | null;
  onChange: (patch: Partial<Form>) => void;
  t: Translate;
}) {
  if (implied !== null) return <p className="hint">{t("tuning.propose.vendorImplied", { form: implied })}</p>;
  return (
    <label>
      {t("tuning.propose.vendor")}
      <select value={form.vendor} data-testid="tuning-propose-vendor" onChange={(e) => onChange({ vendor: e.target.value })}>
        {VENDOR_FORMS.map((key) => (
          <option key={key} value={key}>
            {key}
          </option>
        ))}
      </select>
    </label>
  );
}

function ProposeFields({
  form,
  implied,
  onChange,
  t,
}: {
  form: Form;
  implied: VendorKey | null;
  onChange: (patch: Partial<Form>) => void;
  t: Translate;
}) {
  return (
    <>
      <VendorField form={form} implied={implied} onChange={onChange} t={t} />
      <label>
        {t("tuning.propose.method")}
        <select value={form.method} data-testid="tuning-propose-method"
          onChange={(e) => onChange({ method: e.target.value as TuningMethod })}>
          {METHODS.map((method) => (
            <option key={method} value={method}>
              {method}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("tuning.propose.reasonLabel")}
        <input type="text" maxLength={1000} value={form.reason} data-testid="tuning-propose-reason"
          onChange={(e) => onChange({ reason: e.target.value })} />
      </label>
    </>
  );
}

function ProposeDialog({ ctx, onClose, t }: { ctx: ProposeContext; onClose: () => void; t: Translate }) {
  const implied = ctx.vendor ?? null;
  const [form, setForm] = useState<Form>({ vendor: implied ?? VENDOR_FORMS[0], method: "simc", reason: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<TuningProposal | null>(null);
  const submit = (): void => {
    setBusy(true);
    setError("");
    createTuningProposal(ctx.loopName, bodyOf(ctx, form))
      .then(setResult)
      .catch((failure: unknown) => setError(errorText(failure, t)))
      .finally(() => setBusy(false));
  };
  return (
    <ModalDialog title={t("tuning.propose.title")} onClose={onClose} busy={busy} testId="tuning-propose-dialog">
      <p>{t("tuning.propose.text")}</p>
      <ProposeFields form={form} implied={implied} onChange={(patch) => setForm({ ...form, ...patch })} t={t} />
      {error !== "" && (
        <p className="notice notice-warning" role="alert" data-testid="tuning-propose-error">
          {error}
        </p>
      )}
      {result !== null && <Result proposal={result} datasetId={ctx.datasetId} t={t} />}
      <div className="toolbar" style={{ marginTop: 12 }}>
        <DisabledReason disabled={busy || form.reason.trim() === "" || result !== null} reason={t("tuning.propose.needReason")}>
          <button type="button" data-testid="tuning-propose-submit" onClick={submit}>
            {t("tuning.propose.submit")}
          </button>
        </DisabledReason>
        <button type="button" onClick={onClose}>
          {t(result === null ? "tuning.proposals.cancel" : "tuning.propose.close")}
        </button>
      </div>
    </ModalDialog>
  );
}

function reasonOf(can: ReturnType<typeof useCan>, ready: Readiness, t: Translate): string {
  if (!can.allowed) return can.reason;
  if (ready === "noJob") return t("tuning.propose.reason.noJob");
  if (ready === "noGateway") return t("tuning.propose.reason.noGateway");
  if (ready === "gatewayOff") return t("tuning.propose.reason.gatewayOff");
  return ready === "loading" ? t("tuning.propose.reason.loading") : "";
}

/** The button that opens the propose dialog (disabled with the reason while it cannot be used). */
export function TuningProposeButton({ ctx, t }: { ctx: ProposeContext; t: Translate }) {
  const can = useCan("gw.propose");
  const ready = useReadiness(ctx.loopName);
  const [open, setOpen] = useState(false);
  const reason = reasonOf(can, ready, t);
  return (
    <div data-testid="tuning-propose">
      <DisabledReason disabled={reason !== ""} reason={reason} requiredRole={can.requiredRole} t={t}>
        <button type="button" data-testid="tuning-propose-button" onClick={() => setOpen(true)}>
          {t("tuning.propose.button")}
        </button>
      </DisabledReason>
      {open && <ProposeDialog ctx={ctx} onClose={() => setOpen(false)} t={t} />}
    </div>
  );
}
