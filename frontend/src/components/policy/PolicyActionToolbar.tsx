// frontend/src/components/policy/PolicyActionToolbar.tsx
/**
 * Action toolbar for the Write Policy editor: mode selection, diff review confirmation and the
 * Save/Pin/Reload/Discard buttons. It only renders: what is allowed (and why not) is decided by
 * policyRules.ts and passed in as CanResult values.
 */

import type { CanResult } from "../../AuthContext";
import { DisabledReason } from "../DisabledReason";
import type { Translate } from "../../findings";
import { POLICY_MODES, type GatewayOperatingMode } from "../../policyModel";

export interface PolicyActionToolbarProps {
  mode: GatewayOperatingMode;
  onModeChange: (m: GatewayOperatingMode) => void;
  reviewed: boolean;
  onReviewedChange: (v: boolean) => void;
  /** Digest of the saved server draft that the review tick refers to (null: no draft). */
  digest: string | null;
  save: CanResult;
  pin: CanResult;
  reload: CanResult;
  onSave: () => void;
  onPin: () => void;
  onReload: () => void;
  onDiscard: () => void;
  t: Translate;
}

function ModeSelect({ mode, onChange, t }: { mode: GatewayOperatingMode; onChange: (m: GatewayOperatingMode) => void; t: Translate }) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span>{t("policy.draft.globalMode")}:</span>
      <select value={mode} onChange={(e) => onChange(e.target.value as GatewayOperatingMode)} data-testid="policy-mode-select">
        {POLICY_MODES.map((m) => (
          <option key={m} value={m}>{t(`gateway.mode.${m}`)}</option>
        ))}
      </select>
    </label>
  );
}

function ReviewCheckbox({ reviewed, onChange, digest, t }: { reviewed: boolean; onChange: (v: boolean) => void; digest: string | null; t: Translate }) {
  const shortDigest = digest ? digest.slice(0, 12) : "-";
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 6, margin: "8px 0" }}>
      <input type="checkbox" checked={reviewed} disabled={digest === null} onChange={(e) => onChange(e.target.checked)} data-testid="policy-review-checkbox" />
      <span>{t("policy.actions.reviewCheckbox", { digest: shortDigest })}</span>
    </label>
  );
}

function GatedButton({ can, onClick, testId, label, t }: { can: CanResult; onClick: () => void; testId: string; label: string; t: Translate }) {
  return (
    <DisabledReason disabled={!can.allowed} reason={can.reason} requiredRole={can.requiredRole} t={t}>
      <button type="button" onClick={onClick} data-testid={testId}>{label}</button>
    </DisabledReason>
  );
}

export function PolicyActionToolbar(props: PolicyActionToolbarProps) {
  const { t } = props;
  return (
    <div className="toolbar" style={{ flexWrap: "wrap", gap: 12, marginTop: 12 }} data-testid="policy-action-toolbar">
      <ModeSelect mode={props.mode} onChange={props.onModeChange} t={t} />
      <ReviewCheckbox reviewed={props.reviewed} onChange={props.onReviewedChange} digest={props.digest} t={t} />
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <GatedButton can={props.save} onClick={props.onSave} testId="policy-save-button" label={t("policy.actions.saveDraft")} t={t} />
        <GatedButton can={props.pin} onClick={props.onPin} testId="policy-pin-button" label={t("policy.actions.pin")} t={t} />
        <GatedButton can={props.reload} onClick={props.onReload} testId="policy-reload-button" label={t("policy.actions.reload")} t={t} />
        <button type="button" onClick={props.onDiscard} data-testid="policy-discard-button">{t("policy.actions.discard")}</button>
      </div>
    </div>
  );
}
