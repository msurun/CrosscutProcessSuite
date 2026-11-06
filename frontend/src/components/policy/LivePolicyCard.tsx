// frontend/src/components/policy/LivePolicyCard.tsx
/**
 * Read-only display of the active Write Gateway pinned policy (ADR 013, issues #46/#47).
 * Displays cryptographic SHA-256 digest, author, approver, approval timestamp,
 * operating mode cap, and engineering boundaries for all protected targets.
 */

import type { Translate } from "../../findings";
import type { LivePolicyResponse } from "../../policyApi";
import type { TargetPolicy } from "../../policyModel";

export interface LivePolicyCardProps {
  livePolicy: LivePolicyResponse | null;
  t: Translate;
}

function ExtraPropsView({ doc, t }: { doc: Record<string, unknown>; t: Translate }) {
  const reserved = new Set(["version", "mode", "targets"]);
  const extraKeys = Object.keys(doc).filter((k) => !reserved.has(k));
  if (extraKeys.length === 0) return null;
  const formatted = extraKeys.map((k) => `${k}: ${JSON.stringify(doc[k])}`).join(", ");
  return (
    <p className="hint" data-testid="live-extra-properties">
      {t("policy.live.extraProperties", { properties: formatted })}
    </p>
  );
}

function LiveTargetRow({ tag, policy }: { tag: string; policy: TargetPolicy }) {
  const limits = `[${policy.limits[0]}, ${policy.limits[1]}]`;
  const modes = policy.allowed_loop_modes.join(", ");
  return (
    <tr data-testid={`live-target-${tag}`}>
      <td><strong>{tag}</strong></td>
      <td>{limits}</td>
      <td>{policy.max_step}</td>
      <td>{policy.max_rate_per_s}</td>
      <td>{policy.min_interval_s}</td>
      <td>{modes}</td>
      <td>{policy.hold_off_s}</td>
      <td>{policy.watchdog_s}</td>
      <td>{policy.readback_tolerance}</td>
    </tr>
  );
}

function LiveTableHeader({ t }: { t: Translate }) {
  return (
    <thead>
      <tr>
        <th>{t("policy.draft.tag")}</th>
        <th>{t("policy.draft.limits")}</th>
        <th>{t("policy.draft.maxStep")}</th>
        <th>{t("policy.draft.maxRate")}</th>
        <th>{t("policy.draft.minInterval")}</th>
        <th>{t("policy.draft.allowedModes")}</th>
        <th>{t("policy.draft.holdOff")}</th>
        <th>{t("policy.draft.watchdog")}</th>
        <th>{t("policy.draft.readbackTol")}</th>
      </tr>
    </thead>
  );
}

function LiveTargetsTable({ targets, t }: { targets: Record<string, TargetPolicy>; t: Translate }) {
  const entries = Object.entries(targets);
  if (entries.length === 0) {
    return <p className="hint" data-testid="live-zero-targets">{t("policy.draft.zeroTargetsWarning")}</p>;
  }
  return (
    <div className="table-scroll">
      <table className="loops-table" data-testid="live-targets-table">
        <LiveTableHeader t={t} />
        <tbody>
          {entries.map(([tag, pol]) => (
            <LiveTargetRow key={tag} tag={tag} policy={pol} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LivePinMeta({ live, pin, t }: { live: LivePolicyResponse; pin: NonNullable<LivePolicyResponse["pin"]>; t: Translate }) {
  const fileDigest = live.file_digest ?? pin.digest;
  return (
    <div className="toolbar" style={{ flexWrap: "wrap", gap: 12 }} data-testid="live-pin-meta">
      {live.digest && (
        <span className="status-chip status-chip--ok" data-testid="live-digest">
          {t("policy.live.digest", { digest: live.digest })}
        </span>
      )}
      <span data-testid="live-file-digest">{t("policy.live.fileDigest", { digest: fileDigest })}</span>
      <span>{t("policy.live.author", { author: pin.author })}</span>
      <span>{t("policy.live.approver", { approver: pin.approver })}</span>
      <span>{t("policy.live.approvedAt", { time: pin.approved_at })}</span>
    </div>
  );
}

function LiveEmptyBanner({ t }: { t: Translate }) {
  return (
    <section className="banner" data-testid="live-policy-empty">
      <h5>{t("policy.live.title")}</h5>
      <p className="hint">{t("policy.live.empty")}</p>
    </section>
  );
}

function LiveCardHeader({ mode, t }: { mode: string; t: Translate }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
      <h5>{t("policy.live.title")}</h5>
      <span className="status-chip status-chip--ok" data-testid="live-mode-cap">
        {t("policy.live.modeCap", { mode })}
      </span>
    </div>
  );
}

export function LivePolicyCard({ livePolicy, t }: LivePolicyCardProps) {
  const doc = livePolicy?.document;
  const pin = livePolicy?.pin;
  if (!doc || !pin) return <LiveEmptyBanner t={t} />;

  return (
    <section className="banner" data-testid="live-policy-card">
      <LiveCardHeader mode={livePolicy.mode_cap ?? doc.mode} t={t} />
      <LivePinMeta live={livePolicy} pin={pin} t={t} />
      <ExtraPropsView doc={doc} t={t} />
      <LiveTargetsTable targets={doc.targets} t={t} />
    </section>
  );
}
