// Client for the versioned site catalogue (#165): status, versions, diff, publish and approval.
// Reuses getJson/sendJson from api.ts so errors are ApiError like every other call.
import { API_PREFIX, getJson, sendJson } from "./api";

const BASE = `${API_PREFIX}/site`;

/** One stored version: immutable, with who published it and who (if anyone) approved it. */
export interface VersionMeta {
  version: number;
  sha256: string;
  author: string;
  approver: string | null;
  time: string;
  note: string;
}

/** A field whose value differs between two documents. */
export interface FieldChange {
  field: string;
  before: unknown;
  after: unknown;
}

/** The difference of one section: id-keyed entries, or plain field changes. */
export interface SectionDiff {
  added?: string[];
  removed?: string[];
  changed?: { id: string; fields: FieldChange[] }[];
  fields?: FieldChange[];
}

export interface SiteDiff {
  sections: Record<string, SectionDiff>;
  empty: boolean;
}

/** A publish request waiting for a second engineer. */
export interface PendingPublish {
  id: string;
  requested_by: string;
  requested_at: string;
  note: string;
  reasons: string[];
  diff: SiteDiff;
}

export interface SiteStatus {
  published_version: number | null;
  has_published: boolean;
  published_matches_version: boolean | null;
  has_draft: boolean;
  draft_changed: boolean;
  draft_sections: string[];
  pending: PendingPublish | null;
}

/** The result of a publish call: a stored version, or a request waiting for approval. */
export type PublishResult = { published: VersionMeta } | { pending: PendingPublish };

export const fetchSiteStatus = (): Promise<SiteStatus> => getJson(`${BASE}/status`);

export const fetchVersions = async (): Promise<VersionMeta[]> =>
  (await getJson<{ versions: VersionMeta[] }>(`${BASE}/versions`)).versions;

/** Difference from `a` to `b`; each is a version number, "published" or "draft". */
export const fetchDiff = (a: string | number, b: string | number): Promise<SiteDiff> =>
  getJson(`${BASE}/diff?a=${encodeURIComponent(String(a))}&b=${encodeURIComponent(String(b))}`);

/** Publish the draft. A 202 answer (pending approval) is returned as {pending}. */
export async function publishDraft(note: string): Promise<PublishResult> {
  const answer = await sendJson<VersionMeta | PendingPublish>("POST", `${BASE}/publish`, { note });
  return "reasons" in answer ? { pending: answer } : { published: answer };
}

export const approvePublish = (): Promise<VersionMeta> => sendJson("POST", `${BASE}/publish/approve`, {});

export const rejectPublish = (reason: string): Promise<{ rejected: string }> =>
  sendJson("POST", `${BASE}/publish/reject`, { reason });

export const discardDraft = (): Promise<{ discarded: boolean }> => sendJson("DELETE", `${BASE}/draft`, {});
