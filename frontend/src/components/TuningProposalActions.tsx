// frontend/src/components/TuningProposalActions.tsx
/**
 * Approve, Reject and Rollback of one tuning proposal. Each button is a DisabledReason that
 * names the missing permission or the rule (a second person, an open record). Approve and
 * Rollback open a modal; Approve shows the diff and needs the "I checked the values against
 * the DCS" tick. The server re-checks everything and its refusals are shown in the modal.
 */

import { useState } from "react";
import { useAuth, useCan } from "../AuthContext";
import type { Translate } from "../findings";
import { currentActor } from "../policyRules";
import {
  approveTuningProposal,
  rejectTuningProposal,
  rollbackTuningProposal,
  type TuningProposal,
} from "../tuningApi";
import { errorText, evaluateApprove, evaluateReject, evaluateRollback } from "../tuningRules";
import { DisabledReason } from "./DisabledReason";
import { ModalDialog } from "./ModalDialog";
import { ItemsTable } from "./TuningProposalDetail";

export interface ActionsProps {
  proposal: TuningProposal;
  onChanged: (updated: TuningProposal) => void;
  /** Re-reads the list after a failed call (a timed-out approve leaves the record "applying"). */
  onRefresh?: () => void;
  t: Translate;
}

type Dialog = "approve" | "rollback" | null;
type DialogProps = ActionsProps & { onClose: () => void };

interface Rule {
  allowed: boolean;
  reason: string;
  requiredRole?: string;
}

/** Busy flag and error text of one call; `submit` runs it and hands the result to `onDone`. */
function useSubmit(
  call: () => Promise<TuningProposal>,
  onDone: (p: TuningProposal) => void,
  t: Translate,
  onFailed?: () => void,
): { busy: boolean; error: string; submit: () => void } {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = (): void => {
    setBusy(true);
    setError("");
    call()
      .then(onDone)
      .catch((failure: unknown) => {
        setError(errorText(failure, t));
        onFailed?.();
      })
      .finally(() => setBusy(false));
  };
  return { busy, error, submit };
}

function ActionError({ text }: { text: string }) {
  if (text === "") return null;
  return (
    <p className="notice notice-warning" role="alert" data-testid="tuning-action-error">
      {text}
    </p>
  );
}

function ApproveDialog({ proposal, onClose, onChanged, onRefresh, t }: DialogProps) {
  const [checked, setChecked] = useState(false);
  const done = (p: TuningProposal): void => {
    onChanged(p);
    onClose();
  };
  const { busy, error, submit } = useSubmit(() => approveTuningProposal(proposal.id), done, t, onRefresh);
  const stale = proposal.status !== "queued";
  return (
    <ModalDialog title={t("tuning.proposals.approve.title")} onClose={onClose} busy={busy} testId="tuning-approve-dialog">
      <p>{t("tuning.proposals.approve.text", { loop: proposal.loop_id })}</p>
      <ItemsTable proposal={proposal} t={t} />
      <label style={{ display: "flex", gap: 8, margin: "12px 0" }}>
        <input
          type="checkbox"
          checked={checked}
          data-testid="tuning-approve-check"
          onChange={(event) => setChecked(event.target.checked)}
        />
        {t("tuning.proposals.approve.check")}
      </label>
      <ActionError text={error} />
      <div className="toolbar">
        <DisabledReason
          disabled={!checked || busy || stale}
          reason={t(stale ? "tuning.proposals.reason.notQueued" : "tuning.proposals.approve.needCheck")}
        >
          <button type="button" data-testid="tuning-approve-confirm" onClick={submit}>
            {t("tuning.proposals.approve.confirm")}
          </button>
        </DisabledReason>
        <button type="button" onClick={onClose} disabled={busy}>
          {t("tuning.proposals.cancel")}
        </button>
      </div>
    </ModalDialog>
  );
}

function RollbackDialog({ proposal, onClose, onChanged, onRefresh, t }: DialogProps) {
  const [reason, setReason] = useState("");
  const done = (p: TuningProposal): void => {
    onChanged(p);
    onClose();
  };
  const call = () => rollbackTuningProposal(proposal.id, reason.trim() === "" ? undefined : reason.trim());
  const { busy, error, submit } = useSubmit(call, done, t, onRefresh);
  return (
    <ModalDialog title={t("tuning.proposals.rollback.title")} onClose={onClose} busy={busy} testId="tuning-rollback-dialog">
      <p>{t("tuning.proposals.rollback.text")}</p>
      <label>
        {t("tuning.proposals.rollback.reason")}
        <input
          type="text"
          maxLength={1000}
          value={reason}
          data-testid="tuning-rollback-reason"
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <ActionError text={error} />
      <div className="toolbar" style={{ marginTop: 12 }}>
        <button type="button" data-testid="tuning-rollback-confirm" disabled={busy} onClick={submit}>
          {t("tuning.proposals.rollback.confirm")}
        </button>
        <button type="button" onClick={onClose} disabled={busy}>
          {t("tuning.proposals.cancel")}
        </button>
      </div>
    </ModalDialog>
  );
}

function ActionButton({
  rule,
  testId,
  label,
  onClick,
  t,
}: {
  rule: Rule;
  testId: string;
  label: string;
  onClick: () => void;
  t: Translate;
}) {
  return (
    <DisabledReason disabled={!rule.allowed} reason={rule.reason} requiredRole={rule.requiredRole} t={t}>
      <button type="button" data-testid={testId} onClick={onClick}>
        {label}
      </button>
    </DisabledReason>
  );
}

/** The action row of the detail panel. */
export function TuningProposalActions({ proposal, onChanged, onRefresh, t }: ActionsProps) {
  const { status, user } = useAuth();
  const approve = evaluateApprove(proposal, useCan("gw.approve.tuning"), currentActor(status, user?.username), t);
  const reject = evaluateReject(proposal, useCan("gw.reject"), t);
  const rollback = evaluateRollback(proposal, useCan("gw.propose"), t);
  const [dialog, setDialog] = useState<Dialog>(null);
  const rejecting = useSubmit(() => rejectTuningProposal(proposal.id), onChanged, t, onRefresh);
  const close = (): void => setDialog(null);
  return (
    <div data-testid="tuning-actions">
      <div className="toolbar" style={{ flexWrap: "wrap", gap: 8 }}>
        <ActionButton rule={approve} testId="tuning-approve" label={t("tuning.proposals.approve")}
          onClick={() => setDialog("approve")} t={t} />
        <ActionButton rule={reject} testId="tuning-reject" label={t("tuning.proposals.reject")}
          onClick={rejecting.submit} t={t} />
        <ActionButton rule={rollback} testId="tuning-rollback" label={t("tuning.proposals.rollback")}
          onClick={() => setDialog("rollback")} t={t} />
      </div>
      <ActionError text={rejecting.error} />
      {dialog === "approve" && <ApproveDialog proposal={proposal} onChanged={onChanged} onRefresh={onRefresh} onClose={close} t={t} />}
      {dialog === "rollback" && <RollbackDialog proposal={proposal} onChanged={onChanged} onRefresh={onRefresh} onClose={close} t={t} />}
    </div>
  );
}
