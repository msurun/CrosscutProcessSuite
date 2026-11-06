// frontend/src/components/policy/PolicyDiffView.tsx
/**
 * Textual diff between two policy documents (ADR 013). Every change is badged loosening (widens
 * write authority) or tightening, with its explanation filled in from the changed values.
 * Also lists changed extra properties and the global mode change.
 */

import type { Translate } from "../../findings";
import {
  diffPolicies,
  riskSummary,
  type FieldChange,
  type PolicyDiff,
  type PolicyDocument,
  type TargetDiff,
} from "../../policyModel";

export interface PolicyDiffViewProps {
  liveDoc: PolicyDocument | null;
  draftDoc: PolicyDocument | null;
  t: Translate;
}

/** Shows a value in the diff; absent values appear as a dash. */
function formatValue(value: unknown): string {
  if (value === undefined || value === null) return "-";
  if (typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function ChangeBadge({ loosening, t }: { loosening: boolean; t: Translate }) {
  const chipClass = loosening ? "status-chip status-chip--problem" : "status-chip status-chip--ok";
  const labelKey = loosening ? "policy.diff.loosening" : "policy.diff.tightening";
  return (
    <span className={chipClass} data-testid={loosening ? "badge-loosening" : "badge-tightening"}>
      [{t(labelKey)}]
    </span>
  );
}

function riskSummaryKey(level: "high" | "medium" | "low" | "none"): string {
  if (level === "high") return "policy.diff.riskHigh";
  if (level === "medium") return "policy.diff.riskMedium";
  if (level === "low") return "policy.diff.riskLow";
  return "policy.diff.riskNone";
}

function RiskBanner({ diff, t }: { diff: PolicyDiff; t: Translate }) {
  const summary = riskSummary(diff);
  const kind = summary.level === "high" ? "problem" : summary.level === "medium" ? "warning" : "ok";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
      <span className={`status-chip status-chip--${kind}`} data-testid="risk-summary-chip">
        {t(riskSummaryKey(summary.level))}
      </span>
      <span className="hint" data-testid="risk-summary-counts">
        {t("policy.diff.counts", { loosening: summary.looseningCount, tightening: summary.tighteningCount })}
      </span>
    </div>
  );
}

function ChangeLine({ change, showBadge, t }: { change: FieldChange; showBadge: boolean; t: Translate }) {
  return (
    <>
      {showBadge && <><ChangeBadge loosening={change.loosening} t={t} />{" "}</>}
      <strong>{change.field}</strong>: {formatValue(change.oldValue)} &rarr; {formatValue(change.newValue)}{" "}
      <span className="hint">({t(change.explanation, change.params)})</span>
    </>
  );
}

function DiffItemRow({ change, t }: { change: FieldChange; t: Translate }) {
  return (
    <li data-testid={`diff-field-${change.field}`} style={{ margin: "4px 0" }}>
      <ChangeLine change={change} showBadge={true} t={t} />
    </li>
  );
}

function TargetDiffItem({ target, t }: { target: TargetDiff; t: Translate }) {
  if (target.status === "unchanged") return null;
  const wholeTarget = target.status === "added" || target.status === "removed";
  return (
    <li data-testid={`diff-target-${target.tag}`} style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <strong>{t("policy.diff.target", { tag: target.tag })}</strong> ({t(`policy.diff.status.${target.status}`)})
        {wholeTarget && <ChangeBadge loosening={target.loosening} t={t} />}
      </div>
      <ul style={{ listStyleType: "none", paddingLeft: 16 }}>
        {target.changes.map((c) => (
          wholeTarget
            ? <li key={c.field} className="hint">{t(c.explanation, c.params)}</li>
            : <DiffItemRow key={c.field} change={c} t={t} />
        ))}
      </ul>
    </li>
  );
}

function ModeChangeSection({ change, t }: { change: FieldChange; t: Translate }) {
  return (
    <div style={{ marginBottom: 8 }} data-testid="diff-mode-change">
      <ChangeBadge loosening={change.loosening} t={t} />{" "}
      <strong>{t("policy.diff.mode")}</strong>: {String(change.oldValue)} &rarr; {String(change.newValue)}{" "}
      <span className="hint">({t(change.explanation, change.params)})</span>
    </div>
  );
}

function ExtraChanges({ changes, t }: { changes: FieldChange[]; t: Translate }) {
  if (changes.length === 0) return null;
  return (
    <ul style={{ listStyleType: "none", paddingLeft: 0 }} data-testid="diff-extra-changes">
      {changes.map((c) => (
        <li key={c.field} data-testid={`diff-extra-${c.field}`} style={{ margin: "4px 0" }}>
          <ChangeLine change={c} showBadge={false} t={t} />
        </li>
      ))}
    </ul>
  );
}

function DiffTargetsList({ targets, t }: { targets: TargetDiff[]; t: Translate }) {
  return (
    <ul style={{ listStyleType: "none", paddingLeft: 0 }}>
      {targets.map((td) => (
        <TargetDiffItem key={td.tag} target={td} t={t} />
      ))}
    </ul>
  );
}

export function PolicyDiffView({ liveDoc, draftDoc, t }: PolicyDiffViewProps) {
  const diff = diffPolicies(liveDoc, draftDoc);
  if (!diff.hasChanges) {
    return (
      <div className="notice" data-testid="policy-diff-no-changes">
        <p>{t("policy.diff.noChanges")}</p>
      </div>
    );
  }

  return (
    <div className="diff-view" data-testid="policy-diff-container">
      <RiskBanner diff={diff} t={t} />
      {diff.modeChange && <ModeChangeSection change={diff.modeChange} t={t} />}
      <DiffTargetsList targets={diff.targetDiffs} t={t} />
      <ExtraChanges changes={diff.extraFieldChanges} t={t} />
    </div>
  );
}
