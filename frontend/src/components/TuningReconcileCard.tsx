// frontend/src/components/TuningReconcileCard.tsx
// Card displayed in the Tuning view when a loop is blocked by an unclosed parameter write intent.
// Displays intended vs current DCS values and provides a resolve action requiring gw.approve.tuning and step-up.

import { useState } from "react";
import { useCan } from "../AuthContext";
import type { Translate } from "../findings";
import {
  type ParamIntentRecord,
  type ParamIntentTarget,
  resolveOpenIntent,
} from "../tuningApi";
import { errorText } from "../tuningRules";
import { DisabledReason } from "./DisabledReason";

export interface TuningReconcileCardProps {
  intent: ParamIntentRecord;
  onResolved?: () => void;
  t: Translate;
}

/** Formats the current DCS read or shows the fallback label when unreadable. */
function CurrentValueCell({ value, unknownText }: { value: number | null; unknownText: string }) {
  if (value === null) {
    return <span className="hint">{unknownText}</span>;
  }
  return <span>{value}</span>;
}

/** Table listing intended vs current DCS values for each parameter target. */
function TargetsTable({ targets, t }: { targets: ParamIntentTarget[]; t: Translate }) {
  const unknownLabel = t("tuning.reconcile.unknown");
  return (
    <table className="data-table" data-testid="reconcile-targets-table" style={{ width: "100%", marginTop: 8 }}>
      <thead>
        <tr>
          <th>{t("tuning.reconcile.target")}</th>
          <th>{t("tuning.reconcile.intended")}</th>
          <th>{t("tuning.reconcile.current")}</th>
        </tr>
      </thead>
      <tbody>
        {targets.map((item) => (
          <tr key={item.target} data-testid={`reconcile-row-${item.target}`}>
            <td><code>{item.target}</code></td>
            <td data-testid={`reconcile-intended-${item.target}`}>{item.to_value}</td>
            <td data-testid={`reconcile-current-${item.target}`}>
              <CurrentValueCell value={item.current_value} unknownText={unknownLabel} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Renders error or success notices for the resolve action. */
function ActionMessage({ error, success }: { error: string; success: string }) {
  if (error !== "") {
    return (
      <p className="notice notice-warning" role="alert" data-testid="reconcile-error">
        {error}
      </p>
    );
  }
  if (success !== "") {
    return (
      <p className="notice notice-ok" role="status" data-testid="reconcile-success">
        {success}
      </p>
    );
  }
  return null;
}

/** Button invoking intent resolution wrapped in authority check. */
function ResolveButton({
  busy,
  allowed,
  reason,
  onClick,
  t,
}: {
  busy: boolean;
  allowed: boolean;
  reason: string;
  onClick: () => void;
  t: Translate;
}) {
  return (
    <DisabledReason disabled={!allowed || busy} reason={reason}>
      <button
        type="button"
        data-testid="reconcile-resolve"
        disabled={!allowed || busy}
        onClick={onClick}
      >
        {busy ? t("tuning.reconcile.resolving") : t("tuning.reconcile.resolve")}
      </button>
    </DisabledReason>
  );
}

/**
 * Reconcile card shown when a loop is blocked by an unresolved write intent (reconcile_required).
 * In plain words:
 * The operator sees what the gateway tried to write and what the DCS currently holds.
 * Once verified against the physical plant, the operator resolves the intent behind password step-up.
 */
export function TuningReconcileCard({ intent, onResolved, t }: TuningReconcileCardProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const can = useCan("gw.approve.tuning");

  const handleResolve = async () => {
    setBusy(true);
    setError("");
    try {
      await resolveOpenIntent(intent.key);
      setSuccess(t("tuning.reconcile.success"));
      onResolved?.();
    } catch (err: unknown) {
      setError(errorText(err, t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="panel panel-warning"
      data-testid="tuning-reconcile-card"
      aria-labelledby={`reconcile-title-${intent.key}`}
      style={{ borderLeft: "4px solid var(--color-warning, #e67e22)", padding: 16 }}
    >
      <h3 id={`reconcile-title-${intent.key}`}>{t("tuning.reconcile.title")}: {intent.loop_id}</h3>
      <p className="hint">{t("tuning.reconcile.subtitle")}</p>
      <TargetsTable targets={intent.targets} t={t} />
      <ActionMessage error={error} success={success} />
      <div className="toolbar" style={{ marginTop: 12 }}>
        <ResolveButton
          busy={busy}
          allowed={can.allowed}
          reason={can.reason}
          onClick={() => void handleResolve()}
          t={t}
        />
      </div>
    </section>
  );
}
