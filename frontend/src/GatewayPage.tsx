// frontend/src/GatewayPage.tsx
/**
 * Write Gateway console view (Phase 2, #46).
 * Manages operating modes, target re-enabling, confirm-mode proposal approvals,
 * emergency kill-switch activation, and cryptographic audit log inspection.
 */

import { useCallback, useEffect, useState } from "react";
import { useCan, useCanCheck, type CanResult } from "./AuthContext";
import { DisabledReason } from "./components/DisabledReason";
import type { Translate } from "./findings";
import { PolicyPanel } from "./PolicyPanel";
import { MODE_ORDER, ONE_STEP_REASON, modeTransition, reEnablePermission } from "./gatewayRules";
import {
  approveProposal,
  fetchGatewayAudit,
  fetchGatewayPending,
  fetchGatewayStatus,
  killGateway,
  reEnableTarget,
  rejectProposal,
  setGatewayMode,
  type GatewayAuditResponse,
  type GatewayProposal,
  type GatewayStatus,
} from "./gatewayApi";

export interface GatewayPageProps {
  t: Translate;
}

export function targetStateChipClass(state: string): string {
  if (state === "enabled") return "status-chip status-chip--ok";
  if (state === "killed" || state.startsWith("stopped:")) return "status-chip status-chip--problem";
  if (state === "hold_off") return "status-chip status-chip--warning";
  return "status-chip status-chip--unused";
}

export function modeChipClass(mode: string): string {
  if (mode === "supervised") return "status-chip status-chip--problem";
  if (mode === "confirm") return "status-chip status-chip--warning";
  if (mode === "advisory" || mode === "dry_run") return "status-chip status-chip--ok";
  return "status-chip status-chip--unused";
}

function ErrorMessage({ error, t }: { error: string; t: Translate }) {
  return (
    <div className="notice notice-warning" role="alert" data-testid="gateway-error">
      <p>{t("gateway.error", { reason: error })}</p>
    </div>
  );
}

function ModeConfirmDialog({ onConfirm, onCancel, t }: { onConfirm: () => void; onCancel: () => void; t: Translate }) {
  return (
    <div className="notice notice-warning" role="alert" data-testid="supervised-confirm-dialog">
      <h4>{t("gateway.mode.confirmSupervisedTitle")}</h4>
      <p>{t("gateway.mode.confirmSupervisedText")}</p>
      <div className="toolbar" style={{ marginTop: 8 }}>
        <button type="button" data-testid="supervised-confirm-ok" onClick={onConfirm}>
          {t("gateway.mode.confirmButton")}
        </button>
        <button type="button" onClick={onCancel}>
          {t("gateway.mode.cancelButton")}
        </button>
      </div>
    </div>
  );
}

function KillConfirmDialog({ onConfirm, onCancel, t }: { onConfirm: () => void; onCancel: () => void; t: Translate }) {
  return (
    <div className="notice notice-warning" role="alert" data-testid="kill-confirm-dialog">
      <h4>{t("gateway.kill.confirmTitle")}</h4>
      <p>{t("gateway.kill.confirmText")}</p>
      <div className="toolbar" style={{ marginTop: 8 }}>
        <button type="button" data-testid="kill-confirm-ok" onClick={onConfirm} style={{ color: "var(--status-problem)" }}>
          {t("gateway.kill.confirmButton")}
        </button>
        <button type="button" onClick={onCancel}>
          {t("gateway.mode.cancelButton")}
        </button>
      </div>
    </div>
  );
}

/** Text that explains why a mode option is disabled (empty when it is selectable). */
function modeReasonText(result: CanResult, t: Translate): string {
  if (result.allowed) return "";
  if (result.reason === ONE_STEP_REASON) return t(ONE_STEP_REASON);
  const role = result.requiredRole ? t(`auth.role.${result.requiredRole}`) : "";
  return t(result.reason, { role });
}

function ModeOption({ mode, current, t }: { mode: string; current: string; t: Translate }) {
  const check = useCanCheck();
  const result = modeTransition(current, mode, check);
  const reason = modeReasonText(result, t);
  const label = result.allowed ? t(`gateway.mode.${mode}`) : `${t(`gateway.mode.${mode}`)} (${reason})`;
  return (
    <option value={mode} disabled={!result.allowed} title={reason || undefined} data-testid={`gateway-mode-option-${mode}`}>
      {label}
    </option>
  );
}

function ModeSelector({ mode, onSelect, t }: { mode: string; onSelect: (m: string) => void; t: Translate }) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span>{t("gateway.mode.label")}:</span>
      <select
        value={mode}
        data-testid="gateway-mode-select"
        aria-label={t("gateway.mode.label")}
        onChange={(event) => onSelect(event.target.value)}
      >
        {MODE_ORDER.map((name) => (
          <ModeOption key={name} mode={name} current={mode} t={t} />
        ))}
      </select>
    </label>
  );
}

function ReEnableButton({ tag, state, onReEnable, t }: { tag: string; state: string; onReEnable: (t: string) => void; t: Translate }) {
  const can = useCan(reEnablePermission(state) ?? "gw.re_enable.stopped");
  return (
    <DisabledReason disabled={!can.allowed} reason={can.reason} requiredRole={can.requiredRole} t={t}>
      <button type="button" data-testid={`gateway-reenable-${tag}`} onClick={() => onReEnable(tag)}>
        {t("gateway.targets.reEnable")}
      </button>
    </DisabledReason>
  );
}

function TargetRow({ tag, state, onReEnable, t }: { tag: string; state: string; onReEnable: (t: string) => void; t: Translate }) {
  const canReEnable = reEnablePermission(state) !== null;
  return (
    <tr data-testid={`gateway-target-${tag}`}>
      <td>{tag}</td>
      <td>
        <span className={targetStateChipClass(state)}>{state}</span>
      </td>
      <td>
        {canReEnable && <ReEnableButton tag={tag} state={state} onReEnable={onReEnable} t={t} />}
      </td>
    </tr>
  );
}

function TargetTable({ targets, onReEnable, t }: { targets: Record<string, string>; onReEnable: (t: string) => void; t: Translate }) {
  const entries = Object.entries(targets);
  if (entries.length === 0) return <p className="hint">{t("gateway.targets.empty")}</p>;
  return (
    <div className="table-scroll">
      <table className="loops-table">
        <thead>
          <tr>
            <th>{t("gateway.targets.tag")}</th>
            <th>{t("gateway.targets.state")}</th>
            <th>{t("gateway.targets.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([tag, state]) => (
            <TargetRow key={tag} tag={tag} state={state} onReEnable={onReEnable} t={t} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GatedButton({ permission, testId, label, onClick, t }: { permission: string; testId: string; label: string; onClick: () => void; t: Translate }) {
  const can = useCan(permission);
  return (
    <DisabledReason disabled={!can.allowed} reason={can.reason} requiredRole={can.requiredRole} t={t}>
      <button type="button" data-testid={testId} onClick={onClick}>
        {label}
      </button>
    </DisabledReason>
  );
}

function ProposalRow({
  proposal,
  onApprove,
  onReject,
  t,
}: {
  proposal: GatewayProposal;
  onApprove: (k: string) => void;
  onReject: (k: string) => void;
  t: Translate;
}) {
  return (
    <tr data-testid={`gateway-pending-${proposal.key}`}>
      <td>{proposal.target_tag}</td>
      <td>{proposal.value}</td>
      <td>{proposal.proposer}</td>
      <td>{proposal.reason}</td>
      <td>
        <span className="toolbar">
          <GatedButton permission="gw.approve" testId={`gateway-approve-${proposal.key}`} label={t("gateway.pending.approve")} onClick={() => onApprove(proposal.key)} t={t} />
          <GatedButton permission="gw.reject" testId={`gateway-reject-${proposal.key}`} label={t("gateway.pending.reject")} onClick={() => onReject(proposal.key)} t={t} />
        </span>
      </td>
    </tr>
  );
}

function ProposalTable({
  proposals,
  onApprove,
  onReject,
  t,
}: {
  proposals: GatewayProposal[];
  onApprove: (k: string) => void;
  onReject: (k: string) => void;
  t: Translate;
}) {
  if (proposals.length === 0) return <p className="hint">{t("gateway.pending.empty")}</p>;
  return (
    <div className="table-scroll">
      <table className="loops-table">
        <thead>
          <tr>
            <th>{t("gateway.pending.tag")}</th>
            <th>{t("gateway.pending.value")}</th>
            <th>{t("gateway.pending.proposer")}</th>
            <th>{t("gateway.pending.reason")}</th>
            <th>{t("gateway.pending.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {proposals.map((item) => (
            <ProposalRow key={item.key} proposal={item} onApprove={onApprove} onReject={onReject} t={t} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AuditView({ audit, t }: { audit: GatewayAuditResponse | null; t: Translate }) {
  if (audit === null || audit.records.length === 0) return <p className="hint">{t("gateway.audit.empty")}</p>;
  const records = audit.records.slice(-20);
  return (
    <div className="table-scroll">
      <table className="loops-table">
        <thead>
          <tr>
            <th>{t("gateway.audit.seq")}</th>
            <th>{t("gateway.audit.event")}</th>
            <th>{t("gateway.audit.tag")}</th>
            <th>{t("gateway.audit.value")}</th>
            <th>{t("gateway.audit.reasonCode")}</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r) => (
            <tr key={`${r.seq}-${r.hash}`}>
              <td>{r.seq}</td>
              <td>{r.event}</td>
              <td>{r.tag ?? ""}</td>
              <td>{r.value ?? ""}</td>
              <td>{r.reason_code ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TopControls({
  mode,
  onSelectMode,
  onKillClick,
  refresh,
  t,
}: {
  mode: string;
  onSelectMode: (m: string) => void;
  onKillClick: () => void;
  refresh: () => void;
  t: Translate;
}) {
  return (
    <div className="toolbar" style={{ flexWrap: "wrap", gap: 8 }}>
      <span className={modeChipClass(mode)} role="status" aria-live="polite" data-testid="gateway-mode-chip">
        {mode}
      </span>
      <ModeSelector mode={mode} onSelect={onSelectMode} t={t} />
      <button type="button" onClick={refresh}>
        {t("gateway.refresh")}
      </button>
      <button
        type="button"
        data-testid="gateway-kill-button"
        style={{ color: "var(--status-problem)", borderColor: "var(--status-problem)" }}
        onClick={onKillClick}
      >
        {t("gateway.kill.button")}
      </button>
    </div>
  );
}

export function useGatewayPolling() {
  const [status, setStatus] = useState<GatewayStatus | null>(null);
  const [pending, setPending] = useState<GatewayProposal[]>([]);
  const [audit, setAudit] = useState<GatewayAuditResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const poll = useCallback(async () => {
    try {
      const [s, p, a] = await Promise.all([fetchGatewayStatus(), fetchGatewayPending(), fetchGatewayAudit(50)]);
      setStatus(s);
      setPending(p);
      setAudit(a);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    poll();
    const timer = window.setInterval(poll, 2000);
    return () => window.clearInterval(timer);
  }, [poll]);

  return { status, pending, audit, error, loading, refresh: poll, setError };
}

/** Collapsed by default; the panel (and its requests) exists only while the section is open. */
function PolicySection({ mode, t }: { mode: string | undefined; t: Translate }) {
  const [open, setOpen] = useState(false);
  return (
    <section data-testid="gateway-policy-section">
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h3>{t("policy.section.title")}</h3>
        <button type="button" aria-expanded={open} aria-controls="gateway-policy-body" data-testid="gateway-policy-toggle"
          onClick={() => setOpen(!open)}>
          {open ? t("policy.section.hide") : t("policy.section.show")}
        </button>
      </div>
      <div id="gateway-policy-body">
        {open && <PolicyPanel gatewayMode={mode} t={t} />}
      </div>
    </section>
  );
}

export function GatewayPage({ t }: GatewayPageProps) {
  const { status, pending, audit, error, loading, refresh, setError } = useGatewayPolling();
  const [pendingMode, setPendingMode] = useState<string | null>(null);
  const [showKillConfirm, setShowKillConfirm] = useState(false);

  const handleModeSelect = useCallback(
    (nextMode: string) => {
      if (nextMode === "supervised") {
        setPendingMode("supervised");
        return;
      }
      setGatewayMode(nextMode).then(refresh).catch((err: unknown) => setError(String(err)));
    },
    [refresh, setError],
  );

  const handleConfirmSupervised = useCallback(() => {
    setPendingMode(null);
    setGatewayMode("supervised").then(refresh).catch((err: unknown) => setError(String(err)));
  }, [refresh, setError]);

  const handleConfirmKill = useCallback(() => {
    setShowKillConfirm(false);
    killGateway().then(refresh).catch((err: unknown) => setError(String(err)));
  }, [refresh, setError]);

  const handleApprove = useCallback(
    (key: string) => {
      approveProposal(key).then(refresh).catch((err: unknown) => setError(String(err)));
    },
    [refresh, setError],
  );

  const handleReject = useCallback(
    (key: string) => {
      rejectProposal(key).then(refresh).catch((err: unknown) => setError(String(err)));
    },
    [refresh, setError],
  );

  const handleReEnable = useCallback(
    (tag: string) => {
      reEnableTarget(tag).then(refresh).catch((err: unknown) => setError(String(err)));
    },
    [refresh, setError],
  );

  if (loading && status === null) {
    return <div data-testid="gateway-loading">{t("gateway.loading")}</div>;
  }

  const activeMode = status?.mode ?? "off";
  const targets = status?.targets ?? {};
  const isChainOk = audit?.chain_ok ?? false;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }} data-testid="gateway-page">
      <div className="banner">
        <h2>{t("gateway.title")}</h2>
        <p className="hint">{t("gateway.subtitle")}</p>
        <TopControls
          mode={activeMode}
          onSelectMode={handleModeSelect}
          onKillClick={() => setShowKillConfirm(true)}
          refresh={refresh}
          t={t}
        />
      </div>

      {pendingMode === "supervised" && (
        <ModeConfirmDialog onConfirm={handleConfirmSupervised} onCancel={() => setPendingMode(null)} t={t} />
      )}
      {showKillConfirm && (
        <KillConfirmDialog onConfirm={handleConfirmKill} onCancel={() => setShowKillConfirm(false)} t={t} />
      )}
      {error !== null && <ErrorMessage error={error} t={t} />}

      <section>
        <h3>{t("gateway.targets.title")}</h3>
        <TargetTable targets={targets} onReEnable={handleReEnable} t={t} />
      </section>

      <PolicySection mode={status?.mode} t={t} />

      <section>
        <h3>{t("gateway.pending.title")}</h3>
        <ProposalTable proposals={pending} onApprove={handleApprove} onReject={handleReject} t={t} />
      </section>

      <section>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h3>{t("gateway.audit.title")}</h3>
          <span
            className={isChainOk ? "status-chip status-chip--ok" : "status-chip status-chip--problem"}
            role="status"
            aria-live="polite"
            data-testid="gateway-chain-status"
          >
            {isChainOk ? t("gateway.audit.chainOk") : t("gateway.audit.chainBroken")}
          </span>
        </div>
        <AuditView audit={audit} t={t} />
      </section>
    </div>
  );
}
