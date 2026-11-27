// "Versions" section of the Site page (#165): draft badge, diff, publish with a note, version list and the
// pending-approval entry. Publishing changes that touch loops or controllers with active writes only
// create a request here; a second engineer approves or rejects it.
import { useCallback, useEffect, useState, type ReactElement } from "react";

import { ApiError } from "../api";
import type { Translate } from "../findings";
import {
  approvePublish,
  discardDraft,
  fetchDiff,
  fetchSiteStatus,
  fetchVersions,
  publishDraft,
  rejectPublish,
  type SiteDiff,
  type SiteStatus,
  type VersionMeta,
} from "../siteVersionsApi";
import { SiteDiffView } from "./SiteDiffView";

export interface SiteVersionsProps {
  t: Translate;
}

const errorText = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

/** Status, versions and the draft diff, reloaded on demand. */
function useVersions() {
  const [status, setStatus] = useState<SiteStatus | null>(null);
  const [versions, setVersions] = useState<VersionMeta[]>([]);
  const [draftDiff, setDraftDiff] = useState<SiteDiff | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    try {
      const s = await fetchSiteStatus();
      setStatus(s);
      setVersions(await fetchVersions());
      setDraftDiff(s.has_draft ? await fetchDiff("published", "draft") : null);
      setError("");
    } catch (e) {
      setError(errorText(e));
    }
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { status, versions, draftDiff, error, setError, reload };
}

/** The Versions panel. */
export function SiteVersions({ t }: SiteVersionsProps): ReactElement {
  const { status, versions, draftDiff, error, setError, reload } = useVersions();
  const [note, setNote] = useState("");
  const [shown, setShown] = useState<{ version: number; diff: SiteDiff } | null>(null);
  const [message, setMessage] = useState("");

  const act = async (run: () => Promise<string>) => {
    try {
      setMessage(await run());
      setNote("");
      await reload();
    } catch (e) {
      setError(errorText(e));
    }
  };
  const publish = () =>
    act(async () => {
      const result = await publishDraft(note);
      return "pending" in result ? t("versions.requested") : t("versions.published", { n: result.published.version });
    });
  const approve = () =>
    act(async () => t("versions.published", { n: (await approvePublish()).version }));
  const reject = () =>
    act(async () => {
      await rejectPublish("");
      return t("versions.rejected");
    });
  const discard = () =>
    act(async () => {
      await discardDraft();
      return t("versions.discarded");
    });
  const compare = async (v: number) =>
    setShown({ version: v, diff: await fetchDiff(v > 1 ? v - 1 : "published", v) });

  if (!status) return <p>{error || t("versions.loading")}</p>;
  const pending = status.pending;
  return (
    <section className="site-versions" data-testid="site-versions" aria-label={t("versions.title")}>
      <h3>{t("versions.title")}</h3>
      <p>
        {t("versions.current", { n: status.published_version ?? "-" })}{" "}
        <span className="badge" data-testid="draft-badge">
          {status.has_draft ? t("versions.draft") : t("versions.noDraft")}
        </span>
      </p>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {draftDiff && <SiteDiffView diff={draftDiff} t={t} />}
      {status.has_draft && status.draft_changed && !pending && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void publish();
          }}
        >
          <label>
            {t("versions.note")}
            <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
          </label>
          <button type="submit">{t("versions.publish")}</button>{" "}
          <button type="button" onClick={() => void discard()}>
            {t("versions.discard")}
          </button>
        </form>
      )}
      {pending && (
        <section aria-label={t("versions.pendingTitle")} data-testid="pending-publish" className="approval-entry">
          <h4>{t("versions.pendingTitle")}</h4>
          <p>{t("versions.pendingBy", { user: pending.requested_by, note: pending.note || "-" })}</p>
          <p>{t("versions.pendingWhy", { reasons: pending.reasons.join(", ") })}</p>
          <SiteDiffView diff={pending.diff} t={t} />
          <button type="button" onClick={() => void approve()}>
            {t("versions.approve")}
          </button>{" "}
          <button type="button" onClick={() => void reject()}>
            {t("versions.reject")}
          </button>
        </section>
      )}
      <h4>{t("versions.history")}</h4>
      {versions.length === 0 ? (
        <p>{t("versions.none")}</p>
      ) : (
        <ul>
          {versions.map((v) => (
            <li key={v.version}>
              {t("versions.row", { n: v.version, author: v.author, time: v.time, note: v.note || "-" })}
              {v.approver ? ` ${t("versions.approvedBy", { user: v.approver })}` : ""}{" "}
              <button type="button" onClick={() => void compare(v.version)}>
                {t("versions.showChanges", { n: v.version })}
              </button>
            </li>
          ))}
        </ul>
      )}
      {shown && (
        <div aria-label={t("versions.changesOf", { n: shown.version })}>
          <h4>{t("versions.changesOf", { n: shown.version })}</h4>
          <SiteDiffView diff={shown.diff} t={t} />
        </div>
      )}
    </section>
  );
}
