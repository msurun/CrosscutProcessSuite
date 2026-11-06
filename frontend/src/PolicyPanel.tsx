// frontend/src/PolicyPanel.tsx
/**
 * Write Policy administration panel (ADR 013, issues #46/#47).
 * Shows the live pinned policy to everyone with gateway access; users with policy.edit also get
 * the draft editor, the diff that would be pinned (server draft vs live), and Save/Pin/Reload.
 */

import { useAuth, useCan } from "./AuthContext";
import { DraftTargetsTable } from "./components/policy/DraftTargetsTable";
import { LivePolicyCard } from "./components/policy/LivePolicyCard";
import { PolicyActionToolbar } from "./components/policy/PolicyActionToolbar";
import { PolicyDiffView } from "./components/policy/PolicyDiffView";
import type { Translate } from "./findings";
import type { DraftPolicyResponse } from "./policyApi";
import { countInvalidFields, type PolicyDocument } from "./policyModel";
import { currentActor, evaluatePin, evaluateReload, evaluateSave } from "./policyRules";
import { usePolicyPanel } from "./usePolicyPanel";

export interface PolicyPanelProps {
  /** Operating mode of the gateway; undefined means unknown (Reload stays disabled). */
  gatewayMode?: string;
  t: Translate;
}

type Panel = ReturnType<typeof usePolicyPanel>;

function DraftHeader({ draft, t }: { draft: DraftPolicyResponse | null; t: Translate }) {
  if (!draft) return <p className="hint" data-testid="draft-no-server">{t("policy.draft.noDraft")}</p>;
  return (
    <div className="toolbar" style={{ flexWrap: "wrap", gap: 12, marginBottom: 8 }} data-testid="draft-meta">
      <span className="status-chip status-chip--unused" data-testid="draft-digest">
        {t("policy.draft.digest", { digest: draft.digest })}
      </span>
      <span data-testid="draft-author">{t("policy.draft.author", { author: draft.author })}</span>
      <span>{t("policy.draft.savedAt", { time: draft.saved_at })}</span>
    </div>
  );
}

function MessageBanners({ error, notice }: { error: string | null; notice: string | null }) {
  return (
    <>
      {error && (
        <div className="notice notice-warning" role="alert" data-testid="policy-server-error">
          <p>{error}</p>
        </div>
      )}
      {notice && (
        <div className="notice" role="status" data-testid="policy-server-notice">
          <p>{notice}</p>
        </div>
      )}
    </>
  );
}

function ValidationSummary({ count, t }: { count: number; t: Translate }) {
  if (count === 0) return null;
  return (
    <div className="notice notice-warning" role="alert" data-testid="policy-validation-summary">
      <p>{t("policy.validation.summary", { count })}</p>
    </div>
  );
}

interface EditorProps {
  panel: Panel;
  local: PolicyDocument;
  gatewayMode?: string;
  t: Translate;
}

function useToolbarRules(panel: Panel, local: PolicyDocument, gatewayMode: string | undefined, t: Translate) {
  const { status, user } = useAuth();
  const canEdit = useCan("policy.edit");
  const canPin = useCan("policy.pin");
  const canReload = useCan("policy.reload");
  const invalid = countInvalidFields(local);
  const { busy, data } = panel;
  return {
    invalid,
    save: evaluateSave(busy, canEdit, invalid, t),
    pin: evaluatePin({
      busy, canPin, hasDraft: data.draft !== null, dirty: panel.dirty, reviewed: panel.reviewed,
      actor: currentActor(status, user?.username), draftAuthor: data.draft?.author ?? null,
    }, t),
    reload: evaluateReload(gatewayMode, busy, canReload, t),
  };
}

function DraftEditorSection({ panel, local, gatewayMode, t }: EditorProps) {
  const rules = useToolbarRules(panel, local, gatewayMode, t);
  const draft = panel.data.draft;
  return (
    <section className="banner" data-testid="draft-editor-section">
      <h5>{t("policy.draft.title")}</h5>
      <DraftHeader draft={draft} t={t} />
      <DraftTargetsTable targets={local.targets} onChange={(tg) => panel.setLocal({ ...local, targets: tg })} t={t} />
      <ValidationSummary count={rules.invalid} t={t} />
      <PolicyActionToolbar
        mode={local.mode} onModeChange={(m) => panel.setLocal({ ...local, mode: m })}
        reviewed={panel.reviewed} onReviewedChange={panel.setReviewed} digest={draft?.digest ?? null}
        save={rules.save} pin={rules.pin} reload={rules.reload}
        onSave={panel.save} onPin={panel.pin} onReload={panel.reload} onDiscard={panel.discard} t={t}
      />
    </section>
  );
}

function PinDiffSection({ panel, t }: { panel: Panel; t: Translate }) {
  const draft = panel.data.draft;
  return (
    <section data-testid="diff-view-section">
      <h5>{t("policy.diff.title")}</h5>
      {draft
        ? <PolicyDiffView liveDoc={panel.data.live?.document ?? null} draftDoc={draft.document} t={t} />
        : <p className="hint" data-testid="diff-no-server-draft">{t("policy.diff.noServerDraft")}</p>}
    </section>
  );
}

function UnsavedDiffSection({ panel, t }: { panel: Panel; t: Translate }) {
  if (!panel.dirty) return null;
  return (
    <section data-testid="unsaved-diff-section">
      <h5>{t("policy.diff.unsavedTitle")}</h5>
      <p className="hint">{t("policy.diff.unsavedHint")}</p>
      <PolicyDiffView liveDoc={panel.data.base} draftDoc={panel.data.local} t={t} />
    </section>
  );
}

function EditorArea({ panel, gatewayMode, t }: { panel: Panel; gatewayMode?: string; t: Translate }) {
  const local = panel.data.local;
  if (!local) return null;
  return (
    <>
      <DraftEditorSection panel={panel} local={local} gatewayMode={gatewayMode} t={t} />
      <PinDiffSection panel={panel} t={t} />
      <UnsavedDiffSection panel={panel} t={t} />
    </>
  );
}

export function PolicyPanel({ gatewayMode, t }: PolicyPanelProps) {
  const { status } = useAuth();
  const canEdit = useCan("policy.edit");
  const panel = usePolicyPanel({ enabled: status !== "loading", canEdit: canEdit.allowed, t });
  const { data } = panel;
  if (status === "loading" || data.loading) {
    return <div data-testid="policy-loading">{t("policy.loading")}</div>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }} data-testid="policy-panel">
      <h4>{t("policy.title")}</h4>
      <p className="hint">{t("policy.subtitle")}</p>
      <MessageBanners error={panel.error} notice={panel.notice} />
      {data.live && <LivePolicyCard livePolicy={data.live} t={t} />}
      <EditorArea panel={panel} gatewayMode={gatewayMode} t={t} />
    </div>
  );
}
